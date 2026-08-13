from __future__ import annotations

import ast
import inspect
from pathlib import Path

import powers_tool_cli.cli as cli

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


def test_active_restore_trigger_and_sequence_adapters_delegate_scpi_to_core() -> None:
    restore_source = inspect.getsource(cli._run_restore_from_snapshot)
    trigger_source = inspect.getsource(cli._run_core_trigger)
    sequence_source = inspect.getsource(cli._run_sequence)

    assert "restore_core.run_restore" in restore_source
    assert "trigger_core.run_trigger" in trigger_source
    assert "run_core_command" in sequence_source
    assert "_open_resource(" not in restore_source
    assert "create_power_supply(" not in restore_source
    assert not any(token in restore_source for token in ("OUTP ", "VOLT:", "CURR:", "SYST:ERR?"))
    assert not any(token in trigger_source for token in ("ABOR ", "INIT ", "LIST:", "TRIG:SOUR"))
    assert not any(token in sequence_source for token in ("OUTP ", "VOLT ", "CURR ", "SYST:ERR?"))
