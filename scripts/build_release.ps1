param(
    [string]$Version,
    [string]$ReleaseRoot = "release"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
}

function Get-ProjectVersion {
    $pyproject = Join-Path $RepoRoot "pyproject.toml"
    $match = Select-String -LiteralPath $pyproject -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($null -eq $match) {
        throw "Could not read project version from $pyproject"
    }
    return $match.Matches[0].Groups[1].Value
}

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Value
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($LiteralPath, $Value, $encoding)
}

function Get-Sha256File {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath
    )

    $stream = $null
    $sha256 = $null
    try {
        $stream = [System.IO.File]::Open(
            $LiteralPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::Read
        )
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        $hash = $sha256.ComputeHash($stream)
        return [System.BitConverter]::ToString($hash).Replace("-", "").ToLowerInvariant()
    } finally {
        if ($null -ne $sha256) { $sha256.Dispose() }
        if ($null -ne $stream) { $stream.Dispose() }
    }
}

$projectVersion = Get-ProjectVersion
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = $projectVersion
} elseif ($Version -ne $projectVersion) {
    throw "Version $Version does not match project version $projectVersion"
}

if ([System.IO.Path]::IsPathRooted($ReleaseRoot)) {
    $releaseRootFull = [System.IO.Path]::GetFullPath($ReleaseRoot)
} else {
    $releaseRootFull = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $ReleaseRoot))
}
$repoFull = [System.IO.Path]::GetFullPath($RepoRoot)
$repoPrefix = $repoFull.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not (
    $releaseRootFull.Equals($repoFull, [System.StringComparison]::OrdinalIgnoreCase) -or
    $releaseRootFull.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)
)) {
    throw "ReleaseRoot must stay under the repository: $releaseRootFull"
}

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
    $hash = Get-Sha256File -LiteralPath $artifact.FullName
    "$hash  $($artifact.Name)"
}
Write-Utf8NoBomFile -LiteralPath (Join-Path $versionDir "checksums.txt") -Value $checksums

Write-Host "release artifacts: $versionDir"
