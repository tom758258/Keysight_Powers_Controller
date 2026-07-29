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

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($LiteralPath, $Content, $encoding)
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

function Get-ContainedPath {
    param(
        [Parameter(Mandatory = $true)][string]$BasePath,
        [Parameter(Mandatory = $true)][string]$CandidatePath
    )

    if ([System.IO.Path]::IsPathRooted($CandidatePath)) {
        $full = [System.IO.Path]::GetFullPath($CandidatePath)
    } else {
        $full = [System.IO.Path]::GetFullPath((Join-Path $BasePath $CandidatePath))
    }
    $base = [System.IO.Path]::GetFullPath($BasePath).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $prefix = $base + [System.IO.Path]::DirectorySeparatorChar
    if (-not ($full.Equals($base, [System.StringComparison]::OrdinalIgnoreCase) -or
        $full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase))) {
        throw "Path must stay under ${base}: $full"
    }
    return $full
}

function Get-ReportPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $full = [System.IO.Path]::GetFullPath($Path)
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
        @("powers-tool", "powers-tool $projectVersion", "Safe Powers Tool CLI for supported DC power supplies."),
        @("powers-tool-webui", "powers-tool-webui $projectVersion", "Powers Tool WebUI Server"),
        @("powers-tool-webui-launcher", "powers-tool-webui-launcher $projectVersion", "Powers Tool WebUI Launcher")
    )
    foreach ($check in $checks) {
        $exe = Join-Path $scripts ($check[0] + ".exe")
        Assert-File -Path $exe
        $versionOutput = Invoke-Recorded -Name ("sdist-" + $check[0] + "-version") `
            -FilePath $exe -Arguments @("--version") -WorkingDirectory $script:RunRoot `
            -Python -TimeoutSeconds 30
        Add-Check -Target $script:EntryPointChecks -Name ($check[0] + " --version") `
            -Passed ($versionOutput.Trim() -eq $check[1]) -Detail $versionOutput.Trim()
        $helpOutput = Invoke-Recorded -Name ("sdist-" + $check[0] + "-help") `
            -FilePath $exe -Arguments @("--help") -WorkingDirectory $script:RunRoot `
            -Python -TimeoutSeconds 30
        Add-Check -Target $script:EntryPointChecks -Name ($check[0] + " --help") `
            -Passed ($helpOutput.Contains($check[2])) -Detail $check[2]
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

    $outputFull = Get-ContainedPath -BasePath $script:RepoRoot -CandidatePath $OutputRoot
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
    $versionMatch = [regex]::Match($pyprojectText, '(?m)^version\s*=\s*"([^"]+)"')
    if (-not $nameMatch.Success -or -not $versionMatch.Success) {
        throw "Could not read project metadata"
    }
    $distributionName = $nameMatch.Groups[1].Value
    $projectVersion = $versionMatch.Groups[1].Value
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
        "powers-tool-$projectVersion.exe",
        "powers-tool-webui-$projectVersion.exe",
        "$normalizedDistribution-$projectVersion-py3-none-any.whl",
        "$normalizedDistribution-$projectVersion.tar.gz",
        "checksums.txt"
    )
    $releaseFiles = @(Get-ChildItem -LiteralPath $versionDir -File | Select-Object -ExpandProperty Name)
    Add-Check -Target $script:ArtifactChecks -Name "versioned release folder contents" `
        -Passed (@(Compare-Object -ReferenceObject $expectedRelease -DifferenceObject $releaseFiles).Count -eq 0) `
        -Detail ($releaseFiles -join ", ")

    $checksumPath = Join-Path $versionDir "checksums.txt"
    $checksumLines = Get-Content -LiteralPath $checksumPath
    $checksumNames = @()
    foreach ($line in $checksumLines) {
        if ($line -notmatch '^([0-9a-fA-F]{64})  (.+)$') {
            throw "Invalid checksum line: $line"
        }
        $checksumNames += $Matches[2]
        $actual = Get-Sha256File -LiteralPath (Join-Path $versionDir $Matches[2])
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

    $standaloneCli = Join-Path $versionDir "powers-tool-$projectVersion.exe"
    $standaloneWebui = Join-Path $versionDir "powers-tool-webui-$projectVersion.exe"
    Run-Python -Name "inspect-final-standalone" -Python $python -WorkingDirectory $script:RepoRoot `
        -Arguments @(
            "tests\packaging\inspect_pyinstaller.py",
            "--expected-version", $projectVersion,
            $standaloneCli,
            $standaloneWebui
        ) | Out-Null

    $script:CurrentStep = "clean sdist install"
    $sdist = Join-Path $versionDir "$normalizedDistribution-$projectVersion.tar.gz"
    $artifactEnvironment = Join-Path $script:RunRoot "envs\sdist"
    Invoke-Recorded -Name "create-sdist-environment" -FilePath "uv" `
        -Arguments @("venv", $artifactEnvironment, "--python", $python) `
        -WorkingDirectory $script:RunRoot | Out-Null
    $artifactPython = Join-Path $artifactEnvironment "Scripts\python.exe"
    Assert-File -Path $artifactPython
    Invoke-Recorded -Name "install-final-sdist" -FilePath "uv" `
        -Arguments @("pip", "install", "--python", $artifactPython, $sdist) `
        -WorkingDirectory $script:RunRoot | Out-Null

    $identityCode = @'
import importlib.metadata as metadata
import importlib.resources as resources
import powers_tool_cli
import powers_tool_core
import powers_tool_webui

expected_version = "__PROJECT_VERSION__"
assert metadata.version("powers-tool") == expected_version
assert powers_tool_core.__version__ == expected_version
assert powers_tool_cli.__version__ == expected_version
assert powers_tool_webui.__version__ == expected_version
static = resources.files("powers_tool_webui").joinpath("static")
for filename in ("index.html", "styles.css", "app.js"):
    assert static.joinpath(filename).is_file(), filename
'@
    $identityScript = Join-Path $script:RunRoot "identity_check.py"
    Write-Utf8NoBomFile -LiteralPath $identityScript `
        -Content $identityCode.Replace("__PROJECT_VERSION__", $projectVersion)
    Run-Python -Name "inspect-sdist-install" -Python $artifactPython `
        -WorkingDirectory $script:RunRoot -Arguments @($identityScript) | Out-Null
    Add-Check -Target $script:InstallChecks -Name "sdist package identity and contents" `
        -Passed $true -Detail "Installed final sdist and verified package metadata, imports, and WebUI assets"
    Test-InstalledEntryPoints -Python $artifactPython

    $script:CurrentStep = "final standalone smoke"
    $cliVersion = Invoke-Recorded -Name "standalone-cli-version" -FilePath $standaloneCli `
        -Arguments @("--version") -WorkingDirectory $script:RunRoot -TimeoutSeconds 30
    Add-Check -Target $script:StandaloneChecks -Name "CLI --version" `
        -Passed ($cliVersion.Trim() -eq "powers-tool $projectVersion") -Detail $cliVersion.Trim()
    $webuiVersion = Invoke-Recorded -Name "standalone-webui-version" -FilePath $standaloneWebui `
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

    $script:CurrentStep = "model-aware CLI preflight"
    $preflightRoot = Join-Path $script:RepoRoot (".tmp_tests\cli_preflight\" + $runName)
    Invoke-Recorded -Name "preflight-cli-all" -FilePath "powershell.exe" `
        -Arguments @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            (Join-Path $script:RepoRoot "scripts\preflight-cli.ps1"),
            "-Target", "all",
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
            "-PlanOnly"
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
            $script:FailedStep = "clean generated build directories"
            $script:FailureMessage = $_.Exception.Message
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
        Write-Utf8NoBomFile -LiteralPath (Join-Path $script:RunRoot "report.json") `
            -Content $reportJson
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
        Write-Utf8NoBomFile -LiteralPath (Join-Path $script:RunRoot "summary.md") `
            -Content ($summary -join "`n")
        Write-Host "Acceptance report: $(Join-Path $script:RunRoot 'report.json')"
    }
}

if (-not $script:Ok) { exit 1 }
exit 0
