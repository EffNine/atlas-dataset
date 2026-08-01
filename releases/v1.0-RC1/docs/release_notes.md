# Release Notes — Atlas v1.0-RC1

**Release ID:** `e66408aa594d9438`
**Status:** release_candidate (frozen) · **Date:** 2026-07-30
**Total records:** 9,893,844 · **Categories:** 9 (each ≥ 1M)

## Highlights

- **Milestone release**: all 9 categories at 1M+ records each — the first
  Atlas release that covers every category at production scale.
- **Major expansion from v0.3 (212,328 → 9,893,844 records)** driven by:
  - Wikipedia keyword extraction (science, software, business, creative,
    hardware, system engineering shards)
  - C4 AI/ML streaming subset
  - Synthetic personal-assistant corpus (09_personal_assistant)
- **Intelligence Layer v1.1 complete**: difficulty classification (5-level
  taxonomy) applied across the corpus.
- **Production difficulty classification complete** for the full population.
- **Provenance verified** for the release.

## What's inside

- `dataset/<category>/*.jsonl.zst` — compressed canonical JSONL shards,
  one folder per category (9 folders)
- `metadata/release.json` — frozen release manifest (hash-chained)
- `metadata/statistics.json` — per-category record counts (generated from
  the compressed output)
- `metadata/provenance.json` — source lineage summary
- `metadata/checksums.sha256` — SHA-256 of every release file
- `metadata/compression_report.json` — compression report (sizes, ratios,
  per-file hashes)
- `docs/dataset_card.md`, `docs/release_notes.md` — this documentation

## Gates

| Gate | Result |
|---|---|
| quality_gate | PASS (min 4, avg 7.94) |
| license_gate | PASS |
| human_review_gate | PASS (9,893,844 approved, 0 rejected) |
| dedup_gate | PASS |

## Integrity

- Release hash chain: `e66408aa594d9438…` (sha256-chain-v1)
- Every file has a SHA-256 recorded in `metadata/checksums.sha256`
- Verify locally:
  ```bash
  .venv-release/bin/python scripts/release/verify_release.py --release v1.0-RC1
  ```

## Known notes

- 1,543,548 records carry `difficulty = "?"` (unassigned) — these align with
  the 1.54M `license = "unknown"` records; both are flagged for downstream
  consumers.
- v1.0-RC1 is a **release candidate**. Promotion to v1.0 final and any
  upload to Hugging Face Hub requires explicit human instruction.
