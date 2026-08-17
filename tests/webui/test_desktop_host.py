from __future__ import annotations

import asyncio
import json
import time
from io import StringIO
from urllib.request import urlopen

import pytest

from powers_tool_webui._desktop_host import DesktopHost


class RecordingJobManager:
    def __init__(self, host: DesktopHost | None = None) -> None:
        self.host = host
        self.loop: asyncio.AbstractEventLoop | None = None
        self.observed_should_exit: bool | None = None

    async def shutdown(self, *, timeout_s: float) -> None:
        self.loop = asyncio.get_running_loop()
        self.observed_should_exit = self.host.server.should_exit


def _events(output: StringIO) -> list[dict[str, str]]:
    return [json.loads(line) for line in output.getvalue().splitlines()]


def test_desktop_host_uses_ephemeral_port_health_readiness_and_ordered_shutdown() -> None:
    output = StringIO()
    manager = RecordingJobManager()

    class ShutdownInput:
        def __iter__(self):
            with urlopen(
                f"http://127.0.0.1:{host.port}/api/health", timeout=1
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            assert response.status == 200
            assert payload["status"] == "ok"
            assert payload["package"] == "powers-tool-webui"
            yield '{"command":"shutdown"}\n'

    host = DesktopHost(
        input_stream=ShutdownInput(),
        output_stream=output,
        job_manager_instance=manager,
    )
    manager.host = host

    assert host.run() == 0

    events = _events(output)
    assert events[0]["event"] == "ready"
    assert events[0]["url"].startswith("http://127.0.0.1:")
    assert host.port is not None and host.port > 0
    assert manager.loop is not None
    assert manager.observed_should_exit is False
    assert host.server is not None and host.server.should_exit is True
    assert host.server_thread is not None and not host.server_thread.is_alive()


@pytest.mark.parametrize("failure", ["exception", "timeout"])
def test_shutdown_failure_reports_incomplete_without_stopping_server(failure: str) -> None:
    class FailingJobManager:
        async def shutdown(self, *, timeout_s: float) -> None:
            if failure == "exception":
                raise RuntimeError("cleanup failed")
            await asyncio.sleep(0.1)

    output = StringIO()
    host = DesktopHost(
        output_stream=output,
        job_manager_instance=FailingJobManager(),
        job_shutdown_timeout_s=0.02,
        shutdown_wait_grace_s=0.02,
    )
    host.start()
    try:
        assert host.shutdown() is False

        events = _events(output)
        assert events[0]["event"] == "ready"
        assert events[-1]["event"] == "shutdown_incomplete"
        assert host.server is not None and host.server.should_exit is False
        assert host.server_thread is not None and host.server_thread.is_alive()
        if failure == "timeout":
            time.sleep(0.2)
            assert host.server.should_exit is False
            assert host.server_thread.is_alive()
    finally:
        if host.server is not None:
            host.server.should_exit = True
        if host.server_thread is not None:
            host.server_thread.join(timeout=2)
        host._close_server_socket()
