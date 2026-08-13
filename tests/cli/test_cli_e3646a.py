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
)

def test_e3646a_dry_run_all_expands_two_channels_and_rejects_three(capsys) -> None:
    assert cli.main(["output-on", "--dry-run", "--json", "--model", "keysight-e3646a", "--channel", "all"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["target"]["planning_model_id"] == "keysight-e3646a"
    assert [step["parameters"]["channel"] for step in payload["data"]["plan"]["steps"]] == [1, 2]

    assert cli.main(["output-on", "--dry-run", "--json", "--model", "keysight-e3646a", "--channel", "3"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert "channel 3" in payload["error"]["message"]

@pytest.mark.parametrize(
    ("command", "extra_args"),
    [
        ("set", ["--channel", "1", "--voltage", "1", "--current", "0.05"]),
        ("apply", ["--channel", "1", "--voltage", "1", "--current", "0.05", "--confirm"]),
        ("output-off", ["--channel", "1"]),
        ("safe-off", ["--channel", "1"]),
        ("cycle-output", ["--channel", "1", "--duration-ms", "1", "--confirm"]),
        ("ramp", ["--channel", "1", "--start-voltage", "0", "--stop-voltage", "1", "--step-voltage", "1", "--current", "0.05"]),
        ("ramp-list", ["--segment", "1", "0.05", "0", "1", "1", "0", "0"]),
        ("smoke-output", ["--channel", "1", "--voltage", "1", "--current", "0.05", "--confirm"]),
    ],
)
def test_e3646a_real_output_affecting_commands_success(monkeypatch, capsys, command, extra_args) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E3646A,SERIAL0000,1.0",
        query_responses={
            "INST:NSEL?": "1",
            "VOLT?": "1.0",
            "CURR?": "0.05",
            "OUTP?": "0",
            "MEAS:VOLT?": "1.0",
            "MEAS:CURR?": "0.05",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([command, "--json", "--resource", "ASRL1::INSTR", *extra_args]) == 0

def test_e3646a_real_output_on_uses_promoted_asrl_product_scope(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E3646A,SERIAL0000,1.0",
        query_responses={"INST:NSEL?": "1", "VOLT?": "1.0", "CURR?": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--channel",
                "1",
                "--confirm",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert "OUTP ON" in session.writes

@pytest.mark.parametrize(
    ("command", "extra_args"),
    [
        ("protection-set", ["--channel", "1", "--ovp-voltage", "5", "--confirm"]),
        ("clear-protection", ["--channel", "1", "--confirm"]),
    ],
)
def test_e3646a_real_protection_commands_remain_disabled(monkeypatch, capsys, command, extra_args) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E3646A,SERIAL0000,1.0",
        query_responses={
            "INST:NSEL?": "1",
            "VOLT?": "1.0",
            "CURR?": "0.05",
            "OUTP?": "0",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([command, "--json", "--resource", "ASRL1::INSTR", *extra_args]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] in {"validation", "unsupported_model"}
    assert payload["error"]["code"] != "connection_failed"
    assert not any(
        write.startswith(("VOLT:PROT", "CURR:PROT"))
        for write in session.writes
    )

@pytest.mark.parametrize(
    ("command", "extra_args"),
    [
        ("trigger-step", ["--channel", "1", "--source", "bus", "--fire"]),
        ("trigger-list", ["--channel", "1", "--voltage-list", "0,1", "--current-list", "0.05", "--dwell-list", "0.01", "--fire", "--wait-complete"]),
        ("trigger-fire", []),
        ("trigger-abort", ["--channel", "1"]),
    ],
)
def test_e3646a_real_trigger_write_workflows_remain_disabled(monkeypatch, capsys, command, extra_args) -> None:
    session = FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([command, "--json", "--resource", "ASRL1::INSTR", *extra_args]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] in {"validation", "unsupported_model"}
    assert not any(
        write.startswith(E3646A_FORBIDDEN_WRITE_PREFIXES)
        for write in session.writes
    )
