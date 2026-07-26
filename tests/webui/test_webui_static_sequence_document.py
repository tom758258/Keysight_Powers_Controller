"""Direct behavior checks for Sequence document helpers."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_sequence_document_module_is_pure_and_preserves_normalization_contract() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    sequence_document_js = read_static_javascript("sequence.js")

    assert 'from "./sequence.js"' in app_js
    assert "getElementById" not in sequence_document_js
    assert "createElement" not in sequence_document_js
    assert "querySelector" not in sequence_document_js
    assert "fetch(" not in sequence_document_js
    assert "EventSource" not in sequence_document_js

    run_webui_module_assertions(
        r"""
const sequence = globalThis.webuiSequenceDocument;
const fields = { wait: [{ name: "seconds", type: "number", value: 0 }], "trigger-pulse": [{ name: "pins", type: "select", options: ["1", "2", "1,2"], value: [1] }] };
const dependencies = {
  maxSteps: 3,
  sequenceActions: ["wait", "trigger-pulse"],
  actionDefinitions: (action) => fields[action] || [],
  defaultStep: (action) => Object.fromEntries([["action", action], ...fields[action].map((field) => [field.name, field.value])]),
  parseRearPins: (value) => Array.isArray(value) ? value : String(value).split(",").map(Number),
  validateCanonicalStep: (step) => { if (step.action === "wait" && step.seconds < 0) throw new Error("negative seconds"); }
};
dependencies.normalizeStep = (step, index) => sequence.normalizeSequenceStep(step, index, dependencies);
const v1 = sequence.normalizeSequenceDocument({ version: 1, steps: [{ wait: { seconds: 0 } }] }, dependencies);
strictAssert.deepEqual(v1, { version: 2, loopCount: 1, steps: [{ action: "wait", seconds: 0 }] });
const v2 = sequence.normalizeSequenceDocument({ version: 2, loop_count: 2, steps: [{ action: "trigger-pulse", pins: "1,2" }] }, dependencies);
strictAssert.deepEqual(v2.steps[0], { action: "trigger-pulse", pins: [1, 2] });
strictAssert.equal(sequence.normalizeSequenceDocument({ version: 2, loop_count: 10000, steps: [{ action: "wait", seconds: 0 }] }, dependencies).loopCount, 10000);
strictAssert.throws(() => sequence.normalizeSequenceDocument({ version: 2, loop_count: 10001, steps: [{ action: "wait", seconds: 0 }] }, dependencies), /10,000/);
strictAssert.throws(() => sequence.normalizeSequenceDocument({ version: 2, steps: [{ action: "wait", seconds: 0 }] }, dependencies), /loop_count/);
strictAssert.throws(() => sequence.normalizeSequenceDocument({ version: 1, loop_count: 2, steps: [{ action: "wait", seconds: 0 }] }, dependencies), /unsupported fields/);
const state = { sequenceSteps: [{ action: "wait", seconds: 0 }] };
strictAssert.deepEqual(sequence.sequenceDocumentFromEditor(state, { ...dependencies, loopCount: 2 }), { version: 2, loop_count: 2, steps: [{ action: "wait", seconds: 0 }] });
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("sequence.js",),
    )
