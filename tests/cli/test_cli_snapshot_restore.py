import json

import powers_tool_cli.cli as cli

from tests.cli.cli_test_helpers import (
    OUTPUT_RESOURCE,
    FakeSession,
)
def test_identify_real_reads_identity_queries(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "*OPT?": "0",
            "SYST:VERS?": "1999.0",
            "SYST:COMM:RLST?": "RWLock",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["identify", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "*OPT?", "SYST:VERS?", "SYST:COMM:RLST?"]
    assert payload["data"]["options"] == "0"
    assert payload["data"]["scpi_version"] == "1999.0"
    assert payload["data"]["remote_lockout_state"] == "RWLock"

def test_identify_edu36311a_real_reads_only_idn(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["identify", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?"]
    assert payload["data"]["idn"]["model"] == "EDU36311A"
    assert payload["data"]["options"] is None
    assert payload["data"]["scpi_version"] is None
    assert payload["data"]["remote_lockout_state"] is None

def test_identify_e3646a_real_reads_only_idn(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["identify", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?"]
    assert "*OPT?" not in session.queries
    assert "SYST:VERS?" not in session.queries
    assert "SYST:COMM:RLST?" not in session.queries
    assert payload["data"]["idn"]["model"] == "E3646A"
    assert payload["data"]["options"] is None
    assert payload["data"]["scpi_version"] is None
    assert payload["data"]["remote_lockout_state"] is None

def test_identify_expected_model_guard_remains_parser_visible(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "identify",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--model",
                "keysight-e3646a",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert session.queries == ["*IDN?"]

def test_identify_extended_query_failure_is_json_error(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["identify", "--json", "--resource", OUTPUT_RESOURCE]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?", "*OPT?"]
    assert payload["error"]["code"] == "identify_failed"
    assert "No fake response for '*OPT?'" in payload["error"]["message"]
    assert "Traceback" not in captured.err

def test_snapshot_real_reads_full_state(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "SYST:ERR?": '0,"No error"',
            "OUTP? (@1)": "OFF",
            "OUTP? (@2)": "OFF",
            "OUTP? (@3)": "ON",
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
            "VOLT? (@2)": "2.0",
            "CURR? (@2)": "0.10",
            "VOLT? (@3)": "3.0",
            "CURR? (@3)": "0.15",
            "MEAS:VOLT? (@1)": "1.1",
            "MEAS:CURR? (@1)": "0.11",
            "MEAS:VOLT? (@2)": "2.2",
            "MEAS:CURR? (@2)": "0.22",
            "MEAS:VOLT? (@3)": "3.3",
            "MEAS:CURR? (@3)": "0.33",
            "VOLT:PROT:TRIP? (@1)": "0",
            "CURR:PROT:TRIP? (@1)": "0",
            "VOLT:PROT:TRIP? (@2)": "0",
            "CURR:PROT:TRIP? (@2)": "0",
            "VOLT:PROT:TRIP? (@3)": "0",
            "CURR:PROT:TRIP? (@3)": "0",
            "VOLT:PROT? (@1)": "5.0",
            "CURR:PROT:STAT? (@1)": "1",
            "CURR:PROT:DEL? (@1)": "0.1",
            "CURR:PROT:DEL:STAR? (@1)": "SCH",
            "VOLT:PROT? (@2)": "6.0",
            "CURR:PROT:STAT? (@2)": "0",
            "CURR:PROT:DEL? (@2)": "0.2",
            "CURR:PROT:DEL:STAR? (@2)": "CCTR",
            "VOLT:PROT? (@3)": "7.0",
            "CURR:PROT:STAT? (@3)": "1",
            "CURR:PROT:DEL? (@3)": "0.3",
            "CURR:PROT:DEL:STAR? (@3)": "SCHange",
        },
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["snapshot", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert session.queries[0:2] == ["*IDN?", "SYST:ERR?"]
    assert payload["data"]["read_count"] == 1
    assert payload["data"]["schema_version"] == 2
    assert payload["data"]["kind"] == "powers-tool-snapshot"
    assert payload["data"]["reported_identity"]["model"] == "E36312A"
    assert payload["data"]["resolved_identity"]["model_id"] == "keysight-e36312a"
    assert payload["data"]["outputs"][2] == {"channel": 3, "enabled": True}
    assert payload["data"]["readback"][1] == {
        "channel": 2,
        "setpoints": {"voltage": 2.0, "current": 0.1},
    }
    assert payload["data"]["measurements"][0] == {
        "channel": 1,
        "measurements": {"voltage": 1.1, "current": 0.11},
    }
    assert payload["data"]["protection"] == {
        "over_voltage_tripped": False,
        "over_current_tripped": False,
    }
    assert payload["data"]["protection_settings"][1] == {
        "channel": 2,
        "protection": {
            "ovp_voltage": 6.0,
            "ocp_enabled": False,
            "ocp_delay": 0.2,
            "ocp_delay_trigger": "cc-transition",
        },
    }

def test_snapshot_human_output_uses_schema_2_identity(capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"

    assert cli.main(["snapshot", "--simulate", "--resource", resource]) == 0

    output = capsys.readouterr().out
    assert "Model: Keysight E36312A" in output
    assert "Reported manufacturer: KEYSIGHT" in output
    assert "Reported model: E36312A" in output
    assert "Serial: SIM000003" in output

def test_snapshot_json_writes_raw_document_and_envelope_separately(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"
    raw_path = tmp_path / "snapshot.json"
    envelope_path = tmp_path / "envelope.json"

    assert cli.main([
        "snapshot", "--simulate", "--resource", resource, "--json",
        "--save-json", str(envelope_path), "--snapshot-json", str(raw_path),
    ]) == 0

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 2
    assert raw["kind"] == "powers-tool-snapshot"
    assert "ok" not in raw
    assert envelope["schema_version"] == 2
    assert envelope["data"] == raw
    assert json.loads(capsys.readouterr().out) == envelope

def test_snapshot_json_round_trips_to_restore_dry_run(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"
    raw_path = tmp_path / "snapshot.json"

    assert cli.main(["snapshot", "--simulate", "--resource", resource, "--snapshot-json", str(raw_path)]) == 0
    capsys.readouterr()
    assert cli.main([
        "restore-from-snapshot", "--dry-run", "--snapshot", str(raw_path),
        "--resource", resource, "--channel", "all", "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["target"]["channels"] == [1, 2, 3]

def test_restore_rejects_cli_snapshot_envelope(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"
    envelope_path = tmp_path / "envelope.json"

    assert cli.main([
        "snapshot", "--simulate", "--resource", resource,
        "--json", "--save-json", str(envelope_path),
    ]) == 0
    capsys.readouterr()
    assert cli.main([
        "restore-from-snapshot", "--dry-run", "--snapshot", str(envelope_path),
        "--resource", resource, "--channel", "all", "--json",
    ]) == 2

    assert "snapshot kind" in json.loads(capsys.readouterr().out)["error"]["message"]

def test_snapshot_json_write_failure_is_reported(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"
    invalid_parent = tmp_path / "not-a-directory"
    invalid_parent.write_text("occupied", encoding="utf-8")

    assert cli.main([
        "snapshot", "--simulate", "--resource", resource, "--json",
        "--snapshot-json", str(invalid_parent / "snapshot.json"),
    ]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "snapshot_write_failed"

def test_snapshot_rejects_same_raw_and_envelope_path_before_open(tmp_path, monkeypatch, capsys) -> None:
    output_path = tmp_path / "snapshot.json"
    opened = False

    def forbidden_opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("opener must not be called")

    monkeypatch.setattr(cli, "open_resource", forbidden_opener)
    assert cli.main([
        "snapshot", "--json", "--resource", OUTPUT_RESOURCE,
        "--save-json", str(output_path), "--snapshot-json", str(output_path),
    ]) == 2
    assert opened is False
    assert "must use different paths" in json.loads(capsys.readouterr().out)["error"]["message"]

def test_snapshot_compare_accepts_raw_baseline(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource]) == 0
    baseline = json.loads(capsys.readouterr().out)["data"]
    baseline_path = tmp_path / "snapshot-raw.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource, "--compare", str(baseline_path)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["comparison"]["passed"] is True
    assert payload["data"]["comparison"]["differences"] == []

def test_snapshot_compare_accepts_envelope_and_exits_3_on_mismatch(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource]) == 0
    envelope = json.loads(capsys.readouterr().out)
    envelope["data"]["reported_identity"]["serial"] = "DIFFERENT"
    baseline_path = tmp_path / "snapshot-envelope.json"
    baseline_path.write_text(json.dumps(envelope), encoding="utf-8")

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource, "--compare", str(baseline_path)]) == 3

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["comparison"]["passed"] is False
    assert payload["data"]["comparison"]["differences"][0]["path"] == "reported_identity"

def test_snapshot_compare_tolerance_override_allows_measurement_delta(tmp_path, capsys) -> None:
    resource = "USB0::SIM::E36312A::INSTR"

    assert cli.main(["snapshot", "--simulate", "--json", "--resource", resource]) == 0
    baseline = json.loads(capsys.readouterr().out)["data"]
    baseline["measurements"][0]["measurements"]["voltage"] += 0.5
    baseline_path = tmp_path / "snapshot-tolerance.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    assert (
        cli.main(
            [
                "snapshot",
                "--simulate",
                "--json",
                "--resource",
                resource,
                "--compare",
                str(baseline_path),
                "--measured-voltage-tolerance",
                "0.6",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["comparison"]["passed"] is True
