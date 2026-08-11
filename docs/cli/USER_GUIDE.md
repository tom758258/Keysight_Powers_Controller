# Powers Tool CLI User Guide

This guide is for operators who receive the built CLI executable or an
already-installed `powers-tool` command to control supported DC power
supplies. The framework is vendor-neutral, while the currently supported
hardware is the exact Product scope in [Supported Models](../core/supported-models.md).
It focuses on normal live
workflows, resource selection, and safe first checks. For developer setup,
detailed command reference, and automation details, see the
[CLI README](README.md).

## Start The CLI

Open PowerShell in the folder that contains the CLI executable and check it:

```powershell
.\powers-tool.exe --version
```

Release folders may include a versioned executable name, such as:

```text
powers-tool-<version>.exe
```

Use that file name in the commands below if your release folder uses a
versioned executable. Developers or source-checkout users should use the
[CLI README](README.md) for virtual environment, module, build, and developer
commands.

For an already-installed command, replace `.\powers-tool.exe` with
`powers-tool`:

```powershell
powers-tool --version
```

Normal Product use leaves `--backend` unset and uses the default System VISA
path. A source checkout or installed Python environment can pass an optional
PyVISA selector such as `--backend "@py"` or `--backend "@bt"` when the
corresponding backend package is installed and loadable. `@bt` is recognized as
the `pyvisa_bt` backend identity, but no current Powers Product-open exact live
scope uses that backend; model-aware Product live commands therefore fail
closed with `--backend "@bt"`. Backend loadability does not grant Product
support.

The current official standalone `powers-tool.exe` does not bundle `pyvisa_bt`.
The standalone commands in this guide use the normal System VISA path.

## First Live Check

Use this flow when checking a new computer, VISA runtime, connection, or power
supply setup.

1. Confirm the instrument is safe to query and any connected DUT can tolerate
   the existing output state.
2. List only VISA resources that currently answer `*IDN?`:

```powershell
.\powers-tool.exe list-resources --live-only
```

3. Copy the exact resource string and set a session variable:

```powershell
$env:POWERS_TOOL_RESOURCE = "USB0::...::INSTR"
```

4. Run a read-only identity check:

```powershell
.\powers-tool.exe verify --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
```

5. Run a read-only measurement or status check before any output action:

```powershell
.\powers-tool.exe measure --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --log-scpi
.\powers-tool.exe read-status --resource "$env:POWERS_TOOL_RESOURCE" --json --log-scpi
```

Use an explicit resource string for live commands. Do not rely on a script or
unattended workflow to guess which instrument should be used.

## Resource Listing

For normal live use, prefer:

```powershell
.\powers-tool.exe list-resources --live-only
```

Plain `list-resources` is passive VISA discovery. It can show stale cached
resources after a device is disconnected or unavailable. `--live-only` opens
each discovered resource, queries `*IDN?`, and prints only resources that
answered.

Use `--verify` when diagnosing stale entries because it reports both live and
failed resources:

```powershell
.\powers-tool.exe list-resources --verify
```

Add `--json` when copying results into automation:

```powershell
.\powers-tool.exe list-resources --live-only --json
```

## Resource Variables

Use environment variables to simplify copying and running multiple commands in a session:

```powershell
$env:POWERS_TOOL_RESOURCE = "USB0::...::INSTR"
$env:POWERS_TOOL_ASRL_RESOURCE = "ASRL1::INSTR"
```

Please note:
* `$env:POWERS_TOOL_RESOURCE` is for generic live USB/LAN examples.
* `$env:POWERS_TOOL_ASRL_RESOURCE` is for E3646A RS-232 / ASRL examples.
* These are documentation convenience variables, not hidden CLI defaults.
* Live commands still require an explicit `--resource` argument.

## Finite Workflow Loops

Ramp, Ramp List, and Sequence accept `--loop-count N`. The value is the total
number of complete executions: 1 is the normal single run, 2 restarts once,
and 10,000 is the maximum. Values outside the strict integer range 1 through 10,000
are rejected. For Ramp List and Sequence files, an explicit CLI value wins;
otherwise the file value is used, then 1 for older supported file versions.

Ramp can pulse after every step, after each complete Ramp iteration, or once
after all loops. Ramp List can pulse after every step, after each Segment, or
once after all loops. Loop-complete pulse timing requires at least two total
executions. Sequence keeps its existing per-Step `trigger-pulse` action and
does not add a top-level completion pulse.

## E3646A RS-232 / ASRL

E3646A Product LIVE support is limited to ASRL / RS-232 with a system VISA
backend. Consult the [Product LIVE exact-scope matrix](../core/supported-models.md#product-live-exact-scope-matrix)
for the current command inventory. `identify` and `verify` are diagnostics only
and do not open another command. Protection, trigger, snapshot/restore,
completion pulses, and native LIST are not Product-open for E3646A.

E3646A uses `INST:NSEL` channel preselection for setpoint writes and readbacks.
`OUTP ON/OFF` is a global output enable/disable on this model, so output
enable/disable actions can affect the instrument output state globally.
E3646A `ramp-list` and `sequence` are software workflows, not native LIST.
Sequence accepts only supported read-only/output steps; protection, trigger,
snapshot, restore, native LIST, and completion-pulse steps are rejected.

Set the ASRL resource once per PowerShell session:

```powershell
$env:POWERS_TOOL_ASRL_RESOURCE = "ASRL1::INSTR"
```

Plain `list-resources` normally does not need serial settings:

```powershell
powers-tool list-resources
```

If Keysight IO Libraries Suite / Connection Expert already has the ASRL
resource configured, try a read-only check without overriding those settings:

```powershell
powers-tool verify --resource "$env:POWERS_TOOL_ASRL_RESOURCE"
```

To explicitly apply serial settings for one command, pass only the fields you
want to override. The E3646A factory example is 9600 baud, 8 data bits, none
parity, 2 stop bits, and DTR/DSR handshake, but the instrument front-panel
settings may have been changed:

```powershell
powers-tool verify --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --serial-baud-rate 9600 --serial-data-bits 8 --serial-parity none --serial-stop-bits 2 --serial-flow-control dtr_dsr --serial-remote --serial-local-on-close
```

`--serial-remote` sends `SYST:REM`. `--serial-local-on-close` best-effort
sends `SYST:LOC` during cleanup. These affect remote/local state and are sent
only when explicitly requested.

Useful read/status examples:

```powershell
powers-tool identify --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --serial-remote --serial-local-on-close
powers-tool readback --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
powers-tool measure --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --channel 2 --serial-remote --serial-local-on-close
powers-tool output-state --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
```

For serial read/write termination in PowerShell, use aliases when possible:
`CR`, `LF`, `CRLF`, or `NONE`. `NONE`, omitted, or blank termination means do
not override the VISA setting.

## Read-Only Workflow

Use read-only commands first when validating an instrument:

```powershell
.\powers-tool.exe identify --resource "$env:POWERS_TOOL_RESOURCE" --json --log-scpi
.\powers-tool.exe readback --resource "$env:POWERS_TOOL_RESOURCE" --json --log-scpi
.\powers-tool.exe protection-status --resource "$env:POWERS_TOOL_RESOURCE" --json --log-scpi
.\powers-tool.exe validate-readonly --resource "$env:POWERS_TOOL_RESOURCE" --json --log-scpi
```

These commands query identity, programmed setpoints, measured values, status,
or protection state. They do not intentionally enable outputs.

## Telemetry Logging

CLI `log` performs bounded read-only telemetry and writes paths selected by the
caller:

```powershell
.\powers-tool.exe log --simulate --model keysight-e36312a --channel all --interval-sec 1 --samples 5 --csv telemetry.csv --jsonl telemetry.jsonl
```

Worker `log` instead requires a sample or duration bound and owns
`telemetry.csv`/`telemetry.jsonl` inside its job directory. It is cancellable,
does not safe-off outputs, preserves completed cycles after cancellation or
failure, accepts no caller artifact paths, and does not run concurrently with
another Worker job. Sequence `log` is only a message/note action;
`--log-scpi` traces SCPI traffic and is not telemetry.

## Output-Affecting Workflow

Output-affecting commands are explicit. Before using them, confirm the
instrument model, channel, DUT wiring, voltage, current limit, and protection
settings.

Set low setpoints without enabling output:

```powershell
.\powers-tool.exe set --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --voltage 1 --current 0.05 --json --log-scpi
```

Read back the programmed state:

```powershell
.\powers-tool.exe readback --resource "$env:POWERS_TOOL_RESOURCE" --json --log-scpi
```

Preview the implemented output-enable plan without opening real hardware:

```powershell
.\powers-tool.exe output-on --dry-run --model keysight-e36312a --channel 1 --json
```

Turn output off when the check is complete:

```powershell
.\powers-tool.exe output-off --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --json --log-scpi
```

For a short smoke action, keep voltage and current low and use the documented
bounded commands in the CLI README. Do not run output workflows unattended
against an unknown resource.

## Common Commands

| Command | Typical use |
| --- | --- |
| `list-resources --live-only` | Find resources that currently answer `*IDN?`. |
| `verify` | Confirm one explicit resource opens and responds. |
| `identify` | Read the model identity. |
| `measure` | Read voltage/current for one channel. |
| `read-status` | Read output status. |
| `readback` | Read programmed setpoints and measured values. |
| `protection-status` | Read protection state. |
| `validate-readonly` | Run a read-only diagnostic pass. |
| `log` | Collect bounded read-only telemetry into CLI-owned CSV/JSONL files. |
| `set` | Set voltage/current without enabling output. |
| `output-on` / `output-off` | Enable or disable output on an accepted exact LIVE scope; dry-run and simulator previews remain available. |
| `safe-off` | Turn output off using the supported safety path. |

## No-Hardware Checks

Dry-run and simulator commands do not open real VISA hardware. When a command
needs model-specific planning, pass a canonical simulation/dry-run model ID with
`--model`, or use a deterministic SIM resource such as
`USB0::SIM::E36312A::INSTR`.

```powershell
.\powers-tool.exe set --dry-run --model keysight-e3646a --channel 1 --voltage 1 --current 0.05
.\powers-tool.exe readback --simulate --resource USB0::SIM::E36312A::INSTR --channel all
.\powers-tool.exe trigger-step --dry-run --model keysight-e36312a --channel 1 --source bus --fire
.\powers-tool.exe set --dry-run --profile generic-scpi --channel 1 --voltage 1 --current 0.05
```

`--profile generic-scpi` is dry-run-only and is exposed only on commands whose
existing support matrix permits Generic planning. It cannot be combined with
`--model` and is invalid in simulator or live execution.

Do not use fake or live-looking resource strings to imply a model in
no-hardware mode. For example, `USB0::FAKE::E36312A::INSTR` is a placeholder,
not a model identity.

For live commands, `--model` accepts a canonical ID such as
`keysight-e36312a` and is an expected-model guard. The CLI still queries
`*IDN?` and uses the detected model for driver selection. If the selected model
does not match the connected IDN model, the command fails before setup or write
SCPI:

```powershell
.\powers-tool.exe set --model keysight-e36312a --resource "$env:POWER_USB_RESOURCE" --channel 1 --voltage 1 --current 0.05
```

This requires the connected model to be E36312A and does not force the E36312A
driver.

`--model` is not a feature unlock. Unsupported model, command, mode, connection,
backend, or feature combinations fail closed. Product LIVE support is exact by
detected model, command, transport, backend, and required feature; missing or
pending scopes fail closed. A feature family or no-hardware plan does not imply
that every command in that family is product-open. See the
[exact matrix](../core/supported-models.md#product-live-exact-scope-matrix).

## Common Problems

If `powers-tool.exe` is missing, confirm you are in the folder that contains
the CLI executable and use the actual filename from that folder.

If no live resources are found, check instrument power, USB/LAN cabling, VISA
driver visibility, and whether another program is holding the instrument.

If plain `list-resources` shows old entries, rerun with `--live-only` for the
normal operator path or `--verify` to diagnose stale VISA cache entries.

If a command refuses to run, read the validation message before retrying. The
CLI intentionally rejects unsupported models, channels, unsafe setpoints, and
missing confirmations before performing risky actions.
If the message says a workflow is disabled for a model, choose a supported
command for that model or use hardware that supports that workflow. Retrying
with `--model` does not enable unsupported features.

If JSON output is needed for logs or automation, add `--json`. Diagnostic SCPI
logs from `--log-scpi` are written separately so JSON stdout remains parseable.

## More CLI Documentation

- [CLI README](README.md): engineering setup, full command reference, JSON
  behavior, worker details, and build information.
- [Power CLI JSON / JSONL Contract](../contracts/power-cli-jsonl-contract.md):
  structured command-line output rules.
- [Power Worker Contract](../contracts/power-worker-contract.md): local worker
  REST, JSONL, and artifact contract.
- [Supported Models](../core/supported-models.md): the current Product support
  matrix and model-specific limits.
