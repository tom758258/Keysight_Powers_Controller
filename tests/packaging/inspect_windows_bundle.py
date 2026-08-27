from __future__ import annotations

import argparse
from pathlib import Path

from _inspector_utils import resolve_expected_version


EXPECTED_EXECUTABLES = {
    "powers-tool.exe",
    "powers-tool-webui-launcher.exe",
    "powers-tool-webui-host.exe",
}


def _relative_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def inspect_bundle(
    bundle: Path,
    *,
    source_static: Path,
    source_cli_help: Path,
    expected_version: str,
) -> None:
    if not bundle.is_dir():
        raise AssertionError(f"shared bundle directory does not exist: {bundle}")

    root_entries = {path.name for path in bundle.iterdir()}
    expected_root_entries = {*EXPECTED_EXECUTABLES, "_internal"}
    assert root_entries == expected_root_entries, (
        f"expected shared bundle root entries {sorted(expected_root_entries)!r}, "
        f"found {sorted(root_entries)!r}"
    )

    internal = bundle / "_internal"
    assert internal.is_dir(), internal
    assert len([path for path in bundle.rglob("_internal") if path.is_dir()]) == 1

    metadata_files = sorted(
        path
        for path in internal.rglob("METADATA")
        if path.parent.name.startswith("powers_tool-")
    )
    assert len(metadata_files) == 1, metadata_files
    metadata = metadata_files[0].read_text(encoding="utf-8").splitlines()
    assert "Name: powers-tool" in metadata
    assert f"Version: {expected_version}" in metadata

    bundled_static = internal / "powers_tool_webui" / "static"
    assert bundled_static.is_dir(), bundled_static
    assert _relative_files(source_static) == _relative_files(bundled_static)

    bundled_cli_help = internal / "powers_tool_cli" / "help"
    assert bundled_cli_help.is_dir(), bundled_cli_help
    assert _relative_files(source_cli_help) == _relative_files(bundled_cli_help)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version")
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    try:
        expected_version = resolve_expected_version(
            args.expected_version, inspector_file=Path(__file__)
        )
    except ValueError as exc:
        parser.error(str(exc))

    repository_root = Path(__file__).resolve().parents[2]
    inspect_bundle(
        args.bundle,
        source_static=repository_root / "src" / "powers_tool_webui" / "static",
        source_cli_help=repository_root / "src" / "powers_tool_cli" / "help",
        expected_version=expected_version,
    )
    print("Powers Tool shared Windows onedir inspection passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
