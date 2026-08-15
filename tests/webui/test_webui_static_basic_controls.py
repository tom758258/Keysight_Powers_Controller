"""Direct behavior checks for Basic control presentation helpers."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_basic_controls_module_has_explicit_dependencies_and_preserves_action_labels() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    basic_controls_js = read_static_javascript("basic-controls.js")

    assert 'from "./basic-controls.js"' in app_js
    assert "fetch(" not in basic_controls_js
    assert "EventSource" not in basic_controls_js
    assert "createBasicControls" in basic_controls_js

    run_webui_module_assertions(
        r"""
const basic = globalThis.webuiBasicControls.createBasicControls({
  state: { livePanel: null, basicActionStates: {}, basicJobActions: {}, executionMode: "simulate" },
  defaultChannels: [1, 2, 3],
  e3646aCapabilityError: "capability error",
  e3646aGlobalOutputDescription: "global output",
  valueOrNull: () => null,
  basicOutputPresentation: () => ({ mode: "normal", capability: { channels: [1, 2, 3] } }),
  supportedChannelsForCurrentModel: () => [1, 2, 3],
  channelUnsupportedReason: () => "",
  commandMeta: () => ({ disabled: false }),
  outputControlTitle: () => "",
  outputAllControlTitle: () => "",
  basicSetpointValues: () => ({ ok: false }),
  refreshBasicInputConstraints: () => {},
  validateBasicInput: () => {},
  eventSummary: () => "event"
});
strictAssert.equal(basic.basicActionKey("output", "all"), "output:all");
strictAssert.match(basic.basicActionDisplayName("set:2"), /CH2/);
strictAssert.match(basic.basicActionDisplayName("output:all"), /All/);
strictAssert.match(basic.basicStatusText("success"), /completed/i);
strictAssert.match(basic.basicStatusText("error"), /failed/i);
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("basic-controls.js",),
    )


def test_basic_controls_refresh_uses_explicit_current_action_and_preserves_set_title() -> None:
    run_webui_module_assertions(
        r"""
const { setLocale } = await import(moduleUrls["i18n.js"]);
const statusNode = { textContent: "" };
const createButton = () => {
  const classes = new Set(["basic-toggle", "off"]);
  return {
    disabled: false,
    hidden: false,
    title: "",
    textContent: "",
    attributes: {},
    classList: {
      toggle(name, force) {
        const enabled = force === undefined ? !classes.has(name) : Boolean(force);
        if (enabled) classes.add(name); else classes.delete(name);
        return enabled;
      },
      remove(...names) { names.forEach((name) => classes.delete(name)); },
      contains(name) { return classes.has(name); }
    },
    setAttribute(name, value) { this.attributes[name] = String(value); }
  };
};
const setButton = createButton();
const outputButtons = Object.fromEntries([1, 2, 3].map((channel) => [channel, createButton()]));
const allButton = createButton();
const card = {
  title: "",
  classList: { toggle() {} },
  setAttribute() {},
  querySelector(selector) {
    return selector === "[data-basic-set]" ? setButton : null;
  }
};
globalThis.document = {
  getElementById(id) {
    return id === "basic-command-status" ? statusNode : null;
  },
  querySelector(selector) {
    if (selector === '[data-basic-channel="1"]') return card;
    if (selector === '[data-basic-set="1"]') return setButton;
    if (selector === "[data-basic-all-output]") return allButton;
    const outputMatch = selector.match(/^\[data-basic-output="(\d)"\]$/);
    if (outputMatch) return outputButtons[Number(outputMatch[1])];
    return null;
  }
};
const state = {
  livePanel: {
    resource: "RESOURCE",
    stale: false,
    channels: [
      { channel: 1, output_enabled: true },
      { channel: 2, output_enabled: false },
      { channel: 3, output_enabled: true }
    ]
  },
  basicActionStates: {},
  basicJobActions: {},
  basicStatusActionKey: null,
  executionMode: "simulate"
};
const basic = globalThis.webuiBasicControls.createBasicControls({
  state,
  defaultChannels: [1, 2, 3],
  valueOrNull: () => "RESOURCE",
  basicOutputPresentation: () => ({ mode: "normal", capability: { channels: [1, 2, 3] } }),
  supportedChannelsForCurrentModel: () => [1, 2, 3],
  channelUnsupportedReason: () => "",
  commandMeta: () => ({ disabled: false, live_support_status: "raw support" }),
  outputControlTitle: () => "",
  outputAllControlTitle: () => "",
  basicSetpointValues: () => ({ ok: false }),
  refreshBasicInputConstraints: () => {},
  validateBasicInput: () => {},
  eventSummary: () => "event"
});

basic.setBasicActionState("set:1", "success", { key: "basic_controls.status.completed" });
const completedIdentity = state.basicActionStates["set:1"];
basic.setBasicActionState("output:2", "pending", { key: "basic_controls.status.waiting_readback" }, {
  desiredOutput: true,
  awaitingReadback: true
});
const pendingIdentity = state.basicActionStates["output:2"];
strictAssert.equal(state.basicStatusActionKey, "output:2");
strictAssert.notEqual(statusNode.textContent, "");
strictAssert.match(statusNode.textContent, /Live Data|readback/i);
const englishPendingStatus = statusNode.textContent;

setLocale("zh-TW");
basic.refreshBasicControlsPresentation();
strictAssert.notEqual(statusNode.textContent, englishPendingStatus);
strictAssert.match(statusNode.textContent, /即時資料|讀回/);
strictAssert.equal(state.basicActionStates["set:1"], completedIdentity);
strictAssert.equal(state.basicActionStates["output:2"], pendingIdentity);
strictAssert.equal(pendingIdentity.desiredOutput, true);
strictAssert.equal(pendingIdentity.awaitingReadback, true);
strictAssert.equal(pendingIdentity.status, "pending");

basic.setBasicActionState("set:1", "success", { key: "basic_controls.status.completed" });
strictAssert.equal(setButton.classList.contains("basic-action-success"), true);
strictAssert.notEqual(setButton.title, "");
basic.refreshBasicControlsPresentation();
strictAssert.notEqual(setButton.title, "");
basic.setBasicActionState("set:1", "error", "VISA <raw> detail");
basic.refreshBasicControlsPresentation();
strictAssert.equal(setButton.title, "VISA <raw> detail");

basic.clearBasicActionState("set:1");
strictAssert.equal(state.basicStatusActionKey, null);
strictAssert.notEqual(statusNode.textContent, "");
strictAssert.match(statusNode.textContent, /即時資料|儀器/);
strictAssert.equal(state.basicActionStates["output:2"], pendingIdentity);
setLocale("en");

basic.setBasicActionState("output:1", "success", { key: "basic_controls.status.completed" });
basic.refreshBasicControlsPresentation();
strictAssert.equal(outputButtons[1].classList.contains("on"), true);
strictAssert.equal(outputButtons[1].classList.contains("basic-action-success"), false);
strictAssert.notEqual(outputButtons[1].textContent, "");

state.livePanel.channels[0].output_enabled = false;
basic.refreshBasicControlsPresentation();
strictAssert.equal(outputButtons[1].classList.contains("off"), true);
strictAssert.equal(outputButtons[1].classList.contains("basic-action-success"), false);
strictAssert.notEqual(outputButtons[1].textContent, "");

basic.clearBasicActionState("output:2");
basic.setBasicActionState("output:all", "success", { key: "basic_controls.status.completed" });
basic.refreshBasicControlsPresentation();
strictAssert.equal(allButton.classList.contains("basic-action-success"), false);
strictAssert.deepEqual(
  [1, 2, 3].map((channel) => outputButtons[channel].classList.contains("basic-action-success")),
  [false, false, false]
);
strictAssert.deepEqual(
  [1, 2, 3].map((channel) => outputButtons[channel].classList.contains("on")),
  [false, false, true]
);
strictAssert.deepEqual(
  [1, 2, 3].map((channel) => outputButtons[channel].classList.contains("off")),
  [true, true, false]
);
""",
        ("basic-controls.js", "i18n.js"),
    )


def test_basic_output_tooltips_translate_without_changing_machine_state() -> None:
    run_webui_module_assertions(
        r"""
const { setLocale } = await import(moduleUrls["i18n.js"]);
const state = {
  commands: {},
  commandSupportByModel: { "keysight-model": {} },
  channelCapabilitiesByModel: {
    "keysight-model": { channels: [1, 2], output_control_scope: "per_channel" }
  }
};
let selectedModel = "keysight-model";
const support = globalThis.webuiCommandSupport.createCommandSupport({
  state,
  defaultChannels: [1, 2],
  isNoHardwareMode: () => false,
  selectedPlanningIdentity: () => null,
  physicalModelDisplayName: () => "Model <raw>",
  selectedCommandModel: () => "keysight-model",
  valueOrNull: () => "RESOURCE",
  detectedCommandModelForResource: () => "keysight-model",
  selectedChannelModel: () => selectedModel
});
strictAssert.match(support.outputControlTitle(1, true, true), /CH1/);
strictAssert.match(support.outputControlTitle(1, true, true), /ON/);
strictAssert.match(support.outputControlTitle(1, false, true), /CH1/);
strictAssert.match(support.outputControlTitle(1, false, true), /OFF/);
strictAssert.match(support.outputControlTitle(1, false, false), /CH1/);
strictAssert.match(support.outputControlTitle(1, false, false), /unknown/i);
strictAssert.match(support.outputAllControlTitle(true), /ON/);
strictAssert.match(support.outputAllControlTitle(false), /OFF|unknown/i);

state.channelCapabilitiesByModel["keysight-model"].output_control_scope = "global";
strictAssert.match(support.globalOutputHintText(), /Model <raw>/);
strictAssert.match(support.globalOutputHintText(), /global/i);
selectedModel = null;
strictAssert.match(support.globalOutputHintText(), /global/i);
selectedModel = "keysight-model";
setLocale("zh-TW");
strictAssert.match(support.outputControlTitle(1, true, true), /CH1/);
strictAssert.match(support.outputControlTitle(1, true, true), /ON/);
strictAssert.match(support.outputControlTitle(1, false, true), /CH1/);
strictAssert.match(support.outputControlTitle(1, false, true), /OFF/);
strictAssert.match(support.outputControlTitle(1, false, false), /CH1/);
strictAssert.match(support.outputControlTitle(1, false, false), /未知/);
strictAssert.match(support.outputAllControlTitle(true), /ON/);
strictAssert.match(support.outputAllControlTitle(false), /OFF|未知/);
strictAssert.match(support.outputControlTitle(1, true, true), /Model <raw>/);
strictAssert.match(support.outputAllControlTitle(true), /Model <raw>/);
strictAssert.equal(state.channelCapabilitiesByModel["keysight-model"].output_control_scope, "global");
setLocale("en");
""",
        ("command-support.js", "i18n.js"),
    )
