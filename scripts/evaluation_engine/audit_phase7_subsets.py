#!/usr/bin/env python3
"""audit_phase7_subsets.py — Phase 7.1 pre-flight audit of M1/M2/M3 math
training subsets. READ-ONLY on all sources; writes audit JSON only.

Verifies for each subset:
  1. category distribution
  2. difficulty distribution
  3. source provenance
  4. duplicate IDs
  5. train/eval leakage (vs math_eval_v1 + training-view eval)
  6. checksum manifest (raw-file SHA-256 + canonical records SHA-256)

No training, no dataset modification. Subsets are staged deterministically from
the expert-pilot-6500 math pool per the Phase 7.0 plan (§4.2).
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

REPO = Path("/mnt/d/atlas-dataset")
SRC = REPO / "tmp" / "expert_pilot_6500_records_v0.1.jsonl"
REVIEW = REPO / "review" / "expert_pilot_6500_review_decisions_v0.1.jsonl"
EVAL_V1 = REPO / "evaluation" / "eval_sets" / "phase6_expansion_v1" / "math_eval_v1.jsonl"
TV_TRAIN = REPO / "output" / "training_views" / "math_300m_v0.1" / "train.jsonl"
TV_EVAL = REPO / "output" / "training_views" / "math_300m_v0.1" / "eval.jsonl"
OUT = REPO / "experiments" / "phase7_scale" / "audit"
SUBSET_DIR = REPO / "experiments" / "phase7_scale" / "subsets"

SEL_SEED = "phase7-scale-v1"
SIZES = {"M1": 117, "M2": 500, "M3": 1000}


def stable_key(rid: str, seed: str) -> str:
    return hashlib.sha256(f"{seed}:{rid}".encode("utf-8")).hexdigest()


def load_jsonl(path: Path):
    rows = []
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def sha256_of_lines(rows):
    blob = "\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def raw_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def rec_id(r):
    return r.get("id") or r.get("record_id")

def rec_orig_id(r):
    return r.get("original_id") or (r.get("provenance") or {}).get("original_id")

def rec_source_id(r):
    s = r.get("source")
    if isinstance(s, dict):
        return s.get("source_id") or s.get("name")
    return r.get("source_id") or s

def rec_category(r):
    return r.get("category") or r.get("domain")

def rec_difficulty(r):
    return r.get("difficulty")

def rec_tier(r):
    return r.get("expert_tier")

def rec_license(r):
    return r.get("license")


def audit_rows(rows, name, eval_ids, tv_eval_ids):
    rec_ids = [rec_id(r) for r in rows]
    orig_ids = [rec_orig_id(r) for r in rows]
    sources = [str(rec_source_id(r)) for r in rows]
    licenses = [rec_license(r) for r in rows]

    dup_rec = {k: v for k, v in Counter(rec_ids).items() if v > 1}
    dup_orig = {k: v for k, v in Counter(orig_ids).items() if v > 1}

    return {
        "subset": name,
        "n": len(rows),
        "category_distribution": dict(sorted(Counter(rec_category(r) for r in rows).items())),
        "difficulty_distribution": dict(sorted(Counter(rec_difficulty(r) for r in rows).items())),
        "expert_tier_distribution": dict(sorted(Counter(rec_tier(r) for r in rows).items())),
        "provenance": {
            "source_ids": dict(sorted(Counter(sources).items())),
            "licenses": dict(sorted(Counter(licenses).items())),
            "original_id_present": sum(1 for o in orig_ids if o),
            "original_id_total": len(orig_ids),
        },
        "duplicates": {
            "duplicate_record_ids": dup_rec,
            "duplicate_original_ids": dup_orig,
        },
        "leakage": {
            "eval_v1_overlap": sorted(set(rec_ids) & eval_ids),
            "tv_eval_overlap": sorted(set(rec_ids) & tv_eval_ids),
            "clean": not (set(rec_ids) & eval_ids) and not (set(rec_ids) & tv_eval_ids),
        },
        "checksum": {
            "records_sha256": sha256_of_lines(rows),
        },
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    SUBSET_DIR.mkdir(parents=True, exist_ok=True)

    pool = [r for r in load_jsonl(SRC)
            if str(r.get("source", {}).get("source_id")) == "expert-math-002"]
    review = {}
    for line in load_jsonl(REVIEW):
        review[str(line.get("record_id"))] = line.get("verdict")
    eval_ids = {r.get("record_id") for r in load_jsonl(EVAL_V1)}
    tv_eval_ids = {r.get("record_id") for r in load_jsonl(TV_EVAL)}
    print(f"pool={len(pool)} eval_v1={len(eval_ids)} tv_eval={len(tv_eval_ids)}")

    # M1: REBUILT from the same phase7-scale-v1 ordering as M2/M3 so that
    # M1 ⊂ M2 ⊂ M3 (Phase 7.1 correction). The materialized 117-record
    # training view (math_300m_v0.1/train.jsonl) is NOT used — it is a frozen
    # Phase 5B.1 artifact and is not part of the scaling comparison.
    #
    # Eligible pool for M1/M2/M3: exclude eval_v1, tv_eval, and REJECT.
    eligible = [r for r in pool
                if r.get("id") not in eval_ids
                and r.get("id") not in tv_eval_ids
                and review.get(str(r.get("id"))) != "REJECT"]
    eligible.sort(key=lambda r: stable_key(r.get("id"), SEL_SEED))
    print(f"eligible after eval/REJECT exclusion: {len(eligible)}")

    subsets = {"M1": eligible[:117], "M2": eligible[:500], "M3": eligible[:1000]}

    # Nesting check: is M1 a subset of M2, and M2 of M3?
    m1_ids = {rec_id(r) for r in subsets["M1"]}
    m2_ids = {rec_id(r) for r in subsets["M2"]}
    m3_ids = {rec_id(r) for r in subsets["M3"]}
    nesting = {
        "M1_in_M2": m1_ids <= m2_ids,
        "M1_in_M3": m1_ids <= m3_ids,
        "M2_in_M3": m2_ids <= m3_ids,
        "M1_not_in_M2_count": len(m1_ids - m2_ids),
        "M2_not_in_M3_count": len(m2_ids - m3_ids),
    }

    results = {}
    for name in ("M1", "M2", "M3"):
        rows = subsets[name]
        # For M2/M3, subset of eligible; write staged subset files (audit only,
        # outside frozen views).
        subset_path = SUBSET_DIR / f"{name}_math_train.jsonl"
        with subset_path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        audit = audit_rows(rows, name, eval_ids, tv_eval_ids)
        audit["checksum"]["raw_file_sha256"] = raw_sha256(subset_path)
        audit["staged_path"] = str(subset_path)
        results[name] = audit
        print(f"[{name}] n={audit['n']} diff={audit['difficulty_distribution']} "
              f"leak={audit['leakage']['clean']} dup_rec={audit['duplicates']['duplicate_record_ids']}")

    report = {
        "phase": "7.1",
        "note": "CORRECTED pre-flight audit; READ-ONLY on sources. M1 rebuilt "
                "from the phase7-scale-v1 ordering (Phase 7.1 correction) so "
                "M1 ⊂ M2 ⊂ M3. Staged subset copies are audit artifacts under "
                "experiments/phase7_scale/ (not frozen views).",
        "selection": {"seed": SEL_SEED, "method": "sha256(seed:record_id) sorted",
                      "m1_source": "phase7-scale-v1 first 117 (rebuilt)",
                      "m2_m3_eligible": len(eligible)},
        "eval_exclusions": {"math_eval_v1": sorted(eval_ids)[:10] + ["..."],
                            "tv_eval": sorted(tv_eval_ids)},
        "nesting": nesting,
        "subsets": results,
    }
    out_path = OUT / "phase7_subset_audit.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
