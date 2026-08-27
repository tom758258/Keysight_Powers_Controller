from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_text_hygiene.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_text_hygiene", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _load_checker()


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_inspect_text_file_accepts_utf8_lf_and_crlf(tmp_path: Path) -> None:
    for name, content in (("lf.py", b"value = 'ok'\n"), ("crlf.py", b"value = 'ok'\r\n")):
        path = tmp_path / name
        _write_bytes(path, content)
        assert CHECKER.inspect_text_file(path, Path(name)) == []


def test_inspect_text_file_rejects_bom_created_in_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "bom.py"
    _write_bytes(path, bytes((0xEF, 0xBB, 0xBF)) + b"value = 'ok'\n")

    assert CHECKER.inspect_text_file(path, Path("bom.py")) == ["bom.py:1: UTF-8 BOM is not allowed"]


def test_inspect_text_file_rejects_replacement_character_created_in_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "replacement.py"
    _write_bytes(path, ("value = '" + chr(0xFFFD) + "'\n").encode("utf-8"))

    assert CHECKER.inspect_text_file(path, Path("replacement.py")) == [
        "replacement.py:1: U+FFFD replacement character is not allowed"
    ]


def test_inspect_text_file_rejects_mojibake_created_in_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "mojibake.py"
    mojibake = b"caf\xc3\xa9".decode("latin-1")
    _write_bytes(path, f"value = {mojibake!r}\n".encode("utf-8"))

    assert CHECKER.inspect_text_file(path, Path("mojibake.py")) == [
        "mojibake.py:1: likely UTF-8 mojibake is not allowed"
    ]


def test_inspect_text_file_accepts_legitimate_non_ascii_text(tmp_path: Path) -> None:
    path = tmp_path / "international.md"
    content = "\u6b63\u5e38\u7e41\u9ad4\u4e2d\u6587\uff0c\u5168\u5f62\u6a19\u9ede\u3002 caf\u00e9 \u00b7 \u2192 \u2713\n"
    _write_bytes(path, content.encode("utf-8"))

    assert CHECKER.inspect_text_file(path, Path("international.md")) == []


def test_selected_text_paths_includes_control_files_and_webui_source_html() -> None:
    paths = (
        Path(".editorconfig"),
        Path(".gitattributes"),
        Path(".gitignore"),
        Path("docs/generated-reference.html"),
        Path("docs/webui/README.zh-TW.md"),
        Path("Local/private.md"),
        Path("assets/logo.png"),
        Path("tools/repository-control"),
        Path("scripts/check_text_hygiene.py"),
        Path("src/powers_tool_webui/static/index.html"),
        Path("tests/tooling/test_text_hygiene.py"),
    )

    assert CHECKER.selected_text_paths(paths) == (
        Path(".editorconfig"),
        Path(".gitattributes"),
        Path(".gitignore"),
        Path("scripts/check_text_hygiene.py"),
        Path("src/powers_tool_webui/static/index.html"),
        Path("tests/tooling/test_text_hygiene.py"),
    )


def test_repository_tracked_text_is_clean() -> None:
    assert CHECKER.collect_findings(REPO_ROOT, CHECKER.tracked_files(REPO_ROOT)) == []
