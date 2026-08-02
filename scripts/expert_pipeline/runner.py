"""Runner for the Atlas Expert 6500 pilot extraction.

Single command to execute the pilot end-to-end:

  python scripts/expert_pipeline/runner.py --dry-run          # plan only
  python scripts/expert_pipeline/runner.py --sources swebench # one source
  python scripts/expert_pipeline/runner.py                    # full pilot

Guarantees:
- dry-run mode writes nothing
- existing output files are never overwritten (FileExistsError)
- output goes only to pilot paths (metadata/, tmp/, reports/)
- deterministic ids per source
- logging to stderr + optional log file
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from .adapters.arxiv import ArxivAdapter
from .adapters.openmath import OpenMathAdapter
from .adapters.swebench import SwebenchAdapter
from .constants import (
    PILOT_COMPOSITION,
    PILOT_TOTAL,
    QUALITY_REPORT_PATH,
    RECORDS_PATH,
    MANIFEST_PATH,
)
from .quality import (
    classify_gate,
    compute_dimensions,
    compute_quality_score,
    is_gold,
    scorer_version,
)
from .report import write_manifest, write_quality_report, write_records
from .validation import (
    detect_duplicates,
    security_scan,
    validate_license,
    validate_provenance,
    validate_schema,
)

LOG = logging.getLogger("expert_pipeline")

ADAPTERS = {
    "swebench": SwebenchAdapter,
    "openmath": OpenMathAdapter,
    "arxiv": ArxivAdapter,
}
# source_id -> adapter key
SOURCE_TO_KEY = {
    "expert-swe-001": "swebench",
    "expert-math-002": "openmath",
    "expert-aiml-001": "arxiv",
}


def _setup_logging(verbose: bool, log_file: Path | None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=level, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _score_and_validate(records: list[dict]) -> dict:
    """Score all records, run schema/provenance/license/security, aggregate."""
    dims_all: dict[str, list[int]] = {
        "correctness": [], "reasoning_depth": [], "explanation_quality": [], "provenance_confidence": [],
    }
    gate = Counter()
    gold = 0
    schema_failures: list[dict] = []
    prov_failures: list[dict] = []
    lic_failures: list[dict] = []
    security_flags: list[dict] = []

    for rec in records:
        dims = compute_dimensions(rec)
        rec["_dims"] = dims
        rec["metadata"]["quality_score"] = compute_quality_score(dims)
        for k, v in dims.items():
            dims_all[k].append(v)

        schema_errs = validate_schema(rec)
        prov_errs = validate_provenance(rec)
        lic_errs = validate_license(rec)
        sec = security_scan(rec)

        if schema_errs:
            schema_failures.append({"id": rec["id"], "errors": schema_errs[:5]})
        if prov_errs:
            prov_failures.append({"id": rec["id"], "errors": prov_errs})
        if lic_errs:
            lic_failures.append({"id": rec["id"], "errors": lic_errs})
        if sec:
            security_flags.append({"id": rec["id"], "hits": sec})

        schema_ok = not schema_errs
        label = classify_gate(rec, schema_ok, dims)
        gate[label] += 1
        if label == "KEEP" and is_gold(rec, dims):
            gold += 1

    n = len(records)
    dup = detect_duplicates(records)
    return {
        "records_checked": n,
        "schema": {
            "checked": n,
            "passed": n - len(schema_failures),
            "failed": len(schema_failures),
            "pass_rate": round((n - len(schema_failures)) / n, 4) if n else 0.0,
            "failures": schema_failures,
        },
        "provenance": {
            "checked": n,
            "complete": n - len(prov_failures),
            "rate": round((n - len(prov_failures)) / n, 4) if n else 0.0,
            "failures": prov_failures[:20],
        },
        "license": {
            "checked": n,
            "passed": n - len(lic_failures),
            "rate": round((n - len(lic_failures)) / n, 4) if n else 0.0,
            "failures": lic_failures[:20],
        },
        "security_flags": security_flags,
        "duplicates": {
            "exact_ids": len(dup["exact_duplicate_ids"]),
            "near_groups": len(dup["near_duplicate_groups"]),
            "records_involved": dup["duplicate_records_count"],
            "rate": round(dup["duplicate_records_count"] / n, 4) if n else 0.0,
        },
        "quality": {
            "dimension_means": {
                k: round(sum(v) / len(v), 3) if v else None for k, v in dims_all.items()
            },
            "quality_score_mean": round(sum(r["metadata"]["quality_score"] for r in records) / n, 3) if n else None,
            "quality_score_ge7": sum(1 for r in records if r["metadata"]["quality_score"] >= 7) if n else 0,
            "quality_score_distribution": dict(
                sorted((str(s), sum(1 for r in records if r["metadata"]["quality_score"] == s))
                       for s in sorted({r["metadata"]["quality_score"] for r in records}))
            ),
            "gate": dict(gate),
            "gate_distribution": {k: round(v / n, 4) for k, v in gate.items()} if n else {},
            "gold_candidates": gold,
            "scorer": scorer_version(),
        },
    }


def _build_report(stats: dict, per_source: dict[str, dict], dry_run: bool) -> dict:
    report = {
        "report_name": "expert_pilot_6500_quality_v0.1",
        "phase": "0.5 pilot extraction (Option A)",
        "dry_run": dry_run,
        "per_source": per_source,
        **stats,
    }
    return report


def run_pilot(sources: list[str] | None = None, limits: dict[str, int] | None = None,
              dry_run: bool = False, accessed_at: str | None = None) -> dict:
    """Execute pilot extraction. Returns aggregate stats dict."""
    keys = sources or list(ADAPTERS.keys())
    limits = limits or {}

    all_records: list[dict] = []
    per_source: dict[str, dict] = {}

    for key in keys:
        if key not in ADAPTERS:
            raise ValueError(f"unknown source adapter: {key}")
        adapter = ADAPTERS[key](accessed_at=accessed_at)
        source_id = adapter.source_id
        target = PILOT_COMPOSITION.get(source_id, 0)
        limit = limits.get(key)

        raw_rows = list(adapter.iter_raw(limit=limit or target))
        recs = [adapter.to_record(raw, i) for i, raw in enumerate(raw_rows)]

        # scored + validated per source for the manifest
        src_stats = _score_and_validate(recs)
        per_source[source_id] = {
            "name": adapter.source_name,
            "target": target,
            "retrieved_raw": len(raw_rows),
            "converted": len(recs),
            "dry_run": dry_run,
            **src_stats,
        }
        all_records.extend(recs)
        LOG.info("source %s: retrieved=%d converted=%d", source_id, len(raw_rows), len(recs))

    total_stats = _score_and_validate(all_records)
    report = _build_report(total_stats, per_source, dry_run)

    if not dry_run:
        write_records(all_records, RECORDS_PATH)
        write_manifest(per_source, all_records, MANIFEST_PATH)
        write_quality_report(report, QUALITY_REPORT_PATH)
        LOG.info("wrote records=%s manifest=%s report=%s", RECORDS_PATH, MANIFEST_PATH, QUALITY_REPORT_PATH)
    else:
        LOG.info("DRY RUN: would write %d records, manifest, and quality report", len(all_records))

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Atlas Expert 6500 pilot extraction runner")
    parser.add_argument("--dry-run", action="store_true", help="plan only; write nothing")
    parser.add_argument("--sources", nargs="*", choices=list(ADAPTERS.keys()),
                        default=None, help="subset of adapters (default: all)")
    parser.add_argument("--limit", type=int, default=None,
                        help="limit raw rows per source (testing only)")
    parser.add_argument("--accessed-at", default=None,
                        help="ISO date used for source.accessed_at (default: today)")
    parser.add_argument("--log-file", default=None, help="write logs to this file")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose, Path(args.log_file) if args.log_file else None)

    try:
        report = run_pilot(
            sources=args.sources,
            limits={k: args.limit for k in (args.sources or list(ADAPTERS.keys()))} if args.limit else None,
            dry_run=args.dry_run,
            accessed_at=args.accessed_at,
        )
        print(json.dumps({
            "dry_run": report["dry_run"],
            "records_checked": report["records_checked"],
            "schema_pass_rate": report["schema"]["pass_rate"],
            "gate": report["quality"]["gate"],
            "duplicate_rate": report["duplicates"]["rate"],
            "recommendation": "GO" if report["schema"]["pass_rate"] >= 0.99
            and report["quality"]["gate"].get("KEEP", 0) / max(report["records_checked"], 1) >= 0.90
            and report["duplicates"]["rate"] <= 0.01 else "HOLD",
        }, indent=2))
        return 0
    except FileExistsError as e:
        LOG.error("refusing to overwrite: %s", e)
        return 2
    except Exception as e:  # noqa: BLE001
        LOG.exception("pilot extraction failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
