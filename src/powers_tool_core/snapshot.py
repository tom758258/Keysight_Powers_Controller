"""Adapter-neutral snapshot command."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from powers_tool_core import capabilities
from powers_tool_core.connection import open_resource
from powers_tool_core.core import CoreIoError, CoreValidationError, OperationRequest, UnsupportedModelError
from powers_tool_core.drivers.e36312a import E36312APowerSupply
from powers_tool_core.drivers.psm2010 import PSM2010PowerSupply
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import create_power_supply, select_driver
from powers_tool_core.models import parse_idn
from powers_tool_core.model_resolution import resolve_no_hardware_runtime
from powers_tool_core.live_support import enforce_live_support_for_idn
from powers_tool_core.operations import ScpiLoggingSession
from powers_tool_core.testing.simulator import SimulatedResourceManager

IDN_QUERY = "*IDN?"
SNAPSHOT_SCHEMA_VERSION = 2
SNAPSHOT_KIND = "powers-tool-snapshot"


def run_snapshot(
    request: OperationRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    scpi_logger: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    if request.command != "snapshot":
        raise CoreValidationError(f"unsupported snapshot command {request.command!r}")
    if request.runtime.dry_run or request.runtime.simulate:
        request = replace(request, runtime=resolve_no_hardware_runtime(request.runtime))
        mode = "dry_run" if request.runtime.dry_run else "simulate"
        capabilities.ensure_command_supported(
            request.command,
            request.runtime.planning_model_id,
            request.runtime.planning_profile_id,
            mode,
        )
    instrument, idn = _open(request, opener=opener, scpi_logger=scpi_logger)
    with instrument:
        if not request.runtime.simulate:
            enforce_live_support_for_idn(request, idn)
        power_supply = create_power_supply(instrument.session, idn)
        if not isinstance(power_supply, (E36312APowerSupply, PSM2010PowerSupply)):
            model = parse_idn(idn).model
            raise UnsupportedModelError(
                f"{capabilities.unsupported_command_message('snapshot', model, 'live')}\n"
                f"Found {type(power_supply).__name__} from *IDN? response."
            )
        channels = power_supply.capabilities.channels
        errors, read_count = _read_errors(power_supply, request.parameters.get("max_errors", 20))
        protection_by_channel = [
            {
                "over_voltage_tripped": power_supply.over_voltage_protection_tripped(channel=channel),
                "over_current_tripped": power_supply.over_current_protection_tripped(channel=channel),
            }
            for channel in channels
        ]
        selection = select_driver(idn)
        if selection.physical_identity is None or selection.model_info is None:
            raise CoreValidationError(
                "snapshot manufacturer and model do not resolve to a canonical physical identity"
            )
        parsed_idn = selection.idn
        snapshot = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "kind": SNAPSHOT_KIND,
            "resource": request.runtime.resource,
            "reported_identity": {
                "manufacturer": parsed_idn.manufacturer,
                "model": parsed_idn.model,
                "serial": parsed_idn.serial,
                "firmware": parsed_idn.firmware,
                "parse_ok": parsed_idn.parse_ok,
            },
            "resolved_identity": {
                "vendor_id": selection.physical_identity.vendor_id,
                "model_id": selection.physical_identity.model_id,
                "model_name": selection.physical_identity.canonical_model,
                "display_name": selection.model_info.display_name,
            },
            "errors": errors,
            "read_count": read_count,
            "outputs": [
                {"channel": channel, "enabled": power_supply.output_state(channel=channel)}
                for channel in channels
            ],
            "readback": [
                {
                    "channel": channel,
                    "setpoints": {
                        "voltage": power_supply.programmed_voltage(channel=channel),
                        "current": power_supply.programmed_current(channel=channel),
                    },
                }
                for channel in channels
            ],
            "measurements": [
                {
                    "channel": channel,
                    "measurements": {
                        "voltage": power_supply.measure_voltage(channel=channel),
                        "current": power_supply.measure_current(channel=channel),
                    },
                }
                for channel in channels
            ],
            "protection": {
                key: any(protection[key] for protection in protection_by_channel)
                for key in ("over_voltage_tripped", "over_current_tripped")
            },
            "protection_settings": [
                {
                    "channel": channel,
                    "protection": {
                        "ovp_voltage": _tolerate(lambda channel=channel: power_supply.over_voltage_protection_level(channel=channel)),
                        "ocp_enabled": _tolerate(lambda channel=channel: power_supply.over_current_protection_enabled(channel=channel)),
                        "ocp_delay": _tolerate(lambda channel=channel: power_supply.over_current_protection_delay(channel=channel)),
                        "ocp_delay_trigger": _tolerate(lambda channel=channel: power_supply.over_current_protection_delay_trigger(channel=channel)),
                    },
                }
                for channel in channels
            ],
        }
        if isinstance(power_supply, PSM2010PowerSupply):
            snapshot["output_ranges"] = [
                {
                    "channel": channel,
                    "range": power_supply.output_range(channel=channel),
                }
                for channel in channels
            ]
        return snapshot


def _open(request: OperationRequest, *, opener: Callable[..., Any], scpi_logger: Callable[[str, str, str], None] | None) -> tuple[Any, str]:
    if not request.runtime.resource:
        raise CoreValidationError("resource is required")
    manager = SimulatedResourceManager() if request.runtime.simulate else None
    opened = False
    try:
        context = opener(request.runtime.resource, manager, backend=request.runtime.backend, timeout_ms=request.runtime.timeout_ms)
        instrument = context.__enter__()
        opened = True
        session = ScpiLoggingSession(request.runtime.resource, instrument, scpi_logger) if request.runtime.log_scpi and scpi_logger is not None else instrument
        idn = session.query(IDN_QUERY)
        return _ManagedSession(context, session), idn
    except VisaConnectionError as exc:
        raise CoreIoError(f"snapshot failed: {exc}", opened=opened) from exc
    except (ValueError, TypeError) as exc:
        raise CoreIoError(f"snapshot failed: {exc}", opened=opened) from exc


class _ManagedSession:
    def __init__(self, context: Any, session: Any) -> None:
        self.context = context
        self.session = session

    def __enter__(self) -> "_ManagedSession":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.context.__exit__(exc_type, exc, tb)


def _read_errors(power_supply: Any, max_errors: int) -> tuple[list[str], int]:
    return power_supply.read_error_queue(max_errors)


def _tolerate(callback):
    try:
        return callback()
    except (VisaConnectionError, ValueError):
        return None
