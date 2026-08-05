# Powers Tool CLI 使用者指南

本指南針對取得已建置之 CLI 執行檔或已安裝 `powers-tool` 命令的操作員，說明如何控制支援的 Keysight 直流電源供應器。重點涵蓋常規的實機 (live) 工作流程、資源選擇與安全優先檢查。有關開發人員環境設定、詳細指令參考與自動化細節，請參見 [CLI README](README.zh-TW.md)。

## 啟動 CLI

在包含 CLI 執行檔的資料夾中開啟 PowerShell 並檢查：

```powershell
.\powers-tool.exe --version
```

發佈資料夾可能包含帶有版本號的執行檔名稱，例如：

```text
powers-tool-<version>.exe
```

如果您的發佈資料夾使用的是帶有版本號的執行檔，請在以下的命令中使用該檔名。開發人員或簽出原始碼的使用者請參閱 [CLI README](README.zh-TW.md) 以了解虛擬環境、模組、建置與 developer commands。

若為已安裝的命令，請將 `.\powers-tool.exe` 替換為 `powers-tool`：

```powershell
powers-tool --version
```

## 首次實機檢查 (First Live Check)

在檢查新電腦、VISA runtime、連線或電源供應器設定時，請使用此流程。

1. 確認該儀器可安全地進行查詢，且任何連接的受測物 (DUT) 均能承受現有的輸出狀態。
2. 僅列出目前能回應 `*IDN?` 的 VISA 資源：

```powershell
.\powers-tool.exe list-resources --live-only
```

3. 複製目標儀器確切的資源字串，並設定工作階段變數：

```powershell
$env:POWERS_TOOL_RESOURCE = "USB0::...::INSTR"
```

4. 執行唯讀的身分檢查：

```powershell
.\powers-tool.exe verify --resource "$env:POWERS_TOOL_RESOURCE" --log-scpi
```

5. 在執行任何輸出動作前，進行唯讀的測量或狀態檢查：

```powershell
.\powers-tool.exe measure --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --log-scpi
.\powers-tool.exe read-status --resource "$env:POWERS_TOOL_RESOURCE" --json --log-scpi
```

對於實機命令，請使用明確的資源字串。請勿依賴腳本或無人值守的工作流程來猜測應使用哪台儀器。

`list-resources` 與 `list-resources --live-only` 是 discovery commands，可以在
沒有預先提供 resource 時列舉 backend 發現的 resources。Resource-specific live
commands 則必須由 operator 明確選定並傳入 VISA resource。

## 資源列表

對於正常的實機使用，建議使用：

```powershell
.\powers-tool.exe list-resources --live-only
```

單純的 `list-resources` 是被動的 VISA 探索。當裝置斷線或無法使用時，它可能會顯示過時的快取資源。`--live-only` 會開啟每個找到的資源，查詢 `*IDN?`，並只印出有回應的資源。

診斷過時項目時請使用 `--verify`，因為它會同時回報實機存活與連線失敗的資源：

```powershell
.\powers-tool.exe list-resources --verify
```

將結果複製到自動化流程時，請加上 `--json`：

```powershell
.\powers-tool.exe list-resources --live-only --json
```

## 資源環境變數

使用環境變數可以簡化在同一個工作階段中複製與執行多個命令的操作：

```powershell
$env:POWERS_TOOL_RESOURCE = "USB0::...::INSTR"
$env:POWERS_TOOL_ASRL_RESOURCE = "ASRL1::INSTR"
```

請注意：
* `$env:POWERS_TOOL_RESOURCE` 用於通用的實機 USB/LAN 範例。
* `$env:POWERS_TOOL_ASRL_RESOURCE` 用於 E3646A RS-232 / ASRL 範例。
* 這些是為了文件方便而提供的變數，並非隱藏的 CLI 預設值。
* 實機命令仍需要明確提供 `--resource` 參數。

## 有限工作流程迴圈

Ramp、Ramp List 與 Sequence 接受 `--loop-count N`。這個值代表完整執行次數：
`1` 是一般單次執行，`2` 代表重新執行一次，最大值為 `10,000`。小於 `1`、
大於 `10,000` 或不是嚴格整數的值都會被拒絕。對 Ramp List 與 Sequence 文件，
明確提供的 CLI 值優先；否則使用文件值，再以舊版支援文件的預設值 `1` 收尾。

## E3646A RS-232 / ASRL

E3646A 的 Product LIVE 支援僅限 ASRL／RS-232 transport 與 system VISA backend；目前
可用的 command inventory 請以 [Product LIVE exact-scope matrix](../core/supported-models.md#product-live-exact-scope-matrix)
為準。`identify` 與 `verify` 僅是 diagnostic，不會開啟其他 command。Protection、
Trigger、Snapshot、Restore、completion pulses 與 native LIST 不屬於 E3646A 的
Product-open scope。執行任何 E3646A 實機輸出命令前，請確認實體接線已檢查完成，且要求的
電壓/電流限制對連接負載是安全的。E3646A 使用 `INST:NSEL` 做通道預選；`OUTP ON/OFF`
是全域輸出啟用/停用行為，即使命令接受通道參數，啟用或停用輸出仍可能影響
儀器整體輸出狀態。

E3646A 的 `ramp-list` 與 `sequence` 是 software workflows，不是 native LIST。
Sequence 只允許目前支援的 read-only/output steps；Protection、Trigger、
Snapshot、Restore、native LIST 與 completion-pulse steps 不支援。

每個 PowerShell 工作階段設定一次 ASRL 資源：

```powershell
$env:POWERS_TOOL_ASRL_RESOURCE = "ASRL1::INSTR"
```

單純的 `list-resources` 通常不需要序列設定：

```powershell
powers-tool list-resources
```

如果 Keysight IO Libraries Suite / Connection Expert 已經設定好 ASRL 資源，請嘗試進行唯讀檢查而不覆寫這些設定：

```powershell
powers-tool verify --resource "$env:POWERS_TOOL_ASRL_RESOURCE"
```

若要為單一命令明確套用序列設定，請僅傳遞您要覆寫的欄位。E3646A 的出廠預設範例為 9600 baud、8 data bits、none parity、2 stop bits 與 DTR/DSR 握手，但儀器前控制板的設定可能已被修改：

```powershell
powers-tool verify --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --serial-baud-rate 9600 --serial-data-bits 8 --serial-parity none --serial-stop-bits 2 --serial-flow-control dtr_dsr --serial-remote --serial-local-on-close
```

`--serial-remote` 會發送 `SYST:REM`。`--serial-local-on-close` 會在清理時盡最大努力發送 `SYST:LOC`。這些設定會影響遠端/本機狀態，且僅在明確要求時才會發送。

實用的唯讀/狀態範例：

```powershell
powers-tool identify --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --serial-remote --serial-local-on-close
powers-tool readback --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
powers-tool measure --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --channel 2 --serial-remote --serial-local-on-close
powers-tool output-state --resource "$env:POWERS_TOOL_ASRL_RESOURCE" --channel 1 --serial-remote --serial-local-on-close
```

對於 PowerShell 中的序列讀取/寫入終止字元，請儘量使用別名：`CR`、`LF`、`CRLF` 或 `NONE`。`NONE`、省略或空白終止字元表示不覆寫 VISA 設定。

## 唯讀工作流程

驗證儀器時，請先使用唯讀命令：

```powershell
.\powers-tool.exe identify --resource "$env:POWERS_TOOL_RESOURCE" --json --log-scpi
.\powers-tool.exe readback --resource "$env:POWERS_TOOL_RESOURCE" --json --log-scpi
.\powers-tool.exe protection-status --resource "$env:POWERS_TOOL_RESOURCE" --json --log-scpi
.\powers-tool.exe validate-readonly --resource "$env:POWERS_TOOL_RESOURCE" --json --log-scpi
```

這些命令會查詢身分、程式設定點、測量值、狀態或保護狀態。它們不會刻意啟用輸出。

## 影響輸出的工作流程

影響輸出的命令需要明確指定。使用前，請確認儀器型號、通道、DUT 接線、電壓、電流限制與保護設定。

在不啟用輸出的情況下設定較低的設定點：

```powershell
.\powers-tool.exe set --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --voltage 1 --current 0.05 --json --log-scpi
```

讀回已設定的狀態：

```powershell
.\powers-tool.exe readback --resource "$env:POWERS_TOOL_RESOURCE" --json --log-scpi
```

僅在確認設定點安全後才啟用輸出。對 E3646A 而言，`OUTP ON/OFF` 是全域輸出啟用/停用行為；啟用輸出前請先確認實體接線與連接負載：

```powershell
.\powers-tool.exe output-on --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --confirm --json --log-scpi
```

檢查完成後關閉輸出：

```powershell
.\powers-tool.exe output-off --resource "$env:POWERS_TOOL_RESOURCE" --channel 1 --json --log-scpi
```

若要進行簡短的快速測試動作 (smoke action)，請將電壓與電流保持在低位，並使用 CLI README 中記錄的有限度命令。請勿針對未知的資源在無人值守的情況下執行輸出工作流程。

## 常用指令

| 指令 | 典型用途 |
| --- | --- |
| `list-resources --live-only` | 尋找目前能回應 `*IDN?` 的資源。 |
| `verify` | 確認單一明確資源可被開啟並回應。 |
| `identify` | 讀取型號身分。 |
| `measure` | 讀取單一通道的電壓/電流。 |
| `read-status` | 讀取輸出狀態。 |
| `readback` | 讀取程式設定點與測量值。 |
| `protection-status` | 讀取保護狀態。 |
| `validate-readonly` | 執行一次唯讀診斷。 |
| `set` | 設定電壓/電流而不啟用輸出。 |
| `output-on` / `output-off` | 明確啟用或停用輸出。 |
| `safe-off` | 使用支援的安全路徑關閉輸出。 |

## 無硬體檢查

若只要確認安裝、CLI entry point 與 simulator 路徑，請使用：

```powershell
uv run powers-tool --version
uv run powers-tool doctor --simulate --json
```

這些命令不會進行 live 或 system-VISA resource discovery、不會開啟 VISA resource、
不會送出 SCPI、不會修改實體儀器狀態，也不會啟用輸出；不需要實體儀器或 vendor
VISA runtime。

`--model` 不是 feature unlock；live mode 仍以實際 `*IDN?` 偵測出的 model 選擇 driver。
Unsupported model、command、mode、connection、backend 或 feature combinations 會 fail closed。
Product LIVE support 是 detected model、command、transport、backend 與 required feature 的 exact
scope；missing 或 pending scopes 也會 fail closed。No-hardware plan 或 feature family 不代表其中
所有 commands 都是 Product-open。請參閱 [Supported Models](../core/supported-models.md#product-live-exact-scope-matrix)
確認目前支援組合。

## 常見問題

如果找不到 `powers-tool.exe`，請確認您位於包含 CLI 執行檔的資料夾中，並使用該資料夾中實際的檔名。

如果找不到實機存活的資源，請檢查儀器電源、USB/LAN 纜線、VISA 驅動程式可見度，以及是否有其他程式佔用了該儀器。

如果單純的 `list-resources` 顯示舊項目，請在常規操作流程改用 `--live-only` 重新執行，或使用 `--verify` 來診斷過時的 VISA 快取項目。

如果命令拒絕執行，請將其視為安全與 support policy 的結果；CLI 會在執行風險動作前，刻意拒絕不支援的型號、通道、不安全的設定點，以及缺少確認的操作。重試或加入 `--model` 不會啟用不支援的功能。

如果日誌或自動化需要 JSON 輸出，請加上 `--json`。來自 `--log-scpi` 的診斷 SCPI 日誌會分開寫入 (stderr)，讓 JSON stdout 保持可解析狀態。

## 更多 CLI 文件

- [CLI README](README.zh-TW.md)：工程建置、完整指令參考、JSON 行為、worker 細節與建置資訊。
- [Power CLI JSON / JSONL 契約](../contracts/power-cli-jsonl-contract.md)：結構化的命令列輸出規則。
- [Power Worker 契約](../contracts/power-worker-contract.md)：本機 worker REST、JSONL 與產物 (artifact) 契約。
- [支援型號](../core/supported-models.md)：目前 Product support matrix 與型號特定限制。
