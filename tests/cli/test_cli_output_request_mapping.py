from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

import powers_tool_cli.cli as cli
from powers_tool_cli.commands import output


OUTPUT_REQUEST_COMMANDS = (
    "set",
    "output-on",
    "output-off",
    "safe-off",
    "output-state",
    "cycle-output",
    "apply",
    "ramp",
    "smoke-output",
)


def _parsed_request(argv: list[str]) -> tuple[argparse.Namespace, dict[str, object]]:
    args = cli.build_parser().parse_args(argv)
    return args, output.request_for_args(args)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            ["set", "--channel", "1", "--voltage", "0"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": 1,
                "voltage": 0.0,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "settle_ms": 0,
                "verify_after_write": False,
                "setpoint_voltage_tolerance": 0.001,
                "setpoint_current_tolerance": 0.001,
            },
        ),
        (
            ["output-on", "--channel", "1"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": 1,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "settle_ms": 0,
                "verify_after_write": False,
                "setpoint_voltage_tolerance": 0.001,
                "setpoint_current_tolerance": 0.001,
            },
        ),
        (
            ["output-off", "--channel", "all"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": "all",
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "settle_ms": 0,
                "verify_after_write": False,
                "setpoint_voltage_tolerance": 0.001,
                "setpoint_current_tolerance": 0.001,
            },
        ),
        (
            ["safe-off", "--channel", "all"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": "all",
                "safety_config": None,
            },
        ),
        (
            ["output-state", "--channel", "all"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": "all",
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
            },
        ),
        (
            ["cycle-output", "--channel", "1"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": 1,
                "duration_ms": 500,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
            },
        ),
        (
            ["apply", "--channel", "all", "--voltage", "0", "--current", "0"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": "all",
                "voltage": 0.0,
                "current": 0.0,
                "no_output": False,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "settle_ms": 0,
                "verify_after_write": False,
                "setpoint_voltage_tolerance": 0.001,
                "setpoint_current_tolerance": 0.001,
            },
        ),
        (
            [
                "ramp",
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.5",
                "--current",
                "0",
            ],
            {
                "resource": None,
                "resource_alias": None,
                "channel": 1,
                "start_voltage": 0.0,
                "stop_voltage": 1.0,
                "step_voltage": 0.5,
                "current": 0.0,
                "delay_ms": 0,
                "enable_output": False,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "settle_ms": 0,
                "verify_after_write": False,
                "setpoint_voltage_tolerance": 0.001,
                "setpoint_current_tolerance": 0.001,
            },
        ),
        (
            ["smoke-output", "--channel", "1", "--voltage", "0", "--current", "0"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": 1,
                "voltage": 0.0,
                "current": 0.0,
                "duration_ms": 500,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
            },
        ),
    ],
)
def test_parsed_output_request_mappings_preserve_minimal_requests(
    argv: list[str],
    expected: dict[str, object],
) -> None:
    args, request = _parsed_request(argv)

    assert args.command in output.OUTPUT_REQUEST_COMMANDS
    assert request == expected
    assert list(request) == list(expected)


def test_parsed_output_request_mapping_preserves_optional_fields_order_and_input() -> None:
    argv = [
        "set",
        "--resource",
        "ASRL1::INSTR",
        "--channel",
        "1",
        "--voltage",
        "0",
        "--current",
        "0.05",
        "--safety-config",
        "limits.toml",
        "--backend",
        "@ivi",
        "--timeout-ms",
        "1234",
        "--settle-ms",
        "7",
        "--verify-after-write",
        "--setpoint-voltage-tolerance",
        "0.02",
        "--setpoint-current-tolerance",
        "0.03",
        "--completion-pulse-pins",
        "1,2",
        "--completion-pulse-polarity",
        "negative",
        "--completion-pulse-channel",
        "3",
        "--leave-trigger-configured",
        "--serial-baud-rate",
        "9600",
        "--serial-read-termination",
        "CRLF",
        "--serial-remote",
        "--model",
        "keysight-e36312a",
    ]
    args = cli.build_parser().parse_args(argv)
    before = vars(args).copy()

    request = output.request_for_args(args)

    assert request == {
        "resource": "ASRL1::INSTR",
        "resource_alias": None,
        "channel": 1,
        "voltage": 0.0,
        "current": 0.05,
        "safety_config": "limits.toml",
        "backend": "@ivi",
        "timeout_ms": 1234,
        "settle_ms": 7,
        "verify_after_write": True,
        "setpoint_voltage_tolerance": 0.02,
        "setpoint_current_tolerance": 0.03,
        "completion_pulse": {
            "pins": [1, 2],
            "polarity": "negative",
            "channel": 3,
            "leave_trigger_configured": True,
        },
        "serial_options": {"baud_rate": 9600, "read_termination": "\r\n"},
        "serial_remote": True,
    }
    assert list(request) == [
        "resource",
        "resource_alias",
        "channel",
        "voltage",
        "current",
        "safety_config",
        "backend",
        "timeout_ms",
        "settle_ms",
        "verify_after_write",
        "setpoint_voltage_tolerance",
        "setpoint_current_tolerance",
        "completion_pulse",
        "serial_options",
        "serial_remote",
    ]
    assert vars(args) == before
    assert argv[-2:] == ["--model", "keysight-e36312a"]
    assert "model" not in request
    assert "profile" not in request


def test_parsed_ramp_mapping_preserves_completion_timing_and_omits_loop_count() -> None:
    args, request = _parsed_request(
        [
            "ramp",
            "--channel",
            "1",
            "--start-voltage",
            "0",
            "--stop-voltage",
            "1",
            "--step-voltage",
            "0.5",
            "--current",
            "0.05",
            "--enable-output",
            "--loop-count",
            "2",
            "--completion-pulse-pins",
            "1",
            "--completion-pulse-timing",
            "loop",
        ]
    )

    assert request["enable_output"] is True
    assert request["completion_pulse"] == {
        "pins": [1],
        "polarity": "positive",
        "channel": None,
        "leave_trigger_configured": False,
        "timing": "loop",
    }
    assert "loop_count" not in request
    assert args.loop_count == 2


def test_ramp_channels_mapping_uses_existing_list_parser_and_is_mutually_exclusive() -> None:
    argv = [
        "ramp",
        "--channels",
        "1,2",
        "--start-voltage",
        "0",
        "--stop-voltage",
        "1",
        "--step-voltage",
        "0.5",
        "--current",
        "0.05",
    ]

    args, request = _parsed_request(argv)

    assert args.channels == (1, 2)
    assert request["channels"] == [1, 2]
    assert "channel" not in request
    assert output.request_from_argv("ramp", argv)["channels"] == [1, 2]
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([*argv, "--channel", "1"])


def test_json_safe_setpoint_values_and_drop_none_behavior_are_preserved() -> None:
    _, voltage_only = _parsed_request(["set", "--channel", "1", "--voltage", "nan"])
    _, current_only = _parsed_request(["set", "--channel", "1", "--current", "inf"])

    assert voltage_only["voltage"] == "nan"
    assert "current" not in voltage_only
    assert current_only["current"] == "inf"
    assert "voltage" not in current_only


@pytest.mark.parametrize(
    ("command", "argv", "expected"),
    [
        (
            "set",
            ["set", "--resource=ASRL1::INSTR", "--channel", "bad", "--voltage=bad", "--current", "0"],
            {
                "resource": "ASRL1::INSTR",
                "resource_alias": None,
                "channel": "bad",
                "voltage": "bad",
                "current": 0.0,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "settle_ms": 0,
                "verify_after_write": False,
                "setpoint_voltage_tolerance": 0.001,
                "setpoint_current_tolerance": 0.001,
            },
        ),
        (
            "output-on",
            ["output-on", "--channel=all", "--timeout-ms", "bad"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": "all",
                "safety_config": None,
                "backend": None,
                "timeout_ms": "bad",
                "settle_ms": 0,
                "verify_after_write": False,
                "setpoint_voltage_tolerance": 0.001,
                "setpoint_current_tolerance": 0.001,
            },
        ),
        (
            "output-off",
            ["output-off", "--channel", "1", "--verify-after-write"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": 1,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "settle_ms": 0,
                "verify_after_write": True,
                "setpoint_voltage_tolerance": 0.001,
                "setpoint_current_tolerance": 0.001,
            },
        ),
        (
            "safe-off",
            ["safe-off", "--channel", "1", "--completion-pulse-pins", "1,bad"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": 1,
                "safety_config": None,
                "completion_pulse": {
                    "pins": [1, "bad"],
                    "polarity": "positive",
                    "channel": None,
                    "leave_trigger_configured": False,
                },
            },
        ),
        (
            "apply",
            ["apply", "--channel", "ALL", "--voltage", "1", "--current", "bad", "--no-output"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": "all",
                "voltage": 1.0,
                "current": "bad",
                "no_output": True,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "settle_ms": 0,
                "verify_after_write": False,
                "setpoint_voltage_tolerance": 0.001,
                "setpoint_current_tolerance": 0.001,
            },
        ),
        (
            "ramp",
            [
                "ramp",
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "bad",
                "--current",
                "0.05",
                "--delay-ms",
                "bad",
                "--setpoint-voltage-tolerance",
                "0",
                "--loop-count",
                "2",
                "--completion-pulse-pins",
                "1",
                "--completion-pulse-timing",
                "loop",
            ],
            {
                "resource": None,
                "resource_alias": None,
                "channel": 1,
                "start_voltage": 0.0,
                "stop_voltage": 1.0,
                "step_voltage": "bad",
                "current": 0.05,
                "delay_ms": "bad",
                "enable_output": False,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "settle_ms": 0,
                "verify_after_write": False,
                "setpoint_voltage_tolerance": 0.001,
                "setpoint_current_tolerance": 0.001,
                "completion_pulse": {
                    "pins": [1],
                    "polarity": "positive",
                    "channel": None,
                    "leave_trigger_configured": False,
                },
            },
        ),
        (
            "smoke-output",
            ["smoke-output", "--channel", "1", "--voltage", "-1", "--current", "bad", "--duration-ms", "bad"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": 1,
                "voltage": -1.0,
                "current": "bad",
                "duration_ms": "bad",
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
            },
        ),
    ],
)
def test_raw_output_request_mappings_preserve_raw_values_and_order(
    command: str,
    argv: list[str],
    expected: dict[str, object],
) -> None:
    before = list(argv)

    request = output.request_from_argv(command, argv)

    assert request == expected
    assert list(request) == list(expected)
    assert argv == before


def test_raw_mapping_preserves_completion_path_differences() -> None:
    output_state = output.request_from_argv(
        "output-state",
        ["output-state", "--completion-pulse-pins", "1,bad"],
    )
    cycle_output = output.request_from_argv(
        "cycle-output",
        ["cycle-output", "--completion-pulse-pins", "1"],
    )

    assert output_state["completion_pulse"]["pins"] == [1, "bad"]
    assert "completion_pulse" not in cycle_output


def test_raw_mapping_preserves_missing_values_option_order_and_serial_fields() -> None:
    missing = output.request_from_argv("set", ["set", "--channel", "--voltage"])
    ordered = output.request_from_argv(
        "output-on",
        [
            "output-on",
            "--serial-read-termination=CRLF",
            "--channel=1",
            "--serial-remote",
            "--resource",
            "ASRL1::INSTR",
        ],
    )
    reordered = output.request_from_argv(
        "output-on",
        [
            "output-on",
            "--resource",
            "ASRL1::INSTR",
            "--serial-remote",
            "--channel=1",
            "--serial-read-termination=CRLF",
        ],
    )

    assert missing == {
        "resource": None,
        "resource_alias": None,
        "channel": None,
        "safety_config": None,
        "backend": None,
        "timeout_ms": 5000,
        "settle_ms": 0,
        "verify_after_write": False,
        "setpoint_voltage_tolerance": 0.001,
        "setpoint_current_tolerance": 0.001,
    }
    assert ordered == reordered
    assert ordered["serial_options"] == {"read_termination": "\r\n"}
    assert ordered["serial_remote"] is True


@pytest.mark.parametrize(
    ("argv", "expected_request"),
    [
        (
            ["set", "--json", "--voltage", "bad"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": None,
                "voltage": "bad",
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "settle_ms": 0,
                "verify_after_write": False,
                "setpoint_voltage_tolerance": 0.001,
                "setpoint_current_tolerance": 0.001,
            },
        ),
        (
            ["output-on", "--json", "--channel", "bad"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": "bad",
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "settle_ms": 0,
                "verify_after_write": False,
                "setpoint_voltage_tolerance": 0.001,
                "setpoint_current_tolerance": 0.001,
            },
        ),
        (
            ["apply", "--json", "--channel", "1", "--voltage", "1"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": 1,
                "voltage": 1.0,
                "current": None,
                "no_output": False,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "settle_ms": 0,
                "verify_after_write": False,
                "setpoint_voltage_tolerance": 0.001,
                "setpoint_current_tolerance": 0.001,
            },
        ),
        (
            [
                "ramp",
                "--json",
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.5",
                "--current",
                "0.05",
                "--delay-ms",
                "bad",
            ],
            {
                "resource": None,
                "resource_alias": None,
                "channel": 1,
                "start_voltage": 0.0,
                "stop_voltage": 1.0,
                "step_voltage": 0.5,
                "current": 0.05,
                "delay_ms": "bad",
                "enable_output": False,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "settle_ms": 0,
                "verify_after_write": False,
                "setpoint_voltage_tolerance": 0.001,
                "setpoint_current_tolerance": 0.001,
            },
        ),
        (
            ["smoke-output", "--json", "--channel", "1", "--voltage", "1", "--current", "bad"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": 1,
                "voltage": 1.0,
                "current": "bad",
                "duration_ms": 500,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
            },
        ),
    ],
)
def test_output_parser_errors_keep_baseline_request_and_do_not_dispatch(
    monkeypatch,
    capsys,
    argv: list[str],
    expected_request: dict[str, object],
) -> None:
    def fail_dispatch(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("parser failures must not dispatch output execution")

    monkeypatch.setattr(cli, "_run_output_plan", fail_dispatch)
    monkeypatch.setattr(cli, "open_resource", fail_dispatch)

    assert cli.main(argv) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 2
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"] == expected_request
    assert payload["error"] == {
        "type": "validation",
        "code": "argument_error",
        "message": payload["error"]["message"],
        "retryable": False,
    }


def test_cli_delegates_output_mapping_and_keeps_ramp_list_independent(monkeypatch) -> None:
    parsed_sentinel = {"owner": "output"}
    raw_sentinel = {"owner": "output-raw"}
    ramp_list_sentinel = {"owner": "ramp-list"}
    calls: list[str] = []

    def parsed_mapper(args: argparse.Namespace) -> dict[str, str]:
        calls.append("parsed")
        assert args.command == "set"
        return parsed_sentinel

    def raw_mapper(command: str, argv: object) -> dict[str, str]:
        calls.append("raw")
        assert command == "set"
        assert argv == ["set"]
        return raw_sentinel

    from powers_tool_cli.commands import ramp_list

    monkeypatch.setattr(output, "request_for_args", parsed_mapper)
    monkeypatch.setattr(output, "request_from_argv", raw_mapper)
    monkeypatch.setattr(ramp_list, "request_for_args", lambda args: ramp_list_sentinel)

    assert cli._request_for_args(argparse.Namespace(command="set")) is parsed_sentinel
    assert cli._request_from_argv("set", ["set"]) is raw_sentinel
    assert cli._request_for_args(argparse.Namespace(command="ramp-list")) is ramp_list_sentinel
    assert calls == ["parsed", "raw"]


def test_output_request_command_ownership_is_explicit() -> None:
    assert output.OUTPUT_REQUEST_COMMANDS == frozenset(OUTPUT_REQUEST_COMMANDS)
    assert output.OUTPUT_REQUEST_COMMANDS < output.OUTPUT_COMMANDS
    assert "ramp-list" in output.OUTPUT_COMMANDS
    assert "ramp-list" not in output.OUTPUT_REQUEST_COMMANDS


def test_output_module_import_has_no_cli_or_worker_side_effect() -> None:
    root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """\
        import sys
        sys.path.insert(0, r"{source}")
        import powers_tool_cli.commands.output
        assert "powers_tool_cli.cli" not in sys.modules
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
