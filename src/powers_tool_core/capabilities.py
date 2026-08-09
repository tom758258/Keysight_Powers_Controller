"""Shared command capability metadata for the CLI and future adapters."""

from __future__ import annotations

from typing import Any

from powers_tool_core.core import CoreValidationError, UnsupportedModelError
from powers_tool_core.identity import GENERIC_SCPI_PLANNING_PROFILE_ID

E36312A_MODEL_ID = "keysight-e36312a"
EDU36311A_MODEL_ID = "keysight-edu36311a"
E3646A_MODEL_ID = "keysight-e3646a"
PSM2010_MODEL_ID = "gw-instek-psm-2010"

READ_ONLY_COMMANDS = frozenset(
    {
        "identify",
        "measure",
        "output-state",
        "readback",
        "read-status",
        "validate-readonly",
        "log",
        "sequence",
        "capabilities",
    }
)
OUTPUT_COMMANDS = frozenset(
    {
        "set",
        "output-on",
        "output-off",
        "safe-off",
        "cycle-output",
        "apply",
        "ramp",
        "ramp-list",
        "smoke-output",
    }
)
E36312A_ONLY_COMMANDS = (
    "measure-all",
    "snapshot",
    "trigger-pulse",
    "trigger-status",
    "trigger-step",
    "trigger-list",
    "trigger-fire",
    "trigger-abort",
)
TRIGGER_COMMANDS = frozenset(
    {
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    }
)
OFFLINE_COMMANDS = frozenset({"snapshot-diff", "hardware-report", "doctor", "safety inspect"})

_E36312A_EXTRA_COMMANDS = frozenset(
    {
        "measure-all",
        "protection-status",
        "protection-set",
        "clear-protection",
        "snapshot",
        "restore-from-snapshot",
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    }
)
_DRY_RUN_TRIGGER_COMMANDS = frozenset(
    {
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    }
)
_PSM2010_ENABLED_COMMANDS = frozenset(
    {
        "identify",
        "measure",
        "output-state",
        "readback",
        "read-status",
        "capabilities",
        "output-off",
        "safe-off",
    }
)
_PSM2010_DRY_RUN_COMMANDS = frozenset(
    {
        "identify",
        "output-state",
        "output-off",
        "safe-off",
    }
)


def hardware_validation_status(model_id: str | None) -> dict[str, Any]:
    """Return hardware validation status payload for a selected model."""

    if model_id == E36312A_MODEL_ID:
        return {
            "read_only": "validated",
            "output": "validated",
            "protection": "validated",
            "trigger": "validated",
        }
    if model_id == EDU36311A_MODEL_ID:
        return {
            "read_only": "validated",
            "output": "validated",
            "protection": {
                "dry_run": True,
                "simulate": True,
                "real": True,
                "hardware_validation": "validated",
            },
            "trigger": "not_supported_by_model",
        }
    if model_id == E3646A_MODEL_ID:
        return {
            "read_only": "rs232_read_only",
            "output": "validated",
            "protection": "not_enabled",
            "trigger": "not_enabled",
        }
    if model_id == PSM2010_MODEL_ID:
        return {
            "read_only": "not_enabled",
            "output": "not_enabled",
            "protection": "not_enabled",
            "trigger": "not_enabled",
        }
    return {
        "read_only": "generic_channel_1_only",
        "output": "not_enabled",
        "protection": "not_enabled",
        "trigger": "not_enabled",
    }


def command_support(model_id: str | None) -> dict[str, dict[str, Any]]:
    """Return per-command support metadata for a canonical physical model ID."""

    normalized = model_id or ""
    edu36311a_real = READ_ONLY_COMMANDS | OUTPUT_COMMANDS | {
        "protection-status",
        "protection-set",
        "clear-protection",
    }
    e3646a_real = {"identify", "measure", "output-state", "readback", "read-status", "capabilities"}
    e3646a_output = {
        "set",
        "output-on",
        "output-off",
        "safe-off",
        "cycle-output",
        "apply",
        "ramp",
        "ramp-list",
        "smoke-output",
        "sequence",
    }
    commands = sorted(READ_ONLY_COMMANDS | OUTPUT_COMMANDS | _E36312A_EXTRA_COMMANDS | OFFLINE_COMMANDS)
    support: dict[str, dict[str, Any]] = {}
    for command in commands:
        entry = {
            "real": False,
            "simulate": False,
            "dry_run": False,
            "requires_confirm": command
            in {
                "output-on",
                "cycle-output",
                "apply",
                "smoke-output",
                "protection-set",
                "clear-protection",
                "restore-from-snapshot",
            },
            "hardware_validation": "not_enabled",
        }
        if command in OFFLINE_COMMANDS:
            entry.update(
                {
                    "real": True,
                    "simulate": True,
                    "dry_run": False,
                    "requires_confirm": False,
                    "hardware_validation": "not_applicable",
                }
            )
        elif normalized == E36312A_MODEL_ID:
            if command in READ_ONLY_COMMANDS | OUTPUT_COMMANDS | _E36312A_EXTRA_COMMANDS:
                entry["real"] = True
                entry["simulate"] = True
                entry["dry_run"] = command in READ_ONLY_COMMANDS or command in OUTPUT_COMMANDS or command in _DRY_RUN_TRIGGER_COMMANDS or command in {"protection-set", "clear-protection", "restore-from-snapshot"}
                entry["hardware_validation"] = "validated"
            if command in {"output-on", "cycle-output", "apply", "smoke-output"}:
                entry["hardware_validation"] = "validated_confirm_threshold_conditional"
        elif normalized == EDU36311A_MODEL_ID:
            if command in edu36311a_real:
                entry["real"] = True
                entry["simulate"] = True
                entry["dry_run"] = command in READ_ONLY_COMMANDS or command in OUTPUT_COMMANDS or command in {"protection-set", "clear-protection"}
                entry["hardware_validation"] = "validated"
            if command in {"output-on", "cycle-output", "apply", "smoke-output"}:
                entry["hardware_validation"] = "validated_confirm_threshold_conditional"
            if command in {"protection-set", "clear-protection"}:
                entry.update(
                    {
                        "real": True,
                        "simulate": True,
                        "dry_run": True,
                        "requires_confirm": True,
                        "hardware_validation": "validated",
                    }
                )
            if command in TRIGGER_COMMANDS:
                entry.update(
                    {
                        "real": False,
                        "simulate": False,
                        "dry_run": False,
                        "requires_confirm": False,
                        "hardware_validation": "not_supported_by_model",
                    }
                )
            if command in {"snapshot", "restore-from-snapshot"}:
                entry["hardware_validation"] = "not_supported_by_model"
        elif normalized == E3646A_MODEL_ID:
            if command == "log":
                entry["real"] = True
                entry["simulate"] = True
                entry["dry_run"] = False
                entry["hardware_validation"] = "rs232_read_only"
            if command in e3646a_real and command not in e3646a_output:
                entry["real"] = True
                entry["simulate"] = True
                entry["dry_run"] = command in READ_ONLY_COMMANDS
                entry["hardware_validation"] = "rs232_read_only"
            elif command in e3646a_output:
                entry["real"] = True
                entry["simulate"] = True
                entry["dry_run"] = command in OUTPUT_COMMANDS or command == "sequence"
                entry["hardware_validation"] = "validated"
                if command in {"apply", "output-on", "cycle-output", "smoke-output"}:
                    entry["hardware_validation"] = "validated_confirm_threshold_conditional"
        elif normalized == PSM2010_MODEL_ID:
            if command in _PSM2010_ENABLED_COMMANDS:
                entry["real"] = True
                entry["simulate"] = True
                entry["dry_run"] = command in _PSM2010_DRY_RUN_COMMANDS
                entry["hardware_validation"] = "not_enabled"
        else:
            if command in {"identify", "measure", "doctor", "capabilities"}:
                entry["real"] = True
                entry["simulate"] = True
                entry["hardware_validation"] = "generic_channel_1_only"
            if normalized == GENERIC_SCPI_PLANNING_PROFILE_ID and command in READ_ONLY_COMMANDS | OUTPUT_COMMANDS:
                entry["simulate"] = True
                entry["dry_run"] = True
                entry["hardware_validation"] = "generic_channel_1_only"
        if normalized not in {E36312A_MODEL_ID, EDU36311A_MODEL_ID} and command in TRIGGER_COMMANDS:
            entry.update(
                {
                    "real": False,
                    "simulate": False,
                    "dry_run": False,
                    "requires_confirm": False,
                    "hardware_validation": "not_enabled",
                }
            )
        if command == "log":
            entry["dry_run"] = False
        if normalized == PSM2010_MODEL_ID and command == "doctor":
            entry.update(
                {
                    "real": False,
                    "simulate": False,
                    "dry_run": False,
                    "requires_confirm": False,
                    "hardware_validation": "not_enabled",
                }
            )
        support[command] = entry
    return support


def planning_identity_command_support(
    planning_model_id: str | None,
    planning_profile_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Return support for one explicit physical or nonphysical planning identity."""

    if planning_model_id is not None and planning_profile_id is not None:
        raise CoreValidationError(
            "planning_model_id and planning_profile_id are mutually exclusive"
        )
    return command_support(planning_profile_id or planning_model_id)


def planning_identity_hardware_validation_status(
    planning_model_id: str | None,
) -> dict[str, Any]:
    """Return hardware status for a canonical physical planning identity."""

    return hardware_validation_status(planning_model_id)


def ensure_command_supported(
    command: str,
    planning_model_id: str | None,
    planning_profile_id: str | None,
    mode: str,
) -> None:
    """Raise if the command is disabled for the selected model and runtime mode."""

    mode_key = "dry_run" if mode == "dry-run" else mode
    support = planning_identity_command_support(
        planning_model_id,
        planning_profile_id,
    ).get(command)
    if support is None:
        raise CoreValidationError(f"unsupported core command {command!r}")
    if support.get(mode_key) is True:
        return
    identity_label = planning_profile_id or planning_model_id
    mode_label = "dry-run" if mode_key == "dry_run" else mode_key
    detail = unsupported_command_message(command, identity_label, mode_label)
    raise UnsupportedModelError(detail)


def unsupported_command_message(command: str, identity: str | None, mode: str) -> str:
    """Return a user-facing unsupported command message."""

    model_label = _identity_display_label(identity)
    mode_label = "dry-run" if mode == "dry_run" else mode
    reason = unsupported_command_reason(command, model_label)
    detail = f"{command} is not supported for {model_label} in {mode_label} mode."
    if reason:
        detail = f"{detail}\n{reason}"
    if mode_label in {"dry-run", "simulate"}:
        detail = (
            f"{detail}\n"
            "--model is not a feature unlock and does not enable unsupported commands."
        )
    return detail


def unsupported_command_reason(command: str, identity: str | None) -> str:
    """Return the policy reason for an unsupported model/command pair."""

    model_label = _identity_display_label(identity)
    if identity == GENERIC_SCPI_PLANNING_PROFILE_ID or identity is None:
        return "generic-scpi is a no-hardware planning profile, not a live expected model."
    if model_label == "EDU36311A":
        if command in TRIGGER_COMMANDS:
            return (
                "EDU36311A trigger/native LIST workflows are disabled in live, simulate, and dry-run. "
                "Use E36312A for trigger/native LIST workflows, or choose a supported EDU36311A command "
                "such as read-only, output, or protection."
            )
        if command in {"snapshot", "restore-from-snapshot"}:
            return (
                f"{command} is currently E36312A-only. "
                f"EDU36311A {command} remains disabled until separately implemented and hardware validated."
            )
    if model_label == "E3646A":
        if command in {"protection-set", "clear-protection", "protection-status"}:
            return (
                "E3646A protection workflows are disabled until separately validated. "
                "E3646A software ramp-list and step-limited sequence remain available for validated "
                "output/read-only workflows."
            )
        if command in {"trigger-step", "trigger-list", "trigger-status", "trigger-fire", "trigger-abort"}:
            return (
                "E3646A native LIST and trigger workflows are disabled until separately validated. "
                "E3646A ramp-list and sequence are software workflows, not native LIST."
            )
        if command in {"snapshot", "restore-from-snapshot"}:
            return "E3646A snapshot/restore workflows are disabled until separately validated."
        if command == "trigger-pulse":
            return (
                "E3646A completion-pulse workflows are disabled until separately validated. "
                "E3646A ramp-list and sequence are software workflows, not native LIST."
            )
    e36312a_support = command_support(E36312A_MODEL_ID).get(command, {})
    if any(e36312a_support.get(key) is True for key in ("real", "simulate", "dry_run")):
        return "This workflow is currently E36312A-only for supported modes."
    return "This command is intentionally disabled by the model feature-lock policy."


def _identity_display_label(identity: str | None) -> str:
    if identity is None or identity == GENERIC_SCPI_PLANNING_PROFILE_ID:
        return identity or GENERIC_SCPI_PLANNING_PROFILE_ID
    from powers_tool_core.identity import IDENTITY_INDEXES

    model = IDENTITY_INDEXES.models_by_id.get(identity)
    return model.canonical_model if model is not None else identity


def known_capability_commands() -> set[str]:
    """Return all commands accepted by the capabilities command filter."""

    return set(command_support(E36312A_MODEL_ID)) | set(command_support(E3646A_MODEL_ID)) | set(command_support(EDU36311A_MODEL_ID)) | set(command_support(None))


def capabilities_static_groups() -> dict[str, list[str]]:
    """Return stable command group lists used by the capabilities JSON payload."""

    return {
        "read_only_commands": ["identify", "measure", "output-state", "readback", "read-status", "log", "sequence"],
        "output_commands": ["set", "output-on", "output-off", "safe-off", "cycle-output", "apply", "ramp", "ramp-list", "smoke-output"],
        "e36312a_only_commands": list(E36312A_ONLY_COMMANDS),
    }
