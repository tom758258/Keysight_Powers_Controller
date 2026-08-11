import pytest

from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import select_driver
from powers_tool_core.identity import IDENTITY_INDEXES, planning_model_id_from_sim_resource
from powers_tool_core.model_resolution import MODEL_CHANNELS_BY_ID, SIMULATED_RESOURCE_FOR_MODEL_ID
from powers_tool_core.models import parse_idn
from powers_tool_core.testing.simulator import (
    SIMULATED_IDN,
    SIMULATED_RESOURCES,
    SimulatedResourceManager,
)


def test_simulator_lists_first_target_resources() -> None:
    assert SIMULATED_RESOURCES == (
        "USB0::SIM::E36312A::INSTR",
        "USB0::SIM::EDU36311A::INSTR",
        "ASRL1::SIM::E3646A::INSTR",
        "ASRL1::SIM::PSM2010::INSTR",
    )
    assert SimulatedResourceManager().list_resources() == SIMULATED_RESOURCES


@pytest.mark.parametrize("resource", SIMULATED_RESOURCES)
def test_simulator_idn_responses_are_parseable_registered_idns(resource) -> None:
    session = SimulatedResourceManager().open_resource(resource)

    idn = parse_idn(session.query("*IDN?"))

    assert idn.parse_ok is True
    assert idn.raw == SIMULATED_IDN[resource]
    assert select_driver(idn.raw).physical_identity is not None


def test_deterministic_simulator_registry_uses_matching_canonical_identity() -> None:
    assert set(SIMULATED_RESOURCE_FOR_MODEL_ID) == {
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e3646a",
        "gw-instek-psm-2010",
    }
    for model_id, resource in SIMULATED_RESOURCE_FOR_MODEL_ID.items():
        assert resource in SIMULATED_IDN
        assert planning_model_id_from_sim_resource(resource) == model_id
        session = SimulatedResourceManager().open_resource(resource)
        selection = select_driver(session.query("*IDN?"))
        assert selection.capabilities.channels == MODEL_CHANNELS_BY_ID[model_id]
        assert selection.physical_identity is not None
        assert selection.physical_identity.vendor_id == IDENTITY_INDEXES.models_by_id[model_id].vendor_id


def test_psm2010_simulator_supports_product_read_and_safe_state_commands() -> None:
    session = SimulatedResourceManager().open_resource("ASRL1::SIM::PSM2010::INSTR")

    assert session.query("MEAS?") == "1.000"
    assert session.query("MEAS:CURR?") == "0.050"
    assert session.query("VOLT?") == "1.000"
    assert session.query("CURR?") == "0.050"
    assert session.query("OUTP?") == "OFF"
    session.write("OUTP OFF")
    assert session.query("OUTP?") == "OFF"
    assert session.query("VOLT:RANG?") == "P8V"
    session.write("VOLT:RANG HIGH")
    assert session.query("VOLT:RANG?") == "P20V"
    session.write("VOLT:RANG LOW")
    assert session.query("VOLT:RANG?") == "P8V"
    assert session.query("SYST:ERR?") == '0,"No error"'


@pytest.mark.parametrize(
    ("resource", "channel", "expected_voltage", "expected_current"),
    [
        ("USB0::SIM::E36312A::INSTR", 1, "1.100", "0.110"),
        ("USB0::SIM::E36312A::INSTR", 2, "2.200", "0.220"),
        ("USB0::SIM::E36312A::INSTR", 3, "3.300", "0.330"),
        ("USB0::SIM::EDU36311A::INSTR", 1, "1.010", "0.101"),
        ("USB0::SIM::EDU36311A::INSTR", 2, "2.020", "0.202"),
        ("USB0::SIM::EDU36311A::INSTR", 3, "3.030", "0.303"),
    ],
)
def test_first_target_simulator_supports_channel_list_measurements(
    resource,
    channel,
    expected_voltage,
    expected_current,
) -> None:
    session = SimulatedResourceManager().open_resource(resource)

    assert session.query(f"MEAS:VOLT? (@{channel})") == expected_voltage
    assert session.query(f"MEAS:CURR? (@{channel})") == expected_current


@pytest.mark.parametrize("resource", ["USB0::SIM::E36103B::INSTR", "TCPIP0::SIM::E36232A::INSTR"])
def test_descoped_simulator_resources_are_not_available(resource: str) -> None:
    with pytest.raises(VisaConnectionError, match="Unknown simulated resource"):
        SimulatedResourceManager().open_resource(resource)


@pytest.mark.parametrize(
    ("resource", "channel"),
    [
        ("USB0::SIM::E36312A::INSTR", 1),
        ("USB0::SIM::E36312A::INSTR", 2),
        ("USB0::SIM::E36312A::INSTR", 3),
    ],
)
def test_first_target_simulator_supports_output_state_queries(resource, channel) -> None:
    session = SimulatedResourceManager().open_resource(resource)

    assert session.query(f"OUTP? (@{channel})") == "OFF"


@pytest.mark.parametrize(
    ("channel", "expected_voltage", "expected_current"),
    [
        (1, "1.000", "0.050"),
        (2, "2.000", "0.100"),
        (3, "3.000", "0.150"),
    ],
)
def test_e36312a_simulator_supports_programmed_setpoint_queries(
    channel,
    expected_voltage,
    expected_current,
) -> None:
    session = SimulatedResourceManager().open_resource("USB0::SIM::E36312A::INSTR")

    assert session.query(f"VOLT? (@{channel})") == expected_voltage
    assert session.query(f"CURR? (@{channel})") == expected_current


def test_e3646a_simulator_tracks_selected_channel_output_writes_independently() -> None:
    session = SimulatedResourceManager().open_resource("ASRL1::SIM::E3646A::INSTR")

    session.write("INST:NSEL 2")
    session.write("CURR 0.075")
    session.write("VOLT 1.25")
    session.write("OUTP ON")
    session.write("INST:NSEL 1")

    assert session.query("CURR?") == "0.050"
    assert session.query("VOLT?") == "1.000"
    assert session.query("OUTP?") == "OFF"

    session.write("OUTP OFF")
    session.write("INST:NSEL 2")

    assert session.query("CURR?") == "0.075"
    assert session.query("VOLT?") == "1.25"
    assert session.query("OUTP?") == "ON"


def test_e36312a_simulator_supports_protection_and_identity_queries() -> None:
    session = SimulatedResourceManager().open_resource("USB0::SIM::E36312A::INSTR")

    assert session.query("VOLT:PROT:TRIP?") == "0"
    assert session.query("CURR:PROT:TRIP?") == "0"
    assert session.query("VOLT:PROT:TRIP? (@2)") == "0"
    assert session.query("CURR:PROT:TRIP? (@2)") == "0"
    assert session.query("*OPT?") == "0"
    assert session.query("SYST:VERS?") == "1999.0"
    assert session.query("SYST:COMM:RLST?") == "RWLock"


def test_e36312a_simulator_accepts_clear_protection_writes() -> None:
    session = SimulatedResourceManager().open_resource("USB0::SIM::E36312A::INSTR")

    session.write("OUTP:PROT:CLE (@2)")

    assert session.commands == ["OUTP:PROT:CLE (@2)"]


def test_e36312a_simulator_accepts_protection_set_writes() -> None:
    session = SimulatedResourceManager().open_resource("USB0::SIM::E36312A::INSTR")

    session.write("VOLT:PROT 5,(@2)")
    session.write("CURR:PROT:STAT ON,(@2)")
    session.write("CURR:PROT:DEL 0.5,(@2)")
    session.write("CURR:PROT:DEL:STAR CCTR,(@2)")

    assert session.query("VOLT:PROT? (@2)") == "5"
    assert session.query("CURR:PROT:STAT? (@2)") == "ON"
    assert session.query("CURR:PROT:DEL? (@2)") == "0.5"
    assert session.query("CURR:PROT:DEL:STAR? (@2)") == "CCTR"
    assert session.commands == [
        "VOLT:PROT 5,(@2)",
        "CURR:PROT:STAT ON,(@2)",
        "CURR:PROT:DEL 0.5,(@2)",
        "CURR:PROT:DEL:STAR CCTR,(@2)",
        "VOLT:PROT? (@2)",
        "CURR:PROT:STAT? (@2)",
        "CURR:PROT:DEL? (@2)",
        "CURR:PROT:DEL:STAR? (@2)",
    ]


def test_e36312a_simulator_tracks_trigger_list_state() -> None:
    session = SimulatedResourceManager().open_resource("USB0::SIM::E36312A::INSTR")

    session.write("DIG:PIN1:FUNC TOUT")
    session.write("DIG:PIN1:POL NEG")
    session.write("DIG:TOUT:BUS ON")
    session.write("LIST:VOLT 0,1,(@1)")
    session.write("LIST:CURR 0.05,0.05,(@1)")
    session.write("LIST:DWEL 0.01,0.02,(@1)")
    session.write("LIST:TOUT:EOST 0,1,(@1)")
    session.write("CURR:MODE LIST,(@1)")
    session.write("VOLT:MODE LIST,(@1)")
    session.write("TRIG:SOUR BUS,(@1)")
    session.write("INIT (@1)")
    session.write("*TRG")

    assert session.query("DIG:PIN1:FUNC?") == "TOUT"
    assert session.query("DIG:PIN1:POL?") == "NEG"
    assert session.query("DIG:TOUT:BUS?") == "ON"
    assert session.query("LIST:VOLT? (@1)") == "0,1"
    assert session.query("LIST:TOUT:EOST? (@1)") == "0,1"


def test_e36312a_simulator_accepts_fixed_trigger_modes() -> None:
    session = SimulatedResourceManager().open_resource("USB0::SIM::E36312A::INSTR")

    session.write("CURR:MODE FIX,(@1)")
    session.write("VOLT:MODE FIX,(@1)")

    assert session.query("CURR:MODE? (@1)") == "FIX"
    assert session.query("VOLT:MODE? (@1)") == "FIX"


def test_e36312a_simulator_supports_operation_complete_polling() -> None:
    session = SimulatedResourceManager().open_resource("USB0::SIM::E36312A::INSTR")

    session.write("*CLS")
    session.write("*ESE 1")
    session.write("*OPC")

    assert session.read_stb() & 32
    assert session.query("*ESR?") == "1"
    assert session.query("*ESR?") == "0"
