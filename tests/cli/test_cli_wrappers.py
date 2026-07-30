from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("powershell.exe")


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    if POWERSHELL is None:
        pytest.skip("Windows PowerShell is required")
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_validation_script_inventory_and_obsolete_removals() -> None:
    assert (ROOT / "scripts" / "preflight-cli.ps1").is_file()
    assert (ROOT / "scripts" / "live-cli-check.ps1").is_file()
    assert (ROOT / "scripts" / "_validation_helpers.ps1").is_file()
    for obsolete in (
        "no-hardware-regression.ps1",
        "preflight-smoke-validation.ps1",
        "live-smoke-validation-check.ps1",
    ):
        assert not (ROOT / "scripts" / obsolete).exists()


def test_shared_helper_owns_all_model_and_suite_boundaries() -> None:
    if POWERSHELL is None:
        pytest.skip("Windows PowerShell is required")
    helper = ROOT / "scripts" / "_validation_helpers.ps1"
    command = (
        f". '{helper}'; "
        "$profiles = @(Get-ValidationTargetProfiles | ForEach-Object { "
        "[pscustomobject]@{ "
        "model_id=$_.model_id; channels=@($_.channels); suites=@($_.suites) "
        "} }); "
        "$smokeCases = @(Get-ValidationPreflightCases -Target 'keysight-e36312a' "
        "-ArtifactDirectory '.' -SequencePath '.' -Suite 'smoke'); "
        "$deepCases = @(Get-ValidationPreflightCases -Target 'keysight-e36312a' "
        "-ArtifactDirectory '.' -SequencePath '.' -Suite 'deep'); "
        "$fullCases = @(Get-ValidationPreflightCases -Target 'keysight-e36312a' "
        "-ArtifactDirectory '.' -SequencePath '.' -Suite 'full'); "
        "$result = [pscustomobject]@{ "
        "profiles=$profiles; "
        "suites=@((Resolve-ValidationSuite -Suite 'smoke'), "
        "(Resolve-ValidationSuite -Suite 'deep'), "
        "(Resolve-ValidationSuite -Suite 'full')); "
        "smoke_targets=@(Resolve-ValidationPreflightTargets -Target 'all' -Suite 'smoke'); "
        "deep_targets=@(Resolve-ValidationPreflightTargets -Target 'all' -Suite 'deep'); "
        "smoke_cases=@($smokeCases | ForEach-Object { $_.name }); "
        "deep_cases=@($deepCases | ForEach-Object { $_.name }); "
        "full_cases=@($fullCases | ForEach-Object { $_.name }) "
        "}; "
        "ConvertTo-Json -InputObject $result -Compress -Depth 6"
    )
    result = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    inventory = json.loads(result.stdout)
    profiles = {item["model_id"]: item for item in inventory["profiles"]}
    assert set(profiles) == {
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e3646a",
    }
    assert profiles["keysight-e36312a"]["suites"] == [
        "readonly", "output", "protection", "snapshot", "trigger-list", "software-sequence"
    ]
    assert profiles["keysight-edu36311a"]["suites"] == [
        "readonly", "output", "protection", "software-sequence"
    ]
    assert profiles["keysight-e3646a"]["suites"] == [
        "readonly", "output", "software-sequence"
    ]
    assert inventory["suites"] == ["smoke", "deep", "full"]
    assert inventory["smoke_targets"] == [
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e3646a",
    ]
    assert inventory["deep_targets"] == ["keysight-e36312a", "keysight-e3646a"]
    assert inventory["smoke_cases"] == [
        "identify-simulate",
        "capabilities-simulate",
        "measure-ch1-simulate",
        "set-dry-run",
    ]
    assert len(inventory["deep_cases"]) == 12
    assert set(inventory["full_cases"]) == {
        *inventory["smoke_cases"],
        *inventory["deep_cases"],
    }


def test_representative_smoke_executes_required_no_hardware_cli() -> None:
    output = ROOT / ".tmp_tests" / "pytest_cli_preflight" / uuid4().hex
    result = _run(
        "scripts/preflight-cli.ps1",
        "-Target", "keysight-edu36311a",
        "-Suite", "smoke",
        "-OutputRoot", str(output.relative_to(ROOT)),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    reports = sorted(output.glob("run_*/report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["kind"] == "powers-tool-cli-preflight"
    assert report["status"] == "passed"
    assert report["suite"] == "smoke"
    assert report["targets"] == ["keysight-edu36311a"]
    assert report["hardware_touched"] is False
    assert report["summary_counts"]["failed"] == 0
    assert "Suite: `smoke`" in reports[0].with_name("summary.md").read_text(
        encoding="utf-8"
    )

    target_report = json.loads(
        (reports[0].parent / "keysight-edu36311a" / "report.json").read_text(
            encoding="utf-8"
        )
    )
    commands = {command["name"]: command for command in target_report["commands"]}
    assert set(commands) == {
        "identify-simulate",
        "capabilities-simulate",
        "measure-ch1-simulate",
        "set-dry-run",
    }
    identify = json.loads(
        (ROOT / commands["identify-simulate"]["json_path"]).read_text(encoding="utf-8")
    )
    assert identify["data"]["idn"]["model"] == "EDU36311A"
    capabilities = json.loads(
        (ROOT / commands["capabilities-simulate"]["json_path"]).read_text(encoding="utf-8")
    )
    assert capabilities["data"]["resource"]["model_id"] == "keysight-edu36311a"
    planned_set = json.loads(
        (ROOT / commands["set-dry-run"]["json_path"]).read_text(encoding="utf-8")
    )
    assert (
        planned_set["data"]["plan"]["target"]["planning_model_id"]
        == "keysight-edu36311a"
    )
    assert all(
        command["suite"] == "smoke"
        and command["passed"] is True
        and command["hardware_touched"] is False
        for command in commands.values()
    )


def test_representative_deep_executes_required_no_hardware_cli() -> None:
    output = ROOT / ".tmp_tests" / "pytest_cli_preflight" / uuid4().hex
    result = _run(
        "scripts/preflight-cli.ps1",
        "-Target", "keysight-e3646a",
        "-Suite", "deep",
        "-OutputRoot", str(output.relative_to(ROOT)),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report_path = next(output.glob("run_*/report.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["suite"] == "deep"
    assert report["targets"] == ["keysight-e3646a"]
    assert report["hardware_touched"] is False
    assert "Suite: `deep`" in report_path.with_name("summary.md").read_text(
        encoding="utf-8"
    )

    e3646a = json.loads(
        (report_path.parent / "keysight-e3646a" / "report.json").read_text(
            encoding="utf-8"
        )
    )
    assert {command["category"] for command in e3646a["commands"]} >= {
        "software-sequence",
        "safe-off",
    }
    e3646a_commands = {
        command["name"]: command for command in e3646a["commands"]
    }
    e3646a_safe_off = json.loads(
        (ROOT / e3646a_commands["safe-off-dry-run"]["json_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert e3646a_safe_off["data"]["plan"]["target"] == {
        "channel": "all",
        "planning_model_id": "keysight-e3646a",
        "planning_profile_id": None,
        "resource": None,
    }
    assert all(
        command["hardware_touched"] is False
        for command in e3646a["commands"]
    )
    assert not (report_path.parent / "keysight-e36312a").exists()
    assert not (report_path.parent / "keysight-edu36311a").exists()


def test_preflight_rejects_unsupported_suite_and_target() -> None:
    output = ROOT / ".tmp_tests" / "pytest_cli_preflight" / uuid4().hex
    invalid_suite = _run(
        "scripts/preflight-cli.ps1",
        "-Suite", "unknown",
        "-OutputRoot", str(output.relative_to(ROOT)),
    )
    assert invalid_suite.returncode != 0
    assert "Suite" in invalid_suite.stderr

    invalid_target = _run(
        "scripts/preflight-cli.ps1",
        "-Target", "unknown-model",
        "-Suite", "smoke",
        "-OutputRoot", str(output.relative_to(ROOT)),
    )
    assert invalid_target.returncode == 2
    assert "Unsupported target" in invalid_target.stderr

    unsupported_deep_target = _run(
        "scripts/preflight-cli.ps1",
        "-Target", "keysight-edu36311a",
        "-Suite", "deep",
        "-OutputRoot", str(output.relative_to(ROOT)),
    )
    assert unsupported_deep_target.returncode == 2
    assert "not a deep preflight representative" in unsupported_deep_target.stderr
