param(
    [string]$Target,

    [Alias("Transport")]
    [string]$Connection,

    [string]$Resource,

    [string]$Backend,

    [ValidateSet("readonly", "safe-state", "output", "protection", "snapshot", "trigger-list", "software-sequence", "full")]
    [string]$Suite = "readonly",

    [switch]$PlanOnly,

    [switch]$SkipExternalPreflight,

    [bool]$Restore = $true
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$PolicyGatedCommands = @(
    "measure", "measure-all", "output-state", "read-status", "validate-readonly", "readback",
    "protection-status", "protection-set", "clear-protection", "snapshot", "restore-from-snapshot",
    "log", "doctor", "capabilities", "set", "apply", "output-on", "output-off", "safe-off",
    "cycle-output", "ramp", "ramp-list", "smoke-output", "sequence", "trigger-pulse",
    "trigger-status", "trigger-step", "trigger-list", "trigger-fire", "trigger-abort"
)
$ExemptLiveDiagnosticCommands = @("list-resources", "verify", "identify", "error", "clear")
$IdentityBearingExpectedModelCommands = @("verify", "identify")
$ModelAwareExpectedModelCommands = @(
    "set", "output-on", "output-off", "safe-off", "output-state", "cycle-output", "apply",
    "ramp", "smoke-output", "trigger-pulse", "trigger-status", "trigger-step", "trigger-list",
    "trigger-fire", "trigger-abort", "protection-set", "clear-protection", "snapshot",
    "restore-from-snapshot", "sequence", "ramp-list", "measure-all", "log", "doctor"
)
$RawDiagnosticCommands = @("error", "clear")
$NoPhysicalIdentityCommands = @("list-resources")
$IdnSelectedCommandsWithoutExplicitModelGuard = @(
    "measure", "read-status", "validate-readonly", "readback", "protection-status", "capabilities"
)
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$TmpRoot = Join-Path $RepoRoot ".tmp_tests"
. (Join-Path $PSScriptRoot "_validation_helpers.ps1")
$TargetMetadata = $script:ValidationTargetProfiles
$SupportedTargets = @(Get-SupportedTargetModelIds)
$PreflightScript = Join-Path $PSScriptRoot "preflight-cli.ps1"
$PythonExe = Join-Path (Join-Path $RepoRoot ".venv") "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonExe = "python"
}
$CliExecutable = if ($PythonExe -eq "python") { "powers-tool" } else { Join-Path (Split-Path -Parent $PythonExe) "powers-tool.exe" }
if ($PythonExe -ne "python" -and -not (Test-Path -LiteralPath $CliExecutable)) {
    $CliExecutable = "powers-tool"
}
$CliPrefix = @()
$script:TcpipSessionSettleDelayMs = 500
$script:LiveTcpipSubprocessAttempted = $false

function Get-ValidationChildPythonPath {
    $parts = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($env:PYTHONPATH)) { $parts.Add($env:PYTHONPATH) }
    $parts.Add((Join-Path $RepoRoot "src"))
    return ($parts -join [System.IO.Path]::PathSeparator)
}

function Fail-Validation {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [int]$Code = 2
    )

    [Console]::Error.WriteLine($Message)
    exit $Code
}

function Assert-UnderDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $comparison = [System.StringComparison]::OrdinalIgnoreCase
    if ($fullPath.Equals($fullRoot, $comparison)) {
        return
    }
    if ($fullPath.StartsWith($fullRoot + [System.IO.Path]::DirectorySeparatorChar, $comparison)) {
        return
    }
    if ($fullPath.StartsWith($fullRoot + [System.IO.Path]::AltDirectorySeparatorChar, $comparison)) {
        return
    }
    throw "Refusing to operate outside $fullRoot`: $fullPath"
}

function Reset-OutputDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )

    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    Assert-UnderDirectory -Path $Path -Root $Root
    if (Test-Path -LiteralPath $Path) {
        $resolvedPath = (Resolve-Path -LiteralPath $Path).Path
        Assert-UnderDirectory -Path $resolvedPath -Root $Root
        Remove-Item -LiteralPath $resolvedPath -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    return (Resolve-Path -LiteralPath $Path).Path
}

function ConvertTo-RepoRelativePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullRoot = [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $comparison = [System.StringComparison]::OrdinalIgnoreCase
    if ($fullPath.StartsWith($fullRoot + [System.IO.Path]::DirectorySeparatorChar, $comparison)) {
        return $fullPath.Substring($fullRoot.Length + 1)
    }
    return "<redacted-path>"
}

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][AllowEmptyString()][string[]]$Value
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($LiteralPath, $Value, $encoding)
}

function Format-CommandArgument {
    param([Parameter(Mandatory = $true)][string]$Argument)

    if ($Argument -match '\s') {
        return '"' + ($Argument -replace '"', '\"') + '"'
    }
    return $Argument
}

function Protect-Argument {
    param([Parameter(Mandatory = $true)][string]$Argument)

    if ($Argument -eq $script:RawResource) {
        return "<redacted>"
    }
    if ([System.IO.Path]::IsPathRooted($Argument)) {
        $fullArgument = [System.IO.Path]::GetFullPath($Argument)
        if (-not [string]::IsNullOrWhiteSpace($script:PrivateArtifactDir)) {
            $privateRoot = [System.IO.Path]::GetFullPath($script:PrivateArtifactDir).TrimEnd(
                [System.IO.Path]::DirectorySeparatorChar,
                [System.IO.Path]::AltDirectorySeparatorChar
            )
            if ($fullArgument.Equals($privateRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
                $fullArgument.StartsWith($privateRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
                return "<private-local-path>"
            }
        }
        $fullRoot = [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
        if ($fullArgument.StartsWith($fullRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
            return ConvertTo-RepoRelativePath -Path $fullArgument
        }
        return "<redacted-path>"
    }
    return $Argument
}

function Get-ShareablePythonCommand {
    if ($PythonExe -eq "python") {
        return "python"
    }
    return ".venv\\Scripts\\python.exe"
}

function Get-ShareableCliCommand {
    return "powers-tool"
}

function Add-SensitiveValue {
    param([AllowNull()][string]$Value)

    if (-not [string]::IsNullOrWhiteSpace($Value) -and -not ($script:SensitiveValues -contains $Value)) {
        $script:SensitiveValues.Add($Value)
    }
}

function Get-FreeFormIdnPattern {
    return '(?i)\b[A-Z][A-Z0-9 .&_-]{1,63}\s*,\s*(?=[A-Z0-9._/-]{2,32}\s*,)(?=[A-Z0-9._/-]*\d)[A-Z0-9][A-Z0-9._/-]{1,31}\s*,\s*([^,\r\n]{1,64})\s*,\s*(?=[A-Z0-9._/-]{1,32}(?:\s|$|["'';]))(?=[A-Z0-9._/-]*\d)[A-Z0-9][A-Z0-9._/-]{0,31}'
}

function Test-DistinctiveSensitiveToken {
    param([AllowNull()][string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }
    $trimmed = $Value.Trim()
    return $trimmed.Length -ge 4 -and $trimmed -notmatch '^0+$'
}

function Add-SerialSensitiveValue {
    param([AllowNull()][string]$Value)

    if (Test-DistinctiveSensitiveToken -Value $Value) {
        Add-SensitiveValue -Value $Value.Trim()
    }
}

function Add-SensitiveValuesFromText {
    param([AllowNull()][string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return
    }
    $idnPattern = Get-FreeFormIdnPattern
    foreach ($match in [regex]::Matches($Text, $idnPattern)) {
        Add-SerialSensitiveValue -Value $match.Groups[1].Value
    }
}

function Protect-ShareableText {
    param([AllowNull()][string]$Text)

    if ($null -eq $Text) {
        return $null
    }
    $redacted = [string]$Text
    Add-SensitiveValuesFromText -Text $redacted
    if (-not [string]::IsNullOrWhiteSpace($script:RawResource)) {
        $redacted = $redacted -replace [regex]::Escape($script:RawResource), $script:ResourceDisplay
    }
    # Protect VISA resources that appear in nested simulator/resource-manager diagnostics too.
    $redacted = $redacted -replace '(?i)\b(?:USB|TCPIP|ASRL|GPIB|PXI|VXI|SOCKET)\d*::[^\s"''<>|]+', "<redacted>"
    $idnPattern = Get-FreeFormIdnPattern
    $redacted = [regex]::Replace($redacted, $idnPattern, { param($match) "<redacted-idn>" })
    foreach ($value in @($script:SensitiveValues)) {
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $sensitiveTokenPattern = '(?<![A-Za-z0-9_-])' + [regex]::Escape($value) + '(?![A-Za-z0-9_-])'
            $redacted = [regex]::Replace($redacted, $sensitiveTokenPattern, "<redacted>")
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($RepoRoot)) {
        $redacted = $redacted -replace [regex]::Escape($RepoRoot), "<repository-root>"
    }
    if ($PythonExe -ne "python") {
        $redacted = $redacted -replace [regex]::Escape($PythonExe), (Get-ShareablePythonCommand)
    }
    $redacted = $redacted -replace '(?i)\b(?:10(?:\.\d{1,3}){3}|127(?:\.\d{1,3}){3}|169\.254(?:\.\d{1,3}){2}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2})\b', "<redacted-ip>"
    $redacted = $redacted -replace '(?i)[a-z]:(?:\\\\|\\)[^\r\n"''<>|?*]+', "<redacted-path>"
    $redacted = $redacted -replace '(?<![A-Za-z0-9_])/(?:home|users|mnt|tmp)/[^\r\n"''<>|]+', "<redacted-path>"
    return $redacted
}

function Test-ShareableSensitiveField {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowNull()][string]$ParentName
    )

    $normalized = $Name.Trim().ToLowerInvariant() -replace '-', '_'
    if ($normalized -in @("json_path", "stdout_path", "stderr_path", "stderr_scpi_path", "output_dir", "shareable_artifact_dir", "preflight_report")) {
        return $false
    }
    if ($normalized -in @("resource", "resource_alias", "visa_resource", "resource_name", "serial", "serial_number")) {
        return $true
    }
    if ($normalized -match '(?:^|_)(?:path|file|filename)$') {
        return $true
    }
    return ($normalized -eq "raw" -and $ParentName -eq "idn")
}

function ConvertTo-ShareableJsonValue {
    param(
        [AllowNull()]$Value,
        [AllowNull()][string]$FieldName,
        [AllowNull()][string]$ParentName
    )

    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [string]) {
        $safeStructuralField = ([string]$FieldName).Trim().ToLowerInvariant()
        if ($safeStructuralField -in @("name", "command", "suite", "phase", "validation_kind", "cleanup_role")) {
            if ($Value -match '(?i)\b(?:USB|TCPIP|ASRL|GPIB|PXI|VXI|SOCKET)\d*::[^\s"''<>|]+') {
                return "<redacted>"
            }
            return $Value
        }
        if (Test-ShareableSensitiveField -Name ([string]$FieldName) -ParentName $ParentName) {
            $normalized = ([string]$FieldName).Trim().ToLowerInvariant() -replace '-', '_'
            if ($normalized -in @("resource", "resource_alias", "visa_resource", "resource_name")) {
                return $script:ResourceDisplay
            }
            if ($normalized -eq "raw" -and $ParentName -eq "idn") {
                return "<redacted-idn>"
            }
            if ($normalized -match '(?:^|_)(?:path|file|filename)$') {
                return "<redacted-path>"
            }
            return "<redacted>"
        }
        return Protect-ShareableText -Text $Value
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $result = [ordered]@{}
        foreach ($key in $Value.Keys) {
            $result[[string]$key] = ConvertTo-ShareableJsonValue -Value $Value[$key] -FieldName ([string]$key) -ParentName $FieldName
        }
        return [pscustomobject]$result
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $items = New-Object System.Collections.Generic.List[object]
        foreach ($item in $Value) {
            $items.Add((ConvertTo-ShareableJsonValue -Value $item -FieldName $FieldName -ParentName $ParentName))
        }
        return ,($items.ToArray())
    }
    if ($Value -is [psobject] -and @($Value.PSObject.Properties).Count -gt 0) {
        $result = [ordered]@{}
        foreach ($property in $Value.PSObject.Properties) {
            $result[$property.Name] = ConvertTo-ShareableJsonValue -Value $property.Value -FieldName $property.Name -ParentName $FieldName
        }
        return [pscustomobject]$result
    }
    return $Value
}

function Ensure-ArtifactDirectories {
    if ([string]::IsNullOrWhiteSpace($script:OutputDir)) {
        throw "Output directory is not configured."
    }
    $script:PrivateArtifactDir = Join-Path $script:OutputDir "private"
    $script:ShareableArtifactDir = Join-Path $script:OutputDir "shareable"
    New-Item -ItemType Directory -Path $script:PrivateArtifactDir -Force | Out-Null
    New-Item -ItemType Directory -Path $script:ShareableArtifactDir -Force | Out-Null
}

function Write-ShareableTextArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$PrivatePath,
        [Parameter(Mandatory = $true)][string]$ShareablePath
    )

    $text = if (Test-Path -LiteralPath $PrivatePath) { Get-Content -LiteralPath $PrivatePath -Raw } else { "" }
    Write-Utf8NoBomFile -LiteralPath $ShareablePath -Value @((Protect-ShareableText -Text $text))
}

function Write-ShareableJsonArtifact {
    param(
        [Parameter(Mandatory = $true)][string]$PrivatePath,
        [Parameter(Mandatory = $true)][string]$ShareablePath,
        [AllowNull()]$Payload,
        [Parameter(Mandatory = $true)][ValidateSet("parsed", "missing", "failed")][string]$ParseStatus
    )

    if ($null -ne $Payload) {
        $shareablePayload = ConvertTo-ShareableJsonValue -Value $Payload -FieldName $null -ParentName $null
        Write-Utf8NoBomFile -LiteralPath $ShareablePath -Value @($shareablePayload | ConvertTo-Json -Depth 30)
        return
    }
    $placeholder = [pscustomobject]@{
        artifact_available = $false
        artifact_kind = "command_json"
        parse_status = $ParseStatus
        parse_error = if ($ParseStatus -eq "missing") { "JSON output file was not created." } else { "Could not parse command JSON." }
        private_raw_artifact_retained = (Test-Path -LiteralPath $PrivatePath)
    }
    Write-Utf8NoBomFile -LiteralPath $ShareablePath -Value @($placeholder | ConvertTo-Json -Depth 10)
}

function Protect-Arguments {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    return @($Arguments | ForEach-Object { Protect-Argument -Argument $_ })
}

function Get-GitHead {
    try {
        $head = & git -C $RepoRoot rev-parse HEAD 2>$null
        if ($LASTEXITCODE -eq 0) {
            return [string]$head
        }
    }
    catch {
    }
    return $null
}

function Get-PackageVersion {
    $pyproject = Join-Path $RepoRoot "pyproject.toml"
    if (-not (Test-Path -LiteralPath $pyproject)) {
        return $null
    }
    foreach ($line in Get-Content -LiteralPath $pyproject) {
        if ($line -match '^\s*version\s*=\s*"([^"]+)"') {
            return $Matches[1]
        }
    }
    return $null
}

function Resolve-Target {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        Fail-Validation "Missing required -Target. Supported canonical model IDs: $($SupportedTargets -join ', '). generic-scpi is no-hardware planning only."
    }
    if ($Value -notin $SupportedTargets) {
        Fail-Validation "Unsupported -Target '$Value'. Use one canonical model_id: $($SupportedTargets -join ', ')."
    }
    return $Value
}

function Resolve-Connection {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        Fail-Validation "Missing required -Connection. Supported names: USB/local, LAN/network, or ASRL/RS-232/serial."
    }
    $normalized = $Value.Trim().ToUpperInvariant()
    if ($normalized -in @("USB", "LOCAL", "USB-LOCAL")) {
        return "USB"
    }
    if ($normalized -in @("LAN", "NETWORK", "TCPIP", "TCP/IP", "LAN-NETWORK")) {
        return "LAN"
    }
    if ($normalized -in @("ASRL", "RS232", "RS-232", "SERIAL")) {
        return "ASRL"
    }
    Fail-Validation "Unsupported -Connection '$Value'. Supported names: USB/local, LAN/network, or ASRL/RS-232/serial."
}

function Get-TargetChannels {
    param([string]$Model)

    if ($TargetMetadata.Contains($Model)) {
        return @($TargetMetadata[$Model].channels)
    }
    Fail-Validation "Unsupported -Target '$Model'. Supported targets: $($SupportedTargets -join ', ')."
}

function Get-SupportedSuites {
    param([string]$Model)

    if ($TargetMetadata.Contains($Model)) {
        return @($TargetMetadata[$Model].suites)
    }
    Fail-Validation "Unsupported -Target '$Model'. Supported targets: $($SupportedTargets -join ', ')."
}

function Test-LiveExecutionMode {
    param([string]$Mode)

    return $Mode -in @("real", "live")
}

function Test-LiveTcpipPhase {
    param([AllowNull()][string]$Phase)

    return (
        $Phase -ceq "live" -and
        $script:ConnectionLabel -ceq "LAN" -and
        $script:TransportScope -ceq "tcpip"
    )
}

function Invoke-LiveTcpipSubprocessSettle {
    param([AllowNull()][string]$Phase)

    if (-not (Test-LiveTcpipPhase -Phase $Phase)) {
        return 0
    }
    $settleBeforeMs = 0
    if ($script:LiveTcpipSubprocessAttempted) {
        $settleBeforeMs = $script:TcpipSessionSettleDelayMs
        Start-Sleep -Milliseconds $settleBeforeMs
    }
    $script:LiveTcpipSubprocessAttempted = $true
    return $settleBeforeMs
}

function Get-CaseArtifactBaseName {
    param([Parameter(Mandatory = $true)]$Case)

    return "$($Case.phase)-$($Case.name)"
}

function Get-CaseAttemptArtifactBaseName {
    param(
        [Parameter(Mandatory = $true)]$Case,
        [Parameter(Mandatory = $true)][int]$AttemptNumber
    )

    $baseName = Get-CaseArtifactBaseName -Case $Case
    if (Test-LiveTcpipPhase -Phase $Case.phase) {
        return "$baseName-attempt-$AttemptNumber"
    }
    return $baseName
}

function New-CommandCase {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Suite,
        [Parameter(Mandatory = $true)][string]$Phase,
        [Parameter(Mandatory = $true)][string[]]$Args,
        [bool]$ExpectedSuccess = $true,
        [string]$ExpectedErrorContains,
        [bool]$StateChanging = $false,
        [bool]$LiveHardwareExpected = $false,
        [string]$CleanupRole,
        [string]$ValidationKind,
        [int[]]$ExpectedChannels = @(),
        [AllowNull()]$ExpectedOutputEnabled = $null,
        [string[]]$GeneratedArtifacts = @(),
        [string[]]$CompareSnapshotPaths = @(),
        [bool]$CandidateScopeRequired = $false,
        [bool]$OperatorInteractionRequired = $false
    )

    return [pscustomobject]@{
        name = $Name
        suite = $Suite
        phase = $Phase
        args = $Args
        expected_success = $ExpectedSuccess
        expected_error_contains = $ExpectedErrorContains
        state_changing = $StateChanging
        live_hardware_expected = $LiveHardwareExpected
        cleanup_role = $CleanupRole
        validation_kind = $ValidationKind
        expected_channels = @($ExpectedChannels)
        expected_output_enabled = $ExpectedOutputEnabled
        generated_artifacts = @($GeneratedArtifacts)
        compare_snapshot_paths = @($CompareSnapshotPaths)
        candidate_scope_required = $CandidateScopeRequired
        operator_interaction_required = $OperatorInteractionRequired
    }
}

function Test-CurrentConnectionSupportsCandidates {
    param([Parameter(Mandatory = $true)][string]$Command)

    if ($null -eq $script:CandidateInventory) { return $false }
    $modelProperty = $script:CandidateInventory.PSObject.Properties[$script:NormalizedTarget]
    if ($null -eq $modelProperty -or $Command -notin @($modelProperty.Value.commands)) {
        return $false
    }
    return @($modelProperty.Value.connections | Where-Object {
        $_.Count -eq 2 -and
        $_[0] -eq $script:TransportScope -and
        $_[1] -eq $script:BackendArtifact.backend_scope
    }).Count -eq 1
}

function Load-CoreSupportPolicyInventory {
    $code = @'
import json
import sys
from powers_tool_core.models import CANDIDATE_MODEL_IDS
from powers_tool_core.support_policy import (
    VALIDATION_STATUS_TRANSPORT_PENDING,
    exact_live_support_metadata,
    internal_validation_candidate_inventory,
    live_support_policy_metadata,
)

data = {
    model: {
        'commands': set(entry['commands']),
        'connections': set(entry['connections']),
    }
    for model, entry in internal_validation_candidate_inventory().items()
}
for model in CANDIDATE_MODEL_IDS:
    projected = data.setdefault(model, {'commands': set(), 'connections': set()})
    for command, entry in live_support_policy_metadata(model)['commands'].items():
        pending_scopes = [
            scope
            for scope in entry['scopes']
            if scope['validation_status'] == VALIDATION_STATUS_TRANSPORT_PENDING
        ]
        if pending_scopes:
            projected['commands'].add(command)
            projected['connections'].update(
                (scope['transport_scope'], scope['backend_scope'])
                for scope in pending_scopes
            )
exact = exact_live_support_metadata(
    model_id=sys.argv[1],
    resource=sys.argv[2],
    backend=sys.argv[3],
)
print(json.dumps({
    'candidate_inventory': {
        model: {
            'commands': sorted(entry['commands']),
            'connections': [list(value) for value in sorted(entry['connections'])],
        }
        for model, entry in data.items()
    },
    'product_open_commands': sorted(
        command
        for command, entry in exact['commands'].items()
        if entry['product_open'] and not entry['policy_exempt'] and not entry['offline_only']
    ),
    'validation_pending_commands': sorted(
        command
        for command, entry in exact['commands'].items()
        if entry['exact_scope_validation_status'] == VALIDATION_STATUS_TRANSPORT_PENDING
    ),
}))
'@
    $hadPythonPath = $null -ne [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $oldPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    try {
        [Environment]::SetEnvironmentVariable("PYTHONPATH", (Get-ValidationChildPythonPath), "Process")
        $inventoryJson = & $PythonExe -c $code $script:NormalizedTarget $script:TransportScope $script:BackendArtifact.backend_scope
    }
    finally {
        if ($hadPythonPath) { [Environment]::SetEnvironmentVariable("PYTHONPATH", $oldPythonPath, "Process") }
        else { [Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process") }
    }
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($inventoryJson -join ""))) {
        throw "Core validation support-policy inventory could not be loaded."
    }
    try {
        $inventory = ($inventoryJson -join "`n") | ConvertFrom-Json
        $script:CandidateInventory = $inventory.candidate_inventory
        $script:ProductOpenCommands = @($inventory.product_open_commands)
        $script:ValidationPendingCommands = @($inventory.validation_pending_commands)
    }
    catch { throw "Core validation support-policy inventory is malformed." }
}

function Resolve-ValidationSupportPolicy {
    param([Parameter(Mandatory = $true)][object[]]$LiveCases)

    $commands = @($LiveCases | Where-Object {
        $_.phase -eq "live" -and [bool]$_.live_hardware_expected -and $_.args.Count -gt 0 -and
        [string]$_.args[0] -in $script:PolicyGatedCommands
    } | ForEach-Object { [string]$_.args[0] } | Sort-Object -Unique)
    $pendingCommands = New-Object System.Collections.Generic.List[string]
    foreach ($command in $commands) {
        if ($command -in $script:ProductOpenCommands) { continue }
        if (
            $command -in $script:ValidationPendingCommands -or
            (Test-CurrentConnectionSupportsCandidates -Command $command)
        ) {
            $pendingCommands.Add($command)
            continue
        }
        throw "Live command '$command' is neither Product-open nor an explicit validation candidate for the selected exact scope."
    }
    $script:PendingLiveSupportAllowed = $pendingCommands.Count -gt 0
    $script:SupportPolicyMode = if ($script:PendingLiveSupportAllowed) { "validation" } else { "product" }
}

function Get-BaseValidationCommandArguments {
    param(
        [Parameter(Mandatory = $true)]$Case,
        [Parameter(Mandatory = $true)][string]$JsonPath
    )

    $arguments = Add-LiveExpectedModelArgument -Case $Case
    $arguments = Add-ValidationSupportPolicyArgument -Arguments $arguments
    if ($Case.phase -eq "live") {
        $arguments = Add-BackendArgument -Arguments $arguments
    }
    return $arguments
}

function Add-BackendArgument {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    if (-not [string]::IsNullOrWhiteSpace($script:BackendValue)) {
        return @($Arguments + @("--backend", $script:BackendValue))
    }
    return $Arguments
}

function Add-ValidationSupportPolicyArgument {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    if ($Arguments.Count -eq 0) {
        return $Arguments
    }
    $command = $Arguments[0].Trim().ToLowerInvariant()
    if ($command -in $script:ExemptLiveDiagnosticCommands -or $command -notin $script:PolicyGatedCommands) {
        return $Arguments
    }
    if (-not $script:PendingLiveSupportAllowed) {
        return $Arguments
    }
    if ($Arguments -contains "--validation-allow-pending-live-support") {
        return $Arguments
    }
    return @($Arguments + "--validation-allow-pending-live-support")
}

function Get-LiveCommandIdentityContract {
    param([Parameter(Mandatory = $true)][string]$Command)

    $normalized = $Command.Trim().ToLowerInvariant()
    if ($normalized -in $script:IdentityBearingExpectedModelCommands) {
        return "identity_expected_model"
    }
    if ($normalized -in $script:ModelAwareExpectedModelCommands) {
        return "model_aware_expected_model"
    }
    if ($normalized -in $script:RawDiagnosticCommands) {
        return "raw_diagnostic"
    }
    if ($normalized -in $script:NoPhysicalIdentityCommands) {
        return "no_physical_identity"
    }
    if ($normalized -in $script:IdnSelectedCommandsWithoutExplicitModelGuard) {
        return "idn_selected_without_explicit_guard"
    }
    return "unclassified"
}

function Add-LiveExpectedModelArgument {
    param([Parameter(Mandatory = $true)]$Case)

    if ($Case.phase -ne "live" -or $Case.args.Count -eq 0) {
        return $Case.args
    }
    $contract = Get-LiveCommandIdentityContract -Command $Case.args[0]
    if ($contract -in @("identity_expected_model", "model_aware_expected_model")) {
        if ($Case.args -contains "--model") {
            return $Case.args
        }
        return @($Case.args + @("--model", $script:NormalizedTarget))
    }
    if ($Case.args -contains "--model") {
        throw "$($Case.args[0]) does not accept a live expected-model argument."
    }
    return $Case.args
}

function Get-ValidationCommandArguments {
    param(
        [Parameter(Mandatory = $true)]$Case,
        [Parameter(Mandatory = $true)][string]$JsonPath
    )

    $arguments = @(Get-BaseValidationCommandArguments -Case $Case -JsonPath $JsonPath)
    $saveJsonIndexes = @()
    for ($index = 0; $index -lt $arguments.Count; $index++) {
        if ($arguments[$index] -ceq "--save-json") {
            $saveJsonIndexes += $index
        }
    }
    if ($saveJsonIndexes.Count -gt 1) {
        throw "$($Case.name) contains duplicate --save-json arguments."
    }
    if ($saveJsonIndexes.Count -eq 1) {
        $saveJsonIndex = $saveJsonIndexes[0]
        if ($saveJsonIndex + 1 -ge $arguments.Count) {
            throw "$($Case.name) contains --save-json without a path."
        }
        $arguments[$saveJsonIndex + 1] = $JsonPath
    }
    else {
        $arguments = @($arguments + @("--save-json", $JsonPath))
    }
    return $arguments
}

function Get-TransportScope {
    param([Parameter(Mandatory = $true)][string]$Connection)

    switch ($Connection) {
        "USB" { return "usb" }
        "LAN" { return "tcpip" }
        "ASRL" { return "asrl" }
        default { throw "Unsupported validation connection '$Connection'." }
    }
}

function Get-BackendArtifactFields {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return [pscustomobject]@{
            backend = "system_visa"
            backend_scope = "system_visa"
            backend_argument = $null
        }
    }
    if ($Value.Trim().ToLowerInvariant() -eq "@py") {
        return [pscustomobject]@{
            backend = $Value
            backend_scope = "pyvisa_py"
            backend_argument = $Value
        }
    }
    if ($Value.Trim().ToLowerInvariant() -eq "@bt") {
        return [pscustomobject]@{
            backend = $Value
            backend_scope = "pyvisa_bt"
            backend_argument = $Value
        }
    }
    return [pscustomobject]@{
        backend = $Value
        backend_scope = "custom_visa"
        backend_argument = $Value
    }
}

function Get-PropertyValue {
    param(
        [AllowNull()]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function ConvertTo-IdentityLookupKey {
    param(
        [AllowNull()]$Value,
        [switch]$Model
    )

    if ($Value -isnot [string]) {
        return $null
    }
    try {
        $normalized = $Value.Normalize([System.Text.NormalizationForm]::FormKC)
    }
    catch {
        return $null
    }
    foreach ($character in $normalized.ToCharArray()) {
        $category = [System.Globalization.CharUnicodeInfo]::GetUnicodeCategory($character)
        if (
            $category -in @(
                [System.Globalization.UnicodeCategory]::Control,
                [System.Globalization.UnicodeCategory]::Format,
                [System.Globalization.UnicodeCategory]::Surrogate,
                [System.Globalization.UnicodeCategory]::PrivateUse,
                [System.Globalization.UnicodeCategory]::OtherNotAssigned
            ) -and -not [char]::IsWhiteSpace($character)
        ) {
            return $null
        }
    }
    $normalized = ((@($normalized.Trim() -split '\s+') | Where-Object { $_ -ne "" }) -join " ")
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return $null
    }
    if ($Model -and $normalized -cmatch '[^\x20-\x7e]') {
        return $null
    }
    return $normalized.ToLowerInvariant()
}

function Normalize-ObservedIdentityEvidence {
    param(
        [AllowNull()]$Data,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)]$TargetProfile
    )

    $failures = New-Object System.Collections.Generic.List[string]
    $identity = $null
    $resolvedIdentity = $null
    $identityValue = $null
    $resolvedValue = $null
    $reportedCanonicalVendorId = $null
    $reportedCanonicalModelId = $null
    $snapshotIdentity = $Command -in @("snapshot", "restore-from-snapshot")

    if ($null -eq $Data -or $Data -isnot [pscustomobject]) {
        $failures.Add("observed identity evidence data must be an object.")
    }
    elseif ($snapshotIdentity) {
        $reportedProperty = $Data.PSObject.Properties["reported_identity"]
        $resolvedProperty = $Data.PSObject.Properties["resolved_identity"]
        if ($null -eq $reportedProperty) {
            $failures.Add("observed identity evidence is missing data.reported_identity.")
        }
        elseif ($null -eq $reportedProperty.Value) {
            $failures.Add("observed identity evidence data.reported_identity must not be null.")
        }
        elseif ($reportedProperty.Value -isnot [pscustomobject]) {
            $failures.Add("observed identity evidence data.reported_identity must be an object.")
        }
        else {
            $identityValue = $reportedProperty.Value
            $allowedReportedFields = @("manufacturer", "model", "serial", "firmware", "parse_ok")
            $reportedFieldNames = @($identityValue.PSObject.Properties | ForEach-Object { $_.Name })
            foreach ($field in $allowedReportedFields) {
                if (-not ($reportedFieldNames -ccontains $field)) {
                    $failures.Add("observed identity evidence data.reported_identity is missing exact field $field.")
                }
            }
            foreach ($field in $reportedFieldNames) {
                if (-not ($allowedReportedFields -ccontains $field)) {
                    $failures.Add("observed identity evidence data.reported_identity contains unexpected field $field.")
                }
            }
        }
        if ($null -eq $resolvedProperty) {
            $failures.Add("observed identity evidence is missing data.resolved_identity.")
        }
        elseif ($null -eq $resolvedProperty.Value) {
            $failures.Add("observed identity evidence data.resolved_identity must not be null.")
        }
        elseif ($resolvedProperty.Value -isnot [pscustomobject]) {
            $failures.Add("observed identity evidence data.resolved_identity must be an object.")
        }
        else {
            $resolvedValue = $resolvedProperty.Value
            $allowedResolvedFields = @("vendor_id", "model_id", "model_name", "display_name")
            $resolvedFieldNames = @($resolvedValue.PSObject.Properties | ForEach-Object { $_.Name })
            foreach ($field in $allowedResolvedFields) {
                if (-not ($resolvedFieldNames -ccontains $field)) {
                    $failures.Add("observed identity evidence data.resolved_identity is missing exact field $field.")
                }
            }
            foreach ($field in $resolvedFieldNames) {
                if (-not ($allowedResolvedFields -ccontains $field)) {
                    $failures.Add("observed identity evidence data.resolved_identity contains unexpected field $field.")
                }
            }
        }
    }
    else {
        $resourceProperty = $Data.PSObject.Properties["resource"]
        $resourceIdnProperty = $null
        if ($null -ne $resourceProperty -and $resourceProperty.Value -is [pscustomobject]) {
            $resourceIdnProperty = $resourceProperty.Value.PSObject.Properties["idn"]
        }
        $dataIdnProperty = $Data.PSObject.Properties["idn"]
        $resourceIdnAttempted = $null -ne $resourceIdnProperty -and -not [object]::ReferenceEquals($null, $resourceIdnProperty.Value)
        $dataIdnAttempted = $null -ne $dataIdnProperty -and -not [object]::ReferenceEquals($null, $dataIdnProperty.Value)
        if ($resourceIdnAttempted -and $dataIdnAttempted) {
            $failures.Add("observed identity evidence contains ambiguous duplicate data.resource.idn and data.idn values.")
        }
        elseif (-not $resourceIdnAttempted -and -not $dataIdnAttempted) {
            if ($null -ne $resourceIdnProperty -or $null -ne $dataIdnProperty) {
                $failures.Add("observed identity evidence IDN object must not be null.")
            }
            else {
                $failures.Add("observed identity evidence requires object data.resource.idn or data.idn.")
            }
        }
        else {
            $idnProperty = if ($resourceIdnAttempted) { $resourceIdnProperty } else { $dataIdnProperty }
            if ($idnProperty.Value -isnot [pscustomobject]) {
                $failures.Add("observed identity evidence IDN value must be an object.")
            }
            else {
                $identityValue = $idnProperty.Value
            }
        }
    }

    if ($null -ne $identityValue) {
        $identityFields = [ordered]@{}
        foreach ($field in @("manufacturer", "model", "serial", "firmware")) {
            $property = $identityValue.PSObject.Properties[$field]
            if ($null -eq $property -or $property.Value -isnot [string] -or [string]::IsNullOrWhiteSpace($property.Value)) {
                $failures.Add("observed identity evidence $field must be a non-empty string.")
            }
            else {
                $identityFields[$field] = $property.Value
            }
        }
        $parseOkProperty = $identityValue.PSObject.Properties["parse_ok"]
        if ($null -eq $parseOkProperty -or $parseOkProperty.Value -isnot [System.Boolean] -or $parseOkProperty.Value -ne $true) {
            $failures.Add("observed identity evidence parse_ok must be exact boolean true.")
        }
        else {
            $identityFields["parse_ok"] = $true
        }
        $rawProperty = $identityValue.PSObject.Properties["raw"]
        if (-not $snapshotIdentity -and $null -ne $rawProperty) {
            if ($rawProperty.Value -isnot [string] -or [string]::IsNullOrWhiteSpace($rawProperty.Value)) {
                $failures.Add("observed identity evidence raw must be a non-empty string when present.")
            }
            else {
                $identityFields["raw"] = $rawProperty.Value
            }
        }
        $manufacturerProperty = $identityValue.PSObject.Properties["manufacturer"]
        $modelProperty = $identityValue.PSObject.Properties["model"]
        if ($snapshotIdentity) {
            $manufacturerKey = if ($null -eq $manufacturerProperty) { $null } else { ConvertTo-IdentityLookupKey -Value $manufacturerProperty.Value }
            $modelKey = if ($null -eq $modelProperty) { $null } else { ConvertTo-IdentityLookupKey -Value $modelProperty.Value -Model }
            $targetModelKey = ConvertTo-IdentityLookupKey -Value $TargetProfile.model -Model
            $manufacturerMatched = $false
            if ($null -ne $manufacturerKey) {
                foreach ($alias in @($TargetProfile.reported_manufacturer_aliases)) {
                    if ($manufacturerKey -ceq (ConvertTo-IdentityLookupKey -Value $alias)) {
                        $manufacturerMatched = $true
                        break
                    }
                }
            }
            if (-not $manufacturerMatched -or $null -eq $modelKey -or $modelKey -cne $targetModelKey) {
                $failures.Add("observed reported manufacturer and model do not resolve to the target canonical identity.")
            }
            else {
                $reportedCanonicalVendorId = [string]$TargetProfile.vendor_id
                $reportedCanonicalModelId = [string]$TargetProfile.model_id
            }
        }
        elseif ($null -ne $modelProperty -and $modelProperty.Value -is [string] -and $modelProperty.Value -cne [string]$TargetProfile.model) {
            $failures.Add("observed identity model does not match target model $($TargetProfile.model).")
        }
        if ($failures.Count -eq 0) {
            $identity = [pscustomobject]$identityFields
        }
    }

    if ($null -ne $resolvedValue) {
        $resolvedFields = [ordered]@{}
        foreach ($field in @("vendor_id", "model_id", "model_name", "display_name")) {
            $property = $resolvedValue.PSObject.Properties[$field]
            if ($null -eq $property -or $property.Value -isnot [string] -or [string]::IsNullOrWhiteSpace($property.Value)) {
                $failures.Add("observed resolved identity $field must be a non-empty string.")
            }
            else {
                $resolvedFields[$field] = $property.Value
            }
        }
        $vendorIdProperty = $resolvedValue.PSObject.Properties["vendor_id"]
        $modelIdProperty = $resolvedValue.PSObject.Properties["model_id"]
        $modelNameProperty = $resolvedValue.PSObject.Properties["model_name"]
        $displayNameProperty = $resolvedValue.PSObject.Properties["display_name"]
        if ($null -ne $vendorIdProperty -and $vendorIdProperty.Value -is [string] -and $vendorIdProperty.Value -cne [string]$TargetProfile.vendor_id) {
            $failures.Add("observed resolved identity vendor_id does not match target vendor_id $($TargetProfile.vendor_id).")
        }
        if ($null -ne $modelIdProperty -and $modelIdProperty.Value -is [string] -and $modelIdProperty.Value -cne [string]$TargetProfile.model_id) {
            $failures.Add("observed resolved identity model_id does not match target model_id $($TargetProfile.model_id).")
        }
        if ($null -ne $modelNameProperty -and $modelNameProperty.Value -is [string] -and $modelNameProperty.Value -cne [string]$TargetProfile.model) {
            $failures.Add("observed resolved identity model_name does not match target model $($TargetProfile.model).")
        }
        if ($null -ne $displayNameProperty -and $displayNameProperty.Value -is [string] -and $displayNameProperty.Value -cne [string]$TargetProfile.canonical_display_name) {
            $failures.Add("observed resolved identity display_name does not match target canonical display_name $($TargetProfile.canonical_display_name).")
        }
        if (
            $null -ne $reportedCanonicalVendorId -and
            $null -ne $vendorIdProperty -and
            $vendorIdProperty.Value -is [string] -and
            $vendorIdProperty.Value -cne $reportedCanonicalVendorId
        ) {
            $failures.Add("observed reported and resolved identity vendor IDs conflict.")
        }
        if (
            $null -ne $reportedCanonicalModelId -and
            $null -ne $modelIdProperty -and
            $modelIdProperty.Value -is [string] -and
            $modelIdProperty.Value -cne $reportedCanonicalModelId
        ) {
            $failures.Add("observed reported and resolved identity model IDs conflict.")
        }
        if ($failures.Count -eq 0) {
            $resolvedIdentity = [pscustomobject]$resolvedFields
        }
    }

    return [pscustomobject]@{
        identity = $identity
        resolved_identity = $resolvedIdentity
        failures = @($failures.ToArray())
    }
}

function Normalize-OutputStateEvidence {
    param(
        [AllowNull()]$Data,
        [Parameter(Mandatory = $true)][int[]]$ExpectedChannels
    )

    $records = New-Object System.Collections.Generic.List[object]
    $failures = New-Object System.Collections.Generic.List[string]
    $outputsProperty = if ($null -eq $Data) { $null } else { $Data.PSObject.Properties["outputs"] }
    $items = $null
    if ($null -ne $outputsProperty) {
        $value = $outputsProperty.Value
        if ($null -eq $value -or $value -is [string] -or $value -is [System.Collections.IDictionary] -or
            $value -is [pscustomobject] -or -not ($value -is [System.Collections.IEnumerable])) {
            $failures.Add("output-state data.outputs must be a non-null collection.")
        }
        else {
            $items = @($value)
            if ($items.Count -eq 0) {
                $failures.Add("output-state data.outputs must not be empty.")
            }
        }
    }
    elseif ($ExpectedChannels.Count -eq 1) {
        $enabledProperty = if ($null -eq $Data) { $null } else { $Data.PSObject.Properties["output_enabled"] }
        if ($null -eq $enabledProperty -or -not ($enabledProperty.Value -is [System.Boolean])) {
            $failures.Add("single-channel output-state data.output_enabled must be an exact boolean.")
        }
        else {
            $records.Add([pscustomobject]@{ channel = $ExpectedChannels[0]; enabled = $enabledProperty.Value })
        }
    }
    else {
        $failures.Add("all-channel output-state data.outputs is required.")
    }

    if ($null -ne $items) {
        $seen = @{}
        foreach ($item in $items) {
            if ($null -eq $item) {
                $failures.Add("output-state data.outputs contains a null record.")
                continue
            }
            $channelProperty = $item.PSObject.Properties["channel"]
            $enabledProperty = $item.PSObject.Properties["enabled"]
            if ($null -eq $channelProperty -or $null -eq $enabledProperty) {
                $failures.Add("each output-state record must contain channel and enabled.")
                continue
            }
            $channelValue = $channelProperty.Value
            $channel = 0
            $numericChannel = $false
            if ($channelValue -isnot [System.Boolean] -and $channelValue -isnot [string] -and $channelValue -is [System.ValueType]) {
                try {
                    $number = [Convert]::ToDouble($channelValue, [Globalization.CultureInfo]::InvariantCulture)
                    if (-not [double]::IsNaN($number) -and -not [double]::IsInfinity($number) -and $number -gt 0 -and $number -eq [Math]::Truncate($number) -and $number -le [int]::MaxValue) {
                        $channel = [int]$number
                        $numericChannel = $true
                    }
                }
                catch {}
            }
            if (-not $numericChannel) {
                $failures.Add("output-state record channel must be a finite positive integer number.")
                continue
            }
            if ($channel -notin $ExpectedChannels) {
                $failures.Add("output-state record contains unknown channel $channel.")
                continue
            }
            if ($seen.ContainsKey($channel)) {
                $failures.Add("output-state records contain duplicate channel $channel.")
                continue
            }
            if ($enabledProperty.Value -isnot [System.Boolean]) {
                $failures.Add("output-state record enabled must be an exact boolean.")
                continue
            }
            $seen[$channel] = $true
            $records.Add([pscustomobject]@{ channel = $channel; enabled = $enabledProperty.Value })
        }
        foreach ($expectedChannel in $ExpectedChannels) {
            if (-not $seen.ContainsKey($expectedChannel)) {
                $failures.Add("output-state records are missing expected channel $expectedChannel.")
            }
        }
    }

    return [pscustomobject]@{
        records = @($records.ToArray())
        failures = @($failures.ToArray())
    }
}

function Normalize-InstrumentErrorEvidence {
    param([AllowNull()]$Data)

    $failures = New-Object System.Collections.Generic.List[string]
    $records = $null
    $errorsProperty = if ($null -eq $Data) { $null } else { $Data.PSObject.Properties["errors"] }
    if ($null -eq $errorsProperty) {
        $failures.Add("instrument error evidence is missing data.errors.")
    }
    elseif ($null -eq $errorsProperty.Value) {
        $failures.Add("instrument error evidence data.errors must not be null.")
    }
    elseif ($errorsProperty.Value -is [string] -or
        $errorsProperty.Value -is [System.Collections.IDictionary] -or
        $errorsProperty.Value -is [pscustomobject] -or
        -not ($errorsProperty.Value -is [System.Collections.IEnumerable])) {
        $failures.Add("instrument error evidence data.errors must be a collection.")
    }
    else {
        $records = @($errorsProperty.Value)
        if ($records.Count -ne 0) {
            $failures.Add("instrument error evidence reported a non-empty error queue.")
        }
    }

    return [pscustomobject]@{
        records = $records
        failures = @($failures.ToArray())
    }
}

function New-CleanupEvidence {
    param([Parameter(Mandatory = $true)][string]$ValidationMode)

    $stateChanging = [bool]$script:StateChanging
    $requested = [bool]($stateChanging -and $Restore)
    $status = if ($ValidationMode -eq "planned") {
        "not_executed_plan_only"
    }
    elseif ($ValidationMode -eq "preflight_failed") {
        "not_executed_preflight_failed"
    }
    elseif ($ValidationMode -eq "confirmation_required") {
        "not_executed_confirmation_required"
    }
    elseif (-not $stateChanging) {
        "not_required"
    }
    elseif ($requested) {
        "pending"
    }
    else {
        "skipped_by_operator"
    }
    return [pscustomobject]@{
        requested = $requested
        attempted = $false
        safe_off_command = $null
        safe_off_exit_code = $null
        safe_off_ok = $null
        output_state_checked = $false
        all_outputs_off = $null
        error_queue_checked = $false
        instrument_errors = $null
        status = $status
    }
}

function New-ValidationSequenceFile {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Lines
    )

    Ensure-ArtifactDirectories
    $path = Join-Path $script:PrivateArtifactDir ($Name + ".yaml")
    Write-Utf8NoBomFile -LiteralPath $path -Value $Lines
    return $path
}

function New-ValidationSnapshotFile {
    Ensure-ArtifactDirectories
    $path = Join-Path $script:PrivateArtifactDir "generated-e36312a-snapshot.json"
    $snapshot = [pscustomobject]@{
        schema_version = 2
        kind = "powers-tool-snapshot"
        resource = $TargetMetadata["keysight-e36312a"].simulator_resource
        reported_identity = [pscustomobject]@{
            manufacturer = "KEYSIGHT"
            model = "E36312A"
            serial = "SIM000003"
            firmware = "1.0"
            parse_ok = $true
        }
        resolved_identity = [pscustomobject]@{
            vendor_id = "keysight"
            model_id = "keysight-e36312a"
            model_name = "E36312A"
            display_name = "Keysight E36312A"
        }
        errors = @()
        outputs = @([pscustomobject]@{ channel = 1; enabled = $false })
        readback = @([pscustomobject]@{ channel = 1; setpoints = [pscustomobject]@{ voltage = 1.0; current = 0.05 } })
        measurements = @([pscustomobject]@{ channel = 1; measurements = [pscustomobject]@{ voltage = 1.0; current = 0.0 } })
        protection = [pscustomobject]@{ over_voltage_tripped = $false; over_current_tripped = $false }
        protection_settings = @([pscustomobject]@{ channel = 1; protection = [pscustomobject]@{ ovp_voltage = 5.0; ocp_enabled = $true; ocp_delay = $null; ocp_delay_trigger = $null } })
    }
    Write-Utf8NoBomFile -LiteralPath $path -Value @($snapshot | ConvertTo-Json -Depth 20)
    return $path
}

function Get-ReadOnlyCases {
    param([string]$Model, [bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $TargetMetadata[$Model].simulator_resource }
    $modeFlag = if ($Live) { @() } else { @("--simulate") }
    $phase = if ($Live) { "live" } else { "preflight" }
    $cases = New-Object System.Collections.Generic.List[object]
    $channels = @(Get-TargetChannels -Model $Model)
    $cases.Add((New-CommandCase -Name "verify" -Suite "readonly" -Phase $phase -Args (@("verify") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live))
    $cases.Add((New-CommandCase -Name "identify" -Suite "readonly" -Phase $phase -Args (@("identify") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live))
    $cases.Add((New-CommandCase -Name "clear" -Suite "readonly" -Phase $phase -Args (@("clear") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live))
    $cases.Add((New-CommandCase -Name "error" -Suite "readonly" -Phase $phase -Args (@("error") + $modeFlag + @("--json", "--resource", $resource, "--max-reads", "20", "--log-scpi")) -LiveHardwareExpected:$Live -ValidationKind "empty-errors"))
    foreach ($channel in Get-TargetChannels -Model $Model) {
        $cases.Add((New-CommandCase -Name ("measure-ch" + $channel) -Suite "readonly" -Phase $phase -Args (@("measure") + $modeFlag + @("--json", "--resource", $resource, "--channel", [string]$channel, "--log-scpi")) -LiveHardwareExpected:$Live -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "measure"))))
        $cases.Add((New-CommandCase -Name ("output-state-ch" + $channel) -Suite "readonly" -Phase $phase -Args (@("output-state") + $modeFlag + @("--json", "--resource", $resource, "--channel", [string]$channel, "--log-scpi")) -LiveHardwareExpected:$Live -ExpectedChannels @($channel) -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "output-state"))))
    }
    $cases.Add((New-CommandCase -Name "read-status" -Suite "readonly" -Phase $phase -Args (@("read-status") + $modeFlag + @("--json", "--resource", $resource, "--all", "--log-scpi")) -LiveHardwareExpected:$Live -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "read-status"))))
    $cases.Add((New-CommandCase -Name "readback" -Suite "readonly" -Phase $phase -Args (@("readback") + $modeFlag + @("--json", "--resource", $resource, "--all", "--log-scpi")) -LiveHardwareExpected:$Live -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "readback"))))
    if ($Model -in @("keysight-e36312a", "keysight-edu36311a")) {
        $cases.Add((New-CommandCase -Name "validate-readonly" -Suite "readonly" -Phase $phase -Args (@("validate-readonly") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name "protection-status" -Suite "readonly" -Phase $phase -Args (@("protection-status") + $modeFlag + @("--json", "--resource", $resource, "--all", "--log-scpi")) -LiveHardwareExpected:$Live))
    }
    $cases.Add((New-CommandCase -Name "capabilities" -Suite "readonly" -Phase $phase -Args (@("capabilities") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "capabilities"))))
    if ($Model -ne "gw-instek-psm-2010") {
        if ($Live) {
            $cases.Add((New-CommandCase -Name "doctor-resource" -Suite "readonly" -Phase $phase -Args @("doctor", "--json", "--resource", $resource, "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "doctor" -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "doctor"))))
        }
        else {
            $cases.Add((New-CommandCase -Name "doctor-environment" -Suite "readonly" -Phase $phase -Args @("doctor", "--simulate", "--json") -ValidationKind "doctor-offline"))
        }
    }
    if ($Model -eq "keysight-e36312a") {
        $cases.Add((New-CommandCase -Name "measure-all" -Suite "readonly" -Phase $phase -Args (@("measure-all") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live -ValidationKind "measure-all" -ExpectedChannels $channels -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "measure-all"))))
        if ($Live) {
            $cases.Add((New-CommandCase -Name "readonly-error-queue-checkpoint" -Suite "readonly" -Phase $phase -Args @("error", "--json", "--resource", $resource, "--max-reads", "20", "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "empty-errors"))
        }
    }
    if ($Model -in @("keysight-e36312a", "keysight-edu36311a", "keysight-e3646a")) {
        $logCsv = Join-Path $script:PrivateArtifactDir ($phase + "-log.csv")
        $logJsonl = Join-Path $script:PrivateArtifactDir ($phase + "-log.jsonl")
        $cases.Add((New-CommandCase -Name "log-one-sample" -Suite "readonly" -Phase $phase -Args (@("log") + $modeFlag + @("--channel", "all", "--interval-sec", "0.1", "--samples", "1", "--csv", $logCsv, "--jsonl", $logJsonl, "--json", "--resource", $resource, "--log-scpi")) -LiveHardwareExpected:$Live -ValidationKind "log" -ExpectedChannels $channels -GeneratedArtifacts @($logCsv, $logJsonl) -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "log"))))
    }
    return $cases.ToArray()
}

function Get-SafeStateCases {
    param([string]$Model, [bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $TargetMetadata[$Model].simulator_resource }
    $phase = if ($Live) { "live" } else { "preflight" }
    $channels = @(Get-TargetChannels -Model $Model)
    $stateModeFlag = if ($Live) { @() } else { @("--simulate") }
    $stateArgs = @("output-state") + $stateModeFlag + @("--json", "--resource", $resource, "--channel", "all", "--log-scpi")
    $offArgs = if ($Live) {
        @("--json", "--resource", $resource, "--channel", "all", "--log-scpi")
    }
    else {
        @("--dry-run", "--json", "--model", $Model, "--channel", "all")
    }
    $stateValidation = if ($Live) { "output-state" } else { $null }
    return @(
        (New-CommandCase -Name "output-state-before" -Suite "safe-state" -Phase $phase -Args $stateArgs -LiveHardwareExpected:$Live -ExpectedChannels $channels -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "output-state"))),
        (New-CommandCase -Name "output-off-all" -Suite "safe-state" -Phase $phase -Args (@("output-off") + $offArgs) -StateChanging:$Live -LiveHardwareExpected:$Live -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "output-off"))),
        (New-CommandCase -Name "output-state-after-output-off" -Suite "safe-state" -Phase $phase -Args $stateArgs -LiveHardwareExpected:$Live -ValidationKind $stateValidation -ExpectedChannels $channels -ExpectedOutputEnabled $false -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "output-state"))),
        (New-CommandCase -Name "safe-off-all" -Suite "safe-state" -Phase $phase -Args (@("safe-off") + $offArgs) -StateChanging:$Live -LiveHardwareExpected:$Live -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "safe-off"))),
        (New-CommandCase -Name "output-state-after-safe-off" -Suite "safe-state" -Phase $phase -Args $stateArgs -LiveHardwareExpected:$Live -ValidationKind $stateValidation -ExpectedChannels $channels -ExpectedOutputEnabled $false -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "output-state")))
    )
}

function Get-OutputCases {
    param([string]$Model, [bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $TargetMetadata[$Model].simulator_resource }
    $modelArgs = if ($Live) { @() } else { @("--model", $Model) }
    $phase = if ($Live) { "live" } else { "preflight" }
    $cases = New-Object System.Collections.Generic.List[object]
    $channels = @(Get-TargetChannels -Model $Model)
    $allCommon = if ($Live) { @("--json", "--resource", $resource, "--channel", "all", "--log-scpi") } else { @("--dry-run", "--json") + $modelArgs + @("--channel", "all") }
    $cases.Add((New-CommandCase -Name "safe-off-before" -Suite "output" -Phase $phase -Args (@("safe-off") + $allCommon) -StateChanging:$Live -LiveHardwareExpected:$Live))
    foreach ($channel in Get-TargetChannels -Model $Model) {
        $common = if ($Live) { @("--json", "--resource", $resource, "--channel", [string]$channel, "--log-scpi") } else { @("--dry-run", "--json") + $modelArgs + @("--channel", [string]$channel) }
        $cases.Add((New-CommandCase -Name ("set-ch" + $channel) -Suite "output" -Phase $phase -Args (@("set") + $common + @("--voltage", "1", "--current", "0.05")) -StateChanging:$Live -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name ("output-off-ch" + $channel) -Suite "output" -Phase $phase -Args (@("output-off") + $common) -StateChanging:$Live -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name ("smoke-output-ch" + $channel) -Suite "output" -Phase $phase -Args (@("smoke-output") + $common + @("--voltage", "1", "--current", "0.05", "--duration-ms", "500", "--confirm")) -StateChanging:$Live -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name ("cycle-output-ch" + $channel) -Suite "output" -Phase $phase -Args (@("cycle-output") + $common + @("--duration-ms", "500", "--confirm")) -StateChanging:$Live -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name ("ramp-ch" + $channel) -Suite "output" -Phase $phase -Args (@("ramp") + $common + @("--start-voltage", "0", "--stop-voltage", "1", "--step-voltage", "0.25", "--current", "0.05", "--delay-ms", "100")) -StateChanging:$Live -LiveHardwareExpected:$Live))
        if ($Model -ne "keysight-e3646a") {
            $cases.Add((New-CommandCase -Name ("output-on-ch" + $channel) -Suite "output" -Phase $phase -Args (@("output-on") + $common + @("--confirm")) -StateChanging:$Live -LiveHardwareExpected:$Live -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "output-on"))))
            $stateArgs = if ($Live) { @("output-state", "--json", "--resource", $resource, "--channel", [string]$channel, "--log-scpi") } else { @("output-state", "--simulate", "--json", "--resource", $resource, "--channel", [string]$channel) }
            $stateValidation = if ($Live) { "output-state" } else { $null }
            $cases.Add((New-CommandCase -Name ("assert-output-on-ch" + $channel) -Suite "output" -Phase $phase -Args $stateArgs -LiveHardwareExpected:$Live -ValidationKind $stateValidation -ExpectedChannels @($channel) -ExpectedOutputEnabled $true))
            $cases.Add((New-CommandCase -Name ("standalone-output-off-ch" + $channel) -Suite "output" -Phase $phase -Args (@("output-off") + $common) -StateChanging:$Live -LiveHardwareExpected:$Live))
            $cases.Add((New-CommandCase -Name ("assert-output-off-ch" + $channel) -Suite "output" -Phase $phase -Args $stateArgs -LiveHardwareExpected:$Live -ValidationKind $stateValidation -ExpectedChannels @($channel) -ExpectedOutputEnabled $false))
        }
    }
    if ($Model -eq "keysight-e3646a") {
        $globalSwitchCommon = if ($Live) { @("--json", "--resource", $resource, "--channel", "1", "--log-scpi") } else { @("--dry-run", "--json") + $modelArgs + @("--channel", "1") }
        $cases.Add((New-CommandCase -Name "output-on-global" -Suite "output" -Phase $phase -Args (@("output-on") + $globalSwitchCommon + @("--confirm")) -StateChanging:$Live -LiveHardwareExpected:$Live -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "output-on"))))
        $globalStateArgs = if ($Live) { @("output-state", "--json", "--resource", $resource, "--channel", "all", "--log-scpi") } else { @("output-state", "--simulate", "--json", "--resource", $resource, "--channel", "all") }
        $globalStateValidation = if ($Live) { "output-state" } else { $null }
        $cases.Add((New-CommandCase -Name "assert-global-output-on" -Suite "output" -Phase $phase -Args $globalStateArgs -LiveHardwareExpected:$Live -ValidationKind $globalStateValidation -ExpectedChannels $channels -ExpectedOutputEnabled $true))
        $cases.Add((New-CommandCase -Name "output-off-global" -Suite "output" -Phase $phase -Args (@("output-off") + $globalSwitchCommon) -StateChanging:$Live -LiveHardwareExpected:$Live))
        $cases.Add((New-CommandCase -Name "assert-global-output-off" -Suite "output" -Phase $phase -Args $globalStateArgs -LiveHardwareExpected:$Live -ValidationKind $globalStateValidation -ExpectedChannels $channels -ExpectedOutputEnabled $false))
    }
    if ($Live) {
        $readbackArgs = @("readback", "--json", "--resource", $resource, "--all", "--log-scpi")
    }
    else {
        $readbackArgs = @("readback", "--simulate", "--json", "--resource", $resource, "--all")
    }
    $cases.Add((New-CommandCase -Name "readback-after-set" -Suite "output" -Phase $phase -Args $readbackArgs -LiveHardwareExpected:$Live))
    $cases.Add((New-CommandCase -Name "apply-no-output-all" -Suite "output" -Phase $phase -Args (@("apply") + $allCommon + @("--voltage", "1", "--current", "0.05", "--no-output")) -StateChanging:$Live -LiveHardwareExpected:$Live))
    $cases.Add((New-CommandCase -Name "safe-off-cleanup" -Suite "output" -Phase $phase -Args (@("safe-off") + $allCommon) -StateChanging:$Live -LiveHardwareExpected:$Live))
    return $cases.ToArray()
}

function Get-ProtectionCases {
    param([string]$Model, [bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $TargetMetadata[$Model].simulator_resource }
    $phase = if ($Live) { "live" } else { "preflight" }
    $modeFlag = if ($Live) { @() } else { @("--simulate") }
    $writeFlag = if ($Live) { @() } else { @("--dry-run") }
    return @(
        (New-CommandCase -Name "protection-status-before" -Suite "protection" -Phase $phase -Args (@("protection-status") + $modeFlag + @("--json", "--resource", $resource, "--all", "--log-scpi")) -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "protection-set-all" -Suite "protection" -Phase $phase -Args (@("protection-set") + $writeFlag + @("--json", "--resource", $resource, "--channel", "all", "--ovp-voltage", "5", "--ocp", "on", "--confirm", "--log-scpi")) -StateChanging:$Live -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "protection-status-after-set" -Suite "protection" -Phase $phase -Args (@("protection-status") + $modeFlag + @("--json", "--resource", $resource, "--all", "--log-scpi")) -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "clear-protection-all" -Suite "protection" -Phase $phase -Args (@("clear-protection") + $writeFlag + @("--json", "--resource", $resource, "--all", "--confirm", "--log-scpi")) -StateChanging:$Live -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "protection-status-after-clear" -Suite "protection" -Phase $phase -Args (@("protection-status") + $modeFlag + @("--json", "--resource", $resource, "--all", "--log-scpi")) -LiveHardwareExpected:$Live)
    )
}

function Get-SnapshotCases {
    param([string]$Model, [bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $TargetMetadata["keysight-e36312a"].simulator_resource }
    $phase = if ($Live) { "live" } else { "preflight" }
    $snapshotPath = if ($Live) { Join-Path $script:PrivateArtifactDir "snapshot-live.json" } else { New-ValidationSnapshotFile }
    $modeFlag = if ($Live) { @() } else { @("--simulate") }
    $cases = New-Object System.Collections.Generic.List[object]
    $cases.AddRange(@(
        (New-CommandCase -Name "snapshot-save" -Suite "snapshot" -Phase $phase -Args (@("snapshot") + $modeFlag + @("--json", "--resource", $resource, "--log-scpi", "--snapshot-json", $snapshotPath)) -LiveHardwareExpected:$Live -GeneratedArtifacts @($snapshotPath)),
        (New-CommandCase -Name "snapshot-compare" -Suite "snapshot" -Phase $phase -Args (@("snapshot") + $modeFlag + @("--json", "--resource", $resource, "--compare", $snapshotPath, "--log-scpi")) -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "restore-from-snapshot-plan" -Suite "snapshot" -Phase $phase -Args @("restore-from-snapshot", "--dry-run", "--json", "--snapshot", $snapshotPath, "--resource", $resource, "--channel", "all") -StateChanging:$false -LiveHardwareExpected:$false)
    ))
    if ($Live -and $Model -eq "keysight-e36312a") {
        $snapshotA = Join-Path $script:PrivateArtifactDir "restore-off-snapshot-a.json"
        $snapshotB = Join-Path $script:PrivateArtifactDir "restore-off-snapshot-b.json"
        $snapshotC = Join-Path $script:PrivateArtifactDir "restore-off-snapshot-c.json"
        $snapshotOn = Join-Path $script:PrivateArtifactDir "restore-on-snapshot.json"
        $commonAll = @("--json", "--resource", $resource, "--channel", "all", "--log-scpi")
        $cases.Add((New-CommandCase -Name "restore-off-safe-off" -Suite "snapshot" -Phase $phase -Args (@("safe-off") + $commonAll) -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-off-program-a" -Suite "snapshot" -Phase $phase -Args (@("apply") + $commonAll + @("--voltage", "1", "--current", "0.05", "--no-output")) -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-off-protection-a" -Suite "snapshot" -Phase $phase -Args @("protection-set", "--json", "--resource", $resource, "--channel", "all", "--ovp-voltage", "5", "--ocp", "on", "--confirm", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-off-save-a" -Suite "snapshot" -Phase $phase -Args @("snapshot", "--json", "--resource", $resource, "--snapshot-json", $snapshotA, "--log-scpi") -LiveHardwareExpected:$true -GeneratedArtifacts @($snapshotA)))
        $cases.Add((New-CommandCase -Name "restore-off-mutate-setpoints" -Suite "snapshot" -Phase $phase -Args (@("apply") + $commonAll + @("--voltage", "0.5", "--current", "0.04", "--no-output")) -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-off-mutate-protection" -Suite "snapshot" -Phase $phase -Args @("protection-set", "--json", "--resource", $resource, "--channel", "all", "--ovp-voltage", "4", "--ocp", "off", "--confirm", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-off-save-b" -Suite "snapshot" -Phase $phase -Args @("snapshot", "--json", "--resource", $resource, "--snapshot-json", $snapshotB, "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "snapshot-mutation" -GeneratedArtifacts @($snapshotB) -CompareSnapshotPaths @($snapshotA,$snapshotB)))
        $cases.Add((New-CommandCase -Name "restore-off-execute" -Suite "snapshot" -Phase $phase -Args @("restore-from-snapshot", "--json", "--resource", $resource, "--snapshot", $snapshotA, "--channel", "all", "--confirm", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true -ValidationKind "restore" -ExpectedChannels @(1,2,3) -CandidateScopeRequired:(Test-CurrentConnectionSupportsCandidates -Command "restore-from-snapshot")))
        $cases.Add((New-CommandCase -Name "restore-off-save-c" -Suite "snapshot" -Phase $phase -Args @("snapshot", "--json", "--resource", $resource, "--snapshot-json", $snapshotC, "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "snapshot-compare" -GeneratedArtifacts @($snapshotC) -CompareSnapshotPaths @($snapshotA,$snapshotC)))
        $cases.Add((New-CommandCase -Name "restore-off-assert-outputs" -Suite "snapshot" -Phase $phase -Args @("output-state", "--json", "--resource", $resource, "--channel", "all", "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "output-state" -ExpectedChannels @(1,2,3) -ExpectedOutputEnabled $false))
        $cases.Add((New-CommandCase -Name "restore-on-safe-off" -Suite "snapshot" -Phase $phase -Args (@("safe-off") + $commonAll) -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-on-program-all" -Suite "snapshot" -Phase $phase -Args (@("apply") + $commonAll + @("--voltage", "1", "--current", "0.05", "--no-output")) -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-on-enable-ch1" -Suite "snapshot" -Phase $phase -Args @("output-on", "--json", "--resource", $resource, "--channel", "1", "--confirm", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true -CandidateScopeRequired:(Test-CurrentConnectionSupportsCandidates -Command "output-on")))
        $cases.Add((New-CommandCase -Name "restore-on-save" -Suite "snapshot" -Phase $phase -Args @("snapshot", "--json", "--resource", $resource, "--snapshot-json", $snapshotOn, "--log-scpi") -LiveHardwareExpected:$true -GeneratedArtifacts @($snapshotOn)))
        $cases.Add((New-CommandCase -Name "restore-on-safe-off-before-restore" -Suite "snapshot" -Phase $phase -Args (@("safe-off") + $commonAll) -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-on-mutate-ch1" -Suite "snapshot" -Phase $phase -Args @("set", "--json", "--resource", $resource, "--channel", "1", "--voltage", "0.5", "--current", "0.04", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "restore-on-execute" -Suite "snapshot" -Phase $phase -Args @("restore-from-snapshot", "--json", "--resource", $resource, "--snapshot", $snapshotOn, "--channel", "all", "--restore-output-state", "--confirm", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true -ValidationKind "restore" -ExpectedChannels @(1,2,3) -CandidateScopeRequired:(Test-CurrentConnectionSupportsCandidates -Command "restore-from-snapshot")))
        $cases.Add((New-CommandCase -Name "restore-on-readback" -Suite "snapshot" -Phase $phase -Args @("readback", "--json", "--resource", $resource, "--channel", "all", "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "snapshot-readback" -ExpectedChannels @(1,2,3) -CompareSnapshotPaths @($snapshotOn)))
        $cases.Add((New-CommandCase -Name "restore-on-assert" -Suite "snapshot" -Phase $phase -Args @("output-state", "--json", "--resource", $resource, "--channel", "all", "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "output-state-one-on" -ExpectedChannels @(1,2,3)))
        $cases.Add((New-CommandCase -Name "restore-on-immediate-safe-off" -Suite "snapshot" -Phase $phase -Args (@("safe-off") + $commonAll) -StateChanging:$true -LiveHardwareExpected:$true -CleanupRole "restore_on_immediate_safe_off"))
        $cases.Add((New-CommandCase -Name "restore-on-final-output-state" -Suite "snapshot" -Phase $phase -Args @("output-state", "--json", "--resource", $resource, "--channel", "all", "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "output-state" -ExpectedChannels @(1,2,3) -ExpectedOutputEnabled $false))
        $cases.Add((New-CommandCase -Name "restore-error-queue" -Suite "snapshot" -Phase $phase -Args @("error", "--json", "--resource", $resource, "--max-reads", "20", "--log-scpi") -LiveHardwareExpected:$true -ValidationKind "empty-errors"))
    }
    return $cases.ToArray()
}

function Get-TriggerListCases {
    param([bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $TargetMetadata["keysight-e36312a"].simulator_resource }
    $phase = if ($Live) { "live" } else { "preflight" }
    $modeFlag = if ($Live) { @() } else { @("--simulate") }
    $stepFlag = if ($Live) { @() } else { @("--dry-run") }
    $fireValidationKind = if ($Live) { "trigger-fire" } else { "" }
    return @(
        (New-CommandCase -Name "trigger-status" -Suite "trigger-list" -Phase $phase -Args (@("trigger-status") + $modeFlag + @("--json", "--resource", $resource, "--channel", "1", "--log-scpi")) -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "trigger-step-bus" -Suite "trigger-list" -Phase $phase -Args (@("trigger-step") + $stepFlag + @("--json", "--resource", $resource, "--channel", "1", "--source", "bus", "--fire", "--wait-complete", "--log-scpi")) -StateChanging:$Live -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "trigger-list-bus" -Suite "trigger-list" -Phase $phase -Args (@("trigger-list") + $modeFlag + @("--json", "--resource", $resource, "--channel", "1", "--voltage-list", "0,0.5,1", "--current-list", "0.05,0.05,0.05", "--dwell-list", "0.01,0.01,0.01", "--source", "bus", "--fire", "--wait-complete", "--log-scpi")) -StateChanging:$Live -LiveHardwareExpected:$Live),
        (New-CommandCase -Name "trigger-fire-candidate" -Suite "trigger-list" -Phase $phase -Args (@("trigger-fire") + $stepFlag + @("--json", "--resource", $resource, "--channel", "1", "--wait-complete", "--wait-timeout-ms", "10000", "--poll-ms", "200", "--log-scpi")) -StateChanging:$Live -LiveHardwareExpected:$Live -ValidationKind $fireValidationKind -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "trigger-fire"))),
        (New-CommandCase -Name "trigger-pulse-candidate" -Suite "trigger-list" -Phase $phase -Args (@("trigger-pulse") + $stepFlag + @("--json", "--resource", $resource, "--pin", "1", "--channel", "1", "--polarity", "positive", "--log-scpi")) -StateChanging:$Live -LiveHardwareExpected:$Live -CandidateScopeRequired:($Live -and (Test-CurrentConnectionSupportsCandidates -Command "trigger-pulse")) -OperatorInteractionRequired:$Live),
        (New-CommandCase -Name "trigger-abort" -Suite "trigger-list" -Phase $phase -Args (@("trigger-abort") + $modeFlag + @("--json", "--resource", $resource, "--channel", "1", "--log-scpi")) -StateChanging:$Live -LiveHardwareExpected:$Live)
    )
}

function Get-SoftwareSequenceCases {
    param([string]$Model, [bool]$Live)

    $resource = if ($Live) { $script:RawResource } else { $TargetMetadata[$Model].simulator_resource }
    $phase = if ($Live) { "live" } else { "preflight" }
    $readOnlySequence = New-ValidationSequenceFile -Name "sequence-readonly" -Lines @(
        "version: 1",
        "steps:",
        "  - action: readback",
        "    channel: 1",
        "  - action: output-state",
        "    channel: 1"
    )
    $outputSequence = New-ValidationSequenceFile -Name "sequence-output-low-power" -Lines @(
        "version: 1",
        "steps:",
        "  - action: set",
        "    channel: 1",
        "    voltage: 1",
        "    current: 0.05",
        "  - action: output-on",
        "    channel: 1",
        "  - action: wait",
        "    seconds: 0.1",
        "  - action: output-off",
        "    channel: 1"
    )
    $rampListArgs = @("--segment", "1", "0.05", "0", "1", "0.25", "100", "0")
    $cases = New-Object System.Collections.Generic.List[object]
    if ($Live) {
        $safeOffArgs = @("safe-off", "--json", "--resource", $resource, "--channel", "all", "--log-scpi")
        $cases.Add((New-CommandCase -Name "safe-off-before-software-sequence" -Suite "software-sequence" -Phase $phase -Args $safeOffArgs -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "ramp-list-live-low-power" -Suite "software-sequence" -Phase $phase -Args (@("ramp-list", "--json", "--resource", $resource) + $rampListArgs + @("--log-scpi")) -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "sequence-live-readonly" -Suite "software-sequence" -Phase $phase -Args @("sequence", "--json", "--resource", $resource, "--file", $readOnlySequence, "--log-scpi") -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "sequence-live-output-low-power" -Suite "software-sequence" -Phase $phase -Args @("sequence", "--json", "--resource", $resource, "--file", $outputSequence, "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true))
        $cases.Add((New-CommandCase -Name "safe-off-after-software-sequence" -Suite "software-sequence" -Phase $phase -Args $safeOffArgs -StateChanging:$true -LiveHardwareExpected:$true))
    }
    else {
        $cases.Add((New-CommandCase -Name "ramp-list-lint" -Suite "software-sequence" -Phase $phase -Args (@("ramp-list", "--lint", "--json", "--model", $Model) + $rampListArgs)))
        $cases.Add((New-CommandCase -Name "ramp-list-dry-run" -Suite "software-sequence" -Phase $phase -Args (@("ramp-list", "--dry-run", "--json", "--model", $Model) + $rampListArgs)))
        $cases.Add((New-CommandCase -Name "sequence-lint-readonly" -Suite "software-sequence" -Phase $phase -Args @("sequence", "--lint", "--json", "--model", $Model, "--resource", $resource, "--file", $readOnlySequence)))
        $cases.Add((New-CommandCase -Name "sequence-dry-run-readonly" -Suite "software-sequence" -Phase $phase -Args @("sequence", "--dry-run", "--json", "--model", $Model, "--resource", $resource, "--file", $readOnlySequence)))
        if ($Model -in @("keysight-edu36311a", "keysight-e3646a")) {
            $negativeCases = @(
                @{ Name = "sequence-unsupported-trigger"; Action = "trigger-list"; Expected = "trigger-list" },
                @{ Name = "sequence-unsupported-snapshot"; Action = "snapshot"; Expected = "snapshot" },
                @{ Name = "sequence-unsupported-restore"; Action = "restore-from-snapshot"; Expected = "restore" },
                @{ Name = "sequence-unsupported-native-list"; Action = "native-list"; Expected = "native-list" }
            )
            if ($Model -eq "keysight-e3646a") {
                $negativeCases += @(
                    @{ Name = "sequence-unsupported-protection"; Action = "protection-set"; Expected = "protection" },
                    @{ Name = "sequence-unsupported-completion-pulse"; Action = "trigger-pulse"; Expected = "trigger-pulse" }
                )
            }
            foreach ($negative in $negativeCases) {
                $badSequence = New-ValidationSequenceFile -Name $negative.Name -Lines @(
                    "version: 1",
                    "steps:",
                    ("  - action: " + $negative.Action),
                    "    channel: 1"
                )
                $cases.Add((New-CommandCase -Name ($negative.Name + "-dry-run") -Suite "software-sequence" -Phase $phase -Args @("sequence", "--dry-run", "--json", "--model", $Model, "--resource", $resource, "--file", $badSequence) -ExpectedSuccess:$false -ExpectedErrorContains $negative.Expected))
                $cases.Add((New-CommandCase -Name ($negative.Name + "-simulate") -Suite "software-sequence" -Phase $phase -Args @("sequence", "--simulate", "--json", "--model", $Model, "--resource", $resource, "--file", $badSequence) -ExpectedSuccess:$false -ExpectedErrorContains $negative.Expected))
            }
        }
    }
    return $cases.ToArray()
}

function Get-SuiteCases {
    param(
        [string]$Model,
        [string[]]$Suites,
        [bool]$Live
    )

    $cases = New-Object System.Collections.Generic.List[object]
    foreach ($suiteName in $Suites) {
        if ($suiteName -eq "readonly") {
            $cases.AddRange((Get-ReadOnlyCases -Model $Model -Live:$Live))
        }
        elseif ($suiteName -eq "safe-state") {
            $cases.AddRange((Get-SafeStateCases -Model $Model -Live:$Live))
        }
        elseif ($suiteName -eq "output") {
            $cases.AddRange((Get-OutputCases -Model $Model -Live:$Live))
        }
        elseif ($suiteName -eq "protection") {
            $cases.AddRange((Get-ProtectionCases -Model $Model -Live:$Live))
        }
        elseif ($suiteName -eq "snapshot") {
            $cases.AddRange((Get-SnapshotCases -Model $Model -Live:$Live))
        }
        elseif ($suiteName -eq "trigger-list") {
            $cases.AddRange((Get-TriggerListCases -Live:$Live))
        }
        elseif ($suiteName -eq "software-sequence") {
            $cases.AddRange((Get-SoftwareSequenceCases -Model $Model -Live:$Live))
        }
    }
    return $cases.ToArray()
}

function Assert-CandidateScopeInventory {
    param(
        [Parameter(Mandatory = $true)][string]$Model,
        [Parameter(Mandatory = $true)][object[]]$LiveCases,
        [bool]$RequireComplete = $false
    )

    if ($null -eq $script:CandidateInventory) {
        throw "Core candidate inventory is unavailable."
    }
    $modelProperty = $script:CandidateInventory.PSObject.Properties[$Model]
    if ($null -eq $modelProperty) {
        $expectedCommands = @()
        $candidateConnectionSelected = $false
    }
    else {
        $expectedCommands = @($modelProperty.Value.commands)
        $connectionMatches = @($modelProperty.Value.connections | Where-Object {
            $_.Count -eq 2 -and $_[0] -eq $script:TransportScope -and $_[1] -eq $script:BackendArtifact.backend_scope
        })
        $candidateConnectionSelected = $connectionMatches.Count -eq 1
    }
    foreach ($case in @($LiveCases)) {
        $command = if ($case.args.Count -gt 0) { [string]$case.args[0] } else { "" }
        $isCandidateCommand = ($candidateConnectionSelected -and $case.phase -eq "live" -and [bool]$case.live_hardware_expected -and $command -in $expectedCommands)
        if ($isCandidateCommand -and -not [bool]$case.candidate_scope_required) {
            throw "Live candidate command '$command' in case '$($case.name)' is missing candidate scope marking."
        }
        if ([bool]$case.candidate_scope_required -and -not $isCandidateCommand) {
            throw "Noncandidate live case '$($case.name)' is marked candidate-scope-required."
        }
    }
    $seenCandidateCommands = @($LiveCases | Where-Object {
        if ($_.phase -ne "live" -or -not [bool]$_.live_hardware_expected) { return $false }
        $command = if ($_.args.Count -gt 0) { [string]$_.args[0] } else { "" }
        $command -in $expectedCommands
    } | ForEach-Object { [string]$_.args[0] } | Sort-Object -Unique)
    $missingCommands = @($expectedCommands | Where-Object { $_ -notin $seenCandidateCommands })
    if ($RequireComplete -and $candidateConnectionSelected -and $missingCommands.Count -gt 0) {
        throw "Live candidate inventory is missing command uses: $($missingCommands -join ', ')."
    }
}

function Get-CaseAssertionFailures {
    param(
        [Parameter(Mandatory = $true)]$Case,
        [AllowNull()]$Payload,
        [AllowNull()]$Identity,
        [AllowNull()]$OutputStates,
        [AllowNull()]$InstrumentErrors,
        [Parameter(Mandatory = $true)][string]$StderrPath
    )

    $failures = New-Object System.Collections.Generic.List[string]
    $kind = [string]$Case.validation_kind
    if ([string]::IsNullOrWhiteSpace($kind) -or $null -eq $Payload) {
        return $failures.ToArray()
    }
    $data = Get-PropertyValue -Object $Payload -Name "data"
    if ($kind -in @("output-state", "output-state-one-on")) {
        $states = @($OutputStates)
        if ($states.Count -eq 0 -and $Case.expected_channels.Count -eq 1) {
            $states = @([pscustomobject]@{
                channel = $Case.expected_channels[0]
                enabled = Get-PropertyValue -Object $data -Name "output_enabled"
            })
        }
        foreach ($channel in $Case.expected_channels) {
            $matches = @($states | Where-Object { (Get-PropertyValue -Object $_ -Name "channel") -eq $channel })
            if ($matches.Count -ne 1) {
                $failures.Add("$($Case.name) expected exactly one output-state record for channel $channel.")
                continue
            }
            $enabled = Get-PropertyValue -Object $matches[0] -Name "enabled"
            if ($kind -eq "output-state-one-on") {
                $expected = ($channel -eq 1)
            }
            else {
                $expected = $Case.expected_output_enabled
            }
            if ($enabled -isnot [System.Boolean] -or $enabled -ne $expected) {
                $failures.Add("$($Case.name) expected channel $channel output enabled=$expected.")
            }
        }
        if ($states.Count -ne $Case.expected_channels.Count) {
            $failures.Add("$($Case.name) returned an unexpected output-state channel count.")
        }
    }
    elseif ($kind -eq "measure-all") {
        $records = @((Get-PropertyValue -Object $data -Name "channels"))
        foreach ($channel in $Case.expected_channels) {
            $matches = @($records | Where-Object { (Get-PropertyValue -Object $_ -Name "channel") -eq $channel })
            if ($matches.Count -ne 1) {
                $failures.Add("$($Case.name) expected exactly one measurement record for channel $channel.")
                continue
            }
            $measurements = Get-PropertyValue -Object $matches[0] -Name "measurements"
            foreach ($field in @("voltage", "current")) {
                $value = Get-PropertyValue -Object $measurements -Name $field
                $parsed = 0.0
                if ($null -eq $value -or -not [double]::TryParse([string]$value, [ref]$parsed)) {
                    $failures.Add("$($Case.name) channel $channel has a nonnumeric measured $field value.")
                }
            }
        }
        if ($records.Count -ne $Case.expected_channels.Count) {
            $failures.Add("$($Case.name) returned an unexpected measurement channel count.")
        }
        $scpiText = if (Test-Path -LiteralPath $StderrPath) { Get-Content -LiteralPath $StderrPath -Raw } else { "" }
        if ($scpiText -match '(?im)>>.*(?:OUTP\s+(?:ON|OFF)|VOLT\s|CURR\s|\*CLS|\*TRG|INIT|ABOR)') {
            $failures.Add("$($Case.name) emitted state-changing SCPI.")
        }
    }
    elseif ($kind -eq "doctor") {
        $manager = Get-PropertyValue -Object $data -Name "real_resource_manager"
        $resource = Get-PropertyValue -Object $data -Name "resource"
        if ((Get-PropertyValue -Object $manager -Name "checked") -ne $true -or (Get-PropertyValue -Object $manager -Name "available") -ne $true) {
            $failures.Add("$($Case.name) did not complete the real resource-manager check.")
        }
        if ((Get-PropertyValue -Object $resource -Name "reachable") -ne $true -or $null -eq (Get-PropertyValue -Object $resource -Name "idn")) {
            $failures.Add("$($Case.name) did not open and identify the requested resource.")
        }
        $pyvisa = Get-PropertyValue -Object $data -Name "pyvisa"
        $reportedBackend = [string](Get-PropertyValue -Object $pyvisa -Name "backend")
        $expectedBackend = [string]$script:BackendValue
        if ($reportedBackend -ne $expectedBackend) {
            $failures.Add("$($Case.name) reported an unexpected selected backend.")
        }
        $scpiText = if (Test-Path -LiteralPath $StderrPath) { Get-Content -LiteralPath $StderrPath -Raw } else { "" }
        if ($scpiText -match '(?im)>>.*(?:OUTP\s+(?:ON|OFF)|VOLT\s|CURR\s|\*CLS|\*TRG|INIT|ABOR)') {
            $failures.Add("$($Case.name) emitted state-changing SCPI.")
        }
    }
    elseif ($kind -eq "doctor-offline") {
        $manager = Get-PropertyValue -Object $data -Name "real_resource_manager"
        if ((Get-PropertyValue -Object $manager -Name "checked") -ne $false) {
            $failures.Add("$($Case.name) unexpectedly checked a real resource manager.")
        }
    }
    elseif ($kind -eq "empty-errors") {
        if ($null -eq $InstrumentErrors -or @($InstrumentErrors).Count -ne 0) {
            $failures.Add("$($Case.name) did not confirm an empty instrument error queue.")
        }
    }
    elseif ($kind -eq "trigger-fire") {
        $trigger = Get-PropertyValue -Object $data -Name "trigger"
        $mode = Get-PropertyValue -Object $trigger -Name "mode"
        $channel = Get-PropertyValue -Object $trigger -Name "channel"
        $fired = Get-PropertyValue -Object $trigger -Name "fired"
        $completed = Get-PropertyValue -Object $trigger -Name "completed"
        $channelIsNumber = $channel -is [byte] -or $channel -is [sbyte] -or
            $channel -is [int16] -or $channel -is [uint16] -or
            $channel -is [int32] -or $channel -is [uint32] -or
            $channel -is [int64] -or $channel -is [uint64] -or
            $channel -is [single] -or $channel -is [double] -or $channel -is [decimal]
        if ($mode -isnot [string] -or $mode -cne "fire") {
            $failures.Add("$($Case.name) did not report trigger mode=fire.")
        }
        if (-not $channelIsNumber -or $channel -ne 1) {
            $failures.Add("$($Case.name) did not report numeric trigger channel=1.")
        }
        if ($fired -isnot [bool] -or $fired -ne $true) {
            $failures.Add("$($Case.name) did not report trigger fired=true as a JSON boolean.")
        }
        if ($completed -isnot [bool] -or $completed -ne $true) {
            $failures.Add("$($Case.name) did not report trigger completed=true as a JSON boolean.")
        }
    }
    elseif ($kind -eq "restore") {
        $restored = @((Get-PropertyValue -Object $data -Name "restored_channels"))
        if (($restored -join ',') -ne ($Case.expected_channels -join ',')) {
            $failures.Add("$($Case.name) did not restore exactly the selected channels.")
        }
    }
    elseif ($kind -eq "snapshot-compare") {
        try {
            $left = Get-Content -LiteralPath $Case.compare_snapshot_paths[0] -Raw | ConvertFrom-Json
            $right = Get-Content -LiteralPath $Case.compare_snapshot_paths[1] -Raw | ConvertFrom-Json
            foreach ($section in @("readback", "protection_settings")) {
                $leftValue = (Get-PropertyValue -Object $left -Name $section) | ConvertTo-Json -Depth 20 -Compress
                $rightValue = (Get-PropertyValue -Object $right -Name $section) | ConvertTo-Json -Depth 20 -Compress
                if ($leftValue -cne $rightValue) {
                    $failures.Add("$($Case.name) restorable $section differs after restore.")
                }
            }
        }
        catch {
            $failures.Add("$($Case.name) could not compare canonical snapshot artifacts.")
        }
    }
    elseif ($kind -eq "snapshot-mutation") {
        try {
            $left = Get-Content -LiteralPath $Case.compare_snapshot_paths[0] -Raw | ConvertFrom-Json
            $right = Get-Content -LiteralPath $Case.compare_snapshot_paths[1] -Raw | ConvertFrom-Json
            foreach ($channel in @(1,2,3)) {
                $leftReadback = @($left.readback | Where-Object { $_.channel -eq $channel })
                $rightReadback = @($right.readback | Where-Object { $_.channel -eq $channel })
                $leftProtection = @($left.protection_settings | Where-Object { $_.channel -eq $channel })
                $rightProtection = @($right.protection_settings | Where-Object { $_.channel -eq $channel })
                if ($leftReadback.Count -ne 1 -or $rightReadback.Count -ne 1 -or
                    $leftReadback[0].setpoints.voltage -eq $rightReadback[0].setpoints.voltage -or
                    $leftReadback[0].setpoints.current -eq $rightReadback[0].setpoints.current) {
                    $failures.Add("$($Case.name) did not prove changed setpoints for channel $channel.")
                }
                if ($leftProtection.Count -ne 1 -or $rightProtection.Count -ne 1 -or
                    $leftProtection[0].protection.ovp_voltage -eq $rightProtection[0].protection.ovp_voltage -or
                    $leftProtection[0].protection.ocp_enabled -eq $rightProtection[0].protection.ocp_enabled) {
                    $failures.Add("$($Case.name) did not prove changed OVP and OCP state for channel $channel.")
                }
            }
        }
        catch {
            $failures.Add("$($Case.name) could not prove the pre-restore snapshot mutation.")
        }
    }
    elseif ($kind -eq "snapshot-readback") {
        try {
            $snapshot = Get-Content -LiteralPath $Case.compare_snapshot_paths[0] -Raw | ConvertFrom-Json
            $expected = @($snapshot.readback)
            $actual = @((Get-PropertyValue -Object $data -Name "channels"))
            if ($expected.Count -ne $Case.expected_channels.Count -or $actual.Count -ne $Case.expected_channels.Count) {
                $failures.Add("$($Case.name) snapshot/readback channel inventory differs.")
            }
            foreach ($channel in $Case.expected_channels) {
                $expectedRecord = @($expected | Where-Object { $_.channel -eq $channel })
                $actualRecord = @($actual | Where-Object { $_.channel -eq $channel })
                if ($expectedRecord.Count -ne 1 -or $actualRecord.Count -ne 1) {
                    $failures.Add("$($Case.name) expected exactly one snapshot and live record for channel $channel.")
                    continue
                }
                foreach ($field in @("voltage", "current")) {
                    $expectedValue = 0.0
                    $actualValue = 0.0
                    if (-not [double]::TryParse([string]$expectedRecord[0].setpoints.$field, [ref]$expectedValue) -or
                        -not [double]::TryParse([string]$actualRecord[0].setpoints.$field, [ref]$actualValue)) {
                        $failures.Add("$($Case.name) channel $channel has a nonnumeric $field setpoint.")
                        continue
                    }
                    $tolerance = if ($field -eq "voltage") { 0.001 } else { 0.001 }
                    if ([math]::Abs($expectedValue - $actualValue) -gt $tolerance -or $actualValue -lt 0 -or
                        ($field -eq "voltage" -and $actualValue -gt 1.0) -or
                        ($field -eq "current" -and $actualValue -gt 0.05)) {
                        $failures.Add("$($Case.name) channel $channel restored $field is outside the snapshot tolerance or safe bound.")
                    }
                }
            }
        }
        catch {
            $failures.Add("$($Case.name) could not compare the restored live readback with its snapshot.")
        }
    }
    elseif ($kind -eq "log") {
        $csvPath = $Case.generated_artifacts[0]
        $jsonlPath = $Case.generated_artifacts[1]
        if (-not (Test-Path -LiteralPath $csvPath) -or -not (Test-Path -LiteralPath $jsonlPath)) {
            $failures.Add("$($Case.name) did not create both CSV and JSONL artifacts.")
        }
        else {
            try {
                $rows = @(Import-Csv -LiteralPath $csvPath)
                $expectedHeader = @("timestamp","resource","resource_alias","model","serial","channel","programmed_voltage","programmed_current","measured_voltage","measured_current","output_enabled","errors")
                $actualHeader = if ($rows.Count -gt 0) { @($rows[0].PSObject.Properties.Name) } else { @() }
                if (($actualHeader -join ',') -cne ($expectedHeader -join ',')) { $failures.Add("$($Case.name) CSV header does not match the logging contract.") }
                if ($rows.Count -ne $Case.expected_channels.Count) { $failures.Add("$($Case.name) CSV row count does not match the target channel count.") }
                foreach ($channel in $Case.expected_channels) {
                    $matches = @($rows | Where-Object { $_.channel -eq [string]$channel })
                    if ($matches.Count -ne 1) { $failures.Add("$($Case.name) expected one CSV sample for channel $channel."); continue }
                    $row = $matches[0]
                    foreach ($field in @("programmed_voltage","programmed_current","measured_voltage","measured_current","output_enabled")) {
                        if ([string]::IsNullOrWhiteSpace([string]$row.$field)) { $failures.Add("$($Case.name) CSV field $field is missing for channel $channel.") }
                    }
                    if (-not [string]::IsNullOrEmpty([string]$row.errors)) { $failures.Add("$($Case.name) CSV contains instrument errors for channel $channel.") }
                }
                $events = @(Get-Content -LiteralPath $jsonlPath | ForEach-Object { $_ | ConvertFrom-Json })
                $samples = @($events | Where-Object { $_.event -eq "sample" })
                $summaries = @($events | Where-Object { $_.event -eq "summary" })
                if ($samples.Count -ne $Case.expected_channels.Count -or $summaries.Count -ne 1) { $failures.Add("$($Case.name) JSONL sample/summary event count is invalid.") }
                elseif ($summaries[0].samples_written -ne 1 -or $summaries[0].stopped -ne $false -or $summaries[0].stop_reason -ne "completed") { $failures.Add("$($Case.name) JSONL summary is not a completed one-sample run.") }
                foreach ($channel in $Case.expected_channels) {
                    $jsonlMatches = @($samples | Where-Object { (Get-PropertyValue -Object $_.sample -Name "channel") -eq $channel })
                    if ($jsonlMatches.Count -ne 1) { $failures.Add("$($Case.name) expected one JSONL sample for channel $channel.") }
                }
            }
            catch {
                $failures.Add("$($Case.name) could not parse its CSV/JSONL artifacts.")
            }
        }
        if ((Get-PropertyValue -Object $data -Name "samples_written") -ne 1 -or (Get-PropertyValue -Object $data -Name "stopped") -ne $false) {
            $failures.Add("$($Case.name) command result is not a completed one-sample run.")
        }
    }
    return $failures.ToArray()
}

function Get-FileSha256 {
    [OutputType([string])]
    param([Parameter(Mandatory = $true)][string]$LiteralPath)

    $sha256 = $null
    $fileStream = $null
    try {
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        $fileStream = [System.IO.File]::OpenRead($LiteralPath)
        $hashBytes = $sha256.ComputeHash($fileStream)
        return [System.BitConverter]::ToString($hashBytes).Replace("-", "")
    }
    finally {
        if ($null -ne $fileStream) { $fileStream.Dispose() }
        if ($null -ne $sha256) { $sha256.Dispose() }
    }
}

function Get-GeneratedArtifactFingerprints {
    param([string[]]$Paths = @())

    $fingerprints = New-Object System.Collections.Generic.List[object]
    foreach ($path in @($Paths)) {
        if (-not (Test-Path -LiteralPath $path)) {
            $fingerprints.Add([pscustomobject]@{
                path = [System.IO.Path]::GetFullPath($path)
                exists = $false
                kind = $null
                length = $null
                last_write_utc_ticks = $null
                sha256 = $null
            })
            continue
        }
        $item = Get-Item -LiteralPath $path
        $isFile = -not $item.PSIsContainer
        $fingerprints.Add([pscustomobject]@{
            path = $item.FullName
            exists = $true
            kind = if ($isFile) { "file" } else { "directory" }
            length = if ($isFile) { $item.Length } else { $null }
            last_write_utc_ticks = $item.LastWriteTimeUtc.Ticks
            sha256 = if ($isFile) { Get-FileSha256 -LiteralPath $item.FullName } else { $null }
        })
    }
    return ,($fingerprints.ToArray())
}

function Test-GeneratedArtifactsChanged {
    param(
        [AllowEmptyCollection()][object[]]$Before,
        [AllowEmptyCollection()][object[]]$After
    )

    $beforeJson = @($Before) | ConvertTo-Json -Depth 6 -Compress
    $afterJson = @($After) | ConvertTo-Json -Depth 6 -Compress
    return $beforeJson -cne $afterJson
}

function Invoke-ValidationCommandAttempt {
    param(
        [Parameter(Mandatory = $true)]$Case,
        [Parameter(Mandatory = $true)][int]$AttemptNumber
    )

    Ensure-ArtifactDirectories
    $attemptArtifactBaseName = Get-CaseAttemptArtifactBaseName -Case $Case -AttemptNumber $AttemptNumber
    $jsonPath = Join-Path $script:PrivateArtifactDir ($attemptArtifactBaseName + ".json")
    $stdoutPath = Join-Path $script:PrivateArtifactDir ($attemptArtifactBaseName + ".stdout.txt")
    $stderrPath = Join-Path $script:PrivateArtifactDir ($attemptArtifactBaseName + ".stderr-scpi.txt")
    $shareableJsonPath = Join-Path $script:ShareableArtifactDir ($attemptArtifactBaseName + ".json")
    $shareableStdoutPath = Join-Path $script:ShareableArtifactDir ($attemptArtifactBaseName + ".stdout.txt")
    $shareableStderrPath = Join-Path $script:ShareableArtifactDir ($attemptArtifactBaseName + ".stderr-scpi.txt")
    $allArgs = @(Get-ValidationCommandArguments -Case $Case -JsonPath $jsonPath)
    if (Test-Path -LiteralPath $jsonPath) {
        Remove-Item -LiteralPath $jsonPath -Force
    }
    $generatedBefore = @(Get-GeneratedArtifactFingerprints -Paths @($Case.generated_artifacts))
    $settleBeforeMs = Invoke-LiveTcpipSubprocessSettle -Phase $Case.phase

    $oldErrorActionPreference = $ErrorActionPreference
    $nativePreferenceVariable = Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $hadNativePreference = $null -ne $nativePreferenceVariable
    $oldNativePreference = $null
    $hadPythonPath = $null -ne [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $oldPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    try {
        $ErrorActionPreference = "Continue"
        if ($hadNativePreference) {
            $oldNativePreference = [bool]$nativePreferenceVariable.Value
            $PSNativeCommandUseErrorActionPreference = $false
        }
        [Environment]::SetEnvironmentVariable("PYTHONPATH", (Get-ValidationChildPythonPath), "Process")
        & $CliExecutable @CliPrefix @allArgs 1> $stdoutPath 2> $stderrPath
        $exitCode = $LASTEXITCODE
    }
    finally {
        if ($hadPythonPath) {
            [Environment]::SetEnvironmentVariable("PYTHONPATH", $oldPythonPath, "Process")
        }
        else {
            [Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process")
        }
        $ErrorActionPreference = $oldErrorActionPreference
        if ($hadNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $oldNativePreference
        }
    }

    $generatedAfter = @(Get-GeneratedArtifactFingerprints -Paths @($Case.generated_artifacts))
    $generatedArtifactsChanged = Test-GeneratedArtifactsChanged -Before $generatedBefore -After $generatedAfter
    $payload = $null
    $parseError = $null
    $parseStatus = "parsed"
    if (Test-Path -LiteralPath $jsonPath) {
        try {
            $payload = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json
        }
        catch {
            $parseStatus = "failed"
            $parseError = "Could not parse command JSON."
        }
    }
    else {
        $parseStatus = "missing"
        $parseError = "JSON output file was not created."
    }

    Write-ShareableJsonArtifact -PrivatePath $jsonPath -ShareablePath $shareableJsonPath -Payload $payload -ParseStatus $parseStatus
    Write-ShareableTextArtifact -PrivatePath $stdoutPath -ShareablePath $shareableStdoutPath
    Write-ShareableTextArtifact -PrivatePath $stderrPath -ShareablePath $shareableStderrPath
    $scpiTranscriptEmpty = (Test-Path -LiteralPath $stderrPath) -and (Get-Item -LiteralPath $stderrPath).Length -eq 0

    return [pscustomobject]@{
        attempt_number = $AttemptNumber
        settle_before_ms = $settleBeforeMs
        exit_code = $exitCode
        payload = $payload
        parse_error = $parseError
        parse_status = $parseStatus
        scpi_transcript_empty = $scpiTranscriptEmpty
        generated_artifacts_changed = $generatedArtifactsChanged
        arguments = $allArgs
        private_json_path = $jsonPath
        private_stdout_path = $stdoutPath
        private_stderr_path = $stderrPath
        shareable_json_path = $shareableJsonPath
        shareable_stdout_path = $shareableStdoutPath
        shareable_stderr_path = $shareableStderrPath
    }
}

function Test-PreIoOpenFailureRecoveryEligible {
    param(
        [Parameter(Mandatory = $true)]$Case,
        [Parameter(Mandatory = $true)]$Attempt
    )

    if (-not (Test-LiveTcpipPhase -Phase $Case.phase)) { return $false }
    if ($Case.expected_success -isnot [System.Boolean] -or $Case.expected_success -ne $true) { return $false }
    if ($Attempt.exit_code -eq 0 -or $null -ne $Attempt.parse_error) { return $false }
    if ($Attempt.scpi_transcript_empty -ne $true -or $Attempt.generated_artifacts_changed -eq $true) { return $false }
    $payload = $Attempt.payload
    if ($payload -isnot [pscustomobject]) { return $false }
    $schemaProperty = $payload.PSObject.Properties["schema_version"]
    $okProperty = $payload.PSObject.Properties["ok"]
    $statusProperty = $payload.PSObject.Properties["status"]
    $commandProperty = $payload.PSObject.Properties["command"]
    $dataProperty = $payload.PSObject.Properties["data"]
    $errorProperty = $payload.PSObject.Properties["error"]
    if ($null -eq $schemaProperty -or $schemaProperty.Value -isnot [int] -or $schemaProperty.Value -ne 2) { return $false }
    if ($null -eq $okProperty -or $okProperty.Value -isnot [System.Boolean] -or $okProperty.Value -ne $false) { return $false }
    if ($null -eq $statusProperty -or $statusProperty.Value -isnot [string] -or $statusProperty.Value -cne "error") { return $false }
    if ($null -eq $dataProperty -or -not [object]::ReferenceEquals($null, $dataProperty.Value)) { return $false }
    $resultProperty = $payload.PSObject.Properties["result"]
    if ($null -ne $resultProperty -and -not [object]::ReferenceEquals($null, $resultProperty.Value)) { return $false }
    if ($null -eq $commandProperty -or $commandProperty.Value -isnot [pscustomobject]) { return $false }
    $commandNameProperty = $commandProperty.Value.PSObject.Properties["name"]
    if ($null -eq $commandNameProperty -or $commandNameProperty.Value -isnot [string] -or $commandNameProperty.Value -cne [string]$Case.args[0]) { return $false }
    if ($null -eq $errorProperty -or $errorProperty.Value -isnot [pscustomobject]) { return $false }
    $errorTypeProperty = $errorProperty.Value.PSObject.Properties["type"]
    $errorCodeProperty = $errorProperty.Value.PSObject.Properties["code"]
    $errorMessageProperty = $errorProperty.Value.PSObject.Properties["message"]
    $retryableProperty = $errorProperty.Value.PSObject.Properties["retryable"]
    if ($null -eq $errorTypeProperty -or $errorTypeProperty.Value -isnot [string] -or $errorTypeProperty.Value -cne "connection") { return $false }
    if ($null -eq $errorCodeProperty -or $errorCodeProperty.Value -isnot [string] -or [string]::IsNullOrWhiteSpace($errorCodeProperty.Value)) { return $false }
    if ($null -eq $errorMessageProperty -or $errorMessageProperty.Value -isnot [string] -or -not $errorMessageProperty.Value.Contains("Could not open VISA resource")) { return $false }
    if ($null -eq $retryableProperty -or $retryableProperty.Value -isnot [System.Boolean] -or $retryableProperty.Value -ne $true) { return $false }
    return $true
}

function Invoke-ValidationCommand {
    param([Parameter(Mandatory = $true)]$Case)

    Ensure-ArtifactDirectories
    $artifactBaseName = Get-CaseArtifactBaseName -Case $Case
    $attemptResults = New-Object System.Collections.Generic.List[object]
    $firstAttempt = Invoke-ValidationCommandAttempt -Case $Case -AttemptNumber 1
    $attemptResults.Add($firstAttempt)
    $recoveryAttempted = Test-PreIoOpenFailureRecoveryEligible -Case $Case -Attempt $firstAttempt
    if ($recoveryAttempted) {
        $attemptResults.Add((Invoke-ValidationCommandAttempt -Case $Case -AttemptNumber 2))
    }
    $finalAttempt = $attemptResults[$attemptResults.Count - 1]
    $payload = $finalAttempt.payload
    $parseError = $finalAttempt.parse_error
    $parseStatus = $finalAttempt.parse_status
    $exitCode = $finalAttempt.exit_code
    $allArgs = @($finalAttempt.arguments)
    $jsonPath = $finalAttempt.private_json_path
    $stdoutPath = $finalAttempt.private_stdout_path
    $stderrPath = $finalAttempt.private_stderr_path
    $shareableJsonPath = $finalAttempt.shareable_json_path
    $shareableStdoutPath = $finalAttempt.shareable_stdout_path
    $shareableStderrPath = $finalAttempt.shareable_stderr_path

    $ok = $null
    $hardwareTouched = $null
    $mode = $null
    $dryRun = $null
    $errorCode = $null
    $errorMessage = $null
    if ($null -ne $payload) {
        $ok = [bool]$payload.ok
        $hardwareTouched = [bool]$payload.execution.hardware_touched
        $mode = [string]$payload.execution.mode
        $dryRun = [bool]$payload.execution.dry_run
        if ($null -ne $payload.error) {
            $errorCode = [string]$payload.error.code
            $errorMessage = [string]$payload.error.message
        }
    }
    $finalOkProperty = if ($payload -is [pscustomobject]) { $payload.PSObject.Properties["ok"] } else { $null }
    $finalStatusProperty = if ($payload -is [pscustomobject]) { $payload.PSObject.Properties["status"] } else { $null }
    $recoveredAfterOpenFailure = [bool](
        $recoveryAttempted -and
        $exitCode -eq 0 -and
        $null -ne $finalOkProperty -and
        $finalOkProperty.Value -is [System.Boolean] -and
        $finalOkProperty.Value -eq $true -and
        $null -ne $finalStatusProperty -and
        $finalStatusProperty.Value -is [string] -and
        $finalStatusProperty.Value -ceq "ok"
    )
    $triggerRecord = $null
    if ($null -ne $payload) {
        $payloadData = Get-PropertyValue -Object $payload -Name "data"
        $payloadTrigger = Get-PropertyValue -Object $payloadData -Name "trigger"
        if ($null -ne $payloadTrigger) {
            $triggerRecordFields = [ordered]@{}
            foreach ($triggerField in @("mode", "channel", "fired", "completed", "abort_attempted", "abort_succeeded", "abort_errors")) {
                $triggerProperty = $payloadTrigger.PSObject.Properties[$triggerField]
                if ($null -ne $triggerProperty) {
                    $triggerRecordFields[$triggerField] = $triggerProperty.Value
                }
            }
            $triggerRecord = [pscustomobject]$triggerRecordFields
        }
    }

    $identity = $null
    $identityObserved = $false
    $identityNormalizationFailures = @()
    $outputStates = $null
    $outputStateNormalizationFailures = @()
    $instrumentErrors = $null
    $instrumentErrorNormalizationFailures = @()
    if ($null -ne $payload) {
        $data = Get-PropertyValue -Object $payload -Name "data"
        $commandName = if ($Case.args.Count -gt 0) { [string]$Case.args[0] } else { "" }
        $snapshotIdentityCommand = $commandName -in @("snapshot", "restore-from-snapshot")
        $exactLiveHardwareExpected = $Case.live_hardware_expected -is [System.Boolean] -and $Case.live_hardware_expected -eq $true
        $generalIdentityEvidenceAttempted = $false
        if (-not $snapshotIdentityCommand -and $data -is [pscustomobject]) {
            $dataIdnProperty = $data.PSObject.Properties["idn"]
            $resourceProperty = $data.PSObject.Properties["resource"]
            $resourceIdnProperty = if ($null -ne $resourceProperty -and $resourceProperty.Value -is [pscustomobject]) {
                $resourceProperty.Value.PSObject.Properties["idn"]
            }
            else {
                $null
            }
            $generalIdentityEvidenceAttempted = (
                ($null -ne $dataIdnProperty -and -not [object]::ReferenceEquals($null, $dataIdnProperty.Value)) -or
                ($null -ne $resourceIdnProperty -and -not [object]::ReferenceEquals($null, $resourceIdnProperty.Value))
            )
        }
        $identityRequired = if ($snapshotIdentityCommand) {
            $exactLiveHardwareExpected
        }
        else {
            $Case.phase -eq "live" -and $commandName -ne "readback" -and -not [string]::IsNullOrWhiteSpace([string]$Case.validation_kind) -and $Case.validation_kind -ne "empty-errors"
        }
        $normalizedIdentity = Normalize-ObservedIdentityEvidence -Data $data -Command $commandName -TargetProfile $TargetMetadata[$script:NormalizedTarget]
        if (-not $snapshotIdentityCommand -or $exactLiveHardwareExpected) {
            $identity = $normalizedIdentity.identity
        }
        if ($identityRequired -or ($Case.phase -eq "live" -and $generalIdentityEvidenceAttempted)) {
            $identityNormalizationFailures = @($normalizedIdentity.failures)
        }
        if ($snapshotIdentityCommand) {
            $identityObserved = [bool]($exactLiveHardwareExpected -and $null -ne $identity -and $identityNormalizationFailures.Count -eq 0)
        }
        else {
            $identityObserved = [bool]($Case.phase -eq "live" -and $null -ne $identity -and $normalizedIdentity.failures.Count -eq 0)
        }
        if ($null -ne $data) {
            if ($Case.phase -eq "live" -and $Case.args.Count -gt 0 -and $Case.args[0] -eq "output-state") {
                $normalizedOutputStates = Normalize-OutputStateEvidence -Data $data -ExpectedChannels @($Case.expected_channels)
                $outputStates = @($normalizedOutputStates.records)
                $outputStateNormalizationFailures = @($normalizedOutputStates.failures)
            }
            if ($Case.validation_kind -eq "empty-errors") {
                $normalizedInstrumentErrors = Normalize-InstrumentErrorEvidence -Data $data
                if ($null -ne $normalizedInstrumentErrors.records) {
                    $instrumentErrors = @($normalizedInstrumentErrors.records)
                }
                $instrumentErrorNormalizationFailures = @($normalizedInstrumentErrors.failures)
            }
        }
    }
    if ($null -ne $identity) {
        Add-SensitiveValue -Value ([string](Get-PropertyValue -Object $identity -Name "raw"))
        Add-SerialSensitiveValue -Value ([string](Get-PropertyValue -Object $identity -Name "serial"))
    }
    $casePassed = $true
    $failure = $null
    if ($null -ne $parseError) {
        $casePassed = $false
        $failure = "$($Case.name) did not produce parseable JSON: $parseError"
    }
    elseif ($Case.expected_success) {
        if ($exitCode -ne 0 -or $ok -ne $true) {
            $casePassed = $false
            $failure = "$($Case.name) failed unexpectedly with exit code $exitCode ($errorCode): $errorMessage"
        }
        elseif ($Case.phase -ne "live" -and $hardwareTouched -ne $false) {
            $casePassed = $false
            $failure = "$($Case.name) reported execution.hardware_touched=$hardwareTouched during no-hardware validation."
        }
        elseif ($Case.phase -eq "live" -and -not (Test-LiveExecutionMode -Mode $mode)) {
            $casePassed = $false
            $failure = "$($Case.name) reported execution.mode=$mode during live validation."
        }
        elseif ($Case.phase -eq "live" -and $Case.live_hardware_expected -and $hardwareTouched -ne $true) {
            $casePassed = $false
            $failure = "$($Case.name) reported execution.hardware_touched=$hardwareTouched during live validation."
        }
    }
    else {
        if ($exitCode -eq 0 -or $ok -ne $false) {
            $casePassed = $false
            $failure = "$($Case.name) was expected to fail, but it succeeded."
        }
        elseif (-not [string]::IsNullOrWhiteSpace($Case.expected_error_contains) -and ($errorMessage -notmatch [regex]::Escape($Case.expected_error_contains))) {
            $casePassed = $false
            $failure = "$($Case.name) failed, but not for the expected reason '$($Case.expected_error_contains)': $errorMessage"
        }
        elseif ($hardwareTouched -ne $false) {
            $casePassed = $false
            $failure = "$($Case.name) expected-failure path reported execution.hardware_touched=$hardwareTouched."
        }
    }

    $assertionFailures = @($identityNormalizationFailures) + @($outputStateNormalizationFailures) + @($instrumentErrorNormalizationFailures)
    if ($casePassed) {
        $assertionFailures += @(Get-CaseAssertionFailures -Case $Case -Payload $payload -OutputStates $outputStates -InstrumentErrors $instrumentErrors -StderrPath $stderrPath)
        if ($assertionFailures.Count -gt 0) {
            $casePassed = $false
            $failure = $assertionFailures -join " "
        }
    }

    $generatedArtifactPaths = New-Object System.Collections.Generic.List[string]
    $artifactIndex = 0
    foreach ($generatedPath in $Case.generated_artifacts) {
        $artifactIndex += 1
        if (Test-Path -LiteralPath $generatedPath) {
            $extension = [System.IO.Path]::GetExtension($generatedPath)
            $shareableGeneratedPath = Join-Path $script:ShareableArtifactDir ($artifactBaseName + "-generated-" + $artifactIndex + $extension)
            Write-ShareableTextArtifact -PrivatePath $generatedPath -ShareablePath $shareableGeneratedPath
            $generatedArtifactPaths.Add((ConvertTo-RepoRelativePath -Path $shareableGeneratedPath))
            $shareableGeneratedText = Get-Content -LiteralPath $shareableGeneratedPath -Raw
            $forbiddenValues = @($script:RawResource, $RepoRoot, $PythonExe) + @($script:SensitiveValues)
            foreach ($forbiddenValue in $forbiddenValues) {
                if (-not [string]::IsNullOrWhiteSpace([string]$forbiddenValue) -and $shareableGeneratedText.Contains([string]$forbiddenValue)) {
                    $assertionFailures += "$($Case.name) shareable generated artifact leaked sensitive data."
                    $casePassed = $false
                    $failure = $assertionFailures -join " "
                    break
                }
            }
        }
    }

    $recordArgs = Protect-Arguments -Arguments $allArgs
    $commandLine = (Get-ShareableCliCommand) + " " + (($recordArgs | ForEach-Object { Format-CommandArgument -Argument $_ }) -join " ")
    $backendScope = if ($null -eq $script:BackendArtifact) { $null } else { $script:BackendArtifact.backend_scope }
    $attemptDiagnostics = New-Object System.Collections.Generic.List[object]
    foreach ($attempt in $attemptResults) {
        $attemptPayload = $attempt.payload
        $attemptError = if ($null -eq $attemptPayload) { $null } else { Get-PropertyValue -Object $attemptPayload -Name "error" }
        $attemptExecution = if ($null -eq $attemptPayload) { $null } else { Get-PropertyValue -Object $attemptPayload -Name "execution" }
        $attemptDiagnosticFields = [ordered]@{
            attempt = $attempt.attempt_number
            settle_before_ms = $attempt.settle_before_ms
            exit_code = $attempt.exit_code
            ok = if ($null -eq $attemptPayload) { $null } else { Get-PropertyValue -Object $attemptPayload -Name "ok" }
            status = if ($null -eq $attemptPayload) { $null } else { Get-PropertyValue -Object $attemptPayload -Name "status" }
            error_code = if ($null -eq $attemptError) { $null } else { Get-PropertyValue -Object $attemptError -Name "code" }
            error_message = if ($null -eq $attemptError) { $null } else { Protect-ShareableText -Text ([string](Get-PropertyValue -Object $attemptError -Name "message")) }
            scpi_transcript_empty = $attempt.scpi_transcript_empty
            generated_artifacts_changed = $attempt.generated_artifacts_changed
            json_path = ConvertTo-RepoRelativePath -Path $attempt.shareable_json_path
            stdout_path = ConvertTo-RepoRelativePath -Path $attempt.shareable_stdout_path
            stderr_scpi_path = ConvertTo-RepoRelativePath -Path $attempt.shareable_stderr_path
        }
        if (Test-LiveTcpipPhase -Phase $Case.phase) {
            $attemptDiagnosticFields["hardware_touched"] = if ($null -eq $attemptExecution) { $null } else { Get-PropertyValue -Object $attemptExecution -Name "hardware_touched" }
        }
        $attemptDiagnostics.Add([pscustomobject]$attemptDiagnosticFields)
    }
    $firstPayloadError = if ($null -eq $firstAttempt.payload) { $null } else { Get-PropertyValue -Object $firstAttempt.payload -Name "error" }
    $record = [pscustomobject]@{
        name = $Case.name
        suite = $Case.suite
        phase = $Case.phase
        command_line = $commandLine
        arguments = $recordArgs
        exit_code = $exitCode
        ok = $ok
        mode = $mode
        dry_run = $dryRun
        error_code = $errorCode
        parse_error = $parseError
        attempt_count = $attemptResults.Count
        recovery_attempted = [bool]$recoveryAttempted
        recovered_after_open_failure = $recoveredAfterOpenFailure
        final_attempt = $finalAttempt.attempt_number
        first_error_code = if ($null -eq $firstPayloadError) { $null } else { Get-PropertyValue -Object $firstPayloadError -Name "code" }
        first_error_message = if ($null -eq $firstPayloadError) { $null } else { Protect-ShareableText -Text ([string](Get-PropertyValue -Object $firstPayloadError -Name "message")) }
        first_scpi_transcript_empty = $firstAttempt.scpi_transcript_empty
        settle_delay_ms = if (Test-LiveTcpipPhase -Phase $Case.phase) { $script:TcpipSessionSettleDelayMs } else { 0 }
        attempts = $attemptDiagnostics.ToArray()
        expected_success = $Case.expected_success
        support_policy_mode = if ($allArgs -contains "--validation-allow-pending-live-support") { "validation" } elseif ($allArgs[0] -in $script:PolicyGatedCommands) { "product" } else { $null }
        transport_scope = $script:TransportScope
        backend_scope = $backendScope
        identity_observed = $identityObserved
        output_states_observed = $outputStates
        instrument_errors_observed = $instrumentErrors
        trigger = $triggerRecord
        cleanup_role = $Case.cleanup_role
        state_changing = $Case.state_changing
        validation_kind = $Case.validation_kind
        assertion_failures = @($assertionFailures | ForEach-Object { Protect-ShareableText -Text $_ })
        generated_artifacts = $generatedArtifactPaths.ToArray()
        comparison_result = if ($Case.validation_kind -eq "snapshot-compare") { if ($assertionFailures.Count -eq 0) { "matched" } else { "mismatch" } } else { $null }
        result = if ($casePassed) { "passed" } else { "failed" }
        stdout_path = ConvertTo-RepoRelativePath -Path $shareableStdoutPath
        stderr_path = ConvertTo-RepoRelativePath -Path $shareableStderrPath
        stderr_scpi_path = ConvertTo-RepoRelativePath -Path $shareableStderrPath
        json_path = ConvertTo-RepoRelativePath -Path $shareableJsonPath
    }
    $script:CommandRecords.Add($record)
    if (-not $casePassed) {
        $script:Failures.Add($failure)
    }
    if ($casePassed -and $identityObserved -and $null -ne $identity -and ($null -eq $script:InstrumentIdentity -or $script:InstrumentIdentity.availability -ne "observed")) {
        $serial = Get-PropertyValue -Object $identity -Name "serial"
        $script:InstrumentIdentity = [pscustomobject]@{
            availability = "observed"
            manufacturer = Get-PropertyValue -Object $identity -Name "manufacturer"
            detected_model = Get-PropertyValue -Object $identity -Name "model"
            firmware = Get-PropertyValue -Object $identity -Name "firmware"
            serial = if ([string]::IsNullOrWhiteSpace([string]$serial)) { $null } else { "<redacted>" }
            serial_redacted = -not [string]::IsNullOrWhiteSpace([string]$serial)
            source_command = $Case.name
        }
    }
    return $record
}

function Test-AllOutputsOff {
    param([AllowNull()]$OutputStates)

    if ($null -eq $OutputStates) {
        return $null
    }
    $items = @($OutputStates)
    if ($items.Count -eq 0) {
        return $null
    }
    foreach ($item in $items) {
        $enabled = Get-PropertyValue -Object $item -Name "enabled"
        if ($enabled -isnot [System.Boolean]) {
            return $null
        }
        if ($enabled) {
            return $false
        }
    }
    return $true
}

function Invoke-SafeOffCleanup {
    param([string]$Role = "failure")

    if (-not $Restore) {
        $script:CleanupEvidence = New-CleanupEvidence -ValidationMode "live"
        return
    }
    $script:CleanupEvidence = New-CleanupEvidence -ValidationMode "live"
    $script:CleanupEvidence.requested = $true
    $script:CleanupEvidence.attempted = $true
    $safeOffFailed = $false
    $cleanupName = "safe-off-" + ($Role -replace '[^A-Za-z0-9_-]', '-') + "-cleanup"
    $cleanupCase = New-CommandCase -Name $cleanupName -Suite "cleanup" -Phase "live" -Args @("safe-off", "--json", "--resource", $script:RawResource, "--channel", "all", "--log-scpi") -StateChanging:$true -LiveHardwareExpected:$true -CleanupRole ($Role + "_safe_off")
    try {
        $safeOffRecord = Invoke-ValidationCommand -Case $cleanupCase
        $script:CleanupEvidence.safe_off_command = $safeOffRecord.command_line
        $script:CleanupEvidence.safe_off_exit_code = $safeOffRecord.exit_code
        $script:CleanupEvidence.safe_off_ok = ($safeOffRecord.result -eq "passed")
        if (-not $script:CleanupEvidence.safe_off_ok) {
            $script:CleanupEvidence.status = "failed"
            $script:Failures.Add("Cleanup safe-off command failed.")
            $safeOffFailed = $true
        }

        $outputStateCase = New-CommandCase -Name "cleanup-output-state" -Suite "cleanup" -Phase "live" -Args @("output-state", "--json", "--resource", $script:RawResource, "--channel", "all", "--log-scpi") -LiveHardwareExpected:$true -ExpectedChannels @(Get-TargetChannels -Model $script:NormalizedTarget) -CleanupRole "final_output_state"
        $outputStateRecord = Invoke-ValidationCommand -Case $outputStateCase
        if ($outputStateRecord.result -eq "passed") {
            $script:CleanupEvidence.output_state_checked = $true
            $script:CleanupEvidence.all_outputs_off = Test-AllOutputsOff -OutputStates $outputStateRecord.output_states_observed
        }
        else {
            $script:Failures.Add("Cleanup did not produce verifiable output-state evidence.")
        }

        $errorCase = New-CommandCase -Name "cleanup-error-queue" -Suite "cleanup" -Phase "live" -Args @("error", "--json", "--resource", $script:RawResource, "--max-reads", "20", "--log-scpi") -LiveHardwareExpected:$true -CleanupRole "final_error_queue" -ValidationKind "empty-errors"
        $errorRecord = Invoke-ValidationCommand -Case $errorCase
        if ($errorRecord.result -eq "passed" -or
            ($null -ne $errorRecord.instrument_errors_observed -and @($errorRecord.instrument_errors_observed).Count -gt 0)) {
            $script:CleanupEvidence.error_queue_checked = $true
            $script:CleanupEvidence.instrument_errors = $errorRecord.instrument_errors_observed
        }
        else {
            $script:Failures.Add("Cleanup could not verify the instrument error queue.")
        }

        if ($safeOffFailed) {
            $script:CleanupEvidence.status = "failed"
        }
        elseif ($script:CleanupEvidence.all_outputs_off -eq $false) {
            $script:CleanupEvidence.status = "failed"
            $script:Failures.Add("Cleanup could not confirm that all outputs are off.")
        }
        elseif (-not $script:CleanupEvidence.output_state_checked -or -not $script:CleanupEvidence.error_queue_checked -or $null -eq $script:CleanupEvidence.all_outputs_off) {
            $script:CleanupEvidence.status = "partial"
            if (-not $script:CleanupEvidence.output_state_checked -or $null -eq $script:CleanupEvidence.all_outputs_off) {
                if ($script:Failures -notcontains "Cleanup did not produce verifiable output-state evidence.") {
                    $script:Failures.Add("Cleanup did not produce verifiable output-state evidence.")
                }
            }
            if (-not $script:CleanupEvidence.error_queue_checked) {
                if ($script:Failures -notcontains "Cleanup could not verify the instrument error queue.") {
                    $script:Failures.Add("Cleanup could not verify the instrument error queue.")
                }
            }
        }
        elseif ($null -ne $script:CleanupEvidence.instrument_errors -and @($script:CleanupEvidence.instrument_errors).Count -gt 0) {
            $script:CleanupEvidence.status = "partial"
            $script:Failures.Add("Cleanup finished with instrument errors.")
        }
        else {
            $script:CleanupEvidence.status = "passed"
        }
    }
    catch {
        $script:CleanupEvidence.status = "failed"
        $script:Failures.Add("$Role cleanup threw: " + $_.Exception.Message)
    }
}

function New-TriggerEvidence {
    return [pscustomobject]@{
        fire = [pscustomobject]@{
            armed_prerequisite = $false
            baseline_safe = $null
            fired = $false
            completed = $false
            timeout_or_interrupted = $false
            abort_status = "not_executed"
            abort_attempted = $null
            abort_succeeded = $null
            abort_errors = $null
            trigger_restore_succeeded = $null
            arm_error_queue_empty = $null
            error_queue_empty = $null
            outputs_all_off = $null
        }
        pulse = [pscustomobject]@{
            operator_interaction_required = $true
            operator_ready_confirmed = $false
            baseline_safe = $null
            expected_pin = 1
            expected_polarity = "positive"
            expected_pulse_count = 1
            command_path_succeeded = $false
            operator_observation = "not_requested"
            trigger_restore_succeeded = $null
            cleanup_succeeded = $null
            error_queue_empty = $null
            outputs_all_off = $null
            validates_pulse_width = $false
            validates_timing_accuracy = $false
            validates_waveform_quality = $false
        }
    }
}

function Invoke-TriggerValidationHelper {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("arm", "restore")][string]$Action,
        [Parameter(Mandatory = $true)][string]$SnapshotPath
    )

    $helperPath = Join-Path $PSScriptRoot "e36312a_trigger_validation.py"
    $stdoutPath = Join-Path $script:PrivateArtifactDir ("trigger-fire-helper-" + $Action + ".stdout.json")
    $stderrPath = Join-Path $script:PrivateArtifactDir ("trigger-fire-helper-" + $Action + ".stderr.txt")
    $arguments = @($helperPath, $Action, "--resource", $script:RawResource, "--snapshot-json", $SnapshotPath)
    if (-not [string]::IsNullOrWhiteSpace($script:BackendValue)) {
        $arguments += @("--backend", $script:BackendValue)
    }
    $hadPythonPath = $null -ne [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $oldPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $oldErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        [Environment]::SetEnvironmentVariable("PYTHONPATH", (Get-ValidationChildPythonPath), "Process")
        Invoke-LiveTcpipSubprocessSettle -Phase "live" | Out-Null
        & $PythonExe @arguments 1> $stdoutPath 2> $stderrPath
        $exitCode = $LASTEXITCODE
    }
    finally {
        if ($hadPythonPath) { [Environment]::SetEnvironmentVariable("PYTHONPATH", $oldPythonPath, "Process") }
        else { [Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process") }
        $ErrorActionPreference = $oldErrorActionPreference
    }
    $payload = $null
    try { $payload = Get-Content -LiteralPath $stdoutPath -Raw | ConvertFrom-Json }
    catch { }
    return [pscustomobject]@{
        ok = [bool]($exitCode -eq 0 -and $null -ne $payload -and $payload.ok -eq $true)
        exit_code = $exitCode
        payload = $payload
    }
}

function Invoke-TriggerFireCandidateCase {
    param([Parameter(Mandatory = $true)]$Case)

    Invoke-SafeOffCleanup -Role "trigger-fire-baseline"
    if ($script:CleanupEvidence.status -ne "passed") {
        $script:TriggerEvidence.fire.baseline_safe = $false
        return
    }
    $script:TriggerEvidence.fire.baseline_safe = $true
    $snapshotPath = Join-Path $script:PrivateArtifactDir "trigger-fire-snapshot.json"
    $arm = $null
    try {
        $arm = Invoke-TriggerValidationHelper -Action "arm" -SnapshotPath $snapshotPath
        $script:TriggerEvidence.fire.armed_prerequisite = [bool]$arm.ok
        $script:TriggerEvidence.fire.arm_error_queue_empty = [bool]($arm.ok -and $arm.payload.error_queue_empty)
        if (-not $arm.ok) {
            $script:Failures.Add("trigger-fire arm helper failed before the candidate command.")
            return
        }
        $script:TriggerEvidence.fire.abort_status = "unknown"
        $record = Invoke-ValidationCommand -Case $Case
        $recordTrigger = Get-PropertyValue -Object $record -Name "trigger"
        $recordFiredProperty = if ($null -eq $recordTrigger) { $null } else { $recordTrigger.PSObject.Properties["fired"] }
        $recordCompletedProperty = if ($null -eq $recordTrigger) { $null } else { $recordTrigger.PSObject.Properties["completed"] }
        if ($null -ne $recordFiredProperty -and $recordFiredProperty.Value -is [bool]) {
            $script:TriggerEvidence.fire.fired = $recordFiredProperty.Value
        }
        if ($null -ne $recordCompletedProperty -and $recordCompletedProperty.Value -is [bool]) {
            $script:TriggerEvidence.fire.completed = $recordCompletedProperty.Value
        }
        foreach ($abortField in @("abort_attempted", "abort_succeeded", "abort_errors")) {
            $abortProperty = if ($null -eq $recordTrigger) { $null } else { $recordTrigger.PSObject.Properties[$abortField] }
            if ($null -ne $abortProperty) {
                $script:TriggerEvidence.fire.$abortField = $abortProperty.Value
            }
        }
        $script:TriggerEvidence.fire.timeout_or_interrupted = [bool](
            $record.error_code -ceq "wait_timeout" -or $record.error_code -ceq "interrupted"
        )
        $abortAttemptedProperty = if ($null -eq $recordTrigger) { $null } else { $recordTrigger.PSObject.Properties["abort_attempted"] }
        $abortSucceededProperty = if ($null -eq $recordTrigger) { $null } else { $recordTrigger.PSObject.Properties["abort_succeeded"] }
        if ($record.result -eq "passed") {
            $script:TriggerEvidence.fire.abort_status = "not_required"
        }
        elseif ($null -ne $abortAttemptedProperty -and $abortAttemptedProperty.Value -is [bool] -and $abortAttemptedProperty.Value -eq $false) {
            $script:TriggerEvidence.fire.abort_status = "not_attempted"
        }
        elseif ($null -ne $abortAttemptedProperty -and $abortAttemptedProperty.Value -is [bool] -and $abortAttemptedProperty.Value -eq $true -and
            $null -ne $abortSucceededProperty -and $abortSucceededProperty.Value -is [bool]) {
            $script:TriggerEvidence.fire.abort_status = if ($abortSucceededProperty.Value) { "succeeded" } else { "failed" }
        }
    }
    finally {
        if (Test-Path -LiteralPath $snapshotPath) {
            $restore = Invoke-TriggerValidationHelper -Action "restore" -SnapshotPath $snapshotPath
            $script:TriggerEvidence.fire.trigger_restore_succeeded = [bool]$restore.ok
            if (-not $restore.ok) {
                $script:Failures.Add("trigger-fire helper restore failed.")
            }
        }
        else {
            $script:TriggerEvidence.fire.trigger_restore_succeeded = $false
        }
        Invoke-SafeOffCleanup -Role "trigger-fire-final"
        $script:TriggerEvidence.fire.outputs_all_off = $script:CleanupEvidence.all_outputs_off
        $script:TriggerEvidence.fire.error_queue_empty = [bool](
            $script:CleanupEvidence.error_queue_checked -and
            @($script:CleanupEvidence.instrument_errors).Count -eq 0
        )
    }
}

function Invoke-TriggerPulseCandidateCase {
    param([Parameter(Mandatory = $true)]$Case)

    Write-Host ""
    Write-Host "E36312A trigger-pulse requires external observation."
    Write-Host "- Signal: rear Pin 1"
    Write-Host "- Digital signal reference: rear Pin 4 Common"
    Write-Host "- Expected result: one positive pulse"
    Write-Host "- Connect and arm the oscilloscope or logic analyzer before continuing."
    $ready = Read-Host "Press Enter when the external instrument is armed, or press Ctrl+C to cancel"
    if (-not [string]::IsNullOrEmpty([string]$ready)) {
        $script:Failures.Add("trigger-pulse operator readiness confirmation was invalid.")
        return
    }
    $script:TriggerEvidence.pulse.operator_ready_confirmed = $true
    Invoke-SafeOffCleanup -Role "trigger-pulse-baseline"
    if ($script:CleanupEvidence.status -ne "passed") {
        $script:TriggerEvidence.pulse.baseline_safe = $false
        return
    }
    $script:TriggerEvidence.pulse.baseline_safe = $true
    $record = $null
    try {
        $record = Invoke-ValidationCommand -Case $Case
        $script:TriggerEvidence.pulse.command_path_succeeded = ($record.result -eq "passed")
        $script:TriggerEvidence.pulse.trigger_restore_succeeded = ($record.result -eq "passed")
    }
    finally {
        Invoke-SafeOffCleanup -Role "trigger-pulse-final"
        $script:TriggerEvidence.pulse.outputs_all_off = $script:CleanupEvidence.all_outputs_off
        $script:TriggerEvidence.pulse.error_queue_empty = [bool](
            $script:CleanupEvidence.error_queue_checked -and
            @($script:CleanupEvidence.instrument_errors).Count -eq 0
        )
        $script:TriggerEvidence.pulse.cleanup_succeeded = ($script:CleanupEvidence.status -eq "passed")
    }
    if ($null -eq $record -or $record.result -ne "passed" -or $script:CleanupEvidence.status -ne "passed") {
        $script:TriggerEvidence.pulse.operator_observation = "not_requested_automatic_failure"
        return
    }
    $observation = Read-Host "Did you observe exactly one positive pulse? Enter Yes or No"
    if ([string]::Equals($observation, "Yes", [System.StringComparison]::OrdinalIgnoreCase)) {
        $script:TriggerEvidence.pulse.operator_observation = "passed"
        return
    }
    $script:TriggerEvidence.pulse.operator_observation = if ([string]::Equals($observation, "No", [System.StringComparison]::OrdinalIgnoreCase)) { "failed" } else { "invalid" }
    $script:Failures.Add("trigger-pulse external observation did not receive an explicit Yes result.")
}

function Write-LiveConfirmationWarnings {
    param([Parameter(Mandatory = $true)][string[]]$SuitesToRun)

    if (@($SuitesToRun | Where-Object { $_ -in @("safe-state", "output", "protection", "snapshot", "trigger-list", "software-sequence") }).Count -gt 0) {
        Write-Host "Possible state changes:"
        $outputAffectingSuites = @(@("output", "snapshot", "trigger-list", "software-sequence") | Where-Object { $_ -in $SuitesToRun })
        if (@($outputAffectingSuites).Count -gt 0) {
            if (@($outputAffectingSuites).Count -eq 1) {
                $outputCaseText = "$($outputAffectingSuites[0]) cases"
            }
            elseif (@($outputAffectingSuites).Count -eq 2) {
                $outputCaseText = "$($outputAffectingSuites[0]) or $($outputAffectingSuites[1]) cases"
            }
            else {
                $head = @($outputAffectingSuites[0..($outputAffectingSuites.Count - 2)]) -join ", "
                $outputCaseText = "$head, or $($outputAffectingSuites[-1]) cases"
            }
            Write-Host "- Low-power setpoints may be written: 1 V / 0.05 A."
            Write-Host "- Outputs may briefly turn on for $outputCaseText."
        }
        if ("safe-state" -in $SuitesToRun) {
            Write-Host "- Safe-state cases may turn outputs OFF but never enable outputs or write setpoints."
        }
        if ("protection" -in $SuitesToRun) {
            Write-Host "- Protection suite writes OVP/OCP settings and clears protection state."
        }
        if ("snapshot" -in $SuitesToRun) {
            Write-Host "- E36312A snapshot validation includes confirmed real restore paths and mandatory safe-off cleanup."
        }
        Write-Host "- Safe-off cleanup may be attempted when Restore is true."
        if ("protection" -in $SuitesToRun) {
            Write-Host "- Cleanup does not restore original voltage/current/protection settings."
        }
        else {
            Write-Host "- Cleanup does not restore original voltage/current settings."
        }
    }
    else {
        Write-Host "This suite is non-output-affecting except for possible status/error queue reads."
    }
}

function Normalize-CleanupEvidenceForReport {
    param([Parameter(Mandatory = $true)][string]$ValidationMode)

    $completedStatuses = @("passed", "partial", "failed", "skipped_by_operator")
    if ($null -eq $script:CleanupEvidence) {
        $script:CleanupEvidence = New-CleanupEvidence -ValidationMode $ValidationMode
        return
    }
    if ($script:CleanupEvidence.status -in $completedStatuses) {
        return
    }
    if ($ValidationMode -eq "planned") {
        $script:CleanupEvidence = New-CleanupEvidence -ValidationMode "planned"
        return
    }
    if ($ValidationMode -eq "preflight_failed") {
        $script:CleanupEvidence = New-CleanupEvidence -ValidationMode "preflight_failed"
        return
    }
    if ($ValidationMode -eq "confirmation_required") {
        $script:CleanupEvidence = New-CleanupEvidence -ValidationMode "confirmation_required"
        return
    }
    if ($ValidationMode -eq "live") {
        $script:CleanupEvidence = New-CleanupEvidence -ValidationMode "live"
    }
}

function Write-ValidationArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$ValidationMode,
        [Parameter(Mandatory = $true)][string]$Result,
        [Parameter(Mandatory = $true)][datetime]$StartedAt
    )

    Ensure-ArtifactDirectories
    $completedAt = Get-Date
    $reportPath = Join-Path $script:ShareableArtifactDir "report.json"
    $summaryPath = Join-Path $script:ShareableArtifactDir "summary.md"
    $caseRecords = @($script:CommandRecords | ForEach-Object {
        [pscustomobject]@{
            name = $_.name
            suite = $_.suite
            phase = $_.phase
            expected_success = $_.expected_success
            result = $_.result
        }
    })
    $plannedLiveCases = @($script:PlannedLiveCases | ForEach-Object {
        [pscustomobject]@{
            name = $_.name
            suite = $_.suite
            command = if ($_.args.Count -gt 0) { $_.args[0] } else { $null }
            arguments = Protect-Arguments -Arguments $_.args
            state_changing = $_.state_changing
            validation_kind = $_.validation_kind
            expected_channels = $_.expected_channels
            cleanup_role = $_.cleanup_role
            operator_interaction_required = [bool]$_.operator_interaction_required
        }
    })
    if ($null -eq $script:InstrumentIdentity) {
        $script:InstrumentIdentity = [pscustomobject]@{
            availability = if ($ValidationMode -eq "planned") { "not_observed_plan_only" } else { "not_observed" }
            manufacturer = $null
            detected_model = $null
            firmware = $null
            serial = $null
            serial_redacted = $false
            source_command = $null
        }
    }
    Normalize-CleanupEvidenceForReport -ValidationMode $ValidationMode
    if ($ValidationMode -eq "live" -and $script:StateChanging -and $Restore -and $Result -eq "passed" -and $script:CleanupEvidence.status -ne "passed") {
        if ($script:Failures -notcontains "Required cleanup did not complete successfully.") {
            $script:Failures.Add("Required cleanup did not complete successfully.")
        }
        $Result = "failed"
    }
    $candidateEvidenceOnly = [bool]$script:PendingLiveSupportAllowed
    $promotesLiveSupport = $false
    $reportFields = [ordered]@{
        schema_version = "2.0"
        kind = "powers-tool-live-validation"
        vendor_id = $TargetMetadata[$script:NormalizedTarget].vendor_id
        model_id = $script:NormalizedTarget
        connection = $script:ConnectionLabel
        transport_scope = $script:TransportScope
        suite = $Suite
        validation_mode = $ValidationMode
        support_policy_mode = $script:SupportPolicyMode
        pending_live_support_allowed = $script:PendingLiveSupportAllowed
        candidate_evidence_only = $candidateEvidenceOnly
        promotes_live_support = $promotesLiveSupport
        plan_only = [bool]$PlanOnly
        live_executed = ($ValidationMode -eq "live")
        state_changing = $script:StateChanging
        restore_requested = [bool]$Restore
        resource = $script:ResourceDisplay
        backend = $script:BackendArtifact.backend
        backend_scope = $script:BackendArtifact.backend_scope
        backend_argument = $script:BackendArtifact.backend_argument
        instrument_identity = $script:InstrumentIdentity
        cleanup = $script:CleanupEvidence
        trigger_evidence = $script:TriggerEvidence
        git_head = Get-GitHead
        package_version = Get-PackageVersion
        started_at = $StartedAt.ToUniversalTime().ToString("o")
        completed_at = $completedAt.ToUniversalTime().ToString("o")
        result = $Result
        status = $Result
        output_dir = ConvertTo-RepoRelativePath -Path $script:ShareableArtifactDir
        shareable_artifact_dir = ConvertTo-RepoRelativePath -Path $script:ShareableArtifactDir
        preflight_report = ConvertTo-RepoRelativePath -Path $reportPath
        external_preflight = $script:ExternalPreflight
        suites = $script:SuitesToRun
        cases = $caseRecords
        planned_live_cases = $plannedLiveCases
        commands = $script:CommandRecords.ToArray()
        failures = @($script:Failures | ForEach-Object { Protect-ShareableText -Text $_ })
    }
    if ($ValidationMode -eq "live") {
        $reportFields.expected_model_id = $script:NormalizedTarget
    }
    else {
        $reportFields.planning_model_id = $script:NormalizedTarget
    }
    $report = [pscustomobject]$reportFields
    $shareableReport = ConvertTo-ShareableJsonValue -Value $report -FieldName $null -ParentName $null
    Write-Utf8NoBomFile -LiteralPath $reportPath -Value @($shareableReport | ConvertTo-Json -Depth 30)

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# Powers Tool Live Validation")
    $lines.Add("")
    $lines.Add("Target: ``" + $script:NormalizedTarget + "``")
    $lines.Add("Connection: ``" + $script:ConnectionLabel + "``")
    $lines.Add("Suite: ``" + $Suite + "``")
    $lines.Add("Suites run: ``" + ($script:SuitesToRun -join ", ") + "``")
    $lines.Add("Result: ``" + $Result + "``")
    $lines.Add("PlanOnly: ``" + [bool]$PlanOnly + "``")
    $lines.Add("External preflight: ``" + $script:ExternalPreflight.status + "``")
    $lines.Add("Live executed: ``" + ($ValidationMode -eq "live") + "``")
    $lines.Add("Support policy mode: ``" + $script:SupportPolicyMode + "``")
    $lines.Add("Pending live support allowed: ``" + $script:PendingLiveSupportAllowed.ToString().ToLowerInvariant() + "``")
    $lines.Add("Candidate evidence only: ``" + $candidateEvidenceOnly.ToString().ToLowerInvariant() + "``")
    $lines.Add("Promotes product support: ``" + $promotesLiveSupport.ToString().ToLowerInvariant() + "``")
    $lines.Add("Transport scope: ``" + $script:TransportScope + "``")
    $lines.Add("Backend scope: ``" + $script:BackendArtifact.backend_scope + "``")
    $lines.Add("Shareable artifact directory: ``" + (ConvertTo-RepoRelativePath -Path $script:ShareableArtifactDir) + "``")
    $lines.Add("Resource: ``" + $script:ResourceDisplay + "``")
    $lines.Add("")
    $lines.Add("## Safety Notes")
    if ($candidateEvidenceOnly) {
        $lines.Add("- This run produces candidate validation evidence only. Passing artifacts do not automatically promote product support.")
    }
    else {
        $lines.Add("- This run is a regression validation of an already Product-open exact scope. It does not promote or broaden Product support.")
    }
    $lines.Add("- This suite validates only the selected model, connection, suite, and command cases.")
    $lines.Add("- It does not validate untested features or other connections.")
    $outputAffectingSuites = @($script:SuitesToRun | Where-Object { $_ -in @("output", "snapshot", "trigger-list", "software-sequence") })
    if (@($outputAffectingSuites).Count -gt 0) {
        $lines.Add("- State-changing live cases use low-power 1 V / 0.05 A settings.")
    }
    if ("safe-state" -in $script:SuitesToRun) {
        $lines.Add("- Safe-state cases may turn outputs OFF but never enable outputs or write setpoints.")
    }
    if ($script:StateChanging) {
        $lines.Add("- Safe-off cleanup does not restore original voltage/current/protection settings.")
    }
    else {
        $lines.Add("- The selected suite is non-output-affecting except for possible status/error queue reads.")
    }
    if ($script:NormalizedTarget -eq "keysight-e3646a") {
        $lines.Add("- E3646A OUTP ON/OFF is global, not an independent per-channel relay behavior.")
        $lines.Add("- E3646A ramp-list and sequence are software workflows, not native LIST.")
    }
    $lines.Add("")
    $lines.Add("## Identity And Cleanup Evidence")
    $lines.Add("- Canonical model ID: ``" + $script:NormalizedTarget + "`` (not a detected-driver override).")
    $lines.Add("- Observed identity availability: ``" + $script:InstrumentIdentity.availability + "``")
    if ($null -ne $script:InstrumentIdentity.detected_model) {
        $lines.Add("- Detected model: ``" + $script:InstrumentIdentity.detected_model + "`` from ``" + $script:InstrumentIdentity.source_command + "``.")
    }
    $lines.Add("- Cleanup status: ``" + $script:CleanupEvidence.status + "``")
    $lines.Add("- Cleanup output state checked: ``" + $script:CleanupEvidence.output_state_checked + "``; all outputs off: ``" + $script:CleanupEvidence.all_outputs_off + "``")
    $lines.Add("- Cleanup error queue checked: ``" + $script:CleanupEvidence.error_queue_checked + "``")
    $lines.Add("")
    $lines.Add("## Physical Checks")
    $lines.Add("- Confirm the expected instrument and explicit VISA resource.")
    $lines.Add("- Confirm no DUT is connected, or only a known safe load, before state-changing suites.")
    $lines.Add("- Confirm output indicators are off before output-affecting suites.")
    $lines.Add("- Confirm no OVP/OCP/error/protection abnormal indicators are shown.")
    $lines.Add("")
    $lines.Add("## Case Table")
    $lines.Add("| Case | Suite | Phase | Expected success | Result |")
    $lines.Add("| --- | --- | --- | --- | --- |")
    foreach ($caseRecord in $caseRecords) {
        $lines.Add("| ``" + $caseRecord.name + "`` | ``" + $caseRecord.suite + "`` | ``" + $caseRecord.phase + "`` | ``" + $caseRecord.expected_success + "`` | ``" + $caseRecord.result + "`` |")
    }
    $lines.Add("")
    $lines.Add("## Command Table")
    $lines.Add("| Command | Exit | ok | mode | dry_run | JSON | SCPI/stderr |")
    $lines.Add("| --- | ---: | --- | --- | --- | --- | --- |")
    foreach ($command in $script:CommandRecords) {
        $lines.Add("| ``" + $command.name + "`` | " + $command.exit_code + " | " + $command.ok + " | " + $command.mode + " | " + $command.dry_run + " | ``" + $command.json_path + "`` | ``" + $command.stderr_scpi_path + "`` |")
    }
    if ($script:Failures.Count -gt 0) {
        $lines.Add("")
        $lines.Add("## Failures")
        foreach ($failure in $script:Failures) {
            $lines.Add("- " + (Protect-ShareableText -Text $failure))
        }
    }
    Write-Utf8NoBomFile -LiteralPath $summaryPath -Value $lines
}

$script:ConnectionLabel = $null
$script:TransportScope = $null
$script:BackendArtifact = Get-BackendArtifactFields -Value $null
$script:InstrumentIdentity = $null
$script:CleanupEvidence = $null
$script:TriggerEvidence = New-TriggerEvidence
$script:PrivateArtifactDir = $null
$script:ShareableArtifactDir = $null
$script:ExternalPreflight = [pscustomobject]@{ status = "not_run" }
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:PlannedLiveCases = @()
$script:CandidateInventory = $null
$script:ProductOpenCommands = @()
$script:ValidationPendingCommands = @()
$script:SupportPolicyMode = "validation"
$script:PendingLiveSupportAllowed = $true

if ($env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY -eq "1") {
    return
}

if ($SkipExternalPreflight -and -not $PlanOnly) {
    Fail-Validation "-SkipExternalPreflight can only be used with -PlanOnly."
}

$NormalizedTarget = Resolve-Target -Value $Target
$ConnectionLabel = Resolve-Connection -Value $Connection
if ([string]::IsNullOrWhiteSpace($Resource)) {
    Fail-Validation "Missing required -Resource. Pass the exact VISA resource explicitly; this script never scans or guesses a live resource."
}
if ($NormalizedTarget -eq "keysight-e3646a" -and $ConnectionLabel -ne "ASRL") {
    Fail-Validation "E3646A live validation currently requires an explicit ASRL/RS-232/serial connection."
}

$script:NormalizedTarget = $NormalizedTarget
$script:ConnectionLabel = $ConnectionLabel
$script:RawResource = $Resource
$script:ResourceDisplay = "$ConnectionLabel`:<redacted-resource>"
$script:BackendValue = $Backend
$script:TransportScope = Get-TransportScope -Connection $ConnectionLabel
$script:BackendArtifact = Get-BackendArtifactFields -Value $Backend
$script:InstrumentIdentity = $null
$script:CleanupEvidence = $null
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]

$supportedSuites = Get-SupportedSuites -Model $NormalizedTarget
if ($Suite -eq "full") {
    $SuitesToRun = $supportedSuites
}
else {
    if ($Suite -notin $supportedSuites) {
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $OutputDir = Join-Path (Join-Path $TmpRoot "live_cli_check") ($timestamp + "_" + $NormalizedTarget + "_" + $ConnectionLabel + "_" + $Suite)
        $script:OutputDir = Reset-OutputDirectory -Path $OutputDir -Root $TmpRoot
        $script:SuitesToRun = @($Suite)
        $script:StateChanging = $false
        $script:CommandRecords = New-Object System.Collections.Generic.List[object]
        $script:Failures = New-Object System.Collections.Generic.List[string]
        $script:CleanupEvidence = New-CleanupEvidence -ValidationMode "failed"
        $script:Failures.Add("Unsupported suite '$Suite' for target $NormalizedTarget. Supported suites: $($supportedSuites -join ', ').")
        Write-ValidationArtifacts -ValidationMode "failed" -Result "failed" -StartedAt (Get-Date)
        Fail-Validation "Unsupported suite '$Suite' for target $NormalizedTarget. Supported suites: $($supportedSuites -join ', ')."
    }
    $SuitesToRun = @($Suite)
}
if (-not $PlanOnly -and -not $Restore -and @($SuitesToRun | Where-Object { $_ -in @("snapshot", "trigger-list") }).Count -gt 0) {
    Fail-Validation "Snapshot and trigger-list live validation require safe-off cleanup; -Restore:`$false is not allowed."
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutputDir = Join-Path (Join-Path $TmpRoot "live_cli_check") ($timestamp + "_" + $NormalizedTarget + "_" + $ConnectionLabel + "_" + $Suite)
$script:OutputDir = Reset-OutputDirectory -Path $OutputDir -Root $TmpRoot
$script:SuitesToRun = @($SuitesToRun)
$script:StateChanging = @($SuitesToRun | Where-Object { $_ -in @("safe-state", "output", "protection", "snapshot", "trigger-list", "software-sequence") }).Count -gt 0
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:CleanupEvidence = New-CleanupEvidence -ValidationMode "planned"
$script:TriggerEvidence = New-TriggerEvidence
$script:ExternalPreflight = [pscustomobject]@{ status = "not_run" }
$startedAt = Get-Date

Ensure-ArtifactDirectories
try {
    Load-CoreSupportPolicyInventory
    $script:PlannedLiveCases = @(Get-SuiteCases -Model $NormalizedTarget -Suites $SuitesToRun -Live:$true)
    Resolve-ValidationSupportPolicy -LiveCases $script:PlannedLiveCases
}
catch {
    $script:Failures.Add("Validation support-policy resolution failed: $($_.Exception.Message)")
    Write-ValidationArtifacts -ValidationMode "preflight_failed" -Result "preflight_failed" -StartedAt $startedAt
    Write-Error "Core validation support-policy resolution failed before VISA access."
    exit 1
}
$externalPreflightExit = 0
if ($SkipExternalPreflight) {
    Write-Host "External no-hardware CLI preflight was completed by the release caller."
    $script:ExternalPreflight = [pscustomobject]@{
        status = "skipped_by_caller_after_release_preflight"
    }
}
else {
    $externalPreflightRoot = Join-Path $script:PrivateArtifactDir "external_preflight"
    $externalPreflightStdout = Join-Path $script:PrivateArtifactDir "external_preflight.stdout.txt"
    $externalPreflightStderr = Join-Path $script:PrivateArtifactDir "external_preflight.stderr.txt"
    Write-Host "Running external no-hardware CLI preflight for $NormalizedTarget..."
    $oldErrorActionPreference = $ErrorActionPreference
    $nativePreferenceVariable = Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    $hadNativePreference = $null -ne $nativePreferenceVariable
    $oldNativePreference = $null
    try {
        $ErrorActionPreference = "Continue"
        if ($hadNativePreference) {
            $oldNativePreference = [bool]$nativePreferenceVariable.Value
            $PSNativeCommandUseErrorActionPreference = $false
        }
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $PreflightScript -Target $NormalizedTarget -OutputRoot $externalPreflightRoot 1> $externalPreflightStdout 2> $externalPreflightStderr
        $externalPreflightExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldErrorActionPreference
        if ($hadNativePreference) { $PSNativeCommandUseErrorActionPreference = $oldNativePreference }
    }
    $externalReportPath = @(Get-ChildItem -LiteralPath $externalPreflightRoot -Filter report.json -File -Recurse -ErrorAction SilentlyContinue | Sort-Object { $_.FullName.Length } | Select-Object -First 1)
    $script:ExternalPreflight = [pscustomobject]@{
        status = if ($externalPreflightExit -eq 0) { "passed" } else { "failed" }
        exit_code = $externalPreflightExit
        output_root = ConvertTo-RepoRelativePath -Path $externalPreflightRoot
        report = if ($externalReportPath.Count -eq 1) { ConvertTo-RepoRelativePath -Path $externalReportPath[0].FullName } else { $null }
        stdout = ConvertTo-RepoRelativePath -Path $externalPreflightStdout
        stderr = ConvertTo-RepoRelativePath -Path $externalPreflightStderr
    }
}
if ($externalPreflightExit -ne 0) {
    $script:Failures.Add("External preflight-cli.ps1 failed before live resource access.")
    Write-ValidationArtifacts -ValidationMode "preflight_failed" -Result "preflight_failed" -StartedAt $startedAt
    Write-Error "External preflight failed; no VISA resource was opened. See $(ConvertTo-RepoRelativePath -Path (Join-Path $script:ShareableArtifactDir 'report.json'))."
    exit 1
}

Write-Host "Running selected-suite no-hardware plans for $NormalizedTarget suite '$Suite'..."
$preflightCases = Get-SuiteCases -Model $NormalizedTarget -Suites $SuitesToRun -Live:$false
foreach ($case in $preflightCases) {
    try {
        Invoke-ValidationCommand -Case $case | Out-Null
    }
    catch {
        $script:Failures.Add("$($case.name) could not be prepared: $($_.Exception.Message)")
        break
    }
}
try {
    Assert-CandidateScopeInventory -Model $NormalizedTarget -LiveCases $script:PlannedLiveCases -RequireComplete:($Suite -eq "full")
}
catch {
    $script:Failures.Add("Candidate scope inventory invariant failed: $($_.Exception.Message)")
}

if ($script:Failures.Count -gt 0) {
    Write-ValidationArtifacts -ValidationMode "preflight_failed" -Result "preflight_failed" -StartedAt $startedAt
    Write-Error "Preflight failed. See $(ConvertTo-RepoRelativePath -Path (Join-Path $script:ShareableArtifactDir 'report.json'))."
    exit 1
}

if ($PlanOnly) {
    Write-ValidationArtifacts -ValidationMode "planned" -Result "planned" -StartedAt $startedAt
    Write-Host "Plan-only validation passed."
    Write-Host "Report: $(ConvertTo-RepoRelativePath -Path (Join-Path $script:ShareableArtifactDir 'report.json'))"
    Write-Host "Summary: $(ConvertTo-RepoRelativePath -Path (Join-Path $script:ShareableArtifactDir 'summary.md'))"
    exit 0
}

if ([Console]::IsInputRedirected) {
    $script:Failures.Add("Interactive confirmation is required before opening VISA; stdin is redirected.")
    Write-ValidationArtifacts -ValidationMode "confirmation_required" -Result "confirmation_required" -StartedAt $startedAt
    Write-Error "Interactive confirmation is required before live execution. Re-run from an interactive PowerShell session, or use -PlanOnly."
    exit 2
}

Write-Host ""
Write-Host "Live suite validation is ready to open VISA and send SCPI."
Write-Host "Target: $NormalizedTarget"
Write-Host "Connection: $ConnectionLabel"
Write-Host "Resource: $Resource"
if (-not [string]::IsNullOrWhiteSpace($Backend)) {
    Write-Host "Backend: $Backend"
}
Write-Host "Suites: $($SuitesToRun -join ', ')"
Write-Host ""
Write-LiveConfirmationWarnings -SuitesToRun $SuitesToRun
if ($NormalizedTarget -eq "keysight-e3646a") {
    Write-Host "- E3646A OUTP ON/OFF is global, not independent per-channel relay behavior."
    Write-Host "- E3646A ramp-list and sequence are software workflows, not native LIST."
}
Write-Host ""
Write-Host "Physical checks before pressing Enter:"
Write-Host "- Confirm this is the target $NormalizedTarget and the explicit $ConnectionLabel resource is expected."
Write-Host "- Confirm no DUT is connected, or only known safe loads, for state-changing suites."
Write-Host "- Confirm output indicators are currently OFF before state-changing suites."
Write-Host "- Confirm no OVP/OCP/error/protection abnormal indicators are shown."
Write-Host ""
Read-Host "Press Enter to run live suite validation, or press Ctrl+C to abort"

$liveCases = Get-SuiteCases -Model $NormalizedTarget -Suites $SuitesToRun -Live:$true
try {
    foreach ($case in $liveCases) {
        if ($case.name -eq "trigger-fire-candidate") {
            Invoke-TriggerFireCandidateCase -Case $case
        }
        elseif ($case.name -eq "trigger-pulse-candidate") {
            Invoke-TriggerPulseCandidateCase -Case $case
        }
        else {
            Invoke-ValidationCommand -Case $case | Out-Null
        }
        if ($script:Failures.Count -gt 0) {
            break
        }
    }
}
catch {
    $script:Failures.Add("Live suite execution was interrupted or failed: $($_.Exception.Message)")
}
finally {
    if ($script:StateChanging) {
        $cleanupRole = if ($script:Failures.Count -gt 0) { "failure" } else { "final" }
        Invoke-SafeOffCleanup -Role $cleanupRole
    }
}

if ($script:Failures.Count -gt 0) {
    Write-ValidationArtifacts -ValidationMode "live" -Result "failed" -StartedAt $startedAt
    Write-Error "Live validation failed. See $(ConvertTo-RepoRelativePath -Path (Join-Path $script:ShareableArtifactDir 'report.json'))."
    exit 1
}

$liveResult = if ($script:StateChanging -and -not $Restore) { "passed_without_cleanup_verification" } else { "passed" }
Write-ValidationArtifacts -ValidationMode "live" -Result $liveResult -StartedAt $startedAt
if ($liveResult -eq "passed") {
    Write-Host "Live validation passed."
}
else {
    Write-Host "Live validation completed without cleanup verification because -Restore:`$false was selected."
}
Write-Host "Report: $(ConvertTo-RepoRelativePath -Path (Join-Path $script:ShareableArtifactDir 'report.json'))"
Write-Host "Summary: $(ConvertTo-RepoRelativePath -Path (Join-Path $script:ShareableArtifactDir 'summary.md'))"
