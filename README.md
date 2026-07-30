[繁體中文](README.zh-TW.md)

# Powers Tool

Powers Tool is a vendor-neutral Python toolkit for controlling supported DC
power supplies. Version 2.0.0 provides one installable distribution,
`powers-tool`, with three import packages: `powers_tool_core`,
`powers_tool_cli`, and `powers_tool_webui`.

The framework is vendor-neutral, but current Product-active and
hardware-validated models are `keysight-e36312a` (Keysight E36312A),
`keysight-edu36311a` (Keysight EDU36311A), and `keysight-e3646a` (Keysight
E3646A). Vendor-neutral architecture does not mean arbitrary or unknown power
supplies are supported: unregistered or unresolved live hardware fails closed.
Vendor-specific drivers, aliases, manuals, SCPI behavior, evidence, and support
tables retain their correct vendor names.

The shared Core runtime owns identity resolution, drivers, SCPI behavior,
safety, and exact live-support decisions. The CLI and WebUI are parallel
adapters over Core, while the Power Worker exposes the same Core command
boundary to local automation. The project supports USB, LAN, and explicit
RS-232/ASRL communication through VISA, with safety-first dry-run, simulator,
and machine-readable workflows.

Live hardware is identified from `*IDN?` and remains fail closed outside the
documented exact support scope. See [Supported Models](docs/core/supported-models.md)
for current model and connection coverage, and the
[CLI README](docs/cli/README.md#planning-identities-and-live-expected-model-guards)
for planning and expected-model behavior.

## Features

- Control supported Keysight DC power supplies over USB, LAN, or explicit
  RS-232/ASRL settings using VISA
- Use either the `powers-tool` CLI or the local `powers-tool-webui`
  dashboard
- Use the WebUI in English or Traditional Chinese, switching at runtime
  without reload while keeping machine-facing values, API payloads, and raw
  diagnostics unchanged
- Preview hardware-affecting commands with dry-run mode before opening VISA
- Test workflows without hardware using the built-in simulator
- Set voltage/current limits, control output state, and read back live
  instrument data
- Run ramp, ramp-list, sequence, trigger, snapshot, restore, and protection
  workflows through the shared Core runtime
- Produce JSON and JSONL output for automation, agents, and orchestrators
- Keep real hardware output opt-in; default tests and simulator flows do not
  enable instrument output

## Project Structure

The normal Product release has one distribution and one version number. In
examples, `<version>` means `[project].version` from the root `pyproject.toml`:

- Distribution: `powers-tool` `<version>`
- Core import: `powers_tool_core`
- CLI import: `powers_tool_cli`
- WebUI import: `powers_tool_webui`

The import paths remain independent. Do not use a `keysight_power.*`
namespace package.

```text
src/
  powers_tool_core/
  powers_tool_cli/
  powers_tool_webui/
tests/
  core/
  cli/
  webui/
  integration/
docs/
  core/
  cli/
  webui/
scripts/
```

## Install

Open PowerShell and enter the project root first:

```powershell
cd path\to\powers-tool
```

Install uv if it is not already available:

```powershell
py -m pip install --user uv
```

Verify uv:

```powershell
uv --version
```

Create the project virtual environment in the project folder:

```powershell
uv venv .venv
```

Sync the reproducible development and test environment from `uv.lock`:

```powershell
uv sync --all-extras --link-mode=copy
```

For CI or strict local checks, require the committed lock file to stay
unchanged:

```powershell
uv sync --all-extras --locked --link-mode=copy
```

This project supports Python `>=3.10`. `uv venv .venv` uses an available
compatible Python. If you need a specific Python version, request it explicitly:

```powershell
uv venv .venv --python 3.12
```

The `uv.lock` file is used by uv for development and CI reproducibility.
`pip install .` reads `pyproject.toml`, not `uv.lock`. Users without uv must
install uv before using the locked environment.

The lock file records the local project as `powers-tool`. Installed command
wrappers are `powers-tool`, `powers-tool-webui`, and
`powers-tool-webui-launcher`; former distribution, package, and command names
are not compatibility aliases.

If you need pip directly, use the virtual environment's Python:

```powershell
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m pip install ".[webui]"
.\.venv\Scripts\python.exe -m pip install -e ".[all,dev]"
```

Windows creates virtualenv console wrappers such as
`.\.venv\Scripts\powers-tool.exe` and
`.\.venv\Scripts\powers-tool-webui.exe`. The WebUI launcher wrapper is
`.\.venv\Scripts\powers-tool-webui-launcher.exe`.

## Build

Build the wheel and source distribution. This uses the `build` package from
the `dev` extra installed above:

```powershell
.\.venv\Scripts\python.exe -m build
```

This produces only one Python distribution:

```text
dist\powers_tool-2.0.0-py3-none-any.whl
dist\powers_tool-2.0.0.tar.gz
```

The Product artifact inspector rejects repository validation scripts, private
fixtures, candidate evidence, and internal-only tests. Normal release
automation builds and copies only these Product wheel and source-distribution
artifacts.

Standalone executables are separate PyInstaller workflows. Prepare the locked
development environment, which includes PyInstaller, before building exe
artifacts:

```powershell
uv sync --all-extras --locked --link-mode=copy
```

Build the standalone CLI and WebUI launcher executables:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_cli_exe.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_webui_exe.ps1
```

By default, these commands produce:

```text
dist\powers-tool.exe
dist\powers-tool-webui.exe
```

The standalone `powers-tool-webui.exe` artifact is distinct from the installed
`powers-tool-webui-launcher` console entry point; both invoke the existing
`powers_tool_webui.launcher:main` launcher implementation where applicable.

Check the built CLI executable without touching hardware:

```powershell
.\dist\powers-tool.exe --version
.\dist\powers-tool.exe doctor --simulate --json
```

Build a release folder with wheel, sdist, standalone executables, and checksums:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

For version 2.0.0, this produces release artifacts named with the selected
project version:

```text
release\<version>\powers-tool-<version>.exe
release\<version>\powers-tool-webui-<version>.exe
release\<version>\powers_tool-<version>-py3-none-any.whl
release\<version>\powers_tool-<version>.tar.gz
release\<version>\checksums.txt
```

Run the final no-hardware release acceptance from a clean, fully committed
source working tree. The script uses the existing `.venv`, checks that the
working tree matches committed HEAD, verifies `uv.lock`, and runs the complete
no-hardware test suite once. It then calls `build_release.ps1` once to produce
the final versioned artifacts, inspects the wheel, sdist, and standalone
executables, installs the final sdist in one clean environment, checks all
console entry points, verifies checksums, runs fast CLI smoke for every
Product-active model, runs deeper CLI workflows for capability-representative
models, and checks a simulator `PlanOnly` contract. A new model needs another
deep representative only when it introduces a capability family or hardware
structure not already represented. The script writes `report.json` and
`summary.md` under the ignored output root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\release-acceptance.ps1
```

If `-OutputRoot` is provided, it must resolve to `.tmp_tests` or one of its
subdirectories within the repository.

This acceptance script never performs VISA discovery, opens a resource, or
sends SCPI. It fails if HEAD or the source working tree changes during the run.
It does not publish a release or rename the repository.

## Test

Pytest uses the ignored repository-local `.tmp_pytest` directory by default,
so no-hardware tests do not depend on access to the Windows system temporary
directory. Run pytest from the repository root. If a specific run needs a
separate basetemp, use `--basetemp .tmp_tests/<purpose>`. Do not write pytest
temporary data or generated test artifacts under `Local/`.

Run focused tests while iterating:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\core -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\cli -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\webui -q -p no:cacheprovider
```

Run the full no-hardware suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
```

For scripted validation, live hardware checks, and release acceptance, see the
[CLI README](docs/cli/README.md#scripted-validation). Hardware validation is
explicit opt-in and requires a user-provided VISA resource.

## Contributing

See [Contributing](docs/CONTRIBUTING.md) for development ownership, no-hardware
test expectations, and the contributor validation-artifact workflow. Changes
to live model, command, transport, or backend support require reviewable
real-instrument evidence when applicable.

## Optional Codex / Agent Skill

The project publishes an optional, manually installed
[Powers Tool CLI Orchestration Skill](docs/skill/README.md) for contract-aware
CLI and Power Worker workflows. It is a companion template, not a Powers Tool
runtime feature, and is not included with Python packages, standalone
executables, builds, releases, or CI.

## Documentation

- [Core README](docs/core/README.md)
- [Supported Models](docs/core/supported-models.md)
- [CLI User Guide](docs/cli/USER_GUIDE.md)
- [CLI README](docs/cli/README.md)
- [WebUI README](docs/webui/README.md)
- [WebUI User Guide](docs/webui/USER_GUIDE.md)
- [WebUI Change Rules](docs/webui/web-ui-change-rules.md)
- [Repository Layout](docs/architecture/monorepo-layout.md)
- [Testing Guidelines](docs/testing-guidelines.md)
- [Public Contracts](docs/contracts)
- [Power CLI JSONL Contract](docs/contracts/power-cli-jsonl-contract.md)
- [Power Worker Contract](docs/contracts/power-worker-contract.md)
- [Optional Codex / Agent Skill](docs/skill/README.md)

## License and Disclaimer

This project is licensed under the MIT License. See [LICENSE](LICENSE).

This project is independent and unofficial. It is not affiliated with,
endorsed by, or sponsored by Keysight Technologies.

Users are responsible for complying with all applicable Keysight software,
driver, instrument, and documentation license terms.
