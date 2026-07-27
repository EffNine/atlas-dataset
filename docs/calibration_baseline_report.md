# Atlas Calibration Baseline Report (v0.1)

**Baseline version:** v0.1
**Dataset version:** v0.1
**Generated (UTC):** 2026-07-27T11:20:53+00:00
**Framework:** atlas-quality-calibration 0.1.0
**Reviewed records:** 100 (matched: 100, missing candidates: 0)
**Accept threshold:** quality_score >= 7 AND verified
**Frozen artifacts:**
- Machine-readable baseline: `metadata/calibration_baseline_v0.1.json`
- Checksum registry: `metadata/checksums_v0.1.json`
- Source of truth: `metadata/calibration_report.json`

---

## 1. Summary

This document freezes the Atlas quality-calibration baseline at Phase 3C.1 so
that every future re-calibration can be measured against a known, immutable
reference. The baseline was derived **read-only** from the real on-disk
artifacts (100 human reviews + 100 reviewed pilot candidate knowledge objects)
using the canonical calibration framework (`scripts/calibrate_quality.py`),
which recomputes auto-scores from the current heuristic. No knowledge objects,
dataset sizes, or review decisions were modified to produce this baseline.

The frozen verdict is **READY_FOR_CALIBRATED_AUTO_REVIEW**. The auto-scorer
agrees with human review within the configured tolerance, but the agreement is
**structurally skewed** (see Known Weaknesses). The baseline is therefore a
credible *starting* calibration, not a fully validated one, and must be
revisited before any decision to reduce human oversight.

---

## 2. Current Quality-Model Performance

### Score distributions (1..10)

| score | human count | AI (auto) count |
|---|---|---|
| 6 | 16 | 0 |
| 7 | 82 | 100 |
| 8 | 2 | 0 |

- **Human mean:** 6.86   **AI mean:** 7.00   **Mean bias (AI − human):** +0.14
- **Human spread:** 16 records scored 6, 82 scored 7, 2 scored 8 — a compressed
  range with no scores outside 6–8.

### Correlation & agreement

- Pearson r: `null`  (no variance in the AI column — see weakness)
- Spearman rho: `null`
- Exact agreement: 82%
- Within-1 agreement: 100%
- RMSE: 0.424   MAE: 0.18
- Hallucination rate (human-flagged): 0%

### Accept / reject decision (threshold = 7)

| | Human accept (>=7) | Human reject (<7) |
|---|---|---|
| Human accept (>=7) | TP = 84 | FN = 0 |
| Human reject (<7) | FP = 16 | TN = 0 |

- Precision: 0.840   Recall: 1.000   **F1: 0.913**   Accuracy: 0.840

### Approval / rejection rates (by human verdict)

- Approval rate: **0.84** (84 `approve`)
- Rejection rate: **0.16** (16 `needs_revision`; 0 outright `reject`)

### Confidence (per-stratum reliability, 0..1)

- Min category confidence: 0.676 (08_creative_knowledge)
- Min source confidence: 0.422 (c1, c6)
- Strata flagged **MANDATORY_HUMAN_REVIEW**: `c1, c2, c3, c6, f5` (5 sources)
- All 9 categories are `AUTO_ALLOWED` (none fall below the 0.6 floor).

---

## 3. Known Weaknesses

1. **Auto-score has zero variance.**
   Every one of the 100 reviewed pilot objects received an auto-score of exactly
   **7.0**. The heuristic (`scripts/quality_score.py`) collapsed the entire
   pilot set onto its midpoint. Consequences:
   - Pearson/Spearman correlation is undefined (`null`) — we cannot claim the
     auto-score *ranks* records correctly, only that it *centers* near them.
   - "100% within-1 agreement" is an artifact of compression, not evidence of
     fine-grained agreement.
   - The accept/reject F1 (0.913) is inflated: with all auto-scores at 7, the
     auto-side never rejects, so every human-accept is a true positive and the
     16 human-`needs_revision` records become false positives.

2. **Range compression in human scores.**
   Human scores occupy only 6–8. The pilot objects were authored/selected to be
   uniformly high quality, so the calibration cannot characterize behavior at
   the low end of the scale (1–5) where miscalibration would be most damaging.

3. **Thin per-stratum samples for several sources.**
   Sources `c1, c2, c3, c6, f5` each have only 2–3 reviewed records and
   confidence 0.422–0.527 (< 0.6 floor), so they are correctly gated to
   MANDATORY_HUMAN_REVIEW. Their bias estimates (+0.33 to +0.50) are based on
   very few points and are not yet reliable.

4. **Single-reviewer ground truth.**
   All 100 reviews were produced by one reviewer (`AR`) on the same date with a
   uniform note string. There is no inter-reviewer agreement signal, so the
   "human" column itself carries unknown variance.

5. **No held-out / temporal split.**
   Calibration and the pilot were produced in the same session; there is no
   evidence the auto-scorer generalizes to later, differently-distributed
   batches.

---

## 4. Recommended Improvements

| # | Improvement | Why | Trigger |
|---|---|---|---|
| 1 | **Widen the heuristic's output range** in `quality_score.py` (e.g. weight the dimensions so strong records exceed 7 and weak records fall below). | Removes zero-variance collapse; enables real correlation metrics. | Before any decision to reduce human review. |
| 2 | **Re-calibrate** after (1) and confirm Pearson r > 0.6 and a *non-degenerate* within-1 agreement. | Restores the meaning of the agreement metrics. | After heuristic change. |
| 3 | **Inject low-quality contrast cases** (human-scored 1–5) into the review pool. | Calibrates the high-risk low end of the scale. | Next review cycle. |
| 4 | **Add a second reviewer** on a 10–20% overlap sample to estimate inter-reviewer variance. | Quantifies ground-truth noise. | Next review cycle. |
| 5 | **Keep MANDATORY_HUMAN_REVIEW gates** for `c1, c2, c3, c6, f5` until each has >= 10 reviewed records at confidence >= 0.6. | Thin strata must not be auto-promoted. | Until strata mature. |
| 6 | **Adopt `checksums_v0.1.json`** as a pre-commit / CI guard. | Detects accidental edits to frozen inputs. | Immediately. |

---

## 5. Future Comparison Metrics

When a future re-calibration is performed, compare against this baseline using:

| Metric | Baseline v0.1 value | Direction of improvement |
|---|---|---|
| reviewed_record_count | 100 | increase (>= 100 per stratum of interest) |
| ai_score_distribution | {7: 100} | **must vary** (non-degenerate) |
| human_score_distribution | {6:16, 7:82, 8:2} | widen if contrast cases added |
| pearson_r | null | > 0.6 (required for trust) |
| spearman_rho | null | > 0.6 |
| exact_agree | 0.82 | increase |
| within1_agree | 1.0 | meaningful only once AI varies |
| threshold F1 | 0.913 | > 0.85 (with real negatives) |
| mean_bias (AI−human) | +0.14 | -> 0.0 |
| max_abs_category_bias | 0.4 | < 0.3 |
| max_abs_source_bias | 0.5 | < 0.3 |
| min_source_confidence | 0.422 | >= 0.6 |
| n_mandatory_human_review_strata | 5 | decrease (as strata mature) |
| approval_rate | 0.84 | monitor for drift |
| rejection_rate | 0.16 | monitor for drift |

**Drift detection:** `python scripts/freeze_calibration_baseline.py --verify`
recomputes the sha256 of every tracked input and fails if any differs from
`metadata/checksums_v0.1.json`. CI should run this on every change to the
reviewed objects, review file, schemas, or manifests.

---

*This baseline is frozen. Do not hand-edit the JSON artifacts; regenerate only
after a deliberate re-calibration decision recorded in a new ADR.*
