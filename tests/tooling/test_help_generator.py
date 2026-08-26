from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "generate_help.py"


EXPECTED_OUTPUTS = {
    "cli.html",
    "cli.zh-TW.html",
    "webui.html",
    "webui.zh-TW.html",
    "supported-models.html",
    "supported-models.zh-TW.html",
    "help.css",
}


def generate_bundle(tmp_path: Path) -> Path:
    output_dir = tmp_path / "help"
    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    return output_dir


def test_generated_help_bundle_contains_expected_files(tmp_path: Path) -> None:
    output_dir = generate_bundle(tmp_path)

    assert {path.name for path in output_dir.iterdir()} == EXPECTED_OUTPUTS

    for name in EXPECTED_OUTPUTS:
        if not name.endswith(".html"):
            continue
        html_bytes = (output_dir / name).read_bytes()
        assert b"\r\n" not in html_bytes
        html_text = html_bytes.decode("utf-8")
        assert "{{lang}}" not in html_text
        assert "{{title}}" not in html_text
        assert "{{content}}" not in html_text
        assert 'href="help.css"' in html_text

        if ".zh-TW." in name:
            assert 'lang="zh-TW"' in html_text
        else:
            assert 'lang="en"' in html_text


def test_generated_help_links_and_stable_anchor(tmp_path: Path) -> None:
    output_dir = generate_bundle(tmp_path)

    supported_models = (output_dir / "supported-models.html").read_text(
        encoding="utf-8"
    )
    assert 'id="product-live-exact-scope-matrix"' in supported_models

    for name in ("cli.html", "webui.html"):
        html_text = (output_dir / name).read_text(encoding="utf-8")
        assert 'href="supported-models.html' in html_text
        assert 'href="../core/supported-models.md' not in html_text

    for name in ("cli.zh-TW.html", "webui.zh-TW.html"):
        html_text = (output_dir / name).read_text(encoding="utf-8")
        assert 'href="supported-models.zh-TW.html' in html_text
        assert 'href="../core/supported-models.zh-TW.md' not in html_text

    cli_html = (output_dir / "cli.html").read_text(encoding="utf-8")
    assert (
        'href="supported-models.html#product-live-exact-scope-matrix"'
        in cli_html
    )
    cli_zh_html = (output_dir / "cli.zh-TW.html").read_text(encoding="utf-8")
    assert (
        'href="supported-models.zh-TW.html#product-live-exact-scope-matrix"'
        in cli_zh_html
    )


def test_generated_stylesheet_matches_shared_source(tmp_path: Path) -> None:
    output_dir = generate_bundle(tmp_path)

    generated_css = (output_dir / "help.css").read_bytes()
    source_css = (REPO_ROOT / "docs" / "help" / "help.css").read_bytes()
    assert generated_css == source_css
