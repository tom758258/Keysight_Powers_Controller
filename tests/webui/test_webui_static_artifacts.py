"""Static JSON artifact, Snapshot, Restore, and Sequence WebUI tests."""

from __future__ import annotations

from _webui_shared import (
    extract_js_function,
    read_static_javascript,
    read_static_texts,
    run_frontend_javascript_assertions,
)

def test_static_json_artifact_file_helpers_have_cancel_and_accept_contracts():
    _index_html, app_js, _styles_css = read_static_texts()
    json_files_js = read_static_javascript("json-files.js")

    open_json = extract_js_function(json_files_js, "openJsonFile")
    choose_json = extract_js_function(json_files_js, "chooseJsonFile")
    save_json = extract_js_function(json_files_js, "saveJsonFile")
    build_accept = extract_js_function(json_files_js, "buildJsonFileAccept")
    build_native_accept = extract_js_function(json_files_js, "buildNativeJsonPickerAccept")

    assert '"application/json"' in json_files_js
    assert 'const SNAPSHOT_JSON_EXTENSIONS = [".snapshot.json", ".json"];' in app_js
    assert 'const SEQUENCE_JSON_EXTENSIONS = [".sequence.json", ".json"];' in app_js
    assert 'const RAMP_LIST_JSON_EXTENSIONS = [".ramp-list.json", ".json"];' in app_js
    assert 'return { "application/json": [".json"] };' in build_native_accept
    assert "chooseJsonFile(buildJsonFileAccept(extensions))" in open_json
    assert 'return [...extensions, "application/json"].join(",");' in build_accept
    assert 'input.addEventListener("cancel", abort);' in choose_json
    assert 'window.addEventListener("focus", onWindowFocus, { once: true });' in choose_json
    assert 'abortError(t("file.status.selection_cancelled"))' in choose_json
    assert "document.body.appendChild(link);" in save_json
    assert "window.setTimeout(() => URL.revokeObjectURL(url), 0);" in save_json


def test_frontend_native_json_pickers_use_json_accept_map():
    run_frontend_javascript_assertions(
        r"""
const openOptions = [];
const saveOptions = [];
globalThis.window = {
  showOpenFilePicker: async (options) => {
    openOptions.push(options);
    return [{
      getFile: async () => ({ name: "example.json", text: async () => "{}" })
    }];
  },
  showSaveFilePicker: async (options) => {
    saveOptions.push(options);
    return {
      createWritable: async () => ({ write: async () => {}, close: async () => {} })
    };
  }
};

await globalThis.webuiJsonFiles.openJsonFile({
  description: "Snapshot JSON",
  extensions: [".snapshot.json", ".json"]
});
await globalThis.webuiJsonFiles.saveJsonFile("{}", {
  description: "Snapshot JSON",
  extensions: [".snapshot.json", ".json"],
  suggestedName: "example.snapshot.json"
});

const expectedAccept = { "application/json": [".json"] };
strictAssert.deepEqual(openOptions[0].types[0].accept, expectedAccept);
strictAssert.deepEqual(saveOptions[0].types[0].accept, expectedAccept);
""",
        ("json-files.js",),
    )

def test_static_json_artifact_abort_errors_do_not_render_client_failures():
    _index_html, app_js, _styles_css = read_static_texts()
    workflows_js = read_static_javascript("workflows.js")

    for function_name in (
        "loadRampList",
        "saveRampList",
        "saveSnapshot",
        "loadRestoreSnapshot",
        "loadSequenceFile",
        "saveSequenceFile",
    ):
        block = extract_js_function(workflows_js, function_name)
        assert "catch (error)" in block
        catch_block = block[block.index("catch (error)"):]
        assert "if (isAbortError(error)) return;" in catch_block
        assert catch_block.index("if (isAbortError(error)) return;") < catch_block.index("renderClientResult(")


def test_static_snapshot_completion_validates_finished_result_before_saving_state():
    _index_html, app_js, _styles_css = read_static_texts()

    handle_job_event = extract_js_function(read_static_javascript("jobs.js"), "handleJobEvent")
    capture_snapshot = extract_js_function(app_js, "captureLatestSnapshotDocument")

    assert "captureLatestSnapshotDocument(job);" in handle_job_event
    assert "state.latestSnapshotDocument = job.result;" not in handle_job_event
    assert 'job.command !== "snapshot"' in capture_snapshot
    assert 'job.status !== "finished"' in capture_snapshot
    assert "!job.result" in capture_snapshot
    assert "validateSnapshotDocument(job.result);" in capture_snapshot
    assert capture_snapshot.index("validateSnapshotDocument(job.result);") < capture_snapshot.index("state.latestSnapshotDocument = job.result;")
    assert "return false;" in capture_snapshot


def test_static_snapshot_save_validator_is_independent_from_restore_validator():
    _index_html, app_js, _styles_css = read_static_texts()
    snapshot_document_js = read_static_javascript("snapshot-restore.js")
    restore_document_js = read_static_javascript("snapshot-restore.js")
    workflows_js = read_static_javascript("workflows.js")

    snapshot_validator = extract_js_function(snapshot_document_js, "validateSnapshotDocument")
    restore_validator = extract_js_function(restore_document_js, "validateRestoreSnapshot")
    save_snapshot = extract_js_function(workflows_js, "saveSnapshot")

    assert "validateRestoreSnapshot" not in snapshot_validator
    assert "Array.isArray(document)" in snapshot_validator
    assert "return webuiSnapshotDocument.validateSnapshotDocument(doc);" in workflows_js
    assert "document.schema_version !== 2" in snapshot_validator
    assert "document.reported_identity" in snapshot_validator
    assert "document.resolved_identity" in snapshot_validator
    assert "document.readback" in snapshot_validator
    assert "document.outputs" in snapshot_validator
    assert "setpoints" not in snapshot_validator
    assert "E36312A" not in snapshot_validator

    assert "validateSnapshotDocument(document);" in restore_validator
    assert "validateReadbackChannels(document.readback);" in restore_validator
    assert "keysight-e36312a" in restore_validator
    assert "JSON.stringify(state.latestSnapshotDocument, null, 2)" in save_snapshot


def test_static_restore_payload_preflights_and_normalizes_channel():
    _index_html, app_js, _styles_css = read_static_texts()
    restore_document_js = read_static_javascript("snapshot-restore.js")

    run_selected = extract_js_function(app_js, "runSelected")
    parameter_payload = extract_js_function(read_static_javascript("command-form.js"), "parameterPayload")
    restore_parameters = extract_js_function(restore_document_js, "restoreSnapshotParameters")
    normalize_restore_channel = extract_js_function(restore_document_js, "normalizeRestoreChannel")
    update_selected = extract_js_function(app_js, "updateSelectedCommandState")

    assert "let validatedRestoreDocument = null;" in run_selected
    assert 'state.selected === "restore-from-snapshot"' in run_selected
    assert "validateRestoreSnapshot(state.loadedSnapshotDocument);" in run_selected
    assert "restoreSnapshotParameters(validatedRestoreDocument)" in run_selected
    assert run_selected.index('state.selected === "restore-from-snapshot"') < run_selected.index("const response = await submitJob(payload);")
    assert "restoreSnapshotParameters(state.loadedSnapshotDocument)" in parameter_payload
    assert "channel: normalizeRestoreChannel(restoreChannel, normalizeChannelValue)" in restore_parameters
    assert "file:" not in restore_parameters
    assert "snapshot:" not in restore_parameters
    assert 'return value === "all" ? "all" : normalizeChannelValue(value);' in normalize_restore_channel
    assert "isLoadedRestoreSnapshotValid();" in update_selected


def test_static_restore_plan_preview_reuses_dry_run_job():
    _index_html, app_js, _styles_css = read_static_texts()
    workflows_js = read_static_javascript("workflows.js")

    render_restore = extract_js_function(workflows_js, "renderRestoreForm")
    preview_restore = extract_js_function(workflows_js, "previewRestorePlan")
    handle_job_event = extract_js_function(read_static_javascript("jobs.js"), "handleJobEvent")
    update_selected = extract_js_function(app_js, "updateSelectedCommandState")

    assert 'previewPlanBtn.id = "btn-preview-restore-plan";' in render_restore
    assert 'workflowText(previewPlanBtn, "restore.action.preview_plan"' in render_restore
    assert 'previewPlanBtn.disabled = !isLoadedRestoreSnapshotValid() || state.restorePlanPreviewStatus === "running";' in render_restore
    assert "Loaded snapshot JSON" not in render_restore
    assert "Snapshot JSON Preview" not in render_restore
    assert "restore-preview" not in render_restore
    assert 'command: "restore-from-snapshot"' in preview_restore
    assert "dry_run: true" in preview_restore
    assert "confirm: true" in preview_restore
    assert "parameters: restoreSnapshotParameters(state.loadedSnapshotDocument)" in preview_restore
    assert 'addHistory(response.job_id, "restore-from-snapshot", "accepted"' in preview_restore
    assert "subscribeToJob(response.job_id, \"/api/events\");" in preview_restore
    assert "jobLabel(jobId) ===" in handle_job_event
    assert "captureRestorePlanPreview(job);" in handle_job_event
    assert 'document.getElementById("btn-preview-restore-plan")' in update_selected


def test_static_restore_plan_preview_is_safe_and_structured():
    _index_html, app_js, _styles_css = read_static_texts()
    workflows_js = read_static_javascript("workflows.js")

    render_restore = extract_js_function(workflows_js, "renderRestoreForm")
    render_preview = extract_js_function(workflows_js, "renderRestorePlanPreview")
    capture_preview = extract_js_function(app_js, "captureRestorePlanPreview")

    assert 'planPreview.id = "restore-plan-preview";' in render_restore
    assert "plan.steps.forEach((step)" in render_preview
    assert "step.command" in render_preview
    assert "command.textContent = step.command || \"\";" in render_preview
    assert "innerHTML" not in render_preview
    assert 'state.restorePlanPreviewStatus = "finished";' in capture_preview


def test_static_snapshot_max_errors_documents_destructive_queue_reads():
    _index_html, _app_js, _styles_css = read_static_texts()
    workflows_js = read_static_javascript("workflows.js")

    render_snapshot = extract_js_function(workflows_js, "renderSnapshotForm")
    append_description = extract_js_function(read_static_javascript("command-form.js"), "appendFieldDescription")

    assert "webuiCommandForm.appendFieldDescription(" in render_snapshot
    assert "`form.description.snapshot.${param.name}`" in render_snapshot
    assert 'description.className = "field-description";' in append_description
    assert "t(translationKey, undefined, param.description)" in append_description
    assert "description.dataset.workflowI18n = translationKey;" in append_description

    run_frontend_javascript_assertions(
        r"""
const strictAssert = require("node:assert/strict");
const params = globalThis.__webuiCommandParams.createCommandParams({ rearPinOptions: ["1", "2", "3"] });
const maxErrors = params.snapshot.find((field) => field.name === "max_errors");
strictAssert.ok(maxErrors);
strictAssert.equal(maxErrors.type, "number");
strictAssert.match(maxErrors.description, /error queue/);
strictAssert.match(maxErrors.description, /removed from the instrument queue/);
""",
        ("command-form.js", "command-params.js"),
    )


def test_static_safe_off_channel_documents_behavior():
    _index_html, _app_js, _styles_css = read_static_texts()

    run_frontend_javascript_assertions(
        r"""
const strictAssert = require("node:assert/strict");
const params = globalThis.__webuiCommandParams.createCommandParams({ rearPinOptions: ["1", "2", "3"] });
const channel = params["safe-off"].find((field) => field.name === "channel");
strictAssert.ok(channel);
strictAssert.deepEqual(channel.options, ["all", "1", "2", "3"]);
strictAssert.equal(channel.value, "all");
strictAssert.match(channel.description, /reads back each output state/);
strictAssert.match(channel.description, /not changed/);
""",
        ("command-form.js", "command-params.js"),
    )


def test_static_restore_load_rejects_legacy_envelope_contract():
    _index_html, app_js, _styles_css = read_static_texts()
    workflows_js = read_static_javascript("workflows.js")

    load_restore = extract_js_function(workflows_js, "loadRestoreSnapshot")
    assert "extensions: SNAPSHOT_JSON_EXTENSIONS" in load_restore
    assert "const rawDoc = JSON.parse(text);" in load_restore
    assert "validateRestoreSnapshot(rawDoc);" in load_restore
    assert "state.loadedSnapshotDocument = rawDoc;" in load_restore
    assert "unwrapSnapshot" not in app_js


def test_static_sequence_json_artifact_flow_contracts():
    _index_html, app_js, _styles_css = read_static_texts()
    workflows_js = read_static_javascript("workflows.js")

    sequence_fields = extract_js_function(workflows_js, "sequenceStepFields")

    assert 'const SEQUENCE_JSON_EXTENSIONS = [".sequence.json", ".json"];' in app_js
    assert "dataset.sequenceStepIndex" in workflows_js
    assert "input.dataset.sequenceField" in workflows_js
    assert "state.sequenceSteps" in workflows_js
    assert 'command: "sequence"' in app_js
    assert "{ document: validatedSequenceDocument }" in app_js
    assert "param-document" not in app_js
    assert "option.value = action;" in sequence_fields
    assert 'workflowText(option, `sequence.action.${action.replaceAll("-", "_")}`, optionDisplayName(action));' in sequence_fields
    assert "localizedOption(option, value" in sequence_fields
    assert "option.value = value;" in extract_js_function(workflows_js, "localizedOption")
    assert 'localizedOption(option, value, definition.name === "pins" ? rearPinDisplayName(value) : optionDisplayName(value), definition.name === "pins");' in sequence_fields
