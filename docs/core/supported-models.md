# Supported Models

## Product And Contributor-Validation Boundary

Normal product LIVE execution uses the exact product matrix below. The two
TCPIP + pyvisa-py entries remain registered pending scopes, not
product-open support: system-VISA evidence does not validate pyvisa-py or a
custom backend. An internal contributor-validation policy mode can evaluate
registered pending scopes; it
does not promote them, change public status metadata, or bypass physical
identity, model/profile, transport/backend, safety, confirmation, and request
validation. E3646A remains ASRL / RS-232 + system VISA only.

This document summarizes the checked-in Core live-support policy. The
authoritative command/transport/backend decisions are in
`src/powers_tool_core/support_policy.py`; the CLI contract documents
request and response shapes, not live-support promotion.

## Product LIVE Exact-Scope Matrix

Core parses `*IDN?` and resolves reported manufacturer plus model to one
canonical physical `model_id`, checks any expected-model guard, and then
requires an exact `model_id + command + transport + backend + required
feature` match. Missing and pending scopes fail closed. System-VISA evidence
does not validate pyvisa-py or a custom backend, and no public validation
bypass exists.

The current `live_validated_full_suite` command inventories are:

| Model | Exact product connections | Product-open model-aware commands |
| --- | --- | --- |
| `keysight-e36312a` (Keysight E36312A) | USB + system VISA; TCPIP + system VISA | `measure`, `output-state`, `read-status`, `readback`, `validate-readonly`, `capabilities`, `set`, `output-on`, `output-off`, `safe-off`, `cycle-output`, `apply`, `ramp`, `smoke-output`, `ramp-list`, `sequence`, `protection-status`, `protection-set`, `clear-protection`, `snapshot`, `restore-from-snapshot`, `measure-all`, `log`, `doctor`, `trigger-status`, `trigger-step`, `trigger-list`, `trigger-abort`, `trigger-fire`, `trigger-pulse` |
| `keysight-edu36311a` (Keysight EDU36311A) | USB + system VISA; TCPIP + system VISA | `measure`, `output-state`, `read-status`, `readback`, `validate-readonly`, `capabilities`, `set`, `output-on`, `output-off`, `safe-off`, `cycle-output`, `apply`, `ramp`, `smoke-output`, `ramp-list`, `sequence`, `protection-status`, `protection-set`, `clear-protection`, `log`, `doctor` |
| `keysight-e3646a` (Keysight E3646A) | ASRL / RS-232 + system VISA | `measure`, `output-state`, `read-status`, `readback`, `capabilities`, `set`, `output-on`, `output-off`, `safe-off`, `cycle-output`, `apply`, `ramp`, `smoke-output`, `ramp-list`, `sequence`, `doctor` |

`list-resources`, `verify`, `identify`, `error`, and `clear` are explicit
diagnostic exemptions. Their success proves only that diagnostic operation; it
does not open a model, feature family, transport/backend scope, or another
command.

The Product-open command rows above are exact scopes, not transport/backend
inheritance. A validation run produces reviewable evidence for its selected
model, connection, suite, and cases; it does not automatically promote Product
support.

## Feature-Aware Exact Scopes

The Product-open command rows above are not wildcards for other command
sub-features. Core additionally checks `sequence_action` for each normalized
instrument-relevant Sequence step and `trigger_source` for Trigger Step/List.
Sequence `wait` and `log` remain host-only and need no live feature entry.
Current real trigger-source values are `bus` and `immediate` (`imm` normalizes
to `immediate`); PIN/EXT inputs remain rejected by request/profile validation.

On an accepted Product connection, currently supported actions/sources retain
`live_validated_full_suite`. On the registered E36312A and EDU36311A
TCPIP/pyvisa-py pending parent scopes, implemented features remain
`feature_pending`. Product mode rejects those parent/feature scopes;
contributor Validation mode may use only the exact registered pending entries.
Missing feature metadata is not pending and fails closed in both modes.
A validated connection may contain both `live_validated_full_suite` and
`feature_pending` command features; Product mode opens only the validated
feature entries. A transport-pending connection cannot contain a validated
feature.

## Model Enablement Lifecycle

| Stage | Current models | Runtime meaning |
| --- | --- | --- |
| Product-active | `keysight-e36312a` (Keysight E36312A), `keysight-edu36311a` (Keysight EDU36311A), `keysight-e3646a` (Keysight E3646A) | Model-specific profiles/drivers with accepted exact Product scopes. |
| Candidate | None | Complete contributor model eligible only for explicitly pending Validation-mode scopes. |
| Catalog-only | `keysight-e36313a`, `keysight-e36233a`, `keysight-e36441a`, `keysight-e36155a` | Identity/catalog metadata only; not an active planning or live expected-model identity. |
| De-scoped | `keysight-e36103b`, `keysight-e36232a` | Blocked from Product, Validation, driver fallback, and live metadata. |

`generic-scpi` remains no-hardware/fallback-only and is not a physical model stage.
Adding the candidate lifecycle does not enable a new model. A candidate must
have complete driver, channel, simulator, capability, safety, electrical
rating, setpoint range/limit, test, and exact pending policy metadata before
entering that set. Feature-aware commands require a complete pending feature
inventory in every applicable exact scope; candidate status and validation
artifacts do not make it Product-open.

## Live Suite Validation Matrix

This table is the manually maintained source of truth for suite-based live
validation records. For each active model, `-Suite full` is the complete
validation gate for all currently project-supported LIVE features of that
model. With a passing full-suite record for the approved model and
connection, the model's currently project-supported LIVE features may be
opened. Disabled, unimplemented, out-of-scope, or factory-only features are
not implied by the pass. A passed `scripts/live-cli-check.ps1` run validates
only the selected target model, connection, suite, and cases in that run's
evidence. It does not validate unsupported suites, skipped
features, other connection types, every factory instrument function, or the
whole model.

| Target | Connection scope | Supported suites in `full` | Notes |
| --- | --- | --- | --- |
| E36312A | USB accepted evidence; LAN accepted evidence | `readonly`, `output`, `protection`, `snapshot`, `trigger-list`, `software-sequence` | The full suite covers Product-open `trigger-fire` and manually observed `trigger-pulse`. Suite names are evidence groupings, not command permissions. |
| EDU36311A | USB accepted evidence; LAN accepted evidence | `readonly`, `output`, `protection`, `software-sequence` | Suite names are evidence groupings, not command permissions. Trigger/native LIST, snapshot, and restore-from-snapshot remain unsupported. |
| E3646A | RS-232 / ASRL only | `readonly`, `output`, `software-sequence` | CH1/CH2 only. `OUTP ON/OFF` is global. `ramp-list` and `sequence` are software workflows, not native LIST. |

## Connection-Scoped Live Support Status

Live validation/opening is scoped by model, connection, suite, and cases. A
passed `scripts/live-cli-check.ps1` result only proves validation for the
selected model and connection; it does not mean the same feature is validated
on another connection type, another model, disabled workflows, or factory-only
features.

The current exact Product connections are E36312A USB and LAN, EDU36311A USB
and LAN, and E3646A ASRL / RS-232. Each connection remains limited to the
commands and feature entries listed in the Product matrix. E3646A USB and LAN
are outside the current scope.

The E36312A and EDU36311A TCPIP + pyvisa-py parent scopes remain registered as
`transport_pending` with `product_open=false`. Their implemented command
features remain `feature_pending`: contributor Validation mode may use only the
registered exact pending entries, while Product mode rejects them. System-VISA
evidence does not validate pyvisa-py or a custom backend, and passing evidence
does not update Product support automatically.

| Model | USB | LAN | ASRL / RS-232 |
| --- | --- | --- | --- |
| E36312A | accepted exact commands only | accepted exact commands only | N/A |
| EDU36311A | accepted exact commands only | accepted exact commands only | N/A |
| E3646A | not current scope | not current scope | accepted exact commands only |

EDU36311A trigger/native LIST and snapshot/restore remain disabled in live,
simulate, and dry-run. E3646A protection, trigger/native LIST,
snapshot/restore, and completion-pulse remain disabled. E3646A `ramp-list` and
`sequence` remain software workflows only, not native LIST.

EDU36311A USB read-only, output/write, and protection commands are enabled for
real execution within the exact Product scopes above. Use
`scripts/live-cli-check.ps1
-Target EDU36311A -Connection USB -Resource ... -Suite full` for current
suite validation. The full suite includes `software-sequence` for
project-supported software `ramp-list` and sequence read-only/output
workflows. The legacy smoke wrapper remains available for bounded smoke
checks only. EDU36311A `protection-set` and
`clear-protection` require `--confirm` for real execution and report
`hardware_validation=validated`.

Trigger workflows are E36312A-only. EDU36311A, E3646A, and `generic-scpi` do not
expose trigger dry-run or simulator behavior; their trigger commands report
`real=false`, `simulate=false`, and `dry_run=false`.

## No-Hardware Planning Identity Matrix

Dry-run and simulate planning do not open real VISA hardware. Model-specific
no-hardware commands require an explicit planning identity or a known
deterministic SIM resource. Fake or live-looking resource strings are
placeholders and must not imply a model.

| Planning identity | Deterministic SIM resource | No-hardware channels | Output control scope | Trigger / LIST / protection notes |
| --- | --- | --- | --- | --- |
| `keysight-e36312a` | `USB0::SIM::E36312A::INSTR` | CH1, CH2, CH3 | Per-channel output control; `all` expands to CH1-CH3 | Trigger workflows and native LIST are E36312A-only and validated for live E36312A paths. Protection read/write paths are supported. |
| `keysight-edu36311a` | `USB0::SIM::EDU36311A::INSTR` | CH1, CH2, CH3 | Per-channel output control; `all` expands to CH1-CH3 | Protection read/write paths are supported. Trigger workflows and native LIST are not exposed in dry-run, simulate, or real mode. |
| `keysight-e3646a` | `ASRL1::SIM::E3646A::INSTR` | CH1, CH2 | Global output enable/disable; channel selection is used for setpoints and readback | RS-232 / ASRL output workflows are live validated. Protection writes, trigger workflows, snapshot restore, completion pulses, and native LIST are disabled. |
| `generic-scpi` planning profile | None; use explicit `--profile generic-scpi` in dry-run | CH1 | Unknown | Conservative no-hardware planning only. Trigger workflows, native LIST, and protection writes are not exposed. |

Live hardware uses manufacturer-plus-model IDN resolution. In live mode,
`--model` maps to `RuntimeOptions.expected_model_id`: Core requires the
detected canonical identity to match and fails before command-specific SCPI on
mismatch. The guard never overrides the IDN-selected driver. `generic-scpi`
is a conservative nonphysical dry-run profile and is not a live expected model.

For model-aware live execution, Core makes the final product decision using the
detected `*IDN?` model plus the exact command, transport, and VISA backend.
Pending TCPIP/pyvisa-py and missing scopes reject in normal product use;
identity diagnostics do not imply model or feature support.

## Output Setpoint Programming Ranges

For output workflows, `voltage` means output voltage setpoint and `current`
means output current limit/current setting. The values below are programming
range metadata from the model manuals; they are separate from the existing DC
output rating safety limits. Powers Tool does not currently enforce a hard
manual-derived decimal-place rule and does not round or truncate user
setpoints before SCPI.

| Model | Channel / output | Range | Voltage programming range | Current-limit programming range | Current MIN keyword value |
| --- | --- | --- | --- | --- | --- |
| E36312A | CH1 / P6V | fixed | 0 to 6.18 V | 0 to 5.15 A | 0.001 A |
| E36312A | CH2 / P25V | fixed | 0 to 25.75 V | 0 to 1.03 A | 0.001 A |
| E36312A | CH3 / N25V | fixed | 0 to 25.75 V | 0 to 1.03 A | 0.001 A |
| EDU36311A | CH1 / P6V | fixed | 0 to 6.18 V | 0 to 5.15 A | 0.002 A |
| EDU36311A | CH2 / P30V | fixed | 0 to 30.9 V | 0 to 1.03 A | 0.001 A |
| EDU36311A | CH3 / N30V | fixed | 0 to 30.9 V | 0 to 1.03 A | 0.001 A |
| E3646A | OUT1 / CH1 | LOW / P8V | 0 to 8.24 V | 0 to 3.09 A | 0 A |
| E3646A | OUT1 / CH1 | HIGH / P20V | 0 to 20.60 V | 0 to 1.545 A | 0 A |
| E3646A | OUT2 / CH2 | LOW / P8V | 0 to 8.24 V | 0 to 3.09 A | 0 A |
| E3646A | OUT2 / CH2 | HIGH / P20V | 0 to 20.60 V | 0 to 1.545 A | 0 A |

Sources: E36300 Series Programmable DC Power Supplies Programming Guide,
manual part number E36311-90008, printed page 16; EDU36311A Programming Guide,
manual part number EDU36311-90013, printed pages 15 and 39; Agilent E364xA
Dual Output DC Power Supplies User's and Service Guide, manual part number
E3646-90001, printed pages 82, 83, 84, and 91. E3646A ranges are
range-dependent and are not flattened into a single voltage/current maximum.
At *RST, the E3646A low voltage range is selected.

E36103B and E36232A are not active supported models. They are rejected as
no-hardware planning identities, live expected-model guards, WebUI model selections,
`scripts/live-cli-check.ps1` targets, and live `*IDN?`-detected model-aware
operations. They must not fall back to `GenericScpiPowerSupply`. Other Keysight
E36xxx / E36000-series models are outside the current support matrix until the
complete model metadata, simulator/fake coverage, and model-specific hardware
evidence required by the contributor process exist.

## Command Support Notes

`capabilities --json` includes a `command_support` map, and
`capabilities --command COMMAND --json` also returns `data.selected_command`
for one map entry. The matrix above must stay consistent with these
command-level facts:

- Unsupported model, command, and mode combinations fail intentionally. These
  feature-lock failures mean the workflow is not enabled for that model yet,
  not that `--model` or the WebUI selector can unlock it.
- CLI `--model` and WebUI `runtime.planning_model_id` select canonical physical
  planning models in dry-run/simulate mode. Live requests instead use
  `expected_model_id`; driver selection always follows manufacturer-plus-model
  IDN resolution. `generic-scpi` uses the separate dry-run planning-profile
  field and is never a live expected model.
- E36312A full-suite artifacts provide evidence only for the exact commands
  listed in the product matrix above. A suite or feature-family label does not
  open every command in that family.
- E36312A native trigger/LIST support is exposed through `trigger-status`,
  `trigger-step`, `trigger-list`, and `trigger-abort`. The
  trigger dry-run and simulator paths are also E36312A-only. Native LIST
  execution is limited to 100 steps, dwell values from 0.01 to 3600 seconds,
  and count values from 1 to 256. Real native trigger sources are currently
  limited to BUS and immediate; rear pin and external input sources remain
  dry-run/simulator only until hardware validation.
- Ramp always uses software setpoint steps. Native LIST execution is confined
  to `trigger-list`.
- EDU36311A USB and LAN product execution is limited to the exact commands in
  the matrix above. Feature-family and sequence-step support do not widen that
  command inventory.
- E36312A and EDU36311A OVP/OCP trip status is queried per channel. Aggregate
  `protection-status` flags are the OR of the selected channel results.
- EDU36311A trigger commands remain disabled. `capabilities --json` reports
  all trigger commands with `hardware_validation=not_supported_by_model` and
  does not expose trigger dry-run or simulator behavior.
- EDU36311A snapshot and restore-from-snapshot are not enabled. They remain
  E36312A-only until separately implemented and hardware validated.
- EDU36311A `sequence` must not bypass disabled trigger/native LIST,
  snapshot, or restore workflows; unsupported sequence step types stay
  rejected in live, simulate, and dry-run paths.
- E3646A product execution is limited to ASRL / RS-232 + system VISA and the
  exact commands in the matrix above. `output-on` is Product-open only in that
  ASRL + system-VISA scope. Before any accepted live E3646A output command, confirm
  the physical setup has been checked and the requested voltage/current limits
  are safe for the connected load.
  `verify` is a model-independent connection diagnostic that opens the
  selected resource and queries `*IDN?`; it is not part of the model
  capability matrix. E3646A uses `INST:NSEL` channel preselection for channels
  1 and 2 and does not use channel-list SCPI for output writes. E3646A
  `OUTP ON/OFF` is a global output enable/disable; channel selection is still
  used for setpoint writes and readbacks, but output enable/disable affects the
  instrument output state globally. Protection changes, trigger workflows,
  snapshot, restore, completion pulses, and native LIST remain disabled.
  E3646A `ramp-list` is software setpoint stepping, and E3646A `sequence` is a
  software workflow limited to validated output/read-only steps. Neither is
  native instrument LIST support. E3646A sequence rejects unsupported step
  types such as protection, trigger, snapshot, restore, native LIST, and
  completion-pulse steps.
- E3646A serial settings are explicit only. If no serial options are provided,
  the program does not overwrite VISA backend, Keysight IO Libraries Suite, or
  Connection Expert serial settings. The factory example is 9600 baud, 8 data
  bits, none parity, 2 stop bits, and DTR/DSR handshake, but the actual
  front-panel settings may differ and are not auto-applied.
- E3646A `SYST:REM` and `SYST:LOC` are state-changing remote/local commands.
  They are sent only when `--serial-remote` or `--serial-local-on-close` is
  explicitly requested for an ASRL resource.
- No-hardware output-family, Ramp List, Sequence, `protection-set`,
  `clear-protection`, and trigger plans use strict planning identity.
  `--dry-run` and `--simulate` require either an explicit physical `--model`
  or a known
  deterministic SIM resource. Trigger no-hardware plans accept only
  `--model keysight-e36312a` or a known deterministic E36312A SIM resource such as
  `USB0::SIM::E36312A::INSTR`; an EDU36311A SIM resource is resolved and then
  rejected for trigger workflows. E3646A no-hardware `--channel all` plans
  expand to CH1 and CH2; CH3 is rejected.
- Live trigger behavior remains IDN-driven. `--model` is a live
  expected-model guard and does not override connected hardware.
- `snapshot-diff`, `snapshot-diff --summary`, and `hardware-report` are
  offline/no-hardware tools and never open VISA. `sequence --lint` also
  validates without opening VISA and remains syntax/document validation unless
  combined with `--dry-run` or `--simulate`.
