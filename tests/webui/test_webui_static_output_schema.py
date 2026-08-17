"""Static and direct behavior checks for fixed output command parameter schemas."""

from __future__ import annotations

from _webui_shared import read_static_texts, run_webui_module_assertions


def test_command_form_module_owns_fixed_output_parameters() -> None:
    _index_html, app_js, _styles_css = read_static_texts()

    assert 'webuiCommandForm.setOutputParams()' in app_js

    run_webui_module_assertions(
        r"""
const schema = globalThis.webuiCommandForm;
const set = schema.setOutputParams();
strictAssert.deepEqual(set, [
  { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
  { name: "voltage", type: "number", label: "Voltage(V)", value: 1, optional: true },
  { name: "current", type: "number", label: "Current(A)", value: 0.1, optional: true }
]);
strictAssert.deepEqual(schema.applyOutputParams(), [
  { name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" },
  { name: "voltage", type: "number", label: "Voltage(V)", value: 1 },
  { name: "current", type: "number", label: "Current(A)", value: 0.1 }
]);
strictAssert.deepEqual(schema.smokeOutputParams(), [
  { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
  { name: "voltage", type: "number", label: "Voltage(V)", value: 1 },
  { name: "current", type: "number", label: "Current(A)", value: 0.1 },
  { name: "duration_ms", type: "number", label: "Duration(ms)", value: 100 }
]);
strictAssert.notStrictEqual(schema.setOutputParams(), schema.setOutputParams());
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("command-form.js",),
    )
