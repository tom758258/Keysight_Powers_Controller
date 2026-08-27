from __future__ import annotations

import argparse
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


def _normalise(name: str) -> str:
    return name.replace("\\", "/")


def inspect_executable(
    path: Path,
    required_packages: tuple[str, ...],
) -> None:
    archive = CArchiveReader(str(path))
    names = {_normalise(name): name for name in archive.toc}

    pyz_name = names.get("PYZ.pyz")
    if pyz_name is None:
        raise AssertionError(f"{path} does not contain PYZ.pyz")
    pyz_names = set(archive.open_embedded_archive(pyz_name).toc)
    for package in required_packages:
        assert package in pyz_names, package
        assert any(name.startswith(f"{package}.") for name in pyz_names), package
    assert not any("keysight_power_" in name for name in (*names, *pyz_names))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cli_exe", type=Path)
    parser.add_argument("webui_exe", type=Path)
    args = parser.parse_args(argv)
    inspect_executable(
        args.cli_exe,
        ("powers_tool_core", "powers_tool_cli"),
    )
    inspect_executable(
        args.webui_exe,
        ("powers_tool_core", "powers_tool_webui"),
    )
    print("Powers Tool PyInstaller archive inspection passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
