# Atlas Specialist 10K Pilot Extraction Plan v0.1

## Purpose

Define the first real expert data pilot before any model training: extract,
convert, and validate 6,500 expert records (Option A) from the three
GO-calibrated sources. This document is **planning only**:

- no ingestion
- no downloads
- no training
- no dataset release

## Compatibility

This plan is designed to be compatible with:

- `docs/expert_pilot_plan_v0.1.md`
- `docs/expert_pilot_sample_calibration_plan_v0.1.md`
- `docs/expert_record_schema_v0.1.md`
- `docs/expert_quality_gate_v0.1.md`
- `docs/expert_extraction_runbook_v0.1.md`
- `docs/specialist_model_data_strategy_v0.1.md`
- `docs/specialist_training_budget_v0.1.md`
- `metadata/expert_source_registry_v0.1.json`
- Calibration reports:
  - `reports/expert_pilot_sample_calibration_swe_v0.2.json` (GO)
  - `reports/expert_pilot_sample_calibration_arxiv_v0.1.json` (GO)
  - `reports/expert_pilot_sample_calibration_openmath_v0.1.json` (GO)

## GO Source Capacity (measured, not estimated)

| Source | Domain | License | Verified capacity | Calibration result |
|--------|--------|---------|-------------------|--------------------|
| SWE-bench Verified (expert-swe-001) | software_engineering | MIT | **500 instances** (HF test split, measured) | schema pass 1.0, KEEP 100/100, dup 0.0 |
| OpenMathInstruct-2 (expert-math-002) | mathematics | CC-BY-4.0 | **13,972,791 train** (HF API splits, measured) | schema pass 1.0, KEEP 100/100, dup 0.0 |
| ArXiv cs.LG/CL/AI/stat.ML (expert-aiml-001) | ai_machine_learning | arXiv non-exclusive | **effectively unlimited** abstracts | schema pass 1.0, KEEP 12/12, dup 0.0 |

**Capacity constraint (measured):** SWE-bench Verified contains exactly 500
instances. The originally requested 4,000 SE target **cannot be met from GO
sources alone** (1:1 instance-to-record conversion, no synthetic expansion in
scope). **Resolution: Option A selected (Section 2)** — the pilot runs at
6,500 records using the full measured SWE-bench Verified capacity; no SE
expansion is fabricated.

---

## 1. Pilot Objective

Validate the full expert extraction pipeline end-to-end at 6,500-record scale:

1. **Extraction** — pull records from each GO source with stable provenance.
2. **Schema conversion** — map to Atlas Expert Record Schema v0.1 with 100%
   required-field completeness.
3. **Quality gate** — license, duplicate, correctness, reasoning, provenance
   checks pass at production thresholds.
4. **Provenance** — every record carries source, license, original_id,
   transformations, verification.
5. **Difficulty assignment** — difficulty 1-5 per record (documented
   heuristic or source label; classifier version recorded).
6. **E1/E2/E3 classification** — per-record tier assigned from source and
   content characteristics.

Secondary objectives:

- Produce a human review sample for gate calibration.
- Produce the pilot decision report (GO / HOLD / STOP) for the 10K → full
  acquisition transition.

---

## 2. Target Composition

**Decision: Option A — SELECTED.**

Pilot total: **6,500 records**. No fabricated SE expansion: SWE-bench Verified
measured capacity is 500 instances, and the pilot objective is **pipeline
validation, not target quantity**.

| Domain | Records | GO source | Source capacity | Feasible |
|--------|---------|-----------|-----------------|----------|
| Software Engineering | 500 | SWE-bench Verified | 500 instances | YES — full capacity |
| Mathematics | 3,000 | OpenMathInstruct-2 | 13.97M | YES |
| AI/ML | 3,000 | ArXiv | effectively unlimited | YES |
| **Total** | **6,500** | | | **YES** |

### Decision record

- **Option A (SELECTED):** 500 SWE + 3,000 Math + 3,000 AI/ML = **6,500
  records**. Rationale: uses full measured SWE-bench Verified capacity; does
  not fabricate SE expansion; pilot validates the pipeline at a meaningful
  but honest scale.
- Option B (hold SE, 6,000): rejected — SWE-bench Verified is a GO source
  with full 500-instance capacity available; no reason to exclude it.
- Option C (10,000 as originally requested): rejected — would require a new
  GO SE source first; out of scope, no unverified sources.

The 10K label in this plan's filename refers to the pilot program phase
(per `docs/expert_pilot_plan_v0.1.md`), not the executed record count.
Executed target is 6,500.

| Domain | Records | Source(s) | E1/E2/E3 split (target) |
|--------|---------|-----------|--------------------------|
| Software Engineering | 500 | SWE-bench Verified | E2 100% (verified issue-to-patch) |
| Mathematics | 3,000 | OpenMathInstruct-2 | E1 40% / E2 50% / E3 10% |
| AI/ML | 3,000 | ArXiv | E1 80% / E2 15% / E3 5% |
| **Total** | **6,500** | | global ~E1 55% / E2 38% / E3 7% |

---

## 3. Per-Source Transformation Rules

### 3.1 SWE-bench Verified (software_engineering, MIT)

**Input (per instance):**
`instance_id`, `problem_statement`, `patch`, `test_patch`, `repo`,
`base_commit`, `FAIL_TO_PASS`, `PASS_TO_PASS`, `difficulty` (time-label),
`created_at`, `version`, `hints_text`, `environment_setup_commit`.

**Processing:**
1. Stream `SWE-bench/SWE-bench_Verified` test split; take all 500 instances.
2. Parse `FAIL_TO_PASS` / `PASS_TO_PASS` (JSON-encoded strings in this
   revision).
3. Map difficulty time-label → Atlas 1-5 scale (documented mapping, as in
   calibration).
4. Build `context` = repo, base_commit, files touched, failing tests.
5. Set verification: method `gold_patch`, status `verified`, evidence
   `FAIL_TO_PASS=n, PASS_TO_PASS=m`.
6. E2 tier; `metadata.subdomains` = debugging, patch-generation, repo name.

**Atlas expert record output:**
`domain=software_engineering`, `expert_tier=E2`, `type=qa`,
`problem=problem_statement`, `solution=patch`,
`verification.gold_patch/verified`, `provenance.original_id=instance_id`,
`metadata.model_generated=false`.

### 3.2 OpenMathInstruct-2 (mathematics, CC-BY-4.0)

**Input (per row):**
`problem`, `generated_solution`, `expected_answer`, `problem_source`.

**Processing:**
1. Stream `nvidia/OpenMathInstruct-2` train split; iterate until 3,000
   records pass the quality gate.
2. `model_generated=true` (solutions generated by Llama3.1-405B-Instruct —
   measured from NVIDIA README).
3. Difficulty from problem length heuristic (documented).
4. `context` = problem_source + expected_answer.
5. Verification: method `verified_solution_set`, status `needs_review`,
   evidence `problem_source=…; expected_answer_present=…` (no execution
   check in pilot; expected_answer provides checkable target).
6. E1/E2/E3 by problem_source and content (target E1 40% / E2 50% / E3 10%).

**Atlas expert record output:**
`domain=mathematics`, `expert_tier=E1/E2/E3`, `type=qa`,
`problem=problem`, `solution=generated_solution`,
`metadata.synthetic=true`, `metadata.model_generated=true`.

### 3.3 ArXiv cs.LG / cs.CL / cs.AI / stat.ML (ai_machine_learning)

**Input (per paper):**
arXiv id, title, authors, abstract, categories (primary + all), published,
updated, comment, doi, journal_ref; abs-page retraction check.

**Processing:**
1. Query arXiv API per primary category (newest-first), filter
   `primary_category`, dedupe by arXiv id.
2. Abstract-only extraction (no full-text ingestion, per plan).
3. Check abs page for retraction/correction markers; exclude marked papers.
4. Derive problem = concept-explanation prompt from title/abstract
   (documented template); solution = abstract (author-written, grounded).
5. Verification: method `peer_review`, status `needs_review`, evidence
   `arXiv:id; authors; year`.
6. E1 tier (majority); E2/E3 for survey/frontier content (target E1 80%).

**Atlas expert record output:**
`domain=ai_machine_learning`, `expert_tier=E1 (default)`,
`type=reasoning`, `problem=derived prompt`, `solution=abstract`,
`provenance.original_id=arXiv id`, `metadata.model_generated=false`.

---

## 4. Quality Gates

Every record must pass all gates before inclusion. Gates reuse the
calibration heuristics (deterministic, no LLM) plus human review sample.

| Gate | Check | Pass condition |
|------|-------|----------------|
| License | record + source license | permissive only (MIT, Apache-2.0, CC-BY-4.0, arXiv non-exclusive); **no NC/restricted/unknown** |
| Duplicate | exact id + near-dup normalized problem+solution hash | 0 exact dups; near-dup rate ≤ 0.01 |
| Correctness | verification evidence; expected answer presence | verified or needs_review with evidence; correctness score ≥ 3 |
| Reasoning quality | reasoning_depth ≥ 3; explanation_quality ≥ 3 | score-based (calibration heuristic) |
| Provenance | source, license, original_id, transformations, verification | 100% completeness |
| Security (hard gate) | keys, tokens, credential paths | 0 flags |

Gate classification (per quality gate v0.1):

- **REJECT** — schema failure, license failure, correctness ≤ 2,
  provenance_confidence ≤ 1, or security flag.
- **KEEP** — passes all gates, correctness ≥ 3, provenance_confidence ≥ 3.
- **REVIEW** — otherwise; routed to human review sample.

---

## 5. Expected Artifacts

| Artifact | Path (proposed) | Content |
|----------|-----------------|---------|
| Pilot manifest | `metadata/expert_pilot_6500_manifest_v0.1.json` | source list, counts (500/3,000/3,000), versions, hashes, timestamps |
| Converted dataset | `tmp/expert_pilot_6500_records_v0.1.jsonl` (or curated staging) | all 6,500 Atlas expert records (schema v0.1) |
| Quality report | `reports/expert_pilot_6500_quality_v0.1.json` | schema pass, gate distribution, dup rate, provenance, difficulty, tier stats |
| Human review sample | `review/expert_pilot_6500_review_sample_v0.1.jsonl` | stratified sample (target ~5% ≈ 325 records) for human gate calibration |
| Pilot decision report | `reports/expert_pilot_6500_decision_v0.1.md` | measured metrics + GO/HOLD/STOP recommendation |

No release artifacts, no training views, no HF publish in this phase.

---

## 6. Success Criteria

Thresholds are proposed from the measured calibration baselines (schema
pass 1.0, KEEP ≥ 0.99, dup 0.0 across GO sources) and are subject to
confirmation in the pilot decision report.

### GO (proceed to full acquisition planning)

- Conversion success ≥ 99%
- Schema pass rate ≥ 0.99
- KEEP rate ≥ 0.90 (calibration baseline 0.99-1.0)
- Duplicate rate ≤ 0.01
- Provenance completeness = 100%
- License compliance = 100% (no NC/unknown)
- Security flags = 0
- Human review acceptance ≥ 80% of sampled records
- All three GO sources contribute their committed records: SWE-bench 500,
  OpenMathInstruct-2 3,000, ArXiv 3,000

### HOLD (fix pipeline / adjust plan)

- Conversion 95–99%
- Schema pass 0.95–0.99
- KEEP rate 0.80–0.90
- Duplicate rate 0.01–0.05
- Provenance 95–100%
- Human review acceptance 60–80%
- Or: capacity shortfall > 10% vs committed composition

### STOP (reject pilot outcome)

- Conversion < 95%
- Schema pass < 0.95
- KEEP rate < 0.80
- Duplicate rate > 0.05
- Any NC/unknown license or security flag
- Provenance < 95%
- Human review acceptance < 60%

---

## Constraints

1. **Open-Platypus remains HOLD** — excluded from this pilot; no license
   filtering decision made here.
2. **No training** — pilot output is data only; training pause stands.
3. **No dataset release** — no HF publish, no release bundles.
4. **No unverified sources** — GO sources only; SE capacity limitation is
   explicit (Section 2), not papered over.
5. **No dataset modification** — existing curated/raw artifacts unchanged.

---

## Next Steps (not started; for approval)

1. Target composition **approved (Option A: 6,500 records)** — no further
   composition decision pending.
2. Build the extraction runner per Section 3 rules.
3. Execute pilot; produce Section 5 artifacts.
4. Human review sample calibration; issue pilot decision report.
