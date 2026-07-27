# Training Pipeline Readiness Report

> Phase 4C.0 — Architecture Consolidation & Dependency Unification
> Generated: 2026-07-28

Evaluates whether Atlas is ready for each major training paradigm. This is a readiness assessment, not an execution plan.

---

## Dataset State Summary

| Metric | Current Value | Source |
|--------|--------------|--------|
| **Total curated records** | 263 (v0.1) + 0 (v0.2 same 263) | `metadata/release_index.json` |
| **Target** | 1000 (v0.1 target) | `metadata/acquisition_manifest_v0.1.json` |
| **Progress** | 26.3% of target | 263/1000 |
| **Review coverage** | 0% reviewed (all pending) | `review_queue/pending.jsonl` |
| **Approved records** | 0 | `review_queue/approved.jsonl` |
| **Quality score range** | All scored 7 (fixed) | Inline scoring in pilot |
| **Lifecycle state** | All records: `curated` | `metadata/lifecycle_state.json` |
| **Release gates passed** | v0.1: ❌, v0.2: ❌ | `metadata/release_index.json` (both `gates_passed: false`) |
| **Calibration completed** | ✅ Calibration baseline exists | `metadata/calibration_baseline_v0.1.json` |
| **Training views** | Placeholders only | `training_views/{qwen,llama,deepseek}/README.md` |

---

## Dimension 1: Dataset Quality

### Score: **5/10**

### Strengths
- Schema validation passes for all 263 records
- All records have the required knowledge-object superset fields
- License gate passes (no NC/ND/proprietary/unknown)
- Source lineage is tracked per record

### Weaknesses
- **All records scored a flat 7.0** — the original pilot ingestion used `q = int(rec.get("quality_score", 0)); q = max(0, min(10, q))` which copied the authored score. Since all seed records were authored at 7, there's zero variance. The Quality Evaluation Engine exists but has NOT been run on the dataset to produce meaningful scores.
- **No quality score variance** — impossible to do threshold-based filtering
- **263 records is far below the 1000-target** for statistical meaningfulness
- **No difficulty distribution** — all records have default difficulty=0
- **Knowledge type distribution** unknown — no aggregated report exists

### Readiness Verdict
**Not ready.** The dataset lacks quality score variance, has insufficient records, and has seen zero quality evaluation engine scoring.

---

## Dimension 2: Review Coverage

### Score: **2/10**

### Strengths
- Review infrastructure exists: templates, worksheets, decision files
- Calibration baseline is frozen
- Review assignments exist (`review/operations/review_assignments.json`)

### Weaknesses
- **Zero records have been human-reviewed.** All 263 records are in `pending` status
- Review queue: `pending.jsonl` contains all records; `approved.jsonl`, `rejected.jsonl`, `needs_revision.jsonl` are empty
- **No human approval = no verified records** — `verified` field is `False` on every record
- Release gates check `verification_status` — every record is `pending`, so release gates would fail
- **Release gates already failed** — both v0.1 and v0.2 have `gates_passed: false`

### Readiness Verdict
**Not ready.** Training on unverified data is explicitly against Atlas policy. Human review must reach at least 80% of records before any training can begin.

---

## Dimension 3: Release Maturity

### Score: **4/10**

### Strengths
- Two releases exist (v0.1, v0.2) with hash-chained manifests
- Release management infrastructure is operational
- Semantic diff engine works
- Checksum registries exist

### Weaknesses
- **Both releases have gates_passed: false** — quality_gate and schema_gate failures block both releases
- v0.2 has 263 records (identical to v0.1? — both have 263 total_records)
- No release has been through a successful gate run
- No release has verified training data (approved records)
- Release statistics exist but aren't validated against ground truth

### Readiness Verdict
**Not ready.** No release has passed its gates. Training can only proceed from a gate-passing release.

---

## Dimension 4: Training Readiness Per Paradigm

| Paradigm | Ready? | Blockers |
|----------|--------|----------|
| **SFT** | ❌ | No approved records, <1000 records, no score variance |
| **LoRA** | ❌ | Same as SFT |
| **QLoRA** | ❌ | Same as SFT (config exists but data isn't ready) |
| **Full Fine-Tuning** | ❌ | Same as SFT + risk of overfitting on 263 records |
| **DPO** | ❌ | DPO requires preference pairs; Atlas has no preference data |
| **Knowledge Distillation** | ❌ | Requires a teacher model + student; Atlas dataset alone cannot support distillation |
| **RAG Indexing** | ⚠️ Partial | RAG can work with unverified data, but quality is unknown. Indexing pipeline doesn't exist. |
| **Pre-training** | ❌ | Totally out of scope — Atlas is an SFT/instruction dataset |

### SFT Readiness Details

**Required conditions for SFT:**
1. ✅ Canonical schema with messages array (system/user/assistant)
2. ✅ Format converters exist (6 formats, config-driven)
3. ❌ **1000+ verified records** — currently 263 unverified
4. ❌ **Human review complete** — 0%
5. ❌ **Quality scores > 7** — no scores computed
6. ❌ **Release gates passed** — both releases failed
7. ✅ Training config template exists (`qlora_qwen3_8b.yaml`)
8. ✅ Model-agnostic data pipeline

### LoRA / QLoRA Readiness

**Additional conditions:**
- ✅ LoRA target modules specified in config
- ✅ QLoRA quantization params defined (4-bit NF4, BF16)
- ❌ **No adapter has been trained** — training is paused by mandate
- ❌ **No evaluation benchmarks** — `evaluation/benchmarks/` and `evaluation/test_sets/` have no usable content

---

## Dimension 5: Expected Blocker List

| Blocker | Impact | Resolution Required | Estimated Effort |
|---------|--------|-------------------|------------------|
| **0 records approved** | Blocks all training paradigms | Human review of ≥200 records | 10–20 person-hours |
| **Flat quality scores (all 7)** | Blocks quality-based filtering | Run QEE on all records; establish variance | 0.5 day (automated) |
| **Insufficient volume (263/1000)** | Models underfit; eval not meaningful | Continue expansion to 1000+ | Depends on data availability |
| **Release gates not passing** | No valid release to train from | Fix gate failures (schema, quality, balance) | 1–2 days |
| **No evaluation benchmarks** | Cannot measure training impact | Populate `evaluation/benchmarks/` with standard evals | 0.5 day |
| **No training view generated** | Cannot train from canonical JSONL directly | Run `convert_format.py` after records approved | 0.25 day |
| **Training paused by mandate** | No training can occur regardless of data readiness | Policy decision | N/A |

---

## Dimension 6: Pipeline Readiness Score Summary

| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Dataset Quality | 5 | 30% | 1.5 |
| Review Coverage | 2 | 25% | 0.5 |
| Release Maturity | 4 | 20% | 0.8 |
| Training Infrastructure | 6 | 15% | 0.9 |
| Evaluation Readiness | 2 | 10% | 0.2 |

**Overall Pipeline Readiness: 3.9 / 10**

---

## Recommendations

### Immediate (unblock automated scoring)
1. **Run Quality Evaluation Engine** on all curated records to replace flat scores with variance
2. **Generate a quality distribution report** (min, max, avg, per-category)

### Short-term (unblock review)
3. **Begin human review** starting with highest-confidence records
4. **Establish a review velocity target** (e.g., 50 records/week)

### Medium-term (unblock release)
5. **Run release gates** after review completes on ≥200 records
6. **Fix any gate failures** — likely schema_gate enum mismatches
7. **Generate a valid release** with `gates_passed: true`

### Training-ready triggers
- [ ] ≥800 records approved (verification_status=approved)
- [ ] Release gate run passes all 7 gates
- [ ] Release has `gates_passed: true`
- [ ] Quality scores have meaningful variance (stddev > 0.5)
- [ ] Training view generated for target model
- [ ] Evaluation benchmarks populated
- [ ] Training config reviewed and adapted for target model (not just Qwen3)

**Do not train until all 7 triggers are met.**

---

## Appendix: Training Configs Reference

| Config | File | Purpose | Status |
|--------|------|---------|--------|
| Qwen3-8B QLoRA | `configs/training/qlora_qwen3_8b.yaml` | Reference config | ✅ Template ready, ❌ Paused |
| Format templates | `configs/formatting/templates.json` | 6 model formats | ✅ Ready |
| Training recipe spec | `docs/specs/training_recipe_spec.md` | Spec for declarative recipes | ✅ Documented |
