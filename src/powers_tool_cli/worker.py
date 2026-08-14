"""Powers Tool worker daemon entry point and composition root."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import threading

from powers_tool_cli.worker_config import (
    _optional_int,
    _optional_str,
    _serial_options_from_settings,
    _validate_event_sink,
    _validate_worker_config,
    load_worker_config,
)
from powers_tool_cli.worker_execution import (
    _run_job_impl,
    get_opener,
    job_runner,
    record_cleanup_result,
    record_no_session_stop_cleanup,
)
from powers_tool_cli.worker_http import (
    WorkerHTTPHandler,
    WorkerHTTPServer,
    request_worker_shutdown,
)
from powers_tool_cli.worker_io import (
    _write_json_artifact_atomic,
    emit_event,
)
from powers_tool_cli.worker_protocol import (
    ALLOWED_COMMANDS,
    CONTEXT_KEYS,
    FORBIDDEN_CONTEXT_ARGUMENTS,
    OUTPUT_AFFECTING_COMMANDS,
    OUTPUT_COMMANDS,
    PROTECTION_COMMANDS,
    READ_ONLY_COMMANDS,
    REQUEST_KEYS,
    RUNTIME_ARGUMENT_KEYS,
    TRIGGER_COMMANDS,
    WORKER_SCHEMA_VERSION,
    _FORBIDDEN_VALIDATION_MODE_ARGUMENTS,
    _FORBIDDEN_VALIDATION_MODE_SETTINGS,
    _IDENTITY_SETTING_FIELDS,
    _LEGACY_IDENTITY_ARGUMENTS,
    _command_parameters,
    _command_response,
    _validate_command_body,
    validate_worker_argument_context_fields,
    validate_worker_context,
)
from powers_tool_cli.worker_state import WorkerState

__all__ = [
    "ALLOWED_COMMANDS",
    "CONTEXT_KEYS",
    "FORBIDDEN_CONTEXT_ARGUMENTS",
    "OUTPUT_AFFECTING_COMMANDS",
    "OUTPUT_COMMANDS",
    "PROTECTION_COMMANDS",
    "READ_ONLY_COMMANDS",
    "REQUEST_KEYS",
    "RUNTIME_ARGUMENT_KEYS",
    "TRIGGER_COMMANDS",
    "WORKER_SCHEMA_VERSION",
    "WorkerHTTPHandler",
    "WorkerHTTPServer",
    "WorkerState",
    "_FORBIDDEN_VALIDATION_MODE_ARGUMENTS",
    "_FORBIDDEN_VALIDATION_MODE_SETTINGS",
    "_IDENTITY_SETTING_FIELDS",
    "_LEGACY_IDENTITY_ARGUMENTS",
    "_command_parameters",
    "_command_response",
    "_optional_int",
    "_optional_str",
    "_run_job_impl",
    "_serial_options_from_settings",
    "_validate_command_body",
    "_validate_event_sink",
    "_validate_worker_config",
    "_write_json_artifact_atomic",
    "emit_event",
    "get_opener",
    "job_runner",
    "load_worker_config",
    "record_cleanup_result",
    "record_no_session_stop_cleanup",
    "request_worker_shutdown",
    "run_worker",
    "validate_worker_argument_context_fields",
    "validate_worker_context",
]


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

    emit_event(
        config,
        "ready",
        {
            "run_id": state.run_id,
            "service": "powers-tool",
            "host": "127.0.0.1",
            "port": actual_port,
            "command_url": f"http://127.0.0.1:{actual_port}/command",
            "stop_url": f"http://127.0.0.1:{actual_port}/stop",
            "status_url": f"http://127.0.0.1:{actual_port}/status",
            "artifacts_dir": str(art_dir.resolve()),
            "allowed_commands": sorted(list(ALLOWED_COMMANDS)),
        },
    )

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
