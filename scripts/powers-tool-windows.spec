# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_data_files, copy_metadata


REPO_ROOT = Path(SPECPATH).resolve().parent
SRC_ROOT = REPO_ROOT / "src"

PROJECT_METADATA = copy_metadata("powers-tool")
WEBUI_STATIC = collect_data_files("powers_tool_webui", includes=["static/*"])


cli_analysis = Analysis(
    [str(SRC_ROOT / "powers_tool_cli" / "cli.py")],
    pathex=[str(SRC_ROOT)],
    binaries=[],
    datas=PROJECT_METADATA,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

launcher_analysis = Analysis(
    [str(SRC_ROOT / "powers_tool_webui" / "launcher.py")],
    pathex=[str(SRC_ROOT)],
    binaries=[],
    datas=[*PROJECT_METADATA, *WEBUI_STATIC],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

host_analysis = Analysis(
    [str(SRC_ROOT / "powers_tool_webui" / "_desktop_host.py")],
    pathex=[str(SRC_ROOT)],
    binaries=[],
    datas=[*PROJECT_METADATA, *WEBUI_STATIC],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)


cli_pyz = PYZ(cli_analysis.pure)
launcher_pyz = PYZ(launcher_analysis.pure)
host_pyz = PYZ(host_analysis.pure)

cli_exe = EXE(
    cli_pyz,
    cli_analysis.scripts,
    exclude_binaries=True,
    name="powers-tool",
    console=True,
    contents_directory="_internal",
)

launcher_exe = EXE(
    launcher_pyz,
    launcher_analysis.scripts,
    exclude_binaries=True,
    name="powers-tool-webui-launcher",
    console=False,
    contents_directory="_internal",
)

host_exe = EXE(
    host_pyz,
    host_analysis.scripts,
    exclude_binaries=True,
    name="powers-tool-webui-host",
    console=True,
    contents_directory="_internal",
)


COLLECT(
    cli_exe,
    launcher_exe,
    host_exe,
    cli_analysis.binaries,
    cli_analysis.zipfiles,
    cli_analysis.datas,
    launcher_analysis.binaries,
    launcher_analysis.zipfiles,
    launcher_analysis.datas,
    host_analysis.binaries,
    host_analysis.zipfiles,
    host_analysis.datas,
    name="powers-tool",
)
