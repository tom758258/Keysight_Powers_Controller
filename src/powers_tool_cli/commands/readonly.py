"""Read-only, protection, snapshot, restore artifact, and logging command handlers."""

from __future__ import annotations

__all__ = [
    "_collect_log_samples",
    "_run_clear_protection",
    "_run_hardware_report",
    "_run_identify",
    "_run_log",
    "_run_protection_set",
    "_run_protection_status",
    "_run_read_only_command",
    "_run_readback",
    "_run_snapshot",
    "_run_snapshot_diff",
    "_run_status",
    "_run_validate_readonly",
    "_snapshot_diff_summary",
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
from powers_tool_core.drivers.e36312a import E36312APowerSupply
from powers_tool_core.drivers.e3646a import E3646APowerSupply
from powers_tool_core.drivers.edu36311a import EDU36311APowerSupply
from powers_tool_core.drivers.generic_scpi import GenericScpiPowerSupply
from powers_tool_core.drivers.psm2010 import PSM2010PowerSupply
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import create_power_supply, select_driver
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
OUTPUT_WRITE_POWER_SUPPLY_TYPES = (E36312APowerSupply, EDU36311APowerSupply)
STEP_TRIGGER_POWER_SUPPLY_TYPES = (E36312APowerSupply,)

from powers_tool_cli import cli_runtime
from powers_tool_cli.cli_runtime import *
from powers_tool_cli import cli_request
from powers_tool_cli.cli_request import *
from powers_tool_cli.commands.sequence_run import _cooperative_workflow_interrupt

def _run_status(args: argparse.Namespace) -> int:
    result = _run_read_only_command(
        args,
        command_label="status",
        unsupported_code="unsupported_model_for_status",
        failure_code="status_failed",
        operation=_collect_status,
    )
    exit_code, data = result
    if exit_code != 0:
        return exit_code
    data.pop("idn_raw", None)
    if args.json:
        emit_json_success(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=True),
            request=_request_for_args(args),
            data=data,
        )
        return 0

    _emit_text_lines(cli_rendering.format_read_status(data["errors"], data["outputs"]))
    return 0

def _run_readback(args: argparse.Namespace) -> int:
    result = _run_read_only_command(
        args,
        command_label="readback",
        unsupported_code="unsupported_model_for_readback",
        failure_code="readback_failed",
        operation=_collect_readback,
    )
    if result is None:
        return 1
    exit_code, data = result
    if exit_code != 0:
        return exit_code
    data.pop("idn_raw", None)
    if args.json:
        emit_json_success(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=True),
            request=_request_for_args(args),
            data=data,
        )
        return 0
    _emit_text_lines(
        cli_rendering.format_readback(
            data["resource"],
            data["channels"],
            value_to_text=_format_text_value,
        )
    )
    return 0

def _run_validate_readonly(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except SafetyConfigError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    opened = False
    try:
        with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
            opened = True
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn_raw = session.query(IDN_QUERY)
            _enforce_live_cli_scope(args, idn_raw, command="validate-readonly")
            selection = _patchable_select_driver(idn_raw)
            power_supply = selection.driver_class(session)
            if not isinstance(
                power_supply,
                (E36312APowerSupply, EDU36311APowerSupply, PSM2010PowerSupply),
            ):
                raise _ReadOnlyModelError(
                    "validate-readonly is only supported for E36312A, EDU36311A, or PSM-2010; "
                    f"found {selection.driver_class.__name__} from *IDN? response"
                )
            channels = power_supply.capabilities.channels
            for channel in channels:
                _validate_read_only_channel(power_supply, channel, command_label="validate-readonly")
            errors, read_count = _read_error_queue_from_driver(power_supply, args.max_errors)
            outputs = [
                {"channel": channel, "enabled": power_supply.output_state(channel=channel)}
                for channel in channels
            ]
            readback = [
                {
                    "channel": channel,
                    "setpoints": {
                        "voltage": power_supply.programmed_voltage(channel=channel),
                        "current": power_supply.programmed_current(channel=channel),
                    },
                }
                for channel in channels
            ]
            measurements = [
                {
                    "channel": channel,
                    "measurements": {
                        "voltage": power_supply.measure_voltage(channel=channel),
                        "current": power_supply.measure_current(channel=channel),
                    },
                }
                for channel in channels
            ]
    except _ReadOnlyModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_validate_readonly",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except _ReadOnlyChannelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
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
        code = "validate_readonly_failed" if opened else "connection_failed"
        message = (
            f"validate-readonly failed: {exc}"
            if opened
            else f"Could not open resource for validate-readonly: {exc}"
        )
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=message)
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="validate_readonly_failed",
            message=f"validate-readonly failed: {exc}",
        )

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
        "capabilities": {
            "channels": list(selection.capabilities.channels),
            "measure_channels": {
                "simulate": list(selection.capabilities.simulated_measure_channels),
                "real": list(selection.capabilities.real_measure_channels),
            },
        },
        "hardware_validation": capabilities.hardware_validation_status(
            selection.physical_identity.model_id if selection.physical_identity else None
        ),
        "errors": errors,
        "read_count": read_count,
        "outputs": outputs,
        "readback": readback,
        "measurements": measurements,
    }
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0

    _emit_text_lines(
        cli_rendering.format_validate_readonly(
            data,
            channel_order=selection.capabilities.channels,
            value_to_text=_format_text_value,
        )
    )
    return 0

def _run_read_only_command(
    args: argparse.Namespace,
    *,
    command_label: str,
    unsupported_code: str,
    failure_code: str,
    operation: Any,
) -> tuple[int, dict[str, Any]]:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except SafetyConfigError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="argument_error",
                message=str(exc),
                retryable=False,
            ),
            {},
        )

    selected_channel = "all" if getattr(args, "all", False) else getattr(args, "channel", "all")
    try:
        _read_only_channels_from_selection(selected_channel, (1, 2, 3))
    except _ReadOnlyChannelError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="argument_error",
                message=str(exc),
                retryable=False,
            ),
            {},
        )
    try:
        return 0, readonly_core.run_readonly(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except UnsupportedModelError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code=unsupported_code,
                message=str(exc),
                retryable=False,
                hardware_intent=True,
            ),
            {},
        )
    except CoreValidationError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code=_core_validation_code(exc),
                message=str(exc),
                retryable=False,
                hardware_intent=True,
            ),
            {},
        )
    except CoreIoError as exc:
        return (
            _emit_safe_io_error(
                args,
                request=request,
                execution=execution,
                code=failure_code if exc.opened else "connection_failed",
                message=str(exc),
            ),
            {},
        )

def _run_protection_status(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    try:
        data = protection_core.run_protection(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except UnsupportedModelError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="unsupported_model_for_protection_status", message=str(exc), retryable=False, hardware_intent=True)
    except CoreValidationError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code=_core_validation_code(exc), message=str(exc), retryable=False, hardware_intent=True)
    except CoreIoError as exc:
        code = "protection_status_failed" if exc.opened else "connection_failed"
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=str(exc))
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=data,
        )
        return 0
    _emit_text_lines(cli_rendering.format_protection_status(data))
    return 0

def _run_clear_protection(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    if not args.all and args.channel is None:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message="clear-protection requires --channel N or --all",
            retryable=False,
        )
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except SafetyConfigError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    try:
        data = protection_core.run_protection(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except ConfirmationRequiredError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="confirmation_required", message=str(exc), retryable=False, hardware_intent=True)
    except UnsupportedModelError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="unsupported_model_for_clear_protection", message=str(exc), retryable=False, hardware_intent=True)
    except CoreValidationError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code=_core_validation_code(exc), message=str(exc), retryable=False, hardware_intent=True)
    except CoreIoError as exc:
        code = "clear_protection_failed" if exc.opened else "connection_failed"
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=str(exc))
    except CoreExecutionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="clear_protection_failed",
            message=str(exc),
        )

    if "plan" in data:
        plan = data["plan"]
        if args.json:
            emit_json_success(command=args.command, execution=execution, request=request, data={"plan": plan})
            return 0
        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=args.dry_run)
        return 0
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0
    _emit_text_lines(
        cli_rendering.format_clear_protection_success(
            args.resource,
            data["cleared_channels"],
        )
    )
    return 0

def _run_protection_set(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    if (
        args.ovp_voltage is None
        and args.ocp is None
        and args.ocp_delay is None
        and args.ocp_delay_trigger is None
    ):
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message="protection-set requires --ovp-voltage, --ocp, --ocp-delay, or --ocp-delay-trigger",
            retryable=False,
        )
    try:
        request = _request_for_args(args)
        data = protection_core.run_protection(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except ConfirmationRequiredError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="confirmation_required", message=str(exc), retryable=False, hardware_intent=True)
    except UnsupportedModelError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="unsupported_model_for_protection_set", message=str(exc), retryable=False, hardware_intent=True)
    except CoreValidationError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code=_core_validation_code(exc),
            message=str(exc),
            retryable=False,
        )
    except CoreIoError as exc:
        code = "protection_set_failed" if exc.opened else "connection_failed"
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=str(exc))
    except CoreExecutionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="protection_set_failed",
            message=str(exc),
        )

    if "plan" in data:
        plan = data["plan"]
        if args.json:
            emit_json_success(command=args.command, execution=execution, request=request, data={"plan": plan})
            return 0
        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=args.dry_run)
        return 0
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0
    _emit_text_lines(
        cli_rendering.format_protection_set_success(
            args.resource,
            data["channels"],
            value_to_text=_format_text_value,
        )
    )
    return 0

def _run_identify(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except SafetyConfigError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="argument_error", message=str(exc), retryable=False)

    try:
        data = instrument_io_core.run_instrument_io(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except CoreValidationError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except CoreIoError as exc:
        code = "identify_failed" if exc.opened else "connection_failed"
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=str(exc))
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0
    _emit_text_lines(cli_rendering.format_identify(args.resource, data))
    return 0

def _run_snapshot(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    try:
        data = snapshot_core.run_snapshot(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except UnsupportedModelError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="unsupported_model_for_snapshot", message=str(exc), retryable=False, hardware_intent=True)
    except CoreValidationError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code=_core_validation_code(exc), message=str(exc), retryable=False, hardware_intent=True)
    except CoreIoError as exc:
        code = "snapshot_failed" if exc.opened else "connection_failed"
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=str(exc))
    persisted_snapshot = dict(data)
    comparison = None
    if args.compare:
        try:
            comparison = _compare_snapshot_data(data, args.compare, _snapshot_compare_tolerances(args))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return _emit_cli_error(
                args,
                request=_request_for_args(args),
                error_type="validation",
                code="snapshot_compare_failed",
                message=f"Could not compare snapshot: {exc}",
                retryable=False,
                hardware_intent=True,
            )
        data["comparison"] = comparison
    if args.redact_resource:
        data["resource"] = "<redacted>"
        data["resource_redacted"] = True
        persisted_snapshot["resource"] = "<redacted>"
        persisted_snapshot["resource_redacted"] = True
    if args.snapshot_json:
        try:
            _write_json_file_atomic(args.snapshot_json, persisted_snapshot)
        except OSError as exc:
            return _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="snapshot_write_failed",
                message=f"Could not write raw snapshot JSON: {exc}",
                retryable=False,
                hardware_intent=True,
            )
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=data,
        )
        return 0 if comparison is None or comparison["passed"] else 3
    _emit_text_lines(cli_rendering.format_snapshot(data, comparison=comparison))
    return 0 if comparison is None or comparison["passed"] else 3

def _run_snapshot_diff(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=False)
    try:
        before = _load_snapshot_document(args.before)
        after = _load_snapshot_document(args.after)
        differences = _diff_snapshots(before, after)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    data = {
        "before": args.before,
        "after": args.after,
        "changed": bool(differences),
        "change_count": len(differences),
        "differences": differences,
    }
    if args.summary:
        data["summary"] = _snapshot_diff_summary(differences)
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0
    _emit_text_lines(cli_rendering.format_snapshot_diff(data, summary=args.summary))
    return 0

def _run_hardware_report(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=False)
    try:
        report = _build_hardware_report(args)
        _write_hardware_report_files(report, args.report_json, args.summary_md)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    data = {
        "report_json": args.report_json,
        "summary_md": args.summary_md,
        "report": report,
    }
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0
    _emit_text_lines(
        cli_rendering.format_hardware_report_success(
            args.report_json,
            args.summary_md,
            report,
        )
    )
    return 0

def _snapshot_diff_summary(differences: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for difference in differences:
        category = str(difference.get("category", "unknown"))
        summary[category] = summary.get(category, 0) + 1
    return dict(sorted(summary.items()))

def _run_log(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)

    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except (SafetyConfigError, ValueError, CoreValidationError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    try:
        result = _collect_log_samples(args, manager, backend=args.backend, timeout_ms=args.timeout_ms)
    except CoreValidationError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code=(
                "unsupported_model_for_log"
                if isinstance(exc, UnsupportedModelError)
                else _core_validation_code(exc)
            ),
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except (CoreIoError, OSError, VisaConnectionError, ValueError) as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="log_failed",
            message=f"log failed: {exc}",
        )

    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=result,
        )
        return 0

    _emit_text_lines(cli_rendering.format_log_success(args.resource, args.csv, result))
    return 0

def _collect_log_samples(
    args: argparse.Namespace,
    resource_manager: SimulatedResourceManager | None,
    *,
    backend: str | None,
    timeout_ms: int,
) -> dict[str, Any]:
    request = validate_request_admission(_target_core_request_for_args(args))
    csv_path = Path(args.csv)
    result: dict[str, Any] | None = None
    csv_file: Any = None
    jsonl_file: Any = None
    writer: csv.DictWriter | None = None

    def opener(
        resource: str,
        manager: Any = None,
        *,
        backend: str | None,
        timeout_ms: int,
        serial_options: SerialOptions | None = None,
        serial_remote: bool = False,
        serial_local_on_close: bool = False,
    ) -> Any:
        return _open_resource(
            resource,
            manager if manager is not None else resource_manager,
            backend=backend,
            timeout_ms=timeout_ms,
            serial_options=serial_options,
            serial_remote=serial_remote,
            serial_local_on_close=serial_local_on_close,
            scpi_logger=_connection_scpi_logger_for_args(args),
        )

    def open_writers() -> None:
        nonlocal csv_file, jsonl_file, writer
        if writer is not None:
            return
        if csv_path.parent != Path("."):
            csv_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if args.append else "w"
        write_header = (
            (not args.append)
            or (not csv_path.exists())
            or csv_path.stat().st_size == 0
        )
        csv_file = csv_path.open(mode, newline="", encoding="utf-8")
        writer = csv.DictWriter(csv_file, fieldnames=LOG_CSV_FIELDS)
        if write_header:
            writer.writeheader()
            csv_file.flush()
        jsonl_file = _open_jsonl_log(args)

    def report_sample(row: dict[str, Any]) -> None:
        open_writers()
        if writer is None or csv_file is None:
            raise CoreIoError("log telemetry writer did not initialize")
        writer.writerow(row)
        csv_file.flush()
        if jsonl_file is not None:
            jsonl_file.write(
                json.dumps({"event": "sample", "sample": row}, sort_keys=True)
                + "\n"
            )
            jsonl_file.flush()

    try:
        with _cooperative_workflow_interrupt() as stop_event:
            try:
                result = _patchable_run_core_command(
                    request,
                    opener=opener,
                    stop_requested=stop_event.is_set,
                    sleep=time.sleep,
                    scpi_logger=_log_scpi if args.log_scpi else None,
                    sample_reporter=report_sample,
                )
            except CommandCancelled as exc:
                result = dict(exc.data)
                result["stopped"] = True
                result["stop_reason"] = "interrupted"
    finally:
        if jsonl_file is not None:
            if result is not None:
                jsonl_file.write(
                    json.dumps(
                        {
                            "event": "summary",
                            "samples_written": result["samples_written"],
                            "channels": result["channels"],
                            "stopped": result["stopped"],
                            "stop_reason": result["stop_reason"],
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
                jsonl_file.flush()
            jsonl_file.close()
        if csv_file is not None:
            csv_file.close()

    if result is None:
        raise CoreIoError("log failed without a collection result")
    return {
        **result,
        "csv": args.csv,
        "jsonl": args.jsonl,
        "append": args.append,
    }

