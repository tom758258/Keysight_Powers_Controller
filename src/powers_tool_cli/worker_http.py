"""HTTP server and endpoint orchestration for Powers Tool worker."""

from __future__ import annotations

from copy import deepcopy
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from typing import Any
import uuid

from powers_tool_cli.worker_io import emit_event
from powers_tool_cli.worker_protocol import (
    WORKER_SCHEMA_VERSION,
    _command_response,
    _validate_command_body,
)
from powers_tool_cli.worker_state import WorkerState


class WorkerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    state: WorkerState


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
                now = (
                    datetime.datetime.now(datetime.timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
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
            self._send_json(
                404,
                {
                    "ok": False,
                    "error": {"code": "not_found", "message": "Endpoint not found"},
                },
            )

    def do_POST(self) -> None:
        state = self.state
        content_length = int(self.headers.get("Content-Length", 0))
        body_data: dict[str, Any] = {}
        if content_length > 0:
            try:
                body_data = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except Exception as exc:
                if self.path == "/command":
                    self._send_json(
                        400,
                        _command_response(
                            "error",
                            None,
                            None,
                            error={
                                "code": "invalid_json",
                                "message": f"Invalid JSON body: {exc}",
                            },
                        ),
                    )
                else:
                    self._send_json(
                        400,
                        {
                            "ok": False,
                            "error": {
                                "code": "invalid_json",
                                "message": f"Invalid JSON body: {exc}",
                            },
                        },
                    )
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
                self._send_json(
                    400,
                    {
                        "schema_version": WORKER_SCHEMA_VERSION,
                        "ok": False,
                        "error": {
                            "code": "invalid_cancel_request",
                            "message": "cancel requires schema_version 2 and a non-empty worker_job_id",
                        },
                    },
                )
                return
            reason = body_data.get("reason", "user cancellation")
            if not isinstance(reason, str):
                self._send_json(
                    400,
                    {
                        "schema_version": WORKER_SCHEMA_VERSION,
                        "ok": False,
                        "error": {
                            "code": "invalid_cancel_request",
                            "message": "cancel reason must be a string",
                        },
                    },
                )
                return
            with state.lock:
                active = state.active_job
                if (
                    state.status != "busy"
                    or active is None
                    or active.get("worker_job_id") != worker_job_id
                    or active.get("command")
                    not in {"ramp", "ramp-list", "sequence", "log"}
                ):
                    self._send_json(
                        409,
                        {
                            "schema_version": WORKER_SCHEMA_VERSION,
                            "ok": False,
                            "error": {
                                "code": "job_not_active",
                                "message": "worker_job_id does not identify an active cancellable workflow",
                            },
                        },
                    )
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
                emit_event(
                    state.config,
                    "status",
                    {
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
                    },
                )
            self._send_json(
                202,
                {
                    "schema_version": WORKER_SCHEMA_VERSION,
                    "ok": True,
                    "status": "stopping",
                    "worker_job_id": worker_job_id,
                },
            )
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
                    self._send_json(
                        409,
                        _command_response(
                            "rejected",
                            cmd,
                            client_job_id,
                            reason="busy",
                            error={
                                "code": "busy",
                                "message": "Worker is currently busy processing a job",
                            },
                            active_job=state.active_job,
                        ),
                    )
                    return

                # Save request artifact immediately (strictly block if fails)
                worker_job_id = f"job_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
                job_dir = (
                    Path(state.config["artifacts_dir"]) / "jobs" / worker_job_id
                )
                try:
                    job_dir.mkdir(parents=True, exist_ok=True)
                    artifact_request = {
                        "schema_version": WORKER_SCHEMA_VERSION,
                        "command": cmd,
                        "arguments": arguments,
                        "context": context,
                    }
                    (job_dir / "request.json").write_text(
                        json.dumps(artifact_request, indent=2, sort_keys=True),
                        encoding="utf-8",
                    )
                except Exception as exc:
                    self._send_json(
                        500,
                        _command_response(
                            "error",
                            cmd,
                            client_job_id,
                            error={
                                "code": "artifact_error",
                                "message": f"Could not create job directory or request artifact: {exc}",
                            },
                        ),
                    )
                    return

                # Transition to busy
                state.status = "busy"
                state.job_cancel_event.clear()
                state.pending_terminal_event = None
                artifact_path = str(job_dir.resolve())
                now = (
                    datetime.datetime.now(datetime.timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
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

            emit_event(
                state.config,
                "job_accepted",
                {
                    "job_id": client_job_id,
                    "worker_job_id": worker_job_id,
                    "command": cmd,
                    "run_id": state.run_id,
                },
            )
            self._send_json(
                202,
                _command_response(
                    "accepted",
                    cmd,
                    client_job_id,
                    worker_job_id=worker_job_id,
                    artifact_path=str(job_dir.resolve()),
                ),
            )
        else:
            self._send_json(
                404,
                {
                    "ok": False,
                    "error": {"code": "not_found", "message": "Endpoint not found"},
                },
            )


def request_worker_shutdown(server: WorkerHTTPServer, state: WorkerState) -> None:
    """Helper to cleanly stop the server loop from any thread without deadlocking."""
    with state.lock:
        if state.status != "stopping":
            state.status = "stopping"
            emit_event(state.config, "worker_stopping")
    threading.Thread(target=server.shutdown, daemon=True).start()
