import { t } from "./i18n.js";

export function liveStateText(status, timestamp, message = "", stale = false) {
  const lastUpdate = timestamp ? new Date(timestamp * 1000).toLocaleTimeString() : t("live_data.time.never");
  const knownStatus = ["ok", "busy", "error"].includes(status)
    ? t(`live_data.status.${status}`)
    : status;
  return t("live_data.status.summary", {
    status: knownStatus,
    stale: stale ? t("live_data.status.stale_suffix") : "",
    time: lastUpdate,
    detail: message ? t("live_data.status.detail_suffix", { detail: message }) : ""
  });
}

export function liveStateClass(status, stale = false) {
  if (status === "error") return "state-error";
  if (stale || status === "busy") return "state-warning";
  return "state-ok";
}

export function blankLiveChannels(channels) {
  return channels.map((channel) => ({
    channel,
    output_enabled: null,
    measured_voltage: null,
    measured_current: null,
    set_voltage: null,
    set_current: null,
    over_voltage_tripped: null,
    over_current_tripped: null,
    protection_tripped: null,
    over_voltage_protection_level: null,
    over_current_protection_enabled: null
  }));
}

export function mergeLiveChannels(channels, previousChannels, preservePreviousValues, defaultChannels) {
  const byChannel = new Map((Array.isArray(previousChannels) ? previousChannels : []).map((item) => [Number(item.channel), item]));
  const blanks = blankLiveChannels(defaultChannels);
  (Array.isArray(channels) ? channels : []).forEach((item) => {
    const existing = byChannel.get(Number(item.channel));
    byChannel.set(Number(item.channel), mergeLiveChannel(existing, item, preservePreviousValues));
  });
  return defaultChannels.map((channel, index) => byChannel.get(channel) || blanks[index]);
}

export function mergeLiveChannel(previous, incoming, preservePreviousValues) {
  if (!preservePreviousValues || !previous) return { ...previous, ...incoming };
  const next = { ...previous, ...incoming };
  [
    "output_enabled", "measured_voltage", "measured_current", "set_voltage", "set_current",
    "over_voltage_tripped", "over_current_tripped", "protection_tripped",
    "over_voltage_protection_level", "over_current_protection_enabled", "output_range"
  ].forEach((key) => {
    if (incoming[key] === null || incoming[key] === undefined) next[key] = previous[key];
  });
  return next;
}

export function normalizeMeasurements(sample) {
  const data = sample.data;
  if (data.channels) {
    return data.channels.map((item) => ({
      channel: item.channel,
      voltage: item.measured_voltage ?? item.measurements?.voltage,
      current: item.measured_current ?? item.measurements?.current
    }));
  }
  if (data.data && data.data.channels) {
    return data.data.channels.map((item) => ({ channel: item.channel, ...item.measurements }));
  }
  const entries = Object.entries(data).filter(([, value]) => value && typeof value === "object" && "voltage" in value);
  if (entries.length) return entries.map(([channel, value]) => ({ channel, ...value }));
  return [{ channel: data.channel || "all", voltage: data.voltage, current: data.current }];
}

export function renderChannelCard(channel, sample, helpers) {
  const card = document.querySelector(`[data-channel-card="${channel.channel}"]`);
  if (!card) return;
  const unsupported = helpers.channelUnsupportedReason(channel.channel);
  if (unsupported) {
    card.className = "live-card unsupported";
    card.setAttribute("aria-disabled", "true");
    card.title = unsupported;
    replaceCardContent(card, channel, {
      outputClass: "unknown",
      outputText: t("support.status.unsupported"),
      measuredVoltage: "N/A",
      measuredCurrent: "N/A",
      setVoltage: "N/A",
      setCurrent: "N/A",
      unsupported: true
    });
    return;
  }
  card.setAttribute("aria-disabled", "false");
  card.title = "";
  const outputClass = channel.output_enabled === true ? "on" : channel.output_enabled === false ? "off" : "unknown";
  const outputText = channel.output_enabled === true
    ? t("live_data.output.on")
    : channel.output_enabled === false
      ? t("live_data.output.off")
      : "--";
  const protectionClass = channel.protection_tripped === true ? "protection-tripped" : "";
  card.className = `live-card ${sample.stale ? "stale" : ""} ${sample.status === "error" ? "error" : ""} ${protectionClass}`;
  const showRange = sample.model_id === "gw-instek-psm-2010" && channel.channel === 1;
  replaceCardContent(card, channel, {
    outputClass,
    outputText: t("live_data.output.summary", { state: outputText }),
    measuredVoltage: helpers.formatNum(channel.measured_voltage),
    measuredCurrent: helpers.formatNum(channel.measured_current),
    setVoltage: helpers.formatNum(channel.set_voltage),
    setCurrent: helpers.formatNum(channel.set_current),
    overVoltageTripped: channel.over_voltage_tripped,
    overCurrentTripped: channel.over_current_tripped,
    overVoltageLevel: helpers.formatProtectionVoltage(channel.over_voltage_protection_level),
    overCurrentEnabled: helpers.formatProtectionState(channel.over_current_protection_enabled),
    showClearProtection: channel.protection_tripped === true && !sample.stale,
    showRange,
    outputRange: showRange ? channel.output_range : null
  });
  const shortcut = card.querySelector("[data-clear-protection-channel]");
  if (shortcut) shortcut.addEventListener("click", () => helpers.openClearProtection(channel.channel));
}

export function protectionBadge(label, tripped) {
  const stateClass = tripped === true ? "trip" : tripped === false ? "ok" : "unknown";
  const stateText = tripped === true
    ? t("live_data.protection.trip")
    : tripped === false
      ? t("live_data.protection.clear")
      : "--";
  const badge = element("span", `protection-badge status-indicator ${stateClass}`);
  badge.append(indicatorDot(), element("span", "indicator-text", `${label} ${stateText}`));
  return badge;
}

export function rangeBadge(outputRange) {
  const stateClass = outputRange === "LOW" || outputRange === "HIGH" ? outputRange.toLowerCase() : "unknown";
  const rangeText = outputRange === "LOW"
    ? t("live_data.range.low")
    : outputRange === "HIGH"
      ? t("live_data.range.high")
      : t("live_data.range.unknown");
  const badge = element("span", `range-badge status-indicator ${stateClass}`);
  badge.append(indicatorDot(), element("span", "indicator-text", t("live_data.range.label", { range: rangeText })));
  return badge;
}

function replaceCardContent(card, channel, presentation) {
  card.replaceChildren();
  const head = element("div", "live-card-head");
  head.append(element("strong", "", `CH${channel.channel}`));
  if (presentation.showRange) head.append(rangeBadge(presentation.outputRange));
  head.append(statusIndicator(`status-badge status-indicator output-status ${presentation.outputClass}`, presentation.outputText));
  const output = element("div", "live-output-section");
  const measured = element("div", "live-measured");
  measured.append(
    metric(presentation.measuredVoltage, t("live_data.measurement.output_voltage")),
    metric(presentation.measuredCurrent, t("live_data.measurement.output_current"))
  );
  output.appendChild(measured);
  const controls = element("div", "live-control-section");
  const setpoints = element("div", "live-setpoints");
  setpoints.append(
    metric(presentation.setVoltage, t("live_data.measurement.set_voltage")),
    metric(presentation.setCurrent, t("live_data.measurement.set_current"))
  );
  controls.appendChild(setpoints);
  const protection = element("div", "live-protection-section");
  const badges = element("div", "live-protection-badges");
  if (presentation.unsupported) {
    badges.appendChild(statusIndicator("protection-badge status-indicator unknown", t("support.status.unsupported")));
  } else {
    badges.append(
      protectionBadge("OVP", presentation.overVoltageTripped),
      protectionBadge("OCP", presentation.overCurrentTripped)
    );
    const settings = element("div", "protection-settings");
    settings.append(metric(presentation.overVoltageLevel, "OVP"), metric(presentation.overCurrentEnabled, "OCP"));
    protection.appendChild(settings);
  }
  protection.prepend(badges);
  controls.appendChild(protection);
  card.append(head, output, controls);
  if (presentation.showClearProtection) {
    const clear = element("button", "clear-protection-shortcut", t("live_data.action.clear_protection"));
    clear.type = "button";
    clear.dataset.clearProtectionChannel = String(channel.channel);
    card.appendChild(clear);
  }
}

function element(tagName, className = "", text = null) {
  const node = document.createElement(tagName);
  node.className = className;
  if (text !== null) node.textContent = String(text);
  return node;
}

function indicatorDot() {
  const dot = element("span", "indicator-dot");
  dot.setAttribute("aria-hidden", "true");
  return dot;
}

function statusIndicator(className, text) {
  const indicator = element("span", className);
  indicator.append(indicatorDot(), element("span", "indicator-text", text));
  return indicator;
}

function metric(value, label) {
  const wrapper = document.createElement("div");
  wrapper.append(element("span", "", value), element("small", "", label));
  return wrapper;
}

export function createLiveDataController({ state, isNoHardwareMode, renderBlankLivePanel, runtimePayload, fetchJson, updateLiveMonitorButton, closeEventSource, renderLivePanel, setLiveState, liveStateText, stopLivePreviewSnapshot }) {
  async function startLive() {
    if (isNoHardwareMode()) { renderBlankLivePanel("error", t("live_data.error.real_only")); return; }
    const payload = { runtime: runtimePayload(), parameters: { interval_ms: 5000 } };
    if (!payload.runtime.resource) { renderLivePanel({ status: "error", stale: true, message: t("live_data.error.resource_required") }); return; }
    try {
      stopLivePreviewSnapshot(); updateLiveMonitorButton(false, true);
      const response = await fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) });
      state.liveJobId = response.job_id; updateLiveMonitorButton(true, false); closeEventSource("liveEvents");
      state.liveEvents = new EventSource(response.events_url);
      state.liveEvents.addEventListener("progress", (event) => renderLivePanel(JSON.parse(event.data).data));
      state.liveEvents.addEventListener("finished", () => { state.liveJobId = null; updateLiveMonitorButton(false, false); setLiveState(t("live_data.status.not_monitoring"), "state-idle", t("live_data.status.monitor_stopped")); closeEventSource("liveEvents"); });
      state.liveEvents.addEventListener("failed", (event) => { const message = JSON.parse(event.data).data?.error || t("live_data.error.monitor_failed"); renderLivePanel({ status: "error", stale: true, message }); state.liveJobId = null; updateLiveMonitorButton(false, false); closeEventSource("liveEvents"); });
    } catch (error) { renderLivePanel({ status: "error", stale: true, message: error.message || String(error) }); state.liveJobId = null; updateLiveMonitorButton(false, false); }
  }
  async function toggleLiveMonitor() { if (state.liveJobId || state.liveEvents) await stopLive(); else await startLive(); }
  async function stopLive() {
    if (!state.liveJobId) return; updateLiveMonitorButton(true, true);
    try { const jobId = state.liveJobId; await fetchJson(`/api/live/${jobId}/stop`, { method: "POST" }); closeEventSource("liveEvents"); await waitForLiveTerminal(jobId); state.liveJobId = null; updateLiveMonitorButton(false, false); setLiveState(t("live_data.status.not_monitoring"), "state-idle", t("live_data.status.monitor_stopped")); }
    catch (error) { renderLivePanel({ status: "error", stale: true, message: error.message || String(error) }); updateLiveMonitorButton(true, false); }
  }
  async function startLivePreviewSnapshot(healthState, resource = null) {
    if (isNoHardwareMode()) return; stopLivePreviewSnapshot(); setLiveState(t("live_data.status.refreshing_once"), "state-warning", t("live_data.status.refreshing_after_command"));
    if (!healthState?.serverReady || !healthState?.deviceIdle) { renderBlankLivePanel("error", t("live_data.error.not_ready")); setLiveState(t("live_data.status.refresh_blocked"), "state-error", t("live_data.error.refresh_not_ready")); return; }
    const payload = { runtime: runtimePayload(), parameters: { interval_ms: 1000 } }; if (resource) payload.runtime.resource = resource;
    if (!payload.runtime.resource) { renderBlankLivePanel(); setLiveState(t("live_data.status.not_monitoring"), "state-idle", t("live_data.status.no_resource")); return; }
    try {
      const response = await fetchJson("/api/live", { method: "POST", body: JSON.stringify(payload) }); state.previewJobId = response.job_id; let handledFreshSample = false; state.previewEvents = new EventSource(response.events_url);
      state.previewEvents.addEventListener("progress", (event) => { if (handledFreshSample) return; const sample = JSON.parse(event.data).data; renderLivePanel(sample); if (!isFreshLivePreviewSample(sample)) return; handledFreshSample = true; stopLivePreviewSnapshot(); });
      state.previewEvents.addEventListener("failed", (event) => { const error = JSON.parse(event.data).data?.error || t("live_data.error.preview_failed"); renderBlankLivePanel("error", error); setLiveState(liveStateText("error", Date.now() / 1000, error), "state-error", error); stopLivePreviewSnapshot(); });
    } catch (error) { const message = error.message || String(error); renderBlankLivePanel("error", message); setLiveState(liveStateText("error", Date.now() / 1000, message), "state-error", message); }
  }
  function isFreshLivePreviewSample(sample) { return Boolean(sample && sample.stale === false && sample.status !== "busy" && sample.status !== "error" && Array.isArray(sample.channels)); }
  async function waitForLiveTerminal(jobId) { const deadline = Date.now() + 15000; while (Date.now() < deadline) { const job = await fetchJson(`/api/jobs/${jobId}`); if (["cancelled", "finished", "failed"].includes(job.status)) return job; await new Promise((resolve) => setTimeout(resolve, 100)); } throw new Error("Live Data stop timed out while waiting for the backend job to finish."); }
  return { startLive, toggleLiveMonitor, stopLive, startLivePreviewSnapshot, isFreshLivePreviewSample, waitForLiveTerminal };
}
