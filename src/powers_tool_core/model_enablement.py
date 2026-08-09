"""Pure consistency checks for the physical-model enablement lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from powers_tool_core.models import (
    CANDIDATE_MODEL_IDS,
    DE_SCOPED_MODEL_IDS,
    MODEL_ENABLEMENT_CANDIDATE,
    MODEL_ENABLEMENT_CATALOG_ONLY,
    MODEL_ENABLEMENT_DE_SCOPED,
    MODEL_ENABLEMENT_PRODUCT_ACTIVE,
    PRODUCT_ACTIVE_MODEL_IDS,
    REGISTERED_MODELS,
)
from powers_tool_core.support_features import FEATURE_AWARE_LIVE_COMMANDS
from powers_tool_core.support_policy import (
    EXEMPT_LIVE_DIAGNOSTIC_COMMANDS,
    PURE_OFFLINE_COMMANDS,
    VALIDATION_STATUS_FEATURE_PENDING,
    VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
    VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL,
    VALIDATION_STATUS_TRANSPORT_PENDING,
    ModelSupportPolicy,
    expected_live_feature_inventory,
    validate_live_feature_scope_metadata,
)

MODEL_ENABLEMENT_STAGES = frozenset(
    {
        MODEL_ENABLEMENT_PRODUCT_ACTIVE,
        MODEL_ENABLEMENT_CANDIDATE,
        MODEL_ENABLEMENT_CATALOG_ONLY,
        MODEL_ENABLEMENT_DE_SCOPED,
    }
)

# E3646A predates flattened rating metadata and uses enforced range-dependent
# limits. This compatibility is only for the existing Product-active model.
PRODUCT_RATING_COMPATIBILITY_MODEL_IDS = frozenset({"keysight-e3646a"})


def _resolved_simulator_model_id(idn: str) -> str | None:
    from powers_tool_core.identity import (
        IDENTITY_INDEXES,
        IdentityResolutionError,
        resolve_physical_model_identity,
    )
    from powers_tool_core.models import parse_idn

    parsed = parse_idn(idn)
    if not parsed.parse_ok:
        return None
    try:
        resolved = resolve_physical_model_identity(parsed.manufacturer, parsed.model)
    except IdentityResolutionError:
        return None
    expected_vendor = IDENTITY_INDEXES.models_by_id[resolved.model_id].vendor_id
    return resolved.model_id if resolved.vendor_id == expected_vendor else None


@dataclass(frozen=True)
class ModelEnablementInventory:
    """Injected registries required to validate model-enablement consistency."""

    model_stages: Mapping[str, str]
    product_model_ids: frozenset[str]
    candidate_model_ids: frozenset[str]
    planning_profiles: frozenset[str]
    channels: Mapping[str, tuple[int, ...]]
    simulator_resources: Mapping[str, str]
    simulator_idns: Mapping[str, str]
    drivers: Mapping[str, object]
    command_capabilities: Mapping[str, Mapping[str, Mapping[str, object]]]
    live_policies: Mapping[str, ModelSupportPolicy]
    feature_inventories: Mapping[
        str, Mapping[str, frozenset[tuple[str, str]]]
    ]
    electrical_rating_models: frozenset[str]
    setpoint_range_models: frozenset[str]
    product_rating_compatibility_models: frozenset[str]
    safety_validated_models: frozenset[str]
    no_hardware_covered_models: frozenset[str]


def current_model_enablement_inventory() -> ModelEnablementInventory:
    """Build the current inventory without coupling Core to adapters or scripts."""

    from powers_tool_core.capabilities import command_support
    from powers_tool_core.electrical_ratings import ELECTRICAL_RATINGS_BY_MODEL_ID
    from powers_tool_core.factory import MODEL_DRIVERS
    from powers_tool_core.model_resolution import (
        MODEL_CHANNELS_BY_ID,
        PLANNING_PROFILE_CHANNELS,
        SIMULATED_RESOURCE_FOR_MODEL_ID,
    )
    from powers_tool_core.setpoint_ranges import SETPOINT_RANGES_BY_MODEL_ID
    from powers_tool_core.support_policy import LIVE_SUPPORT_POLICY_REGISTRY
    from powers_tool_core.testing.simulator import SIMULATED_IDN

    active_or_candidate = PRODUCT_ACTIVE_MODEL_IDS | CANDIDATE_MODEL_IDS
    stages = {
        model: info.enablement_stage for model, info in REGISTERED_MODELS.items()
    }
    stages.update({model_id: MODEL_ENABLEMENT_DE_SCOPED for model_id in DE_SCOPED_MODEL_IDS})
    simulator_idns = {
        model: SIMULATED_IDN[resource]
        for model, resource in SIMULATED_RESOURCE_FOR_MODEL_ID.items()
        if resource in SIMULATED_IDN
    }
    command_capabilities = {
        model_id: command_support(model_id) for model_id in active_or_candidate
    }
    feature_inventories = {
        model_id: {
            command: expected_live_feature_inventory(
                model_id, command
            )
            for command, capability in capabilities.items()
            if capability.get("real") is True
            and command in FEATURE_AWARE_LIVE_COMMANDS
        }
        for model_id, capabilities in command_capabilities.items()
    }
    return ModelEnablementInventory(
        model_stages=stages,
        product_model_ids=PRODUCT_ACTIVE_MODEL_IDS,
        candidate_model_ids=CANDIDATE_MODEL_IDS,
        planning_profiles=frozenset(PLANNING_PROFILE_CHANNELS),
        channels=MODEL_CHANNELS_BY_ID,
        simulator_resources=SIMULATED_RESOURCE_FOR_MODEL_ID,
        simulator_idns=simulator_idns,
        drivers={
            model_id: driver
            for model_id, driver in MODEL_DRIVERS.items()
            if model_id in active_or_candidate
        },
        command_capabilities=command_capabilities,
        live_policies={policy.model_id: policy for policy in LIVE_SUPPORT_POLICY_REGISTRY},
        feature_inventories=feature_inventories,
        electrical_rating_models=frozenset(ELECTRICAL_RATINGS_BY_MODEL_ID),
        setpoint_range_models=frozenset(SETPOINT_RANGES_BY_MODEL_ID),
        product_rating_compatibility_models=PRODUCT_RATING_COMPATIBILITY_MODEL_IDS,
        safety_validated_models=frozenset(PRODUCT_ACTIVE_MODEL_IDS),
        no_hardware_covered_models=frozenset(PRODUCT_ACTIVE_MODEL_IDS),
    )


def validate_model_enablement(
    inventory: ModelEnablementInventory | None = None,
) -> None:
    """Fail when lifecycle stages and runtime prerequisites drift apart."""

    if inventory is None:
        from powers_tool_core.model_metadata import validate_product_active_model_metadata

        validate_product_active_model_metadata()
    selected = inventory or current_model_enablement_inventory()
    stage_sets = {
        stage: frozenset(
            model for model, current_stage in selected.model_stages.items() if current_stage == stage
        )
        for stage in MODEL_ENABLEMENT_STAGES
    }
    unknown_stages = set(selected.model_stages.values()) - MODEL_ENABLEMENT_STAGES
    if unknown_stages:
        raise ValueError(f"unknown model enablement stage: {sorted(unknown_stages)}")
    from powers_tool_core.identity import IdentityResolutionError, canonical_physical_model_id

    noncanonical_models: list[str] = []
    for model_id in selected.model_stages:
        try:
            if canonical_physical_model_id(model_id) != model_id:
                noncanonical_models.append(model_id)
        except IdentityResolutionError:
            noncanonical_models.append(model_id)
    if noncanonical_models:
        raise ValueError(f"noncanonical model enablement metadata: {sorted(noncanonical_models)}")
    if {"GENERIC", "generic-scpi"} & set(selected.model_stages):
        raise ValueError("generic planning identity is not a physical model-enablement stage")
    if stage_sets[MODEL_ENABLEMENT_PRODUCT_ACTIVE] != selected.product_model_ids:
        raise ValueError("product model IDs do not match product_active lifecycle models")
    if stage_sets[MODEL_ENABLEMENT_CANDIDATE] != selected.candidate_model_ids:
        raise ValueError("candidate model IDs do not match candidate lifecycle models")
    if selected.planning_profiles != frozenset({"generic-scpi"}):
        raise ValueError("generic planning profile inventory must remain separate")

    physical_registries = {
        "channels": selected.channels,
        "simulator resources": selected.simulator_resources,
        "drivers": selected.drivers,
        "command capabilities": selected.command_capabilities,
        "live policy projection": selected.live_policies,
        "feature inventories": selected.feature_inventories,
    }
    physical_sets = {
        "electrical ratings": selected.electrical_rating_models,
        "setpoint ranges": selected.setpoint_range_models,
        "rating compatibility": selected.product_rating_compatibility_models,
        "safety coverage": selected.safety_validated_models,
        "no-hardware coverage": selected.no_hardware_covered_models,
    }
    for name, registry in physical_registries.items():
        _validate_physical_model_ids(name, registry)
    for name, model_ids in physical_sets.items():
        _validate_physical_model_ids(name, model_ids)

    active_or_candidate = selected.product_model_ids | selected.candidate_model_ids
    forbidden = (
        stage_sets[MODEL_ENABLEMENT_CATALOG_ONLY]
        | stage_sets[MODEL_ENABLEMENT_DE_SCOPED]
    )
    leaked = forbidden & (
        frozenset(selected.drivers)
        | frozenset(selected.simulator_resources)
        | frozenset(selected.live_policies)
    )
    if leaked:
        raise ValueError(f"catalog-only or de-scoped models leaked into active registries: {sorted(leaked)}")

    for model in sorted(active_or_candidate):
        _validate_enabled_model(selected, model, candidate=model in selected.candidate_model_ids)


def _validate_enabled_model(
    inventory: ModelEnablementInventory,
    model: str,
    *,
    candidate: bool,
) -> None:
    if model not in inventory.channels or not inventory.channels[model]:
        raise ValueError(f"{model}: missing channel inventory")
    resource = inventory.simulator_resources.get(model)
    if not resource:
        raise ValueError(f"{model}: missing deterministic simulator resource")
    idn = inventory.simulator_idns.get(model)
    if not idn or _resolved_simulator_model_id(idn) != model:
        raise ValueError(f"{model}: missing deterministic matching simulator IDN")
    driver = inventory.drivers.get(model)
    if driver is None:
        raise ValueError(f"{model}: missing model-specific driver mapping")
    if getattr(driver, "__name__", "") == "GenericScpiPowerSupply":
        raise ValueError(f"{model}: candidate/active model cannot use Generic driver fallback")
    capabilities = inventory.command_capabilities.get(model)
    if not capabilities:
        raise ValueError(f"{model}: missing command capability metadata")
    policy = inventory.live_policies.get(model)
    if policy is None:
        raise ValueError(f"{model}: missing live support-policy metadata")
    if model not in inventory.no_hardware_covered_models:
        raise ValueError(f"{model}: missing simulator/fake/no-hardware coverage")
    if model not in inventory.safety_validated_models:
        raise ValueError(f"{model}: missing safety validation coverage")

    output_capable = any(
        entry.get("real") is True
        for command, entry in capabilities.items()
        if command in {
            "set", "apply", "output-on", "output-off", "safe-off", "cycle-output",
            "ramp", "ramp-list", "smoke-output", "sequence",
        }
    )
    if output_capable:
        has_ratings = model in inventory.electrical_rating_models
        product_compatibility = (
            not candidate
            and model in inventory.product_rating_compatibility_models
        )
        if not has_ratings and not product_compatibility:
            raise ValueError(f"{model}: missing electrical ratings")
        if model not in inventory.setpoint_range_models:
            raise ValueError(f"{model}: missing setpoint range/limit metadata")

    policies = {entry.command: entry for entry in policy.commands}
    for command, capability in capabilities.items():
        if capability.get("real") is not True:
            continue
        if command in EXEMPT_LIVE_DIAGNOSTIC_COMMANDS | PURE_OFFLINE_COMMANDS:
            continue
        command_policy = policies.get(command)
        if command_policy is None:
            raise ValueError(f"{model}/{command}: missing command policy classification")
        if command_policy.validation_status == VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL:
            continue
        if candidate:
            if not command_policy.scopes:
                raise ValueError(f"{model}/{command}: candidate live command lacks exact pending scope")
            if any(
                scope.validation_status != VALIDATION_STATUS_TRANSPORT_PENDING
                for scope in command_policy.scopes
            ):
                raise ValueError(f"{model}/{command}: candidate scope is not exclusively pending")
            if command in FEATURE_AWARE_LIVE_COMMANDS:
                expected_features = inventory.feature_inventories.get(model, {}).get(command)
                if not expected_features:
                    raise ValueError(
                        f"{model}/{command}: candidate live command lacks canonical feature inventory"
                    )
                for scope in command_policy.scopes:
                    validate_live_feature_scope_metadata(
                        model_id=model,
                        command=command,
                        scope=scope,
                        expected_features=expected_features,
                    )
                    if any(
                        feature.validation_status != VALIDATION_STATUS_FEATURE_PENDING
                        for feature in scope.feature_scopes
                    ):
                        raise ValueError(
                            f"{model}/{command}: candidate implemented features must remain feature_pending"
                        )

    product_open = [
        scope
        for command_policy in policy.commands
        for scope in command_policy.scopes
        if scope.validation_status == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE
    ]
    if candidate and product_open:
        raise ValueError(f"{model}: candidate model has an accidental Product-open exact scope")
    if not candidate and not product_open:
        raise ValueError(f"{model}: Product-active model has no Product-open exact scope")
    if not candidate and any(not scope.accepted_evidence_ids for scope in product_open):
        raise ValueError(f"{model}: Product-open scope lacks accepted evidence metadata")


def _validate_physical_model_ids(name: str, values: object) -> None:
    from powers_tool_core.identity import IdentityResolutionError, canonical_physical_model_id

    keys = values.keys() if isinstance(values, Mapping) else values
    for model_id in keys:  # type: ignore[union-attr]
        try:
            canonical_physical_model_id(model_id)
        except (IdentityResolutionError, TypeError) as exc:
            raise ValueError(f"{name} contains noncanonical physical model ID: {model_id!r}") from exc
