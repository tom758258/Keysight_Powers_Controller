"""Doctor, capabilities, and safety inspection command handlers."""

from __future__ import annotations

__all__ = [
    "_run_capabilities",
    "_run_doctor",
    "_run_safety_inspect",
    "_run_worker",
]

import argparse
import importlib.metadata
import platform
import sys
from pathlib import Path
from typing import Any

import powers_tool_core.capabilities as capabilities
from powers_tool_cli import cli_rendering
from powers_tool_cli.cli_io import emit_json_success
from powers_tool_cli.cli_request import _request_for_args
from powers_tool_cli.cli_runtime import (
    _ScpiLoggingSession,
    _core_validation_code,
    _emit_cli_error,
    _emit_safe_io_error,
    _emit_text_lines,
    _enforce_live_cli_scope,
    _list_resources,
    _open_resource,
    _output_affecting_allowed,
    _package_version,
    _patchable_select_driver,
    _resolve_optional_resource_alias,
    _resource_manager_for_args,
    _resource_payload,
    _safety_explanation_for_args,
    _safety_limits_payload,
)
from powers_tool_cli.runtime_mapping import execution_for_args as _execution_for_args
from powers_tool_core.core import CoreValidationError
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import MODEL_DRIVERS
from powers_tool_core.identity import (
    IDENTITY_INDEXES,
    IdentityResolutionError,
    canonical_physical_model_id,
)
from powers_tool_core.models import PRODUCT_ACTIVE_MODEL_IDS
from powers_tool_core.safety import SafetyConfigError, resolve_safety_config
from powers_tool_core.testing.simulator import SimulatedResourceManager

IDN_QUERY = "*IDN?"

def _run_worker(args: argparse.Namespace) -> int:
    from powers_tool_cli.worker import run_worker
    return run_worker(args)

def _run_doctor(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=bool(args.resource))
    manager = _resource_manager_for_args(args)
    pyvisa_available = importlib.util.find_spec("pyvisa") is not None
    data: dict[str, Any] = {
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "package": {"name": "powers-tool-cli", "version": _package_version()},
        "pyvisa": {"available": pyvisa_available, "backend": args.backend},
        "simulator": {
            "available": True,
            "resources": list(SimulatedResourceManager().list_resources()),
        },
        "real_resource_manager": {
            "checked": not args.simulate,
            "available": None,
            "error": None,
        },
        "resource": None,
        "environment": {
            "cwd": str(Path.cwd()),
            "venv": {
                "active": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
                "prefix": sys.prefix,
            },
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
            },
            "python": {"executable": sys.executable},
        },
    }
    if not args.simulate:
        try:
            _list_resources(None, backend=args.backend)
            data["real_resource_manager"]["available"] = True
        except VisaConnectionError as exc:
            data["real_resource_manager"]["available"] = False
            data["real_resource_manager"]["error"] = str(exc)

    if args.resource:
        try:
            with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
                session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
                idn = session.query(IDN_QUERY)
                _enforce_live_cli_scope(args, idn, command="doctor")
            data["resource"] = _resource_payload(
                args.resource,
                simulated=args.simulate,
                reachable=True,
                idn_raw=idn,
            )
        except CoreValidationError as exc:
            return _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code=_core_validation_code(exc),
                message=str(exc),
                retryable=False,
                hardware_intent=True,
            )
        except VisaConnectionError as exc:
            return _emit_safe_io_error(
                args,
                request=request,
                execution=execution,
                code="doctor_resource_failed",
                message=f"doctor resource check failed: {exc}",
            )

    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
    else:
        _emit_text_lines(
            cli_rendering.format_doctor(data, pyvisa_available=pyvisa_available)
        )
    return 0

def _run_capabilities(args: argparse.Namespace) -> int:
    request = _request_for_args(args)
    selected_command = getattr(args, "selected_command", None)
    if selected_command and selected_command not in capabilities.known_capability_commands():
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=f"unknown command: {selected_command}",
            retryable=False,
        )

    if args.model is not None:
        execution = _execution_for_args(args, hardware_intent=False)
        try:
            model_id = canonical_physical_model_id(args.model)
        except IdentityResolutionError as exc:
            return _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="argument_error",
                message=str(exc),
                retryable=False,
            )
        assert model_id is not None
        if model_id not in PRODUCT_ACTIVE_MODEL_IDS:
            return _emit_cli_error(
                args,
                request=request,
                error_type="validation",
                code="argument_error",
                message=f"unsupported physical model_id {model_id!r}",
                retryable=False,
            )

        identity = IDENTITY_INDEXES.models_by_id[model_id]
        vendor = IDENTITY_INDEXES.vendors_by_id[identity.vendor_id]
        driver_class = MODEL_DRIVERS[model_id]
        caps = driver_class.capabilities
        data = {
            "model_id": identity.model_id,
            "vendor_id": identity.vendor_id,
            "vendor_display_name": vendor.display_name,
            "model_name": identity.canonical_model,
            "display_name": identity.display_name,
            "driver": {"class": driver_class.__name__},
            "channels": list(caps.channels),
            "measure_channels": {
                "simulate": list(caps.simulated_measure_channels),
                "real": list(caps.real_measure_channels),
            },
            **capabilities.capabilities_static_groups(),
            "hardware_validation": capabilities.hardware_validation_status(model_id),
            "command_support": capabilities.command_support(model_id),
            "electrical_ratings": (
                caps.electrical_ratings.to_dict() if caps.electrical_ratings else None
            ),
        }
        if selected_command:
            support = data["command_support"]
            data["selected_command"] = {"name": selected_command, **support[selected_command]}
        if args.json:
            emit_json_success(
                command=args.command,
                execution=execution,
                request=request,
                data=data,
            )
        else:
            _emit_text_lines(cli_rendering.format_capabilities(data))
        return 0

    execution = _execution_for_args(args, hardware_intent=True)
    manager = _resource_manager_for_args(args)
    try:
        _resolve_optional_resource_alias(args)
        request = _request_for_args(args)
        with _open_resource(args.resource, manager, backend=args.backend, timeout_ms=args.timeout_ms) as instrument:
            session: Any = _ScpiLoggingSession(args.resource, instrument) if args.log_scpi else instrument
            idn_raw = session.query(IDN_QUERY)
            _enforce_live_cli_scope(args, idn_raw, command="capabilities")
        selection = _patchable_select_driver(idn_raw)
    except SafetyConfigError as exc:
        return _emit_cli_error(args, request=request, error_type="validation", code="argument_error", message=str(exc), retryable=False)
    except CoreValidationError as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code=_core_validation_code(exc),
            message=str(exc),
            retryable=False,
            hardware_intent=True,
        )
    except VisaConnectionError as exc:
        return _emit_safe_io_error(
            args,
            request=request,
            execution=execution,
            code="capabilities_failed",
            message=f"capabilities failed: {exc}",
        )

    caps = selection.capabilities
    static_groups = capabilities.capabilities_static_groups()
    data = {
        "resource": _resource_payload(
            args.resource,
            simulated=args.simulate,
            reachable=True,
            idn_raw=idn_raw,
        ),
        "driver": {
            "class": selection.driver_class.__name__,
            "reason": selection.reason,
        },
        "channels": list(caps.channels),
        "measure_channels": {
            "simulate": list(caps.simulated_measure_channels),
            "real": list(caps.real_measure_channels),
        },
        **static_groups,
        "hardware_validation": capabilities.hardware_validation_status(
            selection.physical_identity.model_id if selection.physical_identity else None
        ),
        "command_support": capabilities.command_support(
            selection.physical_identity.model_id if selection.physical_identity else None
        ),
        "electrical_ratings": caps.electrical_ratings.to_dict() if caps.electrical_ratings else None,
    }
    if selected_command:
        support = data["command_support"]
        data["selected_command"] = {"name": selected_command, **support[selected_command]}
    if args.json:
        emit_json_success(command=args.command, execution=execution, request=request, data=data)
    else:
        _emit_text_lines(cli_rendering.format_capabilities(data))
    return 0

def _run_safety_inspect(args: argparse.Namespace) -> int:
    args.command = "safety inspect"
    request = _request_for_args(args)
    execution = _execution_for_args(args, hardware_intent=False)
    try:
        if args.safety_config is None:
            raise SafetyConfigError("safety inspect requires --safety-config")
        model_id = canonical_physical_model_id(args.model)
        model_name = (
            IDENTITY_INDEXES.models_by_id[model_id].canonical_model
            if model_id is not None
            else None
        )
        resolution = resolve_safety_config(
            args.safety_config,
            resource=args.resource,
            resource_alias=args.resource_alias,
            model=model_name,
            channel=args.channel,
        )
    except (SafetyConfigError, IdentityResolutionError) as exc:
        return _emit_cli_error(
            args,
            request=request,
            error_type="validation",
            code="argument_error",
            message=str(exc),
            retryable=False,
        )
    limits = resolution.limits
    data = {
        "resource": resolution.resource,
        "resource_alias": resolution.resource_alias,
        "model_id": model_id,
        "channel": args.channel,
        "limits": _safety_limits_payload(limits),
        "sources": resolution.sources or {},
        "output_affecting_allowed": _output_affecting_allowed(args.channel, limits),
    }
    from powers_tool_core.electrical_ratings import ratings_for_model_id
    from powers_tool_core.setpoint_limits import effective_setpoint_limits

    ratings = ratings_for_model_id(args.model)
    official = ratings.channel(args.channel) if ratings is not None and isinstance(args.channel, int) else None
    effective = (
        effective_setpoint_limits(
            model=args.model,
            channel=args.channel,
            electrical_ratings=ratings,
            safety_limits=limits,
        )
        if isinstance(args.channel, int)
        else None
    )
    data["official_rating"] = official.to_dict() if official else None
    data["effective_limits"] = effective.to_dict() if effective else None
    if args.explain:
        data["explanation"] = _safety_explanation_for_args(args, limits, resolution.sources or {})
    if args.json:
        emit_json_success(command="safety inspect", execution=execution, request=request, data=data)
    else:
        _emit_text_lines(cli_rendering.format_safety_inspect(data))
    return 0
