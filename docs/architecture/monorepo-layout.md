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
  packaging/
  tooling/
docs/
  core/
  cli/
  webui/
  contracts/
  help/
  skill/
  architecture/
  CONTRIBUTING.md
  testing-guidelines.md
scripts/
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

The root `pyproject.toml` is the single distribution metadata boundary. It
owns the project name and version, dependencies and optional groups, public
console scripts, package discovery, and package data for CLI Help and WebUI
static and Help assets.

`Core` owns vendor-neutral model, capability, validation, support-policy, and
hardware-facing behavior. `CLI` and `WebUI` are separate adapters that depend
on Core; Core must not import either adapter, and CLI and WebUI do not depend
on each other.

`desktop/` contains the Electron Desktop shell and npm packaging sources. It
is not a fourth Python import package and presents the existing WebUI. The
formal Windows application includes `Powers Tool.exe`; packaged Desktop uses
the private `powers-tool-webui-host.exe`, while source mode launches the same
host implementation through `powers_tool_webui._desktop_host`. The private
host is not a public Python console entry point.

Tests are organized under `tests/` by maintained boundary, including Core,
CLI, WebUI, integration, packaging, and tooling checks.

Documentation ownership is divided as follows:

- The root README provides project orientation, high-level navigation, and
  install/build/test/release entry points.
- `docs/core/` contains Core maintainer and integration material plus Product
  support documentation.
- `docs/cli/` contains CLI maintainer documentation and the CLI operator guide.
- `docs/webui/` contains WebUI/Desktop maintainer documentation,
  localization/UI-change contracts, and the shared operator guide.
- `docs/contracts/` contains canonical cross-process, CLI, and Worker
  machine-facing contracts.
- `docs/help/` contains bundled Help presentation and maintenance ownership;
  see [`docs/help/README.md`](../help/README.md).
- `docs/skill/` contains optional Powers Tool orchestration skill
  documentation and assets.
- `docs/CONTRIBUTING.md` contains contributor workflow and durable validation
  requirements; `docs/testing-guidelines.md` contains repository testing
  philosophy and durable test-boundary guidance.
