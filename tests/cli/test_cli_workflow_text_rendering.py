from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

import powers_tool_cli.cli as cli
from powers_tool_cli import cli_rendering
from powers_tool_cli.commands import readonly as readonly_commands


SIM_RESOURCE = "USB0::SIM::E36312A::INSTR"


def _value_to_text(value: object) -> str:
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value)


def test_p3_formatters_preserve_exact_lines_and_inputs(capsys: pytest.CaptureFixture[str]) -> None:
    protection_channels = [
        {
            "channel": 2,
            "protection": {
                "ovp_voltage": 5.0,
                "ocp_enabled": True,
                "ocp_delay": 0.5,
                "ocp_delay_trigger": "cc-transition",
            },
        },
        {
            "channel": 1,
            "protection": {
                "ovp_voltage": None,
                "ocp_enabled": False,
                "ocp_delay": 0.0,
                "ocp_delay_trigger": "setting-change",
            },
        },
    ]
    report = {"result": "passed"}
    log_result = {"samples_written": 2, "stopped": False}
    sequence_lint = {"status": "valid", "sequence_version": 2, "step_count": 6}
    ramp_list = {
        "status": "completed",
        "ramp_list_version": 4,
        "segment_count": 2,
        "completed_segments": 4,
    }
    before = deepcopy((protection_channels, report, log_result, sequence_lint, ramp_list))

    assert cli_rendering.format_clear_success(SIM_RESOURCE) == (
        f"Cleared instrument status for {SIM_RESOURCE}",
    )
    assert cli_rendering.format_clear_protection_success(SIM_RESOURCE, []) == (
        f"Resource: {SIM_RESOURCE}",
        "Cleared channels: ",
    )
    assert cli_rendering.format_clear_protection_success(SIM_RESOURCE, [2, 1]) == (
        f"Resource: {SIM_RESOURCE}",
        "Cleared channels: 2, 1",
    )
    assert cli_rendering.format_protection_set_success(
        SIM_RESOURCE,
        protection_channels,
        value_to_text=_value_to_text,
    ) == (
        f"Resource: {SIM_RESOURCE}",
        "Channel 2: OVP=5, OCP=True, OCP delay=0.5, OCP delay trigger=cc-transition",
        "Channel 1: OVP=None, OCP=False, OCP delay=0, OCP delay trigger=setting-change",
    )
    assert cli_rendering.format_hardware_report_success("report.json", "summary.md", report) == (
        "Report: report.json",
        "Summary: summary.md",
        "Result: passed",
    )
    assert cli_rendering.format_restore_from_snapshot_success(SIM_RESOURCE, [3, 1]) == (
        f"Resource: {SIM_RESOURCE}",
        "Restored channels: 3, 1",
    )
    assert cli_rendering.format_log_success(SIM_RESOURCE, "samples.csv", log_result) == (
        f"Resource: {SIM_RESOURCE}",
        "CSV: samples.csv",
        "Samples written: 2",
        "Stopped: false",
    )
    assert cli_rendering.format_sequence_lint_summary(sequence_lint) == (
        "Status: valid",
        "Sequence version: 2",
        "Steps: 6",
    )
    assert cli_rendering.format_ramp_list_summary(ramp_list) == (
        "Status: completed",
        "Ramp list version: 4",
        "Segments: 2",
        "Completed segments: 4",
    )
    assert (protection_channels, report, log_result, sequence_lint, ramp_list) == before
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize(
    ("formatter_name", "argv"),
    [
        ("format_clear_success", ["clear", "--simulate", "--resource", SIM_RESOURCE]),
        (
            "format_log_success",
            [
                "log",
                "--simulate",
                "--resource",
                SIM_RESOURCE,
                "--channel",
                "1",
                "--interval-sec",
                "0.01",
                "--samples",
                "1",
                "--csv",
                ".tmp_tests/cli_rendering_p3/log.csv",
            ],
        ),
        (
            "format_sequence_lint_summary",
            [
                "sequence",
                "--lint",
                "--resource",
                SIM_RESOURCE,
                "--file",
                "examples/sequence-readonly.yaml",
            ],
        ),
        (
            "format_ramp_list_summary",
            [
                "ramp-list",
                "--lint",
                "--segment",
                "1",
                "0.1",
                "0",
                "1",
                "1",
                "0",
                "0",
            ],
        ),
    ],
)
def test_p3_no_hardware_runners_delegate_text_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    formatter_name: str,
    argv: list[str],
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def sentinel(*args: object, **kwargs: object) -> tuple[str, ...]:
        calls.append((args, kwargs))
        return ("formatter sentinel",)

    monkeypatch.setattr(cli_rendering, formatter_name, sentinel)
    assert cli.main(argv) == 0
    captured = capsys.readouterr()
    assert captured.out == "formatter sentinel\n"
    assert captured.err == ""
    assert calls


def test_p3_core_backed_runners_delegate_text_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def sentinel(*_args: object, **_kwargs: object) -> tuple[str, ...]:
        calls.append("formatter")
        return ("formatter sentinel",)

    def run_protection(request: Any, **_kwargs: object) -> dict[str, Any]:
        if request.command == "clear-protection":
            return {"resource": SIM_RESOURCE, "cleared_channels": [2, 1]}
        return {
            "resource": SIM_RESOURCE,
            "channels": [
                {
                    "channel": 1,
                    "protection": {
                        "ovp_voltage": 5.0,
                        "ocp_enabled": True,
                        "ocp_delay": 0.5,
                        "ocp_delay_trigger": "cc-transition",
                    },
                }
            ],
        }

    monkeypatch.setattr(cli.protection_core, "run_protection", run_protection)
    monkeypatch.setattr(cli_rendering, "format_clear_protection_success", sentinel)
    assert cli.main(["clear-protection", "--resource", SIM_RESOURCE, "--channel", "1", "--confirm"]) == 0
    assert capsys.readouterr().out == "formatter sentinel\n"

    monkeypatch.setattr(cli_rendering, "format_protection_set_success", sentinel)
    assert cli.main([
        "protection-set", "--resource", SIM_RESOURCE, "--channel", "1", "--ovp-voltage", "5", "--confirm",
    ]) == 0
    assert capsys.readouterr().out == "formatter sentinel\n"

    monkeypatch.setattr(cli.restore_core, "run_restore", lambda *_args, **_kwargs: {"restored_channels": [1]})
    monkeypatch.setattr(cli_rendering, "format_restore_from_snapshot_success", sentinel)
    assert cli.main([
        "restore-from-snapshot", "--resource", SIM_RESOURCE, "--snapshot", str(tmp_path / "snapshot.json"), "--channel", "1", "--confirm",
    ]) == 0
    assert capsys.readouterr().out == "formatter sentinel\n"

    monkeypatch.setattr(readonly_commands, "_build_hardware_report", lambda _args: {"result": "passed"})
    monkeypatch.setattr(readonly_commands, "_write_hardware_report_files", lambda *_args: None)
    monkeypatch.setattr(cli_rendering, "format_hardware_report_success", sentinel)
    assert cli.main([
        "hardware-report", "--input-dir", str(tmp_path), "--target", "keysight-e36312a", "--connection", "USB",
        "--resource", SIM_RESOURCE, "--report-json", str(tmp_path / "report.json"), "--summary-md", str(tmp_path / "summary.md"),
    ]) == 0
    assert capsys.readouterr().out == "formatter sentinel\n"
    assert calls == ["formatter", "formatter", "formatter", "formatter"]


def test_p3_json_and_error_paths_skip_success_formatters(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def fail_formatter(*_args: object, **_kwargs: object) -> tuple[str, ...]:
        raise AssertionError("JSON and error paths must not invoke success rendering")

    monkeypatch.setattr(cli_rendering, "format_clear_success", fail_formatter)
    assert cli.main(["clear", "--simulate", "--json", "--resource", SIM_RESOURCE]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == 2

    monkeypatch.setattr(cli.protection_core, "run_protection", lambda *_args, **_kwargs: {"resource": SIM_RESOURCE, "channels": []})
    monkeypatch.setattr(cli_rendering, "format_protection_set_success", fail_formatter)
    assert cli.main([
        "protection-set", "--json", "--resource", SIM_RESOURCE, "--channel", "1", "--ovp-voltage", "5", "--confirm",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == 2

    monkeypatch.setattr(cli.restore_core, "run_restore", lambda *_args, **_kwargs: {"restored_channels": [1]})
    monkeypatch.setattr(cli_rendering, "format_restore_from_snapshot_success", fail_formatter)
    assert cli.main([
        "restore-from-snapshot", "--json", "--resource", SIM_RESOURCE, "--snapshot", str(tmp_path / "snapshot.json"), "--channel", "1", "--confirm",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == 2

    monkeypatch.setattr(cli_rendering, "format_clear_protection_success", fail_formatter)
    monkeypatch.setattr(
        cli.protection_core,
        "run_protection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            cli.ConfirmationRequiredError("confirmation required")
        ),
    )
    assert cli.main(["clear-protection", "--resource", SIM_RESOURCE, "--channel", "1"]) == 2
    assert capsys.readouterr().out == ""

    monkeypatch.setattr(readonly_commands, "_write_hardware_report_files", lambda *_args: (_ for _ in ()).throw(OSError("write failed")))
    monkeypatch.setattr(cli_rendering, "format_hardware_report_success", fail_formatter)
    assert cli.main([
        "hardware-report", "--input-dir", str(tmp_path), "--target", "keysight-e36312a", "--connection", "USB",
        "--resource", SIM_RESOURCE, "--report-json", str(tmp_path / "report.json"), "--summary-md", str(tmp_path / "summary.md"),
    ]) == 2
    assert "write failed" in capsys.readouterr().err


def test_p3_core_io_and_workflow_interruption_skip_success_formatters(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def fail_formatter(*_args: object, **_kwargs: object) -> tuple[str, ...]:
        raise AssertionError("error paths must not invoke success rendering")

    monkeypatch.setattr(cli_rendering, "format_restore_from_snapshot_success", fail_formatter)
    monkeypatch.setattr(
        cli.restore_core,
        "run_restore",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(cli.CoreIoError("restore failed")),
    )
    assert cli.main([
        "restore-from-snapshot", "--resource", SIM_RESOURCE, "--snapshot", str(tmp_path / "snapshot.json"), "--channel", "1", "--confirm",
    ]) == 1
    assert "restore failed" in capsys.readouterr().err

    monkeypatch.setattr(cli_rendering, "format_sequence_lint_summary", fail_formatter)
    monkeypatch.setattr(
        cli,
        "run_core_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(cli.CommandCancelled("sequence stopped")),
    )
    assert cli.main([
        "sequence", "--lint", "--resource", SIM_RESOURCE, "--file", "examples/sequence-readonly.yaml",
    ]) == 3
    assert "sequence stopped" in capsys.readouterr().err


def test_p3_artifact_success_precedes_rendering_and_failed_artifacts_do_not_render(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(readonly_commands, "_build_hardware_report", lambda _args: events.append("build") or {"result": "passed"})
    monkeypatch.setattr(readonly_commands, "_write_hardware_report_files", lambda *_args: events.append("write"))
    monkeypatch.setattr(cli_rendering, "format_hardware_report_success", lambda *_args: events.append("format") or ("summary",))
    monkeypatch.setattr(readonly_commands, "_emit_text_lines", lambda _lines: events.append("emit"))

    assert cli.main([
        "hardware-report", "--input-dir", str(tmp_path), "--target", "keysight-e36312a", "--connection", "USB",
        "--resource", SIM_RESOURCE, "--report-json", str(tmp_path / "report.json"), "--summary-md", str(tmp_path / "summary.md"),
    ]) == 0
    assert events == ["build", "write", "format", "emit"]
    assert capsys.readouterr().out == ""


def test_p3_log_collection_precedes_rendering(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        readonly_commands,
        "_collect_log_samples",
        lambda *_args, **_kwargs: events.append("collect")
        or {"samples_written": 1, "stopped": False},
    )
    monkeypatch.setattr(
        cli_rendering,
        "format_log_success",
        lambda *_args: events.append("format") or ("summary",),
    )
    monkeypatch.setattr(readonly_commands, "_emit_text_lines", lambda _lines: events.append("emit"))

    assert cli.main([
        "log", "--resource", SIM_RESOURCE, "--channel", "1", "--interval-sec", "0.01", "--samples", "1",
        "--csv", str(tmp_path / "samples.csv"),
    ]) == 0
    assert events == ["collect", "format", "emit"]
    assert capsys.readouterr().out == ""
