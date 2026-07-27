#!/usr/bin/env python3
"""
probe_frozen_baseline.py — Phase 3C.1 FRESH verification probe.

Runs against the CURRENT on-disk artifacts (nothing is generated here; this is
purely a read-only assertion sweep). Confirms the freeze is valid:

  1. Dataset size unchanged: raw/pilot/seed.jsonl and
     curated/v0.1/pilot_candidates.jsonl still hold exactly 100 records each
     (no bulk ingestion occurred).
  2. Review decisions unchanged: review/quality_reviews.jsonl still holds 100
     reviews with the same verdict set recorded in the baseline.
  3. Checksum registry matches the live files (no accidental modification).
  4. The frozen baseline file is internally consistent with the live
     calibration (reviewed count, distributions sum, verdict counts).
  5. The canonical calibration self-test still passes (no regression in the
     framework the baseline was built from).

Exit 0 = all checks pass; 1 = at least one failure.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import freeze_calibration_baseline as fcb  # noqa: E402


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def main() -> int:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))

    baseline = json.loads((ROOT / "metadata" / "calibration_baseline_v0.1.json").read_text())
    reg = json.loads((ROOT / "metadata" / "checksums_v0.1.json").read_text())

    # 1. dataset size unchanged
    raw = load_jsonl(ROOT / "raw" / "pilot" / "seed.jsonl")
    cur = load_jsonl(ROOT / "curated" / "v0.1" / "pilot_candidates.jsonl")
    check("dataset: raw/pilot/seed.jsonl == 100 records", len(raw) == 100, f"got {len(raw)}")
    check("dataset: curated/v0.1/pilot_candidates.jsonl == 100 records",
          len(cur) == 100, f"got {len(cur)}")

    # 2. review decisions unchanged
    reviews = load_jsonl(ROOT / "review" / "quality_reviews.jsonl")
    check("review: quality_reviews.jsonl == 100 reviews", len(reviews) == 100, f"got {len(reviews)}")
    from collections import Counter
    verdicts = Counter(str(r.get("verdict", "")).lower() for r in reviews)
    base_verdicts = baseline["verdict_distribution"]
    check("review: verdict set matches baseline",
          dict(verdicts) == base_verdicts, f"live={dict(verdicts)} base={base_verdicts}")

    # 3. checksums match (must NOT detect drift)
    rc = fcb.verify_checksums(ROOT / "metadata" / "checksums_v0.1.json")
    check("checksums: registry matches live files (no drift)", rc == 0)

    # 4. baseline internal consistency
    n = baseline["reviewed_record_count"]
    human_sum = sum(baseline["human_score_distribution"].values())
    auto_sum = sum(baseline["ai_score_distribution"].values())
    check("baseline: human distribution sums to reviewed count",
          human_sum == n, f"sum={human_sum} n={n}")
    check("baseline: ai distribution sums to reviewed count",
          auto_sum == n, f"sum={auto_sum} n={n}")
    check("baseline: approval+rejection == 1.0",
          abs((baseline["approval_rate"] + baseline["rejection_rate"]) - 1.0) < 1e-9,
          f"{baseline['approval_rate']}+{baseline['rejection_rate']}")
    check("baseline: correlation null is expected (ai has zero variance)",
          baseline["correlation_metrics"]["pearson_r"] is None
          and baseline["ai_score_distribution"] == {"7": 100})

    # 5. canonical calibration self-test still passes
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "verify_calibration.py")],
                       capture_output=True, text=True)
    check("self-test: verify_calibration.py passes", r.returncode == 0,
          f"rc={r.returncode}")
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n=== {len(results) - len(failed)}/{len(results)} checks passed ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
