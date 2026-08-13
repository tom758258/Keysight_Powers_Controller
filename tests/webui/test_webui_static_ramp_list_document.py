"""Direct behavior checks for Ramp List document helpers."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_ramp_list_document_module_is_pure_and_preserves_documents() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    ramp_list_js = read_static_javascript("ramp-list.js")

    assert 'from "./ramp-list.js"' in app_js
    assert "getElementById" not in ramp_list_js
    assert "createElement" not in ramp_list_js
    assert "querySelector" not in ramp_list_js
    assert "fetch(" not in ramp_list_js
    assert "EventSource" not in ramp_list_js

    run_webui_module_assertions(
        r"""
const ramp = globalThis.webuiRampListDocument;
strictAssert.deepEqual(ramp.defaultRampSegment(), { channels: [1], current: 0.1, start_voltage: 0, stop_voltage: 1, step_voltage: 0.1, delay_ms: 100, hold_ms: 0 });
strictAssert.deepEqual(ramp.rampSegmentDefinitions().map((definition) => definition.name), ["channels", "current", "start_voltage", "stop_voltage", "step_voltage", "delay_ms", "hold_ms"]);
strictAssert.deepEqual(ramp.rampSegmentDefinitions().slice(-2), [
  { name: "delay_ms", label: "Wait between steps (ms)" },
  { name: "hold_ms", label: "Wait after final step (ms)" },
]);
strictAssert.equal(ramp.effectiveEnabledLoopCount(false, "99"), 1);
strictAssert.equal(ramp.effectiveEnabledLoopCount(true, "2"), 2);
strictAssert.equal(ramp.effectiveEnabledLoopCount(true, "10000"), 10000);
strictAssert.ok(Number.isNaN(ramp.effectiveEnabledLoopCount(true, "1")));
strictAssert.ok(Number.isNaN(ramp.effectiveEnabledLoopCount(true, "10001")));
const state = { rampListEnableOutput: true, rampListLoopEnabled: true, rampListLoopCountDraft: "2", rampListSegments: [ramp.defaultRampSegment()], rampListCompletionPulse: { timing: "loop", pins: [1], polarity: "positive" } };
const saved = ramp.rampListDocument(state);
strictAssert.equal(saved.kind, "powers-tool-ramp-list");
strictAssert.equal(saved.version, 5);
strictAssert.deepEqual(ramp.validateRampListDocument(saved), { segments: [ramp.defaultRampSegment()], completionPulse: { timing: "loop", pins: [1], polarity: "positive" }, enableOutput: true, loopCount: 2 });
const legacySegment = { channel: 2, current: 0.1, start_voltage: 0, stop_voltage: 1, step_voltage: 0.1, delay_ms: 100, hold_ms: 0 };
for (const version of [2, 3, 4]) {
  const legacy = { kind: "powers-tool-ramp-list", version, segments: [legacySegment] };
  if (version >= 3) legacy.enable_output = false;
  if (version === 4) legacy.loop_count = 1;
  strictAssert.deepEqual(ramp.validateRampListDocument(legacy).segments[0].channels, [2]);
}
const unorderedV5 = { ...saved, segments: [{ ...saved.segments[0], channels: [3, 1] }] };
strictAssert.deepEqual(ramp.validateRampListDocument(unorderedV5, [1, 2, 3]).segments[0].channels, [1, 3]);
strictAssert.throws(() => ramp.validateRampListDocument({ ...saved, segments: [{ ...saved.segments[0], channel: 1 }] }), /invalid fields/);
strictAssert.throws(() => ramp.validateRampListDocument({ ...saved, completion_pulse: { ...saved.completion_pulse, timing: "loop" }, loop_count: 1 }), /loop_count/);
strictAssert.throws(() => ramp.validateRampListDocument({ ...saved, unexpected: true }), /unsupported fields/);
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("ramp-list.js",),
    )
