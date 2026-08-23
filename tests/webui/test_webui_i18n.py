"""Pure native ES-module contracts for the WebUI i18n foundation."""

from __future__ import annotations

import shutil
import subprocess
import re
from pathlib import Path

import pytest

from powers_tool_core.parameter_constraints import parameter_constraints_metadata


REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "src" / "powers_tool_webui" / "static"
NODE = shutil.which("node")


def test_i18n_modules_use_the_existing_static_root_package_layout() -> None:
    expected = {
        STATIC_DIR / "i18n.js",
        STATIC_DIR / "dom_i18n.js",
        STATIC_DIR / "locale_en.js",
        STATIC_DIR / "locale_zh_tw.js",
        STATIC_DIR / "locale_ui.js",
    }

    assert all(path.is_file() for path in expected)
    assert not (STATIC_DIR / "locales").exists()
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"static/*.js"' in pyproject
    app_source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert 'import { applyStaticTranslations } from "./dom_i18n.js";' in app_source
    assert "applyStaticTranslations(document);" in app_source


@pytest.mark.skipif(NODE is None, reason="Node.js is required for ES-module runtime tests")
def test_locale_ui_resolution_persistence_and_button_contract() -> None:
    script = r"""
import assert from "node:assert/strict";

const [localeUiUrl, i18nUrl] = process.argv.slice(1);
const localeUi = await import(localeUiUrl);
const i18n = await import(i18nUrl);

for (const [language, expected] of [
  ["zh-TW", "zh-TW"],
  ["ZH_tw", "zh-TW"],
  ["zh-TW-x-private", "zh-TW"],
  ["zh-Hant", "zh-TW"],
  ["ZH_hAnT-HK", "zh-TW"],
  ["zh-CN", "en"],
  ["zh-Hans-TW", "en"],
  ["en-US", "en"],
  ["", "en"],
  [null, "en"],
]) {
  assert.equal(localeUi.browserLocale(language), expected);
}
assert.equal(localeUi.normalizeBrowserLanguage(" ZH_hAnT-TW "), "zh-hant-tw");

assert.equal(localeUi.detectBrowserLocale({ languages: ["", "zh-Hant-HK"], language: "en-US" }), "zh-TW");
assert.equal(localeUi.detectBrowserLocale({ languages: ["en-US", "zh-TW"], language: "zh-TW" }), "en");
assert.equal(localeUi.detectBrowserLocale({ languages: [], language: "zh_TW" }), "zh-TW");
assert.equal(localeUi.detectBrowserLocale({ languages: [null, "  "], language: "" }), "en");
assert.equal(localeUi.detectBrowserLocale(Object.defineProperty({}, "languages", {
  get() { throw new Error("navigator blocked"); },
})), "en");

function storageWith(value) {
  return {
    writes: [],
    getItem(key) {
      assert.equal(key, i18n.LOCALE_STORAGE_KEY);
      return value;
    },
    setItem(key, locale) {
      this.writes.push([key, locale]);
    },
  };
}
for (const valid of ["en", "zh-TW"]) {
  assert.equal(localeUi.readSavedLocale(storageWith(valid)), valid);
}
for (const invalid of ["EN", "zh-tw", "zh_TW", " zh-TW ", "", null, undefined]) {
  assert.equal(localeUi.readSavedLocale(storageWith(invalid)), null);
}
assert.equal(localeUi.readSavedLocale({ getItem() { throw new Error("read denied"); } }), null);
assert.equal(
  localeUi.resolveInitialLocale({
    storage: storageWith("en"),
    navigatorObject: { languages: ["zh-TW"] },
  }),
  "en"
);
assert.equal(
  localeUi.resolveInitialLocale({
    storage: storageWith("invalid"),
    navigatorObject: { languages: ["zh-Hant-TW"] },
  }),
  "zh-TW"
);
assert.equal(localeUi.persistLocale("zh-TW", { setItem() { throw new Error("write denied"); } }), false);

class FakeElement {
  constructor() {
    this.attributes = {};
    this.textContent = "";
  }
  setAttribute(name, value) { this.attributes[name] = value; }
}

class FakeButton extends FakeElement {
  constructor(label = new FakeElement()) {
    super();
    this.listeners = [];
    this.label = label;
  }
  querySelector(selector) {
    assert.equal(selector, "#locale-toggle-label");
    return this.label;
  }
  addEventListener(type, listener) { this.listeners.push({ type, listener }); }
  click() { this.listeners.filter(({ type }) => type === "click").forEach(({ listener }) => listener()); }
}

const button = new FakeButton();
const label = button.label;
const documentObject = {
  documentElement: { lang: "en" },
  getElementById(id) {
    assert.equal(id, "locale-toggle");
    return button;
  },
};
const storage = storageWith("zh-TW");
let refreshes = 0;
assert.equal(localeUi.initializeLocaleUi({
  documentObject,
  navigatorObject: { languages: ["en-US"] },
  storage,
  refreshPresentation() { refreshes += 1; },
}), "zh-TW");
assert.equal(i18n.getLocale(), "zh-TW");
assert.equal(documentObject.documentElement.lang, "zh-TW");
assert.equal(label.textContent, i18n.t("locale.display_zh_tw"));
assert.equal(label.attributes.lang, "zh-TW");
assert.equal(label.attributes["data-i18n"], "locale.display_zh_tw");
assert.equal(button.attributes["aria-label"], i18n.t("accessibility.switch_language_to_en"));
assert.equal(button.attributes["data-i18n-aria-label"], "accessibility.switch_language_to_en");
assert.equal(button.attributes.title, i18n.t("accessibility.switch_language_to_en"));
assert.equal(button.attributes["data-i18n-title"], "accessibility.switch_language_to_en");
assert.equal(button.listeners.length, 1);

localeUi.initializeLocaleUi({
  documentObject,
  navigatorObject: { languages: ["en-US"] },
  storage,
  refreshPresentation() { refreshes += 100; },
});
assert.equal(button.listeners.length, 1);
assert.equal(i18n.getLocale(), "zh-TW");

button.click();
assert.equal(i18n.getLocale(), "en");
assert.equal(documentObject.documentElement.lang, "en");
assert.equal(label.textContent, i18n.t("locale.display_en"));
assert.equal(label.attributes.lang, "en");
assert.equal(label.attributes["data-i18n"], "locale.display_en");
assert.equal(button.attributes["aria-label"], i18n.t("accessibility.switch_language_to_zh_tw"));
assert.equal(button.attributes["data-i18n-aria-label"], "accessibility.switch_language_to_zh_tw");
assert.equal(button.attributes.title, i18n.t("accessibility.switch_language_to_zh_tw"));
assert.equal(button.attributes["data-i18n-title"], "accessibility.switch_language_to_zh_tw");
assert.deepEqual(storage.writes, [[i18n.LOCALE_STORAGE_KEY, "en"]]);
assert.equal(refreshes, 1);

const failingButton = new FakeButton();
const failingDocument = {
  documentElement: { lang: "en" },
  getElementById() { return failingButton; },
};
localeUi.initializeLocaleUi({
  documentObject: failingDocument,
  navigatorObject: { language: "en" },
  storage: {
    getItem() { throw new Error("read denied"); },
    setItem() { throw new Error("write denied"); },
  },
  refreshPresentation() { refreshes += 1; },
});
assert.equal(i18n.getLocale(), "en");
assert.equal(failingDocument.documentElement.lang, "en");
assert.equal(failingButton.label.textContent, i18n.t("locale.display_en"));
assert.equal(failingButton.label.attributes.lang, "en");
assert.equal(
  failingButton.attributes["aria-label"],
  i18n.t("accessibility.switch_language_to_zh_tw")
);
failingButton.click();
assert.equal(i18n.getLocale(), "zh-TW");
assert.equal(failingDocument.documentElement.lang, "zh-TW");
assert.equal(failingButton.label.textContent, i18n.t("locale.display_zh_tw"));
assert.equal(failingButton.label.attributes.lang, "zh-TW");
assert.equal(failingButton.attributes["aria-label"], i18n.t("accessibility.switch_language_to_en"));
assert.equal(refreshes, 2);
"""
    completed = subprocess.run(
        [
            NODE,
            "--input-type=module",
            "--eval",
            script,
            (STATIC_DIR / "locale_ui.js").resolve().as_uri(),
            (STATIC_DIR / "i18n.js").resolve().as_uri(),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


@pytest.mark.skipif(NODE is None, reason="Node.js is required for ES-module runtime tests")
def test_i18n_es_module_runtime_contract() -> None:
    script = r"""
import assert from "node:assert/strict";

const [i18nUrl, enUrl, zhTwUrl] = process.argv.slice(1);
const guardedGlobals = [
  "document",
  "window",
  "navigator",
  "localStorage",
  "fetch",
  "XMLHttpRequest",
  "EventSource",
];
const globalAccesses = [];
for (const name of guardedGlobals) {
  Object.defineProperty(globalThis, name, {
    configurable: true,
    get() {
      globalAccesses.push(name);
      throw new Error(`unexpected global access: ${name}`);
    },
  });
}

const i18n = await import(i18nUrl);
const enModule = await import(enUrl);
const zhTwModule = await import(zhTwUrl);
const { EN_MESSAGES } = enModule;
const { ZH_TW_MESSAGES } = zhTwModule;

assert.equal(i18n.SOURCE_LOCALE, "en");
assert.equal(i18n.FALLBACK_LOCALE, "en");
assert.deepEqual(i18n.SUPPORTED_LOCALES, ["en", "zh-TW"]);
assert.equal(i18n.LOCALE_STORAGE_KEY, "powers-tool.webui.locale");
assert.equal(Object.isFrozen(i18n.SUPPORTED_LOCALES), true);
assert.equal(Object.isFrozen(EN_MESSAGES), true);
assert.equal(Object.isFrozen(ZH_TW_MESSAGES), true);
assert.equal(enModule.default, EN_MESSAGES);
assert.equal(zhTwModule.default, ZH_TW_MESSAGES);
assert.deepEqual(Object.keys(EN_MESSAGES), Object.keys(ZH_TW_MESSAGES));
assert.equal(Object.keys(EN_MESSAGES).length > 0, true);
for (const catalog of [EN_MESSAGES, ZH_TW_MESSAGES]) {
  for (const message of Object.values(catalog)) {
    assert.equal(typeof message, "string");
    assert.equal(message.length > 0, true);
  }
}
const maintainedCommandDescriptions = [
  "apply", "capabilities", "clear", "clear_protection", "cycle_output", "doctor",
  "error", "hardware_report", "identify", "list_resources", "log", "measure",
  "measure_all", "output_off", "output_on", "output_state", "protection_set",
  "protection_status", "ramp", "ramp_list", "readback", "read_status",
  "restore_from_snapshot", "safe_off", "safety_inspect", "sequence", "set",
  "smoke_output", "snapshot", "snapshot_diff", "trigger_abort", "trigger_fire",
  "trigger_list", "trigger_pulse", "trigger_status", "trigger_step", "validate_readonly",
  "verify",
];
for (const command of maintainedCommandDescriptions) {
  for (const catalog of [EN_MESSAGES, ZH_TW_MESSAGES]) {
    assert.equal(typeof catalog[`command.description.${command}`], "string", command);
    assert.equal(catalog[`command.description.${command}`].length > 0, true, command);
  }
}
assert.deepEqual(
  Object.keys(EN_MESSAGES)
    .filter((key) => key.startsWith("command.description."))
    .map((key) => key.slice("command.description.".length))
    .sort(),
  [...maintainedCommandDescriptions].sort()
);
const maintainedCommandGuardMessages = [
  "command.guard.electrical_current",
  "command.guard.electrical_voltage",
  "command.guard.protection_trip",
  "command.guard.pulse_expected_model",
  "command.guard.pulse_no_model",
  "command.guard.pulse_unknown_model",
  "command.guard.pulse_unsupported_model",
  "command.guard.set_requires_setpoint",
  "command.guard.trigger_bus_wait_requires_fire",
  "command.guard.trigger_fire_wait_requires_channel",
  "command.guard.trigger_immediate_fire",
  "command.guard.trigger_list_arm_requires_leave",
  "command.guard.trigger_list_pulse_requires_pins",
  "command.guard.trigger_list_started_requires_leave",
  "command.tooltip.trigger_immediate_fire",
  "command.warning.protection_trip",
];
for (const key of maintainedCommandGuardMessages) {
  assert.equal(typeof EN_MESSAGES[key], "string", key);
  assert.equal(typeof ZH_TW_MESSAGES[key], "string", key);
}
assert.deepEqual(
  Object.keys(EN_MESSAGES)
    .filter((key) => key.startsWith("command.guard.") || key.startsWith("command.tooltip.") || key.startsWith("command.warning."))
    .sort(),
  [...maintainedCommandGuardMessages].sort()
);
    const maintainedFieldDescriptions = [
      "form.description.ramp.enable_output",
  "form.description.safe_off.channel",
  "form.description.sequence.trigger_pulse.leave_trigger_configured",
  "form.description.snapshot.max_errors",
  "form.description.trigger_abort.channel",
  "form.description.trigger_abort.max_errors",
  "form.description.trigger_fire.channel",
  "form.description.trigger_fire.poll_ms",
  "form.description.trigger_fire.wait_complete",
  "form.description.trigger_fire.wait_timeout_ms",
  "form.description.trigger_list.channel",
  "form.description.trigger_list.completion_pulse_pins",
  "form.description.trigger_list.count",
  "form.description.trigger_list.current_list",
  "form.description.trigger_list.dwell_list",
  "form.description.trigger_list.exclusive_pins",
  "form.description.trigger_list.fire",
  "form.description.trigger_list.leave_trigger_configured",
  "form.description.trigger_list.poll_ms",
  "form.description.trigger_list.source",
  "form.description.trigger_list.voltage_list",
  "form.description.trigger_list.wait_complete",
  "form.description.trigger_list.wait_timeout_ms",
  "form.description.trigger_pulse.exclusive_pins",
  "form.description.trigger_pulse.pins",
  "form.description.trigger_status.channel",
  "form.description.trigger_step.channel",
  "form.description.trigger_step.fire",
  "form.description.trigger_step.leave_trigger_configured",
  "form.description.trigger_step.poll_ms",
  "form.description.trigger_step.source",
  "form.description.trigger_step.wait_complete",
  "form.description.trigger_step.wait_timeout_ms",
];
for (const key of maintainedFieldDescriptions) {
  assert.equal(typeof EN_MESSAGES[key], "string", key);
  assert.equal(typeof ZH_TW_MESSAGES[key], "string", key);
}
assert.deepEqual(
  Object.keys(EN_MESSAGES).filter((key) => key.startsWith("form.description.")).sort(),
  [...maintainedFieldDescriptions].sort()
);
assert.equal(EN_MESSAGES["app.document_title"], "Powers Tool WebUI");
assert.equal(ZH_TW_MESSAGES["app.brand"], "Powers Tool");
assert.match(ZH_TW_MESSAGES["resource.visa_resource"], /^VISA /);
assert.equal(ZH_TW_MESSAGES["execution_mode.option.real"], "實機（Real）");
assert.equal(ZH_TW_MESSAGES["execution_mode.option.simulate"], "模擬（Simulate）");
assert.equal(ZH_TW_MESSAGES["execution_mode.option.dry_run"], "Dry-run（規劃）");
assert.equal(ZH_TW_MESSAGES["command.name.ramp"], "單段逐步輸出");
assert.equal(ZH_TW_MESSAGES["command.name.ramp_list"], "多段逐步輸出");
assert.equal(ZH_TW_MESSAGES["command.name.cycle_output"], "短暫開啟輸出");
assert.equal(ZH_TW_MESSAGES["command.name.smoke_output"], "輸出測試");
assert.equal(ZH_TW_MESSAGES["command.name.sequence"], "序列");
assert.equal(ZH_TW_MESSAGES["command.name.trigger_step"], "STEP 觸發");
assert.equal(EN_MESSAGES["command.name.ramp"], "Ramp");
assert.equal(EN_MESSAGES["command.name.ramp_list"], "Ramp list");
assert.equal(EN_MESSAGES["command.name.cycle_output"], "Cycle output");
assert.equal(EN_MESSAGES["command.name.smoke_output"], "Smoke output");
for (const catalog of [EN_MESSAGES, ZH_TW_MESSAGES]) {
  for (const key of [
    "command.description.ramp",
    "command.description.ramp_list",
    "command.description.cycle_output",
    "command.description.smoke_output",
    "ramp.help.multi_channel",
    "workflow.action.add_ramp_segment",
    "workflow.ramp_segment",
    "form.field.delay_ms",
    "workflow.field.delay_ms",
    "workflow.field.hold_ms",
    "workflow.field.enable_each_channel",
    "ramp_list.aria.enable_each_channel",
    "ramp_list.help.enable_each_channel",
    "form.option.segment",
    "support.scope.not_evaluated",
    "live_data.status.not_monitoring",
    "live_data.status.no_resource",
    "form.field.max_errors",
    "form.description.snapshot.max_errors",
    "health.device.busy",
    "basic_controls.heading",
  ]) {
    assert.equal(typeof catalog[key], "string", key);
    assert.equal(catalog[key].length > 0, true, key);
  }
}
assert.match(EN_MESSAGES["ramp_list.help.enable_each_channel"], /OUTPUT/i);
assert.match(EN_MESSAGES["ramp_list.help.enable_each_channel"], /safe/i);
assert.match(EN_MESSAGES["ramp_list.help.enable_each_channel"], /Real hardware/i);
assert.match(EN_MESSAGES["ramp_list.help.enable_each_channel"], /Stop/i);
assert.match(ZH_TW_MESSAGES["ramp_list.help.enable_each_channel"], /OUTPUT/);
assert.match(ZH_TW_MESSAGES["ramp_list.help.enable_each_channel"], /安全/);
assert.match(ZH_TW_MESSAGES["ramp_list.help.enable_each_channel"], /實機硬體/);
assert.match(ZH_TW_MESSAGES["ramp_list.help.enable_each_channel"], /Stop|停止|安全關閉/);
assert.match(EN_MESSAGES["form.description.snapshot.max_errors"], /snapshot/i);
assert.match(EN_MESSAGES["form.description.snapshot.max_errors"], /instrument/i);
assert.match(EN_MESSAGES["form.description.snapshot.max_errors"], /error/i);
assert.match(ZH_TW_MESSAGES["form.description.snapshot.max_errors"], /快照/);
assert.match(ZH_TW_MESSAGES["form.description.snapshot.max_errors"], /儀器/);
assert.match(ZH_TW_MESSAGES["form.description.snapshot.max_errors"], /錯誤/);
assert.match(EN_MESSAGES["health.device.busy"], /\{job\}/);
assert.match(ZH_TW_MESSAGES["health.device.busy"], /\{job\}/);
assert.match(EN_MESSAGES["form.description.ramp.enable_output"], /OUTPUT/i);
assert.match(EN_MESSAGES["form.description.ramp.enable_output"], /safe/i);
assert.match(EN_MESSAGES["form.description.ramp.enable_output"], /Real hardware/i);
assert.match(EN_MESSAGES["form.description.ramp.enable_output"], /Stop/i);
assert.match(ZH_TW_MESSAGES["form.description.ramp.enable_output"], /輸出/);
assert.match(ZH_TW_MESSAGES["form.description.ramp.enable_output"], /安全/);
assert.match(ZH_TW_MESSAGES["form.description.ramp.enable_output"], /實機硬體/);
assert.match(ZH_TW_MESSAGES["form.description.ramp.enable_output"], /停止|安全關閉/);

assert.equal(i18n.getLocale(), "en");
assert.equal(i18n.setLocale("zh-TW"), "zh-TW");
assert.equal(i18n.getLocale(), "zh-TW");
assert.throws(() => i18n.setLocale("ZH-tw"), RangeError);
assert.equal(i18n.getLocale(), "zh-TW");
assert.equal(i18n.setLocale("en"), "en");

for (const value of ["en", "zh-TW"]) {
  assert.equal(i18n.isSupportedLocale(value), true);
}
for (const value of ["", "EN", "zh-tw", "zh-Hant", null, undefined, 1, {}]) {
  assert.equal(i18n.isSupportedLocale(value), false);
}

const enCatalog = {
  "test.greeting": "Hello {name}",
  "test.count": "Captured {count} samples; {count} total",
  "test.fallback": "English fallback",
  "test.undefined": "Value {value}",
  "test.literal": "Content {value}",
};
const zhTwCatalog = {
  "test.greeting": "Traditional Chinese {name}",
  "test.count": "Count {count}; repeated {count}",
  "test.undefined": "Value {value}",
  "test.literal": "Literal {value}",
};
const catalogs = { en: enCatalog, "zh-TW": zhTwCatalog };
const before = JSON.stringify(catalogs);
const missing = [];
const translator = i18n.createI18n({
  catalogs,
  initialLocale: "zh-TW",
  onMissingKey(info) {
    missing.push(info);
  },
});

assert.equal(translator.getLocale(), "zh-TW");
assert.equal(translator.t("test.greeting", { name: "Ada" }), "Traditional Chinese Ada");
assert.equal(translator.t("test.fallback"), "English fallback");
assert.equal(translator.t("test.missing"), "test.missing");
assert.equal(translator.t("test.raw", undefined, "backend detail"), "backend detail");
assert.deepEqual(missing, [
  { key: "test.missing", locale: "zh-TW", fallbackLocale: "en" },
  { key: "test.raw", locale: "zh-TW", fallbackLocale: "en" },
]);

assert.equal(
  translator.t("test.count", { count: 3, extra: "ignored" }),
  "Count 3; repeated 3"
);
assert.equal(translator.t("test.greeting", {}), "Traditional Chinese {name}");
assert.equal(translator.t("test.undefined", { value: undefined }), "Value {value}");
const inheritedParams = Object.create({ name: "prototype value" });
assert.equal(translator.t("test.greeting", inheritedParams), "Traditional Chinese {name}");
const html = "<img src=x onerror=alert(1)>";
assert.equal(translator.t("test.literal", { value: html }), `Literal ${html}`);

assert.equal(translator.setLocale("en"), "en");
assert.equal(translator.t("test.greeting", { name: 7 }), "Hello 7");
assert.throws(() => translator.setLocale("fr"), RangeError);
assert.equal(translator.getLocale(), "en");
assert.equal(JSON.stringify(catalogs), before);
assert.equal(Object.isFrozen(enCatalog), false);
assert.equal(Object.isFrozen(zhTwCatalog), false);

const callerOwned = {
  en: { "test.copy": "Original English" },
  "zh-TW": { "test.copy": "Original zh-TW" },
};
const copied = i18n.createI18n({ catalogs: callerOwned, initialLocale: "zh-TW" });
callerOwned.en["test.copy"] = "Changed English";
callerOwned["zh-TW"]["test.copy"] = "Changed zh-TW";
assert.equal(copied.t("test.copy"), "Original zh-TW");
copied.setLocale("en");
assert.equal(copied.t("test.copy"), "Original English");

const second = i18n.createI18n({ catalogs });
assert.equal(second.getLocale(), "en");
assert.equal(second.setLocale("zh-TW"), "zh-TW");
assert.equal(translator.getLocale(), "en");

const callbackFailure = i18n.createI18n({
  catalogs: { en: {}, "zh-TW": {} },
  onMissingKey() { throw new Error("callback failed"); },
});
assert.equal(callbackFailure.t("test.unknown", undefined, "raw detail"), "raw detail");
assert.equal(callbackFailure.t("test.unknown"), "test.unknown");

Object.prototype["test.prototype"] = "inherited message";
try {
  assert.equal(translator.t("test.prototype"), "test.prototype");
} finally {
  delete Object.prototype["test.prototype"];
}

assert.throws(() => i18n.createI18n(), TypeError);
assert.throws(() => i18n.createI18n({ catalogs: [] }), TypeError);
assert.throws(() => i18n.createI18n({ catalogs: { en: {} } }), TypeError);
assert.throws(() => i18n.createI18n({ catalogs: { "zh-TW": {} } }), TypeError);
assert.throws(
  () => i18n.createI18n({ catalogs: { en: [], "zh-TW": {} } }),
  TypeError
);
assert.throws(
  () => i18n.createI18n({ catalogs: { en: { "test.bad": 1 }, "zh-TW": {} } }),
  TypeError
);
for (const key of ["bad", "Test.bad", "test.bad-key", "test..bad", "test.Bad"]) {
  assert.throws(
    () => i18n.createI18n({ catalogs: { en: { [key]: "value" }, "zh-TW": {} } }),
    TypeError
  );
  assert.throws(() => translator.t(key), TypeError);
}
assert.throws(
  () => i18n.createI18n({
    catalogs: { en: {}, "zh-TW": { "test.zh_only": "zh-TW only" } },
  }),
  /test\.zh_only.*zh-TW.*English source catalog/i
);
const englishOnly = i18n.createI18n({
  catalogs: { en: { "test.english_only": "English fallback" }, "zh-TW": {} },
  initialLocale: "zh-TW",
});
assert.equal(englishOnly.t("test.english_only"), "English fallback");
assert.throws(() => i18n.createI18n({ catalogs, initialLocale: "fr" }), RangeError);
assert.throws(() => i18n.createI18n({ catalogs, onMissingKey: true }), TypeError);

assert.deepEqual(globalAccesses, []);
process.stdout.write(JSON.stringify({ ok: true }));
"""
    completed = subprocess.run(
        [
            NODE,
            "--input-type=module",
            "--eval",
            script,
            (STATIC_DIR / "i18n.js").resolve().as_uri(),
            (STATIC_DIR / "locale_en.js").resolve().as_uri(),
            (STATIC_DIR / "locale_zh_tw.js").resolve().as_uri(),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, (
        f"Node i18n contract failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert completed.stdout == '{"ok":true}'


@pytest.mark.skipif(NODE is None, reason="Node.js is required for ES-module runtime tests")
def test_dom_i18n_applies_only_safe_static_bindings() -> None:
    script = r"""
import assert from "node:assert/strict";

const [domI18nUrl] = process.argv.slice(1);
const guardedGlobals = [
  "document",
  "window",
  "navigator",
  "localStorage",
  "fetch",
  "XMLHttpRequest",
  "EventSource",
];
const globalAccesses = [];
for (const name of guardedGlobals) {
  Object.defineProperty(globalThis, name, {
    configurable: true,
    get() {
      globalAccesses.push(name);
      throw new Error(`unexpected global access: ${name}`);
    },
  });
}

const { applyStaticTranslations } = await import(domI18nUrl);
assert.deepEqual(globalAccesses, []);

class FakeElement {
  constructor(attributes = {}) {
    this.attributes = { ...attributes };
    this.textContent = "English fallback";
    this.innerHTML = "unchanged markup";
    this.id = "protected-id";
    this.name = "protected-name";
    this.value = "protected-value";
  }

  getAttribute(name) {
    return Object.hasOwn(this.attributes, name) ? this.attributes[name] : null;
  }

  setAttribute(name, value) {
    this.attributes[name] = value;
  }
}

const textElement = new FakeElement({ "data-i18n": "test.text" });
const placeholderElement = new FakeElement({
  "data-i18n-placeholder": "test.placeholder",
  placeholder: "English placeholder",
});
const multiElement = new FakeElement({
  "data-i18n-title": "test.title",
  "data-i18n-aria-label": "test.aria",
  title: "English title",
  "aria-label": "English label",
  "aria-controls": "protected-controls",
  "aria-expanded": "true",
});
const maliciousElement = new FakeElement({ "data-i18n": "test.malicious" });
const elements = [textElement, placeholderElement, multiElement, maliciousElement];
const messages = {
  "test.text": "Translated text",
  "test.placeholder": "Translated placeholder",
  "test.title": "Translated title",
  "test.aria": "Translated label",
  "test.malicious": "<img src=x onerror=alert(1)>",
};
const root = {
  querySelectorAll(selector) {
    assert.equal(
      selector,
      "[data-i18n],[data-i18n-placeholder],[data-i18n-title],[data-i18n-aria-label]"
    );
    return elements;
  },
};

assert.equal(applyStaticTranslations(root, (key) => messages[key]), 5);
assert.equal(textElement.textContent, "Translated text");
assert.equal(placeholderElement.attributes.placeholder, "Translated placeholder");
assert.equal(multiElement.attributes.title, "Translated title");
assert.equal(multiElement.attributes["aria-label"], "Translated label");
assert.equal(maliciousElement.textContent, "<img src=x onerror=alert(1)>");
assert.equal(maliciousElement.innerHTML, "unchanged markup");
assert.equal(multiElement.id, "protected-id");
assert.equal(multiElement.name, "protected-name");
assert.equal(multiElement.value, "protected-value");
assert.equal(multiElement.attributes["aria-controls"], "protected-controls");
assert.equal(multiElement.attributes["aria-expanded"], "true");
assert.throws(() => applyStaticTranslations(null, () => "message"), TypeError);
assert.throws(() => applyStaticTranslations({}, () => "message"), TypeError);
assert.throws(() => applyStaticTranslations(root, null), TypeError);
assert.deepEqual(globalAccesses, []);
process.stdout.write(JSON.stringify({ ok: true }));
"""
    completed = subprocess.run(
        [
            NODE,
            "--input-type=module",
            "--eval",
            script,
            (STATIC_DIR / "dom_i18n.js").resolve().as_uri(),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, (
        f"Node DOM i18n contract failed\nstdout:\n{completed.stdout}"
        f"\nstderr:\n{completed.stderr}"
    )
    assert completed.stdout == '{"ok":true}'


@pytest.mark.skipif(NODE is None, reason="Node.js is required for ES-module runtime tests")
def test_device_options_static_translations_preserve_controls_and_state() -> None:
    script = r"""
import assert from "node:assert/strict";

const [domI18nUrl, i18nUrl] = process.argv.slice(1);
const { applyStaticTranslations } = await import(domI18nUrl);
const i18n = await import(i18nUrl);

class FakeElement {
  constructor(attributes = {}, textContent = "") {
    this.attributes = { ...attributes };
    this.textContent = textContent;
    this.value = "";
    this.checked = false;
    this.hidden = false;
    this.listeners = [];
  }

  getAttribute(name) {
    return Object.hasOwn(this.attributes, name) ? this.attributes[name] : null;
  }

  setAttribute(name, value) {
    this.attributes[name] = value;
  }

  addEventListener(type, listener) {
    this.listeners.push({ type, listener });
  }
}

const identityHelp = new FakeElement(
  { "data-i18n": "device.identity_model_help" },
  "Auto-detect uses the connected instrument IDN. Select a model only when you want to require a specific one. In live mode, the detected IDN model remains the runtime driver."
);
const writeText = new FakeElement(
  { "data-i18n": "device.enable_real_hardware_writes" },
  "Enable real hardware writes for this resource"
);
const expectedModel = new FakeElement();
expectedModel.value = "keysight-e36312a";
const writeCheckbox = new FakeElement();
writeCheckbox.checked = true;
const deviceOptionsPanel = new FakeElement();
deviceOptionsPanel.hidden = false;
const resource = new FakeElement();
resource.value = "USB0::TEST::INSTR";
const executionMode = new FakeElement();
executionMode.value = "real";
executionMode.checked = true;
const authorization = { resource: resource.value, enabled: true };

for (const control of [expectedModel, writeCheckbox, resource, executionMode]) {
  control.addEventListener("change", () => {});
}
const identities = {
  expectedModel,
  writeCheckbox,
  deviceOptionsPanel,
  resource,
  executionMode,
  authorization,
};
const listenerCounts = [expectedModel, writeCheckbox, resource, executionMode]
  .map((control) => control.listeners.length);
const root = {
  querySelectorAll(selector) {
    assert.equal(
      selector,
      "[data-i18n],[data-i18n-placeholder],[data-i18n-title],[data-i18n-aria-label]"
    );
    return [identityHelp, writeText];
  },
};

function assertPreserved() {
  assert.equal(identities.expectedModel, expectedModel);
  assert.equal(identities.writeCheckbox, writeCheckbox);
  assert.equal(identities.deviceOptionsPanel, deviceOptionsPanel);
  assert.equal(identities.resource, resource);
  assert.equal(identities.executionMode, executionMode);
  assert.equal(identities.authorization, authorization);
  assert.equal(expectedModel.value, "keysight-e36312a");
  assert.equal(writeCheckbox.checked, true);
  assert.equal(deviceOptionsPanel.hidden, false);
  assert.equal(resource.value, "USB0::TEST::INSTR");
  assert.equal(executionMode.value, "real");
  assert.equal(executionMode.checked, true);
  assert.deepEqual(
    [expectedModel, writeCheckbox, resource, executionMode]
      .map((control) => control.listeners.length),
    listenerCounts
  );
}

assert.equal(i18n.getLocale(), "en");
assert.equal(applyStaticTranslations(root), 2);
const englishIdentityHelp = identityHelp.textContent;
const englishWriteText = writeText.textContent;
assert.match(identityHelp.textContent, /IDN/);
assert.match(writeText.textContent, /hardware writes/);
assertPreserved();

i18n.setLocale("zh-TW");
assert.equal(applyStaticTranslations(root), 2);
assert.notEqual(identityHelp.textContent, englishIdentityHelp);
assert.match(identityHelp.textContent, /IDN/);
assert.notEqual(writeText.textContent, englishWriteText);
assert.match(writeText.textContent, /硬體寫入/);
assertPreserved();

i18n.setLocale("en");
assert.equal(applyStaticTranslations(root), 2);
assert.equal(identityHelp.textContent, englishIdentityHelp);
assert.equal(writeText.textContent, englishWriteText);
assertPreserved();

process.stdout.write(JSON.stringify({ ok: true }));
"""
    completed = subprocess.run(
        [
            NODE,
            "--input-type=module",
            "--eval",
            script,
            (STATIC_DIR / "dom_i18n.js").resolve().as_uri(),
            (STATIC_DIR / "i18n.js").resolve().as_uri(),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, (
        f"Node device-options i18n contract failed\nstdout:\n{completed.stdout}"
        f"\nstderr:\n{completed.stderr}"
    )
    assert completed.stdout == '{"ok":true}'


def test_static_html_p2_bindings_have_catalog_parity_and_preserve_contracts() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    en_source = (STATIC_DIR / "locale_en.js").read_text(encoding="utf-8")
    zh_tw_source = (STATIC_DIR / "locale_zh_tw.js").read_text(encoding="utf-8")
    binding_keys = set(
        re.findall(
            r'data-i18n(?:-placeholder|-title|-aria-label)?="([a-z][a-z0-9_.]+)"',
            html,
        )
    )
    en_keys = set(re.findall(r'^  "([a-z][a-z0-9_.]+)":', en_source, re.MULTILINE))
    zh_tw_keys = set(re.findall(r'^  "([a-z][a-z0-9_.]+)":', zh_tw_source, re.MULTILINE))

    assert binding_keys
    assert en_keys == zh_tw_keys
    assert binding_keys <= en_keys
    assert '<html lang="en">' in html
    assert 'data-i18n="app.unofficial_tool"' in html
    assert 'data-i18n="app.appearance"' in html
    assert 'data-i18n="app.language"' in html
    assert "v__WEBUI_VERSION__" in html
    assert 'id="locale-toggle"' in html
    assert 'id="locale-toggle-label"' in html
    assert 'data-i18n-title="accessibility.switch_language_to_zh_tw"' in html
    assert 'data-i18n="locale.display_en"' in html
    assert 'lang="en"' in html
    assert re.search(
        r'<svg\b(?=[^>]*\bclass="locale-toggle-icon")'
        r'(?=[^>]*\baria-hidden="true")[^>]*>',
        html,
    )
    for mode in ("real", "simulate", "dry-run"):
        assert f'name="execution-mode" value="{mode}"' in html
    for machine_value in ("none", "odd", "even", "mark", "space", "xon_xoff", "rts_cts", "dtr_dsr"):
        assert f'value="{machine_value}"' in html
    assert 'aria-controls="device-options-panel"' in html
    assert 'aria-controls="device-resource-body"' in html
    assert 'aria-expanded="true"' in html
    assert 'aria-expanded="false"' in html


def test_p3_maintained_catalog_messages_are_complete() -> None:
    en_source = (STATIC_DIR / "locale_en.js").read_text(encoding="utf-8")
    zh_tw_source = (STATIC_DIR / "locale_zh_tw.js").read_text(encoding="utf-8")
    en_keys = set(re.findall(r'^  "([a-z][a-z0-9_.]+)":', en_source, re.MULTILINE))
    zh_tw_keys = set(re.findall(r'^  "([a-z][a-z0-9_.]+)":', zh_tw_source, re.MULTILINE))
    required = {
        "device.detected_model",
        "device.expected.auto_detect",
        "device.identity.simulation_model",
        "execution_mode.badge.real_locked",
        "execution_mode.badge.real_enabled",
        "execution_mode.help.dry_run",
        "health.device.busy",
        "health.server.reachable",
        "resource.scan.empty",
        "resource.status.not_scanned",
        "command.category.output",
        "command.name.output_on",
        "command.description.trigger_fire",
        "command.notes.heading",
        "form.field.channel",
        "form.guidance.set_partial",
        "form.option.positive",
        "basic_controls.output.controlled_by_all",
        "basic_controls.help.e3646a_global_output",
    }

    assert en_keys == zh_tw_keys
    assert required <= en_keys


def test_parameter_constraint_tooltip_catalog_covers_current_metadata_inventory() -> None:
    en_source = (STATIC_DIR / "locale_en.js").read_text(encoding="utf-8")
    zh_tw_source = (STATIC_DIR / "locale_zh_tw.js").read_text(encoding="utf-8")
    expected = {
        f"form.constraint.{name}"
        for name in parameter_constraints_metadata()
    } | {"form.constraint.electrical_rating"}
    en_keys = set(re.findall(r'^  "(form\.constraint\.[a-z0-9_]+)":', en_source, re.MULTILINE))
    zh_tw_keys = set(re.findall(r'^  "(form\.constraint\.[a-z0-9_]+)":', zh_tw_source, re.MULTILINE))

    assert en_keys == expected
    assert zh_tw_keys == expected
    assert re.search(r'"form\.constraint\.delay_ms": "[^"]*(?:ms|voltage)', en_source, re.IGNORECASE)
    assert re.search(r'"form\.constraint\.delay_ms": "[^"]*(?:ms|電壓)', zh_tw_source)
    assert re.search(r'"form\.constraint\.hold_ms": "[^"]*(?:ms|voltage)', en_source, re.IGNORECASE)
    assert re.search(r'"form\.constraint\.hold_ms": "[^"]*(?:ms|電壓)', zh_tw_source)
    assert re.search(r'"form\.constraint\.stop_voltage": "[^"]*(?:voltage|0)', en_source, re.IGNORECASE)
    assert re.search(r'"form\.constraint\.stop_voltage": "[^"]*(?:電壓|0)', zh_tw_source)
