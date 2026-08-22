"""Test import helper — shared paths for test modules."""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
