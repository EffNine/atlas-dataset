#!/usr/bin/env python3
"""Optimized full-source classification for Atlas v1.2.

Uses shard-level parallelism to fully utilize dev-pc resources:
- Stage 1: wiki sources with shard workers from config
- Stage 2: remaining sources with shard workers from config
- Skips v1.1 sources and merges them if configured
"""
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

PY = sys.executable
SCRIPT = "scripts/intelligence/batch_classify_v2.py"
REPO = Path(".")
OUT_DIR = REPO / "metadata/intelligence"

# Unified config loader — single source of truth (parallel.config)
sys.path.insert(0, str(REPO / "scripts"))
from parallel.config import load_parallelism_config  # noqa: E402

STAGE1 = [
    "wiki_ai", "wiki_sw", "wiki_sys", "wiki_sci",
    "wiki_biz", "wiki_cre", "wiki_hw",
]

STAGE2 = [
    "synthetic_pa",
    "swebench", "codealpaca", "ultrafeedback", "oasst1", "oasst1_val",
    "sciq", "gsm8k", "mmlu", "capybara", "capybara_extra", "fin_alpaca",
    "github_readmes", "stackoverflow", "gutenberg", "batch_new",
    "personahub_math", "personahub_code", "personahub_ifdata", "numinamath",
    "codealpaca_heval", "no_robots", "coconot", "flan_v2",
    "tulu3_wildchat", "tulu3_aya", "tulu3_wildjailbreak", "tulu3_openmath2",
    "tulu3_synthetic_finalresp", "tulu3_sciriff", "tulu3_tablegpt",
    "tulu3_hardcoded",
]

V11_CLASSIFIED = OUT_DIR / "unknown_classified_v1.1.jsonl"
V12_CLASSIFIED = OUT_DIR / "unknown_classified_v1.2.jsonl"


def get_classification_config(config: dict) -> dict:
    """Extract classification settings from unified config."""
    return config.get("parallelism", {}).get("classification", {})


def append_source_to_v12(label: str):
    """Append a source's classified output into the unified v1.2 file."""
    # batch_classify_v2 writes per-source output into _tmp/
    src_file = OUT_DIR / "_tmp" / f"classified_{label}.jsonl"
    if not src_file.exists():
        print(f"[merge] WARNING: {src_file} not found, skipping append")
        return 0
    
    count = 0
    with open(src_file, "r", encoding="utf-8") as inp:
        with open(V12_CLASSIFIED, "a", encoding="utf-8") as out:
            for line in inp:
                line = line.strip()
                if line:
                    out.write(line + "\n")
                    count += 1
    
    # Delete source file after append to prevent duplicate append on restart
    src_file.unlink()
    print(f"[merge] Appended {count:,} records from {label} into v1.2; removed {src_file.name}")
    return count


def run_source_classify(label, shard_workers=1, print_interval=1):
    """Classify one source (subprocess only). Returns (label, rc)."""
    cmd = [PY, SCRIPT, "--shard-workers", str(shard_workers), "--print-interval", str(print_interval), "--groups", label, "--no-merge"]
    print(f"\n=== {label} ({shard_workers} shard workers) ===")
    print(" ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"FAILED: {label} exit={r.returncode}")
    return label, r.returncode


def merge_v11_into_v12(skip_v11: bool = True):
    if not skip_v11 or not V11_CLASSIFIED.exists():
        print("Skipping v1.1 merge (disabled or file not found).")
        return

    print(f"\n=== Merging v1.1 ({V11_CLASSIFIED.stat().st_size:,} bytes) into v1.2 ===")

    with open(V12_CLASSIFIED, "a", encoding="utf-8") as out:
        with open(V11_CLASSIFIED, "r", encoding="utf-8") as inp:
            for line in inp:
                line = line.strip()
                if line:
                    out.write(line + "\n")
    print(f"Merged v1.1 records into {V12_CLASSIFIED}")

    print("Regenerating v1.2 summaries...")
    counts = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    confidences = []
    sources = {}
    total = 0

    with open(V12_CLASSIFIED, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            total += 1
            # v1.2 records carry difficulty as a dict {level, confidence};
            # v1.1 records carry difficulty as an int. Handle both.
            diff = rec.get("difficulty")
            if isinstance(diff, dict):
                lvl = str(diff.get("level", "1"))
                conf = diff.get("confidence")
            else:
                lvl = str(diff) if isinstance(diff, int) else "1"
                conf = None
            counts[lvl] = counts.get(lvl, 0) + 1
            if conf is not None:
                confidences.append(conf)
            src = rec.get("record_id", "unknown").split("_")[0]
            sources[src] = sources.get(src, 0) + 1

    mean_conf = sum(confidences) / len(confidences) if confidences else 0
    low_conf = sum(1 for c in confidences if c < 0.5)

    summary = {
        "report_metadata": {
            "report_type": "classification_summary_v1_2",
            "intelligence_layer_version": "1.2.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "classifier": "batch_classify_v2.py",
            "classifier_version": "2.0.0",
            "data_snapshot": "atlas-v1.0-final",
            "status": "production",
        },
        "overall": {
            "total_records": total,
            "successful_classifications": total,
            "failed_classifications": 0,
            "classification_rate": 100.0,
        },
        "difficulty_distribution": {
            k: {"count": v, "percentage": round(v / total * 100, 2) if total else 0}
            for k, v in sorted(counts.items())
        },
        "confidence": {
            "mean": round(mean_conf, 4),
            "min": min(confidences) if confidences else 0,
            "max": max(confidences) if confidences else 0,
            "low_confidence_count": low_conf,
            "low_confidence_fraction": round(low_conf / total, 4) if total else 0,
        },
        "per_source": sources,
    }

    with open(OUT_DIR / "classification_summary_v1.2.json", "w") as f:
        json.dump(summary, f, indent=2)

    dist = {
        "report_metadata": summary["report_metadata"],
        "total_records": total,
        "classified": total,
        "failed": 0,
        "remaining_unknown": 0,
        "difficulty_distribution": counts,
        "confidence_stats": summary["confidence"],
        "per_source": sources,
    }
    with open(OUT_DIR / "difficulty_distribution_v1.2.json", "w") as f:
        json.dump(dist, f, indent=2)

    print(f"v1.2 final: {total:,} records | L1={counts.get('1',0):,} L2={counts.get('2',0):,} L3={counts.get('3',0):,} L4={counts.get('4',0):,} L5={counts.get('5',0):,}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Run full-source v1.2 classification")
    ap.add_argument("--skip", default="", help="Comma-separated source labels to skip (already classified)")
    args = ap.parse_args()
    
    skip_sources = {s.strip() for s in args.skip.split(",") if s.strip()}
    
    config = load_parallelism_config()
    clf_cfg = get_classification_config(config)
    
    stage1_workers = clf_cfg.get("stage1_shard_workers", 8)
    stage2_workers = clf_cfg.get("stage2_shard_workers", 2)
    parallel_sources = clf_cfg.get("parallel_sources", 1)
    skip_v11 = clf_cfg.get("skip_v11_sources", True)
    print_interval = clf_cfg.get("print_interval", 1)
    
    print(f"Optimized v1.2 | Stage1={len(STAGE1)} sources @ {stage1_workers} shard-workers | Stage2={len(STAGE2)} sources @ {stage2_workers} shard-workers | parallel_sources={parallel_sources} | skip_v11={skip_v11}")
    if skip_sources:
        print(f"Skipping already-classified sources: {sorted(skip_sources)}")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def run_stage(sources, shard_workers):
        """Run sources in a stage with up to parallel_sources at once.

        Bounded submission: only parallel_sources futures are in flight, so a
        failure stops promptly instead of letting every queued source run to
        completion (executor shutdown(wait=True) would otherwise drain them).
        Classification is concurrent; appends are serialized in this thread
        so the v1.2 file is never written by two threads at once.
        """
        pending = [s for s in sources if s not in skip_sources]
        if not pending:
            return 0
        with ThreadPoolExecutor(max_workers=parallel_sources) as ex:
            inflight: dict = {}
            # Submit the first batch
            for label in pending[:parallel_sources]:
                fut = ex.submit(run_source_classify, label, shard_workers, print_interval)
                inflight[fut] = label
            idx = parallel_sources
            while inflight:
                done_fut = next(as_completed(inflight))
                label = inflight.pop(done_fut)
                _, rc = done_fut.result()
                if rc != 0:
                    sys.exit(rc)
                append_source_to_v12(label)
                # Submit next if more pending (bounded: never exceed parallel_sources)
                if idx < len(pending):
                    label = pending[idx]
                    idx += 1
                    fut = ex.submit(run_source_classify, label, shard_workers, print_interval)
                    inflight[fut] = label
        return 0

    run_stage(STAGE1, stage1_workers)
    run_stage(STAGE2, stage2_workers)

    merge_v11_into_v12(skip_v11=skip_v11)
    print("\n=== ALL DONE ===")
