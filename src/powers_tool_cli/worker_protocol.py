"""Worker protocol definitions, constants, and payload validation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, TYPE_CHECKING

from powers_tool_core.command_runner import validate_request_admission
from powers_tool_core.core import (
    CoreValidationError,
    OperationRequest,
    RuntimeOptions,
    SequenceRequest,
    TriggerRequest,
)

if TYPE_CHECKING:
    from powers_tool_cli.worker_state import WorkerState

_WORKER_COMMAND_TAXONOMY: dict[str, str] = {
    # Read-only / status
    "identify": "read_only",
    "read-status": "read_only",
    "readback": "read_only",
    "measure": "read_only",
    "measure-all": "read_only",
    "output-state": "read_only",
    "protection-status": "read_only",
    "error": "read_only",
    "snapshot": "read_only",
    "log": "read_only",
    # Output / setpoint
    "set": "output",
    "apply": "output",
    "output-on": "output",
    "output-off": "output",
    "safe-off": "output",
    "cycle-output": "output",
    "ramp": "output",
    "ramp-list": "output",
    "smoke-output": "output",
    # Protection / restore / sequence
    "protection-set": "protection",
    "clear-protection": "protection",
    "restore-from-snapshot": "protection",
    "sequence": "protection",
    # Trigger
    "trigger-pulse": "trigger",
    "trigger-status": "trigger",
    "trigger-step": "trigger",
    "trigger-list": "trigger",
    "trigger-fire": "trigger",
    "trigger-abort": "trigger",
    # Core commands unsupported by Worker
    "list-resources": "unsupported",
    "verify": "unsupported",
    "clear": "unsupported",
}

READ_ONLY_COMMANDS = {cmd for cmd, cat in _WORKER_COMMAND_TAXONOMY.items() if cat == "read_only"}
OUTPUT_COMMANDS = {cmd for cmd, cat in _WORKER_COMMAND_TAXONOMY.items() if cat == "output"}
PROTECTION_COMMANDS = {cmd for cmd, cat in _WORKER_COMMAND_TAXONOMY.items() if cat == "protection"}
TRIGGER_COMMANDS = {cmd for cmd, cat in _WORKER_COMMAND_TAXONOMY.items() if cat == "trigger"}
ALLOWED_COMMANDS = READ_ONLY_COMMANDS | OUTPUT_COMMANDS | PROTECTION_COMMANDS | TRIGGER_COMMANDS
OUTPUT_AFFECTING_COMMANDS = OUTPUT_COMMANDS | PROTECTION_COMMANDS
WORKER_SCHEMA_VERSION = 2
REQUEST_KEYS = {"schema_version", "command", "arguments", "job_id", "context"}
CONTEXT_KEYS = {
    "mode",
    "planning_model_id",
    "expected_model_id",
    "planning_profile_id",
}
RUNTIME_ARGUMENT_KEYS = {"confirm_output"}
FORBIDDEN_CONTEXT_ARGUMENTS = {
    "dry_run",
    "simulate",
    "live",
    "planning_model_id",
    "expected_model_id",
    "planning_profile_id",
    "model",
    "model_profile",
    "profile",
}
_LEGACY_IDENTITY_ARGUMENTS = {"model_profile", "model"}
_IDENTITY_SETTING_FIELDS = {
    *_LEGACY_IDENTITY_ARGUMENTS,
    "planning_model_id",
    "expected_model_id",
    "planning_profile_id",
}
_FORBIDDEN_VALIDATION_MODE_ARGUMENTS = {
    "support_policy_mode",
    "validation_allow_pending_live_support",
}
_FORBIDDEN_VALIDATION_MODE_SETTINGS = _FORBIDDEN_VALIDATION_MODE_ARGUMENTS


def _command_response(status: str, command: Any, job_id: Any, **extra: Any) -> dict[str, Any]:
    payload = {
        "schema_version": WORKER_SCHEMA_VERSION,
        "status": status,
        "command": command,
        "job_id": job_id,
    }
    payload.update(extra)
    return payload


def validate_worker_context(
    context: Any,
    *,
    startup_mode: str | None = None,
) -> dict[str, Any]:
    if not isinstance(context, dict):
        raise ValueError("context must be a JSON object")
    unknown = sorted(set(context) - CONTEXT_KEYS)
    if unknown:
        raise ValueError(f"unknown context field(s): {', '.join(unknown)}")

    mode = context.get("mode")
    if mode not in {"live", "simulate", "dry_run"}:
        raise ValueError("context.mode must be 'live', 'simulate', or 'dry_run'")
    for field in ("planning_model_id", "expected_model_id", "planning_profile_id"):
        if field in context and (
            not isinstance(context[field], str) or not context[field].strip()
        ):
            raise ValueError(f"context.{field} must be a non-empty string")

    planning_model_id = context.get("planning_model_id")
    expected_model_id = context.get("expected_model_id")
    planning_profile_id = context.get("planning_profile_id")
    if mode == "live":
        if planning_model_id is not None or planning_profile_id is not None:
            raise ValueError("live context forbids planning_model_id and planning_profile_id")
    elif mode == "simulate":
        if planning_model_id is None:
            raise ValueError("simulate context requires planning_model_id")
        if expected_model_id is not None or planning_profile_id is not None:
            raise ValueError("simulate context forbids expected_model_id and planning_profile_id")
    else:
        if expected_model_id is not None:
            raise ValueError("dry_run context forbids expected_model_id")
        if (planning_model_id is None) == (planning_profile_id is None):
            raise ValueError(
                "dry_run context requires exactly one of planning_model_id or planning_profile_id"
            )
        if planning_profile_id is not None and planning_profile_id != "generic-scpi":
            raise ValueError("context.planning_profile_id must be 'generic-scpi'")

    if startup_mode is not None:
        compatible_modes = {
            "live": {"live", "dry_run"},
            "simulate": {"simulate", "dry_run"},
        }
        if mode not in compatible_modes.get(startup_mode, set()):
            raise ValueError(
                f"{startup_mode} Worker does not accept context.mode {mode!r}"
            )
    return deepcopy(context)


def validate_worker_argument_context_fields(arguments: dict[str, Any]) -> None:
    invalid = sorted(FORBIDDEN_CONTEXT_ARGUMENTS & set(arguments))
    if invalid:
        raise ValueError(
            "mode/model context fields are not accepted in arguments: "
            f"{', '.join(invalid)}"
        )


def _command_parameters(arguments: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in arguments.items() if key not in RUNTIME_ARGUMENT_KEYS}


def _validate_command_body(body: Any, state: "WorkerState") -> tuple[int, dict[str, Any]]:
    from powers_tool_cli.worker_config import _serial_options_from_settings

    if not isinstance(body, dict):
        return 400, _command_response(
            "error",
            None,
            None,
            error={"code": "invalid_request", "message": "POST /command body must be a JSON object"},
        )
    schema_version = body.get("schema_version")
    if type(schema_version) is not int or schema_version != WORKER_SCHEMA_VERSION:
        return 400, _command_response(
            "error",
            body.get("command") if isinstance(body.get("command"), str) else None,
            body.get("job_id") if isinstance(body.get("job_id"), str) else None,
            error={
                "code": "unsupported_schema_version",
                "message": "POST /command requires integer schema_version=2",
            },
        )
    unknown = sorted(set(body) - REQUEST_KEYS)
    command = body.get("command")
    job_id = body.get("job_id")
    if unknown:
        return 400, _command_response(
            "error",
            command if isinstance(command, str) else None,
            job_id if isinstance(job_id, str) else None,
            error={"code": "unknown_field", "message": f"Unknown top-level field(s): {', '.join(unknown)}"},
        )
    if not isinstance(command, str) or not command:
        return 400, _command_response(
            "error",
            command if isinstance(command, str) else None,
            job_id if isinstance(job_id, str) else None,
            error={"code": "missing_command", "message": "POST /command requires a non-empty string command"},
        )
    if command not in ALLOWED_COMMANDS:
        return 400, _command_response(
            "error",
            command,
            job_id if isinstance(job_id, str) else None,
            error={"code": "invalid_command", "message": f"Command {command!r} is not allowed. Supported: {sorted(ALLOWED_COMMANDS)}"},
        )
    arguments = body.get("arguments", {})
    if not isinstance(arguments, dict):
        return 400, _command_response(
            "error",
            command,
            job_id if isinstance(job_id, str) else None,
            error={"code": "invalid_arguments", "message": "arguments must be a JSON object"},
        )
    try:
        validate_worker_argument_context_fields(arguments)
    except ValueError as exc:
        return 400, _command_response(
            "error",
            command,
            job_id if isinstance(job_id, str) else None,
            error={"code": "argument_error", "message": str(exc)},
        )
    attempted_runtime_modes = sorted(_FORBIDDEN_VALIDATION_MODE_ARGUMENTS & set(arguments))
    if attempted_runtime_modes:
        return 400, _command_response(
            "error",
            command,
            job_id if isinstance(job_id, str) else None,
            error={
                "code": "argument_error",
                "message": "validation support policy mode is not available to Worker requests: "
                f"{', '.join(attempted_runtime_modes)}",
            },
        )
    if job_id is not None and not isinstance(job_id, str):
        return 400, _command_response(
            "error",
            command,
            None,
            error={"code": "invalid_job_id", "message": "job_id must be a string when provided"},
        )
    if "confirm_output" in arguments and not isinstance(arguments["confirm_output"], bool):
        return 400, _command_response("error", command, job_id, error={"code": "argument_error", "message": "arguments.confirm_output must be boolean"})
    try:
        context = validate_worker_context(
            body.get("context"),
            startup_mode=state.config["mode"],
        )
    except ValueError as exc:
        return 400, _command_response(
            "error",
            command,
            job_id,
            error={"code": "argument_error", "message": str(exc)},
        )
    settings = state.config.get("settings", {})
    try:
        validation_runtime = RuntimeOptions(
            resource=settings.get("resource"),
            resource_alias=settings.get("resource_alias"),
            safety_config=settings.get("safety_config"),
            simulate=context["mode"] == "simulate",
            dry_run=context["mode"] == "dry_run",
            planning_model_id=context.get("planning_model_id"),
            expected_model_id=context.get("expected_model_id"),
            planning_profile_id=context.get("planning_profile_id"),
            backend=settings.get("backend"),
            timeout_ms=settings.get("timeout_ms", 5000),
            confirm=arguments.get("confirm_output", False),
            serial_options=_serial_options_from_settings(settings),
            serial_remote=bool(settings.get("serial_remote", False)),
            serial_local_on_close=bool(settings.get("serial_local_on_close", False)),
        )
    except CoreValidationError as exc:
        return 400, _command_response(
            "error",
            command,
            job_id,
            error={"code": "argument_error", "message": str(exc)},
        )
    try:
        request_type = (
            SequenceRequest
            if command == "sequence"
            else TriggerRequest
            if command.startswith("trigger-")
            else OperationRequest
        )
        validation_request = request_type(
            command=command,
            runtime=validation_runtime,
            parameters=_command_parameters(arguments),
        )
        admitted_request = validate_request_admission(validation_request)
    except (CoreValidationError, OSError, ValueError) as exc:
        return 400, _command_response("error", command, job_id, error={"code": "argument_error", "message": str(exc)})
    normalized_arguments = {
        key: value for key, value in arguments.items() if key in RUNTIME_ARGUMENT_KEYS
    }
    normalized_arguments.update(admitted_request.parameters)
    confirm_output = normalized_arguments.get("confirm_output", False)
    if command in OUTPUT_AFFECTING_COMMANDS and context["mode"] == "live":
        if not state.config.get("settings", {}).get("allow_output_writes", False):
            return 409, _command_response("rejected", command, job_id, reason="output_changes_not_allowed", error={"code": "output_changes_not_allowed", "message": "live output-affecting commands require settings.allow_output_writes=true"})
        if not confirm_output:
            return 409, _command_response("rejected", command, job_id, reason="output_confirmation_required", error={"code": "output_confirmation_required", "message": "live output-affecting commands require arguments.confirm_output=true"})
    return 202, {
        "command": command,
        "arguments": normalized_arguments,
        "context": context,
        "_admitted_request": admitted_request,
        **({"job_id": job_id} if job_id is not None else {}),
    }
