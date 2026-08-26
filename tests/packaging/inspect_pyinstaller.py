from __future__ import annotations

import argparse
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

from _inspector_utils import resolve_expected_version


def _normalise(name: str) -> str:
    return name.replace("\\", "/")


def _validate_metadata(
    archive: CArchiveReader, names: dict[str, str], *, expected_version: str
) -> None:
    metadata_names = sorted(
        name for name in names if name.endswith(".dist-info/METADATA")
    )
    powers_metadata_names = [
        name for name in metadata_names if name.startswith("powers_tool-")
    ]
    expected_metadata = f"powers_tool-{expected_version}.dist-info/METADATA"
    if powers_metadata_names != [expected_metadata]:
        raise AssertionError(
            f"expected Powers Tool metadata path {expected_metadata!r}, "
            f"found {powers_metadata_names!r}"
        )
    assert not any("keysight" in name.lower() for name in metadata_names)
    metadata_lines = archive.extract(names[expected_metadata]).decode("utf-8").splitlines()
    assert "Name: powers-tool" in metadata_lines
    assert f"Version: {expected_version}" in metadata_lines, (
        f"expected PyInstaller metadata version {expected_version!r}, "
        f"found {[line for line in metadata_lines if line.startswith('Version: ')]!r}"
    )


def inspect_executable(
    path: Path,
    required_packages: tuple[str, ...],
    *,
    webui: bool,
    expected_version: str,
) -> None:
    archive = CArchiveReader(str(path))
    names = {_normalise(name): name for name in archive.toc}
    _validate_metadata(archive, names, expected_version=expected_version)

    pyz_name = names.get("PYZ.pyz")
    if pyz_name is None:
        raise AssertionError(f"{path} does not contain PYZ.pyz")
    pyz_names = set(archive.open_embedded_archive(pyz_name).toc)
    for package in required_packages:
        assert package in pyz_names, package
        assert any(name.startswith(f"{package}.") for name in pyz_names), package
    assert not any("keysight_power_" in name for name in (*names, *pyz_names))
    assert not any("keysight-powers" in name.lower() for name in names)

    if webui:
        for filename in (
            "index.html",
            "styles.css",
            "app.js",
            "help/webui.html",
            "help/webui.zh-TW.html",
            "help/supported-models.html",
            "help/supported-models.zh-TW.html",
            "help/help.css",
        ):
            asset = f"powers_tool_webui/static/{filename}"
            assert asset in names, f"expected WebUI asset {asset!r}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version")
    parser.add_argument("cli_exe", type=Path)
    parser.add_argument("webui_exe", type=Path)
    args = parser.parse_args(argv)
    try:
        expected_version = resolve_expected_version(
            args.expected_version, inspector_file=Path(__file__)
        )
    except ValueError as exc:
        parser.error(str(exc))
    inspect_executable(
        args.cli_exe,
        ("powers_tool_core", "powers_tool_cli"),
        webui=False,
        expected_version=expected_version,
    )
    inspect_executable(
        args.webui_exe,
        ("powers_tool_core", "powers_tool_webui"),
        webui=True,
        expected_version=expected_version,
    )
    print("Powers Tool PyInstaller archive inspection passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
