"""Test module."""
import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import pytest
from evaluation_research.benchmark_discover import discover_all, discover_benchmark, register_benchmark


def _ensure_scripts_on_path():
    import sys
    from pathlib import Path
    _p = Path(__file__).resolve().parent.parent.parent / 'scripts'
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_ensure_scripts_on_path()
