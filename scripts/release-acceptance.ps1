param(
    [string]$OutputRoot = ".tmp_tests\release_acceptance"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:Commands = @()
$script:ArtifactChecks = [System.Collections.ArrayList]::new()
$script:InstallChecks = [System.Collections.ArrayList]::new()
$script:EntryPointChecks = [System.Collections.ArrayList]::new()
$script:StandaloneChecks = [System.Collections.ArrayList]::new()
$script:BuildArtifacts = @()
$script:FailedStep = $null
$script:FailureMessage = $null
$script:Ok = $false
$script:CurrentStep = "initialization"
$script:RunRoot = $null
$script:RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "_validation_helpers.ps1")
$script:PythonVersion = $null
$script:FullAcceptanceCompleted = $false
$script:BuildStarted = $false
$sourceCommit = $null
$sourceBranch = $null
$projectVersion = $null
$distributionName = $null
$pythonMetadata = $null
$initialStatus = @()
$finalStatus = @()

# Local/, README.zh-TW.md, and generated localized files are outside this script's write scope.

function Get-ReleaseOutputPath {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$CandidatePath
    )

    $full = Get-FullPath -Path $CandidatePath -BaseRoot $RepoRoot
    $base = Get-FullPath -Path ".tmp_tests" -BaseRoot $RepoRoot
    Assert-PathUnderRoot `
        -RootPath $base `
        -Path $full `
        -Message "Release acceptance output must stay under the repository .tmp_tests directory: {0}"
    return $full
}

function Get-ReportPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $full = Get-FullPath -Path $Path
    $runPrefix = $script:RunRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) +
        [System.IO.Path]::DirectorySeparatorChar
    if ($full.StartsWith($runPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $full.Substring($runPrefix.Length).Replace(
            [System.IO.Path]::DirectorySeparatorChar,
            "/"
        )
    }
    return $full
}

function Invoke-Recorded {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [switch]$Python,
        [int]$TimeoutSeconds = 0
    )

    $started = Get-Date
    Write-Host "[start] $Name"
    $lines = @()
    $exitCode = 1
    $previousErrorActionPreference = $ErrorActionPreference
    if ($TimeoutSeconds -gt 0) {
        $captureId = [guid]::NewGuid().ToString("N")
        $stdoutPath = Join-Path $script:RunRoot ($captureId + ".stdout")
        $stderrPath = Join-Path $script:RunRoot ($captureId + ".stderr")
        $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments `
            -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            $lines = @("Command timed out after $TimeoutSeconds seconds")
            $exitCode = -1
        } else {
            $process.WaitForExit()
            $exitCode = [int]$process.ExitCode
            $lines = @(
                @(Get-Content -LiteralPath $stdoutPath -ErrorAction SilentlyContinue)
                @(Get-Content -LiteralPath $stderrPath -ErrorAction SilentlyContinue)
            )
        }
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    } else {
        Push-Location -LiteralPath $WorkingDirectory
        try {
            $ErrorActionPreference = "Continue"
            $lines = @(& $FilePath @Arguments 2>&1)
            $exitCode = [int]$LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
            Pop-Location
        }
    }
    $finished = Get-Date
    $output = (($lines | ForEach-Object { [string]$_ }) -join "`n")
    if ($output.Length -gt 12000) {
        $output = $output.Substring($output.Length - 12000)
    }
    $record = [ordered]@{
        name = $Name
        command = ((@($FilePath) + $Arguments) -join " ")
        working_directory = (Get-ReportPath -Path $WorkingDirectory)
        interpreter = if ($Python) { $FilePath } else { "" }
        python_version = if ($Python) { $script:PythonVersion } else { $null }
        exit_code = $exitCode
        duration_ms = [int][Math]::Round(($finished - $started).TotalMilliseconds)
        output_tail = $output
    }
    $script:Commands += ,$record
    if ($output) {
        $lines | ForEach-Object { Write-Host $_ }
    }
    $durationSeconds = ($finished - $started).TotalSeconds
    $durationText = [string]::Format(
        [System.Globalization.CultureInfo]::InvariantCulture,
        "{0:F3}",
        $durationSeconds
    )
    if ($exitCode -eq 0) {
        Write-Host "[passed] $Name duration=${durationText}s"
    } else {
        Write-Host "[failed] $Name duration=${durationText}s"
    }
    if ($exitCode -ne 0) {
        throw "$Name failed with exit code $exitCode"
    }
    return $output
}

function Get-PythonMetadata {
    param(
        [Parameter(Mandatory = $true)][string]$Python
    )

    $code = 'import sys; print(sys.version_info.major); print(sys.version_info.minor); print(sys.version); print(sys.executable)'
    $output = Invoke-Recorded -Name "python-metadata" -FilePath $Python `
        -Arguments @("-c", $code) -WorkingDirectory $script:RunRoot -Python
    $lines = @($output -split "`r?`n")
    if ($lines.Count -lt 4) {
        throw "The project interpreter returned invalid metadata: $Python"
    }
    $metadata = [pscustomobject]@{
        major = [int]$lines[0]
        minor = [int]$lines[1]
        version = [string]$lines[2]
        executable = [System.IO.Path]::GetFullPath([string]$lines[3])
    }
    if ($metadata.major -ne 3 -or $metadata.minor -lt 10) {
        throw "The project interpreter does not satisfy Python >=3.10: $($metadata.version)"
    }
    $script:PythonVersion = [string]$metadata.version
    return $metadata
}

function Run-Python {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    return Invoke-Recorded -Name $Name -FilePath $Python -Arguments $Arguments `
        -WorkingDirectory $WorkingDirectory -Python
}

function Assert-File {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing required artifact: $Path"
    }
}

function Add-Check {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.IList]$Target,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][bool]$Passed,
        [string]$Detail = ""
    )

    $Target.Add([ordered]@{ name = $Name; passed = $Passed; detail = $Detail }) | Out-Null
    if (-not $Passed) {
        throw "Acceptance check failed: $Name"
    }
}

function Remove-GeneratedDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)

    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return
        } catch {
            if ($attempt -eq 20) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
}

function Test-InstalledEntryPoints {
    param(
        [Parameter(Mandatory = $true)][string]$Python
    )

    $scripts = Split-Path -Parent $Python
    $checks = @(
        @("powers-tool", "powers-tool $projectVersion"),
        @("powers-tool-webui", "powers-tool-webui $projectVersion"),
        @("powers-tool-webui-launcher", "powers-tool-webui-launcher $projectVersion")
    )
    foreach ($check in $checks) {
        $exe = Join-Path $scripts ($check[0] + ".exe")
        Assert-File -Path $exe
        $versionOutput = Invoke-Recorded -Name ("sdist-" + $check[0] + "-version") `
            -FilePath $exe -Arguments @("--version") -WorkingDirectory $script:RunRoot `
            -TimeoutSeconds 30
        Add-Check -Target $script:EntryPointChecks -Name ($check[0] + " --version") `
            -Passed ($versionOutput.Trim() -eq $check[1]) -Detail $versionOutput.Trim()
        $helpOutput = Invoke-Recorded -Name ("sdist-" + $check[0] + "-help") `
            -FilePath $exe -Arguments @("--help") -WorkingDirectory $script:RunRoot `
            -TimeoutSeconds 30
        $helpText = $helpOutput.Trim()
        Add-Check -Target $script:EntryPointChecks -Name ($check[0] + " --help") `
            -Passed (-not [string]::IsNullOrWhiteSpace($helpText) -and
                $helpText -match '(?im)^usage:\s*' -and
                $helpText.Contains($check[0])) `
            -Detail "Non-empty usage output for $($check[0])"
    }
}

try {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git is required"
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is required"
    }

    $sourceCommit = (& git -C $script:RepoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $sourceCommit) {
        throw "Could not resolve committed HEAD"
    }
    $sourceBranch = (& git -C $script:RepoRoot branch --show-current).Trim()
    if (-not $sourceBranch) { $sourceBranch = "detached" }
    $initialStatus = @(& git -C $script:RepoRoot status --short --untracked-files=all 2>&1)
    if ($initialStatus.Count -ne 0) {
        throw "Release acceptance requires a clean source worktree: $($initialStatus -join '; ')"
    }

    $outputFull = Get-ReleaseOutputPath -RepoRoot $script:RepoRoot -CandidatePath $OutputRoot
    New-Item -ItemType Directory -Force -Path $outputFull | Out-Null
    $runName = "r_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
    $script:RunRoot = Join-Path $outputFull $runName
    New-Item -ItemType Directory -Force -Path $script:RunRoot | Out-Null
    $uvCache = Join-Path $script:RunRoot "uv-cache"
    New-Item -ItemType Directory -Force -Path $uvCache | Out-Null
    $env:UV_CACHE_DIR = $uvCache
    $env:PYTHONNOUSERSITE = "1"
    foreach ($name in @("PYTHONPATH", "PYTHONHOME", "UV_INTERNAL__PYTHONHOME", "VIRTUAL_ENV")) {
        if (Test-Path "Env:$name") { Remove-Item "Env:$name" }
    }

    $pyprojectPath = Join-Path $script:RepoRoot "pyproject.toml"
    $pyprojectText = Get-Content -LiteralPath $pyprojectPath -Raw
    $nameMatch = [regex]::Match($pyprojectText, '(?m)^name\s*=\s*"([^"]+)"')
    $projectVersion = Get-PackageVersion -ProjectRoot $script:RepoRoot
    if (-not $nameMatch.Success -or [string]::IsNullOrWhiteSpace($projectVersion)) {
        throw "Could not read project metadata"
    }
    $distributionName = $nameMatch.Groups[1].Value
    if ($distributionName -ne "powers-tool") {
        throw "Unexpected project identity: $distributionName $projectVersion"
    }

    $python = Join-Path $script:RepoRoot ".venv\Scripts\python.exe"
    Assert-File -Path $python
    $script:CurrentStep = "project Python metadata"
    $pythonMetadata = Get-PythonMetadata -Python $python

    $script:CurrentStep = "lock consistency"
    Invoke-Recorded -Name "uv-lock-check" -FilePath "uv" `
        -Arguments @("lock", "--check") -WorkingDirectory $script:RepoRoot | Out-Null

    $script:CurrentStep = "complete no-hardware suite"
    Run-Python -Name "pytest-full-no-hardware" -Python $python -WorkingDirectory $script:RepoRoot `
        -Arguments @(
            "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider",
            "--basetemp", (Join-Path $script:RunRoot "pytest")
        ) | Out-Null

    $script:CurrentStep = "final release build"
    foreach ($generated in @("dist", "build")) {
        $generatedPath = Join-Path $script:RepoRoot $generated
        if (Test-Path -LiteralPath $generatedPath) {
            Remove-GeneratedDirectory -Path $generatedPath
        }
    }
    $script:BuildStarted = $true
    $releaseRoot = Join-Path $script:RunRoot "artifacts\release"
    Invoke-Recorded -Name "build-versioned-release" -FilePath "powershell.exe" `
        -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            (Join-Path $script:RepoRoot "scripts\build_release.ps1"),
            "-Version", $projectVersion,
            "-ReleaseRoot", $releaseRoot
        ) -WorkingDirectory $script:RepoRoot | Out-Null

    $script:CurrentStep = "final release artifact checks"
    $versionDir = Join-Path $releaseRoot $projectVersion
    $normalizedDistribution = $distributionName.Replace("-", "_")
    $expectedRelease = @(
        "powers-tool-$projectVersion-windows-x64.zip",
        "$normalizedDistribution-$projectVersion-py3-none-any.whl",
        "$normalizedDistribution-$projectVersion.tar.gz",
        "checksums.txt"
    )
    $releaseEntries = @(Get-ChildItem -LiteralPath $versionDir -Force)
    $invalidEntries = @(
        $releaseEntries |
            Where-Object {
                $_.PSIsContainer -or
                $_.Name -notin $expectedRelease
            }
    )
    Add-Check -Target $script:ArtifactChecks -Name "versioned release folder contents" `
        -Passed (
            $releaseEntries.Count -eq $expectedRelease.Count -and
            $invalidEntries.Count -eq 0
        ) `
        -Detail (($releaseEntries.Name | Sort-Object) -join ", ")

    $windowsBundleZip = Get-Item -LiteralPath (
        Join-Path $versionDir "powers-tool-$projectVersion-windows-x64.zip"
    )
    $checksumPath = Join-Path $versionDir "checksums.txt"
    $checksumLines = Get-Content -LiteralPath $checksumPath
    $checksumNames = @()
    foreach ($line in $checksumLines) {
        if ($line -notmatch '^([0-9a-fA-F]{64})  (.+)$') {
            throw "Invalid checksum line: $line"
        }
        $checksumNames += $Matches[2]
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $versionDir $Matches[2])).Hash.ToLowerInvariant()
        Add-Check -Target $script:ArtifactChecks -Name ("SHA-256 " + $Matches[2]) `
            -Passed ($actual -eq $Matches[1].ToLowerInvariant()) -Detail $actual
    }
    $expectedChecksumNames = @($expectedRelease | Where-Object { $_ -ne "checksums.txt" })
    Add-Check -Target $script:ArtifactChecks -Name "checksum artifact coverage" `
        -Passed (@(Compare-Object -ReferenceObject $expectedChecksumNames -DifferenceObject $checksumNames).Count -eq 0) `
        -Detail ($checksumNames -join ", ")
    $checksumBytes = [System.IO.File]::ReadAllBytes($checksumPath)
    Add-Check -Target $script:ArtifactChecks -Name "checksums UTF-8 without BOM" `
        -Passed (-not ($checksumBytes.Length -ge 3 -and $checksumBytes[0] -eq 0xEF -and `
            $checksumBytes[1] -eq 0xBB -and $checksumBytes[2] -eq 0xBF))

    $script:CurrentStep = "extract unified Windows bundle"
    $bundleExtractRoot = Join-Path $script:RunRoot "windows-bundle"
    New-Item -ItemType Directory -Force -Path $bundleExtractRoot | Out-Null
    Expand-Archive -LiteralPath $windowsBundleZip.FullName -DestinationPath $bundleExtractRoot
    $expectedBundleDirName = "powers-tool-$projectVersion"
    $bundleRootEntries = @(Get-ChildItem -LiteralPath $bundleExtractRoot -Force)
    if (
        $bundleRootEntries.Count -ne 1 -or
        -not $bundleRootEntries[0].PSIsContainer -or
        $bundleRootEntries[0].Name -cne $expectedBundleDirName
    ) {
        $found = ($bundleRootEntries.Name | Sort-Object) -join ", "
        throw "Windows bundle ZIP must contain only $expectedBundleDirName`: $found"
    }

    $extractedBundleDir = $bundleRootEntries[0].FullName
    foreach ($requiredFile in @(
        "Powers Tool.exe",
        "powers-tool.exe",
        "powers-tool-webui-launcher.exe",
        "powers-tool-webui-host.exe"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $extractedBundleDir $requiredFile) -PathType Leaf)) {
            throw "Unified Windows bundle is missing required file: $requiredFile"
        }
    }
    foreach ($requiredDirectory in @("_internal", "resources")) {
        if (-not (Test-Path -LiteralPath (Join-Path $extractedBundleDir $requiredDirectory) -PathType Container)) {
            throw "Unified Windows bundle is missing required directory: $requiredDirectory"
        }
    }
    $internalDirectories = @(
        Get-ChildItem -LiteralPath $extractedBundleDir -Directory -Recurse -Force |
            Where-Object { $_.Name -eq "_internal" }
    )
    if ($internalDirectories.Count -ne 1) {
        throw "Unified Windows bundle must contain exactly one _internal directory."
    }
    if (-not $internalDirectories[0].FullName.Equals(
        (Join-Path $extractedBundleDir "_internal"),
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Unified Windows bundle _internal directory must be at the application root."
    }
    if (Test-Path -LiteralPath (Join-Path $extractedBundleDir "resources\backend")) {
        throw "Unified Windows bundle must not contain resources\backend."
    }
    if (@(Get-ChildItem -LiteralPath $extractedBundleDir -Filter "*-portable.exe" -File -Recurse).Count -ne 0) {
        throw "Unified Windows bundle must not contain a portable executable."
    }
    $packagedCli = Join-Path $extractedBundleDir "powers-tool.exe"
    $packagedLauncher = Join-Path $extractedBundleDir "powers-tool-webui-launcher.exe"

    $installedRuntimeCode = @'
import importlib.metadata as metadata
import sys
from pathlib import Path
from unittest.mock import patch

import powers_tool_cli
import powers_tool_cli.cli as cli
import powers_tool_core
import powers_tool_webui

expected_version = "__PROJECT_VERSION__"
assert metadata.version("powers-tool") == expected_version
assert powers_tool_core.__version__ == expected_version
assert powers_tool_cli.__version__ == expected_version
assert powers_tool_webui.__version__ == expected_version

environment = Path(sys.prefix).resolve()
package_directories = {
    "powers_tool_cli": Path(powers_tool_cli.__file__).resolve().parent,
    "powers_tool_core": Path(powers_tool_core.__file__).resolve().parent,
    "powers_tool_webui": Path(powers_tool_webui.__file__).resolve().parent,
}
for package_name, package_directory in package_directories.items():
    assert package_directory.is_relative_to(environment), (
        package_name,
        package_directory,
        environment,
    )

cli_help = package_directories["powers_tool_cli"].joinpath("help")
for filename in (
    "cli.html",
    "cli.zh-TW.html",
    "supported-models.html",
    "supported-models.zh-TW.html",
    "help.css",
):
    assert cli_help.joinpath(filename).is_file(), filename

webui_static = package_directories["powers_tool_webui"].joinpath("static")
for filename in ("index.html", "styles.css", "app.js"):
    assert webui_static.joinpath(filename).is_file(), filename
webui_help = webui_static.joinpath("help")
for filename in (
    "webui.html",
    "webui.zh-TW.html",
    "supported-models.html",
    "supported-models.zh-TW.html",
    "help.css",
):
    assert webui_help.joinpath(filename).is_file(), filename

opened = []


def capture_open(uri):
    opened.append(uri)
    return True


with patch("webbrowser.open", capture_open):
    assert cli.main(["user-guide"]) == 0
expected_uri = cli_help.joinpath("cli.html").resolve().as_uri()
assert opened == [expected_uri], opened
assert opened[0].startswith("file:")
'@
    $installedRuntimeScript = Join-Path $script:RunRoot "installed_runtime_check.py"
    Write-Utf8NoBomText -LiteralPath $installedRuntimeScript `
        -Text $installedRuntimeCode.Replace("__PROJECT_VERSION__", $projectVersion)

    $wheel = Join-Path $versionDir "$normalizedDistribution-$projectVersion-py3-none-any.whl"
    $sdist = Join-Path $versionDir "$normalizedDistribution-$projectVersion.tar.gz"
    $installArtifacts = @(
        [pscustomobject]@{
            Kind = "wheel"
            Path = $wheel
            Step = "clean wheel install"
            CreateCommand = "create-wheel-environment"
            InstallCommand = "install-final-wheel"
            InspectCommand = "inspect-wheel-install"
        },
        [pscustomobject]@{
            Kind = "sdist"
            Path = $sdist
            Step = "clean sdist install"
            CreateCommand = "create-sdist-environment"
            InstallCommand = "install-final-sdist"
            InspectCommand = "inspect-sdist-install"
        }
    )
    $sdistPython = $null
    foreach ($installArtifact in $installArtifacts) {
        $script:CurrentStep = $installArtifact.Step
        $artifactEnvironment = Join-Path $script:RunRoot ("envs\" + $installArtifact.Kind)
        Invoke-Recorded -Name $installArtifact.CreateCommand -FilePath "uv" `
            -Arguments @("venv", $artifactEnvironment, "--python", $python) `
            -WorkingDirectory $script:RunRoot | Out-Null
        $artifactPython = Join-Path $artifactEnvironment "Scripts\python.exe"
        Assert-File -Path $artifactPython
        Invoke-Recorded -Name $installArtifact.InstallCommand -FilePath "uv" `
            -Arguments @("pip", "install", "--python", $artifactPython, $installArtifact.Path) `
            -WorkingDirectory $script:RunRoot | Out-Null
        Run-Python -Name $installArtifact.InspectCommand -Python $artifactPython `
            -WorkingDirectory $script:RunRoot -Arguments @($installedRuntimeScript) | Out-Null
        Add-Check -Target $script:InstallChecks `
            -Name ($installArtifact.Kind + " package identity, contents, and bundled Help") `
            -Passed $true `
            -Detail ("Installed final " + $installArtifact.Kind +
                " and verified package metadata, imports, and runtime assets")
        if ($installArtifact.Kind -eq "sdist") {
            $sdistPython = $artifactPython
        }
    }
    if (-not $sdistPython) {
        throw "The final sdist environment was not created"
    }
    Test-InstalledEntryPoints -Python $sdistPython

    $script:CurrentStep = "final packaged smoke"
    $cliVersion = Invoke-Recorded -Name "packaged-cli-version" -FilePath $packagedCli `
        -Arguments @("--version") -WorkingDirectory $script:RunRoot -TimeoutSeconds 30
    Add-Check -Target $script:StandaloneChecks -Name "CLI --version" `
        -Passed ($cliVersion.Trim() -eq "powers-tool $projectVersion") -Detail $cliVersion.Trim()
    $webuiVersion = Invoke-Recorded -Name "packaged-webui-launcher-version" -FilePath $packagedLauncher `
        -Arguments @("--version") -WorkingDirectory $script:RunRoot -TimeoutSeconds 30
    $webuiDetail = $webuiVersion.Trim()
    if (-not $webuiDetail) { $webuiDetail = "clean exit; no windowed stdout" }
    Add-Check -Target $script:StandaloneChecks -Name "WebUI --version" `
        -Passed ((-not $webuiVersion.Trim()) -or
            $webuiVersion.Trim() -eq "powers-tool-webui-launcher $projectVersion") `
        -Detail $webuiDetail
    foreach ($artifact in Get-ChildItem -LiteralPath $versionDir -File | Sort-Object Name) {
        $script:BuildArtifacts += ,(Get-ReportPath -Path $artifact.FullName)
    }

    $script:CurrentStep = "all-model CLI smoke preflight"
    $preflightRoot = Join-Path $script:RepoRoot (".tmp_tests\cli_preflight\" + $runName)
    Invoke-Recorded -Name "preflight-cli-all-smoke" -FilePath "powershell.exe" `
        -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            (Join-Path $script:RepoRoot "scripts\preflight-cli.ps1"),
            "-Target", "all",
            "-Suite", "smoke",
            "-OutputRoot", $preflightRoot
        ) -WorkingDirectory $script:RepoRoot | Out-Null

    $script:CurrentStep = "representative CLI deep preflight"
    Invoke-Recorded -Name "preflight-cli-deep-representatives" -FilePath "powershell.exe" `
        -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            (Join-Path $script:RepoRoot "scripts\preflight-cli.ps1"),
            "-Target", "all",
            "-Suite", "deep",
            "-OutputRoot", $preflightRoot
        ) -WorkingDirectory $script:RepoRoot | Out-Null

    $script:CurrentStep = "representative simulator PlanOnly contract"
    Invoke-Recorded -Name "live-cli-plan-only" -FilePath "powershell.exe" `
        -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            (Join-Path $script:RepoRoot "scripts\live-cli-check.ps1"),
            "-Target", "keysight-e36312a",
            "-Connection", "USB",
            "-Resource", "SIM::E36312A",
            "-Suite", "readonly",
            "-PlanOnly",
            "-SkipExternalPreflight"
        ) -WorkingDirectory $script:RepoRoot | Out-Null

    $script:CurrentStep = "final source hygiene"
    foreach ($generated in @("dist", "build")) {
        $generatedPath = Join-Path $script:RepoRoot $generated
        if (Test-Path -LiteralPath $generatedPath) {
            Remove-GeneratedDirectory -Path $generatedPath
        }
    }
    $script:BuildStarted = $false
    Invoke-Recorded -Name "git-diff-check" -FilePath "git" `
        -Arguments @("-C", $script:RepoRoot, "diff", "--check") `
        -WorkingDirectory $script:RepoRoot | Out-Null
    $finalCommit = (& git -C $script:RepoRoot rev-parse HEAD).Trim()
    if ($finalCommit -ne $sourceCommit) {
        throw "HEAD changed during release acceptance: started=$sourceCommit; finished=$finalCommit"
    }
    $finalStatus = @(& git -C $script:RepoRoot status --short --untracked-files=all)
    if ($finalStatus.Count -ne 0) {
        throw "Acceptance commands changed tracked or untracked source paths: $($finalStatus -join '; ')"
    }

    $script:FullAcceptanceCompleted = $true
    $script:Ok = $true
}
catch {
    $script:FailedStep = $script:CurrentStep
    $script:FailureMessage = $_.Exception.Message
    Write-Warning ("Powers Tool release acceptance failed during {0}: {1}" -f `
        $script:CurrentStep, $script:FailureMessage)
}
finally {
    if ($script:BuildStarted) {
        try {
            foreach ($generated in @("dist", "build")) {
                $generatedPath = Join-Path $script:RepoRoot $generated
                if (Test-Path -LiteralPath $generatedPath) {
                    Remove-GeneratedDirectory -Path $generatedPath
                }
            }
        } catch {
            $script:Ok = $false
            $cleanupFailure = $_.Exception.Message
            if ($script:FailedStep) {
                $script:FailureMessage += " Cleanup also failed: $cleanupFailure"
            } else {
                $script:FailedStep = "clean generated build directories"
                $script:FailureMessage = $cleanupFailure
            }
            Write-Warning $_
        }
    }
    if ($script:RunRoot) {
        $report = [ordered]@{
            schema_version = 1
            kind = "powers-tool-release-acceptance"
            ok = $script:Ok
            acceptance_mode = "committed-clean-head"
            full_acceptance_completed = $script:FullAcceptanceCompleted
            source_commit = if ($sourceCommit) { $sourceCommit } else { $null }
            source_branch = if ($sourceBranch) { $sourceBranch } else { $null }
            project_version = if ($projectVersion) { $projectVersion } else { $null }
            distribution_name = if ($distributionName) { $distributionName } else { $null }
            python = [ordered]@{
                requested_interpreter = ".venv\Scripts\python.exe"
                resolved_interpreter = if ($pythonMetadata) { [string]$pythonMetadata.executable } else { $null }
                actual_version = if ($pythonMetadata) { [string]$pythonMetadata.version } else { $null }
                actual_major = if ($pythonMetadata) { [int]$pythonMetadata.major } else { $null }
                actual_minor = if ($pythonMetadata) { [int]$pythonMetadata.minor } else { $null }
            }
            initial_worktree_status = @($initialStatus)
            final_worktree_status = @($finalStatus)
            commands = @($script:Commands)
            build_artifacts = @($script:BuildArtifacts | Select-Object -Unique)
            artifact_checks = @($script:ArtifactChecks)
            install_checks = @($script:InstallChecks)
            entry_point_checks = @($script:EntryPointChecks)
            standalone_checks = @($script:StandaloneChecks)
            failed_step = $script:FailedStep
            failure_message = $script:FailureMessage
            hardware_touched = $false
            support_metadata_changed = $false
            evidence_changed = $false
            repository_renamed = $false
        }
        $reportJson = $report | ConvertTo-Json -Depth 8
        Write-Utf8NoBomText -LiteralPath (Join-Path $script:RunRoot "report.json") `
            -Text $reportJson
        $summary = @(
            "# Powers Tool Release Acceptance",
            "",
            "Result: **$(if ($script:Ok) { 'passed' } else { 'failed' })**",
            "",
            "- Acceptance mode: ``committed-clean-head``",
            "- Full acceptance completed: ``$($script:FullAcceptanceCompleted.ToString().ToLowerInvariant())``",
            "- Source branch: ``$sourceBranch``",
            "- Source commit: ``$sourceCommit``",
            "- Distribution: ``$distributionName`` $projectVersion",
            "- Python: ``$(if ($pythonMetadata) { $pythonMetadata.version } else { 'unavailable' })``",
            "- Hardware touched: ``false``",
            "",
            "| Command | Exit code | Duration ms |",
            "| --- | ---: | ---: |"
        )
        foreach ($command in $script:Commands) {
            $summary += "| ``$($command.name)`` | $($command.exit_code) | $($command.duration_ms) |"
        }
        if (-not $script:Ok) {
            $summary += ""
            $summary += "Failed step: ``$($script:FailedStep)``"
            $summary += "Failure: $($script:FailureMessage)"
        }
        Write-Utf8NoBomText -LiteralPath (Join-Path $script:RunRoot "summary.md") `
            -Text ($summary -join "`n")
        Write-Host "Acceptance report: $(Join-Path $script:RunRoot 'report.json')"
    }
}

if (-not $script:Ok) { exit 1 }
exit 0
