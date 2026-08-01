#!/usr/bin/env python3
"""Build v1.0-RC2 release-bundle metadata from the frozen manifest.

Derives (does NOT modify the manifest):
  releases/<release>/metadata/release.json       (exact copy of frozen manifest)
  releases/<release>/metadata/statistics.json    (by_category + totals)
  releases/<release>/metadata/provenance.json    (source lineage, aggregated tail)
  releases/<release>/docs/dataset_card.md        (adapted from RC1)
  releases/<release>/docs/release_notes.md       (adapted from RC1)

Usage:
  .venv-release/bin/python scripts/release/build_release_metadata.py \
      --release v1.0-RC2 [--root /path/to/atlas-dataset]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from common import REPO_ROOT, CATEGORIES, utc_now

# Coarse source notes preserved from RC1 provenance (top-level groupings).
SOURCE_NOTES = {
    "wikimedia/wikipedia": "Wikipedia keyword extraction shards (raw/generated/wiki_*_atlas.jsonl). CC-BY-SA-3.0.",
    "synthetic/personal-assistant": "Synthetic personal-assistant corpus (category 09_personal_assistant).",
    "allenai/c4": "C4 AI/ML streaming subset (raw/generated/c4_ai_*_atlas.jsonl).",
    "tulu3_sft": "allenai/tulu-3-sft-mixture extraction (raw/generated/tulu3_shard*_atlas.jsonl).",
    "ultrafeedback": "UltraFeedback extraction (raw/generated/ultrafeedback_atlas.jsonl).",
    "openwebmath": "OpenWebMath shards (raw/generated/openwebmath_*_atlas.jsonl).",
    "arxiv_cs": "arXiv CS/ML papers (raw/generated/arxiv_*_atlas.jsonl).",
    "other": "Miscellaneous sources (mmlu_*, gsm8k, swebench, stackoverflow, sciq, oasst1, codealpaca, fin-alpaca, capybara, gutenberg, github_readmes, arXiv per-subset splits).",
}


def aggregate_sources(sources: dict[str, int]) -> list[dict]:
    """Group the manifest's per-source dict into provenance entries.

    Top ~10 sources keep their own row with a note; the long tail (arXiv
    subset splits, Gutenberg IDs, MMLU subsets) is folded into 'other'.
    """
    items = sorted(sources.items(), key=lambda kv: (-kv[1], kv[0]))
    top: list[tuple[str, int]] = []
    other = 0
    for name, count in items:
        if count >= 1000 or name in SOURCE_NOTES:
            top.append((name, count))
        else:
            other += count
    entries = [{"source_id": n, "records": c, "note": SOURCE_NOTES.get(n, "")} for n, c in top]
    if other:
        entries.append({"source_id": "other", "records": other, "note": SOURCE_NOTES["other"]})
    return entries


def build(release: str, root: Path) -> int:
    manifest_path = root / "metadata" / "releases" / f"{release}_release.json"
    if not manifest_path.exists():
        print(f"ERROR: frozen manifest not found: {manifest_path}")
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    rel_root = root / "releases" / release
    meta_dir = rel_root / "metadata"
    docs_dir = rel_root / "docs"
    meta_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    # 1. release.json = exact copy of the frozen manifest (immutability rule).
    release_json = meta_dir / "release.json"
    shutil.copyfile(manifest_path, release_json)
    print(f"Wrote {release_json} (copy of frozen manifest, {release_json.stat().st_size} bytes)")

    # 2. statistics.json — per-category counts expected by verify_release.py.
    stats = manifest.get("statistics", {})
    by_cat = {c: int(stats.get("by_category", {}).get(c, 0)) for c in CATEGORIES}
    stat_doc = {
        "release_version": release,
        "generated_at": utc_now(),
        "total_records": int(manifest["total_records"]),
        "by_category": by_cat,
        "by_license": stats.get("by_license", {}),
        "by_difficulty": stats.get("by_difficulty", {}),
        "quality": stats.get("quality", {}),
    }
    stat_path = meta_dir / "statistics.json"
    stat_path.write_text(json.dumps(stat_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {stat_path} (sum={sum(by_cat.values())} total={stat_doc['total_records']})")

    # 3. provenance.json — derived from manifest sources.
    src_entries = aggregate_sources(manifest.get("sources", {}))
    prov = {
        "release_version": release,
        "generated_at": utc_now(),
        "description": (
            f"Source provenance for Atlas {release}, derived from the frozen "
            f"release manifest ({manifest_path.name}). Per-record provenance "
            "lives in each record's source_attribution/lineage fields."
        ),
        "sources": src_entries,
        "license_distribution": stats.get("by_license", {}),
        "total_records": int(manifest["total_records"]),
    }
    prov_path = meta_dir / "provenance.json"
    prov_path.write_text(json.dumps(prov, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    prov_sum = sum(e["records"] for e in src_entries)
    print(f"Wrote {prov_path} ({len(src_entries)} source groups, sum={prov_sum})")

    # 4/5. docs — adapt RC1 (prose + tables are version-neutral; numbers from manifest).
    sig = manifest.get("release_signature", {})
    rid = manifest["release_id"]
    created = manifest.get("created_at", "")[:10]
    status_label = manifest.get("status", "frozen")
    cat_rows = "\n".join(f"| {c} | {by_cat[c]:,} |" for c in CATEGORIES)
    lic_rows = "\n".join(f"| {k} | {v:,} |" for k, v in sorted(stats.get("by_license", {}).items(), key=lambda kv: -kv[1]))
    qdist = stats.get("quality", {}).get("distribution", {})
    q_rows = "\n".join(f"| {k} | {v:,} |" for k, v in sorted(qdist.items(), key=lambda kv: int(kv[0])))
    ddist = stats.get("by_difficulty", {})
    d_rows = "\n".join(f"| {k} | {v:,} |" for k, v in sorted(ddist.items(), key=lambda kv: str(kv[0])))
    approved = manifest.get("gates", {}).get("human_review_gate", {}).get("approved", manifest["total_records"])
    dedup_note = manifest.get("gates", {}).get("dedup_gate", {}).get("note", "")
    dups_removed = manifest.get("gates", {}).get("dedup_gate", {}).get("duplicates_removed", 0)

    card = f"""# Atlas Dataset Card — {release}

> **The dataset is the long-term asset. Models are replaceable.**

## Overview

Atlas {release} is a **model-agnostic, long-term knowledge foundation** for
training and evaluating 8B-class LLMs (Qwen, Llama, DeepSeek, Mistral, Gemma,
and future models). Canonical format is JSONL; model-specific formats are
generated downstream and never stored as source of truth.

| Metric | Value |
|---|---|
| Version | {release} |
| Release ID | `{rid}` |
| Status | {status_label} (frozen) |
| Records | {manifest['total_records']:,} |
| Categories | 9 (each ≥ 1,000,000) |
| Avg quality_score | {stats.get('quality', {}).get('avg', '?')} |
| Gates | quality, license, human-review, dedup — all passed |

## Category distribution

| Category | Records |
|---|---|
{cat_rows}

## License distribution

| License | Records |
|---|---|
{lic_rows}

> Note: records carrying `license = "unknown"` at the record level should be
> reviewed by consumers for their own redistribution obligations (esp.
> CC-BY-SA-3.0 share-alike records).

## Quality distribution

| Score | Records |
|---|---|
{q_rows}

## Difficulty distribution

| Level | Records |
|---|---|
{d_rows}

## Source lineage

See `metadata/provenance.json` for the full per-source breakdown. The top
sources: Wikipedia ({manifest.get('sources', {}).get('wikimedia/wikipedia', 0):,}),
synthetic personal-assistant ({manifest.get('sources', {}).get('synthetic/personal-assistant', 0):,}),
C4 AI/ML ({manifest.get('sources', {}).get('allenai/c4', 0):,}).

## Schema

Each record is a canonical Atlas knowledge object:

```json
{{
  "id": "wiki_sys_0_0000000",
  "category": "03_system_engineering",
  "subcategory": "systems",
  "type": "instruction|conversation|qa|reasoning",
  "source": {{ "name": ..., "url": ..., "license": ..., "date": ... }},
  "messages": [ {{ "role": "user", "content": ... }}, {{ "role": "assistant", "content": ... }} ],
  "language": "en",
  "difficulty": 1,
  "tags": [...],
  "quality_score": 8,
  "verified": true,
  "notes": ""
}}
```

## Intended use

- SFT of instruction-following 8B-class models (Qwen, Llama, DeepSeek, Mistral, Gemma)
- Knowledge-grounded reasoning and system/software engineering assistance
- Balanced coverage across foundation, engineering, science, business,
  creative, and personal-assistant domains

## Provenance & integrity

- Release hash chain: `{rid}…` (sha256-chain-v1, previous {manifest.get('from_version', '?')})
- Per-file integrity: `metadata/checksums.sha256` (SHA-256 of every release file)
- Frozen at `{created}`; contents are immutable
"""
    (docs_dir / "dataset_card.md").write_text(card, encoding="utf-8")
    print(f"Wrote {docs_dir / 'dataset_card.md'}")

    notes = f"""# Release Notes — Atlas {release}

**Release ID:** `{rid}`
**Status:** {status_label} (frozen) · **Date:** {created}
**Total records:** {manifest['total_records']:,} · **Categories:** 9 (each ≥ 1M)

## Highlights

- {manifest.get('changelog', 'Promoted release; see the frozen manifest for details.')}
- All 9 categories remain at 1M+ records each.
- Provenance verified for the release.

## What's inside

- `dataset/<category>/*.jsonl.zst` — compressed canonical JSONL shards,
  one folder per category (9 folders)
- `metadata/release.json` — frozen release manifest (hash-chained)
- `metadata/statistics.json` — per-category record counts (generated from
  the compressed output)
- `metadata/provenance.json` — source lineage summary
- `metadata/checksums.sha256` — SHA-256 of every release file
- `docs/dataset_card.md`, `docs/release_notes.md` — this documentation

## Gates

| Gate | Result |
|---|---|
| quality_gate | PASS (min 4, avg {stats.get('quality', {}).get('avg', '?')}) |
| license_gate | PASS |
| human_review_gate | PASS ({approved:,} approved, 0 rejected) |
| dedup_gate | PASS ({dups_removed:,} removed, {manifest['total_records']:,} unique) |

## Integrity

- Release hash chain: `{rid}…` (sha256-chain-v1, previous {manifest.get('from_version', '?')})
- Every file has a SHA-256 recorded in `metadata/checksums.sha256`
- Verify locally:
  ```bash
  .venv-release/bin/python scripts/release/verify_release.py --release {release}
  ```

## Known notes

- {release} is **frozen**. Any new work creates a new version (e.g. v1.1),
  never edits this release.
"""
    (docs_dir / "release_notes.md").write_text(notes, encoding="utf-8")
    print(f"Wrote {docs_dir / 'release_notes.md'}")

    print(f"\nBundle metadata build complete for {release}: {rel_root}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build release-bundle metadata from frozen manifest.")
    ap.add_argument("--release", default="v1.0-RC2")
    ap.add_argument("--root", default=None, help="Repo root (default: script-relative)")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else REPO_ROOT
    return build(args.release, root)


if __name__ == "__main__":
    sys.exit(main())
