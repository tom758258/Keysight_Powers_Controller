export function snapshotSuggestedName(document, metadata, now) {
  const pad = (value) => String(value).padStart(2, "0");
  const timestamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const clean = (value) => value ? String(value).replace(/[<>:"/\\|?*]/g, "").trim() : "";
  const model = clean(metadata?.model || document?.reported_identity?.model);
  const serial = clean(metadata?.serial || document?.reported_identity?.serial);
  return model && serial
    ? `powers-tool-${model}-${serial}-${timestamp}.snapshot.json`
    : `powers-tool-snapshot-${timestamp}.snapshot.json`;
}

export function validateSnapshotDocument(document) {
  if (!document || typeof document !== "object" || Array.isArray(document)) {
    throw new Error("Snapshot document must be a JSON object.");
  }
  if (document.schema_version !== 2 || document.kind !== "powers-tool-snapshot") {
    throw new Error("Snapshot must use schema_version 2 and kind 'powers-tool-snapshot'.");
  }
  if (!document.reported_identity || typeof document.reported_identity !== "object" || Array.isArray(document.reported_identity)) {
    throw new Error("Snapshot must contain a valid 'reported_identity' object.");
  }
  if (!document.resolved_identity || typeof document.resolved_identity !== "object" || Array.isArray(document.resolved_identity)) {
    throw new Error("Snapshot must contain a valid 'resolved_identity' object.");
  }
  if (!Array.isArray(document.readback)) {
    throw new Error("Snapshot 'readback' must be an array.");
  }
  if (!Array.isArray(document.outputs)) {
    throw new Error("Snapshot 'outputs' must be an array.");
  }
}
export function validateRestoreSnapshot(document) {
  validateSnapshotDocument(document);
  if (!document.reported_identity.model || !document.resolved_identity.model_id) throw new Error("Snapshot must contain reported and resolved model identity.");
  if (document.readback.length === 0) throw new Error("Snapshot must contain at least one channel in readback.");
  if (document.outputs.length === 0) throw new Error("Snapshot must contain at least one channel in outputs.");
  if (document.protection_settings && !Array.isArray(document.protection_settings)) throw new Error("Snapshot 'protection_settings' must be an array.");
  validateReadbackChannels(document.readback);
  validateOutputChannels(document.outputs);
  const supportedModels = new Set(["keysight-e36312a", "gw-instek-psm-2010"]);
  if (!supportedModels.has(document.resolved_identity.model_id)) {
    throw new Error(`Snapshot model_id '${document.resolved_identity.model_id}' is not supported for restore.`);
  }
  if (document.resolved_identity.model_id === "gw-instek-psm-2010") {
    if (!Array.isArray(document.output_ranges) || document.output_ranges.length !== 1) {
      throw new Error("PSM-2010 snapshot must contain one output_ranges entry.");
    }
    const outputRange = document.output_ranges[0];
    if (outputRange?.channel !== 1 || !["LOW", "HIGH"].includes(outputRange?.range)) {
      throw new Error("PSM-2010 snapshot output range must be LOW or HIGH for channel 1.");
    }
  }
}

function validateReadbackChannels(readback) {
  const channels = new Set();
  readback.forEach((item, index) => {
    if (!item || typeof item !== "object") throw new Error(`Snapshot readback item at index ${index} must be an object.`);
    const channel = item.channel;
    if (!Number.isInteger(channel) || channel < 1 || channel > 3) throw new Error(`Snapshot readback item at index ${index} must have a valid 'channel' (1, 2, or 3).`);
    if (channels.has(channel)) throw new Error(`Snapshot readback contains duplicate channel ${channel}.`);
    channels.add(channel);
    if (!item.setpoints || typeof item.setpoints !== "object") throw new Error(`Snapshot readback item at channel ${channel} is missing a valid 'setpoints' object.`);
    const { voltage, current } = item.setpoints;
    if (typeof voltage !== "number" || typeof current !== "number" || !Number.isFinite(voltage) || !Number.isFinite(current)) {
      throw new Error(`Snapshot readback item at channel ${channel} 'setpoints' must contain finite numbers for 'voltage' and 'current'.`);
    }
  });
}

function validateOutputChannels(outputs) {
  const channels = new Set();
  outputs.forEach((item, index) => {
    if (!item || typeof item !== "object") throw new Error(`Snapshot outputs item at index ${index} must be an object.`);
    const channel = item.channel;
    if (!Number.isInteger(channel) || channel < 1 || channel > 3) throw new Error(`Snapshot outputs item at index ${index} must have a valid 'channel' (1, 2, or 3).`);
    if (channels.has(channel)) throw new Error(`Snapshot outputs contains duplicate channel ${channel}.`);
    channels.add(channel);
    if (typeof item.enabled !== "boolean") throw new Error(`Snapshot outputs item at channel ${channel} must contain a boolean 'enabled' property.`);
  });
}

export function normalizeRestoreChannel(value, normalizeChannelValue) {
  return value === "all" ? "all" : normalizeChannelValue(value);
}

export function restoreSnapshotParameters(document, restoreChannel, restoreOutputState, normalizeChannelValue) {
  return {
    document,
    channel: normalizeRestoreChannel(restoreChannel, normalizeChannelValue),
    restore_output_state: restoreOutputState
  };
}
