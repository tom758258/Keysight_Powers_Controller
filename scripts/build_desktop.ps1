Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$WindowsBundleBuild = Join-Path $PSScriptRoot "build_windows_bundle.ps1"
$DesktopRoot = Join-Path $RepoRoot "desktop"
$DistRoot = Join-Path $RepoRoot "dist"
$SharedBundle = Join-Path $DistRoot "powers-tool"
$DesktopDist = Join-Path $DistRoot "desktop"
$DesktopDirectory = Join-Path $DesktopDist "win-unpacked"

foreach ($ownedPath in @($DesktopDist, $SharedBundle)) {
    $ownedPathFull = [System.IO.Path]::GetFullPath($ownedPath)
    $repoPrefix = [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar
    ) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $ownedPathFull.StartsWith(
        $repoPrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Desktop build path must stay under the repository: $ownedPathFull"
    }
    if (Test-Path -LiteralPath $ownedPathFull) {
        Remove-Item -LiteralPath $ownedPathFull -Recurse -Force
    }
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $WindowsBundleBuild `
    -DistPath $DistRoot
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$Npm = Get-Command -Name "npm.cmd" -CommandType Application -ErrorAction Stop |
    Select-Object -First 1
Push-Location $DesktopRoot
try {
    & $Npm.Source ci
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    & $Npm.Source run check
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    & $Npm.Source run dist:win
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $DesktopDirectory -PathType Container)) {
    throw "Electron directory build did not produce: $DesktopDirectory"
}
if (-not (Test-Path -LiteralPath $SharedBundle -PathType Container)) {
    throw "Shared Windows bundle not found: $SharedBundle"
}

foreach ($entry in Get-ChildItem -LiteralPath $SharedBundle -Force) {
    Copy-Item -LiteralPath $entry.FullName -Destination $DesktopDirectory -Recurse -Force
}

foreach ($requiredPath in @(
    (Join-Path $DesktopDirectory "Powers Tool.exe"),
    (Join-Path $DesktopDirectory "powers-tool.exe"),
    (Join-Path $DesktopDirectory "powers-tool-webui-launcher.exe"),
    (Join-Path $DesktopDirectory "powers-tool-webui-host.exe")
)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Desktop directory is missing required executable: $requiredPath"
    }
}

foreach ($requiredDirectory in @(
    (Join-Path $DesktopDirectory "resources")
)) {
    if (-not (Test-Path -LiteralPath $requiredDirectory -PathType Container)) {
        throw "Desktop directory is missing required directory: $requiredDirectory"
    }
}

$internalDirectories = @(
    Get-ChildItem -LiteralPath $DesktopDirectory -Directory -Recurse -Force |
        Where-Object { $_.Name -eq "_internal" }
)
if ($internalDirectories.Count -ne 1) {
    throw "Desktop directory must contain exactly one _internal directory."
}
if (-not $internalDirectories[0].FullName.Equals(
    (Join-Path $DesktopDirectory "_internal"),
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Desktop _internal directory must be shared at the application root."
}
if (Test-Path -LiteralPath (Join-Path $DesktopDirectory "resources\backend")) {
    throw "Desktop directory must not contain resources\backend."
}
if (@(Get-ChildItem -LiteralPath $DesktopDist -Filter "*-portable.exe" -File -Recurse).Count -ne 0) {
    throw "Desktop directory build must not produce a portable executable."
}

Write-Host "Desktop directory: $DesktopDirectory"
