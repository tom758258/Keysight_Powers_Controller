import json

import pytest

import powers_tool_core.connection as connection
import powers_tool_cli.cli as cli
import powers_tool_cli.cli_runtime as cli_runtime
import powers_tool_cli.commands.output_run as output_run
import powers_tool_cli.commands.readonly as readonly_commands
from powers_tool_core.core import CoreExecutionError
from powers_tool_core.errors import VisaConnectionError

from tests.cli.cli_test_helpers import (
    OUTPUT_RESOURCE,
    FakeSession,
    expected_resource,
)
def test_parser_error_with_save_json_writes_existing_error_envelope(
    monkeypatch, tmp_path, capsys
) -> None:
    save_path = tmp_path / "parser-error.json"

    def fail_open(*args, **kwargs):
        raise AssertionError("parser failures must not open hardware")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open)

    assert (
        cli.main(
            [
                "verify",
                "--json",
                "--save-json",
                str(save_path),
                "--resource",
                "ASRL1::INSTR",
                "--invalid-option",
            ]
        )
        == 2
    )

    stdout_payload = json.loads(capsys.readouterr().out)
    saved_payload = json.loads(save_path.read_text(encoding="utf-8"))
    assert saved_payload == stdout_payload
    assert saved_payload["error"]["code"] == "argument_error"
    assert saved_payload["execution"]["hardware_touched"] is False

def test_parser_error_save_failure_uses_existing_json_save_error(capsys, tmp_path) -> None:
    assert (
        cli.main(
            [
                "verify",
                "--json",
                "--save-json",
                str(tmp_path),
                "--resource",
                "ASRL1::INSTR",
                "--invalid-option",
            ]
        )
        == 1
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "json_save_failed"
    assert payload["execution"]["hardware_touched"] is False

def test_clear_dry_run_json_does_not_open_visa(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "clear",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": True,
        "hardware_touched": False,
    }
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "backend": None,
        "timeout_ms": 5000,
    }
    assert payload["data"]["plan"]["steps"] == [
        {"index": 1, "type": "scpi", "command": "*CLS"}
    ]
    assert captured.err == ""

def test_clear_real_json_writes_only_cls(monkeypatch, capsys) -> None:
    session = FakeSession()
    opened = []

    def fake_open_resource(resource, resource_manager=None, *, backend=None, timeout_ms=5000):
        opened.append((resource, resource_manager, backend, timeout_ms))
        return session

    monkeypatch.setattr(cli_runtime, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "clear",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--backend",
                "@py",
                "--timeout-ms",
                "1234",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert opened == [(OUTPUT_RESOURCE, None, "@py", 1234)]
    assert session.writes == ["*CLS"]
    assert session.queries == []
    assert session.closed is True
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": True,
    }
    assert payload["data"]["cleared"] is True
    assert payload["data"]["resource"] == expected_resource(OUTPUT_RESOURCE, reachable=True)
    assert captured.err == ""

def test_error_simulate_json_does_not_create_real_resource_manager(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "error",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"] == {
        "resource": "USB0::SIM::E36312A::INSTR",
        "backend": None,
        "timeout_ms": 5000,
        "max_reads": 20,
    }
    assert payload["data"]["errors"] == []
    assert payload["data"]["read_count"] == 1
    assert captured.err == ""

def test_error_real_json_reads_until_no_error(monkeypatch, capsys) -> None:
    session = FakeSession(
        query_responses={
            "SYST:ERR?": ['-100,"Command error"', '0,"No error"'],
        }
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(["error", "--json", "--resource", OUTPUT_RESOURCE, "--max-reads", "5"])
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == []
    assert session.queries == ["SYST:ERR?", "SYST:ERR?"]
    assert payload["execution"]["hardware_touched"] is True
    assert payload["data"]["errors"] == ['-100,"Command error"']
    assert payload["data"]["read_count"] == 2
    assert payload["data"]["max_reads"] == 5
    assert captured.err == ""

@pytest.mark.parametrize("command", ["clear", "error"])
def test_safe_generic_io_serial_termination_options_reach_request_and_opener(
    monkeypatch,
    capsys,
    command: str,
) -> None:
    session = FakeSession()
    opened = []

    def fake_open_resource(resource, resource_manager=None, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append((resource, resource_manager, backend, timeout_ms, kwargs))
        return session

    monkeypatch.setattr(cli_runtime, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                command,
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--serial-read-termination",
                "CRLF",
                "--serial-write-termination",
                "LF",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    serial_options = opened[0][4]["serial_options"]
    assert serial_options.read_termination == "\r\n"
    assert serial_options.write_termination == "\n"
    assert payload["request"]["serial_options"]["read_termination"] == "\r\n"
    assert payload["request"]["serial_options"]["write_termination"] == "\n"

def test_measure_simulate_json_does_not_create_real_resource_manager(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "measure",
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

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"] == {
        "resource": "USB0::SIM::E36312A::INSTR",
        "channel": 1,
        "backend": None,
        "timeout_ms": 5000,
    }
    assert payload["data"]["channel"] == 1
    assert payload["data"]["measurements"] == {"voltage": 1.1, "current": 0.11}
    assert captured.err == ""

@pytest.mark.parametrize(
    ("resource", "channel", "expected_measurements"),
    [
        (
            "USB0::SIM::E36312A::INSTR",
            "1",
            {"voltage": 1.1, "current": 0.11},
        ),
        (
            "USB0::SIM::E36312A::INSTR",
            "2",
            {"voltage": 2.2, "current": 0.22},
        ),
        (
            "USB0::SIM::E36312A::INSTR",
            "3",
            {"voltage": 3.3, "current": 0.33},
        ),
        (
            "USB0::SIM::EDU36311A::INSTR",
            "1",
            {"voltage": 1.01, "current": 0.101},
        ),
        (
            "USB0::SIM::EDU36311A::INSTR",
            "2",
            {"voltage": 2.02, "current": 0.202},
        ),
        (
            "USB0::SIM::EDU36311A::INSTR",
            "3",
            {"voltage": 3.03, "current": 0.303},
        ),
    ],
)
def test_measure_simulate_uses_model_driver_for_e36312a_and_edu36311a_channels(
    monkeypatch,
    capsys,
    resource,
    channel,
    expected_measurements,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "measure",
                "--simulate",
                "--json",
                "--resource",
                resource,
                "--channel",
                channel,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"]["resource"] == resource
    assert payload["request"]["channel"] == int(channel)
    assert payload["data"]["channel"] == int(channel)
    assert payload["data"]["measurements"] == expected_measurements
    assert captured.err == ""

def test_measure_simulate_model_driver_logs_channel_list_scpi_to_stderr(
    monkeypatch,
    capsys,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "measure",
                "--simulate",
                "--json",
                "--log-scpi",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "2",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["data"]["measurements"] == {"voltage": 2.2, "current": 0.22}
    assert "USB0::SIM::E36312A::INSTR SCPI >> *IDN?" in captured.err
    assert "USB0::SIM::E36312A::INSTR SCPI >> MEAS:VOLT? (@2)" in captured.err
    assert "USB0::SIM::E36312A::INSTR SCPI >> MEAS:CURR? (@2)" in captured.err

def test_measure_simulate_e3646a_channel_three_is_rejected_without_real_visa(
    monkeypatch,
    capsys,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "measure",
                "--simulate",
                "--json",
                "--resource",
                "ASRL1::SIM::E3646A::INSTR",
                "--channel",
                "3",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "E3646APowerSupply" in payload["error"]["message"]
    assert "channels 1, 2" in payload["error"]["message"]
    assert captured.err == ""

def test_measure_real_json_queries_voltage_then_current(monkeypatch, capsys) -> None:
    session = FakeSession(
        query_responses={
            "MEAS:VOLT?": "1.234",
            "MEAS:CURR?": "0.056",
        }
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(["measure", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "1"])
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == []
    assert session.queries == ["*IDN?", "MEAS:VOLT?", "MEAS:CURR?"]
    assert session.closed is True
    assert payload["execution"]["hardware_touched"] is True
    assert payload["data"]["measurements"] == {"voltage": 1.234, "current": 0.056}
    assert captured.err == ""

@pytest.mark.parametrize("channel", ["2", "3"])
def test_measure_real_e36312a_channel_two_and_three_use_channel_list_queries(
    monkeypatch,
    capsys,
    channel,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            f"MEAS:VOLT? (@{channel})": "1.234",
            f"MEAS:CURR? (@{channel})": "0.056",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "measure",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                channel,
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == []
    assert session.queries == [
        "*IDN?",
        f"MEAS:VOLT? (@{channel})",
        f"MEAS:CURR? (@{channel})",
    ]
    assert session.closed is True
    assert payload["execution"]["hardware_touched"] is True
    assert payload["data"]["channel"] == int(channel)
    assert payload["data"]["measurements"] == {"voltage": 1.234, "current": 0.056}
    assert "USB0::FAKE::E36312A::INSTR SCPI >> *IDN?" in captured.err
    assert f"USB0::FAKE::E36312A::INSTR SCPI >> MEAS:VOLT? (@{channel})" in captured.err
    assert f"USB0::FAKE::E36312A::INSTR SCPI >> MEAS:CURR? (@{channel})" in captured.err

@pytest.mark.parametrize("channel", ["2", "3"])
def test_measure_real_edu36311a_channel_two_and_three_use_channel_list_queries(
    monkeypatch,
    capsys,
    channel,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
        query_responses={
            f"MEAS:VOLT? (@{channel})": "1.234",
            f"MEAS:CURR? (@{channel})": "0.056",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "measure",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                channel,
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == [
        "*IDN?",
        f"MEAS:VOLT? (@{channel})",
        f"MEAS:CURR? (@{channel})",
    ]
    assert payload["data"]["measurements"] == {"voltage": 1.234, "current": 0.056}

def test_measure_real_generic_channel_two_is_rejected_after_idn(
    monkeypatch,
    capsys,
) -> None:
    session = FakeSession(idn="KEYSIGHT,UNKNOWN,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(["measure", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "2"])
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == []
    assert session.queries == ["*IDN?"]
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "unsupported_live_scope"
    assert "unknown live support-policy model_id for reported model 'UNKNOWN'" in payload["error"]["message"]
    assert captured.err == ""

@pytest.mark.parametrize("model", ["E36103B", "E36232A"])
def test_model_aware_live_command_blocks_descoped_idn_before_generic_fallback(
    monkeypatch,
    capsys,
    model: str,
) -> None:
    session = FakeSession(idn=f"KEYSIGHT,{model},SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--json", "--resource", OUTPUT_RESOURCE]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert payload["error"]["code"] == "unsupported_model_for_status"
    assert model in payload["error"]["message"]
    assert "de-scoped and not currently supported" in payload["error"]["message"]
    assert "Generic fallback is blocked" in payload["error"]["message"]
    assert captured.err == ""

def test_safe_off_real_all_reads_back_each_channel(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "OUTP? (@1)": "0",
            "OUTP? (@2)": "1",
            "OUTP? (@3)": "OFF",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "safe-off",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "all",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == ["OUTP OFF,(@1)", "OUTP OFF,(@2)", "OUTP OFF,(@3)"]
    assert session.queries == ["*IDN?", "OUTP? (@1)", "OUTP? (@2)", "OUTP? (@3)", "SYST:ERR?"]
    assert session.events == [
        "query:*IDN?",
        "write:OUTP OFF,(@1)",
        "query:OUTP? (@1)",
        "write:OUTP OFF,(@2)",
        "query:OUTP? (@2)",
        "write:OUTP OFF,(@3)",
        "query:OUTP? (@3)",
        "query:SYST:ERR?",
    ]
    assert payload["data"]["outputs"] == [
        {"channel": 1, "enabled": False},
        {"channel": 2, "enabled": True},
        {"channel": 3, "enabled": False},
    ]

def test_smoke_output_real_sends_safe_scpi_order_and_reads_final_state(
    monkeypatch,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "MEAS:VOLT? (@1)": "1.001",
            "MEAS:CURR? (@1)": "0.051",
            "OUTP? (@1)": "0",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)
    monkeypatch.setattr(output_run.time, "sleep", lambda seconds: None)

    assert (
        cli.main(
            [
                "smoke-output",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == [
        "CURR 0.05,(@1)",
        "VOLT 1,(@1)",
        "OUTP ON,(@1)",
        "OUTP OFF,(@1)",
    ]
    assert session.queries == [
        "*IDN?",
        "MEAS:VOLT? (@1)",
        "MEAS:CURR? (@1)",
        "OUTP? (@1)",
        "SYST:ERR?",
    ]
    assert session.events == [
        "query:*IDN?",
        "write:CURR 0.05,(@1)",
        "write:VOLT 1,(@1)",
        "write:OUTP ON,(@1)",
        "query:MEAS:VOLT? (@1)",
        "query:MEAS:CURR? (@1)",
        "write:OUTP OFF,(@1)",
        "query:OUTP? (@1)",
        "query:SYST:ERR?",
    ]
    assert payload["data"]["setpoints"] == {"current": 0.05, "voltage": 1.0}
    assert payload["data"]["measurements"] == {"voltage": 1.001, "current": 0.051}
    assert payload["data"]["output"]["final_enabled"] is False
    assert payload["data"]["safe_off_attempted"] is True

def test_smoke_output_real_attempts_output_off_after_measurement_failure(
    monkeypatch,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"MEAS:VOLT? (@1)": "not-a-number"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)
    monkeypatch.setattr(output_run.time, "sleep", lambda seconds: None)

    assert (
        cli.main(
            [
                "smoke-output",
                "--json",
                "--resource",
                "USB0::FAKE::E36312A::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 1
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == [
        "CURR 0.05,(@1)",
        "VOLT 1,(@1)",
        "OUTP ON,(@1)",
        "OUTP OFF,(@1)",
    ]
    assert session.queries == ["*IDN?", "MEAS:VOLT? (@1)"]
    assert session.events == [
        "query:*IDN?",
        "write:CURR 0.05,(@1)",
        "write:VOLT 1,(@1)",
        "write:OUTP ON,(@1)",
        "query:MEAS:VOLT? (@1)",
        "write:OUTP OFF,(@1)",
    ]
    assert payload["error"]["code"] == "smoke_output_failed"

@pytest.mark.parametrize(
    ("args", "expected_code"),
    [
        (["clear", "--json", "--resource", OUTPUT_RESOURCE], "status_clear_failed"),
        (["error", "--json", "--resource", OUTPUT_RESOURCE], "error_query_failed"),
        (
            ["measure", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "1"],
            "measurement_failed",
        ),
    ],
)
def test_safe_io_connection_failures_use_stable_error_codes(
    monkeypatch,
    capsys,
    args,
    expected_code,
) -> None:
    def fail_open_resource(*args, **kwargs):
        raise VisaConnectionError("not reachable")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert cli.main(args) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": True,
    }
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == expected_code
    assert payload["error"]["retryable"] is True
    assert captured.err == ""

def test_save_json_writes_same_envelope_as_stdout(tmp_path, capsys) -> None:
    save_path = tmp_path / "nested" / "snapshot.json"

    assert (
        cli.main(
            [
                "snapshot",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--save-json",
                str(save_path),
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    stdout_payload = json.loads(captured.out)
    saved_payload = json.loads(save_path.read_text(encoding="utf-8"))
    assert saved_payload == stdout_payload

def test_save_json_without_json_returns_argument_error(capsys, tmp_path) -> None:
    assert (
        cli.main(
            [
                "snapshot",
                "--simulate",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--save-json",
                str(tmp_path / "snapshot.json"),
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "--save-json requires --json" in payload["error"]["message"]

def test_measure_all_real_e36312a_uses_promoted_product_scope(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "MEAS:VOLT? (@1)": "1.1",
            "MEAS:CURR? (@1)": "0.11",
            "MEAS:VOLT? (@2)": "2.2",
            "MEAS:CURR? (@2)": "0.22",
            "MEAS:VOLT? (@3)": "3.3",
            "MEAS:CURR? (@3)": "0.33",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["measure-all", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries[0] == "*IDN?"
    assert len(payload["data"]["channels"]) == 3
    assert session.writes == []
    assert session.closed is True
    assert payload["error"] is None
    assert captured.err == ""

def test_measure_all_text_output_uses_promoted_product_scope(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "MEAS:VOLT? (@1)": "1.1",
            "MEAS:CURR? (@1)": "0.11",
            "MEAS:VOLT? (@2)": "2.2",
            "MEAS:CURR? (@2)": "0.22",
            "MEAS:VOLT? (@3)": "3.3",
            "MEAS:CURR? (@3)": "0.33",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["measure-all", "--resource", OUTPUT_RESOURCE]) == 0

    captured = capsys.readouterr()
    assert captured.out
    assert captured.err == ""

def test_measure_all_scpi_failure_surfaces_connection_error(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["measure-all", "--json", "--resource", OUTPUT_RESOURCE]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "measure_all_failed"

@pytest.mark.parametrize("idn_raw", [None, 123, {"model": "E36312A"}])
def test_measure_all_rejects_invalid_core_identity(monkeypatch, capsys, idn_raw) -> None:
    monkeypatch.setattr(
        readonly_commands.readonly_core,
        "run_readonly",
        lambda *args, **kwargs: {"resource": OUTPUT_RESOURCE, "channels": [], "idn_raw": idn_raw},
    )

    assert cli.main(["measure-all", "--simulate", "--json", "--resource", "USB0::SIM::E36312A::INSTR"]) == 3

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"] == {
        "type": "execution",
        "code": "invalid_core_result",
        "message": "measure-all Core result did not include a valid observed IDN string.",
        "retryable": False,
    }

def test_measure_all_dry_run_has_no_observed_identity(capsys) -> None:
    assert cli.main(["measure-all", "--dry-run", "--json", "--model", "keysight-e36312a"]) == 0
    assert "idn" not in json.loads(capsys.readouterr().out)["data"]

def test_clear_protection_requires_confirm_for_real_hardware(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened without --confirm")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert (
        cli.main(["clear-protection", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "1"])
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "confirmation_required"

def test_clear_protection_requires_channel_or_all_without_opening_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for invalid arguments")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert cli.main(["clear-protection", "--json", "--resource", OUTPUT_RESOURCE]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"

def test_clear_protection_real_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "clear-protection",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--all",
                "--confirm",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == ["OUTP:PROT:CLE (@1)", "OUTP:PROT:CLE (@2)", "OUTP:PROT:CLE (@3)"]
    assert payload["data"] == {"resource": "USB0::SIM::E36312A::INSTR", "cleared_channels": [1, 2, 3]}

def test_clear_protection_real_text_prints_cleared_channels(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "clear-protection",
                "--resource",
                OUTPUT_RESOURCE,
                "--all",
                "--confirm",
            ]
        )
        == 0
    )

    assert "Cleared channels: 1, 2, 3" in capsys.readouterr().out

def test_clear_protection_real_edu36311a_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "clear-protection",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "3",
                "--confirm",
            ]
        )
        == 0
    )

    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == ["OUTP:PROT:CLE (@3)"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"] == {
        "resource": "USB0::FAKE::EDU36311A::INSTR",
        "cleared_channels": [3],
    }

def test_clear_protection_dry_run_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for dry-run")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "clear-protection",
                "--dry-run",
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
    assert payload["data"]["plan"]["steps"] == [
        {"index": 1, "type": "scpi", "command": "OUTP:PROT:CLE (@2)"}
    ]

def test_clear_protection_execution_error_writes_json_envelope(monkeypatch, capsys) -> None:
    message = "clear-protection completed with instrument errors: ['queue error']"

    def fail(*_args, **_kwargs):
        raise CoreExecutionError(message)

    monkeypatch.setattr(readonly_commands.protection_core, "run_protection", fail)

    assert cli.main([
        "clear-protection", "--simulate", "--json", "--resource", OUTPUT_RESOURCE,
        "--channel", "1",
    ]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "clear_protection_failed"
    assert payload["error"]["message"] == message
    assert "Traceback" not in captured.err
