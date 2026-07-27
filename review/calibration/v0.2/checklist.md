# Reviewer Calibration Checklist — Atlas v0.2

**Phase:** 4B.4 — Reviewer Calibration Round  
**Dataset:** `curated/v0.2/data/phase4b_expansion.jsonl`  
**Sample set:** `review/calibration/v0.2/calibration_samples.jsonl`  
**Purpose:** align reviewer judgment before full human review execution **only**  
**Status:** calibration in progress; v0.2 release remains blocked

## Hard Rules

1. Do **not** promote, approve, or reject Atlas v0.2 production records during calibration.
2. Complete this worksheet, then score consistency across reviewers; do not use sample decisions as release gate data.
3. Do **not** modify dataset files, `review_queue/*.jsonl`, or any curated data during calibration.
4. If you spot a likely high-risk item, record it in `calibration_note`; do not move it into an approval workflow.
5. Release stays blocked until calibration is reviewed and a human owner explicitly lifts the gate.

## Review Fields Required Per Sample

For every record in `calibration_samples.jsonl`, provide:

- `record_id` — source document id (do not change it)
- `sample_id` — calibration sample id from the worksheet
- `reviewer_id` — your reviewer identifier
- `review_date` — ISO date `YYYY-MM-DD`
- `reviewer_decision` — choose `approve` / `needs_revision` / `reject` / `ambiguous` (for calibration **only**)
- `reason` — short reason for the chosen decision
- `confidence` — integer `1..5`
- `comments` — free notes on difficulty, ambiguity, or risk

Use the structured format in `reviewer_guidelines.md`.

## Review Flow

1. Open `calibration_samples.jsonl` and process one record at a time.
2. For each sample, inspect:
   - `messages[].content`
   - `canonical_answer`
   - `category`, `subcategory`, `difficulty`, `knowledge_type`
   - `quality_score` and `evaluation` (`quality_continuous`, `confidence`, `confidence_level`)
   - `source_attribution` and `license`
   - `notes`

3. Record your decision and rationale in the template format described in `reviewer_guidelines.md`.
4. After all samples, complete the self-check section and the reviewer summary table.
5. Return completed worksheet artifacts to `review/calibration/v0.2/`.
6. The calibration report will compare inter-reviewer agreement and update reviewer guidance.

## Reviewer Self-Check

Before finalizing each review session, confirm:

- [ ] Keeped all calibration decisions within the guidance for calibration context; did not convert sample decisions into dataset promotion actions.
- [ ] Completed all 20 sample reviews or documented why a sample was skipped.
- [ ] Flagged edge cases unrelated to release execution (`needs_investigation` is permitted).
- [ ] Did not change or approve any production dataset file or queue.

## Difficulty Guidance

- `difficulty: 0-1` — easier calibration examples; expected broad agreement.
- `difficulty: 2` — moderate examples where wording/tradeoffs matter.
- `difficulty: 3` — edge cases for calibration; expect more variation. Use these to detect reviewer drift.

## Risk Flags To Watch

- Source verification or provenance concerns.
- License text showing verification/open questions.
- Very short answers where clarity or completeness may be underestimated.
- Answers with domain-specific jargon where reviewer expertise varies.
