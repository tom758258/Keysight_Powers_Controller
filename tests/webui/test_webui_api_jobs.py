"""WebUI job admission, confirmation, lock, and validation tests."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from _webui_api_helpers import wait_for_job
from _webui_shared import WEBUI_HIDDEN_UNSUPPORTED_COMMANDS
from powers_tool_webui.jobs import Job, JobStatus, MAX_JOB_EVENTS


def test_job_event_history_is_bounded() -> None:
    job = Job("job-id", "sequence", {}, {})

    for index in range(MAX_JOB_EVENTS + 44):
        job.add_event("progress", {"percent": index})

    assert len(job.events) == MAX_JOB_EVENTS
    assert job.events[0]["id"] == 45
    assert job.events[-1]["id"] == MAX_JOB_EVENTS + 44


def test_job_event_buffer_is_thread_safe() -> None:
    job = Job("job-id", "sequence", {}, {})

    def add_events(worker: int) -> None:
        for index in range(100):
            job.add_event("progress", {"worker": worker, "index": index})

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(add_events, range(4)))

    events = job.events_after(0)
    event_ids = [event["id"] for event in events]
    assert len(events) == MAX_JOB_EVENTS
    assert len(event_ids) == len(set(event_ids))
    assert all(left < right for left, right in zip(event_ids, event_ids[1:]))

    last_event_id = event_ids[len(event_ids) // 2]
    newer_events = job.events_after(last_event_id)
    assert newer_events
    assert all(event["id"] > last_event_id for event in newer_events)


def test_simulated_sequence_post_returns_before_execution_finishes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from powers_tool_webui import app as webui_app
    from powers_tool_webui.jobs import job_manager

    execution_started = threading.Event()
    release_execution = threading.Event()

    def paused_execution(job: Job) -> dict[str, str]:
        job.add_event(
            "progress",
            {
                "completed_units": 1,
                "total_units": 2,
                "percent": 50,
                "message": "50% (1/2 execution units)",
            },
        )
        execution_started.set()
        assert release_execution.wait(timeout=2)
        return {"status": "completed"}

    monkeypatch.setattr(webui_app, "execute_job_command", paused_execution)
    payload = {
        "command": "sequence",
        "runtime": {
            "simulate": True,
            "planning_model_id": "keysight-e36312a",
        },
        "parameters": {
            "document": {
                "version": 2,
                "loop_count": 1,
                "steps": [
                    {"action": "wait", "seconds": 0},
                    {"action": "wait", "seconds": 0},
                ],
            }
        },
    }

    with client, ThreadPoolExecutor(max_workers=1) as executor:
        response_future = executor.submit(client.post, "/api/jobs", json=payload)
        response_data = None
        try:
            response = response_future.result(timeout=1)
            assert response.status_code == 200
            response_data = response.json()
            assert response_data["job_id"]
            assert response_data["status_url"]
            assert response_data["events_url"]
            assert response_data["execution_summary"]["execution_units"] == 2
            assert execution_started.wait(timeout=1)

            job = job_manager.jobs[response_data["job_id"]]
            assert job.status in {JobStatus.STARTED, JobStatus.PROGRESS}
            assert any(event["type"] == "progress" for event in job.events_after(0))
        finally:
            release_execution.set()

        assert response_data is not None
        job_data = wait_for_job(client, response_data["job_id"])
        assert job_data["status"] == "finished"


def test_sequence_job_response_includes_long_execution_warning(client: TestClient) -> None:
    response = client.post(
        "/api/jobs",
        json={
            "command": "sequence",
            "runtime": {
                "dry_run": True,
                "planning_model_id": "keysight-e36312a",
            },
            "parameters": {
                "document": {
                    "version": 2,
                    "loop_count": 1_000,
                    "steps": [{"action": "wait", "seconds": 0}] * 101,
                }
            },
        },
    )

    assert response.status_code == 200
    summary = response.json()["execution_summary"]
    assert summary["execution_units"] == 101_000
    assert "maximum 1,000,000" in summary["execution_warning"]

def test_post_job_real_output_without_confirm_fails(client: TestClient):
    payload = {
        "command": "output-on",
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "simulate": False,
            "dry_run": False,
            "timeout_ms": 5000,
            "confirm": False  # Missing confirm!
        },
        "parameters": {"channel": 1}
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200  # Job is accepted
    data = response.json()
    job_id = data["job_id"]

    # Wait for job to fail
    for _ in range(20):
        res = client.get(f"/api/jobs/{job_id}")
        if res.json()["status"] in ("finished", "failed"):
            break
        time.sleep(0.1)

    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "failed"
    assert "requires explicit confirmation" in job_data["error"]


def test_post_job_real_apply_all_without_confirm_fails(client: TestClient):
    payload = {
        "command": "apply",
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "simulate": False,
            "dry_run": False,
            "timeout_ms": 5000,
            "confirm": False,
        },
        "parameters": {"channel": "all", "voltage": 5.0, "current": 1.0},
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    for _ in range(20):
        res = client.get(f"/api/jobs/{job_id}")
        if res.json()["status"] in ("finished", "failed"):
            break
        time.sleep(0.1)

    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "failed"
    assert "requires explicit confirmation" in job_data["error"]


def test_hidden_unsupported_command_is_rejected_before_submit(client: TestClient):
    from powers_tool_webui.jobs import job_manager

    jobs_before = set(job_manager.jobs)
    payload = {
        "command": "doctor",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
        },
        "parameters": {},
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 400
    assert "not supported by /api/jobs" in response.json()["detail"]
    assert set(job_manager.jobs) == jobs_before


def test_unknown_command_is_rejected_before_submit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from powers_tool_webui.jobs import job_manager

    jobs_before = set(job_manager.jobs)

    async def forbidden_submit(**kwargs: object) -> str:
        raise AssertionError("submit_job must not be called")

    def forbidden_lock_check() -> bool:
        raise AssertionError("hardware lock must not be checked")

    monkeypatch.setattr(job_manager, "submit_job", forbidden_submit)
    monkeypatch.setattr(job_manager, "is_hardware_locked", forbidden_lock_check)
    response = client.post(
        "/api/jobs",
        json={"command": "unknown-command", "runtime": {}, "parameters": {}},
    )

    assert response.status_code == 400
    assert "not supported by /api/jobs" in response.json()["detail"]
    assert set(job_manager.jobs) == jobs_before


@pytest.mark.parametrize("command", sorted(WEBUI_HIDDEN_UNSUPPORTED_COMMANDS))
def test_all_webui_unsupported_commands_are_rejected_before_submit(
    client: TestClient,
    command: str,
) -> None:
    from powers_tool_webui.jobs import job_manager

    jobs_before = set(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={"command": command, "runtime": {}, "parameters": {}},
    )

    assert response.status_code == 400
    assert set(job_manager.jobs) == jobs_before


def test_hardware_lock_prevents_concurrent_jobs(client: TestClient):
    """Test that non-simulate/non-dry-run jobs are rejected when hardware is locked."""
    from powers_tool_webui.jobs import job_manager
    job_manager.active_job_id = "fake-active-job"

    payload = {
        "command": "set",
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "simulate": False,
            "dry_run": False,
            "confirm": True
        },
        "parameters": {"channel": 1, "voltage": 5.0, "current": 1.0}
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 409
    assert "Hardware is currently locked" in response.json()["detail"]

    # Cleanup
    job_manager.active_job_id = None


def test_hardware_lock_allows_simulate_jobs(client: TestClient):
    """Test that simulate jobs can still run when hardware is locked."""
    from powers_tool_webui.jobs import job_manager
    job_manager.active_job_id = "fake-active-job"

    payload = {
        "command": "set",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,  # Simulate mode should bypass lock
            "confirm": False
        },
        "parameters": {"channel": 1, "voltage": 5.0, "current": 1.0}
    }
    response = client.post("/api/jobs", json=payload)
    # Should succeed even when hardware is locked (simulate mode)
    assert response.status_code == 200
    assert response.json()["ok"] is True

    # Cleanup
    job_manager.active_job_id = None


def test_sequence_lint_dry_run(client: TestClient):
    payload = {
        "command": "sequence",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
            "dry_run": True
        },
        "parameters": {
            "lint": True,
            "document": {
                "version": 1,
                "steps": [
                    {"action": "set", "channel": 1, "voltage": 5.0, "current": 1.0},
                    {"action": "output-on", "channel": 1},
                    {"action": "wait", "seconds": 0.1},
                    {"action": "safe-off", "channel": "all"}
                ]
            }
        }
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200
    data = response.json()
    job_id = data["job_id"]

    for _ in range(20):
        res = client.get(f"/api/jobs/{job_id}")
        if res.json()["status"] in ("finished", "failed"):
            break
        time.sleep(0.1)

    job_data = client.get(f"/api/jobs/{job_id}").json()
    assert job_data["status"] == "finished"
    assert job_data["result"]["status"] == "valid"


def test_ramp_list_lint_dry_run(client: TestClient):
    payload = {
        "command": "ramp-list",
        "runtime": {"simulate": True, "dry_run": True, "resource": "USB0::SIM::E36312A::INSTR"},
        "parameters": {
            "lint": True,
            "document": {
                "kind": "powers-tool-ramp-list",
                "version": 2,
                "segments": [
                    {
                        "channel": 1,
                        "current": 0.1,
                        "start_voltage": 0,
                        "stop_voltage": 1,
                        "step_voltage": 0.5,
                        "delay_ms": 100,
                        "hold_ms": 0,
                    }
                ],
            },
        },
    }

    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    for _ in range(20):
        job_data = client.get(f"/api/jobs/{job_id}").json()
        if job_data["status"] in ("finished", "failed"):
            break
        time.sleep(0.1)

    assert job_data["status"] == "finished"
    assert job_data["result"]["status"] == "valid"
    assert job_data["result"]["segment_count"] == 1


def test_api_accepts_zero_delay_ramp_list_step_pulse(client: TestClient):
    payload = {
        "command": "ramp-list",
        "runtime": {
            "simulate": True,
            "dry_run": True,
            "planning_model_id": "keysight-e36312a",
        },
        "parameters": {
            "document": {
                "kind": "powers-tool-ramp-list",
                "version": 2,
                "completion_pulse": {"timing": "step", "pins": [1], "polarity": "positive"},
                "segments": [{
                    "channel": 1, "current": 0.1, "start_voltage": 0, "stop_voltage": 1,
                    "step_voltage": 0.5, "delay_ms": 0, "hold_ms": 0,
                }],
            },
        },
    }

    response = client.post("/api/jobs", json=payload)

    assert response.status_code == 200


@pytest.mark.parametrize("version", [1, "2", True, False, 2.0, None])
def test_api_rejects_invalid_ramp_list_version_before_submission(
    client: TestClient,
    monkeypatch,
    version: object,
) -> None:
    from powers_tool_webui.jobs import job_manager

    jobs_before = set(job_manager.jobs)

    async def forbidden_submit(**kwargs: object) -> str:
        raise AssertionError("submit_job must not be called")

    def forbidden_lock_check() -> bool:
        raise AssertionError("hardware lock must not be checked")

    monkeypatch.setattr(job_manager, "submit_job", forbidden_submit)
    monkeypatch.setattr(job_manager, "is_hardware_locked", forbidden_lock_check)
    response = client.post(
        "/api/jobs",
        json={
            "command": "ramp-list",
            "runtime": {"simulate": True, "resource": "USB0::SIM::E36312A::INSTR"},
            "parameters": {
                "document": {
                    "kind": "powers-tool-ramp-list",
                    "version": version,
                    "segments": [{
                        "channel": 1, "current": 0.1, "start_voltage": 0,
                        "stop_voltage": 1, "step_voltage": 0.5,
                        "delay_ms": 0, "hold_ms": 0,
                    }],
                }
            },
        },
    )

    assert response.status_code == 400
    assert "unsupported ramp-list version" in response.json()["detail"]
    assert set(job_manager.jobs) == jobs_before


def test_api_rejects_legacy_ramp_list_kind_before_submission(
    client: TestClient,
    monkeypatch,
) -> None:
    from powers_tool_webui.jobs import job_manager

    jobs_before = set(job_manager.jobs)

    async def forbidden_submit(**kwargs: object) -> str:
        raise AssertionError("submit_job must not be called")

    def forbidden_lock_check() -> bool:
        raise AssertionError("hardware lock must not be checked")

    monkeypatch.setattr(job_manager, "submit_job", forbidden_submit)
    monkeypatch.setattr(job_manager, "is_hardware_locked", forbidden_lock_check)
    response = client.post(
        "/api/jobs",
        json={
            "command": "ramp-list",
            "runtime": {"simulate": True, "resource": "USB0::SIM::E36312A::INSTR"},
            "parameters": {
                "document": {
                    "kind": "keysight-power-ramp-list",
                    "version": 2,
                    "segments": [{
                        "channel": 1, "current": 0.1, "start_voltage": 0,
                        "stop_voltage": 1, "step_voltage": 0.5,
                        "delay_ms": 0, "hold_ms": 0,
                    }],
                }
            },
        },
    )

    assert response.status_code == 400
    assert "ramp-list kind must be" in response.json()["detail"]
    assert set(job_manager.jobs) == jobs_before


@pytest.mark.parametrize("field", ["completion_pulse_mode", "completion_pulse_dwell_ms", "wait_timeout_ms", "poll_ms"])
def test_api_rejects_removed_ramp_native_fields_before_creating_job(client: TestClient, field: str):
    from powers_tool_webui.jobs import job_manager

    jobs_before = len(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "ramp",
            "runtime": {"simulate": True},
            "parameters": {
                "channel": 1,
                "start_voltage": 0,
                "stop_voltage": 1,
                "step_voltage": 0.5,
                "current": 0.1,
                field: "native" if field == "completion_pulse_mode" else 10,
            },
        },
    )

    assert response.status_code == 400
    assert field in response.json()["detail"]
    assert len(job_manager.jobs) == jobs_before


@pytest.mark.parametrize(
    ("command", "parameters"),
    [
        ("protection-set", {"all": False, "ocp": "on"}),
        ("protection-status", {"all": False}),
        ("clear-protection", {"all": False}),
    ],
)
def test_api_rejects_false_protection_all_before_job_or_lock(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    parameters: dict[str, object],
) -> None:
    from powers_tool_webui.jobs import job_manager

    async def forbidden_submit(**kwargs: object) -> str:
        raise AssertionError("invalid request must not create a job")

    def forbidden_lock_check() -> bool:
        raise AssertionError("invalid request must not inspect the hardware lock")

    monkeypatch.setattr(job_manager, "submit_job", forbidden_submit)
    monkeypatch.setattr(job_manager, "is_hardware_locked", forbidden_lock_check)
    response = client.post(
        "/api/jobs",
        json={"command": command, "runtime": {"simulate": True}, "parameters": parameters},
    )

    assert response.status_code == 400
    assert "all=false" in response.json()["detail"]


def test_api_restore_requires_channel_before_job_or_lock(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from powers_tool_core.command_runner import run_core_command
    from powers_tool_core.core import OperationRequest, RuntimeOptions
    from powers_tool_webui.jobs import job_manager

    snapshot = run_core_command(
        OperationRequest(
            "snapshot",
            RuntimeOptions(simulate=True, resource="USB0::SIM::E36312A::INSTR"),
        )
    )

    async def forbidden_submit(**kwargs: object) -> str:
        raise AssertionError("invalid request must not create a job")

    def forbidden_lock_check() -> bool:
        raise AssertionError("invalid request must not inspect the hardware lock")

    monkeypatch.setattr(job_manager, "submit_job", forbidden_submit)
    monkeypatch.setattr(job_manager, "is_hardware_locked", forbidden_lock_check)
    response = client.post(
        "/api/jobs",
        json={
            "command": "restore-from-snapshot",
            "runtime": {"simulate": True, "resource": "USB0::SIM::E36312A::INSTR"},
            "parameters": {"document": snapshot},
        },
    )

    assert response.status_code == 400
    assert "restore-from-snapshot requires channel" in response.json()["detail"]

