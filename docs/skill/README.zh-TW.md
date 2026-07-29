# Powers Tool CLI 調度 Skill

此目錄提供 Powers Tool 選用的 `powers-tool-cli-orchestration` Codex／Agent
Skill 範本。它協助 Agent 遵循目前 CLI、Power Worker、Core command
admission、execution context、Product LIVE support、artifact lifecycle 與硬體
安全合約。

此 Skill 是獨立的專案附屬功能，不屬於 Powers Tool runtime，也不會隨 wheel、
sdist、executable 或其他 Powers 安裝方式自動安裝。它不是 package data、
console entry point、build／release 輸入、CI gate 或專案測試要求。
`docs/skill/SKILL.md` 留在此處時不會被 Codex 自動發現；需要時才手動複製。

## 適用範圍

適用於合約導向的 CLI／Worker 變更與審查、deterministic no-hardware
調度、schema 2 machine output 檢查、execution context 與 job correlation、
Core 參數 admission、Product LIVE exact scope 判定，以及準備已明確授權的
live workflow。

不要用它擴張 Product support、修改 SCPI、探索硬體、替使用者選擇 live
resource，或自動執行 live output 變更。Repository 原始合約永遠是 authority。

## Standalone references

在 Powers Tool checkout 內，`docs/contracts/` 與 `docs/core/` 的原始文件永遠
是 upstream source of truth。若只有 standalone executable workspace，請在
已安裝 Skill 內手動建立以下快照：

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

來源對應如下：

| 安裝後快照 | Repository 原始來源 |
| --- | --- |
| `common-worker-protocol.md` | `docs/contracts/common-worker-protocol.md` |
| `common-cli-jsonl-contract.md` | `docs/contracts/common-cli-jsonl-contract.md` |
| `common-orchestrator-workflows.md` | `docs/contracts/common-orchestrator-workflows.md` |
| `power-worker-contract.md` | `docs/contracts/power-worker-contract.md` |
| `power-cli-jsonl-contract.md` | `docs/contracts/power-cli-jsonl-contract.md` |
| `power-orchestrator-workflows.md` | `docs/contracts/power-orchestrator-workflows.md` |
| `commands-parameter-contract.md` | `docs/contracts/commands-parameter-contract.md` |
| `supported-models.md` | `docs/core/supported-models.md` |

已安裝的 `references/` 只是手動建立的文件快照，不是另一套正式合約。上游
文件改變後，請在需要時自行重新複製。它們不參與 Powers package、release 或
CI；本 repository 也不會在 `docs/skill/` 提交重複快照。

## Repo-level 安裝

僅希望特定 checkout 使用此 Skill 時，採用 repo-level 安裝。這會建立本機
`.agents/skills/` 安裝；repository 本身不會預先提供該目錄。

預期結構：

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

從 repository root 執行 PowerShell：

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

從 repository root 執行 Bash：

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

## User-level 安裝

希望跨 workspace 使用時，採用 user-level 安裝。以下指令須從 Powers Tool
checkout 執行，以便複製上游 references。

PowerShell：

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

Bash：

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

`scripts/run_power_sim_workflow.mjs` 只執行一個固定的 no-hardware smoke：

- deterministic `USB0::SIM::E36312A::INSTR`；
- simulate Worker；
- top-level context
  `{"mode":"simulate","planning_model_id":"keysight-e36312a"}`；
- 一個 read-only `read-status` command。

它接受明確指定的 Powers executable；若未指定，則只在目前目錄恰好有一個
符合的 `powers-tool*.exe` 時使用該檔案。Helper 會啟動並持有 Worker、
收集 stdout JSONL 與 stderr、等待 ready、取得 status、送出 command、
記錄 accepted job identities、檢查 `request.json` 與 terminal
`result.json`、cooperative stop，最後驗證 summary、correlation、runtime
schema 2 與 Worker exit code。

Helper 會寫出：

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

Wrapper report 使用自己的 `schema_version: 1`，並以
`runtime_schema_version: 2` 標示受檢查的 Powers runtime。Exit code 0 代表
所有 wrapper checks 通過。此 helper 刻意不是通用 orchestrator；它拒絕 live
或任意 resource、其他 command、output write 與 mode selection。

範例：

```powershell
node .agents\skills\powers-tool-cli-orchestration\scripts\run_power_sim_workflow.mjs `
  --exe .\powers-tool-<version>.exe `
  --out .tmp_tests\power_sim_workflow
```

## Invocation 範例

[EXAMPLES.zh-TW.md](EXAMPLES.zh-TW.md) 提供可複製的短 prompt。請使用完全一致
的 Skill 名稱：

```text
使用 $powers-tool-cli-orchestration 執行 deterministic read-only Powers simulator smoke，並只依 machine evidence 判定結果。
```

```text
使用 $powers-tool-cli-orchestration 依 Power Worker 與 Core admission 合約審查這份 repository diff。
```

## Live 安全

Live workflow 必須使用使用者明確提供的 exact VISA resource，並取得另一項
明確 live authorization。不得掃描、猜測、輪替或替換 resource。Live
output-affecting Worker command 必須同時具備
`settings.allow_output_writes: true` 與 `arguments.confirm_output: true`。
使用保守 setpoint、保留 safe-off 與 cleanup，並記住 `expected_model_id` 只是
mismatch guard，不選 driver，也不解鎖 support。

英文文件：[README.md](README.md)。
