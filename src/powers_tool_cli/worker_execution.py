"""Job runner, execution, and error mapping for Powers Tool worker."""

from __future__ import annotations

from copy import deepcopy
import csv
import datetime
import json
from pathlib import Path
import time
from typing import Any, Callable

from powers_tool_core.command_runner import run_core_command
from powers_tool_core.connection import SerialOptions, open_resource
from powers_tool_core.core import (
    CommandCancelled,
    ConfirmationRequiredError,
    CoreExecutionError,
    CoreIoError,
    CoreValidationError,
    OperationRequest,
    RuntimeOptions,
    SequenceRequest,
    StopCleanupError,
    TriggerRequest,
    UnsupportedChannelError,
    UnsupportedModelError,
)
from powers_tool_core.sequence import sequence_plan
from powers_tool_core.stop_cleanup import StopCleanupResult
from powers_tool_core.support_policy import LiveSupportPolicyError
from powers_tool_core.telemetry import TELEMETRY_ROW_FIELDS
from powers_tool_cli.worker_config import _serial_options_from_settings
from powers_tool_cli.worker_http import request_worker_shutdown
from powers_tool_cli.worker_io import _write_json_artifact_atomic, emit_event
from powers_tool_cli.worker_protocol import (
    WORKER_SCHEMA_VERSION,
    _command_parameters,
    validate_worker_context,
)
from powers_tool_cli.worker_state import WorkerState


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
        StopCleanupResult(
            "cleanup_release_to_local",
            "succeeded",
            "post-close cleanup recorded release_to_local=not_applicable",
        ),
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


def job_runner(state: WorkerState) -> None:
    """Asynchronous job processing loop running in a dedicated background thread."""
    while not state.shutdown_event.is_set():
        job = None
        with state.lock:
            while (
                state.next_job is None
                and not state.shutdown_event.is_set()
                and not state.shutdown_flag
            ):
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
    emit_event(
        config,
        "job_started",
        {
            "job_id": client_job_id,
            "worker_job_id": worker_job_id,
            "command": cmd,
            "run_id": state.run_id,
        },
    )

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
            SequenceRequest
            if cmd == "sequence"
            else TriggerRequest
            if cmd.startswith("trigger-")
            else OperationRequest
        )
        request = request_type(cmd, runtime, _command_parameters(arguments))
    # Admission owns canonical parameters and materialized documents. Copy so
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
                        "set",
                        "apply",
                        "output-on",
                        "output-off",
                        "safe-off",
                        "cycle-output",
                        "ramp",
                        "smoke-output",
                        "trigger-pulse",
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
            progress_reporter=report_progress if cmd in {"log", "ramp"} else None,
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
        elif (
            isinstance(exc, (CommandCancelled, KeyboardInterrupt))
            or exc.__class__.__name__ in {"TriggerInterrupted", "SequenceStopped"}
            or state.stop_event.is_set()
            or state.job_cancel_event.is_set()
        ):
            err_type = "execution"
            code = (
                "cancelled"
                if state.job_cancel_event.is_set() and cmd in {"ramp", "ramp-list", "sequence", "log"}
                else "stopped"
            )
            retryable = True

        error_payload = {
            "type": err_type,
            "code": code,
            "message": "Execution was stopped by user request"
            if isinstance(exc, KeyboardInterrupt)
            else str(exc),
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
