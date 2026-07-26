"""Validation shared by adapters and core workflow execution."""

from __future__ import annotations

from collections import deque
from typing import Any, Callable, Generic, TypeVar

from powers_tool_core.core import CoreValidationError, OperationRequest


GENERAL_PULSE_COMMANDS = frozenset(
    {
        "set",
        "apply",
        "output-on",
        "output-off",
        "safe-off",
        "cycle-output",
        "ramp",
        "smoke-output",
    }
)

COMPLETION_PULSE_PLANNING_MODEL_ID = "keysight-e36312a"
MAX_LOOP_COUNT = 10_000
MAX_TOTAL_EXECUTION_UNITS = 1_000_000
EXECUTION_WARNING_THRESHOLD = 100_000
MAX_RETAINED_RESULT_DETAILS = 200

ProgressReporter = Callable[[dict[str, int | float]], None]
_T = TypeVar("_T")


def normalize_loop_count(value: Any, *, field: str = "loop_count") -> int:
    """Return the strict finite workflow iteration count."""

    if type(value) is not int or not 1 <= value <= MAX_LOOP_COUNT:
        raise CoreValidationError(
            f"{field} must be an integer from 1 to {MAX_LOOP_COUNT:,}"
        )
    return value


def validate_execution_units(
    loop_count: int,
    units_per_loop: int,
    *,
    workflow: str,
    reduction_hint: str,
) -> int:
    """Return admitted logical work for one workflow."""

    total = loop_count * units_per_loop
    if total > MAX_TOTAL_EXECUTION_UNITS:
        raise CoreValidationError(
            f"{workflow} requires {total:,} execution units; the maximum allowed is "
            f"{MAX_TOTAL_EXECUTION_UNITS:,}. Reduce Loop count or {reduction_hint}."
        )
    return total


def execution_warning(total_units: int, *, reduction_hint: str) -> str | None:
    if total_units <= EXECUTION_WARNING_THRESHOLD:
        return None
    return (
        f"Long-running workflow: {total_units:,} execution units "
        f"(maximum {MAX_TOTAL_EXECUTION_UNITS:,}). Consider reducing Loop count "
        f"or {reduction_hint}."
    )


class BoundedResultDetails(Generic[_T]):
    """Retain the first and last half of a bounded result detail stream."""

    def __init__(self, maximum: int = MAX_RETAINED_RESULT_DETAILS) -> None:
        self._head_limit = maximum // 2
        self._tail_limit = maximum - self._head_limit
        self._head: list[_T] = []
        self._tail: deque[_T] = deque(maxlen=self._tail_limit)
        self.total = 0

    def append(self, value: _T) -> None:
        self.total += 1
        if len(self._head) < self._head_limit:
            self._head.append(value)
        else:
            self._tail.append(value)

    def retained(self) -> list[_T]:
        return [*self._head, *self._tail]

    def metadata(self, prefix: str) -> dict[str, int | bool]:
        retained = min(self.total, MAX_RETAINED_RESULT_DETAILS)
        return {
            f"{prefix}_total": self.total,
            f"{prefix}_retained": retained,
            f"{prefix}_truncated": self.total > retained,
        }


class ExecutionProgress:
    """Emit progress only when its integer percentage increases."""

    def __init__(
        self,
        total_units: int,
        reporter: ProgressReporter | None = None,
    ) -> None:
        self.total_units = total_units
        self.completed_units = 0
        self._reporter = reporter
        self._last_percent = 0

    def complete_unit(self) -> None:
        self.completed_units += 1
        percent = min(100, self.completed_units * 100 // self.total_units)
        if self._reporter is not None and percent > self._last_percent:
            self._last_percent = percent
            self._reporter(self.snapshot())

    def snapshot(self) -> dict[str, int | float]:
        return {
            "completed_units": self.completed_units,
            "total_units": self.total_units,
            "percent": min(100, self.completed_units * 100 // self.total_units),
        }


def normalize_completion_pulse_channel(value: Any) -> int:
    """Return one strict output-channel anchor for a completion pulse."""

    if type(value) is not int or not 1 <= value <= 3:
        raise CoreValidationError("completion_pulse_channel must be an integer from 1 to 3")
    return value


def validate_general_workflow_parameters(request: OperationRequest) -> None:
    """Validate execution-relevant general workflow semantics."""

    if request.command not in GENERAL_PULSE_COMMANDS:
        return
    if request.command == "set" and request.parameters.get("voltage") is None and request.parameters.get("current") is None:
        raise CoreValidationError("set requires voltage, current, or both")
    if request.command != "ramp" and "completion_pulse_timing" in request.parameters:
        raise CoreValidationError("completion_pulse_timing is only accepted by ramp")
    if request.command == "ramp":
        normalize_loop_count(request.parameters.get("loop_count", 1))
    # Direct operation helpers remain public test/programmatic entry points;
    # admitted requests take the registry dependency path above this layer.
    if "completion_pulse_channel" in request.parameters:
        normalize_completion_pulse_channel(request.parameters["completion_pulse_channel"])
        if "completion_pulse_pins" not in request.parameters:
            raise CoreValidationError("completion_pulse_channel requires completion_pulse_pins")


def validate_completion_pulse_planning_model(
    request: OperationRequest,
    *,
    requested: bool,
    context: str = "completion-pulse options",
) -> None:
    """Require the E36312A physical model for no-hardware pulse planning."""

    if not requested or not (request.runtime.dry_run or request.runtime.simulate):
        return
    if request.runtime.planning_model_id == COMPLETION_PULSE_PLANNING_MODEL_ID:
        return
    selected = request.runtime.planning_profile_id or request.runtime.planning_model_id or "missing"
    raise CoreValidationError(
        f"{context} require planning_model_id {COMPLETION_PULSE_PLANNING_MODEL_ID!r}; "
        f"received {selected!r}"
    )
