"""Focused CLI Help contracts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "generate_help.py"
RUNTIME_HELP_DIR = REPO_ROOT / "src" / "powers_tool_cli" / "help"

REQUIRED_HELP_FILES = (
    "cli.html",
    "cli.zh-TW.html",
    "supported-models.html",
    "supported-models.zh-TW.html",
    "help.css",
)


def test_runtime_help_assets_match_canonical_generator(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated"
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--output-dir", str(output_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    for name in REQUIRED_HELP_FILES:
        generated = (output_dir / name).read_bytes()
        runtime = (RUNTIME_HELP_DIR / name).read_bytes()
        assert generated == runtime, name
    assert not (RUNTIME_HELP_DIR / "webui.html").exists()
    assert not (RUNTIME_HELP_DIR / "webui.zh-TW.html").exists()


def test_cli_user_guide_opens_bundled_help(monkeypatch, capsys) -> None:
    import powers_tool_cli.cli as cli

    opened: list[str] = []

    def fake_open(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr("webbrowser.open", fake_open)

    # Default en
    opened.clear()
    capsys.readouterr()
    result = cli.main(["user-guide"])
    assert result == 0
    assert len(opened) == 1
    expected_en = (Path(cli.__file__).resolve().parent / "help" / "cli.html").resolve().as_uri()
    assert opened[0] == expected_en

    # explicit en
    opened.clear()
    capsys.readouterr()
    result = cli.main(["user-guide", "--language", "en"])
    assert result == 0
    assert len(opened) == 1
    assert opened[0] == expected_en

    # zh-TW
    opened.clear()
    capsys.readouterr()
    result = cli.main(["user-guide", "--language", "zh-TW"])
    assert result == 0
    assert len(opened) == 1
    expected_zh = (Path(cli.__file__).resolve().parent / "help" / "cli.zh-TW.html").resolve().as_uri()
    assert opened[0] == expected_zh

    # browser returns False -> returns 1 + stderr manual path
    def fake_open_false(url: str) -> bool:
        opened.append(url)
        return False

    monkeypatch.setattr("webbrowser.open", fake_open_false)
    opened.clear()
    capsys.readouterr()
    result = cli.main(["user-guide"])
    assert result == 1
    captured = capsys.readouterr()
    assert "Could not open" in captured.err or "Could not open" in captured.out or len(captured.err) > 0
    # stderr should contain manual path
    assert "cli.html" in captured.err
