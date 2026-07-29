[English](README.md)

# Keysight Powers

Keysight Powers 是用於 Keysight 直流電源供應器的 Python 控制工具。
專案提供單一可安裝發行套件 `keysight-powers` `<version>`，並保留三個
獨立的 import package：`keysight_power_core`、`keysight_power_cli` 與
`keysight_power_webui`。

本專案透過 VISA 支援 USB、LAN 與明確的 RS-232/ASRL 通訊，並提供命令列
工具與本機瀏覽器 WebUI。它適合需要明確安全檢查、模擬器支援，以及機器可讀
輸出的電源供應器工作流程。

## 功能特性

- 透過 VISA 使用 USB、LAN 或明確的 RS-232/ASRL 設定控制支援的 Keysight
  直流電源供應器。
- 可使用 `keysight-power` CLI 或本機 `keysight-power-webui` 儀表板。
- 使用 dry-run 模式在開啟 VISA 前預覽會影響硬體的命令。
- 使用內建模擬器在沒有硬體時測試流程。
- 設定電壓/電流限制、控制輸出狀態，並讀取即時儀器資料。
- 透過共用 Core runtime 執行 ramp、ramp-list、sequence、trigger、
  snapshot、restore 與 protection 流程。
- 產生 JSON 與 JSONL 輸出，供自動化、agent 與 orchestrator 使用。
- 保持真實硬體輸出為選用 (opt-in)；預設測試與模擬流程不會啟用儀器輸出。

## 選用 Codex／Agent Skill

專案提供選用、需手動安裝的
[Powers Tool CLI 調度 Skill](docs/skill/README.zh-TW.md)，供合約導向的 CLI
與 Power Worker workflow 使用。它是附屬範本，不是 Powers Tool runtime
功能，也不包含在 Python package、standalone executable、build、release 或
CI 中。

## 專案結構

此 repository 使用單一發行套件與單一版本號。在範例中，`<version>` 代表
根目錄 `pyproject.toml` 中的 `[project].version`：

- 發行套件：`keysight-powers` `<version>`
- Core import：`keysight_power_core`
- CLI import：`keysight_power_cli`
- WebUI import：`keysight_power_webui`

import 路徑彼此獨立。請不要使用 `keysight_power.*` namespace package。

```text
src/
  keysight_power_core/
  keysight_power_cli/
  keysight_power_webui/
tests/
  core/
  cli/
  webui/
  integration/
docs/
  core/
  cli/
  webui/
scripts/
```

## 安裝

先開啟 PowerShell 並進入專案根目錄：

```powershell
cd path\to\Keysight_Powers_Controller
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

`uv.lock` 用於 uv 的開發與 CI 可重現環境。`pip install .` 會讀取
`pyproject.toml`，不會讀取 `uv.lock`。沒有 uv 的使用者需要先安裝 uv，
才能使用 lock 環境。

如果需要直接使用 pip，請使用虛擬環境中的 Python：

```powershell
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m pip install ".[webui]"
.\.venv\Scripts\python.exe -m pip install -e ".[all,dev]"
```

Windows 會建立虛擬環境 console wrapper，例如
`.\.venv\Scripts\keysight-power.exe` 與
`.\.venv\Scripts\keysight-power-webui.exe`。WebUI 啟動器的 wrapper 是
`.\.venv\Scripts\keysight-power-webui-launcher.exe`。

## 建置

建置 wheel 與 source distribution。這會使用前面安裝的 `dev` extra 中的
`build` 套件：

```powershell
.\.venv\Scripts\python.exe -m build
```

這只會產生一個 Python 發行套件：

```text
dist\keysight_powers-<version>-py3-none-any.whl
dist\keysight_powers-<version>.tar.gz
```

獨立的執行檔有分開的 PyInstaller 工作流程。在建置 exe 產物之前，請先安裝 PyInstaller：

```powershell
uv pip install pyinstaller --python .\.venv\Scripts\python.exe
```

如果您的虛擬環境直接使用 pip：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
```

建置獨立的 CLI 與 WebUI 啟動器執行檔：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_cli_exe.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_webui_exe.ps1
```

預設情況下，這些命令會產生：

```text
dist\keysight-power.exe
dist\keysight-power-webui-launcher.exe
```

在不接觸硬體的情況下，快速測試建置完成的 CLI 執行檔：

```powershell
.\dist\keysight-power.exe --version
.\dist\keysight-power.exe doctor --simulate --json
```

建置包含 wheel、sdist、獨立執行檔與檢查碼 (checksums) 的發佈資料夾：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

這會產生以所選專案版本命名的發佈產物：

```text
release\<version>\keysight-power-<version>.exe
release\<version>\keysight-power-webui-launcher-<version>.exe
release\<version>\keysight_powers-<version>-py3-none-any.whl
release\<version>\keysight_powers-<version>.tar.gz
release\<version>\checksums.txt
```

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

執行完整無硬體測試：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

Scripted no-hardware 與 live validation 工作流程記錄在
[CLI README](docs/cli/README.zh-TW.md)。

## 文件

- [Core README](docs/core/README.zh-TW.md)
- [Supported Models](docs/core/supported-models.md)
- [CLI 使用者指南](docs/cli/USER_GUIDE.zh-TW.md)
- [CLI README](docs/cli/README.zh-TW.md)
- [WebUI README](docs/webui/README.zh-TW.md)
- [WebUI 使用者指南](docs/webui/USER_GUIDE.zh-TW.md)
- [Web UI Change Rules](docs/webui/web-ui-change-rules.md)
- [Repository 架構](docs/architecture/monorepo-layout.md)
- [測試指南](docs/testing-guidelines.md)
- [Public Contracts](docs/contracts)
- [Power CLI JSONL Contract](docs/contracts/power-cli-jsonl-contract.md)
- [Power Worker Contract](docs/contracts/power-worker-contract.md)
- [選用 Codex／Agent Skill](docs/skill/README.zh-TW.md)

## 授權條款與免責聲明

本專案採用 MIT License。詳見 [LICENSE](LICENSE)。

本專案是獨立且非官方的專案，未與 Keysight Technologies 建立從屬、
背書或贊助關係。

使用者需自行遵守所有適用的 Keysight 軟體、driver、儀器與文件授權條款。
