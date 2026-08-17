"""Shared helpers for WebUI frontend and static-contract tests."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

WEBUI_COMMAND_NAMES = {
    "clear", "error", "capabilities", "identify",
    "set", "apply", "output-on", "output-off", "safe-off", "cycle-output",
    "ramp", "ramp-list", "smoke-output", "protection-set", "clear-protection", "trigger-pulse",
    "trigger-status", "trigger-step", "trigger-list", "trigger-fire", "trigger-abort",
    "sequence", "snapshot", "restore-from-snapshot",
}

WEBUI_HIDDEN_UNSUPPORTED_COMMANDS = {
    "doctor", "validate-readonly", "log", "snapshot-diff", "hardware-report",
}

WEBUI_HIDDEN_LIVE_DATA_COMMANDS = {
    "measure", "measure-all", "read-status", "protection-status", "output-state",
}

WEBUI_HIDDEN_DIAGNOSTIC_COMMANDS = {"verify", "readback", "safety inspect"}

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "src" / "powers_tool_webui" / "static"


def read_static_texts() -> tuple[str, str, str]:
    app_surface = "\n".join(
        (STATIC_DIR / filename).read_text(encoding="utf-8")
        for filename in ("app.js", "command-form.js", "device-resource.js")
    )
    return (
        (STATIC_DIR / "index.html").read_text(encoding="utf-8"),
        app_surface,
        (STATIC_DIR / "styles.css").read_text(encoding="utf-8"),
    )


def read_static_javascript(filename: str) -> str:
    return (STATIC_DIR / filename).read_text(encoding="utf-8")


def simulated_e36312a_runtime() -> dict[str, Any]:
    return {
        "resource": "USB0::SIM::E36312A::INSTR",
        "simulate": True,
        "timeout_ms": 5000,
        "confirm": False,
    }


def static_tag_with_id(html: str, element_id: str) -> str:
    match = re.search(rf"<[^>]*\bid=\"{re.escape(element_id)}\"[^>]*>", html)
    if not match:
        raise AssertionError(f'Missing element id="{element_id}"')
    return match.group(0)


def assert_static_id(html: str, element_id: str) -> None:
    static_tag_with_id(html, element_id)


def assert_static_attr(html: str, element_id: str, attr: str, value: str | None = None) -> None:
    tag = static_tag_with_id(html, element_id)
    if value is None:
        assert re.search(rf"\b{re.escape(attr)}(?:\s|=|>|$)", tag), tag
    else:
        assert re.search(rf"\b{re.escape(attr)}=\"{re.escape(value)}\"", tag), tag


def extract_param_block(app_js: str, command_name: str) -> str:
    params_block = app_js[
        app_js.index("const PARAMS = {"):app_js.index("function defaultRampSegment()")
    ]
    match = re.search(rf'(?m)^\s*(?:"{re.escape(command_name)}"|{re.escape(command_name)}):', params_block)
    if not match:
        raise AssertionError(f"Missing PARAMS entry for {command_name}")
    start = match.start()
    next_match = re.search(r'(?m)^\s*(?:"[^"]+"|[A-Za-z_$][\w$-]*):', params_block[match.end():])
    end = match.end() + next_match.start() if next_match else len(params_block)
    return params_block[start:end]


def assert_param_contract(
    block: str,
    name: str,
    type_: str | None = None,
    options: list[str] | None = None,
) -> None:
    assert f'name: "{name}"' in block
    if type_ is not None:
        assert f'type: "{type_}"' in block
    if options is not None:
        quoted = ", ".join(f'"{option}"' for option in options)
        assert f"options: [{quoted}]" in block


def extract_js_function(app_js: str, function_name: str) -> str:
    match = re.search(
        rf"(?:async\s+)?function\s+{re.escape(function_name)}\s*\(",
        app_js,
    )
    if not match:
        raise AssertionError(f"Missing function {function_name}")
    parameter_depth = 1
    index = match.end()
    while index < len(app_js):
        if app_js[index] == "(":
            parameter_depth += 1
        elif app_js[index] == ")":
            parameter_depth -= 1
            if parameter_depth == 0:
                break
        index += 1
    if parameter_depth != 0:
        raise AssertionError(f"Could not parse signature for {function_name}")
    brace = app_js.index("{", index)
    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = brace
    while index < len(app_js):
        char = app_js[index]
        next_char = app_js[index + 1] if index + 1 < len(app_js) else ""

        if line_comment:
            if char == "\n":
                line_comment = False
            index += 1
            continue

        if block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue

        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue

        if char == "/" and next_char == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            block_comment = True
            index += 2
            continue
        if char in {"'", '"', "`"}:
            quote = char
            index += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return app_js[match.start():index + 1]
        index += 1
    raise AssertionError(f"Could not extract function {function_name}")


FRONTEND_JAVASCRIPT_BOOTSTRAP = """
globalThis.window = {};
globalThis.document = {
  addEventListener() {},
  getElementById() { return { value: "" }; }
};
"""


FAKE_DOM_PRIMITIVES = r"""
class FakeClassList {
  constructor(owner) { this.owner = owner; }
  _values() { return new Set(this.owner.className.split(/\s+/).filter(Boolean)); }
  add(...names) {
    const values = this._values();
    names.forEach((name) => values.add(name));
    this.owner.className = [...values].join(" ");
  }
  remove(...names) {
    const values = this._values();
    names.forEach((name) => values.delete(name));
    this.owner.className = [...values].join(" ");
  }
  contains(name) { return this._values().has(name); }
  toggle(name, force) {
    const values = this._values();
    const enabled = force === undefined ? !values.has(name) : Boolean(force);
    if (enabled) values.add(name);
    else values.delete(name);
    this.owner.className = [...values].join(" ");
    return enabled;
  }
}

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.className = "";
    this.classList = new FakeClassList(this);
    this.id = "";
    this.textContent = "";
    this.title = "";
    this.style = {};
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.hidden = false;
    this.type = "";
  }
  get options() { return this.children; }
  appendChild(child) {
    if (child.parentNode) {
      child.parentNode.children = child.parentNode.children.filter((item) => item !== child);
    }
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  append(...children) { children.forEach((child) => this.appendChild(child)); }
  addEventListener(type, listener) {
    (this.listeners[type] ||= []).push(listener);
  }
  querySelectorAll() { return []; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  set innerHTML(value) {
    if (value !== "") {
      throw new Error("FakeElement.innerHTML only supports clearing");
    }
    this.textContent = "";
    this.children = [];
  }
}

const descendants = (root) => [root, ...root.children.flatMap((child) => descendants(child))];
"""


def run_frontend_javascript_assertions(
    assertions: str,
    source_names: tuple[str, ...] = ("execution-context.js", "electrical.js", "api.js", "state.js", "device-resource.js", "command-catalog.js", "command-form.js", "results.js", "live-data.js", "json-files.js", "ramp-list.js", "trigger-list.js", "sequence.js", "snapshot-restore.js", "jobs.js", "basic-controls.js", "command-support.js", "workflows.js", "locale_ui.js", "theme_ui.js", "app.js"),
    *,
    bootstrap: str = "",
    expected_failure_substrings: tuple[str, ...] = (),
    after_source_assertions: dict[str, str] | None = None,
) -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for WebUI JavaScript behavior tests."
    production_scripts = [
        {"sourceName": name, "source": read_static_javascript(name)}
        for name in source_names
    ]
    english_messages = {
        key: json.loads(f'"{value}"')
        for key, value in re.findall(
            r'^  "([a-z][a-z0-9_.]+)": "((?:[^"\\]|\\.)*)",?$',
            read_static_javascript("locale_en.js"),
            re.MULTILINE,
        )
    }
    zh_tw_messages = {
        key: json.loads(f'"{value}"')
        for key, value in re.findall(
            r'^  "([a-z][a-z0-9_.]+)": "((?:[^"\\]|\\.)*)",?$',
            read_static_javascript("locale_zh_tw.js"),
            re.MULTILINE,
        )
    }
    runner = f"""
const vm = require("node:vm");
const bootstrapSource = {json.dumps(FRONTEND_JAVASCRIPT_BOOTSTRAP + bootstrap)};
const productionScripts = {json.dumps(production_scripts)};
const assertionsSource = {json.dumps(assertions)};
const afterSourceAssertions = {json.dumps(after_source_assertions or {})};
const englishMessages = {json.dumps(english_messages)};
const zhTwMessages = {json.dumps(zh_tw_messages)};
let activeMessages = englishMessages;
const sandbox = {{
      console,
      require,
      process,
      setTimeout,
  clearTimeout,
  setInterval,
  clearInterval
}};
const context = vm.createContext(sandbox);
sandbox.setLocale = (locale) => {{
  activeMessages = locale === "zh-TW" ? zhTwMessages : englishMessages;
}};
sandbox.__webuiTranslate = (key, params, rawFallback) => {{
  let message = Object.hasOwn(activeMessages, key) ? activeMessages[key] : (rawFallback ?? key);
  return message.replace(/\\{{([A-Za-z_][A-Za-z0-9_]*)\\}}/g, (placeholder, name) =>
    params && Object.hasOwn(params, name) ? String(params[name]) : placeholder
  );
}};
sandbox.__webuiSourceTranslate = (key, params, rawFallback) => {{
  let message = Object.hasOwn(englishMessages, key) ? englishMessages[key] : (rawFallback ?? key);
  return message.replace(/\\{{([A-Za-z_][A-Za-z0-9_]*)\\}}/g, (placeholder, name) =>
    params && Object.hasOwn(params, name) ? String(params[name]) : placeholder
  );
}};

function runScript(source, filename) {{
  return new vm.Script(source, {{ filename }}).runInContext(context);
}}

function moduleCompatibilitySource(source, filename) {{
  if (filename === "execution-context.js") {{
    return source.replace(/^export function /gm, "function ") + `
globalThis.__webuiContext = {{
  isNoHardwareExecutionMode,
  buildWorkspaceResultKey,
  buildWorkspaceResultContextForJob,
  buildCurrentWorkspaceResultContext,
  buildWorkspaceResultEntry,
  findWorkspaceResult
}};`;
  }}
  if (filename === "electrical.js") {{
    return source.replace(/^export function /gm, "function ") + `
globalThis.__webuiElectrical = {{ resolveInputElectricalConstraint }};`;
  }}
  if (filename === "api.js") {{
    return source.replace(/^export async function /gm, "async function ") + `
globalThis.__webuiApi = {{ fetchJson }};`;
  }}
  if (filename === "state.js") {{
    return source.replace(/^export function /gm, "function ") + `
globalThis.__webuiState = {{ createInitialState }};`;
  }}
  if (filename === "device-resource.js") {{
    return `(function() {{\n${{source.replace('import {{ t }} from "./i18n.js";', 'const t = globalThis.__webuiTranslate;').replace(/^export function /gm, "function ")}}\nglobalThis.__webuiDevice = {{ physicalModelDisplayName, planningIdentitySummary, liveResourceSummary, resourceLabel, createDeviceResourceController }};\n}})();`;
  }}
  if (filename === "command-catalog.js") {{
    return source.replace('import {{ sourceT, t }} from "./i18n.js";', 'const sourceT = globalThis.__webuiSourceTranslate; const t = globalThis.__webuiTranslate;').replace(/^export (?:const|function) /gm, (match) => match.replace("export ", "")) + `
globalThis.__webuiCommandCatalog = {{ COMMAND_CATEGORIES, COMMAND_CATEGORY_LABELS, commandCategoryLabel, commandMessageKey, commandDisplayName, commandSourceDisplayName, commandDescription }};`;
  }}
  if (filename === "command-form.js") {{
    return source.replace('import {{ t }} from "./i18n.js";', '').replace(/^export function /gm, "function ") + `
    globalThis.__webuiCommandForm = {{ createCheckboxField, renderCommandGuidance, appendFieldDescription, configureCompactCheckboxHelp, appendSetGuidance, appendCommandNotes, setOutputParams, applyOutputParams, smokeOutputParams, triggerWaitParams, triggerStepParams, triggerListParams, createCommandController }};`;
  }}
  if (filename === "results.js") {{
    return source.replace('import {{ t }} from "./i18n.js";', '').replace(/^export function /gm, "function ") + `
 globalThis.__webuiResults = {{ jobSummary, eventSummary, successfulJobSummary, capabilitiesSummary, identifySummary, verifySummary, readStatusSummary, readbackSummary, snapshotSummary, safetyInspectSummary, outputStatesSummary, setpointSummary, formatSetpointValue, errorQueueSummary, compactParts, statusSummary, statusLabel, statusClass, renderWorkspaceEmpty, renderWorkspaceJob, renderCapabilitiesWorkspaceSummary, renderIdentifyWorkspaceSummary, renderTriggerStatusWorkspaceSummary, appendWorkspaceFields, channelList, featureAvailability }};`;
  }}
  if (filename === "jobs.js") {{
    return source.replace(/^export function /gm, "function ") + `
globalThis.__webuiJobTransport = {{ submitJob, openJobEvents, createJobEventController, addHistory, updateHistory, updateJobResult, renderHistory }};`;
  }}
  if (filename === "live-data.js") {{
    return source.replace('import {{ t }} from "./i18n.js";', '').replace(/^export function /gm, "function ") + `
    globalThis.__webuiLiveData = {{ liveStateText, liveStateClass, blankLiveChannels, mergeLiveChannels, mergeLiveChannel, normalizeMeasurements, renderChannelCard, protectionBadge, createLiveDataController }};`;
  }}
      if (filename === "json-files.js") {{
        return source.replace('import {{ t }} from "./i18n.js";', '').replace(/^export (?:async )?function /gm, (match) => match.replace("export ", "")) + `
globalThis.__webuiJsonFiles = {{ buildNativeJsonPickerAccept, openJsonFile, buildJsonFileAccept, chooseJsonFile, saveJsonFile, abortError, isAbortError }};`;
  }}
  if (filename === "ramp-list.js") {{
    return source.replace(/^export function /gm, "function ") + `
globalThis.__webuiRampListDocument = {{ defaultRampSegment, rampSegmentDefinitions, effectiveEnabledLoopCount, rampListDocument, validateRampListDocument }};`;
  }}
  if (filename === "trigger-list.js") {{
    return source.replace(/^export function /gm, "function ") + `
globalThis.__webuiTriggerListDocument = {{ defaultTriggerListStep, defaultTriggerListChannels, defaultTriggerListControls, triggerListWorkspaceDocument, validateTriggerListWorkspace }};`;
  }}
  if (filename === "sequence.js") {{
    return source.replace(/^export function /gm, "function ") + `
globalThis.__webuiSequenceDocument = {{ normalizeSequenceDocument, normalizeSequenceStep, sequenceDocumentFromEditor }};`;
  }}
  if (filename === "snapshot-restore.js") {{
    return source.replace(/^export function /gm, "function ") + `
globalThis.__webuiSnapshotDocument = {{ snapshotSuggestedName, validateSnapshotDocument }};
globalThis.__webuiRestoreDocument = {{ validateRestoreSnapshot, normalizeRestoreChannel, restoreSnapshotParameters }};`;
  }}
  if (filename === "basic-controls.js") {{
    return source.replace('import {{ t }} from "./i18n.js";', '').replace(/^export function /gm, "function ") + `
globalThis.__webuiBasicControls = {{ createBasicControls }};`;
  }}
  if (filename === "command-support.js") {{
    return source.replace('import {{ t }} from "./i18n.js";', '').replace(/^export function /gm, "function ") + `
globalThis.__webuiCommandSupport = {{ createCommandSupport }};`;
  }}
  if (filename === "workflows.js") {{
    return `(function() {{\n${{source.replace('import {{ t }} from "./i18n.js";', 'const t = globalThis.__webuiTranslate;').replace(/^export function /gm, "function ")}}\nglobalThis.__webuiWorkflows = {{ refreshWorkflowPresentation, createWorkflows, createArtifactAndSequenceWorkflows }};\n}})();`;
  }}
  if (filename === "locale_ui.js") {{
    return `(function() {{
${{source
      .replace(/import \\{{[\\s\\S]*?\\}} from "\\.\\/i18n\\.js";/, `
const LOCALE_STORAGE_KEY = "powers-tool.webui.locale";
const SUPPORTED_LOCALES = ["en", "zh-TW"];
const getLocale = () => globalThis.__webuiLocale;
const isSupportedLocale = (value) => ["en", "zh-TW"].includes(value);
const setLocale = (locale) => {{ globalThis.__webuiLocale = locale; return locale; }};
const t = globalThis.__webuiTranslate;`)
      .replace(/^export function /gm, "function ")}}
globalThis.__webuiLocaleUi = {{ normalizeBrowserLanguage, browserLocale, detectBrowserLocale, readSavedLocale, resolveInitialLocale, persistLocale, targetLocale, renderLanguageButton, initializeLocaleUi }};
 }})();`;
  }}
  if (filename === "theme_ui.js") {{
    return `(function() {{
${{source
      .replace('import {{ t }} from "./i18n.js";', 'const t = globalThis.__webuiTranslate;')
      .replace(/^export const /gm, "const ")
      .replace(/^export function /gm, "function ")}}
globalThis.__webuiThemeUi = {{ initializeThemeUi }};
}})();`;
  }}
  if (filename === "app.js") {{
    return source
      .replace(
            'import * as webuiContext from "./execution-context.js";',
            'var webuiContext = globalThis.__webuiContext;'
      )
      .replace(
            'import * as webuiElectrical from "./electrical.js";',
            'var webuiElectrical = globalThis.__webuiElectrical;'
      )
      .replace(
            'import * as webuiApi from "./api.js";',
            'var webuiApi = globalThis.__webuiApi;'
      )
      .replace(
            'import * as webuiState from "./state.js";',
            'var webuiState = globalThis.__webuiState;'
      )
      .replace(
            'import * as webuiDevice from "./device-resource.js";',
            'var webuiDevice = globalThis.__webuiDevice;'
      )
      .replace(
            'import * as webuiCommandCatalog from "./command-catalog.js";',
            'var webuiCommandCatalog = globalThis.__webuiCommandCatalog;'
      )
      .replace(
            'import * as webuiCommandForm from "./command-form.js";',
            'var webuiCommandForm = globalThis.__webuiCommandForm;'
      )
      .replace(
            'import * as webuiResults from "./results.js";',
            'var webuiResults = globalThis.__webuiResults;'
      )
      .replace(
            'import * as webuiJobTransport from "./jobs.js";',
            'var webuiJobTransport = globalThis.__webuiJobTransport;'
      )
      .replace(
            'import * as webuiLiveData from "./live-data.js";',
            'var webuiLiveData = globalThis.__webuiLiveData;'
      )
      .replace(
            'import * as webuiJsonFiles from "./json-files.js";',
            'var webuiJsonFiles = globalThis.__webuiJsonFiles;'
      )
      .replace(
            'import * as webuiRampListDocument from "./ramp-list.js";',
            'var webuiRampListDocument = globalThis.__webuiRampListDocument;'
      )
      .replace(
            'import * as webuiTriggerListDocument from "./trigger-list.js";',
            'var webuiTriggerListDocument = globalThis.__webuiTriggerListDocument;'
      )
      .replace(
            'import * as webuiSequenceDocument from "./sequence.js";',
            'var webuiSequenceDocument = globalThis.__webuiSequenceDocument;'
      )
      .replace(
            'import * as webuiSnapshotDocument from "./snapshot-restore.js";',
            'var webuiSnapshotDocument = globalThis.__webuiSnapshotDocument;'
      )
      .replace(
            'import * as webuiRestoreDocument from "./snapshot-restore.js";',
            'var webuiRestoreDocument = globalThis.__webuiRestoreDocument;'
      )
      .replace(
            'import * as webuiJobTransport from "./jobs.js";',
            'var webuiJobTransport = globalThis.__webuiJobTransport;'
      )
      .replace(
            'import * as webuiBasicControls from "./basic-controls.js";',
            'var webuiBasicControls = globalThis.__webuiBasicControls;'
      )
      .replace(
            'import * as webuiCommandSupport from "./command-support.js";',
            'var webuiCommandSupport = globalThis.__webuiCommandSupport;'
      )
          .replace(
                'import * as webuiWorkflows from "./workflows.js";',
                'var webuiWorkflows = globalThis.__webuiWorkflows;'
          )
           .replace(
                 'import * as webuiLocaleUi from "./locale_ui.js";',
                 'var webuiLocaleUi = globalThis.__webuiLocaleUi;'
           )
              .replace(
                    'import * as webuiThemeUi from "./theme_ui.js";',
                    'var webuiThemeUi = globalThis.__webuiThemeUi;'
              )
               .replace(
                    'import {{ applyStaticTranslations }} from "./dom_i18n.js";',
                    'var applyStaticTranslations = () => 0;'
              )
              .replace(
                    'import {{ t }} from "./i18n.js";',
                    ''
              );
  }}
  return source;
}}

runScript(bootstrapSource, "frontend-test-bootstrap.js");
for (const {{ sourceName, source }} of productionScripts) {{
  runScript(moduleCompatibilitySource(source, sourceName), sourceName);
  if (Object.hasOwn(afterSourceAssertions, sourceName)) {{
    runScript(afterSourceAssertions[sourceName], `frontend-test-after-${{sourceName}}`);
  }}
}}
runScript(assertionsSource, "frontend-test-assertions.js");
"""
    completed = subprocess.run(
        [node, "--input-type=commonjs"],
        input=runner,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    diagnostics = completed.stderr or completed.stdout
    if expected_failure_substrings:
        assert completed.returncode != 0, "Expected frontend JavaScript execution to fail."
        for expected_substring in expected_failure_substrings:
            assert expected_substring in diagnostics, diagnostics
    else:
        assert completed.returncode == 0, diagnostics


def run_webui_module_assertions(assertions: str, module_names: tuple[str, ...]) -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for WebUI JavaScript behavior tests."
    module_urls = {
        name: (STATIC_DIR / name).resolve().as_uri()
        for name in module_names
    }
    runner = f"""
import {{ strict as strictAssert }} from "node:assert";
const moduleUrls = {json.dumps(module_urls)};
if (moduleUrls["execution-context.js"]) globalThis.webuiContext = await import(moduleUrls["execution-context.js"]);
if (moduleUrls["electrical.js"]) globalThis.webuiElectrical = await import(moduleUrls["electrical.js"]);
if (moduleUrls["api.js"]) globalThis.webuiApi = await import(moduleUrls["api.js"]);
if (moduleUrls["state.js"]) globalThis.webuiState = await import(moduleUrls["state.js"]);
if (moduleUrls["device-resource.js"]) globalThis.webuiDevice = await import(moduleUrls["device-resource.js"]);
if (moduleUrls["command-catalog.js"]) globalThis.webuiCommandCatalog = await import(moduleUrls["command-catalog.js"]);
if (moduleUrls["command-form.js"]) globalThis.webuiCommandForm = await import(moduleUrls["command-form.js"]);
if (moduleUrls["results.js"]) globalThis.webuiResultSummary = await import(moduleUrls["results.js"]);
if (moduleUrls["results.js"]) globalThis.webuiWorkspaceResults = await import(moduleUrls["results.js"]);
if (moduleUrls["live-data.js"]) globalThis.webuiLiveData = await import(moduleUrls["live-data.js"]);
if (moduleUrls["json-files.js"]) globalThis.webuiJsonFiles = await import(moduleUrls["json-files.js"]);
if (moduleUrls["ramp-list.js"]) globalThis.webuiRampListDocument = await import(moduleUrls["ramp-list.js"]);
if (moduleUrls["trigger-list.js"]) globalThis.webuiTriggerListDocument = await import(moduleUrls["trigger-list.js"]);
if (moduleUrls["sequence.js"]) globalThis.webuiSequenceDocument = await import(moduleUrls["sequence.js"]);
if (moduleUrls["snapshot-restore.js"]) globalThis.webuiSnapshotDocument = await import(moduleUrls["snapshot-restore.js"]);
if (moduleUrls["snapshot-restore.js"]) globalThis.webuiRestoreDocument = await import(moduleUrls["snapshot-restore.js"]);
if (moduleUrls["jobs.js"]) globalThis.webuiJobTransport = await import(moduleUrls["jobs.js"]);
if (moduleUrls["basic-controls.js"]) globalThis.webuiBasicControls = await import(moduleUrls["basic-controls.js"]);
if (moduleUrls["command-support.js"]) globalThis.webuiCommandSupport = await import(moduleUrls["command-support.js"]);
if (moduleUrls["workflows.js"]) globalThis.webuiWorkflows = await import(moduleUrls["workflows.js"]);
if (moduleUrls["locale_ui.js"]) globalThis.webuiLocaleUi = await import(moduleUrls["locale_ui.js"]);
{assertions}
"""
    completed = subprocess.run(
        [node, "--input-type=module"],
        input=runner,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    diagnostics = completed.stderr or completed.stdout
    assert completed.returncode == 0, diagnostics
