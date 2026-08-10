# Sprint 5B.6 — M2' Controlled Experiment: Final Summary

**Date:** 2026-08-09  
**Status:** DESIGN COMPLETE — awaiting Technical Lead approval

---

## 1. Deliverables

| # | Artifact | Path | Status |
|---|----------|------|--------|
| 1 | M2' Design Document | `docs/reports/sprint_5b6_m2prime_design.md` | ✅ |
| 2 | M2' Manifest | `experiments/lora_pilot_math_m2prime_v0.1/m2prime_manifest.json` | ✅ |
| 3 | Provenance Report | `docs/reports/sprint_5b6_m2prime_provenance.md` | ✅ |
| 4 | Exposure Comparison | `docs/reports/sprint_5b6_m2prime_exposure_comparison.md` | ✅ |
| 5 | Leakage Audit | `docs/reports/sprint_5b6_m2prime_leakage_audit.md` | ✅ |
| 6 | Difficulty Comparison | `docs/reports/sprint_5b6_m2prime_difficulty_comparison.md` | ✅ |
| 7 | SHA-256 Hashes | See manifest | ✅ |
| 8 | Training Config Recommendation | See design doc §3 | ✅ |

---

## 2. Key Results

### M2' Construction

| Metric | Value |
|--------|-------|
| Source pool | M2 (131 records) |
| Eval overlap excluded | 13 records |
| **M2' size** | **118 records** |
| M1 ⊆ M2' | Yes (117 of 118) |
| M2' \ M1 | 1 record (`expert_math_000761`) |

### Checksums

| Artifact | SHA-256 |
|----------|---------|
| M2' staged file | `7dfa81114f4096286415a672830f6ff334cc95066080fd9f5267e86d0e413dda` |
| M2' records (sorted JSON) | `734e71f45f7c33e672dc977e5d0e71d57cec40dfbf36f0667c03513cd8de435e` |
| M1 staged file (reference) | `6aecc2a754c1a4aec941a9dbb59136445cf04175a0ae02c158e86acd4e4a4572` |

### Leakage Audit

| Set | Eval Overlap | Status |
|-----|--------------|--------|
| M1 | 0 | ✅ CLEAN |
| M2' | 0 | ✅ CLEAN |
| M2 (original) | 13 | ❌ CONTAMINATED |

### Exposure Comparison

| Set | Records | Examples | Avg Presentations |
|-----|---------|----------|-------------------|
| M1 | 117 | 480 | 4.10 |
| M2' | 118 | 480 | 4.07 |
| M2 (original) | 131 | 480 | 3.66 |

M2' exposure matches M1 within 0.85%. Original M2 had 12% lower exposure.

### Difficulty Distribution

| Difficulty | M1 | M2' | Delta |
|------------|----|-----|-------|
| 2 | 100 | 101 | +1 |
| 3 | 17 | 17 | 0 |
| 4 | 0 | 0 | 0 |

Virtually identical.

---

## 3. Controlled Comparison Matrix

| Variable | M1 | M2' | Matched? |
|----------|----|-----|----------|
| Base model | Qwen2.5-7B-Instruct | Qwen2.5-7B-Instruct | ✅ |
| Model revision | a09a3545... | a09a3545... | ✅ |
| LoRA r/α/dropout | 8/16/0.05 | 8/16/0.05 | ✅ |
| Max steps | 60 | 60 | ✅ |
| Batch × accum | 1 × 8 | 1 × 8 | ✅ |
| Examples consumed | 480 | 480 | ✅ |
| LR / scheduler | 2e-4 cosine | 2e-4 cosine | ✅ |
| Seed | 42 | 42 | ✅ |
| Seq length | 256 | 256 | ✅ |
| Eval set | math_eval_v2 | math_eval_v2 | ✅ |
| Eval leakage | 0 | 0 | ✅ |
| Per-record exposure | 4.10 avg | 4.07 avg | ✅ (0.85% diff) |
| Difficulty distribution | 100+17 | 101+17 | ✅ (near-identical) |
| **Dataset size** | **117** | **118** | **❌ (intentional)** |

**Exactly one variable differs: dataset size (117 vs 118).**

---

## 4. What This Designs For

If M2' outperforms M1, the improvement can be attributed to:
- The additional training record (`expert_math_000761`)
- Slightly more diverse exposure (118 vs 117 unique records)

If M2' underperforms M1, the decline can be attributed to:
- The additional record introducing noise or conflicting patterns
- Diminishing returns at this dataset size

If M2' ≈ M1, this confirms that adding a single record has negligible effect at this scale.

---

## 5. Recommended Next Steps (Pending Approval)

1. **Technical Lead review** of this design document
2. **Approval gate** to proceed to training (separate sprint)
3. **Training execution** on Dev PC (RTX 5070 12GB)
4. **Evaluation** using frozen QEE v2 on math_eval_v2
5. **Comparison report** against M1 and baseline

---

## 6. Stop

**No training, evaluation, or code modifications have been performed.**

All artifacts are design/provenance only. Execution requires separate approval.

---

*Summary generated: 2026-08-09*  
*Sprint: 5B.6*  
*Classification: DESIGN ONLY*
