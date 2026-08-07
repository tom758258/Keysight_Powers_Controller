"""Bounded telemetry acquisition shared by command adapters."""

from __future__ import annotations

from datetime import datetime, timezone
import inspect
import time
from typing import Any, Callable

from powers_tool_core.cancellation import interruptible_sleep, raise_if_cancelled
from powers_tool_core.connection import open_resource, serial_open_kwargs
from powers_tool_core.core import (
    CommandCancelled,
    CoreIoError,
    CoreValidationError,
    OperationRequest,
    UnsupportedChannelError,
)
from powers_tool_core.discovery import resource_payload
from powers_tool_core.errors import VisaConnectionError
from powers_tool_core.factory import create_power_supply
from powers_tool_core.live_support import enforce_live_support_for_idn
from powers_tool_core.models import parse_idn
from powers_tool_core.testing.simulator import SimulatedResourceManager
from powers_tool_core.workflow_validation import ProgressReporter


TELEMETRY_ROW_FIELDS = (
    "timestamp",
    "resource",
    "resource_alias",
    "model",
    "serial",
    "channel",
    "programmed_voltage",
    "programmed_current",
    "measured_voltage",
    "measured_current",
    "output_enabled",
    "errors",
)

SampleReporter = Callable[[dict[str, Any]], None]


def run_telemetry(
    request: OperationRequest,
    *,
    opener: Callable[..., Any] = open_resource,
    stop_requested: Callable[[], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    scpi_logger: Callable[[str, str, str], None] | None = None,
    sample_reporter: SampleReporter | None = None,
    progress_reporter: ProgressReporter | None = None,
) -> dict[str, Any]:
    """Collect bounded telemetry rows and return a collection summary."""

    if request.command != "log":
        raise CoreValidationError(f"unsupported telemetry command {request.command!r}")
    if request.runtime.dry_run:
        raise CoreValidationError("log does not support dry-run execution")
    if request.runtime.resource is None:
        raise CoreValidationError("log requires a resource")

    opened = False
    samples_written = 0
    channels: tuple[int, ...] = ()
    idn_raw: str | None = None
    started = time.monotonic()

    def summary(*, stopped: bool, stop_reason: str) -> dict[str, Any]:
        return {
            "resource": resource_payload(
                request.runtime.resource or "",
                simulated=request.runtime.simulate,
                reachable=opened,
                idn_raw=idn_raw,
            ),
            "resource_alias": request.runtime.resource_alias,
            "channel": request.parameters.get("channel"),
            "channels": list(channels),
            "samples_requested": request.parameters.get("samples"),
            "duration_sec": request.parameters.get("duration_sec"),
            "interval_sec": request.parameters["interval_sec"],
            "samples_written": samples_written,
            "stopped": stopped,
            "stop_reason": stop_reason,
        }

    try:
        raise_if_cancelled(stop_requested)
        with _open_telemetry_resource(request, opener) as instrument:
            opened = True
            if request.runtime.log_scpi and scpi_logger is not None:
                from powers_tool_core.operations import ScpiLoggingSession

                instrument = ScpiLoggingSession(
                    request.runtime.resource, instrument, scpi_logger
                )

            idn_raw = instrument.query("*IDN?")
            if not request.runtime.simulate:
                enforce_live_support_for_idn(request, idn_raw, command="log")
            idn = parse_idn(idn_raw)
            power_supply = create_power_supply(instrument, idn_raw)
            channels = _telemetry_channels(request, power_supply.capabilities.channels)
            started = time.monotonic()

            while _should_collect(request, samples_written, started):
                raise_if_cancelled(stop_requested)
                for channel in channels:
                    row = _read_telemetry_row(
                        request, power_supply, idn, channel=channel
                    )
                    if sample_reporter is not None:
                        sample_reporter(row)
                samples_written += 1
                _report_progress(
                    progress_reporter,
                    samples_written=samples_written,
                    samples_requested=request.parameters.get("samples"),
                )
                raise_if_cancelled(stop_requested)
                if not _should_collect(request, samples_written, started):
                    break
                interruptible_sleep(
                    request.parameters["interval_sec"],
                    sleep=sleep,
                    stop_requested=stop_requested,
                )
        return summary(stopped=False, stop_reason="completed")
    except (CommandCancelled, KeyboardInterrupt) as exc:
        raise CommandCancelled(
            "telemetry collection cancelled",
            data=summary(stopped=True, stop_reason="cancelled"),
        ) from exc
    except CoreValidationError:
        raise
    except VisaConnectionError as exc:
        raise CoreIoError(f"log failed: {exc}", opened=opened) from exc
    except (ValueError, TypeError) as exc:
        raise CoreIoError(f"log failed: {exc}", opened=opened) from exc


def _should_collect(request: OperationRequest, samples_written: int, started: float) -> bool:
    samples = request.parameters.get("samples")
    if samples is not None and samples_written >= samples:
        return False
    duration_sec = request.parameters.get("duration_sec")
    if duration_sec is not None and samples_written > 0:
        return (time.monotonic() - started) < duration_sec
    return True


def _telemetry_channels(
    request: OperationRequest, supported_channels: tuple[int, ...]
) -> tuple[int, ...]:
    requested: Any = request.parameters.get("channels", request.parameters.get("channel"))
    channels = supported_channels if requested == "all" else requested
    if type(channels) is int:
        channels = (channels,)
    channels = tuple(channels)
    for channel in channels:
        if channel not in supported_channels:
            raise UnsupportedChannelError(
                f"channel {channel} is not supported; supported: {supported_channels}"
            )
    return channels


def _read_telemetry_row(
    request: OperationRequest, power_supply: Any, idn: Any, *, channel: int
) -> dict[str, Any]:
    errors = power_supply.check_errors(20)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "resource": request.runtime.resource,
        "resource_alias": request.runtime.resource_alias or "",
        "model": idn.model or "",
        "serial": idn.serial or "",
        "channel": channel,
        "programmed_voltage": power_supply.programmed_voltage(channel=channel),
        "programmed_current": power_supply.programmed_current(channel=channel),
        "measured_voltage": power_supply.measure_voltage(channel=channel),
        "measured_current": power_supply.measure_current(channel=channel),
        "output_enabled": power_supply.output_state(channel=channel),
        "errors": "; ".join(errors),
    }


def _report_progress(
    reporter: ProgressReporter | None,
    *,
    samples_written: int,
    samples_requested: int | None,
) -> None:
    if reporter is None:
        return
    payload: dict[str, int | float] = {"samples_written": samples_written}
    if samples_requested is not None:
        payload.update(
            {
                "samples_requested": samples_requested,
                "percent": min(100, samples_written * 100 // samples_requested),
            }
        )
    reporter(payload)


def _open_telemetry_resource(
    request: OperationRequest, opener: Callable[..., Any]
) -> Any:
    resource_manager = SimulatedResourceManager() if request.runtime.simulate else None
    kwargs = {
        "backend": request.runtime.backend,
        "timeout_ms": request.runtime.timeout_ms,
        **serial_open_kwargs(
            serial_options=request.runtime.serial_options,
            serial_remote=request.runtime.serial_remote,
            serial_local_on_close=request.runtime.serial_local_on_close,
        ),
    }
    if resource_manager is not None and _accepts_resource_manager(opener):
        return opener(request.runtime.resource, resource_manager, **kwargs)
    return opener(request.runtime.resource, **kwargs)


def _accepts_resource_manager(opener: Callable[..., Any]) -> bool:
    try:
        parameters = list(inspect.signature(opener).parameters.values())
    except (TypeError, ValueError):
        return False
    if any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters):
        return True
    return len(parameters) >= 2 and parameters[1].name in {
        "resource_manager",
        "manager",
    }
