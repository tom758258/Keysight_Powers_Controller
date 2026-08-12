"""Native-module contracts for WebUI command categories."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_command_catalog_module_is_explicit_and_pure() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    catalog_js = read_static_javascript("command-catalog.js")

    assert 'from "./command-catalog.js"' in app_js
    assert "document" not in catalog_js
    assert "fetch(" not in catalog_js
    assert "EventSource" not in catalog_js


def test_command_catalog_preserves_category_order_and_labels() -> None:
    run_webui_module_assertions(
        r"""
const catalog = globalThis.webuiCommandCatalog;
strictAssert.deepEqual(catalog.COMMAND_CATEGORIES, ["output", "workflow", "protection", "trigger", "artifact", "discovery"]);
strictAssert.deepEqual(catalog.COMMAND_CATEGORY_LABELS, {
  output: "Output", workflow: "Output Workflows", protection: "Protection",
  trigger: "Trigger", artifact: "Snapshot", discovery: "Advanced Diagnostics"
});
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("command-catalog.js",),
    )


def test_command_catalog_localizes_presentation_without_changing_ids() -> None:
    run_webui_module_assertions(
        r"""
const i18n = await import(new URL("./i18n.js", moduleUrls["command-catalog.js"]));
const catalog = globalThis.webuiCommandCatalog;
const ids = [...catalog.COMMAND_CATEGORIES];
strictAssert.equal(catalog.commandCategoryLabel("output"), "Output");
strictAssert.equal(catalog.commandDisplayName("output-on", "Output on"), "Output on");
strictAssert.equal(catalog.commandSourceDisplayName("output-on", "Output on"), "Output on");
strictAssert.equal(catalog.commandDescription("trigger-fire", "raw"), "Send *TRG to an already armed BUS trigger");
i18n.setLocale("zh-TW");
strictAssert.equal(catalog.commandCategoryLabel("output"), "輸出");
strictAssert.equal(catalog.commandDisplayName("output-on", "Output on"), "開啟輸出");
strictAssert.equal(catalog.commandDescription("trigger-fire", "raw"), "將 *TRG 傳送至已準備的 BUS 觸發");
strictAssert.equal(catalog.commandDisplayName("ramp", "Ramp"), "單段逐步輸出");
strictAssert.equal(catalog.commandDisplayName("ramp-list", "Ramp list"), "多段逐步輸出");
strictAssert.equal(catalog.commandDisplayName("cycle-output", "Cycle output"), "短暫開啟輸出");
strictAssert.equal(catalog.commandDisplayName("smoke-output", "Smoke output"), "輸出測試");
strictAssert.equal(
  catalog.commandDescription("ramp", "raw"),
  "讓一個或多個通道以 lockstep 方式逐步調整電壓。"
);
strictAssert.equal(
  catalog.commandDescription("ramp-list", "raw"),
  "依序執行多個逐步輸出區段，各區段可設定通道、電壓範圍、步進量與時間。"
);
strictAssert.equal(catalog.commandDisplayName("sequence", "Sequence"), "序列");
strictAssert.equal(catalog.commandDisplayName("trigger-step", "Trigger step"), "STEP 觸發");
strictAssert.equal(catalog.commandDisplayName("backend-new-command", "Backend New Command"), "Backend New Command");
strictAssert.equal(catalog.commandDescription("backend-new-command", "Raw API description"), "Raw API description");
strictAssert.equal(catalog.commandSourceDisplayName("output-on", "Output on"), "Output on");
strictAssert.equal(i18n.getLocale(), "zh-TW");
strictAssert.deepEqual(catalog.COMMAND_CATEGORIES, ids);
i18n.setLocale("en");
""",
        ("command-catalog.js",),
    )


def test_command_controller_uses_english_source_order_across_locales() -> None:
    run_webui_module_assertions(
        r"""
const i18n = await import(new URL("./i18n.js", moduleUrls["command-catalog.js"]));
class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.textContent = "";
    this.value = "";
    this.className = "";
    this.disabled = false;
    this.dataset = {};
  }
  appendChild(child) { this.children.push(child); return child; }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  querySelectorAll() { return []; }
  set innerHTML(value) {
    strictAssert.equal(value, "");
    this.children = [];
  }
}
const elements = new Map([
  ["command-filter", new FakeElement("input")],
  ["command-categories", new FakeElement()],
  ["command-list", new FakeElement()],
  ["selected-command", new FakeElement()],
  ["command-form", new FakeElement("form")],
  ["command-description", new FakeElement()],
]);
globalThis.document = {
  createElement: (tagName) => new FakeElement(tagName),
  getElementById: (id) => elements.get(id),
};
const workflowIds = ["smoke-output", "sequence", "ramp-list", "cycle-output", "ramp"];
const state = {
  selected: "ramp-list",
  activeCategory: "workflow",
  commands: Object.fromEntries(workflowIds.map((id) => [id, {
    category: "workflow",
    description: id === "cycle-output" ? "Cycle output on then off" : `Raw ${id}`
  }])),
  workflowControl: { phase: "idle" },
};
const catalog = globalThis.webuiCommandCatalog;
const dependencies = {
  state,
  commandCatalog: catalog,
  commandMeta: (name) => state.commands[name] || {},
};
const controller = globalThis.webuiCommandForm.createCommandController(dependencies);
const commandIds = () => elements.get("command-list").children.map(
  (button) => workflowIds.find((id) => button.children[0].textContent === catalog.commandDisplayName(id))
);
const commandLabels = () => elements.get("command-list").children.map((button) => button.children[0].textContent);
const commandButton = (name) => elements.get("command-list").children.find(
  (button) => button.children[0].textContent === catalog.commandDisplayName(name)
);
const expectedIds = ["cycle-output", "ramp", "ramp-list", "sequence", "smoke-output"];
const positiveStatuses = {
  "cycle-output": "Live validated: ASRL / system VISA",
  ramp: "Identity/status diagnostic",
  "ramp-list": "Offline utility",
  sequence: "Simulation supported",
  "smoke-output": "Dry-run supported",
};
Object.entries(positiveStatuses).forEach(([name, status]) => {
  state.commands[name].live_support_status = status;
});

i18n.setLocale("en");
controller.renderCommands();
strictAssert.deepEqual(commandIds(), expectedIds);
strictAssert.deepEqual(commandLabels(), ["Cycle output", "Ramp", "Ramp list", "Sequence", "Smoke output"]);
for (const name of expectedIds) {
  strictAssert.equal(commandButton(name).children[1].textContent, "");
  strictAssert.equal(commandButton(name).disabled, false);
}
state.selected = "cycle-output";
controller.refreshSelectedCommandDescription();
strictAssert.equal(elements.get("command-description").textContent, "Cycle output on then off");
state.commands.ramp.disabled = true;
state.commands.ramp.disabled_reason = "Pending live validation: ASRL / system VISA";
state.commands["smoke-output"].live_support_status = "Connection scope not evaluated";
controller.renderCommands();
strictAssert.equal(commandButton("ramp").children[1].textContent, "Pending live validation: ASRL / system VISA");
strictAssert.equal(commandButton("ramp").disabled, true);
strictAssert.equal(commandButton("smoke-output").children[1].textContent, "Connection scope not evaluated");
strictAssert.equal(commandButton("smoke-output").disabled, false);
state.selected = "ramp";
controller.refreshSelectedCommandDescription();
strictAssert.equal(
  elements.get("command-description").textContent,
  "Ramp one or more channels in lockstep Pending live validation: ASRL / system VISA"
);
state.selected = "smoke-output";
controller.refreshSelectedCommandDescription();
strictAssert.equal(
  elements.get("command-description").textContent,
  "Run guarded output diagnostic Connection scope not evaluated"
);
state.selected = "ramp-list";
for (const name of expectedIds) {
  delete state.commands[name].live_support_status;
}
delete state.commands.ramp.disabled;
delete state.commands.ramp.disabled_reason;
strictAssert.equal(
  elements.get("command-list").children[0].title,
  "Cycle output on then off"
);
const categoryIds = [...catalog.COMMAND_CATEGORIES];

const form = elements.get("command-form");
const formDraft = new FakeElement("input");
formDraft.value = "preserved draft";
form.appendChild(formDraft);
const formIdentity = form.children[0];
i18n.setLocale("zh-TW");
controller.refreshCommandPresentation();
strictAssert.deepEqual(commandIds(), expectedIds);
strictAssert.deepEqual(
  commandLabels(),
  ["短暫開啟輸出", "單段逐步輸出", "多段逐步輸出", "序列", "輸出測試"],
);
strictAssert.equal(
  elements.get("command-list").children[0].title,
  "開啟指定通道，維持設定時間後自動關閉。"
);
state.selected = "cycle-output";
controller.refreshSelectedCommandDescription(["Backend raw guard"]);
strictAssert.equal(
  elements.get("command-description").textContent,
  "開啟指定通道，維持設定時間後自動關閉。 Backend raw guard"
);
strictAssert.equal(
  elements.get("command-description").title,
  elements.get("command-description").textContent
);
strictAssert.equal(
  elements.get("command-description").textContent.startsWith(
    elements.get("command-list").children[0].title
  ),
  true
);
for (const [command, expected] of [
  ["error", "讀取並移除儀器錯誤佇列項目"],
  ["cycle-output", "開啟指定通道，維持設定時間後自動關閉。"],
  ["smoke-output", "設定電壓與電流、短暫開啟並量測輸出，最後關閉輸出並確認狀態。"],
  ["snapshot", "建立硬體快照"],
  ["ramp", "讓一個或多個通道以 lockstep 方式逐步調整電壓。"],
  ["ramp-list", "依序執行多個逐步輸出區段，各區段可設定通道、電壓範圍、步進量與時間。"],
]) {
  state.commands[command] ||= {};
  state.commands[command].description = `Raw API description for ${command}`;
  state.selected = command;
  controller.refreshSelectedCommandDescription();
  strictAssert.equal(elements.get("command-description").textContent, expected);
}
state.commands["backend-new-command"] = {
  category: "workflow",
  description: "Raw API description"
};
state.selected = "backend-new-command";
controller.refreshSelectedCommandDescription();
strictAssert.equal(elements.get("command-description").textContent, "Raw API description");
state.selected = "ramp-list";
i18n.setLocale("en");
state.selected = "cycle-output";
controller.refreshSelectedCommandDescription();
strictAssert.equal(elements.get("command-description").textContent, "Cycle output on then off");
i18n.setLocale("zh-TW");
state.selected = "ramp-list";
strictAssert.equal(state.selected, "ramp-list");
strictAssert.equal(state.activeCategory, "workflow");
strictAssert.equal(form.children[0], formIdentity);
strictAssert.equal(form.children[0].value, "preserved draft");
strictAssert.deepEqual(catalog.COMMAND_CATEGORIES, categoryIds);
strictAssert.deepEqual(
  elements.get("command-categories").children.map((button) => button.textContent),
  categoryIds.map((category) => catalog.commandCategoryLabel(category)),
);

elements.get("command-filter").value = "smoke-output";
controller.renderCommands();
strictAssert.deepEqual(commandIds(), ["smoke-output"]);
elements.get("command-filter").value = catalog.commandDisplayName("ramp-list").toLowerCase();
controller.renderCommands();
strictAssert.deepEqual(commandIds(), ["ramp-list"]);

state.commands = {
  "tie-b": { category: "workflow" },
  "tie-a": { category: "workflow" },
};
elements.get("command-filter").value = "";
const tieController = globalThis.webuiCommandForm.createCommandController({
  ...dependencies,
  commandCatalog: { ...catalog, commandSourceDisplayName: () => "Same English name" },
});
tieController.renderCommands();
strictAssert.deepEqual(
  elements.get("command-list").children.map((button) => button.children[0].textContent),
  [catalog.commandDisplayName("tie-a", "Tie a"), catalog.commandDisplayName("tie-b", "Tie b")],
);
i18n.setLocale("en");
""",
        ("command-catalog.js", "command-form.js"),
    )
