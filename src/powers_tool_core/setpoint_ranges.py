"""Official output setpoint programming ranges."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class OutputSetpointRange:
    """Programming range for one output channel and optional range setting."""

    name: str
    aliases: tuple[str, ...]
    rated_range_label: str | None
    voltage_min: float
    voltage_max: float
    voltage_default: float
    voltage_reset: float
    current_min: float
    current_max: float
    current_default: float
    current_reset: float
    current_min_keyword_value: float | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "name": self.name,
            "aliases": list(self.aliases),
            "rated_range_label": self.rated_range_label,
            "voltage_min": self.voltage_min,
            "voltage_max": self.voltage_max,
            "voltage_default": self.voltage_default,
            "voltage_reset": self.voltage_reset,
            "current_min": self.current_min,
            "current_max": self.current_max,
            "current_default": self.current_default,
            "current_reset": self.current_reset,
        }
        if self.current_min_keyword_value is not None:
            data["current_min_keyword_value"] = self.current_min_keyword_value
        return data


@dataclass(frozen=True)
class ChannelSetpointRanges:
    """Official programming ranges for one output channel."""

    channel: int
    output_identifier: str
    ranges: tuple[OutputSetpointRange, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "output_identifier": self.output_identifier,
            "ranges": [setpoint_range.to_dict() for setpoint_range in self.ranges],
        }


@dataclass(frozen=True)
class ModelSetpointRanges:
    """Verified model setpoint ranges and their official document source."""

    model: str
    channels: Mapping[int, ChannelSetpointRanges]
    range_basis: str
    document_title: str
    publication_id: str
    publication_date: str
    source_pages: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def channel(self, channel: int) -> ChannelSetpointRanges | None:
        return self.channels.get(channel)

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "range_basis": self.range_basis,
            "source": {
                "document_title": self.document_title,
                "publication_id": self.publication_id,
                "publication_date": self.publication_date,
                "pages": list(self.source_pages),
            },
            "notes": list(self.notes),
            "channels": [channel.to_dict() for channel in self.channels.values()],
        }


def _single_range(
    *,
    voltage_max: float,
    current_max: float,
    current_default: float,
    current_min_keyword_value: float,
) -> OutputSetpointRange:
    return OutputSetpointRange(
        name="fixed",
        aliases=(),
        rated_range_label=None,
        voltage_min=0.0,
        voltage_max=voltage_max,
        voltage_default=0.0,
        voltage_reset=0.0,
        current_min=0.0,
        current_max=current_max,
        current_default=current_default,
        current_reset=current_default,
        current_min_keyword_value=current_min_keyword_value,
    )


def _model_ranges(
    model: str,
    values: tuple[tuple[int, str, OutputSetpointRange | tuple[OutputSetpointRange, ...]], ...],
    *,
    range_basis: str,
    document_title: str,
    publication_id: str,
    publication_date: str,
    source_pages: tuple[str, ...],
    notes: tuple[str, ...] = (),
) -> ModelSetpointRanges:
    channels: dict[int, ChannelSetpointRanges] = {}
    for channel, identifier, ranges in values:
        channel_ranges = ranges if isinstance(ranges, tuple) else (ranges,)
        channels[channel] = ChannelSetpointRanges(channel, identifier, channel_ranges)
    return ModelSetpointRanges(
        model=model,
        channels=MappingProxyType(channels),
        range_basis=range_basis,
        document_title=document_title,
        publication_id=publication_id,
        publication_date=publication_date,
        source_pages=source_pages,
        notes=notes,
    )


E36312A_SETPOINT_RANGES = _model_ranges(
    "E36312A",
    (
        (
            1,
            "P6V",
            _single_range(voltage_max=6.18, current_max=5.15, current_default=5.0, current_min_keyword_value=0.001),
        ),
        (
            2,
            "P25V",
            _single_range(voltage_max=25.75, current_max=1.03, current_default=1.0, current_min_keyword_value=0.001),
        ),
        (
            3,
            "N25V",
            _single_range(voltage_max=25.75, current_max=1.03, current_default=1.0, current_min_keyword_value=0.001),
        ),
    ),
    range_basis="official output voltage setpoint and output current limit programming range",
    document_title="E36300 Series Programmable DC Power Supplies Programming Guide",
    publication_id="E36311-90008",
    publication_date="2019-11-26",
    source_pages=("printed page 16",),
    notes=("CH3 uses the project's normal positive setpoint semantics for E36312A, not E3631A negative persona mode.",),
)

EDU36311A_SETPOINT_RANGES = _model_ranges(
    "EDU36311A",
    (
        (
            1,
            "P6V",
            _single_range(voltage_max=6.18, current_max=5.15, current_default=5.0, current_min_keyword_value=0.002),
        ),
        (
            2,
            "P30V",
            _single_range(voltage_max=30.9, current_max=1.03, current_default=1.0, current_min_keyword_value=0.001),
        ),
        (
            3,
            "N30V",
            _single_range(voltage_max=30.9, current_max=1.03, current_default=1.0, current_min_keyword_value=0.001),
        ),
    ),
    range_basis="official output voltage setpoint and output current limit programming range",
    document_title="Triple Output Programmable DC Power Supply EDU36311A Programming Guide",
    publication_id="EDU36311-90013",
    publication_date="2024-04",
    source_pages=("printed page 15", "printed page 39"),
    notes=("CH3 uses the project's existing positive setpoint semantics.",),
)

E3646A_SETPOINT_RANGES = _model_ranges(
    "E3646A",
    (
        (
            1,
            "OUT1",
            (
                OutputSetpointRange("LOW", ("P8V",), "0 to 8 V / 3 A", 0.0, 8.24, 0.0, 0.0, 0.0, 3.09, 3.0, 3.0),
                OutputSetpointRange("HIGH", ("P20V",), "0 to 20 V / 1.5 A", 0.0, 20.60, 0.0, 0.0, 0.0, 1.545, 1.5, 1.5),
            ),
        ),
        (
            2,
            "OUT2",
            (
                OutputSetpointRange("LOW", ("P8V",), "0 to 8 V / 3 A", 0.0, 8.24, 0.0, 0.0, 0.0, 3.09, 3.0, 3.0),
                OutputSetpointRange("HIGH", ("P20V",), "0 to 20 V / 1.5 A", 0.0, 20.60, 0.0, 0.0, 0.0, 1.545, 1.5, 1.5),
            ),
        ),
    ),
    range_basis="official range-dependent output voltage setpoint and output current limit programming range",
    document_title="Agilent E364xA Dual Output DC Power Supplies User's and Service Guide",
    publication_id="E3646-90001",
    publication_date="2013-08-06",
    source_pages=("printed page 82", "printed page 83", "printed page 84", "printed page 91"),
    notes=("At *RST, the low voltage range is selected.", "Range metadata is not flattened into one combined maximum."),
)

PSM2010_SETPOINT_RANGES = _model_ranges(
    "PSM-2010",
    (
        (
            1,
            "OUT1",
            (
                OutputSetpointRange(
                    "LOW",
                    ("P8V",),
                    "0 to 8 V / 20 A",
                    0.0,
                    8.24,
                    0.0,
                    0.0,
                    0.0,
                    20.6,
                    20.0,
                    20.0,
                ),
                OutputSetpointRange(
                    "HIGH",
                    ("P20V",),
                    "0 to 20 V / 10 A",
                    0.0,
                    20.6,
                    0.0,
                    0.0,
                    0.0,
                    10.3,
                    10.0,
                    20.0,
                ),
            ),
        ),
    ),
    range_basis="official range-dependent output voltage setpoint and output current limit programming range",
    document_title="PSM-Series Programming Manual",
    publication_id="82SM-60030IA",
    publication_date="2018-01-09",
    source_pages=("printed page 28",),
    notes=(
        "The manual documents an instrument-wide *RST current value of 20 A; this does not mean 20 A is valid while HIGH range is retained.",
        "HIGH remains limited to a 10 A rating and a 10.3 A programming maximum.",
    ),
)

SETPOINT_RANGES_BY_MODEL_ID: Mapping[str, ModelSetpointRanges] = MappingProxyType(
    {
        "keysight-e36312a": E36312A_SETPOINT_RANGES,
        "keysight-edu36311a": EDU36311A_SETPOINT_RANGES,
        "keysight-e3646a": E3646A_SETPOINT_RANGES,
        "gw-instek-psm-2010": PSM2010_SETPOINT_RANGES,
    }
)


def setpoint_ranges_for_model_id(model_id: str | None) -> ModelSetpointRanges | None:
    if not model_id:
        return None
    return SETPOINT_RANGES_BY_MODEL_ID.get(model_id)


def setpoint_ranges_by_model_metadata() -> dict[str, dict[str, object]]:
    return {
        model_id: ranges.to_dict()
        for model_id, ranges in SETPOINT_RANGES_BY_MODEL_ID.items()
    }
