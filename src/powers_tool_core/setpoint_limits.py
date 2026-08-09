"""Combine official electrical ratings with explicit safety configuration."""

from __future__ import annotations

from dataclasses import dataclass

from powers_tool_core.electrical_ratings import ChannelElectricalRating, ModelElectricalRatings
from powers_tool_core.safety import SafetyLimits, SafetyValidationError, validate_channel


@dataclass(frozen=True)
class EffectiveSetpointLimits:
    model: str | None
    channel: int
    official_rating: ChannelElectricalRating | None
    safety_limits: SafetyLimits | None
    max_voltage: float | None
    max_current: float | None
    voltage_source: str | None
    current_source: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "max_voltage": self.max_voltage,
            "max_current": self.max_current,
            "voltage_source": self.voltage_source,
            "current_source": self.current_source,
        }


def effective_setpoint_limits(
    *,
    model: str | None,
    channel: int,
    electrical_ratings: ModelElectricalRatings | None,
    safety_limits: SafetyLimits | None,
) -> EffectiveSetpointLimits:
    validate_channel(channel, safety_limits)
    rating = electrical_ratings.channel(channel) if electrical_ratings is not None else None
    max_voltage, voltage_source = _effective_max(
        rating.max_voltage if rating else None,
        safety_limits.max_voltage if safety_limits else None,
    )
    max_current, current_source = _effective_max(
        rating.max_current if rating else None,
        safety_limits.max_current if safety_limits else None,
    )
    return EffectiveSetpointLimits(
        model=model,
        channel=channel,
        official_rating=rating,
        safety_limits=safety_limits,
        max_voltage=max_voltage,
        max_current=max_current,
        voltage_source=voltage_source,
        current_source=current_source,
    )


def validate_effective_setpoint(
    *,
    model: str | None,
    channel: int,
    electrical_ratings: ModelElectricalRatings | None,
    safety_limits: SafetyLimits | None = None,
    voltage: float | None = None,
    current: float | None = None,
) -> EffectiveSetpointLimits:
    limits = effective_setpoint_limits(
        model=model,
        channel=channel,
        electrical_ratings=electrical_ratings,
        safety_limits=safety_limits,
    )
    if voltage is not None and limits.max_voltage is not None and voltage > limits.max_voltage:
        raise SafetyValidationError(_message("voltage", voltage, limits.max_voltage, model, channel, limits.voltage_source))
    if current is not None and limits.max_current is not None and current > limits.max_current:
        raise SafetyValidationError(_message("current", current, limits.max_current, model, channel, limits.current_source))
    if (
        voltage is not None
        and current is not None
        and limits.official_rating is not None
        and limits.official_rating.operating_ranges
        and not any(
            voltage <= operating_range.max_voltage
            and current <= operating_range.max_current
            for operating_range in limits.official_rating.operating_ranges
        )
    ):
        model_name = model or "unknown model"
        raise SafetyValidationError(
            f"requested voltage {voltage:g} V and current {current:g} A do not fit "
            f"any official electrical operating range for {model_name} channel {channel}"
        )
    return limits


def _effective_max(official: float | None, safety: float | None) -> tuple[float | None, str | None]:
    if official is None:
        return safety, "safety config" if safety is not None else None
    if safety is None or official <= safety:
        return official, "official DC output rating"
    return safety, "safety config"


def _message(kind: str, value: float, maximum: float, model: str | None, channel: int, source: str | None) -> str:
    model_name = model or "unknown model"
    return (
        f"{kind} {value:g} exceeds effective maximum {maximum:g} "
        f"{'V' if kind == 'voltage' else 'A'} for {model_name} channel {channel}, limited by {source}"
    )
