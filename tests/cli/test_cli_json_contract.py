import json

import pytest

import powers_tool_cli.cli as cli


SIM_RESOURCE = "USB0::SIM::E36312A::INSTR"
SIM_E36312A_RESOURCE = "USB0::SIM::E36312A::INSTR"
REQUIRED_ENVELOPE_KEYS = {
    "schema_version",
    "ok",
    "status",
    "command",
    "execution",
    "request",
    "data",
    "warnings",
    "error",
    "metadata",
}


def parse_json_result(args: list[str], capsys) -> tuple[int, dict[str, object]]:
    exit_code = cli.main(args)
    captured = capsys.readouterr()
    return exit_code, json.loads(captured.out)


def assert_contract_envelope(payload: dict[str, object], *, command: str, ok: bool) -> None:
    assert REQUIRED_ENVELOPE_KEYS <= payload.keys()
    assert payload["schema_version"] == 2
    assert payload["ok"] is ok
    assert payload["status"] == ("ok" if ok else "error")
    assert isinstance(payload["command"], dict)
    assert {"name"} <= payload["command"].keys()
    assert payload["command"]["name"] == command
    assert isinstance(payload["execution"], dict)
    assert {"mode", "dry_run", "hardware_touched"} <= payload["execution"].keys()
    assert isinstance(payload["execution"]["mode"], str)
    assert isinstance(payload["execution"]["dry_run"], bool)
    assert isinstance(payload["execution"]["hardware_touched"], bool)
    assert isinstance(payload["request"], dict)
    assert payload["warnings"] == []
    assert isinstance(payload["metadata"], dict)
    assert {"duration_ms"} <= payload["metadata"].keys()
    assert isinstance(payload["metadata"]["duration_ms"], (int, float))
    assert not isinstance(payload["metadata"]["duration_ms"], bool)
    assert payload["metadata"]["duration_ms"] >= 0

    if ok:
        assert isinstance(payload["data"], dict)
        assert payload["error"] is None
    else:
        assert payload["data"] is None
        assert isinstance(payload["error"], dict)
        assert {"type", "code", "message", "retryable"} <= payload["error"].keys()
        assert isinstance(payload["error"]["type"], str)
        assert isinstance(payload["error"]["code"], str)
        assert isinstance(payload["error"]["message"], str)
        assert isinstance(payload["error"]["retryable"], bool)


@pytest.mark.parametrize(
    ("command", "args"),
    [
        (
            "clear",
            [
                "clear",
                "--dry-run",
                "--json",
                "--resource",
                SIM_RESOURCE,
            ],
        ),
        (
            "error",
            [
                "error",
                "--simulate",
                "--json",
                "--resource",
                SIM_RESOURCE,
            ],
        ),
        (
            "measure",
            [
                "measure",
                "--simulate",
                "--json",
                "--resource",
                SIM_RESOURCE,
                "--channel",
                "1",
            ],
        ),
        (
            "measure",
            [
                "measure",
                "--simulate",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
                "--channel",
                "2",
            ],
        ),
        (
            "measure-all",
            [
                "measure-all",
                "--simulate",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
            ],
        ),
        (
            "read-status",
            [
                "read-status",
                "--simulate",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
            ],
        ),
        (
            "validate-readonly",
            [
                "validate-readonly",
                "--simulate",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
            ],
        ),
        (
            "trigger-pulse",
            [
                "trigger-pulse",
                "--dry-run",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
                "--pin",
                "1",
            ],
        ),
        (
            "trigger-status",
            [
                "trigger-status",
                "--simulate",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
            ],
        ),
        (
            "trigger-step",
            [
                "trigger-step",
                "--dry-run",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
                "--channel",
                "1",
                "--source",
                "bus",
                "--leave-trigger-configured",
            ],
        ),
        (
            "trigger-list",
            [
                "trigger-list",
                "--dry-run",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
                "--channel",
                "1",
                "--voltage-list",
                "0,1",
                "--current-list",
                "0.05",
                "--dwell-list",
                "0.01",
                "--leave-trigger-configured",
            ],
        ),
        (
            "trigger-fire",
            [
                "trigger-fire",
                "--dry-run",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
            ],
        ),
        (
            "trigger-abort",
            [
                "trigger-abort",
                "--dry-run",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
                "--channel",
                "1",
            ],
        ),
        (
            "output-state",
            [
                "output-state",
                "--simulate",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
                "--channel",
                "2",
            ],
        ),
        (
            "cycle-output",
            [
                "cycle-output",
                "--dry-run",
                "--json",
                "--resource",
                SIM_RESOURCE,
                "--channel",
                "1",
                "--duration-ms",
                "250",
            ],
        ),
        (
            "apply",
            [
                "apply",
                "--dry-run",
                "--json",
                "--resource",
                SIM_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ],
        ),
        (
            "smoke-output",
            [
                "smoke-output",
                "--dry-run",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ],
        ),
        (
            "readback",
            [
                "readback",
                "--simulate",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
            ],
        ),
        (
            "protection-status",
            [
                "protection-status",
                "--simulate",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
            ],
        ),
        (
            "clear-protection",
            [
                "clear-protection",
                "--dry-run",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
                "--all",
            ],
        ),
        (
            "protection-set",
            [
                "protection-set",
                "--dry-run",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
                "--channel",
                "all",
                "--ovp-voltage",
                "5",
                "--ocp",
                "on",
            ],
        ),
        (
            "identify",
            [
                "identify",
                "--simulate",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
            ],
        ),
        (
            "snapshot",
            [
                "snapshot",
                "--simulate",
                "--json",
                "--resource",
                SIM_E36312A_RESOURCE,
            ],
        ),
        (
            "log",
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
                "{tmp_path}/contract-log.csv",
            ],
        ),
        (
            "sequence",
            [
                "sequence",
                "--dry-run",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
                "--file",
                "examples/sequence-readonly.yaml",
            ],
        ),
        (
            "doctor",
            [
                "doctor",
                "--simulate",
                "--json",
            ],
        ),
        (
            "capabilities",
            [
                "capabilities",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::EDU36311A::INSTR",
            ],
        ),
        (
            "safety inspect",
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
            ],
        ),
    ],
)
def test_safe_cli_json_commands_keep_contract(command, args, capsys, tmp_path) -> None:
    resolved_args = [
        item.replace("{tmp_path}", str(tmp_path)) if isinstance(item, str) else item
        for item in args
    ]
    exit_code, payload = parse_json_result(resolved_args, capsys)

    assert exit_code == 0
    assert_contract_envelope(payload, command=command, ok=True)
    assert payload["execution"]["hardware_touched"] is False


def test_measure_simulate_json_keeps_stdout_parseable_with_scpi_logs(capsys) -> None:
    exit_code = cli.main(
        [
            "measure",
            "--simulate",
            "--json",
            "--log-scpi",
            "--resource",
            SIM_E36312A_RESOURCE,
            "--channel",
            "2",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert_contract_envelope(payload, command="measure", ok=True)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["data"]["measurements"] == {"voltage": 2.2, "current": 0.22}
    assert "SCPI >> *IDN?" in captured.err
    assert "SCPI >> MEAS:VOLT? (@2)" in captured.err


def test_output_state_simulate_json_keeps_contract(capsys) -> None:
    exit_code, payload = parse_json_result(
        [
            "output-state",
            "--simulate",
            "--json",
            "--resource",
            SIM_E36312A_RESOURCE,
            "--channel",
            "2",
        ],
        capsys,
    )

    assert exit_code == 0
    assert_contract_envelope(payload, command="output-state", ok=True)
    assert payload["data"]["plan"]["operation"] == {"name": "output-state"}


def test_cycle_output_dry_run_json_keeps_contract(capsys) -> None:
    exit_code, payload = parse_json_result(
        [
            "cycle-output",
            "--dry-run",
            "--json",
            "--resource",
            SIM_RESOURCE,
            "--channel",
            "1",
            "--duration-ms",
            "250",
        ],
        capsys,
    )

    assert exit_code == 0
    assert_contract_envelope(payload, command="cycle-output", ok=True)
    assert payload["data"]["plan"]["steps"][1]["action"] == "sleep"


def test_apply_dry_run_json_keeps_contract(capsys) -> None:
    exit_code, payload = parse_json_result(
        [
            "apply",
            "--dry-run",
            "--json",
            "--resource",
            SIM_RESOURCE,
            "--channel",
            "1",
            "--voltage",
            "1",
            "--current",
            "0.05",
        ],
        capsys,
    )

    assert exit_code == 0
    assert_contract_envelope(payload, command="apply", ok=True)
    assert payload["data"]["plan"]["steps"][-1]["action"] == "output_on"


def test_output_dry_run_json_keeps_contract(capsys) -> None:
    exit_code, payload = parse_json_result(
        [
            "set",
            "--dry-run",
            "--json",
            "--resource",
            SIM_RESOURCE,
            "--channel",
            "1",
            "--voltage",
            "1",
            "--current",
            "0.05",
        ],
        capsys,
    )

    assert exit_code == 0
    assert_contract_envelope(payload, command="set", ok=True)
    assert payload["execution"]["mode"] == "real"
    assert payload["execution"]["dry_run"] is True
    assert payload["execution"]["hardware_touched"] is False
    assert payload["data"]["plan"]["steps"][0]["action"] == "set_current_limit"
    assert payload["data"]["plan"]["steps"][1]["action"] == "set_voltage"


def test_validation_error_json_keeps_contract_and_does_not_touch_visa(
    monkeypatch,
    capsys,
) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    exit_code, payload = parse_json_result(
        [
            "measure",
            "--json",
            "--resource",
            SIM_RESOURCE,
            "--channel",
            "0",
        ],
        capsys,
    )

    assert exit_code == 2
    assert_contract_envelope(payload, command="measure", ok=False)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"


def test_ramp_list_file_admission_failure_does_not_touch_hardware(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    ramp_file = tmp_path / "malformed.ramp-list.json"
    ramp_file.write_text("{", encoding="utf-8")
    opener_calls = []

    def fail_open_resource(*args, **kwargs):
        opener_calls.append((args, kwargs))
        raise AssertionError("VISA resource must not be opened for admission failure")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)

    exit_code, payload = parse_json_result(
        [
            "ramp-list",
            "--json",
            "--resource",
            "USB0::FAKE::E36312A::INSTR",
            "--file",
            str(ramp_file),
        ],
        capsys,
    )

    assert exit_code == 2
    assert_contract_envelope(payload, command="ramp-list", ok=False)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "could not parse ramp-list JSON" in payload["error"]["message"]
    assert opener_calls == []
