# Powers Tool CLI

## 參數接收

CLI 會將 argparse 解析出的 Python primitives 傳給共用 Core command
contract。這保留有效的 flag 用法，同時讓 raw Worker/WebUI JSON fail closed：
Core 會拒絕未知或不適用欄位、同時提供的 alias、未記載為 nullable 的明確
null，以及用來代替 exact boolean、integer 或 finite numeric field 的可強制轉換
字串或數字。

這是用於控制支援之直流電源供應器的 vendor-neutral CLI adapter。目前
Product-active 型號以 [Supported Models](../core/supported-models.md) 所列 exact
model scopes 為準；未知 live hardware 會 fail closed。

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

- `powers_tool_cli.cli`：top-level composition 與 entry point（`build_parser`、
  `main`），明確組合各 command owner 的 handler，以及仍由此處保留的
  Core-delegated handler（`_run_core_trigger`、`_run_sequence`、
  `_run_restore_from_snapshot`）。
- `powers_tool_cli.cli_runtime`：共用 resource I/O、safety resolution、JSON
  file helper、error/exit emission，以及直接呼叫 Core/resource 的 adapter。
- `powers_tool_cli.cli_request`：JSON request envelope 與 Core request construction
  （`OperationRequest`、`TriggerRequest` 等 helper）。
- `powers_tool_cli.cli_io`：穩定的 JSON success/error envelope 與 `--save-json`。
- `powers_tool_cli.cli_rendering`：純文字 success-line formatter，包含共用
  workflow execution notice，以及 Output、Trigger、plan、Sequence、discovery、
  read-only、inspection、write、workflow 與 artifact-success summary。
- `powers_tool_cli.lifecycle_client`：Worker lifecycle HTTP request、response
  validation、dry-run 與錯誤 mapping。
- `powers_tool_cli.request_primitives`：共用 argv parsing 與 JSON request fields。
- `powers_tool_cli.runtime_mapping`：identity、execution、support-policy 與
  serial-option mapping。
- `powers_tool_cli.worker`：Worker 進入點與 composition root（`run_worker`），
  保留既有 public compatibility re-export；內部/private 使用者直接依賴各自的
  worker_* owner module。
- `powers_tool_cli.worker_protocol`：Worker schema version、command taxonomy、context/request 驗證、response 封裝與參數正規化。
- `powers_tool_cli.worker_config`：Worker 設定載入、驗證、serial 選項解析與 event sink 檢查。
- `powers_tool_cli.worker_state`：執行緒安全的 `WorkerState` 狀態追蹤容器。
- `powers_tool_cli.worker_http`：`WorkerHTTPServer`、`WorkerHTTPHandler` 端點編排（`/status`、`/stop`、`/cancel`、`/command`）與伺服器關閉 helper。
- `powers_tool_cli.worker_execution`：背景 `job_runner` 迴圈、`_run_job_impl`、PyVISA/simulator 連線開啟、cleanup 記錄、遙測 logging 與 Core 執行/錯誤 mapping。
- `powers_tool_cli.worker_io`：執行緒安全事件發送（`emit_event`）與原子 JSON artifact 寫入（`_write_json_artifact_atomic`）。
- `powers_tool_cli.commands.discovery`：discovery 與 generic instrument I/O
  handler（`list-resources`、`verify`、`clear`、`error`、`measure`）。
- `powers_tool_cli.commands.readonly`：read-only、protection、snapshot artifact、
  hardware-report 與 logging handler。
- `powers_tool_cli.commands.inspection`：`doctor`、`capabilities`、
  `safety inspect` handler。
- `powers_tool_cli.commands.output_run`：output command execution、dry-run
  planning 與 output result adapter。
- `powers_tool_cli.commands.trigger_run`：共用 Trigger request/configuration
  validation 與 result-payload helper。Active Trigger execution 由
  `powers_tool_core.trigger` 負責。
- `powers_tool_cli.commands.sequence_run`：ramp-list workflow handler 與
  shared sequence/Trigger compatibility helper。Sequence planning 與 execution
  由 `powers_tool_core.sequence` 負責。
- `powers_tool_cli.commands.*`（lifecycle、output、ramp_list、sequence、trigger）：
  各 command family 的 parser registration 與 request mapping。

Parser construction 使用明確的 runner callable。各 command family module 負責
handler、parser registration 與 request mapping；`cli.py` 是 composition root，
不再作為 re-export facade，也不引入 service-locator。

CLI 負責參數解析、request mapping、文字與 machine rendering、JSON/JSONL
envelope、exit-code mapping 與 top-level composition；上述三個 root handler
仍由 `cli.py` 實作。Core 負責 IDN/model
resolution、capability metadata、exact live-support admission、driver selection
與 model-specific execution。`validate-readonly` 使用窄的
`powers_tool_core.readonly.run_validate_readonly()` adapter boundary；不將它加入
`COMMAND_CONTRACTS` 或共用 command routing。支援既有 command contract 的 model
應整合在 Core，不需要在 CLI 增加 concrete driver branch。

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

省略 `--backend` 時，CLI 會透過 `pyvisa.ResourceManager()` 使用預設的 System
VISA 路徑。在 source checkout、virtual environment 或 installed Python
environment 中，CLI 可以傳遞 `--backend "@py"` 或 `--backend "@bt"` 等 optional
PyVISA selector；對應的 backend package 必須安裝在同一環境中，且 PyVISA 必須能載入。

`@bt` 會對應到獨立的 `pyvisa_bt` support-policy identity。Backend package 已安裝
或 PyVISA 可載入都不會自行授予 Product support；model-aware live execution 仍須符合
exact Product-open `model + command + transport + backend + required feature`
scope。目前沒有使用 `pyvisa_bt` 的 Product-open exact scope，因此搭配
`--backend "@bt"` 的 model-aware Product live execution 會 fail closed。目前官方
standalone `powers-tool.exe` 不會 bundle pyvisa-py、`pyvisa_bt` 等 optional Python
backend package，也不包含 BT runtime 或 service。

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
| 唯讀與狀態 | measurement、readback、output state、capabilities、儀器狀態與有界 telemetry。 | `measure`、`measure-all`、`read-status`、`readback`、`output-state`、`capabilities`、`log` | [唯讀指令範例](README.md#read-only-command-examples)；`read-status` 是儀器命令。 |
| Setpoint 與 output control | 設定點、輸出切換、safe-off 與受保護的輸出操作。 | `set`、`apply`、`output-on`、`output-off`、`safe-off`、`cycle-output`、`smoke-output` | [會影響輸出的範例](README.md#output-affecting-examples)；[Safety Defaults](README.md#safety-defaults) |
| Output workflows | ramp、ramp-list 與 software sequence。 | `ramp`、`ramp-list`、`sequence` | [Ramp、Sequence 與模擬器範例](README.md#ramp-and-sequence-examples)；[Safety Defaults](README.md#safety-defaults) |
| Protection | protection status、設定與清除。 | `protection-status`、`protection-set`、`clear-protection` | [Protection 與 Trigger 範例](README.md#protection-and-trigger-examples)；`powers-tool --help` |
| Trigger | trigger status、setup、fire、abort、pulse 與 LIST workflow。 | `trigger-status`、`trigger-step`、`trigger-list`、`trigger-fire`、`trigger-abort`、`trigger-pulse` | [Protection 與 Trigger 範例](README.md#protection-and-trigger-examples)；仍受 exact feature scope 約束。 |
| Snapshot 與 restore | 擷取、比較、報告與還原儲存的儀器狀態。 | `snapshot`、`snapshot-diff`、`hardware-report`、`restore-from-snapshot` | [Snapshot 與 Restore 範例](README.md#snapshot-and-restore-examples)；[Power CLI JSON / JSONL 契約](../contracts/power-cli-jsonl-contract.md) |
| Worker 與 automation | 本機 Worker lifecycle 與 command submission。 | `worker`、`send-command`、`status`、`stop`、`wait-ready` | [Power Worker Daemon](README.md#power-worker-daemon)；[Power Worker 契約](../contracts/power-worker-contract.md)。`status` 是 Worker lifecycle status；儀器狀態使用 `read-status`。 |

實際 live availability 仍由 model、command、transport、backend 與 required feature
的 exact Product scope 決定。
Product-open command 不代表整個 feature family 開放；missing 或 pending feature
scopes 仍會 fail closed。CLI model list 僅包含 Product-active models。

GW Instek PSM-2010 的 Product LIVE scope 僅限 ASRL / RS-232 + system VISA，
並開放 Core Product matrix 所列的 23 個 model-aware commands，包括
setpoint／output、protection、snapshot／restore、ramp 與 software sequence
workflows。Powers Trigger commands 與 OCP delay 設定、讀回及 trigger 仍不支援；
USB、TCPIP、GPIB、pyvisa-py、pyvisa-bt 與 custom VISA scopes 仍會 fail closed。

## 測試

預設 CLI 測試不需要硬體：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\cli -q -p no:cacheprovider
```

Focused suites：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\cli\test_cli_output_commands.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\cli\test_cli_trigger.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\cli\test_worker.py -q -p no:cacheprovider
```

原 monolithic `test_cli.py` 已依 command family 拆到 `tests/cli/`（例如
`test_cli_discovery.py`、`test_cli_generic_io.py`、
`test_cli_output_commands.py`）。共用 CLI test helpers 位於
`tests/cli/cli_test_helpers.py`。

pytest 預設使用 repository-local、已忽略的 `.tmp_pytest`，因此不依賴
Windows system temporary directory。請從 repository 根目錄執行 pytest；若需
單次覆寫 basetemp，使用 `--basetemp .tmp_tests/<purpose>`，不要使用 `Local/`。

### Scripted Validation

以下是支援的 standalone validation entry points。請從 repository 根目錄在
PowerShell 執行這些腳本。每個 validation result 僅涵蓋實際執行的 models、
connections、suites 與 checks；執行 validation entry point 不會擴大 Product
support。請參閱 [Contributing](../CONTRIBUTING.md) 了解 contributor workflow。

| Script | Hardware use | Purpose |
| --- | --- | --- |
| `scripts\preflight-cli.ps1` | No hardware | 執行 model-aware CLI smoke/deep no-hardware checks。 |
| `scripts\live-cli-check.ps1` | Plan-only 或明確 live hardware | 執行選定的 model-aware CLI validation suite。 |
| `scripts\release-acceptance.ps1` | No hardware 加上 build checks | 執行 release validation workflow。 |
| `scripts\batch-validation.ps1` | 依 switches 選定 | 執行選定的 simulated 或 live validation tasks。 |

以 `scripts\live-cli-check.ps1` 進行實機 validation 時，假設目標 physical
instrument 僅由單一 client 存取。live execution 前，請確認沒有其他 Powers
WebUI、CLI、logger、test process 或外部 VISA 應用程式正在使用同一個 physical
instrument resource。同一台儀器上的獨立 client 可能互相干擾 SCPI
request/response ordering，也可能在彼此不知情下改變 instrument state。Powers
Tool 不會強制 single-client ownership；這是 live validation 的操作前提。

#### CLI preflight（`scripts\preflight-cli.ps1`）

`scripts\preflight-cli.ps1` 是 no-hardware CLI validation 路徑。它需要 repository
`.venv` CLI（`.\.venv\Scripts\powers-tool.exe`），不會開啟 VISA 或觸碰硬體。它會對
選定 validation target 執行支援的 dry-run 與 simulator CLI cases。

從 repository 根目錄執行預設 preflight：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\preflight-cli.ps1
```

預設 `-Target` 為 `all`，因此會檢查所有已註冊 validation target。若只要驗證單一
model：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\preflight-cli.ps1 `
  -Target keysight-e36312a
```

可接受的 `-Target` 值為：

```text
keysight-e36312a
keysight-edu36311a
keysight-e3646a
gw-instek-psm-2010
```

可明確使用 `-Target all` 重新執行全部四個 target。不支援的 target 名稱會以相同
supported-target 清單失敗。

以 `-Suite` 選擇 preflight 深度：

- `smoke` 執行較快的 identity、metadata 與 readonly 子集。
- `deep` 執行較深的 dry-run 與 simulator cases。搭配 `-Target all` 時，只會執行
  deep representative：`keysight-e36312a` 與 `keysight-e3646a`。
- `full`（預設）對每個選定 target 執行完整 no-hardware case set。

範例：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\preflight-cli.ps1 `
  -Target keysight-e3646a `
  -Suite deep
```

Preflight artifacts 預設寫入 `.tmp_tests\cli_preflight`。可指定自訂 `-OutputRoot`，
但必須留在 `.tmp_tests` 之下。每次執行會建立 timestamped directory，內含 per-target
`report.json`、`summary.md`，以及 per-command JSON/stdout/stderr artifacts。

#### Live CLI validation（`scripts\live-cli-check.ps1`）

`scripts\live-cli-check.ps1` 是維護中的實機 validation wrapper。它要求明確的
`-Target`、`-Connection` 與 `-Resource`，不會掃描或猜測 live resource。執行此腳本
只產生 validation evidence；它不會自行將 pending support 提升為 Product-open，也不會
改變 [Product LIVE exact-scope matrix](../core/supported-models.md#product-live-exact-scope-matrix)。

使用 live wrapper 前，請先把 operator 選定的 exact VISA resource 放入 PowerShell
session 變數。請使用 model 與 transport 專用名稱，避免範例混淆：

```powershell
$env:E36312A_USB_RESOURCE = "USB0::...::INSTR"
```

環境變數只是文件上的便利做法。wrapper 不會自動探索或讀取它；必須明確以
`-Resource "$env:E36312A_USB_RESOURCE"` 傳入。

先執行 plan-only run：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\live-cli-check.ps1 `
  -Target keysight-e36312a `
  -Connection usb `
  -Resource "$env:E36312A_USB_RESOURCE" `
  -Suite readonly `
  -PlanOnly
```

`-PlanOnly` 會產生並驗證 suite 的 CLI dry-run 與 simulator plans，但不開啟 VISA
resource。即使 plan-only 仍必須提供 explicit `-Resource`，planned commands 與
artifacts 才會代表預期 connection。plan-only 模式下，預設仍會執行 external
no-hardware preflight（同一 target 的 `preflight-cli.ps1`）。

若 preflight 已另行完成，只要產生 live plans，可在 `-PlanOnly` 搭配
`-SkipExternalPreflight`：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\live-cli-check.ps1 `
  -Target keysight-e36312a `
  -Connection usb `
  -Resource "$env:E36312A_USB_RESOURCE" `
  -Suite readonly `
  -PlanOnly `
  -SkipExternalPreflight
```

`-SkipExternalPreflight` 不能用於真正的 live run。

檢視 plan 後，移除 `-PlanOnly` 即可執行最小 live readonly suite：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\live-cli-check.ps1 `
  -Target keysight-e36312a `
  -Connection usb `
  -Resource "$env:E36312A_USB_RESOURCE" `
  -Suite readonly
```

Live run 會先執行 external preflight 並產生 suite 的 no-hardware plans，接著列出
可能的 instrument state changes，並要求互動式 Enter 確認後才執行 live SCPI。stdin
被 redirect 時無法核准 live run。state-changing suite 使用有界低功率 cases（通常
1 V / 0.05 A），且 `-Restore` 維持預設 `$true` 時會嘗試 safe-off cleanup。

支援的參數：

- `-Target`：canonical model ID。目前為 `keysight-e36312a`、`keysight-edu36311a`、
  `keysight-e3646a`、`gw-instek-psm-2010`。
- `-Connection`（別名 `-Transport`）：`usb` 或 `local` 代表 USB；`lan` 或 `network`
  代表 LAN/TCPIP；`asrl`、`rs-232` 或 `serial` 代表 ASRL/RS-232。
- `-Resource`：operator 選定的 exact VISA resource。plan-only 模式也必填。
- `-Backend`：選用的 PyVISA backend selector，例如 `@py` 或 `@bt`。省略則使用 System
  VISA。backend 安裝與可載入性本身不授予 Product support；model-aware live execution
  仍須符合 exact Product-open `model + command + transport + backend + required feature`
  scope。`@bt` 會辨識為 `pyvisa_bt` backend identity，但目前沒有任何 Product-open
  或已註冊 validation-candidate scope 使用它。
- `-Suite`：`readonly`（預設）、`safe-state`、`output`、`protection`、`snapshot`、
  `trigger-list`、`software-sequence`、`full`。
- `-PlanOnly`：驗證並寫入 no-hardware plans，不開啟 VISA。
- `-SkipExternalPreflight`：僅在 `-PlanOnly` 時可跳過 separate preflight。
- `-Restore`：預設 `$true`。設為 `$false` 時 live run 可能完成但不驗證 cleanup；
  `snapshot` 或 `trigger-list` live suite 不允許 `-Restore:$false`。

各 target 的 suite 可用性依目前 validation metadata：

- `keysight-e36312a`：`readonly`、`output`、`protection`、`snapshot`、
  `trigger-list`、`software-sequence`、`full`。
- `keysight-edu36311a`：`readonly`、`output`、`protection`、`software-sequence`、
  `full`。
- `keysight-e3646a`：`readonly`、`output`、`software-sequence`、`full`。Live
  validation 目前要求 `-Connection asrl`。
- `gw-instek-psm-2010`：`readonly`、`safe-state`、`output`、`protection`、`snapshot`、
  `software-sequence`、`full`。Live validation 目前要求 `-Connection asrl`。

E3646A 或 PSM-2010 的 RS-232 validation 請設定 ASRL resource 變數並明確傳入：

```powershell
$env:E3646A_ASRL_RESOURCE = "<operator-selected-ASRL-resource>"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\live-cli-check.ps1 `
  -Target keysight-e3646a `
  -Connection asrl `
  -Resource "$env:E3646A_ASRL_RESOURCE" `
  -Suite readonly `
  -PlanOnly
```

E36312A 等 Product-open USB/LAN scope 的 LAN validation，請先設定 LAN resource：

```powershell
$env:E36312A_LAN_RESOURCE = "TCPIP0::...::INSTR"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\live-cli-check.ps1 `
  -Target keysight-e36312a `
  -Connection lan `
  -Resource "$env:E36312A_LAN_RESOURCE" `
  -Suite readonly `
  -PlanOnly
```

若要在 exact registered pending scope 上以已安裝的 optional backend（例如 pyvisa-py）
做 contributor validation，請明確傳入 backend selector。目前 pyvisa-py 的 registered
pending validation scope 是 E36312A 或 EDU36311A 的 TCPIP/LAN，不是 USB：

```powershell
$env:E36312A_LAN_RESOURCE = "TCPIP0::...::INSTR"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\live-cli-check.ps1 `
  -Target keysight-e36312a `
  -Connection lan `
  -Resource "$env:E36312A_LAN_RESOURCE" `
  -Backend "@py" `
  -Suite readonly `
  -PlanOnly
```

Live-validation output 寫在 `.tmp_tests\live_cli_check` 之下：

```text
.tmp_tests\live_cli_check\<timestamp>_<target>_<connection>_<suite>\
```

每次 run 會在 `private\` 保留 private raw validation material，並在 `shareable\`
提供可分享的 artifact set；完成時會印出 shareable `report.json` 與 `summary.md`
路徑。validation report 會記錄 target、connection、backend scope、suite、package
version、Git HEAD、no-hardware plans、executed cases、cleanup evidence 與 result
status。

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

## Ramp 與 Ramp List 文件格式

`ramp` 必須在 `channel` 與 `channels` 之間擇一；多通道選擇會依型號的
canonical channel order 執行，所有所選通道共用相同的 current／voltage path，並以
lockstep 完成 logical voltage step。通道數量不會增加 progress units 或 completion
pulse 次數；每個 logical step 只發一次 pulse。

Ramp List v5 的每個 Segment 使用非空且不重複的 `channels`，不同 Segment 可以選擇
不同通道組合。v2/v3/v4 仍使用單一 `channel` 且可載入與執行；v5 不接受 legacy
`channel`，舊版也不接受 `channels`。Segment pulse 使用該 Segment 第一個 canonical
channel 作為內部 trigger anchor，loop pulse 使用最後一個 Segment 的第一個 canonical
channel；anchor 不會暴露為使用者設定。`enable_output` 對 E3646A 仍遵守全域 output
enable semantics；取消或清理時依既有安全流程處理已啟用的輸出通道。

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

`POST /cancel` 可取消 Ramp、Ramp List、Sequence 與有界 Worker `log`。前三種
workflow 依既有安全清理執行 safe-off；`log` 會完成已開始的 sample cycle、保留
telemetry，正常關閉 session，且不會單純因取消而送出 output OFF。

CLI `powers-tool log` 使用呼叫者指定的 CSV/JSONL 路徑。Worker `log` 是有界、
唯讀、非 output-affecting 的非同步 job，只能在自己的 job directory 寫入
`telemetry.csv` 與 `telemetry.jsonl`；取消或失敗後會保留已寫資料。它不是
background telemetry，也不能和另一個 active Worker job 並行。Sequence action
`log` 仍是 host-side message，`--log-scpi` 則仍是 SCPI traffic tracing。

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

E3646A 在 RS-232/ASRL 上支援唯讀/狀態查詢與輸出工作流程。執行任何 E3646A 實機輸出命令前，請確認實體接線已檢查完成，且要求的電壓/電流限制對連接負載是安全的。

型號支援的命令包括 `identify`、`measure`、`readback`、`read-status`、`output-state`、`capabilities`、`log`、`set`、`apply`、`output-on`、`output-off`、`safe-off`、`cycle-output`、`smoke-output`、`ramp`、`ramp-list` 與影響輸出的 `sequence` 步驟。`verify` 也可作為與型號無關的連線診斷。E3646A 使用 `INST:NSEL` 做通道預選；`OUTP ON/OFF` 是全域輸出啟用/停用行為，即使命令接受通道參數，啟用或停用輸出仍可能影響儀器整體輸出狀態。E3646A 的保護寫入、trigger 工作流程、snapshot restore、completion pulse 與 native LIST 仍維持停用。

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

支援的輸出範例：

```powershell
uv run powers-tool set @Base @Remote --channel 1 --voltage 1 --current 0.05 --json --log-scpi
uv run powers-tool apply @Base @Remote --channel 1 --voltage 1 --current 0.05 --no-output --json --log-scpi
uv run powers-tool output-on @Base @Remote --channel 1 --confirm --json --log-scpi
uv run powers-tool output-off @Base @Remote --channel 1 --json --log-scpi
uv run powers-tool safe-off @Base @Remote --channel 1 --json --log-scpi
uv run powers-tool ramp @Base @Remote --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.25 --current 0.05 --delay-ms 100 --json --log-scpi
uv run powers-tool ramp @Base @Remote --channels 1,2 --start-voltage 0 --stop-voltage 1 --step-voltage 0.25 --current 0.05 --delay-ms 100 --json --log-scpi
```

`ramp` 必須在 `--channel N` 與 `--channels N,N` 之間擇一使用。多通道會依型號的
canonical channel order 執行，所有通道共用相同電流與電壓參數；只有全部通道完成
同一個電壓後，該 logical step 才算完成。既有單通道用法保持相容。

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

影響輸出的命令必須明確要求，且使用前需確認型號、通道、DUT 接線、電壓、電流限制與保護設定。E3646A RS-232 / ASRL 的輸出工作流程屬於目前支援範圍；執行前請確認實體接線已檢查完成，且要求的電壓/電流限制對連接負載是安全的。詳細範例請參考英文 README 與 CLI 使用者指南。

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
- E3646A 在 RS-232 / ASRL 上保留唯讀與狀態查詢工作流程，並支援輸出工作流程。
- `--safety-config` 只會套用本機 plan validation 限制；它不會自動啟用硬體輸出。
- 真實 VISA resource 不應硬編碼在提交的檔案中。
- 硬體測試必須要求使用者提供 resource。
- 啟用輸出的範例必須設定安全的 current limit，並在清理時關閉輸出。
