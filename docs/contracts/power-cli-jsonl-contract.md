# Power CLI JSONL Contract

Schema version: `2`

This contract extends `common-cli-jsonl-contract.md` with Power command names and payload shapes.

Numeric command fields follow the shared
[Commands parameter contract](commands-parameter-contract.md).

CLI flags are parsed by argparse into Python primitives before Core admission.
Raw JSON sent through Worker or WebUI is stricter: Core rejects numeric strings,
boolean-like strings, booleans used as numbers, explicit nulls unless a field
is documented nullable, unknown/inapplicable fields, and conflicting aliases.
The same admitted canonical request is used for planning and execution.

## CLI Commands

The installed Python distribution is `powers-tool`. CLI JSON payloads use
the V2 adapter identifier `powers-tool-cli`, while the reported version is
sourced from the single distribution.

Lifecycle clients:

- `send-command`
- `status`
- `stop`
- `wait-ready`

Instrument/domain commands include:

- `identify`
- `read-status`
- `readback`
- `measure`
- `measure-all`
- `output-state`
- `protection-status`
- `error`
- `snapshot`
- `set`
- `apply`
- `output-on`
- `output-off`
- `safe-off`
- `cycle-output`
- `ramp`
- `ramp-list`
- `smoke-output`
- `protection-set`
- `clear-protection`
- `restore-from-snapshot`
- `sequence`
- `trigger-pulse`
- `trigger-status`
- `trigger-step`
- `trigger-list`
- `trigger-fire`
- `trigger-abort`

This list defines accepted command names and payload envelopes. It does not
mean every command is product-open for real hardware. Model-aware LIVE
execution resolves detected manufacturer plus model to canonical `model_id`.
The exact Core policy key is `model_id + command + transport + backend +
required feature`; missing or pending scopes fail closed.
Dry-run/simulator availability also does not imply product LIVE support. The
five explicit diagnostics are `list-resources`, `verify`, `identify`,
`error`, and `clear`; their success does not promote another command.

The former instrument `status` command is `read-status`. `powers-tool status` is reserved for Worker `GET /status`.

## Tool Manifest

`powers-tool manifest --json` is static introspection of the installed
executable for orchestrators. It never creates a VISA ResourceManager, lists
or opens VISA resources, sends instrument queries, starts a Worker or HTTP
server, writes files or directories, or modifies persistent configuration.
Success prints exactly one machine-readable JSON object to stdout and exits
`0`:

- `event`: fixed `tool_manifest`.
- `schema_version`: integer `2`, the current Common schema version.
- `tool_id`: fixed `powers`.
- `tool_version`: the installed single-distribution version.
- `worker_protocol.compatibility_policy`: fixed `v2-only`.
- `worker_protocol.schema_versions`: `[2]`.

Consumers must ignore unknown fields. Usage and validation failures follow the
shared exit-code rules. `manifest` describes the executable itself; the
`capabilities` command describes instrument/model capabilities.

## Runtime JSONL

`powers-tool worker` writes runtime JSONL to stdout by default. No
`--json`, `--jsonl`, or format flag is required for orchestrators to parse the
Worker stream. Every non-empty stdout line from the Worker is a JSON object
line. Human-readable diagnostics, warnings, and logging must be written to
stderr so stdout remains directly parseable as JSONL.

Power CLI JSON success/error envelopes and Worker runtime JSONL events use
integer `schema_version: 2` and include
`timestamp_utc`. The runtime event names are:

- `ready`
- `status`
- `message`
- `error`
- `summary`
- `dry_run`
- `power_cleanup`

Each non-dry-run Worker session creates one `run_id`. Runtime events,
`GET /status`, accepted job status, and job result artifacts use that same
`run_id`. Dry-run output that does not create a runtime session omits
`run_id`.

The Worker emits `ready` only after `POST /command`, `GET /status`, and
`POST /stop` can accept requests. `ready` contains `schema_version: 2`,
`timestamp_utc`, `run_id`, `service`, `host`, `port`, `command_url`,
`status_url`, and `stop_url`. It never contains `trigger_url`.

Normal Worker shutdown emits a final `summary`. Fatal failure emits
`summary.ok: false`, includes `fatal_error`, and exits `3`. A missing final
summary is incomplete.

`power_cleanup` is Power-specific and contains a `cleanup` object with
`operation`, `status`, and `message`. Cleanup status is one of `succeeded`,
`unsupported`, `not_applicable`, or `failed`. The final `summary` is emitted
only after runner completion, stop cleanup, and HTTP server shutdown.

## Lifecycle Clients

`send-command --command` is required. `--arguments-json` defaults to `{}`.
`--context-json` is required and supplies the top-level Worker `context`.
Mode/model fields are rejected inside `--arguments-json`. `--job-id` is omitted
by default. `--timeout-ms` defaults to `3000` and accepts `100..600000`.
`--json` aliases `--format json`; conflicting format options exit `2`.

Exit mapping:

- Accepted HTTP command submission or successful lifecycle client operation: `0`.
- Local validation or Worker HTTP `400`: `2`.
- Worker `409`/`429`, connection errors, invalid response bodies, and wait timeouts: `3`.

Successful non-dry lifecycle client responses are endpoint-specific. The client
accepts only a non-empty JSON object with the documented fields and types:

- `send-command`: HTTP `202`, `schema_version: 2`, `status: "accepted"`, the
  submitted `command` and `job_id`, and non-empty string `worker_job_id` and
  `artifact_path`.
- `stop`: HTTP `200`, `ok: true`, and a non-empty string `message`.
- `status`: HTTP `200` and a status object with `schema_version: 2`,
  `service: "powers-tool"`, a non-empty `run_id`, and a documented Worker
  lifecycle `status`.
- `wait-ready`: each successful `GET /status` poll is HTTP `200` and has the
  same lifecycle identity fields; readiness remains `status: "ready"`.

The lifecycle client does not duplicate validation of display and progress
fields such as URLs, queue details, or nested job objects. Those fields remain
defined by the Worker contract and are passed through, including additive
fields and failed jobs without an artifact path.

An empty body, malformed JSON, JSON value other than an object, unexpected
success HTTP status, or object that does not meet its endpoint response
contract is `invalid_response` and exits `3`.

`send-command --dry-run` validates and prints the request without sending
HTTP. `status --dry-run` also does not send HTTP. `wait-ready` polls
`GET /status`; readiness means only that the Worker endpoint is reachable and
ready, not that a submitted job has completed. `stop` uses `POST /stop` for
cooperative cleanup and does not enter the domain job queue.

`send-command --json` merges the Worker response with client diagnostics:
`client_command`, `method`, `url`, `endpoint`, `timeout_ms`, `elapsed_ms`,
`request_sent`, `reachable`, `http_status`, `error_phase`, and `ok`. On
failures it also includes `exit_code`. For accepted command responses, `ok`
means the request was accepted; it does not mean job execution succeeded.

## Result Payloads

Power command success envelopes follow the common CLI contract. Command names use the public names above, including `read-status`.

Runtime identity fields:

- CLI `--model` maps to `context.planning_model_id` in dry-run/simulator mode
  and to `context.expected_model_id` in live mode. Values are canonical
  vendor-qualified physical IDs such as `keysight-e36312a`.
- CLI `--profile generic-scpi` maps to the Powers-specific
  `context.planning_profile_id` and is dry-run only. It is exposed only where
  Generic planning is already supported.
- Worker and WebUI command requests place mode and identity under top-level
  `context`. No legacy runtime identity aliases are accepted in `arguments`.
- Existing one-shot and result payload identity fields remain project-specific;
  this context migration does not otherwise redesign output envelopes.
- Physical planning identity is used for dry-run/simulator planning, channel
  validation, and `channel: "all"` expansion. Fake or live-looking resources
  do not imply a model. Deterministic SIM resources may infer the matching model
  because they map to known simulator IDN/model data.
- Live hardware uses the manufacturer-plus-model resolved identity. `--model`
  becomes an expected-model guard in live mode. The guard never overrides the
  IDN-detected driver.

Selected data mappings:

- Dry-run and simulator plan payloads for output-family commands, `ramp-list`,
  `sequence`, `protection-set`, `clear-protection`, and trigger workflows
  identify `planning_model_id` and the Powers-specific `planning_profile_id`
  separately. Physical planning identity is used for channel validation and
  `channel: "all"` expansion. Trigger no-hardware plans accept only
  `keysight-e36312a`; unsupported models do not expose trigger dry-run or
  simulator behavior.
- `read-status`: `resource`, `errors`, `read_count`, and `outputs`.
- `readback`: `resource`, `idn_raw`, and `channels[].setpoints`.
- `measure`: selected channel measurements.
- `measure-all`: all supported channel measurements. Non-dry-run results,
  including simulator execution, also contain `data.idn` derived from the
  observed Core `idn_raw`. This sanitized object contains only `manufacturer`,
  `model`, `serial`, `firmware`, and `parse_ok`; it never contains the raw IDN
  string. Dry-run plans do not contain observed identity.
- `log`: bounded telemetry collection delegated to Core. CLI-owned CSV fields
  remain `timestamp`, `resource`, `resource_alias`, `model`, `serial`,
  `channel`, `programmed_voltage`, `programmed_current`, `measured_voltage`,
  `measured_current`, `output_enabled`, and `errors`, in that order. CLI JSONL
  uses `sample` events carrying those rows and a collection `summary`; CLI
  retains ownership of `--csv`, `--jsonl`, and `--append`. Worker `log` instead
  writes fixed job-local telemetry artifacts. The Sequence `log` action is a
  host-side note, while `--log-scpi` traces SCPI traffic to diagnostics rather
  than collecting telemetry.
- `set`: request arguments contain `channel` plus `voltage`, `current`, or
  both. Omitted setpoints are left unchanged, not defaulted. Successful results
  include `updated_setpoints` with only the setpoints actually written; full
  set requests also keep the existing top-level `voltage` and `current` fields.
- `output-state`: single-channel responses contain `channel` and the exact
  boolean `output_enabled`; they do not contain `output` or `outputs`.
  All-channel responses contain `channel: "all"` and a non-empty `outputs[]`
  whose entries contain `channel` and exact boolean `enabled`; they do not
  contain `output` or top-level `output_enabled`. After a Core success, the CLI
  validates the observed IDN, detected output-state channel inventory, and
  command-specific result shape before building this public payload. A missing,
  unsupported, or malformed observed identity, channel inventory, or result
  produces a schema-2 execution error with `code: "invalid_core_result"`,
  `retryable: false`, and exit code 3 instead of a success envelope.
- Other output-family commands retain their existing payloads. In particular,
  `output-on`, `output-off`, and `cycle-output` single-channel responses keep
  the existing `channel` plus `output` shape. Their `channel: "all"` responses
  keep `channel: "all"` and add `outputs[]` entries keyed by `channel`.
  `cycle-output` enables all channels, waits once for `duration_ms`, then
  disables all channels.
- `protection-status`: aggregate protection flags calculated as the OR of the
  selected channels, true per-channel protection flags, and output state.
- `snapshot`: a `schema_version: 2`, `kind: "powers-tool-snapshot"` document
  with separate `reported_identity` and canonical `resolved_identity`, plus
  errors, outputs, readback, measurements, and protection settings. PSM-2010
  documents additionally include the active range in `output_ranges`.
  `--snapshot-json PATH` writes this raw document atomically and can be used
  without JSON stdout. `--json --save-json PATH` separately writes the full
  CLI schema-2 envelope; restore does not unwrap that envelope. If both options
  are used, their paths must differ. Resource redaction applies to the raw
  snapshot too, and restore never depends on the saved resource field.
- `sequence`: lint/plan/execution status, step results, loop counters, and
  stop/failure details.
- `ramp` and `ramp-list`: requested `enable_output`, whether output enable was
  executed, successfully enabled channels, final output states from a normal
  completion readback, and cancellation cleanup diagnostics. Without output
  enable, final state is unchanged/not observed and no new output-state query
  is issued.
- A single-channel Ramp preserves `channel`. A multi-channel Ramp exposes the
  canonical selected `channels`; `enabled_channels`, `final_output_states`,
  and verification checks reflect that selection. A failed channel write does
  not complete the current logical voltage step and failure data identifies
  `failed_channel`.
- `ramp-list`: document version, per-iteration segment count, completed
  segment count, cumulative segment executions, ordered results, and failed
  Segment details with 1-based loop context. Version 5 plan and Segment results
  expose canonical `channels`; v2/v3/v4 retain their single `channel` shape.
  A partial multi-channel write reports `failed_channel` and the current
  logical step's `completed_channels` without completing that step.
- Ramp and Ramp List every-step pulse results use ordered `triggers` entries
  containing step index, voltage, and trigger result. Ramp-complete pulses are
  emitted once per iteration. Terminal Loop-complete pulse metadata remains
  under `trigger`; Ramp List per-Segment pulse results remain per Segment.
  Multi-channel Ramp List step and Segment pulses fire once, anchored to that
  Segment's first canonical channel; Loop-complete uses the last Segment's
  first canonical channel. The trigger channel is not a document setting.
- Ramp, Ramp List, and Sequence results expose `loop_count` and
  `completed_loops`. `segment_count`/`step_count` are per iteration;
  `completed_segment_executions`/`completed_step_executions` are cumulative.
  Legacy `completed_segments`/`completed_steps` describe the current or most
  recently attempted iteration. Failure and cancellation context includes a
  1-based `loop_index`.
- Workflow results include logical execution-unit totals and progress with
  `completed_units`, `total_units`, and integer `percent`. Detail streams that
  exceed 200 entries retain the first 100 and last 100, with additive
  total/retained/truncated fields. Aggregate counters always describe the full
  execution rather than only retained details.
- Ramp dry-run `steps` describe one voltage-path iteration plus any terminal
  workflow action; `voltage_steps_scope: "one_iteration"` and `loop_count`
  make that boundary explicit. Multi-channel plans expose canonical selected
  channels and one ordered driver action per channel for each logical voltage
  step; channel count does not multiply execution units. Completion-pulse plan actions do not depend on
  whether the workflow enables output.
- Loop-complete pulse results distinguish `requested`, `attempted`, `fired`,
  `completed`, `restored`, `restore_errors`, and `post_pulse_errors`. A
  restore or post-pulse failure may occur after physical `*TRG`; it fails the
  command without changing a recorded fired state. Completed workflow loops
  remain counted separately from terminal pulse success.
- Ramp always uses software setpoint writes and accepts
  `completion_pulse_pins`, `completion_pulse_polarity`,
  `completion_pulse_channel`, `leave_trigger_configured`, and
  `completion_pulse_timing`. Removed Native LIST/trigger-wait options are
  argparse errors. Completion pulse results report `native: false`.
- Direct Ramp, Ramp List, and Sequence Ctrl+C is cooperative. Schema-2
  cancellation uses top-level `status: "error"` with error code `cancelled`;
  cleanup failure uses `cleanup_failed`. Both use the existing runtime exit
  code `3` and include the original cancellation reason and cleanup details.
- `restore-from-snapshot`: accepts only the schema-2 snapshot document,
  validates canonical model identity and serial before writes, and returns
  restored channels and the restore plan. Successful real execution also
  returns `reported_identity` and `resolved_identity` derived from that
  command's observed instrument IDN; these fields are not copied from the
  snapshot document and do not include the raw IDN string. Dry-run and
  simulator plans do not contain observed identity. Legacy and unversioned
  snapshots are rejected rather than converted. Restore-relevant booleans
  must be exact JSON booleans, channels must be unique positive integers, and
  setpoints must be finite numbers; no persisted value is interpreted by
  truthiness.
  PSM-2010 snapshots require one `LOW` or `HIGH` `output_ranges` record per
  restored channel; the saved range must contain the saved voltage/current
  pair and is restored before either setpoint. Existing E36312A schema-2
  snapshots remain unchanged and do not use this optional extension.
- `trigger-list`: selected channel, step count, completion state, and
  `restored`; `restored: true` means the pre-run Trigger configuration and LIST
  table were written back after completion.
- `trigger-pulse`: selected channel, pins, polarity, triggered setpoints, and
  `restored`; `restored: true` means all three channels' pre-run Trigger/LIST
  state plus the rear digital pin and BUS trigger-output state were restored.
  It does not mean output channels were turned off.
- Failed post-admission `trigger-fire` execution envelopes that reach the
  fire/abort path include `data.trigger` with the observed `fired` and
  `completed` state plus `abort_attempted`, `abort_succeeded`, and
  `abort_errors`. Abort is best effort; an abort failure is diagnostic and does
  not replace the original trigger failure. Validation, argument, connection,
  and admission failures do not guarantee `data.trigger`.
- Live trigger behavior remains IDN-driven. Live `--model` is an
  expected-model guard and does not override connected hardware.
