# Core Integration

`powers_tool_core` owns the vendor-neutral hardware-facing runtime for
supported DC power supplies. Current Product support is defined by
[Supported Models](supported-models.md). Adapter packages should build
parser-neutral request objects
and call the shared command runners instead of constructing SCPI directly.

`powers_tool_core` ships as part of the single `powers-tool`
distribution. Its installed version follows `[project].version` from the root
`pyproject.toml`, while the import boundary remains `powers_tool_core`.

The package exposes `__version__` through `powers_tool_core.__all__`.

## Boundary

Core may depend on PyVISA, simulator helpers, model drivers, safety validation,
sequence loading, and command runner modules. It must not import from
`powers_tool_cli` or `powers_tool_webui`.

## Adapter Integration Boundary

Core owns adapter-neutral domain logic, command admission, model identity,
Product policy, driver and SCPI execution, and workflow runtime. The bundled
CLI (including the Worker) and WebUI are parallel adapters: they map their
transport inputs to parser-neutral Core request objects, then own their own
serialization and presentation.

For generic command routing, `validate_request_admission()` and
`run_core_command()` are the adapter-facing Core integration entry points used
by those bundled adapters. Admission performs canonicalization without
hardware, VISA, or SCPI I/O and without device-state mutation. File-backed
requests may perform local filesystem I/O during one-time materialization.
`run_core_command()` admits before dispatching the request.

These statements describe the bundled-adapter integration boundary; they do not
expand package exports or make other non-underscore functions broad stable
third-party APIs. Underscore-prefixed helpers, including `_run_*_admitted`, are
Core-internal handoffs for already admitted requests and are not stable adapter
APIs.

## Support-Policy Contract

This section documents the status, reason, and feature-state values currently
implemented by Core support-policy projections and enforcement. The values
remain layer-specific; they are not a new unified state taxonomy.

`RuntimeOptions.support_policy_mode` defaults to Product mode. Product mode is
the normal user-facing path and requires an exact Product-open scope for
model-aware live commands; documented diagnostic exemptions keep their limited
diagnostic boundary. Contributor Validation mode is an internal validation
role: it keeps existing Product-open scopes available and may additionally
admit either explicitly registered pending policy entries or separately
registered internal validation-candidate allowlist entries. Internal
validation-candidate entries require explicit command and exact connection
allowlists. They are not published through the current Product support
projections and do not modify Product metadata. Validation mode preserves the
same physical identity, expected-model, request, safety, confirmation, and
cleanup boundaries. Registered policy scopes remain subject to exact command,
transport, backend, and required-feature enforcement.

The exact support key is:

```text
canonical detected model_id + effective command + transport + backend + required feature
```

Core resolves the canonical physical `model_id` from reported manufacturer and
model before applying the expected-model guard. Transport and backend are
normalized independently; current machine values include `usb`, `tcpip`,
`asrl`, `gpib`, `system_visa`, `pyvisa_py`, and `custom_visa`.

The currently implemented values have these existing field-level meanings:

- `profile_validated` is a command/profile classification. It does not by
  itself authorize an exact live transport/backend scope.
- `not_supported_by_model` identifies a command or feature that the current
  model/profile does not support and is rejected in both policy modes.
- `live_validated_full_suite` identifies an exact Product-open scope. A
  validated scope is allowed in both Product and Validation mode.
- `transport_pending` identifies an explicitly registered exact parent scope
  that is not Product-open and is eligible only for Validation mode.
- `feature_pending` identifies an explicitly registered exact feature entry
  that is not Product-open and is eligible only for Validation mode.

Missing or unknown command, scope, or feature metadata is not pending. The
runtime gate fails closed for missing metadata, including missing exact feature
metadata; it does not infer support from a profile, a catalog identity, another
transport, another backend, or a sibling feature.

Feature-aware commands use exact normalized `sequence_action` and
`trigger_source` entries. A validated transport/backend parent may contain
both validated and pending feature entries: Product mode opens only the
validated features, while Validation mode may use an explicitly registered
pending feature. A `transport_pending` parent may contain only pending or
explicitly unsupported feature entries; it must not contain a Product-validated
feature.

`live_support_policy_metadata()` and `exact_live_support_metadata()` are safe
schema-v2 display projections. They expose the current Product-facing
classification, including fields such as `validation_status`, `product_open`,
`pending`, `disabled_reason`, and `support_reason` where applicable.
For a model-aware exact scope, a non-Product-open result is reported as
`product_open=false`; a Product-open exact result is reported as
`product_open=true`.

Policy-exempt diagnostics (`list-resources`, `verify`, `identify`, `error`, and
`clear`) do not require an exact model feature scope and do not open another
scope; offline-only commands are not live authorization. These projections do
not replace the enforcing runtime gate: `ensure_live_scope_supported()` and
the live-support enforcement path apply the exact policy before
command-specific SCPI I/O.

Validation mode does not modify Product support metadata. Passing a validation
run does not automatically promote a Product scope. The
`internal_validation_candidate_inventory()` contract returns only explicitly
registered pending validation candidates and does not derive candidates from
catalog recognition, missing metadata, or Product support. It is an exact
allowlist for internal validation admission; its current contents and count
are not documented here. Contributor execution, artifacts, review, and
promotion workflow remain in [Contributing](../CONTRIBUTING.md).

The current public Product support matrix is documented in
[Supported Models](supported-models.md). Core support-policy metadata and the
enforcing runtime gate remain authoritative for actual admission decisions.

Core documentation is package-local:

- `supported-models.md`
- `integration.md`

The cross-adapter JSONL and worker contracts remain under `../contracts/`.
