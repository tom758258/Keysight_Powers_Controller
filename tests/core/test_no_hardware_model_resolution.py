import pytest

from powers_tool_core.command_runner import run_core_command
from powers_tool_core.connection import InstrumentSession
from powers_tool_core.core import CoreValidationError, OperationRequest, RuntimeOptions, SequenceRequest, TriggerRequest
from powers_tool_core.model_resolution import validate_live_expected_model
from powers_tool_core.operations import output_plan, run_operation
from powers_tool_core.protection import run_protection
from powers_tool_core.ramp_list import RAMP_LIST_KIND, run_ramp_list
from powers_tool_core.sequence import run_sequence
from powers_tool_core.testing.simulator import SimulatedResourceManager


def test_runtime_options_planning_model_id_defaults_to_none() -> None:
    assert RuntimeOptions().planning_model_id is None


def test_dry_run_requires_model_or_known_sim_resource() -> None:
    with pytest.raises(CoreValidationError, match="require planning_model_id"):
        output_plan(
            OperationRequest(
                command="output-on",
                runtime=RuntimeOptions(dry_run=True),
                parameters={"channel": 1},
            )
        )


def test_generic_dry_run_profile_is_single_channel() -> None:
    plan = output_plan(
        OperationRequest(
            command="output-on",
            runtime=RuntimeOptions(dry_run=True, planning_profile_id="generic-scpi"),
            parameters={"channel": "all"},
        )
    )

    assert plan["target"]["planning_profile_id"] == "generic-scpi"
    assert plan["target"]["planning_model_id"] is None
    assert [step["parameters"]["channel"] for step in plan["steps"]] == [1]


def test_simulate_derives_resource_from_model_and_rejects_generic() -> None:
    plan = output_plan(
        OperationRequest(
            command="output-on",
            runtime=RuntimeOptions(simulate=True, planning_model_id="keysight-e36312a"),
            parameters={"channel": 1},
        )
    )

    assert plan["target"]["resource"] == "USB0::SIM::E36312A::INSTR"
    with pytest.raises(CoreValidationError, match="invalid in simulator"):
        output_plan(
            OperationRequest(
                command="output-on",
                runtime=RuntimeOptions(simulate=True, planning_profile_id="generic-scpi"),
                parameters={"channel": 1},
            )
        )


def test_psm2010_simulate_measure_derives_deterministic_resource_and_identity() -> None:
    opened: list[str] = []
    manager = SimulatedResourceManager()

    def opener(resource: str, resource_manager=None, **kwargs):
        opened.append(resource)
        return InstrumentSession(manager.open_resource(resource), resource_name=resource)

    data = run_core_command(
        OperationRequest(
            command="measure",
            runtime=RuntimeOptions(simulate=True, planning_model_id="gw-instek-psm-2010"),
            parameters={"channel": 1},
        ),
        opener=opener,
    )

    assert opened == ["ASRL1::SIM::PSM2010::INSTR"]
    assert data["measurements"] == {"voltage": 1.0, "current": 0.05}


@pytest.mark.parametrize(
    ("command", "parameters"),
    [
        ("set", {"channel": 1, "voltage": 1.0}),
        ("apply", {"channel": 1, "voltage": 1.0, "current": 0.05}),
        ("output-on", {"channel": 1}),
    ],
)
def test_psm2010_no_hardware_mutating_commands_remain_disabled(
    command: str, parameters: dict[str, object]
) -> None:
    with pytest.raises(CoreValidationError, match="not enabled|not supported"):
        run_core_command(
            OperationRequest(
                command=command,
                runtime=RuntimeOptions(
                    simulate=True,
                    planning_model_id="gw-instek-psm-2010",
                ),
                parameters=parameters,
            )
        )


def test_simulate_rejects_explicit_non_sim_resource() -> None:
    with pytest.raises(CoreValidationError, match="requires a deterministic SIM resource"):
        output_plan(
            OperationRequest(
                command="output-on",
                runtime=RuntimeOptions(
                    resource="ASRL7::INSTR",
                    simulate=True,
                    planning_model_id="keysight-e3646a",
                ),
                parameters={"channel": 1},
            )
        )


def test_sim_resource_infers_model_and_mismatch_is_rejected() -> None:
    plan = output_plan(
        OperationRequest(
            command="output-on",
            runtime=RuntimeOptions(resource="ASRL1::SIM::E3646A::INSTR", dry_run=True),
            parameters={"channel": "all"},
        )
    )

    assert plan["target"]["planning_model_id"] == "keysight-e3646a"
    assert [step["parameters"]["channel"] for step in plan["steps"]] == [1, 2]
    with pytest.raises(CoreValidationError, match="does not match"):
        output_plan(
            OperationRequest(
                command="output-on",
                runtime=RuntimeOptions(
                    resource="USB0::SIM::E36312A::INSTR",
                    simulate=True,
                    planning_model_id="keysight-e3646a",
                ),
                parameters={"channel": 1},
            )
        )


def test_live_expected_model_requires_canonical_model_id() -> None:
    assert (
        validate_live_expected_model("keysight-e36312a", "keysight-e36312a")
        == "keysight-e36312a"
    )
    with pytest.raises(CoreValidationError, match="invalid expected_model_id"):
        validate_live_expected_model("E36312A", "keysight-e36312a")


def test_live_expected_model_rejects_generic() -> None:
    with pytest.raises(CoreValidationError, match="invalid expected_model_id"):
        validate_live_expected_model("generic-scpi", "keysight-e36312a")


@pytest.mark.parametrize("model", ["keysight-e36103b", "keysight-e36232a"])
def test_descoped_models_are_rejected_as_live_expected_models(model: str) -> None:
    with pytest.raises(CoreValidationError, match="not active or candidate"):
        validate_live_expected_model(model, model)


@pytest.mark.parametrize("model", ["keysight-e36103b", "keysight-e36232a"])
def test_descoped_models_are_rejected_as_no_hardware_planning_model_ids(model: str) -> None:
    with pytest.raises(CoreValidationError, match="not active or candidate"):
        output_plan(
            OperationRequest(
                command="output-on",
                runtime=RuntimeOptions(dry_run=True, planning_model_id=model),
                parameters={"channel": 1},
            )
        )


def test_live_expected_model_mismatch_message_is_explicit() -> None:
    with pytest.raises(CoreValidationError) as exc:
        validate_live_expected_model("keysight-e36312a", "keysight-e3646a", command="set")

    message = str(exc.value)
    assert "Expected model_id keysight-e36312a" in message
    assert "resolved to keysight-e3646a" in message
    assert "does not override the IDN-selected driver" in message


def test_live_unsupported_planning_model_id_is_rejected_before_opening() -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("must not open")

    with pytest.raises(CoreValidationError, match="invalid expected_model_id"):
        run_operation(
            OperationRequest(
                command="output-on",
                runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", expected_model_id="FUTURE123"),
                parameters={"channel": 1},
            ),
            opener=opener,
        )

    assert opened is False


def test_e3646a_no_hardware_channel_three_is_rejected_across_planners() -> None:
    runtime = RuntimeOptions(dry_run=True, planning_model_id="keysight-e3646a")

    with pytest.raises(CoreValidationError, match="channel 3"):
        output_plan(OperationRequest(command="output-on", runtime=runtime, parameters={"channel": 3}))

    ramp_document = {
        "kind": RAMP_LIST_KIND,
        "version": 2,
        "segments": [
            {
                "channel": 3,
                "current": 0.1,
                "start_voltage": 0,
                "stop_voltage": 1,
                "step_voltage": 1,
                "delay_ms": 0,
                "hold_ms": 0,
            }
        ],
    }
    with pytest.raises(CoreValidationError, match="channel 3"):
        run_ramp_list(OperationRequest(command="ramp-list", runtime=runtime, parameters={"document": ramp_document}))

    sequence_document = {"version": 1, "steps": [{"action": "output-on", "channel": 3}]}
    with pytest.raises(CoreValidationError, match="channel 3"):
        run_sequence(SequenceRequest(runtime=runtime, parameters={"document": sequence_document}))

    with pytest.raises(CoreValidationError, match="not supported for E3646A"):
        run_protection(
            OperationRequest(
                command="clear-protection",
                runtime=runtime,
                parameters={"channel": 3},
            )
        )


def test_sequence_e3646a_all_expands_to_two_channels_and_protection_is_policy_disabled() -> None:
    runtime = RuntimeOptions(dry_run=True, planning_model_id="keysight-e3646a")

    sequence_data = run_sequence(
        SequenceRequest(
            runtime=runtime,
            parameters={"document": {"version": 1, "steps": [{"action": "output-off", "channel": "all"}]}},
        )
    )
    assert sequence_data["plan"]["target"]["planning_model_id"] == "keysight-e3646a"
    assert sequence_data["plan"]["steps"][0]["preview"]["commands"] == ["OUTP OFF,(@1)", "OUTP OFF,(@2)"]

    with pytest.raises(CoreValidationError, match="not supported for E3646A"):
        run_protection(
            OperationRequest(
                command="clear-protection",
                runtime=runtime,
                parameters={"channel": "all"},
            )
        )


def test_trigger_dry_run_requires_e36312a_model_or_known_sim_resource() -> None:
    with pytest.raises(CoreValidationError, match="require planning_model_id"):
        run_core_command(
            TriggerRequest(
                command="trigger-fire",
                runtime=RuntimeOptions(dry_run=True),
            )
        )

    data = run_core_command(
        TriggerRequest(
            command="trigger-fire",
            runtime=RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
        )
    )
    assert data["plan"]["target"]["planning_model_id"] == "keysight-e36312a"


@pytest.mark.parametrize("model", ["keysight-edu36311a", "keysight-e3646a", "keysight-e36103b", "keysight-e36232a", "generic-scpi"])
@pytest.mark.parametrize("mode", ["dry_run", "simulate"])
def test_trigger_no_hardware_rejects_unsupported_models(model: str, mode: str) -> None:
    runtime_fields = {
        "planning_profile_id": model,
    } if model == "generic-scpi" else {"planning_model_id": model}

    with pytest.raises(CoreValidationError, match="not supported|invalid in simulator|not active or candidate"):
        run_core_command(
            TriggerRequest(
                command="trigger-fire",
                runtime=RuntimeOptions(
                    dry_run=mode == "dry_run",
                    simulate=mode == "simulate",
                    **runtime_fields,
                ),
            )
        )


def test_trigger_sim_resource_infers_e36312a_and_rejects_edu36311a() -> None:
    data = run_core_command(
        TriggerRequest(
            command="trigger-status",
            runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", dry_run=True),
            parameters={"channel": "all"},
        )
    )

    assert data["plan"]["target"]["planning_model_id"] == "keysight-e36312a"

    with pytest.raises(CoreValidationError, match="trigger/native LIST workflows are disabled"):
        run_core_command(
            TriggerRequest(
                command="trigger-status",
                runtime=RuntimeOptions(resource="USB0::SIM::EDU36311A::INSTR", dry_run=True),
                parameters={"channel": "all"},
            )
        )


def test_trigger_simulate_model_derives_e36312a_resource() -> None:
    opened: list[str] = []
    manager = SimulatedResourceManager()

    def opener(resource: str, **kwargs):
        opened.append(resource)
        return InstrumentSession(manager.open_resource(resource), resource_name=resource)

    data = run_core_command(
        TriggerRequest(
            command="trigger-status",
            runtime=RuntimeOptions(simulate=True, planning_model_id="keysight-e36312a"),
            parameters={"channel": 1},
        ),
        opener=opener,
    )

    assert opened == ["USB0::SIM::E36312A::INSTR"]
    assert data["idn"].split(",")[1] == "E36312A"


def test_trigger_live_unsupported_planning_model_id_is_rejected_before_opening() -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("must not open")

    with pytest.raises(CoreValidationError, match="invalid expected_model_id"):
        run_core_command(
            TriggerRequest(
                command="trigger-status",
                runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", expected_model_id="FUTURE123"),
                parameters={"channel": 1},
            ),
            opener=opener,
        )

    assert opened is False


def test_trigger_status_and_abort_all_dry_run_expand_e36312a_channels() -> None:
    status_data = run_core_command(
        TriggerRequest(
            command="trigger-status",
            runtime=RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
            parameters={"channel": "all"},
        )
    )
    status_commands = [step["command"] for step in status_data["plan"]["steps"]]
    assert "TRIG:SOUR? (@1)" in status_commands
    assert "TRIG:SOUR? (@2)" in status_commands
    assert "TRIG:SOUR? (@3)" in status_commands

    abort_data = run_core_command(
        TriggerRequest(
            command="trigger-abort",
            runtime=RuntimeOptions(dry_run=True, planning_model_id="keysight-e36312a"),
            parameters={"channel": "all"},
        )
    )
    assert [step["command"] for step in abort_data["plan"]["steps"]] == [
        "ABOR (@1)",
        "ABOR (@2)",
        "ABOR (@3)",
    ]
