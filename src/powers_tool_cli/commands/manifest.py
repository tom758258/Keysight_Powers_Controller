"""Tool manifest command: static tool identity and protocol introspection."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from powers_tool_cli import cli_parser as parser_helpers
from powers_tool_cli.cli_io import SCHEMA_VERSION
from powers_tool_cli.cli_runtime import _package_version
from powers_tool_cli.worker_protocol import WORKER_SCHEMA_VERSION

MANIFEST_EVENT = "tool_manifest"
TOOL_ID = "powers"
WORKER_COMPATIBILITY_POLICY = "v2-only"


def register_commands(
    subparsers: argparse._SubParsersAction[Any],
) -> None:
    parser = subparsers.add_parser(
        "manifest",
        help="Print static tool identity and Worker protocol compatibility.",
    )
    parser_helpers._add_lifecycle_format_arguments(parser)
    parser.set_defaults(func=run_manifest)


def build_manifest(
    version_provider: Callable[[], str] = _package_version,
) -> dict[str, Any]:
    return {
        "event": MANIFEST_EVENT,
        "schema_version": SCHEMA_VERSION,
        "tool_id": TOOL_ID,
        "tool_version": version_provider(),
        "worker_protocol": {
            "compatibility_policy": WORKER_COMPATIBILITY_POLICY,
            "schema_versions": [WORKER_SCHEMA_VERSION],
        },
    }


def run_manifest(args: argparse.Namespace) -> int:
    manifest = build_manifest()
    if getattr(args, "format", "text") == "json":
        print(json.dumps(manifest, sort_keys=True))
    else:
        protocol = manifest["worker_protocol"]
        print(f"{TOOL_ID} {manifest['tool_version']}")
        print(
            f"Worker protocol: {protocol['compatibility_policy']} "
            f"(schema versions: {', '.join(str(v) for v in protocol['schema_versions'])})"
        )
    return 0
