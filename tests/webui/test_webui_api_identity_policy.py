"""WebUI identity, exact-support, and model-policy tests."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from _webui_api_helpers import (
    FakeCoreSession,
    assert_direct_job_rejected,
    patch_core_opener,
    policy_snapshot_document,
    wait_for_job,
)

def test_webui_raw_live_expected_model_match_uses_idn_driver(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeCoreSession("Agilent Technologies,E3646A,0,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "set",
            "runtime": {
                "resource": "ASRL1::INSTR",
                "simulate": False,
                "dry_run": False,
                "confirm": True,
                "expected_model_id": "keysight-e3646a",
            },
            "parameters": {"channel": 1, "voltage": 1, "current": 0.05},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")
    assert job_data["result"]["idn"]["model"] == "E3646A"
    assert session.queries[0] == "*IDN?"
    assert "INST:NSEL 1" in session.writes
    assert "CURR 0.05" in session.writes
    assert "VOLT 1" in session.writes
    assert "CURR 0.05,(@1)" not in session.writes
    assert "VOLT 1,(@1)" not in session.writes


def test_webui_resource_capabilities_enforces_exact_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from powers_tool_webui import commands
    from powers_tool_webui.jobs import Job

    session = FakeCoreSession("KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(commands, "open_resource", lambda *args, **kwargs: session)

    result = commands.execute_job_command(
        Job(
            "capabilities-live",
            "capabilities",
            {
                "resource": "USB0::FAKE::INSTR",
                "simulate": False,
                "dry_run": False,
            },
            {},
        )
    )

    assert result["driver"]["class"] == "E36312APowerSupply"
    assert result["live_support"]["evaluated"] is True
    assert result["live_support"]["schema_version"] == 2
    assert result["live_support"]["model_id"] == "keysight-e36312a"
    assert "model" not in result["live_support"]
    assert result["live_support"]["transport_scope"] == "usb"
    assert result["live_support"]["backend_scope"] == "system_visa"
    assert result["live_support"]["policy_mode"] == "product"
    assert result["live_support"]["commands"]["set"]["product_open"] is True
    assert result["live_support"]["commands"]["output-on"]["product_open"] is True
    sequence_features = result["live_support"]["commands"]["sequence"]["features"]
    assert {feature["feature_kind"] for feature in sequence_features} == {
        "sequence_action"
    }
    assert all(feature["product_open"] for feature in sequence_features)
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


def test_webui_resource_capabilities_rejects_pending_backend_after_idn(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from powers_tool_webui import commands

    session = FakeCoreSession("KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(commands, "open_resource", lambda *args, **kwargs: session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "capabilities",
            "runtime": {
                "resource": "TCPIP0::192.0.2.1::INSTR",
                "backend": "@py",
                "simulate": False,
                "dry_run": False,
            },
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "transport_pending" in job_data["error"]
    assert "policy_mode=product" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


def test_webui_identify_returns_pending_exact_metadata_without_opening_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from powers_tool_webui import commands
    from powers_tool_webui.jobs import Job

    session = FakeCoreSession(
        "KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "*OPT?": "0",
            "SYST:VERS?": "1999.0",
            "SYST:COMM:RLST?": "RWLock",
        },
    )
    patch_core_opener(monkeypatch, session)

    result = commands.execute_job_command(
        Job(
            "identify-pending",
            "identify",
            {
                "resource": "TCPIP0::192.0.2.1::INSTR",
                "backend": "@py",
                "expected_model_id": "keysight-e36312a",
                "simulate": False,
                "dry_run": False,
            },
            {},
        )
    )

    live_support = result["live_support"]
    assert live_support["evaluated"] is True
    assert live_support["schema_version"] == 2
    assert live_support["model_id"] == "keysight-e36312a"
    assert "model" not in live_support
    assert live_support["transport_scope"] == "tcpip"
    assert live_support["backend_scope"] == "pyvisa_py"
    assert live_support["policy_mode"] == "product"
    assert live_support["commands"]["set"]["exact_scope_validation_status"] == "transport_pending"
    assert live_support["commands"]["set"]["product_open"] is False
    assert live_support["commands"]["identify"]["policy_exempt"] is True
    assert live_support["commands"]["identify"]["product_open"] is True
    assert live_support["commands"]["snapshot-diff"]["offline_only"] is True
    assert live_support["commands"]["snapshot-diff"]["product_open"] is False
    serialized = json.dumps(live_support)
    assert ".tmp_tests" not in serialized
    assert "SERIAL0000" not in serialized
    assert "192.0.2.1" not in serialized
    assert '"artifact"' not in serialized
    assert '"evidence"' not in serialized
    assert session.queries == ["*IDN?", "*OPT?", "SYST:VERS?", "SYST:COMM:RLST?"]
    assert session.writes == []
    assert session.closed is True


@pytest.mark.parametrize("command", ["identify", "verify"])
@pytest.mark.parametrize("manufacturer", ["OTHER_VENDOR", "Agilent Technologies"])
def test_webui_diagnostic_wrong_vendor_known_model_has_no_exact_support(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    manufacturer: str,
) -> None:
    session = FakeCoreSession(
        f"{manufacturer},E36312A,SERIAL0000,1.0",
        query_responses={
            "*OPT?": "0",
            "SYST:VERS?": "1999.0",
            "SYST:COMM:RLST?": "RWLock",
        },
    )
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": command,
            "runtime": {"resource": "USB0::FAKE::INSTR"},
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")
    result = job_data["result"]
    detected_idn = result["idn"] if command == "identify" else result["resource"]["idn"]
    assert detected_idn["manufacturer"] == manufacturer
    assert detected_idn["model"] == "E36312A"
    assert result["live_support"]["evaluated"] is False
    assert result["live_support"]["commands"] == {}
    assert "manufacturer and model" in result["live_support"]["reason"]
    assert session.writes == []


@pytest.mark.parametrize("command", ["identify", "verify"])
def test_webui_diagnostic_narrow_e3646a_alias_has_exact_support(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    session = FakeCoreSession(
        "Agilent Technologies,E3646A,SERIAL0000,1.0",
        query_responses={
            "*OPT?": "0",
            "SYST:VERS?": "1999.0",
            "SYST:COMM:RLST?": "RWLock",
        },
    )
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": command,
            "runtime": {"resource": "ASRL1::INSTR"},
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")
    live_support = job_data["result"]["live_support"]
    assert live_support["evaluated"] is True
    assert live_support["schema_version"] == 2
    assert live_support["model_id"] == "keysight-e3646a"
    assert "model" not in live_support
    assert live_support["transport_scope"] == "asrl"
    assert live_support["backend_scope"] == "system_visa"
    assert live_support["commands"][command]["product_open"] is True
    assert session.writes == []


def test_webui_diagnostic_expected_model_cannot_override_wrong_vendor(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeCoreSession(
        "OTHER_VENDOR,E36312A,SERIAL0000,1.0",
        query_responses={
            "*OPT?": "0",
            "SYST:VERS?": "1999.0",
            "SYST:COMM:RLST?": "RWLock",
        },
    )
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "identify",
            "runtime": {
                "resource": "USB0::FAKE::INSTR",
                "expected_model_id": "keysight-e36312a",
            },
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "resolved to unknown" in job_data["error"]
    assert session.writes == []


@pytest.mark.parametrize("command", ["identify", "verify"])
def test_webui_diagnostic_wrong_vendor_different_model_preserves_expected_guard(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    session = FakeCoreSession("OTHER_VENDOR,E36312A,SERIAL0000,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": command,
            "runtime": {
                "resource": "USB0::FAKE::INSTR",
                "expected_model_id": "keysight-e3646a",
            },
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "Expected model_id keysight-e3646a" in job_data["error"]
    assert "resolved to unknown" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


@pytest.mark.parametrize("command", ["identify", "verify"])
@pytest.mark.parametrize("model", ["UNKNOWN_MODEL", "E36103B"])
def test_webui_diagnostic_unknown_or_descoped_model_returns_neutral_live_support(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    model: str,
) -> None:
    session = FakeCoreSession(
        f"KEYSIGHT,{model},SERIAL0000,1.0",
        query_responses={
            "*OPT?": "0",
            "SYST:VERS?": "1999.0",
            "SYST:COMM:RLST?": "RWLock",
        },
    )
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": command,
            "runtime": {
                "resource": "USB0::FAKE::INSTR",
                "simulate": False,
                "dry_run": False,
            },
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")
    result = job_data["result"]
    detected_idn = result["idn"] if command == "identify" else result["resource"]["idn"]
    assert detected_idn["model"] == model
    assert result["live_support"] == {
        "schema_version": 2,
        "evaluated": False,
        "model_id": None,
        "reported_manufacturer": "KEYSIGHT",
        "reported_model": model,
        "transport_scope": "usb",
        "backend_scope": "system_visa",
        "policy_mode": "product",
        "commands": {},
        "reason": (
            "The reported manufacturer and model do not resolve to active "
            "exact live-support metadata."
        ),
    }
    serialized = json.dumps(result["live_support"])
    assert "SERIAL0000" not in serialized
    assert "USB0::FAKE::INSTR" not in serialized
    assert '"evidence"' not in serialized
    assert '"artifact"' not in serialized
    expected_queries = (
        ["*IDN?", "*OPT?", "SYST:VERS?", "SYST:COMM:RLST?"]
        if command == "identify"
        else ["*IDN?"]
    )
    assert session.queries == expected_queries
    assert session.writes == []
    assert session.closed is True


@pytest.mark.parametrize("command", ["identify", "verify"])
def test_webui_diagnostic_expected_model_mismatch_remains_a_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    session = FakeCoreSession("Agilent Technologies,E3646A,0,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": command,
            "runtime": {
                "resource": "USB0::FAKE::INSTR",
                "expected_model_id": "keysight-e36312a",
            },
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "Expected model_id keysight-e36312a" in job_data["error"]
    assert "keysight-e3646a" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


def test_webui_unknown_model_normal_live_command_remains_rejected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeCoreSession("KEYSIGHT,UNKNOWN_MODEL,SERIAL0000,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "read-status",
            "runtime": {"resource": "USB0::FAKE::INSTR"},
            "parameters": {"channel": 1},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "unknown live support-policy model_id for reported model 'UNKNOWN_MODEL'" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


def test_webui_pending_command_remains_product_rejected_after_identify_metadata(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeCoreSession("KEYSIGHT,E36312A,SERIAL0000,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "set",
            "runtime": {
                "resource": "TCPIP0::192.0.2.1::INSTR",
                "backend": "@py",
                "expected_model_id": "keysight-e36312a",
                "confirm": True,
            },
            "parameters": {"channel": 1, "voltage": 1.0, "current": 0.05},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "transport_pending" in job_data["error"]
    assert "policy_mode=product" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


def test_webui_identify_expected_model_mismatch_precedes_extended_identity_queries(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeCoreSession("Agilent Technologies,E3646A,0,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "identify",
            "runtime": {
                "resource": "TCPIP0::192.0.2.1::INSTR",
                "backend": "@py",
                "expected_model_id": "keysight-e36312a",
            },
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "Expected model_id keysight-e36312a" in job_data["error"]
    assert "keysight-e3646a" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


def test_webui_simulated_identify_does_not_claim_evaluated_live_support(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/jobs",
        json={
            "command": "identify",
            "runtime": {
                "resource": "USB0::SIM::E36312A::INSTR",
                "simulate": True,
            },
            "parameters": {},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")
    assert job_data["result"]["live_support"]["evaluated"] is False
    assert job_data["result"]["live_support"]["commands"] == {}
    assert "real hardware only" in job_data["result"]["live_support"]["reason"]


@pytest.mark.parametrize(
    "field",
    ["support_policy_mode", "validation_allow_pending_live_support", "validation-allow-pending-live-support"],
)
def test_webui_rejects_forged_validation_mode_fields(client: TestClient, field: str) -> None:
    response = client.post(
        "/api/jobs",
        json={
            "command": "measure",
            "runtime": {"resource": "TCPIP0::192.0.2.1::INSTR", field: "validation"},
            "parameters": {"channel": 1},
        },
    )
    assert response.status_code == 400
    assert "validation support policy fields are not allowed" in response.json()["detail"]


def test_webui_runtime_options_are_always_product_mode() -> None:
    from powers_tool_webui.commands import build_runtime_options

    runtime = build_runtime_options(
        {"resource": "TCPIP0::192.0.2.1::INSTR", "support_policy_mode": "validation"}
    )
    assert runtime.support_policy_mode == "product"


def test_webui_raw_live_expected_model_mismatch_fails_before_output_writes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeCoreSession("Agilent Technologies,E3646A,0,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "set",
            "runtime": {
                "resource": "USB0::FAKE::INSTR",
                "simulate": False,
                "dry_run": False,
                "confirm": True,
                "expected_model_id": "keysight-e36312a",
            },
            "parameters": {"channel": 1, "voltage": 1, "current": 0.05},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert "Expected model_id keysight-e36312a" in job_data["error"]
    assert "resolved to keysight-e3646a" in job_data["error"]
    assert "does not override" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []


@pytest.mark.parametrize("model", ["E36103B", "E36232A"])
def test_webui_live_job_blocks_descoped_idn_before_generic_fallback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    session = FakeCoreSession(f"KEYSIGHT,{model},SERIAL0000,1.0")
    patch_core_opener(monkeypatch, session)

    response = client.post(
        "/api/jobs",
        json={
            "command": "read-status",
            "runtime": {
                "resource": "USB0::FAKE::INSTR",
                "simulate": False,
                "dry_run": False,
            },
            "parameters": {"channel": 1},
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed"
    assert model in job_data["error"]
    assert "de-scoped and not currently supported" in job_data["error"]
    assert "Generic fallback is blocked" in job_data["error"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []


def test_webui_raw_no_hardware_model_profile_behavior_is_unchanged(client: TestClient) -> None:
    explicit = client.post(
        "/api/jobs",
        json={
            "command": "output-on",
            "runtime": {
                "resource": "USB0::FAKE::E3646A::INSTR",
                "dry_run": True,
                "simulate": False,
                "planning_model_id": "keysight-e3646a",
            },
            "parameters": {"channel": "all"},
        },
    )
    assert explicit.status_code == 200
    explicit_job = wait_for_job(client, explicit.json()["job_id"])
    assert explicit_job["status"] == "finished", explicit_job.get("error")
    assert explicit_job["result"]["target"]["planning_model_id"] == "keysight-e3646a"
    assert [step["parameters"]["channel"] for step in explicit_job["result"]["steps"]] == [1, 2]

    inferred = client.post(
        "/api/jobs",
        json={
            "command": "output-on",
            "runtime": {
                "resource": "ASRL1::SIM::E3646A::INSTR",
                "dry_run": True,
                "simulate": False,
            },
            "parameters": {"channel": "all"},
        },
    )
    assert inferred.status_code == 200
    inferred_job = wait_for_job(client, inferred.json()["job_id"])
    assert inferred_job["status"] == "finished", inferred_job.get("error")
    assert inferred_job["result"]["target"]["planning_model_id"] == "keysight-e3646a"

    missing = client.post(
        "/api/jobs",
        json={
            "command": "output-on",
            "runtime": {
                "resource": "USB0::FAKE::E3646A::INSTR",
                "dry_run": True,
                "simulate": False,
            },
            "parameters": {"channel": 1},
        },
    )
    assert missing.status_code == 400
    assert "require planning_model_id" in missing.json()["detail"]

    missing_simulate = client.post(
        "/api/jobs",
        json={
            "command": "output-on",
            "runtime": {
                "simulate": True,
            },
            "parameters": {"channel": 1},
        },
    )
    assert missing_simulate.status_code == 400
    assert "require planning_model_id" in missing_simulate.json()["detail"]


@pytest.mark.parametrize("model", ["keysight-e36103b", "keysight-e36232a"])
@pytest.mark.parametrize("runtime_mode", ["dry_run", "simulate", "live"])
def test_webui_direct_jobs_reject_descoped_model_profiles(
    client: TestClient,
    model: str,
    runtime_mode: str,
) -> None:
    runtime: dict[str, Any] = {}
    if runtime_mode == "dry_run":
        runtime["dry_run"] = True
        runtime["planning_model_id"] = model
    elif runtime_mode == "simulate":
        runtime["simulate"] = True
        runtime["planning_model_id"] = model
    else:
        runtime["resource"] = "USB0::FAKE::INSTR"
        runtime["confirm"] = True
        runtime["expected_model_id"] = model

    response = client.post(
        "/api/jobs",
        json={
            "command": "set",
            "runtime": runtime,
            "parameters": {"channel": 1, "voltage": 1, "current": 0.05},
        },
    )

    assert response.status_code == 400
    assert "not active or candidate" in response.json()["detail"]
    assert model in response.json()["detail"]


@pytest.mark.parametrize(
    ("payload", "fragments"),
    [
        (
            {
                "command": "trigger-step",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-edu36311a"},
                "parameters": {"channel": 1, "source": "bus", "fire": True},
            },
            ("E36312A",),
        ),
        (
            {
                "command": "trigger-list",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-edu36311a"},
                "parameters": {
                    "channel": 1,
                    "source": "bus",
                    "fire": True,
                    "wait_complete": True,
                    "voltage_list": [0.0, 1.0],
                    "current_list": [0.05, 0.05],
                    "dwell_list": [0.01, 0.01],
                },
            },
            ("E36312A",),
        ),
        (
            {
                "command": "snapshot",
                "runtime": {"simulate": True, "resource": "USB0::SIM::EDU36311A::INSTR"},
                "parameters": {},
            },
            ("E36312A",),
        ),
        (
            {
                "command": "restore-from-snapshot",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-edu36311a"},
                "parameters": {"document": policy_snapshot_document("EDU36311A"), "channel": 1},
            },
            ("E36312A",),
        ),
    ],
)
def test_webui_direct_jobs_reject_edu36311a_disabled_workflows(
    client: TestClient,
    payload: dict[str, Any],
    fragments: tuple[str, ...],
) -> None:
    assert_direct_job_rejected(client, payload, *fragments)


@pytest.mark.parametrize(
    ("payload", "fragments"),
    [
        (
            {
                "command": "protection-set",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
                "parameters": {"channel": 1, "ovp_voltage": 5.0},
            },
            ("not",),
        ),
        (
            {
                "command": "clear-protection",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
                "parameters": {"channel": 1},
            },
            ("E3646A", "protection workflows are disabled"),
        ),
        (
            {
                "command": "trigger-pulse",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
                "parameters": {"channel": 1, "pins": [1], "polarity": "positive"},
            },
            ("E3646A", "completion-pulse workflows are disabled"),
        ),
        (
            {
                "command": "trigger-step",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
                "parameters": {"channel": 1, "source": "bus", "fire": True},
            },
            ("E3646A", "native LIST and trigger workflows are disabled"),
        ),
        (
            {
                "command": "trigger-list",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
                "parameters": {
                    "channel": 1,
                    "source": "bus",
                    "fire": True,
                    "wait_complete": True,
                    "voltage_list": [0.0, 1.0],
                    "current_list": [0.05, 0.05],
                    "dwell_list": [0.01, 0.01],
                },
            },
            ("E3646A", "software workflows, not native LIST"),
        ),
        (
            {
                "command": "snapshot",
                "runtime": {"simulate": True, "resource": "ASRL1::SIM::E3646A::INSTR"},
                "parameters": {},
            },
            ("E3646A", "snapshot/restore workflows are disabled"),
        ),
        (
            {
                "command": "restore-from-snapshot",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
                "parameters": {"document": policy_snapshot_document("E3646A"), "channel": 1},
            },
            ("E36312A",),
        ),
        (
            {
                "command": "sequence",
                "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
                "parameters": {"document": {"version": 1, "steps": [{"action": "trigger-pulse", "channel": 1, "pins": [1]}]}},
            },
            ("E36312A",),
        ),
    ],
)
def test_webui_direct_jobs_reject_e3646a_disabled_workflows(
    client: TestClient,
    payload: dict[str, Any],
    fragments: tuple[str, ...],
) -> None:
    assert_direct_job_rejected(client, payload, *fragments)


@pytest.mark.parametrize(
    "runtime",
    [
        {"dry_run": True, "planning_model_id": "keysight-edu36311a"},
        {"dry_run": True, "planning_model_id": "keysight-e3646a"},
        {"simulate": True, "resource": "USB0::SIM::EDU36311A::INSTR"},
        {"simulate": True, "resource": "ASRL1::SIM::E3646A::INSTR"},
    ],
)
def test_webui_direct_general_completion_pulse_uses_core_model_gate(
    client: TestClient,
    runtime: dict[str, Any],
) -> None:
    assert_direct_job_rejected(
        client,
        {
            "command": "apply",
            "runtime": runtime,
            "parameters": {
                "channel": 1,
                "voltage": 1.0,
                "current": 0.05,
                "completion_pulse_pins": [1],
            },
        },
        "require planning_model_id 'keysight-e36312a'",
    )


def test_webui_direct_general_completion_pulse_e36312a_stays_supported(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/jobs",
        json={
            "command": "apply",
            "runtime": {
                "dry_run": True,
                "planning_model_id": "keysight-e36312a",
            },
            "parameters": {
                "channel": 1,
                "voltage": 1.0,
                "current": 0.05,
                "completion_pulse_pins": [1],
            },
        },
    )

    assert response.status_code == 200


def test_webui_direct_jobs_reject_edu36311a_sequence_trigger_pulse(client: TestClient) -> None:
    assert_direct_job_rejected(
        client,
        {
            "command": "sequence",
            "runtime": {"dry_run": True, "planning_model_id": "keysight-edu36311a"},
            "parameters": {
                "document": {
                    "version": 1,
                    "steps": [{"action": "trigger-pulse", "channel": 1, "pins": [1]}],
                }
            },
        },
        "keysight-edu36311a",
        "E36312A",
    )


@pytest.mark.parametrize(
    "action",
    [
        "protection-set",
        "clear-protection",
        "trigger-pulse",
        "trigger-list",
        "snapshot",
        "restore-from-snapshot",
        "native-list",
        "completion-pulse",
    ],
)
def test_webui_direct_jobs_reject_e3646a_unsupported_sequence_steps(
    client: TestClient,
    action: str,
) -> None:
    assert_direct_job_rejected(
        client,
        {
            "command": "sequence",
            "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
            "parameters": {
                "document": {
                    "version": 1,
                    "steps": [{"action": action, "channel": 1, "pins": [1]}],
                }
            },
        },
        "unsupported" if action != "trigger-pulse" else "E36312A",
    )


def test_webui_direct_e3646a_sequence_validated_read_only_and_output_steps_allowed(client: TestClient) -> None:
    response = client.post(
        "/api/jobs",
        json={
            "command": "sequence",
            "runtime": {"dry_run": True, "planning_model_id": "keysight-e3646a"},
            "parameters": {
                "document": {
                    "version": 1,
                    "steps": [
                        {"action": "readback", "channel": 1},
                        {"action": "set", "channel": 2, "voltage": 1.0, "current": 0.05},
                        {"action": "output-off", "channel": 2},
                    ],
                }
            },
        },
    )

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")
    assert job_data["result"]["plan"]["target"]["planning_model_id"] == "keysight-e3646a"

