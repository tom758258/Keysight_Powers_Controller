"""Native-module contracts for Device/Resource presentation helpers."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_device_resource_module_owns_controller_and_app_imports_it() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    device_js = read_static_javascript("device-resource.js")

    assert 'from "./device-resource.js"' in app_js
    assert "export function createDeviceResourceController" in device_js
    assert 'document.getElementById("device-options-panel")' in device_js
    assert "fetch(" not in device_js
    assert "new EventSource" not in device_js


def test_device_module_preserves_resource_and_identity_presentation() -> None:
    run_webui_module_assertions(
        r"""
const device = globalThis.webuiDevice;
const models = [{ model_id: "keysight-e36312a", display_name: "Keysight E36312A" }];
strictAssert.match(device.physicalModelDisplayName(models, "keysight-e36312a"), /E36312A/);
strictAssert.notEqual(device.physicalModelDisplayName(models, ""), "");
strictAssert.notEqual(device.planningIdentitySummary({ executionMode: "simulate", planningProfiles: {}, physicalModels: models }, ""), "");
strictAssert.match(device.planningIdentitySummary({ executionMode: "dry-run", planningProfiles: { generic: { display_name: "Generic SCPI" } }, physicalModels: models }, "profile:generic"), /Generic SCPI/);
for (const status of ["not_scanned", "results", "empty"]) {
  strictAssert.notEqual(device.liveResourceSummary({}, "USB0::A", { status, resources: [], detail: "" }), "");
}
strictAssert.notEqual(device.liveResourceSummary({}, "USB0::A", { status: "results", resources: ["USB0::A"], detail: "" }), "");
strictAssert.notEqual(device.liveResourceSummary({}, "USB0::A", { status: "failed", resources: [], detail: "raw VISA failure" }), "");
strictAssert.match(device.liveResourceSummary({ "USB0::A": "E36312A" }, "USB0::A", { status: "results", resources: ["USB0::A"] }), /USB0::A|E36312A/);
strictAssert.match(device.resourceLabel({ idn: { manufacturer: "Keysight", model: "E36312A" } }, "USB0::A"), /USB0::A/);
strictAssert.match(device.resourceLabel({ idn: { manufacturer: "Keysight", model: "E36312A" } }, "USB0::A"), /Keysight|E36312A/);
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("device-resource.js",),
    )


def test_device_resource_presentation_supports_both_locales_and_preserves_values() -> None:
    run_webui_module_assertions(
        r"""
const i18n = await import(new URL("./i18n.js", moduleUrls["device-resource.js"]));
const device = globalThis.webuiDevice;
const state = {
  executionMode: "simulate",
  planningProfiles: { "generic-scpi": { display_name: "Generic SCPI" } },
  physicalModels: [{ model_id: "keysight-e36312a", display_name: "Keysight E36312A" }]
};
const scan = { status: "results", resources: ["USB0::RAW::INSTR"], detail: "" };
const englishPlanning = device.planningIdentitySummary(state, "keysight-e36312a");
const englishLive = device.liveResourceSummary({}, "USB0::RAW::INSTR", scan);
strictAssert.match(englishPlanning, /Keysight E36312A/);
strictAssert.notEqual(englishLive, "");
i18n.setLocale("zh-TW");
strictAssert.notEqual(device.planningIdentitySummary(state, "keysight-e36312a"), englishPlanning);
strictAssert.match(device.planningIdentitySummary(state, "keysight-e36312a"), /Keysight E36312A/);
strictAssert.match(device.planningIdentitySummary({ ...state, executionMode: "dry-run" }, "profile:generic-scpi"), /Generic SCPI/);
strictAssert.notEqual(device.liveResourceSummary({}, "USB0::RAW::INSTR", scan), englishLive);
strictAssert.notEqual(device.liveResourceSummary({}, "USB0::RAW::INSTR", scan), "");
strictAssert.deepEqual(scan, { status: "results", resources: ["USB0::RAW::INSTR"], detail: "" });
i18n.setLocale("en");
""",
        ("device-resource.js",),
    )


def test_presentation_refreshes_do_not_enter_state_changing_paths() -> None:
    device_js = read_static_javascript("device-resource.js")
    command_js = read_static_javascript("command-form.js")
    device_refresh = device_js[
        device_js.index("function refreshDeviceResourcePresentation()"):
        device_js.index("function setStateIndicator(")
    ]
    command_refresh = command_js[
        command_js.index("function refreshCommandPresentation()"):
        command_js.index("function updatePulseChildVisibility(")
    ]

    for forbidden in ("fetchJson(", "updateExecutionModeUi(", "populateIdentitySelector(", "selectCommand("):
        assert forbidden not in device_refresh
    for forbidden in ("fetchJson(", "selectCommand(", "renderForm(", "new EventSource"):
        assert forbidden not in command_refresh


def test_device_controller_native_module_owns_state_and_e3646a_constants() -> None:
    run_webui_module_assertions(
        r"""
const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    const classes = new Set(["state-warning"]);
    elements.set(id, {
      id,
      title: "",
      textContent: "",
      children: [],
      attributes: {},
      disabled: false,
      hidden: false,
      setAttribute(name, value) { this.attributes[name] = String(value); },
      getAttribute(name) { return this.attributes[name] ?? null; },
      classList: {
        add(name) { classes.add(name); },
        toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
        contains(name) { return classes.has(name); }
      },
      querySelector(selector) { return this.children.find((child) => child.selector === selector) || null; },
      append(...children) { this.children.push(...children); }
    });
  }
  return elements.get(id);
}
globalThis.document = {
  getElementById: element,
  querySelector(selector) { return selector === ".device-resource-section" ? element("device-resource-section") : null; },
  querySelectorAll(selector) { return selector === 'input[name="execution-mode"]' ? radios : []; },
  createElement() {
    return {
      selector: "",
      className: "",
      textContent: "",
      setAttribute() {},
      set className(value) { this._className = value; this.selector = value === "state-dot" ? ".state-dot" : value === "state-text" ? ".state-text" : ""; },
      get className() { return this._className; }
    };
  }
};
const radios = [{ title: "", disabled: false }, { title: "", disabled: true }, { title: "", disabled: false }];
const state = {
  executionMode: "simulate",
  planningIdentityCache: { simulate: "keysight-e3646a", "dry-run": "" },
  realIdentityCache: { expectedModelId: "" },
  resourceModels: {},
  resourceChannelModels: {},
  physicalModels: [],
  channelCapabilitiesByModel: {},
  jobs: [],
  basicActionStates: {},
  workflowControl: { phase: "idle" }
};
let fetchCalls = 0;
const capability = { output_control_scope: "global", channels: [1, 2] };
const controller = webuiDevice.createDeviceResourceController({
  state,
  devicePresentation: webuiDevice,
  executionContext: { isNoHardwareExecutionMode: (mode) => mode !== "real" },
  fetchJson: async () => { fetchCalls += 1; throw new Error("presentation refresh fetched"); },
  valueOrNull: (id) => id === "expected-model-id" ? state.planningIdentityCache.simulate : null,
  channelCapabilityForModel: (model) => model === "keysight-e3646a" ? capability : null
});
const i18n = await import(new URL("./i18n.js", moduleUrls["device-resource.js"]));
controller.setStateIndicator("status", "Ready", "state-ok", "Ready title");
const indicator = element("status");
strictAssert.equal(indicator.classList.contains("state-ok"), true);
strictAssert.equal(indicator.classList.contains("state-warning"), false);
strictAssert.notEqual(indicator.querySelector(".state-text").textContent, "");
strictAssert.equal(indicator.title, "Ready title");
state.health = { status: "not_loaded", readiness: null, hardwareLocked: null, activeJob: null, detail: "" };
controller.refreshHealthPresentation();
strictAssert.notEqual(element("server-state").querySelector(".state-text").textContent, "");
strictAssert.equal(element("server-state").classList.contains("state-warning"), true);
strictAssert.notEqual(element("device-state").querySelector(".state-text").textContent, "");
strictAssert.equal(element("device-state").classList.contains("state-idle"), true);
state.health = { status: "loaded", readiness: "ok", hardwareLocked: false, activeJob: null, detail: "" };
controller.refreshHealthPresentation();
strictAssert.notEqual(element("server-state").querySelector(".state-text").textContent, "");
strictAssert.notEqual(element("device-state").querySelector(".state-text").textContent, "");
state.health = { status: "loaded", readiness: "ok", hardwareLocked: true, activeJob: "job-raw-42", detail: "" };
controller.refreshHealthPresentation();
strictAssert.notEqual(element("server-state").querySelector(".state-text").textContent, "");
strictAssert.notEqual(element("device-state").querySelector(".state-text").textContent, "");
strictAssert.match(element("device-state").title, /job-raw-42/);
state.health = { status: "loaded", readiness: "starting", hardwareLocked: false, activeJob: null, detail: "" };
controller.refreshHealthPresentation();
strictAssert.notEqual(element("server-state").querySelector(".state-text").textContent, "");
strictAssert.match(element("server-state").title, /starting/);
strictAssert.notEqual(element("device-state").querySelector(".state-text").textContent, "");
state.health = { status: "failed", readiness: null, hardwareLocked: null, activeJob: null, detail: "raw backend health failure" };
controller.refreshHealthPresentation();
strictAssert.equal(element("server-state").title, "raw backend health failure");

state.executionModeTransition = true;
const disabledBeforeBusyRefresh = radios.map((radio) => radio.disabled);
controller.refreshExecutionModePresentation();
const englishBusyTitle = radios[0].title;
strictAssert.notEqual(englishBusyTitle, "");
strictAssert.deepEqual(radios.map((radio) => radio.disabled), disabledBeforeBusyRefresh);
i18n.setLocale("zh-TW");
controller.refreshExecutionModePresentation();
strictAssert.notEqual(radios[0].title, "");
strictAssert.notEqual(radios[0].title, englishBusyTitle);
strictAssert.deepEqual(radios.map((radio) => radio.disabled), disabledBeforeBusyRefresh);
state.health = { status: "not_loaded", readiness: null, hardwareLocked: null, activeJob: null, detail: "" };
controller.refreshHealthPresentation();
strictAssert.notEqual(element("server-state").querySelector(".state-text").textContent, "");
strictAssert.notEqual(element("device-state").querySelector(".state-text").textContent, "");
state.executionModeTransition = false;
controller.refreshExecutionModePresentation();
strictAssert.equal(radios[0].title, "");

controller.setDeviceResourceExpanded(true);
const toggle = element("toggle-device-resource");
strictAssert.equal(toggle.getAttribute("aria-expanded"), "true");
strictAssert.notEqual(toggle.getAttribute("aria-label"), "");
const expandedHidden = element("device-resource-body").hidden;
controller.refreshDeviceResourceExpandedPresentation();
strictAssert.equal(element("device-resource-body").hidden, expandedHidden);
strictAssert.equal(toggle.getAttribute("aria-expanded"), "true");
controller.setDeviceResourceExpanded(false);
strictAssert.equal(toggle.getAttribute("aria-expanded"), "false");
const zhCollapsedTitle = toggle.title;
strictAssert.notEqual(zhCollapsedTitle, "");
const collapsedHidden = element("device-resource-body").hidden;
i18n.setLocale("en");
controller.refreshDeviceResourceExpandedPresentation();
strictAssert.notEqual(toggle.title, "");
strictAssert.notEqual(toggle.title, zhCollapsedTitle);
strictAssert.equal(element("device-resource-body").hidden, collapsedHidden);
strictAssert.equal(toggle.getAttribute("aria-expanded"), "false");
strictAssert.equal(fetchCalls, 0);
strictAssert.deepEqual(controller.e3646aGlobalOutputCapability(), capability);
strictAssert.equal(controller.basicOutputPresentation().mode, "e3646a-global");
state.planningIdentityCache.simulate = "keysight-e36312a";
strictAssert.deepEqual(controller.basicOutputPresentation(), { mode: "ordinary", capability: null });
""",
        ("device-resource.js",),
    )


def test_controller_wiring_omits_self_forwarders_and_ignored_properties() -> None:
    app_js = read_static_javascript("app.js")
    device_js = read_static_javascript("device-resource.js")
    command_form_js = read_static_javascript("command-form.js")
    device_wiring = app_js[
        app_js.index("createDeviceResourceController({"):app_js.index("});", app_js.index("createDeviceResourceController({"))
    ]
    command_wiring = app_js[
        app_js.index("createCommandController({"):app_js.index("});", app_js.index("createCommandController({"))
    ]

    for removed in (
        "stateClassNames:",
        "e3646aModelId:",
        "refreshDeviceResourceSummary:",
        "stopLiveJobsBeforeModeChange:",
    ):
        assert removed not in device_wiring

    for removed in (
        "refreshBasicInputConstraintsForForm:",
        "refreshBasicInputConstraints: (...args) => refreshBasicInputConstraints(...args)",
        "commandDisplayName: (...args) => commandDisplayName(...args)",
        "applyParameterConstraintForForm:",
        "applyElectricalRatingConstraintForForm:",
        "enforcePulseFormRulesForForm:",
        "refreshElectricalRatingConstraintsForForm:",
        "renderCurrentForm:",
    ):
        assert removed not in command_wiring

    assert "refreshDeviceResourceSummary," not in device_js
    assert "stopLiveJobsBeforeModeChange," not in device_js
    assert "updateDeviceResourceSummary();" in device_js
    assert "await stopRealLiveJobsAndWait();" in device_js
    assert "refreshBasicInputConstraintsForForm," not in command_form_js
    assert "renderCurrentForm," not in command_form_js
    assert "renderForm(\"ramp-list\");" in command_form_js
    assert "triggerCommands: TRIGGER_COMMANDS" in app_js
    assert "TRIGGER_COMMANDS.has(command)" in command_form_js
    assert all(
        f"{name}:" not in device_wiring + command_wiring
        for name in ("services", "dependencies", "context", "container", "registry", "controllerBag", "callbacks")
    )
