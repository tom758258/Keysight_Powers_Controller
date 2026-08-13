import * as webuiContext from "./execution-context.js";
import * as webuiElectrical from "./electrical.js";
import * as webuiApi from "./api.js";
import * as webuiState from "./state.js";
import * as webuiDevice from "./device-resource.js";
import * as webuiCommandCatalog from "./command-catalog.js";
import * as webuiCommandForm from "./command-form.js";
import * as webuiResults from "./results.js";
import * as webuiLiveData from "./live-data.js";
import * as webuiJsonFiles from "./json-files.js";
import * as webuiRampListDocument from "./ramp-list.js";
import * as webuiTriggerListDocument from "./trigger-list.js";
import * as webuiSequenceDocument from "./sequence.js";
import * as webuiSnapshotDocument from "./snapshot-restore.js";
import * as webuiRestoreDocument from "./snapshot-restore.js";
import * as webuiJobTransport from "./jobs.js";
import * as webuiBasicControls from "./basic-controls.js";
import * as webuiCommandSupport from "./command-support.js";
import * as webuiWorkflows from "./workflows.js";
import * as webuiLocaleUi from "./locale_ui.js";
import { applyStaticTranslations } from "./dom_i18n.js";
import { t } from "./i18n.js";

const state = webuiState.createInitialState({
  rampListSegments: [defaultRampSegment()],
  triggerListControls: webuiTriggerListDocument.defaultTriggerListControls(),
  triggerListChannels: webuiTriggerListDocument.defaultTriggerListChannels(),
  sequenceSteps: [{ action: "wait", seconds: 0 }]
});

const TRIP_GUARDED_COMMANDS = new Set(["output-on", "cycle-output", "ramp", "ramp-list", "smoke-output", "apply"]);
const TRIP_WARNING_COMMANDS = new Set([
  "sequence",
  "restore-from-snapshot",
  "trigger-pulse",
  "trigger-step",
  "trigger-list",
  "trigger-fire"
]);
const REAR_PIN_OPTIONS = ["1", "2", "3", "1,2", "1,3", "2,3", "1,2,3"];
const OPTIONAL_REAR_PIN_OPTIONS = ["", ...REAR_PIN_OPTIONS];
const TRIGGER_COMMANDS = new Set([
  "trigger-pulse",
  "trigger-status",
  "trigger-step",
  "trigger-list",
  "trigger-fire",
  "trigger-abort"
]);
const DEFAULT_CHANNELS = [1, 2, 3];
const REAR_TRIGGER_PULSE_MODEL_ID = "keysight-e36312a";
let pendingResourceLiveSupport = null;

const deviceResourceController = webuiDevice.createDeviceResourceController({
  state,
  devicePresentation: webuiDevice,
  executionContext: webuiContext,
  fetchJson: (...args) => webuiApi.fetchJson(...args),
  clearStaleResourceLiveSupport: (...args) => clearStaleResourceLiveSupport(...args),
  syncBasicFromLivePanel: (...args) => syncBasicFromLivePanel(...args),
  selectCommand: (...args) => selectCommand(...args),
  renderCommands: (...args) => renderCommands(...args),
  valueOrNull: (...args) => valueOrNull(...args),
  exactSupportContextSummary: (...args) => exactSupportContextSummary(...args),
  currentExactLiveSupport: (...args) => currentExactLiveSupport(...args),
  channelCapabilityForModel: (...args) => channelCapabilityForModel(...args),
  currentResourceModel: (...args) => currentResourceModel(...args),
  refreshBasicInputConstraints: (...args) => refreshBasicInputConstraints(...args),
  refreshElectricalRatingConstraints: (...args) => refreshElectricalRatingConstraints(...args),
  renderWorkspaceSummary: (...args) => renderWorkspaceSummary(...args),
  updateSelectedCommandState: (...args) => updateSelectedCommandState(...args),
  closeEventSource: (...args) => closeEventSource(...args),
  renderClientResult: (...args) => renderClientResult(...args),
  renderBlankLivePanel: (...args) => renderBlankLivePanel(...args)
});

var {
  setDeviceOptionsExpanded, setDeviceResourceExpanded, updateDeviceResourceSummary,
  buildDeviceResourceSummary, planningIdentitySummary, liveResourceSummary,
  expectedModelSummary, selectedExpectedModel, selectedPlanningIdentity,
  rememberCurrentExecutionIdentity, isNoHardwareMode, realAuthorizationContext,
  hasRealWriteAuthorization, updateExecutionModeUi,
  populateIdentitySelector, handleExecutionModeChange, stopRealLiveJobsAndWait,
  selectedExpectedModelLabel, physicalModelDisplayName, detectedResourceDisplayModel,
  resourceModelDetectionRecorded, detectedCommandModelForResource,
  detectedChannelModelForResource, selectedCommandModel, selectedChannelModel,
  actualCurrentResourceModel, e3646aGlobalOutputCapability, basicOutputPresentation,
  selectedElectricalRatingModel, handleExpectedModelChanged, updateLiveMonitorButton, refreshLiveMonitorPresentation,
  refreshHealth, refreshHealthPresentation, refreshDeviceResourcePresentation, setStateIndicator
} = deviceResourceController;
const STOPPABLE_WORKFLOWS = new Set(["ramp", "ramp-list", "sequence"]);
const ELECTRICAL_CONSTRAINT_ATTRIBUTES = ["min", "max", "step", "title"];

const PARAMS = {
  "list-resources": [{ name: "live_only", type: "checkbox", label: "Live only" }],
  verify: [],
  clear: [],
  error: [{ name: "max_reads", type: "number", label: "Max reads", value: 20 }],
  readback: [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all" }],
  set: webuiCommandForm.setOutputParams(),
  apply: [...webuiCommandForm.applyOutputParams(), { name: "no_output", type: "checkbox", label: "Do not enable output" }],
  "output-on": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }],
  "output-off": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }],
  "safe-off": [{
    name: "channel",
    type: "select",
    label: "Channel",
    options: ["all", "1", "2", "3"],
    value: "all",
    description: "Disables the selected output, or every available output when set to all, then reads back each output state. Voltage/current setpoints and protection settings are not changed."
  }],
  "cycle-output": [
    { name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" },
    { name: "duration_ms", type: "number", label: "Duration(ms)", value: 100 },
    { name: "completion_pulse_enabled", type: "checkbox", label: "Trigger pulse when finished", pulseToggle: true },
    { name: "completion_pulse_pins", type: "select", label: "Rear pins", options: REAR_PIN_OPTIONS, value: "1", parser: "intList", pulseChild: true },
    { name: "completion_pulse_polarity", type: "select", label: "Polarity", options: ["positive", "negative"], value: "positive", pulseChild: true }
  ],
  ramp: [
    { name: "enable_output", type: "checkbox", label: "Enable output", ariaLabel: "Enable output after first setpoint", helpId: "ramp-enable-output-help", compactHelp: true, description: "Output is enabled only after the first safe setpoint is written and verified. It remains ON after normal completion. Stop workflow turns off every instrument output. Real hardware still requires confirmation." },
    { name: "loop_enabled", type: "checkbox", label: "Enable loop" },
    { name: "loop_count", type: "number", label: "Loop count", value: 2, conditionalLoop: true },
    { name: "channel", type: "select", label: "Channel", options: ["1"], value: "1", description: "Selected channels share the same Ramp parameters and advance in lockstep." },
    { name: "current", type: "number", label: "Current(A)", value: 0.1 },
    { name: "start_voltage", type: "number", label: "Start voltage(V)", value: 0 },
    { name: "stop_voltage", type: "number", label: "Stop voltage(V)", value: 1 },
    { name: "step_voltage", type: "number", label: "Step voltage(V)", value: 0.1 },
    { name: "delay_ms", type: "number", label: "Wait between steps (ms)", value: 0 },
    { name: "completion_pulse_timing", type: "select", label: "Pulse timing", options: ["", "step", "segment", "loop"], value: "" },
    { name: "completion_pulse_pins", type: "select", label: "Rear pins", options: REAR_PIN_OPTIONS, value: "1", parser: "intList", pulseChild: true },
    { name: "completion_pulse_polarity", type: "select", label: "Polarity", options: ["positive", "negative"], value: "positive", pulseChild: true }
  ],
  "ramp-list": [],
  "smoke-output": webuiCommandForm.smokeOutputParams(),
  "protection-set": [
    { name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" },
    { name: "ovp_voltage", type: "number", label: "OVP voltage(V)", value: 5 },
    { name: "ocp", type: "select", label: "OCP", options: ["", "on", "off"], value: "" },
    { name: "ocp_delay", type: "number", label: "OCP delay(s)", optional: true },
    { name: "ocp_delay_trigger", type: "select", label: "OCP delay trigger", options: ["", "setting-change", "cc-transition"], value: "" }
  ],
  "clear-protection": [{ name: "channel", type: "select", label: "Channel", options: ["", "all", "1", "2", "3"], value: "" }],
  "trigger-pulse": [
    { name: "pins", type: "select", label: "Rear pins", options: REAR_PIN_OPTIONS, value: "1", parser: "intList", description: "E36312A only. Configures the selected rear pins as trigger outputs, keeps the current programmed setpoint, and sends global *TRG. The pulse may also fire other armed BUS triggers." },
    { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
    { name: "polarity", type: "select", label: "Polarity", options: ["positive", "negative"], value: "positive" },
    { name: "exclusive_pins", type: "checkbox", label: "Exclusive pins", description: "Resets unselected rear pins before configuring the selected pulse pins." }
  ],
  "trigger-status": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all", description: "Read-only E36312A query of rear pins, trigger source, and STEP/LIST state. It does not modify instrument settings." }],
  "trigger-step": triggerStepParams(),
  "trigger-list": [],
  "trigger-fire": [
    { name: "channel", type: "select", label: "Abort target channel", options: ["", "1", "2", "3"], value: "", optional: true, description: "Used only to abort this output channel if Wait complete times out or is interrupted." },
    { name: "wait_complete", type: "checkbox", label: "Wait complete", description: "Waits for the instrument-wide operation-complete event. Requires an Abort target channel." },
    ...triggerWaitParams()
  ],
  "trigger-abort": [
    { name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all", description: "E36312A only. Aborts Trigger/LIST execution for the selected channel or all channels. It does not turn outputs off." },
    { name: "max_errors", type: "number", label: "Max errors", value: 20, description: "Limits how many instrument error-queue entries are read after aborting." }
  ],
  identify: [],
  snapshot: [{
    name: "max_errors",
    type: "number",
    label: "Max errors",
    value: 20,
    description: "Limits how many times the snapshot reads the instrument error queue. Reading stops early when the instrument reports no error. Each reported error is removed from the instrument queue."
  }],
  sequence: []
};

function defaultRampSegment() {
  return webuiRampListDocument.defaultRampSegment();
}

function triggerStepParams() {
  return webuiCommandForm.triggerStepParams();
}

function triggerListParams() {
  return webuiCommandForm.triggerListParams(OPTIONAL_REAR_PIN_OPTIONS);
}

function triggerWaitParams() {
  return webuiCommandForm.triggerWaitParams();
}

const commandController = webuiCommandForm.createCommandController({
  state,
  params: PARAMS,
  triggerCommands: TRIGGER_COMMANDS,
  fetchJson: (...args) => webuiApi.fetchJson(...args),
  commandCatalog: webuiCommandCatalog,
  populateIdentitySelector: (...args) => populateIdentitySelector(...args),
  commandMeta: (...args) => commandMeta(...args),
  renderWorkspaceSummary: (...args) => renderWorkspaceSummary(...args),
  prefillClearProtectionChannel: (...args) => prefillClearProtectionChannel(...args),
  updateSelectedCommandState: (...args) => updateSelectedCommandState(...args),
  renderRampListForm: (...args) => renderRampListForm(...args),
  renderTriggerListForm: (...args) => renderTriggerListForm(...args),
  renderSnapshotForm: (...args) => renderSnapshotForm(...args),
  renderRestoreForm: (...args) => renderRestoreForm(...args),
  renderSequenceForm: (...args) => renderSequenceForm(...args),
  pulseTimingDisplayName: (...args) => pulseTimingDisplayName(...args),
  isNumericChannel: (...args) => isNumericChannel(...args),
  isChannelSupported: (...args) => isChannelSupported(...args),
  supportedChannelsForCurrentModel: (...args) => supportedChannelsForCurrentModel(...args),
  channelUnsupportedReason: (...args) => channelUnsupportedReason(...args),
  applyWorkflowPulseControlState: (...args) => applyWorkflowPulseControlState(...args),
  renderLoopControl: (...args) => renderLoopControl(...args),
  refreshLoopCompleteOption: (...args) => refreshLoopCompleteOption(...args),
  selectedPlanningIdentity: (...args) => selectedPlanningIdentity(...args),
  valueOrNull: (...args) => valueOrNull(...args),
  hasRealWriteAuthorization: (...args) => hasRealWriteAuthorization(...args),
  rampListDocument: (...args) => rampListDocument(...args),
  activeTriggerListDraft: (...args) => activeTriggerListDraft(...args),
  sequenceDocumentFromEditor: (...args) => sequenceDocumentFromEditor(...args),
  parseMaybeJson: (...args) => parseMaybeJson(...args),
  restoreDocument: webuiRestoreDocument,
  electrical: webuiElectrical,
  electricalConstraintAttributes: ELECTRICAL_CONSTRAINT_ATTRIBUTES,
  selectedElectricalRatingModel: (...args) => selectedElectricalRatingModel(...args)
});

var {
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
} = commandController;

const liveDataController = webuiLiveData.createLiveDataController({
  state,
  isNoHardwareMode: (...args) => isNoHardwareMode(...args),
  renderBlankLivePanel: (...args) => renderBlankLivePanel(...args),
  runtimePayload: (...args) => runtimePayload(...args),
  fetchJson: (...args) => webuiApi.fetchJson(...args),
  updateLiveMonitorButton: (...args) => updateLiveMonitorButton(...args),
  closeEventSource: (...args) => closeEventSource(...args),
  renderLivePanel: (...args) => renderLivePanel(...args),
  setLiveState: (...args) => setLiveState(...args),
  liveStateText: (...args) => liveStateText(...args),
  stopLivePreviewSnapshot: (...args) => stopLivePreviewSnapshot(...args)
});

var { startLive, toggleLiveMonitor, stopLive, startLivePreviewSnapshot, isFreshLivePreviewSample, waitForLiveTerminal } = liveDataController;

const jobEventController = webuiJobTransport.createJobEventController({
  state,
  fetchJson: (...args) => webuiApi.fetchJson(...args),
  closeEventSource: (...args) => closeEventSource(...args),
  updateHistory: (...args) => updateHistory(...args),
  setWorkflowControl: (...args) => setWorkflowControl(...args),
  updateJobResult: (...args) => updateJobResult(...args),
  jobCommand: (...args) => jobCommand(...args),
  refreshSnapshotFormIfVisible: (...args) => refreshSnapshotFormIfVisible(...args),
  renderJobDetail: (...args) => renderJobDetail(...args),
  populateResourceSelect: (...args) => populateResourceSelect(...args),
  captureResourceScanFailure: (...args) => captureResourceScanFailure(...args),
  refreshHealth: (...args) => refreshHealth(...args),
  startLivePreviewSnapshot: (...args) => startLivePreviewSnapshot(...args),
  shouldRefreshLiveAfterCommand: (...args) => shouldRefreshLiveAfterCommand(...args),
  captureLatestSnapshotDocument: (...args) => captureLatestSnapshotDocument(...args),
  captureWorkspaceResult: (...args) => captureWorkspaceResult(...args),
  updateBasicActionFromJob: (...args) => updateBasicActionFromJob(...args),
  updateResourceModelFromJob: (...args) => updateResourceModelFromJob(...args),
  finishResourceLiveSupportEvaluation: (...args) => finishResourceLiveSupportEvaluation(...args),
  jobLabel: (...args) => jobLabel(...args),
  captureRestorePlanPreview: (...args) => captureRestorePlanPreview(...args),
  renderForm: (...args) => renderForm(...args),
  updateSelectedCommandState: (...args) => updateSelectedCommandState(...args),
  reconcileWorkflowJob: (...args) => reconcileWorkflowJob(...args)
});

var { subscribeToJob, handleJobEvent } = jobEventController;

document.addEventListener("DOMContentLoaded", async () => {
  webuiLocaleUi.initializeLocaleUi({ refreshPresentation: refreshLocalizedPresentation });
  applyStaticTranslations(document);
  bind();
  renderBlankLivePanel();
  await refreshHealth();
  await loadCommands();
  drawTrend();
});

function bind() {
  document.getElementById("run").addEventListener("click", runSelected);
  document.getElementById("scan").addEventListener("click", scanResources);
  document.getElementById("resource-select").addEventListener("change", syncSelectedResource);
  document.getElementById("resource").addEventListener("input", syncTypedResource);
  document.getElementById("resource").addEventListener("change", syncTypedResource);
  document.getElementById("resource-select").addEventListener("change", updateDeviceResourceSummary);
  document.getElementById("expected-model-id")?.addEventListener("change", handleExpectedModelChanged);
  document.querySelectorAll('input[name="execution-mode"]').forEach((radio) => radio.addEventListener("change", handleExecutionModeChange));
  document.getElementById("real-write-enabled")?.addEventListener("change", () => {
    state.realWriteAuthorization = document.getElementById("real-write-enabled").checked ? realAuthorizationContext() : null;
    updateExecutionModeUi();
  });
  document.getElementById("device-options-toggle").addEventListener("click", (event) => {
    event.stopPropagation();
    setDeviceOptionsExpanded(document.getElementById("device-options-toggle").getAttribute("aria-expanded") !== "true");
  });
  document.getElementById("device-options-panel").addEventListener("click", (event) => {
    event.stopPropagation();
  });
  document.getElementById("toggle-device-resource").addEventListener("click", () => {
    setDeviceResourceExpanded(document.getElementById("toggle-device-resource").getAttribute("aria-expanded") !== "true");
  });
  document.addEventListener("click", () => setDeviceOptionsExpanded(false));
  document.addEventListener("keydown", (event) => {
    const button = document.getElementById("device-options-toggle");
    if (event.key === "Escape" && button.getAttribute("aria-expanded") === "true") {
      setDeviceOptionsExpanded(false);
      button.focus();
    }
  });
  document.getElementById("command-filter").addEventListener("input", renderCommands);
  document.getElementById("live-start").addEventListener("click", toggleLiveMonitor);
  document.getElementById("result-toggle").addEventListener("click", toggleResultPanel);
  document.getElementById("job-result-toggle").addEventListener("click", toggleJobResultPanel);
  document.getElementById("job-result-clear").addEventListener("click", clearJobResults);
  document.getElementById("advanced-command-toggle").addEventListener("click", toggleAdvancedCommands);
  document.querySelectorAll("[data-basic-set]").forEach((button) => {
    button.addEventListener("click", () => runBasicSet(Number(button.dataset.basicSet)));
  });
  document.querySelectorAll("[data-basic-output]").forEach((button) => {
    button.addEventListener("click", () => runBasicOutput(Number(button.dataset.basicOutput)));
  });
  document.querySelector("[data-basic-all-output]").addEventListener("click", runBasicOutputAll);
  document.querySelectorAll("[data-basic-voltage], [data-basic-current]").forEach((input) => {
    input.addEventListener("input", () => {
      input.dataset.basicDirty = "true";
      validateBasicInput(input);
    });
    input.addEventListener("blur", () => validateBasicInput(input));
  });
  setDeviceOptionsExpanded(false);
  setDeviceResourceExpanded(true);
  updateDeviceResourceSummary();
  updateExecutionModeUi({ resetAuthorization: true });
}

function syncTypedResource() {
  updateExecutionModeUi({ renderCommands: false, resetAuthorization: true });
}

function buildNativeJsonPickerAccept() {
  return webuiJsonFiles.buildNativeJsonPickerAccept();
}

async function openJsonFile({ description, extensions }) {
  return webuiJsonFiles.openJsonFile({ description, extensions });
}

function buildJsonFileAccept(extensions) {
  return webuiJsonFiles.buildJsonFileAccept(extensions);
}

function chooseJsonFile(accept) {
  return webuiJsonFiles.chooseJsonFile(accept);
}

async function saveJsonFile(text, { description, extensions, suggestedName }) {
  return webuiJsonFiles.saveJsonFile(text, { description, extensions, suggestedName });
}

function abortError(message) {
  return webuiJsonFiles.abortError(message);
}

function isAbortError(error) {
  return webuiJsonFiles.isAbortError(error);
}

const JSON_MIME_TYPE = "application/json";
const SNAPSHOT_JSON_EXTENSIONS = [".snapshot.json", ".json"];
const SEQUENCE_JSON_EXTENSIONS = [".sequence.json", ".json"];
const RAMP_LIST_JSON_EXTENSIONS = [".ramp-list.json", ".json"];
const TRIGGER_LIST_WORKSPACE_JSON_EXTENSIONS = [".trigger-list-workspace.json", ".json"];

const workflows = webuiWorkflows.createWorkflows({
  state,
  optionalRearPinOptions: OPTIONAL_REAR_PIN_OPTIONS,
  rearPinOptions: REAR_PIN_OPTIONS,
  webuiCommandForm,
  webuiRampListDocument,
  webuiTriggerListDocument,
  openJsonFile: (...args) => openJsonFile(...args),
  saveJsonFile: (...args) => saveJsonFile(...args),
  isAbortError: (...args) => isAbortError(...args),
  rampListJsonExtensions: RAMP_LIST_JSON_EXTENSIONS,
  triggerListWorkspaceJsonExtensions: TRIGGER_LIST_WORKSPACE_JSON_EXTENSIONS,
  renderClientResult: (...args) => renderClientResult(...args),
  optionDisplayName: (...args) => optionDisplayName(...args),
  renderForm: (...args) => renderForm(...args),
  updateSelectedCommandState: (...args) => updateSelectedCommandState(...args),
  rearPinDisplayName: (...args) => rearPinDisplayName(...args),
  parseRearPins: (...args) => parseRearPins(...args),
  renderLoopControl: (...args) => renderLoopControl(...args),
  applyWorkflowPulseControlState: (...args) => applyWorkflowPulseControlState(...args),
  pulseTimingDisplayName: (...args) => pulseTimingDisplayName(...args),
  pinsSelectValue: (...args) => pinsSelectValue(...args),
  applyParameterConstraint: (...args) => applyParameterConstraint(...args),
  supportedChannelsForCurrentModel: (...args) => supportedChannelsForCurrentModel(...args),
  rampChannelOptions: (...args) => rampChannelOptions(...args),
  rampChannelOptionLabel: (...args) => rampChannelOptionLabel(...args),
  selectedChannelModel: (...args) => selectedChannelModel(...args),
  updateWorkflowDocumentValidity: (...args) => updateWorkflowDocumentValidity(...args),
  updateRampListPulse: (...args) => updateRampListPulse(...args)
});

var {
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
} = workflows;

const artifactAndSequenceWorkflows = webuiWorkflows.createArtifactAndSequenceWorkflows({
  state,
  params: PARAMS,
  rearPinOptions: REAR_PIN_OPTIONS,
  webuiCommandForm,
  webuiSnapshotDocument,
  webuiRestoreDocument,
  webuiSequenceDocument,
  openJsonFile: (...args) => openJsonFile(...args),
  saveJsonFile: (...args) => saveJsonFile(...args),
  isAbortError: (...args) => isAbortError(...args),
  renderClientResult: (...args) => renderClientResult(...args),
  renderForm: (...args) => renderForm(...args),
  updateSelectedCommandState: (...args) => updateSelectedCommandState(...args),
  effectiveSequenceLoopCount,
  jobCommand: (...args) => jobCommand(...args),
  snapshotJsonExtensions: SNAPSHOT_JSON_EXTENSIONS,
  sequenceJsonExtensions: SEQUENCE_JSON_EXTENSIONS,
  optionDisplayName: (...args) => optionDisplayName(...args),
  rearPinDisplayName: (...args) => rearPinDisplayName(...args),
  parseRearPins: (...args) => parseRearPins(...args),
  renderLoopControl: (...args) => renderLoopControl(...args),
  applyWorkflowPulseControlState: (...args) => applyWorkflowPulseControlState(...args),
  applyParameterConstraint: (...args) => applyParameterConstraint(...args),
  updateWorkflowDocumentValidity: (...args) => updateWorkflowDocumentValidity(...args),
  runtimePayload: (...args) => runtimePayload(...args),
  restoreSnapshotParameters: (...args) => restoreSnapshotParameters(...args),
  submitJob: (...args) => submitJob(...args),
  addHistory: (...args) => addHistory(...args),
  subscribeToJob: (...args) => subscribeToJob(...args)
});

var {
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
} = artifactAndSequenceWorkflows;

/* ==========================================
   Snapshot Feature
   ========================================== */

async function scanResources() {
  if (isNoHardwareMode()) {
    renderClientResult("Scan Device", "failed", "Scan Device is available only in Real hardware mode.", { error: "Real mode required" });
    return;
  }
  state.resourceScan = { status: "scanning", resources: [], detail: "" };
  try {
    const payload = {
      command: "list-resources",
      runtime: runtimePayload(),
      parameters: { live_only: true }
    };
    const response = await webuiApi.fetchJson("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    addHistory(response.job_id, "list-resources", "accepted", "Scan Device");
    subscribeToJob(response.job_id, "/api/events");
  } catch (error) {
    state.resourceScan = { status: "failed", resources: [], detail: error.message || String(error) };
    updateDeviceResourceSummary();
    console.error("Scan resources failed", error);
    renderClientResult("Scan Device", "failed", error.message || String(error), {
      error: "Scan resources failed",
      detail: error.message || String(error)
    });
  }
}

function toggleAdvancedCommands() {
  const panel = document.getElementById("advanced-commands");
  setAdvancedCommandsExpanded(panel.hidden);
}

function setAdvancedCommandsExpanded(expanded) {
  const panel = document.getElementById("advanced-commands");
  const button = document.getElementById("advanced-command-toggle");
  panel.hidden = !expanded;
  panel.classList.toggle("collapsed", !expanded);
  button.textContent = t(expanded ? "basic_controls.action.hide_commands" : "basic_controls.action.show_more_commands");
  button.setAttribute("aria-expanded", String(expanded));
}

async function runBasicSet(channel) {
  const actionKey = basicActionKey("set", channel);
  const unsupported = channelUnsupportedReason(channel);
  if (unsupported) {
    failBasicAction(actionKey, "Unsupported channel", unsupported, { channel, label: `Basic CH${channel} Set` });
    return;
  }
  const values = basicSetpointValues(channel);
  if (!values.ok) {
    failBasicAction(actionKey, "Invalid setpoint", values.message, { channel, label: `Basic CH${channel} Set` });
    return;
  }
  await submitBasicJob("set", { channel, ...values.parameters }, actionKey, `Basic CH${channel} Set`);
}

async function runBasicOutput(channel) {
  const unsupported = channelUnsupportedReason(channel);
  if (unsupported) {
    failBasicAction(basicActionKey("output", channel), "Unsupported channel", unsupported, { channel, label: `Basic CH${channel} Output` });
    return;
  }
  if (basicOutputPresentation().mode !== "ordinary") return;
  if (basicOutputLockAction(channel)) return;
  const current = state.executionMode === "real" && basicLiveChannel(channel)?.output_enabled === true;
  const command = current ? "output-off" : "output-on";
  const desiredOutput = !current;
  await submitBasicJob(command, { channel }, basicActionKey("output", channel), `Basic CH${channel} ${desiredOutput ? "ON" : "OFF"}`, { desiredOutput });
}

async function runBasicOutputAll() {
  const presentation = basicOutputPresentation();
  if (presentation.mode === "e3646a-disabled") return;
  if (basicOutputLockAction("all")) return;
  const supported = presentation.mode === "e3646a-global"
    ? presentation.capability.channels
    : supportedChannelsForCurrentModel();
  if (!supported.length) return;
  const globalState = presentation.mode === "e3646a-global" ? e3646aGlobalOutputState(presentation) : null;
  const allOn = state.executionMode === "real" && (globalState ? globalState === "on" : basicAllOutputsOn());
  const command = allOn ? "output-off" : "output-on";
  const desiredOutput = !allOn;
  await submitBasicJob(command, { channel: "all" }, basicActionKey("output", "all"), `Basic All ${desiredOutput ? "ON" : "OFF"}`, { desiredOutput });
}

async function submitBasicJob(command, parameters, actionKey, label, actionState = {}) {
  const meta = commandMeta(command);
  if (meta.disabled) {
    failBasicAction(actionKey, "Command unavailable", meta.disabled_reason || "This command is not available for the selected resource.", { command, parameters, label });
    return;
  }

  const ratingGuard = electricalRatingGuardReason(command, parameters);
  const tripGuard = tripGuardReason(command, parameters);
  if (ratingGuard || tripGuard) {
    failBasicAction(actionKey, ratingGuard ? "Rating guard" : "Protection trip active", ratingGuard || tripGuard, { command, parameters, label });
    return;
  }

  const payload = { command, runtime: runtimePayload(), parameters };
  if (meta.requires_confirm && state.executionMode === "real" && !payload.runtime.confirm) {
    failBasicAction(actionKey, "Authorization required", "Enable real hardware writes for this resource before running this command.", { command, parameters, label });
    return;
  }

  setBasicActionState(actionKey, "pending", { key: "basic_controls.status.running" }, { command, parameters, ...actionState });
  try {
    const response = await submitJob(payload);
    state.basicJobActions[response.job_id] = { actionKey, command, parameters, ...actionState };
    addHistory(response.job_id, command, "accepted", label);
    subscribeToJob(response.job_id, "/api/events");
  } catch (error) {
    failBasicAction(actionKey, "Submit failed", error.message || String(error), { command, parameters, label });
  }
}

function failBasicAction(actionKey, error, detail, context = {}) {
  setBasicActionState(actionKey, "error", detail, context);
  renderClientResult(context.label || basicActionDisplayName(actionKey), "failed", detail, {
    error,
    detail,
    ...context
  });
}

async function runSelected() {
  if (!state.selected) return;
  if (state.workflowControl.phase === "active") {
    await stopActiveWorkflow();
    return;
  }
  if (state.workflowControl.phase !== "idle") return;

  let validatedSequenceDocument = null;
  if (state.selected === "sequence") {
    try {
      validatedSequenceDocument = sequenceDocumentFromEditor();
    } catch (error) {
      renderClientResult(
        "sequence",
        "failed",
        error.message || String(error),
        {
          error: "Sequence validation failed",
          detail: error.message || String(error),
          command: "sequence"
        }
      );
      return;
    }
  }

  let validatedRestoreDocument = null;
  if (state.selected === "restore-from-snapshot") {
    if (!state.loadedSnapshotDocument) {
      renderClientResult(
        "restore-from-snapshot",
        "failed",
        "Load a snapshot before running restore.",
        {
          error: "Snapshot validation failed",
          detail: "Load a snapshot before running restore.",
          command: "restore-from-snapshot"
        }
      );
      return;
    }
    try {
      validateRestoreSnapshot(state.loadedSnapshotDocument);
      validatedRestoreDocument = state.loadedSnapshotDocument;
    } catch (error) {
      renderClientResult(
        "restore-from-snapshot",
        "failed",
        error.message || String(error),
        {
          error: "Snapshot validation failed",
          detail: error.message || String(error),
          command: "restore-from-snapshot"
        }
      );
      return;
    }
  }

  const meta = commandMeta(state.selected);
  if (meta.disabled) {
    renderClientResult(state.selected, "failed", meta.disabled_reason || "This command is not available for the selected resource.", {
      error: "Command unavailable",
      detail: meta.disabled_reason || "This command is not available for the selected resource.",
      command: state.selected
    });
    return;
  }
  const payload = {
    command: state.selected,
    runtime: runtimePayload(),
    parameters: state.selected === "sequence"
      ? { document: validatedSequenceDocument }
      : state.selected === "restore-from-snapshot"
        ? restoreSnapshotParameters(validatedRestoreDocument)
      : parameterPayload()
  };
  const channelGuard = channelAvailabilityGuardReason(state.selected, payload.parameters);
  if (channelGuard) {
    renderClientResult(state.selected, "failed", channelGuard, {
      error: "Unsupported channel",
      detail: channelGuard,
      command: state.selected,
      parameters: payload.parameters
    });
    return;
  }
  const tripGuard = tripGuardReason(state.selected, payload.parameters);
  if (tripGuard) {
    renderClientResult(state.selected, "failed", tripGuard, {
      error: "Protection trip active",
      detail: tripGuard,
      command: state.selected,
      parameters: payload.parameters
    });
    return;
  }
  if (meta.requires_confirm && state.executionMode === "real" && !payload.runtime.confirm) {
    renderClientResult(state.selected, "failed", "Enable real hardware writes for this resource before running.", {
      error: "Confirmation required",
      detail: "Enable real hardware writes for this resource before running.",
      command: state.selected,
      runtime: { confirm: false }
    });
    return;
  }
  const submittedCommand = state.selected;
  if (STOPPABLE_WORKFLOWS.has(submittedCommand)) {
    setWorkflowControl("submitting", { command: submittedCommand });
  }
  try {
    const response = await submitJob(payload);
    addHistory(response.job_id, submittedCommand, "accepted");
    if (submittedCommand === "snapshot") {
      refreshSnapshotFormIfVisible(response.job_id);
    }
    if (STOPPABLE_WORKFLOWS.has(submittedCommand)) {
      setWorkflowControl("active", { command: submittedCommand, jobId: response.job_id });
    }
    subscribeToJob(response.job_id, "/api/events");
  } catch (error) {
    if (STOPPABLE_WORKFLOWS.has(submittedCommand)) {
      setWorkflowControl("idle");
    }
    renderClientResult(submittedCommand, "failed", error.message || String(error), {
      error: "Submit failed",
      detail: error.message || String(error),
      command: submittedCommand
    });
  }
}

async function stopActiveWorkflow() {
  const control = state.workflowControl;
  if (control.phase !== "active" || !control.jobId || !STOPPABLE_WORKFLOWS.has(control.command)) return;
  const jobId = control.jobId;
  setWorkflowControl("stopping", { command: control.command, jobId });
  updateJobResult(jobId, "cancel_requested", { key: "job.summary.waiting_cleanup" });
  try {
    await webuiApi.fetchJson(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
      body: "{}"
    });
  } catch (error) {
    await reconcileWorkflowJob(jobId, error);
  }
}

function setWorkflowControl(phase, values = {}) {
  state.workflowControl = phase === "idle"
    ? { phase: "idle", jobId: null, command: null }
    : {
        phase,
        jobId: values.jobId ?? state.workflowControl.jobId,
        command: values.command ?? state.workflowControl.command
      };
  updateWorkflowRunButton();
  renderCommands();
  if (phase === "idle" && state.selected) updateSelectedCommandState();
}

function updateWorkflowRunButton() {
  const button = document.getElementById("run");
  if (!button) return;
  const { phase, command } = state.workflowControl;
  const activeWorkflow = STOPPABLE_WORKFLOWS.has(command);
  button.classList.toggle("workflow-stop", activeWorkflow && phase === "active");
  const labelKey = phase === "submitting"
    ? "workflow.action.starting"
    : phase === "active" && activeWorkflow
      ? "workflow.action.stop"
      : phase === "stopping"
        ? "workflow.action.stopping"
        : "workflow.action.run";
  button.textContent = t(labelKey);
  const stopMeaning = activeWorkflow && ["active", "stopping"].includes(phase);
  const stopDescription = t("workflow.guidance.stop_safe_off");
  button.title = stopMeaning ? stopDescription : "";
  button.setAttribute("aria-label", stopMeaning ? stopDescription : button.textContent);
  if (phase === "active" && activeWorkflow) button.disabled = false;
  if (phase === "submitting" || phase === "stopping") button.disabled = true;
  const guidance = document.getElementById("command-guidance");
  if (guidance && stopMeaning) {
    guidance.textContent = phase === "stopping"
      ? t("workflow.guidance.waiting_cleanup")
      : stopDescription;
    guidance.hidden = false;
  }
}

async function reconcileWorkflowJob(jobId, originalError = null) {
  try {
    const job = await webuiApi.fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (["finished", "failed", "cancelled"].includes(job.status)) {
      const code = job.error_code ? `  ${job.error_code}` : "";
      updateJobResult(jobId, job.status, job.status === "failed" ? `Failed${code}` : webuiResults.statusLabel(job.status), job);
      setWorkflowControl("idle");
      return;
    }
    if (job.status === "cancel_requested") {
      setWorkflowControl("stopping", { command: job.command, jobId });
      return;
    }
  } catch (error) {
    if (!originalError) originalError = error;
  }
  if (originalError) {
    renderClientResult(
      state.workflowControl.command || "workflow",
      "failed",
      originalError.message || String(originalError),
      { error: "Cancellation request failed", detail: originalError.message || String(originalError) }
    );
  }
}

function submitJob(payload) {
  return webuiJobTransport.submitJob(webuiApi.fetchJson, payload);
}

function captureLatestSnapshotDocument(job) {
  if (!job || job.command !== "snapshot" || job.status !== "finished" || !job.result) {
    return false;
  }
  try {
    validateSnapshotDocument(job.result);
  } catch (error) {
    return false;
  }
  state.latestSnapshotDocument = job.result;
  state.latestSnapshotMetadata = {
    savedAt: Date.now(),
    model: job.result.idn?.model || null,
    serial: job.result.idn?.serial || null,
    resource: job.result.resource || job.runtime?.resource || null
  };
  return true;
}

async function renderJobDetail(jobId, event) {
  try {
    const job = await webuiApi.fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
    updateJobResult(job.job_id, job.status, webuiResults.jobSummary(job, event), job);
    renderResult({
      job_id: job.job_id,
      command: job.command,
      status: job.status,
      runtime: job.runtime,
      parameters: job.parameters,
      result: job.result,
      error: job.error
    });
    return job;
  } catch (error) {
    const rawError = event.data?.error || event.data?.detail;
    updateJobResult(jobId, event.type, rawError || { key: event.type === "failed" ? "job.summary.failed" : `job.summary.${event.type}` });
    renderResult(event.data);
    return null;
  }
}

function shouldRefreshLiveAfterCommand(event, job) {
  const runtime = job?.runtime;
  return event.type === "finished"
    && job?.command !== "list-resources"
    && Boolean(runtime?.resource)
    && runtime.resource === valueOrNull("resource")
    && runtime.simulate === false
    && runtime.dry_run === false;
}

function renderResult(data) {
  document.getElementById("result").textContent = JSON.stringify(data, null, 2);
}

function currentWorkspaceResultContext(command) {
  return webuiContext.buildCurrentWorkspaceResultContext({
    command,
    executionMode: state.executionMode,
    planningIdentity: selectedPlanningIdentity() || "",
    resource: valueOrNull("resource") || "",
    expectedModelGuard: selectedExpectedModel() || "",
    canonicalModelId: actualCurrentResourceModel() || ""
  });
}

function captureWorkspaceResult(job) {
  const entry = webuiContext.buildWorkspaceResultEntry(job, {
    commandModelByResource: state.resourceModels,
    channelModelByResource: state.resourceChannelModels
  });
  if (!entry) return false;
  const resource = entry.context.resource || "";
  if (["capabilities", "identify", "verify"].includes(job.command)) {
    captureResourceLiveSupport(job, resource);
  }
  state.workspaceResults[entry.key] = entry.job;
  renderWorkspaceSummary();
  return true;
}

function renderWorkspaceSummary() {
  const container = document.getElementById("workspace-summary-content");
  if (!container) return;
  container.innerHTML = "";
  if (!state.selected) {
    webuiResults.renderWorkspaceEmpty(container, t("workspace.empty.choose_command"));
    return;
  }
  const context = currentWorkspaceResultContext(state.selected);
  const job = webuiContext.findWorkspaceResult(state.workspaceResults, context);
  if (!job) {
    webuiResults.renderWorkspaceEmpty(container, t("workspace.empty.run_command"));
    return;
  }
  webuiResults.renderWorkspaceJob(container, job, context, {
    commandDisplayName,
    transportScopeLabel,
    backendScopeLabel,
    liveSupportSummary,
    formatNum,
    successfulJobSummary: webuiResults.successfulJobSummary
  });
}

function renderClientResult(command, status, summary, detail) {
  const jobId = `client-${Date.now()}`;
  addHistory(jobId, command, status, command);
  updateJobResult(jobId, status, summary);
  renderResult(detail);
}

function jobCommand(jobId) {
  return state.jobs.find((item) => item.jobId === jobId)?.command || null;
}

function captureRestorePlanPreview(job) {
  if (job?.status === "finished" && job.result?.plan) {
    state.restorePlanPreviewStatus = "finished";
    state.restorePlanPreview = job.result;
    return;
  }
  state.restorePlanPreviewStatus = "failed";
  state.restorePlanPreview = { error: job?.error || "Restore plan preview did not finish." };
}

function jobLabel(jobId) {
  return state.jobs.find((item) => item.jobId === jobId)?.label || null;
}

async function populateResourceSelect(resources) {
  const select = document.getElementById("resource-select");
  const input = document.getElementById("resource");
  const previous = input.value;
  select.innerHTML = "";
  updateResourceModels(resources);
  if (!Array.isArray(resources) || resources.length === 0) {
    state.resourceScan = { status: "empty", resources: [], detail: "" };
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No live resources found";
    select.appendChild(option);
    updateExecutionModeUi({ renderCommands: false });
    return;
  }

  resources.forEach((resource) => {
    const name = typeof resource === "string" ? resource : resource?.name;
    if (!name) return;
    const option = document.createElement("option");
    option.value = name;
    option.textContent = resourceLabel(resource, name);
    select.appendChild(option);
  });
  if (select.options.length === 0) {
    state.resourceScan = { status: "empty", resources: [], detail: "" };
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No live resources found";
    select.appendChild(option);
    updateExecutionModeUi({ renderCommands: false });
    return;
  }
  state.resourceScan = {
    status: "results",
    resources: Array.from(select.options, (option) => option.value).filter(Boolean),
    detail: ""
  };

  if (select.options.length > 0) {
    select.selectedIndex = 0;
    input.value = select.value;
  }
  updateExecutionModeUi({
    renderCommands: false,
    resetAuthorization: input.value !== previous
  });
  refreshBasicInputConstraints();
  if (state.selected) selectCommand(state.selected);
  else renderCommands();
  await refreshSelectedResourceContext(input.value);
}

function captureResourceScanFailure(detail) {
  state.resourceScan = {
    status: "failed",
    resources: [],
    detail: String(detail || "Resource scan failed")
  };
  updateDeviceResourceSummary();
}

function resourceLabel(resource, name) {
  return webuiDevice.resourceLabel(resource, name);
}

async function syncSelectedResource() {
  const input = document.getElementById("resource");
  const previous = input.value;
  const value = document.getElementById("resource-select").value;
  input.value = value;
  updateExecutionModeUi({
    renderCommands: false,
    resetAuthorization: value !== previous
  });
  refreshBasicInputConstraints();
  renderWorkspaceSummary();
  if (state.selected) selectCommand(state.selected);
  else renderCommands();
  if (value !== previous) await refreshSelectedResourceContext(value);
}

async function refreshSelectedResourceContext(resource) {
  if (isNoHardwareMode() || !resource) return;
  clearStaleResourceLiveSupport(resource);
  const hasLiveSupport = state.resourceLiveSupportContext?.resource === resource
    && Boolean(state.resourceLiveSupport);
  if (hasLiveSupport) {
    await refreshSelectedResourcePreview(resource);
    return;
  }
  await evaluateResourceLiveSupport(resource);
}

async function evaluateResourceLiveSupport(resource) {
  if (pendingResourceLiveSupport) {
    pendingResourceLiveSupport.requestedResource = resource === pendingResourceLiveSupport.resource
      ? null
      : resource;
    return;
  }
  const pending = { resource, jobId: null, requestedResource: null };
  pendingResourceLiveSupport = pending;
  const runtime = { ...runtimePayload(), resource, confirm: false };
  delete runtime.serial_remote;
  delete runtime.serial_local_on_close;
  const payload = {
    command: "identify",
    runtime,
    parameters: {}
  };
  try {
    const response = await submitJob(payload);
    pending.jobId = response.job_id;
    addHistory(response.job_id, "identify", "accepted", "Read device information");
    subscribeToJob(response.job_id, "/api/events");
  } catch (error) {
    if (pendingResourceLiveSupport === pending) pendingResourceLiveSupport = null;
    renderClientResult("identify", "failed", error.message || String(error), {
      error: "Support evaluation failed",
      detail: error.message || String(error),
      resource
    });
    await refreshRequestedResourceLiveSupport(pending);
  }
}

async function finishResourceLiveSupportEvaluation(jobId) {
  if (pendingResourceLiveSupport?.jobId !== jobId) return false;
  const completed = pendingResourceLiveSupport;
  pendingResourceLiveSupport = null;
  await refreshRequestedResourceLiveSupport(completed);
  return true;
}

async function refreshRequestedResourceLiveSupport(completed) {
  const requested = completed?.requestedResource;
  if (!requested || requested !== valueOrNull("resource")) return;
  await refreshSelectedResourceContext(requested);
}

function updateResourceModels(resources) {
  if (!Array.isArray(resources)) return;
  resources.forEach((resource) => {
    if (!resource || typeof resource === "string") return;
    const name = resource.name;
    if (!name) return;
    updateResourceModel(name, resource.model_id, resource.idn?.model);
  });
}

function updateResourceModelFromJob(job) {
  const result = job?.result || {};
  const resultResource = result.resource;
  const resourceName = resultResource?.name || (typeof resultResource === "string" ? resultResource : job?.runtime?.resource);
  const reportedModel = resultResource?.idn?.model || result.idn?.model || result.model || result.driver?.model;
  const modelId = resultResource?.model_id || result.live_support?.model_id || null;
  const updated = updateResourceModel(resourceName, modelId, reportedModel);
  if (resourceName && resourceName === valueOrNull("resource")) updateDeviceResourceSummary();
  if (updated) {
    refreshBasicInputConstraints();
    syncBasicFromLivePanel(state.livePanel);
    if (state.selected) selectCommand(state.selected);
    else renderCommands();
  }
}

function updateResourceModel(resource, modelId, reportedModel = null) {
  if (!resource) return false;
  const next = supportedModelKey(modelId);
  const nextChannelModel = channelModelKey(modelId);
  const detectedModel = typeof reportedModel === "string" ? reportedModel.trim() : null;
  if (detectedModel) state.resourceDisplayModels[resource] = detectedModel;
  if (state.resourceLiveSupportContext?.resource === resource
    && modelId
    && state.resourceLiveSupportContext.model_id !== modelId) {
    state.resourceLiveSupport = null;
    state.resourceLiveSupportContext = null;
  }
  if (state.resourceModels[resource] === next && state.resourceChannelModels[resource] === nextChannelModel) return false;
  state.resourceModels[resource] = next;
  state.resourceChannelModels[resource] = nextChannelModel;
  if (resource === valueOrNull("resource")) {
    updateExecutionModeUi({ renderCommands: false, resetAuthorization: true });
  }
  return true;
}

function captureResourceLiveSupport(job, resource) {
  const liveSupport = job?.result?.live_support;
  if (!resource || resource !== valueOrNull("resource") || !liveSupport) return false;
  state.resourceLiveSupport = liveSupport;
  state.resourceLiveSupportContext = {
    resource,
    model_id: liveSupport.model_id || null,
    transport_scope: liveSupport.transport_scope || "unknown",
    backend_scope: liveSupport.backend_scope || "system_visa"
  };
  updateDeviceResourceSummary();
  syncBasicFromLivePanel(state.livePanel);
  if (state.selected) selectCommand(state.selected);
  else renderCommands();
  return true;
}

function clearStaleResourceLiveSupport(resource) {
  if (!state.resourceLiveSupportContext || state.resourceLiveSupportContext.resource === resource) return false;
  state.resourceLiveSupport = null;
  state.resourceLiveSupportContext = null;
  return true;
}

const commandSupport = webuiCommandSupport.createCommandSupport({
  state,
  defaultChannels: DEFAULT_CHANNELS,
  isNoHardwareMode,
  selectedPlanningIdentity,
  physicalModelDisplayName,
  selectedCommandModel,
  valueOrNull,
  detectedCommandModelForResource,
  selectedChannelModel
});

let {
  currentExactLiveSupport,
  selectedModelLiveSupport,
  commandMeta,
  exactCommandSupportText,
  selectedCommandSupport,
  currentResourceModel,
  supportedModelKey,
  commandDisabledReason,
  exactSupportContextSummary,
  liveSupportSummary,
  transportScopeLabel,
  backendScopeLabel,
  supportedChannelsForCurrentModel,
  isChannelSupported,
  isNumericChannel,
  channelUnsupportedReason,
  channelCapabilityForCurrentModel,
  channelCapabilityForModel,
  currentChannelCapabilityModel,
  channelModelKey,
  channelAvailabilityGuardReason,
  selectedChannelsForCommand,
  outputControlTitle,
  outputAllControlTitle,
  outputControlScopeForCurrentModel,
  globalOutputHintText
} = commandSupport;
function toggleResultPanel() {
  state.resultCollapsed = !state.resultCollapsed;
  syncResultPanelState();
}

function expandResultPanel() {
  state.resultCollapsed = false;
  syncResultPanelState();
}

function syncResultPanelState() {
  const panel = document.getElementById("result-panel");
  const button = document.getElementById("result-toggle");
  panel.classList.toggle("collapsed", state.resultCollapsed);
  button.textContent = state.resultCollapsed ? "+" : "-";
  button.setAttribute("aria-label", t(state.resultCollapsed ? "accessibility.expand_result_detail" : "accessibility.collapse_result_detail"));
  button.setAttribute("aria-expanded", String(!state.resultCollapsed));
}

function toggleJobResultPanel() {
  state.jobResultCollapsed = !state.jobResultCollapsed;
  syncJobResultPanelState();
}

function syncJobResultPanelState() {
  const panel = document.getElementById("job-result-panel");
  const button = document.getElementById("job-result-toggle");
  panel.classList.toggle("collapsed", state.jobResultCollapsed);
  button.textContent = state.jobResultCollapsed ? "+" : "-";
  button.setAttribute("aria-label", t(state.jobResultCollapsed ? "accessibility.expand_job_result" : "accessibility.collapse_job_result"));
  button.setAttribute("aria-expanded", String(!state.jobResultCollapsed));
}

function clearJobResults() {
  state.jobs = [];
  renderHistory();
}

function pulseTimingDisplayName(command, value) {
  if (value === "") return "None";
  const labels = command === "ramp"
    ? { step: "Every step", segment: "Ramp complete", loop: "Loop complete" }
    : command === "ramp-list"
      ? { step: "Every step", segment: "Segment complete", loop: "Loop complete" }
      : {};
  return labels[value] || optionDisplayName(value);
}

function refreshLoopCompleteOption(command) {
  const timing = command === "ramp"
    ? document.getElementById("param-completion_pulse_timing")
    : command === "ramp-list"
      ? document.getElementById("ramp-list-pulse-timing")
      : null;
  if (!timing) return;
  const loopChecked = command === "ramp"
    ? Boolean(document.getElementById("param-loop_enabled")?.checked)
    : state.rampListLoopEnabled;
  const enabled = command === "ramp"
    ? loopChecked
    : loopChecked && effectiveRampListLoopCount() >= 2;
  const loopOption = Array.from(timing.options || []).find((option) => option.value === "loop");
  if (loopOption) {
    loopOption.disabled = !enabled;
    loopOption.title = enabled ? "" : "Enable loop to select Loop complete.";
  }
  if (!loopChecked && timing.value === "loop") timing.value = "";
}

function renderLoopControl({
  prefix,
  current = 1,
  onValue = () => {},
  onDisable = () => {},
  enabledInput = null,
  countInputId = null,
  loopEnabled = null,
  countDraft = null,
  onEnabled = () => {},
  onDraft = () => {},
  translate = null,
  enabledTranslationKey = null,
  countTranslationKey = null
}) {
  const hasExplicitState = typeof loopEnabled === "boolean";
  const wrapper = document.createElement("div");
  wrapper.className = "loop-control " + prefix + "-loop-control";
  const enabled = enabledInput || document.createElement("input");
  enabled.type = "checkbox";
  enabled.id ||= prefix + "-loop-enabled";
  enabled.checked = hasExplicitState ? loopEnabled : Number.isInteger(current) && current >= 2;
  const enabledLabel = webuiCommandForm.createCheckboxField(
    enabled,
    enabledTranslationKey && translate ? translate(enabledTranslationKey) : "Enable loop"
  );
  if (enabledTranslationKey) enabledLabel.querySelector(".checkbox-label-text").dataset.i18nLoop = enabledTranslationKey;
  wrapper.appendChild(enabledLabel);

  const mountCount = (value = 2) => {
    wrapper.querySelector?.(".loop-count-field")?.remove();
    const label = document.createElement("label");
    label.className = "loop-count-field";
    let labelText = null;
    if (countTranslationKey) {
      labelText = document.createElement("span");
      labelText.className = "loop-count-label-text";
      labelText.textContent = translate ? translate(countTranslationKey) : "Loop count";
      labelText.dataset.i18nLoop = countTranslationKey;
      label.appendChild(labelText);
    } else {
      label.textContent = "Loop count";
    }
    const count = document.createElement("input");
    count.type = "number";
    count.id = countInputId || prefix + "-loop-count";
    count.min = "2";
    count.max = "10000";
    count.step = "1";
    count.required = true;
    count.value = hasExplicitState
      ? String(value ?? "")
      : String(Number.isInteger(value) && value >= 2 && value <= 10000 ? value : 2);
    const update = () => {
      const parsed = count.value === "" ? Number.NaN : Number(count.value);
      onDraft(count.value);
      onValue(Number.isInteger(parsed) && parsed >= 2 && parsed <= 10000 ? parsed : Number.NaN);
      refreshLoopCompleteOption(prefix);
      if (["ramp-list", "sequence"].includes(prefix)) updateWorkflowDocumentValidity(prefix);
      updateSelectedCommandState();
    };
    count.addEventListener("input", update);
    count.addEventListener("change", update);
    label.appendChild(count);
    wrapper.appendChild(label);
  };

  enabled.addEventListener("change", () => {
    onEnabled(enabled.checked);
    if (enabled.checked) {
      onDraft("2");
      onValue(2);
      mountCount(2);
    } else {
      onDraft("2");
      onValue(1);
      wrapper.querySelector?.(".loop-count-field")?.remove();
      onDisable();
    }
    refreshLoopCompleteOption(prefix);
    if (["ramp-list", "sequence"].includes(prefix)) updateWorkflowDocumentValidity(prefix);
    updateSelectedCommandState();
  });
  if (enabled.checked) mountCount(hasExplicitState ? countDraft : current);
  return wrapper;
}

function stopLivePreviewSnapshot() {
  const jobId = state.previewJobId;
  closeEventSource("previewEvents");
  state.previewJobId = null;
  if (jobId) {
    webuiApi.fetchJson(`/api/live/${jobId}/stop`, { method: "POST" }).catch((error) => {
      console.error("Live preview stop failed", error);
    });
  }
}

async function refreshSelectedResourcePreview(resource) {
  if (isNoHardwareMode()) return;
  stopLivePreviewSnapshot();
  renderBlankLivePanel();
  if (!resource) {
    setLiveState(t("live_data.status.not_monitoring"), "state-idle", t("live_data.status.no_resource"));
    return;
  }
  const healthState = await refreshHealth();
  if (resource !== valueOrNull("resource")) return;
  await startLivePreviewSnapshot(healthState, resource);
}

const basicControls = webuiBasicControls.createBasicControls({
  state,
  defaultChannels: DEFAULT_CHANNELS,
  valueOrNull,
  basicOutputPresentation,
  supportedChannelsForCurrentModel,
  channelUnsupportedReason,
  commandMeta,
  outputControlTitle,
  outputAllControlTitle,
  basicSetpointValues,
  refreshBasicInputConstraints,
  validateBasicInput,
  eventSummary: webuiResults.eventSummary
});

let {
  basicActionKey,
  basicActionDisplayName,
  basicActionMessage,
  basicLiveChannel,
  basicChannelOutputState,
  e3646aGlobalOutputState,
  basicAllOutputsOn,
  setBasicActionState,
  clearBasicActionState,
  renderBasicActionState,
  renderBasicChannelActionState,
  updateBasicActionFromJob,
  syncBasicFromLivePanel,
  syncBasicSetpointInput,
  clearBasicInputDirty,
  renderBasicOutputButton,
  renderBasicAllOutputButton,
  applyBasicPerChannelOutputPresentation,
  applyBasicAllOutputPresentation,
  applyBasicOutputPresentation,
  renderBasicOutputActionStates,
  renderBasicOutputControlState,
  basicOutputLockAction,
  clearResolvedBasicErrors,
  liveSetpointsMatchBasicInputs,
  nearlyEqual,
  basicStatusText,
  setBasicStatus,
  refreshBasicControlsPresentation: refreshBasicControlsPresentationBase
} = basicControls;

function refreshBasicControlsPresentation() {
  refreshBasicControlsPresentationBase();
  const advancedToggle = document.getElementById("advanced-command-toggle");
  if (advancedToggle) {
    const expanded = advancedToggle.getAttribute("aria-expanded") === "true";
    advancedToggle.textContent = t(expanded ? "basic_controls.action.hide_commands" : "basic_controls.action.show_more_commands");
  }
}

function refreshWorkflowOperationalPresentation() {
  updateWorkflowRunButton();
}

function refreshLiveDataPresentation() {
  const panel = state.livePanel;
  if (!panel) return;
  if (!panel.resource && panel.status === "ok" && !panel.message) {
    setLiveState(t("live_data.status.not_monitoring"), "state-idle", t("live_data.status.no_resource"));
  } else {
    setLiveState(liveStateText(panel.status, panel.timestamp, panel.message, panel.stale), liveStateClass(panel.status, panel.stale), panel.message);
  }
  panel.channels.forEach((channel) => renderChannelCard(channel, panel));
  drawTrend();
}

function refreshResultPresentation() {
  syncResultPanelState();
  syncJobResultPanelState();
  renderHistory();
  renderWorkspaceSummary();
}

function refreshLocalizedPresentation() {
  applyStaticTranslations(document);
  webuiLocaleUi.renderLanguageButton(document.getElementById("locale-toggle"));
  refreshDeviceResourcePresentation();
  refreshCommandPresentation();
  refreshSelectedCommandGuardPresentation();
  webuiWorkflows.refreshWorkflowPresentation(document);
  refreshWorkflowOperationalPresentation();
  refreshBasicControlsPresentation();
  refreshResultPresentation();
  refreshLiveDataPresentation();
}

function renderLivePanel(data) {
  const previous = state.livePanel;
  const resource = data.resource || previous?.resource || "";
  const sameResource = previous?.resource === resource;
  const next = {
    timestamp: data.timestamp || previous?.timestamp || Date.now() / 1000,
    resource,
    model: data.model || (sameResource ? previous?.model : null),
    model_id: data.model_id || (sameResource ? previous?.model_id : null),
    stale: Boolean(data.stale),
    status: data.status || "ok",
    message: data.message || data.error || "",
    channels: mergeLiveChannels(
      data.channels,
      sameResource ? previous?.channels : [],
      Boolean(data.stale && sameResource)
    )
  };
  state.livePanel = next;
  state.samples.push({ timestamp: next.timestamp, data: next });
  state.samples = state.samples.slice(-60);
  const modelChanged = !next.stale && updateResourceModel(next.resource, next.model_id, next.model);

  setLiveState(liveStateText(next.status, next.timestamp, next.message, next.stale), liveStateClass(next.status, next.stale), next.message);

  if (next.resource && next.resource === valueOrNull("resource")) updateDeviceResourceSummary();
  next.channels.forEach((channel) => renderChannelCard(channel, next));
  syncBasicFromLivePanel(next);
  if (modelChanged) renderCommands();
  if (modelChanged) refreshBasicInputConstraints();
  if (state.selected) updateSelectedCommandState();
  drawTrend();
}

function setLiveState(text, stateClass = "state-idle", title = "") {
  setStateIndicator("live-state", text, stateClass, title || text);
}

function liveStateText(status, timestamp, message = "", stale = false) {
  return webuiLiveData.liveStateText(status, timestamp, message, stale);
}

function liveStateClass(status, stale = false) {
  return webuiLiveData.liveStateClass(status, stale);
}

function renderBlankLivePanel(status = "ok", message = "") {
  const panel = {
    timestamp: Date.now() / 1000,
    resource: valueOrNull("resource") || "",
    model: null,
    model_id: null,
    stale: false,
    status,
    message,
    channels: blankLiveChannels()
  };
  state.livePanel = panel;
  panel.channels.forEach((channel) => renderChannelCard(channel, panel));
  syncBasicFromLivePanel(panel);
  drawTrend();
}

function blankLiveChannels() {
  return webuiLiveData.blankLiveChannels(DEFAULT_CHANNELS);
}

function mergeLiveChannels(channels, previousChannels = [], preservePreviousValues = false) {
  return webuiLiveData.mergeLiveChannels(channels, previousChannels, preservePreviousValues, DEFAULT_CHANNELS);
}

function mergeLiveChannel(previous, incoming, preservePreviousValues) {
  return webuiLiveData.mergeLiveChannel(previous, incoming, preservePreviousValues);
}

function renderChannelCard(channel, sample) {
  webuiLiveData.renderChannelCard(channel, sample, {
    channelUnsupportedReason,
    formatNum,
    formatProtectionVoltage,
    formatProtectionState,
    openClearProtection
  });
}

function protectionBadge(label, tripped) {
  return webuiLiveData.protectionBadge(label, tripped);
}

function openClearProtection(channel) {
  setAdvancedCommandsExpanded(true);
  state.activeCategory = "protection";
  selectCommand("clear-protection");
  const input = document.getElementById("param-channel");
  if (input) input.value = String(channel);
  updateSelectedCommandState();
  const workspace = document.querySelector(".workspace");
  if (workspace) workspace.scrollIntoView({ behavior: "smooth", block: "nearest" });
  const focusTarget = input || document.getElementById("run");
  if (focusTarget) focusTarget.focus({ preventScroll: true });
}

function prefillClearProtectionChannel() {
  if (state.selected !== "clear-protection") return;
  const input = document.getElementById("param-channel");
  if (!input) return;
  const channels = currentTripChannels();
  input.value = channels.length === 1 ? String(channels[0]) : "";
}

function updateSelectedCommandState() {
  if (!state.selected) return;
  syncTriggerImmediateControls(state.selected);
  const meta = commandMeta(state.selected);
  const parameters = selectedCommandParameters();
  const presentation = selectedCommandPresentation(state.selected, parameters);
  const {
    tripGuard,
    channelGuard,
    ratingGuard,
    setGuard,
    triggerControlGuard,
    triggerFireWaitGuard,
    workflowPulseGuard
  } = presentation;
  const runButton = document.getElementById("run");
  refreshSelectedCommandDescription(presentation.descriptionParts);
  webuiCommandForm.renderCommandGuidance(state.selected, parameters, triggerControlGuardReason, triggerFireWaitGuardReason);
  if (state.workflowControl.phase !== "idle") {
    runButton.disabled = state.workflowControl.phase !== "active";
    updateWorkflowRunButton();
    return;
  }
  runButton.disabled = Boolean(meta.disabled || channelGuard || tripGuard || ratingGuard || setGuard || triggerControlGuard || triggerFireWaitGuard || workflowPulseGuard);
  runButton.disabled ||= !validateConstrainedInputs();
  if (state.selected === "restore-from-snapshot") {
    const restoreValid = isLoadedRestoreSnapshotValid();
    runButton.disabled ||= !restoreValid;
    const previewButton = document.getElementById("btn-preview-restore-plan");
    if (previewButton) previewButton.disabled = !restoreValid || state.restorePlanPreviewStatus === "running";
  }
  if (["sequence", "ramp-list"].includes(state.selected)) {
    updateWorkflowDocumentValidity(state.selected, runButton);
  }
}

function selectedCommandParameters() {
  let parameters = {};
  try {
    parameters = parameterPayload();
  } catch (e) {
    // Keep the form responsive while artifact editors contain invalid JSON.
  }
  return parameters;
}

function selectedCommandPresentation(command, parameters) {
  const tripGuard = tripGuardReason(command, parameters);
  const channelGuard = channelAvailabilityGuardReason(command, parameters);
  const ratingGuard = electricalRatingGuardReason(command, parameters);
  const setGuard = setRequiresSetpointGuardReason(command, parameters);
  const triggerControlGuard = triggerControlGuardReason(command, parameters);
  const triggerFireWaitGuard = triggerFireWaitGuardReason(command, parameters);
  const workflowPulseGuard = workflowPulseGuardReason(command, parameters);
  const tripWarning = tripContextWarning(command);
  return {
    tripGuard,
    channelGuard,
    ratingGuard,
    setGuard,
    triggerControlGuard,
    triggerFireWaitGuard,
    workflowPulseGuard,
    descriptionParts: [channelGuard, ratingGuard, setGuard, tripGuard || tripWarning, workflowPulseGuard].filter(Boolean)
  };
}

function refreshSelectedCommandGuardPresentation() {
  if (!state.selected) return;
  const parameters = selectedCommandParameters();
  const presentation = selectedCommandPresentation(state.selected, parameters);
  refreshSelectedCommandDescription(presentation.descriptionParts);
  webuiCommandForm.renderCommandGuidance(state.selected, parameters, triggerControlGuardReason, triggerFireWaitGuardReason);
  refreshTriggerImmediateControlTitle(state.selected);
  document.querySelectorAll?.("#command-form [data-pulse-control]").forEach((input) => {
    const prerequisite = input.dataset.pulsePrerequisiteI18n
      ? t(input.dataset.pulsePrerequisiteI18n)
      : "";
    refreshWorkflowPulseControlPresentation(input, prerequisite);
  });
}

function updateWorkflowDocumentValidity(command, runButton = null) {
  let valid = true;
  let validationMessage = "";
  try {
    if (command === "sequence") sequenceDocumentFromEditor();
    else if (command === "ramp-list") validateRampListDocument(rampListDocument());
  } catch (e) {
    valid = false;
    validationMessage = e.message || String(e);
  }
  if (command === "sequence") {
    const error = document.getElementById("sequence-document-error");
    if (error) {
      error.textContent = validationMessage;
      error.hidden = valid;
    }
  }
  const saveButton = document.getElementById(command === "sequence" ? "save-sequence" : "save-ramp-list");
  if (saveButton) saveButton.disabled = !valid;
  if (runButton) runButton.disabled ||= !valid;
  return valid;
}

function syncTriggerImmediateControls(command) {
  if (!["trigger-step", "trigger-list"].includes(command)) return;
  const source = String(document.getElementById("param-source")?.value || "bus").toLowerCase();
  const fire = document.getElementById("param-fire");
  if (!fire) return;
  const immediate = ["immediate", "imm"].includes(source);
  if (immediate) fire.checked = false;
  fire.disabled = immediate;
  refreshTriggerImmediateControlTitle(command);
}

function refreshTriggerImmediateControlTitle(command) {
  if (!["trigger-step", "trigger-list"].includes(command)) return;
  const source = String(document.getElementById("param-source")?.value || "bus").toLowerCase();
  const fire = document.getElementById("param-fire");
  if (!fire) return;
  fire.title = ["immediate", "imm"].includes(source) ? t("command.tooltip.trigger_immediate_fire") : "";
}

function triggerControlGuardReason(command, parameters) {
  if (!["trigger-step", "trigger-list"].includes(command)) return "";
  const source = String(parameters.source || "bus").toLowerCase();
  const immediate = ["immediate", "imm"].includes(source);
  if (immediate && parameters.fire) {
    return t("command.guard.trigger_immediate_fire");
  }
  if (source === "bus" && parameters.wait_complete && !parameters.fire) {
    return t("command.guard.trigger_bus_wait_requires_fire");
  }
  if (command === "trigger-list") {
    if ([...(parameters.bost_list || []), ...(parameters.eost_list || [])].some(Boolean) && !(parameters.trigger_output_pins || []).length) {
      return t("command.guard.trigger_list_pulse_requires_pins");
    }
    const started = immediate || (source === "bus" && parameters.fire);
    if (!started && !parameters.leave_trigger_configured) {
      return t("command.guard.trigger_list_arm_requires_leave");
    }
    if (started && !parameters.wait_complete && !parameters.leave_trigger_configured) {
      return t("command.guard.trigger_list_started_requires_leave");
    }
  }
  return "";
}

function triggerFireWaitGuardReason(command, parameters) {
  if (command !== "trigger-fire") return "";
  if (parameters.wait_complete && parameters.channel == null) {
    return t("command.guard.trigger_fire_wait_requires_channel");
  }
  return "";
}

function setRequiresSetpointGuardReason(command, parameters) {
  if (command !== "set") return "";
  return parameters.voltage === undefined && parameters.current === undefined
    ? t("command.guard.set_requires_setpoint")
    : "";
}

function electricalRatingGuardReason(command, parameters) {
  const model = selectedElectricalRatingModel();
  const ratings = state.electricalRatingsByModel?.[model]?.channels;
  if (!Array.isArray(ratings)) return "";
  const displayModel = physicalModelDisplayName(model);
  const check = (channel, voltage, current) => {
    const selected = channel === "all"
      ? ratings
      : ratings.filter((rating) => Array.isArray(channel)
        ? channel.map(String).includes(String(rating.channel))
        : String(rating.channel) === String(channel));
    for (const rating of selected) {
      if (voltage !== undefined && voltage !== null && Number(voltage) > Number(rating.max_voltage)) return t("command.guard.electrical_voltage", { voltage, limit: rating.max_voltage, model: displayModel, channel: rating.channel });
      if (current !== undefined && current !== null && Number(current) > Number(rating.max_current)) return t("command.guard.electrical_current", { current, limit: rating.max_current, model: displayModel, channel: rating.channel });
    }
    return "";
  };
  if (["set", "apply", "smoke-output"].includes(command)) return check(parameters.channel, parameters.voltage, parameters.current);
  if (command === "ramp") return check(parameters.channels || parameters.channel, Math.max(Number(parameters.start_voltage), Number(parameters.stop_voltage)), parameters.current);
  if (command === "ramp-list") for (const segment of state.rampListSegments) { const reason = check(segment.channels, Math.max(Number(segment.start_voltage), Number(segment.stop_voltage)), segment.current); if (reason) return reason; }
  if (command === "trigger-step") return check(parameters.channel, parameters.voltage, parameters.current);
  if (command === "trigger-list") for (const voltage of parameters.voltage_list || []) for (const current of parameters.current_list || []) { const reason = check(parameters.channel, voltage, current); if (reason) return reason; }
  if (command === "sequence") for (const step of state.sequenceSteps) if (["set", "apply"].includes(step.action)) { const reason = check(step.channel ?? 1, step.voltage, step.current); if (reason) return reason; }
  if (command === "restore-from-snapshot" && state.loadedSnapshotDocument) for (const record of state.loadedSnapshotDocument.readback || []) { if (state.restoreChannel !== "all" && String(record.channel) !== String(state.restoreChannel)) continue; const reason = check(record.channel, record.setpoints?.voltage, record.setpoints?.current); if (reason) return reason; }
  return "";
}

function pulseControlsUnavailableReason() {
  const resource = valueOrNull("resource");
  const expected = selectedExpectedModel();
  const detected = detectedChannelModelForResource(resource);
  const supportedModel = physicalModelDisplayName(REAR_TRIGGER_PULSE_MODEL_ID);
  if (expected && resourceModelDetectionRecorded(resource) && detected !== expected) {
    const detectedModel = detected ? physicalModelDisplayName(detected) : t("command.guard.pulse_unknown_model");
    return t("command.guard.pulse_expected_model", {
      model: physicalModelDisplayName(expected),
      detectedModel,
      supportedModel
    });
  }
  const model = selectedChannelModel();
  if (model === REAR_TRIGGER_PULSE_MODEL_ID) return "";
  if (!model) return t("command.guard.pulse_no_model", { supportedModel });
  return t("command.guard.pulse_unsupported_model", {
    supportedModel,
    model: physicalModelDisplayName(model)
  });
}

function applyWorkflowPulseControlState(input, prerequisiteReason = "") {
  if (input.dataset) input.dataset.pulseControl = "true";
  const reason = pulseControlPresentationReason(prerequisiteReason);
  input.disabled = Boolean(reason);
  input.title = reason;
}

function refreshWorkflowPulseControlPresentation(input, prerequisiteReason = "") {
  input.title = pulseControlPresentationReason(prerequisiteReason);
}

function pulseControlPresentationReason(prerequisiteReason = "") {
  const unavailable = pulseControlsUnavailableReason();
  const unknownModel = !selectedChannelModel()
    && !(
      selectedExpectedModel()
      && resourceModelDetectionRecorded(valueOrNull("resource"))
      && detectedChannelModelForResource(valueOrNull("resource")) !== selectedExpectedModel()
  );
  return (unknownModel ? "" : unavailable) || prerequisiteReason;
}

function workflowPulseGuardReason(command, parameters) {
  return commandRequestsPulse(command, parameters) ? pulseControlsUnavailableReason() : "";
}

function commandRequestsPulse(command, parameters) {
  if (command === "cycle-output" || command === "ramp") return Boolean(parameters.completion_pulse_pins);
  if (command === "ramp-list") return Boolean(parameters.document?.completion_pulse);
  if (command === "sequence") return Boolean(parameters.document?.steps?.some((step) => step.action === "trigger-pulse"));
  return false;
}

function currentTripChannels() {
  const panel = state.livePanel;
  const resource = valueOrNull("resource");
  if (!panel || panel.stale || !resource || panel.resource !== resource) return [];
  return panel.channels
    .filter((channel) => channel.protection_tripped === true)
    .map((channel) => Number(channel.channel))
    .filter((channel) => Number.isInteger(channel));
}

function tripGuardReason(command, parameters) {
  if (!TRIP_GUARDED_COMMANDS.has(command)) return "";
  if (command === "apply" && parameters.no_output === true) return "";
  const tripped = currentTripChannels();
  if (!tripped.length) return "";
  const selected = parameters.channels || parameters.channel;
  const rampListChannels = command === "ramp-list"
    ? [...new Set((parameters.document?.segments || []).flatMap((segment) => segment.channels || [segment.channel]).map(Number))]
    : [];
  const blocked = command === "ramp-list"
    ? tripped.filter((channel) => rampListChannels.includes(channel))
    : selected === "all"
      ? tripped
      : Array.isArray(selected)
        ? tripped.filter((channel) => selected.includes(channel))
        : tripped.filter((channel) => channel === Number(selected));
  if (!blocked.length) return "";
  return t("command.guard.protection_trip", {
    channels: blocked.map((channel) => `CH${channel}`).join(", "),
    command
  });
}

function tripContextWarning(command) {
  if (!TRIP_WARNING_COMMANDS.has(command)) return "";
  const tripped = currentTripChannels();
  if (!tripped.length) return "";
  return t("command.warning.protection_trip", {
    channels: tripped.map((channel) => `CH${channel}`).join(", ")
  });
}

function formatProtectionVoltage(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : "--";
}

function formatProtectionState(value) {
  return value === true ? "ON" : value === false ? "OFF" : "--";
}

function drawTrend() {
  const canvas = document.getElementById("trend");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "#d7dee6";
  ctx.beginPath();
  ctx.moveTo(32, 12);
  ctx.lineTo(32, 160);
  ctx.lineTo(620, 160);
  ctx.stroke();
  const values = state.samples.map((sample) => normalizeMeasurements(sample)[0]?.voltage).filter((v) => Number.isFinite(v));
  if (values.length < 2) return;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 0.001);
  ctx.strokeStyle = "#1f7a8c";
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = 36 + index * (580 / Math.max(values.length - 1, 1));
    const y = 156 - ((value - min) / span) * 136;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function normalizeMeasurements(sample) {
  return webuiLiveData.normalizeMeasurements(sample);
}

function addHistory(jobId, command, status, label = command) {
  webuiJobTransport.addHistory(state, jobId, command, status, label, {
    commandDisplayName,
    statusSummary: webuiResults.statusSummary,
    statusClass: webuiResults.statusClass,
    statusLabel: webuiResults.statusLabel,
    translate: t,
    updateExecutionModeUi
  });
}

function updateHistory(jobId, status) {
  webuiJobTransport.updateHistory(state, jobId, status, {
    commandDisplayName,
    statusSummary: webuiResults.statusSummary,
    statusClass: webuiResults.statusClass,
    statusLabel: webuiResults.statusLabel,
    translate: t,
    updateExecutionModeUi
  });
}

function updateJobResult(jobId, status, summary, presentationJob = null) {
  webuiJobTransport.updateJobResult(state, jobId, status, summary, {
    commandDisplayName,
    statusSummary: webuiResults.statusSummary,
    statusClass: webuiResults.statusClass,
    statusLabel: webuiResults.statusLabel,
    jobSummary: webuiResults.jobSummary,
    translate: t,
    updateExecutionModeUi
  }, presentationJob);
}

function renderHistory() {
  webuiJobTransport.renderHistory(state, { ...webuiResults, commandDisplayName, translate: t });
}

function closeEventSource(name) {
  if (state[name]) {
    state[name].close();
    state[name] = null;
  }
}

function parseMaybeJson(text) {
  const trimmed = (text || "").trim();
  if (!trimmed) return {};
  try { return JSON.parse(trimmed); } catch { return {}; }
}

function valueOrNull(id) {
  const value = document.getElementById(id).value.trim();
  return value || null;
}

function formatNum(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : "--";
}
