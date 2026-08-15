"""Pure human-readable text formatters for CLI success paths."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


__all__ = [
    "format_core_output_result",
    "format_core_trigger_result",
    "format_capabilities",
    "format_clear_protection_success",
    "format_clear_success",
    "format_doctor",
    "format_error_queue",
    "format_execution_summary_notice",
    "format_hardware_report_success",
    "format_identify",
    "format_list_resources",
    "format_measure",
    "format_measure_all",
    "format_log_success",
    "format_output_plan",
    "format_protection_status",
    "format_protection_set_success",
    "format_read_status",
    "format_readback",
    "format_ramp_list_summary",
    "format_restore_from_snapshot_success",
    "format_safety_inspect",
    "format_scpi_plan",
    "format_sequence_summary",
    "format_sequence_lint_summary",
    "format_snapshot",
    "format_snapshot_diff",
    "format_validate_readonly",
    "format_verify",
]


def format_core_output_result(
    *,
    command: str,
    resource: str,
    channel: int | str | None,
    current: object,
    voltage: object,
    no_output: bool,
    resource_data: Mapping[str, Any],
    value_to_text: Callable[[object], str],
) -> tuple[str, ...]:
    lines = [f"Resource: {resource}"]
    if command == "ramp" and "channels" in resource_data:
        lines.append("Channels: " + ", ".join(str(item) for item in resource_data["channels"]))
    else:
        lines.append(f"Channel: {channel}")
    if command == "set":
        lines.extend(
            [
                f"Current limit: {value_to_text(current)} A",
                f"Voltage: {value_to_text(voltage)} V",
            ]
        )
    elif command == "apply":
        lines.extend(
            [
                f"Current limit: {value_to_text(current)} A",
                f"Voltage: {value_to_text(voltage)} V",
                f"Output enabled: {str(not no_output).lower()}",
            ]
        )
    elif command == "output-on":
        lines.append("Output enabled: True")
    elif command == "output-off":
        lines.append("Output enabled: False")
    elif command == "safe-off":
        lines.extend(
            f"Channel {output['channel']}: Output enabled: {output['enabled']}"
            for output in resource_data["outputs"]
        )
    elif command == "output-state":
        if channel == "all":
            lines.extend(
                f"Channel {output['channel']}: Output enabled: {str(output['enabled']).lower()}"
                for output in resource_data["outputs"]
            )
        else:
            lines.append(f"Output enabled: {str(resource_data['output_enabled']).lower()}")
    elif command == "cycle-output":
        lines.append("Cycle complete: true")
    elif command == "ramp":
        lines.append(f"Steps: {resource_data['steps']}")
    elif command == "smoke-output":
        measurements = resource_data["measurements"]
        lines.extend(
            [
                f"Measured voltage: {value_to_text(measurements['voltage'])} V",
                f"Measured current: {value_to_text(measurements['current'])} A",
                f"Final output enabled: {resource_data['output']['final_enabled']}",
            ]
        )
    else:
        raise ValueError(f"unsupported core output command: {command}")
    return tuple(lines)


def format_core_trigger_result(
    *,
    command: str,
    resource: str,
    channel: int | str | None,
    mode: str,
    data: Mapping[str, Any],
) -> tuple[str, ...]:
    if "plan" in data:
        return format_scpi_plan(data["plan"], mode=mode, dry_run=True)
    if command == "trigger-pulse":
        return tuple(
            [
                f"Resource: {resource}",
                "Pins: " + ", ".join(str(pin) for pin in data["pins"]),
                f"Exclusive pins: {str(data['exclusive_pins']).lower()}",
                f"Polarity: {data['polarity']}",
                "Triggered: True",
            ]
        )
    if command == "trigger-status":
        return tuple([f"Resource: {resource}", f"Channel: {data['channel']}"])
    if command == "trigger-list":
        return tuple([f"Resource: {resource}", f"Steps: {data['steps']}"])
    if command == "trigger-step":
        return tuple(
            [
                f"Resource: {resource}",
                f"Triggered: {str(data['trigger']['completed']).lower()}",
            ]
        )
    if command == "trigger-fire":
        return tuple(["Triggered: true"])
    if command == "trigger-abort":
        return tuple([f"Channel {channel}: aborted"])
    return ()


def format_output_plan(
    plan: Mapping[str, Any],
    *,
    mode: str,
    dry_run: bool,
    value_to_text: Callable[[object], str],
) -> tuple[str, ...]:
    label = "Dry-run" if dry_run else "Simulation"
    target = plan["target"]
    lines = [
        f"{label} plan for {plan['operation']['name']}",
        f"Mode: {mode}",
        f"Resource: {target['resource']}",
    ]
    if "channels" in target:
        lines.append(
            "Channels: " + ", ".join(str(channel) for channel in target["channels"])
        )
    else:
        lines.append(f"Channel: {target['channel']}")
    lines.extend(
        [
            f"Hardware touched: {str(plan['hardware_touched']).lower()}",
            "Steps:",
        ]
    )
    for step in plan["steps"]:
        parameters = " ".join(
            f"{name}={value_to_text(value)}"
            for name, value in step["parameters"].items()
        )
        lines.append(f"{step['index']}. {step['action']} {parameters}".rstrip())
    return tuple(lines)


def format_scpi_plan(
    plan: Mapping[str, Any],
    *,
    mode: str,
    dry_run: bool,
) -> tuple[str, ...]:
    label = "Dry-run" if dry_run else "Simulation"
    lines = [
        f"{label} plan for {plan['operation']['name']}",
        f"Mode: {mode}",
        f"Resource: {plan['target']['resource']}",
        f"Hardware touched: {str(plan['hardware_touched']).lower()}",
        "Steps:",
    ]
    lines.extend(f"{step['index']}. {step['command']}" for step in plan["steps"])
    return tuple(lines)


def format_sequence_summary(data: Mapping[str, Any]) -> tuple[str, ...]:
    resource = data["resource"]
    resource_name = resource if isinstance(resource, str) else resource.get("name")
    return tuple(
        [
            f"Resource: {resource_name}",
            f"Status: {data['status']}",
            f"Completed steps: {data['completed_steps']}",
        ]
    )


def format_list_resources(
    resources: Sequence[Mapping[str, Any]],
    *,
    live_only: bool,
) -> tuple[str, ...]:
    if live_only:
        lines = ["Live resources:"]
        if not resources:
            lines.append("  <none>")
        else:
            for resource in resources:
                idn = resource["idn"]
                lines.append(f"  {resource['name']}")
                lines.append(f"    IDN: {idn['raw']}")
        return tuple(lines)
    if not resources:
        return tuple(["No VISA resources found."])
    return tuple(str(resource["name"]) for resource in resources)


def format_verify(idn_raw: object) -> tuple[str, ...]:
    return tuple([str(idn_raw)])


def format_execution_summary_notice(
    execution_units: int,
    warning: str | None,
) -> tuple[str, ...]:
    lines = [f"Execution units: {execution_units:,} (maximum 1,000,000)."]
    if warning is not None:
        lines.append(f"Warning: {warning}")
    return tuple(lines)


def format_error_queue(errors: Sequence[object]) -> tuple[str, ...]:
    if not errors:
        return tuple(["No instrument errors."])
    return tuple(str(error) for error in errors)


def format_measure(
    measurements: Mapping[str, Any],
    *,
    value_to_text: Callable[[object], str],
) -> tuple[str, ...]:
    return (
        f"Voltage: {value_to_text(measurements['voltage'])} V",
        f"Current: {value_to_text(measurements['current'])} A",
    )


def format_measure_all(
    channels: Sequence[Mapping[str, Any]],
    *,
    value_to_text: Callable[[object], str],
) -> tuple[str, ...]:
    lines = []
    for channel in channels:
        measurements = channel["measurements"]
        lines.append(
            f"Channel {channel['channel']}: "
            f"{value_to_text(measurements['voltage'])} V, "
            f"{value_to_text(measurements['current'])} A"
        )
    return tuple(lines)


def format_read_status(
    errors: Sequence[object],
    outputs: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    lines = [f"Error: {error}" for error in errors] if errors else ["Errors: none"]
    lines.extend(
        f"Channel {output['channel']}: Output enabled: {str(output['enabled']).lower()}"
        for output in outputs
    )
    return tuple(lines)


def format_readback(
    resource: object,
    channels: Sequence[Mapping[str, Any]],
    *,
    value_to_text: Callable[[object], str],
) -> tuple[str, ...]:
    lines = [f"Resource: {resource}"]
    for channel in channels:
        setpoints = channel["setpoints"]
        lines.append(
            f"Channel {channel['channel']}: "
            f"{value_to_text(setpoints['voltage'])} V, "
            f"{value_to_text(setpoints['current'])} A"
        )
    return tuple(lines)


def format_protection_status(data: Mapping[str, Any]) -> tuple[str, ...]:
    protection = data["protection"]
    lines = [
        f"Resource: {data['resource']}",
        f"Over-voltage tripped: {str(protection['over_voltage_tripped']).lower()}",
        f"Over-current tripped: {str(protection['over_current_tripped']).lower()}",
    ]
    lines.extend(
        f"Channel {output['channel']}: "
        f"Output enabled: {str(output['enabled']).lower()}, "
        f"disabled with protection: {str(output['disabled_with_protection']).lower()}"
        for output in data["outputs"]
    )
    return tuple(lines)


def format_identify(resource: object, data: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        f"Resource: {resource}",
        f"IDN: {data['idn']['raw']}",
        f"Options: {data['options']}",
        f"SCPI version: {data['scpi_version']}",
        f"Remote/local state: {data['remote_lockout_state']}",
    )


def format_validate_readonly(
    data: Mapping[str, Any],
    *,
    channel_order: Sequence[object],
    value_to_text: Callable[[object], str],
) -> tuple[str, ...]:
    idn = data["resource"]["idn"] or {}
    lines = [
        f"Resource: {data['resource']['name']}",
        f"Model: {idn.get('model')}",
        f"Driver: {data['driver']['class']} ({data['driver']['reason']})",
        f"Validation read-only: {data['hardware_validation']['read_only']}",
        f"Errors: {len(data['errors'])}",
    ]
    for channel in channel_order:
        output = next(item for item in data["outputs"] if item["channel"] == channel)
        setpoints = next(item for item in data["readback"] if item["channel"] == channel)["setpoints"]
        measured = next(item for item in data["measurements"] if item["channel"] == channel)["measurements"]
        lines.append(
            f"Channel {channel}: output={str(output['enabled']).lower()}, "
            f"set={value_to_text(setpoints['voltage'])} V/"
            f"{value_to_text(setpoints['current'])} A, "
            f"meas={value_to_text(measured['voltage'])} V/"
            f"{value_to_text(measured['current'])} A"
        )
    return tuple(lines)


def format_snapshot(
    data: Mapping[str, Any],
    *,
    comparison: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    reported = data["reported_identity"]
    resolved = data["resolved_identity"]
    lines = [
        f"Resource: {data['resource']}",
        f"Model: {resolved.get('display_name') or resolved['model_id']}",
        f"Reported manufacturer: {reported['manufacturer']}",
        f"Reported model: {reported['model']}",
        f"Serial: {reported['serial']}",
        f"Errors: {len(data['errors'])}",
    ]
    lines.extend(
        f"Channel {output['channel']}: Output enabled: {str(output['enabled']).lower()}"
        for output in data["outputs"]
    )
    if comparison is not None:
        lines.append(f"Snapshot comparison passed: {str(comparison['passed']).lower()}")
    return tuple(lines)


def format_snapshot_diff(
    data: Mapping[str, Any],
    *,
    summary: bool,
) -> tuple[str, ...]:
    lines = [
        f"Changed: {str(data['changed']).lower()}",
        f"Changes: {data['change_count']}",
    ]
    if summary:
        lines.extend(f"{category}: {count}" for category, count in data["summary"].items())
        return tuple(lines)
    for difference in data["differences"]:
        channel = difference.get("channel")
        channel_text = f" channel {channel}" if channel is not None else ""
        lines.append(
            f"{difference['category']}{channel_text} {difference['field']}: "
            f"{difference['before']} -> {difference['after']}"
        )
    return tuple(lines)


def format_doctor(
    data: Mapping[str, Any],
    *,
    pyvisa_available: object,
) -> tuple[str, ...]:
    return (
        f"Python: {data['python']['version']}",
        f"Package: {data['package']['version']}",
        f"PyVISA: {str(pyvisa_available).lower()}",
        f"Simulator resources: {len(data['simulator']['resources'])}",
    )


def format_capabilities(data: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        f"Driver: {data['driver']['class']}",
        f"Channels: {', '.join(str(channel) for channel in data['channels'])}",
    )


def format_safety_inspect(data: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        f"Resource: {data['resource']}",
        f"Limits: {data['limits']}",
        f"Output allowed: {str(data['output_affecting_allowed']).lower()}",
    )


def format_clear_success(resource: object) -> tuple[str, ...]:
    return (f"Cleared instrument status for {resource}",)


def format_clear_protection_success(
    resource: object,
    cleared_channels: Sequence[object],
) -> tuple[str, ...]:
    return (
        f"Resource: {resource}",
        "Cleared channels: " + ", ".join(str(channel) for channel in cleared_channels),
    )


def format_protection_set_success(
    resource: object,
    channels: Sequence[Mapping[str, Any]],
    *,
    value_to_text: Callable[[object], str],
) -> tuple[str, ...]:
    lines = [f"Resource: {resource}"]
    for channel in channels:
        protection = channel["protection"]
        lines.append(
            f"Channel {channel['channel']}: "
            f"OVP={value_to_text(protection['ovp_voltage'])}, "
            f"OCP={value_to_text(protection['ocp_enabled'])}, "
            f"OCP delay={value_to_text(protection['ocp_delay'])}, "
            f"OCP delay trigger={value_to_text(protection['ocp_delay_trigger'])}"
        )
    return tuple(lines)


def format_hardware_report_success(
    report_json: object,
    summary_md: object,
    report: Mapping[str, Any],
) -> tuple[str, ...]:
    return (
        f"Report: {report_json}",
        f"Summary: {summary_md}",
        f"Result: {report['result']}",
    )


def format_restore_from_snapshot_success(
    resource: object,
    restored_channels: Sequence[object],
) -> tuple[str, ...]:
    return (
        f"Resource: {resource}",
        "Restored channels: " + ", ".join(str(channel) for channel in restored_channels),
    )


def format_log_success(
    resource: object,
    csv_path: object,
    result: Mapping[str, Any],
) -> tuple[str, ...]:
    return (
        f"Resource: {resource}",
        f"CSV: {csv_path}",
        f"Samples written: {result['samples_written']}",
        f"Stopped: {str(result['stopped']).lower()}",
    )


def format_sequence_lint_summary(data: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        f"Status: {data['status']}",
        f"Sequence version: {data['sequence_version']}",
        f"Steps: {data['step_count']}",
    )


def format_ramp_list_summary(data: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        f"Status: {data['status']}",
        f"Ramp list version: {data['ramp_list_version']}",
        f"Segments: {data['segment_count']}",
        f"Completed segments: {data['completed_segments']}",
    )
