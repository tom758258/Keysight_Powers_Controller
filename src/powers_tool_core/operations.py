"""Parser-neutral operation core for Keysight power supply commands."""

from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import Any, Callable, Sequence

from powers_tool_core import capabilities
from powers_tool_core.connection import open_resource, serial_open_kwargs
from powers_tool_core.cancellation import StopRequested, interruptible_sleep, raise_if_cancelled
from powers_tool_core.core import (
    CommandCancelled,
    ConfirmationRequiredError,
    CoreExecutionError,
    CoreIoError,
    CoreValidationError,
    CoreVerificationError,
    OperationRequest,
    UnsupportedChannelError,
    UnsupportedModelError,
)
from powers_tool_core.drivers.e36312a import E36312APowerSupply
from powers_tool_core.drivers.e3646a import E3646APowerSupply
from powers_tool_core.drivers.edu36311a import EDU36311APowerSupply
from powers_tool_core.drivers.psm2010 import PSM2010PowerSupply
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import create_power_supply, select_driver
from powers_tool_core.models import parse_idn
from powers_tool_core.model_resolution import (
    no_hardware_channels,
    resolve_no_hardware_runtime,
)
from powers_tool_core.live_support import enforce_live_support_for_idn
from powers_tool_core.parameter_constraints import validate_request_parameters
from powers_tool_core.safety import (
    SafetyConfigError,
    SafetyLimits,
    SafetyValidationError,
    resolve_safety_config,
    validate_channel,
    validate_setpoint,
)
from powers_tool_core.setpoint_limits import validate_effective_setpoint
from powers_tool_core.stop_cleanup import CleanupReporter, cancel_workflow_with_safe_off
from powers_tool_core.trigger import run_post_action_completion_pulse, trigger_result_payload
from powers_tool_core.workflow_validation import (
    BoundedResultDetails,
    ExecutionProgress,
    ProgressReporter,
    execution_warning,
    normalize_completion_pulse_channel,
    normalize_loop_count,
    validate_execution_units,
    validate_completion_pulse_planning_model,
    validate_general_workflow_parameters,
)

IDN_QUERY = "*IDN?"
OUTPUT_WRITE_POWER_SUPPLY_TYPES = (
    E36312APowerSupply,
    E3646APowerSupply,
    EDU36311APowerSupply,
    PSM2010PowerSupply,
)
OUTPUT_STATE_POWER_SUPPLY_TYPES = OUTPUT_WRITE_POWER_SUPPLY_TYPES
EARLY_COMPLETION_PULSE_VALIDATION_COMMANDS = frozenset(
    {"set", "apply", "output-on", "cycle-output", "smoke-output"}
)


class ScpiLoggingSession:
    """Session proxy that logs SCPI traffic while preserving driver behavior."""

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

    def close(self) -> None:
        self._session.close()


def run_operation(
    request: OperationRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    sleep: Callable[[float], None] = time.sleep,
    scpi_logger: Callable[[str, str, str], None] | None = None,
    stop_requested: StopRequested = None,
    cleanup_reporter: CleanupReporter | None = None,
    progress_reporter: ProgressReporter | None = None,
) -> dict[str, Any]:
    """Run an operation command and return parser-neutral data."""

    runtime = resolve_no_hardware_runtime(request.runtime)
    request = replace(request, runtime=runtime)
    if request.runtime.dry_run or request.runtime.simulate:
        _ensure_operation_supported(request)
    validate_general_workflow_parameters(request)
    if request.command == "ramp":
        voltages = ramp_voltages(
            request.parameters["start_voltage"],
            request.parameters["stop_voltage"],
            request.parameters["step_voltage"],
        )
        validate_execution_units(
            normalize_loop_count(request.parameters.get("loop_count", 1)),
            len(voltages),
            workflow="Ramp",
            reduction_hint="Ramp steps",
        )
    if request.runtime.dry_run or request.runtime.simulate:
        return output_plan(request)

    if request.command in {
        "set",
        "apply",
        "output-on",
        "output-off",
        "safe-off",
        "output-state",
        "cycle-output",
        "ramp",
        "smoke-output",
    }:
        return _run_output_write_operation(
            request,
            opener=opener,
            sleep=sleep,
            scpi_logger=scpi_logger,
            stop_requested=stop_requested,
            cleanup_reporter=cleanup_reporter,
            progress_reporter=progress_reporter,
        )

    raise CoreValidationError(f"unsupported operation command {request.command!r}")


def output_plan(request: OperationRequest) -> dict[str, Any]:
    """Build the dry-run/simulation output plan without opening hardware."""

    runtime = resolve_no_hardware_runtime(request.runtime)
    request = replace(request, runtime=runtime)
    if request.runtime.dry_run or request.runtime.simulate:
        _ensure_operation_supported(request)
    validate_general_workflow_parameters(request)
    validate_request_parameters(request)
    validate_completion_pulse_planning_model(
        request,
        requested=_completion_pulse_requested(request),
    )
    _validate_known_simulated_model_setpoints(request)
    command = request.command
    p = request.parameters
    channel = p.get("channel")
    plan: dict[str, Any] = {
        "operation": {"name": command},
        "target": {
            "resource": request.runtime.resource,
            "planning_model_id": request.runtime.planning_model_id,
            "planning_profile_id": request.runtime.planning_profile_id,
            "channel": channel,
        },
        "steps": [],
        "description": _output_plan_description(command),
        "hardware_touched": False,
    }

    if command == "set":
        _require_plan_channels(request, channel)
        plan["steps"] = _setpoint_write_steps(channel, p)
        _append_write_followup_steps(p, plan["steps"], _setpoint_verification_actions(p))
    elif command == "output-on":
        channels = _plan_channels(request, channel)
        plan["steps"] = [
            _driver_step(index, "output_on", channel=selected_channel)
            for index, selected_channel in enumerate(channels, start=1)
        ]
        _append_write_followup_steps(p, plan["steps"], ("output_state",), channels=channels)
    elif command == "output-off":
        channels = _plan_channels(request, channel)
        plan["steps"] = [
            _driver_step(index, "output_off", channel=selected_channel)
            for index, selected_channel in enumerate(channels, start=1)
        ]
        _append_write_followup_steps(p, plan["steps"], ("output_state",), channels=channels)
    elif command == "safe-off":
        channels = _plan_channels(request, channel)
        plan["steps"] = [
            _driver_step(index, "safe_off", channel=selected_channel)
            for index, selected_channel in enumerate(channels, start=1)
        ]
    elif command == "output-state":
        channels = _plan_channels(request, channel)
        plan["steps"] = [
            _driver_step(index, "output_state", channel=selected_channel)
            for index, selected_channel in enumerate(channels, start=1)
        ]
    elif command == "cycle-output":
        channels = _plan_channels(request, channel)
        steps = []
        index = 1
        for selected_channel in channels:
            steps.append(_driver_step(index, "output_on", channel=selected_channel))
            index += 1
        steps.append(_driver_step(index, "sleep", duration_ms=p.get("duration_ms", 0)))
        index += 1
        for selected_channel in channels:
            steps.append(_driver_step(index, "output_off", channel=selected_channel))
            index += 1
        plan["steps"] = steps
    elif command == "apply":
        channels = _plan_channels(request, channel)
        steps = []
        index = 1
        for selected_channel in channels:
            steps.append(_driver_step(index, "set_current_limit", channel=selected_channel, current=_json_safe_number(p["current"])))
            index += 1
            steps.append(_driver_step(index, "set_voltage", channel=selected_channel, voltage=_json_safe_number(p["voltage"])))
            index += 1
        if not p.get("no_output", False):
            for selected_channel in channels:
                steps.append(_driver_step(index, "output_on", channel=selected_channel))
                index += 1
        plan["steps"] = steps
        _append_write_followup_steps(p, plan["steps"], ("programmed_voltage", "programmed_current"), channels=channels)
    elif command == "ramp":
        _require_plan_channels(request, channel)
        voltages = ramp_voltages(p["start_voltage"], p["stop_voltage"], p["step_voltage"])
        _validate_ramp_completion_pulse(request)
        loop_count = normalize_loop_count(p.get("loop_count", 1))
        execution_units = validate_execution_units(
            loop_count,
            len(voltages),
            workflow="Ramp",
            reduction_hint="Ramp steps",
        )
        pulse_timing = p.get("completion_pulse_timing", "segment")
        pulse_channel = _completion_pulse_channel(request, channel) if _completion_pulse_requested(request) else channel
        enable_output = p.get("enable_output", False)
        steps = [_driver_step(1, "set_current_limit", channel=channel, current=_json_safe_number(p["current"]))]
        index = 2
        for voltage_index, voltage in enumerate(voltages):
            steps.append(_driver_step(index, "set_voltage", channel=channel, voltage=_json_safe_number(voltage)))
            index += 1
            if voltage_index == 0 and enable_output:
                steps.append(_driver_step(index, "output_on", channel=channel))
                index += 1
                steps.append(
                    _driver_step(
                        index,
                        "output_state",
                        channel=channel,
                        expected_enabled=True,
                    )
                )
                index += 1
            if _step_completion_pulse_requested(request):
                steps.append(
                    _driver_step(
                        index,
                        "completion_pulse",
                        channel=pulse_channel,
                        pins=list(p.get("completion_pulse_pins") or ()),
                        polarity=p.get("completion_pulse_polarity", "positive"),
                        mode="post-action",
                        timing="step",
                        scope="iteration",
                    )
                )
                index += 1
            if p.get("delay_ms", 0) > 0 and voltage_index < len(voltages) - 1:
                steps.append(_driver_step(index, "sleep", duration_ms=p["delay_ms"]))
                index += 1
        if p.get("settle_ms", 0) > 0:
            steps.append(_driver_step(index, "sleep", duration_ms=p["settle_ms"]))
            index += 1
        if p.get("verify_after_write", False):
            steps.append(_driver_step(index, "programmed_voltage", channel=channel))
            index += 1
            steps.append(_driver_step(index, "programmed_current", channel=channel))
            index += 1
        if pulse_timing == "segment" and _completion_pulse_requested(request):
            steps.append(
                _driver_step(
                    index,
                    "completion_pulse",
                    channel=pulse_channel,
                    pins=list(p.get("completion_pulse_pins") or ()),
                    polarity=p.get("completion_pulse_polarity", "positive"),
                    mode="post-action",
                    timing="segment",
                    scope="iteration",
                )
            )
            index += 1
        if enable_output:
            steps.append(
                _driver_step(
                    index,
                    "output_state",
                    channel=channel,
                    final=True,
                )
            )
            index += 1
        if pulse_timing == "loop" and _completion_pulse_requested(request):
            steps.append(
                _driver_step(
                    index,
                    "completion_pulse",
                    channel=pulse_channel,
                    pins=list(p.get("completion_pulse_pins") or ()),
                    polarity=p.get("completion_pulse_polarity", "positive"),
                    mode="post-action",
                    timing="loop",
                    scope="workflow",
                )
            )
        plan["steps"] = steps
        plan["description"] = (
            "Preview one Ramp iteration: set current and the first voltage, enable and verify output, "
            "then step remaining voltage setpoints; loop_count gives the total iteration count."
            if enable_output
            else "Preview one Ramp iteration: set current, then step voltage setpoints without changing "
            "output state; loop_count gives the total iteration count."
        )
        plan["voltage_steps_scope"] = "one_iteration"
        plan["enable_output"] = enable_output
        plan["loop_count"] = loop_count
        plan["execution_units"] = execution_units
        plan["execution_warning"] = execution_warning(
            execution_units, reduction_hint="Ramp steps"
        )
        plan["completed_loops"] = 0
        plan["completed_step_executions"] = 0
        plan["output_enable_executed"] = False
        plan["enabled_channels"] = []
        plan["final_output_states"] = [
            {
                "channel": channel,
                "enabled": None,
                "verified": False,
                "unchanged_by_workflow": not enable_output,
            }
        ]
        plan["cancellation_cleanup"] = None
    elif command == "smoke-output":
        _require_plan_channels(request, channel)
        plan["steps"] = [
            _driver_step(1, "set_current_limit", channel=channel, current=_json_safe_number(p["current"])),
            _driver_step(2, "set_voltage", channel=channel, voltage=_json_safe_number(p["voltage"])),
            _driver_step(3, "output_on", channel=channel),
            _driver_step(4, "sleep", duration_ms=p.get("duration_ms", 0)),
            _driver_step(5, "measure_voltage", channel=channel),
            _driver_step(6, "measure_current", channel=channel),
            _driver_step(7, "output_off", channel=channel),
            _driver_step(8, "output_state", channel=channel),
        ]
    else:
        raise CoreValidationError(f"unsupported output command {command!r}")

    return plan


def ramp_voltages(start: float, stop: float, step: float) -> list[float]:
    if step <= 0:
        raise CoreValidationError("step-voltage must be greater than 0")
    direction = 1.0 if stop >= start else -1.0
    signed_step = direction * step
    voltages = [float(start)]
    current = float(start)
    for _ in range(1000):
        next_voltage = current + signed_step
        if (direction > 0 and next_voltage >= stop) or (direction < 0 and next_voltage <= stop):
            break
        voltages.append(next_voltage)
        current = next_voltage
    else:
        raise CoreValidationError("ramp would exceed 1000 voltage steps")
    if not math.isclose(voltages[-1], stop, rel_tol=0.0, abs_tol=1e-12):
        voltages.append(float(stop))
    if len(voltages) > 1000:
        raise CoreValidationError("ramp would exceed 1000 voltage steps")
    return voltages


def _run_output_write_operation(
    request: OperationRequest,
    *,
    opener: Callable[..., Any],
    sleep: Callable[[float], None],
    scpi_logger: Callable[[str, str, str], None] | None,
    stop_requested: StopRequested,
    cleanup_reporter: CleanupReporter | None,
    progress_reporter: ProgressReporter | None,
) -> dict[str, Any]:
    _validate_real_gate(request)
    opened = False
    resource = request.runtime.resource
    if resource is None:
        raise CoreValidationError("resource is required")

    try:
        with opener(
            resource,
            backend=request.runtime.backend,
            timeout_ms=request.runtime.timeout_ms,
            **serial_open_kwargs(
                serial_options=request.runtime.serial_options,
                serial_remote=request.runtime.serial_remote,
                serial_local_on_close=request.runtime.serial_local_on_close,
            ),
        ) as instrument:
            opened = True
            session = (
                ScpiLoggingSession(resource, instrument, scpi_logger)
                if request.runtime.log_scpi and scpi_logger is not None
                else instrument
            )
            idn = session.query(IDN_QUERY)
            enforce_live_support_for_idn(request, idn)
            power_supply = create_power_supply(session, idn)
            allowed_types = (
                OUTPUT_STATE_POWER_SUPPLY_TYPES
                if request.command == "output-state"
                else OUTPUT_WRITE_POWER_SUPPLY_TYPES
            )
            if not isinstance(power_supply, allowed_types):
                model = parse_idn(idn).model
                raise UnsupportedModelError(
                    f"{capabilities.unsupported_command_message(request.command, model, 'live')}\n"
                    f"Found {type(power_supply).__name__} from *IDN? response."
                )
            if request.command in EARLY_COMPLETION_PULSE_VALIDATION_COMMANDS:
                _validate_requested_completion_pulse_power_supply(request, power_supply)
            return _execute_output_write(
                request,
                power_supply,
                idn=idn,
                sleep=sleep,
                stop_requested=stop_requested,
                cleanup_reporter=cleanup_reporter,
                progress_reporter=progress_reporter,
            )
    except VisaConnectionError as exc:
        prefix = f"{request.command} failed" if opened else f"Could not open resource for {request.command}"
        raise CoreIoError(f"{prefix}: {exc}", opened=opened) from exc
    except (CoreValidationError, CoreExecutionError):
        raise
    except ValueError as exc:
        raise CoreExecutionError(f"{request.command} failed: {exc}") from exc


def _execute_output_write(
    request: OperationRequest,
    power_supply: Any,
    *,
    idn: str,
    sleep: Callable[[float], None],
    stop_requested: StopRequested,
    cleanup_reporter: CleanupReporter | None,
    progress_reporter: ProgressReporter | None,
) -> dict[str, Any]:
    command = request.command
    p = request.parameters
    channel = p.get("channel")
    if command not in {"output-off", "safe-off"}:
        raise_if_cancelled(stop_requested)

    if command == "set":
        _require_channel(power_supply, channel, command)
        _validate_setpoint_for_request(request, idn, channel)
        if isinstance(power_supply, PSM2010PowerSupply) and p.get("voltage") is not None and p.get("current") is not None:
            power_supply.set_output_pair(
                channel=channel,
                voltage=p["voltage"],
                current=p["current"],
            )
        elif p.get("current") is not None:
            power_supply.set_current_limit(channel=channel, current=p["current"])
        if p.get("voltage") is not None and not (
            isinstance(power_supply, PSM2010PowerSupply) and p.get("current") is not None
        ):
            power_supply.set_voltage(channel=channel, voltage=p["voltage"])
        _settle_after_write(request, sleep, stop_requested)
        verification = _verify_setpoints_after_write(request, power_supply, channels=(channel,))
        _raise_verification_failed(verification)
        trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=channel)
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel, **_set_result_fields(p))
        _attach_trigger_if_present(data, trigger)
        _attach_verification_if_requested(request, data, verification)
        return data

    if command == "apply":
        channels = _channels_from_selection(channel, power_supply.capabilities.channels)
        for selected_channel in channels:
            _validate_setpoint_for_request(request, idn, selected_channel)
            if not p.get("no_output", False):
                _require_confirmation_if_needed(request, p["voltage"], p["current"], selected_channel, idn)
        for selected_channel in channels:
            _write_output_pair(
                power_supply,
                channel=selected_channel,
                voltage=p["voltage"],
                current=p["current"],
            )
        if not p.get("no_output", False):
            for selected_channel in channels:
                power_supply.output_on(channel=selected_channel)
        _settle_after_write(request, sleep)
        verification = _verify_setpoints_after_write(request, power_supply, channels=channels)
        if verification["passed"] and not p.get("no_output", False):
            verification = _combine_verifications(
                "apply",
                verification,
                *(
                    _verify_output_state_after_write(request, power_supply, expected=True, channel=selected_channel)
                    for selected_channel in channels
                ),
            )
        _raise_verification_failed(verification)
        trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=channel)
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel, voltage=p["voltage"], current=p["current"])
        data["channels"] = list(channels)
        data["output_enabled"] = not p.get("no_output", False)
        _attach_trigger_if_present(data, trigger)
        _attach_verification_if_requested(request, data, verification)
        return data

    if command == "output-on":
        channels = _channels_from_selection(channel, power_supply.capabilities.channels, command=command)
        outputs = []
        for selected_channel in channels:
            voltage = power_supply.programmed_voltage(channel=selected_channel)
            current = power_supply.programmed_current(channel=selected_channel)
            _validate_setpoint_for_request(request, idn, selected_channel, voltage=voltage, current=current)
            _require_confirmation_if_needed(request, voltage, current, selected_channel, idn)
            outputs.append(
                {
                    "channel": selected_channel,
                    "enabled": True,
                    "readback": {
                        "setpoints": {"voltage": voltage, "current": current},
                        "safety_checked": request.runtime.safety_config is not None,
                    },
                }
            )
        for selected_channel in channels:
            power_supply.output_on(channel=selected_channel)
        _settle_after_write(request, sleep)
        verification = _combine_verifications(
            "output-on",
            *(
                _verify_output_state_after_write(request, power_supply, expected=True, channel=selected_channel)
                for selected_channel in channels
            ),
        )
        _raise_verification_failed(verification)
        trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=channel)
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel)
        data["output_enabled"] = True
        if channel == "all":
            data["outputs"] = outputs
        else:
            data["readback"] = outputs[0]["readback"]
        _attach_trigger_if_present(data, trigger)
        _attach_verification_if_requested(request, data, verification)
        return data

    if command == "output-off":
        channels = _channels_from_selection(channel, power_supply.capabilities.channels, command=command)
        for selected_channel in channels:
            validate_channel(selected_channel, _safety_limits(request, channel=selected_channel, model=parse_idn(idn).model))
        for selected_channel in channels:
            power_supply.output_off(channel=selected_channel)
        _settle_after_write(request, sleep)
        verification = _combine_verifications(
            "output-off",
            *(
                _verify_output_state_after_write(request, power_supply, expected=False, channel=selected_channel)
                for selected_channel in channels
            ),
        )
        _raise_verification_failed(verification)
        trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=channel)
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel)
        data["output_enabled"] = False
        if channel == "all":
            data["outputs"] = [{"channel": selected_channel, "enabled": False} for selected_channel in channels]
        _attach_trigger_if_present(data, trigger)
        _attach_verification_if_requested(request, data, verification)
        return data

    if command == "safe-off":
        channels = power_supply.capabilities.channels if channel == "all" else (_require_channel(power_supply, channel, command),)
        outputs = []
        for selected_channel in channels:
            power_supply.output_off(channel=selected_channel)
            outputs.append({"channel": selected_channel, "enabled": power_supply.output_state(channel=selected_channel)})
        trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=channel)
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel)
        data["outputs"] = outputs
        _attach_trigger_if_present(data, trigger)
        return data

    if command == "output-state":
        channels = _channels_from_selection(
            channel,
            getattr(power_supply.capabilities, "real_measure_channels", power_supply.capabilities.channels),
            command=command,
        )
        outputs = []
        for selected_channel in channels:
            raise_if_cancelled(stop_requested)
            validate_channel(selected_channel, _safety_limits(request, channel=selected_channel, model=parse_idn(idn).model))
            outputs.append({"channel": selected_channel, "enabled": power_supply.output_state(channel=selected_channel)})
        data = _resource_payload(request, idn, channel=channel)
        if channel == "all":
            data["outputs"] = outputs
        else:
            data["output_enabled"] = outputs[0]["enabled"]
        return data

    if command == "cycle-output":
        channels = _channels_from_selection(channel, power_supply.capabilities.channels, command=command)
        for selected_channel in channels:
            voltage = power_supply.programmed_voltage(channel=selected_channel)
            current = power_supply.programmed_current(channel=selected_channel)
            _validate_setpoint_for_request(request, idn, selected_channel, voltage=voltage, current=current)
            _require_confirmation_if_needed(request, voltage, current, selected_channel, idn)
        enabled_channels: list[int] = []
        try:
            for selected_channel in channels:
                raise_if_cancelled(stop_requested)
                power_supply.output_on(channel=selected_channel)
                enabled_channels.append(selected_channel)
            interruptible_sleep(
                p.get("duration_ms", 0) / 1000,
                sleep=sleep,
                stop_requested=stop_requested,
            )
        finally:
            for selected_channel in enabled_channels:
                power_supply.output_off(channel=selected_channel)
        trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=channel)
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel, duration_ms=p.get("duration_ms", 0))
        data["cycled"] = True
        data["final_output_enabled"] = False
        if channel == "all":
            data["outputs"] = [
                {"channel": selected_channel, "cycled": True, "final_enabled": False}
                for selected_channel in channels
            ]
        _attach_trigger_if_present(data, trigger)
        return data

    if command == "ramp":
        _require_channel(power_supply, channel, command)
        voltages = ramp_voltages(p["start_voltage"], p["stop_voltage"], p["step_voltage"])
        _validate_ramp_completion_pulse(request)
        loop_count = normalize_loop_count(p.get("loop_count", 1))
        execution_units = validate_execution_units(
            loop_count,
            len(voltages),
            workflow="Ramp",
            reduction_hint="Ramp steps",
        )
        progress = ExecutionProgress(execution_units, progress_reporter)
        pulse_timing = p.get("completion_pulse_timing", "segment")
        enable_output = p.get("enable_output", False)
        for voltage in voltages:
            _validate_setpoint_for_request(request, idn, channel, voltage=voltage, current=p["current"])
            if enable_output:
                _require_confirmation_if_needed(request, voltage, p["current"], channel, idn)
        trigger: dict[str, Any] | None = None
        verification = {"passed": True, "checks": [], "differences": []}
        _validate_requested_completion_pulse_power_supply(request, power_supply)
        completed_voltages = BoundedResultDetails[float]()
        completed_loops = 0
        output_enable_executed = False
        triggers = BoundedResultDetails[dict[str, Any]]()
        active_loop_index = 1
        active_step_index = 0
        active_voltage = voltages[0]
        try:
            raise_if_cancelled(stop_requested)
            if isinstance(power_supply, PSM2010PowerSupply):
                power_supply.set_output_pair(
                    channel=channel,
                    voltage=voltages[0],
                    current=p["current"],
                )
            else:
                power_supply.set_current_limit(channel=channel, current=p["current"])
            for loop_index in range(1, loop_count + 1):
                active_loop_index = loop_index
                for index, voltage in enumerate(voltages):
                    active_step_index = index
                    active_voltage = voltage
                    raise_if_cancelled(stop_requested)
                    if not (
                        isinstance(power_supply, PSM2010PowerSupply)
                        and loop_index == 1
                        and index == 0
                    ):
                        power_supply.set_voltage(channel=channel, voltage=voltage)
                    completed_voltages.append(voltage)
                    progress.complete_unit()
                    if index == 0 and loop_index == 1 and enable_output:
                        power_supply.output_on(channel=channel)
                        output_enable_executed = True
                        on_verification = _verify_output_state_after_write(
                            request,
                            power_supply,
                            expected=True,
                            channel=channel,
                            required=True,
                        )
                        _raise_verification_failed(on_verification)
                    if _step_completion_pulse_requested(request):
                        step_trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=channel)
                        if step_trigger is not None:
                            entry = {"step_index": index, "voltage": voltage, "trigger": step_trigger}
                            if loop_count > 1:
                                entry["loop_index"] = loop_index
                            triggers.append(entry)
                    if p.get("delay_ms", 0) > 0 and index < len(voltages) - 1:
                        interruptible_sleep(p["delay_ms"] / 1000, sleep=sleep, stop_requested=stop_requested)
                _settle_after_write(request, sleep, stop_requested)
                verification = _verify_setpoints_after_write(
                    request,
                    power_supply,
                    channels=(channel,),
                    expected_voltage=p["stop_voltage"],
                )
                _raise_verification_failed(verification)
                raise_if_cancelled(stop_requested)
                if pulse_timing == "segment" and _completion_pulse_requested(request):
                    iteration_trigger = _maybe_run_completion_pulse(
                        request,
                        power_supply,
                        default_channel=channel,
                    )
                    if loop_count == 1:
                        trigger = iteration_trigger
                    elif iteration_trigger is not None:
                        triggers.append({"loop_index": loop_index, "trigger": iteration_trigger})
                completed_loops += 1
            final_output_states = (
                [{
                    "channel": channel,
                    "enabled": power_supply.output_state(channel=channel),
                    "verified": True,
                    "unchanged_by_workflow": False,
                }]
                if enable_output
                else [{
                    "channel": channel,
                    "enabled": None,
                    "verified": False,
                    "unchanged_by_workflow": True,
                }]
            )
            if enable_output and final_output_states[0]["enabled"] is not True:
                raise CoreVerificationError(
                    "final output-state verification failed",
                    verification={
                        "operation": "ramp-final-output-state",
                        "passed": False,
                        "checks": final_output_states,
                        "differences": final_output_states,
                    },
                )
            _raise_on_instrument_errors(power_supply, command)
            raise_if_cancelled(stop_requested)
            if pulse_timing == "loop":
                trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=channel)
        except (CommandCancelled, KeyboardInterrupt):
            cancel_workflow_with_safe_off(
                power_supply,
                partial_result={
                    "loop_count": loop_count,
                    "enable_output": enable_output,
                    "output_enable_executed": output_enable_executed,
                    "enabled_channels": [channel] if output_enable_executed else [],
                    "completed_voltages": completed_voltages.retained(),
                    **completed_voltages.metadata("completed_voltages"),
                    "completed_loops": completed_loops,
                    "completed_step_executions": completed_voltages.total,
                    "failed_step": {
                        "loop_index": active_loop_index,
                        "step_index": active_step_index,
                        "voltage": active_voltage,
                        "code": "interrupted",
                    },
                    "triggers": triggers.retained(),
                    **triggers.metadata("triggers"),
                    "progress": progress.snapshot(),
                    "trigger": (
                        _pending_completion_pulse_result(request, channel=channel)
                        if _completion_pulse_requested(request)
                        and pulse_timing == "loop"
                        else None
                    ),
                },
                reporter=cleanup_reporter,
            )
        except CoreExecutionError as exc:
            if exc.trigger is None and _completion_pulse_requested(request):
                exc.trigger = _pending_completion_pulse_result(request, channel=channel)
            failure_during_iteration = completed_loops < loop_count
            exc.data = {
                "loop_count": loop_count,
                "completed_loops": completed_loops,
                "completed_step_executions": completed_voltages.total,
                "completed_voltages": completed_voltages.retained(),
                **completed_voltages.metadata("completed_voltages"),
                "failed_step": (
                    {
                        "loop_index": active_loop_index,
                        "step_index": active_step_index,
                        "voltage": active_voltage,
                        "code": "step_failed",
                    }
                    if failure_during_iteration
                    else None
                ),
                "failure_phase": "iteration" if failure_during_iteration else "finalization",
                "trigger": exc.trigger,
                "triggers": triggers.retained(),
                **triggers.metadata("triggers"),
                "progress": progress.snapshot(),
            }
            raise
        data = _resource_payload(request, idn, channel=channel, voltages=voltages)
        data["steps"] = len(voltages)
        data["loop_count"] = loop_count
        data["completed_loops"] = completed_loops
        data["completed_step_executions"] = completed_voltages.total
        data["execution_units"] = execution_units
        data["progress"] = progress.snapshot()
        data.update(completed_voltages.metadata("completed_voltages"))
        data["enable_output"] = enable_output
        data["output_enable_executed"] = output_enable_executed
        data["enabled_channels"] = [channel] if output_enable_executed else []
        data["final_output_states"] = final_output_states
        data["cancellation_cleanup"] = None
        _attach_trigger_if_present(data, trigger)
        if triggers.total:
            data["triggers"] = triggers.retained()
            data.update(triggers.metadata("triggers"))
        _attach_verification_if_requested(request, data, verification)
        return data

    if command == "smoke-output":
        _require_channel(power_supply, channel, command)
        _validate_setpoint_for_request(request, idn, channel)
        _require_confirmation_if_needed(request, p["voltage"], p["current"], channel, idn)
        safe_off_attempted = False
        output_was_enabled = False
        measurements: dict[str, float]
        try:
            _write_output_pair(
                power_supply,
                channel=channel,
                voltage=p["voltage"],
                current=p["current"],
            )
            power_supply.output_on(channel=channel)
            output_was_enabled = True
            interruptible_sleep(
                p.get("duration_ms", 0) / 1000,
                sleep=sleep,
                stop_requested=stop_requested,
            )
            measurements = {
                "voltage": power_supply.measure_voltage(channel=channel),
                "current": power_supply.measure_current(channel=channel),
            }
        finally:
            if output_was_enabled:
                safe_off_attempted = True
                power_supply.output_off(channel=channel)
        final_enabled = power_supply.output_state(channel=channel)
        trigger = _maybe_run_completion_pulse(request, power_supply, default_channel=channel)
        _raise_on_instrument_errors(power_supply, command)
        data = _resource_payload(request, idn, channel=channel, voltage=p["voltage"], current=p["current"])
        data["measurements"] = measurements
        data["final_output_enabled"] = final_enabled
        data["safe_off_attempted"] = safe_off_attempted
        _attach_trigger_if_present(data, trigger)
        return data

    raise CoreValidationError(f"unsupported output command {command!r}")


def _validate_real_gate(request: OperationRequest) -> None:
    if request.runtime.dry_run or request.runtime.simulate:
        return
    if not request.runtime.resource:
        raise CoreValidationError("resource is required")


def _ensure_operation_supported(request: OperationRequest) -> None:
    mode = "dry_run" if request.runtime.dry_run else "simulate"
    capabilities.ensure_command_supported(
        request.command,
        request.runtime.planning_model_id,
        request.runtime.planning_profile_id,
        mode,
    )


def _validate_setpoint_for_request(
    request: OperationRequest,
    idn: str,
    channel: int,
    *,
    voltage: float | None = None,
    current: float | None = None,
) -> None:
    p = request.parameters
    limits = _safety_limits(request, channel=channel, model=parse_idn(idn).model)
    requested_voltage = p.get("voltage") if voltage is None else voltage
    requested_current = p.get("current") if current is None else current
    try:
        validate_setpoint(
            channel=channel,
            voltage=requested_voltage,
            current=requested_current,
            limits=limits,
        )
        validate_effective_setpoint(
            model=parse_idn(idn).model,
            channel=channel,
            electrical_ratings=power_supply_ratings_for_idn(idn),
            safety_limits=limits,
            voltage=requested_voltage,
            current=requested_current,
        )
    except (SafetyConfigError, SafetyValidationError) as exc:
        raise CoreValidationError(str(exc)) from exc


def power_supply_ratings_for_idn(idn: str) -> Any:
    from powers_tool_core.electrical_ratings import ratings_for_model_id

    identity = select_driver(idn).physical_identity
    return ratings_for_model_id(identity.model_id if identity is not None else None)


def _validate_known_simulated_model_setpoints(request: OperationRequest) -> None:
    if not request.runtime.simulate or not request.runtime.resource:
        return
    from powers_tool_core.electrical_ratings import ratings_for_model_id
    from powers_tool_core.identity import planning_model_id_from_sim_resource
    from powers_tool_core.testing.simulator import SIMULATED_IDN

    idn = SIMULATED_IDN.get(request.runtime.resource)
    if idn is None:
        return
    model = parse_idn(idn).model
    ratings = ratings_for_model_id(planning_model_id_from_sim_resource(request.runtime.resource))
    if ratings is None:
        return
    p = request.parameters
    channels = ratings.channels.keys() if p.get("channel") == "all" else (p.get("channel"),)
    for channel in channels:
        if not isinstance(channel, int):
            continue
        values: list[float | None]
        if request.command == "ramp":
            values = ramp_voltages(p["start_voltage"], p["stop_voltage"], p["step_voltage"])
        elif request.command in {"set", "apply", "smoke-output"}:
            values = [p.get("voltage")]
        else:
            continue
        limits = _safety_limits(request, channel=channel, model=model)
        try:
            for voltage in values:
                validate_effective_setpoint(
                    model=model,
                    channel=channel,
                    electrical_ratings=ratings,
                    safety_limits=limits,
                    voltage=voltage,
                    current=p.get("current"),
                )
        except SafetyValidationError as exc:
            raise CoreValidationError(str(exc)) from exc


def _require_confirmation_if_needed(
    request: OperationRequest,
    voltage: float,
    current: float,
    channel: int,
    idn: str,
) -> None:
    limits = _safety_limits(request, channel=channel, model=parse_idn(idn).model)
    if limits is None:
        return
    if request.runtime.confirm:
        return
    needs_confirmation = (
        voltage > 0
        and current > 0
        and (
            (
                limits.confirm_above_voltage is not None
                and voltage > limits.confirm_above_voltage
            )
            or (
                limits.confirm_above_current is not None
                and current > limits.confirm_above_current
            )
        )
    )
    if needs_confirmation:
        raise ConfirmationRequiredError(f"{request.command} requires confirm for real hardware execution")


def _safety_limits(request: OperationRequest, *, channel: int | None, model: str | None) -> SafetyLimits | None:
    if request.runtime.safety_config is None:
        return None
    try:
        return resolve_safety_config(
            request.runtime.safety_config,
            resource=None if request.runtime.resource_alias is not None else request.runtime.resource,
            resource_alias=request.runtime.resource_alias,
            model=model,
            channel=channel,
        ).limits
    except SafetyConfigError as exc:
        raise CoreValidationError(str(exc)) from exc


def _require_channel(power_supply: Any, channel: int, command: str) -> int:
    if channel not in power_supply.capabilities.channels:
        raise UnsupportedChannelError(
            f"channel {channel} is not supported for {command}; supported: {power_supply.capabilities.channels}"
        )
    return channel


def _require_read_only_channel(power_supply: Any, channel: int, command: str) -> int:
    channels = getattr(power_supply.capabilities, "real_measure_channels", power_supply.capabilities.channels)
    if channel not in channels:
        raise UnsupportedChannelError(
            f"channel {channel} is not supported for {command}; supported: {channels}"
        )
    return channel


def _channels_from_selection(selection: int | str, supported: Sequence[int], *, command: str | None = None) -> tuple[int, ...]:
    if selection == "all":
        return tuple(supported)
    if selection not in supported:
        command_label = f" for {command}" if command else ""
        raise UnsupportedChannelError(f"channel {selection} is not supported{command_label}; supported: {tuple(supported)}")
    return (int(selection),)


def _raise_on_instrument_errors(power_supply: Any, command: str) -> None:
    errors, _read_count = power_supply.read_error_queue(20)
    if errors:
        raise CoreExecutionError(f"{command} completed with instrument errors: {errors}")


def _settle_after_write(
    request: OperationRequest,
    sleep: Callable[[float], None],
    stop_requested: StopRequested = None,
) -> None:
    settle_ms = request.parameters.get("settle_ms", 0)
    if settle_ms > 0:
        interruptible_sleep(settle_ms / 1000, sleep=sleep, stop_requested=stop_requested)


def _verify_setpoints_after_write(
    request: OperationRequest,
    power_supply: Any,
    *,
    channels: Sequence[int],
    expected_voltage: float | None = None,
) -> dict[str, Any]:
    p = request.parameters
    if not p.get("verify_after_write", False):
        return {"passed": True, "checks": [], "differences": []}
    voltage = p.get("voltage") if expected_voltage is None else expected_voltage
    current = p.get("current")
    voltage_tolerance = p.get("setpoint_voltage_tolerance", 0.001)
    current_tolerance = p.get("setpoint_current_tolerance", 0.001)
    tolerances = {"voltage": voltage_tolerance, "current": current_tolerance}
    checks = []
    differences = []
    for channel in channels:
        expected: dict[str, Any] = {}
        actual: dict[str, Any] = {}
        if voltage is not None:
            actual_voltage = power_supply.programmed_voltage(channel=channel)
            expected["voltage"] = _json_safe_number(voltage)
            actual["voltage"] = _json_safe_number(actual_voltage)
            if abs(actual_voltage - voltage) > voltage_tolerance:
                differences.append(_verification_difference("programmed_voltage", channel, voltage, actual_voltage, voltage_tolerance))
        if current is not None:
            actual_current = power_supply.programmed_current(channel=channel)
            expected["current"] = _json_safe_number(current)
            actual["current"] = _json_safe_number(actual_current)
            if abs(actual_current - current) > current_tolerance:
                differences.append(_verification_difference("programmed_current", channel, current, actual_current, current_tolerance))
        checks.append(
            {
                "channel": channel,
                "expected": expected,
                "actual": actual,
                "tolerances": tolerances,
            }
        )
    return {"passed": not differences, "checks": checks, "differences": differences}


def _verify_output_state_after_write(
    request: OperationRequest,
    power_supply: Any,
    *,
    expected: bool,
    channel: int | None = None,
    required: bool = False,
) -> dict[str, Any]:
    if not required and not request.parameters.get("verify_after_write", False):
        return {"passed": True, "checks": [], "differences": []}
    selected_channel = request.parameters.get("channel") if channel is None else channel
    actual = power_supply.output_state(channel=selected_channel)
    differences = []
    if actual is not expected:
        differences.append(
            {
                "path": f"outputs[channel={selected_channel}].enabled",
                "channel": selected_channel,
                "expected": expected,
                "actual": actual,
            }
        )
    return {
        "passed": not differences,
        "checks": [{"channel": selected_channel, "expected": expected, "actual": actual}],
        "differences": differences,
    }


def _verification_difference(path: str, channel: int, expected: float, actual: float, tolerance: float) -> dict[str, Any]:
    return {
        "path": f"{path}[channel={channel}]",
        "channel": channel,
        "expected": _json_safe_number(expected),
        "actual": _json_safe_number(actual),
        "tolerance": tolerance,
        "delta": _json_safe_number(actual - expected),
    }


def _combine_verifications(label: str, *verifications: dict[str, Any]) -> dict[str, Any]:
    checks = []
    differences = []
    for verification in verifications:
        checks.extend(verification.get("checks", []))
        differences.extend(verification.get("differences", []))
    return {"operation": label, "passed": not differences, "checks": checks, "differences": differences}


def _raise_verification_failed(verification: dict[str, Any]) -> None:
    if not verification["passed"]:
        raise CoreVerificationError("write verification failed", verification=verification)


def _attach_verification_if_requested(request: OperationRequest, data: dict[str, Any], verification: dict[str, Any]) -> None:
    if request.parameters.get("verify_after_write", False):
        data["verification"] = verification


def _completion_pulse_requested(request: OperationRequest) -> bool:
    return "completion_pulse_pins" in request.parameters


def _step_completion_pulse_requested(request: OperationRequest) -> bool:
    return _completion_pulse_requested(request) and request.parameters.get("completion_pulse_timing", "segment") == "step"


def _validate_ramp_completion_pulse(request: OperationRequest) -> None:
    timing = request.parameters.get("completion_pulse_timing", "segment")
    if timing not in {"segment", "step", "loop"}:
        raise CoreValidationError("completion-pulse-timing must be segment, step, or loop")
    if timing == "loop" and normalize_loop_count(request.parameters.get("loop_count", 1)) < 2:
        raise CoreValidationError("loop completion pulse requires loop_count of at least 2")


def _validate_completion_pulse_power_supply(power_supply: Any) -> None:
    if isinstance(power_supply, EDU36311APowerSupply):
        raise CoreValidationError("EDU36311A real execution does not support completion-pulse options")
    if not isinstance(power_supply, E36312APowerSupply):
        raise UnsupportedModelError("completion-pulse options require E36312A")


def _validate_requested_completion_pulse_power_supply(
    request: OperationRequest,
    power_supply: Any,
) -> None:
    if _completion_pulse_requested(request):
        _validate_completion_pulse_power_supply(power_supply)


def _completion_pulse_channel(request: OperationRequest, default_channel: int | str | None = None) -> int:
    if "completion_pulse_channel" in request.parameters:
        return normalize_completion_pulse_channel(request.parameters["completion_pulse_channel"])
    if isinstance(default_channel, int):
        return default_channel
    return 1


def _pending_completion_pulse_result(
    request: OperationRequest,
    *,
    channel: int,
) -> dict[str, Any]:
    return trigger_result_payload(
        mode="completion-pulse",
        native=False,
        channel=_completion_pulse_channel(request, channel),
        pins=tuple(request.parameters.get("completion_pulse_pins") or ()),
        polarity=request.parameters.get("completion_pulse_polarity", "positive"),
        source="bus",
        fired=False,
        completed=False,
        restored=None,
        requested=True,
        attempted=False,
        post_pulse_errors=[],
    )


def _maybe_run_completion_pulse(
    request: OperationRequest,
    power_supply: Any,
    *,
    default_channel: int | str | None,
) -> dict[str, Any] | None:
    pins = tuple(request.parameters.get("completion_pulse_pins") or ())
    if not pins:
        return None
    _validate_completion_pulse_power_supply(power_supply)
    channel = _completion_pulse_channel(request, default_channel)
    trigger = run_post_action_completion_pulse(
        power_supply,
        channel=channel,
        pins=pins,
        polarity=request.parameters.get("completion_pulse_polarity", "positive"),
        leave_configured=request.parameters.get("leave_trigger_configured", False),
    )
    return trigger


def _attach_trigger_if_present(data: dict[str, Any], trigger: dict[str, Any] | None) -> None:
    if trigger is not None:
        data["trigger"] = trigger


def _resource_payload(request: OperationRequest, idn: str, **extra: Any) -> dict[str, Any]:
    parsed = parse_idn(idn)
    data = {
        "resource": request.runtime.resource,
        "resource_alias": request.runtime.resource_alias,
        "idn": {
            "raw": idn,
            "manufacturer": parsed.manufacturer,
            "model": parsed.model,
            "serial": parsed.serial,
            "firmware": parsed.firmware,
            "parse_ok": parsed.parse_ok,
        },
    }
    data.update(extra)
    return data


def _driver_step(index: int, action: str, **parameters: Any) -> dict[str, Any]:
    return {"index": index, "type": "driver_action", "action": action, "parameters": parameters}


def _write_output_pair(
    power_supply: Any,
    *,
    channel: int,
    voltage: float,
    current: float,
) -> None:
    if isinstance(power_supply, PSM2010PowerSupply):
        power_supply.set_output_pair(
            channel=channel,
            voltage=voltage,
            current=current,
        )
        return
    power_supply.set_current_limit(channel=channel, current=current)
    power_supply.set_voltage(channel=channel, voltage=voltage)


def _setpoint_write_steps(channel: int | str | None, parameters: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    if parameters.get("current") is not None:
        steps.append(_driver_step(len(steps) + 1, "set_current_limit", channel=channel, current=_json_safe_number(parameters["current"])))
    if parameters.get("voltage") is not None:
        steps.append(_driver_step(len(steps) + 1, "set_voltage", channel=channel, voltage=_json_safe_number(parameters["voltage"])))
    return steps


def _setpoint_verification_actions(parameters: dict[str, Any]) -> tuple[str, ...]:
    actions = []
    if parameters.get("voltage") is not None:
        actions.append("programmed_voltage")
    if parameters.get("current") is not None:
        actions.append("programmed_current")
    return tuple(actions)


def _set_result_fields(parameters: dict[str, Any]) -> dict[str, Any]:
    updated = {
        name: parameters[name]
        for name in ("voltage", "current")
        if parameters.get(name) is not None
    }
    result: dict[str, Any] = {"updated_setpoints": updated}
    if set(updated) == {"voltage", "current"}:
        result.update(updated)
    return result


def _append_write_followup_steps(
    parameters: dict[str, Any],
    steps: list[dict[str, Any]],
    verification_actions: Sequence[str],
    *,
    channels: Sequence[int] | None = None,
) -> None:
    channel = parameters.get("channel")
    next_index = len(steps) + 1
    if parameters.get("settle_ms", 0) > 0:
        steps.append(_driver_step(next_index, "sleep", duration_ms=parameters["settle_ms"]))
        next_index += 1
    if not parameters.get("verify_after_write", False):
        return
    selected_channels = tuple(channels) if channels is not None else ((1, 2, 3) if channel == "all" else (channel,))
    for selected_channel in selected_channels:
        for action in verification_actions:
            steps.append(_driver_step(next_index, action, channel=selected_channel))
            next_index += 1


def _plan_channels(request: OperationRequest, channel: int | str) -> tuple[int, ...]:
    supported = no_hardware_channels(
        request.runtime.planning_model_id,
        request.runtime.planning_profile_id,
    )
    if channel == "all":
        return supported
    if int(channel) not in supported:
        raise UnsupportedChannelError(f"channel {channel} is not supported; supported: {supported}")
    return (int(channel),)


def _require_plan_channels(request: OperationRequest, channel: int | str | None) -> None:
    if channel is None:
        return
    _plan_channels(request, channel)


def _json_safe_number(value: float) -> float | str:
    numeric = float(value)
    if math.isfinite(numeric):
        return numeric
    return str(value)


def _output_plan_description(command: str) -> str:
    descriptions = {
        "set": "Preview setting voltage, current limit, or both.",
        "output-on": "Preview enabling the selected output channel.",
        "output-off": "Preview disabling the selected output channel.",
        "safe-off": "Preview a conservative output-off action without channel expansion.",
        "output-state": "Preview reading the selected output channel state.",
        "cycle-output": "Preview briefly enabling then disabling the selected output channel.",
        "apply": "Preview setting current, voltage, then enabling output.",
        "ramp": "Preview setting current, then stepping voltage setpoints without changing output state.",
        "smoke-output": "Preview a guarded set, output, measure, and safe-off sequence.",
    }
    try:
        return descriptions[command]
    except KeyError as exc:
        raise CoreValidationError(f"unsupported output command {command!r}") from exc
