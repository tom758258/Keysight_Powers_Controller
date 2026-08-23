"""Configuration loading and validation for Powers Tool worker."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from powers_tool_core.connection import SerialOptions, normalize_serial_termination
from powers_tool_cli.worker_protocol import (
    _FORBIDDEN_VALIDATION_MODE_SETTINGS,
    _IDENTITY_SETTING_FIELDS,
)


def load_worker_config(args: argparse.Namespace) -> dict[str, Any]:
    """Load configuration from config path and apply CLI argument overrides."""
    config: dict[str, Any] = {
        "id": "power_1",
        "type": "power",
        "enabled": True,
        "mode": "simulate",
        "control_host": "127.0.0.1",
        "control_port": 0,
        "artifacts_dir": ".tmp_tests/power_worker/power_1",
        "events_jsonl": None,
        "artifact_mode": "files",
        "settings": {
            "resource": "USB0::SIM::E36312A::INSTR",
            "resource_alias": None,
            "backend": None,
            "timeout_ms": 5000,
            "serial_options": {},
            "serial_remote": False,
            "serial_local_on_close": False,
            "safety_config": None,
            "allow_output_writes": False,
        },
    }

    if getattr(args, "config", None):
        cfg_path = Path(args.config)
        if not cfg_path.exists():
            raise FileNotFoundError(f"Config file not found: {args.config}")
        with open(cfg_path, encoding="utf-8") as f:
            file_cfg = json.load(f)

        for k in [
            "id",
            "type",
            "enabled",
            "mode",
            "control_host",
            "control_port",
            "artifacts_dir",
            "events_jsonl",
            "artifact_mode",
        ]:
            if k in file_cfg:
                config[k] = file_cfg[k]

        if "settings" in file_cfg:
            for k, v in file_cfg["settings"].items():
                config["settings"][k] = v

    if getattr(args, "id", None) is not None:
        config["id"] = args.id
    if getattr(args, "mode", None) is not None:
        config["mode"] = args.mode
    if getattr(args, "control_port", None) is not None:
        config["control_port"] = args.control_port
    if getattr(args, "artifacts_dir", None) is not None:
        config["artifacts_dir"] = args.artifacts_dir
    else:
        if not getattr(args, "config", None):
            config["artifacts_dir"] = f".tmp_tests/power_worker/{config['id']}"

    if getattr(args, "artifact_mode", None) is not None:
        config["artifact_mode"] = args.artifact_mode

    if getattr(args, "events_jsonl", None) is not None:
        config["events_jsonl"] = args.events_jsonl
    else:
        if not getattr(args, "config", None) and config["artifact_mode"] != "memory":
            config["events_jsonl"] = f"{config['artifacts_dir']}/events.jsonl"

    if config["artifact_mode"] != "memory" and not config.get("events_jsonl"):
        config["events_jsonl"] = f"{config['artifacts_dir']}/events.jsonl"

    if getattr(args, "resource", None) is not None:
        config["settings"]["resource"] = args.resource
    _validate_worker_config(config)
    return config


def _validate_worker_config(config: dict[str, Any]) -> None:
    if config["type"] != "power":
        raise ValueError(f"Worker type must be 'power', got {config['type']!r}")

    if not isinstance(config.get("enabled"), bool):
        raise ValueError(f"Worker enabled must be a boolean, got {config.get('enabled')!r}")
    if config["enabled"] is False:
        raise ValueError("Worker enabled=false is not runnable")

    if config.get("mode") not in {"simulate", "live"}:
        raise ValueError(f"Worker mode must be 'simulate' or 'live', got {config.get('mode')!r}")

    artifact_mode = config.get("artifact_mode", "files")
    if artifact_mode not in {"files", "memory"}:
        raise ValueError(
            f"Worker artifact mode must be 'files' or 'memory', got {artifact_mode!r}"
        )
    if artifact_mode == "memory" and config.get("events_jsonl"):
        raise ValueError(
            "Worker artifact mode 'memory' streams events to stdout only and "
            "cannot write an events.jsonl file"
        )

    host = config["control_host"]
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError(f"Control host {host!r} is not allowed. Bind host must be localhost (127.0.0.1) in v1.")

    port = config.get("control_port")
    if not isinstance(port, int) or isinstance(port, bool) or not (0 <= port <= 65535):
        raise ValueError(f"Control port must be an integer from 0 to 65535, got {port!r}")

    settings = config.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("Worker settings must be an object")
    if "default_action" in settings:
        raise ValueError("settings.default_action is not supported; use POST /command")
    attempted_runtime_modes = sorted(_FORBIDDEN_VALIDATION_MODE_SETTINGS & set(settings))
    if attempted_runtime_modes:
        raise ValueError(
            "settings validation support policy mode is not available to Worker: "
            f"{', '.join(attempted_runtime_modes)}"
        )
    identity_settings = sorted(_IDENTITY_SETTING_FIELDS & set(settings))
    if identity_settings:
        raise ValueError(
            "Worker identity selection belongs to each request; settings fields are not allowed: "
            f"{', '.join(identity_settings)}"
        )
    serial_options = settings.get("serial_options")
    if serial_options is not None and not isinstance(serial_options, dict):
        raise ValueError("settings.serial_options must be an object")
    for key in ("serial_remote", "serial_local_on_close"):
        if key in settings and not isinstance(settings[key], bool):
            raise ValueError(f"settings.{key} must be a boolean")


def _serial_options_from_settings(settings: dict[str, Any]) -> SerialOptions | None:
    serial = settings.get("serial_options")
    if not isinstance(serial, dict):
        return None
    options = SerialOptions(
        baud_rate=_optional_int(serial.get("baud_rate")),
        data_bits=_optional_int(serial.get("data_bits")),
        parity=_optional_str(serial.get("parity")),
        stop_bits=serial.get("stop_bits"),
        flow_control=_optional_str(serial.get("flow_control")),
        read_termination=normalize_serial_termination(serial.get("read_termination")),
        write_termination=normalize_serial_termination(serial.get("write_termination")),
    )
    return options if options.has_explicit_values() else None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text != "" else None


def _validate_event_sink(config: dict[str, Any]) -> None:
    events_file = config.get("events_jsonl")
    if not events_file:
        return
    p = Path(events_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8"):
        pass
