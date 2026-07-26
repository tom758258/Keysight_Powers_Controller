"""Worker lifecycle command parser registration."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from powers_tool_cli import cli_parser as parser_helpers
from powers_tool_cli.lifecycle_client import (
    run_send_command,
    run_wait_ready_client,
    run_worker_status_client,
    run_worker_stop_client,
)


def register_commands(
    subparsers: argparse._SubParsersAction[Any],
    *,
    run_worker_command: Callable[[argparse.Namespace], int],
) -> None:
    worker_parser = subparsers.add_parser(
        "worker",
        help="Run the Powers Tool worker daemon.",
    )
    worker_parser.add_argument("--id", help="Worker ID.")
    worker_parser.add_argument("--mode", choices=["simulate", "live"], help="Execution mode.")
    worker_parser.add_argument("--resource", help="VISA resource string.")
    worker_parser.add_argument("--control-port", type=int, help="Control HTTP port.")
    worker_parser.add_argument("--artifacts-dir", help="Artifacts directory.")
    worker_parser.add_argument("--config", help="Worker JSON config file.")
    worker_parser.add_argument("--events-jsonl", help="Events JSONL output file.")
    worker_parser.set_defaults(func=run_worker_command)

    send_parser = subparsers.add_parser("send-command", help="Send a Worker POST /command request.")
    parser_helpers._add_lifecycle_url_argument(send_parser, default_path="/command")
    send_parser.add_argument("--command", dest="worker_command", required=True, help="Power Worker command name.")
    send_parser.add_argument("--arguments-json", default="{}", help="JSON object for command arguments.")
    send_parser.add_argument("--context-json", required=True, help="JSON object for Worker execution context.")
    send_parser.add_argument("--job-id", help="Optional orchestrator job ID.")
    send_parser.add_argument("--dry-run", action="store_true", help="Validate and print request without HTTP.")
    parser_helpers._add_lifecycle_timeout_argument(send_parser)
    parser_helpers._add_lifecycle_format_arguments(send_parser)
    send_parser.set_defaults(func=run_send_command)

    worker_status_parser = subparsers.add_parser("status", help="Read Worker GET /status.")
    parser_helpers._add_lifecycle_url_argument(worker_status_parser, default_path="/status")
    worker_status_parser.add_argument("--dry-run", action="store_true", help="Validate and print request without HTTP.")
    parser_helpers._add_lifecycle_timeout_argument(worker_status_parser)
    parser_helpers._add_lifecycle_format_arguments(worker_status_parser)
    worker_status_parser.set_defaults(func=run_worker_status_client)

    stop_parser = subparsers.add_parser("stop", help="Request Worker POST /stop.")
    parser_helpers._add_lifecycle_url_argument(stop_parser, default_path="/stop")
    stop_parser.add_argument("--reason", default="manual stop", help="Stop reason.")
    parser_helpers._add_lifecycle_timeout_argument(stop_parser)
    parser_helpers._add_lifecycle_format_arguments(stop_parser)
    stop_parser.set_defaults(func=run_worker_stop_client)

    wait_parser = subparsers.add_parser("wait-ready", help="Wait until Worker status is reachable and ready.")
    parser_helpers._add_lifecycle_url_argument(wait_parser, default_path="/status")
    parser_helpers._add_lifecycle_timeout_argument(wait_parser)
    wait_parser.add_argument("--wait-timeout-ms", type=parser_helpers._lifecycle_timeout_ms, default=30000, help="Overall wait timeout.")
    wait_parser.add_argument("--poll-ms", type=parser_helpers._positive_int, default=200, help="Polling interval in milliseconds.")
    parser_helpers._add_lifecycle_format_arguments(wait_parser)
    wait_parser.set_defaults(func=run_wait_ready_client)
