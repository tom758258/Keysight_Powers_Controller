"""GW Instek PSM-2010 driver foundation."""

from __future__ import annotations

import math

from powers_tool_core.drivers.base import Channel, DriverCapabilities
from powers_tool_core.drivers.generic_scpi import (
    GenericScpiPowerSupply,
    _format_number,
    _parse_bool,
    _parse_float,
)
from powers_tool_core.electrical_ratings import PSM2010_ELECTRICAL_RATINGS
from powers_tool_core.safety import SafetyValidationError, validate_setpoint
from powers_tool_core.setpoint_ranges import PSM2010_SETPOINT_RANGES


class PSM2010PowerSupply(GenericScpiPowerSupply):
    """PSM-2010 single-output, explicit-range SCPI driver."""

    capabilities = DriverCapabilities(
        channels=(1,),
        simulated_measure_channels=(1,),
        real_measure_channels=(1,),
        electrical_ratings=PSM2010_ELECTRICAL_RATINGS,
    )

    def output_range(self, *, channel: Channel = None) -> str:
        """Return the active canonical output range."""

        response = self._query("VOLT:RANG?", channel=channel).upper()
        try:
            return _QUERY_RANGE_NAMES[response]
        except KeyError as exc:
            raise ValueError(f"unsupported PSM-2010 output range response: {response!r}") from exc

    def set_output_range(
        self,
        *,
        channel: Channel = None,
        output_range: str,
    ) -> None:
        """Explicitly select the LOW or HIGH output range."""

        canonical = _canonical_output_range(output_range)
        self._write(f"VOLT:RANG {canonical}", channel=channel)

    def set_voltage(self, *, channel: Channel = None, voltage: float) -> None:
        selected_channel = _psm2010_channel(channel)
        current = self.programmed_current(channel=selected_channel)
        self._prepare_output_pair(
            channel=selected_channel,
            voltage=voltage,
            current=current,
        )
        self._write(f"VOLT {_format_number(voltage)}", channel=selected_channel)

    def set_current_limit(self, *, channel: Channel = None, current: float) -> None:
        selected_channel = _psm2010_channel(channel)
        voltage = self.programmed_voltage(channel=selected_channel)
        self._prepare_output_pair(
            channel=selected_channel,
            voltage=voltage,
            current=current,
        )
        self._write(f"CURR {_format_number(current)}", channel=selected_channel)

    def set_output_pair(
        self,
        *,
        channel: Channel = None,
        voltage: float,
        current: float,
    ) -> None:
        """Resolve one complete target pair before writing either setpoint."""

        selected_channel = _psm2010_channel(channel)
        self._prepare_output_pair(
            channel=selected_channel,
            voltage=voltage,
            current=current,
        )
        self._write(f"CURR {_format_number(current)}", channel=selected_channel)
        self._write(f"VOLT {_format_number(voltage)}", channel=selected_channel)

    def output_on(self, *, channel: Channel = None) -> None:
        selected_channel = _psm2010_channel(channel)
        self._prepare_output_pair(
            channel=selected_channel,
            voltage=self.programmed_voltage(channel=selected_channel),
            current=self.programmed_current(channel=selected_channel),
        )
        super().output_on(channel=selected_channel)

    def _prepare_output_pair(
        self,
        *,
        channel: int,
        voltage: float,
        current: float,
    ) -> str:
        self._validate_driver_setpoint(
            channel=channel,
            voltage=voltage,
            current=current,
        )
        active_range = self.output_range(channel=channel)
        compatible = _compatible_programming_ranges(voltage, current)
        if not compatible:
            raise SafetyValidationError(
                f"PSM-2010 target pair {voltage:g} V / {current:g} A does not fit "
                "the LOW or HIGH programming range"
            )
        if active_range in compatible:
            return active_range
        target_range = compatible[0]
        if self.output_state(channel=channel):
            raise SafetyValidationError(
                f"PSM-2010 output is ON; changing output range from {active_range} "
                f"to {target_range} is not allowed"
            )
        self.set_output_range(channel=channel, output_range=target_range)
        return target_range

    def measure_voltage(self, *, channel: Channel = None) -> float:
        return _parse_float(self._query("MEAS?", channel=channel), "voltage")

    def measure_current(self, *, channel: Channel = None) -> float:
        return _parse_float(self._query("MEAS:CURR?", channel=channel), "current")

    def over_voltage_protection_tripped(self, *, channel: Channel = None) -> bool:
        return _parse_bool(
            self._query("VOLT:PROT:TRIP?", channel=channel),
            "over-voltage protection",
        )

    def over_current_protection_tripped(self, *, channel: Channel = None) -> bool:
        return _parse_bool(
            self._query("CURR:PROT:TRIP?", channel=channel),
            "over-current protection",
        )

    def over_current_protection_delay(self, *, channel: Channel = None) -> float:
        _psm2010_channel(channel)
        raise ValueError("PSM-2010 does not support OCP delay readback")

    def over_current_protection_delay_trigger(self, *, channel: Channel = None) -> str:
        _psm2010_channel(channel)
        raise ValueError("PSM-2010 does not support an OCP delay trigger setting")

    def clear_output_protection(self, *, channel: Channel = None) -> None:
        selected_channel = _psm2010_channel(channel)
        self._write("CURR:PROT:CLE", channel=selected_channel)
        self._write("VOLT:PROT:CLE", channel=selected_channel)

    def set_over_voltage_protection(self, *, channel: Channel = None, voltage: float) -> None:
        selected_channel = _psm2010_channel(channel)
        _validate_psm2010_ovp_level(voltage)
        validate_setpoint(
            channel=selected_channel,
            voltage=voltage,
            limits=self._safety_limits,
        )
        self._write(f"VOLT:PROT {_format_number(voltage)}", channel=selected_channel)

    def set_over_current_protection_delay(self, *, channel: Channel = None, seconds: float) -> None:
        selected_channel = _psm2010_channel(channel)
        if not math.isfinite(seconds) or not 0.1 <= seconds <= 10.0:
            raise ValueError(
                "PSM-2010 over-current protection delay must be from 0.1 through 10 seconds"
            )
        self._write(f"CURR:PROT:DEL {_format_number(seconds)}", channel=selected_channel)

    def set_over_current_protection_delay_trigger(
        self,
        *,
        channel: Channel = None,
        trigger: str,
    ) -> None:
        _psm2010_channel(channel)
        raise ValueError("PSM-2010 does not support an OCP delay trigger setting")

    def _write(self, command: str, *, channel: Channel) -> None:
        super()._write(command, channel=_psm2010_channel(channel))

    def _query(self, command: str, *, channel: Channel) -> str:
        return super()._query(command, channel=_psm2010_channel(channel))


_INPUT_RANGE_NAMES = {
    "LOW": "LOW",
    "P8V": "LOW",
    "HIGH": "HIGH",
    "P20V": "HIGH",
}
_QUERY_RANGE_NAMES = {
    "P8V": "LOW",
    "P20V": "HIGH",
}
_PROGRAMMING_RANGE_BY_NAME = {
    output_range.name: output_range
    for output_range in PSM2010_SETPOINT_RANGES.channels[1].ranges
}
_ELECTRICAL_RANGE_BY_NAME = {
    operating_range.name: operating_range
    for operating_range in PSM2010_ELECTRICAL_RATINGS.channels[1].operating_ranges
}


def _psm2010_channel(channel: Channel) -> int:
    if channel in (None, 1, "1"):
        return 1
    raise ValueError("PSM-2010 channel must be 1")


def _validate_psm2010_ovp_level(voltage: float) -> float:
    """Validate the instrument's fixed OVP programming boundary."""

    try:
        numeric = float(voltage)
    except (TypeError, ValueError) as exc:
        raise SafetyValidationError("PSM-2010 OVP level must be a finite number") from exc
    if not math.isfinite(numeric):
        raise SafetyValidationError("PSM-2010 OVP level must be a finite number")
    if not 0.0 <= numeric <= 22.0:
        raise SafetyValidationError("PSM-2010 OVP level must be from 0 through 22 V")
    return numeric


def _canonical_output_range(output_range: str) -> str:
    if not isinstance(output_range, str):
        raise ValueError("PSM-2010 output range must be LOW, HIGH, P8V, or P20V")
    normalized = output_range.strip().upper()
    try:
        return _INPUT_RANGE_NAMES[normalized]
    except KeyError as exc:
        raise ValueError("PSM-2010 output range must be LOW, HIGH, P8V, or P20V") from exc


def _compatible_programming_ranges(voltage: float, current: float) -> tuple[str, ...]:
    return tuple(
        name
        for name, output_range in _PROGRAMMING_RANGE_BY_NAME.items()
        if output_range.voltage_min <= voltage <= output_range.voltage_max
        and output_range.current_min <= current <= output_range.current_max
        and voltage <= _ELECTRICAL_RANGE_BY_NAME[name].max_voltage
        and current <= _ELECTRICAL_RANGE_BY_NAME[name].max_current
    )
