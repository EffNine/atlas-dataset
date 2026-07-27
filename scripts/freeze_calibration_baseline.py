#!/usr/bin/env python3
"""
freeze_calibration_baseline.py — Phase 3C.1 frozen calibration snapshot.

Reads the CURRENT on-disk calibration inputs (human reviews + reviewed
candidate knowledge objects) and emits two immutable reference artifacts:

  * metadata/calibration_baseline_v0.1.json  — the frozen quality-model
    snapshot (distributions + correlation/bias/confidence + approval rates),
    for future re-calibration comparison.
  * metadata/checksums_v0.1.json             — sha256 of every reviewed
    knowledge object, the review file, all schemas, and all manifests, so
    accidental modification of the frozen baseline's inputs can be detected.

This script is STRICTLY READ-ONLY on all inputs. It never writes dataset
records, the review file, schemas, or manifests. It only writes the two
artifact files above. Re-running it recomputes from scratch (idempotent).

Usage:
  python scripts/freeze_calibration_baseline.py            # create artifacts
  python scripts/freeze_calibration_baseline.py --verify   # check checksums drift
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# --- load canonical calibration framework (single source of truth) ---
_qspec = importlib.util.spec_from_file_location(
    "calibrate_quality", ROOT / "scripts" / "calibrate_quality.py")
_cq = importlib.util.module_from_spec(_qspec)
_qspec.loader.exec_module(_cq)


def load_jsonl(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# Files whose hashes we register. All paths are repo-relative so the registry
# is portable across clones.
TRACKED = [
    # reviewed knowledge objects
    "curated/v0.1/pilot_candidates.jsonl",
    "raw/pilot/seed.jsonl",
    # review file
    "review/quality_reviews.jsonl",
    # schemas
    "schemas/quality_review_schema.json",
    "schemas/knowledge_object_schema.json",
    "schemas/dataset_schema.json",
    "schemas/chat_schema.json",
    # manifests / metadata (everything that existed before this freeze)
    "metadata/pilot_manifest.json",
    "metadata/acquisition_manifest_v0.1.json",
    "metadata/ingestion_plan_v0.1.json",
    "metadata/sources.json",
    "metadata/source_registry.json",
    "metadata/categories.json",
    "metadata/calibration_report.json",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_baseline(report: dict, reviews: list[dict]) -> dict:
    """Derive the frozen snapshot fields from the canonical calibration report."""
    g = report["global"]
    n = report["n_matched"]

    # Distribution of the 1..10 scores.
    human_scores = [int(r["human_score"]) for r in reviews]
    auto_scores = [p["auto"] for p in
                   []]  # recomputed below from report pairs if needed
    # We don't have raw pairs here; recompute auto via the report's per-record
    # data is unavailable, but by_category/by_source auto_mean is constant (7.0)
    # — instead reconstruct the auto distribution directly from the calibration
    # pairs embedded nowhere, so recompute quickly from the same function path.
    # Simpler: auto distribution is captured in global via mean; for the
    # per-score histogram we recompute it deterministically below.

    human_dist = {str(s): human_scores.count(s) for s in range(1, 11)}
    human_dist = {k: v for k, v in human_dist.items() if v}

    # AI (auto) score distribution — recompute from candidates via the same
    # scorer used by calibrate_quality so it is guaranteed identical.
    auto_dist = {str(s): 0 for s in range(1, 11)}
    for p in report.get("_pairs", []):
        auto_dist[str(int(p["auto"]))] = auto_dist.get(str(int(p["auto"])), 0) + 1
    auto_dist = {k: v for k, v in auto_dist.items() if v}

    # Approval / rejection rates from human verdicts.
    verdicts = Counter(str(r.get("verdict", "")).lower() for r in reviews)
    approve = verdicts.get("approve", 0)
    needs_revision = verdicts.get("needs_revision", 0)
    reject = verdicts.get("reject", 0)
    approval_rate = round(approve / n, 4) if n else 0.0
    rejection_rate = round((needs_revision + reject) / n, 4) if n else 0.0

    # Bias metrics (global + per-stratum condensed view).
    bias_metrics = {
        "global_mean_bias": g["mean_bias"],
        "global_mae": g["mae"],
        "global_rmse": g["rmse"],
        "per_category_mean_bias": {
            k: v["mean_bias"] for k, v in report["by_category"].items()},
        "per_source_mean_bias": {
            k: v["mean_bias"] for k, v in report["by_source"].items()},
        "max_abs_category_bias": max(
            (abs(v["mean_bias"]) for v in report["by_category"].values()),
            default=0.0),
        "max_abs_source_bias": max(
            (abs(v["mean_bias"]) for v in report["by_source"].values()),
            default=0.0),
    }

    # Confidence metrics (per-stratum reliability + global summary).
    cat_conf = {k: v["confidence"] for k, v in report["by_category"].items()}
    src_conf = {k: v["confidence"] for k, v in report["by_source"].items()}
    mandatory = [k for k, v in report["by_source"].items()
                 if v["gate"] == "MANDATORY_HUMAN_REVIEW"]
    confidence_metrics = {
        "per_category_confidence": cat_conf,
        "per_source_confidence": src_conf,
        "min_category_confidence": min(cat_conf.values(), default=0.0),
        "min_source_confidence": min(src_conf.values(), default=0.0),
        "mandatory_human_review_strata": mandatory,
        "n_mandatory_human_review_strata": len(mandatory),
    }

    return {
        "artifact": "atlas-calibration-baseline",
        "baseline_version": "v0.1",
        "framework_version": report["version"],
        "dataset_version": "v0.1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_calibration_report": "metadata/calibration_report.json",
        "reviewed_record_count": n,
        "accept_threshold": report["accept_threshold"],
        "human_score_distribution": human_dist,
        "ai_score_distribution": auto_dist,
        "correlation_metrics": {
            "pearson_r": g["pearson_r"],
            "spearman_rho": g["spearman_rho"],
            "exact_agree": g["exact_agree"],
            "within1_agree": g["within1_agree"],
            "auto_mean": g["auto_mean"],
            "human_mean": g["human_mean"],
            "hallucination_rate": g["hallucination_rate"],
        },
        "bias_metrics": bias_metrics,
        "confidence_metrics": confidence_metrics,
        "approval_rate": approval_rate,
        "rejection_rate": rejection_rate,
        "verdict_distribution": dict(verdicts),
        "readiness_verdict": report["readiness"]["verdict"],
        "thresholds": report["thresholds"],
        "note": ("Frozen for future comparison. Do not edit by hand; regenerate "
                 "only after a deliberate re-calibration decision."),
    }


def build_checksums() -> dict:
    files = []
    for rel in TRACKED:
        p = ROOT / rel
        if not p.exists():
            files.append({"path": rel, "status": "missing"})
            continue
        data = p.read_bytes()
        files.append({
            "path": rel,
            "sha256": sha256_file(p),
            "bytes": len(data),
            "lines": data.decode("utf-8", "replace").count("\n"),
        })
    present = [f for f in files if f.get("status") != "missing"]
    return {
        "artifact": "atlas-checksum-registry",
        "registry_version": "v0.1",
        "dataset_version": "v0.1",
        "generated": datetime.now(timezone.utc).isoformat(),
        "algorithm": "sha256",
        "purpose": ("Detect accidental modification of reviewed knowledge "
                    "objects, the review file, schemas, and manifests."),
        "files": files,
        "summary": {
            "tracked": len(TRACKED),
            "present": len(present),
            "missing": len(TRACKED) - len(present),
            "total_bytes": sum(f.get("bytes", 0) for f in present),
        },
    }


def verify_checksums(registry_path: Path) -> int:
    reg = json.loads(registry_path.read_text(encoding="utf-8"))
    failures = []
    for entry in reg["files"]:
        rel = entry["path"]
        p = ROOT / rel
        if entry.get("status") == "missing":
            failures.append(f"MISSING  {rel}")
            continue
        actual = sha256_file(p)
        if actual != entry["sha256"]:
            failures.append(f"DRIFT    {rel}  expected={entry['sha256'][:12]} "
                            f"actual={actual[:12]}")
    if failures:
        print("[verify] CHECKSUM DRIFT DETECTED:")
        for f in failures:
            print(f"  {f}")
        return 1
    print(f"[verify] OK — {reg['summary']['present']} files unchanged "
          f"(sha256 match).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify", action="store_true",
                    help="Verify existing checksums_v0.1.json instead of "
                         "regenerating the baseline.")
    args = ap.parse_args()

    reg_path = ROOT / "metadata" / "checksums_v0.1.json"
    if args.verify:
        if not reg_path.exists():
            print("[verify] registry not found; run without --verify first.",
                  file=sys.stderr)
            return 1
        return verify_checksums(reg_path)

    # --- read-only inputs ---
    reviews = load_jsonl(ROOT / "review" / "quality_reviews.jsonl")
    candidates = load_jsonl(ROOT / "curated" / "v0.1" / "pilot_candidates.jsonl")

    # canonical calibration (recomputes auto-scores from current heuristic)
    report = _cq.calibrate(reviews, candidates)

    # re-inject the per-record pairs so we can build the auto-score histogram
    # without re-implementing the scorer. calibrate() does not return pairs, so
    # we rebuild them via the same helper it uses internally.
    cand_by_id = {c["id"]: c for c in candidates}
    pairs = []
    for rv in reviews:
        cand = cand_by_id.get(rv["record_id"])
        if cand is None:
            continue
        auto_score, _ = _cq._quality.score_record(cand)
        pairs.append({"auto": auto_score})
    report["_pairs"] = pairs

    baseline = build_baseline(report, reviews)
    checksums = build_checksums()

    out_baseline = ROOT / "metadata" / "calibration_baseline_v0.1.json"
    out_checks = reg_path
    out_baseline.write_text(json.dumps(baseline, indent=2) + "\n",
                            encoding="utf-8")
    out_checks.write_text(json.dumps(checksums, indent=2) + "\n",
                          encoding="utf-8")

    print(f"[freeze] wrote {out_baseline.relative_to(ROOT)}")
    print(f"[freeze] wrote {out_checks.relative_to(ROOT)}")
    print(f"[freeze] reviewed={baseline['reviewed_record_count']} "
          f"verdict={baseline['readiness_verdict']} "
          f"approval_rate={baseline['approval_rate']} "
          f"rejection_rate={baseline['rejection_rate']}")
    print(f"[freeze] ai_score_distribution={baseline['ai_score_distribution']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
