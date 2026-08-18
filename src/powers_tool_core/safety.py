"""Safety validation for output-affecting setpoints."""

from __future__ import annotations

import math
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised only on Python 3.10
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

from powers_tool_core.errors import PowersToolError

Channel = int | str | None
SUPPORTED_SAFETY_CONFIG_KEYS = frozenset(
    {
        "max_voltage",
        "max_current",
        "allowed_channels",
        "confirm_above_voltage",
        "confirm_above_current",
    }
)
SUPPORTED_RESOURCE_CONFIG_KEYS = SUPPORTED_SAFETY_CONFIG_KEYS | {"alias", "resource", "channels"}
SUPPORTED_TOP_LEVEL_CONFIG_KEYS = frozenset({"safety", "models", "resources"})


class SafetyValidationError(PowersToolError, ValueError):
    """Raised when a requested setpoint violates configured safety rules."""


class SafetyConfigError(PowersToolError, ValueError):
    """Raised when a safety config file is missing or invalid."""


@dataclass(frozen=True)
class SafetyLimits:
    """Explicit safety limits for setpoint validation.

    Electrical rating limits are intentionally absent by default. Upper bounds
    and allowed channels are enforced only when a caller provides them.
    """

    max_voltage: float | None = None
    max_current: float | None = None
    confirm_above_voltage: float | None = None
    confirm_above_current: float | None = None
    allowed_channels: Collection[Channel] | None = None

    def __post_init__(self) -> None:
        if self.max_voltage is not None:
            _validate_non_negative_finite("max_voltage", self.max_voltage)
        if self.max_current is not None:
            _validate_non_negative_finite("max_current", self.max_current)
        if self.confirm_above_voltage is not None:
            _validate_non_negative_finite(
                "confirm_above_voltage",
                self.confirm_above_voltage,
            )
        if self.confirm_above_current is not None:
            _validate_non_negative_finite(
                "confirm_above_current",
                self.confirm_above_current,
            )


@dataclass(frozen=True)
class ResourceSafetyEntry:
    """One named VISA resource entry from a safety config file."""

    alias: str
    resource: str
    limits: SafetyLimits
    limit_fields: frozenset[str]
    channel_limits: dict[int, tuple[SafetyLimits, frozenset[str]]] | None = None


@dataclass(frozen=True)
class SafetyConfig:
    """Parsed safety config with optional global and resource-specific limits."""

    global_limits: SafetyLimits | None = None
    model_limits: dict[str, tuple[SafetyLimits, frozenset[str]]] | None = None
    resources: tuple[ResourceSafetyEntry, ...] = ()

    def global_or_empty_limits(self) -> SafetyLimits:
        return self.global_limits or SafetyLimits()

    def entry_for_alias(self, alias: str) -> ResourceSafetyEntry | None:
        for entry in self.resources:
            if entry.alias == alias:
                return entry
        return None

    def entry_for_resource(self, resource: str) -> ResourceSafetyEntry | None:
        for entry in self.resources:
            if entry.resource == resource:
                return entry
        return None

    def model_limits_for(self, model: str | None) -> tuple[SafetyLimits, frozenset[str]] | None:
        if model is None or self.model_limits is None:
            return None
        return self.model_limits.get(model.upper())

    def effective_limits_for_entry(
        self,
        entry: ResourceSafetyEntry,
        *,
        model: str | None = None,
        channel: Channel = None,
    ) -> SafetyLimits:
        limits = self.global_or_empty_limits()
        model_entry = self.model_limits_for(model)
        if model_entry is not None:
            limits = _merge_limits(limits, model_entry[0], model_entry[1])
        limits = _merge_limits(limits, entry.limits, entry.limit_fields)
        channel_entry = _channel_limits_for_entry(entry, channel)
        if channel_entry is not None:
            limits = _merge_limits(limits, channel_entry[0], channel_entry[1])
        return limits


@dataclass(frozen=True)
class SafetyResolution:
    """Effective resource and limits selected from a safety config."""

    resource: str | None
    resource_alias: str | None
    limits: SafetyLimits
    sources: dict[str, str | None] | None = None


def validate_voltage(
    voltage: float,
    limits: SafetyLimits | None = None,
) -> None:
    """Validate a voltage setpoint before SCPI is sent."""

    active_limits = limits or SafetyLimits()
    value = _validate_non_negative_finite("voltage", voltage)
    if active_limits.max_voltage is not None and value > active_limits.max_voltage:
        raise SafetyValidationError(
            f"voltage {value:g} exceeds maximum {active_limits.max_voltage:g}"
        )


def validate_current(
    current: float,
    limits: SafetyLimits | None = None,
) -> None:
    """Validate a current-limit setpoint before SCPI is sent."""

    active_limits = limits or SafetyLimits()
    value = _validate_non_negative_finite("current", current)
    if active_limits.max_current is not None and value > active_limits.max_current:
        raise SafetyValidationError(
            f"current {value:g} exceeds maximum {active_limits.max_current:g}"
        )


def validate_channel(
    channel: Channel,
    limits: SafetyLimits | None = None,
) -> None:
    """Validate a channel only when explicit allowed channels are configured."""

    active_limits = limits or SafetyLimits()
    if active_limits.allowed_channels is None:
        return
    if channel not in active_limits.allowed_channels:
        raise SafetyValidationError(f"channel {channel!r} is not allowed")


def validate_setpoint(
    *,
    channel: Channel = None,
    voltage: float | None = None,
    current: float | None = None,
    limits: SafetyLimits | None = None,
) -> None:
    """Validate channel, voltage, and current in one call."""

    active_limits = limits or SafetyLimits()
    validate_channel(channel, active_limits)
    if voltage is not None:
        validate_voltage(voltage, active_limits)
    if current is not None:
        validate_current(current, active_limits)


def confirmation_required_for_setpoint(
    *,
    voltage: float | None = None,
    current: float | None = None,
    limits: SafetyLimits | None = None,
) -> bool:
    """Return whether user confirmation is required by configured thresholds."""

    active_limits = limits or SafetyLimits()
    if voltage is not None and active_limits.confirm_above_voltage is not None:
        value = _validate_non_negative_finite("voltage", voltage)
        if value > active_limits.confirm_above_voltage:
            return True
    if current is not None and active_limits.confirm_above_current is not None:
        value = _validate_non_negative_finite("current", current)
        if value > active_limits.confirm_above_current:
            return True
    return False


def _validate_non_negative_finite(name: str, value: float) -> float:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as exc:
        raise SafetyValidationError(f"{name} must be numeric") from exc
    if not math.isfinite(numeric_value):
        raise SafetyValidationError(f"{name} must be finite")
    if numeric_value < 0:
        raise SafetyValidationError(f"{name} must be non-negative")
    return numeric_value


def load_safety_config(
    path: str | Path,
    *,
    resource: str | None = None,
    resource_alias: str | None = None,
) -> SafetyLimits:
    """Load strict effective safety limits from an explicit TOML config path."""

    return resolve_safety_config(
        path,
        resource=resource,
        resource_alias=resource_alias,
    ).limits


def resolve_safety_config(
    path: str | Path,
    *,
    resource: str | None = None,
    resource_alias: str | None = None,
    model: str | None = None,
    channel: Channel = None,
) -> SafetyResolution:
    """Resolve one resource selection against an explicit safety config."""

    if resource is not None and resource_alias is not None:
        raise SafetyConfigError("use either resource or resource-alias, not both")

    config = load_safety_config_document(path)

    if resource_alias is not None:
        entry = config.entry_for_alias(resource_alias)
        if entry is None:
            raise SafetyConfigError(f"unknown resource alias: {resource_alias}")
        return SafetyResolution(
            resource=entry.resource,
            resource_alias=resource_alias,
            limits=config.effective_limits_for_entry(entry, model=model, channel=channel),
            sources=_resolution_sources(config, entry, model=model, channel=channel),
        )

    if resource is not None:
        entry = config.entry_for_resource(resource)
        if entry is not None:
            return SafetyResolution(
                resource=resource,
                resource_alias=None,
                limits=config.effective_limits_for_entry(entry, model=model, channel=channel),
                sources=_resolution_sources(config, entry, model=model, channel=channel),
            )

    base_limits = config.global_or_empty_limits()
    model_entry = config.model_limits_for(model)
    if model_entry is not None:
        base_limits = _merge_limits(base_limits, model_entry[0], model_entry[1])
    return SafetyResolution(
        resource=resource,
        resource_alias=None,
        limits=base_limits,
        sources={
            "global": "safety" if config.global_limits is not None else None,
            "model": model.upper() if model_entry is not None and model is not None else None,
            "resource": None,
            "channel": None,
        },
    )


def load_safety_config_document(path: str | Path) -> SafetyConfig:
    """Load and validate a strict safety config document from TOML."""

    config_path = Path(path)
    try:
        raw_config = config_path.read_bytes()
    except FileNotFoundError as exc:
        raise SafetyConfigError(f"safety config not found: {config_path}") from exc
    except OSError as exc:
        raise SafetyConfigError(f"could not read safety config {config_path}: {exc}") from exc

    try:
        parsed = tomllib.loads(raw_config.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise SafetyConfigError(
            f"could not decode safety config {config_path} as UTF-8"
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise SafetyConfigError(
            f"could not parse safety config {config_path}: {exc}"
        ) from exc

    return _config_from_mapping(parsed, config_path)


def _config_from_mapping(config: dict[str, Any], config_path: Path) -> SafetyConfig:
    unknown_top_level_keys = sorted(set(config) - SUPPORTED_TOP_LEVEL_CONFIG_KEYS)
    if unknown_top_level_keys:
        keys = ", ".join(unknown_top_level_keys)
        raise SafetyConfigError(f"unsupported safety config key: {keys}")

    global_limits = _global_limits_from_config(config, config_path)
    model_limits = _model_limits_from_config(config)
    resources = _resource_entries_from_config(config)

    if global_limits is None and not model_limits and not resources:
        raise SafetyConfigError(
            f"safety config {config_path} must contain [safety] or [[resources]]"
        )

    return SafetyConfig(global_limits=global_limits, model_limits=model_limits, resources=resources)


def _global_limits_from_config(
    config: dict[str, Any],
    config_path: Path,
) -> SafetyLimits | None:
    safety = config.get("safety")
    if safety is None:
        return None
    if not isinstance(safety, dict):
        raise SafetyConfigError(f"safety config {config_path} must contain [safety]")
    if not safety:
        raise SafetyConfigError(
            "safety config [safety] must define at least one supported field"
        )

    unknown_keys = sorted(set(safety) - SUPPORTED_SAFETY_CONFIG_KEYS)
    if unknown_keys:
        keys = ", ".join(unknown_keys)
        raise SafetyConfigError(f"unsupported [safety] key: {keys}")

    limits: dict[str, Any] = {}
    if "max_voltage" in safety:
        limits["max_voltage"] = _config_number("max_voltage", safety["max_voltage"])
    if "max_current" in safety:
        limits["max_current"] = _config_number("max_current", safety["max_current"])
    if "confirm_above_voltage" in safety:
        limits["confirm_above_voltage"] = _config_number(
            "confirm_above_voltage",
            safety["confirm_above_voltage"],
        )
    if "confirm_above_current" in safety:
        limits["confirm_above_current"] = _config_number(
            "confirm_above_current",
            safety["confirm_above_current"],
        )
    if "allowed_channels" in safety:
        limits["allowed_channels"] = _config_allowed_channels(
            safety["allowed_channels"]
        )

    return SafetyLimits(**limits)


def _resource_entries_from_config(config: dict[str, Any]) -> tuple[ResourceSafetyEntry, ...]:
    resources = config.get("resources")
    if resources is None:
        return ()
    if not isinstance(resources, list):
        raise SafetyConfigError("[[resources]] must be an array of tables")

    entries: list[ResourceSafetyEntry] = []
    aliases: set[str] = set()
    resource_names: set[str] = set()
    for index, resource_config in enumerate(resources, start=1):
        if not isinstance(resource_config, dict):
            raise SafetyConfigError(f"resources entry {index} must be a table")

        unknown_keys = sorted(set(resource_config) - SUPPORTED_RESOURCE_CONFIG_KEYS)
        if unknown_keys:
            keys = ", ".join(unknown_keys)
            raise SafetyConfigError(f"unsupported resources entry key: {keys}")

        alias = _required_config_string(resource_config, "alias", index)
        resource = _required_config_string(resource_config, "resource", index)

        if alias in aliases:
            raise SafetyConfigError(f"duplicate resource alias: {alias}")
        if resource in resource_names:
            raise SafetyConfigError(f"duplicate resource string: {resource}")
        aliases.add(alias)
        resource_names.add(resource)

        limit_fields = frozenset(set(resource_config) & SUPPORTED_SAFETY_CONFIG_KEYS)
        channel_limits = _channel_limits_from_resource(resource_config, alias)
        entries.append(
            ResourceSafetyEntry(
                alias=alias,
                resource=resource,
                limits=_limits_from_supported_fields(resource_config),
                limit_fields=limit_fields,
                channel_limits=channel_limits,
            )
        )

    return tuple(entries)


def _model_limits_from_config(
    config: dict[str, Any],
) -> dict[str, tuple[SafetyLimits, frozenset[str]]] | None:
    models = config.get("models")
    if models is None:
        return None
    if not isinstance(models, dict):
        raise SafetyConfigError("[models] must be a table")

    parsed: dict[str, tuple[SafetyLimits, frozenset[str]]] = {}
    for model, model_config in models.items():
        if not isinstance(model, str) or not model.strip():
            raise SafetyConfigError("model names must be non-empty strings")
        if not isinstance(model_config, dict):
            raise SafetyConfigError(f"models.{model} must be a table")
        unknown_keys = sorted(set(model_config) - SUPPORTED_SAFETY_CONFIG_KEYS)
        if unknown_keys:
            keys = ", ".join(unknown_keys)
            raise SafetyConfigError(f"unsupported models.{model} key: {keys}")
        if not model_config:
            raise SafetyConfigError(f"models.{model} must define at least one supported field")
        fields = frozenset(set(model_config) & SUPPORTED_SAFETY_CONFIG_KEYS)
        parsed[model.upper()] = (_limits_from_supported_fields(model_config), fields)
    return parsed


def _channel_limits_from_resource(
    resource_config: dict[str, Any],
    alias: str,
) -> dict[int, tuple[SafetyLimits, frozenset[str]]] | None:
    channels = resource_config.get("channels")
    if channels is None:
        return None
    if not isinstance(channels, dict):
        raise SafetyConfigError(f"resources entry {alias} channels must be a table")
    parsed: dict[int, tuple[SafetyLimits, frozenset[str]]] = {}
    for channel_text, channel_config in channels.items():
        try:
            channel = int(channel_text)
        except (TypeError, ValueError) as exc:
            raise SafetyConfigError(f"resources entry {alias} channel keys must be positive integers") from exc
        if channel < 1:
            raise SafetyConfigError(f"resources entry {alias} channel keys must be positive integers")
        if not isinstance(channel_config, dict):
            raise SafetyConfigError(f"resources entry {alias} channel {channel} must be a table")
        unknown_keys = sorted(set(channel_config) - SUPPORTED_SAFETY_CONFIG_KEYS)
        if unknown_keys:
            keys = ", ".join(unknown_keys)
            raise SafetyConfigError(f"unsupported resources entry channel key: {keys}")
        fields = frozenset(set(channel_config) & SUPPORTED_SAFETY_CONFIG_KEYS)
        parsed[channel] = (_limits_from_supported_fields(channel_config), fields)
    return parsed


def _merge_limits(base: SafetyLimits, override: SafetyLimits, fields: frozenset[str]) -> SafetyLimits:
    return SafetyLimits(
        max_voltage=override.max_voltage if "max_voltage" in fields else base.max_voltage,
        max_current=override.max_current if "max_current" in fields else base.max_current,
        confirm_above_voltage=(
            override.confirm_above_voltage
            if "confirm_above_voltage" in fields
            else base.confirm_above_voltage
        ),
        confirm_above_current=(
            override.confirm_above_current
            if "confirm_above_current" in fields
            else base.confirm_above_current
        ),
        allowed_channels=(
            override.allowed_channels
            if "allowed_channels" in fields
            else base.allowed_channels
        ),
    )


def _channel_limits_for_entry(
    entry: ResourceSafetyEntry,
    channel: Channel,
) -> tuple[SafetyLimits, frozenset[str]] | None:
    if entry.channel_limits is None:
        return None
    if isinstance(channel, int):
        return entry.channel_limits.get(channel)
    return None


def _resolution_sources(
    config: SafetyConfig,
    entry: ResourceSafetyEntry,
    *,
    model: str | None,
    channel: Channel,
) -> dict[str, str | None]:
    model_entry = config.model_limits_for(model)
    channel_entry = _channel_limits_for_entry(entry, channel)
    return {
        "global": "safety" if config.global_limits is not None else None,
        "model": model.upper() if model_entry is not None and model is not None else None,
        "resource": entry.alias,
        "channel": str(channel) if channel_entry is not None else None,
    }


def _required_config_string(
    config: dict[str, Any],
    key: str,
    index: int,
) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SafetyConfigError(f"resources entry {index} must define non-empty {key}")
    return value


def _limits_from_supported_fields(config: dict[str, Any]) -> SafetyLimits:
    limits: dict[str, Any] = {}
    if "max_voltage" in config:
        limits["max_voltage"] = _config_number("max_voltage", config["max_voltage"])
    if "max_current" in config:
        limits["max_current"] = _config_number("max_current", config["max_current"])
    if "confirm_above_voltage" in config:
        limits["confirm_above_voltage"] = _config_number(
            "confirm_above_voltage",
            config["confirm_above_voltage"],
        )
    if "confirm_above_current" in config:
        limits["confirm_above_current"] = _config_number(
            "confirm_above_current",
            config["confirm_above_current"],
        )
    if "allowed_channels" in config:
        limits["allowed_channels"] = _config_allowed_channels(config["allowed_channels"])
    return SafetyLimits(**limits)


def _config_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SafetyConfigError(f"{name} must be a finite non-negative number")
    try:
        return _validate_non_negative_finite(name, value)
    except SafetyValidationError as exc:
        raise SafetyConfigError(str(exc)) from exc


def _config_allowed_channels(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise SafetyConfigError("allowed_channels must be a list of positive integers")

    channels: list[int] = []
    for channel in value:
        if isinstance(channel, bool) or not isinstance(channel, int) or channel < 1:
            raise SafetyConfigError(
                "allowed_channels must be a list of positive integers"
            )
        channels.append(channel)
    return tuple(channels)
