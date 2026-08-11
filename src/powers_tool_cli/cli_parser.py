"""Shared argparse primitives for the Powers Tool CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import powers_tool_core.validation as validation
from powers_tool_cli.cli_io import emit_json_error
from powers_tool_core.connection import (
    DEFAULT_TIMEOUT_MS,
    normalize_serial_termination,
)
from powers_tool_core.workflow_validation import MAX_LOOP_COUNT


@dataclass(frozen=True)
class _ParserErrorContext:
    command_from_argv: Callable[[Sequence[str]], str]
    validation_execution_from_argv: Callable[[Sequence[str]], dict[str, Any]]
    request_from_argv: Callable[[str, Sequence[str]], dict[str, Any]]


class JsonCliArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that keeps JSON validation errors machine-readable."""

    active_argv: tuple[str, ...] = ()
    error_context: _ParserErrorContext | None = None

    def error(self, message: str) -> None:
        if "--json" in self.active_argv:
            context = self.error_context
            if context is None:
                raise RuntimeError("JSON parser error context is not configured")
            command = context.command_from_argv(self.active_argv)
            emit_json_error(
                command=command,
                execution=context.validation_execution_from_argv(self.active_argv),
                request=context.request_from_argv(command, self.active_argv),
                error_type="validation",
                code="argument_error",
                message=message,
                retryable=False,
            )
            raise SystemExit(2)

        super().error(message)


def configure_parser_error_context(
    *,
    command_from_argv: Callable[[Sequence[str]], str],
    validation_execution_from_argv: Callable[[Sequence[str]], dict[str, Any]],
    request_from_argv: Callable[[str, Sequence[str]], dict[str, Any]],
) -> None:
    JsonCliArgumentParser.error_context = _ParserErrorContext(
        command_from_argv=command_from_argv,
        validation_execution_from_argv=validation_execution_from_argv,
        request_from_argv=request_from_argv,
    )


def _add_backend_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backend", help="Optional PyVISA backend.")


def _add_timeout_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=DEFAULT_TIMEOUT_MS,
        help="VISA timeout in milliseconds.",
    )


def _add_serial_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--serial-baud-rate", type=int, help="Optional ASRL baud rate.")
    parser.add_argument("--serial-data-bits", type=int, help="Optional ASRL data bits.")
    parser.add_argument(
        "--serial-parity",
        choices=("none", "odd", "even", "mark", "space"),
        help="Optional ASRL parity.",
    )
    parser.add_argument(
        "--serial-stop-bits",
        choices=("1", "1.5", "2"),
        help="Optional ASRL stop bits.",
    )
    parser.add_argument(
        "--serial-flow-control",
        choices=("none", "xon_xoff", "rts_cts", "dtr_dsr"),
        help="Optional ASRL flow control.",
    )
    parser.add_argument(
        "--serial-read-termination",
        type=normalize_serial_termination,
        help="Optional ASRL read termination. Aliases: CR, LF, CRLF, NONE.",
    )
    parser.add_argument(
        "--serial-write-termination",
        type=normalize_serial_termination,
        help="Optional ASRL write termination. Aliases: CR, LF, CRLF, NONE.",
    )
    parser.add_argument(
        "--serial-remote",
        action="store_true",
        help="Send SYST:REM after opening an ASRL resource.",
    )
    parser.add_argument(
        "--serial-local-on-close",
        action="store_true",
        help="Best-effort send SYST:LOC before closing an ASRL resource.",
    )


def _add_lifecycle_url_argument(
    parser: argparse.ArgumentParser,
    *,
    default_path: str,
) -> None:
    parser.add_argument(
        "--url",
        help=f"Full Worker URL. Defaults to http://127.0.0.1:{{port}}{default_path}.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Worker host.")
    parser.add_argument("--port", type=int, default=0, help="Worker port.")


def _add_lifecycle_timeout_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--timeout-ms",
        type=_lifecycle_timeout_ms,
        default=3000,
        help="HTTP timeout in milliseconds.",
    )


def _add_lifecycle_format_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    parser.add_argument("--json", action="store_true", help="Alias for --format json.")


def _add_json_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON to stdout.",
    )
    parser.add_argument(
        "--save-json",
        help="Write the same JSON envelope to a UTF-8 file. Requires --json.",
    )


def _add_simulate_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Use deterministic simulated resources instead of real VISA resources.",
    )


def _add_dry_run_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the logical operation without opening or writing to hardware.",
    )


def _add_validation_support_policy_argument(parser: argparse.ArgumentParser) -> None:
    """Add the contributor-only pending-scope validation switch."""

    parser.add_argument(
        "--validation-allow-pending-live-support",
        dest="validation_allow_pending_live_support",
        action="store_true",
        help=argparse.SUPPRESS,
    )


def _add_model_argument(
    parser: argparse.ArgumentParser,
    *,
    allow_profile: bool = False,
) -> None:
    parser.add_argument(
        "--model",
        help=(
            "Canonical vendor-qualified physical model ID. Used as planning_model_id "
            "for dry-run/simulator execution and expected_model_id for live execution."
        ),
    )
    if allow_profile:
        parser.add_argument(
            "--profile",
            help="Nonphysical dry-run planning profile; currently generic-scpi.",
        )


def _add_write_verification_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--settle-ms",
        type=_nonnegative_int,
        default=0,
        help="Milliseconds to wait after writes before optional readback verification.",
    )
    parser.add_argument(
        "--verify-after-write",
        action="store_true",
        help="Read back state after writes and fail if verification differs.",
    )
    parser.add_argument(
        "--setpoint-voltage-tolerance",
        type=float,
        default=0.001,
        help="Programmed voltage verification tolerance in volts.",
    )
    parser.add_argument(
        "--setpoint-current-tolerance",
        type=float,
        default=0.001,
        help="Programmed current verification tolerance in amps.",
    )


def _add_completion_pulse_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--completion-pulse-pins",
        type=_trigger_pins_list,
        help="Comma-separated E36312A rear digital trigger output pins.",
    )
    parser.add_argument(
        "--completion-pulse-polarity",
        choices=("positive", "negative"),
        default="positive",
        help="Completion trigger output polarity.",
    )
    parser.add_argument(
        "--completion-pulse-channel",
        type=_e36312a_channel,
        help="E36312A output trigger channel for completion pulses.",
    )


def _add_ramp_completion_pulse_arguments(parser: argparse.ArgumentParser) -> None:
    _add_completion_pulse_arguments(parser)
    parser.add_argument(
        "--completion-pulse-timing",
        choices=("segment", "step", "loop"),
        default="segment",
        help="Pulse after each Ramp, after every voltage step, or once after all loops.",
    )


def _add_trigger_restore_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--leave-trigger-configured",
        action="store_true",
        help=(
            "Leave trigger/list/digital pin settings in place instead of restoring "
            "the pre-run state."
        ),
    )


def _add_trigger_wait_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--poll-ms",
        type=_trigger_poll_ms,
        default=200,
        help="Operation-complete poll interval in milliseconds, minimum 50.",
    )
    parser.add_argument(
        "--wait-timeout-ms",
        type=_positive_int,
        help="Operation-complete wait timeout in milliseconds.",
    )


def _add_duration_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--duration-ms",
        type=_positive_duration_ms,
        default=500,
        help="Enable duration in milliseconds.",
    )


def _add_resource_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--resource", required=True, help="VISA resource string.")


def _add_output_resource_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--resource", help="VISA resource string.")
    group.add_argument(
        "--resource-alias",
        help="Alias from an explicit --safety-config [[resources]] entry.",
    )
    _add_validation_support_policy_argument(parser)


def _add_channel_or_all_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--channel",
        default="all",
        type=_status_channel,
        help="Positive integer output channel or 'all'.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Read all E36312A output channels.",
    )


def _add_safety_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--safety-config",
        help="Explicit TOML safety config path with global or resource limits.",
    )


def _positive_channel(value: str) -> int:
    try:
        return validation.parse_positive_int(value, name="channel")
    except validation.ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _positive_max_reads(value: str) -> int:
    try:
        return validation.parse_positive_int(value, name="max-reads")
    except validation.ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _positive_max_errors(value: str) -> int:
    try:
        return validation.parse_positive_int(value, name="max-errors")
    except validation.ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _positive_duration_ms(value: str) -> int:
    try:
        return validation.parse_positive_int(value, name="duration-ms")
    except validation.ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _positive_int(value: str) -> int:
    try:
        return validation.parse_positive_int(value)
    except validation.ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _loop_count(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"loop-count must be an integer from 1 to {MAX_LOOP_COUNT:,}"
        ) from exc
    if parsed < 1 or parsed > MAX_LOOP_COUNT:
        raise argparse.ArgumentTypeError(
            f"loop-count must be an integer from 1 to {MAX_LOOP_COUNT:,}"
        )
    return parsed


def _lifecycle_timeout_ms(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout-ms must be an integer") from exc
    if parsed < 100 or parsed > 600000:
        raise argparse.ArgumentTypeError("timeout-ms must be between 100 and 600000")
    return parsed


def _trigger_poll_ms(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "poll-ms must be an integer of at least 50"
        ) from exc
    if parsed < 50:
        raise argparse.ArgumentTypeError("poll-ms must be an integer of at least 50")
    return parsed


def _positive_float(value: str) -> float:
    try:
        return validation.parse_positive_float(value)
    except validation.ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _nonnegative_int(value: str) -> int:
    try:
        return validation.parse_nonnegative_int(value)
    except validation.ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _log_channel(value: str) -> int | str:
    if value.lower() == "all":
        return "all"
    return _positive_channel(value)


def _channels_list(value: str) -> tuple[int, ...]:
    try:
        return validation.parse_channel_list(value)
    except validation.ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _float_list(value: str) -> tuple[float, ...]:
    try:
        return validation.parse_float_list(value)
    except validation.ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _bool_list(value: str) -> tuple[bool, ...]:
    parsed = []
    for item in value.split(","):
        normalized = item.strip().lower()
        if normalized in {"true", "on", "1"}:
            parsed.append(True)
        elif normalized in {"false", "off", "0"}:
            parsed.append(False)
        else:
            raise argparse.ArgumentTypeError(
                "boolean lists accept true/false, on/off, or 1/0"
            )
    return tuple(parsed)


def _safe_off_channel(value: str) -> int | str:
    if value.lower() == "all":
        return "all"
    return _positive_channel(value)


def _output_channel(value: str) -> int | str:
    if value.lower() == "all":
        return "all"
    return _positive_channel(value)


def _status_channel(value: str) -> int | str:
    if value.lower() == "all":
        return "all"
    return _positive_channel(value)


def _apply_channel(value: str) -> int | str:
    if value.lower() == "all":
        return "all"
    return _positive_channel(value)


def _e36312a_channel(value: str) -> int:
    channel = _positive_channel(value)
    if channel not in (1, 2, 3):
        raise argparse.ArgumentTypeError("channel must be 1, 2, or 3")
    return channel


def _e36312a_channel_or_all(value: str) -> int | str:
    if value.lower() == "all":
        return "all"
    return _e36312a_channel(value)


def _trigger_pin(value: str) -> int:
    pin = _positive_channel(value)
    if pin not in (1, 2, 3):
        raise argparse.ArgumentTypeError("pin must be 1, 2, or 3")
    return pin


def _trigger_pins_list(value: str) -> tuple[int, ...]:
    try:
        return validation.parse_trigger_pins(value)
    except validation.ValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


_CommandRunner = Callable[[argparse.Namespace], int]


def build_parser(
    version_provider: Callable[[], str],
    *,
    run_list_resources: _CommandRunner,
    run_verify: _CommandRunner,
    run_clear: _CommandRunner,
    run_error: _CommandRunner,
    run_measure: _CommandRunner,
    run_measure_all: _CommandRunner,
    run_status: _CommandRunner,
    run_validate_readonly: _CommandRunner,
    run_readback: _CommandRunner,
    run_protection_status: _CommandRunner,
    run_protection_set: _CommandRunner,
    run_clear_protection: _CommandRunner,
    run_identify: _CommandRunner,
    run_snapshot: _CommandRunner,
    run_snapshot_diff: _CommandRunner,
    run_hardware_report: _CommandRunner,
    run_restore_from_snapshot: _CommandRunner,
    run_log: _CommandRunner,
    run_doctor: _CommandRunner,
    run_capabilities: _CommandRunner,
    run_safety_inspect: _CommandRunner,
    run_worker: _CommandRunner,
    run_output_plan: _CommandRunner,
    run_core_trigger: _CommandRunner,
    run_sequence_command: _CommandRunner,
    run_ramp_list_command: _CommandRunner,
) -> argparse.ArgumentParser:
    parser = JsonCliArgumentParser(
        prog="powers-tool",
        description="Safe Powers Tool CLI for supported DC power supplies.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"powers-tool {version_provider()}",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=JsonCliArgumentParser,
    )

    list_parser = subparsers.add_parser(
        "list-resources",
        help="List VISA resource strings reported by the selected backend.",
    )
    _add_json_argument(list_parser)
    _add_simulate_argument(list_parser)
    _add_backend_argument(list_parser)
    _add_timeout_argument(list_parser)
    _add_serial_arguments(list_parser)
    list_parser.add_argument(
        "--live-only",
        action="store_true",
        help="Only print resources that can be opened and queried with *IDN?.",
    )
    list_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses used for live checks.",
    )
    list_parser.set_defaults(func=run_list_resources)

    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify that one VISA resource can be opened and queried with *IDN?.",
    )
    verify_parser.add_argument("--resource", required=True, help="VISA resource string.")
    _add_json_argument(verify_parser)
    _add_simulate_argument(verify_parser)
    _add_model_argument(verify_parser)
    _add_backend_argument(verify_parser)
    _add_timeout_argument(verify_parser)
    _add_serial_arguments(verify_parser)
    verify_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print the SCPI command and response for the verification query.",
    )
    verify_parser.set_defaults(func=run_verify)

    clear_parser = subparsers.add_parser(
        "clear",
        help="Clear instrument status and error queue with *CLS.",
    )
    _add_resource_argument(clear_parser)
    _add_json_argument(clear_parser)
    _add_simulate_argument(clear_parser)
    _add_dry_run_argument(clear_parser)
    _add_backend_argument(clear_parser)
    _add_timeout_argument(clear_parser)
    _add_serial_arguments(clear_parser)
    clear_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print the SCPI clear command.",
    )
    clear_parser.set_defaults(func=run_clear)

    error_parser = subparsers.add_parser(
        "error",
        help="Read the instrument error queue with SYST:ERR?.",
    )
    _add_resource_argument(error_parser)
    _add_json_argument(error_parser)
    _add_simulate_argument(error_parser)
    _add_backend_argument(error_parser)
    _add_timeout_argument(error_parser)
    _add_serial_arguments(error_parser)
    error_parser.add_argument(
        "--max-reads",
        type=_positive_max_reads,
        default=20,
        help="Maximum error queue reads before stopping.",
    )
    error_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses used for the error query.",
    )
    error_parser.set_defaults(func=run_error)

    measure_parser = subparsers.add_parser(
        "measure",
        help="Query measured voltage and current for the selected channel.",
    )
    _add_resource_argument(measure_parser)
    measure_parser.add_argument(
        "--channel",
        required=True,
        type=_positive_channel,
        help=(
            "Positive integer output channel. Real mode allows channel 1 for "
            "the generic path and model-specific measured channels after *IDN?."
        ),
    )
    _add_json_argument(measure_parser)
    _add_simulate_argument(measure_parser)
    _add_validation_support_policy_argument(measure_parser)
    _add_backend_argument(measure_parser)
    _add_timeout_argument(measure_parser)
    _add_serial_arguments(measure_parser)
    measure_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses used for measurements.",
    )
    measure_parser.set_defaults(func=run_measure)

    measure_all_parser = subparsers.add_parser(
        "measure-all",
        help="Query measured voltage and current for all E36312A channels.",
    )
    _add_output_resource_arguments(measure_all_parser)
    _add_json_argument(measure_all_parser)
    _add_simulate_argument(measure_all_parser)
    _add_dry_run_argument(measure_all_parser)
    _add_model_argument(measure_all_parser)
    _add_safety_config_argument(measure_all_parser)
    _add_backend_argument(measure_all_parser)
    _add_timeout_argument(measure_all_parser)
    measure_all_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses used for measurements.",
    )
    measure_all_parser.set_defaults(func=run_measure_all)

    from powers_tool_cli.commands import output as output_commands
    from powers_tool_cli.commands import trigger as trigger_commands

    output_commands.register_commands(subparsers, run_output_plan=run_output_plan)
    trigger_commands.register_commands(subparsers, run_core_trigger=run_core_trigger)

    status_parser = subparsers.add_parser(
        "read-status",
        help="Read error queue and selected channel output state(s).",
    )
    _add_output_resource_arguments(status_parser)
    status_parser.add_argument(
        "--channel",
        default="all",
        type=_status_channel,
        help="Positive integer output channel or 'all'.",
    )
    status_parser.add_argument(
        "--all",
        action="store_true",
        help="Read all E36312A output channels.",
    )
    status_parser.add_argument(
        "--max-errors",
        type=_positive_max_errors,
        default=20,
        help="Maximum error queue reads before stopping.",
    )
    _add_json_argument(status_parser)
    _add_simulate_argument(status_parser)
    _add_safety_config_argument(status_parser)
    _add_backend_argument(status_parser)
    _add_timeout_argument(status_parser)
    _add_serial_arguments(status_parser)
    status_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    status_parser.set_defaults(func=run_status)

    validate_readonly_parser = subparsers.add_parser(
        "validate-readonly",
        help="Run one read-only validation pass for E36312A or EDU36311A resources.",
    )
    _add_output_resource_arguments(validate_readonly_parser)
    validate_readonly_parser.add_argument(
        "--max-errors",
        type=_positive_max_errors,
        default=20,
        help="Maximum error queue reads before stopping.",
    )
    _add_json_argument(validate_readonly_parser)
    _add_simulate_argument(validate_readonly_parser)
    _add_safety_config_argument(validate_readonly_parser)
    _add_backend_argument(validate_readonly_parser)
    _add_timeout_argument(validate_readonly_parser)
    validate_readonly_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    validate_readonly_parser.set_defaults(func=run_validate_readonly)

    readback_parser = subparsers.add_parser(
        "readback",
        help="Read programmed voltage and current setpoints for E36312A channels.",
    )
    _add_output_resource_arguments(readback_parser)
    _add_channel_or_all_argument(readback_parser)
    _add_json_argument(readback_parser)
    _add_simulate_argument(readback_parser)
    _add_safety_config_argument(readback_parser)
    _add_backend_argument(readback_parser)
    _add_timeout_argument(readback_parser)
    _add_serial_arguments(readback_parser)
    readback_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    readback_parser.set_defaults(func=run_readback)

    protection_parser = subparsers.add_parser(
        "protection-status",
        help="Read E36312A protection trip flags and output states.",
    )
    _add_output_resource_arguments(protection_parser)
    _add_channel_or_all_argument(protection_parser)
    _add_json_argument(protection_parser)
    _add_simulate_argument(protection_parser)
    _add_safety_config_argument(protection_parser)
    _add_backend_argument(protection_parser)
    _add_timeout_argument(protection_parser)
    protection_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    protection_parser.set_defaults(func=run_protection_status)

    protection_set_parser = subparsers.add_parser(
        "protection-set",
        help="Set E36312A over-voltage and over-current protection parameters.",
    )
    _add_output_resource_arguments(protection_set_parser)
    _add_channel_or_all_argument(protection_set_parser)
    protection_set_parser.add_argument(
        "--ovp-voltage",
        type=float,
        help="Over-voltage protection level.",
    )
    protection_set_parser.add_argument(
        "--ocp",
        choices=("on", "off"),
        help="Enable or disable over-current protection.",
    )
    protection_set_parser.add_argument(
        "--ocp-delay",
        type=float,
        help="Over-current protection delay in seconds.",
    )
    protection_set_parser.add_argument(
        "--ocp-delay-trigger",
        choices=("setting-change", "cc-transition"),
        help="Event that starts the over-current protection delay timer.",
    )
    protection_set_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm real hardware protection setup.",
    )
    _add_json_argument(protection_set_parser)
    _add_simulate_argument(protection_set_parser)
    _add_dry_run_argument(protection_set_parser)
    _add_model_argument(protection_set_parser)
    _add_safety_config_argument(protection_set_parser)
    _add_backend_argument(protection_set_parser)
    _add_timeout_argument(protection_set_parser)
    protection_set_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    protection_set_parser.set_defaults(func=run_protection_set)

    clear_protection_parser = subparsers.add_parser(
        "clear-protection",
        help="Clear E36312A output protection for one channel or all channels.",
    )
    _add_output_resource_arguments(clear_protection_parser)
    clear_protection_parser.add_argument(
        "--channel",
        default=None,
        type=_status_channel,
        help="Positive integer output channel or 'all'.",
    )
    clear_protection_parser.add_argument(
        "--all",
        action="store_true",
        help="Clear protection on all E36312A output channels.",
    )
    clear_protection_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm real hardware protection clearing.",
    )
    _add_json_argument(clear_protection_parser)
    _add_simulate_argument(clear_protection_parser)
    _add_dry_run_argument(clear_protection_parser)
    _add_model_argument(clear_protection_parser)
    _add_safety_config_argument(clear_protection_parser)
    _add_backend_argument(clear_protection_parser)
    _add_timeout_argument(clear_protection_parser)
    clear_protection_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    clear_protection_parser.set_defaults(func=run_clear_protection)

    identify_parser = subparsers.add_parser(
        "identify",
        help="Read instrument identity and supported model-specific identity details.",
    )
    _add_output_resource_arguments(identify_parser)
    _add_json_argument(identify_parser)
    _add_simulate_argument(identify_parser)
    _add_model_argument(identify_parser)
    _add_safety_config_argument(identify_parser)
    _add_backend_argument(identify_parser)
    _add_timeout_argument(identify_parser)
    _add_serial_arguments(identify_parser)
    identify_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    identify_parser.set_defaults(func=run_identify)

    snapshot_parser = subparsers.add_parser(
        "snapshot",
        help="Read E36312A errors, outputs, readback, measurements, and protection flags.",
    )
    _add_output_resource_arguments(snapshot_parser)
    snapshot_parser.add_argument(
        "--max-errors",
        type=_positive_max_errors,
        default=20,
        help="Maximum error queue reads before stopping.",
    )
    snapshot_parser.add_argument("--compare", help="Compare snapshot against a saved JSON envelope or raw data snapshot.")
    snapshot_parser.add_argument("--setpoint-voltage-tolerance", type=float, default=0.001, help="Snapshot compare setpoint voltage tolerance in volts.")
    snapshot_parser.add_argument("--setpoint-current-tolerance", type=float, default=0.001, help="Snapshot compare setpoint current tolerance in amps.")
    snapshot_parser.add_argument("--measured-voltage-tolerance", type=float, default=0.05, help="Snapshot compare measured voltage tolerance in volts.")
    snapshot_parser.add_argument("--measured-current-tolerance", type=float, default=0.01, help="Snapshot compare measured current tolerance in amps.")
    snapshot_parser.add_argument("--redact-resource", action="store_true", help="Redact the VISA resource string in JSON snapshot data.")
    snapshot_parser.add_argument(
        "--snapshot-json",
        help="Write the raw schema-2 powers-tool-snapshot document to a UTF-8 JSON file.",
    )
    _add_json_argument(snapshot_parser)
    _add_simulate_argument(snapshot_parser)
    _add_model_argument(snapshot_parser)
    _add_safety_config_argument(snapshot_parser)
    _add_backend_argument(snapshot_parser)
    _add_timeout_argument(snapshot_parser)
    snapshot_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    snapshot_parser.set_defaults(func=run_snapshot)

    snapshot_diff_parser = subparsers.add_parser(
        "snapshot-diff",
        help="Compare two saved snapshot JSON files without opening VISA.",
    )
    snapshot_diff_parser.add_argument("--before", required=True, help="Before snapshot JSON path.")
    snapshot_diff_parser.add_argument("--after", required=True, help="After snapshot JSON path.")
    snapshot_diff_parser.add_argument("--summary", action="store_true", help="Include category change counts and shorten human output.")
    _add_json_argument(snapshot_diff_parser)
    snapshot_diff_parser.set_defaults(func=run_snapshot_diff)

    hardware_report_parser = subparsers.add_parser(
        "hardware-report",
        help="Build an offline hardware validation report from saved JSON artifacts.",
    )
    hardware_report_parser.add_argument("--input-dir", required=True, help="Directory containing command JSON artifacts.")
    hardware_report_parser.add_argument("--target", required=True, help="Target model name.")
    hardware_report_parser.add_argument("--connection", required=True, help="Connection type, such as USB.")
    hardware_report_parser.add_argument("--resource", required=True, help="VISA resource string that was tested.")
    hardware_report_parser.add_argument("--report-json", required=True, help="Report JSON output path.")
    hardware_report_parser.add_argument("--summary-md", required=True, help="Markdown summary output path.")
    hardware_report_parser.add_argument("--before-json", help="Optional before snapshot JSON path.")
    hardware_report_parser.add_argument("--after-json", help="Optional after snapshot JSON path.")
    _add_json_argument(hardware_report_parser)
    hardware_report_parser.set_defaults(func=run_hardware_report)

    restore_parser = subparsers.add_parser(
        "restore-from-snapshot",
        help="Restore selected supported-model channel settings from a saved snapshot.",
    )
    restore_parser.add_argument("--snapshot", required=True, help="Snapshot JSON path.")
    _add_resource_argument(restore_parser)
    restore_parser.add_argument(
        "--channel",
        required=True,
        type=_status_channel,
        help="Positive integer output channel or 'all'.",
    )
    restore_parser.add_argument(
        "--restore-output-state",
        action="store_true",
        help="Restore channels that were ON in the snapshot; requires --confirm in real mode.",
    )
    restore_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm real restore execution.",
    )
    _add_json_argument(restore_parser)
    _add_simulate_argument(restore_parser)
    _add_dry_run_argument(restore_parser)
    _add_validation_support_policy_argument(restore_parser)
    _add_model_argument(restore_parser)
    restore_parser.add_argument("--plan-json", help="Write the dry-run restore plan data to a JSON file. Requires --dry-run.")
    _add_backend_argument(restore_parser)
    _add_timeout_argument(restore_parser)
    restore_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    restore_parser.set_defaults(func=run_restore_from_snapshot)

    log_parser = subparsers.add_parser(
        "log",
        help="Log read-only channel telemetry to CSV.",
    )
    _add_output_resource_arguments(log_parser)
    log_channel_group = log_parser.add_mutually_exclusive_group(required=True)
    log_channel_group.add_argument(
        "--channel",
        type=_log_channel,
        help="Positive integer output channel, or 'all'.",
    )
    log_channel_group.add_argument(
        "--channels",
        type=_channels_list,
        help="Comma-separated positive output channels.",
    )
    log_parser.add_argument(
        "--interval-sec",
        required=True,
        type=_positive_float,
        help="Seconds between samples.",
    )
    log_parser.add_argument("--csv", required=True, help="CSV output path.")
    log_parser.add_argument("--jsonl", help="Optional JSONL output path.")
    log_parser.add_argument(
        "--append",
        action="store_true",
        help="Append to an existing CSV/JSONL file.",
    )
    log_parser.add_argument(
        "--samples",
        type=_positive_int,
        help="Number of samples to collect.",
    )
    log_parser.add_argument(
        "--duration-sec",
        type=_positive_float,
        help="Collection duration in seconds.",
    )
    _add_json_argument(log_parser)
    _add_simulate_argument(log_parser)
    _add_model_argument(log_parser)
    _add_safety_config_argument(log_parser)
    _add_backend_argument(log_parser)
    _add_timeout_argument(log_parser)
    log_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    log_parser.set_defaults(func=run_log)

    from powers_tool_cli.commands import sequence as sequence_command
    from powers_tool_cli.commands import ramp_list as ramp_list_command

    sequence_command.register_commands(subparsers, run_sequence_command=run_sequence_command)
    ramp_list_command.register_commands(subparsers, run_ramp_list_command=run_ramp_list_command)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Report Python, package, PyVISA, simulator, and backend diagnostics.",
    )
    _add_json_argument(doctor_parser)
    _add_simulate_argument(doctor_parser)
    _add_backend_argument(doctor_parser)
    _add_timeout_argument(doctor_parser)
    _add_validation_support_policy_argument(doctor_parser)
    _add_model_argument(doctor_parser)
    doctor_parser.add_argument("--resource", help="Optional resource to identify.")
    doctor_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    doctor_parser.set_defaults(func=run_doctor)

    capabilities_parser = subparsers.add_parser(
        "capabilities",
        help="Report selected driver capabilities for a resource.",
    )
    _add_output_resource_arguments(capabilities_parser)
    _add_json_argument(capabilities_parser)
    _add_simulate_argument(capabilities_parser)
    _add_backend_argument(capabilities_parser)
    _add_timeout_argument(capabilities_parser)
    capabilities_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    capabilities_parser.add_argument("--command", dest="selected_command", help="Select one command support entry.")
    capabilities_parser.set_defaults(func=run_capabilities)

    safety_parser = subparsers.add_parser(
        "safety",
        help="Inspect safety configuration.",
    )
    safety_subparsers = safety_parser.add_subparsers(
        dest="safety_command",
        required=True,
        parser_class=JsonCliArgumentParser,
    )
    safety_inspect_parser = safety_subparsers.add_parser(
        "inspect",
        help="Inspect effective safety limits for a resource or alias.",
    )
    _add_output_resource_arguments(safety_inspect_parser)
    safety_inspect_parser.add_argument("--channel", type=_positive_channel)
    safety_inspect_parser.add_argument("--model")
    _add_json_argument(safety_inspect_parser)
    _add_safety_config_argument(safety_inspect_parser)
    safety_inspect_parser.add_argument("--explain", action="store_true", help="Include per-field effective value and source details.")
    safety_inspect_parser.set_defaults(func=run_safety_inspect)

    from powers_tool_cli.commands import lifecycle as lifecycle_commands

    lifecycle_commands.register_commands(subparsers, run_worker_command=run_worker)

    return parser
