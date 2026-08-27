from powers_tool_core.models import (
    CANDIDATE_MODEL_IDS,
    CATALOG_ONLY_MODEL_IDS,
    REGISTERED_MODELS,
    PRODUCT_ACTIVE_MODEL_IDS,
    lookup_model,
    parse_idn,
    resource_interface,
)


def test_parse_standard_keysight_idn() -> None:
    idn = parse_idn("KEYSIGHT,E36312A,SERIAL0000,1.2.3")

    assert idn.raw == "KEYSIGHT,E36312A,SERIAL0000,1.2.3"
    assert idn.manufacturer == "KEYSIGHT"
    assert idn.model == "E36312A"
    assert idn.serial == "SERIAL0000"
    assert idn.firmware == "1.2.3"
    assert idn.parse_ok is True
    assert idn.to_dict() == {
        "raw": "KEYSIGHT,E36312A,SERIAL0000,1.2.3",
        "manufacturer": "KEYSIGHT",
        "model": "E36312A",
        "serial": "SERIAL0000",
        "firmware": "1.2.3",
        "parse_ok": True,
    }


def test_parse_idn_trims_fields() -> None:
    idn = parse_idn(" KEYSIGHT , E36103B , SERIAL0000 , 1.0 ")

    assert idn.manufacturer == "KEYSIGHT"
    assert idn.model == "E36103B"
    assert idn.serial == "SERIAL0000"
    assert idn.firmware == "1.0"
    assert idn.parse_ok is True


def test_parse_idn_missing_fields_are_none_and_not_ok() -> None:
    idn = parse_idn("KEYSIGHT,E36312A")

    assert idn.manufacturer == "KEYSIGHT"
    assert idn.model == "E36312A"
    assert idn.serial is None
    assert idn.firmware is None
    assert idn.parse_ok is False


def test_parse_idn_empty_fields_are_none_and_not_ok() -> None:
    idn = parse_idn("KEYSIGHT,E36312A,,1.0")

    assert idn.serial is None
    assert idn.firmware == "1.0"
    assert idn.parse_ok is False


def test_parse_idn_preserves_extra_commas_in_firmware() -> None:
    idn = parse_idn("KEYSIGHT,E36312A,SERIAL0000,1.2.3,build 4")

    assert idn.firmware == "1.2.3,build 4"
    assert idn.parse_ok is True


def test_resource_interface_detection() -> None:
    assert resource_interface("USB0::A::INSTR") == "USB"
    assert resource_interface("TCPIP0::192.0.2.1::INSTR") == "TCPIP"
    assert resource_interface("GPIB0::5::INSTR") == "GPIB"
    assert resource_interface("ASRL3::INSTR") == "ASRL"
    assert resource_interface("PXI0::1::INSTR") == "UNKNOWN"


def test_known_model_registry_lookup() -> None:
    assert set(REGISTERED_MODELS) == {
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e36313a",
        "keysight-e3646a",
        "keysight-e36233a",
        "keysight-e36441a",
        "keysight-e36155a",
        "gw-instek-psm-2010",
    }

    model = lookup_model("keysight-e36312a")

    assert model is not None
    assert model.manufacturer == "KEYSIGHT"
    assert model.model == "E36312A"
    assert model.model_id == "keysight-e36312a"
    assert model.vendor_id == "keysight"
    assert model.display_name == "Keysight E36312A"

    psm = lookup_model("gw-instek-psm-2010")
    assert psm is not None
    assert psm.manufacturer == "GW.Inc"
    assert psm.model == "PSM-2010"
    assert psm.enablement_stage == "product_active"
    assert psm.vendor_id == "gw-instek"
    assert psm.display_name == "GW Instek PSM-2010"

    assert lookup_model("E36312A") is None
    assert lookup_model("keysight-e36103b") is None
    assert lookup_model("keysight-e36232a") is None
    assert lookup_model("UNKNOWN") is None


def test_model_enablement_stages_are_explicit() -> None:
    assert PRODUCT_ACTIVE_MODEL_IDS == {
        "keysight-e36312a", "keysight-edu36311a", "keysight-e3646a",
        "gw-instek-psm-2010",
    }
    assert CANDIDATE_MODEL_IDS == set()
    assert CATALOG_ONLY_MODEL_IDS == {
        "keysight-e36313a",
        "keysight-e36233a",
        "keysight-e36441a",
        "keysight-e36155a",
    }
    assert {REGISTERED_MODELS[model].enablement_stage for model in PRODUCT_ACTIVE_MODEL_IDS} == {
        "product_active"
    }
    assert {REGISTERED_MODELS[model].enablement_stage for model in CANDIDATE_MODEL_IDS} == set()
    assert {REGISTERED_MODELS[model].enablement_stage for model in CATALOG_ONLY_MODEL_IDS} == {
        "catalog_only"
    }
