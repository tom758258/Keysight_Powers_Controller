import { t } from "./i18n.js";

export function createCommandSupport({
  state,
  defaultChannels,
  isNoHardwareMode,
  selectedPlanningIdentity,
  physicalModelDisplayName,
  selectedCommandModel,
  valueOrNull,
  detectedCommandModelForResource,
  selectedChannelModel
}) {
function currentExactLiveSupport() {
  const liveSupport = currentResourceLiveSupport();
  return liveSupport?.evaluated === true ? liveSupport : null;
}

function currentResourceLiveSupport() {
  const resource = valueOrNull("resource");
  if (!resource || state.resourceLiveSupportContext?.resource !== resource) return null;
  return state.resourceLiveSupport;
}

function selectedModelLiveSupport(name) {
  const model = selectedCommandModel();
  return model
    ? state.liveSupportByModel?.[model]?.commands?.[name] || null
    : modelIndependentLiveSupport(name);
}

function modelIndependentLiveSupport(name) {
  const models = Object.values(state.liveSupportByModel || {});
  if (!models.length) return null;
  const entries = models.map((model) => model?.commands?.[name]);
  if (entries.some((entry) => !entry)) return null;
  if (entries.every((entry) => entry.policy_exempt === true)) return entries[0];
  if (entries.every((entry) => entry.offline_only === true)) return entries[0];
  return null;
}

function commandMeta(name) {
  const meta = state.commands[name] || {};
  if (isNoHardwareMode()) {
    const identity = selectedPlanningIdentity();
    if (!identity) return {
      ...meta,
      disabled: true,
      disabled_reason: t("support.reason.select_planning_identity"),
      live_support_status: t("support.status.planning_identity_required")
    };
    if (identity.startsWith("profile:")) {
      const profile = state.planningProfiles?.[identity.slice("profile:".length)];
      const support = profile?.command_support?.[name];
      if (!support || support.dry_run !== true) {
        return {
          ...meta,
          disabled: true,
          disabled_reason: t("support.reason.planning_profile_unsupported")
        };
      }
      return {
        ...meta,
        live_support_status: t("support.status.dry_run_planning_profile"),
        requires_confirm: false
      };
    }
    const support = state.commandSupportByModel?.[identity]?.[name];
    const supported = state.executionMode === "simulate" ? support?.simulate : support?.dry_run;
    if (supported !== true) {
      return {
        ...meta,
        disabled: true,
        disabled_reason: t("support.reason.model_mode_unsupported", {
          model: physicalModelDisplayName(identity),
          mode: state.executionMode
        })
      };
    }
    return {
      ...meta,
      live_support_status: t(state.executionMode === "simulate"
        ? "support.status.simulation_supported"
        : "support.status.dry_run_supported"),
      requires_confirm: false
    };
  }
  const support = selectedCommandSupport(name);
  const modelSupport = selectedModelLiveSupport(name);
  let effective = { ...meta };
  if (support?.real === false || (modelSupport && !modelSupport.profile_supported && !modelSupport.policy_exempt)) {
    const unsupportedModel = modelSupport?.profile_validation_status === "not_supported_by_model";
    effective = {
      ...effective,
      disabled: true,
      disabled_reason: unsupportedModel
        ? t("support.status.not_supported_by_model", {
          model: physicalModelDisplayName(selectedCommandModel())
        })
        : modelSupport?.disabled_reason
          || meta.disabled_reason
          || commandDisabledReason(support, selectedCommandModel())
    };
  }
  const resourceSupport = currentResourceLiveSupport();
  if (resourceSupport?.evaluated === false) {
    const unavailable = unresolvedLiveSupportText(resourceSupport);
    if (modelSupport?.policy_exempt || modelSupport?.offline_only) {
      return {
        ...effective,
        disabled: false,
        disabled_reason: null,
        live_support_status: localizedKnownSupportReason(modelSupport.support_reason) || unavailable
      };
    }
    return {
      ...effective,
      disabled: true,
      disabled_reason: unavailable,
      live_support_status: unavailable
    };
  }
  const exactSupport = currentExactLiveSupport();
  if (!exactSupport) {
    effective.live_support_status = modelSupport?.policy_exempt
      ? localizedKnownSupportReason(modelSupport.support_reason)
      : t("support.scope.not_evaluated");
    return effective;
  }
  const exactCommand = exactSupport.commands?.[name];
  if (!exactCommand) {
    return {
      ...effective,
      disabled: true,
      disabled_reason: t("support.reason.missing_live_metadata"),
      live_support_status: t("support.reason.missing_live_metadata")
    };
  }
  effective.live_support_status = exactCommandSupportText(exactCommand, exactSupport);
  if (!exactCommand.policy_exempt && exactCommand.product_open !== true) {
    effective.disabled = true;
    effective.disabled_reason = hasMaintainedExactSupportStatus(exactCommand)
      ? effective.live_support_status
      : exactCommand.disabled_reason || effective.live_support_status;
  }
  return effective;
}

function exactCommandSupportText(commandSupport, liveSupport) {
  if (commandSupport.offline_only) {
    return t("support.status.offline_utility");
  }
  if (commandSupport.policy_exempt) {
    return t("support.status.identity_diagnostic");
  }
  const scope = `${transportScopeLabel(liveSupport.transport_scope)} / ${backendScopeLabel(liveSupport.backend_scope)}`;
  if (commandSupport.exact_scope_validation_status === "live_validated_full_suite") {
    return t("support.status.live_validated", { scope });
  }
  if (["transport_pending", "feature_pending"].includes(commandSupport.exact_scope_validation_status)) {
    return t("support.status.pending_live_validation", { scope });
  }
  if (commandSupport.profile_validation_status === "not_supported_by_model") {
    return t("support.status.not_supported_by_model", {
      model: liveSupport.display_name || liveSupport.model_name || liveSupport.model_id
    });
  }
  if (commandSupport.product_open === false && commandSupport.exact_scope_validation_status == null) {
    return t("support.status.no_product_open_scope", { scope });
  }
  return localizedKnownSupportReason(commandSupport.disabled_reason)
    || t("support.status.no_product_open_scope", { scope });
}

function hasMaintainedExactSupportStatus(commandSupport) {
  return Boolean(
    commandSupport.offline_only
    || commandSupport.policy_exempt
    || commandSupport.profile_validation_status === "not_supported_by_model"
    || ["live_validated_full_suite", "transport_pending", "feature_pending"].includes(commandSupport.exact_scope_validation_status)
    || (commandSupport.product_open === false && commandSupport.exact_scope_validation_status == null)
  );
}

function selectedCommandSupport(name) {
  const model = selectedCommandModel();
  if (!model) return null;
  return state.commandSupportByModel?.[model]?.[name] || null;
}

function currentResourceModel() {
  const resource = valueOrNull("resource");
  if (!resource) return null;
  return detectedCommandModelForResource(resource);
}

function supportedModelKey(model) {
  const modelId = String(model || "").trim();
  return state.commandSupportByModel[modelId] ? modelId : null;
}

function commandDisabledReason(support, model) {
  const validation = support?.hardware_validation;
  const displayModel = physicalModelDisplayName(model);
  if (validation === "planning_only") return t("support.reason.planning_only", { model: displayModel });
  if (validation === "not_supported_by_model") return t("support.reason.not_supported", { model: displayModel });
  return t("support.reason.unavailable", { model: displayModel });
}

function localizedKnownSupportReason(reason) {
  const keys = {
    "Offline utility; live exact scope is not applicable.": "support.status.offline_utility",
    "Identity/status diagnostic; exact model feature scope is not required.": "support.status.identity_diagnostic",
    "Live support metadata is missing for this command.": "support.reason.missing_live_metadata"
  };
  return keys[reason] ? t(keys[reason]) : reason;
}

function exactSupportContextSummary(resource) {
  if (!resource) return t("support.scope.not_evaluated");
  const resourceSupport = currentResourceLiveSupport();
  if (resourceSupport?.evaluated === false) return unresolvedLiveSupportText(resourceSupport);
  const liveSupport = currentExactLiveSupport();
  if (!liveSupport) return t("support.scope.not_evaluated");
  return liveSupportSummary(liveSupport);
}

function liveSupportSummary(liveSupport) {
  if (!liveSupport) return t("support.scope.not_evaluated");
  if (liveSupport.evaluated === false) return unresolvedLiveSupportText(liveSupport);
  return `${transportScopeLabel(liveSupport.transport_scope)} / ${backendScopeLabel(liveSupport.backend_scope)}`;
}

function unresolvedLiveSupportText(liveSupport) {
  const knownReasons = new Set([
    "The reported manufacturer and model do not resolve to active exact live-support metadata."
  ]);
  const reason = typeof liveSupport?.reason === "string" ? liveSupport.reason.trim() : "";
  if (reason && !knownReasons.has(reason)) return reason;
  const model = typeof liveSupport?.reported_model === "string"
    ? liveSupport.reported_model.trim()
    : "";
  return model
    ? t("support.scope.unresolved_model", { model })
    : t("support.scope.unresolved");
}

function transportScopeLabel(scope) {
  return ({ usb: "USB", tcpip: "TCPIP", asrl: "ASRL", gpib: "GPIB", unknown: "Unknown transport" })[scope] || "--";
}

function backendScopeLabel(scope) {
  return ({ system_visa: "system VISA", pyvisa_py: "pyvisa-py", custom_visa: "custom VISA" })[scope] || "--";
}

function supportedChannelsForCurrentModel() {
  const capability = channelCapabilityForCurrentModel();
  if (!capability || !capability.channels.length) return [...defaultChannels];
  return [...capability.channels];
}

function isChannelSupported(channel) {
  if (!isNumericChannel(channel)) return true;
  return supportedChannelsForCurrentModel().includes(Number(channel));
}

function isNumericChannel(channel) {
  return /^[1-9]\d*$/.test(String(channel));
}

function channelUnsupportedReason(channel) {
  if (isChannelSupported(channel)) return "";
  const model = currentChannelCapabilityModel();
  return model
    ? t("support.reason.channel_unsupported", {
      model: physicalModelDisplayName(model),
      channel
    })
    : "";
}

function channelCapabilityForCurrentModel() {
  return channelCapabilityForModel(currentChannelCapabilityModel());
}

function channelCapabilityForModel(model) {
  const modelId = String(model || "").trim();
  if (!modelId) return null;
  const metadata = state.channelCapabilitiesByModel?.[modelId];
  if (Array.isArray(metadata)) {
    return {
      channels: metadata.map(Number).filter(Number.isInteger),
      output_control_scope: "unknown"
    };
  }
  if (!metadata || typeof metadata !== "object") return null;
  const channels = Array.isArray(metadata.channels)
    ? metadata.channels.map(Number).filter(Number.isInteger)
    : [];
  return {
    channels,
    output_control_scope: typeof metadata.output_control_scope === "string" ? metadata.output_control_scope : "unknown"
  };
}

function currentChannelCapabilityModel() {
  return selectedChannelModel();
}

function channelModelKey(model) {
  const modelId = String(model || "").trim();
  return channelCapabilityForModel(modelId) ? modelId : null;
}

function channelAvailabilityGuardReason(command, parameters = {}) {
  const channels = selectedChannelsForCommand(command, parameters);
  const unsupported = channels.find((channel) => !isChannelSupported(channel));
  return unsupported === undefined ? "" : channelUnsupportedReason(unsupported);
}

function selectedChannelsForCommand(command, parameters = {}) {
  if (command === "ramp-list") {
    return [...new Set((parameters.document?.segments || []).map((segment) => Number(segment.channel)).filter(Number.isInteger))];
  }
  if (command === "trigger-list") return [Number(parameters.channel)].filter(Number.isInteger);
  if (command === "ramp" && Array.isArray(parameters.channels)) {
    return parameters.channels.map(Number).filter(Number.isInteger);
  }
  if (command === "sequence") {
    return [...new Set((parameters.document?.steps || [])
      .map((step) => step.channel)
      .filter((channel) => channel !== undefined && channel !== "all")
      .map(Number)
      .filter(Number.isInteger))];
  }
  const selected = parameters.channel;
  if (selected === undefined || selected === null || selected === "" || selected === "all") return [];
  const channel = Number(selected);
  return Number.isInteger(channel) ? [channel] : [];
}

function outputControlTitle(channel, enabled, fresh) {
  const base = t(fresh
    ? enabled
      ? "basic_controls.tooltip.channel_output_on"
      : "basic_controls.tooltip.channel_output_off"
    : "basic_controls.tooltip.channel_output_unknown", { channel });
  return outputControlScopeForCurrentModel() === "global" ? `${base} ${globalOutputHintText()}` : base;
}

function outputAllControlTitle(allOn) {
  const base = t(allOn
    ? "basic_controls.tooltip.all_outputs_on"
    : "basic_controls.tooltip.outputs_off_or_unknown");
  return outputControlScopeForCurrentModel() === "global" ? `${base} ${globalOutputHintText()}` : base;
}

function outputControlScopeForCurrentModel() {
  return channelCapabilityForCurrentModel()?.output_control_scope || "unknown";
}

function globalOutputHintText() {
  const model = currentChannelCapabilityModel();
  return model
    ? t("basic_controls.tooltip.global_output_model", { model: physicalModelDisplayName(model) })
    : t("basic_controls.tooltip.global_output");
}


  return {
    currentExactLiveSupport,
    selectedModelLiveSupport,
    commandMeta,
    exactCommandSupportText,
    selectedCommandSupport,
    currentResourceModel,
    supportedModelKey,
    commandDisabledReason,
    exactSupportContextSummary,
    liveSupportSummary,
    transportScopeLabel,
    backendScopeLabel,
    supportedChannelsForCurrentModel,
    isChannelSupported,
    isNumericChannel,
    channelUnsupportedReason,
    channelCapabilityForCurrentModel,
    channelCapabilityForModel,
    currentChannelCapabilityModel,
    channelModelKey,
    channelAvailabilityGuardReason,
    selectedChannelsForCommand,
    outputControlTitle,
    outputAllControlTitle,
    outputControlScopeForCurrentModel,
    globalOutputHintText
  };
}
