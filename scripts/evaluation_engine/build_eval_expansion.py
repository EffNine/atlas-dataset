#!/usr/bin/env python3
"""build_eval_expansion.py — Phase 6.2 evaluation-set expansion (READ-ONLY on
sources; writes ONLY to evaluation/). No training, no training-view, dataset,
or QEE engine modification.

Draws math + code eval candidates from the expert-pilot-6500 source pool,
excluding existing training-view train-split IDs (train/eval disjoint),
including the existing eval records for continuity, preserving difficulty and
provenance, and recording the automated verification evidence present in the
source records.

Code categories: bug fixing, code review, debugging, refactoring,
algorithm reasoning — assigned by a deterministic, documented keyword
classifier over problem+context text. The classifier is transparent (see
_report) and the resulting distribution is reported honestly.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

REPO = Path("/mnt/d/atlas-dataset")
SRC = REPO / "tmp" / "expert_pilot_6500_records_v0.1.jsonl"
REVIEW = REPO / "review" / "expert_pilot_6500_review_decisions_v0.1.jsonl"
OUT = REPO / "evaluation" / "eval_sets" / "phase6_expansion_v1"

TARGET_N = 100
SPLIT_SEED = "phase2b-materialization-v0.1"
SEL_SEED = "phase6.2-eval-expansion-v1"

VIEWS = {
    "math": {"source_id": "expert-math-002", "view_id": "math-300m", "tv_dir": "math_300m_v0.1"},
    "code": {"source_id": "expert-swe-001", "view_id": "code-300m", "tv_dir": "code_300m_v0.1"},
}

CODE_CATEGORIES = ["bug fixing", "debugging", "code review", "algorithm reasoning", "refactoring"]
CODE_TARGET = {
    "bug fixing": 40, "debugging": 20, "code review": 15,
    "algorithm reasoning": 15, "refactoring": 10,
}


def stable_key(rid: str, seed: str) -> str:
    return hashlib.sha256(f"{seed}:{rid}".encode("utf-8")).hexdigest()


def load_rows():
    rows = []
    with SRC.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_review():
    dec = {}
    if REVIEW.exists():
        with REVIEW.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    d = json.loads(line)
                    dec[str(d.get("record_id"))] = d.get("verdict")
    return dec


def split_deterministic(records, seed, train_ratio=0.9):
    srt = sorted(records, key=lambda r: stable_key(r.get("id") or r.get("record_id"), seed))
    n = len(srt)
    n_train = max(1, int(n * train_ratio)) if n >= 10 else n
    return srt[:n_train], srt[n_train:]


def train_ids_for(rows, source_id, tv_dir):
    """IDs actually materialized in the training-view train.jsonl (the real
    training data). Eval expansion must stay disjoint from these."""
    tv_train = REPO / "output" / "training_views" / tv_dir / "train.jsonl"
    ids = []
    if tv_train.exists():
        with tv_train.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    ids.append(json.loads(line).get("record_id"))
    return ids


def classify_code(r):
    txt = (r.get("problem") or "") + " " + (str(r.get("context") or ""))
    T = txt.lower()
    if re.search(r"\b(refactor|refactoring|clean[ -]?up|simplif|deduplicat|reorganiz|restructure|rename |extract method|remove duplicate|code smell)\b", T):
        return "refactoring"
    if re.search(r"\b(review|maintainers?|feedback|api change|deprecat|backward compatib|we should|proposal)\b", T) and "fail" not in T[:200]:
        return "code review"
    if re.search(r"\b(algorithm|complexity|o\(n|o\(log|time complexity|space complexity|dynamic programming|efficient (algorithm|solution)|performance)\b", T):
        return "algorithm reasoning"
    if re.search(r"\b(traceback|stack trace|failing test|test fails|raises? (an )?(error|exception|TypeError|ValueError)|assert.*(fail|error)|exception)\b", T):
        return "debugging"
    return "bug fixing"


def record_to_eval(record, view_id, category, review_verdict):
    verif = record.get("verification", {}) or {}
    extraction = record.get("extraction", {}) or {}
    prov = record.get("provenance", {}) or {}
    meta = record.get("metadata", {}) or {}
    return {
        "record_id": record.get("id"),
        "view_id": view_id,
        "source_id": record.get("source", {}).get("source_id"),
        "original_id": prov.get("original_id"),
        "domain": record.get("domain"),
        "category": category,
        "difficulty": record.get("difficulty"),
        "expert_tier": record.get("expert_tier"),
        "license": record.get("license"),
        "source_name": record.get("source", {}).get("name"),
        "source_url": record.get("source", {}).get("url"),
        "subdomains": meta.get("subdomains", []),
        "review_verdict": review_verdict,
        "verification": {
            "method": verif.get("method"),
            "status": verif.get("status"),
            "evidence": verif.get("evidence"),
            "reviewer": verif.get("reviewer"),
            "reviewed_at": verif.get("reviewed_at"),
        },
        "verification_evidence": {
            "has_expected_answer": extraction.get("has_expected_answer"),
            "expected_answer_head": extraction.get("expected_answer_head"),
            "has_problem": extraction.get("has_problem"),
            "has_patch": extraction.get("has_patch"),
            "has_test_patch": extraction.get("has_test_patch"),
            "fail_to_pass_count": extraction.get("fail_to_pass_count"),
            "pass_to_pass_count": extraction.get("pass_to_pass_count"),
        },
        "lineage": {
            "ingestion_pipeline": prov.get("ingestion_pipeline"),
            "curated_release": "expert-pilot-6500-v0.1",
            "training_view": view_id,
        },
        "problem": record.get("problem"),
        "solution": record.get("solution"),
        "messages": record.get("messages", []),
        "context": record.get("context"),
    }


def sha256_of_lines(lines):
    blob = "\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in lines)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def select_stratified(eligible, existing_eval, n_target, strat_key, target_mix):
    """Deterministic stratified selection by a key (difficulty or category).

    Keeps existing eval records first, then fills to n_target preserving the
    requested mix where the pool allows.
    """
    picked = list(existing_eval)
    picked_ids = {r.get("id") for r in picked}
    cand = [r for r in eligible if r.get("id") not in picked_ids]
    for c in cand:
        c.setdefault("_cat", strat_key(c))
    by_key = {}
    for c in cand:
        by_key.setdefault(c["_cat"], []).append(c)
    for k in by_key:
        by_key[k].sort(key=lambda r: stable_key(r.get("id"), SEL_SEED))

    keys = list(by_key.keys())
    idx = {k: 0 for k in keys}

    # requested per-category caps (where provided), else proportional
    remaining = n_target - len(picked)
    # accumulate existing counts
    picked_cats = Counter(getattr(r, "_cat", strat_key(r)) for r in picked)
    # for code, use CODE_TARGET as caps; for math/difficulty, proportional caps
    if target_mix:
        caps = dict(target_mix)
    else:
        total = max(1, sum(len(by_key.get(k, [])) for k in by_key))
        caps = {k: max(1, round(n_target * len(by_key.get(k, [])) / total)) for k in by_key}

    order = []
    while remaining > 0:
        progressed = False
        for k in keys:
            if len(order) + len(picked) >= n_target:
                break
            have = picked_cats.get(k, 0) + sum(1 for x in order if x["_cat"] == k)
            cap = caps.get(k, n_target)
            if have < cap and idx[k] < len(by_key[k]):
                order.append(by_key[k][idx[k]])
                idx[k] += 1
                progressed = True
                remaining -= 1
        if not progressed:
            for k in keys:
                while idx[k] < len(by_key[k]) and remaining > 0:
                    order.append(by_key[k][idx[k]])
                    idx[k] += 1
                    remaining -= 1
            break
    picked = picked + order
    return picked


def main():
    rows = load_rows()
    review = load_review()
    OUT.mkdir(parents=True, exist_ok=True)

    summary = {}
    for fam, cfg in VIEWS.items():
        src_id = cfg["source_id"]
        pool = [r for r in rows if str(r.get("source", {}).get("source_id")) == src_id]
        tv_eval = REPO / "output" / "training_views" / cfg["tv_dir"] / "eval.jsonl"
        existing_eval_ids = []
        if tv_eval.exists():
            with tv_eval.open(encoding="utf-8") as f:
                existing_eval_ids = [json.loads(l).get("record_id") for l in f if l.strip()]
        train_ids = train_ids_for(rows, src_id, cfg["tv_dir"])
        eligible = [r for r in pool
                    if r.get("id") not in train_ids
                    and review.get(str(r.get("id"))) != "REJECT"]
        existing_evals = [r for r in pool if r.get("id") in existing_eval_ids]

        if fam == "code":
            strat_key = classify_code
            target_mix = CODE_TARGET
            domain_label = "software_engineering"
        else:
            strat_key = lambda r: r.get("difficulty")
            target_mix = None
            domain_label = "mathematics"

        # assign category key uniformly so existing eval records also carry it
        for r in pool:
            r["_cat"] = strat_key(r)

        chosen = select_stratified(eligible, existing_evals, TARGET_N, strat_key, target_mix)
        eval_rows = [record_to_eval(r, cfg["view_id"], domain_label if fam == "math" else r["_cat"],
                                    review.get(str(r.get("id"))))
                     for r in chosen]
        eval_rows.sort(key=lambda e: e["record_id"])

        eval_path = OUT / f"{fam}_eval_v1.jsonl"
        with eval_path.open("w", encoding="utf-8") as f:
            for e in eval_rows:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

        diff_dist = Counter(e.get("difficulty") for e in eval_rows)
        cat_dist = Counter(e.get("category") for e in eval_rows)
        prov_ok = sum(1 for e in eval_rows if e.get("original_id"))
        verif_status = Counter(e.get("verification", {}).get("status") for e in eval_rows)
        review_dist = Counter(e.get("review_verdict") for e in eval_rows)
        manifest = {
            "eval_set_id": f"phase6-{fam}-eval-v1",
            "version": "v1",
            "generated_at": "2026-08-04T00:00:00Z",
            "family": fam,
            "view_id": cfg["view_id"],
            "source_pool": "expert-pilot-6500-v0.1",
            "source_pool_size": len(pool),
            "n_target": TARGET_N,
            "n_records": len(eval_rows),
            "old_size": len(existing_eval_ids),
            "split": {
                "method": "deterministic_sha256",
                "selection_seed": SEL_SEED,
                "train_seed": SPLIT_SEED,
                "train_disjoint": True,
                "train_ids_excluded": len(train_ids),
                "existing_eval_included": sorted(existing_eval_ids),
            },
            "category_balance": {
                "by_difficulty": {str(k): v for k, v in sorted(diff_dist.items(), key=lambda x: str(x[0]))},
                "by_category": {str(k): v for k, v in sorted(cat_dist.items())},
            },            "provenance": {"original_id_present": prov_ok, "release": "expert-pilot-6500-v0.1"},
            "verification": {str(k): v for k, v in sorted(verif_status.items())},
            "review_verdicts": {str(k): v for k, v in sorted(review_dist.items(), key=lambda x: str(x[0]))},
            "checksum": {"algorithm": "SHA-256", "records": sha256_of_lines(eval_rows)},
            "files": {"eval_jsonl": str(eval_path)},
        }
        (OUT / f"{fam}_eval_v1_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        summary[fam] = {
            "pool": len(pool), "eligible_non_train": len(eligible),
            "existing_eval": len(existing_eval_ids), "selected": len(eval_rows),
            "difficulty": dict(diff_dist), "category": dict(cat_dist),
            "verification": dict(verif_status), "review": dict(review_dist),
            "prov_ok": prov_ok,
        }
        print(f"[{fam}] selected {len(eval_rows)} -> {eval_path}")
        print(f"   difficulty: {dict(diff_dist)}")
        print(f"   category: {dict(cat_dist)}")
        print(f"   verification: {dict(verif_status)}")
        print(f"   review verdicts: {dict(review_dist)}")
        print(f"   provenance original_id present: {prov_ok}/{len(eval_rows)}")

    (OUT / "build_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nWrote build_summary.json")


if __name__ == "__main__":
    main()
