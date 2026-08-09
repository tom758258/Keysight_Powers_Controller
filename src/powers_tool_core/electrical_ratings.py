"""Verified independent-channel DC output ratings."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class ElectricalOperatingRange:
    """Official voltage/current operating range for one output channel."""

    name: str
    max_voltage: float
    max_current: float

    def to_dict(self) -> dict[str, float | str]:
        return {
            "name": self.name,
            "max_voltage": self.max_voltage,
            "max_current": self.max_current,
        }


@dataclass(frozen=True)
class ChannelElectricalRating:
    """Official DC output rating for one independent output channel."""

    channel: int
    max_voltage: float
    max_current: float
    operating_ranges: tuple[ElectricalOperatingRange, ...] = ()

    def to_dict(self) -> dict[str, object]:
        rating: dict[str, object] = {
            "channel": self.channel,
            "max_voltage": self.max_voltage,
            "max_current": self.max_current,
        }
        if self.operating_ranges:
            rating["operating_ranges"] = [
                operating_range.to_dict()
                for operating_range in self.operating_ranges
            ]
        return rating


@dataclass(frozen=True)
class ModelElectricalRatings:
    """Verified model ratings and their official document source."""

    model: str
    channels: Mapping[int, ChannelElectricalRating]
    rating_basis: str
    document_title: str
    publication_id: str
    publication_date: str

    def channel(self, channel: int) -> ChannelElectricalRating | None:
        return self.channels.get(channel)

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "rating_basis": self.rating_basis,
            "source": {
                "document_title": self.document_title,
                "publication_id": self.publication_id,
                "publication_date": self.publication_date,
            },
            "channels": [rating.to_dict() for rating in self.channels.values()],
        }


def _ratings(
    model: str,
    values: tuple[tuple[int, float, float], ...],
    *,
    document_title: str,
    publication_id: str,
    publication_date: str,
) -> ModelElectricalRatings:
    channels = {
        channel: ChannelElectricalRating(channel, max_voltage, max_current)
        for channel, max_voltage, max_current in values
    }
    return ModelElectricalRatings(
        model=model,
        channels=MappingProxyType(channels),
        rating_basis="official independent-channel DC output rating (0 to 40 C)",
        document_title=document_title,
        publication_id=publication_id,
        publication_date=publication_date,
    )


E36312A_ELECTRICAL_RATINGS = _ratings(
    "E36312A",
    ((1, 6.0, 5.0), (2, 25.0, 1.0), (3, 25.0, 1.0)),
    document_title="E36300 Series Triple Output Bench Power Supply",
    publication_id="5992-2124EN",
    publication_date="2023-08-25",
)

EDU36311A_ELECTRICAL_RATINGS = _ratings(
    "EDU36311A",
    ((1, 6.0, 5.0), (2, 30.0, 1.0), (3, 30.0, 1.0)),
    document_title="EDU36311A Triple-Output Bench Power Supply",
    publication_id="3121-1003.ZHTW",
    publication_date="2021-01-11",
)

ELECTRICAL_RATINGS_BY_MODEL_ID: Mapping[str, ModelElectricalRatings] = MappingProxyType(
    {
        "keysight-e36312a": E36312A_ELECTRICAL_RATINGS,
        "keysight-edu36311a": EDU36311A_ELECTRICAL_RATINGS,
    }
)


def ratings_for_model_id(model_id: str | None) -> ModelElectricalRatings | None:
    if not model_id:
        return None
    return ELECTRICAL_RATINGS_BY_MODEL_ID.get(model_id)


def electrical_ratings_by_model_metadata() -> dict[str, dict[str, object]]:
    return {
        model_id: ratings.to_dict()
        for model_id, ratings in ELECTRICAL_RATINGS_BY_MODEL_ID.items()
    }
