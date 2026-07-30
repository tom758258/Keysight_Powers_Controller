# Powers Tool WebUI

用於 Powers Tool 的 FastAPI 與靜態資源 WebUI adapter。

此 README 涵蓋 WebUI 的行為、API、驗證與維護者指南。關於一般操作員的工作流程，請參閱 [WebUI 使用者指南](USER_GUIDE.zh-TW.md)。關於開發人員與 agent UI 變更的邊界，請參閱 [Web UI 變更規則](web-ui-change-rules.md)。

WebUI 與 CLI 是建立在共用 Core runtime 之上的平行產品介面。

WebUI 內建於單一 `powers-tool` 發行套件中，同時保留了 `powers_tool_webui` 的 import 邊界。它依賴共用的 `powers_tool_core` runtime 與發行套件的 `webui` extra。其前端由靜態的 `index.html`、`styles.css`，以及以 `app.js` 為 bootstrap／composition root 的原生 JavaScript modules 組成；執行或建置 WebUI frontend 不需要 bundler／npm build pipeline 或 Node toolchain，但 repository 的 JavaScript syntax validation 仍會使用 Node。

## 套件與進入點 (Package And Entry Point)

WebUI 提供了用於本機 FastAPI 伺服器的 `powers-tool-webui` console wrapper，執行
`powers_tool_webui.server:main`；也提供用於 Windows GUI 啟動器的
`powers-tool-webui-launcher` console wrapper，執行 `powers_tool_webui.launcher:main`。
獨立的 PyInstaller GUI standalone artifact 位於 `dist\powers-tool-webui.exe`，它與
兩個 installed console wrapper 是分開的 artifacts，不會重新命名或取代任何 installed
entry point。Standalone artifact 與 installed server wrapper 的 basename 都是
`powers-tool-webui.exe`，但前者位於 `dist\`、後者位於 `.\.venv\Scripts\`，且分別
執行 launcher 與 server implementation；standalone artifact 與
`powers-tool-webui-launcher` wrapper 共用 `powers_tool_webui.launcher:main` launcher
implementation。

## Environment

根目錄的 [README 安裝指南](../../README.zh-TW.md#安裝) 是 canonical setup
reference。WebUI runtime 可使用：

```powershell
uv sync --extra webui --locked --link-mode=copy
```

若要執行測試或 PyInstaller build，請使用：

```powershell
uv sync --all-extras --locked --link-mode=copy
```

## Localization

維護中的 locale 是 `en` 與 `zh-TW`；English 是 source 與 fallback locale。
Locale 只改變瀏覽器 presentation，runtime 切換不 reload，也不會建立 HTTP
request、Job、workflow action 或 EventSource side effect。Machine values、API
schema、command IDs、model IDs、VISA resources、SCPI 與 raw diagnostics 保持
不變。若 browser storage 不可用，WebUI 會安全 fallback，不影響正常操作。

## Job Parameter Admission

WebUI 會將 request payload 交給共用 Core command-admission registry。每個 command
只接受其文件化欄位，且會拒絕 unknown/cross-command fields、invalid null、
boolean-as-number、numeric string 與 alias conflict。這個 adapter 不得自行增加
alias、default、coercion 或 allowlist；Core 是 CLI、Worker 與 WebUI 共用的單一
parameter authority。

## 用途

WebUI 轉接器圍繞 `powers_tool_core` 中共用的 Core runtime，提供本機 FastAPI 與瀏覽器介面。

WebUI 負責：

- 瀏覽器介面與 `src/powers_tool_webui/static/` 下的靜態資源。
- `src/powers_tool_webui/app.py` 中的 FastAPI 路由架構 (route shape)。
- `src/powers_tool_webui/launcher.py` 中的本機 Tkinter 啟動器行為。
- 面向瀏覽器的請求與回應序列化 (serialization)。
- 工作 (Job) 提交、工作狀態顯示與 SSE 事件呈現。
- 從唯讀 Core 操作衍生出來的 Live Data 顯示狀態。
- 資源掃描顯示與命令 metadata 的渲染。

Core 負責：

- SCPI 命令生成與儀器 I/O。
- Runtime 請求驗證與 dry-run 計畫。
- 輸出、保護、觸發、序列 (sequence)、斜坡 (ramp)、快照與還原行為。
- 安全限制與型號能力 (capability) 判定。
- 停止、取消、release/local (解除遠端/轉為本機)、關閉與清理行為。

WebUI 必須使用 Core 的公開 API，不可 import CLI 轉接器程式碼，也不可重新實作儀器行為。

## 執行

從 repository 根目錄：

```powershell
uv run python -m powers_tool_webui.server --host 127.0.0.1 --port 7999
```

開啟 `http://127.0.0.1:7999/`。

除非有刻意的原因需要將伺服器暴露給本機以外的網路，否則請保持 host 為 `127.0.0.1`。

安裝的 Windows GUI 啟動器 wrapper 為：

```powershell
.\.venv\Scripts\powers-tool-webui.exe --version
.\.venv\Scripts\powers-tool-webui-launcher.exe
```

不帶命令列選項時，啟動器會在 `127.0.0.1` 上從 port `7999` 開始，最多嘗試
100 個 port，通常到 `8098`。啟動器會對每個候選 port 實際 bind server socket；
無論該 port 是被另一個 Powers Tool WebUI 或其他服務占用，都只會跳過，不會開啟
已存在的服務。新啟動的 WebUI 通過 `/api/health` readiness 後，才會開啟瀏覽器，
並顯示包含實際 URL、Running 狀態與 `Quit` 的精簡 Running 視窗；port 設定與
`Start` 會隱藏。

PowerShell 的 `--port` 會要求固定 port；除非同時提供 `--auto-port`，否則不會
自動切換到其他 port：

```powershell
.\.venv\Scripts\powers-tool-webui-launcher.exe --port 9000
.\.venv\Scripts\powers-tool-webui-launcher.exe --port 9000 --auto-port
```

固定 port 衝突會回報選定 port、完成清理並以非零狀態結束，不會改用其他 port
或開啟手動 port 視窗。只有所有自動候選都因 address-in-use 失敗時，才會開啟
manual fallback；手動重試若也遇到 address-in-use，fallback 視窗會保持開啟。
其他 bind、startup、readiness 或 server-exit 錯誤都是 fatal，會保留原始細節、
完成清理並結束，不會開啟 manual fallback。

硬體命令處於活動狀態時，`Quit` 會受目前 lifecycle/cleanup 規則約束；請先在
瀏覽器停止或取消命令，並等待清理完成。

## API

- `GET /api/health`：伺服器與硬體鎖定狀態。
- `GET /api/commands`：命令 metadata、確認旗標，以及僅 WebUI 適用的停用限制。
- `POST /api/jobs`：以 `command`、`runtime`、`parameters` 及選用的 `artifacts` 提交命令工作。
- `GET /api/jobs/{job_id}`：讀取目前工作狀態。
- `POST /api/jobs/{job_id}/cancel`：請求取消。
- `GET /api/events?job_id=...`：帶有 `id`、`event` 與 `data` 的工作 SSE 串流。
- `POST /api/live`：啟動實機唯讀輪詢 (polling)。
- `GET /api/live/{job_id}/events`：即時資料 (live-data) SSE 串流。
- `POST /api/live/{job_id}/stop`：停止即時資料輪詢。

`/api/health` 在 `package` 欄位保留了轉接器識別碼 `powers-tool-webui`，而 `version` 則是來自單一安裝的 `powers-tool` 發行套件。

## Runtime 邊界 (Runtime Boundary)

WebUI 不會 import `powers_tool_cli`，也不會執行直接的 VISA 或 SCPI 操作。它會將 HTTP payload 對應到 core 的 `RuntimeOptions` 與請求物件，接著呼叫 `powers_tool_core.command_runner`。

真實硬體工作會由單一硬體鎖進行序列化。Simulate (模擬)、dry-run (預演)、離線 metadata 命令與 live-data 工作不會占用該鎖定。同步的 core 執行運行於 worker 執行緒，因此 FastAPI 的事件迴圈能繼續提供 health、工作狀態、取消與 SSE 端點的服務。

取消執行中的工作會先將其移至非終止狀態 `cancel_requested`。WebUI 會保留 `active_job_id` 與硬體鎖定，直到當前執行緒的 I/O 與 Core 的停止清理完成為止。只有在那之後，工作才會變成 `cancelled`；若清理失敗，則會變成 `failed`。已接受但尚未啟動的工作可立即變為 `cancelled`。

## 使用者介面 (UI)

靜態 UI 是一個分為三區塊的儀表板：

- 包含套件版本的標題區域，以及用於資源選擇和健康狀態的上方連線列；
- 用於各通道直接設定點及輸出捷徑的基本命令面板 (Basic command panel)；
- 透過 `/api/commands` 填充的可折疊命令列 (command rail)；
- 透過進階命令切換按鈕顯示的自動生成命令表單，內含具型別檢查的控制項，以及圖形化序列步進卡片編輯器 (Sequence step-card editor)；
- 用於即時趨勢圖、即時表格、工作歷程與結果 JSON 的右側面板。

面向機器的命令 ID 保持 kebab-case（例如：`output-on`）。面向人類的 WebUI 命令名稱則使用空格與句首大寫 (sentence case)。

`set` 命令在 Basic command 與 Commands 中接受設定電壓 (Voltage)、電流 (Current) 或兩者。空白的設定點欄位將自工作 payload 中被省略，且在 Core 中不被改變；Live Data/readback (讀回) 仍是獲取儀器完整設定點狀態的來源。
Basic output 控制項是帶有亮燈狀態的 ON 按鈕：未亮的 ON 控制項代表 OFF/未知，而亮起的 ON 控制項則代表根據最新 Live Data 的狀態為 ON。

Live Data 狀態列對 WebUI 狀態 (WebUI State)、命令狀態 (Command State) 與實機狀態 (Live State) 使用 LED 指示燈。命令狀態回報 WebUI 的命令路徑是否空閒以接受真實硬體工作；它反映的是 WebUI 的硬體 I/O 鎖定，而非儀器內部的狀態暫存器。實機狀態則維持與真實 Live Data 讀回及指令執行後的一次性更新綁定。

前端保留一個工作 SSE 控制器與一個即時資料 SSE 控制器。
Ramp List 使用專屬的區段卡片 (segment-card) 編輯器，具備版本化 JSON 載入/儲存功能。
它可載入 v2/v3 文件並視為單次執行，儲存時使用 strict v4，明確包含
`enable_output` 與 `loop_count`（即使 Loop 關閉也會儲存有效值 `1`）。編輯器
最多支援 10 個有序區段，並在送出前具備全清單觸發保護 (full-list trip guarding) 機制。
Sequence (序列) 使用可折疊的步進卡片搭配 JSON 載入/儲存，在 WebUI 中最高支援
250 個步驟。它可載入 v1 並視為單次執行，儲存與執行時使用 strict v2：
`{"version": 2, "loop_count": N, "steps": [...]}`。CLI 與 Core 不受 WebUI
250-step UI 限制。
工作結果 (Job Result) 歷程記錄預設為展開，且可以折疊或清除而不影響結果詳情 (Result Detail)。

### 脈波工作流程

Cycle Output 提供可選的完成脈波 (finished pulse)。Ramp 的 Pulse timing 選項為
None、Every step、Ramp complete 或 Loop complete；Ramp List 的選項為 None、
Every step、Segment complete 或 Loop complete。Sequence 只有既有的 per-Step
`trigger-pulse` action，沒有 top-level completion pulse。

Ramp、Ramp List 與 Sequence 支援有限 Loop。Loop 啟用時，count 必須是 exact integer
`2..10000`；關閉 Loop 時 effective value 為 `1`。Core 最多接受 1,000,000 個
logical execution units，超過 100,000 時 adapter 會顯示 long-running warning；
工作會透過現有 Job/SSE stream 發布整數百分比進度。結果 detail 最多保留前 100
與後 100 筆執行細節，並附加 truncation metadata，但 aggregate counters 仍涵蓋
完整執行。Loop 關閉時會使 Loop complete 回到 None，且該選項會停用。

脈波的後面板腳位與輸出通道相互獨立，並且僅限 E36312A。當已知所選資源為其他型號時，這些控制項會停用。Cycle Output 與 Ramp 中的脈波詳情欄位僅在脈波選項啟用後顯示。後面板腳位欄位提供所有有效腳位組合的選擇器，包含 All。Ramp 與 Ramp List 每一步驟的脈波接受額外的零毫秒延遲。

工作流程的完成脈波是軟體排程的後續動作 `*TRG` 脈波，而非原生的 LIST 執行。它們會短暫修改並還原觸發/後面板腳位設定，且全域的 `*TRG` 可能會影響其他已經 arm 的 BUS 行為。Sequence Trigger pulse 的 `Leave configured` 僅控制這些設定是否在脈波後被還原；它不會讓脈波觸發保持 armed 狀態，且可能影響後續的 Sequence 步驟或其他 BUS 觸發。

### 觸發執行

Trigger Fire 會對每個已經 arm 的 BUS 觸發發送全域 `*TRG`。其 Abort 目標通道僅在啟用 Wait complete 時才需要，並只在全儀器範圍的完成等待發生逾時或被中斷時使用。

對於 Trigger Step 與 Trigger List，Immediate 會在發送 `INIT` 時啟動，因此 Fire now 會被清除並停用。BUS 的 Wait complete 需要在同一個命令中使用 Fire now。沒有 Wait complete 就啟動的 LIST 需要 Leave configured；請選擇 Wait complete 以便在完成後還原，或是選擇 Leave configured 進行非同步執行。

### Trigger List 工作區

Trigger List 使用專屬的三通道工作區編輯器。每個通道保有自己的計數以及 1 到 100 個步驟列，包含 Voltage、Current、Dwell、BOST 與 EOST。Run 僅提交所選的通道。Load/Save 使用嚴格的 `powers-tool-trigger-list-workspace` 版本 1 JSON，並保存所有三個通道草稿及共用控制項。啟用的 BOST/EOST 步驟列需要有 LIST 輸出腳位。

當選擇了 Wait complete 且關閉 Leave configured 時，完成後會寫回執行前的 Trigger 設定與 LIST 表格。執行中的表格在還原前可能會短暫可見。選擇 Leave configured 可保留新表格與 Trigger 設定。
Live Data 樣本包含已解析的型號身分及各通道的 OVP/OCP 觸發狀態 (trip state)。有效的 Live Data 型號能修復所選資源的命令支援快取；缺乏型號的結果不會取代已知的型號。

最新、明確的通道觸發狀態會針對該通道的直接輸出命令加入 WebUI 軟體保護 (soft guard)。過時或未知的觸發狀態則不會加入保護。Safe/off 及復原命令仍然可用。

命令被分類到 Output (輸出)、Output Workflows (輸出工作流程)、Protection (保護)、Trigger (觸發)、Snapshot (快照) 以及 Advanced Diagnostics (進階診斷)。Clear Protection (清除保護) 位於 Protection 下方，且依然需要明確確認。已觸發的通道卡片可開啟並自動填寫表單，而不會直接執行。Clear Status / Errors (清除狀態/錯誤) 是分開的，並且不會清除 OVP/OCP 保護鎖存器 (latches)。

進階診斷提供了 Clear Status / Errors、Get capabilities、Read device information 以及 Read errors。工作區為每個命令與資源保留最新的成功結果，而 Result Detail (結果詳情) 保留完整的原始工作 payload。Read errors (讀取錯誤) 會將儀器錯誤佇列中每個回傳的條目移除。

## 限制

不屬於 WebUI 介面範圍的命令會被 `/api/commands` 標記為停用，若被直接提交會回傳 `not_implemented_in_webui`。預設情況下，此套件不會執行任何硬體測試。

## 測試

```powershell
uv run python -m pytest tests/webui -q -p no:cacheprovider
```

焦點啟動器與套件驗證：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\webui\test_launcher.py tests\webui\test_webui_import.py tests\core\test_distribution_metadata.py -q -p no:cacheprovider
```

編輯 WebUI JavaScript 後，請另外執行：

```powershell
node --check src\powers_tool_webui\static\execution-context.js
node --check src\powers_tool_webui\static\electrical.js
node --check src\powers_tool_webui\static\app.js
```

在可行的情況下，進行更廣泛的無硬體驗證：

```powershell
uv run python -m pytest tests -q -p no:cacheprovider
```

從上述 locked development environment 建置選用的本機 WebUI standalone artifact。
PyInstaller 由 `dev` extra 提供，不需要另外安裝：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_webui_exe.ps1
```

建置完成後，請確認 standalone artifact 能回報套件版本：

```powershell
.\dist\powers-tool-webui.exe --version
```

數字欄位限制來自共用的[命令參數契約](../contracts/commands-parameter-contract.md)。在辨識出資源型號後，UI 會套用已驗證的官方獨立通道直流輸出額定值，並對已知超出額定的請求停用「Run」。未知的型號不會套用憑空發明的限制；Core 仍具有最終決定權。

## 文件導覽

- [WebUI 使用者指南](USER_GUIDE.zh-TW.md)：面向操作員的 WebUI 使用指南。
- [WebUI README](README.zh-TW.md)：此份有關 WebUI 行為、API、驗證及維護者的指南。
- [Web UI 變更規則](web-ui-change-rules.md)：面向維護者與 agent 的 UI 變更規則。
