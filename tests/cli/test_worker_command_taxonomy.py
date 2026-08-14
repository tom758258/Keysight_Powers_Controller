from __future__ import annotations

import pytest

from powers_tool_cli.worker_protocol import (
    ALLOWED_COMMANDS,
    OUTPUT_AFFECTING_COMMANDS,
    OUTPUT_COMMANDS,
    PROTECTION_COMMANDS,
    READ_ONLY_COMMANDS,
    TRIGGER_COMMANDS,
    _WORKER_COMMAND_TAXONOMY,
)
from powers_tool_core.command_contract import COMMAND_CONTRACTS


EXPECTED_CATEGORY_COMMANDS: dict[str, frozenset[str]] = {
    "read_only": frozenset({
        "identify",
        "read-status",
        "readback",
        "measure",
        "measure-all",
        "output-state",
        "protection-status",
        "error",
        "snapshot",
        "log",
    }),
    "output": frozenset({
        "set",
        "apply",
        "output-on",
        "output-off",
        "safe-off",
        "cycle-output",
        "ramp",
        "ramp-list",
        "smoke-output",
    }),
    "protection": frozenset({
        "protection-set",
        "clear-protection",
        "restore-from-snapshot",
        "sequence",
    }),
    "trigger": frozenset({
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    }),
    "unsupported": frozenset({
        "list-resources",
        "verify",
        "clear",
    }),
}

EXPECTED_OUTPUT_AFFECTING_COMMANDS = (
    EXPECTED_CATEGORY_COMMANDS["output"] | EXPECTED_CATEGORY_COMMANDS["protection"]
)


def test_all_core_commands_explicitly_classified() -> None:
    missing_from_taxonomy = set(COMMAND_CONTRACTS) - set(_WORKER_COMMAND_TAXONOMY)
    assert not missing_from_taxonomy, (
        f"Core commands missing from Worker taxonomy (fail-closed): {sorted(missing_from_taxonomy)}"
    )


def test_taxonomy_has_no_stray_commands_outside_core() -> None:
    stray_commands = set(_WORKER_COMMAND_TAXONOMY) - set(COMMAND_CONTRACTS)
    assert not stray_commands, (
        f"Worker taxonomy contains unknown commands outside Core: {sorted(stray_commands)}"
    )


@pytest.mark.parametrize("category, expected_commands", EXPECTED_CATEGORY_COMMANDS.items())
def test_category_exact_membership(category: str, expected_commands: frozenset[str]) -> None:
    actual_commands = frozenset(
        cmd for cmd, cat in _WORKER_COMMAND_TAXONOMY.items() if cat == category
    )
    assert actual_commands == expected_commands


def test_allowed_commands_matches_supported_taxonomy() -> None:
    supported_from_taxonomy = {
        cmd for cmd, cat in _WORKER_COMMAND_TAXONOMY.items() if cat != "unsupported"
    }
    assert ALLOWED_COMMANDS == supported_from_taxonomy
    assert len(ALLOWED_COMMANDS) == 29


def test_exported_category_sets_match_expected() -> None:
    assert READ_ONLY_COMMANDS == EXPECTED_CATEGORY_COMMANDS["read_only"]
    assert OUTPUT_COMMANDS == EXPECTED_CATEGORY_COMMANDS["output"]
    assert PROTECTION_COMMANDS == EXPECTED_CATEGORY_COMMANDS["protection"]
    assert TRIGGER_COMMANDS == EXPECTED_CATEGORY_COMMANDS["trigger"]


def test_supported_command_categories_are_mutually_exclusive_and_complete() -> None:
    category_sets = [
        READ_ONLY_COMMANDS,
        OUTPUT_COMMANDS,
        PROTECTION_COMMANDS,
        TRIGGER_COMMANDS,
    ]
    # Check pairwise disjointness
    for i, set_a in enumerate(category_sets):
        for j, set_b in enumerate(category_sets):
            if i < j:
                intersection = set_a & set_b
                assert not intersection, f"Command category overlap detected: {sorted(intersection)}"

    # Check union matches ALLOWED_COMMANDS
    assert set().union(*category_sets) == ALLOWED_COMMANDS


def test_output_affecting_commands_exact_content() -> None:
    assert OUTPUT_AFFECTING_COMMANDS == OUTPUT_COMMANDS | PROTECTION_COMMANDS
    assert OUTPUT_AFFECTING_COMMANDS == EXPECTED_OUTPUT_AFFECTING_COMMANDS
    assert len(OUTPUT_AFFECTING_COMMANDS) == 13


def test_unsupported_commands_fail_closed() -> None:
    unsupported = {
        cmd for cmd, cat in _WORKER_COMMAND_TAXONOMY.items() if cat == "unsupported"
    }
    assert unsupported == EXPECTED_CATEGORY_COMMANDS["unsupported"]
    for cmd in EXPECTED_CATEGORY_COMMANDS["unsupported"]:
        assert cmd not in ALLOWED_COMMANDS
        assert _WORKER_COMMAND_TAXONOMY[cmd] == "unsupported"
