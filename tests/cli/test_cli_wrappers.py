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
        "[pscustomobject]@{ model_id=$_.model_id; channels=@($_.channels); suites=@($_.suites) } }); "
        "ConvertTo-Json -InputObject $profiles -Compress -Depth 5"
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
    profiles = {item["model_id"]: item for item in json.loads(result.stdout)}
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


def test_all_model_smoke_executes_required_no_hardware_cli() -> None:
    output = ROOT / ".tmp_tests" / "pytest_cli_preflight" / uuid4().hex
    result = _run(
        "scripts/preflight-cli.ps1",
        "-Target", "all",
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
    assert report["targets"] == [
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e3646a",
    ]
    assert report["hardware_touched"] is False
    assert report["summary_counts"]["failed"] == 0
    assert "Suite: `smoke`" in reports[0].with_name("summary.md").read_text(
        encoding="utf-8"
    )

    expected_topology = {
        "keysight-e36312a": {
            "model": "E36312A",
            "channels": [1, 2, 3],
            "interface": "USB",
            "supported": ("snapshot", True),
        },
        "keysight-edu36311a": {
            "model": "EDU36311A",
            "channels": [1, 2, 3],
            "interface": "USB",
            "supported": ("snapshot", False),
        },
        "keysight-e3646a": {
            "model": "E3646A",
            "channels": [1, 2],
            "interface": "ASRL",
            "supported": ("protection-status", False),
        },
    }

    for model_id, expected in expected_topology.items():
        target_report = json.loads(
            (reports[0].parent / model_id / "report.json").read_text(encoding="utf-8")
        )
        assert target_report["suite"] == "smoke"
        commands = {command["name"]: command for command in target_report["commands"]}
        assert set(commands) >= {
            "identify-simulate",
            "capabilities-simulate",
            "measure-ch1-simulate",
            "set-dry-run",
        }
        assert all(command["hardware_touched"] is False for command in commands.values())
        identify = json.loads(
            (ROOT / commands["identify-simulate"]["json_path"]).read_text(encoding="utf-8")
        )
        assert identify["data"]["idn"]["model"] == expected["model"]
        capabilities = json.loads(
            (ROOT / commands["capabilities-simulate"]["json_path"]).read_text(encoding="utf-8")
        )
        assert capabilities["data"]["resource"]["model_id"] == model_id
        assert capabilities["data"]["channels"] == expected["channels"]
        assert capabilities["data"]["resource"]["interface"] == expected["interface"]
        command_name, supported = expected["supported"]
        assert capabilities["data"]["command_support"][command_name]["simulate"] is supported
        planned_set = json.loads(
            (ROOT / commands["set-dry-run"]["json_path"]).read_text(encoding="utf-8")
        )
        assert planned_set["data"]["plan"]["target"]["planning_model_id"] == model_id

        for command in commands.values():
            assert command["suite"] == "smoke"
            assert command["passed"] is True
            assert command["hardware_touched"] is False
            for key in ("json_path", "stdout_path", "stderr_path"):
                assert str(command[key]).startswith(".tmp_tests\\")


def test_deep_preflight_executes_only_capability_representatives() -> None:
    output = ROOT / ".tmp_tests" / "pytest_cli_preflight" / uuid4().hex
    result = _run(
        "scripts/preflight-cli.ps1",
        "-Target", "all",
        "-Suite", "deep",
        "-OutputRoot", str(output.relative_to(ROOT)),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report_path = next(output.glob("run_*/report.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["suite"] == "deep"
    assert report["targets"] == ["keysight-e36312a", "keysight-e3646a"]
    assert report["hardware_touched"] is False
    assert "Suite: `deep`" in report_path.with_name("summary.md").read_text(
        encoding="utf-8"
    )

    e36312a = json.loads(
        (report_path.parent / "keysight-e36312a" / "report.json").read_text(
            encoding="utf-8"
        )
    )
    assert {command["category"] for command in e36312a["commands"]} >= {
        "protection",
        "snapshot",
        "trigger-list",
        "software-sequence",
        "safe-off",
    }
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
        for target in (e36312a, e3646a)
        for command in target["commands"]
    )
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
