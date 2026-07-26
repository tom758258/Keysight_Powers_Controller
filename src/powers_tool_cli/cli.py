"""Safe command line interface for supported DC power supplies."""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import importlib.util
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
from powers_tool_cli.cli_parser import (
    JsonCliArgumentParser,
    _add_backend_argument,
    _add_channel_or_all_argument,
    _add_completion_pulse_arguments,
    _add_dry_run_argument,
    _add_duration_argument,
    _add_json_argument,
    _add_lifecycle_format_arguments,
    _add_lifecycle_timeout_argument,
    _add_lifecycle_url_argument,
    _add_model_argument,
    _add_output_resource_arguments,
    _add_ramp_completion_pulse_arguments,
    _add_resource_argument,
    _add_safety_config_argument,
    _add_serial_arguments,
    _add_simulate_argument,
    _add_timeout_argument,
    _add_trigger_restore_argument,
    _add_trigger_wait_arguments,
    _add_validation_support_policy_argument,
    _add_write_verification_arguments,
    _apply_channel,
    _bool_list,
    _channels_list,
    _e36312a_channel,
    _e36312a_channel_or_all,
    _float_list,
    _lifecycle_timeout_ms,
    _log_channel,
    _loop_count,
    _nonnegative_int,
    _output_channel,
    _positive_channel,
    _positive_duration_ms,
    _positive_float,
    _positive_int,
    _positive_max_errors,
    _positive_max_reads,
    _safe_off_channel,
    _status_channel,
    _trigger_pin,
    _trigger_pins_list,
    _trigger_poll_ms,
    build_parser as _build_parser,
    configure_parser_error_context,
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
COMMAND_NAMES = frozenset(
    {
        "list-resources",
        "verify",
        "clear",
        "error",
        "measure",
        "measure-all",
        "set",
        "output-on",
        "output-off",
        "safe-off",
        "output-state",
        "cycle-output",
        "apply",
        "ramp",
        "ramp-list",
        "smoke-output",
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
        "read-status",
        "validate-readonly",
        "readback",
        "protection-status",
        "protection-set",
        "clear-protection",
        "identify",
        "snapshot",
        "snapshot-diff",
        "hardware-report",
        "restore-from-snapshot",
        "log",
        "sequence",
        "doctor",
        "capabilities",
        "safety",
        "worker",
        "send-command",
        "status",
        "stop",
        "wait-ready",
    }
)

LOG_CSV_FIELDS = (
    "timestamp",
    "resource",
    "resource_alias",
    "model",
    "serial",
    "channel",
    "programmed_voltage",
    "programmed_current",
    "measured_voltage",
    "measured_current",
    "output_enabled",
    "errors",
)


OUTPUT_WRITE_POWER_SUPPLY_TYPES = (E36312APowerSupply, EDU36311APowerSupply)
STEP_TRIGGER_POWER_SUPPLY_TYPES = (E36312APowerSupply,)


class _MeasureChannelUnsupported(ValueError):
    """Raised when a measure channel is outside conservative driver capability."""


class _InvalidCoreResult(ValueError):
    """Raised when a successful Core result violates the CLI adapter contract."""


class _ScpiLoggingSession:
    """Session proxy that logs SCPI traffic while preserving driver behavior."""

    def __init__(self, resource: str, session: Any) -> None:
        self._resource = resource
        self._session = session

    def write(self, command: str) -> Any:
        _log_scpi(self._resource, ">>", command)
        return self._session.write(command)

    def query(self, command: str) -> str:
        _log_scpi(self._resource, ">>", command)
        response = self._session.query(command)
        _log_scpi(self._resource, "<<", response)
        return response

    def close(self) -> None:
        self._session.close()


def build_parser() -> argparse.ArgumentParser:
    configure_parser_error_context(
        command_from_argv=_command_from_argv,
        validation_execution_from_argv=_validation_execution_from_argv,
        request_from_argv=_request_from_argv,
    )
    return _build_parser(
        _package_version,
        run_list_resources=_run_list_resources,
        run_verify=_run_verify,
        run_clear=_run_clear,
        run_error=_run_error,
        run_measure=_run_measure,
        run_measure_all=_run_measure_all,
        run_status=_run_status,
        run_validate_readonly=_run_validate_readonly,
        run_readback=_run_readback,
        run_protection_status=_run_protection_status,
        run_protection_set=_run_protection_set,
        run_clear_protection=_run_clear_protection,
        run_identify=_run_identify,
        run_snapshot=_run_snapshot,
        run_snapshot_diff=_run_snapshot_diff,
        run_hardware_report=_run_hardware_report,
        run_restore_from_snapshot=_run_restore_from_snapshot,
        run_log=_run_log,
        run_doctor=_run_doctor,
        run_capabilities=_run_capabilities,
        run_safety_inspect=_run_safety_inspect,
        run_worker=_run_worker,
        run_output_plan=_run_output_plan,
        run_core_trigger=_run_core_trigger,
        run_sequence_command=_run_sequence,
        run_ramp_list_command=_run_ramp_list,
    )


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = tuple(sys.argv[1:] if argv is None else argv)
    set_json_start_time(time.perf_counter())
    set_json_save_path(_json_save_path_from_argv(raw_argv))
    JsonCliArgumentParser.active_argv = raw_argv
    try:
        args = build_parser().parse_args(raw_argv)
    except JsonSaveError as exc:
        set_json_save_path(None)
        emit_json_error(
            command=_command_from_argv(raw_argv),
            execution=_validation_execution_from_argv(raw_argv),
            request=_request_from_argv(_command_from_argv(raw_argv), raw_argv),
            error_type="connection",
            code="json_save_failed",
            message=f"Could not save JSON: {exc}",
            retryable=False,
        )
        set_json_start_time(None)
        return 1
    except SystemExit as exc:
        exit_code = _exit_code(exc)
        set_json_save_path(None)
        set_json_start_time(None)
        return exit_code
    finally:
        JsonCliArgumentParser.active_argv = ()
    if getattr(args, "json", False):
        if "--format" in raw_argv and getattr(args, "format", None) != "json":
            print("--json conflicts with --format text", file=sys.stderr)
            set_json_start_time(None)
            return 2
        if hasattr(args, "format"):
            args.format = "json"
    setattr(args, "_raw_argv", raw_argv)
    if getattr(args, "save_json", None) is not None and not args.json:
        emit_json_error(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=False),
            request=_request_for_args(args),
            error_type="validation",
            code="argument_error",
            message="--save-json requires --json",
            retryable=False,
        )
        set_json_start_time(None)
        return 2
    if (
        args.command == "snapshot"
        and getattr(args, "save_json", None) is not None
        and getattr(args, "snapshot_json", None) is not None
        and Path(args.save_json).resolve() == Path(args.snapshot_json).resolve()
    ):
        emit_json_error(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=False),
            request=_request_for_args(args),
            error_type="validation",
            code="argument_error",
            message="--save-json and --snapshot-json must use different paths",
            retryable=False,
        )
        set_json_start_time(None)
        return 2
    set_json_save_path(getattr(args, "save_json", None))
    try:
        return int(args.func(args))
    except CoreValidationError as exc:
        set_json_save_path(None)
        emit_json_error(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=False),
            request=_request_from_argv(args.command, raw_argv),
            error_type="validation",
            code=_core_validation_code(exc),
            message=str(exc),
            retryable=False,
        )
        return 2
    except JsonSaveError as exc:
        set_json_save_path(None)
        emit_json_error(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=False),
            request=_request_for_args(args),
            error_type="connection",
            code="json_save_failed",
            message=f"Could not save JSON: {exc}",
            retryable=False,
        )
        set_json_start_time(None)
        return 1
    finally:
        set_json_save_path(None)
        set_json_start_time(None)
        sys.modules.pop("powers_tool_cli", None)


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


def _run_core_trigger(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        if args.command == "trigger-step":
            _validate_trigger_step_args(args)
        core_request = _trigger_request_for_args(args)
    except (SafetyConfigError, ValueError, OSError, CoreValidationError) as exc:
        code = "trigger_list_too_long" if args.command == "trigger-list" and "at most 100" in str(exc) else "argument_error"
        return _emit_cli_error(args, request=request, error_type="validation", code=code, message=str(exc), retryable=False)

    if args.command == "trigger-fire" and getattr(args, "wait_complete", False) and getattr(args, "channel", None) is None:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message="trigger-fire --wait-complete requires --channel for interrupted cleanup",
            retryable=False,
        )

    def opener(resource: str, *, backend: str | None = None, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        return _open_resource(resource, manager, backend=backend, timeout_ms=timeout_ms)

    try:
        data = trigger_core.run_trigger(core_request, opener=opener, sleep=time.sleep, scpi_logger=_log_scpi)
    except UnsupportedModelError as exc:
        code = "unsupported_model_for_trigger_pulse" if args.command == "trigger-pulse" else "unsupported_model_for_trigger"
        return _emit_cli_error(args, request=request, error_type="validation", code=code, message=str(exc), retryable=False, hardware_intent=True)
    except TriggerWaitTimeout as exc:
        if args.json:
            emit_json_error(
                command=args.command,
                execution=execution,
                request=request,
                error_type="timeout",
                code="wait_timeout",
                message=str(exc),
                retryable=False,
                data={"trigger": exc.trigger} if exc.trigger is not None else None,
            )
        else:
            print(str(exc), file=sys.stderr)
        return 1
    except TriggerInterrupted as exc:
        if args.json:
            emit_json_error(
                command=args.command,
                execution=execution,
                request=request,
                error_type="interrupted",
                code="interrupted",
                message=str(exc),
                retryable=True,
                data={"trigger": exc.trigger} if exc.trigger is not None else None,
            )
        else:
            print(str(exc), file=sys.stderr)
        return 130
    except CoreValidationError as exc:
        code = (
            "trigger_native_unsupported"
            if "disabled" in str(exc) or "native" in str(exc)
            else _core_validation_code(exc)
        )
        return _emit_cli_error(args, request=request, error_type="validation", code=code, message=str(exc), retryable=False, hardware_intent=True)
    except CoreIoError as exc:
        failure_codes = {
            "trigger-pulse": "trigger_pulse_failed",
            "trigger-status": "trigger_status_failed",
            "trigger-step": "trigger_config_failed",
            "trigger-list": "trigger_config_failed",
            "trigger-fire": "trigger_fire_failed",
            "trigger-abort": "trigger_config_failed",
        }
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code=failure_codes[args.command] if exc.opened else "connection_failed",
            message=str(exc),
        )
    except CoreExecutionError as exc:
        failure_codes = {
            "trigger-pulse": "trigger_pulse_failed",
            "trigger-status": "trigger_status_failed",
            "trigger-step": "trigger_config_failed",
            "trigger-list": "trigger_config_failed",
            "trigger-fire": "trigger_fire_failed",
            "trigger-abort": "trigger_config_failed",
        }
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code=failure_codes[args.command],
            message=str(exc),
            data={"trigger": exc.trigger} if exc.trigger is not None else None,
        )

    resource_data = _core_trigger_resource_data(args, data)
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=resource_data)
        return 0
    _print_core_trigger_result(args, resource_data)
    return 0


def _run_trigger_pulse(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    pins = _trigger_pins_for_args(args)

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

    scpi = _trigger_pulse_scpi(
        pins,
        args.polarity,
        args.channel,
        exclusive_pins=args.exclusive_pins,
    )
    if args.dry_run:
        plan = dry_run_plan(
            command=args.command,
            resource=args.resource,
            scpi=scpi,
            description=(
                "Preview configuring an E36312A rear digital trigger output pin "
                "then arming a channel with TRIG:SOUR BUS and INIT before "
                "issuing *TRG. *TRG may also trigger any already armed "
                "BUS-triggered behavior on the instrument."
            ),
        )
        if args.json:
            emit_json_success(
                command=args.command,
                execution=execution,
                request=request,
                data={"plan": plan},
            )
            return 0
        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=True)
        return 0

    opened = False
    try:
        with _open_resource(
            args.resource,
            manager,
            backend=args.backend,
            timeout_ms=args.timeout_ms,
        ) as instrument:
            opened = True
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _TriggerPulseModelError(
                    "trigger-pulse is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            voltage = power_supply.programmed_voltage(channel=args.channel)
            current = power_supply.programmed_current(channel=args.channel)
            if args.exclusive_pins:
                power_supply.clear_trigger_output_pins(except_pins=pins)
            power_supply.configure_trigger_output_pins(pins, args.polarity)
            power_supply.enable_trigger_output_bus(True)
            power_supply.set_triggered_current(channel=args.channel, current=current)
            power_supply.set_triggered_voltage(channel=args.channel, voltage=voltage)
            power_supply.set_current_trigger_mode_step(args.channel)
            power_supply.set_voltage_trigger_mode_step(args.channel)
            power_supply.configure_output_trigger_source_bus(args.channel)
            power_supply.trigger_pulse(channel=args.channel)
            _raise_on_instrument_errors(power_supply, "trigger-pulse")
    except _TriggerPulseModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_trigger_pulse",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except VisaConnectionError as exc:
        code = "trigger_pulse_failed" if opened else "connection_failed"
        message = (
            f"trigger-pulse failed: {exc}"
            if opened
            else f"Could not open resource for trigger-pulse: {exc}"
        )
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code=code,
            message=message,
        )
    except ValueError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="trigger_pulse_failed",
            message=f"trigger-pulse failed: {exc}",
        )

    data = {
        "resource": args.resource,
        "pins": list(pins),
        "exclusive_pins": args.exclusive_pins,
        "channel": args.channel,
        "polarity": args.polarity,
        "triggered": True,
        "trigger_setpoints": {
            "current": _json_safe_number(current),
            "voltage": _json_safe_number(voltage),
        },
    }
    if args.pin is not None:
        data["pin"] = args.pin
        data["exclusive_pin"] = args.exclusive_pins
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    print(f"Resource: {args.resource}")
    print("Pins: " + ", ".join(str(pin) for pin in pins))
    print(f"Exclusive pins: {str(args.exclusive_pins).lower()}")
    print(f"Polarity: {args.polarity}")
    print("Triggered: True")
    return 0


class _TriggerModelError(ValueError):
    """Raised when a trigger command sees a non-E36312A model."""


class _TriggerNativeUnsupported(ValueError):
    """Raised when a requested trigger mode cannot run natively."""


class _TriggerInterrupted(RuntimeError):
    """Raised when a user stop request interrupts trigger waiting."""


class _TriggerWaitTimeout(RuntimeError):
    """Raised when operation-complete polling exceeds its timeout."""


class _TriggerExecutionStopped(RuntimeError):
    """Raised after trigger cleanup for interrupted or timed-out execution."""

    def __init__(self, message: str, *, trigger: dict[str, Any], exit_code: int, code: str) -> None:
        super().__init__(message)
        self.trigger = trigger
        self.exit_code = exit_code
        self.code = code


def _completion_pulse_requested(args: argparse.Namespace) -> bool:
    return getattr(args, "completion_pulse_pins", None) is not None


def _completion_pulse_pins(args: argparse.Namespace) -> tuple[int, ...]:
    return tuple(getattr(args, "completion_pulse_pins", None) or ())


def _completion_pulse_channel(args: argparse.Namespace, default_channel: int | str | None = None) -> int:
    configured = getattr(args, "completion_pulse_channel", None)
    if configured is not None:
        return int(configured)
    if isinstance(default_channel, int):
        return default_channel
    return 1


def _trigger_result_payload(
    *,
    mode: str,
    native: bool,
    channel: int,
    pins: tuple[int, ...] = (),
    polarity: str = "positive",
    source: str = "bus",
    armed: bool = False,
    fired: bool = False,
    completed: bool = False,
    aborted: bool = False,
    stopped: bool = False,
    stop_reason: str | None = None,
    wait_timeout_ms: int | None = None,
    poll_ms: int | None = None,
    restored: bool | None = None,
    restore_errors: list[str] | None = None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    payload = {
        "mode": mode,
        "native": native,
        "channel": channel,
        "pins": list(pins),
        "polarity": polarity,
        "source": source,
        "armed": armed,
        "fired": fired,
        "completed": completed,
        "aborted": aborted,
        "stopped": stopped,
        "stop_reason": stop_reason,
        "wait_timeout_ms": wait_timeout_ms,
        "poll_ms": poll_ms,
        "restored": restored,
        "restore_errors": restore_errors or [],
    }
    if fallback_reason is not None:
        payload["fallback_reason"] = fallback_reason
    return payload


def _restore_trigger_snapshot(
    power_supply: E36312APowerSupply,
    snapshot: Any | None,
    *,
    leave_configured: bool,
) -> tuple[bool | None, list[str]]:
    if snapshot is None:
        return (None, [])
    if leave_configured:
        return (False, [])
    try:
        power_supply.restore_trigger_snapshot(snapshot)
    except Exception as exc:
        return (False, [str(exc)])
    return (True, [])


def _trigger_wait_timeout_ms(
    args: argparse.Namespace,
    *,
    mode: str,
    dwell: tuple[float, ...] = (),
    count: int = 1,
) -> int:
    configured = getattr(args, "wait_timeout_ms", None)
    if configured is not None:
        return int(configured)
    if mode in {"list", "ramp"}:
        return int(sum(dwell) * max(count, 1) * 1000) + 5000
    return 10000


def _trigger_poll_interval_ms(args: argparse.Namespace) -> int:
    return max(int(getattr(args, "poll_ms", 200)), 50)


def _wait_complete_preview_commands(wait_complete: bool) -> tuple[str, ...]:
    if not wait_complete:
        return ()
    return ("*CLS", "*ESE 1", "*OPC", "*ESR?")


def _keyboard_stop_requested() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import msvcrt  # type: ignore[import-not-found]
    except ModuleNotFoundError:  # pragma: no cover - Windows-only guard
        return False
    try:
        if not msvcrt.kbhit():
            return False
        key = msvcrt.getwch()
    except OSError:
        return False
    return key.lower() == "q"


def _wait_for_trigger_completion(
    power_supply: E36312APowerSupply,
    *,
    timeout_ms: int,
    poll_ms: int,
) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    try:
        power_supply.prepare_operation_complete_wait()
        while True:
            if _keyboard_stop_requested():
                raise _TriggerInterrupted("trigger wait interrupted")
            if power_supply.operation_complete_event():
                return
            if time.monotonic() >= deadline:
                raise _TriggerWaitTimeout(f"trigger wait timed out after {timeout_ms} ms")
            sleep_seconds = min(poll_ms / 1000, max(deadline - time.monotonic(), 0))
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    except KeyboardInterrupt as exc:
        raise _TriggerInterrupted("trigger wait interrupted") from exc


def _abort_trigger_channels(
    power_supply: E36312APowerSupply,
    channels: Sequence[int],
    *,
    throttle: bool,
) -> list[str]:
    errors: list[str] = []
    for index, channel in enumerate(channels):
        try:
            power_supply.abort_output_trigger(channel)
        except Exception as exc:
            errors.append(str(exc))
        if throttle and index < len(channels) - 1:
            time.sleep(0.1)
    return errors


def _emit_trigger_stop_error(
    args: argparse.Namespace,
    *,
    request: dict[str, Any],
    execution: dict[str, Any],
    exc: _TriggerExecutionStopped,
) -> int:
    message = str(exc)
    data = {"trigger": exc.trigger}
    error_type = "interrupted" if exc.code == "interrupted" else "timeout"
    if args.json:
        emit_json_error(
            command=args.command,
            execution=execution,
            request=request,
            error_type=error_type,
            code=exc.code,
            message=message,
            retryable=exc.code == "interrupted",
            data=data,
        )
    else:
        print(message, file=sys.stderr)
    return exc.exit_code


def _configure_completion_output_pins(
    power_supply: E36312APowerSupply,
    pins: tuple[int, ...],
    polarity: str,
    *,
    exclusive_pins: bool = False,
) -> None:
    if not pins:
        return
    if exclusive_pins:
        power_supply.clear_trigger_output_pins(except_pins=pins)
    power_supply.configure_trigger_output_pins(pins, polarity)
    power_supply.enable_trigger_output_bus(True)


def _run_post_action_completion_pulse(
    args: argparse.Namespace,
    power_supply: E36312APowerSupply,
    *,
    channel: int,
) -> dict[str, Any] | None:
    pins = _completion_pulse_pins(args)
    if not pins:
        return None
    snapshot = power_supply.trigger_snapshot(channel)
    restored: bool | None = None
    restore_errors: list[str] = []
    fired = False
    completed = False
    try:
        power_supply.abort_output_trigger(channel)
        _configure_completion_output_pins(power_supply, pins, args.completion_pulse_polarity)
        current = power_supply.programmed_current(channel=channel)
        voltage = power_supply.programmed_voltage(channel=channel)
        power_supply.set_triggered_current(channel=channel, current=current)
        power_supply.set_triggered_voltage(channel=channel, voltage=voltage)
        power_supply.set_current_trigger_mode_step(channel)
        power_supply.set_voltage_trigger_mode_step(channel)
        power_supply.configure_output_trigger_source_bus(channel)
        power_supply.initiate_output_trigger(channel)
        power_supply.fire_bus_trigger()
        fired = True
        completed = True
    finally:
        restored, restore_errors = _restore_trigger_snapshot(
            power_supply,
            snapshot,
            leave_configured=getattr(args, "leave_trigger_configured", False),
        )
    return _trigger_result_payload(
        mode="completion-pulse",
        native=False,
        channel=channel,
        pins=pins,
        polarity=args.completion_pulse_polarity,
        source="bus",
        armed=True,
        fired=fired,
        completed=completed,
        restored=restored,
        restore_errors=restore_errors,
    )


def _maybe_run_completion_pulse(
    args: argparse.Namespace,
    power_supply: E36312APowerSupply,
    *,
    default_channel: int | str | None,
) -> dict[str, Any] | None:
    if not _completion_pulse_requested(args):
        return None
    if isinstance(power_supply, EDU36311APowerSupply):
        raise _TriggerNativeUnsupported(
            "EDU36311A real execution does not support completion-pulse options"
        )
    channel = _completion_pulse_channel(args, default_channel)
    return _run_post_action_completion_pulse(args, power_supply, channel=channel)


def _attach_trigger_if_present(data: dict[str, Any], trigger: dict[str, Any] | None) -> None:
    if trigger is not None:
        data["trigger"] = trigger


def _trigger_source_scpi(source: str) -> str:
    normalized = source.strip().lower()
    if normalized == "immediate":
        return "IMM"
    if normalized in {"bus", "pin1", "pin2", "pin3", "ext"}:
        return normalized.upper()
    if normalized == "imm":
        return "IMM"
    raise ValueError("trigger source must be bus, immediate, pin1, pin2, pin3, or ext")


def _validate_real_trigger_source(args: argparse.Namespace, source: str) -> None:
    if args.simulate or args.dry_run:
        return
    if source not in {"bus", "immediate"}:
        raise _TriggerNativeUnsupported("real PIN/EXT trigger input is not enabled yet; use --dry-run or --simulate")


def _trigger_step_scpi(
    *,
    channel: int,
    source: str,
    voltage: float | None,
    current: float | None,
    pins: tuple[int, ...] = (),
    polarity: str = "positive",
    fire: bool = False,
    wait_complete: bool = False,
) -> tuple[str, ...]:
    commands: list[str] = [f"ABOR (@{channel})"]
    polarity_command = "POS" if polarity == "positive" else "NEG"
    for pin in pins:
        commands.append(f"DIG:PIN{pin}:FUNC TOUT")
        commands.append(f"DIG:PIN{pin}:POL {polarity_command}")
    if pins:
        commands.append("DIG:TOUT:BUS ON")
    current_text = _format_text_value(current) if current is not None else "<current-readback>"
    voltage_text = _format_text_value(voltage) if voltage is not None else "<voltage-readback>"
    commands.extend(
        [
            f"CURR:TRIG {current_text},(@{channel})",
            f"VOLT:TRIG {voltage_text},(@{channel})",
            f"CURR:MODE STEP,(@{channel})",
            f"VOLT:MODE STEP,(@{channel})",
            f"TRIG:SOUR {_trigger_source_scpi(source)},(@{channel})",
            f"INIT (@{channel})",
        ]
    )
    if source == "bus" and fire:
        commands.append("*TRG")
    commands.extend(_wait_complete_preview_commands(wait_complete))
    return tuple(commands)


def _trigger_list_scpi(
    *,
    channel: int,
    source: str,
    voltages: tuple[float, ...],
    currents: tuple[float, ...],
    dwell: tuple[float, ...],
    pins: tuple[int, ...] = (),
    polarity: str = "positive",
    final_eost_pulse: bool = False,
    begin_outputs: tuple[bool, ...] | None = None,
    end_outputs: tuple[bool, ...] | None = None,
    exclusive_pins: bool = False,
    fire: bool = False,
    count: int = 1,
    wait_complete: bool = False,
) -> tuple[str, ...]:
    commands: list[str] = [f"ABOR (@{channel})"]
    polarity_command = "POS" if polarity == "positive" else "NEG"
    if exclusive_pins and pins:
        for pin in (1, 2, 3):
            if pin not in pins:
                commands.append(f"DIG:PIN{pin}:FUNC DIO")
    for pin in pins:
        commands.append(f"DIG:PIN{pin}:FUNC TOUT")
        commands.append(f"DIG:PIN{pin}:POL {polarity_command}")
    if pins:
        commands.append("DIG:TOUT:BUS ON")
    begin_outputs = begin_outputs if begin_outputs is not None else tuple(False for _ in voltages)
    end_outputs = end_outputs if end_outputs is not None else tuple(
        index == len(voltages) - 1 and final_eost_pulse for index, _ in enumerate(voltages)
    )
    commands.extend(
        [
            f"LIST:VOLT {_number_csv(voltages)},(@{channel})",
            f"LIST:CURR {_number_csv(currents)},(@{channel})",
            f"LIST:DWEL {_number_csv(dwell)},(@{channel})",
            f"LIST:TOUT:BOST {_bool_csv(begin_outputs)},(@{channel})",
            f"LIST:TOUT:EOST {_bool_csv(end_outputs)},(@{channel})",
            f"LIST:COUN {count},(@{channel})",
            f"LIST:STEP AUTO,(@{channel})",
            f"LIST:TERM:LAST ON,(@{channel})",
            f"CURR:MODE LIST,(@{channel})",
            f"VOLT:MODE LIST,(@{channel})",
            f"TRIG:SOUR {_trigger_source_scpi(source)},(@{channel})",
            f"INIT (@{channel})",
        ]
    )
    if source == "bus" and fire:
        commands.append("*TRG")
    commands.extend(_wait_complete_preview_commands(wait_complete))
    return tuple(commands)


def _number_csv(values: Sequence[float]) -> str:
    return ",".join(_format_text_value(value) for value in values)


def _bool_csv(values: Sequence[bool]) -> str:
    return ",".join("1" if value else "0" for value in values)


def _validate_trigger_list_limits(
    *,
    voltages: tuple[float, ...],
    currents: tuple[float, ...],
    dwell: tuple[float, ...],
    count: int,
) -> None:
    if not voltages:
        raise ValueError("trigger LIST requires at least one step")
    if len(voltages) > 100:
        raise ValueError("trigger LIST supports at most 100 steps")
    if len(currents) != len(voltages):
        raise ValueError("current list length must match voltage list length")
    if len(dwell) != len(voltages):
        raise ValueError("dwell list length must match voltage list length")
    if count < 1 or count > 256:
        raise ValueError("LIST count must be between 1 and 256")
    for seconds in dwell:
        if seconds < 0.01 or seconds > 3600:
            raise ValueError("LIST dwell values must be between 0.01 and 3600 seconds")


def _validate_trigger_step_args(args: argparse.Namespace) -> None:
    if _completion_pulse_requested(args):
        raise ValueError(
            "trigger-step does not support --completion-pulse-pins as a completion pulse; "
            "use a one-step trigger-list with --completion-pulse-pins"
        )
    if args.source == "immediate" and args.fire:
        raise ValueError("trigger-step --source immediate does not accept --fire; INIT starts it immediately")
    if args.source not in {"bus", "immediate"} and args.fire:
        raise ValueError("trigger-step --fire is only valid with --source bus")
    if args.wait_complete and args.source == "bus" and not args.fire:
        raise ValueError("trigger-step --wait-complete with BUS source requires --fire")


def _validate_trigger_list_control_args(args: argparse.Namespace, config: dict[str, Any]) -> None:
    source = str(config["source"]).lower()
    if source == "immediate" and args.fire:
        raise ValueError("trigger-list --source immediate does not accept --fire; INIT starts it immediately")
    if source not in {"bus", "immediate"} and args.fire:
        raise ValueError("trigger-list --fire is only valid with --source bus")
    if source != "immediate" and not args.fire and not args.leave_trigger_configured:
        raise ValueError("trigger-list arm-only requires --leave-trigger-configured")
    started = source == "immediate" or (source == "bus" and args.fire)
    if started and not args.wait_complete and not args.leave_trigger_configured:
        raise ValueError("trigger-list started without --wait-complete requires --leave-trigger-configured")
    if args.wait_complete and source == "bus" and not args.fire:
        raise ValueError("trigger-list --wait-complete with BUS source requires --fire")


def _validate_trigger_list_safety(config: dict[str, Any], safety_limits: SafetyLimits | None) -> None:
    channel = int(config["channel"])
    for voltage, current in zip(config["voltages"], config["currents"], strict=True):
        validate_setpoint(channel=channel, voltage=voltage, current=current, limits=safety_limits)


def _validate_trigger_step_safety(
    *,
    channel: int,
    voltage: float | None,
    current: float | None,
    safety_limits: SafetyLimits | None,
) -> None:
    validate_setpoint(channel=channel, voltage=voltage, current=current, limits=safety_limits)


def _run_native_list(
    args: argparse.Namespace,
    power_supply: E36312APowerSupply,
    *,
    channel: int,
    source: str,
    voltages: tuple[float, ...],
    currents: tuple[float, ...],
    dwell: tuple[float, ...],
    pins: tuple[int, ...],
    polarity: str,
    final_eost_pulse: bool,
    begin_outputs: tuple[bool, ...] | None = None,
    end_outputs: tuple[bool, ...] | None = None,
    exclusive_pins: bool = False,
    fire: bool = False,
    count: int = 1,
    wait_complete: bool = True,
    mode: str = "list",
) -> dict[str, Any]:
    _validate_real_trigger_source(args, source)
    _validate_trigger_list_limits(voltages=voltages, currents=currents, dwell=dwell, count=count)
    snapshot = power_supply.trigger_snapshot(channel)
    restored: bool | None = None
    restore_errors: list[str] = []
    fired = False
    completed = False
    aborted = False
    stopped = False
    stop_reason: str | None = None
    wait_timeout_ms = _trigger_wait_timeout_ms(args, mode=mode, dwell=dwell, count=count)
    poll_ms = _trigger_poll_interval_ms(args)
    cleanup_errors: list[str] = []
    pending_stop: _TriggerExecutionStopped | None = None
    try:
        power_supply.abort_output_trigger(channel)
        _configure_completion_output_pins(power_supply, pins, polarity, exclusive_pins=exclusive_pins)
        begin_outputs = begin_outputs if begin_outputs is not None else tuple(False for _ in voltages)
        end_outputs = end_outputs if end_outputs is not None else tuple(
            index == len(voltages) - 1 and final_eost_pulse for index, _ in enumerate(voltages)
        )
        power_supply.configure_list(
            channel=channel,
            voltages=voltages,
            currents=currents,
            dwell=dwell,
            begin_outputs=begin_outputs,
            end_outputs=end_outputs,
            count=count,
            step_mode="AUTO",
            terminate_last=True,
        )
        power_supply.set_current_trigger_mode(channel=channel, mode="LIST")
        power_supply.set_voltage_trigger_mode(channel=channel, mode="LIST")
        power_supply.set_output_trigger_source(channel=channel, source=_trigger_source_scpi(source))
        power_supply.initiate_output_trigger(channel)
        if source == "bus" and fire:
            power_supply.fire_bus_trigger()
            fired = True
        elif source == "immediate":
            fired = True
        if wait_complete:
            _wait_for_trigger_completion(power_supply, timeout_ms=wait_timeout_ms, poll_ms=poll_ms)
            completed = True
        else:
            completed = False
    except (_TriggerInterrupted, _TriggerWaitTimeout) as exc:
        stopped = True
        stop_reason = "interrupted" if isinstance(exc, _TriggerInterrupted) else "timeout"
        cleanup_errors.extend(_abort_trigger_channels(power_supply, (channel,), throttle=True))
        aborted = not cleanup_errors
        if isinstance(exc, _TriggerInterrupted):
            pending_stop = _TriggerExecutionStopped(
                "trigger wait interrupted",
                trigger={},
                exit_code=130,
                code="interrupted",
            )
        else:
            pending_stop = _TriggerExecutionStopped(
                str(exc),
                trigger={},
                exit_code=1,
                code="wait_timeout",
            )
    finally:
        restored, restore_errors = _restore_trigger_snapshot(
            power_supply,
            snapshot,
            leave_configured=getattr(args, "leave_trigger_configured", False) and pending_stop is None,
        )
    if restore_errors:
        cleanup_errors.extend(restore_errors)
    if pending_stop is not None:
        pending_stop.trigger = _trigger_result_payload(
            mode=mode,
            native=True,
            channel=channel,
            pins=pins,
            polarity=polarity,
            source=source,
            armed=True,
            fired=fired,
            completed=False,
            aborted=aborted,
            stopped=stopped,
            stop_reason=stop_reason,
            wait_timeout_ms=wait_timeout_ms,
            poll_ms=poll_ms,
            restored=restored,
            restore_errors=cleanup_errors,
        )
        raise pending_stop
    return _trigger_result_payload(
        mode=mode,
        native=True,
        channel=channel,
        pins=pins,
        polarity=polarity,
        source=source,
        armed=True,
        fired=fired,
        completed=completed,
        aborted=aborted,
        stopped=stopped,
        stop_reason=stop_reason,
        wait_timeout_ms=wait_timeout_ms if wait_complete else None,
        poll_ms=poll_ms if wait_complete else None,
        restored=restored,
        restore_errors=cleanup_errors,
    )


def _run_native_step(
    args: argparse.Namespace,
    power_supply: E36312APowerSupply,
    *,
    channel: int,
    source: str,
    voltage: float | None,
    current: float | None,
    pins: tuple[int, ...],
    polarity: str,
    fire: bool,
    wait_complete: bool,
) -> dict[str, Any]:
    _validate_real_trigger_source(args, source)
    snapshot = power_supply.trigger_snapshot(channel)
    restored: bool | None = None
    restore_errors: list[str] = []
    fired = False
    completed = False
    aborted = False
    stopped = False
    stop_reason: str | None = None
    wait_timeout_ms = _trigger_wait_timeout_ms(args, mode="step")
    poll_ms = _trigger_poll_interval_ms(args)
    cleanup_errors: list[str] = []
    pending_stop: _TriggerExecutionStopped | None = None
    try:
        power_supply.abort_output_trigger(channel)
        _configure_completion_output_pins(power_supply, pins, polarity)
        selected_voltage = power_supply.programmed_voltage(channel=channel) if voltage is None else voltage
        selected_current = power_supply.programmed_current(channel=channel) if current is None else current
        power_supply.set_triggered_current(channel=channel, current=selected_current)
        power_supply.set_triggered_voltage(channel=channel, voltage=selected_voltage)
        power_supply.set_current_trigger_mode_step(channel)
        power_supply.set_voltage_trigger_mode_step(channel)
        power_supply.set_output_trigger_source(channel=channel, source=_trigger_source_scpi(source))
        power_supply.initiate_output_trigger(channel)
        if source == "bus" and fire:
            power_supply.fire_bus_trigger()
            fired = True
        elif source == "immediate":
            fired = True
        if wait_complete:
            _wait_for_trigger_completion(power_supply, timeout_ms=wait_timeout_ms, poll_ms=poll_ms)
            completed = True
        else:
            completed = False
    except (_TriggerInterrupted, _TriggerWaitTimeout) as exc:
        stopped = True
        stop_reason = "interrupted" if isinstance(exc, _TriggerInterrupted) else "timeout"
        cleanup_errors.extend(_abort_trigger_channels(power_supply, (channel,), throttle=True))
        aborted = not cleanup_errors
        if isinstance(exc, _TriggerInterrupted):
            pending_stop = _TriggerExecutionStopped(
                "trigger wait interrupted",
                trigger={},
                exit_code=130,
                code="interrupted",
            )
        else:
            pending_stop = _TriggerExecutionStopped(
                str(exc),
                trigger={},
                exit_code=1,
                code="wait_timeout",
            )
    finally:
        restored, restore_errors = _restore_trigger_snapshot(
            power_supply,
            snapshot,
            leave_configured=getattr(args, "leave_trigger_configured", False) and pending_stop is None,
        )
    if restore_errors:
        cleanup_errors.extend(restore_errors)
    if pending_stop is not None:
        pending_stop.trigger = _trigger_result_payload(
            mode="step",
            native=True,
            channel=channel,
            pins=pins,
            polarity=polarity,
            source=source,
            armed=True,
            fired=fired,
            completed=False,
            aborted=aborted,
            stopped=stopped,
            stop_reason=stop_reason,
            wait_timeout_ms=wait_timeout_ms,
            poll_ms=poll_ms,
            restored=restored,
            restore_errors=cleanup_errors,
        )
        raise pending_stop
    return _trigger_result_payload(
        mode="step",
        native=True,
        channel=channel,
        pins=pins,
        polarity=polarity,
        source=source,
        armed=True,
        fired=fired,
        completed=completed,
        aborted=aborted,
        stopped=stopped,
        stop_reason=stop_reason,
        wait_timeout_ms=wait_timeout_ms if wait_complete else None,
        poll_ms=poll_ms if wait_complete else None,
        restored=restored,
        restore_errors=cleanup_errors,
    )


def _run_trigger_status(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _TriggerModelError(
                    "trigger-status is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            channels = _channels_from_selection(args.channel, power_supply.capabilities.channels)
            data = {
                "resource": _resource_payload(args.resource, simulated=args.simulate, reachable=True, idn_raw=idn),
                "digital_pins": [
                    {
                        "pin": pin,
                        "function": power_supply.digital_pin_function(pin),
                        "polarity": power_supply.digital_pin_polarity(pin),
                    }
                    for pin in (1, 2, 3)
                ],
                "trigger_output_bus_enabled": power_supply.trigger_output_bus_enabled(),
                "channels": [_trigger_channel_status(power_supply, channel) for channel in channels],
            }
    except (_TriggerModelError, _E36312AChannelError) as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="unsupported_model_for_trigger" if isinstance(exc, _TriggerModelError) else "argument_error", message=str(exc), retryable=False, hardware_intent=True)
    except (VisaConnectionError, ValueError) as exc:
        return _emit_safe_io_error(args, request=request, execution=execution, code="trigger_status_failed", message=f"trigger-status failed: {exc}")
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
    else:
        print(f"Resource: {args.resource}")
        print(f"Trigger output BUS: {str(data['trigger_output_bus_enabled']).lower()}")
    return 0


def _trigger_channel_status(power_supply: E36312APowerSupply, channel: int) -> dict[str, Any]:
    return {
        "channel": channel,
        "trigger": {
            "source": power_supply.output_trigger_source(channel),
            "delay": power_supply.output_trigger_delay(channel),
            "voltage_mode": power_supply.voltage_trigger_mode(channel),
            "current_mode": power_supply.current_trigger_mode(channel),
            "triggered_voltage": power_supply.triggered_voltage(channel),
            "triggered_current": power_supply.triggered_current(channel),
        },
        "list": {
            "voltage": list(power_supply.list_voltage(channel)),
            "current": list(power_supply.list_current(channel)),
            "dwell": list(power_supply.list_dwell(channel)),
            "tout_bost": list(power_supply.list_trigger_output_begin(channel)),
            "tout_eost": list(power_supply.list_trigger_output_end(channel)),
            "count": power_supply.list_count(channel),
            "step_mode": power_supply.list_step_mode(channel),
            "terminate_last": power_supply.list_terminate_last(channel),
        },
    }


def _run_trigger_step(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    try:
        _validate_trigger_step_args(args)
        safety_limits = _safety_limits_for_channel(args, args.channel, model="E36312A")
        request = _request_for_args(args)
        _validate_trigger_step_safety(
            channel=args.channel,
            voltage=args.voltage,
            current=args.current,
            safety_limits=safety_limits,
        )
    except (SafetyConfigError, SafetyValidationError, ValueError) as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="argument_error", message=str(exc), retryable=False)
    pins = _completion_pulse_pins(args)
    scpi = _trigger_step_scpi(
        channel=args.channel,
        source=args.source,
        voltage=args.voltage,
        current=args.current,
        pins=pins,
        polarity=args.completion_pulse_polarity,
        fire=args.fire,
        wait_complete=args.wait_complete,
    )
    if args.dry_run:
        plan = dry_run_plan(command=args.command, resource=args.resource, scpi=scpi, description="Preview a native E36312A STEP transient trigger.")
        if args.json:
            emit_json_success(command=args.command, execution=execution, request=request, data={"plan": plan})
            return 0
        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=True)
        return 0
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        _validate_real_trigger_source(args, args.source)
        with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, STEP_TRIGGER_POWER_SUPPLY_TYPES):
                raise _TriggerModelError(
                    "trigger-step is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            trigger = _run_native_step(
                args,
                power_supply,
                channel=args.channel,
                source=args.source,
                voltage=args.voltage,
                current=args.current,
                pins=pins,
                polarity=args.completion_pulse_polarity,
                fire=args.fire,
                wait_complete=args.wait_complete,
            )
            _raise_on_instrument_errors(power_supply, "trigger-step")
            data = {
                "resource": _resource_payload(args.resource, simulated=args.simulate, reachable=True, idn_raw=idn),
                "trigger": trigger,
            }
    except _TriggerModelError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="unsupported_model_for_trigger", message=str(exc), retryable=False, hardware_intent=True)
    except _TriggerNativeUnsupported as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="trigger_native_unsupported", message=str(exc), retryable=False, hardware_intent=True)
    except _TriggerExecutionStopped as exc:
        return _emit_trigger_stop_error(args, request=request, execution=execution, exc=exc)
    except (VisaConnectionError, ValueError) as exc:
        return _emit_safe_io_error(args, request=request, execution=execution, code="trigger_config_failed", message=f"trigger-step failed: {exc}")
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
    else:
        print(f"Resource: {args.resource}")
        print(f"Triggered: {str(data['trigger']['completed']).lower()}")
    return 0


def _run_trigger_list(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    try:
        config = _trigger_list_config_from_args(args)
        _validate_trigger_list_limits(
            voltages=config["voltages"],
            currents=config["currents"],
            dwell=config["dwell"],
            count=config["count"],
        )
        _validate_trigger_list_control_args(args, config)
        safety_limits = _safety_limits_for_channel(args, config["channel"], model="E36312A")
        request = _request_for_args(args)
        _validate_trigger_list_safety(config, safety_limits)
    except (OSError, SafetyConfigError, SafetyValidationError, ValueError) as exc:
        code = "trigger_list_too_long" if "at most 100" in str(exc) else "argument_error"
        return _emit_cli_error(args, request=request, error_type="validation", code=code, message=str(exc), retryable=False)
    scpi = _trigger_list_scpi(
        **config,
        exclusive_pins=args.exclusive_pins,
        fire=args.fire,
        wait_complete=args.wait_complete,
    )
    if args.dry_run:
        plan = dry_run_plan(command=args.command, resource=args.resource, scpi=scpi, description="Preview a native E36312A LIST transient trigger.")
        if args.json:
            emit_json_success(command=args.command, execution=execution, request=request, data={"plan": plan})
            return 0
        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=True)
        return 0
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        _validate_real_trigger_source(args, config["source"])
        with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, E36312APowerSupply):
                raise _TriggerModelError(
                    "trigger-list is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            trigger = _run_native_list(
                args,
                power_supply,
                **config,
                exclusive_pins=args.exclusive_pins,
                fire=args.fire,
                wait_complete=args.wait_complete,
                mode="list",
            )
            _raise_on_instrument_errors(power_supply, "trigger-list")
            data = {
                "resource": _resource_payload(args.resource, simulated=args.simulate, reachable=True, idn_raw=idn),
                "steps": len(config["voltages"]),
                "trigger": trigger,
            }
    except _TriggerModelError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="unsupported_model_for_trigger", message=str(exc), retryable=False, hardware_intent=True)
    except _TriggerNativeUnsupported as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="trigger_native_unsupported", message=str(exc), retryable=False, hardware_intent=True)
    except _TriggerExecutionStopped as exc:
        return _emit_trigger_stop_error(args, request=request, execution=execution, exc=exc)
    except (VisaConnectionError, ValueError) as exc:
        return _emit_safe_io_error(args, request=request, execution=execution, code="trigger_config_failed", message=f"trigger-list failed: {exc}")
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
    else:
        print(f"Resource: {args.resource}")
        print(f"Steps: {data['steps']}")
    return 0


def _trigger_list_config_from_args(args: argparse.Namespace) -> dict[str, Any]:
    document: dict[str, Any] = {}
    if getattr(args, "file", None):
        document = _load_sequence_document(args.file)
    channel = args.channel if args.channel is not None else document.get("channel")
    if channel is None:
        raise ValueError("trigger-list requires --channel or channel in --file")
    voltages = args.voltage_list or _document_float_list(document, "voltages", "voltage_list", "voltage")
    currents = args.current_list or _document_float_list(document, "currents", "current_list", "current")
    dwell = args.dwell_list or _document_float_list(document, "dwell", "dwells", "dwell_list")
    bost = getattr(args, "bost_list", None) or _document_bool_list(document, "bost_list")
    eost = getattr(args, "eost_list", None) or _document_bool_list(document, "eost_list")
    steps = document.get("steps")
    if (voltages is None or currents is None or dwell is None) and steps is not None:
        if not isinstance(steps, list) or not steps:
            raise ValueError("trigger-list steps in --file must be a non-empty list")
        step_voltages: list[float] = []
        step_currents: list[float] = []
        step_dwell: list[float] = []
        step_bost: list[bool] = []
        step_eost: list[bool] = []
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ValueError(f"trigger-list step {index} must be a mapping")
            try:
                step_voltages.append(float(step["voltage"]))
                step_currents.append(float(step["current"]))
                step_dwell.append(float(step["dwell"]))
                step_bost.append(_strict_bool(step.get("bost", False), f"trigger-list step {index} bost"))
                step_eost.append(_strict_bool(step.get("eost", False), f"trigger-list step {index} eost"))
            except KeyError as exc:
                raise ValueError(f"trigger-list step {index} missing {exc.args[0]}") from exc
        if voltages is None:
            voltages = tuple(step_voltages)
        if currents is None:
            currents = tuple(step_currents)
        if dwell is None:
            dwell = tuple(step_dwell)
        if bost is None:
            bost = tuple(step_bost)
        if eost is None:
            eost = tuple(step_eost)
    if voltages is None:
        raise ValueError("trigger-list requires --voltage-list or voltages in --file")
    if currents is None:
        raise ValueError("trigger-list requires --current-list or currents in --file")
    if dwell is None:
        raise ValueError("trigger-list requires --dwell-list or dwell in --file")
    if len(currents) == 1 and len(voltages) > 1:
        currents = tuple(currents[0] for _ in voltages)
    if len(dwell) == 1 and len(voltages) > 1:
        dwell = tuple(dwell[0] for _ in voltages)
    pins = _completion_pulse_pins(args)
    if not pins:
        doc_pins = document.get("pins", document.get("completion_pulse_pins"))
        if doc_pins is not None:
            pins = tuple(_trigger_pin(str(pin)) for pin in doc_pins) if isinstance(doc_pins, list) else _trigger_pins_list(str(doc_pins))
    source = args.source or str(document.get("source", "bus"))
    final_eost_pulse = bool(pins)
    count = args.count if args.count != 1 else int(document.get("count", 1))
    polarity = args.completion_pulse_polarity or str(document.get("polarity", "positive"))
    canonical_requested = any(
        value is not None
        for value in (
            getattr(args, "bost_list", None),
            getattr(args, "eost_list", None),
            getattr(args, "trigger_output_pins", None),
            getattr(args, "trigger_output_polarity", None),
            document.get("bost_list"),
            document.get("eost_list"),
            document.get("trigger_output_pins"),
            document.get("trigger_output_polarity"),
        )
    ) or (steps is not None and any(isinstance(step, dict) and ("bost" in step or "eost" in step) for step in steps))
    if canonical_requested and pins:
        raise ValueError("trigger-list completion-pulse fields cannot be mixed with BOST/EOST trigger-output fields")
    if canonical_requested:
        pins = getattr(args, "trigger_output_pins", None) or tuple(document.get("trigger_output_pins") or ())
        polarity = getattr(args, "trigger_output_polarity", None) or str(document.get("trigger_output_polarity", "positive"))
        bost = bost if bost is not None else tuple(False for _ in voltages)
        eost = eost if eost is not None else tuple(False for _ in voltages)
        if len(bost) != len(voltages):
            raise ValueError("BOST list length must match voltage list length")
        if len(eost) != len(voltages):
            raise ValueError("EOST list length must match voltage list length")
        if (any(bost) or any(eost)) and not pins:
            raise ValueError("trigger-list BOST/EOST pulses require explicit trigger output pins")
    config = {
        "channel": int(channel),
        "source": str(source).lower(),
        "voltages": tuple(float(value) for value in voltages),
        "currents": tuple(float(value) for value in currents),
        "dwell": tuple(float(value) for value in dwell),
        "pins": pins,
        "polarity": polarity,
        "final_eost_pulse": final_eost_pulse if not canonical_requested else False,
        "count": count,
    }
    if canonical_requested:
        config.update({"begin_outputs": tuple(bost), "end_outputs": tuple(eost)})
    return config


def _document_float_list(document: dict[str, Any], *keys: str) -> tuple[float, ...] | None:
    for key in keys:
        if key not in document:
            continue
        value = document[key]
        if isinstance(value, list):
            return tuple(float(item) for item in value)
        if isinstance(value, tuple):
            return tuple(float(item) for item in value)
        return (float(value),)
    return None


def _document_bool_list(document: dict[str, Any], key: str) -> tuple[bool, ...] | None:
    if key not in document:
        return None
    value = document[key]
    if not isinstance(value, list):
        raise ValueError(f"trigger-list {key} must be a list")
    return tuple(_strict_bool(item, f"trigger-list {key}") for item in value)


def _strict_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _run_trigger_fire(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    if args.wait_complete and args.channel is None:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message="trigger-fire --wait-complete requires --channel for interrupted cleanup",
            retryable=False,
        )
    scpi = ("*TRG", *_wait_complete_preview_commands(args.wait_complete))
    if args.dry_run:
        plan = dry_run_plan(command=args.command, resource=args.resource, scpi=scpi, description="Preview firing an already armed BUS trigger.")
        if args.json:
            emit_json_success(command=args.command, execution=execution, request=request, data={"plan": plan})
            return 0
        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=True)
        return 0
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, STEP_TRIGGER_POWER_SUPPLY_TYPES):
                raise _TriggerModelError(
                    "trigger-fire is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            power_supply.fire_bus_trigger()
            wait_timeout_ms = _trigger_wait_timeout_ms(args, mode="fire")
            poll_ms = _trigger_poll_interval_ms(args)
            completed = not args.wait_complete
            if args.wait_complete:
                try:
                    _wait_for_trigger_completion(power_supply, timeout_ms=wait_timeout_ms, poll_ms=poll_ms)
                    completed = True
                except (_TriggerInterrupted, _TriggerWaitTimeout) as exc:
                    cleanup_errors = _abort_trigger_channels(power_supply, (int(args.channel),), throttle=True)
                    trigger = _trigger_result_payload(
                        mode="fire",
                        native=True,
                        channel=int(args.channel),
                        fired=True,
                        completed=False,
                        aborted=not cleanup_errors,
                        stopped=True,
                        stop_reason="interrupted" if isinstance(exc, _TriggerInterrupted) else "timeout",
                        wait_timeout_ms=wait_timeout_ms,
                        poll_ms=poll_ms,
                        source="bus",
                        restore_errors=cleanup_errors,
                    )
                    raise _TriggerExecutionStopped(
                        "trigger wait interrupted" if isinstance(exc, _TriggerInterrupted) else str(exc),
                        trigger=trigger,
                        exit_code=130 if isinstance(exc, _TriggerInterrupted) else 1,
                        code="interrupted" if isinstance(exc, _TriggerInterrupted) else "wait_timeout",
                    ) from exc
            _raise_on_instrument_errors(power_supply, "trigger-fire")
            data = {
                "resource": _resource_payload(args.resource, simulated=args.simulate, reachable=True, idn_raw=idn),
                "trigger": _trigger_result_payload(
                    mode="fire",
                    native=True,
                    channel=int(args.channel or 0),
                    fired=True,
                    completed=completed,
                    wait_timeout_ms=wait_timeout_ms if args.wait_complete else None,
                    poll_ms=poll_ms if args.wait_complete else None,
                    source="bus",
                ),
            }
    except _TriggerModelError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="unsupported_model_for_trigger", message=str(exc), retryable=False, hardware_intent=True)
    except _TriggerNativeUnsupported as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="trigger_native_unsupported", message=str(exc), retryable=False, hardware_intent=True)
    except _TriggerExecutionStopped as exc:
        return _emit_trigger_stop_error(args, request=request, execution=execution, exc=exc)
    except (VisaConnectionError, ValueError) as exc:
        return _emit_safe_io_error(args, request=request, execution=execution, code="trigger_fire_failed", message=f"trigger-fire failed: {exc}")
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
    else:
        print("Triggered: true")
    return 0


def _run_trigger_abort(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    abort_channels = (1, 2, 3) if args.channel == "all" else (int(args.channel),)
    scpi = tuple(f"ABOR (@{channel})" for channel in abort_channels) + ("SYST:ERR?",)
    if args.dry_run:
        plan = dry_run_plan(command=args.command, resource=args.resource, scpi=scpi, description="Preview aborting an E36312A trigger/list channel.")
        if args.json:
            emit_json_success(command=args.command, execution=execution, request=request, data={"plan": plan})
            return 0
        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=True)
        return 0
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn = session.query(IDN_QUERY)
            power_supply = create_power_supply(session, idn)
            if not isinstance(power_supply, STEP_TRIGGER_POWER_SUPPLY_TYPES):
                raise _TriggerModelError(
                    "trigger-abort is only supported for E36312A; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )
            _abort_trigger_channels(power_supply, abort_channels, throttle=True)
            errors, read_count = _read_error_queue_from_driver(power_supply, args.max_errors)
            data = {
                "resource": _resource_payload(args.resource, simulated=args.simulate, reachable=True, idn_raw=idn),
                "channel": args.channel,
                "channels": list(abort_channels),
                "aborted": True,
                "errors": errors,
                "read_count": read_count,
            }
    except _TriggerModelError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="unsupported_model_for_trigger", message=str(exc), retryable=False, hardware_intent=True)
    except _TriggerNativeUnsupported as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="trigger_native_unsupported", message=str(exc), retryable=False, hardware_intent=True)
    except (VisaConnectionError, ValueError) as exc:
        return _emit_safe_io_error(args, request=request, execution=execution, code="trigger_config_failed", message=f"trigger-abort failed: {exc}")
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
    else:
        print(f"Channel {args.channel}: aborted")
    return 0


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
            selection = select_driver(idn_raw)
            power_supply = selection.driver_class(session)
            if not isinstance(power_supply, (E36312APowerSupply, EDU36311APowerSupply)):
                raise _ReadOnlyModelError(
                    "validate-readonly is only supported for E36312A or EDU36311A; "
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


def _write_json_file(path: str, data: dict[str, Any]) -> None:
    output_path = Path(path)
    if output_path.parent != Path("."):
        output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")


def _write_json_file_atomic(path: str, data: dict[str, Any]) -> None:
    output_path = Path(path)
    parent = output_path.parent
    if parent != Path("."):
        parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(data, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, output_path)
    except OSError:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _run_restore_from_snapshot(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    if args.plan_json and not args.dry_run:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message="--plan-json requires --dry-run",
            retryable=False,
        )
    try:
        data = restore_core.run_restore(
            OperationRequest(
                command="restore-from-snapshot",
                runtime=RuntimeOptions(
                    resource=args.resource,
                    simulate=args.simulate,
                    dry_run=args.dry_run,
                    **_runtime_identity_for_args(args),
                    backend=args.backend,
                    timeout_ms=args.timeout_ms,
                    log_scpi=args.log_scpi,
                    confirm=args.confirm,
                    support_policy_mode=_support_policy_mode_for_args(args),
                ),
                parameters={
                    "snapshot": args.snapshot,
                    "channel": args.channel,
                    "restore_output_state": args.restore_output_state,
                },
            ),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except ConfirmationRequiredError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="confirmation_required",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except UnsupportedModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_restore",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except CoreValidationError as exc:
        message = str(exc)
        code = (
            "snapshot_identity_mismatch"
            if "does not match snapshot" in message
            else _core_validation_code(exc)
        )
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code=code,
            message=message,
            retryable=False,
            hardware_intent=not args.dry_run,
        )
    except CoreIoError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="restore_failed" if exc.opened else "connection_failed",
            message=str(exc),
        )

    if args.plan_json:
        try:
            _write_json_file(args.plan_json, data)
        except OSError as exc:
            return _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="argument_error",
                message=f"could not write plan JSON: {exc}",
                retryable=False,
            )
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0
    if args.dry_run or args.simulate:
        _print_scpi_plan(data["plan"], mode=_mode_for_args(args), dry_run=args.dry_run)
        return 0
    _emit_text_lines(
        cli_rendering.format_restore_from_snapshot_success(
            args.resource,
            data["restored_channels"],
        )
    )
    return 0


def _run_log(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)

    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        _validate_log_request(args)
    except (SafetyConfigError, ValueError) as exc:
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
    except _ReadOnlyModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_log",
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
    except (OSError, VisaConnectionError, ValueError) as exc:
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


@contextmanager
def _cooperative_workflow_interrupt() -> Iterator[threading.Event]:
    stop_event = threading.Event()
    installed = threading.current_thread() is threading.main_thread()
    previous_handler: Any = None

    if installed:
        previous_handler = signal.getsignal(signal.SIGINT)

        def request_stop(_signum: int, _frame: Any) -> None:
            stop_event.set()

        signal.signal(signal.SIGINT, request_stop)
    try:
        yield stop_event
    finally:
        if installed:
            signal.signal(signal.SIGINT, previous_handler)


def _emit_workflow_interruption(
    args: argparse.Namespace,
    *,
    request: dict[str, Any],
    execution: dict[str, Any],
    exc: CommandCancelled | StopCleanupError,
) -> int:
    cleanup_failed = isinstance(exc, StopCleanupError)
    code = "cleanup_failed" if cleanup_failed else "cancelled"
    data = dict(getattr(exc, "data", {}) or {})
    data.setdefault("original_reason", "user cancellation")
    if args.json:
        emit_json_error(
            command=args.command,
            execution=execution,
            request=request,
            error_type="execution",
            code=code,
            message=str(exc),
            retryable=cleanup_failed,
            data=data,
        )
    else:
        print(f"{args.command} {code}: {exc}", file=sys.stderr)
    return 3


def _workflow_start_summary(
    args: argparse.Namespace,
    core_request: OperationRequest | SequenceRequest,
) -> tuple[
    OperationRequest | SequenceRequest,
    dict[str, Any],
    list[dict[str, str]],
]:
    admitted_request = validate_request_admission(core_request)
    summary = workflow_execution_summary(admitted_request) or {}
    units = summary.get("execution_units")
    warning = summary.get("execution_warning")
    if not args.json and not getattr(args, "lint", False) and isinstance(units, int):
        print(f"Execution units: {units:,} (maximum 1,000,000).", file=sys.stderr)
        if isinstance(warning, str):
            print(f"Warning: {warning}", file=sys.stderr)
    warnings = (
        [{"code": "long_running_workflow", "message": warning}]
        if isinstance(warning, str)
        else []
    )
    return admitted_request, summary, warnings


def _run_sequence(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        core_request = _sequence_request_for_args(args)
        core_request, execution_summary, execution_warnings = _workflow_start_summary(
            args, core_request
        )
    except (SafetyConfigError, SafetyValidationError, CoreValidationError, ValueError, OSError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code=_core_validation_code(exc),
            message=str(exc),
            retryable=False,
        )

    try:
        with _cooperative_workflow_interrupt() as stop_event:
            data = run_core_command(
                core_request,
                opener=_core_opener_for_args(args),
                stop_requested=stop_event.is_set,
                sleep=time.sleep,
                scpi_logger=_log_scpi,
            )
    except (CommandCancelled, StopCleanupError) as exc:
        return _emit_workflow_interruption(args, request=request, execution=execution, exc=exc)
    except KeyboardInterrupt:
        return _emit_workflow_interruption(
            args,
            request=request,
            execution=execution,
            exc=CommandCancelled("sequence cancelled before a VISA session was opened"),
        )
    except CoreIoError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="sequence_failed",
            message=str(exc),
        )
    except CoreExecutionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="sequence_failed",
            message=str(exc),
            data=dict(getattr(exc, "data", {}) or {})
            or ({"trigger": exc.trigger} if exc.trigger is not None else None),
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
    except (SafetyValidationError, ValueError, OSError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )

    if "idn" in data and isinstance(data.get("resource"), str):
        data["resource"] = _resource_payload(
            data["resource"],
            simulated=args.simulate,
            reachable=True,
            idn_raw=data["idn"],
        )
        data.pop("idn", None)

    if args.json:
        emit_json_success(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=not args.lint),
            request=request,
            data=data,
            warnings=execution_warnings,
        )
    else:
        if args.lint:
            _emit_text_lines(cli_rendering.format_sequence_lint_summary(data))
        else:
            _print_sequence_summary(data)
    return 0


def _run_ramp_list(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        core_request = _ramp_list_request_for_args(args)
        core_request, execution_summary, execution_warnings = _workflow_start_summary(
            args, core_request
        )
        with _cooperative_workflow_interrupt() as stop_event:
            data = run_core_command(
                core_request,
                opener=_core_opener_for_args(args),
                stop_requested=stop_event.is_set,
                sleep=time.sleep,
                scpi_logger=_log_scpi,
            )
    except (CommandCancelled, StopCleanupError) as exc:
        return _emit_workflow_interruption(
            args,
            request=request,
            execution=_execution_for_args(args, hardware_intent=not getattr(args, "lint", False)),
            exc=exc,
        )
    except KeyboardInterrupt:
        return _emit_workflow_interruption(
            args,
            request=request,
            execution=_execution_for_args(args, hardware_intent=not getattr(args, "lint", False)),
            exc=CommandCancelled("ramp-list cancelled before a VISA session was opened"),
        )
    except CoreValidationError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code=_core_validation_code(exc),
            message=str(exc),
            retryable=False,
            hardware_intent=not getattr(args, "lint", False),
        )
    except (SafetyConfigError, SafetyValidationError, ValueError, OSError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=not getattr(args, "lint", False),
        )
    except CoreIoError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=_execution_for_args(args, hardware_intent=True),
            code="ramp_list_failed" if exc.opened else "connection_failed",
            message=str(exc),
        )
    except CoreExecutionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=_execution_for_args(args, hardware_intent=True),
            code="ramp_list_failed",
            message=str(exc),
            data=dict(getattr(exc, "data", {}) or {})
            or ({"trigger": exc.trigger} if exc.trigger is not None else None),
        )

    if data["status"] in {"failed", "stopped"}:
        failed = data.get("failed_segment") or {}
        message = (
            f"ramp-list stopped at segment {failed.get('index')}"
            if data["status"] == "stopped"
            else f"ramp-list segment {failed.get('index')} failed: {failed.get('message', 'segment failed')}"
        )
        if args.json:
            emit_json_error(
                command=args.command,
                execution=_execution_for_args(args, hardware_intent=True),
                request=request,
                error_type="execution",
                code="stopped" if data["status"] == "stopped" else "ramp_list_failed",
                message=message,
                retryable=True,
            )
        else:
            print(message, file=sys.stderr)
        return 3
    if args.json:
        emit_json_success(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=not args.lint),
            request=request,
            data=data,
            warnings=execution_warnings,
        )
    else:
        _emit_text_lines(cli_rendering.format_ramp_list_summary(data))
    return 0


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
        selection = select_driver(idn_raw)
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


def _load_sequence_document(path: str) -> dict[str, Any]:
    sequence_path = Path(path)
    try:
        text = sequence_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"could not read sequence file {sequence_path}: {exc}") from exc
    stripped = text.lstrip()
    if stripped.startswith("{"):
        parsed = json.loads(text)
    else:
        try:
            import yaml  # type: ignore[import-untyped]
        except ModuleNotFoundError:
            parsed = _parse_simple_sequence_yaml(text)
        else:
            parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError("sequence file must contain a mapping")
    return parsed


def _parse_simple_sequence_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_steps = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", maxsplit=1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped == "steps:":
            in_steps = True
            data["steps"] = steps
            continue
        if not in_steps:
            if ":" not in stripped:
                raise ValueError(f"unsupported sequence YAML line: {raw_line}")
            key, value = stripped.split(":", maxsplit=1)
            data[key.strip()] = _parse_sequence_scalar(value.strip())
            continue
        if stripped.startswith("- "):
            current = {}
            steps.append(current)
            item = stripped[2:].strip()
            if item:
                if ":" not in item:
                    current["action"] = item
                else:
                    key, value = item.split(":", maxsplit=1)
                    current[key.strip()] = _parse_sequence_scalar(value.strip())
            continue
        if current is None or ":" not in stripped:
            raise ValueError(f"unsupported sequence YAML line: {raw_line}")
        key, value = stripped.split(":", maxsplit=1)
        current[key.strip()] = _parse_sequence_scalar(value.strip())
    return data


def _parse_sequence_scalar(value: str) -> Any:
    if value == "":
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.lower() == "all":
        return "all"
    try:
        if any(marker in value for marker in (".", "e", "E")):
            return float(value)
        return int(value)
    except ValueError:
        return value.strip("'\"")


def _sequence_plan(args: argparse.Namespace, document: dict[str, Any]) -> dict[str, Any]:
    version = document.get("version", 1)
    if version not in (1, "1"):
        raise ValueError(f"unsupported sequence version: {version}")
    raw_steps = document.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("sequence requires a non-empty steps list")
    steps = []
    for index, raw_step in enumerate(raw_steps, start=1):
        step = _normalize_sequence_step(index, raw_step)
        _validate_sequence_step(args, step)
        steps.append(step)
    return {
        "version": 1,
        "operation": {"name": "sequence"},
        "target": {"resource": args.resource, "resource_alias": args.resource_alias},
        "steps": steps,
        "hardware_touched": False,
    }


def _add_sequence_scpi_previews(plan: dict[str, Any]) -> None:
    for step in plan["steps"]:
        preview = _sequence_step_preview(step)
        if preview:
            step["preview"] = preview


def _sequence_step_preview(step: dict[str, Any]) -> dict[str, Any] | None:
    action = step["action"]
    parameters = step["parameters"]
    if action == "set":
        channel = _sequence_channel(parameters.get("channel", 1))
        voltage = _format_text_value(float(parameters["voltage"]))
        current = _format_text_value(float(parameters["current"]))
        return {"commands": [f"CURR {current},(@{channel})", f"VOLT {voltage},(@{channel})"]}
    if action == "apply":
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=True)
        voltage = _format_text_value(float(parameters["voltage"]))
        current = _format_text_value(float(parameters["current"]))
        commands: list[str] = []
        for selected_channel in _sequence_preview_channels(channel):
            commands.append(f"CURR {current},(@{selected_channel})")
            commands.append(f"VOLT {voltage},(@{selected_channel})")
            if not parameters.get("no_output", False):
                commands.append(f"OUTP ON,(@{selected_channel})")
        return {"commands": commands}
    if action == "output-on":
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=True)
        return {"commands": [f"OUTP ON,(@{selected_channel})" for selected_channel in _sequence_preview_channels(channel)]}
    if action == "output-off":
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=True)
        return {"commands": [f"OUTP OFF,(@{selected_channel})" for selected_channel in _sequence_preview_channels(channel)]}
    if action == "output-state":
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=True)
        return {"commands": [f"OUTP? (@{selected_channel})" for selected_channel in _sequence_preview_channels(channel)]}
    if action == "cycle-output":
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=True)
        commands = [f"OUTP ON,(@{selected_channel})" for selected_channel in _sequence_preview_channels(channel)]
        commands.extend(f"OUTP OFF,(@{selected_channel})" for selected_channel in _sequence_preview_channels(channel))
        return {"commands": commands, "duration_ms": int(parameters.get("duration_ms", 500))}
    if action == "safe-off":
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=True)
        return {"commands": [f"OUTP OFF,(@{selected_channel})" for selected_channel in _sequence_preview_channels(channel)]}
    return None


def _sequence_preview_channels(channel: int | str) -> tuple[int, ...]:
    if channel == "all":
        return E36312APowerSupply.capabilities.channels
    return (int(channel),)


def _normalize_sequence_step(index: int, raw_step: Any) -> dict[str, Any]:
    if isinstance(raw_step, str):
        return {"index": index, "action": raw_step, "parameters": {}}
    if not isinstance(raw_step, dict):
        raise ValueError(f"sequence step {index} must be a mapping")
    if "action" in raw_step or "type" in raw_step:
        action = str(raw_step.get("action", raw_step.get("type")))
        parameters = {key: value for key, value in raw_step.items() if key not in {"action", "type"}}
    elif len(raw_step) == 1:
        action, value = next(iter(raw_step.items()))
        parameters = value if isinstance(value, dict) else {}
    else:
        raise ValueError(f"sequence step {index} requires action")
    if action not in _SEQUENCE_ACTIONS:
        raise ValueError(f"unsupported sequence step {index} action: {action}")
    return {"index": index, "action": action, "parameters": parameters}


_SEQUENCE_ACTIONS = {
    "measure",
    "readback",
    "output-state",
    "log",
    "wait",
    "safe-off",
    "set",
    "output-on",
    "output-off",
    "cycle-output",
    "apply",
}


_SEQUENCE_OUTPUT_ACTIONS = {"safe-off", "set", "output-on", "output-off", "cycle-output", "apply"}


def _validate_sequence_step(args: argparse.Namespace, step: dict[str, Any]) -> None:
    action = step["action"]
    parameters = step["parameters"]
    if action in {"measure", "readback", "output-state", "safe-off", "output-on", "output-off", "cycle-output"}:
        _sequence_channel(parameters.get("channel", 1), allow_all=(action in {"safe-off", "output-state", "output-on", "output-off", "cycle-output"}))
    if action == "wait":
        seconds = float(parameters.get("seconds", parameters.get("duration_sec", 0)))
        if seconds < 0:
            raise ValueError("wait seconds must be non-negative")
    if action in {"set", "apply"}:
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=(action == "apply"))
        voltage = float(parameters["voltage"])
        current = float(parameters["current"])
        safety_limits = _safety_limits_for_args(args)
        channels = (1, 2, 3) if channel == "all" else (channel,)
        for selected_channel in channels:
            validate_setpoint(
                channel=selected_channel,
                voltage=voltage,
                current=current,
                limits=safety_limits,
            )
    elif action in {"output-on", "output-off", "cycle-output"}:
        safety_limits = _safety_limits_for_args(args)
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=True)
        duration_ms = int(parameters.get("duration_ms", 500))
        if action == "cycle-output" and duration_ms < 0:
            raise ValueError("cycle-output duration_ms must be non-negative")
        for selected_channel in _sequence_preview_channels(channel):
            validate_channel(selected_channel, safety_limits)


def _sequence_channel(value: Any, *, allow_all: bool = False) -> int | str:
    if allow_all and isinstance(value, str) and value.lower() == "all":
        return "all"
    try:
        channel = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("sequence channel must be a positive integer") from exc
    if channel < 1:
        raise ValueError("sequence channel must be a positive integer")
    return channel


def _execute_sequence(
    args: argparse.Namespace,
    plan: dict[str, Any],
    manager: SimulatedResourceManager | None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    completed_steps = 0
    failed_step: dict[str, Any] | None = None
    stopped = False
    safe_off_attempted = False
    cleanup_errors: list[dict[str, Any]] = []
    idn_raw: str | None = None
    with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
        session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
        idn_raw = session.query(IDN_QUERY)
        power_supply = create_power_supply(session, idn_raw)
        for step in plan["steps"]:
            try:
                result = _execute_sequence_step(args, power_supply, step)
                results.append(result)
                completed_steps += 1
            except KeyboardInterrupt:
                stopped = True
                failed_step = {"index": step["index"], "action": step["action"], "code": "interrupted"}
                break
            except (VisaConnectionError, ValueError, SafetyValidationError) as exc:
                failed_step = {
                    "index": step["index"],
                    "action": step["action"],
                    "code": "step_failed",
                    "message": str(exc),
                }
                break
        if stopped or failed_step is not None:
            cleanup = _sequence_cleanup_safe_off(power_supply)
            safe_off_attempted = cleanup["safe_off_attempted"]
            cleanup_errors = cleanup["errors"]

    status = "stopped" if stopped else ("failed" if failed_step is not None else "completed")
    return {
        "sequence_version": plan["version"],
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "resource_alias": args.resource_alias,
        "plan": plan,
        "status": status,
        "results": results,
        "completed_steps": completed_steps,
        "failed_step": failed_step,
        "stopped": stopped,
        "cleanup": {"safe_off_attempted": safe_off_attempted, "errors": cleanup_errors},
    }


def _execute_sequence_step(
    args: argparse.Namespace,
    power_supply: GenericScpiPowerSupply,
    step: dict[str, Any],
) -> dict[str, Any]:
    action = step["action"]
    parameters = step["parameters"]
    if action in _SEQUENCE_OUTPUT_ACTIONS and not args.simulate and not isinstance(power_supply, OUTPUT_WRITE_POWER_SUPPLY_TYPES):
        raise ValueError("real output-affecting sequence steps are enabled only for E36312A or EDU36311A")
    if action in {"measure", "readback"}:
        _validate_read_only_channel(power_supply, _sequence_channel(parameters.get("channel", 1)), command_label="sequence")
    if action == "output-state":
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=True)
        for selected_channel in _sequence_channels(channel, getattr(power_supply.capabilities, "real_measure_channels", power_supply.capabilities.channels)):
            _validate_read_only_channel(power_supply, selected_channel, command_label="sequence")
    if action == "measure":
        channel = _sequence_channel(parameters.get("channel", 1))
        return {
            "index": step["index"],
            "action": action,
            "channel": channel,
            "measurements": {
                "voltage": power_supply.measure_voltage(channel=channel),
                "current": power_supply.measure_current(channel=channel),
            },
        }
    if action == "readback":
        channel = _sequence_channel(parameters.get("channel", 1))
        return {
            "index": step["index"],
            "action": action,
            "channel": channel,
            "setpoints": {
                "voltage": power_supply.programmed_voltage(channel=channel),
                "current": power_supply.programmed_current(channel=channel),
            },
        }
    if action == "output-state":
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=True)
        outputs = [
            {"channel": selected_channel, "enabled": power_supply.output_state(channel=selected_channel)}
            for selected_channel in _sequence_channels(channel, getattr(power_supply.capabilities, "real_measure_channels", power_supply.capabilities.channels))
        ]
        result = {"index": step["index"], "action": action, "channel": channel, "enabled": outputs[0]["enabled"]}
        if channel == "all":
            result["outputs"] = outputs
        return result
    if action == "log":
        return {"index": step["index"], "action": action, "message": str(parameters.get("message", ""))}
    if action == "wait":
        seconds = float(parameters.get("seconds", parameters.get("duration_sec", 0)))
        time.sleep(seconds)
        return {"index": step["index"], "action": action, "seconds": seconds}
    if action == "safe-off":
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=True)
        for selected_channel in _sequence_channels(channel, power_supply.capabilities.channels):
            power_supply.output_off(channel=selected_channel)
        return {"index": step["index"], "action": action, "channel": channel}
    if action == "output-off":
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=True)
        for selected_channel in _sequence_channels(channel, power_supply.capabilities.channels):
            power_supply.output_off(channel=selected_channel)
        return {"index": step["index"], "action": action, "channel": channel}
    if action == "output-on":
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=True)
        for selected_channel in _sequence_channels(channel, power_supply.capabilities.channels):
            power_supply.output_on(channel=selected_channel)
        return {"index": step["index"], "action": action, "channel": channel}
    if action == "cycle-output":
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=True)
        channels = _sequence_channels(channel, power_supply.capabilities.channels)
        enabled_channels: list[int] = []
        try:
            for selected_channel in channels:
                power_supply.output_on(channel=selected_channel)
                enabled_channels.append(selected_channel)
            time.sleep(int(parameters.get("duration_ms", 500)) / 1000)
        finally:
            for selected_channel in enabled_channels:
                power_supply.output_off(channel=selected_channel)
        return {"index": step["index"], "action": action, "channel": channel, "duration_ms": int(parameters.get("duration_ms", 500))}
    if action in {"set", "apply"}:
        channel = _sequence_channel(parameters.get("channel", 1), allow_all=(action == "apply"))
        voltage = float(parameters["voltage"])
        current = float(parameters["current"])
        for selected_channel in _sequence_channels(channel, power_supply.capabilities.channels):
            power_supply.set_current_limit(channel=selected_channel, current=current)
            power_supply.set_voltage(channel=selected_channel, voltage=voltage)
            if action == "apply" and not parameters.get("no_output", False):
                power_supply.output_on(channel=selected_channel)
        return {"index": step["index"], "action": action, "channel": channel, "voltage": voltage, "current": current}
    raise ValueError(f"unsupported sequence action: {action}")


def _sequence_channels(channel: int | str, supported_channels: tuple[int, ...]) -> tuple[int, ...]:
    if channel == "all":
        return supported_channels
    if int(channel) not in supported_channels:
        raise ValueError(f"channel {channel} is not supported; supported: {supported_channels}")
    return (int(channel),)


def _sequence_cleanup_safe_off(power_supply: GenericScpiPowerSupply) -> dict[str, Any]:
    attempted = False
    errors: list[dict[str, Any]] = []
    for channel in power_supply.capabilities.channels:
        attempted = True
        try:
            power_supply.output_off(channel=channel)
        except Exception as exc:
            errors.append({"channel": channel, "message": str(exc)})
            continue
    return {"safe_off_attempted": attempted, "errors": errors}


def _print_sequence_summary(data: dict[str, Any]) -> None:
    _emit_text_lines(cli_rendering.format_sequence_summary(data))


def _run_core_output_real(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    execution_warnings: list[dict[str, str]] = []

    try:
        safety_limits = _safety_limits_for_args(args)
        request = _request_for_args(args)
        _validate_output_request(args, safety_limits)
    except (SafetyConfigError, SafetyValidationError, ValueError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    def opener(
        resource: str,
        *,
        backend: str | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        serial_options: SerialOptions | None = None,
        serial_remote: bool = False,
        serial_local_on_close: bool = False,
    ):
        return _open_resource(
            resource,
            manager,
            backend=backend,
            timeout_ms=timeout_ms,
            serial_options=serial_options,
            serial_remote=serial_remote,
            serial_local_on_close=serial_local_on_close,
            scpi_logger=_connection_scpi_logger_for_args(args),
        )

    try:
        if args.command == "ramp":
            core_request = _operation_request_for_args(args)
            core_request, _summary, execution_warnings = _workflow_start_summary(
                args, core_request
            )
            with _cooperative_workflow_interrupt() as stop_event:
                data = run_core_command(
                    core_request,
                    opener=opener,
                    stop_requested=stop_event.is_set,
                    sleep=time.sleep,
                    scpi_logger=_log_scpi,
                )
        else:
            data = operations.run_operation(
                _operation_request_for_args(args),
                opener=opener,
                sleep=time.sleep,
                scpi_logger=_log_scpi,
            )
    except (CommandCancelled, StopCleanupError) as exc:
        return _emit_workflow_interruption(args, request=request, execution=execution, exc=exc)
    except KeyboardInterrupt:
        if args.command != "ramp":
            raise
        return _emit_workflow_interruption(
            args,
            request=request,
            execution=execution,
            exc=CommandCancelled("ramp cancelled before a VISA session was opened"),
        )
    except ConfirmationRequiredError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="confirmation_required",
            message=_confirmation_required_message(args.command),
            retryable=False,
            hardware_intent=True,
        )
    except UnsupportedModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code=f"unsupported_model_for_{args.command.replace('-', '_')}",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except UnsupportedChannelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except CoreVerificationError as exc:
        return _emit_verification_error(
            args,
            request,
            execution,
            exc.verification,
            data=dict(getattr(exc, "data", {}) or {})
            or ({"trigger": exc.trigger} if exc.trigger is not None else None),
        )
    except CoreValidationError as exc:
        if "completion-pulse" in str(exc):
            return _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="trigger_native_unsupported",
                message=str(exc),
                retryable=False,
                hardware_intent=True,
            )
        error_type = "safety" if args.command == "output-on" and "exceeds maximum" in str(exc) else "validation"
        code = (
            "unsafe_output_setpoint"
            if error_type == "safety"
            else _core_validation_code(exc)
        )
        return _emit_cli_error(
            args,
            request=request,
            error_type=error_type,
            code=code,
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except CoreIoError as exc:
        failed_code = f"{args.command.replace('-', '_')}_failed"
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code=failed_code if exc.opened else "connection_failed",
            message=str(exc),
        )
    except CoreExecutionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code=f"{args.command.replace('-', '_')}_failed",
            message=str(exc),
            data=dict(getattr(exc, "data", {}) or {})
            or ({"trigger": exc.trigger} if exc.trigger is not None else None),
        )

    try:
        resource_data = _core_output_resource_data(args, data)
    except _InvalidCoreResult as exc:
        return _emit_invalid_core_result(
            args,
            request=request,
            execution=execution,
            message=str(exc),
        )
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=resource_data,
            warnings=execution_warnings,
        )
        return 0

    _print_core_output_result(args, resource_data)
    return 0


def _run_output_plan(args: argparse.Namespace) -> int:
    if not args.simulate and not args.dry_run:
        return _run_core_output_real(args)

    request = _request_for_args(args)
    try:
        safety_limits = _safety_limits_for_args(args)
        request = _request_for_args(args)
        _validate_output_request(args, safety_limits)
    except (SafetyConfigError, SafetyValidationError, ValueError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    if not args.simulate and not args.dry_run:
        return _emit_cli_error(
            args,
            request=request,
            error_type="safety",
            code="real_execution_disabled",
            message=(
                "Real output execution is disabled; use --dry-run to preview the "
                "operation or --simulate for simulator-safe planning."
            ),
            retryable=False,
        )

    try:
        plan = _output_plan_for_args(args)
        execution_warnings: list[dict[str, str]] = []
        if args.command == "ramp":
            units = plan.get("execution_units")
            warning = plan.get("execution_warning")
            if not args.json and isinstance(units, int):
                print(
                    f"Execution units: {units:,} (maximum 1,000,000).",
                    file=sys.stderr,
                )
                if isinstance(warning, str):
                    print(f"Warning: {warning}", file=sys.stderr)
            if isinstance(warning, str):
                execution_warnings.append(
                    {"code": "long_running_workflow", "message": warning}
                )
        if getattr(args, "completion_pulse_timing", "segment") != "step":
            _append_completion_pulse_plan(args, plan)
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
    if args.json:
        emit_json_success(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=args.command != "safe-off"),
            request=request,
            data={"plan": plan},
            warnings=execution_warnings,
        )
        return 0

    _print_output_plan(plan, mode=_mode_for_args(args), dry_run=args.dry_run)
    return 0


def _query_idn(
    resource: str,
    *,
    resource_manager: SimulatedResourceManager | None,
    backend: str | None,
    timeout_ms: int,
    log_scpi: bool,
) -> str | None:
    try:
        with _open_resource(
            resource,
            resource_manager,
            backend=backend,
            timeout_ms=timeout_ms,
        ) as instrument:
            if log_scpi:
                _log_scpi(resource, ">>", IDN_QUERY)
            response = instrument.identify()
            if log_scpi:
                _log_scpi(resource, "<<", response)
            return response
    except (VisaConnectionError, ValueError):
        return None


def _read_error_queue(
    resource: str,
    *,
    resource_manager: SimulatedResourceManager | None,
    backend: str | None,
    timeout_ms: int,
    log_scpi: bool,
    max_reads: int,
) -> tuple[list[str], int]:
    errors: list[str] = []
    read_count = 0
    with _open_resource(
        resource,
        resource_manager,
        backend=backend,
        timeout_ms=timeout_ms,
    ) as instrument:
        for _ in range(max_reads):
            if log_scpi:
                _log_scpi(resource, ">>", ERROR_QUERY)
            response = instrument.query(ERROR_QUERY)
            read_count += 1
            if log_scpi:
                _log_scpi(resource, "<<", response)
            if _is_no_error_response(response):
                break
            errors.append(response)
    return errors, read_count


def _collect_log_samples(
    args: argparse.Namespace,
    resource_manager: SimulatedResourceManager | None,
    *,
    backend: str | None,
    timeout_ms: int,
) -> dict[str, Any]:
    samples_written = 0
    idn_raw: str | None = None
    interrupted = False
    with _open_resource(
        args.resource,
        resource_manager,
        backend=backend,
        timeout_ms=timeout_ms,
    ) as instrument:
        session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
        idn_raw = session.query(IDN_QUERY)
        _enforce_live_cli_scope(args, idn_raw, command="log")
        idn = parse_idn(idn_raw)
        power_supply = create_power_supply(session, idn_raw)
        channels = _log_channels_for_power_supply(args, power_supply)

        csv_path = Path(args.csv)
        if csv_path.parent != Path("."):
            csv_path.parent.mkdir(parents=True, exist_ok=True)
        jsonl_file = _open_jsonl_log(args)
        mode = "a" if args.append else "w"
        write_header = (not args.append) or (not csv_path.exists()) or csv_path.stat().st_size == 0
        with csv_path.open(mode, newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=LOG_CSV_FIELDS)
            if write_header:
                writer.writeheader()
            start = time.monotonic()
            try:
                while True:
                    if not _should_collect_log_sample(args, samples_written, start):
                        break
                    try:
                        for channel in channels:
                            row = _read_log_row(args, power_supply, idn, channel=channel)
                            writer.writerow(row)
                            if jsonl_file is not None:
                                jsonl_file.write(json.dumps({"event": "sample", "sample": row}, sort_keys=True) + "\n")
                        csv_file.flush()
                        if jsonl_file is not None:
                            jsonl_file.flush()
                        samples_written += 1
                        if not _should_collect_log_sample(args, samples_written, start):
                            break
                        time.sleep(args.interval_sec)
                    except KeyboardInterrupt:
                        interrupted = True
                        break
            finally:
                if jsonl_file is not None:
                    jsonl_file.write(
                        json.dumps(
                            {
                                "event": "summary",
                                "samples_written": samples_written,
                                "channels": list(channels),
                                "stopped": interrupted,
                                "stop_reason": "interrupted" if interrupted else "completed",
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    jsonl_file.close()

    return {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "resource_alias": args.resource_alias,
        "csv": args.csv,
        "jsonl": args.jsonl,
        "append": args.append,
        "channel": args.channel,
        "channels": list(channels),
        "samples_requested": args.samples,
        "duration_sec": args.duration_sec,
        "interval_sec": args.interval_sec,
        "samples_written": samples_written,
        "stopped": interrupted,
        "stop_reason": "interrupted" if interrupted else "completed",
    }


def _should_collect_log_sample(args: argparse.Namespace, samples_written: int, start: float) -> bool:
    if args.samples is not None and samples_written >= args.samples:
        return False
    if args.duration_sec is not None and samples_written > 0:
        return (time.monotonic() - start) < args.duration_sec
    return True


def _log_channels_for_power_supply(
    args: argparse.Namespace,
    power_supply: GenericScpiPowerSupply,
) -> tuple[int, ...]:
    requested = args.channels if args.channels is not None else args.channel
    if requested == "all":
        channels = power_supply.capabilities.channels
    elif isinstance(requested, tuple):
        channels = requested
    else:
        channels = (requested,)
    for channel in channels:
        _validate_read_only_channel(power_supply, channel, command_label="log")
    return tuple(int(channel) for channel in channels)


def _open_jsonl_log(args: argparse.Namespace):
    if args.jsonl is None:
        return None
    path = Path(args.jsonl)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.append else "w"
    return path.open(mode, encoding="utf-8")


def _read_log_row(
    args: argparse.Namespace,
    power_supply: GenericScpiPowerSupply,
    idn: Any,
    *,
    channel: int,
) -> dict[str, Any]:
    errors = power_supply.check_errors(20)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "resource": args.resource,
        "resource_alias": args.resource_alias or "",
        "model": idn.model or "",
        "serial": idn.serial or "",
        "channel": channel,
        "programmed_voltage": power_supply.programmed_voltage(channel=channel),
        "programmed_current": power_supply.programmed_current(channel=channel),
        "measured_voltage": power_supply.measure_voltage(channel=channel),
        "measured_current": power_supply.measure_current(channel=channel),
        "output_enabled": power_supply.output_state(channel=channel),
        "errors": "; ".join(errors),
    }


def _measure_voltage_current(
    resource: str,
    *,
    resource_manager: SimulatedResourceManager | None,
    backend: str | None,
    timeout_ms: int,
    log_scpi: bool,
    channel: int,
    simulate: bool,
) -> dict[str, float]:
    with _open_resource(
        resource,
        resource_manager,
        backend=backend,
        timeout_ms=timeout_ms,
    ) as instrument:
        if simulate:
            return _measure_voltage_current_with_driver(
                resource,
                instrument,
                channel=channel,
                log_scpi=log_scpi,
                mode="simulate",
            )

        if channel not in GenericScpiPowerSupply.capabilities.real_measure_channels:
            return _measure_voltage_current_with_driver(
                resource,
                instrument,
                channel=channel,
                log_scpi=log_scpi,
                mode="real",
            )

        if log_scpi:
            _log_scpi(resource, ">>", MEASURE_VOLTAGE_QUERY)
        voltage_response = instrument.query(MEASURE_VOLTAGE_QUERY)
        if log_scpi:
            _log_scpi(resource, "<<", voltage_response)
            _log_scpi(resource, ">>", MEASURE_CURRENT_QUERY)
        current_response = instrument.query(MEASURE_CURRENT_QUERY)
        if log_scpi:
            _log_scpi(resource, "<<", current_response)

    return {
        "voltage": _parse_measurement(voltage_response, "voltage"),
        "current": _parse_measurement(current_response, "current"),
    }


def _measure_voltage_current_with_driver(
    resource: str,
    instrument: Any,
    *,
    channel: int,
    log_scpi: bool,
    mode: str,
) -> dict[str, float]:
    session = _ScpiLoggingSession(resource, instrument) if log_scpi else instrument
    idn = session.query(IDN_QUERY)
    power_supply = create_power_supply(session, idn)
    capabilities = power_supply.capabilities
    allowed_channels = (
        capabilities.simulated_measure_channels
        if mode == "simulate"
        else capabilities.real_measure_channels
    )
    if channel not in allowed_channels:
        raise _MeasureChannelUnsupported(
            _unsupported_measure_channel_message(
                channel=channel,
                mode=mode,
                driver_name=type(power_supply).__name__,
                allowed_channels=allowed_channels,
            )
        )

    return {
        "voltage": power_supply.measure_voltage(channel=channel),
        "current": power_supply.measure_current(channel=channel),
    }


def _validate_log_request(args: argparse.Namespace) -> None:
    if args.samples is None and args.duration_sec is None:
        raise ValueError("log requires --samples or --duration-sec")
    if args.samples is not None and args.duration_sec is not None:
        raise ValueError("log accepts either --samples or --duration-sec, not both")


def _validate_read_only_channel(
    power_supply: GenericScpiPowerSupply,
    channel: int,
    *,
    command_label: str,
) -> None:
    if not isinstance(power_supply, (E36312APowerSupply, EDU36311APowerSupply)):
        raise _ReadOnlyModelError(
            f"{command_label} is only supported for E36312A or EDU36311A; "
            f"found {type(power_supply).__name__} from *IDN? response"
        )
    if channel not in power_supply.capabilities.channels:
        raise _ReadOnlyChannelError(
            f"channel {channel} is not supported for {command_label}; "
            f"supported: {power_supply.capabilities.channels}"
        )


def _resolve_optional_resource_alias(args: argparse.Namespace) -> None:
    if getattr(args, "resource_alias", None) is None:
        return
    _safety_limits_for_args(args)


def _trigger_pulse_scpi(
    pins: Sequence[int],
    polarity: str,
    channel: int,
    *,
    exclusive_pins: bool = False,
) -> tuple[str, ...]:
    polarity_command = "POS" if polarity == "positive" else "NEG"
    selected_pins = tuple(pins)
    clear_commands = tuple(
        f"DIG:PIN{other_pin}:FUNC DIO"
        for other_pin in (1, 2, 3)
        if exclusive_pins and other_pin not in selected_pins
    )
    configure_commands = tuple(
        command
        for pin in selected_pins
        for command in (
            f"DIG:PIN{pin}:FUNC TOUT",
            f"DIG:PIN{pin}:POL {polarity_command}",
        )
    )
    return clear_commands + configure_commands + (
        "DIG:TOUT:BUS ON",
        f"CURR:TRIG <current-readback>,(@{channel})",
        f"VOLT:TRIG <voltage-readback>,(@{channel})",
        f"CURR:MODE STEP,(@{channel})",
        f"VOLT:MODE STEP,(@{channel})",
        f"TRIG:SOUR BUS,(@{channel})",
        f"INIT (@{channel})",
        "*TRG",
    )


def _read_error_queue_from_driver(
    power_supply: GenericScpiPowerSupply,
    max_reads: int,
) -> tuple[list[str], int]:
    if max_reads < 1:
        raise ValueError("max_errors must be at least 1")

    return power_supply.read_error_queue(max_reads)


def _raise_on_instrument_errors(
    power_supply: GenericScpiPowerSupply,
    operation: str,
    *,
    max_reads: int = 20,
) -> None:
    errors, _ = _read_error_queue_from_driver(power_supply, max_reads)
    if errors:
        raise ValueError(
            f"{operation} left instrument error queue entries: "
            + "; ".join(errors)
        )


def _collect_readback(
    args: argparse.Namespace,
    power_supply: GenericScpiPowerSupply,
    idn_raw: str,
    channels: tuple[int, ...],
) -> dict[str, Any]:
    return {
        "resource": args.resource,
        "channels": [
            {
                "channel": channel,
                "setpoints": {
                    "voltage": power_supply.programmed_voltage(channel=channel),
                    "current": power_supply.programmed_current(channel=channel),
                },
            }
            for channel in channels
        ],
    }


def _collect_status(
    args: argparse.Namespace,
    power_supply: GenericScpiPowerSupply,
    idn_raw: str,
    channels: tuple[int, ...],
) -> dict[str, Any]:
    errors, read_count = _read_error_queue_from_driver(power_supply, args.max_errors)
    return {
        "resource": args.resource,
        "errors": errors,
        "read_count": read_count,
        "outputs": [
            {"channel": channel, "enabled": power_supply.output_state(channel=channel)}
            for channel in channels
        ],
    }


def _collect_protection_status(
    args: argparse.Namespace,
    power_supply: GenericScpiPowerSupply,
    idn_raw: str,
    channels: tuple[int, ...],
) -> dict[str, Any]:
    protection = _protection_payload(power_supply)
    tripped = protection["over_voltage_tripped"] or protection["over_current_tripped"]
    protection_by_channel = [
        {
            "channel": channel,
            "protection": {
                "over_voltage_tripped": protection["over_voltage_tripped"],
                "over_current_tripped": protection["over_current_tripped"],
            },
        }
        for channel in channels
    ]
    return {
        "resource": args.resource,
        "protection": protection,
        "protection_by_channel": protection_by_channel,
        "outputs": [
            {
                "channel": channel,
                "enabled": (enabled := power_supply.output_state(channel=channel)),
                "disabled_with_protection": (not enabled) and tripped,
            }
            for channel in channels
        ],
    }


def _collect_snapshot(
    args: argparse.Namespace,
    power_supply: E36312APowerSupply,
    idn_raw: str,
    channels: tuple[int, ...],
) -> dict[str, Any]:
    channels = power_supply.capabilities.channels
    errors, read_count = _read_error_queue_from_driver(power_supply, args.max_errors)
    return {
        "resource": args.resource,
        "idn": parse_idn(idn_raw).to_dict(),
        "errors": errors,
        "read_count": read_count,
        "outputs": [
            {"channel": channel, "enabled": power_supply.output_state(channel=channel)}
            for channel in channels
        ],
        "readback": [
            {
                "channel": channel,
                "setpoints": {
                    "voltage": power_supply.programmed_voltage(channel=channel),
                    "current": power_supply.programmed_current(channel=channel),
                },
            }
            for channel in channels
        ],
        "measurements": [
            {
                "channel": channel,
                "measurements": {
                    "voltage": power_supply.measure_voltage(channel=channel),
                    "current": power_supply.measure_current(channel=channel),
                },
            }
            for channel in channels
        ],
        "protection": _protection_payload(power_supply),
        "protection_settings": _protection_settings_payload(
            power_supply,
            channels,
            tolerate_errors=True,
        ),
    }


def _snapshot_compare_tolerances(args: argparse.Namespace) -> dict[str, float]:
    return {
        "setpoint_voltage": args.setpoint_voltage_tolerance,
        "setpoint_current": args.setpoint_current_tolerance,
        "measured_voltage": args.measured_voltage_tolerance,
        "measured_current": args.measured_current_tolerance,
    }


def _compare_snapshot_data(
    current: dict[str, Any],
    baseline_path: str,
    tolerances: dict[str, float],
) -> dict[str, Any]:
    baseline_document = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    baseline = baseline_document.get("data", baseline_document) if isinstance(baseline_document, dict) else baseline_document
    if not isinstance(baseline, dict):
        raise ValueError("baseline must be a JSON object or an envelope containing object data")
    restore_core.validate_snapshot_document(baseline)
    differences: list[dict[str, Any]] = []
    _compare_exact(
        differences,
        "reported_identity",
        baseline.get("reported_identity"),
        current.get("reported_identity"),
    )
    _compare_exact(
        differences,
        "resolved_identity",
        baseline.get("resolved_identity"),
        current.get("resolved_identity"),
    )
    _compare_exact(differences, "errors", baseline.get("errors"), current.get("errors"))
    _compare_exact(differences, "outputs", baseline.get("outputs"), current.get("outputs"))
    _compare_exact(differences, "protection", baseline.get("protection"), current.get("protection"))
    _compare_channel_measurements(
        differences,
        "readback",
        baseline.get("readback", []),
        current.get("readback", []),
        {"voltage": tolerances["setpoint_voltage"], "current": tolerances["setpoint_current"]},
        value_key="setpoints",
    )
    _compare_channel_measurements(
        differences,
        "measurements",
        baseline.get("measurements", []),
        current.get("measurements", []),
        {"voltage": tolerances["measured_voltage"], "current": tolerances["measured_current"]},
        value_key="measurements",
    )
    return {
        "passed": not differences,
        "baseline_path": baseline_path,
        "differences": differences,
        "tolerances": tolerances,
    }


def _compare_exact(differences: list[dict[str, Any]], path: str, expected: Any, actual: Any) -> None:
    if expected != actual:
        differences.append({"path": path, "expected": expected, "actual": actual})


def _compare_channel_measurements(
    differences: list[dict[str, Any]],
    path: str,
    expected_items: Any,
    actual_items: Any,
    tolerances: dict[str, float],
    *,
    value_key: str,
) -> None:
    if not isinstance(expected_items, list) or not isinstance(actual_items, list):
        _compare_exact(differences, path, expected_items, actual_items)
        return
    expected_by_channel = {item.get("channel"): item for item in expected_items if isinstance(item, dict)}
    actual_by_channel = {item.get("channel"): item for item in actual_items if isinstance(item, dict)}
    if expected_by_channel.keys() != actual_by_channel.keys():
        differences.append(
            {
                "path": path,
                "expected_channels": sorted(expected_by_channel.keys()),
                "actual_channels": sorted(actual_by_channel.keys()),
            }
        )
        return
    for channel, expected_item in expected_by_channel.items():
        actual_item = actual_by_channel[channel]
        expected_values = expected_item.get(value_key, {})
        actual_values = actual_item.get(value_key, {})
        for name, tolerance in tolerances.items():
            expected_value = expected_values.get(name)
            actual_value = actual_values.get(name)
            if not _numbers_within_tolerance(expected_value, actual_value, tolerance):
                differences.append(
                    {
                        "path": f"{path}[channel={channel}].{value_key}.{name}",
                        "channel": channel,
                        "expected": expected_value,
                        "actual": actual_value,
                        "tolerance": tolerance,
                    }
                )


def _numbers_within_tolerance(expected: Any, actual: Any, tolerance: float) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        return expected == actual


def _protection_payload(power_supply: GenericScpiPowerSupply) -> dict[str, bool]:
    return {
        "over_voltage_tripped": power_supply.over_voltage_protection_tripped(),
        "over_current_tripped": power_supply.over_current_protection_tripped(),
    }


def _protection_settings_payload(
    power_supply: GenericScpiPowerSupply,
    channels: tuple[int, ...],
    *,
    tolerate_errors: bool = False,
) -> list[dict[str, Any]]:
    settings: list[dict[str, Any]] = []
    for channel in channels:
        try:
            ovp_voltage: float | None = power_supply.over_voltage_protection_level(channel=channel)
        except (VisaConnectionError, ValueError):
            if not tolerate_errors:
                raise
            ovp_voltage = None
        try:
            ocp_enabled: bool | None = power_supply.over_current_protection_enabled(channel=channel)
        except (VisaConnectionError, ValueError):
            if not tolerate_errors:
                raise
            ocp_enabled = None
        try:
            ocp_delay: float | None = power_supply.over_current_protection_delay(channel=channel)
        except (VisaConnectionError, ValueError):
            if not tolerate_errors:
                raise
            ocp_delay = None
        try:
            ocp_delay_trigger: str | None = power_supply.over_current_protection_delay_trigger(channel=channel)
        except (VisaConnectionError, ValueError):
            if not tolerate_errors:
                raise
            ocp_delay_trigger = None
        settings.append(
            {
                "channel": channel,
                "protection": {
                    "ovp_voltage": ovp_voltage,
                    "ocp_enabled": ocp_enabled,
                    "ocp_delay": ocp_delay,
                    "ocp_delay_trigger": ocp_delay_trigger,
                },
            }
        )
    return settings


def _load_snapshot_document(path: str) -> dict[str, Any]:
    document = _load_json_document(path)
    data = document.get("data") if isinstance(document.get("data"), dict) else document
    if not isinstance(data, dict):
        raise ValueError(f"snapshot JSON must contain an object: {path}")
    try:
        return restore_core.validate_snapshot_document(data)
    except CoreValidationError as exc:
        raise ValueError(str(exc)) from exc


def _load_json_document(path: str) -> dict[str, Any]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"could not read JSON file {path}: {exc}") from exc
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return parsed


def _diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    _diff_channel_records(
        differences,
        category="output",
        field_path=("enabled",),
        before_records=before.get("outputs"),
        after_records=after.get("outputs"),
    )
    _diff_channel_records(
        differences,
        category="setpoint",
        field_path=("setpoints", "voltage"),
        before_records=before.get("readback"),
        after_records=after.get("readback"),
    )
    _diff_channel_records(
        differences,
        category="setpoint",
        field_path=("setpoints", "current"),
        before_records=before.get("readback"),
        after_records=after.get("readback"),
    )
    _diff_channel_records(
        differences,
        category="measurement",
        field_path=("measurements", "voltage"),
        before_records=before.get("measurements"),
        after_records=after.get("measurements"),
    )
    _diff_channel_records(
        differences,
        category="measurement",
        field_path=("measurements", "current"),
        before_records=before.get("measurements"),
        after_records=after.get("measurements"),
    )
    _diff_channel_records(
        differences,
        category="protection_setting",
        field_path=("protection", "ovp_voltage"),
        before_records=before.get("protection_settings"),
        after_records=after.get("protection_settings"),
    )
    _diff_channel_records(
        differences,
        category="protection_setting",
        field_path=("protection", "ocp_enabled"),
        before_records=before.get("protection_settings"),
        after_records=after.get("protection_settings"),
    )
    _diff_channel_records(
        differences,
        category="protection_setting",
        field_path=("protection", "ocp_delay"),
        before_records=before.get("protection_settings"),
        after_records=after.get("protection_settings"),
    )
    _diff_channel_records(
        differences,
        category="protection_setting",
        field_path=("protection", "ocp_delay_trigger"),
        before_records=before.get("protection_settings"),
        after_records=after.get("protection_settings"),
    )
    if before.get("errors", []) != after.get("errors", []):
        differences.append(
            {
                "category": "error_queue",
                "field": "errors",
                "before": before.get("errors", []),
                "after": after.get("errors", []),
            }
        )
    if before.get("protection") != after.get("protection"):
        differences.append(
            {
                "category": "protection_trip",
                "field": "protection",
                "before": before.get("protection"),
                "after": after.get("protection"),
            }
        )
    return differences


def _diff_channel_records(
    differences: list[dict[str, Any]],
    *,
    category: str,
    field_path: tuple[str, ...],
    before_records: Any,
    after_records: Any,
) -> None:
    before_by_channel = _records_by_channel(before_records)
    after_by_channel = _records_by_channel(after_records)
    for channel in sorted(set(before_by_channel) | set(after_by_channel)):
        before_value = _nested_value(before_by_channel.get(channel), field_path)
        after_value = _nested_value(after_by_channel.get(channel), field_path)
        if before_value != after_value:
            differences.append(
                {
                    "category": category,
                    "channel": channel,
                    "field": ".".join(field_path),
                    "before": before_value,
                    "after": after_value,
                }
            )


def _records_by_channel(records: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(records, list):
        return {}
    by_channel: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        channel = record.get("channel")
        if isinstance(channel, int):
            by_channel[channel] = record
    return by_channel


def _nested_value(record: dict[str, Any] | None, path: tuple[str, ...]) -> Any:
    current: Any = record
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _build_hardware_report(args: argparse.Namespace) -> dict[str, Any]:
    input_dir = Path(args.input_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        raise ValueError(f"input-dir is not a directory: {args.input_dir}")
    artifacts = []
    for path in sorted(input_dir.glob("*.json")):
        try:
            document = _load_json_document(str(path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            artifacts.append({"path": str(path), "parse_error": str(exc)})
            continue
        artifacts.append(
            {
                "path": str(path),
                "command": _nested_value(document, ("command", "name")),
                "ok": document.get("ok"),
                "status": document.get("status"),
                "error_code": _nested_value(document, ("error", "code")),
                "hardware_touched": _nested_value(document, ("execution", "hardware_touched")),
            }
        )
    failures = [
        artifact
        for artifact in artifacts
        if artifact.get("parse_error") or artifact.get("ok") is False
    ]
    diff: dict[str, Any] | None = None
    if args.before_json and args.after_json:
        before = _load_snapshot_document(args.before_json)
        after = _load_snapshot_document(args.after_json)
        differences = _diff_snapshots(before, after)
        diff = {
            "before": args.before_json,
            "after": args.after_json,
            "changed": bool(differences),
            "change_count": len(differences),
            "differences": differences,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "hardware_report",
        "target": args.target,
        "connection": args.connection,
        "resource": args.resource,
        "input_dir": args.input_dir,
        "result": "failed" if failures else "passed",
        "artifact_count": len(artifacts),
        "failure_count": len(failures),
        "artifacts": artifacts,
        "failures": failures,
        "snapshot_diff": diff,
    }


def _write_hardware_report_files(report: dict[str, Any], report_json: str, summary_md: str) -> None:
    report_path = Path(report_json)
    summary_path = Path(summary_md)
    if report_path.parent != Path("."):
        report_path.parent.mkdir(parents=True, exist_ok=True)
    if summary_path.parent != Path("."):
        summary_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        f"# {report['target']} Hardware Report",
        "",
        f"Result: {str(report['result']).upper()}",
        "",
        f"Connection: `{report['connection']}`",
        f"Resource: `{report['resource']}`",
        f"Artifacts: {report['artifact_count']}",
        f"Failures: {report['failure_count']}",
    ]
    diff = report.get("snapshot_diff")
    if isinstance(diff, dict):
        lines.extend(
            [
                "",
                "## Snapshot Diff",
                f"Changed: {str(diff['changed']).lower()}",
                f"Changes: {diff['change_count']}",
            ]
        )
    if report["failures"]:
        lines.append("")
        lines.append("## Failures")
        for failure in report["failures"]:
            lines.append(f"- `{failure['path']}` {failure.get('error_code') or failure.get('parse_error')}")
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _restore_channels_from_args(args: argparse.Namespace, snapshot: dict[str, Any]) -> tuple[int, ...]:
    available = sorted(_records_by_channel(snapshot.get("readback")))
    if not available:
        available = list(E36312APowerSupply.capabilities.channels)
    if args.channel == "all":
        return tuple(channel for channel in available if channel in E36312APowerSupply.capabilities.channels)
    channel = int(args.channel)
    if channel not in E36312APowerSupply.capabilities.channels:
        raise ValueError(f"channel {channel} is not supported; supported: {E36312APowerSupply.capabilities.channels}")
    if channel not in available:
        raise ValueError(f"snapshot does not contain channel {channel}")
    return (channel,)


def _restore_plan(
    snapshot: dict[str, Any],
    *,
    resource: str,
    channels: tuple[int, ...],
    restore_output_state: bool,
    allow_output_on: bool,
) -> dict[str, Any]:
    outputs = _records_by_channel(snapshot.get("outputs"))
    readback = _records_by_channel(snapshot.get("readback"))
    protection = _records_by_channel(snapshot.get("protection_settings"))
    steps: list[dict[str, Any]] = []
    for channel in channels:
        steps.append(_restore_step("output_off", f"OUTP OFF,(@{channel})", channel=channel))
        protection_record = protection.get(channel, {}).get("protection", {})
        ovp_voltage = protection_record.get("ovp_voltage")
        if ovp_voltage is not None:
            steps.append(
                _restore_step(
                    "set_over_voltage_protection",
                    f"VOLT:PROT {_format_text_value(ovp_voltage)},(@{channel})",
                    channel=channel,
                    voltage=ovp_voltage,
                )
            )
        ocp_enabled = protection_record.get("ocp_enabled")
        if ocp_enabled is not None:
            ocp_command = "ON" if ocp_enabled else "OFF"
            steps.append(
                _restore_step(
                    "set_over_current_protection_enabled",
                    f"CURR:PROT:STAT {ocp_command},(@{channel})",
                    channel=channel,
                    enabled=ocp_enabled,
                )
            )
        ocp_delay = protection_record.get("ocp_delay")
        if ocp_delay is not None:
            steps.append(
                _restore_step(
                    "set_over_current_protection_delay",
                    f"CURR:PROT:DEL {_format_text_value(ocp_delay)},(@{channel})",
                    channel=channel,
                    seconds=ocp_delay,
                )
            )
        ocp_delay_trigger = protection_record.get("ocp_delay_trigger")
        if ocp_delay_trigger is not None:
            trigger_command = _ocp_delay_trigger_scpi(ocp_delay_trigger)
            steps.append(
                _restore_step(
                    "set_over_current_protection_delay_trigger",
                    f"CURR:PROT:DEL:STAR {trigger_command},(@{channel})",
                    channel=channel,
                    trigger=ocp_delay_trigger,
                )
            )
        setpoints = readback.get(channel, {}).get("setpoints", {})
        if "current" not in setpoints or "voltage" not in setpoints:
            raise ValueError(f"snapshot does not contain voltage/current setpoints for channel {channel}")
        steps.append(
            _restore_step(
                "set_current_limit",
                f"CURR {_format_text_value(setpoints['current'])},(@{channel})",
                channel=channel,
                current=setpoints["current"],
            )
        )
        steps.append(
            _restore_step(
                "set_voltage",
                f"VOLT {_format_text_value(setpoints['voltage'])},(@{channel})",
                channel=channel,
                voltage=setpoints["voltage"],
            )
        )
        if restore_output_state and allow_output_on and outputs.get(channel, {}).get("enabled") is True:
            steps.append(_restore_step("output_on", f"OUTP ON,(@{channel})", channel=channel))
    return {
        "operation": {"name": "restore-from-snapshot"},
        "target": {"resource": resource, "channels": list(channels)},
        "steps": [
            {
                "index": index,
                "type": "driver_action",
                **step,
            }
            for index, step in enumerate(steps, start=1)
        ],
        "description": "Restore output-off, protection settings, current, voltage, and optionally prior ON states.",
        "hardware_touched": False,
    }


def _restore_step(action: str, scpi: str, **parameters: Any) -> dict[str, Any]:
    return {"action": action, "command": scpi, "parameters": parameters}


def _ocp_delay_trigger_scpi(trigger: Any) -> str:
    if trigger == "setting-change":
        return "SCH"
    if trigger == "cc-transition":
        return "CCTR"
    raise ValueError("ocp_delay_trigger must be one of: setting-change, cc-transition")


def _execute_restore_plan(power_supply: E36312APowerSupply, plan: dict[str, Any]) -> None:
    for step in plan["steps"]:
        action = step["action"]
        parameters = step["parameters"]
        channel = parameters["channel"]
        if action == "output_off":
            power_supply.output_off(channel=channel)
        elif action == "set_over_voltage_protection":
            power_supply.set_over_voltage_protection(channel=channel, voltage=float(parameters["voltage"]))
        elif action == "set_over_current_protection_enabled":
            power_supply.set_over_current_protection_enabled(channel=channel, enabled=parameters["enabled"])
        elif action == "set_over_current_protection_delay":
            power_supply.set_over_current_protection_delay(channel=channel, seconds=float(parameters["seconds"]))
        elif action == "set_over_current_protection_delay_trigger":
            power_supply.set_over_current_protection_delay_trigger(channel=channel, trigger=str(parameters["trigger"]))
        elif action == "set_current_limit":
            power_supply.set_current_limit(channel=channel, current=float(parameters["current"]))
        elif action == "set_voltage":
            power_supply.set_voltage(channel=channel, voltage=float(parameters["voltage"]))
        elif action == "output_on":
            power_supply.output_on(channel=channel)
        else:
            raise ValueError(f"unsupported restore action: {action}")


def _validate_restore_identity(idn: Any, expected_idn: dict[str, Any]) -> None:
    expected_model = expected_idn.get("model")
    expected_serial = expected_idn.get("serial")
    if expected_model != "E36312A":
        raise _RestoreIdentityError(
            f"snapshot model must be E36312A for real restore; found {expected_model!r}"
        )
    if idn.model != expected_model:
        raise _RestoreIdentityError(
            f"connected model {idn.model!r} does not match snapshot model {expected_model!r}"
        )
    if idn.serial != expected_serial:
        raise _RestoreIdentityError(
            f"connected serial {idn.serial!r} does not match snapshot serial {expected_serial!r}"
        )


def _validate_readback_for_output_on(
    channel: int,
    setpoints: dict[str, float],
    safety_limits: SafetyLimits,
) -> None:
    validation.validate_output_on_readback(channel, setpoints, safety_limits)


def _setpoint_confirmation_required(
    *,
    voltage: float | None,
    current: float | None,
    limits: SafetyLimits | None,
    confirmed: bool,
) -> bool:
    return validation.confirmation_required_for_request(
        voltage=voltage,
        current=current,
        limits=limits,
        confirmed=confirmed,
    )


def _confirmation_required_message(command: str) -> str:
    return validation.confirmation_required_message(command)


def _channels_from_selection(
    selected_channel: int | str,
    supported_channels: tuple[int, ...],
) -> tuple[int, ...]:
    try:
        return validation.expand_channel_selection(selected_channel, supported_channels)
    except validation.ChannelSelectionError as exc:
        raise _E36312AChannelError(
            str(exc)
        ) from exc


def _read_only_channels_from_selection(
    selected_channel: int | str,
    supported_channels: tuple[int, ...],
) -> tuple[int, ...]:
    try:
        return validation.expand_channel_selection(selected_channel, supported_channels)
    except validation.ChannelSelectionError as exc:
        raise _ReadOnlyChannelError(
            str(exc)
        ) from exc


def _clear_protection_scpi(channels: tuple[int, ...]) -> tuple[str, ...]:
    return tuple(f"OUTP:PROT:CLE (@{channel})" for channel in channels)


def _protection_set_scpi(
    channels: tuple[int, ...],
    ovp_voltage: float | None,
    ocp: str | None,
) -> tuple[str, ...]:
    commands: list[str] = []
    for channel in channels:
        if ovp_voltage is not None:
            commands.append(f"VOLT:PROT {_format_text_value(ovp_voltage)},(@{channel})")
        if ocp is not None:
            commands.append(f"CURR:PROT:STAT {ocp.upper()},(@{channel})")
    return tuple(commands)


def _resource_payload(
    name: str,
    *,
    simulated: bool,
    reachable: bool | None,
    idn_raw: str | None,
) -> dict[str, Any]:
    idn = parse_idn(idn_raw) if idn_raw is not None else None
    identity = None
    if idn is not None:
        try:
            identity = resolve_physical_model_identity(idn.manufacturer, idn.model)
        except IdentityResolutionError:
            identity = None
    return {
        "name": name,
        "interface": resource_interface(name),
        "simulated": simulated,
        "reachable": reachable,
        "idn": idn.to_dict() if idn is not None else None,
        "vendor_id": identity.vendor_id if identity is not None else None,
        "model_id": identity.model_id if identity is not None else None,
    }


def _safe_io_resource_payload(args: argparse.Namespace) -> dict[str, Any]:
    return _resource_payload(
        args.resource,
        simulated=args.simulate,
        reachable=True,
        idn_raw=None,
    )


def _resource_manager_for_args(args: argparse.Namespace) -> SimulatedResourceManager | None:
    if args.simulate:
        return SimulatedResourceManager()
    return None


def _package_version() -> str:
    try:
        return importlib.metadata.version("powers-tool")
    except importlib.metadata.PackageNotFoundError:
        return "0+unknown"


def _safety_limits_payload(limits: SafetyLimits) -> dict[str, Any]:
    return {
        "max_voltage": limits.max_voltage,
        "max_current": limits.max_current,
        "confirm_above_voltage": limits.confirm_above_voltage,
        "confirm_above_current": limits.confirm_above_current,
        "allowed_channels": (
            list(limits.allowed_channels)
            if limits.allowed_channels is not None
            else None
        ),
    }


def _safety_explanation_for_args(
    args: argparse.Namespace,
    limits: SafetyLimits,
    sources: dict[str, str | None],
) -> dict[str, dict[str, Any]]:
    field_sources = _safety_field_sources(args)
    source_layers = [
        {"layer": "global", "name": sources.get("global")},
        {"layer": "model", "name": sources.get("model")},
        {"layer": "resource", "name": sources.get("resource")},
        {"layer": "channel", "name": sources.get("channel")},
    ]
    payload = _safety_limits_payload(limits)
    return {
        field: {
            "value": value,
            "effective_source": field_sources.get(field),
            "source_layers": source_layers,
        }
        for field, value in payload.items()
    }


def _safety_field_sources(args: argparse.Namespace) -> dict[str, str | None]:
    fields = (
        "max_voltage",
        "max_current",
        "confirm_above_voltage",
        "confirm_above_current",
        "allowed_channels",
    )
    sources: dict[str, str | None] = {field: None for field in fields}
    config = load_safety_config_document(args.safety_config)
    if config.global_limits is not None:
        for field in fields:
            if getattr(config.global_limits, field) is not None:
                sources[field] = "global:safety"
    model_id = canonical_physical_model_id(args.model)
    model_name = (
        IDENTITY_INDEXES.models_by_id[model_id].canonical_model
        if model_id is not None
        else None
    )
    model_entry = config.model_limits_for(model_name)
    if model_entry is not None and model_name is not None:
        for field in model_entry[1]:
            sources[field] = f"model:{model_name}"
    entry = None
    if args.resource_alias is not None:
        entry = config.entry_for_alias(args.resource_alias)
    elif args.resource is not None:
        entry = config.entry_for_resource(args.resource)
    if entry is not None:
        for field in entry.limit_fields:
            sources[field] = f"resource:{entry.alias}"
        channel_entry = None
        if isinstance(args.channel, int) and entry.channel_limits is not None:
            channel_entry = entry.channel_limits.get(args.channel)
        if channel_entry is not None:
            for field in channel_entry[1]:
                sources[field] = f"channel:{args.channel}"
    return sources


def _output_affecting_allowed(channel: int | None, limits: SafetyLimits) -> bool:
    if channel is not None:
        try:
            validate_channel(channel, limits)
        except SafetyValidationError:
            return False
    return True


class _OutputOffModelError(ValueError):
    """Raised when output-off is attempted on a non-E36312A model."""


class _OutputOffChannelError(ValueError):
    """Raised when output-off channel is outside E36312A capability (1,2,3)."""


class _OutputOnModelError(ValueError):
    """Raised when output-on is attempted on a non-E36312A model."""


class _OutputOnChannelError(ValueError):
    """Raised when output-on channel is outside E36312A capability (1,2,3)."""


class _SafeOffModelError(ValueError):
    """Raised when safe-off is attempted on a non-E36312A model."""


class _SafeOffChannelError(ValueError):
    """Raised when safe-off channel is outside E36312A capability (1,2,3)."""


class _OutputStateModelError(ValueError):
    """Raised when output-state is attempted on a non-E36312A model."""


class _OutputStateChannelError(ValueError):
    """Raised when output-state channel is outside E36312A capability (1,2,3)."""


class _CycleOutputModelError(ValueError):
    """Raised when cycle-output is attempted on a non-E36312A model."""


class _CycleOutputChannelError(ValueError):
    """Raised when cycle-output channel is outside E36312A capability (1,2,3)."""


class _ApplyModelError(ValueError):
    """Raised when apply is attempted on a non-E36312A model."""


class _ApplyChannelError(ValueError):
    """Raised when apply channel is outside E36312A capability (1,2,3)."""


class _SmokeOutputModelError(ValueError):
    """Raised when smoke-output is attempted on a non-E36312A model."""


class _SmokeOutputChannelError(ValueError):
    """Raised when smoke-output channel is outside E36312A capability (1,2,3)."""


class _SetModelError(ValueError):
    """Raised when set is attempted on a non-E36312A model."""


class _SetChannelError(ValueError):
    """Raised when set channel is outside E36312A capability (1,2,3)."""


class _MeasureAllModelError(ValueError):
    """Raised when measure-all is attempted on a non-E36312A model."""


class _TriggerPulseModelError(ValueError):
    """Raised when trigger-pulse is attempted on a non-E36312A model."""


class _StatusModelError(ValueError):
    """Raised when status is attempted on a non-E36312A model."""


class _StatusChannelError(ValueError):
    """Raised when status channel is outside E36312A capability (1,2,3)."""


class _ReadOnlyModelError(ValueError):
    """Raised when read-only model-specific commands see an unsupported model."""


class _ReadOnlyChannelError(ValueError):
    """Raised when read-only model-specific commands receive an unsupported channel."""


class _E36312AOnlyError(ValueError):
    """Raised when an E36312A-only command sees a different model."""


class _E36312AChannelError(ValueError):
    """Raised when an E36312A command receives an unsupported channel."""


class _ClearProtectionModelError(ValueError):
    """Raised when clear-protection sees a non-E36312A model."""


class _ProtectionSetModelError(ValueError):
    """Raised when protection-set sees a non-E36312A model."""


class _RestoreModelError(ValueError):
    """Raised when restore-from-snapshot sees a non-E36312A model."""


class _RestoreIdentityError(ValueError):
    """Raised when connected hardware does not match snapshot identity."""


def _set_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
) -> dict[str, Any]:
    return {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "setpoints": {
            "current": _json_safe_number(args.current),
            "voltage": _json_safe_number(args.voltage),
        },
    }


def _output_off_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
    outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "output": {
            "enabled": False,
        },
    }
    if outputs is not None:
        payload["outputs"] = outputs
    return payload


def _safe_off_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
    outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "outputs": outputs,
    }


def _output_state_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
    enabled: bool | None,
    outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
    }
    if outputs is not None:
        payload["outputs"] = outputs
    else:
        if type(enabled) is not bool:
            raise _InvalidCoreResult("output-state Core result did not contain an exact boolean output_enabled value.")
        payload["output_enabled"] = enabled
    return payload


def _cycle_output_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
    outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "duration_ms": args.duration_ms,
        "output": {
            "cycled": True,
            "final_enabled": False,
        },
    }
    if outputs is not None:
        payload["outputs"] = outputs
    return payload


def _smoke_output_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
    *,
    measurements: dict[str, float],
    final_enabled: bool,
    safe_off_attempted: bool,
) -> dict[str, Any]:
    return {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "duration_ms": args.duration_ms,
        "setpoints": {
            "current": _json_safe_number(args.current),
            "voltage": _json_safe_number(args.voltage),
        },
        "measurements": {
            "voltage": _json_safe_number(measurements["voltage"]),
            "current": _json_safe_number(measurements["current"]),
        },
        "output": {
            "final_enabled": final_enabled,
        },
        "safe_off_attempted": safe_off_attempted,
    }


def _apply_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
    channels: tuple[int, ...],
) -> dict[str, Any]:
    payload = {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "setpoints": {
            "current": _json_safe_number(args.current),
            "voltage": _json_safe_number(args.voltage),
        },
        "output": {
            "enabled": not args.no_output,
        },
    }
    if args.channel == "all":
        payload["channels"] = [
            {
                "channel": channel,
                "setpoints": {
                    "current": _json_safe_number(args.current),
                    "voltage": _json_safe_number(args.voltage),
                },
            }
            for channel in channels
        ]
    return payload


def _ramp_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
    voltages: Sequence[float],
) -> dict[str, Any]:
    return {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "setpoints": {
            "current": _json_safe_number(args.current),
            "start_voltage": _json_safe_number(args.start_voltage),
            "stop_voltage": _json_safe_number(args.stop_voltage),
            "step_voltage": _json_safe_number(args.step_voltage),
        },
        "delay_ms": args.delay_ms,
        "steps": len(voltages),
        "voltages": [_json_safe_number(voltage) for voltage in voltages],
        "output": {"changed": False},
    }


def _output_on_resource_payload(
    args: argparse.Namespace,
    idn_raw: str,
    readback: dict[str, Any] | None,
    outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "channel": args.channel,
        "output": {
            "enabled": True,
        },
    }
    if readback is not None:
        payload["readback"] = readback
    if outputs is not None:
        payload["outputs"] = outputs
    return payload


def _normalize_positive_integral_core_channel(value: Any, *, field: str) -> int:
    if type(value) is int:
        if value > 0:
            return value
    elif type(value) is float:
        if math.isfinite(value) and value > 0 and value.is_integer():
            return int(value)
    raise _InvalidCoreResult(f"output-state Core result {field} must be a positive integer.")


def _detected_output_state_channels(data: Any) -> tuple[str, tuple[int, ...]]:
    if type(data) is not dict:
        raise _InvalidCoreResult("output-state Core result must be a dictionary.")
    idn = data.get("idn")
    if type(idn) is not dict:
        raise _InvalidCoreResult("output-state Core result must contain an observed identity dictionary.")
    idn_raw = idn.get("raw")
    if type(idn_raw) is not str or not idn_raw.strip():
        raise _InvalidCoreResult("output-state Core result must contain a non-empty observed IDN string.")
    try:
        selection = select_driver(idn_raw)
    except (TypeError, ValueError, UnsupportedModelError) as exc:
        raise _InvalidCoreResult("output-state Core result observed identity did not resolve to a supported model.") from exc
    if getattr(selection, "reason", None) != "model_specific_driver" or getattr(selection, "physical_identity", None) is None:
        raise _InvalidCoreResult("output-state Core result observed identity did not resolve to a supported model.")
    capabilities = getattr(selection, "capabilities", None)
    channels = getattr(capabilities, "real_measure_channels", None)
    if type(channels) is not tuple or not channels:
        raise _InvalidCoreResult("output-state detected real_measure_channels must be a non-empty tuple.")
    if any(type(channel) is not int or channel <= 0 for channel in channels):
        raise _InvalidCoreResult("output-state detected real_measure_channels contains an invalid channel.")
    if len(set(channels)) != len(channels):
        raise _InvalidCoreResult("output-state detected real_measure_channels contains duplicate channels.")
    return idn_raw, channels


def _normalize_output_state_core_result(
    args: argparse.Namespace,
    data: Any,
) -> tuple[str, bool | None, list[dict[str, Any]] | None]:
    idn_raw, expected_channels = _detected_output_state_channels(data)
    requested_channel = args.channel
    if requested_channel != "all":
        channel = _normalize_positive_integral_core_channel(requested_channel, field="requested channel")
        if "output_enabled" not in data or type(data["output_enabled"]) is not bool:
            raise _InvalidCoreResult("output-state Core result must contain an exact boolean output_enabled value.")
        if "outputs" in data:
            raise _InvalidCoreResult("single-channel output-state Core result must not contain outputs.")
        args.channel = channel
        return idn_raw, data["output_enabled"], None

    if "output_enabled" in data:
        raise _InvalidCoreResult("all-channel output-state Core result must not contain output_enabled.")
    if "outputs" not in data or type(data["outputs"]) is not list or not data["outputs"]:
        raise _InvalidCoreResult("all-channel output-state Core result must contain a non-empty outputs list.")

    by_channel: dict[int, dict[str, Any]] = {}
    for record in data["outputs"]:
        if type(record) is not dict or set(record) != {"channel", "enabled"}:
            raise _InvalidCoreResult("each output-state Core result record must contain only channel and enabled.")
        channel = _normalize_positive_integral_core_channel(record["channel"], field="record channel")
        if type(record["enabled"]) is not bool:
            raise _InvalidCoreResult("each output-state Core result record enabled value must be an exact boolean.")
        if channel in by_channel:
            raise _InvalidCoreResult("output-state Core result contains duplicate channels.")
        if channel not in expected_channels:
            raise _InvalidCoreResult("output-state Core result contains an unknown channel.")
        by_channel[channel] = {"channel": channel, "enabled": record["enabled"]}
    if set(by_channel) != set(expected_channels):
        raise _InvalidCoreResult("output-state Core result does not cover every detected output-state channel.")
    return idn_raw, None, [by_channel[channel] for channel in expected_channels]


def _core_output_resource_data(args: argparse.Namespace, data: dict[str, Any]) -> dict[str, Any]:
    if args.command == "output-state":
        idn_raw, output_enabled, outputs = _normalize_output_state_core_result(args, data)
        payload = _output_state_resource_payload(args, idn_raw, output_enabled, outputs)
    else:
        idn_raw = data["idn"]["raw"]
    if args.command == "set":
        payload = _set_resource_payload(args, idn_raw)
    elif args.command == "apply":
        channels = tuple(data.get("channels", (args.channel,)))
        payload = _apply_resource_payload(args, idn_raw, channels)
    elif args.command == "output-on":
        payload = _output_on_resource_payload(args, idn_raw, data.get("readback"), data.get("outputs"))
    elif args.command == "output-off":
        payload = _output_off_resource_payload(args, idn_raw, data.get("outputs"))
    elif args.command == "safe-off":
        payload = _safe_off_resource_payload(args, idn_raw, data["outputs"])
    elif args.command == "output-state":
        pass
    elif args.command == "cycle-output":
        payload = _cycle_output_resource_payload(args, idn_raw, data.get("outputs"))
    elif args.command == "ramp":
        payload = _ramp_resource_payload(args, idn_raw, data["voltages"])
    elif args.command == "smoke-output":
        payload = _smoke_output_resource_payload(
            args,
            idn_raw,
            measurements=data["measurements"],
            final_enabled=data["final_output_enabled"],
            safe_off_attempted=data["safe_off_attempted"],
        )
    else:
        raise ValueError(f"unsupported core output command: {args.command}")
    _attach_trigger_if_present(payload, data.get("trigger"))
    if "verification" in data:
        payload["verification"] = data["verification"]
    return payload


def _print_core_output_result(args: argparse.Namespace, resource_data: dict[str, Any]) -> None:
    _emit_text_lines(
        cli_rendering.format_core_output_result(
            command=args.command,
            resource=args.resource,
            channel=args.channel,
            current=getattr(args, "current", None),
            voltage=getattr(args, "voltage", None),
            no_output=getattr(args, "no_output", False),
            resource_data=resource_data,
            value_to_text=_format_text_value,
        )
    )


def _list_resources(
    resource_manager: SimulatedResourceManager | None,
    *,
    backend: str | None,
) -> tuple[str, ...]:
    if resource_manager is None:
        return list_resources(backend=backend)
    return list_resources(resource_manager, backend=backend)


def _open_resource(
    resource: str,
    resource_manager: SimulatedResourceManager | None,
    *,
    backend: str | None,
    timeout_ms: int,
    serial_options: SerialOptions | None = None,
    serial_remote: bool = False,
    serial_local_on_close: bool = False,
    scpi_logger: Any = None,
):
    serial_kwargs = _serial_open_kwargs(
        serial_options=serial_options,
        serial_remote=serial_remote,
        serial_local_on_close=serial_local_on_close,
    )
    if resource_manager is None:
        if scpi_logger is not None:
            serial_kwargs["scpi_logger"] = scpi_logger
        return open_resource(
            resource,
            backend=backend,
            timeout_ms=timeout_ms,
            **serial_kwargs,
        )
    if scpi_logger is not None:
        serial_kwargs["scpi_logger"] = scpi_logger
    return open_resource(
        resource,
        resource_manager,
        backend=backend,
        timeout_ms=timeout_ms,
        **serial_kwargs,
    )


def _serial_open_kwargs(
    *,
    serial_options: SerialOptions | None,
    serial_remote: bool,
    serial_local_on_close: bool,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if serial_options is not None:
        kwargs["serial_options"] = serial_options
    if serial_remote:
        kwargs["serial_remote"] = True
    if serial_local_on_close:
        kwargs["serial_local_on_close"] = True
    return kwargs


def _request_for_args(args: argparse.Namespace) -> dict[str, Any]:
    from powers_tool_cli.commands import output as output_commands

    if args.command in output_commands.OUTPUT_REQUEST_COMMANDS:
        return output_commands.request_for_args(args)
    if args.command == "safety":
        return {
            "subcommand": getattr(args, "safety_command", None),
            "resource": getattr(args, "resource", None),
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": getattr(args, "channel", None),
            "model": getattr(args, "model", None),
            "safety_config": getattr(args, "safety_config", None),
        }
    if args.command == "safety inspect":
        return {
            "resource": getattr(args, "resource", None),
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": getattr(args, "channel", None),
            "model": getattr(args, "model", None),
            "safety_config": getattr(args, "safety_config", None),
            "explain": getattr(args, "explain", False),
        }
    if args.command == "list-resources":
        return _with_serial_request_fields(args, {
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            "live_only": getattr(args, "live_only", False),
        })
    if args.command == "verify":
        return _with_serial_request_fields(args, {
            "resource": args.resource,
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        })
    if args.command == "clear":
        return _with_serial_request_fields(args, {
            "resource": args.resource,
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        })
    if args.command == "error":
        return _with_serial_request_fields(args, {
            "resource": args.resource,
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            "max_reads": args.max_reads,
        })
    if args.command == "measure":
        return _with_serial_request_fields(args, {
            "resource": args.resource,
            "channel": args.channel,
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        })
    if args.command == "measure-all":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    from powers_tool_cli.commands import trigger as trigger_commands

    if args.command in trigger_commands.TRIGGER_COMMANDS:
        return trigger_commands.request_for_args(args)
    if args.command == "read-status":
        channel = "all" if getattr(args, "all", False) else args.channel
        return _with_serial_request_fields(args, {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": channel,
            "max_errors": args.max_errors,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        })
    if args.command in {"send-command", "status", "stop", "wait-ready"}:
        return {
            "url": getattr(args, "url", None),
            "host": getattr(args, "host", None),
            "port": getattr(args, "port", None),
            "timeout_ms": getattr(args, "timeout_ms", None),
        }
    if args.command == "validate-readonly":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            "max_errors": args.max_errors,
        }
    if args.command in {"readback", "protection-status"}:
        channel = "all" if getattr(args, "all", False) else args.channel
        payload = {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": channel,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
        return _with_serial_request_fields(args, payload) if args.command == "readback" else payload
    if args.command == "protection-set":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "ovp_voltage": (
                _json_safe_number(args.ovp_voltage)
                if args.ovp_voltage is not None
                else None
            ),
            "ocp": args.ocp,
            "ocp_delay": (
                _json_safe_number(args.ocp_delay)
                if args.ocp_delay is not None
                else None
            ),
            "ocp_delay_trigger": args.ocp_delay_trigger,
            "confirm": getattr(args, "confirm", False),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "clear-protection":
        channel = "all" if getattr(args, "all", False) else args.channel
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": channel,
            "confirm": getattr(args, "confirm", False),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "identify":
        return _with_serial_request_fields(args, {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        })
    if args.command == "snapshot":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "max_errors": args.max_errors,
            "compare": getattr(args, "compare", None),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            "redact_resource": getattr(args, "redact_resource", False),
        }
    if args.command == "snapshot-diff":
        return {
            "before": args.before,
            "after": args.after,
            "summary": getattr(args, "summary", False),
        }
    if args.command == "hardware-report":
        return {
            "input_dir": args.input_dir,
            "target": args.target,
            "connection": args.connection,
            "resource": args.resource,
            "report_json": args.report_json,
            "summary_md": args.summary_md,
            "before_json": getattr(args, "before_json", None),
            "after_json": getattr(args, "after_json", None),
        }
    if args.command == "restore-from-snapshot":
        return {
            "snapshot": args.snapshot,
            "resource": args.resource,
            "channel": args.channel,
            "restore_output_state": getattr(args, "restore_output_state", False),
            "confirm": getattr(args, "confirm", False),
            "plan_json": getattr(args, "plan_json", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "log":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "channels": getattr(args, "channels", None),
            "interval_sec": args.interval_sec,
            "csv": args.csv,
            "jsonl": getattr(args, "jsonl", None),
            "append": getattr(args, "append", False),
            "samples": args.samples,
            "duration_sec": args.duration_sec,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            "lint": getattr(args, "lint", False),
        }
    if args.command == "sequence":
        from powers_tool_cli.commands import sequence as sequence_command

        return sequence_command.request_for_args(args)
    if args.command == "ramp-list":
        from powers_tool_cli.commands import ramp_list as ramp_list_command

        return ramp_list_command.request_for_args(args)
    if args.command == "doctor":
        return {
            "resource": getattr(args, "resource", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "capabilities":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "command": getattr(args, "selected_command", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    return {}


def _request_from_argv(command: str, argv: Sequence[str]) -> dict[str, Any]:
    from powers_tool_cli.commands import output as output_commands

    if command in output_commands.OUTPUT_REQUEST_COMMANDS:
        return output_commands.request_from_argv(command, argv)
    if command == "safety":
        return {
            "subcommand": "inspect" if "inspect" in argv else None,
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "model": _option_value(argv, "--model"),
            "safety_config": _option_value(argv, "--safety-config"),
            "explain": "--explain" in argv,
        }
    if command == "list-resources":
        return _with_serial_request_fields_from_argv(argv, {
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
            "live_only": "--live-only" in argv,
        })
    if command == "verify":
        return _with_serial_request_fields_from_argv(argv, {
            "resource": _option_value(argv, "--resource"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        })
    if command == "clear":
        return _with_serial_request_fields_from_argv(argv, {
            "resource": _option_value(argv, "--resource"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        })
    if command == "error":
        return _with_serial_request_fields_from_argv(argv, {
            "resource": _option_value(argv, "--resource"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
            "max_reads": _max_reads_from_argv(argv),
        })
    if command == "measure":
        return _with_serial_request_fields_from_argv(argv, {
            "resource": _option_value(argv, "--resource"),
            "channel": _channel_from_argv(argv),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        })
    if command == "measure-all":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    from powers_tool_cli.commands import trigger as trigger_commands

    if command in trigger_commands.TRIGGER_COMMANDS:
        return trigger_commands.request_from_argv(command, argv)
    if command == "read-status":
        channel = "all" if "--all" in argv else (_status_channel_from_argv(argv) or "all")
        return _with_serial_request_fields_from_argv(argv, {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": channel,
            "max_errors": _max_errors_from_argv(argv),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        })
    if command == "validate-readonly":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
            "max_errors": _max_errors_from_argv(argv),
        }
    if command in {"readback", "protection-status"}:
        channel = "all" if "--all" in argv else (_status_channel_from_argv(argv) or "all")
        payload = {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": channel,
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
        return _with_serial_request_fields_from_argv(argv, payload) if command == "readback" else payload
    if command == "protection-set":
        channel = "all" if "--all" in argv else (_status_channel_from_argv(argv) or "all")
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": channel,
            "ovp_voltage": _number_from_argv(argv, "--ovp-voltage"),
            "ocp": _option_value(argv, "--ocp"),
            "ocp_delay": _number_from_argv(argv, "--ocp-delay"),
            "ocp_delay_trigger": _option_value(argv, "--ocp-delay-trigger"),
            "confirm": "--confirm" in argv,
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "clear-protection":
        channel = "all" if "--all" in argv else _status_channel_from_argv(argv)
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": channel,
            "confirm": "--confirm" in argv,
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "identify":
        return _with_serial_request_fields_from_argv(argv, {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        })
    if command == "snapshot":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "max_errors": _max_errors_from_argv(argv),
            "compare": _option_value(argv, "--compare"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
            "redact_resource": "--redact-resource" in argv,
        }
    if command == "snapshot-diff":
        return {
            "before": _option_value(argv, "--before"),
            "after": _option_value(argv, "--after"),
            "summary": "--summary" in argv,
        }
    if command == "hardware-report":
        return {
            "input_dir": _option_value(argv, "--input-dir"),
            "target": _option_value(argv, "--target"),
            "connection": _option_value(argv, "--connection"),
            "resource": _option_value(argv, "--resource"),
            "report_json": _option_value(argv, "--report-json"),
            "summary_md": _option_value(argv, "--summary-md"),
            "before_json": _option_value(argv, "--before-json"),
            "after_json": _option_value(argv, "--after-json"),
        }
    if command == "restore-from-snapshot":
        return {
            "snapshot": _option_value(argv, "--snapshot"),
            "resource": _option_value(argv, "--resource"),
            "channel": _status_channel_from_argv(argv),
            "restore_output_state": "--restore-output-state" in argv,
            "confirm": "--confirm" in argv,
            "plan_json": _option_value(argv, "--plan-json"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "log":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "channels": _option_value(argv, "--channels"),
            "interval_sec": _number_from_argv(argv, "--interval-sec"),
            "csv": _option_value(argv, "--csv"),
            "jsonl": _option_value(argv, "--jsonl"),
            "append": "--append" in argv,
            "samples": _int_from_argv(argv, "--samples"),
            "duration_sec": _number_from_argv(argv, "--duration-sec"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
            "lint": "--lint" in argv,
        }
    if command == "sequence":
        from powers_tool_cli.commands import sequence as sequence_command

        return sequence_command.request_from_argv(argv)
    if command == "ramp-list":
        from powers_tool_cli.commands import ramp_list as ramp_list_command

        return ramp_list_command.request_from_argv(argv)
    if command == "doctor":
        return {
            "resource": _option_value(argv, "--resource"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "capabilities":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "command": _option_value(argv, "--command"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    return {}


def _max_reads_from_argv(argv: Sequence[str]) -> int | str:
    value = _option_value(argv, "--max-reads")
    if value is None:
        return 20
    try:
        return int(value)
    except ValueError:
        return value


def _json_save_path_from_argv(argv: Sequence[str]) -> str | None:
    if "--json" not in argv:
        return None
    return _option_value(argv, "--save-json")


def _command_from_argv(argv: Sequence[str]) -> str:
    for item in argv:
        if item in COMMAND_NAMES:
            return item
    return "unknown"


def _exit_code(exc: SystemExit) -> int:
    if exc.code is None:
        return 0
    if isinstance(exc.code, int):
        return exc.code
    return 1


def _log_scpi(resource: str, direction: str, message: str) -> None:
    print(f"{resource} SCPI {direction} {message}", file=sys.stderr)


_CHANNEL_NOT_PROVIDED = object()


def _safety_limits_for_args(
    args: argparse.Namespace,
    *,
    model: str | None = None,
    channel: object = _CHANNEL_NOT_PROVIDED,
) -> SafetyLimits | None:
    resolved_channel = (
        getattr(args, "channel", None)
        if channel is _CHANNEL_NOT_PROVIDED
        else channel
    )
    try:
        resource, limits = validation.resolve_request_safety_limits(
            safety_config=getattr(args, "safety_config", None),
            resource=getattr(args, "resource", None),
            resource_alias=getattr(args, "resource_alias", None),
            model=model,
            channel=resolved_channel if isinstance(resolved_channel, int) else None,
        )
    except validation.SafetyResolutionError as exc:
        raise SafetyConfigError(str(exc)) from exc
    args.resource = resource
    return limits


def _safety_limits_for_channel(
    args: argparse.Namespace,
    channel: int,
    *,
    model: str | None = None,
) -> SafetyLimits | None:
    return _safety_limits_for_args(args, model=model, channel=channel)


def _validate_output_request(
    args: argparse.Namespace,
    safety_limits: SafetyLimits | None,
) -> None:
    validation.validate_output_request(
        command=args.command,
        channel=args.channel,
        safety_limits=safety_limits,
        voltage=getattr(args, "voltage", None),
        current=getattr(args, "current", None),
        start_voltage=getattr(args, "start_voltage", None),
        stop_voltage=getattr(args, "stop_voltage", None),
        step_voltage=getattr(args, "step_voltage", None),
    )


def _emit_cli_error(
    args: argparse.Namespace,
    *,
    request: dict[str, Any],
    error_type: str,
    code: str,
    message: str,
    retryable: bool,
    hardware_intent: bool = False,
) -> int:
    if args.json:
        emit_json_error(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=hardware_intent),
            request=request,
            error_type=error_type,
            code=code,
            message=message,
            retryable=retryable,
        )
    else:
        print(message, file=sys.stderr)
    return 2


def _emit_invalid_core_result(
    args: argparse.Namespace,
    *,
    request: dict[str, Any],
    execution: dict[str, Any],
    message: str,
) -> int:
    if args.json:
        emit_json_error(
            command=args.command,
            execution=execution,
            request=request,
            error_type="execution",
            code="invalid_core_result",
            message=message,
            retryable=False,
        )
    else:
        print(message, file=sys.stderr)
    return 3


def _emit_safe_io_error(
    args: argparse.Namespace,
    *,
    request: dict[str, Any],
    execution: dict[str, Any],
    code: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> int:
    if args.json:
        emit_json_error(
            command=args.command,
            execution=execution,
            request=request,
            error_type="connection",
            code=code,
            message=message,
            retryable=True,
            data=data,
        )
    else:
        print(message, file=sys.stderr)
    return 1


def _output_plan_for_args(args: argparse.Namespace) -> dict[str, Any]:
    return operations.output_plan(_operation_request_for_args(args))


def _driver_step(index: int, action: str, **parameters: Any) -> dict[str, Any]:
    return {
        "index": index,
        "type": "driver_action",
        "action": action,
        "parameters": parameters,
    }


def _operation_request_for_args(args: argparse.Namespace) -> OperationRequest:
    parameters = {
        "channel": getattr(args, "channel", None),
        "voltage": getattr(args, "voltage", None),
        "current": getattr(args, "current", None),
        "duration_ms": getattr(args, "duration_ms", 0),
        "settle_ms": getattr(args, "settle_ms", 0),
        "verify_after_write": getattr(args, "verify_after_write", False),
        "setpoint_voltage_tolerance": getattr(args, "setpoint_voltage_tolerance", 0.001),
        "setpoint_current_tolerance": getattr(args, "setpoint_current_tolerance", 0.001),
        "no_output": getattr(args, "no_output", False),
        "start_voltage": getattr(args, "start_voltage", None),
        "stop_voltage": getattr(args, "stop_voltage", None),
        "step_voltage": getattr(args, "step_voltage", None),
        "delay_ms": getattr(args, "delay_ms", 0),
        "enable_output": getattr(args, "enable_output", False),
        "loop_count": getattr(args, "loop_count", None) or 1,
        "completion_pulse_pins": _completion_pulse_pins(args) if hasattr(args, "completion_pulse_pins") else (),
        "completion_pulse_channel": getattr(args, "completion_pulse_channel", None),
        "completion_pulse_polarity": getattr(args, "completion_pulse_polarity", "positive"),
        "leave_trigger_configured": getattr(args, "leave_trigger_configured", False),
    }
    if args.command == "ramp":
        parameters["completion_pulse_timing"] = getattr(args, "completion_pulse_timing", "segment")
    parameters = _core_command_parameters(args.command, parameters)
    return OperationRequest(
        command=args.command,
        runtime=RuntimeOptions(
            resource=getattr(args, "resource", None),
            resource_alias=getattr(args, "resource_alias", None),
            safety_config=getattr(args, "safety_config", None),
            simulate=getattr(args, "simulate", False),
            dry_run=getattr(args, "dry_run", False),
            **_runtime_identity_for_args(args),
            backend=getattr(args, "backend", None),
            timeout_ms=getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            log_scpi=getattr(args, "log_scpi", False),
            confirm=getattr(args, "confirm", False),
            serial_options=_serial_options_for_args(args),
            serial_remote=getattr(args, "serial_remote", False),
            serial_local_on_close=getattr(args, "serial_local_on_close", False),
            support_policy_mode=_support_policy_mode_for_args(args),
        ),
        parameters=parameters,
    )


def _target_core_request_for_args(args: argparse.Namespace) -> OperationRequest:
    parameters: dict[str, Any] = {
        "channel": getattr(args, "channel", None),
        "all": getattr(args, "all", False),
        "live_only": getattr(args, "live_only", False),
        "max_reads": getattr(args, "max_reads", getattr(args, "max_errors", 20)),
        "max_errors": getattr(args, "max_errors", 20),
        "ovp_voltage": getattr(args, "ovp_voltage", None),
        "ocp": getattr(args, "ocp", None),
        "ocp_delay": getattr(args, "ocp_delay", None),
        "ocp_delay_trigger": getattr(args, "ocp_delay_trigger", None),
    }
    return OperationRequest(
        command=args.command,
        runtime=RuntimeOptions(
            resource=getattr(args, "resource", None),
            resource_alias=getattr(args, "resource_alias", None),
            safety_config=getattr(args, "safety_config", None),
            simulate=getattr(args, "simulate", False),
            dry_run=getattr(args, "dry_run", False),
            **_runtime_identity_for_args(args),
            backend=getattr(args, "backend", None),
            timeout_ms=getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            log_scpi=getattr(args, "log_scpi", False),
            confirm=getattr(args, "confirm", False),
            serial_options=_serial_options_for_args(args),
            serial_remote=getattr(args, "serial_remote", False),
            serial_local_on_close=getattr(args, "serial_local_on_close", False),
            support_policy_mode=_support_policy_mode_for_args(args),
        ),
        parameters=_core_command_parameters(args.command, parameters),
    )


def _enforce_live_cli_scope(args: argparse.Namespace, idn_raw: str, *, command: str | None = None) -> None:
    """Apply the Core-owned gate in a legacy CLI runner that still owns I/O."""
    request = _target_core_request_for_args(args)
    if request.runtime.simulate:
        return
    effective_command = command or request.command
    enforce_live_support_for_idn(request, idn_raw, command=effective_command)


def _core_validation_code(exc: CoreValidationError, fallback: str = "argument_error") -> str:
    return "unsupported_live_scope" if isinstance(exc, LiveSupportPolicyError) else fallback


def _connection_scpi_logger_for_args(args: argparse.Namespace):
    if not getattr(args, "log_scpi", False):
        return None
    if not (getattr(args, "serial_remote", False) or getattr(args, "serial_local_on_close", False)):
        return None
    return _log_scpi


def _core_opener_for_args(args: argparse.Namespace):
    manager = _resource_manager_for_args(args)

    def opener(
        resource: str,
        resource_manager: Any = None,
        *,
        backend: str | None,
        timeout_ms: int,
        serial_options: SerialOptions | None = None,
        serial_remote: bool = False,
        serial_local_on_close: bool = False,
    ):
        return _open_resource(
            resource,
            resource_manager if resource_manager is not None else manager,
            backend=backend,
            timeout_ms=timeout_ms,
            serial_options=serial_options,
            serial_remote=serial_remote,
            serial_local_on_close=serial_local_on_close,
            scpi_logger=_connection_scpi_logger_for_args(args),
        )

    return opener


def _core_lister_for_args(args: argparse.Namespace):
    manager = _resource_manager_for_args(args)

    def lister(resource_manager: Any = None, *, backend: str | None):
        return _list_resources(resource_manager if resource_manager is not None else manager, backend=backend)

    return lister


def _sequence_request_for_args(args: argparse.Namespace) -> SequenceRequest:
    from powers_tool_cli.commands import sequence as sequence_command

    return sequence_command.core_request_for_args(args)


def _ramp_list_request_for_args(args: argparse.Namespace) -> OperationRequest:
    from powers_tool_cli.commands import ramp_list as ramp_list_command

    return ramp_list_command.core_request_for_args(args)


def _trigger_request_for_args(args: argparse.Namespace) -> TriggerRequest:
    parameters: dict[str, Any] = {
        "channel": getattr(args, "channel", None),
        "source": getattr(args, "source", "bus"),
        "voltage": getattr(args, "voltage", None),
        "current": getattr(args, "current", None),
        "fire": getattr(args, "fire", False),
        "wait_complete": getattr(args, "wait_complete", False),
        "wait_timeout_ms": getattr(args, "wait_timeout_ms", None),
        "poll_ms": getattr(args, "poll_ms", 200),
        "leave_trigger_configured": getattr(args, "leave_trigger_configured", False),
        "completion_pulse_pins": _completion_pulse_pins(args) if hasattr(args, "completion_pulse_pins") else (),
        "completion_pulse_polarity": getattr(args, "completion_pulse_polarity", "positive"),
        "exclusive_pins": getattr(args, "exclusive_pins", False),
        "pin": getattr(args, "pin", None),
        "pins": getattr(args, "pins", None),
        "polarity": getattr(args, "polarity", "positive"),
        "max_errors": getattr(args, "max_errors", 20),
    }
    if args.command == "trigger-list":
        config = _trigger_list_config_from_args(args)
        _validate_trigger_list_limits(
            voltages=config["voltages"],
            currents=config["currents"],
            dwell=config["dwell"],
            count=config["count"],
        )
        _validate_trigger_list_control_args(args, config)
        _validate_trigger_list_safety(
            config,
            _safety_limits_for_channel(args, config["channel"], model="E36312A"),
        )
        parameters.update(config)
        if not parameters.get("pins"):
            parameters.pop("pins", None)
        if "begin_outputs" in config:
            parameters.pop("completion_pulse_pins", None)
            parameters.pop("completion_pulse_polarity", None)
            parameters["bost_list"] = config["begin_outputs"]
            parameters["eost_list"] = config["end_outputs"]
            parameters["trigger_output_pins"] = config["pins"]
            parameters["trigger_output_polarity"] = config["polarity"]
    return TriggerRequest(
        command=args.command,
        runtime=RuntimeOptions(
            resource=getattr(args, "resource", None),
            resource_alias=getattr(args, "resource_alias", None),
            safety_config=getattr(args, "safety_config", None),
            simulate=getattr(args, "simulate", False),
            dry_run=getattr(args, "dry_run", False),
            **_runtime_identity_for_args(args),
            backend=getattr(args, "backend", None),
            timeout_ms=getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            log_scpi=getattr(args, "log_scpi", False),
            support_policy_mode=_support_policy_mode_for_args(args),
        ),
        parameters=_core_command_parameters(args.command, parameters),
    )


def _core_command_parameters(command: str, values: dict[str, Any]) -> dict[str, Any]:
    """Remove argparse-only defaults using the Core-owned command contract."""

    allowed = command_parameter_names(command)
    return {
        name: value
        for name, value in values.items()
        if name in allowed
        and value is not None
        and not (
            name == "all"
            and (
                value is False
                or (
                    command in {"protection-status", "protection-set", "clear-protection"}
                    and values.get("channel") is not None
                )
            )
        )
        and not (name == "completion_pulse_pins" and not value)
    }


def _core_trigger_resource_data(args: argparse.Namespace, data: dict[str, Any]) -> dict[str, Any]:
    if "plan" in data:
        return data
    resolved_resource = data.pop("_resource", args.resource)
    idn_raw = data.pop("idn", None)
    payload: dict[str, Any] = {
        "resource": (
            resolved_resource
            if args.command == "trigger-pulse" or idn_raw is None
            else _resource_payload(
                resolved_resource,
                simulated=args.simulate,
                reachable=True,
                idn_raw=idn_raw,
            )
        )
    }
    if args.command == "trigger-pulse":
        payload.update(data)
    elif args.command == "trigger-status":
        payload.update(data)
    elif args.command == "trigger-list":
        payload["steps"] = data["steps"]
        payload["trigger"] = data["trigger"]
    elif args.command == "trigger-step":
        payload["trigger"] = data["trigger"]
    elif args.command == "trigger-fire":
        payload["trigger"] = data["trigger"]
    elif args.command == "trigger-abort":
        payload["channel"] = args.channel
        payload["channels"] = data["channels"]
        payload["aborted"] = True
        payload["errors"] = data.get("errors", [])
        payload["read_count"] = data.get("read_count", 0)
    else:
        raise ValueError(f"unsupported trigger command: {args.command}")
    return payload


def _print_core_trigger_result(args: argparse.Namespace, data: dict[str, Any]) -> None:
    _emit_text_lines(
        cli_rendering.format_core_trigger_result(
            command=args.command,
            resource=args.resource,
            channel=getattr(args, "channel", None),
            mode=_mode_for_args(args),
            data=data,
        )
    )


def _append_write_followup_steps(
    args: argparse.Namespace,
    steps: list[dict[str, Any]],
    verification_actions: Sequence[str],
) -> None:
    channel = getattr(args, "channel", None)
    next_index = len(steps) + 1
    if getattr(args, "settle_ms", 0) > 0:
        steps.append(_driver_step(next_index, "sleep", duration_ms=args.settle_ms))
        next_index += 1
    if not getattr(args, "verify_after_write", False):
        return
    channels = (1, 2, 3) if channel == "all" else (channel,)
    for selected_channel in channels:
        for action in verification_actions:
            steps.append(_driver_step(next_index, action, channel=selected_channel))
            next_index += 1


def _append_completion_pulse_plan(args: argparse.Namespace, plan: dict[str, Any]) -> None:
    pins = _completion_pulse_pins(args)
    if not pins:
        return
    channel = _completion_pulse_channel(args, getattr(args, "channel", None))
    plan["steps"].append(
        _driver_step(
            len(plan["steps"]) + 1,
            "completion_pulse",
            channel=channel,
            pins=list(pins),
            polarity=args.completion_pulse_polarity,
            mode="post-action",
        )
    )
    plan["trigger"] = _trigger_result_payload(
        mode="completion-pulse",
        native=False,
        channel=channel,
        pins=pins,
        polarity=args.completion_pulse_polarity,
        source="bus",
    )


def _output_plan_description(command: str) -> str:
    descriptions = {
        "set": "Preview setting voltage, current limit, or both.",
        "output-on": "Preview enabling the selected output channel.",
        "output-off": "Preview disabling the selected output channel.",
        "safe-off": "Preview a conservative output-off action without channel expansion.",
        "output-state": "Preview reading the selected output channel state.",
        "cycle-output": "Preview briefly enabling then disabling the selected output channel.",
        "apply": "Preview setting current, voltage, then enabling output.",
        "ramp": "Preview setting current, then stepping voltage setpoints without changing output state.",
        "smoke-output": "Preview a guarded set, output, measure, and safe-off sequence.",
    }
    return descriptions[command]


def _print_output_plan(plan: dict[str, Any], *, mode: str, dry_run: bool) -> None:
    _emit_text_lines(
        cli_rendering.format_output_plan(
            plan,
            mode=mode,
            dry_run=dry_run,
            value_to_text=_format_text_value,
        )
    )


def _print_scpi_plan(plan: dict[str, object], *, mode: str, dry_run: bool) -> None:
    _emit_text_lines(cli_rendering.format_scpi_plan(plan, mode=mode, dry_run=dry_run))


def _emit_text_lines(lines: Sequence[str]) -> None:
    for line in lines:
        print(line)


def _ramp_voltages(start: float, stop: float, step: float) -> list[float]:
    if step <= 0:
        raise ValueError("step-voltage must be greater than 0")
    direction = 1.0 if stop >= start else -1.0
    signed_step = direction * step
    voltages = [float(start)]
    current = float(start)
    for _ in range(1000):
        next_voltage = current + signed_step
        if (direction > 0 and next_voltage >= stop) or (direction < 0 and next_voltage <= stop):
            break
        voltages.append(next_voltage)
        current = next_voltage
    else:
        raise ValueError("ramp would exceed 1000 voltage steps")
    if not math.isclose(voltages[-1], stop, rel_tol=0.0, abs_tol=1e-12):
        voltages.append(float(stop))
    if len(voltages) > 1000:
        raise ValueError("ramp would exceed 1000 voltage steps")
    return voltages


def _settle_after_write(args: argparse.Namespace) -> None:
    settle_ms = getattr(args, "settle_ms", 0)
    if settle_ms > 0:
        time.sleep(settle_ms / 1000)


def _verify_setpoints_after_write(
    power_supply: GenericScpiPowerSupply,
    args: argparse.Namespace,
    *,
    channels: Sequence[int],
    expected_voltage: float | None = None,
) -> dict[str, Any]:
    if not getattr(args, "verify_after_write", False):
        return {"passed": True, "checks": [], "differences": []}
    voltage = args.voltage if expected_voltage is None else expected_voltage
    current = args.current
    tolerances = {
        "voltage": args.setpoint_voltage_tolerance,
        "current": args.setpoint_current_tolerance,
    }
    checks = []
    differences = []
    for channel in channels:
        actual_voltage = power_supply.programmed_voltage(channel=channel)
        actual_current = power_supply.programmed_current(channel=channel)
        check = {
            "channel": channel,
            "expected": {"voltage": _json_safe_number(voltage), "current": _json_safe_number(current)},
            "actual": {"voltage": _json_safe_number(actual_voltage), "current": _json_safe_number(actual_current)},
            "tolerances": tolerances,
        }
        checks.append(check)
        if abs(actual_voltage - voltage) > args.setpoint_voltage_tolerance:
            differences.append(_verification_difference("programmed_voltage", channel, voltage, actual_voltage, args.setpoint_voltage_tolerance))
        if abs(actual_current - current) > args.setpoint_current_tolerance:
            differences.append(_verification_difference("programmed_current", channel, current, actual_current, args.setpoint_current_tolerance))
    return {"passed": not differences, "checks": checks, "differences": differences}


def _verify_output_state_after_write(
    power_supply: GenericScpiPowerSupply,
    args: argparse.Namespace,
    *,
    expected: bool,
    channel: int | None = None,
) -> dict[str, Any]:
    if not getattr(args, "verify_after_write", False):
        return {"passed": True, "checks": [], "differences": []}
    selected_channel = args.channel if channel is None else channel
    actual = power_supply.output_state(channel=selected_channel)
    differences = []
    if actual is not expected:
        differences.append(
            {
                "path": f"outputs[channel={selected_channel}].enabled",
                "channel": selected_channel,
                "expected": expected,
                "actual": actual,
            }
        )
    return {
        "passed": not differences,
        "checks": [{"channel": selected_channel, "expected": expected, "actual": actual}],
        "differences": differences,
    }


def _verification_difference(path: str, channel: int, expected: float, actual: float, tolerance: float) -> dict[str, Any]:
    return {
        "path": f"{path}[channel={channel}]",
        "channel": channel,
        "expected": _json_safe_number(expected),
        "actual": _json_safe_number(actual),
        "tolerance": tolerance,
        "delta": _json_safe_number(actual - expected),
    }


def _combine_verifications(label: str, *verifications: dict[str, Any]) -> dict[str, Any]:
    checks = []
    differences = []
    for verification in verifications:
        checks.extend(verification.get("checks", []))
        differences.extend(verification.get("differences", []))
    return {"operation": label, "passed": not differences, "checks": checks, "differences": differences}


def _attach_verification_if_requested(
    args: argparse.Namespace,
    data: dict[str, Any],
    verification: dict[str, Any],
) -> None:
    if getattr(args, "verify_after_write", False):
        data["verification"] = verification


def _emit_verification_error(
    args: argparse.Namespace,
    request: dict[str, Any],
    execution: dict[str, Any],
    verification: dict[str, Any],
    data: dict[str, Any] | None = None,
) -> int:
    message = "write verification failed"
    if args.json:
        emit_json_error(
            command=args.command,
            execution=execution,
            request=request,
            error_type="verification",
            code="verification_failed",
            message=message,
            retryable=False,
            data=data,
            metadata={"verification": verification},
        )
    else:
        print(message, file=sys.stderr)
    return 3


def _format_text_value(value: object) -> str:
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value)


def _parse_measurement(response: str, measurement: str) -> float:
    try:
        return float(response.strip())
    except ValueError as exc:
        raise ValueError(f"Could not parse {measurement} measurement: {response!r}") from exc


def _is_no_error_response(response: str) -> bool:
    normalized = response.strip().lstrip("+")
    return normalized == "0" or normalized.startswith("0,")


def _unsupported_measure_channel_message(
    *,
    channel: int,
    mode: str,
    driver_name: str,
    allowed_channels: tuple[int, ...],
) -> str:
    return (
        f"measure channel {channel} is not enabled in {mode} mode for "
        f"{driver_name}; supported: {_format_channel_set(allowed_channels)}"
    )


def _format_channel_set(channels: tuple[int, ...]) -> str:
    if channels == (1,):
        return "channel 1 only"
    return "channels " + ", ".join(str(channel) for channel in channels)


if __name__ == "__main__":
    raise SystemExit(main())
