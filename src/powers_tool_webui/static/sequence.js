export function normalizeSequenceDocument(doc, dependencies) {
  const { maxSteps, normalizeStep } = dependencies;
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) throw new Error("Sequence document must be a JSON object.");
  if (doc.version !== undefined && doc.version !== 1 && doc.version !== "1" && doc.version !== 2) throw new Error("Sequence version must be 1 or 2.");
  const version = doc.version ?? 1;
  const allowedFields = version === 2 ? ["version", "steps", "loop_count"] : ["version", "steps"];
  if (Object.keys(doc).some((field) => !allowedFields.includes(field))) throw new Error("Sequence document contains unsupported fields.");
  if (!Array.isArray(doc.steps) || doc.steps.length === 0) throw new Error("Sequence document must contain a non-empty 'steps' array.");
  if (doc.steps.length > maxSteps) throw new Error(`Sequence supports at most ${maxSteps} steps in the WebUI.`);
  const loopCount = doc.version === 2 ? doc.loop_count : 1;
  if (!Number.isInteger(loopCount) || loopCount < 1 || loopCount > 10000) throw new Error("Sequence loop_count must be an integer from 1 to 10,000.");
  return { version: 2, loopCount, steps: doc.steps.map(normalizeStep) };
}

export function normalizeSequenceStep(step, index, dependencies) {
  const { sequenceActions, actionDefinitions, defaultStep, parseRearPins, validateCanonicalStep } = dependencies;
  if (!step) throw new Error(`Sequence step at index ${index} is null or empty.`);
  let action;
  let parameters = {};
  if (typeof step === "string") {
    action = step;
  } else if (typeof step === "object" && !Array.isArray(step)) {
    const keys = Object.keys(step);
    if ("action" in step || "type" in step) {
      if ("action" in step && "type" in step && step.action !== step.type) throw new Error(`Step ${index + 1} has conflicting action and type values.`);
      action = step.action ?? step.type;
      parameters = Object.fromEntries(Object.entries(step).filter(([key]) => !["action", "type"].includes(key)));
    } else if (keys.length === 1) {
      action = keys[0];
      parameters = typeof step[action] === "object" && step[action] !== null && !Array.isArray(step[action]) ? step[action] : {};
    } else {
      throw new Error(`Step ${index + 1} is invalid. Objects with multiple keys must contain an action or type property.`);
    }
  } else {
    throw new Error(`Invalid step format at index ${index + 1}.`);
  }
  if (!sequenceActions.includes(action)) {
    if (action === "delay") throw new Error(`Unsupported sequence action "delay" at step ${index + 1}. Did you mean "wait"?`);
    throw new Error(`Unsupported shorthand sequence action "${action}" at step ${index + 1}.`);
  }
  if (action === "wait" && "duration_sec" in parameters) {
    if ("seconds" in parameters && parameters.seconds !== parameters.duration_sec) throw new Error(`Sequence step ${index + 1} has conflicting seconds and duration_sec values.`);
    parameters = { ...parameters, seconds: parameters.duration_sec };
    delete parameters.duration_sec;
  }
  const allowed = new Set(actionDefinitions(action).map((field) => field.name));
  if (Object.keys(parameters).some((field) => !allowed.has(field))) throw new Error(`Sequence step ${index + 1} contains unsupported fields.`);
  if (["set", "apply"].includes(action) && (!("voltage" in parameters) || !("current" in parameters))) throw new Error(`Sequence step ${index + 1} requires voltage and current.`);
  const normalized = defaultStep(action, parameters);
  Object.entries(parameters).forEach(([key, value]) => { normalized[key] = value; });
  if (normalized.channel !== undefined && normalized.channel !== "all") normalized.channel = Number(normalized.channel);
  if (action === "trigger-pulse") normalized.pins = parseRearPins(normalized.pins);
  validateCanonicalStep(normalized, index);
  return normalized;
}

export function sequenceDocumentFromEditor(state, dependencies) {
  const normalized = normalizeSequenceDocument({ version: 2, loop_count: dependencies.loopCount, steps: state.sequenceSteps }, dependencies);
  return { version: 2, loop_count: normalized.loopCount, steps: normalized.steps };
}
