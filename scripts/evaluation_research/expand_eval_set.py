"""Expand eval sets to protocol-mandated N ≥ 30 per family + difficulty tier.

Sources the approved expert records (already gated by schema/license/security
and quality ≥7) and produces a versioned, immutable eval set under
evaluation/eval_sets/protocol_v3/. The original v2 files remain untouched.

Expansion strategy:
  - Stratified sampling by difficulty (L1-L5) and subdomain
  - Target: ≥30 records per family overall AND ≥10 per difficulty tier (harder
    tiers undersampled in v2: math had 13 at diff≥3, code had 2 at diff5)
  - Protocol v2 sanitization: fold system → context, strip assistant turn,
    keep [user message] + canonical_answer
  - Leak guard: sha256 of problem text checked against all records in
    metadata/views/atlas-sft-v0.2/{architecture,code,math,aiml}/train.jsonl

Usage:
  PYTHONPATH=scripts python -m scripts.evaluation_research.expand_eval_set \\
      --source-records tmp/expert_pilot_6500_records_v0.1.jsonl \\
      --source-source math \\\\
      --eval-set-id math_eval_v3 \\\\
      --family math \\\\
      --output-dir evaluation/eval_sets/protocol_v3 \\\\
      --target-n 120 --min-difficulty 2

Produces:
  evaluation/eval_sets/protocol_v3/math_eval_v3.jsonl
  evaluation/eval_sets/protocol_v3/math_eval_v3_manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

# Known source_ids -> family mapping (matches sft_view logic)
FAMILY_BY_SOURCE = {
    "expert-math-002": "math",
    "expert-swe-001": "code",
    "expert-aiml-001": "aiml",
    "expert-arch-001": "architecture",
    "expert-agentic-001": "agentic",
}


def load_records(paths: list[Path]) -> list[dict]:
    out = []
    seen_ids: set[str] = set()
    for p in paths:
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rid = r.get("record_id") or r.get("id")
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            out.append(r)
    return out


def pick_messages(r: dict) -> list[dict]:
    """Return messages suitable for eval (user-only, no system, no assistant)."""
    msgs = r.get("messages") or []
    # Fold system to context
    sys_text = "\n".join(
        (m.get("content") or "") for m in msgs if m.get("role") == "system"
    ).strip()
    clean = [m for m in msgs if m.get("role") != "system"]
    # Keep only the first user turn as the prompt (drop remaining turns to avoid
    # multi-turn eval leakage; eval is single-turn by protocol)
    prompt = ""
    for m in clean:
        if m.get("role") == "user":
            prompt = (m.get("content") or "").strip()
            break
    if sys_text and prompt:
        prompt = f"{sys_text}\n\n{prompt}"
    return [{"role": "user", "content": prompt}] if prompt else clean[:1]


def sanitize_for_eval(r: dict) -> dict:
    """Strip to eval-only format per protocol v2."""
    r = dict(r)
    r["messages"] = pick_messages(r)
    r["version"] = "v3"
    # lineage
    r.setdefault("lineage", {})["source_eval_set"] = {"eval_set_id": "unknown"}
    r.setdefault("lineage", {})["expansion_pipeline"] = "expand_eval_set_v3"
    # protocol_v2 structural
    pv2 = r.setdefault("protocol_v2", {})
    pv2.setdefault("canonical_answer_source", r.get("canonical_answer_source", "solution"))
    pv2.setdefault("canonical_answer_derivation", "original solution text")
    pv2.setdefault("leak_guard_verdict", "pending")
    pv2.setdefault("leak_guard_reason", None)
    pv2.setdefault("messages_contains_reference", False)
    pv2.setdefault("prompt_source", "problem")
    pv2.setdefault("sanitized_from_v1", {"dropped": ["context", "messages[assistant]", "messages[system]"], "reason": "single-turn eval format"})
    return r


def sha256_of_problem(r: dict) -> str:
    problem = r.get("problem") or ""
    content = r.get("messages") and r["messages"][0].get("content") or ""
    text = problem or content
    return hashlib.sha256(text.encode()).hexdigest()


def load_training_problems(view_root: Path) -> dict[str, str]:
    """Map problem-sha256 -> record_id for every record in a view."""
    out: dict[str, str] = {}
    for cat_dir in view_root.iterdir():
        if not cat_dir.is_dir():
            continue
        tf = cat_dir / "train.jsonl"
        if not tf.exists():
            continue
        for line in tf.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            h = sha256_of_problem(r)
            if h:
                out[h] = r.get("record_id") or r.get("id")
    return out


def leak_guard(records: list[dict], training_problems: dict[str, str]) -> dict:
    """Check each record for overlap with training views. Returns hit map."""
    hits: dict[str, list[str]] = {}
    for r in records:
        h = sha256_of_problem(r)
        if h and h in training_problems:
            hits.setdefault(r.get("record_id") or r.get("id", "?"), []).append(
                training_problems[h])
        pv2 = (r.get("protocol_v2") or {}).setdefault("leak_guard_verdict", "pass")
    return hits


def stratified_sample(records: list[dict], *, family: str,
                      target_n: int, min_difficulty: int,
                      per_tier_min: int = 10, seed: int = 42) -> list[dict]:
    """Sample stratified by difficulty, ensuring per-tier minimums then fill to target_n."""
    rng = random.Random(seed)
    buckets: dict[int, list[dict]] = {}
    for r in records:
        d = r.get("difficulty")
        if d is None or d < min_difficulty:
            continue
        buckets.setdefault(d, []).append(r)

    sampled: list[dict] = []
    # First pass: guaranteed per-tier minimum
    for d in sorted(buckets):
        pool = buckets[d]
        n_take = min(per_tier_min, len(pool))
        if n_take == 0:
            continue
        chosen = rng.sample(pool, n_take)
        sampled.extend(chosen)
        buckets[d] = [r for r in pool if r not in chosen]

    # Second pass: fill remaining quota proportionally across tiers
    remaining = target_n - len(sampled)
    if remaining <= 0:
        return sampled[:target_n]

    total_pool = sum(len(v) for v in buckets.values())
    if total_pool == 0:
        return sampled

    for d in sorted(buckets):
        pool = buckets[d]
        if not pool:
            continue
        share = max(0, round(remaining * len(pool) / total_pool))
        share = min(share, len(pool))
        chosen = rng.sample(pool, share)
        sampled.extend(chosen)
        buckets[d] = [r for r in pool if r not in chosen]

    return sampled[:target_n]


def build(expand_args: dict) -> dict:
    src_paths = [Path(p) for p in expand_args["source_records"]]
    records = load_records(src_paths)
    family = expand_args["family"]
    target_n = expand_args["target_n"]
    min_diff = expand_args["min_difficulty"]

    # Filter to family sources
    allowed_sources = {sid for sid, fam in FAMILY_BY_SOURCE.items() if fam == family}
    family_records = [r for r in records if (r.get("source") or {}).get("source_id") in allowed_sources]
    print(f"family={family} total candidates: {len(family_records)}")

    sampled = stratified_sample(family_records, family=family,
                                target_n=target_n, min_difficulty=min_diff)
    print(f"sampled: {len(sampled)}")
    diff_dist = Counter(r.get("difficulty") for r in sampled)
    print(f"distribution: {dict(sorted(diff_dist.items()))}")

    sanitized = [sanitize_for_eval(r) for r in sampled]

    # leak guard
    view_root = REPO_ROOT / "metadata" / "views" / expand_args.get("view_tag", "atlas-sft-v0.2")
    training_problems = load_training_problems(view_root) if view_root.exists() else {}
    hits = leak_guard(sanitized, training_problems)
    n_leak = len(hits)
    for rid, overlaps in hits.items():
        print(f"  LEAK {rid}: overlaps {len(overlaps)} training records")
    # patch protocol_v2 leak_guard_verdict
    leaked_ids = set(hits.keys())
    for r in sanitized:
        rid = r.get("record_id") or r.get("id")
        if rid in leaked_ids:
            (r.setdefault("protocol_v2") or {})["leak_guard_verdict"] = "fail"
            (r.setdefault("protocol_v2") or {})["leak_guard_reason"] = f"problem matches {len(hits[rid])} training record(s)"
        else:
            (r.setdefault("protocol_v2") or {})["leak_guard_verdict"] = "pass"
            (r.setdefault("protocol_v2") or {})["leak_guard_reason"] = None

    out_dir = REPO_ROOT / expand_args["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    eval_file = out_dir / f"{expand_args['eval_set_id']}.jsonl"
    if eval_file.exists():
        raise FileExistsError(f"refusing to overwrite: {eval_file}")

    with open(eval_file, "w", encoding="utf-8") as f:
        for r in sanitized:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    sha = hashlib.sha256(eval_file.read_bytes()).hexdigest()
    manifest = {
        "manifest_name": f"{expand_args['eval_set_id']}_manifest",
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "eval_set_id": expand_args["eval_set_id"],
        "family": family,
        "protocol_version": "v3",
        "n_records": len(sanitized),
        "n_leak_hits": n_leak,
        "sha256": sha,
        "path": str(eval_file.relative_to(REPO_ROOT)),
        "difficulty_distribution": dict(sorted(diff_dist.items())),
        "sampling_seed": 42,
        "contamination_audit": "pending_full_audit",
        "source_records_scanned": len(family_records),
        "source_files": [str(p) for p in src_paths],
        "view_tag": expand_args.get("view_tag", "atlas-sft-v0.2"),
    }
    manifest_path = out_dir / f"{expand_args['eval_set_id']}_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"wrote {eval_file} ({len(sanitized)} records, sha={sha[:12]}...)")
    print(f"manifest: {manifest_path}")
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Expand eval sets to N≥30 per family")
    parser.add_argument("--source-records", nargs="+", required=True,
                        help="Expert record JSONL files to sample from")
    parser.add_argument("--family", required=True,
                        choices=["math", "code", "aiml", "architecture", "agentic"])
    parser.add_argument("--eval-set-id", required=True,
                        help="e.g. math_eval_v3, code_eval_v3")
    parser.add_argument("--output-dir", default="evaluation/eval_sets/protocol_v3")
    parser.add_argument("--target-n", type=int, default=120,
                        help="Target sample size (default 120 to exceed N≥30 comfortably)")
    parser.add_argument("--min-difficulty", type=int, default=2,
                        help="Minimum difficulty tier to include (default 2)")
    parser.add_argument("--view-tag", default="atlas-sft-v0.2",
                        help="View root tag for contamination check")
    args = parser.parse_args(argv)

    manifest = build(vars(args))
    ok = manifest["n_leak_hits"] == 0 and manifest["n_records"] >= 30
    print(json.dumps({"ok": ok, **{k: v for k, v in manifest.items() if k != "source_files"}}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
