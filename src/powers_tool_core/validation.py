"""Parser-neutral validation helpers shared by CLI and future adapters."""

from __future__ import annotations

import math
from pathlib import Path

from powers_tool_core.safety import (
    SafetyConfigError,
    SafetyLimits,
    confirmation_required_for_setpoint,
    resolve_safety_config,
    validate_channel,
    validate_setpoint,
)


class ValidationError(ValueError):
    """Raised when parser-neutral request validation fails."""


class ChannelSelectionError(ValidationError):
    """Raised when a channel selection is not supported."""


class ReadbackValidationError(ValidationError):
    """Raised when readback setpoints fail output-on safety validation."""


class SafetyResolutionError(ValidationError):
    """Raised when safety configuration cannot be resolved."""


def parse_positive_int(value: str, *, name: str = "value") -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValidationError(f"{name} must be a positive integer") from exc
    if parsed < 1:
        raise ValidationError(f"{name} must be a positive integer")
    return parsed


def parse_nonnegative_int(value: str, *, name: str = "value") -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValidationError(f"{name} must be a non-negative integer") from exc
    if parsed < 0:
        raise ValidationError(f"{name} must be a non-negative integer")
    return parsed


def parse_positive_float(value: str, *, name: str = "value") -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValidationError(f"{name} must be a positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValidationError(f"{name} must be a positive number")
    return parsed


def parse_float_list(value: str, *, name: str = "values") -> tuple[float, ...]:
    values: list[float] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            raise ValidationError(f"{name} must be comma-separated numbers")
        try:
            parsed = float(item)
        except ValueError as exc:
            raise ValidationError(f"{name} must be comma-separated numbers") from exc
        if not math.isfinite(parsed):
            raise ValidationError(f"{name} must be finite numbers")
        values.append(parsed)
    if not values:
        raise ValidationError(f"{name} must include at least one number")
    return tuple(values)


def parse_channel_list(value: str) -> tuple[int, ...]:
    channels: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            raise ValidationError("channels must be comma-separated positive integers")
        try:
            channels.append(parse_positive_int(item, name="channel"))
        except ValidationError as exc:
            raise ValidationError("channels must be comma-separated positive integers") from exc
    return tuple(channels)


def parse_trigger_pins(value: str) -> tuple[int, ...]:
    pins: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            raise ValidationError("pins must be comma-separated pins 1, 2, or 3")
        pin = parse_positive_int(item, name="pin")
        if pin not in (1, 2, 3):
            raise ValidationError("pin must be 1, 2, or 3")
        if pin in pins:
            raise ValidationError("pins must not contain duplicates")
        pins.append(pin)
    return tuple(pins)


def expand_channel_selection(
    selected_channel: int | str,
    supported_channels: tuple[int, ...],
) -> tuple[int, ...]:
    if selected_channel == "all":
        return supported_channels
    if selected_channel not in supported_channels:
        raise ChannelSelectionError(
            f"channel {selected_channel} is not supported; supported: {supported_channels}"
        )
    return (int(selected_channel),)


def resolve_request_safety_limits(
    *,
    safety_config: str | Path | None,
    resource: str | None,
    resource_alias: str | None,
    model: str | None,
    channel: int | None,
) -> tuple[str | None, SafetyLimits | None]:
    if resource_alias is not None and safety_config is None:
        raise SafetyResolutionError("resource alias requires --safety-config")
    if safety_config is None:
        return resource, None
    try:
        resolution = resolve_safety_config(
            safety_config,
            resource=None if resource_alias is not None else resource,
            resource_alias=resource_alias,
            model=model,
            channel=channel,
        )
    except SafetyConfigError as exc:
        raise SafetyResolutionError(str(exc)) from exc
    return resolution.resource, resolution.limits


def validate_output_request(
    *,
    command: str,
    channel: int | str,
    safety_limits: SafetyLimits | None,
    voltage: float | None = None,
    current: float | None = None,
    start_voltage: float | None = None,
    stop_voltage: float | None = None,
    step_voltage: float | None = None,
) -> None:
    if command in {"set", "smoke-output"} and channel == "all":
        raise ValidationError(f"{command} does not support channel all")
    if command == "ramp" and channel == "all":
        raise ValidationError("ramp does not support channel all")
    if command == "set" and voltage is None and current is None:
        raise ValidationError("set requires voltage, current, or both")
    if command in {"set", "apply", "smoke-output"}:
        channels = (1, 2, 3) if channel == "all" else (int(channel),)
        for selected_channel in channels:
            validate_setpoint(
                channel=selected_channel,
                voltage=voltage,
                current=current,
                limits=safety_limits,
            )
        return
    if command == "ramp":
        if start_voltage is None or stop_voltage is None or step_voltage is None:
            raise ValidationError("ramp requires start, stop, and step voltage")
        for ramp_voltage in _ramp_voltages(start_voltage, stop_voltage, step_voltage):
            validate_setpoint(
                channel=channel,
                voltage=ramp_voltage,
                current=current,
                limits=safety_limits,
            )
        return
    if command in {"output-on", "output-off", "output-state", "cycle-output"}:
        channels = (1, 2, 3) if channel == "all" else (int(channel),)
        for selected_channel in channels:
            validate_channel(selected_channel, safety_limits)
        return
    if command == "safe-off" and channel != "all":
        validate_channel(channel, safety_limits)


def validate_output_on_readback(
    channel: int,
    setpoints: dict[str, float],
    safety_limits: SafetyLimits,
) -> None:
    try:
        voltage = setpoints["voltage"]
        current = setpoints["current"]
    except KeyError as exc:
        raise ReadbackValidationError(str(exc)) from exc
    validate_setpoint(
        channel=channel,
        voltage=voltage,
        current=current,
        limits=safety_limits,
    )


def confirmation_required_for_request(
    *,
    voltage: float | None,
    current: float | None,
    limits: SafetyLimits | None,
    confirmed: bool,
) -> bool:
    if confirmed or limits is None:
        return False
    return confirmation_required_for_setpoint(
        voltage=voltage,
        current=current,
        limits=limits,
    )


def confirmation_required_message(command: str) -> str:
    return (
        f"{command} real execution requires --confirm because a voltage or "
        "current setpoint exceeds configured confirm_above thresholds"
    )


def _ramp_voltages(start: float, stop: float, step: float) -> list[float]:
    if step <= 0:
        raise ValidationError("step-voltage must be greater than 0")
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
        raise ValidationError("ramp would exceed 1000 voltage steps")
    if not math.isclose(voltages[-1], stop, rel_tol=0.0, abs_tol=1e-12):
        voltages.append(float(stop))
    if len(voltages) > 1000:
        raise ValidationError("ramp would exceed 1000 voltage steps")
    return voltages
