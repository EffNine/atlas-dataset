# Reviewer Guidance — Atlas v0.2 Reviewer Calibration Round

**Phase:** 4B.4 — Reviewer Calibration Round  
**Dataset cohort:** Phase 4B expansion (`curated/v0.2/data/phase4b_expansion.jsonl`)  
**Sample file:** `review/calibration/v0.2/calibration_samples.jsonl`  
**Goal:** produce consistent human judgments **before** full v0.2 human review starts.

## What Calibration Is

Calibration means reviewers compare their judgments on a shared worksheet so the team can:

- detect inconsistent scoring patterns,
- clarify ambiguous checklist items,
- agree on edge-case handling,
- reduce reviewer drift before production review begins.

Calibration outputs are **reviewer consistency artifacts**, not Atlas release approvals.

## Calibration Scope

- Use only the 20 samples in `calibration_samples.jsonl`.
- Do not modify dataset files, review queues, or release metadata.
- Do not promote, approve, or reject Atlas v0.2 records during calibration.
- Record disagreements as calibration findings, not dataset edits.

## Review Object

Each sample represents a knowledge object with:

- user prompt in `messages`
- assistant response in `messages`
- canonical answer in `canonical_answer`
- automated quality context in `quality_score` and `evaluation`
- source provenance in `source_attribution`
- lineage in `lineage`

## Review Decision Values

Use these labels for calibration:

- `approve` — fits Atlas v0.2 standards for training-use.
- `needs_revision` — useful core content, but rewrite/clarification recommended.
- `reject` — unsuitable for Atlas v0.2 due to accuracy, completeness, clarity, licensing, or provenance concerns.
- `ambiguous` — calibration only; insufficient context or high disagreement expected.

## Required Review Template (One Review Per Sample)

Use this record shape for each reviewed sample:

```json
{
  "record_id": "f1_01_foundation_instruction_following_0001",
  "sample_id": "cal_v0.2_01",
  "reviewer_id": "REVIEWER_INITIALS",
  "review_date": "YYYY-MM-DD",
  "reviewer_decision": "approve",
  "reason": "One-line rationale for the chosen decision.",
  "confidence": 5,
  "comments": "Free text: issues, assumptions, edge-case observations, or risk notes."
}
```

Fields:

- `record_id` — exact object id from the sample file.
- `sample_id` — calibration sample id, `cal_v0.2_01` through `cal_v0.2_20`.
- `reviewer_id` — anonymous reviewer code; do not write real identities in shared artifacts unless explicitly allowed.
- `review_date` — ISO date.
- `reviewer_decision` — one of the four allowed values above.
- `reason` — short, specific, evidence-based rationale.
- `confidence` — integer from `1` (guess) to `5` (very confident).
- `comments` — optional but strongly recommended for disagreement-prone samples.

## Multi-Reviewer Aggregation

If multiple reviewers evaluate the same sample:

1. Keep each reviewer submission as a separate review record keyed by `(reviewer_id, sample_id)`.
2. In the final calibration report, track:
   - agreement count,
   - direction of disagreements,
   - whether disagreements cluster by category, source, or difficulty.
3. Resolve only the calibration guidance, not production release decisions.

## Reviewer Consistency Rules

- Review the **response quality**, not just answer correctness.
- A response can be technically correct yet poor training data if it is too fragmentary or ambiguous for consistent model behavior.
- Do not infer missing context that is not in the record.
- Pay attention to:
  - clarity for training,
  - factual correctness,
  - completeness,
  - licensing/provenance clarity,
  - duplication clarity if the source is generic.

## Edge Cases

If a sample falls into one of these states, record it explicitly in `comments`:

- overly generic answer with training risk,
- provenance ambiguity,
- potential factual correctness issue,
- style mismatch with other Atlas examples,
- terse answer where ambiguity may arise during fine-tuning.

Use `needs_investigation` in `comments` when the item should be flagged for deeper review, not for immediate release.

## Calibration Outputs

Return:

- Completed review worksheet JSONL/WORKBOOK for all 20 samples.
- Reviewer summary table with decision counts and average confidence.
- Disagreement log with sampledirection of mismatch.

All outputs belong under `review/calibration/v0.2/`.

## Notes

- Calibration should be completed before Atlas v0.2 human review execution begins.
- v0.2 release remains blocked until calibration is reviewed, guidance is updated, and release is explicitly authorized.
- If constraints or checklist wording creates repeated disagreement, record that in the calibration report so guidance can be improved.
