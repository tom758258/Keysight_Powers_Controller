import pytest

from powers_tool_core.drivers.e36312a import E36312APowerSupply, TriggerSnapshot
from powers_tool_core.drivers.e3646a import E3646APowerSupply
from powers_tool_core.drivers.edu36311a import EDU36311APowerSupply
from powers_tool_core.drivers.generic_scpi import NoChannelStrategy
from powers_tool_core.drivers.psm2010 import PSM2010PowerSupply
from powers_tool_core.electrical_ratings import PSM2010_ELECTRICAL_RATINGS
from powers_tool_core.safety import SafetyLimits, SafetyValidationError


class FakeSession:
    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.commands: list[str] = []
        self.responses = responses or {}

    def write(self, command: str) -> None:
        self.commands.append(command)

    def query(self, command: str) -> str:
        self.commands.append(command)
        response = self.responses.get(command)
        if response is None:
            raise RuntimeError(f"No fake response for {command}")
        return response

    def close(self) -> None:
        pass


class RestoreFailingSession(FakeSession):
    def write(self, command: str) -> None:
        self.commands.append(command)
        if command == "INST:NSEL 1":
            raise RuntimeError("restore failed")


def test_psm2010_driver_exposes_single_channel_capabilities() -> None:
    assert PSM2010PowerSupply.capabilities.channels == (1,)
    assert PSM2010PowerSupply.capabilities.simulated_measure_channels == (1,)
    assert PSM2010PowerSupply.capabilities.real_measure_channels == (1,)
    assert PSM2010PowerSupply.capabilities.electrical_ratings is PSM2010_ELECTRICAL_RATINGS


@pytest.mark.parametrize(("response", "expected"), [("P8V", "LOW"), ("P20V", "HIGH")])
def test_psm2010_driver_queries_canonical_output_range(response, expected) -> None:
    session = FakeSession({"VOLT:RANG?": response})
    power_supply = PSM2010PowerSupply(session)

    assert power_supply.output_range(channel=1) == expected
    assert session.commands == ["VOLT:RANG?"]


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("LOW", "VOLT:RANG LOW"),
        ("P8V", "VOLT:RANG LOW"),
        ("HIGH", "VOLT:RANG HIGH"),
        ("P20V", "VOLT:RANG HIGH"),
    ],
)
def test_psm2010_driver_explicitly_sets_output_range(requested, expected) -> None:
    session = FakeSession()
    power_supply = PSM2010PowerSupply(session)

    power_supply.set_output_range(channel=1, output_range=requested)

    assert session.commands == [expected]


def test_psm2010_driver_rejects_invalid_range_before_io() -> None:
    session = FakeSession()
    power_supply = PSM2010PowerSupply(session)

    with pytest.raises(ValueError, match="output range must be"):
        power_supply.set_output_range(channel=1, output_range="AUTO")

    assert session.commands == []


def test_psm2010_driver_rejects_unknown_range_response() -> None:
    session = FakeSession({"VOLT:RANG?": "LOW"})
    power_supply = PSM2010PowerSupply(session)

    with pytest.raises(ValueError, match="unsupported PSM-2010 output range response"):
        power_supply.output_range(channel=1)

    assert session.commands == ["VOLT:RANG?"]


@pytest.mark.parametrize(
    ("response", "method", "value", "expected_command"),
    [
        ("P8V", "voltage", 5.0, "VOLT 5"),
        ("P8V", "current", 15.0, "CURR 15"),
        ("P20V", "voltage", 15.0, "VOLT 15"),
        ("P20V", "current", 5.0, "CURR 5"),
    ],
)
def test_psm2010_driver_writes_scalar_supported_by_active_range(
    response,
    method,
    value,
    expected_command,
) -> None:
    session = FakeSession({"VOLT:RANG?": response})
    power_supply = PSM2010PowerSupply(session)

    if method == "voltage":
        power_supply.set_voltage(channel=1, voltage=value)
    else:
        power_supply.set_current_limit(channel=1, current=value)

    assert session.commands == ["VOLT:RANG?", expected_command]


@pytest.mark.parametrize(
    ("response", "method", "value", "range_name"),
    [
        ("P8V", "voltage", 15.0, "LOW"),
        ("P20V", "current", 15.0, "HIGH"),
    ],
)
def test_psm2010_driver_rejects_scalar_unsupported_by_active_range(
    response,
    method,
    value,
    range_name,
) -> None:
    session = FakeSession({"VOLT:RANG?": response})
    power_supply = PSM2010PowerSupply(session)

    with pytest.raises(SafetyValidationError, match=rf"PSM-2010 {range_name} range maximum"):
        if method == "voltage":
            power_supply.set_voltage(channel=1, voltage=value)
        else:
            power_supply.set_current_limit(channel=1, current=value)

    assert session.commands == ["VOLT:RANG?"]


def test_psm2010_driver_uses_documented_measurement_queries() -> None:
    session = FakeSession({"MEAS?": "5.000", "MEAS:CURR?": "1.250"})
    power_supply = PSM2010PowerSupply(session)

    assert power_supply.measure_voltage(channel=1) == 5.0
    assert power_supply.measure_current(channel=1) == 1.25
    assert session.commands == ["MEAS?", "MEAS:CURR?"]


@pytest.mark.parametrize("channel", [2, 3])
def test_psm2010_driver_rejects_non_channel_one_before_io(channel) -> None:
    session = FakeSession()
    power_supply = PSM2010PowerSupply(session)

    with pytest.raises(ValueError, match="channel must be 1"):
        power_supply.set_voltage(channel=channel, voltage=1.0)
    with pytest.raises(ValueError, match="channel must be 1"):
        power_supply.set_output_range(channel=channel, output_range="LOW")
    with pytest.raises(ValueError, match="channel must be 1"):
        power_supply.measure_voltage(channel=channel)

    assert session.commands == []


@pytest.mark.parametrize(
    "driver_class",
    [E36312APowerSupply, EDU36311APowerSupply],
)
@pytest.mark.parametrize("channel", [1, 2, 3])
def test_first_target_drivers_use_channel_list_scpi(driver_class, channel) -> None:
    session = FakeSession(
        {
            f"MEAS:VOLT? (@{channel})": "1.234",
            f"MEAS:CURR? (@{channel})": "0.056",
        }
    )
    power_supply = driver_class(session)

    power_supply.set_current_limit(channel=channel, current=0.05)
    power_supply.set_voltage(channel=channel, voltage=1.0)
    power_supply.output_off(channel=channel)
    voltage = power_supply.measure_voltage(channel=channel)
    current = power_supply.measure_current(channel=channel)

    assert voltage == 1.234
    assert current == 0.056
    assert session.commands == [
        f"CURR 0.05,(@{channel})",
        f"VOLT 1,(@{channel})",
        f"OUTP OFF,(@{channel})",
        f"MEAS:VOLT? (@{channel})",
        f"MEAS:CURR? (@{channel})",
    ]


@pytest.mark.parametrize(
    "driver_class",
    [E36312APowerSupply, EDU36311APowerSupply],
)
def test_first_target_drivers_allow_channel_strategy_override(driver_class) -> None:
    session = FakeSession()
    power_supply = driver_class(session, channel_strategy=NoChannelStrategy())

    power_supply.output_off(channel=1)

    assert session.commands == ["OUTP OFF"]


def test_first_target_driver_safety_validation_runs_before_scpi_write() -> None:
    session = FakeSession()
    power_supply = E36312APowerSupply(
        session,
        safety_limits=SafetyLimits(
            max_voltage=5.0,
            max_current=0.5,
            allowed_channels=(1,),
        ),
    )

    with pytest.raises(SafetyValidationError, match="channel 2 is not allowed"):
        power_supply.set_voltage(channel=2, voltage=1.0)

    assert session.commands == []


def test_e36312a_driver_sets_protection_with_channel_list_scpi() -> None:
    session = FakeSession()
    power_supply = E36312APowerSupply(session)

    power_supply.set_over_voltage_protection(channel=2, voltage=5.0)
    power_supply.set_over_current_protection_enabled(channel=2, enabled=True)
    power_supply.set_over_current_protection_delay(channel=2, seconds=0.5)
    power_supply.set_over_current_protection_delay_trigger(channel=2, trigger="setting-change")
    power_supply.set_over_current_protection_delay_trigger(channel=2, trigger="cc-transition")

    assert session.commands == [
        "VOLT:PROT 5,(@2)",
        "CURR:PROT:STAT ON,(@2)",
        "CURR:PROT:DEL 0.5,(@2)",
        "CURR:PROT:DEL:STAR SCH,(@2)",
        "CURR:PROT:DEL:STAR CCTR,(@2)",
    ]


@pytest.mark.parametrize(
    "driver_class",
    [E36312APowerSupply, EDU36311APowerSupply],
)
def test_first_target_drivers_read_channel_protection_trip_flags(driver_class) -> None:
    session = FakeSession(
        {
            "VOLT:PROT:TRIP? (@2)": "1",
            "CURR:PROT:TRIP? (@2)": "0",
        }
    )
    power_supply = driver_class(session)

    assert power_supply.over_voltage_protection_tripped(channel=2) is True
    assert power_supply.over_current_protection_tripped(channel=2) is False
    assert session.commands == [
        "VOLT:PROT:TRIP? (@2)",
        "CURR:PROT:TRIP? (@2)",
    ]


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("SCH", "setting-change"),
        ("SCHange", "setting-change"),
        ("CCTR", "cc-transition"),
        ("CCTRans", "cc-transition"),
    ],
)
def test_e36312a_driver_reads_ocp_delay_trigger(response, expected) -> None:
    session = FakeSession({"CURR:PROT:DEL:STAR? (@2)": response})
    power_supply = E36312APowerSupply(session)

    assert power_supply.over_current_protection_delay_trigger(channel=2) == expected


def test_e36312a_driver_configures_native_list_with_trigger_outputs() -> None:
    session = FakeSession()
    power_supply = E36312APowerSupply(session)

    power_supply.configure_list(
        channel=1,
        voltages=(0.0, 1.0),
        currents=(0.05, 0.05),
        dwell=(0.01, 0.02),
        begin_outputs=(False, False),
        end_outputs=(False, True),
        count=1,
        step_mode="AUTO",
        terminate_last=True,
    )
    power_supply.set_trigger_modes(channel=1, current_mode="LIST", voltage_mode="LIST")
    power_supply.set_output_trigger_source(channel=1, source="BUS")
    power_supply.initiate_output_trigger(1)
    power_supply.fire_bus_trigger()

    assert session.commands == [
        "LIST:VOLT 0,1,(@1)",
        "LIST:CURR 0.05,0.05,(@1)",
        "LIST:DWEL 0.01,0.02,(@1)",
        "LIST:TOUT:BOST 0,0,(@1)",
        "LIST:TOUT:EOST 0,1,(@1)",
        "LIST:COUN 1,(@1)",
        "LIST:STEP AUTO,(@1)",
        "LIST:TERM:LAST ON,(@1)",
        "CURR:MODE FIX,(@1)",
        "VOLT:MODE FIX,(@1)",
        "CURR:MODE LIST,(@1)",
        "VOLT:MODE LIST,(@1)",
        "TRIG:SOUR BUS,(@1)",
        "INIT (@1)",
        "*TRG",
    ]


def test_e36312a_driver_supports_operation_complete_polling() -> None:
    session = FakeSession({"*ESR?": "1"})
    power_supply = E36312APowerSupply(session)

    power_supply.prepare_operation_complete_wait()

    assert power_supply.operation_complete_event() is True
    assert session.commands == ["*CLS", "*ESE 1", "*OPC", "*ESR?"]


def test_e36312a_restore_trigger_snapshot_accepts_fixed_modes() -> None:
    session = FakeSession()
    power_supply = E36312APowerSupply(session)
    snapshot = TriggerSnapshot(
        channel=1,
        digital_pins={
            1: {"function": "TOUT", "polarity": "POS"},
            2: {"function": "TOUT", "polarity": "POS"},
            3: {"function": "DIO", "polarity": "POS"},
        },
        trigger_output_bus_enabled=False,
        trigger={
            "source": "BUS",
            "delay": 0.0,
            "voltage_mode": "FIX",
            "current_mode": "FIX",
            "triggered_voltage": 0.0,
            "triggered_current": 0.002,
        },
        list_state={
            "voltage": (0.0,),
            "current": (0.002,),
            "dwell": (0.01,),
            "tout_bost": (False,),
            "tout_eost": (False,),
            "count": 1,
            "step_mode": "AUTO",
            "terminate_last": False,
        },
    )

    power_supply.restore_trigger_snapshot(snapshot)

    assert session.commands.count("CURR:MODE FIX,(@1)") == 1
    assert session.commands.count("VOLT:MODE FIX,(@1)") == 1


def test_e36312a_restore_trigger_snapshot_maps_dinp_pin_function_to_dio() -> None:
    session = FakeSession()
    power_supply = E36312APowerSupply(session)
    snapshot = TriggerSnapshot(
        channel=1,
        digital_pins={
            1: {"function": "DINP", "polarity": "POS"},
            2: {"function": "DINP", "polarity": "POS"},
            3: {"function": "DINP", "polarity": "POS"},
        },
        trigger_output_bus_enabled=False,
        trigger={
            "source": "BUS",
            "delay": 0.0,
            "voltage_mode": "FIX",
            "current_mode": "FIX",
            "triggered_voltage": 0.0,
            "triggered_current": 0.002,
        },
        list_state={
            "voltage": (0.0,),
            "current": (0.002,),
            "dwell": (0.01,),
            "tout_bost": (False,),
            "tout_eost": (False,),
            "count": 1,
            "step_mode": "AUTO",
            "terminate_last": False,
        },
    )

    power_supply.restore_trigger_snapshot(snapshot)

    assert "DIG:PIN1:FUNC DIO" in session.commands
    assert "DIG:PIN2:FUNC DIO" in session.commands
    assert "DIG:PIN3:FUNC DIO" in session.commands


@pytest.mark.parametrize(
    ("function", "expected_command"),
    [
        ("DIO", "DIG:PIN1:FUNC DIO"),
        ("DINP", "DIG:PIN1:FUNC DIO"),
        ("TOUT", "DIG:PIN1:FUNC TOUT"),
        ("TINP", "DIG:PIN1:FUNC TINP"),
    ],
)
def test_e36312a_set_digital_pin_function_accepts_supported_values(function, expected_command) -> None:
    session = FakeSession()
    power_supply = E36312APowerSupply(session)

    power_supply.set_digital_pin_function(1, function)

    assert session.commands == [expected_command]


def test_e36312a_set_digital_pin_function_rejects_invalid_value() -> None:
    session = FakeSession()
    power_supply = E36312APowerSupply(session)

    with pytest.raises(ValueError, match="digital pin function"):
        power_supply.set_digital_pin_function(1, "BAD")

    assert session.commands == []


def test_e36312a_trigger_mode_switch_always_passes_through_fix() -> None:
    session = FakeSession()
    power_supply = E36312APowerSupply(session)

    power_supply.set_trigger_modes(channel=1, current_mode="STEP", voltage_mode="LIST")

    assert session.commands == [
        "CURR:MODE FIX,(@1)",
        "VOLT:MODE FIX,(@1)",
        "CURR:MODE STEP,(@1)",
        "VOLT:MODE LIST,(@1)",
    ]


def test_e3646a_driver_preselects_and_restores_channel_for_readback() -> None:
    session = FakeSession(
        {
            "INST:NSEL?": "1",
            "VOLT?": "2.000",
            "CURR?": "0.100",
            "OUTP?": "0",
        }
    )
    power_supply = E3646APowerSupply(session)

    assert power_supply.programmed_voltage(channel=2) == 2.0
    assert power_supply.programmed_current(channel=2) == 0.1
    assert power_supply.output_state(channel=2) is False

    assert session.commands == [
        "INST:NSEL?",
        "INST:NSEL 2",
        "VOLT?",
        "INST:NSEL 1",
        "INST:NSEL?",
        "INST:NSEL 2",
        "CURR?",
        "INST:NSEL 1",
        "INST:NSEL?",
        "INST:NSEL 2",
        "OUTP?",
        "INST:NSEL 1",
    ]


def test_e3646a_driver_tolerates_best_effort_channel_restore_failure() -> None:
    session = RestoreFailingSession(
        {
            "INST:NSEL?": "1",
            "MEAS:VOLT?": "2.100",
        }
    )
    power_supply = E3646APowerSupply(session)

    assert power_supply.measure_voltage(channel=2) == 2.1
    assert session.commands == [
        "INST:NSEL?",
        "INST:NSEL 2",
        "MEAS:VOLT?",
        "INST:NSEL 1",
    ]


def test_e3646a_driver_output_writes_success() -> None:
    session = FakeSession(
        {
            "INST:NSEL?": "1",
        }
    )
    power_supply = E3646APowerSupply(session)

    power_supply.set_current_limit(channel=2, current=0.05)
    power_supply.set_voltage(channel=2, voltage=1.0)
    power_supply.output_on(channel=2)
    power_supply.output_off(channel=2)

    assert session.commands == [
        "INST:NSEL?",
        "INST:NSEL 2",
        "CURR 0.05",
        "INST:NSEL 1",
        "INST:NSEL?",
        "INST:NSEL 2",
        "VOLT 1",
        "INST:NSEL 1",
        "INST:NSEL?",
        "INST:NSEL 2",
        "OUTP ON",
        "INST:NSEL 1",
        "INST:NSEL?",
        "INST:NSEL 2",
        "OUTP OFF",
        "INST:NSEL 1",
    ]


def test_e3646a_driver_invalid_channel_raises_before_scpi_write() -> None:
    session = FakeSession()
    power_supply = E3646APowerSupply(session)

    with pytest.raises(ValueError, match="channel must be 1 or 2"):
        power_supply.set_voltage(channel=3, voltage=1.0)

    with pytest.raises(ValueError, match="channel must be 1 or 2"):
        power_supply.set_current_limit(channel=3, current=0.1)

    with pytest.raises(ValueError, match="channel must be 1 or 2"):
        power_supply.output_on(channel=3)

    with pytest.raises(ValueError, match="channel must be 1 or 2"):
        power_supply.output_off(channel=3)

    assert session.commands == []


def test_e3646a_driver_safety_validation_runs_before_scpi_write() -> None:
    session = FakeSession()
    power_supply = E3646APowerSupply(
        session,
        safety_limits=SafetyLimits(
            max_voltage=5.0,
            max_current=0.5,
            allowed_channels=(1,),
        ),
    )

    with pytest.raises(SafetyValidationError, match="channel 2 is not allowed"):
        power_supply.set_voltage(channel=2, voltage=1.0)

    with pytest.raises(SafetyValidationError, match="voltage 6 exceeds"):
        power_supply.set_voltage(channel=1, voltage=6.0)

    assert session.commands == []


def test_e3646a_driver_restore_failure_remains_best_effort() -> None:
    session = RestoreFailingSession(
        {
            "INST:NSEL?": "1",
        }
    )
    power_supply = E3646APowerSupply(session)

    power_supply.output_on(channel=2)

    assert session.commands == [
        "INST:NSEL?",
        "INST:NSEL 2",
        "OUTP ON",
        "INST:NSEL 1",
    ]
