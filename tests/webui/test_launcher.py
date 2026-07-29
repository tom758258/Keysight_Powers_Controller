from __future__ import annotations

import json
from pathlib import Path
from queue import Empty, Queue
import threading
from urllib.error import HTTPError, URLError

import pytest

from powers_tool_webui import launcher


REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeResponse:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.status = status
        self._payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class FakeValue:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class FakeControl:
    def __init__(self) -> None:
        self.state = "normal"

    def configure(self, *, state: str) -> None:
        self.state = state


class FakeRoot:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.destroyed = False

    def destroy(self) -> None:
        self.order.append("destroy")
        self.destroyed = True


class FakeServer:
    def __init__(self) -> None:
        self.should_exit = False


class FakeServerThread:
    def __init__(self, server: FakeServer, order: list[str]) -> None:
        self.server = server
        self.order = order
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float) -> None:
        assert timeout == launcher.SERVER_JOIN_TIMEOUT_S
        assert self.server.should_exit is True
        self.order.append("server_join")
        self.alive = False


class StuckServerThread(FakeServerThread):
    def join(self, timeout: float) -> None:
        assert timeout == launcher.SERVER_JOIN_TIMEOUT_S
        assert self.server.should_exit is True
        self.order.append("server_join")


class FakeLoop:
    def is_running(self) -> bool:
        return True


class FakeManager:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    def shutdown(self, *, timeout_s: float):
        self.order.append("manager_shutdown")

        async def complete() -> None:
            assert timeout_s == launcher.JOB_SHUTDOWN_TIMEOUT_S

        return complete()


def _launcher_for_shutdown(order: list[str]) -> launcher.LauncherApp:
    app = launcher.LauncherApp.__new__(launcher.LauncherApp)
    app._root = FakeRoot(order)
    app._server = FakeServer()
    app._server_thread = FakeServerThread(app._server, order)
    app._server_loop = FakeLoop()
    app._server_loop_ready = threading.Event()
    app._server_loop_ready.set()
    app._job_manager = FakeManager(order)
    app._shutdown_thread = None
    app._shutdown_in_progress = False
    app._jobs_shutdown_complete = False
    app._ui_queue = Queue()
    app._status_value = FakeValue()
    app._start_button = FakeControl()
    app._port_entry = FakeControl()
    app._quit_button = FakeControl()
    return app


def _drain_ui_queue(app: launcher.LauncherApp) -> None:
    while True:
        try:
            callback = app._ui_queue.get_nowait()
        except Empty:
            return
        callback()


def test_build_local_url_uses_loopback_default_port() -> None:
    assert launcher.DEFAULT_HOST == "127.0.0.1"
    assert launcher.DEFAULT_PORT == 7999
    assert launcher.build_local_url(launcher.DEFAULT_PORT) == "http://127.0.0.1:7999"


def test_launcher_version_prints_without_opening_gui(monkeypatch, capsys) -> None:
    def fail_tk() -> object:
        raise AssertionError("launcher GUI should not open for --version")

    monkeypatch.setattr(launcher.tk, "Tk", fail_tk)

    with pytest.raises(SystemExit) as excinfo:
        launcher.main(["--version"])

    captured = capsys.readouterr()

    assert excinfo.value.code == 0
    assert captured.out.strip() == f"powers-tool-webui-launcher {launcher.WEBUI_VERSION}"
    assert captured.err == ""


@pytest.mark.parametrize("value", ["1", "7999", "65535", " 1234 "])
def test_parse_port_accepts_valid_port(value: str) -> None:
    assert 1 <= launcher.parse_port(value) <= 65535


@pytest.mark.parametrize("value", ["0", "65536", "abc", ""])
def test_parse_port_rejects_invalid_port(value: str) -> None:
    with pytest.raises(ValueError):
        launcher.parse_port(value)


def test_server_is_ready_accepts_powers_tool_webui_health(monkeypatch) -> None:
    health_url = f"{launcher.build_local_url(launcher.DEFAULT_PORT)}/api/health"

    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        assert url == health_url
        assert timeout == 0.5
        return FakeResponse({"status": "ok", "package": "powers-tool-webui"})

    monkeypatch.setattr(launcher, "urlopen", fake_urlopen)

    assert launcher._server_is_ready(health_url) is True


def test_server_is_ready_rejects_other_http_service(monkeypatch) -> None:
    health_url = f"{launcher.build_local_url(launcher.DEFAULT_PORT)}/api/health"

    def fake_urlopen(_url: str, timeout: float) -> FakeResponse:
        return FakeResponse({"status": "ok", "package": "other-service"})

    monkeypatch.setattr(launcher, "urlopen", fake_urlopen)

    assert launcher._server_is_ready(health_url) is False


def test_http_server_is_ready_detects_any_http_response(monkeypatch) -> None:
    url = launcher.build_local_url(launcher.DEFAULT_PORT)

    def fake_urlopen(_url: str, timeout: float) -> FakeResponse:
        return FakeResponse({}, status=404)

    monkeypatch.setattr(launcher, "urlopen", fake_urlopen)

    assert launcher._http_server_is_ready(url) is True


def test_http_server_is_ready_accepts_http_error(monkeypatch) -> None:
    url = launcher.build_local_url(launcher.DEFAULT_PORT)

    def fake_urlopen(_url: str, timeout: float) -> FakeResponse:
        raise HTTPError(url, 503, "busy", {}, None)

    monkeypatch.setattr(launcher, "urlopen", fake_urlopen)

    assert launcher._http_server_is_ready(url) is True


def test_http_server_is_ready_rejects_connection_error(monkeypatch) -> None:
    url = launcher.build_local_url(launcher.DEFAULT_PORT)

    def fake_urlopen(_url: str, timeout: float) -> FakeResponse:
        raise URLError("connection refused")

    monkeypatch.setattr(launcher, "urlopen", fake_urlopen)

    assert launcher._http_server_is_ready(url) is False


def test_launcher_does_not_import_cli_adapter() -> None:
    source = (REPO_ROOT / "src" / "powers_tool_webui" / "launcher.py").read_text(
        encoding="utf-8"
    )

    assert "powers_tool_cli" not in source


def test_idle_quit_shuts_down_jobs_before_server_and_destroy(monkeypatch) -> None:
    import asyncio

    order: list[str] = []
    app = _launcher_for_shutdown(order)

    class ImmediateFuture:
        def __init__(self, coroutine) -> None:
            self.coroutine = coroutine

        def result(self, *, timeout: float) -> None:
            assert timeout == launcher.JOB_SHUTDOWN_TIMEOUT_S + 1.0
            asyncio.run(self.coroutine)

    monkeypatch.setattr(
        launcher.asyncio,
        "run_coroutine_threadsafe",
        lambda coroutine, loop: ImmediateFuture(coroutine),
    )

    app.quit()
    app._shutdown_thread.join(timeout=1)
    _drain_ui_queue(app)

    assert order == ["manager_shutdown", "server_join", "destroy"]
    assert app._server.should_exit is True
    assert app._root.destroyed is True


def test_quit_shutdown_failure_keeps_server_and_window_open(
    monkeypatch,
) -> None:
    order: list[str] = []
    app = _launcher_for_shutdown(order)

    class FailedFuture:
        def __init__(self, coroutine) -> None:
            self.coroutine = coroutine

        def result(self, *, timeout: float) -> None:
            self.coroutine.close()
            raise TimeoutError("controlled shutdown timeout")

    monkeypatch.setattr(
        launcher.asyncio,
        "run_coroutine_threadsafe",
        lambda coroutine, loop: FailedFuture(coroutine),
    )
    monkeypatch.setattr(launcher.messagebox, "showerror", lambda *_args: None)

    app.quit()
    app._shutdown_thread.join(timeout=1)
    _drain_ui_queue(app)

    assert order == ["manager_shutdown"]
    assert app._server.should_exit is False
    assert app._root.destroyed is False
    assert app._shutdown_in_progress is False
    assert app._quit_button.state == "normal"
    assert app._status_value.value.startswith("Shutdown incomplete:")


def test_quit_server_join_timeout_keeps_window_open(monkeypatch) -> None:
    import asyncio

    order: list[str] = []
    app = _launcher_for_shutdown(order)
    app._server_thread = StuckServerThread(app._server, order)

    class ImmediateFuture:
        def __init__(self, coroutine) -> None:
            self.coroutine = coroutine

        def result(self, *, timeout: float) -> None:
            asyncio.run(self.coroutine)

    monkeypatch.setattr(
        launcher.asyncio,
        "run_coroutine_threadsafe",
        lambda coroutine, loop: ImmediateFuture(coroutine),
    )
    monkeypatch.setattr(launcher.messagebox, "showerror", lambda *_args: None)

    app.quit()
    app._shutdown_thread.join(timeout=1)
    _drain_ui_queue(app)

    assert order == ["manager_shutdown", "server_join"]
    assert app._server.should_exit is True
    assert app._root.destroyed is False
    assert app._shutdown_in_progress is False
    assert app._status_value.value.startswith("Shutdown incomplete:")


def test_repeated_quit_starts_only_one_shutdown_flow(monkeypatch) -> None:
    import asyncio

    order: list[str] = []
    release_shutdown = threading.Event()
    app = _launcher_for_shutdown(order)

    class ControlledFuture:
        def __init__(self, coroutine) -> None:
            self.coroutine = coroutine

        def result(self, *, timeout: float) -> None:
            assert release_shutdown.wait(timeout=1)
            asyncio.run(self.coroutine)

    monkeypatch.setattr(
        launcher.asyncio,
        "run_coroutine_threadsafe",
        lambda coroutine, loop: ControlledFuture(coroutine),
    )

    app.quit()
    first_thread = app._shutdown_thread
    app.quit()

    assert app._shutdown_thread is first_thread
    assert order == ["manager_shutdown"]

    release_shutdown.set()
    first_thread.join(timeout=1)
    _drain_ui_queue(app)

    assert order == ["manager_shutdown", "server_join", "destroy"]


def test_quit_does_not_shutdown_server_owned_by_another_process() -> None:
    order: list[str] = []
    app = _launcher_for_shutdown(order)
    app._server = None

    app.quit()

    assert order == ["destroy"]


def test_create_uvicorn_server_uses_loopback_and_selected_port() -> None:
    server = launcher.create_uvicorn_server(8123)

    assert server.config.host == "127.0.0.1"
    assert server.config.port == 8123
    assert server.config.log_config is None
    assert server.config.access_log is False


def test_pyproject_declares_launcher_script() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'powers-tool-webui-launcher = "powers_tool_webui.launcher:main"' in pyproject
