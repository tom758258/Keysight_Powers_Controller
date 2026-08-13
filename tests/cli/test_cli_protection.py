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

def test_protection_status_real_reads_flags_then_outputs(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "VOLT:PROT:TRIP? (@2)": "1",
            "CURR:PROT:TRIP? (@2)": "0",
            "OUTP? (@2)": "OFF",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "protection-status",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "2",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "VOLT:PROT:TRIP? (@2)", "CURR:PROT:TRIP? (@2)", "OUTP? (@2)"]
    assert payload["data"]["protection"] == {
        "over_voltage_tripped": True,
        "over_current_tripped": False,
    }
    assert payload["data"]["outputs"] == [
        {"channel": 2, "enabled": False, "disabled_with_protection": True}
    ]

def test_protection_status_real_edu36311a_includes_by_channel(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
        query_responses={
            "VOLT:PROT:TRIP? (@1)": "0",
            "CURR:PROT:TRIP? (@1)": "1",
            "VOLT:PROT:TRIP? (@2)": "0",
            "CURR:PROT:TRIP? (@2)": "0",
            "VOLT:PROT:TRIP? (@3)": "1",
            "CURR:PROT:TRIP? (@3)": "0",
            "OUTP? (@1)": "OFF",
            "OUTP? (@2)": "ON",
            "OUTP? (@3)": "OFF",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "protection-status",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--all",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == [
        "*IDN?",
        "VOLT:PROT:TRIP? (@1)",
        "CURR:PROT:TRIP? (@1)",
        "VOLT:PROT:TRIP? (@2)",
        "CURR:PROT:TRIP? (@2)",
        "VOLT:PROT:TRIP? (@3)",
        "CURR:PROT:TRIP? (@3)",
        "OUTP? (@1)",
        "OUTP? (@2)",
        "OUTP? (@3)",
    ]
    assert payload["data"]["protection"] == {
        "over_voltage_tripped": True,
        "over_current_tripped": True,
    }
    assert payload["data"]["protection_by_channel"] == [
        {
            "channel": 1,
            "protection": {
                "over_voltage_tripped": False,
                "over_current_tripped": True,
            },
        },
        {
            "channel": 2,
            "protection": {
                "over_voltage_tripped": False,
                "over_current_tripped": False,
            },
        },
        {
            "channel": 3,
            "protection": {
                "over_voltage_tripped": True,
                "over_current_tripped": False,
            },
        },
    ]

def test_protection_set_requires_confirm_for_real_hardware(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened without --confirm")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "protection-set",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "1",
                "--ovp-voltage",
                "5",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "confirmation_required"

def test_protection_set_requires_operation(capsys) -> None:
    assert (
        cli.main(
            [
                "protection-set",
                "--dry-run",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "1",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert payload["error"]["message"] == (
        "protection-set requires --ovp-voltage, --ocp, --ocp-delay, or --ocp-delay-trigger"
    )

def test_protection_set_rejects_negative_ocp_delay(capsys) -> None:
    assert (
        cli.main(
            [
                "protection-set",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--ocp-delay",
                "-0.1",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert payload["error"]["message"] == "ocp_delay must be a finite non-negative number"

def test_protection_set_execution_error_writes_json_envelope(
    monkeypatch, tmp_path, capsys
) -> None:
    save_path = tmp_path / "protection-set-error.json"
    message = 'protection-set completed with instrument errors: [\'-113, "Undefined header"\']'

    def fail(*_args, **_kwargs):
        raise CoreExecutionError(message)

    monkeypatch.setattr(cli.protection_core, "run_protection", fail)

    assert cli.main([
        "protection-set", "--simulate", "--json", "--resource", OUTPUT_RESOURCE,
        "--channel", "1", "--ovp-voltage", "5", "--save-json", str(save_path),
    ]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"] == {
        "type": "connection",
        "code": "protection_set_failed",
        "message": message,
        "retryable": True,
    }
    assert json.loads(save_path.read_text(encoding="utf-8")) == payload
    assert "Traceback" not in captured.err

def test_protection_set_dry_run_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for dry-run")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "protection-set",
                "--dry-run",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "all",
                "--ovp-voltage",
                "5",
                "--ocp",
                "on",
                "--ocp-delay",
                "0.5",
                "--ocp-delay-trigger",
                "setting-change",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["steps"] == [
        {"index": 1, "type": "scpi", "command": "VOLT:PROT 5,(@1)"},
        {"index": 2, "type": "scpi", "command": "CURR:PROT:STAT ON,(@1)"},
        {"index": 3, "type": "scpi", "command": "CURR:PROT:DEL 0.5,(@1)"},
        {"index": 4, "type": "scpi", "command": "CURR:PROT:DEL:STAR SCH,(@1)"},
        {"index": 5, "type": "scpi", "command": "VOLT:PROT 5,(@2)"},
        {"index": 6, "type": "scpi", "command": "CURR:PROT:STAT ON,(@2)"},
        {"index": 7, "type": "scpi", "command": "CURR:PROT:DEL 0.5,(@2)"},
        {"index": 8, "type": "scpi", "command": "CURR:PROT:DEL:STAR SCH,(@2)"},
        {"index": 9, "type": "scpi", "command": "VOLT:PROT 5,(@3)"},
        {"index": 10, "type": "scpi", "command": "CURR:PROT:STAT ON,(@3)"},
        {"index": 11, "type": "scpi", "command": "CURR:PROT:DEL 0.5,(@3)"},
        {"index": 12, "type": "scpi", "command": "CURR:PROT:DEL:STAR SCH,(@3)"},
    ]

def test_protection_set_real_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "protection-set",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--ovp-voltage",
                "5",
                "--ocp",
                "on",
                "--ocp-delay",
                "0.5",
                "--ocp-delay-trigger",
                "cc-transition",
                "--confirm",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == [
        "VOLT:PROT 5,(@1)",
        "CURR:PROT:STAT ON,(@1)",
        "CURR:PROT:DEL 0.5,(@1)",
        "CURR:PROT:DEL:STAR CCTR,(@1)",
        "VOLT:PROT 5,(@2)",
        "CURR:PROT:STAT ON,(@2)",
        "CURR:PROT:DEL 0.5,(@2)",
        "CURR:PROT:DEL:STAR CCTR,(@2)",
        "VOLT:PROT 5,(@3)",
        "CURR:PROT:STAT ON,(@3)",
        "CURR:PROT:DEL 0.5,(@3)",
        "CURR:PROT:DEL:STAR CCTR,(@3)",
    ]
    assert payload["data"] == {
        "resource": OUTPUT_RESOURCE,
        "channels": [
            {"channel": 1, "protection": {"ovp_voltage": 5.0, "ocp_enabled": True, "ocp_delay": 0.5, "ocp_delay_trigger": "cc-transition"}},
            {"channel": 2, "protection": {"ovp_voltage": 5.0, "ocp_enabled": True, "ocp_delay": 0.5, "ocp_delay_trigger": "cc-transition"}},
            {"channel": 3, "protection": {"ovp_voltage": 5.0, "ocp_enabled": True, "ocp_delay": 0.5, "ocp_delay_trigger": "cc-transition"}},
        ],
    }

def test_protection_set_real_edu36311a_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "protection-set",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "all",
                "--ovp-voltage",
                "5",
                "--ocp",
                "on",
                "--confirm",
            ]
        )
        == 0
    )

    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == [
        "VOLT:PROT 5,(@1)",
        "CURR:PROT:STAT ON,(@1)",
        "VOLT:PROT 5,(@2)",
        "CURR:PROT:STAT ON,(@2)",
        "VOLT:PROT 5,(@3)",
        "CURR:PROT:STAT ON,(@3)",
    ]
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["resource"] == "USB0::FAKE::EDU36311A::INSTR"

def test_protection_set_rejects_ovp_above_safety_limit(tmp_path, capsys) -> None:
    safety_config = write_safety_config(tmp_path)

    assert (
        cli.main(
            [
                "protection-set",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--ovp-voltage",
                "5.1",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "voltage 5.1 exceeds maximum 5" in payload["error"]["message"]
