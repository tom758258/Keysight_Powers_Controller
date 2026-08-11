"""Canonical feature inventories shared by runtime and live-support policy."""

from __future__ import annotations

FEATURE_KIND_SEQUENCE_ACTION = "sequence_action"
FEATURE_KIND_TRIGGER_SOURCE = "trigger_source"
FEATURE_AWARE_LIVE_COMMANDS = frozenset({"sequence", "trigger-step", "trigger-list"})

SEQUENCE_ACTIONS = frozenset(
    {
        "measure",
        "readback",
        "output-state",
        "log",
        "wait",
        "safe-off",
        "set",
        "output-on",
        "output-off",
        "cycle-output",
        "apply",
        "trigger-pulse",
    }
)
HOST_ONLY_SEQUENCE_ACTIONS = frozenset({"wait", "log"})
INSTRUMENT_SEQUENCE_ACTIONS = SEQUENCE_ACTIONS - HOST_ONLY_SEQUENCE_ACTIONS
REAL_TRIGGER_SOURCES = frozenset({"bus", "immediate"})

SUPPORTED_SEQUENCE_ACTIONS_BY_MODEL_ID = {
    "keysight-e36312a": INSTRUMENT_SEQUENCE_ACTIONS,
    "keysight-edu36311a": INSTRUMENT_SEQUENCE_ACTIONS - {"trigger-pulse"},
    "keysight-e3646a": INSTRUMENT_SEQUENCE_ACTIONS - {"trigger-pulse"},
    "gw-instek-psm-2010": INSTRUMENT_SEQUENCE_ACTIONS - {"trigger-pulse"},
}
SUPPORTED_REAL_TRIGGER_SOURCES_BY_MODEL_ID = {
    "keysight-e36312a": REAL_TRIGGER_SOURCES,
    "keysight-edu36311a": frozenset(),
    "keysight-e3646a": frozenset(),
    "gw-instek-psm-2010": frozenset(),
}


def normalize_sequence_action(value: str) -> str:
    """Return a canonical sequence action without inventing parser aliases."""

    normalized = (value or "").strip().lower()
    if normalized not in SEQUENCE_ACTIONS:
        raise ValueError(f"unsupported sequence action: {value!r}")
    return normalized


def normalize_real_trigger_source(value: str) -> str:
    """Return the canonical real-live trigger source."""

    normalized = (value or "").strip().lower()
    if normalized == "imm":
        normalized = "immediate"
    if normalized not in REAL_TRIGGER_SOURCES:
        raise ValueError(f"unsupported real trigger source: {value!r}")
    return normalized


def supported_sequence_actions_for_model_id(model_id: str | None) -> frozenset[str]:
    """Return current actions for a canonical physical model ID."""

    return SUPPORTED_SEQUENCE_ACTIONS_BY_MODEL_ID.get(model_id, frozenset())


def supported_real_trigger_sources_for_model_id(model_id: str | None) -> frozenset[str]:
    """Return current trigger sources for a canonical physical model ID."""

    return SUPPORTED_REAL_TRIGGER_SOURCES_BY_MODEL_ID.get(model_id, frozenset())


def sequence_feature_requirements(plan: dict[str, object]) -> tuple[tuple[str, str], ...]:
    """Return distinct normalized instrument actions required by a sequence plan."""

    steps = plan.get("steps", [])
    actions: set[str] = set()
    for step in steps:
        if not isinstance(step, dict):
            continue
        action = normalize_sequence_action(str(step["action"]))
        if action not in HOST_ONLY_SEQUENCE_ACTIONS:
            actions.add(action)
    return tuple((FEATURE_KIND_SEQUENCE_ACTION, action) for action in sorted(actions))


def trigger_feature_requirements(command: str, source: str) -> tuple[tuple[str, str], ...]:
    """Return the trigger-source requirement for source-selecting commands."""

    if command not in {"trigger-step", "trigger-list"}:
        return ()
    return ((FEATURE_KIND_TRIGGER_SOURCE, normalize_real_trigger_source(source)),)
