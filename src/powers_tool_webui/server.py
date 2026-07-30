"""Server entry point for Powers Tool WebUI."""

from __future__ import annotations

import argparse
import sys

from . import __version__ as WEBUI_VERSION


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Powers Tool WebUI Server")
    parser.add_argument(
        "--version",
        action="version",
        version=f"powers-tool-webui {WEBUI_VERSION}",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=7999, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    args = parser.parse_args(argv)

    try:
        import uvicorn

        from .app import app
    except ModuleNotFoundError as exc:
        missing = exc.name or "webui runtime dependency"
        print(
            f"Missing optional WebUI dependency {missing!r}. "
            'From the repository root, run `uv sync --extra webui --locked --link-mode=copy`.',
            file=sys.stderr,
        )
        raise SystemExit(2) from exc

    print(f"Starting Powers Tool WebUI on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
