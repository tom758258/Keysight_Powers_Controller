"""Sequence and ramp-list workflow command handlers and sequence planning helpers."""

from __future__ import annotations

__all__ = [
    "_add_sequence_scpi_previews",
    "_cooperative_workflow_interrupt",
    "_emit_workflow_interruption",
    "_execute_sequence",
    "_execute_sequence_step",
    "_load_sequence_document",
    "_normalize_sequence_step",
    "_parse_sequence_scalar",
    "_parse_simple_sequence_yaml",
    "_print_sequence_summary",
    "_run_ramp_list",
    "_sequence_channel",
    "_sequence_channels",
    "_sequence_cleanup_safe_off",
    "_sequence_plan",
    "_sequence_preview_channels",
    "_sequence_step_preview",
    "_validate_sequence_step",
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
        power_supply = _patchable_create_power_supply(session, idn_raw)
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

