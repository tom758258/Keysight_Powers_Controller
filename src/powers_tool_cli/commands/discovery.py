"""Discovery and generic instrument I/O command handlers."""

from __future__ import annotations

__all__ = [
    "_run_clear",
    "_run_error",
    "_run_list_resources",
    "_run_measure",
    "_run_measure_all",
    "_run_verify",
]

import argparse
import sys

import powers_tool_core.discovery as discovery_core
import powers_tool_core.instrument_io as instrument_io_core
import powers_tool_core.readonly as readonly_core
from powers_tool_cli import cli_rendering
from powers_tool_cli.cli_io import emit_json_error, emit_json_success
from powers_tool_cli.cli_request import (
    _request_for_args,
    _target_core_request_for_args,
)
from powers_tool_cli.cli_runtime import (
    _core_lister_for_args,
    _core_opener_for_args,
    _core_validation_code,
    _emit_cli_error,
    _emit_safe_io_error,
    _emit_text_lines,
    _format_text_value,
    _log_scpi,
    _resolve_optional_resource_alias,
)
from powers_tool_cli.runtime_mapping import (
    execution_for_args as _execution_for_args,
    mode_for_args as _mode_for_args,
)
from powers_tool_core.core import CoreIoError, CoreValidationError, UnsupportedChannelError
from powers_tool_core.models import parse_idn
from powers_tool_core.safety import SafetyConfigError

def _run_list_resources(args: argparse.Namespace) -> int:
    execution = _execution_for_args(args, hardware_intent=args.live_only)
    request = _request_for_args(args)
    try:
        data = discovery_core.run_discovery(
            _target_core_request_for_args(args),
            resource_lister=_core_lister_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except CoreIoError as exc:
        message = str(exc)
        if args.json:
            emit_json_error(
                command="list-resources",
                execution=execution,
                request=request,
                error_type="connection",
                code="resource_list_failed",
                message=message,
                retryable=True,
            )
        else:
            print(message, file=sys.stderr)
        return 1

    if args.live_only:
        if args.json:
            emit_json_success(
                command="list-resources",
                execution=execution,
                request=request,
                data=data,
            )
            return 0

        _emit_text_lines(
            cli_rendering.format_list_resources(data["resources"], live_only=True)
        )
        return 0

    if args.json:
        emit_json_success(
            command="list-resources",
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    _emit_text_lines(
        cli_rendering.format_list_resources(data["resources"], live_only=False)
    )
    return 0

def _run_verify(args: argparse.Namespace) -> int:
    execution = _execution_for_args(args, hardware_intent=True)
    request = _request_for_args(args)
    try:
        data = discovery_core.run_discovery(
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
    except CoreIoError:
        message = f"Could not verify VISA resource: {args.resource}"
        if args.json:
            emit_json_error(
                command="verify",
                execution=execution,
                request=request,
                error_type="connection",
                code="resource_unreachable",
                message=message,
                retryable=True,
            )
        else:
            print(message, file=sys.stderr)
        return 1

    if args.json:
        emit_json_success(
            command="verify",
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    _emit_text_lines(cli_rendering.format_verify(data["resource"]["idn"]["raw"]))
    return 0

def _run_clear(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    try:
        data = instrument_io_core.run_instrument_io(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except CoreIoError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="status_clear_failed",
            message=f"Could not clear instrument status for {args.resource}: {exc}",
        )

    if args.dry_run:
        plan = data["plan"]
        if args.json:
            emit_json_success(
                command="clear",
                execution=execution,
                request=request,
                data={"plan": plan},
            )
            return 0

        _print_scpi_plan(plan, mode=_mode_for_args(args), dry_run=True)
        return 0

    if args.json:
        emit_json_success(
            command="clear",
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    _emit_text_lines(cli_rendering.format_clear_success(args.resource))
    return 0

def _run_error(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)

    try:
        data = instrument_io_core.run_instrument_io(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except CoreIoError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="error_query_failed",
            message=f"Could not query error queue for {args.resource}: {exc}",
        )

    if args.json:
        emit_json_success(
            command="error",
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    _emit_text_lines(cli_rendering.format_error_queue(data["errors"]))
    return 0

def _run_measure(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=True)
    try:
        data = instrument_io_core.run_instrument_io(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
        )
    except UnsupportedChannelError as exc:
        if args.json:
            emit_json_error(
                command="measure",
                execution=execution,
                request=request,
                error_type="validation",
                code="argument_error",
                message=str(exc),
                retryable=False,
            )
        else:
            print(str(exc), file=sys.stderr)
        return 2
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
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="measurement_failed",
            message=f"Could not measure voltage/current for {args.resource}: {exc}",
        )

    if args.json:
        emit_json_success(
            command="measure",
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    _emit_text_lines(
        cli_rendering.format_measure(
            data["measurements"],
            value_to_text=_format_text_value,
        )
    )
    return 0

def _run_measure_all(args: argparse.Namespace) -> int:
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
        data = readonly_core.run_readonly(
            _target_core_request_for_args(args),
            opener=_core_opener_for_args(args),
            scpi_logger=_log_scpi,
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
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="measure_all_failed" if exc.opened else "connection_failed",
            message=str(exc),
        )

    if not args.dry_run:
        idn_raw = data.pop("idn_raw", None)
        if not isinstance(idn_raw, str):
            if args.json:
                emit_json_error(
                    command=args.command,
                    execution=execution,
                    request=request,
                    error_type="execution",
                    code="invalid_core_result",
                    message="measure-all Core result did not include a valid observed IDN string.",
                    retryable=False,
                )
            else:
                print("measure-all Core result did not include a valid observed IDN string.", file=sys.stderr)
            return 3
        observed = parse_idn(idn_raw)
        data["idn"] = {
            "manufacturer": observed.manufacturer,
            "model": observed.model,
            "serial": observed.serial,
            "firmware": observed.firmware,
            "parse_ok": observed.parse_ok,
        }
    if args.json:
        emit_json_success(
            command=args.command,
            execution=execution,
            request=request,
            data=data,
        )
        return 0

    _emit_text_lines(
        cli_rendering.format_measure_all(
            data["channels"],
            value_to_text=_format_text_value,
        )
    )
    return 0

