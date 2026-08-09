import re
from dataclasses import replace
from pathlib import Path

import pytest

from powers_tool_core.drivers.generic_scpi import GenericScpiPowerSupply
from powers_tool_core.identity import canonical_physical_model_id
from powers_tool_core.model_enablement import (
    ModelEnablementInventory,
    current_model_enablement_inventory,
    validate_model_enablement,
)
from powers_tool_core.models import (
    CANDIDATE_MODEL_IDS,
    CATALOG_ONLY_MODEL_IDS,
    DE_SCOPED_MODEL_IDS,
    PRODUCT_ACTIVE_MODEL_IDS,
)
from powers_tool_core.support_policy import (
    BACKEND_SYSTEM_VISA,
    TRANSPORT_USB,
    VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
    VALIDATION_STATUS_FEATURE_PENDING,
    VALIDATION_STATUS_PROFILE_VALIDATED,
    VALIDATION_STATUS_TRANSPORT_PENDING,
    CommandLiveSupportScope,
    CommandFeatureSupportScope,
    CommandSupportPolicy,
    ModelSupportPolicy,
)
from powers_tool_core.support_features import (
    FEATURE_KIND_SEQUENCE_ACTION,
    FEATURE_KIND_TRIGGER_SOURCE,
)

SYNTHETIC_CANDIDATE_MODEL_ID = "keysight-e36313a"


def _synthetic_candidate() -> ModelEnablementInventory:
    current = current_model_enablement_inventory()
    model = SYNTHETIC_CANDIDATE_MODEL_ID
    policy = ModelSupportPolicy(
        model_id="keysight-e36313a",
        commands=(
            CommandSupportPolicy(
                command="measure",
                validation_status=VALIDATION_STATUS_PROFILE_VALIDATED,
                scopes=(
                    CommandLiveSupportScope(
                        validation_status=VALIDATION_STATUS_TRANSPORT_PENDING,
                        transport_scope=TRANSPORT_USB,
                        backend_scope=BACKEND_SYSTEM_VISA,
                        note="Synthetic candidate pending validation.",
                    ),
                ),
            ),
        ),
    )
    return replace(
        current,
        model_stages={**current.model_stages, model: "candidate"},
        candidate_model_ids=current.candidate_model_ids | {model},
        channels={**current.channels, model: (1,)},
        simulator_resources={**current.simulator_resources, model: "USB0::SIM::E36313A::INSTR"},
        simulator_idns={**current.simulator_idns, model: "KEYSIGHT,E36313A,SIM000001,1.0"},
        drivers={**current.drivers, model: type("SynthPowerSupply", (), {})},
        command_capabilities={
            **current.command_capabilities,
            model: {"measure": {"real": True, "simulate": True, "dry_run": True}},
        },
        live_policies={**current.live_policies, model: policy},
        safety_validated_models=current.safety_validated_models | {model},
        no_hardware_covered_models=current.no_hardware_covered_models | {model},
    )


def _candidate_with_output_metadata(
    *, ratings: bool, ranges: bool
) -> ModelEnablementInventory:
    candidate = _synthetic_candidate()
    model = SYNTHETIC_CANDIDATE_MODEL_ID
    capabilities = {
        **candidate.command_capabilities[model],
        "set": {"real": True, "simulate": True, "dry_run": True},
    }
    measure_policy = candidate.live_policies[model].commands[0]
    policy = replace(
        candidate.live_policies[model],
        commands=(measure_policy, replace(measure_policy, command="set")),
    )
    return replace(
        candidate,
        command_capabilities={**candidate.command_capabilities, model: capabilities},
        live_policies={**candidate.live_policies, model: policy},
        electrical_rating_models=(
            candidate.electrical_rating_models | {model}
            if ratings
            else candidate.electrical_rating_models - {model}
        ),
        setpoint_range_models=(
            candidate.setpoint_range_models | {model}
            if ranges
            else candidate.setpoint_range_models - {model}
        ),
    )


def _candidate_with_feature_command(
    command: str,
    expected_features: frozenset[tuple[str, str]],
    feature_scopes: tuple[CommandFeatureSupportScope, ...],
) -> ModelEnablementInventory:
    candidate = _synthetic_candidate()
    model = SYNTHETIC_CANDIDATE_MODEL_ID
    measure_policy = candidate.live_policies[model].commands[0]
    feature_policy = CommandSupportPolicy(
        command=command,
        validation_status=VALIDATION_STATUS_PROFILE_VALIDATED,
        scopes=(
            CommandLiveSupportScope(
                validation_status=VALIDATION_STATUS_TRANSPORT_PENDING,
                transport_scope=TRANSPORT_USB,
                backend_scope=BACKEND_SYSTEM_VISA,
                note="Synthetic candidate pending validation.",
                feature_scopes=feature_scopes,
            ),
        ),
    )
    capabilities = {
        **candidate.command_capabilities[model],
        command: {"real": True, "simulate": True, "dry_run": True},
    }
    return replace(
        candidate,
        command_capabilities={**candidate.command_capabilities, model: capabilities},
        live_policies={
            **candidate.live_policies,
            model: replace(
                candidate.live_policies[model],
                commands=(measure_policy, feature_policy),
            ),
        },
        feature_inventories={
            **candidate.feature_inventories,
            model: {command: expected_features},
        },
        electrical_rating_models=candidate.electrical_rating_models | {model},
        setpoint_range_models=candidate.setpoint_range_models | {model},
    )


def test_current_model_enablement_stage_sets_are_exact_and_disjoint() -> None:
    assert PRODUCT_ACTIVE_MODEL_IDS == {"keysight-e36312a", "keysight-edu36311a", "keysight-e3646a"}
    assert CANDIDATE_MODEL_IDS == frozenset()
    assert CATALOG_ONLY_MODEL_IDS == {
        "keysight-e36313a",
        "keysight-e36233a",
        "keysight-e36441a",
        "keysight-e36155a",
        "gw-instek-psm-2010",
    }
    assert DE_SCOPED_MODEL_IDS == {"keysight-e36103b", "keysight-e36232a"}
    stage_sets = [PRODUCT_ACTIVE_MODEL_IDS, CANDIDATE_MODEL_IDS, CATALOG_ONLY_MODEL_IDS, DE_SCOPED_MODEL_IDS]
    assert all(not left & right for index, left in enumerate(stage_sets) for right in stage_sets[index + 1 :])


def test_current_model_enablement_inventory_is_consistent() -> None:
    inventory = current_model_enablement_inventory()
    assert "keysight-e3646a" not in inventory.electrical_rating_models
    assert "keysight-e3646a" in inventory.setpoint_range_models
    assert inventory.product_rating_compatibility_models == {"keysight-e3646a"}
    assert inventory.planning_profiles == {"generic-scpi"}
    validate_model_enablement(inventory)


def test_all_physical_enablement_registries_use_canonical_model_ids() -> None:
    inventory = current_model_enablement_inventory()
    registries = (
        inventory.model_stages,
        inventory.channels,
        inventory.simulator_resources,
        inventory.drivers,
        inventory.command_capabilities,
        inventory.live_policies,
        inventory.feature_inventories,
    )
    model_sets = (
        inventory.product_model_ids,
        inventory.candidate_model_ids,
        inventory.electrical_rating_models,
        inventory.setpoint_range_models,
        inventory.product_rating_compatibility_models,
        inventory.safety_validated_models,
        inventory.no_hardware_covered_models,
    )

    for values in registries:
        assert all(canonical_physical_model_id(model_id) == model_id for model_id in values)
        assert "GENERIC" not in values
        assert "generic-scpi" not in values
    for values in model_sets:
        assert all(canonical_physical_model_id(model_id) == model_id for model_id in values)
        assert "GENERIC" not in values
        assert "generic-scpi" not in values


def test_complete_synthetic_candidate_inventory_passes() -> None:
    validate_model_enablement(_synthetic_candidate())


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("channels", {}, "missing channel inventory"),
        ("simulator_resources", {}, "missing deterministic simulator resource"),
        ("simulator_idns", {}, "missing deterministic matching simulator IDN"),
        ("drivers", {}, "missing model-specific driver mapping"),
        ("command_capabilities", {}, "missing command capability metadata"),
        ("live_policies", {}, "missing live support-policy metadata"),
        ("safety_validated_models", frozenset(), "missing safety validation coverage"),
        ("no_hardware_covered_models", frozenset(), "missing simulator/fake/no-hardware coverage"),
    ],
)
def test_candidate_missing_one_prerequisite_fails_precisely(
    field: str, value: object, match: str
) -> None:
    candidate = _synthetic_candidate()
    current_value = getattr(candidate, field)
    if isinstance(current_value, dict):
        replacement = {key: item for key, item in current_value.items() if key != SYNTHETIC_CANDIDATE_MODEL_ID}
    else:
        replacement = current_value - {SYNTHETIC_CANDIDATE_MODEL_ID}
    with pytest.raises(ValueError, match=match):
        validate_model_enablement(replace(candidate, **{field: replacement}))


def test_candidate_cannot_use_generic_driver_fallback() -> None:
    candidate = _synthetic_candidate()
    with pytest.raises(ValueError, match="Generic driver fallback"):
        validate_model_enablement(
            replace(candidate, drivers={**candidate.drivers, SYNTHETIC_CANDIDATE_MODEL_ID: GenericScpiPowerSupply})
        )


def test_candidate_cannot_have_product_open_scope() -> None:
    candidate = _synthetic_candidate()
    policy = candidate.live_policies[SYNTHETIC_CANDIDATE_MODEL_ID]
    command = policy.commands[0]
    validated_scope = replace(
        command.scopes[0],
        validation_status=VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
        accepted_evidence_ids=("synthetic-accepted-evidence",),
    )
    changed = replace(policy, commands=(replace(command, scopes=(validated_scope,)),))
    with pytest.raises(ValueError, match="not exclusively pending|accidental Product-open"):
        validate_model_enablement(
            replace(candidate, live_policies={**candidate.live_policies, SYNTHETIC_CANDIDATE_MODEL_ID: changed})
        )


@pytest.mark.parametrize(
    ("ratings", "ranges", "match"),
    [
        (False, True, "missing electrical ratings"),
        (True, False, "missing setpoint range/limit metadata"),
    ],
)
def test_output_candidate_requires_ratings_and_ranges_independently(
    ratings: bool, ranges: bool, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        validate_model_enablement(
            _candidate_with_output_metadata(ratings=ratings, ranges=ranges)
        )


def test_output_candidate_with_ratings_and_ranges_passes() -> None:
    validate_model_enablement(
        _candidate_with_output_metadata(ratings=True, ranges=True)
    )


def test_candidate_cannot_use_product_rating_compatibility_exception() -> None:
    candidate = _candidate_with_output_metadata(ratings=False, ranges=True)
    candidate = replace(
        candidate,
        product_rating_compatibility_models=(
            candidate.product_rating_compatibility_models | {SYNTHETIC_CANDIDATE_MODEL_ID}
        ),
    )
    with pytest.raises(ValueError, match="missing electrical ratings"):
        validate_model_enablement(candidate)


def _pending_feature(kind: str, value: str) -> CommandFeatureSupportScope:
    return CommandFeatureSupportScope(
        feature_kind=kind,
        feature_value=value,
        validation_status=VALIDATION_STATUS_FEATURE_PENDING,
        note="Synthetic candidate feature pending validation.",
    )


def test_candidate_sequence_requires_complete_pending_feature_inventory() -> None:
    expected = frozenset(
        {
            (FEATURE_KIND_SEQUENCE_ACTION, "set"),
            (FEATURE_KIND_SEQUENCE_ACTION, "safe-off"),
        }
    )
    complete = (
        _pending_feature(FEATURE_KIND_SEQUENCE_ACTION, "set"),
        _pending_feature(FEATURE_KIND_SEQUENCE_ACTION, "safe-off"),
    )
    validate_model_enablement(
        _candidate_with_feature_command("sequence", expected, complete)
    )

    with pytest.raises(ValueError, match="lacks canonical feature inventory"):
        validate_model_enablement(
            replace(
                _candidate_with_feature_command("sequence", expected, complete),
                feature_inventories={},
            )
        )
    with pytest.raises(ValueError, match="feature inventory drift"):
        validate_model_enablement(
            _candidate_with_feature_command("sequence", expected, complete[:1])
        )


def test_candidate_sequence_features_must_all_remain_pending() -> None:
    expected = frozenset({(FEATURE_KIND_SEQUENCE_ACTION, "set")})
    validated = replace(
        _pending_feature(FEATURE_KIND_SEQUENCE_ACTION, "set"),
        validation_status=VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
    )
    with pytest.raises(ValueError, match="invalid for exact parent scope"):
        validate_model_enablement(
            _candidate_with_feature_command("sequence", expected, (validated,))
        )


def test_candidate_trigger_requires_complete_model_derived_source_inventory() -> None:
    expected = frozenset(
        {
            (FEATURE_KIND_TRIGGER_SOURCE, "bus"),
            (FEATURE_KIND_TRIGGER_SOURCE, "immediate"),
        }
    )
    with pytest.raises(ValueError, match="feature inventory drift"):
        validate_model_enablement(
            _candidate_with_feature_command(
                "trigger-step",
                expected,
                (_pending_feature(FEATURE_KIND_TRIGGER_SOURCE, "bus"),),
            )
        )


@pytest.mark.parametrize(
    ("features", "match"),
    [
        (
            (
                _pending_feature(FEATURE_KIND_SEQUENCE_ACTION, "set"),
                _pending_feature(FEATURE_KIND_SEQUENCE_ACTION, "set"),
            ),
            "duplicate feature scope",
        ),
        (
            (_pending_feature("future_kind", "set"),),
            "unsupported feature kind",
        ),
        (
            (
                replace(
                    _pending_feature(FEATURE_KIND_SEQUENCE_ACTION, "set"),
                    validation_status="future",
                ),
            ),
            "unknown feature validation status",
        ),
        (
            (_pending_feature(FEATURE_KIND_SEQUENCE_ACTION, " SET "),),
            "noncanonical feature value",
        ),
    ],
)
def test_candidate_rejects_invalid_feature_metadata(
    features: tuple[CommandFeatureSupportScope, ...], match: str
) -> None:
    expected = frozenset({(FEATURE_KIND_SEQUENCE_ACTION, "set")})
    with pytest.raises(ValueError, match=match):
        validate_model_enablement(
            _candidate_with_feature_command("sequence", expected, features)
        )


def test_catalog_and_descoped_models_do_not_leak_into_active_registries() -> None:
    inventory = current_model_enablement_inventory()
    forbidden = CATALOG_ONLY_MODEL_IDS | DE_SCOPED_MODEL_IDS
    assert forbidden.isdisjoint(inventory.drivers)
    assert forbidden.isdisjoint(inventory.simulator_resources)
    assert forbidden.isdisjoint(inventory.live_policies)


def test_product_ui_and_wrapper_targets_match_product_active_models() -> None:
    index_html = Path("src/powers_tool_webui/static/index.html").read_text(encoding="utf-8")
    assert '<option value="">Auto-detect</option>' in index_html
    assert 'option value="keysight-' not in index_html
    wrapper = Path("scripts/_validation_helpers.ps1").read_text(encoding="utf-8")
    wrapper_targets = frozenset(
        re.findall(r'^    "(keysight-[^"]+)" = \[pscustomobject\]@\{', wrapper, re.MULTILINE)
    )
    assert wrapper_targets == PRODUCT_ACTIVE_MODEL_IDS
