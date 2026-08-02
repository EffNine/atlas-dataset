# Atlas Expert Pilot Execution Checklist v0.1

## Purpose

Step-by-step execution checklist for Atlas Expert Pilot v0.1.

This checklist is planning and procedure only:
- no full acquisition
- no dataset modification
- no model training
- unknown facts remain explicitly marked `[UNKNOWN]`

## Compatibility

This checklist is designed to be compatible with:
- `metadata/expert_pilot_manifest_v0.1.json`
- `docs/expert_pilot_plan_v0.1.md`
- `docs/expert_extraction_runbook_v0.1.md`
- `docs/expert_quality_gate_v0.1.md`
- `docs/expert_record_schema_v0.1.md`

---

## Phase 0: Pre-flight Validation

### Objective
Confirm the pilot environment, tools, and referenced docs are ready before
any source work begins.

### Input
- Repo state on dev PC
- Existing expert design documents
- Pilot plan and manifest drafts

### Output
- Pre-flight checklist completion record
- Identified blockers, if any

### Pass Criteria
- All required design docs exist and are readable
- No conflicting changes to expert schema, quality gate, or runbook
- Execution environment can run validation scripts

### Failure Conditions
- Missing required design doc
- Conflicting schema or gate definitions
- Environment cannot run basic validation

---

## Phase 1: Source Confirmation

### Objective
Confirm official source URLs, access conditions, version/snapshot/dump dates,
and current availability for all selected pilot sources.

### Input
- `metadata/expert_source_registry_v0.1.json`
- `metadata/expert_pilot_manifest_v0.1.json`

### Output
- Updated `metadata/expert_pilot_manifest_v0.1.json` with confirmed source facts
- List of sources rejected or deferred at this phase

### Pass Criteria
- Every selected source has confirmed `official_source`, `accessed_at`,
  `version`, and `availability`
- Any source that cannot be confirmed is marked `STOP` or deferred

### Failure Conditions
- Selected source becomes unavailable or unsupported before extraction
- Official source cannot be identified
- Access terms prohibit inspection needed for pilot

---

## Phase 2: License Verification

### Objective
Verify license terms for each confirmed source and confirm redistribution
and expert-training use are permitted.

### Input
- Confirmed source facts from Phase 1
- `metadata/expert_source_registry_v0.1.json` license fields

### Output
- Updated `metadata/expert_pilot_manifest_v0.1.json` license status per source
- License exception log, if any

### Pass Criteria
- Every selected source has a resolved license status
- No `unknown` license remains for a source intended for pilot extraction
- Attribution requirements are documented for share-alike sources

### Failure Conditions
- License cannot be verified
- License prohibits expert-training use and no exception applies
- License terms are materially different from registry assumptions

**Decision point:**
- If any pilot source fails license verification, defer that source and
  revise domain targets before proceeding.

---

## Phase 3: Small Sample Extraction

### Objective
Extract a small representative sample from each confirmed and licensed source.
Do not extract full datasets.

### Input
- License-cleared sources from Phase 2
- Source-specific extraction guidance from `docs/expert_extraction_runbook_v0.1.md`

### Output
- Raw sample artifacts per source
- `metadata/expert_pilot_manifest_v0.1.json` updated with sample counts and
  extraction status

### Pass Criteria
- Sample is representative of source content
- Sample size is sufficient for schema conversion and quality gate validation
- Raw samples are stored separately from curated records

### Failure Conditions
- Source access fails during sampling
- Extracted sample is not representative
- Sample size is insufficient to validate downstream gates
- Extraction reveals systematic data quality issues

**Note:** Exact sample size per source is `[UNKNOWN]` until extraction
feasibility is assessed.

---

## Phase 4: Schema Conversion

### Objective
Convert extracted samples to `docs/expert_record_schema_v0.1.md` format.

### Input
- Raw samples from Phase 3
- `docs/expert_record_schema_v0.1.md`
- `docs/expert_extraction_runbook_v0.1.md`

### Output
- Converted expert records
- Conversion failure report with reasons
- Updated `metadata/expert_pilot_manifest_v0.1.json` schema validation status

### Pass Criteria
- Minimum `[UNKNOWN]%` of sample records convert cleanly
- Conversion failures are categorized and explainable
- All converted records contain required schema fields

### Failure Conditions
- Schema conversion failure rate exceeds `[UNKNOWN]%`
- Required fields cannot be populated from source data
- Transformation rules are impractical or ambiguous

---

## Phase 5: Quality Gate Execution

### Objective
Apply `docs/expert_quality_gate_v0.1.md` to all converted records.

### Input
- Converted records from Phase 4
- `docs/expert_quality_gate_v0.1.md`
- Base quality score from existing Atlas quality framework

### Output
- Quality-gated records classified as `KEEP`, `REVIEW`, or `REJECT`
- Quality score distribution report
- Updated `metadata/expert_pilot_manifest_v0.1.json` quality gate status

### Pass Criteria
- Quality gate runs without error on all converted records
- Score distribution shows meaningful variance
- Failure reasons are recorded for rejected records

### Failure Conditions
- Quality gate rejects more than `[UNKNOWN]%` of records with systematic,
  unfixable failures
- Scoring behavior is degenerate or inconsistent
- Domain-specific checks cannot be applied as designed

---

## Phase 6: Human Review Calibration

### Objective
Select and complete a stratified human-review sample from `KEEP` and `REVIEW`
records to calibrate automated quality and tier assignment.

### Input
- Quality-gated records from Phase 5
- Human review schema and guidance from existing Atlas calibration docs

### Output
- Human review worksheet
- Human review results
- Calibration report comparing human judgment to automated gates
- Updated `metadata/expert_pilot_manifest_v0.1.json` human review status

### Pass Criteria
- Human review sample covers all pilot domains and sources
- Review records include correctness, reasoning quality, explanation completeness,
  and hallucination flags
- Results provide actionable calibration signal for thresholds

### Failure Conditions
- Human review cannot be completed
- Review reveals systematic automation errors that cannot be corrected
- Inter-rater agreement is too low to calibrate thresholds

**Note:** Minimum human review sample size is `[UNKNOWN]` until calibration
study defines confidence intervals.

---

## Phase 7: Scale Decision

### Objective
Decide whether to proceed to the full 10K pilot, revise the plan, or stop.

### Input
- Pilot outputs from Phases 0-6
- `metadata/expert_pilot_manifest_v0.1.json`
- Pilot quality and calibration reports

### Output
- Final go/hold/stop decision
- Recommended next actions

### Pass Criteria for GO
- Source confirmation and license verification are complete
- Schema conversion pass rate meets defined threshold
- Quality gate produces meaningful score distribution
- Duplicate and provenance metrics are acceptable
- Human review confirms automated gates are usable

### Failure Conditions for STOP
- Any selected source becomes unavailable or license-unsafe during the pilot
- Schema conversion failure rate exceeds acceptable threshold
- Quality gate rejects records at a rate indicating fundamental source or
  pipeline mismatch
- Duplicate or provenance issues cannot be resolved
- Human review shows calibration is not achievable in current form

### Revision Conditions for HOLD
- Sample yields are insufficient for domain targets
- Quality score distribution is degenerate
- Human review shows correctable scoring errors
- Extraction or transformation workflow needs redesign

---

## Final Decisions

### GO
Proceed to 10K pilot execution.

Meaning:
- All phases completed without hard-stop failures
- Pipeline is validated at small scale
- Sources are confirmed and license-safe
- Quality gate and human review are calibrated enough for pilot-scale use

### HOLD
Fix pipeline issues before scaling.

Meaning:
- Correctable problems were found in extraction, schema conversion,
  quality gating, or calibration
- Do not scale until root causes are fixed and re-validated on a new small sample

### STOP
Reject source or approach.

Meaning:
- A hard stop condition was met
- Pilot approach is not viable without fundamental redesign
- Document failure reasons and alternatives before any retry

---

## Recommended First Execution Command/Action

Confirm source URLs and licenses from the existing registry, then update
`metadata/expert_pilot_manifest_v0.1.json` from `planned` to `in_progress`
for Phase 1.

A concrete first action is:

1. Inspect `metadata/expert_source_registry_v0.1.json`
2. Inspect `metadata/expert_pilot_manifest_v0.1.json`
3. Update manifest source statuses to reflect Phase 1 confirmation state
4. Record any access-date or snapshot findings in the manifest notes

No ingestion or download should begin until Phase 1 and Phase 2 are
completed and recorded.
