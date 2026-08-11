import pytest

from powers_tool_core.core import CommandCancelled, CoreExecutionError, CoreValidationError, OperationRequest, RuntimeOptions
from powers_tool_core.ramp_list import (
    RAMP_LIST_KIND,
    RAMP_LIST_VERSION,
    RAMP_LIST_VERSION_V2,
    run_ramp_list,
)


class FakeSession:
    def __init__(self, fail_write: str | None = None) -> None:
        self.fail_write = fail_write
        self.writes: list[str] = []
        self.queries: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def write(self, command: str) -> None:
        if command == self.fail_write:
            raise ValueError("injected write failure")
        self.writes.append(command)

    def query(self, command: str) -> str:
        self.queries.append(command)
        if command == "*IDN?":
            return "KEYSIGHT,E36312A,SERIAL0000,1.0"
        if command.startswith("OUTP?"):
            return "0"
        return '0,"No error"'


class OutputTrackingSession(FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.output_states = {1: False, 2: False, 3: False}
        self.events: list[str] = []

    def write(self, command: str) -> None:
        self.events.append(f"W:{command}")
        super().write(command)
        if command.startswith("OUTP ON,(@"):
            self.output_states[int(command.rsplit("(@", 1)[1].rstrip(")"))] = True
        if command.startswith("OUTP OFF,(@"):
            self.output_states[int(command.rsplit("(@", 1)[1].rstrip(")"))] = False

    def query(self, command: str) -> str:
        self.events.append(f"Q:{command}")
        if command.startswith("OUTP? (@"):
            self.queries.append(command)
            channel = int(command.rsplit("(@", 1)[1].rstrip(")"))
            return "1" if self.output_states[channel] else "0"
        return super().query(command)


class PSM2010Session(FakeSession):
    def query(self, command: str) -> str:
        self.queries.append(command)
        responses = {
            "*IDN?": "GW.Inc,PSM-2010,SIM000006,FW1.00",
            "VOLT:RANG?": "P8V",
            "OUTP?": "0",
            "SYST:ERR?": '0,"No error"',
        }
        return responses.get(command, '0,"No error"')


def document(*segments):
    return {"kind": RAMP_LIST_KIND, "version": 2, "segments": list(segments)}


def segment(
    channel=1,
    current=0.1,
    start_voltage=0,
    stop_voltage=1,
    step_voltage=0.5,
    delay_ms=0,
    hold_ms=0,
):
    return {
        "channel": channel,
        "current": current,
        "start_voltage": start_voltage,
        "stop_voltage": stop_voltage,
        "step_voltage": step_voltage,
        "delay_ms": delay_ms,
        "hold_ms": hold_ms,
    }


def request(doc, **runtime):
    return OperationRequest(
        command="ramp-list",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", **runtime),
        parameters={"document": doc},
    )


def test_psm2010_ramp_list_uses_shared_range_resolution() -> None:
    session = PSM2010Session()
    result = run_ramp_list(
        OperationRequest(
            "ramp-list",
            RuntimeOptions(
                resource="ASRL1::INSTR",
                support_policy_mode="validation",
            ),
            {
                "document": document(
                    segment(
                        current=5.0,
                        start_voltage=15.0,
                        stop_voltage=15.0,
                        step_voltage=1.0,
                    )
                )
            },
        ),
        opener=lambda *args, **kwargs: session,
        sleep=lambda _seconds: None,
    )

    assert result["status"] == "completed"
    assert session.writes[:3] == ["VOLT:RANG HIGH", "CURR 5", "VOLT 15"]


def test_ramp_list_contract_versions_are_explicit() -> None:
    assert RAMP_LIST_KIND == "powers-tool-ramp-list"
    assert RAMP_LIST_VERSION_V2 == 2
    assert RAMP_LIST_VERSION == 4
    assert type(RAMP_LIST_VERSION) is int


def test_ramp_list_v4_requires_loop_count() -> None:
    doc = {
        "kind": RAMP_LIST_KIND,
        "version": 4,
        "enable_output": False,
        "segments": [segment()],
    }
    with pytest.raises(CoreValidationError, match="version 4 requires loop_count"):
        run_ramp_list(request(doc, dry_run=True))


@pytest.mark.parametrize("loop_count", [0, -1, 10_001, True, 1.0, "2", None])
def test_ramp_list_v4_loop_count_is_strict(loop_count: object) -> None:
    doc = {
        "kind": RAMP_LIST_KIND,
        "version": 4,
        "enable_output": False,
        "loop_count": loop_count,
        "segments": [segment()],
    }
    with pytest.raises(CoreValidationError, match="integer from 1 to 10,000"):
        run_ramp_list(request(doc, dry_run=True))


def test_ramp_list_execution_units_sum_segment_voltage_steps() -> None:
    doc = {
        "kind": RAMP_LIST_KIND,
        "version": 4,
        "enable_output": False,
        "loop_count": 2,
        "segments": [
            segment(start_voltage=0, stop_voltage=1, step_voltage=0.5),
            segment(start_voltage=0, stop_voltage=1, step_voltage=1),
        ],
    }

    data = run_ramp_list(request(doc, dry_run=True))

    assert data["plan"]["execution_units"] == 10


@pytest.mark.parametrize(("version", "enable_output"), [(2, False), (3, True)])
def test_ramp_list_override_upgrades_old_document_without_mutation(version: int, enable_output: bool) -> None:
    doc = {"kind": RAMP_LIST_KIND, "version": version, "segments": [segment()]}
    if version == 3:
        doc["enable_output"] = enable_output
    original = {**doc, "segments": list(doc["segments"])}
    core_request = request(doc, dry_run=True)
    core_request = OperationRequest(
        command="ramp-list",
        runtime=core_request.runtime,
        parameters={**core_request.parameters, "loop_count": 2},
    )

    data = run_ramp_list(core_request)

    assert data["plan"]["version"] == 4
    assert data["plan"]["loop_count"] == 2
    assert data["plan"]["enable_output"] is enable_output
    assert doc == original


@pytest.mark.parametrize("value", ["true", "false", 1, 0, 1.0, None, [], {}])
def test_ramp_list_v3_requires_exact_boolean_enable_output(value: object) -> None:
    doc = {
        "kind": RAMP_LIST_KIND,
        "version": 3,
        "enable_output": value,
        "segments": [segment()],
    }
    with pytest.raises(CoreValidationError, match="must be a boolean"):
        run_ramp_list(request(doc, dry_run=True))


def test_ramp_list_v2_means_enable_output_false() -> None:
    data = run_ramp_list(request(document(segment()), dry_run=True))

    assert data["ramp_list_version"] == 2
    assert data["enable_output"] is False
    assert data["output_enable_executed"] is False


def test_ramp_list_v3_enables_each_channel_only_at_first_segment() -> None:
    session = OutputTrackingSession()
    doc = {
        "kind": RAMP_LIST_KIND,
        "version": 3,
        "enable_output": True,
        "segments": [
            segment(channel=1, start_voltage=0, stop_voltage=0),
            segment(channel=1, start_voltage=0.5, stop_voltage=0.5),
            segment(channel=2, start_voltage=0, stop_voltage=0),
            segment(channel=1, start_voltage=1, stop_voltage=1),
        ],
    }

    data = run_ramp_list(
        request(doc),
        opener=lambda *args, **kwargs: session,
        sleep=lambda seconds: None,
    )

    assert session.writes.count("OUTP ON,(@1)") == 1
    assert session.writes.count("OUTP ON,(@2)") == 1
    assert data["enabled_channels"] == [1, 2]
    assert [item["channel"] for item in data["final_output_states"]] == [1, 2]
    assert all(item["enabled"] is True for item in data["final_output_states"])


def test_ramp_list_lint_validates_without_opening_visa() -> None:
    opened = False
    core_request = request(document(segment()))
    core_request = OperationRequest(
        command="ramp-list",
        runtime=core_request.runtime,
        parameters={**core_request.parameters, "lint": True},
    )

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        return FakeSession()

    data = run_ramp_list(core_request, opener=opener)

    assert opened is False
    assert data["status"] == "valid"
    assert data["segment_count"] == 1
    assert data["segments"][0]["voltages"] == [0.0, 0.5, 1.0]


def test_ramp_list_executes_cross_channel_segments_in_one_session() -> None:
    session = FakeSession()
    opener_calls = 0

    def opener(*args, **kwargs):
        nonlocal opener_calls
        opener_calls += 1
        return session

    data = run_ramp_list(
        request(
            document(
                segment(channel=1, current=0.1, start_voltage=0, stop_voltage=1, step_voltage=0.5),
                segment(channel=2, current=0.05, start_voltage=2, stop_voltage=1, step_voltage=0.5),
            )
        ),
        opener=opener,
        sleep=lambda seconds: None,
    )

    assert opener_calls == 1
    assert session.writes == [
        "CURR 0.1,(@1)",
        "VOLT 0,(@1)",
        "VOLT 0.5,(@1)",
        "VOLT 1,(@1)",
        "CURR 0.05,(@2)",
        "VOLT 2,(@2)",
        "VOLT 1.5,(@2)",
        "VOLT 1,(@2)",
    ]
    assert data["status"] == "completed"
    assert data["completed_segments"] == 2


def test_ramp_list_delay_and_final_hold_are_applied() -> None:
    sleeps: list[float] = []

    run_ramp_list(
        request(document(segment(delay_ms=100, hold_ms=250))),
        opener=lambda *args, **kwargs: FakeSession(),
        sleep=sleeps.append,
    )

    assert sleeps == [0.1, 0.1, 0.25]


def test_ramp_list_invalid_later_segment_produces_no_hardware_io() -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        return FakeSession()

    with pytest.raises(CoreValidationError, match="segment 2"):
        run_ramp_list(
            request(document(segment(), segment(channel=2, step_voltage=0))),
            opener=opener,
        )

    assert opened is False


def test_ramp_list_model_channel_validation_happens_before_writes() -> None:
    session = FakeSession()

    with pytest.raises(CoreValidationError, match="segment 2 channel 4"):
        run_ramp_list(
            request(document(segment(), segment(channel=4))),
            opener=lambda *args, **kwargs: session,
        )

    assert session.writes == []


def test_ramp_list_safety_failure_in_later_segment_produces_no_writes(tmp_path) -> None:
    safety = tmp_path / "safety.toml"
    safety.write_text("[safety]\nmax_voltage = 1\nmax_current = 0.2\n", encoding="utf-8")
    session = FakeSession()
    core_request = OperationRequest(
        command="ramp-list",
        runtime=RuntimeOptions(resource="USB0::SIM::E36312A::INSTR", safety_config=str(safety)),
        parameters={"document": document(segment(), segment(channel=2, stop_voltage=2))},
    )

    with pytest.raises(CoreValidationError, match="segment 2"):
        run_ramp_list(core_request, opener=lambda *args, **kwargs: session)

    assert session.writes == []


def test_ramp_list_failure_stops_later_segments_without_output_off() -> None:
    session = FakeSession(fail_write="VOLT 0.5,(@1)")

    data = run_ramp_list(
        request(document(segment(), segment(channel=2))),
        opener=lambda *args, **kwargs: session,
        sleep=lambda seconds: None,
    )

    assert data["status"] == "failed"
    assert data["completed_segments"] == 0
    assert data["failed_segment"]["index"] == 1
    assert not any(command.startswith("OUTP") for command in session.writes)
    assert not any("(@2)" in command for command in session.writes)


def test_ramp_list_cancellation_safe_offs_all_channels_and_stops_later_segments() -> None:
    session = FakeSession()
    cancelled = False

    def sleep(_seconds: float) -> None:
        nonlocal cancelled
        cancelled = True

    with pytest.raises(CommandCancelled) as raised:
        run_ramp_list(
            request(document(segment(delay_ms=100), segment(channel=2))),
            opener=lambda *args, **kwargs: session,
            sleep=sleep,
            stop_requested=lambda: cancelled,
        )

    assert raised.value.data["status"] == "cancelled"
    assert session.writes[-3:] == ["OUTP OFF,(@1)", "OUTP OFF,(@2)", "OUTP OFF,(@3)"]
    assert session.queries[-4:] == ["OUTP? (@1)", "OUTP? (@2)", "OUTP? (@3)", "SYST:ERR?"]
    assert not any(
        command.startswith(("CURR", "VOLT")) and "(@2)" in command
        for command in session.writes
    )


@pytest.mark.parametrize(
    ("doc", "message"),
    [
        ({"kind": "wrong", "version": 2, "segments": [segment()]}, "kind"),
        ({"kind": "keysight-power-ramp-list", "version": 2, "segments": [segment()]}, "kind"),
        ({"kind": RAMP_LIST_KIND, "version": 1, "segments": [segment()]}, "version"),
        ({"kind": RAMP_LIST_KIND, "version": "2", "segments": [segment()]}, "version"),
        ({"kind": RAMP_LIST_KIND, "version": True, "segments": [segment()]}, "version"),
        ({"kind": RAMP_LIST_KIND, "version": False, "segments": [segment()]}, "version"),
        ({"kind": RAMP_LIST_KIND, "version": 2.0, "segments": [segment()]}, "version"),
        ({"kind": RAMP_LIST_KIND, "segments": [segment()]}, "version"),
        ({"kind": RAMP_LIST_KIND, "version": 3, "segments": [segment()]}, "requires enable_output"),
        (document(), "1 to 10"),
        (document(*(segment() for _ in range(11))), "at most 10"),
        (document(segment(delay_ms=-1)), "delay_ms"),
        (document(segment(hold_ms=-1)), "hold_ms"),
        (document(segment(channel=1.5)), "invalid numeric"),
        (document(segment(delay_ms=1.5)), "invalid numeric"),
        (document(segment(start_voltage=0, stop_voltage=1001, step_voltage=1)), "1000 voltage steps"),
    ],
)
def test_ramp_list_rejects_invalid_documents(doc, message) -> None:
    with pytest.raises(CoreValidationError, match=message):
        run_ramp_list(request(doc, dry_run=True))


@pytest.mark.parametrize("version", [1, "2", True, False, 2.0, None])
def test_ramp_list_rejects_invalid_version_before_opening_visa(version: object) -> None:
    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("VISA must not be opened for an invalid Ramp List document")

    invalid = {"kind": RAMP_LIST_KIND, "version": version, "segments": [segment()]}
    with pytest.raises(CoreValidationError, match="unsupported ramp-list version"):
        run_ramp_list(request(invalid), opener=opener)

    assert opened is False


def test_ramp_list_step_pulse_accepts_zero_delay() -> None:
    doc = document(segment(delay_ms=0), segment(channel=2, delay_ms=0))
    doc["completion_pulse"] = {"timing": "step", "pins": [1], "polarity": "positive"}

    data = run_ramp_list(request(doc, dry_run=True))

    assert data["plan"]["completion_pulse"]["timing"] == "step"


@pytest.mark.parametrize(
    "runtime",
    [
        RuntimeOptions(dry_run=True, planning_model_id="keysight-edu36311a"),
        RuntimeOptions(dry_run=True, planning_model_id="keysight-e3646a"),
        RuntimeOptions(simulate=True, resource="USB0::SIM::EDU36311A::INSTR"),
        RuntimeOptions(simulate=True, resource="ASRL1::SIM::E3646A::INSTR"),
        RuntimeOptions(dry_run=True, planning_profile_id="generic-scpi"),
    ],
)
def test_ramp_list_completion_pulse_no_hardware_requires_e36312a(
    runtime: RuntimeOptions,
) -> None:
    opened = False
    doc = document(segment())
    doc["completion_pulse"] = {
        "timing": "segment",
        "pins": [1],
        "polarity": "positive",
    }

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("no-hardware ramp-list must not open VISA")

    with pytest.raises(
        CoreValidationError,
        match="ramp-list completion_pulse require planning_model_id 'keysight-e36312a'",
    ):
        run_ramp_list(
            OperationRequest(
                command="ramp-list",
                runtime=runtime,
                parameters={"document": doc},
            ),
            opener=opener,
        )

    assert opened is False


@pytest.mark.parametrize(
    ("runtime_kwargs", "message"),
    [
        (
            {"dry_run": True},
            "planning require planning_model_id, planning_profile_id",
        ),
        (
            {"dry_run": True, "planning_model_id": "unknown"},
            "invalid planning_model_id",
        ),
    ],
)
def test_ramp_list_completion_pulse_missing_or_unknown_planning_model_fails_closed(
    runtime_kwargs: dict,
    message: str,
) -> None:
    doc = document(segment())
    doc["completion_pulse"] = {
        "timing": "segment",
        "pins": [1],
        "polarity": "positive",
    }

    with pytest.raises(CoreValidationError, match=message):
        run_ramp_list(
            OperationRequest(
                command="ramp-list",
                runtime=RuntimeOptions(**runtime_kwargs),
                parameters={"document": doc},
            )
        )


def test_ramp_list_no_pulse_other_model_plan_is_unchanged() -> None:
    data = run_ramp_list(
        OperationRequest(
            command="ramp-list",
            runtime=RuntimeOptions(
                dry_run=True,
                planning_model_id="keysight-e3646a",
            ),
            parameters={"document": document(segment())},
        )
    )

    assert data["status"] == "planned"
    assert data["plan"]["completion_pulse"] is None


def test_ramp_list_segment_pulse_uses_each_segment_channel(monkeypatch) -> None:
    calls: list[int] = []

    def pulse(_power_supply, *, channel, **kwargs):
        calls.append(channel)
        return {"channel": channel, "completed": True}

    monkeypatch.setattr("powers_tool_core.ramp_list.run_post_action_completion_pulse", pulse)
    doc = document(segment(channel=1), segment(channel=2))
    doc["completion_pulse"] = {"timing": "segment", "pins": [1], "polarity": "positive"}

    data = run_ramp_list(request(doc), opener=lambda *args, **kwargs: FakeSession(), sleep=lambda seconds: None)

    assert calls == [1, 2]
    assert [item["trigger"]["channel"] for item in data["segments"]] == [1, 2]


def test_ramp_list_loop_pulse_runs_once_on_final_segment_channel(monkeypatch) -> None:
    calls: list[int] = []

    def pulse(_power_supply, *, channel, **kwargs):
        calls.append(channel)
        return {"channel": channel, "requested": True, "attempted": True, "fired": True, "completed": True}

    monkeypatch.setattr("powers_tool_core.ramp_list.run_post_action_completion_pulse", pulse)
    doc = {
        "kind": RAMP_LIST_KIND,
        "version": 4,
        "enable_output": False,
        "loop_count": 2,
        "completion_pulse": {"timing": "loop", "pins": [1], "polarity": "positive"},
        "segments": [segment(channel=1), segment(channel=2)],
    }

    data = run_ramp_list(request(doc), opener=lambda *args, **kwargs: FakeSession(), sleep=lambda seconds: None)

    assert calls == [2]
    assert data["loop_count"] == data["completed_loops"] == 2
    assert data["completed_segments"] == 2
    assert data["completed_segment_executions"] == 4
    assert data["trigger"]["channel"] == 2
    assert [item["loop_index"] for item in data["segments"]] == [1, 1, 2, 2]


@pytest.mark.parametrize("failure_stage", ["output_state", "instrument_error", "cancellation"])
def test_ramp_list_pre_loop_pulse_failure_never_attempts_pulse(monkeypatch, failure_stage: str) -> None:
    class FinalFailureSession(OutputTrackingSession):
        def __init__(self) -> None:
            super().__init__()
            self.output_queries = 0
            self.error_queries = 0

        def query(self, command: str) -> str:
            if command.startswith("OUTP? (@"):
                self.output_queries += 1
                if failure_stage == "output_state" and self.output_queries > 1:
                    self.queries.append(command)
                    return "0"
            if command == "SYST:ERR?":
                self.error_queries += 1
                if failure_stage == "instrument_error" and self.error_queries == 3:
                    self.queries.append(command)
                    return '-200,"Execution error"'
            return super().query(command)

    pulse_calls = 0

    def pulse(*args, **kwargs):
        nonlocal pulse_calls
        pulse_calls += 1
        return {"attempted": True}

    monkeypatch.setattr("powers_tool_core.ramp_list.run_post_action_completion_pulse", pulse)
    session = FinalFailureSession()
    doc = {
        "kind": RAMP_LIST_KIND,
        "version": 4,
        "enable_output": failure_stage == "output_state",
        "loop_count": 2,
        "completion_pulse": {"timing": "loop", "pins": [1], "polarity": "positive"},
        "segments": [segment(channel=1)],
    }
    stop_requested = (
        (lambda: session.error_queries >= 3)
        if failure_stage == "cancellation"
        else None
    )

    with pytest.raises((CoreExecutionError, CommandCancelled)) as raised:
        run_ramp_list(
            request(doc),
            opener=lambda *args, **kwargs: session,
            sleep=lambda seconds: None,
            stop_requested=stop_requested,
        )

    assert pulse_calls == 0
    if isinstance(raised.value, CommandCancelled):
        trigger = raised.value.data["partial_result"]["trigger"]
    else:
        trigger = raised.value.trigger
    assert trigger["requested"] is True
    assert trigger["attempted"] is False
    assert trigger["fired"] is False


@pytest.mark.parametrize(
    ("idn", "resource"),
    [
        ("KEYSIGHT,EDU36311A,SERIAL0000,1.0", "USB0::FAKE::EDU36311A::INSTR"),
        ("KEYSIGHT,E3646A,MY12345678,1.0", "ASRL1::INSTR"),
    ],
)
def test_unsupported_model_ramp_list_completion_pulse_rejects_before_segment_write(
    idn: str,
    resource: str,
) -> None:
    class UnsupportedPulseFakeSession(FakeSession):
        def query(self, command: str) -> str:
            self.queries.append(command)
            if command == "*IDN?":
                return idn
            return '0,"No error"'

    doc = document(segment(channel=1))
    doc["completion_pulse"] = {"timing": "segment", "pins": [1], "polarity": "positive"}

    req = OperationRequest(
        command="ramp-list",
            parameters={"document": doc},
            runtime=RuntimeOptions(resource=resource, dry_run=False, simulate=False, confirm=True)
    )
    session = UnsupportedPulseFakeSession()
    with pytest.raises(CoreValidationError, match="completion pulses are only supported for E36312A"):
        run_ramp_list(req, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)

    assert session.queries == ["*IDN?"]
    assert session.writes == []


def test_e3646a_ramp_list_simulate_and_real_execution() -> None:
    class E3646AFakeSession(FakeSession):
        def query(self, command: str) -> str:
            self.queries.append(command)
            if command == "*IDN?":
                return "KEYSIGHT,E3646A,MY12345678,1.0"
            if command == "INST:NSEL?":
                return "1"
            return '0,"No error"'

    doc = document(segment(channel=2, current=0.05, start_voltage=0.5, stop_voltage=1.5, step_voltage=0.5, delay_ms=10, hold_ms=5))

    req_sim = OperationRequest(
        command="ramp-list",
        parameters={"document": doc},
        runtime=RuntimeOptions(resource="ASRL1::SIM::E3646A::INSTR", dry_run=False, simulate=True)
    )
    data_sim = run_ramp_list(req_sim, opener=lambda *args, **kwargs: E3646AFakeSession(), sleep=lambda seconds: None)
    assert data_sim["status"] == "planned"

    req_real = OperationRequest(
        command="ramp-list",
            parameters={"document": doc},
            runtime=RuntimeOptions(resource="ASRL1::INSTR", dry_run=False, simulate=False, confirm=True)
    )
    session = E3646AFakeSession()
    data_real = run_ramp_list(req_real, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)
    assert data_real["status"] == "completed"
    assert "INST:NSEL 2" in session.writes
    assert "CURR 0.05" in session.writes
    assert "VOLT 0.5" in session.writes
    assert "VOLT 1" in session.writes
    assert "VOLT 1.5" in session.writes
    assert not any("(@" in w for w in session.writes)
