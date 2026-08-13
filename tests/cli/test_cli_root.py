import powers_tool_cli.cli as cli
def test_root_version_prints_package_version(capsys) -> None:
    assert cli.main(["--version"]) == 0

    captured = capsys.readouterr()

    assert captured.out.strip() == f"powers-tool {cli._package_version()}"
    assert captured.err == ""

def test_root_help_uses_vendor_neutral_product_identity(capsys) -> None:
    assert cli.main(["--help"]) == 0

    captured = capsys.readouterr()

    assert "Powers Tool" in captured.out
    assert "supported DC power supplies" in captured.out
    assert "Keysight DC power supplies" not in captured.out

def test_cli_missing_distribution_metadata_uses_nonrelease_fallback(monkeypatch) -> None:
    from importlib import metadata
    import runpy

    def missing_distribution(_name: str) -> str:
        raise metadata.PackageNotFoundError("powers-tool")

    monkeypatch.setattr(cli.importlib.metadata, "version", missing_distribution)

    package_namespace = runpy.run_path("src/powers_tool_cli/__init__.py")

    assert package_namespace["__version__"] == "0+unknown"
    assert package_namespace["__version__"] not in {"1.0.0", "2.0.0"}
    assert cli._package_version() == "0+unknown"
    assert cli._package_version() not in {"1.0.0", "2.0.0"}
