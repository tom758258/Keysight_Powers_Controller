# Repository Layout

```text
src/
  powers_tool_core/
  powers_tool_cli/
  powers_tool_webui/
desktop/
  package.json
  package-lock.json
  main.cjs
tests/
  core/
  cli/
  webui/
  integration/
docs/
  core/
  cli/
  webui/
  contracts/
```

## Package Names

Core, CLI, and WebUI are separate import packages and maintenance boundaries,
released together as one `powers-tool` distribution. The distribution
version is owned by `[project].version` in the root `pyproject.toml`; use
`<version>` in examples where the installed release version is substituted.
Core is vendor-neutral; vendor-specific identity metadata, drivers, and SCPI
behavior remain explicit implementation boundaries.

| Area | Distribution | Import | Version | Console command |
| --- | --- | --- | --- | --- |
| Core | `powers-tool` | `powers_tool_core` | distribution version | None |
| CLI | `powers-tool` | `powers_tool_cli` | distribution version | `powers-tool` |
| WebUI | `powers-tool` | `powers_tool_webui` | distribution version | `powers-tool-webui`, `powers-tool-webui-launcher` |

## Ownership

Root `pyproject.toml` owns distribution metadata, dependencies, console
scripts, package discovery, and WebUI package data for the single
`powers-tool` distribution. Root docs own repository planning,
architecture notes, release checklists, and canonical cross-package contracts
under `../contracts/`.
