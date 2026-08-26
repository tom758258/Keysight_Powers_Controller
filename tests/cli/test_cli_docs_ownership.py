from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_ROOT = REPO_ROOT / "docs" / "cli"


def read_cli_doc(*parts: str) -> str:
    return DOC_ROOT.joinpath(*parts).read_text(encoding="utf-8")


def read_contract(name: str) -> str:
    return (REPO_ROOT / "docs" / "contracts" / name).read_text(encoding="utf-8")


def read_markdown_section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    assert marker in text
    section = text.split(marker, 1)[1]
    return section.split("\n## ", 1)[0]


def read_html_section(text: str, heading_id: str) -> str:
    marker = f'<h2 id="{heading_id}">'
    assert marker in text
    section = text.split(marker, 1)[1]
    return section.split("\n<h2 ", 1)[0]


def test_cli_docs_are_root_local_and_contracts_are_root_level():
    assert (DOC_ROOT / "README.md").exists()
    assert (REPO_ROOT / "CHANGELOG.md").exists()
    assert not (DOC_ROOT / "CHANGELOG.md").exists()

    assert (DOC_ROOT / "USER_GUIDE.md").exists()

    for package_contract in (
        "power-cli-jsonl-contract.md",
        "power-worker-contract.md",
        "power-orchestrator-workflows.md",
        "common-worker-protocol.md",
    ):
        assert not (DOC_ROOT / package_contract).exists()

    for contract in (
        "common-worker-protocol.md",
        "common-cli-jsonl-contract.md",
        "common-orchestrator-workflows.md",
        "power-worker-contract.md",
        "power-cli-jsonl-contract.md",
        "power-orchestrator-workflows.md",
    ):
        assert (REPO_ROOT / "docs" / "contracts" / contract).exists()


def test_cli_readme_keeps_cli_fields_out_of_core_schema():
    text = read_cli_doc("README.md")
    section = read_markdown_section(text, "Package Contents")

    assert "measurement_cli_name" in section
    assert "argparse.Namespace" in section
    assert "CLI owns" in section
    assert "Core owns" in section


def test_power_contracts_link_common_contracts():
    cli_contract = read_contract("power-cli-jsonl-contract.md")
    workflow_contract = read_contract("power-orchestrator-workflows.md")
    worker_contract = read_contract("power-worker-contract.md")

    assert "common-cli-jsonl-contract.md" in cli_contract
    assert "common-orchestrator-workflows.md" in workflow_contract
    assert "common-worker-protocol.md" in worker_contract


def test_common_contracts_stay_instrument_neutral():
    common_text = "\n".join(
        read_contract(name)
        for name in (
            "common-cli-jsonl-contract.md",
            "common-worker-protocol.md",
            "common-orchestrator-workflows.md",
        )
    )

    assert "acquisition" not in common_text.lower()


def test_cli_user_guides_defer_e3646a_command_inventory_to_supported_models():
    paths = (
        "USER_GUIDE.md",
        "USER_GUIDE.zh-TW.md",
        "USER_GUIDE.zh-TW.html",
    )
    texts = {path: read_cli_doc(path) for path in paths}

    forbidden_inventory_phrases = (
        "product-open model-aware commands are `measure`",
        "Product-open model-aware commands 是 `measure`",
        "Product-open model-aware commands 是 <code>measure</code>",
    )
    inline_command = re.compile(
        r"`[a-z][a-z0-9-]*`|<code>[a-z][a-z0-9-]*</code>",
        re.IGNORECASE,
    )

    for path, text in texts.items():
        for phrase in forbidden_inventory_phrases:
            assert phrase not in text
        assert re.search(
            r"supported-models(?:\.zh-TW)?\.md#product-live-exact-scope-matrix",
            text,
        )
        for stable_token in ("INST:NSEL", "OUTP ON/OFF", "native LIST"):
            assert stable_token in text

        if path.endswith(".html"):
            intro = read_html_section(text, "e3646a-rs-232-asrl").split(
                '<div class="code-wrapper">', 1
            )[0]
        else:
            intro = read_markdown_section(text, "E3646A RS-232 / ASRL").split(
                "```", 1
            )[0]

        # Stable operator prose may name a few commands, but a dense inventory
        # belongs only in the canonical Product LIVE exact-scope matrix.
        assert len(inline_command.findall(intro)) < 8


def test_cli_user_guides_do_not_depend_on_developer_docs():
    markdown_link = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

    for path in ("USER_GUIDE.md", "USER_GUIDE.zh-TW.md"):
        text = read_cli_doc(path)

        for target in markdown_link.findall(text):
            basename = target.rsplit("/", 1)[-1]
            assert not basename.startswith("README"), path
            assert "contracts/" not in target, path
            assert "core/integration.md" not in target, path
            assert "webui/USER_GUIDE" not in target, path


def test_cli_readme_defers_physical_planning_inventory_to_core_metadata():
    text = read_cli_doc("README.md")
    section = read_markdown_section(
        text, "Planning Identities And Live Expected-Model Guards"
    )

    assert "../core/supported-models.md" in section
    assert "Accepted physical planning IDs are `keysight-e36312a`" not in section
