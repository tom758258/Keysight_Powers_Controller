from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path

from _inspector_utils import resolve_expected_version


CANONICAL_PACKAGES = ("powers_tool_core", "powers_tool_cli", "powers_tool_webui")
LEGACY_PACKAGES = ("keysight_power_core", "keysight_power_cli", "keysight_power_webui")
ENTRY_POINTS = {
    "powers-tool = powers_tool_cli.cli:main",
    "powers-tool-webui = powers_tool_webui.server:main",
    "powers-tool-webui-launcher = powers_tool_webui.launcher:main",
}
FORBIDDEN_WHEEL_PREFIXES = {
    "scripts/",
    "tests/",
    "private/",
    "candidate-evidence/",
}


def inspect_distribution(
    dist_dir: Path, *, expected_version: str, require_sdist: bool = True
) -> None:
    wheels = sorted(dist_dir.glob("powers_tool-*-py3-none-any.whl"))
    sdists = sorted(dist_dir.glob("powers_tool-*.tar.gz"))
    if len(wheels) != 1:
        raise AssertionError(f"expected exactly one Powers Tool wheel, found {wheels!r}")
    if require_sdist and len(sdists) != 1:
        raise AssertionError(f"expected exactly one Powers Tool sdist, found {sdists!r}")

    expected_wheel = f"powers_tool-{expected_version}-py3-none-any.whl"
    if wheels[0].name != expected_wheel:
        raise AssertionError(
            f"expected wheel filename {expected_wheel!r}, found {wheels[0].name!r}"
        )

    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        expected_dist_info = f"powers_tool-{expected_version}.dist-info"
        metadata_name = f"{expected_dist_info}/METADATA"
        entry_points_name = f"{expected_dist_info}/entry_points.txt"
        powers_metadata = sorted(
            name
            for name in names
            if name.startswith("powers_tool-") and name.endswith(".dist-info/METADATA")
        )
        if powers_metadata != [metadata_name]:
            raise AssertionError(
                f"expected wheel metadata path {metadata_name!r}, "
                f"found {powers_metadata!r}"
            )
        if entry_points_name not in names:
            raise AssertionError(
                f"expected wheel entry points path {entry_points_name!r}"
            )
        metadata = archive.read(metadata_name).decode("utf-8")
        entry_points = archive.read(entry_points_name).decode("utf-8")
        metadata_lines = set(metadata.splitlines())
        assert "Name: powers-tool" in metadata_lines
        assert f"Version: {expected_version}" in metadata_lines, (
            f"expected wheel metadata version {expected_version!r}, "
            f"found {[line for line in metadata_lines if line.startswith('Version: ')]!r}"
        )
        assert "Requires-Python: >=3.10" in metadata_lines
        entry_point_lines = set(entry_points.splitlines())
        assert ENTRY_POINTS <= entry_point_lines
        assert not any(line.startswith("keysight-power") for line in entry_point_lines)
        for package in CANONICAL_PACKAGES:
            assert any(name.startswith(f"{package}/") for name in names), package
        for package in LEGACY_PACKAGES:
            assert not any(name.startswith(f"{package}/") for name in names), package
        assert not any(name.startswith(tuple(FORBIDDEN_WHEEL_PREFIXES)) for name in names)
        build_profile_name = "powers_tool_core/build_profile.py"
        assert build_profile_name in names
        build_profile = archive.read(build_profile_name).decode("utf-8")
        assert "BuildProfile.PRODUCT" in build_profile
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
            assert f"powers_tool_webui/static/{filename}" in names

    if sdists:
        expected_sdist = f"powers_tool-{expected_version}.tar.gz"
        if sdists[0].name != expected_sdist:
            raise AssertionError(
                f"expected sdist filename {expected_sdist!r}, found {sdists[0].name!r}"
            )
        with tarfile.open(sdists[0], "r:gz") as archive:
            names = set(archive.getnames())
            top_levels = {name.split("/", 1)[0] for name in names}
            assert len(top_levels) == 1, f"expected one sdist root, found {top_levels!r}"
            root = top_levels.pop()
            expected_root = f"powers_tool-{expected_version}"
            assert root == expected_root, (
                f"expected sdist root {expected_root!r}, found {root!r}"
            )
            for package in CANONICAL_PACKAGES:
                assert any(name.startswith(f"{root}/src/{package}/") for name in names), package
            for package in LEGACY_PACKAGES:
                assert not any(name.startswith(f"{root}/src/{package}/") for name in names), package
            assert f"{root}/src/powers_tool_core/build_profile.py" in names
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
                assert f"{root}/src/powers_tool_webui/static/{filename}" in names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel-only", action="store_true")
    parser.add_argument("--expected-version")
    parser.add_argument("dist_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        expected_version = resolve_expected_version(
            args.expected_version, inspector_file=Path(__file__)
        )
    except ValueError as exc:
        parser.error(str(exc))
    inspect_distribution(
        args.dist_dir,
        expected_version=expected_version,
        require_sdist=not args.wheel_only,
    )
    print("Powers Tool distribution inspection passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
