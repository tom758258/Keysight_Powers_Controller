# Powers Tool WebUI 使用者指南

本指南供取得已建置之 WebUI 啟動器的操作員使用，說明正常產品操作、畫面工作流程與安全行為。Powers Tool 的架構不綁定特定廠牌；目前硬體支援範圍以 [支援型號](../core/supported-models.zh-TW.md) 所記載的 Product scopes 為準；未知或未註冊的 live hardware 會 fail closed。

## 啟動 WebUI

使用本機 shared onedir build 時，請雙擊 bundle 中的 WebUI 啟動器：

```text
dist\powers-tool\powers-tool-webui-launcher.exe
```

若要從 PowerShell 確認本機 bundle launcher 版本：

```powershell
.\dist\powers-tool\powers-tool-webui-launcher.exe --version
```

正式 Windows release 請解壓縮帶版本號的 Desktop ZIP，並從 application root
啟動 Desktop shell：

```text
powers-tool-<version>-windows-x64.zip
\powers-tool-<version>\Powers Tool.exe
```

解壓後的 application root 包含 CLI、WebUI launcher、private WebUI Host、
Electron runtime files，以及共用的 `_internal` 目錄。

不帶命令列選項時，啟動器會在 `127.0.0.1` 上從 port `7999` 開始，最多嘗試
100 個候選 port，通常到 `8098`。每個候選 port 都會透過實際 bind 測試；無論
該 port 是被另一個 Powers Tool WebUI 或其他服務占用，都只會跳過，不會開啟
已存在於該 port 的服務。新啟動的 WebUI 通過 `/api/health` readiness 後，才會
開啟瀏覽器；啟動器接著顯示包含實際 URL、Running 狀態與 `Quit` 的精簡 Running
視窗，port 設定與 `Start` 會隱藏。

只有所有自動候選 port 都因 address-in-use 失敗時，才會顯示 manual fallback
視窗。請輸入其他本機 port 並點擊 `Start`；如果手動輸入的 port 也因
address-in-use 失敗，視窗會保留以便編輯與重試。重試成功後會回到精簡 Running
視窗。

從 PowerShell 使用 `--port` 可要求固定 port；除非同時提供 `--auto-port`，否則
不會自動切換到其他 port：

```powershell
.\dist\powers-tool\powers-tool-webui-launcher.exe --port 9000
.\dist\powers-tool\powers-tool-webui-launcher.exe --port 9000 --auto-port
```

固定 port 衝突會回報選定的 port、完成清理並以非零狀態結束，不會改用其他 port
或開啟 manual port 視窗。其他 bind、startup、application、server exit 或
readiness error 也會保留原始細節、完成清理並結束，不會開啟 manual fallback。
只有自動 address-in-use exhaustion 會開啟 manual fallback，且只有另一個
address-in-use error 才會讓 fallback 保持開啟。

如果瀏覽器沒有自動開啟，請先開啟啟動器顯示的實際 URL。若實際使用預設 port，
該 URL 會是：

```text
http://127.0.0.1:7999/
```

WebUI 執行於與儀器連接的同一台 Windows 電腦上。它是一個本機工具，而非雲端服務。關閉瀏覽器分頁並不一定會停止伺服器；使用完畢後，請使用啟動器中的 `Quit`。

## 內建說明

請點擊右上角的 `Help` 連結，在瀏覽器中開啟內建 Help。在 Desktop shell 中，Help
會從外部交由系統預設瀏覽器開啟。Help 由同一套 Powers Tool WebUI 在本機提供，
不需要外部文件網站。English WebUI 會開啟 English Help；Traditional Chinese
WebUI 會開啟 Traditional Chinese Help。兩者使用的都是 Powers Tool 本機提供的
同一套內建 Help。

## Desktop Shell

`Powers Tool.exe` 是正式 release 中的 Desktop shell。它顯示同一套 WebUI，
並使用 private WebUI Host。一般畫面、命令、工作流程與安全行為與 WebUI 相同。
primary display 足夠時，視窗初始大小為 1920x1080；否則會 clamp 到 primary
display work area。允許多個 Desktop instance 操作不同的實體儀器，但不可同時讓
different client 操作同一個 physical instrument resource。

## 瀏覽器語言

主介面右上方提供「外觀」與「語言」兩個標示清楚的控制項。語言按鈕會顯示
目前 locale：English 顯示 `English`，繁體中文顯示 `繁體中文`；accessible name
則描述點擊後要切換到的語言。

切換會在 runtime 立即生效，不需要 reload page，並保留目前頁面狀態，包括：

- execution mode；
- resource 與 identity selection；
- command form；
- workflow editor；
- Job History 與 Job Result；
- Result Detail；
- Live Data 顯示狀態。

語言切換只改變瀏覽器 presentation，不會建立 HTTP request、Job 或 workflow
action，也不會建立、停止或以其他方式影響 EventSource。

外觀控制會顯示目前的 System / Light / Dark 主題偏好，點擊後依序切換至下一個
偏好。System 會遵循作業系統的 `prefers-color-scheme`。主題偏好會透過同一個 loopback browser 的
`powers-tool.webui.theme` cookie 保留；Electron Desktop shell 會使用該 cookie
同步 native window theme。選定的主題會套用至主要的 panels、cards、fields
與 status surfaces，不只改變頁面背景。
深色主題下，主要控制項、狀態文字，以及不可用或停用的控制項，會在深色
surface 上維持足夠辨識度。

以下 machine-facing values 保持原值且不翻譯：command IDs、model IDs、VISA
resources、API payload/schema、SCPI、raw diagnostics 與原始錯誤內容。

English 是 source/fallback locale。語言偏好會保留在相同瀏覽器中；如果 browser
storage 不可用，WebUI 會安全 fallback，不影響正常操作。

## 畫面總覽

此頁面是儀器控制主控台，主要區域包括：

- `Execution mode`：頁面內的 Real、Simulate 或 Dry-run 模式選擇；重新載入頁面時一律回到 Real。
- `VISA resource`：Real 命令工作所使用的明確儀器位址。
- `Live resource`：由 `Scan Device` 工作流程探索到的資源。
- `Scan Device`：搜尋目前可回應的 VISA 資源並填入選擇器。
- `Live Data`：唯讀的通道卡片與狀態指示。
- `Basic command`：各通道的 Voltage、Current、Set 與輸出控制。
- `Show more commands`：開啟進階命令列與自動生成表單。
- `Job Result`：最近提交的工作及其狀態。
- `Result Detail`：所選工作的原始 JSON 詳細資料。

所有會影響硬體的工作仍必須明確提出，並通過相應的授權、確認與 Core 安全檢查。

## 首次使用

在檢查新電腦、VISA runtime、連線或電源供應器設定時，請使用此流程。

1. 確認電源供應器與連接的受測物 (DUT) 均可安全查詢。
2. 啟動 WebUI 並開啟本機瀏覽器頁面。
3. 點擊 `Scan Device`。
4. 選擇目標實機資源或將其複製到 `VISA resource`。
5. 啟動 `Live Data` 以確認唯讀通訊與通道狀態。
6. 在執行任何影響輸出的命令前，請先檢閱型號身分、輸出狀態、程式設定點以及保護狀態。
7. 只有在目標通道與設定點確認安全後，才使用 Basic command (基本命令) 或進階命令列。

當可能連接多台儀器時，請勿用猜測的方式選擇資源。

## 資源掃描

`Scan Device` 會執行啟用實機資源過濾的 WebUI 資源探索工作。它的目的是顯示目前能回應的資源，而非過時的 VISA 快取項目。

第一個有效結果會自動選取並複製到 `VISA resource`，同時執行一次唯讀身分工作，以評估 exact Product live support。改選其他實機資源時會重新執行相同的評估。這個評估不會啟用輸出、不會修改儀器設定，也不需要實機寫入授權。您仍可手動輸入由操作員提供的已知 VISA 資源。

Device options 包含執行模式；在 Real 模式還會顯示 `Expected model`。一般實機操作請保留 `Auto-detect`，由連線儀器的 `*IDN?` 決定實際型號。齒輪圖示左側的 **Supported devices / 支援裝置** 按鈕會開啟唯讀清單，顯示目前 Product-open 且 WebUI 可使用的 `system_visa` 連線（廠商、型號、連線方式）。選擇 `Require <model>` 時，它只用於前端 capability 規劃，並作為 expected-model guard 送出：連線儀器的 `*IDN?` model 必須相符，才會進行 setup 或 write SCPI；該選擇不會強制使用該型號的 driver。Device / Resource summary 會將偵測到的 live model 與 Expected model 選擇分開顯示，例如 `live E3646A / Auto-detect` 或 `live E3646A / Require E36312A`。

一般型號選單由 Core 的 Product-active metadata 產生；目前支援的型號與 exact connection／backend scopes 以 [支援型號](../core/supported-models.zh-TW.md) 為準。不支援的直接 model 提交仍會被 WebUI backend 與 Core 拒絕。Auto-detect 在有可用 metadata 時仍可使用偵測到的 live model 資訊，但前端狀態永遠不會覆寫 Core 由 IDN 選出的 live driver。

在 Product-open scope 上成功完成唯讀身分評估後，Device / Resource summary 會顯示偵測到的 transport/backend scope，不含命令數統計。diagnostic 可以顯示命令為 pending，但不會啟用它們。變更 `Expected model` 只更新規劃指引；它不會改寫偵測到的 model 或連線 scope。WebUI 使用正常 Product policy 與預設 system-VISA backend；沒有 backend selector 或 validation mode。Pending metadata 只在實際 runtime transport/backend 符合已註冊 pending scope 時顯示。

若身分評估在未知或已移出範圍（de-scoped）的儀器上成功，WebUI 會顯示無法解析出 Product-open live scope，而不是顯示 unevaluated 狀態。一般 model-aware live commands 維持停用，且 `Expected model` 不符時 diagnostic 仍會失敗。

如果未出現實機存活的資源，請檢查儀器電源、纜線、VISA 驅動程式可見度，以及是否有其他程式佔用了該儀器。

## 即時資料 (Live Data)

`Live Data` 是一個唯讀監控器。它會定期讀取所選資源，更新通道卡片，並顯示 WebUI、命令與即時監控狀態。

在執行輸出命令前使用 Live Data 來確認：

- 預期的型號有回應；
- 測量到的電壓/電流看起來合理；
- 清楚了解目前的程式設定點；
- 確知目前的輸出狀態；
- 支援 OVP/OCP 時可看見其觸發 (trip) 狀態。

成功的實機硬體命令執行後，Live Data 可能會更新一次。它維持唯讀屬性，應被視為所顯示儀器狀態的來源真相。
PSM-2010 的 CH1 卡片會額外顯示目前實際 LOW/HIGH 輸出檔位的唯讀 badge。尚未知或尚未取得資料時顯示 `--`；其他型號不顯示此 badge。

## 基本命令 (Basic Commands)

Basic command 面板用於常見的各通道設定點與輸出動作。

電壓 (Voltage) 與電流 (Current) 欄位允許留空。空白欄位會被省略，並由 Core 保持不變。若要同時設定兩者，請填寫這兩個欄位並點擊該通道的 `Set`。

輸出控制會依最新 Live Data 顯示下一個動作：輸出為 OFF 或未知時顯示 `Turn on`，輸出為 ON 時顯示 `Turn off`。亮起仍表示最新 Live Data 判定輸出為 ON；未亮不代表已確認 OFF，除非 Live Data 仍是最新狀態。在 Real 模式，只要存在非空白 VISA 資源，`Enable real hardware writes for this resource` 預設會啟用並勾選。在 Device options 取消勾選可為目前的資源與身分 context 停用寫入。選擇或輸入其他資源、變更 Expected model、偵測到不同型號，或離開後回到 Real mode，都會建立新的 context 並重新以允許寫入為預設。沒有資源時，該選項停用且不存在寫入授權。Device / Resource 標題會顯示 `Real · Writes locked` 或 `Real · Writes enabled`；它是狀態指示，不是控制項。

E3646A 不支援 CH1 與 CH2 各自切換輸出。兩個通道的輸出控制會顯示 `Controlled by ALL`；請使用 ALL 控制同時開啟或關閉兩個通道。CH1／CH2 的 Voltage、Current 與 Set 仍可分別設定。

啟用輸出前：

1. 確認所選通道。
2. 設定安全的電流限制與電壓。
3. 透過 Live Data 或讀回 (readback) 確認數值。
4. 僅在連接的 DUT 能承受該要求時，才啟用輸出。

## 進階命令 (Advanced Commands)

使用 `Show more commands` 來開啟命令列與生成的命令表單。命令依用途分組，例如 Output (輸出)、Output Workflows (輸出工作流程)、Protection (保護)、Trigger (觸發)、Snapshot (快照) 以及 Advanced Diagnostics (進階診斷)。

該表單由 WebUI 命令 metadata 生成。必填欄位必須在 Run (執行) 之前填寫。被停用的命令或控制項表示不支援的型號、模式或 WebUI scope。

停用命令的說明是刻意的 feature-lock 指引，不是隨機的 UI 錯誤。Product LIVE support 以偵測到的 model、command、transport 與 backend 為 exact scope。read-only、output、protection 或 trigger 的 feature family 不代表該 family 中每個命令都是 product-open；missing 與 pending scopes 都會 fail closed。E3646A 的 Product LIVE 目前僅限 ASRL／RS-232 + system VISA；其軟體 `ramp-list` 與受限步驟的 `sequence` 不是 native LIST。

Sequence actions 與 Trigger Step/List sources 也有 exact feature status。Product-open command 不會自動開放缺乏 metadata 的未來 action 或 source。瀏覽器可能顯示這份附加 inventory，但 Core 會驗證實際請求，並在一般 Product mode 下讓 missing 或 pending features 維持關閉。

命令列會省略已可用命令的重複正向 live-support 標籤；disabled、pending、model-unsupported、unresolved、missing exact scope 與 `Connection scope not evaluated` 等原因仍會顯示。Pending commands 維持停用：pending 表示 instrument profile 認得該命令，但 exact connection/backend evidence 尚非 Product-open。這些瀏覽器狀態僅供指引。Core 會對每個提交的 live job（包括直接或過期的 API 請求）重新執行 exact policy 檢查。

Offline-only utilities 不是 identity/status diagnostics，也不會顯示為 Product-open live commands。

WebUI 僅提供 Product 模式：沒有 validation override，raw job 提交也無法把 pending evidence 變成正常 product support。

某些編輯器支援 JSON Load/Save (載入/儲存)，包括 Sequence (序列)、Ramp List (斜坡清單) 與 Trigger List (觸發清單) 工作區。請使用這些功能來處理可重複的工作流程，並保持儲存的檔案中沒有私人的實驗室資源字串，除非您刻意要將其限制為本機專用。

Ramp、Ramp List 與 Sequence 提供 `Enable loop` 核取方塊。啟用後會出現 inline Loop count，範圍 2 到 10,000；這是工作流程的總執行次數，不是額外重複次數。關閉 Loop 會隱藏欄位，代表執行一次。Ramp 與 Ramp List 只有在 Loop 啟用時才於 Pulse timing 提供 Loop complete。Ramp List 儲存 v5 文件、Sequence 儲存 v2 文件，兩者都明確寫入 `loop_count`，包含單次執行的 1。

Ramp 的 Channel selector 會依所選或偵測到的型號顯示各通道、支援的通道組合，
以及多通道型號的 All。所選通道共用相同電流與電壓設定並以 lockstep 前進；只有
每個所選通道都成功後，該電壓步驟才算完成。
選取通道組合或 All 時，Channel 與 Current 下方會顯示一則全寬提示，說明共用參數與
lockstep 行為。選取單一通道時不會顯示提示，也不會在 Ramp 表單留下空白列。

Ramp List 可載入 v2 至 v5，儲存時一律輸出 v5。每個 Segment 都有自己的通道組合
selector；All 會寫成明確的 channel list。多通道 Segment 以 lockstep 前進，progress
與脈波仍以 logical voltage step 計算，不會乘上通道數；pulse trigger channel 由 Core
內部選擇。E3646A 使用自動啟用輸出時，Ramp List 會先為清單中會使用到的每個通道
寫入其第一組安全設定值，再一次啟用全域輸出。

## 工作結果 (Job Results)

送出的命令會出現在 `Job Result` 中。選擇一個工作以在 `Result Detail` 中檢查其狀態與原始 JSON。

典型的工作狀態包括 accepted (已接受)、started (已啟動)、progress (進行中)、finished (已完成)、failed (失敗)、cancel requested (已請求取消) 與 cancelled (已取消)。失敗的工作應在結果 payload 中包含錯誤訊息。

Device options 提供 Simulate 與 Dry-run 控制項。這兩種模式會停用 VISA resource、掃描、序列設定與 Live Data，且不會開啟或鎖定真實硬體。Simulate 只接受 physical planning model；Dry-run 可接受 physical planning model 或 planning profile。對 live raw API jobs，`runtime.expected_model_id` 是可選的 canonical safety guard，會在 manufacturer 加 model 的 IDN 解析後檢查；不符時在 setup 或 write SCPI 前失敗。瀏覽器從 scan/job IDN metadata 學習 live model 支援；fake resource 字串不代表任何 model。瀏覽器的停用或隱藏狀態不是安全邊界；當 model、command 或 mode 不受支援時，直接提交 `/api/jobs` 仍會被 WebUI backend 與 Core 拒絕。

Raw runtime JSON 採嚴格型別：boolean 欄位要求 JSON boolean，諸如 `"false"` 的字串會被拒絕而不是被當成確認。Raw job 的 channel 要求正整數 JSON integer；exact `"all"` 只被支援全通道選擇的命令接受。boolean、浮點數與數字字串的 channel 值都會被拒絕。
Model-specific dry-run/simulator 請求若沒有明確或 deterministic-SIM planning identity，會在 job 建立前被拒絕。Snapshot restore 只接受具備 `schema_version: 2`、`kind: "powers-tool-snapshot"`、且分開記錄 reported 與 canonical resolved identity 的文件。Restore request flags 與保存的 output/protection 狀態也要求 exact JSON boolean。snapshot 的 `outputs`、`readback` 與 `protection_settings` 區塊必須非空且包含完全相同的 channels；每個通道都需要一筆 protection record，即使其選用值都是 null。未知與刻意不支援的 `/api/jobs` 命令會在 job 或背景任務建立前被拒絕。

## 停止與取消

如果工作尚未啟動，取消動作能很快完成。如果真實的硬體工作已經在執行中，取消將採協作模式：WebUI 請求取消並等待 Core 清理完成。

除非有外部安全考量，否則請勿關閉瀏覽器或強制終止程序來打斷正常的清理過程。清理與 release/local (解除遠端/轉為本機) 的行為由 Core 處理，可能需要一些時間。

`Quit` 會要求取消目前所有 WebUI 工作（包含 Live Data），並等待正常清理完成後才停止本機伺服器。若清理或伺服器關閉無法在逾時前完成，啟動器會保持開啟並顯示 `Shutdown incomplete`，讓您處理問題後再次嘗試。

## 常見問題

### 頁面無法載入

確認伺服器仍在執行，並開啟啟動器顯示的實際 URL。若實際使用預設 port，範例為：

```text
http://127.0.0.1:7999/
```

自動啟動可能選擇不是 `7999` 的 port，請以啟動器顯示的 URL 為準。

### 啟動器顯示 port 已被佔用

啟動器絕不會開啟已經占用候選 port 的服務。預設自動啟動會跳過 address-in-use
候選 port；固定 `--port` 發生衝突時會直接結束，不會選擇其他 port。若已開啟
manual fallback 視窗，請選擇其他 port，或停止占用所選 port 的服務後，再點擊
`Start`。

### Scan Device 找不到任何東西

檢查下列事項：

- 儀器已開機；
- USB、LAN 或適用的 ASRL／RS-232 連線已接妥；
- VISA 驅動程式可看到儀器；
- 沒有其他程式佔用資源；
- 此電腦已安裝正確且可載入的 VISA 後端。

您仍可手動輸入已知的 VISA 資源。

### 執行 (Run) 被封鎖

閱讀畫面上可見的驗證訊息與 Result Detail。常見原因為缺少資源、缺少必填命令欄位、不支援的型號或精確連線範圍、不安全的設定點，或實機影響輸出的命令缺少寫入授權／必要確認。
選擇 Expected model 不會解鎖停用的命令；它只用於 no-hardware 規劃，或在 Real 模式檢查連線儀器的 `*IDN?` model。

### 輸出按鈕看起來不是最新狀態

啟動或重新整理 Live Data。WebUI 會避免將過時的輸出狀態當成最新的事實來顯示。

### 命令顯示忙碌中

真實硬體命令由 WebUI 的硬體鎖定進行序列化。請等待目前的命令與清理完成，或僅在這是操作員刻意要做的動作時才進行取消。

### Live Data 回報過時或錯誤狀態

檢查資源、連線，以及是否有其他命令佔用了硬體 I/O。Live Data 不會覆蓋 (override) 真實的命令執行。

## 操作員安全注意事項

- 在執行影響輸出的命令前，請使用唯讀的 Live Data。
- 首次實機檢查應保持低電壓/電流，並明確指定通道。
- 在啟用輸出前，確認電流限制。
- 請將 `channel all` 視為刻意的多通道動作。
- 在理解觸發 (trip) 原因前，請勿清除保護。
- 將觸發與 LIST 工作流程視為進階操作。
- 在可行情況下，斷開 DUT 之前請停止或關閉輸出。

## 更多產品文件

- [支援型號](../core/supported-models.zh-TW.md)：目前 Product support matrix 與型號特定限制。
