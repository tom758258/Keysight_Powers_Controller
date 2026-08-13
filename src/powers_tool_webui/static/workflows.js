import { t } from "./i18n.js";

export function refreshWorkflowPresentation(root = document) {
  root.querySelectorAll?.("[data-workflow-i18n]").forEach((node) => {
    const params = node.dataset.workflowI18nParams ? JSON.parse(node.dataset.workflowI18nParams) : undefined;
    const text = t(node.dataset.workflowI18n, params, node.dataset.workflowI18nFallback);
    const checkboxText = node.querySelector?.(".checkbox-label-text");
    if (checkboxText) checkboxText.textContent = text;
    else if (node.firstChild?.nodeType === 3) node.firstChild.textContent = text;
    else node.textContent = text;
    if (node.dataset.workflowCompactHelpDescription) refreshCompactCheckboxHelp(node);
  });
  root.querySelectorAll?.("[data-i18n-loop]").forEach((node) => {
    node.textContent = t(node.dataset.i18nLoop, undefined, node.textContent);
  });
}

function refreshCompactCheckboxHelp(label) {
  const description = t(label.dataset.workflowCompactHelpDescription);
  const input = label.querySelector?.("input") || label.children?.[0];
  const help = label.querySelector?.(".visually-hidden");
  label.title = description;
  if (input) {
    input.title = description;
    input.setAttribute("aria-label", t(label.dataset.workflowCompactHelpAria));
  }
  if (help) help.textContent = description;
}

function workflowText(node, key, fallback, params) {
  node.dataset.workflowI18n = key;
  node.dataset.workflowI18nFallback = fallback;
  if (params) node.dataset.workflowI18nParams = JSON.stringify(params);
  node.textContent = t(key, params, fallback);
  return node;
}

function optionKey(value, rearPins = false, timing = false) {
  const rear = { "": "none", "1": "pin_1", "2": "pin_2", "3": "pin_3", "1,2": "pins_1_2", "1,3": "pins_1_3", "2,3": "pins_2_3", "1,2,3": "all" };
  const common = { "": "none", all: "all", bus: "bus", immediate: "immediate", positive: "positive", negative: "negative", step: "step", segment: "segment", loop: "loop" };
  const name = (rearPins ? rear : common)[value];
  return name ? `form.option.${name}` : null;
}

function localizedOption(option, value, fallback, rearPins = false) {
  const key = optionKey(value, rearPins);
  option.value = value;
  if (key) workflowText(option, key, fallback);
  else option.textContent = fallback;
}

export function createWorkflows({
  state,
  optionalRearPinOptions: OPTIONAL_REAR_PIN_OPTIONS,
  rearPinOptions: REAR_PIN_OPTIONS,
  webuiCommandForm,
  webuiRampListDocument,
  webuiTriggerListDocument,
  openJsonFile,
  saveJsonFile,
  isAbortError,
  rampListJsonExtensions,
  triggerListWorkspaceJsonExtensions,
  renderClientResult,
  optionDisplayName,
  renderForm,
  updateSelectedCommandState,
  rearPinDisplayName,
  parseRearPins,
  renderLoopControl,
  applyWorkflowPulseControlState,
  pulseTimingDisplayName,
  pinsSelectValue,
  applyParameterConstraint,
  supportedChannelsForCurrentModel,
  rampChannelOptions,
  rampChannelOptionLabel,
  selectedChannelModel,
  updateWorkflowDocumentValidity,
  updateRampListPulse
}) {
function defaultTriggerListStep() {
  return webuiTriggerListDocument.defaultTriggerListStep();
}

function defaultTriggerListChannels() {
  return webuiTriggerListDocument.defaultTriggerListChannels();
}

function defaultTriggerListControls() {
  return webuiTriggerListDocument.defaultTriggerListControls();
}

function activeTriggerListDraft() {
  return state.triggerListChannels[String(state.triggerListActiveChannel)];
}

function renderTriggerListForm(form) {
  const editor = document.createElement("div");
  editor.className = "trigger-list-editor";
  const toolbar = document.createElement("div");
  toolbar.className = "trigger-list-toolbar";
  [["workflow.action.load_trigger_list", "Load Trigger List", loadTriggerListWorkspace], ["workflow.action.save_trigger_list", "Save Trigger List", saveTriggerListWorkspace], ["workflow.action.add_step", "Add Step", addTriggerListStep]].forEach(([key, text, handler]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    workflowText(button, key, text);
    button.disabled = text === "Add Step" && activeTriggerListDraft().steps.length >= 100;
    button.addEventListener("click", handler);
    toolbar.appendChild(button);
  });
  editor.appendChild(toolbar);
  const tabs = document.createElement("div");
  tabs.className = "trigger-list-tabs";
  [1, 2, 3].forEach((channel) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `secondary${state.triggerListActiveChannel === channel ? " active" : ""}`;
    button.dataset.triggerListChannel = String(channel);
    workflowText(button, "workflow.channel", `Channel ${channel}`, { channel });
    button.addEventListener("click", () => {
      state.triggerListActiveChannel = channel;
      renderForm("trigger-list");
      updateSelectedCommandState();
    });
    tabs.appendChild(button);
  });
  editor.appendChild(tabs);
  const controls = document.createElement("div");
  controls.className = "trigger-list-controls";
  triggerListControlDefinitions().forEach((definition) => controls.appendChild(triggerListControlField(definition)));
  editor.appendChild(controls);
  const table = document.createElement("table");
  table.className = "trigger-list-table";
  const head = document.createElement("thead");
  const headingRow = document.createElement("tr");
  [
    ["workflow.field.step", "Step"],
    ["workflow.field.voltage", "Voltage (V)"],
    ["workflow.field.current", "Current (A)"],
    ["workflow.field.dwell", "Dwell (s)"],
    ["workflow.field.bost", "BOST"],
    ["workflow.field.eost", "EOST"],
    ["workflow.field.actions", "Actions"]
  ].forEach(([key, text]) => headingRow.appendChild(workflowText(document.createElement("th"), key, text)));
  head.appendChild(headingRow);
  table.appendChild(head);
  const body = document.createElement("tbody");
  activeTriggerListDraft().steps.forEach((step, index) => body.appendChild(triggerListStepRow(step, index)));
  table.appendChild(body);
  editor.appendChild(table);
  form.appendChild(editor);
}

function triggerListControlDefinitions() {
  return [
    { name: "count", label: "Count", type: "number" }, { name: "source", label: "Source", type: "select", options: ["immediate", "bus"] },
    { name: "fire", label: "Fire", type: "checkbox" }, { name: "wait_complete", label: "Wait complete", type: "checkbox" },
    { name: "trigger_output_pins", label: "LIST output pins", type: "select", options: OPTIONAL_REAR_PIN_OPTIONS },
    { name: "trigger_output_polarity", label: "Polarity", type: "select", options: ["positive", "negative"] },
    { name: "exclusive_pins", label: "Exclusive pins", type: "checkbox" }, { name: "poll_ms", label: "Poll (ms)", type: "number" },
    { name: "wait_timeout_ms", label: "Timeout (ms)", type: "number" }, { name: "leave_trigger_configured", label: "Leave configured", type: "checkbox" }
  ];
}

function triggerListControlField(definition) {
  const input = document.createElement(definition.type === "select" ? "select" : "input");
  if (definition.type === "select") {
    definition.options.forEach((value) => {
      const option = document.createElement("option");
      localizedOption(option, value, definition.name === "trigger_output_pins" ? rearPinDisplayName(value) : optionDisplayName(value), definition.name === "trigger_output_pins");
      input.appendChild(option);
    });
  } else input.type = definition.type;
  const value = definition.name === "count" ? activeTriggerListDraft().count : state.triggerListControls[definition.name];
  if (definition.type === "checkbox") input.checked = Boolean(value);
  else input.value = definition.name === "trigger_output_pins" ? pinsSelectValue(value) : value ?? "";
  if (definition.name === "count") { input.min = "1"; input.max = "256"; input.step = "1"; }
  if (definition.name === "poll_ms") { input.min = "50"; input.step = "1"; }
  if (definition.name === "wait_timeout_ms") { input.min = "1"; input.step = "1"; }
  input.id = `param-${definition.name}`;
  if (definition.name === "fire" && state.triggerListControls.source === "immediate") input.disabled = true;
  input.addEventListener("change", () => updateTriggerListControl(definition, input));
  input.addEventListener("input", () => updateTriggerListControl(definition, input));
  const label = definition.type === "checkbox"
    ? webuiCommandForm.createCheckboxField(input, definition.label)
    : document.createElement("label");
  label.dataset.workflowI18n = `workflow.field.${definition.name}`;
  label.dataset.workflowI18nFallback = definition.label;
  const checkboxText = label.querySelector?.(".checkbox-label-text");
  if (checkboxText) checkboxText.textContent = t(`workflow.field.${definition.name}`, undefined, definition.label);
  if (definition.type !== "checkbox") {
    workflowText(label, `workflow.field.${definition.name}`, definition.label);
    label.appendChild(input);
  }
  return label;
}

function triggerListStepRow(step, index) {
  const row = document.createElement("tr");
  const number = document.createElement("td");
  number.textContent = String(index + 1);
  row.appendChild(number);
  ["voltage", "current", "dwell", "bost", "eost"].forEach((name) => {
    const cell = document.createElement("td");
    const input = document.createElement("input");
    input.type = ["bost", "eost"].includes(name) ? "checkbox" : "number";
    if (input.type === "checkbox") input.checked = step[name]; else input.value = String(step[name]);
    if (input.type === "number") input.step = "any";
    if (name === "voltage" || name === "current") input.min = "0";
    if (name === "dwell") { input.min = "0.01"; input.max = "3600"; }
    const update = () => { step[name] = input.type === "checkbox" ? input.checked : Number(input.value); updateSelectedCommandState(); };
    input.addEventListener("input", update);
    input.addEventListener("change", update);
    cell.appendChild(input);
    row.appendChild(cell);
  });
  const actions = document.createElement("td");
  [["common.up", "Up", -1, index === 0], ["common.down", "Down", 1, index === activeTriggerListDraft().steps.length - 1], ["common.remove", "Remove", 0, activeTriggerListDraft().steps.length === 1]].forEach(([key, text, offset, disabled]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    workflowText(button, key, text);
    button.disabled = disabled;
    button.addEventListener("click", () => offset === 0 ? removeTriggerListStep(index) : moveTriggerListStep(index, offset));
    actions.appendChild(button);
  });
  row.appendChild(actions);
  return row;
}

function updateTriggerListControl(definition, input) {
  const value = definition.type === "checkbox" ? input.checked : definition.type === "number" ? (input.value === "" ? null : Number(input.value)) : definition.name === "trigger_output_pins" ? parseRearPins(input.value) : input.value;
  if (definition.name === "count") activeTriggerListDraft().count = value; else state.triggerListControls[definition.name] = value;
  if (definition.name === "source" && value === "immediate") state.triggerListControls.fire = false;
  if (definition.name === "source") renderForm("trigger-list");
  updateSelectedCommandState();
}

function addTriggerListStep() {
  const steps = activeTriggerListDraft().steps;
  if (steps.length >= 100) return;
  steps.push({ ...steps[steps.length - 1] });
  renderForm("trigger-list");
  updateSelectedCommandState();
}

function removeTriggerListStep(index) {
  const steps = activeTriggerListDraft().steps;
  if (steps.length <= 1) return;
  steps.splice(index, 1);
  renderForm("trigger-list");
  updateSelectedCommandState();
}

function moveTriggerListStep(index, offset) {
  const steps = activeTriggerListDraft().steps;
  const target = index + offset;
  if (target < 0 || target >= steps.length) return;
  [steps[index], steps[target]] = [steps[target], steps[index]];
  renderForm("trigger-list");
  updateSelectedCommandState();
}

function renderRampListForm(form) {
  const editor = document.createElement("div");
  editor.className = "ramp-list-editor";
  const toolbar = document.createElement("div");
  toolbar.className = "ramp-list-toolbar";
  [
    ["workflow.action.load_ramp_list", "Load Ramp List", loadRampList],
    ["workflow.action.save_ramp_list", "Save Ramp List", saveRampList],
    ["workflow.action.add_ramp_segment", "Add Ramp Segment", addRampSegment]
  ].forEach(([key, text, handler]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    workflowText(button, key, text);
    if (text === "Save Ramp List") button.id = "save-ramp-list";
    button.disabled = text === "Add Ramp Segment" && state.rampListSegments.length >= 10;
    button.addEventListener("click", handler);
    toolbar.appendChild(button);
  });
  editor.appendChild(toolbar);
  const enableInput = document.createElement("input");
  enableInput.type = "checkbox";
  enableInput.id = "ramp-list-enable-output";
  enableInput.checked = state.rampListEnableOutput;
  enableInput.addEventListener("change", () => {
    state.rampListEnableOutput = enableInput.checked;
    updateSelectedCommandState();
  });
  const enableLabel = webuiCommandForm.createCheckboxField(enableInput, "Auto-enable output for each channel", ["ramp-list-enable-output-field"]);
  enableLabel.dataset.workflowI18n = "workflow.field.enable_each_channel";
  enableLabel.dataset.workflowI18nFallback = "Auto-enable output for each channel";
  enableLabel.querySelector(".checkbox-label-text").textContent = t("workflow.field.enable_each_channel");
  webuiCommandForm.configureCompactCheckboxHelp(enableLabel, enableInput, {
    ariaLabel: t("ramp_list.aria.enable_each_channel"),
    helpId: "ramp-list-enable-output-help",
    description: t("ramp_list.help.enable_each_channel")
  });
  enableLabel.dataset.workflowCompactHelpAria = "ramp_list.aria.enable_each_channel";
  enableLabel.dataset.workflowCompactHelpDescription = "ramp_list.help.enable_each_channel";
  editor.appendChild(enableLabel);
  if (selectedChannelModel?.() === "keysight-e3646a") {
    const globalOutputNote = document.createElement("small");
    globalOutputNote.id = "ramp-list-e3646a-output-note";
    globalOutputNote.className = "field-description";
    workflowText(
      globalOutputNote,
      "ramp_list.note.e3646a_global_output",
      "E3646A output enable is global. Ramp List pre-stages the first safe setpoint for every channel used in the list before enabling output once."
    );
    editor.appendChild(globalOutputNote);
  }
  editor.appendChild(renderLoopControl({
    prefix: "ramp-list",
    loopEnabled: state.rampListLoopEnabled,
    countDraft: state.rampListLoopCountDraft,
    onEnabled: (value) => { state.rampListLoopEnabled = value; },
    onDraft: (value) => { state.rampListLoopCountDraft = value; },
    translate: t,
    enabledTranslationKey: "form.field.loop_enabled",
    countTranslationKey: "form.field.loop_count",
    onDisable: () => {
      if (state.rampListCompletionPulse?.timing === "loop") {
        state.rampListCompletionPulse = null;
        renderForm("ramp-list");
      }
    }
  }));
  const pulseFields = document.createElement("div");
  pulseFields.className = "ramp-segment-fields";
  [
    { name: "timing", label: "Pulse timing", type: "select", options: ["", "step", "segment", "loop"] },
    { name: "pins", label: "Rear pins", type: "select", options: REAR_PIN_OPTIONS },
    { name: "polarity", label: "Polarity", type: "select", options: ["positive", "negative"] }
  ].forEach((definition) => {
    const label = document.createElement("label");
    workflowText(label, `workflow.field.${definition.name}`, definition.label);
    const input = document.createElement(definition.type === "select" ? "select" : "input");
    if (definition.type === "select") {
      definition.options.forEach((value) => {
        const option = document.createElement("option");
        const fallback = definition.name === "pins" ? rearPinDisplayName(value) : pulseTimingDisplayName("ramp-list", value);
        if (definition.name === "timing" && value === "segment") {
          option.value = value;
          workflowText(option, "form.option.segment_complete", fallback);
        } else {
          localizedOption(option, value, fallback, definition.name === "pins");
        }
        if (definition.name === "timing" && value === "loop" && !(effectiveRampListLoopCount() >= 2)) {
          option.disabled = true;
        }
        input.appendChild(option);
      });
    } else {
      input.type = "text";
    }
    input.value = definition.name === "pins"
      ? pinsSelectValue(state.rampListCompletionPulse?.pins || [1])
      : String(state.rampListCompletionPulse?.[definition.name] || (definition.name === "polarity" ? "positive" : ""));
    input.id = `ramp-list-pulse-${definition.name}`;
    input.addEventListener("change", () => updateRampListPulse(definition.name, input.value));
    const prerequisiteKey = definition.name !== "timing" && !state.rampListCompletionPulse
      ? "workflow.guard.select_pulse_timing"
      : "";
    const prerequisiteReason = prerequisiteKey ? t(prerequisiteKey) : "";
    if (prerequisiteKey) input.dataset.pulsePrerequisiteI18n = prerequisiteKey;
    applyWorkflowPulseControlState(input, prerequisiteReason);
    label.appendChild(input);
    if (definition.name !== "timing") label.hidden = !state.rampListCompletionPulse;
    pulseFields.appendChild(label);
  });
  editor.appendChild(pulseFields);
  state.rampListSegments.forEach((segment, index) => editor.appendChild(rampSegmentCard(segment, index)));
  form.appendChild(editor);
  updateWorkflowDocumentValidity("ramp-list");
}

function rampSegmentCard(segment, index) {
  const card = document.createElement("div");
  card.className = "ramp-segment-card";
  card.dataset.rampSegmentIndex = String(index);
  const head = document.createElement("div");
  head.className = "ramp-segment-head";
  const title = document.createElement("strong");
  workflowText(title, "workflow.ramp_segment", `Ramp Segment ${index + 1}`, { index: index + 1 });
  const actions = document.createElement("div");
  actions.className = "ramp-segment-actions";
  [
    ["common.up", "Up", () => moveRampSegment(index, -1), index === 0],
    ["common.down", "Down", () => moveRampSegment(index, 1), index === state.rampListSegments.length - 1],
    ["common.remove", "Remove", () => removeRampSegment(index), state.rampListSegments.length === 1]
  ].forEach(([key, text, handler, disabled]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    workflowText(button, key, text);
    button.disabled = disabled;
    button.addEventListener("click", handler);
    actions.appendChild(button);
  });
  head.append(title, actions);
  card.appendChild(head);
  const fields = document.createElement("div");
  fields.className = "ramp-segment-fields";
  rampSegmentDefinitions().forEach((definition) => {
    const label = document.createElement("label");
    workflowText(label, `workflow.field.${definition.name}`, definition.label);
    const input = document.createElement(definition.name === "channels" ? "select" : "input");
    if (definition.name === "channels") {
      const supported = supportedChannelsForCurrentModel();
      const options = rampChannelOptions(supported);
      const currentValue = segment.channels.join(",");
      if (!options.includes(currentValue)) {
        const option = document.createElement("option");
        option.value = currentValue;
        option.textContent = segment.channels.map((channel) => `CH${channel}`).join(" + ");
        option.disabled = true;
        input.appendChild(option);
      }
      options.forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = rampChannelOptionLabel(value, supported);
        input.appendChild(option);
      });
    } else {
      input.type = "number";
    }
    input.value = definition.name === "channels"
      ? segment.channels.join(",")
      : String(segment[definition.name]);
    input.dataset.rampField = definition.name;
    if (definition.name !== "channels") applyParameterConstraint(input, definition.name);
    input.addEventListener("input", () => {
      state.rampListSegments[index][definition.name] = definition.name === "channels"
        ? String(input.value).split(",").map(Number)
        : Number(input.value);
      updateSelectedCommandState();
    });
    label.appendChild(input);
    fields.appendChild(label);
  });
  card.appendChild(fields);
  return card;
}

function rampSegmentDefinitions() {
  return webuiRampListDocument.rampSegmentDefinitions();
}

function addRampSegment() {
  if (state.rampListSegments.length >= 10) return;
  const previous = state.rampListSegments[state.rampListSegments.length - 1];
  state.rampListSegments.push({
    channels: [...previous.channels],
    current: previous.current,
    start_voltage: previous.stop_voltage,
    stop_voltage: previous.stop_voltage,
    step_voltage: previous.step_voltage,
    delay_ms: previous.delay_ms,
    hold_ms: previous.hold_ms
  });
  renderForm("ramp-list");
  updateSelectedCommandState();
}

function removeRampSegment(index) {
  if (state.rampListSegments.length <= 1) return;
  state.rampListSegments.splice(index, 1);
  renderForm("ramp-list");
  updateSelectedCommandState();
}

function moveRampSegment(index, offset) {
  const target = index + offset;
  if (target < 0 || target >= state.rampListSegments.length) return;
  [state.rampListSegments[index], state.rampListSegments[target]] = [state.rampListSegments[target], state.rampListSegments[index]];
  renderForm("ramp-list");
  updateSelectedCommandState();
}

function effectiveEnabledLoopCount(enabled, draft) {
  return webuiRampListDocument.effectiveEnabledLoopCount(enabled, draft);
}

function effectiveRampListLoopCount() {
  return effectiveEnabledLoopCount(state.rampListLoopEnabled, state.rampListLoopCountDraft);
}

function effectiveSequenceLoopCount() {
  return effectiveEnabledLoopCount(state.sequenceLoopEnabled, state.sequenceLoopCountDraft);
}

function rampListDocument() {
  return webuiRampListDocument.rampListDocument(state);
}

function validateRampListDocument(document) {
  return webuiRampListDocument.validateRampListDocument(document);
}

async function loadRampList() {
  try {
    const { text } = await openJsonFile({
      description: "Ramp List JSON",
      extensions: rampListJsonExtensions
    });
    const normalized = validateRampListDocument(
      JSON.parse(text),
      supportedChannelsForCurrentModel()
    );
    state.rampListSegments = normalized.segments;
    state.rampListCompletionPulse = normalized.completionPulse;
    state.rampListEnableOutput = normalized.enableOutput;
    state.rampListLoopEnabled = normalized.loopCount >= 2;
    state.rampListLoopCountDraft = String(normalized.loopCount >= 2 ? normalized.loopCount : 2);
    renderForm("ramp-list");
    updateSelectedCommandState();
  } catch (error) {
    if (isAbortError(error)) return;
    renderClientResult("ramp-list", "failed", error.message || String(error), { error: "Ramp List load failed", detail: error.message || String(error) });
  }
}

async function saveRampList() {
  try {
    const document = rampListDocument();
    validateRampListDocument(document);
    const documentText = `${JSON.stringify(document, null, 2)}\n`;
    await saveJsonFile(documentText, {
      description: "Ramp List JSON",
      extensions: rampListJsonExtensions,
      suggestedName: "ramp-list.ramp-list.json"
    });
  } catch (error) {
    if (isAbortError(error)) return;
    renderClientResult("ramp-list", "failed", error.message || String(error), { error: "Ramp List save failed", detail: error.message || String(error) });
  }
}

function triggerListWorkspaceDocument() {
  return webuiTriggerListDocument.triggerListWorkspaceDocument(state);
}

function validateTriggerListWorkspace(document) {
  return webuiTriggerListDocument.validateTriggerListWorkspace(document);
}

async function loadTriggerListWorkspace() {
  try {
    const { text } = await openJsonFile({ description: "Trigger List Workspace JSON", extensions: triggerListWorkspaceJsonExtensions });
    const normalized = validateTriggerListWorkspace(JSON.parse(text));
    state.triggerListActiveChannel = normalized.activeChannel;
    state.triggerListControls = normalized.controls;
    state.triggerListChannels = normalized.channels;
    renderForm("trigger-list");
    updateSelectedCommandState();
  } catch (error) {
    if (!isAbortError(error)) renderClientResult("trigger-list", "failed", error.message || String(error), { error: "Trigger List load failed", detail: error.message || String(error) });
  }
}

async function saveTriggerListWorkspace() {
  try {
    await saveJsonFile(`${JSON.stringify(triggerListWorkspaceDocument(), null, 2)}\n`, { description: "Trigger List Workspace JSON", extensions: triggerListWorkspaceJsonExtensions, suggestedName: "trigger-list.trigger-list-workspace.json" });
  } catch (error) {
    if (!isAbortError(error)) renderClientResult("trigger-list", "failed", error.message || String(error), { error: "Trigger List save failed", detail: error.message || String(error) });
  }
}

  return {
    defaultTriggerListStep,
    defaultTriggerListChannels,
    defaultTriggerListControls,
    activeTriggerListDraft,
    renderTriggerListForm,
    triggerListControlDefinitions,
    triggerListControlField,
    triggerListStepRow,
    updateTriggerListControl,
    addTriggerListStep,
    removeTriggerListStep,
    moveTriggerListStep,
    renderRampListForm,
    rampSegmentCard,
    rampSegmentDefinitions,
    addRampSegment,
    removeRampSegment,
    moveRampSegment,
    effectiveEnabledLoopCount,
    effectiveRampListLoopCount,
    effectiveSequenceLoopCount,
    rampListDocument,
    validateRampListDocument,
    loadRampList,
    saveRampList,
    triggerListWorkspaceDocument,
    validateTriggerListWorkspace,
    loadTriggerListWorkspace,
    saveTriggerListWorkspace
  };
}


export function createArtifactAndSequenceWorkflows({
  state,
  params: PARAMS,
  rearPinOptions: REAR_PIN_OPTIONS,
  webuiCommandForm,
  webuiSnapshotDocument,
  webuiRestoreDocument,
  webuiSequenceDocument,
  openJsonFile,
  saveJsonFile,
  isAbortError,
  renderClientResult,
  renderForm,
  updateSelectedCommandState,
  effectiveSequenceLoopCount,
  jobCommand,
  snapshotJsonExtensions: SNAPSHOT_JSON_EXTENSIONS,
  sequenceJsonExtensions: SEQUENCE_JSON_EXTENSIONS,
  optionDisplayName,
  rearPinDisplayName,
  parseRearPins,
  renderLoopControl,
  applyWorkflowPulseControlState,
  applyParameterConstraint,
  updateWorkflowDocumentValidity,
  runtimePayload,
  restoreSnapshotParameters,
  submitJob,
  addHistory,
  subscribeToJob
}) {
function renderSnapshotForm(form) {
  const editor = document.createElement("div");
  editor.className = "artifact-editor";

  const toolbar = document.createElement("div");
  toolbar.className = "artifact-toolbar";

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "secondary";
  saveBtn.id = "btn-save-snapshot";
  workflowText(saveBtn, "workflow.action.save_snapshot", "Save Snapshot");
  saveBtn.disabled = !state.latestSnapshotDocument;
  saveBtn.addEventListener("click", saveSnapshot);
  toolbar.appendChild(saveBtn);

  const statusNote = document.createElement("span");
  statusNote.id = "snapshot-status-note";
  statusNote.className = "artifact-file-status";

  const snapshotJob = state.jobs.find(j => j.command === "snapshot" && (j.status === "accepted" || j.status === "started" || j.status === "progress"));
  const inProgress = Boolean(snapshotJob);

  if (state.latestSnapshotDocument) {
    const meta = state.latestSnapshotMetadata;
    const timeStr = meta && meta.savedAt ? new Date(meta.savedAt).toLocaleTimeString() : "";
    if (inProgress) {
      workflowText(statusNote, "snapshot.status.previous_available", "Previous successful snapshot available while a new snapshot is running. ({model}, {time})", { model: meta?.model || t("status.unknown"), time: timeStr });
    } else {
      workflowText(statusNote, "snapshot.status.latest_available", "Latest successful snapshot available ({model}, {time})", { model: meta?.model || t("status.unknown"), time: timeStr });
    }
  } else {
    workflowText(statusNote, inProgress ? "snapshot.status.in_progress" : "snapshot.status.none", inProgress ? "Snapshot in progress..." : "No successful snapshot captured in this session.");
  }
  toolbar.appendChild(statusNote);
  editor.appendChild(toolbar);

  (PARAMS["snapshot"] || []).forEach((param) => {
    const label = document.createElement("label");
    workflowText(label, `form.field.${param.name}`, param.label);
    const input = document.createElement("input");
    input.type = param.type;
    input.id = `param-${param.name}`;
    if (param.value !== undefined) input.value = param.value;
    input.addEventListener("change", updateSelectedCommandState);
    label.appendChild(input);
    webuiCommandForm.appendFieldDescription(
      label,
      param,
      `form.description.snapshot.${param.name}`
    );
    editor.appendChild(label);
  });

  form.appendChild(editor);
}

function refreshSnapshotFormIfVisible(jobId = null) {
  if (state.selected !== "snapshot") return;

  if (jobId !== null && jobCommand(jobId) !== "snapshot") {
    return;
  }

  renderForm("snapshot");
  updateSelectedCommandState();
}

async function saveSnapshot() {
  if (!state.latestSnapshotDocument) {
    renderClientResult("snapshot", "failed", "No snapshot available to save.", { error: "Snapshot save failed", detail: "No snapshot available to save." });
    return;
  }
  try {
    validateSnapshotDocument(state.latestSnapshotDocument);
    const documentText = `${JSON.stringify(state.latestSnapshotDocument, null, 2)}\n`;
    const suggestedName = getSnapshotSuggestedName();
    await saveJsonFile(documentText, {
      description: "Powers Tool Snapshot JSON",
      extensions: SNAPSHOT_JSON_EXTENSIONS,
      suggestedName
    });
  } catch (error) {
    if (isAbortError(error)) return;
    renderClientResult(
      "snapshot",
      "failed",
      error.message || String(error),
      {
        error: "Snapshot save failed",
        detail: error.message || String(error),
        command: "snapshot"
      }
    );
  }
}

function getSnapshotSuggestedName() {
  return webuiSnapshotDocument.snapshotSuggestedName(
    state.latestSnapshotDocument,
    state.latestSnapshotMetadata,
    new Date()
  );
}

function validateSnapshotDocument(doc) {
  return webuiSnapshotDocument.validateSnapshotDocument(doc);
}

/* ==========================================
   Restore from Snapshot Feature
   ========================================== */

function renderRestoreForm(form) {
  const editor = document.createElement("div");
  editor.className = "artifact-editor";

  const toolbar = document.createElement("div");
  toolbar.className = "artifact-toolbar";

  const loadBtn = document.createElement("button");
  loadBtn.type = "button";
  loadBtn.className = "secondary";
  loadBtn.id = "btn-load-snapshot";
  workflowText(loadBtn, "workflow.action.load_snapshot", "Load Snapshot");
  loadBtn.addEventListener("click", loadRestoreSnapshot);
  toolbar.appendChild(loadBtn);

  const fileStatus = document.createElement("span");
  fileStatus.id = "restore-file-status";
  fileStatus.className = "artifact-file-status";
  workflowText(
    fileStatus,
    state.loadedSnapshotFilename ? "restore.status.loaded_file" : "restore.status.no_snapshot",
    state.loadedSnapshotFilename ? "Loaded file: {filename}" : "No snapshot loaded",
    state.loadedSnapshotFilename ? { filename: state.loadedSnapshotFilename } : undefined
  );
  toolbar.appendChild(fileStatus);
  editor.appendChild(toolbar);

  // Channel Select
  const channelLabel = document.createElement("label");
  workflowText(channelLabel, "workflow.field.channel", "Channel");
  const channelSelect = document.createElement("select");
  channelSelect.id = "param-channel";
  ["all", "1", "2", "3"].forEach((ch) => {
    const opt = document.createElement("option");
    opt.value = ch;
    opt.textContent = optionDisplayName(ch);
    channelSelect.appendChild(opt);
  });
  channelSelect.value = state.restoreChannel;
  channelSelect.addEventListener("change", (e) => {
    state.restoreChannel = e.target.value;
    clearRestorePlanPreview();
    renderForm("restore-from-snapshot");
    updateSelectedCommandState();
  });
  channelLabel.appendChild(channelSelect);
  editor.appendChild(channelLabel);

  // Restore previous output state Checkbox
  const restoreStateCheck = document.createElement("input");
  restoreStateCheck.type = "checkbox";
  restoreStateCheck.id = "param-restore_output_state";
  restoreStateCheck.checked = state.restoreOutputState;
  restoreStateCheck.addEventListener("change", (e) => {
    state.restoreOutputState = e.target.checked;
    clearRestorePlanPreview();
    renderForm("restore-from-snapshot");
    updateSelectedCommandState();
  });
  const restoreStateLabel = webuiCommandForm.createCheckboxField(restoreStateCheck, "Restore previous output ON/OFF state");
  restoreStateLabel.dataset.workflowI18n = "restore.field.restore_output_state";
  restoreStateLabel.dataset.workflowI18nFallback = "Restore previous output ON/OFF state";
  restoreStateLabel.querySelector(".checkbox-label-text").textContent = t("restore.field.restore_output_state");
  editor.appendChild(restoreStateLabel);

  const warningNote = document.createElement("div");
  warningNote.style.color = "var(--muted)";
  warningNote.style.fontSize = "0.9em";
  warningNote.style.marginBottom = "8px";
  workflowText(warningNote, "restore.warning.output_state", "When enabled, channels that were ON in the snapshot may be turned ON after restoring settings.");
  editor.appendChild(warningNote);

  const previewPlanBtn = document.createElement("button");
  previewPlanBtn.type = "button";
  previewPlanBtn.className = "secondary";
  previewPlanBtn.id = "btn-preview-restore-plan";
  workflowText(previewPlanBtn, "restore.action.preview_plan", "Preview restore plan");
  previewPlanBtn.disabled = !isLoadedRestoreSnapshotValid() || state.restorePlanPreviewStatus === "running";
  previewPlanBtn.addEventListener("click", previewRestorePlan);
  editor.appendChild(previewPlanBtn);

  const planExplanation = document.createElement("p");
  planExplanation.className = "restore-plan-explanation";
  workflowText(planExplanation, "restore.help.preview_plan", "Shows the exact restore steps without opening VISA, locking hardware, or changing the instrument.");
  editor.appendChild(planExplanation);

  const planPreview = document.createElement("div");
  planPreview.id = "restore-plan-preview";
  planPreview.className = `restore-plan-preview ${state.restorePlanPreviewStatus}`;
  renderRestorePlanPreview(planPreview);
  editor.appendChild(planPreview);

  form.appendChild(editor);
}

async function loadRestoreSnapshot() {
  try {
    const { text, filename } = await openJsonFile({
      description: "Powers Tool Snapshot JSON",
      extensions: SNAPSHOT_JSON_EXTENSIONS
    });
    const rawDoc = JSON.parse(text);
    validateRestoreSnapshot(rawDoc);

    state.loadedSnapshotDocument = rawDoc;
    state.loadedSnapshotFilename = filename;
    clearRestorePlanPreview();

    renderForm("restore-from-snapshot");
    updateSelectedCommandState();
  } catch (error) {
    if (isAbortError(error)) return;
    renderClientResult(
      "restore-from-snapshot",
      "failed",
      error.message || String(error),
      {
        error: "Snapshot load failed",
        detail: error.message || String(error),
        command: "restore-from-snapshot"
      }
    );
  }
}

async function previewRestorePlan() {
  try {
    validateRestoreSnapshot(state.loadedSnapshotDocument);
    state.restorePlanPreviewStatus = "running";
    state.restorePlanPreview = null;
    renderForm("restore-from-snapshot");
    updateSelectedCommandState();
    const payload = {
      command: "restore-from-snapshot",
      runtime: {
        ...runtimePayload(),
        dry_run: true,
        confirm: true
      },
      parameters: restoreSnapshotParameters(state.loadedSnapshotDocument)
    };
    const response = await submitJob(payload);
    addHistory(response.job_id, "restore-from-snapshot", "accepted", "Restore plan preview");
    subscribeToJob(response.job_id, "/api/events");
  } catch (error) {
    state.restorePlanPreviewStatus = "failed";
    state.restorePlanPreview = { error: error.message || String(error) };
    if (state.selected === "restore-from-snapshot") renderForm("restore-from-snapshot");
    renderClientResult(
      "Restore plan preview",
      "failed",
      error.message || String(error),
      {
        error: "Restore plan preview failed",
        detail: error.message || String(error),
        command: "restore-from-snapshot"
      }
    );
  }
}

function renderRestorePlanPreview(container) {
  if (state.restorePlanPreviewStatus === "running") {
    workflowText(container, "restore.status.generating_plan", "Generating restore plan...");
    return;
  }
  if (state.restorePlanPreviewStatus === "failed") {
    workflowText(container, "restore.status.plan_failed", "Could not generate restore plan: {detail}", { detail: state.restorePlanPreview?.error || t("status.unknown") });
    return;
  }
  const plan = state.restorePlanPreview?.plan;
  if (!plan || !Array.isArray(plan.steps)) {
    workflowText(container, "restore.status.no_plan", "No restore plan generated yet.");
    return;
  }
  const heading = document.createElement("strong");
  workflowText(heading, "restore.status.plan_steps", "Restore plan: {count} steps (preview only)", { count: plan.steps.length });
  const safety = document.createElement("p");
  workflowText(safety, "restore.help.preview_safe", "No VISA connection was opened and no instrument settings were changed.");
  const list = document.createElement("ol");
  plan.steps.forEach((step) => {
    const item = document.createElement("li");
    const action = String(step.action || "action").replace(/_/g, " ");
    const actionLabel = document.createElement("span");
    actionLabel.textContent = action;
    const command = document.createElement("code");
    command.textContent = step.command || "";
    item.append(actionLabel, command);
    list.appendChild(item);
  });
  container.append(heading, safety, list);
}

function clearRestorePlanPreview() {
  state.restorePlanPreviewStatus = "idle";
  state.restorePlanPreview = null;
}

function isLoadedRestoreSnapshotValid() {
  try {
    validateRestoreSnapshot(state.loadedSnapshotDocument);
    return true;
  } catch (error) {
    return false;
  }
}

function validateRestoreSnapshot(doc) {
  return webuiRestoreDocument.validateRestoreSnapshot(doc);
}

/* ==========================================
   Sequence Feature
   ========================================== */

function renderSequenceForm(form) {
  const editor = document.createElement("div");
  editor.className = "sequence-editor";
  const toolbar = document.createElement("div");
  toolbar.className = "sequence-toolbar";
  [
    ["workflow.action.load_sequence", "Load Sequence", loadSequenceFile],
    ["workflow.action.save_sequence", "Save Sequence", saveSequenceFile],
    ["workflow.action.add_step", "Add Step", addSequenceStep]
  ].forEach(([key, text, handler]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    workflowText(button, key, text);
    if (text === "Save Sequence") button.id = "save-sequence";
    button.disabled = text === "Add Step" && state.sequenceSteps.length >= sequenceMaxSteps();
    button.addEventListener("click", handler);
    toolbar.appendChild(button);
  });
  const count = document.createElement("span");
  count.className = "sequence-step-count";
  count.textContent = `${state.sequenceSteps.length} / ${sequenceMaxSteps()}`;
  toolbar.appendChild(count);
  if (state.sequenceFilename) {
    const fileStatus = document.createElement("span");
    fileStatus.className = "artifact-file-status";
    fileStatus.textContent = state.sequenceFilename;
    toolbar.appendChild(fileStatus);
  }
  editor.appendChild(toolbar);
  editor.appendChild(renderLoopControl({
    prefix: "sequence",
    loopEnabled: state.sequenceLoopEnabled,
    countDraft: state.sequenceLoopCountDraft,
    onEnabled: (value) => { state.sequenceLoopEnabled = value; },
    onDraft: (value) => { state.sequenceLoopCountDraft = value; },
    translate: t,
    enabledTranslationKey: "form.field.loop_enabled",
    countTranslationKey: "form.field.loop_count"
  }));
  const documentError = document.createElement("div");
  documentError.id = "sequence-document-error";
  documentError.className = "sequence-step-error";
  documentError.hidden = true;
  editor.appendChild(documentError);
  state.sequenceSteps.forEach((step, index) => editor.appendChild(sequenceStepCard(step, index)));
  form.appendChild(editor);
  updateWorkflowDocumentValidity("sequence");
}

const SEQUENCE_ACTIONS = [
  "measure", "readback", "output-state", "log", "wait", "safe-off",
  "set", "output-on", "output-off", "cycle-output", "apply", "trigger-pulse"
];

function sequenceMaxSteps() {
  return Number(state.commands.sequence?.max_steps) || 250;
}

function sequenceActionDefinitions(action) {
  const channel = (all = false) => ({
    name: "channel", label: "Channel", type: "select",
    options: all ? ["all", "1", "2", "3"] : ["1", "2", "3"],
    value: "1"
  });
  return {
    measure: [channel()],
    readback: [channel()],
    "output-state": [channel(true)],
    log: [{ name: "message", label: "Message", type: "text", value: "" }],
    wait: [{ name: "seconds", label: "Seconds", type: "number", value: 0 }],
    "safe-off": [channel(true)],
    set: [channel(), { name: "voltage", label: "Voltage(V)", type: "number", value: 0 }, { name: "current", label: "Current(A)", type: "number", value: 0 }],
    "output-on": [channel(true)],
    "output-off": [channel(true)],
    "cycle-output": [channel(true), { name: "duration_ms", label: "Duration(ms)", type: "number", value: 500 }],
    apply: [channel(true), { name: "voltage", label: "Voltage(V)", type: "number", value: 0 }, { name: "current", label: "Current(A)", type: "number", value: 0 }, { name: "no_output", label: "Do not enable output", type: "checkbox", value: false }],
    "trigger-pulse": [channel(), { name: "pins", label: "Rear pins", type: "select", options: REAR_PIN_OPTIONS, value: [1] }, { name: "polarity", label: "Polarity", type: "select", options: ["positive", "negative"], value: "positive" }, { name: "leave_trigger_configured", label: "Leave configured", type: "checkbox", value: false, description: "Controls whether Trigger and rear-pin settings are restored after the pulse completes. It does not keep a trigger armed. Enabling it may affect later Sequence steps or other BUS triggers." }]
  }[action] || [];
}

function defaultSequenceStep(action = "wait", previous = {}) {
  const step = { action };
  sequenceActionDefinitions(action).forEach((field) => {
    step[field.name] = field.name === "channel" && previous.channel !== undefined
      && field.options.includes(String(previous.channel))
      ? previous.channel
      : field.value;
  });
  return step;
}

function sequenceStepCard(step, index) {
  const card = document.createElement("div");
  card.className = "sequence-step-card";
  card.dataset.sequenceStepIndex = String(index);
  const head = document.createElement("div");
  head.className = "sequence-step-head";
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "secondary";
  workflowText(toggle, state.sequenceExpanded.has(index) ? "common.collapse" : "common.expand", state.sequenceExpanded.has(index) ? "Collapse" : "Expand");
  toggle.addEventListener("click", () => {
    if (state.sequenceExpanded.has(index)) state.sequenceExpanded.delete(index);
    else state.sequenceExpanded.add(index);
    renderForm("sequence");
  });
  const title = document.createElement("strong");
  workflowText(title, "sequence.step_title", `Step ${index + 1}: ${step.action}`, { index: index + 1, action: step.action });
  const summary = document.createElement("span");
  summary.className = "sequence-step-summary";
  summary.textContent = sequenceStepSummary(step);
  const actions = document.createElement("div");
  actions.className = "sequence-step-actions";
  [
    ["common.up", "Up", () => moveSequenceStep(index, -1), index === 0],
    ["common.down", "Down", () => moveSequenceStep(index, 1), index === state.sequenceSteps.length - 1],
    ["common.remove", "Remove", () => removeSequenceStep(index), state.sequenceSteps.length === 1]
  ].forEach(([key, text, handler, disabled]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    workflowText(button, key, text);
    button.disabled = disabled;
    button.addEventListener("click", handler);
    actions.appendChild(button);
  });
  head.append(toggle, title, summary, actions);
  card.appendChild(head);
  if (state.sequenceExpanded.has(index)) {
    card.appendChild(sequenceStepFields(step, index, card, title, summary));
    renderSequenceStepError(card, step, index);
  }
  return card;
}

function sequenceStepFields(step, index, card, title, summary) {
  const fields = document.createElement("div");
  fields.className = "sequence-step-fields";
  const actionLabel = document.createElement("label");
  workflowText(actionLabel, "workflow.field.action", "Action");
  const actionSelect = document.createElement("select");
  SEQUENCE_ACTIONS.forEach((action) => {
    const option = document.createElement("option");
    option.value = action;
    workflowText(option, `sequence.action.${action.replaceAll("-", "_")}`, optionDisplayName(action));
    actionSelect.appendChild(option);
  });
  actionSelect.value = step.action;
  actionSelect.addEventListener("change", () => {
    state.sequenceSteps[index] = defaultSequenceStep(actionSelect.value, step);
    const replacement = sequenceStepCard(state.sequenceSteps[index], index);
    card.replaceWith(replacement);
    updateSelectedCommandState();
  });
  actionLabel.appendChild(actionSelect);
  fields.appendChild(actionLabel);
  sequenceActionDefinitions(step.action).forEach((definition) => {
    const input = document.createElement(definition.type === "select" ? "select" : "input");
    if (definition.type === "select") {
      definition.options.forEach((value) => {
        const option = document.createElement("option");
        localizedOption(option, value, definition.name === "pins" ? rearPinDisplayName(value) : optionDisplayName(value), definition.name === "pins");
        input.appendChild(option);
      });
    } else {
      input.type = definition.type;
    }
    if (definition.type === "checkbox") input.checked = Boolean(step[definition.name]);
    else input.value = definition.name === "pins"
      ? pinsSelectValue(step[definition.name] ?? definition.value)
      : String(step[definition.name] ?? definition.value);
    input.dataset.sequenceField = definition.name;
    applyParameterConstraint(input, definition.name);
    if (step.action === "trigger-pulse") applyWorkflowPulseControlState(input);
    input.addEventListener("input", () => {
      step[definition.name] = sequenceFieldValue(definition, input);
      summary.textContent = sequenceStepSummary(step);
      workflowText(title, "sequence.step_title", `Step ${index + 1}: ${step.action}`, { index: index + 1, action: step.action });
      renderSequenceStepError(card, step, index);
      updateSelectedCommandState();
    });
    input.addEventListener("change", () => {
      step[definition.name] = sequenceFieldValue(definition, input);
      summary.textContent = sequenceStepSummary(step);
      renderSequenceStepError(card, step, index);
      updateSelectedCommandState();
    });
    const label = definition.type === "checkbox"
      ? webuiCommandForm.createCheckboxField(input, definition.label)
      : document.createElement("label");
    label.dataset.workflowI18n = `workflow.field.${definition.name}`;
    label.dataset.workflowI18nFallback = definition.label;
    const checkboxText = label.querySelector?.(".checkbox-label-text");
    if (checkboxText) checkboxText.textContent = t(`workflow.field.${definition.name}`, undefined, definition.label);
    if (definition.type !== "checkbox") {
      workflowText(label, `workflow.field.${definition.name}`, definition.label);
      label.appendChild(input);
    }
    webuiCommandForm.appendFieldDescription(
      label,
      definition,
      `form.description.sequence.${step.action.replaceAll("-", "_")}.${definition.name}`
    );
    fields.appendChild(label);
  });
  return fields;
}

function sequenceFieldValue(definition, input) {
  if (definition.type === "checkbox") return input.checked;
  if (definition.type === "number") return Number(input.value);
  if (definition.name === "channel" && input.value !== "all") return Number(input.value);
  if (definition.name === "pins") return parseRearPins(input.value);
  return input.value;
}

function sequenceStepSummary(step) {
  return Object.entries(step)
    .filter(([key]) => key !== "action")
    .map(([key, value]) => `${key}=${value}`)
    .join(", ");
}

function renderSequenceStepError(card, step, index) {
  const previous = card.querySelector?.(".sequence-step-error");
  if (previous) previous.remove();
  try {
    validateCanonicalSequenceStep(step, index);
    card.classList?.remove("invalid");
  } catch (error) {
    card.classList?.add("invalid");
    const message = document.createElement("div");
    message.className = "sequence-step-error";
    message.textContent = error.message || String(error);
    card.appendChild(message);
  }
}

function addSequenceStep() {
  if (state.sequenceSteps.length >= sequenceMaxSteps()) return;
  state.sequenceSteps.push(defaultSequenceStep());
  renderForm("sequence");
  updateSelectedCommandState();
}

function removeSequenceStep(index) {
  if (state.sequenceSteps.length <= 1) return;
  state.sequenceSteps.splice(index, 1);
  state.sequenceExpanded = new Set();
  renderForm("sequence");
  updateSelectedCommandState();
}

function moveSequenceStep(index, offset) {
  const target = index + offset;
  if (target < 0 || target >= state.sequenceSteps.length) return;
  [state.sequenceSteps[index], state.sequenceSteps[target]] = [state.sequenceSteps[target], state.sequenceSteps[index]];
  state.sequenceExpanded = new Set();
  renderForm("sequence");
  updateSelectedCommandState();
}

async function loadSequenceFile() {
  try {
    const { text, filename } = await openJsonFile({
      description: "Powers Tool Sequence JSON",
      extensions: SEQUENCE_JSON_EXTENSIONS
    });
    const rawDoc = JSON.parse(text);
    const normalized = normalizeSequenceDocument(rawDoc);
    state.sequenceSteps = normalized.steps;
    state.sequenceLoopEnabled = normalized.loopCount >= 2;
    state.sequenceLoopCountDraft = String(normalized.loopCount >= 2 ? normalized.loopCount : 2);
    state.sequenceExpanded = new Set();
    state.sequenceFilename = filename;
    renderForm("sequence");
    updateSelectedCommandState();
  } catch (error) {
    if (isAbortError(error)) return;
    renderClientResult(
      "sequence",
      "failed",
      error.message || String(error),
      {
        error: "Sequence load failed",
        detail: error.message || String(error),
        command: "sequence"
      }
    );
  }
}

async function saveSequenceFile() {
  try {
    const documentText = `${JSON.stringify(sequenceDocumentFromEditor(), null, 2)}\n`;
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const timestamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
    const suggestedName = `powers-tool-sequence-${timestamp}.sequence.json`;

    await saveJsonFile(documentText, {
      description: "Powers Tool Sequence JSON",
      extensions: SEQUENCE_JSON_EXTENSIONS,
      suggestedName
    });
  } catch (error) {
    if (isAbortError(error)) return;
    renderClientResult(
      "sequence",
      "failed",
      error.message || String(error),
      {
        error: "Sequence save failed",
        detail: error.message || String(error),
        command: "sequence"
      }
    );
  }
}

function normalizeSequenceDocument(doc) {
  return webuiSequenceDocument.normalizeSequenceDocument(doc, {
    maxSteps: sequenceMaxSteps(),
    normalizeStep: normalizeSequenceStep
  });
}

function normalizeSequenceStep(step, index) {
  return webuiSequenceDocument.normalizeSequenceStep(step, index, {
    sequenceActions: SEQUENCE_ACTIONS,
    actionDefinitions: sequenceActionDefinitions,
    defaultStep: defaultSequenceStep,
    parseRearPins,
    validateCanonicalStep: validateCanonicalSequenceStep
  });
}

function validateCanonicalSequenceStep(step, index) {
  const fields = sequenceActionDefinitions(step.action);
  const allowed = new Set(["action", ...fields.map((field) => field.name)]);
  if (Object.keys(step).some((field) => !allowed.has(field))) throw new Error(`Sequence step ${index + 1} contains unsupported fields.`);
  fields.forEach((field) => {
    const value = step[field.name];
    if (field.type === "number" && (typeof value !== "number" || !Number.isFinite(value))) throw new Error(`Sequence step ${index + 1} requires a finite ${field.name}.`);
    if (field.type === "select" && !field.options.includes(String(value))) throw new Error(`Sequence step ${index + 1} has an invalid ${field.name}.`);
    if (field.type === "checkbox" && typeof value !== "boolean") throw new Error(`Sequence step ${index + 1} requires a boolean ${field.name}.`);
    if (field.type === "text" && typeof value !== "string") throw new Error(`Sequence step ${index + 1} requires a string ${field.name}.`);
  });
  if (step.action === "wait" && step.seconds < 0) throw new Error(`Sequence step ${index + 1} wait seconds must be non-negative.`);
  if (step.action === "cycle-output" && step.duration_ms < 0) throw new Error(`Sequence step ${index + 1} duration_ms must be non-negative.`);
  if (step.action === "trigger-pulse" && (!Array.isArray(step.pins) || !step.pins.length || step.pins.some((pin) => ![1, 2, 3].includes(pin)))) {
    throw new Error(`Sequence step ${index + 1} rear pins must contain 1, 2, or 3.`);
  }
}

function sequenceDocumentFromEditor() {
  return webuiSequenceDocument.sequenceDocumentFromEditor(state, {
    loopCount: effectiveSequenceLoopCount(),
    maxSteps: sequenceMaxSteps(),
    normalizeStep: normalizeSequenceStep
  });
}

  return {
    renderSnapshotForm,
    refreshSnapshotFormIfVisible,
    saveSnapshot,
    getSnapshotSuggestedName,
    validateSnapshotDocument,
    renderRestoreForm,
    loadRestoreSnapshot,
    previewRestorePlan,
    renderRestorePlanPreview,
    clearRestorePlanPreview,
    isLoadedRestoreSnapshotValid,
    validateRestoreSnapshot,
    renderSequenceForm,
    sequenceMaxSteps,
    sequenceActionDefinitions,
    defaultSequenceStep,
    sequenceStepCard,
    sequenceStepFields,
    sequenceFieldValue,
    sequenceStepSummary,
    renderSequenceStepError,
    addSequenceStep,
    removeSequenceStep,
    moveSequenceStep,
    loadSequenceFile,
    saveSequenceFile,
    normalizeSequenceDocument,
    normalizeSequenceStep,
    validateCanonicalSequenceStep,
    sequenceDocumentFromEditor
  };
}
