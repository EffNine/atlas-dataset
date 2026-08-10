#!/usr/bin/env python3
"""build_p8a_subset.py — Phase 8 (P8-A) deterministic math training subset.

READ-ONLY on all sources; writes ONLY under experiments/phase8_transfer/.
No training. No modification of frozen datasets, training views, or the QEE
engine.

P8-A (Math -> Code) training subset:
  - Source pool: approved math records (expert-math-002) from the
    expert-pilot-6500-v0.1 release.
  - Eligible = pool records that:
      1. belong to the math source pool (expert-math-002);
      2. are NOT REJECT-reviewed (governance);
      3. are NOT in the target eval split `code_eval_v1` (train/eval
         disjointness, phase8_transfer_plan §5.2);
      4. are NOT in `math_eval_v1` (eval split is never trained on, matrix
         cross-cutting rule 3);
      5. are NOT in the frozen training-view eval split
         (`math_300m_v0.1/eval.jsonl`, phase7 practice).
  - Deterministic ordering: ascending `sha256("phase8-transfer-v1:{record_id}")`
    where record_id is the pool record `id`.
  - Take the first N=400 records.

Outputs (all under experiments/phase8_transfer/subsets/):
  P8A_math_train.jsonl             the staged subset (verbatim pool records)
  P8A_math_train_manifest.json     selection params, eligibility, checksums,
                                   provenance, leakage audit

Deterministic: identical output bytes and checksums for identical inputs.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SRC = REPO / "tmp" / "expert_pilot_6500_records_v0.1.jsonl"
REVIEW = REPO / "review" / "expert_pilot_6500_review_decisions_v0.1.jsonl"
MATH_EVAL = REPO / "evaluation" / "eval_sets" / "phase6_expansion_v1" / "math_eval_v1.jsonl"
CODE_EVAL = REPO / "evaluation" / "eval_sets" / "phase6_expansion_v1" / "code_eval_v1.jsonl"
TV_EVAL = REPO / "output" / "training_views" / "math_300m_v0.1" / "eval.jsonl"
OUT_DIR = REPO / "experiments" / "phase8_transfer" / "subsets"

SUBET_NAME = "P8A_math_train"
SOURCE_ID = "expert-math-002"
SEL_SEED = "phase8-transfer-v1"
N_TARGET = 400


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def stable_key(rid: str, seed: str) -> str:
    return hashlib.sha256(f"{seed}:{rid}".encode("utf-8")).hexdigest()


def raw_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def records_sha256(rows: list[dict]) -> str:
    blob = "\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def git_short_head() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return out
    except Exception:
        return "[HUMAN MUST SUPPLY]"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pool = [r for r in load_jsonl(SRC)
            if str(r.get("source", {}).get("source_id")) == SOURCE_ID]
    review = {str(r.get("record_id")): r.get("verdict") for r in load_jsonl(REVIEW)}
    math_eval_ids = {r.get("record_id") for r in load_jsonl(MATH_EVAL)}
    code_eval_ids = {r.get("record_id") for r in load_jsonl(CODE_EVAL)}
    tv_eval_ids = {r.get("record_id") for r in load_jsonl(TV_EVAL)}

    eligible = [r for r in pool
                if review.get(str(r.get("id"))) != "REJECT"
                and r.get("id") not in math_eval_ids
                and r.get("id") not in code_eval_ids
                and r.get("id") not in tv_eval_ids]
    eligible.sort(key=lambda r: stable_key(str(r.get("id")), SEL_SEED))

    subset = eligible[:N_TARGET]
    subset_path = OUT_DIR / f"{SUBET_NAME}.jsonl"
    with subset_path.open("w", encoding="utf-8") as f:
        for r in subset:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    sub_ids = {str(r.get("id")) for r in subset}
    orig_ids = [str((r.get("provenance") or {}).get("original_id")) for r in subset]
    dup_rec = {k: v for k, v in Counter(sub_ids).items() if v > 1}
    dup_orig = {k: v for k, v in Counter(orig_ids).items() if v > 1}

    audit = {
        "leakage": {
            "math_eval_v1_overlap": sorted(sub_ids & math_eval_ids),
            "code_eval_v1_overlap": sorted(sub_ids & code_eval_ids),
            "tv_eval_overlap": sorted(sub_ids & tv_eval_ids),
            "clean": not ((sub_ids & math_eval_ids)
                          or (sub_ids & code_eval_ids)
                          or (sub_ids & tv_eval_ids)),
        },
        "duplicates": {
            "duplicate_record_ids": dup_rec,
            "duplicate_original_ids": dup_orig,
        },
        "distributions": {
            "difficulty": dict(sorted(Counter(r.get("difficulty") for r in subset).items())),
            "domain": dict(sorted(Counter(r.get("domain") for r in subset).items())),
            "expert_tier": dict(sorted(Counter(r.get("expert_tier") for r in subset).items())),
            "license": dict(sorted(Counter(r.get("license") for r in subset).items())),
            "review_verdict": dict(sorted(Counter(
                review.get(str(r.get("id")), "NONE") for r in subset).items())),
        },
        "provenance": {
            "original_id_present": sum(1 for o in orig_ids if o),
            "original_id_total": len(orig_ids),
            "source_id": SOURCE_ID,
        },
    }

    manifest = {
        "experiment": "P8-A",
        "experiment_id": "atlas-math-small-qwen7b-lora-transfer-v1",
        "phase": "8",
        "objective": "Deterministic math training subset for the P8-A "
                     "(Math -> Code) cross-domain transfer experiment.",
        "selection": {
            "method": "sha256(seed:record_id) sorted ascending, first N",
            "seed": SEL_SEED,
            "n_target": N_TARGET,
            "n_selected": len(subset),
            "record_id_field": "id",
            "source_pool": "expert-pilot-6500-v0.1 (expert-math-002)",
            "pool_size": len(pool),
            "eligible_size": len(eligible),
        },
        "eligibility_exclusions": {
            "reject_reviewed": len(pool) - sum(1 for r in pool
                                               if review.get(str(r.get("id"))) != "REJECT"),
            "math_eval_v1": len(pool) - sum(1 for r in pool if r.get("id") not in math_eval_ids),
            "code_eval_v1": len([r for r in pool if r.get("id") in code_eval_ids]),
            "tv_eval": len(pool) - sum(1 for r in pool if r.get("id") not in tv_eval_ids),
        },
        "frozen_inputs": {
            "source_jsonl": str(SRC.relative_to(REPO)),
            "review_jsonl": str(REVIEW.relative_to(REPO)),
            "math_eval_v1": str(MATH_EVAL.relative_to(REPO)),
            "code_eval_v1": str(CODE_EVAL.relative_to(REPO)),
            "tv_eval": str(TV_EVAL.relative_to(REPO)),
        },
        "checksum": {
            "algorithm": "SHA-256",
            "raw_file_sha256": raw_sha256(subset_path),
            "records_sha256": records_sha256(subset),
        },
        "audit": audit,
        "git_commit": git_short_head(),
        "generated_at": "2026-08-05T00:00:00Z",
        "note": "Staged under experiments/phase8_transfer/subsets/ only. Frozen "
                "datasets, training views, and the QEE engine are NOT modified.",
    }

    manifest_path = OUT_DIR / f"{SUBET_NAME}_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"pool={len(pool)} eligible={len(eligible)} selected={len(subset)}")
    print(f"subset: {subset_path.relative_to(REPO)}")
    print(f"manifest: {manifest_path.relative_to(REPO)}")
    print(f"leakage clean: {audit['leakage']['clean']}")
    print(f"difficulty: {audit['distributions']['difficulty']}")
    print(f"raw_file_sha256: {manifest['checksum']['raw_file_sha256']}")
    print(f"records_sha256: {manifest['checksum']['records_sha256']}")


if __name__ == "__main__":
    main()
