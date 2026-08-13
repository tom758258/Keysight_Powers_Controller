"""Legacy trigger command handlers and trigger-specific CLI helpers."""

from __future__ import annotations

__all__ = [
    "_TriggerExecutionStopped",
    "_TriggerInterrupted",
    "_TriggerModelError",
    "_TriggerNativeUnsupported",
    "_TriggerWaitTimeout",
    "_abort_trigger_channels",
    "_attach_trigger_if_present",
    "_bool_csv",
    "_completion_pulse_channel",
    "_completion_pulse_pins",
    "_completion_pulse_requested",
    "_configure_completion_output_pins",
    "_core_trigger_resource_data",
    "_document_bool_list",
    "_document_float_list",
    "_emit_trigger_stop_error",
    "_keyboard_stop_requested",
    "_maybe_run_completion_pulse",
    "_number_csv",
    "_print_core_trigger_result",
    "_restore_trigger_snapshot",
    "_run_native_list",
    "_run_native_step",
    "_run_post_action_completion_pulse",
    "_run_trigger_abort",
    "_run_trigger_fire",
    "_run_trigger_list",
    "_run_trigger_pulse",
    "_run_trigger_status",
    "_run_trigger_step",
    "_strict_bool",
    "_trigger_channel_status",
    "_trigger_list_config_from_args",
    "_trigger_list_scpi",
    "_trigger_poll_interval_ms",
    "_trigger_pulse_scpi",
    "_trigger_result_payload",
    "_trigger_source_scpi",
    "_trigger_step_scpi",
    "_trigger_wait_timeout_ms",
    "_validate_real_trigger_source",
    "_validate_trigger_list_control_args",
    "_validate_trigger_list_limits",
    "_validate_trigger_list_safety",
    "_validate_trigger_step_args",
    "_validate_trigger_step_safety",
    "_wait_complete_preview_commands",
    "_wait_for_trigger_completion",
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

from powers_tool_cli.commands.sequence_run import _load_sequence_document

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
            power_supply = _patchable_create_power_supply(session, idn)
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
            power_supply = _patchable_create_power_supply(session, idn)
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
            power_supply = _patchable_create_power_supply(session, idn)
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
            power_supply = _patchable_create_power_supply(session, idn)
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
            power_supply = _patchable_create_power_supply(session, idn)
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
            power_supply = _patchable_create_power_supply(session, idn)
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

