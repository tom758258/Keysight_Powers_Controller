# Powers Tool WebUI 使用者指南

本指南針對取得已建置之 WebUI 啟動器並使用它來檢查與控制支援的 Keysight 直流電源供應器的操作員。本指南避開了開發人員細節，專注於一般的本機 WebUI 工作流程。開發人員環境設定、API 行為、驗證以及 UI 變更邊界，皆記錄於 [WebUI README](README.zh-TW.md) 與 [Web UI 變更規則](web-ui-change-rules.md)。

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

本機 shared bundle 與已解壓的 Desktop application 都包含 GUI launcher；
`.venv\Scripts\powers-tool-webui.exe` 是 FastAPI server wrapper，
`.venv\Scripts\powers-tool-webui-launcher.exe` 是已安裝的 GUI launcher wrapper。
這些 wrappers 與 bundle/release artifacts 使用相同的 launcher implementation，
但用途與所在路徑不同。


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

開發人員或簽出原始碼的使用者應參閱 [WebUI README](README.zh-TW.md) 以了解終端機指令、驗證、API 與建置細節。

WebUI 執行於與儀器連接的同一台 Windows 電腦上。它是一個本機工具，而非雲端服務。關閉瀏覽器分頁並不一定會停止伺服器；使用完畢後，請使用啟動器中的 `Quit` 或停止終端機程序。

## Desktop Shell

Source checkout 使用者可以從 `desktop/` 執行 Electron Desktop shell：

```powershell
Set-Location .\desktop
npm install
npm start
```

這個 shell 顯示現有 WebUI，並使用 private WebUI Host。primary display 足夠
時，視窗初始大小為 1920x1080；否則會 clamp 到 primary display work area。
允許多個 Desktop instance 操作不同的實體儀器，但不可同時讓不同 client
操作同一個 physical instrument resource。

## 瀏覽器語言

WebUI 支援 English 與繁體中文。請使用主介面的右上方單一語言切換按鈕；目前
語言為 English 時按鈕顯示 `繁體中文`，目前語言為繁體中文時顯示 `English`。

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

Header 也提供 System / Light / Dark 主題控制。System 會遵循作業系統的
`prefers-color-scheme`。主題偏好會透過同一個 loopback browser 的
`powers-tool.webui.theme` cookie 保留；Electron Desktop shell 會使用該 cookie
同步 native window theme。

以下 machine-facing values 保持原值且不翻譯：command IDs、model IDs、VISA
resources、API payload/schema、SCPI、raw diagnostics 與原始錯誤內容。

English 是 source/fallback locale。語言偏好會保留在相同瀏覽器中；如果 browser
storage 不可用，WebUI 會安全 fallback，不影響正常操作。

## 畫面總覽

此頁面為儀器控制主控台。主要區域包含：

- `VISA resource`：命令工作所使用的明確儀器位址。
- `Live resource`：由「掃描裝置」(Scan Device) 工作流程探索到的資源。
- `Scan Device` (掃描裝置)：搜尋實機存活的 VISA 資源並填入選擇器。
- `Live Data` (即時資料)：唯讀的通道卡片與狀態指示燈。
- `Basic command` (基本命令)：各通道的電壓 (Voltage)、電流 (Current)、設定 (Set) 及輸出開啟 (ON) 控制項。
- `Show more commands` (顯示更多命令)：開啟進階命令列與生成的表單。
- `Job Result` (工作結果)：最近提交的工作及其狀態。
- `Result Detail` (結果詳情)：所選工作的原始 JSON 細節。

影響硬體的工作依然需要明確指定與確認。

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

`Scan Device` (掃描裝置) 會執行啟用實機資源過濾的 WebUI 資源探索工作。它的目的是顯示目前能回應的資源，而非過時的 VISA 快取項目。

選擇資源後會將其複製到 `VISA resource` 輸入框中。您也可以手動輸入由操作員提供的已知 VISA 資源。

Device options（裝置選項）包含執行模式；在 Real 模式還會顯示 `Expected model`。一般實機操作請保留 `Auto-detect`，由連線儀器的 `*IDN?` 決定實際型號。齒輪圖示左側的 **Supported devices / 支援裝置** 按鈕會開啟唯讀清單，顯示目前 Product-open 且 WebUI 可使用的 `system_visa` 連線（廠商、型號、連線方式）。選擇 `Require <model>` 時，它只用於前端規劃與預期型號安全護欄：若連線儀器不符，Core 會在設定或寫入 SCPI 前拒絕；它不會強制選用該型號的驅動程式。

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

當有最新的 Live Data 時，ON 控制項會反映其狀態。未亮的 ON 控制項代表 OFF (關閉) 或未知；除非 Live Data 是最新狀態，否則不代表已確認的 OFF 狀態。真實影響輸出的動作需要經過確認。

啟用輸出前：

1. 確認所選通道。
2. 設定安全的電流限制與電壓。
3. 透過 Live Data 或讀回 (readback) 確認數值。
4. 僅在連接的 DUT 能承受該要求時，才啟用輸出。

## 進階命令 (Advanced Commands)

使用 `Show more commands` 來開啟命令列與生成的命令表單。命令依用途分組，例如 Output (輸出)、Output Workflows (輸出工作流程)、Protection (保護)、Trigger (觸發)、Snapshot (快照) 以及 Advanced Diagnostics (進階診斷)。

該表單由 WebUI 命令 metadata 生成。必填欄位必須在 Run (執行) 之前填寫。被停用的命令或控制項表示不支援的型號、模式或不在 WebUI 的支援範圍內。

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

某些編輯器支援 JSON Load/Save (載入/儲存)，包括 Sequence (序列)、Ramp List (斜坡清單) 與 Trigger List (觸發清單) 工作區。請使用這些功能來處理可重複的工作流程，並保持儲存的檔案中沒有私人的實驗室資源字串，除非您刻意要將其限制為本機專用。

## 工作結果 (Job Results)

送出的命令會出現在 `Job Result` 中。選擇一個工作以在 `Result Detail` 中檢查其狀態與原始 JSON。

典型的工作狀態包括 accepted (已接受)、started (已啟動)、progress (進行中)、finished (已完成)、failed (失敗)、cancel requested (已請求取消) 與 cancelled (已取消)。失敗的工作應在結果 payload 中包含錯誤訊息。

Simulate (模擬) 與 dry-run (預演) 工作有助於在實機硬體執行前檢查 payload 形狀。真實影響輸出的工作需要確認。

## 停止與取消

如果工作尚未啟動，取消動作能很快完成。如果真實的硬體工作已經在執行中，取消將採協作模式：WebUI 請求取消並等待 Core 清理完成。

除非有外部安全考量，否則請勿關閉瀏覽器或強制終止程序來打斷正常的清理過程。清理與 release/local (解除遠端/轉為本機) 的行為由 Core 處理，可能需要一些時間。

硬體命令處於活動狀態時，啟動器會封鎖 `Quit` (離開)。請先在瀏覽器中停止或取消命令，然後等待清理完成再退出啟動器。

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
- USB 或 LAN 已連接；
- VISA 驅動程式可看到儀器；
- 沒有其他程式佔用資源；
- 此電腦上有正確的 VISA 後端。

您仍可手動輸入已知的 VISA 資源。

### 執行 (Run) 被封鎖

閱讀畫面上可見的驗證訊息與 Result Detail。常見原因為缺少資源、缺少必填命令欄位、不支援的型號、不安全的設定點，或影響輸出的實機命令缺少確認。

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

## 更多 WebUI 文件

- [WebUI README](README.zh-TW.md)：API 行為、驗證、開發環境設定與維護者邊界。
- [Web UI 變更規則](web-ui-change-rules.md)：針對開發人員與 agent 的 UI 變更規則。
-
