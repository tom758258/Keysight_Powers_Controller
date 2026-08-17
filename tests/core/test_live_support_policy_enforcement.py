import pytest

import powers_tool_core.live_support as live_support_module
from powers_tool_core.core import (
    ConfirmationRequiredError,
    CoreIoError,
    CoreValidationError,
    OperationRequest,
    RuntimeOptions,
    TriggerRequest,
)
from powers_tool_core.instrument_io import run_instrument_io
from powers_tool_core.live_support import enforce_live_support
from powers_tool_core.operations import run_operation
from powers_tool_core.protection import run_protection
from powers_tool_core.ramp_list import RAMP_LIST_KIND, run_ramp_list
from powers_tool_core.readonly import run_readonly
from powers_tool_core.restore import run_restore
from powers_tool_core.snapshot import run_snapshot
from powers_tool_core.support_policy import (
    LiveSupportPolicyError,
    SUPPORT_POLICY_MODE_PRODUCT,
    SUPPORT_POLICY_MODE_VALIDATION,
    exact_live_support_metadata,
)
from powers_tool_core.trigger import run_trigger


class FakeSession:
    def __init__(self, idn: str) -> None:
        self.idn = idn
        self.queries: list[str] = []
        self.writes: list[str] = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True

    def query(self, command: str) -> str:
        self.queries.append(command)
        return {
            "*IDN?": self.idn,
            "MEAS:VOLT?": "1.0",
            "MEAS?": "1.0",
            "MEAS:CURR?": "0.1",
            "VOLT? (@1)": "1.0",
            "CURR? (@1)": "0.05",
            "VOLT?": "1.0",
            "CURR?": "0.05",
            "OUTP?": "OFF",
        }.get(command, '0,"No error"')

    def write(self, command: str) -> None:
        self.writes.append(command)


def _request(
    command: str,
    resource: str,
    *,
    backend: str | None = None,
    model: str | None = None,
    support_policy_mode: str = SUPPORT_POLICY_MODE_PRODUCT,
) -> OperationRequest:
    return OperationRequest(
        command,
        RuntimeOptions(
            resource=resource,
            backend=backend,
            expected_model_id=model,
            support_policy_mode=support_policy_mode,
        ),
    )


def test_runtime_options_defaults_to_product_support_policy_mode() -> None:
    assert RuntimeOptions().support_policy_mode == SUPPORT_POLICY_MODE_PRODUCT


def test_identify_expected_model_mismatch_stops_after_idn() -> None:
    session = FakeSession("Agilent Technologies,E3646A,0,1.0")

    with pytest.raises(CoreValidationError, match="Expected model_id keysight-e36312a"):
        run_instrument_io(
            _request(
                "identify",
                "TCPIP0::192.0.2.1::INSTR",
                backend="@py",
                model="keysight-e36312a",
            ),
            opener=lambda *args, **kwargs: session,
        )

    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed is True


def test_psm2010_identify_does_not_send_unconfirmed_extended_queries() -> None:
    session = FakeSession("GW.Inc,PSM-2010,SN,FW1.00")

    data = run_instrument_io(
        _request("identify", "ASRL1::INSTR", model="gw-instek-psm-2010"),
        opener=lambda *args, **kwargs: session,
    )

    assert data["options"] is None
    assert data["scpi_version"] is None
    assert data["remote_lockout_state"] is None
    assert session.queries == ["*IDN?"]


def test_psm2010_measure_is_product_open_and_uses_driver_queries() -> None:
    product_session = FakeSession("GW.Inc,PSM-2010,SN,FW1.00")
    data = run_instrument_io(
        _request(
            "measure",
            "ASRL1::INSTR",
            model="gw-instek-psm-2010",
        ),
        opener=lambda *args, **kwargs: product_session,
    )
    assert data["measurements"] == {"voltage": 1.0, "current": 0.1}
    assert product_session.queries == ["*IDN?", "MEAS?", "MEAS:CURR?"]


@pytest.mark.parametrize(
    ("command", "expected_queries"),
    [
        ("output-off", ["*IDN?", "SYST:ERR?"]),
        ("safe-off", ["*IDN?", "OUTP?", "SYST:ERR?"]),
        ("output-state", ["*IDN?", "OUTP?"]),
    ],
)
def test_psm2010_product_open_output_commands_use_existing_core_path(
    command: str, expected_queries: list[str]
) -> None:
    session = FakeSession("GW.Inc,PSM-2010,SN,FW1.00")
    request = OperationRequest(
        command,
        RuntimeOptions(
            resource="ASRL1::INSTR",
            expected_model_id="gw-instek-psm-2010",
        ),
        {"channel": 1},
    )

    data = run_operation(request, opener=lambda *args, **kwargs: session)

    assert data["idn"]["model"] == "PSM-2010"
    assert session.queries == expected_queries
    assert session.writes == ([] if command == "output-state" else ["OUTP OFF"])


@pytest.mark.parametrize(
    ("idn", "resource"),
    [
        ("KEYSIGHT,E36312A,SN,1.0", "USB0::1::INSTR"),
        ("KEYSIGHT,E36312A,SN,1.0", "TCPIP0::192.0.2.1::INSTR"),
        ("KEYSIGHT,EDU36311A,SN,1.0", "USB0::1::INSTR"),
        ("KEYSIGHT,EDU36311A,SN,1.0", "TCPIP0::192.0.2.1::INSTR"),
        ("KEYSIGHT,E3646A,SN,1.0", "ASRL1::INSTR"),
    ],
)
def test_validated_measure_scopes_authorize_after_idn(idn: str, resource: str) -> None:
    session = FakeSession(idn)
    data = run_instrument_io(_request("measure", resource), opener=lambda *args, **kwargs: session)
    assert data["measurements"] == {"voltage": 1.0, "current": 0.1}
    assert session.queries[0] == "*IDN?"
    assert "MEAS:VOLT?" in session.queries
    assert "MEAS:CURR?" in session.queries


@pytest.mark.parametrize(
    ("idn", "resource", "backend", "status"),
    [
        ("KEYSIGHT,E36312A,SN,1.0", "TCPIP0::192.0.2.1::INSTR", "@py", "transport_pending"),
        ("KEYSIGHT,EDU36311A,SN,1.0", "TCPIP0::192.0.2.1::INSTR", "@py", "transport_pending"),
        ("KEYSIGHT,E3646A,SN,1.0", "USB0::1::INSTR", None, "profile_validated"),
        ("KEYSIGHT,E36312A,SN,1.0", "GPIB0::1::INSTR", None, "profile_validated"),
        ("KEYSIGHT,E36312A,SN,1.0", "TCPIP0::192.0.2.1::INSTR", "@ivi", "profile_validated"),
    ],
)
def test_rejected_measure_scope_only_queries_idn(idn: str, resource: str, backend: str | None, status: str) -> None:
    session = FakeSession(idn)
    with pytest.raises(LiveSupportPolicyError, match=status) as raised:
        run_instrument_io(_request("measure", resource, backend=backend), opener=lambda *args, **kwargs: session)
    assert "policy_mode=product" in str(raised.value)
    assert session.queries == ["*IDN?"]
    assert session.closed


@pytest.mark.parametrize("model", ["E36312A", "EDU36311A"])
def test_validation_mode_allows_registered_tcpip_pyvisa_py_measure_scope(model: str) -> None:
    session = FakeSession(f"KEYSIGHT,{model},SN,1.0")
    data = run_instrument_io(
        _request(
            "measure",
            "TCPIP0::192.0.2.1::INSTR",
            backend="@py",
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        opener=lambda *args, **kwargs: session,
    )
    assert data["measurements"] == {"voltage": 1.0, "current": 0.1}
    assert session.queries == ["*IDN?", "MEAS:VOLT?", "MEAS:CURR?"]
    assert session.closed


def test_validation_mode_keeps_unregistered_scopes_and_commands_closed() -> None:
    session = FakeSession("KEYSIGHT,E3646A,SN,1.0")
    with pytest.raises(LiveSupportPolicyError, match="no exact transport/backend scope"):
        run_instrument_io(
            _request(
                "measure",
                "USB0::1::INSTR",
                support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            ),
            opener=lambda *args, **kwargs: session,
        )
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed


@pytest.mark.parametrize(
    ("operation_request", "detected_model", "message"),
    [
        (
            _request(
                "missing-command",
                "USB0::1::INSTR",
                support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            ),
            "keysight-e36312a",
            "missing_or_unknown_metadata",
        ),
        (
            _request(
                "trigger-list",
                "TCPIP0::192.0.2.1::INSTR",
                backend="@py",
                support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            ),
            "keysight-edu36311a",
            "not_supported_by_model",
        ),
    ],
)
def test_validation_mode_keeps_missing_and_unsupported_metadata_closed(
    operation_request: OperationRequest,
    detected_model: str,
    message: str,
) -> None:
    with pytest.raises(LiveSupportPolicyError, match=message):
        enforce_live_support(operation_request, detected_model)


def test_unknown_runtime_policy_mode_rejects_after_idn_before_measurement() -> None:
    session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    with pytest.raises(LiveSupportPolicyError, match="unknown_policy_mode"):
        run_instrument_io(
            _request("measure", "USB0::1::INSTR", support_policy_mode="future"),
            opener=lambda *args, **kwargs: session,
        )
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed


def test_expected_model_mismatch_precedes_validation_pending_scope_authorization() -> None:
    session = FakeSession("KEYSIGHT,EDU36311A,SN,1.0")
    with pytest.raises(CoreValidationError, match="Expected model_id keysight-e36312a"):
        run_instrument_io(
            _request(
                "measure",
                "TCPIP0::192.0.2.1::INSTR",
                backend="@py",
                model="keysight-e36312a",
                support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            ),
            opener=lambda *args, **kwargs: session,
        )
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed


def test_expected_model_mismatch_precedes_scope_rejection() -> None:
    session = FakeSession("KEYSIGHT,E3646A,SN,1.0")
    with pytest.raises(CoreValidationError, match="Expected model_id keysight-e36312a"):
        run_instrument_io(
            _request("measure", "USB0::1::INSTR", model="keysight-e36312a"),
            opener=lambda *args, **kwargs: session,
        )
    assert session.queries == ["*IDN?"]


def test_idn_resolves_to_canonical_model_id_before_exact_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def capture_scope(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(live_support_module, "ensure_live_scope_supported", capture_scope)
    request = _request("measure", "USB0::1::INSTR", model="keysight-e36312a")
    live_support_module.enforce_live_support_for_idn(
        request,
        "KEYSIGHT TECHNOLOGIES,E36312A,SN,1.0",
    )
    assert captured["model_id"] == "keysight-e36312a"
    assert "model" not in captured


@pytest.mark.parametrize(
    ("idn", "match"),
    [
        ("ACME,E36312A,SN,1.0", "manufacturer and model do not resolve"),
        ("KEYSIGHT,UNKNOWN_MODEL,SN,1.0", "unknown live support-policy model_id"),
        ("KEYSIGHT,E36103B,SN,1.0", "de-scoped"),
    ],
)
def test_unresolved_or_descoped_idn_fails_before_command_scpi(
    idn: str,
    match: str,
) -> None:
    session = FakeSession(idn)
    with pytest.raises(CoreValidationError, match=match):
        run_instrument_io(
            _request("measure", "USB0::1::INSTR"),
            opener=lambda *args, **kwargs: session,
        )
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed


@pytest.mark.parametrize(
    ("runner", "command", "parameters"),
    [
        (run_readonly, "read-status", {}),
        (run_readonly, "readback", {}),
        (run_readonly, "measure-all", {}),
        (run_protection, "protection-status", {}),
        (run_protection, "protection-set", {"channel": 1, "ovp_voltage": 2.0}),
        (run_protection, "clear-protection", {"channel": 1}),
        (run_snapshot, "snapshot", {}),
    ],
)
def test_model_aware_runners_reject_before_command_scpi(runner, command: str, parameters: dict[str, object]) -> None:
    session = FakeSession("KEYSIGHT,E3646A,SN,1.0")
    request = OperationRequest(command, RuntimeOptions(resource="USB0::1::INSTR", confirm=True), parameters)
    with pytest.raises(LiveSupportPolicyError):
        runner(request, opener=lambda *args, **kwargs: session)
    assert session.queries == ["*IDN?"]
    assert session.writes == []


def test_promoted_output_authorizes_after_idn_and_writes() -> None:
    session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    request = OperationRequest(
        "output-on", RuntimeOptions(resource="USB0::1::INSTR", confirm=True), {"channel": 1}
    )
    run_operation(request, opener=lambda *args, **kwargs: session)
    assert session.queries[0] == "*IDN?"
    assert any(command.startswith("OUTP ON") for command in session.writes)






@pytest.mark.parametrize(
    ("model_id", "command", "resource", "backend"),
    [
        ("keysight-e36312a", "output-on", "USB0::1::INSTR", None),
        ("keysight-e36312a", "trigger-pulse", "USB0::1::INSTR", None),
        ("keysight-e36312a", "trigger-fire", "USB0::1::INSTR", None),
        ("keysight-edu36311a", "log", "TCPIP0::192.0.2.1::INSTR", None),
        ("keysight-e3646a", "doctor", "ASRL1::INSTR", None),
    ],
)
def test_product_mode_opens_promoted_exact_scopes(
    model_id: str, command: str, resource: str, backend: str | None
) -> None:
    scope = enforce_live_support(_request(command, resource, backend=backend), model_id)
    assert scope.admission_kind == "product"




@pytest.mark.parametrize(
    ("model_id", "command", "resource", "backend"),
    [
        ("keysight-e36312a", "output-on", "ASRL1::INSTR", None),
        ("keysight-e36312a", "output-on", "USB0::1::INSTR", "@py"),
        ("keysight-e36312a", "output-on", "USB0::1::INSTR", "@ivi"),
        ("keysight-e36312a", "output-on", "", None),
        ("keysight-edu36311a", "measure-all", "USB0::1::INSTR", None),
        ("keysight-e3646a", "doctor", "TCPIP0::192.0.2.1::INSTR", None),
        ("keysight-e36312a", "trigger-pulse", "ASRL1::INSTR", None),
        ("keysight-e36312a", "trigger-fire", "USB0::1::INSTR", "@py"),
    ],
)
def test_promoted_commands_fail_closed_outside_exact_inventory(
    model_id: str, command: str, resource: str, backend: str | None
) -> None:
    with pytest.raises(CoreValidationError):
        enforce_live_support(
            _request(
                command,
                resource,
                backend=backend,
                support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            ),
            model_id,
        )


def test_e3646a_log_is_product_open_only_for_asrl_system_visa() -> None:
    for mode in (SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION):
        scope = enforce_live_support(
            _request("log", "ASRL1::INSTR", support_policy_mode=mode),
            "keysight-e3646a",
        )
        assert scope.validation_status == "live_validated_full_suite"
        assert scope.admission_kind == "product"
        assert scope.accepted_evidence_ids == (
            "keysight-e3646a-asrl-system-visa-20260807-full",
        )

    for resource, backend in (
        ("USB0::1::INSTR", None),
        ("TCPIP0::192.0.2.1::INSTR", None),
        ("ASRL1::INSTR", "@py"),
        ("ASRL1::INSTR", "@bt"),
        ("ASRL1::INSTR", "@ivi"),
    ):
        with pytest.raises(CoreValidationError):
            enforce_live_support(
                _request(
                    "log",
                    resource,
                    backend=backend,
                ),
                "keysight-e3646a",
            )


def test_promoted_command_changes_only_exact_public_product_metadata() -> None:
    metadata = exact_live_support_metadata(
        model_id="keysight-e36312a",
        resource="USB0::1::INSTR",
        backend=None,
        commands=("output-on", "trigger-status"),
    )
    output_on = metadata["commands"]["output-on"]
    assert output_on["profile_supported"] is True
    assert output_on["exact_scope_validation_status"] == "live_validated_full_suite"
    assert output_on["product_open"] is True
    assert metadata["commands"]["trigger-status"]["product_open"] is True


def test_validation_candidate_expected_model_mismatch_stops_before_output_scpi() -> None:
    session = FakeSession("KEYSIGHT,EDU36311A,SN,1.0")
    request = OperationRequest(
        "output-on",
        RuntimeOptions(
            resource="USB0::1::INSTR",
            expected_model_id="keysight-e36312a",
            confirm=True,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        {"channel": 1},
    )
    with pytest.raises(CoreValidationError, match="Expected model_id keysight-e36312a"):
        run_operation(request, opener=lambda *args, **kwargs: session)
    assert session.queries == ["*IDN?"]
    assert session.writes == []


@pytest.mark.parametrize(
    "model_id",
    ["generic-scpi", "keysight-e36313a", "keysight-e36103b"],
)
def test_validation_candidate_rejects_nonactive_physical_policy_models(model_id: str) -> None:
    with pytest.raises(CoreValidationError):
        enforce_live_support(
            _request(
                "output-on",
                "USB0::1::INSTR",
                support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            ),
            model_id,
        )


def test_exempt_clear_keeps_its_existing_no_idn_behavior() -> None:
    session = FakeSession("KEYSIGHT,E3646A,SN,1.0")
    data = run_instrument_io(_request("clear", "USB0::1::INSTR"), opener=lambda *args, **kwargs: session)
    assert data["cleared"] is True
    assert session.queries == []
    assert session.writes == ["*CLS"]


def test_trigger_abort_pending_scope_rejects_in_product_and_runs_in_validation_mode() -> None:
    product_session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    product_request = TriggerRequest(
        "trigger-abort",
        RuntimeOptions(resource="TCPIP0::192.0.2.1::INSTR", backend="@py"),
        {"channel": 1},
    )
    with pytest.raises(LiveSupportPolicyError, match="transport_pending"):
        run_trigger(product_request, opener=lambda *args, **kwargs: product_session)
    assert product_session.queries == ["*IDN?"]
    assert product_session.writes == []
    assert product_session.closed

    validation_session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    validation_request = TriggerRequest(
        "trigger-abort",
        RuntimeOptions(
            resource="TCPIP0::192.0.2.1::INSTR",
            backend="@py",
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        {"channel": 1},
    )
    data = run_trigger(validation_request, opener=lambda *args, **kwargs: validation_session)
    assert data["channels"] == [1]
    assert validation_session.queries[0] == "*IDN?"
    assert validation_session.writes == ["ABOR (@1)"]
    assert validation_session.closed


def test_trigger_source_feature_pending_rejects_product_before_setup_and_runs_in_validation(
    monkeypatch,
) -> None:
    parameters = {
        "channel": 1,
        "source": "immediate",
        "voltage": 1.0,
        "current": 0.1,
    }
    product_session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    product_request = TriggerRequest(
        "trigger-step",
        RuntimeOptions(resource="TCPIP0::192.0.2.1::INSTR", backend="@py"),
        parameters,
    )
    with pytest.raises(LiveSupportPolicyError, match="transport_pending"):
        run_trigger(product_request, opener=lambda *args, **kwargs: product_session)
    assert product_session.queries == ["*IDN?"]
    assert product_session.writes == []
    assert product_session.closed

    validation_session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    validation_request = TriggerRequest(
        "trigger-step",
        RuntimeOptions(
            resource="TCPIP0::192.0.2.1::INSTR",
            backend="@py",
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        parameters,
    )
    calls = []

    def native_step(*args, **kwargs):
        calls.append(kwargs)
        return {"source": kwargs["source"], "armed": True}

    monkeypatch.setattr("powers_tool_core.trigger._native_step", native_step)
    result = run_trigger(
        validation_request,
        opener=lambda *args, **kwargs: validation_session,
        sleep=lambda _: None,
    )
    assert result["trigger"]["source"] == "immediate"
    assert calls and calls[0]["source"] == "immediate"
    assert validation_session.queries[0] == "*IDN?"
    assert validation_session.closed


def test_trigger_expected_model_mismatch_precedes_validation_pending_scope() -> None:
    session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    request = TriggerRequest(
        "trigger-abort",
        RuntimeOptions(
            resource="TCPIP0::192.0.2.1::INSTR",
            backend="@py",
            expected_model_id="keysight-edu36311a",
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        {"channel": 1},
    )
    with pytest.raises(CoreValidationError, match="Expected model_id keysight-edu36311a"):
        run_trigger(request, opener=lambda *args, **kwargs: session)
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed


def test_validation_mode_keeps_unsupported_trigger_command_closed() -> None:
    session = FakeSession("KEYSIGHT,EDU36311A,SN,1.0")
    request = TriggerRequest(
        "trigger-step",
        RuntimeOptions(
            resource="TCPIP0::192.0.2.1::INSTR",
            backend="@py",
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        {"channel": 1, "source": "bus"},
    )
    with pytest.raises(LiveSupportPolicyError, match="not_supported_by_model"):
        run_trigger(request, opener=lambda *args, **kwargs: session)
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed


def _restore_document(
    *, model: str = "E36312A", serial: str = "SN", voltage: float = 1.0
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "kind": "powers-tool-snapshot",
        "reported_identity": {
            "manufacturer": "KEYSIGHT",
            "model": model,
            "serial": serial,
            "firmware": "1.0",
            "parse_ok": True,
        },
        "resolved_identity": {
            "vendor_id": "keysight",
            "model_id": "keysight-e36312a",
            "model_name": "E36312A",
            "display_name": "Keysight E36312A",
        },
        "outputs": [{"channel": 1, "enabled": False}],
        "readback": [{"channel": 1, "setpoints": {"voltage": voltage, "current": 0.1}}],
        "protection_settings": [
            {
                "channel": 1,
                "protection": {
                    "ovp_voltage": None,
                    "ocp_enabled": None,
                    "ocp_delay": None,
                    "ocp_delay_trigger": None,
                },
            }
        ],
    }


def test_product_mode_restore_rejects_pending_pyvisa_scope_before_restore_scpi() -> None:
    session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    request = OperationRequest(
        "restore-from-snapshot",
        RuntimeOptions(
            resource="TCPIP0::192.0.2.1::INSTR",
            backend="@py",
            confirm=True,
            support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT,
        ),
        {"document": _restore_document(), "channel": 1},
    )
    with pytest.raises(LiveSupportPolicyError, match="transport_pending"):
        run_restore(request, opener=lambda *args, **kwargs: session)
    assert session.queries == ["*IDN?"]
    assert session.writes == []
    assert session.closed


def test_validation_mode_restore_keeps_identity_and_confirmation_guards() -> None:
    mismatch_session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    mismatch_request = OperationRequest(
        "restore-from-snapshot",
        RuntimeOptions(
            resource="TCPIP0::192.0.2.1::INSTR",
            backend="@py",
            confirm=True,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        {"document": _restore_document(serial="OTHER"), "channel": 1},
    )
    with pytest.raises(CoreValidationError, match="does not match snapshot serial"):
        run_restore(mismatch_request, opener=lambda *args, **kwargs: mismatch_session)
    assert mismatch_session.queries == ["*IDN?"]
    assert mismatch_session.writes == []
    assert mismatch_session.closed

    opened = False

    def opener(*args, **kwargs):
        nonlocal opened
        opened = True
        return FakeSession("KEYSIGHT,E36312A,SN,1.0")

    with pytest.raises(ConfirmationRequiredError):
        run_restore(
            OperationRequest(
                "restore-from-snapshot",
                RuntimeOptions(
                    resource="TCPIP0::192.0.2.1::INSTR",
                    backend="@py",
                    support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
                ),
                {"document": _restore_document(), "channel": 1},
            ),
            opener=opener,
        )
    assert opened is False

    unsafe_session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    unsafe_request = OperationRequest(
        "restore-from-snapshot",
        RuntimeOptions(
            resource="TCPIP0::192.0.2.1::INSTR",
            backend="@py",
            confirm=True,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        {"document": _restore_document(voltage=999.0), "channel": 1},
    )
    with pytest.raises(CoreIoError, match="voltage 999 exceeds effective maximum"):
        run_restore(unsafe_request, opener=lambda *args, **kwargs: unsafe_session)
    assert unsafe_session.queries == ["*IDN?"]
    assert unsafe_session.writes == []
    assert unsafe_session.closed


def test_validation_mode_restore_success_reports_current_identity_without_changing_scpi() -> None:
    session = FakeSession("Keysight Technologies,E36312A,SN,2.10")
    request = OperationRequest(
        "restore-from-snapshot",
        RuntimeOptions(
            resource="USB0::0x2A8D::0x1102::SN::0::INSTR",
            confirm=True,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        {"document": _restore_document(), "channel": 1},
    )

    result = run_restore(request, opener=lambda *args, **kwargs: session)

    assert result["reported_identity"] == {
        "manufacturer": "Keysight Technologies",
        "model": "E36312A",
        "serial": "SN",
        "firmware": "2.10",
        "parse_ok": True,
    }
    assert result["resolved_identity"] == {
        "vendor_id": "keysight",
        "model_id": "keysight-e36312a",
        "model_name": "E36312A",
        "display_name": "Keysight E36312A",
    }
    assert session.queries == ["*IDN?", "SYST:ERR?"]
    assert session.writes == ["OUTP OFF,(@1)", "CURR 0.1,(@1)", "VOLT 1,(@1)"]
    assert session.closed


def _ramp_list_document(*, channel: int = 1) -> dict[str, object]:
    return {
        "kind": RAMP_LIST_KIND,
        "version": 2,
        "segments": [
            {
                "channel": channel,
                "current": 0.1,
                "start_voltage": 0.0,
                "stop_voltage": 0.5,
                "step_voltage": 0.5,
                "delay_ms": 0,
                "hold_ms": 0,
            }
        ],
    }


def test_validation_mode_ramp_list_uses_pending_scope_then_keeps_channel_limit() -> None:
    accepted_session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    accepted_request = OperationRequest(
        "ramp-list",
        RuntimeOptions(
            resource="TCPIP0::192.0.2.1::INSTR",
            backend="@py",
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        {"document": _ramp_list_document()},
    )
    data = run_ramp_list(accepted_request, opener=lambda *args, **kwargs: accepted_session, sleep=lambda _: None)
    assert data["status"] == "completed"
    assert accepted_session.queries == ["*IDN?", "SYST:ERR?"]
    assert accepted_session.writes == ["CURR 0.1,(@1)", "VOLT 0,(@1)", "VOLT 0.5,(@1)"]
    assert accepted_session.closed

    limit_session = FakeSession("KEYSIGHT,E36312A,SN,1.0")
    limit_request = OperationRequest(
        "ramp-list",
        RuntimeOptions(
            resource="TCPIP0::192.0.2.1::INSTR",
            backend="@py",
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        ),
        {"document": _ramp_list_document(channel=4)},
    )
    with pytest.raises(CoreValidationError, match="channel 4"):
        run_ramp_list(limit_request, opener=lambda *args, **kwargs: limit_session, sleep=lambda _: None)
    assert limit_session.queries == ["*IDN?"]
    assert limit_session.writes == []
    assert limit_session.closed
