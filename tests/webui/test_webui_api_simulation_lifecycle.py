"""WebUI simulation and job-lifecycle tests."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from _webui_api_helpers import wait_for_job


def test_webui_commands_simulate_mode(client: TestClient):
    """Test WebUI-specific commands work in simulate mode."""
    commands_to_test = [
        ("capabilities", {}),
        ("safety inspect", {}),
        ("measure", {"channel": 1}),
        ("snapshot", {}),
    ]

    for cmd, params in commands_to_test:
        payload = {
            "command": cmd,
            "runtime": {"simulate": True, "resource": "USB0::SIM::E36312A::INSTR"},
            "parameters": params
        }
        response = client.post("/api/jobs", json=payload)
        assert response.status_code == 200, f"Command {cmd} failed to submit"

        job_data = wait_for_job(client, response.json()["job_id"])
        assert job_data["status"] == "finished", f"Command {cmd} failed: {job_data.get('error')}"


@pytest.mark.parametrize(
    ("command", "parameters"),
    [
        ("verify", {}),
        ("readback", {"channel": "all"}),
        ("safety inspect", {}),
    ],
)
def test_hidden_diagnostic_commands_remain_directly_submittable(client: TestClient, command: str, parameters: dict[str, Any]):
    payload = {
        "command": command,
        "runtime": {
            "simulate": True,
            "resource": "USB0::SIM::E36312A::INSTR",
        },
        "parameters": parameters,
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200

    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")


def test_webui_capabilities_rejects_explicit_sim_resource_mismatch(client: TestClient):
    payload = {
        "command": "capabilities",
        "runtime": {
            "simulate": True,
            "resource": "USB0::SIM::EDU36311A::INSTR",
            "planning_model_id": "keysight-e36312a",
        },
        "parameters": {},
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 400
    assert "does not match deterministic SIM" in response.json()["detail"]


def test_readonly_commands_simulate_with_resource(client: TestClient):
    """Test read-only commands work in simulate mode with resource."""
    for cmd in ["read-status", "readback"]:
        payload = {
            "command": cmd,
            "runtime": {
                "resource": "USB0::SIM::E36312A::INSTR",
                "simulate": True
            },
            "parameters": {}
        }
        response = client.post("/api/jobs", json=payload)
        assert response.status_code == 200, f"Command {cmd} failed to submit"

        job_data = wait_for_job(client, response.json()["job_id"])
        assert job_data["status"] == "finished", f"Command {cmd} failed: {job_data.get('error')}"


def test_output_commands_simulate(client: TestClient):
    """Test output commands work in simulate mode."""
    commands_to_test = [
        ("set", {"channel": 1, "voltage": 5.0, "current": 1.0}),
        ("output-on", {"channel": 1}),
        ("output-off", {"channel": 1}),
        ("safe-off", {"channel": "all"}),
    ]

    for cmd, params in commands_to_test:
        payload = {
            "command": cmd,
            "runtime": {
                "resource": "USB0::SIM::E36312A::INSTR",
                "simulate": True
            },
            "parameters": params
        }
        response = client.post("/api/jobs", json=payload)
        assert response.status_code == 200, f"Command {cmd} failed to submit"

        job_data = wait_for_job(client, response.json()["job_id"])
        assert job_data["status"] == "finished", f"Command {cmd} failed: {job_data.get('error')}"


def test_confirm_policy_enforced(client: TestClient):
    """Test that output-affecting commands without confirm fail for non-simulate."""
    payload = {
        "command": "output-on",
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "simulate": False,
            "dry_run": False,
            "confirm": False  # Missing!
        },
        "parameters": {"channel": 1}
    }
    response = client.post("/api/jobs", json=payload)
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "confirmation" in job_data["error"].lower()


def test_job_get_not_found(client: TestClient):
    """Test GET /api/jobs/{job_id} returns 404 for unknown job."""
    response = client.get("/api/jobs/non-existent-id")
    assert response.status_code == 404


def test_job_cancel_not_found(client: TestClient):
    """Test cancel returns 400 for non-existent job."""
    response = client.post("/api/jobs/non-existent-id/cancel")
    assert response.status_code == 400


def test_running_cancel_keeps_hardware_lock_until_cleanup_completes():
    import asyncio

    from powers_tool_webui.jobs import JobManager, JobStatus

    async def check_lifecycle() -> None:
        manager = JobManager()
        job_id = await manager.submit_job(
            "output-on",
            {"resource": "USB0::FAKE::INSTR", "simulate": False, "dry_run": False},
            {"channel": 1},
        )
        assert await manager.start_job(job_id) is True
        assert manager.active_job_id == job_id

        assert await manager.cancel_job(job_id) is True
        assert manager.jobs[job_id].status == JobStatus.CANCEL_REQUESTED
        assert manager.active_job_id == job_id

        await manager.complete_cancel(job_id)
        assert manager.jobs[job_id].status == JobStatus.CANCELLED
        assert manager.active_job_id is None
        assert manager.jobs[job_id].events[-1]["data"] == {
            "message": "Cancelled",
            "cleanup_completed": True,
            "hardware_lock_released": True,
        }

    asyncio.run(check_lifecycle())


def test_cleanup_failure_releases_lock_and_preserves_error_code():
    import asyncio

    from powers_tool_webui.jobs import JobManager, JobStatus

    async def check_lifecycle() -> None:
        manager = JobManager()
        job_id = await manager.submit_job(
            "ramp",
            {"resource": "USB0::FAKE::INSTR", "simulate": False, "dry_run": False},
            {"channel": 1},
        )
        assert await manager.start_job(job_id) is True
        assert await manager.cancel_job(job_id) is True

        await manager.fail_job(
            job_id,
            "workflow cancellation cleanup failed",
            code="cleanup_failed",
            result={"status": "failed", "original_reason": "user_cancelled"},
        )

        job = manager.jobs[job_id]
        assert job.status == JobStatus.FAILED
        assert job.error_code == "cleanup_failed"
        assert job.result["original_reason"] == "user_cancelled"
        assert manager.active_job_id is None
        assert job.events[-1]["data"]["hardware_lock_released"] is True

    asyncio.run(check_lifecycle())
