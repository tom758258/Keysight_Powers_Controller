# Powers Tool CLI

## Parameter Admission

The CLI sends argparse-parsed Python primitives to the shared Core command
contract. This preserves valid flag usage while keeping raw Worker/WebUI JSON
fail closed: Core rejects unknown or inapplicable fields, aliases supplied
together, explicit nulls unless documented nullable, and coercible strings or
numbers used in place of exact booleans, integers, or finite numeric fields.

Vendor-neutral CLI adapter for controlling supported DC power supplies.
Current Product-active and hardware-validated models are the documented
Keysight models; unknown live hardware remains fail closed.

The CLI ships inside the single `powers-tool` distribution while
preserving the `powers_tool_cli` import boundary. It exposes the
`powers-tool` console command and adapts operator commands to the shared
`powers_tool_core` runtime.

## Documentation Set

- [CLI User Guide](USER_GUIDE.md) - operator workflow, live resource
  selection, and safe first checks.
- [CLI README](README.md) - engineering setup, validation scripts, detailed
  command reference, automation, and maintainer boundaries.
- [Power CLI JSON / JSONL Contract](../contracts/power-cli-jsonl-contract.md)
  - command-line JSON envelope and JSONL rules.
- [Power Worker Contract](../contracts/power-worker-contract.md) - local
  worker REST, JSONL, and artifact contract.
- [Power Orchestrator Workflows](../contracts/power-orchestrator-workflows.md)
  - subprocess handoff and result polling guidance.
- [Commands Parameter Contract](../contracts/commands-parameter-contract.md)
  - stable command parameter boundaries.

## Purpose

This package provides the `powers-tool` console script, command argument
parsing, JSON envelope handling, SCPI logging, command adapters over
`powers_tool_core`, and the local Power Worker daemon used by
orchestrators/agents.

Hardware-affecting commands remain explicit and opt-in; the default package
test suite runs without hardware.

For normal operator workflows, start with the [CLI User Guide](USER_GUIDE.md).
This README keeps the detailed command reference, validation paths,
JSON/JSONL contracts, examples, and maintainer-facing CLI behavior in one
place.

## Package Contents

- `powers_tool_cli.cli`: top-level argument parser, command dispatch, stream
  emission, error/exit mapping, SCPI logging, and runtime adapters into Core.
- `powers_tool_cli.cli_io`: stable JSON success/error envelope helpers and
  optional `--save-json` output.
- `powers_tool_cli.cli_rendering`: pure human-readable success-line formatters
  for shared Output, Trigger, plan, Sequence, discovery, read-only, inspection,
  write, workflow, and artifact-success summaries. `cli.py` retains stream
  emission, JSON/error/exit mapping, SCPI logging, streaming, and artifact
  serialization.
- `powers_tool_cli.lifecycle_client`: Worker lifecycle HTTP request construction,
  response validation, dry-run handling, lifecycle output, and error mapping.
- `powers_tool_cli.request_primitives`: shared argv parsing and JSON request
  envelope fields, including serial, completion-pulse, and write-verification
  request shapes.
- `powers_tool_cli.runtime_mapping`: runtime identity, execution, support-policy,
  and serial-option mapping for Core requests.
- `powers_tool_cli.worker`: local async worker service, config validation,
  event emission, job queueing, artifact writing, and `/command`/`/stop` HTTP
  endpoints.
- `powers_tool_cli.commands.lifecycle`: Worker lifecycle parser registration.
- `powers_tool_cli.commands.output`: output command parser registration, runner
  adapter, and JSON request-envelope mapping.
- `powers_tool_cli.commands.ramp_list`: independent Ramp List parser
  registration and request-envelope mapping.
- `powers_tool_cli.commands.sequence`: sequence command registration and CLI
  request conversion.
- `powers_tool_cli.commands.trigger`: Trigger parser registration, runner
  adapter, and Trigger JSON request-envelope mapping.

Parser construction binds explicit runner callables. Command-family modules
import shared argparse primitives directly from `powers_tool_cli.cli_parser`
and receive only their own execution callback; parsed argparse Namespaces do
not carry the top-level `powers_tool_cli.cli` module or another service-locator
object. Request mapping remains owned by the command-family modules and the
existing CLI facades.

## Requirements

The root [README Install guide](../../README.md#install) is the canonical setup
reference. See [Supported Models](../core/supported-models.md) for the exact
Product support matrix; this section does not add support for another model,
transport, or backend.

| Requirement | No-hardware | Live operation |
| --- | --- | --- |
| Python | Use the minimum version declared by `pyproject.toml`: `>=3.10`. | The same Python requirement applies. |
| Core/CLI runtime | Install the current `powers-tool` distribution. | Install the current `powers-tool` distribution. |
| No-hardware | Simulator, dry-run, CLI help, and ordinary tests do not require a physical instrument or vendor VISA runtime. | Not applicable. |
| Live hardware | Not applicable. | Requires a supported physical instrument, an external VISA implementation/runtime that PyVISA can load, and an applicable accepted connection/backend scope. Resource-specific live commands require an explicit operator-selected VISA resource; discovery commands can enumerate resources without a pre-supplied resource. |
| Product support | No-hardware availability does not imply live support. | Model-aware live commands follow the exact `model + command + transport + backend + required feature` scope in [Supported Models](../core/supported-models.md). Diagnostic exemptions remain limited to their documented diagnostic purpose. |
| Safety | Preview and simulator paths do not enable real output. | Output-affecting commands remain subject to the existing confirmation gates and safety limits. |

## Install

The root [README Install guide](../../README.md#install) is the canonical
setup reference. From the repository root, synchronize the locked development
and test environment before running the commands in this document:

```powershell
uv sync --all-extras --locked --link-mode=copy
```

Alternatively, for a basic Core/CLI runtime-only environment, use:

```powershell
uv sync --locked --link-mode=copy
```

The primary installed console entry point is `powers-tool`.

The fallback module entry point is:

```powershell
uv run python -m powers_tool_cli.cli doctor --simulate --json
```

The global `powers-tool --version` option prints `powers-tool <package-version>`
and exits without requiring a subcommand or opening VISA.

## Quick Start

Use these commands from the project root to confirm the installed console entry
point, basic CLI/Core loading, and the deterministic simulator no-hardware path:

```powershell
uv run powers-tool --version
uv run powers-tool doctor --simulate --json
```

This Quick Start does not perform live or system-VISA resource discovery, open a
VISA resource, send SCPI, modify physical instrument state, or enable output. It
does not require a physical instrument or vendor VISA runtime.

For normal operator workflows, continue with the [CLI User Guide](USER_GUIDE.md).
To use the local browser interface, see the
[WebUI User Guide](../webui/USER_GUIDE.md). Exact live model and connection
coverage is documented in [Supported Models](../core/supported-models.md).

## Command Family Index

This is a quick orientation index, not a replacement for
`powers-tool --help` or the detailed examples below.

| Family | Purpose | Representative commands | Details |
| --- | --- | --- | --- |
| Setup and diagnostics | Installation, discovery, identity, error, and safety checks. | `powers-tool --version`, `doctor`, `list-resources`, `verify`, `identify`, `error`, `clear` | [Resource Discovery And Live Resource Setup](#resource-discovery-and-live-resource-setup); `powers-tool --help` |
| Read-only and state | Measurements, readback, output state, capabilities, and instrument status. | `measure`, `measure-all`, `read-status`, `readback`, `output-state`, `capabilities` | [Read-Only Command Examples](#read-only-command-examples); `read-status` is the instrument command. |
| Setpoint and output control | Setpoints, output transitions, safe-off, and guarded output actions. | `set`, `apply`, `output-on`, `output-off`, `safe-off`, `cycle-output`, `smoke-output` | [Output-Affecting Examples](#output-affecting-examples); [Safety Defaults](#safety-defaults) |
| Output workflows | Ramps, ramp lists, software sequences, and telemetry logging. | `ramp`, `ramp-list`, `sequence`, `log` | [Ramp And Sequence Examples](#ramp-and-sequence-examples); [Safety Defaults](#safety-defaults) |
| Protection | Protection status, configuration, and clearing. | `protection-status`, `protection-set`, `clear-protection` | [Protection And Trigger Examples](#protection-and-trigger-examples); `powers-tool --help` |
| Trigger | Trigger status, setup, firing, abort, pulse, and LIST workflows. | `trigger-status`, `trigger-step`, `trigger-list`, `trigger-fire`, `trigger-abort`, `trigger-pulse` | [Protection And Trigger Examples](#protection-and-trigger-examples); exact feature scope still applies. |
| Snapshot and restore | Capture, compare, report, and restore saved instrument state. | `snapshot`, `snapshot-diff`, `hardware-report`, `restore-from-snapshot` | [Snapshot And Restore Examples](#snapshot-and-restore-examples); [Power CLI JSON / JSONL Contract](../contracts/power-cli-jsonl-contract.md) |
| Worker and automation | Local Worker lifecycle and command submission. | `worker`, `send-command`, `status`, `stop`, `wait-ready` | [Power Worker Daemon](#power-worker-daemon); [Power Worker Contract](../contracts/power-worker-contract.md). `status` is Worker lifecycle status; instrument status is `read-status`. |

Actual live availability remains determined by the exact Product scope for the
model, command, transport, backend, and required feature.

## Test

The default CLI tests are no-hardware tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\cli -q -p no:cacheprovider
```

Focused suites:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\cli\test_cli.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\cli\test_worker.py -q -p no:cacheprovider
```

Pytest uses the ignored repository-local `.tmp_pytest` directory by default,
so tests do not depend on access to the Windows system temporary directory.
Run pytest from the repository root. For an intentional per-run override, use
`--basetemp .tmp_tests/<purpose>`. Do not use `Local/` for pytest temporary
data or generated test artifacts.

### Scripted Validation

The following table lists the supported standalone validation entry points,
not a complete inventory of the `scripts/` directory. Run these scripts from
the repository root in PowerShell. Each validation entry point writes a
machine-readable `report.json` and a human-readable `summary.md` under
`.tmp_tests`.

| Script | Hardware use | Purpose |
| --- | --- | --- |
| `scripts\preflight-cli.ps1` | No hardware | Runs `smoke`, `deep`, or compatibility `full` model-aware CLI validation, parses every JSON result, and enforces `hardware_touched=false`. |
| `scripts\live-cli-check.ps1` | Plan-only or explicit live hardware | Runs `preflight-cli.ps1`, then generates the exact selected-suite plans before optional interactive live validation. Formal release acceptance may skip only the redundant external preflight for its subsequent `PlanOnly` check. Use this for candidate feature-validation records. |
| `scripts\release-acceptance.ps1` | No hardware | Validates clean committed HEAD with the existing `.venv`, runs the full suite once, builds one final versioned release, checks its package/install/entry-point/standalone artifacts and checksums, then runs all-model CLI smoke, representative deep preflight, and simulator `-PlanOnly`. |
| `scripts\batch-validation.ps1` | Selected by switches | Runs only the selected simulated or live validation tasks and writes one batch report. |

Run formal release acceptance from the repository root with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\release-acceptance.ps1
```

Each recorded command prints `[start]`, then `[passed]` or `[failed]`, with a
`duration=<seconds>s` value. Child-process stdout/stderr is still collected
after command completion and printed or written to the acceptance output; it is
not streamed line by line. See the root [README](../../README.md) for the
detailed release acceptance scope.

#### Build entry points

These are public build entry points; detailed usage is maintained in the root
[README](../../README.md):

- `scripts\build_cli_exe.ps1`
- `scripts\build_webui_exe.ps1`
- `scripts\build_release.ps1`

#### CI quality utilities

These scripts support CI quality checks and are not standalone validation
entries:

- `scripts/check_text_hygiene.py` checks tracked public text for UTF-8,
  BOM, replacement-character, and mojibake hygiene issues.
- `scripts/check_changed_whitespace.py` checks the GitHub Actions event range
  for whitespace errors. It depends on CI event SHA environment variables and
  is not a general local standalone command.

#### Internal helpers

These files are called by other scripts and are not general user entry points;
do not execute them directly:

- `scripts/_validation_helpers.ps1`
- `scripts/e36312a_trigger_validation.py`

The live wrapper uses the Product CLI and loads the Core-owned candidate inventory directly in memory. It creates no intermediate inventory, manifest, or capability files.

If the current Windows execution policy blocks `.ps1` files, use a
process-local bypass for the selected script:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\preflight-cli.ps1 -Target all -Suite smoke
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\live-cli-check.ps1 -Target keysight-e36312a -Connection USB -Resource "SIM::E36312A" -Suite readonly -PlanOnly
```

`preflight-cli.ps1` validates actual public CLI no-hardware paths and writes
timestamped aggregate and per-model reports under
`.tmp_tests\cli_preflight`. Use `smoke` to check identity, simulator mapping,
capabilities, representative read-only behavior, model-aware planning, and
model-specific topology or support policy for every Product-active model:

```powershell
.\scripts\preflight-cli.ps1 -Target all -Suite smoke
```

Output-control scope is owned by Core model metadata and is tested there:
E36312A and EDU36311A are `per_channel`, while E3646A is `global`. The CLI
capabilities smoke does not treat `output_control_scope` as a capabilities
payload field.

Use `deep` for capability-representative models. With `-Target all`, the
current representatives are `keysight-e36312a` for three-channel Protection,
Snapshot, Trigger List, and complete workflow coverage, and
`keysight-e3646a` for two-channel ASRL/RS-232 and global-output behavior.
`keysight-edu36311a` remains covered by all-model smoke without duplicating
E36312A deep workflows. Add another deep representative only when a new model
introduces a capability family or hardware structure not already represented:

```powershell
.\scripts\preflight-cli.ps1 -Target all -Suite deep
```

The default `full` suite retains the prior broad per-target preflight for
explicit validation and compatibility with existing wrapper workflows.
Smoke, deep, and full are all no-hardware paths.

Suite live validation uses an explicit target, connection, resource, and
suite. By default, every run, including `-PlanOnly`, first calls the broad
model-level `preflight-cli.ps1` and then generates the selected suite's exact
simulator, dry-run, lint, and expected-failure cases. Formal release acceptance
uses its internal skip switch only after all-model smoke and representative deep
preflight have passed; the selected-suite PlanOnly cases still run. `-PlanOnly`
stops there and does not open the supplied resource. Without `-PlanOnly`,
interactive Enter confirmation
is required before opening VISA. If stdin is redirected, live execution is
refused with a confirmation-required report.

Live LAN validation waits 500 ms between independent TCPIP/VXI-11 subprocess
sessions. The first live TCPIP subprocess does not wait. A command may be run
once more only when its first schema-2 failure proves that `open_resource`
failed before any SCPI or functional output artifact was produced. USB, ASRL,
preflight, simulator, dry-run, and PlanOnly flows do not use this delay or
recovery. Trigger validation helpers share the LAN session delay but are never
retried by the CLI-envelope recovery rule.

Each standard live TCPIP command stores its first result as an `attempt-1`
artifact and creates `attempt-2` only for that bounded recovery. The command
record points its normal artifact paths at the final attempt while retaining
`attempts`, `attempt_count`, `recovery_attempted`,
`recovered_after_open_failure`, `final_attempt`, first-error diagnostics, and
the configured settle delay. Recovery means only that the second CLI execution
succeeded; identity, output-state, error-queue, and cleanup assertions can
still fail the case. CSV, JSONL, snapshot, and other command-generated files
keep their functional names, and any first-attempt change to such a file blocks
automatic recovery.

`live-cli-check.ps1` is the maintained contributor validation harness, not the
same thing as declaring a connection opened for normal use. Its artifacts are
candidate evidence only: a passed validation run is scoped to the selected
model, connection, suite, and cases and does not automatically promote product
support. It does not prove every feature, every connection type, or every
model, and it does not mean USB validation covers LAN validation. See
[Contributing](../CONTRIBUTING.md) for the contributor workflow.

Wrapper targets are exact canonical physical `model_id` values; bare model
names are rejected. New shareable reports use string `schema_version: "2.0"`,
`kind: "powers-tool-live-validation"`, `vendor_id`, and `model_id`. Plan-only
reports record `planning_model_id`; live reports record `expected_model_id`.
The wrapper passes the canonical expected-model guard to identity-bearing and
model-aware commands that accept it. `verify` and `identify` validate the
manufacturer-plus-model identity detected by `*IDN?` against that guard;
`error` and `clear` remain raw diagnostic/status operations without a model
guard, and `list-resources` has no target-model override. The wrapper invokes
`powers-tool` and never treats a passing report as support promotion. Failed or
incomplete cleanup evidence is not accepted. Passing artifacts remain
candidate-only and cannot promote Product support automatically. Generic
examples use `POWERS_TOOL_RESOURCE` or `POWERS_TOOL_ASRL_RESOURCE`;
model-specific lab variables such as
`E36312A_USB_RESOURCE` remain explicit operator inputs.

The current `full` plans include dedicated bounded cases for these exact
Product scopes:

| Target and exact Product connection | Product-open commands with dedicated bounded cases |
| --- | --- |
| E36312A USB or TCPIP + system VISA | `output-on`, `log`, resource-backed `doctor`, `measure-all`, real `restore-from-snapshot`, `trigger-fire`, `trigger-pulse` |
| EDU36311A USB or TCPIP + system VISA | `output-on`, `log`, resource-backed `doctor` |
| E3646A ASRL + system VISA | `output-on`, resource-backed `doctor` |

These cases are deliberately bounded. Logging collects one all-channel
sample at 0.1 seconds into private CSV/JSONL files, validates the exact header,
channel inventory, telemetry fields, per-row empty error fields, and completed
summary, then writes only redacted shareable copies. Resource-backed `doctor`
must complete the resource-manager/backend check, open the selected resource,
identify the expected model, and emit no state-changing SCPI; offline `doctor`
is unchanged. E36312A `measure-all` requires exactly CH1-CH3 numeric voltage
and current results. Its two real restore paths separately prove settings with
outputs kept OFF and one bounded CH1 ON snapshot restored with
`--restore-output-state --confirm`; both paths retain the canonical snapshot
guards and require best-effort safe-off, final output-state, and error-queue
evidence even after failure.

The E36312A trigger evidence cases remain in the contributor Full suite.
`trigger-fire` uses a private snapshot/arm helper, invokes the standalone CLI
command to fire the armed BUS trigger, and restores all three channels
afterward. `trigger-pulse` pauses before any case-specific VISA or SCPI, then
asks the operator to connect rear Pin 1 as the signal and rear Pin 4 Common as
the digital signal reference, arm the oscilloscope or logic analyzer, and
press Enter. After the command restores Trigger/LIST and rear digital state,
the wrapper performs safe-off, output-state, and error-queue cleanup before
asking for an explicit `Yes` or `No` observation. This wiring follows the
[Keysight E36300 Series User's Guide](https://www.keysight.com/us/en/assets/9018-04576/user-manuals/9018-04576.pdf).
A `Yes` records only one observed
positive pulse; it does not validate pulse width, timing accuracy, or waveform
quality.

The complete Product-open command inventory remains the
[Product LIVE exact-scope matrix](../core/supported-models.md#product-live-exact-scope-matrix).
Only exact commands in that matrix are opened for normal LIVE use on those
connections. E3646A live validation remains restricted to ASRL /
RS-232; E3646A USB and LAN remain outside the current scope.
Sequence actions and Trigger Step/List sources are also exact feature-policy
requirements. Missing or pending feature entries remain closed in normal CLI
Product mode; a Product-open command does not imply that an unregistered action
or source is open. The CLI model list remains limited to Product-active models;
there are currently no candidate models and no new model is enabled by this
framework.

```powershell
.\scripts\live-cli-check.ps1 -Target keysight-e36312a -Connection USB -Resource $env:E36312A_USB_RESOURCE -Suite full
.\scripts\live-cli-check.ps1 -Target keysight-e36312a -Connection LAN -Resource $env:E36312A_LAN_RESOURCE -Suite full
.\scripts\live-cli-check.ps1 -Target keysight-edu36311a -Connection USB -Resource $env:EDU36311A_USB_RESOURCE -Suite full
.\scripts\live-cli-check.ps1 -Target keysight-edu36311a -Connection LAN -Resource $env:EDU36311A_LAN_RESOURCE -Suite full
.\scripts\live-cli-check.ps1 -Target keysight-e3646a -Connection ASRL -Resource $env:E3646A_ASRL_RESOURCE -Suite full
.\scripts\live-cli-check.ps1 -Target keysight-e36312a -Connection USB -Resource $env:E36312A_USB_RESOURCE -Suite output -PlanOnly
```

Supported suites are model-aware:

| Target | `full` suite composition |
| --- | --- |
| `keysight-e36312a` | `readonly`, `output`, `protection`, `snapshot`, `trigger-list`, `software-sequence` |
| `keysight-edu36311a` | `readonly`, `output`, `protection`, `software-sequence` |
| `keysight-e3646a` | `readonly`, `output`, `software-sequence` |

For each active model, `-Suite full` is an evidence grouping.

A passing full-suite record applies only to the selected model and connection
and is evidence for maintainer review. Product support changes only through an
explicit evidence-backed policy decision; the record itself does not open any
command or feature.

Disabled,
unimplemented, out-of-scope, or factory-only features are not implied by the
pass.

A passed suite means the target model matched, the selected connection type
was used, the selected suite/cases passed, and artifacts were recorded under
`.tmp_tests`. It does not imply untested features, skipped suites, other
models, other connection types, disabled features, out-of-scope factory
features, or every instrument function are validated. It does not validate
the entire model. Explicit unsupported suite requests fail before live
execution instead of silently skipping everything.

| Model | USB | LAN | ASRL / RS-232 |
| --- | --- | --- | --- |
| E36312A | accepted exact commands | accepted exact commands | N/A |
| EDU36311A | accepted exact commands | accepted exact commands | N/A |
| E3646A | not current scope | not current scope | accepted exact commands |

E3646A suite validation is ASRL/RS-232 focused. It uses CH1/CH2, records that
`OUTP ON/OFF` is global, and treats `ramp-list` and `sequence` as software
workflows only, not native LIST. E3646A protection, trigger/native LIST,
snapshot/restore, completion-pulse, and unsupported sequence steps remain
disabled in live, simulate, and dry-run paths.

EDU36311A `software-sequence` validation covers only project-supported
software `ramp-list` and sequence read-only/output workflows. It does not
enable trigger/native LIST, snapshot, or restore-from-snapshot.

CLI preflight uses only `--dry-run` and `--simulate`; it does not scan for or
open VISA resources. It uses deterministic SIM resources and supports one
canonical model or all applicable models for the selected preflight suite:

```powershell
.\scripts\preflight-cli.ps1 -Target all -Suite smoke
.\scripts\preflight-cli.ps1 -Target all -Suite deep
.\scripts\preflight-cli.ps1 -Target keysight-e3646a -Suite full
```

Live validation requires an explicit `-Resource`. The script does not scan for
resources, guess a resource, or read an environment default. Discover a live
resource separately, copy the exact value, then pass it explicitly:

```powershell
.\.venv\Scripts\powers-tool.exe list-resources --live-only --json
```

Use `list-resources --verify --json` instead when you need to diagnose stale
VISA cache entries. After choosing the intended live resource, run the
maintained live script. It pauses for confirmation before opening VISA:

```powershell
$env:E36312A_USB_RESOURCE = "USB0::...::INSTR"
$env:EDU36311A_USB_RESOURCE = "USB0::...::INSTR"

.\scripts\live-cli-check.ps1 -Target keysight-e36312a -Connection USB -Resource $env:E36312A_USB_RESOURCE -Suite full
.\scripts\live-cli-check.ps1 -Target keysight-edu36311a -Connection USB -Resource $env:EDU36311A_USB_RESOURCE -Suite full
```

Suite success is a bounded validation result, not a complete
feature-validation suite result. For enabling or recording a model-specific
feature, use the corresponding `live-cli-check.ps1` suite/case result.

Batch validation runs only the checks selected by switches. Simulated
resources are useful for checking the batch/report workflow without hardware:

```powershell
.\scripts\batch-validation.ps1 `
  -RunE36312AOutput `
  -E36312AUsbResource "USB0::SIM::E36312A::INSTR" `
  -RunEDUReadOnly `
  -EDU36311AUsbResource "USB0::SIM::EDU36311A::INSTR"
```

For real hardware, replace the simulated resources with explicit VISA
resources. `-RunE36312AOutput` is state-changing; `-RunEDUReadOnly` is
read-only. The current `-RunIntegrationPytest` batch switch records a skipped
task only, so run hardware pytest directly when required.

### Optional Hardware Pytest

The live smoke script is the normal hardware OK gate for operator acceptance.
Run hardware pytest only when you need deeper repeatable hardware regression,
when a changed feature has matching hardware tests, or when validating SCPI,
trigger, protection-setting, or intentional protection-trip behavior beyond
the smoke script.

Hardware integration tests are excluded from normal use unless an explicit
resource is passed. If deeper hardware pytest is needed, run the read-only
hardware suite first:

```powershell
uv run python -m pytest tests\integration -q -m hardware --resource "$env:E36312A_USB_RESOURCE" --expected-model E36312A
```

Output-affecting hardware pytest additionally requires `--run-output`:

```powershell
uv run python -m pytest tests\integration -q -m hardware_output --resource "$env:E36312A_USB_RESOURCE" --expected-model E36312A --run-output
```

Add `--backend "@ivi"` when needed. Before any output-affecting run, confirm
the expected instrument, disconnect unknown DUTs, and verify the requested
voltage/current are safe.

## Command Status

E36312A and EDU36311A have model-specific driver foundations selected from
valid `*IDN?` responses. Their channel-list SCPI is covered by no-hardware
tests. Simulated CLI measurement supports channels 1, 2, and 3 for these
models.

### Planning Identities And Live Expected-Model Guards

Output-family commands, `ramp-list`, `sequence`, `protection-set`,
`clear-protection`, and trigger workflows use strict model resolution in
`--dry-run` and `--simulate` mode. In these no-hardware planning paths,
`--model` supplies a canonical physical planning ID such as
`keysight-e36312a`. Supported dry-run commands also expose
`--profile generic-scpi` for separate nonphysical planning. The fields are
mutually exclusive. Simulator mode accepts only a physical planning model or
a known deterministic simulator resource such as
`USB0::SIM::E36312A::INSTR`.
Trigger no-hardware paths are E36312A-only and require `--model keysight-e36312a` or a
known deterministic E36312A SIM resource. The CLI does not infer a model from
arbitrary fake, live-looking, or alias-only resource strings.

Examples:

```powershell
uv run powers-tool set --dry-run --model keysight-e3646a --channel 1 --voltage 1 --current 0.05
uv run powers-tool readback --simulate --resource USB0::SIM::E36312A::INSTR --channel all
uv run powers-tool trigger-step --dry-run --model keysight-e36312a --channel 1 --source bus --fire
```

This is rejected because a fake resource is only a placeholder and must not
imply a model:

```powershell
uv run powers-tool trigger-step --dry-run --resource USB0::FAKE::E36312A::INSTR --channel 1 --source bus --fire
```

Deterministic SIM resources are accepted because they map to known simulator
IDN/model data.

In live mode, `--model` is an expected-model guard. The CLI opens the explicit
resource, queries `*IDN?`, resolves manufacturer plus model, and requires the
canonical detected `model_id` to match before command-specific SCPI. The
selected model never overrides the IDN-detected driver.

Unsupported model, command, and mode failures are intentional feature-lock
behavior. `--model` is not a feature unlock: in dry-run/simulate mode it only
selects a physical planning identity, and in live mode it only checks that the
connected canonical identity is expected. `generic-scpi` is available only
through dry-run `--profile` where the existing support matrix permits it.

Live guard example:

```powershell
uv run powers-tool set --model keysight-e36312a --resource "$env:POWER_USB_RESOURCE" --channel 1 --voltage 1 --current 0.05
```

This requires the connected `*IDN?` model to be `E36312A`.

Accepted physical planning IDs are `keysight-e36312a`,
`keysight-edu36311a`, and `keysight-e3646a`. In `--simulate` mode, `--model`
can derive the matching deterministic simulator resource. The separate
`generic-scpi` profile is dry-run-only and is not a live expected model. If
both `--model` and a SIM resource are provided, their models must match.
Unsupported models, including EDU36311A, do not expose trigger
dry-run or simulator behavior.

No-hardware plans distinguish `planning_model_id` from
`planning_profile_id`. Channel validation and `--channel all` expansion use
the resolved planning identity: E3646A expands `all` to CH1 and CH2 and
rejects CH3; E36312A and EDU36311A expand to CH1, CH2, and CH3;
`generic-scpi` conservatively allows CH1 only.

Trigger/native LIST workflows are E36312A-only. EDU36311A supports validated
read-only, output, and protection workflows, but trigger/native LIST,
`snapshot`, and `restore-from-snapshot` are disabled in live, simulate, and
dry-run until separately implemented and hardware validated. E3646A supports
validated RS-232 read-only/output workflows plus software `ramp-list` and
step-limited software `sequence`; those workflows are not native LIST support
and reject unsupported protection, trigger, snapshot, restore, native LIST,
and completion-pulse sequence steps. E36103B and E36232A are not active
supported models and are rejected as planning models and live expected-model
guards. If live `*IDN?` reports either model, model-aware commands reject the
instrument instead of falling back to `GenericScpiPowerSupply`; `verify` and
`list-resources --live-only` may still report the raw IDN as diagnostics.

Real CLI measurement keeps generic instruments on channel 1. E36312A and
EDU36311A channels 2 and 3 use IDN-selected channel-list measurement queries.
Real CLI `set` is supported for E36312A and EDU36311A channels 1, 2, and 3,
and for live-validated E3646A RS-232 / ASRL channels 1 and 2. It accepts
`--voltage`, `--current`, or both. Omitted setpoints are left unchanged; when
both are supplied, it writes the current limit before voltage. It does not
enable output.

For all active models, `--voltage` is the output voltage setpoint and
`--current` is the output current limit/current setting. Core publishes
official programming-range metadata from the model manuals: E36312A and
EDU36311A use fixed channel ranges, while E3646A has LOW/P8V and HIGH/P20V
range-dependent voltage/current-limit ranges. This metadata does not add a new
CLI range selector, does not silently round or truncate setpoints, and does
not implement hard decimal-place rejection.

Product LIVE support is command-exact, not feature-family-wide. See the
[Product LIVE exact-scope matrix](../core/supported-models.md#product-live-exact-scope-matrix).
The reviewed `output-on`, `measure-all`, `trigger-pulse`, `trigger-fire`, `log`,
resource-backed `doctor`, and `restore-from-snapshot` scopes are Product-open
only for the exact model/transport/system-VISA combinations in that matrix.
Other combinations remain fail-closed. Accepted commands
such as `set`, `output-off`, `safe-off`, `apply`, `ramp`, and model-appropriate
read/protection/trigger commands still require an exact accepted
model/transport/backend scope.

Normal CLI operation always uses the product live-support policy. Pending
transport/backend evidence is not normal product support, and no public force
or validation bypass is available. The Core has a contributor-validation mode
for controlled evidence work, but its invocation is intentionally outside the
normal CLI help, examples, and operator workflow documentation. That mode does
not bypass IDN selection, expected-model checks, request validation, safety
limits, confirmations, or model feature locks.

`list-resources`, `verify`, `clear`, `error`, `measure`, `identify`,
`protection-status`, `protection-set`, `clear-protection`, and `snapshot` now
execute through shared core runners. The CLI still owns argparse handling,
human text output, JSON success/error envelopes, `--save-json`, and exit-code
mapping.

`snapshot` produces a schema-2 `powers-tool-snapshot` document with raw
manufacturer/model/serial/firmware under `reported_identity` and canonical
`vendor_id`/`model_id` under `resolved_identity`. `restore-from-snapshot`
accepts only that versioned document; legacy, unversioned, and arbitrary
CLI-envelope documents are rejected. `snapshot --snapshot-json PATH` writes
the raw persisted snapshot, while `--json --save-json PATH` writes the full
CLI schema-2 envelope. The paths must differ when both options are used. No
model identity is recovered from a bare reported model string.

Restore validates all restore-relevant persisted fields without coercion.
Channels are positive integers, output and OCP states are JSON booleans, and
setpoints are finite numbers. A value such as `"false"` is rejected rather
than treated as enabled or disabled. `outputs`, `readback`, and
`protection_settings` must be non-empty and contain exactly the same channels;
a protection record remains required when all of its optional protection
values are null. Incomplete documents are rejected rather than partially
restored. CLI `--channel 1` is parsed to an integer before Core validation,
while raw Core/JSON numeric strings are rejected; exact `--channel all`
remains available only for commands that support all-channel selection.

`snapshot --compare PATH` compares the current E36312A snapshot with a
schema-2 snapshot document (directly or as saved CLI envelope data). It ignores `resource` and
`read_count`, uses default tolerances of 0.001 V/A for programmed setpoints,
0.05 V measured voltage, and 0.01 A measured current, and exits `3` when
differences are found.

`ramp` is a setpoint-only command for E36312A, E3646A, and EDU36311A: it sets
current limit first, then steps voltage from `--start-voltage` to the exact
`--stop-voltage`. It does not turn output on or off and always uses software
setpoint steps. E3646A and EDU36311A real `ramp` do not support
completion-pulse options. `set`, `apply`, `output-on`, `output-off`, and
`ramp` accept `--settle-ms` and `--verify-after-write`; verification failures
return JSON error code `verification_failed` and exit `3`.

`ramp-list` runs 1 to 10 ordered software-setpoint ramp segments through one
VISA session. It validates the complete versioned JSON document and all
generated setpoints before the first hardware write. It does not enable or
disable output, use native LIST, or perform automatic safe-off on failure.

Ramp `--completion-pulse-timing segment` emits once after each complete Ramp
iteration. `--completion-pulse-timing step` emits after every voltage write,
and `--completion-pulse-timing loop` emits once after all successful
iterations. Every-step timing accepts `--delay-ms 0`.
Rear pulse pins are not output channels. Pulse workflows are E36312A-only, and
`*TRG` may affect other already armed BUS-triggered behavior.

Ramp and inline Ramp List accept `--enable-output`. Ramp writes current and
the first voltage before enabling and verifying output. Ramp List enables each
channel only on its first segment. Normal completion leaves those outputs ON;
omitting the option preserves the prior output state.

`ramp`, `ramp-list`, and `sequence` accept `--loop-count N`, where N is the
total execution count and a strict integer from 1 through 10,000. An explicit
CLI value overrides a document value; otherwise the document value is used,
then 1. Ramp List v2/v3 and Sequence v1 imply 1.

Ramp List version 2 remains accepted with `enable_output: false` and one
iteration. Version 3 requires `enable_output` and implies one iteration.
Version 4 requires exact `enable_output` and `loop_count` fields and may
contain a global `completion_pulse` object. Version 1, malformed values,
unknown fields, and future versions are rejected without fallback. Inline
segments always build v4 and explicitly store `loop_count`, including 1.

Core limits Ramp, Ramp List, and Sequence to 1,000,000 logical execution
units. The CLI prints an execution summary before text-mode execution and
warns above 100,000 units; JSON results use the existing warnings field.
Long runs may retain only the first 100 and last 100 result details while
preserving full aggregate counters and truncation metadata.
`--file` takes `enable_output` only from the document and cannot be combined
with the CLI flag. Inline usage accepts
`--completion-pulse-timing`, `--completion-pulse-pins`, and
`--completion-pulse-polarity`; with `--file`, the document is authoritative
and CLI pulse overrides are rejected.

```powershell
$env:POWERS_TOOL_RESOURCE = "USB0::...::INSTR"
uv run powers-tool ramp-list --lint --json --file example.ramp-list.json
uv run powers-tool ramp-list --dry-run --json --model keysight-e36312a --file example.ramp-list.json
uv run powers-tool ramp-list --json --resource "$env:POWERS_TOOL_RESOURCE" --segment 1 0.1 0 1 0.1 100 0 --segment 2 0.05 0 2 0.2 50 500
```

## Power Worker Daemon

The Powers Tool Worker is a local background service that listens on
localhost and accepts HTTP commands to control Keysight instruments
asynchronously.

For full details on the REST API, JSONL lifecycle events, and job result
artifacts, see the [Power Worker Contract](../contracts/power-worker-contract.md).
For the orchestrator/agent handoff flow, including ready-event discovery and
result artifact polling, see the
[Power Worker Orchestrator Guide](../contracts/power-orchestrator-workflows.md).

Start the worker in simulation mode on a dynamic port:

```powershell
uv run powers-tool worker --id power_1 --mode simulate --control-port 0
```

Worker requests require top-level `context`. Mode and identity use
`context.mode`, `context.planning_model_id`, `context.expected_model_id`, and
`context.planning_profile_id`; these fields are rejected in `arguments`.
Their valid combinations follow the resolved Worker mode, and identity fields
are rejected in settings. A deterministic SIM resource must match the explicit
physical planning model; Worker provides no identity default. The
`send-command` client requires `--context-json` with the same context object.

`POST /stop` is cooperative: the handler only sets stop state and wakes the
runner. The Worker emits structured `power_cleanup` JSONL events and does not
emit its final `summary` or stop the HTTP server until runner cleanup finishes.

`POST /cancel` is the fixed job-specific cancellation endpoint. It requires
schema 2 and the exact active `worker_job_id`; missing, stale, or mismatched
identity fails closed. It safely cancels Ramp, Ramp List, or Sequence without
shutting down the Worker. `/stop` keeps its existing whole-Worker shutdown
meaning. Direct CLI Ctrl+C for those three workflows requests the same
cooperative cleanup; it cannot force-interrupt blocking VISA I/O.

When started, it outputs a `ready` event on stdout containing the dynamically
assigned control endpoints.

Run the simulator-only orchestrator smoke example:

```powershell
.\examples\worker_orchestrator_smoke.ps1
```

## Examples

### Resource Discovery And Live Resource Setup

List only VISA resources that can be opened and queried with `*IDN?`:

```powershell
uv run powers-tool list-resources --live-only
```

Use this for normal live operation. Text output includes each resource's raw
IDN response so the instrument model is visible. Add `--log-scpi` to show the
verification query and response for each live check.

List VISA resource strings reported by the selected backend without opening
them:

```powershell
uv run powers-tool list-resources
```

This is passive discovery only: a resource string can appear here even when the
instrument is not currently reachable.

For live USB examples below, set the VISA resource once per PowerShell session:

```powershell
$env:POWERS_TOOL_RESOURCE = "USB0::...::INSTR"
```

### Generic USB Live Examples

Verify that one resource can be opened and queried with `*IDN?`:

```powershell
uv run powers-tool verify --resource "$env:POWERS_TOOL_RESOURCE"
uv run powers-tool verify --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
```

Clear instrument status and the error queue with `*CLS`:

```powershell
uv run powers-tool clear --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
```

Read the instrument error queue without changing output state:

```powershell
uv run powers-tool error --resource "$env:POWERS_TOOL_RESOURCE" --max-reads 20 --log-scpi
```

### E3646A RS-232 / ASRL Examples

E3646A product LIVE support is ASRL/RS-232 + system VISA only. Its exact
product-open model-aware commands are `measure`, `readback`, `read-status`,
`output-state`, `capabilities`, `set`, `apply`, `output-off`,
`safe-off`, `cycle-output`, `smoke-output`, `ramp`, `ramp-list`, and
`sequence`, `output-on`, and resource-backed `doctor`. `identify` and `verify`
are diagnostics only. Protection, trigger, snapshot/restore, completion pulses,
and native LIST are not product-open.
`ramp-list` is software setpoint stepping, and `sequence` is a step-limited
software workflow for validated output/read-only steps; neither is native LIST.

E3646A uses `INST:NSEL` channel preselection for setpoint writes and readbacks.
`OUTP ON/OFF` is a global output enable/disable on this model, so accepted
commands such as `output-off`, `safe-off`, `cycle-output`, and
`smoke-output` can affect the instrument output state globally even when a
command accepts a channel.
E3646A `sequence` accepts only validated read-only/output steps; protection,
trigger, snapshot, restore, native LIST, and completion-pulse step types are
rejected by the current feature-lock policy.

Set the ASRL resource once per PowerShell session:

```powershell
$env:POWERS_TOOL_ASRL_RESOURCE = "ASRL1::INSTR"
```

For repeated examples, keep common ASRL settings in variables:

```powershell
$Base = @("--resource", "$env:POWERS_TOOL_ASRL_RESOURCE", "--serial-read-termination", "CRLF", "--serial-write-termination", "LF")
$Remote = @("--serial-remote", "--serial-local-on-close")
```

Plain resource discovery does not need serial options:

```powershell
uv run powers-tool list-resources
```

If Connection Expert already has the ASRL resource configured and verified,
you can let VISA use those settings:

```powershell
uv run powers-tool verify --resource "$env:POWERS_TOOL_ASRL_RESOURCE"
```

Serial settings are explicit only. If omitted, the CLI does not overwrite
VISA backend, Keysight IO Libraries Suite, or Connection Expert serial
settings. If supplied, only those supplied fields are applied to ASRL
resources. The E3646A factory example is 9600 baud, 8 data bits, none parity,
2 stop bits, and DTR/DSR handshake, but the actual instrument front-panel
settings may differ:

```powershell
uv run powers-tool verify --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --serial-baud-rate 9600 --serial-data-bits 8 --serial-parity none --serial-stop-bits 2 --serial-flow-control dtr_dsr --serial-remote --serial-local-on-close
```

`--serial-remote` sends `SYST:REM` after opening the ASRL resource.
`--serial-local-on-close` best-effort sends `SYST:LOC` during cleanup. These
commands affect the instrument remote/local state and are never sent unless
explicitly requested.

Read/status examples:

```powershell
uv run powers-tool identify --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --serial-remote --serial-local-on-close
uv run powers-tool readback --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
uv run powers-tool measure --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --channel 2 --serial-remote --serial-local-on-close
uv run powers-tool output-state --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
```

Validated output examples:

```powershell
uv run powers-tool set @Base @Remote --channel 1 --voltage 1 --current 0.05 --json --log-scpi
uv run powers-tool apply @Base @Remote --channel 1 --voltage 1 --current 0.05 --no-output --json --log-scpi
uv run powers-tool output-off @Base @Remote --channel 1 --json --log-scpi
uv run powers-tool safe-off @Base @Remote --channel 1 --json --log-scpi
uv run powers-tool ramp @Base @Remote --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.25 --current 0.05 --delay-ms 100 --json --log-scpi
```

`cycle-output`, `smoke-output`, and `apply` without `--no-output`
require `--confirm` when the selected setpoints exceed the configured
confirmation threshold. `set`, `output-off`, `safe-off`, `ramp`, and
`ramp-list` do not require `--confirm`.

For serial terminations, prefer aliases in PowerShell:

```powershell
uv run powers-tool verify --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --serial-read-termination CRLF --serial-write-termination LF
```

Supported aliases are `CR`, `LF`, `CRLF`, and `NONE`/`none`. `NONE` means do
not set that termination option. Omitted or empty termination fields also mean
do not override the VISA setting. Custom raw strings are still accepted, but
PowerShell may pass values such as `\r` as a literal backslash plus `r`; use
the aliases when you need actual control characters.

### Read-Only Command Examples

Measure voltage and current:

```powershell
uv run powers-tool measure --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --log-scpi
uv run powers-tool measure --resource "$env:POWERS_TOOL_RESOURCE" --channel 2 --log-scpi
```

Preview all-channel measurement without hardware, and read product-open live
status:

```powershell
uv run powers-tool measure-all --simulate --json --resource USB0::SIM::E36312A::INSTR
uv run powers-tool read-status --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
```

Run a full read-only validation pass on E36312A or EDU36311A:

```powershell
uv run powers-tool validate-readonly --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi --save-json logs\validate-readonly.json
```

Read programmed E36312A setpoints and protection state:

```powershell
uv run powers-tool readback --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
uv run powers-tool protection-status --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
```

For E36312A and EDU36311A, `protection-status` reads OVP/OCP trip flags per
channel. The existing aggregate flags remain available and are calculated as
the OR of the selected channel results.

### Snapshot And Restore Examples

Capture a raw E36312A snapshot that restore can consume, then compare it:

```powershell
uv run powers-tool identify --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
uv run powers-tool snapshot --resource "$env:POWERS_TOOL_RESOURCE" --snapshot-json logs\before.json --log-scpi
uv run powers-tool snapshot --json --resource "$env:POWERS_TOOL_RESOURCE" --compare logs\e36312a-baseline.json
uv run powers-tool snapshot-diff --summary --json --before logs\before.json --after logs\after.json
```

Preview a restore plan and save the plan data without opening VISA:

```powershell
uv run powers-tool restore-from-snapshot --dry-run --json --snapshot logs\before.json --resource USB0::SIM::E36312A::INSTR --channel all --plan-json logs\restore-plan.json
```

### Protection And Trigger Examples

Preview or confirm E36312A protection actions:

```powershell
uv run powers-tool clear-protection --dry-run --json --model keysight-e36312a --all
uv run powers-tool clear-protection --json --resource "$env:POWERS_TOOL_RESOURCE" --all --confirm --log-scpi
uv run powers-tool protection-set --dry-run --json --model keysight-e36312a --channel all --ovp-voltage 5 --ocp on
uv run powers-tool protection-set --dry-run --json --model keysight-e36312a --channel 1 --ocp-delay 0.5 --ocp-delay-trigger setting-change
uv run powers-tool protection-set --json --resource "$env:POWERS_TOOL_RESOURCE" --channel all --ovp-voltage 5 --ocp on --confirm --log-scpi
```

Configure an E36312A rear digital pin as trigger output, arm one output channel
with a no-change STEP trigger sequence, and emit `*TRG`:

```powershell
uv run powers-tool trigger-pulse --dry-run --json --model keysight-e36312a --pin 1 --channel 1 --polarity positive
```

Use `--dry-run --model keysight-e36312a` or a deterministic E36312A SIM resource to
preview trigger SCPI without opening VISA. Trigger dry-run and simulator
behavior is E36312A-only; unsupported models do not expose trigger
no-hardware behavior. The final `*TRG` may also trigger any already armed
BUS-triggered instrument behavior. `trigger-pulse` is Product-open only for
E36312A USB/TCPIP + system VISA in the documented exact scope. Live trigger behavior
for accepted commands remains IDN-driven; a live `--model` only requires the
connected IDN model to match and never overrides connected hardware.

Native E36312A trigger/LIST commands:

```powershell
uv run powers-tool trigger-status --json --resource "$env:POWERS_TOOL_RESOURCE" --channel all
uv run powers-tool trigger-step --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --source bus --fire --wait-complete
uv run powers-tool trigger-list --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --voltage-list 0,1 --current-list 0.05 --dwell-list 0.01 --completion-pulse-pins 1 --fire --wait-complete
uv run powers-tool trigger-list --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --voltage-list 0,1 --current-list 0.05 --dwell-list 0.01 --bost-list on,off --eost-list off,on --trigger-output-pins 1 --source immediate --wait-complete
uv run powers-tool trigger-fire --dry-run --json --model keysight-e36312a --channel 1 --wait-complete
uv run powers-tool trigger-abort --json --resource "$env:POWERS_TOOL_RESOURCE" --channel all
```

For native BUS triggers, `trigger-step` and `trigger-list` only arm by default;
add `--fire` to send `*TRG` in the same command. BUS `--wait-complete` requires
`--fire`. Immediate source starts when `INIT` is sent and rejects `--fire`.
Arm-only LIST requires `--leave-trigger-configured`; a LIST that starts without
`--wait-complete` also requires `--leave-trigger-configured`, otherwise restore
would abort it. Trigger Step keeps its existing non-wait behavior. For
`trigger-fire`, `--channel N` is required only with `--wait-complete`; it
selects the output channel to abort if the instrument-wide completion wait
times out or is interrupted. It does not limit the scope of `*TRG` or the
completion wait. Both `trigger-fire` and `trigger-pulse` remain closed for any
other model, transport, or backend. Validation coverage does not promote
support automatically.
Canonical Trigger LIST files and flags accept per-step `bost_list` and
`eost_list` plus `trigger_output_pins` and `trigger_output_polarity`. Enabled
pulses require explicit output pins. Legacy `--completion-pulse-pins` remains
a final-step EOST pulse and cannot be mixed with canonical fields. A completed
wait restores the pre-run Trigger settings and LIST table unless
`--leave-trigger-configured` is selected.

### Output-Affecting Examples

Set low E36312A, E3646A, or EDU36311A setpoints without enabling output:

```powershell
uv run powers-tool set --model keysight-e36312a --resource "$env:POWER_USB_RESOURCE" --channel 1 --voltage 1 --current 0.05
uv run powers-tool set --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --voltage 1 --current 0.05 --log-scpi
uv run powers-tool set --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --voltage 1 --log-scpi
```

The first example uses `--model keysight-e36312a` as a live expected-model guard: it
requires the connected `*IDN?` model to be E36312A before any setup/write SCPI.

Real `set` first confirms the selected resource is an E36312A, E3646A, or
EDU36311A with `*IDN?`, then writes only the requested setpoint fields. E3646A
uses channels 1 and 2 with `INST:NSEL` preselection; E36312A and EDU36311A use
channels 1, 2, and 3.

Preview `output-on` without real hardware:

```powershell
uv run powers-tool output-on --dry-run --json --model keysight-e36312a --channel 1
uv run powers-tool output-on --simulate --json --resource USB0::SIM::E36312A::INSTR --channel all
```

`output-on` is Product-open only for E36312A and EDU36311A USB/TCPIP + system
VISA and E3646A ASRL + system VISA. Other scopes fail closed. The full suite
uses bounded 1 V / 0.05 A setpoints, confirms actual ON/OFF readback, and
requires final safe-off/error-queue cleanup. E3646A uses one global output
switch case after programming both channels; it is not tested as independent
per-channel output relays.

Read back and cycle output state:

```powershell
uv run powers-tool output-state --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --log-scpi
uv run powers-tool cycle-output --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --duration-ms 500 --confirm --log-scpi
uv run powers-tool cycle-output --json --resource "$env:POWERS_TOOL_RESOURCE" --channel all --duration-ms 500 --confirm --log-scpi
```

For `cycle-output --channel all`, the CLI enables channels 1, 2, and 3 in
order, waits once for `--duration-ms`, then disables channels 1, 2, and 3 in
order.

Apply low setpoints and enable output:

```powershell
uv run powers-tool apply --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --voltage 1 --current 0.05 --confirm --log-scpi
uv run powers-tool apply --json --resource "$env:POWERS_TOOL_RESOURCE" --channel all --voltage 1 --current 0.05 --confirm --log-scpi
uv run powers-tool apply --json --resource "$env:POWERS_TOOL_RESOURCE" --channel all --voltage 1 --current 0.05 --no-output --log-scpi
```

Add an explicit safety config to apply local global limits to output plans:

```toml
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2, 3]

[[resources]]
alias = "sim-e36312a"
resource = "USB0::SIM::E36312A::INSTR"
max_voltage = 3.3
max_current = 0.1
allowed_channels = [1]
```

Resource-specific fields override global `[safety]` fields one by one. A raw
`--resource` that matches a `[[resources]].resource` entry also receives that
entry's resource-specific limits; otherwise the global `[safety]` limits apply.

### Ramp And Sequence Examples

Ramp voltage setpoints without changing output state:

```powershell
uv run powers-tool ramp --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.25 --current 0.05 --delay-ms 100 --verify-after-write --settle-ms 200 --log-scpi
uv run powers-tool ramp --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.5 --current 0.05 --loop-count 2 --completion-pulse-timing loop --completion-pulse-pins 1 --log-scpi
```

Validate a sequence file or preview deterministic write SCPI without opening
VISA:

```powershell
uv run powers-tool sequence --lint --json --resource "USB0::SIM::E36312A::INSTR" --file examples\sequence-readonly.yaml
uv run powers-tool sequence --dry-run --json --resource "USB0::SIM::E36312A::INSTR" --file examples\sequence-readonly.yaml
uv run powers-tool sequence --dry-run --json --model keysight-e3646a --file examples\sequence-readonly.yaml
uv run powers-tool sequence --dry-run --json --model keysight-e36312a --file examples\sequence-readonly.yaml --loop-count 2
```

Sequence YAML files are formally supported through the core package's PyYAML
runtime dependency. A small built-in parser remains as a fallback for minimal
environments.

Sequence documents also accept `{"action":"trigger-pulse","channel":1,
"pins":[1],"polarity":"positive","leave_trigger_configured":false}`. The
default restores trigger and rear-pin configuration after the pulse.
`leave_trigger_configured` controls only that restore; it does not keep the
pulse trigger armed, and enabling it may affect later steps or other BUS triggers.

Ramp List examples:

```powershell
uv run powers-tool ramp-list --lint --json --file examples\ramp-list.json
uv run powers-tool ramp-list --dry-run --json --model keysight-e36312a --file examples\ramp-list.json
uv run powers-tool ramp-list --dry-run --json --model keysight-e3646a --file examples\ramp-list.json --loop-count 2
uv run powers-tool ramp-list --json --resource "$env:POWERS_TOOL_RESOURCE" --segment 1 0.1 0 1 0.1 100 0 --segment 2 0.05 0 2 0.2 50 500
```

### Simulator Examples

Clear instrument status and the error queue on a simulated resource:

```powershell
uv run powers-tool clear --dry-run --json --resource "USB0::SIM::E36312A::INSTR"
```

Measure voltage and current on a simulated resource:

```powershell
uv run powers-tool measure --simulate --json --resource "USB0::SIM::E36312A::INSTR" --channel 2
```

Capture a raw snapshot on a simulated resource with redacted resource details:

```powershell
uv run powers-tool snapshot --simulate --redact-resource --resource "USB0::SIM::E36312A::INSTR" --snapshot-json logs\before.json
```

Preview output-affecting commands with no hardware writes:

```powershell
uv run powers-tool set --dry-run --json --resource "USB0::SIM::E36312A::INSTR" --channel 1 --voltage 1 --current 0.05
uv run powers-tool output-on --dry-run --json --model keysight-e3646a --channel all
```

Run offline diagnostics, capabilities, and safety inspect checks:

```powershell
uv run powers-tool doctor --simulate --json
uv run powers-tool capabilities --simulate --json --resource "USB0::SIM::EDU36311A::INSTR" --command protection-set
uv run powers-tool safety inspect --json --explain --safety-config examples\safety-config.toml --resource-alias sim-e36312a --channel 1
```

The early standalone examples provide the same passive discovery and identity
query behavior:

```powershell
.\.venv\Scripts\python.exe examples\01_list_resources.py
.\.venv\Scripts\python.exe examples\02_identify.py --resource "$env:POWERS_TOOL_RESOURCE"
```

Add `--json` to supported CLI commands for the stable machine-readable v1
contract. Diagnostic logs such as `--log-scpi` remain on stderr so JSON stdout
stays parseable. Every JSON success and error envelope includes
`metadata.duration_ms`.

## Safety Defaults

- Output-affecting behavior must be explicit.
- Real product execution is limited to the exact commands and connections in
  the [Product LIVE exact-scope matrix](../core/supported-models.md#product-live-exact-scope-matrix).
  Feature-family, dry-run, simulator, or parser support does not widen it.
- The documented `output-on`, `measure-all`, `trigger-pulse`, `trigger-fire`,
  `log`, resource-backed `doctor`, and `restore-from-snapshot` commands are
  Product-open only in their documented exact scopes. Wrapper validation is
  not a promotion mechanism or normal-use bypass.
- Real `clear`, `error`, and `measure` are safe I/O commands: `clear` sends
  `*CLS` and clears status/error state, while `error` and `measure` only query.
- `--safety-config` is explicit only and applies local plan validation limits;
  it does not enable real hardware output.
- E36312A and EDU36311A setpoints are also bounded by verified official
  independent-channel DC output ratings. Safety config may only lower them.
- Real VISA resources must not be hard-coded in committed files.
- Hardware tests must require a user-provided resource.
- Examples that enable output must set current limit before voltage and turn
  output off in cleanup.

## Status

Active package. Live E36312A validation covers read-only CLI flows,
output-safe setpoint flows, worker dry-run/read-only behavior, and native
trigger-list flows documented in the hardware test guide.
