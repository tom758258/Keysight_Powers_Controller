export function defaultRampSegment() {
  return {
    channel: 1,
    current: 0.1,
    start_voltage: 0,
    stop_voltage: 1,
    step_voltage: 0.1,
    delay_ms: 100,
    hold_ms: 0
  };
}

export function rampSegmentDefinitions() {
  return [
    { name: "channel", label: "Channel" },
    { name: "current", label: "Current(A)" },
    { name: "start_voltage", label: "Start voltage(V)" },
    { name: "stop_voltage", label: "Stop voltage(V)" },
    { name: "step_voltage", label: "Step voltage(V)" },
    { name: "delay_ms", label: "Wait between steps (ms)" },
    { name: "hold_ms", label: "Wait after final step (ms)" }
  ];
}

export function effectiveEnabledLoopCount(enabled, draft) {
  if (!enabled) return 1;
  const parsed = draft === "" ? Number.NaN : Number(draft);
  return Number.isInteger(parsed) && parsed >= 2 && parsed <= 10000 ? parsed : Number.NaN;
}

export function rampListDocument(state) {
  const document = {
    kind: "powers-tool-ramp-list",
    version: 4,
    enable_output: state.rampListEnableOutput,
    loop_count: effectiveEnabledLoopCount(state.rampListLoopEnabled, state.rampListLoopCountDraft),
    segments: state.rampListSegments.map((segment) => ({ ...segment }))
  };
  if (state.rampListCompletionPulse) document.completion_pulse = { ...state.rampListCompletionPulse };
  return document;
}

export function validateRampListDocument(document) {
  if (!document || document.kind !== "powers-tool-ramp-list" || ![2, 3, 4].includes(document.version)) {
    throw new Error("Invalid Ramp List kind or version.");
  }
  const topLevelFields = document.version === 4
    ? ["kind", "version", "enable_output", "loop_count", "completion_pulse", "segments"]
    : document.version === 3
    ? ["kind", "version", "enable_output", "completion_pulse", "segments"]
    : ["kind", "version", "completion_pulse", "segments"];
  if (Object.keys(document).some((field) => !topLevelFields.includes(field))) {
    throw new Error("Ramp List contains unsupported fields.");
  }
  if (document.version >= 3 && typeof document.enable_output !== "boolean") {
    throw new Error("Ramp List version 3 or 4 requires boolean enable_output.");
  }
  if (!Array.isArray(document.segments) || document.segments.length < 1 || document.segments.length > 10) {
    throw new Error("Ramp List requires 1 to 10 segments.");
  }
  const fields = rampSegmentDefinitions().map((item) => item.name);
  const segments = document.segments.map((segment, index) => {
    if (!segment || Object.keys(segment).some((field) => !fields.includes(field)) || fields.some((field) => typeof segment[field] !== "number" || !Number.isFinite(segment[field]))) {
      throw new Error(`Ramp Segment ${index + 1} contains invalid fields.`);
    }
    const voltageCount = Math.ceil(Math.abs(segment.stop_voltage - segment.start_voltage) / segment.step_voltage) + 1;
    if (!Number.isInteger(segment.channel) || segment.channel < 1 || segment.channel > 3
      || segment.current < 0 || segment.start_voltage < 0 || segment.stop_voltage < 0 || segment.step_voltage <= 0
      || !Number.isInteger(segment.delay_ms) || !Number.isInteger(segment.hold_ms)
      || segment.delay_ms < 0 || segment.hold_ms < 0 || voltageCount > 1000) {
      throw new Error(`Ramp Segment ${index + 1} contains invalid limits.`);
    }
    return Object.fromEntries(fields.map((field) => [field, segment[field]]));
  });
  const loopCount = document.version === 4 ? document.loop_count : 1;
  if (!Number.isInteger(loopCount) || loopCount < 1 || loopCount > 10000) {
    throw new Error("Ramp List loop_count must be an integer from 1 to 10,000.");
  }
  let completionPulse = null;
  if (document.completion_pulse !== undefined) {
    const pulse = document.completion_pulse;
    if (!pulse || !["segment", "step", "loop"].includes(pulse.timing) || !Array.isArray(pulse.pins) || !pulse.pins.length
      || pulse.pins.some((pin) => ![1, 2, 3].includes(pin)) || !["positive", "negative"].includes(pulse.polarity)) {
      throw new Error("Ramp List completion_pulse is invalid.");
    }
    if (pulse.timing === "loop" && loopCount < 2) throw new Error("Ramp List Loop complete pulse requires loop_count of at least 2.");
    completionPulse = { timing: pulse.timing, pins: [...pulse.pins], polarity: pulse.polarity };
  }
  return {
    segments,
    completionPulse,
    enableOutput: document.version >= 3 ? document.enable_output : false,
    loopCount
  };
}
