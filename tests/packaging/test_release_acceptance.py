from __future__ import annotations

import importlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
from uuid import uuid4
import zipfile

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release-acceptance.ps1"
BUILD_RELEASE = ROOT / "scripts" / "build_release.ps1"
BUILD_DESKTOP = ROOT / "scripts" / "build_desktop.ps1"
DESKTOP_PACKAGE = ROOT / "desktop" / "package.json"
PACKAGING_DIR = ROOT / "tests" / "packaging"

if str(PACKAGING_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGING_DIR))

inspect_pyinstaller = importlib.import_module("inspect_pyinstaller")
inspector_utils = importlib.import_module("_inspector_utils")


def _write_distribution_fixture(
    dist_dir: Path,
    *,
    artifact_version: str,
    metadata_version: str | None = None,
    sdist_root_version: str | None = None,
    include_sdist: bool = True,
) -> None:
    dist_dir.mkdir(parents=True, exist_ok=True)
    metadata_version = metadata_version or artifact_version
    dist_info = f"powers_tool-{artifact_version}.dist-info"
    wheel = dist_dir / f"powers_tool-{artifact_version}-py3-none-any.whl"
    metadata = (
        "Metadata-Version: 2.4\n"
        "Name: powers-tool\n"
        f"Version: {metadata_version}\n"
        "Requires-Python: >=3.10\n"
    )
    entry_points = (
        "[console_scripts]\n"
        "powers-tool = powers_tool_cli.cli:main\n"
        "powers-tool-webui = powers_tool_webui.server:main\n"
        "powers-tool-webui-launcher = powers_tool_webui.launcher:main\n"
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"{dist_info}/METADATA", metadata)
        archive.writestr(f"{dist_info}/entry_points.txt", entry_points)
        for package in ("powers_tool_core", "powers_tool_cli", "powers_tool_webui"):
            archive.writestr(f"{package}/__init__.py", "")
        archive.writestr(
            "powers_tool_core/build_profile.py",
            "PRODUCT_BUILD_IDENTITY = ProductBuildIdentity(profile=BuildProfile.PRODUCT)\n",
        )
        for filename in (
            "index.html",
            "styles.css",
            "app.js",
            "help/webui.html",
            "help/webui.zh-TW.html",
            "help/supported-models.html",
            "help/supported-models.zh-TW.html",
            "help/help.css",
        ):
            archive.writestr(f"powers_tool_webui/static/{filename}", filename)

    if not include_sdist:
        return
    root = f"powers_tool-{sdist_root_version or artifact_version}"
    with tarfile.open(dist_dir / f"powers_tool-{artifact_version}.tar.gz", "w:gz") as archive:
        for package in ("powers_tool_core", "powers_tool_cli", "powers_tool_webui"):
            _add_tar_text(archive, f"{root}/src/{package}/__init__.py", "")
        _add_tar_text(
            archive,
            f"{root}/src/powers_tool_core/build_profile.py",
            "PRODUCT_BUILD_IDENTITY = ProductBuildIdentity(profile=BuildProfile.PRODUCT)\n",
        )
        for filename in (
            "index.html",
            "styles.css",
            "app.js",
            "help/webui.html",
            "help/webui.zh-TW.html",
            "help/supported-models.html",
            "help/supported-models.zh-TW.html",
            "help/help.css",
        ):
            _add_tar_text(
                archive,
                f"{root}/src/powers_tool_webui/static/{filename}",
                filename,
            )


def _add_tar_text(archive: tarfile.TarFile, name: str, text: str) -> None:
    payload = text.encode("utf-8")
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def _run_distribution_inspector(
    dist_dir: Path, *arguments: str, inspector: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            sys.executable,
            str(inspector or PACKAGING_DIR / "inspect_distribution.py"),
            *arguments,
            str(dist_dir),
        ],
        cwd=ROOT,
        check=False,
    )


class _FakePyz:
    def __init__(self, names: set[str]) -> None:
        self.toc = names


class _FakeCArchive:
    def __init__(
        self,
        *,
        version: str,
        extra_metadata_versions: tuple[str, ...] = (),
        pyz_names: set[str] | None = None,
        webui_assets: bool = True,
    ) -> None:
        self.metadata = {
            f"powers_tool-{item}.dist-info/METADATA": (
                f"Name: powers-tool\nVersion: {item}\n".encode("utf-8")
            )
            for item in (version, *extra_metadata_versions)
        }
        names = [*self.metadata, "PYZ.pyz"]
        if webui_assets:
            names.extend(
                f"powers_tool_webui/static/{filename}"
                for filename in (
                    "index.html",
                    "styles.css",
                    "app.js",
                    "help/webui.html",
                    "help/webui.zh-TW.html",
                    "help/supported-models.html",
                    "help/supported-models.zh-TW.html",
                    "help/help.css",
                )
            )
        self.toc = {name: None for name in names}
        self.pyz_names = pyz_names or {
            "powers_tool_core",
            "powers_tool_core.driver",
            "powers_tool_cli",
            "powers_tool_cli.cli",
            "powers_tool_webui",
            "powers_tool_webui.server",
        }

    def extract(self, name: str) -> bytes:
        return self.metadata[name]

    def open_embedded_archive(self, name: str) -> _FakePyz:
        assert name == "PYZ.pyz"
        return _FakePyz(self.pyz_names)


def _run(
    command: list[str],
    *,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _powershell() -> str:
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.skip(
            "Windows PowerShell is required for acceptance-script behavior tests"
        )
    return executable


def _make_acceptance_repository(request: pytest.FixtureRequest) -> Path:
    fixture_id = uuid4().hex
    repository = ROOT / ".tmp_tests" / "release_dirty_repo" / fixture_id
    git_directory = ROOT / ".tmp_tests" / "release_dirty_git" / fixture_id
    repository.mkdir(parents=True)
    git_directory.parent.mkdir(parents=True, exist_ok=True)
    request.addfinalizer(lambda: shutil.rmtree(repository, ignore_errors=True))
    request.addfinalizer(lambda: shutil.rmtree(git_directory, ignore_errors=True))
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    shutil.copy2(
        ROOT / "scripts" / "_validation_helpers.ps1",
        scripts / "_validation_helpers.ps1",
    )
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "powers-tool"\nversion = "3.4.5"\n',
        encoding="utf-8",
    )
    (repository / "README.md").write_text("preflight fixture\n", encoding="utf-8")
    _run(
        [
            "git",
            "-c",
            "core.longpaths=true",
            "init",
            f"--separate-git-dir={git_directory}",
            "-b",
            "main",
        ],
        cwd=repository,
    )
    _run(["git", "config", "core.longpaths", "true"], cwd=repository)
    _run(["git", "config", "user.email", "release-tests@example.invalid"], cwd=repository)
    _run(["git", "config", "user.name", "Release Tests"], cwd=repository)
    _run(["git", "add", "."], cwd=repository)
    _run(["git", "commit", "-m", "preflight fixture"], cwd=repository)
    return repository


def test_dirty_repository_fails_before_creating_acceptance_output(
    request: pytest.FixtureRequest,
) -> None:
    repository = _make_acceptance_repository(request)
    (repository / "README.md").write_text("dirty change\n", encoding="utf-8")
    output_root = repository / ".tmp_tests" / "release_acceptance"
    result = _run(
        [
            _powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(repository / "scripts" / SCRIPT.name),
        ],
        cwd=repository,
        check=False,
    )

    assert result.returncode == 1
    assert "requires a clean source worktree" in " ".join(
        (result.stdout + result.stderr).split()
    )
    assert not output_root.exists()


def test_output_root_accepts_absolute_path_under_tmp_tests(
    request: pytest.FixtureRequest,
) -> None:
    repository = _make_acceptance_repository(request)
    output_root = repository / ".tmp_tests" / "accepted_release"
    result = _run(
        [
            _powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(repository / "scripts" / SCRIPT.name),
            "-OutputRoot", str(output_root),
        ],
        cwd=repository,
        check=False,
    )

    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode == 1
    assert output_root.is_dir()
    assert "Missing required artifact" in output
    assert "must stay under the repository .tmp_tests directory" not in output


@pytest.mark.parametrize(
    "relative_output",
    [Path(".git") / "release_acceptance", Path("dist") / "release_acceptance"],
)
def test_output_root_rejects_paths_outside_tmp_tests_without_creating_them(
    request: pytest.FixtureRequest,
    relative_output: Path,
) -> None:
    repository = _make_acceptance_repository(request)
    output_root = repository / relative_output
    result = _run(
        [
            _powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(repository / "scripts" / SCRIPT.name),
            "-OutputRoot", str(relative_output),
        ],
        cwd=repository,
        check=False,
    )

    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode == 1
    assert "must stay under the repository .tmp_tests directory" in output
    assert not output_root.exists()
    assert not (repository / ".tmp_tests").exists()


def test_release_acceptance_preserves_required_no_hardware_release_flow() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    for required in (
        "scripts\\build_release.ps1",
        '"pytest-full-no-hardware"',
        '"extract unified Windows bundle"',
        '"resources\\backend"',
        '"lock", "--check"',
        '"install-final-sdist"',
        '"live-cli-plan-only"',
        '"-PlanOnly"',
        '"-SkipExternalPreflight"',
        '"git-diff-check"',
        "HEAD changed during release acceptance",
    ):
        assert required in text

    assert re.search(
        r'"scripts\\preflight-cli\.ps1"\),\s*'
        r'"-Target", "all",\s*'
        r'"-Suite", "smoke"',
        text,
    )
    assert re.search(
        r'"scripts\\preflight-cli\.ps1"\),\s*'
        r'"-Target", "all",\s*'
        r'"-Suite", "deep"',
        text,
    )
    smoke_position = text.index('"preflight-cli-all-smoke"')
    deep_position = text.index('"preflight-cli-deep-representatives"')
    plan_only_position = text.index('"live-cli-plan-only"')
    skip_position = text.index('"-SkipExternalPreflight"')
    assert smoke_position < deep_position < plan_only_position < skip_position


def test_release_acceptance_reports_recorded_command_status() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    helper = text.split("function Invoke-Recorded", 1)[1].split(
        "function Get-PythonMetadata", 1
    )[0]
    start_position = helper.index("[start]")
    assert start_position < helper.index("Start-Process -FilePath")
    assert start_position < helper.index("& $FilePath @Arguments")
    assert "[passed]" in helper
    assert "[failed]" in helper
    assert "duration=" in helper
    assert ".TotalSeconds" in helper
    assert "InvariantCulture" in helper
    assert helper.count("[failed]") == 1
    for field in ("exit_code = $exitCode", "duration_ms =", "output_tail = $output"):
        assert field in helper


def test_release_acceptance_does_not_invoke_itself() -> None:
    assert "release-acceptance.ps1" not in SCRIPT.read_text(encoding="utf-8")


def test_cleanup_preserves_an_existing_primary_failure() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    cleanup = text.rsplit("finally {", 1)[1].split(
        "if ($script:RunRoot)", 1
    )[0]

    assert "if ($script:FailedStep)" in cleanup
    assert 'Cleanup also failed: $cleanupFailure' in cleanup
    assert re.search(
        r"if \(\$script:FailedStep\).*?"
        r"Cleanup also failed: \$cleanupFailure.*?"
        r"else \{.*?"
        r'\$script:FailedStep = "clean generated build directories"',
        cleanup,
        flags=re.DOTALL,
    )


def test_console_entry_point_help_smoke_uses_stable_usage_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "'(?im)^usage:\\s*'" in text
    assert "IsNullOrWhiteSpace" in text
    for brittle_description in (
        "Safe Powers Tool CLI for supported DC power supplies.",
        "Powers Tool WebUI Server",
        "Powers Tool WebUI Launcher",
    ):
        assert brittle_description not in text


def test_release_acceptance_validates_unified_desktop_bundle() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    for required in (
        '"powers-tool-$projectVersion-windows-x64.zip"',
        '"Powers Tool.exe"',
        '"powers-tool.exe"',
        '"powers-tool-webui-launcher.exe"',
        '"powers-tool-webui-host.exe"',
        '"_internal"',
        '"resources"',
        '"*-portable.exe"',
        "exactly one _internal directory",
        "_internal directory must be at the application root",
        'Join-Path $extractedBundleDir "resources\\backend"',
        '"packaged-cli-version"',
        '"packaged-webui-launcher-version"',
        '$releaseEntries = @(Get-ChildItem -LiteralPath $versionDir -Force)',
        '$_.PSIsContainer -or',
        '$_.Name -notin $expectedRelease',
        '$releaseEntries.Count -eq $expectedRelease.Count',
        '$invalidEntries.Count -eq 0',
        '$windowsBundleZip = Get-Item -LiteralPath (',
        'Join-Path $versionDir "powers-tool-$projectVersion-windows-x64.zip"',
    ):
        assert required in text

    artifact_check = text.split(
        '$script:CurrentStep = "final release artifact checks"', 1
    )[1].split("$windowsBundleZip", 1)[0]
    assert "Get-ChildItem -LiteralPath $versionDir -File" not in artifact_check
    assert text.index("$releaseEntries = @(") < text.index(
        "$invalidEntries = @("
    ) < text.index('Name "versioned release folder contents"')
    assert text.index("$windowsBundleZip = Get-Item") < text.index(
        "Expand-Archive -LiteralPath $windowsBundleZip.FullName"
    )
    assert "inspect_pyinstaller.py" not in text


def test_desktop_package_matches_canonical_version_and_uses_directory_builder() -> None:
    package = json.loads(DESKTOP_PACKAGE.read_text(encoding="utf-8"))
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    package_lock = json.loads(
        (DESKTOP_PACKAGE.parent / "package-lock.json").read_text(encoding="utf-8")
    )
    canonical_version = project["version"]

    assert package["version"] == canonical_version
    assert package_lock["version"] == canonical_version
    assert package_lock["packages"][""]["version"] == canonical_version
    assert package["scripts"]["dist:win"] == "electron-builder --dir --win --x64"
    assert package["build"]["directories"]["output"] == "../dist/desktop"
    assert package["build"]["files"] == ["main.cjs"]
    assert package["build"]["win"]["icon"] == "assets/powers-icon.ico"
    assert "electron-builder" in package["devDependencies"]
    assert "portable" not in package


def test_desktop_builder_merges_existing_shared_bundle() -> None:
    text = BUILD_DESKTOP.read_text(encoding="utf-8")

    for required in (
        "build_windows_bundle.ps1",
        "-DistPath $DistRoot",
        '"win-unpacked"',
        '"Powers Tool.exe"',
        '"powers-tool.exe"',
        '"powers-tool-webui-launcher.exe"',
        '"powers-tool-webui-host.exe"',
        '"resources"',
        "contain exactly one _internal directory",
        '"resources\\backend"',
        '"*-portable.exe"',
    ):
        assert required in text


def test_release_builder_creates_unified_top_level_artifacts() -> None:
    text = BUILD_RELEASE.read_text(encoding="utf-8")

    for required in (
        '"build_desktop.ps1"',
        '"powers-tool-$Version-windows-x64.zip"',
        '"powers_tool-$Version-py3-none-any.whl"',
        '"powers_tool-$Version.tar.gz"',
        '"powers-tool-$Version"',
        "Compress-Archive",
        "$expectedArtifactNames",
        '"checksums.txt"',
    ):
        assert required in text

    assert "build_cli_exe.ps1" not in text
    assert "build_webui_exe.ps1" not in text
    assert not (ROOT / "scripts" / "build_cli_exe.ps1").exists()
    assert not (ROOT / "scripts" / "build_webui_exe.ps1").exists()


def test_distribution_inspector_accepts_matching_explicit_future_version(
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    _write_distribution_fixture(dist_dir, artifact_version="3.4.5")

    result = _run_distribution_inspector(
        dist_dir, "--expected-version", "3.4.5"
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_distribution_inspector_rejects_mismatching_metadata(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    _write_distribution_fixture(
        dist_dir, artifact_version="3.4.5", metadata_version="2.0.0"
    )

    result = _run_distribution_inspector(
        dist_dir, "--expected-version", "3.4.5"
    )

    assert result.returncode != 0
    assert "expected wheel metadata version '3.4.5'" in result.stderr
    assert "Version: 2.0.0" in result.stderr


def test_distribution_inspector_rejects_mismatching_artifact_filenames(
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    _write_distribution_fixture(dist_dir, artifact_version="2.0.0")

    result = _run_distribution_inspector(
        dist_dir, "--expected-version", "3.4.5"
    )

    assert result.returncode != 0
    assert "expected wheel filename 'powers_tool-3.4.5-py3-none-any.whl'" in result.stderr
    assert "powers_tool-2.0.0-py3-none-any.whl" in result.stderr


def test_distribution_inspector_rejects_mismatching_sdist_filename(
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    _write_distribution_fixture(dist_dir, artifact_version="3.4.5")
    (dist_dir / "powers_tool-3.4.5.tar.gz").rename(
        dist_dir / "powers_tool-2.0.0.tar.gz"
    )

    result = _run_distribution_inspector(
        dist_dir, "--expected-version", "3.4.5"
    )

    assert result.returncode != 0
    assert "expected sdist filename 'powers_tool-3.4.5.tar.gz'" in result.stderr
    assert "powers_tool-2.0.0.tar.gz" in result.stderr


def test_distribution_inspector_rejects_mismatching_sdist_root(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    _write_distribution_fixture(
        dist_dir, artifact_version="3.4.5", sdist_root_version="2.0.0"
    )

    result = _run_distribution_inspector(
        dist_dir, "--expected-version", "3.4.5"
    )

    assert result.returncode != 0
    assert "expected sdist root 'powers_tool-3.4.5'" in result.stderr
    assert "powers_tool-2.0.0" in result.stderr


def test_distribution_inspector_wheel_only_accepts_explicit_version(
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    _write_distribution_fixture(
        dist_dir, artifact_version="3.4.5", include_sdist=False
    )

    result = _run_distribution_inspector(
        dist_dir, "--wheel-only", "--expected-version", "3.4.5"
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_inspectors_resolve_future_version_from_fixture_pyproject(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    packaging = repository / "tests" / "packaging"
    packaging.mkdir(parents=True)
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "powers-tool"\nversion = "3.4.5"\n', encoding="utf-8"
    )
    for name in ("_inspector_utils.py", "inspect_distribution.py"):
        shutil.copy2(PACKAGING_DIR / name, packaging / name)
    dist_dir = repository / "dist"
    _write_distribution_fixture(dist_dir, artifact_version="3.4.5")

    result = _run_distribution_inspector(
        dist_dir, inspector=packaging / "inspect_distribution.py"
    )
    resolved = inspector_utils.resolve_expected_version(
        None, inspector_file=packaging / "inspect_pyinstaller.py"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert resolved == "3.4.5"
    archive = _FakeCArchive(version=resolved)
    inspect_pyinstaller._validate_metadata(
        archive,
        {name: name for name in archive.toc},
        expected_version=resolved,
    )


def test_pyinstaller_inspector_accepts_matching_future_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _FakeCArchive(version="3.4.5")
    monkeypatch.setattr(inspect_pyinstaller, "CArchiveReader", lambda path: archive)

    inspect_pyinstaller.inspect_executable(
        Path("future.exe"),
        ("powers_tool_core", "powers_tool_webui"),
        webui=True,
        expected_version="3.4.5",
    )


def test_pyinstaller_cli_accepts_explicit_and_canonical_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future_archive = _FakeCArchive(version="3.4.5")
    monkeypatch.setattr(
        inspect_pyinstaller, "CArchiveReader", lambda path: future_archive
    )
    assert (
        inspect_pyinstaller.main(
            ["--expected-version", "3.4.5", "cli.exe", "webui.exe"]
        )
        == 0
    )

    canonical_version = inspector_utils.resolve_expected_version(
        None, inspector_file=PACKAGING_DIR / "inspect_pyinstaller.py"
    )
    canonical_archive = _FakeCArchive(version=canonical_version)
    monkeypatch.setattr(
        inspect_pyinstaller, "CArchiveReader", lambda path: canonical_archive
    )
    assert inspect_pyinstaller.main(["cli.exe", "webui.exe"]) == 0


def test_pyinstaller_inspector_rejects_stale_metadata_version() -> None:
    archive = _FakeCArchive(version="2.0.0")

    with pytest.raises(AssertionError) as error:
        inspect_pyinstaller._validate_metadata(
            archive,
            {name: name for name in archive.toc},
            expected_version="3.4.5",
        )

    assert "powers_tool-3.4.5.dist-info/METADATA" in str(error.value)
    assert "powers_tool-2.0.0.dist-info/METADATA" in str(error.value)


def test_pyinstaller_inspector_rejects_competing_metadata_version() -> None:
    archive = _FakeCArchive(
        version="3.4.5", extra_metadata_versions=("2.0.0",)
    )

    with pytest.raises(AssertionError) as error:
        inspect_pyinstaller._validate_metadata(
            archive,
            {name: name for name in archive.toc},
            expected_version="3.4.5",
        )

    assert "powers_tool-3.4.5.dist-info/METADATA" in str(error.value)
    assert "powers_tool-2.0.0.dist-info/METADATA" in str(error.value)


def test_pyinstaller_inspector_retains_package_webui_and_legacy_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_package = _FakeCArchive(
        version="3.4.5", pyz_names={"powers_tool_core", "powers_tool_core.driver"}
    )
    monkeypatch.setattr(
        inspect_pyinstaller, "CArchiveReader", lambda path: missing_package
    )
    with pytest.raises(AssertionError, match="powers_tool_cli"):
        inspect_pyinstaller.inspect_executable(
            Path("missing-package.exe"),
            ("powers_tool_core", "powers_tool_cli"),
            webui=False,
            expected_version="3.4.5",
        )

    missing_assets = _FakeCArchive(version="3.4.5", webui_assets=False)
    monkeypatch.setattr(
        inspect_pyinstaller, "CArchiveReader", lambda path: missing_assets
    )
    with pytest.raises(AssertionError, match="index.html"):
        inspect_pyinstaller.inspect_executable(
            Path("missing-assets.exe"),
            ("powers_tool_core", "powers_tool_webui"),
            webui=True,
            expected_version="3.4.5",
        )

    legacy = _FakeCArchive(
        version="3.4.5",
        pyz_names={
            "powers_tool_core",
            "powers_tool_core.driver",
            "keysight_power_core",
        },
    )
    monkeypatch.setattr(inspect_pyinstaller, "CArchiveReader", lambda path: legacy)
    with pytest.raises(AssertionError):
        inspect_pyinstaller.inspect_executable(
            Path("legacy.exe"),
            ("powers_tool_core",),
            webui=False,
            expected_version="3.4.5",
        )
