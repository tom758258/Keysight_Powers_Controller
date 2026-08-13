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
strictAssert.equal(support.commandMeta("set").live_support_status, "Simulation supported");
strictAssert.deepEqual(support.supportedChannelsForCurrentModel(), [1, 2]);
strictAssert.equal(support.channelUnsupportedReason(3), "model-a does not support channel 3");
strictAssert.equal(support.channelAvailabilityGuardReason("set", { channel: "3" }), "model-a does not support channel 3");
strictAssert.equal(support.channelAvailabilityGuardReason("ramp", { channels: [1, 3] }), "model-a does not support channel 3");
strictAssert.equal(support.channelAvailabilityGuardReason("ramp-list", {
  document: { segments: [{ channels: [1, 3] }] }
}), "model-a does not support channel 3");
strictAssert.equal(support.transportScopeLabel("tcpip"), "TCPIP");

i18n.setLocale("zh-TW");
strictAssert.equal(support.commandMeta("set").live_support_status, "支援模擬");
strictAssert.equal(support.channelUnsupportedReason(3), "model-a 不支援通道 3");
const zhSimulation = support.commandMeta("set");
strictAssert.equal(zhSimulation.disabled, undefined);

planningIdentity = null;
const required = support.commandMeta("set");
strictAssert.equal(required.disabled, true);
strictAssert.equal(required.disabled_reason, "執行此指令前請先選取規劃識別。");
strictAssert.equal(required.live_support_status, "需要規劃識別。");

planningIdentity = "profile:unsupported";
state.planningProfiles.unsupported = { command_support: {} };
strictAssert.equal(
  support.commandMeta("set").disabled_reason,
  "此規劃設定檔不支援所選指令。"
);
state.planningProfiles.unsupported.command_support.set = { dry_run: true };
strictAssert.equal(support.commandMeta("set").live_support_status, "Dry-run 規劃設定檔");

planningIdentity = "model-a";
state.executionMode = "dry_run";
state.commandSupportByModel["model-a"].set.dry_run = true;
strictAssert.equal(support.commandMeta("set").live_support_status, "支援 Dry-run");
state.commandSupportByModel["model-a"].set.dry_run = false;
strictAssert.equal(
  support.commandMeta("set").disabled_reason,
  "model-a 不支援在 dry_run 模式執行此指令。"
);

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
strictAssert.equal(support.commandMeta("set").live_support_status, "尚未評估連線支援範圍");
strictAssert.equal(support.commandMeta("set").disabled, undefined);
strictAssert.equal(support.exactSupportContextSummary("RESOURCE-A"), "尚未評估連線支援範圍");
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
strictAssert.equal(
  unresolved.live_support_status,
  "已偵測到 UNKNOWN-PSU，但無法解析此資源的 Product-open 實機支援範圍。"
);
strictAssert.equal(unresolved.disabled_reason, unresolved.live_support_status);
strictAssert.equal(support.exactSupportContextSummary("RESOURCE-A"), unresolved.live_support_status);
strictAssert.doesNotMatch(unresolved.live_support_status, /尚未評估/);
const diagnostic = support.commandMeta("identify");
strictAssert.equal(diagnostic.disabled, false);
strictAssert.equal(diagnostic.disabled_reason, null);
strictAssert.equal(diagnostic.live_support_status, "識別／狀態診斷；不需要確切型號功能範圍。");
state.resourceLiveSupport = {
  evaluated: false,
  reported_model: null,
  reason: "The reported manufacturer and model do not resolve to active exact live-support metadata.",
  commands: {}
};
strictAssert.equal(
  support.commandMeta("set").live_support_status,
  "無法解析此資源的 Product-open 實機支援範圍。"
);
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
strictAssert.equal(missingMetadata.live_support_status, "缺少此指令的實機支援中繼資料。");
state.resourceLiveSupport.commands.set = {
  product_open: true,
  exact_scope_validation_status: "live_validated_full_suite"
};
const exactValidated = support.commandMeta("set");
strictAssert.equal(exactValidated.disabled, undefined);
strictAssert.equal(exactValidated.live_support_status, "已通過實機驗證：-- / --");
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
strictAssert.equal(noExactScopeZh.live_support_status, "USB / system VISA 尚未登錄 Product-open 實機範圍");
strictAssert.equal(noExactScopeZh.disabled_reason, noExactScopeZh.live_support_status);
strictAssert.doesNotMatch(noExactScopeZh.disabled_reason, /No product-open live scope/);
i18n.setLocale("en");
const noExactScopeEn = support.commandMeta("set");
strictAssert.equal(noExactScopeEn.live_support_status, "No Product-open live scope is registered for USB / system VISA");
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
strictAssert.equal(support.commandMeta("set").disabled_reason, "model-a 不支援");
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
strictAssert.equal(
  support.exactCommandSupportText({ exact_scope_validation_status: "live_validated_full_suite" }, liveScope),
  "已通過實機驗證：USB / system VISA"
);
strictAssert.equal(
  support.exactCommandSupportText({ exact_scope_validation_status: "transport_pending" }, liveScope),
  "待實機驗證：USB / system VISA"
);
strictAssert.equal(
  support.exactCommandSupportText({ profile_validation_status: "not_supported_by_model" }, liveScope),
  "Model A 不支援"
);
strictAssert.equal(
  support.exactCommandSupportText({ offline_only: true }, liveScope),
  "離線工具；不適用實機確切範圍。"
);
strictAssert.equal(
  support.exactCommandSupportText({ policy_exempt: true }, liveScope),
  "識別／狀態診斷；不需要確切型號功能範圍。"
);
strictAssert.equal(
  support.exactCommandSupportText({ disabled_reason: "Backend raw future reason" }, liveScope),
  "Backend raw future reason"
);
strictAssert.equal(
  support.exactCommandSupportText({}, liveScope),
  "USB / system VISA 尚未登錄 Product-open 實機範圍"
);

i18n.setLocale("en");
strictAssert.equal(
  support.exactCommandSupportText({ exact_scope_validation_status: "live_validated_full_suite" }, liveScope),
  "Live validated: USB / system VISA"
);
strictAssert.equal(
  support.exactCommandSupportText({ exact_scope_validation_status: "feature_pending" }, liveScope),
  "Pending live validation: USB / system VISA"
);
strictAssert.equal(
  support.exactCommandSupportText({ disabled_reason: "Backend raw future reason" }, liveScope),
  "Backend raw future reason"
);
strictAssert.equal("PowersToolWebUI" in globalThis, false);
""",
        ("command-support.js",),
    )
