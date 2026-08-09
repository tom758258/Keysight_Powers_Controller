"""Driver selection and construction."""

from __future__ import annotations

from dataclasses import dataclass

from powers_tool_core.drivers.base import DriverCapabilities
from powers_tool_core.drivers.e36312a import E36312APowerSupply
from powers_tool_core.drivers.e3646a import E3646APowerSupply
from powers_tool_core.drivers.edu36311a import EDU36311APowerSupply
from powers_tool_core.drivers.generic_scpi import ChannelStrategy, GenericScpiPowerSupply
from powers_tool_core.drivers.psm2010 import PSM2010PowerSupply
from powers_tool_core.core import UnsupportedModelError
from powers_tool_core.identity import (
    IdentityResolutionError,
    ResolvedPhysicalModelIdentity,
    resolve_physical_model_identity,
)
from powers_tool_core.models import (
    DE_SCOPED_MODEL_IDS,
    IdnInfo,
    ModelInfo,
    de_scoped_model_message,
    lookup_model,
    parse_idn,
)
from powers_tool_core.safety import SafetyLimits
from powers_tool_core.transport import SessionLike

MODEL_DRIVERS: dict[str, type[GenericScpiPowerSupply]] = {
    "keysight-e36312a": E36312APowerSupply,
    "keysight-e3646a": E3646APowerSupply,
    "keysight-edu36311a": EDU36311APowerSupply,
    "gw-instek-psm-2010": PSM2010PowerSupply,
}


@dataclass(frozen=True)
class DriverSelection:
    """Result of selecting a driver for a parsed IDN response."""

    idn: IdnInfo
    physical_identity: ResolvedPhysicalModelIdentity | None
    model_info: ModelInfo | None
    driver_class: type[GenericScpiPowerSupply]
    reason: str

    @property
    def capabilities(self) -> DriverCapabilities:
        """Return the selected driver's conservative capability metadata."""

        return self.driver_class.capabilities


def select_driver(idn: str | IdnInfo) -> DriverSelection:
    """Select the safest available driver for an IDN response."""

    parsed_idn = parse_idn(idn) if isinstance(idn, str) else idn
    physical_identity = None
    if parsed_idn.parse_ok:
        try:
            physical_identity = resolve_physical_model_identity(
                parsed_idn.manufacturer,
                parsed_idn.model,
            )
        except IdentityResolutionError:
            physical_identity = None
    model_id = physical_identity.model_id if physical_identity is not None else None
    if model_id in DE_SCOPED_MODEL_IDS:
        raise UnsupportedModelError(de_scoped_model_message(model_id))

    model_info = lookup_model(model_id)

    if not parsed_idn.parse_ok:
        reason = "malformed_idn_generic_fallback"
        driver_class = GenericScpiPowerSupply
    elif model_info is None:
        reason = "unknown_model_generic_fallback"
        driver_class = GenericScpiPowerSupply
    elif model_info.model_id in MODEL_DRIVERS:
        reason = "model_specific_driver"
        driver_class = MODEL_DRIVERS[model_info.model_id]
    else:
        reason = "known_model_generic_fallback"
        driver_class = GenericScpiPowerSupply

    return DriverSelection(
        idn=parsed_idn,
        physical_identity=physical_identity,
        model_info=model_info,
        driver_class=driver_class,
        reason=reason,
    )


def create_power_supply(
    session: SessionLike,
    idn: str | IdnInfo,
    *,
    channel_strategy: ChannelStrategy | None = None,
    safety_limits: SafetyLimits | None = None,
) -> GenericScpiPowerSupply:
    """Create a power-supply driver around an already-opened session."""

    selection = select_driver(idn)
    return selection.driver_class(
        session,
        channel_strategy=channel_strategy,
        safety_limits=safety_limits,
    )
