import json
from types import SimpleNamespace

import pytest

import powers_tool_core.connection as connection
import powers_tool_cli.cli as cli
import powers_tool_cli.cli_runtime as cli_runtime
import powers_tool_cli.commands.output_run as output_run
from powers_tool_core.errors import VisaConnectionError

from tests.cli.cli_test_helpers import (
    OUTPUT_RESOURCE,
    SERIAL_TERMINATION_ARGS,
    WRITE_VERIFICATION_REQUEST_DEFAULTS,
    FakeSession,
    assert_live_scope_rejected,
    expected_resource,
    output_command_args,
    write_safety_config,
    _assert_invalid_output_state_core_result,
    _output_state_core_result,
    _run_output_state_core_result,
)
@pytest.mark.parametrize(
    ("args", "expected_actions"),
    [
        (output_command_args("set"), ["set_current_limit", "set_voltage"]),
        (output_command_args("output-on"), ["output_on"]),
        (output_command_args("output-off"), ["output_off"]),
        (output_command_args("safe-off"), ["safe_off"]),
        (output_command_args("output-state"), ["output_state"]),
        (
            output_command_args("cycle-output", duration_ms="250"),
            ["output_on", "sleep", "output_off"],
        ),
        (output_command_args("apply"), ["set_current_limit", "set_voltage", "output_on"]),
    ],
)
def test_output_commands_dry_run_json_emit_logical_plans(
    args,
    expected_actions,
    capsys,
) -> None:
    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 2
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": True,
        "hardware_touched": False,
    }
    assert payload["request"]["safety_config"] is None
    assert payload["request"]["resource_alias"] is None
    assert payload["data"]["plan"]["operation"] == {"name": args[0]}
    assert payload["data"]["plan"]["target"] == {
        "resource": OUTPUT_RESOURCE,
        "planning_model_id": "keysight-e36312a",
        "planning_profile_id": None,
        "channel": 1,
    }
    assert payload["data"]["plan"]["hardware_touched"] is False
    steps = payload["data"]["plan"]["steps"]
    assert [step["action"] for step in steps] == expected_actions
    assert all(step["type"] == "driver_action" for step in steps)
    assert all("command" not in step for step in steps)
    assert captured.err == ""

def test_dry_run_without_model_or_sim_resource_fails(capsys) -> None:
    assert cli.main(["output-on", "--dry-run", "--json", "--channel", "1"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "require planning_model_id" in payload["error"]["message"]

def test_simulate_model_derives_resource_and_rejects_mismatch(capsys) -> None:
    assert cli.main(["output-on", "--simulate", "--json", "--model", "keysight-e36312a", "--channel", "1"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["plan"]["target"]["planning_model_id"] == "keysight-e36312a"
    assert payload["data"]["plan"]["target"]["resource"] == "USB0::SIM::E36312A::INSTR"

    assert (
        cli.main(
            [
                "output-on",
                "--simulate",
                "--json",
                "--model",
                "keysight-e3646a",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "1",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert "does not match" in payload["error"]["message"]

def test_apply_simulate_rejects_explicit_non_sim_resource_before_hardware_io(monkeypatch, capsys) -> None:
    def fail_open(*args, **kwargs):
        raise AssertionError("must not open VISA")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open)

    assert (
        cli.main(
            [
                "apply",
                "--simulate",
                "--json",
                "--model",
                "keysight-e3646a",
                "--resource",
                "ASRL7::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "requires a deterministic SIM resource" in payload["error"]["message"]

def test_live_generic_expected_model_fails_before_hardware_io(monkeypatch, capsys) -> None:
    def fail_open(*args, **kwargs):
        raise AssertionError("must not open VISA")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--model",
                "GENERIC",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "1",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert "invalid expected_model_id" in payload["error"]["message"]

def test_invalid_model_fails_as_argument_error(capsys) -> None:
    assert cli.main(["output-on", "--dry-run", "--json", "--model", "not-a-model", "--channel", "1"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "invalid planning_model_id" in payload["error"]["message"]

def test_cycle_output_dry_run_json_includes_duration(capsys) -> None:
    args = output_command_args("cycle-output", duration_ms="250")

    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["duration_ms"] == 250
    assert payload["data"]["plan"]["steps"][1] == {
        "index": 2,
        "type": "driver_action",
        "action": "sleep",
        "parameters": {"duration_ms": 250},
    }

def test_apply_dry_run_json_includes_setpoints_and_output_on(capsys) -> None:
    args = output_command_args("apply", voltage="1", current="0.05")

    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["voltage"] == 1.0
    assert payload["request"]["current"] == 0.05
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == [
        "set_current_limit",
        "set_voltage",
        "output_on",
    ]

def test_apply_all_no_output_dry_run_sets_each_channel_without_output(capsys) -> None:
    assert (
        cli.main(
            [
                "apply",
                "--dry-run",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "all",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--no-output",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    steps = payload["data"]["plan"]["steps"]
    assert [(step["action"], step["parameters"]["channel"]) for step in steps] == [
        ("set_current_limit", 1),
        ("set_voltage", 1),
        ("set_current_limit", 2),
        ("set_voltage", 2),
        ("set_current_limit", 3),
        ("set_voltage", 3),
    ]
    assert all(step["action"] != "output_on" for step in steps)

def test_smoke_output_dry_run_json_emits_guarded_plan(capsys) -> None:
    assert (
        cli.main(
            [
                "smoke-output",
                "--dry-run",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": True,
        "hardware_touched": False,
    }
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == [
        "set_current_limit",
        "set_voltage",
        "output_on",
        "sleep",
        "measure_voltage",
        "measure_current",
        "output_off",
        "output_state",
    ]

def test_smoke_output_simulate_json_does_not_create_real_resource_manager(
    monkeypatch,
    capsys,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert (
        cli.main(
            [
                "smoke-output",
                "--simulate",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["mode"] == "simulate"
    assert payload["execution"]["hardware_touched"] is False
    assert payload["data"]["plan"]["operation"] == {"name": "smoke-output"}

def test_set_dry_run_json_applies_explicit_safety_config(tmp_path, capsys) -> None:
    safety_config = write_safety_config(tmp_path)

    assert (
        cli.main(
            [
                *output_command_args("set"),
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": None,
        "channel": 1,
        "voltage": 1.0,
        "current": 0.05,
        "safety_config": safety_config,
        "backend": None,
        "timeout_ms": 5000,
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
    }
    assert payload["data"]["plan"]["steps"][0]["action"] == "set_current_limit"
    assert payload["data"]["plan"]["steps"][1]["action"] == "set_voltage"
    assert captured.err == ""

@pytest.mark.parametrize(
    ("args", "expected_message"),
    [
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "5.1",
                "--current",
                "0.05",
            ],
            "voltage 5.1 exceeds maximum 5",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.6",
            ],
            "current 0.6 exceeds maximum 0.5",
        ),
    ],
)
def test_set_safety_config_limit_failures_use_json_validation_errors(
    tmp_path,
    args,
    expected_message,
    capsys,
) -> None:
    safety_config = write_safety_config(tmp_path)

    assert cli.main([*args, "--dry-run", "--json", "--safety-config", safety_config]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["execution"]["hardware_touched"] is False
    assert payload["request"]["safety_config"] == safety_config
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert payload["error"]["retryable"] is False
    assert expected_message in payload["error"]["message"]
    assert captured.err == ""

@pytest.mark.parametrize(
    "args",
    [
        output_command_args("set", channel="2"),
        output_command_args("output-on", channel="2"),
        output_command_args("output-off", channel="2"),
    ],
)
def test_safety_config_rejects_disallowed_integer_channels(
    tmp_path,
    args,
    capsys,
) -> None:
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
allowed_channels = [1]
""".strip(),
    )

    assert cli.main([*args, "--dry-run", "--json", "--safety-config", safety_config]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 2 is not allowed" in payload["error"]["message"]
    assert captured.err == ""

def test_safe_off_all_with_safety_config_is_allowed(tmp_path, capsys) -> None:
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "safe-off",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": None,
        "channel": "all",
        "safety_config": safety_config,
    }
    assert payload["data"]["plan"]["target"]["channel"] == "all"
    assert payload["data"]["plan"]["steps"][0]["parameters"]["channel"] == 1
    assert captured.err == ""

def test_output_plan_resource_alias_resolves_effective_resource_and_limits(
    tmp_path,
    capsys,
) -> None:
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2]

[[resources]]
alias = "sim-e36312a"
resource = "{OUTPUT_RESOURCE}"
max_voltage = 3.3
max_current = 0.1
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--resource-alias",
                "sim-e36312a",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": "sim-e36312a",
        "channel": 1,
        "voltage": 1.0,
        "current": 0.05,
        "safety_config": safety_config,
        "backend": None,
        "timeout_ms": 5000,
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
    }
    assert payload["data"]["plan"]["target"]["resource"] == OUTPUT_RESOURCE
    assert captured.err == ""

def test_raw_resource_match_applies_resource_specific_limits(tmp_path, capsys) -> None:
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1, 2]

[[resources]]
alias = "sim-e36312a"
resource = "{OUTPUT_RESOURCE}"
max_voltage = 0.5
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["resource"] == OUTPUT_RESOURCE
    assert payload["request"]["resource_alias"] is None
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "voltage 1 exceeds maximum 0.5" in payload["error"]["message"]
    assert captured.err == ""

def test_resource_alias_requires_explicit_safety_config(capsys) -> None:
    assert (
        cli.main(
            [
                "set",
                "--resource-alias",
                "sim-e36312a",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--dry-run",
                "--json",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["resource"] is None
    assert payload["request"]["resource_alias"] == "sim-e36312a"
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "resource alias requires --safety-config" in payload["error"]["message"]
    assert captured.err == ""

def test_unknown_resource_alias_uses_json_validation_error(tmp_path, capsys) -> None:
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
max_voltage = 5.0

[[resources]]
alias = "sim-e36312a"
resource = "{OUTPUT_RESOURCE}"
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--resource-alias",
                "missing",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--dry-run",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["resource"] is None
    assert payload["request"]["resource_alias"] == "missing"
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "unknown resource alias: missing" in payload["error"]["message"]
    assert captured.err == ""

def test_real_set_with_alias_without_dry_run_executes_after_validation(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
max_voltage = 5.0
max_current = 0.5
allowed_channels = [1]

[[resources]]
alias = "sim-e36312a"
resource = "{OUTPUT_RESOURCE}"
max_current = 0.1
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--resource-alias",
                "sim-e36312a",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["resource"] == OUTPUT_RESOURCE
    assert payload["request"]["resource_alias"] == "sim-e36312a"
    assert payload["execution"]["hardware_touched"] is True
    assert session.writes == ["CURR 0.05,(@1)", "VOLT 1,(@1)"]
    assert captured.err == ""

def test_simulate_output_with_safety_config_does_not_create_real_resource_manager(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)
    safety_config = write_safety_config(tmp_path)

    assert (
        cli.main(
            [
                *output_command_args("set"),
                "--simulate",
                "--json",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["request"]["safety_config"] == safety_config
    assert captured.err == ""

def test_real_set_with_safety_config_without_dry_run_executes(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)
    safety_config = write_safety_config(tmp_path)

    assert cli.main([*output_command_args("set"), "--json", "--safety-config", safety_config]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": True,
    }
    assert payload["request"]["safety_config"] == safety_config
    assert payload["data"]["setpoints"] == {"current": 0.05, "voltage": 1.0}
    assert session.writes == ["CURR 0.05,(@1)", "VOLT 1,(@1)"]
    assert captured.err == ""

@pytest.mark.parametrize(
    ("config_content", "args", "expected_message"),
    [
        (
            "[safety]\nunknown = 1\n",
            [*output_command_args("set"), "--dry-run"],
            "unsupported [safety] key: unknown",
        ),
        (
            "[safety]\nmax_voltage = 0.5\n",
            [*output_command_args("set"), "--dry-run"],
            "voltage 1 exceeds maximum 0.5",
        ),
    ],
)
def test_safety_config_text_errors_go_to_stderr(
    tmp_path,
    config_content,
    args,
    expected_message,
    capsys,
) -> None:
    safety_config = write_safety_config(tmp_path, config_content)

    assert cli.main([*args, "--safety-config", safety_config]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert expected_message in captured.err

def test_missing_safety_config_path_uses_json_validation_error(capsys) -> None:
    missing_path = "does-not-exist.toml"

    assert (
        cli.main(
            [
                *output_command_args("set"),
                "--dry-run",
                "--json",
                "--safety-config",
                missing_path,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["request"]["safety_config"] == missing_path
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "safety config not found" in payload["error"]["message"]
    assert captured.err == ""

@pytest.mark.parametrize(
    ("args", "expected_lines"),
    [
        (
            output_command_args("set"),
            [
                "Dry-run plan for set",
                "1. set_current_limit channel=1 current=0.05",
                "2. set_voltage channel=1 voltage=1",
            ],
        ),
        (
            output_command_args("output-on"),
            ["Dry-run plan for output-on", "1. output_on channel=1"],
        ),
        (
            output_command_args("output-off"),
            ["Dry-run plan for output-off", "1. output_off channel=1"],
        ),
        (
            output_command_args("safe-off"),
            ["Dry-run plan for safe-off", "1. safe_off channel=1"],
        ),
    ],
)
def test_output_commands_text_dry_run_output(args, expected_lines, capsys) -> None:
    assert cli.main([*args, "--dry-run"]) == 0

    captured = capsys.readouterr()
    for line in expected_lines:
        assert line in captured.out
    assert f"Resource: {OUTPUT_RESOURCE}" in captured.out
    assert "Hardware touched: false" in captured.out
    assert captured.err == ""

@pytest.mark.parametrize(
    "args",
    [
        output_command_args("safe-off"),
    ],
)
def test_real_output_commands_without_dry_run_are_rejected_before_visa(
    monkeypatch,
    capsys,
    args,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)
    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["command"] == {"name": args[0]}
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": True,
        "hardware_touched": False,
    }
    assert payload["data"]["plan"]["target"]["channel"] == 1
    assert captured.err == ""

@pytest.mark.parametrize("channel", ["1", "2", "3"])
def test_output_state_real_e36312a_reads_channel_state(monkeypatch, capsys, channel) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={f"OUTP? (@{channel})": "ON"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-state",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                channel,
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?", f"OUTP? (@{channel})"]
    assert session.writes == []
    assert payload["data"]["channel"] == int(channel)
    assert payload["data"]["output_enabled"] is True
    assert "output" not in payload["data"]
    assert "outputs" not in payload["data"]
    assert f"USB0::SIM::E36312A::INSTR SCPI >> OUTP? (@{channel})" in captured.err

def test_output_state_real_e36312a_all_uses_canonical_outputs(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"OUTP? (@1)": "ON", "OUTP? (@2)": "OFF", "OUTP? (@3)": "ON"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(["output-state", "--json", "--resource", OUTPUT_RESOURCE, "--channel", "all"]) == 0

    data = json.loads(capsys.readouterr().out)["data"]
    assert data["channel"] == "all"
    assert data["outputs"] == [
        {"channel": 1, "enabled": True},
        {"channel": 2, "enabled": False},
        {"channel": 3, "enabled": True},
    ]
    assert "output" not in data
    assert "output_enabled" not in data

@pytest.mark.parametrize("enabled", [True, False])
def test_output_state_core_result_accepts_exact_single_boolean(
    monkeypatch, capsys, enabled
) -> None:
    exit_code, payload, stderr = _run_output_state_core_result(
        monkeypatch,
        capsys,
        _output_state_core_result(output_enabled=enabled),
    )

    assert exit_code == 0
    assert payload["data"]["channel"] == 1
    assert payload["data"]["output_enabled"] is enabled
    assert "output" not in payload["data"]
    assert "outputs" not in payload["data"]
    assert stderr == ""

def test_output_state_core_result_accepts_complete_all_records(monkeypatch, capsys) -> None:
    data = _output_state_core_result(
        channel="all",
        output_enabled=None,
        outputs=[
            {"channel": 3.0, "enabled": True},
            {"channel": 1, "enabled": False},
            {"channel": 2, "enabled": True},
        ],
    )

    exit_code, payload, stderr = _run_output_state_core_result(
        monkeypatch, capsys, data, channel="all"
    )

    assert exit_code == 0
    assert payload["data"]["channel"] == "all"
    assert payload["data"]["outputs"] == [
        {"channel": 1, "enabled": False},
        {"channel": 2, "enabled": True},
        {"channel": 3, "enabled": True},
    ]
    assert "output" not in payload["data"]
    assert "output_enabled" not in payload["data"]
    assert stderr == ""

@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {},
        {"idn": None},
        {"idn": "KEYSIGHT,E36312A,SERIAL0000,1.0"},
        {"idn": {}},
        {"idn": {"raw": None}},
        {"idn": {"raw": 123}},
        {"idn": {"raw": ""}},
        {"idn": {"raw": "not-an-idn"}},
        {"idn": {"raw": "KEYSIGHT,UNKNOWN,SERIAL0000,1.0"}},
    ],
)
def test_output_state_core_result_rejects_invalid_observed_identity(
    monkeypatch, capsys, data
) -> None:
    _assert_invalid_output_state_core_result(monkeypatch, capsys, data)

@pytest.mark.parametrize(
    "data",
    [
        _output_state_core_result(output_enabled=None),
        _output_state_core_result(output_enabled="false"),
        _output_state_core_result(output_enabled=0),
        _output_state_core_result(output_enabled=1),
        {**_output_state_core_result(output_enabled=None), "output_enabled": None},
        _output_state_core_result(
            output_enabled=False,
            outputs=[{"channel": 1, "enabled": False}],
        ),
    ],
)
def test_output_state_core_result_rejects_malformed_single_data(
    monkeypatch, capsys, data
) -> None:
    _assert_invalid_output_state_core_result(monkeypatch, capsys, data)

@pytest.mark.parametrize(
    "outputs",
    [
        None,
        [],
        1,
        "bad",
        {"channel": 1, "enabled": False},
        [None],
        ["bad"],
        [{"enabled": False}],
        [{"channel": 1}],
        [{"channel": 1, "enabled": False, "extra": "bad"}],
        [{"channel": 1, "enabled": "false"}],
        [{"channel": 1, "enabled": 0}],
        [{"channel": 1, "enabled": 1}],
        [{"channel": 1, "enabled": None}],
        [{"channel": "1", "enabled": False}],
        [{"channel": True, "enabled": False}],
        [{"channel": 1.5, "enabled": False}],
        [{"channel": float("nan"), "enabled": False}],
        [{"channel": float("inf"), "enabled": False}],
        [{"channel": 0, "enabled": False}],
        [{"channel": -1, "enabled": False}],
        [
            {"channel": 1, "enabled": False},
            {"channel": 1, "enabled": False},
            {"channel": 2, "enabled": False},
            {"channel": 3, "enabled": False},
        ],
        [
            {"channel": 1, "enabled": False},
            {"channel": 2, "enabled": False},
            {"channel": 4, "enabled": False},
        ],
        [
            {"channel": 1, "enabled": False},
            {"channel": 2, "enabled": False},
        ],
    ],
)
def test_output_state_core_result_rejects_malformed_all_records(
    monkeypatch, capsys, outputs
) -> None:
    data = _output_state_core_result(
        channel="all", output_enabled=None, outputs=outputs
    )
    if outputs is None:
        data["outputs"] = None
    _assert_invalid_output_state_core_result(
        monkeypatch, capsys, data, channel="all"
    )

def test_output_state_core_result_rejects_all_with_top_level_output_enabled(
    monkeypatch, capsys
) -> None:
    data = _output_state_core_result(
        channel="all",
        output_enabled=False,
        outputs=[
            {"channel": 1, "enabled": False},
            {"channel": 2, "enabled": False},
            {"channel": 3, "enabled": False},
        ],
    )

    _assert_invalid_output_state_core_result(
        monkeypatch, capsys, data, channel="all"
    )

@pytest.mark.parametrize(
    "capabilities",
    [
        SimpleNamespace(),
        SimpleNamespace(real_measure_channels=None),
        SimpleNamespace(real_measure_channels=()),
        SimpleNamespace(real_measure_channels=[1, 2, 3]),
        SimpleNamespace(real_measure_channels=(1, 1, 2)),
        SimpleNamespace(real_measure_channels=(True, 2, 3)),
        SimpleNamespace(real_measure_channels=("1", 2, 3)),
        SimpleNamespace(real_measure_channels=(1.0, 2, 3)),
        SimpleNamespace(real_measure_channels=(0, 2, 3)),
        SimpleNamespace(real_measure_channels=(-1, 2, 3)),
    ],
)
def test_output_state_core_result_rejects_invalid_detected_channels(
    monkeypatch, capsys, capabilities
) -> None:
    selection = SimpleNamespace(
        physical_identity=SimpleNamespace(model_id="keysight-e36312a"),
        reason="model_specific_driver",
        capabilities=capabilities,
    )
    monkeypatch.setattr(cli_runtime, "select_driver", lambda idn_raw: selection)
    data = _output_state_core_result(
        channel="all",
        output_enabled=None,
        outputs=[
            {"channel": 1, "enabled": False},
            {"channel": 2, "enabled": False},
            {"channel": 3, "enabled": False},
        ],
    )

    _assert_invalid_output_state_core_result(
        monkeypatch, capsys, data, channel="all"
    )

def test_safe_off_real_e36312a_expands_all_channels(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            "OUTP? (@1)": "0",
            "OUTP? (@2)": "0",
            "OUTP? (@3)": "0",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "safe-off",
                "--json",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "all",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?", "OUTP? (@1)", "OUTP? (@2)", "OUTP? (@3)", "SYST:ERR?"]
    assert session.writes == ["OUTP OFF,(@1)", "OUTP OFF,(@2)", "OUTP OFF,(@3)"]
    assert session.events == [
        "query:*IDN?",
        "write:OUTP OFF,(@1)",
        "query:OUTP? (@1)",
        "write:OUTP OFF,(@2)",
        "query:OUTP? (@2)",
        "write:OUTP OFF,(@3)",
        "query:OUTP? (@3)",
        "query:SYST:ERR?",
    ]
    assert payload["data"]["outputs"] == [
        {"channel": 1, "enabled": False},
        {"channel": 2, "enabled": False},
        {"channel": 3, "enabled": False},
    ]
    assert captured.err == ""

def test_cycle_output_real_e36312a_cycles_output_without_delay(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@2)": "1.0", "CURR? (@2)": "0.1"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)
    monkeypatch.setattr(output_run.time, "sleep", lambda seconds: None)

    assert (
        cli.main(
            [
                "cycle-output",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "2",
                "--duration-ms",
                "250",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == ["OUTP ON,(@2)", "OUTP OFF,(@2)"]
    assert payload["data"]["duration_ms"] == 250
    assert payload["data"]["output"] == {"cycled": True, "final_enabled": False}
    assert captured.err == ""

def test_apply_real_e36312a_sets_then_enables_output(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "3",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == ["CURR 0.05,(@3)", "VOLT 1,(@3)", "OUTP ON,(@3)"]
    assert payload["data"]["output"] == {"enabled": True}
    assert captured.err == ""

def test_apply_real_e36312a_all_channels_sets_then_enables_each(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == [
        "CURR 0.05,(@1)",
        "VOLT 1,(@1)",
        "CURR 0.05,(@2)",
        "VOLT 1,(@2)",
        "CURR 0.05,(@3)",
        "VOLT 1,(@3)",
        "OUTP ON,(@1)",
        "OUTP ON,(@2)",
        "OUTP ON,(@3)",
    ]
    assert payload["data"]["channel"] == "all"
    assert payload["data"]["output"] == {"enabled": True}
    assert payload["data"]["channels"] == [
        {"channel": 1, "setpoints": {"current": 0.05, "voltage": 1.0}},
        {"channel": 2, "setpoints": {"current": 0.05, "voltage": 1.0}},
        {"channel": 3, "setpoints": {"current": 0.05, "voltage": 1.0}},
    ]

def test_apply_real_e36312a_no_output_skips_output_on(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--no-output",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.writes == [
        "CURR 0.05,(@1)",
        "VOLT 1,(@1)",
        "CURR 0.05,(@2)",
        "VOLT 1,(@2)",
        "CURR 0.05,(@3)",
        "VOLT 1,(@3)",
    ]
    assert payload["request"]["no_output"] is True
    assert payload["data"]["output"] == {"enabled": False}

@pytest.mark.parametrize(
    "args",
    [
        output_command_args("set"),
        output_command_args("output-on"),
        output_command_args("output-off"),
        output_command_args("safe-off"),
    ],
)
def test_output_commands_simulate_without_dry_run_succeed_without_real_visa(
    monkeypatch,
    capsys,
    args,
) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)

    assert cli.main([*args, "--simulate", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"] == {
        "mode": "simulate",
        "dry_run": False,
        "hardware_touched": False,
    }
    assert payload["data"]["plan"]["operation"] == {"name": args[0]}
    assert payload["data"]["plan"]["hardware_touched"] is False
    assert captured.err == ""

def test_set_plan_orders_current_limit_before_voltage(capsys) -> None:
    assert cli.main([*output_command_args("set"), "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    steps = json.loads(captured.out)["data"]["plan"]["steps"]
    assert steps == [
        {
            "index": 1,
            "type": "driver_action",
            "action": "set_current_limit",
            "parameters": {"channel": 1, "current": 0.05},
        },
        {
            "index": 2,
            "type": "driver_action",
            "action": "set_voltage",
            "parameters": {"channel": 1, "voltage": 1.0},
        },
    ]

def test_set_dry_run_json_accepts_voltage_only(capsys) -> None:
    assert cli.main([
        "set",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--voltage",
        "1",
        "--dry-run",
        "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["voltage"] == 1.0
    assert "current" not in payload["request"]
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == ["set_voltage"]

def test_set_dry_run_json_accepts_current_only(capsys) -> None:
    assert cli.main([
        "set",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--current",
        "0.05",
        "--dry-run",
        "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["current"] == 0.05
    assert "voltage" not in payload["request"]
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == ["set_current_limit"]

def test_set_dry_run_json_rejects_missing_setpoints(capsys) -> None:
    assert cli.main([
        "set",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--dry-run",
        "--json",
    ]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "argument_error"
    assert "set requires voltage, current, or both" in payload["error"]["message"]

def test_set_text_dry_run_lists_only_requested_setpoint(capsys) -> None:
    assert cli.main([
        "set",
        "--resource",
        "USB0::SIM::E36312A::INSTR",
        "--channel",
        "1",
        "--voltage",
        "1",
        "--dry-run",
    ]) == 0

    captured = capsys.readouterr()
    assert "set_voltage channel=1 voltage=1" in captured.out
    assert "set_current_limit" not in captured.out

def test_channel_two_plan_is_logical_and_not_scpi(capsys) -> None:
    args = output_command_args("set", channel="2")
    args[2] = "USB0::SIM::E36312A::INSTR"

    assert cli.main([*args, "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    plan = payload["data"]["plan"]
    assert plan["target"]["channel"] == 2
    assert all(step["parameters"]["channel"] == 2 for step in plan["steps"])
    assert all("command" not in step for step in plan["steps"])
    assert "SCPI" not in captured.out

def test_output_all_channel_dry_run_expands_supported_commands(capsys) -> None:
    assert (
        cli.main(
            [
                "safe-off",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--channel",
                "all",
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["data"]["plan"]["target"]["channel"] == "all"
    assert payload["data"]["plan"]["steps"] == [
        {
            "index": 1,
            "type": "driver_action",
            "action": "safe_off",
            "parameters": {"channel": 1},
        },
        {
            "index": 2,
            "type": "driver_action",
            "action": "safe_off",
            "parameters": {"channel": 2},
        },
        {
            "index": 3,
            "type": "driver_action",
            "action": "safe_off",
            "parameters": {"channel": 3},
        },
    ]

    for command, expected_actions in (
        ("output-on", ["output_on", "output_on", "output_on"]),
        ("output-off", ["output_off", "output_off", "output_off"]),
        ("output-state", ["output_state", "output_state", "output_state"]),
    ):
        args = output_command_args(command, channel="all")
        args[2] = "USB0::SIM::E36312A::INSTR"
        assert cli.main([*args, "--dry-run", "--json"]) == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["data"]["plan"]["target"]["channel"] == "all"
        assert [step["action"] for step in payload["data"]["plan"]["steps"]] == expected_actions
        assert [step["parameters"]["channel"] for step in payload["data"]["plan"]["steps"]] == [1, 2, 3]

    args = output_command_args("cycle-output", channel="all", duration_ms="250")
    args[2] = "USB0::SIM::E36312A::INSTR"
    assert cli.main([*args, "--dry-run", "--json"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert [step["action"] for step in payload["data"]["plan"]["steps"]] == [
        "output_on",
        "output_on",
        "output_on",
        "sleep",
        "output_off",
        "output_off",
        "output_off",
    ]
    assert payload["data"]["plan"]["steps"][3]["parameters"] == {"duration_ms": 250}

    for command in ("set", "ramp", "smoke-output"):
        args = output_command_args(command, channel="all")
        if command == "ramp":
            args = [
                "ramp",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "all",
                "--start-voltage",
                "0",
                "--stop-voltage",
                "1",
                "--step-voltage",
                "0.5",
                "--current",
                "0.1",
            ]
        assert cli.main([*args, "--dry-run", "--json"]) == 2
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["error"]["type"] == "validation"
        assert payload["error"]["code"] == "argument_error"
        assert payload["execution"]["hardware_touched"] is False

@pytest.mark.parametrize(
    ("args", "expected_message"),
    [
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "-0.1",
                "--current",
                "0.05",
            ],
            "voltage must be non-negative",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "nan",
                "--current",
                "0.05",
            ],
            "voltage must be finite",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "inf",
                "--current",
                "0.05",
            ],
            "voltage must be finite",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "-0.05",
            ],
            "current must be non-negative",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "nan",
            ],
            "current must be finite",
        ),
        (
            [
                "set",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "inf",
            ],
            "current must be finite",
        ),
        (
            [
                "output-on",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "0",
            ],
            "channel must be a positive integer",
        ),
    ],
)
def test_output_command_invalid_values_use_stable_json_validation_errors(
    args,
    expected_message,
    capsys,
) -> None:
    assert cli.main([*args, "--dry-run", "--json"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["execution"]["hardware_touched"] is False
    assert payload["data"] is None
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert payload["error"]["retryable"] is False
    assert expected_message in payload["error"]["message"]
    assert captured.err == ""

@pytest.mark.parametrize(
    ("channel", "expected_writes"),
    [
        (1, ["CURR 0.05,(@1)", "VOLT 1,(@1)"]),
        (2, ["CURR 0.05,(@2)", "VOLT 1,(@2)"]),
        (3, ["CURR 0.05,(@3)", "VOLT 1,(@3)"]),
    ],
)
def test_set_real_e36312a_sends_current_before_voltage(
    monkeypatch,
    capsys,
    channel,
    expected_writes,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                str(channel),
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == expected_writes
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.closed is True
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": False,
        "hardware_touched": True,
    }
    assert payload["data"] == {
        "resource": expected_resource(
            OUTPUT_RESOURCE,
            reachable=True,
            idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        ),
        "channel": channel,
        "setpoints": {"current": 0.05, "voltage": 1.0},
    }
    assert captured.err == ""

def test_set_real_text_output_is_minimal_without_output_enabled(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(output_command_args("set")) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        f"Resource: {OUTPUT_RESOURCE}\n"
        "Channel: 1\n"
        "Current limit: 0.05 A\n"
        "Voltage: 1 V\n"
    )
    assert "Output enabled" not in captured.out
    assert captured.err == ""

def test_set_real_resource_alias_backend_timeout_resolves_once(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    opened: list[tuple[str, str | None, int]] = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        opened.append((resource, backend, timeout_ms))
        return session

    monkeypatch.setattr(cli_runtime, "open_resource", fake_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
allowed_channels = [1, 2, 3]
max_voltage = 5.0
max_current = 0.5

[[resources]]
alias = "e36312a"
resource = "{OUTPUT_RESOURCE}"
allowed_channels = [2]
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource-alias",
                "e36312a",
                "--channel",
                "2",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--safety-config",
                safety_config,
                "--backend",
                "@py",
                "--timeout-ms",
                "1234",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert opened == [(OUTPUT_RESOURCE, "@py", 1234)]
    assert_live_scope_rejected(payload, session)
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": "e36312a",
        "channel": 2,
        "voltage": 1.0,
        "current": 0.05,
        "safety_config": safety_config,
        "backend": "@py",
        "timeout_ms": 1234,
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
    }
    assert payload["execution"]["hardware_touched"] is True
    assert captured.err == ""

def test_set_real_safety_config_rejects_before_open(monkeypatch, tmp_path, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
allowed_channels = [1]
max_voltage = 5.0
max_current = 0.5
""".strip(),
    )

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "2",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 2 is not allowed" in payload["error"]["message"]
    assert captured.err == ""

def test_set_real_e36312a_with_log_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> CURR 0.05,(@1)" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> VOLT 1,(@1)" in captured.err
    json.loads(captured.out)

@pytest.mark.parametrize("idn", ["KEYSIGHT,UNKNOWN,SERIAL0000,1.0", "UNKNOWN,MODEL,SN,FW"])
def test_set_real_non_e36312a_models_are_rejected(monkeypatch, capsys, idn) -> None:
    session = FakeSession(idn=idn)
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("set"), "--json"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert_live_scope_rejected(payload, session)

def test_set_real_edu36311a_sends_current_before_voltage(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "2",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 0
    )

    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == ["CURR 0.05,(@2)", "VOLT 1,(@2)"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["resource"]["idn"]["model"] == "EDU36311A"

def test_set_real_edu36311a_rejects_completion_pulse(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--completion-pulse-pins",
                "1",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "trigger_native_unsupported"

def test_set_real_unsupported_channel_is_rejected_after_idn(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("set", channel="99"), "--json"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 99 is not supported for set" in payload["error"]["message"]

def test_set_real_open_failure_uses_connection_failed(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise VisaConnectionError("open failed")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert cli.main([*output_command_args("set"), "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "connection_failed"

def test_set_real_write_failure_uses_set_failed(monkeypatch, capsys) -> None:
    class FailingWriteSession(FakeSession):
        def write(self, command: str) -> None:
            super().write(command)
            raise VisaConnectionError("write failed")

    session = FailingWriteSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("set"), "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?"]
    assert session.writes == ["CURR 0.05,(@1)"]
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "set_failed"

def test_set_real_instrument_error_queue_fails_command(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"SYST:ERR?": ['-222,"Data out of range"', '0,"No error"']},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("set"), "--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert session.writes == ["CURR 0.05,(@1)", "VOLT 1,(@1)"]
    assert session.queries == ["*IDN?", "SYST:ERR?", "SYST:ERR?"]
    assert payload["ok"] is False
    assert payload["error"]["code"] == "set_failed"
    assert '-222,"Data out of range"' in payload["error"]["message"]

@pytest.mark.parametrize("channel", [1, 2, 3])
def test_output_on_real_e36312a_sends_correct_scpi(monkeypatch, capsys, channel) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={
            f"VOLT? (@{channel})": "1.0",
            f"CURR? (@{channel})": "0.05",
        },
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                str(channel),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["output"]["enabled"] is True
    assert any(command.startswith("OUTP ON") for command in session.writes)

def test_output_on_real_text_output_reports_enabled(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@2)": "1.0", "CURR? (@2)": "0.05"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("output-on"), "--channel", "2"]) == 0

    captured = capsys.readouterr()
    assert "enabled" in captured.out.lower()
    assert captured.err == ""
    assert session.queries[0] == "*IDN?"
    assert any(command.startswith("OUTP ON") for command in session.writes)
    assert session.closed is True

def test_output_on_real_resource_alias_backend_timeout_resolves_once(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@2)": "1.0", "CURR? (@2)": "0.05"},
    )
    opened: list[tuple[str, str | None, int]] = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        opened.append((resource, backend, timeout_ms))
        return session

    monkeypatch.setattr(cli_runtime, "open_resource", fake_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
allowed_channels = [1, 2, 3]

[[resources]]
alias = "e36312a"
resource = "{OUTPUT_RESOURCE}"
allowed_channels = [2]
""".strip(),
    )

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource-alias",
                "e36312a",
                "--channel",
                "2",
                "--safety-config",
                safety_config,
                "--backend",
                "@py",
                "--timeout-ms",
                "1234",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert opened == [(OUTPUT_RESOURCE, "@py", 1234)]
    assert_live_scope_rejected(payload, session)
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": "e36312a",
        "channel": 2,
        "safety_config": safety_config,
        "backend": "@py",
        "timeout_ms": 1234,
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
    }
    assert payload["execution"]["hardware_touched"] is True
    assert captured.err == ""

def test_output_on_real_safety_config_rejects_before_open(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "2",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 2 is not allowed" in payload["error"]["message"]
    assert captured.err == ""

def test_output_on_real_e36312a_with_log_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> VOLT? (@1)" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> OUTP ON,(@1)" in captured.err
    json.loads(captured.out)  # must not raise - stdout is valid JSON

@pytest.mark.parametrize("idn", ["KEYSIGHT,UNKNOWN,SERIAL0000,1.0", "UNKNOWN,MODEL,SN,FW"])
def test_output_on_real_non_e36312a_models_are_rejected(monkeypatch, capsys, idn) -> None:
    session = FakeSession(idn=idn)
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert_live_scope_rejected(payload, session)

def test_output_on_real_unsupported_channel_is_rejected_after_idn(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "99",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"

def test_output_on_real_open_failure_uses_connection_failed(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise VisaConnectionError("open failed")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert cli.main([*output_command_args("output-on"), "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "connection_failed"

def test_output_on_real_write_failure_surfaces_connection_error(monkeypatch, capsys) -> None:
    class FailingWriteSession(FakeSession):
        def write(self, command: str) -> None:
            super().write(command)
            raise VisaConnectionError("write failed")

    session = FailingWriteSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert cli.main([*output_command_args("output-on"), "--json"]) == 1

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "connection"
    assert payload["error"]["code"] == "output_on_failed"
    assert session.writes

def test_output_on_real_safety_config_checks_readback_before_enabling(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)
    safety_config = write_safety_config(tmp_path)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--safety-config",
                safety_config,
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["data"]["readback"]["safety_checked"] is True
    assert any(command.startswith("OUTP ON") for command in session.writes)

def test_output_on_real_safety_config_rejects_unsafe_readback(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "5.1", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)
    safety_config = write_safety_config(tmp_path)

    assert (
        cli.main(
            [
                "output-on",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "safety"
    assert payload["error"]["code"] == "unsafe_output_setpoint"
    assert not any(command.startswith("OUTP ON") for command in session.writes)

@pytest.mark.parametrize("channel", [1, 2, 3])
def test_output_off_real_e36312a_sends_correct_scpi(monkeypatch, capsys, channel) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                str(channel),
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert session.writes == [f"OUTP OFF,(@{channel})"]
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.closed is True
    assert payload["execution"]["mode"] == "real"
    assert payload["execution"]["dry_run"] is False
    assert payload["execution"]["hardware_touched"] is True
    assert payload["data"]["channel"] == channel
    assert payload["data"]["output"]["enabled"] is False
    assert payload["data"]["resource"]["name"] == OUTPUT_RESOURCE
    assert payload["data"]["resource"]["idn"]["model"] == "E36312A"
    assert captured.err == ""

def test_output_off_real_resource_alias_resolves_once_and_sends_scpi(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    opened: list[tuple[str, str | None, int]] = []

    def fake_open_resource(resource, *, backend=None, timeout_ms=5000):
        opened.append((resource, backend, timeout_ms))
        return session

    monkeypatch.setattr(cli_runtime, "open_resource", fake_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        f"""
[safety]
allowed_channels = [1, 2, 3]

[[resources]]
alias = "e36312a"
resource = "{OUTPUT_RESOURCE}"
allowed_channels = [2]
""".strip(),
    )

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource-alias",
                "e36312a",
                "--channel",
                "2",
                "--safety-config",
                safety_config,
                "--backend",
                "@py",
                "--timeout-ms",
                "1234",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert opened == [(OUTPUT_RESOURCE, "@py", 1234)]
    assert_live_scope_rejected(payload, session)
    assert payload["request"] == {
        "resource": OUTPUT_RESOURCE,
        "resource_alias": "e36312a",
        "channel": 2,
        "safety_config": safety_config,
        "backend": "@py",
        "timeout_ms": 1234,
        **WRITE_VERIFICATION_REQUEST_DEFAULTS,
    }
    assert payload["execution"]["hardware_touched"] is True
    assert captured.err == ""

def test_output_off_real_safety_config_rejects_before_open(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)
    safety_config = write_safety_config(
        tmp_path,
        """
[safety]
allowed_channels = [1]
""".strip(),
    )

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "2",
                "--safety-config",
                safety_config,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["execution"]["hardware_touched"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"
    assert "channel 2 is not allowed" in payload["error"]["message"]
    assert captured.err == ""

def test_output_off_real_e36312a_with_log_scpi(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--log-scpi",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["data"]["output"]["enabled"] is False
    assert f"{OUTPUT_RESOURCE} SCPI >> *IDN?" in captured.err
    assert f"{OUTPUT_RESOURCE} SCPI >> OUTP OFF,(@1)" in captured.err
    json.loads(captured.out)  # must not raise - stdout is valid JSON

def test_output_off_real_generic_e36312a_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,UNKNOWN,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["execution"]["hardware_touched"] is True
    assert payload["error"]["type"] == "validation"
    assert_live_scope_rejected(payload, session)

def test_output_off_real_unknown_model_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="UNKNOWN,MODEL,SN,FW")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert_live_scope_rejected(payload, session)

def test_output_off_real_unsupported_channel_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-off",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "99",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"

def test_output_state_real_non_e36312a_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,UNKNOWN,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-state",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert_live_scope_rejected(payload, session)

def test_output_state_real_edu36311a_reads_channel_state(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0",
        query_responses={"OUTP? (@3)": "OFF"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "output-state",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "3",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert session.queries == ["*IDN?", "OUTP? (@3)"]
    assert payload["data"]["output_enabled"] is False

def test_cycle_output_real_invalid_duration_rejected(capsys) -> None:
    assert (
        cli.main(
            [
                "cycle-output",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--duration-ms",
                "0",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == "argument_error"

def test_apply_real_generic_model_is_rejected(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,UNKNOWN,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert_live_scope_rejected(payload, session)

def test_apply_real_edu36311a_all_no_output_writes_all_channels(monkeypatch, capsys) -> None:
    session = FakeSession(idn="KEYSIGHT,EDU36311A,SERIAL0000,1.0")
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "apply",
                "--json",
                "--resource",
                "USB0::FAKE::EDU36311A::INSTR",
                "--channel",
                "all",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--no-output",
            ]
        )
        == 0
    )

    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == [
        "CURR 0.05,(@1)",
        "VOLT 1,(@1)",
        "CURR 0.05,(@2)",
        "VOLT 1,(@2)",
        "CURR 0.05,(@3)",
        "VOLT 1,(@3)",
    ]
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["resource"]["idn"]["model"] == "EDU36311A"
    assert payload["data"]["output"]["enabled"] is False

@pytest.mark.parametrize(
    ("command", "extra_args"),
    [
        ("set", ["--channel", "1", "--voltage", "1", "--current", "0.05"]),
        ("output-on", ["--channel", "1"]),
        ("output-off", ["--channel", "1"]),
        ("safe-off", ["--channel", "1"]),
        ("cycle-output", ["--channel", "1", "--duration-ms", "1"]),
        ("apply", ["--channel", "1", "--voltage", "1", "--current", "0.05"]),
        ("ramp", ["--channel", "1", "--start-voltage", "0", "--stop-voltage", "1", "--step-voltage", "1", "--current", "0.05"]),
        ("smoke-output", ["--channel", "1", "--voltage", "1", "--current", "0.05"]),
        ("ramp-list", ["--lint", "--segment", "1", "0.05", "0", "1", "1", "0", "0"]),
        ("sequence", ["--lint", "--file", "examples/sequence-readonly.yaml"]),
    ],
)
def test_output_commands_accept_serial_options_in_json_request(capsys, command, extra_args) -> None:
    assert (
        cli.main(
            [
                command,
                "--json",
                "--resource",
                "ASRL1::INSTR",
                *extra_args,
                *SERIAL_TERMINATION_ARGS,
                "--model",
                "keysight-e36312a",
                "--dry-run",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["serial_options"]["read_termination"] == "\r\n"
    assert payload["request"]["serial_options"]["write_termination"] == "\n"
    assert payload["request"]["serial_remote"] is True
    assert payload["request"]["serial_local_on_close"] is True

def test_output_state_serial_options_still_work(capsys) -> None:
    assert (
        cli.main(
            [
                "output-state",
                "--json",
                "--simulate",
                "--resource",
                "ASRL1::SIM::E3646A::INSTR",
                "--channel",
                "1",
                *SERIAL_TERMINATION_ARGS,
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["request"]["serial_options"]["read_termination"] == "\r\n"
    assert payload["request"]["serial_options"]["write_termination"] == "\n"

def test_safe_off_accepts_serial_options_without_confirm(monkeypatch, capsys) -> None:
    session = FakeSession(
        idn="KEYSIGHT,E3646A,SERIAL0000,1.0",
        query_responses={"INST:NSEL?": "1", "OUTP?": "0"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "safe-off",
                "--json",
                "--resource",
                "ASRL1::INSTR",
                "--channel",
                "1",
                *SERIAL_TERMINATION_ARGS,
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True

@pytest.mark.parametrize(
    ("command", "extra_args", "query_responses"),
    [
        ("set", ["--channel", "1", "--voltage", "1", "--current", "0.05"], {"INST:NSEL?": "1"}),
        ("output-on", ["--channel", "1"], {"INST:NSEL?": "1", "VOLT?": "1.0", "CURR?": "0.05", "OUTP?": "0"}),
        ("output-off", ["--channel", "1"], {"INST:NSEL?": "1", "OUTP?": "1"}),
        ("safe-off", ["--channel", "1"], {"INST:NSEL?": "1", "OUTP?": "1"}),
        ("cycle-output", ["--channel", "1", "--duration-ms", "1"], {"INST:NSEL?": "1", "VOLT?": "1.0", "CURR?": "0.05", "OUTP?": "1"}),
        ("apply", ["--channel", "1", "--voltage", "1", "--current", "0.05", "--no-output"], {"INST:NSEL?": "1"}),
        ("ramp", ["--channel", "1", "--start-voltage", "0", "--stop-voltage", "1", "--step-voltage", "1", "--current", "0.05"], {"INST:NSEL?": "1"}),
        ("smoke-output", ["--channel", "1", "--voltage", "1", "--current", "0.05"], {"INST:NSEL?": "1", "OUTP?": "0", "MEAS:VOLT?": "1.0", "MEAS:CURR?": "0.05"}),
    ],
)
def test_output_family_real_forwards_serial_options_to_opener(
    monkeypatch,
    capsys,
    command,
    extra_args,
    query_responses,
) -> None:
    opened = []
    session = FakeSession(idn="KEYSIGHT,E3646A,SERIAL0000,1.0", query_responses=query_responses)

    def fake_open_resource(resource, resource_manager=None, *, backend=None, timeout_ms=5000, **kwargs):
        opened.append(kwargs)
        return session

    monkeypatch.setattr(cli_runtime, "open_resource", fake_open_resource)

    assert (
        cli.main(
            [
                command,
                "--json",
                "--resource",
                "ASRL1::INSTR",
                *extra_args,
                *SERIAL_TERMINATION_ARGS,
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    serial_options = opened[0]["serial_options"]
    assert serial_options.read_termination == "\r\n"
    assert serial_options.write_termination == "\n"
    assert opened[0]["serial_remote"] is True
    assert opened[0]["serial_local_on_close"] is True

@pytest.mark.parametrize(
    ("command", "args", "query_responses"),
    [
        ("set", ["--voltage", "1", "--current", "0.05"], {"VOLT? (@1)": "1.2", "CURR? (@1)": "0.05"}),
        ("apply", ["--voltage", "1", "--current", "0.05", "--no-output"], {"VOLT? (@1)": "1.2", "CURR? (@1)": "0.05"}),
        ("output-off", [], {"OUTP? (@1)": "ON"}),
        (
            "ramp",
            ["--start-voltage", "0", "--stop-voltage", "1", "--step-voltage", "1", "--current", "0.05"],
            {"VOLT? (@1)": "0.8", "CURR? (@1)": "0.05"},
        ),
    ],
)
def test_write_verification_failure_returns_exit_3(monkeypatch, capsys, command, args, query_responses) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0", query_responses=query_responses)
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *open_args, **open_kwargs: session)

    assert (
        cli.main(
            [
                command,
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                *args,
                "--verify-after-write",
            ]
        )
        == 3
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "verification_failed"
    assert payload["metadata"]["verification"]["passed"] is False

def test_settle_ms_sleeps_before_verification(monkeypatch, capsys) -> None:
    sleeps = []
    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"VOLT? (@1)": "1.0", "CURR? (@1)": "0.05"},
    )
    monkeypatch.setattr(cli_runtime, "open_resource", lambda *args, **kwargs: session)
    monkeypatch.setattr(output_run.time, "sleep", lambda seconds: sleeps.append(seconds))

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--voltage",
                "1",
                "--current",
                "0.05",
                "--settle-ms",
                "25",
                "--verify-after-write",
            ]
        )
        == 0
    )

    assert sleeps == [0.025]
    assert json.loads(capsys.readouterr().out)["data"]["verification"]["passed"] is True

def test_output_off_dry_run_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened for dry-run")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "output-off",
                "--dry-run",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert "plan" in payload["data"]
    assert payload["data"]["plan"]["operation"]["name"] == "output-off"
    assert payload["execution"]["hardware_touched"] is False

def test_output_off_simulate_does_not_open_resource(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("VISA resource should not be opened for simulate")

    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    assert (
        cli.main(
            [
                "output-off",
                "--simulate",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert "plan" in payload["data"]

@pytest.mark.parametrize("command,extra_args", [
    ("safe-off", []),
])
def test_safe_off_dry_run_remains_logical(monkeypatch, capsys, command, extra_args) -> None:
    def fail_real_manager(backend=None):
        raise AssertionError("real VISA manager should not be created")

    def fail_open_resource(*args, **kwargs):
        raise AssertionError("real VISA resource should not be opened")

    monkeypatch.setattr(connection, "create_resource_manager", fail_real_manager)
    monkeypatch.setattr(cli_runtime, "open_resource", fail_open_resource)

    args = [command, "--json", "--resource", OUTPUT_RESOURCE, "--channel", "1"] + extra_args
    assert cli.main([*args, "--dry-run"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["execution"] == {
        "mode": "real",
        "dry_run": True,
        "hardware_touched": False,
    }
    assert payload["data"]["plan"]["operation"]["name"] == "safe-off"
