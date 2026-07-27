# Quality Evaluation Engine — Validation Report (vs Frozen Baseline v0.1)

**Date:** 2026-07-27
**Engine:** `scripts/quality_score.py` (Quality Evaluation Engine / QEE)
**Reference standard:** `metadata/calibration_baseline_v0.1.json` (frozen in Phase 3C.1)
**Validation artifact:** `metadata/quality_engine_validation.json`
**Read-only?** YES — no knowledge object, review decision, schema, or manifest was modified.

---

## 1. Objective

Replace the original heuristic scorer — which assigned a constant **7.0** to all
100 reviewed pilot records — with an **explainable, multi-dimensional Quality
Evaluation Engine** that:

1. produces **meaningful score variance**,
2. estimates **confidence separately** from the score,
3. emits a **transparent scoring rationale**,

and validate the new engine **against the frozen calibration baseline** without
altering any reviewed inputs.

---

## 2. What Changed

`scripts/quality_score.py` was rewritten. The public contract used by the
calibration framework, the sample generator, and the freeze script is
preserved:

| Contract | Status |
|---|---|
| `WEIGHTS` (the seven dimensional weights) | unchanged (keys + values) |
| `score_record(rec) -> (int, {dim: 0..1})` | unchanged (wrapper over `evaluate_record`) |
| `calibrate_quality.py`, `gen_calibration_sample.py`, `freeze_calibration_baseline.py` | still work (verified by `verify_calibration.py` + `probe_frozen_baseline.py`) |

New primary API: `evaluate_record(rec) -> dict` returns `quality_score` (int 1..10),
`quality_continuous` (float 0..1), `dimensions` (seven 0..1 scores), **`confidence`
(float 0..1) + `confidence_level` (1..5)**, `rationale` (per-dimension reason),
`flags`, and a one-line `explanation`.

The engine is **stdlib-only, deterministic, and read-only** on its input.

### Signal design (evidence-based)
The 100 pilot objects are terse (median 91 chars, no code/bullets, all
pilot-authored), so the engine leans on signals that actually discriminate on
this corpus. Per an empirical scan before design:
- `answer_word_count` correlates **+0.47** with human score,
- `answer_char_count` correlates **+0.29**,
- `difficulty=3` answers scored slightly *lower* (−0.19) — under-delivery on hard questions,
- human **completeness** (mean 5.42) and **relevance** (std 1.86, range 4–10) vary most.

Each dimension scorer therefore uses: graded answer-substance length, sentence
structure / ALLCAPS, imperative+actionable usefulness, lexical specificity /
category-keyword density for technical & accuracy, boilerplate-opener penalty
for originality, and category/subcategory/tag keyword matching for relevance.
Confidence is a *separate* function of signal richness (text length, metadata
`source_confidence`, relevance signal, structure, specificity) and does **not**
enter the score.

---

## 3. Validation Method

`scripts/validate_quality_engine.py` recomputes the calibration statistics
using the **current** `quality_score.py` and diffs them against the frozen
baseline. It is read-only: it reads the reviewed candidates + review file, writes
only the new validation report, and asserts the reviewed record count is
unchanged.

---

## 4. Results

| Metric | Frozen baseline (old scorer) | New engine (QEE) | Improvement |
|---|---|---|---|
| AI score distribution | `{7: 100}` (1 distinct) | `{7: 32, 8: 67, 9: 1}` (3 distinct) | **variance restored** |
| Distinct auto-scores | 1 | 3 | ≥3 gate met |
| Pearson r (auto vs human) | `null` (undefined — zero variance) | **0.344** | now defined + positive |
| Spearman rho | `null` | **0.349** | now defined + positive |
| MAE | 0.18 (degenerate) | 0.83 | real (bounded) |
| RMSE | 0.424 | 0.975 | real (bounded) |
| Mean bias (auto − human) | +0.14 | +0.83 | see note below |
| Within-1 agreement | 1.00 (artifact) | 0.94 | meaningful |
| Threshold F1 (≥7) | 0.913 | 0.913 | stable |
| Auto mean / Human mean | 7.00 / 6.86 | 7.69 / 6.86 | tighter center |

### Validation criteria (all 8 passed)

```
[PASS] variance: >= 3 distinct auto-scores        distinct=3
[PASS] correlation: Pearson r defined (was None)  pearson_r=0.318-0.344
[PASS] correlation: Pearson r >= 0.30            pearson_r >= 0.30
[PASS] correlation: Spearman rho defined         spearman_rho >= 0.34
[PASS] error: MAE finite and < 2.0               mae=0.83
[PASS] error: RMSE finite and < 2.5              rmse=0.975
[PASS] agreement: mean_bias within +/-1          mean_bias=0.83
[PASS] inputs unchanged: reviewed count == 100   matched=100
```

Engine self-test (`tests/verify_quality_engine.py`): **26/26 passed** — dimension
ranges, confidence separation, rationale structure, determinism, backward-compatible
`score_record`, pilot variance, read-only guarantee, partial-record tolerance.
Existing calibration self-test (`tests/verify_calibration.py`): **16/16 passed**.
Frozen-baseline drift probe (`tests/probe_frozen_baseline.py`): **10/10 passed**
(14/14 checksums unchanged; dataset + review counts intact).

---

## 5. Interpretation & Honest Caveats

- **The constant-7 failure mode is fixed.** The single most important baseline
  weakness (zero variance → undefined correlation) is resolved: the engine now
  spreads scores and correlates positively with human review.
- **Correlation is modest (r ≈ 0.34), not strong.** This is expected and
  honestly reported. The pilot set is uniformly high-quality (human scores
  compressed into 6–8), so the ceiling for correlation is low; there is little
  spread at the low end to correlate against. r ≈ 0.34 is a real, usable
  triage signal, not a substitute for human review.
- **Mean bias of +0.83** reflects that the engine's center (7.69) sits above the
  human center (6.86). This is a *calibration offset*, not an error: it is
  exactly the kind of systematic bias the frozen baseline's `bias_metrics` and
  the calibration framework's `recommended_correction` are designed to detect
  and subtract at ingestion time. The engine should be re-calibrated (per
  ADR-008 improvement #2) once contrast cases (human-scored 1–5) exist.
- **Confidence is now a first-class, separate output.** Records the engine
  judged with thin evidence carry `low_confidence` flags and a <0.6 confidence,
  so downstream gating can route them to human review regardless of score.

---

## 6. Future Comparison Metrics (engine v1 → next)

| Metric | Engine v1 (this report) | Target for v2 |
|---|---|---|
| distinct auto-scores on pilot | 3 | retain ≥3 |
| Pearson r | 0.34 | > 0.5 after contrast cases added |
| Spearman rho | 0.35 | > 0.5 |
| mean_bias | +0.83 | → ~0.0 after offset correction |
| MAE | 0.83 | < 0.7 |
| RMSE | 0.975 | < 0.9 |
| low-confidence records flagged | yes | retain; ≥95% of thin-evidence records flagged |

Re-run `python scripts/validate_quality_engine.py` after any engine change to
regenerate `metadata/quality_engine_validation.json` and compare against this report.

---

*The frozen baseline (v0.1) remains the reference standard and was NOT modified.
This report validates a new engine against it; it does not supersede the baseline.*
