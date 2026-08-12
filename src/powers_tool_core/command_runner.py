"""Core command-routing integration boundary for bundled adapters.

``validate_request_admission()`` and ``run_core_command()`` are adapter-facing
Core integration entry points used by the bundled CLI, Worker, and WebUI
adapters. They accept parser-neutral Core request objects and keep
serialization and presentation at the adapter boundary. Helpers prefixed with
``_``, including ``_run_*_admitted``, are Core-internal handoffs for already
admitted requests and are not stable adapter APIs.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any, Callable

from powers_tool_core import capabilities
from powers_tool_core.core import CoreValidationError, OperationRequest, SequenceRequest, TriggerRequest
from powers_tool_core.discovery import run_discovery
from powers_tool_core.instrument_io import run_instrument_io
from powers_tool_core.model_resolution import no_hardware_channels, resolve_no_hardware_runtime
from powers_tool_core.operations import run_operation
from powers_tool_core.command_contract import validate_and_normalize_request
from powers_tool_core.parameter_constraints import validate_request_parameters
from powers_tool_core.protection import run_protection
from powers_tool_core.ramp_list import run_ramp_list
from powers_tool_core.readonly import run_readonly
from powers_tool_core.restore import run_restore
from powers_tool_core.sequence import run_sequence
from powers_tool_core.snapshot import run_snapshot
from powers_tool_core.telemetry import SampleReporter, run_telemetry
from powers_tool_core.trigger import run_trigger
from powers_tool_core.stop_cleanup import CleanupReporter, stop_aware_opener
from powers_tool_core.workflow_validation import ProgressReporter, validate_general_workflow_parameters


def validate_request_admission(
    request: OperationRequest | TriggerRequest | SequenceRequest,
) -> OperationRequest | TriggerRequest | SequenceRequest:
    """Admit and canonicalize a request for the bundled adapter boundary.

    Performs admission and canonicalization without hardware, VISA, or SCPI
    I/O and without device-state mutation. File-backed requests may perform
    local filesystem I/O during one-time materialization.
    """

    request = validate_and_normalize_request(request)
    validate_request_parameters(request)
    if isinstance(request, OperationRequest):
        validate_general_workflow_parameters(request)
        if request.command == "ramp":
            _ramp_execution_summary(request)
    if isinstance(request, TriggerRequest) or request.command.startswith("trigger-"):
        from powers_tool_core.trigger import validate_trigger_request

        validate_trigger_request(request)
        if request.command == "trigger-list":
            missing = [
                name for name in ("channel", "voltages", "currents", "dwell")
                if name not in request.parameters
            ]
            if missing:
                raise CoreValidationError(
                    "trigger-list requires " + ", ".join(missing)
                )

    if isinstance(request, SequenceRequest) or request.command == "sequence":
        from powers_tool_core.sequence import load_sequence_document, sequence_plan
        from powers_tool_core.support_features import sequence_feature_requirements

        document = request.parameters.get("document")
        if document is None and request.parameters.get("file") is not None:
            document = load_sequence_document(str(request.parameters["file"]))
        if document is None:
            raise CoreValidationError("sequence requires file or document")
        if not isinstance(document, dict):
            raise CoreValidationError("sequence document must be an object")
        canonical_parameters = {
            key: value for key, value in request.parameters.items() if key not in {"file", "document"}
        }
        request = replace(request, parameters={**canonical_parameters, "document": deepcopy(document)})
        if (request.runtime.dry_run or request.runtime.simulate) and any(
            isinstance(step, dict)
            and (step.get("action") == "trigger-pulse" or step.get("type") == "trigger-pulse")
            for step in request.parameters["document"].get("steps", [])
        ):
            request = _apply_no_hardware_support_gate(request)
        plan = sequence_plan(request, request.parameters["document"])
        if (request.runtime.dry_run or request.runtime.simulate) and sequence_feature_requirements(plan):
            sequence_plan(request, request.parameters["document"])
        return request

    if request.command == "restore-from-snapshot":
        from powers_tool_core.restore import validate_restore_admission

        assert isinstance(request, OperationRequest)
        request = validate_restore_admission(request)
    else:
        request = _apply_no_hardware_support_gate(request)

    if request.command == "ramp" and (request.runtime.dry_run or request.runtime.simulate):
        request = _canonicalize_no_hardware_ramp_channels(request)

    if request.command == "ramp-list":
        from powers_tool_core.ramp_list import ramp_list_document_for_request, ramp_list_plan

        document = ramp_list_document_for_request(request)
        request = replace(
            request,
            parameters={
                **{key: value for key, value in request.parameters.items() if key not in {"file", "document"}},
                "document": deepcopy(document),
            },
        )
        ramp_list_plan(request, request.parameters["document"])
    return request


def _canonicalize_no_hardware_ramp_channels(
    request: OperationRequest | TriggerRequest | SequenceRequest,
) -> OperationRequest | TriggerRequest | SequenceRequest:
    selected = request.parameters.get("channels")
    if selected is None:
        return request
    supported = no_hardware_channels(
        request.runtime.planning_model_id,
        request.runtime.planning_profile_id,
    )
    unsupported = tuple(channel for channel in selected if channel not in supported)
    if unsupported:
        raise CoreValidationError(
            f"ramp channels {unsupported} are not supported; supported: {supported}"
        )
    canonical = tuple(channel for channel in supported if channel in selected)
    return replace(request, parameters={**request.parameters, "channels": canonical})


def workflow_execution_summary(
    request: OperationRequest | TriggerRequest | SequenceRequest,
) -> dict[str, Any] | None:
    """Return Core-owned logical work metadata for an admitted workflow."""

    request = validate_request_admission(request)
    if request.command == "ramp":
        return _ramp_execution_summary(request)
    if request.command == "ramp-list":
        from powers_tool_core.ramp_list import ramp_list_plan

        plan = ramp_list_plan(request, request.parameters["document"])
        return {
            "execution_units": plan["execution_units"],
            "execution_warning": plan["execution_warning"],
        }
    if request.command == "sequence":
        from powers_tool_core.sequence import sequence_plan

        plan = sequence_plan(request, request.parameters["document"])
        return {
            "execution_units": plan["execution_units"],
            "execution_warning": plan["execution_warning"],
        }
    return None


def _ramp_execution_summary(request: OperationRequest) -> dict[str, Any]:
    from powers_tool_core.operations import ramp_voltages
    from powers_tool_core.workflow_validation import (
        execution_warning,
        normalize_loop_count,
        validate_execution_units,
    )

    loop_count = normalize_loop_count(request.parameters.get("loop_count", 1))
    units = validate_execution_units(
        loop_count,
        len(
            ramp_voltages(
                request.parameters["start_voltage"],
                request.parameters["stop_voltage"],
                request.parameters["step_voltage"],
            )
        ),
        workflow="Ramp",
        reduction_hint="Ramp steps",
    )
    return {
        "execution_units": units,
        "execution_warning": execution_warning(
            units, reduction_hint="Ramp steps"
        ),
    }


def run_core_command(
    request: OperationRequest | TriggerRequest | SequenceRequest,
    *,
    opener: Callable[..., Any] | None = None,
    resource_lister: Callable[..., tuple[str, ...]] | None = None,
    stop_requested: Callable[[], bool] | None = None,
    sleep: Callable[[float], None] | None = None,
    scpi_logger: Callable[[str, str, str], None] | None = None,
    cleanup_reporter: CleanupReporter | None = None,
    progress_reporter: ProgressReporter | None = None,
    sample_reporter: SampleReporter | None = None,
) -> dict[str, Any]:
    """Admit and execute a parser-neutral request for bundled adapters.

    This adapter-facing Core integration entry point re-admits the request
    before dispatch; adapters retain serialization and presentation
    responsibility.
    """

    request = validate_request_admission(request)
    command = request.command
    if stop_requested is not None and command != "log":
        opener = stop_aware_opener(
            opener or _default_opener,
            stop_requested=stop_requested,
            simulated=request.runtime.simulate,
            reporter=cleanup_reporter,
        )
    if isinstance(request, SequenceRequest) or command == "sequence":
        kwargs: dict[str, Any] = {
            "stop_requested": stop_requested,
            "scpi_logger": scpi_logger,
            "cleanup_reporter": cleanup_reporter,
            "progress_reporter": progress_reporter,
        }
        if opener is not None:
            kwargs["opener"] = opener
        if sleep is not None:
            kwargs["sleep"] = sleep
        from powers_tool_core.sequence import _run_sequence_admitted

        return _run_sequence_admitted(request, **kwargs)
    if command == "ramp-list":
        kwargs = {
            "stop_requested": stop_requested,
            "scpi_logger": scpi_logger,
            "cleanup_reporter": cleanup_reporter,
            "progress_reporter": progress_reporter,
        }
        if opener is not None:
            kwargs["opener"] = opener
        if sleep is not None:
            kwargs["sleep"] = sleep
        from powers_tool_core.ramp_list import _run_ramp_list_admitted

        return _run_ramp_list_admitted(request, **kwargs)
    if isinstance(request, TriggerRequest) or command.startswith("trigger-"):
        kwargs = {"stop_requested": stop_requested, "scpi_logger": scpi_logger}
        if opener is not None:
            kwargs["opener"] = opener
        return run_trigger(request, **kwargs)
    if command in {"list-resources", "verify"}:
        kwargs = {"scpi_logger": scpi_logger}
        if opener is not None:
            kwargs["opener"] = opener
        if resource_lister is not None:
            kwargs["resource_lister"] = resource_lister
        return run_discovery(request, **kwargs)
    if command in {"clear", "error", "measure", "identify"}:
        kwargs = {"scpi_logger": scpi_logger}
        if opener is not None:
            kwargs["opener"] = opener
        return run_instrument_io(request, **kwargs)
    if command in {"protection-status", "protection-set", "clear-protection"}:
        kwargs = {"scpi_logger": scpi_logger}
        if opener is not None:
            kwargs["opener"] = opener
        return run_protection(request, **kwargs)
    if command == "snapshot":
        kwargs = {"scpi_logger": scpi_logger}
        if opener is not None:
            kwargs["opener"] = opener
        return run_snapshot(request, **kwargs)
    if command == "restore-from-snapshot":
        kwargs = {
            "scpi_logger": scpi_logger,
            "stop_requested": stop_requested,
        }
        if opener is not None:
            kwargs["opener"] = opener
        from powers_tool_core.restore import _run_restore_admitted

        return _run_restore_admitted(request, **kwargs)
    if command in {"read-status", "readback", "measure-all"}:
        kwargs = {"scpi_logger": scpi_logger}
        if opener is not None:
            kwargs["opener"] = opener
        return run_readonly(request, **kwargs)
    if command == "log":
        kwargs = {
            "stop_requested": stop_requested,
            "scpi_logger": scpi_logger,
            "sample_reporter": sample_reporter,
            "progress_reporter": progress_reporter,
        }
        if opener is not None:
            kwargs["opener"] = opener
        if sleep is not None:
            kwargs["sleep"] = sleep
        return run_telemetry(request, **kwargs)
    if command in {"set", "apply", "output-on", "output-off", "safe-off", "output-state", "cycle-output", "ramp", "smoke-output"}:
        kwargs = {
            "scpi_logger": scpi_logger,
            "stop_requested": stop_requested,
            "cleanup_reporter": cleanup_reporter,
            "progress_reporter": progress_reporter,
        }
        if opener is not None:
            kwargs["opener"] = opener
        if sleep is not None:
            kwargs["sleep"] = sleep
        return run_operation(request, **kwargs)
    raise CoreValidationError(f"unsupported core command {command!r}")


def _apply_no_hardware_support_gate(
    request: OperationRequest | TriggerRequest | SequenceRequest,
) -> OperationRequest | TriggerRequest | SequenceRequest:
    if not (request.runtime.dry_run or request.runtime.simulate):
        return request
    if request.command not in capabilities.known_capability_commands():
        return request
    runtime = resolve_no_hardware_runtime(request.runtime)
    mode = "dry_run" if runtime.dry_run else "simulate"
    capabilities.ensure_command_supported(
        request.command,
        runtime.planning_model_id,
        runtime.planning_profile_id,
        mode,
    )
    return replace(request, runtime=runtime)


def _default_opener(*args: Any, **kwargs: Any) -> Any:
    from powers_tool_core.connection import open_resource

    return open_resource(*args, **kwargs)
