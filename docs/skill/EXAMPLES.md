# Powers Tool CLI Orchestration Examples

These prompts assume `powers-tool-cli-orchestration` is installed. Replace
angle-bracket placeholders before using a live-workflow prompt.

## No-hardware simulator read-only workflow

```text
Use $powers-tool-cli-orchestration to run the bundled deterministic E36312A simulator helper with <POWERS_TOOL_EXECUTABLE>. Use only USB0::SIM::E36312A::INSTR, simulate mode, planning_model_id keysight-e36312a, and read-status. Write artifacts under .tmp_tests/power_skill_smoke and decide success only from schema-2 machine evidence, request/result artifacts, correlation, final summary, and Worker exit code. Do not perform VISA discovery or any output-affecting command.
```

Expected behavior: the agent uses the fixed helper workflow, never opens real
hardware, and reports any failed correlation, parse, terminal-result, summary,
or exit-code check.

## Contract-aware repository diff review

```text
Use $powers-tool-cli-orchestration to review the current repository diff. Read the upstream common and Power Worker/CLI/orchestrator contracts, the Core command-parameter contract, and supported-models.md in contract lookup order. Check schema_version 2, top-level POST /command context, identity semantics, Core-owned admission, run/job/artifact correlation, exact Product LIVE scope, and owned-process cleanup. Report findings only; do not edit files or run live hardware.
```

Expected behavior: repository originals take precedence over installed
references. The review does not treat no-hardware capability, pending evidence,
or another backend as Product-open.

## Prepare, but do not execute, a live read-only workflow

```text
Use $powers-tool-cli-orchestration to prepare but not execute a live read-only Power Worker read-status workflow. The exact user-selected VISA resource is <EXACT_USER_PROVIDED_VISA_RESOURCE>. I explicitly authorize live read-only access to that exact resource for the future workflow, but this request authorizes planning only. Do not scan, guess, rotate, or substitute the resource. Use expected_model_id keysight-e36312a only as a live mismatch guard, verify the exact model + read-status + transport + backend + required-feature Product scope from supported-models.md, and provide the Worker config, schema-2 POST /command request, readiness, terminal result, stop, summary, and exit-code checks.
```

Expected behavior: the agent produces a plan without starting a Worker or
opening VISA. It refuses to finalize the plan until the placeholder is replaced
with an exact user-provided resource and does not use the model guard to select
a driver or unlock support.

## Prepare, but do not execute, a live output-affecting workflow

```text
Use $powers-tool-cli-orchestration to prepare but not execute a live output-affecting Power Worker apply workflow. The exact user-selected VISA resource is <EXACT_USER_PROVIDED_VISA_RESOURCE>. I explicitly authorize a future live output workflow on only that exact resource, but this request authorizes planning only. Never scan, guess, rotate, or substitute the resource. Use expected_model_id keysight-e36312a only as a mismatch guard. Verify the exact Product scope first. Require Worker settings.allow_output_writes: true and request arguments.confirm_output: true. Plan CH1 with a conservative 0.05 A current limit and 0.5 V setpoint, preserve current-before-voltage behavior, verify output state, then safe-off and complete owned-process cleanup even on failure. Include schema-2 request/result and run_id/job_id/worker_job_id checks.
```

Expected behavior: the agent prepares the config and request but performs no
live I/O. Both output-write gates remain explicit; cleanup includes safe-off,
terminal artifact verification, cooperative stop, final summary, and Worker
exit code. The placeholder must be replaced before the plan is actionable.
