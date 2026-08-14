"""CLI JSON request envelope and Core request construction."""

from __future__ import annotations

__all__ = [
    "_core_command_parameters",
    "_driver_step",
    "_operation_request_for_args",
    "_output_plan_for_args",
    "_ramp_list_request_for_args",
    "_request_for_args",
    "_request_from_argv",
    "_sequence_request_for_args",
    "_target_core_request_for_args",
    "_validate_readonly_request_for_args",
    "_trigger_request_for_args",
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
    TriggerInterrupted,
    TriggerRequest,
    TriggerWaitTimeout,
    UnsupportedChannelError,
    UnsupportedModelError,
)
from powers_tool_core.errors import VisaConnectionError
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
from powers_tool_cli import cli_runtime
from powers_tool_cli.cli_runtime import *
from powers_tool_cli import cli_runtime
from powers_tool_cli.cli_runtime import *

def _request_for_args(args: argparse.Namespace) -> dict[str, Any]:
    from powers_tool_cli.commands import output as output_commands

    if args.command in output_commands.OUTPUT_REQUEST_COMMANDS:
        return output_commands.request_for_args(args)
    if args.command == "safety":
        return {
            "subcommand": getattr(args, "safety_command", None),
            "resource": getattr(args, "resource", None),
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": getattr(args, "channel", None),
            "model": getattr(args, "model", None),
            "safety_config": getattr(args, "safety_config", None),
        }
    if args.command == "safety inspect":
        return {
            "resource": getattr(args, "resource", None),
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": getattr(args, "channel", None),
            "model": getattr(args, "model", None),
            "safety_config": getattr(args, "safety_config", None),
            "explain": getattr(args, "explain", False),
        }
    if args.command == "list-resources":
        return _with_serial_request_fields(args, {
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            "live_only": getattr(args, "live_only", False),
        })
    if args.command == "verify":
        return _with_serial_request_fields(args, {
            "resource": args.resource,
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        })
    if args.command == "clear":
        return _with_serial_request_fields(args, {
            "resource": args.resource,
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        })
    if args.command == "error":
        return _with_serial_request_fields(args, {
            "resource": args.resource,
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            "max_reads": args.max_reads,
        })
    if args.command == "measure":
        return _with_serial_request_fields(args, {
            "resource": args.resource,
            "channel": args.channel,
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        })
    if args.command == "measure-all":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    from powers_tool_cli.commands import trigger as trigger_commands

    if args.command in trigger_commands.TRIGGER_COMMANDS:
        return trigger_commands.request_for_args(args)
    if args.command == "read-status":
        channel = "all" if getattr(args, "all", False) else args.channel
        return _with_serial_request_fields(args, {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": channel,
            "max_errors": args.max_errors,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        })
    if args.command in {"send-command", "status", "stop", "wait-ready"}:
        return {
            "url": getattr(args, "url", None),
            "host": getattr(args, "host", None),
            "port": getattr(args, "port", None),
            "timeout_ms": getattr(args, "timeout_ms", None),
        }
    if args.command == "validate-readonly":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            "max_errors": args.max_errors,
        }
    if args.command in {"readback", "protection-status"}:
        channel = "all" if getattr(args, "all", False) else args.channel
        payload = {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": channel,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
        return _with_serial_request_fields(args, payload) if args.command == "readback" else payload
    if args.command == "protection-set":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "ovp_voltage": (
                _json_safe_number(args.ovp_voltage)
                if args.ovp_voltage is not None
                else None
            ),
            "ocp": args.ocp,
            "ocp_delay": (
                _json_safe_number(args.ocp_delay)
                if args.ocp_delay is not None
                else None
            ),
            "ocp_delay_trigger": args.ocp_delay_trigger,
            "confirm": getattr(args, "confirm", False),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "clear-protection":
        channel = "all" if getattr(args, "all", False) else args.channel
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": channel,
            "confirm": getattr(args, "confirm", False),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "identify":
        return _with_serial_request_fields(args, {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        })
    if args.command == "snapshot":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "max_errors": args.max_errors,
            "compare": getattr(args, "compare", None),
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            "redact_resource": getattr(args, "redact_resource", False),
        }
    if args.command == "snapshot-diff":
        return {
            "before": args.before,
            "after": args.after,
            "summary": getattr(args, "summary", False),
        }
    if args.command == "hardware-report":
        return {
            "input_dir": args.input_dir,
            "target": args.target,
            "connection": args.connection,
            "resource": args.resource,
            "report_json": args.report_json,
            "summary_md": args.summary_md,
            "before_json": getattr(args, "before_json", None),
            "after_json": getattr(args, "after_json", None),
        }
    if args.command == "restore-from-snapshot":
        return {
            "snapshot": args.snapshot,
            "resource": args.resource,
            "channel": args.channel,
            "restore_output_state": getattr(args, "restore_output_state", False),
            "confirm": getattr(args, "confirm", False),
            "plan_json": getattr(args, "plan_json", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "log":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "channel": args.channel,
            "channels": getattr(args, "channels", None),
            "interval_sec": args.interval_sec,
            "csv": args.csv,
            "jsonl": getattr(args, "jsonl", None),
            "append": getattr(args, "append", False),
            "samples": args.samples,
            "duration_sec": args.duration_sec,
            "safety_config": getattr(args, "safety_config", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            "lint": getattr(args, "lint", False),
        }
    if args.command == "sequence":
        from powers_tool_cli.commands import sequence as sequence_command

        return sequence_command.request_for_args(args)
    if args.command == "ramp-list":
        from powers_tool_cli.commands import ramp_list as ramp_list_command

        return ramp_list_command.request_for_args(args)
    if args.command == "doctor":
        return {
            "resource": getattr(args, "resource", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    if args.command == "capabilities":
        return {
            "resource": args.resource,
            "resource_alias": getattr(args, "resource_alias", None),
            "command": getattr(args, "selected_command", None),
            "backend": getattr(args, "backend", None),
            "timeout_ms": getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
        }
    return {}

def _request_from_argv(command: str, argv: Sequence[str]) -> dict[str, Any]:
    from powers_tool_cli.commands import output as output_commands

    if command in output_commands.OUTPUT_REQUEST_COMMANDS:
        return output_commands.request_from_argv(command, argv)
    if command == "safety":
        return {
            "subcommand": "inspect" if "inspect" in argv else None,
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "model": _option_value(argv, "--model"),
            "safety_config": _option_value(argv, "--safety-config"),
            "explain": "--explain" in argv,
        }
    if command == "list-resources":
        return _with_serial_request_fields_from_argv(argv, {
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
            "live_only": "--live-only" in argv,
        })
    if command == "verify":
        return _with_serial_request_fields_from_argv(argv, {
            "resource": _option_value(argv, "--resource"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        })
    if command == "clear":
        return _with_serial_request_fields_from_argv(argv, {
            "resource": _option_value(argv, "--resource"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        })
    if command == "error":
        return _with_serial_request_fields_from_argv(argv, {
            "resource": _option_value(argv, "--resource"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
            "max_reads": _max_reads_from_argv(argv),
        })
    if command == "measure":
        return _with_serial_request_fields_from_argv(argv, {
            "resource": _option_value(argv, "--resource"),
            "channel": _channel_from_argv(argv),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        })
    if command == "measure-all":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    from powers_tool_cli.commands import trigger as trigger_commands

    if command in trigger_commands.TRIGGER_COMMANDS:
        return trigger_commands.request_from_argv(command, argv)
    if command == "read-status":
        channel = "all" if "--all" in argv else (_status_channel_from_argv(argv) or "all")
        return _with_serial_request_fields_from_argv(argv, {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": channel,
            "max_errors": _max_errors_from_argv(argv),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        })
    if command == "validate-readonly":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
            "max_errors": _max_errors_from_argv(argv),
        }
    if command in {"readback", "protection-status"}:
        channel = "all" if "--all" in argv else (_status_channel_from_argv(argv) or "all")
        payload = {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": channel,
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
        return _with_serial_request_fields_from_argv(argv, payload) if command == "readback" else payload
    if command == "protection-set":
        channel = "all" if "--all" in argv else (_status_channel_from_argv(argv) or "all")
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": channel,
            "ovp_voltage": _number_from_argv(argv, "--ovp-voltage"),
            "ocp": _option_value(argv, "--ocp"),
            "ocp_delay": _number_from_argv(argv, "--ocp-delay"),
            "ocp_delay_trigger": _option_value(argv, "--ocp-delay-trigger"),
            "confirm": "--confirm" in argv,
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "clear-protection":
        channel = "all" if "--all" in argv else _status_channel_from_argv(argv)
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": channel,
            "confirm": "--confirm" in argv,
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "identify":
        return _with_serial_request_fields_from_argv(argv, {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        })
    if command == "snapshot":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "max_errors": _max_errors_from_argv(argv),
            "compare": _option_value(argv, "--compare"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
            "redact_resource": "--redact-resource" in argv,
        }
    if command == "snapshot-diff":
        return {
            "before": _option_value(argv, "--before"),
            "after": _option_value(argv, "--after"),
            "summary": "--summary" in argv,
        }
    if command == "hardware-report":
        return {
            "input_dir": _option_value(argv, "--input-dir"),
            "target": _option_value(argv, "--target"),
            "connection": _option_value(argv, "--connection"),
            "resource": _option_value(argv, "--resource"),
            "report_json": _option_value(argv, "--report-json"),
            "summary_md": _option_value(argv, "--summary-md"),
            "before_json": _option_value(argv, "--before-json"),
            "after_json": _option_value(argv, "--after-json"),
        }
    if command == "restore-from-snapshot":
        return {
            "snapshot": _option_value(argv, "--snapshot"),
            "resource": _option_value(argv, "--resource"),
            "channel": _status_channel_from_argv(argv),
            "restore_output_state": "--restore-output-state" in argv,
            "confirm": "--confirm" in argv,
            "plan_json": _option_value(argv, "--plan-json"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "log":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "channel": _channel_from_argv(argv),
            "channels": _option_value(argv, "--channels"),
            "interval_sec": _number_from_argv(argv, "--interval-sec"),
            "csv": _option_value(argv, "--csv"),
            "jsonl": _option_value(argv, "--jsonl"),
            "append": "--append" in argv,
            "samples": _int_from_argv(argv, "--samples"),
            "duration_sec": _number_from_argv(argv, "--duration-sec"),
            "safety_config": _option_value(argv, "--safety-config"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
            "lint": "--lint" in argv,
        }
    if command == "sequence":
        from powers_tool_cli.commands import sequence as sequence_command

        return sequence_command.request_from_argv(argv)
    if command == "ramp-list":
        from powers_tool_cli.commands import ramp_list as ramp_list_command

        return ramp_list_command.request_from_argv(argv)
    if command == "doctor":
        return {
            "resource": _option_value(argv, "--resource"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    if command == "capabilities":
        return {
            "resource": _option_value(argv, "--resource"),
            "resource_alias": _option_value(argv, "--resource-alias"),
            "command": _option_value(argv, "--command"),
            "backend": _option_value(argv, "--backend"),
            "timeout_ms": _timeout_from_argv(argv),
        }
    return {}

def _output_plan_for_args(args: argparse.Namespace) -> dict[str, Any]:
    return operations.output_plan(_operation_request_for_args(args))

def _driver_step(index: int, action: str, **parameters: Any) -> dict[str, Any]:
    return {
        "index": index,
        "type": "driver_action",
        "action": action,
        "parameters": parameters,
    }

def _operation_request_for_args(args: argparse.Namespace) -> OperationRequest:
    completion_pulse_pins: tuple[int, ...] = ()
    if hasattr(args, "completion_pulse_pins"):
        from powers_tool_cli.commands import trigger_run

        completion_pulse_pins = trigger_run._completion_pulse_pins(args)
    parameters = {
        "channel": getattr(args, "channel", None),
        "channels": getattr(args, "channels", None),
        "voltage": getattr(args, "voltage", None),
        "current": getattr(args, "current", None),
        "duration_ms": getattr(args, "duration_ms", 0),
        "settle_ms": getattr(args, "settle_ms", 0),
        "verify_after_write": getattr(args, "verify_after_write", False),
        "setpoint_voltage_tolerance": getattr(args, "setpoint_voltage_tolerance", 0.001),
        "setpoint_current_tolerance": getattr(args, "setpoint_current_tolerance", 0.001),
        "no_output": getattr(args, "no_output", False),
        "start_voltage": getattr(args, "start_voltage", None),
        "stop_voltage": getattr(args, "stop_voltage", None),
        "step_voltage": getattr(args, "step_voltage", None),
        "delay_ms": getattr(args, "delay_ms", 0),
        "enable_output": getattr(args, "enable_output", False),
        "loop_count": getattr(args, "loop_count", None) or 1,
        "completion_pulse_pins": completion_pulse_pins,
        "completion_pulse_channel": getattr(args, "completion_pulse_channel", None),
        "completion_pulse_polarity": getattr(args, "completion_pulse_polarity", "positive"),
        "leave_trigger_configured": getattr(args, "leave_trigger_configured", False),
    }
    if args.command == "ramp":
        parameters["completion_pulse_timing"] = getattr(args, "completion_pulse_timing", "segment")
    parameters = _core_command_parameters(args.command, parameters)
    return OperationRequest(
        command=args.command,
        runtime=RuntimeOptions(
            resource=getattr(args, "resource", None),
            resource_alias=getattr(args, "resource_alias", None),
            safety_config=getattr(args, "safety_config", None),
            simulate=getattr(args, "simulate", False),
            dry_run=getattr(args, "dry_run", False),
            **_runtime_identity_for_args(args),
            backend=getattr(args, "backend", None),
            timeout_ms=getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            log_scpi=getattr(args, "log_scpi", False),
            confirm=getattr(args, "confirm", False),
            serial_options=_serial_options_for_args(args),
            serial_remote=getattr(args, "serial_remote", False),
            serial_local_on_close=getattr(args, "serial_local_on_close", False),
            support_policy_mode=_support_policy_mode_for_args(args),
        ),
        parameters=parameters,
    )

def _target_core_request_for_args(args: argparse.Namespace) -> OperationRequest:
    parameters: dict[str, Any] = {
        "channel": getattr(args, "channel", None),
        "all": getattr(args, "all", False),
        "live_only": getattr(args, "live_only", False),
        "max_reads": getattr(args, "max_reads", getattr(args, "max_errors", 20)),
        "max_errors": getattr(args, "max_errors", 20),
        "ovp_voltage": getattr(args, "ovp_voltage", None),
        "ocp": getattr(args, "ocp", None),
        "ocp_delay": getattr(args, "ocp_delay", None),
        "ocp_delay_trigger": getattr(args, "ocp_delay_trigger", None),
        "channels": getattr(args, "channels", None),
        "interval_sec": getattr(args, "interval_sec", None),
        "samples": getattr(args, "samples", None),
        "duration_sec": getattr(args, "duration_sec", None),
    }
    return OperationRequest(
        command=args.command,
        runtime=RuntimeOptions(
            resource=getattr(args, "resource", None),
            resource_alias=getattr(args, "resource_alias", None),
            safety_config=getattr(args, "safety_config", None),
            simulate=getattr(args, "simulate", False),
            dry_run=getattr(args, "dry_run", False),
            **_runtime_identity_for_args(args),
            backend=getattr(args, "backend", None),
            timeout_ms=getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            log_scpi=getattr(args, "log_scpi", False),
            confirm=getattr(args, "confirm", False),
            serial_options=_serial_options_for_args(args),
            serial_remote=getattr(args, "serial_remote", False),
            serial_local_on_close=getattr(args, "serial_local_on_close", False),
            support_policy_mode=_support_policy_mode_for_args(args),
        ),
        parameters=_core_command_parameters(args.command, parameters),
    )


def _validate_readonly_request_for_args(args: argparse.Namespace) -> OperationRequest:
    """Build the narrow Core request used by the readonly validation adapter."""
    request = _target_core_request_for_args(args)
    return OperationRequest(
        command=request.command,
        runtime=request.runtime,
        parameters={"max_errors": getattr(args, "max_errors", 20)},
    )

def _sequence_request_for_args(args: argparse.Namespace) -> SequenceRequest:
    from powers_tool_cli.commands import sequence as sequence_command

    return sequence_command.core_request_for_args(args)

def _ramp_list_request_for_args(args: argparse.Namespace) -> OperationRequest:
    from powers_tool_cli.commands import ramp_list as ramp_list_command

    return ramp_list_command.core_request_for_args(args)

def _trigger_request_for_args(args: argparse.Namespace) -> TriggerRequest:
    completion_pulse_pins: tuple[int, ...] = ()
    if hasattr(args, "completion_pulse_pins"):
        from powers_tool_cli.commands import trigger_run

        completion_pulse_pins = trigger_run._completion_pulse_pins(args)
    parameters: dict[str, Any] = {
        "channel": getattr(args, "channel", None),
        "source": getattr(args, "source", "bus"),
        "voltage": getattr(args, "voltage", None),
        "current": getattr(args, "current", None),
        "fire": getattr(args, "fire", False),
        "wait_complete": getattr(args, "wait_complete", False),
        "wait_timeout_ms": getattr(args, "wait_timeout_ms", None),
        "poll_ms": getattr(args, "poll_ms", 200),
        "leave_trigger_configured": getattr(args, "leave_trigger_configured", False),
        "completion_pulse_pins": completion_pulse_pins,
        "completion_pulse_polarity": getattr(args, "completion_pulse_polarity", "positive"),
        "exclusive_pins": getattr(args, "exclusive_pins", False),
        "pin": getattr(args, "pin", None),
        "pins": getattr(args, "pins", None),
        "polarity": getattr(args, "polarity", "positive"),
        "max_errors": getattr(args, "max_errors", 20),
    }
    if args.command == "trigger-list":
        from powers_tool_cli.commands import trigger_run

        config = trigger_run._trigger_list_config_from_args(args)
        trigger_run._validate_trigger_list_limits(
            voltages=config["voltages"],
            currents=config["currents"],
            dwell=config["dwell"],
            count=config["count"],
        )
        trigger_run._validate_trigger_list_control_args(args, config)
        trigger_run._validate_trigger_list_safety(
            config,
            _safety_limits_for_channel(args, config["channel"], model="E36312A"),
        )
        parameters.update(config)
        if not parameters.get("pins"):
            parameters.pop("pins", None)
        if "begin_outputs" in config:
            parameters.pop("completion_pulse_pins", None)
            parameters.pop("completion_pulse_polarity", None)
            parameters["bost_list"] = config["begin_outputs"]
            parameters["eost_list"] = config["end_outputs"]
            parameters["trigger_output_pins"] = config["pins"]
            parameters["trigger_output_polarity"] = config["polarity"]
    return TriggerRequest(
        command=args.command,
        runtime=RuntimeOptions(
            resource=getattr(args, "resource", None),
            resource_alias=getattr(args, "resource_alias", None),
            safety_config=getattr(args, "safety_config", None),
            simulate=getattr(args, "simulate", False),
            dry_run=getattr(args, "dry_run", False),
            **_runtime_identity_for_args(args),
            backend=getattr(args, "backend", None),
            timeout_ms=getattr(args, "timeout_ms", DEFAULT_TIMEOUT_MS),
            log_scpi=getattr(args, "log_scpi", False),
            support_policy_mode=_support_policy_mode_for_args(args),
        ),
        parameters=_core_command_parameters(args.command, parameters),
    )

def _core_command_parameters(command: str, values: dict[str, Any]) -> dict[str, Any]:
    """Remove argparse-only defaults using the Core-owned command contract."""

    allowed = command_parameter_names(command)
    return {
        name: value
        for name, value in values.items()
        if name in allowed
        and value is not None
        and not (
            name == "all"
            and (
                value is False
                or (
                    command in {"protection-status", "protection-set", "clear-protection"}
                    and values.get("channel") is not None
                )
            )
        )
        and not (name == "completion_pulse_pins" and not value)
    }

