"""WebUI request mapping for shared core command execution."""

from __future__ import annotations

import inspect
from copy import deepcopy
from typing import Any

from powers_tool_core import capabilities as core_capabilities
from powers_tool_core.command_runner import run_core_command
from powers_tool_core.connection import SerialOptions, normalize_serial_termination, open_resource
from powers_tool_core.core import (
    CommandCancelled,
    ConfirmationRequiredError,
    CoreExecutionError,
    CoreValidationError,
    OperationRequest,
    RuntimeOptions,
    SequenceRequest,
    TriggerRequest,
)
from powers_tool_core.discovery import IDN_QUERY, resource_payload
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import select_driver
from powers_tool_core.identity import IdentityResolutionError, resolve_physical_model_identity
from powers_tool_core.live_support import enforce_product_live_support_for_idn
from powers_tool_core.model_resolution import validate_live_expected_model
from powers_tool_core.model_metadata import product_active_model_metadata
from powers_tool_core.models import parse_idn
from powers_tool_core.readonly import run_live_panel_read
from powers_tool_core.support_policy import (
    EXEMPT_LIVE_DIAGNOSTIC_COMMANDS,
    LiveSupportPolicyError,
    SUPPORT_POLICY_MODE_PRODUCT,
    exact_live_support_metadata,
    normalize_backend,
    normalize_transport,
    )
from powers_tool_core.testing.simulator import SimulatedResourceManager

from .jobs import Job


MUTATING_COMMANDS = {
    "set",
    "apply",
    "output-on",
    "output-off",
    "safe-off",
    "cycle-output",
    "ramp",
    "ramp-list",
    "smoke-output",
    "sequence",
    "protection-set",
    "clear-protection",
    "restore-from-snapshot",
}

TRIGGER_COMMANDS = {
    "trigger-pulse",
    "trigger-status",
    "trigger-step",
    "trigger-list",
    "trigger-fire",
    "trigger-abort",
}

SHARED_CORE_COMMANDS = {
    "list-resources",
    "verify",
    "clear",
    "error",
    "measure",
    "measure-all",
    "read-status",
    "readback",
    "set",
    "apply",
    "output-on",
    "output-off",
    "safe-off",
    "output-state",
    "cycle-output",
    "ramp",
    "ramp-list",
    "smoke-output",
    "protection-status",
    "protection-set",
    "clear-protection",
    "identify",
    "snapshot",
    "restore-from-snapshot",
    "sequence",
    *TRIGGER_COMMANDS,
}

WEBUI_UNSUPPORTED_COMMANDS = {
    "doctor",
    "validate-readonly",
    "snapshot-diff",
    "hardware-report",
    "log",
}

WEBUI_SPECIAL_JOB_COMMANDS = {"capabilities", "safety inspect"}
WEBUI_JOB_COMMANDS = frozenset(SHARED_CORE_COMMANDS | WEBUI_SPECIAL_JOB_COMMANDS)


def selectable_physical_models(
    metadata: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return frontend-safe selectable model metadata from Core registries."""

    return [
        {
            key: value
            for key, value in entry.items()
            if key not in {
                "command_support", "live_support", "electrical_ratings", "setpoint_ranges",
            }
        }
        for entry in (metadata or product_active_model_metadata(())).values()
    ]

def channel_capabilities_by_model_id(
    metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return WebUI model-to-channel metadata from driver capabilities."""

    return {
        model_id: {
            "channels": entry["channels"],
            "output_control_scope": entry["output_control_scope"],
        }
        for model_id, entry in (metadata or product_active_model_metadata(())).items()
    }


def live_support_by_model_id(
    command_names: set[str],
    metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return safe Core-owned live-support projections for WebUI commands."""

    return {
        model_id: entry["live_support"]
        for model_id, entry in (
            metadata or product_active_model_metadata(command_names)
        ).items()
    }


def build_runtime_options(runtime_dict: dict[str, Any]) -> RuntimeOptions:
    return RuntimeOptions(
        resource=_optional_runtime_string(runtime_dict, "resource"),
        resource_alias=_optional_runtime_string(runtime_dict, "resource_alias"),
        safety_config=_optional_runtime_string(runtime_dict, "safety_config"),
        simulate=_optional_runtime_bool(runtime_dict, "simulate", False),
        dry_run=_optional_runtime_bool(runtime_dict, "dry_run", False),
        backend=_optional_runtime_string(runtime_dict, "backend"),
        planning_model_id=_optional_identity_string(runtime_dict, "planning_model_id"),
        expected_model_id=_optional_identity_string(runtime_dict, "expected_model_id"),
        planning_profile_id=_optional_identity_string(runtime_dict, "planning_profile_id"),
        timeout_ms=_runtime_timeout_ms(runtime_dict),
        log_scpi=_optional_runtime_bool(runtime_dict, "log_scpi", False),
        confirm=_optional_runtime_bool(runtime_dict, "confirm", False),
        serial_options=_serial_options_from_runtime(runtime_dict),
        serial_remote=_optional_runtime_bool(runtime_dict, "serial_remote", False),
        serial_local_on_close=_optional_runtime_bool(
            runtime_dict, "serial_local_on_close", False
        ),
        # WebUI is deliberately product-only; P4 mode selection is CLI-only.
        support_policy_mode="product",
    )


def execute_job_command(job: Job) -> dict[str, Any]:
    command = job.command
    if command not in WEBUI_JOB_COMMANDS:
        raise CoreValidationError(f"command is not supported by /api/jobs: {command}")
    runtime = build_runtime_options(job.runtime)
    if command == "capabilities":
        return _capabilities(runtime)
    if command == "safety inspect":
        return _safety_inspect(runtime)
    request = deepcopy(job.admitted_request) if job.admitted_request is not None else None
    runtime = request.runtime if request is not None else runtime
    if _requires_real_confirmation(command, runtime):
        raise ConfirmationRequiredError(f"Command '{command}' affects hardware output and requires explicit confirmation.")
    if request is None:
        request = _request_for_job(command, runtime, job.parameters)
    def report_cleanup(result: Any) -> None:
        payload = result.to_dict()
        job.cleanup.append(payload)
        job.add_event("power_cleanup", payload)
        if payload["status"] == "unsupported":
            job.warnings.append({"code": "cleanup_unsupported", "message": payload["message"]})

    kwargs: dict[str, Any] = {"stop_requested": lambda: job.cancel_requested}
    if "progress_reporter" in inspect.signature(run_core_command).parameters:
        kwargs["progress_reporter"] = lambda progress: job.add_event(
            "progress",
            {
                **progress,
                "message": (
                    f"{progress['percent']}% "
                    f"({progress['completed_units']:,}/{progress['total_units']:,} execution units)"
                ),
            },
        )
    if "cleanup_reporter" in inspect.signature(run_core_command).parameters:
        kwargs["cleanup_reporter"] = report_cleanup
    result = run_core_command(request, **kwargs)
    if command in {"identify", "verify"}:
        result = _with_diagnostic_live_support(command, runtime, result)
    if command == "ramp-list" and result.get("status") == "stopped":
        failed = result.get("failed_segment") or {}
        raise CommandCancelled(f"ramp-list stopped at segment {failed.get('index')}")
    if command == "ramp-list" and result.get("status") == "failed":
        failed = result.get("failed_segment") or {}
        raise CoreExecutionError(
            f"ramp-list segment {failed.get('index')} failed: {failed.get('message', 'segment failed')}",
            trigger=failed.get("trigger"),
            data=result,
        )
    if command == "sequence" and result.get("status") == "failed":
        failed = result.get("failed_step") or {}
        raise CoreExecutionError(
            f"sequence step {failed.get('index')} failed: {failed.get('message', 'step failed')}",
            trigger=failed.get("trigger"),
            data=result,
        )
    return result


def _with_diagnostic_live_support(
    command: str,
    runtime: RuntimeOptions,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Attach safe exact-scope metadata after an exempt diagnostic reads IDN."""

    resource_data = result.get("resource")
    idn = result.get("idn")
    if not isinstance(idn, dict) and isinstance(resource_data, dict):
        idn = resource_data.get("idn")
    manufacturer = idn.get("manufacturer") if isinstance(idn, dict) else None
    model = idn.get("model") if isinstance(idn, dict) else None
    if not isinstance(model, str) or not model.strip():
        return result
    try:
        identity = resolve_physical_model_identity(manufacturer, model)
    except IdentityResolutionError:
        if not runtime.simulate:
            validate_live_expected_model(
                runtime.expected_model_id,
                None,
                command=command,
            )
        live_support = _unsupported_detected_model_live_support(
            manufacturer,
            model,
            runtime,
        )
        return {**result, "live_support": live_support}
    if runtime.simulate:
        live_support = _unevaluated_live_support(
            model_id=identity.model_id,
            reported_manufacturer=manufacturer,
            reported_model=model,
            runtime=runtime,
        )
    else:
        validate_live_expected_model(
            runtime.expected_model_id,
            identity.model_id,
            command=command,
        )
        try:
            live_support = exact_live_support_metadata(
                model_id=identity.model_id,
                resource=runtime.resource,
                backend=runtime.backend,
            )
        except LiveSupportPolicyError:
            live_support = _unsupported_detected_model_live_support(
                manufacturer,
                model,
                runtime,
            )
    return {**result, "live_support": live_support}


def _unevaluated_live_support(
    *,
    model_id: str | None,
    reported_manufacturer: str | None,
    reported_model: str | None,
    runtime: RuntimeOptions,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "evaluated": False,
        "model_id": model_id,
        "reported_manufacturer": reported_manufacturer,
        "reported_model": reported_model,
        "transport_scope": normalize_transport(runtime.resource),
        "backend_scope": normalize_backend(runtime.backend),
        "policy_mode": SUPPORT_POLICY_MODE_PRODUCT,
        "commands": {},
        "reason": "Live exact-scope policy applies to real hardware only.",
    }


def _unsupported_detected_model_live_support(
    reported_manufacturer: str | None,
    reported_model: str | None,
    runtime: RuntimeOptions,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "evaluated": False,
        "model_id": None,
        "reported_manufacturer": reported_manufacturer,
        "reported_model": reported_model,
        "transport_scope": normalize_transport(runtime.resource),
        "backend_scope": normalize_backend(runtime.backend),
        "policy_mode": SUPPORT_POLICY_MODE_PRODUCT,
        "commands": {},
        "reason": (
            "The reported manufacturer and model do not resolve to active "
            "exact live-support metadata."
        ),
    }


def execute_live_readonly(command: str, runtime: RuntimeOptions, parameters: dict[str, Any]) -> dict[str, Any]:
    if command not in {"measure", "measure-all", "read-status", "readback", "protection-status", "snapshot"}:
        raise CoreValidationError(f"live data command is not read-only: {command}")
    request = _request_for_job(command, runtime, parameters)
    return run_core_command(request)


def execute_live_panel_read(runtime: RuntimeOptions, parameters: dict[str, Any]) -> dict[str, Any]:
    request = OperationRequest(command="live-panel", runtime=runtime, parameters=_normalize_parameters(parameters))
    return run_live_panel_read(request)


def _request_for_job(command: str, runtime: RuntimeOptions, parameters: dict[str, Any]) -> OperationRequest | TriggerRequest | SequenceRequest:
    normalized_parameters = _normalize_parameters(parameters)
    if command in TRIGGER_COMMANDS:
        return TriggerRequest(command=command, runtime=runtime, parameters=normalized_parameters)
    if command == "sequence":
        return SequenceRequest(command=command, runtime=runtime, parameters=normalized_parameters)
    return OperationRequest(command=command, runtime=runtime, parameters=normalized_parameters)


def webui_command_support_by_model_id(
    command_names: set[str],
    metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return model-aware support metadata for visible WebUI commands."""

    return {
        model_id: _webui_support_from_core_metadata(model_id, entry, command_names)
        for model_id, entry in (
            metadata or product_active_model_metadata(command_names)
        ).items()
    }


def _webui_support_from_core_metadata(
    model_id: str,
    metadata: dict[str, Any],
    command_names: set[str],
) -> dict[str, dict[str, Any]]:
    support = {
        command: dict(entry)
        for command, entry in metadata["command_support"].items()
        if command in command_names
    }
    for command, entry in support.items():
        if entry.get("real") is False:
            entry["disabled_reason"] = core_capabilities.unsupported_command_reason(
                command, model_id
            )
    for command in sorted(command_names & EXEMPT_LIVE_DIAGNOSTIC_COMMANDS):
        support[command] = {
            "real": True,
            "simulate": True,
            "dry_run": False,
            "requires_confirm": False,
            "hardware_validation": "model_independent",
        }
    return support


def _serial_options_from_runtime(runtime_dict: dict[str, Any]) -> SerialOptions | None:
    serial = runtime_dict.get("serial_options")
    if serial is None:
        return None
    if not isinstance(serial, dict):
        raise TypeError("runtime.serial_options must be an object or null")
    supported = {
        "baud_rate", "data_bits", "parity", "stop_bits", "flow_control",
        "read_termination", "write_termination",
    }
    unknown = sorted(set(serial) - supported)
    if unknown:
        raise ValueError(f"unknown runtime.serial_options field(s): {', '.join(unknown)}")
    baud_rate = _strict_optional_int(serial, "baud_rate")
    data_bits = _strict_optional_int(serial, "data_bits")
    if baud_rate is not None and baud_rate < 1:
        raise ValueError("runtime.serial_options.baud_rate must be positive")
    if data_bits is not None and data_bits not in {5, 6, 7, 8}:
        raise ValueError("runtime.serial_options.data_bits must be 5, 6, 7, or 8")
    parity = _strict_serial_string(serial, "parity")
    flow_control = _strict_serial_string(serial, "flow_control")
    read_termination = _strict_serial_string(serial, "read_termination")
    write_termination = _strict_serial_string(serial, "write_termination")
    stop_bits = serial.get("stop_bits")
    if stop_bits is not None:
        if isinstance(stop_bits, bool) or not isinstance(stop_bits, (int, float, str)):
            raise TypeError("runtime.serial_options.stop_bits must be a number, string, or null")
        if str(stop_bits).strip() not in {"1", "1.0", "1.5", "2", "2.0"}:
            raise ValueError("serial stop bits must be 1, 1.5, or 2")
    if parity is not None and parity.strip().lower() not in {
        "none", "n", "odd", "o", "even", "e", "mark", "m", "space", "s",
    }:
        raise ValueError("serial parity must be none, odd, even, mark, or space")
    if flow_control is not None and flow_control.strip().lower().replace("-", "_") not in {
        "none", "xon_xoff", "xonxoff", "rts_cts", "rtscts", "dtr_dsr", "dtrdsr",
    }:
        raise ValueError("serial flow control must be none, xon_xoff, rts_cts, or dtr_dsr")
    options = SerialOptions(
        baud_rate=baud_rate,
        data_bits=data_bits,
        parity=parity,
        stop_bits=stop_bits,
        flow_control=flow_control,
        read_termination=normalize_serial_termination(read_termination),
        write_termination=normalize_serial_termination(write_termination),
    )
    return options if options.has_explicit_values() else None


def _optional_runtime_bool(runtime: dict[str, Any], field: str, default: bool) -> bool:
    if field not in runtime:
        return default
    value = runtime[field]
    if not isinstance(value, bool):
        raise TypeError(f"runtime.{field} must be a boolean")
    return value


def _optional_runtime_string(runtime: dict[str, Any], field: str) -> str | None:
    value = runtime.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"runtime.{field} must be a string or null")
    return value


def _optional_identity_string(runtime: dict[str, Any], field: str) -> str | None:
    value = _optional_runtime_string(runtime, field)
    if value is not None and not value.strip():
        raise ValueError(f"runtime.{field} must be a non-empty string")
    return value


def _runtime_timeout_ms(runtime: dict[str, Any]) -> int:
    value = runtime.get("timeout_ms", 5000)
    if type(value) is not int or not 1 <= value <= 600000:
        raise ValueError("runtime.timeout_ms must be an integer from 1 to 600000")
    return value


def _strict_optional_int(values: dict[str, Any], field: str) -> int | None:
    value = values.get(field)
    if value is None:
        return None
    if type(value) is not int:
        raise TypeError(f"runtime.serial_options.{field} must be an integer or null")
    return value


def _strict_serial_string(values: dict[str, Any], field: str) -> str | None:
    value = values.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"runtime.serial_options.{field} must be a string or null")
    return value


def _normalize_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    return dict(parameters)


def _requires_real_confirmation(command: str, runtime: RuntimeOptions) -> bool:
    return command in MUTATING_COMMANDS and not runtime.simulate and not runtime.dry_run and not runtime.confirm


def _capabilities(runtime: RuntimeOptions) -> dict[str, Any]:
    from powers_tool_core.setpoint_ranges import (
        setpoint_ranges_for_model_id,
    )

    if runtime.resource:
        manager = SimulatedResourceManager() if runtime.simulate else None
        try:
            with open_resource(
                runtime.resource,
                manager,
                backend=runtime.backend,
                timeout_ms=runtime.timeout_ms,
                serial_options=runtime.serial_options,
                serial_remote=runtime.serial_remote,
                serial_local_on_close=runtime.serial_local_on_close,
            ) as instrument:
                idn_raw = instrument.query(IDN_QUERY)
                if not runtime.simulate:
                    enforce_product_live_support_for_idn(
                        OperationRequest(command="capabilities", runtime=runtime), idn_raw
                    )
        except VisaConnectionError as exc:
            raise CoreValidationError(f"capabilities failed: {exc}") from exc

        selection = select_driver(idn_raw)
        caps = selection.capabilities
        live_support = (
            _unevaluated_live_support(
                model_id=(
                    selection.physical_identity.model_id
                    if selection.physical_identity is not None
                    else None
                ),
                reported_manufacturer=selection.idn.manufacturer,
                reported_model=selection.idn.model,
                runtime=runtime,
            )
            if runtime.simulate
            else exact_live_support_metadata(
                model_id=selection.physical_identity.model_id,
                resource=runtime.resource,
                backend=runtime.backend,
            )
        )
        return {
            "resource": resource_payload(
                runtime.resource,
                simulated=runtime.simulate,
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
            "hardware_validation": core_capabilities.hardware_validation_status(
                selection.physical_identity.model_id if selection.physical_identity else None
            ),
            "command_support": core_capabilities.command_support(
                selection.physical_identity.model_id if selection.physical_identity else None
            ),
            "live_support": live_support,
            "electrical_ratings": caps.electrical_ratings.to_dict() if caps.electrical_ratings else None,
            "setpoint_ranges": (
                setpoint_ranges_for_model_id(selection.physical_identity.model_id).to_dict()
                if selection.physical_identity
                and setpoint_ranges_for_model_id(selection.physical_identity.model_id)
                else None
            ),
        }

    return {
        "models": {
            model_id: {
                "channels": entry["channels"],
                "electrical_ratings": entry["electrical_ratings"],
                "setpoint_ranges": entry["setpoint_ranges"],
            }
            for model_id, entry in product_active_model_metadata(()).items()
        }
    }


def _safety_inspect(runtime: RuntimeOptions) -> dict[str, Any]:
    if runtime.safety_config is None:
        return {"safety_config_loaded": False}
    from powers_tool_core.safety import resolve_safety_config

    config = resolve_safety_config(
        runtime.safety_config,
        resource=None if runtime.resource_alias is not None else runtime.resource,
        resource_alias=runtime.resource_alias,
    )
    return {
        "safety_config_loaded": True,
        "limits": {
            "max_voltage": config.limits.max_voltage,
            "max_current": config.limits.max_current,
            "allowed_channels": list(config.limits.allowed_channels),
        },
    }
