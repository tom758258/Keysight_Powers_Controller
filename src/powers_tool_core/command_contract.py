"""Fail-closed, adapter-neutral command parameter admission contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Mapping

from powers_tool_core.core import CoreValidationError, OperationRequest, SequenceRequest, TriggerRequest
from powers_tool_core.workflow_validation import MAX_LOOP_COUNT


_MISSING = object()


@dataclass(frozen=True)
class Field:
    kind: str
    required: bool = False
    nullable: bool = False
    default: Any = _MISSING
    values: frozenset[str] = frozenset()
    allow_all: bool = False


@dataclass(frozen=True)
class CommandContract:
    fields: Mapping[str, Field]
    aliases: Mapping[str, str] = None  # alias -> canonical
    mutually_exclusive: tuple[tuple[str, ...], ...] = ()
    exactly_one_of: tuple[tuple[str, ...], ...] = ()
    at_least_one: tuple[tuple[str, ...], ...] = ()
    dependencies: Mapping[str, tuple[str, ...]] = None
    removed_fields: Mapping[str, str] = None


def _fields(*names: str, **typed: Field) -> dict[str, Field]:
    result = {name: Field("any") for name in names}
    result.update(typed)
    return result


BOOLEAN_FALSE = Field("bool", default=False)
POSITIVE_INTEGER = Field("int", required=True)
NUMBER = Field("number")
CHANNEL = Field("channel")
ALL_CHANNEL = Field("channel", allow_all=True)
STRING = Field("string")
DOCUMENT = Field("object")


_PULSE_FIELDS = {
    "completion_pulse_pins": Field("pin_list"),
    "completion_pulse_polarity": Field("enum", default="positive", values=frozenset({"positive", "negative"})),
    "completion_pulse_channel": Field("pulse_channel"),
    "leave_trigger_configured": BOOLEAN_FALSE,
}
_PULSE_DEPENDENCIES = {
    "completion_pulse_channel": ("completion_pulse_pins",),
}
_REMOVED_GENERAL_WORKFLOW_FIELDS = {
    "completion_pulse_mode": "use the post-action completion-pulse contract instead",
    "completion_pulse_dwell_ms": "use the post-action completion-pulse contract instead",
    "wait_timeout_ms": "trigger wait controls are accepted only by trigger commands",
    "poll_ms": "trigger wait controls are accepted only by trigger commands",
}
_GENERAL_PULSE_CONTRACT_OPTIONS = {
    "dependencies": _PULSE_DEPENDENCIES,
    "removed_fields": _REMOVED_GENERAL_WORKFLOW_FIELDS,
}
_VERIFY_FIELDS = {
    "verify_after_write": BOOLEAN_FALSE,
    "settle_ms": Field("nonnegative_int", default=0),
    "setpoint_voltage_tolerance": Field("nonnegative_number", default=0.001),
    "setpoint_current_tolerance": Field("nonnegative_number", default=0.001),
}


COMMAND_CONTRACTS: dict[str, CommandContract] = {
    "list-resources": CommandContract(_fields(live_only=BOOLEAN_FALSE)),
    "verify": CommandContract({}),
    "clear": CommandContract({}),
    "error": CommandContract(_fields(max_reads=Field("positive_int", default=20))),
    "measure": CommandContract(_fields(channel=Field("channel", required=True))),
    "measure-all": CommandContract({}),
    "log": CommandContract(
        _fields(
            channel=Field("channel", allow_all=True),
            channels=Field("channel_list"),
            interval_sec=Field("positive_number", required=True),
            samples=Field("positive_int"),
            duration_sec=Field("positive_number"),
        ),
        exactly_one_of=(("channel", "channels"), ("samples", "duration_sec")),
    ),
    "read-status": CommandContract(_fields(channel=Field("channel", allow_all=True, default="all"), max_errors=Field("positive_int", default=20))),
    "readback": CommandContract(_fields(channel=Field("channel", allow_all=True, default="all"))),
    "identify": CommandContract({}),
    "snapshot": CommandContract(_fields(max_errors=Field("positive_int", default=20))),
    "protection-status": CommandContract(_fields(channel=Field("channel", allow_all=True, default="all"), all=Field("bool"))),
    "protection-set": CommandContract(_fields(
        channel=Field("channel", allow_all=True, default="all"),
        all=Field("bool"),
        ovp_voltage=Field("nonnegative_number"),
        ocp=Field("enum", values=frozenset({"on", "off"})),
        ocp_delay=Field("nonnegative_number"),
        ocp_delay_trigger=Field("enum", values=frozenset({"setting-change", "cc-transition"})),
    ), at_least_one=(("ovp_voltage", "ocp", "ocp_delay", "ocp_delay_trigger"),)),
    "clear-protection": CommandContract(_fields(channel=ALL_CHANNEL, all=Field("bool")), exactly_one_of=(("channel", "all"),)),
    "set": CommandContract(_fields(channel=Field("channel", required=True), voltage=Field("nonnegative_number"), current=Field("nonnegative_number"), **_VERIFY_FIELDS, **_PULSE_FIELDS), at_least_one=(("voltage", "current"),), **_GENERAL_PULSE_CONTRACT_OPTIONS),
    "apply": CommandContract(_fields(channel=Field("channel", required=True, allow_all=True), voltage=Field("nonnegative_number", required=True), current=Field("nonnegative_number", required=True), no_output=BOOLEAN_FALSE, **_VERIFY_FIELDS, **_PULSE_FIELDS), **_GENERAL_PULSE_CONTRACT_OPTIONS),
    "output-on": CommandContract(_fields(channel=Field("channel", required=True, allow_all=True), **_VERIFY_FIELDS, **_PULSE_FIELDS), **_GENERAL_PULSE_CONTRACT_OPTIONS),
    "output-off": CommandContract(_fields(channel=Field("channel", required=True, allow_all=True), **_VERIFY_FIELDS, **_PULSE_FIELDS), **_GENERAL_PULSE_CONTRACT_OPTIONS),
    "safe-off": CommandContract(_fields(channel=Field("channel", required=True, allow_all=True), **_VERIFY_FIELDS, **_PULSE_FIELDS), **_GENERAL_PULSE_CONTRACT_OPTIONS),
    "output-state": CommandContract(_fields(channel=Field("channel", required=True, allow_all=True))),
    "cycle-output": CommandContract(_fields(channel=Field("channel", required=True, allow_all=True), duration_ms=Field("positive_int", default=500), **_VERIFY_FIELDS, **_PULSE_FIELDS), **_GENERAL_PULSE_CONTRACT_OPTIONS),
    "ramp": CommandContract(_fields(
        channel=Field("channel"),
        channels=Field("channel_list"),
        current=Field("nonnegative_number", required=True),
        start_voltage=Field("nonnegative_number", required=True),
        stop_voltage=Field("nonnegative_number", required=True),
        step_voltage=Field("positive_number", required=True),
        delay_ms=Field("nonnegative_int", default=0),
        enable_output=BOOLEAN_FALSE,
        loop_count=Field("range_int", default=1),
        completion_pulse_timing=Field("enum", default="segment", values=frozenset({"segment", "step", "loop"})),
        **_VERIFY_FIELDS,
        **_PULSE_FIELDS,
    ), exactly_one_of=(("channel", "channels"),), **_GENERAL_PULSE_CONTRACT_OPTIONS),
    "smoke-output": CommandContract(_fields(channel=Field("channel", required=True), voltage=Field("nonnegative_number", required=True), current=Field("nonnegative_number", required=True), duration_ms=Field("positive_int", default=500), **_VERIFY_FIELDS, **_PULSE_FIELDS), **_GENERAL_PULSE_CONTRACT_OPTIONS),
    "ramp-list": CommandContract(_fields(file=STRING, document=DOCUMENT, lint=BOOLEAN_FALSE, loop_count=Field("range_int")), mutually_exclusive=(("file", "document"),)),
    "sequence": CommandContract(_fields(file=STRING, document=DOCUMENT, lint=BOOLEAN_FALSE, loop_count=Field("range_int")), mutually_exclusive=(("file", "document"),)),
    "restore-from-snapshot": CommandContract(_fields(document=DOCUMENT, snapshot=STRING, file=STRING, channel=Field("channel", required=True, allow_all=True), restore_output_state=BOOLEAN_FALSE), mutually_exclusive=(("document", "snapshot", "file"),)),
    "trigger-pulse": CommandContract(_fields(channel=Field("channel", default=1), pin=Field("pin"), pins=Field("pin_list"), polarity=Field("enum", default="positive", values=frozenset({"positive", "negative"})), exclusive_pins=BOOLEAN_FALSE, max_errors=Field("positive_int", default=20)), exactly_one_of=(("pin", "pins"),)),
    "trigger-status": CommandContract(_fields(channel=Field("channel", allow_all=True, default="all"), max_errors=Field("positive_int", default=20))),
    "trigger-step": CommandContract(_fields(
        channel=Field("channel", required=True),
        source=Field("enum", default="bus", values=frozenset({"bus", "immediate", "pin1", "pin2", "pin3", "ext"})),
        voltage=Field("nonnegative_number"), current=Field("nonnegative_number"), fire=BOOLEAN_FALSE,
        wait_complete=BOOLEAN_FALSE, wait_timeout_ms=Field("positive_int", default=10000), poll_ms=Field("min50_int", default=200),
        **_PULSE_FIELDS,
    ), dependencies=_PULSE_DEPENDENCIES),
    "trigger-list": CommandContract(_fields(
        channel=Field("channel", required=True),
        source=Field("enum", default="bus", values=frozenset({"bus", "immediate", "pin1", "pin2", "pin3", "ext"})),
        voltages=Field("number_list"), currents=Field("number_list"), dwell=Field("number_list"),
        bost_list=Field("bool_list"), eost_list=Field("bool_list"), trigger_output_pins=Field("pin_list"),
        trigger_output_polarity=Field("enum", values=frozenset({"positive", "negative"})),
        count=Field("range_count", default=1), fire=BOOLEAN_FALSE, wait_complete=BOOLEAN_FALSE, exclusive_pins=BOOLEAN_FALSE,
        wait_timeout_ms=Field("positive_int", default=10000), poll_ms=Field("min50_int", default=200),
        completion_pulse_pins=Field("pin_list"), completion_pulse_polarity=Field("enum", values=frozenset({"positive", "negative"})),
        pins=Field("pin_list"), polarity=Field("enum", values=frozenset({"positive", "negative"})), leave_trigger_configured=BOOLEAN_FALSE,
    ), aliases={"voltage_list": "voltages", "current_list": "currents", "dwell_list": "dwell"}, mutually_exclusive=(("voltages", "voltage_list"), ("currents", "current_list"), ("dwell", "dwell_list"))),
    "trigger-fire": CommandContract(_fields(channel=CHANNEL, wait_complete=BOOLEAN_FALSE, wait_timeout_ms=Field("positive_int", default=10000), poll_ms=Field("min50_int", default=200))),
    "trigger-abort": CommandContract(_fields(channel=Field("channel", required=True, allow_all=True), max_errors=Field("positive_int", default=20))),
}

SEQUENCE_ACTION_CONTRACTS: dict[str, CommandContract] = {
    "measure": CommandContract(_fields(channel=Field("channel", default=1))),
    "readback": CommandContract(_fields(channel=Field("channel", default=1))),
    "output-state": CommandContract(_fields(channel=Field("channel", default=1, allow_all=True))),
    "log": CommandContract(_fields(message=Field("string", default=""))),
    "wait": CommandContract(_fields(seconds=Field("nonnegative_number", required=True)), aliases={"duration_sec": "seconds"}, mutually_exclusive=(("seconds", "duration_sec"),)),
    "trigger-pulse": CommandContract(_fields(channel=Field("channel", default=1), pins=Field("pin_list"), polarity=Field("enum", default="positive", values=frozenset({"positive", "negative"})), leave_trigger_configured=BOOLEAN_FALSE)),
    "safe-off": CommandContract(_fields(channel=Field("channel", default=1, allow_all=True))),
    "output-on": CommandContract(_fields(channel=Field("channel", default=1, allow_all=True))),
    "output-off": CommandContract(_fields(channel=Field("channel", default=1, allow_all=True))),
    "cycle-output": CommandContract(_fields(channel=Field("channel", default=1, allow_all=True), duration_ms=Field("positive_int", default=500))),
    "set": CommandContract(_fields(channel=Field("channel", default=1), voltage=Field("nonnegative_number", required=True), current=Field("nonnegative_number", required=True))),
    "apply": CommandContract(_fields(channel=Field("channel", default=1, allow_all=True), voltage=Field("nonnegative_number", required=True), current=Field("nonnegative_number", required=True), no_output=BOOLEAN_FALSE)),
}


_KNOWN_PARAMETER_NAMES = frozenset(
    name
    for contract in (*COMMAND_CONTRACTS.values(), *SEQUENCE_ACTION_CONTRACTS.values())
    for name in (
        *contract.fields,
        *(contract.aliases or {}),
        *(contract.removed_fields or {}),
    )
)


def command_parameter_names(command: str) -> frozenset[str]:
    """Return the Core-owned allowed parameter names for an adapter request."""

    contract = COMMAND_CONTRACTS.get(command)
    if contract is None:
        return frozenset()
    return frozenset(contract.fields)


def validate_sequence_action_parameters(action: str, parameters: Any) -> dict[str, Any]:
    """Validate one parsed Sequence action through the Core contract registry."""

    contract = SEQUENCE_ACTION_CONTRACTS[action]
    if not isinstance(parameters, dict):
        raise CoreValidationError(f"sequence {action} parameters must be an object")
    return _admit_parameters(
        f"sequence {action}", parameters, contract, materialize_defaults=True
    )


def validate_and_normalize_request(
    request: OperationRequest | TriggerRequest | SequenceRequest,
) -> OperationRequest | TriggerRequest | SequenceRequest:
    """Return an admitted request whose parameters contain only canonical typed values."""

    contract = COMMAND_CONTRACTS.get(request.command)
    if contract is None:
        raise CoreValidationError(f"unsupported core command {request.command!r}")
    if not isinstance(request.parameters, dict):
        raise CoreValidationError("parameters must be an object")
    raw = dict(request.parameters)
    if request.command.startswith("protection-") or request.command == "clear-protection":
        raw = _normalize_protection_selector(request.command, raw)
    semantic_defaults = request.command.startswith("trigger-") or request.command in {
        "read-status", "readback", "protection-status", "protection-set",
    }
    normalized = _admit_parameters(
        request.command, raw, contract, materialize_defaults=semantic_defaults
    )
    if request.command == "trigger-fire" and normalized["wait_complete"] and "channel" not in normalized:
        raise CoreValidationError("trigger-fire wait_complete requires channel as the abort target")
    return replace(request, parameters=normalized)


def _normalize_protection_selector(command: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Keep the legacy all flag at the boundary while exposing one selector."""

    if "channel" in raw and "all" in raw:
        raise CoreValidationError("channel and all are mutually exclusive")
    if "all" not in raw:
        return raw
    all_value = raw["all"]
    if type(all_value) is not bool:
        raise CoreValidationError("all must be a boolean")
    if not all_value:
        raise CoreValidationError("all=false is not a valid protection selector")
    raw = dict(raw)
    raw.pop("all")
    raw["channel"] = "all"
    return raw


def _admit_parameters(
    label: str,
    parameters: Any,
    contract: CommandContract,
    *,
    materialize_defaults: bool,
) -> dict[str, Any]:
    if not isinstance(parameters, dict):
        raise CoreValidationError(f"{label} parameters must be an object")
    raw = dict(parameters)
    aliases = contract.aliases or {}
    removed = contract.removed_fields or {}
    removed_present = sorted(set(raw) & set(removed))
    if removed_present:
        name = removed_present[0]
        raise CoreValidationError(f"{label} field {name} has been removed: {removed[name]}")
    for group in contract.mutually_exclusive:
        present = [name for name in group if name in raw]
        if len(present) > 1:
            if any(name in aliases or name in aliases.values() for name in present):
                raise CoreValidationError(f"{label} alias conflict: {', '.join(present)} cannot be supplied together")
            raise CoreValidationError(f"{label} mutually exclusive fields: {', '.join(present)}")
    for group in contract.exactly_one_of:
        present = [name for name in group if name in raw]
        if len(present) != 1:
            raise CoreValidationError(f"{label} requires exactly one of: {', '.join(group)}")
    for alias, canonical in aliases.items():
        if alias in raw:
            raw[canonical] = raw.pop(alias)
    unknown = sorted(set(raw) - set(contract.fields))
    if unknown:
        if label == "measure-all" and unknown == ["channel"]:
            raise CoreValidationError("measure-all always reads all channels and does not accept channel")
        unknown_fields = [name for name in unknown if name not in _KNOWN_PARAMETER_NAMES]
        if unknown_fields:
            raise CoreValidationError(f"{label} has unknown field(s): {', '.join(unknown_fields)}")
        raise CoreValidationError(
            f"{label} has known-but-inapplicable field(s): {', '.join(unknown)}"
        )
    normalized: dict[str, Any] = {}
    # Invalid supplied values are more useful than an unrelated missing field.
    for name, field in contract.fields.items():
        if name not in raw:
            continue
        value = raw[name]
        if value is None:
            if field.kind == "bool":
                raise CoreValidationError(f"{name} must be a boolean")
            if field.kind in {"channel", "pulse_channel"}:
                normalized[name] = _normalize_field(name, value, field)
                continue
            if not field.nullable:
                raise CoreValidationError(f"{name} must not be null")
            normalized[name] = None
        else:
            normalized[name] = _normalize_field(name, value, field)
    for group in contract.at_least_one:
        if not any(name in normalized for name in group):
            if label == "set" and group == ("voltage", "current"):
                raise CoreValidationError("set requires voltage, current, or both")
            raise CoreValidationError(f"{label} requires at least one of: {', '.join(group)}")
    for name, field in contract.fields.items():
        if name in normalized:
            continue
        if field.required:
            raise CoreValidationError(f"{label} requires {name}")
        if materialize_defaults and field.default is not _MISSING:
            normalized[name] = field.default
    for field, required_fields in (contract.dependencies or {}).items():
        if field in normalized and any(required not in normalized for required in required_fields):
            raise CoreValidationError(f"{label} {field} requires {', '.join(required_fields)}")
    if label == "ramp" and "channels" in normalized:
        channels = normalized["channels"]
        if len(set(channels)) != len(channels):
            raise CoreValidationError("ramp channels must not contain duplicates")
    return normalized


def _normalize_field(name: str, value: Any, field: Field) -> Any:
    kind = field.kind
    if kind == "any":
        return value
    if kind == "bool":
        if type(value) is not bool:
            raise CoreValidationError(f"{name} must be a boolean")
        return value
    if kind == "string":
        if not isinstance(value, str) or not value.strip():
            raise CoreValidationError(f"{name} must be a non-empty string")
        return value
    if kind == "object":
        if not isinstance(value, dict):
            raise CoreValidationError(f"{name} must be an object")
        return value
    if kind == "enum":
        if type(value) is not str or value not in field.values:
            raise CoreValidationError(f"{name} must be one of: {', '.join(sorted(field.values))}")
        return value
    if kind == "channel":
        if field.allow_all and type(value) is str and value == "all":
            return value
        if type(value) is not int or value < 1:
            suffix = " or 'all'" if field.allow_all else ""
            raise CoreValidationError(f"{name} must be a positive integer{suffix}")
        return value
    if kind == "pin":
        if type(value) is not int or value not in {1, 2, 3}:
            raise CoreValidationError(f"{name} must be one of rear pins 1, 2, or 3")
        return value
    if kind == "pulse_channel":
        if type(value) is not int or not 1 <= value <= 3:
            raise CoreValidationError("completion_pulse_channel must be an integer from 1 to 3")
        return value
    if kind == "pin_list":
        if not isinstance(value, (list, tuple)) or not value:
            raise CoreValidationError(f"{name} must be a non-empty list of rear pins")
        if any(type(pin) is not int or pin not in {1, 2, 3} for pin in value) or len(set(value)) != len(value):
            raise CoreValidationError(f"{name} must contain unique rear pins 1, 2, or 3")
        return tuple(value)
    if kind == "channel_list":
        if not isinstance(value, (list, tuple)) or not value:
            raise CoreValidationError(f"{name} must be a non-empty list of channels")
        if any(type(channel) is not int or channel < 1 for channel in value):
            raise CoreValidationError(f"{name} must contain positive integer channels")
        return tuple(value)
    if kind in {"number_list", "bool_list"}:
        if not isinstance(value, (list, tuple)):
            raise CoreValidationError(f"{name} must be a list")
        if kind == "bool_list":
            if any(type(item) is not bool for item in value):
                raise CoreValidationError(f"{name} must contain exact booleans")
            return tuple(value)
        return tuple(_number(name, item) for item in value)
    if kind in {"int", "positive_int", "nonnegative_int", "min50_int", "range_int", "range_count"}:
        if type(value) is not int:
            raise CoreValidationError(f"{name} must be an exact integer")
        if kind == "positive_int" and value < 1:
            raise CoreValidationError(f"{name} must be positive")
        if kind == "nonnegative_int" and value < 0:
            raise CoreValidationError(f"{name} must be non-negative")
        if kind == "min50_int" and value < 50:
            raise CoreValidationError(f"{name} must be at least 50")
        if kind == "range_int" and not 1 <= value <= MAX_LOOP_COUNT:
            raise CoreValidationError(
                f"{name} must be an integer from 1 to {MAX_LOOP_COUNT:,}"
            )
        if kind == "range_count" and not 1 <= value <= 256:
            raise CoreValidationError(f"{name} must be an integer from 1 to 256")
        return value
    number = _number(name, value)
    if kind == "nonnegative_number" and number < 0:
        raise CoreValidationError(f"{name} must be a finite non-negative number")
    if kind == "positive_number" and number <= 0:
        raise CoreValidationError(f"{name} must be positive")
    return number


def _number(name: str, value: Any) -> int | float:
    if type(value) not in {int, float} or not math.isfinite(value):
        raise CoreValidationError(f"{name} must be a finite number")
    return value
