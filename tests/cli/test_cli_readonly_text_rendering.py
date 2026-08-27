from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

import pytest

import powers_tool_cli.cli as cli
from powers_tool_cli import cli_rendering


SIM_RESOURCE = "USB0::SIM::E36312A::INSTR"


def _value_to_text(value: object) -> str:
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value)


@pytest.mark.parametrize(
    ("resources", "live_only", "expected"),
    [
        ([], False, ("No VISA resources found.",)),
        (
            [{"name": "USB0::A::INSTR"}, {"name": "TCPIP0::B::INSTR"}],
            False,
            ("USB0::A::INSTR", "TCPIP0::B::INSTR"),
        ),
        ([], True, ("Live resources:", "  <none>")),
        (
            [
                {"name": "USB0::A::INSTR", "idn": {"raw": "KEYSIGHT,A,1,1"}},
                {"name": "TCPIP0::B::INSTR", "idn": {"raw": "KEYSIGHT,B,2,1"}},
            ],
            True,
            (
                "Live resources:",
                "  USB0::A::INSTR",
                "    IDN: KEYSIGHT,A,1,1",
                "  TCPIP0::B::INSTR",
                "    IDN: KEYSIGHT,B,2,1",
            ),
        ),
    ],
)
def test_format_list_resources_preserves_exact_lines_and_inputs(
    resources: list[dict[str, Any]],
    live_only: bool,
    expected: tuple[str, ...],
) -> None:
    before = deepcopy(resources)

    result = cli_rendering.format_list_resources(resources, live_only=live_only)

    assert result == expected
    assert result is not cli_rendering.format_list_resources(resources, live_only=live_only)
    assert resources == before


def test_format_discovery_and_readonly_results_preserve_exact_lines_and_inputs() -> None:
    measurements = {"voltage": 1.0, "current": 0.05}
    channels = [
        {"channel": 2, "measurements": {"voltage": 2.2, "current": 0.22}},
        {"channel": 1, "measurements": {"voltage": 1.1, "current": 0.11}},
    ]
    readback_channels = [
        {"channel": 2, "setpoints": {"voltage": 2.0, "current": 0.2}},
        {"channel": 1, "setpoints": {"voltage": 1.0, "current": 0.1}},
    ]
    protection_data = {
        "resource": SIM_RESOURCE,
        "protection": {"over_voltage_tripped": True, "over_current_tripped": False},
        "outputs": [
            {"channel": 2, "enabled": False, "disabled_with_protection": True},
            {"channel": 1, "enabled": True, "disabled_with_protection": False},
        ],
    }
    identify_data = {
        "idn": {"raw": "KEYSIGHT,E36312A,SIM000003,1.0"},
        "options": ["OPT2", "OPT1"],
        "scpi_version": "1999.0",
        "remote_lockout_state": "RWLock",
    }
    before = deepcopy((measurements, channels, readback_channels, protection_data, identify_data))

    assert cli_rendering.format_verify("KEYSIGHT,E36312A,SIM000003,1.0") == (
        "KEYSIGHT,E36312A,SIM000003,1.0",
    )
    assert cli_rendering.format_error_queue([]) == ("No instrument errors.",)
    assert cli_rendering.format_error_queue(['-100,"Command error"']) == ('-100,"Command error"',)
    assert cli_rendering.format_measure(measurements, value_to_text=_value_to_text) == (
        "Voltage: 1 V",
        "Current: 0.05 A",
    )
    assert cli_rendering.format_measure_all(channels, value_to_text=_value_to_text) == (
        "Channel 2: 2.2 V, 0.22 A",
        "Channel 1: 1.1 V, 0.11 A",
    )
    assert cli_rendering.format_read_status(
        ['-100,"Command error"'],
        [{"channel": 2, "enabled": False}, {"channel": 1, "enabled": True}],
    ) == (
        'Error: -100,"Command error"',
        "Channel 2: Output enabled: false",
        "Channel 1: Output enabled: true",
    )
    assert cli_rendering.format_read_status([], []) == ("Errors: none",)
    assert cli_rendering.format_readback(
        SIM_RESOURCE,
        readback_channels,
        value_to_text=_value_to_text,
    ) == (
        f"Resource: {SIM_RESOURCE}",
        "Channel 2: 2 V, 0.2 A",
        "Channel 1: 1 V, 0.1 A",
    )
    assert cli_rendering.format_protection_status(protection_data) == (
        f"Resource: {SIM_RESOURCE}",
        "Over-voltage tripped: true",
        "Over-current tripped: false",
        "Channel 2: Output enabled: false, disabled with protection: true",
        "Channel 1: Output enabled: true, disabled with protection: false",
    )
    assert cli_rendering.format_identify(SIM_RESOURCE, identify_data) == (
        f"Resource: {SIM_RESOURCE}",
        "IDN: KEYSIGHT,E36312A,SIM000003,1.0",
        "Options: ['OPT2', 'OPT1']",
        "SCPI version: 1999.0",
        "Remote/local state: RWLock",
    )
    assert (measurements, channels, readback_channels, protection_data, identify_data) == before


def test_format_inspection_results_preserve_exact_lines_and_inputs() -> None:
    validate_data = {
        "resource": {"name": SIM_RESOURCE, "idn": {"model": "E36312A"}},
        "driver": {"class": "E36312APowerSupply", "reason": "reported identity"},
        "hardware_validation": {"read_only": True},
        "errors": ['-100,"Command error"'],
        "outputs": [{"channel": 2, "enabled": False}, {"channel": 1, "enabled": True}],
        "readback": [
            {"channel": 2, "setpoints": {"voltage": 2.0, "current": 0.2}},
            {"channel": 1, "setpoints": {"voltage": 1.0, "current": 0.1}},
        ],
        "measurements": [
            {"channel": 2, "measurements": {"voltage": 2.2, "current": 0.22}},
            {"channel": 1, "measurements": {"voltage": 1.1, "current": 0.11}},
        ],
    }
    snapshot_data = {
        "resource": "<redacted>",
        "reported_identity": {"manufacturer": "KEYSIGHT", "model": "E36312A", "serial": "SIM000003"},
        "resolved_identity": {"model_id": "keysight-e36312a", "display_name": "Keysight E36312A"},
        "errors": [],
        "outputs": [{"channel": 2, "enabled": False}, {"channel": 1, "enabled": True}],
    }
    diff_data = {
        "changed": True,
        "change_count": 2,
        "differences": [
            {"category": "output", "channel": 2, "field": "enabled", "before": False, "after": True},
            {"category": "identity", "field": "serial", "before": "A", "after": "B"},
        ],
        "summary": {"identity": 1, "output": 1},
    }
    doctor_data = {
        "python": {"version": "3.13.0"},
        "package": {"version": "2.0.0"},
        "simulator": {"resources": ["SIM1", "SIM2"]},
    }
    capabilities_data = {"driver": {"class": "E36312APowerSupply"}, "channels": [2, 1]}
    safety_data = {
        "resource": SIM_RESOURCE,
        "limits": {"max_voltage": 3.3, "allowed_channels": [1, 2]},
        "output_affecting_allowed": False,
    }
    before = deepcopy((validate_data, snapshot_data, diff_data, doctor_data, capabilities_data, safety_data))

    assert cli_rendering.format_validate_readonly(
        validate_data,
        channel_order=(1, 2),
        value_to_text=_value_to_text,
    ) == (
        f"Resource: {SIM_RESOURCE}",
        "Model: E36312A",
        "Driver: E36312APowerSupply (reported identity)",
        "Validation read-only: True",
        "Errors: 1",
        "Channel 1: output=true, set=1 V/0.1 A, meas=1.1 V/0.11 A",
        "Channel 2: output=false, set=2 V/0.2 A, meas=2.2 V/0.22 A",
    )
    no_identity_data = deepcopy(validate_data)
    no_identity_data["resource"]["idn"] = None
    assert cli_rendering.format_validate_readonly(
        no_identity_data,
        channel_order=(),
        value_to_text=_value_to_text,
    )[1] == "Model: None"
    assert cli_rendering.format_snapshot(
        snapshot_data,
        comparison={"passed": False},
    ) == (
        "Resource: <redacted>",
        "Model: Keysight E36312A",
        "Reported manufacturer: KEYSIGHT",
        "Reported model: E36312A",
        "Serial: SIM000003",
        "Errors: 0",
        "Channel 2: Output enabled: false",
        "Channel 1: Output enabled: true",
        "Snapshot comparison passed: false",
    )
    assert cli_rendering.format_snapshot(snapshot_data, comparison=None)[-1] == "Channel 1: Output enabled: true"
    assert cli_rendering.format_snapshot_diff(diff_data, summary=False) == (
        "Changed: true",
        "Changes: 2",
        "output channel 2 enabled: False -> True",
        "identity serial: A -> B",
    )
    assert cli_rendering.format_snapshot_diff(diff_data, summary=True) == (
        "Changed: true",
        "Changes: 2",
        "identity: 1",
        "output: 1",
    )
    assert cli_rendering.format_doctor(doctor_data, pyvisa_available=True) == (
        "Python: 3.13.0",
        "Package: 2.0.0",
        "PyVISA: true",
        "Simulator resources: 2",
    )
    assert cli_rendering.format_capabilities(capabilities_data) == (
        "Driver: E36312APowerSupply",
        "Channels: 2, 1",
    )
    assert cli_rendering.format_capabilities(
        {"driver": {"class": "GenericScpiPowerSupply"}, "channels": []}
    ) == ("Driver: GenericScpiPowerSupply", "Channels: ")
    assert cli_rendering.format_safety_inspect(safety_data) == (
        f"Resource: {SIM_RESOURCE}",
        "Limits: {'max_voltage': 3.3, 'allowed_channels': [1, 2]}",
        "Output allowed: false",
    )
    assert (validate_data, snapshot_data, diff_data, doctor_data, capabilities_data, safety_data) == before


def test_direct_formatters_do_not_write_streams(capsys) -> None:
    cli_rendering.format_list_resources([], live_only=False)
    cli_rendering.format_verify("IDN")
    cli_rendering.format_error_queue([])
    cli_rendering.format_measure({"voltage": 1.0, "current": 0.1}, value_to_text=_value_to_text)
    cli_rendering.format_measure_all([], value_to_text=_value_to_text)
    cli_rendering.format_read_status([], [])
    cli_rendering.format_readback("resource", [], value_to_text=_value_to_text)
    cli_rendering.format_protection_status(
        {"resource": "resource", "protection": {"over_voltage_tripped": False, "over_current_tripped": False}, "outputs": []}
    )
    cli_rendering.format_identify("resource", {"idn": {"raw": "IDN"}, "options": None, "scpi_version": None, "remote_lockout_state": None})
    cli_rendering.format_validate_readonly(
        {"resource": {"name": "resource", "idn": None}, "driver": {"class": "Driver", "reason": "reason"}, "hardware_validation": {"read_only": True}, "errors": [], "outputs": [], "readback": [], "measurements": []},
        channel_order=(),
        value_to_text=_value_to_text,
    )
    cli_rendering.format_snapshot(
        {"resource": "resource", "reported_identity": {"manufacturer": "maker", "model": "model", "serial": "serial"}, "resolved_identity": {"model_id": "model"}, "errors": [], "outputs": []},
        comparison=None,
    )
    cli_rendering.format_snapshot_diff({"changed": False, "change_count": 0, "differences": [], "summary": {}}, summary=False)
    cli_rendering.format_doctor({"python": {"version": "3"}, "package": {"version": "2"}, "simulator": {"resources": []}}, pyvisa_available=False)
    cli_rendering.format_capabilities({"driver": {"class": "Driver"}, "channels": []})
    cli_rendering.format_safety_inspect({"resource": "resource", "limits": {}, "output_affecting_allowed": False})

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.parametrize(
    ("formatter_name", "argv"),
    [
        ("format_list_resources", ["list-resources", "--simulate"]),
        ("format_verify", ["verify", "--simulate", "--resource", SIM_RESOURCE]),
        ("format_error_queue", ["error", "--simulate", "--resource", SIM_RESOURCE]),
        ("format_measure", ["measure", "--simulate", "--resource", SIM_RESOURCE, "--channel", "1"]),
        ("format_measure_all", ["measure-all", "--simulate", "--resource", SIM_RESOURCE]),
        ("format_read_status", ["read-status", "--simulate", "--resource", SIM_RESOURCE]),
        ("format_readback", ["readback", "--simulate", "--resource", SIM_RESOURCE]),
        ("format_validate_readonly", ["validate-readonly", "--simulate", "--resource", SIM_RESOURCE]),
        ("format_protection_status", ["protection-status", "--simulate", "--resource", SIM_RESOURCE]),
        ("format_identify", ["identify", "--simulate", "--resource", SIM_RESOURCE]),
        ("format_snapshot", ["snapshot", "--simulate", "--resource", SIM_RESOURCE]),
        ("format_doctor", ["doctor", "--simulate"]),
        ("format_capabilities", ["capabilities", "--simulate", "--resource", SIM_RESOURCE]),
        (
            "format_safety_inspect",
            [
                "safety",
                "inspect",
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
def test_readonly_runners_delegate_text_success_and_skip_rendering_for_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    formatter_name: str,
    argv: list[str],
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def sentinel(*args: object, **kwargs: object) -> tuple[str, ...]:
        calls.append((args, kwargs))
        return ("formatter sentinel",)

    monkeypatch.setattr(cli_rendering, formatter_name, sentinel)
    assert cli.main(argv) == 0
    captured = capsys.readouterr()
    assert captured.out == "formatter sentinel\n"
    assert captured.err == ""
    assert calls

    def fail_formatter(*_args: object, **_kwargs: object) -> tuple[str, ...]:
        raise AssertionError("JSON success paths must not invoke text rendering")

    monkeypatch.setattr(cli_rendering, formatter_name, fail_formatter)
    assert cli.main([*argv, "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["schema_version"] == 2
    assert captured.err == ""


def test_snapshot_diff_delegates_text_success_and_skips_rendering_for_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    snapshot_args = ["snapshot", "--simulate", "--resource", SIM_RESOURCE]
    assert cli.main([*snapshot_args, "--snapshot-json", str(before)]) == 0
    capsys.readouterr()
    assert cli.main([*snapshot_args, "--snapshot-json", str(after)]) == 0
    capsys.readouterr()
    argv = ["snapshot-diff", "--before", str(before), "--after", str(after)]

    monkeypatch.setattr(
        cli_rendering,
        "format_snapshot_diff",
        lambda *_args, **_kwargs: ("formatter sentinel",),
    )
    assert cli.main(argv) == 0
    captured = capsys.readouterr()
    assert captured.out == "formatter sentinel\n"
    assert captured.err == ""

    monkeypatch.setattr(
        cli_rendering,
        "format_snapshot_diff",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("JSON success paths must not invoke text rendering")
        ),
    )
    assert cli.main([*argv, "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["schema_version"] == 2
    assert captured.err == ""


def test_success_renderers_are_not_used_for_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_formatter(*_args: object, **_kwargs: object) -> tuple[str, ...]:
        raise AssertionError("validation errors must not invoke success rendering")

    monkeypatch.setattr(cli_rendering, "format_measure", fail_formatter)
    assert cli.main(["measure", "--resource", SIM_RESOURCE, "--channel", "0"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "channel must be a positive integer" in captured.err
