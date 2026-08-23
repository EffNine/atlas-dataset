"""Build verified / deduplicated / size-budgeted SFT training views from
Atlas expert-pipeline record batches.

Reads expert records (schema v0.1, quality-scored by the runner), applies
uniform gates, and writes one train.jsonl per category under a versioned
view root plus a MANIFEST.json containing SHA-256 checksums of every output.

Gates applied to every record (all must pass):
  1. schema            - expert_pipeline.validation.validate_schema == []
  2. license           - license is in constants.ALLOWED_LICENSES
  3. security          - validation.security_scan has no hits
  4. messages          - exactly user+assistant turns, both non-empty
  5. quality           - metadata.quality_score >= min_quality (default 7,
                         matching the release quality gate)
  6. token budget      - estimated tokens (chars/4) <= max_tokens (default 4096)
Deduplication (within category, then across categories):
  - primary key: provenance.original_id
  - fallback:     sha256(normalized problem text)

Usage:
  PYTHONPATH=scripts python -m expert_pipeline.sft_view \
      --tag atlas-sft-v0.1 \
      --records tmp/expert_pilot_6500_records_v0.1.jsonl \
                tmp/records_atlas_expert_architecture-v0.2.jsonl

Outputs (never overwritten):
  metadata/views/<tag>/<category>/train.jsonl
  metadata/views/<tag>/MANIFEST.json
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from .constants import ALLOWED_LICENSES
from .util import normalize_text, sha256_hex
from .validation import security_scan, validate_schema

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECORDS = [
    REPO_ROOT / "tmp" / "expert_pilot_6500_records_v0.1.jsonl",
    REPO_ROOT / "tmp" / "records_atlas_expert_architecture-v0.2.jsonl",
]

CATEGORY_BY_SOURCE = {
    "expert-arch-001": "architecture",
    "expert-swe-001": "code",
    "expert-math-002": "math",
    "expert-aiml-001": "aiml",
}

DIM_KEYS = ("correctness", "reasoning_depth", "explanation_quality", "provenance_confidence")


def est_tokens(record: dict) -> int:
    return sum(len(m.get("content", "")) for m in record.get("messages", [])) // 4


def messages_ok(record: dict) -> bool:
    msgs = record.get("messages") or []
    return (
        len(msgs) >= 2
        and msgs[0].get("role") == "user"
        and msgs[-1].get("role") == "assistant"
        and all((m.get("content") or "").strip() for m in msgs)
    )


def gate_record(record: dict, *, max_tokens: int, min_quality: int) -> list[str]:
    """Return rejection reasons (empty = accepted)."""
    reasons: list[str] = []
    sid = (record.get("source") or {}).get("source_id", "")
    if sid not in CATEGORY_BY_SOURCE:
        reasons.append("unknown_source")
    if validate_schema(record):
        reasons.append("schema")
    if record.get("license") not in ALLOWED_LICENSES:
        reasons.append("license")
    if security_scan(record):
        reasons.append("security")
    if not messages_ok(record):
        reasons.append("messages")
    q = (record.get("metadata") or {}).get("quality_score")
    if not isinstance(q, int) or q < min_quality:
        reasons.append("quality_below_threshold")
    if est_tokens(record) > max_tokens:
        reasons.append("token_budget")
    return reasons


def dedup_keys(record: dict) -> list[str]:
    keys = []
    oid = (record.get("provenance") or {}).get("original_id")
    if oid:
        keys.append(f"oid:{oid}")
    problem = record.get("problem") or ""
    if problem.strip():
        keys.append(f"text:{sha256_hex(normalize_text(problem))}")
    return keys


def load_records(paths: list[Path]) -> list[dict]:
    out = []
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def build_view(records: list[dict], view_root: Path, *,
               max_tokens: int = 4096, min_quality: int = 7) -> dict:
    """Gate, dedup, write category views + manifest. Returns the manifest."""
    per_category: dict[str, list[dict]] = {}
    rejections: Counter = Counter()
    seen_global: set[str] = set()
    dup_counts: Counter = Counter()

    for rec in records:
        reasons = gate_record(rec, max_tokens=max_tokens, min_quality=min_quality)
        if reasons:
            for r in reasons:
                rejections[r] += 1
            continue
        cat = CATEGORY_BY_SOURCE[rec["source"]["source_id"]]
        keys = dedup_keys(rec)
        if any(k in seen_global for k in keys):
            dup_counts[cat] += 1
            continue
        seen_global.update(keys)
        per_category.setdefault(cat, []).append(rec)

    if view_root.exists():
        raise FileExistsError(f"refusing to overwrite existing view root: {view_root}")
    view_root.mkdir(parents=True, exist_ok=True)

    manifest = {
        "manifest_name": f"sft_view_{view_root.name}",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "gates": {
            "schema": "validate_schema == []",
            "license": f"license in {sorted(ALLOWED_LICENSES)}",
            "security": "security_scan clean",
            "messages": "user+assistant, non-empty",
            "quality": f"metadata.quality_score >= {min_quality}",
            "token_budget": f"est_tokens(chars/4) <= {max_tokens}",
        },
        "dedup": {"primary": "provenance.original_id", "fallback": "sha256(normalized_problem)"},
        "input_records": len(records),
        "accepted_total": 0,
        "duplicates_skipped": dict(dup_counts),
        "rejections": dict(rejections),
        "categories": {},
    }

    for cat in sorted(per_category):
        recs = sorted(per_category[cat], key=lambda r: r["id"])
        out_dir = view_root / cat
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "train.jsonl"
        with open(out_file, "w", encoding="utf-8") as f:
            for rec in recs:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        file_sha = hashlib.sha256(out_file.read_bytes()).hexdigest()
        try:
            manifest_path_str = str(out_file.relative_to(REPO_ROOT))
        except ValueError:
            manifest_path_str = str(out_file)  # views built outside REPO_ROOT (tests)
        manifest["categories"][cat] = {
            "path": manifest_path_str,
            "records": len(recs),
            "sha256": file_sha,
            "sources": sorted({r["source"]["source_id"] for r in recs}),
            "est_token_p50": sorted(est_tokens(r) for r in recs)[len(recs) // 2],
            "est_token_max": max(est_tokens(r) for r in recs),
        }
        manifest["accepted_total"] += len(recs)

    manifest_path = view_root / "MANIFEST.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def verify_view(view_root: Path) -> dict:
    """Re-hash every category file against MANIFEST.json. Fail-closed."""
    manifest = json.loads((view_root / "MANIFEST.json").read_text(encoding="utf-8"))
    problems = []
    for cat, meta in manifest["categories"].items():
        f = REPO_ROOT / meta["path"]
        if not f.exists():
            problems.append(f"{cat}: missing {f}")
            continue
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        if actual != meta["sha256"]:
            problems.append(f"{cat}: sha256 mismatch")
        n = sum(1 for line in f.read_text(encoding="utf-8").splitlines() if line.strip())
        if n != meta["records"]:
            problems.append(f"{cat}: record count {n} != {meta['records']}")
    return {"verified": not problems, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build verified SFT views")
    parser.add_argument("--tag", required=True, help="view tag, e.g. atlas-sft-v0.1")
    parser.add_argument("--records", nargs="+", default=[str(p) for p in DEFAULT_RECORDS])
    parser.add_argument("--views-root", default=str(REPO_ROOT / "metadata" / "views"))
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--min-quality", type=int, default=7)
    args = parser.parse_args(argv)

    records = load_records([Path(p) for p in args.records])
    view_root = Path(args.views_root) / args.tag
    manifest = build_view(records, view_root,
                          max_tokens=args.max_tokens, min_quality=args.min_quality)
    result = verify_view(view_root)
    print(json.dumps({
        "view_root": str(view_root),
        "input_records": manifest["input_records"],
        "accepted_total": manifest["accepted_total"],
        "per_category": {c: m["records"] for c, m in manifest["categories"].items()},
        "rejections": manifest["rejections"],
        "duplicates_skipped": manifest["duplicates_skipped"],
        "verification": result,
    }, indent=2))
    return 0 if result["verified"] else 2


if __name__ == "__main__":
    sys.exit(main())
