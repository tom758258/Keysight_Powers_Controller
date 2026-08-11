"""Direct behavior checks for Snapshot document helpers."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_snapshot_document_module_is_pure_and_preserves_schema_contract() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    snapshot_document_js = read_static_javascript("snapshot-restore.js")

    assert 'from "./snapshot-restore.js"' in app_js
    assert "getElementById" not in snapshot_document_js
    assert "createElement" not in snapshot_document_js
    assert "querySelector" not in snapshot_document_js
    assert "fetch(" not in snapshot_document_js
    assert "EventSource" not in snapshot_document_js

    run_webui_module_assertions(
        r"""
const snapshot = globalThis.webuiSnapshotDocument;
const valid = { schema_version: 2, kind: "powers-tool-snapshot", reported_identity: { model: "E36312A", serial: "A/1" }, resolved_identity: { model_id: "keysight-e36312a" }, readback: [], outputs: [] };
strictAssert.equal(snapshot.validateSnapshotDocument(valid), undefined);
strictAssert.equal(snapshot.snapshotSuggestedName(valid, null, new Date(2024, 0, 2, 3, 4, 5)), "powers-tool-E36312A-A1-20240102-030405.snapshot.json");
strictAssert.throws(() => snapshot.validateSnapshotDocument({ ...valid, kind: "other" }), /schema_version 2/);
strictAssert.throws(() => snapshot.validateSnapshotDocument({ ...valid, readback: {} }), /readback/);
const psm = { ...valid, reported_identity: { model: "PSM-2010", serial: "SIM" }, resolved_identity: { model_id: "gw-instek-psm-2010" }, readback: [{ channel: 1, setpoints: { voltage: 1, current: 0.05 } }], outputs: [{ channel: 1, enabled: false }], output_ranges: [{ channel: 1, range: "LOW" }] };
strictAssert.equal(snapshot.validateRestoreSnapshot(psm), undefined);
strictAssert.throws(() => snapshot.validateRestoreSnapshot({ ...psm, output_ranges: undefined }), /output_ranges/);
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("snapshot-restore.js",),
    )
