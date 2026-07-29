---
name: powers-tool-cli-orchestration
description: Use when modifying, reviewing, testing, or orchestrating Powers Tool CLI and Power Worker workflows, including schema-2 JSON/JSONL, POST /command context, Core admission, execution identities, job artifacts, simulator and dry-run validation, exact Product LIVE support, owned-process cleanup, and live power-supply safety. Do not use for CSS-only WebUI styling, unrelated documentation edits, general Python refactors, VISA discovery, or automatic hardware control.
---

# Powers Tool CLI Orchestration

Follow the public Powers Tool CLI, Worker, Core admission, Product-support, and
safety contracts. Treat this as an instruction-only companion: it is not part
of the Powers runtime, does not provide a driver, and does not authorize live
hardware work.

## Contract lookup order

Before contract-sensitive work, read these documents in order:

1. Inside the Powers Tool repository, use the original files under
   `docs/contracts/` and `docs/core/supported-models.md`. They are the upstream
   source of truth.
2. In a standalone executable workspace, use the installed Skill's
   `references/` directory. These files are a manually copied snapshot, not a
   second contract.
3. If both sources exist, prefer the repository originals. If they differ,
   report the stale snapshot and use the originals.
4. Use CLI `--help` only to confirm behavior after contract lookup. If neither
   originals nor all required snapshots are readable, report the missing
   contract evidence instead of inventing flags or behavior.

Read the common documents before their Power-specific extensions:

1. `common-worker-protocol.md`
2. `common-cli-jsonl-contract.md`
3. `common-orchestrator-workflows.md`
4. `power-worker-contract.md`
5. `power-cli-jsonl-contract.md`
6. `power-orchestrator-workflows.md`
7. `commands-parameter-contract.md`
8. `supported-models.md`

## Scope

Use this Skill for CLI or Worker lifecycle changes, repository diff reviews,
machine-output validation, no-hardware orchestration, execution-context
decisions, job correlation, command admission, Product LIVE scope checks, or
preparing an explicitly authorized live workflow.

Do not use it to widen model support, promote pending evidence, change SCPI,
discover VISA resources, select a resource for the user, or execute live work
without explicit authorization. Do not treat it as a WebUI browser API
contract, package component, release gate, or general repository guide.

## Machine evidence

- Require exact integer `schema_version: 2` wherever the runtime contract
  specifies schema 2: Worker JSONL events, `GET /status`, accepted
  `POST /command` responses, `request.json`, terminal `result.json`, and other
  schema-2 CLI JSON/JSONL envelopes. Reject missing versions, schema 1,
  strings, booleans, unsupported integers, fallback, or negotiation.
- Follow the documented endpoint shape. The current Power `POST /stop`
  acknowledgment is the explicit exception: validate HTTP 200, `ok: true`, and
  a non-empty `message`; do not invent a `schema_version` field that its
  contract does not define.
- Use machine JSON/JSONL, artifacts, status objects, final summary, and process
  exit code for decisions. Human-readable text is diagnostic only.
- Treat parse errors, missing terminal evidence, final `summary.ok: false`, or
  a nonzero Worker exit code as failure or incomplete convergence.
- Ignore unknown output fields allowed by schema 2, but never ignore missing or
  mistyped required fields.

## Execution context and identities

Every Power Worker `POST /command` request requires top-level `context`.
Do not place mode or identity fields inside `arguments`.

| Mode | Required or allowed identity | Forbidden identity |
| --- | --- | --- |
| `live` | optional `expected_model_id` | `planning_model_id`, `planning_profile_id` |
| `simulate` | required `planning_model_id` | `expected_model_id`, `planning_profile_id` |
| `dry_run` | exactly one of `planning_model_id` or `planning_profile_id` | `expected_model_id`, both planning fields together |

A live Worker accepts live and dry-run requests. A simulate Worker accepts
simulate and dry-run requests. Reject other startup/request combinations.

- Treat `expected_model_id` only as a live mismatch guard. Detected
  manufacturer-plus-model identity remains authoritative, selects the driver,
  and controls live support. The guard never selects a driver or unlocks a
  command, feature, transport, or backend.
- Use `planning_model_id` for a canonical physical model in simulate or
  model-specific dry-run planning.
- Use `planning_profile_id` only for a nonphysical dry-run profile. The current
  Powers value is `generic-scpi`; it is not a physical model and never selects
  a live driver.
- Do not infer any identity from a fake or live-looking resource. A known
  deterministic simulator resource may provide the documented no-hardware
  planning identity, but an explicit identity and simulator resource must
  agree.

## Command admission and Product support

- Treat Core command admission as the single parameter authority shared by
  direct Core requests, CLI, Power Worker, and WebUI Commands. Do not add
  adapter-local aliases, defaults, coercion, or allowlists.
- Preserve exact JSON types. Reject unknown or cross-command fields, invalid
  nulls, boolean-as-number values, numeric strings, alias conflicts, and other
  inputs the Core contract rejects.
- Treat Product LIVE as an exact scope:
  `model + command + transport + backend + required categorical feature`.
  The presence of a model, command, driver, capability row, or family name
  alone never proves that the current connection may execute live.
- Do not treat no-hardware capability, candidate or pending scope, validation
  mode, historical evidence, another transport/backend, or another feature as
  Product-open. Missing and pending exact scopes fail closed.
- Consult `supported-models.md` for the current exact Product matrix; never
  reconstruct it from memory or broaden it by analogy.

## Worker lifecycle and correlation

1. Prefer dry-run or simulate before considering live.
2. Start an owned `powers-tool worker` subprocess in machine mode and retain
   its process handle.
3. Stream stdout as JSONL and stderr separately. Wait for `ready`; if it was
   missed, use `wait-ready` or poll `GET /status` without performing device I/O.
4. Use `GET /status` only for lifecycle health and progress. It is not an
   instrument status command; use admitted `read-status` for that domain work.
5. Send a schema-2 `POST /command` envelope with `command`, object
   `arguments`, optional client `job_id`, and required top-level `context`.
6. Treat HTTP `202` and `status: "accepted"` only as queue acceptance. Record
   the echoed `job_id`, generated `worker_job_id`, and `artifact_path`.
7. Verify `request.json` immediately exists after acceptance. It contains the
   admitted schema-2 command, arguments, and context.
8. Follow `GET /status` and the accepted artifact directory until terminal
   `result.json` exists. Absence of `result.json` is not success.
9. Accept terminal success only when `result.json` has status `succeeded`,
   `ok: true`, and matching `run_id` and `worker_job_id`. Treat `failed` and
   `cancelled` as non-success.
10. Request cooperative `stop` for the owned Worker, wait for the final
    `summary`, and collect the Worker exit code. Do not stop or reuse unrelated
    existing processes.

Keep identities distinct:

- `run_id` identifies one Worker runtime session and correlates stdout events,
  status responses, result artifacts, and final summary.
- `job_id` is the optional orchestrator-provided ID echoed by runtime
  responses/status/events. It is not the artifact identity and is not written
  into Power `request.json` or `result.json`.
- `worker_job_id` is generated by the Worker, identifies the job and artifact
  directory, and is required for exact workflow cancellation.

Use `POST /cancel` only for the active cancellable Ramp, Ramp List, or Sequence
job and provide its exact schema-2 `worker_job_id`. Cancellation is cooperative
and does not stop the Worker. Treat `POST /stop` as a cooperative stop request,
not proof that cleanup or process shutdown has finished. Preserve owned-process
cleanup and bounded observation through final summary and exit.

## Live safety

- Require the user to provide the exact live VISA resource explicitly. Never
  guess, scan, rotate, brute-force, infer, or silently substitute a resource
  during a workflow.
- Require explicit live authorization separately from resource selection.
- For every live output-affecting Worker command, require both gates:
  Worker `settings.allow_output_writes: true` and request
  `arguments.confirm_output: true`. Either gate missing must fail closed.
- Keep current limit/setpoint ordering, conservative setpoints, safe-off, and
  documented cleanup behavior. Do not change output, protection, trigger,
  timing, remote/local, or cleanup semantics without explicit confirmation.
- Preparing a live workflow does not authorize running it. Stop after producing
  the exact command/config plan when the request says to prepare only.

## Work pattern

1. Identify the affected contract surface and mode.
2. Read the source-of-truth contracts in lookup order.
3. Establish exact identity, command admission, Product scope, resource, and
   safety gates before proposing execution.
4. Validate with dry-run or deterministic simulation where possible.
5. Correlate machine evidence and owned-process cleanup.
6. Report contract impact, checks run, skipped live validation, and remaining
   safety risk.

## Bundled simulator helper

Use `scripts/run_power_sim_workflow.mjs` only for the fixed no-hardware
E36312A simulator `read-status` smoke. It starts an owned simulate Worker,
checks lifecycle and job artifacts, cooperatively stops it, and produces a
wrapper report. It rejects live/arbitrary resources, alternate commands, and
mode selection.

```powershell
node .agents\skills\powers-tool-cli-orchestration\scripts\run_power_sim_workflow.mjs `
  --exe .\powers-tool-<version>.exe `
  --out .tmp_tests\power_sim_workflow
```

The helper report has its own `schema_version: 1` and identifies checked Powers
runtime evidence with `runtime_schema_version: 2`. Treat its exit code and
`ok` field as the wrapper result; inspect individual checks and artifacts on
failure.
