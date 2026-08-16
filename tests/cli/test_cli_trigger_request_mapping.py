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
import powers_tool_cli.cli_parser as cli_parser
import powers_tool_cli.cli_request as cli_request
import powers_tool_cli.cli_runtime as cli_runtime
from powers_tool_cli.commands import output, ramp_list, sequence, trigger


TRIGGER_COMMANDS = (
    "trigger-pulse",
    "trigger-status",
    "trigger-step",
    "trigger-list",
    "trigger-fire",
    "trigger-abort",
)


_ARGUMENT_ERROR_MESSAGES = {
    "missing_required": "one of the arguments --pin --pins is required",
    "invalid_typed": "argument --channel: channel must be a positive integer",
    "mutually_exclusive": "argument --pins: not allowed with argument --pin",
    "unknown_option": "unrecognized arguments: --unknown-option",
    "invalid_bost_list": (
        "argument --bost-list: boolean lists accept true/false, on/off, or 1/0"
    ),
}


def _parsed_request(argv: list[str]) -> tuple[argparse.Namespace, dict[str, object]]:
    args = cli.build_parser().parse_args(argv)
    return args, trigger.request_for_args(args)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            ["trigger-pulse", "--pin", "1"],
            {
                "resource": None,
                "resource_alias": None,
                "pins": [1],
                "channel": 1,
                "polarity": "positive",
                "exclusive_pins": False,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "pin": 1,
                "exclusive_pin": False,
            },
        ),
        (
            ["trigger-status"],
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
            ["trigger-step", "--channel", "1"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": 1,
                "source": "bus",
                "voltage": None,
                "current": None,
                "fire": False,
                "wait_complete": False,
                "wait_timeout_ms": None,
                "poll_ms": 200,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
            },
        ),
        (
            ["trigger-list"],
            {
                "resource": None,
                "resource_alias": None,
                "file": None,
                "channel": None,
                "source": "bus",
                "voltage_list": None,
                "current_list": None,
                "dwell_list": None,
                "bost_list": None,
                "eost_list": None,
                "trigger_output_pins": None,
                "trigger_output_polarity": None,
                "count": 1,
                "fire": False,
                "wait_complete": False,
                "wait_timeout_ms": None,
                "poll_ms": 200,
                "exclusive_pins": False,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
            },
        ),
        (
            ["trigger-fire"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": None,
                "wait_complete": False,
                "wait_timeout_ms": None,
                "poll_ms": 200,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
            },
        ),
        (
            ["trigger-abort", "--channel", "all"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": "all",
                "max_errors": 20,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
            },
        ),
    ],
)
def test_parsed_trigger_request_mappings_preserve_minimal_requests(
    argv: list[str],
    expected: dict[str, object],
) -> None:
    args, request = _parsed_request(argv)

    assert args.command in trigger.TRIGGER_COMMANDS
    assert request == expected
    assert list(request) == list(expected)


def test_parsed_trigger_list_mapping_copies_lists_and_keeps_metadata_separate() -> None:
    argv = [
        "trigger-list",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--voltage-list",
        "0,1",
        "--current-list",
        "0.05",
        "--dwell-list",
        "0.01,0.02",
        "--bost-list",
        "on,off",
        "--eost-list",
        "off,on",
        "--trigger-output-pins",
        "1,3",
        "--trigger-output-polarity",
        "negative",
        "--source",
        "immediate",
        "--fire",
        "--wait-complete",
        "--wait-timeout-ms",
        "1000",
        "--poll-ms",
        "50",
        "--exclusive-pins",
        "--completion-pulse-pins",
        "2",
        "--completion-pulse-polarity",
        "negative",
        "--completion-pulse-channel",
        "3",
        "--leave-trigger-configured",
        "--safety-config",
        "limits.toml",
        "--backend",
        "@ivi",
        "--timeout-ms",
        "1234",
        "--model",
        "keysight-e36312a",
    ]
    args = cli.build_parser().parse_args(argv)
    before = vars(args).copy()

    request = trigger.request_for_args(args)

    assert request == {
        "resource": "USB0::SIM::E36312A::INSTR",
        "resource_alias": None,
        "file": None,
        "channel": 1,
        "source": "immediate",
        "voltage_list": [0.0, 1.0],
        "current_list": [0.05],
        "dwell_list": [0.01, 0.02],
        "bost_list": [True, False],
        "eost_list": [False, True],
        "trigger_output_pins": [1, 3],
        "trigger_output_polarity": "negative",
        "count": 1,
        "fire": True,
        "wait_complete": True,
        "wait_timeout_ms": 1000,
        "poll_ms": 50,
        "exclusive_pins": True,
        "safety_config": "limits.toml",
        "backend": "@ivi",
        "timeout_ms": 1234,
        "completion_pulse": {
            "pins": [2],
            "polarity": "negative",
            "channel": 3,
            "leave_trigger_configured": True,
        },
    }
    assert list(request) == [
        "resource",
        "resource_alias",
        "file",
        "channel",
        "source",
        "voltage_list",
        "current_list",
        "dwell_list",
        "bost_list",
        "eost_list",
        "trigger_output_pins",
        "trigger_output_polarity",
        "count",
        "fire",
        "wait_complete",
        "wait_timeout_ms",
        "poll_ms",
        "exclusive_pins",
        "safety_config",
        "backend",
        "timeout_ms",
        "completion_pulse",
    ]
    assert request["voltage_list"] is not args.voltage_list
    assert request["bost_list"] is not args.bost_list
    assert request["trigger_output_pins"] is not args.trigger_output_pins
    assert vars(args) == before
    assert "model" not in request
    assert "simulate" not in request
    assert "dry_run" not in request


def test_parsed_trigger_step_json_safe_numbers_and_fresh_requests() -> None:
    args = cli.build_parser().parse_args(
        [
            "trigger-step",
            "--channel",
            "1",
            "--voltage",
            "nan",
            "--current",
            "inf",
            "--source",
            "bus",
            "--fire",
            "--wait-complete",
            "--wait-timeout-ms",
            "500",
            "--poll-ms",
            "75",
        ]
    )

    first = trigger.request_for_args(args)
    second = trigger.request_for_args(args)

    assert first["voltage"] == "nan"
    assert first["current"] == "inf"
    assert first["fire"] is True
    assert first["wait_complete"] is True
    assert first["wait_timeout_ms"] == 500
    assert first["poll_ms"] == 75
    assert first is not second
    assert first == second


def test_parsed_trigger_pulse_multiple_pins_has_no_single_pin_fields() -> None:
    args, request = _parsed_request(
        ["trigger-pulse", "--pins", "1,3", "--channel", "2", "--exclusive-pin"]
    )

    assert request["pins"] == [1, 3]
    assert request["channel"] == 2
    assert request["exclusive_pins"] is True
    assert "pin" not in request
    assert "exclusive_pin" not in request
    assert args.pins == (1, 3)


@pytest.mark.parametrize(
    ("command", "argv", "expected"),
    [
        (
            "trigger-pulse",
            [
                "trigger-pulse",
                "--pin=2",
                "--pins",
                "1,bad",
                "--channel",
                "0",
                "--polarity=",
                "--exclusive-pins",
                "--timeout-ms=bad",
            ],
            {
                "resource": None,
                "resource_alias": None,
                "pins": [1, "bad"],
                "channel": 1,
                "polarity": "positive",
                "exclusive_pins": True,
                "safety_config": None,
                "backend": None,
                "timeout_ms": "bad",
                "pin": 2,
                "exclusive_pin": True,
            },
        ),
        (
            "trigger-status",
            ["trigger-status", "--channel=ALL", "--backend", "@ivi"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": "all",
                "safety_config": None,
                "backend": "@ivi",
                "timeout_ms": 5000,
            },
        ),
        (
            "trigger-step",
            [
                "trigger-step",
                "--channel",
                "bad",
                "--source=",
                "--voltage",
                "bad",
                "--current=nan",
                "--fire",
                "--wait-complete",
                "--wait-timeout-ms",
                "bad",
                "--poll-ms=0",
                "--completion-pulse-pins",
                "1,bad",
            ],
            {
                "resource": None,
                "resource_alias": None,
                "channel": "bad",
                "source": "bus",
                "voltage": "bad",
                "current": "nan",
                "fire": True,
                "wait_complete": True,
                "wait_timeout_ms": "bad",
                "poll_ms": 0,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "completion_pulse": {
                    "pins": [1, "bad"],
                    "polarity": "positive",
                    "channel": None,
                    "leave_trigger_configured": False,
                },
            },
        ),
        (
            "trigger-list",
            [
                "trigger-list",
                "--file=plan.json",
                "--channel",
                "0",
                "--voltage-list",
                "0,bad,",
                "--current-list=-1",
                "--dwell-list",
                "0.01",
                "--count=bad",
                "--fire",
                "--wait-complete",
                "--wait-timeout-ms",
                "bad",
                "--poll-ms=0",
                "--exclusive-pins",
                "--completion-pulse-pins=1,bad",
            ],
            {
                "resource": None,
                "resource_alias": None,
                "file": "plan.json",
                "channel": 0,
                "source": "bus",
                "voltage_list": [0.0, "bad", ""],
                "current_list": [-1.0],
                "dwell_list": [0.01],
                "count": "bad",
                "fire": True,
                "wait_complete": True,
                "wait_timeout_ms": "bad",
                "poll_ms": 0,
                "exclusive_pins": True,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "completion_pulse": {
                    "pins": [1, "bad"],
                    "polarity": "positive",
                    "channel": None,
                    "leave_trigger_configured": False,
                },
            },
        ),
        (
            "trigger-fire",
            ["trigger-fire", "--channel=0", "--wait-complete", "--wait-timeout-ms", "bad", "--poll-ms=0"],
            {
                "resource": None,
                "resource_alias": None,
                "channel": 0,
                "wait_complete": True,
                "wait_timeout_ms": "bad",
                "poll_ms": 0,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
            },
        ),
        (
            "trigger-abort",
            ["trigger-abort", "--channel", "all", "--max-errors=bad", "--resource-alias", "bench"],
            {
                "resource": None,
                "resource_alias": "bench",
                "channel": "all",
                "max_errors": "bad",
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
            },
        ),
    ],
)
def test_raw_trigger_request_mappings_preserve_raw_values_and_order(
    command: str,
    argv: list[str],
    expected: dict[str, object],
) -> None:
    before = list(argv)

    request = trigger.request_from_argv(command, argv)

    assert request == expected
    assert list(request) == list(expected)
    assert argv == before


def test_raw_trigger_mapping_preserves_missing_values_and_option_order() -> None:
    missing = trigger.request_from_argv(
        "trigger-step",
        ["trigger-step", "--channel", "--voltage"],
    )
    ordered = trigger.request_from_argv(
        "trigger-pulse",
        ["trigger-pulse", "--resource", "ASRL1::INSTR", "--pin", "1", "--channel=1"],
    )
    reordered = trigger.request_from_argv(
        "trigger-pulse",
        ["trigger-pulse", "--channel=1", "--pin", "1", "--resource", "ASRL1::INSTR"],
    )

    assert missing["channel"] is None
    assert missing["voltage"] is None
    assert ordered == reordered


def test_trigger_list_parsed_and_raw_metadata_shapes_remain_distinct() -> None:
    args = cli.build_parser().parse_args(
        [
            "trigger-list",
            "--bost-list",
            "on,off",
            "--eost-list",
            "off,on",
            "--trigger-output-pins",
            "1",
            "--trigger-output-polarity",
            "negative",
        ]
    )
    parsed = trigger.request_for_args(args)
    raw = trigger.request_from_argv(
        "trigger-list",
        [
            "trigger-list",
            "--bost-list=on,off",
            "--eost-list=off,on",
            "--trigger-output-pins=1",
            "--trigger-output-polarity=negative",
        ],
    )

    assert parsed["bost_list"] == [True, False]
    assert parsed["eost_list"] == [False, True]
    assert parsed["trigger_output_pins"] == [1]
    assert parsed["trigger_output_polarity"] == "negative"
    assert {"bost_list", "eost_list", "trigger_output_pins", "trigger_output_polarity"}.isdisjoint(raw)


@pytest.mark.parametrize(
    "argv",
    [
        ["trigger-pulse", "--json"],
        ["trigger-step", "--json", "--channel", "bad"],
        ["trigger-list", "--json", "--count", "bad"],
        ["trigger-abort", "--json", "--channel", "1", "--unknown-option"],
    ],
)
def test_trigger_parser_errors_keep_raw_request_order_and_do_not_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    captured: list[dict[str, Any]] = []

    def capture_error(**kwargs: Any) -> None:
        captured.append(kwargs)

    def fail_dispatch(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("parser failures must not dispatch trigger execution")

    monkeypatch.setattr(cli_parser, "emit_json_error", capture_error)
    monkeypatch.setattr(cli, "_run_core_trigger", fail_dispatch)
    monkeypatch.setattr(cli_runtime, "open_resource", fail_dispatch)

    assert cli.main(argv) == 2

    assert len(captured) == 1
    payload = captured[0]
    command = argv[0]
    expected = trigger.request_from_argv(command, argv)
    assert payload["command"] == command
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"] == expected
    assert list(payload["request"]) == list(expected)
    assert payload["error_type"] == "validation"
    assert payload["code"] == "argument_error"
    assert payload["retryable"] is False


def test_trigger_parser_error_json_envelope_stays_machine_readable(capsys) -> None:
    assert cli.main(["trigger-step", "--json", "--channel", "bad"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 2
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["command"] == {"name": "trigger-step"}
    assert payload["request"] == trigger.request_from_argv(
        "trigger-step",
        ["trigger-step", "--json", "--channel", "bad"],
    )
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert payload["error"]["message"] == _ARGUMENT_ERROR_MESSAGES["invalid_typed"]
    assert payload["error"]["retryable"] is False


@pytest.mark.parametrize(
    ("argv", "expected_request", "message_key"),
    [
        pytest.param(
            ["trigger-pulse", "--json", "--pin", "1", "--pins", "2"],
            {
                "resource": None,
                "resource_alias": None,
                "pins": [2],
                "channel": 1,
                "polarity": "positive",
                "exclusive_pins": False,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
                "pin": 1,
                "exclusive_pin": False,
            },
            "mutually_exclusive",
            id="trigger-pulse-pin-and-pins",
        ),
        pytest.param(
            ["trigger-list", "--json", "--bost-list", "on,bad"],
            {
                "resource": None,
                "resource_alias": None,
                "file": None,
                "channel": None,
                "source": "bus",
                "voltage_list": None,
                "current_list": None,
                "dwell_list": None,
                "count": 1,
                "fire": False,
                "wait_complete": False,
                "wait_timeout_ms": None,
                "poll_ms": 200,
                "exclusive_pins": False,
                "safety_config": None,
                "backend": None,
                "timeout_ms": 5000,
            },
            "invalid_bost_list",
            id="trigger-list-invalid-bost-list",
        ),
    ],
)
def test_trigger_parser_errors_preserve_special_raw_requests_before_emission(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    expected_request: dict[str, object],
    message_key: str,
) -> None:
    captured: list[dict[str, Any]] = []
    emit_json_error = cli_parser.emit_json_error

    def capture_and_emit(**kwargs: Any) -> None:
        captured.append(kwargs)
        emit_json_error(**kwargs)

    def fail_dispatch(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("parser failures must not dispatch trigger execution")

    monkeypatch.setattr(cli_parser, "emit_json_error", capture_and_emit)
    monkeypatch.setattr(trigger, "run_trigger", fail_dispatch)
    monkeypatch.setattr(cli, "_run_core_trigger", fail_dispatch)
    monkeypatch.setattr(cli_runtime, "open_resource", fail_dispatch)
    monkeypatch.setattr(cli, "_log_scpi", fail_dispatch)

    assert cli.main(argv) == 2

    assert len(captured) == 1
    emitted = captured[0]
    assert emitted["command"] == argv[0]
    assert emitted["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert emitted["request"] == expected_request
    assert list(emitted["request"]) == list(expected_request)
    assert emitted["error_type"] == "validation"
    assert emitted["code"] == "argument_error"
    assert emitted["message"] == _ARGUMENT_ERROR_MESSAGES[message_key]
    assert emitted["retryable"] is False

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 2
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["command"] == {"name": argv[0]}
    assert payload["execution"] == emitted["execution"]
    assert payload["request"] == expected_request
    assert payload["error"] == {
        "type": "validation",
        "code": "argument_error",
        "message": _ARGUMENT_ERROR_MESSAGES[message_key],
        "retryable": False,
    }


@pytest.mark.parametrize(
    ("argv", "message_key"),
    [
        pytest.param(
            ["trigger-pulse", "--json"],
            "missing_required",
            id="missing-required",
        ),
        pytest.param(
            ["trigger-abort", "--json", "--channel", "1", "--unknown-option"],
            "unknown_option",
            id="unknown-option",
        ),
    ],
)
def test_trigger_parser_error_messages_match_fixed_baselines(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    message_key: str,
) -> None:
    def fail_dispatch(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("parser failures must not dispatch trigger execution")

    monkeypatch.setattr(trigger, "run_trigger", fail_dispatch)
    monkeypatch.setattr(cli, "_run_core_trigger", fail_dispatch)
    monkeypatch.setattr(cli_runtime, "open_resource", fail_dispatch)
    monkeypatch.setattr(cli, "_log_scpi", fail_dispatch)

    assert cli.main(argv) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 2
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["command"] == {"name": argv[0]}
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert payload["error"]["message"] == _ARGUMENT_ERROR_MESSAGES[message_key]
    assert payload["error"]["retryable"] is False


def test_cli_delegates_trigger_mapping_and_keeps_other_families_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed_sentinel = {"owner": "trigger"}
    raw_sentinel = {"owner": "trigger-raw"}
    output_sentinel = {"owner": "output"}
    ramp_list_sentinel = {"owner": "ramp-list"}
    sequence_sentinel = {"owner": "sequence"}
    calls: list[str] = []

    def parsed_mapper(args: argparse.Namespace) -> dict[str, str]:
        calls.append("parsed")
        assert args.command == "trigger-fire"
        return parsed_sentinel

    def raw_mapper(command: str, argv: object) -> dict[str, str]:
        calls.append("raw")
        assert command == "trigger-fire"
        assert argv == ["trigger-fire"]
        return raw_sentinel

    monkeypatch.setattr(trigger, "request_for_args", parsed_mapper)
    monkeypatch.setattr(trigger, "request_from_argv", raw_mapper)
    monkeypatch.setattr(output, "request_for_args", lambda args: output_sentinel)
    monkeypatch.setattr(ramp_list, "request_for_args", lambda args: ramp_list_sentinel)
    monkeypatch.setattr(sequence, "request_for_args", lambda args: sequence_sentinel)

    assert cli_request._request_for_args(argparse.Namespace(command="trigger-fire")) is parsed_sentinel
    assert cli_request._request_from_argv("trigger-fire", ["trigger-fire"]) is raw_sentinel
    assert cli_request._request_for_args(argparse.Namespace(command="set")) is output_sentinel
    assert cli_request._request_for_args(argparse.Namespace(command="ramp-list")) is ramp_list_sentinel
    assert cli_request._request_for_args(argparse.Namespace(command="sequence")) is sequence_sentinel
    assert calls == ["parsed", "raw"]


def test_trigger_command_ownership_is_explicit() -> None:
    assert trigger.TRIGGER_COMMANDS == frozenset(TRIGGER_COMMANDS)
    assert not hasattr(trigger, "TRIGGER_REQUEST_COMMANDS")


def test_trigger_module_import_has_no_cli_worker_or_core_execution_side_effect() -> None:
    root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """\
        import sys
        sys.path.insert(0, r"{source}")
        import powers_tool_cli.commands.trigger
        assert "powers_tool_cli.cli" not in sys.modules
        assert "powers_tool_cli.worker" not in sys.modules
        assert "powers_tool_core.trigger" not in sys.modules
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
