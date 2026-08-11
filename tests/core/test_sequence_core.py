import pytest
from powers_tool_core.core import CommandCancelled, CoreValidationError, SequenceRequest, RuntimeOptions
from powers_tool_core.support_policy import (
    LiveSupportPolicyError,
    SUPPORT_POLICY_MODE_VALIDATION,
)
from powers_tool_core.sequence import run_sequence
from powers_tool_core.support_features import sequence_feature_requirements


class FakeSession:
    capabilities = type("Capabilities", (), {"channels": (1, 2, 3)})()

    def __init__(self, *, fail_safe_off_channels: tuple[int, ...] = ()) -> None:
        self.writes: list[str] = []
        self.fail_safe_off_channels = fail_safe_off_channels
        self.queries: list[str] = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str) -> str:
        self.queries.append(command)
        responses = {
            "*IDN?": "KEYSIGHT,E36312A,SERIAL0000,1.0",
            "MEAS:VOLT? (@1)": "1.0",
            "MEAS:CURR? (@1)": "0.1",
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.1",
            "VOLT? (@2)": "1.0",
            "CURR? (@2)": "0.1",
            "VOLT? (@3)": "1.0",
            "CURR? (@3)": "0.1",
            "OUTP? (@1)": "0",
            "OUTP? (@2)": "0",
            "OUTP? (@3)": "0",
        }
        return responses.get(command, '0,"No error"')


class PSM2010Session(FakeSession):
    capabilities = type("Capabilities", (), {"channels": (1,)})()

    def __init__(self) -> None:
        super().__init__()
        self.output_range = "LOW"
        self.voltage = 1.0
        self.current = 0.05
        self.output_enabled = False

    def write(self, command: str) -> None:
        super().write(command)
        if command.startswith("VOLT:RANG "):
            self.output_range = command.split()[-1]
        elif command.startswith("VOLT "):
            self.voltage = float(command.split()[-1])
        elif command.startswith("CURR "):
            self.current = float(command.split()[-1])
        elif command == "OUTP ON":
            self.output_enabled = True
        elif command == "OUTP OFF":
            self.output_enabled = False

    def query(self, command: str) -> str:
        self.queries.append(command)
        responses = {
            "*IDN?": "GW.Inc,PSM-2010,SIM000006,FW1.00",
            "VOLT:RANG?": "P8V" if self.output_range == "LOW" else "P20V",
            "VOLT?": str(self.voltage),
            "CURR?": str(self.current),
            "OUTP?": "1" if self.output_enabled else "0",
            "SYST:ERR?": '0,"No error"',
        }
        return responses.get(command, '0,"No error"')


def request(document, *, resource="USB0::SIM::E36312A::INSTR", **runtime):
    return SequenceRequest(
        runtime=RuntimeOptions(resource=resource, **runtime),
        parameters={"document": document},
    )


def test_sequence_lint_does_not_open_visa() -> None:
    opened = False
    core_request = request({"version": 1, "steps": [{"action": "measure", "channel": 1}]})
    core_request = SequenceRequest(runtime=core_request.runtime, parameters={**core_request.parameters, "lint": True})

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        return FakeSession()

    data = run_sequence(core_request, opener=opener)

    assert opened is False
    assert data["status"] == "valid"
    assert data["step_count"] == 1


def test_sequence_core_has_no_webui_step_limit() -> None:
    core_request = request({"version": 1, "steps": [{"action": "wait", "seconds": 0}] * 251})
    core_request = SequenceRequest(runtime=core_request.runtime, parameters={**core_request.parameters, "lint": True})

    data = run_sequence(core_request, opener=lambda *args, **kwargs: FakeSession())

    assert data["status"] == "valid"
    assert data["step_count"] == 251


def test_sequence_v2_requires_loop_count_and_v1_rejects_it() -> None:
    with pytest.raises(CoreValidationError, match="version 2 requires loop_count"):
        run_sequence(request({"version": 2, "steps": [{"action": "wait", "seconds": 0}]}, dry_run=True))
    with pytest.raises(CoreValidationError, match="unsupported field"):
        run_sequence(request({"version": 1, "loop_count": 2, "steps": [{"action": "wait", "seconds": 0}]}, dry_run=True))


@pytest.mark.parametrize("loop_count", [0, -1, 10_001, True, 1.0, "2", None])
def test_sequence_v2_loop_count_is_strict(loop_count: object) -> None:
    with pytest.raises(CoreValidationError, match="integer from 1 to 10,000"):
        run_sequence(request({
            "version": 2,
            "loop_count": loop_count,
            "steps": [{"action": "wait", "seconds": 0}],
        }, dry_run=True))


def test_sequence_execution_unit_admission_boundaries() -> None:
    accepted = run_sequence(request({
        "version": 2,
        "loop_count": 10_000,
        "steps": [{"action": "wait", "seconds": 0}] * 100,
    }, dry_run=True))
    assert accepted["plan"]["execution_units"] == 1_000_000

    with pytest.raises(CoreValidationError, match="1,000,001 execution units"):
        run_sequence(request({
            "version": 2,
            "loop_count": 9_901,
            "steps": [{"action": "wait", "seconds": 0}] * 101,
        }, dry_run=True))


def test_sequence_bounds_results_and_reports_monotonic_progress() -> None:
    progress: list[dict[str, int | float]] = []
    data = run_sequence(
        request({
            "version": 2,
            "loop_count": 201,
            "steps": [{"action": "wait", "seconds": 0}],
        }),
        opener=lambda *args, **kwargs: FakeSession(),
        sleep=lambda seconds: None,
        progress_reporter=progress.append,
    )

    assert data["results_total"] == 201
    assert data["results_retained"] == 200
    assert data["results_truncated"] is True
    assert [item["loop_index"] for item in data["results"][:100]] == list(range(1, 101))
    assert [item["loop_index"] for item in data["results"][100:]] == list(range(102, 202))
    assert [item["percent"] for item in progress] == sorted(
        {item["percent"] for item in progress}
    )
    assert progress[-1] == {
        "completed_units": 201,
        "total_units": 201,
        "percent": 100,
    }


def test_sequence_two_loops_report_current_and_cumulative_counts() -> None:
    data = run_sequence(
        request({
            "version": 2,
            "loop_count": 2,
            "steps": [{"action": "wait", "seconds": 0}, {"action": "measure", "channel": 1}],
        }),
        opener=lambda *args, **kwargs: FakeSession(),
        sleep=lambda seconds: None,
    )

    assert data["loop_count"] == data["completed_loops"] == 2
    assert data["step_count"] == data["completed_steps"] == 2
    assert data["completed_step_executions"] == 4
    assert [item["loop_index"] for item in data["results"]] == [1, 1, 2, 2]


def test_sequence_feature_requirements_are_normalized_deduplicated_and_host_only_free() -> None:
    plan = {
        "steps": [
            {"action": "set"},
            {"action": "set"},
            {"action": "wait"},
            {"action": "log"},
            {"action": "measure"},
        ]
    }
    assert sequence_feature_requirements(plan) == (
        ("sequence_action", "measure"),
        ("sequence_action", "set"),
    )


def test_sequence_dry_run_does_not_open_visa_and_adds_preview() -> None:
    opened = False
    core_request = request(
        {"version": 1, "steps": [{"action": "set", "channel": 1, "voltage": 1.0, "current": 0.1}]},
        dry_run=True,
    )

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        return FakeSession()

    data = run_sequence(core_request, opener=opener)

    assert opened is False
    assert data["status"] == "planned"
    assert data["plan"]["steps"][0]["preview"]["commands"] == ["CURR 0.1,(@1)", "VOLT 1,(@1)"]


def test_psm2010_sequence_dry_run_uses_single_output_scpi_preview() -> None:
    data = run_sequence(
        request(
            {
                "version": 1,
                "steps": [{"action": "set", "channel": 1, "voltage": 1.0, "current": 0.1}],
            },
            resource="ASRL1::SIM::PSM2010::INSTR",
            dry_run=True,
            planning_model_id="gw-instek-psm-2010",
        )
    )

    assert data["plan"]["steps"][0]["preview"]["commands"] == ["CURR 0.1", "VOLT 1"]


def test_psm2010_sequence_uses_shared_range_resolution() -> None:
    session = PSM2010Session()
    data = run_sequence(
        request(
            {
                "version": 1,
                "steps": [
                    {"action": "set", "channel": 1, "voltage": 15.0, "current": 5.0}
                ],
            },
            resource="ASRL1::INSTR",
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        opener=lambda *args, **kwargs: session,
    )

    assert data["status"] == "completed"
    assert session.writes[:3] == ["VOLT:RANG HIGH", "CURR 5", "VOLT 15"]


def test_psm2010_sequence_rejects_cross_range_transition_while_output_is_on() -> None:
    session = PSM2010Session()
    data = run_sequence(
        request(
            {
                "version": 1,
                "steps": [
                    {"action": "set", "channel": 1, "voltage": 5.0, "current": 5.0},
                    {"action": "output-on", "channel": 1},
                    {"action": "set", "channel": 1, "voltage": 15.0, "current": 5.0},
                ],
            },
            resource="ASRL1::INSTR",
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        opener=lambda *args, **kwargs: session,
    )

    assert data["status"] == "failed"
    assert "output is ON" in data["failed_step"]["message"]
    assert "VOLT:RANG HIGH" not in session.writes


def test_sequence_dry_run_all_output_and_cycle_previews() -> None:
    core_request = request(
        {
            "version": 1,
            "steps": [
                {"action": "output-on", "channel": "all"},
                {"action": "output-state", "channel": "all"},
                {"action": "cycle-output", "channel": "all", "duration_ms": 250},
            ],
        },
        dry_run=True,
    )

    data = run_sequence(core_request, opener=lambda *args, **kwargs: FakeSession())

    assert data["plan"]["steps"][0]["preview"]["commands"] == [
        "OUTP ON,(@1)",
        "OUTP ON,(@2)",
        "OUTP ON,(@3)",
    ]
    assert data["plan"]["steps"][1]["preview"]["commands"] == [
        "OUTP? (@1)",
        "OUTP? (@2)",
        "OUTP? (@3)",
    ]
    assert data["plan"]["steps"][2]["preview"] == {
        "commands": [
            "OUTP ON,(@1)",
            "OUTP ON,(@2)",
            "OUTP ON,(@3)",
            "OUTP OFF,(@1)",
            "OUTP OFF,(@2)",
            "OUTP OFF,(@3)",
        ],
        "duration_ms": 250,
    }


def test_sequence_execute_cycle_output_all_sleeps_once() -> None:
    session = FakeSession()
    sleeps: list[float] = []
    core_request = request({"version": 1, "steps": [{"action": "cycle-output", "channel": "all", "duration_ms": 250}]})

    data = run_sequence(core_request, opener=lambda *args, **kwargs: session, sleep=sleeps.append)

    assert data["status"] == "completed"
    assert session.writes == [
        "OUTP ON,(@1)",
        "OUTP ON,(@2)",
        "OUTP ON,(@3)",
        "OUTP OFF,(@1)",
        "OUTP OFF,(@2)",
        "OUTP OFF,(@3)",
    ]
    assert sleeps == [0.25]


def test_sequence_keyboard_interrupt_safe_off_cleanup() -> None:
    session = FakeSession()
    core_request = request(
        {"version": 1, "steps": [{"action": "wait", "seconds": 1}, {"action": "measure", "channel": 1}]}
    )

    def interrupting_sleep(seconds: float) -> None:
        raise KeyboardInterrupt

    with pytest.raises(CommandCancelled) as raised:
        run_sequence(core_request, opener=lambda *args, **kwargs: session, sleep=interrupting_sleep)

    assert raised.value.data["status"] == "cancelled"
    assert raised.value.data["partial_result"]["failed_step"] == {
        "loop_index": 1,
        "index": 1,
        "action": "wait",
        "code": "interrupted",
    }
    assert session.writes == ["OUTP OFF,(@1)", "OUTP OFF,(@2)", "OUTP OFF,(@3)"]
    assert session.queries[-4:] == ["OUTP? (@1)", "OUTP? (@2)", "OUTP? (@3)", "SYST:ERR?"]


def test_sequence_cleanup_errors_do_not_replace_original_failure() -> None:
    session = FakeSession()
    original_write = session.write

    def write(command: str) -> None:
        if command == "OUTP ON,(@1)":
            raise ValueError("output on failed")
        if command == "OUTP OFF,(@2)":
            raise ValueError("cleanup channel 2 failed")
        original_write(command)

    session.write = write  # type: ignore[method-assign]
    core_request = request({"version": 1, "steps": [{"action": "output-on", "channel": 1}]})

    data = run_sequence(core_request, opener=lambda *args, **kwargs: session)

    assert data["status"] == "failed"
    assert data["failed_step"]["index"] == 1
    assert data["failed_step"]["message"] == "output on failed"
    assert data["cleanup"]["errors"] == [{"channel": 2, "message": "cleanup channel 2 failed"}]


def test_validation_mode_pending_sequence_keeps_same_session_cleanup_after_failure() -> None:
    session = FakeSession()
    original_write = session.write

    def write(command: str) -> None:
        if command == "VOLT 1,(@1)":
            raise ValueError("injected setpoint failure")
        original_write(command)

    session.write = write  # type: ignore[method-assign]
    core_request = request(
        {"version": 1, "steps": [{"action": "set", "channel": 1, "voltage": 1.0, "current": 0.1}]},
        resource="TCPIP0::192.0.2.1::INSTR",
        backend="@py",
        support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
    )

    data = run_sequence(core_request, opener=lambda *args, **kwargs: session, sleep=lambda _: None)

    assert data["status"] == "failed"
    assert data["failed_step"]["message"] == "injected setpoint failure"
    assert data["cleanup"]["safe_off_attempted"] is True
    assert session.queries[0] == "*IDN?"
    assert session.writes == ["CURR 0.1,(@1)", "OUTP OFF,(@1)", "OUTP OFF,(@2)", "OUTP OFF,(@3)"]
    assert session.closed


def test_validation_mode_sequence_rejects_missing_scope_before_steps() -> None:
    session = FakeSession()
    core_request = request(
        {"version": 1, "steps": [{"action": "measure", "channel": 1}]},
        resource="GPIB0::1::INSTR",
        support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
    )

    with pytest.raises(LiveSupportPolicyError, match="no exact transport/backend scope"):
        run_sequence(core_request, opener=lambda *args, **kwargs: session, sleep=lambda _: None)

    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed


def test_sequence_trigger_pulse_dry_run_and_execution(monkeypatch) -> None:
    doc = {
        "version": 1,
        "steps": [{"action": "trigger-pulse", "channel": 2, "pins": [1, 3], "polarity": "negative", "leave_trigger_configured": False}],
    }
    dry_run = run_sequence(request(doc, dry_run=True), opener=lambda *args, **kwargs: FakeSession())
    assert dry_run["plan"]["steps"][0]["preview"]["commands"][-1] == "*TRG"

    calls = []

    def pulse(_power_supply, **kwargs):
        calls.append(kwargs)
        return {"completed": True, **kwargs}

    monkeypatch.setattr("powers_tool_core.sequence.run_post_action_completion_pulse", pulse)
    data = run_sequence(request(doc), opener=lambda *args, **kwargs: FakeSession())

    assert data["status"] == "completed"
    assert calls == [{"channel": 2, "pins": (1, 3), "polarity": "negative", "leave_configured": False}]


def test_e3646a_sequence_execution() -> None:
    class E3646AFakeSession:
        capabilities = type("Capabilities", (), {"channels": (1, 2)})()

        def __init__(self) -> None:
            self.writes: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def write(self, command: str) -> None:
            self.writes.append(command)

        def query(self, command: str) -> str:
            responses = {
                "*IDN?": "KEYSIGHT,E3646A,SERIAL0000,1.0",
                "INST:NSEL?": "1",
                "VOLT?": "1.0",
                "CURR?": "0.1",
                "OUTP?": "0",
            }
            return responses.get(command, '0,"No error"')

    doc = {
        "version": 1,
        "steps": [
            {"action": "set", "channel": 2, "voltage": 1.5, "current": 0.05},
            {"action": "apply", "channel": 1, "voltage": 1.2, "current": 0.04, "no_output": True},
            {"action": "output-off", "channel": 2},
            {"action": "safe-off", "channel": 1},
            {"action": "cycle-output", "channel": 2, "duration_ms": 10},
        ],
    }

    session = E3646AFakeSession()
    req = SequenceRequest(
        runtime=RuntimeOptions(resource="ASRL1::INSTR", dry_run=False, simulate=False),
        parameters={"document": doc},
    )
    data = run_sequence(req, opener=lambda *args, **kwargs: session, sleep=lambda seconds: None)

    assert data["status"] == "completed"
    assert "INST:NSEL 2" in session.writes
    assert "VOLT 1.5" in session.writes
    assert "CURR 0.05" in session.writes
    assert "INST:NSEL 1" in session.writes
    assert "VOLT 1.2" in session.writes
    assert "CURR 0.04" in session.writes
    assert "OUTP OFF" in session.writes
    assert "OUTP ON" in session.writes


@pytest.mark.parametrize(
    ("idn", "resource"),
    [
        ("KEYSIGHT,EDU36311A,SERIAL0000,1.0", "USB0::FAKE::EDU36311A::INSTR"),
        ("KEYSIGHT,E3646A,SERIAL0000,1.0", "ASRL1::INSTR"),
    ],
)
def test_unsupported_model_sequence_trigger_pulse_rejects_before_steps(
    idn: str,
    resource: str,
) -> None:
    class UnsupportedPulseFakeSession:
        def __init__(self):
            self.queries = []
            self.writes = []
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.closed = True
            return None

        def write(self, command: str) -> None:
            self.writes.append(command)

        def query(self, command: str) -> str:
            self.queries.append(command)
            if command == "*IDN?":
                return idn
            return '0,"No error"'

    doc = {
        "version": 1,
        "steps": [
            {"action": "set", "channel": 1, "voltage": 1.0, "current": 0.1},
            {"action": "trigger-pulse", "channel": 1, "pins": [1]},
        ],
    }

    req = SequenceRequest(
        runtime=RuntimeOptions(resource=resource, dry_run=False, simulate=False),
        parameters={"document": doc},
    )
    session = UnsupportedPulseFakeSession()
    with pytest.raises(LiveSupportPolicyError, match="missing_feature_metadata"):
        run_sequence(req, opener=lambda *args, **kwargs: session)
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed


@pytest.mark.parametrize(
    "runtime",
    [
        RuntimeOptions(dry_run=True, planning_model_id="keysight-edu36311a"),
        RuntimeOptions(dry_run=True, planning_model_id="keysight-e3646a"),
        RuntimeOptions(simulate=True, resource="USB0::SIM::EDU36311A::INSTR"),
        RuntimeOptions(simulate=True, resource="ASRL1::SIM::E3646A::INSTR"),
    ],
)
def test_sequence_trigger_pulse_no_hardware_gate_remains_fail_closed(
    runtime: RuntimeOptions,
) -> None:
    opened = False
    doc = {
        "version": 1,
        "steps": [{"action": "trigger-pulse", "channel": 1, "pins": [1]}],
    }

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("sequence planning must not open VISA")

    with pytest.raises(CoreValidationError, match="E36312A supports this step"):
        run_sequence(
            SequenceRequest(runtime=runtime, parameters={"document": doc}),
            opener=opener,
        )

    assert opened is False
