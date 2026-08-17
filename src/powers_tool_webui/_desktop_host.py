"""Private local WebUI host for a future desktop integration."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
import time
from typing import Any, Callable, TextIO
from urllib.error import URLError
from urllib.request import urlopen

try:
    from .jobs import job_manager
except ImportError:  # pragma: no cover - PyInstaller script entry point
    from powers_tool_webui.jobs import job_manager


PACKAGE_NAME = "powers-tool-webui"
DEFAULT_HOST = "127.0.0.1"
JOB_SHUTDOWN_TIMEOUT_S = 10.0
SERVER_JOIN_TIMEOUT_S = 3.0
STARTUP_TIMEOUT_S = 8.0
READINESS_POLL_INTERVAL_S = 0.2
SHUTDOWN_WAIT_GRACE_S = 1.0


def build_local_url(port: int) -> str:
    return f"http://{DEFAULT_HOST}:{port}"


def bind_local_socket() -> socket.socket:
    return socket.create_server((DEFAULT_HOST, 0))


def create_uvicorn_server(port: int) -> Any:
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        raise _missing_webui_dependency_error(exc) from exc
    try:
        from .app import app
    except ModuleNotFoundError as exc:
        raise _missing_webui_dependency_error(exc) from exc
    except ImportError:  # pragma: no cover - PyInstaller script entry point
        try:
            from powers_tool_webui.app import app
        except ModuleNotFoundError as exc:
            raise _missing_webui_dependency_error(exc) from exc

    config = uvicorn.Config(
        app,
        host=DEFAULT_HOST,
        port=port,
        log_config=None,
        access_log=False,
    )
    return uvicorn.Server(config)


def _missing_webui_dependency_error(exc: ModuleNotFoundError) -> RuntimeError:
    missing = exc.name or "webui runtime dependency"
    return RuntimeError(
        f"Missing optional WebUI dependency {missing!r}. "
        "Install the WebUI optional dependencies. "
        "For a source checkout, run "
        "`uv sync --extra webui --locked --link-mode=copy` from the repository root."
    )


def _server_is_ready(url: str) -> bool:
    try:
        with urlopen(url, timeout=0.5) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("status") == "ok"
        and payload.get("package") == PACKAGE_NAME
    )


class DesktopHost:
    """Own one local WebUI server and expose its lifecycle over stdin."""

    def __init__(
        self,
        *,
        server_factory: Callable[[int], Any] | None = None,
        socket_binder: Callable[[], Any] | None = None,
        readiness_checker: Callable[[str], bool] | None = None,
        job_manager_instance: Any = job_manager,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
        job_shutdown_timeout_s: float = JOB_SHUTDOWN_TIMEOUT_S,
        shutdown_wait_grace_s: float = SHUTDOWN_WAIT_GRACE_S,
        server_join_timeout_s: float = SERVER_JOIN_TIMEOUT_S,
        startup_timeout_s: float = STARTUP_TIMEOUT_S,
        readiness_poll_interval_s: float = READINESS_POLL_INTERVAL_S,
    ) -> None:
        self._server_factory = server_factory or create_uvicorn_server
        self._socket_binder = socket_binder or bind_local_socket
        self._readiness_checker = readiness_checker or _server_is_ready
        self._job_manager = job_manager_instance
        self._input_stream = input_stream or sys.stdin
        self._output_stream = output_stream or sys.stdout
        self._job_shutdown_timeout_s = job_shutdown_timeout_s
        self._shutdown_wait_grace_s = shutdown_wait_grace_s
        self._server_join_timeout_s = server_join_timeout_s
        self._startup_timeout_s = startup_timeout_s
        self._readiness_poll_interval_s = readiness_poll_interval_s

        self._server: Any | None = None
        self._server_socket: Any | None = None
        self._server_thread: threading.Thread | None = None
        self._server_loop: asyncio.AbstractEventLoop | None = None
        self._server_loop_ready = threading.Event()
        self._server_error: BaseException | None = None
        self._port: int | None = None
        self._shutdown_in_progress = False

    @property
    def server(self) -> Any | None:
        return self._server

    @property
    def server_thread(self) -> threading.Thread | None:
        return self._server_thread

    @property
    def port(self) -> int | None:
        return self._port

    def run(self) -> int:
        try:
            self.start()
        except BaseException as exc:
            self._emit("error", self._error_message(exc))
            self._cleanup_failed_startup()
            return 1

        for line in self._input_stream:
            command = self._parse_command(line)
            if command != "shutdown":
                continue
            if self.shutdown():
                return 0
        return 0

    def start(self) -> str:
        self._server_socket = self._socket_binder()
        self._port = int(self._server_socket.getsockname()[1])
        self._server_error = None
        self._server_loop_ready.clear()
        self._server = self._server_factory(self._port)
        self._server_thread = threading.Thread(
            target=self._run_server,
            name="powers-tool-webui-host-server",
            daemon=True,
        )
        self._server_thread.start()

        if not self._server_loop_ready.wait(timeout=self._server_join_timeout_s):
            raise RuntimeError("WebUI server event loop did not start.")

        url = build_local_url(self._port)
        health_url = f"{url}/api/health"
        deadline = time.monotonic() + self._startup_timeout_s
        while time.monotonic() < deadline:
            if self._readiness_checker(health_url):
                self._emit("ready", url=url)
                return url
            if self._server_thread is not None and not self._server_thread.is_alive():
                raise self._server_error or RuntimeError(
                    "WebUI server stopped during startup."
                )
            time.sleep(self._readiness_poll_interval_s)
        raise TimeoutError(f"WebUI server did not become ready at {url}.")

    def shutdown(self) -> bool:
        if self._shutdown_in_progress:
            return False
        self._shutdown_in_progress = True
        try:
            server_loop = self._server_loop
            if server_loop is None or not server_loop.is_running():
                raise RuntimeError("WebUI server event loop is not running.")

            future = asyncio.run_coroutine_threadsafe(
                self._job_manager.shutdown(timeout_s=self._job_shutdown_timeout_s),
                server_loop,
            )
            try:
                future.result(
                    timeout=self._job_shutdown_timeout_s + self._shutdown_wait_grace_s
                )
            except BaseException as exc:
                future.cancel()
                self._emit("shutdown_incomplete", self._error_message(exc))
                return False

            if self._server is not None:
                self._server.should_exit = True

            server_thread = self._server_thread
            if server_thread is not None and server_thread.is_alive():
                server_thread.join(timeout=self._server_join_timeout_s)
            if server_thread is not None and server_thread.is_alive():
                raise TimeoutError("WebUI server did not stop before the join timeout.")
            self._close_server_socket()
            return True
        except BaseException as exc:
            self._emit("shutdown_incomplete", self._error_message(exc))
            return False
        finally:
            self._shutdown_in_progress = False

    def _run_server(self) -> None:
        server_socket = self._server_socket
        try:
            asyncio.run(self._serve_server(server_socket))
        except BaseException as exc:  # pragma: no cover - runtime safety net
            self._server_error = exc

    async def _serve_server(self, server_socket: Any) -> None:
        self._server_loop = asyncio.get_running_loop()
        self._server_loop_ready.set()
        await self._server.serve(sockets=[server_socket])

    def _cleanup_failed_startup(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        server_thread = self._server_thread
        if (
            server_thread is not None
            and server_thread is not threading.current_thread()
            and server_thread.is_alive()
        ):
            server_thread.join(timeout=self._server_join_timeout_s)
        self._close_server_socket(suppress_errors=True)

    def _close_server_socket(self, *, suppress_errors: bool = False) -> None:
        server_socket = self._server_socket
        self._server_socket = None
        if server_socket is not None:
            try:
                server_socket.close()
            except OSError:
                if not suppress_errors:
                    raise

    def _emit(self, event: str, message: str | None = None, *, url: str | None = None) -> None:
        payload: dict[str, str] = {"event": event}
        if url is not None:
            payload["url"] = url
        if message is not None:
            payload["message"] = message
        self._output_stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self._output_stream.flush()

    @staticmethod
    def _parse_command(line: str) -> str | None:
        try:
            payload = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        command = payload.get("command")
        return command if isinstance(command, str) else None

    @staticmethod
    def _error_message(exc: BaseException) -> str:
        return f"{type(exc).__name__}: {exc}"


def main() -> int:
    return DesktopHost().run()


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
