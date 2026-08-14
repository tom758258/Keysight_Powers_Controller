"""Doctor, capabilities, and safety inspection command handlers."""

from __future__ import annotations

__all__ = [
    "_run_capabilities",
    "_run_doctor",
    "_run_safety_inspect",
    "_run_worker",
]

import argparse
import csv
import importlib.metadata
import json
import math
import os
import platform
import signal
import sys
import tempfile
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import powers_tool_core.capabilities as capabilities
import powers_tool_core.discovery as discovery_core
import powers_tool_core.instrument_io as instrument_io_core
import powers_tool_core.operations as operations
import powers_tool_core.protection as protection_core
import powers_tool_core.ramp_list as ramp_list_core
import powers_tool_core.readonly as readonly_core
import powers_tool_core.restore as restore_core
import powers_tool_core.sequence as sequence
import powers_tool_core.snapshot as snapshot_core
import powers_tool_core.trigger as trigger_core
import powers_tool_core.validation as validation
from powers_tool_cli.cli_io import (
    JsonSaveError,
    SCHEMA_VERSION,
    emit_json_error,
    emit_json_success,
    set_json_save_path,
    set_json_start_time,
)
from powers_tool_cli import cli_rendering
from powers_tool_cli.lifecycle_client import (
    run_send_command as _run_send_command,
    run_wait_ready_client as _run_wait_ready_client,
    run_worker_status_client as _run_worker_status_client,
    run_worker_stop_client as _run_worker_stop_client,
)
from powers_tool_cli.runtime_mapping import (
    execution_for_args as _execution_for_args,
    mode_for_args as _mode_for_args,
    runtime_identity_for_args as _runtime_identity_for_args,
    serial_options_for_args as _serial_options_for_args,
    support_policy_mode_for_args as _support_policy_mode_for_args,
    validation_execution_from_argv as _validation_execution_from_argv,
    with_serial_request_fields as _with_serial_request_fields,
)
from powers_tool_cli.request_primitives import (
    channel_from_argv as _channel_from_argv,
    completion_pins_from_argv as _completion_pins_from_argv,
    completion_request_fields_from_argv as _completion_request_fields_from_argv,
    drop_none_setpoints as _drop_none_setpoints,
    duration_from_argv as _duration_from_argv,
    float_list_from_argv as _float_list_from_argv,
    int_from_argv as _int_from_argv,
    int_option_from_argv as _int_option_from_argv,
    json_safe_number as _json_safe_number,
    max_errors_from_argv as _max_errors_from_argv,
    number_from_argv as _number_from_argv,
    option_value as _option_value,
    pin_from_argv as _pin_from_argv,
    pins_from_argv as _pins_from_argv,
    status_channel_from_argv as _status_channel_from_argv,
    timeout_from_argv as _timeout_from_argv,
    trigger_pins_for_args as _trigger_pins_for_args,
    with_serial_request_fields_from_argv as _with_serial_request_fields_from_argv,
    write_verification_request_fields as _write_verification_request_fields,
    write_verification_request_fields_from_argv as _write_verification_request_fields_from_argv,
)
from powers_tool_core.connection import DEFAULT_TIMEOUT_MS, SerialOptions, list_resources, normalize_serial_termination, open_resource
from powers_tool_core.command_runner import (
    run_core_command,
    validate_request_admission,
    workflow_execution_summary,
)
from powers_tool_core.command_contract import command_parameter_names
from powers_tool_core.core import (
    CommandCancelled,
    ConfirmationRequiredError,
    CoreExecutionError,
    CoreIoError,
    CoreValidationError,
    CoreVerificationError,
    OperationRequest,
    RuntimeOptions,
    SequenceRequest,
    StopCleanupError,
    TriggerInterrupted,
    TriggerRequest,
    TriggerWaitTimeout,
    UnsupportedChannelError,
    UnsupportedModelError,
)
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.identity import (
    IDENTITY_INDEXES,
    IdentityResolutionError,
    canonical_physical_model_id,
    resolve_physical_model_identity,
)
from powers_tool_core.live_support import enforce_live_support_for_idn
from powers_tool_core.support_policy import (
    LiveSupportPolicyError,
    SUPPORT_POLICY_MODE_PRODUCT,
    SUPPORT_POLICY_MODE_VALIDATION,
)
from powers_tool_core.telemetry import TELEMETRY_ROW_FIELDS
from powers_tool_core.model_resolution import validate_live_expected_model
from powers_tool_core.models import parse_idn, resource_interface
from powers_tool_core.safety import (
    SafetyConfigError,
    SafetyLimits,
    SafetyValidationError,
    load_safety_config_document,
    resolve_safety_config,
    validate_channel,
    validate_setpoint,
)
from powers_tool_core.testing.simulator import SimulatedResourceManager
from powers_tool_core.transport import dry_run_plan

IDN_QUERY = "*IDN?"
CLEAR_STATUS_COMMAND = "*CLS"
ERROR_QUERY = "SYST:ERR?"
MEASURE_VOLTAGE_QUERY = "MEAS:VOLT?"
MEASURE_CURRENT_QUERY = "MEAS:CURR?"
PROGRAMMED_VOLTAGE_QUERY = "VOLT?"
PROGRAMMED_CURRENT_QUERY = "CURR?"
OVP_TRIP_QUERY = "VOLT:PROT:TRIP?"
OCP_TRIP_QUERY = "CURR:PROT:TRIP?"
LOG_CSV_FIELDS = TELEMETRY_ROW_FIELDS
from powers_tool_cli import cli_runtime
from powers_tool_cli.cli_runtime import *
from powers_tool_cli import cli_request
from powers_tool_cli.cli_request import *

def _run_worker(args: argparse.Namespace) -> int:
    from powers_tool_cli.worker import run_worker
    return run_worker(args)

def _run_doctor(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=bool(args.resource))
    manager = _resource_manager_for_args(args)
    pyvisa_available = importlib.util.find_spec("pyvisa") is not None
    data: dict[str, Any] = {
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "package": {"name": "powers-tool-cli", "version": _package_version()},
        "pyvisa": {"available": pyvisa_available, "backend": args.backend},
        "simulator": {
            "available": True,
            "resources": list(SimulatedResourceManager().list_resources()),
        },
        "real_resource_manager": {
            "checked": not args.simulate,
            "available": None,
            "error": None,
        },
        "resource": None,
        "environment": {
            "cwd": str(Path.cwd()),
            "venv": {
                "active": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
                "prefix": sys.prefix,
            },
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
            },
            "python": {"executable": sys.executable},
        },
    }
    if not args.simulate:
        try:
            _list_resources(None, backend=args.backend)
            data["real_resource_manager"]["available"] = True
        except VisaConnectionError as exc:
            data["real_resource_manager"]["available"] = False
            data["real_resource_manager"]["error"] = str(exc)

    if args.resource:
        try:
            with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
                session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
                idn = session.query(IDN_QUERY)
                _enforce_live_cli_scope(args, idn, command="doctor")
            data["resource"] = _resource_payload(
                args.resource,
                simulated=args.simulate,
                reachable=True,
                idn_raw=idn,
            )
        except CoreValidationError as exc:
            return _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code=_core_validation_code(exc),
                message=str(exc),
                retryable=False,
                hardware_intent=True,
            )
        except VisaConnectionError as exc:
            return _emit_safe_io_error(
                args,
                request=request,
                execution=execution,
                code="doctor_resource_failed",
                message=f"doctor resource check failed: {exc}",
            )

    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
    else:
        _emit_text_lines(
            cli_rendering.format_doctor(data, pyvisa_available=pyvisa_available)
        )
    return 0

def _run_capabilities(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    selected_command = getattr(args, "selected_command", None)
    if selected_command and selected_command not in capabilities.known_capability_commands():
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=f"unknown command: {selected_command}",
            retryable=False,
        )
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn_raw = session.query(IDN_QUERY)
            _enforce_live_cli_scope(args, idn_raw, command="capabilities")
        selection = _patchable_select_driver(idn_raw)
    except SafetyConfigError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="argument_error", message=str(exc), retryable=False)
    except CoreValidationError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code=_core_validation_code(exc),
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except VisaConnectionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="capabilities_failed",
            message=f"capabilities failed: {exc}",
        )

    caps = selection.capabilities
    static_groups = capabilities.capabilities_static_groups()
    data = {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "driver": {
            "class": selection.driver_class.__name__,
            "reason": selection.reason,
        },
        "channels": list(caps.channels),
        "measure_channels": {
            "simulate": list(caps.simulated_measure_channels),
            "real": list(caps.real_measure_channels),
        },
        **static_groups,
        "hardware_validation": capabilities.hardware_validation_status(
            selection.physical_identity.model_id if selection.physical_identity else None
        ),
        "command_support": capabilities.command_support(
            selection.physical_identity.model_id if selection.physical_identity else None
        ),
        "electrical_ratings": caps.electrical_ratings.to_dict() if caps.electrical_ratings else None,
    }
    if selected_command:
        support = data["command_support"]
        data["selected_command"] = {"name": selected_command, **support[selected_command]}
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
    else:
        _emit_text_lines(cli_rendering.format_capabilities(data))
    return 0

def _run_safety_inspect(args: argparse.Namespace) -> int:
    args.command = "safety inspect"
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=False)
    try:
        if args.safety_config is None:
            raise SafetyConfigError("safety inspect requires --safety-config")
        model_id = canonical_physical_model_id(args.model)
        model_name = (
            IDENTITY_INDEXES.models_by_id[model_id].canonical_model
            if model_id is not None
            else None
        )
        resolution = resolve_safety_config(
            args.safety_config,
            resource=args.resource,
            resource_alias=args.resource_alias,
            model=model_name,
            channel=args.channel,
        )
    except (SafetyConfigError, IdentityResolutionError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )
    limits = resolution.limits
    data = {
        "resource": resolution.resource,
        "resource_alias": resolution.resource_alias,
        "model_id": model_id,
        "channel": args.channel,
        "limits": _safety_limits_payload(limits),
        "sources": resolution.sources or {},
        "output_affecting_allowed": _output_affecting_allowed(args.channel, limits),
    }
    from powers_tool_core.electrical_ratings import ratings_for_model_id
    from powers_tool_core.setpoint_limits import effective_setpoint_limits

    ratings = ratings_for_model_id(args.model)
    official = ratings.channel(args.channel) if ratings is not None and isinstance(args.channel, int) else None
    effective = (
        effective_setpoint_limits(
            model=args.model,
            channel=args.channel,
            electrical_ratings=ratings,
            safety_limits=limits,
        )
        if isinstance(args.channel, int)
        else None
    )
    data["official_rating"] = official.to_dict() if official else None
    data["effective_limits"] = effective.to_dict() if effective else None
    if args.explain:
        data["explanation"] = _safety_explanation_for_args(args, limits, resolution.sources or {})
    if args.json:
        emit_json_success(command="safety inspect", execution=execution, request=request, data=data)
    else:
        _emit_text_lines(cli_rendering.format_safety_inspect(data))
    return 0

