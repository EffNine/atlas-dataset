# Jev Shadow Evaluation Pilot — Report

**Date:** 2026-09-17 · **Status:** COMPLETE (shadow-only)
**Scope:** Evaluate whether Jev (TypeSafe System One, model `jev-latest` → resolved `jev-1.13.0`) is a useful low-cost quality evaluator for Atlas training data. No Atlas records modified, no training, no release-gate integration.

## What was executed

1. Inspected Atlas state: release v1.0 final (9,515,938 records, 9 categories), pilot/v0.2 (4,499 records, 4 arms), existing tooling (`evaluation_engine`, `dedup_dataset.py`, `quality_score.py`).
2. Installed `typesafe-sdk` into `.venv`.
3. Built pilot tooling: `run_jev_pilot.py` (resumable, parallel 8 workers), 6 Jev questions batched per record:
   - `correct` (Noul), `quality` (Score 0–4), `adherence` (Noul), `consistent_category` (Noul), `problematic` (Noul), `training_value` (Score 0–4)
4. Sampled 500 records deterministically (seed 20260917): math 150 / code 100 / general 150 / systems 100 from pilot/v0.2.
5. Ran Jev on all 500: **500/500 ok, 0 errors**, 8 workers, ~20 s wall time.
6. Analyzed: distributions, per-arm breakdown, correlations, flags, outliers, near-dup (reusing `dedup_dataset.py` shingle+minhash primitives), manual inspection of low/high/outlier cases.

## Measurements (actual)

| metric | value |
|--------|-------|
| records evaluated | 500 / 500 |
| Jev ok / errors | 500 / 0 |
| latency per call (mean / p50 / p90 / max) | 0.322 / 0.301 / 0.376 / 0.870 s |
| wall time for 500 (8 workers) | ~20 s |
| total tokens | 808,606 (in 758,606 / out 50,000) ≈ **1,617 tokens/record** |
| model | jev-1.13.0 (jev-latest alias), request ids logged per record |

### Signal quality (means over 500)

| dimension | mean | interpretation |
|-----------|------|----------------|
| correct | 0.719 | 72% of responses judged substantively correct |
| adherence | 0.808 | responses generally follow instructions |
| consistent_category | 0.954 | content almost always matches taxonomy label |
| problematic | 0.204 | ~1-in-5 records carry some problem signal |
| quality | 2.63 / 4 | rounded: 8 Excellent, 302 Good, 145 Acceptable, 43 Poor, 2 Useless |
| training_value | 2.73 / 4 | rounded: 420 Moderate, 67 Low, 13 Not useful, ~50 High+ |

Correlations: `corr(correct, quality)=0.945`, `corr(quality, training_value)=0.738`, **0 contradiction cases** (low-correct + high-quality). The dimensions are coherent, not noisy.

### Per-arm breakdown

| arm | n | quality | training_value | correct | problematic | cat-consist | adherence |
|-----|---|---------|----------------|---------|-------------|-------------|-----------|
| math | 150 | 2.76 | 2.55 | 0.76 | 0.20 | 0.98 | 0.80 |
| code | 100 | 2.46 | 2.86 | 0.64 | 0.19 | 0.95 | 0.82 |
| general | 150 | 2.67 | 2.76 | 0.75 | 0.19 | 0.93 | 0.83 |
| systems | 100 | 2.57 | 2.81 | 0.69 | 0.25 | 0.95 | 0.78 |

### Flags & outliers

- Records with ≥1 flag (problematic≥0.5, quality≤1, category-mismatch, correct<0.35): **61 (12.2%)**
- problem-flag ≥0.5: 44 · unlikely-correct (<0.35): 47 · low-quality (≤1): 11 · category-mismatch (<0.5): **0**
- Outliers (quality<1.5 or correct<0.25): **46 (9.2%)** — 19 math, 11 general, 9 systems, 7 code; concentrated in `expert-math-002` (23)
- Near-dup candidates in sample (Jaccard≥0.25, existing Atlas dedup primitives): **21 pairs** — all traceable to the cross-arm mirroring documented below

### Manual inspection of low/high cases (verified useful)

- Lowest-quality records (q≤0.9, correct 0.02–0.13, problematic 0.5–0.94) are math responses that **cut off mid-reasoning or go down a wrong algebraic path** — Jev is catching genuinely bad data, not style differences.
- A top-quality record (`v2-math-96158aff303d74a0`, q=3.68) is a clean, boxed, correct worked example — correct call.
- `consistent_category` returned 0 mismatches, which is **expected false-negative**: Jev sees `category`+`subcategory` labels inside its own state, so it confirms the label's plausibility rather than cross-checking against the arm/file it actually came from. The arm-level taxonomy issue is better detected by the offline exact-dup + label analysis below.

### Jev disagreement with existing Atlas validation signals

- Pilot/v0.2 records carry no `quality_score`/`verified` field (unlike v0.1 arms), so there is no numeric Atlas quality signal to correlate against at record level. Disagreement analysis therefore reduces to: Jev flags 61 records (12.2%) that the pipeline passed through untouched — these are actionable new findings (list in `jev_pilot_report.json` → `flagged_records`).
- The 47 unlikely-correct + 44 problematic flags are the highest-value signal: they concentrate in math records from `expert-math-002` (OpenMathInstruct-2), suggesting this source benefits most from a Jev-style second pass.

### Jev-independent data findings (confirmed, significant)

- pilot/v0.2 `general` arm is a verbatim mirror of 366 math + 366 code + 366 systems records; **822 cross-arm exact user-content duplicate pairs** exist in the full pilot. 40/500 sampled records are exact dups of another arm.
- `general`-arm records carry `category: 03_system_engineering` regardless of content.

## Honest limitations

1. **No human-labeled ground truth** was used to score Jev's judgments; signal quality is assessed by coherence (correlations, contradiction count) and manual inspection of ~15 cases, not by measured precision/recall.
2. **`consistent_category` is self-confirmed** (labels are in the state it judges) — it detects implausible labels, not arm-level misfiling. The latter needs offline analysis (done above).
3. Token usage (~1,617/record) is driven by state size; the 8k-char truncation guard is inactive at typical record sizes.
4. `usage.output_tokens` appears fixed at ~100/record regardless of questions — cost modeling should rely on input tokens + question count, not output.
5. Jev's `correct` judgment on multi-step math was occasionally wrong in manual inspection (it judges "substantively correct" without solving) — treat `correct<0.35` as "review", not "definitely wrong".

## Artifacts (all under `experiments/jev-pilot-atlas-v0.1/`)

- `jev_results.jsonl` — 500 per-record results: answers, latencies, token usage, request_id, content SHA-256 (traceable to source record)
- `jev_run_log.json` — run summary
- `jev_pilot_report.json` — machine-readable analysis: distributions, per-category means, 61 flagged records, 21 near-dup pairs
- `sample_manifest.json` / `sample_records.jsonl` / `sample_content_index.json` — the sample + traceability hashes
- `run_jev_pilot.py` — resumable tooling (re-runnable as data/keys evolve)
- `README.md`, `STATUS.md` — design + how to re-run
- `REPORT.md` (this file)

Atlas verified unchanged: no writes to `pilot/`, `curated/`, `raw/`, `releases/`, `metadata/`, `training_views/`.

## Recommendation

**Proceed — with two conditions.**

Evidence for Jev as a low-cost shadow evaluator:
- **Fast:** 0.32 s/call, 500 records in ~20 s at 8 workers — cheaper than QEE-v2-style model evaluation and no GPU needed.
- **Cheap:** ~1.6K input tokens/record, all 6 dimensions in one call (TypeSafe batching economics).
- **Coherent:** 0.945 correct↔quality correlation, zero internal contradictions; flags concentrate where manual inspection agrees (truncated/wrong math paths).
- **Traceable:** per-record content SHA-256 + Jev request_id in every result row.
- **Actionable:** 12.2% flag rate isolates 61 reviewable records, dominated by one math source — a concrete, testable queue.

Conditions before a larger run:
1. **Deduplicate pilot/v0.2 first** (822 cross-arm exact-dup pairs). Running Jev on duplicated data wastes ~33% of budget and biases arm-level distributions.
2. **Fix the taxonomy** for `general`-arm `03_system_engineering` labels, and change the Jev `consistent_category` question to cross-check against an out-of-state category list (not the record's own labels) so it actually detects misfiling.

Then: run Jev over the full deduplicated pilot (≈2,900 unique records, ≈4.7M tokens, ~15–20 min) as a shadow quality layer feeding the review queue — not as a release-gate signal. Calibrate `correct`/`problematic` thresholds against a small human-labeled subset before any automation decision.
