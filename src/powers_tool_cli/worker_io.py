"""Thread-safe event emission and atomic artifact publishing for Powers Tool worker."""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import sys
import threading
from typing import Any
import uuid

from powers_tool_cli.worker_protocol import WORKER_SCHEMA_VERSION

_event_lock = threading.Lock()
_sequence_counter = 1


def emit_event(
    config: dict[str, Any],
    event_name: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Thread-safe event logger writing both to stdout and to events_jsonl file."""
    global _sequence_counter
    with _event_lock:
        timestamp = (
            datetime.datetime.now(datetime.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        payload = {
            "schema_version": WORKER_SCHEMA_VERSION,
            "event": event_name,
            "worker_id": config["id"],
            "type": "power",
            "timestamp_utc": timestamp,
            "sequence": _sequence_counter,
        }
        if extra:
            payload.update(extra)
        _sequence_counter += 1

        encoded = json.dumps(payload, sort_keys=True)
        print(encoded, flush=True)

        events_file = config.get("events_jsonl")
        if events_file:
            try:
                p = Path(events_file)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "a", encoding="utf-8") as f:
                    f.write(encoded + "\n")
            except Exception as exc:
                print(f"worker event log write failed: {exc}", file=sys.stderr, flush=True)


def _write_json_artifact_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Publish a JSON artifact only after its full contents are durable."""
    encoded = json.dumps(payload, indent=2, sort_keys=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise
