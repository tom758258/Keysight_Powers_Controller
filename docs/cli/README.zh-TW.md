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

操作員工作流程請參閱 [CLI 使用者指南](USER_GUIDE.zh-TW.md)。

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
- `powers_tool_cli.commands.manifest`：static `manifest` tool introspection，
  回報工具身分、package version 與 Worker protocol 相容性；不接觸 VISA、
  Worker runtime 或 HTTP，也不建立 filesystem output。
- `powers_tool_cli.commands.output_run`：output command execution、dry-run
  planning 與 output result adapter。
- `powers_tool_cli.commands.trigger_run`：共用 Trigger request/configuration
  validation 與 result-payload helper。Active Trigger execution 由
  `powers_tool_core.trigger` 負責。
- `powers_tool_cli.commands.sequence_run`：ramp-list workflow handler 與
  shared sequence/Trigger compatibility helper。Sequence planning 與 execution
  由 `powers_tool_core.sequence` 負責。
- `powers_tool_cli.commands.lifecycle`：Worker lifecycle parser registration。
- `powers_tool_cli.commands.output`：output command parser registration、runner
  adapter 與 JSON request-envelope mapping。
- `powers_tool_cli.commands.ramp_list`：獨立的 Ramp List parser registration 與
  request-envelope mapping。
- `powers_tool_cli.commands.sequence`：sequence command registration 與 CLI
  request conversion。
- `powers_tool_cli.commands.trigger`：Trigger parser registration、runner adapter
  與 Trigger JSON request-envelope mapping。

Parser construction 使用明確的 runner callable。各 command family module 直接從
`powers_tool_cli.cli_parser` 匯入共用 argparse primitives，且只接收自己的 execution
callback；解析後的 `argparse.Namespace` 不會攜帶 top-level `powers_tool_cli.cli`
module 或其他 service-locator object。各 module 負責自己的 handler、parser
registration 與 request mapping；`cli.py` 是 composition root，而非 re-export facade。

CLI 負責參數解析、request mapping、文字與 machine rendering、JSON/JSONL
envelope、exit-code mapping 與 top-level composition；上述三個 root handler
仍由 `cli.py` 實作。Core 負責 IDN/model
resolution、capability metadata、exact live-support admission、driver selection
與 model-specific execution。`validate-readonly` 使用窄的
`powers_tool_core.readonly.run_validate_readonly()` adapter boundary；不將它加入
`COMMAND_CONTRACTS` 或共用 command routing。支援既有 command contract 的 model
應整合在 Core，不需要在 CLI 增加 concrete driver branch。

`measurement_cli_name` 等 CLI-only fields、解析後的 `argparse.Namespace` 值、command
aliases 與 adapter error text 都是 CLI adapter concerns，不屬於 Core schema。

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
`--backend "@bt"` 的 model-aware Product live execution 會 fail closed。封裝後的
`powers-tool.exe` 不會 bundle pyvisa-py、`pyvisa_bt` 等 optional Python
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

`powers-tool manifest --json` 提供純靜態的 tool introspection，供 orchestrator
在不接觸儀器的情況下靜態確認工具本身：

```powershell
powers-tool manifest --json
```

成功時輸出單一 JSON object，回報 `tool_id`、package version（`tool_version`）
與 Common Worker Protocol schema 相容性。此命令不列舉或開啟 VISA resource、
不查詢 `*IDN?`、不啟動 Worker 或 HTTP server，也不會建立檔案或目錄；欄位語意
請參閱 [Power CLI JSON / JSONL 契約](../contracts/power-cli-jsonl-contract.md)。

## 命令系列索引

以下是快速導覽，不取代 `powers-tool --help` 或下方詳細範例。

| Family | Purpose | Representative commands | Details |
| --- | --- | --- | --- |
| 安裝與診斷 | 安裝、探索、身分、錯誤與安全檢查。 | `powers-tool --version`、`doctor`、`manifest`、`list-resources`、`verify`、`identify`、`error`、`clear` | [資源搜尋與實機資源設定](#資源搜尋與實機資源設定)；[Power CLI JSON / JSONL 契約](../contracts/power-cli-jsonl-contract.md)；`powers-tool --help` |
| 唯讀與狀態 | measurement、readback、output state、capabilities、儀器狀態與有界 telemetry。 | `measure`、`measure-all`、`read-status`、`readback`、`output-state`、`capabilities`、`log` | [唯讀指令範例](#唯讀指令範例)；`read-status` 是儀器命令。 |
| Setpoint 與 output control | 設定點、輸出切換、safe-off 與受保護的輸出操作。 | `set`、`apply`、`output-on`、`output-off`、`safe-off`、`cycle-output`、`smoke-output` | [會影響輸出的範例](#會影響輸出的範例)；[Safety Defaults](#safety-defaults) |
| Output workflows | ramp、ramp-list 與 software sequence。 | `ramp`、`ramp-list`、`sequence` | [Ramp、Sequence 與模擬器範例](#ramp-與-sequence-範例)；[Safety Defaults](#safety-defaults) |
| Protection | protection status、設定與清除。 | `protection-status`、`protection-set`、`clear-protection` | [Protection 與 Trigger 範例](#protection-與-trigger-範例)；`powers-tool --help` |
| Trigger | trigger status、setup、fire、abort、pulse 與 LIST workflow。 | `trigger-status`、`trigger-step`、`trigger-list`、`trigger-fire`、`trigger-abort`、`trigger-pulse` | [Protection 與 Trigger 範例](#protection-與-trigger-範例)；仍受 exact feature scope 約束。 |
| Snapshot 與 restore | 擷取、比較、報告與還原儲存的儀器狀態。 | `snapshot`、`snapshot-diff`、`hardware-report`、`restore-from-snapshot` | [Snapshot 與 Restore 範例](#snapshot-與-restore-範例)；[Power CLI JSON / JSONL 契約](../contracts/power-cli-jsonl-contract.md) |
| Worker 與 automation | 本機 Worker lifecycle 與 command submission。 | `worker`、`send-command`、`status`、`stop`、`wait-ready` | [Power Worker Daemon](#power-worker-daemon)；[Power Worker 契約](../contracts/power-worker-contract.md)。`status` 是 Worker lifecycle status；儀器狀態使用 `read-status`。 |

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
`test_cli_output_commands.py`）。CLI 解析器測試（`tests/cli/test_cli_parser.py`）
包含 Core → CLI command completeness drift guard，確保 `COMMAND_CONTRACTS`
中的所有正式 Core 指令皆存在於 CLI 的 `COMMAND_NAMES` 清單中。
共用 CLI test helpers 位於 `tests/cli/cli_test_helpers.py`。

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

#### 建置入口 (Build entry points)

以下是公開建置入口；詳細用法維護於根目錄的 [README](../../README.zh-TW.md)：

- `scripts\build_desktop.ps1`
- `scripts\build_windows_bundle.ps1`
- `scripts\build_release.ps1`

正式 Windows release 使用 `scripts\build_release.ps1` 產生的 unified Desktop ZIP。

#### CI 品質工具

以下腳本支援 CI 品質檢查，不是獨立的 validation 入口：

- `scripts/check_text_hygiene.py` 檢查 tracked public text 的 UTF-8、BOM、
  replacement character 與 mojibake hygiene 問題。
- `scripts/check_changed_whitespace.py` 檢查 GitHub Actions event range 內的
  whitespace 錯誤。它依賴 CI event SHA environment variables，不是一般本機
  standalone 命令。

完整的 Product-open command inventory 以
[Product LIVE exact-scope matrix](../core/supported-models.md#product-live-exact-scope-matrix)
為準。只有該 matrix 中明確列出的 commands 才會在對應 connections 上開放一般 LIVE
使用。E3646A 與 PSM-2010 的 live use 仍限於 ASRL / RS-232 + system VISA；兩者的
USB 與 LAN 路徑不在目前 scope 內。PSM-2010 對 Core Product matrix 所列的 23 個
model-aware commands 維持 Product-open。
Sequence actions 與 Trigger Step/List sources 也是 exact feature-policy 要求。
一般 CLI Product mode 下，缺少或 pending 的 feature entries 維持關閉；
Product-open command 不代表未註冊的 action 或 source 也開放。CLI model list
僅包含 Product-active models。

### Optional Hardware Pytest

live smoke script 是操作員驗收時的正常硬體 OK gate。只有在需要更深的可重複硬體
regression、變更的功能有對應的硬體測試，或要驗證 smoke script 之外的 SCPI、
trigger、protection-setting 或刻意保護觸發行為時，才執行 hardware pytest。

Hardware integration tests 在未明確傳入 resource 時不會執行。若需要更深層的
hardware pytest，請先執行 read-only 硬體套件：

```powershell
uv run python -m pytest tests\integration -q -m hardware --resource "$env:E36312A_USB_RESOURCE" --expected-model E36312A
```

影響輸出的 hardware pytest 另外要求 `--run-output`：

```powershell
uv run python -m pytest tests\integration -q -m hardware_output --resource "$env:E36312A_USB_RESOURCE" --expected-model E36312A --run-output
```

需要時可加 `--backend "@ivi"`。任何影響輸出的執行前，請確認預期儀器、斷開未知
DUT，並確認要求的 voltage/current 是安全的。

## Planning Identities 與 Live Expected-Model Guards

Output-family commands、`ramp-list`、`sequence`、`protection-set`、
`clear-protection` 與 trigger workflows 在 `--dry-run` 與 `--simulate` 模式下使用
嚴格的 model resolution。在這些 no-hardware planning 路徑中，`--model` 提供
canonical physical planning ID，例如 `keysight-e36312a`。受支援的 dry-run commands
另提供 `--profile generic-scpi` 作為分開的 nonphysical planning。兩個欄位互斥。
Simulator mode 只接受 physical planning model 或已知的 deterministic simulator
resource，例如 `USB0::SIM::E36312A::INSTR`。Trigger no-hardware 路徑僅限 E36312A，
且需要 `--model keysight-e36312a` 或已知的 deterministic E36312A SIM resource。CLI
不會從任意的 fake、live-looking 或 alias-only resource 字串推測 model。

範例：

```powershell
uv run powers-tool set --dry-run --model keysight-e3646a --channel 1 --voltage 1 --current 0.05
uv run powers-tool readback --simulate --resource USB0::SIM::E36312A::INSTR --channel all
uv run powers-tool trigger-step --dry-run --model keysight-e36312a --channel 1 --source bus --fire
```

以下會被拒絕，因為 fake resource 只是 placeholder，不得暗示 model：

```powershell
uv run powers-tool trigger-step --dry-run --resource USB0::FAKE::E36312A::INSTR --channel 1 --source bus --fire
```

Deterministic SIM resources 會被接受，因為它們對應到已知的 simulator IDN/model
data。

在 live 模式下，`--model` 是 expected-model guard。CLI 開啟明確指定的 resource、
查詢 `*IDN?`、解析 manufacturer 加 model，並要求 canonical 偵測結果的 `model_id`
相符後才送出 command-specific SCPI。被選擇的 model 永遠不會覆寫由 IDN 偵測出的
driver。

不支援的 model、command 與 mode 失敗是刻意設計的 feature-lock 行為。`--model`
不是 feature unlock：在 dry-run/simulate 模式它只選擇 physical planning identity，
在 live 模式它只檢查連線到的 canonical identity 是否符合預期。`generic-scpi` 只有
在既有 support matrix 允許處透過 dry-run `--profile` 提供。

Live guard 範例：

```powershell
uv run powers-tool set --model keysight-e36312a --resource "$env:POWER_USB_RESOURCE" --channel 1 --voltage 1 --current 0.05
```

這要求連線儀器的 `*IDN?` model 必須是 `E36312A`。

接受的 physical planning IDs 由 Core Product-active metadata 定義，並記錄於
[Supported Models](../core/supported-models.md)。在 `--simulate` 模式下，`--model`
可以推導出對應的 deterministic simulator resource。獨立的 `generic-scpi` profile
僅限 dry-run，不是 live expected model。若同時提供 `--model` 與 SIM resource，
兩者的 model 必須相符。不支援的 models（包括 EDU36311A）不會暴露 trigger dry-run
或 simulator 行為。

No-hardware plans 會區分 `planning_model_id` 與 `planning_profile_id`。Channel
validation 與 `--channel all` 展開使用解析出的 planning identity：E3646A 將 `all`
展開為 CH1 與 CH2 並拒絕 CH3；PSM-2010 使用 CH1；E36312A 與 EDU36311A 展開為
CH1、CH2、CH3；`generic-scpi` 保守允許 CH1。

Trigger/native LIST workflows 僅限 E36312A。EDU36311A 支援 read-only、output 與
protection workflows，但 trigger/native LIST、`snapshot` 與 `restore-from-snapshot`
在 live、simulate 與 dry-run 都停用。E3646A 支援 RS-232 read-only/output workflows
加上軟體 `ramp-list` 與 step-limited 軟體 `sequence`；這些不是 native LIST 支援，
且會拒絕不受支援的 protection、trigger、snapshot、restore、native LIST 與
completion-pulse sequence steps。E36103B 與 E36232A 不是 active supported models，
會被當作 planning models 與 live expected-model guards 拒絕。若 live `*IDN?` 回報
其中之一，model-aware commands 會拒絕該儀器而不是 fallback 到
`GenericScpiPowerSupply`；`verify` 與 `list-resources --live-only` 仍可作 diagnostic
回報 raw IDN。

真實 CLI measurement 讓 generic instruments 固定使用 channel 1。E36312A 與
EDU36311A 的 channel 2 與 3 使用由 IDN 選擇的 channel-list measurement queries。
真實 CLI `set` 支援 E36312A 與 EDU36311A 的 channels 1、2、3，以及 E3646A
RS-232 / ASRL 的 channels 1、2。它接受 `--voltage`、`--current` 或兩者。省略的
設定點保持不變；同時提供兩者時，先寫 current limit 再寫 voltage。它不會啟用輸出。

對所有 active models，`--voltage` 是輸出電壓設定點，`--current` 是輸出電流限制／
電流設定值。Core 公布來自 model manuals 的官方 programming-range metadata：
E36312A 與 EDU36311A 使用固定通道範圍，E3646A 則有 LOW/P8V 與 HIGH/P20V 的
range-dependent voltage/current-limit ranges。此 metadata 不會新增 CLI range
selector，不會靜默 round 或 truncate setpoints，也不實作硬性小數位數拒絕。

Product LIVE support 以 command 為單位，不是整個 feature family。請參閱
[Product LIVE exact-scope matrix](../core/supported-models.md#product-live-exact-scope-matrix)。
`output-on`、`measure-all`、`trigger-pulse`、`trigger-fire`、`log`、resource-backed
`doctor` 與 `restore-from-snapshot` scopes 只在該 matrix 文件化的 exact
model/transport/system-VISA 組合下 Product-open；其他組合維持 fail-closed。
`set`、`output-off`、`safe-off`、`apply`、`ramp` 等 accepted commands，以及
model-appropriate 的 read/protection/trigger commands，仍需要 exact accepted 的
model/transport/backend scope。

一般 CLI 操作一律使用 product live-support policy。Pending transport/backend 或
feature scope 不是正常 product support，也沒有公開的 force option。不支援的 model、
command、connection、backend 或 feature 組合都會 fail closed。CLI 不會繞過 IDN
selection、expected-model checks、request validation、safety limits、confirmations
或 model feature locks。

`list-resources`、`verify`、`clear`、`error`、`measure`、`identify`、
`protection-status`、`protection-set`、`clear-protection` 與 `snapshot` 現在透過共用的
Core runners 執行。CLI 仍擁有 argparse 處理、人類可讀文字輸出、JSON success/error
envelope、`--save-json` 與 exit-code mapping。

`snapshot` 產生 schema-2 `powers-tool-snapshot` 文件，`reported_identity` 下保留原始
manufacturer/model/serial/firmware，並在 `resolved_identity` 下提供 canonical 的
`vendor_id`／`model_id`。`restore-from-snapshot` 只接受該版本化文件；legacy、未版本化
與任意 CLI-envelope 文件都會被拒絕。`snapshot --snapshot-json PATH` 寫入原始保存的
snapshot，而 `--json --save-json PATH` 寫入完整 CLI schema-2 envelope；同時使用兩個
選項時路徑必須不同。Core 不會從單獨的 reported model 字串還原 model identity。

Restore 對所有與 restore 相關的持久化欄位做驗證，不做強制轉型。Channels 必須是正整數、
output 與 OCP 狀態必須是 JSON boolean、setpoints 必須是有限數值。諸如 `"false"` 的值會
被拒絕，而不是被視為啟用或停用。`outputs`、`readback` 與 `protection_settings` 必須
非空且包含完全相同的 channels；即使 protection record 的所有選用保護值都是 null，
該 record 仍然必要。不完整的文件會被拒絕，而不是部分還原。CLI `--channel 1` 會在
Core validation 前解析為整數，而 raw Core/JSON 數字字串會被拒絕；exact `--channel all`
仍僅供支援全通道選擇的命令使用。

`snapshot --compare PATH` 會將目前 E36312A snapshot 與 schema-2 snapshot 文件（直接
提供或作為已存 CLI envelope data）比較。它忽略 `resource` 與 `read_count`，對
programmed setpoints 使用預設容差 0.001 V/A、measured voltage 0.05 V、measured
current 0.01 A，並在有差異時以 exit code `3` 結束。

`ramp` 接受 `--channel N` 或 `--channels N,N` 擇一。所有所選通道共用相同的 current
與 voltage 參數，並依 canonical channel order 以一個 lockstep logical voltage step
前進。既有單通道形式保持不變。Ramp 先設定 current limit，再從 `--start-voltage`
步進到精確的 `--stop-voltage`；除非提供 `--enable-output`，否則不會開或關輸出，且一律
使用軟體設定點步進。E3646A 與 EDU36311A 的真實 `ramp` 不支援 completion-pulse
options。`set`、`apply`、`output-on`、`output-off` 與 `ramp` 接受 `--settle-ms` 與
`--verify-after-write`；驗證失敗會回傳 JSON error code `verification_failed` 並以
exit code `3` 結束。

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

`ramp-list` 會透過單一 VISA session 執行 1 到 10 個有序的軟體設定點 ramp segments。
它會在第一次硬體寫入前驗證完整版本化 JSON 文件與所有產生的設定點。預設不啟用也不
停用輸出；明確的 `enable_output: true` 會對每個 workflow channel 啟用一次。它不使用
native LIST，一般執行失敗時也不會自動 safe-off。
Ramp `--completion-pulse-timing segment` 在每次完整 Ramp iteration 後發一次脈波；
`--completion-pulse-timing step` 在每個 logical voltage step 後發一次；
`--completion-pulse-timing loop` 在所有成功 iterations 後發一次。Every-step timing
接受 `--delay-ms 0`。後面板脈波腳位不是輸出通道。Pulse workflows 僅限 E36312A，
且 `*TRG` 可能影響其他已 armed 的 BUS-triggered 行為。

Ramp 與 inline Ramp List 接受 `--enable-output`。Ramp 會在啟用並驗證輸出前先寫入
current 與第一個 voltage。Ramp List 只在每個通道的第一個 segment 啟用該通道。正常
完成時這些輸出維持 ON；省略此選項則保留原本輸出狀態。

`ramp`、`ramp-list` 與 `sequence` 接受 `--loop-count N`，N 是總執行次數，且必須是
1 到 10,000 的 strict integer。明確的 CLI 值覆蓋文件值；否則使用文件值，再退化為 1。
Ramp List v2/v3 與 Sequence v1 隱含 1。

Ramp List version 2 以 `enable_output: false` 與單次 iteration 語意繼續被接受。
Version 3 要求 `enable_output` 並隱含單次 iteration。Version 4 要求 exact 的
`enable_output` 與 `loop_count` 欄位，且可包含 global `completion_pulse` 物件。
這些版本的每個 Segment 使用一個 `channel`。Version 5 是最新格式，要求 `channels`、
`enable_output` 與 `loop_count`；`channels` 是非空、由唯一正整數組成的清單。
Version 1、格式錯誤值、未知欄位與未來版本都會被拒絕，沒有 fallback。Inline 的
`--segment CHANNEL ...` 語法不變，但會以 `channels: [CHANNEL]` 建 v5 並明確保存
`loop_count`（包括 1）。

Core 將 Ramp、Ramp List 與 Sequence 限制在 1,000,000 個 logical execution units。
CLI 會在文字模式執行前印出 execution summary，超過 100,000 units 時警告；JSON 結果
使用既有 warnings 欄位。長時間 run 可能只保留前 100 與後 100 筆 result details，
同時保留完整 aggregate counters 與 truncation metadata。
`--file` 只從文件取得 `enable_output`，不能與 CLI flag 併用。Inline 用法接受
`--completion-pulse-timing`、`--completion-pulse-pins` 與 `--completion-pulse-polarity`；
使用 `--file` 時以文件為準，CLI pulse override 會被拒絕。

```powershell
$env:POWERS_TOOL_RESOURCE = "USB0::...::INSTR"
uv run powers-tool ramp-list --lint --json --file example.ramp-list.json
uv run powers-tool ramp-list --dry-run --json --model keysight-e36312a --file example.ramp-list.json
uv run powers-tool ramp-list --json --resource "$env:POWERS_TOOL_RESOURCE" --segment 1 0.1 0 1 0.1 100 0 --segment 2 0.05 0 2 0.2 50 500
```

## Power Worker Daemon

Power Worker 以 machine mode 提供本機 lifecycle 與 command submission。`GET /status`
只代表 control-plane health/progress，不是儀器 `read-status`；`POST /command` 的
accepted／HTTP `202` 只代表 job 已接受或進入 queue，不代表 domain command 已完成。
files mode 必須依 contract 等待 terminal `result.json`，並確認
`status: "succeeded"`、`ok: true`、`run_id` 與 `worker_job_id` correlation 正確；
memory mode 不會建立 `result.json`，應改由 terminal stdout JSONL event，及／或
`GET /status` 的 `last_job` 取得 terminal result。

Worker JSON/JSONL stdout 只輸出 machine evidence；human-readable stdout/stderr
只能作 diagnostic。`ready` 不代表 domain command 完成，`request.json` 只證明
files mode 的 request 已持久化，不代表 command 完成。請依
[Power Worker 契約](../contracts/power-worker-contract.md) 與
[Power Orchestrator 工作流程](../contracts/power-orchestrator-workflows.md) 觀察
完整生命週期。

以 dynamic port 啟動 simulator Worker：

```powershell
uv run powers-tool worker --id power_1 --mode simulate --control-port 0
```

Worker request 必須使用 top-level `context`。Mode 與 identity 分別使用
`context.mode`、`context.planning_model_id`、`context.expected_model_id` 與
`context.planning_profile_id`；這些欄位放在 `arguments` 會被拒絕，identity fields
放在 settings 也會被拒絕。Deterministic SIM resource 必須符合明確指定的 physical
planning model；Worker 不提供 identity default。`send-command` client 使用
`--context-json` 傳遞相同的 context object。

`POST /stop` 是 cooperative：handler 只設定 stop state 並喚醒 runner，不在 HTTP
handler thread 執行 VISA I/O、cleanup 或 server shutdown。Worker 會等 runner 完成
安全清理後，才送出 final `summary` 並停止 HTTP server；stop acknowledgment 不代表
cleanup 或 shutdown 已完成。

`POST /cancel` 是固定的 job-specific cancellation endpoint，要求 schema 2 與 exact
active `worker_job_id`；missing、stale 或 mismatched identity 會 fail closed。它可取消
Ramp、Ramp List、Sequence 與有界 Worker `log`，但不會關閉 Worker。前三種 workflow
依既有安全清理執行 safe-off；`log` 會完成已開始的 sample cycle、保留 telemetry，
正常關閉 session，且不會單純因取消而送出 output OFF。`/stop` 則維持關閉整個
Worker 的語意。

CLI `powers-tool log` 使用呼叫者指定的 CSV/JSONL 路徑。Worker `log` 是有界、
唯讀、非 output-affecting 的非同步 job。在 `files` mode，它會在自己的 job
directory 寫入固定的 `telemetry.csv` 與 `telemetry.jsonl`，並在取消或失敗後
保留已完成的 telemetry evidence。在 `memory` mode，它不建立 telemetry files；
每筆 telemetry row 會以 schema-2 `sample` stdout JSONL event 輸出，terminal
result 只保留 bounded summary。它不是 background telemetry，也不能和另一個
active Worker job 並行。Sequence action `log` 仍是 host-side message，
`--log-scpi` 則仍是 SCPI traffic tracing，而非 telemetry。

Worker 預設為 file-backed（`--artifact-mode files`）：啟動時建立 artifact 目錄與
`events.jsonl`，每個 accepted job 在 `jobs/<worker_job_id>/` 寫入 `request.json`
與 `result.json`。Orchestrator 可明確選用 `--artifact-mode memory`：啟動不建立
任何 artifact 目錄、事件檔或 request/result/telemetry 檔案；accepted 回應省略
`artifact_path`；終端事件 `job_finished`／`job_failed`／`job_cancelled` 與
`GET /status` 的 `last_job` 直接帶入完整 result envelope；`log` 的每筆
telemetry row 改以 schema-2 `sample` stdout JSONL 事件輸出。memory 模式會拒絕
明確的 `--events-jsonl`，因為 stdout 是唯一事件流。詳細欄位語意請參閱
[Power Worker 契約](../contracts/power-worker-contract.md)。

Worker 啟動後會在 stdout 輸出 `ready` event，包含 dynamic control endpoints；該事件
只表示 control plane 可用，不是任何 domain command 的 terminal completion。

執行 maintained simulator-only orchestrator smoke example：

```powershell
.\examples\worker_orchestrator_smoke.ps1
```

## 範例

### 資源搜尋與實機資源設定

僅列出可以被開啟並透過 `*IDN?` 查詢的 VISA 資源：

```powershell
uv run powers-tool list-resources --live-only
```

一般 live 操作請使用此形式。文字輸出會包含每個 resource 的原始 IDN 回應，因此能看見
儀器型號。加上 `--log-scpi` 可顯示每次 live check 的驗證 query 與回應。

列出所選 backend 回報、但不開啟的 VISA resource 字串：

```powershell
uv run powers-tool list-resources
```

這只是被動探索：即使儀器目前不可連線，resource string 仍可能出現。

以下實機 USB 範例請先在 PowerShell 工作階段設定 VISA 資源一次：

```powershell
$env:POWERS_TOOL_RESOURCE = "USB0::...::INSTR"
```

### Generic USB Live Examples

驗證單一資源可被開啟並透過 `*IDN?` 查詢：

```powershell
uv run powers-tool verify --resource "$env:POWERS_TOOL_RESOURCE"
uv run powers-tool verify --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
```

以 `*CLS` 清除儀器狀態與 error queue：

```powershell
uv run powers-tool clear --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
```

在不改變輸出狀態下讀取儀器 error queue：

```powershell
uv run powers-tool error --resource "$env:POWERS_TOOL_RESOURCE" --max-reads 20 --log-scpi
```

### E3646A RS-232 / ASRL 範例

E3646A 的 Product LIVE support 僅限 ASRL/RS-232 + system VISA。其 exact
product-open model-aware commands 為 `measure`、`readback`、`read-status`、
`output-state`、`capabilities`、`log`、`set`、`apply`、`output-off`、`safe-off`、
`cycle-output`、`smoke-output`、`ramp`、`ramp-list`、`sequence`、`output-on`，以及
resource-backed `doctor`。`identify` 與 `verify` 僅是 diagnostics。Protection、
trigger、snapshot/restore、completion pulses 與 native LIST 不是 product-open。
`ramp-list` 是軟體設定點步進，`sequence` 是受支援 output/read-only steps 的
step-limited 軟體工作流程；兩者都不是 native LIST。

型號使用 `INST:NSEL` 做通道預選；`OUTP ON/OFF` 是全域輸出啟用/停用行為，
即使命令接受通道參數，啟用或停用輸出仍可能影響儀器整體輸出狀態。
E3646A `sequence` 只接受受支援的 read-only/output steps；protection、trigger、
snapshot、restore、native LIST 與 completion-pulse step types 會被目前 feature-lock
policy 拒絕。

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

單純的 resource discovery 不需要 serial options：

```powershell
uv run powers-tool list-resources
```

Serial settings 只在明確提供時生效。省略時，CLI 不會覆寫 VISA backend、Keysight IO
Libraries Suite 或 Connection Expert 的 serial 設定；提供時也只有提供的欄位會套用到
ASRL resources。E3646A 出廠範例為 9600 baud、8 data bits、none parity、2 stop bits
與 DTR/DSR handshake，但實際儀器面板設定可能不同：

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

序列終止字元請優先使用別名 `CR`、`LF`、`CRLF` 或 `NONE`。`NONE` 表示不設定該
終止字元選項；省略或空白欄位也表示不覆寫 VISA 設定。自訂原始字串仍被接受，但
PowerShell 可能把 `\r` 之類的值當成字面反斜線加 `r` 傳入；需要實際控制字元時請使用
別名。

### PSM-2010 RS-232 / ASRL Scope

PSM-2010 的 Product LIVE support 僅限 ASRL/RS-232 + system VISA。其 exact
model-aware scope 包含 Core Product matrix 所列的 23 個 commands，涵蓋
setpoint／output、protection、snapshot／restore、ramp 與 software sequence
workflows。Powers Trigger commands 與 OCP delay 設定／讀回／trigger 仍不支援。
USB、TCPIP、GPIB、pyvisa-py、pyvisa-bt 與 custom VISA scopes 維持關閉。

### 唯讀指令範例

量測 voltage 與 current：

```powershell
uv run powers-tool measure --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --log-scpi
uv run powers-tool measure --resource "$env:POWERS_TOOL_RESOURCE" --channel 2 --log-scpi
```

預覽 no-hardware 的全通道量測，並讀取 product-open 的 live 狀態：

```powershell
uv run powers-tool measure-all --simulate --json --resource USB0::SIM::E36312A::INSTR
uv run powers-tool read-status --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
```

對 E36312A 或 EDU36311A 執行完整 read-only validation：

```powershell
uv run powers-tool validate-readonly --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi --save-json logs\validate-readonly.json
```

讀取 E36312A 已程式化的設定點與保護狀態：

```powershell
uv run powers-tool readback --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
uv run powers-tool protection-status --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
```

E36312A 與 EDU36311A 的 `protection-status` 會逐通道讀取 OVP/OCP trip flags。既有
aggregate flags 仍然可用，並以所選通道結果的 OR 計算。

### Snapshot 與 Restore 範例

擷取 restore 可消費的原始 E36312A snapshot，接著進行比較：

```powershell
uv run powers-tool identify --json --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
uv run powers-tool snapshot --resource "$env:POWERS_TOOL_RESOURCE" --snapshot-json logs\before.json --log-scpi
uv run powers-tool snapshot --json --resource "$env:POWERS_TOOL_RESOURCE" --compare logs\e36312a-baseline.json
uv run powers-tool snapshot-diff --summary --json --before logs\before.json --after logs\after.json
```

預覽 restore plan 並在不開啟 VISA 下儲存 plan data：

```powershell
uv run powers-tool restore-from-snapshot --dry-run --json --snapshot logs\before.json --resource USB0::SIM::E36312A::INSTR --channel all --plan-json logs\restore-plan.json
```

### Protection 與 Trigger 範例

預覽或執行 E36312A 保護操作：

```powershell
uv run powers-tool clear-protection --dry-run --json --model keysight-e36312a --all
uv run powers-tool clear-protection --json --resource "$env:POWERS_TOOL_RESOURCE" --all --confirm --log-scpi
uv run powers-tool protection-set --dry-run --json --model keysight-e36312a --channel all --ovp-voltage 5 --ocp on
uv run powers-tool protection-set --dry-run --json --model keysight-e36312a --channel 1 --ocp-delay 0.5 --ocp-delay-trigger setting-change
uv run powers-tool protection-set --json --resource "$env:POWERS_TOOL_RESOURCE" --channel all --ovp-voltage 5 --ocp on --confirm --log-scpi
```

將 E36312A 後面板數位腳位設定為 trigger 輸出，對一個輸出通道 arm 不改變設定的 STEP
trigger sequence，並送出 `*TRG`：

```powershell
uv run powers-tool trigger-pulse --dry-run --json --model keysight-e36312a --pin 1 --channel 1 --polarity positive
```

使用 `--dry-run --model keysight-e36312a` 或 deterministic E36312A SIM resource 可在
不開啟 VISA 下預覽 trigger SCPI。Trigger dry-run 與 simulator 行為僅限 E36312A；
不支援的 model 不會暴露 trigger no-hardware 行為。最後的 `*TRG` 也可能觸發其他已
armed 的 BUS-triggered 行為。`trigger-pulse` 只在文件記載的 exact scope 內（E36312A
USB/TCPIP + system VISA）Product-open。accepted commands 的 live trigger 行為仍由
IDN 決定；live `--model` 只要求連線 IDN model 相符，永遠不會覆寫連線的硬體。

原生 E36312A trigger/LIST commands：

```powershell
uv run powers-tool trigger-status --json --resource "$env:POWERS_TOOL_RESOURCE" --channel all
uv run powers-tool trigger-step --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --source bus --fire --wait-complete
uv run powers-tool trigger-list --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --voltage-list 0,1 --current-list 0.05 --dwell-list 0.01 --completion-pulse-pins 1 --fire --wait-complete
uv run powers-tool trigger-list --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --voltage-list 0,1 --current-list 0.05 --dwell-list 0.01 --bost-list on,off --eost-list off,on --trigger-output-pins 1 --source immediate --wait-complete
uv run powers-tool trigger-fire --dry-run --json --model keysight-e36312a --channel 1 --wait-complete
uv run powers-tool trigger-abort --json --resource "$env:POWERS_TOOL_RESOURCE" --channel all
```

原生 BUS triggers 的 `trigger-step` 與 `trigger-list` 預設只 arm；加上 `--fire` 才會
在同一命令內送出 `*TRG`。BUS 的 `--wait-complete` 需要 `--fire`。Immediate source 在
送出 `INIT` 時啟動，並拒絕 `--fire`。Arm-only LIST 需要 `--leave-trigger-configured`；
沒有 `--wait-complete` 就啟動的 LIST 也需要它，否則 restore 會中止該 LIST。Trigger
Step 保留既有非等待行為。`trigger-fire` 只有搭配 `--wait-complete` 時才需要
`--channel N`；它選擇全儀器完成等待逾時或被中斷時要 abort 的輸出通道，但不限制
`*TRG` 或完成等待的範圍。`trigger-fire` 與 `trigger-pulse` 對其他 model、transport
或 backend 維持關閉。
Canonical Trigger LIST files 與 flags 接受 per-step 的 `bost_list` 與 `eost_list`，
以及 `trigger_output_pins` 與 `trigger_output_polarity`。啟用的脈波需要明確的輸出
腳位。Legacy `--completion-pulse-pins` 仍代表最後一步的 EOST pulse，且不能與 canonical
欄位混用。完成的 wait 會還原執行前的 Trigger settings 與 LIST table，除非選擇
`--leave-trigger-configured`。

### 會影響輸出的範例

在不啟用輸出下設定較低的 E36312A、E3646A 或 EDU36311A 設定點：

```powershell
uv run powers-tool set --model keysight-e36312a --resource "$env:POWER_USB_RESOURCE" --channel 1 --voltage 1 --current 0.05
uv run powers-tool set --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --voltage 1 --current 0.05 --log-scpi
uv run powers-tool set --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --voltage 1 --log-scpi
```

第一個範例以 `--model keysight-e36312a` 作為 live expected-model guard：在任何
setup/write SCPI 前，要求連線的 `*IDN?` model 必須是 E36312A。

真實 `set` 會先以 `*IDN?` 確認所選 resource 是 E36312A、E3646A 或 EDU36311A，然後只寫入
要求的設定點欄位。E3646A 使用 channels 1、2 搭配 `INST:NSEL` 預選；E36312A 與
EDU36311A 使用 channels 1、2、3。

在沒有硬體的情況下預覽 `output-on`：

```powershell
uv run powers-tool output-on --dry-run --json --model keysight-e36312a --channel 1
uv run powers-tool output-on --simulate --json --resource USB0::SIM::E36312A::INSTR --channel all
```

`output-on` 只在 E36312A 與 EDU36311A 的 USB/TCPIP + system VISA，以及 E3646A 的
ASRL + system VISA 下 Product-open。其他 scope fail closed。E3646A 在程式化兩個通道後
使用一個全域輸出開關，不是獨立的 per-channel output relay。

讀回並循環輸出狀態：

```powershell
uv run powers-tool output-state --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --log-scpi
uv run powers-tool cycle-output --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --duration-ms 500 --confirm --log-scpi
uv run powers-tool cycle-output --json --resource "$env:POWERS_TOOL_RESOURCE" --channel all --duration-ms 500 --confirm --log-scpi
```

`cycle-output --channel all` 會依序啟用 channels 1、2、3，等待一次 `--duration-ms`，
再依序停用 channels 1、2、3。

套用低設定點並啟用輸出：

```powershell
uv run powers-tool apply --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --voltage 1 --current 0.05 --confirm --log-scpi
uv run powers-tool apply --json --resource "$env:POWERS_TOOL_RESOURCE" --channel all --voltage 1 --current 0.05 --confirm --log-scpi
uv run powers-tool apply --json --resource "$env:POWERS_TOOL_RESOURCE" --channel all --voltage 1 --current 0.05 --no-output --log-scpi
```

加入明確的 safety config，將本機全域限制套用到輸出 plans：

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

Resource-specific 欄位會逐項覆蓋 global `[safety]` 欄位。符合某個
`[[resources]].resource` entry 的原始 `--resource` 也會取得該 entry 的
resource-specific limits；否則適用 global `[safety]` limits。

### Ramp 與 Sequence 範例

不改變輸出狀態下 ramp 電壓設定點：

```powershell
uv run powers-tool ramp --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.25 --current 0.05 --delay-ms 100 --verify-after-write --settle-ms 200 --log-scpi
uv run powers-tool ramp --json --resource "$env:POWERS_TOOL_RESOURCE" --channels 1,2 --start-voltage 0 --stop-voltage 1 --step-voltage 0.25 --current 0.05 --delay-ms 100 --verify-after-write --log-scpi
uv run powers-tool ramp --json --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --start-voltage 0 --stop-voltage 1 --step-voltage 0.5 --current 0.05 --loop-count 2 --completion-pulse-timing loop --completion-pulse-pins 1 --log-scpi
```

驗證 sequence file，或在不开啟 VISA 下預覽確定性的 write SCPI：

```powershell
uv run powers-tool sequence --lint --json --resource "USB0::SIM::E36312A::INSTR" --file examples\sequence-readonly.yaml
uv run powers-tool sequence --dry-run --json --resource "USB0::SIM::E36312A::INSTR" --file examples\sequence-readonly.yaml
uv run powers-tool sequence --dry-run --json --model keysight-e3646a --file examples\sequence-readonly.yaml
uv run powers-tool sequence --dry-run --json --model keysight-e36312a --file examples\sequence-readonly.yaml --loop-count 2
```

Sequence YAML files 透過 core package 的 PyYAML runtime dependency 正式支援；為了最小
環境仍保留一個小型內建 parser 作為 fallback。

Sequence documents 也接受
`{"action":"trigger-pulse","channel":1,"pins":[1],"polarity":"positive",
"leave_trigger_configured":false}`。預設會在脈波後還原 trigger 與後面板腳位設定。
`leave_trigger_configured` 只控制該還原行為；它不會讓脈波觸發保持 armed，且啟用它可能
影響後續步驟或其他 BUS triggers。

Ramp List 範例：

```powershell
uv run powers-tool ramp-list --lint --json --file examples\ramp-list.json
uv run powers-tool ramp-list --dry-run --json --model keysight-e36312a --file examples\ramp-list.json
uv run powers-tool ramp-list --dry-run --json --model keysight-e3646a --file examples\ramp-list.json --loop-count 2
uv run powers-tool ramp-list --json --resource "$env:POWERS_TOOL_RESOURCE" --segment 1 0.1 0 1 0.1 100 0 --segment 2 0.05 0 2 0.2 50 500
```

### Simulator Examples

在模擬資源上清除儀器狀態與 error queue：

```powershell
uv run powers-tool clear --dry-run --json --resource "USB0::SIM::E36312A::INSTR"
```

在模擬資源上量測 voltage 與 current：

```powershell
uv run powers-tool measure --simulate --json --resource "USB0::SIM::E36312A::INSTR" --channel 2
```

在模擬資源上擷取 resource 資訊已遮蔽的原始 snapshot：

```powershell
uv run powers-tool snapshot --simulate --redact-resource --resource "USB0::SIM::E36312A::INSTR" --snapshot-json logs\before.json
```

以 no-hardware writes 預覽影響輸出的命令：

```powershell
uv run powers-tool set --dry-run --json --resource "USB0::SIM::E36312A::INSTR" --channel 1 --voltage 1 --current 0.05
uv run powers-tool output-on --dry-run --json --model keysight-e3646a --channel all
```

執行 offline diagnostics、capabilities 與 safety inspect 檢查：

```powershell
uv run powers-tool doctor --simulate --json
uv run powers-tool capabilities --simulate --json --resource "USB0::SIM::EDU36311A::INSTR" --command protection-set
uv run powers-tool safety inspect --json --explain --safety-config examples\safety-config.toml --resource-alias sim-e36312a --channel 1
```

早期的 standalone examples 提供相同的被動探索與身分查詢行為：

```powershell
.\.venv\Scripts\python.exe examples\01_list_resources.py
.\.venv\Scripts\python.exe examples\02_identify.py --resource "$env:POWERS_TOOL_RESOURCE"
```

受支援的 CLI 命令加上 `--json` 可得到穩定的 machine-readable contract。諸如
`--log-scpi` 的 diagnostic logs 維持輸出到 stderr，因此 JSON stdout 保持可解析。每個
JSON success 與 error envelope 都包含 `metadata.duration_ms`。

## Safety Defaults

- 影響輸出的行為必須明確要求。
- 真實 product execution 僅限
  [Product LIVE exact-scope matrix](../core/supported-models.md#product-live-exact-scope-matrix)
  中明確記載的 commands 與 connections。Feature family、dry-run、simulator 或 parser
  支援都不會擴大它。
- 文件記載的 `output-on`、`measure-all`、`trigger-pulse`、`trigger-fire`、`log`、
  resource-backed `doctor` 與 `restore-from-snapshot` commands 只在其文件化的 exact
  scopes 內 Product-open；不支援的 model、connection、backend 或 feature 組合會
  fail closed。
- 真實的 `clear`、`error` 與 `measure` 是安全的 I/O commands：`clear` 送出 `*CLS` 並
  清除狀態／錯誤狀態，而 `error` 與 `measure` 只做查詢。
- `--safety-config` 只會套用本機 plan validation 限制；它不會自動啟用硬體輸出。
- E36312A 與 EDU36311A 的設定點另受已驗證的官方獨立通道直流輸出額定值約束；
  safety config 只能讓限制更嚴格。
- 真實 VISA resource 不應硬編碼在提交的檔案中。
- 硬體測試必須要求使用者提供 resource。
- 啟用輸出的範例必須先設定 current limit 再設定 voltage，並在清理時關閉輸出。
