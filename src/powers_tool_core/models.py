"""IDN parsing and model metadata."""

from __future__ import annotations

from dataclasses import dataclass

from powers_tool_core.identity import IDENTITY_INDEXES, PhysicalModelInfo

MODEL_ENABLEMENT_PRODUCT_ACTIVE = "product_active"
MODEL_ENABLEMENT_CANDIDATE = "candidate"
MODEL_ENABLEMENT_CATALOG_ONLY = "catalog_only"
MODEL_ENABLEMENT_DE_SCOPED = "de_scoped"


@dataclass(frozen=True)
class IdnInfo:
    """Parsed information from a SCPI `*IDN?` response."""

    raw: str
    manufacturer: str | None
    model: str | None
    serial: str | None
    firmware: str | None
    parse_ok: bool

    def to_dict(self) -> dict[str, object]:
        """Return the stable CLI JSON representation for parsed IDN data."""

        return {
            "raw": self.raw,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "serial": self.serial,
            "firmware": self.firmware,
            "parse_ok": self.parse_ok,
        }


@dataclass(frozen=True)
class ModelInfo:
    """Known model metadata without unverified electrical ratings."""

    identity: PhysicalModelInfo
    target_group: str
    enablement_stage: str
    first_hardware_target: bool = False

    @property
    def model_id(self) -> str:
        return self.identity.model_id

    @property
    def vendor_id(self) -> str:
        return self.identity.vendor_id

    @property
    def manufacturer(self) -> str:
        return IDENTITY_INDEXES.vendors_by_id[self.vendor_id].canonical_manufacturer

    @property
    def model(self) -> str:
        return self.identity.canonical_model

    @property
    def display_name(self) -> str:
        return self.identity.display_name


REGISTERED_MODELS: dict[str, ModelInfo] = {
    "keysight-e36312a": ModelInfo(
        identity=IDENTITY_INDEXES.models_by_id["keysight-e36312a"],
        target_group="initial",
        enablement_stage=MODEL_ENABLEMENT_PRODUCT_ACTIVE,
        first_hardware_target=True,
    ),
    "keysight-edu36311a": ModelInfo(
        identity=IDENTITY_INDEXES.models_by_id["keysight-edu36311a"],
        target_group="initial",
        enablement_stage=MODEL_ENABLEMENT_PRODUCT_ACTIVE,
        first_hardware_target=True,
    ),
    "keysight-e36313a": ModelInfo(
        identity=IDENTITY_INDEXES.models_by_id["keysight-e36313a"],
        target_group="near-term",
        enablement_stage=MODEL_ENABLEMENT_CATALOG_ONLY,
    ),
    "keysight-e3646a": ModelInfo(
        identity=IDENTITY_INDEXES.models_by_id["keysight-e3646a"],
        target_group="read-only-serial",
        enablement_stage=MODEL_ENABLEMENT_PRODUCT_ACTIVE,
    ),
    "keysight-e36233a": ModelInfo(
        identity=IDENTITY_INDEXES.models_by_id["keysight-e36233a"],
        target_group="near-term",
        enablement_stage=MODEL_ENABLEMENT_CATALOG_ONLY,
    ),
    "keysight-e36441a": ModelInfo(
        identity=IDENTITY_INDEXES.models_by_id["keysight-e36441a"],
        target_group="near-term",
        enablement_stage=MODEL_ENABLEMENT_CATALOG_ONLY,
    ),
    "keysight-e36155a": ModelInfo(
        identity=IDENTITY_INDEXES.models_by_id["keysight-e36155a"],
        target_group="later",
        enablement_stage=MODEL_ENABLEMENT_CATALOG_ONLY,
    ),
    "gw-instek-psm-2010": ModelInfo(
        identity=IDENTITY_INDEXES.models_by_id["gw-instek-psm-2010"],
        target_group="psm-series",
        enablement_stage=MODEL_ENABLEMENT_PRODUCT_ACTIVE,
    ),
}

DE_SCOPED_MODEL_IDS = frozenset({"keysight-e36103b", "keysight-e36232a"})
PRODUCT_ACTIVE_MODEL_IDS = frozenset(
    model_id
    for model_id, info in REGISTERED_MODELS.items()
    if info.enablement_stage == MODEL_ENABLEMENT_PRODUCT_ACTIVE
)
CANDIDATE_MODEL_IDS = frozenset(
    model_id
    for model_id, info in REGISTERED_MODELS.items()
    if info.enablement_stage == MODEL_ENABLEMENT_CANDIDATE
)
CATALOG_ONLY_MODEL_IDS = frozenset(
    model_id
    for model_id, info in REGISTERED_MODELS.items()
    if info.enablement_stage == MODEL_ENABLEMENT_CATALOG_ONLY
)


def de_scoped_model_message(model_id: str) -> str:
    """Return the current support-boundary message for a de-scoped model."""

    identity = IDENTITY_INDEXES.models_by_id.get(model_id)
    model = identity.canonical_model if identity is not None else model_id
    return (
        f"{model} is de-scoped and not active supported. It was previously "
        "considered as an unvalidated planning model, but is now blocked from "
        "generic fallback. Future reintroduction requires a new "
        "model-enablement plan, programming-guide review, simulator/fake "
        "coverage, explicit feature matrix, and real hardware validation."
    )


def parse_idn(raw: str) -> IdnInfo:
    """Parse a SCPI `*IDN?` response into the stable project model."""

    parts = [part.strip() for part in raw.split(",", maxsplit=3)]
    values = [part or None for part in parts]

    def get(index: int) -> str | None:
        if index >= len(values):
            return None
        return values[index]

    return IdnInfo(
        raw=raw,
        manufacturer=get(0),
        model=get(1),
        serial=get(2),
        firmware=get(3),
        parse_ok=all(get(index) is not None for index in range(4)),
    )


def resource_interface(name: str) -> str:
    """Return the high-level VISA interface family for a resource name."""

    normalized = name.strip().upper()
    for interface in ("USB", "TCPIP", "GPIB", "ASRL"):
        if normalized.startswith(interface):
            return interface
    return "UNKNOWN"


def lookup_model(model_id: str | None) -> ModelInfo | None:
    """Return metadata for a registered canonical physical model ID."""

    if model_id is None:
        return None
    return REGISTERED_MODELS.get(model_id)
