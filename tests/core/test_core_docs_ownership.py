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


def test_core_overviews_do_not_freeze_validation_status_or_harness_details():
    core_docs = (
        read_core_doc("README.md"),
        read_core_doc("README.zh-TW.md"),
    )
    for text in core_docs:
        assert "hardware-validated support" not in text
        assert "hardware-validated 支援" not in text
        assert "candidate-evidence" not in text
        assert ".tmp_tests" not in text
        assert "-Suite full" not in text

    english = core_docs[0]
    assert "automatically promote product support" not in english
    assert "../CONTRIBUTING.md" in english
    assert "supported-models.md" in english

    supported = read_core_doc("supported-models.md")
    contributor = (REPO_ROOT / "docs" / "CONTRIBUTING.md").read_text(
        encoding="utf-8"
    )
    assert "## Product LIVE Exact-Scope Matrix" in supported
    assert "candidate evidence" in contributor.lower()
    assert "promotion" in contributor.lower()


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
