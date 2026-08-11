import json
import re
from dataclasses import fields, replace
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType

import pytest

from powers_tool_core.support_evidence import (
    EVIDENCE_KIND_FULL_SUITE,
    EVIDENCE_KIND_VERIFIED_FULL_SUITE,
    SOURCE_AVAILABILITY_HISTORICAL_REFERENCE_ONLY,
    SOURCE_AVAILABILITY_VERIFIED_LOCAL,
    SUPPORT_EVIDENCE_BY_ID,
    SUPPORT_EVIDENCE_MANIFEST,
    SUPPORT_EVIDENCE_RECORDS,
    validate_support_evidence_manifest,
    validate_support_evidence_metadata,
)
from powers_tool_core.support_policy import (
    BACKEND_PYVISA_PY,
    BACKEND_SYSTEM_VISA,
    LIVE_SUPPORT_POLICY_REGISTRY,
    VALIDATION_STATUS_FEATURE_PENDING,
    VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE,
    VALIDATION_STATUS_TRANSPORT_PENDING,
    exact_live_support_metadata,
    validate_live_support_metadata,
)


EXPECTED_EVIDENCE = {
    "keysight-e36312a-usb-system-visa-20260709-full": (
        "keysight-e36312a",
        "usb",
        ".tmp_tests/live_cli_check/20260709_153201_E36312A_USB_full",
    ),
    "keysight-e36312a-tcpip-system-visa-20260709-full": (
        "keysight-e36312a",
        "tcpip",
        ".tmp_tests/live_cli_check/20260709_201420_E36312A_LAN_full",
    ),
    "keysight-edu36311a-usb-system-visa-20260709-full": (
        "keysight-edu36311a",
        "usb",
        ".tmp_tests/live_cli_check/20260709_151534_EDU36311A_USB_full",
    ),
    "keysight-edu36311a-tcpip-system-visa-20260709-full": (
        "keysight-edu36311a",
        "tcpip",
        ".tmp_tests/live_cli_check/20260709_200530_EDU36311A_LAN_full",
    ),
    "keysight-e3646a-asrl-system-visa-20260709-full": (
        "keysight-e3646a",
        "asrl",
        ".tmp_tests/live_cli_check/20260709_151205_E3646A_ASRL_full",
    ),
}

EXPECTED_VERIFIED_EVIDENCE = {
    "keysight-e36312a-usb-system-visa-20260717-full": (
        "keysight-e36312a", "usb",
        ".tmp_tests/live_cli_check/20260717_111636_keysight-e36312a_USB_full/shareable",
        "784087da966a141aab0c859580f0e85b5856f7b3cf319d889790b6f1751b6048",
    ),
    "keysight-e36312a-tcpip-system-visa-20260717-full": (
        "keysight-e36312a", "tcpip",
        ".tmp_tests/live_cli_check/20260717_110602_keysight-e36312a_LAN_full/shareable",
        "17c4f2d5c5a7e618f0d216cfab1c38b769b123a1fc157b4a0ee9e3acac5c4927",
    ),
    "keysight-edu36311a-usb-system-visa-20260717-full": (
        "keysight-edu36311a", "usb",
        ".tmp_tests/live_cli_check/20260717_104734_keysight-edu36311a_USB_full/shareable",
        "b613f9eb40cb08df805ed00cb6668c79ef41b5225526874e78daf1a3f5d77b66",
    ),
    "keysight-edu36311a-tcpip-system-visa-20260717-full": (
        "keysight-edu36311a", "tcpip",
        ".tmp_tests/live_cli_check/20260717_104008_keysight-edu36311a_LAN_full/shareable",
        "591f4415ebcc5f63d4f42b4a57a81ca9be3586854a9f1fe453c59802591e9ef9",
    ),
    "keysight-e3646a-asrl-system-visa-20260717-full": (
        "keysight-e3646a", "asrl",
        ".tmp_tests/live_cli_check/20260717_112310_keysight-e3646a_ASRL_full/shareable",
        "e9df449f532f6759161eeb1cfcf643c700d937ffc3078d8515280a267c3ae9e3",
    ),
}
NEW_E3646A_LOG_EVIDENCE_ID = "keysight-e3646a-asrl-system-visa-20260807-full"
PSM2010_EVIDENCE_ID = "gw-instek-psm-2010-asrl-system-visa-20260811-full"
PSM2010_VALIDATED_COMMANDS = frozenset(
    {
        "measure",
        "output-state",
        "readback",
        "read-status",
        "capabilities",
        "output-off",
        "safe-off",
    }
)

EXPECTED_COMMAND_COUNTS = {
    "keysight-e36312a": 23,
    "keysight-edu36311a": 18,
    "keysight-e3646a": 14,
}

EXPECTED_VERIFIED_COMMANDS = {
    "keysight-e36312a": frozenset(
        {
            "apply", "capabilities", "clear-protection", "cycle-output", "doctor",
            "log", "measure", "measure-all", "output-off", "output-on", "output-state",
            "protection-set", "protection-status", "ramp", "ramp-list", "read-status",
            "readback", "restore-from-snapshot", "safe-off", "sequence", "set",
            "smoke-output", "snapshot", "trigger-abort", "trigger-fire", "trigger-list",
            "trigger-pulse", "trigger-status", "trigger-step", "validate-readonly",
        }
    ),
    "keysight-edu36311a": frozenset(
        {
            "apply", "capabilities", "clear-protection", "cycle-output", "doctor", "log",
            "measure", "output-off", "output-on", "output-state", "protection-set",
            "protection-status", "ramp", "ramp-list", "read-status", "readback", "safe-off",
            "sequence", "set", "smoke-output", "validate-readonly",
        }
    ),
    "keysight-e3646a": frozenset(
        {
            "apply", "capabilities", "cycle-output", "doctor", "measure", "output-off",
            "output-on", "output-state", "ramp", "ramp-list", "read-status", "readback",
            "safe-off", "sequence", "set", "smoke-output",
        }
    ),
}

EXPECTED_PROMOTED_COMMANDS = {
    "keysight-e36312a": frozenset(
        {"output-on", "log", "doctor", "measure-all", "restore-from-snapshot", "trigger-fire", "trigger-pulse"}
    ),
    "keysight-edu36311a": frozenset({"output-on", "log", "doctor"}),
    "keysight-e3646a": frozenset({"output-on", "doctor", "log"}),
    "gw-instek-psm-2010": PSM2010_VALIDATED_COMMANDS,
}

EXPECTED_FEATURES_BY_MODEL = {
    "keysight-e36312a": {
        "sequence": frozenset(
            ("sequence_action", value)
            for value in {
                "apply", "cycle-output", "measure", "output-off", "output-on",
                "output-state", "readback", "safe-off", "set", "trigger-pulse",
            }
        ),
        "trigger-step": frozenset(
            {("trigger_source", "bus"), ("trigger_source", "immediate")}
        ),
        "trigger-list": frozenset(
            {("trigger_source", "bus"), ("trigger_source", "immediate")}
        ),
    },
    "keysight-edu36311a": {
        "sequence": frozenset(
            ("sequence_action", value)
            for value in {
                "apply", "cycle-output", "measure", "output-off", "output-on",
                "output-state", "readback", "safe-off", "set",
            }
        ),
    },
    "keysight-e3646a": {
        "sequence": frozenset(
            ("sequence_action", value)
            for value in {
                "apply", "cycle-output", "measure", "output-off", "output-on",
                "output-state", "readback", "safe-off", "set",
            }
        ),
    },
}


def test_production_evidence_manifest_contract() -> None:
    assert SUPPORT_EVIDENCE_MANIFEST.schema_version == 2
    assert type(SUPPORT_EVIDENCE_MANIFEST.schema_version) is int
    assert SUPPORT_EVIDENCE_MANIFEST.promotes_support is False
    assert isinstance(SUPPORT_EVIDENCE_MANIFEST.records, tuple)
    assert SUPPORT_EVIDENCE_MANIFEST.records == SUPPORT_EVIDENCE_RECORDS

    validate_support_evidence_manifest(SUPPORT_EVIDENCE_MANIFEST)


@pytest.mark.parametrize("schema_version", [1, 3, "2", 2.0, True, False])
def test_evidence_manifest_rejects_wrong_schema_versions(schema_version: object) -> None:
    malformed = replace(SUPPORT_EVIDENCE_MANIFEST, schema_version=schema_version)

    with pytest.raises(ValueError, match="unsupported evidence manifest schema version"):
        validate_support_evidence_manifest(malformed)


@pytest.mark.parametrize("promotes_support", [True, 0, None])
def test_evidence_manifest_rejects_promotion(promotes_support: object) -> None:
    malformed = replace(SUPPORT_EVIDENCE_MANIFEST, promotes_support=promotes_support)

    with pytest.raises(ValueError, match="evidence manifest must be explicitly non-promoting"):
        validate_support_evidence_manifest(malformed)


@pytest.mark.parametrize("records", [(), list(SUPPORT_EVIDENCE_RECORDS)])
def test_evidence_manifest_requires_immutable_non_empty_records(records: object) -> None:
    malformed = replace(SUPPORT_EVIDENCE_MANIFEST, records=records)

    with pytest.raises(
        ValueError,
        match="evidence manifest records must be an immutable non-empty tuple",
    ):
        validate_support_evidence_manifest(malformed)


def test_evidence_manifest_and_registry_cannot_drift() -> None:
    manifest_ids = {
        record.evidence_id
        for record in SUPPORT_EVIDENCE_MANIFEST.records
    }

    assert set(SUPPORT_EVIDENCE_BY_ID) == manifest_ids
    for record in SUPPORT_EVIDENCE_MANIFEST.records:
        assert SUPPORT_EVIDENCE_BY_ID[record.evidence_id] is record


def test_registered_evidence_identities_are_exact() -> None:
    assert len(SUPPORT_EVIDENCE_RECORDS) == 12
    assert len(SUPPORT_EVIDENCE_BY_ID) == 12
    assert set(SUPPORT_EVIDENCE_BY_ID) == (
        set(EXPECTED_EVIDENCE)
        | set(EXPECTED_VERIFIED_EVIDENCE)
        | {NEW_E3646A_LOG_EVIDENCE_ID, PSM2010_EVIDENCE_ID}
    )
    for evidence_id, (model_id, transport, artifact_directory) in EXPECTED_EVIDENCE.items():
        record = SUPPORT_EVIDENCE_BY_ID[evidence_id]
        assert (record.model_id, record.transport_scope, record.backend_scope) == (
            model_id,
            transport,
            "system_visa",
        )
        assert record.artifact_directory == artifact_directory
        assert record.report_path == f"{artifact_directory}/report.json"
        assert record.summary_path == f"{artifact_directory}/summary.md"
        assert record.source_availability == SOURCE_AVAILABILITY_HISTORICAL_REFERENCE_ONLY
        assert record.evidence_kind == EVIDENCE_KIND_FULL_SUITE
        assert record.evidence_date == "2026-07-09"
        assert record.report_sha256 is None
        assert record.artifact_schema_version == "1.0"
    with pytest.raises(TypeError):
        SUPPORT_EVIDENCE_BY_ID["new-evidence"] = SUPPORT_EVIDENCE_RECORDS[0]  # type: ignore[index]


def test_historical_evidence_inventories_are_frozen_and_exact() -> None:
    for evidence_id in EXPECTED_EVIDENCE:
        record = SUPPORT_EVIDENCE_BY_ID[evidence_id]
        assert len(record.accepted_commands) == EXPECTED_COMMAND_COUNTS[record.model_id]
        assert record.accepted_features_by_command == EXPECTED_FEATURES_BY_MODEL[record.model_id]
        assert isinstance(record.accepted_features_by_command, MappingProxyType)
        with pytest.raises(AttributeError):
            record.accepted_commands.add("future-command")  # type: ignore[attr-defined]
        with pytest.raises(TypeError):
            record.accepted_features_by_command["sequence"] = frozenset()  # type: ignore[index]


def test_verified_evidence_records_are_exact_and_immutable() -> None:
    sequence_features = frozenset(
        ("sequence_action", value)
        for value in {"output-off", "output-on", "output-state", "readback", "set"}
    )
    for evidence_id, (model_id, transport, artifact_directory, sha256) in EXPECTED_VERIFIED_EVIDENCE.items():
        record = SUPPORT_EVIDENCE_BY_ID[evidence_id]
        assert (record.model_id, record.transport_scope, record.backend_scope) == (
            model_id, transport, "system_visa"
        )
        assert record.evidence_kind == EVIDENCE_KIND_VERIFIED_FULL_SUITE
        assert record.evidence_date == "2026-07-17"
        assert record.artifact_directory == artifact_directory
        assert record.report_path == f"{artifact_directory}/report.json"
        assert record.summary_path == f"{artifact_directory}/summary.md"
        assert record.artifact_schema_version == "2.0"
        assert record.report_sha256 == sha256
        assert re.fullmatch(r"[0-9a-f]{64}", record.report_sha256)
        assert record.source_availability == SOURCE_AVAILABILITY_VERIFIED_LOCAL
        assert record.legacy_model_name is None
        assert record.legacy_backend_interpretation is None
        assert record.migration_note is None
        assert record.accepted_commands == EXPECTED_VERIFIED_COMMANDS[model_id]
        assert record.accepted_features_by_command["sequence"] == sequence_features
        if model_id == "keysight-e36312a":
            assert record.accepted_features_by_command["trigger-step"] == frozenset(
                {("trigger_source", "bus")}
            )
            assert record.accepted_features_by_command["trigger-list"] == frozenset(
                {("trigger_source", "bus")}
            )
        assert isinstance(record.accepted_features_by_command, MappingProxyType)


def test_new_e3646a_log_evidence_is_exact_and_historical_record_is_unchanged() -> None:
    record = SUPPORT_EVIDENCE_BY_ID[NEW_E3646A_LOG_EVIDENCE_ID]
    assert (record.model_id, record.transport_scope, record.backend_scope) == (
        "keysight-e3646a",
        "asrl",
        "system_visa",
    )
    assert record.evidence_date == "2026-08-07"
    assert record.evidence_kind == EVIDENCE_KIND_VERIFIED_FULL_SUITE
    assert record.artifact_directory == (
        ".tmp_tests/live_cli_check/"
        "20260807_154408_keysight-e3646a_ASRL_full/shareable"
    )
    assert record.report_path == f"{record.artifact_directory}/report.json"
    assert record.summary_path == f"{record.artifact_directory}/summary.md"
    assert record.artifact_schema_version == "2.0"
    assert record.report_sha256 == (
        "ea75f78c8fb8c95fdbd91fed87becb3e41a786220440b3a9c48d0815ae249c2d"
    )
    assert re.fullmatch(r"[0-9a-f]{64}", record.report_sha256)
    assert record.source_availability == SOURCE_AVAILABILITY_VERIFIED_LOCAL
    assert record.migration_note is None
    assert record.accepted_commands == frozenset({"log"})
    assert record.accepted_features_by_command == {}
    assert isinstance(record.accepted_features_by_command, MappingProxyType)

    historical = SUPPORT_EVIDENCE_BY_ID[
        "keysight-e3646a-asrl-system-visa-20260717-full"
    ]
    assert historical.evidence_date == "2026-07-17"
    assert "log" not in historical.accepted_commands


def test_psm2010_verified_evidence_is_exact_and_immutable() -> None:
    record = SUPPORT_EVIDENCE_BY_ID[PSM2010_EVIDENCE_ID]
    assert (record.model_id, record.transport_scope, record.backend_scope) == (
        "gw-instek-psm-2010",
        "asrl",
        "system_visa",
    )
    assert record.evidence_date == "2026-08-11"
    assert record.evidence_kind == EVIDENCE_KIND_VERIFIED_FULL_SUITE
    assert record.artifact_directory == (
        ".tmp_tests/live_cli_check/"
        "20260811_182827_gw-instek-psm-2010_ASRL_full/shareable"
    )
    assert record.report_path == f"{record.artifact_directory}/report.json"
    assert record.summary_path == f"{record.artifact_directory}/summary.md"
    assert record.artifact_schema_version == "2.0"
    assert record.report_sha256 == (
        "7621936dd5ffc46cdc826370f5a3cb1c65973377e036cab96f79ab0a3fb413a8"
    )
    assert record.source_availability == SOURCE_AVAILABILITY_VERIFIED_LOCAL
    assert record.accepted_commands == PSM2010_VALIDATED_COMMANDS
    assert record.accepted_features_by_command == {}
    assert isinstance(record.accepted_features_by_command, MappingProxyType)


def test_evidence_registry_alias_is_rejected() -> None:
    record = SUPPORT_EVIDENCE_RECORDS[0]
    malformed_registry = {
        key: value
        for key, value in SUPPORT_EVIDENCE_BY_ID.items()
        if key != record.evidence_id
    }
    malformed_registry["incorrect-alias"] = record

    with pytest.raises(ValueError, match="evidence registry key mismatch"):
        validate_live_support_metadata(evidence_registry=malformed_registry)


def test_accepted_evidence_reference_identity_mismatch_is_rejected() -> None:
    reference_id = "keysight-e36312a-usb-system-visa-20260709-full"
    mismatched = replace(
        SUPPORT_EVIDENCE_BY_ID[reference_id],
        evidence_id="keysight-e36312a-usb-system-visa-20260709-alternate",
    )
    malformed_registry = {**SUPPORT_EVIDENCE_BY_ID, reference_id: mismatched}

    with pytest.raises(ValueError, match="evidence registry key mismatch"):
        validate_live_support_metadata(evidence_registry=malformed_registry)


def test_candidate_basis_evidence_reference_identity_mismatch_is_rejected() -> None:
    reference_id = "keysight-e36312a-tcpip-system-visa-20260709-full"
    mismatched = replace(
        SUPPORT_EVIDENCE_BY_ID[reference_id],
        evidence_id="keysight-e36312a-tcpip-system-visa-20260709-alternate",
    )
    malformed_registry = {**SUPPORT_EVIDENCE_BY_ID, reference_id: mismatched}

    with pytest.raises(ValueError, match="evidence registry key mismatch"):
        validate_live_support_metadata(evidence_registry=malformed_registry)


def test_production_evidence_registry_keys_are_exact() -> None:
    for evidence_id, record in SUPPORT_EVIDENCE_BY_ID.items():
        assert evidence_id == record.evidence_id

    validate_support_evidence_metadata()
    validate_live_support_metadata()


def test_unrecorded_command_cannot_inherit_accepted_evidence() -> None:
    evidence = SUPPORT_EVIDENCE_RECORDS[0]
    mismatched = replace(
        evidence,
        accepted_commands=evidence.accepted_commands - {"measure"},
    )
    evidence_registry = {**SUPPORT_EVIDENCE_BY_ID, evidence.evidence_id: mismatched}
    with pytest.raises(ValueError, match="evidence command mismatch"):
        validate_live_support_metadata(evidence_registry=evidence_registry)


def test_unrecorded_feature_cannot_inherit_accepted_evidence() -> None:
    evidence = SUPPORT_EVIDENCE_RECORDS[0]
    features = dict(evidence.accepted_features_by_command)
    features["sequence"] = features["sequence"] - {
        ("sequence_action", "apply")
    }
    mismatched = replace(
        evidence,
        accepted_features_by_command=MappingProxyType(features),
    )
    evidence_registry = {**SUPPORT_EVIDENCE_BY_ID, evidence.evidence_id: mismatched}
    with pytest.raises(ValueError, match="evidence feature mismatch"):
        validate_live_support_metadata(evidence_registry=evidence_registry)


def test_evidence_paths_are_relative_and_metadata_is_non_sensitive() -> None:
    forbidden = re.compile(
        r"::|\b(?:10\.|192\.168\.|169\.254\.|172\.(?:1[6-9]|2\d|3[01])\.)"
    )
    for record in SUPPORT_EVIDENCE_RECORDS:
        for path_value in (record.artifact_directory, record.report_path, record.summary_path):
            assert not PurePosixPath(path_value).is_absolute()
            assert not PureWindowsPath(path_value).is_absolute()
            assert ".." not in PurePosixPath(path_value).parts
        for field in fields(record):
            value = getattr(record, field.name)
            if isinstance(value, str):
                assert forbidden.search(value) is None


def test_availability_and_checksum_combinations_fail_closed() -> None:
    base = SUPPORT_EVIDENCE_RECORDS[0]
    verified = SUPPORT_EVIDENCE_BY_ID[
        "keysight-e36312a-usb-system-visa-20260717-full"
    ]
    validate_support_evidence_metadata((verified,))

    with pytest.raises(ValueError, match="requires SHA-256"):
        validate_support_evidence_metadata((replace(verified, report_sha256=None),))
    for bad_hash in (123, "ABC", "g" * 64, "a" * 63):
        with pytest.raises(ValueError, match="requires SHA-256"):
            validate_support_evidence_metadata((replace(verified, report_sha256=bad_hash),))
    with pytest.raises(ValueError, match="cannot claim a checksum"):
        validate_support_evidence_metadata((replace(base, report_sha256="a" * 64),))
    with pytest.raises(ValueError, match="invalid evidence source availability"):
        validate_support_evidence_metadata((replace(base, source_availability="unknown"),))
    with pytest.raises(ValueError, match="invalid artifact schema version"):
        validate_support_evidence_metadata((replace(base, artifact_schema_version=1),))
    with pytest.raises(ValueError, match="duplicate evidence_id"):
        validate_support_evidence_metadata((base, base))
    with pytest.raises(ValueError, match="noncanonical evidence model_id"):
        validate_support_evidence_metadata((replace(base, model_id="E36312A"),))
    with pytest.raises(ValueError, match="repository-relative"):
        validate_support_evidence_metadata(
            (replace(base, artifact_directory="C:/Users/example/evidence"),)
        )


def test_verified_evidence_does_not_require_artifact_files(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_artifact_access(path: object, *args: object, **kwargs: object) -> object:
        if ".tmp_tests" in str(path):
            raise AssertionError("runtime attempted to access ignored evidence artifacts")
        return original_stat(path, *args, **kwargs)

    import os

    original_stat = os.stat
    monkeypatch.setattr(os, "stat", reject_artifact_access)
    validate_support_evidence_metadata()
    validate_live_support_metadata()


def test_policy_accepted_and_candidate_basis_references_are_exact() -> None:
    accepted_count = 0
    pending_count = 0
    for model_policy in LIVE_SUPPORT_POLICY_REGISTRY:
        for command_policy in model_policy.commands:
            for scope in command_policy.scopes:
                if scope.validation_status == VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE:
                    accepted_count += 1
                    assert scope.accepted_evidence_ids
                    assert scope.candidate_basis_evidence_ids == ()
                    for evidence_id in scope.accepted_evidence_ids:
                        evidence = SUPPORT_EVIDENCE_BY_ID[evidence_id]
                        assert evidence.model_id == model_policy.model_id
                        assert evidence.transport_scope == scope.transport_scope
                        assert evidence.backend_scope == scope.backend_scope
                elif scope.validation_status == VALIDATION_STATUS_TRANSPORT_PENDING:
                    pending_count += 1
                    assert scope.accepted_evidence_ids == ()
                    assert scope.backend_scope == BACKEND_PYVISA_PY
                    assert scope.candidate_basis_evidence_ids
                    for evidence_id in scope.candidate_basis_evidence_ids:
                        evidence = SUPPORT_EVIDENCE_BY_ID[evidence_id]
                        assert evidence.model_id == model_policy.model_id
                        assert evidence.transport_scope == scope.transport_scope
                        assert evidence.backend_scope == "system_visa"
                    assert all(
                        feature.validation_status == VALIDATION_STATUS_FEATURE_PENDING
                        and not feature.inherits_parent_accepted_evidence
                        for feature in scope.feature_scopes
                    )
    assert accepted_count > 0
    assert pending_count > 0


def test_each_promoted_command_references_its_exact_verified_evidence() -> None:
    for model_policy in LIVE_SUPPORT_POLICY_REGISTRY:
        promoted_commands = EXPECTED_PROMOTED_COMMANDS[model_policy.model_id]
        for command_policy in model_policy.commands:
            if command_policy.command not in promoted_commands:
                continue
            for scope in command_policy.scopes:
                if scope.validation_status != VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE:
                    continue
                if model_policy.model_id == "gw-instek-psm-2010":
                    expected_id = PSM2010_EVIDENCE_ID
                elif (
                    model_policy.model_id == "keysight-e3646a"
                    and command_policy.command == "log"
                ):
                    expected_id = NEW_E3646A_LOG_EVIDENCE_ID
                else:
                    expected_id = (
                        f"{model_policy.model_id}-{scope.transport_scope}-"
                        "system-visa-20260717-full"
                    )
                assert scope.accepted_evidence_ids == (expected_id,)


@pytest.mark.parametrize(
    ("evidence_id", "match"),
    [
        ("keysight-edu36311a-usb-system-visa-20260709-full", "evidence model mismatch"),
        ("keysight-e36312a-tcpip-system-visa-20260709-full", "evidence transport mismatch"),
        ("missing-evidence-id", "missing evidence registry entry"),
    ],
)
def test_wrong_or_missing_evidence_cannot_authorize_scope(
    evidence_id: str,
    match: str,
) -> None:
    model_policy = next(
        policy for policy in LIVE_SUPPORT_POLICY_REGISTRY if policy.model_id == "keysight-e36312a"
    )
    command_policy = next(policy for policy in model_policy.commands if policy.command == "measure")
    scope = next(scope for scope in command_policy.scopes if scope.transport_scope == "usb")
    changed_command = replace(
        command_policy,
        scopes=(replace(scope, accepted_evidence_ids=(evidence_id,)),)
        + tuple(item for item in command_policy.scopes if item is not scope),
    )
    changed_model = replace(
        model_policy,
        commands=(changed_command,)
        + tuple(item for item in model_policy.commands if item is not command_policy),
    )
    registry = (changed_model,) + tuple(
        item for item in LIVE_SUPPORT_POLICY_REGISTRY if item is not model_policy
    )
    with pytest.raises(ValueError, match=match):
        validate_live_support_metadata(registry)


def test_evidence_backend_must_exactly_match_policy_scope() -> None:
    evidence = SUPPORT_EVIDENCE_RECORDS[0]
    mismatched = replace(evidence, backend_scope="pyvisa_py")
    evidence_registry = {**SUPPORT_EVIDENCE_BY_ID, evidence.evidence_id: mismatched}
    with pytest.raises(ValueError, match="evidence backend mismatch"):
        validate_live_support_metadata(evidence_registry=evidence_registry)


def test_pending_scope_cannot_claim_accepted_evidence() -> None:
    model_policy = next(
        policy for policy in LIVE_SUPPORT_POLICY_REGISTRY if policy.model_id == "keysight-e36312a"
    )
    command_policy = next(policy for policy in model_policy.commands if policy.command == "measure")
    pending = next(
        scope for scope in command_policy.scopes if scope.validation_status == VALIDATION_STATUS_TRANSPORT_PENDING
    )
    changed_pending = replace(
        pending,
        accepted_evidence_ids=pending.candidate_basis_evidence_ids,
        candidate_basis_evidence_ids=(),
    )
    changed_command = replace(
        command_policy,
        scopes=tuple(changed_pending if scope is pending else scope for scope in command_policy.scopes),
    )
    changed_model = replace(
        model_policy,
        commands=tuple(
            changed_command if policy is command_policy else policy
            for policy in model_policy.commands
        ),
    )
    registry = tuple(
        changed_model if policy is model_policy else policy
        for policy in LIVE_SUPPORT_POLICY_REGISTRY
    )
    with pytest.raises(ValueError, match="pending scope claims accepted evidence"):
        validate_live_support_metadata(registry)


def test_validated_features_explicitly_inherit_parent_evidence() -> None:
    for model_policy in LIVE_SUPPORT_POLICY_REGISTRY:
        for command_policy in model_policy.commands:
            for scope in command_policy.scopes:
                if scope.validation_status != VALIDATION_STATUS_LIVE_VALIDATED_FULL_SUITE:
                    continue
                for feature in scope.feature_scopes:
                    assert feature.inherits_parent_accepted_evidence is True


def test_public_projection_is_schema_v2_and_redacts_evidence() -> None:
    projection = exact_live_support_metadata(
        model_id="keysight-e36312a",
        resource="USB0::FAKE::INSTR",
        backend=None,
        commands={"set", "sequence"},
    )
    assert projection["schema_version"] == 2
    assert projection["model_id"] == "keysight-e36312a"
    assert "model" not in projection
    serialized = json.dumps(projection)
    for forbidden in (
        "evidence_id",
        "accepted_evidence_ids",
        "candidate_basis_evidence_ids",
        ".tmp_tests",
        "report_sha256",
        "migration note",
    ):
        assert forbidden not in serialized
