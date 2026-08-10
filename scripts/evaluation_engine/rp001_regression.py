#!/usr/bin/env python3
"""rp001_regression.py — RP-001 regression corpus runner.

Evaluates a fixed, deterministic corpus of (family, reference, candidate)
inputs through the on-disk QEE v2 evaluators and serializes every result (or a
CRASH marker) to a JSONL file. The same corpus is run BEFORE and AFTER the
RP-001 patch; the two dumps are compared to prove that every previously
non-crashing evaluation produces identical outputs and scores, and that the
previously crashing inputs no longer crash.

Corpus (deterministic):
  * every canonical_answer of ``math_eval_v2`` (N=100) as reference, with
    candidate = reference (self-eval) and candidate = reference + " =" (the
    fixed path),
  * the real Qwen2.5 smoke responses (3 math, 3 code),
  * a set of crafted edge cases (bare trailing "=" and friends),
  * a code corpus through ``CodeAnswerEvaluator`` (unaffected by the patch).

Usage:
    python rp001_regression.py --out before.jsonl [--math-only]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

MATH_EVAL = REPO / "evaluation" / "eval_sets" / "protocol_v2" / "math_eval_v2.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def run_case(family: str, reference: str, candidate: str, idx: int) -> dict:
    from evaluation_engine.v2.math_eval import MathAnswerEvaluator
    from evaluation_engine.v2.code_eval import CodeAnswerEvaluator

    base = {"idx": idx, "family": family, "candidate_tail": candidate[-60:]}
    try:
        if family == "math":
            r = MathAnswerEvaluator().evaluate(reference=reference, candidate=candidate)
            payload = {
                "correct": r.correct, "score": r.score, "method": r.method,
                "extracted_reference": r.extracted_reference,
                "extracted_candidate": r.extracted_candidate,
                "normalized_reference": r.normalized_reference,
                "normalized_candidate": r.normalized_candidate,
                "reason": r.reason, "confidence": r.confidence,
            }
        else:
            r = CodeAnswerEvaluator().evaluate(reference=reference, candidate=candidate)
            payload = {
                "correct": r.correct, "score": r.score, "method": r.method,
                "reason": r.reason, "confidence": r.confidence,
                "details": r.details,
            }
        return {**base, "status": "ok", "result": payload}
    except Exception as exc:  # noqa: BLE001 - record crash for the regression diff
        return {**base, "status": "crash", "error": f"{type(exc).__name__}: {exc}"}


def build_corpus() -> list[dict]:
    corpus: list[dict] = []
    math_recs = load_jsonl(MATH_EVAL)
    refs = [r.get("canonical_answer") or "" for r in math_recs]

    # (family, reference, candidate) triples
    triples: list[tuple[str, str, str]] = []
    for i, ref in enumerate(refs):
        triples.append(("math", ref, ref))            # self-eval (full path)
        triples.append(("math", ref, ref + " ="))      # bare trailing '=' (fixed path)
        triples.append(("math", ref, ""))              # empty candidate

    # Real Qwen2.5 smoke responses (captured from the 2026-08-06 smoke run).
    smoke_math = [
        "To solve this problem, we need to calculate the total revenue from selling "
        "large pizzas during both weekends and weekdays, then find the difference "
        "between the two.\n\n### Step 1: Calculate the number of pizzas sold "
        "dur",
        "To solve the given problem, we need to rewrite the quadratic expression "
        "\\(x^2 + 1300x + 1300\\) in the form \\((x + b)^2 + c\\).\n\n### Step 1: "
        "Completing the Square\nStart ",
        "To find the least positive difference between a term of the arithmetic "
        "sequence \\(2, 9, 16, 23, 30, \\ldots\\) and a term of the sequence "
        "defined by \\(a_n = n^2\\), we first need to express these sequences "
        "mathematica",
    ]
    smoke_code = [
        "diff --git a/src/feature_union.py b/src/feature_union.py\n"
        "@@ -1,3 +1,4 @@\n def transform(self, X):\n-    return X\n+    return "
        "pd.DataFrame(X)",
        "The fix is to add a type check.\n\n```python\nif isinstance(x, int):\n"
        "    return x + 1\n```",
        "This issue can be resolved by updating the return statement.",
    ]
    for ref in refs[:3]:
        for s in smoke_math:
            triples.append(("math", ref, s))

    for r in refs[:3]:
        for s in smoke_code:
            triples.append(("code", r, s))
    # A realistic gold-patch reference for the code smoke checks.
    triples.append(("code", "diff --git a/x b/x\n@@ -1 +1 @@\n-a\n+b", "diff --git a/x b/x\n@@ -1 +1 @@\n-a\n+b"))

    # Crafted edge cases (math).
    edges = [
        "", "   ", "The answer is =", "x = ", "a=b", "x = y =", "= =",
        "foo\n\nbar =", "42 =", "=42", "x = y = z", "answer =",
        "\\boxed{5}=", "The result is 5 =", "5 =\n\n", "= x", "a = b = c =",
        "final answer: =", "x = y =\n\n",
    ]
    for e in edges:
        triples.append(("math", "5", e))
        triples.append(("math", "", e))

    for t in triples:
        corpus.append({"family": t[0], "reference": t[1], "candidate": t[2]})
    return corpus


def main() -> int:
    ap = argparse.ArgumentParser(description="RP-001 regression corpus runner")
    ap.add_argument("--out", required=True, help="output JSONL path")
    args = ap.parse_args()

    corpus = build_corpus()
    out = []
    for i, case in enumerate(corpus):
        row = run_case(case["family"], case["reference"], case["candidate"], i)
        out.append(row)

    with open(args.out, "w", encoding="utf-8") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    n_crash = sum(1 for r in out if r["status"] == "crash")
    print(f"[RP001] wrote {len(out)} results to {args.out} "
          f"(crashes={n_crash})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
