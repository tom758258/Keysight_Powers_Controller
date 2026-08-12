from __future__ import annotations

import pytest

import powers_tool_core.capabilities as capabilities


def test_hardware_validation_status_e36312a_shape() -> None:
    assert capabilities.hardware_validation_status("keysight-e36312a") == {
        "read_only": "validated",
        "output": "validated",
        "protection": "validated",
        "trigger": "validated",
    }


def test_hardware_validation_status_edu36311a_trigger_boundary() -> None:
    assert capabilities.hardware_validation_status("keysight-edu36311a") == {
        "read_only": "validated",
        "output": "validated",
        "protection": {
            "dry_run": True,
            "simulate": True,
            "real": True,
            "hardware_validation": "validated",
        },
        "trigger": "not_supported_by_model",
    }


def test_command_support_e36312a_output_protection_and_trigger_real() -> None:
    support = capabilities.command_support("keysight-e36312a")

    assert support["output-on"]["real"] is True
    assert support["output-on"]["hardware_validation"] == "validated_confirm_threshold_conditional"
    assert support["protection-set"]["real"] is True
    for command in (
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    ):
        assert support[command]["real"] is True
        assert support[command]["simulate"] is True
        assert support[command]["dry_run"] is True
        assert support[command]["hardware_validation"] == "validated"


def test_command_support_edu36311a_output_protection_and_trigger_boundary() -> None:
    support = capabilities.command_support("keysight-edu36311a")

    assert support["output-on"]["real"] is True
    assert support["protection-set"] == {
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
        assert support[command]["real"] is False
        assert support[command]["simulate"] is False
        assert support[command]["dry_run"] is False
        assert support[command]["hardware_validation"] == "not_supported_by_model"


@pytest.mark.parametrize("command", ["trigger-step", "trigger-list"])
def test_command_support_e36312a_native_trigger_policy(command: str) -> None:
    support = capabilities.command_support("keysight-e36312a")

    assert support[command]["real"] is True
    assert support[command]["simulate"] is True
    assert support[command]["dry_run"] is True
    assert support[command]["hardware_validation"] == "validated"


@pytest.mark.parametrize("command", ["snapshot", "restore-from-snapshot"])
def test_command_support_edu36311a_snapshot_restore_disabled(command: str) -> None:
    support = capabilities.command_support("keysight-edu36311a")

    assert support[command]["real"] is False
    assert support[command]["simulate"] is False
    assert support[command]["dry_run"] is False
    assert support[command]["hardware_validation"] == "not_supported_by_model"


def test_command_support_generic_fallback() -> None:
    support = capabilities.command_support(None)

    assert support["identify"]["real"] is True
    assert support["identify"]["hardware_validation"] == "generic_channel_1_only"
    assert support["measure"]["real"] is True
    assert support["set"]["real"] is False
    assert support["set"]["hardware_validation"] == "not_enabled"


@pytest.mark.parametrize("model", [None, "UNKNOWN"])
def test_command_support_non_e36312a_models_disable_trigger_no_hardware(model: str | None) -> None:
    support = capabilities.command_support(model)

    for command in (
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    ):
        assert support[command]["real"] is False
        assert support[command]["simulate"] is False
        assert support[command]["dry_run"] is False


def test_command_support_e3646a_rs232_read_only_boundary() -> None:
    assert capabilities.hardware_validation_status("keysight-e3646a") == {
        "read_only": "rs232_read_only",
        "output": "validated",
        "protection": "not_enabled",
        "trigger": "not_enabled",
    }

    support = capabilities.command_support("keysight-e3646a")

    assert "verify" not in support
    for command in ("identify", "measure", "readback", "read-status", "output-state", "capabilities"):
        assert support[command]["real"] is True
        assert support[command]["hardware_validation"] == "rs232_read_only"

    assert support["log"] == {
        "real": True,
        "simulate": True,
        "dry_run": False,
        "requires_confirm": False,
        "hardware_validation": "rs232_read_only",
    }

    validated_output_commands = (
        "set",
        "output-off",
        "safe-off",
        "ramp",
        "ramp-list",
        "sequence",
    )
    for command in validated_output_commands:
        assert support[command]["real"] is True
        assert support[command]["hardware_validation"] == "validated"

    conditional_output_commands = ("apply", "output-on", "cycle-output", "smoke-output")
    for command in conditional_output_commands:
        assert support[command]["real"] is True
        assert support[command]["hardware_validation"] == "validated_confirm_threshold_conditional"

    assert support["ramp-list"]["requires_confirm"] is False

    for command in (
        "protection-set",
        "clear-protection",
        "restore-from-snapshot",
        "trigger-step",
        "trigger-status",
        "trigger-pulse",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
        "snapshot",
    ):
        assert support[command]["real"] is False
        if command.startswith("trigger-"):
            assert support[command]["simulate"] is False
            assert support[command]["dry_run"] is False
        assert support[command]["hardware_validation"] == "not_enabled"


def test_command_support_psm2010_product_boundary() -> None:
    assert capabilities.hardware_validation_status("gw-instek-psm-2010") == {
        "read_only": "rs232_read_only",
        "output": "validated",
        "protection": "validated",
        "trigger": "not_supported_by_model",
    }

    support = capabilities.command_support("gw-instek-psm-2010")

    readonly_commands = {
        "identify": True,
        "measure": False,
        "output-state": True,
        "readback": False,
        "read-status": False,
        "capabilities": False,
        "validate-readonly": False,
        "log": False,
    }
    for command, dry_run in readonly_commands.items():
        assert support[command]["real"] is True
        assert support[command]["simulate"] is True
        assert support[command]["dry_run"] is dry_run
        assert support[command]["hardware_validation"] == "rs232_read_only"

    dry_run_commands = {
        "set", "apply", "output-on", "output-off", "safe-off", "cycle-output",
        "ramp", "ramp-list", "sequence", "smoke-output", "protection-set",
        "clear-protection", "restore-from-snapshot",
    }
    for command in (
        "set", "output-off", "safe-off", "ramp", "ramp-list", "sequence",
        "protection-status", "protection-set", "clear-protection", "snapshot",
        "restore-from-snapshot",
    ):
        assert support[command]["real"] is True
        assert support[command]["simulate"] is True
        assert support[command]["dry_run"] is (command in dry_run_commands)
        assert support[command]["hardware_validation"] == "validated"

    for command in ("output-on", "cycle-output", "apply", "smoke-output"):
        assert support[command]["real"] is True
        assert support[command]["simulate"] is True
        assert support[command]["dry_run"] is True
        assert support[command]["hardware_validation"] == (
            "validated_confirm_threshold_conditional"
        )

    assert support["doctor"] == {
        "real": True,
        "simulate": True,
        "dry_run": False,
        "requires_confirm": False,
        "hardware_validation": "not_applicable",
    }

    for command in capabilities.TRIGGER_COMMANDS:
        assert support[command] == {
            "real": False,
            "simulate": False,
            "dry_run": False,
            "requires_confirm": False,
            "hardware_validation": "not_supported_by_model",
        }


@pytest.mark.parametrize(
    "command",
    [
        "protection-set",
        "clear-protection",
        "snapshot",
        "restore-from-snapshot",
        "trigger-pulse",
        "trigger-status",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    ],
)
def test_command_support_e3646a_unsupported_mutating_and_native_workflows_disabled(command: str) -> None:
    support = capabilities.command_support("keysight-e3646a")

    assert support[command]["real"] is False
    assert support[command]["simulate"] is False
    assert support[command]["dry_run"] is False
    assert support[command]["hardware_validation"] == "not_enabled"


@pytest.mark.parametrize("command", ["ramp-list", "sequence"])
def test_command_support_e3646a_software_workflows_remain_allowed(command: str) -> None:
    support = capabilities.command_support("keysight-e3646a")

    assert support[command]["real"] is True
    assert support[command]["simulate"] is True
    assert support[command]["hardware_validation"] == "validated"


@pytest.mark.parametrize("model", ["UNKNOWN", "FUTURE123"])
def test_command_support_unknown_models_do_not_enable_mutating_workflows(model: str) -> None:
    support = capabilities.command_support(model)

    for command in (
        "set",
        "apply",
        "output-on",
        "output-off",
        "safe-off",
        "cycle-output",
        "ramp",
        "ramp-list",
        "smoke-output",
        "sequence",
        "protection-set",
        "clear-protection",
        "snapshot",
        "restore-from-snapshot",
        "trigger-pulse",
        "trigger-step",
        "trigger-list",
        "trigger-fire",
        "trigger-abort",
    ):
        assert support[command]["real"] is False, command


def test_known_capability_commands_include_cli_queryable_commands() -> None:
    commands = capabilities.known_capability_commands()

    assert "verify" not in commands
    assert {
        "capabilities",
        "validate-readonly",
        "output-on",
        "protection-set",
        "trigger-step",
        "snapshot-diff",
        "safety inspect",
    } <= commands


def test_capabilities_static_groups_preserve_json_lists() -> None:
    assert capabilities.capabilities_static_groups() == {
        "read_only_commands": ["identify", "measure", "output-state", "readback", "read-status", "log", "sequence"],
        "output_commands": ["set", "output-on", "output-off", "safe-off", "cycle-output", "apply", "ramp", "ramp-list", "smoke-output"],
        "e36312a_only_commands": [
            "measure-all",
            "trigger-pulse",
            "trigger-status",
            "trigger-step",
            "trigger-list",
            "trigger-fire",
            "trigger-abort",
        ],
    }


def _unsupported_message(command: str, model: str, mode: str) -> str:
    model_id = {
        "E36312A": "keysight-e36312a",
        "EDU36311A": "keysight-edu36311a",
        "E3646A": "keysight-e3646a",
    }.get(model, model)
    with pytest.raises(Exception) as exc:
        capabilities.ensure_command_supported(command, model_id, None, mode)
    return str(exc.value)


def test_edu36311a_trigger_error_explains_feature_lock() -> None:
    message = _unsupported_message("trigger-step", "EDU36311A", "dry-run")

    assert "trigger-step" in message
    assert "EDU36311A" in message
    assert "dry-run mode" in message
    assert "disabled in live, simulate, and dry-run" in message
    assert "Use E36312A" in message


@pytest.mark.parametrize("command", sorted(capabilities.TRIGGER_COMMANDS))
def test_psm2010_trigger_error_explains_permanent_model_boundary(command: str) -> None:
    message = _unsupported_message(command, "gw-instek-psm-2010", "simulate")

    assert command in message
    assert "PSM-2010 does not support Powers trigger workflows." in message
    assert "not yet" not in message
    assert "not validated" not in message
    assert "currently disabled" not in message


@pytest.mark.parametrize("command", ["snapshot", "restore-from-snapshot"])
def test_edu36311a_snapshot_restore_error_explains_e36312a_only(command: str) -> None:
    message = _unsupported_message(command, "EDU36311A", "simulate")

    assert command in message
    assert "EDU36311A" in message
    assert "simulate mode" in message
    assert "E36312A-only" in message
    assert "hardware validated" in message


@pytest.mark.parametrize("command", ["protection-set", "trigger-list", "snapshot", "restore-from-snapshot", "trigger-pulse"])
def test_e3646a_disabled_workflow_errors_explain_validation_boundary(command: str) -> None:
    message = _unsupported_message(command, "E3646A", "live")

    assert command in message
    assert "E3646A" in message
    assert "live mode" in message
    assert "disabled until separately validated" in message
    if command in {"trigger-list", "trigger-pulse"}:
        assert "software workflows, not native LIST" in message


@pytest.mark.parametrize("model", ["UNKNOWN", "FUTURE123"])
def test_unknown_model_mutating_error_explains_feature_lock(model: str) -> None:
    message = _unsupported_message("output-on", model, "live")

    assert "output-on" in message
    assert model in message
    assert "live mode" in message
    assert "E36312A-only" in message
