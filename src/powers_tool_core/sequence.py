"""Parser-neutral sequence lint, dry-run, and execution core."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from powers_tool_core.cancellation import interruptible_sleep, raise_if_cancelled
from powers_tool_core.connection import open_resource
from powers_tool_core.core import CommandCancelled, CoreExecutionError, CoreIoError, CoreValidationError, SequenceRequest
from powers_tool_core.drivers.e36312a import E36312APowerSupply
from powers_tool_core.drivers.edu36311a import EDU36311APowerSupply
from powers_tool_core.drivers.e3646a import E3646APowerSupply
from powers_tool_core.drivers.psm2010 import PSM2010PowerSupply
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import create_power_supply
from powers_tool_core.model_resolution import (
    no_hardware_channels,
    resolve_no_hardware_runtime,
)
from powers_tool_core.live_support import enforce_live_support_for_idn
from powers_tool_core.safety import SafetyConfigError, SafetyLimits, SafetyValidationError, resolve_safety_config, validate_channel, validate_setpoint
from powers_tool_core.setpoint_limits import validate_effective_setpoint
from powers_tool_core.stop_cleanup import CleanupReporter, cancel_workflow_with_safe_off
from powers_tool_core.support_features import (
    SEQUENCE_ACTIONS,
    sequence_feature_requirements,
    supported_sequence_actions_for_model_id,
)
from powers_tool_core.trigger import run_post_action_completion_pulse, trigger_pulse_scpi
from powers_tool_core.workflow_validation import (
    BoundedResultDetails,
    ExecutionProgress,
    ProgressReporter,
    execution_warning,
    normalize_loop_count,
    validate_execution_units,
)
from powers_tool_core.command_contract import validate_sequence_action_parameters

IDN_QUERY = "*IDN?"
OUTPUT_WRITE_POWER_SUPPLY_TYPES = (
    E36312APowerSupply,
    E3646APowerSupply,
    EDU36311APowerSupply,
    PSM2010PowerSupply,
)
SEQUENCE_OUTPUT_ACTIONS = {"safe-off", "set", "output-on", "output-off", "cycle-output", "apply", "trigger-pulse"}


def run_sequence(
    request: SequenceRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    sleep: Callable[[float], None] = time.sleep,
    scpi_logger: Callable[[str, str, str], None] | None = None,
    stop_requested: Callable[[], bool] | None = None,
    cleanup_reporter: CleanupReporter | None = None,
    progress_reporter: ProgressReporter | None = None,
) -> dict[str, Any]:
    """Lint, plan, or execute a sequence request."""

    # Public Core entry points must offer the same fail-closed admission as
    # adapter routing.  The internal runner receives an already materialized
    # document and never reopens a user-provided path.
    from powers_tool_core.command_runner import validate_request_admission

    return _run_sequence_admitted(
        validate_request_admission(request),
        opener=opener,
        sleep=sleep,
        scpi_logger=scpi_logger,
        stop_requested=stop_requested,
        cleanup_reporter=cleanup_reporter,
        progress_reporter=progress_reporter,
    )


def _run_sequence_admitted(
    request: SequenceRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    sleep: Callable[[float], None] = time.sleep,
    scpi_logger: Callable[[str, str, str], None] | None = None,
    stop_requested: Callable[[], bool] | None = None,
    cleanup_reporter: CleanupReporter | None = None,
    progress_reporter: ProgressReporter | None = None,
) -> dict[str, Any]:
    """Execute one admitted Sequence request without source-file fallback."""

    planning_resolved = False
    if request.runtime.dry_run or request.runtime.simulate:
        try:
            request = replace(request, runtime=resolve_no_hardware_runtime(request.runtime))
            planning_resolved = True
        except CoreValidationError as exc:
            if "planning require planning_model_id" not in str(exc):
                raise
    document = request.parameters.get("document")
    if not isinstance(document, dict):
        raise CoreValidationError("admitted sequence requires document")

    plan = sequence_plan(request, document)
    if sequence_feature_requirements(plan) and not planning_resolved:
        request = replace(request, runtime=resolve_no_hardware_runtime(request.runtime))
        plan = sequence_plan(request, document)

    if request.parameters.get("lint", False):
        return {
            "status": "valid",
            "sequence_version": plan["version"],
            "step_count": len(plan["steps"]),
            "loop_count": plan["loop_count"],
            "completed_loops": 0,
            "completed_steps": 0,
            "completed_step_executions": 0,
            "plan": plan,
        }

    if request.runtime.dry_run:
        add_sequence_scpi_previews(plan)
        return {
            "sequence_version": plan["version"],
            "resource": request.runtime.resource,
            "resource_alias": request.runtime.resource_alias,
            "plan": plan,
            "status": "planned",
            "step_count": len(plan["steps"]),
            "loop_count": plan["loop_count"],
            "completed_loops": 0,
            "completed_steps": 0,
            "completed_step_executions": 0,
            "failed_step": None,
            "stopped": False,
            "cleanup": {"safe_off_attempted": False, "errors": []},
        }

    return execute_sequence(
        request,
        plan,
        opener=opener,
        sleep=sleep,
        scpi_logger=scpi_logger,
        stop_requested=stop_requested,
        cleanup_reporter=cleanup_reporter,
        progress_reporter=progress_reporter,
    )


def load_sequence_document(path: str) -> dict[str, Any]:
    sequence_path = Path(path)
    try:
        text = sequence_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"could not read sequence file {sequence_path}: {exc}") from exc
    stripped = text.lstrip()
    if stripped.startswith("{"):
        parsed = json.loads(text)
    else:
        try:
            import yaml  # type: ignore[import-untyped]
        except ModuleNotFoundError:
            parsed = parse_simple_sequence_yaml(text)
        else:
            parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise CoreValidationError("sequence file must contain a mapping")
    return parsed


def parse_simple_sequence_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_steps = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", maxsplit=1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped == "steps:":
            in_steps = True
            data["steps"] = steps
            continue
        if not in_steps:
            if ":" not in stripped:
                raise CoreValidationError(f"unsupported sequence YAML line: {raw_line}")
            key, value = stripped.split(":", maxsplit=1)
            data[key.strip()] = _parse_sequence_scalar(value.strip())
            continue
        if stripped.startswith("- "):
            current = {}
            steps.append(current)
            item = stripped[2:].strip()
            if item:
                if ":" not in item:
                    current["action"] = item
                else:
                    key, value = item.split(":", maxsplit=1)
                    current[key.strip()] = _parse_sequence_scalar(value.strip())
            continue
        if current is None or ":" not in stripped:
            raise CoreValidationError(f"unsupported sequence YAML line: {raw_line}")
        key, value = stripped.split(":", maxsplit=1)
        current[key.strip()] = _parse_sequence_scalar(value.strip())
    return data


def sequence_plan(request: SequenceRequest, document: dict[str, Any]) -> dict[str, Any]:
    version = document.get("version", 1)
    if not (version == "1" or type(version) is int and version in (1, 2)):
        raise CoreValidationError(f"unsupported sequence version: {version}")
    allowed_fields = {"version", "steps"} if version in (1, "1") else {"version", "steps", "loop_count"}
    unknown = sorted(set(document) - allowed_fields)
    if unknown:
        raise CoreValidationError(f"sequence contains unsupported field(s): {', '.join(unknown)}")
    if version == 2 and "loop_count" not in document:
        raise CoreValidationError("sequence version 2 requires loop_count")
    document_loop_count = (
        normalize_loop_count(document["loop_count"], field="sequence loop_count")
        if version == 2
        else 1
    )
    override = request.parameters.get("loop_count")
    loop_count = (
        normalize_loop_count(override, field="sequence loop_count")
        if override is not None
        else document_loop_count
    )
    raw_steps = document.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise CoreValidationError("sequence requires a non-empty steps list")
    steps = []
    for index, raw_step in enumerate(raw_steps, start=1):
        step = normalize_sequence_step(index, raw_step)
        validate_sequence_step(request, step)
        steps.append(step)
    execution_units = validate_execution_units(
        loop_count,
        len(steps),
        workflow="Sequence",
        reduction_hint="Sequence steps",
    )
    return {
        "version": 2 if version == 2 or override is not None else 1,
        "loop_count": loop_count,
        "execution_units": execution_units,
        "execution_warning": execution_warning(
            execution_units, reduction_hint="Sequence steps"
        ),
        "operation": {"name": "sequence"},
        "target": {
            "resource": request.runtime.resource,
            "resource_alias": request.runtime.resource_alias,
            "planning_model_id": request.runtime.planning_model_id,
            "planning_profile_id": request.runtime.planning_profile_id,
        },
        "steps": steps,
        "hardware_touched": False,
    }


def add_sequence_scpi_previews(plan: dict[str, Any]) -> None:
    for step in plan["steps"]:
        preview = sequence_step_preview(
            step,
            planning_model_id=plan["target"].get("planning_model_id"),
            planning_profile_id=plan["target"].get("planning_profile_id"),
        )
        if preview:
            step["preview"] = preview


def sequence_step_preview(
    step: dict[str, Any],
    *,
    planning_model_id: str | None = None,
    planning_profile_id: str | None = None,
) -> dict[str, Any] | None:
    action = step["action"]
    parameters = step["parameters"]
    if action == "set":
        channel = sequence_channel(parameters.get("channel", 1))
        voltage = _format_text_value(parameters["voltage"])
        current = _format_text_value(parameters["current"])
        return {
            "commands": [
                _preview_scpi(f"CURR {current}", channel, planning_model_id),
                _preview_scpi(f"VOLT {voltage}", channel, planning_model_id),
            ]
        }
    if action == "apply":
        channel = sequence_channel(parameters.get("channel", 1), allow_all=True)
        voltage = _format_text_value(parameters["voltage"])
        current = _format_text_value(parameters["current"])
        commands: list[str] = []
        for selected_channel in sequence_preview_channels(channel, planning_model_id=planning_model_id, planning_profile_id=planning_profile_id):
            commands.append(_preview_scpi(f"CURR {current}", selected_channel, planning_model_id))
            commands.append(_preview_scpi(f"VOLT {voltage}", selected_channel, planning_model_id))
            if not parameters.get("no_output", False):
                commands.append(_preview_scpi("OUTP ON", selected_channel, planning_model_id))
        return {"commands": commands}
    if action == "output-on":
        channel = sequence_channel(parameters.get("channel", 1), allow_all=True)
        return {"commands": [_preview_scpi("OUTP ON", selected_channel, planning_model_id) for selected_channel in sequence_preview_channels(channel, planning_model_id=planning_model_id, planning_profile_id=planning_profile_id)]}
    if action == "output-off":
        channel = sequence_channel(parameters.get("channel", 1), allow_all=True)
        return {"commands": [_preview_scpi("OUTP OFF", selected_channel, planning_model_id) for selected_channel in sequence_preview_channels(channel, planning_model_id=planning_model_id, planning_profile_id=planning_profile_id)]}
    if action == "output-state":
        channel = sequence_channel(parameters.get("channel", 1), allow_all=True)
        return {"commands": [_preview_scpi("OUTP?", selected_channel, planning_model_id) for selected_channel in sequence_preview_channels(channel, planning_model_id=planning_model_id, planning_profile_id=planning_profile_id)]}
    if action == "cycle-output":
        channel = sequence_channel(parameters.get("channel", 1), allow_all=True)
        commands = [_preview_scpi("OUTP ON", selected_channel, planning_model_id) for selected_channel in sequence_preview_channels(channel, planning_model_id=planning_model_id, planning_profile_id=planning_profile_id)]
        commands.extend(_preview_scpi("OUTP OFF", selected_channel, planning_model_id) for selected_channel in sequence_preview_channels(channel, planning_model_id=planning_model_id, planning_profile_id=planning_profile_id))
        return {"commands": commands, "duration_ms": parameters.get("duration_ms", 500)}
    if action == "safe-off":
        channel = sequence_channel(parameters.get("channel", 1), allow_all=True)
        return {"commands": [_preview_scpi("OUTP OFF", selected_channel, planning_model_id) for selected_channel in sequence_preview_channels(channel, planning_model_id=planning_model_id, planning_profile_id=planning_profile_id)]}
    if action == "trigger-pulse":
        channel = sequence_channel(parameters.get("channel", 1))
        pins = sequence_pulse_pins(parameters.get("pins"))
        return {"commands": list(trigger_pulse_scpi(pins, parameters.get("polarity", "positive"), channel))}
    return None


def normalize_sequence_step(index: int, raw_step: Any) -> dict[str, Any]:
    if not isinstance(raw_step, dict):
        raise CoreValidationError(f"sequence step {index} must be a mapping")
    if "action" in raw_step and "type" in raw_step:
        raise CoreValidationError(f"sequence step {index} cannot contain both action and type")
    if "action" in raw_step or "type" in raw_step:
        action = raw_step.get("action", raw_step.get("type"))
        if type(action) is not str:
            raise CoreValidationError(f"sequence step {index} action must be a string")
        parameters = {key: value for key, value in raw_step.items() if key not in {"action", "type", "index"}}
    elif len(raw_step) == 1:
        action, value = next(iter(raw_step.items()))
        if not isinstance(value, dict):
            raise CoreValidationError(f"sequence step {index} shorthand {action!r} must contain an object")
        parameters = value
    else:
        raise CoreValidationError(f"sequence step {index} requires action")
    if action not in SEQUENCE_ACTIONS:
        raise CoreValidationError(f"unsupported sequence step {index} action: {action}")
    return {"index": index, "action": action, "parameters": validate_sequence_action_parameters(action, parameters)}


def validate_sequence_step(request: SequenceRequest, step: dict[str, Any]) -> None:
    action = step["action"]
    parameters = step["parameters"]
    if (
        (request.runtime.dry_run or request.runtime.simulate)
        and action == "trigger-pulse"
        and action not in supported_sequence_actions_for_model_id(
            request.runtime.planning_model_id
        )
    ):
        identity = request.runtime.planning_profile_id or request.runtime.planning_model_id
        raise CoreValidationError(f"unsupported sequence trigger-pulse for {identity}; E36312A supports this step")
    if action in {"measure", "readback", "output-state", "safe-off", "output-on", "output-off", "cycle-output"}:
        channel = sequence_channel(parameters.get("channel", 1), allow_all=(action in {"safe-off", "output-state", "output-on", "output-off", "cycle-output"}))
        _validate_no_hardware_sequence_channels(request, channel)
    if action == "trigger-pulse":
        channel = sequence_channel(parameters.get("channel", 1))
        _validate_no_hardware_sequence_channels(request, channel)
        sequence_pulse_pins(parameters.get("pins"))
        if parameters.get("polarity", "positive") not in {"positive", "negative"}:
            raise CoreValidationError("trigger-pulse polarity must be positive or negative")
    if action == "wait":
        # The centralized sequence action contract already enforces this type.
        parameters["seconds"]
    if action in {"set", "apply"}:
        channel = sequence_channel(parameters.get("channel", 1), allow_all=(action == "apply"))
        _validate_no_hardware_sequence_channels(request, channel)
        voltage = parameters["voltage"]
        current = parameters["current"]
        limits = _safety_limits(request)
        channels = _early_validation_channels(request, channel)
        try:
            for selected_channel in channels:
                validate_setpoint(channel=selected_channel, voltage=voltage, current=current, limits=limits)
        except (SafetyConfigError, SafetyValidationError) as exc:
            raise CoreValidationError(str(exc)) from exc
    elif action in {"output-on", "output-off", "cycle-output"}:
        channel = sequence_channel(parameters.get("channel", 1), allow_all=True)
        _validate_no_hardware_sequence_channels(request, channel)
        duration_ms = parameters.get("duration_ms", 500)
        if action == "cycle-output" and duration_ms < 1:
            raise CoreValidationError("cycle-output duration_ms must be at least 1")
        try:
            for selected_channel in _early_validation_channels(request, channel):
                validate_channel(selected_channel, _safety_limits(request))
        except (SafetyConfigError, SafetyValidationError) as exc:
            raise CoreValidationError(str(exc)) from exc


def execute_sequence(
    request: SequenceRequest,
    plan: dict[str, Any],
    *,
    opener: Callable[..., Any],
    sleep: Callable[[float], None],
    scpi_logger: Callable[[str, str, str], None] | None = None,
    stop_requested: Callable[[], bool] | None = None,
    cleanup_reporter: CleanupReporter | None = None,
    progress_reporter: ProgressReporter | None = None,
) -> dict[str, Any]:
    results = BoundedResultDetails[dict[str, Any]]()
    progress = ExecutionProgress(plan["execution_units"], progress_reporter)
    completed_steps = 0
    completed_step_executions = 0
    failed_step: dict[str, Any] | None = None
    stopped = False
    safe_off_attempted = False
    cleanup_errors: list[dict[str, Any]] = []
    idn_raw: str | None = None
    completed_loops = 0
    try:
        with opener(
            request.runtime.resource,
            backend=request.runtime.backend,
            timeout_ms=request.runtime.timeout_ms,
            serial_options=request.runtime.serial_options,
            serial_remote=request.runtime.serial_remote,
            serial_local_on_close=request.runtime.serial_local_on_close,
        ) as instrument:
            if request.runtime.log_scpi and scpi_logger is not None:
                instrument = ScpiLoggingSession(str(request.runtime.resource), instrument, scpi_logger)
            idn_raw = instrument.query(IDN_QUERY)
            enforce_live_support_for_idn(
                request,
                idn_raw,
                feature_requirements=sequence_feature_requirements(plan),
            )
            power_supply = create_power_supply(instrument, idn_raw)
            _preflight_sequence(request, power_supply, plan, model=_model_from_idn(idn_raw))
            for loop_index in range(1, plan["loop_count"] + 1):
                completed_steps = 0
                for step in plan["steps"]:
                    try:
                        raise_if_cancelled(stop_requested)
                        result = execute_sequence_step(request, power_supply, step, sleep=sleep, stop_requested=stop_requested)
                        if plan["loop_count"] > 1:
                            result["loop_index"] = loop_index
                        results.append(result)
                        completed_steps += 1
                        completed_step_executions += 1
                        progress.complete_unit()
                    except (CommandCancelled, KeyboardInterrupt):
                        cancel_workflow_with_safe_off(
                            power_supply,
                            partial_result={
                                "sequence_version": plan["version"],
                                "loop_count": plan["loop_count"],
                                "loop_index": loop_index,
                                "completed_loops": completed_loops,
                                "completed_steps": completed_steps,
                                "completed_step_executions": completed_step_executions,
                                "results": results.retained(),
                                **results.metadata("results"),
                                "progress": progress.snapshot(),
                                "failed_step": {
                                    "loop_index": loop_index,
                                    "index": step["index"],
                                    "action": step["action"],
                                    "code": "interrupted",
                                },
                            },
                            reporter=cleanup_reporter,
                        )
                    except (VisaConnectionError, ValueError, SafetyValidationError, CoreValidationError, CoreExecutionError) as exc:
                        failed_step = {
                            "loop_index": loop_index,
                            "index": step["index"],
                            "action": step["action"],
                            "code": "step_failed",
                            "message": str(exc),
                        }
                        if isinstance(exc, CoreExecutionError) and exc.trigger is not None:
                            failed_step["trigger"] = exc.trigger
                        break
                if failed_step is not None:
                    break
                completed_loops += 1
            if failed_step is None:
                try:
                    raise_if_cancelled(stop_requested)
                except CommandCancelled as exc:
                    cancel_workflow_with_safe_off(
                        power_supply,
                        partial_result={
                            "sequence_version": plan["version"],
                            "loop_count": plan["loop_count"],
                            "loop_index": plan["loop_count"],
                            "completed_loops": completed_loops,
                            "completed_steps": completed_steps,
                            "completed_step_executions": completed_step_executions,
                            "results": results.retained(),
                            **results.metadata("results"),
                            "progress": progress.snapshot(),
                            "failed_step": {
                                "loop_index": plan["loop_count"],
                                "code": "interrupted",
                                "message": str(exc),
                            },
                        },
                        reporter=cleanup_reporter,
                    )
            if failed_step is not None:
                cleanup = sequence_cleanup_safe_off(power_supply)
                safe_off_attempted = cleanup["safe_off_attempted"]
                cleanup_errors = cleanup["errors"]
    except VisaConnectionError as exc:
        raise CoreIoError(f"sequence failed: {exc}", opened=False) from exc

    status = "stopped" if stopped else ("failed" if failed_step is not None else "completed")
    return {
        "sequence_version": plan["version"],
        "resource": request.runtime.resource,
        "resource_alias": request.runtime.resource_alias,
        "idn": idn_raw,
        "plan": plan,
        "status": status,
        "results": results.retained(),
        **results.metadata("results"),
        "execution_units": plan["execution_units"],
        "progress": progress.snapshot(),
        "step_count": len(plan["steps"]),
        "completed_steps": completed_steps,
        "loop_count": plan["loop_count"],
        "completed_loops": completed_loops,
        "completed_step_executions": completed_step_executions,
        "failed_step": failed_step,
        "stopped": stopped,
        "cleanup": {"safe_off_attempted": safe_off_attempted, "errors": cleanup_errors},
    }


class ScpiLoggingSession:
    def __init__(self, resource: str, session: Any, logger: Callable[[str, str, str], None]) -> None:
        self._resource = resource
        self._session = session
        self._logger = logger

    def write(self, command: str) -> Any:
        self._logger(self._resource, ">>", command)
        return self._session.write(command)

    def query(self, command: str) -> str:
        self._logger(self._resource, ">>", command)
        response = self._session.query(command)
        self._logger(self._resource, "<<", response)
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


def execute_sequence_step(
    request: SequenceRequest,
    power_supply: Any,
    step: dict[str, Any],
    *,
    sleep: Callable[[float], None],
    stop_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    action = step["action"]
    parameters = step["parameters"]
    if action in SEQUENCE_OUTPUT_ACTIONS and not request.runtime.simulate and not isinstance(power_supply, OUTPUT_WRITE_POWER_SUPPLY_TYPES):
        raise CoreValidationError("real output-affecting sequence steps are enabled only for E36312A, E3646A, EDU36311A, or PSM-2010")
    if action in {"measure", "readback"}:
        _validate_read_only_channel(power_supply, sequence_channel(parameters.get("channel", 1)), command_label="sequence")
    if action == "output-state":
        channel = sequence_channel(parameters.get("channel", 1), allow_all=True)
        for selected_channel in sequence_channels(channel, getattr(power_supply.capabilities, "real_measure_channels", power_supply.capabilities.channels)):
            _validate_read_only_channel(power_supply, selected_channel, command_label="sequence")
    if action == "measure":
        channel = sequence_channel(parameters.get("channel", 1))
        return {
            "index": step["index"],
            "action": action,
            "channel": channel,
            "measurements": {
                "voltage": power_supply.measure_voltage(channel=channel),
                "current": power_supply.measure_current(channel=channel),
            },
        }
    if action == "readback":
        channel = sequence_channel(parameters.get("channel", 1))
        return {
            "index": step["index"],
            "action": action,
            "channel": channel,
            "setpoints": {
                "voltage": power_supply.programmed_voltage(channel=channel),
                "current": power_supply.programmed_current(channel=channel),
            },
        }
    if action == "output-state":
        channel = sequence_channel(parameters.get("channel", 1), allow_all=True)
        outputs = [
            {"channel": selected_channel, "enabled": power_supply.output_state(channel=selected_channel)}
            for selected_channel in sequence_channels(channel, getattr(power_supply.capabilities, "real_measure_channels", power_supply.capabilities.channels))
        ]
        result = {"index": step["index"], "action": action, "channel": channel, "enabled": outputs[0]["enabled"]}
        if channel == "all":
            result["outputs"] = outputs
        return result
    if action == "log":
        return {"index": step["index"], "action": action, "message": parameters.get("message", "")}
    if action == "wait":
        seconds = parameters["seconds"]
        interruptible_sleep(seconds, sleep=sleep, stop_requested=stop_requested)
        return {"index": step["index"], "action": action, "seconds": seconds}
    if action == "trigger-pulse":
        if not isinstance(power_supply, E36312APowerSupply):
            raise CoreValidationError("sequence trigger-pulse is only supported for E36312A")
        channel = sequence_channel(parameters.get("channel", 1))
        trigger = run_post_action_completion_pulse(
            power_supply,
            channel=channel,
            pins=sequence_pulse_pins(parameters.get("pins")),
            polarity=parameters.get("polarity", "positive"),
            leave_configured=parameters.get("leave_trigger_configured", False),
        )
        return {"index": step["index"], "action": action, "channel": channel, "trigger": trigger}
    if action == "safe-off":
        channel = sequence_channel(parameters.get("channel", 1), allow_all=True)
        for selected_channel in sequence_channels(channel, power_supply.capabilities.channels):
            power_supply.output_off(channel=selected_channel)
        return {"index": step["index"], "action": action, "channel": channel}
    if action == "output-off":
        channel = sequence_channel(parameters.get("channel", 1), allow_all=True)
        for selected_channel in sequence_channels(channel, power_supply.capabilities.channels):
            power_supply.output_off(channel=selected_channel)
        return {"index": step["index"], "action": action, "channel": channel}
    if action == "output-on":
        channel = sequence_channel(parameters.get("channel", 1), allow_all=True)
        for selected_channel in sequence_channels(channel, power_supply.capabilities.channels):
            power_supply.output_on(channel=selected_channel)
        return {"index": step["index"], "action": action, "channel": channel}
    if action == "cycle-output":
        channel = sequence_channel(parameters.get("channel", 1), allow_all=True)
        channels = sequence_channels(channel, power_supply.capabilities.channels)
        enabled_channels: list[int] = []
        try:
            for selected_channel in channels:
                raise_if_cancelled(stop_requested)
                power_supply.output_on(channel=selected_channel)
                enabled_channels.append(selected_channel)
            interruptible_sleep(
                parameters.get("duration_ms", 500) / 1000,
                sleep=sleep,
                stop_requested=stop_requested,
            )
        finally:
            for selected_channel in enabled_channels:
                power_supply.output_off(channel=selected_channel)
        return {"index": step["index"], "action": action, "channel": channel, "duration_ms": parameters.get("duration_ms", 500)}
    if action in {"set", "apply"}:
        channel = sequence_channel(parameters.get("channel", 1), allow_all=(action == "apply"))
        voltage = parameters["voltage"]
        current = parameters["current"]
        for selected_channel in sequence_channels(channel, power_supply.capabilities.channels):
            raise_if_cancelled(stop_requested)
            if isinstance(power_supply, PSM2010PowerSupply):
                power_supply.set_output_pair(
                    channel=selected_channel,
                    voltage=voltage,
                    current=current,
                )
            else:
                power_supply.set_current_limit(channel=selected_channel, current=current)
                power_supply.set_voltage(channel=selected_channel, voltage=voltage)
            if action == "apply" and not parameters.get("no_output", False):
                power_supply.output_on(channel=selected_channel)
        return {"index": step["index"], "action": action, "channel": channel, "voltage": voltage, "current": current}
    raise CoreValidationError(f"unsupported sequence action: {action}")


def sequence_cleanup_safe_off(power_supply: Any) -> dict[str, Any]:
    attempted = False
    errors: list[dict[str, Any]] = []
    for channel in power_supply.capabilities.channels:
        attempted = True
        try:
            power_supply.output_off(channel=channel)
        except Exception as exc:
            errors.append({"channel": channel, "message": str(exc)})
    return {"safe_off_attempted": attempted, "errors": errors}


def _preflight_sequence(request: SequenceRequest, power_supply: Any, plan: dict[str, Any], *, model: str | None) -> None:
    state: dict[int, dict[str, float]] = {}
    enable_channels: set[int] = set()
    for step in plan["steps"]:
        if step["action"] == "output-off":
            selected = sequence_channel(
                step["parameters"].get("channel", 1),
                allow_all=True,
            )
            for channel in sequence_channels(selected, power_supply.capabilities.channels):
                try:
                    validate_channel(
                        channel,
                        _safety_limits_for_channel(
                            request,
                            model=model,
                            channel=channel,
                        ),
                    )
                except (SafetyConfigError, SafetyValidationError) as exc:
                    raise CoreValidationError(str(exc)) from exc
    for step in plan["steps"]:
        if step["action"] in {"output-on", "cycle-output"} or (
            step["action"] == "apply" and not step["parameters"].get("no_output", False)
        ):
            selected = sequence_channel(step["parameters"].get("channel", 1), allow_all=True)
            enable_channels.update(sequence_channels(selected, power_supply.capabilities.channels))
    for channel in sorted(enable_channels):
        state[channel] = {
            "voltage": power_supply.programmed_voltage(channel=channel),
            "current": power_supply.programmed_current(channel=channel),
        }
    for step in plan["steps"]:
        action = step["action"]
        parameters = step["parameters"]
        if action in {"set", "apply"}:
            selected = sequence_channel(parameters.get("channel", 1), allow_all=(action == "apply"))
            for channel in sequence_channels(selected, power_supply.capabilities.channels):
                state[channel] = {"voltage": parameters["voltage"], "current": parameters["current"]}
                _validate_sequence_effective(request, power_supply, model, channel, state[channel])
        if action in {"output-on", "cycle-output"} or (action == "apply" and not parameters.get("no_output", False)):
            selected = sequence_channel(parameters.get("channel", 1), allow_all=True)
            for channel in sequence_channels(selected, power_supply.capabilities.channels):
                values = state[channel]
                _validate_sequence_effective(request, power_supply, model, channel, values)


def _validate_sequence_effective(
    request: SequenceRequest,
    power_supply: Any,
    model: str | None,
    channel: int,
    values: dict[str, float],
) -> None:
    limits = _safety_limits_for_channel(request, model=model, channel=channel)
    try:
        validate_effective_setpoint(
            model=model,
            channel=channel,
            electrical_ratings=power_supply.capabilities.electrical_ratings,
            safety_limits=limits,
            voltage=values["voltage"],
            current=values["current"],
        )
    except SafetyValidationError as exc:
        raise CoreValidationError(str(exc)) from exc


def _safety_limits_for_channel(request: SequenceRequest, *, model: str | None, channel: int) -> SafetyLimits | None:
    if request.runtime.safety_config is None:
        return None
    return resolve_safety_config(
        request.runtime.safety_config,
        resource=None if request.runtime.resource_alias else request.runtime.resource,
        resource_alias=request.runtime.resource_alias,
        model=model,
        channel=channel,
    ).limits


def _model_from_idn(idn: str) -> str | None:
    from powers_tool_core.models import parse_idn

    return parse_idn(idn).model


def sequence_channel(value: Any, *, allow_all: bool = False) -> int | str:
    if allow_all and type(value) is str and value == "all":
        return "all"
    if type(value) is not int or value < 1:
        raise CoreValidationError("sequence channel must be a positive integer")
    return value


def sequence_pulse_pins(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise CoreValidationError("sequence trigger-pulse pins must be a non-empty list")
    if any(isinstance(pin, bool) or not isinstance(pin, int) or pin not in {1, 2, 3} for pin in value):
        raise CoreValidationError("sequence trigger-pulse pins must contain rear pins 1, 2, or 3")
    pins = tuple(value)
    if len(set(pins)) != len(pins):
        raise CoreValidationError("sequence trigger-pulse pins must not contain duplicates")
    return pins


def sequence_channels(channel: int | str, supported_channels: tuple[int, ...]) -> tuple[int, ...]:
    if channel == "all":
        return supported_channels
    if int(channel) not in supported_channels:
        raise CoreValidationError(f"channel {channel} is not supported; supported: {supported_channels}")
    return (int(channel),)


def _validate_read_only_channel(power_supply: Any, channel: int, *, command_label: str) -> None:
    supported = getattr(power_supply.capabilities, "real_measure_channels", power_supply.capabilities.channels)
    if channel not in supported:
        raise CoreValidationError(f"channel {channel} is not supported for {command_label}; supported: {supported}")


def sequence_preview_channels(
    channel: int | str,
    *,
    planning_model_id: str | None = None,
    planning_profile_id: str | None = None,
) -> tuple[int, ...]:
    if channel == "all":
        if planning_model_id is None and planning_profile_id is None:
            return E36312APowerSupply.capabilities.channels
        return no_hardware_channels(planning_model_id, planning_profile_id)
    return (int(channel),)


def _preview_scpi(command: str, channel: int, planning_model_id: str | None) -> str:
    if planning_model_id == "gw-instek-psm-2010":
        return command
    separator = "," if " " in command else " "
    return f"{command}{separator}(@{channel})"


def _validate_no_hardware_sequence_channels(request: SequenceRequest, channel: int | str) -> None:
    if not (request.runtime.dry_run or request.runtime.simulate):
        return
    if (
        request.runtime.planning_model_id is None
        and request.runtime.planning_profile_id is None
    ):
        return
    supported = no_hardware_channels(
        request.runtime.planning_model_id,
        request.runtime.planning_profile_id,
    )
    if channel == "all":
        return
    if int(channel) not in supported:
        raise CoreValidationError(f"channel {channel} is not supported; supported: {supported}")


def _early_validation_channels(
    request: SequenceRequest,
    channel: int | str,
) -> tuple[int, ...]:
    if channel != "all":
        return (int(channel),)
    model_id = request.runtime.planning_model_id or request.runtime.expected_model_id
    if model_id is None and request.runtime.planning_profile_id is None:
        return ()
    return no_hardware_channels(model_id, request.runtime.planning_profile_id)


def _safety_limits(request: SequenceRequest) -> Any:
    if request.runtime.safety_config is None:
        return SafetyLimits()
    try:
        return resolve_safety_config(
            request.runtime.safety_config,
            resource=request.runtime.resource,
            resource_alias=request.runtime.resource_alias,
        ).limits
    except SafetyConfigError as exc:
        raise CoreValidationError(str(exc)) from exc


def _parse_sequence_scalar(value: str) -> Any:
    if value == "":
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.lower() == "all":
        return "all"
    try:
        if any(marker in value for marker in (".", "e", "E")):
            return float(value)
        return int(value)
    except ValueError:
        return value.strip("'\"")


def _format_text_value(value: object) -> str:
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value)
