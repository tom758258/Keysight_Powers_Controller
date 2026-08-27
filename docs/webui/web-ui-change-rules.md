# WebUI Change Rules

This document is the maintainer and agent-facing working contract for WebUI
polish and reorganization work. It is not an operator guide. It exists to let
UI work move quickly without damaging power-supply, SCPI, VISA, job, live-data,
or cleanup behavior underneath.

Read this file before changing WebUI code. Also read `AGENTS.md`, the WebUI
README, and the current task context.

## Goal

Improve the browser UI only:

- Make the existing WebUI clearer, denser, more polished, or easier to use.
- Preserve the current Core runtime behavior and browser API contracts.
- Leave SCPI, VISA, output, trigger, protection, sequence, snapshot, live-data,
  cancellation, and cleanup behavior untouched unless the user explicitly asks
  for a backend change and confirms the risk.

Assume connected supported power supplies are real hardware. A UI mistake can
set the wrong voltage/current, enable the wrong output, clear the wrong
protection state, or launch a risky workflow, so treat non-visual changes as
high risk.

## Files You May Change For UI Polish

Normal WebUI frontend work is contained under
`src/powers_tool_webui/static/`. This includes the maintained static HTML, CSS,
and browser JavaScript presentation modules, including modules such as
`command-params.js`, `dom_i18n.js`, and `theme_ui.js` when their presentation
responsibilities are in scope. File location does not make a behavioral change
presentation-only. Changes within this directory must still preserve the API,
execution, instrument-safety, job, Live Data, and cleanup boundaries below.

Generated Help files under `src/powers_tool_webui/static/help/` are runtime
outputs. Maintain their Markdown and shared presentation sources under
`docs/help/`, then regenerate and synchronize owned assets when Help sources
change; do not edit generated HTML by hand.

Optional, only when a stable UI contract changes or a new public behavior needs
coverage:

- `tests/webui/test_webui_*.py`
- `tests/webui/_webui_*.py`
- `tests/webui/conftest.py`

Optional documentation updates:

- `docs/webui/README.md`
- `docs/webui/USER_GUIDE.md`
- `docs/webui/web-ui-change-rules.md`

Keep edits surgical. Do not touch unrelated files.

## Files And Behavior You Must Not Change

Do not change Core, CLI, package metadata, or WebUI backend behavior for a
visual UI task:

- `src/powers_tool_core/**`
- `src/powers_tool_cli/**`
- `pyproject.toml`
- Backend behavior in `src/powers_tool_webui/app.py`,
  `commands.py`, `jobs.py`, or `server.py`

Do not change any SCPI, VISA, output, trigger, protection, timeout, live-data,
or cleanup behavior. Specifically do not change:

- SCPI commands or command ordering.
- VISA backend, resource selection, or timeout behavior.
- Output-on, output-off, safe-off, apply, set, ramp, ramp-list, trigger, LIST,
  protection, clear, restore, snapshot, or sequence semantics.
- Safety-config interpretation or official rating limits.
- Hardware-lock behavior and real-job serialization.
- Live Data polling interval, hardware read path, stale/error semantics, or
  post-command refresh behavior.
- Cancellation, stop, release/local, close, and cleanup order.
- JSON success/error envelopes, job status values, or event stream semantics.

If a UI idea seems to require any of the above, stop and write the requested
backend/API change as a proposal instead of implementing it.

## Current WebUI Shape

Before running the developer commands below, use the root
[README Install guide](../../README.md#install) to prepare the locked
development environment from the repository root:

```powershell
uv sync --all-extras --locked --link-mode=copy
```

Developer runtime entry point:

```powershell
uv run python -m powers_tool_webui.server --host 127.0.0.1 --port 7999
```

Local URL:

```text
http://127.0.0.1:7999/
```

The WebUI is an instrument control dashboard:

- Backend: FastAPI/Uvicorn in `src/powers_tool_webui/app.py`.
- Browser frontend: static HTML/CSS/JavaScript in
  `src/powers_tool_webui/static/`.
- The browser WebUI itself has no Node build step or frontend package manager.
- The separate Electron Desktop shell is under `desktop/` and uses npm for
  source-mode development and Windows packaging.
- No external CDN dependency.
- No framework migration unless explicitly approved by the user.

## API Contract To Preserve

Do not rename, remove, or repurpose these endpoints:

- `GET /`
- `GET /api/health`
- `GET /api/commands`
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/cancel`
- `GET /api/events?job_id=...`
- `POST /api/live`
- `POST /api/live/{job_id}/stop`
- `GET /api/live/{job_id}/events`

Do not change request payload names in `app.js` unless the backend, tests, and
docs are intentionally changed together by a separate approved backend task.

Important job payload fields currently sent by the UI include:

- `command`
- `runtime`
- `parameters`
- `artifacts`
- `resource`
- `simulate`
- `dry_run`
- `backend`
- `confirm`
- `channel`
- `voltage`
- `current`
- `safety_config`
- command-specific fields generated from `/api/commands`

The UI must continue to use `/api/commands` as the source of truth for command
metadata, confirmation requirements, supported models, disabled commands,
parameter names, and generated forms. Do not invent command or parameter
options in the frontend.

## DOM And Form Contract To Preserve

You may reorganize layout and visual grouping, but preserve functional IDs,
`name` attributes, and `data-*` attributes unless the stable UI contract
changes. Only update static tests for stable contracts; do not lock CSS colors,
layout measurements, helper function names, local JavaScript variable names, or
panel copy as a substitute for behavioral coverage. See the root
[Testing Guidelines](../testing-guidelines.md).

Important IDs and attributes include:

- `resource`
- `resource-select`
- `scan`
- `live-start`
- `server-state`
- `device-state`
- `live-state`
- `live-cards`
- `basic-command`
- `basic-output-all`
- `advanced-command-toggle`
- `basic-command-status`
- `advanced-commands`
- `command-filter`
- `command-categories`
- `command-list`
- `selected-command`
- `command-description`
- `run`
- `confirm`
- `command-form`
- `workspace-summary-content`
- `job-result-panel`
- `job-history`
- `job-result-clear`
- `job-result-toggle`
- `result-panel`
- `result-toggle`
- `result`
- `data-basic-channel`
- `data-basic-output`
- `data-basic-all-output`
- `data-basic-set`
- `data-basic-voltage`
- `data-basic-current`
- `data-channel-card`

Hidden controls must not submit stale values. Disabled and unavailable states
must stay visible enough for operators to understand why an action is blocked.

## Behavior That Must Stay True

The UI may look different, but these behaviors must remain true:

- Health loads from `GET /api/health` and reports hardware-lock state.
- Command metadata loads from `GET /api/commands`.
- Scan Device submits the `list-resources` command through `POST /api/jobs`
  with `live_only: true`.
- Selecting a live resource copies it into the VISA resource input.
- The command rail hides CLI-only, debug, live-data internal, and unsupported
  commands while preserving direct backend rejection for invalid submissions.
- The Basic command panel omits blank Voltage/Current values instead of
  sending them as setpoints.
- Basic output buttons represent fresh Live Data output state; unknown/off is
  not displayed as confirmed ON.
- Output-affecting commands require page-local real-write authorization for
  the current Real resource. The browser uses command `requires_confirm`
  metadata and does not maintain an independent mutating-command list.
- Simulate and Dry-run are no-hardware modes: their runtime payloads never
  include a VISA resource, serial settings, expected identity, or confirmation.
- Live Data is Real-mode only; `/api/live` rejects simulate and dry-run.
- Real hardware jobs are serialized by the WebUI hardware lock.
- Simulate, dry-run, offline metadata commands, and live-data jobs do not
  occupy the real hardware command lock.
- Cancelling an executing job uses the job cancellation path and does not
  directly close VISA resources from the browser.
- Job updates are streamed through `GET /api/events?job_id=...` and shown in
  Job Result / Result Detail.
- Live Data starts through `POST /api/live` and streams through
  `GET /api/live/{job_id}/events`.
- Live Data can be stopped through `POST /api/live/{job_id}/stop`.
- Live Data reads are read-only and must not overlap real hardware command I/O.
- Fresh Live Data can repair model support cache for the selected resource;
  unknown/stale data must not invent support.
- Fresh channel trip state adds a soft guard for direct output commands on that
  channel; safe/off and recovery commands remain available.
- Advanced command forms keep generated controls, JSON Load/Save workspaces,
  Sequence limits, Ramp List limits, Trigger List channel workspaces, and pulse
  option rules aligned with Core command metadata.
- Rear digital pulse controls remain separate from output channels and
  E36312A-only where applicable.

## Visual Design Boundaries

Allowed:

- Improve layout, grouping, spacing, colors, typography, responsive behavior,
  focus states, disabled states, and status readability.
- Reword visible labels when the meaning stays identical.
- Add static helper text only when it reduces operational ambiguity.
- Add purely client-side affordances such as tabs, collapsible panels, badges,
  warnings, summaries, or filters.
- Add small CSS-only motion if it does not distract from instrument safety.

Avoid:

- Marketing-style landing pages. The first screen should remain the usable
  control console.
- Decorative changes that make controls harder to scan.
- Hidden controls that still submit stale values.
- Extra network dependencies.
- A frontend build chain.
- Broad rewrites of `app.js` or its small helper modules when a small change is enough.

For this project, clarity beats spectacle. The UI should feel like a power
supply control console: readable, calm, direct, and hard to misuse.

## When To Ask Before Continuing

Ask the user before implementing if the request requires:

- New backend endpoints.
- New payload fields.
- New commands or command groups.
- New model support or capability rules.
- Any change to SCPI, VISA, output state, trigger timing, LIST behavior,
  timeout, cleanup, stop, release/local, protection, or safety behavior.
- A new dependency, frontend framework, build tool, icon package, charting
  library, or CDN.
- Removing an existing control.
- Changing what Run, Scan Device, Live Data, Cancel, or Basic output controls
  do.

If unsure whether a change is visual or behavioral, treat it as behavioral and
ask.

## Required Checks Before Completion

Run the narrowest relevant checks first:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\webui -q -p no:cacheprovider
```

If WebUI JavaScript changed, also run:

```powershell
git ls-files 'src/powers_tool_webui/static/*.js' |
    ForEach-Object {
        node --check $_
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
```

`execution-context.js` owns only pure execution/workspace context and workspace-result
entry/lookup helpers. It must not access the DOM, fetch, EventSource, or mutable
application state. Direct behavior coverage for those helpers belongs in
`tests/webui/test_webui_static_context.py`.
`electrical.js` owns only pure electrical input-constraint calculation. It
must not access the DOM, fetch, EventSource, or mutable application state.
`command-form.js` owns fixed Output and Trigger parameter descriptors,
shared command-form DOM primitives, guidance, accessibility help, and
parameter notes. It receives command metadata and guard functions explicitly
from `app.js`.
`command-params.js` owns command parameter descriptor definitions used to
construct forms; it does not define backend command admission or Product policy.
`dom_i18n.js` owns applying catalog translations to static DOM bindings; locale
selection and catalog lookup remain owned by the localization modules.
`theme_ui.js` owns theme preference validation/persistence, effective-theme
calculation, and theme-control presentation; it does not own locale selection.
`results.js` owns job-result and status summary text plus Workspace Result DOM
presentation. It receives
the current execution context and support-label helpers explicitly from `app.js`.
`jobs.js` owns Job HTTP submission, SSE transport, Job History state mutation,
and Job History DOM presentation. It receives status labels and the
execution-mode refresh callback explicitly. `live-data.js` owns Live Data
sample normalization, channel merge helpers, state text, channel-card rendering,
and its Start/Stop/one-shot lifecycle through explicit dependencies.
`json-files.js` owns browser-native JSON file selection, download fallback,
and AbortError handling shared by artifact and workflow editors.
`ramp-list.js` owns only pure Ramp List document materialization
and validation. It must not access the DOM, fetch, EventSource, or mutable
application state.
`trigger-list.js` owns only pure Trigger List workspace document
materialization and validation. It must not access the DOM, fetch, EventSource,
or mutable application state.
`sequence.js` owns only pure Sequence document normalization and
editor serialization. It receives the existing action schema and canonical
step validator explicitly, and must not access the DOM, fetch, EventSource, or
mutable application state.
`snapshot-restore.js` owns pure Snapshot filename/schema validation and Restore
payload materialization. It must not access the DOM, fetch, EventSource, or
mutable application state.
`basic-controls.js` owns Basic control action-state, Live-readback, and
E3646A output presentation. It receives the current state and explicit
application callbacks; Basic Job submission remains in `app.js`.
`command-support.js` owns presentation of Core-derived command support,
exact live scope, and channel capability metadata. It must not admit commands
or introduce Product policy outside the metadata returned by the backend.
`workflows.js` owns the Ramp List, Trigger List, Sequence, Snapshot, and
Restore editor DOM plus their JSON Load/Save orchestration. It receives state,
document helpers, and application callbacks explicitly; it must not create
Core requests or change workflow admission, safety, or cleanup semantics.
`app.js` owns the DOM/state adapters, workspace cache mutation, rendering, and
job lifecycle. `index.html` loads it as the sole native module bootstrap; it
imports helper modules through explicit relative module dependencies.

When practical, run broader no-hardware checks:

```powershell
uv run python -m pytest tests -q -p no:cacheprovider
```

If the local environment lacks dependencies, say exactly what could not run and
why. Do not claim validation that did not happen.

## Manual UI Smoke Checklist

If you can run the app locally, verify:

- The page loads at `http://127.0.0.1:7999/`.
- No browser console errors appear on first load.
- Scan Device updates the live resource selector or reports no live resources
  cleanly.
- Selecting a live resource fills the VISA resource input.
- Basic Voltage/Current blank fields are omitted from setpoint payloads.
- Output-affecting real commands require confirmation.
- Command categories and filtering still expose supported WebUI commands.
- Generated forms show required, optional, and disabled fields clearly.
- Sequence, Ramp List, and Trigger List editors preserve Load/Save behavior.
- Live Data Start/Stop changes state without overlapping command execution.
- Job Result and Result Detail update after a simulated command.
- Mobile width around 390 px does not overlap text or controls.
- Desktop width around 1280 px remains dense but scannable.

Do not perform real-instrument output or trigger experiments unless the user
explicitly asks. If an instrument is connected and the user requests a smoke
test, start with read-only checks, then low voltage/current, explicit channel,
and output-off cleanup.

## Completion Summary

When finished, provide this short summary:

- Files changed.
- What visual/user workflow problem was addressed.
- Any behavior intentionally preserved.
- Tests and checks run, with pass/fail results.
- Manual UI checks run, with viewport notes if relevant.
- Any skipped validation and why.
- Any risk or follow-up that requires backend approval.
