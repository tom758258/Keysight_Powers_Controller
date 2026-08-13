"""WebUI SSE, Live Data, and hardware-I/O exclusion tests."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

def test_sse_event_order(client: TestClient):
    payload = {
        "command": "read-status",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True
        },
        "parameters": {}
    }
    response = client.post("/api/jobs", json=payload)
    job_id = response.json()["job_id"]

    # Check job events array directly
    from powers_tool_webui.jobs import job_manager
    import asyncio

    async def check_events():
        events = await job_manager.get_job_events(job_id)
        types = [e["type"] for e in events]
        assert "accepted" in types
        assert "started" in types
        assert "finished" in types or "failed" in types

    asyncio.run(check_events())


def test_live_data_missing_resource_fails(client: TestClient):
    response = client.post(
        "/api/live",
        json={"runtime": {"simulate": False}, "parameters": {"interval_ms": 50}},
    )
    assert response.status_code == 400
    assert "requires a selected hardware resource" in response.json()["detail"]


def test_live_data_simulate_fails(client: TestClient):
    response = client.post(
        "/api/live",
        json={
            "runtime": {
                "resource": "USB0::SIM::E36312A::INSTR",
                "simulate": True,
            },
            "parameters": {"interval_ms": 50},
        },
    )
    assert response.status_code == 400
    assert "simulate and dry-run are not supported" in response.json()["detail"]


def test_live_data_start_and_stop(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _patch_live_panel(monkeypatch)
    payload = {
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "simulate": False
        },
        "parameters": {
            "interval_ms": 100
        }
    }
    response = client.post("/api/live", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    job_id = data["job_id"]

    time.sleep(0.3) # Let it generate a few events

    # Stop it
    stop_response = client.post(f"/api/live/{job_id}/stop")
    assert stop_response.status_code == 200

    # Verify it stopped
    from powers_tool_webui.jobs import job_manager
    job = job_manager.jobs.get(job_id)
    assert job.cancel_requested is True


def test_live_data_live_panel_emits_three_channel_panel_sample(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[Any, dict[str, Any]]] = []

    def fake_live_panel(runtime: Any, parameters: dict[str, Any]) -> dict[str, Any]:
        calls.append((runtime, parameters))
        return _fake_live_panel(runtime.resource)

    from powers_tool_webui import commands

    monkeypatch.setattr(commands, "execute_live_panel_read", fake_live_panel)
    payload = {
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "simulate": False,
        },
        "parameters": {
            "interval_ms": 50,
        },
    }
    response = client.post("/api/live", json=payload)
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    event = _wait_for_live_progress(job_id)
    sample = event["data"]
    assert sample["status"] == "ok"
    assert sample["stale"] is False
    assert sample["resource"] == "USB0::FAKE::E36312A::INSTR"
    assert sample["model"] == "E36312A"
    assert sample["mode"] == "live"
    assert [channel["channel"] for channel in sample["channels"]] == [1, 2, 3]
    assert [channel["measured_voltage"] for channel in sample["channels"]] == [1.1, 2.2, 3.3]
    assert [channel["measured_current"] for channel in sample["channels"]] == [0.11, 0.22, 0.33]
    assert [channel["set_voltage"] for channel in sample["channels"]] == [1.0, 2.0, 3.0]
    assert [channel["set_current"] for channel in sample["channels"]] == [0.1, 0.2, 0.3]
    assert [channel["output_enabled"] for channel in sample["channels"]] == [True, False, True]
    assert [channel["over_voltage_tripped"] for channel in sample["channels"]] == [False, False, False]
    assert [channel["over_current_tripped"] for channel in sample["channels"]] == [True, False, False]
    assert [channel["protection_tripped"] for channel in sample["channels"]] == [True, False, False]
    assert [channel["over_voltage_protection_level"] for channel in sample["channels"]] == [5.0, 6.0, 7.0]
    assert [channel["over_current_protection_enabled"] for channel in sample["channels"]] == [True, False, True]
    assert calls
    assert calls[0][0].simulate is False
    assert calls[0][1] == {}

    assert client.post(f"/api/live/{job_id}/stop").status_code == 200


@pytest.mark.parametrize("envelope_key", ["result", "data"])
def test_live_data_live_panel_unwraps_envelope(envelope_key: str):
    from powers_tool_webui.app import _live_panel_sample_from_reading

    sample = _live_panel_sample_from_reading(
        {envelope_key: _fake_e36312a_live_panel("USB0::FAKE::E36312A::INSTR")},
        {"resource": "USB0::FAKE::E36312A::INSTR"},
    )

    assert sample["status"] == "ok"
    assert sample["stale"] is False
    assert sample["mode"] == "live"
    assert sample["channels"][0]["measured_voltage"] == 1.000237
    assert sample["channels"][0]["measured_current"] == 0.000019
    assert sample["channels"][0]["set_voltage"] == 1.0
    assert sample["channels"][0]["set_current"] == 0.1
    assert sample["channels"][0]["over_voltage_tripped"] is False
    assert sample["channels"][0]["over_current_tripped"] is False
    assert sample["channels"][0]["protection_tripped"] is False
    assert sample["channels"][0]["over_voltage_protection_level"] == 5.0
    assert sample["channels"][0]["over_current_protection_enabled"] is True
    assert sample["channels"][1]["set_voltage"] == 0.0
    assert sample["channels"][1]["over_current_protection_enabled"] is False
    assert sample["channels"][2]["measured_current"] == 0.0


def test_live_data_live_panel_with_no_panel_records_is_stale_error(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    def fake_live_panel(runtime: Any, parameters: dict[str, Any]) -> dict[str, Any]:
        return {"resource": runtime.resource, "model": "E36312A"}

    from powers_tool_webui import commands

    monkeypatch.setattr(commands, "execute_live_panel_read", fake_live_panel)
    response = client.post(
        "/api/live",
        json={
            "runtime": {
                "resource": "USB0::FAKE::E36312A::INSTR",
                "simulate": False,
            },
            "parameters": {"interval_ms": 50},
        },
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    sample = _wait_for_live_progress(job_id)["data"]
    assert sample["status"] == "error"
    assert sample["stale"] is True
    assert "did not include output, readback, or measurement records" in sample["message"]
    assert [channel["measured_voltage"] for channel in sample["channels"]] == [None, None, None]
    assert [channel["protection_tripped"] for channel in sample["channels"]] == [None, None, None]
    assert [channel["over_voltage_protection_level"] for channel in sample["channels"]] == [None, None, None]
    assert [channel["over_current_protection_enabled"] for channel in sample["channels"]] == [None, None, None]

    assert client.post(f"/api/live/{job_id}/stop").status_code == 200


def test_live_data_panel_sample_normalizes_numeric_values():
    from powers_tool_webui.app import _live_panel_sample_from_reading

    sample = _live_panel_sample_from_reading(
        {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "idn": {"model": "E36312A"},
            "outputs": [
                {"channel": 1, "enabled": "0"},
                {"channel": 2, "enabled": "OFF"},
                {"channel": 3, "enabled": 2},
            ],
            "readback": [
                {"channel": 1, "setpoints": {"voltage": "1", "current": "0.1"}},
                {"channel": 2, "setpoints": {"voltage": "", "current": None}},
            ],
            "measurements": [
                {"channel": 1, "measurements": {"voltage": "1.000237", "current": "0.000019"}},
                {"channel": 2, "measurements": {"voltage": "nan", "current": "inf"}},
            ],
            "channels": [
                {
                    "channel": 1,
                    "output_enabled": "ON",
                    "over_voltage_tripped": "0",
                    "over_current_tripped": "1",
                    "over_voltage_protection_level": "5.5",
                    "over_current_protection_enabled": "on",
                },
                {
                    "channel": 2,
                    "output_enabled": "unknown",
                    "over_voltage_tripped": None,
                    "over_current_tripped": None,
                    "protection_tripped": "false",
                    "over_voltage_protection_level": "nan",
                    "over_current_protection_enabled": "off",
                },
            ],
        },
        {"resource": "USB0::FAKE::E36312A::INSTR"},
    )

    assert sample["status"] == "ok"
    assert sample["stale"] is False
    assert sample["model"] == "E36312A"
    assert sample["channels"][0]["measured_voltage"] == 1.000237
    assert sample["channels"][0]["measured_current"] == 0.000019
    assert sample["channels"][0]["set_voltage"] == 1.0
    assert sample["channels"][0]["set_current"] == 0.1
    assert [channel["output_enabled"] for channel in sample["channels"]] == [True, False, None]
    assert sample["channels"][1]["measured_voltage"] is None
    assert sample["channels"][1]["measured_current"] is None
    assert sample["channels"][1]["set_voltage"] is None
    assert sample["channels"][1]["set_current"] is None
    assert sample["channels"][0]["over_voltage_tripped"] is False
    assert sample["channels"][0]["over_current_tripped"] is True
    assert sample["channels"][0]["protection_tripped"] is True
    assert sample["channels"][0]["over_voltage_protection_level"] == 5.5
    assert sample["channels"][0]["over_current_protection_enabled"] is True
    assert sample["channels"][1]["protection_tripped"] is False
    assert sample["channels"][1]["over_voltage_protection_level"] is None
    assert sample["channels"][1]["over_current_protection_enabled"] is False


@pytest.mark.parametrize(
    ("raw_range", "expected_range"),
    [("LOW", "LOW"), (" high ", "HIGH"), ("P8V", None), (None, None)],
)
def test_live_data_panel_sample_normalizes_psm_output_range(
    raw_range: str | None,
    expected_range: str | None,
):
    from powers_tool_webui.app import _live_panel_sample_from_reading

    sample = _live_panel_sample_from_reading(
        {
            "resource": "ASRL1::FAKE::PSM2010::INSTR",
            "idn": {"manufacturer": "GW.Inc", "model": "PSM-2010"},
            "channels": [
                {
                    "channel": 1,
                    "output_range": raw_range,
                    "output_enabled": False,
                    "setpoints": {"voltage": "1.0", "current": "0.1"},
                    "measurements": {"voltage": "0.0", "current": "0.0"},
                }
            ],
        },
        {"resource": "ASRL1::FAKE::PSM2010::INSTR"},
    )

    assert sample["model_id"] == "gw-instek-psm-2010"
    assert sample["channels"][0]["output_range"] == expected_range
    assert sample["channels"][0]["measured_voltage"] == 0.0
    assert sample["channels"][0]["set_current"] == 0.1
    assert sample["channels"][0]["output_enabled"] is False


def test_live_data_real_mode_reports_busy_without_live_panel_call(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from powers_tool_webui import commands
    from powers_tool_webui.jobs import job_manager

    def fail_live_panel(*args, **kwargs):
        raise AssertionError("live data must not read hardware while another real job owns the lock")

    monkeypatch.setattr(commands, "execute_live_panel_read", fail_live_panel)
    job_manager.active_job_id = "write-job"

    response = client.post(
        "/api/live",
        json={
            "runtime": {
                "resource": "USB0::FAKE::E36312A::INSTR",
                "simulate": False,
            },
            "parameters": {"interval_ms": 50},
        },
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    event = _wait_for_live_progress(job_id)
    assert event["data"]["status"] == "busy"
    assert event["data"]["stale"] is True
    assert [channel["channel"] for channel in event["data"]["channels"]] == [1, 2, 3]
    assert [channel["measured_voltage"] for channel in event["data"]["channels"]] == [None, None, None]
    assert [channel["protection_tripped"] for channel in event["data"]["channels"]] == [None, None, None]
    assert [channel["over_voltage_protection_level"] for channel in event["data"]["channels"]] == [None, None, None]
    assert [channel["over_current_protection_enabled"] for channel in event["data"]["channels"]] == [None, None, None]

    assert client.post(f"/api/live/{job_id}/stop").status_code == 200
    job_manager.active_job_id = None


def test_real_command_waits_for_inflight_live_panel_without_overlap(monkeypatch: pytest.MonkeyPatch):
    import asyncio

    from powers_tool_webui import app as web_app
    from powers_tool_webui import commands
    from powers_tool_webui.jobs import job_manager

    job_manager.jobs.clear()
    job_manager.active_job_id = None

    live_entered = threading.Event()
    release_live = threading.Event()
    live_active = threading.Event()
    command_entered = threading.Event()
    overlap: list[str] = []

    def fake_live_panel(runtime: Any, parameters: dict[str, Any]) -> dict[str, Any]:
        live_active.set()
        live_entered.set()
        release_live.wait(timeout=2)
        live_active.clear()
        return _fake_live_panel(runtime.resource)

    def fake_execute_job(job):
        command_entered.set()
        if live_active.is_set():
            overlap.append("command overlapped live panel read")
        return {"operation": job.command}

    monkeypatch.setattr(commands, "execute_live_panel_read", fake_live_panel)
    monkeypatch.setattr(web_app, "execute_job_command", fake_execute_job)

    async def run_check() -> None:
        live_job_id = await job_manager.submit_job(
            command="live-data",
            runtime={
                "resource": "USB0::FAKE::E36312A::INSTR",
                "simulate": False,
            },
            parameters={"interval_ms": 50},
        )
        live_task = asyncio.create_task(web_app._execute_live_data_background(live_job_id))
        assert await asyncio.to_thread(live_entered.wait, 2)

        command_job_id = await job_manager.submit_job(
            command="read-status",
            runtime={
                "resource": "USB0::FAKE::E36312A::INSTR",
                "simulate": False,
                "dry_run": False,
            },
            parameters={"channel": 1},
        )
        command_task = asyncio.create_task(web_app._execute_job_background(command_job_id))
        await asyncio.sleep(0.15)
        assert not command_entered.is_set()

        release_live.set()
        assert await asyncio.to_thread(command_entered.wait, 2)
        await command_task
        assert job_manager.jobs[command_job_id].status.value == "finished"
        assert overlap == []

        await job_manager.cancel_job(live_job_id)
        await live_task

    asyncio.run(run_check())


def test_live_data_stop_terminates_progress_events(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    _patch_live_panel(monkeypatch)
    response = client.post(
        "/api/live",
        json={
            "runtime": {
                "resource": "USB0::FAKE::E36312A::INSTR",
                "simulate": False,
            },
            "parameters": {"interval_ms": 50},
        },
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    _wait_for_live_progress(job_id)

    assert client.post(f"/api/live/{job_id}/stop").status_code == 200
    _wait_for_live_terminal_status(job_id)

    from powers_tool_webui.jobs import job_manager
    job = job_manager.jobs[job_id]
    progress_count = sum(1 for event in job.events if event["type"] == "progress")
    time.sleep(0.15)
    assert sum(1 for event in job.events if event["type"] == "progress") == progress_count


def _wait_for_live_progress(job_id: str) -> dict[str, Any]:
    from powers_tool_webui.jobs import job_manager

    for _ in range(30):
        job = job_manager.jobs[job_id]
        if job.status.value in {"failed", "cancelled"}:
            raise AssertionError(f"live job ended before progress: {job.status.value}: {job.error}")
        progress = [event for event in job.events if event["type"] == "progress"]
        if progress:
            return progress[-1]
        time.sleep(0.05)
    raise AssertionError("live progress event was not emitted")


def _wait_for_live_terminal_status(job_id: str) -> None:
    from powers_tool_webui.jobs import job_manager

    for _ in range(30):
        if job_manager.jobs[job_id].status.value in {"finished", "failed", "cancelled"}:
            return
        time.sleep(0.05)
    raise AssertionError("live job did not stop")


def _patch_live_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    from powers_tool_webui import commands

    def fake_live_panel(runtime: Any, parameters: dict[str, Any]) -> dict[str, Any]:
        assert runtime.simulate is False
        return _fake_live_panel(runtime.resource)

    monkeypatch.setattr(commands, "execute_live_panel_read", fake_live_panel)


def _fake_live_panel(resource: str) -> dict[str, Any]:
    return {
        "resource": resource,
        "idn": {"model": "E36312A"},
        "outputs": [
            {"channel": 1, "enabled": True},
            {"channel": 2, "enabled": False},
            {"channel": 3, "enabled": True},
        ],
        "readback": [
            {"channel": 1, "setpoints": {"voltage": 1.0, "current": 0.1}},
            {"channel": 2, "setpoints": {"voltage": 2.0, "current": 0.2}},
            {"channel": 3, "setpoints": {"voltage": 3.0, "current": 0.3}},
        ],
        "measurements": [
            {"channel": 1, "measurements": {"voltage": 1.1, "current": 0.11}},
            {"channel": 2, "measurements": {"voltage": 2.2, "current": 0.22}},
            {"channel": 3, "measurements": {"voltage": 3.3, "current": 0.33}},
        ],
        "channels": [
            {
                "channel": 1,
                "over_voltage_tripped": False,
                "over_current_tripped": True,
                "over_voltage_protection_level": 5.0,
                "over_current_protection_enabled": True,
            },
            {
                "channel": 2,
                "over_voltage_tripped": False,
                "over_current_tripped": False,
                "over_voltage_protection_level": 6.0,
                "over_current_protection_enabled": False,
            },
            {
                "channel": 3,
                "over_voltage_tripped": False,
                "over_current_tripped": False,
                "over_voltage_protection_level": 7.0,
                "over_current_protection_enabled": True,
            },
        ],
    }


def _fake_e36312a_live_panel(resource: str) -> dict[str, Any]:
    return {
        "resource": resource,
        "idn": {"model": "E36312A"},
        "outputs": [
            {"channel": 1, "enabled": True},
            {"channel": 2, "enabled": False},
            {"channel": 3, "enabled": False},
        ],
        "readback": [
            {"channel": 1, "setpoints": {"voltage": "1", "current": "0.1"}},
            {"channel": 2, "setpoints": {"voltage": "0", "current": "0.1"}},
            {"channel": 3, "setpoints": {"voltage": "0", "current": "0.1"}},
        ],
        "measurements": [
            {"channel": 1, "measurements": {"voltage": "1.000237", "current": "0.000019"}},
            {"channel": 2, "measurements": {"voltage": "0.000108", "current": "0.000000"}},
            {"channel": 3, "measurements": {"voltage": "0.0", "current": "0.0"}},
        ],
        "channels": [
            {
                "channel": 1,
                "over_voltage_tripped": False,
                "over_current_tripped": False,
                "over_voltage_protection_level": "5.0",
                "over_current_protection_enabled": "1",
            },
            {
                "channel": 2,
                "over_voltage_tripped": False,
                "over_current_tripped": False,
                "over_voltage_protection_level": "5.0",
                "over_current_protection_enabled": "0",
            },
            {
                "channel": 3,
                "over_voltage_tripped": False,
                "over_current_tripped": False,
                "over_voltage_protection_level": "5.0",
                "over_current_protection_enabled": "1",
            },
        ],
    }
