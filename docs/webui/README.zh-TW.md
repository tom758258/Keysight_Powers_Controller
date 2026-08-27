# Powers Tool WebUI

用於 Powers Tool 的 FastAPI 與靜態資源 WebUI adapter。

此 README 涵蓋 WebUI 的行為、API、驗證與維護者指南。關於一般操作員的工作流程，請參閱 [WebUI 使用者指南](USER_GUIDE.zh-TW.md)。關於開發人員與 agent UI 變更的邊界，請參閱 [Web UI 變更規則](web-ui-change-rules.md)。

WebUI 與 CLI 是建立在共用 Core runtime 之上的平行產品介面。

## Product 支援邊界

Product model selector 僅包含 Product-active 型號。GW Instek PSM-2010 的
Product LIVE scope 僅限 ASRL / RS-232 + system VISA，並開放 Core Product
matrix 所列的 23 個 model-aware commands，包括 setpoint／output、protection、
snapshot／restore、ramp 與 software sequence workflows。Powers Trigger
commands 仍不支援；其他 transport 與 backend 仍會 fail closed。完整範圍以
[Supported Models](../core/supported-models.md) 為準。

WebUI 內建於單一 `powers-tool` 發行套件中，同時保留了 `powers_tool_webui` 的 import 邊界。它依賴共用的 `powers_tool_core` runtime 與發行套件的 `webui` extra。其前端由靜態的 `index.html`、`styles.css`，以及以 `app.js` 為 bootstrap／composition root 的原生 JavaScript modules 組成；執行或建置 WebUI frontend 不需要 bundler／npm build pipeline 或 Node toolchain。`app.js` 是 bootstrap 與整合層。`api.js` 擁有共用的 JSON HTTP request/response 邊界；`execution-context.js` 擁有純 execution/workspace context；`state.js` 擁有初始 page-local state。`device-resource.js` 擁有 Device/Resource 與 execution-mode 控制項。`command-form.js` 擁有命令目錄／表單渲染、payload 建構、guidance、accessibility help 與參數限制。`results.js` 擁有 job-result summary 與 Workspace Result 呈現。`jobs.js` 擁有 Job HTTP 提交、SSE transport 與 Job History 狀態及呈現。`live-data.js` 擁有 Live Data 取樣、lifecycle 與通道呈現。
`json-files.js` 擁有共用的瀏覽器 JSON file picker 與下載 helper。
`ramp-list.js` 擁有純 Ramp List 文件 materialization 與驗證。
`trigger-list.js` 擁有純 Trigger List workspace 文件 materialization 與驗證。
`sequence.js` 透過明確的 action-schema 相依性，擁有純 Sequence 文件正規化與編輯器序列化。
`snapshot-restore.js` 擁有 Snapshot 與 Restore 的 schema 驗證與 payload materialization。
`basic-controls.js` 擁有 Basic 控制動作與 Live-readback 呈現。
`command-support.js` 擁有 command-support 與 channel-capability 呈現。
`workflows.js` 擁有瀏覽器端的 Ramp List、Trigger List、Sequence、Snapshot 與 Restore
編輯器，以及它們的 JSON Load/Save orchestration。它在模組邊界間只接收自己使用的
state、document helpers 與 application callbacks；文件 schema 仍由各自的 focused
document modules 擁有。
`i18n.js` 擁有 locale 驗證、catalog lookup、English fallback 與 interpolation。
`locale_ui.js` 擁有瀏覽器語言偵測、locale 偏好儲存、`<html lang>` 與 runtime 語言
控制項。`locale_en.js` 提供 English source catalog，`locale_zh_tw.js` 提供維護中的
Traditional Chinese catalog。

`app.js` 維持 bootstrap 與 composition root。Controller factory 參數僅代表跨模組邊界
提供的相依性；某個 controller 擁有的 helpers 彼此直接呼叫，不會繞回 `app.js` 路由。
`device-resource.js` 私下擁有其 Device/Resource 與 execution-mode 呈現所使用的固定
state-indicator class names 與 E3646A presentation model identifier。
`command-form.js` 繼續擁有命令／表單渲染、Trigger notes，以及參數與電氣限制。
Workflow ownership 不變。

Frontend tests 包含 native module-graph smoke，會在不改寫 import/export 的前提下匯入
真實的 `app.js` graph root。既有的 global compatibility harness 仍可用於更廣泛的
frontend 行為測試；它不取代 native graph 檢查。

## 套件與進入點 (Package And Entry Point)

WebUI 提供了用於本機 FastAPI 伺服器的 `powers-tool-webui` console wrapper，執行
`powers_tool_webui.server:main`；也提供用於 Windows GUI 啟動器的
`powers-tool-webui-launcher` console wrapper，執行 `powers_tool_webui.launcher:main`。
本機 shared PyInstaller onedir bundle 包含
`dist\powers-tool\powers-tool.exe`、
`dist\powers-tool\powers-tool-webui-launcher.exe`，以及供後續 desktop
integration 使用的 private `dist\powers-tool\powers-tool-webui-host.exe`；
三者共用 `dist\powers-tool\_internal\` 目錄。Desktop Host 是供 source-mode
Electron Desktop shell 使用的 private executable，不是新的公開 CLI entry
point。Shared bundle artifacts 與已安裝的 console wrappers 分開，不會重新
命名或取代任何 installed entry point。

Source-mode Desktop shell 是以 Electron 顯示現有 WebUI，不建立第二套 WebUI。
從 repository root 執行：

```powershell
Set-Location .\desktop
npm ci
npm start
```

它會啟動 private Host，開啟初始 1920x1080 並依 primary display work area
進行 clamp，並遵循 WebUI 的 System、Light、Dark 主題偏好。允許多個
Desktop instance 供不同實體儀器使用，但不同 client 不可同時操作同一個
physical instrument resource。

## 內建說明

WebUI 會從本機 `/help/` route 提供內建 Help。Header 的 `Help` link 會在新的
瀏覽器分頁開啟目前 locale：English 使用 `/help/`，Traditional Chinese 使用
`/help/webui.zh-TW.html`。Desktop shell 顯示同一套 WebUI，因此使用相同的內建
Help。

Help HTML 是由維護中的 WebUI `USER_GUIDE` Markdown 與
[Supported Models](../core/supported-models.zh-TW.md) 文件生成。Generated HTML
只是 presentation output，不得視為另一份獨立維護的文件來源。

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
不變。Locale preference 使用獨立的 browser storage key
`powers-tool.webui.locale`；若 storage 不可用，WebUI 會安全 fallback，不影響
正常操作。

Header 右上角提供「外觀」與「語言」兩個標示清楚的控制項。語言控制會顯示
目前 locale（`English` 或 `繁體中文`），accessible name 則描述切換目的地。
外觀控制會顯示目前的主題偏好，並依序切換 System、Light、Dark。主題偏好會
以一年的 `Max-Age` 儲存在 `powers-tool.webui.theme` cookie，並由 browser WebUI
與 Electron shell 共用。System 模式遵循 `prefers-color-scheme`；Electron shell
會使用同一個 loopback cookie 同步 native window theme。選定的主題會套用至
WebUI 主要的 panels、cards、fields 與 status surfaces，不只改變頁面背景。
深色主題下，主要控制項、狀態文字，以及不可用或停用的控制項，會在深色
surface 上維持足夠辨識度。

## Job Parameter Admission

`POST /api/jobs` 的 top level 只接受 `command`、`runtime`、`parameters` 與選用的空
`artifacts`。未知的 top-level 欄位回傳 HTTP 400。`parameters` 會在 job 進入 queue 或
取得 hardware lock 前，由 Core-owned command contract 進行 admission。WebUI 不會
自行維護 per-command allowlist、alias 或型別轉換；無效的 exact type、明確 null、
未知／不適用欄位與 alias conflict 回傳 HTTP 400，而不是 server error。通過 admission
的 canonical request 就是被 job 執行的請求。

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
- Physical-model 與 nonphysical planning-profile metadata projections。
- 停止、取消、release/local (解除遠端/轉為本機)、關閉與清理行為。

WebUI 必須使用 Core 的公開 API，不可 import CLI 轉接器程式碼，也不可重新實作儀器行為。

## 執行

從 repository 根目錄：

```powershell
uv run python -m powers_tool_webui.server --host 127.0.0.1 --port 7999
```

開啟 `http://127.0.0.1:7999/`。

除非有刻意的原因需要將伺服器暴露給本機以外的網路，否則請保持 host 為 `127.0.0.1`。

已安裝的 Windows console wrappers：

```powershell
# FastAPI server console wrapper
.\.venv\Scripts\powers-tool-webui.exe --version
# GUI launcher console wrapper
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
或開啟手動 port 視窗。加上 `--auto-port` 則明確從選定 port 開始嘗試最多 100 個
port。只有所有自動候選都因 address-in-use 失敗時，才會開啟完整 port fallback 視窗、
回報嘗試過的範圍，並允許手動輸入其他 port；`Start` 接著只嘗試該 port。手動重試若也
遇到 address-in-use，fallback 視窗會保持開啟並重新啟用 port 欄位與 `Start`；成功的
fallback 重試會回到精簡 Running 視窗。自動候選不會超過 port `65535`。

非 address-in-use 的 bind 失敗會立即停止自動選擇。Uvicorn 或 application 初始化失敗、
server thread 提前結束與 readiness timeout 也都是 fatal startup failures。啟動器會保留
原始錯誤細節、要求部分建立的 server 停止、關閉自己持有的 socket、短暫等待其 server
thread，並以非零狀態結束。這些失敗永不重新開啟 manual port window，包括發生在手動
fallback retry 時。

啟動器保持視窗可用，讓 `Quit` 能停止其本機 Uvicorn server。`Quit` 會先請求取消作用中
的 WebUI jobs——包括 Live Data 以及 simulation／dry-run workflows——並等待它們完成
正常清理後才停止 launcher 擁有的 server。若 job 清理或 server shutdown 逾時，啟動器
會保持開啟並回報 shutdown 未完成。精簡／fallback 的呈現方式不改變 port 選擇、startup
失敗分類、cleanup 或 process exit-code 行為。

本機 shared PyInstaller GUI artifact 是位於
`dist\powers-tool\powers-tool-webui-launcher.exe` 的獨立執行檔；它由同一份 launcher
implementation 建置，但不是上面安裝的 server wrapper。

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

來自 `/api/commands` 的 physical metadata 只以 canonical `model_id` 鍵值存放於
`command_support_by_model_id`、`live_support_by_model_id`、
`channel_capabilities_by_model_id`、`electrical_ratings_by_model_id` 與
`setpoint_ranges_by_model_id`。獨立的 `planning_profiles` 物件承載 nonphysical
profiles（例如 `generic-scpi`），不會混入 physical model map。其 metadata 直接由 Core
projection 而來；WebUI 只負責隨 command response 序列化。Evidence 與 private support
metadata 不會被暴露。

## Runtime 邊界 (Runtime Boundary)

WebUI 不會 import `powers_tool_cli`，也不會執行直接的 VISA 或 SCPI 操作。它會將 HTTP payload 對應到 core 的 `RuntimeOptions` 與請求物件，接著呼叫 `powers_tool_core.command_runner`。

真實硬體工作會由單一硬體鎖進行序列化。Simulate (模擬)、dry-run (預演)、離線 metadata 命令與 live-data 工作不會占用該鎖定。同步的 core 執行運行於 worker 執行緒，因此 FastAPI 的事件迴圈能繼續提供 health、工作狀態、取消與 SSE 端點的服務。

Raw `/api/jobs` payload 使用 V2 runtime identity 欄位。Dry-run 只接受
`runtime.planning_model_id` 或 `runtime.planning_profile_id` 其中之一；simulator mode
只接受 physical planning ID。Live execution 只接受選用的 `runtime.expected_model_id`。
Core 會查詢 `*IDN?`、解析 manufacturer 加 model，並在預期的 canonical model 不符時於
command-specific SCPI 前失敗；guard 永遠不會覆寫由 IDN 選出的 driver。

Dry-run 範例：

```json
{
  "command": "trigger-step",
  "runtime": {
    "resource": "USB0::FAKE::E36312A::INSTR",
    "dry_run": true,
    "simulate": false,
    "planning_model_id": "keysight-e36312a"
  },
  "parameters": {
    "channel": 1,
    "source": "bus",
    "fire": true
  }
}
```

Legacy 的 `runtime.model_profile` 與 `runtime.model` 欄位會被拒絕。WebUI 不會從 fake
或 live-looking resource 字串推測 dry-run/simulate model；請使用 V2 planning 欄位或
deterministic SIM resource（例如 `USB0::SIM::E36312A::INSTR`）。WebUI 的 live resource
支援由 scan/job IDN metadata 學習而來。瀏覽器提供 page-local 的 Real、Simulate 與
Dry-run execution modes；一律以 Real mode 重新載入，且絕不將 mode、identity 或 write
authorization 保存在 browser storage。Simulate 需要 canonical physical planning model；
Dry-run 接受 physical planning model 或 planning profile。No-hardware 請求會省略 live
resource、serial settings、expected-model guard 與 confirmation。

Raw runtime 值採嚴格型別。Boolean 欄位只接受 JSON `true` 或 `false`；諸如 `"false"` 的
字串永遠無法滿足 confirmation 或啟用模式。Integer、string、identity 與 serial-option
欄位同樣會在 job 提交前驗證。Raw `parameters.channel` 對支援的命令只接受 exact 正整數
JSON integer 或 exact `"all"`；boolean、float 與數字字串不會被轉型。Core-owned command
admission 會在建立 WebUI job 前拒絕缺少或衝突的 planning identity，以及格式錯誤的
restore/snapshot boolean。未知命令與 `/api/jobs` 刻意不支援的命令也會在 job/task 建立
前同步拒絕。Physical model 選項與所有 model-keyed support/rating map 都由同一份 Core
Product-active metadata inventory 產生；`generic-scpi` 仍是獨立的 nonphysical planning
profile。

Browser 與 raw WebUI jobs 一律使用 product support-policy mode。Validation-policy
runtime 欄位會被拒絕而非忽略。Frontend 的 enabled 狀態僅供 UX：Core 仍是最終由 IDN
選擇的 exact-scope authority，pending transport/backend scope 不是 product-open。

對 Ramp、Ramp List 與 Sequence，主要 Run 按鈕是有狀態的：
`Run`、`Starting...`、紅色 `Stop`、`Stopping...`，直到 terminal SSE event 確認作用中
job 已清除後才回到 `Run`。Stop 代表「停止作用中的 workflow 並安全關閉所有輸出」。
清理執行期間，UI 顯示 `Waiting for safe-off and cleanup`，並保持命令切換與 Live Data
硬體存取封鎖。SSE 中斷透過 job-status reconciliation 處理；正常完成不需要額外的
health/lock poll。

取消執行中的工作會先將其移至非終止狀態 `cancel_requested`。WebUI 會保留 `active_job_id` 與硬體鎖定，直到當前執行緒的 I/O 與 Core 的停止清理完成為止。只有在那之後，工作才會變成 `cancelled`；若清理失敗，則會變成 `failed`。已接受但尚未啟動的工作可立即變為 `cancelled`。

## 使用者介面 (UI)

靜態 UI 是一個分為三區塊的儀表板：

- 包含套件版本的標題區域，以及用於資源選擇和健康狀態的上方連線列；
- 用於各通道直接設定點及輸出捷徑的基本命令面板 (Basic command panel)；
- 透過 `/api/commands` 填充的可折疊命令列 (command rail)；
- 透過進階命令切換按鈕顯示的自動生成命令表單，內含具型別檢查的控制項，以及圖形化序列步進卡片編輯器 (Sequence step-card editor)；
- 用於即時趨勢圖、即時表格、工作歷程與結果 JSON 的右側面板。

面向機器的命令 ID 保持 kebab-case（例如：`output-on`）。面向人類的 WebUI 命令名稱則使用空格與句首大寫 (sentence case)。

連線區域包含 **Supported devices / 支援裝置** 唯讀清單與 Device options（裝置選項）。在 Real 模式，`Expected model` 預設為 `Auto-detect`，此時省略 `runtime.expected_model_id`；Auto-detect 使用連線儀器的 IDN 進行 live 操作。選擇 `Require <model>` 會送出 canonical 的 `runtime.expected_model_id` 作為 live safety guard，並可在 metadata 存在時驅動前端命令、通道與額定規劃。Device / Resource summary 會將偵測到的 live model 與 expected model 選擇分開顯示，例如 `live E3646A / Auto-detect` 或 `live E3646A / Require E36312A`。被選擇的 model 永遠不會覆寫由 IDN 選出的 live driver；Core 仍是 setup/write SCPI 前 live mismatch 拒絕的 authority。Device / Resource 標頭會以 `Real · Writes locked` 或 `Real · Writes enabled` 顯示 page-local 的 write authorization 狀態；badge 不可互動，授權仍由 Device options 控制。Real 模式下，非空白的 VISA resource 預設會為「當前 resource、expected-model guard 與偵測到 model」的組合建立 write authorization。Device options checkbox 可以在相同 context 下停用寫入。選擇或輸入其他 resource、變更 Expected model、偵測到不同 model，或回到 Real mode 都會以預設啟用寫入建立新 context。沒有 resource 時 checkbox 停用且不存在授權。
Serial 欄位皆為選用；空白欄位會自 runtime payload 省略，不覆寫 VISA backend 或
Connection Expert 設定。Read/write termination 欄位接受 `CR`、`LF`、`CRLF` 與 `NONE`
alias。`NONE`、空白或省略代表不套用 termination override。

Frontend command rail 可能為了操作員清晰度隱藏或停用不支援的 commands，但這僅是 UX。
直接提交 `/api/jobs` 仍會經過 WebUI backend validation 與 Core support gates，因此即使
呼叫端略過瀏覽器控制項，不支援的 model/command/mode 組合仍會被拒絕。

瀏覽器會區分 profile support 與 exact Product-mode live availability。在真實資源回傳
capabilities 之前，commands 保持其 model-planning 行為，並顯示連線 scope 尚未評估。
在已經 Product-open 的 scope 上成功執行 resource-backed `capabilities`，或成功的真實
`identify` diagnostic，會加入 IDN 偵測的 model、正規化的 transport/backend scope，以及
per-command 的 exact status。Diagnostic 路徑會在 expected-model guard 下讀取身分，但
不會開放 pending feature commands。Validated commands 維持可用；pending 或缺少的 exact
scopes 以不同原因顯示為停用，而 identity/status diagnostics 則明確屬於 policy-exempt。
更換 resource 會清除這個 exact context，直到對新資源讀取 capabilities 或 identity。

若成功的 `identify` 或 `verify` diagnostic 偵測到未知或已移除的 model，diagnostic 結果
仍然可用，但其 support projection 為 unevaluated 且不含任何 command availability。這個
中性結果會清除過期的 exact context，也不啟用 Generic fallback；一般 model-aware live
commands 仍 fail closed。Expected-model mismatch 仍會在附加選用支援 metadata 前使
diagnostic 失敗。

當 exact context 已知時，Device / Resource summary 會顯示偵測到的 model、expected-model
guard、transport/backend scope，以及精簡的 validated/pending/unavailable 計數。Pending
metadata 只在實際 runtime transport/backend 符合某個已註冊 pending scope 時出現。WebUI
維持 Product-only，標準瀏覽器使用預設 system-VISA backend；它沒有 validation mode 或
VISA-backend selector。這些顯示與停用控制項都是 UX；Core 在 IDN 後的 exact-scope gate
仍是 authority。

安全的 Core projection 也可以為 exact scope 包含附加的 `sequence_action` 與
`trigger_source` inventories。這些 entries 只暴露狀態與 Product availability，不暴露
evidence 或內部 notes。Projection contract 是 schema version 2：已評估的 physical
結果使用 canonical `model_id`；unevaluated diagnostics 則將回報的 manufacturer/model
與可為 null 的 resolved `model_id` 分開。Projection 永不暴露 evidence IDs、歷史路徑、
checksums 或 private evidence notes。由於文件與 trigger request 在執行時才選擇 feature，
command rail 維持 command-level，不會因為另一個未來 feature 是 pending 就全域停用某個
command。Core 會在 IDN 之後、feature-specific SCPI 之前驗證實際 normalized request
features。

Product model selector 只包含 Product-active models。Candidate、catalog-only 與
de-scoped models 不是瀏覽器 runtime 選項；目前沒有任何 candidates。

純 offline utilities 與 identity/status diagnostics 分類不同。它們不代表 Product-open
live commands，也不會被描述為 policy-exempt 的硬體 diagnostics。

`set` 命令在 Basic command 與 Commands 中接受設定電壓 (Voltage)、電流 (Current) 或兩者。空白的設定點欄位將自工作 payload 中被省略，且在 Core 中不被改變；Live Data/readback (讀回) 仍是獲取儀器完整設定點狀態的來源。
Voltage 是輸出電壓設定點，Current 是輸出電流限制／電流設定值（適用於 E36312A、
EDU36311A 與 E3646A）。`/api/commands` 為這些 active models 提供官方 setpoint
programming-range metadata。E3646A 的 metadata 對 LOW/P8V 與 HIGH/P20V 是 range-
dependent；目前的 WebUI 不會依該 metadata 新增 range selector。Browser constraints 與
hints 只是 UX，backend Core validation 仍是 authority。此 metadata 不引入硬性小數位數
拒絕或靜默的四捨五入／截斷。
Basic output 控制項是帶有亮燈狀態的 ON 按鈕：未亮的 ON 控制項代表 OFF/未知，而亮起的 ON 控制項則代表根據最新 Live Data 的狀態為 ON。
E3646A 使用一個全域輸出開關：其 CH1 與 CH2 輸出控制項會停用並標示由 ALL 控制，而它們
的 Voltage、Current 與 Set 控制項保持獨立。readback 未知時 E3646A ALL 控制項仍可用並
送出 output-on；命令後的硬體狀態顯示仍由新的 Live Data 決定。

Live Data 狀態列對 WebUI 狀態 (WebUI State)、命令狀態 (Command State) 與實機狀態 (Live State) 使用 LED 指示燈。命令狀態回報 WebUI 的命令路徑是否空閒以接受真實硬體工作；它反映的是 WebUI 的硬體 I/O 鎖定，而非儀器內部的狀態暫存器。實機狀態則維持與真實 Live Data 讀回及指令執行後的一次性更新綁定。

前端保留一個工作 SSE 控制器與一個即時資料 SSE 控制器。
Ramp List 使用專屬的區段卡片 (segment-card) 編輯器，具備版本化 JSON 載入/儲存功能。
它可載入 v2/v3/v4/v5，儲存時一律使用 strict v5，明確包含 `enable_output`、
`loop_count` 與每個 Segment 的 `channels`（即使 Loop 關閉也會儲存有效值 `1`）。
每個 Segment 可依目前型號 metadata 選擇不同通道組合；All 會儲存為明確的 canonical
channel list。編輯器最多支援 10 個有序區段，並在送出前檢查所有所選通道的支援、
額定值與 protection-trip 狀態。
Sequence (序列) 使用可折疊的步進卡片搭配 JSON 載入/儲存，在 WebUI 中最高支援
250 個步驟。它可載入 v1 並視為單次執行，儲存與執行時使用 strict v2：
`{"version": 2, "loop_count": N, "steps": [...]}`，且永不序列化內部的 camel-case
狀態名稱。CLI 與 Core 不受 WebUI
250-step UI 限制。
對 Ramp 與每個 Ramp List segment，`Wait between steps (ms)` 只在非最終 voltage step
之後套用；Ramp List 的 `Wait after final step (ms)` 在最後一個 voltage step 之後、該
segment 完成之前套用。
工作結果 (Job Result) 歷程記錄預設為展開，且可以折疊或清除而不影響結果詳情 (Result Detail)。

### 脈波工作流程

Cycle Output 提供可選的完成脈波 (finished pulse)。Ramp 的 Pulse timing 選項為
None、Every step、Ramp complete 或 Loop complete；Ramp List 的選項為 None、
Every step、Segment complete 或 Loop complete。Sequence 只有既有的 per-Step
`trigger-pulse` action，沒有 top-level completion pulse。
多通道 Ramp List 的 Every-step 與 Segment-complete 每次只發一個脈波，內部使用該
Segment 第一個 canonical channel；Loop-complete 使用最後一個 Segment 的第一個
canonical channel。使用者不需要也不能設定此 trigger channel。

Ramp 的 Channel selector 會依目前型號 metadata 動態顯示單一通道、通道組合與
All。單一選項送出 `channel`；組合與 All 送出明確、canonical 的 `channels` 清單。
所有所選通道共用相同 Ramp 參數，並以 lockstep logical steps 前進。
全寬的多通道提示只會在選取通道組合或 All 時顯示於 Channel 與 Current 下方；選取
單一通道時不會保留空白提示列，其餘 Ramp 參數會維持雙欄對齊。
Ramp 表單的欄位順序為 Enable output、Enable loop、Channel/Current、Ramp setpoints
與 Pulse timing。Ramp List 將 Enable loop 放在 Auto-enable output for each channel 與
Pulse timing 之間。Sequence 將 Enable loop 放在 toolbar 與 Step 1 之間；
Create snapshot 沒有 Loop 狀態。Loop count 僅在啟用時 inline 建立，預設為 2，接受
2 到 10,000 的整數。

Ramp、Ramp List 與 Sequence 支援有限 Loop。Loop 啟用時，count 必須是 exact integer
`2..10000`；關閉 Loop 時 effective value 為 `1`。Core 最多接受 1,000,000 個
logical execution units，超過 100,000 時 adapter 會顯示 long-running warning；
工作會透過現有 Job/SSE stream 發布整數百分比進度。結果 detail 最多保留前 100
與後 100 筆執行細節，並附加 truncation metadata，但 aggregate counters 仍涵蓋
完整執行。關閉 Loop 會移除該欄位、使 effective value 變為 1，並將已選的
Loop-complete pulse 重設為 None；Loop 關閉時該選項停用。無效的已啟用 Loop count 會在
編輯器重新渲染時保持可見，並讓 `Run` 與 `Save` 維持停用，直到修正或明確關閉 Loop。
若 Ramp List 已選擇 Loop-complete timing，無效草稿會暫時停用該選項但不清除選擇；
修正 count 後立即恢復選項與選擇。

脈波的後面板腳位與輸出通道相互獨立，並且僅限 E36312A。當已知所選資源確定是其他型號時，這些控制項會停用。身分未知時，脈波詳情仍可設定，但 `Run` 會被封鎖並顯示
E36312A planning/support 指引，直到選擇或偵測到合適的 model。Cycle Output 與 Ramp 中的脈波詳情欄位僅在脈波選項啟用後顯示。後面板腳位欄位提供所有有效腳位組合的選擇器，包含 All。Ramp 與 Ramp List 每一步驟的脈波接受額外的零毫秒延遲。

Ramp List 在 E3646A context 會於自動啟用輸出附近顯示提示。由於 E3646A 的輸出啟用
是全域控制，Core 會先為清單中會使用到的每個通道寫入第一組安全設定值，再一次啟用
全域輸出。

工作流程的完成脈波是軟體排程的後續動作 `*TRG` 脈波，而非原生的 LIST 執行。它們會短暫修改並還原觸發/後面板腳位設定，且全域的 `*TRG` 可能會影響其他已經 arm 的 BUS 行為。Sequence Trigger pulse 的 `Leave configured` 僅控制這些設定是否在脈波後被還原；它不會讓脈波觸發保持 armed 狀態，且可能影響後續的 Sequence 步驟或其他 BUS 觸發。

### 觸發執行

Trigger Fire 會對每個已經 arm 的 BUS 觸發發送全域 `*TRG`。其 Abort 目標通道僅在啟用 Wait complete 時才需要，並只在全儀器範圍的完成等待發生逾時或被中斷時使用。

對於 Trigger Step 與 Trigger List，Immediate 會在發送 `INIT` 時啟動，因此 Fire now 會被清除並停用。BUS 的 Wait complete 需要在同一個命令中使用 Fire now。沒有 Wait complete 就啟動的 LIST 需要 Leave configured；請選擇 Wait complete 以便在完成後還原，或是選擇 Leave configured 進行非同步執行。

### Trigger List 工作區

Trigger List 使用專屬的三通道工作區編輯器。每個通道保有自己的計數以及 1 到 100 個步驟列，包含 Voltage、Current、Dwell、BOST 與 EOST。Run 僅提交所選的通道。Load/Save 使用嚴格的 `powers-tool-trigger-list-workspace` 版本 1 JSON，並保存所有三個通道草稿及共用控制項。啟用的 BOST/EOST 步驟列需要有 LIST 輸出腳位。

當選擇了 Wait complete 且關閉 Leave configured 時，完成後會寫回執行前的 Trigger 設定與 LIST 表格。執行中的表格在還原前可能會短暫可見。選擇 Leave configured 可保留新表格與 Trigger 設定。
Live Data 樣本包含已解析的型號身分及各通道的 OVP/OCP 觸發狀態 (trip state)。有效的 Live Data 型號能修復所選資源的命令支援快取；缺乏型號的結果不會取代已知的型號。
PSM-2010 的 CH1 卡片會額外顯示目前實際 LOW/HIGH 輸出檔位的唯讀 badge。尚未知或尚未取得資料時顯示 `--`；其他型號不顯示此 badge。

最新、明確的通道觸發狀態會針對該通道的直接輸出命令加入 WebUI 軟體保護 (soft guard)。過時或未知的觸發狀態則不會加入保護。Safe/off 及復原命令仍然可用。

命令被分類到 Output (輸出)、Output Workflows (輸出工作流程)、Protection (保護)、Trigger (觸發)、Snapshot (快照) 以及 Advanced Diagnostics (進階診斷)。Clear Protection (清除保護) 位於 Protection 下方，且依然需要明確確認。已觸發的通道卡片可開啟並自動填寫表單，而不會直接執行。Clear Status / Errors (清除狀態/錯誤) 是分開的，並且不會清除 OVP/OCP 保護鎖存器 (latches)。

進階診斷提供了 Clear Status / Errors、Get capabilities、Read device information 以及 Read errors。Workspace 會為每個完整執行 context 保留最新的成功結果：Real 包含
resource、Expected Model guard 與解析後的 canonical identity；Simulate 與 Dry-run 則
包含其 physical planning model 或 planning profile。Result Detail (結果詳情) 保留完整的原始工作 payload。Read errors (讀取錯誤) 會將儀器錯誤佇列中每個回傳的條目移除。

## 限制

不屬於 WebUI 介面範圍的命令會被 `/api/commands` 標記為停用，若被直接提交會回傳 `not_implemented_in_webui`。預設情況下，此套件不會執行任何硬體測試。
Model feature-lock policy 也適用於直接的 `/api/jobs` 提交：EDU36311A 的
trigger/native LIST 與 snapshot/restore jobs、E3646A 的 protection/trigger/native
LIST/snapshot/restore 與 completion-pulse jobs，以及不支援的 E3646A sequence step
types，都會在 backend/Core 邊界被拒絕。

Live validation evidence 由 CLI suite artifacts 記錄，不是由瀏覽器 selector 建立。
WebUI 只顯示目前 policy 的安全 Core projection，不暴露 evidence paths，也不提升狀態。
Suite 名稱是 evidence 分組，不會開放 feature family 中的所有命令。Core 要求 exact 的
canonical `model_id`、command、transport、backend 與 required-feature scope；缺少與
pending scope 都 fail closed。權威的目前命令清單是
[Product LIVE exact-scope matrix](../core/supported-models.md#product-live-exact-scope-matrix)。
WebUI 的隱藏或停用仍僅是 UX；backend/Core 拒絕才是不受支援直接提交的安全邊界。

WebUI expected-model 欄位只是 safety guard 與 planning hint，不會改變由 IDN 選出的
live driver，也不會讓瀏覽器開啟不同的連線類型。目前已記錄的開放狀態以 connection 為範圍；
只有 Core exact matrix 中的 commands 開放：

- E36312A USB + system VISA
- E36312A LAN + system VISA
- EDU36311A USB + system VISA
- EDU36311A LAN + system VISA
- E3646A ASRL / RS-232 + system VISA
- PSM-2010 ASRL / RS-232 + system VISA

這些連線上只開放 Core product matrix 中明確的 commands。E3646A 與 PSM-2010 仍限於
ASRL / RS-232 + system VISA；兩者的 USB 與 LAN 路徑不在目前 scope 內。PSM-2010 開放
Core Product matrix 中確切的 23 個 model-aware commands，涵蓋 setpoint／output、
protection、snapshot／restore、ramp 與 software-sequence workflows；Powers Trigger
commands 仍不支援。

| Model | USB | LAN | ASRL / RS-232 |
| --- | --- | --- | --- |
| E36312A | accepted exact commands | accepted exact commands | N/A |
| EDU36311A | accepted exact commands | accepted exact commands | N/A |
| E3646A | not current scope | not current scope | accepted exact commands |
| PSM-2010 | not current scope | not current scope | accepted exact commands |

E36312A 的 `full` 在 read-only、output、protection、snapshot 與 trigger-list suites
之外現在包含 `software-sequence`。EDU36311A 的 `full` 在 read-only、output 與
protection suites 之外包含 `software-sequence`；EDU36311A 的 trigger/native LIST 與
snapshot/restore 維持停用。E3646A 的 `full` 仍是 `readonly`、`output` 與
`software-sequence`；E3646A 的 `ramp-list` 與 `sequence` 是軟體工作流程而非 native
LIST，且 protection、trigger/native LIST、snapshot/restore 與 completion-pulse 維持
停用。

## 測試

```powershell
uv run python -m pytest tests/webui -q -p no:cacheprovider
```

焦點指令分類與工作接收驗證：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\webui\test_webui_api_jobs.py -q -p no:cacheprovider
```

WebUI 工作測試（`tests/webui/test_webui_api_jobs.py`）包含 Core → WebUI 指令分類
drift guard，確保 `COMMAND_CONTRACTS` 中的所有正式 Core 指令皆明確劃分於
`SHARED_CORE_COMMANDS` 或 `WEBUI_UNSUPPORTED_COMMANDS`，防止無聲遺漏或重疊。

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

從上述 locked development environment 建置本機 shared Windows onedir bundle。
PyInstaller 由 `dev` extra 提供，不需要另外安裝：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows_bundle.ps1
```

建置完成後，請確認 shared bundle launcher 能回報套件版本：

```powershell
.\dist\powers-tool\powers-tool-webui-launcher.exe --version
```

數字欄位限制來自共用的[命令參數契約](../contracts/commands-parameter-contract.md)。在辨識出資源型號後，UI 會套用已驗證的官方獨立通道直流輸出額定值，並對已知超出額定的請求停用「Run」。未知的型號不會套用憑空發明的限制；Core 仍具有最終決定權。

## 文件導覽

- [WebUI 使用者指南](USER_GUIDE.zh-TW.md)：面向操作員的 WebUI 使用指南。
- [WebUI README](README.zh-TW.md)：此份有關 WebUI 行為、API、驗證及維護者的指南。
- [Web UI 變更規則](web-ui-change-rules.md)：面向維護者與 agent 的 UI 變更規則。
- [Localization Contract](localization-contract.md)：維護中的瀏覽器 localization 與
  presentation-only runtime contract。
