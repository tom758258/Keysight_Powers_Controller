import json
import re
from pathlib import Path

import powers_tool_cli.cli as cli


def _capabilities(resource: str, capsys) -> dict[str, object]:
    assert cli.main(["capabilities", "--simulate", "--json", "--resource", resource]) == 0
    return json.loads(capsys.readouterr().out)["data"]


def test_supported_models_matrix_matches_cli_support(capsys):
    matrix = Path("docs/core/supported-models.md").read_text(encoding="utf-8")
    for token in (
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e3646a",
        "not_supported_by_model",
    ):
        assert token in matrix

    e36312a = _capabilities("USB0::SIM::E36312A::INSTR", capsys)["command_support"]
    e3646a = _capabilities("ASRL1::SIM::E3646A::INSTR", capsys)["command_support"]
    edu = _capabilities("USB0::SIM::EDU36311A::INSTR", capsys)["command_support"]

    assert e36312a["smoke-output"]["real"] is True
    assert e36312a["protection-set"]["real"] is True
    assert e36312a["trigger-list"]["real"] is True
    assert e36312a["trigger-list"]["dry_run"] is True
    assert e3646a["set"]["real"] is True
    assert e3646a["set"]["hardware_validation"] == "validated"
    assert (
        e3646a["output-on"]["hardware_validation"]
        == "validated_confirm_threshold_conditional"
    )
    assert edu["validate-readonly"]["real"] is True
    assert edu["smoke-output"]["real"] is True
    assert edu["apply"]["real"] is True
    assert edu["trigger-list"]["real"] is False
    assert edu["protection-set"] == {
        "real": True,
        "simulate": True,
        "dry_run": True,
        "requires_confirm": True,
        "hardware_validation": "validated",
    }
    for command in (
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    ):
        assert edu[command]["real"] is False
        assert edu[command]["simulate"] is False
        assert edu[command]["dry_run"] is False
        assert edu[command]["hardware_validation"] == "not_supported_by_model"


def test_public_docs_preserve_machine_schema_and_support_tokens() -> None:
    paths = (
        "README.md",
        "docs/core/README.md",
        "docs/core/integration.md",
        "docs/core/supported-models.md",
        "docs/cli/README.md",
        "docs/cli/USER_GUIDE.md",
        "docs/contracts/power-cli-jsonl-contract.md",
        "docs/contracts/power-worker-contract.md",
        "docs/webui/README.md",
        "docs/webui/USER_GUIDE.md",
    )
    combined = "\n".join(Path(path).read_text(encoding="utf-8") for path in paths)

    for token in (
        "planning_model_id",
        "expected_model_id",
        "planning_profile_id",
        "schema_version: 2",
        'kind: "powers-tool-ramp-list"',
        "version: 2",
        "Product-active",
        "Candidate",
        "live_validated_full_suite",
        "feature_pending",
        "not_supported_by_model",
        "product_open=false",
    ):
        assert token in combined

    for legacy_token in (
        "implemented_pending_hardware_validation",
    ):
        assert legacy_token not in combined


def test_hidden_validation_flag_stays_in_contributing_for_core_support_docs() -> None:
    public_paths = (
        "docs/core/supported-models.md",
        "docs/core/integration.md",
    )
    public_docs = "\n".join(
        Path(path).read_text(encoding="utf-8") for path in public_paths
    )
    contributor = Path("docs/CONTRIBUTING.md").read_text(encoding="utf-8")
    hidden_flag = "--validation-allow-pending-live-support"

    assert hidden_flag in contributor
    assert hidden_flag not in public_docs


def test_core_support_document_ownership_is_explicit() -> None:
    supported = Path("docs/core/supported-models.md").read_text(encoding="utf-8")
    integration = Path("docs/core/integration.md").read_text(encoding="utf-8")
    contributor = Path("docs/CONTRIBUTING.md").read_text(encoding="utf-8")

    for token in (
        "--validation-allow-pending-live-support",
        "internal_validation_candidate_inventory",
        "transport_pending",
        "feature_pending",
        "live-cli-check.ps1",
        ".tmp_tests",
        "private/",
        "shareable/",
        "## Live Suite Validation Matrix",
        "## Model Enablement Lifecycle",
        "Candidate |",
        "candidate prerequisites",
    ):
        assert token not in supported

    for token in (
        "## Support-Policy Contract",
        "profile_validated",
        "not_supported_by_model",
        "live_validated_full_suite",
        "transport_pending",
        "feature_pending",
        "product_open",
        "internal_validation_candidate_inventory",
    ):
        assert token in integration

    assert "integration.md#support-policy-contract" in supported
    assert "core/integration.md#support-policy-contract" in contributor
    assert "supported-models.md" in integration
    assert "../CONTRIBUTING.md" in integration


def test_contributor_docs_preserve_safety_and_privacy_keywords() -> None:
    contributor = Path("docs/CONTRIBUTING.md").read_text(encoding="utf-8")

    for keyword in (
        "private/",
        "shareable/",
        "output OFF",
        "voltage",
        "current limit",
        "OVP/OCP",
        "cleanup",
        "private IP address",
        "serial number",
        "IDN string",
        "personal filesystem path",
    ):
        assert keyword in contributor


def test_public_dry_run_examples_do_not_use_live_resource_without_model():
    checked_paths = (
        "README.md",
        "docs/cli/README.md",
        "docs/cli/USER_GUIDE.md",
        "docs/core/README.md",
        "docs/core/supported-models.md",
        "docs/contracts/power-cli-jsonl-contract.md",
        "docs/webui/README.md",
        "docs/webui/USER_GUIDE.md",
    )
    offenders: list[str] = []
    for path in checked_paths:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            if "--dry-run" not in line:
                continue
            if (
                "$env:POWERS_TOOL_RESOURCE" in line
                and "--model" not in line
                and "::SIM::" not in line
            ):
                offenders.append(f"{path}:{line_number}: {line}")
            if (
                re.search(r"USB0::FAKE::\w+::INSTR", line)
                and "--model" not in line
            ):
                context = "\n".join(
                    lines[max(0, line_number - 5) : line_number + 2]
                )
                if "rejected" not in context and "Not OK" not in context:
                    offenders.append(f"{path}:{line_number}: {line}")

    assert offenders == []
