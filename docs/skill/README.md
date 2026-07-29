# Powers Tool CLI Orchestration Skill

This directory publishes the optional `powers-tool-cli-orchestration` Codex /
Agent Skill template for Powers Tool. It helps an agent follow the current CLI,
Power Worker, Core command-admission, execution-context, Product LIVE support,
artifact-lifecycle, and hardware-safety contracts.

The Skill is an independent project companion. It is not part of the Powers
Tool runtime and is not installed with a wheel, sdist, executable, or other
Powers installation. It is not package data, a console entry point, a build or
release input, a CI gate, or a project test requirement. Codex will not discover
`docs/skill/SKILL.md` while it remains here; copy it manually only when needed.

## Scope

Use the Skill for contract-aware CLI/Worker changes and reviews, deterministic
no-hardware orchestration, schema-2 machine-output checks, execution-context and
job correlation, Core parameter admission, exact Product LIVE scope decisions,
or preparation of explicitly authorized live workflows.

Do not use it to widen Product support, change SCPI, discover hardware, choose a
live resource for the user, or automatically run live output changes. Repository
contract originals remain authoritative.

## Standalone references

Inside a Powers Tool checkout, the original files under `docs/contracts/` and
`docs/core/` are always the upstream source of truth. For a standalone
executable workspace, manually create this snapshot in the installed Skill:

```text
references/
  common-worker-protocol.md
  common-cli-jsonl-contract.md
  common-orchestrator-workflows.md
  power-worker-contract.md
  power-cli-jsonl-contract.md
  power-orchestrator-workflows.md
  commands-parameter-contract.md
  supported-models.md
```

Copy them from:

| Installed snapshot | Repository source |
| --- | --- |
| `common-worker-protocol.md` | `docs/contracts/common-worker-protocol.md` |
| `common-cli-jsonl-contract.md` | `docs/contracts/common-cli-jsonl-contract.md` |
| `common-orchestrator-workflows.md` | `docs/contracts/common-orchestrator-workflows.md` |
| `power-worker-contract.md` | `docs/contracts/power-worker-contract.md` |
| `power-cli-jsonl-contract.md` | `docs/contracts/power-cli-jsonl-contract.md` |
| `power-orchestrator-workflows.md` | `docs/contracts/power-orchestrator-workflows.md` |
| `commands-parameter-contract.md` | `docs/contracts/commands-parameter-contract.md` |
| `supported-models.md` | `docs/core/supported-models.md` |

Installed `references/` files are only a manually created documentation
snapshot. They are not another formal contract. Re-copy them when upstream
documents change and the installed Skill needs the update. They do not
participate in Powers packaging, release, or CI, and this repository does not
commit a duplicate snapshot under `docs/skill/`.

## Repo-level installation

Use repo-level installation when the Skill should be available only in one
checkout. This creates a local `.agents/skills/` installation; the repository
does not ship one.

Expected layout:

```text
powers-tool/
  .agents/
    skills/
      powers-tool-cli-orchestration/
        SKILL.md
        references/
          common-worker-protocol.md
          common-cli-jsonl-contract.md
          common-orchestrator-workflows.md
          power-worker-contract.md
          power-cli-jsonl-contract.md
          power-orchestrator-workflows.md
          commands-parameter-contract.md
          supported-models.md
        scripts/
          run_power_sim_workflow.mjs
```

PowerShell from the repository root:

```powershell
$skill = ".agents\skills\powers-tool-cli-orchestration"
New-Item -ItemType Directory -Force "$skill\references", "$skill\scripts" | Out-Null

Copy-Item "docs\skill\SKILL.md" "$skill\SKILL.md"
Copy-Item "docs\skill\scripts\run_power_sim_workflow.mjs" "$skill\scripts\"
Copy-Item "docs\contracts\common-worker-protocol.md" "$skill\references\"
Copy-Item "docs\contracts\common-cli-jsonl-contract.md" "$skill\references\"
Copy-Item "docs\contracts\common-orchestrator-workflows.md" "$skill\references\"
Copy-Item "docs\contracts\power-worker-contract.md" "$skill\references\"
Copy-Item "docs\contracts\power-cli-jsonl-contract.md" "$skill\references\"
Copy-Item "docs\contracts\power-orchestrator-workflows.md" "$skill\references\"
Copy-Item "docs\contracts\commands-parameter-contract.md" "$skill\references\"
Copy-Item "docs\core\supported-models.md" "$skill\references\"
```

Bash from the repository root:

```bash
skill=".agents/skills/powers-tool-cli-orchestration"
mkdir -p "$skill/references" "$skill/scripts"

cp docs/skill/SKILL.md "$skill/SKILL.md"
cp docs/skill/scripts/run_power_sim_workflow.mjs "$skill/scripts/"
cp docs/contracts/common-worker-protocol.md "$skill/references/"
cp docs/contracts/common-cli-jsonl-contract.md "$skill/references/"
cp docs/contracts/common-orchestrator-workflows.md "$skill/references/"
cp docs/contracts/power-worker-contract.md "$skill/references/"
cp docs/contracts/power-cli-jsonl-contract.md "$skill/references/"
cp docs/contracts/power-orchestrator-workflows.md "$skill/references/"
cp docs/contracts/commands-parameter-contract.md "$skill/references/"
cp docs/core/supported-models.md "$skill/references/"
```

## User-level installation

Use user-level installation when the Skill should be available across
workspaces. Run these examples from a Powers Tool checkout so the upstream
references can be copied.

PowerShell:

```powershell
$userProfile = [Environment]::GetFolderPath("UserProfile")
$skill = Join-Path $userProfile ".agents\skills\powers-tool-cli-orchestration"
New-Item -ItemType Directory -Force (Join-Path $skill "references"), (Join-Path $skill "scripts") | Out-Null

Copy-Item "docs\skill\SKILL.md" (Join-Path $skill "SKILL.md")
Copy-Item "docs\skill\scripts\run_power_sim_workflow.mjs" (Join-Path $skill "scripts")
Copy-Item "docs\contracts\common-worker-protocol.md" (Join-Path $skill "references")
Copy-Item "docs\contracts\common-cli-jsonl-contract.md" (Join-Path $skill "references")
Copy-Item "docs\contracts\common-orchestrator-workflows.md" (Join-Path $skill "references")
Copy-Item "docs\contracts\power-worker-contract.md" (Join-Path $skill "references")
Copy-Item "docs\contracts\power-cli-jsonl-contract.md" (Join-Path $skill "references")
Copy-Item "docs\contracts\power-orchestrator-workflows.md" (Join-Path $skill "references")
Copy-Item "docs\contracts\commands-parameter-contract.md" (Join-Path $skill "references")
Copy-Item "docs\core\supported-models.md" (Join-Path $skill "references")
```

Bash:

```bash
skill="$HOME/.agents/skills/powers-tool-cli-orchestration"
mkdir -p "$skill/references" "$skill/scripts"

cp docs/skill/SKILL.md "$skill/SKILL.md"
cp docs/skill/scripts/run_power_sim_workflow.mjs "$skill/scripts/"
cp docs/contracts/common-worker-protocol.md "$skill/references/"
cp docs/contracts/common-cli-jsonl-contract.md "$skill/references/"
cp docs/contracts/common-orchestrator-workflows.md "$skill/references/"
cp docs/contracts/power-worker-contract.md "$skill/references/"
cp docs/contracts/power-cli-jsonl-contract.md "$skill/references/"
cp docs/contracts/power-orchestrator-workflows.md "$skill/references/"
cp docs/contracts/commands-parameter-contract.md "$skill/references/"
cp docs/core/supported-models.md "$skill/references/"
```

## Simulator helper

`scripts/run_power_sim_workflow.mjs` runs one fixed no-hardware smoke:

- deterministic `USB0::SIM::E36312A::INSTR`;
- simulate Worker;
- top-level context
  `{"mode":"simulate","planning_model_id":"keysight-e36312a"}`;
- one read-only `read-status` command.

It accepts an explicit Powers executable, or uses the only matching
`powers-tool*.exe` in the current directory. It starts and owns the Worker,
collects stdout JSONL and stderr, waits for readiness, gets status, sends the
command, records accepted job identities, checks `request.json` and terminal
`result.json`, requests cooperative stop, and validates final summary,
correlation, runtime schema 2, and Worker exit code.

The helper writes:

```text
worker_stdout.jsonl
worker_stderr.txt
wait_ready.json
status_before_command.json
accepted.json
request.json
result.json
stop.json
power_sim_report.json
```

The wrapper report uses its own `schema_version: 1` and records
`runtime_schema_version: 2`. A zero exit code means all wrapper checks passed.
The helper is intentionally not a general orchestrator: it rejects live or
arbitrary resources, alternate commands, output writes, and mode selection.

Example:

```powershell
node .agents\skills\powers-tool-cli-orchestration\scripts\run_power_sim_workflow.mjs `
  --exe .\powers-tool-<version>.exe `
  --out .tmp_tests\power_sim_workflow
```

## Invocation examples

See [EXAMPLES.md](EXAMPLES.md) for short copyable prompts. Invoke the installed
Skill by its exact name:

```text
Use $powers-tool-cli-orchestration to run the deterministic read-only Powers simulator smoke and assess only machine evidence.
```

```text
Use $powers-tool-cli-orchestration to review this repository diff against the Power Worker and Core admission contracts.
```

## Live safety

Live workflows require an exact VISA resource explicitly supplied by the user
and separate explicit live authorization. Never scan, guess, rotate, or replace
that resource. For a live output-affecting Worker command, both
`settings.allow_output_writes: true` and `arguments.confirm_output: true` are
required. Use conservative setpoints, preserve safe-off and cleanup, and
remember that `expected_model_id` is only a mismatch guard, not driver or
support selection.

Traditional Chinese documentation: [README.zh-TW.md](README.zh-TW.md).
