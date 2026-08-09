import pytest

from powers_tool_core.drivers.base import DriverCapabilities
from powers_tool_core.drivers.e36312a import E36312APowerSupply
from powers_tool_core.drivers.e3646a import E3646APowerSupply
from powers_tool_core.drivers.edu36311a import EDU36311APowerSupply
from powers_tool_core.drivers.generic_scpi import GenericScpiPowerSupply
from powers_tool_core.electrical_ratings import E36312A_ELECTRICAL_RATINGS, EDU36311A_ELECTRICAL_RATINGS
from powers_tool_core.factory import create_power_supply, select_driver
from powers_tool_core.core import UnsupportedModelError
from powers_tool_core.models import parse_idn


class FakeSession:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.closed = False

    def write(self, command: str) -> None:
        self.commands.append(command)

    def query(self, command: str) -> str:
        self.commands.append(command)
        return "0"

    def close(self) -> None:
        self.closed = True


def test_first_target_models_are_recognized() -> None:
    e36312a = select_driver("KEYSIGHT,E36312A,SERIAL0000,1.0")
    edu36311a = select_driver("KEYSIGHT,EDU36311A,SERIAL0000,1.0")

    assert e36312a.model_info is not None
    assert e36312a.model_info.first_hardware_target is True
    assert e36312a.physical_identity is not None
    assert e36312a.physical_identity.model_id == "keysight-e36312a"
    assert e36312a.driver_class is E36312APowerSupply
    assert e36312a.reason == "model_specific_driver"
    assert edu36311a.model_info is not None
    assert edu36311a.model_info.first_hardware_target is True
    assert edu36311a.driver_class is EDU36311APowerSupply
    assert edu36311a.reason == "model_specific_driver"

    e3646a = select_driver("KEYSIGHT,E3646A,SERIAL0000,1.0")
    assert e3646a.model_info is not None
    assert e3646a.driver_class is E3646APowerSupply
    assert e3646a.reason == "model_specific_driver"


def test_driver_selection_requires_resolved_manufacturer_plus_model_identity() -> None:
    wrong_vendor = select_driver("OTHER_VENDOR,E36312A,SERIAL0000,1.0")
    unknown_model = select_driver("KEYSIGHT,UNKNOWN,SERIAL0000,1.0")

    for selection in (wrong_vendor, unknown_model):
        assert selection.physical_identity is None
        assert selection.model_info is None
        assert selection.driver_class is GenericScpiPowerSupply
        assert selection.reason == "unknown_model_generic_fallback"


def test_narrow_p1_manufacturer_alias_selects_only_its_registered_model() -> None:
    e3646a = select_driver("Agilent Technologies,E3646A,SERIAL0000,1.0")
    e36312a = select_driver("Agilent Technologies,E36312A,SERIAL0000,1.0")

    assert e3646a.physical_identity is not None
    assert e3646a.physical_identity.model_id == "keysight-e3646a"
    assert e3646a.driver_class is E3646APowerSupply
    assert e36312a.physical_identity is None
    assert e36312a.driver_class is GenericScpiPowerSupply


def test_first_target_drivers_expose_conservative_capabilities() -> None:
    e36312a_expected = DriverCapabilities(
        channels=(1, 2, 3),
        simulated_measure_channels=(1, 2, 3),
        real_measure_channels=(1, 2, 3),
        electrical_ratings=E36312A_ELECTRICAL_RATINGS,
    )
    edu36311a_expected = DriverCapabilities(
        channels=(1, 2, 3),
        simulated_measure_channels=(1, 2, 3),
        real_measure_channels=(1, 2, 3),
        electrical_ratings=EDU36311A_ELECTRICAL_RATINGS,
    )

    e36312a = select_driver("KEYSIGHT,E36312A,SERIAL0000,1.0")
    edu36311a = select_driver("KEYSIGHT,EDU36311A,SERIAL0000,1.0")

    assert e36312a.capabilities == e36312a_expected
    assert edu36311a.capabilities == edu36311a_expected

    assert select_driver("KEYSIGHT,E3646A,SERIAL0000,1.0").capabilities == DriverCapabilities(
        channels=(1, 2),
        simulated_measure_channels=(1, 2),
        real_measure_channels=(1, 2),
    )


def test_descoped_models_are_blocked_from_generic_fallback() -> None:
    for model in ("E36103B", "E36232A"):
        with pytest.raises(UnsupportedModelError) as excinfo:
            select_driver(f"KEYSIGHT,{model},SERIAL0000,1.0")

        message = str(excinfo.value)
        assert model in message
        assert "de-scoped and not active supported" in message
        assert "blocked from generic fallback" in message


def test_descoped_model_create_power_supply_does_not_wrap_session() -> None:
    session = FakeSession()

    with pytest.raises(UnsupportedModelError):
        create_power_supply(session, "KEYSIGHT,E36103B,SERIAL0000,1.0")

    assert session.commands == []


def test_near_term_and_later_models_are_recognized() -> None:
    for model in (
        "E36313A",
        "E36233A",
        "E36441A",
        "E36155A",
    ):
        selection = select_driver(f"KEYSIGHT,{model},SERIAL0000,1.0")

        assert selection.model_info is not None
        assert selection.model_info.model == model
        assert selection.driver_class is GenericScpiPowerSupply
        assert selection.reason == "known_model_generic_fallback"


def test_unknown_model_falls_back_to_generic_driver() -> None:
    selection = select_driver("KEYSIGHT,UNKNOWN,SERIAL0000,1.0")

    assert selection.idn.parse_ok is True
    assert selection.model_info is None
    assert selection.driver_class is GenericScpiPowerSupply
    assert selection.reason == "unknown_model_generic_fallback"


def test_malformed_idn_falls_back_to_generic_driver_without_model_metadata() -> None:
    selection = select_driver("KEYSIGHT,E36312A")

    assert selection.idn.parse_ok is False
    assert selection.model_info is None
    assert selection.driver_class is GenericScpiPowerSupply
    assert selection.reason == "malformed_idn_generic_fallback"


def test_select_driver_accepts_preparsed_idn() -> None:
    parsed = parse_idn("KEYSIGHT,E36312A,SERIAL0000,1.0")

    selection = select_driver(parsed)

    assert selection.idn is parsed
    assert selection.model_info is not None
    assert selection.model_info.model == "E36312A"


def test_create_power_supply_wraps_session_without_commands() -> None:
    session = FakeSession()

    power_supply = create_power_supply(
        session,
        "KEYSIGHT,E36312A,SERIAL0000,1.0",
    )

    assert isinstance(power_supply, E36312APowerSupply)
    assert session.commands == []

def test_psm2010_catalog_identity_resolves_to_generic_fallback() -> None:
    selection = select_driver("GW.Inc,PSM-2010,SERIAL0000,1.0")

    assert selection.physical_identity is not None
    assert selection.physical_identity.model_id == "gw-instek-psm-2010"

    assert selection.model_info is not None
    assert selection.model_info.vendor_id == "gw-instek"
    assert selection.model_info.model == "PSM-2010"

    assert selection.driver_class is GenericScpiPowerSupply
    assert selection.reason == "known_model_generic_fallback"
