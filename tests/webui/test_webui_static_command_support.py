"""Direct behavior checks for command-support presentation helpers."""

from __future__ import annotations

from _webui_shared import read_static_javascript, read_static_texts, run_webui_module_assertions


def test_command_support_module_preserves_planning_and_channel_guards() -> None:
    _index_html, app_js, _styles_css = read_static_texts()
    command_support_js = read_static_javascript("command-support.js")

    assert 'from "./command-support.js"' in app_js
    assert "fetch(" not in command_support_js
    assert "EventSource" not in command_support_js

    run_webui_module_assertions(
        r"""
const state = {
  executionMode: "simulate",
  commands: {
    set: { description: "Set output" },
    identify: { description: "Read device information" }
  },
  planningProfiles: {},
  commandSupportByModel: { "model-a": { set: { simulate: true } } },
  channelCapabilitiesByModel: { "model-a": { channels: [1, 2], output_control_scope: "per_channel" } },
  liveSupportByModel: {},
  resourceLiveSupport: null,
  resourceLiveSupportContext: null
};
const i18n = await import(new URL("./i18n.js", moduleUrls["command-support.js"]));
let noHardware = true;
let planningIdentity = "model-a";
let selectedCommandModelId = "model-a";
const support = globalThis.webuiCommandSupport.createCommandSupport({
  state,
  defaultChannels: [1, 2, 3],
  isNoHardwareMode: () => noHardware,
  selectedPlanningIdentity: () => planningIdentity,
  physicalModelDisplayName: (model) => model,
  selectedCommandModel: () => selectedCommandModelId,
  valueOrNull: () => "RESOURCE-A",
  detectedCommandModelForResource: () => "model-a",
  selectedChannelModel: () => "model-a"
});
strictAssert.equal(support.commandMeta("set").disabled, undefined);
const enSimulationStatus = support.commandMeta("set").live_support_status;
strictAssert.notEqual(enSimulationStatus, "");
strictAssert.deepEqual(support.supportedChannelsForCurrentModel(), [1, 2]);
strictAssert.match(support.channelUnsupportedReason(3), /model-a.*3/);
strictAssert.match(support.channelAvailabilityGuardReason("set", { channel: "3" }), /model-a.*3/);
strictAssert.match(support.channelAvailabilityGuardReason("ramp", { channels: [1, 3] }), /model-a.*3/);
strictAssert.match(support.channelAvailabilityGuardReason("ramp-list", {
  document: { segments: [{ channels: [1, 3] }] }
}), /model-a.*3/);
strictAssert.equal(support.transportScopeLabel("tcpip"), "TCPIP");

i18n.setLocale("zh-TW");
strictAssert.notEqual(support.commandMeta("set").live_support_status, "");
strictAssert.notEqual(support.commandMeta("set").live_support_status, enSimulationStatus);
strictAssert.match(support.commandMeta("set").live_support_status, /模擬/);
strictAssert.match(support.channelUnsupportedReason(3), /model-a.*3/);
const zhSimulation = support.commandMeta("set");
strictAssert.equal(zhSimulation.disabled, undefined);

planningIdentity = null;
const required = support.commandMeta("set");
strictAssert.equal(required.disabled, true);
strictAssert.match(required.disabled_reason, /規劃識別/);
strictAssert.match(required.live_support_status, /規劃識別/);

planningIdentity = "profile:unsupported";
state.planningProfiles.unsupported = { command_support: {} };
strictAssert.match(support.commandMeta("set").disabled_reason, /規劃設定檔|指令/);
state.planningProfiles.unsupported.command_support.set = { dry_run: true };
strictAssert.match(support.commandMeta("set").live_support_status, /Dry-run|規劃/);

planningIdentity = "model-a";
state.executionMode = "dry_run";
state.commandSupportByModel["model-a"].set.dry_run = true;
strictAssert.match(support.commandMeta("set").live_support_status, /Dry-run/);
state.commandSupportByModel["model-a"].set.dry_run = false;
strictAssert.match(support.commandMeta("set").disabled_reason, /model-a|dry_run|指令/);

noHardware = false;
state.executionMode = "real";
state.liveSupportByModel["model-a"] = {
  commands: {
    set: { profile_supported: true, policy_exempt: false },
    identify: {
      profile_supported: true,
      policy_exempt: true,
      support_reason: "Identity/status diagnostic; exact model feature scope is not required."
    }
  }
};
state.liveSupportByModel["model-b"] = {
  commands: {
    set: { profile_supported: true, policy_exempt: false },
    identify: {
      profile_supported: true,
      policy_exempt: true,
      support_reason: "Identity/status diagnostic; exact model feature scope is not required."
    }
  }
};
strictAssert.notEqual(support.commandMeta("set").live_support_status, "");
strictAssert.equal(support.commandMeta("set").disabled, undefined);
strictAssert.notEqual(support.exactSupportContextSummary("RESOURCE-A"), "");
state.resourceLiveSupportContext = { resource: "RESOURCE-A" };
state.resourceLiveSupport = {
  evaluated: false,
  reported_model: "UNKNOWN-PSU",
  reason: "The reported manufacturer and model do not resolve to active exact live-support metadata.",
  commands: {}
};
selectedCommandModelId = null;
const unresolved = support.commandMeta("set");
strictAssert.equal(unresolved.disabled, true);
strictAssert.match(unresolved.live_support_status, /UNKNOWN-PSU/);
strictAssert.equal(unresolved.disabled_reason, unresolved.live_support_status);
strictAssert.equal(support.exactSupportContextSummary("RESOURCE-A"), unresolved.live_support_status);
strictAssert.doesNotMatch(unresolved.live_support_status, /尚未評估/);
const diagnostic = support.commandMeta("identify");
strictAssert.equal(diagnostic.disabled, false);
strictAssert.equal(diagnostic.disabled_reason, null);
strictAssert.match(diagnostic.live_support_status, /識別|狀態診斷/);
state.resourceLiveSupport = {
  evaluated: false,
  reported_model: null,
  reason: "The reported manufacturer and model do not resolve to active exact live-support metadata.",
  commands: {}
};
strictAssert.match(support.commandMeta("set").live_support_status, /實機支援範圍/);
state.resourceLiveSupport = {
  evaluated: false,
  reported_model: null,
  reason: "Future backend reason",
  commands: {}
};
strictAssert.equal(support.commandMeta("set").live_support_status, "Future backend reason");
selectedCommandModelId = "model-a";
state.resourceLiveSupport = { evaluated: true, commands: {} };
const missingMetadata = support.commandMeta("set");
strictAssert.equal(missingMetadata.disabled, true);
strictAssert.match(missingMetadata.live_support_status, /指令|實機支援|中繼資料/);
state.resourceLiveSupport.commands.set = {
  product_open: true,
  exact_scope_validation_status: "live_validated_full_suite"
};
const exactValidated = support.commandMeta("set");
strictAssert.equal(exactValidated.disabled, undefined);
strictAssert.match(exactValidated.live_support_status, /實機驗證/);
state.resourceLiveSupport = {
  evaluated: true,
  transport_scope: "asrl",
  backend_scope: "system_visa",
  commands: {
    set: { product_open: true, exact_scope_validation_status: "live_validated_full_suite" },
    identify: { product_open: true, policy_exempt: true },
    ramp: { product_open: false, exact_scope_validation_status: "feature_pending" }
  }
};
strictAssert.equal(support.exactSupportContextSummary("RESOURCE-A"), "ASRL / system VISA");
strictAssert.doesNotMatch(support.exactSupportContextSummary("RESOURCE-A"), /已驗證|待驗證|不可用/);
i18n.setLocale("en");
strictAssert.equal(support.exactSupportContextSummary("RESOURCE-A"), "ASRL / system VISA");
strictAssert.doesNotMatch(support.exactSupportContextSummary("RESOURCE-A"), /validated|pending|unavailable/i);
i18n.setLocale("zh-TW");
state.resourceLiveSupport = {
  evaluated: true,
  transport_scope: "usb",
  backend_scope: "system_visa",
  commands: {
    set: {
      product_open: false,
      exact_scope_validation_status: null,
      disabled_reason: "No product-open live scope is registered for USB / system VISA."
    }
  }
};
const noExactScopeZh = support.commandMeta("set");
strictAssert.equal(noExactScopeZh.disabled, true);
strictAssert.match(noExactScopeZh.live_support_status, /USB \/ system VISA/);
strictAssert.equal(noExactScopeZh.disabled_reason, noExactScopeZh.live_support_status);
strictAssert.doesNotMatch(noExactScopeZh.disabled_reason, /No product-open live scope/);
i18n.setLocale("en");
const noExactScopeEn = support.commandMeta("set");
strictAssert.match(noExactScopeEn.live_support_status, /USB \/ system VISA/);
strictAssert.equal(noExactScopeEn.disabled_reason, noExactScopeEn.live_support_status);
i18n.setLocale("zh-TW");
state.resourceLiveSupport.commands.set = {
  product_open: false,
  exact_scope_validation_status: "future_status",
  disabled_reason: "Backend raw future reason"
};
const futureExactStatus = support.commandMeta("set");
strictAssert.equal(futureExactStatus.disabled_reason, "Backend raw future reason");
strictAssert.equal(futureExactStatus.live_support_status, "Backend raw future reason");
state.resourceLiveSupport = null;
state.resourceLiveSupportContext = null;
state.liveSupportByModel["model-a"].commands.set = {
  profile_supported: false,
  policy_exempt: false,
  profile_validation_status: "not_supported_by_model",
  disabled_reason: "Backend model reason"
};
strictAssert.match(support.commandMeta("set").disabled_reason, /model-a|不支援/);
state.liveSupportByModel["model-a"].commands.set = {
  profile_supported: false,
  policy_exempt: false,
  profile_validation_status: "future_status",
  disabled_reason: "Backend raw future reason"
};
strictAssert.equal(support.commandMeta("set").disabled_reason, "Backend raw future reason");

const liveScope = {
  transport_scope: "usb",
  backend_scope: "system_visa",
  display_name: "Model A"
};
strictAssert.match(
  support.exactCommandSupportText({ exact_scope_validation_status: "live_validated_full_suite" }, liveScope),
  /USB \/ system VISA/,
);
strictAssert.match(
  support.exactCommandSupportText({ exact_scope_validation_status: "transport_pending" }, liveScope),
  /USB \/ system VISA/,
);
strictAssert.match(
  support.exactCommandSupportText({ profile_validation_status: "not_supported_by_model" }, liveScope),
  /Model A|不支援/,
);
strictAssert.match(
  support.exactCommandSupportText({ offline_only: true }, liveScope),
  /離線|實機/,
);
strictAssert.match(
  support.exactCommandSupportText({ policy_exempt: true }, liveScope),
  /識別|狀態診斷/,
);
strictAssert.equal(
  support.exactCommandSupportText({ disabled_reason: "Backend raw future reason" }, liveScope),
  "Backend raw future reason"
);
strictAssert.match(support.exactCommandSupportText({}, liveScope), /USB \/ system VISA/);

i18n.setLocale("en");
strictAssert.match(
  support.exactCommandSupportText({ exact_scope_validation_status: "live_validated_full_suite" }, liveScope),
  /Live validated: USB \/ system VISA/,
);
strictAssert.match(
  support.exactCommandSupportText({ exact_scope_validation_status: "feature_pending" }, liveScope),
  /Pending live validation: USB \/ system VISA/,
);
strictAssert.equal(
  support.exactCommandSupportText({ disabled_reason: "Backend raw future reason" }, liveScope),
  "Backend raw future reason"
);
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("command-support.js",),
    )
