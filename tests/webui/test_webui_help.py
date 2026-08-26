"""Focused WebUI Help contracts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "generate_help.py"
RUNTIME_HELP_DIR = REPO_ROOT / "src" / "powers_tool_webui" / "static" / "help"

REQUIRED_HELP_FILES = (
    "webui.html",
    "webui.zh-TW.html",
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
    assert not (RUNTIME_HELP_DIR / "cli.html").exists()
    assert not (RUNTIME_HELP_DIR / "cli.zh-TW.html").exists()


def test_webui_help_route_and_main_help_link(client) -> None:
    response = client.get("/help/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert response.headers.get("cache-control") == "no-store"
    assert 'lang="en"' in response.text
    assert 'href="help.css"' in response.text

    zh_response = client.get("/help/webui.zh-TW.html")
    assert zh_response.status_code == 200
    assert 'lang="zh-TW"' in zh_response.text

    css_response = client.get("/help/help.css")
    assert css_response.status_code == 200
    assert css_response.headers.get("cache-control") == "no-store"

    supported = client.get("/help/supported-models.html")
    assert supported.status_code == 200
    assert 'id="product-live-exact-scope-matrix"' in supported.text

    index = client.get("/")
    assert index.status_code == 200
    html = index.text
    assert 'id="help-link"' in html
    assert 'href="/help/"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener"' in html
    assert 'data-i18n="app.help"' in html
