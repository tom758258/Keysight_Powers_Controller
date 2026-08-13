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

def test_e3646a_cli_capabilities_reports_validated_output(capsys) -> None:
    assert (
        cli.main(
            [
                "capabilities",
                "--simulate",
                "--json",
                "--resource",
                "ASRL1::SIM::E3646A::INSTR",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    support = payload["data"]["command_support"]

    validated_commands = (
        "set",
        "output-off",
        "safe-off",
        "ramp",
        "ramp-list",
        "sequence",
    )
    for command in validated_commands:
        assert support[command]["real"] is True
        assert support[command]["hardware_validation"] == "validated"

    conditional_commands = ("apply", "output-on", "cycle-output", "smoke-output")
    for command in conditional_commands:
        assert support[command]["real"] is True
        assert support[command]["hardware_validation"] == "validated_confirm_threshold_conditional"

    disabled_commands = (
        "protection-status",
        "protection-set",
        "clear-protection",
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    )
    for command in disabled_commands:
        assert support[command]["real"] is False
        if command.startswith("trigger-"):
            assert support[command]["simulate"] is False
            assert support[command]["dry_run"] is False

def test_doctor_capabilities_and_safety_inspect_json(capsys) -> None:
    assert cli.main(["doctor", "--simulate", "--json"]) == 0
    doctor_payload = json.loads(capsys.readouterr().out)
    assert doctor_payload["data"]["simulator"]["available"] is True

    assert (
        cli.main(
            [
                "capabilities",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
            ]
        )
        == 0
    )
    capabilities_payload = json.loads(capsys.readouterr().out)
    assert capabilities_payload["data"]["driver"]["class"] == "EDU36311APowerSupply"
    assert capabilities_payload["data"]["channels"] == [1, 2, 3]

    assert (
        cli.main(
            [
                "safety",
                "inspect",
                "--json",
                "--safety-config",
                "examples/safety-config.toml",
                "--resource-alias",
                "sim-e36312a",
                "--channel",
                "1",
            ]
        )
        == 0
    )
    safety_payload = json.loads(capsys.readouterr().out)
    assert safety_payload["command"] == {"name": "safety inspect"}
    assert safety_payload["data"]["limits"]["max_voltage"] == 3.3

def test_resource_backed_capabilities_uses_exact_live_scope(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["capabilities", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["driver"]["class"] == "E36312APowerSupply"
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True

def test_resource_backed_capabilities_rejects_pyvisa_py_pending_scope(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "capabilities",
                "--json",
                "--resource",
                "TCPIP0::192.0.2.1::INSTR",
                "--backend",
                "@py",
            ]
        )
        == 2
    )

    assert_live_scope_rejected(json.loads(capsys.readouterr().out), session)

def test_resource_backed_doctor_is_not_a_live_policy_exemption(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "_list_resources", lambda *args, **kwargs: ())
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["doctor", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["resource"]["model_id"] == "keysight-e36312a"
