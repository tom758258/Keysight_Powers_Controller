"""Ramp-list workflow handler and shared sequence/Trigger compatibility helpers."""

from __future__ import annotations

__all__ = [
    "_cooperative_workflow_interrupt",
    "_emit_workflow_interruption",
    "_load_sequence_document",
    "_parse_sequence_scalar",
    "_parse_simple_sequence_yaml",
    "_print_sequence_summary",
    "_run_ramp_list",
    "_workflow_start_summary",
]

import argparse
import json
import signal
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from powers_tool_cli import cli_rendering
from powers_tool_cli.cli_io import emit_json_error, emit_json_success
from powers_tool_cli.cli_request import _ramp_list_request_for_args, _request_for_args
from powers_tool_cli.cli_runtime import (
    _core_opener_for_args,
    _core_validation_code,
    _emit_cli_error,
    _emit_safe_io_error,
    _emit_text_lines,
    _log_scpi,
    _patchable_run_core_command,
    _resolve_optional_resource_alias,
)
from powers_tool_cli.runtime_mapping import execution_for_args as _execution_for_args
from powers_tool_core.command_runner import validate_request_admission, workflow_execution_summary
from powers_tool_core.core import (
    CommandCancelled,
    CoreExecutionError,
    CoreIoError,
    CoreValidationError,
    OperationRequest,
    SequenceRequest,
    StopCleanupError,
)
from powers_tool_core.safety import SafetyConfigError, SafetyValidationError

@contextmanager
def _cooperative_workflow_interrupt() -> Iterator[threading.Event]:
    stop_event = threading.Event()
    installed = threading.current_thread() is threading.main_thread()
    previous_handler: Any = None

    if installed:
        previous_handler = signal.getsignal(signal.SIGINT)

        def request_stop(_signum: int, _frame: Any) -> None:
            stop_event.set()

        signal.signal(signal.SIGINT, request_stop)
    try:
        yield stop_event
    finally:
        if installed:
            signal.signal(signal.SIGINT, previous_handler)

def _emit_workflow_interruption(
    args: argparse.Namespace,
    *,
    request: dict[str, Any],
    execution: dict[str, Any],
    exc: CommandCancelled | StopCleanupError,
) -> int:
    cleanup_failed = isinstance(exc, StopCleanupError)
    code = "cleanup_failed" if cleanup_failed else "cancelled"
    data = dict(getattr(exc, "data", {}) or {})
    data.setdefault("original_reason", "user cancellation")
    if args.json:
        emit_json_error(
            command=args.command,
            execution=execution,
            request=request,
            error_type="execution",
            code=code,
            message=str(exc),
            retryable=cleanup_failed,
            data=data,
        )
    else:
        print(f"{args.command} {code}: {exc}", file=sys.stderr)
    return 3

def _workflow_start_summary(
    args: argparse.Namespace,
    core_request: OperationRequest | SequenceRequest,
) -> tuple[
    OperationRequest | SequenceRequest,
    dict[str, Any],
    list[dict[str, str]],
]:
    admitted_request = validate_request_admission(core_request)
    summary = workflow_execution_summary(admitted_request) or {}
    units = summary.get("execution_units")
    warning = summary.get("execution_warning")
    if not args.json and not getattr(args, "lint", False) and isinstance(units, int):
        for line in cli_rendering.format_execution_summary_notice(
            units,
            warning if isinstance(warning, str) else None,
        ):
            print(line, file=sys.stderr)
    warnings = (
        [{"code": "long_running_workflow", "message": warning}]
        if isinstance(warning, str)
        else []
    )
    return admitted_request, summary, warnings

def _run_ramp_list(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=False)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        core_request = _ramp_list_request_for_args(args)
        core_request, execution_summary, execution_warnings = _workflow_start_summary(
            args, core_request
        )
        base_opener = _core_opener_for_args(args)

        def opener(*opener_args: Any, **opener_kwargs: Any) -> Any:
            if execution["mode"] == "real" and not execution["dry_run"]:
                execution["hardware_touched"] = True
            return base_opener(*opener_args, **opener_kwargs)

        with _cooperative_workflow_interrupt() as stop_event:
            data = _patchable_run_core_command(
                core_request,
                opener=opener,
                stop_requested=stop_event.is_set,
                sleep=time.sleep,
                scpi_logger=_log_scpi,
            )
    except (CommandCancelled, StopCleanupError) as exc:
        return _emit_workflow_interruption(
            args,
            request=request,
            execution=execution,
            exc=exc,
        )
    except KeyboardInterrupt:
        return _emit_workflow_interruption(
            args,
            request=request,
            execution=execution,
            exc=CommandCancelled("ramp-list cancelled before a VISA session was opened"),
        )
    except CoreValidationError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code=_core_validation_code(exc),
            message=str(exc),
            retryable=False,
            hardware_intent=bool(execution["hardware_touched"]),
        )
    except (SafetyConfigError, SafetyValidationError, ValueError, OSError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=bool(execution["hardware_touched"]),
        )
    except CoreIoError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="ramp_list_failed" if exc.opened else "connection_failed",
            message=str(exc),
        )
    except CoreExecutionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="ramp_list_failed",
            message=str(exc),
            data=dict(getattr(exc, "data", {}) or {})
            or ({"trigger": exc.trigger} if exc.trigger is not None else None),
        )

    if data["status"] in {"failed", "stopped"}:
        failed = data.get("failed_segment") or {}
        message = (
            f"ramp-list stopped at segment {failed.get('index')}"
            if data["status"] == "stopped"
            else f"ramp-list segment {failed.get('index')} failed: {failed.get('message', 'segment failed')}"
        )
        if args.json:
            emit_json_error(
                command=args.command,
                execution=execution,
                request=request,
                error_type="execution",
                code="stopped" if data["status"] == "stopped" else "ramp_list_failed",
                message=message,
                retryable=True,
            )
        else:
            print(message, file=sys.stderr)
        return 3
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=data,
            warnings=execution_warnings,
        )
    else:
        _emit_text_lines(cli_rendering.format_ramp_list_summary(data))
    return 0

def _load_sequence_document(path: str) -> dict[str, Any]:
    sequence_path = Path(path)
    try:
        text = sequence_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"could not read sequence file {sequence_path}: {exc}") from exc
    stripped = text.lstrip()
    if stripped.startswith("{"):
        parsed = json.loads(text)
    else:
        try:
            import yaml  # type: ignore[import-untyped]
        except ModuleNotFoundError:
            parsed = _parse_simple_sequence_yaml(text)
        else:
            parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError("sequence file must contain a mapping")
    return parsed

def _parse_simple_sequence_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_steps = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", maxsplit=1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped == "steps:":
            in_steps = True
            data["steps"] = steps
            continue
        if not in_steps:
            if ":" not in stripped:
                raise ValueError(f"unsupported sequence YAML line: {raw_line}")
            key, value = stripped.split(":", maxsplit=1)
            data[key.strip()] = _parse_sequence_scalar(value.strip())
            continue
        if stripped.startswith("- "):
            current = {}
            steps.append(current)
            item = stripped[2:].strip()
            if item:
                if ":" not in item:
                    current["action"] = item
                else:
                    key, value = item.split(":", maxsplit=1)
                    current[key.strip()] = _parse_sequence_scalar(value.strip())
            continue
        if current is None or ":" not in stripped:
            raise ValueError(f"unsupported sequence YAML line: {raw_line}")
        key, value = stripped.split(":", maxsplit=1)
        current[key.strip()] = _parse_sequence_scalar(value.strip())
    return data

def _parse_sequence_scalar(value: str) -> Any:
    if value == "":
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.lower() == "all":
        return "all"
    try:
        if any(marker in value for marker in (".", "e", "E")):
            return float(value)
        return int(value)
    except ValueError:
        return value.strip("'\"")

def _print_sequence_summary(data: dict[str, Any]) -> None:
    _emit_text_lines(cli_rendering.format_sequence_summary(data))

