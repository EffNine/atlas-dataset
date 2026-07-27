# Quality Calibration Framework

**Status:** Implemented (v0.1.0) · **Phase:** pre-bulk-ingestion gate
**Owner:** Atlas Lead · **Blocking gate:** "Begin bulk ingestion" (see roadmap)

## 1. Purpose

Before any bulk ingestion into `curated/`, we must know how much to trust the
automated quality scorer (`scripts/quality_score.py`). This framework measures
the agreement between the **automated scorer** and **structured human review**,
quantifies **bias by category and by source**, computes a **confidence score**
for the auto-scorer in each stratum, and emits **adjustment recommendations**
plus a single **readiness verdict** for the bulk-ingestion decision gate.

It answers four operational questions:

1. **Accuracy** — How close is `quality_score.py` to human judgment (MAE/RMSE,
   agreement, correlation, and accept/reject decision quality)?
2. **Bias** — Does the scorer systematically over- or under-rate any category
   or upstream source?
3. **Confidence** — In which strata is the auto-score reliable enough to triage
   on its own, and where is human review mandatory?
4. **Adjustments** — What should change before bulk ingestion: additive
   corrections, mandatory human review, or weight re-tuning?

## 2. Design Constraints

- **No dataset growth.** This phase must not change the size of `raw/` or
  `curated/`. Calibration consumes the existing 100 pilot candidates
  (`curated/v0.1/pilot_candidates.jsonl`) and produces *review artifacts* only
  (a worksheet + a reviews file keyed by existing `record_id`). Nothing is
  written back into the dataset.
- **Stdlib-only, deterministic, no network** — same guarantees as the rest of
  the pipeline (see `scripts/atlas.py` self-test invariants).
- **Single source of auto-scores.** Calibration imports `quality_score.py` and
  *recomputes* auto-scores live, so it always reflects the current heuristic
  rather than a stale stored field.
- **Read-only on data.** The generator and the calibrator never mutate dataset
  records.

## 3. Components

| File | Role |
|---|---|
| `schemas/quality_review_schema.json` | JSON Schema for one structured human review. |
| `scripts/gen_calibration_sample.py` | Deterministic stratified sampler → review worksheet (read-only on candidates). Also emits an **illustrative** example seed (synthetic, must be deleted before real runs). |
| `scripts/calibrate_quality.py` | Core: joins auto-scores with human reviews, computes accuracy / bias / confidence / recommendations, writes `metadata/calibration_report.json` + `docs/quality_calibration_report.md`. |
| `review_queue/calibration_sample.jsonl` | Worksheet: which records to review + auto dimension context. |
| `review_queue/quality_reviews.jsonl` | **Filled by a human** from the worksheet (schema above). This is the calibration input. |
| `review_queue/quality_reviews.example.jsonl` | Synthetic illustrative seed — NOT real review. Demonstrates the harness end-to-end. |
| `metadata/calibration_report.json` | Machine-readable calibration output. |
| `docs/quality_calibration_report.md` | Human digest of the latest run. |
| `tests/verify_calibration.py` | Assertion-based verification of the framework. |

## 4. Human Review Schema

Each review line (keyed by `record_id`):

```json
{
  "record_id": "02_software_engineering_debugging_0010",
  "category": "02_software_engineering",
  "source_id": "s1",
  "reviewer": "AR",
  "review_date": "2026-07-27",
  "human_score": 8,
  "dimension_scores": {
    "accuracy": 8, "completeness": 8, "technical_correctness": 9,
    "clarity": 8, "usefulness": 8, "originality": 7, "relevance": 8
  },
  "verdict": "accept",
  "hallucination": false,
  "confidence": 5,
  "notes": "Clean, correct debugging answer."
}
```

`human_score` and the seven `dimension_scores` use the **same 1–10 scale** as
`quality_score.py`, so agreement is directly comparable. `verdict` uses the
`verdict` uses the v0.1 gate (`approve` / `needs_revision` / `reject` — see
`schemas/quality_review_schema.json`). `confidence` (1–5) weights the human's
reliability; `hallucination` feeds the hallucination-rate metric.

## 5. Metrics

### 5.1 Accuracy (global)
- **MAE / RMSE** of `auto − human`.
- **Exact agreement** and **within-1 agreement** (target ≥ 0.80).
- **Pearson r** and **Spearman rho** (rank correlation; `None` when auto-scores
  have no variance — a signal the scorer isn't discriminating).
- **Accept/Reject decision confusion matrix** at the `quality_score >= 7` gate
  → precision / recall / **F1** (target ≥ 0.85). This is the metric that
  actually matters for the ingestion gate.
- **Hallucination rate** (fraction of human-flagged records).

### 5.2 Bias by stratum (category, source)
For each stratum: mean bias (`auto − human`), MAE, within-1, decision F1, and a
`recommended_correction = −mean_bias` (additive offset that would align the
auto-score to the human centroid for that stratum).

### 5.3 Bias by dimension
Per quality dimension: auto vs human means, bias, MAE, and Pearson r. Flags
dimensions where the heuristic disagrees systematically or has near-zero
correlation (candidate for weight re-tuning).

### 5.4 Confidence score
`confidence(stratum) = (1 − MAE/9) × sqrt(min(n, 10) / 10)`.

Combines **error magnitude** (low MAE → high confidence) with **sample size**
(thin strata are not over-trusted). Range 0–1.

### 5.5 Readiness verdict
| Condition | Verdict | Meaning |
|---|---|---|
| `n < 5` | `INSUFFICIENT_DATA` | Gather more reviews. |
| within-1 ≥ 0.80 **and** F1 ≥ 0.85 | `READY_FOR_CALIBRATED_AUTO_REVIEW` | Bulk ingestion OK with stratum corrections + spot-checks. |
| within-1 ≥ 0.60 **and** F1 ≥ 0.70 | `REQUIRES_HUMAN_REVIEW` | Auto-score triages only; every promotion needs a human. No bulk on auto alone. |
| otherwise | `NOT_READY` | Re-tune the scorer; do not ingest. |

### 5.6 Recommendations
Per stratum: `AUTO_ALLOWED` / `MONITOR` / `MANDATORY_HUMAN_REVIEW` /
`APPLY_ADDITIVE_CORRECTION` / `RETUNE_WEIGHT`. A stratum is `MANDATORY_HUMAN_REVIEW`
when confidence < 0.60, `|bias| ≥ 1.0`, or decision F1 < 0.70.

## 6. Workflow

```
1) python scripts/gen_calibration_sample.py \
       --candidates curated/v0.1/pilot_candidates.jsonl
   -> review_queue/calibration_sample.jsonl   (worksheet, read-only on data)

2) Human reviewer copies worksheet rows into review_queue/quality_reviews.jsonl
   and fills human_score / dimension_scores / verdict / hallucination /
   confidence / reviewer.  (Delete the *.example.jsonl synthetic seed first.)

3) python scripts/calibrate_quality.py \
       --reviews review_queue/quality_reviews.jsonl \
       --candidates curated/v0.1/pilot_candidates.jsonl \
       --report-out metadata/calibration_report.json \
       --md-out docs/quality_calibration_report.md

4) Inspect readiness verdict + recommendations. Do NOT begin bulk ingestion
   unless verdict is READY_FOR_CALIBRATED_AUTO_REVIEW (or a human owner
   explicitly accepts REQUIRES_HUMAN_REVIEW with a full review plan).

5) Re-run after any change to quality_score.py weights, or after each new
   ingestion batch, to keep calibration current.
```

## 7. Current State (illustrative run)

The checked-in `metadata/calibration_report.json` was produced from the
**synthetic example seed** (`quality_reviews.example.jsonl`), NOT real human
review. It demonstrates the harness and shows the likely shape of results:
on the pilot set the auto-scorer rates almost every record ≈7 (low variance →
`pearson_r = None`), and several categories/sources trip `MANDATORY_HUMAN_REVIEW`
due to thin samples. **Replace with real human reviews before using the verdict.**

## 8. Relationship to other gates

- The calibration verdict informs the roadmap's **"Begin bulk ingestion"** gate.
- `review_queue/` already holds `pending.jsonl` per ADR-007; `quality_reviews.jsonl`
  is a *calibration* artifact and is distinct from the promotion queue.
- Calibration only *measures*; it never promotes or ingests. Promotion stays a
  human action (ADR-006 / ADR-007).
