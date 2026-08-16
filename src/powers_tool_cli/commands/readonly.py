"""Read-only, protection, snapshot, restore artifact, and logging command handlers."""

from __future__ import annotations

__all__ = [
    "_collect_log_samples",
    "_run_clear_protection",
    "_run_hardware_report",
    "_run_identify",
    "_run_log",
    "_run_protection_set",
    "_run_protection_status",
    "_run_read_only_command",
    "_run_readback",
    "_run_snapshot",
    "_run_snapshot_diff",
    "_run_status",
    "_run_validate_readonly",
    "_snapshot_diff_summary",
]

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

import powers_tool_core.instrument_io as instrument_io_core
import powers_tool_core.protection as protection_core
import powers_tool_core.readonly as readonly_core
import powers_tool_core.snapshot as snapshot_core
from powers_tool_cli import cli_rendering
from powers_tool_cli.cli_io import emit_json_success
from powers_tool_cli.cli_request import (
    _request_for_args,
    _target_core_request_for_args,
    _validate_readonly_request_for_args,
)
from powers_tool_cli.cli_runtime import (
    _ReadOnlyChannelError,
    _build_hardware_report,
    _collect_readback,
    _collect_status,
    _compare_snapshot_data,
    _connection_scpi_logger_for_args,
    _core_opener_for_args,
    _core_validation_code,
    _diff_snapshots,
    _emit_cli_error,
    _emit_safe_io_error,
    _emit_text_lines,
    _format_text_value,
    _load_snapshot_document,
    _log_scpi,
    _open_jsonl_log,
    _open_resource,
    _patchable_run_core_command,
    _read_only_channels_from_selection,
    _resolve_optional_resource_alias,
    _resource_manager_for_args,
    _resource_payload,
    _snapshot_compare_tolerances,
    _write_hardware_report_files,
    _write_json_file_atomic,
)
from powers_tool_cli.commands.sequence_run import _cooperative_workflow_interrupt
from powers_tool_cli.runtime_mapping import (
    execution_for_args as _execution_for_args,
    mode_for_args as _mode_for_args,
)
from powers_tool_core.command_runner import validate_request_admission
from powers_tool_core.connection import SerialOptions
from powers_tool_core.core import (
    CommandCancelled,
    ConfirmationRequiredError,
    CoreExecutionError,
    CoreIoError,
    CoreValidationError,
    UnsupportedModelError,
)
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.safety import SafetyConfigError
from powers_tool_core.telemetry import TELEMETRY_ROW_FIELDS
from powers_tool_core.testing.simulator import SimulatedResourceManager

LOG_CSV_FIELDS = TELEMETRY_ROW_FIELDS

def _run_status(args: argparse.Namespace) -> int:
    result = _run_read_only_command(
        args,
        command_label="status",
        unsupported_code="unsupported_model_for_status",
        failure_code="status_failed",
        operation=_collect_status,
    )
    exit_code, data = result
    if exit_code != 0:
        return exit_code
    data.pop("idn_raw", None)
    if args.json:
        emit_json_success(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=True),
            request=_request_for_args(args),
            data=data,
        )
        return 0

    _emit_text_lines(cli_rendering.format_read_status(data["errors"], data["outputs"]))
    return 0

def _run_readback(args: argparse.Namespace) -> int:
    result = _run_read_only_command(
        args,
        command_label="readback",
        unsupported_code="unsupported_model_for_readback",
        failure_code="readback_failed",
        operation=_collect_readback,
    )
    if result is None:
        return 1
    exit_code, data = result
    if exit_code != 0:
        return exit_code
    data.pop("idn_raw", None)
    if args.json:
        emit_json_success(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=True),
            request=_request_for_args(args),
            data=data,
        )
        return 0
    _emit_text_lines(
        cli_rendering.format_readback(
            data["resource"],
            data["channels"],
            value_to_text=_format_text_value,
        )
    )
    return 0

def _run_validate_readonly(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except SafetyConfigError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    try:
        core_data = readonly_core.run_validate_readonly(
            _validate_readonly_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except UnsupportedModelError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="unsupported_model_for_validate_readonly",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except CoreValidationError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code=_core_validation_code(exc),
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except CoreIoError as exc:
        code = "validate_readonly_failed" if exc.opened else "connection_failed"
        message = (
            f"validate-readonly failed: {exc}"
            if exc.opened
            else f"Could not open resource for validate-readonly: {exc}"
        )
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=message)

    idn_raw = core_data.pop("idn_raw")
    data = {
        **core_data,
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
    }
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0

    _emit_text_lines(
        cli_rendering.format_validate_readonly(
            data,
            channel_order=data["capabilities"]["channels"],
            value_to_text=_format_text_value,
        )
    )
    return 0

def _run_read_only_command(
    args: argparse.Namespace,
    *,
    command_label: str,
    unsupported_code: str,
    failure_code: str,
    operation: Any,
) -> tuple[int, dict[str, Any]]:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except SafetyConfigError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="argument_error",
                message=str(exc),
                retryable=False,
            ),
            {},
        )

    selected_channel = "all" if getattr(args, "all", False) else getattr(args, "channel", "all")
    try:
        _read_only_channels_from_selection(selected_channel, (1, 2, 3))
    except _ReadOnlyChannelError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="argument_error",
                message=str(exc),
                retryable=False,
            ),
            {},
        )
    try:
        return 0, readonly_core.run_readonly(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except UnsupportedModelError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code=unsupported_code,
                message=str(exc),
                retryable=False,
                hardware_intent=True,
            ),
            {},
        )
    except CoreValidationError as exc:
        return (
            _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code=_core_validation_code(exc),
                message=str(exc),
                retryable=False,
                hardware_intent=True,
            ),
            {},
        )
    except CoreIoError as exc:
        return (
            _emit_safe_io_error(
                args,
                request=request,
                execution=execution,
                code=failure_code if exc.opened else "connection_failed",
                message=str(exc),
            ),
            {},
        )

def _run_protection_status(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    try:
        data = protection_core.run_protection(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except UnsupportedModelError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="unsupported_model_for_protection_status", message=str(exc), retryable=False, hardware_intent=True)
    except CoreValidationError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code=_core_validation_code(exc), message=str(exc), retryable=False, hardware_intent=True)
    except CoreIoError as exc:
        code = "protection_status_failed" if exc.opened else "connection_failed"
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=str(exc))
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=data,
        )
        return 0
    _emit_text_lines(cli_rendering.format_protection_status(data))
    return 0

def _run_clear_protection(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    if not args.all and args.channel is None:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message="clear-protection requires --channel N or --all",
            retryable=False,
        )
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except SafetyConfigError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    try:
        data = protection_core.run_protection(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except ConfirmationRequiredError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="confirmation_required", message=str(exc), retryable=False, hardware_intent=True)
    except UnsupportedModelError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="unsupported_model_for_clear_protection", message=str(exc), retryable=False, hardware_intent=True)
    except CoreValidationError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code=_core_validation_code(exc), message=str(exc), retryable=False, hardware_intent=True)
    except CoreIoError as exc:
        code = "clear_protection_failed" if exc.opened else "connection_failed"
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=str(exc))
    except CoreExecutionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="clear_protection_failed",
            message=str(exc),
        )

    if "plan" in data:
        plan = data["plan"]
        if args.json:
            emit_json_success(command=args.command, execution=execution, request=request, data={"plan": plan})
            return 0
        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=args.dry_run)
        return 0
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0
    _emit_text_lines(
        cli_rendering.format_clear_protection_success(
            args.resource,
            data["cleared_channels"],
        )
    )
    return 0

def _run_protection_set(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    if (
        args.ovp_voltage is None
        and args.ocp is None
        and args.ocp_delay is None
        and args.ocp_delay_trigger is None
    ):
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message="protection-set requires --ovp-voltage, --ocp, --ocp-delay, or --ocp-delay-trigger",
            retryable=False,
        )
    try:
        request = _request_for_args(args)
        data = protection_core.run_protection(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except ConfirmationRequiredError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="confirmation_required", message=str(exc), retryable=False, hardware_intent=True)
    except UnsupportedModelError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="unsupported_model_for_protection_set", message=str(exc), retryable=False, hardware_intent=True)
    except CoreValidationError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code=_core_validation_code(exc),
            message=str(exc),
            retryable=False,
        )
    except CoreIoError as exc:
        code = "protection_set_failed" if exc.opened else "connection_failed"
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=str(exc))
    except CoreExecutionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="protection_set_failed",
            message=str(exc),
        )

    if "plan" in data:
        plan = data["plan"]
        if args.json:
            emit_json_success(command=args.command, execution=execution, request=request, data={"plan": plan})
            return 0
        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=args.dry_run)
        return 0
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0
    _emit_text_lines(
        cli_rendering.format_protection_set_success(
            args.resource,
            data["channels"],
            value_to_text=_format_text_value,
        )
    )
    return 0

def _run_identify(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except SafetyConfigError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="argument_error", message=str(exc), retryable=False)

    try:
        data = instrument_io_core.run_instrument_io(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except CoreValidationError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except CoreIoError as exc:
        code = "identify_failed" if exc.opened else "connection_failed"
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=str(exc))
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0
    _emit_text_lines(cli_rendering.format_identify(args.resource, data))
    return 0

def _run_snapshot(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    try:
        data = snapshot_core.run_snapshot(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except UnsupportedModelError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="unsupported_model_for_snapshot", message=str(exc), retryable=False, hardware_intent=True)
    except CoreValidationError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code=_core_validation_code(exc), message=str(exc), retryable=False, hardware_intent=True)
    except CoreIoError as exc:
        code = "snapshot_failed" if exc.opened else "connection_failed"
        return _emit_safe_io_error(args, request=request, execution=execution, code=code, message=str(exc))
    persisted_snapshot = dict(data)
    comparison = None
    if args.compare:
        try:
            comparison = _compare_snapshot_data(data, args.compare, _snapshot_compare_tolerances(args))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return _emit_cli_error(
                args,
                request=_request_for_args(args),
                error_type="validation",
                code="snapshot_compare_failed",
                message=f"Could not compare snapshot: {exc}",
                retryable=False,
                hardware_intent=True,
            )
        data["comparison"] = comparison
    if args.redact_resource:
        data["resource"] = "<redacted>"
        data["resource_redacted"] = True
        persisted_snapshot["resource"] = "<redacted>"
        persisted_snapshot["resource_redacted"] = True
    if args.snapshot_json:
        try:
            _write_json_file_atomic(args.snapshot_json, persisted_snapshot)
        except OSError as exc:
            return _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="snapshot_write_failed",
                message=f"Could not write raw snapshot JSON: {exc}",
                retryable=False,
                hardware_intent=True,
            )
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=data,
        )
        return 0 if comparison is None or comparison["passed"] else 3
    _emit_text_lines(cli_rendering.format_snapshot(data, comparison=comparison))
    return 0 if comparison is None or comparison["passed"] else 3

def _run_snapshot_diff(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=False)
    try:
        before = _load_snapshot_document(args.before)
        after = _load_snapshot_document(args.after)
        differences = _diff_snapshots(before, after)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    data = {
        "before": args.before,
        "after": args.after,
        "changed": bool(differences),
        "change_count": len(differences),
        "differences": differences,
    }
    if args.summary:
        data["summary"] = _snapshot_diff_summary(differences)
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0
    _emit_text_lines(cli_rendering.format_snapshot_diff(data, summary=args.summary))
    return 0

def _run_hardware_report(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=False)
    try:
        report = _build_hardware_report(args)
        _write_hardware_report_files(report, args.report_json, args.summary_md)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    data = {
        "report_json": args.report_json,
        "summary_md": args.summary_md,
        "report": report,
    }
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
        return 0
    _emit_text_lines(
        cli_rendering.format_hardware_report_success(
            args.report_json,
            args.summary_md,
            report,
        )
    )
    return 0

def _snapshot_diff_summary(differences: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for difference in differences:
        category = str(difference.get("category", "unknown"))
        summary[category] = summary.get(category, 0) + 1
    return dict(sorted(summary.items()))

def _run_log(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)

    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
    except (SafetyConfigError, ValueError, CoreValidationError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )

    try:
        result = _collect_log_samples(args, manager, backend=args.backend, timeout_ms=args.timeout_ms)
    except CoreValidationError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code=(
                "unsupported_model_for_log"
                if isinstance(exc, UnsupportedModelError)
                else _core_validation_code(exc)
            ),
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except (CoreIoError, OSError, VisaConnectionError, ValueError) as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="log_failed",
            message=f"log failed: {exc}",
        )

    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=result,
        )
        return 0

    _emit_text_lines(cli_rendering.format_log_success(args.resource, args.csv, result))
    return 0

def _collect_log_samples(
    args: argparse.Namespace,
    resource_manager: SimulatedResourceManager | None,
    *,
    backend: str | None,
    timeout_ms: int,
) -> dict[str, Any]:
    request = validate_request_admission(_target_core_request_for_args(args))
    csv_path = Path(args.csv)
    result: dict[str, Any] | None = None
    csv_file: Any = None
    jsonl_file: Any = None
    writer: csv.DictWriter | None = None

    def opener(
        resource: str,
        manager: Any = None,
        *,
        backend: str | None,
        timeout_ms: int,
        serial_options: SerialOptions | None = None,
        serial_remote: bool = False,
        serial_local_on_close: bool = False,
    ) -> Any:
        return _open_resource(
            resource,
            manager if manager is not None else resource_manager,
            backend=backend,
            timeout_ms=timeout_ms,
            serial_options=serial_options,
            serial_remote=serial_remote,
            serial_local_on_close=serial_local_on_close,
            scpi_logger=_connection_scpi_logger_for_args(args),
        )

    def open_writers() -> None:
        nonlocal csv_file, jsonl_file, writer
        if writer is not None:
            return
        if csv_path.parent != Path("."):
            csv_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if args.append else "w"
        write_header = (
            (not args.append)
            or (not csv_path.exists())
            or csv_path.stat().st_size == 0
        )
        csv_file = csv_path.open(mode, newline="", encoding="utf-8")
        writer = csv.DictWriter(csv_file, fieldnames=LOG_CSV_FIELDS)
        if write_header:
            writer.writeheader()
            csv_file.flush()
        jsonl_file = _open_jsonl_log(args)

    def report_sample(row: dict[str, Any]) -> None:
        open_writers()
        if writer is None or csv_file is None:
            raise CoreIoError("log telemetry writer did not initialize")
        writer.writerow(row)
        csv_file.flush()
        if jsonl_file is not None:
            jsonl_file.write(
                json.dumps({"event": "sample", "sample": row}, sort_keys=True)
                + "\n"
            )
            jsonl_file.flush()

    try:
        with _cooperative_workflow_interrupt() as stop_event:
            try:
                result = _patchable_run_core_command(
                    request,
                    opener=opener,
                    stop_requested=stop_event.is_set,
                    sleep=time.sleep,
                    scpi_logger=_log_scpi if args.log_scpi else None,
                    sample_reporter=report_sample,
                )
            except CommandCancelled as exc:
                result = dict(exc.data)
                result["stopped"] = True
                result["stop_reason"] = "interrupted"
    finally:
        if jsonl_file is not None:
            if result is not None:
                jsonl_file.write(
                    json.dumps(
                        {
                            "event": "summary",
                            "samples_written": result["samples_written"],
                            "channels": result["channels"],
                            "stopped": result["stopped"],
                            "stop_reason": result["stop_reason"],
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
                jsonl_file.flush()
            jsonl_file.close()
        if csv_file is not None:
            csv_file.close()

    if result is None:
        raise CoreIoError("log failed without a collection result")
    return {
        **result,
        "csv": args.csv,
        "jsonl": args.jsonl,
        "append": args.append,
    }
