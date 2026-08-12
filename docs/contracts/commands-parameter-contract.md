# Commands Parameter Contract

Core owns the numeric parameter constraints used by direct Core requests, CLI,
Power Worker, and WebUI Commands. Adapter defaults are not limits.

## Raw Request Admission

Core is the single authority for command parameter admission. Every raw Worker
and WebUI command request is checked against its command-specific allowed
fields before a hardware lock, VISA open, or SCPI I/O. Unknown fields and
fields belonging to another command fail closed. Explicit JSON `null` is
rejected unless a documented field is nullable.

Raw booleans are exact JSON booleans, integers are exact JSON integers, and
numeric values are finite JSON numbers; strings such as `"false"` and `"1"`,
booleans used as numbers, and numeric strings are not coerced. CLI argparse
values are already parsed Python primitives and pass through the same Core
contract. Aliases are accepted only when one spelling is supplied; two aliases
for the same value are an admission error.

Admission canonicalizes a request once, before a Worker job, WebUI job, VISA
open, or hardware lock. Sequence, Ramp List, and snapshot-restore file sources
are read and strictly validated at that boundary, deep-copied into `document`,
and their source path field is removed. Execution consumes only this admitted
document, so replacing or deleting a source file after submission cannot
change a queued workflow. Re-admitting an already admitted request is
idempotent.

Only semantic defaults are materialized. In particular, trigger controls and
read-only/all-channel selectors have canonical defaults, while optional
completion-pulse and other presence-sensitive settings remain absent unless
the caller supplied them. Protection uses the canonical `channel` selector;
the compatibility form `all: true` becomes `channel: "all"`. Supplying both
forms, including `all: false`, is rejected; a lone `all: false` is not an
all-channel selector and is an admission failure. `protection-status` and
`protection-set` default to `channel: "all"` only when no selector was
supplied at all. `clear-protection` always requires an explicit `channel` or
`all: true` selector.

Top-level telemetry `log` is separate from the Sequence action named `log`.
The top-level command accepts only Core execution semantics: exactly one of
`channel` (positive integer or `"all"`) and `channels` (non-empty positive
integer list), exactly one of positive integer `samples` and positive numeric
`duration_sec`, plus positive numeric `interval_sec`. Channel-list order and
duplicates are preserved. Adapter fields such as `csv`, `jsonl`, and `append`
are not Core parameters. The Sequence `log` action remains a host-side
message/note action with `message`; it does not collect telemetry.

## Fixed Limits

- Public Core and raw JSON `channel` values are type-strict: an accepted
  channel is an exact positive integer. Exact `"all"` is accepted only by
  commands that support all-channel selection. Booleans, floats, numeric
  strings, whitespace-padded strings, null, arrays, objects, and alternate
  spellings such as `"ALL"` are rejected rather than coerced. CLI text is
  parsed by argparse before it reaches this contract.
- Voltage and current values must be finite and non-negative.
- `set` requires `channel` plus at least one of `voltage` or `current`.
  Supplying only one setpoint leaves the omitted setpoint unchanged on the
  instrument; adapters must not replace omitted values with zero or readback
  guesses.
- `apply`, `ramp`, `smoke-output`, Ramp List, and Sequence set/apply steps keep
  their complete setpoint requirements.
- Ramp requires exactly one selector: an exact positive integer `channel`, or
  a non-empty `channels` list of unique positive integers. Core rejects
  duplicates and unsupported channels, then orders `channels` by the selected
  or detected model's canonical channel order. There is no Core `all` value
  for Ramp; adapters may materialize All as an explicit list.
- `restore-from-snapshot` requires an explicit `channel`, accepting one exact
  positive integer or exact `"all"`; omission never defaults to all channels.
- `step_voltage` must be finite and greater than zero.
- Ramp and Ramp List `delay_ms` is the additional delay after each voltage
  step completes before starting the next step. It is a non-negative integer.
- Ramp `enable_output` is an optional exact boolean and defaults to `false`.
  Ramp List version 2 always means `false`; versions 3 and 4 require an exact
  top-level JSON boolean. Adapters must not coerce strings or numbers.
- Ramp, Ramp List, and Sequence `loop_count` is the total number of complete
  workflow executions. It must be an exact integer from 1 through 10,000;
  booleans, floats, strings, null, zero, negatives, and 10,001 are rejected.
  `1` is one normal execution, while `2` restarts once. Ramp List v4 and
  Sequence v2 require the field. Older supported document versions imply 1.
- Core calculates logical execution units before opening hardware: Ramp uses
  `loop_count * voltage_step_count`, Ramp List uses `loop_count` times the sum
  of all Segment voltage-step counts, and Sequence uses `loop_count *
  sequence_step_count`. Values through 1,000,000 are admitted; larger requests
  are rejected with the calculated and maximum values plus reduction guidance.
  Adapters warn, without another confirmation mode, above 100,000 units.
- A general completion pulse may set `completion_pulse_channel` as its output
  trigger anchor. An explicitly supplied value must be an exact integer from 1
  through 3 and requires non-empty `completion_pulse_pins`; booleans, floats,
  strings, null, zero, negatives, and values above 3 are rejected. The anchor
  channel and rear pins are independent settings.
- `hold_ms`, settle delays, and Sequence waits are non-negative.
- Cycle Output, Smoke Output, and Sequence Cycle `duration_ms` are positive
  integers.
- `max_reads`, `max_errors`, and `wait_timeout_ms` are positive integers.
- Trigger poll intervals are integers of at least 50 ms.
- Trigger LIST count is 1 through 256. LIST dwell is 0.01 through 3600 seconds.
- Native Trigger LIST accepts canonical `bost_list`, `eost_list`,
  `trigger_output_pins`, and `trigger_output_polarity`. BOST/EOST lengths must
  match the voltage step count, and any enabled BOST/EOST pulse requires
  explicit output pins. Legacy `completion_pulse_pins` remains a final-step
  EOST pulse and must not be mixed with canonical fields.
- Native `trigger-step` and `trigger-list` reject `fire=true` with Immediate
  source because `INIT` starts Immediate execution.
- Native BUS `trigger-step` and `trigger-list` requests with
  `wait_complete=true` require `fire=true` in the same command.
- Native `trigger-list` arm-only requests require
  `leave_trigger_configured=true`, so a later `trigger-fire` can start the
  armed LIST.
- A started native `trigger-list` without `wait_complete=true` requires
  `leave_trigger_configured=true`, so restore does not abort the active LIST.
- With `wait_complete=true` and `leave_trigger_configured=false`, native
  Trigger LIST restores the pre-run Trigger configuration and LIST table after
  completion. `leave_trigger_configured=true` retains the newly configured
  LIST table.
- `trigger-fire` sends global `*TRG`. When `wait_complete=true`, `channel` is
  required only as the output channel to abort if the instrument-wide
  completion wait times out or is interrupted.
- Ramp supports at most 1000 voltage steps. Ramp List supports 1 through 10
  segments, each with at most 1000 voltage steps.

No unspecified maximum is added to time or read-count fields.

## Ramp Timing

Ramp and Ramp List use software setpoint steps. A multi-channel Ramp writes the
same voltage to every selected channel in canonical order; the logical step
completes only when every write succeeds. `delay_ms` starts only after the
logical voltage step and any synchronous every-step completion pulse finish. It
does not include write or pulse execution time and is not a real-time or exact
step interval.

One canonical timing is selected. Ramp accepts `step` (every voltage step),
`segment` (Ramp complete after each iteration), or `loop` (once after every
iteration). Ramp List accepts `step`, `segment` (after each Segment), or
`loop`. Loop-complete timing requires `loop_count >= 2`. Every-step pulses
accept `delay_ms = 0`.

With `enable_output: true`, Ramp validates every effective setpoint for every
selected channel before writes, then orders current, first voltage, output ON,
mandatory ON readback for all selected channels,
remaining voltage steps, per-iteration Ramp-complete pulse when selected, and
final output-state readback. E3646A performs its global output ON only once;
its selected channel setpoints remain per-channel. Ramp List applies the same first-setpoint rule
once per channel and does not repeat output ON in later segments or loops.

## Effective Electrical Limits

The verified independent-channel `DC output rating (0 to 40 C)` is a hard
setpoint maximum:

| Model | Channel | Maximum voltage | Maximum current |
|---|---:|---:|---:|
| E36312A | 1 | 6 V | 5 A |
| E36312A | 2, 3 | 25 V | 1 A |
| EDU36311A | 1 | 6 V | 5 A |
| EDU36311A | 2, 3 | 30 V | 1 A |

Sources are Keysight `E36300 Series Triple Output Bench Power Supply`,
publication `5992-2124EN`, dated `2023-08-25`, and `EDU36311A Triple-Output
Bench Power Supply`, publication `3121-1003.ZHTW`, dated `2021-01-11`.

An official electrical rating may define multiple operating ranges for one
channel. Its maximum voltage and maximum current then describe the independent
envelope, not permission to use every combination inside that envelope. When a
request supplies both voltage and current, the pair must fit within at least one
official operating range. A request that supplies only one value retains the
independent scalar maximum check.

Official ratings and safety config remain separate. The effective maximum is
the smaller value. A more permissive safety config never widens an official
rating. Confirmation thresholds remain safety-config policy only.

These ratings are not claims about SCPI maximum programmable values. Unknown
models have no invented rating. Output-family, Ramp List, Sequence, and
protection-write dry-run/simulate planning requires an explicit model profile
or a known deterministic simulator resource before model-specific channel
validation. In live mode, CLI `--model` / `runtime.expected_model_id` is only an
expected-model guard checked against `*IDN?`; it does not choose the driver or
provide channel/capability limits. OVP values are not constrained by the DC
output rating. Auto-series and parallel combined ratings are unsupported.
