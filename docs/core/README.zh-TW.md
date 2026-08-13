# Powers Tool Core

## 命令參數接收

Core 擁有由所有公開 command adapter 共用的 fail-closed command parameter
registry。Admission 發生在 hardware lock、VISA open、SCPI I/O 或狀態變更之前。
每個 command 只接受其文件化欄位；其他 command 的 known field 會被視為不適用
而拒絕。Raw value 必須使用 exact JSON type；除非明確 nullable，explicit null、
alias 衝突、boolean-as-number 與 numeric string 都會被拒絕。詳情請參閱
[command parameter contract](../contracts/commands-parameter-contract.md)。

Core 內建於單一 `powers-tool` 發行套件中，同時保留了 `powers_tool_core` 的 import 邊界。它負責處理與硬體互動的行為，並由 CLI 與 WebUI 轉接器共用。

這是用於安全控制支援之直流電源供應器的 vendor-neutral Core library 與 driver
layer。Product support 由文件化的 exact scope 決定；未知 live hardware 會保持
closed。目前公開支援的型號矩陣請參閱[支援型號](supported-models.md)。

## 用途

本套件負責硬體層的型號邏輯、安全驗證、傳輸輔助工具、模擬器支援、快照 (snapshot) 處理，以及與解析器無關的序列 (sequence) runtime。它必須與 CLI 及 WebUI 套件保持獨立。

當其他 Python 套件需要直接呼叫電源供應器 runtime 時，請使用 core 套件。一般使用者通常應使用包含在同一個 `powers-tool` 發行套件中的 `powers-tool` 主控台腳本。

## 實體身分與 Registry 邊界

Core 會先從儀器回報的 manufacturer 與 model 解析 physical instrument，再選擇
model-specific driver。physical catalog、lifecycle、driver、channel、simulator、
capability、electrical-range 與 safety registry 使用 canonical vendor-qualified
ID，例如 `keysight-e36312a`。Vendor-specific driver class name 保持不變。

Physical catalog 將 GW Instek PSM-2010 登錄為
`gw-instek-psm-2010`。Registry presence 本身不決定 Product availability；
lifecycle、capabilities 與 exact live-support policy 仍是彼此分離的 authority。

`RuntimeOptions` 將 physical 與 nonphysical identity domain 分開：
`planning_model_id` 是 canonical physical planning identity，`expected_model_id`
是 optional live safety guard，`planning_profile_id` 是 nonphysical dry-run profile。
`generic-scpi` 不是 physical model 或 live expected model，也不在 physical registry
中。

## Live Support Policy 模式

Product execution 必須通過 exact `model_id + command + transport + backend +
required feature` scope；缺少、未知或 pending scope 都會 fail closed。`expected_model_id`
只作 live mismatch guard，不會選擇 driver 或解鎖 command。No-hardware capability、
另一種 transport/backend 或另一個 feature 都不代表 Product-open。

Backend selector 與 Product support 分開正規化：未設定或空白代表
`system_visa`，`@py` 代表 `pyvisa_py`，`@bt` 代表 `pyvisa_bt`，其他 selector
代表 `custom_visa`。Backend identity 本身不授予 Product support。目前沒有使用
`pyvisa_bt` 的 Product-open exact scope，因此 model-aware Product execution 搭配
`@bt` 時會 fail closed。

`list-resources`、`verify`、`identify`、`error` 與 `clear` 是明確的 diagnostic
exemptions。它們的成功只證明該 diagnostic operation，不會開放 model、feature
family、transport/backend scope 或其他 command。Exact Product matrix 請以
[Supported Models](supported-models.md) 為準；不同 transport/backend scope 不會互相繼承。
Contributor validation workflow 請參閱 [Contributing](../CONTRIBUTING.md)；驗證不會修改
Product metadata。

## 套件內容

- `powers_tool_core.connection`: VISA 後端選擇、資源列表、身分查詢與連線輔助工具。
- `powers_tool_core.factory`: 基於 IDN 的驅動程式選擇，適用於通用 SCPI、E36312A、EDU36311A、E3646A 與 PSM-2010 儀器。
- `powers_tool_core.drivers`: 特定型號的驅動程式實作與共用的 SCPI 通道策略。
- `powers_tool_core.operations`: 輸出與設定點操作，例如 `set`、`apply`、`output-on`、`output-off`、`safe-off`、`ramp`、`ramp-list`，以及 readback/snapshot 輔助工具。
- `powers_tool_core.readonly`: 唯讀的 `status`、`readback`、`measure-all` 與不會開啟 VISA 的 dry-run 計畫。
- `powers_tool_core.telemetry`: 有界的 top-level telemetry `log` 採樣、完整 cycle 取消與 adapter-owned row 回報。它與 host-only Sequence `log` 註記 action 分離，且不提供 dry-run execution。
- `powers_tool_core.trigger`: E36312A 觸發 (trigger)、STEP、原生 LIST、fire 與 abort 支援。
- `powers_tool_core.sequence`: 與解析器無關的序列文件載入、語法檢查 (linting)、dry-run 計畫與執行。
- `powers_tool_core.ramp_list`: 版本化的 JSON Ramp List 載入、完整的預先驗證、計畫與有序的軟體設定點執行。
- `powers_tool_core.discovery`、`instrument_io`、`protection` 與 `snapshot`: 供 CLI 與 WebUI 共用的 adapter-neutral 執行器 (runners)，用於探索、安全的儀器 I/O、保護與快照指令。
- `powers_tool_core.command_runner`: 共用路由器，供提交 parser-neutral core 請求的轉接器使用。
- `powers_tool_core.cancellation` 與 `stop_cleanup`: 協作取消、可中斷的等待、僅限 GPIB 的 local release，以及 Worker 與 WebUI 共用的結構化停止清理結果。
- `powers_tool_core.safety`: 明確的本機安全設定檔載入與計畫驗證。
- `powers_tool_core.electrical_ratings` 與 `setpoint_limits`: 已驗證的獨立通道直流輸出額定值、可選的 range-dependent voltage/current 組合，以及有效的安全限制。
- `powers_tool_core.capabilities`: 指令與型號的能力 (capability) 報告。
- `powers_tool_core.model_metadata`、`support_policy`、`model_resolution` 與
  `model_enablement`：公開的 model projection、exact live-support metadata、
  身分驗證與 metadata 一致性檢查。
- `powers_tool_core.testing`: 供測試與 CLI 模擬模式使用的無硬體模擬器。

## 安裝

從 repository 根目錄同步 locked environment：

```powershell
uv sync --all-extras --locked --link-mode=copy
```

基本 Core/CLI runtime：

```powershell
uv sync --locked --link-mode=copy
```

Runtime 會解析 `pyvisa`、PyYAML 與 Python 版本所需的 TOML fallback。本專案
支援 Python `>=3.10`；測試相依套件來自根目錄的 `dev` extra。Core 不提供
獨立的 console script；一般使用者應使用同一個 `powers-tool` distribution 的
`powers-tool` entry point。

## 測試

預設的 core 測試為無硬體測試：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core -q -p no:cacheprovider
```

在修改特定層級時，特定焦點測試套件很有用：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core\test_model_drivers.py tests\core\test_trigger.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\core\test_operations.py -q -p no:cacheprovider
```

Pytest 預設使用已忽略的 repository-local `.tmp_pytest` 目錄，因此測試不依賴 Windows 系統暫存目錄權限。請從 repository 根目錄執行 pytest。不要把 pytest 暫存資料或產生的測試產物寫到 `Local/`。

Contributor validation 與需主動啟用 (opt-in) 的硬體工作流程由
[Contributing](../CONTRIBUTING.md) 維護。進行任何硬體驗證前，請先執行上方的
Core 無硬體測試。

## 文件

- Core 整合指南：`integration.md`
- 支援型號：`supported-models.md`
- 接收 core 封裝的 CLI JSON 契約：`../contracts/power-cli-jsonl-contract.md`
- 根目錄工作區 README：`../../README.zh-TW.md`
- Contributor validation workflow：`../CONTRIBUTING.md`
- 命令參數契約：`../contracts/commands-parameter-contract.md`

## Runtime、Planning 與 Safety Notes

`generic-scpi` 是 no-hardware planning profile，不是 physical model lifecycle stage。

E36312A 與 EDU36311A 的保護觸發讀取使用 channel-list 查詢。共用的 Core 保護狀態會保留總和旗標 (aggregate flags)，同時從所選的通道計算它們；WebUI 的 live-panel 讀取則回傳已解析的型號身分及通道本身的 OVP/OCP 觸發狀態。

原生 LIST 執行僅限於 `trigger-list`；Ramp 一律使用軟體
設定點步進。`generic-scpi` 是 nonphysical no-hardware
planning profile，不是 physical trigger planning model。影響硬體的行為保持明確
且需主動啟用 (opt-in)。

官方 electrical rating 可為同一通道定義多個 operating ranges。此時獨立的最大
voltage 與 current 只描述整體 envelope，不能單獨證明每一組 voltage/current
組合都有效。當兩個值同時提供時，Core 要求該組合至少落在一個 official
operating range 內。明確設定的 safety limits 仍與 official rating 分開，且只能
讓有效限制更嚴格。

轉接器邊界刻意設計為單向：core 包含驅動程式方法、SCPI 輔助工具、模擬器選擇與 dry-run 計畫；CLI 與 WebUI 建立 `RuntimeOptions`/`OperationRequest` 物件，並將回傳的 `data` 封裝在它們自己的傳輸封裝 (transport envelopes) 中。

## 輸出工作流程脈波 (Pulses)

Ramp 必須在 `channel` 與非空、不可重複的 `channels` 清單之間擇一提供。
多通道選擇會依型號的 canonical channel order 重新排序；所有所選通道共用相同
電流與電壓路徑。只有每個所選通道都成功寫入後，該 logical voltage step 才算完成。
驗證與輸出狀態涵蓋所有所選通道，但 progress 與 completion pulse 仍以每個 logical
voltage step 一次計算。未指定 completion-pulse anchor 時，使用第一個 canonical
selected channel。

Ramp、Ramp List 與 Sequence 支援 strict `loop_count` 總執行次數 `1..10000`。
舊 Ramp List v2/v3 與 Sequence v1 代表一次執行；Ramp List v4/v5 與 Sequence v2
會保存 `loop_count`。結果的 `segment_count` 與 `step_count` 仍以單次 iteration
計算；`completed_loops` 只計算完整成功的 iteration，而 segment/step execution
計數則跨 iteration 累計。

Core 最多接受 1,000,000 個 logical execution units：Ramp 計算 voltage steps，
Ramp List 加總所有 Segments 的 voltage steps，Sequence 計算 Steps，再乘上
`loop_count`。Adapters 在超過 100,000 units 時警告。Runtime detail arrays
最多保留前 100 與後 100 筆，並附加 total/retained/truncated metadata；aggregate
counters 仍涵蓋完整執行。長時間工作流程透過 completed 與 total execution units
回報整數百分比進度。

Completion pulses 使用 E36312A 的後面板數位腳位；後面板腳位與所選的輸出通道
分開。Ramp 的 `step` timing 在每次 iteration 的每次 voltage write 後脈波，
`segment` 在每次完整 Ramp iteration 後脈波，`loop` 在所有 iteration 後脈波。
多通道 Ramp List Segment 依 canonical channel order 前進，所有所選通道都成功寫入後
才完成一個 logical voltage step。每一步驟與每個 Segment 只發一次脈波，並使用該
Segment 第一個 canonical channel 作為 internal trigger anchor；`loop` 使用最後一個
Segment 的第一個 canonical channel。此 anchor 不是文件設定。Every-step timing 接受
`delay_ms = 0`。
Sequence 沒有 top-level completion pulse，只有既有的 per-Step `trigger-pulse`
action。軟體脈波會為觸發與數位腳位設定建立快照並進行還原，並可能發送全域
`*TRG`，影響其他已經 armed 的 BUS 行為。

Ramp List v2/v3/v4 的每個 Segment 使用單一 `channel`；v5 是最新格式，要求明確的
`enable_output`、`loop_count`，以及每個 Segment 非空、不可重複的 `channels` 清單。
E3646A 使用自動啟用輸出時，Core 會先為整份清單使用的每個通道寫入其第一次出現
Segment 的第一組安全設定值，再一次啟用全域輸出；之後仍照常執行所有 Segment writes。
