from __future__ import annotations

import json
from pathlib import Path
from queue import Empty, Queue
import threading
from urllib.error import URLError

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
    def __init__(self, value: str = "") -> None:
        self.value = value

    def set(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class FakeBoolean:
    def __init__(self, value: bool) -> None:
        self.value = value

    def set(self, value: bool) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value


class FakeControl:
    def __init__(self) -> None:
        self.state = "normal"

    def configure(self, *, state: str) -> None:
        self.state = state


class FakeRoot:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.destroyed = False
        self.destroy_count = 0
        self.iconified = False
        self.restored = False
        self.lifted = False

    def destroy(self) -> None:
        self.order.append("destroy")
        self.destroyed = True
        self.destroy_count += 1

    def iconify(self) -> None:
        self.iconified = True

    def deiconify(self) -> None:
        self.iconified = False
        self.restored = True

    def lift(self) -> None:
        self.lifted = True


class FakeServerConfig:
    def __init__(self) -> None:
        self.setup_event_loop_accessed = False

    @property
    def setup_event_loop(self) -> None:
        self.setup_event_loop_accessed = True
        raise AttributeError("setup_event_loop was removed")


class FakeServer:
    def __init__(self) -> None:
        self.should_exit = False
        self.config = FakeServerConfig()
        self.served_sockets: list[object] = []

    async def serve(self, *, sockets: list[object]) -> None:
        self.served_sockets = sockets


class FakeSocket:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


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


def _launcher_for_startup(
    *,
    initial_port: int,
    socket_binder,
    server_factory,
    readiness_checker=lambda _url: False,
    browser_open=lambda _url: None,
) -> launcher.LauncherApp:
    app = launcher.LauncherApp.__new__(launcher.LauncherApp)
    app._root = FakeRoot([])
    app._server_factory = server_factory
    app._socket_binder = socket_binder
    app._browser_open = browser_open
    app._readiness_checker = readiness_checker
    app._server = None
    app._server_socket = None
    app._server_thread = None
    app._server_loop = None
    app._server_loop_ready = threading.Event()
    app._startup_thread = None
    app._shutdown_thread = None
    app._shutdown_in_progress = False
    app._jobs_shutdown_complete = False
    app._ui_queue = Queue()
    app._startup_success = threading.Event()
    app._server_error = None
    app._manual_port_fallback = False
    app._startup_attempt = 0
    app._startup_result_handled = False
    app._exit_code = 0
    app._use_default_port = FakeBoolean(initial_port == launcher.DEFAULT_PORT)
    app._port_value = FakeValue(str(initial_port))
    app._url_value = FakeValue(launcher.build_local_url(initial_port))
    app._status_value = FakeValue("Ready")
    app._port_entry = FakeControl()
    app._start_button = FakeControl()
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


def test_server_is_ready_rejects_connection_error(monkeypatch) -> None:
    health_url = f"{launcher.build_local_url(launcher.DEFAULT_PORT)}/api/health"

    def fake_urlopen(_url: str, timeout: float) -> FakeResponse:
        raise URLError("connection refused")

    monkeypatch.setattr(launcher, "urlopen", fake_urlopen)

    assert launcher._server_is_ready(health_url) is False


def test_auto_port_uses_first_bound_socket_and_actual_browser_url(
    monkeypatch,
) -> None:
    attempted_ports: list[int] = []
    created_ports: list[int] = []
    browser_urls: list[str] = []
    bound_socket = FakeSocket()
    server = FakeServer()

    def socket_binder(port: int) -> FakeSocket:
        attempted_ports.append(port)
        if port < 8001:
            raise OSError(launcher.errno.EADDRINUSE, "in use")
        return bound_socket

    def server_factory(port: int) -> FakeServer:
        created_ports.append(port)
        return server

    class ImmediateThread:
        def __init__(
            self,
            *,
            target,
            name: str,
            daemon: bool,
            args: tuple[object, ...] = (),
        ) -> None:
            self._target = target
            self._args = args
            self._alive = False

        def start(self) -> None:
            self._alive = True
            self._target(*self._args)
            self._alive = False

        def is_alive(self) -> bool:
            return self._alive

    app = _launcher_for_startup(
        initial_port=launcher.DEFAULT_PORT,
        socket_binder=socket_binder,
        server_factory=server_factory,
        readiness_checker=lambda url: url.endswith(":8001/api/health"),
        browser_open=browser_urls.append,
    )
    monkeypatch.setattr(launcher.threading, "Thread", ImmediateThread)

    app.start(auto_port=True)
    _drain_ui_queue(app)

    assert attempted_ports == [7999, 8000, 8001]
    assert created_ports == [8001]
    assert server.config.setup_event_loop_accessed is False
    assert server.served_sockets == [bound_socket]
    assert browser_urls == ["http://127.0.0.1:8001"]
    assert app._status_value.value == "Running at http://127.0.0.1:8001"


@pytest.mark.parametrize(
    ("argv", "expected_ports"),
    [
        ([], tuple(range(7999, 8099))),
        (["--port", "9000"], (9000,)),
        (["--port", "9000", "--auto-port"], tuple(range(9000, 9100))),
        (["--port", "65534", "--auto-port"], (65534, 65535)),
    ],
)
def test_launcher_cli_selects_expected_port_candidates(
    monkeypatch,
    argv: list[str],
    expected_ports: tuple[int, ...],
) -> None:
    recorded_ports: list[tuple[int, ...]] = []
    root = FakeRoot([])

    class FakeMainApp:
        def __init__(self, _root: FakeRoot, *, initial_port: int) -> None:
            self.initial_port = initial_port
            self.exit_code = 0

        def start(self, *, auto_port: bool) -> None:
            recorded_ports.append(
                launcher._candidate_ports(self.initial_port, auto_port=auto_port)
            )

    root.after = lambda delay, callback: callback()
    root.mainloop = lambda: None
    monkeypatch.setattr(launcher.tk, "Tk", lambda: root)
    monkeypatch.setattr(launcher, "LauncherApp", FakeMainApp)

    assert launcher.main(argv) == 0

    assert root.iconified is True
    assert recorded_ports == [expected_ports]


def test_fixed_port_conflict_does_not_increment(monkeypatch) -> None:
    attempted_ports: list[int] = []
    errors: list[tuple[str, str]] = []

    def socket_binder(port: int) -> FakeSocket:
        attempted_ports.append(port)
        raise OSError(launcher.errno.EADDRINUSE, "in use")

    app = _launcher_for_startup(
        initial_port=9000,
        socket_binder=socket_binder,
        server_factory=lambda _port: pytest.fail("server must not be created"),
    )
    monkeypatch.setattr(
        launcher.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
    )

    app.start()

    assert attempted_ports == [9000]
    assert app._root.restored is False
    assert app._root.destroyed is True
    assert app._start_button.state == "disabled"
    assert app.exit_code == 1
    assert len(errors) == 1
    assert errors[0][0] == "Start failed"
    assert errors[0][1].startswith("Port 9000 is already in use. OSError:")
    assert "in use" in errors[0][1]


def test_auto_port_exhaustion_restores_manual_window(monkeypatch) -> None:
    attempted_ports: list[int] = []
    errors: list[tuple[str, str]] = []

    def socket_binder(port: int) -> FakeSocket:
        attempted_ports.append(port)
        if port == 9001:
            raise PermissionError("bind denied")
        raise OSError(launcher.errno.EADDRINUSE, "in use")

    app = _launcher_for_startup(
        initial_port=launcher.DEFAULT_PORT,
        socket_binder=socket_binder,
        server_factory=lambda _port: pytest.fail("server must not be created"),
    )
    monkeypatch.setattr(launcher, "AUTO_PORT_ATTEMPTS", 3)
    monkeypatch.setattr(
        launcher.messagebox,
        "showerror",
        lambda title, message: errors.append((title, message)),
    )

    app.start(auto_port=True)

    assert attempted_ports == [7999, 8000, 8001]
    assert app._root.restored is True
    assert app._use_default_port.get() is False
    assert app._port_entry.state == "normal"
    assert "7999..8001" in app._status_value.value
    assert errors == [("No available port", app._status_value.value)]

    app._port_value.set("9000")
    app.start()

    assert attempted_ports == [7999, 8000, 8001, 9000]
    assert app._root.destroyed is False
    assert app._root.restored is True
    assert app._port_entry.state == "normal"
    assert app._start_button.state == "normal"
    assert app.exit_code == 0
    assert errors[1][0] == "Port unavailable"
    assert errors[1][1].startswith("Port 9000 is already in use. OSError:")

    app._port_value.set("9001")
    app.start()

    assert attempted_ports == [7999, 8000, 8001, 9000, 9001]
    assert app._root.destroyed is True
    assert app.exit_code == 1
    assert errors[2] == ("Start failed", "PermissionError: bind denied")


@pytest.mark.parametrize("failure_phase", ["bind", "server"])
def test_auto_port_stops_on_non_conflict_error(
    monkeypatch,
    failure_phase: str,
) -> None:
    attempted_ports: list[int] = []
    created_ports: list[int] = []
    bound_socket = FakeSocket()
    errors: list[str] = []

    def socket_binder(port: int) -> FakeSocket:
        attempted_ports.append(port)
        if failure_phase == "bind":
            raise PermissionError("bind denied")
        return bound_socket

    def server_factory(port: int) -> FakeServer:
        created_ports.append(port)
        raise RuntimeError("app initialization failed")

    app = _launcher_for_startup(
        initial_port=launcher.DEFAULT_PORT,
        socket_binder=socket_binder,
        server_factory=server_factory,
    )
    monkeypatch.setattr(
        launcher.messagebox,
        "showerror",
        lambda _title, message: errors.append(message),
    )

    app.start(auto_port=True)

    assert attempted_ports == [7999]
    assert app._root.restored is False
    assert app._root.destroyed is True
    assert app.exit_code == 1
    if failure_phase == "bind":
        assert created_ports == []
        assert bound_socket.closed is False
        assert errors == ["PermissionError: bind denied"]
    else:
        assert created_ports == [7999]
        assert bound_socket.closed is True
        assert errors == ["RuntimeError: app initialization failed"]


def test_startup_failure_cleans_owned_resources_once(monkeypatch) -> None:
    errors: list[str] = []
    app = _launcher_for_startup(
        initial_port=launcher.DEFAULT_PORT,
        socket_binder=lambda _port: pytest.fail("bind must not run"),
        server_factory=lambda _port: pytest.fail("server must not be created"),
    )
    server = FakeServer()
    server_socket = FakeSocket()
    app._server = server
    app._server_socket = server_socket
    app._server_thread = FakeServerThread(server, app._root.order)
    app._startup_attempt = 4
    monkeypatch.setattr(
        launcher.messagebox,
        "showerror",
        lambda _title, message: errors.append(message),
    )

    error = TimeoutError("WebUI server did not become ready.")
    app._show_startup_error(error, startup_attempt=4)
    app._show_startup_error(error, startup_attempt=4)
    app._mark_server_ready(
        launcher.build_local_url(launcher.DEFAULT_PORT),
        startup_attempt=3,
    )

    assert errors == ["TimeoutError: WebUI server did not become ready."]
    assert server.should_exit is True
    assert server_socket.closed is True
    assert app._root.order == ["server_join", "destroy"]
    assert app._root.destroy_count == 1
    assert app._root.restored is False
    assert app.exit_code == 1


def test_launcher_main_returns_startup_exit_code(monkeypatch) -> None:
    root = FakeRoot([])

    class FailedMainApp:
        def __init__(self, _root: FakeRoot, *, initial_port: int) -> None:
            assert initial_port == 9000
            self.exit_code = 1

        def start(self, *, auto_port: bool) -> None:
            assert auto_port is False

    root.after = lambda delay, callback: callback()
    root.mainloop = lambda: None
    monkeypatch.setattr(launcher.tk, "Tk", lambda: root)
    monkeypatch.setattr(launcher, "LauncherApp", FailedMainApp)

    assert launcher.main(["--port", "9000"]) == 1


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
