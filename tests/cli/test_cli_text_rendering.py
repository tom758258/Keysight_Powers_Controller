from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

import powers_tool_cli.cli as cli
from powers_tool_cli import cli_rendering
from powers_tool_cli.commands import output_run, sequence_run


def _format_text_value(value: object) -> str:
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value)


@pytest.mark.parametrize(
    ("command", "channel", "resource_data", "expected"),
    [
        (
            "set",
            1,
            {},
            (
                "Resource: USB0::SIM::E36312A::INSTR",
                "Channel: 1",
                "Current limit: 0.05 A",
                "Voltage: 1 V",
            ),
        ),
        (
            "apply",
            1,
            {},
            (
                "Resource: USB0::SIM::E36312A::INSTR",
                "Channel: 1",
                "Current limit: 0.05 A",
                "Voltage: 1 V",
                "Output enabled: false",
            ),
        ),
        (
            "output-on",
            1,
            {},
            (
                "Resource: USB0::SIM::E36312A::INSTR",
                "Channel: 1",
                "Output enabled: True",
            ),
        ),
        (
            "output-off",
            1,
            {},
            (
                "Resource: USB0::SIM::E36312A::INSTR",
                "Channel: 1",
                "Output enabled: False",
            ),
        ),
        (
            "safe-off",
            "all",
            {"outputs": [{"channel": 1, "enabled": False}, {"channel": 2, "enabled": True}]},
            (
                "Resource: USB0::SIM::E36312A::INSTR",
                "Channel: all",
                "Channel 1: Output enabled: False",
                "Channel 2: Output enabled: True",
            ),
        ),
        (
            "output-state",
            "all",
            {"outputs": [{"channel": 1, "enabled": True}, {"channel": 2, "enabled": False}]},
            (
                "Resource: USB0::SIM::E36312A::INSTR",
                "Channel: all",
                "Channel 1: Output enabled: true",
                "Channel 2: Output enabled: false",
            ),
        ),
        (
            "output-state",
            1,
            {"output_enabled": True},
            (
                "Resource: USB0::SIM::E36312A::INSTR",
                "Channel: 1",
                "Output enabled: true",
            ),
        ),
        (
            "cycle-output",
            1,
            {},
            (
                "Resource: USB0::SIM::E36312A::INSTR",
                "Channel: 1",
                "Cycle complete: true",
            ),
        ),
        (
            "ramp",
            1,
            {"steps": 3},
            (
                "Resource: USB0::SIM::E36312A::INSTR",
                "Channel: 1",
                "Steps: 3",
            ),
        ),
        (
            "ramp",
            None,
            {"channels": [1, 3], "steps": 3},
            (
                "Resource: USB0::SIM::E36312A::INSTR",
                "Channels: 1, 3",
                "Steps: 3",
            ),
        ),
        (
            "smoke-output",
            1,
            {
                "measurements": {"voltage": 1.25, "current": 0.05},
                "output": {"final_enabled": False},
            },
            (
                "Resource: USB0::SIM::E36312A::INSTR",
                "Channel: 1",
                "Measured voltage: 1.25 V",
                "Measured current: 0.05 A",
                "Final output enabled: False",
            ),
        ),
    ],
)
def test_format_core_output_result_preserves_exact_lines_and_inputs(
    command: str,
    channel: int | str | None,
    resource_data: dict[str, Any],
    expected: tuple[str, ...],
) -> None:
    before = deepcopy(resource_data)

    result = cli_rendering.format_core_output_result(
        command=command,
        resource="USB0::SIM::E36312A::INSTR",
        channel=channel,
        current=0.05,
        voltage=1.0,
        no_output=True,
        resource_data=resource_data,
        value_to_text=_format_text_value,
    )

    assert result == expected
    assert result is not cli_rendering.format_core_output_result(
        command=command,
        resource="USB0::SIM::E36312A::INSTR",
        channel=channel,
        current=0.05,
        voltage=1.0,
        no_output=True,
        resource_data=resource_data,
        value_to_text=_format_text_value,
    )
    assert resource_data == before


def test_format_core_output_result_rejects_unknown_command() -> None:
    with pytest.raises(ValueError, match="^unsupported core output command: unknown$"):
        cli_rendering.format_core_output_result(
            command="unknown",
            resource="USB0::SIM::E36312A::INSTR",
            channel=1,
            current=None,
            voltage=None,
            no_output=False,
            resource_data={},
            value_to_text=_format_text_value,
        )


def test_format_output_plan_preserves_parameter_order_and_scalar_text() -> None:
    plan = {
        "operation": {"name": "set"},
        "target": {"resource": "USB0::SIM::E36312A::INSTR", "channel": 1},
        "hardware_touched": False,
        "steps": [
            {
                "index": 1,
                "action": "set_current_limit",
                "parameters": {
                    "channel": 1,
                    "current": 0.05,
                    "enabled": True,
                    "missing": None,
                    "nan": math.nan,
                    "infinity": math.inf,
                },
            },
            {"index": 2, "action": "noop", "parameters": {}},
        ],
    }
    before = deepcopy(plan)

    result = cli_rendering.format_output_plan(
        plan,
        mode="dry-run",
        dry_run=True,
        value_to_text=_format_text_value,
    )

    assert result == (
        "Dry-run plan for set",
        "Mode: dry-run",
        "Resource: USB0::SIM::E36312A::INSTR",
        "Channel: 1",
        "Hardware touched: false",
        "Steps:",
        "1. set_current_limit channel=1 current=0.05 enabled=True missing=None nan=nan infinity=inf",
        "2. noop",
    )
    assert result is not cli_rendering.format_output_plan(
        plan,
        mode="dry-run",
        dry_run=True,
        value_to_text=_format_text_value,
    )
    assert repr(plan) == repr(before)


def test_format_output_plan_renders_multi_channel_target_without_channel() -> None:
    plan = {
        "operation": {"name": "ramp"},
        "target": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "channels": [1, 3],
        },
        "hardware_touched": False,
        "steps": [],
    }

    result = cli_rendering.format_output_plan(
        plan,
        mode="dry-run",
        dry_run=True,
        value_to_text=_format_text_value,
    )

    assert result == (
        "Dry-run plan for ramp",
        "Mode: dry-run",
        "Resource: USB0::SIM::E36312A::INSTR",
        "Channels: 1, 3",
        "Hardware touched: false",
        "Steps:",
    )


def test_format_scpi_plan_preserves_simulation_label_and_step_order() -> None:
    plan = {
        "operation": {"name": "clear"},
        "target": {"resource": "USB0::SIM::E36312A::INSTR"},
        "hardware_touched": False,
        "steps": [
            {"index": 1, "command": "*CLS"},
            {"index": 2, "command": "SYST:ERR?"},
        ],
    }
    before = deepcopy(plan)

    result = cli_rendering.format_scpi_plan(plan, mode="simulate", dry_run=False)

    assert result == (
        "Simulation plan for clear",
        "Mode: simulate",
        "Resource: USB0::SIM::E36312A::INSTR",
        "Hardware touched: false",
        "Steps:",
        "1. *CLS",
        "2. SYST:ERR?",
    )
    assert result is not cli_rendering.format_scpi_plan(plan, mode="simulate", dry_run=False)
    assert plan == before


@pytest.mark.parametrize(
    ("command", "channel", "data", "expected"),
    [
        (
            "trigger-pulse",
            1,
            {"pins": [1, 3], "exclusive_pins": True, "polarity": "negative"},
            (
                "Resource: USB0::SIM::E36312A::INSTR",
                "Pins: 1, 3",
                "Exclusive pins: true",
                "Polarity: negative",
                "Triggered: True",
            ),
        ),
        (
            "trigger-status",
            "all",
            {"channel": "all"},
            ("Resource: USB0::SIM::E36312A::INSTR", "Channel: all"),
        ),
        (
            "trigger-list",
            1,
            {"steps": 2},
            ("Resource: USB0::SIM::E36312A::INSTR", "Steps: 2"),
        ),
        (
            "trigger-step",
            1,
            {"trigger": {"completed": False}},
            ("Resource: USB0::SIM::E36312A::INSTR", "Triggered: false"),
        ),
        ("trigger-fire", None, {}, ("Triggered: true",)),
        ("trigger-abort", "all", {}, ("Channel all: aborted",)),
    ],
)
def test_format_core_trigger_result_preserves_exact_lines_and_inputs(
    command: str,
    channel: int | str | None,
    data: dict[str, Any],
    expected: tuple[str, ...],
) -> None:
    before = deepcopy(data)

    result = cli_rendering.format_core_trigger_result(
        command=command,
        resource="USB0::SIM::E36312A::INSTR",
        channel=channel,
        mode="simulate",
        data=data,
    )

    assert result == expected
    assert result is not cli_rendering.format_core_trigger_result(
        command=command,
        resource="USB0::SIM::E36312A::INSTR",
        channel=channel,
        mode="simulate",
        data=data,
    )
    assert data == before


def test_format_core_trigger_result_preserves_plan_and_unknown_command_behavior() -> None:
    plan = {
        "operation": {"name": "trigger-pulse"},
        "target": {"resource": "USB0::SIM::E36312A::INSTR"},
        "hardware_touched": False,
        "steps": [{"index": 1, "command": "*TRG"}],
    }

    assert cli_rendering.format_core_trigger_result(
        command="trigger-pulse",
        resource="USB0::SIM::E36312A::INSTR",
        channel=1,
        mode="dry-run",
        data={"plan": plan},
    ) == (
        "Dry-run plan for trigger-pulse",
        "Mode: dry-run",
        "Resource: USB0::SIM::E36312A::INSTR",
        "Hardware touched: false",
        "Steps:",
        "1. *TRG",
    )
    assert cli_rendering.format_core_trigger_result(
        command="unknown",
        resource="USB0::SIM::E36312A::INSTR",
        channel=None,
        mode="simulate",
        data={},
    ) == ()


@pytest.mark.parametrize(
    "resource",
    [
        "USB0::SIM::E36312A::INSTR",
        {"name": "USB0::SIM::E36312A::INSTR"},
    ],
)
def test_format_sequence_summary_preserves_resource_forms(resource: object) -> None:
    data = {"resource": resource, "status": "completed", "completed_steps": 3}
    before = deepcopy(data)

    result = cli_rendering.format_sequence_summary(data)

    assert result == (
        "Resource: USB0::SIM::E36312A::INSTR",
        "Status: completed",
        "Completed steps: 3",
    )
    assert result is not cli_rendering.format_sequence_summary(data)
    assert data == before


def test_format_execution_summary_notice_preserves_exact_lines() -> None:
    assert cli_rendering.format_execution_summary_notice(12_345, None) == (
        "Execution units: 12,345 (maximum 1,000,000).",
    )
    assert cli_rendering.format_execution_summary_notice(1_234_567, "long workflow") == (
        "Execution units: 1,234,567 (maximum 1,000,000).",
        "Warning: long workflow",
    )


def test_direct_formatters_do_not_write_streams(capsys) -> None:
    cli_rendering.format_output_plan(
        {
            "operation": {"name": "set"},
            "target": {"resource": "USB0::SIM::E36312A::INSTR", "channel": 1},
            "hardware_touched": False,
            "steps": [],
        },
        mode="dry-run",
        dry_run=True,
        value_to_text=_format_text_value,
    )
    cli_rendering.format_sequence_summary(
        {"resource": "USB0::SIM::E36312A::INSTR", "status": "valid", "completed_steps": 0}
    )
    cli_rendering.format_execution_summary_notice(12_345, "long workflow")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_workflow_execution_notice_callers_keep_stderr_routing_and_gating(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = {
        "execution_units": 1_234_567,
        "execution_warning": "long workflow",
    }
    warning_payload = [{"code": "long_running_workflow", "message": "long workflow"}]

    monkeypatch.setattr(output_run, "_request_for_args", lambda _args: {})
    monkeypatch.setattr(output_run, "_safety_limits_for_args", lambda _args: object())
    monkeypatch.setattr(output_run, "_validate_output_request", lambda *_args: None)
    monkeypatch.setattr(output_run, "_output_plan_for_args", lambda _args: dict(summary))
    monkeypatch.setattr(output_run, "_append_completion_pulse_plan", lambda *_args: None)
    monkeypatch.setattr(output_run, "_print_output_plan", lambda *_args, **_kwargs: None)

    output_text_args = argparse.Namespace(
        command="ramp",
        simulate=True,
        dry_run=True,
        json=False,
        completion_pulse_timing="segment",
    )
    assert output_run._run_output_plan(output_text_args) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "Execution units: 1,234,567 (maximum 1,000,000).\n"
        "Warning: long workflow\n"
    )

    json_calls: list[dict[str, object]] = []
    monkeypatch.setattr(output_run, "emit_json_success", lambda **kwargs: json_calls.append(kwargs))
    monkeypatch.setattr(output_run, "_execution_for_args", lambda *_args, **_kwargs: {})
    output_json_args = argparse.Namespace(
        command="ramp",
        simulate=True,
        dry_run=True,
        json=True,
        completion_pulse_timing="segment",
    )
    assert output_run._run_output_plan(output_json_args) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert json_calls[0]["warnings"] == warning_payload

    monkeypatch.setattr(sequence_run, "validate_request_admission", lambda request: request)
    monkeypatch.setattr(sequence_run, "workflow_execution_summary", lambda _request: dict(summary))
    sequence_request = object()

    sequence_text_args = argparse.Namespace(json=False, lint=False)
    returned_request, returned_summary, warnings = sequence_run._workflow_start_summary(
        sequence_text_args,
        sequence_request,
    )
    assert returned_request is sequence_request
    assert returned_summary == summary
    assert warnings == warning_payload
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "Execution units: 1,234,567 (maximum 1,000,000).\n"
        "Warning: long workflow\n"
    )

    for args in (argparse.Namespace(json=True, lint=False), argparse.Namespace(json=False, lint=True)):
        _, _, warnings = sequence_run._workflow_start_summary(args, sequence_request)
        assert warnings == warning_payload
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


def test_cli_thin_adapters_emit_each_formatter_line(capsys) -> None:
    output_run._print_core_output_result(
        argparse.Namespace(
            command="set",
            resource="USB0::SIM::E36312A::INSTR",
            channel=1,
            current=0.05,
            voltage=1.0,
        ),
        {},
    )
    sequence_run._print_sequence_summary(
        {"resource": "USB0::SIM::E36312A::INSTR", "status": "completed", "completed_steps": 2}
    )

    captured = capsys.readouterr()
    assert captured.out == (
        "Resource: USB0::SIM::E36312A::INSTR\n"
        "Channel: 1\n"
        "Current limit: 0.05 A\n"
        "Voltage: 1 V\n"
        "Resource: USB0::SIM::E36312A::INSTR\n"
        "Status: completed\n"
        "Completed steps: 2\n"
    )
    assert captured.err == ""


def test_cli_text_success_uses_formatter_and_json_and_errors_do_not(monkeypatch, capsys) -> None:
    calls: list[dict[str, object]] = []

    def format_plan(*_args: object, **kwargs: object) -> tuple[str, ...]:
        calls.append(kwargs)
        return ("formatter sentinel",)

    monkeypatch.setattr(cli_rendering, "format_output_plan", format_plan)
    args = [
        "set",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--voltage",
        "1",
        "--dry-run",
    ]

    assert cli.main(args) == 0
    captured = capsys.readouterr()
    assert captured.out == "formatter sentinel\n"
    assert captured.err == ""
    assert len(calls) == 1

    def fail_formatter(*_args: object, **_kwargs: object) -> tuple[str, ...]:
        raise AssertionError("JSON and text-error paths must not invoke success rendering")

    monkeypatch.setattr(cli_rendering, "format_output_plan", fail_formatter)
    assert cli.main([*args, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 2
    assert payload["command"] == {"name": "set"}

    assert cli.main([
        "set",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--dry-run",
    ]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "set requires voltage, current, or both\n"


def test_rendering_module_import_has_no_cli_worker_or_core_execution_side_effect() -> None:
    root = Path(__file__).resolve().parents[2]
    script = "\n".join(
        [
            "import sys",
            f"sys.path.insert(0, {str(root / 'src')!r})",
            "import powers_tool_cli.cli_rendering",
            "assert 'powers_tool_cli.cli' not in sys.modules",
            "assert 'powers_tool_cli.worker' not in sys.modules",
            "assert 'powers_tool_core.operations' not in sys.modules",
            "assert 'powers_tool_core.trigger' not in sys.modules",
        ]
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=environment,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
