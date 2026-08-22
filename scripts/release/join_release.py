#!/usr/bin/env python3
"""Atlas Release Join Stage.

Streams the authoritative approved record list (review_queue/approved.jsonl)
and resolves every approved record into canonical release JSONL, routed by
category into releases/v1.0-RC1/dataset/<category>/.

Record resolution model (proven by investigation — see
docs/v1.0-RC1_release_input_investigation.md):

  approved.jsonl (9,893,844 records, matches frozen manifest exactly)
    ├── 8,350,296 full canonical records (messages inline)   → written as-is
    └── 1,543,548 review stubs (no messages)
          ├── 1,543,298 resolved from raw/generated/ shards (join by ID)
          └──       250 resolved from pilot/curated sources

Canonical output record = shard/pilot content + approved stub review fields
(category, subcategory, quality_score, license, verification_*) so the
approved category assignment and review metadata are preserved.

Output modes:
  --output-format jsonl  canonical JSONL (spec default)
  --output-format zst    streaming zstd JSONL (disk-safe; ~22GB vs ~5GB)

Usage:
  .venv-release/bin/python scripts/release/join_release.py \
      --approved review_queue/approved.jsonl \
      --shards raw/generated \
      --pattern '*_atlas.jsonl' \
      --output releases/v1.0-RC1/dataset \
      --output-format jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from common import (
    CATEGORIES,
    REPO_ROOT,
    iter_jsonl,
    open_zstd_writer,
    utc_now,
)

# Authoritative approved record list.
DEFAULT_APPROVED = REPO_ROOT / "review_queue" / "approved.jsonl"
# Source shards for stub content.
DEFAULT_SHARDS = REPO_ROOT / "raw" / "generated"
# Pilot/curated sources for the last 250 stub records.
DEFAULT_PILOT_DIRS = [
    REPO_ROOT / "curated" / "v0.1" / "data",
    REPO_ROOT / "curated" / "v0.2" / "data",
    REPO_ROOT / "raw" / "pilot",
    REPO_ROOT / "review" / "v0.2",
]
DEFAULT_MANIFEST = REPO_ROOT / "metadata" / "releases" / "v1.0-RC1_release.json"
DEFAULT_OUTPUT = REPO_ROOT / "releases" / "v1.0-RC1" / "dataset"
DEFAULT_REPORT = REPO_ROOT / "reports" / "releases" / "v1.0-RC1_join_report.json"

# Fields owned by the approved stub (review decisions) — override shard content.
STUB_AUTHORITY_FIELDS = (
    "category",
    "subcategory",
    "quality_score",
    "license",
    "verification_status",
    "verification_date",
    "reviewer",
)


def _source_key(rec: dict) -> str:
    """Best-effort provenance key for the report distribution."""
    src = rec.get("source")
    if isinstance(src, dict):
        name = src.get("name") or src.get("source_id")
        if name:
            return str(name)
    sa = rec.get("source_attribution")
    if isinstance(sa, dict) and sa.get("source_id"):
        return str(sa["source_id"])
    lineage = rec.get("lineage")
    if isinstance(lineage, dict) and lineage.get("source_id"):
        return str(lineage["source_id"])
    return "unknown"


def _canonical_id(rec: dict) -> str:
    return str(rec.get("id") or "")


def merge_record(stub: dict, content: dict) -> dict:
    """Merge approved stub review metadata into shard/pilot content.

    Content fields (messages, source, tags, difficulty, ...) come from the
    shard/pilot record; review decisions (category, subcategory,
    quality_score, license, verification_*) come from the approved stub.
    """
    out = dict(content)
    for field in STUB_AUTHORITY_FIELDS:
        if field in stub:
            out[field] = stub[field]
    # Ensure the canonical id is preserved from the approved record.
    out["id"] = stub.get("id") or content.get("id")
    return out


class ReleaseJoiner:
    """Streaming join of approved records + content sources."""

    def __init__(
        self,
        *,
        output_dir: Path,
        output_format: str = "jsonl",
        manifest_path: Path | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_format = output_format
        self.manifest_path = Path(manifest_path) if manifest_path else None
        self.manifest: dict[str, Any] = {}
        if self.manifest_path and self.manifest_path.exists():
            with self.manifest_path.open("r", encoding="utf-8") as fh:
                self.manifest = json.load(fh)

        self.writers: dict[str, Any] = {}
        self.stub_meta: dict[str, dict] = {}      # stub id -> approved stub record
        self.full_records = 0
        self.stub_records = 0
        self.joined_from_shards = 0
        self.joined_from_pilot = 0
        self.missing_stubs: list[str] = []
        self.duplicate_ids: list[str] = []
        self.written_ids: set[str] = set()
        self.written_by_cat: Counter[str] = Counter()
        self.provenance: Counter[str] = Counter()

    # -- output helpers -------------------------------------------------

    def _open_writer(self, category: str):
        cat_dir = self.output_dir / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        if self.output_format == "zst":
            # Write to temp file first, then rename for atomicity
            return open_zstd_writer(cat_dir / f"{category}.jsonl.zst.tmp")
        return (cat_dir / f"{category}.jsonl.tmp").open("w", encoding="utf-8")

    def _write(self, category: str, rec: dict) -> None:
        if category not in CATEGORIES:
            return
        if category not in self.writers:
            self.writers[category] = self._open_writer(category)
        line = json.dumps(rec, ensure_ascii=False)
        w = self.writers[category]
        if self.output_format == "zst":
            w.write((line + "\n").encode("utf-8"))
        else:
            w.write(line + "\n")
        rid = _canonical_id(rec)
        if rid in self.written_ids:
            self.duplicate_ids.append(rid)
        else:
            self.written_ids.add(rid)
        self.written_by_cat[category] += 1
        self.provenance[_source_key(rec)] += 1

    def close(self) -> None:
        for w in self.writers.values():
            try:
                w.close()
            except Exception:
                pass
        self.writers.clear()

    def finalize(self) -> None:
        """Atomically rename temp files to final output."""
        for cat_dir in self.output_dir.iterdir():
            if not cat_dir.is_dir():
                continue
            for tmp_file in cat_dir.glob("*.tmp"):
                final_file = tmp_file.with_suffix(tmp_file.suffix.replace(".tmp", ""))
                if tmp_file.exists():
                    tmp_file.rename(final_file)

    # -- pass 1: approved.jsonl ----------------------------------------

    def scan_approved(self, approved_path: Path) -> None:
        """Write full records; index stubs for later resolution."""
        for rec in iter_jsonl(approved_path):
            if "messages" in rec:
                self.full_records += 1
                self._write(str(rec.get("category", "unknown")), rec)
            else:
                self.stub_records += 1
                self.stub_meta[_canonical_id(rec)] = rec

    # -- pass 2: shards -------------------------------------------------

    def resolve_from_shards(self, shards_dir: Path, pattern: str) -> None:
        """Scan shards; resolve any stub whose id matches a shard record."""
        if not self.stub_meta:
            return
        for shard in sorted(Path(shards_dir).glob(pattern)):
            for rec in iter_jsonl(shard):
                rid = _canonical_id(rec)
                if rid in self.stub_meta:
                    stub = self.stub_meta.pop(rid)
                    merged = merge_record(stub, rec)
                    self.joined_from_shards += 1
                    self._write(str(stub.get("category", "unknown")), merged)

    # -- pass 3: pilot/curated sources ---------------------------------

    def resolve_from_pilot(self, pilot_dirs: list[Path]) -> None:
        """Resolve remaining stubs from pilot/curated record sources."""
        if not self.stub_meta:
            return
        for d in pilot_dirs:
            base = Path(d)
            if not base.is_dir():
                continue
            for f in sorted(base.glob("*.jsonl")):
                for rec in iter_jsonl(f):
                    # Some review input files wrap the record under "record".
                    payload = rec.get("record") if isinstance(rec.get("record"), dict) else rec
                    if not isinstance(payload, dict):
                        continue
                    rid = _canonical_id(payload)
                    if rid in self.stub_meta:
                        stub = self.stub_meta.pop(rid)
                        merged = merge_record(stub, payload)
                        self.joined_from_pilot += 1
                        self._write(str(stub.get("category", "unknown")), merged)

    # -- validation -----------------------------------------------------

    def validate(self) -> dict[str, Any]:
        self.missing_stubs = list(self.stub_meta.keys())
        total = sum(self.written_by_cat.values())
        expected_by_cat = {
            str(c): int(self.manifest.get("statistics", {}).get("by_category", {}).get(c, 0))
            for c in CATEGORIES
        }
        expected_total = int(self.manifest.get("total_records", 0))

        cat_ok = all(
            self.written_by_cat.get(c, 0) == expected_by_cat[c] for c in CATEGORIES
        )
        checks = {
            "total_records": {"expected": expected_total, "actual": total,
                              "ok": total == expected_total},
            "categories_match_manifest": {"ok": cat_ok,
                                          "actual": dict(self.written_by_cat),
                                          "expected": expected_by_cat},
            "no_duplicate_ids": {"ok": len(self.duplicate_ids) == 0,
                                 "count": len(self.duplicate_ids)},
            "no_missing_stubs": {"ok": len(self.missing_stubs) == 0,
                                 "count": len(self.missing_stubs)},
            "stubs_resolved": {
                "stub_records": self.stub_records,
                "from_shards": self.joined_from_shards,
                "from_pilot": self.joined_from_pilot,
                "ok": (self.joined_from_shards + self.joined_from_pilot
                       == self.stub_records),
            },
        }
        all_ok = all(c["ok"] for c in checks.values())
        return {"all_ok": all_ok, "checks": checks}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Assemble canonical Atlas release records from approved + content sources.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--approved", default=str(DEFAULT_APPROVED), help="approved.jsonl path")
    ap.add_argument("--shards", default=str(DEFAULT_SHARDS), help="shard directory")
    ap.add_argument("--pattern", default="*_atlas.jsonl", help="shard glob pattern")
    ap.add_argument(
        "--pilot-dirs",
        default=",".join(str(p) for p in DEFAULT_PILOT_DIRS),
        help="comma-separated pilot/curated dirs for the last 250 stubs",
    )
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT), help="dataset output dir")
    ap.add_argument(
        "--output-format", choices=("jsonl", "zst"), default="jsonl",
        help="jsonl = canonical JSONL (spec); zst = streaming zstd (disk-safe)",
    )
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="frozen release manifest")
    ap.add_argument("--report", default=str(DEFAULT_REPORT), help="join report output path")
    ap.add_argument(
        "--limit-approved",
        type=int,
        default=0,
        help="optional: process only first N approved records (testing)",
    )
    args = ap.parse_args(argv)

    approved_path = Path(args.approved)
    output_dir = Path(args.output)
    report_path = Path(args.report)
    pilot_dirs = [Path(p.strip()) for p in args.pilot_dirs.split(",") if p.strip()]

    print(
        f"Atlas release join | approved={approved_path.name} "
        f"| output_format={args.output_format} | output={output_dir}"
    )

    joiner = ReleaseJoiner(
        output_dir=output_dir,
        output_format=args.output_format,
        manifest_path=Path(args.manifest),
    )
    started = time.time()

    # Pass 1
    print("Pass 1: scanning approved.jsonl ...")
    if args.limit_approved:
        n = 0
        for rec in iter_jsonl(approved_path):
            if "messages" in rec:
                joiner.full_records += 1
                joiner._write(str(rec.get("category", "unknown")), rec)
            else:
                joiner.stub_records += 1
                joiner.stub_meta[_canonical_id(rec)] = rec
            n += 1
            if n >= args.limit_approved:
                break
    else:
        joiner.scan_approved(approved_path)
    print(f"  full records : {joiner.full_records:,}")
    print(f"  stub records : {joiner.stub_records:,}")

    # Pass 2
    print("Pass 2: resolving stubs from shards ...")
    joiner.resolve_from_shards(Path(args.shards), args.pattern)
    print(f"  joined from shards: {joiner.joined_from_shards:,}")

    # Pass 3
    print("Pass 3: resolving remaining stubs from pilot sources ...")
    joiner.resolve_from_pilot(pilot_dirs)
    print(f"  joined from pilot : {joiner.joined_from_pilot:,}")
    joiner.close()
    joiner.finalize()  # Atomically rename temp files to final output

    elapsed = time.time() - started
    validation = joiner.validate()

    report = {
        "release": "v1.0-RC1",
        "generated_at": utc_now(),
        "tool": "scripts/release/join_release.py",
        "output_format": args.output_format,
        "elapsed_s": round(elapsed, 2),
        "input": {
            "approved_path": str(approved_path),
            "shards_dir": str(Path(args.shards)),
            "pilot_dirs": [str(p) for p in pilot_dirs],
        },
        "statistics": {
            "approved_records": joiner.full_records + joiner.stub_records,
            "full_records_inline": joiner.full_records,
            "stub_records": joiner.stub_records,
            "joined_from_shards": joiner.joined_from_shards,
            "joined_from_pilot": joiner.joined_from_pilot,
            "skipped_records": 0,
            "duplicate_count": len(joiner.duplicate_ids),
            "missing_stub_count": len(joiner.missing_stubs),
            "missing_stub_sample": joiner.missing_stubs[:10],
            "category_distribution": dict(joiner.written_by_cat),
            "provenance_distribution": dict(joiner.provenance.most_common()),
        },
        "validation": validation,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"\nJoin completed in {elapsed:.1f}s")
    print(f"  approved records : {joiner.full_records + joiner.stub_records:,}")
    print(f"  joined from shards: {joiner.joined_from_shards:,}")
    print(f"  joined from pilot : {joiner.joined_from_pilot:,}")
    print(f"  missing stubs    : {len(joiner.missing_stubs)}")
    print(f"  duplicates       : {len(joiner.duplicate_ids)}")
    print(f"  category counts  : {dict(joiner.written_by_cat)}")
    for name, c in validation["checks"].items():
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {name}")
    print(f"\nReport: {report_path}")
    print(f"Output: {output_dir}")
    return 0 if validation["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
