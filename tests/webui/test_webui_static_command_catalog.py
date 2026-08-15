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
strictAssert.deepEqual(
  Object.keys(catalog.COMMAND_CATEGORY_LABELS).sort(),
  [...catalog.COMMAND_CATEGORIES].sort(),
);
for (const category of catalog.COMMAND_CATEGORIES) {
  strictAssert.equal(typeof catalog.commandCategoryLabel(category), "string");
  strictAssert.notEqual(catalog.commandCategoryLabel(category), "");
}
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
const englishCategory = catalog.commandCategoryLabel("output");
const englishDisplay = catalog.commandDisplayName("output-on", "Output on");
const englishSourceDisplay = catalog.commandSourceDisplayName("output-on", "Output on");
const englishDescription = catalog.commandDescription("trigger-fire", "raw");
strictAssert.notEqual(englishCategory, "");
strictAssert.notEqual(englishDisplay, "");
strictAssert.equal(englishSourceDisplay, englishDisplay);
strictAssert.match(englishDescription, /TRG|BUS/);
i18n.setLocale("zh-TW");
strictAssert.notEqual(catalog.commandCategoryLabel("output"), englishCategory);
strictAssert.notEqual(catalog.commandDisplayName("output-on", "Output on"), englishDisplay);
strictAssert.notEqual(catalog.commandDescription("trigger-fire", "raw"), englishDescription);
for (const command of ["ramp", "ramp-list", "cycle-output", "smoke-output", "sequence", "trigger-step"]) {
  strictAssert.notEqual(catalog.commandDisplayName(command, command), "");
}
strictAssert.notEqual(catalog.commandDisplayName("backend-new-command", "Backend New Command"), "");
strictAssert.equal(catalog.commandDescription("backend-new-command", "Raw API description"), "Raw API description");
strictAssert.equal(catalog.commandSourceDisplayName("output-on", "Output on"), englishSourceDisplay);
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
strictAssert.equal(commandLabels().length, expectedIds.length);
commandLabels().forEach((label) => strictAssert.notEqual(label, ""));
for (const name of expectedIds) {
  strictAssert.equal(commandButton(name).children[1].textContent, "");
  strictAssert.equal(commandButton(name).disabled, false);
}
state.selected = "cycle-output";
controller.refreshSelectedCommandDescription();
strictAssert.notEqual(elements.get("command-description").textContent, "");
state.commands.ramp.disabled = true;
state.commands.ramp.disabled_reason = "Pending live validation: ASRL / system VISA";
state.commands["smoke-output"].live_support_status = "Connection scope not evaluated";
controller.renderCommands();
strictAssert.match(commandButton("ramp").children[1].textContent, /ASRL \/ system VISA/);
strictAssert.equal(commandButton("ramp").disabled, true);
strictAssert.notEqual(commandButton("smoke-output").children[1].textContent, "");
strictAssert.equal(commandButton("smoke-output").disabled, false);
state.selected = "ramp";
controller.refreshSelectedCommandDescription();
strictAssert.match(elements.get("command-description").textContent, /ASRL \/ system VISA/);
state.selected = "smoke-output";
controller.refreshSelectedCommandDescription();
strictAssert.notEqual(elements.get("command-description").textContent, "");
state.selected = "ramp-list";
for (const name of expectedIds) {
  delete state.commands[name].live_support_status;
}
delete state.commands.ramp.disabled;
delete state.commands.ramp.disabled_reason;
strictAssert.notEqual(elements.get("command-list").children[0].title, "");
const categoryIds = [...catalog.COMMAND_CATEGORIES];

const form = elements.get("command-form");
const formDraft = new FakeElement("input");
formDraft.value = "preserved draft";
form.appendChild(formDraft);
const formIdentity = form.children[0];
i18n.setLocale("zh-TW");
controller.refreshCommandPresentation();
strictAssert.deepEqual(commandIds(), expectedIds);
strictAssert.equal(commandLabels().length, expectedIds.length);
commandLabels().forEach((label) => strictAssert.notEqual(label, ""));
strictAssert.notEqual(elements.get("command-list").children[0].title, "");
state.selected = "cycle-output";
controller.refreshSelectedCommandDescription(["Backend raw guard"]);
strictAssert.match(elements.get("command-description").textContent, /Backend raw guard/);
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
for (const command of ["error", "cycle-output", "smoke-output", "snapshot", "ramp", "ramp-list"]) {
  state.commands[command] ||= {};
  state.commands[command].description = `Raw API description for ${command}`;
  state.selected = command;
  controller.refreshSelectedCommandDescription();
  strictAssert.notEqual(elements.get("command-description").textContent, "");
  strictAssert.doesNotMatch(elements.get("command-description").textContent, /^Raw API description/);
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
strictAssert.notEqual(elements.get("command-description").textContent, "");
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
