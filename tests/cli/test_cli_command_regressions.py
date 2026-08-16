import json

import pytest

import powers_tool_core.connection as connection
import powers_tool_cli.cli as cli
import powers_tool_cli.cli_runtime as cli_runtime
from powers_tool_core.errors import VisaConnectionError

from tests.cli.cli_test_helpers import (
    OUTPUT_RESOURCE,
    FakeSession,
    assert_live_scope_rejected,
    _all_trigger_snapshot_query_responses,
)
def test_new_commands_simulate_without_real_visa(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "measure-all",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
            ]
        )
        == 0
    )
    measure_all_data = json.loads(capsys.readouterr().out)["data"]
    assert measure_all_data["channels"][1]["measurements"] == {
        "voltage": 2.2,
        "current": 0.22,
    }
    assert measure_all_data["idn"] == {
        "manufacturer": "KEYSIGHT",
        "model": "E36312A",
        "serial": "SIM000003",
        "firmware": "1.0",
        "parse_ok": True,
    }
    assert "raw" not in measure_all_data["idn"]

    assert (
        cli.main(
            [
                "read-status",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["data"]["outputs"] == [
        {"channel": 1, "enabled": False},
        {"channel": 2, "enabled": False},
        {"channel": 3, "enabled": False},
    ]

    assert (
        cli.main(
            [
                "trigger-pulse",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--pin",
                "3",
            ]
        )
        == 0
    )
    pulse = json.loads(capsys.readouterr().out)["data"]
    assert pulse["triggered"] is True
    assert pulse["restored"] is True

@pytest.mark.parametrize(
    ("command", "extra_args"),
    [
        ("measure-all", []),
        ("read-status", []),
        ("trigger-pulse", ["--pin", "1"]),
    ],
)
def test_new_real_commands_reject_non_e36312a(
    monkeypatch,
    capsys,
    command,
    extra_args,
) -> None:
    session = FakeSession(idn="KEYSIGHT,UNKNOWN,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([command, "--json", "--resource", OUTPUT_RESOURCE, *extra_args]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert_live_scope_rejected(payload, session)

def test_new_command_open_failure_uses_connection_failed(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise VisaConnectionError("open failed")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert cli.main(["measure-all", "--json", "--resource", OUTPUT_RESOURCE]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "connection_failed"

def test_new_commands_log_scpi_to_stderr_without_corrupting_json(monkeypatch, capsys) -> None:
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
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> DIG:PIN1:FUNC TOUT" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> *TRG" in captured.err

@pytest.mark.parametrize(
    ("command", "extra_args"),
    [
        ("readback", []),
        ("protection-status", []),
        ("clear-protection", ["--channel", "1", "--confirm"]),
        ("snapshot", []),
    ],
)
def test_new_e36312a_commands_reject_non_e36312a(monkeypatch, capsys, command, extra_args) -> None:
    session = FakeSession(idn="KEYSIGHT,UNKNOWN,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([command, "--json", "--resource", OUTPUT_RESOURCE, *extra_args]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert_live_scope_rejected(payload, session)

@pytest.mark.parametrize(
    ("command", "extra_args", "code"),
    [
        ("readback", ["--channel", "99"], "argument_error"),
        ("protection-status", ["--channel", "99"], "argument_error"),
        ("clear-protection", ["--channel", "99", "--dry-run"], "argument_error"),
        ("snapshot", ["--max-errors", "0"], "argument_error"),
    ],
)
def test_new_e36312a_commands_argument_errors(capsys, command, extra_args, code) -> None:
    assert cli.main([command, "--json", "--resource", OUTPUT_RESOURCE, *extra_args]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == code

def test_new_e36312a_commands_simulate_without_real_visa(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)
    resource = "USB0::SIM::E36312A::INSTR"
    commands = [
        ["readback", "--simulate", "--json", "--resource", resource],
        ["protection-status", "--simulate", "--json", "--resource", resource],
        ["clear-protection", "--simulate", "--json", "--resource", resource, "--all"],
        ["identify", "--simulate", "--json", "--resource", resource],
        ["snapshot", "--simulate", "--json", "--resource", resource],
    ]

    for command in commands:
        assert cli.main(command) == 0
        assert json.loads(capsys.readouterr().out)["ok"] is True
