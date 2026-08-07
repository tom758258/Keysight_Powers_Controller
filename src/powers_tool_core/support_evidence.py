"""Immutable identities for accepted historical live-support evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
import re
from types import MappingProxyType
from typing import Mapping

from powers_tool_core.identity import IdentityResolutionError, canonical_physical_model_id
from powers_tool_core.support_features import (
    FEATURE_KIND_SEQUENCE_ACTION,
    FEATURE_KIND_TRIGGER_SOURCE,
    normalize_real_trigger_source,
    normalize_sequence_action,
)

SOURCE_AVAILABILITY_VERIFIED_LOCAL = "verified_local"
SOURCE_AVAILABILITY_HISTORICAL_REFERENCE_ONLY = "historical_reference_only"

EVIDENCE_KIND_FULL_SUITE = "accepted_historical_full_suite"
EVIDENCE_KIND_VERIFIED_FULL_SUITE = "accepted_verified_full_suite"

_EVIDENCE_KINDS = frozenset(
    {EVIDENCE_KIND_FULL_SUITE, EVIDENCE_KIND_VERIFIED_FULL_SUITE}
)

_SOURCE_AVAILABILITY_STATES = frozenset(
    {
        SOURCE_AVAILABILITY_VERIFIED_LOCAL,
        SOURCE_AVAILABILITY_HISTORICAL_REFERENCE_ONLY,
    }
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_EVIDENCE_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_PRIVATE_IPV4_PATTERN = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|169\.254\.\d{1,3}\.\d{1,3})\b"
)

LEGACY_SYSTEM_VISA_INTERPRETATION = (
    "The historical wrapper omitted an explicit backend argument and used the "
    "default pyvisa.ResourceManager() system-VISA path. This does not validate "
    "pyvisa-py or a custom VISA backend."
)
EVIDENCE_MIGRATION_NOTE = (
    "Migrated from the accepted pre-V2 live-support baseline. The historical "
    "artifact remains immutable, and this identity migration is not new hardware validation."
)

_E36312A_ACCEPTED_COMMANDS = frozenset(
    {
        "measure", "output-state", "read-status", "readback", "validate-readonly",
        "capabilities", "set", "output-off", "safe-off", "cycle-output", "apply",
        "ramp", "smoke-output", "ramp-list", "sequence", "protection-status",
        "protection-set", "clear-protection", "snapshot", "trigger-status",
        "trigger-step", "trigger-list", "trigger-abort",
    }
)
_EDU36311A_ACCEPTED_COMMANDS = frozenset(
    {
        "measure", "output-state", "read-status", "readback", "validate-readonly",
        "capabilities", "set", "output-off", "safe-off", "cycle-output", "apply",
        "ramp", "smoke-output", "ramp-list", "sequence", "protection-status",
        "protection-set", "clear-protection",
    }
)
_E3646A_ACCEPTED_COMMANDS = frozenset(
    {
        "measure", "output-state", "read-status", "readback", "capabilities", "set",
        "output-off", "safe-off", "cycle-output", "apply", "ramp", "smoke-output",
        "ramp-list", "sequence",
    }
)

_E36312A_VERIFIED_COMMANDS = _E36312A_ACCEPTED_COMMANDS | {
    "doctor", "log", "measure-all", "output-on", "restore-from-snapshot",
    "trigger-fire", "trigger-pulse",
}
_EDU36311A_VERIFIED_COMMANDS = _EDU36311A_ACCEPTED_COMMANDS | {
    "doctor", "log", "output-on",
}
_E3646A_VERIFIED_COMMANDS = _E3646A_ACCEPTED_COMMANDS | {"doctor", "output-on"}
_E3646A_20260807_VERIFIED_COMMANDS = frozenset({"log"})

_E36312A_ACCEPTED_FEATURES = {
    "sequence": frozenset(
        (FEATURE_KIND_SEQUENCE_ACTION, value)
        for value in {
            "apply", "cycle-output", "measure", "output-off", "output-on",
            "output-state", "readback", "safe-off", "set", "trigger-pulse",
        }
    ),
    "trigger-step": frozenset(
        {
            (FEATURE_KIND_TRIGGER_SOURCE, "bus"),
            (FEATURE_KIND_TRIGGER_SOURCE, "immediate"),
        }
    ),
    "trigger-list": frozenset(
        {
            (FEATURE_KIND_TRIGGER_SOURCE, "bus"),
            (FEATURE_KIND_TRIGGER_SOURCE, "immediate"),
        }
    ),
}
_EDU36311A_ACCEPTED_FEATURES = {
    "sequence": frozenset(
        (FEATURE_KIND_SEQUENCE_ACTION, value)
        for value in {
            "apply", "cycle-output", "measure", "output-off", "output-on",
            "output-state", "readback", "safe-off", "set",
        }
    ),
}
_E3646A_ACCEPTED_FEATURES = {
    "sequence": frozenset(
        (FEATURE_KIND_SEQUENCE_ACTION, value)
        for value in {
            "apply", "cycle-output", "measure", "output-off", "output-on",
            "output-state", "readback", "safe-off", "set",
        }
    ),
}

_VERIFIED_SEQUENCE_FEATURES = frozenset(
    (FEATURE_KIND_SEQUENCE_ACTION, value)
    for value in {"output-off", "output-on", "output-state", "readback", "set"}
)
_E36312A_VERIFIED_FEATURES = {
    "sequence": _VERIFIED_SEQUENCE_FEATURES,
    "trigger-step": frozenset({(FEATURE_KIND_TRIGGER_SOURCE, "bus")}),
    "trigger-list": frozenset({(FEATURE_KIND_TRIGGER_SOURCE, "bus")}),
}
_EDU36311A_VERIFIED_FEATURES = {"sequence": _VERIFIED_SEQUENCE_FEATURES}
_E3646A_VERIFIED_FEATURES = {"sequence": _VERIFIED_SEQUENCE_FEATURES}

_ACCEPTED_COMMANDS_BY_MODEL_ID = MappingProxyType(
    {
        "keysight-e36312a": _E36312A_ACCEPTED_COMMANDS,
        "keysight-edu36311a": _EDU36311A_ACCEPTED_COMMANDS,
        "keysight-e3646a": _E3646A_ACCEPTED_COMMANDS,
    }
)
_ACCEPTED_FEATURES_BY_MODEL_ID = MappingProxyType(
    {
        "keysight-e36312a": _E36312A_ACCEPTED_FEATURES,
        "keysight-edu36311a": _EDU36311A_ACCEPTED_FEATURES,
        "keysight-e3646a": _E3646A_ACCEPTED_FEATURES,
    }
)


@dataclass(frozen=True)
class SupportEvidenceRecord:
    """Stable, non-sensitive metadata for one historical evidence bundle."""

    evidence_id: str
    model_id: str
    transport_scope: str
    backend_scope: str
    evidence_date: str
    evidence_kind: str
    artifact_directory: str
    report_path: str
    summary_path: str
    legacy_model_name: str | None
    legacy_backend_interpretation: str | None
    artifact_schema_version: str | None
    report_sha256: str | None
    source_availability: str
    migration_note: str | None
    accepted_commands: frozenset[str]
    accepted_features_by_command: Mapping[str, frozenset[tuple[str, str]]]


@dataclass(frozen=True)
class SupportEvidenceManifest:
    """Schema contract for the non-promoting V2 evidence migration manifest."""

    schema_version: int
    promotes_support: bool
    records: tuple[SupportEvidenceRecord, ...]


def _historical_record(
    evidence_id: str,
    model_id: str,
    transport_scope: str,
    legacy_model_name: str,
    artifact_directory: str,
) -> SupportEvidenceRecord:
    return SupportEvidenceRecord(
        evidence_id=evidence_id,
        model_id=model_id,
        transport_scope=transport_scope,
        backend_scope="system_visa",
        evidence_date="2026-07-09",
        evidence_kind=EVIDENCE_KIND_FULL_SUITE,
        artifact_directory=artifact_directory,
        report_path=f"{artifact_directory}/report.json",
        summary_path=f"{artifact_directory}/summary.md",
        legacy_model_name=legacy_model_name,
        legacy_backend_interpretation=LEGACY_SYSTEM_VISA_INTERPRETATION,
        artifact_schema_version="1.0",
        report_sha256=None,
        source_availability=SOURCE_AVAILABILITY_HISTORICAL_REFERENCE_ONLY,
        migration_note=EVIDENCE_MIGRATION_NOTE,
        accepted_commands=_ACCEPTED_COMMANDS_BY_MODEL_ID[model_id],
        accepted_features_by_command=MappingProxyType(
            dict(_ACCEPTED_FEATURES_BY_MODEL_ID[model_id])
        ),
    )


def _verified_record(
    evidence_id: str,
    model_id: str,
    transport_scope: str,
    artifact_directory: str,
    report_sha256: str,
    accepted_commands: frozenset[str],
    accepted_features_by_command: Mapping[str, frozenset[tuple[str, str]]],
    *,
    evidence_date: str,
) -> SupportEvidenceRecord:
    return SupportEvidenceRecord(
        evidence_id=evidence_id,
        model_id=model_id,
        transport_scope=transport_scope,
        backend_scope="system_visa",
        evidence_date=evidence_date,
        evidence_kind=EVIDENCE_KIND_VERIFIED_FULL_SUITE,
        artifact_directory=artifact_directory,
        report_path=f"{artifact_directory}/report.json",
        summary_path=f"{artifact_directory}/summary.md",
        legacy_model_name=None,
        legacy_backend_interpretation=None,
        artifact_schema_version="2.0",
        report_sha256=report_sha256,
        source_availability=SOURCE_AVAILABILITY_VERIFIED_LOCAL,
        migration_note=None,
        accepted_commands=frozenset(accepted_commands),
        accepted_features_by_command=MappingProxyType(
            {
                command: frozenset(features)
                for command, features in accepted_features_by_command.items()
            }
        ),
    )


SUPPORT_EVIDENCE_RECORDS = (
    _historical_record(
        "keysight-e36312a-usb-system-visa-20260709-full",
        "keysight-e36312a",
        "usb",
        "E36312A",
        ".tmp_tests/live_cli_check/20260709_153201_E36312A_USB_full",
    ),
    _historical_record(
        "keysight-e36312a-tcpip-system-visa-20260709-full",
        "keysight-e36312a",
        "tcpip",
        "E36312A",
        ".tmp_tests/live_cli_check/20260709_201420_E36312A_LAN_full",
    ),
    _historical_record(
        "keysight-edu36311a-usb-system-visa-20260709-full",
        "keysight-edu36311a",
        "usb",
        "EDU36311A",
        ".tmp_tests/live_cli_check/20260709_151534_EDU36311A_USB_full",
    ),
    _historical_record(
        "keysight-edu36311a-tcpip-system-visa-20260709-full",
        "keysight-edu36311a",
        "tcpip",
        "EDU36311A",
        ".tmp_tests/live_cli_check/20260709_200530_EDU36311A_LAN_full",
    ),
    _historical_record(
        "keysight-e3646a-asrl-system-visa-20260709-full",
        "keysight-e3646a",
        "asrl",
        "E3646A",
        ".tmp_tests/live_cli_check/20260709_151205_E3646A_ASRL_full",
    ),
    _verified_record(
        "keysight-e36312a-usb-system-visa-20260717-full",
        "keysight-e36312a",
        "usb",
        ".tmp_tests/live_cli_check/20260717_111636_keysight-e36312a_USB_full/shareable",
        "784087da966a141aab0c859580f0e85b5856f7b3cf319d889790b6f1751b6048",
        _E36312A_VERIFIED_COMMANDS,
        _E36312A_VERIFIED_FEATURES,
        evidence_date="2026-07-17",
    ),
    _verified_record(
        "keysight-e36312a-tcpip-system-visa-20260717-full",
        "keysight-e36312a",
        "tcpip",
        ".tmp_tests/live_cli_check/20260717_110602_keysight-e36312a_LAN_full/shareable",
        "17c4f2d5c5a7e618f0d216cfab1c38b769b123a1fc157b4a0ee9e3acac5c4927",
        _E36312A_VERIFIED_COMMANDS,
        _E36312A_VERIFIED_FEATURES,
        evidence_date="2026-07-17",
    ),
    _verified_record(
        "keysight-edu36311a-usb-system-visa-20260717-full",
        "keysight-edu36311a",
        "usb",
        ".tmp_tests/live_cli_check/20260717_104734_keysight-edu36311a_USB_full/shareable",
        "b613f9eb40cb08df805ed00cb6668c79ef41b5225526874e78daf1a3f5d77b66",
        _EDU36311A_VERIFIED_COMMANDS,
        _EDU36311A_VERIFIED_FEATURES,
        evidence_date="2026-07-17",
    ),
    _verified_record(
        "keysight-edu36311a-tcpip-system-visa-20260717-full",
        "keysight-edu36311a",
        "tcpip",
        ".tmp_tests/live_cli_check/20260717_104008_keysight-edu36311a_LAN_full/shareable",
        "591f4415ebcc5f63d4f42b4a57a81ca9be3586854a9f1fe453c59802591e9ef9",
        _EDU36311A_VERIFIED_COMMANDS,
        _EDU36311A_VERIFIED_FEATURES,
        evidence_date="2026-07-17",
    ),
    _verified_record(
        "keysight-e3646a-asrl-system-visa-20260717-full",
        "keysight-e3646a",
        "asrl",
        ".tmp_tests/live_cli_check/20260717_112310_keysight-e3646a_ASRL_full/shareable",
        "e9df449f532f6759161eeb1cfcf643c700d937ffc3078d8515280a267c3ae9e3",
        _E3646A_VERIFIED_COMMANDS,
        _E3646A_VERIFIED_FEATURES,
        evidence_date="2026-07-17",
    ),
    _verified_record(
        "keysight-e3646a-asrl-system-visa-20260807-full",
        "keysight-e3646a",
        "asrl",
        ".tmp_tests/live_cli_check/20260807_154408_keysight-e3646a_ASRL_full/shareable",
        "ea75f78c8fb8c95fdbd91fed87becb3e41a786220440b3a9c48d0815ae249c2d",
        _E3646A_20260807_VERIFIED_COMMANDS,
        {},
        evidence_date="2026-08-07",
    ),
)

SUPPORT_EVIDENCE_MANIFEST = SupportEvidenceManifest(
    schema_version=2,
    promotes_support=False,
    records=SUPPORT_EVIDENCE_RECORDS,
)

SUPPORT_EVIDENCE_BY_ID: Mapping[str, SupportEvidenceRecord] = MappingProxyType(
    {record.evidence_id: record for record in SUPPORT_EVIDENCE_MANIFEST.records}
)


def validate_support_evidence_metadata(
    records: tuple[SupportEvidenceRecord, ...] | None = None,
) -> None:
    """Fail closed when evidence identities or availability claims are inconsistent."""

    selected = SUPPORT_EVIDENCE_MANIFEST.records if records is None else records
    seen_ids: set[str] = set()
    for record in selected:
        if not _EVIDENCE_ID_PATTERN.fullmatch(record.evidence_id):
            raise ValueError(f"invalid evidence_id: {record.evidence_id!r}")
        if record.evidence_id in seen_ids:
            raise ValueError(f"duplicate evidence_id: {record.evidence_id}")
        seen_ids.add(record.evidence_id)
        try:
            if canonical_physical_model_id(record.model_id) != record.model_id:
                raise ValueError(f"noncanonical evidence model_id: {record.model_id!r}")
        except IdentityResolutionError as exc:
            raise ValueError(f"noncanonical evidence model_id: {record.model_id!r}") from exc
        if record.transport_scope not in {"usb", "tcpip", "asrl", "gpib"}:
            raise ValueError(f"invalid evidence transport: {record.transport_scope!r}")
        if record.backend_scope not in {"system_visa", "pyvisa_py", "custom_visa"}:
            raise ValueError(f"invalid evidence backend: {record.backend_scope!r}")
        if record.evidence_kind not in _EVIDENCE_KINDS:
            raise ValueError(f"invalid evidence kind: {record.evidence_kind!r}")
        if not isinstance(record.evidence_date, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", record.evidence_date
        ):
            raise ValueError(f"invalid evidence date: {record.evidence_id}")
        if record.source_availability not in _SOURCE_AVAILABILITY_STATES:
            raise ValueError(f"invalid evidence source availability: {record.source_availability!r}")
        if record.source_availability == SOURCE_AVAILABILITY_VERIFIED_LOCAL:
            if not isinstance(record.report_sha256, str) or not _SHA256_PATTERN.fullmatch(
                record.report_sha256
            ):
                raise ValueError(f"verified-local evidence requires SHA-256: {record.evidence_id}")
        elif record.report_sha256 is not None:
            raise ValueError(
                f"historical-reference-only evidence cannot claim a checksum: {record.evidence_id}"
            )
        if record.artifact_schema_version is not None and (
            not isinstance(record.artifact_schema_version, str)
            or not re.fullmatch(r"[1-9]\d*\.\d+", record.artifact_schema_version)
        ):
            raise ValueError(f"invalid artifact schema version: {record.evidence_id}")
        if record.evidence_kind == EVIDENCE_KIND_FULL_SUITE:
            if record.evidence_date != "2026-07-09":
                raise ValueError(f"historical evidence date changed: {record.evidence_id}")
            if record.artifact_schema_version != "1.0":
                raise ValueError(f"historical evidence schema changed: {record.evidence_id}")
            if record.source_availability != SOURCE_AVAILABILITY_HISTORICAL_REFERENCE_ONLY:
                raise ValueError(f"historical evidence source state changed: {record.evidence_id}")
            if not isinstance(record.legacy_model_name, str) or not record.legacy_model_name:
                raise ValueError(f"historical evidence model name is required: {record.evidence_id}")
            if not isinstance(record.legacy_backend_interpretation, str) or not record.legacy_backend_interpretation:
                raise ValueError(f"historical backend interpretation is required: {record.evidence_id}")
            if not isinstance(record.migration_note, str) or not record.migration_note.strip():
                raise ValueError(f"evidence migration note is required: {record.evidence_id}")
        else:
            if record.artifact_schema_version != "2.0":
                raise ValueError(f"verified evidence schema mismatch: {record.evidence_id}")
            if record.source_availability != SOURCE_AVAILABILITY_VERIFIED_LOCAL:
                raise ValueError(f"verified evidence source state mismatch: {record.evidence_id}")
            if any(
                value is not None
                for value in (
                    record.legacy_model_name,
                    record.legacy_backend_interpretation,
                    record.migration_note,
                )
            ):
                raise ValueError(f"verified evidence cannot claim historical metadata: {record.evidence_id}")
        _validate_repository_relative_path(record.artifact_directory, record.evidence_id)
        _validate_repository_relative_path(record.report_path, record.evidence_id)
        _validate_repository_relative_path(record.summary_path, record.evidence_id)
        if record.report_path != f"{record.artifact_directory}/report.json":
            raise ValueError(f"unexpected evidence report path: {record.evidence_id}")
        if record.summary_path != f"{record.artifact_directory}/summary.md":
            raise ValueError(f"unexpected evidence summary path: {record.evidence_id}")
        _validate_accepted_inventory(record)
        _validate_non_sensitive_record(record)


def validate_support_evidence_manifest(manifest: SupportEvidenceManifest) -> None:
    """Fail closed when the V2 evidence manifest contract is inconsistent."""

    if type(manifest.schema_version) is not int or manifest.schema_version != 2:
        raise ValueError(
            "unsupported evidence manifest schema version: "
            f"{manifest.schema_version!r}"
        )
    if manifest.promotes_support is not False:
        raise ValueError("evidence manifest must be explicitly non-promoting")
    if not isinstance(manifest.records, tuple) or not manifest.records:
        raise ValueError(
            "evidence manifest records must be an immutable non-empty tuple"
        )
    validate_support_evidence_metadata(manifest.records)


def validate_support_evidence_registry(
    registry: Mapping[str, SupportEvidenceRecord],
) -> None:
    """Fail closed when registry keys do not exactly identify their records."""

    validate_support_evidence_metadata(tuple(registry.values()))
    for registry_key, record in registry.items():
        if registry_key != record.evidence_id:
            raise ValueError(
                "evidence registry key mismatch: "
                f"key={registry_key!r}, evidence_id={record.evidence_id!r}"
            )


def _validate_accepted_inventory(record: SupportEvidenceRecord) -> None:
    if not isinstance(record.accepted_commands, frozenset) or not record.accepted_commands:
        raise ValueError(f"evidence accepted commands must be a non-empty frozenset: {record.evidence_id}")
    for command in record.accepted_commands:
        if not command or command != command.strip().lower():
            raise ValueError(f"noncanonical evidence command: {record.evidence_id}/{command!r}")
    if not isinstance(record.accepted_features_by_command, MappingProxyType):
        raise ValueError(f"evidence feature inventory must be immutable: {record.evidence_id}")
    for command, features in record.accepted_features_by_command.items():
        if command not in record.accepted_commands:
            raise ValueError(f"evidence feature command mismatch: {record.evidence_id}/{command}")
        if not isinstance(features, frozenset):
            raise ValueError(f"evidence features must be immutable: {record.evidence_id}/{command}")
        for feature_kind, feature_value in features:
            if feature_kind == FEATURE_KIND_SEQUENCE_ACTION:
                normalized_value = normalize_sequence_action(feature_value)
            elif feature_kind == FEATURE_KIND_TRIGGER_SOURCE:
                normalized_value = normalize_real_trigger_source(feature_value)
            else:
                raise ValueError(
                    f"unsupported evidence feature kind: {record.evidence_id}/{command}/{feature_kind}"
                )
            if feature_value != normalized_value:
                raise ValueError(
                    f"noncanonical evidence feature: {record.evidence_id}/{command}/"
                    f"{feature_kind}/{feature_value!r}"
                )


def _validate_repository_relative_path(value: str, evidence_id: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"evidence path must be repository-relative: {evidence_id}")
    path = PurePosixPath(value)
    if (
        not value.startswith(".tmp_tests/live_cli_check/")
        or path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or ".." in path.parts
        or "\\" in value
    ):
        raise ValueError(f"evidence path must be repository-relative: {evidence_id}")


def _validate_non_sensitive_record(record: SupportEvidenceRecord) -> None:
    values = (
        record.evidence_id,
        record.artifact_directory,
        record.report_path,
        record.summary_path,
        record.legacy_backend_interpretation,
        record.migration_note,
    )
    for value in values:
        if value is None:
            continue
        if "::" in value or _PRIVATE_IPV4_PATTERN.search(value):
            raise ValueError(f"evidence metadata contains private resource data: {record.evidence_id}")


validate_support_evidence_manifest(SUPPORT_EVIDENCE_MANIFEST)
validate_support_evidence_registry(SUPPORT_EVIDENCE_BY_ID)
