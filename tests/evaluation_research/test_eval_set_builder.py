"""Test module."""
import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import pytest
from evaluation_research.eval_set_builder import EvalSetBuilder, FrozenEvalSet


def _ensure_scripts_on_path():
    import sys
    from pathlib import Path
    _p = Path(__file__).resolve().parent.parent.parent / 'scripts'
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_ensure_scripts_on_path()
