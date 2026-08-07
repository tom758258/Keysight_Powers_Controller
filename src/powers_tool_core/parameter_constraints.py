"""Shared numeric parameter constraints for command adapters."""

from __future__ import annotations

import math
from typing import Any

from powers_tool_core.core import CoreValidationError, OperationRequest, SequenceRequest, TriggerRequest


PARAMETER_CONSTRAINTS: dict[str, dict[str, Any]] = {
    "voltage": {"min": 0, "step": "any", "unit": "V", "description": "Finite non-negative voltage setpoint."},
    "current": {"min": 0, "step": "any", "unit": "A", "description": "Finite non-negative current setpoint or limit."},
    "start_voltage": {"min": 0, "step": "any", "unit": "V", "description": "Finite non-negative starting voltage."},
    "stop_voltage": {"min": 0, "step": "any", "unit": "V", "description": "Finite non-negative final voltage."},
    "step_voltage": {"exclusive_min": 0, "step": "any", "unit": "V", "description": "Finite positive voltage step size."},
    "delay_ms": {"min": 0, "step": 1, "unit": "ms", "description": "Additional delay after each voltage step before starting the next step."},
    "hold_ms": {"min": 0, "step": 1, "unit": "ms", "description": "Non-negative hold after a ramp segment."},
    "settle_ms": {"min": 0, "step": 1, "unit": "ms", "description": "Non-negative wait before optional verification."},
    "duration_ms": {"min": 1, "step": 1, "unit": "ms", "description": "Positive output-on duration."},
    "max_reads": {"min": 1, "step": 1, "description": "Positive maximum read count."},
    "max_errors": {"min": 1, "step": 1, "description": "Positive maximum error queue read count."},
    "wait_timeout_ms": {"min": 1, "step": 1, "unit": "ms", "description": "Positive trigger wait timeout."},
    "poll_ms": {"min": 50, "step": 1, "unit": "ms", "description": "Trigger completion polling interval."},
    "count": {"min": 1, "max": 256, "step": 1, "description": "Trigger LIST repeat count."},
    "dwell_list": {"min": 0.01, "max": 3600, "step": "any", "unit": "s", "description": "Trigger LIST dwell values."},
    "ovp_voltage": {"min": 0, "step": "any", "unit": "V", "description": "Finite non-negative OVP threshold."},
    "ocp_delay": {"min": 0, "step": "any", "unit": "s", "description": "Finite non-negative OCP delay."},
    "seconds": {"min": 0, "step": "any", "unit": "s", "description": "Finite non-negative Sequence wait."},
}

INTEGER_PARAMETERS = frozenset(
    {"delay_ms", "hold_ms", "settle_ms", "duration_ms", "max_reads", "max_errors", "wait_timeout_ms", "poll_ms", "count"}
)
NONNEGATIVE_LIST_PARAMETERS = frozenset({"voltage_list", "current_list", "voltages", "currents"})
COMMAND_SPECIFIC_PARAMETERS = {
    "duration_ms": frozenset({"cycle-output", "smoke-output"}),
}
ALL_CHANNEL_COMMANDS = frozenset(
    {
        "apply",
        "output-on",
        "output-off",
        "safe-off",
        "output-state",
        "cycle-output",
        "read-status",
        "readback",
        "protection-status",
        "protection-set",
        "clear-protection",
        "restore-from-snapshot",
        "trigger-status",
        "trigger-abort",
        "log",
    }
)
CHANNEL_FORBIDDEN_COMMANDS = frozenset({"measure-all"})


def parameter_constraints_metadata() -> dict[str, dict[str, Any]]:
    return {name: dict(constraint) for name, constraint in PARAMETER_CONSTRAINTS.items()}


def validate_request_parameters(request: OperationRequest | TriggerRequest | SequenceRequest) -> None:
    """Reject invalid top-level numeric data before any VISA I/O."""

    if "channel" in request.parameters:
        if request.command in CHANNEL_FORBIDDEN_COMMANDS:
            raise CoreValidationError(
                f"{request.command} always reads all channels and does not accept channel"
            )
        strict_channel_parameter(
            request.parameters,
            "channel",
            allow_all=request.command in ALL_CHANNEL_COMMANDS,
        )
    if request.command == "restore-from-snapshot":
        strict_boolean_parameter(request.parameters, "restore_output_state", default=False)
    if request.command == "ramp":
        strict_boolean_parameter(request.parameters, "enable_output", default=False)

    for name, constraint in PARAMETER_CONSTRAINTS.items():
        if name not in request.parameters or request.parameters[name] is None:
            continue
        if name in COMMAND_SPECIFIC_PARAMETERS and request.command not in COMMAND_SPECIFIC_PARAMETERS[name]:
            continue
        value = request.parameters[name]
        if name == "dwell_list":
            _validate_number_list(name, value, minimum=0.01, maximum=3600)
        else:
            _validate_number(name, value, constraint, integer=name in INTEGER_PARAMETERS)
    for name in NONNEGATIVE_LIST_PARAMETERS:
        if name in request.parameters and request.parameters[name] is not None:
            _validate_number_list(name, request.parameters[name], minimum=0)


def strict_boolean_parameter(
    parameters: dict[str, Any],
    name: str,
    *,
    default: bool,
) -> bool:
    """Return one exact boolean parameter without coercing external data."""

    if name not in parameters:
        return default
    value = parameters[name]
    if type(value) is not bool:
        raise CoreValidationError(f"{name} must be a boolean")
    return value


def strict_channel_parameter(
    parameters: dict[str, Any],
    name: str = "channel",
    *,
    allow_all: bool,
    required: bool = False,
    default: int | str | None = None,
) -> int | str | None:
    """Return one exact channel selection without coercing external data."""

    if name not in parameters:
        if required:
            raise CoreValidationError(f"{name} is required")
        return default
    value = parameters[name]
    if value == "all" and type(value) is str:
        if allow_all:
            return value
        raise CoreValidationError(f"{name} must be a positive integer")
    if type(value) is not int or value < 1:
        suffix = " or 'all'" if allow_all else ""
        raise CoreValidationError(f"{name} must be a positive integer{suffix}")
    return value


def _validate_number(name: str, value: Any, constraint: dict[str, Any], *, integer: bool) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CoreValidationError(f"{name} must be {'an integer' if integer else 'a number'}")
    if integer and not isinstance(value, int):
        raise CoreValidationError(f"{name} must be an integer")
    number = float(value)
    if not math.isfinite(number):
        raise CoreValidationError(f"{name} must be finite")
    if "exclusive_min" in constraint and number <= constraint["exclusive_min"]:
        raise CoreValidationError(f"{name} must be greater than {constraint['exclusive_min']}")
    if "min" in constraint and number < constraint["min"]:
        raise CoreValidationError(f"{name} must be at least {constraint['min']}")
    if "max" in constraint and number > constraint["max"]:
        raise CoreValidationError(f"{name} must be at most {constraint['max']}")


def _validate_number_list(name: str, value: Any, *, minimum: float, maximum: float | None = None) -> None:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise CoreValidationError(f"{name} must be a list of numbers")
    for item in value:
        constraint: dict[str, Any] = {"min": minimum}
        if maximum is not None:
            constraint["max"] = maximum
        _validate_number(name, item, constraint, integer=False)
