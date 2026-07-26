import json
import csv
from types import SimpleNamespace

import pytest

import powers_tool_core.connection as connection
import powers_tool_cli.cli as cli
from powers_tool_core.core import CommandCancelled, CoreExecutionError, StopCleanupError
from powers_tool_core.errors import VisaConnectionError


OUTPUT_RESOURCE = "USB0::SIM::E36312A::INSTR"
WRITE_VERIFICATION_REQUEST_DEFAULTS = {
    "settle_ms": 0,
    "verify_after_write": False,
    "setpoint_voltage_tolerance": 0.001,
    "setpoint_current_tolerance": 0.001,
}
SERIAL_TERMINATION_ARGS = [
    "--serial-read-termination",
    "CRLF",
    "--serial-write-termination",
    "LF",
    "--serial-remote",
    "--serial-local-on-close",
]


def test_root_version_prints_package_version(capsys) -> None:
    assert cli.main(["--version"]) == 0

    captured = capsys.readouterr()

    assert captured.out.strip() == f"powers-tool {cli._package_version()}"
    assert captured.err == ""


def test_root_help_uses_vendor_neutral_product_identity(capsys) -> None:
    assert cli.main(["--help"]) == 0

    captured = capsys.readouterr()

    assert "Powers Tool" in captured.out
    assert "supported DC power supplies" in captured.out
    assert "Keysight DC power supplies" not in captured.out


def test_cli_missing_distribution_metadata_uses_nonrelease_fallback(monkeypatch) -> None:
    from importlib import metadata
    import runpy

    def missing_distribution(_name: str) -> str:
        raise metadata.PackageNotFoundError("powers-tool")

    monkeypatch.setattr(cli.importlib.metadata, "version", missing_distribution)

    package_namespace = runpy.run_path("src/powers_tool_cli/__init__.py")

    assert package_namespace["__version__"] == "0+unknown"
    assert package_namespace["__version__"] not in {"1.0.0", "2.0.0"}
    assert cli._package_version() == "0+unknown"
    assert cli._package_version() not in {"1.0.0", "2.0.0"}


class FakeSession:
    def __init__(
        self,
        idn: str = "KEYSIGHT,E36312A,SERIAL0000,1.0",
        *,
        query_responses: dict[str, list[str] | str] | None = None,
    ) -> None:
        self.idn = idn
        self.query_responses = query_responses or {}
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.events: list[str] = []
        self.closed = False

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.closed = True

    def identify(self) -> str:
        return self.idn

    def write(self, command: str) -> None:
        self.writes.append(command)
        self.events.append(f"write:{command}")

    def query(self, command: str) -> str:
        self.queries.append(command)
        self.events.append(f"query:{command}")
        if command == "*IDN?":
            return self.idn
        if command == "SYST:ERR?":
            response = self.query_responses.get(command)
            if isinstance(response, list):
                if response:
                    return response.pop(0)
                return '0,"No error"'
            if response is not None:
                return response
            return '0,"No error"'
        response = self.query_responses.get(command)
        if isinstance(response, list):
            if response:
                return response.pop(0)
            return '0,"No error"'
        if response is not None:
            return response
        raise VisaConnectionError(f"No fake response for {command!r}")


def assert_live_scope_rejected(payload: dict[str, object], session: FakeSession) -> None:
    assert payload["ok"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "unsupported_live_scope"
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


@pytest.mark.parametrize(
    "argv",
    [
        ["protection-status", "--json", "--resource", "GPIB0::1::INSTR"],
        ["snapshot", "--json", "--resource", "GPIB0::1::INSTR"],
        ["output-on", "--json", "--resource", "ASRL1::INSTR", "--channel", "1"],
        ["trigger-pulse", "--json", "--resource", "ASRL1::INSTR", "--pin", "1"],
    ],
)
def test_live_policy_rejections_use_stable_validation_code(monkeypatch, capsys, argv) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(argv) == 2

    assert_live_scope_rejected(json.loads(capsys.readouterr().out), session)


def test_hidden_validation_mode_is_parser_only_and_allows_registered_pending_scope(monkeypatch, capsys) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "measure",
            "--resource",
            "TCPIP0::192.0.2.1::INSTR",
            "--channel",
            "1",
            "--validation-allow-pending-live-support",
        ]
    )
    assert args.validation_allow_pending_live_support is True

    with pytest.raises(SystemExit):
        parser.parse_args(["measure", "--help"])
    assert "--validation-allow-pending-live-support" not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    assert "--validation-allow-pending-live-support" not in capsys.readouterr().out

    product_session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: product_session)
    assert (
        cli.main(
            [
                "measure",
                "--json",
                "--resource",
                "TCPIP0::192.0.2.1::INSTR",
                "--backend",
                "@py",
                "--channel",
                "1",
            ]
        )
        == 2
    )
    assert_live_scope_rejected(json.loads(capsys.readouterr().out), product_session)

    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"MEAS:VOLT?": "1.0", "MEAS:CURR?": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    assert (
        cli.main(
            [
                "measure",
                "--json",
                "--resource",
                "TCPIP0::192.0.2.1::INSTR",
                "--backend",
                "@py",
                "--channel",
                "1",
                "--validation-allow-pending-live-support",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert session.queries == ["*IDN?", "MEAS:VOLT?", "MEAS:CURR?"]


def test_hidden_validation_mode_keeps_no_hardware_feature_locks(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("dry-run must not open VISA")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)
    assert (
        cli.main(
            [
                "trigger-step",
                "--dry-run",
                "--model",
                "keysight-edu36311a",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--source",
                "bus",
                "--validation-allow-pending-live-support",
                "--json",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "validation"


@pytest.mark.parametrize(
    "argv",
    [
        ["measure", "--resource", OUTPUT_RESOURCE, "--channel", "1"],
        ["read-status", "--resource", OUTPUT_RESOURCE],
        ["set", "--resource", OUTPUT_RESOURCE, "--channel", "1", "--voltage", "1", "--current", "0.1"],
        ["protection-status", "--resource", OUTPUT_RESOURCE],
        ["snapshot", "--resource", OUTPUT_RESOURCE],
        ["restore-from-snapshot", "--resource", OUTPUT_RESOURCE, "--snapshot", "snapshot.json", "--channel", "1"],
        ["trigger-abort", "--resource", OUTPUT_RESOURCE, "--channel", "1"],
        ["ramp-list", "--resource", OUTPUT_RESOURCE, "--segment", "1", "0.1", "0", "0.5", "0.5", "0", "0"],
        ["sequence", "--resource", OUTPUT_RESOURCE, "--file", "sequence.yaml"],
        ["doctor", "--resource", OUTPUT_RESOURCE],
        ["capabilities", "--resource", OUTPUT_RESOURCE],
    ],
)
def test_hidden_validation_argument_is_accepted_and_suppressed_for_each_parser_family(capsys, argv) -> None:
    parser = cli.build_parser()
    args = parser.parse_args([*argv, "--validation-allow-pending-live-support"])
    assert args.validation_allow_pending_live_support is True

    with pytest.raises(SystemExit):
        parser.parse_args([argv[0], "--help"])
    assert "--validation-allow-pending-live-support" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "builder"),
    [
        (["set", "--resource", OUTPUT_RESOURCE, "--channel", "1", "--voltage", "1", "--current", "0.1"], cli._operation_request_for_args),
        (["read-status", "--resource", OUTPUT_RESOURCE], cli._target_core_request_for_args),
        (["trigger-abort", "--resource", OUTPUT_RESOURCE, "--channel", "1"], cli._trigger_request_for_args),
        (["ramp-list", "--resource", OUTPUT_RESOURCE, "--segment", "1", "0.1", "0", "0.5", "0.5", "0", "0"], cli._ramp_list_request_for_args),
        (["sequence", "--resource", OUTPUT_RESOURCE, "--file", "sequence.yaml"], cli._sequence_request_for_args),
    ],
)
@pytest.mark.parametrize("hidden", [False, True])
def test_cli_request_builders_propagate_only_policy_mode(argv, builder, hidden: bool) -> None:
    parser = cli.build_parser()
    args = parser.parse_args([*argv, *(["--validation-allow-pending-live-support"] if hidden else [])])
    request = builder(args)

    assert request.runtime.support_policy_mode == ("validation" if hidden else "product")
    assert "validation_allow_pending_live_support" not in request.parameters


def test_restore_request_propagates_validation_mode_without_public_request_parameter(monkeypatch, capsys) -> None:
    captured = {}

    def fake_run_restore(request, **kwargs):
        captured["request"] = request
        return {"resource": request.runtime.resource, "restored_channels": [1], "plan": {}}

    monkeypatch.setattr(cli.restore_core, "run_restore", fake_run_restore)
    assert (
        cli.main(
            [
                "restore-from-snapshot",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--snapshot",
                "snapshot.json",
                "--channel",
                "1",
                "--confirm",
                "--validation-allow-pending-live-support",
            ]
        )
        == 0
    )
    request = captured["request"]
    assert request.runtime.support_policy_mode == "validation"
    assert "validation_allow_pending_live_support" not in request.parameters
    payload = json.loads(capsys.readouterr().out)
    assert "validation_allow_pending_live_support" not in json.dumps(payload)


def test_restore_json_preserves_observed_identity_from_core(monkeypatch, capsys) -> None:
    reported_identity = {
        "manufacturer": "Keysight Technologies",
        "model": "E36312A",
        "serial": "SN",
        "firmware": "2.10",
        "parse_ok": True,
    }
    resolved_identity = {
        "vendor_id": "keysight",
        "model_id": "keysight-e36312a",
        "model_name": "E36312A",
        "display_name": "Keysight E36312A",
    }

    monkeypatch.setattr(
        cli.restore_core,
        "run_restore",
        lambda request, **kwargs: {
            "resource": request.runtime.resource,
            "restored_channels": [1],
            "plan": {},
            "reported_identity": reported_identity,
            "resolved_identity": resolved_identity,
        },
    )

    assert (
        cli.main(
            [
                "restore-from-snapshot",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--snapshot",
                "snapshot.json",
                "--channel",
                "1",
                "--confirm",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["reported_identity"] == reported_identity
    assert payload["data"]["resolved_identity"] == resolved_identity


def expected_idn(raw: str) -> dict[str, object]:
    manufacturer, model, serial, firmware = raw.split(",", maxsplit=3)
    return {
        "raw": raw,
        "manufacturer": manufacturer,
        "model": model,
        "serial": serial,
        "firmware": firmware,
        "parse_ok": True,
    }


def expected_resource(
    name: str,
    *,
    interface: str = "USB",
    simulated: bool = False,
    reachable: bool | None = None,
    idn: str | None = None,
) -> dict[str, object]:
    identity_by_model = {
        "E36312A": ("keysight", "keysight-e36312a"),
        "EDU36311A": ("keysight", "keysight-edu36311a"),
        "E3646A": ("keysight", "keysight-e3646a"),
    }
    reported_model = idn.split(",")[1] if idn is not None else None
    vendor_id, model_id = identity_by_model.get(reported_model, (None, None))
    return {
        "name": name,
        "interface": interface,
        "simulated": simulated,
        "reachable": reachable,
        "idn": expected_idn(idn) if idn is not None else None,
        "vendor_id": vendor_id,
        "model_id": model_id,
    }


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


def test_parser_error_with_save_json_writes_existing_error_envelope(
    monkeypatch, tmp_path, capsys
) -> None:
    save_path = tmp_path / "parser-error.json"

    def fail_open(*args, **kwargs):
        raise AssertionError("parser failures must not open hardware")

    monkeypatch.setattr(cli, "open_resource", fail_open)

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
        ]
    assert payload["data"]["count"] == 3
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


def test_clear_dry_run_json_does_not_open_visa(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

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

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

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
def test_measure_simulate_uses_model_driver_for_first_target_channels(
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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--json", "--resource", OUTPUT_RESOURCE]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert payload["error"]["code"] == "unsupported_model_for_status"
    assert model in payload["error"]["message"]
    assert "de-scoped and not active supported" in payload["error"]["message"]
    assert "blocked from generic fallback" in payload["error"]["message"]
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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

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

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

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


def output_command_args(
    command: str,
    *,
    channel: str = "1",
    voltage: str = "1",
    current: str = "0.05",
    duration_ms: str = "500",
) -> list[str]:
    args = [command, "--resource", OUTPUT_RESOURCE, "--channel", channel]
    if command in {"set", "apply"}:
        args.extend(["--voltage", voltage, "--current", current])
    if command == "cycle-output":
        args.extend(["--duration-ms", duration_ms])
    return args


def write_safety_config(tmp_path, content: str | None = None) -> str:
    config_path = tmp_path / "powers-tool.toml"
    config_path.write_text(
        content
        or """
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2, 3]
""".strip(),
        encoding="utf-8",
    )
    return str(config_path)


@pytest.mark.parametrize(
    ("args", "expected_actions"),
    [
        (output_command_args("set"), ["set_current_limit", "set_voltage"]),
        (output_command_args("output-on"), ["output_on"]),
        (output_command_args("output-off"), ["output_off"]),
        (output_command_args("safe-off"), ["safe_off"]),
        (output_command_args("output-state"), ["output_state"]),
        (
            output_command_args("cycle-output", duration_ms="250"),
            ["output_on", "sleep", "output_off"],
        ),
        (output_command_args("apply"), ["set_current_limit", "set_voltage", "output_on"]),
    ],
)
def test_output_commands_dry_run_json_emit_logical_plans(
    args,
    expected_actions,
    capsys,
) -> None:
    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 2
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": True,
        "hardware_touched": False,
    }
    assert payload["request"]["safety_config"] is None
    assert payload["request"]["resource_alias"] is None
    assert payload["data"]["plan"]["operation"] == {"name": args[0]}
    assert payload["data"]["plan"]["target"] == {
        "resource": OUTPUT_RESOURCE,
        "planning_model_id": "keysight-e36312a",
        "planning_profile_id": None,
        "channel": 1,
    }
    assert payload["data"]["plan"]["hardware_touched"] is False
    steps = payload["data"]["plan"]["steps"]
    assert [step["action"] for step in steps] == expected_actions
    assert all(step["type"] == "driver_action" for step in steps)
    assert all("command" not in step for step in steps)
    assert captured.err == ""


def test_dry_run_without_model_or_sim_resource_fails(capsys) -> None:
    assert cli.main(["output-on", "--dry-run", "--json", "--channel", "1"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "require planning_model_id" in payload["error"]["message"]


def test_simulate_model_derives_resource_and_rejects_mismatch(capsys) -> None:
    assert cli.main(["output-on", "--simulate", "--json", "--model", "keysight-e36312a", "--channel", "1"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["target"]["planning_model_id"] == "keysight-e36312a"
    assert payload["data"]["plan"]["target"]["resource"] == "USB0::SIM::E36312A::INSTR"

    assert (
        cli.main(
            [
                "output-on",
                "--simulate",
                "--json",
                "--model",
                "keysight-e3646a",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "1",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert "does not match" in payload["error"]["message"]


def test_apply_simulate_rejects_explicit_non_sim_resource_before_hardware_io(monkeypatch, capsys) -> None:
    def fail_open(*args, **kwargs):
        raise AssertionError("must not open VISA")

    monkeypatch.setattr(cli, "open_resource", fail_open)

    assert (
        cli.main(
            [
                "apply",
                "--simulate",
                "--json",
                "--model",
                "keysight-e3646a",
                "--resource",
                "ASRL7::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "requires a deterministic SIM resource" in payload["error"]["message"]


def test_live_generic_expected_model_fails_before_hardware_io(monkeypatch, capsys) -> None:
    def fail_open(*args, **kwargs):
        raise AssertionError("must not open VISA")

    monkeypatch.setattr(cli, "open_resource", fail_open)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--model",
                "GENERIC",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "1",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert "invalid expected_model_id" in payload["error"]["message"]


def test_e3646a_dry_run_all_expands_two_channels_and_rejects_three(capsys) -> None:
    assert cli.main(["output-on", "--dry-run", "--json", "--model", "keysight-e3646a", "--channel", "all"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["target"]["planning_model_id"] == "keysight-e3646a"
    assert [step["parameters"]["channel"] for step in payload["data"]["plan"]["steps"]] == [1, 2]

    assert cli.main(["output-on", "--dry-run", "--json", "--model", "keysight-e3646a", "--channel", "3"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert "channel 3" in payload["error"]["message"]


def test_invalid_model_fails_as_argument_error(capsys) -> None:
    assert cli.main(["output-on", "--dry-run", "--json", "--model", "not-a-model", "--channel", "1"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "invalid planning_model_id" in payload["error"]["message"]


def test_cycle_output_dry_run_json_includes_duration(capsys) -> None:
    args = output_command_args("cycle-output", duration_ms="250")

    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["duration_ms"] == 250
    assert payload["data"]["plan"]["steps"][1] == {
        "index": 2,
        "type": "driver_action",
        "action": "sleep",
        "parameters": {"duration_ms": 250},
    }


def test_apply_dry_run_json_includes_setpoints_and_output_on(capsys) -> None:
    args = output_command_args("apply", voltage="1", current="0.05")

    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["voltage"] == 1.0
    assert payload["request"]["current"] == 0.05
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == [
        "set_current_limit",
        "set_voltage",
        "output_on",
    ]


def test_apply_all_no_output_dry_run_sets_each_channel_without_output(capsys) -> None:
    assert (
        cli.main(
            [
                "apply",
                "--dry-run",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "all",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--no-output",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    steps = payload["data"]["plan"]["steps"]
    assert [(step["action"], step["parameters"]["channel"]) for step in steps] == [
        ("set_current_limit", 1),
        ("set_voltage", 1),
        ("set_current_limit", 2),
        ("set_voltage", 2),
        ("set_current_limit", 3),
        ("set_voltage", 3),
    ]
    assert all(step["action"] != "output_on" for step in steps)


def test_smoke_output_dry_run_json_emits_guarded_plan(capsys) -> None:
    assert (
        cli.main(
            [
                "smoke-output",
                "--dry-run",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
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
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": True,
        "hardware_touched": False,
    }
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == [
        "set_current_limit",
        "set_voltage",
        "output_on",
        "sleep",
        "measure_voltage",
        "measure_current",
        "output_off",
        "output_state",
    ]


def test_smoke_output_simulate_json_does_not_create_real_resource_manager(
    monkeypatch,
    capsys,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "smoke-output",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
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
    assert payload["execution"]["mode"] == "simulate"
    assert payload["execution"]["hardware_touched"] is False
    assert payload["data"]["plan"]["operation"] == {"name": "smoke-output"}


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


def test_set_dry_run_json_applies_explicit_safety_config(tmp_path, capsys) -> None:
    safety_config = write_safety_config(tmp_path)

    assert (
        cli.main(
            [
                *output_command_args("set"),
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": None,
        "channel": 1,
        "voltage": 1.0,
        "current": 0.05,
        "safety_config": safety_config,
        "backend": None,
        "timeout_ms": 5000,
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
    }
    assert payload["data"]["plan"]["steps"][0]["action"] == "set_current_limit"
    assert payload["data"]["plan"]["steps"][1]["action"] == "set_voltage"
    assert captured.err == ""


@pytest.mark.parametrize(
    ("args", "expected_message"),
    [
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "5.1",
                "--current",
                "0.05",
            ],
            "voltage 5.1 exceeds maximum 5",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.6",
            ],
            "current 0.6 exceeds maximum 0.5",
        ),
    ],
)
def test_set_safety_config_limit_failures_use_json_validation_errors(
    tmp_path,
    args,
    expected_message,
    capsys,
) -> None:
    safety_config = write_safety_config(tmp_path)

    assert cli.main([*args, "--dry-run", "--json", "--safety-config", safety_config]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["execution"]["hardware_touched"] is False
    assert payload["request"]["safety_config"] == safety_config
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert payload["error"]["retryable"] is False
    assert expected_message in payload["error"]["message"]
    assert captured.err == ""


@pytest.mark.parametrize(
    "args",
    [
        output_command_args("set", channel="2"),
        output_command_args("output-on", channel="2"),
        output_command_args("output-off", channel="2"),
    ],
)
def test_safety_config_rejects_disallowed_integer_channels(
    tmp_path,
    args,
    capsys,
) -> None:
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
allowed_channels = [1]
""".strip(),
    )

    assert cli.main([*args, "--dry-run", "--json", "--safety-config", safety_config]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 2 is not allowed" in payload["error"]["message"]
    assert captured.err == ""


def test_safe_off_all_with_safety_config_is_allowed(tmp_path, capsys) -> None:
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "safe-off",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": None,
        "channel": "all",
        "safety_config": safety_config,
    }
    assert payload["data"]["plan"]["target"]["channel"] == "all"
    assert payload["data"]["plan"]["steps"][0]["parameters"]["channel"] == 1
    assert captured.err == ""


def test_output_plan_resource_alias_resolves_effective_resource_and_limits(
    tmp_path,
    capsys,
) -> None:
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2]

[[resources]]
alias = "sim-e36312a"
resource = "{OUTPUT_RESOURCE}"
max_voltage = 3.3
max_current = 0.1
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--resource-alias",
                "sim-e36312a",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": "sim-e36312a",
        "channel": 1,
        "voltage": 1.0,
        "current": 0.05,
        "safety_config": safety_config,
        "backend": None,
        "timeout_ms": 5000,
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
    }
    assert payload["data"]["plan"]["target"]["resource"] == OUTPUT_RESOURCE
    assert captured.err == ""


def test_raw_resource_match_applies_resource_specific_limits(tmp_path, capsys) -> None:
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2]

[[resources]]
alias = "sim-e36312a"
resource = "{OUTPUT_RESOURCE}"
max_voltage = 0.5
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["resource"] == OUTPUT_RESOURCE
    assert payload["request"]["resource_alias"] is None
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "voltage 1 exceeds maximum 0.5" in payload["error"]["message"]
    assert captured.err == ""


def test_resource_alias_requires_explicit_safety_config(capsys) -> None:
    assert (
        cli.main(
            [
                "set",
                "--resource-alias",
                "sim-e36312a",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--dry-run",
                "--json",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["resource"] is None
    assert payload["request"]["resource_alias"] == "sim-e36312a"
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "resource alias requires --safety-config" in payload["error"]["message"]
    assert captured.err == ""


def test_unknown_resource_alias_uses_json_validation_error(tmp_path, capsys) -> None:
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
max_voltage = 5.0

[[resources]]
alias = "sim-e36312a"
resource = "{OUTPUT_RESOURCE}"
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--resource-alias",
                "missing",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["resource"] is None
    assert payload["request"]["resource_alias"] == "missing"
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "unknown resource alias: missing" in payload["error"]["message"]
    assert captured.err == ""


def test_real_set_with_alias_without_dry_run_executes_after_validation(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1]

[[resources]]
alias = "sim-e36312a"
resource = "{OUTPUT_RESOURCE}"
max_current = 0.1
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--resource-alias",
                "sim-e36312a",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["resource"] == OUTPUT_RESOURCE
    assert payload["request"]["resource_alias"] == "sim-e36312a"
    assert payload["execution"]["hardware_touched"] is True
    assert session.writes == ["CURR 0.05,(@1)", "VOLT 1,(@1)"]
    assert captured.err == ""


def test_simulate_output_with_safety_config_does_not_create_real_resource_manager(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)
    safety_config = write_safety_config(tmp_path)

    assert (
        cli.main(
            [
                *output_command_args("set"),
                "--simulate",
                "--json",
                "--safety-config",
                safety_config,
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
    assert payload["request"]["safety_config"] == safety_config
    assert captured.err == ""


def test_real_set_with_safety_config_without_dry_run_executes(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    safety_config = write_safety_config(tmp_path)

    assert cli.main([*output_command_args("set"), "--json", "--safety-config", safety_config]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": True,
    }
    assert payload["request"]["safety_config"] == safety_config
    assert payload["data"]["setpoints"] == {"current": 0.05, "voltage": 1.0}
    assert session.writes == ["CURR 0.05,(@1)", "VOLT 1,(@1)"]
    assert captured.err == ""


@pytest.mark.parametrize(
    ("config_content", "args", "expected_message"),
    [
        (
            "[safety]\nunknown = 1\n",
            [*output_command_args("set"), "--dry-run"],
            "unsupported [safety] key: unknown",
        ),
        (
            "[safety]\nmax_voltage = 0.5\n",
            [*output_command_args("set"), "--dry-run"],
            "voltage 1 exceeds maximum 0.5",
        ),
    ],
)
def test_safety_config_text_errors_go_to_stderr(
    tmp_path,
    config_content,
    args,
    expected_message,
    capsys,
) -> None:
    safety_config = write_safety_config(tmp_path, config_content)

    assert cli.main([*args, "--safety-config", safety_config]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert expected_message in captured.err


def test_missing_safety_config_path_uses_json_validation_error(capsys) -> None:
    missing_path = "does-not-exist.toml"

    assert (
        cli.main(
            [
                *output_command_args("set"),
                "--dry-run",
                "--json",
                "--safety-config",
                missing_path,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["safety_config"] == missing_path
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "safety config not found" in payload["error"]["message"]
    assert captured.err == ""


@pytest.mark.parametrize(
    ("args", "expected_lines"),
    [
        (
            output_command_args("set"),
            [
                "Dry-run plan for set",
                "1. set_current_limit channel=1 current=0.05",
                "2. set_voltage channel=1 voltage=1",
            ],
        ),
        (
            output_command_args("output-on"),
            ["Dry-run plan for output-on", "1. output_on channel=1"],
        ),
        (
            output_command_args("output-off"),
            ["Dry-run plan for output-off", "1. output_off channel=1"],
        ),
        (
            output_command_args("safe-off"),
            ["Dry-run plan for safe-off", "1. safe_off channel=1"],
        ),
    ],
)
def test_output_commands_text_dry_run_output(args, expected_lines, capsys) -> None:
    assert cli.main([*args, "--dry-run"]) == 0

    captured = capsys.readouterr()
    for line in expected_lines:
        assert line in captured.out
    assert f"Resource: {OUTPUT_RESOURCE}" in captured.out
    assert "Hardware touched: false" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    "args",
    [
        output_command_args("safe-off"),
    ],
)
def test_real_output_commands_without_dry_run_are_rejected_before_visa(
    monkeypatch,
    capsys,
    args,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)
    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["command"] == {"name": args[0]}
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": True,
        "hardware_touched": False,
    }
    assert payload["data"]["plan"]["target"]["channel"] == 1
    assert captured.err == ""


@pytest.mark.parametrize("channel", ["1", "2", "3"])
def test_output_state_real_e36312a_reads_channel_state(monkeypatch, capsys, channel) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={f"OUTP? (@{channel})": "ON"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-state",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                channel,
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?", f"OUTP? (@{channel})"]
    assert session.writes == []
    assert payload["data"]["channel"] == int(channel)
    assert payload["data"]["output_enabled"] is True
    assert "output" not in payload["data"]
    assert "outputs" not in payload["data"]
    assert f"USB0::SIM::E36312A::INSTR SCPI >> OUTP? (@{channel})" in captured.err


def test_output_state_real_e36312a_all_uses_canonical_outputs(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"OUTP? (@1)": "ON", "OUTP? (@2)": "OFF", "OUTP? (@3)": "ON"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["output-state", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "all"]) == 0

    data = json.loads(capsys.readouterr().out)["data"]
    assert data["channel"] == "all"
    assert data["outputs"] == [
        {"channel": 1, "enabled": True},
        {"channel": 2, "enabled": False},
        {"channel": 3, "enabled": True},
    ]
    assert "output" not in data
    assert "output_enabled" not in data


def _output_state_core_result(*, channel=1, output_enabled=False, outputs=None):
    data = {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": None,
        "idn": {"raw": "KEYSIGHT,E36312A,SERIAL0000,1.0"},
        "channel": channel,
    }
    if output_enabled is not None:
        data["output_enabled"] = output_enabled
    if outputs is not None:
        data["outputs"] = outputs
    return data


def _run_output_state_core_result(monkeypatch, capsys, data, *, channel="1"):
    monkeypatch.setattr(cli.operations, "run_operation", lambda *args, **kwargs: data)
    exit_code = cli.main(
        ["output-state", "--json", "--resource", OUTPUT_RESOURCE, "--channel", channel]
    )
    captured = capsys.readouterr()
    return exit_code, json.loads(captured.out), captured.err


@pytest.mark.parametrize("enabled", [True, False])
def test_output_state_core_result_accepts_exact_single_boolean(
    monkeypatch, capsys, enabled
) -> None:
    exit_code, payload, stderr = _run_output_state_core_result(
        monkeypatch,
        capsys,
        _output_state_core_result(output_enabled=enabled),
    )

    assert exit_code == 0
    assert payload["data"]["channel"] == 1
    assert payload["data"]["output_enabled"] is enabled
    assert "output" not in payload["data"]
    assert "outputs" not in payload["data"]
    assert stderr == ""


def test_output_state_core_result_accepts_complete_all_records(monkeypatch, capsys) -> None:
    data = _output_state_core_result(
        channel="all",
        output_enabled=None,
        outputs=[
            {"channel": 3.0, "enabled": True},
            {"channel": 1, "enabled": False},
            {"channel": 2, "enabled": True},
        ],
    )

    exit_code, payload, stderr = _run_output_state_core_result(
        monkeypatch, capsys, data, channel="all"
    )

    assert exit_code == 0
    assert payload["data"]["channel"] == "all"
    assert payload["data"]["outputs"] == [
        {"channel": 1, "enabled": False},
        {"channel": 2, "enabled": True},
        {"channel": 3, "enabled": True},
    ]
    assert "output" not in payload["data"]
    assert "output_enabled" not in payload["data"]
    assert stderr == ""


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {},
        {"idn": None},
        {"idn": "KEYSIGHT,E36312A,SERIAL0000,1.0"},
        {"idn": {}},
        {"idn": {"raw": None}},
        {"idn": {"raw": 123}},
        {"idn": {"raw": ""}},
        {"idn": {"raw": "not-an-idn"}},
        {"idn": {"raw": "KEYSIGHT,UNKNOWN,SERIAL0000,1.0"}},
    ],
)
def test_output_state_core_result_rejects_invalid_observed_identity(
    monkeypatch, capsys, data
) -> None:
    _assert_invalid_output_state_core_result(monkeypatch, capsys, data)


@pytest.mark.parametrize(
    "data",
    [
        _output_state_core_result(output_enabled=None),
        _output_state_core_result(output_enabled="false"),
        _output_state_core_result(output_enabled=0),
        _output_state_core_result(output_enabled=1),
        {**_output_state_core_result(output_enabled=None), "output_enabled": None},
        _output_state_core_result(
            output_enabled=False,
            outputs=[{"channel": 1, "enabled": False}],
        ),
    ],
)
def test_output_state_core_result_rejects_malformed_single_data(
    monkeypatch, capsys, data
) -> None:
    _assert_invalid_output_state_core_result(monkeypatch, capsys, data)


@pytest.mark.parametrize(
    "outputs",
    [
        None,
        [],
        1,
        "bad",
        {"channel": 1, "enabled": False},
        [None],
        ["bad"],
        [{"enabled": False}],
        [{"channel": 1}],
        [{"channel": 1, "enabled": False, "extra": "bad"}],
        [{"channel": 1, "enabled": "false"}],
        [{"channel": 1, "enabled": 0}],
        [{"channel": 1, "enabled": 1}],
        [{"channel": 1, "enabled": None}],
        [{"channel": "1", "enabled": False}],
        [{"channel": True, "enabled": False}],
        [{"channel": 1.5, "enabled": False}],
        [{"channel": float("nan"), "enabled": False}],
        [{"channel": float("inf"), "enabled": False}],
        [{"channel": 0, "enabled": False}],
        [{"channel": -1, "enabled": False}],
        [
            {"channel": 1, "enabled": False},
            {"channel": 1, "enabled": False},
            {"channel": 2, "enabled": False},
            {"channel": 3, "enabled": False},
        ],
        [
            {"channel": 1, "enabled": False},
            {"channel": 2, "enabled": False},
            {"channel": 4, "enabled": False},
        ],
        [
            {"channel": 1, "enabled": False},
            {"channel": 2, "enabled": False},
        ],
    ],
)
def test_output_state_core_result_rejects_malformed_all_records(
    monkeypatch, capsys, outputs
) -> None:
    data = _output_state_core_result(
        channel="all", output_enabled=None, outputs=outputs
    )
    if outputs is None:
        data["outputs"] = None
    _assert_invalid_output_state_core_result(
        monkeypatch, capsys, data, channel="all"
    )


def test_output_state_core_result_rejects_all_with_top_level_output_enabled(
    monkeypatch, capsys
) -> None:
    data = _output_state_core_result(
        channel="all",
        output_enabled=False,
        outputs=[
            {"channel": 1, "enabled": False},
            {"channel": 2, "enabled": False},
            {"channel": 3, "enabled": False},
        ],
    )

    _assert_invalid_output_state_core_result(
        monkeypatch, capsys, data, channel="all"
    )


@pytest.mark.parametrize(
    "capabilities",
    [
        SimpleNamespace(),
        SimpleNamespace(real_measure_channels=None),
        SimpleNamespace(real_measure_channels=()),
        SimpleNamespace(real_measure_channels=[1, 2, 3]),
        SimpleNamespace(real_measure_channels=(1, 1, 2)),
        SimpleNamespace(real_measure_channels=(True, 2, 3)),
        SimpleNamespace(real_measure_channels=("1", 2, 3)),
        SimpleNamespace(real_measure_channels=(1.0, 2, 3)),
        SimpleNamespace(real_measure_channels=(0, 2, 3)),
        SimpleNamespace(real_measure_channels=(-1, 2, 3)),
    ],
)
def test_output_state_core_result_rejects_invalid_detected_channels(
    monkeypatch, capsys, capabilities
) -> None:
    selection = SimpleNamespace(
        physical_identity=SimpleNamespace(model_id="keysight-e36312a"),
        reason="model_specific_driver",
        capabilities=capabilities,
    )
    monkeypatch.setattr(cli, "select_driver", lambda idn_raw: selection)
    data = _output_state_core_result(
        channel="all",
        output_enabled=None,
        outputs=[
            {"channel": 1, "enabled": False},
            {"channel": 2, "enabled": False},
            {"channel": 3, "enabled": False},
        ],
    )

    _assert_invalid_output_state_core_result(
        monkeypatch, capsys, data, channel="all"
    )


def _assert_invalid_output_state_core_result(
    monkeypatch, capsys, data, *, channel="1"
) -> None:
    exit_code, payload, stderr = _run_output_state_core_result(
        monkeypatch, capsys, data, channel=channel
    )

    assert exit_code == 3
    assert payload["schema_version"] == 2
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["data"] is None
    assert payload["error"]["type"] == "execution"
    assert payload["error"]["code"] == "invalid_core_result"
    assert payload["error"]["retryable"] is False
    assert "Traceback" not in stderr


def test_safe_off_real_e36312a_expands_all_channels(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "OUTP? (@1)": "0",
            "OUTP? (@2)": "0",
            "OUTP? (@3)": "0",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "safe-off",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "all",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?", "OUTP? (@1)", "OUTP? (@2)", "OUTP? (@3)", "SYST:ERR?"]
    assert session.writes == ["OUTP OFF,(@1)", "OUTP OFF,(@2)", "OUTP OFF,(@3)"]
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
        {"channel": 2, "enabled": False},
        {"channel": 3, "enabled": False},
    ]
    assert captured.err == ""


def test_cycle_output_real_e36312a_cycles_output_without_delay(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@2)": "1.0", "CURR? (@2)": "0.1"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    assert (
        cli.main(
            [
                "cycle-output",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "2",
                "--duration-ms",
                "250",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == ["OUTP ON,(@2)", "OUTP OFF,(@2)"]
    assert payload["data"]["duration_ms"] == 250
    assert payload["data"]["output"] == {"cycled": True, "final_enabled": False}
    assert captured.err == ""


def test_apply_real_e36312a_sets_then_enables_output(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "3",
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
    assert session.writes == ["CURR 0.05,(@3)", "VOLT 1,(@3)", "OUTP ON,(@3)"]
    assert payload["data"]["output"] == {"enabled": True}
    assert captured.err == ""


def test_apply_real_e36312a_all_channels_sets_then_enables_each(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == [
        "CURR 0.05,(@1)",
        "VOLT 1,(@1)",
        "CURR 0.05,(@2)",
        "VOLT 1,(@2)",
        "CURR 0.05,(@3)",
        "VOLT 1,(@3)",
        "OUTP ON,(@1)",
        "OUTP ON,(@2)",
        "OUTP ON,(@3)",
    ]
    assert payload["data"]["channel"] == "all"
    assert payload["data"]["output"] == {"enabled": True}
    assert payload["data"]["channels"] == [
        {"channel": 1, "setpoints": {"current": 0.05, "voltage": 1.0}},
        {"channel": 2, "setpoints": {"current": 0.05, "voltage": 1.0}},
        {"channel": 3, "setpoints": {"current": 0.05, "voltage": 1.0}},
    ]


def test_apply_real_e36312a_no_output_skips_output_on(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--no-output",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.writes == [
        "CURR 0.05,(@1)",
        "VOLT 1,(@1)",
        "CURR 0.05,(@2)",
        "VOLT 1,(@2)",
        "CURR 0.05,(@3)",
        "VOLT 1,(@3)",
    ]
    assert payload["request"]["no_output"] is True
    assert payload["data"]["output"] == {"enabled": False}


@pytest.mark.parametrize(
    "args",
    [
        output_command_args("set"),
        output_command_args("output-on"),
        output_command_args("output-off"),
        output_command_args("safe-off"),
    ],
)
def test_output_commands_simulate_without_dry_run_succeed_without_real_visa(
    monkeypatch,
    capsys,
    args,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert cli.main([*args, "--simulate", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["data"]["plan"]["operation"] == {"name": args[0]}
    assert payload["data"]["plan"]["hardware_touched"] is False
    assert captured.err == ""


def test_set_plan_orders_current_limit_before_voltage(capsys) -> None:
    assert cli.main([*output_command_args("set"), "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    steps = json.loads(captured.out)["data"]["plan"]["steps"]
    assert steps == [
        {
            "index": 1,
            "type": "driver_action",
            "action": "set_current_limit",
            "parameters": {"channel": 1, "current": 0.05},
        },
        {
            "index": 2,
            "type": "driver_action",
            "action": "set_voltage",
            "parameters": {"channel": 1, "voltage": 1.0},
        },
    ]


def test_set_dry_run_json_accepts_voltage_only(capsys) -> None:
    assert cli.main([
        "set",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--voltage",
        "1",
        "--dry-run",
        "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["voltage"] == 1.0
    assert "current" not in payload["request"]
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == ["set_voltage"]


def test_set_dry_run_json_accepts_current_only(capsys) -> None:
    assert cli.main([
        "set",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--current",
        "0.05",
        "--dry-run",
        "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["current"] == 0.05
    assert "voltage" not in payload["request"]
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == ["set_current_limit"]


def test_set_dry_run_json_rejects_missing_setpoints(capsys) -> None:
    assert cli.main([
        "set",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--dry-run",
        "--json",
    ]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "set requires voltage, current, or both" in payload["error"]["message"]


def test_set_text_dry_run_lists_only_requested_setpoint(capsys) -> None:
    assert cli.main([
        "set",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--voltage",
        "1",
        "--dry-run",
    ]) == 0

    captured = capsys.readouterr()
    assert "set_voltage channel=1 voltage=1" in captured.out
    assert "set_current_limit" not in captured.out


def test_channel_two_plan_is_logical_and_not_scpi(capsys) -> None:
    args = output_command_args("set", channel="2")
    args[2] = "USB0::SIM::E36312A::INSTR"

    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    plan = payload["data"]["plan"]
    assert plan["target"]["channel"] == 2
    assert all(step["parameters"]["channel"] == 2 for step in plan["steps"])
    assert all("command" not in step for step in plan["steps"])
    assert "SCPI" not in captured.out


def test_output_all_channel_dry_run_expands_supported_commands(capsys) -> None:
    assert (
        cli.main(
            [
                "safe-off",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "all",
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["data"]["plan"]["target"]["channel"] == "all"
    assert payload["data"]["plan"]["steps"] == [
        {
            "index": 1,
            "type": "driver_action",
            "action": "safe_off",
            "parameters": {"channel": 1},
        },
        {
            "index": 2,
            "type": "driver_action",
            "action": "safe_off",
            "parameters": {"channel": 2},
        },
        {
            "index": 3,
            "type": "driver_action",
            "action": "safe_off",
            "parameters": {"channel": 3},
        },
    ]

    for command, expected_actions in (
        ("output-on", ["output_on", "output_on", "output_on"]),
        ("output-off", ["output_off", "output_off", "output_off"]),
        ("output-state", ["output_state", "output_state", "output_state"]),
    ):
        args = output_command_args(command, channel="all")
        args[2] = "USB0::SIM::E36312A::INSTR"
        assert cli.main([*args, "--dry-run", "--json"]) == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["data"]["plan"]["target"]["channel"] == "all"
        assert [step["action"] for step in payload["data"]["plan"]["steps"]] == expected_actions
        assert [step["parameters"]["channel"] for step in payload["data"]["plan"]["steps"]] == [1, 2, 3]

    args = output_command_args("cycle-output", channel="all", duration_ms="250")
    args[2] = "USB0::SIM::E36312A::INSTR"
    assert cli.main([*args, "--dry-run", "--json"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == [
        "output_on",
        "output_on",
        "output_on",
        "sleep",
        "output_off",
        "output_off",
        "output_off",
    ]
    assert payload["data"]["plan"]["steps"][3]["parameters"] == {"duration_ms": 250}

    for command in ("set", "ramp", "smoke-output"):
        args = output_command_args(command, channel="all")
        if command == "ramp":
            args = [
                "ramp",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.5",
                "--current",
                "0.1",
            ]
        assert cli.main([*args, "--dry-run", "--json"]) == 2
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["error"]["type"] == "validation"
        assert payload["error"]["code"] == "argument_error"
        assert payload["execution"]["hardware_touched"] is False


@pytest.mark.parametrize(
    ("args", "expected_message"),
    [
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "-0.1",
                "--current",
                "0.05",
            ],
            "voltage must be non-negative",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "nan",
                "--current",
                "0.05",
            ],
            "voltage must be finite",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "inf",
                "--current",
                "0.05",
            ],
            "voltage must be finite",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "-0.05",
            ],
            "current must be non-negative",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "nan",
            ],
            "current must be finite",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "inf",
            ],
            "current must be finite",
        ),
        (
            [
                "output-on",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "0",
            ],
            "channel must be a positive integer",
        ),
    ],
)
def test_output_command_invalid_values_use_stable_json_validation_errors(
    args,
    expected_message,
    capsys,
) -> None:
    assert cli.main([*args, "--dry-run", "--json"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["execution"]["hardware_touched"] is False
    assert payload["data"] is None
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert payload["error"]["retryable"] is False
    assert expected_message in payload["error"]["message"]
    assert captured.err == ""


# --- E36312A real set (uses hardcoded resource) ---


@pytest.mark.parametrize(
    ("channel", "expected_writes"),
    [
        (1, ["CURR 0.05,(@1)", "VOLT 1,(@1)"]),
        (2, ["CURR 0.05,(@2)", "VOLT 1,(@2)"]),
        (3, ["CURR 0.05,(@3)", "VOLT 1,(@3)"]),
    ],
)
def test_set_real_e36312a_sends_current_before_voltage(
    monkeypatch,
    capsys,
    channel,
    expected_writes,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                str(channel),
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
    assert session.writes == expected_writes
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.closed is True
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": True,
    }
    assert payload["data"] == {
        "resource": expected_resource(
            OUTPUT_RESOURCE,
            reachable=True,
            idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        ),
        "channel": channel,
        "setpoints": {"current": 0.05, "voltage": 1.0},
    }
    assert captured.err == ""


def test_set_real_text_output_is_minimal_without_output_enabled(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(output_command_args("set")) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        f"Resource: {OUTPUT_RESOURCE}\n"
        "Channel: 1\n"
        "Current limit: 0.05 A\n"
        "Voltage: 1 V\n"
    )
    assert "Output enabled" not in captured.out
    assert captured.err == ""


def test_set_real_resource_alias_backend_timeout_resolves_once(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    opened: list[tuple[str, str | None, int]] = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        opened.append((resource, backend, timeout_ms))
        return session

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
allowed_channels = [1, 2, 3]
max_voltage = 5.0
max_current = 0.5

[[resources]]
alias = "e36312a"
resource = "{OUTPUT_RESOURCE}"
allowed_channels = [2]
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource-alias",
                "e36312a",
                "--channel",
                "2",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--safety-config",
                safety_config,
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
        "channel": 2,
        "voltage": 1.0,
        "current": 0.05,
        "safety_config": safety_config,
        "backend": "@py",
        "timeout_ms": 1234,
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
    }
    assert payload["execution"]["hardware_touched"] is True
    assert captured.err == ""


def test_set_real_safety_config_rejects_before_open(monkeypatch, tmp_path, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
allowed_channels = [1]
max_voltage = 5.0
max_current = 0.5
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "2",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 2 is not allowed" in payload["error"]["message"]
    assert captured.err == ""


def test_set_real_e36312a_with_log_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> CURR 0.05,(@1)" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> VOLT 1,(@1)" in captured.err
    json.loads(captured.out)


@pytest.mark.parametrize("idn", ["KEYSIGHT,UNKNOWN,SERIAL0000,1.0", "UNKNOWN,MODEL,SN,FW"])
def test_set_real_non_e36312a_models_are_rejected(monkeypatch, capsys, idn) -> None:
    session = FakeSession(idn=idn)
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("set"), "--json"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert_live_scope_rejected(payload, session)


def test_set_real_edu36311a_sends_current_before_voltage(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "2",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == ["CURR 0.05,(@2)", "VOLT 1,(@2)"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["resource"]["idn"]["model"] == "EDU36311A"


def test_set_real_edu36311a_rejects_completion_pulse(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
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
    assert payload["error"]["code"] == "trigger_native_unsupported"


def test_set_real_unsupported_channel_is_rejected_after_idn(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("set", channel="99"), "--json"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 99 is not supported for set" in payload["error"]["message"]


def test_set_real_open_failure_uses_connection_failed(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise VisaConnectionError("open failed")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert cli.main([*output_command_args("set"), "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "connection_failed"


def test_set_real_write_failure_uses_set_failed(monkeypatch, capsys) -> None:
    class FailingWriteSession(FakeSession):
        def write(self, command: str) -> None:
            super().write(command)
            raise VisaConnectionError("write failed")

    session = FailingWriteSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("set"), "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?"]
    assert session.writes == ["CURR 0.05,(@1)"]
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "set_failed"


def test_set_real_instrument_error_queue_fails_command(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"SYST:ERR?": ['-222,"Data out of range"', '0,"No error"']},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("set"), "--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert session.writes == ["CURR 0.05,(@1)", "VOLT 1,(@1)"]
    assert session.queries == ["*IDN?", "SYST:ERR?", "SYST:ERR?"]
    assert payload["ok"] is False
    assert payload["error"]["code"] == "set_failed"
    assert '-222,"Data out of range"' in payload["error"]["message"]


# --- E36312A real output-on (uses hardcoded resource) ---

@pytest.mark.parametrize("channel", [1, 2, 3])
def test_output_on_real_e36312a_sends_correct_scpi(monkeypatch, capsys, channel) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            f"VOLT? (@{channel})": "1.0",
            f"CURR? (@{channel})": "0.05",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                str(channel),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["output"]["enabled"] is True
    assert any(command.startswith("OUTP ON") for command in session.writes)


def test_output_on_real_text_output_reports_enabled(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@2)": "1.0", "CURR? (@2)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("output-on"), "--channel", "2"]) == 0

    captured = capsys.readouterr()
    assert "enabled" in captured.out.lower()
    assert captured.err == ""
    assert session.queries[0] == "*IDN?"
    assert any(command.startswith("OUTP ON") for command in session.writes)
    assert session.closed is True


def test_output_on_real_resource_alias_backend_timeout_resolves_once(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@2)": "1.0", "CURR? (@2)": "0.05"},
    )
    opened: list[tuple[str, str | None, int]] = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        opened.append((resource, backend, timeout_ms))
        return session

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
allowed_channels = [1, 2, 3]

[[resources]]
alias = "e36312a"
resource = "{OUTPUT_RESOURCE}"
allowed_channels = [2]
""".strip(),
    )

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource-alias",
                "e36312a",
                "--channel",
                "2",
                "--safety-config",
                safety_config,
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
        "channel": 2,
        "safety_config": safety_config,
        "backend": "@py",
        "timeout_ms": 1234,
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
    }
    assert payload["execution"]["hardware_touched"] is True
    assert captured.err == ""


def test_output_on_real_safety_config_rejects_before_open(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "2",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 2 is not allowed" in payload["error"]["message"]
    assert captured.err == ""


def test_output_on_real_e36312a_with_log_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-on",
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
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> VOLT? (@1)" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> OUTP ON,(@1)" in captured.err
    json.loads(captured.out)  # must not raise - stdout is valid JSON


@pytest.mark.parametrize("idn", ["KEYSIGHT,UNKNOWN,SERIAL0000,1.0", "UNKNOWN,MODEL,SN,FW"])
def test_output_on_real_non_e36312a_models_are_rejected(monkeypatch, capsys, idn) -> None:
    session = FakeSession(idn=idn)
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert_live_scope_rejected(payload, session)


def test_output_on_real_unsupported_channel_is_rejected_after_idn(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "99",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"


def test_output_on_real_open_failure_uses_connection_failed(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise VisaConnectionError("open failed")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert cli.main([*output_command_args("output-on"), "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "connection_failed"


def test_output_on_real_write_failure_surfaces_connection_error(monkeypatch, capsys) -> None:
    class FailingWriteSession(FakeSession):
        def write(self, command: str) -> None:
            super().write(command)
            raise VisaConnectionError("write failed")

    session = FailingWriteSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("output-on"), "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "output_on_failed"
    assert session.writes


def test_output_on_real_safety_config_checks_readback_before_enabling(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    safety_config = write_safety_config(tmp_path)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["readback"]["safety_checked"] is True
    assert any(command.startswith("OUTP ON") for command in session.writes)


def test_output_on_real_safety_config_rejects_unsafe_readback(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "5.1", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    safety_config = write_safety_config(tmp_path)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "safety"
    assert payload["error"]["code"] == "unsafe_output_setpoint"
    assert not any(command.startswith("OUTP ON") for command in session.writes)


# --- E36312A real output-off (uses hardcoded resource) ---

@pytest.mark.parametrize("channel", [1, 2, 3])
def test_output_off_real_e36312a_sends_correct_scpi(monkeypatch, capsys, channel) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                str(channel),
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == [f"OUTP OFF,(@{channel})"]
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.closed is True
    assert payload["execution"]["mode"] == "real"
    assert payload["execution"]["dry_run"] is False
    assert payload["execution"]["hardware_touched"] is True
    assert payload["data"]["channel"] == channel
    assert payload["data"]["output"]["enabled"] is False
    assert payload["data"]["resource"]["name"] == OUTPUT_RESOURCE
    assert payload["data"]["resource"]["idn"]["model"] == "E36312A"
    assert captured.err == ""


def test_output_off_real_resource_alias_resolves_once_and_sends_scpi(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    opened: list[tuple[str, str | None, int]] = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        opened.append((resource, backend, timeout_ms))
        return session

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
allowed_channels = [1, 2, 3]

[[resources]]
alias = "e36312a"
resource = "{OUTPUT_RESOURCE}"
allowed_channels = [2]
""".strip(),
    )

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource-alias",
                "e36312a",
                "--channel",
                "2",
                "--safety-config",
                safety_config,
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
        "channel": 2,
        "safety_config": safety_config,
        "backend": "@py",
        "timeout_ms": 1234,
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
    }
    assert payload["execution"]["hardware_touched"] is True
    assert captured.err == ""


def test_output_off_real_safety_config_rejects_before_open(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "2",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 2 is not allowed" in payload["error"]["message"]
    assert captured.err == ""


def test_output_off_real_e36312a_with_log_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
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
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["data"]["output"]["enabled"] is False
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> OUTP OFF,(@1)" in captured.err
    json.loads(captured.out)  # must not raise - stdout is valid JSON


def test_output_off_real_generic_e36312a_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,UNKNOWN,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert_live_scope_rejected(payload, session)


def test_output_off_real_unknown_model_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="UNKNOWN,MODEL,SN,FW")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert_live_scope_rejected(payload, session)


def test_output_off_real_unsupported_channel_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "99",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    # session is closed by context manager after error


def test_output_state_real_non_e36312a_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,UNKNOWN,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-state",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert_live_scope_rejected(payload, session)


def test_output_state_real_edu36311a_reads_channel_state(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
        query_responses={"OUTP? (@3)": "OFF"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-state",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "3",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "OUTP? (@3)"]
    assert payload["data"]["output_enabled"] is False


def test_cycle_output_real_invalid_duration_rejected(capsys) -> None:
    assert (
        cli.main(
            [
                "cycle-output",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--duration-ms",
                "0",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "argument_error"


def test_apply_real_generic_model_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,UNKNOWN,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert_live_scope_rejected(payload, session)


def test_apply_real_edu36311a_all_no_output_writes_all_channels(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "all",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--no-output",
            ]
        )
        == 0
    )

    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == [
        "CURR 0.05,(@1)",
        "VOLT 1,(@1)",
        "CURR 0.05,(@2)",
        "VOLT 1,(@2)",
        "CURR 0.05,(@3)",
        "VOLT 1,(@3)",
    ]
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["resource"]["idn"]["model"] == "EDU36311A"
    assert payload["data"]["output"]["enabled"] is False


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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["measure-all", "--resource", OUTPUT_RESOURCE]) == 0

    captured = capsys.readouterr()
    assert captured.out
    assert captured.err == ""


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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--resource", OUTPUT_RESOURCE, "--channel", "2"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "Errors: none\nChannel 2: Output enabled: false\n"


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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

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

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

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

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)
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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([command, "--json", "--resource", OUTPUT_RESOURCE, *extra_args]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert_live_scope_rejected(payload, session)


def test_status_unsupported_channel_is_argument_error(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "99"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "argument_error"


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


def test_new_command_open_failure_uses_connection_failed(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise VisaConnectionError("open failed")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert cli.main(["measure-all", "--json", "--resource", OUTPUT_RESOURCE]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "connection_failed"


def test_measure_all_scpi_failure_surfaces_connection_error(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["measure-all", "--json", "--resource", OUTPUT_RESOURCE]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "measure_all_failed"


@pytest.mark.parametrize("idn_raw", [None, 123, {"model": "E36312A"}])
def test_measure_all_rejects_invalid_core_identity(monkeypatch, capsys, idn_raw) -> None:
    monkeypatch.setattr(
        cli.readonly_core,
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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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


def test_status_scpi_failure_uses_status_failed(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"SYST:ERR?": '0,"No error"'},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["read-status", "--json", "--resource", OUTPUT_RESOURCE]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "status_failed"


def test_new_commands_log_scpi_to_stderr_without_corrupting_json(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            **_all_trigger_snapshot_query_responses(),
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

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

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

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


E3646A_FORBIDDEN_WRITE_PREFIXES = (
    "VOLT",
    "CURR",
    "OUTP",
    "APPL",
    "TRIG",
    "INIT",
    "ABOR",
    "*TRG",
    "LIST:",
    "DIG:",
)


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
        ("set", ["--channel", "1", "--voltage", "1", "--current", "0.05"]),
        ("output-on", ["--channel", "1"]),
        ("output-off", ["--channel", "1"]),
        ("safe-off", ["--channel", "1"]),
        ("cycle-output", ["--channel", "1", "--duration-ms", "1"]),
        ("apply", ["--channel", "1", "--voltage", "1", "--current", "0.05"]),
        ("ramp", ["--channel", "1", "--start-voltage", "0", "--stop-voltage", "1", "--step-voltage", "1", "--current", "0.05"]),
        ("smoke-output", ["--channel", "1", "--voltage", "1", "--current", "0.05"]),
        ("ramp-list", ["--lint", "--segment", "1", "0.05", "0", "1", "1", "0", "0"]),
        ("sequence", ["--lint", "--file", "examples/sequence-readonly.yaml"]),
    ],
)
def test_output_commands_accept_serial_options_in_json_request(capsys, command, extra_args) -> None:
    assert (
        cli.main(
            [
                command,
                "--json",
                "--resource",
                "ASRL1::INSTR",
                *extra_args,
                *SERIAL_TERMINATION_ARGS,
                "--model",
                "keysight-e36312a",
                "--dry-run",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["serial_options"]["read_termination"] == "\r\n"
    assert payload["request"]["serial_options"]["write_termination"] == "\n"
    assert payload["request"]["serial_remote"] is True
    assert payload["request"]["serial_local_on_close"] is True


def test_output_state_serial_options_still_work(capsys) -> None:
    assert (
        cli.main(
            [
                "output-state",
                "--json",
                "--simulate",
                "--resource",
                "ASRL1::SIM::E3646A::INSTR",
                "--channel",
                "1",
                *SERIAL_TERMINATION_ARGS,
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["serial_options"]["read_termination"] == "\r\n"
    assert payload["request"]["serial_options"]["write_termination"] == "\n"


def test_safe_off_accepts_serial_options_without_confirm(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E3646A,SERIAL0000,1.0",
        query_responses={"INST:NSEL?": "1", "OUTP?": "0"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "safe-off",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--channel",
                "1",
                *SERIAL_TERMINATION_ARGS,
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


@pytest.mark.parametrize(
    ("command", "extra_args", "query_responses"),
    [
        ("set", ["--channel", "1", "--voltage", "1", "--current", "0.05"], {"INST:NSEL?": "1"}),
        ("output-on", ["--channel", "1"], {"INST:NSEL?": "1", "VOLT?": "1.0", "CURR?": "0.05", "OUTP?": "0"}),
        ("output-off", ["--channel", "1"], {"INST:NSEL?": "1", "OUTP?": "1"}),
        ("safe-off", ["--channel", "1"], {"INST:NSEL?": "1", "OUTP?": "1"}),
        ("cycle-output", ["--channel", "1", "--duration-ms", "1"], {"INST:NSEL?": "1", "VOLT?": "1.0", "CURR?": "0.05", "OUTP?": "1"}),
        ("apply", ["--channel", "1", "--voltage", "1", "--current", "0.05", "--no-output"], {"INST:NSEL?": "1"}),
        ("ramp", ["--channel", "1", "--start-voltage", "0", "--stop-voltage", "1", "--step-voltage", "1", "--current", "0.05"], {"INST:NSEL?": "1"}),
        ("smoke-output", ["--channel", "1", "--voltage", "1", "--current", "0.05"], {"INST:NSEL?": "1", "OUTP?": "0", "MEAS:VOLT?": "1.0", "MEAS:CURR?": "0.05"}),
    ],
)
def test_output_family_real_forwards_serial_options_to_opener(
    monkeypatch,
    capsys,
    command,
    extra_args,
    query_responses,
) -> None:
    opened = []
    session = FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0", query_responses=query_responses)

    def fake_open_resource(resource, resource_manager=None, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append(kwargs)
        return session

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                command,
                "--json",
                "--resource",
                "ASRL1::INSTR",
                *extra_args,
                *SERIAL_TERMINATION_ARGS,
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    serial_options = opened[0]["serial_options"]
    assert serial_options.read_termination == "\r\n"
    assert serial_options.write_termination == "\n"
    assert opened[0]["serial_remote"] is True
    assert opened[0]["serial_local_on_close"] is True


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


def test_log_simulate_json_writes_csv(tmp_path, capsys) -> None:
    csv_path = tmp_path / "edu-log.csv"

    assert (
        cli.main(
            [
                "log",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--channel",
                "2",
                "--interval-sec",
                "0.01",
                "--samples",
                "2",
                "--csv",
                str(csv_path),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert payload["data"]["samples_written"] == 2
    assert payload["data"]["stopped"] is False
    assert rows[0].keys() == set(cli.LOG_CSV_FIELDS)
    assert rows[0]["resource"] == "USB0::SIM::EDU36311A::INSTR"
    assert rows[0]["model"] == "EDU36311A"
    assert rows[0]["serial"] == "SIM000004"
    assert rows[0]["channel"] == "2"
    assert rows[0]["programmed_voltage"] == "2.0"
    assert rows[0]["programmed_current"] == "0.1"
    assert rows[0]["measured_voltage"] == "2.02"
    assert rows[0]["measured_current"] == "0.202"
    assert rows[0]["output_enabled"] == "False"


def test_log_simulate_json_logs_scpi_to_stderr_only(tmp_path, capsys) -> None:
    csv_path = tmp_path / "edu-log.csv"

    assert (
        cli.main(
            [
                "log",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--channel",
                "2",
                "--interval-sec",
                "0.01",
                "--samples",
                "1",
                "--csv",
                str(csv_path),
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    json.loads(captured.out)
    assert captured.out.startswith("{")
    assert "SCPI" not in captured.out
    assert "USB0::SIM::EDU36311A::INSTR SCPI >> *IDN?" in captured.err
    assert "USB0::SIM::EDU36311A::INSTR SCPI >> MEAS:VOLT? (@2)" in captured.err


def test_log_simulate_all_channels_jsonl_and_append(tmp_path, capsys) -> None:
    csv_path = tmp_path / "edu-log.csv"
    jsonl_path = tmp_path / "edu-log.jsonl"

    args = [
        "log",
        "--simulate",
        "--json",
        "--resource",
        "USB0::SIM::EDU36311A::INSTR",
        "--channel",
        "all",
        "--interval-sec",
        "0.01",
        "--samples",
        "1",
        "--csv",
        str(csv_path),
        "--jsonl",
        str(jsonl_path),
    ]
    assert cli.main(args) == 0
    first_payload = json.loads(capsys.readouterr().out)
    assert first_payload["data"]["channels"] == [1, 2, 3]

    assert cli.main([*args, "--append"]) == 0
    json.loads(capsys.readouterr().out)

    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert len(rows) == 6
    assert [row["channel"] for row in rows[:3]] == ["1", "2", "3"]
    jsonl_lines = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert jsonl_lines[-1]["event"] == "summary"
    assert jsonl_lines[-1]["channels"] == [1, 2, 3]


def test_sequence_dry_run_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for sequence dry-run")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "sequence",
                "--dry-run",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--file",
                "examples/sequence-readonly.yaml",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "planned"
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == [
        "log",
        "measure",
        "readback",
        "output-state",
        "wait",
        "safe-off",
    ]


def test_sequence_v1_file_loop_override_upgrades_to_v2(tmp_path, capsys) -> None:
    sequence_file = tmp_path / "sequence.json"
    sequence_file.write_text(
        json.dumps({"version": 1, "steps": [{"action": "wait", "seconds": 0}]}),
        encoding="utf-8",
    )

    assert cli.main([
        "sequence", "--dry-run", "--json", "--file", str(sequence_file), "--loop-count", "2",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["version"] == 2
    assert payload["data"]["plan"]["loop_count"] == 2


def test_sequence_lint_parses_bundled_yaml(capsys) -> None:
    assert (
        cli.main(
            [
                "sequence",
                "--lint",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--file",
                "examples/sequence-readonly.yaml",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "valid"
    assert payload["data"]["sequence_version"] == 2
    assert payload["data"]["loop_count"] == 1
    assert payload["data"]["step_count"] == 6


def test_sequence_simulate_executes_read_only_steps(capsys) -> None:
    assert (
        cli.main(
            [
                "sequence",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--file",
                "examples/sequence-readonly.yaml",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "completed"
    assert payload["data"]["completed_steps"] == 6
    assert payload["data"]["results"][1]["measurements"] == {"voltage": 2.02, "current": 0.202}


def test_sequence_real_forwards_serial_options_to_opener(monkeypatch, tmp_path, capsys) -> None:
    sequence_file = tmp_path / "wait-sequence.json"
    sequence_file.write_text(
        json.dumps({"version": 1, "steps": [{"action": "wait", "seconds": 0}]}),
        encoding="utf-8",
    )
    opened = []

    def fake_open_resource(resource, resource_manager=None, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append(kwargs)
        return FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "sequence",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--file",
                str(sequence_file),
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


def test_log_sampling_failure_surfaces_connection_error(monkeypatch, tmp_path, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
        query_responses={
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.10",
            "SYST:ERR?": '0,"No error"',
            "MEAS:VOLT? (@2)": "2.02",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "log",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "2",
                "--interval-sec",
                "0.01",
                "--samples",
                "1",
                "--csv",
                str(tmp_path / "partial.csv"),
            ]
        )
        == 1
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "log_failed"


def test_promoted_log_keeps_interruptible_sampling_behavior(monkeypatch, tmp_path, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.10",
            "MEAS:VOLT? (@2)": "2.02",
            "MEAS:CURR? (@2)": "0.202",
            "OUTP? (@2)": "OFF",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    def interrupting_sleep(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", interrupting_sleep)

    assert (
        cli.main(
            [
                "log",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "2",
                "--interval-sec",
                "0.01",
                "--samples",
                "2",
                "--csv",
                str(tmp_path / "interrupted.csv"),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["stopped"] is True
    assert payload["data"]["stop_reason"] == "interrupted"
    assert payload["data"]["samples_written"] == 1


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


def test_clear_protection_requires_confirm_for_real_hardware(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened without --confirm")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(["clear-protection", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "1"])
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "confirmation_required"


def test_clear_protection_requires_channel_or_all_without_opening_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for invalid arguments")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert cli.main(["clear-protection", "--json", "--resource", OUTPUT_RESOURCE]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"


def test_clear_protection_real_sends_expected_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

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


def test_identify_real_reads_identity_queries(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "*OPT?": "0",
            "SYST:VERS?": "1999.0",
            "SYST:COMM:RLST?": "RWLock",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["identify", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "*OPT?", "SYST:VERS?", "SYST:COMM:RLST?"]
    assert payload["data"]["options"] == "0"
    assert payload["data"]["scpi_version"] == "1999.0"
    assert payload["data"]["remote_lockout_state"] == "RWLock"


def test_identify_edu36311a_real_reads_only_idn(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["identify", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?"]
    assert payload["data"]["idn"]["model"] == "EDU36311A"
    assert payload["data"]["options"] is None
    assert payload["data"]["scpi_version"] is None
    assert payload["data"]["remote_lockout_state"] is None


def test_identify_e3646a_real_reads_only_idn(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["identify", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?"]
    assert "*OPT?" not in session.queries
    assert "SYST:VERS?" not in session.queries
    assert "SYST:COMM:RLST?" not in session.queries
    assert payload["data"]["idn"]["model"] == "E3646A"
    assert payload["data"]["options"] is None
    assert payload["data"]["scpi_version"] is None
    assert payload["data"]["remote_lockout_state"] is None


def test_identify_expected_model_guard_remains_parser_visible(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "identify",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--model",
                "keysight-e3646a",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert session.queries == ["*IDN?"]


def test_identify_extended_query_failure_is_json_error(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["identify", "--json", "--resource", OUTPUT_RESOURCE]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?", "*OPT?"]
    assert payload["error"]["code"] == "identify_failed"
    assert "No fake response for '*OPT?'" in payload["error"]["message"]
    assert "Traceback" not in captured.err


def test_snapshot_real_reads_full_state(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "OUTP? (@1)": "OFF",
            "OUTP? (@2)": "OFF",
            "OUTP? (@3)": "ON",
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
            "VOLT:PROT:TRIP? (@1)": "0",
            "CURR:PROT:TRIP? (@1)": "0",
            "VOLT:PROT:TRIP? (@2)": "0",
            "CURR:PROT:TRIP? (@2)": "0",
            "VOLT:PROT:TRIP? (@3)": "0",
            "CURR:PROT:TRIP? (@3)": "0",
            "VOLT:PROT? (@1)": "5.0",
            "CURR:PROT:STAT? (@1)": "1",
            "CURR:PROT:DEL? (@1)": "0.1",
            "CURR:PROT:DEL:STAR? (@1)": "SCH",
            "VOLT:PROT? (@2)": "6.0",
            "CURR:PROT:STAT? (@2)": "0",
            "CURR:PROT:DEL? (@2)": "0.2",
            "CURR:PROT:DEL:STAR? (@2)": "CCTR",
            "VOLT:PROT? (@3)": "7.0",
            "CURR:PROT:STAT? (@3)": "1",
            "CURR:PROT:DEL? (@3)": "0.3",
            "CURR:PROT:DEL:STAR? (@3)": "SCHange",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["snapshot", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries[0:2] == ["*IDN?", "SYST:ERR?"]
    assert payload["data"]["read_count"] == 1
    assert payload["data"]["schema_version"] == 2
    assert payload["data"]["kind"] == "powers-tool-snapshot"
    assert payload["data"]["reported_identity"]["model"] == "E36312A"
    assert payload["data"]["resolved_identity"]["model_id"] == "keysight-e36312a"
    assert payload["data"]["outputs"][2] == {"channel": 3, "enabled": True}
    assert payload["data"]["readback"][1] == {
        "channel": 2,
        "setpoints": {"voltage": 2.0, "current": 0.1},
    }
    assert payload["data"]["measurements"][0] == {
        "channel": 1,
        "measurements": {"voltage": 1.1, "current": 0.11},
    }
    assert payload["data"]["protection"] == {
        "over_voltage_tripped": False,
        "over_current_tripped": False,
    }
    assert payload["data"]["protection_settings"][1] == {
        "channel": 2,
        "protection": {
            "ovp_voltage": 6.0,
            "ocp_enabled": False,
            "ocp_delay": 0.2,
            "ocp_delay_trigger": "cc-transition",
        },
    }


def test_snapshot_human_output_uses_schema_2_identity(capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"

    assert cli.main(["snapshot", "--simulate", "--resource", resource]) == 0

    output = capsys.readouterr().out
    assert "Model: Keysight E36312A" in output
    assert "Reported manufacturer: KEYSIGHT" in output
    assert "Reported model: E36312A" in output
    assert "Serial: SIM000003" in output


def test_snapshot_json_writes_raw_document_and_envelope_separately(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"
    raw_path = tmp_path / "snapshot.json"
    envelope_path = tmp_path / "envelope.json"

    assert cli.main([
        "snapshot", "--simulate", "--resource", resource, "--json",
        "--save-json", str(envelope_path), "--snapshot-json", str(raw_path),
    ]) == 0

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 2
    assert raw["kind"] == "powers-tool-snapshot"
    assert "ok" not in raw
    assert envelope["schema_version"] == 2
    assert envelope["data"] == raw
    assert json.loads(capsys.readouterr().out) == envelope


def test_snapshot_json_round_trips_to_restore_dry_run(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"
    raw_path = tmp_path / "snapshot.json"

    assert cli.main(["snapshot", "--simulate", "--resource", resource, "--snapshot-json", str(raw_path)]) == 0
    capsys.readouterr()
    assert cli.main([
        "restore-from-snapshot", "--dry-run", "--snapshot", str(raw_path),
        "--resource", resource, "--channel", "all", "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["target"]["channels"] == [1, 2, 3]


def test_restore_rejects_cli_snapshot_envelope(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"
    envelope_path = tmp_path / "envelope.json"

    assert cli.main([
        "snapshot", "--simulate", "--resource", resource,
        "--json", "--save-json", str(envelope_path),
    ]) == 0
    capsys.readouterr()
    assert cli.main([
        "restore-from-snapshot", "--dry-run", "--snapshot", str(envelope_path),
        "--resource", resource, "--channel", "all", "--json",
    ]) == 2

    assert "snapshot kind" in json.loads(capsys.readouterr().out)["error"]["message"]


def test_snapshot_json_write_failure_is_reported(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"
    invalid_parent = tmp_path / "not-a-directory"
    invalid_parent.write_text("occupied", encoding="utf-8")

    assert cli.main([
        "snapshot", "--simulate", "--resource", resource, "--json",
        "--snapshot-json", str(invalid_parent / "snapshot.json"),
    ]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "snapshot_write_failed"


def test_snapshot_rejects_same_raw_and_envelope_path_before_open(tmp_path, monkeypatch, capsys) -> None:
    output_path = tmp_path / "snapshot.json"
    opened = False

    def forbidden_opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("opener must not be called")

    monkeypatch.setattr(cli, "open_resource", forbidden_opener)
    assert cli.main([
        "snapshot", "--json", "--resource", OUTPUT_RESOURCE,
        "--save-json", str(output_path), "--snapshot-json", str(output_path),
    ]) == 2
    assert opened is False
    assert "must use different paths" in json.loads(capsys.readouterr().out)["error"]["message"]


def test_snapshot_compare_accepts_raw_baseline(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource]) == 0
    baseline = json.loads(capsys.readouterr().out)["data"]
    baseline_path = tmp_path / "snapshot-raw.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource, "--compare", str(baseline_path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["comparison"]["passed"] is True
    assert payload["data"]["comparison"]["differences"] == []


def test_snapshot_compare_accepts_envelope_and_exits_3_on_mismatch(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource]) == 0
    envelope = json.loads(capsys.readouterr().out)
    envelope["data"]["reported_identity"]["serial"] = "DIFFERENT"
    baseline_path = tmp_path / "snapshot-envelope.json"
    baseline_path.write_text(json.dumps(envelope), encoding="utf-8")

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource, "--compare", str(baseline_path)]) == 3

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["comparison"]["passed"] is False
    assert payload["data"]["comparison"]["differences"][0]["path"] == "reported_identity"


def test_snapshot_compare_tolerance_override_allows_measurement_delta(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource]) == 0
    baseline = json.loads(capsys.readouterr().out)["data"]
    baseline["measurements"][0]["measurements"]["voltage"] += 0.5
    baseline_path = tmp_path / "snapshot-tolerance.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    assert (
        cli.main(
            [
                "snapshot",
                "--simulate",
                "--json",
                "--resource",
                resource,
                "--compare",
                str(baseline_path),
                "--measured-voltage-tolerance",
                "0.6",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["comparison"]["passed"] is True


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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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
    assert payload["data"]["plan"]["version"] == 4
    assert payload["data"]["plan"]["loop_count"] == 1
    assert payload["data"]["segments"][1]["hold_ms"] == 250


def test_ramp_list_inline_enable_output_builds_v4(capsys) -> None:
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
    assert payload["data"]["plan"]["version"] == 4
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
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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


def _trigger_snapshot_query_responses(channel: int = 1) -> dict[str, str]:
    return {
        "DIG:PIN1:FUNC?": "TOUT",
        "DIG:PIN1:POL?": "POS",
        "DIG:PIN2:FUNC?": "TOUT",
        "DIG:PIN2:POL?": "POS",
        "DIG:PIN3:FUNC?": "DIO",
        "DIG:PIN3:POL?": "POS",
        "DIG:TOUT:BUS?": "0",
        f"TRIG:SOUR? (@{channel})": "BUS",
        f"TRIG:DEL? (@{channel})": "+0.00000000E+00",
        f"VOLT:MODE? (@{channel})": "FIX",
        f"CURR:MODE? (@{channel})": "FIX",
        f"VOLT:TRIG? (@{channel})": "+0.00000000E+00",
        f"CURR:TRIG? (@{channel})": "+2.00000000E-03",
        f"LIST:VOLT? (@{channel})": "+0.00000000E+00",
        f"LIST:CURR? (@{channel})": "+2.00000000E-03",
        f"LIST:DWEL? (@{channel})": "+1.00000000E-02",
        f"LIST:TOUT:BOST? (@{channel})": "0",
        f"LIST:TOUT:EOST? (@{channel})": "0",
        f"LIST:COUN? (@{channel})": "+1",
        f"LIST:STEP? (@{channel})": "AUTO",
        f"LIST:TERM:LAST? (@{channel})": "0",
        "*ESR?": "+1",
    }


def _all_trigger_snapshot_query_responses() -> dict[str, str]:
    return {
        **_trigger_snapshot_query_responses(1),
        **_trigger_snapshot_query_responses(2),
        **_trigger_snapshot_query_responses(3),
    }


@pytest.mark.parametrize(
    ("command", "args", "query_responses"),
    [
        ("set", ["--voltage", "1", "--current", "0.05"], {"VOLT? (@1)": "1.2", "CURR? (@1)": "0.05"}),
        ("apply", ["--voltage", "1", "--current", "0.05", "--no-output"], {"VOLT? (@1)": "1.2", "CURR? (@1)": "0.05"}),
        ("output-off", [], {"OUTP? (@1)": "ON"}),
        (
            "ramp",
            ["--start-voltage", "0", "--stop-voltage", "1", "--step-voltage", "1", "--current", "0.05"],
            {"VOLT? (@1)": "0.8", "CURR? (@1)": "0.05"},
        ),
    ],
)
def test_write_verification_failure_returns_exit_3(monkeypatch, capsys, command, args, query_responses) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0", query_responses=query_responses)
    monkeypatch.setattr(cli, "open_resource", lambda *open_args, **open_kwargs: session)

    assert (
        cli.main(
            [
                command,
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                *args,
                "--verify-after-write",
            ]
        )
        == 3
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "verification_failed"
    assert payload["metadata"]["verification"]["passed"] is False


def test_settle_ms_sleeps_before_verification(monkeypatch, capsys) -> None:
    sleeps = []
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--settle-ms",
                "25",
                "--verify-after-write",
            ]
        )
        == 0
    )

    assert sleeps == [0.025]
    assert json.loads(capsys.readouterr().out)["data"]["verification"]["passed"] is True


def test_readback_log_scpi_to_stderr_without_corrupting_json(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

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


# --- Preserved behaviors: dry-run and simulate ---


def test_output_off_dry_run_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened for dry-run")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "output-off",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert "plan" in payload["data"]
    assert payload["data"]["plan"]["operation"]["name"] == "output-off"
    assert payload["execution"]["hardware_touched"] is False


def test_output_off_simulate_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for simulate")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "output-off",
                "--simulate",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert "plan" in payload["data"]


# --- Safe-off dry-run remains logical ---


@pytest.mark.parametrize("command,extra_args", [
    ("safe-off", []),
])
def test_safe_off_dry_run_remains_logical(monkeypatch, capsys, command, extra_args) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)
    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    args = [command, "--json", "--resource", OUTPUT_RESOURCE, "--channel", "1"] + extra_args
    assert cli.main([*args, "--dry-run"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": True,
        "hardware_touched": False,
    }
    assert payload["data"]["plan"]["operation"]["name"] == "safe-off"
