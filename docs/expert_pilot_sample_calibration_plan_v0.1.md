# Atlas Expert Pilot Sample Calibration Plan v0.1

## Purpose

Validate the Atlas expert pipeline using tiny representative samples before
committing to the full 10K pilot.

This phase is a direct response to Phase 0 `HOLD` blockers:
- unknown extraction yields
- unverified math-source access/license
- uncalibrated schema/quality gate targets

This document is analysis and design only:
- no ingestion
- no downloads
- no dataset modifications
- no model training

## Scope

Only the following samples:
- SWE-bench verified: 100 records
- Open-Platypus: 100 records
- ArXiv cs.LG / cs.CL / cs.AI / stat.ML: 10–20 papers/examples
- Mathematics: pending; no sample until license/access is resolved

## Compatibility

This plan is designed to be compatible with:
- `reports/expert_pilot_phase0_validation_v0.1.json`
- `metadata/expert_pilot_manifest_v0.1.json`
- `docs/expert_pilot_plan_v0.1.md`
- `docs/expert_extraction_runbook_v0.1.md`
- `docs/expert_quality_gate_v0.1.md`
- `docs/expert_record_schema_v0.1.md`

## Unknowns

The following items are marked `[UNKNOWN]` because they depend on actual
sample execution and calibration:
- exact extraction yield per source after filtering
- exact schema pass rate
- exact quality gate pass rate
- exact duplicate rate
- exact provenance completeness rate
- exact success thresholds for Phase 1 promotion

These must be measured during sample calibration, not assumed now.

---

## 1. Sample Sources and Sizes

| Source ID | Name | Domain | Sample Size | Status | Notes |
|-----------|------|--------|-------------|--------|-------|
| `expert-swe-001` | SWE-bench verified | software_engineering | 100 records | VERIFIED | MIT-licensed verified issue-to-patch pairs |
| `expert-aiml-002` | Open-Platypus | ai_machine_learning | 100 records | VERIFIED | Apache-2.0 instruction pairs |
| `expert-aiml-001` | ArXiv cs.LG / cs.CL / cs.AI / stat.ML | ai_machine_learning | 10–20 papers/examples | VERIFIED | arXiv non-exclusive license; paper-to-example conversion required |
| `expert-math-002` | OpenMathInstruct-2 | mathematics | 0 | PARTIAL/PENDING | Gated access and license unverified; sample deferred |

Only these tiny samples are allowed in Phase 0.5.
No full acquisition, no full dataset downloads, no dataset modifications.

---

## 2. Per-Source Calibration Design

### 2.1 SWE-bench verified

Source id: `expert-swe-001`
Registry status: `VERIFIED`
Sample size: 100 records

#### Extraction input
- Official SWE-bench verified subset from the Hugging Face dataset page
- JSON-like instances with task identifiers, problem statements, repo metadata,
  and patch/evaluation references
- Verified instances with `FAIL_TO_PASS` and `PASS_TO_PASS` counts

#### Transformation steps
1. Select 100 verified instances with complete patch/test evidence.
2. Normalize repo, branch, and commit references.
3. Strip or anonymize contributor metadata if present in patches or logs.
4. Convert each instance to `docs/expert_record_schema_v0.1.md` format:
   - `domain`: `software_engineering`
   - `expert_tier`: `E2`
   - `difficulty`: assign from instance signal; default `3` if absent
   - `type`: `qa`
   - `source`: `expert-swe-001`, SWE-bench verified, MIT, snapshot date
   - `license`: `MIT`
   - `problem`: issue statement or bug description
   - `context`: repo name, file paths, failing tests, environment constraints
   - `solution`: patch summary or repaired code
   - `verification.method`: `gold_patch`
   - `verification.status`: `verified`
   - `verification.evidence`: `FAIL_TO_PASS` and `PASS_TO_PASS` counts
   - `provenance.original_id`: upstream instance identifier
   - `metadata.subdomains`: debugging, patch-generation, language/tool tags
   - `messages`: user turn = problem + optional context; assistant turn = solution

#### Expected Atlas record output
- 100 converted expert records in Atlas Expert Record Schema format
- All required fields present
- `verification.evidence` populated for each record

#### Validation checks
- All 100 records have non-empty `problem` and `solution`
- All 100 records have `verification.method == "gold_patch"`
- All 100 records have `verification.status == "verified"`
- All 100 records have non-empty `verification.evidence`
- No security-sensitive private repo details remain in context or solution

#### Metrics
- schema pass rate
- quality gate pass rate
- duplicate rate
- provenance completeness

---

### 2.2 Open-Platypus

Source id: `expert-aiml-002`
Registry status: `VERIFIED`
Sample size: 100 records

#### Extraction input
- Official Open-Platypus dataset from the Hugging Face dataset page
- Instruction-style pairs across science, math, and code
- License: `Apache-2.0`

#### Transformation steps
1. Select 100 representative instruction pairs.
2. Separate human-authored content from model-augmented content if detectable.
3. Normalize question/answer formatting.
4. Convert each pair to `docs/expert_record_schema_v0.1.md` format:
   - `domain`: `ai_machine_learning`
   - `expert_tier`: `E2`
   - `difficulty`: assign from question complexity; default `2`
   - `type`: `qa` or `instruction`
   - `source`: `expert-aiml-002`, Open-Platypus, `Apache-2.0`, access date
   - `license`: `Apache-2.0`
   - `problem`: question or instruction text
   - `context`: optional background or data provided in the pair
   - `solution`: answer text
   - `verification.method`: `verified_solution_set`
   - `verification.status`: `verified` only after factual audit
   - `verification.evidence`: source pair id, audit notes
   - `provenance.original_id`: upstream row id or hash
   - `metadata.subdomains`: science, math, code, or domain-specific tags
   - `metadata.model_generated`: `true` if upstream content is model-generated
   - `messages`: user turn = problem; assistant turn = solution

#### Expected Atlas record output
- 100 converted expert records in Atlas Expert Record Schema format
- All required fields present
- `metadata.model_generated` accurately reflects source content

#### Validation checks
- All 100 records have non-empty `problem` and `solution`
- All 100 records have `license == "Apache-2.0"`
- Model-generated content is flagged in `metadata.model_generated`
- No empty or malformed answers are promoted

#### Metrics
- schema pass rate
- quality gate pass rate
- duplicate rate
- provenance completeness

---

### 2.3 ArXiv cs.LG / cs.CL / cs.AI / stat.ML

Source id: `expert-aiml-001`
Registry status: `VERIFIED`
Sample size: 10–20 papers/examples

#### Extraction input
- ArXiv abstract and source text for cs.LG, cs.CL, cs.AI, and stat.ML
- Metadata includes arXiv id, authors, title, abstract, and PDF/source links
- License: arXiv non-exclusive license

#### Transformation steps
1. Select 10–20 papers or well-sourced sections.
2. Fetch abstracts and selected sections only; do not ingest full PDFs.
3. Preserve arXiv id, authors, and year for provenance.
4. Convert each paper/section to `docs/expert_record_schema_v0.1.md` format:
   - `domain`: `ai_machine_learning`
   - `expert_tier`: `E1`
   - `difficulty`: assign from section complexity; default `2`
   - `type`: `reasoning` or `qa`
   - `source`: `expert-aiml-001`, ArXiv cs.LG/CL/AI/stat.ML,
     `arXiv non-exclusive license`, access date
   - `license`: `arXiv non-exclusive license`
   - `attribution`: required; include arXiv id, authors, and title
   - `problem`: research question or concept explanation prompt derived from paper
   - `context`: abstract, section excerpt, methodology summary, constraints
   - `solution`: expert explanation, derivation, or summary grounded in source
   - `verification.method`: `peer_review`
   - `verification.status`: `verified` only for well-sourced sections
   - `verification.evidence`: arXiv id, section source, author/year
   - `provenance.original_id`: arXiv id
   - `metadata.subdomains`: transformers, llm, rag, mlops, or paper-specific tags
   - `messages`: user turn = problem + context; assistant turn = solution

#### Expected Atlas record output
- 10–20 converted expert records in Atlas Expert Record Schema format
- All required fields present
- `attribution` is non-empty for each record

#### Validation checks
- All records have non-empty `problem` and `solution`
- All records have `source.url` pointing to official arXiv source
- All records have `provenance.original_id` set to arXiv id
- Retracted or corrected papers are excluded when detectable

#### Metrics
- schema pass rate
- quality gate pass rate
- duplicate rate
- provenance completeness

---

### 2.4 Mathematics

Source id: `expert-math-002`
Registry status: `PARTIAL`
Sample size: 0

#### Status
- Deferred from Phase 0.5
- Gated access and exact license terms remain unverified
- No sample extraction until Phase 0 resolves math-source blockers

#### Expected action
- Keep `expert-math-002` in `pending` state
- Re-evaluate for Phase 0.5 or Phase 1 after access/license verification

---

## 3. Common Validation Checks

All samples, regardless of source, must pass the following checks:

### 3.1 Schema completeness
- Every record contains all required fields from `docs/expert_record_schema_v0.1.md`
- `id`, `domain`, `expert_tier`, `difficulty`, `type` are valid
- `messages` contains at least one `user` and one `assistant` turn
- `problem` and `solution` are non-empty strings

### 3.2 License validation
- `license` is not `unknown`
- If `license` requires attribution, `attribution` is non-empty
- No restricted, proprietary, or NC licenses without policy exception

### 3.3 Duplicate detection
- Exact duplicates are identified within each sample
- Near-duplicates are identified by normalized `problem` + `solution` hash
- Duplicate rate is measured and reported

### 3.4 Provenance completeness
- `source.source_id` present
- `source.url` present
- `source.accessed_at` present
- `provenance.original_id` present
- `provenance.transformations` present and non-empty
- `provenance.ingestion_pipeline` present

### 3.5 Quality gate readiness
- Each record is classified as `KEEP`, `REVIEW`, or `REJECT`
- Quality score distribution is computed
- Failure reasons are recorded for rejected records

---

## 4. Metrics to Collect

For each sample source, compute:

| Metric | Definition |
|--------|------------|
| schema pass rate | fraction of sample records that convert cleanly to expert schema |
| quality gate pass rate | fraction of sample records classified as `KEEP` or `REVIEW` |
| duplicate rate | fraction of sample records that are exact or near-duplicates |
| provenance completeness | fraction of sample records with all required provenance fields |

These metrics are used to decide whether Phase 1 can proceed.

---

## 5. Success Criteria

Sample calibration allows Phase 1 to proceed only if all of the following
are true.

### 5.1 Schema pass rate
- Minimum `[UNKNOWN]%` of sample records convert cleanly to the expert schema.
- Conversion failures are categorized and explainable.

### 5.2 Quality gate pass rate
- Quality gate runs without error on all sample records.
- Score distribution shows meaningful variance, not a constant.
- Failure reasons are recorded and actionable.

### 5.3 Duplicate rate
- Exact and near-duplicate rates are measurable.
- Duplicate patterns are explainable and not indicative of source corruption.

### 5.4 Provenance completeness
- Minimum `[UNKNOWN]%` of sample records have complete provenance fields.

### 5.5 Source-specific criteria
- SWE-bench sample: patch/test evidence is present for all converted records
- Open-Platypus sample: model-generated flag is accurate for all converted records
- ArXiv sample: attribution and provenance are complete for all converted records

### 5.6 Math source resolution
- `expert-math-002` access and license are resolved before Phase 1 proceeds
- If math source remains unresolved, Phase 1 proceeds without it and domain targets are revised

---

## 6. Stop Conditions for Sample Calibration

Sample calibration should be rejected or revised if any of the following occur.

### Hard stop conditions
- Selected source becomes unavailable or license-unsafe during sampling
- Schema conversion failure rate exceeds `[UNKNOWN]%`
- Quality gate rejects all sample records with systematic, unfixable failures
- Duplicate rate indicates source corruption or extraction error
- Provenance completeness falls below minimum required for training safety

### Revision conditions
- Sample yields are insufficient to validate pipeline behavior
- Quality score distribution is degenerate
- Extraction or transformation workflow is impractical at tiny scale
- Human review is impossible because no sample can be produced

If a hard stop condition is met, pause sample calibration, document the
failure, and revise the plan before any Phase 1 attempt.

---

## 7. Recommended Execution Order

1. Confirm SWE-bench verified access and license.
2. Extract 100 SWE-bench verified sample records.
3. Confirm Open-Platypus access and license.
4. Extract 100 Open-Platypus sample records.
5. Confirm ArXiv access and license.
6. Extract 10–20 ArXiv papers/examples.
7. Convert all samples to expert schema.
8. Run quality gate on all converted samples.
9. Compute schema/quality/duplicate/provenance metrics.
10. Write sample calibration report with go/hold/stop recommendation.
11. If GO, update Phase 0 validation report and proceed to Phase 1.
12. If HOLD, revise pipeline and repeat sample calibration.
13. If STOP, document blockers and alternatives.

## Out of Scope

- Full acquisition
- Complete dataset downloads
- Model training or fine-tuning
- Release or publication workflows
- Any operation that modifies `raw/`, `curated/`, or existing datasets
