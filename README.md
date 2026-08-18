[繁體中文](README.zh-TW.md)

# Powers Tool

Powers Tool is a vendor-neutral Python toolkit for controlling supported DC
power supplies. It provides one installable distribution,
`powers-tool`, with three import packages: `powers_tool_core`,
`powers_tool_cli`, and `powers_tool_webui`.

The framework is vendor-neutral, but current Product support is limited to
the registered and documented model scopes in
[Supported Models](docs/core/supported-models.md). Vendor-neutral architecture
does not mean arbitrary or unknown power supplies are supported: unregistered
or unresolved live hardware fails closed.
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

**Live hardware prerequisite:** Live hardware operation requires a separately
installed VISA implementation/runtime that PyVISA can load. The `powers-tool`
distribution installs PyVISA, but PyVISA is the Python API layer rather than a
complete system or vendor VISA runtime. Powers Tool does not bundle Keysight IO
Libraries Suite, NI-VISA, or another vendor/system VISA runtime. Simulator,
dry-run, and normal no-hardware validation do not require a physical instrument
or vendor VISA runtime. Installing a VISA runtime does not expand support:
live operation remains limited to the exact model, command, transport, backend,
and required-feature scopes in [Supported Models](docs/core/supported-models.md).

## Features

- Control supported DC power supplies over USB, LAN, or explicit
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

The lock file records the local project as `powers-tool`. Installed command
wrappers are `powers-tool`, `powers-tool-webui`, and
`powers-tool-webui-launcher`; former distribution, package, and command names
are not compatibility aliases.

Windows creates virtualenv console wrappers such as
`.\.venv\Scripts\powers-tool.exe` and
`.\.venv\Scripts\powers-tool-webui.exe`. The WebUI launcher wrapper is
`.\.venv\Scripts\powers-tool-webui-launcher.exe`.

Normal setup only requires the existing `uv sync` workflow. If sync succeeds but
one of these wrappers is missing or has not been updated, run this from the
repository root to force uv to reinstall the `powers-tool` distribution and
recreate the project console wrappers:

```powershell
uv sync --all-extras --link-mode=copy --reinstall-package powers-tool
```

After installation, use the [CLI Quick Start](docs/cli/README.md#quick-start)
for a safe no-hardware check, or see the
[WebUI User Guide](docs/webui/USER_GUIDE.md) to start the local browser
interface.

## Quick Start

These entry points are safe no-hardware or local-only checks. They do not
discover VISA resources or enable instrument output.

Run a simulator CLI smoke:

```powershell
uv run powers-tool doctor --simulate --json
```

Start the local WebUI launcher:

```powershell
uv run powers-tool-webui-launcher
```

Start the source-mode Electron Desktop shell:

```powershell
Set-Location .\desktop
npm ci
npm start
```

For detailed CLI operation, see the [CLI README](docs/cli/README.md). For
browser and Desktop usage, see the [WebUI User Guide](docs/webui/USER_GUIDE.md).

## Build

Build the wheel and source distribution. This uses the `build` package from
the `dev` extra installed above:

```powershell
.\.venv\Scripts\python.exe -m build
```

This produces only one Python distribution:

```text
dist\powers_tool-<version>-py3-none-any.whl
dist\powers_tool-<version>.tar.gz
```

The Product distribution inspector rejects repository validation scripts,
private fixtures, candidate evidence, and internal-only tests. It validates the
Python wheel and source distribution; the Desktop application is assembled
separately for the Windows ZIP.

Prepare the locked development environment, which includes PyInstaller, before
building Windows application artifacts:

```powershell
uv sync --all-extras --locked --link-mode=copy
```

Build the shared Windows onedir bundle containing the CLI, WebUI launcher, and
private Desktop Host:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows_bundle.ps1
```

The Windows WebUI Launcher uses Tkinter, so the Python environment used to
build the shared Windows bundle must provide a working Tcl/Tk runtime. The
build script checks this prerequisite before starting PyInstaller.

By default, this command produces one shared Python application directory with
three executables and one shared supporting-files directory:

```text
dist\powers-tool\
  powers-tool.exe
  powers-tool-webui-launcher.exe
  powers-tool-webui-host.exe
  _internal\
```

The local `powers-tool-webui-launcher.exe` artifact is distinct from the
installed `powers-tool-webui-launcher` console entry point; both invoke the
existing `powers_tool_webui.launcher:main` launcher implementation. The
`powers-tool-webui-host.exe` artifact is a private console executable for the
Desktop shell, not a new public CLI entry point. All three executables share
the same `_internal` directory.

The source-mode Desktop shell is the existing WebUI presented in Electron; it
does not create a second WebUI implementation. From the repository root:

```powershell
Set-Location .\desktop
npm ci
npm start
```

The shell starts the private WebUI Host, opens a 1920x1080 window clamped to
the primary display work area, and supports System, Light, and Dark themes.
The selected theme applies to the main panels, cards, fields, and status
surfaces, not only the page background.
Dark theme keeps primary controls, status text, and unavailable or disabled
controls visually distinguishable against dark surfaces.
Multiple Desktop instances are allowed, so separate instances can operate
different physical instruments. Do not use different clients concurrently on
the same physical instrument resource.

Build the Electron Windows directory application, including the shared Python
bundle:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1
```

The resulting application directory contains `Powers Tool.exe`, the three
Python executables, Electron runtime files, and one shared root `_internal`
directory. The formal Windows release uses the same application directory in a
versioned ZIP.

Check the built CLI executable without touching hardware:

```powershell
.\dist\powers-tool\powers-tool.exe --version
.\dist\powers-tool\powers-tool.exe doctor --simulate --json
```

Build the versioned Python distributions and unified Desktop Windows ZIP:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

This produces artifacts named with the selected project version:

```text
release\<version>\powers-tool-<version>-windows-x64.zip
release\<version>\powers_tool-<version>-py3-none-any.whl
release\<version>\powers_tool-<version>.tar.gz
release\<version>\checksums.txt
```

The ZIP contains one `powers-tool-<version>\` application root with the
Electron shell, CLI, WebUI launcher, private WebUI Host, Electron runtime
files, and the shared `_internal\` directory. `checksums.txt` hashes the ZIP,
wheel, and sdist only.

Run the final no-hardware release acceptance from a clean, fully committed
source working tree. The script uses the existing `.venv`, checks that the
working tree matches committed HEAD, verifies `uv.lock`, and runs the complete
no-hardware test suite once. It then calls `build_release.ps1` once to produce
the final versioned artifacts, inspects the wheel, sdist, and unified Desktop
ZIP, installs the final sdist in one clean environment, checks all
console entry points, verifies checksums, runs fast CLI smoke for every
Product-active model, runs deeper CLI workflows for capability-representative
models, and checks a simulator `PlanOnly` contract. A new model needs another
deep representative only when it introduces a capability family or hardware
structure not already represented. The script writes `report.json` and
`summary.md` under the ignored output root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\release-acceptance.ps1
```

For each recorded command, it prints a `[start]` line followed by a `[passed]`
or `[failed]` line with `duration=<seconds>s`. Child-process stdout/stderr
remains collected after the command completes and is printed or written to the
acceptance output; it is not streamed line by line.

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

Run the static checks used by CI:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
```

Run the fast no-hardware suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --ignore=tests\cli\test_cli_wrappers.py --ignore=tests\packaging\test_release_acceptance.py
```

CI also checks tracked WebUI JavaScript syntax, runs the focused WebUI Node
runtime tests, builds the Python package on Linux and Windows, and runs package
import plus CLI, WebUI, and Launcher smokes. The Windows Python 3.13 job also
builds the Desktop directory. Wrapper contracts run in a separate Windows job.
The complete `release-acceptance.ps1` gate, distribution inspection, and release
acceptance tests remain release validation rather than ordinary pull-request CI.

For scripted validation, live hardware checks, and release acceptance, see the
[CLI README](docs/cli/README.md#scripted-validation). Hardware validation is
explicit opt-in and requires a user-provided VISA resource.

## Codex / Agent Skill

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

## Contributing

See [Contributing](docs/CONTRIBUTING.md) for development ownership, no-hardware
test expectations, and the contributor validation-artifact workflow. Changes
to live model, command, transport, or backend support require reviewable
real-instrument evidence when applicable.

## License and Disclaimer

This project is licensed under the MIT License. See [LICENSE](LICENSE).

This project is independent and unofficial. It is not affiliated with,
endorsed by, or sponsored by supported instrument manufacturers or vendors.

Users are responsible for complying with applicable software, driver,
instrument, and documentation license terms from those vendors.
