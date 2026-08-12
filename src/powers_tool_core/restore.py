"""Adapter-neutral restore-from-snapshot command."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import math
from pathlib import Path
from typing import Any, Callable

from powers_tool_core import capabilities
from powers_tool_core.connection import open_resource
from powers_tool_core.cancellation import StopRequested, raise_if_cancelled
from powers_tool_core.core import ConfirmationRequiredError, CoreIoError, CoreValidationError, OperationRequest, UnsupportedModelError
from powers_tool_core.drivers.e36312a import E36312APowerSupply
from powers_tool_core.drivers.psm2010 import (
    PSM2010PowerSupply,
    _compatible_programming_ranges,
    _validate_psm2010_ovp_level,
)
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import create_power_supply
from powers_tool_core.identity import IDENTITY_INDEXES, IdentityResolutionError, resolve_physical_model_identity
from powers_tool_core.models import parse_idn
from powers_tool_core.model_resolution import resolve_no_hardware_runtime
from powers_tool_core.live_support import enforce_live_support_for_idn
from powers_tool_core.operations import IDN_QUERY, ScpiLoggingSession
from powers_tool_core.parameter_constraints import strict_boolean_parameter, strict_channel_parameter
from powers_tool_core.safety import SafetyValidationError
from powers_tool_core.setpoint_limits import validate_effective_setpoint
from powers_tool_core.testing.simulator import SimulatedResourceManager
from powers_tool_core.snapshot import SNAPSHOT_KIND, SNAPSHOT_SCHEMA_VERSION
from powers_tool_core.command_contract import validate_and_normalize_request


def run_restore(
    request: OperationRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    scpi_logger: Callable[[str, str, str], None] | None = None,
    stop_requested: StopRequested = None,
) -> dict[str, Any]:
    from powers_tool_core.command_runner import validate_request_admission

    return _run_restore_admitted(
        validate_request_admission(request),
        opener=opener,
        scpi_logger=scpi_logger,
        stop_requested=stop_requested,
    )


def _run_restore_admitted(
    request: OperationRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    scpi_logger: Callable[[str, str, str], None] | None = None,
    stop_requested: StopRequested = None,
) -> dict[str, Any]:
    """Execute an admitted restore request using its canonical document only."""

    if request.command != "restore-from-snapshot":
        raise CoreValidationError(f"unsupported restore command {request.command!r}")
    request, snapshot = prepare_restore_request(request)
    restore_output_state = strict_boolean_parameter(
        request.parameters,
        "restore_output_state",
        default=False,
    )
    if request.runtime.dry_run or request.runtime.simulate:
        mode = "dry_run" if request.runtime.dry_run else "simulate"
        capabilities.ensure_command_supported(
            request.command,
            request.runtime.planning_model_id,
            request.runtime.planning_profile_id,
            mode,
        )
    channels = _restore_channels(request, snapshot)
    plan = restore_plan(
        snapshot,
        resource=str(request.runtime.resource),
        channels=channels,
        restore_output_state=restore_output_state,
        allow_output_on=restore_output_state and request.runtime.confirm,
    )
    if request.runtime.dry_run or request.runtime.simulate:
        return {
            "plan": plan,
            "restored_channels": list(channels),
            "restore_output_state": restore_output_state,
            "resource": request.runtime.resource,
        }
    if not request.runtime.confirm:
        raise ConfirmationRequiredError("restore-from-snapshot real execution requires confirmation")
    resource = request.runtime.resource
    if not resource:
        raise CoreValidationError("resource is required")
    manager = SimulatedResourceManager() if request.runtime.simulate else None
    opened = False
    try:
        with opener(resource, manager, backend=request.runtime.backend, timeout_ms=request.runtime.timeout_ms) as instrument:
            opened = True
            session = ScpiLoggingSession(resource, instrument, scpi_logger) if request.runtime.log_scpi and scpi_logger is not None else instrument
            idn_raw = session.query(IDN_QUERY)
            parsed_idn = parse_idn(idn_raw)
            resolved_identity = _validate_restore_identity(parsed_idn, snapshot)
            enforce_live_support_for_idn(request, idn_raw)
            power_supply = create_power_supply(session, idn_raw)
            if not isinstance(power_supply, (E36312APowerSupply, PSM2010PowerSupply)):
                model = parse_idn(idn_raw).model
                raise UnsupportedModelError(
                    f"{capabilities.unsupported_command_message('restore-from-snapshot', model, 'live')}\n"
                    f"Found {type(power_supply).__name__} from *IDN? response."
                )
            _validate_restore_setpoints(power_supply, plan)
            _execute_restore_plan(power_supply, plan, stop_requested=stop_requested)
            _raise_on_instrument_errors(power_supply)
    except CoreValidationError:
        raise
    except VisaConnectionError as exc:
        raise CoreIoError(f"{'restore-from-snapshot failed' if opened else 'Could not open resource for restore-from-snapshot'}: {exc}", opened=opened) from exc
    except (ValueError, TypeError) as exc:
        raise CoreIoError(f"restore-from-snapshot failed: {exc}", opened=opened) from exc
    model_info = IDENTITY_INDEXES.models_by_id[resolved_identity.model_id]
    return {
        "resource": resource,
        "restored_channels": list(channels),
        "plan": plan,
        "reported_identity": {
            "manufacturer": parsed_idn.manufacturer,
            "model": parsed_idn.model,
            "serial": parsed_idn.serial,
            "firmware": parsed_idn.firmware,
            "parse_ok": parsed_idn.parse_ok,
        },
        "resolved_identity": {
            "vendor_id": resolved_identity.vendor_id,
            "model_id": resolved_identity.model_id,
            "model_name": resolved_identity.canonical_model,
            "display_name": model_info.display_name,
        },
    }


def restore_plan(
    snapshot: dict[str, Any],
    *,
    resource: str,
    channels: tuple[int, ...],
    restore_output_state: bool,
    allow_output_on: bool,
) -> dict[str, Any]:
    model_id = snapshot["resolved_identity"]["model_id"]
    psm2010 = model_id == "gw-instek-psm-2010"
    outputs = _records_by_channel(snapshot.get("outputs"))
    readback = _records_by_channel(snapshot.get("readback"))
    protection = _records_by_channel(snapshot.get("protection_settings"))
    output_ranges = _records_by_channel(snapshot.get("output_ranges"))
    steps: list[dict[str, Any]] = []
    for channel in channels:
        if channel not in outputs:
            raise CoreValidationError(f"snapshot outputs does not contain channel {channel}")
        if channel not in readback:
            raise CoreValidationError(f"snapshot readback does not contain channel {channel}")
        if channel not in protection:
            raise CoreValidationError(
                f"snapshot protection_settings does not contain channel {channel}"
            )
        if psm2010 and channel not in output_ranges:
            raise CoreValidationError(
                f"snapshot output_ranges does not contain channel {channel}"
            )
        protection_record = protection[channel]["protection"]
        if psm2010 and protection_record.get("ocp_delay") is not None:
            raise CoreValidationError("PSM-2010 snapshot ocp_delay must be null")
        steps.append(_restore_step("output_off", _restore_scpi("OUTP OFF", channel, psm2010), channel=channel))
        if psm2010:
            output_range = output_ranges[channel]["range"]
            steps.append(
                _restore_step(
                    "set_output_range",
                    f"VOLT:RANG {output_range}",
                    channel=channel,
                    output_range=output_range,
                )
            )
        ovp_voltage = protection_record.get("ovp_voltage")
        if ovp_voltage is not None:
            steps.append(_restore_step("set_over_voltage_protection", _restore_scpi(f"VOLT:PROT {_format_value(ovp_voltage)}", channel, psm2010), channel=channel, voltage=ovp_voltage))
        ocp_enabled = protection_record.get("ocp_enabled")
        if ocp_enabled is not None:
            ocp_command = "ON" if ocp_enabled else "OFF"
            steps.append(_restore_step("set_over_current_protection_enabled", _restore_scpi(f"CURR:PROT:STAT {ocp_command}", channel, psm2010), channel=channel, enabled=ocp_enabled))
        ocp_delay = protection_record.get("ocp_delay")
        if ocp_delay is not None:
            steps.append(_restore_step("set_over_current_protection_delay", _restore_scpi(f"CURR:PROT:DEL {_format_value(ocp_delay)}", channel, psm2010), channel=channel, seconds=ocp_delay))
        ocp_delay_trigger = protection_record.get("ocp_delay_trigger")
        if ocp_delay_trigger is not None:
            trigger_command = _ocp_delay_trigger_scpi(ocp_delay_trigger)
            steps.append(_restore_step("set_over_current_protection_delay_trigger", _restore_scpi(f"CURR:PROT:DEL:STAR {trigger_command}", channel, psm2010), channel=channel, trigger=ocp_delay_trigger))
        setpoints = readback.get(channel, {}).get("setpoints", {})
        if "current" not in setpoints or "voltage" not in setpoints:
            raise CoreValidationError(f"snapshot does not contain voltage/current setpoints for channel {channel}")
        steps.append(_restore_step("set_current_limit", _restore_scpi(f"CURR {_format_value(setpoints['current'])}", channel, psm2010), channel=channel, current=setpoints["current"]))
        steps.append(_restore_step("set_voltage", _restore_scpi(f"VOLT {_format_value(setpoints['voltage'])}", channel, psm2010), channel=channel, voltage=setpoints["voltage"]))
        if restore_output_state and allow_output_on and outputs.get(channel, {}).get("enabled") is True:
            steps.append(_restore_step("output_on", _restore_scpi("OUTP ON", channel, psm2010), channel=channel))
    return {
        "operation": {"name": "restore-from-snapshot"},
        "target": {"resource": resource, "channels": list(channels)},
        "steps": [{"index": index, "type": "driver_action", **step} for index, step in enumerate(steps, start=1)],
        "description": "Restore output-off, protection settings, current, voltage, and optionally prior ON states.",
        "hardware_touched": False,
    }


def prepare_restore_request(
    request: OperationRequest,
) -> tuple[OperationRequest, dict[str, Any]]:
    """Validate snapshot identity and resolve no-hardware restore planning."""

    strict_boolean_parameter(request.parameters, "restore_output_state", default=False)
    snapshot = snapshot_document_for_request(request)
    snapshot_model_id = snapshot["resolved_identity"]["model_id"]
    if request.runtime.planning_profile_id is not None:
        raise CoreValidationError("planning_profile_id is invalid for restore-from-snapshot")
    if request.runtime.dry_run or request.runtime.simulate:
        explicit_model_id = request.runtime.planning_model_id
        if explicit_model_id is not None and explicit_model_id != snapshot_model_id:
            raise CoreValidationError(
                f"planning_model_id {explicit_model_id!r} does not match snapshot "
                f"model_id {snapshot_model_id!r}"
            )
        request = replace(
            request,
            runtime=replace(
                request.runtime,
                planning_model_id=snapshot_model_id,
            ),
        )
        request = replace(request, runtime=resolve_no_hardware_runtime(request.runtime))
    return request, snapshot


def validate_restore_admission(request: OperationRequest) -> OperationRequest:
    """Validate restore document, identity, channels, and plan without I/O."""

    request = validate_and_normalize_request(request)
    request, snapshot = prepare_restore_request(request)
    request = replace(
        request,
        parameters={
            **{
                key: value
                for key, value in request.parameters.items()
                if key not in {"file", "snapshot", "document"}
            },
            "document": deepcopy(snapshot),
        },
    )
    restore_output_state = strict_boolean_parameter(
        request.parameters,
        "restore_output_state",
        default=False,
    )
    channels = _restore_channels(request, snapshot)
    restore_plan(
        snapshot,
        resource=str(request.runtime.resource),
        channels=channels,
        restore_output_state=restore_output_state,
        allow_output_on=False,
    )
    return request


def snapshot_document_for_request(request: OperationRequest) -> dict[str, Any]:
    """Load and strictly validate one schema-2 snapshot document."""

    document = request.parameters.get("document")
    if isinstance(document, dict):
        return validate_snapshot_document(document)
    path = request.parameters.get("snapshot")
    if path is None:
        path = request.parameters.get("file")
    if path is None:
        raise CoreValidationError("restore-from-snapshot requires snapshot, file, or document")
    try:
        loaded = json.loads(Path(str(path)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoreValidationError(str(exc)) from exc
    if not isinstance(loaded, dict):
        raise CoreValidationError("snapshot document must be a JSON object")
    return validate_snapshot_document(loaded)


def validate_snapshot_document(document: dict[str, Any]) -> dict[str, Any]:
    """Require the canonical schema-2 snapshot identity contract."""

    schema_version = document.get("schema_version")
    if type(schema_version) is not int or schema_version != SNAPSHOT_SCHEMA_VERSION:
        raise CoreValidationError("snapshot requires integer schema_version=2")
    if document.get("kind") != SNAPSHOT_KIND:
        raise CoreValidationError(f"snapshot kind must be {SNAPSHOT_KIND!r}")
    _reject_unknown_fields(
        document,
        {
            "schema_version", "kind", "resource", "reported_identity", "resolved_identity",
            "errors", "read_count", "outputs", "readback", "measurements", "protection",
            "protection_settings", "output_ranges",
        },
        "snapshot",
    )
    reported = document.get("reported_identity")
    resolved = document.get("resolved_identity")
    if not isinstance(reported, dict):
        raise CoreValidationError("snapshot reported_identity must be an object")
    if not isinstance(resolved, dict):
        raise CoreValidationError("snapshot resolved_identity must be an object")
    _reject_unknown_fields(reported, {"manufacturer", "model", "serial", "firmware", "parse_ok"}, "snapshot reported_identity")
    _reject_unknown_fields(resolved, {"vendor_id", "model_id", "model_name", "display_name"}, "snapshot resolved_identity")
    if reported.get("parse_ok") is not True:
        raise CoreValidationError("snapshot reported_identity.parse_ok must be true")
    for field in ("manufacturer", "model", "serial", "firmware"):
        value = reported.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CoreValidationError(
                f"snapshot reported_identity.{field} must be a non-empty string"
            )
    try:
        identity = resolve_physical_model_identity(
            reported["manufacturer"],
            reported["model"],
        )
    except IdentityResolutionError as exc:
        raise CoreValidationError(
            "snapshot reported manufacturer and model do not resolve to a canonical physical identity"
        ) from exc
    model_info = IDENTITY_INDEXES.models_by_id[identity.model_id]
    expected_resolved = {
        "vendor_id": identity.vendor_id,
        "model_id": identity.model_id,
        "model_name": identity.canonical_model,
        "display_name": model_info.display_name,
    }
    if resolved != expected_resolved:
        raise CoreValidationError(
            "snapshot reported_identity conflicts with resolved_identity"
        )
    if identity.model_id not in {"keysight-e36312a", "gw-instek-psm-2010"}:
        raise CoreValidationError(
            "snapshot model must be E36312A or PSM-2010 "
            "for restore-from-snapshot"
        )
    supported_channels = _snapshot_supported_channels(identity.model_id)
    outputs = _validate_output_records(document.get("outputs"), supported_channels)
    readback = _validate_readback_records(document.get("readback"), supported_channels)
    # These read-only producer sections are optional in older schema-2
    # snapshots, but become strict as soon as they are present.
    if "measurements" in document:
        _validate_measurement_records(document["measurements"], supported_channels)
    if "protection" in document:
        _validate_snapshot_protection(document["protection"])
    protection = _validate_protection_records(
        document.get("protection_settings"),
        supported_channels,
        psm2010=identity.model_id == "gw-instek-psm-2010",
    )
    output_ranges: dict[int, dict[str, Any]] = {}
    if identity.model_id == "gw-instek-psm-2010":
        output_ranges = _validate_output_range_records(
            document.get("output_ranges"),
            supported_channels,
        )
    elif "output_ranges" in document:
        raise CoreValidationError(
            "snapshot output_ranges is only supported for PSM-2010"
        )
    if not outputs:
        raise CoreValidationError("snapshot outputs must not be empty")
    if not readback:
        raise CoreValidationError("snapshot readback must not be empty")
    if not protection:
        raise CoreValidationError("snapshot protection_settings must not be empty")
    inventories = {
        "outputs": set(outputs),
        "readback": set(readback),
        "protection_settings": set(protection),
    }
    if identity.model_id == "gw-instek-psm-2010":
        inventories["output_ranges"] = set(output_ranges)
    all_channels = set().union(*inventories.values())
    for section, channels in inventories.items():
        missing = sorted(all_channels - channels)
        if missing:
            raise CoreValidationError(
                f"snapshot {section} does not contain channel {missing[0]}"
            )
    if identity.model_id == "gw-instek-psm-2010":
        for channel, range_record in output_ranges.items():
            setpoints = readback[channel]["setpoints"]
            if range_record["range"] not in _compatible_programming_ranges(
                float(setpoints["voltage"]),
                float(setpoints["current"]),
            ):
                raise CoreValidationError(
                    f"snapshot output range does not contain channel {channel} setpoints"
                )
    return document


def _restore_channels(request: OperationRequest, snapshot: dict[str, Any]) -> tuple[int, ...]:
    available = sorted(_records_by_channel(snapshot.get("readback")))
    if not available:
        raise CoreValidationError("snapshot readback must not be empty")
    selected = strict_channel_parameter(
        request.parameters,
        "channel",
        allow_all=True,
        required=True,
    )
    supported_channels = _snapshot_supported_channels(
        snapshot["resolved_identity"]["model_id"]
    )
    if selected == "all":
        channels = tuple(channel for channel in available if channel in supported_channels)
        _require_restore_channels(snapshot, channels)
        return channels
    assert type(selected) is int
    channel = selected
    if channel not in supported_channels:
        raise CoreValidationError(f"channel {channel} is not supported; supported: {supported_channels}")
    if channel not in available:
        raise CoreValidationError(f"snapshot does not contain channel {channel}")
    _require_restore_channels(snapshot, (channel,))
    return (channel,)


def _restore_step(action: str, scpi: str, **parameters: Any) -> dict[str, Any]:
    return {"action": action, "command": scpi, "parameters": parameters}


def _restore_scpi(command: str, channel: int, psm2010: bool) -> str:
    if psm2010:
        return command
    separator = "," if " " in command else " "
    return f"{command}{separator}(@{channel})"


def _ocp_delay_trigger_scpi(trigger: Any) -> str:
    if trigger == "setting-change":
        return "SCH"
    if trigger == "cc-transition":
        return "CCTR"
    raise CoreValidationError("ocp_delay_trigger must be one of: setting-change, cc-transition")


def _execute_restore_plan(
    power_supply: E36312APowerSupply | PSM2010PowerSupply,
    plan: dict[str, Any],
    *,
    stop_requested: StopRequested = None,
) -> None:
    pending_psm_current: dict[int, float] = {}
    for step in plan["steps"]:
        raise_if_cancelled(stop_requested)
        action = step["action"]
        parameters = step["parameters"]
        channel = parameters["channel"]
        if action == "output_off":
            power_supply.output_off(channel=channel)
        elif action == "set_output_range":
            if not isinstance(power_supply, PSM2010PowerSupply):
                raise CoreValidationError("set_output_range is only valid for PSM-2010 restore")
            power_supply.set_output_range(
                channel=channel,
                output_range=str(parameters["output_range"]),
            )
        elif action == "set_over_voltage_protection":
            power_supply.set_over_voltage_protection(channel=channel, voltage=float(parameters["voltage"]))
        elif action == "set_over_current_protection_enabled":
            power_supply.set_over_current_protection_enabled(channel=channel, enabled=parameters["enabled"])
        elif action == "set_over_current_protection_delay":
            power_supply.set_over_current_protection_delay(channel=channel, seconds=float(parameters["seconds"]))
        elif action == "set_over_current_protection_delay_trigger":
            power_supply.set_over_current_protection_delay_trigger(channel=channel, trigger=str(parameters["trigger"]))
        elif action == "set_current_limit":
            if isinstance(power_supply, PSM2010PowerSupply):
                pending_psm_current[channel] = float(parameters["current"])
            else:
                power_supply.set_current_limit(channel=channel, current=float(parameters["current"]))
        elif action == "set_voltage":
            if isinstance(power_supply, PSM2010PowerSupply):
                power_supply.set_output_pair(
                    channel=channel,
                    voltage=float(parameters["voltage"]),
                    current=pending_psm_current[channel],
                )
            else:
                power_supply.set_voltage(channel=channel, voltage=float(parameters["voltage"]))
        elif action == "output_on":
            power_supply.output_on(channel=channel)
        else:
            raise CoreValidationError(f"unsupported restore action: {action}")


def _validate_restore_setpoints(
    power_supply: E36312APowerSupply | PSM2010PowerSupply,
    plan: dict[str, Any],
) -> None:
    pending: dict[int, dict[str, float]] = {}
    for step in plan["steps"]:
        parameters = step["parameters"]
        channel = parameters.get("channel")
        if not isinstance(channel, int):
            continue
        values = pending.setdefault(channel, {})
        if step["action"] == "set_current_limit":
            values["current"] = float(parameters["current"])
        elif step["action"] == "set_voltage":
            values["voltage"] = float(parameters["voltage"])
    for channel, values in pending.items():
        validate_effective_setpoint(
            model=power_supply.capabilities.electrical_ratings.model,
            channel=channel,
            electrical_ratings=power_supply.capabilities.electrical_ratings,
            voltage=values.get("voltage"),
            current=values.get("current"),
        )


def _validate_restore_identity(idn: Any, snapshot: dict[str, Any]) -> Any:
    expected_model_id = snapshot["resolved_identity"]["model_id"]
    expected_serial = snapshot["reported_identity"]["serial"]
    try:
        connected = resolve_physical_model_identity(idn.manufacturer, idn.model)
    except IdentityResolutionError as exc:
        raise CoreValidationError(
            "connected manufacturer and model do not resolve to a canonical physical identity"
        ) from exc
    if connected.model_id != expected_model_id:
        raise CoreValidationError(
            f"connected model_id {connected.model_id!r} does not match snapshot "
            f"model_id {expected_model_id!r}"
        )
    if idn.serial != expected_serial:
        raise CoreValidationError(f"connected serial {idn.serial!r} does not match snapshot serial {expected_serial!r}")
    return connected


def _raise_on_instrument_errors(
    power_supply: E36312APowerSupply | PSM2010PowerSupply,
) -> None:
    errors, _read_count = power_supply.read_error_queue(20)
    if errors:
        raise CoreValidationError("instrument reported errors after restore-from-snapshot: " + "; ".join(errors))


def _records_by_channel(records: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(records, list):
        return {}
    by_channel: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        channel = record.get("channel")
        if type(channel) is not int:
            continue
        by_channel[channel] = record
    return by_channel


def _validated_channel_records(
    records: Any,
    section: str,
    supported_channels: tuple[int, ...],
) -> dict[int, dict[str, Any]]:
    if not isinstance(records, list):
        raise CoreValidationError(f"snapshot {section} must be a list")
    by_channel: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise CoreValidationError(f"snapshot {section} entries must be objects")
        channel = record.get("channel")
        if type(channel) is not int or channel <= 0:
            raise CoreValidationError(
                f"snapshot {section}[].channel must be a positive integer"
            )
        if channel not in supported_channels:
            raise CoreValidationError(
                f"snapshot {section}[].channel {channel} is not supported"
            )
        if channel in by_channel:
            raise CoreValidationError(f"duplicate snapshot {section} channel {channel}")
        by_channel[channel] = record
    return by_channel


def _validate_output_records(
    records: Any,
    supported_channels: tuple[int, ...],
) -> dict[int, dict[str, Any]]:
    by_channel = _validated_channel_records(records, "outputs", supported_channels)
    for record in by_channel.values():
        _reject_unknown_fields(record, {"channel", "enabled"}, "snapshot outputs[]")
        if type(record.get("enabled")) is not bool:
            raise CoreValidationError("snapshot outputs[].enabled must be a boolean")
    return by_channel


def _validate_readback_records(
    records: Any,
    supported_channels: tuple[int, ...],
) -> dict[int, dict[str, Any]]:
    by_channel = _validated_channel_records(records, "readback", supported_channels)
    for record in by_channel.values():
        _reject_unknown_fields(record, {"channel", "setpoints"}, "snapshot readback[]")
        setpoints = record.get("setpoints")
        if not isinstance(setpoints, dict):
            raise CoreValidationError("snapshot readback[].setpoints must be an object")
        _reject_unknown_fields(setpoints, {"voltage", "current"}, "snapshot readback[].setpoints")
        for field in ("voltage", "current"):
            _require_finite_number(
                setpoints.get(field),
                f"snapshot readback[].setpoints.{field}",
            )
    return by_channel


def _snapshot_supported_channels(model_id: str) -> tuple[int, ...]:
    if model_id == "keysight-e36312a":
        return E36312APowerSupply.capabilities.channels
    if model_id == "gw-instek-psm-2010":
        return PSM2010PowerSupply.capabilities.channels
    raise CoreValidationError(f"snapshot model_id {model_id!r} is not supported")


def _validate_measurement_records(
    records: Any,
    supported_channels: tuple[int, ...],
) -> dict[int, dict[str, Any]]:
    by_channel = _validated_channel_records(records, "measurements", supported_channels)
    for record in by_channel.values():
        _reject_unknown_fields(record, {"channel", "measurements"}, "snapshot measurements[]")
        readings = record.get("measurements")
        if not isinstance(readings, dict):
            raise CoreValidationError("snapshot measurements[].measurements must be an object")
        _reject_unknown_fields(
            readings, {"voltage", "current"}, "snapshot measurements[].measurements"
        )
        for field in ("voltage", "current"):
            _require_finite_number(
                readings.get(field), f"snapshot measurements[].measurements.{field}"
            )
    return by_channel


def _validate_snapshot_protection(value: Any) -> None:
    if not isinstance(value, dict):
        raise CoreValidationError("snapshot protection must be an object")
    _reject_unknown_fields(
        value,
        {"over_voltage_tripped", "over_current_tripped"},
        "snapshot protection",
    )
    for field in ("over_voltage_tripped", "over_current_tripped"):
        if type(value.get(field)) is not bool:
            raise CoreValidationError(f"snapshot protection.{field} must be a boolean")


def _validate_protection_records(
    records: Any,
    supported_channels: tuple[int, ...],
    *,
    psm2010: bool,
) -> dict[int, dict[str, Any]]:
    by_channel = _validated_channel_records(
        records,
        "protection_settings",
        supported_channels,
    )
    for record in by_channel.values():
        _reject_unknown_fields(record, {"channel", "protection"}, "snapshot protection_settings[]")
        protection = record.get("protection")
        if not isinstance(protection, dict):
            raise CoreValidationError(
                "snapshot protection_settings[].protection must be an object"
            )
        _reject_unknown_fields(protection, {"ovp_voltage", "ocp_enabled", "ocp_delay", "ocp_delay_trigger"}, "snapshot protection_settings[].protection")
        ovp_voltage = protection.get("ovp_voltage")
        if ovp_voltage is not None:
            _require_finite_number(
                ovp_voltage,
                "snapshot protection_settings[].protection.ovp_voltage",
            )
            if psm2010:
                try:
                    _validate_psm2010_ovp_level(float(ovp_voltage))
                except SafetyValidationError as exc:
                    raise CoreValidationError(str(exc)) from exc
        ocp_enabled = protection.get("ocp_enabled")
        if ocp_enabled is not None and type(ocp_enabled) is not bool:
            raise CoreValidationError("snapshot ocp_enabled must be a boolean or null")
        ocp_delay = protection.get("ocp_delay")
        if psm2010 and ocp_delay is not None:
            raise CoreValidationError("PSM-2010 snapshot ocp_delay must be null")
        if ocp_delay is not None:
            _require_finite_number(
                ocp_delay,
                "snapshot protection_settings[].protection.ocp_delay",
            )
            if float(ocp_delay) < 0:
                raise CoreValidationError("snapshot ocp_delay must be non-negative")
        ocp_delay_trigger = protection.get("ocp_delay_trigger")
        if ocp_delay_trigger is not None and ocp_delay_trigger not in {
            "setting-change",
            "cc-transition",
        }:
            raise CoreValidationError(
                "snapshot ocp_delay_trigger must be one of: setting-change, cc-transition, null"
            )
        if psm2010 and ocp_delay_trigger is not None:
            raise CoreValidationError(
                "PSM-2010 snapshot ocp_delay_trigger must be null"
            )
    return by_channel


def _validate_output_range_records(
    records: Any,
    supported_channels: tuple[int, ...],
) -> dict[int, dict[str, Any]]:
    by_channel = _validated_channel_records(
        records,
        "output_ranges",
        supported_channels,
    )
    for record in by_channel.values():
        _reject_unknown_fields(
            record,
            {"channel", "range"},
            "snapshot output_ranges[]",
        )
        if record.get("range") not in {"LOW", "HIGH"}:
            raise CoreValidationError(
                "snapshot output_ranges[].range must be LOW or HIGH"
            )
    if not by_channel:
        raise CoreValidationError("snapshot output_ranges must not be empty")
    return by_channel


def _require_finite_number(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CoreValidationError(f"{field} must be a finite number")
    if not math.isfinite(float(value)):
        raise CoreValidationError(f"{field} must be a finite number")


def _reject_unknown_fields(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CoreValidationError(f"{label} has unsupported field(s): {', '.join(unknown)}")


def _require_restore_channels(snapshot: dict[str, Any], channels: tuple[int, ...]) -> None:
    sections = {
        "outputs": _records_by_channel(snapshot.get("outputs")),
        "readback": _records_by_channel(snapshot.get("readback")),
        "protection_settings": _records_by_channel(snapshot.get("protection_settings")),
    }
    if snapshot["resolved_identity"]["model_id"] == "gw-instek-psm-2010":
        sections["output_ranges"] = _records_by_channel(snapshot.get("output_ranges"))
    for channel in channels:
        for section, records in sections.items():
            if channel not in records:
                raise CoreValidationError(
                    f"snapshot {section} does not contain channel {channel}"
                )


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)
