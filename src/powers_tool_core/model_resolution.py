"""Strict runtime identity validation and no-hardware model resolution."""

from __future__ import annotations

from dataclasses import replace

from powers_tool_core.core import CoreValidationError, RuntimeOptions
from powers_tool_core.identity import (
    GENERIC_SCPI_PLANNING_PROFILE_ID,
    IdentityResolutionError,
    canonical_physical_model_id,
    canonical_planning_profile_id,
    planning_model_id_from_sim_resource,
)
from powers_tool_core.models import CANDIDATE_MODEL_IDS, PRODUCT_ACTIVE_MODEL_IDS


RUNTIME_PHYSICAL_MODEL_IDS = PRODUCT_ACTIVE_MODEL_IDS | CANDIDATE_MODEL_IDS

MODEL_CHANNELS_BY_ID = {
    "keysight-e36312a": (1, 2, 3),
    "keysight-edu36311a": (1, 2, 3),
    "keysight-e3646a": (1, 2),
    "gw-instek-psm-2010": (1,),
}
PLANNING_PROFILE_CHANNELS = {
    GENERIC_SCPI_PLANNING_PROFILE_ID: (1,),
}

SIMULATED_RESOURCE_FOR_MODEL_ID = {
    "keysight-e36312a": "USB0::SIM::E36312A::INSTR",
    "keysight-edu36311a": "USB0::SIM::EDU36311A::INSTR",
    "keysight-e3646a": "ASRL1::SIM::E3646A::INSTR",
    "gw-instek-psm-2010": "ASRL1::SIM::PSM2010::INSTR",
}


def runtime_execution_mode(runtime: RuntimeOptions) -> str:
    """Return the established resolved execution mode."""

    if runtime.simulate:
        return "simulate"
    if runtime.dry_run:
        return "dry_run"
    return "live"


def validate_runtime_identity(runtime: RuntimeOptions) -> None:
    """Validate explicit runtime identity fields before any hardware I/O."""

    planning_model_id = _canonical_runtime_model_id(
        runtime.planning_model_id,
        field="planning_model_id",
    )
    expected_model_id = _canonical_runtime_model_id(
        runtime.expected_model_id,
        field="expected_model_id",
    )
    planning_profile_id = _canonical_runtime_profile_id(runtime.planning_profile_id)
    mode = runtime_execution_mode(runtime)

    if mode == "dry_run":
        if expected_model_id is not None:
            raise CoreValidationError("expected_model_id is invalid in dry-run mode")
        if planning_model_id is not None and planning_profile_id is not None:
            raise CoreValidationError(
                "planning_model_id and planning_profile_id are mutually exclusive"
            )
        inferred = _planning_model_id_from_resource(runtime.resource)
        if planning_profile_id is not None and inferred is not None:
            raise CoreValidationError(
                "planning_profile_id conflicts with deterministic SIM physical identity"
            )
        _reconcile_planning_model_id(planning_model_id, inferred)
        return

    if mode == "simulate":
        if expected_model_id is not None:
            raise CoreValidationError("expected_model_id is invalid in simulator mode")
        if planning_profile_id is not None:
            raise CoreValidationError("planning_profile_id is invalid in simulator mode")
        _reconcile_planning_model_id(
            planning_model_id,
            _planning_model_id_from_resource(runtime.resource),
        )
        return

    if planning_model_id is not None:
        raise CoreValidationError("planning_model_id is invalid in live mode")
    if planning_profile_id is not None:
        raise CoreValidationError("planning_profile_id is invalid in live mode")


def validate_live_expected_model(
    expected_model_id: str | None,
    detected_model_id: str | None,
    *,
    command: str | None = None,
) -> str | None:
    """Compare a live safety guard with the resolved detected model identity."""

    expected = _canonical_runtime_model_id(
        expected_model_id,
        field="expected_model_id",
    )
    if expected is None:
        return None
    detected = _canonical_detected_model_id(detected_model_id)
    if detected != expected:
        prefix = f"{command}: " if command else ""
        reported = detected or "unknown"
        raise CoreValidationError(
            f"{prefix}Expected model_id {expected} but connected instrument resolved to {reported}. "
            "expected_model_id is a safety guard and does not override the IDN-selected driver."
        )
    return expected


def resolve_no_hardware_runtime(runtime: RuntimeOptions) -> RuntimeOptions:
    """Resolve one physical model or nonphysical dry-run planning profile."""

    validate_runtime_identity(runtime)
    mode = runtime_execution_mode(runtime)
    if mode == "live":
        return runtime

    inferred = _planning_model_id_from_resource(runtime.resource)
    planning_model_id = _reconcile_planning_model_id(runtime.planning_model_id, inferred)
    planning_profile_id = _canonical_runtime_profile_id(runtime.planning_profile_id)

    if planning_model_id is None and planning_profile_id is None:
        raise CoreValidationError(
            "dry-run and simulator planning require planning_model_id, planning_profile_id, "
            "or a known deterministic SIM resource"
        )
    if mode == "simulate" and planning_model_id is None:
        raise CoreValidationError("simulator mode requires a canonical physical planning_model_id")

    resource = runtime.resource
    if mode == "simulate":
        assert planning_model_id is not None
        resource = _simulate_resource_for_model_id(planning_model_id, resource)

    return replace(
        runtime,
        resource=resource,
        planning_model_id=planning_model_id,
        planning_profile_id=planning_profile_id,
    )


def no_hardware_channels(
    planning_model_id: str | None,
    planning_profile_id: str | None = None,
) -> tuple[int, ...]:
    """Return channels for one already-resolved planning identity."""

    if planning_model_id is not None and planning_profile_id is not None:
        raise CoreValidationError(
            "planning_model_id and planning_profile_id are mutually exclusive"
        )
    if planning_profile_id is not None:
        profile_id = _canonical_runtime_profile_id(planning_profile_id)
        assert profile_id is not None
        return PLANNING_PROFILE_CHANNELS[profile_id]
    model_id = _canonical_runtime_model_id(planning_model_id, field="planning_model_id")
    if model_id is None:
        raise CoreValidationError("a planning identity is required")
    try:
        return MODEL_CHANNELS_BY_ID[model_id]
    except KeyError as exc:
        raise CoreValidationError(f"unsupported planning_model_id {model_id!r}") from exc


def _canonical_runtime_model_id(value: str | None, *, field: str) -> str | None:
    try:
        model_id = canonical_physical_model_id(value)
    except IdentityResolutionError as exc:
        raise CoreValidationError(f"invalid {field}: {exc}") from exc
    if model_id is not None and model_id not in RUNTIME_PHYSICAL_MODEL_IDS:
        raise CoreValidationError(
            f"invalid {field}: physical model_id {model_id!r} is not active or candidate"
        )
    return model_id


def _canonical_runtime_profile_id(value: str | None) -> str | None:
    try:
        return canonical_planning_profile_id(value)
    except IdentityResolutionError as exc:
        raise CoreValidationError(f"invalid planning_profile_id: {exc}") from exc


def _planning_model_id_from_resource(resource: str | None) -> str | None:
    try:
        inferred = planning_model_id_from_sim_resource(resource)
    except IdentityResolutionError as exc:
        raise CoreValidationError(f"invalid deterministic SIM identity: {exc}") from exc
    if inferred is not None and inferred not in RUNTIME_PHYSICAL_MODEL_IDS:
        raise CoreValidationError(
            f"deterministic SIM model_id {inferred!r} is not active or candidate"
        )
    return inferred


def _reconcile_planning_model_id(
    explicit_model_id: str | None,
    inferred_model_id: str | None,
) -> str | None:
    explicit = _canonical_runtime_model_id(
        explicit_model_id,
        field="planning_model_id",
    )
    if explicit is not None and inferred_model_id is not None and explicit != inferred_model_id:
        raise CoreValidationError(
            f"planning_model_id {explicit!r} does not match deterministic SIM "
            f"model_id {inferred_model_id!r}"
        )
    return explicit or inferred_model_id


def _simulate_resource_for_model_id(model_id: str, resource: str | None) -> str:
    if resource is not None:
        if _planning_model_id_from_resource(resource) is None:
            raise CoreValidationError(
                "simulator mode requires a deterministic SIM resource; omit resource to derive "
                "one from planning_model_id or pass a known SIM resource"
            )
        return resource
    try:
        return SIMULATED_RESOURCE_FOR_MODEL_ID[model_id]
    except KeyError as exc:
        raise CoreValidationError(
            f"planning_model_id {model_id!r} has no deterministic simulator resource"
        ) from exc


def _canonical_detected_model_id(model_id: str | None) -> str | None:
    try:
        return canonical_physical_model_id(model_id)
    except IdentityResolutionError as exc:
        raise CoreValidationError(f"invalid detected model_id: {exc}") from exc
