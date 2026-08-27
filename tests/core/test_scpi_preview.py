import pytest

from powers_tool_core._scpi_preview import preview_measure_scpi


@pytest.mark.parametrize(
    "idn",
    [
        "KEYSIGHT,E36312A,SERIAL0000,1.0",
        "KEYSIGHT,EDU36311A,SERIAL0000,1.0",
    ],
)
@pytest.mark.parametrize("channel", [1, 2, 3])
def test_preview_measure_scpi_uses_channel_list_queries_for_e36312a_and_edu36311a(idn, channel) -> None:
    assert preview_measure_scpi(idn, channel=channel) == (
        f"MEAS:VOLT? (@{channel})",
        f"MEAS:CURR? (@{channel})",
    )


def test_preview_measure_scpi_uses_generic_queries_for_fallback_driver() -> None:
    assert preview_measure_scpi("KEYSIGHT,UNKNOWN,SERIAL0000,1.0", channel=1) == (
        "MEAS:VOLT?",
        "MEAS:CURR?",
    )
