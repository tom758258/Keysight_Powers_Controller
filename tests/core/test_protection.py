from __future__ import annotations

import pytest

from powers_tool_core.core import CoreValidationError, OperationRequest, RuntimeOptions
from powers_tool_core.protection import run_protection


class FakeSession:
    def __init__(self, idn: str, responses: dict[str, str]) -> None:
        self.idn = idn
        self.responses = responses
        self.queries: list[str] = []

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        pass

    def query(self, command: str) -> str:
        self.queries.append(command)
        if command == "*IDN?":
            return self.idn
        return self.responses[command]

    def write(self, command: str) -> None:
        raise AssertionError(f"protection-status must not write {command!r}")

    def close(self) -> None:
        pass


@pytest.mark.parametrize("model", ["E36312A", "EDU36311A"])
def test_protection_status_reads_and_aggregates_trip_flags_by_channel(model: str) -> None:
    session = FakeSession(
        f"KEYSIGHT,{model},SERIAL0000,1.0",
        {
            "VOLT:PROT:TRIP? (@1)": "0",
            "CURR:PROT:TRIP? (@1)": "0",
            "VOLT:PROT:TRIP? (@2)": "1",
            "CURR:PROT:TRIP? (@2)": "0",
            "VOLT:PROT:TRIP? (@3)": "0",
            "CURR:PROT:TRIP? (@3)": "1",
            "OUTP? (@1)": "OFF",
            "OUTP? (@2)": "ON",
            "OUTP? (@3)": "OFF",
        },
    )
    request = OperationRequest(
        command="protection-status",
        runtime=RuntimeOptions(resource=f"USB0::FAKE::{model}::INSTR"),
        parameters={"all": True},
    )

    result = run_protection(request, opener=lambda *args, **kwargs: session)

    assert result["protection"] == {
        "over_voltage_tripped": True,
        "over_current_tripped": True,
    }
    assert result["protection_by_channel"] == [
        {
            "channel": 1,
            "protection": {
                "over_voltage_tripped": False,
                "over_current_tripped": False,
            },
        },
        {
            "channel": 2,
            "protection": {
                "over_voltage_tripped": True,
                "over_current_tripped": False,
            },
        },
        {
            "channel": 3,
            "protection": {
                "over_voltage_tripped": False,
                "over_current_tripped": True,
            },
        },
    ]
    assert result["outputs"] == [
        {"channel": 1, "enabled": False, "disabled_with_protection": False},
        {"channel": 2, "enabled": True, "disabled_with_protection": False},
        {"channel": 3, "enabled": False, "disabled_with_protection": True},
    ]
    assert session.queries == [
        "*IDN?",
        "VOLT:PROT:TRIP? (@1)",
        "CURR:PROT:TRIP? (@1)",
        "VOLT:PROT:TRIP? (@2)",
        "CURR:PROT:TRIP? (@2)",
        "VOLT:PROT:TRIP? (@3)",
        "CURR:PROT:TRIP? (@3)",
        "OUTP? (@1)",
        "OUTP? (@2)",
        "OUTP? (@3)",
    ]


def test_psm2010_simulated_protection_status_uses_single_output_scpi() -> None:
    result = run_protection(
        OperationRequest(
            "protection-status",
            RuntimeOptions(
                simulate=True,
                resource="ASRL1::SIM::PSM2010::INSTR",
            ),
            {"all": True},
        )
    )

    assert result["protection_by_channel"] == [
        {
            "channel": 1,
            "protection": {
                "over_voltage_tripped": False,
                "over_current_tripped": False,
            },
        }
    ]


def test_psm2010_protection_plan_rejects_delay_trigger_before_open() -> None:
    opened = False

    def opener(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("opener must not run")

    with pytest.raises(CoreValidationError, match="does not support the ocp_delay_trigger"):
        run_protection(
            OperationRequest(
                "protection-set",
                RuntimeOptions(
                    dry_run=True,
                    planning_model_id="gw-instek-psm-2010",
                ),
                {
                    "channel": 1,
                    "ocp_delay_trigger": "setting-change",
                },
            ),
            opener=opener,
        )

    assert opened is False
