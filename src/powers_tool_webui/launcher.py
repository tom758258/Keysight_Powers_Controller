"""Tkinter launcher for the local Powers Tool WebUI."""

from __future__ import annotations

import argparse
import asyncio
import errno
import json
from queue import Empty, Queue
import socket
import threading
import time
import tkinter as tk
from tkinter import messagebox
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

try:
    from . import __version__ as WEBUI_VERSION
except ImportError:  # pragma: no cover - PyInstaller script entry point
    from powers_tool_webui import __version__ as WEBUI_VERSION

try:
    from .jobs import job_manager
except ImportError:  # pragma: no cover - PyInstaller script entry point
    from powers_tool_webui.jobs import job_manager


PACKAGE_NAME = "powers-tool-webui"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7999
AUTO_PORT_ATTEMPTS = 100
JOB_SHUTDOWN_TIMEOUT_S = 10.0
SERVER_JOIN_TIMEOUT_S = 3.0


def build_local_url(port: int) -> str:
    return f"http://{DEFAULT_HOST}:{port}"


def parse_port(value: str) -> int:
    try:
        port = int(value.strip())
    except ValueError as exc:
        raise ValueError("Port must be a number.") from exc
    if port < 1 or port > 65535:
        raise ValueError("Port must be between 1 and 65535.")
    return port


def _candidate_ports(start_port: int, *, auto_port: bool) -> tuple[int, ...]:
    attempt_count = AUTO_PORT_ATTEMPTS if auto_port else 1
    stop_port = min(start_port + attempt_count, 65536)
    return tuple(range(start_port, stop_port))


def bind_local_socket(port: int) -> socket.socket:
    return socket.create_server((DEFAULT_HOST, port))


def _is_port_in_use_error(exc: OSError) -> bool:
    return exc.errno == errno.EADDRINUSE or getattr(exc, "winerror", None) == 10048


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


class LauncherApp:
    def __init__(
        self,
        root: tk.Tk,
        *,
        server_factory: Callable[[int], Any] | None = None,
        socket_binder: Callable[[int], Any] | None = None,
        browser_open: Callable[[str], object] | None = None,
        readiness_checker: Callable[[str], bool] | None = None,
        job_manager_instance: Any = job_manager,
        initial_port: int = DEFAULT_PORT,
    ) -> None:
        self._root = root
        self._server_factory = server_factory or create_uvicorn_server
        self._socket_binder = socket_binder or bind_local_socket
        self._browser_open = browser_open or webbrowser.open
        self._readiness_checker = readiness_checker or _server_is_ready
        self._job_manager = job_manager_instance
        self._server: Any | None = None
        self._server_socket: Any | None = None
        self._server_thread: threading.Thread | None = None
        self._server_loop: asyncio.AbstractEventLoop | None = None
        self._server_loop_ready = threading.Event()
        self._startup_thread: threading.Thread | None = None
        self._shutdown_thread: threading.Thread | None = None
        self._shutdown_in_progress = False
        self._jobs_shutdown_complete = False
        self._ui_queue: Queue[Callable[[], None]] = Queue()
        self._startup_success = threading.Event()
        self._server_error: BaseException | None = None
        self._manual_port_fallback = False
        self._startup_attempt = 0
        self._startup_result_handled = False
        self._exit_code = 0

        self._use_default_port = tk.BooleanVar(value=initial_port == DEFAULT_PORT)
        self._port_value = tk.StringVar(value=str(initial_port))
        self._url_value = tk.StringVar(value=build_local_url(initial_port))
        self._status_value = tk.StringVar(value="Ready")

        self._root.title("Powers Tool WebUI Launcher")
        self._root.protocol("WM_DELETE_WINDOW", self.quit)

        frame = tk.Frame(self._root, padx=16, pady=14)
        frame.grid(row=0, column=0, sticky="nsew")
        self._root.columnconfigure(0, weight=1)
        self._root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        self._config_frame = tk.Frame(frame)
        self._config_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._config_frame.columnconfigure(1, weight=1)

        self._default_checkbox = tk.Checkbutton(
            self._config_frame,
            text=f"Use default port {DEFAULT_PORT}",
            variable=self._use_default_port,
            command=self._sync_port_controls,
        )
        self._default_checkbox.grid(row=0, column=0, columnspan=2, sticky="w")

        tk.Label(self._config_frame, text="Port").grid(
            row=1,
            column=0,
            sticky="w",
            pady=(10, 0),
        )
        self._port_entry = tk.Entry(
            self._config_frame,
            textvariable=self._port_value,
            width=10,
        )
        self._port_entry.grid(row=1, column=1, sticky="w", pady=(10, 0))

        tk.Label(frame, text="URL").grid(row=1, column=0, sticky="w", pady=(10, 0))
        tk.Label(frame, textvariable=self._url_value, anchor="w").grid(
            row=1,
            column=1,
            sticky="ew",
            pady=(10, 0),
        )

        tk.Label(frame, textvariable=self._status_value, anchor="w").grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(12, 0),
        )

        button_row = tk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        self._start_button = tk.Button(
            button_row,
            text="Start",
            width=10,
            command=self.start,
        )
        self._start_button.grid(row=0, column=0, padx=(0, 8))
        self._quit_button = tk.Button(
            button_row,
            text="Quit",
            width=10,
            command=self.quit,
        )
        self._quit_button.grid(row=0, column=1)

        self._port_value.trace_add("write", lambda *_args: self._update_url())
        self._sync_port_controls()
        self._root.after(100, self._process_ui_queue)

    @property
    def server(self) -> Any | None:
        return self._server

    @property
    def server_thread(self) -> threading.Thread | None:
        return self._server_thread

    @property
    def exit_code(self) -> int:
        return self._exit_code

    def start(self, *, auto_port: bool = False) -> None:
        try:
            start_port = self._selected_port()
        except ValueError as exc:
            messagebox.showerror("Invalid port", str(exc))
            return

        self._startup_attempt += 1
        startup_attempt = self._startup_attempt
        self._startup_result_handled = False
        if auto_port:
            self._manual_port_fallback = False
        candidates = _candidate_ports(start_port, auto_port=auto_port)
        self._lock_started_controls()
        if auto_port:
            self._status_value.set(
                f"Starting on an available port in {candidates[0]}..{candidates[-1]}..."
            )
        else:
            self._status_value.set(f"Starting on port {start_port}...")
        self._startup_success.clear()
        self._server_error = None
        self._server = None
        self._server_socket = None
        self._server_thread = None
        self._server_loop = None
        self._server_loop_ready.clear()
        self._startup_thread = None

        for port in candidates:
            self._port_value.set(str(port))
            try:
                server_socket = self._socket_binder(port)
            except OSError as exc:
                if not _is_port_in_use_error(exc):
                    self._show_startup_error(
                        exc,
                        startup_attempt=startup_attempt,
                    )
                    return
                if not auto_port:
                    if self._manual_port_fallback:
                        self._show_manual_port_conflict(
                            port,
                            exc,
                            startup_attempt=startup_attempt,
                        )
                    else:
                        self._show_startup_error(
                            exc,
                            startup_attempt=startup_attempt,
                            port=port,
                            port_in_use=True,
                        )
                    return
                continue

            if port != DEFAULT_PORT:
                self._use_default_port.set(False)
                self._port_value.set(str(port))
            self._server_socket = server_socket
            try:
                self._server = self._server_factory(port)
                self._server_thread = threading.Thread(
                    target=self._run_server,
                    name="powers-tool-webui-launcher-server",
                    daemon=True,
                )
                self._server_thread.start()
                self._startup_thread = threading.Thread(
                    target=self._wait_for_startup,
                    args=(port, startup_attempt),
                    name="powers-tool-webui-launcher-startup",
                    daemon=True,
                )
                self._startup_thread.start()
            except Exception as exc:
                self._show_startup_error(
                    exc,
                    startup_attempt=startup_attempt,
                )
            return

        self._startup_result_handled = True
        self._manual_port_fallback = True
        self._use_default_port.set(False)
        self._sync_port_controls()
        message = (
            f"No available port was found in {candidates[0]}..{candidates[-1]}. "
            "Enter another port and select Start."
        )
        self._status_value.set(message)
        self._show_fallback_window()
        messagebox.showerror("No available port", message)

    def quit(self) -> None:
        if self._shutdown_in_progress:
            return
        if (
            self._server is None
            or self._server_thread is None
            or not self._server_thread.is_alive()
        ):
            self._root.destroy()
            return

        self._shutdown_in_progress = True
        self._lock_started_controls()
        self._quit_button.configure(state="disabled")
        self._status_value.set("Stopping active jobs...")
        self._shutdown_thread = threading.Thread(
            target=self._shutdown_owned_server,
            name="powers-tool-webui-launcher-shutdown",
            daemon=True,
        )
        self._shutdown_thread.start()

    def _shutdown_owned_server(self) -> None:
        try:
            if not self._jobs_shutdown_complete:
                if not self._server_loop_ready.wait(timeout=SERVER_JOIN_TIMEOUT_S):
                    raise RuntimeError("WebUI server event loop is not available.")
                server_loop = self._server_loop
                if server_loop is None or not server_loop.is_running():
                    raise RuntimeError("WebUI server event loop is not running.")
                future = asyncio.run_coroutine_threadsafe(
                    self._job_manager.shutdown(timeout_s=JOB_SHUTDOWN_TIMEOUT_S),
                    server_loop,
                )
                future.result(timeout=JOB_SHUTDOWN_TIMEOUT_S + 1.0)
                self._jobs_shutdown_complete = True

            self._server.should_exit = True
            if self._server_thread is not None and self._server_thread.is_alive():
                self._server_thread.join(timeout=SERVER_JOIN_TIMEOUT_S)
            if self._server_thread is not None and self._server_thread.is_alive():
                raise TimeoutError("WebUI server did not stop before the join timeout.")
        except BaseException as exc:
            self._post_ui(lambda exc=exc: self._show_shutdown_error(exc))
            return
        self._post_ui(self._root.destroy)

    def _show_shutdown_error(self, exc: BaseException) -> None:
        message = f"{type(exc).__name__}: {exc}"
        self._status_value.set(f"Shutdown incomplete: {message}")
        self._quit_button.configure(state="normal")
        self._shutdown_in_progress = False
        messagebox.showerror("Shutdown incomplete", message)

    def _wait_for_startup(self, port: int, startup_attempt: int) -> None:
        url = build_local_url(port)
        health_url = f"{url}/api/health"
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if self._readiness_checker(health_url):
                self._post_ui(
                    lambda: self._mark_server_ready(
                        url,
                        startup_attempt=startup_attempt,
                    )
                )
                return
            if self._server_thread is not None and not self._server_thread.is_alive():
                error = self._server_error or RuntimeError(
                    "WebUI server stopped during startup."
                )
                self._post_ui(
                    lambda error=error: self._show_startup_error(
                        error,
                        startup_attempt=startup_attempt,
                    )
                )
                return
            time.sleep(0.2)
        self._post_ui(
            lambda: self._show_startup_error(
                TimeoutError(f"WebUI server did not become ready at {url}."),
                startup_attempt=startup_attempt,
            )
        )

    def _run_server(self) -> None:
        server_socket = self._server_socket
        try:
            asyncio.run(self._serve_server(server_socket))
        except BaseException as exc:  # pragma: no cover - runtime safety net
            self._server_error = exc
        finally:
            if self._server_socket is server_socket:
                self._server_socket = None
                if server_socket is not None:
                    server_socket.close()
            self._server_loop = None

    async def _serve_server(self, server_socket: Any) -> None:
        self._server_loop = asyncio.get_running_loop()
        self._server_loop_ready.set()
        await self._server.serve(sockets=[server_socket])

    def _mark_server_ready(self, url: str, *, startup_attempt: int) -> None:
        if (
            startup_attempt != self._startup_attempt
            or self._startup_result_handled
        ):
            return
        self._startup_result_handled = True
        self._startup_success.set()
        self._url_value.set(url)
        self._status_value.set(f"Running at {url}")
        self._show_running_window()
        self._browser_open(url)

    def _show_startup_error(
        self,
        exc: BaseException,
        *,
        startup_attempt: int,
        port: int | None = None,
        port_in_use: bool = False,
    ) -> None:
        if (
            startup_attempt != self._startup_attempt
            or self._startup_result_handled
            or self._startup_success.is_set()
        ):
            return
        self._startup_result_handled = True
        self._exit_code = 1
        message = self._startup_error_message(
            exc,
            port=port,
            port_in_use=port_in_use,
        )
        self._status_value.set(f"Failed: {message}")
        messagebox.showerror("Start failed", message)
        self._cleanup_failed_startup()

    def _show_manual_port_conflict(
        self,
        port: int,
        exc: BaseException,
        *,
        startup_attempt: int,
    ) -> None:
        if (
            startup_attempt != self._startup_attempt
            or self._startup_result_handled
        ):
            return
        self._startup_result_handled = True
        message = self._startup_error_message(
            exc,
            port=port,
            port_in_use=True,
        )
        self._status_value.set(f"Failed: {message}")
        self._show_fallback_window()
        messagebox.showerror("Port unavailable", message)

    @staticmethod
    def _startup_error_message(
        exc: BaseException,
        *,
        port: int | None,
        port_in_use: bool,
    ) -> str:
        details = f"{type(exc).__name__}: {exc}"
        if port_in_use and port is not None:
            return f"Port {port} is already in use. {details}"
        return details

    def _cleanup_failed_startup(self) -> None:
        if self._server is not None:
            self._server.should_exit = True

        server_socket = self._server_socket
        self._server_socket = None
        if server_socket is not None:
            try:
                server_socket.close()
            except OSError:
                pass

        server_thread = self._server_thread
        if (
            server_thread is not None
            and server_thread is not threading.current_thread()
            and server_thread.is_alive()
        ):
            server_thread.join(timeout=SERVER_JOIN_TIMEOUT_S)

        self._root.destroy()

    def _show_running_window(self) -> None:
        self._config_frame.grid_remove()
        self._start_button.grid_remove()
        self._quit_button.configure(state="normal")
        self._root.update_idletasks()
        self._root.deiconify()

    def _show_fallback_window(self) -> None:
        self._config_frame.grid()
        self._start_button.grid()
        self._start_button.configure(state="normal")
        self._default_checkbox.configure(state="normal")
        self._quit_button.configure(state="normal")
        self._sync_port_controls()
        self._root.update_idletasks()
        self._root.deiconify()
        self._root.lift()

    def _post_ui(self, callback: Callable[[], None]) -> None:
        self._ui_queue.put(callback)

    def _process_ui_queue(self) -> None:
        while True:
            try:
                callback = self._ui_queue.get_nowait()
            except Empty:
                break
            callback()
        try:
            self._root.after(100, self._process_ui_queue)
        except tk.TclError:
            pass

    def _sync_port_controls(self) -> None:
        if self._use_default_port.get():
            self._port_value.set(str(DEFAULT_PORT))
            self._port_entry.configure(state="disabled")
        else:
            self._port_entry.configure(state="normal")
        self._update_url()

    def _update_url(self) -> None:
        try:
            port = self._selected_port()
        except ValueError:
            self._url_value.set(f"http://{DEFAULT_HOST}:")
            return
        self._url_value.set(build_local_url(port))

    def _selected_port(self) -> int:
        if self._use_default_port.get():
            return DEFAULT_PORT
        return parse_port(self._port_value.get())

    def _lock_started_controls(self) -> None:
        self._start_button.configure(state="disabled")
        self._port_entry.configure(state="disabled")


def _server_is_ready(url: str) -> bool:
    try:
        with urlopen(url, timeout=0.5) as response:
            if int(response.status) != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                return False
            return payload.get("status") == "ok" and payload.get("package") == PACKAGE_NAME
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Powers Tool WebUI Launcher")
    parser.add_argument(
        "--version",
        action="version",
        version=f"powers-tool-webui-launcher {WEBUI_VERSION}",
    )
    parser.add_argument(
        "--port",
        type=parse_port,
        help="Port to bind; fixed unless --auto-port is also set",
    )
    parser.add_argument(
        "--auto-port",
        action="store_true",
        help="Try up to 100 ports starting from --port or 7999",
    )
    args = parser.parse_args(argv)

    initial_port = args.port if args.port is not None else DEFAULT_PORT
    auto_port = args.auto_port or args.port is None
    root = tk.Tk()
    root.withdraw()
    app = LauncherApp(root, initial_port=initial_port)
    root.after(0, lambda: app.start(auto_port=auto_port))
    root.mainloop()
    return app.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
