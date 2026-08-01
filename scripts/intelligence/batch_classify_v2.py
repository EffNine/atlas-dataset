#!/usr/bin/env python3
"""
batch_classify_v2.py — full-source parallel classification for Atlas v1.x+.

Extends batch_classify.py to cover ALL raw/generated shards, not just the 4
v1.1 sources. Sources are grouped into ~16 affinity groups and processed in
parallel via ProcessPoolExecutor (one worker per group).

Usage:
  # Default: classify all sources, 8 workers
  python scripts/intelligence/batch_classify_v2.py --workers 8

  # Specific groups only
  python scripts/intelligence/batch_classify_v2.py --groups wikipedia mmlu tulu3

  # Dry run: show what would be classified
  python scripts/intelligence/batch_classify_v2.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Allow running as `python -m scripts.intelligence.batch_classify_v2`
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from difficulty_analyzer import process_file  # noqa: E402
from batch_classify import SourceConfig, merge_and_report  # noqa: E402

# ---------------------------------------------------------------------------
# Source groups
# ---------------------------------------------------------------------------

@dataclass
class SourceConfig:
    label: str
    glob_pattern: str
    description: str = ""

ALL_SOURCES: list[SourceConfig] = [
    # Wikipedia family (6.2M records)
    SourceConfig("wiki_ai",     "raw/generated/wiki_ai_shard*_atlas.jsonl",     "Wikipedia AI (40 shards)"),
    SourceConfig("wiki_sw",     "raw/generated/wiki_sw_shard*_atlas.jsonl",     "Wikipedia SW (10 shards)"),
    SourceConfig("wiki_sys",    "raw/generated/wiki_sys_shard*_atlas.jsonl",    "Wikipedia Systems (8 shards)"),
    SourceConfig("wiki_sci",    "raw/generated/wiki_sci_shard*_atlas.jsonl",    "Wikipedia Science (16 shards)"),
    SourceConfig("wiki_biz",    "raw/generated/wiki_biz_shard*_atlas.jsonl",    "Wikipedia Business (13 shards)"),
    SourceConfig("wiki_cre",    "raw/generated/wiki_cre_shard*_atlas.jsonl",    "Wikipedia Creative (8 shards)"),
    SourceConfig("wiki_hw",     "raw/generated/wiki_hw_shard*_atlas.jsonl",     "Wikipedia Hardware (9 shards)"),
    # Synthetic
    SourceConfig("synthetic_pa", "raw/generated/synthetic_test_v1.jsonl",        "Synthetic personal-assistant"),
    # Tulu-3 family (939k + 100k + 93k + 50k + 50k + 50k + 50k + 50k)
    SourceConfig("tulu3",       "raw/generated/tulu3_shard*_atlas.jsonl",       "Tulu-3 (6 shards)"),
    SourceConfig("tulu3_wildchat", "raw/generated/tulu_v3.9_wildchat_*_atlas.jsonl", "Tulu-3 WildChat"),
    SourceConfig("tulu3_aya",   "raw/generated/tulu_v3.9_aya_*_atlas.jsonl",    "Tulu-3 Aya"),
    SourceConfig("tulu3_wildjailbreak", "raw/generated/tulu_v3.9_wildjailbreak_*_atlas.jsonl", "Tulu-3 WildJailbreak"),
    SourceConfig("tulu3_openmath2", "raw/generated/tulu_v3.9_open_math_2_gsm8k_*_atlas.jsonl", "Tulu-3 OpenMath2"),
    SourceConfig("tulu3_synthetic_finalresp", "raw/generated/tulu_v3.9_synthetic_finalresp_*_atlas.jsonl", "Tulu-3 Synthetic FinalResp"),
    SourceConfig("tulu3_sciriff", "raw/generated/tulu_v3.9_sciriff_*_atlas.jsonl", "Tulu-3 SciRRF"),
    SourceConfig("tulu3_tablegpt", "raw/generated/tulu_v3.9_table_gpt_*_atlas.jsonl", "Tulu-3 TableGPT"),
    SourceConfig("tulu3_hardcoded", "raw/generated/tulu_v3.9_hard_coded_repeated_*_atlas.jsonl", "Tulu-3 Hard-coded"),
    # Math
    SourceConfig("openwebmath", "raw/generated/openwebmath_shard*_atlas.jsonl", "OpenWebMath (114 shards)"),
    SourceConfig("personahub_math", "raw/generated/personahub_math_*_atlas.jsonl", "PersonaHub Math"),
    SourceConfig("numinamath",  "raw/generated/numinamath_tir_math_*_atlas.jsonl", "NuminaMath TIR"),
    # Code
    SourceConfig("codealpaca_heval", "raw/generated/evol_codealpaca_heval_*_atlas.jsonl", "Evol CodeAlpaca + HEval"),
    SourceConfig("personahub_code", "raw/generated/personahub_code_*_atlas.jsonl", "PersonaHub Code"),
    SourceConfig("personahub_ifdata", "raw/generated/personahub_ifdata_*_atlas.jsonl", "PersonaHub IFData"),
    SourceConfig("swebench",    "raw/generated/swebench_atlas.jsonl",            "SWE-bench"),
    SourceConfig("codealpaca",  "raw/generated/codealpaca_atlas.jsonl",          "CodeAlpaca-20k"),
    # Instruction/chat
    SourceConfig("ultrafeedback", "raw/generated/ultrafeedback_atlas.jsonl",     "UltraFeedback"),
    SourceConfig("oasst1",      "raw/generated/oasst1_atlas.jsonl",              "OpenAssistant OASST1"),
    SourceConfig("oasst1_val",  "raw/generated/oasst1_val_atlas.jsonl",          "OASST1 validation"),
    SourceConfig("no_robots",   "raw/generated/no_robots_converted_atlas.jsonl", "NoRobots"),
    SourceConfig("coconot",     "raw/generated/coconot_converted_atlas.jsonl",   "CoCoNot"),
    SourceConfig("flan_v2",     "raw/generated/flan_v2_converted_atlas.jsonl",   "Flan V2"),
    # General QA/science
    SourceConfig("sciq",        "raw/generated/sciq_atlas.jsonl",                "SciQ"),
    SourceConfig("gsm8k",       "raw/generated/gsm8k_atlas.jsonl",               "GSM8K"),
    SourceConfig("mmlu",        "raw/generated/mmlu_*_atlas.jsonl",              "MMLU subsets (56 shards)"),
    SourceConfig("capybara",    "raw/generated/capybara_atlas.jsonl",            "Capybara"),
    SourceConfig("capybara_extra", "raw/generated/capybara_extra_atlas.jsonl",  "Capybara extra"),
    SourceConfig("fin_alpaca",  "raw/generated/fin-alpaca_atlas.jsonl",          "Finance Alpaca"),
    # C4
    SourceConfig("c4",          "raw/generated/c4_ai_shard*_atlas.jsonl",        "C4 AI/ML (12 shards)"),
    # ArXiv
    SourceConfig("arxiv_cs",    "raw/generated/arxiv_cs_atlas.jsonl",            "ArXiv CS"),
    SourceConfig("arxiv_hw",    "raw/generated/arxiv_hardware_atlas.jsonl",      "ArXiv Hardware"),
    SourceConfig("arxiv_ml",    "raw/generated/arxiv_ml_batch*_atlas.jsonl",     "ArXiv ML"),
    # Miscellaneous
    SourceConfig("gutenberg",   "raw/generated/gutenberg_*_atlas.jsonl",         "Project Gutenberg"),
    SourceConfig("github_readmes", "raw/generated/github_readmes_atlas.jsonl",   "GitHub READMEs"),
    SourceConfig("stackoverflow", "raw/generated/stackoverflow_atlas.jsonl",     "Stack Overflow"),
    SourceConfig("batch_new",   "raw/generated/batch_new_sources.jsonl",         "Batch new sources"),
]

# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _classify_one(config: SourceConfig, root: str, out_dir: str,
                  print_interval: int, shard_workers: int) -> dict[str, Any]:
    """Run classify_source_shards for one source (worker function)."""
    from batch_classify import classify_source_shards  # local import for pickling

    out_path = Path(out_dir) / f"classified_{config.label}.jsonl"
    stats = classify_source_shards(
        root_path=root,
        config=config,
        output_path=out_path,
        print_progress_interval=print_interval,
        shard_workers=shard_workers,
    )
    return stats

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repo root")
    ap.add_argument("--release", default="v1.2", help="Release tag for output filenames")
    ap.add_argument("--output-dir", default=None, help="Output dir (default: metadata/intelligence)")
    ap.add_argument("--temp-dir", default=None, help="Temp dir (default: metadata/intelligence/_tmp)")
    ap.add_argument("--workers", type=int, default=8, help="Parallel workers")
    ap.add_argument("--print-interval", type=int, default=20, help="Progress print every N shards")
    ap.add_argument("--shard-workers", type=int, default=1, help="Parallel workers within each source")
    ap.add_argument("--groups", nargs="*", default=None, help="Only run these source labels")
    ap.add_argument("--no-merge", action="store_true",
                    help="Skip merge_and_report (caller merges per-source files, e.g. run_classify_all_v2.py)")
    ap.add_argument("--dry-run", action="store_true", help="List sources, no work")
    args = ap.parse_args(argv)

    root = Path(args.root)
    out_dir = Path(args.output_dir) if args.output_dir else root / "metadata" / "intelligence"
    temp_dir = Path(args.temp_dir) if args.temp_dir else out_dir / "_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    sources = ALL_SOURCES
    if args.groups:
        sources = [s for s in sources if s.label in args.groups]

    # Dry run: show what each group would process
    if args.dry_run:
        print(f"Dry run | root={root} | workers={args.workers} | sources={len(sources)}")
        for s in sources:
            shards = sorted(root.glob(s.glob_pattern))
            shards = [f for f in shards if f.stat().st_size > 0]
            total_bytes = sum(f.stat().st_size for f in shards)
            print(f"  {s.label:25s} {len(shards):4d} shards  {total_bytes/1e9:.2f} GB  {s.description}")
        return 0

    print(f"Classify all sources | release={args.release} | workers={args.workers} | sources={len(sources)}")
    start = time.time()

    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_classify_one, s, str(root), str(temp_dir), args.print_interval, args.shard_workers): s
            for s in sources
        }
        for fut in as_completed(futures):
            s = futures[fut]
            try:
                stats = fut.result()
                results.append(stats)
                print(f"[DONE] {s.label}: {stats['classified']:,} records, {stats.get('elapsed','?')}", flush=True)
            except Exception as exc:
                print(f"[FAIL] {s.label}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                results.append({"label": s.label, "classified": 0, "errors": 1})

    elapsed = time.time() - start
    total_classified = sum(r.get("classified", 0) for r in results)
    print(f"\nAll sources done: {total_classified:,} records in {elapsed:.0f}s")

    if args.no_merge:
        print(f"Output: {temp_dir} (per-source files; --no-merge, caller merges)")
        return 0 if all(r.get("errors", 0) == 0 for r in results) else 1

    # Merge and generate reports
    print("Merging reports...")
    merge_and_report(
        results,
        output_dir=out_dir,
        temp_dir=temp_dir,
        release=args.release,
    )
    print(f"Output: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
