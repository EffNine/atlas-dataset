# Phase 2 — Deduplication Report

**Scope:** pilot/v0.2 (4 arms, 4,499 records) · **Method:** deterministic SHA-256 content hashing (exact) + MinHash LSH (near) · **Non-destructive:** no records deleted or rewritten.

## Deduplication classes

| class | meaning | count | action |
|---|---|---|---|
| `exact_duplicate` | identical user **+** assistant content (full-content SHA-256) | **822** groups → 822 drop rows | `drop_duplicate` |
| `exact_duplicate_user_only` | identical user content, **differing** assistant responses | 2 groups → 825 rows | 735 `drop_duplicate` (same source) + 90 `keep_both_review` (cross-source) |
| `near_duplicate` | user-content MinHash Jaccard in [0.8, 1.0), not exact | **6** pairs | `keep_both_review` |
| legitimate repeated examples | same prompt, intentionally distinct answers from different sources | 90 rows | `keep_both_review` — NOT auto-dropped |
| requires human review | any row needing a decision before it can be dropped | **96** | `keep_both_review` |

## Key numbers

- Total records: **4,499**
- Identical-content duplicate groups: **822** (the Phase-1 finding, confirmed exactly)
- Exact full-content duplicate rows: **822** → unique after dropping these: **3,677**
- User-only duplicate rows: **825** (same prompt, differing answers) → dropping the 735 same-source redundant ones yields **2,942**
- **Unique records after exact dedup: 3,677**; after also removing same-source user-only redundancy: **2,942**
- Requires human review: **96**

| count meaning | value |
|---|---|
| unique after exact-content dedup | 3,677 |
| unique after exact + same-source user-only dedup | 2,942 |

## Exact-duplicate distribution by arm pair

The 822 identical-content groups break down as:

| canonical arm → duplicate arm | groups |
|---|---|
| `code` → `general` | 366 |
| `math` → `general` | 366 |
| `general` → `systems` | 90 |

This confirms the Phase-1 finding that the **`general` arm is a verbatim mirror** of 366 math + 366 code records, and **`systems` mirrors 90 of the general arm's linux-kernel records**. The ~33% duplication of the 4,499-record pilot is exactly this cross-arm mirroring.

## Cross-source "user-only" duplicates (legitimate vs redundant)

Of the 825 user-only-duplicate rows:
- **735** are same-source → redundant parallel answers, `drop_duplicate` recommended.
- **90** are cross-source (same prompt, two different source answers) → `keep_both_review`. These are **legitimate repeated examples** (distinct responses to the same question) and must not be auto-dropped.

## Near-duplicate pairs (Jaccard ≥ 0.8)

6 user-content near-duplicate pairs, all `keep_both_review`. These are not exact; each needs a human call on whether they are genuinely distinct examples.

## Provenance preserved

Every manifest row carries: `record_id`, `arm`, `source`, `category_label`, `subcategory_label`, `user_sha256_16`, `asst_sha256_16`, `full_content_sha256`. No original record was modified.

## Machine-readable artifact

`deduplication_manifest.jsonl` — one row per duplicate relationship (1,653 rows: 822 exact + 825 user-only + 6 near). Summary in `deduplication_report.json`.

## Recommendation for the ~2,900-record Jev run

Run Jev on the **3,677 unique records** (drop the 822 exact full-content duplicates). If you also drop the 735 same-source user-only redundant pairs, that yields **2,942** — which is the ~2,900 target. Keep the 96 human-review rows and 6 near-duplicate pairs flagged so they can be evaluated separately. This avoids over-weighting the mirrored ~33% and biasing arm-level distributions.
