# Supported Models

## Product Live Support Boundary

Normal Product LIVE execution uses the exact Product matrix below. Core
resolves the reported manufacturer plus model to one canonical physical
`model_id`, applies any expected-model guard, and requires an exact
`model_id + command + transport + backend + required feature` match. Missing,
unsupported, or non-Product-open scopes fail closed. A Product-open system VISA
scope does not inherit to pyvisa-py, pyvisa-bt, or a custom backend. No current
Product-open exact scope uses `pyvisa_bt`. E3646A and PSM-2010 remain ASRL /
RS-232 + system VISA only.

The `live_validated_full_suite` status identifies current Product-open exact
command scopes in the public support projection. For the machine-readable
policy-mode and status contract, see [Core support-policy contract](integration.md#support-policy-contract).
Contributor validation and evidence workflow is maintained in
[Contributing](../CONTRIBUTING.md).

## Product LIVE Exact-Scope Matrix

Core parses `*IDN?` and resolves reported manufacturer plus model to one
canonical physical `model_id`, checks any expected-model guard, and then
requires an exact `model_id + command + transport + backend + required
feature` match. Missing or non-Product-open scopes fail closed. A system VISA
scope does not extend to pyvisa-py, pyvisa-bt, or a custom backend.

The current `live_validated_full_suite` command inventories are:

| Model | Exact product connections | Product-open model-aware commands |
| --- | --- | --- |
| `keysight-e36312a` (Keysight E36312A) | USB + system VISA; TCPIP + system VISA | `measure`, `output-state`, `read-status`, `readback`, `validate-readonly`, `capabilities`, `set`, `output-on`, `output-off`, `safe-off`, `cycle-output`, `apply`, `ramp`, `smoke-output`, `ramp-list`, `sequence`, `protection-status`, `protection-set`, `clear-protection`, `snapshot`, `restore-from-snapshot`, `measure-all`, `log`, `doctor`, `trigger-status`, `trigger-step`, `trigger-list`, `trigger-abort`, `trigger-fire`, `trigger-pulse` |
| `keysight-edu36311a` (Keysight EDU36311A) | USB + system VISA; TCPIP + system VISA | `measure`, `output-state`, `read-status`, `readback`, `validate-readonly`, `capabilities`, `set`, `output-on`, `output-off`, `safe-off`, `cycle-output`, `apply`, `ramp`, `smoke-output`, `ramp-list`, `sequence`, `protection-status`, `protection-set`, `clear-protection`, `log`, `doctor` |
| `keysight-e3646a` (Keysight E3646A) | ASRL / RS-232 + system VISA | `measure`, `output-state`, `read-status`, `readback`, `capabilities`, `set`, `output-on`, `output-off`, `safe-off`, `cycle-output`, `apply`, `ramp`, `smoke-output`, `ramp-list`, `sequence`, `log`, `doctor` |
| `gw-instek-psm-2010` (GW Instek PSM-2010) | ASRL / RS-232 + system VISA | `measure`, `output-state`, `read-status`, `readback`, `validate-readonly`, `capabilities`, `set`, `output-on`, `output-off`, `safe-off`, `cycle-output`, `apply`, `ramp`, `smoke-output`, `ramp-list`, `sequence`, `protection-status`, `protection-set`, `clear-protection`, `snapshot`, `restore-from-snapshot`, `log`, `doctor` |

`list-resources`, `verify`, `identify`, `error`, and `clear` are explicit
diagnostic exemptions. Their success proves only that diagnostic operation; it
does not open a model, feature family, transport/backend scope, or another
command.

The Product-open command rows above are exact scopes, not transport/backend
inheritance. A command or feature not listed is not opened by another model,
connection, backend, or command family.

## Feature-Aware Exact Scopes

The Product-open command rows above are not wildcards for other command
sub-features. Core additionally checks `sequence_action` for each normalized
instrument-relevant Sequence step and `trigger_source` for Trigger Step/List.
Sequence `wait` and `log` remain host-only and need no live feature entry.
Current real trigger-source values are `bus` and `immediate` (`imm` normalizes
to `immediate`); PIN/EXT inputs remain rejected by request/profile validation.

On a Product-open connection, currently supported actions and sources are
Product-open. A pending connection or feature is not currently supported for
Product use; missing feature metadata does not open the scope.
Only Product-open feature entries are available to Product callers.

## Models Not Currently Available For Product Use

The following catalog-known model IDs are not active Product planning or live
expected-model identities: `keysight-e36313a`, `keysight-e36233a`,
`keysight-e36441a`, and `keysight-e36155a`.

`keysight-e36103b` and `keysight-e36232a` are de-scoped. They are rejected as
no-hardware planning identities, live expected-model guards, WebUI model
selections, and live model-aware operations. They must not fall back to
`GenericScpiPowerSupply`.

Other Keysight E36xxx / E36000-series models currently have no Product support.
`generic-scpi` remains a conservative no-hardware planning profile and is not a
physical live model.

## Connection-Scoped Product Support

Product support is scoped by model, connection, backend, command, and feature.

The current exact Product connections are E36312A USB and LAN, EDU36311A USB
and LAN, and E3646A and PSM-2010 ASRL / RS-232. Each connection remains limited
to the commands and feature entries listed in the Product matrix. E3646A and
PSM-2010 USB and LAN are outside the current scope.

The E36312A and EDU36311A TCPIP + pyvisa-py connections are not currently
available for Product use. System VISA support does not extend to pyvisa-py or
pyvisa-bt or a custom backend.

| Model | USB | LAN | ASRL / RS-232 |
| --- | --- | --- | --- |
| E36312A | accepted exact commands only | accepted exact commands only | N/A |
| EDU36311A | accepted exact commands only | accepted exact commands only | N/A |
| E3646A | not current scope | not current scope | accepted exact commands only |
| PSM-2010 | not current scope | not current scope | accepted exact commands only |

EDU36311A trigger/native LIST and snapshot/restore remain disabled in live,
simulate, and dry-run. E3646A protection, trigger/native LIST,
snapshot/restore, and completion-pulse remain disabled. E3646A `ramp-list` and
`sequence` remain software workflows only, not native LIST.

EDU36311A USB read-only, output/write, and protection commands are enabled for
real execution within the exact Product scopes above. EDU36311A
`protection-set` and `clear-protection` require `--confirm` for real execution
and report `hardware_validation=validated`.

Trigger workflows are E36312A-only. EDU36311A, E3646A, PSM-2010, and
`generic-scpi` do not expose trigger dry-run or simulator behavior; their trigger commands report
`real=false`, `simulate=false`, and `dry_run=false`.
PSM-2010 does not support Powers trigger workflows; its trigger commands also
report `hardware_validation=not_supported_by_model`.

## No-Hardware Planning Identity Matrix

Dry-run and simulate planning do not open real VISA hardware. Model-specific
no-hardware commands require an explicit planning identity or a known
deterministic SIM resource. Fake or live-looking resource strings are
placeholders and must not imply a model.

| Planning identity | Deterministic SIM resource | No-hardware channels | Output control scope | Trigger / LIST / protection notes |
| --- | --- | --- | --- | --- |
| `keysight-e36312a` | `USB0::SIM::E36312A::INSTR` | CH1, CH2, CH3 | Per-channel output control; `all` expands to CH1-CH3 | Trigger workflows and native LIST are E36312A-only and Product-open on supported live E36312A paths. Protection read/write paths are supported. |
| `keysight-edu36311a` | `USB0::SIM::EDU36311A::INSTR` | CH1, CH2, CH3 | Per-channel output control; `all` expands to CH1-CH3 | Protection read/write paths are supported. Trigger workflows and native LIST are not exposed in dry-run, simulate, or real mode. |
| `keysight-e3646a` | `ASRL1::SIM::E3646A::INSTR` | CH1, CH2 | Global output enable/disable; channel selection is used for setpoints and readback | RS-232 / ASRL output workflows are Product-open within the exact scope. Protection writes, trigger workflows, snapshot restore, completion pulses, and native LIST are disabled. |
| `gw-instek-psm-2010` | `ASRL1::SIM::PSM2010::INSTR` | CH1 | Global output control | Product LIVE includes the exact read-only, output, protection, snapshot/restore, ramp, and software-sequence commands in the matrix. LOW and HIGH ranges remain distinct. Powers trigger workflows are not supported by the model profile. |
| `generic-scpi` planning profile | None; use explicit `--profile generic-scpi` in dry-run | CH1 | Unknown | Conservative no-hardware planning only. Trigger workflows, native LIST, and protection writes are not exposed. |

Live hardware uses manufacturer-plus-model IDN resolution. In live mode,
`--model` maps to `RuntimeOptions.expected_model_id`: Core requires the
detected canonical identity to match and fails before command-specific SCPI on
mismatch. The guard never overrides the IDN-selected driver. `generic-scpi`
is a conservative nonphysical dry-run profile and is not a live expected model.

For model-aware live execution, Core makes the final Product decision using the
detected `*IDN?` model plus the exact command, transport, and VISA backend.
Missing and non-Product-open scopes reject in normal Product use; identity
diagnostics do not imply model or feature support.

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
| PSM-2010 | OUT1 / CH1 | LOW / P8V | 0 to 8.24 V | 0 to 20.6 A | N/A |
| PSM-2010 | OUT1 / CH1 | HIGH / P20V | 0 to 20.6 V | 0 to 10.3 A | N/A |

Sources: E36300 Series Programmable DC Power Supplies Programming Guide,
manual part number E36311-90008, printed page 16; EDU36311A Programming Guide,
manual part number EDU36311-90013, printed pages 15 and 39; Agilent E364xA
Dual Output DC Power Supplies User's and Service Guide, manual part number
E3646-90001, printed pages 82, 83, 84, and 91; GW Instek PSM-Series
Programming Manual, manual part number 82SM-60030IA, printed page 28. E3646A
and PSM-2010 ranges are range-dependent and are not flattened into a single
voltage/current maximum. At *RST, the E3646A low voltage range is selected.
The PSM-2010 manual documents an instrument-wide *RST current value of 20 A;
this does not mean 20 A is valid while HIGH range is retained. HIGH remains
limited to a 10 A rating and a 10.3 A programming maximum.

## Command Support Notes

`capabilities --json` includes a `command_support` map, and
`capabilities --command COMMAND --json` also returns `data.selected_command`
for one map entry. The matrix above must stay consistent with these
command-level facts:

- Unsupported model, command, and mode combinations fail intentionally. These
  feature-lock failures mean the workflow is not supported for that model,
  not that `--model` or the WebUI selector can unlock it.
- CLI `--model` and WebUI `runtime.planning_model_id` select canonical physical
  planning models in dry-run/simulate mode. Live requests instead use
  `expected_model_id`; driver selection always follows manufacturer-plus-model
  IDN resolution. `generic-scpi` uses the separate dry-run planning-profile
  field and is never a live expected model.
- E36312A native trigger/LIST support is exposed through `trigger-status`,
  `trigger-step`, `trigger-list`, and `trigger-abort`. The
  trigger dry-run and simulator paths are also E36312A-only. Native LIST
  execution is limited to 100 steps, dwell values from 0.01 to 3600 seconds,
  and count values from 1 to 256. Real native trigger sources are currently
  limited to BUS and immediate; rear pin and external input sources are not
  Product-open.
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
- EDU36311A snapshot and restore-from-snapshot are not Product-open for
  EDU36311A.
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
  software workflow limited to supported output/read-only steps. Neither is
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
- PSM-2010 Product execution is limited to ASRL / RS-232 + system VISA and the
  exact commands in the matrix above. It uses CH1, global output control, and
  distinct LOW/HIGH operating ranges. Its Product-open `sequence` actions are
  `apply`, `cycle-output`, `measure`, `output-off`, `output-on`,
  `output-state`, `readback`, `safe-off`, and `set`; `wait` and `log`
  remain host-only. The protection command family supports OVP configuration,
  OCP enable/status/trip behavior, and protection clear. OCP delay
  configuration, readback, and trigger remain unsupported. Powers trigger
  commands, all other transports, and all other VISA backends remain closed.
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
