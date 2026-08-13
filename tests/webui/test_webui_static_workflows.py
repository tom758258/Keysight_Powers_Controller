"""Static workflow, capability, workspace, and trigger WebUI tests."""

from __future__ import annotations

import re
import textwrap

from _webui_shared import (
    WEBUI_HIDDEN_LIVE_DATA_COMMANDS,
    assert_param_contract,
    extract_js_function,
    extract_param_block,
    read_static_javascript,
    read_static_texts,
    run_frontend_javascript_assertions,
    run_webui_module_assertions,
)


def test_workflow_factory_wiring_omits_unused_dependencies() -> None:
    app_js = read_static_javascript("app.js")
    workflows_js = read_static_javascript("workflows.js")
    def captured_block(pattern: str, source: str) -> str:
        match = re.search(pattern, source, re.DOTALL)
        assert match is not None
        return match.group("body")

    workflow_wiring = captured_block(
        r"webuiWorkflows\.createWorkflows\(\{(?P<body>.*?)\}\s*\);",
        app_js,
    )
    artifact_wiring = captured_block(
        r"webuiWorkflows\.createArtifactAndSequenceWorkflows\(\{(?P<body>.*?)\}\s*\);",
        app_js,
    )
    workflow_signature = captured_block(
        r"export\s+function\s+createWorkflows\s*\(\s*\{(?P<body>.*?)\}\s*\)\s*\{",
        workflows_js,
    )
    artifact_signature = captured_block(
        r"export\s+function\s+createArtifactAndSequenceWorkflows\s*\(\s*\{(?P<body>.*?)\}\s*\)\s*\{",
        workflows_js,
    )

    for removed in ("defaultRampSegment", "triggerListParams", "commandDisplayName", "params", "normalizeChannelValue"):
        assert f"{removed}:" not in workflow_wiring
        assert removed not in workflow_signature
    assert "normalizeChannelValue:" not in artifact_wiring
    assert "normalizeChannelValue" not in artifact_signature

    for retained in (
        "webuiRampListDocument",
        "webuiTriggerListDocument",
        "openJsonFile",
        "saveJsonFile",
        "pulseTimingDisplayName",
        "pinsSelectValue",
        "applyParameterConstraint",
        "updateWorkflowDocumentValidity",
        "updateRampListPulse",
    ):
        assert retained in workflow_wiring
        assert retained in workflow_signature
    for retained in (
        "rearPinOptions",
        "webuiRestoreDocument",
        "webuiSequenceDocument",
        "applyParameterConstraint",
        "updateWorkflowDocumentValidity",
        "effectiveSequenceLoopCount",
        "restoreSnapshotParameters",
        "submitJob",
        "subscribeToJob",
    ):
        assert retained in artifact_wiring
        assert retained in artifact_signature

    combined = workflow_signature + artifact_signature
    assert all(
        f"{name}," not in combined and f"{name}:" not in combined
        for name in ("services", "dependencies", "context", "container", "registry", "callbacks", "workflowBag")
    )


def test_ramp_list_renderer_uses_explicit_module_dependencies() -> None:
    run_webui_module_assertions(
        r"""
class FakeClassList {
  constructor(owner) { this.owner = owner; }
  add(...names) {
    const values = new Set(this.owner.className.split(/\s+/).filter(Boolean));
    names.forEach((name) => values.add(name));
    this.owner.className = [...values].join(" ");
  }
  contains(name) { return this.owner.className.split(/\s+/).includes(name); }
}

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.className = "";
    this.classList = new FakeClassList(this);
    this.listeners = {};
    this.attributes = {};
    this.textContent = "";
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.hidden = false;
    this.id = "";
  }
  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    return child;
  }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  addEventListener(type, listener) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(listener);
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  querySelector(selector) {
    if (selector === ".checkbox-label-text") {
      return descendants(this).find((node) => node.classList.contains("checkbox-label-text"));
    }
    return undefined;
  }
  querySelectorAll(selector) {
    if (selector === "[data-workflow-i18n]") {
      return descendants(this).filter((node) => node.dataset.workflowI18n);
    }
    if (selector === "[data-workflow-compact-help-description]") {
      return descendants(this).filter((node) => node.dataset.workflowCompactHelpDescription);
    }
    if (selector === "[data-parameter-constraint]") {
      return descendants(this).filter((node) => node.dataset.parameterConstraint);
    }
    return [];
  }
  set innerHTML(value) {
    strictAssert.equal(value, "");
    this.children = [];
  }
}

const elements = new Map();
const descendants = (root) => [root, ...root.children.flatMap((child) => descendants(child))];
const addElement = (id, tagName = "div") => {
  const element = new FakeElement(tagName);
  element.id = id;
  elements.set(id, element);
  return element;
};
addElement("command-filter", "input");
addElement("command-categories");
addElement("command-list");
addElement("selected-command");
const commandForm = addElement("command-form", "form");
globalThis.document = {
  createElement: (tagName) => new FakeElement(tagName),
  getElementById: (id) => elements.get(id) || descendants(commandForm).find((node) => node.id === id),
};

const state = {
  selected: null,
  activeCategory: "workflow",
  commands: { "ramp-list": { category: "workflow" } },
  workflowControl: { phase: "idle" },
  parameterConstraints: {
    start_voltage: { min: 0, step: "any", description: "Finite non-negative starting voltage." },
    stop_voltage: { min: 0, step: "any", description: "Finite non-negative final voltage." },
  },
  electricalRatingsByModel: {},
  rampListSegments: [{
    channels: [2],
    start_voltage: 1.25,
    stop_voltage: 2.5,
    step_voltage: 0.25,
    current: 0.2,
    delay_ms: 50,
  }],
  rampListEnableOutput: true,
  rampListLoopEnabled: false,
  rampListLoopCountDraft: "2",
  rampListCompletionPulse: null,
};
const originalSegments = state.rampListSegments;
const constrainedFields = [];
const validityCalls = [];
let selectedUpdateCount = 0;
let renderFormFromController;
let updateRampListPulseFromController;
let applyParameterConstraintFromController;
let rampListModel = "keysight-e36312a";
const combinationOptions = (channels) => {
  const options = [];
  for (let mask = 1; mask < (1 << channels.length); mask += 1) {
    options.push(channels.filter((_channel, index) => mask & (1 << index)).join(","));
  }
  return options.sort((left, right) => left.split(",").length - right.split(",").length || left.localeCompare(right));
};

const loopControl = ({ prefix }) => {
  const wrapper = new FakeElement("div");
  const label = new FakeElement("label");
  const input = new FakeElement("input");
  input.id = `${prefix}-loop-enabled`;
  label.appendChild(input);
  wrapper.appendChild(label);
  return wrapper;
};
const workflows = globalThis.webuiWorkflows.createWorkflows({
  state,
  rearPinOptions: ["1", "2", "3", "2,3"],
  webuiCommandForm: globalThis.webuiCommandForm,
  webuiRampListDocument: globalThis.webuiRampListDocument,
  renderForm: (...args) => renderFormFromController(...args),
  updateSelectedCommandState: () => {},
  rearPinDisplayName: (value) => value || "None",
  parseRearPins: (value) => String(value).split(",").filter(Boolean).map(Number),
  renderLoopControl: loopControl,
  applyWorkflowPulseControlState: () => {},
  pulseTimingDisplayName: (_command, value) => value || "None",
  pinsSelectValue: (value) => Array.isArray(value) ? value.join(",") : String(value),
  applyParameterConstraint: (input, name) => {
    constrainedFields.push(name);
    input.dataset.constraintApplied = name;
    applyParameterConstraintFromController(input, name);
  },
  supportedChannelsForCurrentModel: () => rampListModel === "keysight-e3646a" ? [1, 2] : [1, 2, 3],
  rampChannelOptions: combinationOptions,
  rampChannelOptionLabel: (value, supported) => value.split(",").length === supported.length && supported.length > 1
    ? "All"
    : value.split(",").map((channel) => `CH${channel}`).join(" + "),
  selectedChannelModel: () => rampListModel,
  updateWorkflowDocumentValidity: (command) => validityCalls.push(command),
  updateRampListPulse: (...args) => updateRampListPulseFromController(...args),
});
const controller = globalThis.webuiCommandForm.createCommandController({
  state,
  commandCatalog: globalThis.webuiCommandCatalog,
  electrical: globalThis.webuiElectrical,
  commandMeta: (name) => state.commands[name] || {},
  renderWorkspaceSummary: () => {},
  prefillClearProtectionChannel: () => {},
  updateSelectedCommandState: () => { selectedUpdateCount += 1; },
  renderRampListForm: workflows.renderRampListForm,
});
renderFormFromController = controller.renderForm;
updateRampListPulseFromController = controller.updateRampListPulse;
applyParameterConstraintFromController = controller.applyParameterConstraint;

strictAssert.doesNotThrow(() => controller.selectCommand("ramp-list"));
strictAssert.equal(state.selected, "ramp-list");
strictAssert.equal(commandForm.children.length, 1);
const editor = commandForm.children[0];
const findClass = (name) => descendants(editor).filter((node) => node.classList.contains(name));
strictAssert.equal(findClass("ramp-list-toolbar").length, 1);
strictAssert.deepEqual(
  findClass("ramp-list-toolbar")[0].children.map((button) => button.textContent),
  ["Load Ramp List", "Save Ramp List", "Add Ramp Segment"],
);
strictAssert.ok(descendants(editor).some((node) => node.id === "ramp-list-enable-output"));
strictAssert.ok(descendants(editor).some((node) => node.id === "ramp-list-loop-enabled"));
strictAssert.ok(descendants(editor).some((node) => node.id === "ramp-list-pulse-timing"));
strictAssert.equal(findClass("ramp-segment-card").length, 1);
strictAssert.deepEqual(
  constrainedFields,
  globalThis.webuiRampListDocument.rampSegmentDefinitions().map((definition) => definition.name).filter((name) => name !== "channels"),
);
const channelSelect = descendants(editor).find((node) => node.dataset.rampField === "channels");
strictAssert.deepEqual(channelSelect.children.map((option) => [option.value, option.textContent]), [
  ["1", "CH1"], ["2", "CH2"], ["3", "CH3"], ["1,2", "CH1 + CH2"],
  ["1,3", "CH1 + CH3"], ["2,3", "CH2 + CH3"], ["1,2,3", "All"]
]);
strictAssert.equal(descendants(editor).some((node) => node.id === "ramp-list-e3646a-output-note"), false);
rampListModel = "keysight-e3646a";
controller.renderForm("ramp-list");
const e3646aEditor = commandForm.children[0];
const twoChannelSelect = descendants(e3646aEditor).find((node) => node.dataset.rampField === "channels");
strictAssert.deepEqual(twoChannelSelect.children.map((option) => [option.value, option.textContent]), [
  ["1", "CH1"], ["2", "CH2"], ["1,2", "All"]
]);
strictAssert.ok(descendants(e3646aEditor).some((node) => node.id === "ramp-list-e3646a-output-note"));
rampListModel = "keysight-e36312a";
strictAssert.deepEqual(validityCalls, ["ramp-list", "ramp-list"]);
strictAssert.ok(descendants(editor).find((node) => node.dataset.rampField === "start_voltage").dataset.constraintApplied);

controller.renderForm("ramp-list");
strictAssert.equal(state.rampListSegments, originalSegments);
strictAssert.equal(state.rampListSegments[0].start_voltage, 1.25);
strictAssert.deepEqual(validityCalls, ["ramp-list", "ramp-list", "ramp-list"]);

const pulseInput = (name) => descendants(commandForm).find(
  (node) => node.id === `ramp-list-pulse-${name}`
);
const selectedUpdatesBeforePulse = selectedUpdateCount;
strictAssert.equal(state.rampListCompletionPulse, null);
let timingInput = pulseInput("timing");
timingInput.value = "segment";
strictAssert.doesNotThrow(() => timingInput.listeners.change[0]());
strictAssert.deepEqual(state.rampListCompletionPulse, {
  timing: "segment",
  pins: [1],
  polarity: "positive",
});

const pinsInput = pulseInput("pins");
pinsInput.value = "2,3";
strictAssert.doesNotThrow(() => pinsInput.listeners.change[0]());
strictAssert.deepEqual(state.rampListCompletionPulse, {
  timing: "segment",
  pins: [2, 3],
  polarity: "positive",
});

const polarityInput = pulseInput("polarity");
polarityInput.value = "negative";
strictAssert.doesNotThrow(() => polarityInput.listeners.change[0]());
strictAssert.deepEqual(state.rampListCompletionPulse, {
  timing: "segment",
  pins: [2, 3],
  polarity: "negative",
});

timingInput = pulseInput("timing");
timingInput.value = "";
strictAssert.doesNotThrow(() => timingInput.listeners.change[0]());
strictAssert.equal(state.rampListCompletionPulse, null);
strictAssert.equal(selectedUpdateCount - selectedUpdatesBeforePulse, 4);
const stopVoltageInput = descendants(commandForm).find((node) => node.dataset.rampField === "stop_voltage");
const startVoltageInput = descendants(commandForm).find((node) => node.dataset.rampField === "start_voltage");
strictAssert.equal(stopVoltageInput.title, "Finite non-negative final voltage.");
const stopVoltagePresentationState = {
  value: stopVoltageInput.value,
  min: stopVoltageInput.min,
  max: stopVoltageInput.max,
  step: stopVoltageInput.step,
  required: stopVoltageInput.required,
  disabled: stopVoltageInput.disabled,
  listeners: Object.fromEntries(
    Object.entries(stopVoltageInput.listeners).map(([name, listeners]) => [name, listeners.length]),
  ),
};

const i18n = await import(new URL("./i18n.js", moduleUrls["command-catalog.js"]));
i18n.setLocale("zh-TW");
let localizedEditor = commandForm.children[0];
globalThis.webuiWorkflows.refreshWorkflowPresentation(localizedEditor);
controller.refreshParameterConstraintPresentation(localizedEditor);
strictAssert.equal(
  descendants(localizedEditor).find((node) => node.dataset.rampField === "stop_voltage"),
  stopVoltageInput,
);
strictAssert.equal(stopVoltageInput.title, "停止電壓必須為有限值且不得小於 0。");
strictAssert.equal(startVoltageInput.title, "有限且非負的起始電壓。");
strictAssert.deepEqual({
  value: stopVoltageInput.value,
  min: stopVoltageInput.min,
  max: stopVoltageInput.max,
  step: stopVoltageInput.step,
  required: stopVoltageInput.required,
  disabled: stopVoltageInput.disabled,
  listeners: Object.fromEntries(
    Object.entries(stopVoltageInput.listeners).map(([name, listeners]) => [name, listeners.length]),
  ),
}, stopVoltagePresentationState);
strictAssert.equal(state.rampListSegments, originalSegments);
i18n.setLocale("en");
globalThis.webuiWorkflows.refreshWorkflowPresentation(localizedEditor);
controller.refreshParameterConstraintPresentation(localizedEditor);
strictAssert.equal(
  descendants(localizedEditor).find((node) => node.dataset.rampField === "stop_voltage"),
  stopVoltageInput,
);
strictAssert.equal(stopVoltageInput.title, "Finite non-negative final voltage.");
strictAssert.deepEqual({
  value: stopVoltageInput.value,
  min: stopVoltageInput.min,
  max: stopVoltageInput.max,
  step: stopVoltageInput.step,
  required: stopVoltageInput.required,
  disabled: stopVoltageInput.disabled,
  listeners: Object.fromEntries(
    Object.entries(stopVoltageInput.listeners).map(([name, listeners]) => [name, listeners.length]),
  ),
}, stopVoltagePresentationState);
strictAssert.equal(state.rampListSegments, originalSegments);
i18n.setLocale("zh-TW");
globalThis.webuiWorkflows.refreshWorkflowPresentation(localizedEditor);
controller.refreshParameterConstraintPresentation(localizedEditor);
let localizedToolbar = descendants(localizedEditor).find((node) => node.classList.contains("ramp-list-toolbar"));
strictAssert.deepEqual(
  localizedToolbar.children.map((button) => button.textContent),
  ["載入多段逐步輸出", "儲存多段逐步輸出", "新增逐步輸出區段"],
);
strictAssert.equal(
  descendants(localizedEditor).find((node) => node.classList.contains("ramp-segment-head")).children[0].textContent,
  "逐步輸出區段 1",
);
strictAssert.doesNotThrow(() => localizedToolbar.children[2].listeners.click[0]());
localizedEditor = commandForm.children[0];
strictAssert.equal(state.rampListSegments.length, 2);
strictAssert.deepEqual(
  descendants(localizedEditor)
    .filter((node) => node.classList.contains("ramp-segment-head"))
    .map((head) => head.children[0].textContent),
  ["逐步輸出區段 1", "逐步輸出區段 2"],
);
i18n.setLocale("en");
globalThis.webuiWorkflows.refreshWorkflowPresentation(localizedEditor);
controller.refreshParameterConstraintPresentation(localizedEditor);
localizedToolbar = descendants(localizedEditor).find((node) => node.classList.contains("ramp-list-toolbar"));
strictAssert.equal(localizedToolbar.children[2].textContent, "Add Ramp Segment");
strictAssert.deepEqual(
  descendants(localizedEditor)
    .filter((node) => node.classList.contains("ramp-segment-head"))
    .map((head) => head.children[0].textContent),
  ["Ramp Segment 1", "Ramp Segment 2"],
);
""",
        (
            "command-catalog.js",
            "command-form.js",
            "electrical.js",
            "ramp-list.js",
            "trigger-list.js",
            "workflows.js",
        ),
    )


def test_ramp_form_preserves_page_local_draft_across_reselection() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");

        class FakeClassList {
          constructor(owner) { this.owner = owner; }
          values() { return new Set(this.owner.className.split(/\s+/).filter(Boolean)); }
          add(...names) {
            const values = this.values();
            names.forEach((name) => values.add(name));
            this.owner.className = [...values].join(" ");
          }
          contains(name) { return this.values().has(name); }
          toggle(name, force) {
            const values = this.values();
            const enabled = force === undefined ? !values.has(name) : Boolean(force);
            if (enabled) values.add(name);
            else values.delete(name);
            this.owner.className = [...values].join(" ");
            return enabled;
          }
        }

        class FakeElement {
          constructor(tagName) {
            this.tagName = tagName.toUpperCase();
            this.children = [];
            this.parentNode = null;
            this.dataset = {};
            this.className = "";
            this.classList = new FakeClassList(this);
            this.listeners = {};
            this.attributes = {};
            this.textContent = "";
            this.value = "";
            this.checked = false;
            this.disabled = false;
            this.hidden = false;
            this.id = "";
            this.type = "";
          }
          get options() { return this.tagName === "SELECT" ? this.children : undefined; }
          get firstChild() { return this.children[0] || null; }
          appendChild(child) {
            this.children.push(child);
            child.parentNode = this;
            return child;
          }
          append(...children) { children.forEach((child) => this.appendChild(child)); }
          addEventListener(type, listener) {
            if (!this.listeners[type]) this.listeners[type] = [];
            this.listeners[type].push(listener);
          }
          dispatch(type) {
            for (const listener of this.listeners[type] || []) listener({ target: this });
          }
          setAttribute(name, value) {
            this.attributes[name] = String(value);
            if (name === "id") this.id = String(value);
          }
          getAttribute(name) { return this.attributes[name] ?? null; }
          hasAttribute(name) { return Object.hasOwn(this.attributes, name); }
          removeAttribute(name) { delete this.attributes[name]; }
          remove() {
            if (!this.parentNode) return;
            this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
            this.parentNode = null;
          }
          querySelector(selector) {
            if (selector.startsWith("#")) {
              const id = selector.slice(1);
              return descendants(this).find((node) => node.id === id) || null;
            }
            if (selector.startsWith(".")) {
              const className = selector.slice(1);
              return descendants(this).find((node) => node.classList.contains(className)) || null;
            }
            return null;
          }
          querySelectorAll(selector) {
            if (selector === "[data-i18n-loop]") {
              return descendants(this).filter((node) => node.dataset.i18nLoop);
            }
            return [];
          }
          set innerHTML(value) {
            strictAssert.equal(value, "");
            this.children = [];
          }
        }

        const descendants = (root) => [root, ...root.children.flatMap((child) => descendants(child))];
        const elements = new Map();
        const addElement = (id, tagName = "div") => {
          const element = new FakeElement(tagName);
          element.id = id;
          elements.set(id, element);
          return element;
        };
        addElement("command-filter", "input");
        addElement("command-categories");
        addElement("command-list");
        addElement("selected-command");
        addElement("command-description");
        addElement("command-guidance");
        const commandForm = addElement("command-form", "form");
        globalThis.document = {
          createElement: (tagName) => new FakeElement(tagName),
          getElementById: (id) => elements.get(id)
            || descendants(commandForm).find((node) => node.id === id)
            || null,
          querySelectorAll: (selector) => selector === "#command-form .pulse-child-field"
            ? descendants(commandForm).filter((node) => node.classList.contains("pulse-child-field"))
            : [],
        };

        renderWorkspaceSummary = () => {};
        prefillClearProtectionChannel = () => {};
        updateSelectedCommandState = () => {};
        refreshElectricalRatingConstraints = () => {};
        applyWorkflowPulseControlState = () => {};
        isChannelSupported = () => true;
        supportedChannelsForCurrentModel = () => [1, 2, 3];
        selectedElectricalRatingModel = () => null;
        state.commands = {};
        state.workflowControl = { phase: "idle", jobId: null, command: null };

        selectCommand("ramp");
        const channelOptions = () => document.getElementById("param-channel").children.map((item) => [item.value, item.textContent]);
        strictAssert.deepEqual(channelOptions(), [["1", "CH1"], ["2", "CH2"], ["3", "CH3"], ["1,2", "CH1 + CH2"], ["1,3", "CH1 + CH3"], ["2,3", "CH2 + CH3"], ["1,2,3", "All"]]);
        supportedChannelsForCurrentModel = () => [1, 2];
        selectCommand("ramp");
        strictAssert.deepEqual(channelOptions(), [["1", "CH1"], ["2", "CH2"], ["1,2", "All"]]);
        supportedChannelsForCurrentModel = () => [1];
        selectCommand("ramp");
        strictAssert.deepEqual(channelOptions(), [["1", "CH1"]]);
        supportedChannelsForCurrentModel = () => [1, 2, 3];
        selectCommand("ramp");
        strictAssert.equal(document.getElementById("param-delay_ms").value, "0");
        strictAssert.equal(document.getElementById("param-stop_voltage").value, "1");
        strictAssert.equal(document.getElementById("param-enable_output").checked, false);
        strictAssert.equal(document.getElementById("param-loop_count"), null);

        const setInput = (id, value) => {
          const input = document.getElementById(id);
          input.value = value;
          input.dispatch("input");
        };
        setInput("param-delay_ms", "500");
        setInput("param-channel", "1,3");
        setInput("param-start_voltage", "0.5");
        setInput("param-stop_voltage", "2.5");
        setInput("param-step_voltage", "0.25");
        setInput("param-current", "0.2");
        const enableOutput = document.getElementById("param-enable_output");
        enableOutput.checked = true;
        enableOutput.dispatch("change");
        const loopEnabled = document.getElementById("param-loop_enabled");
        loopEnabled.checked = true;
        loopEnabled.dispatch("change");
        setInput("param-loop_count", "4");
        setInput("param-completion_pulse_timing", "loop");
        setInput("param-completion_pulse_pins", "2,3");
        setInput("param-completion_pulse_polarity", "negative");

        selectCommand("ramp");
        strictAssert.equal(document.getElementById("param-delay_ms").value, "500");
        strictAssert.equal(document.getElementById("param-channel").value, "1,3");
        strictAssert.equal(document.getElementById("param-start_voltage").value, "0.5");
        strictAssert.equal(document.getElementById("param-stop_voltage").value, "2.5");
        strictAssert.equal(document.getElementById("param-step_voltage").value, "0.25");
        strictAssert.equal(document.getElementById("param-current").value, "0.2");
        strictAssert.equal(document.getElementById("param-enable_output").checked, true);
        strictAssert.equal(document.getElementById("param-loop_enabled").checked, true);
        strictAssert.equal(document.getElementById("param-loop_count").value, "4");
        strictAssert.equal(document.getElementById("param-completion_pulse_timing").value, "loop");
        strictAssert.equal(document.getElementById("param-completion_pulse_pins").value, "2,3");
        strictAssert.equal(document.getElementById("param-completion_pulse_polarity").value, "negative");

        strictAssert.deepEqual(parameterPayload(), {
          enable_output: true,
          loop_count: 4,
          channels: [1, 3],
          current: 0.2,
          start_voltage: 0.5,
          stop_voltage: 2.5,
          step_voltage: 0.25,
          delay_ms: 500,
          completion_pulse_timing: "loop",
          completion_pulse_pins: [2, 3],
          completion_pulse_polarity: "negative",
        });
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_sequence_renderer_rebuilds_from_canonical_draft_without_missing_dependencies() -> None:
    run_webui_module_assertions(
        r"""
class FakeClassList {
  constructor(owner) { this.owner = owner; }
  values() { return new Set(this.owner.className.split(/\s+/).filter(Boolean)); }
  add(...names) {
    const values = this.values();
    names.forEach((name) => values.add(name));
    this.owner.className = [...values].join(" ");
  }
  remove(...names) {
    const values = this.values();
    names.forEach((name) => values.delete(name));
    this.owner.className = [...values].join(" ");
  }
  contains(name) { return this.values().has(name); }
}

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.className = "";
    this.classList = new FakeClassList(this);
    this.listeners = {};
    this.attributes = {};
    this.textContent = "";
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.hidden = false;
    this.id = "";
    this.type = "";
  }
  appendChild(child) {
    this.children.push(child);
    child.parentNode = this;
    return child;
  }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  addEventListener(type, listener) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(listener);
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  querySelector(selector) {
    if (selector === ".checkbox-label-text") {
      return descendants(this).find((node) => node.classList.contains("checkbox-label-text"));
    }
    if (selector === ".sequence-step-error") {
      return descendants(this).find((node) => node.classList.contains("sequence-step-error"));
    }
    if (selector === ".visually-hidden") {
      return descendants(this).find((node) => node.classList.contains("visually-hidden"));
    }
    if (selector === "input") return descendants(this).find((node) => node.tagName === "INPUT");
    return undefined;
  }
  querySelectorAll(selector) {
    if (selector === "[data-workflow-i18n]") {
      return descendants(this).filter((node) => node.dataset.workflowI18n);
    }
    if (selector === "[data-i18n-loop]") {
      return descendants(this).filter((node) => node.dataset.i18nLoop);
    }
    return [];
  }
  replaceWith(replacement) {
    const index = this.parentNode.children.indexOf(this);
    this.parentNode.children[index] = replacement;
    replacement.parentNode = this.parentNode;
    this.parentNode = null;
  }
  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
    this.parentNode = null;
  }
  set innerHTML(value) {
    strictAssert.equal(value, "");
    this.children = [];
  }
}

const descendants = (root) => [root, ...root.children.flatMap((child) => descendants(child))];
const commandForm = new FakeElement("form");
globalThis.document = {
  createElement: (tagName) => new FakeElement(tagName),
  getElementById: (id) => id === "command-form" ? commandForm : null,
};

const createCheckboxField = (input, text) => {
  const label = new FakeElement("label");
  const visible = new FakeElement("span");
  visible.className = "checkbox-label-text";
  visible.textContent = text;
  label.append(input, visible);
  return label;
};
const state = {
  commands: { sequence: { max_steps: 250 } },
  sequenceSteps: [{ action: "wait", seconds: 0 }],
  sequenceExpanded: new Set(),
  sequenceLoopEnabled: false,
  sequenceLoopCountDraft: "2",
  sequenceFilename: "",
};
const stepsIdentity = state.sequenceSteps;
const validityCalls = [];
let selectedUpdates = 0;
let artifact;
const renderLoopControl = () => new FakeElement("div");
const renderForm = (command) => {
  strictAssert.equal(command, "sequence");
  commandForm.innerHTML = "";
  artifact.renderSequenceForm(commandForm);
};
artifact = globalThis.webuiWorkflows.createArtifactAndSequenceWorkflows({
  state,
  rearPinOptions: ["1", "2", "3", "1,2", "1,3", "2,3", "1,2,3"],
  webuiCommandForm: {
    createCheckboxField,
    appendFieldDescription() {},
  },
  webuiSequenceDocument: {},
  renderForm,
  updateSelectedCommandState: () => { selectedUpdates += 1; },
  optionDisplayName: (value) => String(value),
  rearPinDisplayName: (value) => String(value),
  parseRearPins: (value) => String(value).split(",").map(Number),
  renderLoopControl,
  applyWorkflowPulseControlState() {},
  applyParameterConstraint(input, name) {
    input.dataset.parameterConstraint = name;
  },
  updateWorkflowDocumentValidity: (command) => validityCalls.push(command),
});

strictAssert.doesNotThrow(() => renderForm("sequence"));
strictAssert.equal(commandForm.children.length, 1);
strictAssert.equal(state.sequenceSteps, stepsIdentity);
strictAssert.equal(state.sequenceSteps.length, 1);
strictAssert.deepEqual(validityCalls, ["sequence"]);

let editor = commandForm.children[0];
let cards = descendants(editor).filter((node) => node.classList.contains("sequence-step-card"));
strictAssert.equal(cards.length, 1);
let toggle = cards[0].children[0].children[0];
strictAssert.equal(toggle.textContent, "Expand");
strictAssert.equal(toggle.listeners.click.length, 1);
strictAssert.doesNotThrow(() => toggle.listeners.click[0]());

editor = commandForm.children[0];
cards = descendants(editor).filter((node) => node.classList.contains("sequence-step-card"));
strictAssert.equal(cards.length, 1);
strictAssert.equal(state.sequenceSteps, stepsIdentity);
let secondsInput = descendants(cards[0]).find((node) => node.dataset.sequenceField === "seconds");
strictAssert.ok(secondsInput);
secondsInput.value = "2.5";
secondsInput.listeners.input[0]();
strictAssert.equal(state.sequenceSteps[0].seconds, 2.5);

let toolbar = descendants(editor).find((node) => node.classList.contains("sequence-toolbar"));
const addButton = toolbar.children[2];
strictAssert.equal(addButton.textContent, "Add Step");
strictAssert.equal(addButton.disabled, false);
strictAssert.equal(addButton.listeners.click.length, 1);
addButton.listeners.click[0]();

editor = commandForm.children[0];
cards = descendants(editor).filter((node) => node.classList.contains("sequence-step-card"));
strictAssert.equal(cards.length, 2);
strictAssert.equal(state.sequenceSteps, stepsIdentity);
strictAssert.equal(state.sequenceSteps[0].seconds, 2.5);
strictAssert.deepEqual(state.sequenceSteps[1], { action: "wait", seconds: 0 });
const firstActions = cards[0].children[0].children[3].children;
const secondActions = cards[1].children[0].children[3].children;
strictAssert.deepEqual(firstActions.map((button) => button.disabled), [true, false, false]);
strictAssert.deepEqual(secondActions.map((button) => button.disabled), [false, true, false]);

toggle = cards[1].children[0].children[0];
toggle.listeners.click[0]();
editor = commandForm.children[0];
cards = descendants(editor).filter((node) => node.classList.contains("sequence-step-card"));
const secondFields = descendants(cards[1]).find((node) => node.classList.contains("sequence-step-fields"));
const actionSelect = secondFields.children[0].children[0];
actionSelect.value = "apply";
strictAssert.doesNotThrow(() => actionSelect.listeners.change[0]());

cards = descendants(commandForm.children[0]).filter((node) => node.classList.contains("sequence-step-card"));
for (const [name, value] of [["channel", "2"], ["voltage", "3.3"], ["current", "0.4"]]) {
  const input = descendants(cards[1]).find((node) => node.dataset.sequenceField === name);
  input.value = value;
  input.listeners.input[0]();
}
const noOutput = descendants(cards[1]).find((node) => node.dataset.sequenceField === "no_output");
noOutput.checked = true;
noOutput.listeners.change[0]();
strictAssert.deepEqual(state.sequenceSteps[1], {
  action: "apply", channel: 2, voltage: 3.3, current: 0.4, no_output: true
});
const draftBeforeLocale = JSON.stringify(state.sequenceSteps);

const i18n = await import(new URL("./i18n.js", moduleUrls["workflows.js"]));
for (const locale of ["zh-TW", "en", "zh-TW", "en"]) {
  i18n.setLocale(locale);
  globalThis.webuiWorkflows.refreshWorkflowPresentation(commandForm);
  strictAssert.equal(JSON.stringify(state.sequenceSteps), draftBeforeLocale);
  strictAssert.equal(state.sequenceSteps, stepsIdentity);
  strictAssert.equal(descendants(commandForm).filter((node) => node.classList.contains("sequence-step-card")).length, 2);
}
strictAssert.equal(selectedUpdates > 0, true);
strictAssert.equal(validityCalls.length >= 4, true);
""",
        ("workflows.js",),
    )


def test_static_pulse_child_fields_and_rear_pin_select_contracts():
    _index_html, app_js, styles_css = read_static_texts()
    sequence_document_js = read_static_javascript("sequence.js")
    command_form_js = read_static_javascript("command-form.js")
    workflows_js = read_static_javascript("workflows.js")

    cycle = extract_param_block(app_js, "cycle-output")
    ramp = extract_param_block(app_js, "ramp")
    trigger_pulse = extract_param_block(app_js, "trigger-pulse")
    trigger_list = extract_js_function(command_form_js, "triggerListParams")
    sequence_definitions = extract_js_function(workflows_js, "sequenceActionDefinitions")
    normalize_sequence = extract_js_function(sequence_document_js, "normalizeSequenceStep")

    assert 'name: "completion_pulse_enabled", type: "checkbox"' in cycle
    assert 'name: "completion_pulse_pins", type: "select"' in cycle
    assert cycle.count("pulseChild: true") == 2
    assert 'name: "completion_pulse_pins", type: "select"' in ramp
    assert ramp.count("pulseChild: true") == 2
    assert 'payload.completion_pulse_mode = "post-action";' not in app_js
    assert 'name: "pins", type: "select", label: "Rear pins"' in trigger_pulse
    assert 'name: "completion_pulse_pins", type: "select"' in trigger_list
    assert 'name: "pins", label: "Rear pins", type: "select"' in sequence_definitions
    assert "if (action === \"trigger-pulse\") normalized.pins = parseRearPins(normalized.pins);" in normalize_sequence
    assert "return webuiSequenceDocument.normalizeSequenceDocument(doc," in workflows_js
    assert "return webuiSequenceDocument.sequenceDocumentFromEditor(state," in workflows_js
    assert ".form-grid .pulse-child-field.visible { display: block; }" in styles_css
    assert "function updatePulseChildVisibility(command)" in command_form_js


def test_frontend_workflow_pulse_model_behavior_uses_canonical_ids() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        const testElements = new Map([
          ["expected-model-id", { value: "" }],
          ["resource", { value: "" }],
          ["resource-select", { value: "", options: [{ textContent: "" }] }],
          ["device-resource-summary", { textContent: "", title: "" }]
        ]);
        document.getElementById = (id) => testElements.get(id) || { value: "" };

        const modelMetadata = [
          { model_id: "keysight-e36312a", model_name: "E36312A", display_name: "Keysight E36312A" },
          { model_id: "keysight-edu36311a", model_name: "EDU36311A", display_name: "Keysight EDU36311A" },
          { model_id: "keysight-e3646a", model_name: "E3646A", display_name: "Keysight E3646A" }
        ];
        const modelIds = modelMetadata.map((model) => model.model_id);
        state.physicalModels = modelMetadata;
        state.commands = { "trigger-pulse": { description: "Standalone trigger pulse" } };
        state.commandSupportByModel = Object.fromEntries(modelIds.map((modelId) => [modelId, {
          "trigger-pulse": { real: modelId === "keysight-e36312a" },
          probe: { marker: modelId }
        }]));
        state.channelCapabilitiesByModel = Object.fromEntries(modelIds.map((modelId) => [modelId, {
          channels: modelId === "keysight-e3646a" ? [1, 2] : [1, 2, 3],
          output_control_scope: modelId === "keysight-e3646a" ? "global" : "per_channel"
        }]));
        state.electricalRatingsByModel = Object.fromEntries(modelIds.map((modelId) => [modelId, {
          channels: [{ channel: 1, max_voltage: modelId === "keysight-e3646a" ? 20 : 6, max_current: 1 }]
        }]));

        function setExpected(modelId) {
          testElements.get("expected-model-id").value = modelId || "";
        }

        function setUndetectedResource(resource) {
          testElements.get("resource").value = resource;
          testElements.get("resource-select").value = resource;
          delete state.resourceModels[resource];
          delete state.resourceChannelModels[resource];
          delete state.resourceDisplayModels[resource];
        }

        function setDetectedResource(resource, modelId, reportedModel) {
          testElements.get("resource").value = resource;
          testElements.get("resource-select").value = resource;
          state.resourceModels[resource] = modelId && state.commandSupportByModel[modelId] ? modelId : null;
          state.resourceChannelModels[resource] = modelId && state.channelCapabilitiesByModel[modelId] ? modelId : null;
          state.resourceDisplayModels[resource] = reportedModel;
        }

        const workflowPulseRequests = {
          "cycle-output": { completion_pulse_pins: [1] },
          ramp: { completion_pulse_pins: [1] },
          "ramp-list": { document: { completion_pulse: { timing: "segment", pins: [1], polarity: "positive" } } },
          sequence: { document: { steps: [{ action: "trigger-pulse", pins: [1], polarity: "positive" }] } }
        };
        const workflowSurfaces = ["cycle-output", "ramp", "ramp-list", "sequence"];

        setExpected("keysight-e36312a");
        setUndetectedResource("USB0::EXPECTED::INSTR");
        strictAssert.equal(selectedCommandModel(), "keysight-e36312a");
        strictAssert.equal(selectedChannelModel(), "keysight-e36312a");
        strictAssert.equal(selectedElectricalRatingModel(), "keysight-e36312a");
        strictAssert.equal(selectedCommandSupport("probe").marker, "keysight-e36312a");
        strictAssert.equal(channelCapabilityForCurrentModel().channels.length, 3);
        strictAssert.equal(selectedChannelRatingFor("1").max_voltage, 6);
        strictAssert.equal(pulseControlsUnavailableReason(), "");
        for (const surface of workflowSurfaces) {
          const input = { disabled: true, title: "stale" };
          applyWorkflowPulseControlState(input);
          strictAssert.equal(input.disabled, false, `${surface} control should be enabled for E36312A`);
          strictAssert.equal(input.title, "");
          strictAssert.equal(workflowPulseGuardReason(surface, workflowPulseRequests[surface]), "");
        }
        strictAssert.equal(commandRequestsPulse("trigger-pulse", { pins: [1] }), false);
        strictAssert.notEqual(commandMeta("trigger-pulse").disabled, true);

        setExpected("");
        setDetectedResource("USB0::DETECTED::INSTR", "keysight-e36312a", "E36312A");
        strictAssert.equal(selectedChannelModel(), "keysight-e36312a");
        strictAssert.equal(pulseControlsUnavailableReason(), "");
        for (const surface of workflowSurfaces) {
          strictAssert.equal(workflowPulseGuardReason(surface, workflowPulseRequests[surface]), "");
        }

        for (const [modelId, displayName] of [
          ["keysight-edu36311a", "Keysight EDU36311A"],
          ["keysight-e3646a", "Keysight E3646A"]
        ]) {
          setExpected(modelId);
          setUndetectedResource(`USB0::${modelId}::INSTR`);
          const reason = pulseControlsUnavailableReason();
          strictAssert.match(reason, new RegExp(displayName));
          strictAssert.equal(reason.includes(modelId), false);
          const input = { disabled: false, title: "" };
          applyWorkflowPulseControlState(input);
          strictAssert.equal(input.disabled, true);
          strictAssert.equal(input.title, reason);
          for (const surface of workflowSurfaces) {
            strictAssert.equal(Boolean(workflowPulseGuardReason(surface, workflowPulseRequests[surface])), true);
          }
        }

        setExpected("");
        setDetectedResource("USB0::UNKNOWN::INSTR", null, "UNKNOWN");
        strictAssert.match(pulseControlsUnavailableReason(), /no supported model is selected or detected/);
        for (const surface of workflowSurfaces) {
          strictAssert.equal(Boolean(workflowPulseGuardReason(surface, workflowPulseRequests[surface])), true);
        }

        setExpected("keysight-e36312a");
        setDetectedResource("USB0::MISMATCH::INSTR", "keysight-edu36311a", "EDU36311A");
        const mismatchReason = pulseControlsUnavailableReason();
        strictAssert.match(mismatchReason, /Keysight E36312A/);
        strictAssert.match(mismatchReason, /Keysight EDU36311A/);
        strictAssert.equal(mismatchReason.includes("keysight-"), false);
        updateDeviceResourceSummary();
        strictAssert.match(testElements.get("device-resource-summary").title, /does not match/);

        setDetectedResource("USB0::MISMATCH::INSTR", "keysight-e36312a", "E36312A");
        updateDeviceResourceSummary();
        strictAssert.equal(testElements.get("device-resource-summary").title.includes("does not match"), false);
        strictAssert.equal(pulseControlsUnavailableReason(), "");

        setExpected("");
        setDetectedResource("USB0::SWITCH-A::INSTR", "keysight-e3646a", "E3646A");
        strictAssert.equal(Boolean(pulseControlsUnavailableReason()), true);
        setDetectedResource("USB0::SWITCH-B::INSTR", "keysight-e36312a", "E36312A");
        strictAssert.equal(selectedChannelModel(), "keysight-e36312a");
        strictAssert.equal(pulseControlsUnavailableReason(), "");
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_static_workflow_pulse_gates_do_not_compare_display_model_names() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    workflows_js = read_static_javascript("workflows.js")
    command_form_js = read_static_javascript("command-form.js")

    assert 'const REAR_TRIGGER_PULSE_MODEL_ID = "keysight-e36312a";' in app_js
    for display_name in ("E36312A", "EDU36311A", "E3646A"):
        assert not re.search(
            rf'(?:===|!==)\s*["\']{display_name}["\']|["\']{display_name}["\']\s*(?:===|!==)',
            app_js,
        )
    assert "applyWorkflowPulseControlState(input);" in extract_js_function(command_form_js, "renderForm")
    assert "applyWorkflowPulseControlState(input, prerequisiteReason);" in extract_js_function(workflows_js, "renderRampListForm")
    assert "applyWorkflowPulseControlState(input);" in extract_js_function(workflows_js, "sequenceStepFields")
    assert "workflowPulseGuardReason(command, parameters)" in extract_js_function(app_js, "selectedCommandPresentation")
    assert 'command === "trigger-pulse"' not in extract_js_function(app_js, "commandRequestsPulse")


def test_static_frontend_uses_command_support_to_disable_unsupported_model_commands():
    _index_html, app_js, _styles_css = read_static_texts()
    command_support_js = read_static_javascript("command-support.js")
    device_js = read_static_javascript("device-resource.js")
    command_meta = extract_js_function(command_support_js, "commandMeta")
    update_selected = extract_js_function(app_js, "updateSelectedCommandState")
    selected_command = extract_js_function(device_js, "selectedCommandModel")

    assert "const support = selectedCommandSupport(name);" in command_meta
    assert "support?.real === false" in command_meta
    assert "disabled: true" in command_meta
    assert "commandDisabledReason(support, selectedCommandModel())" in command_meta
    assert "runButton.disabled = Boolean(meta.disabled" in update_selected
    assert "state.commandSupportByModel?.[expected]" in selected_command


def test_static_frontend_policy_for_edu_and_e3646a_disabled_controls():
    _index_html, app_js, _styles_css = read_static_texts()
    command_support_js = read_static_javascript("command-support.js")
    command_meta = extract_js_function(command_support_js, "commandMeta")
    update_selected = extract_js_function(app_js, "updateSelectedCommandState")

    assert '"trigger-step"' in app_js
    assert '"trigger-list"' in app_js
    assert '"snapshot"' in app_js
    assert '"restore-from-snapshot"' in app_js
    assert '"protection-set"' in app_js
    assert '"trigger-pulse"' in app_js
    assert "support?.real === false" in command_meta
    assert "disabled: true" in command_meta
    assert "runButton.disabled = Boolean(meta.disabled" in update_selected


def test_static_e3646a_ramp_list_and_sequence_wording_does_not_imply_native_list_support():
    index_html, app_js, _styles_css = read_static_texts()

    assert "native LIST" not in index_html
    assert "native LIST" not in extract_param_block(app_js, "ramp-list")
    assert "Native LIST" not in extract_param_block(app_js, "ramp-list")


def test_static_job_result_summary_contract():
    _index_html, app_js, _styles_css = read_static_texts()
    result_summary_js = read_static_javascript("results.js")

    render_job_detail = app_js[app_js.index("async function renderJobDetail"):app_js.index("function shouldRefreshLiveAfterCommand")]

    assert "updateJobResult(job.job_id, job.status, webuiResults.jobSummary(job, event), job);" in render_job_detail
    assert "renderResult({" in render_job_detail
    assert 'if (command === "capabilities") return capabilitiesSummary(result);' in result_summary_js
    assert 'if (command === "identify") return identifySummary(result);' in result_summary_js
    assert 'if (command === "verify") return verifySummary(result);' in result_summary_js
    assert 'if (command === "read-status") return readStatusSummary(result);' in result_summary_js
    assert 'if (command === "readback") return readbackSummary(result);' in result_summary_js
    assert 'if (command === "snapshot") return snapshotSummary(result);' in result_summary_js
    assert 'if (command === "error") return errorQueueSummary(result, "instrument");' in result_summary_js
    assert 'if (command === "safety inspect") return safetyInspectSummary(result);' in result_summary_js
    assert "outputStatesSummary(result.outputs)" in result_summary_js
    assert "setpointSummary(channels)" in result_summary_js
    assert "result.resources.length" in result_summary_js


def test_static_workspace_summary_keeps_latest_success_by_complete_execution_context():
    index_html, app_js, _styles_css = read_static_texts()
    context_js = read_static_javascript("execution-context.js")
    jobs_js = read_static_javascript("jobs.js")
    state_js = read_static_javascript("state.js")
    workspace_js = read_static_javascript("results.js")

    capture = extract_js_function(app_js, "captureWorkspaceResult")
    handle_job_event = extract_js_function(jobs_js, "handleJobEvent")
    render = extract_js_function(app_js, "renderWorkspaceSummary")
    current_context = extract_js_function(app_js, "currentWorkspaceResultContext")

    assert 'id="workspace-summary-content"' in index_html
    assert "workspaceResults: {}" in state_js
    assert "buildWorkspaceResultEntry(job, {" in capture
    assert "if (!entry) return false;" in capture
    assert "state.workspaceResults[entry.key] = entry.job;" in capture
    assert "currentWorkspaceResultContext(state.selected)" in render
    assert "findWorkspaceResult(state.workspaceResults, context)" in render
    assert 't("workspace.empty.choose_command")' in render
    assert 't("workspace.empty.run_command")' in render
    assert "webuiResults.renderWorkspaceJob(container, job, context, {" in render
    assert "renderCapabilitiesWorkspaceSummary(container, job.result, helpers);" in workspace_js
    assert "renderIdentifyWorkspaceSummary(container, job.result);" in workspace_js
    assert "captureWorkspaceResult(job);" in handle_job_event
    assert "captureWorkspaceResult: (...args) => captureWorkspaceResult(...args)" in app_js
    assert "function buildWorkspaceResultKey(context)" not in app_js
    assert "function buildWorkspaceResultKey(context)" in context_js
    assert "function buildWorkspaceResultContextForJob(job, modelMaps = {})" in context_js
    assert "function buildCurrentWorkspaceResultContext(snapshot)" in context_js
    assert "function buildWorkspaceResultEntry(job, modelMaps = {})" in context_js
    assert "function findWorkspaceResult(workspaceResults, context)" in context_js
    assert "webuiContext.buildCurrentWorkspaceResultContext({" in current_context


def test_frontend_workspace_result_keys_isolate_complete_execution_context() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        const elements = new Map([
          ["resource", { value: "RESOURCE-A" }],
          ["expected-model-id", { value: "keysight-e36312a" }]
        ]);
        document.getElementById = (id) => elements.get(id) || null;
        state.livePanel = null;
        state.resourceLiveSupport = null;
        state.resourceLiveSupportContext = null;
        state.resourceModels = { "RESOURCE-A": "keysight-e36312a" };
        state.resourceChannelModels = { "RESOURCE-A": "keysight-e36312a" };

        const realJob = (resource, expected, modelId) => ({
          status: "finished",
          command: "identify",
          runtime: {
            resource,
            simulate: false,
            dry_run: false,
            ...(expected ? { expected_model_id: expected } : {})
          },
          result: { resource: { name: resource, model_id: modelId } }
        });
        const keyForJob = (job) => webuiContext.buildWorkspaceResultEntry(job, {
          commandModelByResource: state.resourceModels,
          channelModelByResource: state.resourceChannelModels
        }).key;

        state.executionMode = "real";
        const realA = realJob("RESOURCE-A", "keysight-e36312a", "keysight-e36312a");
        const realAKey = keyForJob(realA);
        strictAssert.equal(
          realAKey,
          webuiContext.buildWorkspaceResultKey(currentWorkspaceResultContext("identify")),
          "identical Real context must restore its result"
        );
        strictAssert.notEqual(realAKey, keyForJob(realJob("RESOURCE-B", "keysight-e36312a", "keysight-e36312a")));
        strictAssert.notEqual(realAKey, keyForJob(realJob("RESOURCE-A", "", "keysight-e36312a")));
        strictAssert.notEqual(realAKey, keyForJob(realJob("RESOURCE-A", "keysight-e36312a", "keysight-edu36311a")));

        state.executionMode = "simulate";
        elements.get("expected-model-id").value = "keysight-e36312a";
        const simulateA = {
          status: "finished",
          command: "identify",
          runtime: { resource: "PRESERVED-A", simulate: true, dry_run: false, planning_model_id: "keysight-e36312a" },
          result: {}
        };
        const simulateAWithOtherPreservedResource = {
          ...simulateA,
          runtime: { ...simulateA.runtime, resource: "PRESERVED-B" }
        };
        strictAssert.equal(keyForJob(simulateA), keyForJob(simulateAWithOtherPreservedResource));
        strictAssert.equal(keyForJob(simulateA), webuiContext.buildWorkspaceResultKey(currentWorkspaceResultContext("identify")));
        strictAssert.notEqual(keyForJob(simulateA), keyForJob({
          ...simulateA,
          runtime: { ...simulateA.runtime, planning_model_id: "keysight-edu36311a" }
        }));
        strictAssert.notEqual(realAKey, keyForJob(simulateA));

        state.executionMode = "dry-run";
        elements.get("expected-model-id").value = "profile:generic-scpi";
        const dryProfile = {
          status: "finished",
          command: "identify",
          runtime: { simulate: false, dry_run: true, planning_profile_id: "generic-scpi" },
          result: {}
        };
        strictAssert.equal(keyForJob(dryProfile), webuiContext.buildWorkspaceResultKey(currentWorkspaceResultContext("identify")));
        strictAssert.notEqual(keyForJob(dryProfile), keyForJob({
          ...dryProfile,
          runtime: { simulate: false, dry_run: true, planning_model_id: "keysight-e36312a" }
        }));
        strictAssert.notEqual(keyForJob(dryProfile), keyForJob(simulateA));
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_frontend_workspace_capture_keeps_helper_and_lifecycle_boundaries() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        state.workspaceResults = Object.create(null);
        state.resourceModels = { "RESOURCE-A": "keysight-e36312a" };
        state.resourceChannelModels = { "RESOURCE-A": "keysight-edu36311a" };
        const liveSupportCalls = [];
        const renderCalls = [];
        captureResourceLiveSupport = (job, resource) => {
          liveSupportCalls.push({ job, resource });
          return true;
        };
        renderWorkspaceSummary = () => renderCalls.push("rendered");
        const jobFor = (command, result = { resource: { name: "RESOURCE-A", model_id: "keysight-e3646a" } }) => ({
          status: "finished",
          command,
          runtime: {
            resource: "RESOURCE-A",
            simulate: false,
            dry_run: false,
            expected_model_id: "keysight-e36312a"
          },
          result
        });

        for (const invalidJob of [
          null,
          undefined,
          { ...jobFor("set"), status: "failed" },
          { ...jobFor("set"), status: "cancelled" },
          { ...jobFor("set"), command: "" },
          { ...jobFor("set"), result: null }
        ]) {
          strictAssert.equal(captureWorkspaceResult(invalidJob), false);
        }
        strictAssert.deepEqual(Reflect.ownKeys(state.workspaceResults), []);
        strictAssert.deepEqual(liveSupportCalls, []);
        strictAssert.deepEqual(renderCalls, []);

        const first = jobFor("set", {});
        const firstBefore = JSON.parse(JSON.stringify(first));
        strictAssert.equal(captureWorkspaceResult(first), true);
        const firstEntry = webuiContext.buildWorkspaceResultEntry(first, {
          commandModelByResource: state.resourceModels,
          channelModelByResource: state.resourceChannelModels
        });
        strictAssert.strictEqual(state.workspaceResults[firstEntry.key], first);
        strictAssert.deepEqual(first, firstBefore);
        strictAssert.deepEqual(renderCalls, ["rendered"]);

        const later = jobFor("set", { marker: "later" });
        strictAssert.equal(captureWorkspaceResult(later), true);
        strictAssert.strictEqual(state.workspaceResults[firstEntry.key], later);
        strictAssert.deepEqual(renderCalls, ["rendered", "rendered"]);

        for (const command of ["capabilities", "identify", "verify"]) {
          const job = jobFor(command);
          strictAssert.equal(captureWorkspaceResult(job), true);
          strictAssert.strictEqual(liveSupportCalls.at(-1).job, job);
          strictAssert.equal(liveSupportCalls.at(-1).resource, "RESOURCE-A");
        }
        const liveSupportCount = liveSupportCalls.length;
        strictAssert.equal(captureWorkspaceResult(jobFor("trigger-status")), true);
        strictAssert.equal(liveSupportCalls.length, liveSupportCount);
        strictAssert.equal(renderCalls.length, 6);
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_frontend_stale_resource_preview_is_suppressed_after_health_refresh() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        (async () => {
        let activeResource = "RESOURCE-A";
        document.getElementById = (id) => id === "resource" ? { value: activeResource } : null;
        isNoHardwareMode = () => false;
        stopLivePreviewSnapshot = () => {};
        renderBlankLivePanel = () => {};

        let resolveDirectHealth;
        refreshHealth = () => new Promise((resolve) => { resolveDirectHealth = resolve; });
        const directPreviews = [];
        startLivePreviewSnapshot = async (_health, resource) => directPreviews.push(resource);

        const directRefresh = refreshSelectedResourcePreview("RESOURCE-A");
        await Promise.resolve();
        activeResource = "RESOURCE-B";
        resolveDirectHealth({ hardware_busy: false });
        await directRefresh;
        strictAssert.deepEqual(directPreviews, []);

        activeResource = "RESOURCE-A";
        let resolveTerminalHealth;
        const terminalPreviews = [];
        const job = {
          status: "finished",
          command: "identify",
          runtime: { resource: "RESOURCE-A", simulate: false, dry_run: false }
        };
        const controller = webuiJobTransport.createJobEventController({
          state: {
            workflowControl: { jobId: null, phase: "idle" },
            basicJobActions: {},
            selected: null
          },
          fetchJson: async () => ({}),
          closeEventSource: () => {},
          updateHistory: () => {},
          setWorkflowControl: () => {},
          updateJobResult: () => {},
          jobCommand: () => "identify",
          refreshSnapshotFormIfVisible: () => {},
          renderJobDetail: async () => job,
          populateResourceSelect: async () => {},
          captureResourceScanFailure: () => {},
          refreshHealth: () => new Promise((resolve) => { resolveTerminalHealth = resolve; }),
          startLivePreviewSnapshot: (_health, resource) => terminalPreviews.push(resource),
          shouldRefreshLiveAfterCommand,
          captureLatestSnapshotDocument: () => {},
          captureWorkspaceResult: () => {},
          updateBasicActionFromJob: () => {},
          updateResourceModelFromJob: () => {},
          finishResourceLiveSupportEvaluation: async () => {},
          jobLabel: () => "",
          captureRestorePlanPreview: () => {},
          renderForm: () => {},
          updateSelectedCommandState: () => {},
          reconcileWorkflowJob: () => {}
        });

        const terminalRefresh = controller.handleJobEvent("job-a", { type: "finished", data: {} });
        await Promise.resolve();
        activeResource = "RESOURCE-B";
        resolveTerminalHealth({ hardware_busy: false });
        await terminalRefresh;
        strictAssert.deepEqual(terminalPreviews, []);
        })().catch((error) => {
          console.error(error);
          process.exitCode = 1;
        });
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_frontend_resource_single_flight_and_execution_mode_context_refresh() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        (async () => {

        class FakeClassList {
          add() {}
          toggle() {}
        }

        class FakeSelect {
          constructor(value = "") {
            this.value = value;
            this.options = [];
            this.children = [];
            this.classList = new FakeClassList();
            this._selectedIndex = -1;
          }
          replaceChildren() {
            this.value = "";
            this.options = [];
            this.children = [];
          }
          add(option) {
            this.options.push(option);
            this.children.push(option);
          }
          append(...children) {
            this.children.push(...children);
            children.forEach((child) => this.options.push(...(child.children || [])));
          }
          appendChild(child) {
            this.add(child);
            return child;
          }
          set innerHTML(value) {
            this.replaceChildren();
          }
          get innerHTML() {
            return "";
          }
          set selectedIndex(index) {
            this._selectedIndex = index;
            this.value = this.options[index]?.value || "";
          }
          get selectedIndex() {
            return this._selectedIndex;
          }
        }

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

        const createControl = (value = "") => ({
          value,
          checked: false,
          disabled: false,
          hidden: false,
          title: "",
          textContent: "",
          className: "",
          classList: new FakeClassList(),
          parentElement: { hidden: false },
          firstChild: { textContent: "" }
        });
        const identity = new FakeSelect("keysight-e36312a");
        const elements = new Map([
          ["expected-model-id", identity],
          ["resource", createControl("")],
          ["resource-select", new FakeSelect("")],
          ["real-write-enabled", createControl()],
          ["execution-mode-badge", createControl()],
          ["execution-mode-help", createControl()],
          ["identity-model-label", createControl()],
          ["device-resource-summary", createControl()],
          ["command-form", createControl()],
          ["workspace-summary-content", createControl()]
        ]);
        ["scan", "live-start", "serial-baud-rate", "serial-data-bits", "serial-parity", "serial-stop-bits", "serial-flow-control", "serial-read-termination", "serial-write-termination", "serial-remote", "serial-local-on-close"].forEach((id) => elements.set(id, createControl()));
        const radios = ["real", "simulate", "dry-run"].map((value) => ({ value, checked: value === "real", disabled: false, title: "" }));

        globalThis.Option = function Option(text, value) { return { textContent: text, value: String(value) }; };
        document.getElementById = (id) => elements.get(id) || null;
        document.createElement = () => ({ children: [], append(...children) { this.children.push(...children); } });
        document.querySelectorAll = (selector) => selector === 'input[name="execution-mode"]' ? radios : [];
        document.querySelector = (selector) => {
          const match = selector.match(/\[value="([^"]+)"\]/);
          return match ? radios.find((radio) => radio.value === match[1]) || null : null;
        };

        state.executionMode = "real";
        state.executionModeTransition = false;
        state.workflowControl = { phase: "idle" };
        state.basicActionStates = {};
        state.jobs = [];
        state.selected = "set";
        state.realIdentityCache = { expectedModelId: "keysight-e36312a" };
        state.planningIdentityCache = { simulate: "keysight-e3646a", "dry-run": "profile:generic-scpi" };
        state.physicalModels = [
          { model_id: "keysight-e36312a", display_name: "Keysight E36312A" },
          { model_id: "keysight-e3646a", display_name: "Keysight E3646A" }
        ];
        state.planningProfiles = {
          "generic-scpi": { profile_id: "generic-scpi", display_name: "Generic SCPI" }
        };
        state.parameterConstraints = {
          voltage: { min: 0, max: 100, step: 0.1, description: "Generic voltage guidance" }
        };
        state.electricalRatingsByModel = {
          "keysight-e36312a": { channels: [{ channel: 1, max_voltage: 6, max_current: 5 }] },
          "keysight-e3646a": { channels: [{ channel: 1, max_voltage: 20, max_current: 1 }] }
        };
        state.commandSupportByModel = {
          "keysight-e36312a": {},
          "keysight-e3646a": {}
        };
        state.channelCapabilitiesByModel = {
          "keysight-e36312a": { channels: [1, 2, 3], output_control_scope: "per_channel" },
          "keysight-e3646a": { channels: [1, 2], output_control_scope: "global" }
        };
        state.resourceModels = { "RESOURCE-REAL": "keysight-e3646a" };
        state.resourceChannelModels = { "RESOURCE-REAL": "keysight-e3646a" };
        state.livePanel = null;
        state.workspaceResults = {};

        const realJob = {
          status: "finished",
          command: "set",
          runtime: { resource: "RESOURCE-REAL", simulate: false, dry_run: false, expected_model_id: "keysight-e36312a" },
          result: { resource: { name: "RESOURCE-REAL", model_id: "keysight-e3646a" } }
        };
        const realKey = webuiContext.buildWorkspaceResultEntry(realJob, {
          commandModelByResource: state.resourceModels,
          channelModelByResource: state.resourceChannelModels
        }).key;
        state.workspaceResults[realKey] = { marker: "real" };

        const selectedCalls = [];
        const formLimits = [];
        const workspaceViews = [];
        const clientFailures = [];
        stopRealLiveJobsAndWait = async () => {};
        renderBlankLivePanel = () => {};
        renderClientResult = (...args) => clientFailures.push(args);
        updateDeviceResourceSummary = () => {};
        updateSelectedCommandState = () => {};
        syncBasicFromLivePanel = () => {};
        renderCommands = () => {};
        selectCommand = (name) => {
          selectedCalls.push(name);
          const input = new FakeInput();
          refreshInputElectricalConstraints(input, "voltage");
          formLimits.push({ mode: state.executionMode, max: input.max, title: input.title });
          const context = currentWorkspaceResultContext(name);
          workspaceViews.push({ context, marker: webuiContext.findWorkspaceResult(state.workspaceResults, context)?.marker || null });
        };
        renderWorkspaceSummary = () => {
          const context = currentWorkspaceResultContext(state.selected);
          workspaceViews.push({ context, marker: webuiContext.findWorkspaceResult(state.workspaceResults, context)?.marker || null });
        };
        const supportEvaluations = [];
        const evaluationHistory = [];
        const evaluationSubscriptions = [];
        const previewResources = [];
        let resolveFirstSupport;
        const firstSupportResponse = new Promise((resolve) => { resolveFirstSupport = resolve; });
        submitJob = async (payload) => {
          supportEvaluations.push(payload);
          if (supportEvaluations.length === 1) return firstSupportResponse;
          return { job_id: `support-${supportEvaluations.length}` };
        };
        addHistory = (...args) => evaluationHistory.push(args);
        subscribeToJob = (...args) => evaluationSubscriptions.push(args);
        refreshSelectedResourcePreview = async (resource) => previewResources.push(resource);

        updateExecutionModeUi({ renderCommands: false, resetAuthorization: true });
        const writeCheckbox = elements.get("real-write-enabled");
        strictAssert.equal(writeCheckbox.disabled, true);
        strictAssert.equal(writeCheckbox.checked, false);
        strictAssert.equal(state.realWriteAuthorization, null);

        elements.get("resource").value = "RESOURCE-REAL";
        elements.get("resource-select").value = "RESOURCE-REAL";
        syncTypedResource();
        strictAssert.equal(writeCheckbox.disabled, false);
        strictAssert.equal(writeCheckbox.checked, true);
        strictAssert.equal(state.realWriteAuthorization, realAuthorizationContext());
        strictAssert.deepEqual(JSON.parse(state.realWriteAuthorization), {
          resource: "RESOURCE-REAL",
          expected_model_id: "keysight-e36312a",
          connected_model_id: "keysight-e3646a"
        });
        strictAssert.equal(elements.get("execution-mode-badge").textContent, "Real · Writes enabled");

        writeCheckbox.checked = false;
        state.realWriteAuthorization = null;
        updateExecutionModeUi({ renderCommands: false });
        strictAssert.equal(writeCheckbox.checked, false);
        strictAssert.equal(state.realWriteAuthorization, null);

        elements.get("serial-remote").checked = true;
        elements.get("serial-local-on-close").checked = true;
        const scanSelection = populateResourceSelect([{
          name: "RESOURCE-SCAN",
          model_id: "keysight-e3646a",
          idn: { manufacturer: "Keysight", model: "E3646A" }
        }]);
        strictAssert.equal(elements.get("resource").value, "RESOURCE-SCAN");
        strictAssert.equal(writeCheckbox.checked, true);
        strictAssert.equal(state.realWriteAuthorization, realAuthorizationContext());
        strictAssert.equal(supportEvaluations.length, 1);
        strictAssert.equal(supportEvaluations[0].command, "identify");
        strictAssert.equal(supportEvaluations[0].runtime.resource, "RESOURCE-SCAN");
        strictAssert.equal(supportEvaluations[0].runtime.confirm, false);
        strictAssert.equal("serial_remote" in supportEvaluations[0].runtime, false);
        strictAssert.equal("serial_local_on_close" in supportEvaluations[0].runtime, false);
        strictAssert.deepEqual(supportEvaluations[0].parameters, {});
        await refreshSelectedResourceContext("RESOURCE-SCAN");
        strictAssert.equal(supportEvaluations.length, 1, "pending support evaluation must not be submitted twice");

        elements.get("resource-select").value = "RESOURCE-B";
        state.resourceModels["RESOURCE-B"] = "keysight-e36312a";
        state.resourceChannelModels["RESOURCE-B"] = "keysight-e36312a";
        await syncSelectedResource();
        elements.get("resource-select").value = "RESOURCE-SCAN";
        await syncSelectedResource();
        strictAssert.equal(supportEvaluations.length, 1, "switching back to A must not resubmit A");
        elements.get("resource-select").value = "RESOURCE-B";
        await syncSelectedResource();
        elements.get("resource-select").value = "RESOURCE-SELECTED";
        state.resourceModels["RESOURCE-SELECTED"] = "keysight-e36312a";
        state.resourceChannelModels["RESOURCE-SELECTED"] = "keysight-e36312a";
        await syncSelectedResource();
        strictAssert.equal(supportEvaluations.length, 1, "B and C must wait for A");
        resolveFirstSupport({ job_id: "support-1" });
        await scanSelection;
        strictAssert.deepEqual(evaluationHistory[0].slice(1, 4), ["identify", "accepted", "Read device information"]);
        strictAssert.deepEqual(evaluationSubscriptions[0], ["support-1", "/api/events"]);
        strictAssert.equal(
          shouldRefreshLiveAfterCommand(
            { type: "finished" },
            { command: "identify", runtime: { resource: "RESOURCE-SCAN", simulate: false, dry_run: false } }
          ),
          false
        );
        strictAssert.deepEqual(previewResources, []);
        await finishResourceLiveSupportEvaluation("support-1");
        strictAssert.deepEqual(JSON.parse(state.realWriteAuthorization), {
          resource: "RESOURCE-SELECTED",
          expected_model_id: "keysight-e36312a",
          connected_model_id: "keysight-e36312a"
        });
        strictAssert.equal(supportEvaluations.length, 2);
        strictAssert.equal(supportEvaluations[1].command, "identify");
        strictAssert.equal(supportEvaluations[1].runtime.resource, "RESOURCE-SELECTED");
        strictAssert.equal(supportEvaluations[1].runtime.confirm, false);
        const unsupportedSupport = { evaluated: false, reported_model: "UNKNOWN-PSU", commands: {} };
        state.resourceLiveSupport = null;
        state.resourceLiveSupportContext = null;
        strictAssert.equal(
          captureResourceLiveSupport({ result: { live_support: unsupportedSupport } }, "RESOURCE-OLD"),
          false
        );
        strictAssert.equal(state.resourceLiveSupport, null, "stale resource result must be ignored");
        strictAssert.equal(
          captureResourceLiveSupport({ result: { live_support: unsupportedSupport } }, "RESOURCE-SELECTED"),
          true
        );
        strictAssert.strictEqual(state.resourceLiveSupport, unsupportedSupport);
        await finishResourceLiveSupportEvaluation("support-2");
        strictAssert.equal(pendingResourceLiveSupport, null, "terminal evaluation must clear pending");
        await refreshSelectedResourceContext("RESOURCE-SELECTED");
        strictAssert.equal(supportEvaluations.length, 2, "matching support context must be reused");
        strictAssert.deepEqual(previewResources, ["RESOURCE-SELECTED"]);

        elements.get("resource").value = "RESOURCE-TYPED";
        state.resourceModels["RESOURCE-TYPED"] = "keysight-e3646a";
        state.resourceChannelModels["RESOURCE-TYPED"] = "keysight-e3646a";
        syncTypedResource();
        strictAssert.equal(state.realWriteAuthorization, realAuthorizationContext());
        strictAssert.equal(JSON.parse(state.realWriteAuthorization).resource, "RESOURCE-TYPED");

        identity.value = "keysight-e3646a";
        handleExpectedModelChanged();
        strictAssert.equal(JSON.parse(state.realWriteAuthorization).expected_model_id, "keysight-e3646a");

        elements.get("resource").value = "RESOURCE-REAL";
        elements.get("resource-select").value = "RESOURCE-REAL";
        syncTypedResource();
        identity.value = "keysight-e36312a";
        handleExpectedModelChanged();
        const beforeDetectedModelChange = state.realWriteAuthorization;
        updateResourceModel("RESOURCE-REAL", "keysight-e36312a", "E36312A");
        strictAssert.notEqual(state.realWriteAuthorization, beforeDetectedModelChange);
        strictAssert.equal(JSON.parse(state.realWriteAuthorization).connected_model_id, "keysight-e36312a");
        updateResourceModel("RESOURCE-REAL", "keysight-e3646a", "E3646A");
        strictAssert.equal(JSON.parse(state.realWriteAuthorization).connected_model_id, "keysight-e3646a");
        selectedCalls.length = 0;
        formLimits.length = 0;
        workspaceViews.length = 0;

        await handleExecutionModeChange({ target: radios[1] });
        strictAssert.equal(identity.value, "keysight-e3646a");
        strictAssert.equal(writeCheckbox.checked, false);
        strictAssert.equal(writeCheckbox.disabled, true);
        strictAssert.equal(state.realWriteAuthorization, null);
        strictAssert.deepEqual(formLimits.at(-1), { mode: "simulate", max: "20", title: "Official independent-channel DC output rating: maximum 20 V." });
        strictAssert.equal(workspaceViews.at(-1).context.executionMode, "simulate");
        strictAssert.equal(workspaceViews.at(-1).marker, null, "Simulate must not show the Real result");

        const simulateContext = currentWorkspaceResultContext("set");
        state.workspaceResults[webuiContext.buildWorkspaceResultKey(simulateContext)] = { marker: "simulate" };
        await handleExecutionModeChange({ target: radios[2] });
        strictAssert.equal(identity.value, "profile:generic-scpi");
        strictAssert.equal(writeCheckbox.checked, false);
        strictAssert.equal(state.realWriteAuthorization, null);
        strictAssert.deepEqual(formLimits.at(-1), { mode: "dry-run", max: "100", title: "Finite non-negative voltage setpoint." });
        strictAssert.equal(workspaceViews.at(-1).context.executionMode, "dry-run");
        strictAssert.equal(workspaceViews.at(-1).marker, null, "Dry-run must not show the Simulate result");

        await handleExecutionModeChange({ target: radios[0] });
        strictAssert.equal(identity.value, "keysight-e36312a");
        strictAssert.equal(writeCheckbox.checked, true);
        strictAssert.equal(writeCheckbox.disabled, false);
        strictAssert.equal(state.realWriteAuthorization, realAuthorizationContext());
        strictAssert.equal(elements.get("execution-mode-badge").textContent, "Real · Writes enabled");
        strictAssert.deepEqual(formLimits.at(-1), { mode: "real", max: "6", title: "Official independent-channel DC output rating: maximum 6 V." });
        const realContext = workspaceViews.at(-1).context;
        strictAssert.equal(realContext.resource, "RESOURCE-REAL");
        strictAssert.equal(realContext.expectedModelGuard, "keysight-e36312a");
        strictAssert.equal(realContext.canonicalModelId, "keysight-e3646a");
        strictAssert.notEqual(realContext.expectedModelGuard, realContext.canonicalModelId);
        strictAssert.equal(workspaceViews.at(-1).marker, "real");
        strictAssert.equal(webuiContext.buildWorkspaceResultKey(realContext), realKey);
        strictAssert.deepEqual(selectedCalls, ["set", "set", "set"]);

        state.liveJobId = "live-stop-failure";
        webuiApi.fetchJson = async () => { throw new Error("Live stop failed"); };
        await handleExecutionModeChange({ target: radios[1] });
        strictAssert.equal(state.executionMode, "real");
        strictAssert.deepEqual(selectedCalls, ["set", "set", "set"]);
        strictAssert.equal(clientFailures.length, 1);
        })().catch((error) => {
          console.error(error);
          process.exitCode = 1;
        });
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_static_workspace_capabilities_and_identify_use_result_fields():
    _index_html, app_js, _styles_css = read_static_texts()
    workspace_js = read_static_javascript("results.js")

    capabilities = extract_js_function(workspace_js, "renderCapabilitiesWorkspaceSummary")
    identify = extract_js_function(workspace_js, "renderIdentifyWorkspaceSummary")

    for field in ("model", "resource", "channels", "measure_channels", "command_support", "models"):
        assert field in capabilities
    assert "featureAvailability(" in capabilities
    assert "details.channels.length" in capabilities
    for field in ("manufacturer", "model", "serial", "firmware", "options", "scpi_version", "resource"):
        assert field in identify


def test_static_command_keys_are_used_for_selection_and_submission():
    _index_html, app_js, _styles_css = read_static_texts()
    command_form_js = read_static_javascript("command-form.js")

    render_commands = command_form_js[command_form_js.index("function renderCommands()"):command_form_js.index("function selectCommand")]

    assert "Object.entries(state.commands)" in render_commands
    assert 'title.textContent = commandDisplayName(name);' in render_commands
    assert "button.append(title, status);" in render_commands
    assert "button.addEventListener(\"click\", () => selectCommand(name));" in render_commands
    assert "command: state.selected" in app_js
    assert "renderForm(name);" in command_form_js
    assert "selectCommand(commandDisplayName(name))" not in app_js


def test_static_command_display_names_preserve_machine_command_keys():
    _index_html, app_js, _styles_css = read_static_texts()
    command_form_js = read_static_javascript("command-form.js")

    render_commands = command_form_js[command_form_js.index("function renderCommands()"):command_form_js.index("function selectCommand")]

    assert 'name.includes(filter) || commandDisplayName(name).toLowerCase().includes(filter)' in render_commands
    assert 'commandSourceDisplayName(a[0]).localeCompare(commandSourceDisplayName(b[0]), "en")' in render_commands
    assert 'a[0].localeCompare(b[0], "en")' in render_commands


def test_static_command_select_options_use_human_labels_and_machine_values():
    _index_html, app_js, _styles_css = read_static_texts()
    workflows_js = read_static_javascript("workflows.js")
    command_form_js = read_static_javascript("command-form.js")

    render_form = extract_js_function(command_form_js, "renderForm")
    render_restore = extract_js_function(workflows_js, "renderRestoreForm")
    display_name = extract_js_function(command_form_js, "optionDisplayName")

    assert "item.value = option;" in render_form
    assert 'item.textContent = command === "ramp" && param.name === "channel"' in render_form
    assert ': param.parser === "intList"' in render_form
    assert '? rearPinDisplayName(option)' in render_form
    assert ': pulseTimingDisplayName(command, option);' in render_form
    assert "opt.value = ch;" in render_restore
    assert "opt.textContent = optionDisplayName(ch);" in render_restore
    assert 'value.replace(/-/g, " ")' in display_name
    assert 'return `Pin ${value}`' not in display_name


def test_frontend_loop_document_round_trips_use_external_schemas() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        state.commands.sequence = { max_steps: 250 };

        const v1 = normalizeSequenceDocument({
          version: 1,
          steps: [{ action: "wait", seconds: 0 }]
        });
        strictAssert.equal(v1.loopCount, 1);
        const v2 = normalizeSequenceDocument({
          version: 2,
          loop_count: 4,
          steps: [{ action: "wait", seconds: 0 }]
        });
        strictAssert.equal(v2.loopCount, 4);
        strictAssert.throws(
          () => normalizeSequenceDocument({ version: 2, steps: [{ action: "wait", seconds: 0 }] }),
          /loop_count/
        );
        strictAssert.throws(
          () => normalizeSequenceDocument({ version: 1, loop_count: 2, steps: [{ action: "wait", seconds: 0 }] }),
          /unsupported fields/
        );

        state.sequenceLoopEnabled = true;
        state.sequenceLoopCountDraft = "4";
        state.sequenceSteps = [{ action: "wait", seconds: 0 }];
        const serialized = sequenceDocumentFromEditor();
        strictAssert.deepEqual(Object.keys(serialized), ["version", "loop_count", "steps"]);
        strictAssert.equal(serialized.version, 2);
        strictAssert.equal(serialized.loop_count, 4);
        strictAssert.equal(Object.hasOwn(serialized, "loopCount"), false);

        state.rampListEnableOutput = false;
        state.rampListLoopEnabled = false;
        state.rampListLoopCountDraft = "2";
        state.rampListCompletionPulse = null;
        state.rampListSegments = [{
          channels: [1], current: 0.1, start_voltage: 0, stop_voltage: 1,
          step_voltage: 1, delay_ms: 0, hold_ms: 0
        }];
        const rampList = rampListDocument();
        strictAssert.equal(rampList.version, 5);
        strictAssert.equal(rampList.loop_count, 1);
        strictAssert.equal(validateRampListDocument({
          kind: "powers-tool-ramp-list",
          version: 2,
          segments: [{
            channel: 1, current: 0.1, start_voltage: 0, stop_voltage: 1,
            step_voltage: 1, delay_ms: 0, hold_ms: 0
          }]
        }).loopCount, 1);
        strictAssert.equal(validateRampListDocument(rampList).loopCount, 1);
        strictAssert.throws(
          () => validateRampListDocument({ ...rampList, completion_pulse: { timing: "loop", pins: [1], polarity: "positive" } }),
          /requires loop_count of at least 2/
        );
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_frontend_sequence_zero_wait_loop_document_does_not_disable_run_or_save() -> None:
    run_webui_module_assertions(
        r"""
const state = {
  commands: { sequence: { max_steps: 250 } },
  sequenceLoopEnabled: false,
  sequenceLoopCountDraft: "2",
  sequenceSteps: [{ action: "wait", seconds: 0 }]
};
const workflows = globalThis.webuiWorkflows.createWorkflows({
  state,
  webuiRampListDocument: globalThis.webuiRampListDocument
});
const artifact = globalThis.webuiWorkflows.createArtifactAndSequenceWorkflows({
  state,
  rearPinOptions: ["1", "2", "3", "1,2", "1,3", "2,3", "1,2,3"],
  webuiSequenceDocument: globalThis.webuiSequenceDocument,
  parseRearPins: (value) => Array.isArray(value) ? value : String(value).split(",").map(Number),
  effectiveSequenceLoopCount: workflows.effectiveSequenceLoopCount
});

strictAssert.equal(artifact.sequenceDocumentFromEditor().loop_count, 1);

state.sequenceLoopEnabled = true;
state.sequenceLoopCountDraft = "2";
state.sequenceSteps = [
  { action: "output-on", channel: 1 },
  { action: "wait", seconds: 0 },
  { action: "output-off", channel: 1 },
  { action: "wait", seconds: 0 }
];
strictAssert.deepEqual(artifact.sequenceDocumentFromEditor(), {
  version: 2,
  loop_count: 2,
  steps: state.sequenceSteps
});
""",
        ("ramp-list.js", "sequence.js", "workflows.js"),
    )

    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        const elements = {
          "save-sequence": { disabled: false },
          "sequence-document-error": { textContent: "", hidden: false }
        };
        document.getElementById = (id) => elements[id] || null;
        state.commands.sequence = { max_steps: 250 };
        state.sequenceLoopEnabled = true;
        state.sequenceLoopCountDraft = "2";
        state.sequenceSteps = [
          { action: "output-on", channel: 1 },
          { action: "wait", seconds: 0 },
          { action: "output-off", channel: 1 },
          { action: "wait", seconds: 0 }
        ];

        const sequenceRun = { disabled: false };
        strictAssert.equal(updateWorkflowDocumentValidity("sequence", sequenceRun), true);
        strictAssert.equal(elements["save-sequence"].disabled, false);
        strictAssert.equal(sequenceRun.disabled, false);
        strictAssert.equal(elements["sequence-document-error"].textContent, "");
        strictAssert.equal(elements["sequence-document-error"].hidden, true);
        const runtimeGuardedRun = { disabled: true };
        strictAssert.equal(updateWorkflowDocumentValidity("sequence", runtimeGuardedRun), true);
        strictAssert.equal(runtimeGuardedRun.disabled, true);
        strictAssert.deepEqual(sequenceDocumentFromEditor(), {
          version: 2,
          loop_count: 2,
          steps: state.sequenceSteps
        });
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_frontend_invalid_enabled_loop_counts_disable_run_and_save_without_serializing() -> None:
    assertions = textwrap.dedent(
        r"""
        const strictAssert = require("node:assert/strict");
        const elements = {
          "save-ramp-list": { disabled: false },
          "save-sequence": { disabled: false },
          "sequence-document-error": { textContent: "", hidden: true }
        };
        document.getElementById = (id) => elements[id] || null;
        state.rampListEnableOutput = false;
        state.rampListCompletionPulse = null;
        state.rampListSegments = [{
          channels: [1], current: 0.1, start_voltage: 0, stop_voltage: 1,
          step_voltage: 1, delay_ms: 0, hold_ms: 0
        }];
        state.sequenceSteps = [{ action: "wait", seconds: 0 }];
        let saveCalls = 0;
        let serializedNullLoopCount = false;
        saveJsonFile = async () => { saveCalls += 1; };
        renderClientResult = () => {};
        const originalStringify = JSON.stringify;
        JSON.stringify = (value, ...args) => {
          const serialized = originalStringify(value, ...args);
          if (serialized?.includes('"loop_count": null')) serializedNullLoopCount = true;
          return serialized;
        };

        (async () => {
          for (const invalid of ["", "1.5", "1", "0", "-1", "10001"]) {
            state.rampListLoopEnabled = true;
            state.rampListLoopCountDraft = invalid;
            const rampRun = { disabled: false };
            strictAssert.equal(updateWorkflowDocumentValidity("ramp-list", rampRun), false);
            strictAssert.equal(rampRun.disabled, true);
            strictAssert.equal(elements["save-ramp-list"].disabled, true);
            await saveRampList();

            state.sequenceLoopEnabled = true;
            state.sequenceLoopCountDraft = invalid;
            const sequenceRun = { disabled: false };
            strictAssert.equal(updateWorkflowDocumentValidity("sequence", sequenceRun), false);
            strictAssert.equal(sequenceRun.disabled, true);
            strictAssert.equal(elements["save-sequence"].disabled, true);
            strictAssert.match(elements["sequence-document-error"].textContent, /loop_count/);
            strictAssert.equal(elements["sequence-document-error"].hidden, false);
            await saveSequenceFile();
          }
          strictAssert.equal(saveCalls, 0);
          strictAssert.equal(serializedNullLoopCount, false);
        })().catch((error) => {
          process.nextTick(() => { throw error; });
        });
        """
    )
    run_frontend_javascript_assertions(assertions)


def test_static_snapshot_has_no_sequence_loop_state_or_control() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    workflows_js = read_static_javascript("workflows.js")
    snapshot = extract_js_function(workflows_js, "renderSnapshotForm")
    sequence = extract_js_function(workflows_js, "renderSequenceForm")

    assert "loop" not in snapshot.lower()
    assert "sequenceLoopCount" not in snapshot
    assert sequence.index("editor.appendChild(toolbar)") < sequence.index("renderLoopControl({")
    assert sequence.index("renderLoopControl({") < sequence.index("state.sequenceSteps.forEach")


def test_static_commands_disable_by_selected_resource_model():
    _index_html, app_js, _styles_css = read_static_texts()
    state_js = read_static_javascript("state.js")
    command_support_js = read_static_javascript("command-support.js")
    command_form_js = read_static_javascript("command-form.js")
    device_js = read_static_javascript("device-resource.js")

    assert "commandSupportByModel: {}" in state_js
    assert "channelCapabilitiesByModel: {}" in state_js
    assert "resourceModels: {}" in state_js
    assert "resourceChannelModels: {}" in state_js
    assert "state.commandSupportByModel = payload.command_support_by_model_id || {};" in command_form_js
    assert "state.channelCapabilitiesByModel = payload.channel_capabilities_by_model_id || {};" in command_form_js
    assert "updateResourceModels(resources);" in app_js
    assert "resource.model_id" in app_js
    assert "function selectedCommandModel()" in device_js
    assert "function detectedCommandModelForResource(resource)" in device_js
    assert "state.commandSupportByModel?.[model]?.[name]" in command_support_js
    assert "const model = selectedCommandModel();" in extract_js_function(command_support_js, "selectedCommandSupport")
    assert "const next = supportedModelKey(modelId);" in app_js
    assert "!next.stale && updateResourceModel(next.resource, next.model_id, next.model)" in app_js
    assert "support?.real === false" in command_support_js
    assert 'button.disabled = Boolean(effectiveMeta.disabled || state.workflowControl.phase !== "idle");' in command_form_js
    assert "runButton.disabled = Boolean(meta.disabled || channelGuard || tripGuard || ratingGuard || setGuard || triggerControlGuard || triggerFireWaitGuard || workflowPulseGuard);" in app_js
    assert 'error: "Command unavailable"' in app_js


def test_static_frontend_consumes_exact_live_support_without_exposing_validation_controls():
    index_html, app_js, _styles_css = read_static_texts()
    state_js = read_static_javascript("state.js")
    basic_controls_js = read_static_javascript("basic-controls.js")
    command_support_js = read_static_javascript("command-support.js")
    command_form_js = read_static_javascript("command-form.js")
    device_js = read_static_javascript("device-resource.js")
    load_commands = extract_js_function(command_form_js, "loadCommands")
    command_meta = extract_js_function(command_support_js, "commandMeta")
    capture_support = extract_js_function(app_js, "captureResourceLiveSupport")
    capture_workspace = extract_js_function(app_js, "captureWorkspaceResult")
    clear_stale = extract_js_function(app_js, "clearStaleResourceLiveSupport")
    update_model = extract_js_function(app_js, "updateResourceModel")
    model_changed = extract_js_function(device_js, "handleExpectedModelChanged")
    runtime_payload = extract_js_function(command_form_js, "runtimePayload")
    render_basic = extract_js_function(basic_controls_js, "renderBasicChannelActionState")
    render_basic_output = extract_js_function(basic_controls_js, "renderBasicOutputControlState")

    assert "liveSupportByModel: {}" in state_js
    assert "resourceLiveSupport: null" in state_js
    assert "resourceLiveSupportContext: null" in state_js
    assert "state.liveSupportByModel = payload.live_support_by_model_id || {};" in load_commands
    assert '["capabilities", "identify", "verify"].includes(job.command)' in capture_workspace
    assert "captureResourceLiveSupport(job, resource);" in capture_workspace
    assert 'resource !== valueOrNull("resource")' in capture_support
    assert "liveSupport.evaluated" not in capture_support
    assert "state.resourceLiveSupport = liveSupport;" in capture_support
    assert "model_id: liveSupport.model_id || null" in capture_support
    assert "transport_scope: liveSupport.transport_scope" in capture_support
    assert "backend_scope: liveSupport.backend_scope" in capture_support
    assert "state.resourceLiveSupportContext.resource === resource" in clear_stale
    assert "state.resourceLiveSupport = null;" in clear_stale
    assert "state.resourceLiveSupportContext.model_id !== modelId" in update_model
    assert "state.resourceLiveSupport = null;" in update_model
    assert "exactCommand.product_open !== true" in command_meta
    assert "exactCommand.policy_exempt" in command_meta
    assert "commandSupport.offline_only" in command_support_js
    assert "Offline utility; live exact scope is not applicable." in command_support_js
    assert 't("support.scope.not_evaluated")' in command_meta
    assert '"support.status.pending_live_validation"' in command_support_js
    assert '"support.status.no_product_open_scope"' in command_support_js
    assert "Identity/status diagnostic; exact model feature scope is not required." in command_support_js
    assert "state.resourceLiveSupport" not in model_changed
    assert 'const setMeta = commandMeta("set");' in render_basic
    assert "setButton.disabled = Boolean(unsupported || setMeta.disabled);" in render_basic
    assert 'commandMeta(enabled ? "output-off" : "output-on")' in render_basic_output
    assert "commandMetaForState.disabled" in render_basic_output
    assert "support_policy_mode" not in runtime_payload
    assert "validation" not in runtime_payload
    assert "backend-selector" not in index_html
    assert "validation-allow-pending-live-support" not in index_html
    assert "validation-allow-pending-live-support" not in app_js


def test_static_channel_capability_guards_use_metadata():
    _index_html, app_js, styles_css = read_static_texts()
    command_support_js = read_static_javascript("command-support.js")
    device_js = read_static_javascript("device-resource.js")
    command_form_js = read_static_javascript("command-form.js")

    assert "const DEFAULT_CHANNELS = [1, 2, 3];" in app_js
    assert "function supportedChannelsForCurrentModel()" in command_support_js
    assert "if (!capability || !capability.channels.length) return [...defaultChannels];" in command_support_js
    assert "function channelCapabilityForCurrentModel()" in command_support_js
    assert "function channelCapabilityForModel(model)" in command_support_js
    assert "function selectedChannelModel()" in device_js
    assert "function detectedChannelModelForResource(resource)" in device_js
    assert "metadata.channels" in command_support_js
    assert "metadata.output_control_scope" in command_support_js
    assert "Array.isArray(metadata)" in command_support_js
    assert "? modelId : null" in extract_js_function(command_support_js, "supportedModelKey")
    assert "function currentChannelCapabilityModel()" in command_support_js
    assert "return selectedChannelModel();" in extract_js_function(command_support_js, "currentChannelCapabilityModel")
    assert "function channelModelKey(model)" in command_support_js
    assert "state.resourceChannelModels[resource] = nextChannelModel;" in app_js
    assert "channelAvailabilityGuardReason(command, parameters)" in extract_js_function(app_js, "selectedCommandPresentation")
    assert "channelAvailabilityGuardReason(state.selected, payload.parameters)" in app_js
    assert "item.disabled = true;" in command_form_js
    assert "channelUnsupportedReason(option)" in command_form_js
    assert 'error: "Unsupported channel"' in app_js
    assert ".basic-channel-card.unsupported" in styles_css
    assert ".live-card.unsupported" in styles_css


def test_static_basic_and_live_disable_unsupported_channels():
    _index_html, app_js, _styles_css = read_static_texts()
    basic_controls_js = read_static_javascript("basic-controls.js")
    live_data_js = read_static_javascript("live-data.js")

    run_set = extract_js_function(app_js, "runBasicSet")
    run_output = extract_js_function(app_js, "runBasicOutput")
    render_live = extract_js_function(live_data_js, "renderChannelCard")
    render_basic = extract_js_function(basic_controls_js, "renderBasicChannelActionState")
    all_on = extract_js_function(basic_controls_js, "basicAllOutputsOn")
    clear_errors = extract_js_function(basic_controls_js, "clearResolvedBasicErrors")

    assert "const unsupported = channelUnsupportedReason(channel);" in run_set
    assert 'failBasicAction(actionKey, "Unsupported channel"' in run_set
    assert "const unsupported = channelUnsupportedReason(channel);" in run_output
    assert 'failBasicAction(basicActionKey("output", channel), "Unsupported channel"' in run_output
    assert 'card.className = "live-card unsupported";' in render_live
    assert 'card.setAttribute("aria-disabled", "true");' in render_live
    assert 'measuredVoltage: "N/A"' in render_live
    assert 'measuredCurrent: "N/A"' in render_live
    assert "Unsupported" in render_live
    assert 'card.classList.toggle("unsupported", Boolean(unsupported));' in render_basic
    assert 'card.setAttribute("aria-disabled", String(Boolean(unsupported)));' in render_basic
    assert "setButton.disabled = Boolean(unsupported || setMeta.disabled);" in render_basic
    assert "supportedChannelsForCurrentModel().every" in all_on
    assert "supportedChannelsForCurrentModel().every" in clear_errors


def test_static_e3646a_output_hint_is_global_for_supported_channels():
    _index_html, app_js, _styles_css = read_static_texts()
    command_support_js = read_static_javascript("command-support.js")

    output_title = extract_js_function(command_support_js, "outputControlTitle")
    all_title = extract_js_function(command_support_js, "outputAllControlTitle")

    assert 'outputControlScopeForCurrentModel() === "global"' in output_title
    assert 'outputControlScopeForCurrentModel() === "global"' in all_title
    assert "globalOutputHintText()" in output_title
    assert "globalOutputHintText()" in all_title
    assert 'model === "E3646A"' not in output_title
    assert 'model === "E3646A"' not in all_title
    assert "function outputControlScopeForCurrentModel()" in command_support_js
    assert "output_control_scope" in extract_js_function(command_support_js, "outputControlScopeForCurrentModel")
    global_hint = extract_js_function(command_support_js, "globalOutputHintText")
    assert 't("basic_controls.tooltip.global_output_model"' in global_hint
    assert 't("basic_controls.tooltip.global_output")' in global_hint


def test_static_trip_guard_and_clear_protection_recovery_contract():
    _index_html, app_js, _styles_css = read_static_texts()
    live_data_js = read_static_javascript("live-data.js")

    clear_block = extract_param_block(app_js, "clear-protection")
    assert_param_contract(clear_block, "channel", "select", ["", "all", "1", "2", "3"])
    assert 'value: ""' in clear_block
    assert 'const TRIP_GUARDED_COMMANDS = new Set(["output-on", "cycle-output", "ramp", "ramp-list", "smoke-output", "apply"]);' in app_js
    assert 'if (command === "apply" && parameters.no_output === true) return "";' in app_js
    assert "if (!panel || panel.stale || !resource || panel.resource !== resource) return [];" in app_js
    assert "function setAdvancedCommandsExpanded(expanded)" in app_js
    assert "setAdvancedCommandsExpanded(panel.hidden);" in app_js
    assert "setAdvancedCommandsExpanded(true);" in app_js
    assert 'state.activeCategory = "protection";' in app_js
    assert 'selectCommand("clear-protection");' in app_js
    assert "clear.dataset.clearProtectionChannel = String(channel.channel);" in live_data_js
    assert 'workspace.scrollIntoView({ behavior: "smooth", block: "nearest" });' in app_js
    assert "focusTarget.focus({ preventScroll: true });" in app_js
    assert 'input.value = channels.length === 1 ? String(channels[0]) : "";' in app_js
    assert 't("live_data.protection.trip")' in live_data_js
    assert 't("live_data.protection.clear")' in live_data_js


def test_static_channel_confirmation_and_job_detail_contracts():
    _index_html, app_js, styles_css = read_static_texts()
    command_form_js = read_static_javascript("command-form.js")
    workflows_js = read_static_javascript("workflows.js")

    assert 'set: webuiCommandForm.setOutputParams()' in app_js
    assert 'export function setOutputParams()' in command_form_js
    assert "{ ...params[1], optional: true }" in command_form_js
    assert "{ ...params[2], optional: true }" in command_form_js
    assert "const SET_PARTIAL_GUIDANCE =" in command_form_js
    render_form = extract_js_function(command_form_js, "renderForm")
    append_set_guidance = extract_js_function(command_form_js, "appendSetGuidance")
    render_guidance = extract_js_function(command_form_js, "renderCommandGuidance")
    assert 'if (command === "set" && param.name === "current") appendSetGuidance(label);' in render_form
    assert 'guidance.className = "field-description set-field-guidance";' in append_set_guidance
    assert "guidance.textContent = SET_PARTIAL_GUIDANCE;" in append_set_guidance
    assert "SET_PARTIAL_GUIDANCE" not in render_guidance
    field_description_css = styles_css[styles_css.index(".field-description {"):styles_css.index(".command-notes {")]
    assert "text-transform: none;" in field_description_css
    assert "setRequiresSetpointGuardReason(command, parameters)" in extract_js_function(app_js, "selectedCommandPresentation")
    assert '"smoke-output": webuiCommandForm.smokeOutputParams()' in app_js
    assert_param_contract(app_js, "channel", "select", ["1", "2", "3"])
    assert_param_contract(workflows_js, "voltage", "number")
    assert_param_contract(workflows_js, "current", "number")
    assert_param_contract(workflows_js, "no_output", "checkbox")
    assert_param_contract(workflows_js, "duration_ms", "number")
    for command in ("output-on", "output-off", "cycle-output"):
        assert_param_contract(extract_param_block(app_js, command), "channel", "select", ["all", "1", "2", "3"])
    params_block = app_js[app_js.index("const PARAMS = {"):app_js.index("function defaultRampSegment()")]
    assert '"protection-set"' in params_block
    protection_block = extract_param_block(app_js, "protection-set")
    assert_param_contract(protection_block, "ocp_delay", "number")
    assert_param_contract(protection_block, "ocp_delay_trigger", "select", ["", "setting-change", "cc-transition"])
    for command in WEBUI_HIDDEN_LIVE_DATA_COMMANDS:
        assert f'"{command}"' not in params_block

    assert 'if (param.name === "channel")' in command_form_js
    assert 'if (param.parser === "intList")' in command_form_js
    assert 'if (param.parser === "numberList")' in command_form_js
    assert 'if (value === "all") return value;' in command_form_js
    assert 'return /^[1-9]\\d*$/.test(value) ? Number(value) : value;' in command_form_js

    assert "const meta = commandMeta(state.selected);" in app_js
    assert "meta.requires_confirm && state.executionMode === \"real\" && !payload.runtime.confirm" in app_js
    assert 'error: "Confirmation required"' in app_js
    assert "runtime: { confirm: false }" in app_js

    assert "const job = await webuiApi.fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);" in app_js
    for key in ("job_id", "command", "status", "runtime", "parameters", "result", "error"):
        assert f"{key}: job.{key}" in app_js


def test_static_form_has_no_advanced_json_injection():
    index_html, app_js, _styles_css = read_static_texts()

    assert "Advanced JSON" not in index_html
    assert "advanced-json" not in index_html
    assert "advanced-json" not in app_js
    assert "Object.assign(payload" not in app_js


def test_static_trigger_forms_have_advanced_parameters():
    _index_html, app_js, _styles_css = read_static_texts()
    command_form_js = read_static_javascript("command-form.js")
    params_block = app_js[app_js.index("const PARAMS = {"):app_js.index("function defaultRampSegment()")]

    for command in (
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    ):
        assert f'"{command}"' in params_block

    assert_param_contract(extract_param_block(app_js, "trigger-pulse"), "pins", "select")
    assert 'parser: "intList"' in app_js
    assert_param_contract(command_form_js, "voltage_list", "text")
    assert_param_contract(command_form_js, "current_list", "text")
    assert_param_contract(command_form_js, "dwell_list", "text")
    assert 'parser: "numberList"' in command_form_js
    assert_param_contract(extract_js_function(command_form_js, "triggerListParams"), "completion_pulse_pins", "select")
    assert_param_contract(extract_js_function(command_form_js, "triggerStepParams"), "source", "select", ["bus", "immediate"])
    assert_param_contract(extract_js_function(command_form_js, "triggerListParams"), "source", "select", ["bus", "immediate"])
    assert_param_contract(command_form_js, "wait_timeout_ms", "number")
    assert_param_contract(command_form_js, "leave_trigger_configured", "checkbox")


def test_static_trigger_forms_document_behavior_and_key_fields():
    _index_html, app_js, styles_css = read_static_texts()
    command_form_js = read_static_javascript("command-form.js")

    summaries = {
        "trigger-pulse": "Configures the selected rear pins as trigger outputs",
        "trigger-status": "Read-only E36312A query",
        "trigger-step": "Configures and arms a STEP transient",
        "trigger-list": "Configures and arms a LIST waveform",
        "trigger-fire": "Used only to abort this output channel",
        "trigger-abort": "Aborts Trigger/LIST execution",
    }
    blocks = {
        "trigger-pulse": extract_param_block(app_js, "trigger-pulse"),
        "trigger-status": extract_param_block(app_js, "trigger-status"),
        "trigger-step": extract_js_function(command_form_js, "triggerStepParams"),
        "trigger-list": extract_js_function(command_form_js, "triggerListParams"),
        "trigger-fire": extract_param_block(app_js, "trigger-fire"),
        "trigger-abort": extract_param_block(app_js, "trigger-abort"),
    }
    for command, summary in summaries.items():
        assert summary in blocks[command]
        assert "description:" in blocks[command]

    for field in ("source", "fire", "wait_complete", "poll_ms", "wait_timeout_ms",
                  "exclusive_pins", "leave_trigger_configured"):
        field_start = command_form_js.index(f'name: "{field}"')
        assert "description:" in command_form_js[field_start:field_start + 500]
    for field in ("voltage_list", "current_list", "dwell_list", "count", "completion_pulse_pins"):
        assert f'name: "{field}"' in blocks["trigger-list"]
        field_start = blocks["trigger-list"].index(f'name: "{field}"')
        assert "description:" in blocks["trigger-list"][field_start:field_start + 450]

    assert "pin1" not in extract_js_function(command_form_js, "triggerStepParams")
    assert "pin1" not in extract_js_function(command_form_js, "triggerListParams")
    assert 'label: "Abort target channel"' in blocks["trigger-fire"]
    assert "It does not turn outputs off" in blocks["trigger-abort"]
    assert "instrument error-queue entries" in blocks["trigger-abort"]

    render_form = extract_js_function(command_form_js, "renderForm")
    command_form_js = read_static_javascript("command-form.js")
    append_notes = extract_js_function(command_form_js, "appendCommandNotes")
    assert "if (!TRIGGER_COMMANDS.has(command) && !param.compactHelp) appendFieldDescription(label, param);" in render_form
    assert "if (TRIGGER_COMMANDS.has(command)) appendCommandNotes(form, command, PARAMS[command] || [], commandMeta);" in render_form
    assert 'notes.className = "command-notes";' in append_notes
    assert 'title.textContent = "Command notes";' in append_notes
    assert "summary.textContent = commandMeta(command).description || \"\";" in append_notes
    assert "const descriptions = params.filter((param) => param.description);" in append_notes
    assert "term.textContent = param.label;" in append_notes
    assert "detail.textContent = param.description;" in append_notes
    assert ".command-notes {" in styles_css
    assert "grid-column: 1 / -1;" in styles_css[styles_css.index(".command-notes {"):styles_css.index(".ramp-list-editor {")]


def test_static_sequence_trigger_pulse_leave_configured_documents_restore_semantics():
    _index_html, app_js, styles_css = read_static_texts()
    workflows_js = read_static_javascript("workflows.js")

    definitions = extract_js_function(workflows_js, "sequenceActionDefinitions")
    sequence_fields = extract_js_function(workflows_js, "sequenceStepFields")

    assert 'name: "leave_trigger_configured"' in definitions
    assert "It does not keep a trigger armed." in definitions
    assert "may affect later Sequence steps or other BUS triggers" in definitions
    assert "webuiCommandForm.appendFieldDescription(" in sequence_fields
    assert "`form.description.sequence.${step.action.replaceAll(\"-\", \"_\")}.${definition.name}`" in sequence_fields
    assert ".sequence-step-fields .checkbox-field" not in styles_css
    assert ".form-grid .checkbox-field .field-description" in styles_css


def test_static_trigger_controls_disable_invalid_combinations_and_immediate_fire():
    _index_html, app_js, _styles_css = read_static_texts()

    update_state = extract_js_function(app_js, "updateSelectedCommandState")
    sync = extract_js_function(app_js, "syncTriggerImmediateControls")
    guard = extract_js_function(app_js, "triggerControlGuardReason")

    assert "syncTriggerImmediateControls(state.selected)" in update_state
    assert "selectedCommandPresentation(state.selected, parameters)" in update_state
    assert "triggerControlGuardReason(command, parameters)" in extract_js_function(app_js, "selectedCommandPresentation")
    assert "meta.disabled || channelGuard || tripGuard || ratingGuard || setGuard || triggerControlGuard || triggerFireWaitGuard" in update_state
    assert "triggerArmOnlyGuardReason" not in app_js
    assert '["trigger-step", "trigger-list"]' in guard
    assert "fire.checked = false" in sync
    assert "fire.disabled = immediate" in sync
    assert 't("command.guard.trigger_bus_wait_requires_fire")' in guard
    assert 't("command.guard.trigger_list_started_requires_leave")' in guard


def test_static_trigger_guidance_explains_global_fire_and_wait_semantics():
    index_html, app_js, styles_css = read_static_texts()

    guidance = extract_js_function(read_static_javascript("command-form.js"), "renderCommandGuidance")
    fire_guard = extract_js_function(app_js, "triggerFireWaitGuardReason")

    assert 'id="command-guidance"' in index_html
    assert index_html.index('id="command-guidance"') < index_html.index('id="command-form"')
    assert "command.guidance.trigger_fire" in guidance
    assert "command.guidance.trigger_step" in guidance
    assert 't("command.guard.trigger_fire_wait_requires_channel")' in fire_guard
    assert ".command-guidance {" in styles_css
    command_guidance_css = styles_css[styles_css.index(".command-guidance {"):styles_css.index(".trigger-list-editor {")]
    assert "text-transform: none;" in command_guidance_css


def test_static_trigger_status_has_human_readable_workspace_summary():
    _index_html, app_js, _styles_css = read_static_texts()
    workspace_js = read_static_javascript("results.js")

    render = extract_js_function(app_js, "renderWorkspaceSummary")
    summary = extract_js_function(workspace_js, "renderTriggerStatusWorkspaceSummary")

    assert "webuiResults.renderWorkspaceJob(container, job, context, {" in render
    assert "renderTriggerStatusWorkspaceSummary(container, job.result, helpers.formatNum);" in workspace_js
    for field in ("digital_pins", "trigger_output_bus_enabled", "triggered_voltage", "triggered_current", "step_mode", "terminate_last"):
        assert field in summary


def test_static_trigger_list_uses_three_channel_workspace_editor():
    _index_html, app_js, styles_css = read_static_texts()
    trigger_list_js = read_static_javascript("trigger-list.js")
    workflows_js = read_static_javascript("workflows.js")
    command_form_js = read_static_javascript("command-form.js")

    render = extract_js_function(workflows_js, "renderTriggerListForm")
    payload = extract_js_function(command_form_js, "parameterPayload")
    validator = extract_js_function(trigger_list_js, "validateTriggerListWorkspace")

    for text in ("Load Trigger List", "Save Trigger List", "Add Step", "Channel ${channel}", "BOST", "EOST"):
        assert text in render
    assert "button.dataset.triggerListChannel = String(channel);" in render
    assert "steps.push({ ...steps[steps.length - 1] })" in workflows_js
    assert "steps.length >= 100" in workflows_js
    assert "steps.length <= 1" in workflows_js
    assert 'if (input.type === "number") input.step = "any";' in workflows_js
    for field in ("bost_list", "eost_list", "trigger_output_pins", "trigger_output_polarity"):
        assert field in payload
    assert "powers-tool-trigger-list-workspace" in validator
    assert 'exact(document.channels, ["1", "2", "3"]' in validator
    assert "contains unknown or missing fields" in validator
    assert "return webuiTriggerListDocument.triggerListWorkspaceDocument(state);" in workflows_js
    assert "return webuiTriggerListDocument.validateTriggerListWorkspace(document);" in workflows_js
    assert ".trigger-list-editor {" in styles_css
    assert '.trigger-list-tabs button[data-trigger-list-channel]' in styles_css
    assert '.trigger-list-tabs button[data-trigger-list-channel="1"]' in styles_css
    assert '.trigger-list-tabs button[data-trigger-list-channel="2"]' in styles_css
    assert '.trigger-list-tabs button[data-trigger-list-channel="3"]' in styles_css


def test_static_trigger_list_documents_restore_and_pulse_pin_guard():
    _index_html, app_js, _styles_css = read_static_texts()

    guidance = extract_js_function(read_static_javascript("command-form.js"), "renderCommandGuidance")
    guard = extract_js_function(app_js, "triggerControlGuardReason")

    assert "command.guidance.trigger_list" in guidance
    assert 't("command.guard.trigger_list_pulse_requires_pins")' in guard
