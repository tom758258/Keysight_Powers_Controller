from __future__ import annotations

import importlib.util
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[2]
LEGACY_IDENTITY_TOKENS = (
    "keysight-powers",
    "keysight-power",
    "keysight_power_core",
    "keysight_power_cli",
    "keysight_power_webui",
    "Keysight Powers",
    "Keysight Power",
    "Keysight Power contributors",
    "keysight-power-ramp-list",
    "model_profile",
    "KeysightPowerError",
    "Keysight power CLI",
    "Keysight power supply commands",
)
ACTIVE_AUDIT_PATHS = (
    "pyproject.toml",
    "src",
    ".github/workflows",
    "scripts",
    "tests/packaging/inspect_distribution.py",
    "tests/packaging/inspect_pyinstaller.py",
)
NEGATIVE_REGRESSION_EXEMPTIONS = {
    "src/powers_tool_cli/worker_protocol.py": {"model_profile"},
    "src/powers_tool_webui/app.py": {"model_profile"},
    "scripts/release-acceptance.ps1": {
        "keysight-power",
        "keysight_power_core",
        "keysight_power_cli",
        "keysight_power_webui",
    },
    "tests/packaging/inspect_distribution.py": {
        "keysight-power",
        "keysight_power_core",
        "keysight_power_cli",
        "keysight_power_webui",
    },
}


def test_pyproject_uses_only_current_distribution_packages_and_scripts() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["name"] == "powers-tool"
    assert data["project"]["scripts"] == {
        "powers-tool": "powers_tool_cli.cli:main",
        "powers-tool-webui": "powers_tool_webui.server:main",
        "powers-tool-webui-launcher": "powers_tool_webui.launcher:main",
    }
    assert data["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "powers_tool_core*",
        "powers_tool_cli*",
        "powers_tool_webui*",
    ]


def test_old_python_packages_are_absent() -> None:
    for package in LEGACY_IDENTITY_TOKENS[2:5]:
        assert not (ROOT / "src" / package).exists()
        assert importlib.util.find_spec(package) is None


def test_active_packaging_and_runtime_paths_have_no_stale_identity() -> None:
    findings: list[str] = []
    for relative in ACTIVE_AUDIT_PATHS:
        path = ROOT / relative
        files = path.rglob("*") if path.is_dir() else (path,)
        for file in files:
            if not file.is_file() or file.suffix.lower() not in {".py", ".ps1", ".toml", ".yml", ".yaml"}:
                continue
            file_relative = file.relative_to(ROOT).as_posix()
            text = file.read_text(encoding="utf-8")
            exempt = NEGATIVE_REGRESSION_EXEMPTIONS.get(file_relative, set())
            for token in LEGACY_IDENTITY_TOKENS:
                if token in text and token not in exempt:
                    findings.append(f"{file_relative}: {token!r}")

    assert findings == []
