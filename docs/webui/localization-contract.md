# WebUI Localization Contract

## Purpose and Current Status

This document defines the maintained localization contract for the Powers Tool
browser WebUI. The supported locales are `en` and `zh-TW`. English is the
source and fallback locale, and localization is limited to presentation owned
by the browser WebUI.

The contract applies to catalogs, locale selection, DOM presentation, dynamic
browser-owned summaries, and state-preserving runtime switching. It does not
change Core, CLI, API, SCPI, VISA, transport, Product support, or diagnostic
behavior.

The CLI, Core, drivers, workflow file schemas, CSV, JSON, JSONL, logs, exported
artifacts, and raw diagnostics remain outside WebUI localization ownership.
Backend modules may provide presentation metadata or message sources, but Core
and backend data remain authoritative.

## Locale Resolution and User Interface

The maintained constants are:

```text
SOURCE_LOCALE = "en"
FALLBACK_LOCALE = "en"
SUPPORTED_LOCALES = ["en", "zh-TW"]
LOCALE_STORAGE_KEY = "powers-tool.webui.locale"
```

Initial locale resolution uses this precedence:

1. Use the saved locale only when the storage value is exactly `en` or
   `zh-TW`.
2. Otherwise select `zh-TW` when the browser language matches `zh-TW`, a
   `zh-TW-` prefix, `zh-Hant`, or a `zh-Hant-` prefix.
3. Use `en` for all other browser languages and saved values.

Saved-locale validation is exact and does not perform case folding, underscore
replacement, or permissive canonicalization. Browser-language matching is
case-insensitive and normalizes `_` to `-`. Other Chinese language tags do not
map to `zh-TW`.

The locale control is a single button in the upper-right of the main
interface. It displays the target language: `繁體中文` in English and `English`
in Traditional Chinese. Switching takes effect immediately,
updates `<html lang>`, and persists a manual selection when storage is
available. Storage read or write failures must not make the WebUI unusable.

## Ownership and Architecture Boundary

The browser owns presentation such as headings, labels, help text, option
display text, placeholders, titles, ARIA labels, empty states, known status and
summary text, and known browser-generated validation or error presentation.

Localization must never become an input to validation, authorization,
capability selection, identity selection, Product admission, support decisions,
or runtime behavior. It must not change:

- Real, Simulate, or Dry-run semantics or their separate identity slots;
- Expected Model, planning model, or planning profile semantics;
- fail-closed command admission, Product support, model lifecycle, or feature
  status;
- request and response schemas, command IDs, command values, Job behavior, or
  workflow document fields;
- Stop, safe-off, cleanup, local/release, Restore, SCPI, VISA, transport,
  backend, hardware-lock, evidence, or Product promotion boundaries.

`app.py`, `commands.py`, and `jobs.py` remain backend-owned. Only explicit
browser-facing presentation metadata or message sources are localized. Unknown
Core, backend, validation, VISA, SCPI, instrument, HTTP, support, admission,
and rejection details remain verbatim.

## Non-Translatable Machine Contracts

Display text may be translated, but these values must neither be translated
nor derived from translated text:

| Contract area | Protected values | Rule |
| --- | --- | --- |
| HTTP interface | Endpoints, methods, status codes | Preserve exactly; locale switching makes no request. |
| API schema | JSON keys, booleans, enum values, schema versions | Preserve exactly in payloads and logic. |
| Commands | Command IDs and command-count semantics | Translate labels and descriptions only. |
| Models and support | Model IDs, Product IDs, capability and support values | Keep authoritative raw values; never infer support from a label. |
| Planning | Planning model and profile IDs | Keep submitted and stored IDs unchanged. |
| Execution | `real`, `simulate`, `dry-run`, and runtime status values | Translate presentation only; compare canonical state. |
| Device communication | Transport/backend values, VISA resources, SCPI tokens | Preserve verbatim and never interpolate as HTML. |
| Electrical data | Channel values, units, and numeric values | Preserve values and units; translate surrounding labels only. |
| Forms and DOM | Form names/values, DOM IDs, and `data-*` values | Translate associated presentation nodes or safe attributes only. |
| Workflow documents | Paths, field names, enums, JSON structure, schema versions | Do not translate submitted, saved, previewed, or restored data. |
| Artifacts | CSV, JSON, JSONL, and machine-readable fields | Outside browser localization ownership. |
| Diagnostics | Unknown error, rejection, validation, support, HTTP, VISA, SCPI, and instrument text | Preserve original text as a visible fallback. |

## Catalog, Keys, Interpolation, and Fallback

Translation keys are semantic, stable, and independent of presentation wording.
Use dot-separated namespaces with lowercase `snake_case` segments. Do not use
complete English sentences, DOM IDs as the only meaning, array indexes, or
locale names in keys.

The maintained namespace families are:

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

Dynamic messages use named interpolation such as `{command}`, `{channel}`,
`{count}`, `{model}`, `{path}`, or `{status}`. Positional interpolation is not
allowed. Catalog strings and parameters are inserted as text with
`textContent`, explicit text nodes, or a fixed safe attribute; they must never
be executed or interpreted as HTML.

Lookup order is:

1. the selected locale key;
2. the English key;
3. an explicitly supplied raw fallback;
4. the semantic key as a diagnosable last resort.

The committed English and Traditional Chinese catalogs must have key parity.
An absent Traditional Chinese key falls back to English. An absent English key
is a catalog contract failure. Unknown semantic keys and unknown raw backend
details must remain diagnosable and must not be hidden or replaced by an empty
string.

## Current Traditional Chinese Terminology

The following terms are the maintained presentation choices. Canonical machine
values and technical tokens remain unchanged.

| English term | `zh-TW` display | Keep token | Context |
| --- | --- | --- | --- |
| Real | 實機（Real） | Yes | Execution mode |
| Simulate | 模擬（Simulate） | Yes | Execution mode |
| Dry-run | Dry-run（規劃） | Yes | Execution mode |
| Device | 裝置 | No | Device identity and summary |
| Resource | 資源 | No | Resource selection and scan |
| VISA Resource | VISA 資源 | Yes | Communication resource |
| Expected Model | 預期型號 | No | Real identity guard |
| Planning Model | 規劃型號 | No | Non-Real planning |
| Planning Profile | 規劃設定檔 | No | Dry-run planning |
| Command | 指令 | No | Command catalog |
| Parameter | 參數 | No | Command form |
| Job | 作業 | No | Queued execution |
| Job History | 作業歷程 | No | History panel |
| Workspace Result | 工作區結果 | No | Latest result summary |
| Result Detail | 結果詳細資料 | No | Raw JSON detail heading |
| Live Data | 即時資料 | No | Real-only monitoring |
| Basic controls | 基本控制 | No | Direct controls |
| Ramp List | 斜坡清單 | No | Workflow editor |
| Sequence | 序列 | No | Workflow editor |
| Snapshot | 快照 | No | State capture |
| Restore | 還原 | No | State restoration |
| Protection | 保護 | No | OVP/OCP presentation |
| Trigger | 觸發 | No | Trigger workflow |
| Pulse | 脈衝 | No | Completion pulse |
| Output | 輸出 | No | Channel output |
| Channel | 通道 | No | Channel selection and status |
| Pending | 待驗證 | No | Support-validation context; canonical support values remain unchanged |

## Current Presentation Surfaces

The current browser presentation boundary includes:

| Surface | Localized content | Invariant |
| --- | --- | --- |
| Static HTML | Headings, help, buttons, placeholders, titles, and ARIA text | Update presentation without replacing interactive containers or dispatching events. |
| Execution mode | Labels, badges, help, identity labels, and mode summaries | Preserve canonical mode and all identity slots. |
| Device and Resource | Scan state, resource display, identity, health, and support summaries | Use cached raw state; do not scan, fetch health, or change selection. |
| Command catalog and form | Categories, labels, descriptions, options, help, and validation presentation | Preserve raw command IDs, parameter names, option values, and drafts. |
| Workflow editors | Workflow controls, field labels, guidance, validation text, and cached summaries | Preserve invalid drafts, focus, selection, documents, Loop, and completion-pulse state. |
| Basic controls | Labels, action status, and known browser-owned messages | Never read or write output, protection, trigger, or device state. |
| Job History | Known labels, summaries, status, and controls | Redraw from cached raw Job state and semantic descriptors; perform no Job API action. |
| Workspace Result | Known summaries, status, actions, and Result Detail heading | Preserve raw result data and serialized JSON exactly. |
| Live Data | Controls, status text, titles, legends, axes, and cached channel cards | Redraw from existing samples only; do not acquire, append, or alter connection state. |
| Errors and support | Known semantic wrappers and raw fallback detail | Preserve unknown diagnostics and authoritative support metadata. |

## State-Preserving Locale Switching

Locale switching may regenerate browser presentation only. It must not reload,
call an API, create or modify a Job, start or stop a workflow, rebuild an
EventSource, start or stop Live Data, change execution mode, selected command,
resource, Expected Model, planning model/profile, write authorization, form
values, workflow documents, or runtime options.

It must not clear command input, editors, Snapshot/Restore state, Job History,
Workspace Result, Result Detail, Live Data samples/charts, or logs. It must not
rescan resources, request capability/support metadata, dispatch existing event
handlers, or cause VISA, SCPI, transport, or hardware behavior.

Refresh paths must use cached raw state and semantic descriptors. In particular,
presentation refresh must not call a state-changing execution-mode update,
resource scan, health refresh, command selection handler, Job action, preview,
monitor operation, or EventSource lifecycle operation.

## Maintained Verification Requirements

Localization changes must continue to verify:

- English and `zh-TW` catalog key parity and English completeness;
- English fallback with a synthetic incomplete translation catalog;
- named interpolation, text-only insertion, and missing/unknown key behavior;
- exact saved-locale validation, browser-language mapping, and storage failure
  fallback;
- initial and runtime `<html lang>` updates;
- static and dynamic presentation in both locales;
- unchanged machine values, form values, canonical IDs, units, DOM/data
  contracts, API endpoints, and API payloads;
- preservation of unknown raw diagnostics and support/rejection reasons;
- zero API requests and zero Job creation, update, or cancellation during a
  locale switch;
- no EventSource lifecycle change, Live Data acquisition, or sample append;
- unchanged execution, identity, selected command/resource, planning state, and
  write authorization;
- preservation of forms, workflow editors, Snapshot/Restore, Job History,
  Workspace Result, Result Detail, logs, cached samples, chart state, and
  monitor/preview state;
- locale modules in the native module graph, static asset contracts, package
  contents, and standalone build inputs.

Tests should assert semantic keys, raw values, structure, and side-effect
boundaries. Exact English source-locale literals are appropriate only when the
language itself is the subject of the test.
