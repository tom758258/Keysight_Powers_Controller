from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import Any

import pytest

import powers_tool_cli.cli as cli
import powers_tool_cli.lifecycle_client as lifecycle_client
from powers_tool_cli.commands import inspection, lifecycle as lifecycle_commands


LIFECYCLE_COMMANDS = (
    "worker",
    "send-command",
    "status",
    "stop",
    "wait-ready",
)
TOP_LEVEL_COMMAND_ORDER = (
    "list-resources",
    "verify",
    "clear",
    "error",
    "measure",
    "measure-all",
    "set",
    "output-on",
    "output-off",
    "safe-off",
    "output-state",
    "cycle-output",
    "apply",
    "ramp",
    "smoke-output",
    "trigger-pulse",
    "trigger-status",
    "trigger-step",
    "trigger-list",
    "trigger-fire",
    "trigger-abort",
    "read-status",
    "validate-readonly",
    "readback",
    "protection-status",
    "protection-set",
    "clear-protection",
    "identify",
    "snapshot",
    "snapshot-diff",
    "hardware-report",
    "restore-from-snapshot",
    "log",
    "sequence",
    "ramp-list",
    "doctor",
    "capabilities",
    "safety",
    *LIFECYCLE_COMMANDS,
    "manifest",
)


def _action(
    option_strings: tuple[str, ...],
    dest: str,
    *,
    required: bool = False,
    default: object = None,
    type_name: str | None = None,
    choices: tuple[object, ...] | None = None,
    action_name: str = "_StoreAction",
    nargs: object = None,
    const: object = None,
    metavar: object = None,
    help: str,
) -> tuple[object, ...]:
    return (
        option_strings,
        dest,
        required,
        default,
        type_name,
        choices,
        action_name,
        nargs,
        const,
        metavar,
        help,
    )


HELP_ACTION = _action(
    ("-h", "--help"),
    "help",
    default=argparse.SUPPRESS,
    action_name="_HelpAction",
    nargs=0,
    help="show this help message and exit",
)
URL_ACTIONS = {
    path: (
        _action(("--url",), "url", help=f"Full Worker URL. Defaults to http://127.0.0.1:{{port}}{path}."),
        _action(("--host",), "host", default="127.0.0.1", help="Worker host."),
        _action(("--port",), "port", default=0, type_name="int", help="Worker port."),
    )
    for path in ("/command", "/status", "/stop")
}
TIMEOUT_ACTION = _action(
    ("--timeout-ms",),
    "timeout_ms",
    default=3000,
    type_name="_lifecycle_timeout_ms",
    help="HTTP timeout in milliseconds.",
)
FORMAT_ACTIONS = (
    _action(("--format",), "format", default="text", choices=("text", "json"), help="Output format."),
    _action(
        ("--json",),
        "json",
        default=False,
        action_name="_StoreTrueAction",
        nargs=0,
        const=True,
        help="Alias for --format json.",
    ),
)
DRY_RUN_ACTION = _action(
    ("--dry-run",),
    "dry_run",
    default=False,
    action_name="_StoreTrueAction",
    nargs=0,
    const=True,
    help="Validate and print request without HTTP.",
)

EXPECTED_ACTIONS = {
    "worker": (
        HELP_ACTION,
        _action(("--id",), "id", help="Worker ID."),
        _action(("--mode",), "mode", choices=("simulate", "live"), help="Execution mode."),
        _action(("--resource",), "resource", help="VISA resource string."),
        _action(("--control-port",), "control_port", type_name="int", help="Control HTTP port."),
        _action(("--artifacts-dir",), "artifacts_dir", help="Artifacts directory."),
        _action(("--config",), "config", help="Worker JSON config file."),
        _action(("--events-jsonl",), "events_jsonl", help="Events JSONL output file."),
    ),
    "send-command": (
        HELP_ACTION,
        *URL_ACTIONS["/command"],
        _action(("--command",), "worker_command", required=True, help="Power Worker command name."),
        _action(("--arguments-json",), "arguments_json", default="{}", help="JSON object for command arguments."),
        _action(("--context-json",), "context_json", required=True, help="JSON object for Worker execution context."),
        _action(("--job-id",), "job_id", help="Optional orchestrator job ID."),
        DRY_RUN_ACTION,
        TIMEOUT_ACTION,
        *FORMAT_ACTIONS,
    ),
    "status": (
        HELP_ACTION,
        *URL_ACTIONS["/status"],
        DRY_RUN_ACTION,
        TIMEOUT_ACTION,
        *FORMAT_ACTIONS,
    ),
    "stop": (
        HELP_ACTION,
        *URL_ACTIONS["/stop"],
        _action(("--reason",), "reason", default="manual stop", help="Stop reason."),
        TIMEOUT_ACTION,
        *FORMAT_ACTIONS,
    ),
    "wait-ready": (
        HELP_ACTION,
        *URL_ACTIONS["/status"],
        TIMEOUT_ACTION,
        _action(
            ("--wait-timeout-ms",),
            "wait_timeout_ms",
            default=30000,
            type_name="_lifecycle_timeout_ms",
            help="Overall wait timeout.",
        ),
        _action(
            ("--poll-ms",),
            "poll_ms",
            default=200,
            type_name="_positive_int",
            help="Polling interval in milliseconds.",
        ),
        *FORMAT_ACTIONS,
    ),
}
EXPECTED_RUNNERS = {
    "worker": inspection._run_worker,
    "send-command": lifecycle_commands.run_send_command,
    "status": lifecycle_commands.run_worker_status_client,
    "stop": lifecycle_commands.run_worker_stop_client,
    "wait-ready": lifecycle_commands.run_wait_ready_client,
}

EXPECTED_HELP = {
    "worker": """\
usage: powers-tool worker [-h] [--id ID] [--mode {simulate,live}]
                          [--resource RESOURCE] [--control-port CONTROL_PORT]
                          [--artifacts-dir ARTIFACTS_DIR] [--config CONFIG]
                          [--events-jsonl EVENTS_JSONL]

options:
  -h, --help            show this help message and exit
  --id ID               Worker ID.
  --mode {simulate,live}
                        Execution mode.
  --resource RESOURCE   VISA resource string.
  --control-port CONTROL_PORT
                        Control HTTP port.
  --artifacts-dir ARTIFACTS_DIR
                        Artifacts directory.
  --config CONFIG       Worker JSON config file.
  --events-jsonl EVENTS_JSONL
                        Events JSONL output file.
""",
    "send-command": """\
usage: powers-tool send-command [-h] [--url URL] [--host HOST] [--port PORT]
                                --command WORKER_COMMAND
                                [--arguments-json ARGUMENTS_JSON]
                                --context-json CONTEXT_JSON [--job-id JOB_ID]
                                [--dry-run] [--timeout-ms TIMEOUT_MS]
                                [--format {text,json}] [--json]

options:
  -h, --help            show this help message and exit
  --url URL             Full Worker URL. Defaults to
                        http://127.0.0.1:{port}/command.
  --host HOST           Worker host.
  --port PORT           Worker port.
  --command WORKER_COMMAND
                        Power Worker command name.
  --arguments-json ARGUMENTS_JSON
                        JSON object for command arguments.
  --context-json CONTEXT_JSON
                        JSON object for Worker execution context.
  --job-id JOB_ID       Optional orchestrator job ID.
  --dry-run             Validate and print request without HTTP.
  --timeout-ms TIMEOUT_MS
                        HTTP timeout in milliseconds.
  --format {text,json}  Output format.
  --json                Alias for --format json.
""",
    "status": """\
usage: powers-tool status [-h] [--url URL] [--host HOST] [--port PORT]
                          [--dry-run] [--timeout-ms TIMEOUT_MS]
                          [--format {text,json}] [--json]

options:
  -h, --help            show this help message and exit
  --url URL             Full Worker URL. Defaults to
                        http://127.0.0.1:{port}/status.
  --host HOST           Worker host.
  --port PORT           Worker port.
  --dry-run             Validate and print request without HTTP.
  --timeout-ms TIMEOUT_MS
                        HTTP timeout in milliseconds.
  --format {text,json}  Output format.
  --json                Alias for --format json.
""",
    "stop": """\
usage: powers-tool stop [-h] [--url URL] [--host HOST] [--port PORT]
                        [--reason REASON] [--timeout-ms TIMEOUT_MS]
                        [--format {text,json}] [--json]

options:
  -h, --help            show this help message and exit
  --url URL             Full Worker URL. Defaults to
                        http://127.0.0.1:{port}/stop.
  --host HOST           Worker host.
  --port PORT           Worker port.
  --reason REASON       Stop reason.
  --timeout-ms TIMEOUT_MS
                        HTTP timeout in milliseconds.
  --format {text,json}  Output format.
  --json                Alias for --format json.
""",
    "wait-ready": """\
usage: powers-tool wait-ready [-h] [--url URL] [--host HOST] [--port PORT]
                              [--timeout-ms TIMEOUT_MS]
                              [--wait-timeout-ms WAIT_TIMEOUT_MS]
                              [--poll-ms POLL_MS] [--format {text,json}]
                              [--json]

options:
  -h, --help            show this help message and exit
  --url URL             Full Worker URL. Defaults to
                        http://127.0.0.1:{port}/status.
  --host HOST           Worker host.
  --port PORT           Worker port.
  --timeout-ms TIMEOUT_MS
                        HTTP timeout in milliseconds.
  --wait-timeout-ms WAIT_TIMEOUT_MS
                        Overall wait timeout.
  --poll-ms POLL_MS     Polling interval in milliseconds.
  --format {text,json}  Output format.
  --json                Alias for --format json.
""",
}


def _lifecycle_subparsers() -> dict[str, argparse.ArgumentParser]:
    parser = cli.build_parser()
    action = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    assert tuple(action.choices) == TOP_LEVEL_COMMAND_ORDER
    return {command: action.choices[command] for command in LIFECYCLE_COMMANDS}


def _action_metadata(action: argparse.Action) -> tuple[object, ...]:
    return (
        tuple(action.option_strings),
        action.dest,
        action.required,
        action.default,
        getattr(action.type, "__name__", None),
        tuple(action.choices) if action.choices is not None else None,
        type(action).__name__,
        action.nargs,
        action.const,
        action.metavar,
        action.help,
    )


def _normalize_help(value: str) -> str:
    return value.replace("\r\n", "\n")


def test_lifecycle_registration_preserves_actions_order_and_runner_identity() -> None:
    subparsers = _lifecycle_subparsers()

    assert set(LIFECYCLE_COMMANDS) <= cli.COMMAND_NAMES
    for command, parser in subparsers.items():
        assert tuple(_action_metadata(action) for action in parser._actions) == EXPECTED_ACTIONS[command]
        assert parser._defaults == {"func": EXPECTED_RUNNERS[command]}


@pytest.mark.parametrize(
    ("argv", "expected", "runner"),
    [
        (
            ["worker"],
            {
                "command": "worker",
                "id": None,
                "mode": None,
                "resource": None,
                "control_port": None,
                "artifacts_dir": None,
                "config": None,
                "events_jsonl": None,
            },
            inspection._run_worker,
        ),
        (
            [
                "send-command",
                "--command",
                "read-status",
                "--context-json",
                '{"mode":"dry_run","planning_profile_id":"generic-scpi"}',
            ],
            {
                "command": "send-command",
                "url": None,
                "host": "127.0.0.1",
                "port": 0,
                "worker_command": "read-status",
                "arguments_json": "{}",
                "context_json": '{"mode":"dry_run","planning_profile_id":"generic-scpi"}',
                "job_id": None,
                "dry_run": False,
                "timeout_ms": 3000,
                "format": "text",
                "json": False,
            },
            lifecycle_commands.run_send_command,
        ),
        (
            ["status"],
            {
                "command": "status",
                "url": None,
                "host": "127.0.0.1",
                "port": 0,
                "dry_run": False,
                "timeout_ms": 3000,
                "format": "text",
                "json": False,
            },
            lifecycle_commands.run_worker_status_client,
        ),
        (
            ["stop"],
            {
                "command": "stop",
                "url": None,
                "host": "127.0.0.1",
                "port": 0,
                "reason": "manual stop",
                "timeout_ms": 3000,
                "format": "text",
                "json": False,
            },
            lifecycle_commands.run_worker_stop_client,
        ),
        (
            ["wait-ready"],
            {
                "command": "wait-ready",
                "url": None,
                "host": "127.0.0.1",
                "port": 0,
                "timeout_ms": 3000,
                "wait_timeout_ms": 30000,
                "poll_ms": 200,
                "format": "text",
                "json": False,
            },
            lifecycle_commands.run_wait_ready_client,
        ),
    ],
)
def test_lifecycle_parse_vectors_preserve_namespace_and_runner(
    argv: list[str],
    expected: dict[str, object],
    runner: Any,
) -> None:
    args = cli.build_parser().parse_args(argv)

    assert args.func is runner
    assert not hasattr(args, "_runtime")
    actual = vars(args).copy()
    actual.pop("func")
    assert actual == expected


def test_lifecycle_help_output_is_crlf_normalized_baseline() -> None:
    subparsers = _lifecycle_subparsers()

    for command, parser in subparsers.items():
        assert _normalize_help(parser.format_help()) == EXPECTED_HELP[command]


def test_lifecycle_parser_errors_preserve_json_envelope_and_do_not_dispatch(monkeypatch, capsys) -> None:
    def fail_dispatch(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("parser failure must not dispatch a lifecycle runner")

    monkeypatch.setattr(inspection, "_run_worker", fail_dispatch)
    for name in (
        "run_send_command",
        "run_worker_status_client",
        "run_worker_stop_client",
        "run_wait_ready_client",
    ):
        monkeypatch.setattr(lifecycle_commands, name, fail_dispatch)
    monkeypatch.setattr(lifecycle_client.urllib.request, "urlopen", fail_dispatch)

    assert cli.main(["send-command", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 2
    assert payload["status"] == "error"
    assert payload["ok"] is False
    assert payload["command"] == {"name": "send-command"}
    assert payload["execution"] == {"mode": "real", "dry_run": False, "hardware_touched": False}
    assert payload["request"] == {}
    assert payload["error"] == {
        "type": "validation",
        "code": "argument_error",
        "message": "the following arguments are required: --command, --context-json",
        "retryable": False,
    }

    assert cli.main(["send-command", "--command", "read-status", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["message"] == "the following arguments are required: --context-json"

    assert cli.main(["status", "--unknown-option", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["message"] == "unrecognized arguments: --unknown-option"

    assert cli.main(["status", "--json", "--format", "text"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "--json conflicts with --format text\n"


def test_lifecycle_module_import_is_parser_only() -> None:
    root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """\
        import sys
        sys.path.insert(0, r"{source}")
        import powers_tool_cli.commands.lifecycle
        assert "powers_tool_cli.worker" not in sys.modules
        """
    ).format(source=root / "src")

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
