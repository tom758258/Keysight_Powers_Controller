import json
import csv
from types import SimpleNamespace

import pytest

import powers_tool_core.connection as connection
import powers_tool_cli.cli as cli
from powers_tool_core.core import CommandCancelled, CoreExecutionError, StopCleanupError
from powers_tool_core.errors import VisaConnectionError

from tests.cli.cli_test_helpers import (
    OUTPUT_RESOURCE,
    SERIAL_TERMINATION_ARGS,
    WRITE_VERIFICATION_REQUEST_DEFAULTS,
    FakeSession,
    assert_live_scope_rejected,
    expected_idn,
    expected_resource,
    output_command_args,
    write_safety_config,
    _all_trigger_snapshot_query_responses,
    _trigger_snapshot_query_responses,
)

def test_ramp_completion_over_100_steps_uses_software_without_warning(capsys) -> None:
    assert (
        cli.main(
            [
                "ramp",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.005",
                "--current",
                "0.05",
                "--completion-pulse-pins",
                "1",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["warnings"] == []
    assert payload["data"]["plan"]["trigger"]["native"] is False
    assert all("LIST:" not in str(step) for step in payload["data"]["plan"]["steps"])

@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--completion-pulse-mode", "native"),
        ("--completion-pulse-dwell-ms", "10"),
        ("--wait-timeout-ms", "1000"),
        ("--poll-ms", "200"),
    ],
)
def test_ramp_removed_native_completion_options_are_argparse_errors(capsys, option: str, value: str) -> None:
    assert (
        cli.main(
            [
                "ramp",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.005",
                "--current",
                "0.05",
                "--completion-pulse-pins",
                "1",
                option,
                value,
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "unrecognized arguments" in payload["error"]["message"]

def test_ramp_dry_run_completion_uses_software_steps(capsys) -> None:
    assert (
        cli.main(
            [
                "ramp",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
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
                "--completion-pulse-pins",
                "1",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert all("LIST:" not in str(step) for step in payload["data"]["plan"]["steps"])
    assert payload["data"]["plan"]["trigger"]["native"] is False

@pytest.mark.parametrize(
    "mode_args",
    [
        ["--dry-run", "--model", "keysight-edu36311a"],
        ["--dry-run", "--model", "keysight-e3646a"],
        ["--simulate", "--resource", "USB0::SIM::EDU36311A::INSTR"],
        ["--simulate", "--resource", "ASRL1::SIM::E3646A::INSTR"],
    ],
)
def test_cli_general_completion_pulse_no_hardware_uses_core_model_gate(
    capsys,
    mode_args: list[str],
) -> None:
    assert (
        cli.main(
            [
                "apply",
                "--json",
                *mode_args,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--completion-pulse-pins",
                "1",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "require planning_model_id 'keysight-e36312a'" in payload["error"]["message"]

def test_cli_general_completion_pulse_e36312a_plan_shape_stays_supported(capsys) -> None:
    assert (
        cli.main(
            [
                "apply",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--completion-pulse-pins",
                "1",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == [
        "set_current_limit",
        "set_voltage",
        "output_on",
        "completion_pulse",
    ]

def test_ramp_dry_run_json_plans_setpoint_only_steps(capsys) -> None:
    assert (
        cli.main(
            [
                "ramp",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
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
                "10",
                "--settle-ms",
                "20",
                "--verify-after-write",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    actions = [step["action"] for step in payload["data"]["plan"]["steps"]]
    assert actions == [
        "set_current_limit",
        "set_voltage",
        "sleep",
        "set_voltage",
        "sleep",
        "set_voltage",
        "sleep",
        "programmed_voltage",
        "programmed_current",
    ]
    assert "output_on" not in actions
    assert "output_off" not in actions
    assert payload["data"]["plan"]["steps"][5]["parameters"]["voltage"] == 1.0
    assert payload["data"]["plan"]["loop_count"] == 1

@pytest.mark.parametrize("value", ["1", "10000"])
@pytest.mark.parametrize(
    "argv",
    [
        ["ramp", "--channel", "1", "--start-voltage", "0", "--stop-voltage", "1", "--step-voltage", "1", "--current", "0.1"],
        ["ramp-list", "--segment", "1", "0.1", "0", "1", "1", "0", "0"],
        ["sequence", "--file", "sequence.json"],
    ],
)
def test_loop_count_parser_accepts_contract_bounds(argv: list[str], value: str) -> None:
    args = cli.build_parser().parse_args([*argv, "--loop-count", value])
    assert args.loop_count == int(value)

@pytest.mark.parametrize("value", ["0", "-1", "10001", "1.5", "true"])
@pytest.mark.parametrize(
    "argv",
    [
        ["ramp", "--channel", "1", "--start-voltage", "0", "--stop-voltage", "1", "--step-voltage", "1", "--current", "0.1"],
        ["ramp-list", "--segment", "1", "0.1", "0", "1", "1", "0", "0"],
        ["sequence", "--file", "sequence.json"],
    ],
)
def test_loop_count_parser_rejects_out_of_contract_values(argv: list[str], value: str) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([*argv, "--loop-count", value])

def test_ramp_simulate_json_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for simulate ramp")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "ramp",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.25",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    assert json.loads(capsys.readouterr().out)["ok"] is True

def test_ramp_real_writes_current_voltage_steps_and_exact_stop(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "ramp",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.4",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.writes == ["CURR 0.05,(@1)", "VOLT 0,(@1)", "VOLT 0.4,(@1)", "VOLT 0.8,(@1)", "VOLT 1,(@1)"]
    assert all("OUTP" not in command for command in session.writes)
    assert payload["data"]["voltages"] == [0.0, 0.4, 0.8, 1.0]

def test_ramp_real_completion_uses_software_core_path(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            **_trigger_snapshot_query_responses(),
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "ramp",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
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
                "--completion-pulse-pins",
                "1",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert "VOLT 0,(@1)" in session.writes
    assert "LIST:VOLT 0,0.5,1,(@1)" not in session.writes
    assert "LIST:TOUT:EOST 0,0,1,(@1)" not in session.writes
    assert payload["data"]["trigger"]["native"] is False

def test_ramp_rejects_more_than_1000_voltage_writes(capsys) -> None:
    assert (
        cli.main(
            [
                "ramp",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1000",
                "--step-voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "1000 voltage steps" in payload["error"]["message"]

def test_ramp_enable_output_shapes_dry_run_request_and_plan(capsys) -> None:
    assert (
        cli.main(
            [
                "ramp",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--channel",
                "1",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "1",
                "--current",
                "0.1",
                "--enable-output",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["enable_output"] is True
    assert payload["data"]["plan"]["enable_output"] is True
    assert [step["action"] for step in payload["data"]["plan"]["steps"][:4]] == [
        "set_current_limit",
        "set_voltage",
        "output_on",
        "output_state",
    ]

@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (
            CommandCancelled(
                "workflow cancelled by user",
                data={"status": "cancelled", "original_reason": "user_cancelled", "cleanup": []},
            ),
            "cancelled",
        ),
        (
            StopCleanupError(
                "workflow cancellation cleanup failed",
                results=({"operation": "output_state", "status": "failed", "message": "still on"},),
            ),
            "cleanup_failed",
        ),
    ],
)
def test_ramp_cancellation_json_envelope(monkeypatch, capsys, exception, code) -> None:
    monkeypatch.setattr(cli, "run_core_command", lambda *args, **kwargs: (_ for _ in ()).throw(exception))

    exit_code = cli.main([
        "ramp",
        "--json",
        "--resource",
        OUTPUT_RESOURCE,
        "--channel",
        "1",
        "--start-voltage",
        "0",
        "--stop-voltage",
        "1",
        "--step-voltage",
        "1",
        "--current",
        "0.1",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert payload["schema_version"] == 2
    assert payload["status"] == "error"
    assert payload["error"]["code"] == code
    assert payload["data"]["original_reason"] == "user_cancelled"

def test_ramp_list_lint_inline_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for ramp-list lint")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "ramp-list",
                "--lint",
                "--json",
                "--segment",
                "1",
                "0.1",
                "0",
                "1",
                "0.5",
                "100",
                "0",
                "--segment",
                "2",
                "0.05",
                "1",
                "2",
                "0.5",
                "50",
                "250",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "valid"
    assert payload["data"]["segment_count"] == 2
    assert payload["data"]["plan"]["version"] == 5
    assert payload["data"]["plan"]["loop_count"] == 1
    assert payload["data"]["segments"][1]["hold_ms"] == 250
    assert payload["data"]["segments"][1]["channels"] == [2]

def test_ramp_list_inline_enable_output_builds_v5(capsys) -> None:
    assert (
        cli.main(
            [
                "ramp-list",
                "--lint",
                "--json",
                "--enable-output",
                "--segment",
                "1",
                "0.1",
                "0",
                "1",
                "0.5",
                "0",
                "0",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["version"] == 5
    assert payload["data"]["plan"]["loop_count"] == 1
    assert payload["data"]["plan"]["enable_output"] is True

def test_ramp_list_file_rejects_enable_output_override(tmp_path, capsys) -> None:
    ramp_file = tmp_path / "example.ramp-list.json"
    ramp_file.write_text(
        json.dumps({
            "kind": "powers-tool-ramp-list",
            "version": 2,
            "segments": [{
                "channel": 1,
                "current": 0.1,
                "start_voltage": 0,
                "stop_voltage": 1,
                "step_voltage": 0.5,
                "delay_ms": 0,
                "hold_ms": 0,
            }],
        }),
        encoding="utf-8",
    )

    assert cli.main([
        "ramp-list",
        "--lint",
        "--json",
        "--file",
        str(ramp_file),
        "--enable-output",
    ]) == 2
    assert "--file cannot be combined with --enable-output" in json.loads(
        capsys.readouterr().out
    )["error"]["message"]

def test_ramp_list_dry_run_file_uses_versioned_document(tmp_path, capsys) -> None:
    ramp_file = tmp_path / "example.ramp-list.json"
    ramp_file.write_text(
        json.dumps(
            {
                "kind": "powers-tool-ramp-list",
                "version": 2,
                "segments": [
                    {
                        "channel": 1,
                        "current": 0.1,
                        "start_voltage": 0,
                        "stop_voltage": 1,
                        "step_voltage": 0.4,
                        "delay_ms": 0,
                        "hold_ms": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        cli.main(
            [
                "ramp-list",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--file",
                str(ramp_file),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "planned"
    assert payload["data"]["plan"]["version"] == 2
    assert payload["data"]["plan"]["segments"][0]["voltages"] == [0.0, 0.4, 0.8, 1.0]

def test_ramp_list_v2_file_loop_override_upgrades_to_v4(tmp_path, capsys) -> None:
    ramp_file = tmp_path / "example.ramp-list.json"
    ramp_file.write_text(
        json.dumps({
            "kind": "powers-tool-ramp-list",
            "version": 2,
            "segments": [{
                "channel": 1,
                "current": 0.1,
                "start_voltage": 0,
                "stop_voltage": 1,
                "step_voltage": 1,
                "delay_ms": 0,
                "hold_ms": 0,
            }],
        }),
        encoding="utf-8",
    )

    assert cli.main([
        "ramp-list", "--dry-run", "--json", "--model", "keysight-e36312a",
        "--file", str(ramp_file), "--loop-count", "2",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["version"] == 4
    assert payload["data"]["plan"]["loop_count"] == 2
    assert payload["data"]["plan"]["enable_output"] is False

def test_ramp_list_v1_file_is_rejected_without_conversion(tmp_path, capsys) -> None:
    ramp_file = tmp_path / "legacy.ramp-list.json"
    ramp_file.write_text(
        json.dumps(
            {
                "kind": "powers-tool-ramp-list",
                "version": 1,
                "segments": [
                    {
                        "channel": 1,
                        "current": 0.1,
                        "start_voltage": 0,
                        "stop_voltage": 1,
                        "step_voltage": 0.5,
                        "delay_ms": 0,
                        "hold_ms": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert cli.main(["ramp-list", "--lint", "--json", "--file", str(ramp_file)]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 2
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "unsupported ramp-list version: 1" in payload["error"]["message"]

def test_ramp_list_simulate_inline_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for ramp-list simulate")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "ramp-list",
                "--simulate",
                "--model",
                "keysight-e36312a",
                "--json",
                "--segment",
                "1",
                "0.1",
                "0",
                "1",
                "0.5",
                "0",
                "0",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["data"]["status"] == "planned"

def test_ramp_list_file_and_segment_are_mutually_exclusive(tmp_path, capsys) -> None:
    ramp_file = tmp_path / "example.ramp-list.json"
    ramp_file.write_text("{}", encoding="utf-8")

    assert (
        cli.main(
            [
                "ramp-list",
                "--json",
                "--file",
                str(ramp_file),
                "--segment",
                "1",
                "0.1",
                "0",
                "1",
                "0.5",
                "0",
                "0",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"

def test_ramp_list_real_executes_segments_in_order(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    opened = []

    def fake_open_resource(*args, **kwargs):
        opened.append((args, kwargs))
        return session

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "ramp-list",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--segment",
                "1",
                "0.1",
                "0",
                "1",
                "1",
                "0",
                "0",
                "--segment",
                "2",
                "0.05",
                "2",
                "1",
                "1",
                "0",
                "0",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert opened
    assert payload["execution"]["hardware_touched"] is True
    assert payload["data"]["completed_segments"] == 2
    assert session.writes == [
        "CURR 0.1,(@1)",
        "VOLT 0,(@1)",
        "VOLT 1,(@1)",
        "CURR 0.05,(@2)",
        "VOLT 2,(@2)",
        "VOLT 1,(@2)",
    ]

def test_ramp_list_real_forwards_serial_options_to_opener(monkeypatch, capsys) -> None:
    opened = []
    session = FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0", query_responses={"INST:NSEL?": "1"})

    def fake_open_resource(resource, resource_manager=None, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append(kwargs)
        return session

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "ramp-list",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--segment",
                "1",
                "0.05",
                "0",
                "1",
                "1",
                "0",
                "0",
                *SERIAL_TERMINATION_ARGS,
            ]
        )
        == 0
    )

    json.loads(capsys.readouterr().out)
    serial_options = opened[0]["serial_options"]
    assert serial_options.read_termination == "\r\n"
    assert serial_options.write_termination == "\n"
    assert opened[0]["serial_remote"] is True
    assert opened[0]["serial_local_on_close"] is True
