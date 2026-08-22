"""Shared setup for evaluation_research tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
