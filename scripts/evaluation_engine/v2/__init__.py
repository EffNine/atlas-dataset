"""evaluation_engine.v2 — QEE v2: verifiable correctness evaluation.

Phase 5A.2 deliverable. Additive to the v1 engine (scripts/quality_score.py);
does not modify or replace it. Provides:

  * math_eval        — final-answer extraction + equivalent-expression checks.
  * code_eval        — syntax validation, structural/patch comparison, tests.
  * semantic_eval    — rubric-based answer evaluation with anti-stuffing.
  * engine           — QeeV2Engine (schema-compatible quality scoring).
  * calibration      — v1-vs-v2 before/after comparison + calibration fitting.
"""

from .engine import QeeV2Engine, evaluate_record, score_record, WEIGHTS

__all__ = ["QeeV2Engine", "evaluate_record", "score_record", "WEIGHTS"]
