"""Tests for shared WebUI API test helpers."""

from __future__ import annotations

from typing import Any

import pytest

import _webui_api_helpers as helpers


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = iter(payloads)

    def get(self, path: str) -> _FakeResponse:
        return _FakeResponse(next(self._payloads))


def test_wait_for_job_returns_later_terminal_payload() -> None:
    client = _FakeClient(
        [
            {"job_id": "job-1", "status": "running"},
            {"job_id": "job-1", "status": "finished", "result": {"ok": True}},
        ]
    )

    result = helpers.wait_for_job(client, "job-1", poll_interval=0)

    assert result["status"] == "finished"
    assert result["result"] == {"ok": True}


def test_wait_for_job_returns_cancelled_payload() -> None:
    client = _FakeClient([{"job_id": "job-3", "status": "cancelled"}])

    result = helpers.wait_for_job(client, "job-3")

    assert result["status"] == "cancelled"


def test_wait_for_job_timeout_reports_job_and_last_payload() -> None:
    client = _FakeClient([{"job_id": "job-2", "status": "running"}])

    with pytest.raises(pytest.fail.Exception) as exc_info:
        helpers.wait_for_job(client, "job-2", timeout=0)

    message = str(exc_info.value)
    assert "job-2" in message
    assert "{'job_id': 'job-2', 'status': 'running'}" in message
