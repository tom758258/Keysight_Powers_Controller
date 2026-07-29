from __future__ import annotations

import importlib
import io
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
from uuid import uuid4
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release-acceptance.ps1"
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
        for filename in ("index.html", "styles.css", "app.js"):
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
        for filename in ("index.html", "styles.css", "app.js"):
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
                for filename in ("index.html", "styles.css", "app.js")
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


def test_release_acceptance_uses_one_release_artifact_flow() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert text.count("scripts\\build_release.ps1") == 1
    assert text.count('"pytest-full-no-hardware"') == 1
    assert "tests\\packaging\\inspect_distribution.py" not in text
    assert text.count("tests\\packaging\\inspect_pyinstaller.py") == 1
    for required in (
        '"lock", "--check"',
        '"install-final-sdist"',
        '"preflight-cli-all"',
        '"-Target", "all"',
        '"live-cli-plan-only"',
        '"-PlanOnly"',
        '"git-diff-check"',
        "HEAD changed during release acceptance",
    ):
        assert required in text

    for removed in (
        "Python310",
        "CurrentPython",
        "InterpreterPreflightOnly",
        "KeepWorktree",
        "build_cli_exe.ps1",
        "build_webui_exe.ps1",
        "test_packaging_identity.py",
        "pytest-focused",
        "worktree add",
        "build-wheel-from-sdist",
    ):
        assert removed not in text


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


def test_console_entry_point_smoke_is_not_recorded_as_python() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    entry_points = text.split("function Test-InstalledEntryPoints {", 1)[1].split(
        "\ntry {", 1
    )[0]

    assert entry_points.count("Invoke-Recorded") == 2
    assert "-Python" not in entry_points


def test_release_acceptance_passes_project_version_to_standalone_inspector() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    pattern = (
        r'"tests\\packaging\\inspect_pyinstaller\.py".{0,160}'
        r'"--expected-version", \$projectVersion'
    )
    assert re.search(pattern, text, flags=re.DOTALL)


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
