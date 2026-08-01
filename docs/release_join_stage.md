# Atlas Release Join Stage — Documentation

## Purpose

The **join stage** assembles the canonical v1.0-RC1 release records from the
authoritative approved source. It is the first step of the production release
pipeline:

```
review_queue/approved.jsonl  (authoritative, 9,893,844 records)
        │  streaming join
        ▼
raw/generated/ shards ──►  releases/v1.0-RC1/dataset/<category>/  (canonical JSONL)
pilot/curated sources ─┘
        │
        ▼
zstd compression → checksums → verify → Hugging Face upload
```

## Why a join stage exists

The frozen manifest (`metadata/releases/v1.0-RC1_release.json`) declares
9,893,844 records and matches `review_queue/approved.jsonl` **exactly** per
category. But `approved.jsonl` contains:

- **8,350,296 full canonical records** (messages inline) — written as-is
- **1,543,548 review stubs** (no messages; index entries only)

Stub content is resolved from:
- **1,543,298 records** from `raw/generated/*_atlas.jsonl` (join by record ID)
- **250 records** from pilot/curated sources (`curated/v0.1`, `curated/v0.2`,
  `raw/pilot`, `review/v0.2`)

Full investigation: `docs/v1.0-RC1_release_input_investigation.md`.

## Script

`scripts/release/join_release.py` — streaming, O(1) memory per pass.

### Passes

1. **scan_approved** — stream `approved.jsonl`; write full records to category
   outputs; index stub records in memory (`stub_meta` dict, ~1.5M entries).
2. **resolve_from_shards** — stream every `*_atlas.jsonl` shard; for records
   whose ID matches a stub, merge approved review fields into shard content
   and route by the approved category.
3. **resolve_from_pilot** — scan pilot/curated JSONL for remaining stubs.
4. **validate** — total == 9,893,844, per-category counts == manifest,
   no duplicate IDs, no missing stubs.

### Canonical record merge

```
output = shard/pilot content (messages, source, tags, difficulty, ...)
       + approved stub review fields (category, subcategory, quality_score,
         license, verification_status, verification_date, reviewer)
```

The **approved stub's `category`** is authoritative for routing — never the
shard's — so per-category counts stay manifest-exact.

## CLI

```bash
# Canonical JSONL output (spec default)
.venv-release/bin/python scripts/release/join_release.py \
    --approved review_queue/approved.jsonl \
    --shards raw/generated \
    --pattern '*_atlas.jsonl' \
    --output releases/v1.0-RC1/dataset \
    --output-format jsonl

# Disk-safe streaming zstd output (~22GB JSONL vs ~5GB zst)
.venv-release/bin/python scripts/release/join_release.py \
    --approved review_queue/approved.jsonl \
    --shards raw/generated \
    --pattern '*_atlas.jsonl' \
    --output releases/v1.0-RC1/dataset \
    --output-format zst
```

Report: `reports/releases/v1.0-RC1_join_report.json`

## Validation (Phase 3)

| Check | Rule |
|---|---|
| total_records | exactly 9,893,844 |
| categories_match_manifest | per-category counts == manifest `by_category` |
| no_duplicate_ids | every output ID unique |
| no_missing_stubs | all 1,543,548 stubs resolved |
| stubs_resolved | from_shards + from_pilot == stub_records |

Exit code 0 = all checks pass; 1 = any failure.

## Known issue: 377,906 duplicate wiki_sw records (FROZEN SOURCE)

The v1.0-RC1 join run (2026-07-31) reported `no_duplicate_ids: FAIL`
(377,906 duplicates). Investigation:

- **All 377,906 duplicates are in `02_software_engineering`**, ID prefix
  `wiki_sw_1_*`, each appearing **exactly twice with byte-identical content**.
- The remaining 8 categories have **zero** duplicates.
- **Root cause is the frozen source** `review_queue/approved.jsonl`, not the
  join: the approved list itself contains the duplicate IDs (confirmed by
  direct scan: 9,893,844 lines, 9,515,938 unique IDs, 377,906 extra).
- The frozen manifest's `total_records: 9,893,844` and `dedup_gate: passed`
  therefore count the duplicates.

**Decision status: PENDING HUMAN — release must not be uploaded until
resolved.** Options: (a) release as-is, manifest-exact, documenting the
duplicates; (b) dedup to 9,515,938 unique records (changes manifest counts →
requires a new release candidate, violates immutability of v1.0-RC1).

## Disk constraint (IMPORTANT)

Joined JSONL ≈ **22 GB** (measured from real record sizes: full records
2.41 KB avg + stub content ~1.4 GB). On this Mac (8 GB RAM, 16 Gi free on the
Data volume) the full JSONL output **does not fit** alongside the existing
20 GB `approved.jsonl` + 22 GB `raw/generated/`.

**Use `--output-format zst` for the production run** — the join then streams
directly to `*.jsonl.zst` (~5 GB), and the compression stage becomes a
verification-only step. The record content is identical; only the on-disk
encoding differs.

## Tests

```bash
.venv-release/bin/python -m pytest tests/test_join_release.py -v
```

10 tests: streaming counts, category routing, totals, deterministic output
(two runs byte-identical), duplicate detection, zst mode, missing-stub
failure, nested-record pilot input, merge semantics.

## Safety

- Read-only on: `approved.jsonl`, shards, pilot sources, manifest.
- Writes only: `releases/v1.0-RC1/dataset/<category>/*` and the report.
- Does not modify: manifest, curated data, intelligence metadata.
