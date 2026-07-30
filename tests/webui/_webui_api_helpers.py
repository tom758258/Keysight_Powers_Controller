"""Shared helpers for WebUI API tests."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

class FakeCoreSession:
    def __init__(self, idn: str, *, query_responses: dict[str, str] | None = None) -> None:
        self.idn = idn
        self.query_responses = query_responses or {}
        self.queries: list[str] = []
        self.writes: list[str] = []
        self.closed = False

    def __enter__(self) -> "FakeCoreSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.closed = True

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str) -> str:
        self.queries.append(command)
        if command == "*IDN?":
            return self.idn
        if command == "INST:NSEL?":
            return self.query_responses.get(command, "1")
        if command == "SYST:ERR?":
            return self.query_responses.get(command, '0,"No error"')
        if command in self.query_responses:
            return self.query_responses[command]
        raise AssertionError(f"unexpected query {command!r}")


def wait_for_job(
    client: TestClient,
    job_id: str,
    *,
    timeout: float = 5.0,
    poll_interval: float = 0.05,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        job_data = client.get(f"/api/jobs/{job_id}").json()
        if job_data["status"] in ("finished", "failed"):
            return job_data
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(f"Timed out waiting for job {job_id!r}; last payload: {job_data!r}")
        time.sleep(min(poll_interval, remaining))


def patch_core_opener(monkeypatch: pytest.MonkeyPatch, session: FakeCoreSession) -> None:
    from powers_tool_core.command_runner import run_core_command as real_run_core_command
    from powers_tool_webui import commands

    def fake_opener(*args: Any, **kwargs: Any) -> FakeCoreSession:
        return session

    def fake_run_core_command(request: Any, **kwargs: Any) -> dict[str, Any]:
        return real_run_core_command(request, opener=fake_opener, **kwargs)

    monkeypatch.setattr(commands, "run_core_command", fake_run_core_command)


def assert_direct_job_rejected(client: TestClient, payload: dict[str, Any], *message_fragments: str) -> None:
    response = client.post("/api/jobs", json=payload)
    if response.status_code == 400:
        detail = response.json()["detail"]
        for fragment in message_fragments:
            assert fragment in detail
        return

    assert response.status_code == 200
    job_data = wait_for_job(client, response.json()["job_id"])
    assert job_data["status"] == "failed", job_data.get("result")
    error = job_data.get("error") or ""
    for fragment in message_fragments:
        assert fragment in error


def policy_snapshot_document(model: str) -> dict[str, Any]:
    model_ids = {
        "E36312A": "keysight-e36312a",
        "EDU36311A": "keysight-edu36311a",
        "E3646A": "keysight-e3646a",
    }
    return {
        "schema_version": 2,
        "kind": "powers-tool-snapshot",
        "reported_identity": {
            "manufacturer": "KEYSIGHT",
            "model": model,
            "serial": "SERIAL0000",
            "firmware": "1.0",
            "parse_ok": True,
        },
        "resolved_identity": {
            "vendor_id": "keysight",
            "model_id": model_ids[model],
            "model_name": model,
            "display_name": f"Keysight {model}",
        },
        "outputs": [{"channel": 1, "enabled": False}],
        "readback": [{"channel": 1, "setpoints": {"voltage": 1.0, "current": 0.05}}],
        "protection_settings": [{"channel": 1, "protection": {"ovp_voltage": 5.0, "ocp_enabled": True}}],
    }
