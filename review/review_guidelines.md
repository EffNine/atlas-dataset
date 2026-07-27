# Atlas Human Review Guidelines

## Purpose
These guidelines define how each Atlas Knowledge Object should be evaluated during Phase 3C Human Quality Calibration. The goal is to produce consistent, reproducible human judgments that can be compared against the automated quality scorer.

## Scope
- Review all 100 pilot Knowledge Objects in `curated/v0.1/pilot_candidates.jsonl`.
- Do not modify the pilot objects.
- Do not add or remove records from `raw/` or `curated/`.
- All review artifacts belong under `review/`.

## Review Criteria
Score each item on a 1–10 scale, where 10 is excellent and 1 is poor.

1. **Accuracy** — Is the answer factually correct?
2. **Technical Correctness** — Are technical claims sound and precise?
3. **Completeness** — Does the answer cover what a learner needs?
4. **Clarity** — Is the explanation clear and well structured?
5. **Usefulness** — Would this help train a future LLM or assist a user?
6. **Source Reliability** — Is the upstream source trustworthy?
7. **Overall Quality** — Aggregate judgment of the knowledge object.

## Decision
- **approve** — Meets quality expectations.
- **needs_revision** — Useful but incomplete or slightly flawed.
- **reject** — Factually wrong, unsafe, or not useful for training.

## Reviewer Checks
- Verify factual correctness against known references when possible.
- Confirm the category matches the content.
- Confirm the difficulty level is appropriate.
- Flag hallucinations or unsupported claims.
- Consider whether the knowledge would survive future model changes.

## Output Format
Write one JSON object per line in `review/quality_reviews.jsonl` matching `schemas/quality_review_schema.json`.

Required fields:
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

## Notes
- Keep `notes` concise but specific enough to explain borderline scores.
- Multiple reviewers on the same record are supported and improve calibration.
- Synthetic or placeholder review data must not be mixed into real calibration reports.
