"""Parser-neutral read-only core operations."""

from __future__ import annotations

from typing import Any, Callable
import time
import inspect

from powers_tool_core.core import (
    OperationRequest,
    CoreValidationError,
    UnsupportedModelError,
    UnsupportedChannelError,
    CoreIoError,
)
from powers_tool_core.connection import open_resource, serial_open_kwargs
from powers_tool_core.factory import create_power_supply, select_driver
from powers_tool_core.drivers.e36312a import E36312APowerSupply
from powers_tool_core.drivers.e3646a import E3646APowerSupply
from powers_tool_core.drivers.edu36311a import EDU36311APowerSupply
from powers_tool_core.drivers.psm2010 import PSM2010PowerSupply
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.models import parse_idn
from powers_tool_core.live_support import enforce_live_support_for_idn
from powers_tool_core.testing.simulator import SimulatedResourceManager
from powers_tool_core.transport import dry_run_plan

IDN_QUERY = "*IDN?"
ERROR_QUERY = "SYST:ERR?"

def run_readonly(
    request: OperationRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    scpi_logger: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Run a read-only command and return parser-neutral data."""
    command = "status" if request.command == "read-status" else request.command
    if command not in {"status", "readback", "measure-all"}:
        raise CoreValidationError(f"unsupported read-only command {request.command!r}")

    p = request.parameters
    if command == "measure-all" and p.get("channel") is not None:
        raise CoreValidationError("measure-all always reads all channels and does not accept channel")

    if request.runtime.dry_run:
        return {"plan": readonly_plan(request)}

    opened = False
    try:
        with _open_readonly_resource(request, opener) as instrument:
            opened = True
            if request.runtime.log_scpi and scpi_logger is not None:
                from powers_tool_core.operations import ScpiLoggingSession
                instrument = ScpiLoggingSession(str(request.runtime.resource), instrument, scpi_logger)

            idn_raw = instrument.query(IDN_QUERY)
            if not request.runtime.simulate:
                enforce_live_support_for_idn(request, idn_raw)
            power_supply = create_power_supply(instrument, idn_raw)

            if not isinstance(
                power_supply,
                (E36312APowerSupply, E3646APowerSupply, EDU36311APowerSupply, PSM2010PowerSupply),
            ):
                raise UnsupportedModelError(
                    f"{request.command} is only supported for E36312A, E3646A, EDU36311A, or PSM-2010; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )

            channel_sel = p.get("channel", "all")
            if channel_sel is None:
                channel_sel = "all"
            if channel_sel == "all":
                channels = power_supply.capabilities.channels
            else:
                try:
                    ch = int(channel_sel)
                    if ch not in power_supply.capabilities.channels:
                        raise UnsupportedChannelError(
                            f"channel {ch} is not supported; "
                            f"supported: {power_supply.capabilities.channels}"
                        )
                    channels = (ch,)
                except UnsupportedChannelError:
                    raise
                except (ValueError, TypeError):
                    raise CoreValidationError(f"invalid channel parameter {channel_sel!r}")

            if command == "status":
                max_errors = p.get("max_errors", 20)
                errors, read_count = power_supply.read_error_queue(max_errors)

                outputs = [
                    {"channel": ch, "enabled": power_supply.output_state(channel=ch)}
                    for ch in channels
                ]
                return {
                    "resource": request.runtime.resource,
                    "idn_raw": idn_raw,
                    "errors": errors,
                    "read_count": read_count,
                    "outputs": outputs,
                }

            elif command == "readback":
                return {
                    "resource": request.runtime.resource,
                    "idn_raw": idn_raw,
                    "channels": [
                        {
                            "channel": ch,
                            "setpoints": {
                                "voltage": power_supply.programmed_voltage(channel=ch),
                                "current": power_supply.programmed_current(channel=ch),
                            },
                        }
                        for ch in channels
                    ],
                }

            elif command == "measure-all":
                if not isinstance(power_supply, E36312APowerSupply):
                    raise UnsupportedModelError(
                        f"measure-all is only supported for E36312A; "
                        f"found {type(power_supply).__name__} from *IDN? response"
                    )
                return {
                    "resource": request.runtime.resource,
                    "idn_raw": idn_raw,
                    "channels": [
                        {
                            "channel": ch,
                            "measurements": {
                                "voltage": power_supply.measure_voltage(channel=ch),
                                "current": power_supply.measure_current(channel=ch),
                            },
                        }
                        for ch in channels
                    ],
                }

    except CoreValidationError:
        raise
    except VisaConnectionError as exc:
        raise CoreIoError(f"{request.command} failed: {exc}", opened=opened) from exc
    except (ValueError, TypeError) as exc:
        raise CoreIoError(f"{request.command} failed: {exc}", opened=opened) from exc


def run_live_panel_read(
    request: OperationRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    scpi_logger: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Read only the fields needed by the WebUI live panel."""
    if request.command != "live-panel":
        raise CoreValidationError(f"unsupported live-panel command {request.command!r}")
    if request.runtime.dry_run:
        return {"plan": live_panel_plan(request)}

    opened = False
    try:
        with _open_readonly_resource(request, opener) as instrument:
            opened = True
            if request.runtime.log_scpi and scpi_logger is not None:
                from powers_tool_core.operations import ScpiLoggingSession
                instrument = ScpiLoggingSession(str(request.runtime.resource), instrument, scpi_logger)

            idn_raw = instrument.query(IDN_QUERY)
            if not request.runtime.simulate:
                selection = select_driver(idn_raw)
                model_id = (
                    selection.physical_identity.model_id
                    if selection.physical_identity is not None
                    else None
                )
                for required_command in (
                    ("measure", "output-state", "readback")
                    if model_id == "keysight-e3646a"
                    else ("measure", "output-state", "readback", "protection-status")
                ):
                    enforce_live_support_for_idn(request, idn_raw, command=required_command)
            power_supply = create_power_supply(instrument, idn_raw)
            supported_types = (E36312APowerSupply, E3646APowerSupply, EDU36311APowerSupply)
            if not request.runtime.simulate:
                supported_types = (*supported_types, PSM2010PowerSupply)
            if not isinstance(power_supply, supported_types):
                raise UnsupportedModelError(
                    f"live-panel is only supported for E36312A, E3646A, EDU36311A, "
                    f"or PSM-2010 in Real mode; "
                    f"found {type(power_supply).__name__} from *IDN? response"
                )

            return {
                "resource": request.runtime.resource,
                "idn_raw": idn_raw,
                "idn": parse_idn(idn_raw).to_dict(),
                "channels": [
                    _e3646a_live_channel_payload(power_supply, channel)
                    if isinstance(power_supply, E3646APowerSupply)
                    else _live_channel_payload(power_supply, channel)
                    for channel in power_supply.capabilities.channels
                ],
            }
    except CoreValidationError:
        raise
    except VisaConnectionError as exc:
        raise CoreIoError(f"live-panel failed: {exc}", opened=opened) from exc
    except (ValueError, TypeError) as exc:
        raise CoreIoError(f"live-panel failed: {exc}", opened=opened) from exc


def readonly_plan(request: OperationRequest) -> dict[str, object]:
    """Build a read/query preview for a read-only command without opening VISA."""
    command = "status" if request.command == "read-status" else request.command
    if command == "status":
        channel = request.parameters.get("channel", "all")
        return dry_run_plan(
            command=request.command,
            resource=request.runtime.resource,
            scpi=(ERROR_QUERY, f"OUTP? (@{channel})"),
            description="Preview reading instrument error queue and output state.",
        )
    if command == "readback":
        channel = request.parameters.get("channel", "all")
        return dry_run_plan(
            command=command,
            resource=request.runtime.resource,
            scpi=(f"VOLT? (@{channel})", f"CURR? (@{channel})"),
            description="Preview reading programmed voltage and current setpoints.",
        )
    if command == "measure-all":
        return dry_run_plan(
            command=command,
            resource=request.runtime.resource,
            scpi=(IDN_QUERY, "MEAS:VOLT? (@1)", "MEAS:CURR? (@1)", "MEAS:VOLT? (@2)", "MEAS:CURR? (@2)", "MEAS:VOLT? (@3)", "MEAS:CURR? (@3)"),
            description="Preview reading measured voltage and current for all E36312A channels.",
        )
    raise CoreValidationError(f"unsupported read-only command {command!r}")


def live_panel_plan(request: OperationRequest) -> dict[str, object]:
    return dry_run_plan(
        command="live-panel",
        resource=request.runtime.resource,
        scpi=(
            IDN_QUERY,
            "VOLT:PROT:TRIP? (@1)",
            "CURR:PROT:TRIP? (@1)",
            "OUTP? (@1)",
            "VOLT:PROT? (@1)",
            "CURR:PROT:STAT? (@1)",
            "VOLT? (@1)",
            "CURR? (@1)",
            "MEAS:VOLT? (@1)",
            "MEAS:CURR? (@1)",
            "VOLT:PROT:TRIP? (@2)",
            "CURR:PROT:TRIP? (@2)",
            "OUTP? (@2)",
            "VOLT:PROT? (@2)",
            "CURR:PROT:STAT? (@2)",
            "VOLT? (@2)",
            "CURR? (@2)",
            "MEAS:VOLT? (@2)",
            "MEAS:CURR? (@2)",
            "VOLT:PROT:TRIP? (@3)",
            "CURR:PROT:TRIP? (@3)",
            "OUTP? (@3)",
            "VOLT:PROT? (@3)",
            "CURR:PROT:STAT? (@3)",
            "VOLT? (@3)",
            "CURR? (@3)",
            "MEAS:VOLT? (@3)",
            "MEAS:CURR? (@3)",
        ),
        description="Preview reading WebUI live panel output state, setpoints, measurements, and protection settings.",
    )


def _live_channel_payload(power_supply: Any, channel: int) -> dict[str, Any]:
    over_voltage_tripped = power_supply.over_voltage_protection_tripped(channel=channel)
    over_current_tripped = power_supply.over_current_protection_tripped(channel=channel)
    payload = {
        "channel": channel,
        "output_enabled": power_supply.output_state(channel=channel),
        "over_voltage_tripped": over_voltage_tripped,
        "over_current_tripped": over_current_tripped,
        "protection_tripped": over_voltage_tripped or over_current_tripped,
        "over_voltage_protection_level": power_supply.over_voltage_protection_level(channel=channel),
        "over_current_protection_enabled": power_supply.over_current_protection_enabled(channel=channel),
        "setpoints": {
            "voltage": power_supply.programmed_voltage(channel=channel),
            "current": power_supply.programmed_current(channel=channel),
        },
        "measurements": {
            "voltage": power_supply.measure_voltage(channel=channel),
            "current": power_supply.measure_current(channel=channel),
        },
    }
    if isinstance(power_supply, PSM2010PowerSupply):
        try:
            payload["output_range"] = power_supply.output_range(channel=channel)
        except (VisaConnectionError, ValueError):
            payload["output_range"] = None
    return payload


def _e3646a_live_channel_payload(power_supply: Any, channel: int) -> dict[str, Any]:
    return {
        "channel": channel,
        "output_enabled": power_supply.output_state(channel=channel),
        "over_voltage_tripped": None,
        "over_current_tripped": None,
        "protection_tripped": None,
        "over_voltage_protection_level": None,
        "over_current_protection_enabled": None,
        "setpoints": {
            "voltage": power_supply.programmed_voltage(channel=channel),
            "current": power_supply.programmed_current(channel=channel),
        },
        "measurements": {
            "voltage": power_supply.measure_voltage(channel=channel),
            "current": power_supply.measure_current(channel=channel),
        },
    }


def _open_readonly_resource(request: OperationRequest, opener: Callable[..., Any]) -> Any:
    resource_manager = SimulatedResourceManager() if request.runtime.simulate else None
    if resource_manager is not None and _accepts_resource_manager(opener):
        return opener(
            request.runtime.resource,
            resource_manager,
            backend=request.runtime.backend,
            timeout_ms=request.runtime.timeout_ms,
            **serial_open_kwargs(
                serial_options=request.runtime.serial_options,
                serial_remote=request.runtime.serial_remote,
                serial_local_on_close=request.runtime.serial_local_on_close,
            ),
        )
    return opener(
        request.runtime.resource,
        backend=request.runtime.backend,
        timeout_ms=request.runtime.timeout_ms,
        **serial_open_kwargs(
            serial_options=request.runtime.serial_options,
            serial_remote=request.runtime.serial_remote,
            serial_local_on_close=request.runtime.serial_local_on_close,
        ),
    )


def _accepts_resource_manager(opener: Callable[..., Any]) -> bool:
    try:
        parameters = list(inspect.signature(opener).parameters.values())
    except (TypeError, ValueError):
        return False
    if any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters):
        return True
    return len(parameters) >= 2 and parameters[1].name in {"resource_manager", "manager"}
