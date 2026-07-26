const JOB_EVENT_TYPES = [
  "accepted", "started", "progress", "cancel_requested",
  "finished", "failed", "cancelled", "error"
];

export function submitJob(fetchJson, payload) {
  return fetchJson("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
}

export function openJobEvents({ jobId, baseUrl, closeEvents, onEvent, onError, eventSourceFactory = (url) => new EventSource(url) }) {
  closeEvents();
  const events = eventSourceFactory(`${baseUrl}?job_id=${encodeURIComponent(jobId)}`);
  JOB_EVENT_TYPES.forEach((type) => {
    events.addEventListener(type, (event) => onEvent(jobId, JSON.parse(event.data)));
  });
  events.onerror = () => onError(jobId);
  return events;
}

export function createJobEventController({ state, fetchJson, closeEventSource, updateHistory, setWorkflowControl, updateJobResult, jobCommand, refreshSnapshotFormIfVisible, renderJobDetail, populateResourceSelect, captureResourceScanFailure, refreshHealth, startLivePreviewSnapshot, shouldRefreshLiveAfterCommand, captureLatestSnapshotDocument, captureWorkspaceResult, updateBasicActionFromJob, updateResourceModelFromJob, finishResourceLiveSupportEvaluation, jobLabel, captureRestorePlanPreview, renderForm, updateSelectedCommandState, reconcileWorkflowJob }) {
  function subscribeToJob(jobId, baseUrl) {
    state.events = openJobEvents({
      jobId, baseUrl, closeEvents: () => closeEventSource("events"), onEvent: handleJobEvent,
      onError: (activeJobId) => { if (state.workflowControl.jobId === activeJobId && state.workflowControl.phase !== "idle") reconcileWorkflowJob(activeJobId); }
    });
  }
  async function handleJobEvent(jobId, event) {
    updateHistory(jobId, event.type);
    if (state.workflowControl.jobId === jobId) {
      if (event.type === "cancel_requested") { setWorkflowControl("stopping", { jobId, command: state.workflowControl.command }); updateJobResult(jobId, "cancel_requested", { key: "job.summary.waiting_cleanup" }); }
      else if (["started", "progress"].includes(event.type) && state.workflowControl.phase !== "stopping") setWorkflowControl("active", { jobId, command: state.workflowControl.command });
    }
    if (typeof event.data?.message === "string" && ["accepted", "progress"].includes(event.type)) {
      updateJobResult(jobId, event.type, event.data.message);
    }
    if (jobCommand(jobId) === "snapshot" && ["accepted", "started", "progress"].includes(event.type)) refreshSnapshotFormIfVisible(jobId);
    if (!["finished", "failed", "cancelled"].includes(event.type)) return;
    closeEventSource("events");
    const job = await renderJobDetail(jobId, event);
    if (state.workflowControl.jobId === jobId && job && ["finished", "failed", "cancelled"].includes(job.status)) {
      if (job.status === "failed" && job.error_code === "cleanup_failed") updateJobResult(jobId, "failed", { key: "job.summary.cleanup_failed" });
      else if (job.status === "cancelled") updateJobResult(jobId, "cancelled", { key: "job.summary.cancelled" });
      setWorkflowControl("idle");
    }
    let healthState = null;
    if (event.type === "finished" && jobCommand(jobId) === "list-resources") await populateResourceSelect(event.data?.result?.resources || []);
    if (event.type === "failed" && jobCommand(jobId) === "list-resources") captureResourceScanFailure?.(event.data?.error || event.data?.detail || "Resource scan failed");
    else if (shouldRefreshLiveAfterCommand(event, job)) {
      healthState = await refreshHealth();
      if (shouldRefreshLiveAfterCommand(event, job)) startLivePreviewSnapshot(healthState, job.runtime.resource);
    }
    if (event.type === "finished" && job) { captureLatestSnapshotDocument(job); captureWorkspaceResult(job); }
    if (jobCommand(jobId) === "snapshot") refreshSnapshotFormIfVisible(jobId);
    if (state.basicJobActions[jobId]) updateBasicActionFromJob(jobId, event, job);
    if (event.type === "finished") updateResourceModelFromJob(job);
    await finishResourceLiveSupportEvaluation?.(jobId);
    if (jobLabel(jobId) === "Restore plan preview") { captureRestorePlanPreview(job); if (state.selected === "restore-from-snapshot") { renderForm("restore-from-snapshot"); updateSelectedCommandState(); } }
    if (!healthState) refreshHealth();
  }
  return { subscribeToJob, handleJobEvent };
}

export function addHistory(state, jobId, command, status, label, helpers) {
  state.jobs.unshift({
    jobId,
    command,
    label,
    status,
    summary: null
  });
  state.jobs = state.jobs.slice(0, 20);
  renderHistory(state, helpers);
  helpers.updateExecutionModeUi();
}

export function updateHistory(state, jobId, status, helpers) {
  const job = state.jobs.find((item) => item.jobId === jobId);
  if (job) {
    job.status = status;
    job.summary = null;
  }
  renderHistory(state, helpers);
  helpers.updateExecutionModeUi();
}

export function updateJobResult(state, jobId, status, summary, helpers, presentationJob = null) {
  const job = state.jobs.find((item) => item.jobId === jobId);
  if (!job) return;
  job.status = status;
  job.summary = summary || null;
  if (presentationJob) job.presentationJob = presentationJob;
  renderHistory(state, helpers);
  helpers.updateExecutionModeUi();
}

export function renderHistory(state, helpers) {
  const history = document.getElementById("job-history");
  history.innerHTML = "";
  state.jobs.forEach((job) => {
    const item = document.createElement("div");
    item.className = "history-item";
    const label = document.createElement("strong");
    label.textContent = helpers.commandDisplayName(job.command);
    const badge = document.createElement("span");
    badge.className = `result-status ${helpers.statusClass(job.status)}`;
    badge.textContent = helpers.statusLabel(job.status);
    const summary = document.createElement("span");
    summary.className = "result-summary";
    summary.textContent = job.presentationJob && helpers.jobSummary
      ? helpers.jobSummary(job.presentationJob)
      : semanticSummaryText(job.summary, helpers) || helpers.statusSummary(job.status);
    item.append(label, " - ", badge, " - ", summary);
    history.appendChild(item);
  });
}

function semanticSummaryText(summary, helpers) {
  if (!summary || typeof summary === "string") return summary || "";
  if (typeof summary.key === "string" && helpers.translate) {
    return helpers.translate(summary.key, summary.params || {}, summary.rawFallback);
  }
  return summary.rawFallback || "";
}
