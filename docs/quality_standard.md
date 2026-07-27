# Quality Standard

Quality is the differentiator of Atlas. We prioritize **quality over quantity**.

## 1. Scoring Model

Each record receives an integer `quality_score` from **1–10**, computed as a
weighted sum of seven dimensions (see `scripts/quality_score.py`). Weights are
tunable in the script header.

| Dimension | Weight | What it measures |
|---|---|---|
| Accuracy | 0.20 | factual correctness of the assistant answer |
| Completeness | 0.15 | covers the question fully, no missing steps |
| Technical correctness | 0.20 | domain/code/math is right |
| Clarity | 0.15 | unambiguous, well-structured writing |
| Usefulness | 0.15 | genuinely helps a real user/task |
| Originality | 0.05 | not a generic/boilerplate response |
| Relevance | 0.10 | on-topic for its category/subcategory |

Score mapping:

- **9–10** — exemplary; candidate for flagship examples.
- **7–8** — solid; accepted into `curated/` after verification.
- **4–6** — borderline; revise or reject.
- **1–3** — reject.

**Acceptance threshold for curated/: `quality_score >= 7` AND `verified == true`.**

## 2. Automatic Checks (hard fails)

`validate_dataset.py` rejects any record that:

- Violates `schemas/dataset_schema.json`.
- Has empty user or assistant content.
- References an unknown category/subcategory.
- Has `license == "unknown"` at curated stage.
- Is an exact (or normalized) duplicate of another record.
- Exceeds max token/content limits.

## 3. Manual Review Dimensions

A human reviewer confirms:

- No hallucination.
- No subtle technical error the scorer missed.
- Tone/format appropriate for an instruction dataset.
- License/compliance correct.

## 4. Rejection Criteria (explicit)

- Hallucinated answers.
- Duplicate content (exact or near).
- Low-effort responses.
- Outdated information presented as current.
- Incorrect technical information.
- PII / unlicensed text.

## 5. Continuous Improvement

- Re-score periodically as scoring heuristics improve.
- Track score distribution per version in the release manifest.
- Downgrade + re-review any record flagged post-release.
