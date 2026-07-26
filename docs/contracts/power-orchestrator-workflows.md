# Power Orchestrator Workflows

Schema version: `2`

This document extends `common-orchestrator-workflows.md` with Power-specific examples and safety policy.

## Startup

Start the Worker with `powers-tool worker`. Wait for the `ready` event and use `command_url`, `status_url`, and `stop_url`. If `ready` is missed, poll `GET /status`. Do not expect `trigger_url` or `default_action`.

## Read-Only Check

Use `GET /status` only for Worker lifecycle state. Use `POST /command` with `command: "read-status"` for instrument output state and error queue reads.

```json
{
  "schema_version": 2,
  "command": "read-status",
  "arguments": { "channel": "all" },
  "context": {
    "mode": "dry_run",
    "planning_model_id": "keysight-e36312a"
  }
}
```

## Live Output Writes

For live output-affecting commands, configure the Worker with
`settings.allow_output_writes: true` and send `arguments.confirm_output: true`.
The optional expected model remains a live mismatch guard.

```json
{
  "schema_version": 2,
  "command": "apply",
  "arguments": {
    "channel": 1,
    "voltage": 1.2,
    "current": 0.1,
    "confirm_output": true
  },
  "job_id": "orchestrator-apply-1",
  "context": {
    "mode": "live",
    "expected_model_id": "keysight-e36312a"
  }
}
```

If either output-write gate is missing, the Worker returns `409` and does not enqueue work or open VISA.

## Artifacts

Use `worker_job_id` or the accepted response `artifact_path` to locate results. Do not infer artifact paths from omitted client `job_id`.

## Python Subprocess Example

```python
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


def start_stdout_reader(proc):
    lines = queue.Queue()

    def reader():
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            lines.put(raw_line)
        lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    return lines


def read_jsonl_until(proc, lines, event_name, timeout_s=10):
    deadline = time.monotonic() + timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"worker did not emit {event_name}")
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            if proc.poll() is not None:
                raise RuntimeError(f"worker exited before {event_name}") from None
            raise TimeoutError(f"worker did not emit {event_name}") from None
        if line is None:
            raise RuntimeError(f"worker stdout closed before {event_name}")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"worker stdout was not JSON: {line!r}") from exc
        if event.get("event") == event_name:
            return event


def run_client(*args):
    completed = subprocess.run(
        [sys.executable, "-m", "powers_tool_cli.cli", *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)


port = None
proc = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "powers_tool_cli.cli",
        "worker",
        "--mode",
        "simulate",
        "--control-port",
        "0",
        "--artifacts-dir",
        ".tmp/power-worker",
    ],
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)

stdout_lines = start_stdout_reader(proc)
try:
    ready = read_jsonl_until(proc, stdout_lines, "ready")
    assert ready["service"] == "powers-tool"
    assert ready["run_id"]
    assert "trigger_url" not in ready
    port = str(ready["port"])

    wait_ready = run_client("wait-ready", "--port", port, "--json")
    assert wait_ready["run_id"] == ready["run_id"]

    status = run_client("status", "--port", port, "--json")
    assert status["run_id"] == ready["run_id"]

    accepted = run_client(
        "send-command",
        "--port",
        port,
        "--command",
        "read-status",
        "--context-json",
        json.dumps({
            "mode": "simulate",
            "planning_model_id": "keysight-e36312a",
        }),
        "--job-id",
        "client-job-1",
        "--json",
    )
    assert accepted["status"] == "accepted"
    assert accepted["ok"] is True
    assert accepted["job_id"] == "client-job-1"
    assert accepted["worker_job_id"]
    artifact_dir = Path(accepted["artifact_path"])
    assert artifact_dir.is_dir()
    assert (artifact_dir / "request.json").is_file()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = run_client("status", "--port", port, "--json")
        if status.get("last_job", {}).get("worker_job_id") == accepted["worker_job_id"]:
            break
        result_path = artifact_dir / "result.json"
        if result_path.exists():
            break
        time.sleep(0.2)
    else:
        raise TimeoutError("job did not finish")

    result = json.loads((artifact_dir / "result.json").read_text(encoding="utf-8"))
    assert result["run_id"] == ready["run_id"]
    assert result["worker_job_id"] == accepted["worker_job_id"]
    assert result["command"] == {"name": "read-status"}
    assert result["ok"] is True
    assert result["status"] == "succeeded"
finally:
    if proc.poll() is None:
        if port is not None:
            try:
                run_client("stop", "--port", port, "--json")
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

assert proc.returncode == 0
```

## Stop

`POST /stop` is outside the normal command queue. It requests cooperative cleanup and must not perform long VISA I/O in the HTTP handler thread.
