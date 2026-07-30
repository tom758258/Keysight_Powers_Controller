from __future__ import annotations

import pytest
from powers_tool_core.core import RuntimeOptions, OperationRequest, CoreValidationError, UnsupportedModelError, UnsupportedChannelError
from powers_tool_core.readonly import run_live_panel_read, run_readonly
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
