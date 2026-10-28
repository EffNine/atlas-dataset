# Release Notes — Atlas v1.0

**Release ID:** `4dcfd43e9da2d756`
**Status:** final (frozen) · **Date:** 2026-08-01
**Total records:** 9,515,938 · **Categories:** 9 (each ≥ 1M)

## Highlights

- v1.0: 9,515,938 records — promoted from v1.0-RC2 (frozen release candidate) to final release. Dataset bytes identical to RC2; all gates re-affirmed. Chain continues from RC2's stored chain_hash.
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
| quality_gate | PASS (min 4, avg 7.94) |
| license_gate | PASS |
| human_review_gate | PASS (9,515,938 approved, 0 rejected) |
| dedup_gate | PASS (377,906 removed, 9,515,938 unique) |

## Integrity

- Release hash chain: `4dcfd43e9da2d756…` (sha256-chain-v1, previous v1.0-RC2)
- Every file has a SHA-256 recorded in `metadata/checksums.sha256`
- Verify locally:
  ```bash
  .venv-release/bin/python scripts/release/verify_release.py --release v1.0
  ```

## Known notes

- v1.0 is **frozen**. Any new work creates a new version (e.g. v1.1),
  never edits this release.
