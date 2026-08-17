"""Adapter-neutral simple instrument I/O commands."""

from __future__ import annotations

from typing import Any, Callable

from powers_tool_core.connection import open_resource, serial_open_kwargs
from powers_tool_core.core import CoreIoError, CoreValidationError, OperationRequest, UnsupportedChannelError
from powers_tool_core.discovery import resource_payload
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import create_power_supply
from powers_tool_core.identity import IdentityResolutionError, resolve_physical_model_identity
from powers_tool_core.models import parse_idn, resource_interface
from powers_tool_core.live_support import enforce_live_support_for_idn
from powers_tool_core.model_resolution import validate_live_expected_model
from powers_tool_core.operations import ScpiLoggingSession
from powers_tool_core.testing.simulator import SimulatedResourceManager
from powers_tool_core.transport import dry_run_plan

CLEAR_STATUS_COMMAND = "*CLS"
IDN_QUERY = "*IDN?"
EXTENDED_IDENTITY_QUERIES = {
    "options": "*OPT?",
    "scpi_version": "SYST:VERS?",
    "remote_lockout_state": "SYST:COMM:RLST?",
}


def run_instrument_io(
    request: OperationRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    scpi_logger: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    if request.command == "clear":
        return _run_clear(request, opener=opener, scpi_logger=scpi_logger)
    if request.command == "error":
        return _run_error(request, opener=opener, scpi_logger=scpi_logger)
    if request.command == "measure":
        return _run_measure(request, opener=opener, scpi_logger=scpi_logger)
    if request.command == "identify":
        return _run_identify(request, opener=opener, scpi_logger=scpi_logger)
    raise CoreValidationError(f"unsupported instrument I/O command {request.command!r}")


def _run_clear(
    request: OperationRequest,
    *,
    opener: Callable[..., Any],
    scpi_logger: Callable[[str, str, str], None] | None,
) -> dict[str, Any]:
    if request.runtime.dry_run:
        return {
            "plan": dry_run_plan(
                command="clear",
                resource=request.runtime.resource,
                scpi=(CLEAR_STATUS_COMMAND,),
                description="Preview clearing instrument status and error queue.",
            )
        }
    resource = _require_resource(request)
    instrument = _open_session(request, opener=opener, scpi_logger=scpi_logger)
    with instrument:
        instrument.session.write(CLEAR_STATUS_COMMAND)
    return {
        "resource": resource_payload(resource, simulated=request.runtime.simulate, reachable=True, idn_raw=None),
        "cleared": True,
    }


def _run_error(
    request: OperationRequest,
    *,
    opener: Callable[..., Any],
    scpi_logger: Callable[[str, str, str], None] | None,
) -> dict[str, Any]:
    resource = _require_resource(request)
    max_reads = request.parameters.get("max_reads", 20)
    instrument = _open_session(request, opener=opener, scpi_logger=scpi_logger)
    with instrument:
        errors, read_count = _read_error_queue(instrument.session, max_reads)
    return {
        "resource": resource_payload(resource, simulated=request.runtime.simulate, reachable=True, idn_raw=None),
        "errors": errors,
        "read_count": read_count,
        "max_reads": max_reads,
    }


def _run_measure(
    request: OperationRequest,
    *,
    opener: Callable[..., Any],
    scpi_logger: Callable[[str, str, str], None] | None,
) -> dict[str, Any]:
    channel = request.parameters.get("channel", 1)
    resource = _require_resource(request)
    if channel == 1 and not request.runtime.simulate and resource_interface(resource) != "ASRL":
        instrument, idn = _open_power_supply(request, opener=opener, scpi_logger=scpi_logger)
        with instrument:
            enforce_live_support_for_idn(request, idn)
            measurements = {
                "voltage": _parse_float(instrument.session.query("MEAS:VOLT?"), "voltage"),
                "current": _parse_float(instrument.session.query("MEAS:CURR?"), "current"),
            }
        return {
            "resource": resource_payload(resource, simulated=False, reachable=True, idn_raw=None),
            "channel": channel,
            "measurements": measurements,
        }
    instrument, idn = _open_power_supply(request, opener=opener, scpi_logger=scpi_logger)
    with instrument:
        if not request.runtime.simulate:
            enforce_live_support_for_idn(request, idn)
        power_supply = create_power_supply(instrument.session, idn)
        allowed = (
            power_supply.capabilities.simulated_measure_channels
            if request.runtime.simulate
            else power_supply.capabilities.real_measure_channels
        )
        if channel not in allowed:
            mode = "simulate" if request.runtime.simulate else "real"
            raise UnsupportedChannelError(
                f"measure channel {channel} is not enabled in {mode} mode for "
                f"{type(power_supply).__name__}; supported: {_format_channel_set(tuple(allowed))}"
            )
        measurements = {
            "voltage": power_supply.measure_voltage(channel=channel),
            "current": power_supply.measure_current(channel=channel),
        }
    return {
        "resource": resource_payload(resource, simulated=request.runtime.simulate, reachable=True, idn_raw=None),
        "channel": channel,
        "measurements": measurements,
    }


def _run_identify(
    request: OperationRequest,
    *,
    opener: Callable[..., Any],
    scpi_logger: Callable[[str, str, str], None] | None,
) -> dict[str, Any]:
    resource = _require_resource(request)
    instrument, idn = _open_power_supply(request, opener=opener, scpi_logger=scpi_logger)
    with instrument:
        session = instrument.session
        idn_info = parse_idn(idn)
        data = {
            "resource": resource,
            "idn": idn_info.to_dict(),
            "options": None,
            "scpi_version": None,
            "remote_lockout_state": None,
        }
        try:
            try:
                identity = resolve_physical_model_identity(
                    idn_info.manufacturer,
                    idn_info.model,
                )
            except IdentityResolutionError:
                identity = None
            model_id = identity.model_id if identity is not None else None
            if not request.runtime.simulate:
                validate_live_expected_model(
                    request.runtime.expected_model_id,
                    model_id,
                    command=request.command,
                )
            for field, query in _identity_queries_for_model_id(model_id).items():
                data[field] = session.query(query).strip()
        except CoreValidationError:
            raise
        except (VisaConnectionError, ValueError, TypeError) as exc:
            raise CoreIoError(f"{request.command} failed: {exc}", opened=True) from exc
        return data


def _identity_queries_for_model_id(model_id: str | None) -> dict[str, str]:
    if model_id in {
        "keysight-edu36311a",
        "keysight-e3646a",
        "gw-instek-psm-2010",
    }:
        return {}
    return EXTENDED_IDENTITY_QUERIES


class _ManagedSession:
    def __init__(self, context: Any, session: Any) -> None:
        self.context = context
        self.session = session

    def __enter__(self) -> "_ManagedSession":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.context.__exit__(exc_type, exc, tb)


def _open_power_supply(
    request: OperationRequest,
    *,
    opener: Callable[..., Any],
    scpi_logger: Callable[[str, str, str], None] | None,
) -> tuple[_ManagedSession, str]:
    resource = _require_resource(request)
    manager = SimulatedResourceManager() if request.runtime.simulate else None
    opened = False
    try:
        context = opener(
            resource,
            manager,
            backend=request.runtime.backend,
            timeout_ms=request.runtime.timeout_ms,
            **serial_open_kwargs(
                serial_options=request.runtime.serial_options,
                serial_remote=request.runtime.serial_remote,
                serial_local_on_close=request.runtime.serial_local_on_close,
            ),
        )
        instrument = context.__enter__()
        opened = True
        session = (
            ScpiLoggingSession(resource, instrument, scpi_logger)
            if request.runtime.log_scpi and scpi_logger is not None
            else instrument
        )
        idn = session.query(IDN_QUERY)
        return _ManagedSession(context, session), idn
    except VisaConnectionError as exc:
        raise CoreIoError(f"{request.command} failed: {exc}", opened=opened) from exc
    except (ValueError, TypeError) as exc:
        raise CoreIoError(f"{request.command} failed: {exc}", opened=opened) from exc


def _open_session(
    request: OperationRequest,
    *,
    opener: Callable[..., Any],
    scpi_logger: Callable[[str, str, str], None] | None,
) -> _ManagedSession:
    resource = _require_resource(request)
    manager = SimulatedResourceManager() if request.runtime.simulate else None
    opened = False
    try:
        context = opener(
            resource,
            manager,
            backend=request.runtime.backend,
            timeout_ms=request.runtime.timeout_ms,
            **serial_open_kwargs(
                serial_options=request.runtime.serial_options,
                serial_remote=request.runtime.serial_remote,
                serial_local_on_close=request.runtime.serial_local_on_close,
            ),
        )
        instrument = context.__enter__()
        opened = True
        session = (
            ScpiLoggingSession(resource, instrument, scpi_logger)
            if request.runtime.log_scpi and scpi_logger is not None
            else instrument
        )
        return _ManagedSession(context, session)
    except VisaConnectionError as exc:
        raise CoreIoError(f"{request.command} failed: {exc}", opened=opened) from exc
    except (ValueError, TypeError) as exc:
        raise CoreIoError(f"{request.command} failed: {exc}", opened=opened) from exc


def _require_resource(request: OperationRequest) -> str:
    if not request.runtime.resource:
        raise CoreValidationError("resource is required")
    return request.runtime.resource


def _read_error_queue(session: Any, max_reads: int) -> tuple[list[str], int]:
    if max_reads < 1:
        raise CoreValidationError("max_reads must be at least 1")
    errors = []
    read_count = 0
    for _ in range(max_reads):
        response = session.query("SYST:ERR?").strip()
        read_count += 1
        norm = response.lstrip("+")
        if norm == "0" or norm.startswith("0,"):
            break
        errors.append(response)
    return errors, read_count


def _parse_float(response: str, label: str) -> float:
    try:
        return float(response.strip())
    except ValueError as exc:
        raise CoreIoError(f"Could not parse {label} measurement: {response!r}", opened=True) from exc


def _format_channel_set(channels: tuple[int, ...]) -> str:
    if channels == (1,):
        return "channel 1 only"
    return "channels " + ", ".join(str(channel) for channel in channels)
