#!/usr/bin/env python3
"""dashboard.server — entry point for the Atlas Engineering Dashboard.

Usage (from the repository root):

    python -m scripts.dashboard.server [--host 127.0.0.1] [--port 8765]

Environment:
    ATLAS_DASHBOARD_TOKEN   when set, /api/* requires
                            "Authorization: Bearer <token>"
    ATLAS_WORKERS_DASHBOARD job-pool worker override (see ADR-013)

The server binds to the loopback interface by default. It never exposes
environment values, credentials or filesystem secrets through the API.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow `python scripts/dashboard/server.py` direct execution.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aiohttp import web  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="atlas-dashboard",
        description="Atlas Engineering Dashboard (read-only state + governed "
                    "action orchestration)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (default: 127.0.0.1 loopback)")
    ap.add_argument("--port", type=int, default=8765,
                    help="bind port (default: 8765)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    # Dashboard modules use top-level imports per repo convention
    # (pytest.ini: pythonpath = scripts). Ensure scripts/ is importable for
    # both `python -m scripts.dashboard.server` and direct script execution.
    scripts_dir = Path(__file__).resolve().parents[1]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    from dashboard.app import create_app
    app = create_app()
    web.run_app(app, host=args.host, port=args.port, print=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
