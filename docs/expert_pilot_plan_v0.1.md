# Atlas Expert Pilot Plan v0.1

## Purpose

Plan a 10,000-record expert pilot to validate the Atlas expert pipeline
before full acquisition.

This document is analysis and design only:
- no ingestion
- no downloads
- no dataset modifications
- no model training

## Compatibility

This pilot plan is designed to be compatible with:
- `metadata/expert_source_registry_v0.1.json`
- `docs/expert_extraction_runbook_v0.1.md`
- `docs/expert_quality_gate_v0.1.md`
- `docs/expert_record_schema_v0.1.md`
- `docs/expert_evaluation_benchmark_v0.1.md`

## Unknowns

The following items are marked `[UNKNOWN]` because they depend on future
sample extraction, human review, or calibration:
- exact sample yields per source after filtering
- exact pass rates for schema and quality gate
- human review coverage needed for pilot confidence
- final pilot success/failure thresholds

These must be resolved during pilot execution, not assumed now.

---

## 1. Pilot Objective

Validate that the Atlas expert pipeline can produce high-quality,
schema-compliant, license-safe, and deduplicated expert records from
Priority 1 sources.

Specific objectives:
1. Confirm source confirmation, license check, and small-sample extraction
   workflows are practical.
2. Measure schema conversion completeness and quality gate pass rates.
3. Establish duplicate-rate and provenance-completeness baselines.
4. Produce a human-review sample for calibration and threshold tuning.
5. Decide whether to proceed, revise, or stop the expert pipeline.

---

## 2. Target Size

Total pilot size: 10,000 records

| Domain | Target | Rationale |
|--------|--------|-----------|
| Software Engineering | 4,000 | Largest priority domain; includes debugging, review, and Q&A sources |
| AI/ML | 3,000 | Includes paper, instruction, and textbook-style sources |
| Mathematics | 3,000 | Includes competition and instruction sources |

This pilot does not cover Science, System Engineering, Creative, or Business.

---

## 3. Source Selection

Only VERIFIED and PARTIAL sources from `metadata/expert_source_registry_v0.1.json`
are eligible.

### 3.1 Software Engineering sources

| Source ID | Name | Status | License | Notes |
|-----------|------|--------|---------|-------|
| `expert-swe-001` | SWE-bench verified | VERIFIED | MIT | Primary SE source; issue-to-patch pairs with verification predicates |
| `expert-swe-002` | StackExchange Code XML dumps | PARTIAL | CC-BY-SA-4.0 | Secondary SE source; requires PII stripping and attribution |

### 3.2 AI/ML sources

| Source ID | Name | Status | License | Notes |
|-----------|------|--------|---------|-------|
| `expert-aiml-001` | ArXiv cs.LG / cs.CL / cs.AI / stat.ML | VERIFIED | arXiv non-exclusive license | Primary AI/ML source; abstracts and well-sourced sections |
| `expert-aiml-002` | Open-Platypus | VERIFIED | Apache-2.0 | Secondary AI/ML source; instruction pairs across science/math/code |

### 3.3 Mathematics sources

| Source ID | Name | Status | License | Notes |
|-----------|------|--------|---------|-------|
| `expert-math-002` | OpenMathInstruct-2 | PARTIAL | MIT, gated; verify on download | Primary math source; large instruction dataset; gated access must be confirmed before pilot extraction |

No UNKNOWN sources are included in this pilot.

---

## 4. Acquisition Sequence

The pilot follows a strict sequential gate process.
Do not proceed to the next step until the current gate is satisfied.

### Gate 1: Source confirmation
- Confirm official source URLs and access conditions for each selected source.
- Document dataset version/snapshot/dump date.
- Reject any source that becomes UNKNOWN or unavailable before pilot start.

### Gate 2: License check
- Verify license terms for each selected source.
- Confirm redistribution and expert-training use are permitted.
- Reject or defer any source with unresolved license risk.
- Record license decision in pilot metadata.

### Gate 3: Small sample extraction
- Extract a small representative sample from each source.
- Do not extract the full dataset.
- Sample size per source: `[UNKNOWN]` until extraction feasibility is assessed.
- Preserve raw sample artifacts separately from curated records.

### Gate 4: Schema conversion
- Convert each sample record to `docs/expert_record_schema_v0.1.md` format.
- Apply source-specific transformations from `docs/expert_extraction_runbook_v0.1.md`.
- Record conversion failures and reasons.

### Gate 5: Quality gate validation
- Apply `docs/expert_quality_gate_v0.1.md` to all converted records.
- Classify each record as KEEP, REVIEW, or REJECT.
- Record quality score distribution and failure reasons.

### Gate 6: Human review sample
- Select a stratified human-review sample from KEEP and REVIEW records.
- Sample should cover all domains and sources.
- Minimum sample size: `[UNKNOWN]` until calibration study defines confidence intervals.
- Human review should assess correctness, reasoning quality, explanation completeness, and hallucination flags.

---

## 5. Success Criteria

Pilot is considered successful if all of the following criteria are met.

### 5.1 Schema pass rate
- Minimum `[UNKNOWN]`% of extracted samples convert cleanly to the expert record schema.
- Conversion failures must be categorized and explainable.

### 5.2 Quality score distribution
- Quality scores should show meaningful variance, not collapse to a constant.
- Target: at least 3 distinct quality score values across the pilot.
- Mean and distribution should be documented for later calibration.

### 5.3 Duplicate rate
- Exact duplicate rate after deduplication must be measured.
- Near-duplicate rate must be measured.
- Target: `[UNKNOWN]%` duplicate rate; exact target to be defined after first extraction.

### 5.4 Provenance completeness
- Minimum `[UNKNOWN]%` of KEEP records must have complete provenance:
  - `source.source_id`
  - `source.url`
  - `source.accessed_at`
  - `provenance.original_id`
  - `provenance.transformations`
  - `provenance.ingestion_pipeline`

### 5.5 Human review agreement
- Human review sample must provide measurable agreement with automated quality gates.
- Results will be used to calibrate expert scoring thresholds.

---

## 6. Stop Conditions

The pilot should be rejected or revised if any of the following occur.

### Hard stop conditions
- Any selected source becomes unavailable or license-unsafe during the pilot.
- Schema conversion failure rate exceeds `[UNKNOWN]%`.
- Quality gate rejects more than `[UNKNOWN]%` of records with systematic, unfixable failures.
- Duplicate rate indicates source overlap or extraction error that cannot be resolved.
- Provenance completeness falls below minimum required for training safety.

### Revision conditions
- Source sample yields are insufficient to meet domain targets.
- Quality score distribution shows degenerate behavior.
- Human review reveals systematic scoring errors.
- Extraction or transformation workflow is impractical at scale.

If a hard stop condition is met, pause the pilot, document the failure,
and revise the plan before continuing.

---

## 7. Pilot Outputs

The pilot should produce the following artifacts:
- `metadata/expert_pilot_manifest_v0.1.json` — source list, sample counts, status
- `metadata/expert_pilot_quality_report_v0.1.json` — schema pass rate, quality distribution, duplicate rate, provenance completeness
- `docs/expert_pilot_report_v0.1.md` — human-readable pilot summary and go/no-go recommendation
- `review_queue/expert_pilot_review_sample.jsonl` — human review worksheet

---

## 8. Recommended Execution Order

1. Confirm sources and licenses.
2. Extract small samples per source.
3. Convert to expert schema.
4. Run quality gate.
5. Measure schema/quality/duplicate/provenance metrics.
6. Select human review sample.
7. Complete human review.
8. Write pilot report and go/no-go recommendation.

## Out of Scope

- Full acquisition
- Complete dataset downloads
- Model training or fine-tuning
- Release or publication workflows
- Any operation that modifies `raw/`, `curated/`, or existing datasets
