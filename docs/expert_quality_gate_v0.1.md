# Atlas Expert Quality Gate v0.1

## Purpose

Define how Atlas decides whether an expert record is good enough for 300M
model training.

This document is analysis and design only:
- no ingestion
- no downloads
- no dataset modifications

## Scope

Applies to expert-domain records only:
- software engineering
- AI/ML
- mathematics
- science
- system engineering

It is intended to sit downstream of `docs/expert_record_schema_v0.1.md` and
upstream of any training-view generation.

## Compatibility

This gate is designed to be compatible with:
- `docs/expert_record_schema_v0.1.md`
- existing Atlas quality scoring philosophy in `docs/quality_calibration.md`
- `docs/quality_engine_validation_report.md`

Where this gate adds expert-specific checks, it does not replace the base
quality scorer. It is an additional layer on top of it.

## Unknowns

The following items are marked `[UNKNOWN]` because they depend on future
calibration or human review data that does not yet exist:
- exact numeric thresholds for some domain-specific checks
- calibrated auto-score thresholds for expert data
- human-agreement targets for expert review

These must be resolved during implementation calibration, not assumed now.

---

## 1. Global Quality Requirements

Every expert record must satisfy all global requirements before it can be
promoted to training use.

### 1.1 Provenance validation

- `source.source_id` must be present and map to a known source in
  `metadata/expert_source_registry_v0.1.json` or later registry.
- `source.url` must be present unless the source is fully internal and
  explicitly approved.
- `source.accessed_at` must be a valid ISO-8601 date.
- `provenance.original_id` must be present.
- `provenance.transformations` must be a non-empty ordered list.
- `provenance.ingestion_pipeline` must identify the expert pipeline version.

### 1.2 License validation

- `license` must not be `unknown` in curated expert data.
- If `license` is `CC-BY-SA-4.0` or similar, `attribution` must be non-empty.
- Restricted, proprietary, or NC licenses must be rejected unless an explicit
  policy exception is recorded.

### 1.3 Schema completeness

- All required fields from `docs/expert_record_schema_v0.1.md` must be present.
- `id`, `domain`, `expert_tier`, `difficulty`, `type` must be valid.
- `messages` must contain at least one `user` and one `assistant` turn.
- `problem` and `solution` must be non-empty strings.

### 1.4 Duplicate detection

- Exact duplicate detection by `id` is mandatory.
- Near-duplicate detection by normalized `problem` + `solution` hash is
  required within each source and domain.
- Cross-source duplicates should be flagged for review, not auto-rejected,
  because the same expert content may be legitimately reused with different
  framing.

### 1.5 Correctness verification

- `verification.method` must be present.
- `verification.status` must be one of:
  `verified`, `unverified`, `needs_review`, `rejected`.
- Records marked `verified` must have non-empty `verification.evidence`.
- If verification evidence is absent, the record must be treated as lower
  confidence and routed to `REVIEW`.

### 1.6 Explanation quality

- `solution` must be substantive enough to train a 300M model.
- Empty, placeholder, or single-sentence answers are not acceptable for
  expert training unless explicitly justified by source type.
- For reasoning-heavy domains, chain-of-thought or derivation structure is
  preferred; absence should lower confidence, not automatically reject.

---

## 2. Domain-Specific Validation

### 2.1 Software Engineering

| Check | Requirement | Rationale |
|-------|-------------|----------|
| Code correctness | Patch or code example must be syntactically valid and internally consistent | 300M specialist must learn correct code patterns |
| Bug reasoning | Problem statement must identify a real defect or design issue | Prevents training on fictitious bugs |
| Test verification | If test evidence exists, it must be referenced in `verification.evidence` | SWE-bench and similar sources provide this |
| Architectural explanation | Design answers must include rationale, tradeoffs, or constraints | Prevents shallow "use microservices" answers |
| Security sensitivity | Private repo paths, keys, or credentials must be stripped | Hard gate; reject if present |

### 2.2 AI/ML

| Check | Requirement | Rationale |
|-------|-------------|----------|
| Technical accuracy | Claims about algorithms, models, or metrics must be consistent with authoritative sources | 300M specialist must not learn incorrect ML facts |
| Methodology explanation | Papers or textbook derivations must explain method, not just state results | Prevents memorization without understanding |
| Experiment interpretation | Results must be interpreted with awareness of baseline, dataset, and metric | Prevents overclaiming |
| Limitation awareness | Answers should acknowledge scope or constraints when source does | Encourages calibrated expert reasoning |
| Model-generated flag | `metadata.model_generated` must be accurate | Needed for synthetic cap and trust calibration |

### 2.3 Mathematics

| Check | Requirement | Rationale |
|-------|-------------|----------|
| Solution correctness | Final answer or proof must be mathematically valid | Hard gate for math expert training |
| Reasoning quality | Steps must be logically connected; skipped reasoning is a penalty | 300M model needs traceable reasoning |
| Proof/derivation validation | Formal or semi-formal proofs must preserve notation and logical flow | Prevents garbled math explanations |
| Ground-truth availability | If a validator or official solution exists, use it as primary evidence | Preferred verification path |
| Notation consistency | LaTeX or symbolic notation should be preserved and consistent | Reduces training noise |

### 2.4 Science and System Engineering

Science and System Engineering are deferred from Phase 1 domain-specific
validation. Once expert data for these domains enters the pipeline, analogous
tables should be added.

---

## 3. Expert Scoring System

### 3.1 Score dimensions

Each record receives a score on the following dimensions.
Scores are integers from 1 to 5 unless otherwise noted.

| Dimension | Meaning | Notes |
|-----------|---------|-------|
| correctness | Factual or technical correctness of the solution | Hard gate; low score should reject |
| difficulty | How hard the problem is for a 300M specialist | Maps to curriculum pacing |
| reasoning_depth | Whether the answer shows step-by-step reasoning or justification | Higher is better for expert training |
| explanation_quality | Clarity, structure, and trainability of the answer | Not just length; structure matters |
| provenance_confidence | How trustworthy the source and verification evidence are | Source registry status matters here |
| uniqueness | How much this record adds beyond near-duplicates | Deduplication signal |

### 3.2 Thresholds

The following thresholds are proposed. They are marked `[UNKNOWN]` because
they have not yet been calibrated against human expert review.

| Threshold | Meaning | Current guidance |
|-----------|---------|------------------|
| reject | Record is unsuitable for 300M expert training | `correctness <= 2` OR `provenance_confidence <= 1` OR schema/legal failure |
| accepted | Record is usable for expert training | `correctness >= 3` AND `provenance_confidence >= 3` AND schema/legal pass AND not rejected |
| gold | Record is high-value exemplar for expert training | `[UNKNOWN]`; likely requires `correctness >= 4`, `reasoning_depth >= 4`, `explanation_quality >= 4`, and strong verification evidence |

### 3.3 Interaction with existing Atlas quality scoring

- Existing `quality_score.py` provides a 0-10 quality score.
- The expert scoring system is additive and runs after the base quality score.
- A record with high base quality but low expert-specific score should be
  routed to `REVIEW`, not automatically rejected.
- A record with low base quality should be rejected regardless of expert
  score, because base quality is a minimum bar.

---

## 4. Expert Tier Validation

Expert tiers are assigned based on source type, verification strength, and
content characteristics.

### 4.1 E1: Professional knowledge

**Definition:**
Authoritative professional knowledge from high-trust sources.

**Typical sources:**
- Official documentation
- Verified community Q&A with expert voting
- Textbook-derived instruction from openly licensed sources
- Curated reference material

**Qualification criteria:**
- Source is accepted or review-tier in `expert_source_registry_v0.1.json`
  with high quality score.
- Content is grounded in authoritative reference material.
- Verification method is `peer_review`, `doc_template`, or equivalent.
- Solution is technically correct and complete.

**Expected share in 300M training:** 60%

### 4.2 E2: Advanced reasoning

**Definition:**
Problem-solving content that requires non-trivial reasoning, derivation, or
implementation.

**Typical sources:**
- Verified issue-to-patch pairs
- Competition or coursework problems with verified solutions
- Experiment analysis and paper explanations
- Code review with actionable feedback

**Qualification criteria:**
- Source is accepted or review-tier with medium-to-high quality score.
- Content requires multi-step reasoning, debugging, or design decisions.
- Verification method is `gold_patch`, `auto_grader`, `verified_solution_set`,
  or equivalent.
- Solution includes reasoning, not just a final answer.

**Expected share in 300M training:** 30%

### 4.3 E3: Frontier

**Definition:**
Research-level or competition-frontier content that pushes the boundary of
current expert knowledge.

**Typical sources:**
- Research papers with novel results
- Olympiad or research-frontier problems
- Novel solutions or experimental designs

**Qualification criteria:**
- Source is accepted or review-tier with frontier or competition status.
- Content is at the boundary of what a 300M specialist can reasonably learn.
- Verification method is `peer_review`, `official_solution`, or equivalent
  with strong evidence.
- Content includes explicit assumptions, constraints, or novelty context.

**Expected share in 300M training:** 10%

### 4.4 Tier assignment rules

- Do not assign an expert tier without source evidence.
- If a source contains mixed tiers, assign tier per record based on content
  characteristics, not source label alone.
- Tier assignment must be recorded in `expert_tier` and justified in
  `metadata.notes` when borderline.

---

## 5. Output Decision

Every expert record receives one of three decisions after quality gating.

### 5.1 KEEP

**Meaning:** Record is approved for expert training use.

**Conditions:**
- All global quality requirements are satisfied.
- Domain-specific validation passes.
- Expert score meets `accepted` threshold.
- Expert tier is assigned and justified.
- License is resolved and permitted.
- Duplicate check passes.

**Action:** Promote to training-ready expert layer.

### 5.2 REVIEW

**Meaning:** Record has potential value but requires human review before
training use.

**Conditions:**
- Base quality score is acceptable, but expert-specific score is borderline.
- Verification evidence is weak or missing.
- License is likely acceptable but not fully confirmed.
- Duplicate status is ambiguous.
- Domain-specific check raises concern but does not clearly fail.
- Tier assignment is uncertain.

**Action:** Send to human review queue with specific flags indicating what
must be resolved.

### 5.3 REJECT

**Meaning:** Record is unsuitable for 300M expert training.

**Conditions:**
- Any hard global failure:
  - unknown license without exception
  - missing provenance
  - schema incomplete
  - correctness failure
- Domain-specific hard failure:
  - code correctness failure
  - math invalidity
  - factual inaccuracy in AI/ML
- Expert score meets `reject` threshold.
- Record is an exact duplicate of a higher-quality record.

**Action:** Exclude from expert training layer. Log reason for audit.

---

## 6. Recommended Implementation Order

The following order is recommended for coding the quality gate.

### Phase 1: Global hard gates
Implement first because they are prerequisites for everything else.
- Provenance validation
- License validation
- Schema completeness
- Exact duplicate detection

### Phase 2: Base quality integration
Reuse existing `quality_score.py` and calibration framework.
- Import base quality score
- Apply base quality reject/accept thresholds
- Route low-confidence records to `REVIEW`

### Phase 3: Expert scoring dimensions
Add the six expert-specific dimensions.
- correctness
- difficulty
- reasoning_depth
- explanation_quality
- provenance_confidence
- uniqueness

### Phase 4: Domain-specific validators
Implement per-domain checks as pluggable modules.
- Software Engineering validator
- AI/ML validator
- Mathematics validator
- Future: Science, System Engineering

### Phase 5: Expert tier assignment
Implement E1/E2/E3 assignment rules.
- Start with source-led tier assignment
- Add content-based override for mixed sources

### Phase 6: Calibration and thresholds
Run expert calibration using human review.
- Define exact numeric thresholds for `reject`, `accepted`, `gold`
- Validate against pilot expert data
- Adjust weights and thresholds based on human agreement

### Phase 7: Integration with review queue
Connect quality gate outputs to existing Atlas review workflow.
- `KEEP` -> eligible for training view generation
- `REVIEW` -> review queue with expert-specific flags
- `REJECT` -> audit log with reason

## Out of Scope

- Model training
- Release or Hugging Face publication
- Any operation that modifies `raw/`, `curated/`, or training outputs
