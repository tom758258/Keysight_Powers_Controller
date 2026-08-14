from __future__ import annotations

import pytest
from powers_tool_core.core import RuntimeOptions, OperationRequest, CoreValidationError, UnsupportedModelError, UnsupportedChannelError
from powers_tool_core.readonly import run_live_panel_read, run_readonly, run_validate_readonly
from powers_tool_core.connection import open_resource
from powers_tool_core.testing.simulator import SimulatedResourceManager

sim_mgr = SimulatedResourceManager()

def sim_opener(resource, backend=None, timeout_ms=5000):
    return open_resource(resource, sim_mgr, backend=backend, timeout_ms=timeout_ms)


class E3646AStatusSession:
    def __init__(self) -> None:
        self.events: list[str] = []

    def __enter__(self) -> "E3646AStatusSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        pass

    def write(self, command: str) -> None:
        self.events.append(f"write:{command}")

    def query(self, command: str) -> str:
        self.events.append(f"query:{command}")
        if command == "*IDN?":
            return "KEYSIGHT,E3646A,SERIAL0000,1.0"
        if command == "SYST:ERR?":
            return '0,"No error"'
        if command == "INST:NSEL?":
            return "1"
        if command == "OUTP?":
            selected = next(
                (
                    event.rsplit(" ", maxsplit=1)[-1]
                    for event in reversed(self.events)
                    if event.startswith("write:INST:NSEL ")
                ),
                "1",
            )
            return "ON" if selected == "1" else "OFF"
        raise AssertionError(f"unexpected query {command!r}")

    def close(self) -> None:
        pass


class PSM2010LiveSession:
    def __init__(self, range_response: str) -> None:
        self.range_response = range_response
        self.events: list[str] = []

    def __enter__(self) -> "PSM2010LiveSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        pass

    def write(self, command: str) -> None:
        self.events.append(f"write:{command}")

    def query(self, command: str) -> str:
        self.events.append(f"query:{command}")
        responses = {
            "*IDN?": "GW.Inc,PSM-2010,SERIAL0000,1.0",
            "VOLT:PROT:TRIP?": "0",
            "CURR:PROT:TRIP?": "0",
            "OUTP?": "0",
            "VOLT:PROT?": "5.0",
            "CURR:PROT:STAT?": "1",
            "VOLT?": "1.0",
            "CURR?": "0.1",
            "MEAS?": "0.0",
            "MEAS:CURR?": "0.0",
        }
        if command == "VOLT:RANG?":
            return self.range_response
        try:
            return responses[command]
        except KeyError as exc:
            raise AssertionError(f"unexpected query {command!r}") from exc

    def close(self) -> None:
        pass


class ValidateReadonlySession:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.closed = False
        self.responses = {
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
        }

    def __enter__(self) -> "ValidateReadonlySession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.closed = True

    def query(self, command: str) -> str:
        self.queries.append(command)
        if command == "*IDN?":
            return "KEYSIGHT,E36312A,SERIAL0000,1.0"
        try:
            return self.responses[command]
        except KeyError as exc:
            raise AssertionError(f"unexpected query {command!r}") from exc

    def write(self, command: str) -> None:
        raise AssertionError(f"unexpected write {command!r}")

    def close(self) -> None:
        self.closed = True


def test_validate_readonly_core_preserves_single_session_query_order():
    session = ValidateReadonlySession()
    runtime = RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", simulate=True)
    request = OperationRequest(
        command="validate-readonly",
        runtime=runtime,
        parameters={"max_errors": 20},
    )

    result = run_validate_readonly(request, opener=lambda *args, **kwargs: session)

    assert session.closed is True
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
    assert result["driver"]["class"] == "E36312APowerSupply"
    assert result["capabilities"]["channels"] == [1, 2, 3]


def test_validate_readonly_core_only_accepts_its_narrow_command():
    runtime = RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", simulate=True)
    request = OperationRequest(command="read-status", runtime=runtime)

    with pytest.raises(CoreValidationError, match="unsupported validate-readonly command"):
        run_validate_readonly(request, opener=lambda *args, **kwargs: pytest.fail("opened hardware"))

def test_readonly_simulate_status():
    runtime = RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", simulate=True)
    req = OperationRequest(command="read-status", runtime=runtime, parameters={"channel": "all"})
    res = run_readonly(req, opener=sim_opener)
    assert res["resource"] == "USB0::SIM::E36312A::INSTR"
    assert "E36312A" in res["idn_raw"]
    assert len(res["errors"]) == 0
    assert len(res["outputs"]) == 3
    assert res["outputs"][0]["channel"] == 1
    assert res["outputs"][0]["enabled"] is False


def test_readonly_e3646a_status_reads_all_outputs_with_preselection():
    session = E3646AStatusSession()
    runtime = RuntimeOptions(resource="ASRL1::INSTR")
    req = OperationRequest(command="read-status", runtime=runtime, parameters={"channel": "all"})

    res = run_readonly(req, opener=lambda *args, **kwargs: session)

    assert res["outputs"] == [
        {"channel": 1, "enabled": True},
        {"channel": 2, "enabled": False},
    ]
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


def test_readonly_e3646a_status_reads_selected_output_only():
    session = E3646AStatusSession()
    runtime = RuntimeOptions(resource="ASRL1::INSTR")
    req = OperationRequest(command="read-status", runtime=runtime, parameters={"channel": 1})

    res = run_readonly(req, opener=lambda *args, **kwargs: session)

    assert res["outputs"] == [{"channel": 1, "enabled": True}]
    assert session.events == [
        "query:*IDN?",
        "query:SYST:ERR?",
        "query:INST:NSEL?",
        "write:INST:NSEL 1",
        "query:OUTP?",
        "write:INST:NSEL 1",
    ]


def test_readonly_e3646a_status_rejects_invalid_channel_before_status_reads():
    session = E3646AStatusSession()
    runtime = RuntimeOptions(resource="ASRL1::INSTR")
    req = OperationRequest(command="read-status", runtime=runtime, parameters={"channel": 3})

    with pytest.raises(UnsupportedChannelError, match="channel 3 is not supported"):
        run_readonly(req, opener=lambda *args, **kwargs: session)

    assert session.events == ["query:*IDN?"]

def test_readonly_simulate_readback():
    runtime = RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", simulate=True)
    req = OperationRequest(command="readback", runtime=runtime, parameters={"channel": 1})
    res = run_readonly(req, opener=sim_opener)
    assert len(res["channels"]) == 1
    assert res["channels"][0]["channel"] == 1
    assert "voltage" in res["channels"][0]["setpoints"]
    assert "current" in res["channels"][0]["setpoints"]


@pytest.mark.parametrize("command", ["read-status", "readback"])
def test_readonly_simulate_psm2010_single_channel(command: str):
    runtime = RuntimeOptions(resource="ASRL1::SIM::PSM2010::INSTR", simulate=True)
    req = OperationRequest(command=command, runtime=runtime, parameters={"channel": "all"})

    res = run_readonly(req, opener=sim_opener)

    assert "PSM-2010" in res["idn_raw"]
    collection = res["outputs"] if command == "read-status" else res["channels"]
    assert [item["channel"] for item in collection] == [1]


def test_readonly_simulate_e3646a_readback_all_channels():
    runtime = RuntimeOptions(resource="ASRL1::SIM::E3646A::INSTR", simulate=True)
    req = OperationRequest(command="readback", runtime=runtime, parameters={"channel": "all"})

    res = run_readonly(req, opener=sim_opener)

    assert "E3646A" in res["idn_raw"]
    assert [channel["channel"] for channel in res["channels"]] == [1, 2]
    assert res["channels"][1]["setpoints"] == {"voltage": 2.0, "current": 0.1}

def test_readonly_simulate_measure_all_e36312a():
    runtime = RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", simulate=True)
    req = OperationRequest(command="measure-all", runtime=runtime)
    res = run_readonly(req, opener=sim_opener)
    assert len(res["channels"]) == 3
    assert res["channels"][0]["channel"] == 1

def test_readonly_simulate_measure_all_edu36311a_fails():
    runtime = RuntimeOptions(resource="USB0::SIM::EDU36311A::INSTR", simulate=True)
    req = OperationRequest(command="measure-all", runtime=runtime)
    with pytest.raises(UnsupportedModelError, match="measure-all is only supported for E36312A"):
        run_readonly(req, opener=sim_opener)

def test_readonly_unsupported_command():
    runtime = RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", simulate=True)
    req = OperationRequest(command="invalid-cmd", runtime=runtime)
    with pytest.raises(CoreValidationError, match="unsupported read-only command"):
        run_readonly(req, opener=sim_opener)

def test_readonly_invalid_channel():
    runtime = RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", simulate=True)
    req = OperationRequest(command="readback", runtime=runtime, parameters={"channel": 99})
    with pytest.raises(UnsupportedChannelError, match="channel 99 is not supported"):
        run_readonly(req, opener=sim_opener)


def test_readonly_dry_run_returns_plan_without_opener():
    runtime = RuntimeOptions(resource="USB0::FAKE::E36312A::INSTR", dry_run=True)
    req = OperationRequest(command="read-status", runtime=runtime, parameters={"channel": "all"})

    def fail_opener(*args, **kwargs):
        raise AssertionError("dry-run must not open hardware")

    res = run_readonly(req, opener=fail_opener)

    assert res["plan"]["operation"] == {"name": "read-status"}
    assert res["plan"]["target"]["resource"] == "USB0::FAKE::E36312A::INSTR"
    assert res["plan"]["hardware_touched"] is False


def test_readonly_measure_all_rejects_channel_filter():
    runtime = RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", simulate=True)
    req = OperationRequest(command="measure-all", runtime=runtime, parameters={"channel": 1})
    with pytest.raises(CoreValidationError, match="measure-all always reads all channels"):
        run_readonly(req, opener=sim_opener)


def test_live_panel_read_returns_only_panel_fields():
    runtime = RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", simulate=True)
    req = OperationRequest(command="live-panel", runtime=runtime)

    res = run_live_panel_read(req, opener=sim_opener)

    assert set(res) == {"resource", "idn_raw", "idn", "channels"}
    assert res["idn"]["model"] == "E36312A"
    assert len(res["channels"]) == 3
    assert set(res["channels"][0]) == {
        "channel",
        "output_enabled",
        "over_voltage_tripped",
        "over_current_tripped",
        "protection_tripped",
        "over_voltage_protection_level",
        "over_current_protection_enabled",
        "setpoints",
        "measurements",
    }
    assert set(res["channels"][0]["setpoints"]) == {"voltage", "current"}
    assert set(res["channels"][0]["measurements"]) == {"voltage", "current"}
    assert res["channels"][0]["over_voltage_tripped"] is False
    assert res["channels"][0]["over_current_tripped"] is False
    assert res["channels"][0]["protection_tripped"] is False
    assert isinstance(res["channels"][0]["over_voltage_protection_level"], float)
    assert res["channels"][0]["over_current_protection_enabled"] in {True, False}
    assert "protection_settings" not in res
    assert "errors" not in res
    assert "read_count" not in res


@pytest.mark.parametrize(
    ("range_response", "expected_range"),
    [("P8V", "LOW"), ("P20V", "HIGH")],
)
def test_live_panel_read_psm_projects_driver_output_range(
    range_response: str,
    expected_range: str,
):
    session = PSM2010LiveSession(range_response)
    runtime = RuntimeOptions(resource="ASRL1::INSTR", simulate=False)
    req = OperationRequest(command="live-panel", runtime=runtime)

    res = run_live_panel_read(req, opener=lambda *args, **kwargs: session)

    assert res["idn"]["model"] == "PSM-2010"
    assert res["channels"] == [
        {
            "channel": 1,
            "output_enabled": False,
            "over_voltage_tripped": False,
            "over_current_tripped": False,
            "protection_tripped": False,
            "over_voltage_protection_level": 5.0,
            "over_current_protection_enabled": True,
            "setpoints": {"voltage": 1.0, "current": 0.1},
            "measurements": {"voltage": 0.0, "current": 0.0},
            "output_range": expected_range,
        }
    ]
    assert session.events.count("query:VOLT:RANG?") == 1
    assert not any(event.startswith("write:") for event in session.events)


def test_live_panel_read_psm_unknown_output_range_is_none():
    session = PSM2010LiveSession("P12V")
    runtime = RuntimeOptions(resource="ASRL1::INSTR", simulate=False)
    req = OperationRequest(command="live-panel", runtime=runtime)

    res = run_live_panel_read(req, opener=lambda *args, **kwargs: session)

    assert res["channels"][0]["output_range"] is None
    assert session.events.count("query:VOLT:RANG?") == 1


def test_live_panel_read_reports_protection_by_channel(monkeypatch):
    from powers_tool_core.testing import simulator

    resource = "USB0::SIM::E36312A::INSTR"
    runtime = RuntimeOptions(resource=resource, simulate=True)
    req = OperationRequest(command="live-panel", runtime=runtime)

    def trip_opener(resource_name, manager, backend=None, timeout_ms=5000):
        monkeypatch.setitem(
            simulator.SIMULATED_PROTECTION_TRIPS[resource_name][2],
            "current",
            True,
        )
        return open_resource(resource_name, manager, backend=backend, timeout_ms=timeout_ms)

    res = run_live_panel_read(req, opener=trip_opener)

    assert [channel["over_current_tripped"] for channel in res["channels"]] == [False, True, False]
    assert [channel["protection_tripped"] for channel in res["channels"]] == [False, True, False]
