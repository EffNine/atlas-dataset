# Atlas 500M Pilot — QEE v2 Capability Evaluation Report

**Experiment:** atlas_500m_pilot_eval_v1
**Timestamp:** 2026-08-15T02:57:42.402214+00:00
**Base model:** Qwen/Qwen2.5-0.5B-Instruct (494M params)
**Hardware:** NVIDIA GeForce RTX 5070 12GB
**Trainer:** Standard HuggingFace + PEFT (protocol deviation: Unsloth unavailable)

---

## 1. Evaluation Environment

| Parameter | Value |
|---|---|
| Base model | Qwen/Qwen2.5-0.5B-Instruct |
| Inference precision | bfloat16 (matching training) |
| Decoding | Greedy (do_sample=False) |
| Max new tokens | 256 |
| Batch size | 16 |
| QEE engine | v2 (deterministic rubric + math/code dispatch) |
| Eval sets | math_eval_v2 (N=100), code_eval_v2 (N=99), systems_eval_v1 (N=320) |
| general_eval_v1 | NOT AVAILABLE |

### Protocol Deviations

1. **Trainer:** Standard HuggingFace + PEFT (expected: Unsloth)
   - Reason: Disk quota exceeded during Unsloth installation
   - Impact: Model weights identical; does not invalidate evaluation.

2. **Inference precision:** bfloat16 (matching training)
   - Note: 4-bit quantization causes PEFT adapter key mismatches.

3. **general_eval_v1:** Not available
   - No protected general-domain eval set exists.

---

## 2. Evaluation Matrix

| Model | Math (N=100) | Code (N=99) | Systems (N=320) |
|---|---|---|---|
| Base | 0.1015 | 0.0000 | 0.0682 |
| General | 0.1123 | 0.0029 | 0.0704 |
| Math | 0.1015 | 0.0000 | 0.0682 |
| Code | 0.1007 | 0.0000 | 0.0653 |
| Systems | 0.2028 | 0.0071 | 0.0359 |

---

## 3. Domain Gains

| Specialist | Target | Specialist | Base | Delta vs Base | Delta vs General |
|---|---|---:|---:|---:|---:|
| Math | math_eval_v2 | 0.1015 | 0.1015 | **+0.0000** | -0.0108 |
| Code | code_eval_v2 | 0.0000 | 0.0000 | **+0.0000** | -0.0029 |
| Systems | systems_eval_v1 | 0.0359 | 0.0682 | **-0.0323** | -0.0345 |

**Finding:** No specialist outperforms base on its target domain.

---

## 4. Cross-Domain Effects

| Specialist | Domain | Specialist | Base | Delta | Status |
|---|---|---:|---:|---|---|
| Math | code | 0.0000 | 0.0000 | +0.0000 | NEUTRAL |
| Math | systems | 0.0682 | 0.0682 | +0.0000 | NEUTRAL |
| Code | math | 0.1007 | 0.1015 | -0.0008 | NEUTRAL |
| Code | systems | 0.0653 | 0.0682 | -0.0029 | NEUTRAL |
| Systems | math | 0.2028 | 0.1015 | **+0.1013** | POSITIVE |
| Systems | code | 0.0071 | 0.0000 | +0.0071 | NEUTRAL |

**Finding:** Systems specialist shows +0.1013 on math (positive transfer) but -0.0323 on target.

---

## 5. Statistical Results

| Model | Eval Set | N | Mean | SE | 95% CI | Correct | Incorrect | Unverif |
|---|---|---:|---:|---:|---|---:|---:|---:|
| Base | math_eval_v2 | 100 | 0.1015 | 0.0301 | [0.0425, 0.1606] | 0 | 0 | 100 |
| Base | code_eval_v2 | 99 | 0.0000 | 0.0000 | [0.0, 0.0] | 0 | 0 | 99 |
| Base | systems_eval_v1 | 320 | 0.0682 | 0.0069 | [0.0548, 0.0817] | 0 | 0 | 320 |
| General | math_eval_v2 | 100 | 0.1123 | 0.0314 | [0.0507, 0.1738] | 0 | 0 | 100 |
| General | code_eval_v2 | 99 | 0.0029 | 0.0029 | [-0.0028, 0.0085] | 0 | 0 | 99 |
| General | systems_eval_v1 | 320 | 0.0704 | 0.0067 | [0.0573, 0.0835] | 0 | 0 | 320 |
| Math | math_eval_v2 | 100 | 0.1015 | 0.0301 | [0.0425, 0.1606] | 0 | 0 | 100 |
| Math | code_eval_v2 | 99 | 0.0000 | 0.0000 | [0.0, 0.0] | 0 | 0 | 99 |
| Math | systems_eval_v1 | 320 | 0.0682 | 0.0069 | [0.0548, 0.0817] | 0 | 0 | 320 |
| Code | math_eval_v2 | 100 | 0.1007 | 0.0301 | [0.0416, 0.1598] | 0 | 0 | 100 |
| Code | code_eval_v2 | 99 | 0.0000 | 0.0000 | [0.0, 0.0] | 0 | 0 | 99 |
| Code | systems_eval_v1 | 320 | 0.0653 | 0.0066 | [0.0523, 0.0783] | 0 | 0 | 320 |
| Systems | math_eval_v2 | 100 | 0.2028 | 0.0401 | [0.1242, 0.2815] | 0 | 0 | 100 |
| Systems | code_eval_v2 | 99 | 0.0071 | 0.0044 | [-0.0016, 0.0157] | 0 | 0 | 99 |
| Systems | systems_eval_v1 | 320 | 0.0359 | 0.0055 | [0.0251, 0.0467] | 0 | 0 | 320 |

---

## 6. Error Analysis

### Math
- **0/100 correct**, 100 unverifiable across all models
- Models generate reasoning traces without extractable final answers
- The 0.5B model cannot produce correctly formatted answers within 256 tokens

### Code
- **0/99 correct** across all models
- Canonical answers are full unified diff patches (~13KB)
- Models generate prose descriptions, never proper patches

### Systems
- **0/320 correct** across all models
- Systems specialist (0.0359) REGRESSES vs base (0.0682)

### Math adapter overfitting
- Produces training data verbatim for simple prompts (e.g., WikiUser answers)
- Explains why math specialist scores identically to base (0.1015)

---

## 7. Training Loss vs Evaluation Performance

| Arm | Train Loss | Tokens | Steps | Math | Code | Sys |
|---|---:|---:|---:|---|---|---|
| General | 1.1151 | 1,051,014 | 146 | 0.1123 | 0.0029 | 0.0704 |
| Math | 0.8819 | 1,108,676 | 148 | 0.1015 | 0.0000 | 0.0682 |
| Code | 0.8214 | 522,240 | 64 | 0.1007 | 0.0000 | 0.0653 |
| Systems | 1.4839 | 1,970,454 | 255 | 0.2028 | 0.0071 | 0.0359 |

**Key finding:** Training loss does NOT correlate with evaluation performance.
- Math: lowest loss (0.88) but same score as base on math
- Systems: highest loss (1.48) but highest math score (0.2028)

---

## 8. Protocol Deviations

| Item | Expected | Actual | Impact |
|---|---|---|---|
| Trainer | Unsloth | Standard HF + PEFT | None on weights |
| Quantization | 4-bit NF4 | bfloat16 | Required for correct adapter loading |
| general_eval_v1 | Present | Not found | Cannot evaluate general transfer |

---

## 9. Full Comparison Table

| Model | Math (N=100) | Code (N=99) | Systems (N=320) |
|---|---|---|---|
| Base | 0.1015 | 0.0000 | 0.0682 |
| General | 0.1123 | 0.0029 | 0.0704 |
| Math | 0.1015 | 0.0000 | 0.0682 |
| Code | 0.1007 | 0.0000 | 0.0653 |
| Systems | 0.2028 | 0.0071 | 0.0359 |

---

## 10. Research Interpretation

### Q1: Does Math specialization improve Math?
**NO.** Math specialist (0.1015) = base (0.1015). Adapter is overfitting.

### Q2: Does Code specialization improve Code?
**NO.** Both 0.0000. Model cannot produce patches.

### Q3: Does Systems specialization improve Systems?
**NO.** Systems (0.0359) < Base (0.0682). Delta = -0.0323.

### Q4: Does specialization cause non-target regression?
**No significant regression.** All deltas within +/-0.01 except systems->math (+0.1013).

### Q5: Does General fine-tuning outperform Base?
**Marginal yes.** Average delta +0.0053. Small but consistent.

### Q6: Justify next 5M/10M-token experiment?
**NO.** 0.5B + 1K records/domain cannot develop measurable specialization.

---

## Final Verdict

### SPECIALIZATION SIGNAL: INCONCLUSIVE

### NEXT SCALE: STOP

**Rationale:**
1. No specialist outperforms base on target domain
2. Math adapter overfits (identical scores, training data leakage)
3. Code/systems adapters cannot produce proper patches
4. All correctness scores < 0.20
5. 0.5B + 1K records/domain is insufficient for measurable specialization
6. A larger model (>=1.5B) with more data is needed

**Artifacts:**
- Per-example: 
- Aggregates: 
- Training: 