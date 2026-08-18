# Contributing to Powers Tool

Thank you for improving Powers Tool. Useful contributions include issue
reports, focused bug fixes, English documentation, tests, simulator and fake
instrument improvements, model support, command/workflow support, and
transport/backend evidence.

Keep pull requests focused. Describe any change to a public contract,
instrument-safety behavior, support metadata, or real-instrument validation
scope. Do not combine an unrelated refactor with a model or hardware-safety
change.

## Development setup

Work from the repository root. The root `pyproject.toml` owns the supported
Python version, dependencies, package version, build metadata, and console
entry points. `uv.lock` is the committed reproducibility lock file.

```powershell
uv venv .venv
uv sync --all-extras --locked --link-mode=copy
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

The repository is one distribution, `powers-tool`; do not create a
component-local distribution. Use focused no-hardware tests while iterating,
then run relevant Core, CLI, WebUI, and documentation/ownership tests. Explain
in the pull request if the full no-hardware suite was not run.

## Architecture and ownership

The three import packages have distinct responsibilities:

- `powers_tool_core` owns model logic, exact live-scope authorization,
  drivers, safety validation, and hardware-facing behavior.
- `powers_tool_cli` is the command-line adapter.
- `powers_tool_webui` is the browser and HTTP adapter.

The dependency direction is `CLI -> Core` and `WebUI -> Core`. Core must not
import either adapter. Frontend enabled/disabled state is UX only; Core is the
final safety and exact-scope authority.

Keep the Core architecture vendor-neutral. New vendor or model support still
requires explicit manufacturer-plus-model identity metadata, a vendor/model
driver, verified SCPI behavior, safety coverage, and exact support scopes.

## Testing expectations

Default tests must not need hardware. Add focused fake-session, simulator, or
dry-run coverage for the changed behavior. Run relevant Core, CLI, WebUI, and
documentation/ownership tests, followed by the full no-hardware suite when
practical.

The packaging identity tests scan every tracked UTF-8 text file for the frozen
legacy framework-name inventory. Retained historical, negative-test, and
deferred localized references require an exact file/token/count allowlist with
a documented reason; a new occurrence or allowlist-count drift fails the gate.

Real-instrument evidence is required before proposing a new model, command,
workflow, SCPI behavior, VISA/backend behavior, transport scope, output setup,
voltage/current limit, OVP/OCP behavior, trigger behavior, snapshot/restore,
sequence behavior, timeout, cleanup, remote/local behavior, or pending-scope
promotion. A passing artifact is evidence for review, not a self-service
support decision.

## Real-instrument validation

The maintained contributor validation harness is
`scripts\live-cli-check.ps1`. Run `-PlanOnly` first; it performs simulator,
dry-run, lint, and expected-failure checks without opening VISA.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\live-cli-check.ps1 `
  -Target "<SUPPORTED_TARGET>" `
  -Connection "<USB|LAN|ASRL>" `
  -Resource "<EXPLICIT_VISA_RESOURCE>" `
  -Suite "<SUITE>" `
  -PlanOnly
```

After reviewing the plan, remove `-PlanOnly` only in an interactive session.
Live validation is explicit opt-in, requires confirmation, never scans or
guesses a resource, uses bounded low-power cases, and writes reviewable
artifacts below `.tmp_tests\live_cli_check`. `-Backend "@py"` is an optional
advanced contributor-validation choice when the exact pending scope is
registered; it is not normal product support.

The wrapper applies the canonical target as an expected-model guard only to
identity-bearing commands and model-aware commands that own that CLI contract.
`verify` and `identify` query `*IDN?` and compare the manufacturer-plus-model
resolution with that guard. Raw `error` and `clear` diagnostics do not accept a
model guard, and `list-resources` does not accept a physical model identity.

## New models, commands, and capabilities

Physical model enablement follows four explicit stages: `catalog_only`,
`candidate`, `product_active`, and `de_scoped`. Catalog recognition is useful
identity metadata, but it is not a runtime profile. A candidate is accepted
only after its model metadata, model-specific driver, channels, deterministic
simulator identity, capabilities, electrical ratings, setpoint range/limit
metadata, hard limits, safety checks, and tests all exist, together with a
complete exact pending command/feature policy. Ratings and ranges are
independent prerequisites; one does not substitute for the other.

Use this order for a proposed model support expansion:

```text
catalog-only model
→ implement complete model/profile/driver metadata
→ define channels, ratings, ranges, and hard limits
→ add request validation
→ mark candidate
→ register exact command and feature scopes as pending
→ add simulator/fake/no-hardware tests
→ run bounded hidden Validation-mode bootstrap
→ extend the maintained wrapper where appropriate
→ attach complete redacted artifacts
→ maintainer review
→ explicit evidence-backed Product policy decision
```

Catalog recognition is not a candidate, a candidate is not Product-open, and
a model with missing prerequisites is not pending support. Contributors must
not mark a model candidate until every candidate prerequisite is present. A
new model must not use `GenericScpiPowerSupply` for model-aware output merely
because its SCPI looks similar to an existing model. Product support requires
accepted exact evidence and an explicit policy decision; changing only a stage
or attaching a passing artifact does not promote support.

The machine-readable Core support-policy contract is defined in
[Core Integration](core/integration.md#support-policy-contract).

Exact command support is also feature-aware. The first feature kinds are
normalized sequence actions and real trigger sources. Adding a new sequence
action or trigger source requires profile/request validation and an exact
feature entry for every applicable transport/backend scope. Missing feature
metadata fails closed; `feature_pending` remains contributor Validation-mode
only. A validated connection may mix validated and pending features without
opening the pending feature in Product mode. Every applicable pending scope of
a feature-aware candidate command must list the complete profile-supported
feature inventory as `feature_pending`.

## Hidden validation mode

Contributors may use the intentionally hidden bootstrap option
`--validation-allow-pending-live-support` only for a registered pending exact
scope. It is contributor/bootstrap tooling, not a general `--force`, not
normal product support, and not automatic promotion.

The option never bypasses model/profile recognition, detected `*IDN?`,
expected-model mismatch, missing metadata, unsupported commands, hard model or
channel limits, official ratings, range-dependent voltage/current constraints,
setpoint safety, confirmation, OVP/OCP, trigger restrictions, sequence
restrictions, cleanup, or session close. Missing metadata is not pending support.

For a bounded bootstrap case without a wrapper entry, use the hidden option
only after Core recognizes the model, the command is
implemented, ratings/hard limits and request validation exist, the exact
pending scope is registered, and simulator or fake coverage exists:

```powershell
.\.venv\Scripts\python.exe -m powers_tool_cli.cli `
  <COMMAND> `
  --validation-allow-pending-live-support `
  --resource "<EXPLICIT_VISA_RESOURCE>" `
  --model "<EXPECTED_MODEL>" `
  <BOUNDED_COMMAND_ARGUMENTS> `
  --json
```

Do not use this template to enable an unbounded output-on experiment. Extend
the maintained wrapper for formal, repeatable pull-request evidence whenever a
case is reusable.

## Artifact requirements

The wrapper keeps local raw execution files in `private/` and creates a
redacted `shareable/` artifact set. Attach only the files from `shareable/`:
its `report.json`, `summary.md`, and redacted per-command JSON/stdout/stderr
evidence. Never upload or manually copy files from `private/`. Failed or
malformed raw command output remains private; the shareable set records a safe
placeholder when that output cannot be parsed. The shareable set records the
commit SHA, package version, pull-request revision, expected model, detected
manufacturer/model, firmware, redacted serial, transport, backend, exact
wrapper command, target, suite, selected cases, plan-only/live status, exit
codes, failures or partial results, output-state result, error queue, and
cleanup result.

Failed validation is still useful evidence and must not be discarded. Passing
artifacts for pending or new exact scopes are candidate evidence; regression
artifacts for already Product-open exact scopes are not candidate evidence.
Neither kind automatically promotes or broadens Product support.
Failed cleanup is not accepted evidence.
Skipped or incomplete cleanup is not cleanup-verified evidence. Required
state-changing evidence cannot pass unless safe-off succeeds, outputs are
confirmed OFF, and the final error queue is clean.

Product-open support is referenced from Core policy by exact, non-sensitive
evidence metadata. Each accepted record remains exact to canonical physical
`model_id`, transport, backend, command, and required feature; an artifact for
another vendor, model, transport, or backend cannot be inherited. A passing
candidate artifact does not update Product support automatically. System-VISA
evidence may be cited as a non-promoting basis for a pending pyvisa-py scope,
but it never validates that backend.

## Power-supply safety and privacy

Use no DUT or only a known safe load for state-changing validation. Set an
explicit low voltage and current limit, verify output OFF before and after the
run, and account for OVP/OCP, channel selection, E3646A global-output behavior,
and sequence-step safety. Always provide an explicit resource.

Do not upload a raw resource, private IP address, complete serial number, raw
IDN string, personal filesystem path, or any file from `private/` in a pull
request, public artifact, issue, or documentation. Generated validation
artifacts remain ignored and must not be committed.

## Pull request checklist

- [ ] Scope is focused and public-contract changes are disclosed.
- [ ] Relevant no-hardware tests passed; full-suite status is stated.
- [ ] Instrument-safety, output, limits, confirmation, cleanup, and metadata
      changes are disclosed.
- [ ] Any pending exact scope and bounded wrapper case are identified.
- [ ] Real validation artifacts are complete, redacted, and include failures
      or partial evidence when applicable.
- [ ] The pull request does not claim automatic promotion from a passing run.
- [ ] English documentation is updated when required; localized documentation
      is deferred unless explicitly requested.
