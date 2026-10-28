# Phase 2 — Taxonomy Audit Report

**Method:** independent content-based domain inference (weighted domain signals + source priors). The record's own category label is **not** used as ground truth — inference is derived from user+assistant content and the record's source. Comparison is against the independent reference `taxonomy_reference_v1.json` (the 9 canonical Atlas categories from `metadata/categories.json` + the pilot/v0.2 label mappings).

## Findings

- **Records audited:** 4,499
- **Confident high-margin suspects (misclassification, conf≥0.5 & margin≥0.3):** 0
- **Domain mismatches at any confidence:** 61 (1.36%) — all low-confidence screen hits, none rising to a confident suspect
- **Inconclusive (no domain signal):** 0
- **Label matches (or benign math-alias):** 4,438

## Per-label breakdown

| label (pilot/v0.2) | n | confident suspects | predicted distribution |
|---|---|---|---|
| `mathematics` (→01_foundation) | 1,366 | 0 | 01_foundation 1,305 · 02_software 32 · 03_system 13 · 07_business 12 · 06_science 2 · 08_creative 1 · 04_ai 1 |
| `software_engineering` (→02) | 767 | 0 | 02_software 767 |
| `system_engineering` (→03) | 2,000 | 0 | 03_system 2,000 |
| `03_system_engineering` (→03) | 366 | 0 | 03_system 366 |

## Interpretation of the "general-arm" issue

The Phase-1 report flagged that the **`general` arm's 366 records carry `category: 03_system_engineering`** while mirroring math/code/linux-kernel content. The audit confirms this is a real mislabel **at the arm level**, but it is *not* a content-level misclassification:

- The `general` arm's 366 records (label `03_system_engineering`) are **exact duplicates** of `code` (366 SWE) and the linux-kernel records, and their content *does* infer to `03_system_engineering` / `02_software_engineering` — so the label is defensible for the *content*, the mislabel is that these records were filed under a *general* arm with a system-engineering label rather than their source's own arm.
- The 61 low-confidence domain mismatches are math word-problems whose incidental keywords (e.g. "market", "revenue", "copper", "function") triggered a weak non-math-domain inference. These are **false positives of the screen**, not real misclassifications — which is exactly why the suspect threshold requires conf≥0.5 & margin≥0.3.

## Confidence / uncertainty

- **High confidence:** the `general`-arm filing issue is real (confirmed by exact-dup + label cross-reference in the dedup manifest).
- **Low confidence:** the 61 domain-mismatch rows — the keyword screen is a coarse filter and cannot distinguish "math word-problem about money" (correctly 01_foundation) from "business content" (07). Human review required.
- **Inconclusive:** nothing; every record had some domain signal.

## Recommended corrections (proposal only — NO source data modified)

1. **Re-file the `general` arm's 366 mirrored records** under their source arms (`math`/`code`/`systems`) rather than a `general` arm with a `03_system_engineering` label. This is a curation/migration decision for the next pilot version, not an in-place relabel.
2. Keep the 61 domain-mismatch rows as a **human-review queue**; the screen should not auto-relabel.
3. Use `taxonomy_reference_v1.json` (not the record's own label) as the reference for all future Jev category-consistency questions.

## Artifacts

- `taxonomy_audit.json` — summary + per-label breakdown
- `taxonomy_audit_rows.jsonl` — one row per record (4,499) with inferred category, confidence, scores, match/suspect flags
- `taxonomy_reference_v1.json` — independent, versioned, hash-auditable category reference (SHA-256 `a430a07f…`)
