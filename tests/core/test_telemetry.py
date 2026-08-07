from __future__ import annotations

from contextlib import closing

import pytest

import powers_tool_core.telemetry as telemetry
from powers_tool_core.command_runner import run_core_command
from powers_tool_core.core import (
    CommandCancelled,
    OperationRequest,
    RuntimeOptions,
    UnsupportedChannelError,
)
from powers_tool_core.testing.simulator import SimulatedResourceManager
from powers_tool_core.support_policy import (
    LiveSupportPolicyError,
    SUPPORT_POLICY_MODE_VALIDATION,
)


def _request(parameters: dict) -> OperationRequest:
    return OperationRequest(
        "log",
        RuntimeOptions(simulate=True, planning_model_id="keysight-e36312a"),
        parameters,
    )


def test_sample_count_collection_reports_multi_channel_rows_and_closes_session() -> None:
    manager = SimulatedResourceManager()
    session = manager.open_resource("USB0::SIM::E36312A::INSTR")
    rows: list[dict] = []

    result = run_core_command(
        _request(
            {"channels": [3, 1, 3], "interval_sec": 0.01, "samples": 2}
        ),
        opener=lambda *args, **kwargs: closing(session),
        sleep=lambda _seconds: None,
        sample_reporter=rows.append,
    )

    assert result["samples_written"] == 2
    assert result["channels"] == [3, 1, 3]
    assert [row["channel"] for row in rows] == [3, 1, 3, 3, 1, 3]
    assert session.closed is True


def test_duration_collection_uses_complete_cycle_then_interval_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    monkeypatch.setattr(telemetry.time, "monotonic", lambda: now[0])
    rows: list[dict] = []

    result = run_core_command(
        _request({"channel": 1, "interval_sec": 0.1, "duration_sec": 0.25}),
        sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
        sample_reporter=rows.append,
    )

    assert result["samples_written"] == 3
    assert len(rows) == 3
    assert now[0] == pytest.approx(0.3)


def test_unsupported_channel_is_rejected_and_session_closes() -> None:
    manager = SimulatedResourceManager()
    session = manager.open_resource("USB0::SIM::E36312A::INSTR")

    with pytest.raises(UnsupportedChannelError, match="channel 4"):
        run_core_command(
            _request({"channel": 4, "interval_sec": 0.1, "samples": 1}),
            opener=lambda *args, **kwargs: closing(session),
        )

    assert session.closed is True


def test_cancellation_finishes_the_active_cycle_before_stopping() -> None:
    cancelled = False
    rows: list[dict] = []

    def report(row: dict) -> None:
        nonlocal cancelled
        rows.append(row)
        cancelled = True

    with pytest.raises(CommandCancelled) as raised:
        run_core_command(
            _request({"channel": "all", "interval_sec": 1.0, "samples": 10}),
            stop_requested=lambda: cancelled,
            sample_reporter=report,
        )

    assert [row["channel"] for row in rows] == [1, 2, 3]
    assert raised.value.data["samples_written"] == 1
    assert raised.value.data["channels"] == [1, 2, 3]
    assert raised.value.data["stop_reason"] == "cancelled"


def test_e3646a_log_executes_only_through_the_exact_validation_candidate() -> None:
    manager = SimulatedResourceManager()
    validation_session = manager.open_resource("ASRL1::SIM::E3646A::INSTR")
    rows: list[dict] = []
    parameters = {"channel": "all", "interval_sec": 0.1, "samples": 1}

    result = run_core_command(
        OperationRequest(
            "log",
            RuntimeOptions(
                resource="ASRL1::INSTR",
                expected_model_id="keysight-e3646a",
                support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            ),
            parameters,
        ),
        opener=lambda *args, **kwargs: closing(validation_session),
        sample_reporter=rows.append,
    )

    assert result["channels"] == [1, 2]
    assert [row["channel"] for row in rows] == [1, 2]

    product_session = manager.open_resource("ASRL1::SIM::E3646A::INSTR")
    with pytest.raises(LiveSupportPolicyError):
        run_core_command(
            OperationRequest(
                "log",
                RuntimeOptions(
                    resource="ASRL1::INSTR",
                    expected_model_id="keysight-e3646a",
                ),
                parameters,
            ),
            opener=lambda *args, **kwargs: closing(product_session),
        )
    assert product_session.commands == ["*IDN?"]
