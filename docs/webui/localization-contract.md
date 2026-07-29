# WebUI Localization Contract

## 1. Purpose And Current Runtime Status

This document defines the investigation findings, browser-localization boundary,
initial Traditional Chinese terminology, user-visible text inventory, refresh
rules, and maintained runtime contract for Powers WebUI localization.

Localization is implemented and maintained in the browser WebUI. The maintained
locales are `en` and `zh-TW`. English is the source locale, a complete locale,
and the mandatory fallback locale. Localization is limited to presentation
owned by the browser WebUI.

Historically, P0 was the documentation-only phase that introduced this
contract. Subsequent P1-P6 phases implemented the catalogs, i18n runtime, DOM
bindings, locale control, state-preserving runtime switching, terminology
review, and regression coverage described below. The phase history is not a
description of the current implementation status.

The CLI, Core, drivers, SCPI, VISA, transport and backend behavior, API schemas,
workflow file schemas, CSV, JSON, JSONL, logs, exported artifacts, and raw
diagnostics are outside the localization ownership of this contract. Backend
modules are inventoried only where they explicitly provide presentation metadata
or a message source that the browser displays. This does not transfer ownership
of those messages, validation, or diagnostics to the WebUI.

The current implementation includes catalogs, an i18n runtime, DOM localization
helpers, and a locale control. It changes browser presentation only and does not
alter Core, API, SCPI, VISA, Product support, or raw diagnostic behavior.

## 2. Locked Product Decisions

The maintained implementation uses these constants and decisions:

```text
SOURCE_LOCALE = "en"
FALLBACK_LOCALE = "en"
SUPPORTED_LOCALES = ["en", "zh-TW"]
LOCALE_STORAGE_KEY = "powers-tool.webui.locale"
```

Initial locale resolution has this precedence:

1. Use the saved locale only when the value under
   `powers-tool.webui.locale` is exactly `en` or `zh-TW`.
2. Otherwise, select `zh-TW` when the browser language matches `zh-TW`,
   `zh-TW-*`, `zh-Hant`, or `zh-Hant-*`.
3. Use `en` for all other browser languages and saved values.

Saved-locale validation and browser-language matching are intentionally
different. A saved locale receives no case folding, underscore replacement, or
other permissive canonicalization; any value other than the exact strings `en`
and `zh-TW` is ignored. Browser-language matching is case-insensitive, first
normalizes `_` to `-`, and then accepts `zh-TW`, a `zh-TW-` prefix, `zh-Hant`, or
a `zh-Hant-` prefix. Other Chinese language tags must not be mapped to `zh-TW`.

The locale control is a single button in the upper-right of the main interface,
not inside Device options, Settings, or another menu. It displays the
target language: `繁體中文` in English and `English` in Traditional Chinese.
Changing locale must take effect immediately without reloading the page, update
`<html lang>`, and persist a manual selection using the independent locale
storage key. A localStorage read or write failure must safely fall back without
making the WebUI unusable.

## 3. Ownership And Architecture Boundary

The browser WebUI owns only browser presentation: headings, labels, help text,
option display text, placeholders, titles, ARIA labels, empty states, known
status and summary presentation, and known browser-generated validation or error
presentation.

Core and backend data remain authoritative. Localization must never become an
input to validation, authorization, capability selection, identity selection,
Product admission, support decisions, or runtime behavior. It must not change:

- Real, Simulate, or Dry-run execution semantics or their separate identity
  slots;
- page-local identity reset on reload, the Real-only Live Data restriction, or
  Expected Model as an identity guard;
- fail-closed command admission, Product support, model lifecycle, command
  count, planning model, or planning profile semantics;
- request or response schemas, the Job queue, admitted runtime options, Loop or
  completion-pulse semantics;
- Stop, safe-off, cleanup, local/release, Restore, SCPI, VISA, transport,
  backend, hardware lock, evidence, or Product promotion boundaries.

`app.py`, `commands.py`, and `jobs.py` remain backend-owned. Only explicitly
browser-facing presentation metadata or message sources from those files are in
the inventory. Unknown Core, backend, validation, VISA, SCPI, instrument, HTTP,
support, admission, and rejection details must remain verbatim.

## 4. Non-Translatable Machine Contracts

Display text may be translated, but the following values must neither be
translated nor derived from translated text.

| Contract area | Protected examples | Rule |
| --- | --- | --- |
| HTTP interface | API endpoint, HTTP method, status code | Preserve exactly; locale switching makes no request. |
| API schema | Request/response JSON keys, booleans, enum values, schema versions | Preserve exactly in payloads and logic. |
| Commands | Command IDs and command-count semantics | Keep canonical IDs; translate only catalog labels and descriptions. |
| Models and support | Model IDs, Product IDs, support/capability values | Keep authoritative raw values; never infer support from a label. |
| Planning | Planning model IDs and planning profile IDs | Keep submitted and stored IDs unchanged. |
| Execution | `real`, `simulate`, `dry-run` and runtime status values | Translate presentation only; compare canonical state. |
| Device communication | Transport/backend values, VISA resources, SCPI tokens | Preserve verbatim and never interpolate as HTML. |
| Electrical data | Channel values, units, numeric values | Preserve values and units; surrounding labels may be translated. |
| Forms and DOM | Form `name`, form `value`, DOM contract IDs, `data-*` contract values | Translate associated display nodes/attributes only. |
| Workflow documents | File paths, field names, enums, JSON structure, schema versions | Do not translate submitted, saved, previewed, or restored data. |
| Artifacts | CSV/JSON/JSONL fields and machine-readable output | Outside browser localization ownership. |
| Diagnostics | Unknown error, rejection, validation, support, HTTP, VISA, SCPI, and instrument text | Preserve the original text as a visible fallback. |

For example, the display may say `實機（Real）`, `模擬（Simulate）`, or
`Dry-run（規劃）`, while application and API values remain `real`, `simulate`,
and `dry-run`.

## 5. Translation-Key Contract

Translation keys must be semantic, stable, and independent of presentation
wording. Use dot-separated namespaces with lowercase `snake_case` segments.
Do not use a complete English sentence as a key, a DOM ID as the only meaning,
a locale name in a key, or an array index.

The initial namespace set is:

```text
common.*
app.*
locale.*
device.*
resource.*
execution_mode.*
command.*
form.*
workflow.*
ramp.*
ramp_list.*
sequence.*
snapshot.*
restore.*
job.*
result.*
workspace.*
live_data.*
basic_controls.*
status.*
support.*
validation.*
error.*
accessibility.*
```

Keys identify meaning and context, for example
`execution_mode.option.real`, `job.summary.command`,
`live_data.status.waiting`, and `validation.required_field`. Repeated wording
with different meanings may use different keys. A single semantic message should
not receive different keys merely because it appears in several DOM locations.

## 6. Interpolation And Fallback

Dynamic messages use named interpolation such as `{command}`, `{channel}`,
`{count}`, `{model}`, `{path}`, or `{status}`. Positional interpolation is not
allowed. All parameter values are inserted as text with `textContent`, explicit
text nodes, or a fixed safe attribute. Catalog strings and parameters must never
be executed or interpreted as HTML.

Runtime lookup order is:

1. the selected locale key;
2. the English key;
3. an explicitly supplied raw fallback;
4. the semantic key itself as a diagnosable last resort.

A missing `zh-TW` key falls back to English. A missing English key is a catalog
contract failure and must fail catalog validation. Committed `en` and `zh-TW`
catalogs are expected to have key parity; fallback tests should use synthetic
incomplete catalogs rather than intentionally shipping incomplete `zh-TW`.

An unknown semantic presentation key must retain diagnosable content. Unknown
raw Core, backend, validation, VISA, SCPI, instrument, HTTP, support, or
rejection text must be shown unchanged, never replaced with an empty string,
hidden, or treated as HTML.

## 7. Traditional Chinese Terminology Decisions

These are formal initial P0 terminology decisions. Ordinary interface wording
may be refined during P6 terminology QA when it is unnatural or inconsistent.
Machine values, technical tokens, and the non-translatable contracts in section
4 are fixed and cannot change as a translation decision.

| English term | Recommended `zh-TW` display | Keep English token | Context | Notes |
| --- | --- | --- | --- | --- |
| Real | 實機（Real） | Yes | Execution mode | Makes hardware impact explicit. Canonical value remains `real`. |
| Simulate | 模擬（Simulate） | Yes | Execution mode | Canonical value remains `simulate`. |
| Dry-run | Dry-run（規劃） | Yes | Execution mode | Retain the established technical token. |
| Device | 裝置 | No | Device identity and summary | Use Taiwan terminology. |
| Resource | 資源 | No | Resource selection and scan | Do not translate the resource value. |
| VISA Resource | VISA 資源 | Yes | Communication resource | `VISA` remains a technical token. |
| Expected Model | 預期型號 | No | Real identity guard | Not a device selector. |
| Planning Model | 規劃型號 | No | Non-Real planning | Preserve the model ID. |
| Planning Profile | 規劃設定檔 | No | Planning behavior | Preserve the profile ID. |
| Command | 指令 | No | Command catalog | Command ID remains canonical. |
| Parameter | 參數 | No | Command form | Form names and values remain canonical. |
| Job | 作業 | No | Queued execution | Not translated in API data. |
| Job History | 作業歷程 | No | History panel | Entries require semantic raw state. |
| Workspace | 工作區 | No | Current browser workspace | Not a filesystem translation. |
| Workspace Result | 工作區結果 | No | Latest result summary | Raw result payload remains unchanged. |
| Result | 結果 | No | Execution result | Raw fields remain unchanged. |
| Result Detail | 結果詳細資料 | No | Raw JSON detail | Only the heading is translated. |
| Live Data | 即時資料 | No | Real-only monitoring | Samples and units remain unchanged. |
| Basic controls | 基本控制 | No | Direct controls | Lowercase `controls` follows current heading style. |
| Ramp | 斜坡 | No | Workflow editor | Technical meaning is a value ramp. |
| Ramp List | 斜坡清單 | No | Workflow editor | LIST payload stays canonical. |
| Sequence | 序列 | No | Workflow editor | File fields stay canonical. |
| Loop | 迴圈 | No | Workflow semantics | Loop count/value stays canonical. |
| Snapshot | 快照 | No | State capture | Snapshot document remains unchanged. |
| Restore | 還原 | No | State restoration | Does not change Restore execution semantics. |
| Protection | 保護 | No | OVP/OCP presentation | OVP/OCP tokens may remain English. |
| Trigger | 觸發 | No | Trigger workflow | SCPI and trigger enums remain unchanged. |
| Pulse | 脈衝 | No | Completion pulse | Preserve established semantics. |
| Output | 輸出 | No | Channel output | Boolean and API values remain unchanged. |
| Channel | 通道 | No | Channel selection/status | Channel values remain unchanged. |
| Scan Device | 掃描裝置 | No | Resource scan action | Must not run during locale refresh. |
| Clear | 清除 | No | Clear presentation/history | Locale refresh must not invoke it. |
| Stop | 停止 | No | Job/live action | Does not change stop semantics. |
| Start | 開始 | No | Live/monitor action | Does not start during locale refresh. |
| Run | 執行 | No | Command/workflow action | Does not submit during locale refresh. |
| Status | 狀態 | No | Status label | Raw status remains canonical. |
| Ready | 就緒 | No | Known status | Use only for a recognized semantic state. |
| Busy | 忙碌 | No | Known status | Use only for a recognized semantic state. |
| Failed | 失敗 | No | Known status | Preserve unknown failure detail. |
| Cancelled | 已取消 | No | Known job status | Canonical status remains unchanged. |
| Completed | 已完成 | No | Known job status | Canonical status remains unchanged. |
| Supported | 支援 | No | Product/support summary | Never use the translation for admission. |
| Unsupported | 不支援 | No | Product/support summary | Preserve an unknown support reason. |
| Pending | 待處理 | No | Job state | Use `待驗證` only for support validation context. |

## 8. Historical User-Visible Text Inventory

This table records the P0 user-visible text inventory and the implementation
ownership originally planned for P2-P5. It is retained as historical design
context and does not describe the current implementation status.

Treatment values are `translate`, `translate_with_canonical_token`,
`preserve_raw`, `machine_value`, `not_user_visible`, and `out_of_scope`.
The key and phase columns record the historical P0/P2-P5 plan; they are not
current implementation requirements.

| Source | Surface/function | Current literal or pattern | Content type | Treatment | Proposed key/namespace | Refresh requirement | Risk | Planned phase |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `src/powers_tool_webui/static/index.html` | Page shell, header, sections | `Powers WebUI`, introductory help, Device options, Command, Job History, Workspace Result | Heading/help/static text | translate | `app.*`, `device.*`, `command.*`, `job.*`, `workspace.*` | Update text nodes in place | Broad static English surface | P2 |
| `src/powers_tool_webui/static/index.html` | Buttons and links | Scan Device, Run, Stop, Clear, download/open actions | Button/link text | translate | `common.*`, `device.action.*`, `job.action.*`, `result.action.*` | Update in place; never dispatch click | Labels are adjacent to destructive/runtime actions | P2 |
| `src/powers_tool_webui/static/index.html` | Forms | Labels, help, placeholders, option display, title and ARIA text | Form presentation | translate | `form.*`, `accessibility.*` | Update attributes/text in place | Values must remain canonical | P2 |
| `src/powers_tool_webui/static/index.html` | Execution selector | Real, Simulate, Dry-run, initial static help, title, and ARIA text | Option display/static presentation | translate_with_canonical_token | `execution_mode.option.*`, `execution_mode.help.*`, `accessibility.*` | P2 binds static radio labels, initial help, title, and ARIA in place; P3 refreshes dynamic mode presentation | Option values are contracts; dynamic badges, mode-specific help, identity labels, and Device/Resource summaries are P3-owned | P2/P3 |
| `src/powers_tool_webui/static/app.js` | Application status and health | Loading, ready, failure, health and selected-command presentation | Status/message | translate or preserve_raw | `app.status.*`, `status.*`, `error.*` | Translate known wrapper from cached state; retain raw detail | Some render paths fetch or mutate state | P3/P4 |
| `src/powers_tool_webui/static/app.js` | `renderChannelCard` | Channel/output/measurement card labels and values | Dynamic summary | translate; machine_value | `live_data.channel.*` | Cached presentation-only redraw | Duplicates Live Data card rendering; uses HTML construction | P4 |
| `src/powers_tool_webui/static/api.js` | Request helpers | Endpoint, method, payload and thrown response detail | Machine/diagnostic | machine_value or preserve_raw | `error.http.*` only for known browser wrapper | No request during locale switch | Raw HTTP detail must not be hidden or translated | P4 |
| `src/powers_tool_webui/static/state.js` | Application state | Mode, selected command/resource, jobs, results and flags | Raw state | not_user_visible | None | Must remain unchanged | Some presentation strings are currently stored with raw state | P4/P5 |
| `src/powers_tool_webui/static/execution-context.js` | Execution context | Canonical mode/identity/planning values | Machine value | machine_value | `execution_mode.*` only at display boundary | Read only during refresh | Identity slots and mode semantics are protected | P3 |
| `src/powers_tool_webui/static/device-resource.js` | Device/resource summary | Connected/selected resource, expected/planning model, scan results, empty states | Dynamic summary/status | translate or preserve_raw | `device.*`, `resource.*`, `support.*` | In-place or cached raw redraw only | `liveResourceSummary()` compares `textContent` to `No live resources found`; raw scan/health state is incomplete | P3 |
| `src/powers_tool_webui/static/device-resource.js` | Resource options | Resource display and submitted resource string | Option display/value | translate around raw value; machine_value | `resource.option.*` | Preserve selected value | Display and machine value can be conflated | P3 |
| `src/powers_tool_webui/static/device-resource.js` | Mode UI | Write enabled/locked, identity guard and model help | Known status/help | translate_with_canonical_token | `execution_mode.*`, `device.identity.*` | In-place only | `updateExecutionModeUi()` also changes enabled state and must not be a generic locale refresh | P3 |
| `src/powers_tool_webui/static/command-catalog.js` | Command catalog data | Command labels, groups and descriptions; command IDs | Presentation metadata/value | translate; machine_value | `command.catalog.*` | Re-label existing options/cards or cached catalog redraw | Labels must not replace IDs in selection logic | P3 |
| `src/powers_tool_webui/static/command-form.js` | `renderCommands` | Group headings, option labels, support badges/help | Dynamic catalog presentation | translate | `command.*`, `support.*` | Prefer in-place label update | Uses `innerHTML`; command selection must remain by raw ID | P3 |
| `src/powers_tool_webui/static/command-form.js` | `renderForm` and field builders | Parameter labels, help, placeholders, boolean/enum option text, required/validation messages | Dynamic form presentation | translate | `form.*`, `validation.*` | In-place only while editing | Clears/rebuilds form and can lose user input; generic/Ramp/Snapshot state is DOM-owned | P3 |
| `src/powers_tool_webui/static/command-form.js` | Form submission | Form names, values, numeric/channel/model/path values | Machine value | machine_value | None | Never modify | Translated option text must not enter payloads | P3 |
| `src/powers_tool_webui/static/command-support.js` | Support presentation | Supported/unsupported/pending and known reasons | Status/summary | translate or preserve_raw | `support.status.*`, `support.reason.*` | Render known state from cached raw metadata | Unknown support reason must stay verbatim; support remains authoritative | P3/P4 |
| `src/powers_tool_webui/static/electrical.js` | Electrical fields | Voltage/current/power labels, constraints, units and numeric formatting | Label/value | translate; machine_value | `form.electrical.*` | Update label/help only | Units and numeric values are non-translatable | P3 |
| `src/powers_tool_webui/static/json-files.js` | File controls | Choose/load/download/file-name and parse messages | Label/status/path | translate or preserve_raw | `common.file.*`, `validation.file.*` | Update known presentation only | Paths and raw parse detail must remain unchanged | P4 |
| `src/powers_tool_webui/static/jobs.js` | Job History | Empty state, label, summary, status, cancel/detail controls | Dynamic history presentation | translate | `job.*`, `status.*` | Cached semantic redraw after prerequisite | `state.jobs` stores rendered English `label` and `summary`; not re-translatable today | P4 |
| `src/powers_tool_webui/static/jobs.js` | Job transport | Job IDs, command, status, request and result data | Machine/raw value | machine_value or preserve_raw | None | Never mutate/re-request | Switching locale must not create, update, cancel, or fetch a Job | P4/P5 |
| `src/powers_tool_webui/static/results.js` | Workspace Result | Empty state, command/result summary, status and actions | Dynamic summary | translate or preserve_raw | `workspace.*`, `result.summary.*`, `status.*` | Cached raw redraw or in-place | Must preserve result state and raw unknown messages | P4 |
| `src/powers_tool_webui/static/results.js` | Result Detail | `Result Detail` heading and serialized JSON | Heading/raw diagnostic/data | translate heading; preserve_raw body | `result.detail.heading` | Heading in place; body unchanged | JSON keys/content must not be translated or treated as HTML | P2/P4 |
| `src/powers_tool_webui/static/live-data.js` | Live Data shell | Start/Stop, interval/window/channel controls, waiting/empty/status text | Controls/status | translate | `live_data.*`, `status.*` | In-place or cached redraw | Live Data is Real-only; render functions can alter controls | P4/P5 |
| `src/powers_tool_webui/static/live-data.js` | Charts and `renderChannelCard` | Titles, legends, axis labels, channel/output/measurement text | Cached dynamic presentation | translate; machine_value | `live_data.chart.*`, `live_data.channel.*` | Redraw from existing cached samples only | Uses HTML construction; must not append samples or touch EventSource | P4/P5 |
| `src/powers_tool_webui/static/basic-controls.js` | Basic controls | Headings, field labels, Apply/Read/Output/Protection/Trigger messages | Controls/status | translate or preserve_raw | `basic_controls.*`, `protection.*`, `trigger.*` | In-place; cached status redraw only | Event handlers perform hardware/runtime actions | P4 |
| `src/powers_tool_webui/static/workflows.js` | Workflow shell | Workflow selector, preview/run/status, Loop and completion pulse text | Controls/summary | translate_with_canonical_token where needed | `workflow.*` | In-place or cached semantic redraw | Preview/run paths must never execute on locale switch | P4 |
| `src/powers_tool_webui/static/ramp-list.js` | Ramp List editor | Step/channel/dwell/repeat labels, add/remove/empty/validation summaries | Editor presentation | translate | `ramp_list.*`, `validation.*` | Prefer in-place; cached valid model only when safe | Re-render can lose invalid drafts, focus, or editor state | P4 |
| `src/powers_tool_webui/static/trigger-list.js` | Trigger/List editor | Trigger source, list fields, completion and validation text | Editor presentation | translate_with_canonical_token | `trigger.*`, `workflow.*` | Prefer in-place | Enum/SCPI-style tokens and submitted fields remain canonical | P4 |
| `src/powers_tool_webui/static/sequence.js` | Sequence editor | Steps, loop, add/remove, import/export and validation summaries | Editor presentation | translate | `sequence.*`, `validation.*` | Prefer in-place; cached raw model if complete | Re-render can lose invalid drafts or focus | P4 |
| `src/powers_tool_webui/static/snapshot-restore.js` | Snapshot/Restore editor | Capture, file, preview, restore, confirmation, status and validation text | Editor/action presentation | translate | `snapshot.*`, `restore.*`, `validation.*` | In-place; cached presentation only | Must not capture, preview, restore, or clear state on switch | P4 |
| `src/powers_tool_webui/app.py` | Browser API responses | Explicit browser-displayed health/support/message fields | Presentation source/raw diagnostic | translate known browser wrapper; preserve_raw | `status.*`, `support.*`, `error.*` | Cache before presentation redraw | Backend remains authoritative; do not localize API output | P3/P4 |
| `src/powers_tool_webui/commands.py` | Command metadata | Explicit labels/descriptions plus IDs and parameter schema supplied to browser | Presentation metadata/machine schema | translate at browser boundary; machine_value | `command.catalog.*`, `form.*` | Use cached catalog metadata | Do not expand localization into command admission or Core | P3 |
| `src/powers_tool_webui/jobs.py` | Job message sources | Status/result/rejection/detail displayed by browser | Raw state/diagnostic | known semantic status may translate; preserve_raw detail | `job.*`, `status.*`, `error.*` | Browser redraw from cached raw state | Backend messages and rejection reasons remain original | P4 |
| `tests/webui/test_webui_static_shell.py` and static device/context tests | HTML/module assertions | Exact English headings, options, help and state strings | Test literal | English source tests or future structural/key assertions | `app.*`, `device.*`, `execution_mode.*` | N/A | Structural tests are coupled to full sentences | P2/P3 |
| `tests/webui/test_webui_static_command_catalog.py`, `test_webui_static_command_support.py`, `test_webui_static_controls.py` | Catalog/form/support assertions | English labels, descriptions, statuses and messages | Test literal | Source-locale assertions where intentional; otherwise semantic/raw assertions | `command.*`, `form.*`, `support.*` | N/A | Must continue testing canonical IDs and values separately | P3 |
| `tests/webui/test_webui_static_workflows.py` and workflow document tests | Editor assertions | English editor labels/messages and document field literals | Test literal/schema | Translate presentation tests; machine_value for schemas | `workflow.*`, `ramp_list.*`, `sequence.*`, `snapshot.*`, `restore.*` | N/A | Do not localize JSON document contracts | P4 |
| `tests/webui/test_webui_static_job_history.py`, `test_webui_static_result_summary.py`, `test_webui_static_live_data.py`, `test_webui_static_basic_controls.py` | Dynamic surface assertions | English summaries/statuses/empty states | Test literal | Locale-aware presentation assertions plus raw-state assertions | `job.*`, `result.*`, `live_data.*`, `basic_controls.*` | N/A | Existing literals conceal retranslation/state-preservation needs | P4/P5 |
| `tests/webui/_webui_shared.py` and `test_webui_native_module_graph.py` | Native module harness | Fixed production module list and compatibility transforms | Test infrastructure | not_user_visible | None | Include future locale modules | New modules will otherwise be absent from native graph tests | P1/P6 |
| `tests/webui/test_webui_api_contract.py`, packaging/release tests, `pyproject.toml` | Static assets/package graph | Explicit assets plus `static/*.js` collection | Packaging contract | not_user_visible | None | Include future modules where explicit | Wildcard collection is compatible, but explicit asset assertions need updates | P1/P6 |
| CLI, Core, driver, CSV/JSON/JSONL output | Non-browser interfaces | User and machine output outside the browser | Out of scope | out_of_scope | None | None | Must not be pulled into WebUI localization | None |

## 9. State-Preserving Locale Refresh Contract

Locale switching may regenerate browser presentation only. It must not reload,
call an API, create/submit/cancel/update a Job, start/stop/rebuild an EventSource,
start/stop/request Live Data, start/stop preview or monitor work, change execution
mode, selected command, resource, Expected Model, planning model/profile, write
authorization, form values, workflow documents, or any runtime option. It must
not clear command input, editors, Snapshot/Restore state, Job History, Workspace
Result, Result Detail, Live Data samples/charts/display state, or logs. It must
not rescan resources, request capability/support metadata, dispatch existing
event handlers, or cause VISA, SCPI, transport, or hardware behavior.

Refresh ownership is as follows:

| Surface | Allowed refresh | Forbidden action or prerequisite |
| --- | --- | --- |
| Static HTML | Update registered text and safe attributes in place. | Do not replace interactive containers or dispatch events. |
| Execution mode | P2 updates static radio labels, initial static help, title, and ARIA bindings in place. P3 updates dynamic badges, mode-specific help, identity labels, and Device/Resource summaries from raw state. | Locale refresh must not call `updateExecutionModeUi()` directly because it can modify controls, identity options, commands, or state; never change canonical mode or an identity slot. |
| Device/Resource summary | Re-label existing DOM or redraw from cached raw identity/resource/support state. | No scan, health fetch, selection change, or support request. Cache raw scan and latest health state before relying on redraw. |
| Command catalog | Re-label entries from cached catalog metadata while preserving raw command IDs and selection. | No catalog refetch or selection handler. |
| Command form | Update labels/help/options/validation presentation in place. | Do not clear or rebuild controls while editing; preserve raw draft state and user input. |
| Workflow editors | Update headings, labels, buttons, help, and known validation text in place; redraw only from a complete cached raw editor model. | No preview/run/import/export and no loss of invalid drafts, focus, selection, Loop, or completion-pulse state. |
| Basic controls | Update labels and known status wrappers in place. | Never read/write output, protection, trigger, or device state. |
| Job History | Redraw from cached raw command/status plus semantic `{key, params, rawFallback}` descriptors. | Use cached semantic descriptors for retranslation; no Job API action. |
| Workspace Result | Re-label or redraw from cached raw result/status and semantic summary data. | No result clear, refetch, or mutation. |
| Result Detail | Translate only surrounding heading/ARIA; preserve serialized raw JSON exactly. | Never translate keys or values or re-request detail. |
| Live Data | Update controls, known status text, titles, legends, and axis labels in place, or perform a presentation-only redraw using existing cached samples. | Must not fetch, append samples, create/close EventSource, or change monitor/preview state. Redraw must preserve samples, channel/window state, and connection state. |
| Status/log/error presentation | Re-render recognized semantic messages from key/params/raw fallback; retain unknown raw text. | Never infer application state from translated text or hide raw diagnostics. |
| Support summary | Re-render known presentation from cached authoritative support metadata. | No capability/support request and no admission decision from presentation. |

Known unsafe refresh paths include `updateDeviceResourceSummary()`,
`updateExecutionModeUi()`, `updateSelectedCommandState()`, `renderLivePanel()`,
`refreshHealth()`, `handleExecutionModeChange()`, and
`syncSelectedResource()` when they combine presentation with state mutation,
fetching, or event effects. During the P0 investigation, these paths were
identified as unsafe for direct locale refresh. The maintained implementation
separates or bypasses those effects rather than invoking the paths wholesale.

The P0 investigation also identified English-text state inference, insufficient
semantic Job History data, incomplete cached scan/health state, and unsafe HTML
construction as implementation prerequisites. These findings were addressed
during P3-P5 and are retained here as historical design rationale.

## 10. Testing And Acceptance Criteria

Maintained localization changes must continue to verify:

- committed English and `zh-TW` catalog key parity and English completeness;
- English fallback using a synthetic missing-translation catalog;
- named interpolation, text-only insertion, and missing/unknown key behavior;
- invalid saved locale handling, browser-language mapping, and storage
  read/write failure behavior;
- initial and runtime `<html lang>` updates;
- static text, placeholders, titles, ARIA labels, option display, and dynamic
  presentation in both locales;
- unchanged machine values, form values, canonical IDs, units, DOM/data
  contracts, API endpoints, and API payloads;
- preservation of unknown raw diagnostics and rejection/support reasons;
- zero API requests and zero Job creation/update/cancellation during locale
  switching;
- no EventSource creation/closure/rebuild and no Live Data acquisition or sample
  append during switching;
- unchanged execution mode, all identity slots, selected command/resource,
  Expected Model, planning model/profile, and write authorization;
- preservation of command form input, every workflow editor, Snapshot/Restore,
  Job History, Workspace Result, Result Detail, logs, cached Live Data samples,
  chart state, and monitor/preview state;
- presentation-only Live Data redraw from cached samples, including translated
  titles, legends, axes, and recognized status text;
- English source-locale literal tests where language is the subject, while
  structure/behavior tests assert semantic keys, raw values, or DOM structure;
- locale modules in the native module graph, `_webui_shared.py` harness,
  explicit static asset contracts, package contents, and standalone build.

The no-side-effect switching tests must instrument `fetch`, EventSource
construction/closure, reload, Job actions, preview/monitor actions, and state
snapshots. They must compare all protected state before and after multiple locale
switches.

## 11. Historical Implementation Phases

The following entries record the completed implementation phases. They provide
historical context and are not a current-status checklist; the maintained
runtime contract is defined in Sections 1-10.

### P1: Catalog And Runtime Contract

P1 completed the dependency-free foundation in `locale_en.js`,
`locale_zh_tw.js`, and `i18n.js`. The locale modules own frozen maintained
catalogs, while the pure runtime owns exact locale validation, lookup and
English fallback, optional raw fallback, named interpolation, and the initial
English singleton. The catalogs were empty at the end of P1 and are populated
with static presentation messages by P2.

### P2: Static Browser Presentation

P2 completed the minimal `dom_i18n.js` binding for text content, placeholders,
titles, and ARIA labels. `index.html` now binds the page title and brand,
Device/Resource static framing, execution radio labels and initial help, serial
controls, initial resource controls, Commands empty state and Run control, and
the static Result framing. English fallback prose remains in the HTML, and the
production singleton applies the English catalog once after the DOM is ready.

P2 preserves form values, IDs, `data-*` values, event bindings, and the existing
`<html lang="en">`. At the end of P2, browser-language detection, storage, a
language control, and runtime switching were deferred until P5. Dynamic execution
presentation, Device/Resource summaries, catalog/forms, workflows, Basic
controls, Job History entries, result content, and Live Data remain assigned to
P3 and P4.

### P3: Device, Resource, Execution, And Command Surfaces

P3 is complete. Device/Resource summaries, resource scan presentation,
known server/device health states, dynamic execution-mode badges and help,
identity labels and selector framing, command categories, maintained command
names and descriptions, and ordinary parameter-driven command forms now use
the production catalogs. Form localization covers labels, maintained
descriptions, compact help, ARIA labels, maintained option display text,
guidance, and command notes while preserving command IDs, parameter names,
option values, model/profile/resource values, and payloads.
Option translation uses parameter context so channel numbers remain channel
values while rear-pin fields use pin wording. Command-specific Trigger Step
labels and Ramp Loop labels retain their semantics during in-place refresh.

Resource scan presentation now uses explicit raw `not_scanned`, `scanning`,
`results`, `empty`, and `failed` state instead of option text. The latest raw
health readiness, hardware-lock, active-job, and failure detail are cached for
presentation-only redraw without a health request. Execution, Device/Resource,
health, command catalog, and ordinary command-form presentation have focused
refresh functions that do not call the state-changing execution-mode path,
select a command, rebuild the current ordinary form, submit/fetch a Job, or
touch EventSource state.
The initial cached health state presents Checking/Unknown until a health
response arrives; busy execution tooltips and Device/Resource toggle
accessibility text are also refreshed without changing control state.

At the end of P3, specialized workflow editors, Basic controls, Job History,
Workspace Result content, Result Detail content, Live Data, workflow operational
status, and general backend/client result wrappers were not yet localized; those
surfaces were deferred to P4. Locale selection, browser-language detection,
persistence, `<html lang>` switching, and the centralized whole-page refresh
controller were deferred to P5.

### P4: Workflows And Dynamic Operational Surfaces

Completed. Workflow editors, Basic controls, Job History, Workspace Result,
Result Detail surroundings, Live Data, and their known browser-owned
status/support/error presentation use the production catalogs. Surface-local
refresh paths update existing editor/control DOM or redraw cached presentation
without dispatching operations. History retains raw Job identity, command,
status, and result data so command labels and known summaries are produced at
render time; workspace summaries likewise render from cached raw results.
Live Data channel cards and protection presentation use explicit DOM nodes and
`textContent`, including cached-sample redraws.

Focused P4 review fixes also make workflow run/stop guidance render from
canonical workflow state, keep known Job History and Basic-control action
messages as semantic presentation state, and complete Basic-control and Ramp
List compact-help accessibility refresh. These paths translate at render time;
raw diagnostics and machine values remain unchanged.

Basic status refresh now follows an explicit current action instead of object
insertion order. Set-action titles and browser-owned output tooltips translate
at render time. Known `cleanup_failed` summaries use maintained translations
while their raw errors remain in Job and Result Detail data; unknown Job errors
and `error_code` values remain visible verbatim.

Workflow documents, command and option values, Job IDs, model/resource values,
units, serialized Result Detail JSON, exported artifacts, and unknown backend,
Core, VISA, SCPI, instrument, HTTP, support, validation, and file-parse detail
remain raw. At the end of P4, locale selection, browser-language detection,
persistence, `<html lang>` switching, and the centralized whole-page refresh
controller had not yet been added; P5 subsequently completed them.

### P5: Locale UI And State-Preserving Runtime Switching

Completed. The upper-right target-language button switches between English and
Traditional Chinese without reload. Initialization accepts only exact saved
`en` or `zh-TW` values, otherwise maps supported Traditional Chinese browser
tags, updates `<html lang>`, and tolerates navigator or localStorage failures.
Manual selection is persisted when storage is available.

The centralized presentation refresh composes the existing static, execution,
Device/Resource, command/form, workflow, Basic controls, Job History, workspace
result, Result Detail surroundings, and cached Live Data refresh paths. Repeated
switching tests preserve browser state, drafts, semantic/raw result data,
samples, machine values, and raw diagnostics while prohibiting requests, Job or
workflow actions, EventSource changes, acquisition, sample append, and reload.
Result panel toggle accessibility is recalculated from canonical collapsed state
after static translations are applied.
P6 subsequently completed terminology review, complete localization regression,
and documentation closeout.

### P6: Terminology, Regression, And Documentation Closeout

Completed. The final terminology review aligns maintained Traditional Chinese
presentation with the decisions above: Command uses `指令`, Job uses `作業`,
Real hardware uses `實機硬體`, and Live Data monitoring uses `監看`. Technical
tokens such as Real, Simulate, Dry-run, VISA, SCPI, BUS, LIST, ON/OFF, model
IDs, units, and raw diagnostic detail remain unchanged. Browser-owned
capability metadata presentation no longer leaves an unnecessary English phrase
in the Traditional Chinese message.

The final repeated-switch regression extends the P5 protected-state snapshot
across ordinary command values, execution and identity state, Ramp List,
Trigger List, Sequence, Snapshot/Restore, Job History, Workspace Result, Result
Detail panel state, and cached Live Data. It continues to require zero reloads,
requests, EventSource lifecycle changes, Job/workflow actions, acquisition, or
sample append while presentation text and accessibility attributes are
retranslated.

The maintained locales remain `en` and `zh-TW`; English remains the complete
fallback locale. Initial locale selection, persistence, runtime switching, and
the presentation-only boundary are defined in Sections 2, 6, and 9. Browser
presentation is translated, while command and parameter names, option and API
values, workflow/JSON fields, exported data, and unknown backend, Core, VISA,
SCPI, instrument, support, validation, file, and cleanup diagnostics remain
canonical or verbatim.

No-hardware P6 validation on 2026-07-23 included 56 focused localization,
switching, DOM, and native-module tests plus the complete 362-test
`tests/webui` suite, JavaScript syntax checking, and text/diff hygiene.
Localization P1 through P6 is complete, but this completion does not establish
release readiness or publication approval. Package, standalone, release, and
hardware validation remain separate workflows and were not performed for P6.

This split follows Powers ownership: execution modes and independent identity
slots require focused P3 work, while Job History, workflow editors, Basic
controls, and Live Data need raw-state and side-effect isolation before the P5
switch can safely refresh them. Meters remains a design reference for catalogs,
fallback, DOM binding, target-language control, and no-side-effect tests, but
Powers modules must not be copied file-for-file.
