#!/usr/bin/env python3
"""Atlas duplicate audit — read-only analysis of review_queue/approved.jsonl.

Identifies every record ID that appears more than once in the approved list
and characterizes the duplicate groups:

  - multiplicity distribution (2x / 3x / >3x)
  - byte-identical ratio (raw JSON bytes SHA-256)
  - content-identical ratio (messages SHA-256)
  - conflicting duplicates (messages differ)
  - same-category ratio and cross-category duplicates
  - source origin distribution
  - provenance consistency (source name/url/license, license, quality,
    verification status between occurrences)

Streams the input twice; holds only duplicate records in memory.
NEVER modifies any dataset. Audit only.

Usage:
  .venv-release/bin/python scripts/release/audit_duplicates.py \
      [--approved review_queue/approved.jsonl] \
      [--report reports/releases/v1.0-RC1_duplicate_audit.json] \
      [--limit N]   # stop after N lines (testing only)
"""
import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict


def iter_jsonl(path, limit=None):
    """Yield (raw_line_without_newline, parsed_record)."""
    n = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            yield line, json.loads(line)
            n += 1
            if limit is not None and n >= limit:
                break


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compact_record(rec: dict) -> dict:
    """Minimal comparable view of a record for duplicate characterization."""
    src = rec.get("source") or {}
    msgs = rec.get("messages")
    return {
        "raw_sha256": None,  # filled by caller with the raw line bytes
        "messages_sha256": (
            sha256(json.dumps(msgs, ensure_ascii=False, sort_keys=True))
            if msgs else "NO_MESSAGES"
        ),
        "category": rec.get("category"),
        "subcategory": rec.get("subcategory"),
        "quality_score": rec.get("quality_score"),
        "license": rec.get("license"),
        "verified": rec.get("verified"),
        "verification_status": rec.get("verification_status"),
        "reviewer": rec.get("reviewer"),
        "source_name": src.get("name"),
        "source_url": src.get("url"),
        "source_license": src.get("license"),
        "type": rec.get("type"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--approved", default="review_queue/approved.jsonl",
                    help="approved record list (authoritative source)")
    ap.add_argument("--report", default="reports/releases/v1.0-RC1_duplicate_audit.json",
                    help="output audit report path")
    ap.add_argument("--limit", type=int, default=None,
                    help="only read N lines (testing)")
    args = ap.parse_args()

    # ---- Pass 1: find IDs that appear more than once ----
    print("Pass 1: scanning for duplicate IDs ...")
    seen = set()
    dup_ids = set()
    total_records = 0
    for raw, rec in iter_jsonl(args.approved, args.limit):
        rid = rec.get("id")
        if rid is None:
            continue
        total_records += 1
        if rid in seen:
            dup_ids.add(rid)
        else:
            seen.add(rid)
    unique_ids = len(seen)
    print(f"  approved records : {total_records:,}")
    print(f"  unique ids       : {unique_ids:,}")
    print(f"  duplicate ids    : {len(dup_ids):,}")
    del seen  # free memory before pass 2

    # ---- Pass 2: capture compact records for duplicate IDs only ----
    print("Pass 2: capturing duplicate records ...")
    groups = defaultdict(list)  # id -> [compact, compact, ...]
    for raw, rec in iter_jsonl(args.approved, args.limit):
        rid = rec.get("id")
        if rid in dup_ids:
            c = compact_record(rec)
            c["raw_sha256"] = sha256(raw)
            groups[rid].append(c)
    print(f"  duplicate records captured: {sum(len(v) for v in groups.values()):,}")

    # ---- Analysis ----
    dup_records = sum(len(v) for v in groups.values())
    multiplicity = Counter(len(v) for v in groups.values())

    byte_identical = 0
    content_identical = 0
    conflicting = 0            # messages differ
    cross_category = 0
    same_category = 0
    metadata_conflict = 0      # messages same but metadata (license/quality/category/source) differs
    provenance_consistent = 0
    provenance_different = 0

    cat_of_dup = Counter()
    source_of_dup = Counter()
    subcat_of_dup = Counter()

    for rid, recs in groups.items():
        cat_of_dup[recs[0].get("category")] += 1
        source_of_dup[recs[0].get("source_name")] += 1
        subcat_of_dup[recs[0].get("subcategory")] += 1

        if len(recs) < 2:
            continue

        # pairwise comparison (handles 3x+ groups by comparing all pairs)
        g_byte_ident = True
        g_content_ident = True
        g_same_cat = True
        g_prov_consistent = True
        for a, b in zip(recs, recs[1:]):
            if a["raw_sha256"] != b["raw_sha256"]:
                g_byte_ident = False
            if a["messages_sha256"] != b["messages_sha256"]:
                g_content_ident = False
            if a["category"] != b["category"]:
                g_same_cat = False
            if not (
                a["source_name"] == b["source_name"]
                and a["source_url"] == b["source_url"]
                and a["source_license"] == b["source_license"]
                and a["license"] == b["license"]
                and a["quality_score"] == b["quality_score"]
                and a["verification_status"] == b["verification_status"]
            ):
                g_prov_consistent = False
        byte_identical += 1 if g_byte_ident else 0
        content_identical += 1 if g_content_ident else 0
        same_category += 1 if g_same_cat else 0
        cross_category += 0 if g_same_cat else 1
        provenance_consistent += 1 if g_prov_consistent else 0
        provenance_different += 0 if g_prov_consistent else 1
        if not g_content_ident:
            conflicting += 1
        elif not g_byte_ident:
            metadata_conflict += 1

    groups_total = len(groups)
    now = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat()
    report = {
        "release": "v1.0-RC1",
        "generated_at": now,
        "tool": "scripts/release/audit_duplicates.py",
        "input": {
            "approved_path": args.approved,
            "approved_total_records": total_records,
            "unique_ids": unique_ids,
            "duplicate_ids": len(dup_ids),
        },
        "summary": {
            "total_duplicate_ids": len(dup_ids),
            "total_duplicate_records": dup_records,
            "duplicate_groups": groups_total,
            "byte_identical_groups": byte_identical,
            "byte_identical_percentage": round(100.0 * byte_identical / groups_total, 4) if groups_total else 0.0,
            "content_identical_groups": content_identical,
            "content_identical_percentage": round(100.0 * content_identical / groups_total, 4) if groups_total else 0.0,
            "conflicting_duplicates": conflicting,
            "metadata_only_conflicts": metadata_conflict,
            "same_category_groups": same_category,
            "same_category_percentage": round(100.0 * same_category / groups_total, 4) if groups_total else 0.0,
            "cross_category_duplicates": cross_category,
            "provenance_consistent_groups": provenance_consistent,
            "provenance_consistent_percentage": round(100.0 * provenance_consistent / groups_total, 4) if groups_total else 0.0,
            "provenance_different_groups": provenance_different,
        },
        "multiplicity_distribution": {
            "2x": multiplicity.get(2, 0),
            "3x": multiplicity.get(3, 0),
            "gt3x": sum(v for k, v in multiplicity.items() if k > 3),
            "max_multiplicity": max(multiplicity) if multiplicity else 0,
            "distribution": dict(sorted(multiplicity.items())),
        },
        "category_distribution": dict(sorted(cat_of_dup.items())),
        "subcategory_distribution": dict(sorted(subcat_of_dup.items(), key=lambda kv: -kv[1])),
        "source_origin": {
            "total_duplicate_ids_by_source": dict(
                sorted(source_of_dup.items(), key=lambda kv: -kv[1])
            ),
            "unique_sources": len(source_of_dup),
        },
        "validation": {
            "all_groups_analyzed": groups_total == len(dup_ids),
            "all_duplicate_records_captured": dup_records == sum(
                k * v for k, v in multiplicity.items()
            ),
            "audit_only_no_modifications": True,
        },
    }

    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    s = report["summary"]
    print("\n=== DUPLICATE AUDIT SUMMARY ===")
    print(f"  total duplicate IDs      : {s['total_duplicate_ids']:,}")
    print(f"  total duplicate records  : {s['total_duplicate_records']:,}")
    print(f"  duplicate groups         : {s['duplicate_groups']:,}")
    print(f"  byte-identical           : {s['byte_identical_percentage']}%")
    print(f"  content-identical        : {s['content_identical_percentage']}%")
    print(f"  conflicting duplicates   : {s['conflicting_duplicates']:,}")
    print(f"  cross-category           : {s['cross_category_duplicates']:,}")
    print(f"  provenance consistent    : {s['provenance_consistent_percentage']}%")
    print(f"  multiplicity             : {report['multiplicity_distribution']['distribution']}")
    print(f"\nReport: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
