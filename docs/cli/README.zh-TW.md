# Powers Tool CLI

## 參數接收

CLI 會將 argparse 解析出的 Python primitives 傳給共用 Core command
contract。這保留有效的 flag 用法，同時讓 raw Worker/WebUI JSON fail closed：
Core 會拒絕未知或不適用欄位、同時提供的 alias、未記載為 nullable 的明確
null，以及用來代替 exact boolean、integer 或 finite numeric field 的可強制轉換
字串或數字。

這是用於控制支援之直流電源供應器的 vendor-neutral CLI adapter。目前
Product-active 且已完成硬體驗證的型號以文件所述 Keysight models 為準；未知
live hardware 會 fail closed。

CLI 包含在單一 `powers-tool` distribution 中，保留 `powers_tool_cli` import
boundary，並透過 `powers-tool` console command 將操作員命令轉接到共用
`powers_tool_core` runtime。

此文件是 `docs/cli/README.md` 的繁體中文操作摘要。完整工程細節、命令清單與最新範例仍以英文 README 為主；操作員工作流程請優先閱讀 [CLI 使用者指南](USER_GUIDE.zh-TW.md)。

## 文件集

- [CLI 使用者指南](USER_GUIDE.zh-TW.md) - 操作員工作流程、即時資源選擇與安全優先檢查。
- [CLI README](README.zh-TW.md) - 工程建置、驗證腳本、詳細指令參考、自動化與維護者邊界。
- [Power CLI JSON / JSONL 契約](../contracts/power-cli-jsonl-contract.md) - 命令列 JSON 封裝與 JSONL 規則。
- [Power Worker 契約](../contracts/power-worker-contract.md) - 本機 worker REST、JSONL 與 artifact 契約。
- [Power Orchestrator 工作流程](../contracts/power-orchestrator-workflows.md) - 子行程交接與結果輪詢指南。
- [命令參數契約](../contracts/commands-parameter-contract.md) - 穩定的命令參數邊界。

## 用途

此套件提供 `powers-tool` console script、命令參數解析、JSON envelope 處理、
SCPI logging，以及供 orchestrator／agent 使用的本機 Power Worker daemon。
會影響硬體的命令仍須明確且 opt-in；預設套件測試不需要硬體。

## 套件內容

- `powers_tool_cli.cli`：top-level parser、command dispatch、JSON/error/exit
  mapping、SCPI logging 與 Core adapter。
- `powers_tool_cli.cli_io`：穩定的 JSON success/error envelope 與 `--save-json`。
- `powers_tool_cli.lifecycle_client`：Worker lifecycle HTTP request、response
  validation、dry-run 與錯誤 mapping。
- `powers_tool_cli.request_primitives`：共用 argv parsing 與 JSON request fields。
- `powers_tool_cli.runtime_mapping`：identity、execution、support-policy 與
  serial-option mapping。
- `powers_tool_cli.worker`：本機 async Worker、job queue、event 與 artifact。
- `powers_tool_cli.commands.*`：各 command family 的 parser registration 與
  request mapping。

Parser construction 使用明確的 runner callable；request mapping 仍由各 command
family module 與既有 CLI facade 負責，不引入 service-locator。

## 需求

根目錄的 [README 安裝指南](../../README.zh-TW.md#安裝) 是 canonical setup
reference。[Supported Models](../core/supported-models.md) 是 exact Product
support matrix；本節不會為其他 model、transport 或 backend 增加支援。

| 需求 | No-hardware | Live operation |
| --- | --- | --- |
| Python | 使用 `pyproject.toml` 定義的最低版本：`>=3.10`。 | 相同的 Python 需求。 |
| Core/CLI runtime | 安裝目前的 `powers-tool` distribution。 | 安裝目前的 `powers-tool` distribution。 |
| No-hardware | simulator、dry-run、CLI help 與一般測試不需要實體儀器或 vendor VISA runtime。 | 不適用。 |
| Live hardware | 不適用。 | 需要受支援的實體儀器、PyVISA 可載入的外部 VISA implementation/runtime，以及適用且已接受的 connection/backend scope。Resource-specific live commands 需要 operator 明確選定的 VISA resource；discovery commands 可在沒有預先提供 resource 時列舉 resources。 |
| Product support | No-hardware 可用不代表 live 支援。 | Model-aware live commands 遵循 [Supported Models](../core/supported-models.md) 中 exact `model + command + transport + backend + required feature` scope。Diagnostic exemptions 僅限其文件化的 diagnostic purpose。 |
| Safety | Preview 與 simulator 路徑不會啟用真實輸出。 | 影響輸出的命令仍受既有 confirmation gate 與 safety limit 約束。 |

## 安裝

根目錄的 [README 安裝指南](../../README.zh-TW.md#安裝) 是 canonical setup
reference。從 repository 根目錄先同步 locked development/test environment：

```powershell
uv sync --all-extras --locked --link-mode=copy
```

若只需要基本 Core/CLI runtime，可使用：

```powershell
uv sync --locked --link-mode=copy
```

主要安裝後 console entry point 是 `powers-tool`。

Fallback module entry point：

```powershell
uv run python -m powers_tool_cli.cli doctor --simulate --json
```

global `powers-tool --version` option 會輸出 `powers-tool <package-version>`，
不需要 subcommand，也不會開啟 VISA。

## 快速開始

在專案根目錄執行以下命令，以確認 installed console entry point、CLI/Core 基本
載入，以及 deterministic simulator 的 no-hardware 路徑：

```powershell
uv run powers-tool --version
uv run powers-tool doctor --simulate --json
```

此 Quick Start 不會進行 live 或 system-VISA resource discovery、不會開啟 VISA
resource、不會送出 SCPI、不會修改實體儀器狀態，也不會啟用輸出；不需要實體
儀器或 vendor VISA runtime。

一般操作員工作流程請接續閱讀 [CLI 使用者指南](USER_GUIDE.zh-TW.md)。本機瀏覽器
介面請參閱 [WebUI 使用者指南](../webui/USER_GUIDE.zh-TW.md)。Exact live model
與 connection coverage 請參閱 [Supported Models](../core/supported-models.md)。

## 命令系列索引

以下是快速導覽，不取代 `powers-tool --help` 或下方詳細範例。

| Family | Purpose | Representative commands | Details |
| --- | --- | --- | --- |
| 安裝與診斷 | 安裝、探索、身分、錯誤與安全檢查。 | `powers-tool --version`、`doctor`、`list-resources`、`verify`、`identify`、`error`、`clear` | [資源探索與實機資源設定](README.md#resource-discovery-and-live-resource-setup)；`powers-tool --help` |
| 唯讀與狀態 | measurement、readback、output state、capabilities 與儀器狀態。 | `measure`、`measure-all`、`read-status`、`readback`、`output-state`、`capabilities` | [唯讀指令範例](README.md#read-only-command-examples)；`read-status` 是儀器命令。 |
| Setpoint 與 output control | 設定點、輸出切換、safe-off 與受保護的輸出操作。 | `set`、`apply`、`output-on`、`output-off`、`safe-off`、`cycle-output`、`smoke-output` | [會影響輸出的範例](README.md#output-affecting-examples)；[Safety Defaults](README.md#safety-defaults) |
| Output workflows | ramp、ramp-list、software sequence 與 telemetry logging。 | `ramp`、`ramp-list`、`sequence`、`log` | [Ramp、Sequence 與模擬器範例](README.md#ramp-and-sequence-examples)；[Safety Defaults](README.md#safety-defaults) |
| Protection | protection status、設定與清除。 | `protection-status`、`protection-set`、`clear-protection` | [Protection 與 Trigger 範例](README.md#protection-and-trigger-examples)；`powers-tool --help` |
| Trigger | trigger status、setup、fire、abort、pulse 與 LIST workflow。 | `trigger-status`、`trigger-step`、`trigger-list`、`trigger-fire`、`trigger-abort`、`trigger-pulse` | [Protection 與 Trigger 範例](README.md#protection-and-trigger-examples)；仍受 exact feature scope 約束。 |
| Snapshot 與 restore | 擷取、比較、報告與還原儲存的儀器狀態。 | `snapshot`、`snapshot-diff`、`hardware-report`、`restore-from-snapshot` | [Snapshot 與 Restore 範例](README.md#snapshot-and-restore-examples)；[Power CLI JSON / JSONL 契約](../contracts/power-cli-jsonl-contract.md) |
| Worker 與 automation | 本機 Worker lifecycle 與 command submission。 | `worker`、`send-command`、`status`、`stop`、`wait-ready` | [Power Worker Daemon](README.md#power-worker-daemon)；[Power Worker 契約](../contracts/power-worker-contract.md)。`status` 是 Worker lifecycle status；儀器狀態使用 `read-status`。 |

實際 live availability 仍由 model、command、transport、backend 與 required feature
的 exact Product scope 決定。

## 測試

預設 CLI 測試不需要硬體：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\cli -q -p no:cacheprovider
```

pytest 預設使用 repository-local、已忽略的 `.tmp_pytest`，因此不依賴
Windows system temporary directory。請從 repository 根目錄執行 pytest；若需
單次覆寫 basetemp，使用 `--basetemp .tmp_tests/<purpose>`，不要使用 `Local/`。

### Scripted Validation

以下是支援的 standalone validation entry points，不是 `scripts/` 的完整清單。
每個 entry point 都會在 `.tmp_tests` 下寫入 machine-readable `report.json` 與
human-readable `summary.md`。

| Script | Hardware use | Purpose |
| --- | --- | --- |
| `scripts\preflight-cli.ps1` | No hardware | 執行 smoke、deep 或 compatibility full model-aware CLI validation，解析每個 JSON 結果並強制 `hardware_touched=false`。 |
| `scripts\live-cli-check.ps1` | Plan-only 或明確 live hardware | 先執行 preflight，再產生指定 suite 的 exact plan；只有非 `-PlanOnly` 且明確確認後才進入 live validation。 |
| `scripts\release-acceptance.ps1` | No hardware 加上受控 release workflow | 驗證 clean committed HEAD、套件、entry point、standalone artifact 與 checksums，並執行指定的 no-hardware checks。 |
| `scripts\batch-validation.ps1` | 依 switches 選定 | 只執行選定的 simulated 或 live validation task，並產生一份 batch report。 |

從 repository 根目錄執行正式 release acceptance：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\release-acceptance.ps1
```

每個 recorded command 都會顯示 `[start]`，接著顯示 `[passed]` 或 `[failed]`，
並包含 `duration=<seconds>s`。child-process stdout/stderr 仍會在命令完成後收集，
再印出或寫入 acceptance output，不會逐行即時串流。詳細 release acceptance
範圍請參閱根目錄 [README](../../README.md)。

Build entry points、CI quality utilities 與 internal helpers 的完整用途請參閱
英文 CLI README；本文件不把它們誤列為一般 operator command。`preflight-cli.ps1`
的 smoke、deep 與 full suite 是 no-hardware 路徑。`live-cli-check.ps1` 的
PlanOnly 不會開啟 resource；沒有 `-PlanOnly` 時仍需明確互動確認。

Validation artifact 只證明選定的 model、connection、suite 與 cases，不會自動
提升 Product support，也不代表其他 model、connection、feature 或整個儀器。

## 命令狀態

CLI 的 planning identity 與 live expected-model guard 是不同概念。`expected_model_id`
只用來檢查 live `*IDN?` identity mismatch，不會選擇 driver、解鎖 command 或
擴大 Product scope。`planning_model_id` 用於 simulate 或 model-specific dry-run；
`planning_profile_id` 只代表非實體的 dry-run profile，例如 `generic-scpi`，不是
physical model，也不會選擇 live driver。

Accepted physical planning IDs 與 live Product scope 以
[Supported Models](../core/supported-models.md) 為準。Known deterministic simulator
resource 必須與明確 identity 一致；CLI 不會從 fake、live-looking 或 alias-only
resource 猜測 model。

## Power Worker Daemon

Power Worker 以 machine mode 提供本機 lifecycle 與 command submission。`GET /status`
只代表 control-plane health/progress，不是儀器 `read-status`；`POST /command` 的
accepted／HTTP `202` 只代表 job 進入 queue。必須繼續觀察 artifact 直到 terminal
`result.json`，並確認 `status: "succeeded"`、`ok: true`、`run_id` 與
`worker_job_id` correlation 正確。

Worker JSON/JSONL stdout 只輸出 machine evidence；human-readable stdout/stderr
只能作 diagnostic。`ready` 不代表 domain command 完成，`request.json` 只證明
request 已持久化。`POST /stop` acknowledgment 只代表 cooperative stop 已提出，
不代表 cleanup、final summary 或 Worker process exit 已完成。請依
[Power Worker 契約](../contracts/power-worker-contract.md) 與
[Power Orchestrator 工作流程](../contracts/power-orchestrator-workflows.md) 觀察
完整生命週期。

## 範例

### 資源搜尋與實機資源設定

僅列出可以被開啟並透過 `*IDN?` 查詢的 VISA 資源：

```powershell
uv run powers-tool list-resources --live-only
```

通用實機 USB/LAN 範例請先在 PowerShell 工作階段設定 VISA 資源一次：

```powershell
$env:POWERS_TOOL_RESOURCE = "USB0::...::INSTR"
```

驗證單一資源可被開啟並透過 `*IDN?` 查詢：

```powershell
uv run powers-tool verify --resource "$env:POWERS_TOOL_RESOURCE"
uv run powers-tool verify --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
```

### E3646A RS-232 / ASRL 範例

E3646A 在 RS-232/ASRL 上支援已實機驗證的唯讀/狀態查詢與輸出工作流程。執行任何 E3646A 實機輸出命令前，請確認實體接線已檢查完成，且要求的電壓/電流限制對連接負載是安全的。

型號支援的命令包括 `identify`、`measure`、`readback`、`read-status`、`output-state`、`capabilities`、`set`、`apply`、`output-on`、`output-off`、`safe-off`、`cycle-output`、`smoke-output`、`ramp`、`ramp-list` 與影響輸出的 `sequence` 步驟。`verify` 也可作為與型號無關的連線診斷。E3646A 使用 `INST:NSEL` 做通道預選；`OUTP ON/OFF` 是全域輸出啟用/停用行為，即使命令接受通道參數，啟用或停用輸出仍可能影響儀器整體輸出狀態。E3646A 的保護寫入、trigger 工作流程、snapshot restore、completion pulse 與 native LIST 仍維持停用。

每個 PowerShell 工作階段設定一次 ASRL 資源：

```powershell
$env:POWERS_TOOL_ASRL_RESOURCE = "ASRL1::INSTR"
```

重複執行範例時，可把共用 ASRL 設定放在 PowerShell 變數：

```powershell
$Base = @("--resource", "$env:POWERS_TOOL_ASRL_RESOURCE", "--serial-read-termination", "CRLF", "--serial-write-termination", "LF")
$Remote = @("--serial-remote", "--serial-local-on-close")
```

如果 Connection Expert 已經設定並驗證 ASRL 資源，可讓 VISA 使用既有設定：

```powershell
uv run powers-tool verify --resource "$env:POWERS_TOOL_ASRL_RESOURCE"
```

若要為單一命令明確套用序列設定，請只傳入要覆寫的欄位：

```powershell
uv run powers-tool verify --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --serial-baud-rate 9600 --serial-data-bits 8 --serial-parity none --serial-stop-bits 2 --serial-flow-control dtr_dsr --serial-remote --serial-local-on-close
```

`--serial-remote` 會在開啟 ASRL 資源後發送 `SYST:REM`。`--serial-local-on-close` 會在清理時盡最大努力發送 `SYST:LOC`。這些命令會影響儀器遠端/本機狀態，且只在明確要求時發送。

常用唯讀/狀態範例：

```powershell
uv run powers-tool identify --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --serial-remote --serial-local-on-close
uv run powers-tool readback --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
uv run powers-tool measure --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --channel 2 --serial-remote --serial-local-on-close
uv run powers-tool output-state --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
```

已驗證的輸出範例：

```powershell
uv run powers-tool set @Base @Remote --channel 1 --voltage 1 --current 0.05 --json --log-scpi
uv run powers-tool apply @Base @Remote --channel 1 --voltage 1 --current 0.05 --no-output --json --log-scpi
uv run powers-tool output-on @Base @Remote --channel 1 --confirm --json --log-scpi
uv run powers-tool output-off @Base @Remote --channel 1 --json --log-scpi
uv run powers-tool safe-off @Base @Remote --channel 1 --json --log-scpi
uv run powers-tool ramp @Base @Remote --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.25 --current 0.05 --delay-ms 100 --json --log-scpi
```

`output-on`、`cycle-output`、`smoke-output`，以及未使用 `--no-output` 的 `apply`，在選定設定點超過確認門檻時需要 `--confirm`。`set`、`output-off`、`safe-off`、`ramp`、`ramp-list` 不要求 `--confirm`。

序列終止字元請優先使用別名 `CR`、`LF`、`CRLF` 或 `NONE`。`NONE` 表示不設定該終止字元選項；省略或空白欄位也表示不覆寫 VISA 設定。

### 唯讀指令範例

```powershell
uv run powers-tool measure --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --log-scpi
uv run powers-tool measure-all --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
uv run powers-tool read-status --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
uv run powers-tool validate-readonly --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi --save-json logs/validate-readonly.json
uv run powers-tool readback --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
uv run powers-tool protection-status --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
```

### Snapshot 與 Restore 範例

```powershell
uv run powers-tool snapshot --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
uv run powers-tool snapshot --json --resource "$env:POWERS_TOOL_RESOURCE" --compare logs/e36312a-baseline.json
uv run powers-tool snapshot-diff --summary --json --before logs/before.json --after logs/after.json
uv run powers-tool restore-from-snapshot --dry-run --json --snapshot logs/before.json --resource "$env:POWERS_TOOL_RESOURCE" --channel all --plan-json logs/restore-plan.json
```

### Protection 與 Trigger 範例

```powershell
uv run powers-tool clear-protection --dry-run --json --resource "$env:POWERS_TOOL_RESOURCE" --all
uv run powers-tool protection-set --dry-run --json --resource "$env:POWERS_TOOL_RESOURCE" --channel all --ovp-voltage 5 --ocp on
uv run powers-tool trigger-pulse --json --resource "$env:POWERS_TOOL_RESOURCE" --pin 1 --channel 1 --polarity positive --log-scpi
uv run powers-tool trigger-status --json --resource "$env:POWERS_TOOL_RESOURCE" --channel all
```

### 會影響輸出的範例

影響輸出的命令必須明確要求，且使用前需確認型號、通道、DUT 接線、電壓、電流限制與保護設定。E3646A RS-232 / ASRL 輸出工作流程已實機驗證；執行前請確認實體接線已檢查完成，且要求的電壓/電流限制對連接負載是安全的。詳細範例請參考英文 README 與 CLI 使用者指南。

### Ramp、Sequence 與模擬器範例

```powershell
uv run powers-tool ramp-list --lint --json --file example.ramp-list.json
uv run powers-tool sequence --lint --json --resource "USB0::SIM::E36312A::INSTR" --file examples/sequence-readonly.yaml
uv run powers-tool clear --dry-run --json --resource "USB0::SIM::E36312A::INSTR"
uv run powers-tool measure --simulate --json --resource "USB0::SIM::E36312A::INSTR" --channel 2
uv run powers-tool doctor --simulate --json
uv run powers-tool capabilities --simulate --json --resource "USB0::SIM::EDU36311A::INSTR" --command protection-set
uv run powers-tool safety inspect --json --explain --safety-config examples/safety-config.toml --resource-alias sim-e36312a --channel 1
```

## Safety Defaults

- 影響輸出的行為必須明確要求。
- E3646A 在 RS-232 / ASRL 上保留唯讀與狀態查詢工作流程，並加入已實機驗證的輸出工作流程。
- `--safety-config` 只會套用本機 plan validation 限制；它不會自動啟用硬體輸出。
- 真實 VISA resource 不應硬編碼在提交的檔案中。
- 硬體測試必須要求使用者提供 resource。
- 啟用輸出的範例必須設定安全的 current limit，並在清理時關閉輸出。

## 狀態

Active package。E36312A live validation 涵蓋 hardware test guide 所記載的唯讀 CLI
流程、安全 setpoint 流程、Worker dry-run／read-only 行為與 native trigger-list
流程。
