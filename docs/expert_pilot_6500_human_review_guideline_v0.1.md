# Atlas Expert Pilot Phase 1B — Human Review Guideline & Execution Checklist v0.1

## Purpose

Define how the 324-record human review calibration sample
(`review/expert_pilot_6500_review_sample_v0.1.jsonl`) is reviewed and how
acceptance is computed. This document is **procedure only**:

- it does not perform reviews
- it does not assign labels or verdicts
- it does not assign reviewers to records

The review itself is a separate, later step that consumes this guideline.

## Scope

- Sample: 324 records (SWE-bench Verified 25 · OpenMathInstruct-2 149 ·
  ArXiv 150), drawn deterministically (seed 20260802) from the 6,500-record
  pilot (`tmp/expert_pilot_6500_records_v0.1.jsonl`).
- Every sample line is a review envelope + the full Atlas expert record:
  `review_id`, `record_id`, `source_id`, `stratum`, `review_status`,
  `assigned_reviewer`, `assigned_timestamp`, `completed_timestamp`,
  `calibration` (auto_gate, quality_score, difficulty, expert_tier), `record`.
- Objective: calibrate the automated quality gate against human judgement and
  confirm the pilot GO (plan §6: human review acceptance ≥ 80%).
- Boundaries: no dataset modifications, no release unlock, no auto-generated
  approvals. The review writes decisions to a dedicated decision file only.

## Review Model

Each reviewer evaluates one record at a time on four dimensions (1–5 scale),
then assigns a verdict. The dimensions mirror the automated gate
(`scripts/expert_pipeline/quality.py`) so human and machine scores are
directly comparable.

### Dimension rubric (1–5)

| Score | Correctness | Reasoning depth | Explanation quality | Provenance confidence |
|-------|-------------|-----------------|---------------------|-----------------------|
| 5 | Verifiably correct; evidence available (gold patch / tests / expected answer); no errors found | Multi-step, complete derivation or patch; all branches handled | Clear, structured, self-contained; would help another expert | Source + license + original_id + transformations + verification evidence all present and trustworthy |
| 4 | Correct with strong supporting evidence | Solid multi-step reasoning with minor gaps | Well organized; minor omissions | Complete provenance; small uncertainty (e.g., needs_review status) |
| 3 | Correct overall; evidence partial or generic | Single-step or shallow but correct reasoning | Adequate; some steps implicit | Provenance present but evidence thin |
| 2 | Incorrect or unsupported; evidence missing | Superficial; conclusion without derivation | Confusing or terse | Provenance incomplete or weak |
| 1 | Wrong or empty; contradicts problem | No reasoning | Unusable | Missing or untrustworthy |

### Verdicts

| Verdict | Rule |
|---------|------|
| **KEEP** | correctness ≥ 3 AND provenance_confidence ≥ 3 AND license OK AND no security concern |
| **REVIEW** | otherwise, but not REJECT (e.g., borderline correctness or thin provenance) |
| **REJECT** | correctness ≤ 2, OR provenance_confidence ≤ 1, OR license not permissive (NC/restricted/unknown), OR security/credential material present |

Record-specific checks before scoring:

1. **License**: record `license` and `source.license` must be one of
   MIT / Apache-2.0 / CC-BY-4.0 / arXiv non-exclusive license. Anything
   else (especially NC, unknown, "other") → REJECT.
2. **Duplicate**: compare `provenance.original_id` and normalized
   problem+solution against the other sampled records. Duplicates → flag,
   do not count as two acceptances.
3. **Security**: scan problem/context/solution for private keys, AWS keys,
   OpenAI keys, credential paths. Any hit → REJECT (hard gate).
4. **Provenance completeness**: `source.source_id`, `source.url`,
   `provenance.original_id`, `provenance.transformations` (non-empty),
   `provenance.ingestion_pipeline`, `verification.method` + `evidence`
   must all be present.

## Calibration Procedure

1. Reviewer assigns the four dimension scores and a verdict per record,
   independently of the `calibration.auto_gate` value (auto_gate is for
   comparison after review, not a hint during review).
2. After the cohort is reviewed, compare human verdict vs `auto_gate`:
   - **agreement** = same verdict class (KEEP/REVIEW/REJECT)
   - disagreements are the calibration signal: record them by stratum and
     dimension for the decision report
3. Compute acceptance rate = records with verdict KEEP ÷ total reviewed.
   - ≥ 80% → supports GO (plan §6)
   - 60–80% → HOLD (fix pipeline / adjust plan)
   - < 60% → STOP (reject pilot outcome)
4. Report must include measured numbers only: counts, dimension mean
   scores, agreement rate, per-stratum breakdown, disagreement list.

## Reviewer Identity & Independence

- Reviewer IDs are placeholders unless real identities are supplied.
  Convention: `reviewer_<category_prefix>_<NN>`, e.g. `reviewer_swe_01`.
- **Never fabricate a human identity**; if a machine/automated pass is used
  (not allowed in this calibration), it must be labeled `auto-batch` —
  but this pilot is human review, so only human reviewer IDs are valid.
- One reviewer per record; category-based assignment first, then
  round-robin within the category.
- Reviewers must not modify any dataset file, the sample file, the quality
  report, or the manifest. Output goes only to the decision file.

## Output Artifacts (created during the review step, not now)

| Artifact | Path | Content |
|----------|------|---------|
| Review decisions | `review/expert_pilot_6500_review_decisions_v0.1.jsonl` | one decision per reviewed record (schema below) |
| Review progress summary | `reports/expert_pilot_6500_review_summary_v0.1.json` | measured acceptance, agreement, per-stratum stats |
| Updated decision report | `reports/expert_pilot_6500_decision_v0.1.md` | append human-review section (GO/HOLD/STOP confirmation) |

### Decision line schema

```json
{
  "review_id": "rev_000001",
  "record_id": "expert_swe_000000",
  "reviewer": "reviewer_swe_01",
  "verdict": "KEEP | REVIEW | REJECT",
  "dimensions": {
    "correctness": 4,
    "reasoning_depth": 4,
    "explanation_quality": 4,
    "provenance_confidence": 4
  },
  "notes": "concise, specific rationale (no copy-paste across records)",
  "reviewed_at": "2026-08-02T00:00:00Z",
  "auto_gate_snapshot": "KEEP"
}
```

## Validation Rules for the Decision File

- Exactly one decision per reviewed record; no duplicate `record_id`.
- Decision file must not overlap with prior decision batches (append-only
  semantics if batches are used).
- `reviewer` must be a real reviewer ID or `auto-batch` (never a fabricated
  human name).
- `notes` should be concise and specific to the record — avoid verbatim
  repetition of the same explanation across records in the same family.
- No decision may mutate `review/` sample state, the manifest, or any
  dataset artifact.

## Execution Checklist

Phase 1B review runs in this order. Each step is gated on the previous.

### Step 0 — Preconditions
- [ ] `review/expert_pilot_6500_review_sample_v0.1.jsonl` exists (324 lines)
- [ ] `reports/expert_pilot_6500_quality_v0.1.json` exists (baseline)
- [ ] This guideline is agreed by all reviewers
- [ ] Reviewer IDs decided; pool fixed for the run

### Step 1 — Assign
- [ ] Load the sample; extract all `record_id`s
- [ ] Assign exactly one reviewer per record (category first, then round-robin)
- [ ] Write assignments (do not write verdicts yet)

### Step 2 — Review
- [ ] Each reviewer scores every assigned record on the four dimensions
- [ ] Run the record-specific checks: license, duplicate, security, provenance
- [ ] Assign verdict KEEP / REVIEW / REJECT with notes
- [ ] Do NOT consult `calibration.auto_gate` while scoring

### Step 3 — Record decisions
- [ ] Write `review/expert_pilot_6500_review_decisions_v0.1.jsonl`
- [ ] Validate: 1 decision per record, no duplicates, reviewer IDs valid,
      notes non-empty and specific
- [ ] Count KEEP / REVIEW / REJECT (measured)

### Step 4 — Compute acceptance
- [ ] Acceptance rate = KEEP ÷ total reviewed (≥ 80% → supports GO)
- [ ] Compute agreement rate vs `auto_gate`
- [ ] List disagreements by record, stratum, dimension
- [ ] Write `reports/expert_pilot_6500_review_summary_v0.1.json`
- [ ] Append human-review section to `reports/expert_pilot_6500_decision_v0.1.md`

### Step 5 — Verify
- [ ] Fresh verification of the decision file (counts, uniqueness, schema)
- [ ] Confirm no dataset/sample/manifest mutation (`git status` on protected dirs)
- [ ] Report measured results only

## Constraints

- No training, no release, no dataset modification, no unverified sources.
- Open-Platypus remains HOLD.
- This document does not perform or label anything — review execution is a
  separate approved step.
