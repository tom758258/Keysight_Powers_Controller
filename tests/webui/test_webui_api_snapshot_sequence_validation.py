"""WebUI Snapshot, Restore, Sequence, and runtime-validation tests."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from _webui_api_helpers import policy_snapshot_document, wait_for_job

def test_api_sequence_webui_step_limit(client: TestClient, tmp_path):
    from powers_tool_webui.jobs import job_manager

    steps_250 = [{"action": "wait", "seconds": 0}] * 250
    payload = {
        "command": "sequence",
        "runtime": {"simulate": True, "dry_run": True},
        "parameters": {"document": {"version": 1, "steps": steps_250}},
    }

    accepted = client.post("/api/jobs", json=payload)
    assert accepted.status_code == 200

    jobs_before = len(job_manager.jobs)
    payload["parameters"]["document"]["steps"].append({"action": "wait", "seconds": 0})
    rejected = client.post("/api/jobs", json=payload)
    assert rejected.status_code == 400
    assert len(job_manager.jobs) == jobs_before

    sequence_file = tmp_path / "too-large.sequence.json"
    sequence_file.write_text(
        json.dumps({"version": 1, "steps": payload["parameters"]["document"]["steps"]}),
        encoding="utf-8",
    )
    payload["parameters"] = {"file": str(sequence_file)}
    rejected_file = client.post("/api/jobs", json=payload)
    assert rejected_file.status_code == 400
    assert len(job_manager.jobs) == jobs_before


def test_api_restore_from_snapshot_dry_run(client: TestClient):
    """Test restore preview dry-run produces the complete plan without taking the hardware lock."""

    snapshot_doc = {
        "schema_version": 2,
        "kind": "powers-tool-snapshot",
        "resource": "USB0::SIM::E36312A::INSTR",
        "reported_identity": {
            "manufacturer": "KEYSIGHT",
            "model": "E36312A",
            "serial": "MY12345678",
            "firmware": "3.0.0",
            "parse_ok": True
        },
        "resolved_identity": {
            "vendor_id": "keysight",
            "model_id": "keysight-e36312a",
            "model_name": "E36312A",
            "display_name": "Keysight E36312A",
        },
        "outputs": [
            {"channel": 1, "enabled": True},
            {"channel": 2, "enabled": False},
            {"channel": 3, "enabled": False}
        ],
        "readback": [
            {
                "channel": 1,
                "setpoints": {
                    "voltage": 5.0,
                    "current": 1.0
                }
            },
            {
                "channel": 2,
                "setpoints": {
                    "voltage": 3.3,
                    "current": 0.5
                }
            },
            {
                "channel": 3,
                "setpoints": {
                    "voltage": 12.0,
                    "current": 2.0
                }
            }
        ],
        "measurements": [],
        "protection": {
            "over_voltage_tripped": False,
            "over_current_tripped": False
        },
        "protection_settings": [
            {
                "channel": channel,
                "protection": {
                    "ovp_voltage": None,
                    "ocp_enabled": None,
                    "ocp_delay": None,
                    "ocp_delay_trigger": None,
                },
            }
            for channel in (1, 2, 3)
        ]
    }

    payload = {
        "command": "restore-from-snapshot",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": False,
            "dry_run": True,
            "confirm": True
        },
        "parameters": {
            "document": snapshot_doc,
            "channel": "all",
            "restore_output_state": True
        }
    }

    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    assert client.get("/api/health").json()["hardware_locked"] is False

    job_data = wait_for_job(client, job_id)
    assert job_data["status"] == "finished"
    assert "error" not in job_data or job_data["error"] is None

    result = job_data["result"]
    assert "plan" in result
    assert "OUTP ON,(@1)" in [step["command"] for step in result["plan"]["steps"]]
    assert client.get("/api/health").json()["hardware_locked"] is False
    assert result["restored_channels"] == [1, 2, 3]


def test_webui_job_reports_admitted_runtime(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from powers_tool_core.command_runner import run_core_command
    from powers_tool_core.core import OperationRequest, RuntimeOptions
    from powers_tool_webui import app as web_app

    snapshot = run_core_command(
        OperationRequest(
            "snapshot",
            RuntimeOptions(simulate=True, resource="USB0::SIM::E36312A::INSTR"),
        )
    )
    captured: dict[str, Any] = {}

    def fake_execute(job: Any) -> dict[str, object]:
        captured["runtime"] = job.admitted_request.runtime
        return {"status": "planned"}

    monkeypatch.setattr(web_app, "execute_job_command", fake_execute)
    response = client.post(
        "/api/jobs",
        json={
            "command": "restore-from-snapshot",
            "runtime": {
                "resource": "USB0::SIM::E36312A::INSTR",
                "simulate": True,
                "timeout_ms": 4321,
            },
            "parameters": {"document": snapshot, "channel": "all"},
        },
    )

    assert response.status_code == 200
    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
    assert job["runtime"]["planning_model_id"] == "keysight-e36312a"
    assert job["runtime"]["resource"] == "USB0::SIM::E36312A::INSTR"
    assert job["runtime"]["timeout_ms"] == 4321
    assert "support_policy_mode" not in job["runtime"]
    assert "validation_allow_pending_live_support" not in job["runtime"]
    runtime = captured["runtime"]
    assert runtime.planning_model_id == job["runtime"]["planning_model_id"]
    assert runtime.resource == job["runtime"]["resource"]
    assert runtime.timeout_ms == job["runtime"]["timeout_ms"]


@pytest.mark.parametrize("command", ["capabilities", "safety inspect"])
def test_webui_special_jobs_keep_validated_public_runtime(
    client: TestClient,
    command: str,
) -> None:
    response = client.post(
        "/api/jobs",
        json={"command": command, "runtime": {"dry_run": True}, "parameters": {}},
    )

    assert response.status_code == 200
    runtime = client.get(f"/api/jobs/{response.json()['job_id']}").json()["runtime"]
    assert set(runtime) == {
        "resource", "resource_alias", "safety_config", "simulate", "dry_run",
        "backend", "timeout_ms", "log_scpi", "confirm", "serial_options",
        "serial_remote", "serial_local_on_close", "planning_model_id",
        "expected_model_id", "planning_profile_id",
    }
    assert runtime["dry_run"] is True
    assert "support_policy_mode" not in runtime


def test_api_sequence_execution(client: TestClient):
    """Test sequence execution with valid steps and verify non-existent action rejection."""

    valid_sequence = {
        "version": 1,
        "steps": [
            {
                "action": "set",
                "channel": 1,
                "voltage": 2.5,
                "current": 0.5
            },
            {
                "action": "wait",
                "seconds": 0.1
            },
            {
                "action": "output-off",
                "channel": 1
            }
        ]
    }

    payload = {
        "command": "sequence",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
            "dry_run": True,
            "confirm": True
        },
        "parameters": {
            "document": valid_sequence
        }
    }

    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    job_data = wait_for_job(client, job_id)
    assert job_data["status"] == "finished"
    assert "plan" in job_data["result"]


def test_api_sequence_rejects_delay_action(client: TestClient):
    """Verify that sequence submission rejects unsupported 'delay' action on the API level."""
    invalid_sequence = {
        "version": 1,
        "steps": [
            {
                "action": "delay",
                "duration_ms": 100
            }
        ]
    }
    payload = {
        "command": "sequence",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
            "dry_run": True,
            "confirm": True
        },
        "parameters": {
            "document": invalid_sequence
        }
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 400
    assert "unsupported sequence step" in response.json()["detail"]


def test_api_restore_from_snapshot_rejects_missing_setpoints(client: TestClient):
    """Verify that restore rejects snapshot document missing required setpoints on the API level."""
    invalid_snapshot = {
        "schema_version": 2,
        "kind": "powers-tool-snapshot",
        "resource": "USB0::SIM::E36312A::INSTR",
        "reported_identity": {
            "manufacturer": "KEYSIGHT",
            "model": "E36312A",
            "serial": "MY12345678",
            "firmware": "3.0.0",
            "parse_ok": True,
        },
        "resolved_identity": {
            "vendor_id": "keysight",
            "model_id": "keysight-e36312a",
            "model_name": "E36312A",
            "display_name": "Keysight E36312A",
        },
        "outputs": [
            {"channel": 1, "enabled": True}
        ],
        "readback": [
            # ?? setpoints!
            {
                "channel": 1
            }
        ]
    }
    payload = {
        "command": "restore-from-snapshot",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "simulate": True,
            "dry_run": True,
            "confirm": True
        },
        "parameters": {
            "document": invalid_snapshot,
            "channel": "all"
        }
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 400
    assert "setpoints" in response.json()["detail"].lower()


@pytest.mark.parametrize("value", ["false", "true", 0, 1, 0.0, 1.0, None, [], {}])
def test_api_restore_rejects_malformed_restore_boolean_before_submission(
    client: TestClient,
    value: object,
) -> None:
    from powers_tool_webui.jobs import job_manager

    jobs_before = set(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "restore-from-snapshot",
            "runtime": {"dry_run": True},
            "parameters": {
                "document": policy_snapshot_document("E36312A"),
                "channel": 1,
                "restore_output_state": value,
            },
        },
    )

    assert response.status_code == 400
    assert "restore_output_state must be a boolean" in response.json()["detail"]
    assert set(job_manager.jobs) == jobs_before


def test_api_restore_rejects_malformed_snapshot_boolean_before_submission(
    client: TestClient,
) -> None:
    from powers_tool_webui.jobs import job_manager

    snapshot = policy_snapshot_document("E36312A")
    snapshot["outputs"][0]["enabled"] = "false"
    jobs_before = set(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "restore-from-snapshot",
            "runtime": {"dry_run": True},
            "parameters": {"document": snapshot, "channel": 1},
        },
    )

    assert response.status_code == 400
    assert "outputs[].enabled must be a boolean" in response.json()["detail"]
    assert set(job_manager.jobs) == jobs_before


@pytest.mark.parametrize("channel", [True, False, 1.0, 1.9, 0.0, "1", " 1 ", None, [], {}])
def test_api_rejects_coercible_channel_before_lock_or_submission(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    channel: object,
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
            "command": "set",
            "runtime": {"simulate": True},
            "parameters": {"channel": channel, "voltage": 1.0},
        },
    )

    assert response.status_code == 400
    assert "channel must be a positive integer" in response.json()["detail"]
    assert set(job_manager.jobs) == jobs_before


def test_api_restore_rejects_incomplete_protection_inventory_before_submission(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from powers_tool_webui.jobs import job_manager

    snapshot = policy_snapshot_document("E36312A")
    snapshot["protection_settings"] = snapshot["protection_settings"][1:]
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
            "command": "restore-from-snapshot",
            "runtime": {"dry_run": True},
            "parameters": {"document": snapshot, "channel": "all"},
        },
    )

    assert response.status_code == 400
    assert "snapshot protection_settings must not be empty" in response.json()["detail"]
    assert set(job_manager.jobs) == jobs_before


@pytest.mark.parametrize("value", ["false", "true", 1, 0, "", [], {}])
def test_api_rejects_non_boolean_confirmation_before_submission(
    client: TestClient,
    value: object,
) -> None:
    from powers_tool_webui.jobs import job_manager

    jobs_before = set(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "set",
            "runtime": {
                "resource": "USB0::FAKE::INSTR",
                "confirm": value,
            },
            "parameters": {"channel": 1, "voltage": 1.0},
        },
    )

    assert response.status_code == 400
    assert "runtime.confirm must be a boolean" in response.json()["detail"]
    assert set(job_manager.jobs) == jobs_before


def test_api_rejects_missing_planning_identity_before_submission(
    client: TestClient,
) -> None:
    from powers_tool_webui.jobs import job_manager

    jobs_before = set(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "set",
            "runtime": {"dry_run": True},
            "parameters": {"channel": 1, "voltage": 1.0},
        },
    )

    assert response.status_code == 400
    assert "require planning_model_id" in response.json()["detail"]
    assert set(job_manager.jobs) == jobs_before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("simulate", "true"),
        ("dry_run", 1),
        ("log_scpi", []),
        ("serial_remote", {}),
        ("serial_local_on_close", "false"),
        ("timeout_ms", True),
        ("resource", 123),
        ("serial_options", []),
    ],
)
def test_api_rejects_invalid_runtime_field_types_before_submission(
    client: TestClient,
    field: str,
    value: object,
) -> None:
    from powers_tool_webui.jobs import job_manager

    jobs_before = set(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "read-status",
            "runtime": {field: value},
            "parameters": {},
        },
    )

    assert response.status_code == 400
    assert set(job_manager.jobs) == jobs_before


def test_api_commands_accepts_complete_synthetic_future_vendor_metadata(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import powers_tool_webui.app as app_module
    from powers_tool_core.model_metadata import product_active_model_metadata

    metadata = product_active_model_metadata(set(app_module.COMMAND_METADATA))
    metadata["acme-x1"] = {
        "model_id": "acme-x1",
        "vendor_id": "acme",
        "vendor_display_name": "Acme",
        "model_name": "X1",
        "display_name": "Acme X1",
        "channels": [1],
        "output_control_scope": "per_channel",
        "command_support": {},
        "live_support": {"schema_version": 2, "model_id": "acme-x1", "commands": {}},
        "electrical_ratings": {"channels": []},
        "setpoint_ranges": {"channels": []},
    }
    monkeypatch.setattr(app_module, "product_active_model_metadata", lambda commands: metadata)

    payload = client.get("/api/commands").json()

    assert any(model["model_id"] == "acme-x1" for model in payload["physical_models"])
    for field in (
        "command_support_by_model_id",
        "live_support_by_model_id",
        "channel_capabilities_by_model_id",
        "electrical_ratings_by_model_id",
        "setpoint_ranges_by_model_id",
    ):
        assert "acme-x1" in payload[field]
