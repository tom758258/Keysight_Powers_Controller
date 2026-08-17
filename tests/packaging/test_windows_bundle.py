from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSPECTOR_PATH = Path(__file__).with_name("inspect_windows_bundle.py")


def _load_inspector():
    spec = importlib.util.spec_from_file_location(
        "powers_tool_windows_bundle_inspector", INSPECTOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shared_spec_has_two_onedir_executables_and_one_collect() -> None:
    text = (ROOT / "scripts" / "powers-tool-windows.spec").read_text(
        encoding="utf-8"
    )

    assert text.count("Analysis(") == 2
    assert text.count("PYZ(") == 2
    assert text.count("EXE(") == 2
    assert text.count("exclude_binaries=True") == 2
    assert text.count('contents_directory="_internal"') == 2
    assert text.count("COLLECT(") == 1
    assert "MERGE" not in text


def test_windows_bundle_script_guards_tk_before_cleanup_and_pyinstaller() -> None:
    text = (ROOT / "scripts" / "build_windows_bundle.ps1").read_text(
        encoding="utf-8"
    )

    assert "import tkinter as tk" in text
    assert "root = tk.Tk()" in text
    assert "Tkinter WebUI Launcher" in text
    assert "Tcl/Tk runtime" in text

    probe = text.index("& $Python -c $tkProbe")
    cleanup = text.index("Remove-Item -LiteralPath $bundlePath")
    pyinstaller = text.index("& $Python -m PyInstaller")
    assert probe < cleanup < pyinstaller


def test_bundle_inspector_compares_the_complete_static_tree(tmp_path: Path) -> None:
    inspector = _load_inspector()
    source_static = tmp_path / "source-static"
    bundled_static = tmp_path / "bundle" / "_internal" / "powers_tool_webui" / "static"
    source_static.joinpath("nested").mkdir(parents=True)
    source_static.joinpath("index.html").write_text("index", encoding="utf-8")
    source_static.joinpath("nested", "app.js").write_text("app", encoding="utf-8")
    bundled_static.mkdir(parents=True)
    for source in source_static.rglob("*"):
        if source.is_file():
            target = bundled_static / source.relative_to(source_static)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())

    bundle = tmp_path / "bundle"
    (bundle / "powers-tool.exe").write_bytes(b"")
    (bundle / "powers-tool-webui-launcher.exe").write_bytes(b"")
    metadata_dir = bundle / "_internal" / "powers_tool-2.0.0.dist-info"
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "METADATA").write_text(
        "Name: powers-tool\nVersion: 2.0.0\n", encoding="utf-8"
    )

    inspector.inspect_bundle(
        bundle,
        source_static=source_static,
        expected_version="2.0.0",
    )
