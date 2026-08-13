# Powers Tool WebUI User Guide

This guide is for operators who receive the built WebUI launcher and use it to
inspect and control supported DC power supplies. The framework is
vendor-neutral, while current hardware support is defined by the documented
[Product scopes](../core/supported-models.md). This guide avoids developer
details and focuses on normal local WebUI workflows. Developer setup, API behavior,
validation, and UI change boundaries are documented in the
[WebUI README](README.md) and [WebUI Change Rules](web-ui-change-rules.md).

## Start The WebUI

For normal use, double-click the WebUI launcher provided with the release or
local build:

```text
powers-tool-webui.exe
```

To confirm the launcher version from PowerShell:

```powershell
.\powers-tool-webui.exe --version
```

Release folders may include a versioned launcher name, such as:

```text
powers-tool-webui-<version>.exe
```

With no command-line options, the launcher remains hidden while it
automatically tries port `7999` followed by up to 99 higher ports. Wait for the
browser to open. After startup succeeds, the launcher shows a compact Running
window with the actual URL, Running status, and `Quit`; the port settings and
`Start` are hidden.

Only if every automatic candidate is already in use does the launcher show the
full port settings window. Enter another local port and click `Start`. If that
manually entered port is also in use, the full fallback window stays open and
lets you edit the port and try again. After a retry succeeds, the launcher
returns to the compact Running window.

From PowerShell, `--port` requests one fixed port. It never switches to another
port unless `--auto-port` is also supplied:

```powershell
.\powers-tool-webui.exe --port 9000
.\powers-tool-webui.exe --port 9000 --auto-port
```

A fixed-port conflict reports the selected port and exits instead of opening
the manual port window. Other startup failures, including application startup,
server exit, or readiness errors, also report their original details, clean up,
and exit. Only automatic address-in-use exhaustion opens the manual fallback,
and only another address-in-use error keeps that fallback window open.
This window presentation does not change port selection, startup failure,
cleanup, or exit-code behavior.

If the browser does not open automatically after the launcher reports that the
server is running, open the URL shown by the launcher. For the default port it
is:

```text
http://127.0.0.1:7999/
```

Developers or source-checkout users should use the [WebUI README](README.md)
for terminal commands, validation, API, and build details.

The WebUI runs on the same Windows computer that has access to the instrument.
It is a local tool, not a cloud service. Closing the browser tab does not
always stop the server; use `Quit` in the launcher or stop the terminal process
when you are done.

## Browser Language

The WebUI supports English and Traditional Chinese. Use the single language
toggle button in the upper-right of the main interface. When the current
language is English, the button shows `繁體中文`; when the current language is
Traditional Chinese, it shows `English`.

Language switching takes effect at runtime without reloading the page. It keeps
the current page state, including:

- execution mode;
- resource and identity selection;
- command form;
- workflow editor;
- Job History and Job Result;
- Result Detail;
- Live Data display state.

The switch changes browser presentation only. It does not make an HTTP request,
create a Job, run a workflow action, or create, stop, or otherwise affect an
EventSource.

Machine-facing values remain unchanged and are not translated, including
command IDs, model IDs, VISA resources, API payloads and schemas, SCPI, raw
diagnostics, and original error content.

English is the source and fallback locale. The language preference is retained
in the same browser. If browser storage is unavailable, the WebUI safely falls
back without affecting normal operation.

## Screen Overview

The page is an instrument control console. The main areas are:

- `Execution mode`: page-local Real, Simulate, or Dry-run selection. The page
  always opens in Real mode.
- `VISA resource`: the explicit instrument address used by Real command jobs.
- `Live resource`: resources discovered by the Scan Device workflow.
- `Scan Device`: searches for live VISA resources and fills the selector.
- `Live Data`: read-only channel cards and state indicators.
- `Basic command`: per-channel Voltage, Current, Set, and output ON controls.
- `Show more commands`: opens the advanced command rail and generated form.
- `Job Result`: recent submitted jobs and their state.
- `Result Detail`: raw JSON details for the selected job.

Hardware-affecting jobs remain explicit and confirmed.

## First Use

Use this flow when checking a new computer, VISA runtime, connection, or power
supply setup.

1. Confirm the supply and connected DUT are safe to query.
2. Start the WebUI and open the local browser page.
3. Click `Scan Device`.
4. Select the intended live resource or copy it into `VISA resource`.
5. Start `Live Data` to confirm read-only communication and channel state.
6. Review model identity, output state, programmed setpoints, and protection
   state before running any output-affecting command.
7. Use Basic command or the advanced command rail only after the target channel
   and setpoints are known safe.

Do not guess a resource when more than one instrument may be connected.

## Resource Scanning

`Scan Device` runs the WebUI resource discovery job with live-resource filtering
enabled. It is intended to show resources that currently answer, not stale VISA
cache entries.

The first valid scan result is selected automatically and copied into the
`VISA resource` input. That automatic selection runs one read-only identity
job to evaluate exact Product live support. Selecting a different live
resource runs the same evaluation again. The evaluation does not enable
output, change instrument settings, or require real-write authorization. You
may also type a known operator-provided VISA resource manually.

Device options include execution mode and, in Real mode, `Expected model`. Leave it on `Auto-detect` for normal
live use. Auto-detect uses the connected instrument IDN. When `Require
<model>` is selected, the WebUI uses it for frontend capability planning and
sends it as an expected-model guard: the connected `*IDN?` model must match
before setup or write SCPI, and the selection does not force that model's
driver. The Device / Resource summary shows the detected live model and
expected model selection separately, for example `live E3646A / Auto-detect`
or `live E3646A / Require E36312A`.

The normal model dropdown is generated from Core Product-active metadata.
Current supported models and exact connection/backend scopes are defined by
[Supported Models](../core/supported-models.md). Unsupported direct model
submissions are still rejected by the WebUI backend and Core. Auto-detect may
still use detected live model metadata when available, but frontend state
never overrides the Core IDN-selected live driver.

After the read-only identity evaluation succeeds on a Product-open scope, the
Device / Resource summary shows the detected transport/backend scope without
command-count statistics. The diagnostic can show that commands are pending,
but it does not enable them. Changing `Expected model` updates
planning guidance only; it does not rewrite the detected model or connection
scope. The WebUI uses the normal Product policy and the default system-VISA
backend; it does not provide a backend selector or validation mode. Pending
metadata is shown only when the actual runtime transport/backend matches a
registered pending scope.

If identity succeeds for an unknown or de-scoped instrument, the WebUI shows
that no Product-open live scope could be resolved instead of showing an
unevaluated state. Normal model-aware live commands remain disabled, and an
`Expected model` mismatch still fails the diagnostic.

If no live resource appears, check instrument power, cabling, VISA driver
visibility, and whether another program is holding the instrument.

## Live Data

`Live Data` is a read-only monitor. It reads the selected resource on an
interval, updates channel cards, and shows WebUI, command, and live monitor
state.

Use Live Data before output commands to confirm:

- the expected model answered;
- measured voltage/current look plausible;
- programmed setpoints are understood;
- output state is known;
- OVP/OCP trip state is visible when supported.

Live Data may refresh once after successful real hardware commands. It remains
read-only and should be treated as the source of displayed instrument state.
For PSM-2010, the CH1 card also shows the current actual LOW/HIGH output range
as a read-only badge. It shows `--` when the range is unknown or not yet
available; other models do not show this badge.

## Basic Commands

The Basic command panel is for common per-channel setpoint and output actions.

Voltage and Current fields are blankable. Blank fields are omitted and left
unchanged by Core. To set both, fill both fields and click `Set` for the
channel.

Output controls show the next action from fresh Live Data: `Turn on` when the
output is OFF or unknown, and `Turn off` when it is ON. A lit control still
means the output is ON; an unlit control is not a confirmed OFF state unless
Live Data is fresh. In Real mode, `Enable real hardware writes for this
resource` is enabled and selected by default whenever a non-blank VISA resource
is present. Clear
the checkbox in Device options to disable writes for the current resource and
identity context. Selecting or typing another resource, changing Expected
model, detecting a different model, or returning to Real mode creates a new
context with writes enabled by default. With no resource, the checkbox is
disabled and no write authorization exists. The Device / Resource header shows
`Real · Writes locked` or `Real · Writes enabled`; it is a status indicator,
not a control.

E3646A does not support independent CH1 or CH2 output switching. Their output
controls show `Controlled by ALL`; use the ALL control to turn both channels on
or off together. CH1 and CH2 Voltage, Current, and Set controls remain
independent.

Before enabling output:

1. Confirm the selected channel.
2. Set a safe current limit and voltage.
3. Confirm the values through Live Data or readback.
4. Enable output only when the connected DUT can tolerate the request.

## Advanced Commands

Use `Show more commands` for the command rail and generated command form.
Commands are grouped by purpose, such as Output, Output Workflows, Protection,
Trigger, Snapshot, and Advanced Diagnostics.

The form is generated from WebUI command metadata. Required fields must be
filled before Run. Disabled commands or controls indicate unsupported model,
mode, or WebUI scope.

Disabled-command explanations are intentional feature-lock guidance, not random
UI failures. Product LIVE support is exact by detected model, command,
transport, and backend. A read-only, output, protection, or trigger feature
family does not mean every command in that family is product-open; missing and
pending scopes fail closed. E3646A product LIVE remains ASRL / RS-232 + system
VISA only, and its software `ramp-list` and step-limited `sequence` are not
native LIST.

Sequence actions and Trigger Step/List sources also have exact feature status.
A Product-open command does not automatically open a future action
or source that lacks metadata. The browser may display this additive inventory,
but Core validates the actual request and keeps missing or pending features
closed in normal Product mode.

The command rail omits repeated positive live-support labels for commands that
are available. Disabled, pending, model-unsupported, unresolved, missing exact
scope, and `Connection scope not evaluated` reasons remain visible. Pending
commands remain disabled; pending means the instrument profile recognizes the
command but the exact connection/backend evidence is not Product-open. These
browser states are guidance only. Core repeats the exact policy check for every
submitted live job, including direct or stale API requests.

Offline-only utilities are not identity/status diagnostics and are not shown
as Product-open live commands.

The WebUI is product-only. It does not offer a validation override, and raw
job submissions cannot use one to turn pending evidence into normal product
support.

Some editors support JSON Load/Save, including Sequence, Ramp List, and Trigger
List workspaces. Use these for repeatable workflows, and keep saved files free
of private lab resource strings unless they are intentionally local-only.

Ramp, Ramp List, and Sequence provide an `Enable loop` checkbox. When enabled,
an inline Loop count appears with a range of 2 through 10,000; this is the total
number of workflow executions, not additional repeats. Turning Loop off hides
the field and means one execution. Ramp and Ramp List offer Loop complete in
Pulse timing only while Loop is enabled. Ramp List saves v5 documents and
Sequence saves v2 documents, both with explicit `loop_count`, including 1.

Ramp's Channel selector follows the selected or detected model. It lists each
channel, supported channel combinations, and All for multi-channel models.
Selected channels share the same current and voltage settings and advance in
lockstep; a voltage step completes only after every selected channel succeeds.
For a channel combination or All, a full-width note below Channel and Current
explains this shared lockstep behavior. The note is absent for a single channel,
without leaving an empty row in the Ramp form.

Ramp List loads v2 through v5 and always saves v5. Each Segment has its own
channel-combination selector; All is written as an explicit channel list.
Multi-channel Segments advance in lockstep, while progress and pulses count one
logical voltage step rather than one action per channel. Pulse trigger channels
are selected internally. On E3646A, Auto-enable pre-stages the first safe
setpoint for every channel used in the list before enabling global output once.

## Job Results

Submitted commands appear in `Job Result`. Select a job to inspect its state
and raw JSON in `Result Detail`.

Typical job states include accepted, started, progress, finished, failed,
cancel requested, and cancelled. A failed job should include a message in the
result payload.

The browser provides Simulate and Dry-run controls in Device options. Both
modes disable VISA resource, scanning, serial controls, and Live Data; they do
not open or lock real hardware. Simulate accepts only a physical planning
model. Dry-run accepts a physical planning model or a planning profile. For
live raw API jobs, `runtime.expected_model_id` is an optional
canonical safety guard checked after manufacturer-plus-model IDN resolution;
mismatch fails before setup or write SCPI. The browser learns live model
support from scan/job IDN metadata; fake resource strings do not imply a
model. Browser disabled or hidden state is not the safety boundary; direct
`/api/jobs` submissions are still rejected by the WebUI backend and Core when
the model, command, or mode is unsupported.

Raw runtime JSON is type-strict: boolean fields require JSON booleans, and a
string such as `"false"` is rejected rather than treated as confirmation.
Raw job channels require a positive JSON integer; exact `"all"` is accepted
only by commands that support all-channel selection. Boolean, floating-point,
and numeric-string channel values are rejected.
Model-specific dry-run/simulator requests are rejected before job creation if
no explicit or deterministic-SIM planning identity is available. Snapshot
restore accepts only `schema_version: 2`, `kind: "powers-tool-snapshot"`
documents with separate reported and canonical resolved identity. Restore
request flags and persisted output/protection states also require exact JSON
booleans. The snapshot `outputs`, `readback`, and `protection_settings`
sections must be non-empty and contain exactly the same channels; every
channel needs a protection record even when its optional values are null.
Unknown and intentionally unsupported `/api/jobs` commands are
rejected before a job or background task is created.

## Stop And Cancel

If a job has not started, cancel can finish quickly. If a real hardware job is
already executing, cancellation is cooperative: the WebUI requests cancellation
and waits for Core cleanup to finish.

Do not close the browser or kill the process to interrupt normal cleanup unless
there is an external safety reason. Cleanup and release/local behavior belong
to Core and may take time.

`Quit` requests cancellation of active WebUI work, including Live Data, and
waits for normal cleanup before stopping the local server. If shutdown cannot
finish before its timeout, the launcher stays open and reports `Shutdown
incomplete` so you can resolve the problem and try again.

## Common Problems

### The page does not load

Confirm the server is still running and open:

```text
http://127.0.0.1:7999/
```

Check the URL shown by the launcher because automatic startup may have selected
a port other than `7999`.

### The launcher says the port is already in use

The launcher never opens the service that already owns a candidate port.
Default automatic startup skips address-in-use candidates. A fixed `--port`
conflict exits without choosing another port. If the manual fallback window is
open, choose another port or stop the service that owns the selected port, then
click `Start` again.

### Scan Device finds nothing

Check that:

- the instrument is powered on;
- USB or LAN is connected;
- the VISA driver can see the instrument;
- no other program is holding the resource;
- the correct backend is available on this PC.

You can still type a known VISA resource manually.

### Run is blocked

Read the visible validation message and Result Detail. Common causes are a
missing resource, missing required command field, unsupported model, unsafe
setpoint, or missing confirmation for real output-affecting commands.
Selecting an expected model does not unlock disabled commands; it only plans
no-hardware requests or guards a live command against the connected `*IDN?`
model.

### Output buttons do not look current

Start or refresh Live Data. The WebUI avoids displaying stale output state as
fresh truth.

### A command appears busy

Real hardware commands are serialized by the WebUI hardware lock. Wait for the
current command and cleanup to finish, or cancel only when that is the intended
operator action.

### Live Data reports stale or error state

Check the resource, connection, and whether another command owns hardware I/O.
Live Data does not override real command execution.

## Operator Safety Notes

- Use read-only Live Data before output-affecting commands.
- Keep first live checks low voltage/current and explicit channel.
- Confirm current limit before enabling output.
- Treat `channel all` as a deliberate multi-channel action.
- Do not clear protection until the cause of the trip is understood.
- Treat trigger and LIST workflows as advanced operations.
- Stop or turn output off before disconnecting the DUT when practical.

## More WebUI Documentation

- [WebUI README](README.md): API behavior, validation, development setup, and
  maintainer boundaries.
- [WebUI Change Rules](web-ui-change-rules.md): developer and agent rules for
  UI changes.
