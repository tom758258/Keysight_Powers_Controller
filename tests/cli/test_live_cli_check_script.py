import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from powers_tool_cli import cli
from powers_tool_core.identity import PHYSICAL_MODELS, VENDORS
from powers_tool_core.support_evidence import SUPPORT_EVIDENCE_MANIFEST


SCRIPT = Path("scripts/live-cli-check.ps1")


def _powershell() -> str:
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if executable is None:
        pytest.skip("PowerShell is required for live-cli-check.ps1 tests")
    return executable


def _run_live_cli_check(
    *args: str, env: dict[str, str] | None = None, stdin_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            *args,
        ],
        check=False,
        cwd=Path.cwd(),
        env=process_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        input=stdin_text,
        timeout=180,
    )


def _run_powershell_command(command: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        check=False,
        cwd=Path.cwd(),
        env=process_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
    )


@pytest.mark.parametrize(
    ("data", "expected_channels", "valid"),
    [
        ({"output_enabled": True}, [1], True),
        ({"output_enabled": False}, [1], True),
        ({"outputs": [{"channel": 1, "enabled": True}]}, [1], True),
        ({"outputs": None, "output_enabled": True}, [1], False),
        ({"outputs": "bad"}, [1], False),
        ({"outputs": {"channel": 1, "enabled": True}}, [1], False),
        ({"outputs": []}, [1], False),
        ({"outputs": [None]}, [1], False),
        ({"outputs": [{"channel": 1}]}, [1], False),
        ({"outputs": [{"channel": "1", "enabled": True}]}, [1], False),
        ({"outputs": [{"channel": True, "enabled": True}]}, [1], False),
        ({"outputs": [{"channel": 1.5, "enabled": True}]}, [1], False),
        ({"outputs": [{"channel": 0, "enabled": True}]}, [1], False),
        ({"outputs": [{"channel": 1, "enabled": "false"}]}, [1], False),
        ({"outputs": [{"channel": 1, "enabled": False}, {"channel": 1, "enabled": False}]}, [1], False),
        ({"outputs": [{"channel": 2, "enabled": False}]}, [1], False),
        ({"outputs": [{"channel": 1, "enabled": False}]}, [1, 2], False),
        ({"output": {"enabled": False}}, [1], False),
        ({"outputs": [{"channel": 1, "enabled": False}], "output_enabled": True}, [1], True),
    ],
)
def test_live_cli_check_strictly_normalizes_output_state_evidence(data, expected_channels, valid):
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$data = @'
{json.dumps(data)}
'@ | ConvertFrom-Json
$result = Normalize-OutputStateEvidence -Data $data -ExpectedChannels @({','.join(map(str, expected_channels))})
$result | ConvertTo-Json -Depth 10 -Compress
'''
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    normalized = json.loads(result.stdout.strip())
    failures = normalized["failures"] if isinstance(normalized["failures"], list) else [normalized["failures"]]
    assert (len(failures) == 0) is valid
    if valid:
        records = normalized["records"] if isinstance(normalized["records"], list) else [normalized["records"]]
        assert records == [{"channel": 1, "enabled": data.get("outputs", [{}])[0].get("enabled", data.get("output_enabled"))}]


REPORTED_E36312A_IDENTITY = {
    "manufacturer": "Keysight Technologies",
    "model": "E36312A",
    "serial": "SN",
    "firmware": "2.10",
    "parse_ok": True,
}
RESOLVED_E36312A_IDENTITY = {
    "vendor_id": "keysight",
    "model_id": "keysight-e36312a",
    "model_name": "E36312A",
    "display_name": "Keysight E36312A",
}


def _reported_identity(manufacturer: str, model: str) -> dict[str, object]:
    return {
        "manufacturer": manufacturer,
        "model": model,
        "serial": "SN",
        "firmware": "2.10",
        "parse_ok": True,
    }


def _resolved_identity(model_id: str, model_name: str, display_name: str) -> dict[str, str]:
    return {
        "vendor_id": "keysight",
        "model_id": model_id,
        "model_name": model_name,
        "display_name": display_name,
    }


def _normalize_observed_identity(
    target: str, command_name: str, data: object
) -> dict[str, object]:
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$data = @'
{json.dumps(data)}
'@ | ConvertFrom-Json
$profile = $script:ValidationTargetProfiles["{target}"]
$result = Normalize-ObservedIdentityEvidence -Data $data -Command "{command_name}" -TargetProfile $profile
$result | ConvertTo-Json -Depth 10 -Compress
'''
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip())


def _normalization_succeeded(result: dict[str, object]) -> bool:
    failures = result["failures"]
    if not isinstance(failures, list):
        failures = [failures]
    return len(failures) == 0


def test_live_cli_check_identity_metadata_matches_core_frozen_registry() -> None:
    command = r'''
. .\scripts\_validation_helpers.ps1
@($script:ValidationTargetProfiles.Values | ForEach-Object {
    [pscustomobject]@{
        model_id = $_.model_id
        reported_manufacturer_aliases = @($_.reported_manufacturer_aliases)
        canonical_display_name = $_.canonical_display_name
    }
}) | ConvertTo-Json -Depth 5 -Compress
'''
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    profiles = {item["model_id"]: item for item in json.loads(result.stdout)}
    vendors = {vendor.vendor_id: vendor for vendor in VENDORS}
    models = {model.model_id: model for model in PHYSICAL_MODELS}
    assert set(profiles) == {
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e3646a",
    }
    for model_id, profile in profiles.items():
        model = models[model_id]
        vendor = vendors[model.vendor_id]
        assert profile["reported_manufacturer_aliases"] == [
            vendor.canonical_manufacturer,
            *vendor.manufacturer_aliases,
            *model.manufacturer_aliases,
        ]
        assert profile["canonical_display_name"] == model.display_name


@pytest.mark.parametrize("command_name", ["snapshot", "restore-from-snapshot"])
@pytest.mark.parametrize(
    ("target", "manufacturer", "model", "resolved", "valid"),
    [
        (
            "keysight-e36312a",
            "ＫＥＹＳＩＧＨＴ",
            " e36312a ",
            _resolved_identity("keysight-e36312a", "E36312A", "Keysight E36312A"),
            True,
        ),
        (
            "keysight-edu36311a",
            "  Keysight   Technologies  ",
            " edu36311a ",
            _resolved_identity("keysight-edu36311a", "EDU36311A", "Keysight EDU36311A"),
            True,
        ),
        (
            "keysight-e3646a",
            "KEYSIGHT",
            "E3646A",
            _resolved_identity("keysight-e3646a", "E3646A", "Keysight E3646A"),
            True,
        ),
        (
            "keysight-e3646a",
            "Agilent Technologies",
            "E3646A",
            _resolved_identity("keysight-e3646a", "E3646A", "Keysight E3646A"),
            True,
        ),
        (
            "keysight-e36312a",
            "Agilent Technologies",
            "E36312A",
            _resolved_identity("keysight-e36312a", "E36312A", "Keysight E36312A"),
            False,
        ),
        (
            "keysight-edu36311a",
            "Agilent Technologies",
            "EDU36311A",
            _resolved_identity("keysight-edu36311a", "EDU36311A", "Keysight EDU36311A"),
            False,
        ),
        (
            "keysight-e36312a",
            "Keysight-Technologies",
            "E36312A",
            _resolved_identity("keysight-e36312a", "E36312A", "Keysight E36312A"),
            False,
        ),
        (
            "keysight-e36312a",
            "Keysight Technologies, Inc.",
            "E36312A",
            _resolved_identity("keysight-e36312a", "E36312A", "Keysight E36312A"),
            False,
        ),
    ],
)
def test_snapshot_restore_identity_uses_core_normalization_and_model_specific_aliases(
    command_name, target, manufacturer, model, resolved, valid
):
    normalized = _normalize_observed_identity(
        target,
        command_name,
        {
            "reported_identity": _reported_identity(manufacturer, model),
            "resolved_identity": resolved,
        },
    )

    assert _normalization_succeeded(normalized) is valid


@pytest.mark.parametrize("command_name", ["snapshot", "restore-from-snapshot"])
@pytest.mark.parametrize(
    "data",
    [
        {
            "reported_identity": {**REPORTED_E36312A_IDENTITY, "raw": "raw-idn"},
            "resolved_identity": RESOLVED_E36312A_IDENTITY,
        },
        {
            "reported_identity": {**REPORTED_E36312A_IDENTITY, "extra": "unexpected"},
            "resolved_identity": RESOLVED_E36312A_IDENTITY,
        },
        {
            "reported_identity": {
                "Manufacturer": REPORTED_E36312A_IDENTITY["manufacturer"],
                **{
                    key: value
                    for key, value in REPORTED_E36312A_IDENTITY.items()
                    if key != "manufacturer"
                },
            },
            "resolved_identity": RESOLVED_E36312A_IDENTITY,
        },
        {
            "reported_identity": REPORTED_E36312A_IDENTITY,
            "resolved_identity": {**RESOLVED_E36312A_IDENTITY, "extra": "unexpected"},
        },
        {
            "reported_identity": REPORTED_E36312A_IDENTITY,
            "resolved_identity": {
                "Display_Name": RESOLVED_E36312A_IDENTITY["display_name"],
                **{
                    key: value
                    for key, value in RESOLVED_E36312A_IDENTITY.items()
                    if key != "display_name"
                },
            },
        },
        {
            "reported_identity": REPORTED_E36312A_IDENTITY,
            "resolved_identity": {
                **RESOLVED_E36312A_IDENTITY,
                "display_name": "Keysight Technologies E36312A",
            },
        },
        {
            "reported_identity": _reported_identity("Agilent Technologies", "E3646A"),
            "resolved_identity": RESOLVED_E36312A_IDENTITY,
        },
    ],
)
def test_snapshot_restore_identity_rejects_non_allowlisted_or_conflicting_fields(
    command_name, data
):
    normalized = _normalize_observed_identity("keysight-e36312a", command_name, data)

    assert _normalization_succeeded(normalized) is False


@pytest.mark.parametrize(
    ("command_name", "data", "valid"),
    [
        ("measure-all", {"idn": REPORTED_E36312A_IDENTITY}, True),
        ("output-state", {"resource": {"idn": {**REPORTED_E36312A_IDENTITY, "raw": "Keysight Technologies,E36312A,SN,2.10"}}}, True),
        ("measure-all", {"idn": "Keysight Technologies,E36312A,SN,2.10"}, False),
        ("measure-all", {"idn": None}, False),
        ("measure-all", {"idn": []}, False),
        (
            "measure-all",
            {"resource": {"idn": None}, "idn": REPORTED_E36312A_IDENTITY},
            True,
        ),
        (
            "measure-all",
            {"resource": {"idn": REPORTED_E36312A_IDENTITY}, "idn": None},
            True,
        ),
        (
            "measure-all",
            {"resource": {"idn": REPORTED_E36312A_IDENTITY}, "idn": REPORTED_E36312A_IDENTITY},
            False,
        ),
        (
            "measure-all",
            {
                "resource": {"idn": "bad"},
                "idn": REPORTED_E36312A_IDENTITY,
            },
            False,
        ),
        ("snapshot", {"reported_identity": REPORTED_E36312A_IDENTITY, "resolved_identity": RESOLVED_E36312A_IDENTITY}, True),
        ("restore-from-snapshot", {"reported_identity": REPORTED_E36312A_IDENTITY, "resolved_identity": RESOLVED_E36312A_IDENTITY}, True),
        ("snapshot", {}, False),
        ("snapshot", {"reported_identity": None, "resolved_identity": RESOLVED_E36312A_IDENTITY}, False),
        ("snapshot", {"reported_identity": REPORTED_E36312A_IDENTITY, "resolved_identity": None}, False),
        ("snapshot", {"reported_identity": "bad", "resolved_identity": RESOLVED_E36312A_IDENTITY}, False),
        ("snapshot", {"reported_identity": REPORTED_E36312A_IDENTITY, "resolved_identity": []}, False),
        ("snapshot", {"reported_identity": {key: value for key, value in REPORTED_E36312A_IDENTITY.items() if key != "model"}, "resolved_identity": RESOLVED_E36312A_IDENTITY}, False),
        ("snapshot", {"reported_identity": {**REPORTED_E36312A_IDENTITY, "parse_ok": "true"}, "resolved_identity": RESOLVED_E36312A_IDENTITY}, False),
        ("snapshot", {"reported_identity": REPORTED_E36312A_IDENTITY, "resolved_identity": {key: value for key, value in RESOLVED_E36312A_IDENTITY.items() if key != "model_id"}}, False),
        ("snapshot", {"reported_identity": {**REPORTED_E36312A_IDENTITY, "model": "EDU36311A"}, "resolved_identity": RESOLVED_E36312A_IDENTITY}, False),
        ("snapshot", {"reported_identity": REPORTED_E36312A_IDENTITY, "resolved_identity": {**RESOLVED_E36312A_IDENTITY, "model_id": "keysight-edu36311a"}}, False),
        ("snapshot", {"reported_identity": REPORTED_E36312A_IDENTITY, "resolved_identity": {**RESOLVED_E36312A_IDENTITY, "vendor_id": "other"}}, False),
        ("snapshot", {"reported_identity": REPORTED_E36312A_IDENTITY, "resolved_identity": {**RESOLVED_E36312A_IDENTITY, "model_name": "EDU36311A"}}, False),
        ("snapshot", {"idn": REPORTED_E36312A_IDENTITY}, False),
    ],
)
def test_live_cli_check_strictly_normalizes_observed_identity_evidence(
    command_name, data, valid
):
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$data = @'
{json.dumps(data)}
'@ | ConvertFrom-Json
$profile = $script:ValidationTargetProfiles["keysight-e36312a"]
$result = Normalize-ObservedIdentityEvidence -Data $data -Command "{command_name}" -TargetProfile $profile
$result | ConvertTo-Json -Depth 10 -Compress
'''
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    normalized = json.loads(result.stdout.strip())
    failures = normalized["failures"] if isinstance(normalized["failures"], list) else [normalized["failures"]]
    assert (len(failures) == 0) is valid
    if valid:
        assert normalized["identity"]["model"] == "E36312A"


def _observed_identity_fixture_cli_path(tmp_path: Path, data: object) -> Path:
    fixture_cli = tmp_path / "powers_tool_cli"
    fixture_cli.mkdir()
    (fixture_cli / "__init__.py").write_text("", encoding="utf-8")
    (fixture_cli / "cli.py").write_text(
        f"""
import json
import sys

payload = {{
    "ok": True,
    "error": None,
    "execution": {{"mode": "real", "dry_run": False, "hardware_touched": True}},
    "data": json.loads({json.dumps(json.dumps(data))}),
}}
save_path = sys.argv[sys.argv.index("--save-json") + 1]
with open(save_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
""".lstrip(),
        encoding="utf-8",
    )
    return tmp_path


def _invoke_optional_identity_case(
    tmp_path: Path, *, target: str, data: object
) -> dict[str, object]:
    fixture_path = _observed_identity_fixture_cli_path(tmp_path, data)
    output_dir = tmp_path / "out"
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "{target}"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "ASRL1::FIXTURE::INSTR"
$script:ResourceDisplay = "ASRL:<redacted-resource>"
$script:ConnectionLabel = "ASRL"
$script:TransportScope = "asrl"
$script:BackendArtifact = Get-BackendArtifactFields -Value $null
$script:BackendValue = $null
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:InstrumentIdentity = $null
$case = New-CommandCase -Name "optional-identity" -Suite "readonly" -Phase "live" -Args @("clear", "--json", "--resource", $script:RawResource) -LiveHardwareExpected:$true
$record = Invoke-ValidationCommand -Case $case
$record | ConvertTo-Json -Depth 10 -Compress
'''
    result = _run_powershell_command(command, env={"PYTHONPATH": str(fixture_path)})

    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip())


@pytest.mark.parametrize(
    ("data", "expected_result", "identity_observed"),
    [
        ({}, "passed", False),
        ({"idn": None}, "passed", False),
        ({"resource": {"idn": None}}, "passed", False),
        ({"resource": {"idn": None}, "idn": None}, "passed", False),
        (
            {"resource": {"idn": None}, "idn": REPORTED_E36312A_IDENTITY},
            "passed",
            True,
        ),
        (
            {"resource": {"idn": REPORTED_E36312A_IDENTITY}, "idn": None},
            "passed",
            True,
        ),
        ({"resource": {"idn": None}, "idn": "bad"}, "failed", False),
        ({"resource": {"idn": "bad"}, "idn": None}, "failed", False),
        ({"resource": {"idn": None}, "idn": []}, "failed", False),
        ({"resource": {"idn": []}, "idn": None}, "failed", False),
        (
            {
                "resource": {"idn": None},
                "idn": {
                    key: value
                    for key, value in REPORTED_E36312A_IDENTITY.items()
                    if key != "model"
                },
            },
            "failed",
            False,
        ),
        (
            {
                "resource": {"idn": REPORTED_E36312A_IDENTITY},
                "idn": REPORTED_E36312A_IDENTITY,
            },
            "failed",
            False,
        ),
        (
            {
                "resource": {"idn": REPORTED_E36312A_IDENTITY},
                "idn": {**REPORTED_E36312A_IDENTITY, "model": "EDU36311A"},
            },
            "failed",
            False,
        ),
        (
            {"resource": {"idn": "bad"}, "idn": REPORTED_E36312A_IDENTITY},
            "failed",
            False,
        ),
        (
            {"resource": {"idn": REPORTED_E36312A_IDENTITY}, "idn": []},
            "failed",
            False,
        ),
    ],
)
def test_optional_observed_identity_uses_exactly_one_non_null_path(
    tmp_path, data, expected_result, identity_observed
):
    record = _invoke_optional_identity_case(
        tmp_path, target="keysight-e36312a", data=data
    )

    assert record["result"] == expected_result
    assert record["identity_observed"] is identity_observed
    assert (record["assertion_failures"] == []) is (expected_result == "passed")
    resource = data.get("resource") if isinstance(data, dict) else None
    resource_idn = resource.get("idn") if isinstance(resource, dict) else None
    data_idn = data.get("idn") if isinstance(data, dict) else None
    if resource_idn is not None and data_idn is not None:
        assert record["assertion_failures"] == [
            "observed identity evidence contains ambiguous duplicate "
            "data.resource.idn and data.idn values."
        ]


@pytest.mark.parametrize(
    "target",
    ["keysight-e36312a", "keysight-edu36311a", "keysight-e3646a"],
)
def test_optional_null_identity_placeholder_is_absent_for_all_targets(
    tmp_path, target
):
    record = _invoke_optional_identity_case(
        tmp_path, target=target, data={"resource": {"idn": None}}
    )

    assert record["result"] == "passed"
    assert record["identity_observed"] is False
    assert record["assertion_failures"] == []


@pytest.mark.parametrize(
    ("command_name", "live_hardware_value", "data", "expected_result"),
    [
        ("snapshot", "$true", {}, "failed"),
        ("snapshot", "$true", None, "failed"),
        ("restore-from-snapshot", "$true", {}, "failed"),
        (
            "snapshot",
            "$true",
            {
                "reported_identity": REPORTED_E36312A_IDENTITY,
                "resolved_identity": RESOLVED_E36312A_IDENTITY,
            },
            "passed",
        ),
        (
            "restore-from-snapshot",
            "$true",
            {
                "reported_identity": {**REPORTED_E36312A_IDENTITY, "model": "EDU36311A"},
                "resolved_identity": RESOLVED_E36312A_IDENTITY,
            },
            "failed",
        ),
        ("snapshot", "$false", {}, "passed"),
        ("snapshot", "$null", {}, "passed"),
        ("snapshot", '"true"', {}, "passed"),
        ("restore-from-snapshot", "$false", {}, "passed"),
    ],
)
def test_snapshot_restore_identity_requirement_uses_exact_live_hardware_expected(
    tmp_path, command_name, live_hardware_value, data, expected_result
):
    fixture_path = _observed_identity_fixture_cli_path(tmp_path, data)
    output_dir = tmp_path / "out"
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "USB0::FIXTURE::INSTR"
$script:ResourceDisplay = "USB:<redacted-resource>"
$script:ConnectionLabel = "USB"
$script:TransportScope = "usb"
$script:BackendArtifact = Get-BackendArtifactFields -Value $null
$script:BackendValue = $null
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:InstrumentIdentity = $null
$case = New-CommandCase -Name "identity-case" -Suite "snapshot" -Phase "live" -Args @("{command_name}", "--json", "--resource", $script:RawResource)
$case.live_hardware_expected = {live_hardware_value}
$record = Invoke-ValidationCommand -Case $case
$record | ConvertTo-Json -Depth 10 -Compress
'''
    result = _run_powershell_command(command, env={"PYTHONPATH": str(fixture_path)})

    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(result.stdout.strip())
    assert record["result"] == expected_result
    assert record["identity_observed"] is (expected_result == "passed" and bool(data))


@pytest.mark.parametrize(
    ("identity_present", "identity", "expected_result", "identity_observed"),
    [
        (False, None, "passed", False),
        (True, REPORTED_E36312A_IDENTITY, "passed", True),
        (True, None, "passed", False),
        (True, "bad", "failed", False),
        (True, {**REPORTED_E36312A_IDENTITY, "model": "EDU36311A"}, "failed", False),
    ],
)
def test_snapshot_readback_allows_missing_identity_but_validates_present_evidence(
    tmp_path, identity_present, identity, expected_result, identity_observed
):
    channels = [
        {
            "channel": channel,
            "setpoints": {"voltage": 1.0, "current": 0.05},
        }
        for channel in (1, 2, 3)
    ]
    data = {"resource": "USB0::FIXTURE::INSTR", "channels": channels}
    if identity_present:
        data["idn"] = identity
    fixture_path = _observed_identity_fixture_cli_path(tmp_path, data)
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps({"readback": channels}), encoding="utf-8")
    output_dir = tmp_path / "out"
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "USB0::FIXTURE::INSTR"
$script:ResourceDisplay = "USB:<redacted-resource>"
$script:ConnectionLabel = "USB"
$script:TransportScope = "usb"
$script:BackendArtifact = Get-BackendArtifactFields -Value $null
$script:BackendValue = $null
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:InstrumentIdentity = $null
$case = New-CommandCase -Name "restore-on-readback" -Suite "snapshot" -Phase "live" -Args @("readback", "--json", "--resource", $script:RawResource, "--channel", "all") -LiveHardwareExpected:$true -ValidationKind "snapshot-readback" -ExpectedChannels @(1,2,3) -CompareSnapshotPaths @("{snapshot_path}")
$record = Invoke-ValidationCommand -Case $case
$record | ConvertTo-Json -Depth 10 -Compress
'''
    result = _run_powershell_command(command, env={"PYTHONPATH": str(fixture_path)})

    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(result.stdout.strip())
    assert record["result"] == expected_result
    assert record["identity_observed"] is identity_observed
    assert (record["assertion_failures"] == []) is (expected_result == "passed")


def _snapshot_workflow_fixture_cli_path(tmp_path: Path) -> Path:
    fixture_cli = tmp_path / "powers_tool_cli"
    fixture_cli.mkdir()
    (fixture_cli / "__init__.py").write_text("", encoding="utf-8")
    (fixture_cli / "cli.py").write_text(
        r'''
import json
import sys
from pathlib import Path

reported = {
    "manufacturer": "Keysight Technologies",
    "model": "E36312A",
    "serial": "SN",
    "firmware": "2.10",
    "parse_ok": True,
}
resolved = {
    "vendor_id": "keysight",
    "model_id": "keysight-e36312a",
    "model_name": "E36312A",
    "display_name": "Keysight E36312A",
}

def snapshot_document(mutated=False):
    return {
        "schema_version": 2,
        "kind": "powers-tool-snapshot",
        "resource": "USB0::FIXTURE::INSTR",
        "reported_identity": reported,
        "resolved_identity": resolved,
        "errors": [],
        "read_count": 1,
        "outputs": [{"channel": channel, "enabled": False} for channel in (1, 2, 3)],
        "readback": [
            {
                "channel": channel,
                "setpoints": {
                    "voltage": 0.5 if mutated else 1.0,
                    "current": 0.04 if mutated else 0.05,
                },
            }
            for channel in (1, 2, 3)
        ],
        "measurements": [
            {"channel": channel, "measurements": {"voltage": 0.0, "current": 0.0}}
            for channel in (1, 2, 3)
        ],
        "protection": {"over_voltage_tripped": False, "over_current_tripped": False},
        "protection_settings": [
            {
                "channel": channel,
                "protection": {
                    "ovp_voltage": 4.0 if mutated else 5.0,
                    "ocp_enabled": False if mutated else True,
                    "ocp_delay": None,
                    "ocp_delay_trigger": None,
                },
            }
            for channel in (1, 2, 3)
        ],
    }

command = sys.argv[1]
dry_run = "--dry-run" in sys.argv
save_path = Path(sys.argv[sys.argv.index("--save-json") + 1])
data = {
    "resource": {
        "idn": {
            **reported,
            "raw": "Keysight Technologies,E36312A,SN,2.10",
        }
    }
}
if command == "snapshot":
    mutated = False
    if "--snapshot-json" in sys.argv:
        snapshot_path = Path(sys.argv[sys.argv.index("--snapshot-json") + 1])
        mutated = snapshot_path.name == "restore-off-snapshot-b.json"
        document = snapshot_document(mutated=mutated)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(document), encoding="utf-8")
        data = document
    else:
        data = snapshot_document()
        if "--compare" in sys.argv:
            data["comparison"] = {"passed": True, "differences": []}
elif command == "restore-from-snapshot":
    if dry_run:
        data = {"plan": {}, "restored_channels": [1, 2, 3], "restore_output_state": False}
    else:
        data = {
            "resource": "USB0::FIXTURE::INSTR",
            "restored_channels": [1, 2, 3],
            "plan": {},
            "reported_identity": reported,
            "resolved_identity": resolved,
        }
elif command == "readback":
    data = {
        "resource": "USB0::FIXTURE::INSTR",
        "channels": snapshot_document()["readback"],
    }
elif command == "output-state":
    one_on = save_path.name == "live-restore-on-assert.json"
    data = {
        "resource": {"idn": {**reported, "raw": "Keysight Technologies,E36312A,SN,2.10"}},
        "channel": "all",
        "outputs": [
            {"channel": channel, "enabled": one_on and channel == 1}
            for channel in (1, 2, 3)
        ],
    }
elif command == "error":
    data = {"resource": "USB0::FIXTURE::INSTR", "errors": [], "read_count": 1}

payload = {
    "ok": True,
    "error": None,
    "execution": {
        "mode": "real",
        "dry_run": dry_run,
        "hardware_touched": not dry_run,
    },
    "data": data,
}
save_path.parent.mkdir(parents=True, exist_ok=True)
save_path.write_text(json.dumps(payload), encoding="utf-8")
'''.lstrip(),
        encoding="utf-8",
    )
    return tmp_path


def test_actual_snapshot_cases_complete_full_workflow(tmp_path):
    fixture_path = _snapshot_workflow_fixture_cli_path(tmp_path)
    output_dir = tmp_path / "out"
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:OutputDir = "{output_dir}"
$script:RawResource = "USB0::FIXTURE::INSTR"
$script:ResourceDisplay = "USB:<redacted-resource>"
$script:ConnectionLabel = "USB"
$script:TransportScope = "usb"
$script:BackendArtifact = Get-BackendArtifactFields -Value $null
$script:BackendValue = $null
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:InstrumentIdentity = $null
$script:StateChanging = $true
$script:Restore = $true
$script:PlanOnly = $false
Ensure-ArtifactDirectories
$executed = New-Object System.Collections.Generic.List[string]
foreach ($case in @(Get-SnapshotCases -Model "keysight-e36312a" -Live $true)) {{
    Invoke-ValidationCommand -Case $case | Out-Null
    $executed.Add($case.name)
}}
[pscustomobject]@{{
    executed = $executed.ToArray()
    failures = $script:Failures.ToArray()
    records = $script:CommandRecords.ToArray()
}} | ConvertTo-Json -Depth 20 -Compress
'''
    result = _run_powershell_command(command, env={"PYTHONPATH": str(fixture_path)})

    assert result.returncode == 0, result.stdout + result.stderr
    run = json.loads(result.stdout.strip())
    assert run["failures"] == []
    assert run["executed"][-1] == "restore-error-queue"
    records = {record["name"]: record for record in run["records"]}
    for name in ("restore-off-save-b", "restore-off-execute", "restore-off-save-c"):
        assert records[name]["result"] == "passed"
        assert records[name]["identity_observed"] is True
    assert records["restore-on-readback"]["result"] == "passed"
    assert records["restore-on-readback"]["identity_observed"] is False
    assert records["restore-on-readback"]["assertion_failures"] == []


def test_live_cli_check_uses_candidate_scope_names_only() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    removed_names = (
        "Candidate" + "ContextRequired",
        "candidate_" + "context_required",
        "Assert-Candidate" + "ContextInventory",
        "Test-CurrentConnectionUsesCandidate" + "Capabilities",
        "missing candidate " + "context",
    )

    assert all(name not in script for name in removed_names)
    for current_name in (
        "CandidateScopeRequired",
        "candidate_scope_required",
        "Assert-CandidateScopeInventory",
        "Test-CurrentConnectionSupportsCandidates",
        "missing candidate scope marking",
    ):
        assert current_name in script


def _report_path(stdout: str, stderr: str) -> Path:
    combined = stdout + "\n" + stderr
    for line in combined.splitlines():
        if "Report:" in line:
            return Path(line.split("Report:", 1)[1].strip())
        if "See " in line and line.strip().endswith("report.json."):
            return Path(line.rsplit("See ", 1)[1].rstrip("."))
    raise AssertionError(f"report path not found in output:\n{combined}")


def _new_live_check_report(before: set[Path]) -> Path:
    reports = set(Path(".tmp_tests/live_cli_check").glob("*/shareable/report.json"))
    created = reports - before
    assert len(created) == 1, created
    return created.pop()


def _fixture_cli_path(tmp_path: Path, *, mode: str, hardware_touched: bool) -> Path:
    fixture_cli = tmp_path / "powers_tool_cli"
    fixture_cli.mkdir()
    (fixture_cli / "__init__.py").write_text("", encoding="utf-8")
    (fixture_cli / "cli.py").write_text(
        f"""
import json
import sys

payload = {{
    "ok": True,
    "error": None,
    "execution": {{
        "mode": "{mode}",
        "dry_run": False,
        "hardware_touched": {str(hardware_touched)},
    }},
}}

save_path = sys.argv[sys.argv.index("--save-json") + 1]
with open(save_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
""".lstrip(),
        encoding="utf-8",
    )
    return tmp_path


def _dynamic_fixture_cli_path(tmp_path: Path) -> Path:
    fixture_cli = tmp_path / "powers_tool_cli"
    fixture_cli.mkdir()
    (fixture_cli / "__init__.py").write_text("", encoding="utf-8")
    (fixture_cli / "cli.py").write_text(
        """
import json
import sys

if "no-json" in sys.argv:
    sys.exit(1)

payload = {
    "ok": True,
    "error": None,
    "execution": {
        "mode": "real" if "real" in sys.argv else "simulate",
        "dry_run": "dry-run" in sys.argv,
        "hardware_touched": "hardware-true" in sys.argv,
    },
}

save_path = sys.argv[sys.argv.index("--save-json") + 1]
with open(save_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
""".lstrip(),
        encoding="utf-8",
    )
    return tmp_path


def _trigger_record_fixture_cli_path(tmp_path: Path) -> Path:
    fixture_cli = tmp_path / "powers_tool_cli"
    fixture_cli.mkdir()
    (fixture_cli / "__init__.py").write_text("", encoding="utf-8")
    (fixture_cli / "cli.py").write_text(
        r'''
import json
import sys

command = sys.argv[1]
trigger = {
    "mode": "fire",
    "channel": 1,
    "fired": True,
    "completed": command == "success",
}
if command == "abort-empty":
    trigger.update({"abort_attempted": True, "abort_succeeded": True, "abort_errors": []})
elif command == "abort-missing":
    trigger.update({"abort_attempted": True, "abort_succeeded": False})

ok = command == "success"
payload = {
    "ok": ok,
    "error": None if ok else {"code": "trigger_fire_failed", "message": "fixture trigger failure"},
    "execution": {"mode": "simulate", "dry_run": False, "hardware_touched": False},
}
if command != "no-trigger":
    payload["data"] = {"trigger": trigger}

save_path = sys.argv[sys.argv.index("--save-json") + 1]
with open(save_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
sys.exit(0 if ok else 1)
'''.lstrip(),
        encoding="utf-8",
    )
    return tmp_path


def _artifact_privacy_fixture_cli_path(tmp_path: Path) -> Path:
    fixture_cli = tmp_path / "powers_tool_cli"
    fixture_cli.mkdir()
    (fixture_cli / "__init__.py").write_text("", encoding="utf-8")
    (fixture_cli / "cli.py").write_text(
        r'''
import json
import sys

resource = "TCPIP0::192.168.50.77::5025::SOCKET"
command = sys.argv[1]
if command.startswith("keysight-tech"):
    idn = "Keysight Technologies,E36312A,MY12345678,2.10"
elif command == "agilent-zero":
    idn = "Agilent Technologies,E3646A,0,1.0"
else:
    idn = "KEYSIGHT,E36312A,MY12345678,2.10"
external_path = r"C:\Users\Example User\private\sequence.yaml"
save_path = sys.argv[sys.argv.index("--save-json") + 1]
print(f"{resource} {idn} serial again: {idn.split(',')[2]} {external_path} D:\\Lab Data\\private artifact.txt /home/example user/private/sequence.yaml")
print(f"{resource} {idn} serial again: {idn.split(',')[2]} {external_path}", file=sys.stderr)

if command in {"malformed", "keysight-tech-malformed"}:
    with open(save_path, "w", encoding="utf-8") as handle:
        handle.write(f'{{"resource":"{resource}","idn":"{idn}","path":"{external_path}"')
    sys.exit(2)
if command == "missing":
    sys.exit(2)

payload = {
    "ok": False,
    "error": {"code": "fixture_error", "message": f"failed after {idn} at {external_path}"},
    "execution": {"mode": "real", "dry_run": False, "hardware_touched": False},
}
if command == "agilent-zero":
    payload["data"] = {
        "idn": {
            "raw": idn,
            "manufacturer": "Agilent Technologies",
            "model": "E3646A",
            "serial": "0",
            "firmware": "1.0",
            "parse_ok": True,
        },
        "evidence": {
            "firmware": "1.0",
            "exit_code": 0,
            "voltage": 1.0,
            "current": 0.05,
            "error_count": 0,
        },
    }
with open(save_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
sys.exit(2)
'''.lstrip(),
        encoding="utf-8",
    )
    return tmp_path


def _main_flow_fixture_cli_path(tmp_path: Path) -> Path:
    fixture_cli = tmp_path / "powers_tool_cli"
    fixture_cli.mkdir()
    (fixture_cli / "__init__.py").write_text("", encoding="utf-8")
    (fixture_cli / "cli.py").write_text(
        r'''
import json
import os
import sys
from pathlib import Path

failed = os.environ.get("P5_FIXTURE_PREFLIGHT_FAIL") == "1"
payload = {
    "ok": not failed,
    "error": None if not failed else {"code": "fixture_preflight_failed", "message": "fixture preflight failed"},
    "execution": {"mode": "simulate", "dry_run": False, "hardware_touched": False},
}
command = sys.argv[1]
if command == "doctor":
    payload["data"] = {"real_resource_manager": {"checked": False, "available": None}}
elif command == "measure-all":
    payload["data"] = {
        "channels": [
            {"channel": channel, "measurements": {"voltage": 0.0, "current": 0.0}}
            for channel in (1, 2, 3)
        ]
    }
elif command == "log":
    csv_path = Path(sys.argv[sys.argv.index("--csv") + 1])
    jsonl_path = Path(sys.argv[sys.argv.index("--jsonl") + 1])
    header = "timestamp,resource,resource_alias,model,serial,channel,programmed_voltage,programmed_current,measured_voltage,measured_current,output_enabled,errors\n"
    rows = [f"2026-01-01T00:00:00Z,SIM,,E36312A,SIM,{channel},1,0.05,0,0,false,\n" for channel in (1, 2, 3)]
    csv_path.write_text(header + "".join(rows), encoding="utf-8")
    events = [json.dumps({"event": "sample", "sample": {"channel": channel}}) for channel in (1, 2, 3)]
    events.append(json.dumps({"event": "summary", "samples_written": 1, "channels": [1, 2, 3], "stopped": False, "stop_reason": "completed"}))
    jsonl_path.write_text("\n".join(events) + "\n", encoding="utf-8")
    payload["data"] = {"samples_written": 1, "stopped": False, "stop_reason": "completed"}
save_path = sys.argv[sys.argv.index("--save-json") + 1]
with open(save_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
sys.exit(0 if payload["ok"] else 2)
'''.lstrip(),
        encoding="utf-8",
    )
    return tmp_path






def _artifact_privacy_command(
    output_dir: Path, names: tuple[str, ...] = ("malformed", "missing", "error-only")
) -> str:
    case_names = ", ".join(f'"{name}"' for name in names)
    return rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "TCPIP0::192.168.50.77::5025::SOCKET"
$script:ResourceDisplay = "LAN:<redacted-resource>"
$script:NormalizedTarget = "keysight-e36312a"
$script:ConnectionLabel = "LAN"
$script:TransportScope = "tcpip"
$script:BackendArtifact = Get-BackendArtifactFields -Value "@py"
$script:BackendValue = "@py"
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:SuitesToRun = @("readonly")
$script:Suite = "readonly"
$script:StateChanging = $false
$script:Restore = $true
$script:PlanOnly = $false
foreach ($name in @({case_names})) {{
    $case = New-CommandCase -Name $name -Suite "readonly" -Phase "live" -Args @($name, "--json", "--resource", $script:RawResource) -ExpectedSuccess:$false
    Invoke-ValidationCommand -Case $case | Out-Null
}}
Write-ValidationArtifacts -ValidationMode "live" -Result "failed" -StartedAt (Get-Date)
Write-Output (Join-Path $script:ShareableArtifactDir "report.json")
'''


def test_live_cli_check_malformed_missing_and_error_only_artifacts_fail_closed(tmp_path):
    fixture_path = _artifact_privacy_fixture_cli_path(tmp_path)
    result = _run_powershell_command(
        _artifact_privacy_command(tmp_path / "out"),
        env={"PYTHONPATH": str(fixture_path)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_path = Path(result.stdout.strip())
    shareable_dir = report_path.parent
    private_dir = shareable_dir.parent / "private"
    malformed_placeholder = json.loads(
        (shareable_dir / "live-malformed-attempt-1.json").read_text(encoding="utf-8")
    )
    missing_placeholder = json.loads(
        (shareable_dir / "live-missing-attempt-1.json").read_text(encoding="utf-8")
    )
    assert malformed_placeholder == {
        "artifact_available": False,
        "artifact_kind": "command_json",
        "parse_status": "failed",
        "parse_error": "Could not parse command JSON.",
        "private_raw_artifact_retained": True,
    }
    assert missing_placeholder["artifact_available"] is False
    assert missing_placeholder["parse_status"] == "missing"
    assert missing_placeholder["private_raw_artifact_retained"] is False
    assert "TCPIP0::192.168.50.77::5025::SOCKET" in (
        private_dir / "live-malformed-attempt-1.json"
    ).read_text(encoding="utf-8")

    shareable_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in shareable_dir.rglob("*")
        if path.is_file()
    )
    forbidden = (
        "TCPIP0::192.168.50.77::5025::SOCKET",
        "192.168.50.77",
        "MY12345678",
        "KEYSIGHT,E36312A,MY12345678,2.10",
        r"C:\Users\Example User\private\sequence.yaml",
        r"Users\Example User\private\sequence.yaml",
        r"D:\Lab Data\private artifact.txt",
        r"Lab Data\private artifact.txt",
        "/home/example user/private/sequence.yaml",
        "example user/private/sequence.yaml",
        str(Path.cwd()),
        str(Path(sys.executable)),
    )
    assert all(value not in shareable_text for value in forbidden)
    assert "<redacted-idn>" in shareable_text
    assert "<redacted-resource>" in shareable_text
    assert "fixture_error" in shareable_text
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert all("\\shareable\\" in command["json_path"] for command in report["commands"])


def _shareable_text(directory: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in directory.rglob("*")
        if path.is_file()
    )


def test_live_cli_check_redacts_keysight_technologies_error_only_idn_and_serial(tmp_path):
    fixture_path = _artifact_privacy_fixture_cli_path(tmp_path)
    result = _run_powershell_command(
        _artifact_privacy_command(tmp_path / "out", ("keysight-tech-error-only",)),
        env={"PYTHONPATH": str(fixture_path)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    shareable_dir = Path(result.stdout.strip()).parent
    shareable_text = _shareable_text(shareable_dir)
    assert "Keysight Technologies,E36312A,MY12345678,2.10" not in shareable_text
    assert "MY12345678" not in shareable_text
    assert "<redacted-idn>" in shareable_text
    for expected in ("fixture_error", "keysight-tech-error-only", "exit_code", "transport_scope", "backend_scope"):
        assert expected in shareable_text


def test_live_cli_check_keeps_keysight_technologies_malformed_json_private(tmp_path):
    fixture_path = _artifact_privacy_fixture_cli_path(tmp_path)
    result = _run_powershell_command(
        _artifact_privacy_command(tmp_path / "out", ("keysight-tech-malformed",)),
        env={"PYTHONPATH": str(fixture_path)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_path = Path(result.stdout.strip())
    shareable_dir = report_path.parent
    private_dir = shareable_dir.parent / "private"
    raw_idn = "Keysight Technologies,E36312A,MY12345678,2.10"
    assert raw_idn in (private_dir / "live-keysight-tech-malformed-attempt-1.json").read_text(encoding="utf-8")
    assert json.loads((shareable_dir / "live-keysight-tech-malformed-attempt-1.json").read_text(encoding="utf-8"))["parse_status"] == "failed"
    shareable_text = _shareable_text(shareable_dir)
    assert raw_idn not in shareable_text
    assert "MY12345678" not in shareable_text
    assert "<redacted-idn>" in shareable_text


def test_live_cli_check_redacts_zero_serial_without_corrupting_numeric_evidence(tmp_path):
    fixture_path = _artifact_privacy_fixture_cli_path(tmp_path)
    result = _run_powershell_command(
        _artifact_privacy_command(tmp_path / "out", ("agilent-zero",)),
        env={"PYTHONPATH": str(fixture_path)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    shareable_dir = Path(result.stdout.strip()).parent
    shareable_text = _shareable_text(shareable_dir)
    assert "Agilent Technologies,E3646A,0,1.0" not in shareable_text
    assert "<redacted-idn>" in shareable_text
    assert "1.<redacted>" not in shareable_text
    assert "<redacted>.05" not in shareable_text
    assert "exit_code = <redacted>" not in shareable_text
    payload = json.loads((shareable_dir / "live-agilent-zero-attempt-1.json").read_text(encoding="utf-8"))
    assert payload["data"]["idn"]["serial"] == "<redacted>"
    assert payload["data"]["evidence"] == {
        "firmware": "1.0",
        "exit_code": 0,
        "voltage": 1.0,
        "current": 0.05,
        "error_count": 0,
    }
    assert '"firmware":  "1.0"' in shareable_text


@pytest.mark.parametrize(
    ("idn", "serial", "distinctive"),
    [
        ("KEYSIGHT,E36312A,MY12345678,2.10", "MY12345678", True),
        ("Keysight Technologies,E36312A,MY12345678,2.10", "MY12345678", True),
        ("Agilent,E3646A,MY00000001,A.01.00", "MY00000001", True),
        ("Agilent Technologies,E3646A,MY00000001,A.01.00", "MY00000001", True),
        ("Agilent Technologies,E3646A,0,1.0", "0", False),
        ("Acme Instruments,PSU1000,SYNTH0001,3.2", "SYNTH0001", True),
        ("aCmE instruments,PSU1000,0,3.2", "0", False),
    ],
)
def test_live_cli_check_free_form_idn_redactor_handles_manufacturer_variants(
    idn, serial, distinctive
):
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:RawResource = $null
$script:ResourceDisplay = "<redacted-resource>"
$result = Protect-ShareableText -Text "identity: {idn}; standalone serial: {serial}; firmware 1.0; exit code 0; voltage 1.0; current 0.05"
[pscustomobject]@{{ text = $result; sensitive = @($script:SensitiveValues) }} | ConvertTo-Json -Compress
'''
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    redaction = json.loads(result.stdout)
    assert idn not in redaction["text"]
    assert "<redacted-idn>" in redaction["text"]
    if distinctive:
        assert serial not in redaction["text"]
        assert serial in redaction["sensitive"]
    else:
        assert redaction["text"].endswith("firmware 1.0; exit code 0; voltage 1.0; current 0.05")
        assert "0" not in redaction["sensitive"]


def test_live_cli_check_report_normalizes_stale_cleanup_lifecycle_states(tmp_path):
    fixture_path = _dynamic_fixture_cli_path(tmp_path)
    output_dir = tmp_path / "out"
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "USB0::FIXTURE::INSTR"
$script:ResourceDisplay = "USB:<redacted-resource>"
$script:NormalizedTarget = "keysight-e36312a"
$script:ConnectionLabel = "USB"
$script:TransportScope = "usb"
$script:BackendArtifact = Get-BackendArtifactFields -Value $null
$script:BackendValue = $null
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:SuitesToRun = @("readonly")
$script:Suite = "readonly"
$script:StateChanging = $false
$script:Restore = $true
$script:PlanOnly = $false
$script:CleanupEvidence = New-CleanupEvidence -ValidationMode "planned"
$case = New-CommandCase -Name "live-readonly" -Suite "readonly" -Phase "live" -Args @("real", "--json") -LiveHardwareExpected:$true
Invoke-ValidationCommand -Case $case | Out-Null
Write-ValidationArtifacts -ValidationMode "live" -Result "passed" -StartedAt (Get-Date)
Write-Output (Join-Path $script:ShareableArtifactDir "report.json")
'''
    result = _run_powershell_command(command, env={"PYTHONPATH": str(fixture_path)})

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(Path(result.stdout.strip()).read_text(encoding="utf-8"))
    assert report["validation_mode"] == "live"
    assert report["result"] == "passed"
    assert report["state_changing"] is False
    assert report["cleanup"]["status"] == "not_required"
    assert report["cleanup"]["requested"] is False
    assert report["cleanup"]["attempted"] is False


def _live_fixture_validation_command(output_dir: Path, *, expect_passed: bool) -> str:
    expected_result = "passed" if expect_passed else "failed"
    failure_check = (
        'if ($script:Failures.Count -ne 0) { throw ($script:Failures -join "`n") }'
        if expect_passed
        else 'if ($script:Failures.Count -eq 0) { throw "expected a live validation failure" }'
    )
    return rf"""
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "USB0::FIXTURE::INSTR"
$script:ResourceDisplay = "USB:<redacted-resource>"
$script:BackendValue = $null
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$case = New-CommandCase -Name "verify" -Suite "readonly" -Phase "live" -Args @("verify", "--json", "--resource", $script:RawResource) -LiveHardwareExpected:$true
$record = Invoke-ValidationCommand -Case $case
if ($record.result -ne "{expected_result}") {{ throw "expected result {expected_result}, got $($record.result)" }}
{failure_check}
if ($record.mode -ne "real") {{ throw "expected mode real, got $($record.mode)" }}
"""


def test_live_validation_accepts_real_execution_mode_fixture(tmp_path):
    fixture_path = _fixture_cli_path(tmp_path, mode="real", hardware_touched=True)
    output_dir = tmp_path / "out"
    command = _live_fixture_validation_command(output_dir, expect_passed=True)
    env = {"PYTHONPATH": str(fixture_path)}
    result = _run_powershell_command(command, env=env)

    assert result.returncode == 0, result.stdout + result.stderr


def test_live_validation_still_rejects_real_mode_without_hardware_touch_fixture(tmp_path):
    fixture_path = _fixture_cli_path(tmp_path, mode="real", hardware_touched=False)
    output_dir = tmp_path / "out"
    command = _live_fixture_validation_command(output_dir, expect_passed=False)
    env = {"PYTHONPATH": str(fixture_path)}
    result = _run_powershell_command(command, env=env)

    assert result.returncode == 0, result.stdout + result.stderr


def _confirmation_warnings_for_suites(suites):
    suite_items = ", ".join(f'"{suite}"' for suite in suites)
    command = f"""
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\\scripts\\live-cli-check.ps1
Write-LiveConfirmationWarnings -SuitesToRun @({suite_items})
"""
    return _run_powershell_command(command)


def test_live_confirmation_warnings_are_scoped_to_selected_suites():
    result = _confirmation_warnings_for_suites(
        ["readonly", "output", "software-sequence"]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Low-power setpoints may be written" in result.stdout
    assert (
        "Outputs may briefly turn on for output or software-sequence cases."
        in result.stdout
    )
    assert "trigger-list cases" not in result.stdout
    assert "Protection suite writes" not in result.stdout


def test_live_confirmation_warnings_include_trigger_list_when_selected():
    result = _confirmation_warnings_for_suites(
        ["readonly", "output", "trigger-list", "software-sequence"]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Low-power setpoints may be written" in result.stdout
    assert (
        "Outputs may briefly turn on for output, trigger-list, or software-sequence cases."
        in result.stdout
    )
    assert "Protection suite writes" not in result.stdout


def test_live_confirmation_warnings_format_single_output_affecting_suite():
    result = _confirmation_warnings_for_suites(["readonly", "output"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Outputs may briefly turn on for output cases." in result.stdout


def test_live_confirmation_warnings_format_single_software_sequence_suite():
    result = _confirmation_warnings_for_suites(["readonly", "software-sequence"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "Outputs may briefly turn on for software-sequence cases." in result.stdout
    )


def test_live_cli_check_uses_phase_specific_artifact_names(tmp_path):
    fixture_path = _dynamic_fixture_cli_path(tmp_path)
    output_dir = tmp_path / "out"
    command = rf"""
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "USB0::FIXTURE::INSTR"
$script:ResourceDisplay = "USB:<redacted-resource>"
$script:BackendValue = $null
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$preflight = New-CommandCase -Name "trigger-step-bus" -Suite "trigger-list" -Phase "preflight" -Args @("simulate", "--json")
$live = New-CommandCase -Name "trigger-step-bus" -Suite "trigger-list" -Phase "live" -Args @("real", "hardware-true", "--json") -LiveHardwareExpected:$true
$preflightRecord = Invoke-ValidationCommand -Case $preflight
$liveRecord = Invoke-ValidationCommand -Case $live
if ($preflightRecord.result -ne "passed") {{ throw "preflight did not pass" }}
if ($liveRecord.result -ne "passed") {{ throw "live did not pass" }}
if ($preflightRecord.json_path -eq $liveRecord.json_path) {{ throw "artifact paths collided" }}
if ($preflightRecord.json_path -notmatch "preflight-trigger-step-bus\.json$") {{ throw "bad preflight path $($preflightRecord.json_path)" }}
if ($liveRecord.json_path -notmatch "live-trigger-step-bus\.json$") {{ throw "bad live path $($liveRecord.json_path)" }}
"""
    result = _run_powershell_command(command, env={"PYTHONPATH": str(fixture_path)})

    assert result.returncode == 0, result.stdout + result.stderr
    assert (output_dir / "private" / "preflight-trigger-step-bus.json").exists()
    assert (output_dir / "private" / "live-trigger-step-bus.json").exists()
    assert (output_dir / "shareable" / "preflight-trigger-step-bus.json").exists()
    assert (output_dir / "shareable" / "live-trigger-step-bus.json").exists()


def test_live_cli_check_failed_live_command_does_not_reuse_stale_preflight_json(tmp_path):
    fixture_path = _dynamic_fixture_cli_path(tmp_path)
    output_dir = tmp_path / "out"
    command = rf"""
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "USB0::FIXTURE::INSTR"
$script:ResourceDisplay = "USB:<redacted-resource>"
$script:BackendValue = $null
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$preflight = New-CommandCase -Name "trigger-step-bus" -Suite "trigger-list" -Phase "preflight" -Args @("simulate", "--json")
$live = New-CommandCase -Name "trigger-step-bus" -Suite "trigger-list" -Phase "live" -Args @("no-json", "--json") -LiveHardwareExpected:$true
$preflightRecord = Invoke-ValidationCommand -Case $preflight
$liveRecord = Invoke-ValidationCommand -Case $live
if ($preflightRecord.result -ne "passed") {{ throw "preflight did not pass" }}
if ($liveRecord.result -ne "failed") {{ throw "expected live failure, got $($liveRecord.result)" }}
if ($liveRecord.parse_error -ne "JSON output file was not created.") {{ throw "unexpected parse error $($liveRecord.parse_error)" }}
if ($liveRecord.mode) {{ throw "live mode should be empty when JSON is missing" }}
if (Test-Path -LiteralPath (Join-Path $script:OutputDir "live-trigger-step-bus.json")) {{ throw "live JSON should not exist" }}
"""
    result = _run_powershell_command(command, env={"PYTHONPATH": str(fixture_path)})

    assert result.returncode == 0, result.stdout + result.stderr
    preflight_payload = json.loads((output_dir / "private" / "preflight-trigger-step-bus.json").read_text(encoding="utf-8"))
    assert preflight_payload["execution"]["hardware_touched"] is False
    assert not (output_dir / "private" / "live-trigger-step-bus.json").exists()


def test_live_cli_check_preflight_still_rejects_hardware_touched_fixture(tmp_path):
    fixture_path = _dynamic_fixture_cli_path(tmp_path)
    output_dir = tmp_path / "out"
    command = rf"""
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "USB0::FIXTURE::INSTR"
$script:ResourceDisplay = "USB:<redacted-resource>"
$script:BackendValue = $null
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$case = New-CommandCase -Name "verify" -Suite "readonly" -Phase "preflight" -Args @("hardware-true", "--json")
$record = Invoke-ValidationCommand -Case $case
if ($record.result -ne "failed") {{ throw "expected preflight failure, got $($record.result)" }}
if ($script:Failures.Count -eq 0) {{ throw "expected failure message" }}
if (($script:Failures -join "`n") -notmatch "no-hardware validation") {{ throw ($script:Failures -join "`n") }}
"""
    result = _run_powershell_command(command, env={"PYTHONPATH": str(fixture_path)})

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("target", "connection", "resource", "skip_external_preflight"),
    [
        ("keysight-e36312a", "USB", "USB0::SIM::E36312A::INSTR", False),
        ("keysight-edu36311a", "USB", "USB0::SIM::EDU36311A::INSTR", True),
        ("keysight-e3646a", "ASRL", "ASRL1::SIM::E3646A::INSTR", True),
    ],
)
def test_live_cli_check_readonly_plan_only_succeeds_without_hardware(
    target, connection, resource, skip_external_preflight
):
    assert SCRIPT.exists()

    arguments = [
        "-Target",
        target,
        "-Connection",
        connection,
        "-Resource",
        resource,
        "-Suite",
        "readonly",
        "-PlanOnly",
    ]
    if skip_external_preflight:
        arguments.append("-SkipExternalPreflight")
    result = _run_live_cli_check(*arguments)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Press Enter" not in result.stdout
    report = json.loads(_report_path(result.stdout, result.stderr).read_text(encoding="utf-8"))
    assert report["validation_mode"] == "planned"
    assert report["schema_version"] == "2.0"
    assert type(report["schema_version"]) is str
    assert SUPPORT_EVIDENCE_MANIFEST.schema_version == 2
    assert type(SUPPORT_EVIDENCE_MANIFEST.schema_version) is int
    assert report["kind"] == "powers-tool-live-validation"
    assert report["support_policy_mode"] == "validation"
    assert report["pending_live_support_allowed"] is True
    assert report["candidate_evidence_only"] is True
    assert report["promotes_live_support"] is False
    assert report["plan_only"] is True
    assert report["live_executed"] is False
    assert report["model_id"] == target
    assert report["vendor_id"] == "keysight"
    assert report["planning_model_id"] == target
    assert "expected_model_id" not in report
    assert report["transport_scope"] == {"USB": "usb", "ASRL": "asrl"}[connection]
    assert report["backend"] == "system_visa"
    assert report["backend_scope"] == "system_visa"
    assert report["backend_argument"] is None
    assert report["instrument_identity"]["availability"] == "not_observed_plan_only"
    assert report["instrument_identity"]["detected_model"] is None
    assert report["cleanup"]["status"] == "not_executed_plan_only"
    expected_preflight_status = (
        "skipped_by_caller_after_release_preflight"
        if skip_external_preflight
        else "passed"
    )
    assert report["external_preflight"]["status"] == expected_preflight_status
    assert "hardware_touched" not in json.dumps(report)


def test_live_cli_check_skip_external_preflight_requires_plan_only() -> None:
    result = _run_live_cli_check("-SkipExternalPreflight")

    assert result.returncode == 2
    assert "can only be used with -PlanOnly" in (result.stdout + result.stderr)


def test_live_cli_check_external_preflight_failure_remains_fail_closed() -> None:
    before = set(Path(".tmp_tests/live_cli_check").glob("*/shareable/report.json"))
    command = r"""
function global:powershell.exe { $global:LASTEXITCODE = 1 }
& .\scripts\live-cli-check.ps1 `
    -Target keysight-e36312a `
    -Connection USB `
    -Resource SIM::E36312A `
    -Suite readonly `
    -PlanOnly
"""
    result = _run_powershell_command(command)

    assert result.returncode == 1
    output = " ".join((result.stdout + result.stderr).split())
    assert "External preflight failed; no VISA resource was opened" in output
    report = json.loads(_new_live_check_report(before).read_text(encoding="utf-8"))
    assert report["validation_mode"] == "preflight_failed"
    assert report["external_preflight"]["status"] == "failed"
    assert report["commands"] == []
    assert report["live_executed"] is False


def test_plan_only_can_skip_completed_release_preflight_without_skipping_plans() -> None:
    result = _run_live_cli_check(
        "-Target",
        "keysight-e36312a",
        "-Connection",
        "USB",
        "-Resource",
        "SIM::E36312A",
        "-Suite",
        "readonly",
        "-PlanOnly",
        "-SkipExternalPreflight",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_path = _report_path(result.stdout, result.stderr)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["external_preflight"] == {
        "status": "skipped_by_caller_after_release_preflight"
    }
    assert report["plan_only"] is True
    assert report["live_executed"] is False
    assert report["commands"]
    assert {"verify", "identify", "capabilities"} <= {
        command["name"] for command in report["commands"]
    }
    private_payloads = list(
        (report_path.parent.parent / "private").glob("preflight-*.json")
    )
    assert private_payloads
    assert all(
        json.loads(path.read_text(encoding="utf-8"))["execution"]["hardware_touched"]
        is False
        for path in private_payloads
    )


def test_live_cli_check_rejects_redirected_stdin_before_live_execution() -> None:
    before = set(Path(".tmp_tests/live_cli_check").glob("*/shareable/report.json"))
    result = _run_live_cli_check(
        "-Target",
        "keysight-e36312a",
        "-Connection",
        "USB",
        "-Resource",
        "USB0::SIM::E36312A::INSTR",
        "-Suite",
        "readonly",
        stdin_text="\n",
    )

    assert result.returncode != 0
    assert "Press Enter" not in result.stdout
    report = json.loads(_new_live_check_report(before).read_text(encoding="utf-8"))
    assert report["validation_mode"] == "confirmation_required"
    assert report["live_executed"] is False
    assert any("stdin is redirected" in failure for failure in report["failures"])


def test_trigger_list_plan_only_lists_manual_candidate_without_helper_or_stdin() -> None:
    resource = "USB0::PRIVATE-PLAN::E36312A::INSTR"
    result = _run_live_cli_check(
        "-Target",
        "keysight-e36312a",
        "-Connection",
        "USB",
        "-Resource",
        resource,
        "-Suite",
        "trigger-list",
        "-PlanOnly",
        "-SkipExternalPreflight",
        stdin_text="unexpected input must not be read",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_path = _report_path(result.stdout, result.stderr)
    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)
    planned = {case["command"]: case for case in report["planned_live_cases"]}
    assert {"trigger-fire", "trigger-pulse"} <= set(planned)
    assert planned["trigger-pulse"]["operator_interaction_required"] is True
    assert not (report_path.parent.parent / "private" / "trigger-fire-snapshot.json").exists()
    assert "Did you observe" not in result.stdout
    assert resource not in report_text
    assert str(Path.cwd()) not in report_text
    assert "SERIAL" not in report_text


def test_trigger_list_redirected_stdin_fails_before_manual_case() -> None:
    before = set(Path(".tmp_tests/live_cli_check").glob("*/shareable/report.json"))
    result = _run_live_cli_check(
        "-Target",
        "keysight-e36312a",
        "-Connection",
        "USB",
        "-Resource",
        "USB0::SIM::E36312A::INSTR",
        "-Suite",
        "trigger-list",
        stdin_text="\n",
    )

    assert result.returncode != 0
    report_path = _new_live_check_report(before)
    assert not (report_path.parent.parent / "private" / "trigger-fire-snapshot.json").exists()
    assert "Did you observe" not in result.stdout


@pytest.mark.parametrize(
    ("connection", "backend"),
    [("ASRL", None), ("USB", "@py"), ("USB", "@ivi")],
)
def test_plan_only_has_no_stale_candidate_scope_marking(connection, backend) -> None:
    arguments = [
        "-Target",
        "keysight-e36312a",
        "-Connection",
        connection,
        "-Resource",
        "SIM::E36312A",
        "-Suite",
        "trigger-list",
        "-PlanOnly",
        "-SkipExternalPreflight",
    ]
    if backend is not None:
        arguments += ["-Backend", backend]

    result = _run_live_cli_check(*arguments)

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(_report_path(result.stdout, result.stderr).read_text(encoding="utf-8"))
    assert report["plan_only"] is True
    assert report["live_executed"] is False
    assert report["failures"] == []


def test_future_candidate_inventory_still_requires_full_plan_coverage() -> None:
    command = r'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CandidateInventory = '{"keysight-e36312a":{"commands":["future-candidate"],"connections":[["usb","system_visa"]]}}' | ConvertFrom-Json
$script:TransportScope = "usb"
$script:BackendArtifact = Get-BackendArtifactFields -Value $null
$cases = @((New-CommandCase -Name "measure" -Suite "readonly" -Phase "live" -Args @("measure") -LiveHardwareExpected:$true))
try {
    Assert-CandidateScopeInventory -Model "keysight-e36312a" -LiveCases $cases -RequireComplete:$true
    "unexpected-success"
}
catch { $_.Exception.Message }
'''
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "missing command uses: future-candidate" in result.stdout


def test_trigger_pulse_observation_occurs_only_after_command_and_cleanup(tmp_path) -> None:
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:TriggerEvidence = New-TriggerEvidence
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:StateChanging = $true
$script:Restore = $true
$script:CleanupEvidence = New-CleanupEvidence -ValidationMode "live"
$trace = New-Object System.Collections.Generic.List[string]
$responses = [System.Collections.Generic.Queue[string]]::new()
$responses.Enqueue("")
$responses.Enqueue("No")
function Read-Host {{ param([string]$Prompt); if ($responses.Count -eq 2) {{ $trace.Add("ready-prompt") }} else {{ $trace.Add("observation-prompt") }}; return $responses.Dequeue() }}
function Invoke-SafeOffCleanup {{ param([string]$Role); $trace.Add("cleanup-" + $Role); $script:CleanupEvidence = [pscustomobject]@{{ status = "passed"; all_outputs_off = $true; error_queue_checked = $true; instrument_errors = @() }} }}
function Invoke-ValidationCommand {{ param($Case); $trace.Add("command"); return [pscustomobject]@{{ result = "passed" }} }}
$case = New-CommandCase -Name "pulse" -Suite "trigger-list" -Phase "live" -Args @("trigger-pulse")
Invoke-TriggerPulseCandidateCase -Case $case
[pscustomobject]@{{ trace = $trace; failures = $script:Failures.Count; observation = $script:TriggerEvidence.pulse.operator_observation; error_queue_empty = $script:TriggerEvidence.pulse.error_queue_empty; outputs_all_off = $script:TriggerEvidence.pulse.outputs_all_off }} | ConvertTo-Json -Compress
'''
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["trace"] == [
        "ready-prompt",
        "cleanup-trigger-pulse-baseline",
        "command",
        "cleanup-trigger-pulse-final",
        "observation-prompt",
    ]
    assert payload["failures"] == 1
    assert payload["observation"] == "failed"
    assert payload["error_queue_empty"] is True
    assert payload["outputs_all_off"] is True


def test_trigger_fire_wrapper_restores_again_when_candidate_fails(tmp_path) -> None:
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:PrivateArtifactDir = "{(tmp_path / 'private').as_posix()}"
New-Item -ItemType Directory -Path $script:PrivateArtifactDir -Force | Out-Null
$script:TriggerEvidence = New-TriggerEvidence
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:StateChanging = $true
$script:Restore = $true
$script:CleanupEvidence = New-CleanupEvidence -ValidationMode "live"
$trace = New-Object System.Collections.Generic.List[string]
function Invoke-SafeOffCleanup {{ param([string]$Role); $trace.Add("cleanup-" + $Role); $script:CleanupEvidence = [pscustomobject]@{{ status = "passed"; all_outputs_off = $true; error_queue_checked = $true; instrument_errors = @() }} }}
function Invoke-TriggerValidationHelper {{ param([string]$Action, [string]$SnapshotPath); $trace.Add($Action); if ($Action -eq "arm") {{ New-Item -ItemType File -Path $SnapshotPath -Force | Out-Null }}; return [pscustomobject]@{{ ok = $true; payload = [pscustomobject]@{{ error_queue_empty = $true }} }} }}
function Invoke-ValidationCommand {{ param($Case); $trace.Add("candidate"); throw "candidate failed" }}
$case = New-CommandCase -Name "fire" -Suite "trigger-list" -Phase "live" -Args @("trigger-fire")
try {{ Invoke-TriggerFireCandidateCase -Case $case }} catch {{ $trace.Add("caught") }}
$trace | ConvertTo-Json -Compress
'''
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    trace = json.loads(result.stdout)
    assert trace.index("restore") > trace.index("candidate")
    assert "cleanup-trigger-fire-final" in trace


def test_trigger_fire_payload_assertion_requires_exact_json_values(tmp_path) -> None:
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$case = New-CommandCase -Name "fire" -Suite "trigger-list" -Phase "preflight" -Args @("trigger-fire") -ValidationKind "trigger-fire"
$payloads = @(
    '{{"data":{{"trigger":{{"mode":"fire","channel":1,"fired":true,"completed":true}}}}}}',
    '{{"data":{{"trigger":{{"mode":"fire","channel":1,"fired":true,"completed":false}}}}}}',
    '{{"data":{{"trigger":{{"mode":"fire","channel":1,"fired":false,"completed":true}}}}}}',
    '{{"data":{{}}}}',
    '{{"data":{{"trigger":{{"mode":"fire","channel":"1","fired":true,"completed":true}}}}}}',
    '{{"data":{{"trigger":{{"mode":"step","channel":1,"fired":true,"completed":true}}}}}}',
    '{{"data":{{"trigger":{{"mode":"fire","channel":1,"fired":"true","completed":1}}}}}}'
)
$counts = @($payloads | ForEach-Object {{
    $payload = $_ | ConvertFrom-Json
    @(Get-CaseAssertionFailures -Case $case -Payload $payload -Identity $null -OutputStates $null -InstrumentErrors $null -StderrPath "{tmp_path / 'empty.stderr'}").Count
}})
$counts | ConvertTo-Json -Compress
'''
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == [0, 1, 1, 4, 1, 1, 2]


def test_trigger_fire_command_record_preserves_diagnostics_and_property_presence(tmp_path) -> None:
    fixture_path = _trigger_record_fixture_cli_path(tmp_path)
    output_dir = tmp_path / "out"
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "USB0::FIXTURE::INSTR"
$script:ResourceDisplay = "USB:<redacted-resource>"
$script:BackendValue = $null
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$caseEmpty = New-CommandCase -Name "abort-empty" -Suite "trigger-list" -Phase "preflight" -Args @("abort-empty", "--json") -ValidationKind "trigger-fire"
$caseMissing = New-CommandCase -Name "abort-missing" -Suite "trigger-list" -Phase "preflight" -Args @("abort-missing", "--json") -ValidationKind "trigger-fire"
$caseNoTrigger = New-CommandCase -Name "no-trigger" -Suite "trigger-list" -Phase "preflight" -Args @("no-trigger", "--json") -ValidationKind "trigger-fire"
$empty = Invoke-ValidationCommand -Case $caseEmpty
$missing = Invoke-ValidationCommand -Case $caseMissing
$noTrigger = Invoke-ValidationCommand -Case $caseNoTrigger
[pscustomobject]@{{
    empty = $empty.trigger
    empty_has_abort_errors = $null -ne $empty.trigger.PSObject.Properties["abort_errors"]
    missing = $missing.trigger
    missing_has_abort_errors = $null -ne $missing.trigger.PSObject.Properties["abort_errors"]
    no_trigger = $noTrigger.trigger
}} | ConvertTo-Json -Depth 10 -Compress
'''
    result = _run_powershell_command(command, env={"PYTHONPATH": str(fixture_path)})

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["empty"] == {
        "mode": "fire",
        "channel": 1,
        "fired": True,
        "completed": False,
        "abort_attempted": True,
        "abort_succeeded": True,
        "abort_errors": [],
    }
    assert payload["empty_has_abort_errors"] is True
    assert payload["missing"] == {
        "mode": "fire",
        "channel": 1,
        "fired": True,
        "completed": False,
        "abort_attempted": True,
        "abort_succeeded": False,
    }
    assert payload["missing_has_abort_errors"] is False
    assert payload["no_trigger"] is None


def test_trigger_fire_evidence_comes_only_from_recorded_payload(tmp_path) -> None:
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:PrivateArtifactDir = "{(tmp_path / 'private').as_posix()}"
New-Item -ItemType Directory -Path $script:PrivateArtifactDir -Force | Out-Null
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:StateChanging = $true
$script:Restore = $true
$script:CleanupEvidence = New-CleanupEvidence -ValidationMode "live"
function Invoke-SafeOffCleanup {{ param([string]$Role); $script:CleanupEvidence = [pscustomobject]@{{ status = "passed"; all_outputs_off = $true; error_queue_checked = $true; instrument_errors = @() }} }}
function Invoke-TriggerValidationHelper {{ param([string]$Action, [string]$SnapshotPath); if ($Action -eq "arm") {{ New-Item -ItemType File -Path $SnapshotPath -Force | Out-Null }}; return [pscustomobject]@{{ ok = $true; payload = [pscustomobject]@{{ error_queue_empty = $true }} }} }}
$script:CurrentRecord = $null
function Invoke-ValidationCommand {{ param($Case); return $script:CurrentRecord }}
$case = New-CommandCase -Name "fire" -Suite "trigger-list" -Phase "live" -Args @("trigger-fire")
$records = @(
    [pscustomobject]@{{ result = "passed"; error_code = $null; trigger = ('{{"mode":"fire","channel":1,"fired":true,"completed":true}}' | ConvertFrom-Json) }},
    [pscustomobject]@{{ result = "failed"; error_code = $null; trigger = ('{{"mode":"fire","channel":1,"fired":true,"completed":false}}' | ConvertFrom-Json) }},
    [pscustomobject]@{{ result = "failed"; error_code = $null; trigger = ('{{"mode":"fire","channel":1,"fired":false,"completed":true}}' | ConvertFrom-Json) }},
    [pscustomobject]@{{ result = "failed"; error_code = $null; trigger = $null }},
    [pscustomobject]@{{ result = "failed"; error_code = $null; trigger = ('{{"mode":"fire","channel":2,"fired":true,"completed":true}}' | ConvertFrom-Json) }},
    [pscustomobject]@{{ result = "failed"; error_code = $null; trigger = ('{{"mode":"step","channel":1,"fired":true,"completed":true}}' | ConvertFrom-Json) }},
    [pscustomobject]@{{ result = "failed"; error_code = $null; trigger = ('{{"mode":"fire","channel":1,"fired":"true","completed":1}}' | ConvertFrom-Json) }}
)
$evidence = @($records | ForEach-Object {{
    $script:CurrentRecord = $_
    $script:TriggerEvidence = New-TriggerEvidence
    Invoke-TriggerFireCandidateCase -Case $case
    [pscustomobject]@{{ fired = $script:TriggerEvidence.fire.fired; completed = $script:TriggerEvidence.fire.completed; abort_status = $script:TriggerEvidence.fire.abort_status }}
}})
$evidence | ConvertTo-Json -Compress
'''
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == [
        {"fired": True, "completed": True, "abort_status": "not_required"},
        {"fired": True, "completed": False, "abort_status": "unknown"},
        {"fired": False, "completed": True, "abort_status": "unknown"},
        {"fired": False, "completed": False, "abort_status": "unknown"},
        {"fired": True, "completed": True, "abort_status": "unknown"},
        {"fired": True, "completed": True, "abort_status": "unknown"},
        {"fired": False, "completed": False, "abort_status": "unknown"},
    ]


def test_trigger_fire_abort_and_error_evidence_comes_from_recorded_diagnostics(tmp_path) -> None:
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:PrivateArtifactDir = "{(tmp_path / 'private').as_posix()}"
New-Item -ItemType Directory -Path $script:PrivateArtifactDir -Force | Out-Null
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:StateChanging = $true
$script:Restore = $true
$script:CleanupEvidence = New-CleanupEvidence -ValidationMode "live"
function Invoke-SafeOffCleanup {{ param([string]$Role); $script:CleanupEvidence = [pscustomobject]@{{ status = "passed"; all_outputs_off = $true; error_queue_checked = $true; instrument_errors = @() }} }}
function Invoke-TriggerValidationHelper {{ param([string]$Action, [string]$SnapshotPath); if ($Action -eq "arm") {{ New-Item -ItemType File -Path $SnapshotPath -Force | Out-Null }}; return [pscustomobject]@{{ ok = $true; payload = [pscustomobject]@{{ error_queue_empty = $true }} }} }}
$script:CurrentRecord = $null
function Invoke-ValidationCommand {{ param($Case); return $script:CurrentRecord }}
$case = New-CommandCase -Name "fire" -Suite "trigger-list" -Phase "live" -Args @("trigger-fire")
$records = @(
    [pscustomobject]@{{ name = "timeout"; result = "failed"; error_code = "wait_timeout"; trigger = ('{{"fired":true,"completed":false,"abort_attempted":true,"abort_succeeded":true,"abort_errors":[]}}' | ConvertFrom-Json) }},
    [pscustomobject]@{{ name = "interrupted"; result = "failed"; error_code = "interrupted"; trigger = ('{{"fired":true,"completed":false,"abort_attempted":true,"abort_succeeded":false,"abort_errors":["abort failed"]}}' | ConvertFrom-Json) }},
    [pscustomobject]@{{ name = "not-attempted"; result = "failed"; error_code = "trigger_fire_failed"; trigger = ('{{"fired":false,"completed":false,"abort_attempted":false}}' | ConvertFrom-Json) }},
    [pscustomobject]@{{ name = "general-fire"; result = "failed"; error_code = "trigger_fire_failed"; trigger = ('{{"fired":false,"completed":false}}' | ConvertFrom-Json) }},
    [pscustomobject]@{{ name = "error-queue"; result = "failed"; error_code = "trigger_fire_failed"; trigger = ('{{"fired":true,"completed":false,"abort_attempted":true,"abort_succeeded":false,"abort_errors":["queue abort failed"]}}' | ConvertFrom-Json) }},
    [pscustomobject]@{{ name = "assertion"; result = "failed"; error_code = $null; trigger = ('{{"fired":true,"completed":true}}' | ConvertFrom-Json) }},
    [pscustomobject]@{{ name = "success"; result = "passed"; error_code = $null; trigger = ('{{"fired":true,"completed":true}}' | ConvertFrom-Json) }},
    [pscustomobject]@{{ name = "missing"; result = "failed"; error_code = "trigger_fire_failed"; trigger = $null }}
)
$evidence = @($records | ForEach-Object {{
    $script:CurrentRecord = $_
    $script:TriggerEvidence = New-TriggerEvidence
    Invoke-TriggerFireCandidateCase -Case $case
    [pscustomobject]@{{
        name = $_.name
        timeout_or_interrupted = $script:TriggerEvidence.fire.timeout_or_interrupted
        abort_status = $script:TriggerEvidence.fire.abort_status
        abort_attempted = $script:TriggerEvidence.fire.abort_attempted
        abort_succeeded = $script:TriggerEvidence.fire.abort_succeeded
        abort_errors = $script:TriggerEvidence.fire.abort_errors
    }}
}})
$notExecuted = New-TriggerEvidence
[pscustomobject]@{{ evidence = $evidence; not_executed = $notExecuted.fire.abort_status }} | ConvertTo-Json -Depth 10 -Compress
'''
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    evidence = {item["name"]: item for item in payload["evidence"]}
    assert evidence["timeout"] == {
        "name": "timeout",
        "timeout_or_interrupted": True,
        "abort_status": "succeeded",
        "abort_attempted": True,
        "abort_succeeded": True,
        "abort_errors": [],
    }
    assert evidence["interrupted"]["timeout_or_interrupted"] is True
    assert evidence["interrupted"]["abort_status"] == "failed"
    assert evidence["interrupted"]["abort_errors"] == ["abort failed"]
    assert evidence["not-attempted"]["abort_status"] == "not_attempted"
    assert evidence["not-attempted"]["timeout_or_interrupted"] is False
    assert evidence["general-fire"]["abort_status"] == "unknown"
    assert evidence["general-fire"]["timeout_or_interrupted"] is False
    assert evidence["error-queue"]["abort_status"] == "failed"
    assert evidence["error-queue"]["timeout_or_interrupted"] is False
    assert evidence["assertion"]["abort_status"] == "unknown"
    assert evidence["assertion"]["timeout_or_interrupted"] is False
    assert evidence["success"]["abort_status"] == "not_required"
    assert evidence["success"]["timeout_or_interrupted"] is False
    assert evidence["missing"]["abort_status"] == "unknown"
    assert evidence["missing"]["abort_errors"] is None
    assert payload["not_executed"] == "not_executed"


def test_live_cli_check_centrally_adds_validation_flag_only_for_policy_commands():
    command = r"""
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$policy = @(Add-ValidationSupportPolicyArgument -Arguments @("measure", "--json"))
if (@($policy | Where-Object { $_ -eq "--validation-allow-pending-live-support" }).Count -ne 1) { throw "policy command did not receive exactly one flag" }
$duplicate = @(Add-ValidationSupportPolicyArgument -Arguments @("measure", "--validation-allow-pending-live-support", "--json"))
if (@($duplicate | Where-Object { $_ -eq "--validation-allow-pending-live-support" }).Count -ne 1) { throw "duplicate flag inserted" }
foreach ($diagnostic in @("list-resources", "verify", "identify", "error", "clear")) {
    $args = @(Add-ValidationSupportPolicyArgument -Arguments @($diagnostic, "--json"))
    if ($args -contains "--validation-allow-pending-live-support") { throw "$diagnostic should remain exempt" }
}
"""
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr


def _wrapper_arguments(command: str) -> list[str]:
    powershell = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:NormalizedTarget = "keysight-e3646a"
$script:RawResource = "ASRL1::INSTR"
$script:OutputDir = ".tmp_tests\parser-contract"
$script:BackendValue = $null
Ensure-ArtifactDirectories
$case = @(Get-SuiteCases -Model $script:NormalizedTarget -Suites (Get-SupportedSuites -Model $script:NormalizedTarget) -Live:$true | Where-Object {{ $_.args[0] -eq "{command}" }})[0]
@(Get-ValidationCommandArguments -Case $case -JsonPath ".tmp_tests\parser-contract.json") | ConvertTo-Json -Compress
'''
    result = _run_powershell_command(powershell)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_live_cli_check_verify_arguments_are_accepted_by_production_parser():
    arguments = _wrapper_arguments("verify")

    args = cli.build_parser().parse_args(arguments)

    assert arguments == [
        "verify",
        "--json",
        "--resource",
        "ASRL1::INSTR",
        "--log-scpi",
        "--model",
        "keysight-e3646a",
        "--save-json",
        ".tmp_tests\\parser-contract.json",
    ]
    assert cli._target_core_request_for_args(args).runtime.expected_model_id == "keysight-e3646a"


@pytest.mark.parametrize("command", ["error", "clear"])
def test_live_cli_check_raw_diagnostic_arguments_omit_model(command):
    arguments = _wrapper_arguments(command)

    cli.build_parser().parse_args(arguments)

    assert "--model" not in arguments


def test_live_cli_check_identify_retains_expected_model_guard():
    arguments = _wrapper_arguments("identify")

    args = cli.build_parser().parse_args(arguments)

    assert cli._target_core_request_for_args(args).runtime.expected_model_id == "keysight-e3646a"


def test_live_cli_check_model_aware_command_retains_expected_model_guard():
    arguments = _wrapper_arguments("output-state")

    args = cli.build_parser().parse_args(arguments)

    assert cli._target_core_request_for_args(args).runtime.expected_model_id == "keysight-e3646a"


@pytest.mark.parametrize(
    ("target", "resource"),
    [
        ("keysight-e36312a", "USB0::SIM::E36312A::INSTR"),
        ("keysight-edu36311a", "USB0::SIM::EDU36311A::INSTR"),
        ("keysight-e3646a", "ASRL1::SIM::E3646A::INSTR"),
    ],
)
def test_every_maintained_live_suite_case_is_production_parser_compatible(
    tmp_path, target, resource
):
    output_dir = (tmp_path / target).as_posix()
    powershell = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:NormalizedTarget = "{target}"
$script:RawResource = "{resource}"
$script:OutputDir = "{output_dir}"
$script:BackendValue = $null
Ensure-ArtifactDirectories
$records = @()
foreach ($case in @(Get-SuiteCases -Model "{target}" -Suites (Get-SupportedSuites -Model "{target}") -Live:$true)) {{
    $contract = Get-LiveCommandIdentityContract -Command $case.args[0]
    $arguments = @(Get-ValidationCommandArguments -Case $case -JsonPath (Join-Path $script:PrivateArtifactDir ($case.name + ".json")))
    $records += [pscustomobject]@{{ name = $case.name; contract = $contract; arguments = $arguments }}
}}
$records | ConvertTo-Json -Depth 12 -Compress
'''
    result = _run_powershell_command(powershell)
    assert result.returncode == 0, result.stdout + result.stderr
    records = json.loads(result.stdout)

    for record in records:
        assert record["contract"] != "unclassified", record
        cli.build_parser().parse_args(record["arguments"])


@pytest.mark.parametrize(
    ("value", "backend", "scope", "argument"),
    [
        (None, "system_visa", "system_visa", None),
        ("@py", "@py", "pyvisa_py", "@py"),
        ("@ivi", "@ivi", "custom_visa", "@ivi"),
    ],
)
def test_live_cli_check_normalizes_backend_for_artifacts(value, backend, scope, argument):
    literal = "$null" if value is None else f'"{value}"'
    expected_argument = "$null" if argument is None else f'"{argument}"'
    command = rf"""
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$fields = Get-BackendArtifactFields -Value {literal}
if ($fields.backend -ne "{backend}") {{ throw "wrong backend: $($fields.backend)" }}
if ($fields.backend_scope -ne "{scope}") {{ throw "wrong scope: $($fields.backend_scope)" }}
if ($fields.backend_argument -ne {expected_argument}) {{ throw "wrong backend argument" }}
"""
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr


def test_live_cli_check_plan_artifact_redacts_resource_and_command_paths():
    resource = "TCPIP0::PLANONLY::E36312A::INSTR"
    result = _run_live_cli_check(
        "-Target",
        "keysight-e36312a",
        "-Connection",
        "LAN",
        "-Resource",
        resource,
        "-Backend",
        "@py",
        "-Suite",
        "readonly",
        "-PlanOnly",
        "-SkipExternalPreflight",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_path = _report_path(result.stdout, result.stderr)
    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert resource not in report_text
    assert str(Path.cwd()) not in report_text
    assert report["resource"] == "LAN:<redacted-resource>"
    assert all("<redacted-resource>" not in command["arguments"] for command in report["commands"])
    assert "candidate validation evidence only" in report_path.with_name("summary.md").read_text(encoding="utf-8")


def test_live_cli_check_shareable_plan_contains_no_private_runtime_material():
    resource = "USB0::SHAREABLE-CONTEXT::E36312A::INSTR"
    result = _run_live_cli_check(
        "-Target",
        "keysight-e36312a",
        "-Connection",
        "USB",
        "-Resource",
        resource,
        "-Suite",
        "readonly",
        "-PlanOnly",
        "-SkipExternalPreflight",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_path = _report_path(result.stdout, result.stderr)
    shareable_dir = report_path.parent
    shareable_text = _shareable_text(shareable_dir)
    private_dir = shareable_dir.parent / "private"
    forbidden = (
        resource,
        "USB0::SIM::E36312A::INSTR",
        str(private_dir),
    )
    assert all(value not in shareable_text for value in forbidden)


@pytest.mark.parametrize(
    ("target", "connection", "resource", "suite"),
    [
        ("keysight-edu36311a", "USB", "USB0::SIM::EDU36311A::INSTR", "trigger-list"),
        ("keysight-edu36311a", "USB", "USB0::SIM::EDU36311A::INSTR", "snapshot"),
        ("keysight-e3646a", "ASRL", "ASRL1::SIM::E3646A::INSTR", "protection"),
        ("keysight-e3646a", "ASRL", "ASRL1::SIM::E3646A::INSTR", "trigger-list"),
        ("keysight-e3646a", "ASRL", "ASRL1::SIM::E3646A::INSTR", "snapshot"),
    ],
)
def test_live_cli_check_unsupported_explicit_suites_fail_before_live(target, connection, resource, suite):
    result = _run_live_cli_check(
        "-Target",
        target,
        "-Connection",
        connection,
        "-Resource",
        resource,
        "-Suite",
        suite,
        "-PlanOnly",
    )

    assert result.returncode == 2
    assert "Unsupported suite" in (result.stdout + result.stderr)


def test_live_cli_check_e3646a_full_plan_contains_software_sequence_not_native_list():
    result = _run_live_cli_check(
        "-Target",
        "keysight-e3646a",
        "-Connection",
        "ASRL",
        "-Resource",
        "ASRL1::SIM::E3646A::INSTR",
        "-Suite",
        "full",
        "-PlanOnly",
        "-SkipExternalPreflight",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(_report_path(result.stdout, result.stderr).read_text(encoding="utf-8"))
    assert report["suites"] == ["readonly", "output", "software-sequence"]
    case_names = {case["name"] for case in report["cases"]}
    assert any(case["name"] == "log-one-sample" for case in report["cases"])
    private_log = _report_path(result.stdout, result.stderr).parent.parent / "private" / "preflight-log.csv"
    with private_log.open(newline="", encoding="utf-8") as handle:
        assert [int(row["channel"]) for row in csv.DictReader(handle)] == [1, 2]
    assert "sequence-unsupported-protection-dry-run" in case_names
    assert "sequence-unsupported-trigger-dry-run" in case_names
    assert "sequence-unsupported-snapshot-dry-run" in case_names
    assert "sequence-unsupported-restore-dry-run" in case_names
    assert "sequence-unsupported-native-list-dry-run" in case_names
    assert "sequence-unsupported-completion-pulse-dry-run" in case_names


def test_live_cli_check_full_suite_composition_is_model_aware():
    script = (Path("scripts") / "_validation_helpers.ps1").read_text(encoding="utf-8")

    assert '"keysight-e36312a" = [pscustomobject]@{' in script
    assert '"keysight-edu36311a" = [pscustomobject]@{' in script
    assert '"keysight-e3646a" = [pscustomobject]@{' in script
    assert 'suites = @("readonly", "output", "protection", "snapshot", "trigger-list", "software-sequence")' in script
    assert 'suites = @("readonly", "output", "protection", "software-sequence")' in script
    assert 'suites = @("readonly", "output", "software-sequence")' in script


def test_live_cli_check_log_validator_rejects_incomplete_or_error_artifacts(tmp_path):
    header = (
        "timestamp,resource,resource_alias,model,serial,channel,programmed_voltage,"
        "programmed_current,measured_voltage,measured_current,output_enabled,errors\n"
    )
    valid_rows = [
        f"2026-01-01T00:00:00Z,SIM,,E36312A,SIM,{channel},1,0.05,0,0,false,\n"
        for channel in (1, 2, 3)
    ]
    valid_events = [
        {"event": "sample", "sample": {"channel": channel}} for channel in (1, 2, 3)
    ] + [
        {
            "event": "summary",
            "samples_written": 1,
            "channels": [1, 2, 3],
            "stopped": False,
            "stop_reason": "completed",
        }
    ]
    scenarios = {
        "missing-files": (None, None),
        "wrong-row-count": (valid_rows[:2], valid_events),
        "nonempty-errors": (
            [*valid_rows[:2], valid_rows[2].rstrip("\n") + "-200 instrument error\n"],
            valid_events,
        ),
        "missing-summary": (valid_rows, valid_events[:-1]),
        "interrupted-summary": (
            valid_rows,
            [
                *valid_events[:-1],
                {
                    **valid_events[-1],
                    "stopped": True,
                    "stop_reason": "interrupted",
                },
            ],
        ),
    }
    for name, (rows, events) in scenarios.items():
        csv_path = tmp_path / f"{name}.csv"
        jsonl_path = tmp_path / f"{name}.jsonl"
        if rows is not None and events is not None:
            csv_path.write_text(header + "".join(rows), encoding="utf-8")
            jsonl_path.write_text(
                "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
            )
        command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$case = New-CommandCase -Name "log-test" -Suite "readonly" -Phase "preflight" -Args @("log") -ValidationKind "log" -ExpectedChannels @(1,2,3) -GeneratedArtifacts @("{csv_path}", "{jsonl_path}")
$payload = '{{"data":{{"samples_written":1,"stopped":false,"stop_reason":"completed"}}}}' | ConvertFrom-Json
$failures = @(Get-CaseAssertionFailures -Case $case -Payload $payload -Identity $null -OutputStates $null -InstrumentErrors $null -StderrPath "{tmp_path / 'empty.stderr'}")
if ($failures.Count -eq 0) {{ throw "expected log validation failure" }}
'''
        result = _run_powershell_command(command)
        assert result.returncode == 0, name + ": " + result.stdout + result.stderr


def test_live_cli_check_target_metadata_matches_core_registries():
    command = r'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$TargetMetadata | ConvertTo-Json -Depth 8 -Compress
'''
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    metadata = json.loads(result.stdout)
    from powers_tool_core.model_resolution import (
        MODEL_CHANNELS_BY_ID,
        SIMULATED_RESOURCE_FOR_MODEL_ID,
    )
    from powers_tool_core.models import PRODUCT_ACTIVE_MODEL_IDS

    assert set(metadata) == set(PRODUCT_ACTIVE_MODEL_IDS)
    for model_id, entry in metadata.items():
        assert entry["model_id"] == model_id
        assert entry["channels"] == list(MODEL_CHANNELS_BY_ID[model_id])
        assert entry["simulator_resource"] == SIMULATED_RESOURCE_FOR_MODEL_ID[model_id]


@pytest.mark.parametrize(
    ("target", "connection", "resource", "expected_suites", "expected_candidates"),
    [
        (
            "keysight-e36312a",
            "USB",
            "USB0::SIM::E36312A::INSTR",
            ["readonly", "output", "protection", "snapshot", "trigger-list", "software-sequence"],
            {
                "output-on",
                "log",
                "doctor",
                "measure-all",
                "restore-from-snapshot",
                "trigger-fire",
                "trigger-pulse",
            },
        ),
        (
            "keysight-edu36311a",
            "USB",
            "USB0::SIM::EDU36311A::INSTR",
            ["readonly", "output", "protection", "software-sequence"],
            {"output-on", "log", "doctor"},
        ),
        (
            "keysight-e3646a",
            "ASRL",
            "ASRL1::SIM::E3646A::INSTR",
            ["readonly", "output", "software-sequence"],
            {"output-on", "doctor", "log"},
        ),
    ],
)
def test_live_cli_check_full_plan_reports_expanded_software_sequence_suites(
    target: str,
    connection: str,
    resource: str,
    expected_suites: list[str],
    expected_candidates: set[str],
):
    result = _run_live_cli_check(
        "-Target",
        target,
        "-Connection",
        connection,
        "-Resource",
        resource,
        "-Suite",
        "full",
        "-PlanOnly",
        "-SkipExternalPreflight",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_path = _report_path(result.stdout, result.stderr)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report_path.with_name("summary.md").read_text(encoding="utf-8")
    assert report["suites"] == expected_suites
    assert "software-sequence" in report["suites"]
    assert "software-sequence" in summary
    planned = report["planned_live_cases"]
    candidate_commands = {
        case["command"]
        for case in planned
        if case["command"] in expected_candidates
    }
    assert candidate_commands == expected_candidates
    candidate_cases = [
        case for case in planned
        if case["command"] in expected_candidates and case["name"] != "restore-from-snapshot-plan"
    ]
    internal_markers = ("candidate_" + "context_required", "candidate_scope_required")
    assert all(marker not in case for marker in internal_markers for case in candidate_cases)
    if target == "keysight-e36312a":
        pulse = next(case for case in planned if case["command"] == "trigger-pulse")
        assert pulse["operator_interaction_required"] is True
    if target != "keysight-e36312a":
        assert not any(case["command"] == "restore-from-snapshot" for case in planned)
        assert not any(case["command"] == "measure-all" for case in planned)
    if target == "keysight-e3646a":
        log_case = next(case for case in planned if case["command"] == "log")
        assert log_case["name"] == "log-one-sample"
        assert log_case["arguments"][log_case["arguments"].index("--channel") + 1] == "all"
        global_on = next(case for case in planned if case["name"] == "output-on-global")
        assert global_on["arguments"][global_on["arguments"].index("--channel") + 1] == "1"
        assert sum(case["command"] == "output-on" for case in planned) == 1
    else:
        output_on_cases = [case for case in planned if case["command"] == "output-on" and case["suite"] == "output"]
        assert len(output_on_cases) == 3
        assert all("--confirm" in case["arguments"] for case in output_on_cases)
    if target == "keysight-e36312a":
        names = {case["name"] for case in planned}
        assert {"restore-off-execute", "restore-on-enable-ch1", "restore-on-execute", "restore-on-immediate-safe-off"} <= names
        restore_case = next(case for case in planned if case["name"] == "restore-on-enable-ch1")
        assert all(marker not in restore_case for marker in internal_markers)
    case_names = {case["name"] for case in report["cases"] if case["suite"] == "software-sequence"}
    assert {
        "ramp-list-lint",
        "ramp-list-dry-run",
        "sequence-lint-readonly",
        "sequence-dry-run-readonly",
    } <= case_names


@pytest.mark.parametrize(
    ("target", "connection", "resource"),
    [
        ("keysight-e36312a", "USB", "USB0::SIM::E36312A::INSTR"),
        ("keysight-edu36311a", "USB", "USB0::SIM::EDU36311A::INSTR"),
        ("keysight-e3646a", "ASRL", "ASRL1::SIM::E3646A::INSTR"),
    ],
)
def test_live_cli_check_software_sequence_plan_only_supported_for_active_targets(target: str, connection: str, resource: str):
    result = _run_live_cli_check(
        "-Target",
        target,
        "-Connection",
        connection,
        "-Resource",
        resource,
        "-Suite",
        "software-sequence",
        "-PlanOnly",
        "-SkipExternalPreflight",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_path = _report_path(result.stdout, result.stderr)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["suites"] == ["software-sequence"]
    command_names = [command["name"] for command in report["commands"]]
    assert "ramp-list-lint" in command_names
    assert "ramp-list-dry-run" in command_names
    assert "sequence-lint-readonly" in command_names
    assert "sequence-dry-run-readonly" in command_names
    assert len({command["json_path"] for command in report["commands"]}) == len(report["commands"])
    assert len({command["stdout_path"] for command in report["commands"]}) == len(report["commands"])
    assert len({command["stderr_path"] for command in report["commands"]}) == len(report["commands"])


@pytest.mark.parametrize(
    ("target", "connection", "resource", "expected_failures"),
    [
        (
            "keysight-edu36311a",
            "USB",
            "USB0::SIM::EDU36311A::INSTR",
            {
                "sequence-unsupported-trigger-dry-run",
                "sequence-unsupported-trigger-simulate",
                "sequence-unsupported-snapshot-dry-run",
                "sequence-unsupported-snapshot-simulate",
                "sequence-unsupported-restore-dry-run",
                "sequence-unsupported-restore-simulate",
                "sequence-unsupported-native-list-dry-run",
                "sequence-unsupported-native-list-simulate",
            },
        ),
        (
            "keysight-e3646a",
            "ASRL",
            "ASRL1::SIM::E3646A::INSTR",
            {
                "sequence-unsupported-protection-dry-run",
                "sequence-unsupported-protection-simulate",
                "sequence-unsupported-trigger-dry-run",
                "sequence-unsupported-trigger-simulate",
                "sequence-unsupported-snapshot-dry-run",
                "sequence-unsupported-snapshot-simulate",
                "sequence-unsupported-restore-dry-run",
                "sequence-unsupported-restore-simulate",
                "sequence-unsupported-native-list-dry-run",
                "sequence-unsupported-native-list-simulate",
                "sequence-unsupported-completion-pulse-dry-run",
                "sequence-unsupported-completion-pulse-simulate",
            },
        ),
    ],
)
def test_live_cli_check_software_sequence_expected_failures_are_reported_as_passed(
    target: str,
    connection: str,
    resource: str,
    expected_failures: set[str],
):
    result = _run_live_cli_check(
        "-Target",
        target,
        "-Connection",
        connection,
        "-Resource",
        resource,
        "-Suite",
        "software-sequence",
        "-PlanOnly",
        "-SkipExternalPreflight",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(_report_path(result.stdout, result.stderr).read_text(encoding="utf-8"))
    cases_by_name = {case["name"]: case for case in report["cases"]}
    assert expected_failures <= set(cases_by_name)
    for name in expected_failures:
        assert cases_by_name[name]["expected_success"] is False
        assert cases_by_name[name]["result"] == "passed"


def _cleanup_fixture_cli_path(
    tmp_path: Path,
    *,
    safe_off_ok: bool = True,
    output_state_ok: bool = True,
    error_queue_ok: bool = True,
    output_states: object = None,
    instrument_errors: list[str] | None = None,
) -> Path:
    fixture_cli = tmp_path / "powers_tool_cli"
    fixture_cli.mkdir()
    (fixture_cli / "__init__.py").write_text("", encoding="utf-8")
    config = json.dumps(
        {
            "safe_off_ok": safe_off_ok,
            "output_state_ok": output_state_ok,
            "error_queue_ok": error_queue_ok,
            "output_states": [
                {"channel": 1, "enabled": False},
                {"channel": 2, "enabled": False},
                {"channel": 3, "enabled": False},
            ] if output_states is None else output_states,
            "instrument_errors": [] if instrument_errors is None else instrument_errors,
        }
    )
    (fixture_cli / "cli.py").write_text(
        rf"""
import json
import sys

config = json.loads({config!r})
command = sys.argv[1]
payload = {{
    "ok": True,
    "error": None,
    "execution": {{"mode": "real", "dry_run": False, "hardware_touched": True}},
    "data": {{
        "resource": {{
            "resource": "TCPIP0::192.168.50.77::5025::SOCKET",
            "idn": {{
                "raw": "KEYSIGHT,E36312A,MY12345678,2.10",
                "manufacturer": "KEYSIGHT",
                "model": "E36312A",
                "serial": "MY12345678",
                "firmware": "2.10",
                "parse_ok": True,
            }},
        }},
        "external_path": r"C:\\Users\\Example User\\private\\sequence.yaml",
    }},
}}
if command == "safe-off" and not config["safe_off_ok"]:
    payload["ok"] = False
    payload["error"] = {{"code": "safe_off_failed", "message": "safe-off failed"}}
elif command == "output-state":
    payload["data"] = {{"outputs": config["output_states"]}}
    if not config["output_state_ok"]:
        payload["ok"] = False
        payload["error"] = {{"code": "output_state_failed", "message": "output-state failed"}}
elif command == "error":
    payload["data"] = {{"errors": config["instrument_errors"]}}
    if not config["error_queue_ok"]:
        payload["ok"] = False
        payload["error"] = {{"code": "error_queue_failed", "message": "error queue failed"}}

print(r"TCPIP0::192.168.50.77::5025::SOCKET KEYSIGHT,E36312A,MY12345678,2.10 C:\Users\Example User\private\sequence.yaml")
print(r"TCPIP0::192.168.50.77::5025::SOCKET MY12345678", file=sys.stderr)
save_path = sys.argv[sys.argv.index("--save-json") + 1]
with open(save_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
sys.exit(0 if payload["ok"] else 2)
""".lstrip(),
        encoding="utf-8",
    )
    return tmp_path


def _e3646a_null_identity_cleanup_fixture_cli_path(
    tmp_path: Path, *, malformed_identity: bool = False
) -> Path:
    fixture_cli = tmp_path / "powers_tool_cli"
    fixture_cli.mkdir()
    (fixture_cli / "__init__.py").write_text("", encoding="utf-8")
    identity = "bad" if malformed_identity else None
    (fixture_cli / "cli.py").write_text(
        f'''
import json
import sys

command = sys.argv[1]
resource = {{
    "idn": {identity!r},
    "interface": "ASRL",
    "model_id": "keysight-e3646a",
    "name": "ASRL1::FIXTURE::E3646A::INSTR",
    "reachable": True,
    "simulated": False,
    "vendor_id": "keysight",
}}
data = {{"resource": resource}}
if command == "clear":
    data["cleared"] = True
elif command == "output-state":
    data.update({{
        "channel": "all",
        "outputs": [
            {{"channel": 1, "enabled": False}},
            {{"channel": 2, "enabled": False}},
        ],
    }})
elif command == "error":
    data.update({{"errors": [], "max_reads": 20, "read_count": 1}})

payload = {{
    "ok": True,
    "error": None,
    "execution": {{"mode": "real", "dry_run": False, "hardware_touched": True}},
    "data": data,
}}
save_path = sys.argv[sys.argv.index("--save-json") + 1]
with open(save_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
'''.lstrip(),
        encoding="utf-8",
    )
    return tmp_path


def _error_evidence_fixture_cli_path(tmp_path: Path, data: object) -> Path:
    fixture_cli = tmp_path / "powers_tool_cli"
    fixture_cli.mkdir()
    (fixture_cli / "__init__.py").write_text("", encoding="utf-8")
    (fixture_cli / "cli.py").write_text(
        f"""
import json
import sys

payload = {{
    "ok": True,
    "error": None,
    "execution": {{"mode": "real", "dry_run": False, "hardware_touched": True}},
    "data": json.loads({json.dumps(json.dumps(data))}),
}}
save_path = sys.argv[sys.argv.index("--save-json") + 1]
with open(save_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
print(json.dumps(payload))
""".lstrip(),
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.parametrize(
    ("data", "expected_result"),
    [
        ({}, "failed"),
        ({"errors": None}, "failed"),
        ({"errors": []}, "passed"),
        ({"errors": ["-200,Instrument error"]}, "failed"),
        ({"errors": "-200,Instrument error"}, "failed"),
        ({"errors": {"code": -200}}, "failed"),
    ],
)
def test_live_cli_check_error_evidence_is_fail_closed_in_report(
    tmp_path, data, expected_result
) -> None:
    fixture_path = _error_evidence_fixture_cli_path(tmp_path, data)
    output_dir = tmp_path / "out"
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "USB0::FIXTURE::INSTR"
$script:ResourceDisplay = "USB:<redacted-resource>"
$script:ConnectionLabel = "USB"
$script:TransportScope = "usb"
$script:BackendArtifact = Get-BackendArtifactFields -Value $null
$script:BackendValue = $null
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:SuitesToRun = @("readonly")
$script:Suite = "readonly"
$script:StateChanging = $false
$script:Restore = $false
$script:PlanOnly = $false
$case = New-CommandCase -Name "readonly-error-queue-checkpoint" -Suite "readonly" -Phase "live" -Args @("error", "--json", "--resource", $script:RawResource, "--max-reads", "20") -LiveHardwareExpected:$true -ValidationKind "empty-errors"
$record = Invoke-ValidationCommand -Case $case
$result = if ($script:Failures.Count -eq 0) {{ "passed" }} else {{ "failed" }}
Write-ValidationArtifacts -ValidationMode "live" -Result $result -StartedAt (Get-Date)
Write-Output (Join-Path $script:ShareableArtifactDir "report.json")
'''
    result = _run_powershell_command(command, env={"PYTHONPATH": str(fixture_path)})

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(Path(result.stdout.strip().splitlines()[-1]).read_text(encoding="utf-8"))
    assert report["result"] == expected_result
    record = next(
        command
        for command in report["commands"]
        if command["name"] == "readonly-error-queue-checkpoint"
    )
    assert record["result"] == expected_result
    if data == {"errors": []}:
        assert isinstance(record["instrument_errors_observed"], list)
        assert record["instrument_errors_observed"] == []


def test_live_cli_check_uses_readonly_error_queue_checkpoint_name() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'New-CommandCase -Name "readonly-error-queue-checkpoint"' in script
    assert 'New-CommandCase -Name "measure-all-error-queue"' not in script


def _run_e3646a_null_identity_cleanup_fixture(
    tmp_path: Path, *, malformed_identity: bool = False, cleanup: bool = True
) -> dict[str, object]:
    fixture_path = _e3646a_null_identity_cleanup_fixture_cli_path(
        tmp_path, malformed_identity=malformed_identity
    )
    output_dir = tmp_path / "out"
    cleanup_command = "Invoke-SafeOffCleanup -Role \"final\"" if cleanup else ""
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e3646a"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "ASRL1::FIXTURE::E3646A::INSTR"
$script:ResourceDisplay = "ASRL:<redacted-resource>"
$script:ConnectionLabel = "ASRL"
$script:TransportScope = "asrl"
$script:BackendArtifact = Get-BackendArtifactFields -Value $null
$script:BackendValue = $null
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:InstrumentIdentity = $null
$script:SuitesToRun = @("readonly", "output")
$script:Suite = "full"
$script:StateChanging = $true
$script:Restore = $true
$script:PlanOnly = $false
$case = New-CommandCase -Name "clear" -Suite "readonly" -Phase "live" -Args @("clear", "--json", "--resource", $script:RawResource) -LiveHardwareExpected:$true
$clearRecord = Invoke-ValidationCommand -Case $case
{cleanup_command}
[pscustomobject]@{{
    clear = $clearRecord
    cleanup = $script:CleanupEvidence
    failures = $script:Failures.ToArray()
    commands = $script:CommandRecords.ToArray()
}} | ConvertTo-Json -Depth 20 -Compress
'''
    result = _run_powershell_command(command, env={"PYTHONPATH": str(fixture_path)})

    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip())


def test_e3646a_null_identity_placeholder_does_not_break_cleanup_error_evidence(
    tmp_path,
):
    run = _run_e3646a_null_identity_cleanup_fixture(tmp_path)

    assert run["clear"]["result"] == "passed"
    assert run["clear"]["identity_observed"] is False
    assert run["cleanup"]["status"] == "passed"
    assert run["cleanup"]["error_queue_checked"] is True
    assert run["cleanup"]["instrument_errors"] == []
    error_record = next(
        record for record in run["commands"] if record["name"] == "cleanup-error-queue"
    )
    assert error_record["result"] == "passed"
    assert error_record["identity_observed"] is False
    assert error_record["instrument_errors_observed"] == []
    assert "Cleanup could not verify the instrument error queue." not in run["failures"]


def test_e3646a_non_null_malformed_identity_placeholder_fails_closed(tmp_path):
    run = _run_e3646a_null_identity_cleanup_fixture(
        tmp_path, malformed_identity=True, cleanup=False
    )

    assert run["clear"]["result"] == "failed"
    assert run["clear"]["identity_observed"] is False
    assert run["clear"]["assertion_failures"] == [
        "observed identity evidence IDN value must be an object."
    ]


def _run_state_changing_fixture(
    output_dir: Path,
    *,
    restore: bool = True,
    expect_result: str = "passed",
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    command = rf"""
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "TCPIP0::192.168.50.77::5025::SOCKET"
$script:ResourceDisplay = "LAN:<redacted-resource>"
$script:NormalizedTarget = "keysight-e36312a"
$script:ConnectionLabel = "LAN"
$script:TransportScope = "tcpip"
$script:BackendArtifact = Get-BackendArtifactFields -Value "@py"
$script:BackendValue = "@py"
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:SuitesToRun = @("output")
$script:Suite = "output"
$script:StateChanging = $true
$script:Restore = ${str(restore).lower()}
$script:PlanOnly = $false
$case = New-CommandCase -Name "fixture-set" -Suite "output" -Phase "live" -Args @("set", "--json", "--resource", $script:RawResource, "--channel", "1", "--voltage", "1", "--current", "0.05", "--confirm") -StateChanging:$true -LiveHardwareExpected:$true
Invoke-ValidationCommand -Case $case | Out-Null
Invoke-SafeOffCleanup -Role "final"
$result = if ($script:Failures.Count -eq 0) {{ "passed" }} else {{ "failed" }}
if (-not $script:Restore -and $result -eq "passed") {{ $result = "passed_without_cleanup_verification" }}
Write-ValidationArtifacts -ValidationMode "live" -Result $result -StartedAt (Get-Date)
if ($result -ne "{expect_result}") {{ throw "expected {expect_result}, got $result" }}
Write-Output (Join-Path $script:ShareableArtifactDir "report.json")
"""
    return _run_powershell_command(command, env=env)


def test_live_cli_check_shareable_artifacts_recursively_redact_private_live_fixture(tmp_path):
    fixture_path = _cleanup_fixture_cli_path(tmp_path)
    result = _run_state_changing_fixture(
        tmp_path / "out",
        env={"PYTHONPATH": str(fixture_path)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report_path = Path(result.stdout.strip())
    shareable_dir = report_path.parent
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "2.0"
    assert shareable_dir.name == "shareable"
    assert report["shareable_artifact_dir"].endswith("\\shareable")
    assert report["instrument_identity"] == {
        "availability": "observed",
        "manufacturer": "KEYSIGHT",
        "detected_model": "E36312A",
        "firmware": "2.10",
        "serial": "<redacted>",
        "serial_redacted": True,
        "source_command": "fixture-set",
    }
    assert all("\\shareable\\" in value for command in report["commands"] for value in (command["json_path"], command["stdout_path"], command["stderr_path"]))
    assert all("\\private\\" not in " ".join(command["arguments"]) for command in report["commands"])
    forbidden = (
        "TCPIP0::192.168.50.77::5025::SOCKET",
        "192.168.50.77",
        "MY12345678",
        "KEYSIGHT,E36312A,MY12345678,2.10",
        r"C:\Users\Example User",
        str(Path.cwd()),
        str(Path(sys.executable)),
    )
    shareable_text = "\n".join(path.read_text(encoding="utf-8") for path in shareable_dir.rglob("*") if path.is_file())
    assert all(value not in shareable_text for value in forbidden)
    for expected in ("KEYSIGHT", "E36312A", "2.10", "fixture-set", "transport_scope", "backend_scope"):
        assert expected in shareable_text
    shareable_payload = json.loads((shareable_dir / "live-fixture-set-attempt-1.json").read_text(encoding="utf-8"))
    assert shareable_payload["data"]["resource"]["idn"]["raw"] == "<redacted-idn>"
    assert shareable_payload["data"]["resource"]["idn"]["serial"] == "<redacted>"
    assert (shareable_dir.parent / "private").is_dir()


@pytest.mark.parametrize(
    ("safe_off_ok", "output_states", "instrument_errors", "cleanup_status", "failure_fragment"),
    [
        (False, [{"channel": 1, "enabled": False}, {"channel": 2, "enabled": False}, {"channel": 3, "enabled": False}], [], "failed", "Cleanup safe-off command failed."),
        (True, [{"channel": 1, "enabled": True}, {"channel": 2, "enabled": False}, {"channel": 3, "enabled": False}], [], "failed", "Cleanup could not confirm that all outputs are off."),
        (True, [{"channel": 1, "enabled": None}, {"channel": 2, "enabled": False}, {"channel": 3, "enabled": False}], [], "partial", "Cleanup did not produce verifiable output-state evidence."),
        (True, [{"channel": 1, "enabled": False}, {"channel": 2, "enabled": False}, {"channel": 3, "enabled": False}], ["-200,Instrument error"], "partial", "Cleanup finished with instrument errors."),
    ],
)
def test_live_cli_check_required_state_cleanup_incomplete_forces_failed_result(
    tmp_path,
    safe_off_ok,
    output_states,
    instrument_errors,
    cleanup_status,
    failure_fragment,
):
    fixture_path = _cleanup_fixture_cli_path(
        tmp_path,
        safe_off_ok=safe_off_ok,
        output_states=output_states,
        instrument_errors=instrument_errors,
    )
    result = _run_state_changing_fixture(
        tmp_path / "out",
        expect_result="failed",
        env={"PYTHONPATH": str(fixture_path)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(Path(result.stdout.strip()).read_text(encoding="utf-8"))
    assert report["result"] == "failed"
    assert report["cleanup"]["status"] == cleanup_status
    assert failure_fragment in report["failures"]


@pytest.mark.parametrize(
    ("fixture_kwargs", "failure_fragment"),
    [
        ({"output_state_ok": False}, "Cleanup did not produce verifiable output-state evidence."),
        ({"error_queue_ok": False}, "Cleanup could not verify the instrument error queue."),
    ],
)
def test_live_cli_check_required_state_cleanup_command_failures_are_not_passed(
    tmp_path,
    fixture_kwargs,
    failure_fragment,
):
    fixture_path = _cleanup_fixture_cli_path(tmp_path, **fixture_kwargs)
    result = _run_state_changing_fixture(
        tmp_path / "out",
        expect_result="failed",
        env={"PYTHONPATH": str(fixture_path)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(Path(result.stdout.strip()).read_text(encoding="utf-8"))
    assert report["cleanup"]["status"] == "partial"
    assert failure_fragment in report["failures"]
    assert report["failures"].count(failure_fragment) == 1


def test_live_cli_check_restore_false_is_truthfully_not_cleanup_verified(tmp_path):
    fixture_path = _cleanup_fixture_cli_path(tmp_path)
    result = _run_state_changing_fixture(
        tmp_path / "out",
        restore=False,
        expect_result="passed_without_cleanup_verification",
        env={"PYTHONPATH": str(fixture_path)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(Path(result.stdout.strip()).read_text(encoding="utf-8"))
    assert report["cleanup"]["requested"] is False
    assert report["cleanup"]["attempted"] is False
    assert report["cleanup"]["status"] == "skipped_by_operator"
    assert report["result"] == "passed_without_cleanup_verification"


def test_live_cli_check_cleanup_lifecycle_statuses_are_distinct():
    command = r"""
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:StateChanging = $true
$script:Restore = $true
$planned = New-CleanupEvidence -ValidationMode "planned"
$preflight = New-CleanupEvidence -ValidationMode "preflight_failed"
$confirmation = New-CleanupEvidence -ValidationMode "confirmation_required"
$script:StateChanging = $false
$readonly = New-CleanupEvidence -ValidationMode "live"
$script:StateChanging = $true
$script:Restore = $false
$skipped = New-CleanupEvidence -ValidationMode "live"
@{ planned = $planned.status; preflight = $preflight.status; confirmation = $confirmation.status; readonly = $readonly.status; skipped = $skipped.status } | ConvertTo-Json -Compress
"""
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "planned": "not_executed_plan_only",
        "preflight": "not_executed_preflight_failed",
        "confirmation": "not_executed_confirmation_required",
        "readonly": "not_required",
        "skipped": "skipped_by_operator",
    }


@pytest.mark.parametrize(
    "target",
    [
        "E36312A",
        "EDU36311A",
        "E3646A",
        "GENERIC",
        "generic-scpi",
        "keysight-e36103b",
        "keysight-e36232a",
        "keysight-e36313a",
    ],
)
def test_live_cli_check_noncanonical_or_inactive_targets_fail_before_live(target: str):
    result = _run_live_cli_check(
        "-Target",
        target,
        "-Connection",
        "USB",
        "-Resource",
        "USB0::SIM::E36312A::INSTR",
        "-Suite",
        "readonly",
        "-PlanOnly",
    )

    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "Unsupported -Target" in combined
    assert "Running no-hardware preflight" not in result.stdout


def test_english_docs_describe_contributor_validation_workflow():
    contributor = Path("docs/CONTRIBUTING.md").read_text(encoding="utf-8")
    normalized = " ".join(contributor.split())

    assert "live-cli-check.ps1" in contributor
    assert "-PlanOnly" in contributor
    assert "private/" in contributor
    assert "shareable/" in contributor
    assert "Passing artifacts are candidate evidence only." in normalized


def test_english_docs_describe_cli_suite_scope():
    cli_readme = Path("docs/cli/README.md").read_text(encoding="utf-8")
    contributor = Path("docs/CONTRIBUTING.md").read_text(encoding="utf-8")

    cli_normalized = " ".join(cli_readme.split())
    artifact_requirements = contributor.split("## Artifact requirements", 1)[1]
    evidence_scope = artifact_requirements.split(
        "## Power-supply safety and privacy", 1
    )[0]
    evidence_scope_normalized = " ".join(evidence_scope.split())

    assert "does not validate the entire model" in cli_normalized
    assert "broaden Product support" in cli_normalized
    assert "preflight-cli.ps1" in cli_readme

    for token in (
        "model_id",
        "transport",
        "backend",
        "command",
        "required feature",
    ):
        assert token in evidence_scope

    assert "cannot be inherited" in evidence_scope_normalized
    assert (
        "does not update Product support automatically"
        in evidence_scope_normalized
    )


def test_english_docs_describe_supported_e3646a_product_boundaries():
    supported = Path("docs/core/supported-models.md").read_text(encoding="utf-8")
    normalized = " ".join(supported.split())

    assert "E3646A product execution is limited to ASRL / RS-232 + system VISA" in normalized
    assert "E3646A `ramp-list` is software setpoint stepping" in normalized
    assert "E3646A `sequence` is a software workflow" in normalized
    assert "native instrument LIST support" in normalized
    assert "OUTP ON/OFF" in supported
    assert "Trigger workflows are E36312A-only" in normalized
    assert "EDU36311A trigger commands remain disabled" in normalized


def _tcpip_session_fixture_cli_path(tmp_path: Path) -> Path:
    fixture_cli = tmp_path / "powers_tool_cli"
    fixture_cli.mkdir()
    (fixture_cli / "__init__.py").write_text("", encoding="utf-8")
    (fixture_cli / "cli.py").write_text(
        r'''
import json
import os
import sys
from pathlib import Path

mode = os.environ["TCPIP_FIXTURE_MODE"]
state_path = Path(os.environ["TCPIP_FIXTURE_STATE"])
count = int(state_path.read_text(encoding="utf-8")) if state_path.exists() else 0
count += 1
state_path.write_text(str(count), encoding="utf-8")
command = sys.argv[1]

def success_data():
    if command == "output-state":
        return {
            "outputs": [
                {"channel": 1, "enabled": False},
                {"channel": 2, "enabled": False},
                {"channel": 3, "enabled": False},
            ]
        }
    if command == "error":
        return {"errors": []}
    return {"resource": {"idn": None}}

failure = mode in {"recover", "generated", "recover-payload-assertion"} and count == 1
failure = failure or mode in {"persistent", "partial"}
if mode == "cleanup-recover":
    failure = command == "safe-off" and count == 1
if mode == "cleanup-persistent":
    failure = command == "safe-off"

if mode == "policy":
    payload = {
        "schema_version": 2,
        "status": "error",
        "ok": False,
        "command": {"name": command},
        "data": None,
        "error": {
            "type": "policy",
            "code": "policy_rejected",
            "message": "validation policy rejected the request",
            "retryable": False,
        },
        "execution": {"mode": "real", "dry_run": False, "hardware_touched": False},
    }
    exit_code = 3
elif mode == "argument":
    payload = {
        "schema_version": 2,
        "status": "error",
        "ok": False,
        "command": {"name": command},
        "data": None,
        "error": {
            "type": "argument",
            "code": "invalid_argument",
            "message": "invalid argument",
            "retryable": False,
        },
        "execution": {"mode": "real", "dry_run": False, "hardware_touched": False},
    }
    exit_code = 2
elif mode == "identity-assertion":
    payload = {
        "schema_version": 2,
        "status": "ok",
        "ok": True,
        "command": {"name": command},
        "data": {"idn": "not-an-object"},
        "error": None,
        "execution": {"mode": "real", "dry_run": False, "hardware_touched": True},
    }
    exit_code = 0
elif mode == "payload-assertion" or (mode == "recover-payload-assertion" and count > 1):
    payload = {
        "schema_version": 2,
        "status": "ok",
        "ok": True,
        "command": {"name": command},
        "data": {"outputs": "not-a-list"},
        "error": None,
        "execution": {"mode": "real", "dry_run": False, "hardware_touched": True},
    }
    exit_code = 0
elif failure or mode == "scpi-failure":
    payload = {
        "schema_version": 2,
        "status": "error",
        "ok": False,
        "command": {"name": command},
        "data": None,
        "error": {
            "type": "connection",
            "code": "connection_failed" if command != "capabilities" else "capabilities_failed",
            "message": f"{command} failed: Could not open VISA resource 'TCPIP0::FIXTURE::INSTR'",
            "retryable": True,
        },
        "execution": {"mode": "real", "dry_run": False, "hardware_touched": True},
    }
    if mode == "partial":
        payload["data"] = {"partial": True}
    exit_code = 3
    if mode == "scpi-failure":
        print("TCPIP0::FIXTURE::INSTR SCPI >> *IDN?", file=sys.stderr)
    if mode == "generated":
        Path(os.environ["TCPIP_FIXTURE_GENERATED"]).write_text("attempt-one", encoding="utf-8")
else:
    payload = {
        "schema_version": 2,
        "status": "ok",
        "ok": True,
        "command": {"name": command},
        "data": success_data(),
        "error": None,
        "execution": {"mode": "real", "dry_run": False, "hardware_touched": True},
    }
    exit_code = 0

save_indexes = [index for index, value in enumerate(sys.argv) if value == "--save-json"]
if len(save_indexes) != 1:
    raise SystemExit(91)
save_path = Path(sys.argv[save_indexes[0] + 1])
save_path.write_text(json.dumps(payload), encoding="utf-8")
print(json.dumps({"attempt": count, "command": command}))
raise SystemExit(exit_code)
'''.lstrip(),
        encoding="utf-8",
    )
    return tmp_path


def _run_tcpip_session_fixture(
    tmp_path: Path,
    *,
    mode: str,
    transport: str = "tcpip",
    phase: str = "live",
    command_name: str = "clear",
    state_changing: bool = False,
    validation_kind: str = "",
    generated_artifact: bool = False,
    target: str = "keysight-e36312a",
) -> dict[str, object]:
    fixture_path = _tcpip_session_fixture_cli_path(tmp_path)
    output_dir = tmp_path / "out"
    state_path = tmp_path / "attempt-count.txt"
    generated_path = tmp_path / "command-output.json"
    connection = {"tcpip": "LAN", "usb": "USB", "asrl": "ASRL"}[transport]
    generated = f'-GeneratedArtifacts @("{generated_path}")' if generated_artifact else ""
    validation = f'-ValidationKind "{validation_kind}"' if validation_kind else ""
    expected_channels = "-ExpectedChannels @(1,2,3)" if command_name == "output-state" else ""
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
function Get-FileHash {{ throw "legacy Get-FileHash must not be invoked" }}
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "{target}"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "TCPIP0::FIXTURE::INSTR"
$script:ResourceDisplay = "{connection}:<redacted-resource>"
$script:ConnectionLabel = "{connection}"
$script:TransportScope = "{transport}"
$script:BackendArtifact = Get-BackendArtifactFields -Value $null
$script:BackendValue = $null
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:InstrumentIdentity = $null
$script:Restore = $true
$script:PlanOnly = $false
$script:LiveTcpipSubprocessAttempted = $false
$script:SleepCalls = New-Object System.Collections.Generic.List[int]
function Start-Sleep {{ param([int]$Milliseconds); $script:SleepCalls.Add($Milliseconds) }}
$case = New-CommandCase -Name "fixture-{command_name}" -Suite "readonly" -Phase "{phase}" -Args @("{command_name}", "--json", "--resource", $script:RawResource, "--save-json", "legacy.json") -StateChanging:${str(state_changing).lower()} -LiveHardwareExpected:$true {validation} {expected_channels} {generated}
$record = Invoke-ValidationCommand -Case $case
[pscustomobject]@{{
    record = $record
    sleeps = $script:SleepCalls.ToArray()
    failures = $script:Failures.ToArray()
    files = @((Get-ChildItem -LiteralPath $script:OutputDir -Recurse -File).Name | Sort-Object)
}} | ConvertTo-Json -Depth 30 -Compress
'''
    env = {
        "PYTHONPATH": str(fixture_path),
        "TCPIP_FIXTURE_MODE": mode,
        "TCPIP_FIXTURE_STATE": str(state_path),
        "TCPIP_FIXTURE_GENERATED": str(generated_path),
    }
    result = _run_powershell_command(command, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_generated_artifact_fingerprints_use_dotnet_sha256_and_preserve_nonfile_shapes(tmp_path):
    file_path = tmp_path / "artifact.txt"
    missing_path = tmp_path / "missing.txt"
    directory_path = tmp_path / "artifact-directory"
    file_path.write_bytes(b"abc")
    directory_path.mkdir()
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
function Get-FileHash {{ throw "legacy Get-FileHash must not be invoked" }}
$fileFingerprint = @(Get-GeneratedArtifactFingerprints -Paths @("{file_path}"))[0][0]
$missingFingerprint = @(Get-GeneratedArtifactFingerprints -Paths @("{missing_path}"))[0][0]
$directoryFingerprint = @(Get-GeneratedArtifactFingerprints -Paths @("{directory_path}"))[0][0]
[pscustomobject]@{{
    direct_sha256 = Get-FileSha256 -LiteralPath "{file_path}"
    file = $fileFingerprint
    missing = $missingFingerprint
    directory = $directoryFingerprint
}} | ConvertTo-Json -Depth 10 -Compress
'''
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    fingerprints = json.loads(result.stdout.strip())
    expected_sha256 = "BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD"
    assert fingerprints["direct_sha256"] == expected_sha256
    assert fingerprints["file"]["sha256"] == expected_sha256
    assert fingerprints["direct_sha256"] == fingerprints["file"]["sha256"]
    assert set(fingerprints["file"]) == {
        "path",
        "exists",
        "kind",
        "length",
        "last_write_utc_ticks",
        "sha256",
    }
    assert fingerprints["file"]["exists"] is True
    assert fingerprints["file"]["kind"] == "file"
    assert fingerprints["file"]["length"] == 3
    assert isinstance(fingerprints["file"]["last_write_utc_ticks"], int)
    assert set(fingerprints["missing"]) == set(fingerprints["file"])
    assert fingerprints["missing"] == {
        "path": str(missing_path.resolve()),
        "exists": False,
        "kind": None,
        "length": None,
        "last_write_utc_ticks": None,
        "sha256": None,
    }
    assert set(fingerprints["directory"]) == set(fingerprints["file"])
    assert fingerprints["directory"]["exists"] is True
    assert fingerprints["directory"]["kind"] == "directory"
    assert fingerprints["directory"]["length"] is None
    assert isinstance(fingerprints["directory"]["last_write_utc_ticks"], int)
    assert fingerprints["directory"]["sha256"] is None


def test_tcpip_first_pre_io_open_failure_recovers_once_with_attempt_artifacts(tmp_path):
    run = _run_tcpip_session_fixture(tmp_path, mode="recover")
    record = run["record"]

    assert record["result"] == "passed"
    assert record["attempt_count"] == 2
    assert record["recovery_attempted"] is True
    assert record["recovered_after_open_failure"] is True
    assert record["final_attempt"] == 2
    assert record["first_error_code"] == "connection_failed"
    assert "TCPIP0::FIXTURE::INSTR" not in record["first_error_message"]
    assert record["first_scpi_transcript_empty"] is True
    assert record["settle_delay_ms"] == 500
    assert [attempt["settle_before_ms"] for attempt in record["attempts"]] == [0, 500]
    assert run["sleeps"] == [500]
    assert record["json_path"].endswith("live-fixture-clear-attempt-2.json")
    assert "live-fixture-clear-attempt-1.json" in run["files"]
    assert "live-fixture-clear-attempt-2.json" in run["files"]
    assert "legacy.json" not in run["files"]
    private_dir = tmp_path / "out" / "private"
    assert '"attempt": 1' in (private_dir / "live-fixture-clear-attempt-1.stdout.txt").read_text(encoding="utf-16")
    assert '"attempt": 2' in (private_dir / "live-fixture-clear-attempt-2.stdout.txt").read_text(encoding="utf-16")


def test_tcpip_command_specific_connection_code_can_recover(tmp_path):
    run = _run_tcpip_session_fixture(
        tmp_path,
        mode="recover",
        command_name="capabilities",
    )

    assert run["record"]["result"] == "passed"
    assert run["record"]["first_error_code"] == "capabilities_failed"
    assert run["record"]["recovered_after_open_failure"] is True


def test_recovered_cli_execution_can_still_fail_final_payload_assertions(tmp_path):
    run = _run_tcpip_session_fixture(
        tmp_path,
        mode="recover-payload-assertion",
        command_name="output-state",
        validation_kind="output-state",
    )
    record = run["record"]

    assert record["attempt_count"] == 2
    assert record["recovery_attempted"] is True
    assert record["recovered_after_open_failure"] is True
    assert record["final_attempt"] == 2
    assert record["result"] == "failed"
    assert record["assertion_failures"]


def test_tcpip_persistent_open_failure_fails_after_one_recovery(tmp_path):
    run = _run_tcpip_session_fixture(tmp_path, mode="persistent")
    record = run["record"]

    assert record["result"] == "failed"
    assert record["attempt_count"] == 2
    assert record["recovery_attempted"] is True
    assert record["recovered_after_open_failure"] is False
    assert record["final_attempt"] == 2
    assert run["sleeps"] == [500]


@pytest.mark.parametrize("transport", ["usb", "asrl"])
def test_non_tcpip_open_failure_does_not_retry_or_sleep(tmp_path, transport):
    run = _run_tcpip_session_fixture(tmp_path, mode="persistent", transport=transport)

    assert run["record"]["attempt_count"] == 1
    assert run["record"]["recovery_attempted"] is False
    assert run["sleeps"] == []


@pytest.mark.parametrize(
    ("mode", "command_name", "state_changing", "validation_kind"),
    [
        ("scpi-failure", "clear", False, ""),
        ("scpi-failure", "safe-off", True, ""),
        ("policy", "clear", False, ""),
        ("argument", "clear", False, ""),
        ("partial", "clear", False, ""),
        ("identity-assertion", "clear", False, ""),
        ("payload-assertion", "output-state", False, "output-state"),
    ],
)
def test_tcpip_non_pre_io_failures_do_not_retry(
    tmp_path, mode, command_name, state_changing, validation_kind
):
    run = _run_tcpip_session_fixture(
        tmp_path,
        mode=mode,
        command_name=command_name,
        state_changing=state_changing,
        validation_kind=validation_kind,
    )

    assert run["record"]["attempt_count"] == 1
    assert run["record"]["recovery_attempted"] is False
    assert run["sleeps"] == []


def test_tcpip_generated_artifact_change_blocks_recovery(tmp_path):
    run = _run_tcpip_session_fixture(
        tmp_path,
        mode="generated",
        command_name="snapshot",
        generated_artifact=True,
    )

    assert run["record"]["attempt_count"] == 1
    assert run["record"]["recovery_attempted"] is False
    assert run["record"]["attempts"][0]["generated_artifacts_changed"] is True
    assert run["sleeps"] == []


@pytest.mark.parametrize("command_name", ["log", "snapshot"])
def test_tcpip_functional_generated_outputs_are_not_attempt_isolated_or_overwritten(
    tmp_path, command_name
):
    run = _run_tcpip_session_fixture(
        tmp_path,
        mode="generated",
        command_name=command_name,
        generated_artifact=True,
    )

    assert run["record"]["attempt_count"] == 1
    assert run["record"]["attempts"][0]["generated_artifacts_changed"] is True
    assert (tmp_path / "command-output.json").read_text(encoding="utf-8") == "attempt-one"
    assert not any("command-output-attempt" in name for name in run["files"])


@pytest.mark.parametrize(
    "target",
    ["keysight-e36312a", "keysight-edu36311a", "keysight-e3646a"],
)
def test_tcpip_recovery_semantics_are_model_independent(tmp_path, target):
    run = _run_tcpip_session_fixture(tmp_path, mode="recover", target=target)

    assert run["record"]["result"] == "passed"
    assert run["record"]["attempt_count"] == 2
    assert run["record"]["recovered_after_open_failure"] is True
    assert run["sleeps"] == [500]


def test_tcpip_preflight_case_does_not_retry_or_sleep(tmp_path):
    run = _run_tcpip_session_fixture(
        tmp_path,
        mode="persistent",
        phase="preflight",
    )

    assert run["record"]["attempt_count"] == 1
    assert run["record"]["recovery_attempted"] is False
    assert run["sleeps"] == []


def _run_tcpip_cleanup_fixture(tmp_path: Path, *, mode: str) -> dict[str, object]:
    fixture_path = _tcpip_session_fixture_cli_path(tmp_path)
    output_dir = tmp_path / "out"
    state_path = tmp_path / "attempt-count.txt"
    command = rf'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:CliExecutable = $PythonExe
$script:CliPrefix = @("-m", "powers_tool_cli.cli")
$script:NormalizedTarget = "keysight-e36312a"
$script:OutputDir = "{output_dir}"
New-Item -ItemType Directory -Path $script:OutputDir -Force | Out-Null
$script:RawResource = "TCPIP0::FIXTURE::INSTR"
$script:ResourceDisplay = "LAN:<redacted-resource>"
$script:ConnectionLabel = "LAN"
$script:TransportScope = "tcpip"
$script:BackendArtifact = Get-BackendArtifactFields -Value $null
$script:BackendValue = $null
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:CommandRecords = New-Object System.Collections.Generic.List[object]
$script:Failures = New-Object System.Collections.Generic.List[string]
$script:InstrumentIdentity = $null
$script:StateChanging = $true
$script:Restore = $true
$script:PlanOnly = $false
$script:LiveTcpipSubprocessAttempted = $false
$script:SleepCalls = New-Object System.Collections.Generic.List[int]
function Start-Sleep {{ param([int]$Milliseconds); $script:SleepCalls.Add($Milliseconds) }}
Invoke-SafeOffCleanup -Role "final"
[pscustomobject]@{{
    cleanup = $script:CleanupEvidence
    commands = $script:CommandRecords.ToArray()
    sleeps = $script:SleepCalls.ToArray()
    failures = $script:Failures.ToArray()
}} | ConvertTo-Json -Depth 30 -Compress
'''
    result = _run_powershell_command(
        command,
        env={
            "PYTHONPATH": str(fixture_path),
            "TCPIP_FIXTURE_MODE": mode,
            "TCPIP_FIXTURE_STATE": str(state_path),
            "TCPIP_FIXTURE_GENERATED": str(tmp_path / "unused.json"),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_tcpip_cleanup_recovers_safe_off_and_settles_each_subprocess_once(tmp_path):
    run = _run_tcpip_cleanup_fixture(tmp_path, mode="cleanup-recover")
    safe_off, output_state, error_queue = run["commands"]

    assert run["cleanup"]["status"] == "passed"
    assert safe_off["attempt_count"] == 2
    assert safe_off["recovered_after_open_failure"] is True
    assert [attempt["settle_before_ms"] for attempt in safe_off["attempts"]] == [0, 500]
    assert output_state["attempts"][0]["settle_before_ms"] == 500
    assert error_queue["attempts"][0]["settle_before_ms"] == 500
    assert run["sleeps"] == [500, 500, 500]


def test_tcpip_cleanup_persistent_safe_off_failure_remains_failed(tmp_path):
    run = _run_tcpip_cleanup_fixture(tmp_path, mode="cleanup-persistent")
    safe_off = run["commands"][0]

    assert run["cleanup"]["status"] == "failed"
    assert safe_off["result"] == "failed"
    assert safe_off["attempt_count"] == 2
    assert safe_off["recovered_after_open_failure"] is False
    assert "Cleanup safe-off command failed." in run["failures"]
    assert run["sleeps"] == [500, 500, 500]


def test_trigger_helper_uses_settle_coordinator_without_cli_recovery_contract():
    script = SCRIPT.read_text(encoding="utf-8")
    helper_body = script.split("function Invoke-TriggerValidationHelper", 1)[1].split(
        "function Invoke-TriggerFireCandidateCase", 1
    )[0]

    assert 'Invoke-LiveTcpipSubprocessSettle -Phase "live"' in helper_body
    assert "Test-PreIoOpenFailureRecoveryEligible" not in helper_body
    assert "attempt-" not in helper_body


def test_redaction_keeps_hyphenated_command_identifiers_and_rejects_prose_idn_guess():
    command = r'''
$env:POWERS_TOOL_LIVE_CLI_CHECK_IMPORT_ONLY = "1"
. .\scripts\live-cli-check.ps1
$script:SensitiveValues = New-Object System.Collections.Generic.List[string]
$script:RawResource = $null
$script:ResourceDisplay = "LAN:<redacted-resource>"
$prose = Protect-ShareableText -Text "Preview a guarded set, output, measure, and turn off."
$script:SensitiveValues.Add("measure")
$commands = Protect-ShareableText -Text "measure-all safe-off measure"
[pscustomobject]@{ prose = $prose; commands = $commands; sensitive = $script:SensitiveValues.ToArray() } | ConvertTo-Json -Compress
'''
    result = _run_powershell_command(command)

    assert result.returncode == 0, result.stdout + result.stderr
    redaction = json.loads(result.stdout)
    assert redaction["prose"] == "Preview a guarded set, output, measure, and turn off."
    assert redaction["commands"] == "measure-all safe-off <redacted>"
