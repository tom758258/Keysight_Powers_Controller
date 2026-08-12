"""Shared argv and serial request-envelope primitives."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from powers_tool_core.connection import DEFAULT_TIMEOUT_MS, normalize_serial_termination


def option_value(argv: Sequence[str], option: str) -> str | None:
    prefix = f"{option}="
    for index, item in enumerate(argv):
        if item.startswith(prefix):
            return item[len(prefix) :]
        if item == option:
            value_index = index + 1
            if value_index >= len(argv) or argv[value_index].startswith("--"):
                return None
            return argv[value_index]
    return None


def int_from_argv(argv: Sequence[str], option: str) -> int | str | None:
    value = option_value(argv, option)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def int_option_from_argv(argv: Sequence[str], option: str, default: int | None) -> int | str | None:
    value = int_from_argv(argv, option)
    return default if value is None else value


def timeout_from_argv(argv: Sequence[str]) -> int | str:
    value = option_value(argv, "--timeout-ms")
    if value is None:
        return DEFAULT_TIMEOUT_MS
    try:
        return int(value)
    except ValueError:
        return value


def with_serial_request_fields_from_argv(argv: Sequence[str], payload: dict[str, Any]) -> dict[str, Any]:
    serial_options = {
        "baud_rate": int_option_from_argv(argv, "--serial-baud-rate", None),
        "data_bits": int_option_from_argv(argv, "--serial-data-bits", None),
        "parity": option_value(argv, "--serial-parity"),
        "stop_bits": option_value(argv, "--serial-stop-bits"),
        "flow_control": option_value(argv, "--serial-flow-control"),
        "read_termination": normalize_serial_termination(option_value(argv, "--serial-read-termination")),
        "write_termination": normalize_serial_termination(option_value(argv, "--serial-write-termination")),
    }
    serial_options = {key: value for key, value in serial_options.items() if value is not None}
    if serial_options:
        payload["serial_options"] = serial_options
    if "--serial-remote" in argv:
        payload["serial_remote"] = True
    if "--serial-local-on-close" in argv:
        payload["serial_local_on_close"] = True
    return payload


def json_safe_number(value: float) -> float | str:
    numeric = float(value)
    if math.isfinite(numeric):
        return numeric
    return str(value)


def number_from_argv(argv: Sequence[str], option: str) -> float | str | None:
    value = option_value(argv, option)
    if value is None:
        return None
    try:
        return json_safe_number(float(value))
    except ValueError:
        return value


def drop_none_setpoints(request: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in request.items() if key not in {"voltage", "current"} or value is not None}


def float_list_from_argv(argv: Sequence[str], option: str) -> list[float | str] | None:
    value = option_value(argv, option)
    if value is None:
        return None
    values: list[float | str] = []
    for item in value.split(","):
        item = item.strip()
        try:
            values.append(float(item))
        except ValueError:
            values.append(item)
    return values


def channel_from_argv(argv: Sequence[str]) -> int | str | None:
    return int_from_argv(argv, "--channel")


def channels_from_argv(argv: Sequence[str]) -> list[int | str] | None:
    return _integer_list_from_argv(argv, "--channels")


def status_channel_from_argv(argv: Sequence[str]) -> int | str | None:
    value = option_value(argv, "--channel")
    if value is None:
        return None
    if value.lower() == "all":
        return "all"
    try:
        return int(value)
    except ValueError:
        return value


def pin_from_argv(argv: Sequence[str]) -> int | str | None:
    return int_from_argv(argv, "--pin")


def pins_from_argv(argv: Sequence[str]) -> list[int | str] | None:
    return _integer_list_from_argv(argv, "--pins")


def completion_pins_from_argv(argv: Sequence[str]) -> list[int | str] | None:
    return _integer_list_from_argv(argv, "--completion-pulse-pins")


def _integer_list_from_argv(argv: Sequence[str], option: str) -> list[int | str] | None:
    value = option_value(argv, option)
    if value is None:
        return None
    values: list[int | str] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            values.append(item)
            continue
        try:
            values.append(int(item))
        except ValueError:
            values.append(item)
    return values


def trigger_pins_for_args(args: Any) -> tuple[int, ...]:
    pins = getattr(args, "pins", None)
    if pins is not None:
        return tuple(pins)
    pin = getattr(args, "pin", None)
    if pin is not None:
        return (pin,)
    raise ValueError("trigger-pulse requires --pin or --pins")


def write_verification_request_fields(args: Any) -> dict[str, Any]:
    return {
        "settle_ms": getattr(args, "settle_ms", 0),
        "verify_after_write": getattr(args, "verify_after_write", False),
        "setpoint_voltage_tolerance": getattr(args, "setpoint_voltage_tolerance", 0.001),
        "setpoint_current_tolerance": getattr(args, "setpoint_current_tolerance", 0.001),
    }


def write_verification_request_fields_from_argv(argv: Sequence[str]) -> dict[str, Any]:
    return {
        "settle_ms": int_option_from_argv(argv, "--settle-ms", 0),
        "verify_after_write": "--verify-after-write" in argv,
        "setpoint_voltage_tolerance": number_from_argv(argv, "--setpoint-voltage-tolerance") or 0.001,
        "setpoint_current_tolerance": number_from_argv(argv, "--setpoint-current-tolerance") or 0.001,
    }


def completion_request_fields(args: Any) -> dict[str, Any]:
    if (
        getattr(args, "completion_pulse_pins", None) is None
        and getattr(args, "completion_pulse_channel", None) is None
        and getattr(args, "completion_pulse_polarity", "positive") == "positive"
        and not getattr(args, "leave_trigger_configured", False)
    ):
        return {}
    return {
        "completion_pulse": {
            "pins": list(getattr(args, "completion_pulse_pins", None) or ()),
            "polarity": getattr(args, "completion_pulse_polarity", "positive"),
            "channel": getattr(args, "completion_pulse_channel", None),
            "leave_trigger_configured": getattr(args, "leave_trigger_configured", False),
            **({"timing": getattr(args, "completion_pulse_timing", "segment")} if args.command == "ramp" else {}),
        }
    }


def completion_request_fields_from_argv(argv: Sequence[str]) -> dict[str, Any]:
    pins = completion_pins_from_argv(argv)
    channel = int_from_argv(argv, "--completion-pulse-channel")
    polarity = option_value(argv, "--completion-pulse-polarity") or "positive"
    leave_configured = "--leave-trigger-configured" in argv
    if pins is None and channel is None and polarity == "positive" and not leave_configured:
        return {}
    return {
        "completion_pulse": {
            "pins": pins or [],
            "polarity": polarity,
            "channel": channel,
            "leave_trigger_configured": leave_configured,
        }
    }


def duration_from_argv(argv: Sequence[str]) -> int | str:
    return int_option_from_argv(argv, "--duration-ms", 500)


def max_errors_from_argv(argv: Sequence[str]) -> int | str:
    return int_option_from_argv(argv, "--max-errors", 20)
