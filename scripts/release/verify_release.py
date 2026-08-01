#!/usr/bin/env python3
"""Verify an Atlas release bundle end-to-end (local, pre-upload).

Checks:
  1. folder structure — all 9 category dirs + metadata/ + docs/ present
  2. compressed files — every .jsonl.zst decompresses and line count matches
     statistics.json
  3. checksums.sha256 — every file matches its recorded SHA-256
  4. record counts — per-category counts match statistics.json and
     release.json
  5. release metadata — release.json parses; total_records consistent

Usage:
  .venv-release/bin/python scripts/release/verify_release.py \
      --release v1.0-RC1 [--output releases/v1.0-RC1]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import CATEGORIES, REPO_ROOT, count_jsonl_zst, read_json, sha256_file

DEFAULT_RELEASE = "v1.0-RC1"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify an Atlas release bundle locally.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--release", default=DEFAULT_RELEASE, help="Release version tag.")
    ap.add_argument(
        "--output",
        default=None,
        help="Release root (default: <repo>/releases/<release>).",
    )
    args = ap.parse_args(argv)

    release_root = (
        Path(args.output) if args.output else REPO_ROOT / "releases" / args.release
    )
    if not release_root.exists():
        print(f"ERROR: release root does not exist: {release_root}")
        return 2

    problems: list[str] = []
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))
        if not ok:
            problems.append(f"{name}: {detail}")

    # 1. Folder structure.
    dataset_dir = release_root / "dataset"
    metadata_dir = release_root / "metadata"
    docs_dir = release_root / "docs"
    check("structure:dataset", dataset_dir.is_dir(), str(dataset_dir))
    check("structure:metadata", metadata_dir.is_dir(), str(metadata_dir))
    check("structure:docs", docs_dir.is_dir(), str(docs_dir))
    missing_cats = [c for c in CATEGORIES if not (dataset_dir / c).is_dir()]
    check(
        "structure:9-categories",
        not missing_cats,
        f"missing: {missing_cats}" if missing_cats else "all present",
    )

    # 2. Release metadata.
    release_json = metadata_dir / "release.json"
    check("metadata:release.json", release_json.exists(), str(release_json))
    stats_json = metadata_dir / "statistics.json"
    check("metadata:statistics.json", stats_json.exists(), str(stats_json))
    prov_json = metadata_dir / "provenance.json"
    check("metadata:provenance.json", prov_json.exists(), str(prov_json))
    checksum_file = metadata_dir / "checksums.sha256"
    check("metadata:checksums.sha256", checksum_file.exists(), str(checksum_file))

    declared_total = None
    if release_json.exists():
        try:
            rel = read_json(release_json)
            declared_total = rel.get("total_records")
            check(
                "metadata:release.json-parses",
                True,
                f"total_records={declared_total}",
            )
        except Exception as exc:
            check("metadata:release.json-parses", False, str(exc))

    expected_by_cat: dict[str, int] = {}
    actual_total = 0
    if stats_json.exists():
        try:
            stats = read_json(stats_json)
            by_cat = stats.get("by_category", {})
            expected_by_cat = {c: int(by_cat.get(c, 0)) for c in CATEGORIES}
            actual_total = int(stats.get("total_records", 0))
            check(
                "metadata:statistics-consistent",
                sum(expected_by_cat.values()) == actual_total,
                f"sum(by_category)={sum(expected_by_cat.values())} total={actual_total}",
            )
        except Exception as exc:
            check("metadata:statistics.json-parses", False, str(exc))

    # 3. Compressed files — decompress, count, compare to statistics.
    zst_files = sorted(dataset_dir.rglob("*.jsonl.zst"))
    check("dataset:zst-files-present", len(zst_files) > 0, f"{len(zst_files)} files")
    counted_by_cat: dict[str, int] = {c: 0 for c in CATEGORIES}
    for zf in zst_files:
        rel = zf.relative_to(dataset_dir)
        cat = rel.parts[0]
        try:
            n = count_jsonl_zst(zf)
            counted_by_cat[cat] += n
            check(
                f"dataset:{rel.name}-decompresses",
                True,
                f"{n} records",
            )
        except Exception as exc:
            check(f"dataset:{rel.name}-decompresses", False, str(exc))

    if expected_by_cat:
        for c in CATEGORIES:
            exp = expected_by_cat.get(c, 0)
            act = counted_by_cat.get(c, 0)
            check(
                f"counts:{c}",
                act == exp,
                f"expected={exp} actual={act}",
            )
        if declared_total is not None and declared_total > 0:
            check(
                "counts:total-vs-release",
                actual_total == declared_total,
                f"statistics={actual_total} release={declared_total}",
            )

    # 4. Checksums.
    if checksum_file.exists():
        expected: dict[str, str] = {}
        try:
            for line in checksum_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                hexd, rel = line.split("  ", 1)
                expected[rel] = hexd
        except Exception as exc:
            check("checksums:parse", False, str(exc))
            expected = {}
        mismatch = 0
        missing = 0
        for rel, hexd in expected.items():
            fp = release_root / rel
            if not fp.exists():
                missing += 1
                continue
            if sha256_file(fp) != hexd:
                mismatch += 1
        check("checksums:all-match", mismatch == 0 and missing == 0,
              f"mismatch={mismatch} missing={missing} entries={len(expected)}")

    # Report.
    print(f"Release verification: {args.release} ({release_root})")
    print(f"{'check':<42}{'status':<8}detail")
    print("-" * 100)
    for name, ok, detail in checks:
        print(f"{name:<42}{'PASS' if ok else 'FAIL':<8}{detail}")
    print("-" * 100)
    passed = len([c for c in checks if c[1]])
    print(f"{passed}/{len(checks)} checks passed")
    if problems:
        print(f"\nFAILED ({len(problems)}):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nRESULT: RELEASE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
