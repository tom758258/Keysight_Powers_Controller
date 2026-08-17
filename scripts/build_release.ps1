param(
    [string]$Version,
    [string]$ReleaseRoot = "release"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
. (Join-Path $PSScriptRoot "_validation_helpers.ps1")

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
}

$pyproject = Join-Path $RepoRoot "pyproject.toml"
$projectVersion = Get-PackageVersion -ProjectRoot $RepoRoot
if ([string]::IsNullOrWhiteSpace($projectVersion)) {
    throw "Could not read project version from $pyproject"
}
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = $projectVersion
} elseif ($Version -ne $projectVersion) {
    throw "Version $Version does not match project version $projectVersion"
}

$releaseRootFull = Get-FullPath -Path $ReleaseRoot -BaseRoot $RepoRoot
Assert-PathUnderRoot `
    -RootPath $RepoRoot `
    -Path $releaseRootFull `
    -Message "ReleaseRoot must stay under the repository: {0}"

$versionDir = Join-Path $releaseRootFull $Version
if (Test-Path -LiteralPath $versionDir) {
    Remove-Item -LiteralPath $versionDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $versionDir | Out-Null

& $Python -m build
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& $Python (Join-Path $RepoRoot "tests\packaging\inspect_distribution.py") --expected-version $Version (Join-Path $RepoRoot "dist")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$desktopPackage = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot "desktop\package.json") | ConvertFrom-Json
if ($desktopPackage.version -ne $Version) {
    throw "Desktop package version $($desktopPackage.version) does not match release version $Version"
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_desktop.ps1")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$desktopDirectory = Join-Path $RepoRoot "dist\desktop\win-unpacked"
if (-not (Test-Path -LiteralPath $desktopDirectory -PathType Container)) {
    throw "Desktop build did not produce release directory: $desktopDirectory"
}

Copy-Item -LiteralPath (Join-Path $RepoRoot "dist\powers_tool-$Version-py3-none-any.whl") -Destination $versionDir -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "dist\powers_tool-$Version.tar.gz") -Destination $versionDir -Force

$archiveRoot = Join-Path $releaseRootFull ".build-$Version"
if (Test-Path -LiteralPath $archiveRoot) {
    Remove-Item -LiteralPath $archiveRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $archiveRoot | Out-Null
$versionedBundleDir = Join-Path $archiveRoot "powers-tool-$Version"
New-Item -ItemType Directory -Force -Path $versionedBundleDir | Out-Null
foreach ($entry in Get-ChildItem -LiteralPath $desktopDirectory -Force) {
    Copy-Item -LiteralPath $entry.FullName -Destination $versionedBundleDir -Recurse -Force
}

$windowsZipName = "powers-tool-$Version-windows-x64.zip"
$windowsZip = Join-Path $versionDir $windowsZipName
Compress-Archive `
    -LiteralPath $versionedBundleDir `
    -DestinationPath $windowsZip `
    -CompressionLevel Optimal

Remove-Item -LiteralPath $archiveRoot -Recurse -Force

$expectedArtifactNames = @(
    $windowsZipName,
    "powers_tool-$Version-py3-none-any.whl",
    "powers_tool-$Version.tar.gz"
)
$releaseEntries = @(Get-ChildItem -LiteralPath $versionDir -Force)
$invalidEntries = @(
    $releaseEntries |
        Where-Object { $_.PSIsContainer -or $_.Name -notin $expectedArtifactNames }
)
if (
    $releaseEntries.Count -ne $expectedArtifactNames.Count -or
    $invalidEntries.Count -ne 0
) {
    $found = ($releaseEntries.Name | Sort-Object) -join ", "
    throw "Release build did not produce exactly the expected distributables: $found"
}

$checksums = foreach ($artifactName in ($expectedArtifactNames | Sort-Object)) {
    $artifact = Get-Item -LiteralPath (Join-Path $versionDir $artifactName)
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifact.FullName).Hash.ToLowerInvariant()
    "$hash  $($artifact.Name)"
}
Write-Utf8NoBomLines -LiteralPath (Join-Path $versionDir "checksums.txt") -Lines $checksums

Write-Host "release artifacts: $versionDir"
