"""GW Instek PSM-2010 driver foundation."""

from __future__ import annotations

from powers_tool_core.drivers.base import Channel, DriverCapabilities
from powers_tool_core.drivers.generic_scpi import (
    GenericScpiPowerSupply,
    _format_number,
    _parse_float,
)
from powers_tool_core.electrical_ratings import PSM2010_ELECTRICAL_RATINGS
from powers_tool_core.safety import SafetyValidationError


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
        self._validate_driver_setpoint(channel=selected_channel, voltage=voltage)
        active_range = self.output_range(channel=selected_channel)
        _validate_active_range_setpoint(active_range, voltage=voltage)
        self._write(f"VOLT {_format_number(voltage)}", channel=selected_channel)

    def set_current_limit(self, *, channel: Channel = None, current: float) -> None:
        selected_channel = _psm2010_channel(channel)
        self._validate_driver_setpoint(channel=selected_channel, current=current)
        active_range = self.output_range(channel=selected_channel)
        _validate_active_range_setpoint(active_range, current=current)
        self._write(f"CURR {_format_number(current)}", channel=selected_channel)

    def measure_voltage(self, *, channel: Channel = None) -> float:
        return _parse_float(self._query("MEAS?", channel=channel), "voltage")

    def measure_current(self, *, channel: Channel = None) -> float:
        return _parse_float(self._query("MEAS:CURR?", channel=channel), "current")

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
_ELECTRICAL_RANGE_BY_NAME = {
    operating_range.name: operating_range
    for operating_range in PSM2010_ELECTRICAL_RATINGS.channels[1].operating_ranges
}


def _psm2010_channel(channel: Channel) -> int:
    if channel in (None, 1, "1"):
        return 1
    raise ValueError("PSM-2010 channel must be 1")


def _canonical_output_range(output_range: str) -> str:
    if not isinstance(output_range, str):
        raise ValueError("PSM-2010 output range must be LOW, HIGH, P8V, or P20V")
    normalized = output_range.strip().upper()
    try:
        return _INPUT_RANGE_NAMES[normalized]
    except KeyError as exc:
        raise ValueError("PSM-2010 output range must be LOW, HIGH, P8V, or P20V") from exc


def _validate_active_range_setpoint(
    active_range: str,
    *,
    voltage: float | None = None,
    current: float | None = None,
) -> None:
    rating = _ELECTRICAL_RANGE_BY_NAME[active_range]
    if voltage is not None and voltage > rating.max_voltage:
        raise SafetyValidationError(
            f"voltage {voltage:g} exceeds PSM-2010 {active_range} range maximum "
            f"{rating.max_voltage:g} V"
        )
    if current is not None and current > rating.max_current:
        raise SafetyValidationError(
            f"current {current:g} exceeds PSM-2010 {active_range} range maximum "
            f"{rating.max_current:g} A"
        )
