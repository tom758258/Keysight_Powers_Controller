"""Output command execution, result adapters, and dry-run planning."""

from __future__ import annotations

__all__ = [
    "_append_completion_pulse_plan",
    "_apply_resource_payload",
    "_core_output_resource_data",
    "_cycle_output_resource_payload",
    "_detected_output_state_channels",
    "_emit_verification_error",
    "_normalize_output_state_core_result",
    "_normalize_positive_integral_core_channel",
    "_output_off_resource_payload",
    "_output_on_resource_payload",
    "_output_plan_description",
    "_output_state_resource_payload",
    "_print_core_output_result",
    "_print_output_plan",
    "_print_scpi_plan",
    "_ramp_resource_payload",
    "_run_core_output_real",
    "_run_output_plan",
    "_safe_off_resource_payload",
    "_set_resource_payload",
    "_smoke_output_resource_payload",
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
from powers_tool_cli.commands.trigger_run import (
    _attach_trigger_if_present,
    _completion_pulse_channel,
    _completion_pulse_pins,
    _trigger_result_payload,
)
from powers_tool_cli.commands.sequence_run import (
    _cooperative_workflow_interrupt,
    _emit_workflow_interruption,
    _workflow_start_summary,
)

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
                data = _patchable_run_core_command(
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
    data: dict[str, Any],
) -> dict[str, Any]:
    voltages = data["voltages"]
    payload = {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
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
    if "channels" in data:
        payload["channels"] = list(data["channels"])
        for name in (
            "completed_step_executions",
            "execution_units",
            "progress",
            "enabled_channels",
            "final_output_states",
        ):
            if name in data:
                payload[name] = data[name]
    else:
        payload["channel"] = args.channel
    return payload

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
        selection = _patchable_select_driver(idn_raw)
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
        payload = _ramp_resource_payload(args, idn_raw, data)
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
