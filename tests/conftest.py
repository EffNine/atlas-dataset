"""Shared pytest configuration — ensures scripts/ is on sys.path."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))
