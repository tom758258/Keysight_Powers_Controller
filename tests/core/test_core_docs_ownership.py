from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_ROOT = REPO_ROOT / "docs" / "core"


def read_core_doc(*parts: str) -> str:
    return DOC_ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_core_docs_are_root_local():
    assert (DOC_ROOT / "README.md").exists()
    assert (REPO_ROOT / "CHANGELOG.md").exists()
    assert not (DOC_ROOT / "CHANGELOG.md").exists()

    for path in (
        "integration.md",
        "supported-models.md",
    ):
        assert (DOC_ROOT / path).exists()

    for adapter_doc in (
        "cli-integration.md",
        "power-cli-jsonl-contract.md",
        "power-worker-contract.md",
    ):
        assert not (DOC_ROOT / adapter_doc).exists()


def test_core_integration_documents_package_boundary():
    text = read_core_doc("integration.md")

    assert "powers_tool_core" in text
    assert "powers_tool_cli" in text
    assert "powers_tool_webui" in text
    assert "SCPI" in text


def test_root_contracts_remain_canonical():
    for contract in (
        "common-worker-protocol.md",
        "common-cli-jsonl-contract.md",
        "common-orchestrator-workflows.md",
        "power-worker-contract.md",
        "power-cli-jsonl-contract.md",
        "power-orchestrator-workflows.md",
    ):
        assert (REPO_ROOT / "docs" / "contracts" / contract).exists()


def test_public_identity_docs_keep_machine_readable_ownership_tokens():
    root = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    core = read_core_doc("README.md")
    assert "powers_tool_core" in root
    assert "docs/core/supported-models.md" in root
    assert "powers_tool_core" in core


def test_root_testing_guidelines_are_linked_and_structural():
    guidelines_path = REPO_ROOT / "docs" / "testing-guidelines.md"
    assert guidelines_path.exists()

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/testing-guidelines.md" in readme

    guidelines = guidelines_path.read_text(encoding="utf-8")
    for heading in (
        "# Testing Guidelines",
        "## What To Test",
        "## What Not To Freeze",
    ):
        assert heading in guidelines

    for token in ("SCPI", "safety", "JSON"):
        assert token in guidelines
