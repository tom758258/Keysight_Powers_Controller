from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest
import powers_tool_cli.cli as cli
import powers_tool_cli.commands.output_run as output_run

CLI_IMPLEMENTATION_MODULES = (
    "cli.py",
    "cli_runtime.py",
    "cli_request.py",
    "commands/discovery.py",
    "commands/readonly.py",
    "commands/inspection.py",
    "commands/output_run.py",
    "commands/trigger_run.py",
    "commands/sequence_run.py",
)

ACTIVE_MODULES_WITHOUT_COMPAT_OR_LEGACY_DRIVER_IMPORTS = (
    "cli_request.py",
    "commands/discovery.py",
    "commands/readonly.py",
    "commands/inspection.py",
    "commands/output_run.py",
    "commands/trigger_run.py",
    "commands/sequence_run.py",
)


def _session_violations(source: str) -> list[int]:
    tree = ast.parse(source)
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr != "_session":
            continue
        owner = next(
            (
                candidate
                for candidate in ast.walk(tree)
                if isinstance(candidate, ast.ClassDef)
                and candidate.name == "_ScpiLoggingSession"
                and node in ast.walk(candidate)
            ),
            None,
        )
        if owner is None:
            violations.append(node.lineno)
    return violations


def test_cli_does_not_access_driver_private_session() -> None:
    package_dir = Path(cli.__file__).resolve().parent
    violations: list[str] = []
    for relative_path in CLI_IMPLEMENTATION_MODULES:
        source = (package_dir / relative_path).read_text(encoding="utf-8")
        for lineno in _session_violations(source):
            violations.append(f"{relative_path}:{lineno}")
    assert violations == []


def test_active_output_restore_trigger_and_sequence_adapters_delegate_scpi_to_core() -> None:
    output_source = inspect.getsource(output_run._run_core_output_real)
    restore_source = inspect.getsource(cli._run_restore_from_snapshot)
    trigger_source = inspect.getsource(cli._run_core_trigger)
    sequence_source = inspect.getsource(cli._run_sequence)

    assert "operations.run_operation" in output_source
    assert "run_core_command" in output_source
    assert "restore_core.run_restore" in restore_source
    assert "trigger_core.run_trigger" in trigger_source
    assert "run_core_command" in sequence_source
    assert not any(
        token in output_source for token in ("OUTP ", "VOLT ", "CURR ", "SYST:ERR?")
    )
    assert "_open_resource(" not in restore_source
    assert "create_power_supply(" not in restore_source
    assert not any(token in restore_source for token in ("OUTP ", "VOLT:", "CURR:", "SYST:ERR?"))
    assert not any(token in trigger_source for token in ("ABOR ", "INIT ", "LIST:", "TRIG:SOUR"))
    assert not any(token in sequence_source for token in ("OUTP ", "VOLT ", "CURR ", "SYST:ERR?"))


def test_validate_readonly_adapter_delegates_without_driver_workflow(monkeypatch, capsys) -> None:
    calls = []

    def fake_run_validate_readonly(request, *, opener, scpi_logger):
        calls.append((request, opener, scpi_logger))
        return {
            "resource": request.runtime.resource,
            "idn_raw": "KEYSIGHT,E36312A,SERIAL0000,1.0",
            "driver": {"class": "E36312APowerSupply", "reason": "model_specific_driver"},
            "capabilities": {
                "channels": [1, 2, 3],
                "measure_channels": {"simulate": [1, 2, 3], "real": [1, 2, 3]},
            },
            "hardware_validation": {"read_only": True},
            "errors": [],
            "read_count": 1,
            "outputs": [
                {"channel": channel, "enabled": False}
                for channel in (1, 2, 3)
            ],
            "readback": [
                {
                    "channel": channel,
                    "setpoints": {"voltage": 0.0, "current": 0.0},
                }
                for channel in (1, 2, 3)
            ],
            "measurements": [
                {
                    "channel": channel,
                    "measurements": {"voltage": 0.0, "current": 0.0},
                }
                for channel in (1, 2, 3)
            ],
        }

    monkeypatch.setattr(cli.readonly_core, "run_validate_readonly", fake_run_validate_readonly)
    monkeypatch.setattr(cli, "create_power_supply", lambda *args, **kwargs: pytest.fail("CLI created a driver"))
    monkeypatch.setattr(cli, "select_driver", lambda *args, **kwargs: pytest.fail("CLI selected a driver"))

    assert (
        cli.main(
            [
                "validate-readonly",
                "--json",
                "--simulate",
                "--resource",
                "USB0::SIM::E36312A::INSTR",
                "--max-errors",
                "7",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["driver"] == {
        "class": "E36312APowerSupply",
        "reason": "model_specific_driver",
    }
    assert len(calls) == 1
    assert calls[0][0].command == "validate-readonly"
    assert calls[0][0].parameters == {"max_errors": 7}


def test_validate_readonly_adapter_has_no_concrete_driver_import_or_branch() -> None:
    source = inspect.getsource(cli._run_validate_readonly)
    assert "readonly_core.run_validate_readonly" in source
    assert not any(
        token in source
        for token in (
            "_open_resource(",
            "_patchable_select_driver",
            "_patchable_create_power_supply",
            "driver_class",
            "isinstance(",
            "E36312APowerSupply",
            "EDU36311APowerSupply",
            "PSM2010PowerSupply",
            "OUTP?",
            "VOLT?",
            "CURR?",
        )
    )


def test_active_cli_modules_do_not_import_concrete_drivers() -> None:
    package_dir = Path(cli.__file__).resolve().parent
    violations: list[str] = []
    for relative_path in ACTIVE_MODULES_WITHOUT_COMPAT_OR_LEGACY_DRIVER_IMPORTS:
        tree = ast.parse((package_dir / relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
                "powers_tool_core.drivers"
            ):
                violations.append(f"{relative_path}:{node.lineno}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("powers_tool_core.drivers"):
                        violations.append(f"{relative_path}:{node.lineno}")
    assert violations == []
