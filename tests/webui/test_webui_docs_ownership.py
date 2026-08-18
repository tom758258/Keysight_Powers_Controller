from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_ROOT = REPO_ROOT / "docs" / "webui"


def read_webui_doc(*parts: str) -> str:
    return DOC_ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_webui_docs_are_root_local():
    assert (DOC_ROOT / "README.md").exists()
    assert (REPO_ROOT / "CHANGELOG.md").exists()
    assert not (DOC_ROOT / "CHANGELOG.md").exists()

    for path in (
        "USER_GUIDE.md",
        "web-ui-change-rules.md",
    ):
        assert (DOC_ROOT / path).exists()

    for cli_doc in (
        "power-cli-jsonl-contract.md",
        "power-worker-contract.md",
        "power-orchestrator-workflows.md",
    ):
        assert not (DOC_ROOT / cli_doc).exists()


def test_webui_docs_point_to_current_import_and_static_paths():
    text = "\n".join(
        read_webui_doc(*path)
        for path in (
            ("README.md",),
            ("USER_GUIDE.md",),
            ("web-ui-change-rules.md",),
        )
    )

    assert "powers_tool_webui" in text
    assert "powers_tool_core" in text
    assert "src/powers_tool_webui/static" in text


def test_webui_docs_describe_exact_support_as_product_only_ux():
    readme = read_webui_doc("README.md")
    guide = read_webui_doc("USER_GUIDE.md")
    text = f"{readme}\n{guide}"
    assert "Product-only" in readme
    for token in ("expected_model_id", "pending", "system-VISA"):
        assert token in text
    assert "--validation-allow-pending-live-support" not in text
    assert "Local/" not in text


def test_webui_docs_distinguish_installed_wrappers_and_standalone_artifact() -> None:
    readme = read_webui_doc("README.md")

    assert "powers-tool-webui" in readme
    assert "powers-tool-webui-launcher" in readme
    assert "dist\\powers-tool\\powers-tool-webui-launcher.exe" in readme
