"""Trigger-specific CLI request, validation, and result helpers."""

from __future__ import annotations

__all__ = [
    "_attach_trigger_if_present",
    "_completion_pulse_channel",
    "_completion_pulse_pins",
    "_completion_pulse_requested",
    "_core_trigger_resource_data",
    "_document_bool_list",
    "_document_float_list",
    "_print_core_trigger_result",
    "_strict_bool",
    "_trigger_list_config_from_args",
    "_trigger_result_payload",
    "_validate_trigger_list_control_args",
    "_validate_trigger_list_limits",
    "_validate_trigger_list_safety",
    "_validate_trigger_step_args",
]

import argparse
from typing import Any

from powers_tool_cli import cli_rendering
from powers_tool_cli.cli_parser import _trigger_pin, _trigger_pins_list
from powers_tool_cli.cli_runtime import _emit_text_lines, _resource_payload
from powers_tool_cli.runtime_mapping import mode_for_args as _mode_for_args
from powers_tool_cli.commands.sequence_run import _load_sequence_document
from powers_tool_core.safety import SafetyLimits, validate_setpoint


def _completion_pulse_requested(args: argparse.Namespace) -> bool:
    return getattr(args, "completion_pulse_pins", None) is not None


def _completion_pulse_pins(args: argparse.Namespace) -> tuple[int, ...]:
    return tuple(getattr(args, "completion_pulse_pins", None) or ())


def _completion_pulse_channel(
    args: argparse.Namespace,
    default_channel: int | str | None = None,
) -> int:
    configured = getattr(args, "completion_pulse_channel", None)
    if configured is not None:
        return int(configured)
    if isinstance(default_channel, int):
        return default_channel
    return 1


def _trigger_result_payload(
    *,
    mode: str,
    native: bool,
    channel: int,
    pins: tuple[int, ...] = (),
    polarity: str = "positive",
    source: str = "bus",
    armed: bool = False,
    fired: bool = False,
    completed: bool = False,
    aborted: bool = False,
    stopped: bool = False,
    stop_reason: str | None = None,
    wait_timeout_ms: int | None = None,
    poll_ms: int | None = None,
    restored: bool | None = None,
    restore_errors: list[str] | None = None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    payload = {
        "mode": mode,
        "native": native,
        "channel": channel,
        "pins": list(pins),
        "polarity": polarity,
        "source": source,
        "armed": armed,
        "fired": fired,
        "completed": completed,
        "aborted": aborted,
        "stopped": stopped,
        "stop_reason": stop_reason,
        "wait_timeout_ms": wait_timeout_ms,
        "poll_ms": poll_ms,
        "restored": restored,
        "restore_errors": restore_errors or [],
    }
    if fallback_reason is not None:
        payload["fallback_reason"] = fallback_reason
    return payload


def _attach_trigger_if_present(
    data: dict[str, Any],
    trigger: dict[str, Any] | None,
) -> None:
    if trigger is not None:
        data["trigger"] = trigger


def _validate_trigger_list_limits(
    *,
    voltages: tuple[float, ...],
    currents: tuple[float, ...],
    dwell: tuple[float, ...],
    count: int,
) -> None:
    if not voltages:
        raise ValueError("trigger LIST requires at least one step")
    if len(voltages) > 100:
        raise ValueError("trigger LIST supports at most 100 steps")
    if len(currents) != len(voltages):
        raise ValueError("current list length must match voltage list length")
    if len(dwell) != len(voltages):
        raise ValueError("dwell list length must match voltage list length")
    if count < 1 or count > 256:
        raise ValueError("LIST count must be between 1 and 256")
    for seconds in dwell:
        if seconds < 0.01 or seconds > 3600:
            raise ValueError("LIST dwell values must be between 0.01 and 3600 seconds")


def _validate_trigger_step_args(args: argparse.Namespace) -> None:
    if _completion_pulse_requested(args):
        raise ValueError(
            "trigger-step does not support --completion-pulse-pins as a completion pulse; "
            "use a one-step trigger-list with --completion-pulse-pins"
        )
    if args.source == "immediate" and args.fire:
        raise ValueError(
            "trigger-step --source immediate does not accept --fire; INIT starts it immediately"
        )
    if args.source not in {"bus", "immediate"} and args.fire:
        raise ValueError("trigger-step --fire is only valid with --source bus")
    if args.wait_complete and args.source == "bus" and not args.fire:
        raise ValueError("trigger-step --wait-complete with BUS source requires --fire")


def _validate_trigger_list_control_args(
    args: argparse.Namespace,
    config: dict[str, Any],
) -> None:
    source = str(config["source"]).lower()
    if source == "immediate" and args.fire:
        raise ValueError(
            "trigger-list --source immediate does not accept --fire; INIT starts it immediately"
        )
    if source not in {"bus", "immediate"} and args.fire:
        raise ValueError("trigger-list --fire is only valid with --source bus")
    if source != "immediate" and not args.fire and not args.leave_trigger_configured:
        raise ValueError("trigger-list arm-only requires --leave-trigger-configured")
    started = source == "immediate" or (source == "bus" and args.fire)
    if started and not args.wait_complete and not args.leave_trigger_configured:
        raise ValueError(
            "trigger-list started without --wait-complete requires --leave-trigger-configured"
        )
    if args.wait_complete and source == "bus" and not args.fire:
        raise ValueError("trigger-list --wait-complete with BUS source requires --fire")


def _validate_trigger_list_safety(
    config: dict[str, Any],
    safety_limits: SafetyLimits | None,
) -> None:
    channel = int(config["channel"])
    for voltage, current in zip(config["voltages"], config["currents"], strict=True):
        validate_setpoint(
            channel=channel,
            voltage=voltage,
            current=current,
            limits=safety_limits,
        )


def _trigger_list_config_from_args(args: argparse.Namespace) -> dict[str, Any]:
    document: dict[str, Any] = {}
    if getattr(args, "file", None):
        document = _load_sequence_document(args.file)
    channel = args.channel if args.channel is not None else document.get("channel")
    if channel is None:
        raise ValueError("trigger-list requires --channel or channel in --file")
    voltages = args.voltage_list or _document_float_list(
        document, "voltages", "voltage_list", "voltage"
    )
    currents = args.current_list or _document_float_list(
        document, "currents", "current_list", "current"
    )
    dwell = args.dwell_list or _document_float_list(
        document, "dwell", "dwells", "dwell_list"
    )
    bost = getattr(args, "bost_list", None) or _document_bool_list(document, "bost_list")
    eost = getattr(args, "eost_list", None) or _document_bool_list(document, "eost_list")
    steps = document.get("steps")
    if (voltages is None or currents is None or dwell is None) and steps is not None:
        if not isinstance(steps, list) or not steps:
            raise ValueError("trigger-list steps in --file must be a non-empty list")
        step_voltages: list[float] = []
        step_currents: list[float] = []
        step_dwell: list[float] = []
        step_bost: list[bool] = []
        step_eost: list[bool] = []
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ValueError(f"trigger-list step {index} must be a mapping")
            try:
                step_voltages.append(float(step["voltage"]))
                step_currents.append(float(step["current"]))
                step_dwell.append(float(step["dwell"]))
                step_bost.append(
                    _strict_bool(step.get("bost", False), f"trigger-list step {index} bost")
                )
                step_eost.append(
                    _strict_bool(step.get("eost", False), f"trigger-list step {index} eost")
                )
            except KeyError as exc:
                raise ValueError(f"trigger-list step {index} missing {exc.args[0]}") from exc
        if voltages is None:
            voltages = tuple(step_voltages)
        if currents is None:
            currents = tuple(step_currents)
        if dwell is None:
            dwell = tuple(step_dwell)
        if bost is None:
            bost = tuple(step_bost)
        if eost is None:
            eost = tuple(step_eost)
    if voltages is None:
        raise ValueError("trigger-list requires --voltage-list or voltages in --file")
    if currents is None:
        raise ValueError("trigger-list requires --current-list or currents in --file")
    if dwell is None:
        raise ValueError("trigger-list requires --dwell-list or dwell in --file")
    if len(currents) == 1 and len(voltages) > 1:
        currents = tuple(currents[0] for _ in voltages)
    if len(dwell) == 1 and len(voltages) > 1:
        dwell = tuple(dwell[0] for _ in voltages)
    pins = _completion_pulse_pins(args)
    if not pins:
        doc_pins = document.get("pins", document.get("completion_pulse_pins"))
        if doc_pins is not None:
            pins = (
                tuple(_trigger_pin(str(pin)) for pin in doc_pins)
                if isinstance(doc_pins, list)
                else _trigger_pins_list(str(doc_pins))
            )
    source = args.source or str(document.get("source", "bus"))
    final_eost_pulse = bool(pins)
    count = args.count if args.count != 1 else int(document.get("count", 1))
    polarity = args.completion_pulse_polarity or str(document.get("polarity", "positive"))
    canonical_requested = any(
        value is not None
        for value in (
            getattr(args, "bost_list", None),
            getattr(args, "eost_list", None),
            getattr(args, "trigger_output_pins", None),
            getattr(args, "trigger_output_polarity", None),
            document.get("bost_list"),
            document.get("eost_list"),
            document.get("trigger_output_pins"),
            document.get("trigger_output_polarity"),
        )
    ) or (
        steps is not None
        and any(
            isinstance(step, dict) and ("bost" in step or "eost" in step)
            for step in steps
        )
    )
    if canonical_requested and pins:
        raise ValueError(
            "trigger-list completion-pulse fields cannot be mixed with BOST/EOST trigger-output fields"
        )
    if canonical_requested:
        pins = getattr(args, "trigger_output_pins", None) or tuple(
            document.get("trigger_output_pins") or ()
        )
        polarity = getattr(args, "trigger_output_polarity", None) or str(
            document.get("trigger_output_polarity", "positive")
        )
        bost = bost if bost is not None else tuple(False for _ in voltages)
        eost = eost if eost is not None else tuple(False for _ in voltages)
        if len(bost) != len(voltages):
            raise ValueError("BOST list length must match voltage list length")
        if len(eost) != len(voltages):
            raise ValueError("EOST list length must match voltage list length")
        if (any(bost) or any(eost)) and not pins:
            raise ValueError("trigger-list BOST/EOST pulses require explicit trigger output pins")
    config = {
        "channel": int(channel),
        "source": str(source).lower(),
        "voltages": tuple(float(value) for value in voltages),
        "currents": tuple(float(value) for value in currents),
        "dwell": tuple(float(value) for value in dwell),
        "pins": pins,
        "polarity": polarity,
        "final_eost_pulse": final_eost_pulse if not canonical_requested else False,
        "count": count,
    }
    if canonical_requested:
        config.update({"begin_outputs": tuple(bost), "end_outputs": tuple(eost)})
    return config


def _document_float_list(
    document: dict[str, Any],
    *keys: str,
) -> tuple[float, ...] | None:
    for key in keys:
        if key not in document:
            continue
        value = document[key]
        if isinstance(value, list):
            return tuple(float(item) for item in value)
        if isinstance(value, tuple):
            return tuple(float(item) for item in value)
        return (float(value),)
    return None


def _document_bool_list(
    document: dict[str, Any],
    key: str,
) -> tuple[bool, ...] | None:
    if key not in document:
        return None
    value = document[key]
    if not isinstance(value, list):
        raise ValueError(f"trigger-list {key} must be a list")
    return tuple(_strict_bool(item, f"trigger-list {key}") for item in value)


def _strict_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _core_trigger_resource_data(
    args: argparse.Namespace,
    data: dict[str, Any],
) -> dict[str, Any]:
    if "plan" in data:
        return data
    resolved_resource = data.pop("_resource", args.resource)
    idn_raw = data.pop("idn", None)
    payload: dict[str, Any] = {
        "resource": (
            resolved_resource
            if args.command == "trigger-pulse" or idn_raw is None
            else _resource_payload(
                resolved_resource,
                simulated=args.simulate,
                reachable=True,
                idn_raw=idn_raw,
            )
        )
    }
    if args.command == "trigger-pulse":
        payload.update(data)
    elif args.command == "trigger-status":
        payload.update(data)
    elif args.command == "trigger-list":
        payload["steps"] = data["steps"]
        payload["trigger"] = data["trigger"]
    elif args.command == "trigger-step":
        payload["trigger"] = data["trigger"]
    elif args.command == "trigger-fire":
        payload["trigger"] = data["trigger"]
    elif args.command == "trigger-abort":
        payload["channel"] = args.channel
        payload["channels"] = data["channels"]
        payload["aborted"] = True
        payload["errors"] = data.get("errors", [])
        payload["read_count"] = data.get("read_count", 0)
    else:
        raise ValueError(f"unsupported trigger command: {args.command}")
    return payload


def _print_core_trigger_result(
    args: argparse.Namespace,
    data: dict[str, Any],
) -> None:
    _emit_text_lines(
        cli_rendering.format_core_trigger_result(
            command=args.command,
            resource=args.resource,
            channel=getattr(args, "channel", None),
            mode=_mode_for_args(args),
            data=data,
        )
    )
