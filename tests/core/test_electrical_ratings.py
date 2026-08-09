import pytest

from powers_tool_core.electrical_ratings import (
    ChannelElectricalRating,
    ElectricalOperatingRange,
    ModelElectricalRatings,
    PSM2010_ELECTRICAL_RATINGS,
    electrical_ratings_by_model_metadata,
    ratings_for_model_id,
)
from powers_tool_core.safety import SafetyLimits, SafetyValidationError
from powers_tool_core.setpoint_limits import effective_setpoint_limits, validate_effective_setpoint


@pytest.mark.parametrize(
    ("model", "channel", "max_voltage", "max_current"),
    [
        ("keysight-e36312a", 1, 6.0, 5.0),
        ("keysight-e36312a", 2, 25.0, 1.0),
        ("keysight-e36312a", 3, 25.0, 1.0),
        ("keysight-edu36311a", 1, 6.0, 5.0),
        ("keysight-edu36311a", 2, 30.0, 1.0),
        ("keysight-edu36311a", 3, 30.0, 1.0),
    ],
)
def test_verified_channel_ratings(model, channel, max_voltage, max_current) -> None:
    ratings = ratings_for_model_id(model)

    assert ratings is not None
    assert ratings.channel(channel).max_voltage == max_voltage
    assert ratings.channel(channel).max_current == max_current
    validate_effective_setpoint(
        model=model,
        channel=channel,
        electrical_ratings=ratings,
        voltage=max_voltage,
        current=max_current,
    )


@pytest.mark.parametrize(
    ("setpoint", "expected"),
    [
        ({"voltage": 6.01}, r"voltage 6\.01 exceeds effective maximum 6 V"),
        ({"current": 5.01}, r"current 5\.01 exceeds effective maximum 5 A"),
    ],
)
def test_official_rating_rejects_above_boundary_with_source(setpoint, expected) -> None:
    ratings = ratings_for_model_id("keysight-e36312a")

    with pytest.raises(
        SafetyValidationError,
        match=rf"{expected} for E36312A channel 1, limited by official DC output rating",
    ):
        validate_effective_setpoint(
            model="E36312A",
            channel=1,
            electrical_ratings=ratings,
            **setpoint,
        )


def test_safety_config_can_only_make_rating_more_restrictive() -> None:
    ratings = ratings_for_model_id("keysight-e36312a")

    restrictive = effective_setpoint_limits(
        model="E36312A",
        channel=2,
        electrical_ratings=ratings,
        safety_limits=SafetyLimits(max_voltage=5, max_current=0.5),
    )
    permissive = effective_setpoint_limits(
        model="E36312A",
        channel=2,
        electrical_ratings=ratings,
        safety_limits=SafetyLimits(max_voltage=50, max_current=5),
    )

    assert (restrictive.max_voltage, restrictive.voltage_source) == (5, "safety config")
    assert (restrictive.max_current, restrictive.current_source) == (0.5, "safety config")
    assert (permissive.max_voltage, permissive.voltage_source) == (25, "official DC output rating")
    assert (permissive.max_current, permissive.current_source) == (1, "official DC output rating")


def test_unknown_model_has_no_invented_rating() -> None:
    assert ratings_for_model_id("UNKNOWN") is None
    assert set(electrical_ratings_by_model_metadata()) == {
        "gw-instek-psm-2010",
        "keysight-e36312a",
        "keysight-edu36311a",
    }


def test_psm2010_ratings_preserve_dual_range_pair_validation() -> None:
    rating = PSM2010_ELECTRICAL_RATINGS.channel(1)

    assert rating is not None
    assert (rating.max_voltage, rating.max_current) == (20.0, 20.0)
    assert [
        (item.name, item.max_voltage, item.max_current)
        for item in rating.operating_ranges
    ] == [
        ("LOW", 8.0, 20.0),
        ("HIGH", 20.0, 10.0),
    ]

    with pytest.raises(
        SafetyValidationError,
        match=r"15 V and current 15 A do not fit any official electrical operating range",
    ):
        validate_effective_setpoint(
            model="PSM-2010",
            channel=1,
            electrical_ratings=PSM2010_ELECTRICAL_RATINGS,
            voltage=15.0,
            current=15.0,
        )


DUAL_RANGE_RATINGS = ModelElectricalRatings(
    model="TEST-DUAL-RANGE",
    channels={
        1: ChannelElectricalRating(
            channel=1,
            max_voltage=20.0,
            max_current=20.0,
            operating_ranges=(
                ElectricalOperatingRange("LOW", max_voltage=8.0, max_current=20.0),
                ElectricalOperatingRange("HIGH", max_voltage=20.0, max_current=10.0),
            ),
        )
    },
    rating_basis="test-only dual-range rating",
    document_title="test-only",
    publication_id="test-only",
    publication_date="test-only",
)


@pytest.mark.parametrize(("voltage", "current"), [(5.0, 15.0), (15.0, 5.0)])
def test_dual_range_rating_accepts_pair_in_any_operating_range(voltage, current) -> None:
    validate_effective_setpoint(
        model="TEST-DUAL-RANGE",
        channel=1,
        electrical_ratings=DUAL_RANGE_RATINGS,
        voltage=voltage,
        current=current,
    )


def test_dual_range_rating_rejects_pair_outside_all_operating_ranges() -> None:
    with pytest.raises(
        SafetyValidationError,
        match=(
            r"requested voltage 15 V and current 15 A do not fit any official "
            r"electrical operating range for TEST-DUAL-RANGE channel 1"
        ),
    ):
        validate_effective_setpoint(
            model="TEST-DUAL-RANGE",
            channel=1,
            electrical_ratings=DUAL_RANGE_RATINGS,
            safety_limits=SafetyLimits(max_voltage=50.0, max_current=50.0),
            voltage=15.0,
            current=15.0,
        )


def test_dual_range_rating_keeps_scalar_only_validation() -> None:
    validate_effective_setpoint(
        model="TEST-DUAL-RANGE",
        channel=1,
        electrical_ratings=DUAL_RANGE_RATINGS,
        voltage=15.0,
    )
    validate_effective_setpoint(
        model="TEST-DUAL-RANGE",
        channel=1,
        electrical_ratings=DUAL_RANGE_RATINGS,
        current=15.0,
    )


def test_explicit_operating_ranges_are_serialized() -> None:
    channel = DUAL_RANGE_RATINGS.channel(1)

    assert channel is not None
    assert channel.to_dict()["operating_ranges"] == [
        {"name": "LOW", "max_voltage": 8.0, "max_current": 20.0},
        {"name": "HIGH", "max_voltage": 20.0, "max_current": 10.0},
    ]
