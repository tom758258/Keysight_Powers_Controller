"""Powers Tool worker daemon implementation."""

from __future__ import annotations

import argparse
import csv
from copy import deepcopy
import datetime
import json
import sys
import os
import time
import uuid
import threading
from pathlib import Path
from typing import Any, Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from powers_tool_core.connection import SerialOptions, normalize_serial_termination, open_resource
from powers_tool_core.core import (
    RuntimeOptions,
    OperationRequest,
    TriggerRequest,
    SequenceRequest,
    CoreValidationError,
    UnsupportedModelError,
    UnsupportedChannelError,
    ConfirmationRequiredError,
    CommandCancelled,
    CoreIoError,
    CoreExecutionError,
    StopCleanupError,
)
from powers_tool_core.command_runner import run_core_command, validate_request_admission
from powers_tool_core.sequence import load_sequence_document, sequence_plan
from powers_tool_core.stop_cleanup import StopCleanupResult
from powers_tool_core.support_policy import LiveSupportPolicyError
from powers_tool_core.telemetry import TELEMETRY_ROW_FIELDS

READ_ONLY_COMMANDS = {
    "identify",
    "read-status",
    "readback",
    "measure",
    "measure-all",
    "output-state",
    "protection-status",
    "error",
    "snapshot",
    "log",
}
OUTPUT_COMMANDS = {
    "set",
    "apply",
    "output-on",
    "output-off",
    "safe-off",
    "cycle-output",
    "ramp",
    "ramp-list",
    "smoke-output",
}
PROTECTION_COMMANDS = {"protection-set", "clear-protection", "restore-from-snapshot", "sequence"}
TRIGGER_COMMANDS = {
    "trigger-pulse",
    "trigger-status",
    "trigger-step",
    "trigger-list",
    "trigger-fire",
    "trigger-abort",
}
ALLOWED_COMMANDS = READ_ONLY_COMMANDS | OUTPUT_COMMANDS | PROTECTION_COMMANDS | TRIGGER_COMMANDS
OUTPUT_AFFECTING_COMMANDS = OUTPUT_COMMANDS | {"protection-set", "clear-protection", "restore-from-snapshot", "sequence"}
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

_event_lock = threading.Lock()
_sequence_counter = 1


class WorkerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def emit_event(config: dict[str, Any], event_name: str, extra: dict[str, Any] | None = None) -> None:
    """Thread-safe event logger writing both to stdout and to events_jsonl file."""
    global _sequence_counter
    with _event_lock:
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        payload = {
            "schema_version": WORKER_SCHEMA_VERSION,
            "event": event_name,
            "worker_id": config["id"],
            "type": "power",
            "timestamp_utc": timestamp,
            "sequence": _sequence_counter,
        }
        if extra:
            payload.update(extra)
        _sequence_counter += 1

        encoded = json.dumps(payload, sort_keys=True)
        print(encoded, flush=True)

        events_file = config.get("events_jsonl")
        if events_file:
            try:
                p = Path(events_file)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "a", encoding="utf-8") as f:
                    f.write(encoded + "\n")
            except Exception as exc:
                print(f"worker event log write failed: {exc}", file=sys.stderr, flush=True)


def _write_json_artifact_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Publish a JSON artifact only after its full contents are durable."""
    encoded = json.dumps(payload, indent=2, sort_keys=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


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


def _validate_command_body(body: Any, state: "WorkerState") -> tuple[int, dict[str, Any]]:
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


class WorkerState:
    """Thread-safe worker daemon state tracker."""
    def __init__(self, config: dict[str, Any], port: int) -> None:
        self.config = config
        self.port = port
        self.status = "ready"  # ready|busy|stopping|error
        self.active_job: dict[str, Any] | None = None
        self.last_job: dict[str, Any] | None = None
        self.fatal_error: dict[str, Any] | None = None
        self.lock = threading.Condition()
        self.shutdown_event = threading.Event()
        self.stop_event = threading.Event()
        self.job_cancel_event = threading.Event()
        self.next_job: dict[str, Any] | None = None
        self.pending_terminal_event: tuple[str, dict[str, Any]] | None = None
        self.shutdown_flag = False
        self.server: WorkerHTTPServer | None = None
        self.run_id = str(uuid.uuid4())
        self.cleanup_results: list[dict[str, str]] = []
        self.cleanup_failed = False

        if config["mode"] == "simulate":
            from powers_tool_core.testing.simulator import SimulatedResourceManager
            self.sim_mgr = SimulatedResourceManager()
        else:
            self.sim_mgr = None


class WorkerHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for local control API endpoints."""
    protocol_version = "HTTP/1.1"
    server: WorkerHTTPServer

    @property
    def state(self) -> WorkerState:
        return self.server.state

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default server log to keep stdout clean for JSONL events
        pass

    def _send_json(self, status_code: int, data: dict[str, Any]) -> None:
        try:
            body = json.dumps(data, sort_keys=True).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
        except Exception:
            pass

    def do_GET(self) -> None:
        state = self.state
        if self.path == "/status":
            with state.lock:
                now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
                res = {
                    "schema_version": WORKER_SCHEMA_VERSION,
                    "service": "powers-tool",
                    "run_id": state.run_id,
                    "status": state.status,
                    "command_url": f"http://127.0.0.1:{state.port}/command",
                    "stop_url": f"http://127.0.0.1:{state.port}/stop",
                    "status_url": f"http://127.0.0.1:{state.port}/status",
                    "queue_size": 1 if state.next_job is not None else 0,
                    "active_job": state.active_job,
                    "last_job": state.last_job,
                    "fatal_error": state.fatal_error,
                    "timestamp_utc": now,
                }
            self._send_json(200, res)
        else:
            self._send_json(404, {"ok": False, "error": {"code": "not_found", "message": "Endpoint not found"}})

    def do_POST(self) -> None:
        state = self.state
        content_length = int(self.headers.get("Content-Length", 0))
        body_data: dict[str, Any] = {}
        if content_length > 0:
            try:
                body_data = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except Exception as exc:
                if self.path == "/command":
                    self._send_json(400, _command_response(
                        "error",
                        None,
                        None,
                        error={"code": "invalid_json", "message": f"Invalid JSON body: {exc}"},
                    ))
                else:
                    self._send_json(400, {"ok": False, "error": {"code": "invalid_json", "message": f"Invalid JSON body: {exc}"}})
                return

        if self.path == "/stop":
            # The handler only publishes cooperative stop state and wakes the runner.
            reason = body_data.get("reason", "manual stop")
            state.stop_event.set()
            emit_event(state.config, "stop_requested", {"reason": reason})
            with state.lock:
                state.shutdown_flag = True
                state.lock.notify_all()
            self._send_json(200, {"ok": True, "message": "Stop requested"})
            return

        if self.path == "/cancel":
            allowed_fields = {"schema_version", "worker_job_id", "reason"}
            schema_version = body_data.get("schema_version")
            worker_job_id = body_data.get("worker_job_id")
            if (
                set(body_data) - allowed_fields
                or type(schema_version) is not int
                or schema_version != WORKER_SCHEMA_VERSION
                or not isinstance(worker_job_id, str)
                or not worker_job_id
            ):
                self._send_json(400, {
                    "schema_version": WORKER_SCHEMA_VERSION,
                    "ok": False,
                    "error": {
                        "code": "invalid_cancel_request",
                        "message": "cancel requires schema_version 2 and a non-empty worker_job_id",
                    },
                })
                return
            reason = body_data.get("reason", "user cancellation")
            if not isinstance(reason, str):
                self._send_json(400, {
                    "schema_version": WORKER_SCHEMA_VERSION,
                    "ok": False,
                    "error": {"code": "invalid_cancel_request", "message": "cancel reason must be a string"},
                })
                return
            with state.lock:
                active = state.active_job
                if (
                    state.status != "busy"
                    or active is None
                    or active.get("worker_job_id") != worker_job_id
                    or active.get("command") not in {"ramp", "ramp-list", "sequence", "log"}
                ):
                    self._send_json(409, {
                        "schema_version": WORKER_SCHEMA_VERSION,
                        "ok": False,
                        "error": {
                            "code": "job_not_active",
                            "message": "worker_job_id does not identify an active cancellable workflow",
                        },
                    })
                    return
                already_requested = state.job_cancel_event.is_set()
                state.job_cancel_event.set()
                state.active_job = {
                    **active,
                    "status": "stopping",
                    "cancellation_reason": reason,
                }
                state.lock.notify_all()
            if not already_requested:
                emit_event(state.config, "status", {
                    "status": "stopping",
                    "job_id": active.get("job_id"),
                    "worker_job_id": worker_job_id,
                    "command": active.get("command"),
                    "reason": reason,
                    "message": (
                        "Waiting for telemetry sampling to stop"
                        if active.get("command") == "log"
                        else "Waiting for safe-off and cleanup"
                    ),
                })
            self._send_json(202, {
                "schema_version": WORKER_SCHEMA_VERSION,
                "ok": True,
                "status": "stopping",
                "worker_job_id": worker_job_id,
            })
            return

        if self.path == "/command":
            validation = _validate_command_body(body_data, state)
            if validation[0] != 202:
                self._send_json(validation[0], validation[1])
                return
            body_data = validation[1]
            cmd = body_data["command"]
            arguments = body_data["arguments"]
            context = body_data["context"]
            admitted_request = body_data.pop("_admitted_request")
            client_job_id = body_data.get("job_id")

            with state.lock:
                if state.status != "ready":
                    self._send_json(409, _command_response(
                        "rejected",
                        cmd,
                        client_job_id,
                        reason="busy",
                        error={"code": "busy", "message": "Worker is currently busy processing a job"},
                        active_job=state.active_job,
                    ))
                    return

                # Save request artifact immediately (strictly block if fails)
                worker_job_id = f"job_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
                job_dir = Path(state.config["artifacts_dir"]) / "jobs" / worker_job_id
                try:
                    job_dir.mkdir(parents=True, exist_ok=True)
                    artifact_request = {
                        "schema_version": WORKER_SCHEMA_VERSION,
                        "command": cmd,
                        "arguments": arguments,
                        "context": context,
                    }
                    (job_dir / "request.json").write_text(json.dumps(artifact_request, indent=2, sort_keys=True), encoding="utf-8")
                except Exception as exc:
                    self._send_json(500, _command_response(
                        "error",
                        cmd,
                        client_job_id,
                        error={
                            "code": "artifact_error",
                            "message": f"Could not create job directory or request artifact: {exc}",
                        },
                    ))
                    return

                # Transition to busy
                state.status = "busy"
                state.job_cancel_event.clear()
                state.pending_terminal_event = None
                artifact_path = str(job_dir.resolve())
                now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
                state.active_job = {
                    "job_id": client_job_id,
                    "worker_job_id": worker_job_id,
                    "command": cmd,
                    "status": "queued",
                    "artifact_path": artifact_path,
                    "accepted_at": now,
                }

                state.next_job = {
                    "job_id": client_job_id,
                    "worker_job_id": worker_job_id,
                    "command": cmd,
                    "arguments": arguments,
                    "context": context,
                    "request": deepcopy(admitted_request),
                    "dir": job_dir,
                }
                state.lock.notify_all()

            emit_event(state.config, "job_accepted", {"job_id": client_job_id, "worker_job_id": worker_job_id, "command": cmd, "run_id": state.run_id})
            self._send_json(202, _command_response(
                "accepted",
                cmd,
                client_job_id,
                worker_job_id=worker_job_id,
                artifact_path=str(job_dir.resolve()),
            ))
        else:
            self._send_json(404, {"ok": False, "error": {"code": "not_found", "message": "Endpoint not found"}})


def request_worker_shutdown(server: WorkerHTTPServer, state: WorkerState) -> None:
    """Helper to cleanly stop the server loop from any thread without deadlocking."""
    with state.lock:
        if state.status != "stopping":
            state.status = "stopping"
            emit_event(state.config, "worker_stopping")
    threading.Thread(target=server.shutdown, daemon=True).start()


def record_cleanup_result(state: WorkerState, result: StopCleanupResult) -> None:
    payload = result.to_dict()
    with state.lock:
        state.cleanup_results.append(payload)
        if result.status == "failed":
            state.cleanup_failed = True
            state.status = "error"
    emit_event(state.config, "power_cleanup", {"run_id": state.run_id, "cleanup": payload})


def record_no_session_stop_cleanup(state: WorkerState) -> None:
    if state.cleanup_results:
        return
    record_cleanup_result(
        state,
        StopCleanupResult("release_to_local", "not_applicable", "no open VISA session"),
    )
    record_cleanup_result(
        state,
        StopCleanupResult("close_session", "not_applicable", "no open VISA session"),
    )
    record_cleanup_result(
        state,
        StopCleanupResult("cleanup_release_to_local", "succeeded", "post-close cleanup recorded release_to_local=not_applicable"),
    )


def get_opener(state: WorkerState) -> Callable[..., Any]:
    """Return a connection opener that correctly utilizes simulated or live PyVISA resources."""
    if state.sim_mgr is not None:
        def opener(
            resource: str,
            resource_manager: Any = None,
            *,
            backend: str | None = None,
            timeout_ms: int = 5000,
            serial_options: SerialOptions | None = None,
            serial_remote: bool = False,
            serial_local_on_close: bool = False,
        ) -> Any:
            return open_resource(
                resource,
                state.sim_mgr,
                backend=backend,
                timeout_ms=timeout_ms,
                serial_options=serial_options,
                serial_remote=serial_remote,
                serial_local_on_close=serial_local_on_close,
            )
        return opener
    else:
        def opener(
            resource: str,
            resource_manager: Any = None,
            *,
            backend: str | None = None,
            timeout_ms: int = 5000,
            serial_options: SerialOptions | None = None,
            serial_remote: bool = False,
            serial_local_on_close: bool = False,
        ) -> Any:
            return open_resource(
                resource,
                backend=backend,
                timeout_ms=timeout_ms,
                serial_options=serial_options,
                serial_remote=serial_remote,
                serial_local_on_close=serial_local_on_close,
            )
        return opener


def _command_parameters(arguments: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in arguments.items() if key not in RUNTIME_ARGUMENT_KEYS}


def job_runner(state: WorkerState) -> None:
    """Asynchronous job processing loop running in a dedicated background thread."""
    while not state.shutdown_event.is_set():
        job = None
        with state.lock:
            while state.next_job is None and not state.shutdown_event.is_set() and not state.shutdown_flag:
                state.lock.wait(timeout=0.05)
            if state.shutdown_event.is_set():
                break
            if state.shutdown_flag and state.next_job is None:
                record_no_session_stop_cleanup(state)
                request_worker_shutdown(state.server, state)
                break
            job = state.next_job
            state.next_job = None

        if job:
            _run_job_impl(state, job)

            should_shutdown = False
            terminal_event: tuple[str, dict[str, Any]] | None = None
            with state.lock:
                state.active_job = None
                if state.cleanup_failed:
                    state.status = "error"
                elif state.status == "busy":
                    state.status = "ready"
                state.job_cancel_event.clear()
                terminal_event = state.pending_terminal_event
                state.pending_terminal_event = None
                should_shutdown = state.shutdown_flag

            if terminal_event is not None:
                emit_event(state.config, terminal_event[0], terminal_event[1])
            if should_shutdown:
                record_no_session_stop_cleanup(state)
                request_worker_shutdown(state.server, state)


def _run_job_impl(state: WorkerState, job: dict[str, Any]) -> None:
    config = state.config
    settings = config.get("settings", {})
    cmd = job["command"]
    client_job_id = job.get("job_id")
    worker_job_id = job.get("worker_job_id", client_job_id)
    arguments = job.get("arguments", {})
    context = validate_worker_context(
        job.get("context"),
        startup_mode=config["mode"],
    )
    job_dir: Path = job["dir"]

    with state.lock:
        if state.active_job is not None and state.active_job.get("worker_job_id") == worker_job_id:
            state.active_job = {
                **state.active_job,
                "status": "stopping" if state.job_cancel_event.is_set() else "running",
                "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            }
    emit_event(config, "job_started", {"job_id": client_job_id, "worker_job_id": worker_job_id, "command": cmd, "run_id": state.run_id})

    request = job.get("request")
    if not isinstance(request, (OperationRequest, TriggerRequest, SequenceRequest)):
        # Compatibility for in-process callers predating queued admission.
        # HTTP submissions always carry the admitted request above.
        runtime = RuntimeOptions(
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
        request_type = (
            SequenceRequest if cmd == "sequence" else TriggerRequest
            if cmd.startswith("trigger-") else OperationRequest
        )
        request = request_type(cmd, runtime, _command_parameters(arguments))
    # Admission owns canonical parameters and materialized documents.  Copy so
    # no worker-local code can mutate the queued submission.
    request = deepcopy(request)
    params = request.parameters
    runtime = request.runtime
    confirm_req = runtime.confirm

    opener = get_opener(state)
    start_perf = time.perf_counter()
    result_data: dict[str, Any] | None = None
    warnings: list[dict[str, str]] = []
    error_payload: dict[str, Any] | None = None
    ok = True
    exc_obj: Exception | None = None
    final_status = "succeeded"
    cleanup_results: list[dict[str, str]] = []
    telemetry_csv_file: Any = None
    telemetry_jsonl_file: Any = None
    telemetry_writer: csv.DictWriter | None = None
    telemetry_rows_written = 0
    telemetry_channels_seen: list[int] = []

    def report_cleanup(result: StopCleanupResult) -> None:
        payload = result.to_dict()
        cleanup_results.append(payload)
        record_cleanup_result(state, result)
        if result.status == "unsupported":
            warnings.append({"code": "cleanup_unsupported", "message": result.message})

    def report_progress(progress: dict[str, int | float]) -> None:
        with state.lock:
            if (
                state.active_job is not None
                and state.active_job.get("worker_job_id") == worker_job_id
            ):
                state.active_job = {**state.active_job, "progress": dict(progress)}

    def report_sample(row: dict[str, Any]) -> None:
        nonlocal telemetry_rows_written
        if telemetry_writer is None or telemetry_csv_file is None or telemetry_jsonl_file is None:
            raise RuntimeError("worker telemetry artifacts are not open")
        telemetry_writer.writerow(row)
        telemetry_csv_file.flush()
        telemetry_jsonl_file.write(
            json.dumps({"event": "sample", "sample": row}, sort_keys=True) + "\n"
        )
        telemetry_jsonl_file.flush()
        telemetry_rows_written += 1
        channel = int(row["channel"])
        if channel not in telemetry_channels_seen:
            telemetry_channels_seen.append(channel)

    try:
        if cmd == "log":
            telemetry_csv_file = (job_dir / "telemetry.csv").open(
                "w", newline="", encoding="utf-8"
            )
            telemetry_writer = csv.DictWriter(
                telemetry_csv_file, fieldnames=TELEMETRY_ROW_FIELDS
            )
            telemetry_writer.writeheader()
            telemetry_csv_file.flush()
            telemetry_jsonl_file = (job_dir / "telemetry.jsonl").open(
                "w", encoding="utf-8"
            )
        if cmd == "sequence":
            doc = params.get("document")
            if not isinstance(doc, dict):
                raise CoreValidationError("worker sequence request is missing admitted document")

            # Output-affecting double-confirmation check
            if doc is not None:
                plan = sequence_plan(request, doc)
                has_writes = any(
                    step.get("action") in {
                        "set", "apply", "output-on", "output-off", "safe-off", "cycle-output", "ramp", "smoke-output", "trigger-pulse"
                    }
                    for step in plan.get("steps", [])
                )

                if has_writes and context["mode"] == "live":
                    allow_writes = settings.get("allow_output_writes", False)
                    if not allow_writes or not confirm_req:
                        raise ConfirmationRequiredError(
                            "live output-affecting sequence requires both config allow_output_writes=true "
                            "and request confirm=true"
                        )

        result_data = run_core_command(
            request,
            opener=opener,
            stop_requested=lambda: state.stop_event.is_set() or state.job_cancel_event.is_set(),
            cleanup_reporter=report_cleanup,
            progress_reporter=report_progress if cmd == "log" else None,
            sample_reporter=report_sample if cmd == "log" else None,
        )
        if state.job_cancel_event.is_set() and cmd in {"ramp", "ramp-list", "sequence"}:
            if config["mode"] == "simulate" or runtime.dry_run:
                raise CommandCancelled(
                    "workflow cancelled after no-hardware planning completed",
                    data={
                        "status": "cancelled",
                        "cancelled_by_user": True,
                        "original_reason": "user_cancelled",
                        "cleanup": [],
                        "partial_result": result_data,
                    },
                )
            late_result = {
                "operation": "workflow_safe_off",
                "status": "failed",
                "message": "cancellation arrived after the VISA session had closed",
            }
            raise StopCleanupError(
                "workflow cancellation cleanup failed",
                results=(late_result,),
                data={
                    "status": "failed",
                    "original_reason": "user_cancelled",
                    "cleanup": [late_result],
                    "partial_result": result_data,
                },
            )
        if cmd == "sequence":
            if result_data.get("status") == "stopped":
                raise KeyboardInterrupt("sequence wait interrupted")
            if result_data.get("status") == "failed":
                failed_step = result_data.get("failed_step") or {}
                msg = failed_step.get("message", "step failed")
                raise CoreExecutionError(
                    f"sequence step failed: {msg}",
                    trigger=failed_step.get("trigger"),
                    data=result_data,
                )
        if cmd == "ramp-list":
            if result_data.get("status") == "stopped":
                raise KeyboardInterrupt("ramp-list execution interrupted")
            if result_data.get("status") == "failed":
                failed_segment = result_data.get("failed_segment") or {}
                msg = failed_segment.get("message", "segment failed")
                raise CoreExecutionError(
                    f"ramp-list segment {failed_segment.get('index')} failed: {msg}",
                    trigger=failed_segment.get("trigger"),
                    data=result_data,
                )

    except (Exception, KeyboardInterrupt) as exc:
        ok = False
        exc_obj = exc
        err_type = "execution"
        code = "execution_failed"
        retryable = True

        # Mapping core exceptions correctly using isinstance
        if isinstance(exc, CoreValidationError):
            err_type = "validation"
            if isinstance(exc, ConfirmationRequiredError):
                code = "confirmation_required"
            elif isinstance(exc, LiveSupportPolicyError):
                code = "unsupported_live_scope"
            elif isinstance(exc, UnsupportedModelError):
                code = f"unsupported_model_for_{cmd.replace('-', '_')}"
            elif isinstance(exc, UnsupportedChannelError):
                code = "argument_error"
            else:
                code = "argument_error"
            retryable = False
        elif isinstance(exc, CoreIoError):
            err_type = "io"
            code = "io_failed"
            if getattr(exc, "opened", False) is False:
                code = "connection_failed"
            retryable = True
        elif isinstance(exc, StopCleanupError):
            err_type = "io"
            code = "cleanup_failed"
            retryable = True
        elif isinstance(exc, (CommandCancelled, KeyboardInterrupt)) or exc.__class__.__name__ in {"TriggerInterrupted", "SequenceStopped"} or state.stop_event.is_set() or state.job_cancel_event.is_set():
            err_type = "execution"
            code = "cancelled" if state.job_cancel_event.is_set() and cmd in {"ramp", "ramp-list", "sequence", "log"} else "stopped"
            retryable = True

        error_payload = {
            "type": err_type,
            "code": code,
            "message": "Execution was stopped by user request" if isinstance(exc, KeyboardInterrupt) else str(exc),
            "retryable": retryable,
        }
        final_status = "cancelled" if code in {"cancelled", "stopped"} else "failed"
        if isinstance(exc, (CommandCancelled, StopCleanupError, CoreExecutionError)):
            result_data = dict(getattr(exc, "data", {}) or {})
            if isinstance(exc, CoreExecutionError) and exc.trigger is not None:
                result_data.setdefault("trigger", exc.trigger)

    if cmd == "log":
        try:
            if telemetry_jsonl_file is not None:
                summary_data = result_data or {}
                telemetry_jsonl_file.write(
                    json.dumps(
                        {
                            "event": "summary",
                            "samples_written": summary_data.get("samples_written"),
                            "channels": summary_data.get(
                                "channels", telemetry_channels_seen
                            ),
                            "stopped": final_status == "cancelled",
                            "stop_reason": summary_data.get(
                                "stop_reason",
                                "completed" if ok else final_status,
                            ),
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
                telemetry_jsonl_file.flush()
        except Exception as exc:
            ok = False
            final_status = "failed"
            error_payload = {
                "type": "io",
                "code": "artifact_error",
                "message": f"Could not finalize telemetry artifact: {exc}",
                "retryable": False,
            }
        finally:
            for telemetry_file in (telemetry_csv_file, telemetry_jsonl_file):
                if telemetry_file is None:
                    continue
                try:
                    telemetry_file.close()
                except Exception as exc:
                    ok = False
                    final_status = "failed"
                    error_payload = {
                        "type": "io",
                        "code": "artifact_error",
                        "message": f"Could not close telemetry artifact: {exc}",
                        "retryable": False,
                    }

        if result_data is not None:
            result_data = {
                key: result_data.get(key)
                for key in (
                    "samples_written",
                    "samples_requested",
                    "duration_sec",
                    "interval_sec",
                    "channels",
                    "stop_reason",
                )
            }

    duration_ms = round((time.perf_counter() - start_perf) * 1000, 3)

    # Determine hardware_touched
    hardware_touched = False
    if config["mode"] == "live" and not runtime.dry_run:
        if ok:
            hardware_touched = True
        elif cmd == "ramp-list" and result_data is not None:
            hardware_touched = True
        elif cmd == "log" and (telemetry_rows_written > 0 or result_data is not None):
            hardware_touched = True
        elif exc_obj is not None:
            # Touched hardware only if we opened the VISA connection successfully
            if not isinstance(exc_obj, CoreValidationError) and getattr(exc_obj, "opened", False):
                hardware_touched = True

    # Compile CLI JSON contract compliant envelope
    envelope = {
        "schema_version": WORKER_SCHEMA_VERSION,
        "run_id": state.run_id,
        "worker_job_id": worker_job_id,
        "ok": ok,
        "status": final_status,
        "command": {"name": cmd},
        "execution": {
            "mode": config["mode"],
            "dry_run": runtime.dry_run,
            "hardware_touched": hardware_touched,
        },
        "request": {"command": cmd, "arguments": arguments},
        "data": result_data if ok or (cmd == "log" and final_status == "cancelled") else None,
        "warnings": warnings,
        "error": error_payload,
        "metadata": {
            "duration_ms": duration_ms,
            "cleanup": cleanup_results,
        },
    }

    # Write result artifact. If the write fails, do not advertise an artifact path.
    result_path = job_dir / "result.json"
    artifact_path: str | None = str(result_path.resolve())
    artifact_error: dict[str, Any] | None = None
    try:
        _write_json_artifact_atomic(result_path, envelope)
    except Exception as exc:
        ok = False
        artifact_error = {
            "type": "io",
            "code": "artifact_error",
            "message": f"Could not write job result artifact: {exc}",
            "retryable": False,
        }
        error_payload = artifact_error
        envelope["ok"] = False
        envelope["status"] = "failed"
        envelope["error"] = error_payload
        final_status = "failed"
        try:
            _write_json_artifact_atomic(result_path, envelope)
        except Exception:
            artifact_path = None

    # Emit completion events
    artifact_dir = str(job_dir.resolve())
    if ok:
        event_payload = {
            "job_id": client_job_id,
            "worker_job_id": worker_job_id,
            "command": cmd,
            "artifact_available": artifact_path is not None,
        }
        if artifact_path is not None:
            event_payload["artifact_path"] = artifact_dir
        with state.lock:
            state.last_job = {
                "job_id": client_job_id,
                "worker_job_id": worker_job_id,
                "command": cmd,
                "status": "succeeded",
                "artifact_available": artifact_path is not None,
                "artifact_path": artifact_dir,
            }
        with state.lock:
            state.pending_terminal_event = ("job_finished", event_payload)
    else:
        event_payload = {
            "job_id": client_job_id,
            "worker_job_id": worker_job_id,
            "command": cmd,
            "error": error_payload,
            "artifact_available": artifact_path is not None and artifact_error is None,
        }
        if artifact_error is not None:
            event_payload["artifact_error"] = artifact_error
        elif artifact_path is not None:
            event_payload["artifact_path"] = artifact_dir
        with state.lock:
            state.last_job = {
                "job_id": client_job_id,
                "worker_job_id": worker_job_id,
                "command": cmd,
                "status": final_status,
                "error": error_payload,
                "artifact_available": artifact_path is not None and artifact_error is None,
            }
            if artifact_error is not None:
                state.last_job["artifact_error"] = artifact_error
            elif artifact_path is not None:
                state.last_job["artifact_path"] = artifact_dir
        with state.lock:
            state.pending_terminal_event = (
                "job_cancelled" if final_status == "cancelled" else "job_failed",
                event_payload,
            )


def load_worker_config(args: argparse.Namespace) -> dict[str, Any]:
    """Load configuration from config path and apply CLI argument overrides."""
    config: dict[str, Any] = {
        "id": "power_1",
        "type": "power",
        "enabled": True,
        "mode": "simulate",
        "control_host": "127.0.0.1",
        "control_port": 0,
        "artifacts_dir": ".tmp_tests/power_worker/power_1",
        "events_jsonl": None,
        "settings": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "resource_alias": None,
            "backend": None,
            "timeout_ms": 5000,
            "serial_options": {},
            "serial_remote": False,
            "serial_local_on_close": False,
            "safety_config": None,
            "allow_output_writes": False,
        }
    }

    if getattr(args, "config", None):
        cfg_path = Path(args.config)
        if not cfg_path.exists():
            raise FileNotFoundError(f"Config file not found: {args.config}")
        with open(cfg_path, encoding="utf-8") as f:
            file_cfg = json.load(f)

        for k in ["id", "type", "enabled", "mode", "control_host", "control_port", "artifacts_dir", "events_jsonl"]:
            if k in file_cfg:
                config[k] = file_cfg[k]

        if "settings" in file_cfg:
            for k, v in file_cfg["settings"].items():
                config["settings"][k] = v

    if getattr(args, "id", None) is not None:
        config["id"] = args.id
    if getattr(args, "mode", None) is not None:
        config["mode"] = args.mode
    if getattr(args, "control_port", None) is not None:
        config["control_port"] = args.control_port
    if getattr(args, "artifacts_dir", None) is not None:
        config["artifacts_dir"] = args.artifacts_dir
    else:
        if not getattr(args, "config", None):
            config["artifacts_dir"] = f".tmp_tests/power_worker/{config['id']}"

    if getattr(args, "events_jsonl", None) is not None:
        config["events_jsonl"] = args.events_jsonl
    else:
        if not getattr(args, "config", None):
            config["events_jsonl"] = f"{config['artifacts_dir']}/events.jsonl"

    if not config.get("events_jsonl"):
        config["events_jsonl"] = f"{config['artifacts_dir']}/events.jsonl"

    if getattr(args, "resource", None) is not None:
        config["settings"]["resource"] = args.resource
    _validate_worker_config(config)
    return config


def _validate_worker_config(config: dict[str, Any]) -> None:
    if config["type"] != "power":
        raise ValueError(f"Worker type must be 'power', got {config['type']!r}")

    if not isinstance(config.get("enabled"), bool):
        raise ValueError(f"Worker enabled must be a boolean, got {config.get('enabled')!r}")
    if config["enabled"] is False:
        raise ValueError("Worker enabled=false is not runnable")

    if config.get("mode") not in {"simulate", "live"}:
        raise ValueError(f"Worker mode must be 'simulate' or 'live', got {config.get('mode')!r}")

    host = config["control_host"]
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError(f"Control host {host!r} is not allowed. Bind host must be localhost (127.0.0.1) in v1.")

    port = config.get("control_port")
    if not isinstance(port, int) or isinstance(port, bool) or not (0 <= port <= 65535):
        raise ValueError(f"Control port must be an integer from 0 to 65535, got {port!r}")

    settings = config.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("Worker settings must be an object")
    if "default_action" in settings:
        raise ValueError("settings.default_action is not supported; use POST /command")
    attempted_runtime_modes = sorted(_FORBIDDEN_VALIDATION_MODE_SETTINGS & set(settings))
    if attempted_runtime_modes:
        raise ValueError(
            "settings validation support policy mode is not available to Worker: "
            f"{', '.join(attempted_runtime_modes)}"
        )
    identity_settings = sorted(_IDENTITY_SETTING_FIELDS & set(settings))
    if identity_settings:
        raise ValueError(
            "Worker identity selection belongs to each request; settings fields are not allowed: "
            f"{', '.join(identity_settings)}"
        )
    serial_options = settings.get("serial_options")
    if serial_options is not None and not isinstance(serial_options, dict):
        raise ValueError("settings.serial_options must be an object")
    for key in ("serial_remote", "serial_local_on_close"):
        if key in settings and not isinstance(settings[key], bool):
            raise ValueError(f"settings.{key} must be a boolean")


def _serial_options_from_settings(settings: dict[str, Any]) -> SerialOptions | None:
    serial = settings.get("serial_options")
    if not isinstance(serial, dict):
        return None
    options = SerialOptions(
        baud_rate=_optional_int(serial.get("baud_rate")),
        data_bits=_optional_int(serial.get("data_bits")),
        parity=_optional_str(serial.get("parity")),
        stop_bits=serial.get("stop_bits"),
        flow_control=_optional_str(serial.get("flow_control")),
        read_termination=normalize_serial_termination(serial.get("read_termination")),
        write_termination=normalize_serial_termination(serial.get("write_termination")),
    )
    return options if options.has_explicit_values() else None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text != "" else None


def _validate_event_sink(config: dict[str, Any]) -> None:
    events_file = config.get("events_jsonl")
    if not events_file:
        return
    p = Path(events_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8"):
        pass


def run_worker(args: argparse.Namespace) -> int:
    """Entry point for worker subcommand execution."""
    try:
        config = load_worker_config(args)
        _validate_event_sink(config)
    except Exception as exc:
        print(f"Configuration validation failed: {exc}", file=sys.stderr)
        return 1

    art_dir = Path(config["artifacts_dir"])
    art_dir.mkdir(parents=True, exist_ok=True)

    host = config["control_host"]
    req_port = config["control_port"]

    try:
        server = WorkerHTTPServer((host, req_port), WorkerHTTPHandler)
    except Exception as exc:
        print(f"Failed to bind HTTP server on {host}:{req_port}: {exc}", file=sys.stderr)
        return 1

    actual_port = server.server_address[1]
    state = WorkerState(config, actual_port)

    # Cross reference references
    server.state = state
    state.server = server

    runner_thread = threading.Thread(target=job_runner, args=(state,), daemon=True)
    runner_thread.start()

    emit_event(config, "ready", {
        "run_id": state.run_id,
        "service": "powers-tool",
        "host": "127.0.0.1",
        "port": actual_port,
        "command_url": f"http://127.0.0.1:{actual_port}/command",
        "stop_url": f"http://127.0.0.1:{actual_port}/stop",
        "status_url": f"http://127.0.0.1:{actual_port}/status",
        "artifacts_dir": str(art_dir.resolve()),
        "allowed_commands": sorted(list(ALLOWED_COMMANDS)),
    })

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.stop_event.set()
        with state.lock:
            state.shutdown_flag = True
            state.lock.notify_all()
        request_worker_shutdown(server, state)
        state.shutdown_event.set()
        with state.lock:
            state.lock.notify_all()
        runner_thread.join()
        ok = state.status != "error" and not state.cleanup_failed
        emit_event(
            config,
            "summary",
            {
                "run_id": state.run_id,
                "ok": ok,
                "last_job": state.last_job,
                "cleanup": state.cleanup_results,
            },
        )

    return 0 if ok else 3
