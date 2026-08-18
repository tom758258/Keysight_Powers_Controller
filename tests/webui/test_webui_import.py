from importlib import metadata
from pathlib import Path
import runpy
import sys
import types

import pytest


def test_webui_import() -> None:
    import powers_tool_webui

    assert powers_tool_webui.__version__ == metadata.version("powers-tool")


def test_webui_missing_distribution_metadata_uses_nonrelease_fallback(monkeypatch) -> None:
    def missing_distribution(_name: str) -> str:
        raise metadata.PackageNotFoundError("powers-tool")

    monkeypatch.setattr(metadata, "version", missing_distribution)
    package_init = Path("src/powers_tool_webui/__init__.py")
    namespace = runpy.run_path(str(package_init))

    assert namespace["__version__"] == "0+unknown"


def test_webui_server_version_prints_without_starting_server(monkeypatch, capsys) -> None:
    from powers_tool_webui import server

    def fail_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "uvicorn":
            raise AssertionError("uvicorn should not be imported for --version")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    with pytest.raises(SystemExit) as excinfo:
        server.main(["--version"])

    captured = capsys.readouterr()

    assert excinfo.value.code == 0
    assert captured.out.strip() == f"powers-tool-webui {server.WEBUI_VERSION}"
    assert captured.err == ""


def test_webui_server_defaults_to_port_7999(monkeypatch, capsys) -> None:
    from powers_tool_webui import app, server

    run_args: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> None:
        run_args["args"] = args
        run_args["kwargs"] = kwargs

    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        types.SimpleNamespace(run=fake_run),
    )

    assert server.main([]) == 0

    captured = capsys.readouterr()

    assert captured.out.strip() == "Starting Powers Tool WebUI on http://127.0.0.1:7999"
    assert run_args == {
        "args": (app.app,),
        "kwargs": {"host": "127.0.0.1", "port": 7999, "reload": False},
    }
