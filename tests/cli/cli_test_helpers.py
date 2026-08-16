import json

import powers_tool_cli.cli as cli
import powers_tool_cli.commands.output_run as output_run
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
        "PSM-2010": ("gw-instek", "gw-instek-psm-2010"),
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
    monkeypatch.setattr(output_run.operations, "run_operation", lambda *args, **kwargs: data)
    exit_code = cli.main(
        ["output-state", "--json", "--resource", OUTPUT_RESOURCE, "--channel", channel]
    )
    captured = capsys.readouterr()
    return exit_code, json.loads(captured.out), captured.err


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
