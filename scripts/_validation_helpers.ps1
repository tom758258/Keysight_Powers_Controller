Set-StrictMode -Version Latest

$script:ValidationTargetProfiles = [ordered]@{
    "keysight-e36312a" = [pscustomobject]@{
        model_id = "keysight-e36312a"
        vendor_id = "keysight"
        model = "E36312A"
        model_name = "E36312A"
        reported_manufacturer_aliases = @("KEYSIGHT", "KEYSIGHT TECHNOLOGIES")
        canonical_display_name = "Keysight E36312A"
        channels = @(1, 2, 3)
        simulator_resource = "USB0::SIM::E36312A::INSTR"
        suites = @("readonly", "output", "protection", "snapshot", "trigger-list", "software-sequence")
        preflight_capability_expectations = [ordered]@{
            "data.channels" = @(1, 2, 3)
            "data.resource.interface" = "USB"
            "data.command_support.snapshot.simulate" = $true
            "data.command_support.trigger-list.dry_run" = $true
        }
    }
    "keysight-edu36311a" = [pscustomobject]@{
        model_id = "keysight-edu36311a"
        vendor_id = "keysight"
        model = "EDU36311A"
        model_name = "EDU36311A"
        reported_manufacturer_aliases = @("KEYSIGHT", "KEYSIGHT TECHNOLOGIES")
        canonical_display_name = "Keysight EDU36311A"
        channels = @(1, 2, 3)
        simulator_resource = "USB0::SIM::EDU36311A::INSTR"
        suites = @("readonly", "output", "protection", "software-sequence")
        preflight_capability_expectations = [ordered]@{
            "data.channels" = @(1, 2, 3)
            "data.resource.interface" = "USB"
            "data.command_support.protection-status.simulate" = $true
            "data.command_support.snapshot.simulate" = $false
        }
    }
    "keysight-e3646a" = [pscustomobject]@{
        model_id = "keysight-e3646a"
        vendor_id = "keysight"
        model = "E3646A"
        model_name = "E3646A"
        reported_manufacturer_aliases = @("KEYSIGHT", "KEYSIGHT TECHNOLOGIES", "Agilent Technologies")
        canonical_display_name = "Keysight E3646A"
        channels = @(1, 2)
        simulator_resource = "ASRL1::SIM::E3646A::INSTR"
        suites = @("readonly", "output", "software-sequence")
        preflight_capability_expectations = [ordered]@{
            "data.channels" = @(1, 2)
            "data.resource.interface" = "ASRL"
            "data.command_support.output-on.simulate" = $true
            "data.command_support.protection-status.simulate" = $false
        }
    }
    "gw-instek-psm-2010" = [pscustomobject]@{
        model_id = "gw-instek-psm-2010"
        vendor_id = "gw-instek"
        model = "PSM-2010"
        model_name = "PSM-2010"
        reported_manufacturer_aliases = @("GW.Inc")
        canonical_display_name = "GW Instek PSM-2010"
        channels = @(1)
        simulator_resource = "ASRL1::SIM::PSM2010::INSTR"
        suites = @("readonly", "safe-state", "output", "protection", "snapshot", "software-sequence")
        preflight_capability_expectations = [ordered]@{
            "data.channels" = @(1)
            "data.resource.interface" = "ASRL"
            "data.command_support.output-off.dry_run" = $true
            "data.command_support.set.simulate" = $true
            "data.command_support.protection-status.simulate" = $true
            "data.command_support.snapshot.simulate" = $true
        }
    }
}

$script:ValidationDeepRepresentativeTargets = @(
    "keysight-e36312a",
    "keysight-e3646a"
)

function Get-ValidationTargetProfiles {
    $seen = @{}
    foreach ($profile in $script:ValidationTargetProfiles.Values) {
        if ([string]::IsNullOrWhiteSpace([string]$profile.model_id)) {
            throw "Validation target model_id must not be empty."
        }
        if ($profile.model_id -cne $profile.model_id.ToLowerInvariant()) {
            throw "Validation target model_id must be lowercase: '$($profile.model_id)'."
        }
        if ($seen.ContainsKey($profile.model_id)) {
            throw "Duplicate validation target model_id '$($profile.model_id)'."
        }
        if (@($profile.reported_manufacturer_aliases).Count -eq 0) {
            throw "Validation target reported_manufacturer_aliases must not be empty: '$($profile.model_id)'."
        }
        foreach ($alias in @($profile.reported_manufacturer_aliases)) {
            if ($alias -isnot [string] -or [string]::IsNullOrWhiteSpace($alias)) {
                throw "Validation target reported_manufacturer_aliases contains an invalid value: '$($profile.model_id)'."
            }
        }
        if ([string]::IsNullOrWhiteSpace([string]$profile.canonical_display_name)) {
            throw "Validation target canonical_display_name must not be empty: '$($profile.model_id)'."
        }
        $seen[$profile.model_id] = $true
    }
    return @($script:ValidationTargetProfiles.Values)
}

function Get-SupportedTargetModelIds {
    return @(Get-ValidationTargetProfiles | ForEach-Object { $_.model_id })
}

function Get-ValidationDeepRepresentativeTargetIds {
    return @($script:ValidationDeepRepresentativeTargets)
}

function Resolve-ValidationSuite {
    param([AllowNull()][AllowEmptyString()][string]$Suite = "full")

    if ([string]::IsNullOrWhiteSpace($Suite)) {
        $Suite = "full"
    }
    $normalized = $Suite.Trim().ToLowerInvariant()
    if ($normalized -notin @("smoke", "deep", "full")) {
        throw "Unsupported preflight suite '$Suite'. Use smoke, deep, or full."
    }
    return $normalized
}

function Resolve-ValidationTargets {
    param([AllowNull()][AllowEmptyString()][string]$Target = "all")

    if ([string]::IsNullOrWhiteSpace($Target)) {
        $Target = "all"
    }
    $normalized = $Target.Trim().ToLowerInvariant()
    if ($normalized -eq "all") {
        return @(Get-SupportedTargetModelIds)
    }
    $supported = @(Get-SupportedTargetModelIds)
    if ($normalized -notin $supported) {
        throw "Unsupported target '$Target'. Use all or one of: $($supported -join ', ')."
    }
    return @($normalized)
}

function Resolve-ValidationTarget {
    param([AllowNull()][AllowEmptyString()][string]$Target)

    $targets = @(Resolve-ValidationTargets -Target $Target)
    if ($targets.Count -ne 1) {
        throw "A single canonical target is required."
    }
    return $targets[0]
}

function Resolve-ValidationPreflightTargets {
    param(
        [AllowNull()][AllowEmptyString()][string]$Target = "all",
        [AllowNull()][AllowEmptyString()][string]$Suite = "full"
    )

    $resolvedSuite = Resolve-ValidationSuite -Suite $Suite
    $targets = @(Resolve-ValidationTargets -Target $Target)
    if ($resolvedSuite -ne "deep") {
        return $targets
    }
    $representatives = @(Get-ValidationDeepRepresentativeTargetIds)
    $normalizedTarget = if ([string]::IsNullOrWhiteSpace($Target)) {
        "all"
    } else {
        $Target.Trim().ToLowerInvariant()
    }
    if ($normalizedTarget -eq "all") {
        return $representatives
    }
    if ($targets[0] -notin $representatives) {
        throw "Target '$($targets[0])' is not a deep preflight representative. Use all or one of: $($representatives -join ', ')."
    }
    return $targets
}

function Get-ValidationTargetProfile {
    param([Parameter(Mandatory = $true)][string]$Target)

    $resolved = Resolve-ValidationTarget -Target $Target
    return $script:ValidationTargetProfiles[$resolved]
}

function Get-ValidationSupportedSuites {
    param([Parameter(Mandatory = $true)][string]$Target)
    return @((Get-ValidationTargetProfile -Target $Target).suites)
}

function New-PreflightCommandCase {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateSet("smoke", "deep")][string]$Suite,
        [Parameter(Mandatory = $true)][string]$Category,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][ValidateSet("dry-run", "simulate")][string]$Mode,
        [string]$ExpectedPath,
        [AllowNull()]$ExpectedValue,
        [System.Collections.IDictionary]$ExpectedValues = [ordered]@{}
    )
    return [pscustomobject]@{
        name = $Name
        suite = $Suite
        category = $Category
        command = $Command
        arguments = $Arguments
        mode = $Mode
        expected_path = $ExpectedPath
        expected_value = $ExpectedValue
        expected_values = $ExpectedValues
    }
}

function Get-ValidationPreflightCases {
    param(
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$ArtifactDirectory,
        [Parameter(Mandatory = $true)][string]$SequencePath,
        [AllowNull()][AllowEmptyString()][string]$Suite = "full"
    )

    $resolvedSuite = Resolve-ValidationSuite -Suite $Suite
    $profile = Get-ValidationTargetProfile -Target $Target
    $model = $profile.model_id
    $resource = $profile.simulator_resource
    $cases = [System.Collections.Generic.List[object]]::new()
    $cases.Add((New-PreflightCommandCase -Name "list-resources-simulate" -Suite "deep" -Category "resource-planning" -Command "list-resources" -Arguments @("list-resources", "--simulate", "--json") -Mode "simulate" -ExpectedPath "data.count" -ExpectedValue 4))
    $cases.Add((New-PreflightCommandCase -Name "identify-simulate" -Suite "smoke" -Category "identity" -Command "identify" -Arguments @("identify", "--simulate", "--json", "--resource", $resource) -Mode "simulate" -ExpectedPath "data.idn.model" -ExpectedValue $profile.model))
    $cases.Add((New-PreflightCommandCase -Name "verify-simulate" -Suite "deep" -Category "identity" -Command "verify" -Arguments @("verify", "--simulate", "--json", "--resource", $resource) -Mode "simulate"))
    $cases.Add((New-PreflightCommandCase -Name "capabilities-simulate" -Suite "smoke" -Category "metadata" -Command "capabilities" -Arguments @("capabilities", "--simulate", "--json", "--resource", $resource) -Mode "simulate" -ExpectedPath "data.resource.model_id" -ExpectedValue $model -ExpectedValues $profile.preflight_capability_expectations))
    $cases.Add((New-PreflightCommandCase -Name "measure-ch1-simulate" -Suite "smoke" -Category "readonly" -Command "measure" -Arguments @("measure", "--simulate", "--json", "--resource", $resource, "--channel", "1") -Mode "simulate"))
    if ($model -eq "gw-instek-psm-2010") {
        $cases.Add((New-PreflightCommandCase -Name "output-state-ch1-simulate" -Suite "smoke" -Category "readonly" -Command "output-state" -Arguments @("output-state", "--simulate", "--json", "--resource", $resource, "--channel", "1") -Mode "simulate" -ExpectedPath "data.plan.target.planning_model_id" -ExpectedValue $model))
    }
    $cases.Add((New-PreflightCommandCase -Name "readback-simulate" -Suite "deep" -Category "readonly" -Command "readback" -Arguments @("readback", "--simulate", "--json", "--resource", $resource, "--all") -Mode "simulate"))
    if ($model -eq "gw-instek-psm-2010") {
        $cases.Add((New-PreflightCommandCase -Name "read-status-simulate" -Suite "deep" -Category "readonly" -Command "read-status" -Arguments @("read-status", "--simulate", "--json", "--resource", $resource, "--all") -Mode "simulate"))
    }
    $cases.Add((New-PreflightCommandCase -Name "error-simulate" -Suite "deep" -Category "diagnostics" -Command "error" -Arguments @("error", "--simulate", "--json", "--resource", $resource, "--max-reads", "2") -Mode "simulate" -ExpectedPath "data.read_count" -ExpectedValue 1))
    if ("output" -in $profile.suites) {
        $cases.Add((New-PreflightCommandCase -Name "set-dry-run" -Suite "smoke" -Category "output" -Command "set" -Arguments @("set", "--dry-run", "--json", "--model", $model, "--channel", "1", "--voltage", "1", "--current", "0.05") -Mode "dry-run" -ExpectedPath "data.plan.target.planning_model_id" -ExpectedValue $model))
    }
    if ($model -eq "gw-instek-psm-2010") {
        $cases.Add((New-PreflightCommandCase -Name "output-off-simulate" -Suite "deep" -Category "safe-off" -Command "output-off" -Arguments @("output-off", "--simulate", "--json", "--resource", $resource, "--channel", "all") -Mode "simulate" -ExpectedPath "data.plan.target.planning_model_id" -ExpectedValue $model))
        $cases.Add((New-PreflightCommandCase -Name "safe-off-simulate" -Suite "deep" -Category "safe-off" -Command "safe-off" -Arguments @("safe-off", "--simulate", "--json", "--resource", $resource, "--channel", "all") -Mode "simulate" -ExpectedPath "data.plan.target.planning_model_id" -ExpectedValue $model))
        $cases.Add((New-PreflightCommandCase -Name "output-state-dry-run" -Suite "deep" -Category "readonly" -Command "output-state" -Arguments @("output-state", "--dry-run", "--json", "--model", $model, "--channel", "1") -Mode "dry-run" -ExpectedPath "data.plan.target.planning_model_id" -ExpectedValue $model))
        $cases.Add((New-PreflightCommandCase -Name "output-off-dry-run" -Suite "deep" -Category "safe-off" -Command "output-off" -Arguments @("output-off", "--dry-run", "--json", "--model", $model, "--channel", "all") -Mode "dry-run" -ExpectedPath "data.plan.target.planning_model_id" -ExpectedValue $model))
    }
    if ("output" -in $profile.suites -or $model -eq "gw-instek-psm-2010") {
        $cases.Add((New-PreflightCommandCase -Name "safe-off-dry-run" -Suite "deep" -Category "safe-off" -Command "safe-off" -Arguments @("safe-off", "--dry-run", "--json", "--model", $model, "--channel", "all") -Mode "dry-run" -ExpectedPath "data.plan.target.planning_model_id" -ExpectedValue $model))
    }
    if ("software-sequence" -in $profile.suites) {
        $cases.Add((New-PreflightCommandCase -Name "ramp-list-dry-run" -Suite "deep" -Category "software-sequence" -Command "ramp-list" -Arguments @("ramp-list", "--dry-run", "--json", "--model", $model, "--segment", "1", "0.05", "0", "1", "0.25", "100", "0") -Mode "dry-run"))
        $cases.Add((New-PreflightCommandCase -Name "sequence-dry-run" -Suite "deep" -Category "software-sequence" -Command "sequence" -Arguments @("sequence", "--dry-run", "--json", "--model", $model, "--resource", $resource, "--file", $SequencePath) -Mode "dry-run"))
    }

    if ("protection" -in $profile.suites) {
        $cases.Add((New-PreflightCommandCase -Name "protection-status-simulate" -Suite "deep" -Category "protection" -Command "protection-status" -Arguments @("protection-status", "--simulate", "--json", "--resource", $resource, "--all") -Mode "simulate"))
        $cases.Add((New-PreflightCommandCase -Name "protection-set-dry-run" -Suite "deep" -Category "protection" -Command "protection-set" -Arguments @("protection-set", "--dry-run", "--json", "--resource", $resource, "--channel", "all", "--ovp-voltage", "5", "--ocp", "on", "--confirm") -Mode "dry-run"))
    }
    if ("snapshot" -in $profile.suites) {
        $snapshotPath = Join-Path $ArtifactDirectory "snapshot.json"
        $cases.Add((New-PreflightCommandCase -Name "snapshot-simulate" -Suite "deep" -Category "snapshot" -Command "snapshot" -Arguments @("snapshot", "--simulate", "--json", "--resource", $resource, "--snapshot-json", $snapshotPath) -Mode "simulate"))
    }
    if ("trigger-list" -in $profile.suites) {
        $cases.Add((New-PreflightCommandCase -Name "trigger-status-simulate" -Suite "deep" -Category "trigger-list" -Command "trigger-status" -Arguments @("trigger-status", "--simulate", "--json", "--resource", $resource, "--channel", "1") -Mode "simulate"))
        $cases.Add((New-PreflightCommandCase -Name "trigger-step-dry-run" -Suite "deep" -Category "trigger-list" -Command "trigger-step" -Arguments @("trigger-step", "--dry-run", "--json", "--model", $model, "--channel", "1", "--source", "bus", "--fire") -Mode "dry-run"))
    }
    if ($resolvedSuite -eq "full") {
        return $cases.ToArray()
    }
    return @($cases | Where-Object { $_.suite -eq $resolvedSuite })
}
