[English](README.md)

# Powers Tool

Powers Tool 是用於支援之直流電源供應器的 vendor-neutral Python 控制工具。
它提供單一可安裝發行套件 `powers-tool`，並保留三個獨立的
import package：`powers_tool_core`、`powers_tool_cli` 與 `powers_tool_webui`。

本架構是 vendor-neutral，但目前 Product support 僅限
[Supported Models](docs/core/supported-models.md) 所記載、已註冊且文件化的
model scope。Vendor-neutral 架構不代表任意或未知電源供應器都受支援；
未註冊或無法解析的 live hardware 會 fail closed。Vendor-specific driver、alias、
手冊、SCPI 行為、evidence
與 support table 保留正確的 vendor 名稱。

共用 Core runtime 負責 identity resolution、driver、SCPI 行為、安全性與 exact
live-support 決策。CLI 與 WebUI 是建立在 Core 之上的平行 adapter；Power Worker
則將相同的 Core command boundary 提供給本機 automation。專案透過 VISA 支援
USB、LAN 與明確設定的 RS-232/ASRL 通訊，並提供安全優先的 dry-run、simulator
與 machine-readable workflow。

Live hardware 會從 `*IDN?` 解析，且在文件所述 exact support scope 之外保持
fail closed。當前型號與 connection coverage 請參閱
[Supported Models](docs/core/supported-models.md)。

**Live hardware prerequisite：** 實體硬體操作需要另行安裝可由 PyVISA 載入的
VISA implementation/runtime。`powers-tool` 會安裝 PyVISA，但 PyVISA 是
Python API 層，不等於完整的 system 或 vendor VISA runtime。Powers Tool
不內含 Keysight IO Libraries Suite、NI-VISA 或其他廠商／系統 VISA runtime。
Simulator、dry-run 與一般 no-hardware validation 不需要實體儀器或 vendor VISA
runtime。安裝 VISA runtime 不會擴大支援範圍；live operation 仍受
[Supported Models](docs/core/supported-models.md) 所記載的 exact model、command、
transport、backend 與 required-feature scope 限制。

## 功能特性

- 透過 VISA 使用 USB、LAN 或明確的 RS-232/ASRL 設定控制支援的直流電源
  供應器。
- 可使用 `powers-tool` CLI 或本機 `powers-tool-webui` 儀表板。
- WebUI 支援 English 與繁體中文，可在 runtime 切換語言，且不需 reload；
  語言切換只改變 presentation，machine-facing values、API payloads 與 raw
  diagnostics 保持原值。
- 使用 dry-run 模式在開啟 VISA 前預覽會影響硬體的命令。
- 使用內建模擬器在沒有硬體時測試流程。
- 設定電壓/電流限制、控制輸出狀態，並讀取即時儀器資料。
- 透過共用 Core runtime 執行 ramp、ramp-list、sequence、trigger、
  snapshot、restore 與 protection 流程。
- 產生 JSON 與 JSONL 輸出，供自動化、agent 與 orchestrator 使用。
- 保持真實硬體輸出為選用 (opt-in)；預設測試與模擬流程不會啟用儀器輸出。

## 專案結構

此 repository 使用單一發行套件與單一版本號。在範例中，`<version>` 代表
根目錄 `pyproject.toml` 中的 `[project].version`：

- 發行套件：`powers-tool` `<version>`
- Core import：`powers_tool_core`
- CLI import：`powers_tool_cli`
- WebUI import：`powers_tool_webui`

import 路徑彼此獨立。請不要使用 `keysight_power.*` namespace package。

```text
src/
  powers_tool_core/
  powers_tool_cli/
  powers_tool_webui/
desktop/
  package.json
  package-lock.json
  main.cjs
tests/
  core/
  cli/
  webui/
  integration/
  packaging/
  tooling/
docs/
  core/                runtime 與 Product 支援文件
  cli/                 CLI 維護者與操作員文件
  webui/               WebUI 與 Desktop 文件
  contracts/           公開 protocol 與 workflow contracts
  help/                bundled Help presentation 與維護
  skill/               選用的 orchestration skill
  architecture/
  CONTRIBUTING.md
  testing-guidelines.md
scripts/
```

## 安裝

先開啟 PowerShell 並進入專案根目錄：

```powershell
cd path\to\powers-tool
```

如果尚未安裝 uv，先安裝：

```powershell
py -m pip install --user uv
```

確認 uv 可用：

```powershell
uv --version
```

在專案資料夾建立虛擬環境：

```powershell
uv venv .venv
```

依照 `uv.lock` 同步可重現的開發與測試環境：

```powershell
uv sync --all-extras --link-mode=copy
```

CI 或嚴格本機檢查可要求已提交的 lock file 不被改動：

```powershell
uv sync --all-extras --locked --link-mode=copy
```

本專案支援 Python `>=3.10`。`uv venv .venv` 會使用可用的相容 Python。
如果需要指定版本，請明確指定：

```powershell
uv venv .venv --python 3.12
```

lock file 將本機專案記錄為 `powers-tool`。安裝的 command wrappers 為
`powers-tool`、`powers-tool-webui` 與 `powers-tool-webui-launcher`；舊有的
distribution、package 與 command 名稱不是相容 alias。

Windows 會建立虛擬環境 console wrapper，例如
`.\.venv\Scripts\powers-tool.exe` 與
`.\.venv\Scripts\powers-tool-webui.exe`。WebUI 啟動器的 wrapper 是
`.\.venv\Scripts\powers-tool-webui-launcher.exe`。

一般 setup 只需要既有 `uv sync` workflow。若 sync 成功但其中一個 wrapper
缺失或尚未更新，請在 repository 根目錄執行以下命令，強制 uv 重新安裝
`powers-tool` distribution 並重建 project console wrappers：

```powershell
uv sync --all-extras --link-mode=copy --reinstall-package powers-tool
```

安裝完成後，請使用 [CLI Quick Start](docs/cli/README.zh-TW.md#快速開始)
進行安全的 no-hardware 檢查，或參閱
[WebUI 使用者指南](docs/webui/USER_GUIDE.zh-TW.md) 啟動本機瀏覽器介面。

## 快速開始

以下入口都是安全的 no-hardware 或本機操作；不會搜尋 VISA resource，
也不會啟用儀器輸出。

執行 simulator CLI smoke：

```powershell
uv run powers-tool doctor --simulate --json
```

啟動本機 WebUI launcher：

```powershell
uv run powers-tool-webui-launcher
```

啟動 source-mode Electron Desktop shell：

```powershell
Set-Location .\desktop
npm ci
npm start
```

詳細 CLI 操作請參閱 [CLI README](docs/cli/README.zh-TW.md)；瀏覽器與 Desktop
操作請參閱 [WebUI 使用者指南](docs/webui/USER_GUIDE.zh-TW.md)。

## 內建說明

Powers Tool 內建產品 Help，不需要另外開啟 repository 文件：

- CLI：`powers-tool user-guide`
- Traditional Chinese CLI Help：`powers-tool user-guide --language zh-TW`
- WebUI/Desktop：使用右上角的 `Help`。

Bundled Help 由本機提供，並與已安裝或已發行的產品版本相匹配。

## 建置

建置 wheel 與 source distribution。這會使用前面安裝的 `dev` extra 中的
`build` 套件：

```powershell
.\.venv\Scripts\python.exe -m build
```

這只會產生一個 Python 發行套件：

```text
dist\powers_tool-<version>-py3-none-any.whl
dist\powers_tool-<version>.tar.gz
```

Product distribution inspector 會排除 repository validation scripts、private
fixtures、candidate evidence 與 internal-only tests，並驗證 Python wheel 與
source distribution；Desktop application 會另外組裝至 Windows ZIP。

請先準備包含 PyInstaller 的 locked development environment，再建置 Windows
application artifacts：

```powershell
uv sync --all-extras --locked --link-mode=copy
```

建置包含 CLI、WebUI 啟動器與 private Desktop Host 的 Windows shared onedir bundle：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows_bundle.ps1
```

Windows WebUI Launcher 使用 Tkinter，因此用於建置 shared Windows bundle
的 Python 環境必須提供可正常使用的 Tcl/Tk runtime。建置腳本會在啟動
PyInstaller 前先檢查這項 prerequisite。

預設情況下，此命令會產生包含三個執行檔與一個共用 supporting-files
目錄的 application directory：

```text
dist\powers-tool\
  powers-tool.exe
  powers-tool-webui-launcher.exe
  powers-tool-webui-host.exe
  _internal\
```

這個 shared Windows onedir bundle 包含 CLI、WebUI Launcher，以及供 Desktop
shell 使用的 private Desktop Host。`powers-tool-webui-host.exe` 不是新的
公開 CLI entry point；三者共用同一個 `_internal` 目錄。

本機 `powers-tool-webui-launcher.exe` 與已安裝的
`powers-tool-webui-launcher` console entry point 分開；兩者都使用現有的
`powers_tool_webui.launcher:main` launcher implementation。

Source-mode Desktop shell 使用 Electron 呈現現有 WebUI，不建立第二套
WebUI 實作。從 repository root 執行：

```powershell
Set-Location .\desktop
npm ci
npm start
```

Desktop shell 會啟動 private WebUI Host，開啟初始 1920x1080 並依 primary
display work area 進行 clamp，並支援 System、Light、Dark 主題。選定的主題
會套用至主要的 panels、cards、fields 與 status surfaces，不只改變頁面背景。
深色主題下，主要控制項、狀態文字，以及不可用或停用的控制項，會在深色
surface 上維持足夠辨識度。
允許同時執行多個 Desktop instance，因此不同 instance 可以操作不同的實體儀器；
但不同 client 仍不可同時操作同一個 physical instrument resource。

建置整合 shared Python bundle 的 Electron Windows directory application：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1
```

產生的 application directory 包含 `Powers Tool.exe`、三個 Python 執行檔、
Electron runtime files，以及位於 root 的單一共用 `_internal` 目錄。正式
Windows release 會將同一個 application directory 放入帶版本號的 ZIP。

在不接觸硬體的情況下，快速測試建置完成的 CLI 執行檔：

```powershell
.\dist\powers-tool\powers-tool.exe --version
.\dist\powers-tool\powers-tool.exe doctor --simulate --json
```

建置包含 wheel、sdist 與 unified Desktop Windows ZIP 的版本化發佈資料夾：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

這會產生以所選專案版本命名的發佈產物：

```text
release\<version>\powers-tool-<version>-windows-x64.zip
release\<version>\powers_tool-<version>-py3-none-any.whl
release\<version>\powers_tool-<version>.tar.gz
release\<version>\checksums.txt
```

ZIP 內只有一個 `powers-tool-<version>\` application root，包含 Electron
shell、CLI、WebUI launcher、private WebUI Host、Electron runtime files，以及
共用的 `_internal\` 目錄。`checksums.txt` 只計算 ZIP、wheel 與 sdist 的
hash。

正式 release acceptance 必須從 clean、fully committed source working tree 執行。
腳本使用既有 `.venv`、檢查 working tree 與 committed HEAD 一致並驗證 `uv.lock`，
完整執行一次 no-hardware 測試套件，接著呼叫一次 `build_release.ps1` 產生最終
版本化 artifacts，檢查 wheel、sdist 與 unified Desktop ZIP，在單一乾淨環境安裝
最終 sdist，確認所有 console entry points、驗證 checksums、對每個 Product-active
model 執行快速 CLI smoke，對 capability 代表性 model 執行較深的 CLI workflow，
並檢查 simulator `PlanOnly` contract。
新的 model 只有在引入尚未被代表的 capability family 或硬體結構時，才需要另一個
deep representative。腳本會在 ignored 的輸出根目錄下寫出 `report.json` 與
`summary.md`：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\release-acceptance.ps1
```

每個 recorded command 都會先顯示 `[start]`，完成後顯示 `[passed]` 或
`[failed]` 以及 `duration=<seconds>s`。child-process stdout/stderr 仍會在命令
完成後收集並印出或寫入 acceptance output，不會逐行即時串流。

若提供 `-OutputRoot`，必須解析到 repository 內的 `.tmp_tests` 或其子目錄。

此 acceptance script 不會進行 VISA discovery、開啟 resource 或送出 SCPI；
執行期間 HEAD 或 source working tree 變動會使其失敗。它不會發佈 release，
也不會重新命名 repository。

## 測試

Pytest 預設使用已忽略的 repository-local `.tmp_pytest` 目錄，因此無硬體測試
不依賴 Windows 系統暫存目錄權限。請從 repository 根目錄執行 pytest。
如果單次執行需要獨立 basetemp，請使用 `--basetemp .tmp_tests/<purpose>`。
不要把 pytest 暫存資料或測試產物寫到 `Local/`。

開發迭代時可先跑 focused tests：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\cli -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\webui -q -p no:cacheprovider
```

執行 CI 使用的靜態檢查：

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
```

執行 fast no-hardware 測試：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --ignore=tests\cli\test_cli_wrappers.py --ignore=tests\packaging\test_release_acceptance.py
```

CI 也會檢查 tracked WebUI JavaScript syntax、執行必要的 WebUI Node runtime
tests，在 Linux 與 Windows 建置 Python package，並執行 package import 以及
CLI、WebUI、Launcher smoke。Windows Python 3.13 job 也會建置 Desktop directory。
Wrapper contracts 會在獨立的 Windows job 執行。完整的
`release-acceptance.ps1` gate、distribution inspection 與 release acceptance
tests 仍保留給 release validation，不屬於一般 pull-request CI。

Scripted no-hardware、live validation 與 release acceptance 工作流程記錄在
[CLI README](docs/cli/README.zh-TW.md#scripted-validation)。Hardware validation
屬於明確 opt-in，且需要使用者提供 VISA resource。

## Codex／Agent Skill

專案提供選用、需手動安裝的
[Powers Tool CLI 調度 Skill](docs/skill/README.zh-TW.md)，供合約導向的 CLI
與 Power Worker workflow 使用。它是附屬範本，不是 Powers Tool runtime
功能，也不包含在 Python package、standalone executable、build、release 或
CI 中。

## 文件

- [Core README](docs/core/README.zh-TW.md)
- [Supported Models](docs/core/supported-models.md)
- [CLI 使用者指南](docs/cli/USER_GUIDE.zh-TW.md)
- [CLI README](docs/cli/README.zh-TW.md)
- [WebUI README](docs/webui/README.zh-TW.md)
- [WebUI 使用者指南](docs/webui/USER_GUIDE.zh-TW.md)
- [Web UI Change Rules](docs/webui/web-ui-change-rules.md)
- [Help 維護](docs/help/README.md)
- [Repository Layout](docs/architecture/monorepo-layout.md)
- [測試指南](docs/testing-guidelines.md)
- [Public Contracts](docs/contracts)
- [Power CLI JSONL Contract](docs/contracts/power-cli-jsonl-contract.md)
- [Power Worker Contract](docs/contracts/power-worker-contract.md)

## 貢獻

貢獻、開發 ownership、no-hardware 測試期望、contributor validation-artifact
workflow 與變更規則請參閱 [CONTRIBUTING](docs/CONTRIBUTING.md)。變更 live
model、command、transport 或 backend 支援時，適用情況下需要可審閱的真機
evidence。

## 授權條款與免責聲明

本專案採用 MIT License。詳見 [LICENSE](LICENSE)。

應用程式圖示：Powers Tool 應用程式圖示使用 ChatGPT 中的 OpenAI 圖像生成功能產生，
並由專案維護者審閱及選定。

本專案是獨立且非官方的專案，未與支援之儀器製造商或 vendor 建立從屬、
背書或贊助關係。

Powers Tool 所提及的所有製造商名稱、產品名稱、型號名稱與商標，其權利均歸各自權利人所有。

使用者需自行遵守支援之 vendor 所適用的軟體、driver、儀器與文件授權條款。
