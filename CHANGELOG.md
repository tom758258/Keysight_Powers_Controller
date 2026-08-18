# Changelog

## Unreleased

## 3.0.0

- Adds Product LIVE support for the GW Instek PSM-2010 over ASRL / RS-232 +
  system VISA, with 23 model-aware commands covering read-only, output,
  protection, snapshot/restore, ramp, and software-sequence workflows.
- Adds range-aware electrical rating validation for instruments with multiple
  operating ranges, requiring combined voltage/current setpoints to fit an
  official range.
- Adds bounded Power Worker telemetry logging with job-local CSV/JSONL
  artifacts and cooperative cancellation.
- Expands Keysight E3646A ASRL + system VISA Product LIVE support with the
  telemetry `log` command.
- Adds the Electron Desktop shell with System, Light, and Dark themes.
- Adds the shared Windows onedir bundle and unified versioned Windows ZIP
  packaging flow.
- Adds multi-channel Ramp support and Ramp List v5 per-Segment channel
  selections while preserving legacy Ramp List compatibility.

## 2.0.0

- Updates the Common Worker, CLI JSON/JSONL, and orchestrator
  contracts to schema version 2 only for the shared `POST /command` mode/model
  context. Common fields are `mode`, live-only `expected_model_id`, and physical
  `planning_model_id`; project-specific contracts may define an additional
  planning identity without changing Common field meanings.
- Moves Powers Worker execution mode and model identity from command arguments
  to top-level `context`. Powers retains the dry-run-only, project-specific
  `planning_profile_id: "generic-scpi"`; queue, status, stop, cancellation,
  cleanup, artifacts, Product support, and hardware-evidence behavior remain
  unchanged.
- Renames the product from Keysight Powers to Powers Tool and the distribution
  from `keysight-powers` to `powers-tool`.
- Renames the Python packages to `powers_tool_core`, `powers_tool_cli`, and
  `powers_tool_webui`, and renames the CLI/WebUI entry points to `powers-tool`,
  `powers-tool-webui`, and `powers-tool-webui-launcher`.
- Removes old command, import-package, field, environment-variable, and schema
  compatibility aliases.
- Introduces vendor-qualified physical `model_id` values and requires reported
  manufacturer plus model to jointly resolve live identity. An expected model
  is a safety guard and never overrides the IDN-selected driver.
- Replaces the physical-model-like `GENERIC` identity with the no-hardware-only
  `generic-scpi` planning profile.
- Splits the ambiguous model-profile contract into `planning_model_id`,
  `expected_model_id`, and `planning_profile_id`.
- Moves affected public schemas to version 2 and changes the Ramp List
  discriminator to `powers-tool-ramp-list`.
- Migrates support policy to canonical `model_id` while preserving the exact
  Product-open and pending command, transport, backend, and feature boundaries.
- Preserves the documented Keysight hardware support boundaries during the
  identity migration. Product support remains limited to exact model, command,
  transport, backend, and required-feature scopes.
- Keeps Product release artifacts limited to the single `powers-tool`
  distribution and excludes repository validation scripts, private fixtures,
  candidate evidence, and internal-only tests.

## 1.0.0

- First stable release of `keysight-powers` for Keysight DC power supply
  workflows.
- Provides the shared Core runtime, `keysight-power` CLI, local WebUI server,
  and Windows WebUI launcher in one installable distribution.
- Supports USB and LAN VISA communication, simulator and dry-run workflows,
  JSON/JSONL automation output, ramp, sequence, trigger, snapshot, restore,
  and protection operations.
- Keeps real hardware output opt-in; default tests and simulator flows do not
  enable instrument output.
