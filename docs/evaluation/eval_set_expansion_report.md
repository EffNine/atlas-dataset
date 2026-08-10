# Evaluation Set Expansion Report — Phase 6.2

> **Phase:** 6.2
> **Status:** COMPLETE
> **Date:** 2026-08-04
> **Objective:** Expand Atlas evaluation sets to meet the Phase 6 benchmark gates
> (minimum N=30, preferred N=100 per family).
> **Constraints honored:** No model training. No training-view modification. No
> QEE engine modification. All new artifacts written under `evaluation/` only.

---

## 1. Summary

| Family | Old size | New size | Gate (min 30) | Gate (pref 100) | Status |
|--------|----------|----------|---------------|-----------------|--------|
| Math | 13 | **100** | ✅ met | ✅ met | PASS |
| Code | 2 | **100** | ✅ met | ✅ met | PASS |

Both families now meet the preferred N=100 target. Sets are disjoint from the
training-view `train.jsonl` splits and include the previous eval records for
continuity.

---

## 2. Source and Method

**Source pool:** `tmp/expert_pilot_6500_records_v0.1.jsonl` (release
`expert-pilot-6500-v0.1`): 3,000 math (`expert-math-002`, augmented-GSM8K) +
500 code (`expert-swe-001`, SWE-bench Verified) records.

**Selection method (deterministic, reproducible):**
1. **Exclude training-view train records** (117 math, 22 code from the existing
   `train.jsonl`) → guarantees train/eval disjointness.
2. **Exclude REJECT-reviewed records** (governance rule) → 1 math record
   excluded on that basis.
3. **Include existing eval records** (13 math, 2 code) for continuity.
4. **Deterministic stratified fill to N=100** using `sha256(seed:record_id)`
   with selection seed `phase6.2-eval-expansion-v1`, stratified by difficulty
   (math) and by category (code).

**Builder:** `scripts/evaluation_engine/build_eval_expansion.py` (re-runnable,
READ-ONLY on all sources).

---

## 3. Math Evaluation Set

### 3.1 Sizes
- Old: 13 records
- New: **100 records** (`evaluation/eval_sets/phase6_expansion_v1/math_eval_v1.jsonl`)

### 3.2 Category / difficulty distribution

| Difficulty | Count |
|-----------|-------|
| 2 | 82 |
| 3 | 16 |
| 4 | 2 |
| **Total** | **100** |

Category: 100/100 mathematics (single-domain family). Difficulty metadata is
preserved per record from the source `difficulty` field.

### 3.3 Provenance
- 100/100 records carry `original_id` (augmented-GSM8K source identifiers).
- Lineage recorded: `curated_release=expert-pilot-6500-v0.1`,
  `ingestion_pipeline=atlas-expert-pilot-6500-v0.1`, `training_view=math-300m`.
- Review verdicts: 13 KEEP (existing eval continuity), 87 unreviewed (None).

### 3.4 Verification method
- All 100 records include `verification.status=needs_review` with automated
  evidence `problem_source=augmented_gsm8k; expected_answer_present=True`
  (`extraction.has_expected_answer=True`, `expected_answer_head` present).
- **Caveat:** verification is automated (expected-answer presence), not human
  review. Each record carries its full solution text for reference.

---

## 4. Code Evaluation Set

### 4.1 Sizes
- Old: 2 records
- New: **100 records** (`evaluation/eval_sets/phase6_expansion_v1/code_eval_v1.jsonl`)

### 4.2 Category distribution (5 requested categories)

| Category | Count |
|----------|-------|
| Bug fixing | 48 |
| Debugging | 20 |
| Code review | 15 |
| Algorithm reasoning | 10 |
| Refactoring | 7 |
| **Total** | **100** |

Difficulty mix: 2 → 37, 3 → 51, 4 → 10, 5 → 2.

### 4.3 Provenance
- 100/100 records carry `original_id` (SWE-bench `repo__repo-PR` identifiers,
  e.g. `django__django-11138`).
- Source: SWE-bench Verified (MIT), recorded per record with name + URL.
- Review verdicts: 2 KEEP (existing eval continuity), 98 unreviewed (None).

### 4.4 Verification method
- All 100 records are `verification.status=verified` via **gold patch**
  (`method=gold_patch`, evidence `FAIL_TO_PASS=…, PASS_TO_PASS=…`).
- Each record carries `has_problem/has_patch/has_test_patch=True` and
  `fail_to_pass_count` / `pass_to_pass_count` from `extraction`.

### 4.5 Category-label caveat (transparency)
The five code categories are **derived labels** from a documented keyword
classifier over `problem`+`context` text (see builder), because the SWE-bench
source does not natively tag these categories. Spot-checking shows labels are
mostly sensible but not perfect (e.g., an `IndexError` bug can be classified as
"code review"). Labels are intended for **sampling balance**, not ground-truth
taxonomy. A category-balanced sub-selection should be used when reporting
per-category metrics.

---

## 5. Manifests (checksum, version, split)

Written to `evaluation/eval_sets/phase6_expansion_v1/`:

| File | Version | Records SHA-256 |
|------|---------|-----------------|
| `math_eval_v1_manifest.json` | v1 | `3591b31ffdf73f9b994abaaee631f76b9188939330356a0e3c37ccfe1b92758a` |
| `code_eval_v1_manifest.json` | v1 | `8ff09120446b5c87f94b2acde6aefb29255015be0bb8c3d23c05e900457c4c67` |

Each manifest records:
- `eval_set_id`, `version`, `n_records`, `old_size`
- `split`: method (`deterministic_sha256`), selection seed, train seed,
  `train_disjoint=true`, train IDs excluded, existing eval included
- `category_balance` (by difficulty + by category)
- `provenance` (original_id presence, release)
- `verification` (status distribution)
- `checksum.records` (SHA-256 over canonical sorted JSON)

Also `build_summary.json` records the per-family build tallies.

---

## 6. Artifacts

| Artifact | Path |
|----------|------|
| Math eval JSONL | `evaluation/eval_sets/phase6_expansion_v1/math_eval_v1.jsonl` |
| Math manifest | `evaluation/eval_sets/phase6_expansion_v1/math_eval_v1_manifest.json` |
| Code eval JSONL | `evaluation/eval_sets/phase6_expansion_v1/code_eval_v1.jsonl` |
| Code manifest | `evaluation/eval_sets/phase6_expansion_v1/code_eval_v1_manifest.json` |
| Build summary | `evaluation/eval_sets/phase6_expansion_v1/build_summary.json` |
| Builder (reproducible) | `scripts/evaluation_engine/build_eval_expansion.py` |

---

## 7. Recommendation: Phase 6.3 Evaluation Gate

**Recommendation: GATE CONDITIONALLY PASSED — with a verification caveat.**

**Passed:**
- Math eval set: **100 records** (≥ 30 min, = 100 preferred) ✅
- Code eval set: **100 records**, all 5 requested categories represented ✅
- Both sets: deterministic, reproducible, train-disjoint, full provenance,
  complete automated verification evidence, versioned manifests with checksums ✅

**Conditions before treating the gate as fully closed:**
1. **Math verification is `needs_review` (automated only).** The math set relies
   on `expected_answer_present` evidence; a human review sample should confirm
   reference-answer quality before the gate is used to score model capability.
2. **Code categories are heuristic labels.** Report per-category metrics against
   the category-balanced subset and treat labels as sampling strata, not ground
   truth.
3. **QEE v2 correctness metric still needs calibration** (known +2.14 bias vs
   human review, and Phase 5A.4 showed format-vs-reasoning sensitivity). The
   expanded sets are necessary but not sufficient for trustworthy model-gating;
   run them through QEE v2 and compare against human review before using scores
   for training decisions.

**Bottom line:** the *evaluation set* gate (size, balance, provenance,
verification, manifests) is met. The *evaluation pipeline* gate remains open
pending QEE v2 calibration on the expanded sets.
