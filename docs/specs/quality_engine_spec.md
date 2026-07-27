# Quality Engine Specification

This document freezes the Atlas Quality Engine contract for Atlas v1.0.

#

# 1. Purpose

The Quality Engine provides deterministic automated scoring, calibration metadata, and human review contracts. Its outputs are used for promotion gates, bias auditing, and explainability.

#

# 2. Automated Scoring Contract

- Output: integer `quality_score` in range 0-10 inclusive.
- Computed from weighted dimensions unless explicitly configured otherwise.
- Dimensions: Accuracy, Completeness, Technical correctness, Clarity, Usefulness, Originality, Relevance.
- Automated score is a triage signal, not a final human-replacement approval.
- Scale remains stable across versions; changes require recalibration and release metadata note.

#

# 3. Human Review Contract

Human review artifacts must validate against `schemas/quality_review_schema.json` and include:
- `record_id`
- `category`
- `source_id`
- `reviewer`
- `review_date`
- `human_score`
- `dimension_scores`
- `verdict`
- `hallucination`
- `confidence`
- `notes`

#

# 4. Dimension Scores

Human review supports 1-10 integer scores for each dimension, aligned with automated scorer weights. Calibration compares automated versus human scores by category, source, and reviewer.

#

# 5. Confidence Reports

Confidence weights are used in calibration calculations to emphasize higher-confidence human judgments.

#

# 6. Explainable Outputs

Quality explanations can be derived from dimension scores, review notes, hallucination flags, and calibration reports. Release metadata must include enough information to reconstruct recommend thresholds.

#

# 7. Review Agreement

Multiple reviewers on the same record may produce agreement metrics, recorded as metadata or calibration report values. Agreement metadata is additive and optional unless a review policy demands it.

#

# 8. Future Extensibility

- Additional dimensions are allowed as additive schema updates.
- Additional aggregation views over quality signals are allowed via metadata and reporting tools.
- Changes to automated scoring scale or weights require new calibration baseline and release note.

#

# 9. Related Documents

- Main spec Sections 6 and 17.
- `schemas/dataset_schema.json` and `schemas/quality_review_schema.json`.
- Quality calibration docs: `docs/quality_calibration.md`, `docs/calibration_baseline_report.md`.
