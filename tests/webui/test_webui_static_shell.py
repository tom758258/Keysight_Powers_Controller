"""Static shell, resource, live-panel, and basic-control WebUI tests."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from _webui_shared import (
    assert_static_attr,
    assert_static_id,
    extract_js_function,
    read_static_javascript,
    read_static_texts,
    run_frontend_javascript_assertions,
    static_tag_with_id,
)

def test_guard_no_cli_import():
    package_root = Path(__file__).parents[2] / "src" / "powers_tool_webui"
    for source_path in package_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert not any(name == "powers_tool_cli" or name.startswith("powers_tool_cli.") for name in imported)


def test_p5_localized_refresh_composes_only_presentation_paths_and_preserves_state():
    assertions = r"""
const strictAssert = require("node:assert/strict");
const calls = [];
let fetchCalls = 0;
let eventSourceConstructions = 0;
let eventSourceCloses = 0;
let reloads = 0;
globalThis.fetch = () => { fetchCalls += 1; };
globalThis.EventSource = class {
  constructor() { eventSourceConstructions += 1; }
  close() { eventSourceCloses += 1; }
};
globalThis.location = { reload() { reloads += 1; } };

applyStaticTranslations = () => calls.push("static");
webuiLocaleUi.renderLanguageButton = () => calls.push("locale");
refreshDeviceResourcePresentation = () => calls.push("device");
refreshCommandPresentation = () => calls.push("command");
refreshSelectedCommandGuardPresentation = () => calls.push("command-guards");
webuiWorkflows.refreshWorkflowPresentation = () => calls.push("workflow");
refreshWorkflowOperationalPresentation = () => calls.push("workflow-operation");
refreshBasicControlsPresentation = () => calls.push("basic");
refreshResultPresentation = () => calls.push("result");
refreshLiveDataPresentation = () => calls.push("live");

state.executionMode = "simulate";
state.realIdentityCache = { expectedModelId: "keysight-e36312a", resource: "RAW::RESOURCE", serial: { baud_rate: 9600 } };
state.planningIdentityCache = { simulate: "keysight-e3646a", "dry-run": "keysight-edu36311a" };
state.realWriteAuthorization = '{"resource":"RAW::RESOURCE","expected_model_id":"keysight-e36312a","connected_model_id":"keysight-e3646a"}';
state.basicActionStates = { "output:all": { status: "pending", desiredOutput: true, awaitingReadback: true } };
state.selected = "ramp-list";
state.activeCategory = "workflow";
state.rampListSegments = [{ channel: 1, voltage: 1.25, current: 0.1, dwell: 0.5 }];
state.rampListEnableOutput = true;
state.rampListLoopEnabled = true;
state.rampListLoopCountDraft = "invalid draft";
state.rampListCompletionPulse = { enabled: true, pins: "1,3", timing: "loop" };
state.triggerListActiveChannel = 2;
state.triggerListControls = { source: "bus", wait_complete: true };
state.triggerListChannels = { 1: { voltage: "1.5", current: "0.1" }, 2: { voltage: "invalid draft" } };
state.sequenceSteps = [{ action: "wait", seconds: 2 }];
state.sequenceLoopEnabled = true;
state.sequenceLoopCountDraft = "invalid sequence draft";
state.sequenceExpanded = new Set([0]);
state.latestSnapshotDocument = { schema_version: 1, model_id: "keysight-e36312a" };
state.loadedSnapshotDocument = { schema_version: 2, kind: "powers-tool-snapshot", raw: "VISA <raw> detail" };
state.loadedSnapshotFilename = "RAW.snapshot.json";
state.restoreChannel = "all";
state.restoreOutputState = true;
state.restorePlanPreview = { steps: [{ command: "set", channel: 1 }] };
state.restorePlanPreviewStatus = "finished";
state.jobs = [{ jobId: "job-raw", command: "ramp", status: "failed", summary: { rawFallback: "VISA <raw> detail" } }];
state.workspaceResults = { raw: { command: "ramp", result: { unit: "V", value: 1.25 } } };
state.liveJobId = "live-job";
state.livePanel = { status: "ok", resource: "RAW::RESOURCE", channels: [{ channel: 1, voltage: 1.25, output_enabled: false }] };
state.samples = [{ timestamp: 1, data: state.livePanel }];
state.resultCollapsed = false;
state.jobResultCollapsed = true;
const commandInput = { value: "draft", checked: true, selectValue: "all", parameterName: "channel" };
const resourceInput = { value: "RAW::RESOURCE" };
const realWriteCheckbox = { checked: false, disabled: false };
const resultJson = '{"raw":"VISA <raw> detail"}';
const before = JSON.stringify({
  executionMode: state.executionMode,
  realIdentityCache: state.realIdentityCache,
  planningIdentityCache: state.planningIdentityCache,
  realWriteAuthorization: state.realWriteAuthorization,
  basicActionStates: state.basicActionStates,
  selected: state.selected,
  activeCategory: state.activeCategory,
  rampListSegments: state.rampListSegments,
  rampListEnableOutput: state.rampListEnableOutput,
  rampListLoopEnabled: state.rampListLoopEnabled,
  rampListLoopCountDraft: state.rampListLoopCountDraft,
  rampListCompletionPulse: state.rampListCompletionPulse,
  triggerListActiveChannel: state.triggerListActiveChannel,
  triggerListControls: state.triggerListControls,
  triggerListChannels: state.triggerListChannels,
  sequenceSteps: state.sequenceSteps,
  sequenceLoopEnabled: state.sequenceLoopEnabled,
  sequenceLoopCountDraft: state.sequenceLoopCountDraft,
  sequenceExpanded: [...state.sequenceExpanded],
  latestSnapshotDocument: state.latestSnapshotDocument,
  loadedSnapshotDocument: state.loadedSnapshotDocument,
  loadedSnapshotFilename: state.loadedSnapshotFilename,
  restoreChannel: state.restoreChannel,
  restoreOutputState: state.restoreOutputState,
  restorePlanPreview: state.restorePlanPreview,
  restorePlanPreviewStatus: state.restorePlanPreviewStatus,
  jobs: state.jobs,
  workspaceResults: state.workspaceResults,
  liveJobId: state.liveJobId,
  livePanel: state.livePanel,
  samples: state.samples,
  resultCollapsed: state.resultCollapsed,
  jobResultCollapsed: state.jobResultCollapsed,
  commandInput,
  resourceInput,
  realWriteCheckbox,
  resultJson,
});
const identities = {
  realIdentityCache: state.realIdentityCache,
  basicActionStates: state.basicActionStates,
  rampListSegments: state.rampListSegments,
  rampListCompletionPulse: state.rampListCompletionPulse,
  triggerListChannels: state.triggerListChannels,
  sequenceSteps: state.sequenceSteps,
  sequenceExpanded: state.sequenceExpanded,
  loadedSnapshotDocument: state.loadedSnapshotDocument,
  restorePlanPreview: state.restorePlanPreview,
  jobs: state.jobs,
  workspaceResults: state.workspaceResults,
  livePanel: state.livePanel,
  samples: state.samples,
};

for (const locale of ["en", "zh-TW", "en", "zh-TW"]) {
  globalThis.__webuiLocale = locale;
  refreshLocalizedPresentation();
}

const after = JSON.stringify({
  executionMode: state.executionMode,
  realIdentityCache: state.realIdentityCache,
  planningIdentityCache: state.planningIdentityCache,
  realWriteAuthorization: state.realWriteAuthorization,
  basicActionStates: state.basicActionStates,
  selected: state.selected,
  activeCategory: state.activeCategory,
  rampListSegments: state.rampListSegments,
  rampListEnableOutput: state.rampListEnableOutput,
  rampListLoopEnabled: state.rampListLoopEnabled,
  rampListLoopCountDraft: state.rampListLoopCountDraft,
  rampListCompletionPulse: state.rampListCompletionPulse,
  triggerListActiveChannel: state.triggerListActiveChannel,
  triggerListControls: state.triggerListControls,
  triggerListChannels: state.triggerListChannels,
  sequenceSteps: state.sequenceSteps,
  sequenceLoopEnabled: state.sequenceLoopEnabled,
  sequenceLoopCountDraft: state.sequenceLoopCountDraft,
  sequenceExpanded: [...state.sequenceExpanded],
  latestSnapshotDocument: state.latestSnapshotDocument,
  loadedSnapshotDocument: state.loadedSnapshotDocument,
  loadedSnapshotFilename: state.loadedSnapshotFilename,
  restoreChannel: state.restoreChannel,
  restoreOutputState: state.restoreOutputState,
  restorePlanPreview: state.restorePlanPreview,
  restorePlanPreviewStatus: state.restorePlanPreviewStatus,
  jobs: state.jobs,
  workspaceResults: state.workspaceResults,
  liveJobId: state.liveJobId,
  livePanel: state.livePanel,
  samples: state.samples,
  resultCollapsed: state.resultCollapsed,
  jobResultCollapsed: state.jobResultCollapsed,
  commandInput,
  resourceInput,
  realWriteCheckbox,
  resultJson,
});
strictAssert.equal(after, before);
for (const [name, value] of Object.entries(identities)) strictAssert.equal(state[name], value);
strictAssert.equal(fetchCalls, 0);
strictAssert.equal(eventSourceConstructions, 0);
strictAssert.equal(eventSourceCloses, 0);
strictAssert.equal(reloads, 0);
strictAssert.deepEqual(calls, Array(4).fill([
  "static", "locale", "device", "command", "command-guards", "workflow",
  "workflow-operation", "basic", "result", "live",
]).flat());
"""
    run_frontend_javascript_assertions(assertions)

    _index_html, app_js, _styles_css = read_static_texts()
    refresh = extract_js_function(app_js, "refreshLocalizedPresentation")
    for forbidden in (
        "fetch",
        "EventSource",
        "renderForm",
        "updateExecutionModeUi",
        "refreshHealth",
        "selectCommand",
        "toggleLiveMonitor",
        "runSelected",
        "location.reload",
    ):
        assert forbidden not in refresh


def test_job_result_panel_accessibility_refreshes_from_canonical_collapsed_state():
    assertions = r"""
const strictAssert = require("node:assert/strict");
function classList() {
  const values = new Set();
  return {
    toggle(name, enabled) {
      if (enabled) values.add(name);
      else values.delete(name);
    },
    contains(name) { return values.has(name); },
  };
}
function panelElement() {
  return { classList: classList() };
}
function buttonElement() {
  return {
    textContent: "",
    attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
  };
}

const jobPanel = panelElement();
const jobButton = buttonElement();
const resultPanel = panelElement();
const resultButton = buttonElement();
const elements = new Map([
  ["job-result-panel", jobPanel],
  ["job-result-toggle", jobButton],
  ["result-panel", resultPanel],
  ["result-toggle", resultButton],
]);
document.getElementById = (id) => elements.get(id);

let renderHistoryCalls = 0;
let renderWorkspaceCalls = 0;
let fetchCalls = 0;
let eventSourceConstructions = 0;
let eventSourceCloses = 0;
let jobActions = 0;
let reloads = 0;
renderHistory = () => { renderHistoryCalls += 1; };
renderWorkspaceSummary = () => { renderWorkspaceCalls += 1; };
clearJobResults = () => { jobActions += 1; };
globalThis.fetch = () => { fetchCalls += 1; };
globalThis.EventSource = class {
  constructor() { eventSourceConstructions += 1; }
  close() { eventSourceCloses += 1; }
};
globalThis.location = { reload() { reloads += 1; } };

const rawJob = {
  jobId: "job-raw",
  command: "ramp",
  status: "failed",
  presentationJob: { error: "VISA <raw> detail" },
};
state.jobs = [rawJob];
const jobsIdentity = state.jobs;
state.resultCollapsed = false;

function assertJobPanel(collapsed, locale, text, expanded, label) {
  state.jobResultCollapsed = collapsed;
  setLocale(locale);
  refreshResultPresentation();
  strictAssert.equal(state.jobResultCollapsed, collapsed);
  strictAssert.equal(jobButton.textContent, text);
  strictAssert.equal(jobButton.attributes["aria-expanded"], expanded);
  strictAssert.equal(jobButton.attributes["aria-label"], label);
  strictAssert.equal(jobPanel.classList.contains("collapsed"), collapsed);
  strictAssert.equal(state.jobs, jobsIdentity);
  strictAssert.equal(state.jobs[0], rawJob);
  strictAssert.equal(rawJob.presentationJob.error, "VISA <raw> detail");
}

assertJobPanel(true, "en", "+", "false", "Expand job result");
assertJobPanel(true, "zh-TW", "+", "false", "展開作業結果");
assertJobPanel(false, "en", "-", "true", "Collapse job result");
assertJobPanel(false, "zh-TW", "-", "true", "收合作業結果");

state.jobResultCollapsed = true;
toggleJobResultPanel();
strictAssert.equal(state.jobResultCollapsed, false);
strictAssert.equal(jobButton.textContent, "-");
strictAssert.equal(jobButton.attributes["aria-expanded"], "true");
strictAssert.equal(jobButton.attributes["aria-label"], "收合作業結果");

strictAssert.equal(renderHistoryCalls, 4);
strictAssert.equal(renderWorkspaceCalls, 4);
strictAssert.equal(fetchCalls, 0);
strictAssert.equal(eventSourceConstructions, 0);
strictAssert.equal(eventSourceCloses, 0);
strictAssert.equal(jobActions, 0);
strictAssert.equal(reloads, 0);
"""
    run_frontend_javascript_assertions(assertions)

    _index_html, app_js, _styles_css = read_static_texts()
    sync = extract_js_function(app_js, "syncJobResultPanelState")
    toggle = extract_js_function(app_js, "toggleJobResultPanel")
    refresh = extract_js_function(app_js, "refreshResultPresentation")
    assert "state.jobResultCollapsed" in sync
    assert "syncJobResultPanelState();" in toggle
    assert "syncJobResultPanelState();" in refresh
    for forbidden in ("fetch", "EventSource", "clearJobResults", "state.jobs =", "location.reload"):
        assert forbidden not in sync


def test_import_smoke():
    """Verify WebUI runtime is importable."""
    from powers_tool_webui.app import app
    from powers_tool_webui.jobs import job_manager, JobStatus
    from powers_tool_webui.commands import execute_job_command
    from powers_tool_webui.server import main
    assert app is not None
    assert job_manager is not None
    assert JobStatus is not None
    assert execute_job_command is not None
    assert main is not None


def test_static_ui_exposes_advanced_serial_controls():
    html, app_js, styles_css = read_static_texts()
    serial_control_ids = (
        "serial-baud-rate",
        "serial-data-bits",
        "serial-parity",
        "serial-stop-bits",
        "serial-flow-control",
        "serial-read-termination",
        "serial-write-termination",
        "serial-remote",
        "serial-local-on-close",
    )

    assert 'class="device-resource-section"' in html
    assert_static_id(html, "device-resource-body")
    assert_static_id(html, "device-options-toggle")
    assert_static_id(html, "device-options-panel")
    assert_static_id(html, "supported-devices-toggle")
    assert_static_id(html, "supported-devices-panel")
    assert_static_id(html, "supported-devices-body")
    assert_static_id(html, "toggle-device-resource")
    assert_static_id(html, "resource")
    assert_static_id(html, "resource-select")
    assert_static_id(html, "scan")
    assert_static_attr(html, "device-options-toggle", "aria-label", "Device options")
    assert_static_attr(html, "device-options-toggle", "aria-controls", "device-options-panel")
    assert_static_attr(html, "device-options-toggle", "aria-expanded", "false")
    assert_static_attr(html, "supported-devices-toggle", "aria-controls", "supported-devices-panel")
    assert_static_attr(html, "supported-devices-toggle", "aria-expanded", "false")
    assert html.index('id="supported-devices-toggle"') < html.index('id="device-options-toggle"')
    for expected in (
        'data-i18n="supported_devices.vendor"',
        'data-i18n="supported_devices.model"',
        'data-i18n="supported_devices.connections"',
    ):
        assert expected in html
    assert_static_attr(html, "toggle-device-resource", "aria-controls", "device-resource-body")
    assert_static_attr(html, "toggle-device-resource", "aria-expanded", "true")
    assert_static_id(html, "expected-model-id")

    panel_index = html.index('id="device-options-panel"')
    body_index = html.index('id="device-resource-body"')
    assert panel_index < html.index('id="expected-model-id"') < body_index
    for element_id in serial_control_ids:
        assert_static_id(html, element_id)
        assert panel_index < html.index(f'id="{element_id}"') < body_index

    assert "Expected model" in html
    assert "Model / expected model" not in html
    identity_help_tag = static_tag_with_id(html, "identity-model-help")
    assert 'data-i18n="device.identity_model_help"' in identity_help_tag
    assert html.count('id="identity-model-help"') == 1
    assert 'option value="keysight-' not in html
    assert "renderExpectedModelOptions" in app_js
    assert 'model.model_id' in app_js
    for unvalidated_model in ("E36103B", "E36232A"):
        assert f'<option value="{unvalidated_model}">{unvalidated_model}</option>' not in html
    assert '<option value="GENERIC">GENERIC</option>' not in html
    assert "serial-panel" not in html
    assert ".serial-panel" not in styles_css
    assert 'name="execution-mode" value="simulate"' in html
    assert 'name="execution-mode" value="dry-run"' in html
    assert 'class="device-resource-title-row"' in html
    assert 'id="execution-mode-badge" class="execution-mode-badge real-locked" aria-live="polite">Real · Writes locked</span>' in html
    badge_tag = static_tag_with_id(html, "execution-mode-badge")
    assert badge_tag.startswith("<span ")
    assert "onclick" not in badge_tag
    assert 'getElementById("execution-mode-badge").addEventListener' not in app_js
    title_row = html[html.index('class="device-resource-title-row"'):html.index('</div>', html.index('class="device-resource-title-row"'))]
    title_end = title_row.index("</strong>")
    badge_start = title_row.index('id="execution-mode-badge"')
    assert 'id="device-resource-title"' in title_row
    assert title_end < badge_start
    assert html.count('id="real-write-authorization"') == 1
    assert html.count('id="real-write-enabled"') == 1
    real_write_label = html[
        html.index('<label id="real-write-authorization"'):
        html.index("</label>", html.index('<label id="real-write-authorization"')) + len("</label>")
    ]
    assert '<input id="real-write-enabled" type="checkbox">' in real_write_label
    assert real_write_label.count('data-i18n="device.enable_real_hardware_writes"') == 1
    assert real_write_label.index('id="real-write-enabled"') < real_write_label.index(
        'data-i18n="device.enable_real_hardware_writes"'
    )
    assert "Simulate" in html
    execution_mode_ui = extract_js_function(app_js, "updateExecutionModeUi")
    assert "refreshExecutionModePresentation();" in execution_mode_ui
    execution_presentation = extract_js_function(app_js, "refreshExecutionModePresentation")
    for key in (
        "execution_mode.badge.real_locked",
        "execution_mode.badge.real_enabled",
        "execution_mode.badge.simulate",
        "execution_mode.badge.dry_run",
    ):
        assert key in execution_presentation
    for class_name in ("real-locked", "real-enabled", "simulate", "dry-run"):
        assert f'badge.classList.add("{class_name}")' in execution_mode_ui
    assert ".device-resource-title-row" in styles_css
    assert ".execution-mode-badge.real-locked" in styles_css
    assert ".execution-mode-badge.real-enabled" in styles_css

    runtime_block = extract_js_function(app_js, "runtimePayload")
    assert 'const expectedModelId = valueOrNull("expected-model-id");' in runtime_block
    assert "if (expectedModelId !== null) runtime.expected_model_id = expectedModelId;" in runtime_block
    assert "serialOptionsPayload()" in runtime_block
    assert "runtime.serial_options = serialOptions" in runtime_block
    assert "runtime.serial_remote = true" in runtime_block
    assert "runtime.serial_local_on_close = true" in runtime_block
    assert ".serial-grid" in styles_css


def test_static_command_forms_do_not_repeat_real_write_authorization_warning() -> None:
    index_html, app_js, styles_css = read_static_texts()
    update_selected = extract_js_function(app_js, "updateSelectedCommandState")
    command_form_js = read_static_javascript("command-form.js")
    refresh_description = extract_js_function(command_form_js, "refreshSelectedCommandDescription")
    runtime_block = extract_js_function(app_js, "runtimePayload")
    submit_selected = extract_js_function(app_js, "runSelected")
    submit_basic = extract_js_function(app_js, "submitBasicJob")

    assert "confirm-banner" not in index_html
    assert "confirm-banner" not in app_js
    assert "confirm-banner" not in styles_css
    assert "Enable real hardware writes in Device options before running this command." not in app_js
    assert "webuiCommandForm.renderCommandGuidance(state.selected, parameters, triggerControlGuardReason, triggerFireWaitGuardReason);" in update_selected
    assert "commandStatusText(meta)" in refresh_description
    assert "meta.live_support_status" not in refresh_description
    assert "confirm: hasRealWriteAuthorization()" in runtime_block
    assert 'meta.requires_confirm && state.executionMode === "real" && !payload.runtime.confirm' in submit_selected
    assert 'meta.requires_confirm && state.executionMode === "real" && !payload.runtime.confirm' in submit_basic
    reset_authorization = extract_js_function(app_js, "resetRealWriteAuthorization")
    assert "clearRealWriteAuthorization()" in reset_authorization
    assert "state.realWriteAuthorization = realAuthorizationContext();" in reset_authorization
    assert "resetAuthorization: state.executionMode === \"real\"" in extract_js_function(
        app_js, "handleExpectedModelChanged"
    )
    assert "resetAuthorization: modeChanged" in extract_js_function(
        app_js, "handleExecutionModeChange"
    )
    assert "resetAuthorization: value !== previous" in extract_js_function(
        app_js, "syncSelectedResource"
    )
    assert "resetAuthorization: true" in extract_js_function(app_js, "syncTypedResource")
    assert "resetAuthorization: true" in extract_js_function(app_js, "updateResourceModel")


def test_static_normal_model_dropdown_policy() -> None:
    html, app_js, _styles_css = read_static_texts()
    model_select = html[html.index('id="expected-model-id"'):html.index("</select>", html.index('id="expected-model-id"'))]

    assert '<option value="">Auto-detect</option>' in model_select
    assert 'option value="keysight-' not in model_select
    renderer = extract_js_function(app_js, "populateIdentitySelector")
    assert "state.physicalModels.forEach" in renderer
    assert "model.model_id" in renderer
    for unvalidated_model in ("E36103B", "E36232A"):
        assert unvalidated_model not in model_select


def test_static_device_resource_summary_uses_model_wording():
    _html, app_js, _styles_css = read_static_texts()
    state_js = read_static_javascript("state.js")
    summary = extract_js_function(app_js, "updateDeviceResourceSummary")
    builder = extract_js_function(app_js, "buildDeviceResourceSummary")

    assert "Manual" not in summary
    assert "refreshDeviceResourceSummaryPresentation();" in summary
    assert "execution_mode.summary.real" in builder
    assert "execution_mode.summary.simulate" in builder
    assert "execution_mode.summary.dry_run" in builder
    assert "device.expected_guard" in builder
    assert "resource.real.preserved" in builder
    assert "actualCurrentResourceModel()" in builder
    assert "exactSupportContextSummary(resource)" in builder
    assert "resourceDisplayModels: {}" in state_js
    assert "state.resourceDisplayModels[resource] = detectedModel;" in app_js


def test_frontend_planning_identity_state_is_page_local_and_mode_isolated() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");

        class FakeContainer {
          constructor() {
            this.children = [];
            this.label = "";
          }
          append(...children) { this.children.push(...children); }
        }

        class FakeSelect extends FakeContainer {
          constructor() {
            super();
            this.value = "";
            this.options = [];
          }
          replaceChildren() {
            this.children = [];
            this.options = [];
            this.value = "";
          }
          add(option) {
            this.children.push(option);
            this.options.push(option);
          }
          append(...children) {
            super.append(...children);
            children.forEach((child) => this.options.push(...(child.children || [])));
          }
        }

        globalThis.Option = function Option(text, value) {
          return { textContent: text, value: String(value), disabled: false };
        };
        const select = new FakeSelect();
        document.createElement = (tagName) => tagName === "optgroup" ? new FakeContainer() : {};
        document.getElementById = (id) => id === "expected-model-id" ? select : null;

        state.physicalModels = [
          { model_id: "keysight-e36312a", display_name: "Keysight E36312A" },
          { model_id: "keysight-e3646a", display_name: "Keysight E3646A" }
        ];
        state.planningProfiles = {
          "generic-scpi": { profile_id: "generic-scpi", display_name: "Generic SCPI" }
        };
        state.realIdentityCache.expectedModelId = "";
        state.planningIdentityCache = { simulate: "", "dry-run": "" };

        state.executionMode = "simulate";
        populateIdentitySelector();
        strictAssert.equal(select.value, "", "first Simulate entry must be blank");
        select.value = "keysight-e36312a";
        rememberCurrentExecutionIdentity();

        state.executionMode = "dry-run";
        populateIdentitySelector();
        strictAssert.equal(select.value, "", "first Dry-run entry must be blank");
        select.value = "profile:generic-scpi";
        rememberCurrentExecutionIdentity();

        state.executionMode = "simulate";
        populateIdentitySelector();
        strictAssert.equal(select.value, "keysight-e36312a");

        state.executionMode = "dry-run";
        populateIdentitySelector();
        strictAssert.equal(select.value, "profile:generic-scpi");

        state.executionMode = "real";
        populateIdentitySelector();
        strictAssert.equal(select.value, "", "Dry-run identity must not become Expected Model");
        select.value = "keysight-e3646a";
        rememberCurrentExecutionIdentity();

        state.executionMode = "simulate";
        populateIdentitySelector();
        strictAssert.equal(select.value, "keysight-e36312a", "Real guard must not replace Simulate identity");
        """
    )
    run_frontend_javascript_assertions(assertions)

    _html, app_js, _styles_css = read_static_texts()
    state_js = read_static_javascript("state.js")
    assert 'planningIdentityCache: { simulate: "", "dry-run": "" }' in state_js
    assert "localStorage" not in app_js
    assert "sessionStorage" not in app_js
    assert "rememberCurrentExecutionIdentity();" in extract_js_function(app_js, "handleExecutionModeChange")
    assert "rememberCurrentExecutionIdentity();" in extract_js_function(app_js, "handleExpectedModelChanged")


def test_frontend_planning_electrical_constraints_restore_base_values() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");

        class FakeInput {
          constructor() {
            this.type = "number";
            this.dataset = {};
            this.attributes = {};
            for (const name of ["min", "max", "step", "title"]) {
              Object.defineProperty(this, name, {
                get: () => this.attributes[name] ?? "",
                set: (value) => { this.attributes[name] = String(value); }
              });
            }
          }
          setAttribute(name, value) { this.attributes[name] = String(value); }
          getAttribute(name) { return this.attributes[name] ?? null; }
          hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name); }
          removeAttribute(name) { delete this.attributes[name]; }
        }

        const identity = { value: "keysight-e36312a" };
        const channel = { value: "1" };
        document.getElementById = (id) => ({
          "expected-model-id": identity,
          "param-channel": channel
        })[id] || null;

        state.executionMode = "simulate";
        state.parameterConstraints = {
          voltage: { min: 0, max: 100, step: 0.1, description: "Finite non-negative voltage setpoint." },
          stop_voltage: { min: 0, step: "any", description: "Finite non-negative final voltage." },
          future_value: { min: 0, step: "any", description: "Future backend constraint." }
        };
        state.electricalRatingsByModel = {
          "keysight-e36312a": { channels: [{ channel: 1, max_voltage: 6, max_current: 5 }] },
          "keysight-e3646a": { channels: [{ channel: 1, max_voltage: 20, max_current: 1 }] }
        };

        const input = new FakeInput();
        refreshInputElectricalConstraints(input, "voltage");
        strictAssert.equal(input.min, "0");
        strictAssert.equal(input.max, "6");
        strictAssert.equal(input.step, "0.1");
        strictAssert.match(input.title, /maximum 6 V/);

        input.min = "1";
        input.step = "2";
        identity.value = "profile:generic-scpi";
        refreshInputElectricalConstraints(input, "voltage");
        strictAssert.equal(selectedElectricalRatingModel(), null);
        strictAssert.equal(input.min, "0");
        strictAssert.equal(input.max, "100");
        strictAssert.equal(input.step, "0.1");
        strictAssert.equal(input.title, "Finite non-negative voltage setpoint.");
        strictAssert.equal(input.dataset.electricalBaseConstraints, undefined);

        identity.value = "keysight-e3646a";
        refreshInputElectricalConstraints(input, "voltage");
        strictAssert.equal(input.max, "20");
        strictAssert.match(input.title, /maximum 20 V/);

        identity.value = "";
        refreshInputElectricalConstraints(input, "voltage");
        strictAssert.equal(input.min, "0");
        strictAssert.equal(input.max, "100");
        strictAssert.equal(input.step, "0.1");
        strictAssert.equal(input.title, "Finite non-negative voltage setpoint.");

        const stopVoltage = new FakeInput();
        applyParameterConstraint(stopVoltage, "stop_voltage");
        strictAssert.equal(stopVoltage.title, "Finite non-negative final voltage.");
        const future = new FakeInput();
        applyParameterConstraint(future, "future_value");
        strictAssert.equal(future.title, "Future backend constraint.");

        setLocale("zh-TW");
        const root = {
          querySelectorAll(selector) {
            strictAssert.equal(selector, "[data-parameter-constraint]");
            return [input, stopVoltage, future];
          }
        };
        refreshParameterConstraintPresentation(root);
        strictAssert.equal(input.title, "有限且非負的電壓設定值。");
        strictAssert.equal(stopVoltage.title, "停止電壓必須為有限值且不得小於 0。");
        strictAssert.equal(future.title, "Future backend constraint.");

        identity.value = "keysight-e36312a";
        refreshInputElectricalConstraints(input, "voltage");
        strictAssert.equal(input.title, "官方獨立通道直流輸出額定值：最大 6 V。");
        setLocale("en");
        refreshParameterConstraintPresentation(root);
        strictAssert.equal(input.title, "Official independent-channel DC output rating: maximum 6 V.");
        strictAssert.equal(stopVoltage.title, "Finite non-negative final voltage.");
        strictAssert.equal(future.title, "Future backend constraint.");
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_frontend_device_resource_summary_is_mode_and_identity_aware() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        const elements = new Map([
          ["resource", { value: "ASRL7::INSTR" }],
          ["resource-select", { value: "ASRL7::INSTR", options: [{ textContent: "ASRL7::INSTR" }] }],
          ["expected-model-id", { value: "keysight-e36312a" }],
          ["device-resource-summary", { textContent: "", title: "" }]
        ]);
        document.getElementById = (id) => elements.get(id) || null;

        state.physicalModels = [
          { model_id: "keysight-e36312a", display_name: "Keysight E36312A" },
          { model_id: "keysight-edu36311a", display_name: "Keysight EDU36311A" }
        ];
        state.planningProfiles = {
          "generic-scpi": { profile_id: "generic-scpi", display_name: "Generic SCPI" }
        };
        state.resourceModels = { "ASRL7::INSTR": "keysight-edu36311a" };
        state.resourceChannelModels = { "ASRL7::INSTR": "keysight-edu36311a" };
        state.resourceDisplayModels = { "ASRL7::INSTR": "EDU36311A" };
        state.resourceLiveSupport = {
          evaluated: true,
          model_id: "keysight-edu36311a",
          transport_scope: "asrl",
          backend_scope: "system_visa",
          commands: {
            set: { product_open: true, policy_exempt: false },
            ramp: { product_open: false, policy_exempt: false, exact_scope_validation_status: "feature_pending" }
          }
        };
        state.resourceLiveSupportContext = {
          resource: "ASRL7::INSTR",
          model_id: "keysight-edu36311a"
        };

        state.executionMode = "real";
        updateDeviceResourceSummary();
        const summary = elements.get("device-resource-summary");
        strictAssert.match(summary.textContent, /Real mode/);
        strictAssert.match(summary.textContent, /VISA resource: ASRL7::INSTR/);
        strictAssert.match(summary.textContent, /Detected model: Keysight EDU36311A/);
        strictAssert.match(summary.textContent, /Expected Model guard: Require Keysight E36312A/);
        strictAssert.match(summary.textContent, /ASRL \/ system VISA/);
        strictAssert.doesNotMatch(summary.textContent, /validated|pending|unavailable/);
        strictAssert.match(summary.title, /does not match/);

        state.executionMode = "simulate";
        elements.get("expected-model-id").value = "keysight-e36312a";
        updateDeviceResourceSummary();
        strictAssert.match(summary.textContent, /Simulate mode/);
        strictAssert.match(summary.textContent, /Planning model: Keysight E36312A/);
        strictAssert.match(summary.textContent, /Real VISA resource preserved, not used: ASRL7::INSTR/);
        strictAssert.equal(summary.textContent.includes("Expected Model guard"), false);

        state.executionMode = "dry-run";
        elements.get("expected-model-id").value = "profile:generic-scpi";
        updateDeviceResourceSummary();
        strictAssert.match(summary.textContent, /Dry-run mode/);
        strictAssert.match(summary.textContent, /Planning profile: Generic SCPI/);
        strictAssert.match(summary.textContent, /preserved, not used/);
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_static_model_profile_change_refreshes_effective_ui_model():
    _html, app_js, _styles_css = read_static_texts()
    bind = extract_js_function(app_js, "bind")
    handler = extract_js_function(app_js, "handleExpectedModelChanged")
    selected_expected = extract_js_function(app_js, "selectedExpectedModel")
    selected_expected_label = extract_js_function(app_js, "selectedExpectedModelLabel")
    selected_command = extract_js_function(app_js, "selectedCommandModel")
    selected_channel = extract_js_function(app_js, "selectedChannelModel")
    runtime_block = extract_js_function(app_js, "runtimePayload")

    assert 'document.getElementById("expected-model-id")?.addEventListener("change", handleExpectedModelChanged);' in bind
    assert 'valueOrNull("expected-model-id")' in selected_expected
    assert "physicalModelDisplayName(expected)" in selected_expected_label
    assert "state.commandSupportByModel?.[expected]" in selected_command
    assert "return detectedCommandModelForResource(valueOrNull(\"resource\"));" in selected_command
    assert "state.channelCapabilitiesByModel?.[expected]" in selected_channel
    assert "return detectedChannelModelForResource(valueOrNull(\"resource\"));" in selected_channel
    assert "updateExecutionModeUi({ renderCommands: false" in handler
    assert 'resetAuthorization: state.executionMode === "real"' in handler
    assert "refreshBasicInputConstraints();" in handler
    assert "refreshElectricalRatingConstraints();" in handler
    assert "renderWorkspaceSummary();" in handler
    assert "updateSelectedCommandState();" in handler
    assert "resourceModels" not in handler
    assert "resourceChannelModels" not in handler
    assert "resourceDisplayModels" not in handler
    assert 'const expectedModelId = valueOrNull("expected-model-id");' in runtime_block
    assert "if (expectedModelId !== null) runtime.expected_model_id = expectedModelId;" in runtime_block
    assert 'runtime.expected_model_id = ""' not in runtime_block


def test_static_commands_payload_stores_setpoint_range_metadata():
    _html, app_js, _styles_css = read_static_texts()
    state_js = read_static_javascript("state.js")
    load_commands = extract_js_function(app_js, "loadCommands")

    assert "setpointRangesByModel: {}" in state_js
    assert "state.setpointRangesByModel = payload.setpoint_ranges_by_model_id || {};" in load_commands


def test_static_device_options_popover_behavior():
    _html, app_js, _styles_css = read_static_texts()
    device_resource_js = read_static_javascript("device-resource.js")
    bind = extract_js_function(app_js, "bind")
    options = extract_js_function(device_resource_js, "setDeviceOptionsExpanded")
    supported = extract_js_function(device_resource_js, "setSupportedDevicesExpanded")

    assert "panel.hidden = !expanded;" in options
    assert "panel.hidden = !expanded;" in supported
    assert 'button.setAttribute("aria-expanded", String(expanded));' in options
    assert 'document.getElementById("device-options-toggle").addEventListener("click", (event) => {' in bind
    assert 'setDeviceOptionsExpanded(document.getElementById("device-options-toggle").getAttribute("aria-expanded") !== "true");' in bind
    assert 'document.getElementById("supported-devices-toggle")?.addEventListener("click", (event) => {' in bind
    assert 'setSupportedDevicesExpanded(document.getElementById("supported-devices-toggle").getAttribute("aria-expanded") !== "true");' in bind
    assert "setSupportedDevicesExpanded(false);" in bind
    assert 'document.addEventListener("click", () => {' in bind
    assert 'document.addEventListener("keydown", (event) => {' in bind

    keydown_block = bind[bind.index('document.addEventListener("keydown", (event) => {'):]
    assert 'event.key === "Escape"' in keydown_block or 'event.key !== "Escape"' in keydown_block
    assert "setDeviceOptionsExpanded(false);" in keydown_block
    assert "setSupportedDevicesExpanded(false);" in keydown_block
    assert ".focus();" in keydown_block
    assert "renderSupportedDevices" in device_resource_js

    panel_click = bind[
        bind.index('document.getElementById("device-options-panel")'):
        bind.index('document.getElementById("toggle-device-resource")')
    ]
    assert "event.stopPropagation();" in panel_click


def test_static_device_resource_collapse_behavior():
    _html, app_js, _styles_css = read_static_texts()
    bind = extract_js_function(app_js, "bind")
    collapse = extract_js_function(app_js, "setDeviceResourceExpanded")

    assert "body.hidden = !expanded;" in collapse
    assert 'button.textContent = expanded ? "-" : "+";' in collapse
    assert 'button.setAttribute("aria-expanded", String(expanded));' in collapse
    assert 'document.getElementById("toggle-device-resource").addEventListener("click", () => {' in bind
    assert 'setDeviceResourceExpanded(document.getElementById("toggle-device-resource").getAttribute("aria-expanded") !== "true");' in bind


def test_static_top_bar_uses_live_resource_defaults():
    index_html, app_js, _styles_css = read_static_texts()

    assert_static_id(index_html, "resource")
    assert 'id="resource" value=' not in index_html
    assert 'id="resource" value="USB0::SIM::E36312A::INSTR"' not in index_html
    assert_static_id(index_html, "resource-select")
    assert_static_id(index_html, "scan")
    assert '<span data-i18n="app.unofficial_tool">Unofficial Tool</span> v__WEBUI_VERSION__' in index_html
    assert_static_id(index_html, "server-state")
    assert_static_id(index_html, "device-state")
    assert_static_id(index_html, "live-state")
    assert "Server State:" not in index_html
    assert "Device State:" not in index_html
    assert 'id="health"' not in index_html
    assert '<span id="health">checking</span>' not in index_html

    assert 'resource: valueOrNull("resource")' in app_js
    assert 'resource: document.getElementById("resource").value' not in app_js
    assert "simulate: false" in app_js
    assert "dry_run: false" in app_js
    assert "timeout_ms: 5000" in app_js
    assert "backend: null" in app_js
    assert "safety_config: null" in app_js


def test_static_resource_selection_refreshes_selected_context():
    index_html, app_js, _styles_css = read_static_texts()
    sync_selected = extract_js_function(app_js, "syncSelectedResource")
    refresh_preview = extract_js_function(app_js, "refreshSelectedResourcePreview")

    assert_static_id(index_html, "resource")
    assert_static_id(index_html, "resource-select")
    assert 'document.getElementById("resource-select").addEventListener("change", syncSelectedResource);' in app_js

    assert "const input = document.getElementById(\"resource\");" in sync_selected
    assert "const previous = input.value;" in sync_selected
    assert "const value = document.getElementById(\"resource-select\").value;" in sync_selected
    assert "input.value = value;" in sync_selected
    assert "if (value !== previous) await refreshSelectedResourceContext(value);" in sync_selected

    assert "webuiApi.fetchJson(\"/api/live\"" not in refresh_preview
    assert "stopLivePreviewSnapshot();" in refresh_preview
    assert "renderBlankLivePanel();" in refresh_preview
    assert "if (!resource)" in refresh_preview
    assert (
        'setLiveState(t("live_data.status.not_monitoring"), "state-idle", '
        't("live_data.status.no_resource"));'
    ) in refresh_preview
    assert "const healthState = await refreshHealth();" in refresh_preview
    assert 'if (resource !== valueOrNull("resource")) return;' in refresh_preview
    assert "await startLivePreviewSnapshot(healthState, resource);" in refresh_preview
    assert refresh_preview.index("stopLivePreviewSnapshot();") < refresh_preview.index("renderBlankLivePanel();")
    assert refresh_preview.index("renderBlankLivePanel();") < refresh_preview.index("const healthState = await refreshHealth();")
    assert refresh_preview.index("const healthState = await refreshHealth();") < refresh_preview.index(
        'if (resource !== valueOrNull("resource")) return;'
    )
    assert refresh_preview.index('if (resource !== valueOrNull("resource")) return;') < refresh_preview.index(
        "await startLivePreviewSnapshot(healthState, resource);"
    )


def test_static_state_indicators_show_webui_command_and_live_state():
    index_html, app_js, _styles_css = read_static_texts()
    live_data_js = read_static_javascript("live-data.js")
    refresh_health = extract_js_function(app_js, "refreshHealth")
    preview = extract_js_function(live_data_js, "startLivePreviewSnapshot")
    stop_live = extract_js_function(live_data_js, "stopLive")
    monitor_button = extract_js_function(app_js, "updateLiveMonitorButton")

    for hook in ('class="state-dot"', 'class="state-text"', 'class="state-indicator'):
        assert hook in index_html
    assert (
        '<span class="state-text" data-i18n="live_data.status.not_monitoring">'
        "Not monitoring</span>"
    ) in index_html

    assert "state.health =" in refresh_health
    assert "refreshHealthPresentation();" in refresh_health
    health_presentation = extract_js_function(app_js, "refreshHealthPresentation")
    assert '"server-state"' in health_presentation
    assert '"device-state"' in health_presentation
    assert "health.status.ready" in health_presentation
    assert "health.status.busy" in health_presentation
    assert "health.status.unknown" in health_presentation

    assert 'setLiveState(t("live_data.status.refreshing_once"), "state-warning"' in preview
    assert 'setLiveState(t("live_data.status.refresh_blocked"), "state-error"' in preview
    assert 'setLiveState(t("live_data.status.not_monitoring"), "state-idle"' in stop_live
    assert 'button.textContent = t(monitoring ? "live_data.action.stop_monitor" : "live_data.action.start_monitor");' in monitor_button
    assert 'button.setAttribute("aria-pressed", String(monitoring));' in monitor_button
    assert 'button.classList.toggle("on", monitoring);' in monitor_button


def test_scan_resources_handles_missing_live_only_checkbox():
    _index_html, app_js, _styles_css = read_static_texts()
    live_data_js = read_static_javascript("live-data.js")

    assert 'command: "list-resources"' in app_js
    assert "parameters: { live_only: true }" in app_js
    assert 'webuiApi.fetchJson("/api/jobs", { method: "POST", body: JSON.stringify(payload) })' in app_js
    assert 'fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) })' in live_data_js
    assert 'fetchJson(`/api/live/${jobId}/stop`, { method: "POST" })' in live_data_js
    assert 'selectCommand("list-resources")' not in app_js
    assert 'const liveOnly = document.getElementById("param-live_only")' not in app_js
    assert 'document.getElementById("param-live_only").checked = true' not in app_js


def test_static_finished_real_command_refreshes_live_snapshot():
    _index_html, app_js, _styles_css = read_static_texts()
    jobs_js = read_static_javascript("jobs.js")
    live_data_js = read_static_javascript("live-data.js")
    refresh = extract_js_function(app_js, "shouldRefreshLiveAfterCommand")
    preview = extract_js_function(live_data_js, "startLivePreviewSnapshot")
    fresh_preview = extract_js_function(live_data_js, "isFreshLivePreviewSample")

    assert 'fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) })' in live_data_js
    assert 'fetchJson(`/api/live/${jobId}/stop`, { method: "POST" })' in live_data_js
    assert "job.runtime.resource" in jobs_js
    assert "runtime.simulate === false" in refresh
    assert "runtime.dry_run === false" in refresh
    assert "!state.liveEvents" not in refresh
    assert "state.liveEvents" not in preview
    assert 'closeEventSource("liveEvents")' not in preview
    assert 'setLiveState(t("live_data.status.refreshing_once"), "state-warning"' in preview
    assert "handledFreshSample" in preview
    assert "handledFirstSample" not in preview
    assert "renderLivePanel(sample);" in preview
    assert "if (!isFreshLivePreviewSample(sample)) return;" in preview
    assert "sample.stale === false" in fresh_preview
    assert 'sample.status !== "busy"' in fresh_preview
    assert 'sample.status !== "error"' in fresh_preview
    assert "Array.isArray(sample.channels)" in fresh_preview
    assert 'stopLivePreviewSnapshot();\n  setLiveState("Not monitoring"' not in preview


def test_static_live_data_uses_three_channel_panel_contract():
    index_html, app_js, _styles_css = read_static_texts()
    live_data_js = read_static_javascript("live-data.js")

    assert 'id="live-cards"' in index_html
    for channel in ("1", "2", "3"):
        assert f'data-channel-card="{channel}"' in index_html
    assert 'id="live-table"' not in index_html

    start_live = extract_js_function(live_data_js, "startLive")
    stop_live = extract_js_function(live_data_js, "stopLive")
    wait_for_terminal = extract_js_function(live_data_js, "waitForLiveTerminal")
    assert 'parameters: { interval_ms: 5000 }' in start_live
    assert 'class="live-data-note"' in index_html
    assert "Live Data monitor" in index_html
    assert "5 seconds" in index_html
    assert "Successful real hardware commands" in index_html
    assert 'read_command: "measure-all"' not in start_live
    assert 'channel: "all"' not in start_live
    assert 'if (!payload.runtime.resource)' in start_live
    assert 'simulate: true' not in start_live
    assert 'fetchJson("/api/live", { method: "POST"' in start_live
    for event_type in ("progress", "finished", "failed"):
        assert f'addEventListener("{event_type}"' in start_live
    assert 'fetchJson(`/api/live/${jobId}/stop`, { method: "POST" })' in stop_live
    assert "await waitForLiveTerminal(jobId);" in stop_live
    assert "Date.now() + 15000" in wait_for_terminal
    assert 'fetchJson(`/api/jobs/${jobId}`)' in wait_for_terminal
    assert 'document.getElementById("live-start").addEventListener("click", toggleLiveMonitor);' in app_js
    assert "webuiLiveData.createLiveDataController({" in app_js
    assert "var { startLive, toggleLiveMonitor, stopLive, startLivePreviewSnapshot, isFreshLivePreviewSample, waitForLiveTerminal } = liveDataController;" in app_js
    assert "sameResource ? previous?.channels : []" in app_js
    assert "Boolean(data.stale && sameResource)" in app_js
    for field in (
        "output_enabled",
        "measured_voltage",
        "measured_current",
        "set_voltage",
        "set_current",
        "over_voltage_tripped",
        "over_current_tripped",
        "protection_tripped",
        "over_voltage_protection_level",
        "over_current_protection_enabled",
        "stale",
        "error",
    ):
        assert field in app_js or field in live_data_js


def test_static_live_data_exposes_start_control():
    index_html, app_js, _styles_css = read_static_texts()

    assert_static_attr(index_html, "live-start", "type", "button")
    assert_static_attr(index_html, "live-start", "aria-pressed", "false")
    assert 'id="live-stop"' not in index_html
    assert 'document.getElementById("live-start").addEventListener("click", toggleLiveMonitor);' in app_js
    assert 'document.getElementById("live-stop")' not in app_js


def test_static_layout_exposes_stable_structural_hooks():
    index_html, _app_js, _styles_css = read_static_texts()
    for element_id in (
        "basic-command",
        "advanced-command-toggle",
        "advanced-commands",
        "command-categories",
        "command-list",
        "job-result-panel",
        "job-history",
        "result-panel",
        "job-result-clear",
        "job-result-toggle",
        "result-toggle",
        "command-form",
        "workspace-summary-content",
    ):
        assert_static_id(index_html, element_id)
    assert_static_attr(index_html, "advanced-commands", "hidden")
    assert 'class="rightbar"' not in index_html


def test_static_basic_command_panel_contract():
    index_html, app_js, _styles_css = read_static_texts()

    assert_static_id(index_html, "basic-command")
    assert_static_id(index_html, "basic-command-status")
    assert 'data-basic-all-output' in index_html
    assert_static_attr(index_html, "advanced-command-toggle", "aria-controls", "advanced-commands")
    assert_static_attr(index_html, "advanced-command-toggle", "aria-expanded", "false")
    assert 'data-i18n="basic_controls.action.show_more_commands"' in index_html
    assert index_html.count('data-i18n="basic_controls.action.set"') == 3
    assert index_html.count('data-i18n-aria-label="basic_controls.aria.e3646a_global_output_information"') == 2
    assert index_html.count('data-i18n-title="basic_controls.help.e3646a_global_output"') == 2
    assert 'panel.hidden = !expanded;' in app_js

    for channel in ("1", "2", "3"):
        assert f'data-basic-channel="{channel}"' in index_html
        assert f'data-basic-voltage="{channel}"' in index_html
        assert f'data-basic-current="{channel}"' in index_html
        assert f'data-basic-set="{channel}"' in index_html
        assert f'data-basic-output="{channel}"' in index_html


def test_static_basic_output_buttons_label_next_action_and_use_lit_state():
    index_html, _app_js, _styles_css = read_static_texts()
    basic_controls_js = read_static_javascript("basic-controls.js")
    output_button = extract_js_function(basic_controls_js, "renderBasicOutputButton")
    all_button = extract_js_function(basic_controls_js, "renderBasicAllOutputButton")

    assert 'data-i18n="basic_controls.output.on_control">Turn on</button>' in index_html
    assert 'data-i18n="basic_controls.output.all_on_control">Turn all on</button>' in index_html
    assert 'button.textContent = t(enabled ? "basic_controls.output.off_control" : "basic_controls.output.on_control");' in output_button
    assert 'button.textContent = t(globalState === "on" ? "basic_controls.output.all_off_control" : "basic_controls.output.all_on_control");' in all_button
    assert 'button.textContent = t(allOn ? "basic_controls.output.all_off_control" : "basic_controls.output.all_on_control");' in all_button
    assert 'button.textContent = enabled ? "ON" : "OFF";' not in output_button
    assert 'button.textContent = allOn ? "All ON" : "All OFF";' not in all_button
    assert 'button.classList.toggle("on", enabled);' in output_button
    assert 'button.classList.toggle("off", !enabled);' in output_button
    assert 'button.classList.toggle("on", allOn);' in all_button
    assert 'button.classList.toggle("off", !allOn);' in all_button


def test_static_basic_output_buttons_lock_until_matching_readback():
    _index_html, app_js, _styles_css = read_static_texts()
    basic_controls_js = read_static_javascript("basic-controls.js")
    set_action = extract_js_function(basic_controls_js, "setBasicActionState")
    run_output = extract_js_function(app_js, "runBasicOutput")
    run_all = extract_js_function(app_js, "runBasicOutputAll")
    update_basic = extract_js_function(basic_controls_js, "updateBasicActionFromJob")
    render_states = extract_js_function(basic_controls_js, "renderBasicOutputActionStates")
    render_control = extract_js_function(basic_controls_js, "renderBasicOutputControlState")
    lock_action = extract_js_function(basic_controls_js, "basicOutputLockAction")
    clear_resolved = extract_js_function(basic_controls_js, "clearResolvedBasicErrors")
    render_channel = extract_js_function(basic_controls_js, "renderBasicChannelActionState")

    assert "presentation:" in set_action
    assert "rawMessage:" in set_action
    assert "basicActionMessage(state.basicActionStates[actionKey])" in set_action
    assert 'state.basicActionStates[actionKey] = { status, message, ...context };' not in set_action
    assert 'if (basicOutputLockAction(channel)) return;' in run_output
    assert 'if (basicOutputLockAction("all")) return;' in run_all
    assert 'awaitingReadback: true' in update_basic
    assert 'setBasicActionState(action.actionKey, "pending"' in update_basic
    assert 'button.disabled = Boolean(unsupported || lockAction || commandMetaForState.disabled);' in render_control
    assert 'button.classList.toggle("basic-action-pending", Boolean(lockAction));' in render_control
    assert 'defaultChannels.forEach((channel) => renderBasicOutputControlState(channel));' in render_states
    assert 'renderBasicOutputControlState("all");' in render_states
    assert 'const allAction = state.basicActionStates[basicActionKey("output", "all")];' in lock_action
    assert 'if (allAction?.status === "pending") return allAction;' in lock_action
    assert 'target === "all"' in lock_action
    assert 'state.basicActionStates[basicActionKey("output", channel)]' in lock_action
    assert 'setBasicActionState(outputKey, "success"' in clear_resolved
    assert 'setBasicActionState(basicActionKey("output", "all"), "success"' in clear_resolved
    assert "outputAction" in clear_resolved
    assert "allAction" in clear_resolved
    assert 'allOutputState === "pending"' in render_channel
