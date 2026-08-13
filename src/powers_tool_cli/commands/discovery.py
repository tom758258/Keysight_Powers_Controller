"""Discovery and generic instrument I/O command handlers."""

from __future__ import annotations

__all__ = [
    "_run_clear",
    "_run_error",
    "_run_list_resources",
    "_run_measure",
    "_run_measure_all",
    "_run_verify",
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

def _run_list_resources(args: argparse.Namespace) -> int:
    execution = _execution_for_args(args, hardware_intent=args.live_only)
    request = _request_for_args(args)
    try:
        data = discovery_core.run_discovery(
            _target_core_request_for_args(args),
            resource_lister=_core_lister_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except CoreIoError as exc:
        message = str(exc)
        if args.json:
            emit_json_error(
                command="list-resources",
                execution=execution,
                request=request,
                error_type="connection",
                code="resource_list_failed",
                message=message,
                retryable=True,
            )
        else:
            print(message, file=sys.stderr)
        return 1

    if args.live_only:
        if args.json:
            emit_json_success(
                command="list-resources",
                execution=execution,
                request=request,
                data=data,
            )
            return 0

        _emit_text_lines(
            cli_rendering.format_list_resources(data["resources"], live_only=True)
        )
        return 0

    if args.json:
        emit_json_success(
            command="list-resources",
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    _emit_text_lines(
        cli_rendering.format_list_resources(data["resources"], live_only=False)
    )
    return 0

def _run_verify(args: argparse.Namespace) -> int:
    execution = _execution_for_args(args, hardware_intent=True)
    request = _request_for_args(args)
    try:
        data = discovery_core.run_discovery(
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
    except CoreIoError:
        message = f"Could not verify VISA resource: {args.resource}"
        if args.json:
            emit_json_error(
                command="verify",
                execution=execution,
                request=request,
                error_type="connection",
                code="resource_unreachable",
                message=message,
                retryable=True,
            )
        else:
            print(message, file=sys.stderr)
        return 1

    if args.json:
        emit_json_success(
            command="verify",
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    _emit_text_lines(cli_rendering.format_verify(data["resource"]["idn"]["raw"]))
    return 0

def _run_clear(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    try:
        data = instrument_io_core.run_instrument_io(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except CoreIoError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="status_clear_failed",
            message=f"Could not clear instrument status for {args.resource}: {exc}",
        )

    if args.dry_run:
        plan = data["plan"]
        if args.json:
            emit_json_success(
                command="clear",
                execution=execution,
                request=request,
                data={"plan": plan},
            )
            return 0

        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=True)
        return 0

    if args.json:
        emit_json_success(
            command="clear",
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    _emit_text_lines(cli_rendering.format_clear_success(args.resource))
    return 0

def _run_error(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)

    try:
        data = instrument_io_core.run_instrument_io(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except CoreIoError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="error_query_failed",
            message=f"Could not query error queue for {args.resource}: {exc}",
        )

    if args.json:
        emit_json_success(
            command="error",
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    _emit_text_lines(cli_rendering.format_error_queue(data["errors"]))
    return 0

def _run_measure(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    try:
        data = instrument_io_core.run_instrument_io(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except UnsupportedChannelError as exc:
        if args.json:
            emit_json_error(
                command="measure",
                execution=execution,
                request=request,
                error_type="validation",
                code="argument_error",
                message=str(exc),
                retryable=False,
            )
        else:
            print(str(exc), file=sys.stderr)
        return 2
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
    except CoreIoError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="measurement_failed",
            message=f"Could not measure voltage/current for {args.resource}: {exc}",
        )

    if args.json:
        emit_json_success(
            command="measure",
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    _emit_text_lines(
        cli_rendering.format_measure(
            data["measurements"],
            value_to_text=_format_text_value,
        )
    )
    return 0

def _run_measure_all(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
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
        data = readonly_core.run_readonly(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
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
    except CoreIoError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="measure_all_failed" if exc.opened else "connection_failed",
            message=str(exc),
        )

    if not args.dry_run:
        idn_raw = data.pop("idn_raw", None)
        if not isinstance(idn_raw, str):
            if args.json:
                emit_json_error(
                    command=args.command,
                    execution=execution,
                    request=request,
                    error_type="execution",
                    code="invalid_core_result",
                    message="measure-all Core result did not include a valid observed IDN string.",
                    retryable=False,
                )
            else:
                print("measure-all Core result did not include a valid observed IDN string.", file=sys.stderr)
            return 3
        observed = parse_idn(idn_raw)
        data["idn"] = {
            "manufacturer": observed.manufacturer,
            "model": observed.model,
            "serial": observed.serial,
            "firmware": observed.firmware,
            "parse_ok": observed.parse_ok,
        }
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    _emit_text_lines(
        cli_rendering.format_measure_all(
            data["channels"],
            value_to_text=_format_text_value,
        )
    )
    return 0

