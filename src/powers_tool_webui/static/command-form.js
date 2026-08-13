import { t } from "./i18n.js";

const SET_PARTIAL_GUIDANCE = "Set accepts Voltage, Current, or both. Blank fields are left unchanged.";

export function createCheckboxField(input, text, classNames = []) {
  const label = document.createElement("label");
  label.classList.add("checkbox-field", ...classNames);
  const visibleText = document.createElement("span");
  visibleText.className = "checkbox-label-text";
  visibleText.textContent = text;
  label.append(input, visibleText);
  return label;
}

export function renderCommandGuidance(command, parameters, triggerControlGuardReason, triggerFireWaitGuardReason) {
  const guidance = document.getElementById("command-guidance");
  if (!guidance) return;
  const messages = {
    "trigger-step": t("command.guidance.trigger_step"),
    "trigger-list": t("command.guidance.trigger_list"),
    "trigger-fire": t("command.guidance.trigger_fire")
  };
  const guard = triggerControlGuardReason(command, parameters) || triggerFireWaitGuardReason(command, parameters);
  const text = [guard, messages[command]].filter(Boolean).join(" ");
  if (guidance.dataset) guidance.dataset.command = command;
  guidance.textContent = text;
  guidance.hidden = !text;
}

export function appendFieldDescription(label, param, translationKey = null) {
  if (!param.description) return;
  const description = document.createElement("small");
  description.className = "field-description";
  description.textContent = translationKey
    ? t(translationKey, undefined, param.description)
    : param.description;
  if (translationKey) {
    description.dataset.workflowI18n = translationKey;
    description.dataset.workflowI18nFallback = param.description;
  }
  label.appendChild(description);
}

export function configureCompactCheckboxHelp(label, input, { ariaLabel, helpId, description }) {
  label.setAttribute("for", input.id);
  label.title = description;
  input.title = description;
  input.setAttribute("aria-label", ariaLabel);
  input.setAttribute("aria-describedby", helpId);

  const help = document.createElement("span");
  help.id = helpId;
  help.className = "visually-hidden";
  help.textContent = description;
  label.appendChild(help);
}

export function appendSetGuidance(label) {
  const guidance = document.createElement("small");
  guidance.className = "field-description set-field-guidance";
  guidance.textContent = SET_PARTIAL_GUIDANCE;
  label.appendChild(guidance);
}

export function appendCommandNotes(form, command, params, commandMeta) {
  const notes = document.createElement("section");
  notes.className = "command-notes";
  const title = document.createElement("strong");
  title.textContent = "Command notes";
  notes.appendChild(title);

  const summary = document.createElement("p");
  summary.textContent = commandMeta(command).description || "";
  notes.appendChild(summary);

  const descriptions = params.filter((param) => param.description);
  if (descriptions.length) {
    const list = document.createElement("dl");
    descriptions.forEach((param) => {
      const term = document.createElement("dt");
      term.textContent = param.label;
      const detail = document.createElement("dd");
      detail.textContent = param.description;
      list.append(term, detail);
    });
    notes.appendChild(list);
  }
  form.appendChild(notes);
}

export function setOutputParams() {
  const params = [
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "voltage", type: "number", label: "Voltage(V)", value: 1 },
    { name: "current", type: "number", label: "Current(A)", value: 0.1 }
  ];
  return [params[0], { ...params[1], optional: true }, { ...params[2], optional: true }];
}

export function applyOutputParams() {
  return [
    { name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" },
    { name: "voltage", type: "number", label: "Voltage(V)", value: 1 },
    { name: "current", type: "number", label: "Current(A)", value: 0.1 }
  ];
}

export function smokeOutputParams() {
  return [
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "voltage", type: "number", label: "Voltage(V)", value: 1 },
    { name: "current", type: "number", label: "Current(A)", value: 0.1 },
    { name: "duration_ms", type: "number", label: "Duration(ms)", value: 100 }
  ];
}

export function triggerWaitParams() {
  return [
    { name: "poll_ms", type: "number", label: "Poll(ms)", value: 200, description: "Interval between completion-status polls when waiting." },
    { name: "wait_timeout_ms", type: "number", label: "Timeout(ms)", optional: true, description: "Optional maximum wait time; leave blank to use the command default." }
  ];
}

export function triggerStepParams() {
  return [
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1", description: "E36312A only. Configures and arms a STEP transient. It does not fire by default; omitted voltage or current values keep the current programmed setpoint." },
    { name: "voltage", type: "number", label: "Triggered voltage(V)", optional: true },
    { name: "current", type: "number", label: "Triggered current(A)", optional: true },
    { name: "source", type: "select", label: "Source", options: ["bus", "immediate"], value: "bus", description: "Selects BUS or Immediate as the trigger source." },
    { name: "fire", type: "checkbox", label: "Fire now", description: "After arming, sends global *TRG for BUS source. This may also fire other armed BUS triggers." },
    { name: "wait_complete", type: "checkbox", label: "Wait complete", description: "Waits for the instrument-wide operation-complete event before returning." },
    ...triggerWaitParams(),
    { name: "leave_trigger_configured", type: "checkbox", label: "Leave configured", description: "Keeps the configured trigger source and transient mode instead of restoring them after execution." }
  ];
}

export function triggerListParams(optionalRearPinOptions) {
  return [
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1", description: "E36312A only. Configures and arms a LIST waveform. It does not fire by default; one current or dwell value can be applied to every voltage step." },
    { name: "voltage_list", type: "text", label: "Voltage list(V)", value: "0,1", parser: "numberList", description: "Comma-separated voltage steps." },
    { name: "current_list", type: "text", label: "Current list(A)", value: "0.05", parser: "numberList", description: "Comma-separated current limits. A single value applies to every voltage step." },
    { name: "dwell_list", type: "text", label: "Dwell list(s)", value: "0.01", parser: "numberList", description: "Comma-separated dwell times. A single value applies to every voltage step." },
    { name: "count", type: "number", label: "Count", value: 1, description: "Number of times to repeat the complete LIST waveform." },
    { name: "source", type: "select", label: "Source", options: ["bus", "immediate"], value: "bus", description: "Selects BUS or Immediate as the trigger source." },
    { name: "fire", type: "checkbox", label: "Fire now", description: "After arming, sends global *TRG for BUS source. This may also fire other armed BUS triggers." },
    { name: "wait_complete", type: "checkbox", label: "Wait complete", description: "Waits for all LIST steps and repeat counts to complete before returning." },
    { name: "completion_pulse_pins", type: "select", label: "Pulse pins", options: optionalRearPinOptions, value: "", optional: true, parser: "intList", description: "Optionally emits a completion pulse on the selected rear pins after LIST execution finishes." },
    { name: "completion_pulse_polarity", type: "select", label: "Pulse polarity", options: ["positive", "negative"], value: "positive" },
    { name: "exclusive_pins", type: "checkbox", label: "Exclusive pins", description: "Resets unselected rear pins before configuring completion-pulse pins." },
    ...triggerWaitParams(),
    { name: "leave_trigger_configured", type: "checkbox", label: "Leave configured", description: "Keeps the configured trigger source and LIST mode instead of restoring them after execution." }
  ];
}


export function createCommandController({
  state,
  params: PARAMS,
  triggerCommands: TRIGGER_COMMANDS,
  fetchJson,
  commandCatalog,
  populateIdentitySelector,
  commandMeta,
  renderWorkspaceSummary,
  prefillClearProtectionChannel,
  updateSelectedCommandState,
  renderRampListForm,
  renderTriggerListForm,
  renderSnapshotForm,
  renderRestoreForm,
  renderSequenceForm,
  pulseTimingDisplayName,
  isNumericChannel,
  isChannelSupported,
  supportedChannelsForCurrentModel,
  channelUnsupportedReason,
  applyWorkflowPulseControlState,
  renderLoopControl,
  refreshLoopCompleteOption,
  selectedPlanningIdentity,
  valueOrNull,
  hasRealWriteAuthorization,
  rampListDocument,
  activeTriggerListDraft,
  sequenceDocumentFromEditor,
  parseMaybeJson,
  restoreDocument,
  electrical,
  electricalConstraintAttributes,
  selectedElectricalRatingModel
}) {
state.rampDraft ||= Object.fromEntries((PARAMS?.ramp || []).map((param) => [
  param.name,
  param.type === "checkbox" ? Boolean(param.value) : String(param.value ?? "")
]));

async function loadCommands() {
  const payload = await fetchJson("/api/commands");
  state.commands = payload.commands || {};
  state.commandSupportByModel = payload.command_support_by_model_id || {};
  state.liveSupportByModel = payload.live_support_by_model_id || {};
  state.channelCapabilitiesByModel = payload.channel_capabilities_by_model_id || {};
  state.parameterConstraints = payload.parameter_constraints || {};
  state.electricalRatingsByModel = payload.electrical_ratings_by_model_id || {};
  state.setpointRangesByModel = payload.setpoint_ranges_by_model_id || {};
  state.physicalModels = Array.isArray(payload.physical_models) ? payload.physical_models : [];
  state.planningProfiles = payload.planning_profiles || {};
  populateIdentitySelector();
  refreshBasicInputConstraints();
  renderCommands();
}

function renderExpectedModelOptions() {
  populateIdentitySelector();
}

function commandStatusText(effectiveMeta) {
  if (effectiveMeta.disabled_reason) return effectiveMeta.disabled_reason;
  if (effectiveMeta.disabled) return effectiveMeta.live_support_status || "";
  return effectiveMeta.live_support_status === t("support.scope.not_evaluated")
    ? effectiveMeta.live_support_status
    : "";
}

function renderCommands() {
  const filter = document.getElementById("command-filter").value.toLowerCase();
  const categories = document.getElementById("command-categories");
  const list = document.getElementById("command-list");
  categories.innerHTML = "";
  list.innerHTML = "";

  commandCatalog.COMMAND_CATEGORIES.forEach((category) => {
    const button = document.createElement("button");
    button.className = `category-button${state.activeCategory === category ? " active" : ""}`;
    button.type = "button";
    button.textContent = commandCatalog.commandCategoryLabel(category);
    button.addEventListener("click", () => {
      state.activeCategory = category;
      renderCommands();
    });
    categories.appendChild(button);
  });

  Object.entries(state.commands)
    .filter(([name, meta]) => (meta.category || "discovery") === state.activeCategory)
    .filter(([name]) => !filter || name.includes(filter) || commandDisplayName(name).toLowerCase().includes(filter))
    .sort((a, b) => {
      const displayOrder = commandSourceDisplayName(a[0]).localeCompare(commandSourceDisplayName(b[0]), "en");
      return displayOrder || a[0].localeCompare(b[0], "en");
    })
    .forEach(([name]) => {
      const effectiveMeta = commandMeta(name);
      const button = document.createElement("button");
      button.className = `command-button${state.selected === name ? " active" : ""}`;
      button.disabled = Boolean(effectiveMeta.disabled || state.workflowControl.phase !== "idle");
      button.title = commandCatalog.commandDescription(name, effectiveMeta.description || "");
      const title = document.createElement("span");
      title.textContent = commandDisplayName(name);
      const status = document.createElement("small");
      status.textContent = commandStatusText(effectiveMeta);
      button.append(title, status);
      button.addEventListener("click", () => selectCommand(name));
      list.appendChild(button);
    });
}

function selectCommand(name) {
  if (state.workflowControl.phase !== "idle") return;
  state.selected = name;
  document.getElementById("selected-command").textContent = commandDisplayName(name);
  renderForm(name);
  renderWorkspaceSummary();
  prefillClearProtectionChannel();
  updateSelectedCommandState();
  renderCommands();
}

function renderForm(command) {
  const form = document.getElementById("command-form");
  form.innerHTML = "";
  if (command === "ramp-list") {
    renderRampListForm(form);
    return;
  }
  if (command === "trigger-list") {
    renderTriggerListForm(form);
    return;
  }
  if (command === "snapshot") {
    renderSnapshotForm(form);
    return;
  }
  if (command === "restore-from-snapshot") {
    renderRestoreForm(form);
    return;
  }
  if (command === "sequence") {
    renderSequenceForm(form);
    return;
  }
  (PARAMS[command] || []).forEach((param) => {
    if (command === "ramp" && param.name === "loop_count") return;
    const options = command === "ramp" && param.name === "channel"
      ? rampChannelOptions(supportedChannelsForCurrentModel())
      : param.options;
    let input;
    if (param.type === "select") {
      input = document.createElement("select");
      options.forEach((option) => {
        const item = document.createElement("option");
        item.value = option;
        item.textContent = command === "ramp" && param.name === "channel"
          ? rampChannelOptionLabel(option, supportedChannelsForCurrentModel())
          : param.parser === "intList"
          ? rearPinDisplayName(option)
          : pulseTimingDisplayName(command, option);
        item.dataset.i18nOption = option;
        item.dataset.i18nParam = param.name;
        if (param.name === "channel" && isNumericChannel(option) && !isChannelSupported(option)) {
          item.disabled = true;
          item.title = channelUnsupportedReason(option);
        }
        input.appendChild(item);
      });
    } else if (param.type === "textarea") {
      input = document.createElement("textarea");
    } else {
      input = document.createElement("input");
      input.type = param.type;
    }
    input.id = `param-${param.name}`;
    input.dataset.i18nParam = param.name;
    if (command === "ramp" && Object.hasOwn(state.rampDraft, param.name)) {
      if (param.type === "checkbox") input.checked = Boolean(state.rampDraft[param.name]);
      else input.value = state.rampDraft[param.name];
      if (param.type === "select" && input.selectedIndex < 0) {
        input.value = options[0];
        state.rampDraft[param.name] = input.value;
      }
    } else if (param.value !== undefined) {
      input.value = param.value;
    }
    applyParameterConstraint(input, param.name);
    applyElectricalRatingConstraint(input, param.name);
    if (param.name.includes("completion_pulse")) applyWorkflowPulseControlState(input);
    input.addEventListener("change", () => {
      if (command === "ramp") {
        state.rampDraft[param.name] = param.type === "checkbox" ? input.checked : input.value;
      }
      enforcePulseFormRules(command, param.name, input);
      refreshElectricalRatingConstraints();
      updateSelectedCommandState();
    });
    input.addEventListener("input", () => {
      if (command === "ramp") {
        state.rampDraft[param.name] = param.type === "checkbox" ? input.checked : input.value;
      }
      enforcePulseFormRules(command, param.name, input);
      updateSelectedCommandState();
    });
    const label = param.type === "checkbox"
      ? createCheckboxField(input, param.label)
      : document.createElement("label");
    label.dataset.i18nParam = param.name;
    if (param.type !== "checkbox") {
      label.textContent = param.label;
      label.appendChild(input);
    }
    if (command === "ramp" && param.name === "loop_enabled") {
      form.appendChild(renderLoopControl({
        prefix: "ramp",
        enabledInput: input,
        current: 1,
        loopEnabled: Boolean(state.rampDraft.loop_enabled),
        countDraft: state.rampDraft.loop_count,
        countInputId: "param-loop_count",
        translate: t,
        enabledTranslationKey: "form.field.loop_enabled",
        countTranslationKey: "form.field.loop_count",
        onValue: () => {},
        onEnabled: (enabled) => {
          state.rampDraft.loop_enabled = enabled;
        },
        onDraft: (value) => {
          state.rampDraft.loop_count = value;
        },
        onDisable: () => {
          const timing = document.getElementById("param-completion_pulse_timing");
          if (timing?.value === "loop") {
            timing.value = "";
            state.rampDraft.completion_pulse_timing = "";
          }
          updatePulseChildVisibility("ramp");
        }
      }));
      return;
    }
    if (param.pulseToggle) label.classList.add("pulse-toggle-field");
    if (param.pulseChild) label.classList.add("pulse-child-field");
    if (command === "ramp" && param.name === "enable_output") {
      label.classList.add("ramp-enable-output-field");
    }
    if (param.conditionalLoop) {
      label.hidden = true;
      input.min = "2"; input.max = "10000"; input.step = "1";
    }
    if (param.compactHelp) configureCompactCheckboxHelp(label, input, param);
    if (!TRIGGER_COMMANDS.has(command) && !param.compactHelp) appendFieldDescription(label, param);
    if (command === "set" && param.name === "current") appendSetGuidance(label);
    form.appendChild(label);
  });
  if (TRIGGER_COMMANDS.has(command)) appendCommandNotes(form, command, PARAMS[command] || [], commandMeta);
  updatePulseChildVisibility(command);
  refreshLoopCompleteOption(command);
  refreshCommandFormPresentation();
}

function refreshCommandFormPresentation() {
  const command = state.selected;
  if (!command) return;
  refreshCommandGuidancePresentation();
  refreshParameterConstraintPresentation();
  if (["ramp-list", "trigger-list", "snapshot", "restore-from-snapshot", "sequence"].includes(command)) return;
  const form = document.getElementById("command-form");
  if (!form || typeof form.querySelectorAll !== "function") return;
  const params = new Map((PARAMS[command] || []).map((param) => [param.name, param]));
  form.querySelectorAll("label[data-i18n-param]").forEach((label) => {
    const param = params.get(label.dataset.i18nParam);
    if (!param) return;
    const text = t(fieldTranslationKey(command, param.name), undefined, param.label);
    const checkboxText = label.querySelector(".checkbox-label-text");
    if (checkboxText) checkboxText.textContent = text;
    else if (label.firstChild?.nodeType === 3) label.firstChild.textContent = text;
    const description = label.querySelector(".field-description:not(.set-field-guidance)");
    if (description) description.textContent = t(`form.description.${command.replaceAll("-", "_")}.${param.name}`, undefined, param.description);
    if (param.compactHelp) {
      const compact = t(`form.description.${command.replaceAll("-", "_")}.${param.name}`, undefined, param.description);
      label.title = compact;
      const input = label.querySelector(`#param-${param.name}`);
      if (input) {
        input.title = compact;
        input.setAttribute("aria-label", t(`form.aria.${command.replaceAll("-", "_")}.${param.name}`, undefined, param.ariaLabel));
      }
      const help = label.querySelector(".visually-hidden");
      if (help) help.textContent = compact;
    }
  });
  form.querySelectorAll("option[data-i18n-option]").forEach((option) => {
    if (command === "ramp" && option.dataset.i18nParam === "channel") {
      option.textContent = rampChannelOptionLabel(option.value, supportedChannelsForCurrentModel());
      return;
    }
    const optionKey = optionTranslationKey(option.dataset.i18nParam, option.dataset.i18nOption);
    if (optionKey) option.textContent = t(optionKey, undefined, option.textContent);
    if (option.dataset.i18nParam === "channel" && isNumericChannel(option.value) && option.disabled) {
      option.title = channelUnsupportedReason(option.value);
    }
  });
  form.querySelectorAll("[data-i18n-loop]").forEach((element) => {
    element.textContent = t(element.dataset.i18nLoop, undefined, element.textContent);
  });
  const setGuidance = form.querySelector?.(".set-field-guidance");
  if (setGuidance) setGuidance.textContent = t("form.guidance.set_partial", undefined, SET_PARTIAL_GUIDANCE);
  const notes = form.querySelector?.(".command-notes");
  if (notes) {
    const title = notes.querySelector("strong");
    if (title) title.textContent = t("command.notes.heading");
    const summary = notes.querySelector("p");
    if (summary) summary.textContent = commandCatalog.commandDescription(command, commandMeta(command).description || "");
    notes.querySelectorAll("dt").forEach((term, index) => {
      const param = (PARAMS[command] || []).filter((item) => item.description)[index];
      if (param) term.textContent = t(fieldTranslationKey(command, param.name), undefined, param.label);
    });
    notes.querySelectorAll("dd").forEach((detail, index) => {
      const param = (PARAMS[command] || []).filter((item) => item.description)[index];
      if (param) detail.textContent = t(`form.description.${command.replaceAll("-", "_")}.${param.name}`, undefined, param.description);
    });
  }
}

function fieldTranslationKey(command, paramName) {
  if (command === "trigger-fire" && paramName === "channel") {
    return "form.field.trigger_fire_channel";
  }
  if (command === "trigger-step" && ["voltage", "current"].includes(paramName)) {
    return `form.field.triggered_${paramName}`;
  }
  return `form.field.${paramName}`;
}

function optionTranslationKey(paramName, value) {
  const commonKeys = {
    "": "none",
    all: "all",
    bus: "bus",
    immediate: "immediate",
    positive: "positive",
    negative: "negative",
    on: "on",
    off: "off",
    "setting-change": "setting_change",
    "cc-transition": "cc_transition"
  };
  const rearPinKeys = {
    "": "none",
    "1": "pin_1",
    "2": "pin_2",
    "3": "pin_3",
    "1,2": "pins_1_2",
    "1,3": "pins_1_3",
    "2,3": "pins_2_3",
    "1,2,3": "all"
  };
  const timingKeys = { "": "none", step: "step", segment: "segment", loop: "loop" };
  const keys = ["pins", "completion_pulse_pins"].includes(paramName)
    ? rearPinKeys
    : paramName === "completion_pulse_timing"
      ? timingKeys
      : commonKeys;
  return Object.hasOwn(keys, value) ? `form.option.${keys[value]}` : null;
}

function refreshCommandPresentation() {
  renderCommands();
  const selected = document.getElementById("selected-command");
  if (selected && state.selected) selected.textContent = commandDisplayName(state.selected);
  refreshCommandFormPresentation();
}

function refreshSelectedCommandDescription(presentationParts = []) {
  const description = document.getElementById("command-description");
  if (!description || !state.selected) return;
  const meta = commandMeta(state.selected);
  const text = [
    commandCatalog.commandDescription(state.selected, meta.description || ""),
    commandStatusText(meta),
    ...presentationParts
  ].filter(Boolean).join(" ");
  description.textContent = text;
  description.title = text;
}

function refreshCommandGuidancePresentation() {
  const guidance = document.getElementById("command-guidance");
  if (!guidance) return;
  const keys = {
    "trigger-step": "command.guidance.trigger_step",
    "trigger-list": "command.guidance.trigger_list",
    "trigger-fire": "command.guidance.trigger_fire"
  };
  const command = guidance.dataset?.command;
  const maintained = keys[command] ? t(keys[command]) : "";
  guidance.textContent = maintained;
  guidance.hidden = !maintained;
}

function updatePulseChildVisibility(command) {
  const enabled = command === "cycle-output"
    ? Boolean(document.getElementById("param-completion_pulse_enabled")?.checked)
    : command === "ramp"
      ? Boolean(document.getElementById("param-completion_pulse_timing")?.value)
      : true;
  document.querySelectorAll("#command-form .pulse-child-field").forEach((field) => {
    field.classList.toggle("visible", enabled);
  });
}

function runtimePayload() {
  if (state.executionMode === "simulate") {
    const planningModelId = selectedPlanningIdentity();
    return planningModelId
      ? { simulate: true, dry_run: false, planning_model_id: planningModelId, confirm: false }
      : { simulate: true, dry_run: false, confirm: false };
  }
  if (state.executionMode === "dry-run") {
    const identity = selectedPlanningIdentity();
    const runtime = { simulate: false, dry_run: true, confirm: false };
    if (identity?.startsWith("profile:")) runtime.planning_profile_id = identity.slice("profile:".length);
    else if (identity) runtime.planning_model_id = identity;
    return runtime;
  }
  const runtime = {
    resource: valueOrNull("resource"),
    backend: null,
    timeout_ms: 5000,
    safety_config: null,
    simulate: false,
    dry_run: false,
    confirm: hasRealWriteAuthorization()
  };
  const serialOptions = serialOptionsPayload();
  const expectedModelId = valueOrNull("expected-model-id");
  if (expectedModelId !== null) runtime.expected_model_id = expectedModelId;
  if (Object.keys(serialOptions).length) runtime.serial_options = serialOptions;
  if (document.getElementById("serial-remote")?.checked) runtime.serial_remote = true;
  if (document.getElementById("serial-local-on-close")?.checked) runtime.serial_local_on_close = true;
  return runtime;
}

function serialOptionsPayload() {
  const payload = {};
  const baudRate = optionalIntegerValue("serial-baud-rate");
  const dataBits = optionalIntegerValue("serial-data-bits");
  const parity = valueOrNull("serial-parity");
  const stopBits = valueOrNull("serial-stop-bits");
  const flowControl = valueOrNull("serial-flow-control");
  const readTermination = valueOrNull("serial-read-termination");
  const writeTermination = valueOrNull("serial-write-termination");
  if (baudRate !== null) payload.baud_rate = baudRate;
  if (dataBits !== null) payload.data_bits = dataBits;
  if (parity !== null) payload.parity = parity;
  if (stopBits !== null) payload.stop_bits = stopBits;
  if (flowControl !== null) payload.flow_control = flowControl;
  if (readTermination !== null) payload.read_termination = readTermination;
  if (writeTermination !== null) payload.write_termination = writeTermination;
  return payload;
}

function optionalIntegerValue(id) {
  const raw = valueOrNull(id);
  if (raw === null) return null;
  const parsed = Number(raw);
  return Number.isInteger(parsed) ? parsed : null;
}

function parameterPayload() {
  if (state.selected === "ramp-list") return { document: rampListDocument() };
  if (state.selected === "trigger-list") {
    const draft = activeTriggerListDraft();
    return {
      channel: state.triggerListActiveChannel,
      voltage_list: draft.steps.map((step) => step.voltage),
      current_list: draft.steps.map((step) => step.current),
      dwell_list: draft.steps.map((step) => step.dwell),
      bost_list: draft.steps.map((step) => step.bost),
      eost_list: draft.steps.map((step) => step.eost),
      count: draft.count,
      ...state.triggerListControls,
      trigger_output_pins: [...state.triggerListControls.trigger_output_pins],
      trigger_output_polarity: state.triggerListControls.trigger_output_polarity
    };
  }
  if (state.selected === "restore-from-snapshot") return restoreSnapshotParameters(state.loadedSnapshotDocument);
  if (state.selected === "sequence") return { document: sequenceDocumentFromEditor() };
  const payload = {};
  (PARAMS[state.selected] || []).forEach((param) => {
    const input = document.getElementById(`param-${param.name}`);
    if (!input) return;
    const parsed = parameterValue(param, input);
    if (parsed !== undefined) payload[param.name] = parsed;
  });
  if (state.selected === "cycle-output") {
    if (!payload.completion_pulse_enabled) {
      delete payload.completion_pulse_pins;
      delete payload.completion_pulse_polarity;
    }
    delete payload.completion_pulse_enabled;
  }
  if (state.selected === "ramp") {
    const channels = String(payload.channel).split(",").map(Number);
    if (channels.length > 1) {
      delete payload.channel;
      payload.channels = channels;
    }
    if (!payload.loop_enabled) {
      if (payload.completion_pulse_timing === "loop") payload.completion_pulse_timing = "";
    } else if (!Number.isInteger(payload.loop_count) || payload.loop_count < 2 || payload.loop_count > 10000) {
      throw new Error("Ramp Loop count must be an integer from 2 to 10,000.");
    }
    delete payload.loop_enabled;
    if (!payload.completion_pulse_timing) {
      delete payload.completion_pulse_timing;
      delete payload.completion_pulse_pins;
      delete payload.completion_pulse_polarity;
    }
  }
  return payload;
}

function enforcePulseFormRules(command, name, input) {
  if (command === "cycle-output") {
    updatePulseChildVisibility(command);
    return;
  }
  if (command !== "ramp") return;
  updatePulseChildVisibility(command);
  refreshLoopCompleteOption(command);
}

function applyParameterConstraint(input, name) {
  if (input.type !== "number") return;
  const parameter = electrical.resolveInputElectricalConstraint({
    parameterConstraints: state.parameterConstraints,
    electricalRatingsByModel: state.electricalRatingsByModel,
    modelId: null,
    channel: null,
    parameterName: name
  }).parameter;
  if (!parameter) return;
  Object.entries(parameter.attributes).forEach(([attribute, value]) => {
    input[attribute] = attribute === "title"
      ? parameterConstraintTitle(name, value)
      : value;
  });
  if (parameter.attributes.title) {
    input.dataset.parameterConstraint = name;
    input.dataset.parameterConstraintFallback = parameter.attributes.title;
  }
  if (parameter.exclusiveMin !== undefined) input.dataset.exclusiveMin = parameter.exclusiveMin;
}

function applyElectricalRatingConstraint(input, name) {
  if (input.type !== "number" || !["voltage", "start_voltage", "stop_voltage", "current"].includes(name)) return;
  restoreBaseElectricalConstraints(input);
  const constraint = arguments.length >= 3 ? arguments[2] : selectedInputElectricalConstraint(name);
  if (!constraint?.override) return;
  input.dataset.electricalBaseConstraints = JSON.stringify(Object.fromEntries(
    electricalConstraintAttributes.map((attribute) => [attribute, input.hasAttribute(attribute) ? input.getAttribute(attribute) : null])
  ));
  Object.entries(constraint.override.attributes).forEach(([attribute, value]) => {
    input.setAttribute(
      attribute,
      attribute === "title"
        ? electricalRatingConstraintTitle(name, constraint.override.attributes.max, value)
        : value
    );
  });
}

function parameterConstraintTitle(name, rawFallback = "") {
  return t(`form.constraint.${name}`, undefined, rawFallback);
}

function electricalRatingConstraintTitle(name, limit, rawFallback = "") {
  return t("form.constraint.electrical_rating", {
    limit,
    unit: name === "current" ? "A" : "V"
  }, rawFallback);
}

function refreshParameterConstraintPresentation(root = document) {
  root.querySelectorAll?.("[data-parameter-constraint]").forEach((input) => {
    const name = input.dataset.parameterConstraint;
    const rawFallback = input.dataset.parameterConstraintFallback || input.title;
    const serializedBase = input.dataset.electricalBaseConstraints;
    if (!serializedBase) {
      input.title = parameterConstraintTitle(name, rawFallback);
      return;
    }
    const base = JSON.parse(serializedBase);
    if (base.title !== null && base.title !== undefined) {
      base.title = parameterConstraintTitle(name, rawFallback);
      input.dataset.electricalBaseConstraints = JSON.stringify(base);
    }
    input.title = electricalRatingConstraintTitle(name, input.max, input.title);
  });
}

function restoreBaseElectricalConstraints(input) {
  const serialized = input.dataset.electricalBaseConstraints;
  if (!serialized) return;
  const base = JSON.parse(serialized);
  electricalConstraintAttributes.forEach((attribute) => {
    if (base[attribute] === null || base[attribute] === undefined) input.removeAttribute(attribute);
    else input.setAttribute(attribute, base[attribute]);
  });
  delete input.dataset.electricalBaseConstraints;
}

function refreshInputElectricalConstraints(input, name) {
  restoreBaseElectricalConstraints(input);
  applyParameterConstraint(input, name);
  if (arguments.length >= 3) applyElectricalRatingConstraint(input, name, arguments[2]);
  else applyElectricalRatingConstraint(input, name);
}

function selectedChannelRating() {
  const selected = document.getElementById("param-channel")?.value || "1";
  return selectedChannelRatingFor(selected);
}

function selectedChannelRatingFor(selected) {
  return selectedInputElectricalConstraint("voltage", selected).rating;
}

function selectedInputElectricalConstraint(name, channel = document.getElementById("param-channel")?.value || "1") {
  const selection = state.selected === "ramp" && String(channel).includes(",")
    ? String(channel).split(",").map(Number)
    : channel;
  return electrical.resolveInputElectricalConstraint({
    parameterConstraints: state.parameterConstraints,
    electricalRatingsByModel: state.electricalRatingsByModel,
    modelId: selectedElectricalRatingModel(),
    channel: selection,
    parameterName: name
  });
}

function rampChannelOptions(channels) {
  const values = channels.map(Number);
  const options = [];
  for (let size = 1; size <= values.length; size += 1) {
    const visit = (start, selected) => {
      if (selected.length === size) {
        options.push(selected.join(","));
        return;
      }
      for (let index = start; index < values.length; index += 1) visit(index + 1, [...selected, values[index]]);
    };
    visit(0, []);
  }
  return options;
}

function rampChannelOptionLabel(value, supported) {
  const channels = String(value).split(",");
  if (channels.length === supported.length && channels.length > 1) return t("form.option.all");
  return channels.map((channel) => `CH${channel}`).join(" + ");
}

function refreshElectricalRatingConstraints() {
  document.querySelectorAll("#command-form input[type=number]").forEach((input) => {
    refreshInputElectricalConstraints(input, input.id.replace("param-", ""));
  });
}

function validateConstrainedInputs() {
  let valid = true;
  document.querySelectorAll("#command-form input[type=number]").forEach((input) => {
    input.setCustomValidity("");
    const exclusiveMin = input.dataset.exclusiveMin;
    if (exclusiveMin !== undefined && input.value !== "" && Number(input.value) <= Number(exclusiveMin)) {
      input.setCustomValidity(`Value must be greater than ${exclusiveMin}.`);
    }
    valid &&= input.checkValidity();
  });
  return valid;
}

function refreshBasicInputConstraints() {
  document.querySelectorAll("[data-basic-voltage], [data-basic-current]").forEach((input) => {
    const channel = Number(input.dataset.basicVoltage || input.dataset.basicCurrent);
    const name = input.dataset.basicVoltage ? "voltage" : "current";
    const unsupported = channelUnsupportedReason(channel);
    restoreBaseElectricalConstraints(input);
    applyParameterConstraint(input, name);
    input.disabled = Boolean(unsupported);
    if (unsupported) {
      input.title = unsupported;
      input.setCustomValidity("");
      return;
    }
    applyElectricalRatingConstraint(input, name, selectedInputElectricalConstraint(name, channel));
    validateBasicInput(input);
  });
}

function validateBasicInput(input) {
  input.setCustomValidity("");
  const exclusiveMin = input.dataset.exclusiveMin;
  if (exclusiveMin !== undefined && input.value !== "" && Number(input.value) <= Number(exclusiveMin)) {
    input.setCustomValidity(`Value must be greater than ${exclusiveMin}.`);
  }
  return input.checkValidity();
}

function basicSetpointValues(channel) {
  const voltageInput = document.querySelector(`[data-basic-voltage="${channel}"]`);
  const currentInput = document.querySelector(`[data-basic-current="${channel}"]`);
  if (!voltageInput || !currentInput) return { ok: false, message: `CH${channel} controls are missing.` };
  const valid = [voltageInput, currentInput].every((input) => validateBasicInput(input));
  if (!valid) return { ok: false, message: `CH${channel} setpoint is outside allowed limits.` };
  if (voltageInput.value === "" && currentInput.value === "") return { ok: false, message: `CH${channel} requires V, A, or both.` };
  const parameters = {};
  if (voltageInput.value !== "") {
    const voltage = Number(voltageInput.value);
    if (!Number.isFinite(voltage)) return { ok: false, message: `CH${channel} V must be a finite number.` };
    parameters.voltage = voltage;
  }
  if (currentInput.value !== "") {
    const current = Number(currentInput.value);
    if (!Number.isFinite(current)) return { ok: false, message: `CH${channel} A must be a finite number.` };
    parameters.current = current;
  }
  return { ok: true, parameters };
}

function updateRampListPulse(name, value) {
  if (name === "timing" && !value) state.rampListCompletionPulse = null;
  else {
    state.rampListCompletionPulse ||= { timing: "segment", pins: [1], polarity: "positive" };
    state.rampListCompletionPulse[name] = name === "pins" ? parseRearPins(value) : value;
  }
  renderForm("ramp-list");
  updateSelectedCommandState();
}

function restoreSnapshotParameters(document) {
  return restoreDocument.restoreSnapshotParameters(document, state.restoreChannel, state.restoreOutputState, normalizeChannelValue);
}

function normalizeRestoreChannel(value) {
  return restoreDocument.normalizeRestoreChannel(value, normalizeChannelValue);
}

function parameterValue(param, input) {
  if (param.type === "checkbox") return input.checked;
  if (param.type === "number") {
    if (input.value === "") return param.optional ? undefined : null;
    return Number(input.value);
  }
  if (param.type === "textarea") return parseMaybeJson(input.value);
  if (input.value === "") return undefined;
  if (param.name === "channel") return normalizeChannelValue(input.value);
  if (param.parser === "intList") return parseDelimitedNumbers(input.value, true);
  if (param.parser === "numberList") return parseDelimitedNumbers(input.value, false);
  return input.value;
}

function normalizeChannelValue(value) {
  if (value === "all") return value;
  return /^[1-9]\d*$/.test(value) ? Number(value) : value;
}

function parseDelimitedNumbers(value, integerOnly) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean)
    .map((item) => integerOnly ? parseInt(item, 10) : Number(item));
}

function commandDisplayName(name) {
  if (!name) return "";
  return commandCatalog.commandDisplayName(name, commandDisplayNameFallback(name));
}

function commandSourceDisplayName(name) {
  if (!name) return "";
  return commandCatalog.commandSourceDisplayName(name, commandDisplayNameFallback(name));
}

function commandDisplayNameFallback(name) {
  const overrides = {
    snapshot: "Create snapshot", "restore-from-snapshot": "Restore snapshot", "protection-set": "Set protection",
    clear: "Clear Status / Errors", capabilities: "Get capabilities", identify: "Read device information", error: "Read errors"
  };
  if (overrides[name]) return overrides[name];
  const spaced = name.replace(/-/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function parseRearPins(value) {
  const source = Array.isArray(value) ? value : String(value || "").split(",");
  return source.map((item) => Number(String(item).trim())).filter((item) => [1, 2, 3].includes(item));
}

function pinsSelectValue(value) { return parseRearPins(value).join(","); }

function rearPinDisplayName(value) {
  const labels = { "1": "Pin 1", "2": "Pin 2", "3": "Pin 3", "1,2": "Pins 1 + 2", "1,3": "Pins 1 + 3", "2,3": "Pins 2 + 3", "1,2,3": "All" };
  const fallback = value === "" ? "None" : labels[value] || value;
  const key = optionTranslationKey("pins", value);
  return key ? t(key, undefined, fallback) : fallback;
}

function optionDisplayName(value) {
  const overrides = { "cc-transition": "CC transition" };
  const key = optionTranslationKey("", value);
  if (key) return t(key, undefined, value === "" ? "None" : overrides[value] || value);
  if (overrides[value]) return overrides[value];
  const spaced = value.replace(/-/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}


  return {
    loadCommands,
    renderExpectedModelOptions,
    renderCommands,
    selectCommand,
    renderForm,
    refreshCommandFormPresentation,
    refreshCommandPresentation,
    refreshSelectedCommandDescription,
    updatePulseChildVisibility,
    runtimePayload,
    serialOptionsPayload,
    optionalIntegerValue,
    parameterPayload,
    enforcePulseFormRules,
    applyParameterConstraint,
    refreshParameterConstraintPresentation,
    applyElectricalRatingConstraint,
    restoreBaseElectricalConstraints,
    refreshInputElectricalConstraints,
    selectedChannelRating,
    selectedChannelRatingFor,
    selectedInputElectricalConstraint,
    rampChannelOptions,
    rampChannelOptionLabel,
    refreshElectricalRatingConstraints,
    validateConstrainedInputs,
    refreshBasicInputConstraints,
    validateBasicInput,
    basicSetpointValues,
    updateRampListPulse,
    restoreSnapshotParameters,
    normalizeRestoreChannel,
    parameterValue,
    normalizeChannelValue,
    parseDelimitedNumbers,
    commandDisplayName,
    parseRearPins,
    pinsSelectValue,
    rearPinDisplayName,
    optionDisplayName
  };
}
