import json

import pytest

import powers_tool_core.connection as connection
import powers_tool_cli.cli as cli
from powers_tool_core.errors import VisaConnectionError

from tests.cli.cli_test_helpers import (
    FakeSession,
    expected_resource,
)
def test_list_resources_prints_backend_resources(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "list_resources",
        lambda *, backend=None: ("USB0::A::INSTR", "TCPIP0::B::INSTR"),
    )

    assert cli.main(["list-resources"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "USB0::A::INSTR\nTCPIP0::B::INSTR\n"
    assert captured.err == ""

def test_list_resources_prints_empty_message(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "list_resources", lambda *, backend=None: ())

    assert cli.main(["list-resources"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "No VISA resources found.\n"
    assert captured.err == ""

def test_list_resources_live_only_prints_openable_idn_resources(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "list_resources",
        lambda *, backend=None: ("USB0::FAKE::INSTR", "USB0::DEAD::INSTR"),
    )

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        if resource == "USB0::DEAD::INSTR":
            raise VisaConnectionError("not reachable")
        return FakeSession("KEYSIGHT,UNKNOWN,SERIAL0000,1.0")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert cli.main(["list-resources", "--live-only"]) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        "Live resources:\n"
        "  USB0::FAKE::INSTR\n"
        "    IDN: KEYSIGHT,UNKNOWN,SERIAL0000,1.0\n"
    )
    assert captured.err == ""

def test_list_resources_live_only_can_log_scpi(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "list_resources", lambda *, backend=None: ("USB0::FAKE::INSTR",))
    monkeypatch.setattr(
        cli,
        "open_resource",
        lambda resource, *, backend=None, timeout_ms=5000: FakeSession(
            "KEYSIGHT,UNKNOWN,SERIAL0000,1.0"
        ),
    )

    assert cli.main(["list-resources", "--live-only", "--log-scpi"]) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        "Live resources:\n"
        "  USB0::FAKE::INSTR\n"
        "    IDN: KEYSIGHT,UNKNOWN,SERIAL0000,1.0\n"
    )
    assert "USB0::FAKE::INSTR SCPI >> *IDN?" in captured.err
    assert "USB0::FAKE::INSTR SCPI << KEYSIGHT,UNKNOWN,SERIAL0000,1.0" in captured.err

def test_verify_prints_idn_response(monkeypatch, capsys) -> None:
    opened = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        opened.append((resource, backend, timeout_ms))
        return FakeSession("KEYSIGHT,UNKNOWN,SERIAL0000,1.0")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "verify",
                "--resource",
                "USB0::FAKE::INSTR",
                "--backend",
                "@py",
                "--timeout-ms",
                "1234",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert captured.out == "KEYSIGHT,UNKNOWN,SERIAL0000,1.0\n"
    assert captured.err == ""
    assert opened == [("USB0::FAKE::INSTR", "@py", 1234)]

@pytest.mark.parametrize("model", ["E36103B", "E36232A"])
def test_identity_diagnostics_report_descoped_raw_idn(monkeypatch, capsys, model: str) -> None:
    raw_idn = f"KEYSIGHT,{model},SERIAL0000,1.0"
    monkeypatch.setattr(cli, "list_resources", lambda *, backend=None: ("USB0::FAKE::INSTR",))
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: FakeSession(raw_idn))

    assert cli.main(["verify", "--resource", "USB0::FAKE::INSTR"]) == 0
    assert capsys.readouterr().out == f"{raw_idn}\n"

    assert cli.main(["list-resources", "--live-only"]) == 0
    captured = capsys.readouterr()
    assert raw_idn in captured.out
    assert captured.err == ""

def test_verify_serial_flags_are_forwarded_to_opener(monkeypatch, capsys) -> None:
    opened = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append((resource, backend, timeout_ms, kwargs))
        return FakeSession("KEYSIGHT,E3646A,SERIAL0000,1.0")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "verify",
                "--resource",
                "ASRL1::INSTR",
                "--serial-baud-rate",
                "9600",
                "--serial-data-bits",
                "8",
                "--serial-parity",
                "none",
                "--serial-stop-bits",
                "2",
                "--serial-flow-control",
                "dtr_dsr",
                "--serial-remote",
                "--serial-local-on-close",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert captured.out == "KEYSIGHT,E3646A,SERIAL0000,1.0\n"
    serial_options = opened[0][3]["serial_options"]
    assert serial_options.baud_rate == 9600
    assert serial_options.data_bits == 8
    assert serial_options.parity == "none"
    assert serial_options.stop_bits == "2"
    assert serial_options.flow_control == "dtr_dsr"
    assert opened[0][3]["serial_remote"] is True
    assert opened[0][3]["serial_local_on_close"] is True

@pytest.mark.parametrize(
    ("flag", "alias", "attribute", "expected"),
    [
        ("--serial-read-termination", "CR", "read_termination", "\r"),
        ("--serial-write-termination", "LF", "write_termination", "\n"),
        ("--serial-read-termination", "CRLF", "read_termination", "\r\n"),
    ],
)
def test_verify_serial_termination_aliases_are_normalized_for_runtime(
    monkeypatch,
    capsys,
    flag: str,
    alias: str,
    attribute: str,
    expected: str,
) -> None:
    opened = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append(kwargs)
        return FakeSession("KEYSIGHT,E3646A,SERIAL0000,1.0")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert cli.main(["verify", "--resource", "ASRL1::INSTR", flag, alias]) == 0

    capsys.readouterr()
    serial_options = opened[0]["serial_options"]
    assert getattr(serial_options, attribute) == expected

def test_verify_serial_termination_none_does_not_create_serial_options(monkeypatch, capsys) -> None:
    opened = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append(kwargs)
        return FakeSession("KEYSIGHT,E3646A,SERIAL0000,1.0")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert cli.main(["verify", "--resource", "ASRL1::INSTR", "--serial-read-termination", "NONE"]) == 0

    capsys.readouterr()
    assert "serial_options" not in opened[0]

def test_verify_json_serial_termination_alias_uses_normalized_request_value(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "open_resource",
        lambda resource, *, backend=None, timeout_ms=5000, **kwargs: FakeSession(
            "KEYSIGHT,E3646A,SERIAL0000,1.0"
        ),
    )

    assert (
        cli.main(
            [
                "verify",
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
    assert payload["request"]["serial_options"]["read_termination"] == "\r\n"
    assert payload["request"]["serial_options"]["write_termination"] == "\n"

def test_verify_json_omits_serial_options_when_not_provided(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "open_resource",
        lambda resource, *, backend=None, timeout_ms=5000: FakeSession(
            "KEYSIGHT,E3646A,SERIAL0000,1.0"
        ),
    )

    assert cli.main(["verify", "--resource", "ASRL1::INSTR", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert "serial_options" not in payload["request"]
    assert "serial_remote" not in payload["request"]
    assert "serial_local_on_close" not in payload["request"]

def test_verify_returns_failure_when_resource_cannot_be_queried(monkeypatch, capsys) -> None:
    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        raise VisaConnectionError("not reachable")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert cli.main(["verify", "--resource", "USB0::DEAD::INSTR"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Could not verify VISA resource: USB0::DEAD::INSTR" in captured.err

def test_list_resources_json_prints_machine_readable_payload(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "list_resources",
        lambda resource_manager=None, *, backend=None: ("USB0::A::INSTR",),
    )

    assert cli.main(["list-resources", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["metadata"]["duration_ms"] >= 0
    payload["metadata"] = {}
    assert payload == {
        "schema_version": 2,
        "ok": True,
        "status": "ok",
        "command": {"name": "list-resources"},
        "execution": {
            "mode": "real",
            "dry_run": False,
            "hardware_touched": False,
        },
        "request": {
            "backend": None,
            "timeout_ms": 5000,
            "live_only": False,
        },
        "data": {
            "resources": [expected_resource("USB0::A::INSTR")],
            "count": 1,
        },
        "warnings": [],
        "error": None,
        "metadata": {},
    }
    assert captured.err == ""

def test_list_resources_json_failure_uses_stable_error_code(monkeypatch, capsys) -> None:
    def fail_list_resources(resource_manager=None, *, backend=None):
        raise VisaConnectionError("backend unavailable")

    monkeypatch.setattr(cli, "list_resources", fail_list_resources)

    assert cli.main(["list-resources", "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 2
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["command"] == {"name": "list-resources"}
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"] == {
        "backend": None,
        "timeout_ms": 5000,
        "live_only": False,
    }
    assert payload["data"] is None
    assert payload["warnings"] == []
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "resource_list_failed"
    assert payload["error"]["retryable"] is True
    assert payload["metadata"]["duration_ms"] >= 0
    assert captured.err == ""

def test_verify_json_prints_machine_readable_payload(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "open_resource",
        lambda resource, resource_manager=None, *, backend=None, timeout_ms=5000: FakeSession(
            "KEYSIGHT,UNKNOWN,SERIAL0000,1.0"
        ),
    )

    assert cli.main(["verify", "--resource", "USB0::FAKE::INSTR", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["metadata"]["duration_ms"] >= 0
    payload["metadata"] = {}
    assert payload == {
        "schema_version": 2,
        "ok": True,
        "status": "ok",
        "command": {"name": "verify"},
        "execution": {
            "mode": "real",
            "dry_run": False,
            "hardware_touched": True,
        },
        "request": {
            "resource": "USB0::FAKE::INSTR",
            "backend": None,
            "timeout_ms": 5000,
        },
        "data": {
            "resource": expected_resource(
                "USB0::FAKE::INSTR",
                reachable=True,
                idn="KEYSIGHT,UNKNOWN,SERIAL0000,1.0",
            ),
        },
        "warnings": [],
        "error": None,
        "metadata": {},
    }
    assert captured.err == ""

def test_verify_json_failure_prints_error_payload(monkeypatch, capsys) -> None:
    def fake_open_resource(resource, resource_manager=None, *, backend=None, timeout_ms=5000):
        raise VisaConnectionError("not reachable")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert cli.main(["verify", "--resource", "USB0::DEAD::INSTR", "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 2
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["command"] == {"name": "verify"}
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": True,
    }
    assert payload["request"] == {
        "resource": "USB0::DEAD::INSTR",
        "backend": None,
        "timeout_ms": 5000,
    }
    assert payload["data"] is None
    assert payload["warnings"] == []
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "resource_unreachable"
    assert payload["error"]["retryable"] is True
    assert "USB0::DEAD::INSTR" in payload["error"]["message"]
    assert payload["metadata"]["duration_ms"] >= 0
    assert captured.err == ""

def test_verify_json_missing_resource_returns_validation_payload(capsys) -> None:
    assert cli.main(["verify", "--json"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["metadata"]["duration_ms"] >= 0
    payload["metadata"] = {}
    assert payload == {
        "schema_version": 2,
        "ok": False,
        "status": "error",
        "command": {"name": "verify"},
        "execution": {
            "mode": "real",
            "dry_run": False,
            "hardware_touched": False,
        },
        "request": {
            "resource": None,
            "backend": None,
            "timeout_ms": 5000,
        },
        "data": None,
        "warnings": [],
        "error": {
            "type": "validation",
            "code": "argument_error",
            "message": "the following arguments are required: --resource",
            "retryable": False,
        },
        "metadata": {},
    }
    assert captured.err == ""

def test_verify_model_maps_to_live_expected_model_id() -> None:
    args = cli.build_parser().parse_args(
        [
            "verify",
            "--json",
            "--resource",
            "ASRL1::INSTR",
            "--model",
            "keysight-e3646a",
        ]
    )

    request = cli._target_core_request_for_args(args)

    assert request.runtime.expected_model_id == "keysight-e3646a"
    assert request.runtime.planning_model_id is None

def test_verify_expected_model_mismatch_stops_after_idn(monkeypatch, capsys) -> None:
    session = FakeSession("Agilent Technologies,E3646A,0,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "verify",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--model",
                "keysight-e36312a",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "Expected model_id keysight-e36312a" in payload["error"]["message"]
    assert payload["execution"]["hardware_touched"] is True
    assert session.queries == ["*IDN?"]
    assert session.writes == []

def test_list_resources_simulate_does_not_create_real_resource_manager(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert cli.main(["list-resources", "--simulate"]) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        "USB0::SIM::E36312A::INSTR\n"
        "USB0::SIM::EDU36311A::INSTR\n"
        "ASRL1::SIM::E3646A::INSTR\n"
        "ASRL1::SIM::PSM2010::INSTR\n"
    )
    assert captured.err == ""

def test_list_resources_simulate_live_only_json_logs_scpi_to_stderr(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert cli.main(["list-resources", "--simulate", "--live-only", "--json", "--log-scpi"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 2
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["command"] == {"name": "list-resources"}
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"] == {
        "backend": None,
        "timeout_ms": 5000,
        "live_only": True,
    }
    assert payload["data"]["resources"] == [
        expected_resource(
            "USB0::SIM::E36312A::INSTR",
            simulated=True,
            reachable=True,
            idn="KEYSIGHT,E36312A,SIM000003,1.0",
        ),
            expected_resource(
                "USB0::SIM::EDU36311A::INSTR",
                simulated=True,
                reachable=True,
                idn="KEYSIGHT,EDU36311A,SIM000004,1.0",
            ),
            expected_resource(
                "ASRL1::SIM::E3646A::INSTR",
                interface="ASRL",
                simulated=True,
                reachable=True,
                idn="KEYSIGHT,E3646A,SIM000005,1.0",
            ),
            expected_resource(
                "ASRL1::SIM::PSM2010::INSTR",
                interface="ASRL",
                simulated=True,
                reachable=True,
                idn="GW.Inc,PSM-2010,SIM000006,FW1.00",
            ),
        ]
    assert payload["data"]["count"] == 4
    assert payload["warnings"] == []
    assert payload["error"] is None
    assert payload["metadata"]["duration_ms"] >= 0
    assert "SCPI >> *IDN?" in captured.err
    assert "KEYSIGHT,E36312A,SIM000003,1.0" in captured.err

def test_verify_simulate_json_does_not_create_real_resource_manager(monkeypatch, capsys) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "verify",
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
    assert payload["schema_version"] == 2
    assert payload["command"] == {"name": "verify"}
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"] == {
        "resource": "USB0::SIM::E36312A::INSTR",
        "backend": None,
        "timeout_ms": 5000,
    }
    assert payload["data"] == {
        "resource": expected_resource(
            "USB0::SIM::E36312A::INSTR",
            simulated=True,
            reachable=True,
            idn="KEYSIGHT,E36312A,SIM000003,1.0",
        ),
    }
    assert captured.err == ""
