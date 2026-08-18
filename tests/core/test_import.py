import ast
import importlib.util
from pathlib import Path
import runpy


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "src"
CORE_SOURCE_ROOT = SOURCE_ROOT / "powers_tool_core"
ADAPTER_PACKAGE_ROOTS = frozenset({"powers_tool_cli", "powers_tool_webui"})


def _resolve_import_from(path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module

    package_parts = path.relative_to(SOURCE_ROOT).with_suffix("").parts[:-1]
    if node.level > len(package_parts):
        return None
    base_parts = package_parts[: len(package_parts) - node.level + 1]
    if node.module is None:
        return ".".join(base_parts)
    return ".".join((*base_parts, *node.module.split(".")))


def _core_adapter_import_violations() -> list[tuple[str, int, str]]:
    violations: list[tuple[str, int, str]] = []
    for path in sorted(CORE_SOURCE_ROOT.rglob("*.py"), key=lambda candidate: candidate.as_posix()):
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets = (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                target = _resolve_import_from(path, node)
                targets = () if target is None else (target,)
            else:
                continue
            for target in targets:
                if target.split(".", 1)[0] in ADAPTER_PACKAGE_ROOTS:
                    violations.append((relative_path, node.lineno, target))
    return sorted(violations)


def test_package_imports() -> None:
    from importlib import metadata

    import powers_tool_core

    assert powers_tool_core.__version__ == metadata.version("powers-tool")


def test_old_core_namespace_is_absent_without_compatibility_shim() -> None:
    old_namespace = "keysight" + "_power_core"

    assert not Path("src", old_namespace).exists()
    assert importlib.util.find_spec(old_namespace) is None


def test_package_discovery_uses_only_the_new_core_namespace() -> None:
    metadata = Path("pyproject.toml").read_text(encoding="utf-8")

    assert '"powers_tool_core*"' in metadata
    assert f'"{"keysight" + "_power_core"}*"' not in metadata


def test_core_source_does_not_import_cli_or_webui_adapters() -> None:
    violations = _core_adapter_import_violations()

    assert not violations, "\n".join(
        [
            "Core must not import CLI or WebUI adapters.",
            *(
                f"{path}:{line}: imports {target} "
                "(violates Core-to-adapter import rule)"
                for path, line, target in violations
            ),
        ]
    )


def test_core_missing_distribution_metadata_uses_nonrelease_fallback(monkeypatch) -> None:
    from importlib import metadata

    def missing_distribution(_name: str) -> str:
        raise metadata.PackageNotFoundError("powers-tool")

    monkeypatch.setattr(metadata, "version", missing_distribution)
    namespace = runpy.run_path("src/powers_tool_core/__init__.py")
    source = Path("src/powers_tool_core/__init__.py").read_text(encoding="utf-8")

    assert namespace["__version__"] == "0+unknown"
    assert "powers_tool_cli" not in source
    assert "powers_tool_webui" not in source
