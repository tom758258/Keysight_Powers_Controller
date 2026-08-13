export function defaultRampSegment() {
  return {
    channels: [1],
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
    { name: "channels", label: "Channels" },
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
    version: 5,
    enable_output: state.rampListEnableOutput,
    loop_count: effectiveEnabledLoopCount(state.rampListLoopEnabled, state.rampListLoopCountDraft),
    segments: state.rampListSegments.map((segment) => ({
      ...segment,
      channels: [...segment.channels]
    }))
  };
  if (state.rampListCompletionPulse) document.completion_pulse = { ...state.rampListCompletionPulse };
  return document;
}

export function validateRampListDocument(document, supportedChannels = null) {
  if (!document || document.kind !== "powers-tool-ramp-list" || ![2, 3, 4, 5].includes(document.version)) {
    throw new Error("Invalid Ramp List kind or version.");
  }
  const topLevelFields = document.version >= 4
    ? ["kind", "version", "enable_output", "loop_count", "completion_pulse", "segments"]
    : document.version === 3
    ? ["kind", "version", "enable_output", "completion_pulse", "segments"]
    : ["kind", "version", "completion_pulse", "segments"];
  if (Object.keys(document).some((field) => !topLevelFields.includes(field))) {
    throw new Error("Ramp List contains unsupported fields.");
  }
  if (document.version >= 3 && typeof document.enable_output !== "boolean") {
    throw new Error("Ramp List version 3, 4, or 5 requires boolean enable_output.");
  }
  if (!Array.isArray(document.segments) || document.segments.length < 1 || document.segments.length > 10) {
    throw new Error("Ramp List requires 1 to 10 segments.");
  }
  const valueFields = rampSegmentDefinitions().map((item) => item.name).filter((name) => name !== "channels");
  const selector = document.version === 5 ? "channels" : "channel";
  const fields = [selector, ...valueFields];
  const segments = document.segments.map((segment, index) => {
    if (!segment || Object.keys(segment).some((field) => !fields.includes(field))
      || valueFields.some((field) => typeof segment[field] !== "number" || !Number.isFinite(segment[field]))) {
      throw new Error(`Ramp Segment ${index + 1} contains invalid fields.`);
    }
    let channels;
    if (document.version === 5) {
      if (!Array.isArray(segment.channels) || !segment.channels.length
        || segment.channels.some((channel) => !Number.isInteger(channel) || channel < 1)
        || new Set(segment.channels).size !== segment.channels.length) {
        throw new Error(`Ramp Segment ${index + 1} contains invalid channels.`);
      }
      channels = [...segment.channels];
      if (Array.isArray(supportedChannels)
        && channels.every((channel) => supportedChannels.includes(channel))) {
        channels = supportedChannels.filter((channel) => channels.includes(channel));
      }
    } else {
      if (!Number.isInteger(segment.channel) || segment.channel < 1) {
        throw new Error(`Ramp Segment ${index + 1} contains invalid channel.`);
      }
      channels = [segment.channel];
    }
    const voltageCount = Math.ceil(Math.abs(segment.stop_voltage - segment.start_voltage) / segment.step_voltage) + 1;
    if (segment.current < 0 || segment.start_voltage < 0 || segment.stop_voltage < 0 || segment.step_voltage <= 0
      || !Number.isInteger(segment.delay_ms) || !Number.isInteger(segment.hold_ms)
      || segment.delay_ms < 0 || segment.hold_ms < 0 || voltageCount > 1000) {
      throw new Error(`Ramp Segment ${index + 1} contains invalid limits.`);
    }
    return {
      channels,
      ...Object.fromEntries(valueFields.map((field) => [field, segment[field]]))
    };
  });
  const loopCount = document.version >= 4 ? document.loop_count : 1;
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
