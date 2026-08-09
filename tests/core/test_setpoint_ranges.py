from powers_tool_core.setpoint_ranges import (
    setpoint_ranges_by_model_metadata,
    setpoint_ranges_for_model_id,
)


def only_range(model: str, channel: int) -> dict[str, object]:
    ranges = setpoint_ranges_for_model_id(model)
    assert ranges is not None
    channel_ranges = ranges.channel(channel)
    assert channel_ranges is not None
    assert len(channel_ranges.ranges) == 1
    return channel_ranges.ranges[0].to_dict()


def output_identifier(model: str, channel: int) -> str:
    ranges = setpoint_ranges_for_model_id(model)
    assert ranges is not None
    channel_ranges = ranges.channel(channel)
    assert channel_ranges is not None
    return channel_ranges.output_identifier


def test_e36312a_programming_ranges() -> None:
    assert only_range("keysight-e36312a", 1) == {
        "name": "fixed",
        "aliases": [],
        "rated_range_label": None,
        "voltage_min": 0.0,
        "voltage_max": 6.18,
        "voltage_default": 0.0,
        "voltage_reset": 0.0,
        "current_min": 0.0,
        "current_max": 5.15,
        "current_default": 5.0,
        "current_reset": 5.0,
        "current_min_keyword_value": 0.001,
    }
    assert output_identifier("keysight-e36312a", 2) == "P25V"
    assert only_range("keysight-e36312a", 2)["voltage_max"] == 25.75
    assert only_range("keysight-e36312a", 2)["current_max"] == 1.03
    assert output_identifier("keysight-e36312a", 3) == "N25V"
    assert only_range("keysight-e36312a", 3)["voltage_max"] == 25.75
    assert only_range("keysight-e36312a", 3)["current_min_keyword_value"] == 0.001


def test_edu36311a_programming_ranges_include_current_min_keyword_values() -> None:
    assert only_range("keysight-edu36311a", 1)["voltage_max"] == 6.18
    assert only_range("keysight-edu36311a", 1)["current_max"] == 5.15
    assert only_range("keysight-edu36311a", 1)["current_min"] == 0.0
    assert only_range("keysight-edu36311a", 1)["current_min_keyword_value"] == 0.002
    assert only_range("keysight-edu36311a", 2)["voltage_max"] == 30.9
    assert only_range("keysight-edu36311a", 2)["current_min_keyword_value"] == 0.001
    assert only_range("keysight-edu36311a", 3)["voltage_max"] == 30.9
    assert only_range("keysight-edu36311a", 3)["current_min_keyword_value"] == 0.001


def test_e3646a_programming_ranges_are_range_aware() -> None:
    ranges = setpoint_ranges_for_model_id("keysight-e3646a")
    assert ranges is not None
    assert ranges.channel(1) is not None
    channel_ranges = ranges.channel(1).ranges

    low = channel_ranges[0].to_dict()
    high = channel_ranges[1].to_dict()
    assert low["name"] == "LOW"
    assert low["aliases"] == ["P8V"]
    assert low["rated_range_label"] == "0 to 8 V / 3 A"
    assert low["voltage_max"] == 8.24
    assert low["current_max"] == 3.09
    assert high["name"] == "HIGH"
    assert high["aliases"] == ["P20V"]
    assert high["rated_range_label"] == "0 to 20 V / 1.5 A"
    assert high["voltage_max"] == 20.60
    assert high["current_max"] == 1.545

    assert ranges.channel(2).to_dict() == ranges.channel(1).to_dict() | {"channel": 2, "output_identifier": "OUT2"}


def test_psm2010_programming_ranges_are_range_aware() -> None:
    ranges = setpoint_ranges_for_model_id("gw-instek-psm-2010")
    assert ranges is not None
    channel = ranges.channel(1)
    assert channel is not None
    assert channel.output_identifier == "OUT1"

    low, high = (item.to_dict() for item in channel.ranges)
    assert low == {
        "name": "LOW",
        "aliases": ["P8V"],
        "rated_range_label": "0 to 8 V / 20 A",
        "voltage_min": 0.0,
        "voltage_max": 8.24,
        "voltage_default": 0.0,
        "voltage_reset": 0.0,
        "current_min": 0.0,
        "current_max": 20.6,
        "current_default": 20.0,
        "current_reset": 20.0,
    }
    assert high == {
        "name": "HIGH",
        "aliases": ["P20V"],
        "rated_range_label": "0 to 20 V / 10 A",
        "voltage_min": 0.0,
        "voltage_max": 20.6,
        "voltage_default": 0.0,
        "voltage_reset": 0.0,
        "current_min": 0.0,
        "current_max": 10.3,
        "current_default": 10.0,
        "current_reset": 20.0,
    }
    assert "does not mean 20 A is valid while HIGH range is retained" in ranges.notes[0]


def test_setpoint_ranges_metadata_lists_documented_models() -> None:
    metadata = setpoint_ranges_by_model_metadata()
    assert set(metadata) == {
        "gw-instek-psm-2010",
        "keysight-e36312a",
        "keysight-edu36311a",
        "keysight-e3646a",
    }
    assert metadata["keysight-e3646a"]["source"]["pages"] == [
        "printed page 82",
        "printed page 83",
        "printed page 84",
        "printed page 91",
    ]
    assert setpoint_ranges_for_model_id("keysight-e36103b") is None
    assert setpoint_ranges_for_model_id("keysight-e36232a") is None
