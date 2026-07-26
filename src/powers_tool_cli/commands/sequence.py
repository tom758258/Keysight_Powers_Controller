"""Sequence command parser registration and request shaping."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from functools import partial
from typing import Any, Callable

from powers_tool_cli import cli_parser as parser_helpers
from powers_tool_cli.request_primitives import (
    option_value,
    timeout_from_argv,
    with_serial_request_fields_from_argv,
)
from powers_tool_cli.runtime_mapping import (
    runtime_identity_for_args,
    serial_options_for_args,
    support_policy_mode_for_args,
    with_serial_request_fields,
)
from powers_tool_core.connection import DEFAULT_TIMEOUT_MS
from powers_tool_core.core import RuntimeOptions, SequenceRequest


REQUEST_FIELDS = (
    "resource",
    "resource_alias",
    "file",
    "safety_config",
    "backend",
    "timeout_ms",
    "serial_options",
    "serial_remote",
    "serial_local_on_close",
)


def register_commands(
    subparsers: argparse._SubParsersAction[Any],
    *,
    run_sequence_command: Callable[[argparse.Namespace], int],
) -> None:
    runtime = parser_helpers
    handler = partial(run_sequence, run_sequence_command=run_sequence_command)
    sequence_parser = subparsers.add_parser(
        "sequence",
        help="Run a conservative software sequence from a YAML or JSON file.",
    )
    runtime._add_output_resource_arguments(sequence_parser)
    sequence_parser.add_argument("--file", required=True, help="YAML or JSON sequence file.")
    sequence_parser.add_argument("--loop-count", type=runtime._loop_count, help="Total sequence iterations (1 to 10,000).")
    runtime._add_json_argument(sequence_parser)
    runtime._add_simulate_argument(sequence_parser)
    runtime._add_dry_run_argument(sequence_parser)
    runtime._add_model_argument(sequence_parser, allow_profile=True)
    sequence_parser.add_argument("--lint", action="store_true", help="Validate the sequence file without opening VISA or executing steps.")
    runtime._add_safety_config_argument(sequence_parser)
    runtime._add_backend_argument(sequence_parser)
    runtime._add_timeout_argument(sequence_parser)
    runtime._add_serial_arguments(sequence_parser)
    sequence_parser.add_argument(
        "--log-scpi",
        action="store_true",
        help="Print SCPI commands and responses to stderr.",
    )
    sequence_parser.set_defaults(func=handler)


def request_for_args(args: argparse.Namespace) -> dict[str, Any]:
    return with_serial_request_fields(args, {
        "resource": getattr(args, "resource", None),
        "resource_alias": getattr(args, "resource_alias", None),
        "file": getattr(args, "file", None),
        "safety_config": getattr(args, "safety_config", None),
        "backend": getattr(args, "backend", None),
        "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        "loop_count": getattr(args, "loop_count", None),
    })


def request_from_argv(argv: Sequence[str]) -> dict[str, Any]:
    return with_serial_request_fields_from_argv(argv, {
        "resource": option_value(argv, "--resource"),
        "resource_alias": option_value(argv, "--resource-alias"),
        "file": option_value(argv, "--file"),
        "safety_config": option_value(argv, "--safety-config"),
        "backend": option_value(argv, "--backend"),
        "timeout_ms": timeout_from_argv(argv),
        "loop_count": option_value(argv, "--loop-count"),
    })


def core_request_for_args(args: argparse.Namespace) -> SequenceRequest:
    return SequenceRequest(
        runtime=RuntimeOptions(
            resource=getattr(args, "resource", None),
            resource_alias=getattr(args, "resource_alias", None),
            safety_config=getattr(args, "safety_config", None),
            simulate=getattr(args, "simulate", False),
            dry_run=getattr(args, "dry_run", False),
            **runtime_identity_for_args(args),
            backend=getattr(args, "backend", None),
            timeout_ms=getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            log_scpi=getattr(args, "log_scpi", False),
            serial_options=serial_options_for_args(args),
            serial_remote=getattr(args, "serial_remote", False),
            serial_local_on_close=getattr(args, "serial_local_on_close", False),
            support_policy_mode=support_policy_mode_for_args(args),
        ),
        parameters={
            "file": getattr(args, "file", None),
            "lint": getattr(args, "lint", False),
            **({"loop_count": args.loop_count} if getattr(args, "loop_count", None) is not None else {}),
        },
    )


def run_sequence(
    args: argparse.Namespace,
    *,
    run_sequence_command: Callable[[argparse.Namespace], int],
) -> int:
    return run_sequence_command(args)
