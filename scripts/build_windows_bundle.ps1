param(
    [string]$DistPath = "dist"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
}

$pythonBits = & $Python -c "import struct; print(struct.calcsize('P') * 8)"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
if ($pythonBits.Trim() -ne "64") {
    throw "Windows shared bundle requires 64-bit Python; detected $($pythonBits.Trim())-bit Python"
}

$tkProbe = @'
import sys
import tkinter as tk

root = None
try:
    root = tk.Tk()
    root.withdraw()
except Exception:
    sys.exit(1)
finally:
    if root is not None:
        root.destroy()
'@
& $Python -c $tkProbe | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Windows shared bundle includes a Tkinter WebUI Launcher and requires a working Tcl/Tk runtime; no bundle was built."
}

if ([System.IO.Path]::IsPathRooted($DistPath)) {
    $distFull = [System.IO.Path]::GetFullPath($DistPath)
} else {
    $distFull = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $DistPath))
}
$repoFull = [System.IO.Path]::GetFullPath($RepoRoot)
$repoPrefix = $repoFull.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not (
    $distFull.Equals($repoFull, [System.StringComparison]::OrdinalIgnoreCase) -or
    $distFull.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)
)) {
    throw "DistPath must stay under the repository: $distFull"
}

$bundlePath = Join-Path $distFull "powers-tool"
if (Test-Path -LiteralPath $bundlePath) {
    Remove-Item -LiteralPath $bundlePath -Recurse -Force
}

$specPath = Join-Path $RepoRoot "scripts\powers-tool-windows.spec"
$workPath = Join-Path $RepoRoot "build\pyinstaller-windows"

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $distFull `
    --workpath $workPath `
    $specPath

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
