# Powers Tool Core

## Command Parameter Admission

Core owns the fail-closed command parameter registry used by all public command
adapters. Admission happens before hardware locks, VISA opens, SCPI I/O, or
state changes. Each command accepts only its documented fields; known fields
from another command are rejected as inapplicable. Raw values use exact JSON
types (boolean, integer, and finite number), explicit null is rejected unless
explicitly nullable, and aliases may not be supplied together. See the
[command parameter contract](../contracts/commands-parameter-contract.md).

Vendor-neutral Core library and driver layer for controlling supported DC
power supplies safely. Product-active and hardware-validated support is governed
by documented exact scopes; unknown live hardware remains closed. For the current
product-supported model matrix, see [Supported Models](supported-models.md).

Core ships inside the single `powers-tool` distribution while preserving
the `powers_tool_core` import boundary. It owns hardware-facing behavior
and is shared by the CLI and WebUI adapters.

## Purpose

This package owns the hardware-facing model logic, safety validation,
transport helpers, simulator support, snapshot handling, and parser-neutral
sequence runtime. It must stay independent from the CLI and WebUI packages.

Use the core package when another Python package needs to call the power-supply
runtime directly. End users should normally use the `powers-tool` console
script included in the same `powers-tool` distribution.

## Physical Identity And Registry Boundary

Core resolves a physical instrument from its reported manufacturer and model
before selecting a model-specific driver. Its physical catalog, lifecycle,
driver, channel, simulator, capability, electrical-range, and safety-coverage
registries use canonical vendor-qualified IDs such as
`keysight-e36312a`. Vendor-specific driver class names remain unchanged.

`RuntimeOptions` keeps the physical and nonphysical identity domains separate:
`planning_model_id` is a canonical physical planning identity,
`expected_model_id` is an optional live safety guard, and
`planning_profile_id` is a nonphysical dry-run profile. `generic-scpi` is not a
physical model or live expected model and is absent from physical registries.
`powers_tool_core.model_metadata.planning_profile_metadata()` is the public
Core-owned projection for nonphysical planning-profile metadata. It does not
place planning profiles in physical model, driver, electrical-rating, or
setpoint-range metadata.

## Live Support Policy Modes

The contributor-validation policy mode admits only registered pending scopes
and commands returned by Core `internal_validation_candidate_inventory()`.
Product mode remains fail-closed, and validation never mutates Product metadata.

`RuntimeOptions.support_policy_mode` defaults to `product`. After Core reads
`*IDN?`, it resolves the reported manufacturer plus model to a canonical
physical `model_id` and validates any expected-model guard. Product execution
then requires an exact `model_id + command + transport + backend + required
feature` scope before command-specific SCPI. Missing, unsupported, and pending
scopes fail closed.

Exact policy evaluation is feature-aware for `sequence_action` and
`trigger_source`. Sequence validates every distinct instrument-relevant
normalized action before its first step; host-only `wait` and `log` actions do
not require live feature entries. `trigger-step` and `trigger-list` validate
their effective BUS or Immediate source before trigger setup. A validated
command scope does not open an unregistered action/source. Missing,
unknown, unsupported, and Product-mode pending feature entries fail closed;
Validation mode accepts only explicitly registered `feature_pending` entries.
A validated transport/backend parent may mix validated and pending command
features: validated siblings remain Product-open, while each pending feature
remains Validation-only. A transport-pending parent cannot contain a validated
feature.

`powers_tool_core.support_policy.live_support_policy_metadata()` and
`exact_live_support_metadata()` provide JSON-ready display projections without
exposing validation artifacts or mutable registry records. The model-level
projection distinguishes profile support, explicit diagnostic exemptions, and
registered scopes. The exact projection evaluates one detected model,
resource transport, and backend in Product mode for adapter UX; it does not
replace the enforcing runtime gate. These projections use schema version 2 and
canonical `model_id`; they do not expose evidence IDs, artifact paths,
checksums, or private evidence notes. Unevaluated diagnostics distinguish
reported manufacturer/model fields from resolved physical identity and expose
no Product-open command map.

Identity/status diagnostics and pure offline utilities are separate in this
projection. Exempt diagnostics may report exact Product-policy metadata after
a real IDN read without acquiring a model feature scope. If the detected model
has no active exact policy, the diagnostic may still succeed with an
unevaluated, empty support projection; this does not open live commands or
enable Generic fallback. Expected-model mismatches remain validation errors.
Offline-only utilities are marked `offline_only`; they are not diagnostics and
are never reported as Product-open exact live commands.

## Package Contents

- `powers_tool_core.connection`: VISA backend selection, resource listing,
  identity query, and connection helpers.
- `powers_tool_core.factory`: IDN-based driver selection for generic SCPI,
  E36312A, EDU36311A, and E3646A instruments.
- `powers_tool_core.drivers`: model-specific driver implementations and
  shared SCPI channel strategies.
- `powers_tool_core.operations`: output and setpoint operations such as
  `set`, `apply`, `output-on`, `output-off`, `safe-off`, `ramp`, `ramp-list`, and
  readback/snapshot helpers.
- `powers_tool_core.readonly`: read-only `status`, `readback`,
  `measure-all`, log, and validation flows, including dry-run plans that do
  not open VISA.
- `powers_tool_core.trigger`: E36312A trigger, STEP, native LIST, fire, and
  abort support.
- `powers_tool_core.sequence`: parser-neutral sequence document loading,
  linting, dry-run planning, and execution.
- `powers_tool_core.ramp_list`: versioned JSON Ramp List loading, full
  prevalidation, planning, and ordered software-setpoint execution.
- `powers_tool_core.discovery`, `instrument_io`, `protection`, and
  `snapshot`: adapter-neutral runners for discovery, safe instrument I/O,
  protection, and snapshot commands shared by CLI and WebUI.
- `powers_tool_core.command_runner`: shared router used by adapters that
  submit parser-neutral core requests.
- `powers_tool_core.cancellation` and `stop_cleanup`: cooperative
  cancellation, interruptible waits, GPIB-only local release, and structured
  stop cleanup results shared by Worker and WebUI.
- `powers_tool_core.safety`: explicit local safety-config loading and plan
  validation.
- `powers_tool_core.electrical_ratings` and `setpoint_limits`: verified
  independent-channel DC output ratings and effective safety limits.
- `powers_tool_core.setpoint_ranges`: official output voltage setpoint and
  output current limit programming-range metadata from model programming
  manuals.
- `powers_tool_core.capabilities`: command and model capability reporting.
- `powers_tool_core.model_metadata`: public physical-model and nonphysical
  planning-profile metadata projections.
- `powers_tool_core.support_policy`: exact live-support enforcement metadata
  and safe public display projections.
- `powers_tool_core.support_evidence`: immutable accepted evidence metadata
  identities and non-sensitive support metadata.
- `powers_tool_core.model_resolution`: centralized runtime identity validation
  for dry-run/simulator planning and live expected-model guards.
- `powers_tool_core.model_enablement`: injectable consistency validation for
  Product-active, candidate, catalog-only, and de-scoped model inventories.
- `powers_tool_core.testing`: no-hardware simulator used by tests and CLI
  simulation mode.

## Install

The root [README Install guide](../../README.md#install) is the canonical
setup reference. From the repository root, synchronize the basic Core/CLI
runtime environment with:

```powershell
uv sync --locked --link-mode=copy
```

For Core tests or other development tasks, use the locked environment with all
extras:

```powershell
uv sync --all-extras --locked --link-mode=copy
```

Runtime installs resolve `pyvisa`, PyYAML for sequence YAML support, and the
Python-version TOML fallback where needed. The `powers_tool_core` import
package has no component-specific console command. The single `powers-tool`
distribution still installs the `powers-tool`, `powers-tool-webui`, and
`powers-tool-webui-launcher` console entry points. This project supports Python
`>=3.10`; test dependencies come from the root `dev` extra.

## Test

The default core tests are no-hardware tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core -q -p no:cacheprovider
```

Focused suites are useful when changing specific layers:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core\test_model_drivers.py tests\core\test_trigger.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\core\test_operations.py -q -p no:cacheprovider
```

Pytest uses the ignored repository-local `.tmp_pytest` directory by default,
so tests do not depend on access to the Windows system temporary directory.
Run pytest from the repository root. For an intentional per-run override, use
`--basetemp .tmp_tests/<purpose>`. Do not use `Local/` for pytest temporary
data or generated test artifacts.

The repository-level validation scripts also exercise Core through the CLI
adapter. Run the model-aware no-hardware preflight before a plan-only live
wrapper check:

```powershell
.\scripts\preflight-cli.ps1 -Target all -Suite smoke
.\scripts\live-cli-check.ps1 -Target keysight-e36312a -Connection USB -Resource SIM::E36312A -Suite readonly -PlanOnly
```

Live suite checks and hardware pytest are explicit, opt-in hardware checks.
`scripts\live-cli-check.ps1` is the maintained contributor validation harness
and records target/connection/suite/case candidate-evidence artifacts under
`.tmp_tests`; passing artifacts do not automatically promote product support.
See [Contributing](../CONTRIBUTING.md) for the contributor workflow. For each
active model, `-Suite full` is the complete validation gate for all
project-supported LIVE features of that model.

A passing full-suite record applies only to the selected model and connection
and is evidence for maintainer review. Product support changes only through an
explicit evidence-backed policy decision; the record itself does not open any
command or feature.

Disabled, unimplemented,
out-of-scope, or factory-only features are not implied by the pass. A passing
suite validates only the selected model, connection, suite, and recorded cases;
it does not validate other connection types or every factory instrument
function. Commands, state-changing behavior, and report locations are
documented in the [CLI README scripted validation section](../cli/README.md#scripted-validation).

## Docs

- Core integration guide: `integration.md`
- Supported models: `supported-models.md`
- CLI JSON contract that consumes core envelopes: `../contracts/power-cli-jsonl-contract.md`
- Root workspace README: `../../README.md`
- CLI validation scripts: `../cli/README.md#scripted-validation`
- Commands parameter contract: `../contracts/commands-parameter-contract.md`

## Status

Model-specific driver foundations are selected from valid `*IDN?` responses.
Channel-list SCPI, snapshot/readback parsing, protection state handling,
sequence loading/planning, safety validation, simulator behavior, and
output-operation planning are covered by no-hardware tests.

`generic-scpi` is a no-hardware planning profile, not a physical-model lifecycle
stage.

E36312A and EDU36311A protection trip reads use channel-list queries. Shared
Core protection status preserves aggregate flags while calculating them from
the selected channels, and the WebUI live-panel read returns parsed model
identity plus channel-local OVP/OCP trip state.

LIST execution belongs only to `trigger-list`; Ramp always uses software
setpoint steps. `generic-scpi` is a nonphysical no-hardware planning profile,
not a physical trigger planning model.

The `full` suite requires external operator observation for
`trigger-pulse`; passing a wrapper run still does not automatically promote a
command.

A feature family does not open other commands. Software `ramp-list` and step-limited
`sequence` are not native LIST support.

For output workflows, `voltage` is the output voltage setpoint and `current`
is the output current limit/current setting on E36312A, EDU36311A, and
E3646A. Core exposes official programming-range metadata separately from
independent-channel DC output rating safety limits. The manuals document common
SCPI numeric parameter handling, so this metadata does not introduce
decimal-place rejection or silent rounding/truncation in Core.

The adapter boundary is intentionally one-way: core contains driver methods,
SCPI helpers, simulator selection, no-hardware model resolution, and dry-run
planning; CLI and WebUI build `RuntimeOptions`/`OperationRequest` objects and
wrap returned `data` in their own transport envelopes.

Dry-run and simulator planning does not guess a model from arbitrary resource
strings. Output-family, Ramp List, Sequence, protection write, and trigger
planners require `RuntimeOptions.planning_model_id`, an allowed dry-run
`planning_profile_id`, or a known deterministic simulator resource. Returned
plans identify physical and nonphysical planning identities separately.
Fake or live-looking resources such as `USB0::FAKE::E36312A::INSTR` are test
placeholders and must not imply a model. Deterministic SIM resources such as
`USB0::SIM::E36312A::INSTR` are accepted because they map to known simulator
IDN/model data. Trigger no-hardware planning accepts only E36312A. Live
hardware uses the manufacturer-plus-model IDN resolution. In live mode,
`expected_model_id` is a safety guard: after `*IDN?`, Core requires the
detected canonical `model_id` to match
before setup/write SCPI. The selected model never overrides the IDN-selected
driver.

After that guard, Core enforces exact product support using the resolved
canonical `model_id`, effective command, VISA resource transport, runtime
backend, and required feature. Missing or pending scopes fail closed before
command-specific I/O. This applies equally to direct Core callers and adapter
requests; no validation-mode bypass exists.

## Output Workflow Pulses

Ramp, Ramp List, and Sequence support a strict `loop_count` total iteration
count from 1 through 10,000. Old Ramp List v2/v3 and Sequence v1 documents imply
one iteration; Ramp List v4 and Sequence v2 persist `loop_count`. Result
`segment_count` and `step_count` remain per iteration. `completed_loops` counts
only whole successful iterations, while `completed_segment_executions` and
`completed_step_executions` are cumulative across iterations.

Core admits at most 1,000,000 logical execution units: Ramp counts voltage
steps, Ramp List sums voltage steps across all Segments, and Sequence counts
Steps, then multiplies that per-iteration work by `loop_count`. Adapters warn
above 100,000 units. Runtime detail arrays retain at most the first 100 and
last 100 entries with additive total/retained/truncated metadata, while
aggregate counters cover the complete execution. Long-running workflows report
integer-percent progress using completed and total execution units.

Completion pulses use E36312A rear digital pins; rear pins are separate from
the selected output channel. Ramp `step` timing pulses after every voltage
write in every iteration, `segment` pulses once after each complete Ramp
iteration, and `loop` pulses once after all iterations. Ramp List keeps its
per-step and per-Segment behavior in every iteration; `loop` pulses once using
the last Segment channel as an internal trigger anchor. Every-step timing
accepts `delay_ms = 0`. Sequence has no top-level completion pulse; its
per-Step `trigger-pulse` action is unchanged.

Ramp dry-run plans show the voltage path for one iteration and report the total
iteration count separately as `loop_count`. Pulse actions follow execution
order independently of `enable_output`: Ramp-complete follows the iteration's
setpoint checks, while Loop-complete is the terminal workflow action. Every
planned Ramp pulse uses the same effective `completion_pulse_channel` anchor as
execution; rear-pin selection remains a separate setting.

A Loop-complete pulse is attempted only after the workflow iterations, final
setpoint/output verification, workflow error-queue check, and final
cancellation check succeed. Its result distinguishes `requested`, `attempted`,
`fired`, `completed`, `restored`, `restore_errors`, and
`post_pulse_errors`. Because `*TRG` is sent before trigger restoration, a
restore, post-pulse error-queue, release, or close failure can occur after the
physical pulse. Such failures fail the command without falsely changing the
recorded fired state. `completed_loops` remains complete when only the
terminal Loop-complete pulse fails; a per-iteration Ramp-complete pulse is
part of that iteration and must succeed before its loop is counted.

Ramp and Ramp List leave output state unchanged by default. Optional
`enable_output: true` enables an output only after the current limit and first
voltage setpoint are validated and written, then requires an ON readback.
Normal completion leaves enabled outputs ON and reads their final state again.

Ramp List version 2 keeps `kind: "powers-tool-ramp-list"` and remains accepted
with fixed `enable_output: false` and `loop_count: 1` semantics. Version 3
requires an exact top-level JSON boolean `enable_output` and also implies one
iteration. Version 4 requires both `enable_output` and `loop_count`. Sequence
v1 implies one iteration and forbids `loop_count`; Sequence v2 requires it.
Missing, wrong-type, unknown, legacy, and future-version fields are rejected
before hardware I/O. Explicit CLI loop overrides upgrade supported older
documents internally without mutating the loaded document.

`segment_count` and `step_count` describe one document iteration.
`completed_loops` counts fully completed iterations.
`completed_segments` and `completed_steps` describe the current or most
recently attempted iteration, while `completed_segment_executions` and
`completed_step_executions` are cumulative across iterations. Failed or
cancelled item context contains a 1-based `loop_index` plus its normal Segment
or Step index. Single-iteration successful item shapes remain compatible.

Ramp, Ramp List, and Sequence cancellation is cooperative. After the current
VISA call returns, Core stops future workflow steps and pulses, uses the same
session to request OFF on every supported channel, verifies every channel OFF,
drains the error queue with a 20-read bound, and then lets the owning session
close. Only complete cleanup reports cancellation; an OFF, readback, error
queue, or session-close failure reports `cleanup_failed`. This workflow stop
is not a hardware emergency stop and is separate from `trigger-abort`, which
aborts Trigger/LIST execution without guaranteeing output OFF.
Sequence documents accept the canonical `trigger-pulse` action. Software
pulses snapshot and restore trigger/digital pin settings unless
`leave_trigger_configured` is explicitly requested.
They send global `*TRG`, which may also trigger other armed BUS behavior.
