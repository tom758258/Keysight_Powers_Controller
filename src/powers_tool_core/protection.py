"""Adapter-neutral protection commands."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Callable

from powers_tool_core import capabilities
from powers_tool_core.connection import open_resource
from powers_tool_core.core import (
    ConfirmationRequiredError,
    CoreExecutionError,
    CoreIoError,
    CoreValidationError,
    OperationRequest,
    UnsupportedModelError,
)
from powers_tool_core.drivers.e36312a import E36312APowerSupply
from powers_tool_core.drivers.edu36311a import EDU36311APowerSupply
from powers_tool_core.drivers.psm2010 import PSM2010PowerSupply
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import create_power_supply
from powers_tool_core.models import parse_idn
from powers_tool_core.model_resolution import (
    no_hardware_channels,
    resolve_no_hardware_runtime,
)
from powers_tool_core.live_support import enforce_live_support_for_idn
from powers_tool_core.operations import ScpiLoggingSession
from powers_tool_core.safety import SafetyConfigError, SafetyValidationError, resolve_safety_config, validate_channel, validate_setpoint
from powers_tool_core.testing.simulator import SimulatedResourceManager
from powers_tool_core.transport import dry_run_plan
from powers_tool_core.validation import ChannelSelectionError, expand_channel_selection

IDN_QUERY = "*IDN?"
SUPPORTED_TYPES = (E36312APowerSupply, EDU36311APowerSupply, PSM2010PowerSupply)
OCP_DELAY_TRIGGERS = {"setting-change": "SCH", "cc-transition": "CCTR"}
PROTECTION_SET_OPERATION_ERROR = (
    "protection-set requires --ovp-voltage, --ocp, --ocp-delay, or --ocp-delay-trigger"
)


def run_protection(
    request: OperationRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    scpi_logger: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    from powers_tool_core.command_runner import validate_request_admission

    request = validate_request_admission(request)
    if request.command == "protection-status":
        return _run_status(request, opener=opener, scpi_logger=scpi_logger)
    if request.command == "protection-set":
        request = replace(request, runtime=resolve_no_hardware_runtime(request.runtime))
        _ensure_protection_supported(request)
        return _run_set(request, opener=opener, scpi_logger=scpi_logger)
    if request.command == "clear-protection":
        request = replace(request, runtime=resolve_no_hardware_runtime(request.runtime))
        _ensure_protection_supported(request)
        return _run_clear(request, opener=opener, scpi_logger=scpi_logger)
    raise CoreValidationError(f"unsupported protection command {request.command!r}")


def _run_status(request: OperationRequest, *, opener: Callable[..., Any], scpi_logger: Callable[[str, str, str], None] | None) -> dict[str, Any]:
    selected = _selected_channel(request)
    _channels(selected, E36312APowerSupply.capabilities.channels)
    instrument, idn = _open(request, opener=opener, scpi_logger=scpi_logger)
    with instrument:
        if not request.runtime.simulate:
            enforce_live_support_for_idn(request, idn)
        power_supply = create_power_supply(instrument.session, idn)
        _require_supported(power_supply, request.command, parse_idn(idn).model)
        channels = _channels(selected, power_supply.capabilities.channels)
        protection_by_channel = [
            {
                "channel": channel,
                "protection": _protection_payload(power_supply, channel=channel),
            }
            for channel in channels
        ]
        protection = _aggregate_protection(protection_by_channel)
        channel_trips = {
            item["channel"]: (
                item["protection"]["over_voltage_tripped"]
                or item["protection"]["over_current_tripped"]
            )
            for item in protection_by_channel
        }
        return {
            "resource": request.runtime.resource,
            "idn": parse_idn(idn).to_dict(),
            "protection": protection,
            "protection_by_channel": protection_by_channel,
            "outputs": [
                {
                    "channel": channel,
                    "enabled": (enabled := power_supply.output_state(channel=channel)),
                    "disabled_with_protection": (not enabled) and channel_trips[channel],
                }
                for channel in channels
            ],
        }


def _run_clear(request: OperationRequest, *, opener: Callable[..., Any], scpi_logger: Callable[[str, str, str], None] | None) -> dict[str, Any]:
    selected = _selected_channel(request)
    channels = _channels(selected, _plan_supported_channels(request))
    if request.runtime.dry_run or request.runtime.simulate:
        psm2010 = request.runtime.planning_model_id == "gw-instek-psm-2010"
        return {
            "plan": dry_run_plan(
                command=request.command,
                resource=request.runtime.resource,
                planning_model_id=request.runtime.planning_model_id,
                planning_profile_id=request.runtime.planning_profile_id,
                scpi=(
                    tuple(
                        command
                        for _channel in channels
                        for command in ("CURR:PROT:CLE", "VOLT:PROT:CLE")
                    )
                    if psm2010
                    else tuple(f"OUTP:PROT:CLE (@{channel})" for channel in channels)
                ),
                description="Preview clearing output protection for selected channels.",
            )
        }
    if not request.runtime.simulate and not request.runtime.confirm:
        raise ConfirmationRequiredError("clear-protection real execution requires --confirm")
    instrument, idn = _open(request, opener=opener, scpi_logger=scpi_logger)
    with instrument:
        enforce_live_support_for_idn(request, idn)
        power_supply = create_power_supply(instrument.session, idn)
        _require_supported(power_supply, request.command, parse_idn(idn).model)
        channels = _channels(selected, power_supply.capabilities.channels)
        for channel in channels:
            power_supply.clear_output_protection(channel=channel)
        _raise_on_errors(power_supply, request.command)
    return {"resource": request.runtime.resource, "cleared_channels": list(channels)}


def _run_set(request: OperationRequest, *, opener: Callable[..., Any], scpi_logger: Callable[[str, str, str], None] | None) -> dict[str, Any]:
    p = request.parameters
    if not _has_set_operation(p):
        raise CoreValidationError(PROTECTION_SET_OPERATION_ERROR)
    ocp_delay = _optional_ocp_delay(p.get("ocp_delay"))
    ocp_delay_trigger = _optional_ocp_delay_trigger(p.get("ocp_delay_trigger"))
    _validate_psm_protection_options(
        _known_runtime_model_id(request) == "gw-instek-psm-2010",
        ocp_delay=ocp_delay,
        ocp_delay_trigger=ocp_delay_trigger,
    )
    channels = _channels(_selected_channel(request), _plan_supported_channels(request))
    limits = _safety_limits(request)
    try:
        for channel in channels:
            validate_channel(channel, limits)
            if p.get("ovp_voltage") is not None:
                validate_setpoint(channel=channel, voltage=p["ovp_voltage"], limits=limits)
    except (SafetyValidationError, SafetyConfigError) as exc:
        raise CoreValidationError(str(exc)) from exc
    if request.runtime.dry_run or request.runtime.simulate:
        return {
            "plan": dry_run_plan(
                command=request.command,
                resource=request.runtime.resource,
                planning_model_id=request.runtime.planning_model_id,
                planning_profile_id=request.runtime.planning_profile_id,
                scpi=_protection_set_scpi(
                    channels,
                    p.get("ovp_voltage"),
                    p.get("ocp"),
                    ocp_delay,
                    ocp_delay_trigger,
                    psm2010=request.runtime.planning_model_id == "gw-instek-psm-2010",
                ),
                description="Preview setting output protection for selected channels.",
            )
        }
    if not request.runtime.simulate and not request.runtime.confirm:
        raise ConfirmationRequiredError("protection-set real execution requires --confirm")
    instrument, idn = _open(request, opener=opener, scpi_logger=scpi_logger)
    with instrument:
        enforce_live_support_for_idn(request, idn)
        power_supply = create_power_supply(instrument.session, idn)
        _require_supported(power_supply, request.command, parse_idn(idn).model)
        _validate_psm_protection_options(
            isinstance(power_supply, PSM2010PowerSupply),
            ocp_delay=ocp_delay,
            ocp_delay_trigger=ocp_delay_trigger,
        )
        channels = _channels(_selected_channel(request), power_supply.capabilities.channels)
        for channel in channels:
            if p.get("ovp_voltage") is not None:
                power_supply.set_over_voltage_protection(channel=channel, voltage=p["ovp_voltage"])
            if p.get("ocp") is not None:
                power_supply.set_over_current_protection_enabled(channel=channel, enabled=p["ocp"] == "on")
            if ocp_delay is not None:
                power_supply.set_over_current_protection_delay(channel=channel, seconds=ocp_delay)
            if ocp_delay_trigger is not None:
                power_supply.set_over_current_protection_delay_trigger(channel=channel, trigger=ocp_delay_trigger)
        _raise_on_errors(power_supply, request.command)
    return {
        "resource": request.runtime.resource,
        "channels": [
            {
                "channel": channel,
                "protection": {
                    "ovp_voltage": _json_safe_number(p["ovp_voltage"]) if p.get("ovp_voltage") is not None else None,
                    "ocp_enabled": (p["ocp"] == "on" if p.get("ocp") is not None else None),
                    "ocp_delay": _json_safe_number(ocp_delay) if ocp_delay is not None else None,
                    "ocp_delay_trigger": ocp_delay_trigger,
                },
            }
            for channel in channels
        ],
    }


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
        raise CoreIoError(f"{request.command} failed: {exc}", opened=opened) from exc
    except (ValueError, TypeError) as exc:
        raise CoreIoError(f"{request.command} failed: {exc}", opened=opened) from exc


class _ManagedSession:
    def __init__(self, context: Any, session: Any) -> None:
        self.context = context
        self.session = session

    def __enter__(self) -> "_ManagedSession":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.context.__exit__(exc_type, exc, tb)


def _require_supported(power_supply: Any, command: str, model: str | None) -> None:
    if not isinstance(power_supply, SUPPORTED_TYPES):
        raise UnsupportedModelError(
            f"{capabilities.unsupported_command_message(command, model, 'live')}\n"
            f"Found {type(power_supply).__name__} from *IDN? response."
        )


def _ensure_protection_supported(request: OperationRequest) -> None:
    if not (request.runtime.dry_run or request.runtime.simulate):
        return
    mode = "dry_run" if request.runtime.dry_run else "simulate"
    capabilities.ensure_command_supported(
        request.command,
        request.runtime.planning_model_id,
        request.runtime.planning_profile_id,
        mode,
    )


def _selected_channel(request: OperationRequest) -> int | str:
    try:
        return request.parameters["channel"]
    except KeyError as exc:
        raise CoreValidationError("protection request is missing admitted channel") from exc


def _channels(selected: int | str | None, supported: tuple[int, ...]) -> tuple[int, ...]:
    if selected is None:
        raise CoreValidationError("clear-protection requires --channel N or --all")
    try:
        return expand_channel_selection(selected, supported)
    except ChannelSelectionError as exc:
        raise CoreValidationError(str(exc)) from exc


def _plan_supported_channels(request: OperationRequest) -> tuple[int, ...]:
    if request.runtime.dry_run or request.runtime.simulate:
        if (
            request.runtime.planning_model_id is not None
            or request.runtime.planning_profile_id is not None
        ):
            return no_hardware_channels(
                request.runtime.planning_model_id,
                request.runtime.planning_profile_id,
            )
    return E36312APowerSupply.capabilities.channels


def _protection_payload(power_supply: Any, *, channel: int) -> dict[str, bool]:
    return {
        "over_voltage_tripped": power_supply.over_voltage_protection_tripped(channel=channel),
        "over_current_tripped": power_supply.over_current_protection_tripped(channel=channel),
    }


def _aggregate_protection(protection_by_channel: list[dict[str, Any]]) -> dict[str, bool]:
    return {
        key: any(item["protection"][key] for item in protection_by_channel)
        for key in ("over_voltage_tripped", "over_current_tripped")
    }


def _has_set_operation(parameters: dict[str, Any]) -> bool:
    return any(
        parameters.get(key) is not None
        for key in ("ovp_voltage", "ocp", "ocp_delay", "ocp_delay_trigger")
    )


def _optional_ocp_delay(value: Any) -> float | None:
    if value is None:
        return None
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise CoreValidationError("ocp_delay must be a finite non-negative number")
    return value


def _optional_ocp_delay_trigger(value: Any) -> str | None:
    if value is None:
        return None
    if value not in OCP_DELAY_TRIGGERS:
        raise CoreValidationError(
            "ocp_delay_trigger must be one of: setting-change, cc-transition"
        )
    return str(value)


def _protection_set_scpi(
    channels: tuple[int, ...],
    ovp_voltage: float | None,
    ocp: str | None,
    ocp_delay: float | None,
    ocp_delay_trigger: str | None,
    *,
    psm2010: bool = False,
) -> tuple[str, ...]:
    commands: list[str] = []
    for channel in channels:
        if ovp_voltage is not None:
            commands.append(_protection_scpi(f"VOLT:PROT {_json_safe_number(ovp_voltage)}", channel, psm2010))
        if ocp is not None:
            commands.append(_protection_scpi(f"CURR:PROT:STAT {ocp.upper()}", channel, psm2010))
        if ocp_delay is not None:
            commands.append(_protection_scpi(f"CURR:PROT:DEL {_json_safe_number(ocp_delay)}", channel, psm2010))
        if ocp_delay_trigger is not None:
            commands.append(_protection_scpi(f"CURR:PROT:DEL:STAR {OCP_DELAY_TRIGGERS[ocp_delay_trigger]}", channel, psm2010))
    return tuple(commands)


def _protection_scpi(command: str, channel: int, psm2010: bool) -> str:
    return command if psm2010 else f"{command},(@{channel})"


def _validate_psm_protection_options(
    psm2010: bool,
    *,
    ocp_delay: float | None,
    ocp_delay_trigger: str | None,
) -> None:
    if not psm2010:
        return
    if ocp_delay_trigger is not None:
        raise CoreValidationError(
            "PSM-2010 does not support the ocp_delay_trigger protection option"
        )
    if ocp_delay is not None:
        raise CoreValidationError(
            "PSM-2010 does not support the ocp_delay protection option"
        )


def _known_runtime_model_id(request: OperationRequest) -> str | None:
    return request.runtime.planning_model_id or request.runtime.expected_model_id


def _safety_limits(request: OperationRequest):
    if request.runtime.safety_config is None:
        return None
    try:
        return resolve_safety_config(
            request.runtime.safety_config,
            resource=None if request.runtime.resource_alias is not None else request.runtime.resource,
            resource_alias=request.runtime.resource_alias,
        ).limits
    except SafetyConfigError as exc:
        raise CoreValidationError(str(exc)) from exc
    except SafetyValidationError as exc:
        raise CoreValidationError(str(exc)) from exc


def _raise_on_errors(power_supply: Any, command: str) -> None:
    errors, _read_count = power_supply.read_error_queue(20)
    if errors:
        raise CoreExecutionError(f"{command} completed with instrument errors: {errors}")


def _json_safe_number(value: float) -> float | str:
    numeric = float(value)
    return int(numeric) if numeric.is_integer() else numeric
