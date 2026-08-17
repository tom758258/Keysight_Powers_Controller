import * as webuiCommandForm from "./command-form.js";

export function createCommandParams({ rearPinOptions, optionalRearPinOptions }) {
  const PARAMS = {
    "list-resources": [{ name: "live_only", type: "checkbox", label: "Live only" }],
    verify: [],
    clear: [],
    error: [{ name: "max_reads", type: "number", label: "Max reads", value: 20 }],
    readback: [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all" }],
    set: webuiCommandForm.setOutputParams(),
    apply: [...webuiCommandForm.applyOutputParams(), { name: "no_output", type: "checkbox", label: "Do not enable output" }],
    "output-on": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }],
    "output-off": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" }],
    "safe-off": [{
      name: "channel",
      type: "select",
      label: "Channel",
      options: ["all", "1", "2", "3"],
      value: "all",
      description: "Disables the selected output, or every available output when set to all, then reads back each output state. Voltage/current setpoints and protection settings are not changed."
    }],
    "cycle-output": [
      { name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" },
      { name: "duration_ms", type: "number", label: "Duration(ms)", value: 100 },
      { name: "completion_pulse_enabled", type: "checkbox", label: "Trigger pulse when finished", pulseToggle: true },
      { name: "completion_pulse_pins", type: "select", label: "Rear pins", options: rearPinOptions, value: "1", parser: "intList", pulseChild: true },
      { name: "completion_pulse_polarity", type: "select", label: "Polarity", options: ["positive", "negative"], value: "positive", pulseChild: true }
    ],
    ramp: [
      { name: "enable_output", type: "checkbox", label: "Enable output", ariaLabel: "Enable output after first setpoint", helpId: "ramp-enable-output-help", compactHelp: true, description: "Output is enabled only after the first safe setpoint is written and verified. It remains ON after normal completion. Stop workflow turns off every instrument output. Real hardware still requires confirmation." },
      { name: "loop_enabled", type: "checkbox", label: "Enable loop" },
      { name: "loop_count", type: "number", label: "Loop count", value: 2, conditionalLoop: true },
      { name: "channel", type: "select", label: "Channel", options: ["1"], value: "1" },
      { name: "current", type: "number", label: "Current(A)", value: 0.1 },
      { name: "start_voltage", type: "number", label: "Start voltage(V)", value: 0 },
      { name: "stop_voltage", type: "number", label: "Stop voltage(V)", value: 1 },
      { name: "step_voltage", type: "number", label: "Step voltage(V)", value: 0.1 },
      { name: "delay_ms", type: "number", label: "Wait between steps (ms)", value: 0 },
      { name: "completion_pulse_timing", type: "select", label: "Pulse timing", options: ["", "step", "segment", "loop"], value: "" },
      { name: "completion_pulse_pins", type: "select", label: "Rear pins", options: rearPinOptions, value: "1", parser: "intList", pulseChild: true },
      { name: "completion_pulse_polarity", type: "select", label: "Polarity", options: ["positive", "negative"], value: "positive", pulseChild: true }
    ],
    "ramp-list": [],
    "smoke-output": webuiCommandForm.smokeOutputParams(),
    "protection-set": [
      { name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "1" },
      { name: "ovp_voltage", type: "number", label: "OVP voltage(V)", value: 5 },
      { name: "ocp", type: "select", label: "OCP", options: ["", "on", "off"], value: "" },
      { name: "ocp_delay", type: "number", label: "OCP delay(s)", optional: true },
      { name: "ocp_delay_trigger", type: "select", label: "OCP delay trigger", options: ["", "setting-change", "cc-transition"], value: "" }
    ],
    "clear-protection": [{ name: "channel", type: "select", label: "Channel", options: ["", "all", "1", "2", "3"], value: "" }],
    "trigger-pulse": [
      { name: "pins", type: "select", label: "Rear pins", options: rearPinOptions, value: "1", parser: "intList", description: "E36312A only. Configures the selected rear pins as trigger outputs, keeps the current programmed setpoint, and sends global *TRG. The pulse may also fire other armed BUS triggers." },
      { name: "channel", type: "select", label: "Channel", options: ["1", "2", "3"], value: "1" },
      { name: "polarity", type: "select", label: "Polarity", options: ["positive", "negative"], value: "positive" },
      { name: "exclusive_pins", type: "checkbox", label: "Exclusive pins", description: "Resets unselected rear pins before configuring the selected pulse pins." }
    ],
    "trigger-status": [{ name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all", description: "Read-only E36312A query of rear pins, trigger source, and STEP/LIST state. It does not modify instrument settings." }],
    "trigger-step": webuiCommandForm.triggerStepParams(),
    "trigger-list": [],
    "trigger-fire": [
      { name: "channel", type: "select", label: "Abort target channel", options: ["", "1", "2", "3"], value: "", optional: true, description: "Used only to abort this output channel if Wait complete times out or is interrupted." },
      { name: "wait_complete", type: "checkbox", label: "Wait complete", description: "Waits for the instrument-wide operation-complete event. Requires an Abort target channel." },
      ...webuiCommandForm.triggerWaitParams()
    ],
    "trigger-abort": [
      { name: "channel", type: "select", label: "Channel", options: ["all", "1", "2", "3"], value: "all", description: "E36312A only. Aborts Trigger/LIST execution for the selected channel or all channels. It does not turn outputs off." },
      { name: "max_errors", type: "number", label: "Max errors", value: 20, description: "Limits how many instrument error-queue entries are read after aborting." }
    ],
    identify: [],
    snapshot: [{
      name: "max_errors",
      type: "number",
      label: "Max errors",
      value: 20,
      description: "Limits how many times the snapshot reads the instrument error queue. Reading stops early when the instrument reports no error. Each reported error is removed from the instrument queue."
    }],
    sequence: []
  };
  return PARAMS;
}
