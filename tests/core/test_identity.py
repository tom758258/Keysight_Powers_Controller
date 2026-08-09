from dataclasses import FrozenInstanceError, fields, replace

import pytest

from powers_tool_core.drivers.e36312a import E36312APowerSupply
from powers_tool_core.drivers.generic_scpi import GenericScpiPowerSupply
from powers_tool_core.factory import select_driver
from powers_tool_core.identity import (
    GENERIC_SCPI_PLANNING_PROFILE_ID,
    IDENTITY_INDEXES,
    PHYSICAL_MODELS,
    VENDORS,
    IdentityMetadataError,
    IdentityResolutionError,
    PhysicalModelInfo,
    VendorInfo,
    build_identity_indexes,
    canonical_physical_model_id,
    canonical_planning_profile_id,
    normalize_manufacturer,
    normalize_model_name,
    planning_model_id_from_sim_resource,
    resolve_physical_model_identity,
    resolve_planning_model_id,
    validate_builtin_identity_inventory,
    validate_identity_inventory_mapping,
    validate_model_id,
    validate_profile_id,
    validate_vendor_id,
)
from powers_tool_core.models import (
    CANDIDATE_MODEL_IDS,
    CATALOG_ONLY_MODEL_IDS,
    DE_SCOPED_MODEL_IDS,
    PRODUCT_ACTIVE_MODEL_IDS,
    REGISTERED_MODELS,
    IdnInfo,
)


FROZEN_MODEL_IDS = {
    "keysight-e36312a",
    "keysight-edu36311a",
    "keysight-e3646a",
    "keysight-e36313a",
    "keysight-e36233a",
    "keysight-e36441a",
    "keysight-e36155a",
    "keysight-e36103b",
    "keysight-e36232a",
    "gw-instek-psm-2010",
}

FROZEN_REPORTED_MODELS = {
    "E36312A",
    "EDU36311A",
    "E3646A",
    "E36313A",
    "E36233A",
    "E36441A",
    "E36155A",
    "E36103B",
    "E36232A",
    "PSM-2010",
}

EXPECTED_MODEL_ID_BY_CANONICAL_MODEL = {
    "E36312A": "keysight-e36312a",
    "EDU36311A": "keysight-edu36311a",
    "E3646A": "keysight-e3646a",
    "E36313A": "keysight-e36313a",
    "E36233A": "keysight-e36233a",
    "E36441A": "keysight-e36441a",
    "E36155A": "keysight-e36155a",
    "E36103B": "keysight-e36103b",
    "E36232A": "keysight-e36232a",
    "PSM-2010": "gw-instek-psm-2010",
}

EXPECTED_DISPLAY_NAME_BY_MODEL_ID = {
    "keysight-e36312a": "Keysight E36312A",
    "keysight-edu36311a": "Keysight EDU36311A",
    "keysight-e3646a": "Keysight E3646A",
    "keysight-e36313a": "Keysight E36313A",
    "keysight-e36233a": "Keysight E36233A",
    "keysight-e36441a": "Keysight E36441A",
    "keysight-e36155a": "Keysight E36155A",
    "keysight-e36103b": "Keysight E36103B",
    "keysight-e36232a": "Keysight E36232A",
    "gw-instek-psm-2010": "GW Instek PSM-2010",
}


@pytest.mark.parametrize("value", ["keysight", "acme-labs", "v2"])
def test_valid_vendor_id_grammar(value: str) -> None:
    assert validate_vendor_id(value) == value


@pytest.mark.parametrize("value", ["keysight-e36312a", "acme-power-1"])
def test_valid_model_id_grammar(value: str) -> None:
    assert validate_model_id(value) == value


@pytest.mark.parametrize("value", ["generic-scpi", "planning", "profile-2"])
def test_valid_profile_id_grammar(value: str) -> None:
    assert validate_profile_id(value) == value


@pytest.mark.parametrize(
    ("validator", "value"),
    [
        (validate_vendor_id, "KEYSIGHT"),
        (validate_vendor_id, "keysight_power"),
        (validate_vendor_id, "-keysight"),
        (validate_vendor_id, "keysight-"),
        (validate_model_id, "E36312A"),
        (validate_model_id, "keysight"),
        (validate_model_id, "KEYSIGHT-E36312A"),
        (validate_model_id, "keysight_e36312a"),
        (validate_profile_id, "GENERIC-SCPI"),
        (validate_profile_id, "generic_scpi"),
        (validate_profile_id, ""),
    ],
)
def test_invalid_identifier_grammar_is_rejected(validator, value: str) -> None:
    with pytest.raises(IdentityResolutionError):
        validator(value)


def test_canonical_input_helpers_keep_physical_and_planning_identity_separate() -> None:
    assert canonical_physical_model_id(None) is None
    assert canonical_physical_model_id(" keysight-e36312a ") == "keysight-e36312a"
    assert canonical_planning_profile_id(None) is None
    assert canonical_planning_profile_id(" generic-scpi ") == "generic-scpi"

    for value in ("E36312A", "KEYSIGHT-E36312A", "keysight_e36312a", "generic-scpi"):
        with pytest.raises(IdentityResolutionError) as excinfo:
            canonical_physical_model_id(value)
        assert excinfo.value.reason == "invalid_model_id"
    with pytest.raises(IdentityResolutionError) as excinfo:
        canonical_physical_model_id("keysight-unknown")
    assert excinfo.value.reason == "unknown_model_id"
    with pytest.raises(IdentityResolutionError):
        canonical_planning_profile_id("keysight-e36312a")


def test_normalization_is_nfkc_whitespace_and_case_only() -> None:
    fullwidth_manufacturer = "".join(
        character if character == " " else chr(ord(character) + 0xFEE0)
        for character in "KEYSIGHT TECHNOLOGIES"
    )
    fullwidth_model = "".join(chr(ord(character) + 0xFEE0) for character in "E36312A")
    assert normalize_manufacturer(f"  {fullwidth_manufacturer}\t  ") == "keysight technologies"
    assert normalize_manufacturer("Straße") == "strasse"
    assert normalize_model_name(f"  {fullwidth_model}  ") == "e36312a"
    assert normalize_model_name(" E36312a ") == "e36312a"


def test_normalization_does_not_remove_punctuation_suffixes_or_hyphens() -> None:
    assert normalize_manufacturer("Keysight, Inc.") == "keysight, inc."
    assert normalize_model_name("E-36312A") == "e-36312a"
    for manufacturer in ("KEYSIGHT, INC.", "KEYSIGHT INC", "KEYSIGHT-TECHNOLOGIES"):
        with pytest.raises(IdentityResolutionError) as excinfo:
            resolve_physical_model_identity(manufacturer, "E36312A")
        assert excinfo.value.reason == "unknown_manufacturer"
    with pytest.raises(IdentityResolutionError) as excinfo:
        resolve_physical_model_identity("KEYSIGHT", "E-36312A")
    assert excinfo.value.reason == "unknown_model"


def test_non_ascii_model_content_and_control_content_are_rejected() -> None:
    with pytest.raises(IdentityResolutionError) as excinfo:
        resolve_physical_model_identity("KEYSIGHT", "E36312Ä")
    assert excinfo.value.reason == "invalid_model"
    with pytest.raises(IdentityResolutionError) as excinfo:
        resolve_physical_model_identity("KEY\x00SIGHT", "E36312A")
    assert excinfo.value.reason == "invalid_manufacturer"


def test_builtin_records_are_frozen_and_fields_are_independent() -> None:
    vendor = VENDORS[0]
    model = PHYSICAL_MODELS[0]
    with pytest.raises(FrozenInstanceError):
        vendor.vendor_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        model.model_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        model.display_name = "changed"  # type: ignore[misc]
    assert "display_name" in {field.name for field in fields(PhysicalModelInfo)}
    assert model.model_id == "keysight-e36312a"
    assert model.vendor_id == "keysight"
    assert model.canonical_model == "E36312A"
    assert model.display_name == "Keysight E36312A"


def test_builtin_identity_inventory_exactly_covers_legacy_inventory() -> None:
    validate_builtin_identity_inventory()
    assert set(IDENTITY_INDEXES.models_by_id) == FROZEN_MODEL_IDS
    assert {model.canonical_model for model in PHYSICAL_MODELS} == FROZEN_REPORTED_MODELS
    assert {model.model_id for model in PHYSICAL_MODELS} == set(REGISTERED_MODELS) | set(DE_SCOPED_MODEL_IDS)
    assert all(model.vendor_id in IDENTITY_INDEXES.vendors_by_id for model in PHYSICAL_MODELS)
    assert GENERIC_SCPI_PLANNING_PROFILE_ID not in IDENTITY_INDEXES.models_by_id


def test_builtin_identity_inventory_has_exact_frozen_mappings_and_display_names() -> None:
    assert {
        model.canonical_model: model.model_id for model in PHYSICAL_MODELS
    } == EXPECTED_MODEL_ID_BY_CANONICAL_MODEL
    assert {
        model.model_id: model.display_name for model in PHYSICAL_MODELS
    } == EXPECTED_DISPLAY_NAME_BY_MODEL_ID


def test_exact_inventory_mapping_rejects_swapped_same_vendor_model_ids() -> None:
    swapped = list(PHYSICAL_MODELS)
    swapped[0] = replace(swapped[0], model_id="keysight-e3646a")
    swapped[2] = replace(swapped[2], model_id="keysight-e36312a")

    assert {model.model_id for model in swapped} == FROZEN_MODEL_IDS
    assert {model.canonical_model for model in swapped} == FROZEN_REPORTED_MODELS
    with pytest.raises(IdentityMetadataError) as excinfo:
        validate_identity_inventory_mapping(swapped, EXPECTED_MODEL_ID_BY_CANONICAL_MODEL)
    assert excinfo.value.reason == "invalid_identity_metadata"


def test_canonical_lifecycle_sets_preserve_assignments() -> None:
    assert PRODUCT_ACTIVE_MODEL_IDS == {"keysight-e36312a", "keysight-edu36311a", "keysight-e3646a"}
    assert CANDIDATE_MODEL_IDS == {"gw-instek-psm-2010"}
    assert CATALOG_ONLY_MODEL_IDS == {
        "keysight-e36313a",
        "keysight-e36233a",
        "keysight-e36441a",
        "keysight-e36155a",
    }
    assert DE_SCOPED_MODEL_IDS == {"keysight-e36103b", "keysight-e36232a"}


@pytest.mark.parametrize(
    ("manufacturer", "model", "model_id"),
    [
        ("KEYSIGHT", "E36312A", "keysight-e36312a"),
        (" keysight ", " edu36311a ", "keysight-edu36311a"),
        ("Keysight   Technologies", "e3646a", "keysight-e3646a"),
        ("KEYSIGHT", "E36313A", "keysight-e36313a"),
        ("KEYSIGHT", "E36233A", "keysight-e36233a"),
        ("KEYSIGHT", "E36441A", "keysight-e36441a"),
        ("KEYSIGHT", "E36155A", "keysight-e36155a"),
        ("KEYSIGHT", "E36103B", "keysight-e36103b"),
        ("KEYSIGHT", "E36232A", "keysight-e36232a"),
    ],
)
def test_builtin_resolver_recognizes_all_physical_identities(
    manufacturer: str,
    model: str,
    model_id: str,
) -> None:
    resolved = resolve_physical_model_identity(manufacturer, model)
    assert resolved.reported_manufacturer == manufacturer
    assert resolved.reported_model == model
    assert resolved.vendor_id == "keysight"
    assert resolved.model_id == model_id


def test_builtin_resolver_recognizes_gw_instek_psm_2010_identity() -> None:
    vendor = IDENTITY_INDEXES.vendors_by_id["gw-instek"]
    model = IDENTITY_INDEXES.models_by_id["gw-instek-psm-2010"]

    assert vendor.display_name == "GW Instek"
    assert vendor.canonical_manufacturer == "GW.Inc"
    assert vendor.manufacturer_aliases == ()
    assert model.vendor_id == "gw-instek"
    assert model.canonical_model == "PSM-2010"
    assert model.display_name == "GW Instek PSM-2010"
    assert model.model_aliases == ()

    resolved = resolve_physical_model_identity("  gw.inc  ", "  psm-2010  ")
    assert resolved.vendor_id == "gw-instek"
    assert resolved.model_id == "gw-instek-psm-2010"
    assert resolved.canonical_model == "PSM-2010"


def test_historical_manufacturer_alias_is_narrow_and_evidence_backed() -> None:
    assert resolve_physical_model_identity("Agilent Technologies", "E3646A").model_id == "keysight-e3646a"
    with pytest.raises(IdentityResolutionError) as excinfo:
        resolve_physical_model_identity("Agilent Technologies", "E36312A")
    assert excinfo.value.reason == "manufacturer_model_mismatch"
    for manufacturer in ("AGILENT", "HP", "Hewlett-Packard"):
        with pytest.raises(IdentityResolutionError) as excinfo:
            resolve_physical_model_identity(manufacturer, "E3646A")
        assert excinfo.value.reason == "unknown_manufacturer"


@pytest.mark.parametrize(
    ("manufacturer", "model", "reason"),
    [
        (None, "E36312A", "missing_manufacturer"),
        ("KEYSIGHT", None, "missing_model"),
        ("  ", "E36312A", "missing_manufacturer"),
        ("KEYSIGHT", "  ", "missing_model"),
        ("UNKNOWN", "E36312A", "unknown_manufacturer"),
        ("KEYSIGHT", "UNKNOWN", "unknown_model"),
        ("KEYSIGHT", "PSM-2010", "manufacturer_model_mismatch"),
        ("GW.Inc", "E36312A", "manufacturer_model_mismatch"),
        ("GW INSTEK", "PSM-2010", "unknown_manufacturer"),
        ("GW.Inc", "PSM2010", "unknown_model"),
    ],
)
def test_resolver_fails_closed(manufacturer, model, reason: str) -> None:
    with pytest.raises(IdentityResolutionError) as excinfo:
        resolve_physical_model_identity(manufacturer, model)
    assert excinfo.value.reason == reason


def test_resolver_has_no_model_only_or_manufacturer_only_api() -> None:
    with pytest.raises(IdentityResolutionError) as excinfo:
        resolve_physical_model_identity(None, "E36312A")
    assert excinfo.value.reason == "missing_manufacturer"
    with pytest.raises(IdentityResolutionError) as excinfo:
        resolve_physical_model_identity("KEYSIGHT", None)
    assert excinfo.value.reason == "missing_model"


def _synthetic_metadata():
    vendors = (
        VendorInfo("acme", "Acme", "ACME", ("ACME CORP",)),
        VendorInfo("other", "Other", "OTHER"),
    )
    models = (
        PhysicalModelInfo("acme-one", "acme", "ONE", "Acme One", ("ONE-A",)),
        PhysicalModelInfo("other-one", "other", "ONE", "Other One"),
        PhysicalModelInfo("other-two", "other", "TWO", "Other Two"),
    )
    return vendors, models


def test_reported_model_names_need_not_be_globally_unique() -> None:
    vendors, models = _synthetic_metadata()
    indexes = build_identity_indexes(vendors, models)
    assert resolve_physical_model_identity("ACME", "ONE", indexes=indexes).model_id == "acme-one"
    assert resolve_physical_model_identity("OTHER", "ONE", indexes=indexes).model_id == "other-one"
    with pytest.raises(IdentityResolutionError) as excinfo:
        resolve_physical_model_identity("ACME", "TWO", indexes=indexes)
    assert excinfo.value.reason == "manufacturer_model_mismatch"


def test_explicit_model_alias_resolves_only_for_its_vendor() -> None:
    vendors, models = _synthetic_metadata()
    indexes = build_identity_indexes(vendors, models)
    assert resolve_physical_model_identity("ACME", "ONE-A", indexes=indexes).model_id == "acme-one"
    with pytest.raises(IdentityResolutionError) as excinfo:
        resolve_physical_model_identity("OTHER", "ONE-A", indexes=indexes)
    assert excinfo.value.reason == "manufacturer_model_mismatch"


@pytest.mark.parametrize("display_name", ["", "   ", None, 123, "\u200b"])
def test_model_display_name_must_be_nonempty_safe_text(display_name) -> None:
    vendors = (VendorInfo("acme", "Acme", "ACME"),)
    models = (
        PhysicalModelInfo(
            "acme-one",
            "acme",
            "ONE",
            display_name,  # type: ignore[arg-type]
        ),
    )
    with pytest.raises(IdentityMetadataError) as excinfo:
        build_identity_indexes(vendors, models)
    assert excinfo.value.reason == "invalid_identity_metadata"


def test_display_name_is_independent_presentation_metadata_only() -> None:
    vendors = (VendorInfo("acme", "Acme", "ACME"),)
    display_name = "  Ａｃｍｅ   One  "
    model = PhysicalModelInfo("acme-one", "acme", "ONE", display_name)
    indexes = build_identity_indexes(vendors, (model,))

    assert indexes.models_by_id["acme-one"].display_name == display_name
    assert resolve_physical_model_identity("ACME", "ONE", indexes=indexes).model_id == "acme-one"


@pytest.mark.parametrize(
    ("vendors", "model"),
    [
        (
            (VendorInfo("acme", "Acme", "ACME"),),
            PhysicalModelInfo("other-one", "acme", "ONE", "Acme One"),
        ),
        (
            (VendorInfo("acme", "Acme", "ACME"),),
            PhysicalModelInfo("keysight-e36312a", "acme", "ONE", "Acme One"),
        ),
        (
            (VendorInfo("acme-labs", "Acme Labs", "ACME LABS"),),
            PhysicalModelInfo("acme-one", "acme-labs", "ONE", "Acme Labs One"),
        ),
        (
            (
                VendorInfo("acme", "Acme", "ACME"),
                VendorInfo("acme-labs", "Acme Labs", "ACME LABS"),
            ),
            PhysicalModelInfo("acme-labs-one", "acme", "ONE", "Acme One"),
        ),
        (
            (VendorInfo("acme", "Acme", "ACME"),),
            PhysicalModelInfo("unknown-vendor-one", "acme", "ONE", "Acme One"),
        ),
        (
            (VendorInfo("acme", "Acme", "ACME"),),
            PhysicalModelInfo("generic-scpi", "acme", "ONE", "Generic SCPI"),
        ),
    ],
)
def test_model_id_must_belong_to_its_independently_stored_vendor(vendors, model) -> None:
    with pytest.raises(IdentityMetadataError) as excinfo:
        build_identity_indexes(vendors, (model,))
    assert excinfo.value.reason == "invalid_identity_metadata"


@pytest.mark.parametrize(
    ("vendors", "model"),
    [
        (
            (VendorInfo("acme", "Acme", "ACME"),),
            PhysicalModelInfo("acme-one", "acme", "ONE", "Acme One"),
        ),
        (
            (VendorInfo("acme-labs", "Acme Labs", "ACME LABS"),),
            PhysicalModelInfo("acme-labs-one", "acme-labs", "ONE", "Acme Labs One"),
        ),
        (
            (
                VendorInfo("acme", "Acme", "ACME"),
                VendorInfo("acme-labs", "Acme Labs", "ACME LABS"),
            ),
            PhysicalModelInfo("acme-labs-one", "acme-labs", "ONE", "Acme Labs One"),
        ),
    ],
)
def test_model_id_accepts_exact_registered_vendor_ownership(vendors, model) -> None:
    indexes = build_identity_indexes(vendors, (model,))
    assert indexes.models_by_id[model.model_id] is model


@pytest.mark.parametrize(
    "models",
    [
        PHYSICAL_MODELS[:-1],
        PHYSICAL_MODELS
        + (PhysicalModelInfo("keysight-extra", "keysight", "EXTRA", "Keysight Extra"),),
        PHYSICAL_MODELS + (PHYSICAL_MODELS[0],),
        (replace(PHYSICAL_MODELS[0], model_id="keysight-wrong"),) + PHYSICAL_MODELS[1:],
    ],
)
def test_exact_inventory_mapping_rejects_missing_extra_duplicate_and_wrong_models(models) -> None:
    with pytest.raises(IdentityMetadataError) as excinfo:
        validate_identity_inventory_mapping(models, EXPECTED_MODEL_ID_BY_CANONICAL_MODEL)
    assert excinfo.value.reason == "invalid_identity_metadata"


@pytest.mark.parametrize(
    ("vendors", "models"),
    [
        ((VendorInfo("bad_vendor", "Bad", "BAD"),), ()),
        ((VendorInfo("acme", "", "ACME"),), ()),
        ((VendorInfo("acme", "Acme", ""),), ()),
        ((VendorInfo("acme", "Acme", "ACME"), VendorInfo("acme", "Again", "AGAIN")), ()),
        ((VendorInfo("acme", "Acme", "ACME", (" A ", "a")),), ()),
        (
            (VendorInfo("acme", "Acme", "ACME", ("SHARED",)), VendorInfo("other", "Other", "OTHER", ("shared",))),
            (),
        ),
        ((VendorInfo("acme", "Acme", "ACME"),), (PhysicalModelInfo("ONE", "acme", "ONE", "Acme One"),)),
        ((VendorInfo("acme", "Acme", "ACME"),), (PhysicalModelInfo("generic-scpi", "acme", "ONE", "Acme One"),)),
        ((VendorInfo("acme", "Acme", "ACME"),), (PhysicalModelInfo("acme-one", "missing", "ONE", "Acme One"),)),
        (
            (VendorInfo("acme", "Acme", "ACME"),),
            (
                PhysicalModelInfo("acme-one", "acme", "ONE", "Acme One"),
                PhysicalModelInfo("acme-one", "acme", "TWO", "Acme Two"),
            ),
        ),
        (
            (VendorInfo("acme", "Acme", "ACME"),),
            (PhysicalModelInfo("acme-one", "acme", "ONE", "Acme One", (" one-a ", "ONE-A")),),
        ),
        (
            (VendorInfo("acme", "Acme", "ACME"),),
            (
                PhysicalModelInfo("acme-one", "acme", "ONE", "Acme One", ("TWO",)),
                PhysicalModelInfo("acme-two", "acme", "TWO", "Acme Two"),
            ),
        ),
        (
            (VendorInfo("acme", "Acme", "ACME"), VendorInfo("other", "Other", "OTHER", ("OTHER CORP",))),
            (
                PhysicalModelInfo(
                    "acme-one",
                    "acme",
                    "ONE",
                    "Acme One",
                    manufacturer_aliases=("OTHER CORP",),
                ),
            ),
        ),
    ],
)
def test_metadata_validation_rejects_malformed_duplicates_and_collisions(vendors, models) -> None:
    with pytest.raises(IdentityMetadataError) as excinfo:
        build_identity_indexes(vendors, models)
    assert excinfo.value.reason == "invalid_identity_metadata"


def test_same_vendor_level_and_model_specific_manufacturer_alias_may_coexist() -> None:
    vendors = (VendorInfo("acme", "Acme", "ACME", ("ACME CORP",)),)
    models = (
        PhysicalModelInfo(
            "acme-one",
            "acme",
            "ONE",
            "Acme One",
            manufacturer_aliases=("acme corp",),
        ),
    )
    indexes = build_identity_indexes(vendors, models)
    assert resolve_physical_model_identity("ACME CORP", "ONE", indexes=indexes).model_id == "acme-one"


@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        ("USB0::SIM::E36312A::INSTR", "keysight-e36312a"),
        ("USB0::SIM::EDU36311A::INSTR", "keysight-edu36311a"),
        ("ASRL1::SIM::E3646A::INSTR", "keysight-e3646a"),
        ("ASRL1::SIM::PSM2010::INSTR", "gw-instek-psm-2010"),
    ],
)
def test_deterministic_sim_resources_infer_v2_model_ids(resource: str, expected: str) -> None:
    assert planning_model_id_from_sim_resource(resource) == expected
    assert resolve_planning_model_id(expected, resource) == expected


@pytest.mark.parametrize(
    "resource",
    [
        None,
        "",
        "USB0::FAKE::E36312A::INSTR",
        "USB0::E36312A::SERIAL::INSTR",
        "TCPIP0::192.0.2.1::INSTR",
        "ASRL1::INSTR",
        "not a resource E36312A",
    ],
)
def test_unknown_fake_live_and_malformed_resources_do_not_infer(resource) -> None:
    assert planning_model_id_from_sim_resource(resource) is None


def test_explicit_and_inferred_sim_identity_must_agree() -> None:
    with pytest.raises(IdentityResolutionError) as excinfo:
        resolve_planning_model_id("keysight-e3646a", "USB0::SIM::E36312A::INSTR")
    assert excinfo.value.reason == "model_id_mismatch"
    assert resolve_planning_model_id("keysight-e3646a", "TCPIP0::192.0.2.1::INSTR") == "keysight-e3646a"
    assert resolve_planning_model_id(None, "USB0::FAKE::E36312A::INSTR") is None
    assert planning_model_id_from_sim_resource("USB0::SIM::GENERIC::INSTR") is None


def test_existing_sim_resolution_remains_legacy_planning_model_id() -> None:
    assert planning_model_id_from_sim_resource("USB0::SIM::E36312A::INSTR") == "keysight-e36312a"
    assert planning_model_id_from_sim_resource("USB0::SIM::EDU36311A::INSTR") == "keysight-edu36311a"
    assert planning_model_id_from_sim_resource("ASRL1::SIM::E3646A::INSTR") == "keysight-e3646a"
    assert planning_model_id_from_sim_resource("ASRL1::SIM::PSM2010::INSTR") == "gw-instek-psm-2010"


def test_existing_factory_selection_and_public_idn_json_are_unchanged() -> None:
    assert select_driver("KEYSIGHT,E36312A,SERIAL0000,1.0").driver_class is E36312APowerSupply
    assert select_driver("KEYSIGHT,UNKNOWN,SERIAL0000,1.0").driver_class is GenericScpiPowerSupply
    idn = IdnInfo("KEYSIGHT,E36312A,SERIAL0000,1.0", "KEYSIGHT", "E36312A", "SERIAL0000", "1.0", True)
    assert idn.to_dict() == {
        "raw": "KEYSIGHT,E36312A,SERIAL0000,1.0",
        "manufacturer": "KEYSIGHT",
        "model": "E36312A",
        "serial": "SERIAL0000",
        "firmware": "1.0",
        "parse_ok": True,
    }
