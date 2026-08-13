import { t } from "./i18n.js";

export function physicalModelDisplayName(physicalModels, modelId, translate = t) {
  const canonicalModelId = String(modelId || "").trim();
  if (!canonicalModelId) return translate("device.model.unknown");
  const metadata = physicalModels.find((model) => model?.model_id === canonicalModelId);
  return metadata?.display_name || metadata?.model_name || canonicalModelId;
}

export function planningIdentitySummary({ executionMode, planningProfiles, physicalModels }, identity, translate = t) {
  if (!identity) return translate(executionMode === "simulate" ? "device.planning_model.none" : "device.planning_target.none");
  if (identity.startsWith("profile:")) {
    const profileId = identity.slice("profile:".length);
    const profile = planningProfiles?.[profileId];
    return translate("device.planning_profile.value", { profile: profile?.display_name || profile?.model_name || profileId });
  }
  return translate("device.planning_model.value", { model: physicalModelDisplayName(physicalModels, identity, translate) });
}

export function liveResourceSummary(resourceDisplayModels, resource, scanState, translate = t) {
  const detected = resourceDisplayModels[resource] || null;
  if (detected) return translate("resource.status.live_model", { model: detected });
  if (scanState?.status === "failed") return translate("resource.status.failed", undefined, scanState.detail);
  if (scanState?.status === "results") {
    return scanState.resources.includes(resource)
      ? translate("resource.status.live_selected")
      : translate("resource.status.results", { count: scanState.resources.length });
  }
  if (scanState?.status === "empty") return translate("resource.status.empty");
  return translate("resource.status.not_scanned");
}

export function resourceLabel(resource, name) {
  if (!resource || typeof resource === "string") return name;
  return [name, resource.idn?.manufacturer, resource.idn?.model].filter(Boolean).join(" - ");
}

const STATE_CLASS_NAMES = ["state-ok", "state-warning", "state-error", "state-idle"];
const E3646A_MODEL_ID = "keysight-e3646a";


export function createDeviceResourceController({
  state,
  devicePresentation,
  executionContext,
  fetchJson,
  clearStaleResourceLiveSupport,
  syncBasicFromLivePanel,
  selectCommand,
  renderCommands,
  valueOrNull,
  exactSupportContextSummary,
  currentExactLiveSupport,
  channelCapabilityForModel,
  currentResourceModel,
  refreshBasicInputConstraints,
  refreshElectricalRatingConstraints,
  renderWorkspaceSummary,
  updateSelectedCommandState,
  closeEventSource,
  renderClientResult,
  renderBlankLivePanel
}) {
function setDeviceOptionsExpanded(expanded) {
  const panel = document.getElementById("device-options-panel");
  const button = document.getElementById("device-options-toggle");
  panel.hidden = !expanded;
  button.setAttribute("aria-expanded", String(expanded));
}

function setSupportedDevicesExpanded(expanded) {
  const panel = document.getElementById("supported-devices-panel");
  const button = document.getElementById("supported-devices-toggle");
  if (!panel || !button) {
    return;
  }
  panel.hidden = !expanded;
  button.setAttribute("aria-expanded", String(expanded));
}

function supportedDeviceConnectionLabel(connection) {
  if (connection === "tcpip") {
    return t("supported_devices.connection.tcpip");
  }
  if (connection === "asrl") {
    return t("supported_devices.connection.asrl");
  }
  return t("supported_devices.connection.usb");
}

function renderSupportedDevices() {
  const body = document.getElementById("supported-devices-body");
  if (!body) {
    return;
  }
  const devices = Array.isArray(state.supportedDevices) ? state.supportedDevices : [];
  body.replaceChildren(
    ...devices.map((device) => {
      const row = document.createElement("tr");
      for (const value of [
        device.vendor,
        device.model,
        (device.connections || [])
          .map(supportedDeviceConnectionLabel)
          .join(t("supported_devices.connection_separator")),
      ]) {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.appendChild(cell);
      }
      return row;
    })
  );
}

function setDeviceResourceExpanded(expanded) {
  const section = document.querySelector(".device-resource-section");
  const body = document.getElementById("device-resource-body");
  const button = document.getElementById("toggle-device-resource");
  body.hidden = !expanded;
  section.classList.toggle("collapsed", !expanded);
  button.textContent = expanded ? "-" : "+";
  button.setAttribute("aria-expanded", String(expanded));
  refreshDeviceResourceExpandedPresentation();
}

function refreshDeviceResourceExpandedPresentation() {
  const button = document.getElementById("toggle-device-resource");
  if (!button) return;
  const expanded = button.getAttribute("aria-expanded") === "true";
  const text = t(expanded
    ? "accessibility.collapse_device_resource"
    : "accessibility.expand_device_resource");
  button.setAttribute("aria-label", text);
  button.title = text;
}

function updateDeviceResourceSummary() {
  const resource = document.getElementById("resource").value.trim();
  const clearedExactSupport = clearStaleResourceLiveSupport(resource);
  refreshDeviceResourceSummaryPresentation();
  if (clearedExactSupport) {
    syncBasicFromLivePanel(state.livePanel);
    if (state.selected) selectCommand(state.selected);
    else renderCommands();
  }
}

function refreshDeviceResourceSummaryPresentation() {
  const summary = document.getElementById("device-resource-summary");
  const resource = document.getElementById("resource").value.trim();
  const select = document.getElementById("resource-select");
  const presentation = buildDeviceResourceSummary(resource, select);
  summary.textContent = presentation.text;
  summary.title = presentation.title;
  const detected = detectedCommandModelForResource(resource);
  const expected = selectedExpectedModel();
  if (expected && resourceModelDetectionRecorded(resource) && detected !== expected) {
    summary.title = t("device.expected_mismatch");
  }
}

function buildDeviceResourceSummary(resource, select) {
  if (isNoHardwareMode()) {
    const mode = t(state.executionMode === "simulate" ? "execution_mode.summary.simulate" : "execution_mode.summary.dry_run");
    const planning = planningIdentitySummary(selectedPlanningIdentity());
    const realContext = resource
      ? t("resource.real.preserved", { resource })
      : t("resource.real.not_used");
    const text = [mode, planning, realContext].join(" / ");
    return { text, title: text };
  }

  const canonicalModel = actualCurrentResourceModel();
  const reportedModel = detectedResourceDisplayModel(resource);
  const detection = canonicalModel
    ? t("device.detected_model", { model: physicalModelDisplayName(canonicalModel) })
    : reportedModel
      ? t("device.reported_model", { model: reportedModel })
      : t("device.detection_status", { status: liveResourceSummary(resource, select) });
  const text = [
    t("execution_mode.summary.real"),
    t("resource.visa_summary", { resource: resource || t("common.not_selected") }),
    detection,
    t("device.expected_guard", { guard: expectedModelSummary() }),
    exactSupportContextSummary(resource)
  ].join(" / ");
  return { text, title: text };
}

function planningIdentitySummary(identity) {
  return devicePresentation.planningIdentitySummary(state, identity);
}

function liveResourceSummary(resource, select) {
  return devicePresentation.liveResourceSummary(state.resourceDisplayModels, resource, state.resourceScan, t);
}

function expectedModelSummary() {
  const expected = selectedExpectedModel();
  return expected
    ? t("device.expected.require", { model: physicalModelDisplayName(expected) })
    : t("device.expected.auto_detect");
}

function selectedExpectedModel() {
  return state.executionMode === "real" ? valueOrNull("expected-model-id") : null;
}

function selectedPlanningIdentity() {
  return state.executionMode === "real" ? null : valueOrNull("expected-model-id");
}

function rememberCurrentExecutionIdentity() {
  const identity = valueOrNull("expected-model-id") || "";
  if (state.executionMode === "real") {
    state.realIdentityCache.expectedModelId = identity;
  } else if (Object.prototype.hasOwnProperty.call(state.planningIdentityCache, state.executionMode)) {
    state.planningIdentityCache[state.executionMode] = identity;
  }
}

function isNoHardwareMode() {
  return executionContext.isNoHardwareExecutionMode(state.executionMode);
}

function realAuthorizationContext() {
  return JSON.stringify({
    resource: valueOrNull("resource"),
    expected_model_id: state.realIdentityCache.expectedModelId || valueOrNull("expected-model-id"),
    connected_model_id: detectedCommandModelForResource(valueOrNull("resource"))
  });
}

function clearRealWriteAuthorization() {
  state.realWriteAuthorization = null;
  const checkbox = document.getElementById("real-write-enabled");
  if (checkbox) checkbox.checked = false;
}

function resetRealWriteAuthorization() {
  const resource = valueOrNull("resource");
  if (state.executionMode !== "real" || !resource) {
    clearRealWriteAuthorization();
    return false;
  }
  state.realWriteAuthorization = realAuthorizationContext();
  const checkbox = document.getElementById("real-write-enabled");
  if (checkbox) checkbox.checked = true;
  return true;
}

function hasRealWriteAuthorization() {
  return state.executionMode === "real" && state.realWriteAuthorization === realAuthorizationContext();
}

function updateExecutionModeUi({
  renderCommands: shouldRenderCommands = true,
  resetAuthorization = false
} = {}) {
  const noHardware = isNoHardwareMode();
  const jobBusy = executionModeBusy();
  document.querySelectorAll('input[name="execution-mode"]').forEach((radio) => {
    radio.disabled = jobBusy;
  });
  refreshExecutionModeBusyPresentation();
  const badge = document.getElementById("execution-mode-badge");
  const checkbox = document.getElementById("real-write-enabled");
  const resourceControls = ["resource", "resource-select", "scan", "live-start", "serial-baud-rate", "serial-data-bits", "serial-parity", "serial-stop-bits", "serial-flow-control", "serial-read-termination", "serial-write-termination", "serial-remote", "serial-local-on-close"];
  resourceControls.forEach((id) => {
    const control = document.getElementById(id);
    if (!control) return;
    control.disabled = noHardware;
    control.classList.toggle("no-hardware-control", noHardware);
  });
  populateIdentitySelector();
  if (resetAuthorization) resetRealWriteAuthorization();
  if (checkbox) {
    checkbox.disabled = noHardware || !valueOrNull("resource");
    checkbox.checked = hasRealWriteAuthorization();
    checkbox.parentElement.hidden = noHardware;
  }
  refreshExecutionModePresentation();
  if (badge) {
    badge.className = "execution-mode-badge";
    if (state.executionMode === "simulate") badge.classList.add("simulate");
    else if (state.executionMode === "dry-run") badge.classList.add("dry-run");
    else if (hasRealWriteAuthorization()) badge.classList.add("real-enabled");
    else badge.classList.add("real-locked");
  }
  updateDeviceResourceSummary();
  if (shouldRenderCommands) renderCommands();
  syncBasicFromLivePanel(state.livePanel);
}

function executionModeBusy() {
  return state.executionModeTransition
    || state.workflowControl.phase !== "idle"
    || Object.values(state.basicActionStates).some((action) => ["pending", "submitting", "active", "stopping"].includes(action.status))
    || state.jobs.some((job) => ["accepted", "started", "progress", "running", "cancel_requested"].includes(job.status));
}

function refreshExecutionModeBusyPresentation() {
  const title = executionModeBusy() ? t("execution_mode.busy_title") : "";
  document.querySelectorAll('input[name="execution-mode"]').forEach((radio) => {
    radio.title = title;
  });
}

function refreshExecutionModePresentation() {
  const noHardware = isNoHardwareMode();
  const badge = document.getElementById("execution-mode-badge");
  const help = document.getElementById("execution-mode-help");
  const label = document.getElementById("identity-model-label");
  if (label?.firstChild) label.firstChild.textContent = t(noHardware
    ? (state.executionMode === "simulate" ? "device.identity.simulation_model" : "device.identity.planning_target")
    : "device.identity.expected_model");
  if (help) help.textContent = t(noHardware
    ? (state.executionMode === "simulate" ? "execution_mode.help.simulate" : "execution_mode.help.dry_run")
    : "execution_mode.help.real");
  if (badge) badge.textContent = t(state.executionMode === "simulate"
    ? "execution_mode.badge.simulate"
    : state.executionMode === "dry-run"
      ? "execution_mode.badge.dry_run"
      : hasRealWriteAuthorization() ? "execution_mode.badge.real_enabled" : "execution_mode.badge.real_locked");
  refreshExecutionModeBusyPresentation();
}

function populateIdentitySelector() {
  const select = document.getElementById("expected-model-id");
  if (!select || !state.physicalModels.length) return;
  select.replaceChildren();
  if (state.executionMode === "real") {
    select.add(new Option(t("device.expected.auto_detect"), ""));
    state.physicalModels.forEach((model) => select.add(new Option(model.display_name || model.model_name, model.model_id)));
    const expected = state.realIdentityCache.expectedModelId;
    select.value = state.physicalModels.some((model) => model.model_id === expected) ? expected : "";
  } else if (state.executionMode === "simulate") {
    select.add(new Option(t("device.identity.select_simulation_model"), ""));
    state.physicalModels.forEach((model) => select.add(new Option(model.display_name || model.model_name, model.model_id)));
    const planned = state.planningIdentityCache.simulate;
    select.value = state.physicalModels.some((model) => model.model_id === planned) ? planned : "";
  } else {
    select.add(new Option(t("device.identity.select_planning_target"), ""));
    const physical = document.createElement("optgroup"); physical.label = t("device.identity.physical_models");
    state.physicalModels.forEach((model) => physical.append(new Option(model.display_name || model.model_name, model.model_id)));
    select.append(physical);
    const profiles = document.createElement("optgroup"); profiles.label = t("device.identity.planning_profiles");
    Object.values(state.planningProfiles || {}).forEach((profile) => {
      const profileId = profile.profile_id || profile.planning_profile_id;
      if (profileId) profiles.append(new Option(profile.display_name || profile.model_name || profileId, `profile:${profileId}`));
    });
    select.append(profiles);
    const planned = state.planningIdentityCache["dry-run"];
    const physicalMatch = state.physicalModels.some((model) => model.model_id === planned);
    const profileMatch = planned.startsWith("profile:") && Boolean(state.planningProfiles?.[planned.slice("profile:".length)]);
    select.value = physicalMatch || profileMatch ? planned : "";
  }
}

async function handleExecutionModeChange(event) {
  const requested = event.target.value;
  if (requested === state.executionMode || state.executionModeTransition) return;
  let modeChanged = false;
  event.target.checked = false;
  document.querySelector(`input[name="execution-mode"][value="${state.executionMode}"]`).checked = true;
  state.executionModeTransition = true;
  document.querySelectorAll('input[name="execution-mode"]').forEach((radio) => radio.disabled = true);
  try {
    await stopRealLiveJobsAndWait();
    rememberCurrentExecutionIdentity();
    state.executionMode = requested;
    modeChanged = true;
    document.querySelector(`input[name="execution-mode"][value="${requested}"]`).checked = true;
    renderBlankLivePanel("ok", "Execution mode changed.");
  } catch (error) {
    renderClientResult("Execution mode", "failed", error.message || String(error), { error: "Mode change cancelled" });
  } finally {
    state.executionModeTransition = false;
    updateExecutionModeUi({
      renderCommands: !modeChanged || !state.selected,
      resetAuthorization: modeChanged
    });
    if (modeChanged) {
      if (state.selected) selectCommand(state.selected);
      else renderWorkspaceSummary();
    }
  }
}

async function stopRealLiveJobsAndWait() {
  const jobs = [["liveJobId", "liveEvents"], ["previewJobId", "previewEvents"]];
  for (const [idKey, eventKey] of jobs) {
    const jobId = state[idKey];
    closeEventSource(eventKey);
    if (!jobId) continue;
    await fetchJson(`/api/live/${jobId}/stop`, { method: "POST" });
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      const job = await fetchJson(`/api/jobs/${jobId}`);
      if (["cancelled", "finished", "failed"].includes(job.status)) { state[idKey] = null; break; }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (state[idKey] === jobId) throw new Error("Live Data did not reach a terminal state within 15 seconds; remaining in Real mode.");
  }
}

function selectedExpectedModelLabel() {
  const expected = selectedExpectedModel();
  return expected ? `Require ${physicalModelDisplayName(expected)}` : "Auto-detect";
}

function physicalModelDisplayName(modelId) {
  return devicePresentation.physicalModelDisplayName(state.physicalModels, modelId);
}

function detectedResourceDisplayModel(resource) {
  if (!resource) return null;
  return state.resourceDisplayModels[resource] || null;
}

function resourceModelDetectionRecorded(resource) {
  return Boolean(resource) && Object.prototype.hasOwnProperty.call(state.resourceChannelModels, resource);
}

function detectedCommandModelForResource(resource) {
  if (!resource) return null;
  return state.resourceModels[resource] || null;
}

function detectedChannelModelForResource(resource) {
  if (!resource) return null;
  return state.resourceChannelModels[resource] || null;
}

function selectedCommandModel() {
  if (isNoHardwareMode()) {
    const identity = selectedPlanningIdentity();
    return identity?.startsWith("profile:") ? null : identity;
  }
  const expected = selectedExpectedModel();
  if (expected && state.commandSupportByModel?.[expected]) return expected;
  return detectedCommandModelForResource(valueOrNull("resource"));
}

function selectedChannelModel() {
  if (isNoHardwareMode()) {
    const identity = selectedPlanningIdentity();
    return identity?.startsWith("profile:") ? null : identity;
  }
  const expected = selectedExpectedModel();
  if (expected && state.channelCapabilitiesByModel?.[expected]) return expected;
  return detectedChannelModelForResource(valueOrNull("resource"));
}

function actualCurrentResourceModel() {
  const resource = valueOrNull("resource");
  if (!resource) return null;
  const livePanel = state.livePanel;
  if (livePanel && !livePanel.stale && livePanel.resource === resource && livePanel.model_id) {
    return String(livePanel.model_id).trim() || null;
  }
  const detected = detectedCommandModelForResource(resource) || detectedChannelModelForResource(resource);
  if (detected) return detected;
  const liveSupport = currentExactLiveSupport();
  return liveSupport?.model_id ? String(liveSupport.model_id).trim() || null : null;
}

function e3646aGlobalOutputCapability() {
  const capability = channelCapabilityForModel(E3646A_MODEL_ID);
  if (!capability || capability.output_control_scope !== "global") return null;
  if (capability.channels.length !== 2 || capability.channels[0] !== 1 || capability.channels[1] !== 2) return null;
  return capability;
}

function basicOutputPresentation() {
  const model = isNoHardwareMode() ? selectedPlanningIdentity() : actualCurrentResourceModel();
  if (model !== E3646A_MODEL_ID) {
    return { mode: "ordinary", capability: null };
  }
  const capability = e3646aGlobalOutputCapability();
  return capability
    ? { mode: "e3646a-global", capability }
    : { mode: "e3646a-disabled", capability: null };
}

function selectedElectricalRatingModel() {
  if (isNoHardwareMode()) {
    const identity = selectedPlanningIdentity();
    if (!identity || identity.startsWith("profile:")) return null;
    return state.electricalRatingsByModel?.[identity] ? identity : null;
  }
  const expected = selectedExpectedModel();
  if (expected && state.electricalRatingsByModel?.[expected]) return expected;
  return currentResourceModel();
}

function handleExpectedModelChanged() {
  rememberCurrentExecutionIdentity();
  updateExecutionModeUi({ renderCommands: false, resetAuthorization: state.executionMode === "real" });
  refreshBasicInputConstraints();
  refreshElectricalRatingConstraints();
  if (state.selected) {
    selectCommand(state.selected);
  } else {
    renderCommands();
  }
  renderWorkspaceSummary();
  updateSelectedCommandState();
}

function updateLiveMonitorButton(monitoring, disabled = false) {
  const button = document.getElementById("live-start");
  if (!button) return;
  button.disabled = disabled;
  button.textContent = t(monitoring ? "live_data.action.stop_monitor" : "live_data.action.start_monitor");
  button.setAttribute("aria-pressed", String(monitoring));
  button.classList.toggle("on", monitoring);
  button.classList.toggle("off", !monitoring);
}

async function refreshHealth() {
  try {
    const health = await fetchJson("/api/health");
    state.health = {
      status: "loaded",
      readiness: health.status,
      hardwareLocked: Boolean(health.hardware_locked),
      activeJob: health.active_job || null,
      detail: ""
    };
    const serverReady = health.status === "ok";
    const deviceIdle = serverReady && !health.hardware_locked;
    refreshHealthPresentation();
    return { serverReady, deviceIdle };
  } catch (error) {
    state.health = {
      status: "failed",
      readiness: null,
      hardwareLocked: null,
      activeJob: null,
      detail: error.message || String(error)
    };
    refreshHealthPresentation();
    renderBlankLivePanel("error", error.message || String(error));
    return { serverReady: false, deviceIdle: false, error };
  }
}

function refreshLiveMonitorPresentation() {
  const button = document.getElementById("live-start");
  if (!button) return;
  updateLiveMonitorButton(Boolean(state.liveJobId || state.liveEvents), button.disabled);
}

function refreshHealthPresentation() {
  const health = state.health;
  const notLoaded = !health || health.status === "not_loaded";
  const failed = health?.status === "failed";
  const ready = health?.status === "loaded" && health.readiness === "ok";
  const idle = ready && !health.hardwareLocked;
  setStateIndicator(
    "server-state",
    t(notLoaded ? "health.status.checking" : ready ? "health.status.ready" : "health.status.error"),
    notLoaded ? "state-warning" : ready ? "state-ok" : "state-error",
    notLoaded
      ? t("health.server.checking")
      : failed
      ? health.detail
      : ready
        ? t("health.server.reachable")
        : t("health.server.status", { status: health?.readiness || t("health.status.unknown") })
  );
  setStateIndicator(
    "device-state",
    t(ready ? (idle ? "health.status.ready" : "health.status.busy") : "health.status.unknown"),
    ready ? (idle ? "state-ok" : "state-warning") : "state-idle",
    idle
      ? t("health.device.idle")
      : ready
        ? t("health.device.busy", { job: health.activeJob || t("health.status.unknown") })
        : t(failed ? "health.device.unreachable" : "health.device.unavailable")
  );
}

function refreshDeviceResourcePresentation() {
  refreshExecutionModePresentation();
  refreshDeviceResourceExpandedPresentation();
  refreshDeviceResourceSummaryPresentation();
  renderSupportedDevices();
  refreshHealthPresentation();
  const select = document.getElementById("resource-select");
  if (select?.options?.length === 1 && !select.options[0].value) {
    select.options[0].textContent = t(state.resourceScan?.status === "empty"
      ? "resource.scan.empty"
      : state.resourceScan?.status === "failed"
        ? "resource.scan.failed"
        : "resource.scan.waiting");
  }
  const identity = document.getElementById("expected-model-id");
  if (identity?.options?.length) {
    identity.options[0].textContent = t(state.executionMode === "real"
      ? "device.expected.auto_detect"
      : state.executionMode === "simulate"
        ? "device.identity.select_simulation_model"
        : "device.identity.select_planning_target");
    for (const group of identity.querySelectorAll?.("optgroup") || []) {
      group.label = t(group === identity.querySelector("optgroup")
        ? "device.identity.physical_models"
        : "device.identity.planning_profiles");
    }
  }
}

function setStateIndicator(elementId, text, stateClass = "state-idle", title = "") {
  const indicator = document.getElementById(elementId);
  if (!indicator) return;
  indicator.classList.add("state-indicator");
  STATE_CLASS_NAMES.forEach((className) => indicator.classList.toggle(className, className === stateClass));
  let dot = indicator.querySelector(".state-dot");
  let textNode = indicator.querySelector(".state-text");
  if (!dot || !textNode) {
    indicator.textContent = "";
    dot = document.createElement("span");
    dot.className = "state-dot";
    dot.setAttribute("aria-hidden", "true");
    textNode = document.createElement("span");
    textNode.className = "state-text";
    indicator.append(dot, textNode);
  }
  textNode.textContent = text;
  indicator.title = title || text;
}


  return {
    setDeviceOptionsExpanded,
    setSupportedDevicesExpanded,
    renderSupportedDevices,
    setDeviceResourceExpanded,
    refreshDeviceResourceExpandedPresentation,
    updateDeviceResourceSummary,
    refreshDeviceResourceSummaryPresentation,
    buildDeviceResourceSummary,
    planningIdentitySummary,
    liveResourceSummary,
    expectedModelSummary,
    selectedExpectedModel,
    selectedPlanningIdentity,
    rememberCurrentExecutionIdentity,
    isNoHardwareMode,
    realAuthorizationContext,
    clearRealWriteAuthorization,
    resetRealWriteAuthorization,
    hasRealWriteAuthorization,
    updateExecutionModeUi,
    refreshExecutionModePresentation,
    refreshExecutionModeBusyPresentation,
    refreshDeviceResourcePresentation,
    populateIdentitySelector,
    handleExecutionModeChange,
    stopRealLiveJobsAndWait,
    selectedExpectedModelLabel,
    physicalModelDisplayName,
    detectedResourceDisplayModel,
    resourceModelDetectionRecorded,
    detectedCommandModelForResource,
    detectedChannelModelForResource,
    selectedCommandModel,
    selectedChannelModel,
    actualCurrentResourceModel,
    e3646aGlobalOutputCapability,
    basicOutputPresentation,
    selectedElectricalRatingModel,
    handleExpectedModelChanged,
    updateLiveMonitorButton,
    refreshLiveMonitorPresentation,
    refreshHealth,
    refreshHealthPresentation,
    setStateIndicator
  };
}
