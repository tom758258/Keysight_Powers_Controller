"""Direct behavior checks for Trigger parameter schema helpers."""

from __future__ import annotations

from _webui_shared import run_webui_module_assertions


def test_command_form_module_owns_trigger_parameter_descriptors() -> None:
    run_webui_module_assertions(
        r"""
const trigger = globalThis.webuiCommandForm;
strictAssert.deepEqual(trigger.triggerWaitParams().map((field) => field.name), ["poll_ms", "wait_timeout_ms"]);
const step = trigger.triggerStepParams();
strictAssert.deepEqual(step.map((field) => field.name), ["channel", "voltage", "current", "source", "fire", "wait_complete", "poll_ms", "wait_timeout_ms", "leave_trigger_configured"]);
strictAssert.deepEqual(step.find((field) => field.name === "source").options, ["bus", "immediate"]);
const list = trigger.triggerListParams(["", "1", "1,2"]);
strictAssert.deepEqual(list.find((field) => field.name === "completion_pulse_pins").options, ["", "1", "1,2"]);
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("command-form.js",),
    )
