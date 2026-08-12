import pytest

from powers_tool_core.command_runner import run_core_command, validate_request_admission
from powers_tool_core.core import CoreValidationError, RuntimeOptions, SequenceRequest, TriggerRequest, OperationRequest


def test_trigger_step_string_fire_is_rejected() -> None:
    with pytest.raises(CoreValidationError, match="fire"):
        validate_request_admission(TriggerRequest("trigger-step", RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"), {"channel": 1, "fire": "false"}))


def test_log_contract_normalizes_explicit_channels_and_bounds() -> None:
    admitted = validate_request_admission(
        OperationRequest(
            "log",
            RuntimeOptions(simulate=True, planning_model_id="keysight-e36312a"),
            {"channels": [3, 1, 3], "interval_sec": 0.5, "samples": 2},
        )
    )

    assert admitted.parameters == {
        "channels": (3, 1, 3),
        "interval_sec": 0.5,
        "samples": 2,
    }


@pytest.mark.parametrize(
    "parameters",
    [
        {"interval_sec": 1.0, "samples": 1},
        {"channel": 1, "channels": [1], "interval_sec": 1.0, "samples": 1},
        {"channel": 1, "interval_sec": 1.0},
        {"channel": 1, "interval_sec": 1.0, "samples": 1, "duration_sec": 1.0},
        {"channel": 1, "interval_sec": 0, "samples": 1},
        {"channel": 1, "interval_sec": 1.0, "samples": 0},
        {"channel": 1, "interval_sec": 1.0, "duration_sec": 0},
        {"channels": [], "interval_sec": 1.0, "samples": 1},
        {"channels": [0], "interval_sec": 1.0, "samples": 1},
    ],
)
def test_log_contract_rejects_invalid_selectors_and_bounds(parameters: dict) -> None:
    with pytest.raises(CoreValidationError):
        validate_request_admission(
            OperationRequest(
                "log",
                RuntimeOptions(simulate=True, planning_model_id="keysight-e36312a"),
                parameters,
            )
        )


@pytest.mark.parametrize("field", ["csv", "jsonl", "append"])
def test_log_contract_rejects_adapter_owned_fields(field: str) -> None:
    with pytest.raises(CoreValidationError, match=field):
        validate_request_admission(
            OperationRequest(
                "log",
                RuntimeOptions(simulate=True, planning_model_id="keysight-e36312a"),
                {"channel": 1, "interval_sec": 1.0, "samples": 1, field: True},
            )
        )


def test_trigger_list_alias_conflict_is_rejected() -> None:
    with pytest.raises(CoreValidationError, match="alias conflict"):
        validate_request_admission(TriggerRequest("trigger-list", RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"), {"channel": 1, "voltages": [1.0], "voltage_list": [1.0]}))


def test_sequence_wait_shorthand_scalar_is_rejected() -> None:
    request = SequenceRequest("sequence", RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"), {"document": {"version": 1, "steps": [{"wait": 3}]}})
    with pytest.raises(CoreValidationError, match="must contain an object"):
        validate_request_admission(request)


def test_protection_ocp_enum_is_fail_closed() -> None:
    with pytest.raises(CoreValidationError, match="ocp"):
        validate_request_admission(OperationRequest("protection-set", RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"), {"ocp": "disabled"}))


@pytest.mark.parametrize("command", ["trigger-step", "trigger-list"])
def test_trigger_fire_string_false_is_rejected_before_opener(command: str) -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("admission must not open hardware")

    parameters = {"channel": 1, "fire": "false"}
    if command == "trigger-list":
        parameters.update(voltages=[1.0], currents=[0.1], dwell=[0.01], leave_trigger_configured=True)
    with pytest.raises(CoreValidationError, match="fire"):
        run_core_command(TriggerRequest(command, RuntimeOptions(resource="USB0::FAKE::INSTR"), parameters), opener=opener)
    assert opened is False


@pytest.mark.parametrize("field", ["wait_complete", "leave_trigger_configured", "exclusive_pins"])
def test_trigger_boolean_strings_are_rejected_without_wait_or_hardware(field: str) -> None:
    parameters = {"channel": 1, field: "false"}
    command = "trigger-step"
    if field == "exclusive_pins":
        command = "trigger-pulse"
        parameters = {"channel": 1, "pins": [1], field: "false"}
    with pytest.raises(CoreValidationError, match=field):
        validate_request_admission(
            TriggerRequest(command, RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"), parameters)
        )


@pytest.mark.parametrize(
    ("canonical", "alias", "value"),
    [
        ("voltages", "voltage_list", [1.0]),
        ("currents", "current_list", [0.1]),
        ("dwell", "dwell_list", [0.01]),
    ],
)
def test_trigger_list_each_alias_conflict_is_rejected(canonical: str, alias: str, value: list[float]) -> None:
    parameters = {
        "channel": 1,
        "voltages": [1.0],
        "currents": [0.1],
        "dwell": [0.01],
        "leave_trigger_configured": True,
        canonical: value,
        alias: value,
    }
    with pytest.raises(CoreValidationError, match="alias conflict"):
        validate_request_admission(
            TriggerRequest("trigger-list", RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"), parameters)
        )


def test_sequence_action_rejects_another_actions_field() -> None:
    request = SequenceRequest(
        "sequence",
        RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
        {"document": {"version": 1, "steps": [{"action": "wait", "seconds": 1, "voltage": 5.0}]}},
    )
    with pytest.raises(CoreValidationError, match="inapplicable"):
        validate_request_admission(request)


def test_sequence_file_and_document_are_mutually_exclusive() -> None:
    with pytest.raises(CoreValidationError, match="mutually exclusive"):
        validate_request_admission(
            SequenceRequest("sequence", RuntimeOptions(dry_run=True), {"file": "sequence.json", "document": {"version": 1, "steps": [{"wait": {"seconds": 1}}]}})
        )


def test_ramp_list_null_loop_count_and_numeric_string_segment_are_rejected() -> None:
    document = {
        "kind": "powers-tool-ramp-list",
        "version": 2,
        "segments": [{"channel": 1, "current": 0.1, "start_voltage": 0, "stop_voltage": 1, "step_voltage": 1, "delay_ms": 0, "hold_ms": 0}],
    }
    with pytest.raises(CoreValidationError, match="loop_count must not be null"):
        validate_request_admission(OperationRequest("ramp-list", RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"), {"document": document, "loop_count": None}))
    document["segments"][0]["current"] = "0.1"
    with pytest.raises(CoreValidationError, match="invalid numeric value"):
        validate_request_admission(OperationRequest("ramp-list", RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"), {"document": document}))


@pytest.mark.parametrize(("loop_count", "accepted"), [(10_000, True), (10_001, False)])
def test_command_contract_enforces_workflow_loop_bound(
    loop_count: int, accepted: bool
) -> None:
    request = OperationRequest(
        "ramp",
        RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
        {
            "channel": 1,
            "start_voltage": 0,
            "stop_voltage": 0,
            "step_voltage": 1,
            "current": 0.1,
            "loop_count": loop_count,
        },
    )
    if accepted:
        assert validate_request_admission(request).parameters["loop_count"] == 10_000
    else:
        with pytest.raises(CoreValidationError, match="1 to 10,000"):
            validate_request_admission(request)


def test_ramp_contract_accepts_legacy_channel_and_canonicalizes_channels() -> None:
    legacy = validate_request_admission(
        OperationRequest(
            "ramp",
            RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
            {"channel": 2, "current": 0.1, "start_voltage": 0, "stop_voltage": 1, "step_voltage": 1},
        )
    )
    multi = validate_request_admission(
        OperationRequest(
            "ramp",
            RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
            {"channels": [3, 1], "current": 0.1, "start_voltage": 0, "stop_voltage": 1, "step_voltage": 1},
        )
    )

    assert legacy.parameters["channel"] == 2
    assert "channels" not in legacy.parameters
    assert multi.parameters["channels"] == (1, 3)


@pytest.mark.parametrize(
    "selection",
    [
        {},
        {"channel": 1, "channels": [1, 2]},
        {"channels": []},
        {"channels": [1, 1]},
        {"channels": [1, 4]},
    ],
)
def test_ramp_contract_rejects_invalid_channel_selection(selection: dict) -> None:
    with pytest.raises(CoreValidationError):
        validate_request_admission(
            OperationRequest(
                "ramp",
                RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
                {
                    **selection,
                    "current": 0.1,
                    "start_voltage": 0,
                    "stop_voltage": 1,
                    "step_voltage": 1,
                },
            )
        )


@pytest.mark.parametrize("field", ["verify_after_write", "no_output", "leave_trigger_configured"])
@pytest.mark.parametrize("value", ["false", 0, 1])
def test_workflow_booleans_require_exact_json_boolean(field: str, value: object) -> None:
    command = "apply" if field != "leave_trigger_configured" else "trigger-step"
    parameters = {"channel": 1, "voltage": 1.0, "current": 0.1, field: value}
    if command.startswith("trigger"):
        parameters = {"channel": 1, field: value}
        request = TriggerRequest(command, RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"), parameters)
    else:
        request = OperationRequest(command, RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"), parameters)
    with pytest.raises(CoreValidationError, match=field):
        validate_request_admission(request)


def test_protection_all_requires_exact_boolean() -> None:
    with pytest.raises(CoreValidationError, match="all"):
        validate_request_admission(OperationRequest("protection-set", RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"), {"all": 1, "ocp": "on"}))


def test_protection_set_false_all_is_rejected() -> None:
    opened = False

    def forbidden_opener(*args: object, **kwargs: object) -> object:
        nonlocal opened
        opened = True
        raise AssertionError("admission must not open hardware")

    with pytest.raises(CoreValidationError, match="all=false"):
        run_core_command(
            OperationRequest(
                "protection-set",
                RuntimeOptions(resource="USB0::FAKE::INSTR"),
                {"all": False, "ocp": "on"},
            ),
            opener=forbidden_opener,
        )
    assert opened is False


def test_protection_status_false_all_is_rejected() -> None:
    opened = False

    def forbidden_opener(*args: object, **kwargs: object) -> object:
        nonlocal opened
        opened = True
        raise AssertionError("admission must not open hardware")

    with pytest.raises(CoreValidationError, match="all=false"):
        run_core_command(
            OperationRequest(
                "protection-status",
                RuntimeOptions(resource="USB0::FAKE::INSTR"),
                {"all": False},
            ),
            opener=forbidden_opener,
        )
    assert opened is False


def test_protection_all_true_normalizes_to_channel_all() -> None:
    admitted = validate_request_admission(
        OperationRequest(
            "protection-set",
            RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
            {"all": True, "ocp": "on"},
        )
    )

    assert admitted.parameters == {"channel": "all", "ocp": "on"}
    assert "all" not in admitted.parameters
    assert validate_request_admission(admitted) == admitted


def test_protection_channel_and_all_false_conflict() -> None:
    with pytest.raises(CoreValidationError, match="mutually exclusive"):
        validate_request_admission(
            OperationRequest(
                "protection-set",
                RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
                {"channel": 1, "all": False, "ocp": "on"},
            )
        )


def test_clear_protection_false_all_is_rejected() -> None:
    opened = False

    def forbidden_opener(*args: object, **kwargs: object) -> object:
        nonlocal opened
        opened = True
        raise AssertionError("admission must not open hardware")

    with pytest.raises(CoreValidationError, match="all=false"):
        run_core_command(
            OperationRequest(
                "clear-protection",
                RuntimeOptions(resource="USB0::FAKE::INSTR"),
                {"all": False},
            ),
            opener=forbidden_opener,
        )
    assert opened is False


def test_removed_general_field_has_specific_diagnostic() -> None:
    with pytest.raises(
        CoreValidationError,
        match="ramp field wait_timeout_ms has been removed",
    ):
        validate_request_admission(
            OperationRequest(
                "ramp",
                RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
                {"wait_timeout_ms": 1},
            )
        )


def test_unknown_field_remains_generic() -> None:
    with pytest.raises(CoreValidationError, match="has unknown field\\(s\\): invented"):
        validate_request_admission(
            OperationRequest(
                "ramp",
                RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
                {"invented": 1},
            )
        )


def test_known_but_inapplicable_field_has_specific_diagnostic() -> None:
    with pytest.raises(CoreValidationError, match="measure has known-but-inapplicable field\\(s\\): voltage"):
        validate_request_admission(
            OperationRequest(
                "measure",
                RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
                {"channel": 1, "voltage": 1.0},
            )
        )


def test_completion_pulse_dependency_preserves_presence() -> None:
    runtime = RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a")
    base = {"channel": 1, "voltage": 1.0}

    assert validate_request_admission(OperationRequest("set", runtime, base)).parameters == base
    pins_only = validate_request_admission(
        OperationRequest("set", runtime, {**base, "completion_pulse_pins": [1]})
    )
    assert pins_only.parameters == {**base, "completion_pulse_pins": (1,)}
    with pytest.raises(CoreValidationError, match="completion_pulse_channel requires completion_pulse_pins"):
        validate_request_admission(
            OperationRequest("set", runtime, {**base, "completion_pulse_channel": 1})
        )
    both = validate_request_admission(
        OperationRequest(
            "set",
            runtime,
            {**base, "completion_pulse_channel": 1, "completion_pulse_pins": [1]},
        )
    )
    assert both.parameters == {
        **base,
        "completion_pulse_channel": 1,
        "completion_pulse_pins": (1,),
    }
    assert validate_request_admission(both) == both


def test_restore_multiple_sources_are_rejected_before_file_access() -> None:
    with pytest.raises(CoreValidationError, match="mutually exclusive"):
        validate_request_admission(OperationRequest("restore-from-snapshot", RuntimeOptions(dry_run=True), {"file": "snapshot.json", "snapshot": "other.json"}))
