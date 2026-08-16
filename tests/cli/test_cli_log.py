import csv
import json

import powers_tool_cli.cli as cli
import powers_tool_cli.cli_runtime as cli_runtime
import powers_tool_cli.commands.readonly as readonly_commands

from tests.cli.cli_test_helpers import (
    FakeSession,
    assert_live_scope_rejected,
)
def test_log_simulate_json_writes_csv(tmp_path, capsys) -> None:
    csv_path = tmp_path / "edu-log.csv"

    assert (
        cli.main(
            [
                "log",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--channel",
                "2",
                "--interval-sec",
                "0.01",
                "--samples",
                "2",
                "--csv",
                str(csv_path),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert payload["data"]["samples_written"] == 2
    assert payload["data"]["stopped"] is False
    assert rows[0].keys() == set(cli.LOG_CSV_FIELDS)
    assert rows[0]["resource"] == "USB0::SIM::EDU36311A::INSTR"
    assert rows[0]["model"] == "EDU36311A"
    assert rows[0]["serial"] == "SIM000004"
    assert rows[0]["channel"] == "2"
    assert rows[0]["programmed_voltage"] == "2.0"
    assert rows[0]["programmed_current"] == "0.1"
    assert rows[0]["measured_voltage"] == "2.02"
    assert rows[0]["measured_current"] == "0.202"
    assert rows[0]["output_enabled"] == "False"

def test_log_simulate_json_logs_scpi_to_stderr_only(tmp_path, capsys) -> None:
    csv_path = tmp_path / "edu-log.csv"

    assert (
        cli.main(
            [
                "log",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--channel",
                "2",
                "--interval-sec",
                "0.01",
                "--samples",
                "1",
                "--csv",
                str(csv_path),
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    json.loads(captured.out)
    assert captured.out.startswith("{")
    assert "SCPI" not in captured.out
    assert "USB0::SIM::EDU36311A::INSTR SCPI >> *IDN?" in captured.err
    assert "USB0::SIM::EDU36311A::INSTR SCPI >> MEAS:VOLT? (@2)" in captured.err

def test_log_simulate_all_channels_jsonl_and_append(tmp_path, capsys) -> None:
    csv_path = tmp_path / "edu-log.csv"
    jsonl_path = tmp_path / "edu-log.jsonl"

    args = [
        "log",
        "--simulate",
        "--json",
        "--resource",
        "USB0::SIM::EDU36311A::INSTR",
        "--channel",
        "all",
        "--interval-sec",
        "0.01",
        "--samples",
        "1",
        "--csv",
        str(csv_path),
        "--jsonl",
        str(jsonl_path),
    ]
    assert cli.main(args) == 0
    first_payload = json.loads(capsys.readouterr().out)
    assert first_payload["data"]["channels"] == [1, 2, 3]

    assert cli.main([*args, "--append"]) == 0
    json.loads(capsys.readouterr().out)

    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert len(rows) == 6
    assert [row["channel"] for row in rows[:3]] == ["1", "2", "3"]
    jsonl_lines = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert jsonl_lines[-1]["event"] == "summary"
    assert jsonl_lines[-1]["channels"] == [1, 2, 3]

def test_log_simulate_explicit_channels_and_duration_preserve_order(
    tmp_path, capsys, monkeypatch
) -> None:
    csv_path = tmp_path / "duration-log.csv"
    clock = iter((0.0, 0.0, 1.0))
    monkeypatch.setattr(readonly_commands.time, "monotonic", lambda: next(clock, 1.0))

    assert cli.main(
        [
            "log",
            "--simulate",
            "--json",
            "--resource",
            "USB0::SIM::E36312A::INSTR",
            "--channels",
            "3,1,3",
            "--interval-sec",
            "0.1",
            "--duration-sec",
            "0.5",
            "--csv",
            str(csv_path),
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert payload["data"]["samples_written"] == 1
    assert payload["data"]["channels"] == [3, 1, 3]
    assert [int(row["channel"]) for row in rows] == [3, 1, 3]

def test_log_unsupported_channel_does_not_create_artifacts(tmp_path, capsys) -> None:
    csv_path = tmp_path / "rejected.csv"
    jsonl_path = tmp_path / "rejected.jsonl"

    assert cli.main(
        [
            "log",
            "--simulate",
            "--json",
            "--resource",
            "USB0::SIM::EDU36311A::INSTR",
            "--channel",
            "4",
            "--interval-sec",
            "0.01",
            "--samples",
            "1",
            "--csv",
            str(csv_path),
            "--jsonl",
            str(jsonl_path),
        ]
    ) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "validation"
    assert not csv_path.exists()
    assert not jsonl_path.exists()

def test_log_live_support_rejection_does_not_create_artifacts(
    monkeypatch, tmp_path, capsys
) -> None:
    session = FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)
    csv_path = tmp_path / "rejected.csv"
    jsonl_path = tmp_path / "rejected.jsonl"

    assert cli.main(
        [
            "log",
            "--json",
            "--resource",
            "USB0::1::INSTR",
            "--channel",
            "all",
            "--interval-sec",
            "0.01",
            "--samples",
            "1",
            "--csv",
            str(csv_path),
            "--jsonl",
            str(jsonl_path),
        ]
    ) == 2

    assert_live_scope_rejected(json.loads(capsys.readouterr().out), session)
    assert not csv_path.exists()
    assert not jsonl_path.exists()

def test_log_sampling_failure_surfaces_connection_error(monkeypatch, tmp_path, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
        query_responses={
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.10",
            "SYST:ERR?": '0,"No error"',
            "MEAS:VOLT? (@2)": "2.02",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "log",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "2",
                "--interval-sec",
                "0.01",
                "--samples",
                "1",
                "--csv",
                str(tmp_path / "partial.csv"),
            ]
        )
        == 1
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "log_failed"

def test_promoted_log_keeps_interruptible_sampling_behavior(monkeypatch, tmp_path, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.10",
            "MEAS:VOLT? (@2)": "2.02",
            "MEAS:CURR? (@2)": "0.202",
            "OUTP? (@2)": "OFF",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    def interrupting_sleep(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(readonly_commands.time, "sleep", interrupting_sleep)

    assert (
        cli.main(
            [
                "log",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "2",
                "--interval-sec",
                "0.01",
                "--samples",
                "2",
                "--csv",
                str(tmp_path / "interrupted.csv"),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["stopped"] is True
    assert payload["data"]["stop_reason"] == "interrupted"
    assert payload["data"]["samples_written"] == 1
