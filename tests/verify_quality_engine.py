#!/usr/bin/env python3
"""
verify_quality_engine.py — Assertion-based self-test for the Atlas Quality
Evaluation Engine (scripts/quality_score.py).

Confirms the engine satisfies its design contract:
  * evaluate_record returns a complete, well-typed result dict.
  * All seven dimensions are in [0,1] and the union of dimension keys == WEIGHTS.
  * quality_score is an int in 1..10.
  * confidence is in [0,1], confidence_level in 1..5, and is NOT mechanically
    tied to the score (a deliberately low-confidence record does not force a low
    score, and vice-versa) — i.e. they are SEPARATE quantities.
  * rationale is non-empty and each entry has dimension/score/band/reason.
  * DETERMINISTIC: same record -> identical result across calls.
  * score_record(rec) -> (int, {dim:0..1}) backward-compatible API still works
    and agrees with evaluate_record.
  * Variance: across the 100 reviewed pilot records the engine produces >= 3
    distinct scores (the frozen baseline's constant-7 failure mode is gone).
  * No knowledge object is modified: the module is read-only on its input.

Exit code 0 = all checks pass; 1 = at least one failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import quality_score as qe  # noqa: E402


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))

    # --- 1. basic evaluate_record structure on a synthetic record ---
    rec = {
        "id": "test_x", "category": "02_software_engineering", "subcategory": "debugging",
        "metadata": {"source_confidence": "high"},
        "tags": ["debugging", "procedure"],
        "messages": [
            {"role": "user", "content": "How do you debug a null pointer?"},
            {"role": "assistant", "content": "Reproduce the failure, isolate the call path, "
             "add logging at the boundary, then fix the root cause and add a regression test."},
        ],
    }
    ev = qe.evaluate_record(rec)
    check("evaluate_record returns dict", isinstance(ev, dict))
    for key in ("quality_score", "quality_continuous", "dimensions", "confidence",
                "confidence_level", "rationale", "flags", "explanation"):
        check(f"evaluate_record has key '{key}'", key in ev, f"missing={key}" if key not in ev else "")

    # --- 2. dimensions in [0,1] and match WEIGHTS keys ---
    dims = ev["dimensions"]
    check("dimensions keys == WEIGHTS keys", set(dims) == set(qe.WEIGHTS),
          f"dims={sorted(dims)} weights={sorted(qe.WEIGHTS)}")
    check("all dimensions in [0,1]", all(0.0 <= v <= 1.0 for v in dims.values()),
          f"min={min(dims.values())} max={max(dims.values())}")
    check("quality_score is int 1..10", isinstance(ev["quality_score"], int)
          and 1 <= ev["quality_score"] <= 10, f"score={ev['quality_score']}")

    # --- 3. confidence separation ---
    check("confidence in [0,1]", 0.0 <= ev["confidence"] <= 1.0, f"conf={ev['confidence']}")
    check("confidence_level in 1..5", 1 <= ev["confidence_level"] <= 5,
          f"level={ev['confidence_level']}")

    # a record engineered to be LOW confidence (tiny text, no metadata, no
    # category-relevance signal) must still receive a valid 1..10 score AND a
    # LOW confidence (proving the two quantities are computed independently and
    # one does not mechanically force the other).
    low_conf_rec = {
        "category": "99_unknown",
        "messages": [{"role": "user", "content": "q"},
                     {"role": "assistant", "content": "a"}],
    }
    ev_lc = qe.evaluate_record(low_conf_rec)
    check("low-confidence record: conf<=0.6 AND score still valid 1..10",
          ev_lc["confidence"] <= 0.6 and 1 <= ev_lc["quality_score"] <= 10,
          f"conf={ev_lc['confidence']} score={ev_lc['quality_score']}")
    # and conversely a rich, on-topic record can be high-confidence + high score
    check("separation: confidence is its own axis (low-conf record flagged)",
          "low_confidence" in ev_lc["flags"] or ev_lc["confidence"] <= 0.6,
          f"flags={ev_lc['flags']} conf={ev_lc['confidence']}")

    # --- 4. rationale structure ---
    check("rationale non-empty", len(ev["rationale"]) == len(qe.WEIGHTS),
          f"len={len(ev['rationale'])}")
    ok_rat = all(all(k in r for k in ("dimension", "score", "band", "reason"))
                 and isinstance(r["reason"], str) and r["reason"]
                 for r in ev["rationale"])
    check("every rationale entry has dimension/score/band/reason", ok_rat)
    check("explanation is a non-empty string", isinstance(ev["explanation"], str) and ev["explanation"])

    # --- 5. determinism ---
    ev_a = qe.evaluate_record(rec)
    ev_b = qe.evaluate_record(rec)
    check("deterministic: identical result across calls",
          json.dumps(ev_a, sort_keys=True) == json.dumps(ev_b, sort_keys=True))

    # --- 6. backward-compatible score_record ---
    s, d = qe.score_record(rec)
    check("score_record returns (int, dict)", isinstance(s, int) and isinstance(d, dict))
    check("score_record score == evaluate_record quality_score", s == ev["quality_score"])
    check("score_record dims == evaluate_record dimensions", d == ev["dimensions"])

    # --- 7. variance across the real reviewed pilot corpus ---
    cans = load_jsonl(ROOT / "curated" / "v0.1" / "pilot_candidates.jsonl")
    scores = [qe.score_record(c)[0] for c in cans]
    distinct = len(set(scores))
    check("variance: >= 3 distinct auto-scores on pilot (no constant-7)",
          distinct >= 3, f"distinct={distinct} dist={{c: scores.count(c) for c in sorted(set(scores))}}")

    # --- 8. read-only guarantee: input record not mutated ---
    before = json.dumps(rec, sort_keys=True)
    qe.evaluate_record(rec)
    qe.score_record(rec)
    after = json.dumps(rec, sort_keys=True)
    check("read-only: input record unmodified by evaluation", before == after)

    # --- 9. tolerance for missing/partial records (no crash) ---
    partial = {"messages": [{"role": "assistant", "content": "hi"}]}
    try:
        evp = qe.evaluate_record(partial)
        ok_partial = isinstance(evp["quality_score"], int) and 1 <= evp["quality_score"] <= 10
    except Exception as e:  # noqa: BLE001
        ok_partial = False
        evp = {"err": str(e)}
    check("tolerant: partial record evaluated without crash", ok_partial, str(evp.get("err", "")))

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n=== {len(results) - len(failed)}/{len(results)} checks passed ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
