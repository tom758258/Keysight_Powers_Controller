import json

import pytest

import powers_tool_cli.cli as cli
import powers_tool_cli.cli_runtime as cli_runtime
import powers_tool_cli.commands.inspection as inspection

from tests.cli.cli_test_helpers import (
    OUTPUT_RESOURCE,
    FakeSession,
    assert_live_scope_rejected,
)


def test_offline_model_capabilities_uses_core_metadata_without_hardware(
    monkeypatch,
    capsys,
) -> None:
    def fail_hardware(*args, **kwargs):
        raise AssertionError("offline model capabilities must not touch hardware")

    monkeypatch.setattr(inspection, "_resource_manager_for_args", fail_hardware)
    monkeypatch.setattr(inspection, "_list_resources", fail_hardware)
    monkeypatch.setattr(inspection, "_open_resource", fail_hardware)
    monkeypatch.setattr(inspection, "_patchable_select_driver", fail_hardware)

    assert (
        cli.main(
            [
                "capabilities",
                "--model",
                "keysight-e36312a",
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    data = payload["data"]
    assert payload["schema_version"] == 2
    assert payload["ok"] is True
    assert payload["command"] == {"name": "capabilities"}
    assert payload["execution"]["hardware_touched"] is False
    assert payload["request"]["model"] == "keysight-e36312a"
    assert data["model_id"] == "keysight-e36312a"
    assert data["model_name"] == "E36312A"
    assert data["driver"] == {"class": "E36312APowerSupply"}
    assert data["channels"] == [1, 2, 3]
    assert data["measure_channels"] == {"simulate": [1, 2, 3], "real": [1, 2, 3]}
    assert data["hardware_validation"]["read_only"] == "validated"
    assert data["command_support"]["capabilities"]["real"] is True
    assert data["electrical_ratings"]["model"] == "E36312A"
    assert "resource" not in data
    assert "reason" not in data["driver"]


@pytest.mark.parametrize("model_id", ["not-a-model", "keysight-e36313a"])
def test_offline_model_capabilities_rejects_invalid_targets(model_id, capsys) -> None:
    assert cli.main(["capabilities", "--model", model_id, "--json"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert payload["request"]["model"] == model_id
    assert payload["execution"]["hardware_touched"] is False


def test_capabilities_model_and_resource_are_mutually_exclusive(capsys) -> None:
    assert (
        cli.main(
            [
                "capabilities",
                "--model",
                "keysight-e36312a",
                "--resource",
                OUTPUT_RESOURCE,
                "--json",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert payload["request"]["model"] == "keysight-e36312a"


def test_e3646a_cli_capabilities_reports_validated_output(capsys) -> None:
    assert (
        cli.main(
            [
                "capabilities",
                "--simulate",
                "--json",
                "--resource",
                "ASRL1::SIM::E3646A::INSTR",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    support = payload["data"]["command_support"]

    validated_commands = (
        "set",
        "output-off",
        "safe-off",
        "ramp",
        "ramp-list",
        "sequence",
    )
    for command in validated_commands:
        assert support[command]["real"] is True
        assert support[command]["hardware_validation"] == "validated"

    conditional_commands = ("apply", "output-on", "cycle-output", "smoke-output")
    for command in conditional_commands:
        assert support[command]["real"] is True
        assert support[command]["hardware_validation"] == "validated_confirm_threshold_conditional"

    disabled_commands = (
        "protection-status",
        "protection-set",
        "clear-protection",
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    )
    for command in disabled_commands:
        assert support[command]["real"] is False
        if command.startswith("trigger-"):
            assert support[command]["simulate"] is False
            assert support[command]["dry_run"] is False

def test_doctor_capabilities_and_safety_inspect_json(capsys) -> None:
    assert cli.main(["doctor", "--simulate", "--json"]) == 0
    doctor_payload = json.loads(capsys.readouterr().out)
    assert doctor_payload["data"]["simulator"]["available"] is True

    assert (
        cli.main(
            [
                "capabilities",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
            ]
        )
        == 0
    )
    capabilities_payload = json.loads(capsys.readouterr().out)
    assert capabilities_payload["data"]["driver"]["class"] == "EDU36311APowerSupply"
    assert capabilities_payload["data"]["channels"] == [1, 2, 3]

    assert (
        cli.main(
            [
                "safety",
                "inspect",
                "--json",
                "--safety-config",
                "examples/safety-config.toml",
                "--resource-alias",
                "sim-e36312a",
                "--channel",
                "1",
            ]
        )
        == 0
    )
    safety_payload = json.loads(capsys.readouterr().out)
    assert safety_payload["command"] == {"name": "safety inspect"}
    assert safety_payload["data"]["limits"]["max_voltage"] == 3.3

def test_resource_backed_capabilities_uses_exact_live_scope(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["capabilities", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["driver"]["class"] == "E36312APowerSupply"
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True

def test_resource_backed_capabilities_rejects_pyvisa_py_pending_scope(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "capabilities",
                "--json",
                "--resource",
                "TCPIP0::192.0.2.1::INSTR",
                "--backend",
                "@py",
            ]
        )
        == 2
    )

    assert_live_scope_rejected(json.loads(capsys.readouterr().out), session)

def test_resource_backed_doctor_is_not_a_live_policy_exemption(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "_list_resources", lambda *args, **kwargs: ())
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["doctor", "--json", "--resource", OUTPUT_RESOURCE]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["resource"]["model_id"] == "keysight-e36312a"
