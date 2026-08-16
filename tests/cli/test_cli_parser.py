from __future__ import annotations

import argparse
import ast
from functools import partial
import inspect
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

import powers_tool_cli.cli as cli
import powers_tool_cli.cli_parser as cli_parser
from powers_tool_cli.commands import (
    discovery,
    inspection,
    output as output_commands,
    output_run,
    ramp_list as ramp_list_commands,
    readonly,
    sequence as sequence_commands,
    sequence_run,
    trigger as trigger_commands,
)


PARSER_PRIMITIVES = (
    "JsonCliArgumentParser",
    "_add_backend_argument",
    "_add_channel_or_all_argument",
    "_add_completion_pulse_arguments",
    "_add_dry_run_argument",
    "_add_duration_argument",
    "_add_json_argument",
    "_add_lifecycle_format_arguments",
    "_add_lifecycle_timeout_argument",
    "_add_lifecycle_url_argument",
    "_add_model_argument",
    "_add_output_resource_arguments",
    "_add_ramp_completion_pulse_arguments",
    "_add_resource_argument",
    "_add_safety_config_argument",
    "_add_serial_arguments",
    "_add_simulate_argument",
    "_add_timeout_argument",
    "_add_trigger_restore_argument",
    "_add_trigger_wait_arguments",
    "_add_validation_support_policy_argument",
    "_add_write_verification_arguments",
    "_apply_channel",
    "_bool_list",
    "_channels_list",
    "_e36312a_channel",
    "_e36312a_channel_or_all",
    "_float_list",
    "_lifecycle_timeout_ms",
    "_log_channel",
    "_loop_count",
    "_nonnegative_int",
    "_output_channel",
    "_positive_channel",
    "_positive_duration_ms",
    "_positive_float",
    "_positive_int",
    "_positive_max_errors",
    "_positive_max_reads",
    "_safe_off_channel",
    "_status_channel",
    "_trigger_pin",
    "_trigger_pins_list",
    "_trigger_poll_ms",
)


ROOT_RUNNER_BINDINGS = {
    "run_list_resources": "_run_list_resources",
    "run_verify": "_run_verify",
    "run_clear": "_run_clear",
    "run_error": "_run_error",
    "run_measure": "_run_measure",
    "run_measure_all": "_run_measure_all",
    "run_status": "_run_status",
    "run_validate_readonly": "_run_validate_readonly",
    "run_readback": "_run_readback",
    "run_protection_status": "_run_protection_status",
    "run_protection_set": "_run_protection_set",
    "run_clear_protection": "_run_clear_protection",
    "run_identify": "_run_identify",
    "run_snapshot": "_run_snapshot",
    "run_snapshot_diff": "_run_snapshot_diff",
    "run_hardware_report": "_run_hardware_report",
    "run_restore_from_snapshot": "_run_restore_from_snapshot",
    "run_log": "_run_log",
    "run_doctor": "_run_doctor",
    "run_capabilities": "_run_capabilities",
    "run_safety_inspect": "_run_safety_inspect",
    "run_worker": "_run_worker",
}


FAMILY_RUNNER_BINDINGS = {
    "run_output_plan": "_run_output_plan",
    "run_core_trigger": "_run_core_trigger",
    "run_sequence_command": "_run_sequence",
    "run_ramp_list_command": "_run_ramp_list",
}


PARSER_RUNNER_BINDINGS = ROOT_RUNNER_BINDINGS | FAMILY_RUNNER_BINDINGS


PARSER_RUNNER_EXPRESSIONS = {
    "run_list_resources": "discovery._run_list_resources",
    "run_verify": "discovery._run_verify",
    "run_clear": "discovery._run_clear",
    "run_error": "discovery._run_error",
    "run_measure": "discovery._run_measure",
    "run_measure_all": "discovery._run_measure_all",
    "run_status": "readonly._run_status",
    "run_validate_readonly": "readonly._run_validate_readonly",
    "run_readback": "readonly._run_readback",
    "run_protection_status": "readonly._run_protection_status",
    "run_protection_set": "readonly._run_protection_set",
    "run_clear_protection": "readonly._run_clear_protection",
    "run_identify": "readonly._run_identify",
    "run_snapshot": "readonly._run_snapshot",
    "run_snapshot_diff": "readonly._run_snapshot_diff",
    "run_hardware_report": "readonly._run_hardware_report",
    "run_restore_from_snapshot": "_run_restore_from_snapshot",
    "run_log": "readonly._run_log",
    "run_doctor": "inspection._run_doctor",
    "run_capabilities": "inspection._run_capabilities",
    "run_safety_inspect": "inspection._run_safety_inspect",
    "run_worker": "inspection._run_worker",
    "run_output_plan": "output_run._run_output_plan",
    "run_core_trigger": "_run_core_trigger",
    "run_sequence_command": "_run_sequence",
    "run_ramp_list_command": "sequence_run._run_ramp_list",
}


ROOT_COMMAND_HANDLERS = {
    ("list-resources",): discovery._run_list_resources,
    ("verify",): discovery._run_verify,
    ("clear",): discovery._run_clear,
    ("error",): discovery._run_error,
    ("measure",): discovery._run_measure,
    ("measure-all",): discovery._run_measure_all,
    ("read-status",): readonly._run_status,
    ("validate-readonly",): readonly._run_validate_readonly,
    ("readback",): readonly._run_readback,
    ("protection-status",): readonly._run_protection_status,
    ("protection-set",): readonly._run_protection_set,
    ("clear-protection",): readonly._run_clear_protection,
    ("identify",): readonly._run_identify,
    ("snapshot",): readonly._run_snapshot,
    ("snapshot-diff",): readonly._run_snapshot_diff,
    ("hardware-report",): readonly._run_hardware_report,
    ("restore-from-snapshot",): cli._run_restore_from_snapshot,
    ("log",): readonly._run_log,
    ("doctor",): inspection._run_doctor,
    ("capabilities",): inspection._run_capabilities,
    ("safety", "inspect"): inspection._run_safety_inspect,
    ("worker",): inspection._run_worker,
}


FAMILY_HANDLER_BINDINGS = (
    (
        "output",
        output_commands,
        "run_output_plan",
        output_commands.run_output,
        output_run._run_output_plan,
        (
            ("set",),
            ("output-on",),
            ("output-off",),
            ("safe-off",),
            ("output-state",),
            ("cycle-output",),
            ("apply",),
            ("ramp",),
            ("smoke-output",),
        ),
        ("set", "--channel", "1"),
    ),
    (
        "trigger",
        trigger_commands,
        "run_core_trigger",
        trigger_commands.run_trigger,
        cli._run_core_trigger,
        (
            ("trigger-pulse",),
            ("trigger-status",),
            ("trigger-step",),
            ("trigger-list",),
            ("trigger-fire",),
            ("trigger-abort",),
        ),
        ("trigger-status",),
    ),
    (
        "sequence",
        sequence_commands,
        "run_sequence_command",
        sequence_commands.run_sequence,
        cli._run_sequence,
        (("sequence",),),
        ("sequence", "--file", "sequence.yaml"),
    ),
    (
        "ramp_list",
        ramp_list_commands,
        "run_ramp_list_command",
        ramp_list_commands.run_ramp_list,
        sequence_run._run_ramp_list,
        (("ramp-list",),),
        ("ramp-list", "--segment", "1", "0.1", "0", "1", "0.1", "100", "0"),
    ),
)


FAMILY_REGISTRATION_BINDINGS = {
    "output_commands": "run_output_plan",
    "trigger_commands": "run_core_trigger",
    "sequence_command": "run_sequence_command",
    "ramp_list_command": "run_ramp_list_command",
}


def _parser_for_path(parser: argparse.ArgumentParser, path: tuple[str, ...]) -> argparse.ArgumentParser:
    current_parser = parser
    for command_name in path:
        subparsers = next(
            (
                action
                for action in current_parser._actions
                if isinstance(action, argparse._SubParsersAction)
            ),
            None,
        )
        assert subparsers is not None, f"No subparsers found while resolving {path!r}."
        assert command_name in subparsers.choices, f"Missing parser path {path!r}."
        current_parser = subparsers.choices[command_name]
    return current_parser


def _function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_cli_parser_primitives_have_one_owner_without_cli_facade_reexports() -> None:
    assert cli.JsonCliArgumentParser is cli_parser.JsonCliArgumentParser
    for name in PARSER_PRIMITIVES:
        if name != "JsonCliArgumentParser":
            assert not hasattr(cli, name)

    source = Path(cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert definitions.isdisjoint(PARSER_PRIMITIVES)


def test_root_parser_construction_has_internal_owner_and_public_facade() -> None:
    assert cli._build_parser is cli_parser.build_parser
    assert cli_parser.build_parser.__module__ == "powers_tool_cli.cli_parser"

    parser = cli.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert set(subparsers.choices) == cli.COMMAND_NAMES


def test_command_family_modules_use_explicit_callbacks_without_runtime_locator() -> None:
    root = Path(__file__).resolve().parents[2]
    banned_names = {"runtime", "module", "namespace", "registry", "mapping", "container"}
    for (
        module_name,
        family_module,
        callback_name,
        adapter,
        _,
        _,
        _,
    ) in FAMILY_HANDLER_BINDINGS:
        source = (root / "src" / "powers_tool_cli" / "commands" / f"{module_name}.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        registration = _function_node(tree, "register_commands")
        adapter_node = _function_node(tree, adapter.__name__)

        registration_signature = inspect.signature(family_module.register_commands)
        assert [
            parameter.name
            for parameter in registration_signature.parameters.values()
            if parameter.kind != inspect.Parameter.KEYWORD_ONLY
        ] == ["subparsers"]
        assert registration_signature.parameters[callback_name].kind == inspect.Parameter.KEYWORD_ONLY
        assert {
            parameter.name
            for parameter in registration_signature.parameters.values()
            if parameter.kind == inspect.Parameter.KEYWORD_ONLY
        } == {callback_name}

        adapter_signature = inspect.signature(adapter)
        assert [
            parameter.name
            for parameter in adapter_signature.parameters.values()
            if parameter.kind != inspect.Parameter.KEYWORD_ONLY
        ] == ["args"]
        assert adapter_signature.parameters[callback_name].kind == inspect.Parameter.KEYWORD_ONLY
        assert {
            parameter.name
            for parameter in adapter_signature.parameters.values()
            if parameter.kind == inspect.Parameter.KEYWORD_ONLY
        } == {callback_name}

        for signature in (registration_signature, adapter_signature):
            assert not any(
                parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                for parameter in signature.parameters.values()
            )
            assert banned_names.isdisjoint(signature.parameters)

        assert not any(
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "args"
            and node.attr == "_runtime"
            for node in ast.walk(tree)
        )
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"getattr", "setattr"}
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "args"
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "_runtime"
            for node in ast.walk(tree)
        )
        assert not any(
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "sys"
            and node.value.attr == "modules"
            and isinstance(node.slice, ast.Name)
            and node.slice.id == "__name__"
            for node in ast.walk(tree)
        )
        assert registration.name == "register_commands"
        assert adapter_node.name == adapter.__name__


def test_cli_parser_import_does_not_load_cli_or_worker() -> None:
    root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """\
        import sys
        sys.path.insert(0, r"{source}")
        import powers_tool_cli.cli_parser
        assert "powers_tool_cli.cli" not in sys.modules
        assert "powers_tool_cli.worker" not in sys.modules
        """
    ).format(source=root / "src")

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_parser_build_parser_signature_has_no_whole_module_dependency() -> None:
    sig = inspect.signature(cli_parser.build_parser)
    params = list(sig.parameters.values())

    assert params[0].name == "version_provider"
    assert params[0].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert [param.name for param in params if param.kind != inspect.Parameter.KEYWORD_ONLY] == [
        "version_provider"
    ]
    assert not any(
        param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        for param in params
    )

    kw_only_params = [p for p in params if p.kind == inspect.Parameter.KEYWORD_ONLY]
    assert {param.name for param in kw_only_params} == set(PARSER_RUNNER_BINDINGS)

    banned_names = {"runtime", "module", "namespace", "runners", "registry", "mapping", "container", "context"}
    for param in params:
        assert param.name not in banned_names, f"Banned parameter '{param.name}' found in signature."


def test_cli_build_parser_does_not_pass_whole_module() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Find the def build_parser() function definition
    build_parser_node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_parser"
    )

    # Find the _build_parser(...) call inside it
    class CallVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.calls: list[ast.Call] = []
        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name) and node.func.id == "_build_parser":
                self.calls.append(node)
            self.generic_visit(node)

    visitor = CallVisitor()
    visitor.visit(build_parser_node)
    assert len(visitor.calls) == 1, "Expected exactly one call to '_build_parser' inside 'build_parser'."
    call = visitor.calls[0]

    assert len(call.args) == 1
    assert not any(isinstance(arg, ast.Starred) for arg in call.args)
    assert isinstance(call.args[0], ast.Name)
    assert call.args[0].id == "_package_version"
    assert all(keyword.arg is not None for keyword in call.keywords)
    assert len(call.keywords) == len(PARSER_RUNNER_BINDINGS)
    assert {keyword.arg for keyword in call.keywords} == set(PARSER_RUNNER_BINDINGS)
    for keyword in call.keywords:
        assert keyword.arg is not None
        assert ast.unparse(keyword.value) == PARSER_RUNNER_EXPRESSIONS[keyword.arg]


def test_cli_parser_registers_each_family_with_its_explicit_callback() -> None:
    source = Path(cli_parser.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    build_parser_node = _function_node(tree, "build_parser")
    calls: dict[str, list[ast.Call]] = {}
    for node in ast.walk(build_parser_node):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.attr == "register_commands"
            and node.func.value.id in FAMILY_REGISTRATION_BINDINGS
        ):
            calls.setdefault(node.func.value.id, []).append(node)

    assert set(calls) == set(FAMILY_REGISTRATION_BINDINGS)
    for module_name, callback_name in FAMILY_REGISTRATION_BINDINGS.items():
        assert len(calls[module_name]) == 1
        call = calls[module_name][0]
        assert len(call.args) == 1
        assert isinstance(call.args[0], ast.Name)
        assert call.args[0].id == "subparsers"
        assert all(keyword.arg is not None for keyword in call.keywords)
        assert [keyword.arg for keyword in call.keywords] == [callback_name]
        assert isinstance(call.keywords[0].value, ast.Name)
        assert call.keywords[0].value.id == callback_name


def test_cli_parser_commands_point_to_original_callables() -> None:
    parser = cli.build_parser()
    for path, expected_handler in ROOT_COMMAND_HANDLERS.items():
        parser_for_path = _parser_for_path(parser, path)
        assert parser_for_path.get_default("func") is expected_handler


def test_family_registration_binds_one_shared_callback_handler() -> None:
    for (
        _,
        family_module,
        callback_name,
        adapter,
        _,
        paths,
        representative_argv,
    ) in FAMILY_HANDLER_BINDINGS:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command", required=True)
        received_args: list[argparse.Namespace] = []

        def fake_callback(args: argparse.Namespace) -> int:
            received_args.append(args)
            return 37

        with pytest.raises(TypeError):
            family_module.register_commands(subparsers)

        family_module.register_commands(subparsers, **{callback_name: fake_callback})
        handler = _parser_for_path(parser, paths[0]).get_default("func")
        assert isinstance(handler, partial)
        assert handler.func is adapter
        assert handler.keywords == {callback_name: fake_callback}
        for path in paths:
            assert _parser_for_path(parser, path).get_default("func") is handler

        args = parser.parse_args(representative_argv)
        assert args.func is handler
        assert not hasattr(args, "_runtime")
        assert callback_name not in vars(args)
        assert args.func(args) == 37
        assert received_args == [args]


def test_cli_build_parser_binds_each_family_handler_to_its_cli_runner() -> None:
    parser = cli.build_parser()
    for (
        _,
        _,
        callback_name,
        adapter,
        cli_runner,
        paths,
        _,
    ) in FAMILY_HANDLER_BINDINGS:
        handler = _parser_for_path(parser, paths[0]).get_default("func")
        assert isinstance(handler, partial)
        assert handler.func is adapter
        assert handler.keywords == {callback_name: cli_runner}


def test_cli_main_does_not_add_runtime_to_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_args: argparse.Namespace | None = None

    def mock_doctor(args_obj: argparse.Namespace) -> int:
        nonlocal captured_args
        captured_args = args_obj
        return 0

    monkeypatch.setattr(inspection, "_run_doctor", mock_doctor)

    assert cli.main(["doctor", "--simulate", "--json"]) == 0
    assert captured_args is not None
    assert not hasattr(captured_args, "_runtime")


def test_cli_main_does_not_set_runtime_locator() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    main_node = _function_node(tree, "main")

    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "setattr"
        and len(node.args) >= 2
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "args"
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "_runtime"
        for node in ast.walk(main_node)
    )
