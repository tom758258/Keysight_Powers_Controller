import json

import pytest

import powers_tool_core.connection as connection
import powers_tool_cli.cli as cli
import powers_tool_cli.cli_runtime as cli_runtime

from tests.cli.cli_test_helpers import (
    OUTPUT_RESOURCE,
    FakeSession,
)
def test_status_real_reads_errors_then_outputs(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "SYST:ERR?": ['-100,"Command error"', '0,"No error"'],
            "OUTP? (@1)": "ON",
            "OUTP? (@2)": "OFF",
            "OUTP? (@3)": "1",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == [
        "*IDN?",
        "SYST:ERR?",
        "SYST:ERR?",
        "OUTP? (@1)",
        "OUTP? (@2)",
        "OUTP? (@3)",
    ]
    assert session.closed is True
    assert payload["data"] == {
        "resource": OUTPUT_RESOURCE,
        "errors": ['-100,"Command error"'],
        "read_count": 2,
        "outputs": [
            {"channel": 1, "enabled": True},
            {"channel": 2, "enabled": False},
            {"channel": 3, "enabled": True},
        ],
    }

def test_status_real_edu36311a_reads_errors_then_outputs(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "OUTP? (@1)": "OFF",
            "OUTP? (@2)": "ON",
            "OUTP? (@3)": "0",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--json", "--resource", "USB0::FAKE::EDU36311A::INSTR"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == [
        "*IDN?",
        "SYST:ERR?",
        "OUTP? (@1)",
        "OUTP? (@2)",
        "OUTP? (@3)",
    ]
    assert payload["data"]["outputs"] == [
        {"channel": 1, "enabled": False},
        {"channel": 2, "enabled": True},
        {"channel": 3, "enabled": False},
    ]

def test_status_real_e3646a_reads_errors_then_outputs_with_preselection(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E3646A,SERIAL0000,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "INST:NSEL?": ["1", "1"],
            "OUTP?": ["ON", "OFF"],
        },
    )
    opened = []

    def fake_open_resource(resource, *args, **kwargs):
        opened.append((resource, kwargs))
        return session

    monkeypatch.setattr(cli_runtime, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "read-status",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--serial-baud-rate",
                "9600",
                "--serial-read-termination",
                "CRLF",
                "--serial-write-termination",
                "LF",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.events == [
        "query:*IDN?",
        "query:SYST:ERR?",
        "query:INST:NSEL?",
        "write:INST:NSEL 1",
        "query:OUTP?",
        "write:INST:NSEL 1",
        "query:INST:NSEL?",
        "write:INST:NSEL 2",
        "query:OUTP?",
        "write:INST:NSEL 1",
    ]
    assert not any("(@" in event or "PROT" in event or "TRIG" in event for event in session.events)
    assert payload["data"]["outputs"] == [
        {"channel": 1, "enabled": True},
        {"channel": 2, "enabled": False},
    ]
    assert opened[0][0] == "ASRL1::INSTR"
    serial_options = opened[0][1]["serial_options"]
    assert serial_options.baud_rate == 9600
    assert serial_options.read_termination == "\r\n"
    assert serial_options.write_termination == "\n"

def test_validate_readonly_simulate_json_does_not_create_real_resource_manager(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "validate-readonly",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["resource"]["idn"]["model"] == "EDU36311A"
    assert payload["data"]["driver"]["class"] == "EDU36311APowerSupply"
    assert payload["data"]["capabilities"]["channels"] == [1, 2, 3]
    assert payload["data"]["outputs"] == [
        {"channel": 1, "enabled": False},
        {"channel": 2, "enabled": False},
        {"channel": 3, "enabled": False},
    ]

@pytest.mark.parametrize(
    ("idn", "resource", "driver_class"),
    [
        ("KEYSIGHT,E36312A,SERIAL0000,1.0", OUTPUT_RESOURCE, "E36312APowerSupply"),
        ("KEYSIGHT,EDU36311A,SERIAL0000,1.0", "USB0::FAKE::EDU36311A::INSTR", "EDU36311APowerSupply"),
    ],
)
def test_validate_readonly_real_sends_expected_scpi_for_supported_models(
    monkeypatch,
    capsys,
    idn,
    resource,
    driver_class,
) -> None:
    session = FakeSession(
        idn=idn,
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "OUTP? (@1)": "OFF",
            "OUTP? (@2)": "ON",
            "OUTP? (@3)": "0",
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.10",
            "VOLT? (@3)": "3.0",
            "CURR? (@3)": "0.15",
            "MEAS:VOLT? (@1)": "1.1",
            "MEAS:CURR? (@1)": "0.11",
            "MEAS:VOLT? (@2)": "2.2",
            "MEAS:CURR? (@2)": "0.22",
            "MEAS:VOLT? (@3)": "3.3",
            "MEAS:CURR? (@3)": "0.33",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["validate-readonly", "--json", "--resource", resource]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == [
        "*IDN?",
        "SYST:ERR?",
        "OUTP? (@1)",
        "OUTP? (@2)",
        "OUTP? (@3)",
        "VOLT? (@1)",
        "CURR? (@1)",
        "VOLT? (@2)",
        "CURR? (@2)",
        "VOLT? (@3)",
        "CURR? (@3)",
        "MEAS:VOLT? (@1)",
        "MEAS:CURR? (@1)",
        "MEAS:VOLT? (@2)",
        "MEAS:CURR? (@2)",
        "MEAS:VOLT? (@3)",
        "MEAS:CURR? (@3)",
    ]
    assert session.closed is True
    assert payload["data"]["driver"]["class"] == driver_class
    assert payload["data"]["read_count"] == 1
    assert payload["data"]["outputs"] == [
        {"channel": 1, "enabled": False},
        {"channel": 2, "enabled": True},
        {"channel": 3, "enabled": False},
    ]
    assert payload["data"]["readback"][1] == {
        "channel": 2,
        "setpoints": {"voltage": 2.0, "current": 0.1},
    }
    assert payload["data"]["measurements"][2] == {
        "channel": 3,
        "measurements": {"voltage": 3.3, "current": 0.33},
    }

def test_validate_readonly_rejects_generic_model(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,UNKNOWN,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["validate-readonly", "--json", "--resource", OUTPUT_RESOURCE]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "unsupported_live_scope"

def test_validate_readonly_invalid_max_errors_is_argument_error(capsys) -> None:
    assert (
        cli.main(
            [
                "validate-readonly",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--max-errors",
                "0",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert payload["error"]["message"] == "argument --max-errors: max-errors must be a positive integer"

def test_validate_readonly_log_scpi_to_stderr_without_corrupting_json(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "OUTP? (@1)": "OFF",
            "OUTP? (@2)": "OFF",
            "OUTP? (@3)": "OFF",
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.10",
            "VOLT? (@3)": "3.0",
            "CURR? (@3)": "0.15",
            "MEAS:VOLT? (@1)": "1.1",
            "MEAS:CURR? (@1)": "0.11",
            "MEAS:VOLT? (@2)": "2.2",
            "MEAS:CURR? (@2)": "0.22",
            "MEAS:VOLT? (@3)": "3.3",
            "MEAS:CURR? (@3)": "0.33",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["validate-readonly", "--json", "--resource", OUTPUT_RESOURCE, "--log-scpi"]) == 0

    captured = capsys.readouterr()
    json.loads(captured.out)
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> MEAS:CURR? (@3)" in captured.err

def test_validate_readonly_save_json_writes_stdout_envelope(tmp_path, capsys) -> None:
    json_path = tmp_path / "validate-readonly.json"

    assert (
        cli.main(
            [
                "validate-readonly",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--save-json",
                str(json_path),
            ]
        )
        == 0
    )

    stdout_payload = json.loads(capsys.readouterr().out)
    saved_payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved_payload == stdout_payload

def test_status_real_one_channel_text(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "OUTP? (@2)": "OFF",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--resource", OUTPUT_RESOURCE, "--channel", "2"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "Errors: none\nChannel 2: Output enabled: false\n"

def test_status_unsupported_channel_is_argument_error(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "99"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "argument_error"

def test_status_invalid_max_errors_is_argument_error(capsys) -> None:
    assert (
        cli.main(
            [
                "read-status",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--max-errors",
                "0",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "argument_error"

def test_status_scpi_failure_uses_status_failed(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"SYST:ERR?": '0,"No error"'},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--json", "--resource", OUTPUT_RESOURCE]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "status_failed"

def test_readback_real_e36312a_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.10",
            "VOLT? (@3)": "3.0",
            "CURR? (@3)": "0.15",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["readback", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == [
        "*IDN?",
        "VOLT? (@1)",
        "CURR? (@1)",
        "VOLT? (@2)",
        "CURR? (@2)",
        "VOLT? (@3)",
        "CURR? (@3)",
    ]
    assert session.closed is True
    assert payload["data"]["channels"] == [
        {"channel": 1, "setpoints": {"voltage": 1.0, "current": 0.05}},
        {"channel": 2, "setpoints": {"voltage": 2.0, "current": 0.1}},
        {"channel": 3, "setpoints": {"voltage": 3.0, "current": 0.15}},
    ]

def test_readback_real_edu36311a_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
        query_responses={
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.10",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "readback",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "2",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "VOLT? (@2)", "CURR? (@2)"]
    assert payload["data"]["channels"] == [
        {"channel": 2, "setpoints": {"voltage": 2.0, "current": 0.1}},
    ]

def test_readback_real_forwards_serial_options_to_opener(monkeypatch, capsys) -> None:
    opened = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append((resource, backend, timeout_ms, kwargs))
        return FakeSession(
            idn="KEYSIGHT,E3646A,SERIAL0000,1.0",
            query_responses={
                "INST:NSEL?": "1",
                "VOLT?": "1.0",
                "CURR?": "0.05",
            },
        )

    monkeypatch.setattr(cli_runtime, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "readback",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--channel",
                "1",
                "--serial-baud-rate",
                "9600",
                "--serial-read-termination",
                "\\n",
                "--serial-write-termination",
                "\\r",
                "--serial-remote",
                "--serial-local-on-close",
            ]
        )
        == 0
    )

    json.loads(capsys.readouterr().out)
    serial_options = opened[0][3]["serial_options"]
    assert serial_options.baud_rate == 9600
    assert serial_options.read_termination == "\\n"
    assert serial_options.write_termination == "\\r"
    assert opened[0][3]["serial_remote"] is True
    assert opened[0][3]["serial_local_on_close"] is True

def test_readback_real_e3646a_preselects_and_restores_channel(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E3646A,SERIAL0000,1.0",
        query_responses={
            "INST:NSEL?": "1",
            "VOLT?": "2.0",
            "CURR?": "0.10",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "readback",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--channel",
                "2",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.events == [
        "query:*IDN?",
        "query:INST:NSEL?",
        "write:INST:NSEL 2",
        "query:VOLT?",
        "write:INST:NSEL 1",
        "query:INST:NSEL?",
        "write:INST:NSEL 2",
        "query:CURR?",
        "write:INST:NSEL 1",
    ]
    assert payload["data"]["channels"] == [
        {"channel": 2, "setpoints": {"voltage": 2.0, "current": 0.1}},
    ]

def test_readback_real_e3646a_rejects_channel_outside_driver_capabilities(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["readback", "--json", "--resource", "ASRL1::INSTR", "--channel", "3"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "supported: (1, 2)" in payload["error"]["message"]

def test_readback_serial_remote_local_log_scpi_stays_on_stderr(monkeypatch, capsys) -> None:
    class FakeSerialSession(FakeSession):
        def __init__(self, resource: str, scpi_logger):
            super().__init__(
                idn="KEYSIGHT,E3646A,SERIAL0000,1.0",
                query_responses={
                    "INST:NSEL?": "1",
                    "VOLT?": "1.0",
                    "CURR?": "0.05",
                },
            )
            self.resource = resource
            self.scpi_logger = scpi_logger

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            if self.scpi_logger is not None:
                self.scpi_logger(self.resource, ">>", "SYST:LOC")
            super().__exit__(exc_type, exc, traceback)

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000, **kwargs):
        scpi_logger = kwargs.get("scpi_logger")
        if kwargs.get("serial_remote") and scpi_logger is not None:
            scpi_logger(resource, ">>", "SYST:REM")
        return FakeSerialSession(resource, scpi_logger if kwargs.get("serial_local_on_close") else None)

    monkeypatch.setattr(cli_runtime, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "readback",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--channel",
                "1",
                "--log-scpi",
                "--serial-remote",
                "--serial-local-on-close",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    json.loads(captured.out)
    assert "ASRL1::INSTR SCPI >> SYST:REM" in captured.err
    assert "ASRL1::INSTR SCPI >> SYST:LOC" in captured.err

def test_readback_log_scpi_to_stderr_without_corrupting_json(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "readback",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    json.loads(captured.out)
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> VOLT? (@1)" in captured.err
