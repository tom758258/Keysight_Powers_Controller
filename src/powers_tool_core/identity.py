"""Pure vendor-qualified physical-model identity primitives."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence


_VENDOR_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MODEL_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
_PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ASCII_PATTERN = re.compile(r"^[\x20-\x7e]+$")

GENERIC_SCPI_PLANNING_PROFILE_ID = "generic-scpi"


class IdentityError(ValueError):
    """Base error for identity validation and resolution failures."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class IdentityMetadataError(IdentityError):
    """Identity metadata is malformed, conflicting, or ambiguous."""

    def __init__(self, message: str) -> None:
        super().__init__("invalid_identity_metadata", message)


class IdentityResolutionError(IdentityError):
    """Reported or requested identity cannot be resolved safely."""


@dataclass(frozen=True)
class VendorInfo:
    """Canonical vendor identity and explicit reported-name aliases."""

    vendor_id: str
    display_name: str
    canonical_manufacturer: str
    manufacturer_aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class PhysicalModelInfo:
    """Canonical physical-model identity with independently stored fields."""

    model_id: str
    vendor_id: str
    canonical_model: str
    display_name: str
    model_aliases: tuple[str, ...] = ()
    manufacturer_aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedPhysicalModelIdentity:
    """Reported identity fields and their canonical physical identity."""

    reported_manufacturer: str
    reported_model: str
    vendor_id: str
    model_id: str
    canonical_model: str


@dataclass(frozen=True)
class _ManufacturerTarget:
    vendor_id: str
    model_ids: frozenset[str] | None


@dataclass(frozen=True)
class IdentityIndexes:
    """Validated immutable indexes for pure identity resolution."""

    vendors_by_id: Mapping[str, VendorInfo]
    models_by_id: Mapping[str, PhysicalModelInfo]
    canonical_manufacturers: Mapping[str, _ManufacturerTarget]
    manufacturer_aliases: Mapping[str, _ManufacturerTarget]
    canonical_models: Mapping[tuple[str, str], PhysicalModelInfo]
    model_aliases: Mapping[tuple[str, str], PhysicalModelInfo]
    model_name_vendors: Mapping[str, frozenset[str]]


def normalize_manufacturer(value: str) -> str:
    """Normalize a manufacturer name using only the frozen lookup rules."""

    normalized = _normalize_spacing(value, field="manufacturer")
    return normalized.casefold()


def normalize_model_name(value: str) -> str:
    """Normalize an ASCII model name using only the frozen lookup rules."""

    normalized = _normalize_spacing(value, field="model")
    if normalized and _ASCII_PATTERN.fullmatch(normalized) is None:
        raise IdentityResolutionError(
            "invalid_model",
            "model identity must contain printable ASCII characters only",
        )
    return normalized.lower()


def validate_vendor_id(value: str) -> str:
    """Return a canonical vendor ID or reject it without rewriting."""

    if not isinstance(value, str) or _VENDOR_ID_PATTERN.fullmatch(value) is None:
        raise IdentityResolutionError("invalid_vendor_id", f"invalid canonical vendor_id {value!r}")
    return value


def validate_model_id(value: str) -> str:
    """Return a canonical vendor-qualified model ID or reject it."""

    if not isinstance(value, str) or _MODEL_ID_PATTERN.fullmatch(value) is None:
        raise IdentityResolutionError("invalid_model_id", f"invalid canonical model_id {value!r}")
    return value


def validate_profile_id(value: str) -> str:
    """Return a canonical planning profile ID or reject it."""

    if not isinstance(value, str) or _PROFILE_ID_PATTERN.fullmatch(value) is None:
        raise IdentityResolutionError("invalid_profile_id", f"invalid canonical profile_id {value!r}")
    return value


def build_identity_indexes(
    vendors: Sequence[VendorInfo],
    models: Sequence[PhysicalModelInfo],
) -> IdentityIndexes:
    """Validate identity metadata and build immutable lookup indexes."""

    vendors_by_id: dict[str, VendorInfo] = {}
    canonical_manufacturers: dict[str, _ManufacturerTarget] = {}
    manufacturer_aliases: dict[str, _ManufacturerTarget] = {}

    for vendor in vendors:
        try:
            validate_vendor_id(vendor.vendor_id)
            display_name = _required_text(vendor.display_name, "vendor display_name")
            canonical = normalize_manufacturer(vendor.canonical_manufacturer)
        except IdentityError as exc:
            raise IdentityMetadataError(str(exc)) from exc
        if not display_name:
            raise IdentityMetadataError(f"vendor {vendor.vendor_id!r} has an empty display_name")
        if not canonical:
            raise IdentityMetadataError(f"vendor {vendor.vendor_id!r} has an empty canonical manufacturer")
        if vendor.vendor_id in vendors_by_id:
            raise IdentityMetadataError(f"duplicate vendor_id {vendor.vendor_id!r}")
        vendors_by_id[vendor.vendor_id] = vendor

        normalized_aliases = _normalized_unique(
            vendor.manufacturer_aliases,
            normalize_manufacturer,
            f"vendor {vendor.vendor_id!r} manufacturer aliases",
        )
        if canonical in normalized_aliases:
            raise IdentityMetadataError(
                f"vendor {vendor.vendor_id!r} repeats its canonical manufacturer as an alias"
            )
        target = _ManufacturerTarget(vendor.vendor_id, None)
        _insert_manufacturer_target(
            canonical_manufacturers,
            manufacturer_aliases,
            canonical,
            target,
            canonical=True,
        )
        for alias in normalized_aliases:
            _insert_manufacturer_target(
                canonical_manufacturers,
                manufacturer_aliases,
                alias,
                target,
                canonical=False,
            )

    models_by_id: dict[str, PhysicalModelInfo] = {}
    canonical_models: dict[tuple[str, str], PhysicalModelInfo] = {}
    model_aliases: dict[tuple[str, str], PhysicalModelInfo] = {}
    model_name_vendors: dict[str, set[str]] = {}
    pending_model_manufacturer_aliases: list[tuple[str, PhysicalModelInfo]] = []

    for model in models:
        try:
            validate_model_id(model.model_id)
            validate_vendor_id(model.vendor_id)
            canonical_model = normalize_model_name(model.canonical_model)
            display_name = _required_text(model.display_name, "physical model display_name")
        except IdentityError as exc:
            raise IdentityMetadataError(str(exc)) from exc
        if model.model_id == GENERIC_SCPI_PLANNING_PROFILE_ID:
            raise IdentityMetadataError("generic-scpi cannot appear in the physical model registry")
        if model.vendor_id not in vendors_by_id:
            raise IdentityMetadataError(
                f"physical model {model.model_id!r} references unknown vendor {model.vendor_id!r}"
            )
        _validate_model_id_vendor_consistency(
            model.model_id,
            model.vendor_id,
            vendors_by_id,
        )
        if not canonical_model:
            raise IdentityMetadataError(f"physical model {model.model_id!r} has an empty canonical model")
        if not display_name:
            raise IdentityMetadataError(f"physical model {model.model_id!r} has an empty display_name")
        if model.model_id in models_by_id:
            raise IdentityMetadataError(f"duplicate model_id {model.model_id!r}")
        models_by_id[model.model_id] = model

        normalized_aliases = _normalized_unique(
            model.model_aliases,
            normalize_model_name,
            f"model {model.model_id!r} aliases",
        )
        if canonical_model in normalized_aliases:
            raise IdentityMetadataError(
                f"model {model.model_id!r} repeats its canonical model name as an alias"
            )
        canonical_key = (model.vendor_id, canonical_model)
        _insert_model_target(canonical_models, model_aliases, canonical_key, model, canonical=True)
        model_name_vendors.setdefault(canonical_model, set()).add(model.vendor_id)
        for alias in normalized_aliases:
            alias_key = (model.vendor_id, alias)
            _insert_model_target(canonical_models, model_aliases, alias_key, model, canonical=False)
            model_name_vendors.setdefault(alias, set()).add(model.vendor_id)

        normalized_manufacturer_aliases = _normalized_unique(
            model.manufacturer_aliases,
            normalize_manufacturer,
            f"model {model.model_id!r} manufacturer aliases",
        )
        for alias in normalized_manufacturer_aliases:
            pending_model_manufacturer_aliases.append((alias, model))

    for alias, model in pending_model_manufacturer_aliases:
        existing = canonical_manufacturers.get(alias) or manufacturer_aliases.get(alias)
        if existing is not None:
            if existing.vendor_id != model.vendor_id:
                raise IdentityMetadataError(
                    f"model-specific manufacturer alias {alias!r} conflicts with vendor {existing.vendor_id!r}"
                )
            if existing.model_ids is None:
                continue
            manufacturer_aliases[alias] = _ManufacturerTarget(
                model.vendor_id,
                existing.model_ids | {model.model_id},
            )
        else:
            manufacturer_aliases[alias] = _ManufacturerTarget(
                model.vendor_id,
                frozenset({model.model_id}),
            )

    return IdentityIndexes(
        vendors_by_id=MappingProxyType(vendors_by_id),
        models_by_id=MappingProxyType(models_by_id),
        canonical_manufacturers=MappingProxyType(canonical_manufacturers),
        manufacturer_aliases=MappingProxyType(manufacturer_aliases),
        canonical_models=MappingProxyType(canonical_models),
        model_aliases=MappingProxyType(model_aliases),
        model_name_vendors=MappingProxyType(
            {name: frozenset(vendor_ids) for name, vendor_ids in model_name_vendors.items()}
        ),
    )


def resolve_physical_model_identity(
    manufacturer: str | None,
    model: str | None,
    *,
    indexes: IdentityIndexes | None = None,
) -> ResolvedPhysicalModelIdentity:
    """Resolve a reported manufacturer-plus-model pair to one physical identity."""

    active_indexes = IDENTITY_INDEXES if indexes is None else indexes
    if manufacturer is None:
        raise IdentityResolutionError("missing_manufacturer", "manufacturer is required")
    if model is None:
        raise IdentityResolutionError("missing_model", "model is required")
    if not isinstance(manufacturer, str):
        raise IdentityResolutionError("invalid_manufacturer", "manufacturer must be text")
    if not isinstance(model, str):
        raise IdentityResolutionError("invalid_model", "model must be text")

    normalized_manufacturer = normalize_manufacturer(manufacturer)
    if not normalized_manufacturer:
        raise IdentityResolutionError("missing_manufacturer", "manufacturer must not be blank")
    normalized_model = normalize_model_name(model)
    if not normalized_model:
        raise IdentityResolutionError("missing_model", "model must not be blank")

    manufacturer_target = active_indexes.canonical_manufacturers.get(normalized_manufacturer)
    if manufacturer_target is None:
        manufacturer_target = active_indexes.manufacturer_aliases.get(normalized_manufacturer)
    if manufacturer_target is None:
        raise IdentityResolutionError(
            "unknown_manufacturer",
            f"unknown instrument manufacturer {manufacturer!r}",
        )

    model_key = (manufacturer_target.vendor_id, normalized_model)
    model_info = active_indexes.canonical_models.get(model_key)
    if model_info is None:
        model_info = active_indexes.model_aliases.get(model_key)
    if model_info is None:
        known_vendors = active_indexes.model_name_vendors.get(normalized_model, frozenset())
        reason = "manufacturer_model_mismatch" if known_vendors else "unknown_model"
        raise IdentityResolutionError(
            reason,
            f"manufacturer {manufacturer!r} and model {model!r} do not resolve to a registered physical identity",
        )
    if (
        manufacturer_target.model_ids is not None
        and model_info.model_id not in manufacturer_target.model_ids
    ):
        raise IdentityResolutionError(
            "manufacturer_model_mismatch",
            f"manufacturer alias {manufacturer!r} is not valid for model {model!r}",
        )

    return ResolvedPhysicalModelIdentity(
        reported_manufacturer=manufacturer,
        reported_model=model,
        vendor_id=model_info.vendor_id,
        model_id=model_info.model_id,
        canonical_model=model_info.canonical_model,
    )


def canonical_physical_model_id(value: str | None) -> str | None:
    """Accept only a known canonical physical model ID."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise IdentityResolutionError("invalid_model_id", "model_id must be text")
    canonical = value.strip()
    validate_model_id(canonical)
    if canonical == GENERIC_SCPI_PLANNING_PROFILE_ID:
        raise IdentityResolutionError("invalid_model_id", "generic-scpi is not a physical model_id")
    if canonical not in IDENTITY_INDEXES.models_by_id:
        raise IdentityResolutionError("unknown_model_id", f"unknown physical model_id {canonical!r}")
    return canonical


def canonical_planning_profile_id(value: str | None) -> str | None:
    """Accept only a known nonphysical planning profile ID."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise IdentityResolutionError("invalid_profile_id", "planning profile_id must be text")
    canonical = value.strip()
    validate_profile_id(canonical)
    if canonical != GENERIC_SCPI_PLANNING_PROFILE_ID:
        raise IdentityResolutionError("unknown_profile_id", f"unknown planning profile_id {canonical!r}")
    return canonical


def planning_model_id_from_sim_resource(resource: str | None) -> str | None:
    """Infer a physical planning model from an exact deterministic SIM IDN."""

    if not isinstance(resource, str):
        return None
    from powers_tool_core.models import parse_idn
    from powers_tool_core.testing.simulator import SIMULATED_IDN

    raw_idn = SIMULATED_IDN.get(resource)
    if raw_idn is None:
        return None
    parsed = parse_idn(raw_idn)
    if not parsed.parse_ok:
        raise IdentityResolutionError("invalid_sim_identity", "deterministic SIM IDN is malformed")
    resolved = resolve_physical_model_identity(parsed.manufacturer, parsed.model)
    return resolved.model_id


def resolve_planning_model_id(
    explicit_model_id: str | None,
    resource: str | None,
) -> str | None:
    """Reconcile an explicit physical model ID with deterministic SIM identity."""

    explicit = canonical_physical_model_id(explicit_model_id)
    inferred = planning_model_id_from_sim_resource(resource)
    if explicit is not None and inferred is not None and explicit != inferred:
        raise IdentityResolutionError(
            "model_id_mismatch",
            f"explicit model_id {explicit!r} does not match deterministic SIM model_id {inferred!r}",
        )
    return explicit or inferred


def validate_builtin_identity_inventory() -> None:
    """Prove the parallel V2 inventory covers the current legacy inventory."""

    from powers_tool_core.models import DE_SCOPED_MODEL_IDS, REGISTERED_MODELS

    core_model_ids = set(REGISTERED_MODELS) | set(DE_SCOPED_MODEL_IDS)
    identity_model_ids = {info.model_id for info in PHYSICAL_MODELS}
    if identity_model_ids != core_model_ids:
        raise IdentityMetadataError(
            "physical identity inventory does not match REGISTERED_MODELS plus DE_SCOPED_MODEL_IDS"
        )
    validate_identity_inventory_mapping(
        PHYSICAL_MODELS,
        EXPECTED_MODEL_ID_BY_CANONICAL_MODEL,
    )


def validate_identity_inventory_mapping(
    models: Sequence[PhysicalModelInfo],
    expected_model_id_by_canonical_model: Mapping[str, str],
) -> None:
    """Validate an exact canonical-model-to-model-ID inventory mapping."""

    observed: dict[str, str] = {}
    for model in models:
        if model.canonical_model in observed:
            raise IdentityMetadataError(
                f"duplicate canonical model {model.canonical_model!r} in identity inventory"
            )
        observed[model.canonical_model] = model.model_id
    expected = dict(expected_model_id_by_canonical_model)
    if observed != expected:
        raise IdentityMetadataError(
            "physical identity inventory does not match the expected canonical-model-to-model-ID mapping"
        )


def _normalize_spacing(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise IdentityResolutionError(f"invalid_{field}", f"{field} must be text")
    normalized = unicodedata.normalize("NFKC", value)
    if any(
        unicodedata.category(character).startswith("C") and not character.isspace()
        for character in normalized
    ):
        raise IdentityResolutionError(
            f"invalid_{field}",
            f"{field} contains control or formatting characters",
        )
    return " ".join(normalized.strip().split())


def _required_text(value: str, field: str) -> str:
    try:
        return _normalize_spacing(value, field=field)
    except IdentityError as exc:
        raise IdentityMetadataError(str(exc)) from exc


def _validate_model_id_vendor_consistency(
    model_id: str,
    vendor_id: str,
    registered_vendors: Mapping[str, VendorInfo],
) -> None:
    expected_prefix = f"{vendor_id}-"
    if not model_id.startswith(expected_prefix):
        raise IdentityMetadataError(
            f"physical model {model_id!r} is inconsistent with vendor_id {vendor_id!r}; "
            f"expected prefix {expected_prefix!r}"
        )

    matching_vendors = tuple(
        candidate
        for candidate in registered_vendors
        if model_id.startswith(f"{candidate}-")
    )
    owner = max(matching_vendors, key=len)
    if owner != vendor_id:
        raise IdentityMetadataError(
            f"physical model {model_id!r} is owned by registered vendor prefix {owner!r}, "
            f"not vendor_id {vendor_id!r}"
        )


def _normalized_unique(values: Sequence[str], normalize, label: str) -> tuple[str, ...]:
    normalized_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        try:
            normalized = normalize(value)
        except IdentityError as exc:
            raise IdentityMetadataError(f"{label} contains an invalid value: {exc}") from exc
        if not normalized:
            raise IdentityMetadataError(f"{label} contains an empty value")
        if normalized in seen:
            raise IdentityMetadataError(f"{label} contains duplicate normalized alias {normalized!r}")
        seen.add(normalized)
        normalized_values.append(normalized)
    return tuple(normalized_values)


def _insert_manufacturer_target(
    canonical_index: dict[str, _ManufacturerTarget],
    alias_index: dict[str, _ManufacturerTarget],
    name: str,
    target: _ManufacturerTarget,
    *,
    canonical: bool,
) -> None:
    existing = canonical_index.get(name) or alias_index.get(name)
    if existing is not None:
        raise IdentityMetadataError(
            f"manufacturer name {name!r} conflicts between vendors "
            f"{existing.vendor_id!r} and {target.vendor_id!r}"
        )
    (canonical_index if canonical else alias_index)[name] = target


def _insert_model_target(
    canonical_index: dict[tuple[str, str], PhysicalModelInfo],
    alias_index: dict[tuple[str, str], PhysicalModelInfo],
    key: tuple[str, str],
    target: PhysicalModelInfo,
    *,
    canonical: bool,
) -> None:
    existing = canonical_index.get(key) or alias_index.get(key)
    if existing is not None:
        raise IdentityMetadataError(
            f"model name {key[1]!r} for vendor {key[0]!r} conflicts between "
            f"{existing.model_id!r} and {target.model_id!r}"
        )
    (canonical_index if canonical else alias_index)[key] = target


VENDORS = (
    VendorInfo(
        vendor_id="keysight",
        display_name="Keysight Technologies",
        canonical_manufacturer="KEYSIGHT",
        manufacturer_aliases=("KEYSIGHT TECHNOLOGIES",),
    ),
    VendorInfo(
        vendor_id="gw-instek",
        display_name="GW Instek",
        canonical_manufacturer="GW.Inc",
    ),
)

EXPECTED_MODEL_ID_BY_CANONICAL_MODEL = MappingProxyType(
    {
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
)

PHYSICAL_MODELS = (
    PhysicalModelInfo("keysight-e36312a", "keysight", "E36312A", "Keysight E36312A"),
    PhysicalModelInfo("keysight-edu36311a", "keysight", "EDU36311A", "Keysight EDU36311A"),
    PhysicalModelInfo(
        "keysight-e3646a",
        "keysight",
        "E3646A",
        "Keysight E3646A",
        manufacturer_aliases=("Agilent Technologies",),
    ),
    PhysicalModelInfo("keysight-e36313a", "keysight", "E36313A", "Keysight E36313A"),
    PhysicalModelInfo("keysight-e36233a", "keysight", "E36233A", "Keysight E36233A"),
    PhysicalModelInfo("keysight-e36441a", "keysight", "E36441A", "Keysight E36441A"),
    PhysicalModelInfo("keysight-e36155a", "keysight", "E36155A", "Keysight E36155A"),
    PhysicalModelInfo("keysight-e36103b", "keysight", "E36103B", "Keysight E36103B"),
    PhysicalModelInfo("keysight-e36232a", "keysight", "E36232A", "Keysight E36232A"),
    PhysicalModelInfo("gw-instek-psm-2010", "gw-instek", "PSM-2010", "GW Instek PSM-2010"),
)

IDENTITY_INDEXES = build_identity_indexes(VENDORS, PHYSICAL_MODELS)
