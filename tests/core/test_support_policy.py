import json
from dataclasses import replace

import pytest

from powers_tool_core.support_features import supported_sequence_actions_for_model_id

from powers_tool_core.support_policy import (
    ACTIVE_LIVE_POLICY_MODEL_IDS,
    BACKEND_CUSTOM_VISA,
    BACKEND_PYVISA_BT,
    BACKEND_PYVISA_PY,
    BACKEND_SYSTEM_VISA,
    EXEMPT_LIVE_DIAGNOSTIC_COMMANDS,
    LIVE_SUPPORT_POLICY_REGISTRY,
    PURE_OFFLINE_COMMANDS,
    SUPPORT_POLICY_MODE_PRODUCT,
    SUPPORT_POLICY_MODE_VALIDATION,
    TRANSPORT_ASRL,
    TRANSPORT_GPIB,
    TRANSPORT_TCPIP,
    TRANSPORT_UNKNOWN,
    TRANSPORT_USB,
    VALIDATION_STATUS_FEATURE_PENDING,
    VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
    VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL,
    VALIDATION_STATUS_PROFILE_VALIDATED,
    VALIDATION_STATUS_TRANSPORT_PENDING,
    CommandLiveSupportScope,
    CommandFeatureSupportScope,
    CommandSupportPolicy,
    LiveSupportPolicyError,
    ModelSupportPolicy,
    command_live_support,
    command_live_support_matrix,
    ensure_live_scope_supported,
    exact_live_support_metadata,
    find_live_support_scope,
    find_feature_support,
    is_live_support_policy_exempt,
    internal_validation_candidate_inventory,
    live_support_policy_metadata,
    normalize_backend,
    normalize_support_feature_value,
    normalize_transport,
    validate_live_support_metadata,
    unevaluated_live_support_policy_metadata,
)


E36312A_VALIDATED_COMMANDS = {
    "measure",
    "output-state",
    "read-status",
    "readback",
    "validate-readonly",
    "capabilities",
    "set",
    "output-off",
    "safe-off",
    "cycle-output",
    "apply",
    "ramp",
    "smoke-output",
    "ramp-list",
    "sequence",
    "protection-status",
    "protection-set",
    "clear-protection",
    "snapshot",
    "trigger-status",
    "trigger-step",
    "trigger-list",
    "trigger-abort",
    "output-on",
    "log",
    "doctor",
    "measure-all",
    "restore-from-snapshot",
    "trigger-fire",
    "trigger-pulse",
}
EDU36311A_VALIDATED_COMMANDS = {
    "measure",
    "output-state",
    "read-status",
    "readback",
    "validate-readonly",
    "capabilities",
    "set",
    "output-off",
    "safe-off",
    "cycle-output",
    "apply",
    "ramp",
    "smoke-output",
    "ramp-list",
    "sequence",
    "protection-status",
    "protection-set",
    "clear-protection",
    "output-on",
    "log",
    "doctor",
}
E3646A_VALIDATED_COMMANDS = {
    "measure",
    "output-state",
    "read-status",
    "readback",
    "capabilities",
    "set",
    "output-off",
    "safe-off",
    "cycle-output",
    "apply",
    "ramp",
    "smoke-output",
    "ramp-list",
    "sequence",
    "output-on",
    "doctor",
    "log",
}
PSM2010_VALIDATED_COMMANDS = {
    "measure",
    "output-state",
    "readback",
    "read-status",
    "capabilities",
    "output-off",
    "safe-off",
}
PSM2010_UNSUPPORTED_TRIGGER_COMMANDS = {
    "trigger-pulse",
    "trigger-status",
    "trigger-step",
    "trigger-list",
    "trigger-fire",
    "trigger-abort",
}


def _commands_for_scope(model_id: str, transport: str, backend: str) -> set[str]:
    return {
        command
        for command, policy in command_live_support_matrix(model_id).items()
        if any(
            scope.transport_scope == transport and scope.backend_scope == backend
            for scope in policy.scopes
        )
    }


def _replace_command(
    registry: tuple[ModelSupportPolicy, ...],
    model_id: str,
    command: str,
    replacement: CommandSupportPolicy,
) -> tuple[ModelSupportPolicy, ...]:
    return tuple(
        replace(
            model_policy,
            commands=tuple(
                replacement if policy.command == command else policy
                for policy in model_policy.commands
            ),
        )
        if model_policy.model_id == model_id
        else model_policy
        for model_policy in registry
    )


def test_required_constants_are_stable() -> None:
    assert SUPPORT_POLICY_MODE_PRODUCT == "product"
    assert SUPPORT_POLICY_MODE_VALIDATION == "validation"
    assert {
        VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL,
        VALIDATION_STATUS_PROFILE_VALIDATED,
        VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
        VALIDATION_STATUS_TRANSPORT_PENDING,
        VALIDATION_STATUS_FEATURE_PENDING,
    } == {
        "not_supported_by_model",
        "profile_validated",
        "live_validated_full_suite",
        "transport_pending",
        "feature_pending",
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("USB0::fixture::INSTR", TRANSPORT_USB),
        (" tcpip0::192.0.2.1::instr ", TRANSPORT_TCPIP),
        ("ASRL7::INSTR", TRANSPORT_ASRL),
        ("GPIB0::5::INSTR", TRANSPORT_GPIB),
        ("usb", TRANSPORT_USB),
        ("unrecognized", TRANSPORT_UNKNOWN),
        (None, TRANSPORT_UNKNOWN),
        ("   ", TRANSPORT_UNKNOWN),
    ],
)
def test_transport_normalization(value: str | None, expected: str) -> None:
    assert normalize_transport(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, BACKEND_SYSTEM_VISA),
        ("", BACKEND_SYSTEM_VISA),
        ("   ", BACKEND_SYSTEM_VISA),
        (" @PY ", BACKEND_PYVISA_PY),
        ("@bt", BACKEND_PYVISA_BT),
        (" @BT ", BACKEND_PYVISA_BT),
        ("@ivi", BACKEND_CUSTOM_VISA),
    ],
)
def test_backend_normalization(value: str | None, expected: str) -> None:
    assert normalize_backend(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("system_visa", BACKEND_SYSTEM_VISA),
        ("pyvisa_py", BACKEND_PYVISA_PY),
        ("pyvisa_bt", BACKEND_PYVISA_BT),
        ("custom_visa", BACKEND_CUSTOM_VISA),
    ],
)
def test_canonical_backend_labels_remain_canonical(value: str, expected: str) -> None:
    assert normalize_backend(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "@py",
        "@bt",
        "@ivi",
        "system_visa",
        "pyvisa_py",
        "pyvisa_bt",
        "custom_visa",
    ],
)
def test_backend_normalization_is_idempotent(value: str | None) -> None:
    normalized = normalize_backend(value)
    assert normalize_backend(normalized) == normalized


@pytest.mark.parametrize(
    ("model", "transport", "commands"),
    [
        ("keysight-e36312a", TRANSPORT_USB, E36312A_VALIDATED_COMMANDS),
        ("keysight-e36312a", TRANSPORT_TCPIP, E36312A_VALIDATED_COMMANDS),
        ("keysight-edu36311a", TRANSPORT_USB, EDU36311A_VALIDATED_COMMANDS),
        ("keysight-edu36311a", TRANSPORT_TCPIP, EDU36311A_VALIDATED_COMMANDS),
        ("keysight-e3646a", TRANSPORT_ASRL, E3646A_VALIDATED_COMMANDS),
        ("gw-instek-psm-2010", TRANSPORT_ASRL, PSM2010_VALIDATED_COMMANDS),
    ],
)
def test_exact_validated_command_inventory(
    model: str, transport: str, commands: set[str]
) -> None:
    assert _commands_for_scope(model, transport, BACKEND_SYSTEM_VISA) == commands
    for command in commands:
        scope = find_live_support_scope(
            model_id=model,
            command=command,
            transport=transport,
            backend=BACKEND_SYSTEM_VISA,
        )
        assert scope is not None
        assert scope.validation_status == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE
        assert scope.accepted_evidence_ids
        assert scope.accepted_evidence_ids
        assert "pyvisa-py" in (scope.note or "")


@pytest.mark.parametrize(
    ("model", "commands"),
    [
        ("keysight-e36312a", E36312A_VALIDATED_COMMANDS),
        ("keysight-edu36311a", EDU36311A_VALIDATED_COMMANDS),
    ],
)
def test_tcpip_pyvisa_py_pending_inventory(model: str, commands: set[str]) -> None:
    assert _commands_for_scope(model, TRANSPORT_TCPIP, BACKEND_PYVISA_PY) == commands
    for command in commands:
        scope = find_live_support_scope(
            model_id=model,
            command=command,
            transport=TRANSPORT_TCPIP,
            backend="@py",
        )
        assert scope is not None
        assert scope.validation_status == VALIDATION_STATUS_TRANSPORT_PENDING
        assert "pending separate live validation" in (scope.note or "")


@pytest.mark.parametrize(
    ("model", "transport", "backend"),
    [
        ("keysight-e36312a", TRANSPORT_USB, BACKEND_PYVISA_PY),
        ("keysight-edu36311a", TRANSPORT_USB, BACKEND_PYVISA_PY),
        ("keysight-e3646a", TRANSPORT_TCPIP, BACKEND_SYSTEM_VISA),
        ("keysight-e3646a", TRANSPORT_USB, BACKEND_SYSTEM_VISA),
        ("keysight-e3646a", TRANSPORT_TCPIP, BACKEND_PYVISA_PY),
        ("keysight-e36312a", TRANSPORT_TCPIP, BACKEND_CUSTOM_VISA),
    ],
)
def test_unregistered_scopes_do_not_appear(
    model: str, transport: str, backend: str
) -> None:
    assert _commands_for_scope(model, transport, backend) == set()


@pytest.mark.parametrize("mode", [SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION])
def test_validated_scope_is_allowed_in_both_modes(mode: str) -> None:
    scope = ensure_live_scope_supported(
        model_id="keysight-e36312a",
        command="measure",
        transport="USB0::fixture::INSTR",
        backend=None,
        support_policy_mode=mode,
    )
    assert scope.validation_status == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE


def test_product_rejects_and_validation_allows_transport_pending() -> None:
    arguments = {
        "model_id": "keysight-e36312a",
        "command": "measure",
        "transport": "TCPIP",
        "backend": "@py",
    }
    with pytest.raises(LiveSupportPolicyError, match="transport_pending"):
        ensure_live_scope_supported(
            **arguments, support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT
        )
    scope = ensure_live_scope_supported(
        **arguments, support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION
    )
    assert scope.validation_status == VALIDATION_STATUS_TRANSPORT_PENDING


def test_psm2010_has_only_exact_product_open_scope() -> None:
    assert _commands_for_scope(
        "gw-instek-psm-2010", TRANSPORT_ASRL, BACKEND_SYSTEM_VISA
    ) == PSM2010_VALIDATED_COMMANDS

    for command in PSM2010_VALIDATED_COMMANDS:
        for mode in (SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION):
            scope = ensure_live_scope_supported(
                model_id="gw-instek-psm-2010",
                command=command,
                transport="ASRL1::INSTR",
                backend=None,
                support_policy_mode=mode,
            )
            assert scope.validation_status == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE
            assert scope.accepted_evidence_ids == (
                "gw-instek-psm-2010-asrl-system-visa-20260811-full",
            )
            assert scope.admission_kind == "product"
        assert scope.candidate_basis_evidence_ids == ()


@pytest.mark.parametrize(
    ("transport", "backend"),
    [
        ("GPIB0::5::INSTR", None),
        ("USB0::fixture::INSTR", None),
        ("TCPIP0::192.0.2.1::INSTR", None),
        ("ASRL1::INSTR", "@py"),
        ("ASRL1::INSTR", "@bt"),
        ("ASRL1::INSTR", "@ivi"),
    ],
)
@pytest.mark.parametrize("mode", [SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION])
def test_psm2010_unregistered_live_scopes_fail_closed(
    transport: str, backend: str | None, mode: str
) -> None:
    with pytest.raises(LiveSupportPolicyError):
        ensure_live_scope_supported(
            model_id="gw-instek-psm-2010",
            command="measure",
            transport=transport,
            backend=backend,
            support_policy_mode=mode,
        )


@pytest.mark.parametrize("command", ["set", "output-on", "doctor"])
def test_psm2010_validation_candidates_remain_closed_in_product_mode(command: str) -> None:
    assert command_live_support("gw-instek-psm-2010", command).scopes == ()
    with pytest.raises(LiveSupportPolicyError):
        ensure_live_scope_supported(
            model_id="gw-instek-psm-2010",
            command=command,
            transport="ASRL1::INSTR",
            backend=None,
            support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT,
        )

    scope = ensure_live_scope_supported(
        model_id="gw-instek-psm-2010",
        command=command,
        transport="ASRL1::INSTR",
        backend=None,
        support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
    )
    assert scope.admission_kind == "validation_candidate"
    assert scope.validation_status == VALIDATION_STATUS_TRANSPORT_PENDING
    assert scope.accepted_evidence_ids == ()


@pytest.mark.parametrize(
    ("transport", "backend"),
    [
        ("USB0::fixture::INSTR", None),
        ("TCPIP0::192.0.2.1::INSTR", None),
        ("GPIB0::5::INSTR", None),
        ("ASRL1::INSTR", "@py"),
        ("ASRL1::INSTR", "@bt"),
        ("ASRL1::INSTR", "@ivi"),
    ],
)
def test_psm2010_validation_candidates_reject_nonexact_connections(
    transport: str,
    backend: str | None,
) -> None:
    with pytest.raises(LiveSupportPolicyError):
        ensure_live_scope_supported(
            model_id="gw-instek-psm-2010",
            command="set",
            transport=transport,
            backend=backend,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        )


@pytest.mark.parametrize("command", sorted(PSM2010_UNSUPPORTED_TRIGGER_COMMANDS))
@pytest.mark.parametrize("mode", [SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION])
def test_psm2010_trigger_family_is_not_supported_by_model(command: str, mode: str) -> None:
    policy = command_live_support("gw-instek-psm-2010", command)

    assert policy.validation_status == VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL
    assert policy.scopes == ()
    with pytest.raises(LiveSupportPolicyError, match="not_supported_by_model"):
        ensure_live_scope_supported(
            model_id="gw-instek-psm-2010",
            command=command,
            transport="ASRL1::INSTR",
            backend=None,
            support_policy_mode=mode,
        )


def test_psm2010_validation_sequence_rejects_trigger_action_feature() -> None:
    with pytest.raises(LiveSupportPolicyError, match="missing_feature_metadata"):
        ensure_live_scope_supported(
            model_id="gw-instek-psm-2010",
            command="sequence",
            transport="ASRL1::INSTR",
            backend=None,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            feature_requirements=(("sequence_action", "trigger-pulse"),),
        )

    scope = ensure_live_scope_supported(
        model_id="gw-instek-psm-2010",
        command="sequence",
        transport="ASRL1::INSTR",
        backend=None,
        support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        feature_requirements=(("sequence_action", "set"),),
    )
    assert scope.admission_kind == "validation_candidate"


def test_feature_pending_is_validation_only_with_synthetic_metadata() -> None:
    base = command_live_support("keysight-e36312a", "sequence")
    feature_scope = replace(base.scopes[0], feature_scopes=(
        CommandFeatureSupportScope(
            feature_kind="sequence_action",
            feature_value="set",
            validation_status=VALIDATION_STATUS_FEATURE_PENDING,
            note="Synthetic feature candidate.",
        ),
    ))
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "sequence",
        replace(base, scopes=(feature_scope,)),
    )
    with pytest.raises(LiveSupportPolicyError, match="feature_pending"):
        ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command="sequence",
            feature_requirements=(("sequence_action", "set"),),
            transport=feature_scope.transport_scope,
            backend=feature_scope.backend_scope,
            support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT,
            registry=registry,
        )
    assert (
        ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command="sequence",
            transport=feature_scope.transport_scope,
            backend=feature_scope.backend_scope,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            feature_requirements=(("sequence_action", "set"),),
            registry=registry,
        ).validation_status
        == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE
    )


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    [
        ("sequence_action", " SET ", "set"),
        ("trigger_source", "BUS", "bus"),
        ("trigger_source", "imm", "immediate"),
    ],
)
def test_feature_value_normalization(kind: str, value: str, expected: str) -> None:
    assert normalize_support_feature_value(kind, value) == expected


def test_feature_lookup_is_exact_and_rejects_duplicates() -> None:
    scope = command_live_support("keysight-e36312a", "trigger-step").scopes[0]
    assert find_feature_support(scope, "trigger_source", "IMM").feature_value == "immediate"
    without_immediate = replace(
        scope,
        feature_scopes=tuple(
            feature for feature in scope.feature_scopes if feature.feature_value != "immediate"
        ),
    )
    assert find_feature_support(without_immediate, "trigger_source", "immediate") is None
    duplicated = replace(scope, feature_scopes=scope.feature_scopes + (scope.feature_scopes[0],))
    with pytest.raises(LiveSupportPolicyError, match="duplicate live support feature metadata"):
        find_feature_support(duplicated, "trigger_source", scope.feature_scopes[0].feature_value)


def test_transport_pending_parent_requires_and_allows_pending_feature_only_in_validation() -> None:
    arguments = {
        "model_id": "keysight-e36312a",
        "command": "sequence",
        "transport": TRANSPORT_TCPIP,
        "backend": BACKEND_PYVISA_PY,
        "feature_requirements": (("sequence_action", "set"),),
    }
    with pytest.raises(LiveSupportPolicyError, match="transport_pending"):
        ensure_live_scope_supported(
            **arguments, support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT
        )
    scope = ensure_live_scope_supported(
        **arguments, support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION
    )
    feature = find_feature_support(scope, "sequence_action", "set")
    assert feature is not None
    assert feature.validation_status == VALIDATION_STATUS_FEATURE_PENDING


def test_validated_parent_allows_mixed_validated_and_pending_features() -> None:
    base = command_live_support("keysight-e36312a", "sequence")
    scope = base.scopes[0]
    changed_features = tuple(
        replace(
            feature,
            validation_status=VALIDATION_STATUS_FEATURE_PENDING,
            inherits_parent_accepted_evidence=False,
            note="Synthetic future feature validation remains pending.",
        )
        if feature.feature_value == "set"
        else feature
        for feature in scope.feature_scopes
    )
    changed_scope = replace(scope, feature_scopes=changed_features)
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "sequence",
        replace(base, scopes=(changed_scope,) + base.scopes[1:]),
    )

    validate_live_support_metadata(registry)
    for mode in (SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION):
        ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command="sequence",
            transport=scope.transport_scope,
            backend=scope.backend_scope,
            support_policy_mode=mode,
            feature_requirements=(("sequence_action", "apply"),),
            registry=registry,
        )
    with pytest.raises(LiveSupportPolicyError, match="feature_pending"):
        ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command="sequence",
            transport=scope.transport_scope,
            backend=scope.backend_scope,
            support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT,
            feature_requirements=(("sequence_action", "set"),),
            registry=registry,
        )
    ensure_live_scope_supported(
        model_id="keysight-e36312a",
        command="sequence",
        transport=scope.transport_scope,
        backend=scope.backend_scope,
        support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        feature_requirements=(("sequence_action", "set"),),
        registry=registry,
    )
    projected_scope = live_support_policy_metadata(
        "keysight-e36312a", {"sequence"}, registry=registry
    )["commands"]["sequence"]["scopes"][0]
    projected_features = {
        feature["feature_value"]: feature
        for feature in projected_scope["features"]
    }
    assert projected_features["apply"]["product_open"] is True
    assert projected_features["apply"]["pending"] is False
    assert projected_features["set"]["product_open"] is False
    assert projected_features["set"]["pending"] is True


@pytest.mark.parametrize("mode", [SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION])
def test_validated_parent_allows_explicit_unsupported_feature_metadata(mode: str) -> None:
    base = command_live_support("keysight-e36312a", "sequence")
    scope = base.scopes[0]
    changed_scope = replace(
        scope,
        feature_scopes=tuple(
            replace(
                feature,
                validation_status=VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL,
                inherits_parent_accepted_evidence=False,
                note="Synthetic explicit unsupported feature.",
            )
            if feature.feature_value == "set"
            else feature
            for feature in scope.feature_scopes
        ),
    )
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "sequence",
        replace(base, scopes=(changed_scope,) + base.scopes[1:]),
    )

    validate_live_support_metadata(registry)
    with pytest.raises(LiveSupportPolicyError, match="not_supported_by_model"):
        ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command="sequence",
            transport=scope.transport_scope,
            backend=scope.backend_scope,
            support_policy_mode=mode,
            feature_requirements=(("sequence_action", "set"),),
            registry=registry,
        )


def test_transport_pending_parent_rejects_validated_feature_metadata() -> None:
    base = command_live_support("keysight-e36312a", "sequence")
    pending_scope = next(
        scope
        for scope in base.scopes
        if scope.validation_status == VALIDATION_STATUS_TRANSPORT_PENDING
    )
    changed_scope = replace(
        pending_scope,
        feature_scopes=(
            replace(
                pending_scope.feature_scopes[0],
                validation_status=VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
                note="Synthetic invalid validated feature.",
            ),
        )
        + pending_scope.feature_scopes[1:],
    )
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "sequence",
        replace(
            base,
            scopes=tuple(
                changed_scope if scope is pending_scope else scope for scope in base.scopes
            ),
        ),
    )

    with pytest.raises(ValueError, match="feature status is invalid for exact parent scope"):
        validate_live_support_metadata(registry)


def test_transport_pending_parent_allows_explicit_unsupported_feature_metadata() -> None:
    base = command_live_support("keysight-e36312a", "sequence")
    pending_scope = next(
        scope
        for scope in base.scopes
        if scope.validation_status == VALIDATION_STATUS_TRANSPORT_PENDING
    )
    changed_scope = replace(
        pending_scope,
        feature_scopes=tuple(
            replace(
                feature,
                validation_status=VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL,
                note="Synthetic explicit unsupported feature.",
            )
            if feature.feature_value == "set"
            else feature
            for feature in pending_scope.feature_scopes
        ),
    )
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "sequence",
        replace(
            base,
            scopes=tuple(
                changed_scope if scope is pending_scope else scope for scope in base.scopes
            ),
        ),
    )

    validate_live_support_metadata(registry)
    with pytest.raises(LiveSupportPolicyError, match="not_supported_by_model"):
        ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command="sequence",
            transport=pending_scope.transport_scope,
            backend=pending_scope.backend_scope,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            feature_requirements=(("sequence_action", "set"),),
            registry=registry,
        )


@pytest.mark.parametrize("mode", [SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION])
def test_missing_feature_metadata_fails_closed(mode: str) -> None:
    base = command_live_support("keysight-e36312a", "sequence")
    scope = replace(
        base.scopes[0],
        feature_scopes=tuple(
            feature for feature in base.scopes[0].feature_scopes if feature.feature_value != "set"
        ),
    )
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "sequence",
        replace(base, scopes=(scope,)),
    )
    with pytest.raises(LiveSupportPolicyError, match="missing_feature_metadata") as raised:
        ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command="sequence",
            transport=scope.transport_scope,
            backend=scope.backend_scope,
            support_policy_mode=mode,
            feature_requirements=(("sequence_action", "set"),),
            registry=registry,
        )
    assert "feature_kind=sequence_action" in str(raised.value)
    assert "feature_value=set" in str(raised.value)


def test_unknown_feature_status_fails_closed() -> None:
    base = command_live_support("keysight-e36312a", "trigger-step")
    source = base.scopes[0].feature_scopes[0]
    scope = replace(
        base.scopes[0],
        feature_scopes=(replace(source, validation_status="future"),)
        + base.scopes[0].feature_scopes[1:],
    )
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "trigger-step",
        replace(base, scopes=(scope,)),
    )
    with pytest.raises(LiveSupportPolicyError, match="unknown validation status"):
        ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command="trigger-step",
            transport=scope.transport_scope,
            backend=scope.backend_scope,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            feature_requirements=(("trigger_source", source.feature_value),),
            registry=registry,
        )


@pytest.mark.parametrize("mode", [SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION])
def test_not_supported_is_rejected_in_both_modes(mode: str) -> None:
    with pytest.raises(LiveSupportPolicyError, match="not_supported_by_model"):
        ensure_live_scope_supported(
            model_id="keysight-edu36311a",
            command="trigger-list",
            transport=TRANSPORT_USB,
            backend=BACKEND_SYSTEM_VISA,
            support_policy_mode=mode,
        )


@pytest.mark.parametrize(
    ("model_id", "command", "transport", "mode", "match"),
    [
        ("keysight-e36312a", "missing-command", TRANSPORT_USB, SUPPORT_POLICY_MODE_PRODUCT, "missing_or_unknown_metadata"),
        ("keysight-e36312a", "measure", TRANSPORT_GPIB, SUPPORT_POLICY_MODE_PRODUCT, "no exact transport/backend scope"),
        ("keysight-e36312a", "measure", TRANSPORT_USB, "future", "unknown_policy_mode"),
        ("E36312A", "measure", TRANSPORT_USB, SUPPORT_POLICY_MODE_PRODUCT, "missing_or_unknown_metadata"),
        ("keysight-e36103b", "measure", TRANSPORT_USB, SUPPORT_POLICY_MODE_PRODUCT, "missing_or_unknown_metadata"),
        ("keysight-e36232a", "measure", TRANSPORT_USB, SUPPORT_POLICY_MODE_PRODUCT, "missing_or_unknown_metadata"),
        ("keysight-e36313a", "measure", TRANSPORT_USB, SUPPORT_POLICY_MODE_PRODUCT, "missing_or_unknown_metadata"),
        ("keysight-unknown", "measure", TRANSPORT_USB, SUPPORT_POLICY_MODE_PRODUCT, "missing_or_unknown_metadata"),
        ("generic-scpi", "measure", TRANSPORT_USB, SUPPORT_POLICY_MODE_PRODUCT, "missing_or_unknown_metadata"),
    ],
)
def test_evaluator_fails_closed(
    model_id: str, command: str, transport: str, mode: str, match: str
) -> None:
    with pytest.raises(LiveSupportPolicyError, match=match) as raised:
        ensure_live_scope_supported(
            model_id=model_id,
            command=command,
            transport=transport,
            backend=BACKEND_SYSTEM_VISA,
            support_policy_mode=mode,
        )
    message = str(raised.value)
    assert "model_id=" in message
    assert "command=" in message
    assert "transport=" in message
    assert "backend=" in message
    assert "policy_mode=" in message
    assert "status=" in message


def test_unknown_scope_status_fails_closed() -> None:
    base = command_live_support("keysight-e36312a", "measure")
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "measure",
        replace(base, scopes=(replace(base.scopes[0], validation_status="future_status"),)),
    )
    with pytest.raises(LiveSupportPolicyError, match="unknown validation status"):
        ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command="measure",
            transport=base.scopes[0].transport_scope,
            backend=base.scopes[0].backend_scope,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            registry=registry,
        )


@pytest.mark.parametrize(
    "status",
    [
        "future_status",
        VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
        VALIDATION_STATUS_TRANSPORT_PENDING,
        VALIDATION_STATUS_FEATURE_PENDING,
    ],
)
@pytest.mark.parametrize("mode", [SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION])
def test_evaluator_rejects_invalid_top_level_status_with_valid_scope(
    status: str, mode: str
) -> None:
    base = command_live_support("keysight-e36312a", "measure")
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "measure",
        replace(base, validation_status=status),
    )
    with pytest.raises(LiveSupportPolicyError, match="command-policy validation status"):
        ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command="measure",
            transport=base.scopes[0].transport_scope,
            backend=base.scopes[0].backend_scope,
            support_policy_mode=mode,
            registry=registry,
        )


def test_promoted_command_opens_only_its_exact_product_scope() -> None:
    policy = command_live_support("keysight-e36312a", "output-on")
    assert policy.validation_status == VALIDATION_STATUS_PROFILE_VALIDATED
    scope = ensure_live_scope_supported(
        model_id="keysight-e36312a",
        command="output-on",
        transport=TRANSPORT_USB,
        backend=BACKEND_SYSTEM_VISA,
        support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT,
    )
    assert scope.validation_status == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE
    assert scope.admission_kind == "product"
    with pytest.raises(LiveSupportPolicyError, match="no exact transport/backend scope"):
        ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command="output-on",
            transport=TRANSPORT_ASRL,
            backend=BACKEND_SYSTEM_VISA,
            support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT,
        )


@pytest.mark.parametrize(
    ("model", "commands"),
    [
        (
            "keysight-edu36311a",
            {
                "measure-all",
                "trigger-pulse",
                "trigger-status",
                "trigger-step",
                "trigger-list",
                "trigger-fire",
                "trigger-abort",
                "snapshot",
                "restore-from-snapshot",
            },
        ),
        (
            "keysight-e3646a",
            {
                "measure-all",
                "protection-status",
                "protection-set",
                "clear-protection",
                "snapshot",
                "restore-from-snapshot",
                "trigger-pulse",
                "trigger-status",
                "trigger-step",
                "trigger-list",
                "trigger-fire",
                "trigger-abort",
            },
        ),
    ],
)
def test_explicit_model_unsupported_boundaries(model: str, commands: set[str]) -> None:
    matrix = command_live_support_matrix(model)
    for command in commands:
        assert matrix[command].validation_status == VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL
        assert matrix[command].scopes == ()


def test_e3646a_software_workflows_have_only_current_asrl_scope() -> None:
    for command in ("ramp-list", "sequence"):
        policy = command_live_support("keysight-e3646a", command)
        assert {
            (scope.transport_scope, scope.backend_scope, scope.validation_status)
            for scope in policy.scopes
        } == {
            (
                TRANSPORT_ASRL,
                BACKEND_SYSTEM_VISA,
                VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
            )
        }


def test_diagnostic_and_offline_boundaries_are_explicit() -> None:
    assert EXEMPT_LIVE_DIAGNOSTIC_COMMANDS == {
        "list-resources",
        "verify",
        "identify",
        "error",
        "clear",
    }
    assert all(is_live_support_policy_exempt(command) for command in EXEMPT_LIVE_DIAGNOSTIC_COMMANDS)
    assert all(is_live_support_policy_exempt(command) for command in PURE_OFFLINE_COMMANDS)
    assert not is_live_support_policy_exempt("doctor")
    assert not is_live_support_policy_exempt("capabilities")
    assert not is_live_support_policy_exempt("measure")
    assert not is_live_support_policy_exempt("missing-read-command")
    for matrix in (command_live_support_matrix(model) for model in ACTIVE_LIVE_POLICY_MODEL_IDS):
        assert EXEMPT_LIVE_DIAGNOSTIC_COMMANDS.isdisjoint(matrix)
        assert PURE_OFFLINE_COMMANDS.isdisjoint(matrix)


def test_checked_in_registry_passes_validation() -> None:
    validate_live_support_metadata()


def test_checked_in_feature_inventory_matches_current_profiles() -> None:
    for model in ACTIVE_LIVE_POLICY_MODEL_IDS:
        for scope in command_live_support(model, "sequence").scopes:
            assert {
                feature.feature_value for feature in scope.feature_scopes
            } == supported_sequence_actions_for_model_id(model)
            expected_status = (
                VALIDATION_STATUS_FEATURE_PENDING
                if scope.validation_status == VALIDATION_STATUS_TRANSPORT_PENDING
                else VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE
            )
            assert {feature.validation_status for feature in scope.feature_scopes} == {
                expected_status
            }
    assert "trigger-pulse" in supported_sequence_actions_for_model_id("keysight-e36312a")
    assert "trigger-pulse" not in supported_sequence_actions_for_model_id("keysight-edu36311a")
    assert "trigger-pulse" not in supported_sequence_actions_for_model_id("keysight-e3646a")
    for command in ("trigger-step", "trigger-list"):
        for scope in command_live_support("keysight-e36312a", command).scopes:
            assert {feature.feature_value for feature in scope.feature_scopes} == {
                "bus", "immediate"
            }


def test_public_feature_projection_is_additive_and_redacted() -> None:
    metadata = live_support_policy_metadata("keysight-e36312a", {"sequence"})
    scope = metadata["commands"]["sequence"]["scopes"][0]
    assert scope["features"]
    assert {feature["feature_kind"] for feature in scope["features"]} == {
        "sequence_action"
    }
    serialized = json.dumps(metadata)
    assert "evidence" not in serialized
    assert "artifact" not in serialized
    assert ".tmp_tests" not in serialized
    assert "pre-P7" not in serialized


def test_validator_rejects_feature_inventory_drift() -> None:
    base = command_live_support("keysight-e36312a", "sequence")
    scope = replace(base.scopes[0], feature_scopes=base.scopes[0].feature_scopes[:-1])
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "sequence",
        replace(base, scopes=(scope,) + base.scopes[1:]),
    )
    with pytest.raises(ValueError, match="feature inventory drift"):
        validate_live_support_metadata(registry)


@pytest.mark.parametrize(
    ("feature", "match"),
    [
        (
            CommandFeatureSupportScope("future_kind", "set", VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE, note="migration"),
            "unsupported feature kind",
        ),
        (
            CommandFeatureSupportScope("Sequence_Action", "set", VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE, note="migration"),
            "noncanonical feature kind",
        ),
        (
            CommandFeatureSupportScope("sequence_action", " SET ", VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE, note="migration"),
            "noncanonical feature value",
        ),
        (
            CommandFeatureSupportScope("sequence_action", "set", "future", note="migration"),
            "unknown feature validation status",
        ),
        (
            CommandFeatureSupportScope("sequence_action", "set", VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE),
            "validated feature lacks explicit parent-evidence inheritance",
        ),
    ],
)
def test_validator_rejects_invalid_feature_metadata(
    feature: CommandFeatureSupportScope, match: str
) -> None:
    base = command_live_support("keysight-e36312a", "sequence")
    scope = replace(base.scopes[0], feature_scopes=(feature,) + base.scopes[0].feature_scopes[1:])
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "sequence",
        replace(base, scopes=(scope,) + base.scopes[1:]),
    )
    with pytest.raises(ValueError, match=match):
        validate_live_support_metadata(registry)


def test_validator_rejects_duplicate_feature_scope_and_wrong_command_kind() -> None:
    sequence = command_live_support("keysight-e36312a", "sequence")
    duplicate_scope = replace(
        sequence.scopes[0],
        feature_scopes=sequence.scopes[0].feature_scopes
        + (sequence.scopes[0].feature_scopes[0],),
    )
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "sequence",
        replace(sequence, scopes=(duplicate_scope,) + sequence.scopes[1:]),
    )
    with pytest.raises(ValueError, match="duplicate feature scope"):
        validate_live_support_metadata(registry)

    measure = command_live_support("keysight-e36312a", "measure")
    wrong_scope = replace(
        measure.scopes[0],
        feature_scopes=(sequence.scopes[0].feature_scopes[0],),
    )
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "measure",
        replace(measure, scopes=(wrong_scope,) + measure.scopes[1:]),
    )
    with pytest.raises(ValueError, match="unexpected feature scope"):
        validate_live_support_metadata(registry)


def test_validator_rejects_duplicate_exact_scope() -> None:
    base = command_live_support("keysight-e36312a", "measure")
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "measure",
        replace(base, scopes=base.scopes + (base.scopes[0],)),
    )
    with pytest.raises(ValueError, match="duplicate exact scope"):
        validate_live_support_metadata(registry)


@pytest.mark.parametrize(
    ("replacement", "match"),
    [
        (
            replace(command_live_support("keysight-e36312a", "measure"), validation_status="future"),
            "invalid command-policy validation status",
        ),
        (
            replace(
                command_live_support("keysight-e36312a", "measure"),
                validation_status=VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
            ),
            "invalid command-policy validation status",
        ),
        (
            replace(
                command_live_support("keysight-e36312a", "measure"),
                validation_status=VALIDATION_STATUS_TRANSPORT_PENDING,
            ),
            "invalid command-policy validation status",
        ),
        (
            replace(
                command_live_support("keysight-e36312a", "measure"),
                validation_status=VALIDATION_STATUS_FEATURE_PENDING,
            ),
            "invalid command-policy validation status",
        ),
        (
            replace(
                command_live_support("keysight-e36312a", "measure"),
                scopes=(replace(command_live_support("keysight-e36312a", "measure").scopes[0], validation_status="future"),),
            ),
            "unknown scope validation status",
        ),
        (
            replace(
                command_live_support("keysight-e36312a", "measure"),
                scopes=(replace(command_live_support("keysight-e36312a", "measure").scopes[0], accepted_evidence_ids=()),),
            ),
            "validated scope lacks accepted evidence",
        ),
        (
            replace(
                command_live_support("keysight-e36312a", "measure"),
                scopes=(replace(command_live_support("keysight-e36312a", "measure").scopes[0], accepted_evidence_ids=("missing-evidence-id",)),),
            ),
            "missing evidence registry entry",
        ),
        (
            replace(
                command_live_support("keysight-e36312a", "measure"),
                scopes=(
                    CommandLiveSupportScope(
                        VALIDATION_STATUS_TRANSPORT_PENDING,
                        TRANSPORT_GPIB,
                        BACKEND_SYSTEM_VISA,
                    ),
                ),
            ),
            "pending scope lacks note",
        ),
        (
            replace(
                command_live_support("keysight-edu36311a", "trigger-list"),
                scopes=(command_live_support("keysight-e36312a", "measure").scopes[0],),
            ),
            "unsupported command has live scopes",
        ),
    ],
)
def test_validator_rejects_invalid_command_metadata(
    replacement: CommandSupportPolicy, match: str
) -> None:
    model = "keysight-edu36311a" if replacement.command == "trigger-list" else "keysight-e36312a"
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY, model, replacement.command, replacement
    )
    with pytest.raises(ValueError, match=match):
        validate_live_support_metadata(registry)


def test_validator_rejects_de_scoped_model() -> None:
    registry = LIVE_SUPPORT_POLICY_REGISTRY + (
        ModelSupportPolicy("keysight-e36103b", tuple(command_live_support_matrix("keysight-e36312a").values())),
    )
    with pytest.raises(ValueError, match="de-scoped model"):
        validate_live_support_metadata(registry)


@pytest.mark.parametrize("model", ["e36312a", " E36312A", "E36312A "])
def test_validator_rejects_noncanonical_model_metadata(model: str) -> None:
    registry = (replace(LIVE_SUPPORT_POLICY_REGISTRY[0], model_id=model),) + LIVE_SUPPORT_POLICY_REGISTRY[1:]
    with pytest.raises(ValueError, match="noncanonical model policy"):
        validate_live_support_metadata(registry)


@pytest.mark.parametrize("command", ["Measure", " measure", "measure "])
def test_validator_rejects_noncanonical_command_metadata(command: str) -> None:
    base = command_live_support("keysight-e36312a", "measure")
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "measure",
        replace(base, command=command),
    )
    with pytest.raises(ValueError, match="noncanonical command policy"):
        validate_live_support_metadata(registry)


def test_validator_rejects_unknown_exact_transport() -> None:
    base = command_live_support("keysight-e36312a", "measure")
    registry = _replace_command(
        LIVE_SUPPORT_POLICY_REGISTRY,
        "keysight-e36312a",
        "measure",
        replace(base, scopes=(replace(base.scopes[0], transport_scope=TRANSPORT_UNKNOWN),)),
    )
    with pytest.raises(ValueError, match="exact live scope cannot use unknown transport"):
        validate_live_support_metadata(registry)


def test_validator_rejects_missing_and_unexpected_command_inventory_entries() -> None:
    inventory = set(command_live_support_matrix("keysight-e36312a"))
    with pytest.raises(ValueError, match="policy-governed commands missing"):
        validate_live_support_metadata(command_inventory=inventory | {"future-command"})
    with pytest.raises(ValueError, match="outside current inventory"):
        validate_live_support_metadata(command_inventory=inventory - {"measure"})


def test_public_model_projection_is_json_safe_and_omits_private_evidence() -> None:
    metadata = live_support_policy_metadata(
        "keysight-e36312a", {"set", "clear", "snapshot-diff", "future-command"}
    )

    assert metadata["schema_version"] == 2
    assert metadata["model_id"] == "keysight-e36312a"
    assert "model" not in metadata
    assert metadata["vendor_id"] == "keysight"
    assert metadata["model_name"] == "E36312A"
    assert metadata["display_name"] == "Keysight E36312A"
    assert metadata["live_capable"] is True
    set_support = metadata["commands"]["set"]
    assert set_support["profile_validation_status"] == VALIDATION_STATUS_PROFILE_VALIDATED
    assert set_support["profile_supported"] is True
    assert set_support["policy_exempt"] is False
    assert {
        (scope["transport_scope"], scope["backend_scope"], scope["validation_status"])
        for scope in set_support["scopes"]
    } == {
        (TRANSPORT_USB, BACKEND_SYSTEM_VISA, VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE),
        (TRANSPORT_TCPIP, BACKEND_SYSTEM_VISA, VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE),
        (TRANSPORT_TCPIP, BACKEND_PYVISA_PY, VALIDATION_STATUS_TRANSPORT_PENDING),
    }
    assert metadata["commands"]["clear"]["policy_exempt"] is True
    assert metadata["commands"]["clear"]["offline_only"] is False
    assert metadata["commands"]["clear"]["scopes"] == []
    offline = metadata["commands"]["snapshot-diff"]
    assert offline["policy_exempt"] is False
    assert offline["offline_only"] is True
    assert offline["scopes"] == []
    assert "Offline utility" in offline["support_reason"]
    assert metadata["commands"]["future-command"]["metadata_available"] is False
    assert metadata["commands"]["future-command"]["profile_supported"] is False

    serialized = json.dumps(metadata)
    assert ".tmp_tests" not in serialized
    assert "artifact" not in serialized
    assert "evidence" not in serialized
    assert "serial" not in serialized


def test_unevaluated_projection_uses_core_owned_safe_classification() -> None:
    metadata = unevaluated_live_support_policy_metadata(
        commands={"set"},
        reason="No resolved physical identity.",
    )

    assert metadata["schema_version"] == 2
    assert metadata["evaluated"] is False
    assert metadata["model_id"] is None
    assert metadata["live_capable"] is False
    assert metadata["fallback_only"] is True
    for command in EXEMPT_LIVE_DIAGNOSTIC_COMMANDS:
        entry = metadata["commands"][command]
        assert entry["policy_exempt"] is True
        assert entry["offline_only"] is False
        assert entry["scopes"] == []
    for command in PURE_OFFLINE_COMMANDS:
        entry = metadata["commands"][command]
        assert entry["policy_exempt"] is False
        assert entry["offline_only"] is True
        assert entry["scopes"] == []
    assert metadata["commands"]["set"]["policy_exempt"] is False
    assert metadata["commands"]["set"]["offline_only"] is False
    assert metadata["commands"]["set"]["scopes"] == []
    serialized = json.dumps(metadata)
    for forbidden in ("evidence", "artifact", ".tmp_tests", "report_sha256"):
        assert forbidden not in serialized


def test_public_exact_projection_distinguishes_open_pending_and_missing_scopes() -> None:
    commands = {"set", "output-on", "clear", "snapshot-diff"}
    usb = exact_live_support_metadata(
        model_id="keysight-e36312a",
        resource="USB0::FAKE::INSTR",
        backend=None,
        commands=commands,
    )
    system_tcpip = exact_live_support_metadata(
        model_id="keysight-e36312a",
        resource="TCPIP0::192.0.2.1::INSTR",
        backend=None,
        commands=commands,
    )
    pending = exact_live_support_metadata(
        model_id="keysight-e36312a",
        resource="TCPIP0::192.0.2.1::INSTR",
        backend="@py",
        commands=commands,
    )

    assert usb["policy_mode"] == SUPPORT_POLICY_MODE_PRODUCT
    assert usb["commands"]["set"]["product_open"] is True
    assert system_tcpip["commands"]["set"]["product_open"] is True
    assert pending["commands"]["set"] == {
        "profile_validation_status": VALIDATION_STATUS_PROFILE_VALIDATED,
        "profile_supported": True,
        "metadata_available": True,
        "policy_exempt": False,
        "offline_only": False,
        "disabled_reason": "Pending live validation: TCPIP / pyvisa-py.",
        "support_reason": "Pending live validation: TCPIP / pyvisa-py.",
        "exact_scope_validation_status": VALIDATION_STATUS_TRANSPORT_PENDING,
        "product_open": False,
    }
    assert pending["commands"]["output-on"]["exact_scope_validation_status"] == VALIDATION_STATUS_TRANSPORT_PENDING
    assert pending["commands"]["output-on"]["product_open"] is False
    assert pending["commands"]["output-on"]["disabled_reason"] == "Pending live validation: TCPIP / pyvisa-py."
    assert pending["commands"]["clear"]["policy_exempt"] is True
    assert pending["commands"]["clear"]["offline_only"] is False
    assert pending["commands"]["clear"]["product_open"] is True
    assert pending["commands"]["clear"]["exact_scope_validation_status"] is None
    offline = pending["commands"]["snapshot-diff"]
    assert offline["policy_exempt"] is False
    assert offline["offline_only"] is True
    assert offline["product_open"] is False
    assert offline["exact_scope_validation_status"] is None
    assert offline["support_reason"] == "Offline utility; live exact scope is not applicable."


def test_public_projection_preserves_model_and_generic_boundaries() -> None:
    edu = live_support_policy_metadata("keysight-edu36311a", {"trigger-list"})
    e3646a_asrl = exact_live_support_metadata(
        model_id="keysight-e3646a",
        resource="ASRL7::INSTR",
        backend=None,
        commands={"set"},
    )
    e3646a_usb = exact_live_support_metadata(
        model_id="keysight-e3646a",
        resource="USB0::FAKE::INSTR",
        backend=None,
        commands={"set"},
    )
    assert edu["commands"]["trigger-list"]["profile_validation_status"] == VALIDATION_STATUS_NOT_SUPPORTED_BY_MODEL
    assert edu["commands"]["trigger-list"]["profile_supported"] is False
    assert edu["commands"]["trigger-list"]["scopes"] == []
    assert e3646a_asrl["commands"]["set"]["product_open"] is True
    assert e3646a_usb["commands"]["set"]["product_open"] is False
    assert e3646a_usb["commands"]["set"]["exact_scope_validation_status"] is None
    with pytest.raises(LiveSupportPolicyError):
        exact_live_support_metadata(
            model_id="GENERIC", resource="USB0::FAKE::INSTR", backend=None
        )
    with pytest.raises(LiveSupportPolicyError):
        live_support_policy_metadata("keysight-e36103b", {"set"})
    with pytest.raises(LiveSupportPolicyError):
        live_support_policy_metadata("keysight-unknown", {"set"})
def test_internal_validation_candidate_inventory_is_exact_and_immutable() -> None:
    inventory = internal_validation_candidate_inventory()

    assert dict(inventory["gw-instek-psm-2010"]) == {
        "commands": tuple(
            sorted(
                {
                    "validate-readonly", "log", "doctor", "set", "output-on",
                    "cycle-output", "apply", "ramp", "smoke-output", "ramp-list",
                    "sequence", "protection-status", "protection-set",
                    "clear-protection", "snapshot", "restore-from-snapshot",
                }
            )
        ),
        "connections": ((TRANSPORT_ASRL, BACKEND_SYSTEM_VISA),),
    }
    with pytest.raises(TypeError):
        inventory["future-model"] = {}  # type: ignore[index]


def test_validation_mode_uses_promoted_product_scope_without_candidate_bypass() -> None:
    for mode in (SUPPORT_POLICY_MODE_PRODUCT, SUPPORT_POLICY_MODE_VALIDATION):
        scope = ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command="output-on",
            transport="USB0::fixture::INSTR",
            backend=None,
            support_policy_mode=mode,
        )
        assert scope.admission_kind == "product"

    with pytest.raises(LiveSupportPolicyError):
        ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command="output-on",
            transport="ASRL1::INSTR",
            backend=None,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        )

    with pytest.raises(LiveSupportPolicyError):
        ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command="output-on",
            transport="USB0::fixture::INSTR",
            backend="@py",
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        )

    for command in ("trigger-fire", "trigger-pulse"):
        scope = ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command=command,
            transport="USB0::fixture::INSTR",
            backend=None,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        )
        assert scope.admission_kind == "product"
        lan_scope = ensure_live_scope_supported(
            model_id="keysight-e36312a",
            command=command,
            transport="TCPIP0::fixture::INSTR",
            backend=None,
            support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
        )
        assert lan_scope.admission_kind == "product"
        for transport in ("USB0::fixture::INSTR", "TCPIP0::fixture::INSTR"):
            product_scope = ensure_live_scope_supported(
                model_id="keysight-e36312a",
                command=command,
                transport=transport,
                backend=None,
                support_policy_mode=SUPPORT_POLICY_MODE_PRODUCT,
            )
            assert product_scope.admission_kind == "product"
        with pytest.raises(LiveSupportPolicyError):
            ensure_live_scope_supported(
                model_id="keysight-e36312a",
                command=command,
                transport="ASRL1::INSTR",
                backend=None,
                support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            )
        with pytest.raises(LiveSupportPolicyError):
            ensure_live_scope_supported(
                model_id="keysight-edu36311a",
                command=command,
                transport="USB0::fixture::INSTR",
                backend=None,
                support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            )
        with pytest.raises(LiveSupportPolicyError):
            ensure_live_scope_supported(
                model_id="keysight-e36312a",
                command=command,
                transport="USB0::fixture::INSTR",
                backend="@py",
                support_policy_mode=SUPPORT_POLICY_MODE_VALIDATION,
            )
