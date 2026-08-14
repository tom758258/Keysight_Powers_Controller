"""Thread-safe state container for Powers Tool worker daemon."""

from __future__ import annotations

import threading
from typing import Any, TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from powers_tool_cli.worker_http import WorkerHTTPServer


class WorkerState:
    """Thread-safe worker daemon state tracker."""

    def __init__(self, config: dict[str, Any], port: int) -> None:
        self.config = config
        self.port = port
        self.status = "ready"  # ready|busy|stopping|error
        self.active_job: dict[str, Any] | None = None
        self.last_job: dict[str, Any] | None = None
        self.fatal_error: dict[str, Any] | None = None
        self.lock = threading.Condition()
        self.shutdown_event = threading.Event()
        self.stop_event = threading.Event()
        self.job_cancel_event = threading.Event()
        self.next_job: dict[str, Any] | None = None
        self.pending_terminal_event: tuple[str, dict[str, Any]] | None = None
        self.shutdown_flag = False
        self.server: WorkerHTTPServer | None = None
        self.run_id = str(uuid.uuid4())
        self.cleanup_results: list[dict[str, str]] = []
        self.cleanup_failed = False

        if config["mode"] == "simulate":
            from powers_tool_core.testing.simulator import SimulatedResourceManager

            self.sim_mgr = SimulatedResourceManager()
        else:
            self.sim_mgr = None
