# Powers Tool WebUI

FastAPI and static-asset WebUI adapter for Powers Tool.

The WebUI is a vendor-neutral product adapter for supported DC power supplies.
Current Product support is limited to the Product-active scopes documented in
[Supported Models](../core/supported-models.md); unknown live hardware remains
fail closed in Core.

This README is the WebUI behavior, API, validation, and maintainer guide. For
normal operator workflows, use the [WebUI User Guide](USER_GUIDE.md). For
developer and agent UI-change boundaries, use the
[WebUI Change Rules](web-ui-change-rules.md).

The WebUI and CLI are parallel product interfaces over the shared Core
runtime.

The WebUI ships inside the single `powers-tool` distribution while
preserving the `powers_tool_webui` import boundary. It depends on the
shared `powers_tool_core` runtime and the distribution's `webui` extra.
Its frontend is static `index.html`, `styles.css`, and native JavaScript modules
rooted at `app.js`; no Node toolchain is required. `app.js` is the bootstrap and
integration layer. `api.js` owns the shared JSON HTTP request/response boundary;
`execution-context.js` owns pure execution/workspace context; and `state.js`
owns initial page-local state. `device-resource.js` owns Device/Resource and
execution-mode controls. `command-form.js` owns command catalog/form rendering,
payload construction, guidance, accessibility help, and parameter constraints.
`results.js` owns job-result summaries and Workspace Result presentation.
`jobs.js` owns Job HTTP submission, SSE transport, and Job History state and
presentation. `live-data.js` owns Live Data sampling, lifecycle, and channel
presentation.
`json-files.js` owns shared browser JSON file picker and download helpers.
`ramp-list.js` owns pure Ramp List document materialization and
validation.
`trigger-list.js` owns pure Trigger List workspace document
materialization and validation.
`sequence.js` owns pure Sequence document normalization and
editor serialization through explicit action-schema dependencies.
`snapshot-restore.js` owns Snapshot and Restore schema validation and payload
materialization.
`basic-controls.js` owns Basic control action and Live-readback presentation.
`command-support.js` owns command-support and channel-capability presentation.
`workflows.js` owns the browser-facing Ramp List, Trigger List, Sequence,
Snapshot, and Restore editors plus their JSON Load/Save orchestration. It
receives only the state, document helpers, and application callbacks it uses
across module boundaries; document schemas remain owned by their focused
document modules.
`i18n.js` owns locale validation, catalog lookup, English fallback, and
interpolation. `locale_ui.js` owns browser-language detection, locale
preference storage, `<html lang>`, and the runtime language control.
`locale_en.js` provides the English source catalog, and `locale_zh_tw.js`
provides the maintained Traditional Chinese catalog.

`app.js` remains the bootstrap and composition root. Controller factory
parameters represent only dependencies supplied across module boundaries;
helpers owned by one controller call each other directly instead of being
routed back through `app.js`. `device-resource.js` privately owns the fixed
state-indicator class names and E3646A presentation model identifier used by
its Device/Resource and execution-mode presentation. `command-form.js`
continues to own command/form rendering, Trigger notes, and parameter and
electrical constraints. Workflow ownership is unchanged.

Frontend tests include a native module-graph smoke that imports the real
`app.js` graph root without rewriting its imports or exports. The existing
global compatibility harness remains available for broader frontend behavior
tests; it does not replace the native graph check.

## Package And Entry Point

The WebUI exposes the `powers-tool-webui` console command for the local
FastAPI server and the `powers-tool-webui-launcher` console command for the
Windows GUI launcher. The local shared PyInstaller onedir bundle contains
`dist\powers-tool\powers-tool.exe`,
`dist\powers-tool\powers-tool-webui-launcher.exe`, and the private
`dist\powers-tool\powers-tool-webui-host.exe`, all using the shared
`dist\powers-tool\_internal\` directory. The Desktop Host is a private
executable used by the source-mode Electron Desktop shell; it is not a new
public CLI entry point.

The source-mode Desktop shell is the existing WebUI in an Electron window. From
the repository root, run:

```powershell
Set-Location .\desktop
npm ci
npm start
```

It starts the private Host, opens a 1920x1080 window clamped to the primary
display work area, and follows the WebUI's System, Light, and Dark theme
preference. Multiple Desktop instances are allowed for different physical
instruments, but different clients must not operate the same physical
instrument resource concurrently.

## Environment

The root [README Install guide](../../README.md#install) is the canonical
setup reference. From the repository root, prepare the WebUI runtime with:

```powershell
uv sync --extra webui --locked --link-mode=copy
```

For tests or PyInstaller builds in this document, use the locked development
environment instead:

```powershell
uv sync --all-extras --locked --link-mode=copy
```

## Localization

The maintained locales are `en` and `zh-TW`; English is the source and
fallback locale. Locale selection switches at runtime without reloading the
page and is presentation-only: it must not create HTTP requests, Jobs,
workflow actions, or EventSource side effects. Machine values, API schemas,
command IDs, model IDs, VISA resources, SCPI, and raw diagnostics remain
unchanged. The locale preference uses the independent browser storage key
`powers-tool.webui.locale`; storage failures safely fall back without making
the WebUI unusable.

The upper-right header presents labeled Appearance and Language controls. The
Language control displays the current locale (`English` or `繁體中文`), while
its accessible name describes the destination locale. Appearance displays the
current theme preference and cycles through System, Light, and Dark. The theme
preference is stored in the `powers-tool.webui.theme` cookie with a one-year
expiry and is shared by the browser WebUI and the Electron shell. System mode
follows `prefers-color-scheme`; the Electron shell synchronizes its native
window theme from the same loopback cookie.
The selected theme applies to the main panels, cards, fields, and status
surfaces throughout the WebUI, not only the page background.
Dark theme keeps primary controls, status text, and unavailable or disabled
controls visually distinguishable against dark surfaces.

## Purpose

The WebUI adapter provides a local FastAPI and browser interface around the
shared Core runtime in `powers_tool_core`.

The WebUI owns:

- Browser interface and static assets under `src/powers_tool_webui/static/`.
- FastAPI route shape in `src/powers_tool_webui/app.py`.
- Local Tkinter launcher behavior in `src/powers_tool_webui/launcher.py`.
- Browser-facing request and response serialization.
- Job submission, job state display, and SSE event presentation.
- Live Data display state derived from read-only Core operations.
- Resource scanning display and command metadata rendering.

Core owns:

- SCPI command generation and instrument I/O.
- Runtime request validation and dry-run planning.
- Output, protection, trigger, sequence, ramp, snapshot, and restore behavior.
- Safety limits and model capability decisions.
- Physical-model and nonphysical planning-profile metadata projections.
- Stop, cancellation, release/local, close, and cleanup behavior.

The WebUI must use Core public APIs instead of importing CLI adapter code or
reimplementing instrument behavior.

## Job Parameter Admission

`POST /api/jobs` accepts only `command`, `runtime`, `parameters`, and optional
empty `artifacts` at its top level. Unknown top-level fields return HTTP 400.
`parameters` are admitted by the Core-owned command contract before a job is
queued or a hardware lock is acquired. The WebUI does not duplicate per-command
allowlists, aliases, or type coercion; invalid exact types, explicit nulls,
unknown/inapplicable fields, and alias conflicts return HTTP 400 rather than a
server error. The admitted canonical request is the one executed by the job.

## Run

From the repository root:

```powershell
uv run python -m powers_tool_webui.server --host 127.0.0.1 --port 7999
```

Open `http://127.0.0.1:7999/`.

Keep the host as `127.0.0.1` unless there is a deliberate reason to expose the
server beyond the local machine.

The installed Windows console wrappers are:

```powershell
# FastAPI server console wrapper
.\.venv\Scripts\powers-tool-webui.exe --version
# GUI launcher console wrapper
.\.venv\Scripts\powers-tool-webui-launcher.exe
```

With no arguments, the launcher starts automatically on `127.0.0.1`, beginning
at port `7999` and trying up to 100 ports through `8098`. The launcher remains
hidden during automatic startup. Each candidate is tested by binding the server
socket, so a port used by another Powers Tool WebUI or any other service is
skipped without opening that existing service. After the newly started WebUI
reports ready at `/api/health`, the browser opens and the launcher shows a
compact Running window containing only the actual bound URL, Running status,
and Quit.

Use `--port 9000` to try only port `9000`. If that fixed port cannot be bound,
the launcher reports the original bind error, cleans up, and exits with a
nonzero status; it does not try another port or open the manual port window.
Add `--auto-port` to explicitly try up to 100 ports beginning at the selected
port:

```powershell
.\.venv\Scripts\powers-tool-webui-launcher.exe --port 9000
.\.venv\Scripts\powers-tool-webui-launcher.exe --port 9000 --auto-port
```

Automatic candidates never exceed port `65535`. Only when every automatic
candidate fails because its address is already in use does the launcher show
the full port fallback window, report the attempted range, and allow a
different port to be entered manually. Start then tries only that port. If the
manually entered port is also in use, the full fallback window stays open and
re-enables the port field and Start button for another retry. A successful
fallback retry returns to the compact Running window.

A non-address-in-use bind failure stops automatic selection immediately.
Uvicorn or application initialization failures, an early server-thread exit,
and readiness timeout are also fatal startup failures. The launcher preserves
the original error details, requests the partially created server to stop,
closes its owned socket, waits briefly for its server thread, and exits with a
nonzero status. These failures never reopen the manual port window, including
when they occur during a manual fallback retry.

The launcher keeps the window available so Quit can stop its local Uvicorn
server. Quit first requests cancellation of active WebUI jobs, including Live
Data and simulation or dry-run workflows, and waits for their normal cleanup
before stopping the launcher-owned server. If job cleanup or server shutdown
times out, the launcher stays open and reports that shutdown is incomplete.
The compact/fallback presentation does not change port selection, startup
failure classification, cleanup, or process exit-code behavior.

The local shared PyInstaller GUI artifact is a separate executable at
`dist\powers-tool\powers-tool-webui-launcher.exe`; it is built from the same
launcher implementation but is not the installed server wrapper above.

## API

- `GET /api/health`: server and hardware-lock state.
- `GET /api/commands`: command metadata, confirmation flags, WebUI-only
  limitations, and Core-derived model-level exact live-support summaries.
- `POST /api/jobs`: submit a command job with `command`, `runtime`,
  `parameters`, and optional `artifacts`.
- `GET /api/jobs/{job_id}`: read current job state.
- `POST /api/jobs/{job_id}/cancel`: request cancellation.
- `GET /api/events?job_id=...`: job SSE stream with `id`, `event`, and `data`.
- `POST /api/live`: start live read-only polling.
- `GET /api/live/{job_id}/events`: live-data SSE stream.
- `POST /api/live/{job_id}/stop`: stop live-data polling.

Physical metadata from `/api/commands` is keyed only by canonical `model_id`
under `command_support_by_model_id`, `live_support_by_model_id`,
`channel_capabilities_by_model_id`, `electrical_ratings_by_model_id`, and
`setpoint_ranges_by_model_id`. The separate `planning_profiles` object carries
nonphysical profiles such as `generic-scpi`; it is never mixed into a physical
model map. Its metadata is projected directly from Core; WebUI only serializes
it with the command response. Evidence and private support metadata are not
exposed.

`/api/health` reports the adapter identifier `powers-tool-webui` for the
`package` field, while `version` is sourced from the single installed
`powers-tool` distribution.

## Runtime Boundary

The WebUI does not import `powers_tool_cli` and does not perform direct
VISA or SCPI operations. It maps HTTP payloads to core `RuntimeOptions` and
request objects, then calls `powers_tool_core.command_runner`.

Real hardware jobs are serialized by a single hardware lock. Simulate,
dry-run, offline metadata commands, and live-data jobs do not occupy that lock.
Synchronous core execution runs in a worker thread so FastAPI's event loop
continues serving health, job status, cancellation, and SSE endpoints.

Raw `/api/jobs` payloads use the V2 runtime identity fields. Dry-run accepts
exactly one of `runtime.planning_model_id` or
`runtime.planning_profile_id`; simulator mode accepts only the physical
planning ID. Live execution accepts only optional `runtime.expected_model_id`.
Core queries `*IDN?`, resolves manufacturer plus model, fails before
command-specific SCPI if the expected canonical model differs, and never lets
the guard override the IDN-selected driver.

Dry-run example:

```json
{
  "command": "trigger-step",
  "runtime": {
    "resource": "USB0::FAKE::E36312A::INSTR",
    "dry_run": true,
    "simulate": false,
    "planning_model_id": "keysight-e36312a"
  },
  "parameters": {
    "channel": 1,
    "source": "bus",
    "fire": true
  }
}
```

Legacy `runtime.model_profile` and `runtime.model` fields are rejected. The
WebUI does not infer a dry-run/simulate model from fake or live-looking resource strings;
use a V2 planning field or a deterministic SIM resource such as
`USB0::SIM::E36312A::INSTR`. WebUI live resource support is learned from
scan/job IDN metadata. The browser provides page-local Real, Simulate, and
Dry-run execution modes. It always reloads in Real mode and never persists
mode, identity, or write authorization in browser storage. Simulate requires a
canonical physical planning model; Dry-run accepts either a physical planning
model or a planning profile. No-hardware requests omit the live resource,
serial settings, expected-model guard, and confirmation.

Raw runtime values are type-strict. Boolean fields accept only JSON `true` or
`false`; strings such as `"false"` never satisfy confirmation or enable a
mode. Integer, string, identity, and serial-option fields are likewise
validated before job submission. Raw `parameters.channel` accepts only an
exact positive JSON integer or exact `"all"` for commands that support it;
booleans, floats, and numeric strings are not coerced. Core-owned command admission rejects missing
or conflicting planning identity and malformed restore/snapshot booleans
before creating a WebUI job. Unknown commands and commands intentionally
unsupported by `/api/jobs` are also rejected synchronously before job or task
creation. Physical model
options and every model-keyed support/rating map are generated from the same
Core Product-active metadata inventory; `generic-scpi` remains a separate
nonphysical planning profile.

The browser and raw WebUI jobs always use the product support-policy mode.
Validation-policy runtime fields are rejected, not ignored. Frontend enabled
state is UX only: Core remains the final IDN-selected exact-scope authority,
and pending transport/backend scopes are not product-open.

Cancelling an executing job first moves it to non-terminal
`cancel_requested`. The WebUI keeps `active_job_id` and the hardware lock until
the current thread I/O and Core stop cleanup finish. Only then does the job
become `cancelled`; cleanup failure makes it `failed`. Accepted jobs that have
not started can become `cancelled` immediately.

For Ramp, Ramp List, and Sequence, the primary Run button is stateful:
`Run`, `Starting...`, red `Stop`, `Stopping...`, then `Run` only after the
terminal SSE event confirms the active job was cleared. Stop means “Stop the
active workflow and safely turn all outputs off.” While cleanup runs, the UI
shows `Waiting for safe-off and cleanup` and keeps command switching and Live
Data hardware access blocked. SSE interruption uses job-status reconciliation;
normal completion does not require an extra health/lock poll.

## UI

The static UI is a three-panel dashboard:

- package-versioned title area and top connection bar for resource selection
  and health;
- Basic command panel for direct per-channel setpoint and output shortcuts;
- collapsible command rail populated from `/api/commands`;
- generated command form with typed controls and a graphical Sequence
  step-card editor, shown by the advanced command toggle;
- right panel for live trend canvas, live table, job history, and result JSON.

Machine-facing command IDs remain kebab-case. Human-facing WebUI command names
use spaces and sentence case.

The connection area includes a **Supported devices** read-only list and advanced device options. In Real mode, `Expected model`
defaults to `Auto-detect`, which omits `runtime.expected_model_id`. Auto-detect
uses the connected instrument IDN for live operation. Selecting `Require
<model>` sends the canonical `runtime.expected_model_id` as a live safety guard and may
drive frontend command, channel, and rating planning when metadata exists. The
Device / Resource summary shows the detected live model separately from the
expected model selection, such as `live E3646A / Auto-detect` or `live E3646A /
Require E36312A`. A selected model never overrides the IDN-selected live
driver; Core remains the authority for live mismatch rejection before setup or
write SCPI. The Device / Resource header displays the page-local write
authorization state as `Real · Writes locked` or `Real · Writes enabled`; the
badge is not interactive, and authorization remains controlled by Device
options. In Real mode, a non-blank VISA resource creates write authorization
for the exact current resource, expected-model guard, and detected model
context by default. The Device options checkbox can disable writes for that
unchanged context. Selecting or typing another resource, changing Expected
model, detecting a different model, or returning to Real mode creates a new
context with writes enabled by default. With no resource, the checkbox is
disabled and no authorization exists.
The serial fields are optional; blank fields are omitted from the runtime
payload and do not override VISA backend or Connection Expert settings.
Read/write termination fields accept `CR`, `LF`, `CRLF`, and `NONE` aliases.
`NONE`, blank, or omitted termination means no termination override is applied.

The frontend command rail may hide or disable unsupported commands for
operator clarity, but this is UX only. Direct `/api/jobs` submissions still
pass through WebUI backend validation and Core support gates, so unsupported
model/command/mode combinations are rejected even when a caller bypasses the
browser controls.

The browser distinguishes profile support from exact Product-mode live
availability. Before a real resource has returned capabilities, commands keep
their model-planning behavior and show that the connection scope has not been
evaluated. A successful resource-backed `capabilities` result on an already
Product-open scope, or a successful real `identify` diagnostic, adds the
IDN-detected model, normalized transport/backend scope, and per-command exact
status. The diagnostic path reads identity under the expected-model guard but
does not open pending feature commands. Validated commands remain available;
pending or missing exact scopes are shown disabled with distinct reasons,
while identity/status diagnostics remain explicitly policy-exempt. Changing
the resource clears this exact context until capabilities or identity are read
for the new resource.

If a successful `identify` or `verify` diagnostic detects an unknown or
de-scoped model, the diagnostic result remains available but its support
projection is unevaluated and contains no command availability. That neutral
result clears stale exact context and does not enable Generic fallback; normal
model-aware live commands still fail closed. An expected-model mismatch still
fails the diagnostic before optional support metadata is attached.

The Device / Resource summary shows the detected model, expected-model guard,
transport/backend scope, and compact validated/pending/unavailable counts when
that exact context is known. Pending metadata appears only when the actual
runtime transport/backend matches a registered pending scope. WebUI remains
Product-only and the standard browser uses the default system-VISA backend; it
has no validation mode or VISA-backend selector. These displays and disabled
controls are UX; the Core post-IDN exact-scope gate remains authoritative.

The safe Core projection can also include additive `sequence_action` and
`trigger_source` inventories for an exact scope. These entries expose status
and Product availability only; they do not expose evidence or internal notes.
The projection contract is schema version 2: evaluated physical results use
canonical `model_id`, while unevaluated diagnostics keep reported manufacturer
and model separate from a nullable resolved `model_id`. The projection never
exposes evidence IDs, historical paths, checksums, or private evidence notes.
Because documents and trigger requests select features at run time, the
command rail remains command-level and does not globally disable a command
merely because another future feature is pending. Core validates the actual
normalized request features after IDN and before feature-specific SCPI.

The Product model selector contains Product-active models only. Candidate,
catalog-only, and de-scoped models are not browser runtime choices; there are
currently no candidates. WebUI remains
Product-only and provides neither a candidate bootstrap control nor a backend
or validation selector.

Pure offline utilities are classified separately from identity/status
diagnostics. They do not represent Product-open live commands and are not
described as policy-exempt hardware diagnostics.

The `set` command accepts Voltage, Current, or both in Basic command and
Commands. Blank setpoint fields are omitted from the job payload and left
unchanged by Core; Live Data/readback remains the source for complete
instrument setpoint state.
Voltage is the output voltage setpoint, and Current is the output current
limit/current setting for E36312A, EDU36311A, and E3646A. `/api/commands`
includes official setpoint programming-range metadata for these active models.
E3646A metadata is range-dependent for LOW/P8V and HIGH/P20V; the current
WebUI does not add a range selector from that metadata. Browser constraints
and hints are UX only, and backend Core validation remains authoritative. The
metadata does not introduce hard decimal-place rejection or silent
rounding/truncation.
Basic output controls are lit-state ON buttons: an unlit ON control represents
OFF/unknown, and a lit ON control represents ON according to fresh Live Data.
E3646A uses one global output switch: its CH1 and CH2 output controls are
disabled and identify that they are controlled by ALL, while their Voltage,
Current, and Set controls remain independent. The E3646A ALL control remains
available when readback is unknown and submits output-on; fresh Live Data
continues to determine the displayed hardware state after the command.

The Live Data status row uses LED indicators for WebUI State, Command State,
and Live State. Command State reports whether the WebUI command path is free
to accept real hardware jobs; it reflects the WebUI hardware I/O lock, not an
instrument-internal state register. Live State remains tied to real Live Data
readback and one-shot post-command refreshes.

The frontend keeps one job SSE controller and one live-data SSE controller.
Ramp List uses a dedicated segment-card editor with versioned JSON Load/Save.
It loads v2/v3/v4/v5 and always saves strict v5 with explicit `enable_output`,
`loop_count`, and `channels`, including loop count 1. Each Segment has a
model-aware channel-combination selector and may use a different combination;
All is saved as the model's explicit canonical channel list. The editor supports
up to 10 ordered segments and full-list channel/rating/trip guarding before
submission.
For Ramp and each Ramp List segment, `Wait between steps (ms)` applies only
after a non-final voltage step. Ramp List `Wait after final step (ms)` applies
after the final voltage step and before that segment completes.
Sequence uses collapsed step cards with JSON Load/Save and supports up to 250
steps in the WebUI. It loads v1 as one execution and always saves/runs strict
v2 as `{"version": 2, "loop_count": N, "steps": [...]}`. It never serializes
the internal camel-case state name. CLI and Core have no WebUI step limit.
Job Result history is expanded by default and can be collapsed or cleared
without changing Result Detail.

### Pulse Workflows

Cycle Output exposes an optional finished pulse. Ramp uses one Pulse timing
selector: None, Every step, Ramp complete, or Loop complete. Ramp List uses
None, Every step, Segment complete, or Loop complete. Sequence retains only
its per-Step Trigger pulse action.
For a multi-channel Ramp List Segment, Every-step and Segment-complete fire once
using the first canonical selected channel as an internal anchor. Loop-complete
uses the last Segment's first canonical channel. The anchor is not configurable.

Ramp places Enable output first, then Enable loop, Channel/Current, Ramp
setpoints, and Pulse timing. Its Channel selector is generated from the
current model metadata: single channels are followed by channel combinations
and All when the model has multiple channels. Singletons submit `channel`;
combinations and All submit an explicit canonical `channels` list. All selected
channels share the same Ramp parameters and advance as lockstep logical steps.
The full-width multi-channel helper appears below Channel and Current only for
a channel combination or All; a single-channel selection leaves no empty helper
row, so the remaining Ramp parameters stay aligned in the two-column form.
Ramp List places Enable loop between Auto-enable
output for each channel and Pulse timing. Sequence places Enable loop between
its toolbar and Step 1; Create snapshot has no Loop state. Loop count is
conditionally created inline only when enabled, defaults to 2, and accepts
integers 2 through 10,000.

Ramp, Ramp List, and Sequence admission allows at most 1,000,000 logical
execution units and shows a long-running warning above 100,000. Workflow jobs
publish integer-percent execution-unit progress through the existing Job/SSE
stream. Results retain at most the first 100 and last 100 execution details
with additive truncation metadata; aggregate counters still describe all
completed work.
Turning Loop off removes the field, makes the effective value 1, and resets a
selected Loop-complete pulse to None. The Loop-complete option is disabled
while Loop is off. An invalid enabled Loop count remains visible across editor
re-renders and keeps Run and Save disabled until it is corrected or Loop is
explicitly turned off. If Ramp List Loop-complete timing was selected, an
invalid draft temporarily disables that option without clearing the selection;
correcting the count immediately restores the option and selection.

Pulse rear pins are independent of output channels and are E36312A-only.
Controls are disabled when the selected resource is definitively known to be
another model. While identity is unknown, pulse details remain configurable,
but Run stays blocked with E36312A planning/support guidance until a suitable
model is selected or detected.
Pulse detail fields in Cycle Output and Ramp appear only after a pulse option
is enabled. Rear-pin fields use a selector for every valid pin combination,
including All. Ramp and Ramp List Every-step pulse accept a zero millisecond
additional delay.

E3646A Ramp List shows a model-aware note beside Auto-enable output. Because
this model's output enable is global, Core pre-stages the first safe setpoint
for every channel used by the list before enabling output once.

Workflow completion pulses are software-scheduled post-action `*TRG` pulses,
not native LIST execution. They temporarily modify and restore trigger/rear-pin
settings, and global `*TRG` may affect other armed BUS behavior. Sequence
Trigger pulse `Leave configured` controls only whether those settings are
restored after the pulse; it does not keep the pulse trigger armed and may
affect later Sequence steps or other BUS triggers.

### Trigger Execution

Trigger Fire sends global `*TRG` to every armed BUS trigger. Its Abort target
channel is required only when Wait complete is enabled and is used only if the
instrument-wide completion wait times out or is interrupted.

For Trigger Step and Trigger List, Immediate starts when `INIT` is sent, so
Fire now is cleared and disabled. BUS Wait complete requires Fire now in the
same command. A LIST that starts without Wait complete requires Leave
configured; select Wait complete to restore after completion or Leave
configured for asynchronous execution.

### Trigger List Workspace

Trigger List uses a dedicated three-channel workspace editor. Each channel
keeps its own count and 1 to 100 step rows with Voltage, Current, Dwell, BOST,
and EOST. Run submits only the selected channel. Load/Save uses strict
`powers-tool-trigger-list-workspace` version 1 JSON and preserves all three
channel drafts plus shared controls. Enabled BOST/EOST rows require LIST
output pins.

When Wait complete is selected and Leave configured is off, completion writes
back the pre-run Trigger settings and LIST table. The running table may be
briefly visible before restore. Select Leave configured to retain the new
table and Trigger settings.
Live Data samples include parsed model identity and channel-local OVP/OCP trip
state. A valid Live Data model can repair the selected resource's command
support cache; results without a model do not replace an already known model.
For PSM-2010, the CH1 card also shows the current actual LOW/HIGH output range
as a read-only badge. It shows `--` when the range is unknown or not yet
available; other models do not show this badge.

Fresh, explicit channel trip state adds a WebUI soft guard for direct output
commands targeting that channel. Stale or unknown trip state does not add a
guard. Safe/off and recovery commands remain available.

Commands are grouped into Output, Output Workflows, Protection, Trigger,
Snapshot, and Advanced Diagnostics. Clear Protection is under Protection and
still requires explicit confirmation. A tripped channel card can open and
prefill the form without executing it. Clear Status / Errors is separate and
does not clear OVP/OCP protection latches.

Advanced Diagnostics exposes Clear Status / Errors, Get capabilities, Read
device information, and Read errors. The Workspace keeps the latest successful
result for each complete execution context: Real includes resource, Expected
Model guard, and resolved canonical identity; Simulate and Dry-run include
their physical planning model or planning profile. Result Detail keeps the
complete raw job payload. Read errors removes each returned entry from the
instrument error queue.

## Limits

Commands outside the WebUI surface are marked disabled by `/api/commands` and
return `not_implemented_in_webui` if submitted directly. No hardware tests are
run from this package by default. Model feature-lock policy is also enforced
for direct `/api/jobs` submissions: EDU36311A trigger/native LIST and
snapshot/restore jobs, E3646A protection/trigger/native LIST/snapshot/restore
and completion-pulse jobs, and unsupported E3646A sequence step types are
rejected by the backend/Core boundary.

Live validation evidence is recorded by CLI suite artifacts, not created by
the browser selector. The WebUI only displays a safe Core projection of the
current policy; it does not expose evidence paths or promote status. Suite
names are evidence groupings and do not open every command in a feature
family. Core requires an exact canonical `model_id`, command, transport,
backend, and required-feature scope; missing and pending scopes fail closed.
The authoritative current
command list is the
[Product LIVE exact-scope matrix](../core/supported-models.md#product-live-exact-scope-matrix).
WebUI hiding or disabling remains UX only; backend/Core rejection is still the
safety boundary for unsupported direct submissions.

The WebUI expected-model field is a safety guard and planning hint only. It
does not change the IDN-selected live driver or cause the browser to open a
different connection type. Current recorded opening status is connection-
scoped; only commands in the Core exact matrix are opened:

- E36312A USB + system VISA
- E36312A LAN + system VISA
- EDU36311A USB + system VISA
- EDU36311A LAN + system VISA
- E3646A ASRL / RS-232 + system VISA
- PSM-2010 ASRL / RS-232 + system VISA

Only exact commands in the Core product matrix are opened on those
connections. E3646A and PSM-2010 remain restricted to ASRL / RS-232 + system
VISA; their USB and LAN paths remain outside the current scope. PSM-2010 opens
the exact 23 model-aware commands in the Core Product matrix, including
setpoint/output, protection, snapshot/restore, ramp, and software-sequence
workflows. Powers Trigger commands remain unsupported.

| Model | USB | LAN | ASRL / RS-232 |
| --- | --- | --- | --- |
| E36312A | accepted exact commands | accepted exact commands | N/A |
| EDU36311A | accepted exact commands | accepted exact commands | N/A |
| E3646A | not current scope | not current scope | accepted exact commands |
| PSM-2010 | not current scope | not current scope | accepted exact commands |

E36312A `full` now includes `software-sequence` in addition to read-only,
output, protection, snapshot, and trigger-list suites. EDU36311A `full` now
includes `software-sequence` in addition to read-only, output, and protection
suites; EDU36311A trigger/native LIST and snapshot/restore remain disabled.
E3646A `full` remains `readonly`, `output`, and `software-sequence`; E3646A
`ramp-list` and `sequence` are software workflows, not native LIST, and
protection, trigger/native LIST, snapshot/restore, and completion-pulse remain
disabled.


## Test

```powershell
uv run python -m pytest tests/webui -q -p no:cacheprovider
```

Focused command classification and job admission validation:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\webui\test_webui_api_jobs.py -q -p no:cacheprovider
```

WebUI job tests (`tests/webui/test_webui_api_jobs.py`) include a Core-to-WebUI
command classification drift guard ensuring all formal Core commands in
`COMMAND_CONTRACTS` are explicitly partitioned between `SHARED_CORE_COMMANDS`
and `WEBUI_UNSUPPORTED_COMMANDS` without silent fallback or overlap.

Focused launcher and package validation:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\webui\test_launcher.py tests\webui\test_webui_import.py tests\core\test_distribution_metadata.py -q -p no:cacheprovider
```

After editing WebUI JavaScript, also run:

```powershell
node --check src\powers_tool_webui\static\execution-context.js
node --check src\powers_tool_webui\static\electrical.js
node --check src\powers_tool_webui\static\app.js
```

Broader no-hardware validation when practical:

```powershell
uv run python -m pytest tests -q -p no:cacheprovider
```

Build the local shared Windows onedir bundle from the locked development
environment described above. PyInstaller is provided by the `dev` extra and
does not need a separate install:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows_bundle.ps1
```

After building, confirm the shared-bundle launcher reports the package version:

```powershell
.\dist\powers-tool\powers-tool-webui-launcher.exe --version
```

Numeric field limits come from the shared
[Commands parameter contract](../contracts/commands-parameter-contract.md).
After a resource model is identified, the UI applies verified official
independent-channel DC output ratings and disables Run for known over-rating
requests. Unknown models do not receive invented limits; Core remains
authoritative.

## Documentation Map

- [WebUI User Guide](USER_GUIDE.md): operator-facing WebUI usage guide.
- [WebUI README](README.md): this WebUI behavior, API, validation, and
  maintainer guide.
- [WebUI Change Rules](web-ui-change-rules.md): maintainer and agent-facing
  rules for UI changes.
- [Localization Contract](localization-contract.md): maintained browser
  localization and presentation-only runtime contract.
