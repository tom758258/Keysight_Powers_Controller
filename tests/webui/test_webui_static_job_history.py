"""Static and direct behavior checks for WebUI Job History presentation."""

from __future__ import annotations

from _webui_shared import (
    read_static_javascript,
    read_static_texts,
    run_frontend_javascript_assertions,
    run_webui_module_assertions,
)


def test_frontend_job_history_module_preserves_bounded_status_history() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    history_js = read_static_javascript("jobs.js")

    assert 'from "./jobs.js"' in app_js
    assert "export function addHistory" in history_js
    assert "export function openJobEvents" in history_js

    run_webui_module_assertions(
        r"""
const history = globalThis.webuiJobTransport;
const state = { jobs: [] };
const calls = [];
const historyNode = { innerHTML: "", appendChild: () => {} };
globalThis.document = {
  getElementById: () => historyNode,
  createElement: () => ({ append: () => {} })
};
const helpers = {
  commandDisplayName: (value) => `Label ${value}`,
  statusSummary: (value) => `Summary ${value}`,
  statusLabel: (value) => `Status ${value}`,
  statusClass: (value) => `Class ${value}`,
  translate: (key) => `Translated ${key}`,
  updateExecutionModeUi: () => calls.push("mode")
};
history.addHistory(state, "job-1", "set", "accepted", "Set", helpers);
strictAssert.deepEqual(state.jobs, [{ jobId: "job-1", command: "set", label: "Set", status: "accepted", summary: null }]);
history.updateHistory(state, "job-1", "started", helpers);
strictAssert.equal(state.jobs[0].status, "started");
history.updateJobResult(state, "job-1", "finished", "Done", helpers);
strictAssert.equal(state.jobs[0].summary, "Done");
const rawPresentationJob = { status: "finished", command: "set", result: { marker: "raw" } };
history.updateJobResult(state, "job-1", "finished", { key: "job.summary.finished" }, helpers, rawPresentationJob);
history.updateJobResult(state, "job-1", "finished", { key: "job.summary.finished" }, helpers);
strictAssert.equal(state.jobs[0].presentationJob, rawPresentationJob);
for (let index = 2; index <= 21; index += 1) {
  history.addHistory(state, `job-${index}`, "set", "accepted", "Set", helpers);
}
strictAssert.equal(state.jobs.length, 20);
strictAssert.equal(state.jobs[0].jobId, "job-21");
strictAssert.equal(state.jobs.at(-1).jobId, "job-2");
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("jobs.js",),
    )


def test_app_job_history_adapters_supply_complete_render_dependencies() -> None:
    run_frontend_javascript_assertions(
        r"""
const strictAssert = require("node:assert/strict");
const elements = new Map();
const historyNode = {
  _innerHTML: "",
  children: [],
  get innerHTML() { return this._innerHTML; },
  set innerHTML(value) { this._innerHTML = value; this.children = []; },
  appendChild(child) { this.children.push(child); }
};
const resultNode = { textContent: "" };
elements.set("job-history", historyNode);
elements.set("result", resultNode);
document.getElementById = (id) => elements.get(id) || { value: "" };
document.createElement = (tagName) => ({
  tagName: tagName.toUpperCase(),
  className: "",
  textContent: "",
  children: [],
  append(...children) { this.children.push(...children); }
});
const latestHistoryItem = () => historyNode.children.find(
  (node) => node.className.split(/\s+/).includes("history-item")
);
const historyPartByClass = (className) => latestHistoryItem().children.find(
  (node) => node?.className?.split(/\s+/).includes(className)
);
const historyCommand = () => latestHistoryItem().children.find(
  (node) => node?.tagName === "STRONG"
);
const historyStatus = () => historyPartByClass("result-status");
const historySummary = () => historyPartByClass("result-summary");

isNoHardwareMode = () => false;
runtimePayload = () => ({ simulate: false, dry_run: false });
updateExecutionModeUi = () => {};
let subscribedJobId = null;
subscribeToJob = (jobId) => { subscribedJobId = jobId; };
webuiApi.fetchJson = async () => ({ job_id: "scan-job" });

(async () => {
  await scanResources();
  strictAssert.equal(subscribedJobId, "scan-job");
  strictAssert.equal(state.jobs[0].label, "Scan Device");
  strictAssert.equal(state.jobs[0].status, "accepted");
  strictAssert.match(historyStatus().className, /running/);

  updateHistory("scan-job", "started");
  strictAssert.equal(state.jobs[0].status, "started");
  strictAssert.equal(historyStatus().textContent, "Started");

  updateJobResult("scan-job", "finished", "Scan complete");
  strictAssert.equal(state.jobs[0].summary, "Scan complete");
  strictAssert.equal(historyStatus().textContent, "Success");

  addHistory("locale-job", "set", "accepted", "set");
  const rawLocaleJob = state.jobs[0];
  updateJobResult("locale-job", "cancel_requested", { key: "job.summary.waiting_cleanup" });
  setLocale("zh-TW");
  renderHistory();
  strictAssert.equal(state.jobs[0], rawLocaleJob);
  strictAssert.equal(state.jobs[0].command, "set");
  strictAssert.equal(state.jobs[0].status, "cancel_requested");
  strictAssert.equal(historyCommand().textContent, "設定");
  strictAssert.equal(historyStatus().textContent, "已要求取消");
  strictAssert.equal(historySummary().textContent, "正在等待安全關閉輸出與清理");
  setLocale("en");
  renderHistory();
  strictAssert.equal(historySummary().textContent, "Waiting for safe-off and cleanup");
  updateJobResult("locale-job", "failed", "VISA <raw> detail");
  setLocale("zh-TW");
  renderHistory();
  strictAssert.equal(historySummary().textContent, "VISA <raw> detail");
  setLocale("en");
  renderHistory();
  strictAssert.equal(historyCommand().textContent, "Set");

  const unknownCodeJob = {
    status: "failed",
    command: "set",
    error_code: "driver_timeout",
    error: null
  };
  updateJobResult("locale-job", "failed", { key: "job.summary.failed" }, unknownCodeJob);
  renderHistory();
  strictAssert.equal(historySummary().textContent, "Command failed - driver_timeout");
  setLocale("zh-TW");
  renderHistory();
  strictAssert.equal(historySummary().textContent, "指令失敗 - driver_timeout");
  unknownCodeJob.error = "VISA <raw> detail";
  renderHistory();
  strictAssert.equal(historySummary().textContent, "VISA <raw> detail");
  strictAssert.equal(webuiResults.jobSummary({ status: "failed" }), "指令失敗");
  setLocale("en");
  const cleanupFailedJob = {
    status: "failed",
    command: "ramp",
    error_code: "cleanup_failed",
    error: "Cancellation arrived after the VISA session had closed"
  };
  const cleanupFailedIdentity = cleanupFailedJob;
  updateJobResult("locale-job", "failed", { key: "job.summary.cleanup_failed" }, cleanupFailedJob);
  renderHistory();
  strictAssert.equal(historySummary().textContent, "Failed  cleanup_failed");
  strictAssert.equal(webuiResults.jobSummary(cleanupFailedJob), "Failed  cleanup_failed");
  strictAssert.equal(webuiResults.eventSummary({
    type: "failed",
    data: {
      code: "cleanup_failed",
      error: "Cancellation arrived after the VISA session had closed"
    }
  }), "Failed  cleanup_failed");
  strictAssert.equal(cleanupFailedJob, cleanupFailedIdentity);
  strictAssert.equal(cleanupFailedJob.error, "Cancellation arrived after the VISA session had closed");
  strictAssert.equal(cleanupFailedJob.error_code, "cleanup_failed");
  strictAssert.equal(state.jobs[0].presentationJob, cleanupFailedJob);
  setLocale("zh-TW");
  renderHistory();
  strictAssert.equal(historySummary().textContent, "失敗 - cleanup_failed");
  strictAssert.equal(webuiResults.jobSummary(cleanupFailedJob), "失敗 - cleanup_failed");
  strictAssert.equal(cleanupFailedJob.error, "Cancellation arrived after the VISA session had closed");
  strictAssert.equal(cleanupFailedJob.error_code, "cleanup_failed");
  setLocale("en");
  renderHistory();
  strictAssert.equal(historySummary().textContent, "Failed  cleanup_failed");
  strictAssert.equal(state.jobs[0].presentationJob, cleanupFailedIdentity);

  renderClientResult("Scan Device", "failed", "Client failure", { error: "detail survives" });
  strictAssert.equal(state.jobs[0].summary, "Client failure");
  strictAssert.equal(resultNode.textContent, JSON.stringify({ error: "detail survives" }, null, 2));

  clearJobResults();
  strictAssert.deepEqual(state.jobs, []);
  strictAssert.equal(historyNode.children.length, 0);
  renderHistory();
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""
    )
