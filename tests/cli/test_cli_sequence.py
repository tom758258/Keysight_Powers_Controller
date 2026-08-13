import json
import csv
from types import SimpleNamespace

import pytest

import powers_tool_core.connection as connection
import powers_tool_cli.cli as cli
from powers_tool_core.core import CommandCancelled, CoreExecutionError, StopCleanupError
from powers_tool_core.errors import VisaConnectionError

from tests.cli.cli_test_helpers import (
    OUTPUT_RESOURCE,
    SERIAL_TERMINATION_ARGS,
    WRITE_VERIFICATION_REQUEST_DEFAULTS,
    FakeSession,
    assert_live_scope_rejected,
    expected_idn,
    expected_resource,
    output_command_args,
    write_safety_config,
)

def test_sequence_dry_run_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for sequence dry-run")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "sequence",
                "--dry-run",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--file",
                "examples/sequence-readonly.yaml",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "planned"
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == [
        "log",
        "measure",
        "readback",
        "output-state",
        "wait",
        "safe-off",
    ]

def test_sequence_v1_file_loop_override_upgrades_to_v2(tmp_path, capsys) -> None:
    sequence_file = tmp_path / "sequence.json"
    sequence_file.write_text(
        json.dumps({"version": 1, "steps": [{"action": "wait", "seconds": 0}]}),
        encoding="utf-8",
    )

    assert cli.main([
        "sequence", "--dry-run", "--json", "--file", str(sequence_file), "--loop-count", "2",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["version"] == 2
    assert payload["data"]["plan"]["loop_count"] == 2

def test_sequence_lint_parses_bundled_yaml(capsys) -> None:
    assert (
        cli.main(
            [
                "sequence",
                "--lint",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--file",
                "examples/sequence-readonly.yaml",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "valid"
    assert payload["data"]["sequence_version"] == 2
    assert payload["data"]["loop_count"] == 1
    assert payload["data"]["step_count"] == 6

def test_sequence_simulate_executes_read_only_steps(capsys) -> None:
    assert (
        cli.main(
            [
                "sequence",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--file",
                "examples/sequence-readonly.yaml",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "completed"
    assert payload["data"]["completed_steps"] == 6
    assert payload["data"]["results"][1]["measurements"] == {"voltage": 2.02, "current": 0.202}

def test_sequence_real_forwards_serial_options_to_opener(monkeypatch, tmp_path, capsys) -> None:
    sequence_file = tmp_path / "wait-sequence.json"
    sequence_file.write_text(
        json.dumps({"version": 1, "steps": [{"action": "wait", "seconds": 0}]}),
        encoding="utf-8",
    )
    opened = []

    def fake_open_resource(resource, resource_manager=None, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append(kwargs)
        return FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0")

    monkeypatch.setattr(cli, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                "sequence",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--file",
                str(sequence_file),
                *SERIAL_TERMINATION_ARGS,
            ]
        )
        == 0
    )

    json.loads(capsys.readouterr().out)
    serial_options = opened[0]["serial_options"]
    assert serial_options.read_termination == "\r\n"
    assert serial_options.write_termination == "\n"
    assert opened[0]["serial_remote"] is True
    assert opened[0]["serial_local_on_close"] is True
