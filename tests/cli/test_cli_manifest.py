import json
import os
import subprocess
import sys
from pathlib import Path

import powers_tool_cli.cli as cli
import powers_tool_cli.cli_runtime as cli_runtime
from powers_tool_cli.commands.manifest import build_manifest


ROOT = Path(__file__).resolve().parents[2]

EXPECTED_MANIFEST = {
    "event": "tool_manifest",
    "schema_version": 2,
    "tool_id": "powers",
    "tool_version": cli_runtime._package_version(),
    "worker_protocol": {
        "compatibility_policy": "v2-only",
        "schema_versions": [2],
    },
}


def test_manifest_json_contract(capsys) -> None:
    assert cli.main(["manifest", "--json"]) == 0

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]

    assert captured.err == ""
    assert len(lines) == 1
    assert json.loads(lines[0]) == EXPECTED_MANIFEST


def test_manifest_json_format_flag_matches_json_alias(capsys) -> None:
    assert cli.main(["manifest", "--format", "json"]) == 0

    captured = capsys.readouterr()

    assert captured.err == ""
    assert json.loads(captured.out) == EXPECTED_MANIFEST


def test_manifest_text_mode_prints_short_human_output(capsys) -> None:
    assert cli.main(["manifest"]) == 0

    captured = capsys.readouterr()

    assert captured.err == ""
    assert cli_runtime._package_version() in captured.out
    assert "v2-only" in captured.out


def test_manifest_build_uses_single_version_provider() -> None:
    assert build_manifest(version_provider=lambda: "9.9.9")["tool_version"] == "9.9.9"


def test_manifest_does_not_touch_visa_or_runtime_paths(monkeypatch, capsys) -> None:
    def fail_visa(*args, **kwargs):
        raise AssertionError("manifest must not call VISA or runtime resource paths")

    monkeypatch.setattr(cli_runtime, "list_resources", fail_visa)
    monkeypatch.setattr(cli_runtime, "open_resource", fail_visa)
    monkeypatch.setattr(cli_runtime, "SimulatedResourceManager", fail_visa)

    assert cli.main(["manifest", "--json"]) == 0

    captured = capsys.readouterr()

    assert captured.err == ""
    assert json.loads(captured.out)["event"] == "tool_manifest"


def test_manifest_subprocess_is_static_in_empty_workdir(tmp_path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-m", "powers_tool_cli.cli", "manifest", "--json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == EXPECTED_MANIFEST
    assert list(tmp_path.iterdir()) == []
