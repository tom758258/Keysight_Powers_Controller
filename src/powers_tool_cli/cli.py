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

LOG_CSV_FIELDS = TELEMETRY_ROW_FIELDS


OUTPUT_WRITE_POWER_SUPPLY_TYPES = (E36312APowerSupply, EDU36311APowerSupply)
STEP_TRIGGER_POWER_SUPPLY_TYPES = (E36312APowerSupply,)


# M1 module re-exports

from powers_tool_cli import cli_runtime

from powers_tool_cli.cli_runtime import *

from powers_tool_cli import cli_request

from powers_tool_cli.cli_request import *

from powers_tool_cli.commands import discovery

from powers_tool_cli.commands.discovery import *

from powers_tool_cli.commands import trigger_run

from powers_tool_cli.commands.trigger_run import *

from powers_tool_cli.commands import readonly

from powers_tool_cli.commands.readonly import *

from powers_tool_cli.commands import inspection

from powers_tool_cli.commands.inspection import *

from powers_tool_cli.commands import sequence_run

from powers_tool_cli.commands.sequence_run import *

from powers_tool_cli.commands import output_run

from powers_tool_cli.commands.output_run import *



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
            data = _patchable_run_core_command(
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
