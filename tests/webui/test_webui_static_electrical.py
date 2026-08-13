"""Native-module contracts for pure WebUI electrical helpers."""

from __future__ import annotations

from _webui_shared import (
    read_static_javascript,
    read_static_texts,
    run_frontend_javascript_assertions,
    run_webui_module_assertions,
)


def test_electrical_module_is_pure_and_bootstrap_imports_it() -> None:
    index_html, app_js, _styles_css = read_static_texts()
    electrical_js = read_static_javascript("electrical.js")

    assert '<script type="module" src="/static/app.js"></script>' in index_html
    assert 'from "./electrical.js"' in app_js
    assert "PowersToolWebUI" not in electrical_js
    assert "document" not in electrical_js
    assert "fetch(" not in electrical_js
    assert "EventSource" not in electrical_js


def test_electrical_module_preserves_parameter_and_rating_semantics() -> None:
    run_webui_module_assertions(
        r"""
const electrical = globalThis.webuiElectrical;
strictAssert.deepEqual(Object.keys(electrical), ["resolveInputElectricalConstraint"]);
strictAssert.equal("PowersToolWebUI" in globalThis, false);
const constraints = { voltage: { min: 0, max: 100, step: 0.1, description: "Voltage" }, current: { min: 0, step: 0.01 } };
const ratings = { "model-a": { channels: [{ channel: 1, max_voltage: 6, max_current: 5 }, { channel: 2, max_voltage: 25, max_current: 1 }] } };
const voltage = electrical.resolveInputElectricalConstraint({ parameterConstraints: constraints, electricalRatingsByModel: ratings, modelId: "model-a", channel: 1, parameterName: "voltage" });
strictAssert.deepEqual(voltage, { parameter: { attributes: { min: "0", max: "100", step: "0.1", title: "Voltage" } }, rating: { max_voltage: 6, max_current: 5 }, override: { attributes: { max: "6", title: "Official independent-channel DC output rating: maximum 6 V." } } });
const all = electrical.resolveInputElectricalConstraint({ parameterConstraints: constraints, electricalRatingsByModel: ratings, modelId: "model-a", channel: "all", parameterName: "current" });
strictAssert.deepEqual(all.rating, { max_voltage: 6, max_current: 1 });
strictAssert.equal(all.override.attributes.max, "1");
const subset = electrical.resolveInputElectricalConstraint({ parameterConstraints: constraints, electricalRatingsByModel: ratings, modelId: "model-a", channel: [1, 2], parameterName: "voltage" });
strictAssert.deepEqual(subset.rating, { max_voltage: 6, max_current: 1 });
strictAssert.equal(subset.override.attributes.max, "6");
const current = electrical.resolveInputElectricalConstraint({ parameterConstraints: { current: { min: null, max: null, step: null, exclusive_min: null, description: "" } }, electricalRatingsByModel: ratings, modelId: "model-a", channel: "2", parameterName: "current" });
strictAssert.deepEqual(current.parameter, { attributes: { min: "null", max: "null", step: "any" }, exclusiveMin: "null" });
strictAssert.deepEqual(current.rating, { max_voltage: 25, max_current: 1 });
const startVoltage = electrical.resolveInputElectricalConstraint({ parameterConstraints: constraints, electricalRatingsByModel: ratings, modelId: "model-a", channel: 1, parameterName: "start_voltage" });
strictAssert.equal(startVoltage.override.attributes.max, "6");
const nonElectrical = electrical.resolveInputElectricalConstraint({ parameterConstraints: { delay_ms: { min: 0, step: 1, description: false } }, electricalRatingsByModel: ratings, modelId: "model-a", channel: 1, parameterName: "delay_ms" });
strictAssert.deepEqual(nonElectrical.parameter, { attributes: { min: "0", step: "1" } });
strictAssert.equal(nonElectrical.override, null);
const missing = electrical.resolveInputElectricalConstraint({ parameterConstraints: constraints, electricalRatingsByModel: ratings, modelId: "missing", channel: 1, parameterName: "voltage" });
strictAssert.deepEqual(missing, { parameter: { attributes: { min: "0", max: "100", step: "0.1", title: "Voltage" } }, rating: null, override: null });
const partial = electrical.resolveInputElectricalConstraint({ parameterConstraints: constraints, electricalRatingsByModel: { "model-a": { channels: [{ channel: 1, max_voltage: 6 }] } }, modelId: "model-a", channel: 1, parameterName: "current" });
strictAssert.equal(Number.isNaN(partial.rating.max_current), true);
strictAssert.equal(partial.override.attributes.max, "NaN");
const request = { parameterConstraints: constraints, electricalRatingsByModel: ratings, modelId: "model-a", channel: 1, parameterName: "voltage" };
const requestBefore = JSON.parse(JSON.stringify(request));
strictAssert.notEqual(electrical.resolveInputElectricalConstraint(request), electrical.resolveInputElectricalConstraint(request));
strictAssert.deepEqual(request, requestBefore);
""",
        ("electrical.js",),
    )


def test_frontend_rating_guard_remains_unchanged_for_workflow_and_restore_paths() -> None:
    assertions = r"""
const strictAssert = require("node:assert/strict");
const identity = { value: "model-a" };
const resource = { value: "RESOURCE" };
document.getElementById = (id) => id === "expected-model-id" ? identity : id === "resource" ? resource : null;
state.executionMode = "simulate";
state.physicalModels = [{ model_id: "model-a", display_name: "Model A" }];
state.electricalRatingsByModel = {
  "model-a": { channels: [{ channel: 1, max_voltage: 6, max_current: 5 }, { channel: 2, max_voltage: 25, max_current: 1 }] }
};
const expected = "Voltage 7 exceeds official DC output rating 6 V for Model A channel 1.";
strictAssert.equal(electricalRatingGuardReason("ramp", { channel: 1, start_voltage: 0, stop_voltage: 7, current: 1 }), expected);
strictAssert.equal(electricalRatingGuardReason("ramp", { channels: [1, 2], start_voltage: 0, stop_voltage: 7, current: 1 }), expected);
state.rampListSegments = [{ channels: [2, 1], start_voltage: 0, stop_voltage: 7, current: 1 }];
strictAssert.equal(electricalRatingGuardReason("ramp-list", {}), expected);
state.livePanel = { resource: "RESOURCE", stale: false, channels: [
  { channel: 1, protection_tripped: true }, { channel: 2, protection_tripped: false }
] };
strictAssert.match(tripGuardReason("ramp-list", {
  document: { segments: [{ channels: [2, 1] }] }
}), /CH1/);
strictAssert.equal(electricalRatingGuardReason("trigger-step", { channel: 1, voltage: 7, current: 1 }), expected);
strictAssert.equal(electricalRatingGuardReason("trigger-list", { channel: 1, voltage_list: [7], current_list: [1] }), expected);
state.sequenceSteps = [{ action: "set", channel: 1, voltage: 7, current: 1 }];
strictAssert.equal(electricalRatingGuardReason("sequence", {}), expected);
state.loadedSnapshotDocument = { readback: [{ channel: 1, setpoints: { voltage: 7, current: 1 } }] };
state.restoreChannel = "all";
strictAssert.equal(electricalRatingGuardReason("restore-from-snapshot", {}), expected);
strictAssert.equal(electricalRatingGuardReason("set", { channel: 1, voltage: 6, current: 5 }), "");
"""
    run_frontend_javascript_assertions(assertions)
