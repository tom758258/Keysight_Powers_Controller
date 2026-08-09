param(
    [string]$Target = "all",
    [ValidateSet("smoke", "deep", "full")][string]$Suite = "full",
    [string]$OutputRoot = ".tmp_tests\cli_preflight"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$TmpRoot = Join-Path $RepoRoot ".tmp_tests"
. (Join-Path $PSScriptRoot "_validation_helpers.ps1")

function Assert-UnderTmpRoot {
    param([Parameter(Mandatory = $true)][string]$Path)
    $root = [System.IO.Path]::GetFullPath($TmpRoot).TrimEnd('\', '/')
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Preflight output must stay under .tmp_tests: $full"
    }
}

function Write-Utf8NoBomFile {
    param([Parameter(Mandatory = $true)][string]$LiteralPath, [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
    [System.IO.File]::WriteAllText($LiteralPath, $Value, [System.Text.UTF8Encoding]::new($false))
}

function ConvertTo-RepoRelativePath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $root = [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd('\', '/')
    $full = [System.IO.Path]::GetFullPath($Path)
    if ($full.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $full.Substring($root.Length + 1)
    }
    return $full
}

function Get-ProjectMetadata {
    $content = Get-Content -LiteralPath (Join-Path $RepoRoot "pyproject.toml") -Raw
    $nameMatch = [regex]::Match($content, '(?m)^name\s*=\s*"([^"]+)"')
    $versionMatch = [regex]::Match($content, '(?m)^version\s*=\s*"([^"]+)"')
    if (-not $nameMatch.Success -or -not $versionMatch.Success) { throw "Could not resolve project metadata." }
    return [pscustomobject]@{ name = $nameMatch.Groups[1].Value; version = $versionMatch.Groups[1].Value }
}

function Get-GitHead {
    $head = & git -C $RepoRoot rev-parse HEAD 2>$null
    if ($LASTEXITCODE -eq 0) { return $head.Trim() }
    return $null
}

function Get-NestedValue {
    param([Parameter(Mandatory = $true)]$Object, [Parameter(Mandatory = $true)][string]$Path)
    $value = $Object
    foreach ($part in $Path.Split('.')) {
        $property = $value.PSObject.Properties[$part]
        if ($null -eq $property) { throw "Missing JSON field '$Path'." }
        $value = $property.Value
    }
    return ,$value
}

function Invoke-PreflightCase {
    param([Parameter(Mandatory = $true)]$Case, [Parameter(Mandatory = $true)][string]$OutputDirectory)
    $safeName = $Case.name -replace '[^A-Za-z0-9_.-]', '_'
    $jsonPath = Join-Path $OutputDirectory ($safeName + ".json")
    $stdoutPath = Join-Path $OutputDirectory ($safeName + ".stdout.txt")
    $stderrPath = Join-Path $OutputDirectory ($safeName + ".stderr.txt")
    $arguments = @($Case.arguments + @("--save-json", $jsonPath))
    $started = Get-Date
    & $script:CliExecutable @arguments 1> $stdoutPath 2> $stderrPath
    $exitCode = $LASTEXITCODE
    $payload = $null
    $failures = [System.Collections.Generic.List[string]]::new()
    try {
        $payload = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json -ErrorAction Stop
    } catch {
        $failures.Add("JSON parse failed: $($_.Exception.Message)")
    }
    if ($exitCode -ne 0) { $failures.Add("Exit code was $exitCode.") }
    if ($null -ne $payload) {
        if ($payload.ok -ne $true) { $failures.Add("CLI envelope ok was not true.") }
        if ($payload.command.name -ne $Case.command) { $failures.Add("Command identity mismatch.") }
        if ($payload.execution.hardware_touched -ne $false) { $failures.Add("execution.hardware_touched was not false.") }
        if ($Case.mode -eq "dry-run" -and $payload.execution.dry_run -ne $true) { $failures.Add("execution.dry_run was not true.") }
        if ($Case.mode -eq "simulate" -and $payload.execution.mode -ne "simulate") { $failures.Add("execution.mode was not simulate.") }
        if (-not [string]::IsNullOrWhiteSpace($Case.expected_path)) {
            try {
                $actual = Get-NestedValue -Object $payload -Path $Case.expected_path
                if ([string]$actual -ne [string]$Case.expected_value) { $failures.Add("$($Case.expected_path) expected '$($Case.expected_value)' but got '$actual'.") }
            } catch { $failures.Add($_.Exception.Message) }
        }
        foreach ($expectation in $Case.expected_values.GetEnumerator()) {
            try {
                $actual = Get-NestedValue -Object $payload -Path $expectation.Key
                $actualJson = ConvertTo-Json -InputObject $actual -Compress -Depth 10
                $expectedJson = ConvertTo-Json -InputObject $expectation.Value -Compress -Depth 10
                if ($actualJson -cne $expectedJson) {
                    $failures.Add("$($expectation.Key) expected '$expectedJson' but got '$actualJson'.")
                }
            } catch { $failures.Add($_.Exception.Message) }
        }
    }
    return [pscustomobject]@{
        name = $Case.name; suite = $Case.suite; category = $Case.category; command = $Case.command
        arguments = $arguments; exit_code = $exitCode
        duration_ms = [math]::Round(((Get-Date) - $started).TotalMilliseconds, 3)
        ok = if ($null -ne $payload) { $payload.ok } else { $null }
        mode = if ($null -ne $payload) { $payload.execution.mode } else { $null }
        dry_run = if ($null -ne $payload) { $payload.execution.dry_run } else { $null }
        hardware_touched = if ($null -ne $payload) { $payload.execution.hardware_touched } else { $null }
        passed = ($failures.Count -eq 0); failures = $failures.ToArray()
        json_path = ConvertTo-RepoRelativePath -Path $jsonPath
        stdout_path = ConvertTo-RepoRelativePath -Path $stdoutPath
        stderr_path = ConvertTo-RepoRelativePath -Path $stderrPath
    }
}

$outputBase = if ([System.IO.Path]::IsPathRooted($OutputRoot)) { [System.IO.Path]::GetFullPath($OutputRoot) } else { [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputRoot)) }
Assert-UnderTmpRoot -Path $outputBase
$runRoot = Join-Path $outputBase ("run_" + (Get-Date -Format "yyyyMMdd_HHmmss_fff"))
Assert-UnderTmpRoot -Path $runRoot
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$script:CliExecutable = Join-Path $RepoRoot ".venv\Scripts\powers-tool.exe"
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $script:CliExecutable)) { throw "Repository .venv CLI is required." }
$env:PYTHONPATH = Join-Path $RepoRoot "src"
$metadata = Get-ProjectMetadata
if ($metadata.name -ne "powers-tool") { throw "Unexpected distribution name '$($metadata.name)'." }

try {
    $resolvedSuite = Resolve-ValidationSuite -Suite $Suite
    $targets = @(Resolve-ValidationPreflightTargets -Target $Target -Suite $resolvedSuite)
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 2
}
$targetReports = [System.Collections.Generic.List[object]]::new()
foreach ($resolvedTarget in $targets) {
    $targetDir = Join-Path $runRoot $resolvedTarget
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    $sequencePath = Join-Path $targetDir "sequence-readonly.yaml"
    if ($resolvedSuite -ne "smoke") {
        Write-Utf8NoBomFile -LiteralPath $sequencePath -Value "version: 1`nsteps:`n  - action: readback`n    channel: 1`n  - action: output-state`n    channel: 1`n"
    }
    $startedAt = Get-Date
    $commands = [System.Collections.Generic.List[object]]::new()
    foreach ($case in @(Get-ValidationPreflightCases -Target $resolvedTarget -ArtifactDirectory $targetDir -SequencePath $sequencePath -Suite $resolvedSuite)) {
        $commands.Add((Invoke-PreflightCase -Case $case -OutputDirectory $targetDir))
    }
    $failed = @($commands | Where-Object { -not $_.passed })
    $profile = Get-ValidationTargetProfile -Target $resolvedTarget
    $report = [ordered]@{
        schema_version = 1; kind = "powers-tool-cli-preflight"; status = if ($failed.Count -eq 0) { "passed" } else { "failed" }
        target = $resolvedTarget; targets = @($resolvedTarget); suite = $resolvedSuite; model_id = $resolvedTarget; expected_model = $profile.model
        package_version = $metadata.version; git_head = Get-GitHead; generated_at = (Get-Date).ToUniversalTime().ToString("o")
        validation_mode = "no-hardware-cli-preflight"; hardware_touched = $false; simulator_resource = $profile.simulator_resource
        support_policy_mode = "no-hardware"; visa_io_performed = $false; resource_scan_performed = $false; resource_guess_performed = $false
        suites = @($profile.suites); commands = $commands.ToArray(); checks = @($commands | ForEach-Object { [pscustomobject]@{ name = $_.name; passed = $_.passed; failures = $_.failures } })
        artifact_paths = [ordered]@{ output_dir = ConvertTo-RepoRelativePath -Path $targetDir; report = ConvertTo-RepoRelativePath -Path (Join-Path $targetDir "report.json"); summary = ConvertTo-RepoRelativePath -Path (Join-Path $targetDir "summary.md") }
        summary_counts = [ordered]@{ total = $commands.Count; passed = $commands.Count - $failed.Count; failed = $failed.Count }
    }
    Write-Utf8NoBomFile -LiteralPath (Join-Path $targetDir "report.json") -Value ($report | ConvertTo-Json -Depth 30)
    $summary = @("# Powers Tool CLI Preflight", "", "Target: ``$resolvedTarget``", "Suite: ``$resolvedSuite``", "Status: ``$($report.status)``", "Hardware touched: ``false``", "", "| Command | Category | Exit | Result |", "| --- | --- | ---: | --- |")
    $summary += @($commands | ForEach-Object { "| ``$($_.name)`` | ``$($_.category)`` | $($_.exit_code) | ``$(if ($_.passed) { 'passed' } else { 'failed' })`` |" })
    Write-Utf8NoBomFile -LiteralPath (Join-Path $targetDir "summary.md") -Value ($summary -join "`n")
    $targetReports.Add([pscustomobject]$report)
}

$aggregateFailed = @($targetReports | Where-Object { $_.status -ne "passed" })
$aggregate = [ordered]@{
    schema_version = 1; kind = "powers-tool-cli-preflight"; status = if ($aggregateFailed.Count -eq 0) { "passed" } else { "failed" }
    target = $Target; targets = @($targets); suite = $resolvedSuite; package_version = $metadata.version; git_head = Get-GitHead
    generated_at = (Get-Date).ToUniversalTime().ToString("o"); validation_mode = "no-hardware-cli-preflight"; hardware_touched = $false
    support_policy_mode = "no-hardware"; visa_io_performed = $false; resource_scan_performed = $false; resource_guess_performed = $false
    target_results = @($targetReports | ForEach-Object { [pscustomobject]@{ target = $_.target; suite = $_.suite; status = $_.status; summary_counts = $_.summary_counts; artifact_paths = $_.artifact_paths } })
    artifact_paths = [ordered]@{ output_dir = ConvertTo-RepoRelativePath -Path $runRoot; report = ConvertTo-RepoRelativePath -Path (Join-Path $runRoot "report.json"); summary = ConvertTo-RepoRelativePath -Path (Join-Path $runRoot "summary.md") }
    summary_counts = [ordered]@{ targets = $targetReports.Count; passed = $targetReports.Count - $aggregateFailed.Count; failed = $aggregateFailed.Count }
}
Write-Utf8NoBomFile -LiteralPath (Join-Path $runRoot "report.json") -Value ($aggregate | ConvertTo-Json -Depth 20)
$aggregateSummary = @("# Powers Tool CLI Preflight", "", "Suite: ``$resolvedSuite``", "Status: ``$($aggregate.status)``", "Targets: ``$($targets -join ', ')``", "Hardware touched: ``false``", "", "| Target | Status |", "| --- | --- |")
$aggregateSummary += @($targetReports | ForEach-Object { "| ``$($_.target)`` | ``$($_.status)`` |" })
Write-Utf8NoBomFile -LiteralPath (Join-Path $runRoot "summary.md") -Value ($aggregateSummary -join "`n")
Write-Host "Report: $(ConvertTo-RepoRelativePath -Path (Join-Path $runRoot 'report.json'))"
Write-Host "Summary: $(ConvertTo-RepoRelativePath -Path (Join-Path $runRoot 'summary.md'))"
if ($aggregateFailed.Count -gt 0) { exit 1 }
exit 0
