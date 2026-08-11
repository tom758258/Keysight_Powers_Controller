"""WebUI HTTP, metadata, and basic job-submission contract tests."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from _webui_api_helpers import wait_for_job
from _webui_shared import (
    WEBUI_COMMAND_NAMES,
    WEBUI_HIDDEN_DIAGNOSTIC_COMMANDS,
    WEBUI_HIDDEN_LIVE_DATA_COMMANDS,
    WEBUI_HIDDEN_UNSUPPORTED_COMMANDS,
    read_static_javascript,
    read_static_texts,
    run_webui_module_assertions,
    simulated_e36312a_runtime,
)

def test_api_jobs_rejects_unknown_top_level_field_with_400(client: TestClient) -> None:
    response = client.post(
        "/api/jobs",
        json={
            "command": "set",
            "runtime": {"dry_run": True, "planning_model_id": "keysight-e36312a"},
            "parameters": {"channel": 1, "voltage": 1.0},
            "unexpected": True,
        },
    )

    assert response.status_code == 400
    assert "unknown top-level field" in response.json()["detail"]
def test_index_uses_cache_busted_assets_and_no_store(client: TestClient):
    from powers_tool_webui import __version__

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert '/static/styles.css?v=' in response.text
    assert '/static/app.js?v=' in response.text
    assert 'data-i18n="app.unofficial_tool"' in response.text
    assert f"v{__version__}" in response.text
    assert "__WEBUI_VERSION__" not in response.text
    javascript_urls = re.findall(r'<script type="module" src="([^"]+)"', response.text)
    assert javascript_urls == [
        re.search(r'(/static/app\.js\?v=[^"]+)', response.text).group(1),
    ]
    assert all(re.search(r"\?v=[^&\"]+", asset_url) for asset_url in javascript_urls)
    for asset_url in javascript_urls:
        asset_response = client.get(asset_url)
        assert asset_response.status_code == 200
        assert asset_response.headers["Cache-Control"] == "no-store"


def test_static_assets_accept_query_string_and_no_store(client: TestClient):
    for asset_path, expected_text in (
        ("/static/execution-context.js?v=test", "export function buildWorkspaceResultKey"),
        ("/static/electrical.js?v=test", "export function resolveInputElectricalConstraint"),
        ("/static/api.js?v=test", "export async function fetchJson"),
        ("/static/i18n.js?v=test", "export function createI18n"),
        ("/static/dom_i18n.js?v=test", "export function applyStaticTranslations"),
        ("/static/locale_en.js?v=test", "export const EN_MESSAGES"),
        ("/static/locale_zh_tw.js?v=test", "export const ZH_TW_MESSAGES"),
        ("/static/locale_ui.js?v=test", "export function initializeLocaleUi"),
        ("/static/state.js?v=test", "export function createInitialState"),
        ("/static/device-resource.js?v=test", "export function physicalModelDisplayName"),
        ("/static/command-form.js?v=test", "export function setOutputParams"),
        ("/static/results.js?v=test", "export function jobSummary"),
        ("/static/results.js?v=test", "export function renderWorkspaceJob"),
        ("/static/jobs.js?v=test", "export function addHistory"),
        ("/static/live-data.js?v=test", "export function mergeLiveChannels"),
        ("/static/ramp-list.js?v=test", "export function validateRampListDocument"),
        ("/static/trigger-list.js?v=test", "export function validateTriggerListWorkspace"),
        ("/static/sequence.js?v=test", "export function normalizeSequenceDocument"),
        ("/static/snapshot-restore.js?v=test", "export function validateSnapshotDocument"),
        ("/static/snapshot-restore.js?v=test", "export function validateRestoreSnapshot"),
        ("/static/jobs.js?v=test", "export function openJobEvents"),
    ("/static/basic-controls.js?v=test", "export function createBasicControls"),
    ("/static/command-support.js?v=test", "export function createCommandSupport"),
    ("/static/workflows.js?v=test", "export function createWorkflows"),
        ("/static/app.js?v=test", 'from "./execution-context.js"'),
    ):
        response = client.get(asset_path)

        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert expected_text in response.text


def test_frontend_api_module_preserves_json_request_and_error_contract() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    api_js = read_static_javascript("api.js")

    assert 'from "./api.js"' in app_js
    assert "document" not in api_js
    assert "EventSource" not in api_js

    run_webui_module_assertions(
        r"""
const calls = [];
globalThis.fetch = async (url, options) => {
  calls.push({ url, options });
  return { ok: true, json: async () => ({ accepted: true }) };
};
const payload = await globalThis.webuiApi.fetchJson("/api/jobs", { method: "POST", body: "{}" });
strictAssert.deepEqual(payload, { accepted: true });
strictAssert.deepEqual(calls, [{
  url: "/api/jobs",
  options: { headers: { "Content-Type": "application/json" }, method: "POST", body: "{}" }
}]);
globalThis.fetch = async () => ({ ok: false, json: async () => ({ detail: "blocked" }) });
await strictAssert.rejects(
  globalThis.webuiApi.fetchJson("/api/jobs"),
  /blocked/
);
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("api.js",),
    )


def test_health_check(client: TestClient):
    from powers_tool_webui import __version__

    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["package"] == "powers-tool-webui"
    assert data["version"] == __version__


def test_commands_metadata(client: TestClient):
    from powers_tool_core.model_metadata import planning_profile_metadata

    response = client.get("/api/commands")
    assert response.status_code == 200
    data = response.json()
    assert "commands" in data
    assert "command_support_by_model_id" in data
    assert "live_support_by_model_id" in data
    assert data["planning_profiles"] == planning_profile_metadata(set(data["commands"]))
    channel_capabilities = data["channel_capabilities_by_model_id"]
    assert channel_capabilities["keysight-e36312a"]["channels"] == [1, 2, 3]
    assert channel_capabilities["keysight-e36312a"]["output_control_scope"] == "per_channel"
    assert channel_capabilities["keysight-edu36311a"]["channels"] == [1, 2, 3]
    assert channel_capabilities["keysight-edu36311a"]["output_control_scope"] == "per_channel"
    assert channel_capabilities["keysight-e3646a"]["channels"] == [1, 2]
    assert channel_capabilities["keysight-e3646a"]["output_control_scope"] == "global"
    assert channel_capabilities["gw-instek-psm-2010"]["channels"] == [1]
    assert channel_capabilities["gw-instek-psm-2010"]["output_control_scope"] == "global"
    assert "generic-scpi" not in channel_capabilities
    assert data["planning_profiles"]["generic-scpi"]["channels"] == [1]
    assert data["electrical_ratings_by_model_id"]["keysight-e36312a"]["channels"][0] == {
        "channel": 1,
        "max_voltage": 6.0,
        "max_current": 5.0,
    }
    setpoint_ranges = data["setpoint_ranges_by_model_id"]
    assert set(setpoint_ranges) == {
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e3646a",
        "gw-instek-psm-2010",
    }
    e3646a_ch1_ranges = setpoint_ranges["keysight-e3646a"]["channels"][0]["ranges"]
    assert e3646a_ch1_ranges[0]["name"] == "LOW"
    assert e3646a_ch1_ranges[0]["voltage_max"] == 8.24
    assert e3646a_ch1_ranges[0]["current_max"] == 3.09
    assert e3646a_ch1_ranges[1]["name"] == "HIGH"
    assert e3646a_ch1_ranges[1]["voltage_max"] == 20.6
    assert e3646a_ch1_ranges[1]["current_max"] == 1.545
    assert data["parameter_constraints"]["delay_ms"]["min"] == 0
    assert data["parameter_constraints"]["poll_ms"]["min"] == 50

    # Check a few expected commands
    cmds = data["commands"]
    assert "set" in cmds
    assert cmds["set"]["requires_confirm"] is True
    assert not (WEBUI_HIDDEN_LIVE_DATA_COMMANDS & set(cmds))
    assert "list-resources" not in cmds
    expected_categories = {
        "output": {"set", "apply", "output-on", "output-off", "safe-off"},
        "workflow": {"cycle-output", "ramp", "ramp-list", "sequence", "smoke-output"},
        "protection": {"protection-set", "clear-protection"},
        "trigger": {"trigger-pulse", "trigger-status", "trigger-step", "trigger-list", "trigger-fire", "trigger-abort"},
        "artifact": {"snapshot", "restore-from-snapshot"},
        "discovery": {"clear", "error", "capabilities", "identify"},
    }
    actual_categories = {
        category: {name for name, metadata in cmds.items() if metadata["category"] == category}
        for category in expected_categories
    }
    assert actual_categories == expected_categories
    assert set(cmds) == set().union(*expected_categories.values())
    assert cmds["smoke-output"]["category"] == "workflow"
    for command in (
        "smoke-output",
        "safe-off",
        "identify",
        "error",
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    ):
        assert isinstance(cmds[command]["description"], str)
        assert cmds[command]["description"].strip()
    assert cmds["identify"]["category"] == "discovery"
    assert not (WEBUI_HIDDEN_DIAGNOSTIC_COMMANDS & set(cmds))
    assert cmds["clear-protection"]["category"] == "protection"
    assert cmds["clear-protection"]["requires_confirm"] is True
    clear_description = cmds["clear"]["description"]
    assert "OVP" in clear_description
    assert "OCP" in clear_description
    assert "does not clear" in clear_description.lower()
    assert "latch" in clear_description.lower()
    assert cmds["sequence"]["max_steps"] == 250

    # Check output-affecting commands are marked correctly
    assert cmds["output-on"]["requires_confirm"] is True
    assert cmds["output-off"]["requires_confirm"] is True
    assert cmds["smoke-output"]["requires_confirm"] is True
    assert "smoke-output" in data["output_affecting_commands"]
    assert "ramp-list" in data["output_affecting_commands"]


def test_api_rejects_invalid_static_parameter_before_creating_job(client: TestClient):
    from powers_tool_webui.jobs import job_manager

    jobs_before = len(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "set",
            "runtime": {"simulate": True},
            "parameters": {"channel": 1, "voltage": -1, "current": 0.1},
        },
    )

    assert response.status_code == 400
    assert "voltage" in response.json()["detail"]
    assert len(job_manager.jobs) == jobs_before


@pytest.mark.parametrize("pulse_channel", [True, 1.5, "2", None, 0, -1, 4])
def test_api_rejects_invalid_completion_pulse_channel_before_creating_job(
    client: TestClient,
    pulse_channel: object,
) -> None:
    from powers_tool_webui.jobs import job_manager

    jobs_before = len(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "ramp",
            "runtime": {"simulate": True, "resource": "USB0::SIM::E36312A::INSTR"},
            "parameters": {
                "channel": 1,
                "start_voltage": 0,
                "stop_voltage": 1,
                "step_voltage": 1,
                "current": 0.1,
                "completion_pulse_pins": [1],
                "completion_pulse_channel": pulse_channel,
            },
        },
    )

    assert response.status_code == 400
    assert "completion_pulse_channel must be an integer from 1 to 3" in response.json()["detail"]
    assert len(job_manager.jobs) == jobs_before


def test_api_rejects_completion_pulse_channel_without_pins_before_creating_job(client: TestClient) -> None:
    from powers_tool_webui.jobs import job_manager

    jobs_before = len(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "ramp",
            "runtime": {"simulate": True, "resource": "USB0::SIM::E36312A::INSTR"},
            "parameters": {
                "channel": 1,
                "start_voltage": 0,
                "stop_voltage": 1,
                "step_voltage": 1,
                "current": 0.1,
                "completion_pulse_channel": 2,
            },
        },
    )

    assert response.status_code == 400
    assert "completion_pulse_channel requires completion_pulse_pins" in response.json()["detail"]
    assert len(job_manager.jobs) == jobs_before


@pytest.mark.parametrize("pulse_channel", [1, 3])
def test_api_accepts_valid_completion_pulse_channel(client: TestClient, pulse_channel: int) -> None:
    response = client.post(
        "/api/jobs",
        json={
            "command": "ramp",
            "runtime": {"simulate": True, "resource": "USB0::SIM::E36312A::INSTR"},
            "parameters": {
                "channel": 1,
                "start_voltage": 0,
                "stop_voltage": 1,
                "step_voltage": 1,
                "current": 0.1,
                "completion_pulse_pins": [1],
                "completion_pulse_channel": pulse_channel,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.parametrize("field", ["model_profile", "model"])
def test_api_rejects_legacy_runtime_identity_before_creating_job(
    client: TestClient,
    field: str,
):
    from powers_tool_webui.jobs import job_manager

    jobs_before = len(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "measure",
            "runtime": {"simulate": True, field: "E36312A"},
            "parameters": {"channel": 1},
        },
    )

    assert response.status_code == 400
    assert "legacy runtime identity fields are not allowed" in response.json()["detail"]
    assert len(job_manager.jobs) == jobs_before


def test_api_rejects_arm_only_trigger_list_before_creating_job(client: TestClient):
    from powers_tool_webui.jobs import job_manager

    jobs_before = len(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "trigger-list",
            "runtime": {"simulate": True},
            "parameters": {"channel": 1, "source": "bus"},
        },
    )

    assert response.status_code == 400
    assert "leave_trigger_configured=true" in response.json()["detail"]
    assert len(job_manager.jobs) == jobs_before


@pytest.mark.parametrize(
    ("command", "parameters", "message"),
    [
        ("trigger-step", {"source": "immediate", "fire": True}, "does not accept fire=true"),
        ("trigger-list", {"source": "immediate", "fire": True}, "does not accept fire=true"),
        ("trigger-step", {"source": "bus", "wait_complete": True}, "requires fire=true"),
        ("trigger-list", {"source": "bus", "wait_complete": True}, "requires fire=true"),
        ("trigger-list", {"source": "immediate"}, "started without wait_complete=true"),
        ("trigger-list", {"source": "bus", "fire": True}, "started without wait_complete=true"),
    ],
)
def test_api_rejects_invalid_trigger_control_before_creating_job(
    client: TestClient,
    command: str,
    parameters: dict[str, object],
    message: str,
):
    from powers_tool_webui.jobs import job_manager

    jobs_before = len(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": command,
            "runtime": {"simulate": True},
            "parameters": {"channel": 1, **parameters},
        },
    )

    assert response.status_code == 400
    assert message in response.json()["detail"]
    assert len(job_manager.jobs) == jobs_before


def test_api_rejects_trigger_fire_wait_without_abort_target_before_creating_job(client: TestClient):
    from powers_tool_webui.jobs import job_manager

    jobs_before = len(job_manager.jobs)
    response = client.post(
        "/api/jobs",
        json={
            "command": "trigger-fire",
            "runtime": {"simulate": True},
            "parameters": {"wait_complete": True},
        },
    )

    assert response.status_code == 400
    assert "abort target" in response.json()["detail"]
    assert len(job_manager.jobs) == jobs_before


def test_commands_metadata_includes_model_aware_support(client: TestClient):
    response = client.get("/api/commands")
    assert response.status_code == 200
    data = response.json()
    support = data["command_support_by_model_id"]

    assert set(support) == {
        "keysight-e36312a",
        "keysight-e3646a",
        "keysight-edu36311a",
        "gw-instek-psm-2010",
    }
    assert support["keysight-e36312a"]["trigger-list"]["real"] is True
    assert support["keysight-edu36311a"]["trigger-list"]["real"] is False
    assert support["keysight-edu36311a"]["trigger-list"]["hardware_validation"] == "not_supported_by_model"
    assert "trigger/native LIST workflows are disabled in live, simulate, and dry-run" in support["keysight-edu36311a"]["trigger-list"]["disabled_reason"]
    assert "E36312A-only" in support["keysight-edu36311a"]["snapshot"]["disabled_reason"]
    assert support["keysight-e3646a"]["identify"]["real"] is True
    assert support["keysight-e3646a"]["set"]["real"] is True
    assert support["keysight-e3646a"]["set"]["hardware_validation"] == "validated"
    assert "protection workflows are disabled until separately validated" in support["keysight-e3646a"]["protection-set"]["disabled_reason"]
    assert "software workflows, not native LIST" in support["keysight-e3646a"]["trigger-list"]["disabled_reason"]
    assert "snapshot/restore workflows are disabled until separately validated" in support["keysight-e3646a"]["restore-from-snapshot"]["disabled_reason"]
    assert "completion-pulse workflows are disabled" in support["keysight-e3646a"]["trigger-pulse"]["disabled_reason"]
    assert "disabled_reason" not in support["keysight-e3646a"]["ramp-list"]
    assert "disabled_reason" not in support["keysight-e3646a"]["sequence"]
    assert support["gw-instek-psm-2010"]["set"]["real"] is False
    assert support["gw-instek-psm-2010"]["output-on"]["real"] is False
    assert (
        support["gw-instek-psm-2010"]["capabilities"]["hardware_validation"]
        == "rs232_read_only"
    )
    for command in ("output-off", "safe-off"):
        assert support["gw-instek-psm-2010"][command]["hardware_validation"] == "validated"
    for command in (
        "trigger-pulse", "trigger-status", "trigger-step", "trigger-list",
        "trigger-fire", "trigger-abort",
    ):
        trigger_support = support["gw-instek-psm-2010"][command]
        assert trigger_support["real"] is False
        assert trigger_support["simulate"] is False
        assert trigger_support["dry_run"] is False
        assert trigger_support["hardware_validation"] == "not_supported_by_model"
        assert "PSM-2010 does not support Powers trigger workflows." in trigger_support["disabled_reason"]
    generic_support = data["planning_profiles"]["generic-scpi"]["command_support"]
    assert generic_support["set"]["real"] is False
    for model in support:
        assert support[model]["clear"]["real"] is True
        assert support[model]["error"]["real"] is True
        assert "verify" not in support[model]
        assert "readback" not in support[model]
        assert "safety inspect" not in support[model]


def test_commands_metadata_includes_safe_exact_live_support_projection(
    client: TestClient,
) -> None:
    response = client.get("/api/commands")
    assert response.status_code == 200
    data = response.json()

    assert {
        "commands",
        "command_support_by_model_id",
        "live_support_by_model_id",
        "channel_capabilities_by_model_id",
        "electrical_ratings_by_model_id",
        "setpoint_ranges_by_model_id",
        "parameter_constraints",
        "output_affecting_commands",
    } <= set(data)
    live_support = data["live_support_by_model_id"]
    assert set(live_support) == {
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e3646a",
        "gw-instek-psm-2010",
    }

    e36312a_set = live_support["keysight-e36312a"]["commands"]["set"]
    assert {
        (scope["transport_scope"], scope["backend_scope"], scope["validation_status"])
        for scope in e36312a_set["scopes"]
    } == {
        ("usb", "system_visa", "live_validated_full_suite"),
        ("tcpip", "system_visa", "live_validated_full_suite"),
        ("tcpip", "pyvisa_py", "transport_pending"),
    }
    assert live_support["keysight-edu36311a"]["commands"]["trigger-list"]["profile_supported"] is False
    assert live_support["keysight-edu36311a"]["commands"]["trigger-list"]["scopes"] == []
    e3646a_set = live_support["keysight-e3646a"]["commands"]["set"]
    assert [(scope["transport_scope"], scope["backend_scope"]) for scope in e3646a_set["scopes"]] == [
        ("asrl", "system_visa")
    ]
    assert live_support["keysight-e3646a"]["commands"]["trigger-list"]["profile_supported"] is False
    psm = live_support["gw-instek-psm-2010"]["commands"]
    psm_validated = {"capabilities", "output-off", "safe-off"}
    assert {
        command
        for command, policy in psm.items()
        if any(scope["product_open"] for scope in policy["scopes"])
    } == psm_validated
    for command in psm_validated:
        assert {
            (scope["transport_scope"], scope["backend_scope"], scope["validation_status"])
            for scope in psm[command]["scopes"]
        } == {("asrl", "system_visa", "live_validated_full_suite")}
    for command in {"set", "output-on"}:
        assert psm[command]["scopes"] == []
    projected_diagnostics = set(psm) & {
        "list-resources", "verify", "identify", "error", "clear",
    }
    assert projected_diagnostics
    for command in projected_diagnostics:
        assert psm[command]["policy_exempt"] is True
        assert psm[command]["scopes"] == []
    generic_live = data["planning_profiles"]["generic-scpi"]["live_support"]
    assert generic_live["live_capable"] is False
    assert generic_live["schema_version"] == 2
    assert generic_live["evaluated"] is False
    assert generic_live["model_id"] is None
    assert generic_live["commands"]["set"]["scopes"] == []
    for command in {"list-resources", "verify", "identify", "error", "clear"}:
        entry = generic_live["commands"][command]
        assert entry["policy_exempt"] is True
        assert entry["offline_only"] is False
        assert entry["scopes"] == []
    assert generic_live["commands"]["identify"]["profile_supported"] is True
    assert live_support["keysight-e36312a"]["commands"]["clear"]["policy_exempt"] is True
    assert live_support["keysight-e36312a"]["commands"]["clear"]["scopes"] == []
    sequence_scope = next(
        scope
        for scope in live_support["keysight-e36312a"]["commands"]["sequence"]["scopes"]
        if scope["transport_scope"] == "usb"
    )
    assert {feature["feature_kind"] for feature in sequence_scope["features"]} == {
        "sequence_action"
    }
    assert all(feature["product_open"] for feature in sequence_scope["features"])
    pending_sequence_scope = next(
        scope
        for scope in live_support["keysight-e36312a"]["commands"]["sequence"]["scopes"]
        if scope["backend_scope"] == "pyvisa_py"
    )
    assert all(
        feature["validation_status"] == "feature_pending"
        and feature["product_open"] is False
        for feature in pending_sequence_scope["features"]
    )

    serialized = json.dumps(live_support)
    assert ".tmp_tests" not in serialized
    assert '"artifact"' not in serialized
    assert '"evidence"' not in serialized
    assert '"serial"' not in serialized


def test_product_model_selector_excludes_catalog_candidate_and_descoped_models() -> None:
    index_html, app_js, _styles_css = read_static_texts()
    command_form_js = read_static_javascript("command-form.js")
    assert '<option value="">Auto-detect</option>' in index_html
    assert "payload.physical_models" in command_form_js
    assert "model.model_id" in read_static_javascript("device-resource.js")
    for model in ("E36313A", "E36233A", "E36441A", "E36155A", "E36103B", "E36232A"):
        assert f'<option value="{model}">' not in index_html


def test_command_coverage(client: TestClient):
    """Verify WebUI command list hides CLI-only/debug commands."""
    response = client.get("/api/commands")
    assert response.status_code == 200
    data = response.json()
    webui_commands = set(data["commands"].keys())

    assert WEBUI_COMMAND_NAMES <= webui_commands
    assert "list-resources" not in webui_commands
    assert not (WEBUI_HIDDEN_LIVE_DATA_COMMANDS & webui_commands)
    assert not (WEBUI_HIDDEN_DIAGNOSTIC_COMMANDS & webui_commands)
    assert not (WEBUI_HIDDEN_UNSUPPORTED_COMMANDS & webui_commands)
    for model_support in data["command_support_by_model_id"].values():
        assert set(model_support) <= webui_commands


@pytest.mark.parametrize(
    ("command", "parameters"),
    [
        ("trigger-pulse", {"pins": [1], "channel": 1, "polarity": "positive", "exclusive_pins": False}),
        ("trigger-status", {"channel": "all"}),
        ("trigger-step", {"channel": 1, "source": "bus", "fire": True, "wait_complete": False, "poll_ms": 200}),
        (
            "trigger-list",
            {
                "channel": 1,
                "voltage_list": [0.0, 1.0],
                "current_list": [0.05],
                "dwell_list": [0.01],
                "count": 1,
                "source": "bus",
                "fire": True,
                "wait_complete": False,
                "completion_pulse_pins": [1],
                "completion_pulse_polarity": "positive",
                "exclusive_pins": False,
                "poll_ms": 200,
                "leave_trigger_configured": True,
            },
        ),
        ("trigger-fire", {"channel": 1, "wait_complete": False, "poll_ms": 200}),
        ("trigger-abort", {"channel": "all", "max_errors": 20}),
    ],
)
def test_trigger_commands_submit_in_dry_run(client: TestClient, command: str, parameters: dict[str, Any]):
    payload = {
        "command": command,
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "dry_run": True,
            "simulate": False,
            "planning_model_id": "keysight-e36312a",
        },
        "parameters": parameters,
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200

    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")
    assert job_data["result"]["plan"]["operation"]["name"] == command


def test_trigger_dry_run_with_fake_resource_requires_model_profile(client: TestClient):
    payload = {
        "command": "trigger-step",
        "runtime": {
            "resource": "USB0::FAKE::E36312A::INSTR",
            "dry_run": True,
            "simulate": False,
        },
        "parameters": {
            "channel": 1,
            "source": "bus",
            "fire": True,
            "wait_complete": False,
            "poll_ms": 200,
        },
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 400
    assert "require planning_model_id" in response.json()["detail"]


def test_trigger_dry_run_with_e36312a_sim_resource_infers_model(client: TestClient):
    payload = {
        "command": "trigger-step",
        "runtime": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "dry_run": True,
            "simulate": False,
        },
        "parameters": {
            "channel": 1,
            "source": "bus",
            "fire": True,
            "wait_complete": False,
            "poll_ms": 200,
        },
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200

    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished", job_data.get("error")
    assert job_data["result"]["plan"]["target"]["planning_model_id"] == "keysight-e36312a"


def test_hidden_list_resources_direct_submit_succeeds(client: TestClient):
    payload = {
        "command": "list-resources",
        "runtime": {"simulate": True},
        "parameters": {},
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200

    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished"
    assert "resources" in job_data["result"]


def test_post_job_simulate_set(client: TestClient):
    payload = {
        "command": "set",
        "runtime": simulated_e36312a_runtime(),
        "parameters": {"channel": 1, "voltage": 5.0, "current": 1.0}
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "job_id" in data

    job_data = wait_for_job(client, data["job_id"])
    assert job_data["status"] == "finished"
    assert "operation" in job_data["result"]


def test_post_job_simulate_set_accepts_voltage_only(client: TestClient):
    payload = {
        "command": "set",
        "runtime": simulated_e36312a_runtime(),
        "parameters": {"channel": 1, "voltage": 5.0},
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200

    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished"
    assert [step["action"] for step in job_data["result"]["steps"]] == ["set_voltage"]
    assert job_data["parameters"] == {"channel": 1, "voltage": 5.0}


def test_post_job_rejects_set_without_setpoints(client: TestClient):
    payload = {
        "command": "set",
        "runtime": simulated_e36312a_runtime(),
        "parameters": {"channel": 1},
    }
    response = client.post("/api/jobs", json=payload)

    assert response.status_code == 400
    assert "set requires voltage, current, or both" in response.json()["detail"]


def test_post_job_simulate_set_rejects_string_channel(client: TestClient):
    payload = {
        "command": "set",
        "runtime": simulated_e36312a_runtime(),
        "parameters": {"channel": "3", "voltage": 5.0, "current": 1.0},
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 400
    assert "channel must be a positive integer" in response.json()["detail"]


def test_post_job_simulate_apply_preserves_all_channel(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from powers_tool_webui import commands

    captured: list[Any] = []

    def fake_run_core_command(request, *, stop_requested=None):
        captured.append(request)
        return {"ok": True, "parameters": request.parameters}

    monkeypatch.setattr(commands, "run_core_command", fake_run_core_command)

    payload = {
        "command": "apply",
        "runtime": simulated_e36312a_runtime(),
        "parameters": {"channel": "all", "voltage": 5.0, "current": 1.0},
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200

    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "finished"
    assert captured[0].command == "apply"
    assert captured[0].parameters["channel"] == "all"
    assert job_data["result"]["parameters"]["channel"] == "all"


def test_adapter_preserves_validated_channel_for_core_requests(monkeypatch: pytest.MonkeyPatch):
    from powers_tool_core.core import RuntimeOptions
    from powers_tool_webui import commands
    from powers_tool_webui.jobs import Job

    captured: list[Any] = []

    def fake_run_core_command(request, *, stop_requested=None):
        captured.append(request)
        return {"ok": True}

    monkeypatch.setattr(commands, "run_core_command", fake_run_core_command)

    runtime = {"resource": "USB0::SIM::E36312A::INSTR", "simulate": True}
    commands.execute_job_command(Job("set-job", "set", runtime, {"channel": 3, "voltage": 1.0, "current": 0.1}))
    commands.execute_job_command(Job("on-job", "output-on", runtime, {"channel": 3}))
    commands.execute_job_command(Job("safe-job", "safe-off", runtime, {"channel": "all"}))

    assert captured[0].parameters["channel"] == 3
    assert captured[1].parameters["channel"] == 3
    assert captured[2].parameters["channel"] == "all"

    request = commands._request_for_job("read-status", RuntimeOptions(simulate=True), {"channel": 2})
    assert request.parameters["channel"] == 2

