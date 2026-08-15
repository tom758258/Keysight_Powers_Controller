"""Shared CLI runtime helpers, resource I/O, error emission, and safety adapters."""

from __future__ import annotations

__all__ = [
    "_CHANNEL_NOT_PROVIDED",
    "_E36312AChannelError",
    "_InvalidCoreResult",
    "_MeasureChannelUnsupported",
    "_ReadOnlyChannelError",
    "_ReadOnlyModelError",
    "_ScpiLoggingSession",
    "_build_hardware_report",
    "_channels_from_selection",
    "_collect_protection_status",
    "_collect_readback",
    "_collect_snapshot",
    "_collect_status",
    "_command_from_argv",
    "_compare_channel_measurements",
    "_compare_exact",
    "_compare_snapshot_data",
    "_confirmation_required_message",
    "_connection_scpi_logger_for_args",
    "_core_lister_for_args",
    "_core_opener_for_args",
    "_core_validation_code",
    "_diff_channel_records",
    "_diff_snapshots",
    "_emit_cli_error",
    "_emit_invalid_core_result",
    "_emit_safe_io_error",
    "_emit_text_lines",
    "_enforce_live_cli_scope",
    "_exit_code",
    "_format_channel_set",
    "_format_text_value",
    "_is_no_error_response",
    "_json_save_path_from_argv",
    "_list_resources",
    "_load_json_document",
    "_load_snapshot_document",
    "_log_scpi",
    "_max_reads_from_argv",
    "_measure_voltage_current",
    "_measure_voltage_current_with_driver",
    "_nested_value",
    "_numbers_within_tolerance",
    "_open_jsonl_log",
    "_open_resource",
    "_output_affecting_allowed",
    "_package_version",
    "_parse_measurement",
    "_patchable_create_power_supply",
    "_patchable_list_resources",
    "_patchable_open_resource",
    "_patchable_run_core_command",
    "_patchable_select_driver",
    "_protection_payload",
    "_protection_settings_payload",
    "_query_idn",
    "_raise_on_instrument_errors",
    "_read_error_queue",
    "_read_error_queue_from_driver",
    "_read_only_channels_from_selection",
    "_records_by_channel",
    "_resolve_optional_resource_alias",
    "_resource_manager_for_args",
    "_resource_payload",
    "_safe_io_resource_payload",
    "_safety_explanation_for_args",
    "_safety_field_sources",
    "_safety_limits_for_args",
    "_safety_limits_for_channel",
    "_safety_limits_payload",
    "_serial_open_kwargs",
    "_snapshot_compare_tolerances",
    "_unsupported_measure_channel_message",
    "_validate_output_request",
    "_validate_read_only_channel",
    "_write_hardware_report_files",
    "_write_json_file",
    "_write_json_file_atomic",
]

import argparse
import csv
import importlib.metadata
import json
import math
import os
import platform
import signal
import sys
import tempfile
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import powers_tool_core.capabilities as capabilities
import powers_tool_core.discovery as discovery_core
import powers_tool_core.instrument_io as instrument_io_core
import powers_tool_core.operations as operations
import powers_tool_core.protection as protection_core
import powers_tool_core.ramp_list as ramp_list_core
import powers_tool_core.readonly as readonly_core
import powers_tool_core.restore as restore_core
import powers_tool_core.sequence as sequence
import powers_tool_core.snapshot as snapshot_core
import powers_tool_core.trigger as trigger_core
import powers_tool_core.validation as validation
from powers_tool_cli.cli_io import (
    JsonSaveError,
    SCHEMA_VERSION,
    emit_json_error,
    emit_json_success,
    set_json_save_path,
    set_json_start_time,
)
from powers_tool_cli import cli_rendering
from powers_tool_cli.lifecycle_client import (
    run_send_command as _run_send_command,
    run_wait_ready_client as _run_wait_ready_client,
    run_worker_status_client as _run_worker_status_client,
    run_worker_stop_client as _run_worker_stop_client,
)
from powers_tool_cli.runtime_mapping import (
    execution_for_args as _execution_for_args,
    mode_for_args as _mode_for_args,
    runtime_identity_for_args as _runtime_identity_for_args,
    serial_options_for_args as _serial_options_for_args,
    support_policy_mode_for_args as _support_policy_mode_for_args,
    validation_execution_from_argv as _validation_execution_from_argv,
    with_serial_request_fields as _with_serial_request_fields,
)
from powers_tool_cli.request_primitives import (
    channel_from_argv as _channel_from_argv,
    completion_pins_from_argv as _completion_pins_from_argv,
    completion_request_fields_from_argv as _completion_request_fields_from_argv,
    drop_none_setpoints as _drop_none_setpoints,
    duration_from_argv as _duration_from_argv,
    float_list_from_argv as _float_list_from_argv,
    int_from_argv as _int_from_argv,
    int_option_from_argv as _int_option_from_argv,
    json_safe_number as _json_safe_number,
    max_errors_from_argv as _max_errors_from_argv,
    number_from_argv as _number_from_argv,
    option_value as _option_value,
    pin_from_argv as _pin_from_argv,
    pins_from_argv as _pins_from_argv,
    status_channel_from_argv as _status_channel_from_argv,
    timeout_from_argv as _timeout_from_argv,
    trigger_pins_for_args as _trigger_pins_for_args,
    with_serial_request_fields_from_argv as _with_serial_request_fields_from_argv,
    write_verification_request_fields as _write_verification_request_fields,
    write_verification_request_fields_from_argv as _write_verification_request_fields_from_argv,
)
from powers_tool_core.connection import DEFAULT_TIMEOUT_MS, SerialOptions, list_resources, normalize_serial_termination, open_resource
from powers_tool_core.command_runner import (
    run_core_command,
    validate_request_admission,
    workflow_execution_summary,
)
from powers_tool_core.command_contract import command_parameter_names
from powers_tool_core.core import (
    CommandCancelled,
    ConfirmationRequiredError,
    CoreExecutionError,
    CoreIoError,
    CoreValidationError,
    CoreVerificationError,
    OperationRequest,
    RuntimeOptions,
    SequenceRequest,
    StopCleanupError,
    UnsupportedChannelError,
    UnsupportedModelError,
)
from powers_tool_core.drivers.e36312a import E36312APowerSupply
from powers_tool_core.drivers.e3646a import E3646APowerSupply
from powers_tool_core.drivers.edu36311a import EDU36311APowerSupply
from powers_tool_core.drivers.generic_scpi import GenericScpiPowerSupply
from powers_tool_core.drivers.psm2010 import PSM2010PowerSupply
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import create_power_supply, select_driver
from powers_tool_core.identity import (
    IDENTITY_INDEXES,
    IdentityResolutionError,
    canonical_physical_model_id,
    resolve_physical_model_identity,
)
from powers_tool_core.live_support import enforce_live_support_for_idn
from powers_tool_core.support_policy import (
    LiveSupportPolicyError,
    SUPPORT_POLICY_MODE_PRODUCT,
    SUPPORT_POLICY_MODE_VALIDATION,
)
from powers_tool_core.telemetry import TELEMETRY_ROW_FIELDS
from powers_tool_core.model_resolution import validate_live_expected_model
from powers_tool_core.models import parse_idn, resource_interface
from powers_tool_core.safety import (
    SafetyConfigError,
    SafetyLimits,
    SafetyValidationError,
    load_safety_config_document,
    resolve_safety_config,
    validate_channel,
    validate_setpoint,
)
from powers_tool_core.testing.simulator import SimulatedResourceManager
from powers_tool_core.transport import dry_run_plan

IDN_QUERY = "*IDN?"
CLEAR_STATUS_COMMAND = "*CLS"
ERROR_QUERY = "SYST:ERR?"
MEASURE_VOLTAGE_QUERY = "MEAS:VOLT?"
MEASURE_CURRENT_QUERY = "MEAS:CURR?"
PROGRAMMED_VOLTAGE_QUERY = "VOLT?"
PROGRAMMED_CURRENT_QUERY = "CURR?"
OVP_TRIP_QUERY = "VOLT:PROT:TRIP?"
OCP_TRIP_QUERY = "CURR:PROT:TRIP?"
LOG_CSV_FIELDS = TELEMETRY_ROW_FIELDS
OUTPUT_WRITE_POWER_SUPPLY_TYPES = (E36312APowerSupply, EDU36311APowerSupply)


def _cli_binding(name: str, default: Any) -> Any:
    import sys

    cli_module = sys.modules.get("powers_tool_cli.cli")
    if cli_module is not None and hasattr(cli_module, name):
        return getattr(cli_module, name)
    return default


def _patchable_open_resource(*args: Any, **kwargs: Any) -> Any:
    import sys

    cli_module = sys.modules.get("powers_tool_cli.cli")
    if cli_module is not None:
        patched_private = getattr(cli_module, "_open_resource", None)
        if patched_private is not None and patched_private is not _open_resource:
            return patched_private(*args, **kwargs)
        return cli_module.open_resource(*args, **kwargs)
    return open_resource(*args, **kwargs)


def _patchable_list_resources(*args: Any, **kwargs: Any) -> Any:
    return _cli_binding("list_resources", list_resources)(*args, **kwargs)


def _patchable_create_power_supply(*args: Any, **kwargs: Any) -> Any:
    return _cli_binding("create_power_supply", create_power_supply)(*args, **kwargs)


def _patchable_select_driver(*args: Any, **kwargs: Any) -> Any:
    return _cli_binding("select_driver", select_driver)(*args, **kwargs)


def _patchable_run_core_command(*args: Any, **kwargs: Any) -> Any:
    return _cli_binding("run_core_command", run_core_command)(*args, **kwargs)


class _MeasureChannelUnsupported(ValueError):
    """Raised when a measure channel is outside conservative driver capability."""

class _InvalidCoreResult(ValueError):
    """Raised when a successful Core result violates the CLI adapter contract."""

class _ScpiLoggingSession:
    """Session proxy that logs SCPI traffic while preserving driver behavior."""

    def __init__(self, resource: str, session: Any) -> None:
        self._resource = resource
        self._session = session

    def write(self, command: str) -> Any:
        _log_scpi(self._resource, ">>", command)
        return self._session.write(command)

    def query(self, command: str) -> str:
        _log_scpi(self._resource, ">>", command)
        response = self._session.query(command)
        _log_scpi(self._resource, "<<", response)
        return response

    def close(self) -> None:
        self._session.close()

def _write_json_file(path: str, data: dict[str, Any]) -> None:
    output_path = Path(path)
    if output_path.parent != Path("."):
        output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")

def _write_json_file_atomic(path: str, data: dict[str, Any]) -> None:
    output_path = Path(path)
    parent = output_path.parent
    if parent != Path("."):
        parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(data, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, output_path)
    except OSError:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise

def _query_idn(
    resource: str,
    *,
    resource_manager: SimulatedResourceManager | None,
    backend: str | None,
    timeout_ms: int,
    log_scpi: bool,
) -> str | None:
    try:
        with _open_resource(
            resource,
            resource_manager,
            backend=backend,
            timeout_ms=timeout_ms,
        ) as instrument:
            if log_scpi:
                _log_scpi(resource, ">>", IDN_QUERY)
            response = instrument.identify()
            if log_scpi:
                _log_scpi(resource, "<<", response)
            return response
    except (VisaConnectionError, ValueError):
        return None

def _read_error_queue(
    resource: str,
    *,
    resource_manager: SimulatedResourceManager | None,
    backend: str | None,
    timeout_ms: int,
    log_scpi: bool,
    max_reads: int,
) -> tuple[list[str], int]:
    errors: list[str] = []
    read_count = 0
    with _open_resource(
        resource,
        resource_manager,
        backend=backend,
        timeout_ms=timeout_ms,
    ) as instrument:
        for _ in range(max_reads):
            if log_scpi:
                _log_scpi(resource, ">>", ERROR_QUERY)
            response = instrument.query(ERROR_QUERY)
            read_count += 1
            if log_scpi:
                _log_scpi(resource, "<<", response)
            if _is_no_error_response(response):
                break
            errors.append(response)
    return errors, read_count

def _open_jsonl_log(args: argparse.Namespace):
    if args.jsonl is None:
        return None
    path = Path(args.jsonl)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.append else "w"
    return path.open(mode, encoding="utf-8")

def _measure_voltage_current(
    resource: str,
    *,
    resource_manager: SimulatedResourceManager | None,
    backend: str | None,
    timeout_ms: int,
    log_scpi: bool,
    channel: int,
    simulate: bool,
) -> dict[str, float]:
    with _open_resource(
        resource,
        resource_manager,
        backend=backend,
        timeout_ms=timeout_ms,
    ) as instrument:
        if simulate:
            return _measure_voltage_current_with_driver(
                resource,
                instrument,
                channel=channel,
                log_scpi=log_scpi,
                mode="simulate",
            )

        if channel not in GenericScpiPowerSupply.capabilities.real_measure_channels:
            return _measure_voltage_current_with_driver(
                resource,
                instrument,
                channel=channel,
                log_scpi=log_scpi,
                mode="real",
            )

        if log_scpi:
            _log_scpi(resource, ">>", MEASURE_VOLTAGE_QUERY)
        voltage_response = instrument.query(MEASURE_VOLTAGE_QUERY)
        if log_scpi:
            _log_scpi(resource, "<<", voltage_response)
            _log_scpi(resource, ">>", MEASURE_CURRENT_QUERY)
        current_response = instrument.query(MEASURE_CURRENT_QUERY)
        if log_scpi:
            _log_scpi(resource, "<<", current_response)

    return {
        "voltage": _parse_measurement(voltage_response, "voltage"),
        "current": _parse_measurement(current_response, "current"),
    }

def _measure_voltage_current_with_driver(
    resource: str,
    instrument: Any,
    *,
    channel: int,
    log_scpi: bool,
    mode: str,
) -> dict[str, float]:
    session = _ScpiLoggingSession(resource, instrument) if log_scpi else instrument
    idn = session.query(IDN_QUERY)
    power_supply = create_power_supply(session, idn)
    capabilities = power_supply.capabilities
    allowed_channels = (
        capabilities.simulated_measure_channels
        if mode == "simulate"
        else capabilities.real_measure_channels
    )
    if channel not in allowed_channels:
        raise _MeasureChannelUnsupported(
            _unsupported_measure_channel_message(
                channel=channel,
                mode=mode,
                driver_name=type(power_supply).__name__,
                allowed_channels=allowed_channels,
            )
        )

    return {
        "voltage": power_supply.measure_voltage(channel=channel),
        "current": power_supply.measure_current(channel=channel),
    }

def _validate_read_only_channel(
    power_supply: GenericScpiPowerSupply,
    channel: int,
    *,
    command_label: str,
) -> None:
    if not isinstance(
        power_supply,
        (E36312APowerSupply, EDU36311APowerSupply, PSM2010PowerSupply),
    ):
        raise _ReadOnlyModelError(
            f"{command_label} is only supported for E36312A, EDU36311A, or PSM-2010; "
            f"found {type(power_supply).__name__} from *IDN? response"
        )
    if channel not in power_supply.capabilities.channels:
        raise _ReadOnlyChannelError(
            f"channel {channel} is not supported for {command_label}; "
            f"supported: {power_supply.capabilities.channels}"
        )

def _resolve_optional_resource_alias(args: argparse.Namespace) -> None:
    if getattr(args, "resource_alias", None) is None:
        return
    _safety_limits_for_args(args)

def _read_error_queue_from_driver(
    power_supply: GenericScpiPowerSupply,
    max_reads: int,
) -> tuple[list[str], int]:
    if max_reads < 1:
        raise ValueError("max_errors must be at least 1")

    return power_supply.read_error_queue(max_reads)

def _raise_on_instrument_errors(
    power_supply: GenericScpiPowerSupply,
    operation: str,
    *,
    max_reads: int = 20,
) -> None:
    errors, _ = _read_error_queue_from_driver(power_supply, max_reads)
    if errors:
        raise ValueError(
            f"{operation} left instrument error queue entries: "
            + "; ".join(errors)
        )

def _collect_readback(
    args: argparse.Namespace,
    power_supply: GenericScpiPowerSupply,
    idn_raw: str,
    channels: tuple[int, ...],
) -> dict[str, Any]:
    return {
        "resource": args.resource,
        "channels": [
            {
                "channel": channel,
                "setpoints": {
                    "voltage": power_supply.programmed_voltage(channel=channel),
                    "current": power_supply.programmed_current(channel=channel),
                },
            }
            for channel in channels
        ],
    }

def _collect_status(
    args: argparse.Namespace,
    power_supply: GenericScpiPowerSupply,
    idn_raw: str,
    channels: tuple[int, ...],
) -> dict[str, Any]:
    errors, read_count = _read_error_queue_from_driver(power_supply, args.max_errors)
    return {
        "resource": args.resource,
        "errors": errors,
        "read_count": read_count,
        "outputs": [
            {"channel": channel, "enabled": power_supply.output_state(channel=channel)}
            for channel in channels
        ],
    }

def _collect_protection_status(
    args: argparse.Namespace,
    power_supply: GenericScpiPowerSupply,
    idn_raw: str,
    channels: tuple[int, ...],
) -> dict[str, Any]:
    protection = _protection_payload(power_supply)
    tripped = protection["over_voltage_tripped"] or protection["over_current_tripped"]
    protection_by_channel = [
        {
            "channel": channel,
            "protection": {
                "over_voltage_tripped": protection["over_voltage_tripped"],
                "over_current_tripped": protection["over_current_tripped"],
            },
        }
        for channel in channels
    ]
    return {
        "resource": args.resource,
        "protection": protection,
        "protection_by_channel": protection_by_channel,
        "outputs": [
            {
                "channel": channel,
                "enabled": (enabled := power_supply.output_state(channel=channel)),
                "disabled_with_protection": (not enabled) and tripped,
            }
            for channel in channels
        ],
    }

def _collect_snapshot(
    args: argparse.Namespace,
    power_supply: E36312APowerSupply,
    idn_raw: str,
    channels: tuple[int, ...],
) -> dict[str, Any]:
    channels = power_supply.capabilities.channels
    errors, read_count = _read_error_queue_from_driver(power_supply, args.max_errors)
    return {
        "resource": args.resource,
        "idn": parse_idn(idn_raw).to_dict(),
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
        "protection": _protection_payload(power_supply),
        "protection_settings": _protection_settings_payload(
            power_supply,
            channels,
            tolerate_errors=True,
        ),
    }

def _snapshot_compare_tolerances(args: argparse.Namespace) -> dict[str, float]:
    return {
        "setpoint_voltage": args.setpoint_voltage_tolerance,
        "setpoint_current": args.setpoint_current_tolerance,
        "measured_voltage": args.measured_voltage_tolerance,
        "measured_current": args.measured_current_tolerance,
    }

def _compare_snapshot_data(
    current: dict[str, Any],
    baseline_path: str,
    tolerances: dict[str, float],
) -> dict[str, Any]:
    baseline_document = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    baseline = baseline_document.get("data", baseline_document) if isinstance(baseline_document, dict) else baseline_document
    if not isinstance(baseline, dict):
        raise ValueError("baseline must be a JSON object or an envelope containing object data")
    restore_core.validate_snapshot_document(baseline)
    differences: list[dict[str, Any]] = []
    _compare_exact(
        differences,
        "reported_identity",
        baseline.get("reported_identity"),
        current.get("reported_identity"),
    )
    _compare_exact(
        differences,
        "resolved_identity",
        baseline.get("resolved_identity"),
        current.get("resolved_identity"),
    )
    _compare_exact(differences, "errors", baseline.get("errors"), current.get("errors"))
    _compare_exact(differences, "outputs", baseline.get("outputs"), current.get("outputs"))
    _compare_exact(
        differences,
        "output_ranges",
        baseline.get("output_ranges"),
        current.get("output_ranges"),
    )
    _compare_exact(differences, "protection", baseline.get("protection"), current.get("protection"))
    _compare_channel_measurements(
        differences,
        "readback",
        baseline.get("readback", []),
        current.get("readback", []),
        {"voltage": tolerances["setpoint_voltage"], "current": tolerances["setpoint_current"]},
        value_key="setpoints",
    )
    _compare_channel_measurements(
        differences,
        "measurements",
        baseline.get("measurements", []),
        current.get("measurements", []),
        {"voltage": tolerances["measured_voltage"], "current": tolerances["measured_current"]},
        value_key="measurements",
    )
    return {
        "passed": not differences,
        "baseline_path": baseline_path,
        "differences": differences,
        "tolerances": tolerances,
    }

def _compare_exact(differences: list[dict[str, Any]], path: str, expected: Any, actual: Any) -> None:
    if expected != actual:
        differences.append({"path": path, "expected": expected, "actual": actual})

def _compare_channel_measurements(
    differences: list[dict[str, Any]],
    path: str,
    expected_items: Any,
    actual_items: Any,
    tolerances: dict[str, float],
    *,
    value_key: str,
) -> None:
    if not isinstance(expected_items, list) or not isinstance(actual_items, list):
        _compare_exact(differences, path, expected_items, actual_items)
        return
    expected_by_channel = {item.get("channel"): item for item in expected_items if isinstance(item, dict)}
    actual_by_channel = {item.get("channel"): item for item in actual_items if isinstance(item, dict)}
    if expected_by_channel.keys() != actual_by_channel.keys():
        differences.append(
            {
                "path": path,
                "expected_channels": sorted(expected_by_channel.keys()),
                "actual_channels": sorted(actual_by_channel.keys()),
            }
        )
        return
    for channel, expected_item in expected_by_channel.items():
        actual_item = actual_by_channel[channel]
        expected_values = expected_item.get(value_key, {})
        actual_values = actual_item.get(value_key, {})
        for name, tolerance in tolerances.items():
            expected_value = expected_values.get(name)
            actual_value = actual_values.get(name)
            if not _numbers_within_tolerance(expected_value, actual_value, tolerance):
                differences.append(
                    {
                        "path": f"{path}[channel={channel}].{value_key}.{name}",
                        "channel": channel,
                        "expected": expected_value,
                        "actual": actual_value,
                        "tolerance": tolerance,
                    }
                )

def _numbers_within_tolerance(expected: Any, actual: Any, tolerance: float) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        return expected == actual

def _protection_payload(power_supply: GenericScpiPowerSupply) -> dict[str, bool]:
    return {
        "over_voltage_tripped": power_supply.over_voltage_protection_tripped(),
        "over_current_tripped": power_supply.over_current_protection_tripped(),
    }

def _protection_settings_payload(
    power_supply: GenericScpiPowerSupply,
    channels: tuple[int, ...],
    *,
    tolerate_errors: bool = False,
) -> list[dict[str, Any]]:
    settings: list[dict[str, Any]] = []
    for channel in channels:
        try:
            ovp_voltage: float | None = power_supply.over_voltage_protection_level(channel=channel)
        except (VisaConnectionError, ValueError):
            if not tolerate_errors:
                raise
            ovp_voltage = None
        try:
            ocp_enabled: bool | None = power_supply.over_current_protection_enabled(channel=channel)
        except (VisaConnectionError, ValueError):
            if not tolerate_errors:
                raise
            ocp_enabled = None
        try:
            ocp_delay: float | None = power_supply.over_current_protection_delay(channel=channel)
        except (VisaConnectionError, ValueError):
            if not tolerate_errors:
                raise
            ocp_delay = None
        try:
            ocp_delay_trigger: str | None = power_supply.over_current_protection_delay_trigger(channel=channel)
        except (VisaConnectionError, ValueError):
            if not tolerate_errors:
                raise
            ocp_delay_trigger = None
        settings.append(
            {
                "channel": channel,
                "protection": {
                    "ovp_voltage": ovp_voltage,
                    "ocp_enabled": ocp_enabled,
                    "ocp_delay": ocp_delay,
                    "ocp_delay_trigger": ocp_delay_trigger,
                },
            }
        )
    return settings

def _load_snapshot_document(path: str) -> dict[str, Any]:
    document = _load_json_document(path)
    data = document.get("data") if isinstance(document.get("data"), dict) else document
    if not isinstance(data, dict):
        raise ValueError(f"snapshot JSON must contain an object: {path}")
    try:
        return restore_core.validate_snapshot_document(data)
    except CoreValidationError as exc:
        raise ValueError(str(exc)) from exc

def _load_json_document(path: str) -> dict[str, Any]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"could not read JSON file {path}: {exc}") from exc
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return parsed

def _diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    _diff_channel_records(
        differences,
        category="output",
        field_path=("enabled",),
        before_records=before.get("outputs"),
        after_records=after.get("outputs"),
    )
    _diff_channel_records(
        differences,
        category="setpoint",
        field_path=("setpoints", "voltage"),
        before_records=before.get("readback"),
        after_records=after.get("readback"),
    )
    _diff_channel_records(
        differences,
        category="setpoint",
        field_path=("setpoints", "current"),
        before_records=before.get("readback"),
        after_records=after.get("readback"),
    )
    _diff_channel_records(
        differences,
        category="measurement",
        field_path=("measurements", "voltage"),
        before_records=before.get("measurements"),
        after_records=after.get("measurements"),
    )
    _diff_channel_records(
        differences,
        category="measurement",
        field_path=("measurements", "current"),
        before_records=before.get("measurements"),
        after_records=after.get("measurements"),
    )
    _diff_channel_records(
        differences,
        category="protection_setting",
        field_path=("protection", "ovp_voltage"),
        before_records=before.get("protection_settings"),
        after_records=after.get("protection_settings"),
    )
    _diff_channel_records(
        differences,
        category="protection_setting",
        field_path=("protection", "ocp_enabled"),
        before_records=before.get("protection_settings"),
        after_records=after.get("protection_settings"),
    )
    _diff_channel_records(
        differences,
        category="protection_setting",
        field_path=("protection", "ocp_delay"),
        before_records=before.get("protection_settings"),
        after_records=after.get("protection_settings"),
    )
    _diff_channel_records(
        differences,
        category="protection_setting",
        field_path=("protection", "ocp_delay_trigger"),
        before_records=before.get("protection_settings"),
        after_records=after.get("protection_settings"),
    )
    if before.get("errors", []) != after.get("errors", []):
        differences.append(
            {
                "category": "error_queue",
                "field": "errors",
                "before": before.get("errors", []),
                "after": after.get("errors", []),
            }
        )
    if before.get("protection") != after.get("protection"):
        differences.append(
            {
                "category": "protection_trip",
                "field": "protection",
                "before": before.get("protection"),
                "after": after.get("protection"),
            }
        )
    return differences

def _diff_channel_records(
    differences: list[dict[str, Any]],
    *,
    category: str,
    field_path: tuple[str, ...],
    before_records: Any,
    after_records: Any,
) -> None:
    before_by_channel = _records_by_channel(before_records)
    after_by_channel = _records_by_channel(after_records)
    for channel in sorted(set(before_by_channel) | set(after_by_channel)):
        before_value = _nested_value(before_by_channel.get(channel), field_path)
        after_value = _nested_value(after_by_channel.get(channel), field_path)
        if before_value != after_value:
            differences.append(
                {
                    "category": category,
                    "channel": channel,
                    "field": ".".join(field_path),
                    "before": before_value,
                    "after": after_value,
                }
            )

def _records_by_channel(records: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(records, list):
        return {}
    by_channel: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        channel = record.get("channel")
        if isinstance(channel, int):
            by_channel[channel] = record
    return by_channel

def _nested_value(record: dict[str, Any] | None, path: tuple[str, ...]) -> Any:
    current: Any = record
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current

def _build_hardware_report(args: argparse.Namespace) -> dict[str, Any]:
    input_dir = Path(args.input_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        raise ValueError(f"input-dir is not a directory: {args.input_dir}")
    artifacts = []
    for path in sorted(input_dir.glob("*.json")):
        try:
            document = _load_json_document(str(path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            artifacts.append({"path": str(path), "parse_error": str(exc)})
            continue
        artifacts.append(
            {
                "path": str(path),
                "command": _nested_value(document, ("command", "name")),
                "ok": document.get("ok"),
                "status": document.get("status"),
                "error_code": _nested_value(document, ("error", "code")),
                "hardware_touched": _nested_value(document, ("execution", "hardware_touched")),
            }
        )
    failures = [
        artifact
        for artifact in artifacts
        if artifact.get("parse_error") or artifact.get("ok") is False
    ]
    diff: dict[str, Any] | None = None
    if args.before_json and args.after_json:
        before = _load_snapshot_document(args.before_json)
        after = _load_snapshot_document(args.after_json)
        differences = _diff_snapshots(before, after)
        diff = {
            "before": args.before_json,
            "after": args.after_json,
            "changed": bool(differences),
            "change_count": len(differences),
            "differences": differences,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "hardware_report",
        "target": args.target,
        "connection": args.connection,
        "resource": args.resource,
        "input_dir": args.input_dir,
        "result": "failed" if failures else "passed",
        "artifact_count": len(artifacts),
        "failure_count": len(failures),
        "artifacts": artifacts,
        "failures": failures,
        "snapshot_diff": diff,
    }

def _write_hardware_report_files(report: dict[str, Any], report_json: str, summary_md: str) -> None:
    report_path = Path(report_json)
    summary_path = Path(summary_md)
    if report_path.parent != Path("."):
        report_path.parent.mkdir(parents=True, exist_ok=True)
    if summary_path.parent != Path("."):
        summary_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        f"# {report['target']} Hardware Report",
        "",
        f"Result: {str(report['result']).upper()}",
        "",
        f"Connection: `{report['connection']}`",
        f"Resource: `{report['resource']}`",
        f"Artifacts: {report['artifact_count']}",
        f"Failures: {report['failure_count']}",
    ]
    diff = report.get("snapshot_diff")
    if isinstance(diff, dict):
        lines.extend(
            [
                "",
                "## Snapshot Diff",
                f"Changed: {str(diff['changed']).lower()}",
                f"Changes: {diff['change_count']}",
            ]
        )
    if report["failures"]:
        lines.append("")
        lines.append("## Failures")
        for failure in report["failures"]:
            lines.append(f"- `{failure['path']}` {failure.get('error_code') or failure.get('parse_error')}")
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def _confirmation_required_message(command: str) -> str:
    return validation.confirmation_required_message(command)

def _channels_from_selection(
    selected_channel: int | str,
    supported_channels: tuple[int, ...],
) -> tuple[int, ...]:
    try:
        return validation.expand_channel_selection(selected_channel, supported_channels)
    except validation.ChannelSelectionError as exc:
        raise _E36312AChannelError(
            str(exc)
        ) from exc

def _read_only_channels_from_selection(
    selected_channel: int | str,
    supported_channels: tuple[int, ...],
) -> tuple[int, ...]:
    try:
        return validation.expand_channel_selection(selected_channel, supported_channels)
    except validation.ChannelSelectionError as exc:
        raise _ReadOnlyChannelError(
            str(exc)
        ) from exc

def _resource_payload(
    name: str,
    *,
    simulated: bool,
    reachable: bool | None,
    idn_raw: str | None,
) -> dict[str, Any]:
    idn = parse_idn(idn_raw) if idn_raw is not None else None
    identity = None
    if idn is not None:
        try:
            identity = resolve_physical_model_identity(idn.manufacturer, idn.model)
        except IdentityResolutionError:
            identity = None
    return {
        "name": name,
        "interface": resource_interface(name),
        "simulated": simulated,
        "reachable": reachable,
        "idn": idn.to_dict() if idn is not None else None,
        "vendor_id": identity.vendor_id if identity is not None else None,
        "model_id": identity.model_id if identity is not None else None,
    }

def _safe_io_resource_payload(args: argparse.Namespace) -> dict[str, Any]:
    return _resource_payload(
        args.resource,
        simulated=args.simulate,
        reachable=True,
        idn_raw=None,
    )

def _resource_manager_for_args(args: argparse.Namespace) -> SimulatedResourceManager | None:
    if args.simulate:
        return SimulatedResourceManager()
    return None

def _package_version() -> str:
    try:
        return importlib.metadata.version("powers-tool")
    except importlib.metadata.PackageNotFoundError:
        return "0+unknown"

def _safety_limits_payload(limits: SafetyLimits) -> dict[str, Any]:
    return {
        "max_voltage": limits.max_voltage,
        "max_current": limits.max_current,
        "confirm_above_voltage": limits.confirm_above_voltage,
        "confirm_above_current": limits.confirm_above_current,
        "allowed_channels": (
            list(limits.allowed_channels)
            if limits.allowed_channels is not None
            else None
        ),
    }

def _safety_explanation_for_args(
    args: argparse.Namespace,
    limits: SafetyLimits,
    sources: dict[str, str | None],
) -> dict[str, dict[str, Any]]:
    field_sources = _safety_field_sources(args)
    source_layers = [
        {"layer": "global", "name": sources.get("global")},
        {"layer": "model", "name": sources.get("model")},
        {"layer": "resource", "name": sources.get("resource")},
        {"layer": "channel", "name": sources.get("channel")},
    ]
    payload = _safety_limits_payload(limits)
    return {
        field: {
            "value": value,
            "effective_source": field_sources.get(field),
            "source_layers": source_layers,
        }
        for field, value in payload.items()
    }

def _safety_field_sources(args: argparse.Namespace) -> dict[str, str | None]:
    fields = (
        "max_voltage",
        "max_current",
        "confirm_above_voltage",
        "confirm_above_current",
        "allowed_channels",
    )
    sources: dict[str, str | None] = {field: None for field in fields}
    config = load_safety_config_document(args.safety_config)
    if config.global_limits is not None:
        for field in fields:
            if getattr(config.global_limits, field) is not None:
                sources[field] = "global:safety"
    model_id = canonical_physical_model_id(args.model)
    model_name = (
        IDENTITY_INDEXES.models_by_id[model_id].canonical_model
        if model_id is not None
        else None
    )
    model_entry = config.model_limits_for(model_name)
    if model_entry is not None and model_name is not None:
        for field in model_entry[1]:
            sources[field] = f"model:{model_name}"
    entry = None
    if args.resource_alias is not None:
        entry = config.entry_for_alias(args.resource_alias)
    elif args.resource is not None:
        entry = config.entry_for_resource(args.resource)
    if entry is not None:
        for field in entry.limit_fields:
            sources[field] = f"resource:{entry.alias}"
        channel_entry = None
        if isinstance(args.channel, int) and entry.channel_limits is not None:
            channel_entry = entry.channel_limits.get(args.channel)
        if channel_entry is not None:
            for field in channel_entry[1]:
                sources[field] = f"channel:{args.channel}"
    return sources

def _output_affecting_allowed(channel: int | None, limits: SafetyLimits) -> bool:
    if channel is not None:
        try:
            validate_channel(channel, limits)
        except SafetyValidationError:
            return False
    return True

class _ReadOnlyModelError(ValueError):
    """Raised when read-only model-specific commands see an unsupported model."""

class _ReadOnlyChannelError(ValueError):
    """Raised when read-only model-specific commands receive an unsupported channel."""

class _E36312AChannelError(ValueError):
    """Raised when an E36312A command receives an unsupported channel."""

def _list_resources(
    resource_manager: SimulatedResourceManager | None,
    *,
    backend: str | None,
) -> tuple[str, ...]:
    if resource_manager is None:
        return _patchable_list_resources(backend=backend)
    return _patchable_list_resources(resource_manager, backend=backend)

def _open_resource(
    resource: str,
    resource_manager: SimulatedResourceManager | None,
    *,
    backend: str | None,
    timeout_ms: int,
    serial_options: SerialOptions | None = None,
    serial_remote: bool = False,
    serial_local_on_close: bool = False,
    scpi_logger: Any = None,
):
    serial_kwargs = _serial_open_kwargs(
        serial_options=serial_options,
        serial_remote=serial_remote,
        serial_local_on_close=serial_local_on_close,
    )
    if resource_manager is None:
        if scpi_logger is not None:
            serial_kwargs["scpi_logger"] = scpi_logger
        return _patchable_open_resource(
            resource,
            backend=backend,
            timeout_ms=timeout_ms,
            **serial_kwargs,
        )
    if scpi_logger is not None:
        serial_kwargs["scpi_logger"] = scpi_logger
    return _patchable_open_resource(
        resource,
        resource_manager,
        backend=backend,
        timeout_ms=timeout_ms,
        **serial_kwargs,
    )

def _serial_open_kwargs(
    *,
    serial_options: SerialOptions | None,
    serial_remote: bool,
    serial_local_on_close: bool,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if serial_options is not None:
        kwargs["serial_options"] = serial_options
    if serial_remote:
        kwargs["serial_remote"] = True
    if serial_local_on_close:
        kwargs["serial_local_on_close"] = True
    return kwargs

def _max_reads_from_argv(argv: Sequence[str]) -> int | str:
    value = _option_value(argv, "--max-reads")
    if value is None:
        return 20
    try:
        return int(value)
    except ValueError:
        return value

def _json_save_path_from_argv(argv: Sequence[str]) -> str | None:
    if "--json" not in argv:
        return None
    return _option_value(argv, "--save-json")

def _command_from_argv(argv: Sequence[str]) -> str:
    import sys

    cli_module = sys.modules.get("powers_tool_cli.cli")
    command_names = getattr(cli_module, "COMMAND_NAMES", frozenset())
    for item in argv:
        if item in command_names:
            return item
    return "unknown"

def _exit_code(exc: SystemExit) -> int:
    if exc.code is None:
        return 0
    if isinstance(exc.code, int):
        return exc.code
    return 1

def _log_scpi(resource: str, direction: str, message: str) -> None:
    print(f"{resource} SCPI {direction} {message}", file=sys.stderr)

_CHANNEL_NOT_PROVIDED = object()

def _safety_limits_for_args(
    args: argparse.Namespace,
    *,
    model: str | None = None,
    channel: object = _CHANNEL_NOT_PROVIDED,
) -> SafetyLimits | None:
    resolved_channel = (
        getattr(args, "channel", None)
        if channel is _CHANNEL_NOT_PROVIDED
        else channel
    )
    try:
        resource, limits = validation.resolve_request_safety_limits(
            safety_config=getattr(args, "safety_config", None),
            resource=getattr(args, "resource", None),
            resource_alias=getattr(args, "resource_alias", None),
            model=model,
            channel=resolved_channel if isinstance(resolved_channel, int) else None,
        )
    except validation.SafetyResolutionError as exc:
        raise SafetyConfigError(str(exc)) from exc
    args.resource = resource
    return limits

def _safety_limits_for_channel(
    args: argparse.Namespace,
    channel: int,
    *,
    model: str | None = None,
) -> SafetyLimits | None:
    return _safety_limits_for_args(args, model=model, channel=channel)

def _validate_output_request(
    args: argparse.Namespace,
    safety_limits: SafetyLimits | None,
) -> None:
    if args.command == "ramp" and getattr(args, "channels", None) is not None:
        return
    validation.validate_output_request(
        command=args.command,
        channel=args.channel,
        safety_limits=safety_limits,
        voltage=getattr(args, "voltage", None),
        current=getattr(args, "current", None),
        start_voltage=getattr(args, "start_voltage", None),
        stop_voltage=getattr(args, "stop_voltage", None),
        step_voltage=getattr(args, "step_voltage", None),
    )

def _emit_cli_error(
    args: argparse.Namespace,
    *,
    request: dict[str, Any],
    error_type: str,
    code: str,
    message: str,
    retryable: bool,
    hardware_intent: bool = False,
) -> int:
    if args.json:
        emit_json_error(
            command=args.command,
            execution=_execution_for_args(args, hardware_intent=hardware_intent),
            request=request,
            error_type=error_type,
            code=code,
            message=message,
            retryable=retryable,
        )
    else:
        print(message, file=sys.stderr)
    return 2

def _emit_invalid_core_result(
    args: argparse.Namespace,
    *,
    request: dict[str, Any],
    execution: dict[str, Any],
    message: str,
) -> int:
    if args.json:
        emit_json_error(
            command=args.command,
            execution=execution,
            request=request,
            error_type="execution",
            code="invalid_core_result",
            message=message,
            retryable=False,
        )
    else:
        print(message, file=sys.stderr)
    return 3

def _emit_safe_io_error(
    args: argparse.Namespace,
    *,
    request: dict[str, Any],
    execution: dict[str, Any],
    code: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> int:
    if args.json:
        emit_json_error(
            command=args.command,
            execution=execution,
            request=request,
            error_type="connection",
            code=code,
            message=message,
            retryable=True,
            data=data,
        )
    else:
        print(message, file=sys.stderr)
    return 1

def _enforce_live_cli_scope(args: argparse.Namespace, idn_raw: str, *, command: str | None = None) -> None:
    """Apply the Core-owned gate in a legacy CLI runner that still owns I/O."""
    from powers_tool_cli.cli_request import _target_core_request_for_args

    request = _target_core_request_for_args(args)
    if request.runtime.simulate:
        return
    effective_command = command or request.command
    enforce_live_support_for_idn(request, idn_raw, command=effective_command)

def _core_validation_code(exc: CoreValidationError, fallback: str = "argument_error") -> str:
    return "unsupported_live_scope" if isinstance(exc, LiveSupportPolicyError) else fallback

def _connection_scpi_logger_for_args(args: argparse.Namespace):
    if not getattr(args, "log_scpi", False):
        return None
    if not (getattr(args, "serial_remote", False) or getattr(args, "serial_local_on_close", False)):
        return None
    return _log_scpi

def _core_opener_for_args(args: argparse.Namespace):
    manager = _resource_manager_for_args(args)

    def opener(
        resource: str,
        resource_manager: Any = None,
        *,
        backend: str | None,
        timeout_ms: int,
        serial_options: SerialOptions | None = None,
        serial_remote: bool = False,
        serial_local_on_close: bool = False,
    ):
        return _open_resource(
            resource,
            resource_manager if resource_manager is not None else manager,
            backend=backend,
            timeout_ms=timeout_ms,
            serial_options=serial_options,
            serial_remote=serial_remote,
            serial_local_on_close=serial_local_on_close,
            scpi_logger=_connection_scpi_logger_for_args(args),
        )

    return opener

def _core_lister_for_args(args: argparse.Namespace):
    manager = _resource_manager_for_args(args)

    def lister(resource_manager: Any = None, *, backend: str | None):
        return _list_resources(resource_manager if resource_manager is not None else manager, backend=backend)

    return lister

def _emit_text_lines(lines: Sequence[str]) -> None:
    for line in lines:
        print(line)

def _format_text_value(value: object) -> str:
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value)

def _parse_measurement(response: str, measurement: str) -> float:
    try:
        return float(response.strip())
    except ValueError as exc:
        raise ValueError(f"Could not parse {measurement} measurement: {response!r}") from exc

def _is_no_error_response(response: str) -> bool:
    normalized = response.strip().lstrip("+")
    return normalized == "0" or normalized.startswith("0,")

def _unsupported_measure_channel_message(
    *,
    channel: int,
    mode: str,
    driver_name: str,
    allowed_channels: tuple[int, ...],
) -> str:
    return (
        f"measure channel {channel} is not enabled in {mode} mode for "
        f"{driver_name}; supported: {_format_channel_set(allowed_channels)}"
    )

def _format_channel_set(channels: tuple[int, ...]) -> str:
    if channels == (1,):
        return "channel 1 only"
    return "channels " + ", ".join(str(channel) for channel in channels)

