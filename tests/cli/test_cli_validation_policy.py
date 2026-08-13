import json
import csv
from types import SimpleNamespace

import pytest

import powers_tool_core.connection as connection
import powers_tool_cli.cli as cli
from powers_tool_core.core import CommandCancelled, CoreExecutionError, StopCleanupError
from powers_tool_core.errors import VisaConnectionError

from tests.cli.cli_test_helpers import (
    OUTPUT_RESOURCE,
    SERIAL_TERMINATION_ARGS,
    WRITE_VERIFICATION_REQUEST_DEFAULTS,
    FakeSession,
    assert_live_scope_rejected,
    expected_idn,
    expected_resource,
    output_command_args,
    write_safety_config,
)

@pytest.mark.parametrize(
    "argv",
    [
        ["protection-status", "--json", "--resource", "GPIB0::1::INSTR"],
        ["snapshot", "--json", "--resource", "GPIB0::1::INSTR"],
        ["output-on", "--json", "--resource", "ASRL1::INSTR", "--channel", "1"],
        ["trigger-pulse", "--json", "--resource", "ASRL1::INSTR", "--pin", "1"],
    ],
)
def test_live_policy_rejections_use_stable_validation_code(monkeypatch, capsys, argv) -> None:
    session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)

    assert cli.main(argv) == 2

    assert_live_scope_rejected(json.loads(capsys.readouterr().out), session)

def test_hidden_validation_mode_is_parser_only_and_allows_registered_pending_scope(monkeypatch, capsys) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "measure",
            "--resource",
            "TCPIP0::192.0.2.1::INSTR",
            "--channel",
            "1",
            "--validation-allow-pending-live-support",
        ]
    )
    assert args.validation_allow_pending_live_support is True

    with pytest.raises(SystemExit):
        parser.parse_args(["measure", "--help"])
    assert "--validation-allow-pending-live-support" not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    assert "--validation-allow-pending-live-support" not in capsys.readouterr().out

    product_session = FakeSession(idn="KEYSIGHT,E36312A,SERIAL0000,1.0")
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: product_session)
    assert (
        cli.main(
            [
                "measure",
                "--json",
                "--resource",
                "TCPIP0::192.0.2.1::INSTR",
                "--backend",
                "@py",
                "--channel",
                "1",
            ]
        )
        == 2
    )
    assert_live_scope_rejected(json.loads(capsys.readouterr().out), product_session)

    session = FakeSession(
        idn="KEYSIGHT,E36312A,SERIAL0000,1.0",
        query_responses={"MEAS:VOLT?": "1.0", "MEAS:CURR?": "0.05"},
    )
    monkeypatch.setattr(cli, "open_resource", lambda *args, **kwargs: session)
    assert (
        cli.main(
            [
                "measure",
                "--json",
                "--resource",
                "TCPIP0::192.0.2.1::INSTR",
                "--backend",
                "@py",
                "--channel",
                "1",
                "--validation-allow-pending-live-support",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert session.queries == ["*IDN?", "MEAS:VOLT?", "MEAS:CURR?"]

def test_hidden_validation_mode_keeps_no_hardware_feature_locks(monkeypatch, capsys) -> None:
    def fail_open_resource(*args, **kwargs):
        raise AssertionError("dry-run must not open VISA")

    monkeypatch.setattr(cli, "open_resource", fail_open_resource)
    assert (
        cli.main(
            [
                "trigger-step",
                "--dry-run",
                "--model",
                "keysight-edu36311a",
                "--resource",
                OUTPUT_RESOURCE,
                "--channel",
                "1",
                "--source",
                "bus",
                "--validation-allow-pending-live-support",
                "--json",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "validation"

@pytest.mark.parametrize(
    "argv",
    [
        ["measure", "--resource", OUTPUT_RESOURCE, "--channel", "1"],
        ["read-status", "--resource", OUTPUT_RESOURCE],
        ["set", "--resource", OUTPUT_RESOURCE, "--channel", "1", "--voltage", "1", "--current", "0.1"],
        ["protection-status", "--resource", OUTPUT_RESOURCE],
        ["snapshot", "--resource", OUTPUT_RESOURCE],
        ["restore-from-snapshot", "--resource", OUTPUT_RESOURCE, "--snapshot", "snapshot.json", "--channel", "1"],
        ["trigger-abort", "--resource", OUTPUT_RESOURCE, "--channel", "1"],
        ["ramp-list", "--resource", OUTPUT_RESOURCE, "--segment", "1", "0.1", "0", "0.5", "0.5", "0", "0"],
        ["sequence", "--resource", OUTPUT_RESOURCE, "--file", "sequence.yaml"],
        ["doctor", "--resource", OUTPUT_RESOURCE],
        ["capabilities", "--resource", OUTPUT_RESOURCE],
    ],
)
def test_hidden_validation_argument_is_accepted_and_suppressed_for_each_parser_family(capsys, argv) -> None:
    parser = cli.build_parser()
    args = parser.parse_args([*argv, "--validation-allow-pending-live-support"])
    assert args.validation_allow_pending_live_support is True

    with pytest.raises(SystemExit):
        parser.parse_args([argv[0], "--help"])
    assert "--validation-allow-pending-live-support" not in capsys.readouterr().out

@pytest.mark.parametrize(
    ("argv", "builder"),
    [
        (["set", "--resource", OUTPUT_RESOURCE, "--channel", "1", "--voltage", "1", "--current", "0.1"], cli._operation_request_for_args),
        (["read-status", "--resource", OUTPUT_RESOURCE], cli._target_core_request_for_args),
        (["trigger-abort", "--resource", OUTPUT_RESOURCE, "--channel", "1"], cli._trigger_request_for_args),
        (["ramp-list", "--resource", OUTPUT_RESOURCE, "--segment", "1", "0.1", "0", "0.5", "0.5", "0", "0"], cli._ramp_list_request_for_args),
        (["sequence", "--resource", OUTPUT_RESOURCE, "--file", "sequence.yaml"], cli._sequence_request_for_args),
    ],
)
@pytest.mark.parametrize("hidden", [False, True])
def test_cli_request_builders_propagate_only_policy_mode(argv, builder, hidden: bool) -> None:
    parser = cli.build_parser()
    args = parser.parse_args([*argv, *(["--validation-allow-pending-live-support"] if hidden else [])])
    request = builder(args)

    assert request.runtime.support_policy_mode == ("validation" if hidden else "product")
    assert "validation_allow_pending_live_support" not in request.parameters

def test_restore_request_propagates_validation_mode_without_public_request_parameter(monkeypatch, capsys) -> None:
    captured = {}

    def fake_run_restore(request, **kwargs):
        captured["request"] = request
        return {"resource": request.runtime.resource, "restored_channels": [1], "plan": {}}

    monkeypatch.setattr(cli.restore_core, "run_restore", fake_run_restore)
    assert (
        cli.main(
            [
                "restore-from-snapshot",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--snapshot",
                "snapshot.json",
                "--channel",
                "1",
                "--confirm",
                "--validation-allow-pending-live-support",
            ]
        )
        == 0
    )
    request = captured["request"]
    assert request.runtime.support_policy_mode == "validation"
    assert "validation_allow_pending_live_support" not in request.parameters
    payload = json.loads(capsys.readouterr().out)
    assert "validation_allow_pending_live_support" not in json.dumps(payload)

def test_restore_json_preserves_observed_identity_from_core(monkeypatch, capsys) -> None:
    reported_identity = {
        "manufacturer": "Keysight Technologies",
        "model": "E36312A",
        "serial": "SN",
        "firmware": "2.10",
        "parse_ok": True,
    }
    resolved_identity = {
        "vendor_id": "keysight",
        "model_id": "keysight-e36312a",
        "model_name": "E36312A",
        "display_name": "Keysight E36312A",
    }

    monkeypatch.setattr(
        cli.restore_core,
        "run_restore",
        lambda request, **kwargs: {
            "resource": request.runtime.resource,
            "restored_channels": [1],
            "plan": {},
            "reported_identity": reported_identity,
            "resolved_identity": resolved_identity,
        },
    )

    assert (
        cli.main(
            [
                "restore-from-snapshot",
                "--json",
                "--resource",
                OUTPUT_RESOURCE,
                "--snapshot",
                "snapshot.json",
                "--channel",
                "1",
                "--confirm",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["reported_identity"] == reported_identity
    assert payload["data"]["resolved_identity"] == resolved_identity
