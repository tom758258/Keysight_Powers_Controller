# Power Worker Contract

Schema version: `2`

This contract extends `common-worker-protocol.md` for Powers Tool power-supply operations.

## Endpoints

- `GET /status`: lifecycle status only. It is non-mutating and never opens VISA.
- `POST /command`: asynchronous Power command submission.
- `POST /cancel`: cooperative cancellation of the exact active cancellable job.
- `POST /stop`: priority cooperative stop request.

`/trigger`, `trigger_url`, `--default-action`, and default-action config are not supported.

`POST /cancel` requires exactly schema version 2 and the active
`worker_job_id` (plus an optional string reason). Wrong, stale, completed, or
non-cancellable identity fails closed. Ramp, Ramp List, Sequence, and bounded
telemetry `log` cancellation does not shut down the Worker; successful cleanup
or normal log session close returns it to `ready`.
`GET /status` does not need a `cancel_url` because the route is fixed.

## Power Stop Cleanup

`POST /stop` only sets stop state, wakes the background runner, and returns.
It performs no VISA I/O, cleanup, or HTTP-server shutdown in the handler.
The runner must finish command safety cleanup before the Worker stops the HTTP
server or emits the final `summary`.

A successful `POST /stop` returns HTTP `200` with a JSON object containing
`ok: true` and a non-empty string `message`. It acknowledges the cooperative
stop request only; it does not indicate that cleanup or shutdown has finished.

Stop-only cleanup results use Power status values `succeeded`, `unsupported`,
`not_applicable`, and `failed`. Cleanup runs `release_to_local`, closes the
VISA session, then records `cleanup_release_to_local`; HTTP server shutdown
follows runner completion. `release_to_local` uses device-specific PyVISA GPIB
local control only when available. USB/LAN are `unsupported`; simulated or
unopened sessions are `not_applicable`. `cleanup_release_to_local` is
post-close bookkeeping and must not access the closed VISA session.

User cancellation of Ramp, Ramp List, or Sequence first stops future steps and
completion pulses. On the workflow's existing session it requests output OFF
for every supported channel, verifies each OFF, and drains the instrument error
queue to the no-error sentinel with a maximum of 20 reads. Session close and
hardware-lock release follow. Terminal `cancelled` is allowed only when every
stage succeeds; otherwise terminal status is `failed`, error code is
`cleanup_failed`, and result diagnostics preserve `original_reason:
user_cancelled`. Blocking VISA I/O is not forcibly interrupted.

Telemetry `log` is read-only and uses different cancellation semantics. A
cycle that has started finishes every requested channel and flushes its rows;
cancellation is observed before the next cycle or during the interval wait.
The session then closes normally and collected telemetry remains available.
Log cancellation does not issue output OFF or run workflow safe-off/error-queue
cleanup. Blocking VISA queries are not forcibly interrupted.

Each result is emitted as a structured `power_cleanup` JSONL event.
Unsupported cleanup is a warning. Any failed release, close, or post-cleanup
makes final `summary.ok` false and Worker exit code `3`.

## `POST /command`

The request body is a strict JSON object:

```json
{
  "schema_version": 2,
  "command": "read-status",
  "arguments": { "channel": "all" },
  "job_id": "optional-orchestrator-id",
  "context": {
    "mode": "dry_run",
    "planning_model_id": "keysight-e36312a"
  }
}
```

Allowed top-level fields are `schema_version`, `command`, `arguments`, `job_id`,
and `context`. `schema_version` is required and must be the exact integer `2`;
booleans, strings, floats, missing versions, and unsupported integers are
rejected. `context` is required. Unknown fields, malformed JSON, a non-object
body, a missing/non-string command, non-object `arguments`, non-string `job_id`,
unknown command names, invalid context, and invalid Power arguments return `400`
before any VISA I/O, queue mutation, or artifact creation.

Command parameters are admitted only by the Core command-parameter contract.
The Worker does not maintain a second command parameter allowlist, alias policy,
or type coercion rule; Worker request exposure taxonomy is maintained in Worker
protocol, while parameter validation and canonicalization remain Core-owned. The
admitted canonical parameters and context, rather than the raw JSON request, are
retained for queued execution. JSON booleans and integers
must be exact values; explicit `null`, alias conflicts, unknown fields, and
fields that belong to a different command are rejected before a hardware lock
or VISA session is acquired.

Every `/command` response is a JSON object with integer `schema_version: 2`,
`status`, `command`, and `job_id`. In the HTTP response, `command` is the
submitted command string, for example `"read-status"`.

- Accepted commands return `202` with `status: "accepted"` and a non-empty
  string `worker_job_id`. In `files` mode the response also contains a
  non-empty string `artifact_path`; `memory` mode omits `artifact_path`
  because no job artifact directory exists.
- Validation failures return `400` with `status: "error"`.
- Admission/safety rejections return `409` with `status: "rejected"` and one of the Power rejection reasons.

Power rejection reasons are `busy`, `run_not_ready`, `output_confirmation_required`, and `output_changes_not_allowed`.

`POST /command` HTTP `202` means only that the request was accepted and
enqueued. It does not mean the Power command has succeeded. In `files` mode,
before returning HTTP `202`, the Worker must create the job artifact directory
and write `request.json` successfully. If artifact initialization fails, the
request must not be reported as accepted.

`job_id` is the optional orchestrator ID from the request. It is echoed in
responses and runtime status but is not written into request/result artifacts
or measurement metadata. `worker_job_id` identifies the Worker artifact
directory and is the Worker job identity.

Power Worker job states are:

- `accepted`: the HTTP handler accepted the request.
- `queued`: in `files` mode the job artifact directory and `request.json`
  exist; in either mode the job is waiting for the background runner.
- `running`: the background runner is executing the command.
- `succeeded`: terminal success.
- `failed`: terminal failure.
- `cancelled`: terminal cooperative stop/cancellation.

## `GET /status`

`GET /status` is non-mutating. It must not open VISA, execute a domain
command, mutate the queue, request stop, or create artifacts.

The response includes integer `schema_version: 2`, exact string
`service: "powers-tool"`, non-empty strings `run_id`, `command_url`,
`status_url`, `stop_url`, and `timestamp_utc`, Worker `status`, non-negative
integer `queue_size`, plus `active_job`, `last_job`, and `fatal_error` objects
or `null`. Worker status is one of `ready`, `busy`, `stopping`, or `error`.

`active_job` and `last_job`, when present, include job correlation and status
fields. A terminal job also includes `artifact_available`; `artifact_path` is
present only when the result artifact is available. An artifact-write failure
therefore reports `artifact_available: false` and omits `artifact_path`. In
`memory` mode a terminal `last_job` instead includes `result`, holding the
complete result envelope described under Artifacts, plus `error` for failures.
Top-level `job_id` is not used for domain job identity.

## Commands

Read-only/status:

- `identify`
- `read-status`
- `readback`
- `measure`
- `measure-all`
- `output-state`
- `protection-status`
- `error`
- `snapshot`
- `log`

Output/setpoint:

- `set`
- `apply`
- `output-on`
- `output-off`
- `safe-off`
- `cycle-output`
- `ramp`
- `ramp-list`
- `smoke-output`

Protection/restore/sequencing:

- `protection-set`
- `clear-protection`
- `restore-from-snapshot`
- `sequence`

Trigger:

- `trigger-pulse`
- `trigger-status`
- `trigger-step`
- `trigger-list`
- `trigger-fire`
- `trigger-abort`

These are Worker request names, not a blanket product LIVE allowlist. Worker
maintains its own request-command exposure taxonomy across read-only, output,
protection, and trigger categories, while explicit unsupported Core commands
(`list-resources`, `verify`, `clear`) fail closed. Command parameter allowlists,
aliases, type validation, and canonicalization remain strictly owned by the
Core command contract. Worker passes model-aware live requests to the shared
Core boundary, which selects the detected `*IDN?` model and requires an exact
command/transport/backend product scope. Missing and pending scopes fail
closed, and Worker provides no validation bypass. A command may remain useful in
dry-run or simulator mode without an accepted real-hardware scope.

Worker always operates in the product support-policy mode. Validation-policy
request or settings fields are rejected rather than ignored. Runtime identity
is selected per request through `context` and is never a support unlock.

## Execution Context

Powers requires a top-level `context` for every `POST /command` request.
Accepted fields are:

- `mode`
- `planning_model_id`
- `expected_model_id`
- `planning_profile_id`

`planning_profile_id` is a Powers-specific nonphysical dry-run planning field.
The only current value is `generic-scpi`.

| Context mode | Required or allowed | Forbidden |
| --- | --- | --- |
| `live` | optional `expected_model_id` | `planning_model_id`, `planning_profile_id` |
| `simulate` | required `planning_model_id` | `expected_model_id`, `planning_profile_id` |
| `dry_run` | exactly one of `planning_model_id` or `planning_profile_id` | `expected_model_id`; both planning fields together |

Worker startup mode compatibility is unchanged:

- a live Worker accepts `live` and `dry_run` context;
- a simulate Worker accepts `simulate` and `dry_run` context;
- all other combinations are rejected before queue or artifact mutation.

`expected_model_id` is only a live mismatch guard. Detected identity remains
authoritative and selects the driver. `planning_model_id` is a canonical
physical model used for simulator or dry-run planning. `planning_profile_id`
is not a physical model and never selects a live driver.

The following fields are rejected inside `arguments`:

- `dry_run`
- `simulate`
- `live`
- `planning_model_id`
- `expected_model_id`
- `planning_profile_id`
- `model`
- `model_profile`
- `profile`

## Arguments

Common `arguments` keys:

- `confirm_output`: optional boolean, default `false`. Required with Worker config `settings.allow_output_writes: true` for live output-affecting commands.

`log` requires exactly one of `channel` or `channels`, exactly one of `samples`
or `duration_sec`, and a positive `interval_sec`. `channel` is a positive
integer or exact `"all"`; `channels` is a non-empty array of positive integers.
All bounds must be positive. Worker `log` is read-only and does not require
output-write settings or confirmation. It supports `live` within exact Product
policy and `simulate`; `dry_run` is rejected because Worker does not fabricate
telemetry. `csv`, `jsonl`, and `append` are rejected. A caller cannot select an
artifact path, and `log` is one exclusive Worker job rather than background
telemetry concurrent with another command.

Command-specific fields match the CLI/core names, including `channel`,
`voltage`, `current`, `loop_count`, `max_errors`, `max_reads`, `file`, `document`,
`snapshot`, `wait_timeout_ms`, `poll_ms`, protection options, snapshot
options, and sequence options. Raw JSON `channel` accepts an exact positive
integer or exact `"all"`; booleans, floats, numeric strings, null, arrays, and
objects are rejected before queue or artifact mutation. `"all"` is accepted
only by commands with all-channel selection;
for output commands, `"all"` is supported by `apply`, `safe-off`,
`output-on`, `output-off`, `output-state`, and `cycle-output`. `set`, `ramp`,
and `smoke-output` do not accept `"all"`. Ramp instead requires exactly one of
single `channel` or a non-empty, duplicate-free `channels` list; Core rejects
unsupported entries and canonicalizes the list before queue admission for
no-hardware jobs. `ramp-list` accepts `file` or `document`. Version 5 Segments
select a non-empty, duplicate-free `channels` list; older supported versions
continue to select one positive integer `channel`.

Restore snapshot documents must contain non-empty `outputs`, `readback`, and
`protection_settings` sections with exactly the same channel inventory. A
channel protection record is required even when each optional protection
field is null; incomplete snapshots are rejected instead of partially
restored. PSM-2010 documents also require a matching `output_ranges` section
with one `LOW` or `HIGH` active range per channel. Restore also requires an
explicit `channel` selector; exact `"all"` is valid, but an omitted selector is
rejected before artifact creation.

`set` arguments require `channel` plus `voltage`, `current`, or both. An
omitted setpoint is left unchanged on the instrument and must not be replaced
with zero or readback-derived values. Requests with neither `voltage` nor
`current` return HTTP 400 before artifact creation or queue mutation.

Worker dry-run/simulate requests that need model-specific planning use
`context.planning_model_id`; Powers Generic dry-run uses
`context.planning_profile_id`. Fake or live-looking resource strings do not
imply a model. If an explicit physical planning ID and deterministic simulator
resource are present, they must match. Core-owned command admission validates
these requirements and command support before HTTP `202`, job-directory
creation, `request.json`, or queue mutation.

Worker runtime settings may include optional ASRL serial fields under
`settings.serial_options`: `baud_rate`, `data_bits`, `parity`, `stop_bits`,
`flow_control`, `read_termination`, and `write_termination`. Empty or omitted
fields are not applied and do not override the VISA backend or Connection
Expert settings. `read_termination` and `write_termination` accept `CR`, `LF`,
`CRLF`, and `NONE` aliases; `NONE` means no termination override. The boolean
settings `serial_remote` and `serial_local_on_close` request explicit
`SYST:REM` and best-effort cleanup `SYST:LOC` for ASRL resources only.

Ramp, Ramp List, and Sequence `loop_count` is a strict integer from 1 through
10,000 and means total complete workflow executions. Invalid raw values are
rejected before queue or artifact mutation. Explicit request overrides take
precedence over document values.

Core also rejects more than 1,000,000 logical execution units before queue or
artifact mutation. Ramp counts voltage steps, Ramp List sums Segment voltage
steps, and Sequence counts Steps, each multiplied by `loop_count`. Adapters
warn above 100,000 units. Ramp channel count does not multiply its logical
units or progress. Runtime detail arrays retain at most the first 100
and last 100 entries with additive truncation metadata, and progress is
reported by completed units, total units, and integer percent. Ramp List
Segment channel count, like Ramp channel count, does not multiply logical units.

Ramp List v2 documents imply `enable_output: false` and `loop_count: 1`; v3
requires exact `enable_output` and implies one iteration; v4 requires exact
`enable_output` and `loop_count` with single-channel Segments. Ramp List v5 is
the latest format and requires exact `enable_output`, `loop_count`, and a
non-empty unique `channels` list in every Segment. v2/v3/v4 reject `channels`,
and v5 rejects `channel`. Sequence v1 forbids `loop_count` and implies
one iteration; v2 requires it. Unknown or missing strict-version fields and
future versions are rejected. Each Ramp List segment also contains `current`,
`start_voltage`, `stop_voltage`, `step_voltage`, `delay_ms`, and
`hold_ms`. An optional global `completion_pulse` contains `timing`
(`segment`, `step`, or `loop`), E36312A rear digital `pins`, and `polarity`.
Loop timing requires at least two iterations.

Ramp accepts `completion_pulse_timing`; step timing accepts `delay_ms = 0`
and uses software post-action pulses. An explicit `completion_pulse_channel`
must be an exact integer from 1 through 3 and requires non-empty
`completion_pulse_pins`; invalid or inapplicable raw values are rejected before
queue or artifact mutation. Sequence accepts canonical
`trigger-pulse` actions with `channel`, `pins`, `polarity`, and optional
`leave_trigger_configured` for E36312A only. Sequence must not bypass model
feature gates: EDU36311A trigger/native LIST and snapshot/restore remain
disabled, and E3646A protection, trigger/native LIST, snapshot/restore,
completion-pulse, and native LIST remain disabled. Rear pulse pins and output
channels are separate.

General output/ramp commands reject the removed `completion_pulse_mode`,
`completion_pulse_dwell_ms`, `wait_timeout_ms`, and `poll_ms` fields before
artifact creation or queue mutation. Native LIST and trigger wait controls are
accepted only by the relevant Trigger commands.

Post-action pulses modify and restore trigger/rear-pin settings unless
explicitly left configured. Their global `*TRG` may trigger other armed BUS
behavior.
Loop-complete pulse results distinguish requested, attempted, fired,
completed, restored, restore errors, and post-pulse errors. Because physical
`*TRG` precedes restoration, a restore or later cleanup failure may be
reported after the pulse fired. Workflow loop counters and terminal pulse
success are therefore separate result dimensions.
Native `trigger-step` and `trigger-list` reject `fire: true` with Immediate
source, and BUS requests with `wait_complete: true` require `fire: true` in
the same command. Native `trigger-list` arm-only requests require
`leave_trigger_configured: true`; a started LIST without `wait_complete: true`
also requires `leave_trigger_configured: true`. Invalid requests return HTTP
400 before artifact creation or queue mutation.
`trigger-fire` sends global `*TRG`. Requests with `wait_complete: true` require
`channel` as the abort target for a timed-out or interrupted instrument-wide
completion wait; invalid requests return HTTP 400 before artifact creation or
queue mutation.
Native `trigger-list` accepts canonical `bost_list`, `eost_list`,
`trigger_output_pins`, and `trigger_output_polarity`. Per-step pulse lists
must match the voltage step count; enabled pulses require explicit output
pins. These fields cannot be mixed with legacy `completion_pulse_pins`, which
continues to mean a final-step EOST pulse. Invalid requests return HTTP 400
before artifact creation or queue mutation.

## Safety

For live output-affecting Worker commands, both conditions are required before enqueueing:

- Worker config `settings.allow_output_writes: true`.
- Request `arguments.confirm_output: true`.

Rejected commands do not open VISA, enqueue work, write artifacts, or issue partial SCPI.

## Artifacts

The Worker supports two startup artifact modes selected with
`powers-tool worker --artifact-mode files|memory`. `files` is the default and
is backward compatible. `memory` is an explicit opt-in for orchestrators that
consume results from the stdout JSONL event stream and `GET /status` instead
of files.

In `files` mode, accepted jobs create:

- `request.json`: integer `schema_version: 2`, `command`, `arguments`, and
  admitted `context`.
- `result.json`: final-only CLI-style result envelope with integer
  `schema_version: 2`, `run_id`, `worker_job_id`, `ok`, terminal `status`,
  `command`, `execution`, `request`, `data`, `warnings`, `error`, and
  `metadata`.

A `log` runner additionally creates `telemetry.csv` and `telemetry.jsonl` in
its existing job directory when execution starts. CSV uses the CLI telemetry
field order; JSONL contains the same sample rows and a terminal collection
summary. Both files are flushed as rows are reported and are retained on
cancellation or failure. The HTTP handler creates only the job directory and
`request.json` before `202`; it does not pre-create telemetry files or
`result.json`. Callers cannot provide alternate paths.

`artifact_path` is the job artifact directory, not the `result.json` path.
The final `result.json.command` field keeps the existing CLI result command
object shape, for example `{"name": "read-status"}`. This differs from the
HTTP `/command` response, where `command` is the submitted command string.
`result.json` is written atomically only for terminal states. Pending/running
absence of `result.json` is not success. Failed and cancelled jobs also write a
terminal result artifact when the artifact directory is writable.

Terminal artifact `status` is one of `succeeded`, `failed`, or `cancelled`.
`ok` is `true` only for `succeeded`.

Successful and cancelled `log` result data uses the existing result schema and
contains only `samples_written`, `samples_requested`, `duration_sec`,
`interval_sec`, `channels`, and `stop_reason`. `samples_written` counts complete
multi-channel cycles, not individual rows. Artifact/session/query/reporter
failure is terminal `failed`, never partial success.

In `memory` mode the Worker creates none of the bookkeeping or telemetry files
above. Startup creates no artifact directory (including no placeholder) and no
`events.jsonl`; the `ready` event omits `artifacts_dir` and reports
`artifact_mode: "memory"`. Accepted responses omit `artifact_path`, and no
per-job directory, `request.json`, or `result.json` is created.

Memory-mode terminal events carry the final outcome. `job_finished` includes a
`result` object with the same schema as the `files`-mode `result.json`;
`job_failed` and `job_cancelled` keep their existing `error` semantics and also
include that `result` object. A terminal `last_job` mirrors the same `status`,
`error`, and `result` fields. Only `active_job` and `last_job` are retained;
no job history collection exists.

Memory-mode `log` streams each telemetry row as one schema-2 `sample` stdout
JSONL event containing `run_id`, the optional client `job_id`, `worker_job_id`,
and the Core telemetry row under `sample`. No `telemetry.csv` or
`telemetry.jsonl` is created; samples are consumed live from stdout while the
terminal result keeps only the bounded summary fields above. Memory mode
rejects an explicit `--events-jsonl` path because stdout is the only event
stream.
