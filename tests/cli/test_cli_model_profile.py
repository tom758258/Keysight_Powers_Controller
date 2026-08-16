import json
from pathlib import Path

import pytest

import powers_tool_cli.cli as cli
import powers_tool_cli.cli_request as cli_request
from powers_tool_cli.commands import output_run


GENERIC_PLANNING_COMMANDS = (
    "set",
    "output-on",
    "output-off",
    "safe-off",
    "output-state",
    "cycle-output",
    "apply",
    "ramp",
    "ramp-list",
    "smoke-output",
    "sequence",
)


class FakeLiveSession:
    def __init__(self, idn: str) -> None:
        self.idn = idn
        self.queries: list[str] = []
        self.writes: list[str] = []
        self.closed = False

    def __enter__(self) -> "FakeLiveSession":
        return self

    def __exit__(self, *args: object) -> None:
        self.closed = True

    def query(self, command: str) -> str:
        self.queries.append(command)
        if command == "*IDN?":
            return self.idn
        if command == "INST:NSEL?":
            return "1"
        if command == "SYST:ERR?":
            return '0,"No error"'
        raise AssertionError(f"unexpected query {command!r}")

    def write(self, command: str) -> None:
        self.writes.append(command)


def _parse(argv: list[str]):
    return cli.build_parser().parse_args(argv)


@pytest.mark.parametrize("command", GENERIC_PLANNING_COMMANDS)
def test_generic_planning_commands_expose_profile_help(command: str, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _parse([command, "--help"])

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--model" in help_text
    assert "--profile" in help_text
    assert "generic-scpi" in help_text


@pytest.mark.parametrize(
    "command",
    ("trigger-step", "trigger-list", "protection-set", "clear-protection"),
)
def test_model_specific_commands_do_not_expose_generic_profile(command: str, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _parse([command, "--help"])

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--model" in help_text
    assert "--profile" not in help_text


@pytest.mark.parametrize(
    ("argv", "builder"),
    [
        (
            ["set", "--dry-run", "--model", "keysight-e3646a", "--channel", "1", "--voltage", "1"],
            cli_request._operation_request_for_args,
        ),
        (
            ["sequence", "--dry-run", "--model", "keysight-e36312a", "--file", "sequence.json"],
            cli_request._sequence_request_for_args,
        ),
        (
            ["ramp-list", "--dry-run", "--model", "keysight-e3646a", "--file", "ramp.json"],
            cli_request._ramp_list_request_for_args,
        ),
        (
            ["trigger-step", "--dry-run", "--model", "keysight-e36312a", "--channel", "1", "--source", "bus", "--fire"],
            cli_request._trigger_request_for_args,
        ),
    ],
)
def test_dry_run_model_maps_to_planning_model_id(argv, builder) -> None:
    request = builder(_parse(argv))

    assert request.runtime.planning_model_id == argv[argv.index("--model") + 1]
    assert request.runtime.expected_model_id is None
    assert request.runtime.planning_profile_id is None


def test_simulator_model_maps_to_planning_model_id() -> None:
    args = _parse(
        [
            "set",
            "--simulate",
            "--model",
            "keysight-e36312a",
            "--channel",
            "1",
            "--voltage",
            "1",
        ]
    )

    runtime = cli_request._operation_request_for_args(args).runtime
    assert runtime.planning_model_id == "keysight-e36312a"
    assert runtime.expected_model_id is None


def test_live_model_maps_to_expected_model_id() -> None:
    args = _parse(
        [
            "set",
            "--model",
            "keysight-e36312a",
            "--resource",
            "USB0::FAKE::INSTR",
            "--channel",
            "1",
            "--voltage",
            "1",
        ]
    )

    runtime = cli_request._operation_request_for_args(args).runtime
    assert runtime.expected_model_id == "keysight-e36312a"
    assert runtime.planning_model_id is None
    assert runtime.planning_profile_id is None


def test_dry_run_profile_maps_to_planning_profile_id() -> None:
    args = _parse(
        [
            "set",
            "--dry-run",
            "--profile",
            "generic-scpi",
            "--channel",
            "1",
            "--voltage",
            "1",
        ]
    )

    runtime = cli_request._operation_request_for_args(args).runtime
    assert runtime.planning_profile_id == "generic-scpi"
    assert runtime.planning_model_id is None
    assert runtime.expected_model_id is None


@pytest.mark.parametrize(
    "argv",
    [
        ["set", "--model", "E36312A", "--resource", "USB0::FAKE::INSTR", "--channel", "1", "--voltage", "1"],
        ["set", "--dry-run", "--model", "E36312A", "--channel", "1", "--voltage", "1"],
        ["set", "--dry-run", "--model", "GENERIC", "--channel", "1", "--voltage", "1"],
        ["set", "--profile", "generic-scpi", "--resource", "USB0::FAKE::INSTR", "--channel", "1", "--voltage", "1"],
        ["set", "--simulate", "--profile", "generic-scpi", "--channel", "1", "--voltage", "1"],
        ["set", "--dry-run", "--model", "keysight-e36312a", "--profile", "generic-scpi", "--channel", "1", "--voltage", "1"],
    ],
)
def test_invalid_cli_identity_combinations_fail_as_validation(capsys, argv) -> None:
    assert cli.main([*argv, "--json"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["type"] == "validation"
    assert payload["error"]["code"] == "argument_error"


def test_live_expected_model_mismatch_stops_after_idn(monkeypatch, capsys) -> None:
    session = FakeLiveSession("Agilent Technologies,E3646A,SERIAL0000,1.0")
    monkeypatch.setattr(output_run, "_open_resource", lambda *args, **kwargs: session)

    assert (
        cli.main(
            [
                "set",
                "--json",
                "--model",
                "keysight-e36312a",
                "--resource",
                "USB0::FAKE::INSTR",
                "--channel",
                "1",
                "--voltage",
                "1",
            ]
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert "Expected model_id keysight-e36312a" in payload["error"]["message"]
    assert session.queries == ["*IDN?"]
    assert session.writes == []


def test_validation_switch_remains_hidden_and_orthogonal(capsys) -> None:
    with pytest.raises(SystemExit):
        _parse(["set", "--help"])
    assert "validation-allow-pending-live-support" not in capsys.readouterr().out

    args = _parse(
        [
            "set",
            "--dry-run",
            "--model",
            "keysight-e36312a",
            "--validation-allow-pending-live-support",
            "--channel",
            "1",
            "--voltage",
            "1",
        ]
    )
    request = cli_request._operation_request_for_args(args)
    assert request.runtime.planning_model_id == "keysight-e36312a"
    assert request.runtime.support_policy_mode == "validation"


def test_only_v2_console_entry_points_are_declared() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'powers-tool = "powers_tool_cli.cli:main"' in pyproject
    assert 'powers-tool-webui = "powers_tool_webui.server:main"' in pyproject
    assert 'powers-tool-webui-launcher = "powers_tool_webui.launcher:main"' in pyproject
    assert "keysight-power =" not in pyproject
