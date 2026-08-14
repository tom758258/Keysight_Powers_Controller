"""Ramp-list workflow handler and shared sequence/Trigger compatibility helpers."""

from __future__ import annotations

__all__ = [
    "_cooperative_workflow_interrupt",
    "_emit_workflow_interruption",
    "_load_sequence_document",
    "_parse_sequence_scalar",
    "_parse_simple_sequence_yaml",
    "_print_sequence_summary",
    "_run_ramp_list",
    "_workflow_start_summary",
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
from powers_tool_core.drivers.psm2010 import PSM2010PowerSupply
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
)
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

def _run_ramp_list(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=False)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        core_request = _ramp_list_request_for_args(args)
        core_request, execution_summary, execution_warnings = _workflow_start_summary(
            args, core_request
        )
        base_opener = _core_opener_for_args(args)

        def opener(*opener_args: Any, **opener_kwargs: Any) -> Any:
            if execution["mode"] == "real" and not execution["dry_run"]:
                execution["hardware_touched"] = True
            return base_opener(*opener_args, **opener_kwargs)

        with _cooperative_workflow_interrupt() as stop_event:
            data = _patchable_run_core_command(
                core_request,
                opener=opener,
                stop_requested=stop_event.is_set,
                sleep=time.sleep,
                scpi_logger=_log_scpi,
            )
    except (CommandCancelled, StopCleanupError) as exc:
        return _emit_workflow_interruption(
            args,
            request=request,
            execution=execution,
            exc=exc,
        )
    except KeyboardInterrupt:
        return _emit_workflow_interruption(
            args,
            request=request,
            execution=execution,
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
            hardware_intent=bool(execution["hardware_touched"]),
        )
    except (SafetyConfigError, SafetyValidationError, ValueError, OSError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=bool(execution["hardware_touched"]),
        )
    except CoreIoError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="ramp_list_failed" if exc.opened else "connection_failed",
            message=str(exc),
        )
    except CoreExecutionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
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
                execution=execution,
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
            execution=execution,
            request=request,
            data=data,
            warnings=execution_warnings,
        )
    else:
        _emit_text_lines(cli_rendering.format_ramp_list_summary(data))
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

def _print_sequence_summary(data: dict[str, Any]) -> None:
    _emit_text_lines(cli_rendering.format_sequence_summary(data))

