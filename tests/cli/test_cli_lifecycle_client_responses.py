from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

import powers_tool_cli.cli as cli
import powers_tool_cli.lifecycle_client as lifecycle_client

CONTEXT_ARGS = [
    "--context-json",
    '{"mode":"dry_run","planning_profile_id":"generic-scpi"}',
]


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _body(payload: object) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _accepted_response(*, command: str = "read-status", job_id: str | None = None) -> dict[str, object]:
    return {
        "schema_version": 2,
        "status": "accepted",
        "command": command,
        "job_id": job_id,
        "worker_job_id": "worker-job-1",
        "artifact_path": "C:/artifacts/jobs/worker-job-1",
    }


def _status_response(*, status: str = "ready") -> dict[str, object]:
    return {
        "schema_version": 2,
        "service": "powers-tool",
        "run_id": "run-1",
        "status": status,
        "command_url": "http://127.0.0.1:9000/command",
        "stop_url": "http://127.0.0.1:9000/stop",
        "status_url": "http://127.0.0.1:9000/status",
        "queue_size": 0,
        "active_job": None,
        "last_job": None,
        "fatal_error": None,
        "timestamp_utc": "2026-07-21T00:00:00Z",
    }


def _install_response(monkeypatch: pytest.MonkeyPatch, status: int, body: bytes) -> None:
    monkeypatch.setattr(
        lifecycle_client.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _FakeResponse(status, body),
    )


def _install_exception(monkeypatch: pytest.MonkeyPatch, exception: Exception) -> None:
    def raise_exception(*args: object, **kwargs: object) -> _FakeResponse:
        raise exception

    monkeypatch.setattr(lifecycle_client.urllib.request, "urlopen", raise_exception)


def _run_json(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict[str, Any], str]:
    exit_code = cli.main([*argv, "--json"])
    captured = capsys.readouterr()
    return exit_code, json.loads(captured.out), captured.err


def test_send_command_accepts_only_documented_response(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _install_response(monkeypatch, 202, _body(_accepted_response()))

    exit_code, payload, stderr = _run_json(
        capsys,
        [
            "send-command",
            "--url",
            "http://127.0.0.1:9000/command",
            "--command",
            "read-status",
            *CONTEXT_ARGS,
        ],
    )

    assert exit_code == 0
    assert payload["status"] == "accepted"
    assert payload["worker_job_id"] == "worker-job-1"
    assert payload["http_status"] == 202
    assert payload["ok"] is True
    assert stderr == ""


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (202, b""),
        (201, _body(_accepted_response())),
        (202, b"{"),
        (202, b"[]"),
        (202, _body({**_accepted_response(), "status": "queued"})),
        (202, _body(_accepted_response(command="identify"))),
        (202, _body({key: value for key, value in _accepted_response().items() if key != "worker_job_id"})),
    ],
    ids=("empty", "unexpected-status", "malformed", "array", "invalid-status", "wrong-command", "missing-worker-id"),
)
def test_send_command_rejects_invalid_success_response(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
    body: bytes,
) -> None:
    _install_response(monkeypatch, status, body)

    exit_code, payload, stderr = _run_json(
        capsys,
        [
            "send-command",
            "--url",
            "http://127.0.0.1:9000/command",
            "--command",
            "read-status",
            *CONTEXT_ARGS,
        ],
    )

    assert exit_code == 3
    assert payload["error"]["code"] == "invalid_response"
    assert payload["http_status"] == status
    assert payload["error_phase"] == "invalid_response"
    assert payload["ok"] is False
    assert payload["exit_code"] == 3
    assert stderr == ""


def test_stop_accepts_documented_200_response_in_text_mode(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _install_response(monkeypatch, 200, _body({"ok": True, "message": "Stop requested"}))

    exit_code = cli.main(["stop", "--url", "http://127.0.0.1:9000/stop"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == "OK\n"
    assert captured.err == ""


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (200, b""),
        (200, b"{"),
        (200, b"[]"),
        (200, b"true"),
        (200, _body({"message": "Stop requested"})),
        (200, _body({"ok": "true", "message": "Stop requested"})),
        (202, _body({"ok": True, "message": "Stop requested"})),
        (201, _body({"ok": True, "message": "Stop requested"})),
        (200, _body({"ok": True})),
        (200, _body({"ok": True, "message": ""})),
    ],
    ids=(
        "empty",
        "malformed",
        "array",
        "scalar",
        "missing-ok",
        "invalid-ok",
        "unexpected-202",
        "unexpected-201",
        "missing-message",
        "empty-message",
    ),
)
def test_stop_rejects_invalid_success_response(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
    body: bytes,
) -> None:
    _install_response(monkeypatch, status, body)

    exit_code, payload, stderr = _run_json(capsys, ["stop", "--url", "http://127.0.0.1:9000/stop"])

    assert exit_code == 3
    assert payload["error"]["code"] == "invalid_response"
    assert payload["http_status"] == status
    assert payload["ok"] is False
    assert payload["exit_code"] == 3
    assert stderr == ""


def test_send_command_rejects_mismatched_job_identity(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _install_response(monkeypatch, 202, _body(_accepted_response(job_id=None)))

    exit_code, payload, stderr = _run_json(
        capsys,
        [
            "send-command",
            "--url", "http://127.0.0.1:9000/command",
            "--command", "read-status",
            "--job-id", "client-job-1",
            *CONTEXT_ARGS,
        ],
    )

    assert exit_code == 3
    assert payload["error"]["code"] == "invalid_response"
    assert payload["error_phase"] == "invalid_response"
    assert stderr == ""


def test_status_accepts_documented_200_response(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _install_response(monkeypatch, 200, _body(_status_response()))

    exit_code, payload, stderr = _run_json(capsys, ["status", "--url", "http://127.0.0.1:9000/status"])

    assert exit_code == 0
    assert payload["status"] == "ready"
    assert payload["service"] == "powers-tool"
    assert payload["http_status"] == 200
    assert stderr == ""


def test_status_accepts_lifecycle_identity_without_display_fields(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_response(
        monkeypatch,
        200,
        _body({"schema_version": 2, "service": "powers-tool", "run_id": "run-1", "status": "ready"}),
    )

    exit_code, payload, stderr = _run_json(capsys, ["status", "--url", "http://127.0.0.1:9000/status"])

    assert exit_code == 0
    assert payload["status"] == "ready"
    assert stderr == ""


def test_status_accepts_artifact_failure_without_path_and_additive_fields(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    response = {
        **_status_response(status="error"),
        "last_job": {
            "worker_job_id": "worker-job-1",
            "job_id": None,
            "command": "read-status",
            "status": "failed",
            "artifact_available": False,
            "error": {"code": "artifact_error"},
            "artifact_error": {"code": "artifact_error"},
            "future_job_field": "accepted",
        },
        "future_status_field": "accepted",
    }
    _install_response(monkeypatch, 200, _body(response))

    exit_code, payload, stderr = _run_json(capsys, ["status", "--url", "http://127.0.0.1:9000/status"])

    assert exit_code == 0
    assert payload["last_job"]["artifact_available"] is False
    assert "artifact_path" not in payload["last_job"]
    assert payload["future_status_field"] == "accepted"
    assert stderr == ""


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (200, b""),
        (202, _body(_status_response())),
        (200, _body({**_status_response(), "status": "unknown"})),
    ],
    ids=("empty", "unexpected-status", "invalid-worker-status"),
)
def test_status_rejects_invalid_success_response(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
    body: bytes,
) -> None:
    _install_response(monkeypatch, status, body)

    exit_code, payload, stderr = _run_json(capsys, ["status", "--url", "http://127.0.0.1:9000/status"])

    assert exit_code == 3
    assert payload["error"]["code"] == "invalid_response"
    assert payload["http_status"] == status
    assert stderr == ""


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (200, _body(_status_response())),
        (200, b""),
        (202, _body(_status_response())),
        (200, _body({**_status_response(), "status": "unknown"})),
    ],
    ids=("ready", "empty", "unexpected-status", "invalid-worker-status"),
)
def test_wait_ready_validates_each_status_response(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
    body: bytes,
) -> None:
    _install_response(monkeypatch, status, body)

    exit_code, payload, stderr = _run_json(
        capsys,
        [
            "wait-ready",
            "--url", "http://127.0.0.1:9000/status",
            "--timeout-ms", "100",
            "--wait-timeout-ms", "100",
            "--poll-ms", "1",
        ],
    )

    if status == 200 and body == _body(_status_response()):
        assert exit_code == 0
        assert payload["status"] == "ready"
    else:
        assert exit_code == 3
        assert payload["error"]["code"] == "invalid_response"
        assert payload["http_status"] == status
    assert stderr == ""


@pytest.mark.parametrize(
    ("http_status", "expected_exit"),
    [(400, 2), (409, 3), (429, 3)],
)
def test_send_command_preserves_http_error_exit_mapping(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    http_status: int,
    expected_exit: int,
) -> None:
    _install_exception(
        monkeypatch,
        urllib.error.HTTPError(
            "http://127.0.0.1:9000/command",
            http_status,
            "error",
            None,
            io.BytesIO(_body({"status": "error", "error": {"code": "worker_error", "message": "failed"}})),
        ),
    )

    exit_code, payload, stderr = _run_json(
        capsys,
        [
            "send-command",
            "--url",
            "http://127.0.0.1:9000/command",
            "--command",
            "read-status",
            *CONTEXT_ARGS,
        ],
    )

    assert exit_code == expected_exit
    assert payload["error"]["code"] == "worker_error"
    assert payload["http_status"] == http_status
    assert payload["error_phase"] == "http_status"
    assert stderr == ""


def test_send_command_preserves_connection_error_mapping(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _install_exception(monkeypatch, urllib.error.URLError("offline"))

    exit_code, payload, stderr = _run_json(
        capsys,
        [
            "send-command",
            "--url",
            "http://127.0.0.1:9000/command",
            "--command",
            "read-status",
            *CONTEXT_ARGS,
        ],
    )

    assert exit_code == 3
    assert payload["error"]["code"] == "connection_failed"
    assert payload["http_status"] is None
    assert payload["error_phase"] == "connection"
    assert stderr == ""
