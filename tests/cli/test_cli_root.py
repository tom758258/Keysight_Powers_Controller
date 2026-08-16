from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import powers_tool_cli.cli as cli
import powers_tool_cli.cli_runtime as cli_runtime

ROOT = Path(__file__).resolve().parents[2]


def _run_cli_module(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "powers_tool_cli.cli", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_cli_module_entry_version() -> None:
    result = _run_cli_module("--version")
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == f"powers-tool {cli_runtime._package_version()}"


def test_cli_module_entry_help() -> None:
    result = _run_cli_module("--help")
    assert result.returncode == 0
    assert "Powers Tool" in result.stdout
    assert "supported DC power supplies" in result.stdout


def test_cli_module_entry_json_argument_error() -> None:
    result = _run_cli_module(
        "snapshot",
        "--simulate",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--save-json",
        "snapshot.json",
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "--save-json requires --json" in payload["error"]["message"]


def test_root_version_prints_package_version(capsys) -> None:
    assert cli.main(["--version"]) == 0

    captured = capsys.readouterr()

    assert captured.out.strip() == f"powers-tool {cli_runtime._package_version()}"
    assert captured.err == ""

def test_root_help_uses_vendor_neutral_product_identity(capsys) -> None:
    assert cli.main(["--help"]) == 0

    captured = capsys.readouterr()

    assert "Powers Tool" in captured.out
    assert "supported DC power supplies" in captured.out
    assert "Keysight DC power supplies" not in captured.out

def test_cli_missing_distribution_metadata_uses_nonrelease_fallback(monkeypatch) -> None:
    from importlib import metadata
    import runpy

    def missing_distribution(_name: str) -> str:
        raise metadata.PackageNotFoundError("powers-tool")

    monkeypatch.setattr(cli_runtime.importlib.metadata, "version", missing_distribution)

    package_namespace = runpy.run_path("src/powers_tool_cli/__init__.py")

    assert package_namespace["__version__"] == "0+unknown"
    assert package_namespace["__version__"] not in {"1.0.0", "2.0.0"}
    assert cli_runtime._package_version() == "0+unknown"
    assert cli_runtime._package_version() not in {"1.0.0", "2.0.0"}
