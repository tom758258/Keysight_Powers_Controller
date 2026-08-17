import json

import pytest

import powers_tool_cli.cli as cli
import powers_tool_cli.cli_runtime as cli_runtime
from powers_tool_core.core import CoreExecutionError
from powers_tool_core.errors import VisaConnectionError

from tests.cli.cli_test_helpers import (
    OUTPUT_RESOURCE,
    FakeSession,
    assert_live_scope_rejected,
    write_safety_config,
    _all_trigger_snapshot_query_responses,
    _trigger_snapshot_query_responses,
)
def test_trigger_pulse_real_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            **_trigger_snapshot_query_responses(1),
            **_trigger_snapshot_query_responses(2),
            **_trigger_snapshot_query_responses(3),
            "VOLT? (@3)": "1.0",
            "CURR? (@3)": "0.05",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pin",
                "2",
                "--channel",
                "3",
                "--polarity",
                "negative",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["data"]["triggered"] is True
    assert "*TRG" in session.writes

def test_trigger_pulse_dry_run_json_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--pin",
                "1",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["data"]["plan"]["steps"] == [
        {"index": 1, "type": "scpi", "command": "DIG:PIN1:FUNC TOUT"},
        {"index": 2, "type": "scpi", "command": "DIG:PIN1:POL POS"},
        {"index": 3, "type": "scpi", "command": "DIG:TOUT:BUS ON"},
        {"index": 4, "type": "scpi", "command": "CURR:TRIG <current-readback>,(@1)"},
        {"index": 5, "type": "scpi", "command": "VOLT:TRIG <voltage-readback>,(@1)"},
        {"index": 6, "type": "scpi", "command": "CURR:MODE FIX,(@1)"},
        {"index": 7, "type": "scpi", "command": "VOLT:MODE FIX,(@1)"},
        {"index": 8, "type": "scpi", "command": "CURR:MODE STEP,(@1)"},
        {"index": 9, "type": "scpi", "command": "VOLT:MODE STEP,(@1)"},
        {"index": 10, "type": "scpi", "command": "TRIG:SOUR BUS,(@1)"},
        {"index": 11, "type": "scpi", "command": "INIT (@1)"},
        {"index": 12, "type": "scpi", "command": "*TRG"},
    ]

def test_trigger_dry_run_without_model_or_e36312a_sim_resource_fails(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--dry-run",
                "--json",
                "--pin",
                "1",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "require planning_model_id" in payload["error"]["message"]

def test_trigger_pulse_dry_run_json_accepts_multiple_pins(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--pins",
                "1,2",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["pins"] == [1, 2]
    assert payload["request"]["exclusive_pins"] is False
    assert "pin" not in payload["request"]
    assert payload["data"]["plan"]["steps"][:5] == [
        {"index": 1, "type": "scpi", "command": "DIG:PIN1:FUNC TOUT"},
        {"index": 2, "type": "scpi", "command": "DIG:PIN1:POL POS"},
        {"index": 3, "type": "scpi", "command": "DIG:PIN2:FUNC TOUT"},
        {"index": 4, "type": "scpi", "command": "DIG:PIN2:POL POS"},
        {"index": 5, "type": "scpi", "command": "DIG:TOUT:BUS ON"},
    ]

def test_trigger_pulse_real_accepts_multiple_pins(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            **_all_trigger_snapshot_query_responses(),
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pins",
                "1,2",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["request"]["pins"] == [1, 2]

def test_trigger_pulse_exclusive_pin_clears_other_trigger_pins(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            **_all_trigger_snapshot_query_responses(),
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pin",
                "1",
                "--exclusive-pin",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert "DIG:PIN2:FUNC DIO" in session.writes
    assert "DIG:PIN3:FUNC DIO" in session.writes

def test_trigger_pulse_exclusive_pins_clears_only_unselected_pin(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            **_all_trigger_snapshot_query_responses(),
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pins",
                "1,2",
                "--exclusive-pins",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert "DIG:PIN3:FUNC DIO" in session.writes

def test_trigger_pulse_exclusive_pin_dry_run_lists_clear_steps(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--pin",
                "3",
                "--exclusive-pin",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["exclusive_pin"] is True
    assert payload["data"]["plan"]["steps"][:4] == [
        {"index": 1, "type": "scpi", "command": "DIG:PIN1:FUNC DIO"},
        {"index": 2, "type": "scpi", "command": "DIG:PIN2:FUNC DIO"},
        {"index": 3, "type": "scpi", "command": "DIG:PIN3:FUNC TOUT"},
        {"index": 4, "type": "scpi", "command": "DIG:PIN3:POL POS"},
    ]

def test_trigger_pulse_reports_instrument_error_queue(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            **_all_trigger_snapshot_query_responses(),
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
            "SYST:ERR?": ['-211,"Trigger ignored"', '0,"No error"'],
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pin",
                "1",
            ]
        )
        == 1
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert '-211,"Trigger ignored"' in payload["error"]["message"]

def test_trigger_pulse_resource_alias_resolves_before_open(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    opened: list[tuple[str, str | None, int]] = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        opened.append((resource, backend, timeout_ms))
        return session

    monkeypatch.setattr(cli_runtime, "open_resource", fake_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        f"""
[[resources]]
alias = "e36312a"
resource = "{OUTPUT_RESOURCE}"
""".strip(),
    )

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource-alias",
                "e36312a",
                "--safety-config",
                safety_config,
                "--pin",
                "1",
                "--backend",
                "@py",
                "--timeout-ms",
                "1234",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert opened == [(OUTPUT_RESOURCE, "@py", 1234)]
    assert_live_scope_rejected(payload, session)
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": "e36312a",
        "pins": [1],
        "channel": 1,
        "polarity": "positive",
        "exclusive_pins": False,
        "safety_config": safety_config,
        "backend": "@py",
        "timeout_ms": 1234,
        "pin": 1,
        "exclusive_pin": False,
    }

def test_trigger_pulse_invalid_pin_is_argument_error(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pin",
                "4",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "argument_error"

@pytest.mark.parametrize(
    "args",
    [
        ["--pins", "1,1"],
        ["--pins", "4"],
        ["--pins", ""],
        ["--pins", "1,"],
        ["--pin", "1", "--pins", "1,2"],
    ],
)
def test_trigger_pulse_invalid_pins_are_argument_errors(capsys, args) -> None:
    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                *args,
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"

def test_trigger_pulse_write_failure_surfaces_connection_error(monkeypatch, capsys) -> None:
    class FailingWriteSession(FakeSession):
        def write(self, command: str) -> None:
            super().write(command)
            raise VisaConnectionError("write failed")

    session = FailingWriteSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            **_all_trigger_snapshot_query_responses(),
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--pin",
                "1",
            ]
        )
        == 1
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "trigger_pulse_failed"
    assert session.writes

def test_trigger_status_simulate_reports_list_and_pin_state(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-status",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "1",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["digital_pins"][0]["pin"] == 1
    assert payload["data"]["channels"][0]["trigger"]["source"] == "BUS"
    assert payload["data"]["channels"][0]["list"]["count"] == 1

def test_trigger_status_dry_run_model_plans_without_opening(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "trigger-status",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--channel",
                "all",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["target"]["planning_model_id"] == "keysight-e36312a"
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert "TRIG:SOUR? (@1)" in commands
    assert "TRIG:SOUR? (@2)" in commands
    assert "TRIG:SOUR? (@3)" in commands

def test_trigger_status_simulate_model_derives_e36312a_resource(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-status",
                "--simulate",
                "--json",
                "--model",
                "keysight-e36312a",
                "--channel",
                "1",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["resource"]["name"] == "USB0::SIM::E36312A::INSTR"
    assert payload["data"]["resource"]["idn"]["model"] == "E36312A"

def test_trigger_list_dry_run_json_plans_native_list_scpi(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--channel",
                "1",
                "--voltage-list",
                "0,1",
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
                "--completion-pulse-pins",
                "1",
                "--fire",
                "--leave-trigger-configured",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert commands == [
        "ABOR (@1)",
        "DIG:PIN1:FUNC TOUT",
        "DIG:PIN1:POL POS",
        "DIG:TOUT:BUS ON",
        "LIST:VOLT 0,1,(@1)",
        "LIST:CURR 0.05,0.05,(@1)",
        "LIST:DWEL 0.01,0.01,(@1)",
        "LIST:TOUT:BOST 0,0,(@1)",
        "LIST:TOUT:EOST 0,1,(@1)",
        "LIST:COUN 1,(@1)",
        "LIST:STEP AUTO,(@1)",
        "LIST:TERM:LAST ON,(@1)",
        "CURR:MODE FIX,(@1)",
        "VOLT:MODE FIX,(@1)",
        "CURR:MODE LIST,(@1)",
        "VOLT:MODE LIST,(@1)",
        "TRIG:SOUR BUS,(@1)",
        "INIT (@1)",
        "*TRG",
    ]

def test_trigger_list_rejects_more_than_100_steps(capsys) -> None:
    values = ",".join(str(index / 100) for index in range(101))

    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--channel",
                "1",
                "--voltage-list",
                values,
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "trigger_list_too_long"

def test_trigger_step_bus_fire_is_explicit(capsys) -> None:
    base_args = [
        "trigger-step",
        "--dry-run",
        "--json",
        "--model",
        "keysight-e36312a",
        "--channel",
        "1",
        "--source",
        "bus",
        "--leave-trigger-configured",
    ]

    assert cli.main(base_args) == 0
    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert "*TRG" not in commands

    assert cli.main([*base_args, "--fire"]) == 0
    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert "*TRG" in commands

def test_trigger_list_dry_run_supports_explicit_bost_eost(capsys) -> None:
    assert cli.main([
        "trigger-list", "--dry-run", "--json", "--model", "keysight-e36312a",
        "--channel", "1", "--voltage-list", "0,1", "--current-list", "0.05",
        "--dwell-list", "0.01", "--bost-list", "on,off", "--eost-list", "off,on",
        "--trigger-output-pins", "1,3", "--trigger-output-polarity", "negative",
        "--source", "immediate", "--wait-complete",
    ]) == 0

    commands = [step["command"] for step in json.loads(capsys.readouterr().out)["data"]["plan"]["steps"]]
    assert "LIST:TOUT:BOST 1,0,(@1)" in commands
    assert "LIST:TOUT:EOST 0,1,(@1)" in commands
    assert "DIG:PIN1:POL NEG" in commands
    assert "DIG:PIN3:POL NEG" in commands

def test_trigger_step_rejects_completion_pulse_pins(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-step",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--channel",
                "1",
                "--completion-pulse-pins",
                "1",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "one-step trigger-list" in payload["error"]["message"]

def test_trigger_step_bus_arm_only_keeps_existing_non_wait_behavior(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-step",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--channel",
                "1",
                "--source",
                "bus",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True

@pytest.mark.parametrize("mode", ["--dry-run", "--simulate"])
def test_trigger_step_no_hardware_edu36311a_is_rejected(capsys, mode: str) -> None:
    assert (
        cli.main(
            [
                "trigger-step",
                mode,
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--channel",
                "1",
                "--source",
                "bus",
                "--fire",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "unsupported_model_for_trigger"
    assert "trigger/native LIST workflows are disabled in live, simulate, and dry-run" in payload["error"]["message"]

def test_trigger_step_real_edu36311a_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "trigger-step",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "1",
                "--source",
                "bus",
                "--leave-trigger-configured",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert_live_scope_rejected(payload, session)

def test_trigger_list_bus_arm_only_requires_leave_configured(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--channel",
                "1",
                "--voltage-list",
                "0,1",
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "leave-trigger-configured" in payload["error"]["message"]

def test_trigger_list_started_without_wait_requires_leave_configured(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--channel",
                "1",
                "--voltage-list",
                "0,1",
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
                "--fire",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert "without --wait-complete" in payload["error"]["message"]

def test_trigger_list_completion_pins_imply_final_eost(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--channel",
                "1",
                "--voltage-list",
                "0,1",
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
                "--completion-pulse-pins",
                "1",
                "--fire",
                "--wait-complete",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert "LIST:TOUT:EOST 0,1,(@1)" in commands
    assert "*OPC?" not in commands
    assert "*OPC" in commands
    assert "*ESR?" in commands

def test_trigger_list_file_steps_format(tmp_path, capsys) -> None:
    list_file = tmp_path / "list.json"
    list_file.write_text(
        json.dumps(
            {
                "channel": 1,
                "steps": [
                    {"voltage": 0.0, "current": 0.05, "dwell": 0.01},
                    {"voltage": 1.0, "current": 0.06, "dwell": 0.02},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--file",
                str(list_file),
                "--leave-trigger-configured",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert "LIST:VOLT 0,1,(@1)" in commands
    assert "LIST:CURR 0.05,0.06,(@1)" in commands
    assert "LIST:DWEL 0.01,0.02,(@1)" in commands

def test_trigger_list_file_array_format_still_supported(tmp_path, capsys) -> None:
    list_file = tmp_path / "list.json"
    list_file.write_text(
        json.dumps({"channel": 1, "voltages": [0, 1], "currents": [0.05], "dwell": [0.01]}),
        encoding="utf-8",
    )

    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--file",
                str(list_file),
                "--leave-trigger-configured",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert "LIST:CURR 0.05,0.05,(@1)" in commands

def test_trigger_list_safety_config_checks_each_step(tmp_path, capsys) -> None:
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
max_voltage = 0.5
max_current = 0.5
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--channel",
                "1",
                "--voltage-list",
                "0.1,0.6",
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
                "--leave-trigger-configured",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "exceeds maximum" in payload["error"]["message"]

def test_trigger_list_exclusive_pins_clears_unselected_pins(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--channel",
                "1",
                "--voltage-list",
                "0,1",
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
                "--completion-pulse-pins",
                "2",
                "--exclusive-pins",
                "--fire",
                "--wait-complete",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert "DIG:PIN1:FUNC DIO" in commands
    assert "DIG:PIN2:FUNC DIO" not in commands
    assert "DIG:PIN3:FUNC DIO" in commands

def test_trigger_fire_wait_complete_requires_channel(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-fire",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--wait-complete",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "requires --channel" in payload["error"]["message"]

def test_trigger_fire_success_json_contains_full_trigger_payload(monkeypatch, capsys) -> None:
    trigger = {
        "mode": "fire",
        "native": True,
        "channel": 1,
        "pins": [],
        "polarity": "positive",
        "source": "bus",
        "armed": False,
        "fired": True,
        "completed": True,
        "aborted": False,
        "stopped": False,
        "stop_reason": None,
        "wait_timeout_ms": 1000,
        "poll_ms": 50,
        "restored": None,
        "restore_errors": [],
    }
    monkeypatch.setattr(
        cli.trigger_core,
        "run_trigger",
        lambda *args, **kwargs: {"_resource": OUTPUT_RESOURCE, "idn": None, "trigger": trigger},
    )

    assert cli.main(["trigger-fire", "--simulate", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "1"]) == 0

    assert json.loads(capsys.readouterr().out)["data"]["trigger"] == trigger

def test_trigger_fire_failure_json_contains_abort_diagnostics(monkeypatch, capsys) -> None:
    trigger = {
        "mode": "fire",
        "native": True,
        "channel": 1,
        "fired": True,
        "completed": False,
        "abort_attempted": True,
        "abort_succeeded": False,
        "abort_errors": ["abort failed"],
    }

    def fail(*args, **kwargs):
        raise CoreExecutionError("trigger-fire failed: queue error", trigger=trigger)

    monkeypatch.setattr(cli.trigger_core, "run_trigger", fail)

    assert cli.main(["trigger-fire", "--simulate", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "1"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "trigger_fire_failed"
    assert payload["data"]["trigger"] == trigger

def test_trigger_abort_all_plans_each_channel(capsys) -> None:
    assert (
        cli.main(
            [
                "trigger-abort",
                "--dry-run",
                "--json",
                "--model",
                "keysight-e36312a",
                "--channel",
                "all",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    commands = [step["command"] for step in payload["data"]["plan"]["steps"]]
    assert commands[:3] == ["ABOR (@1)", "ABOR (@2)", "ABOR (@3)"]
