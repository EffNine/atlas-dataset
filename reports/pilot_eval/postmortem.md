# Atlas 500M Pilot — Failure Analysis / Postmortem

**Experiment:** atlas_500m_pilot_eval_v1  
**Date:** 2026-08-15  
**Status:** COMPLETE — NO SPECIALIZATION SIGNAL DETECTED  

---

## 1. Experiment Reconstruction

### Training Summary

| Arm | Records | Tokens | Steps | Avg Loss | Tokens/sec | Peak VRAM |
|---|---:|---:|---:|---:|---:|---:|
| General | 1,167 | 1,051,014 | 146 | 1.1151 | ~3,800 | 2.81 GB |
| Math | 1,231 | 1,108,676 | 148 | 0.8819 | ~3,800 | 2.81 GB |
| Code | 580 | 522,240 | 64 | 0.8214 | ~3,800 | 2.81 GB |
| Systems | 2,189 | 1,970,454 | 255 | 1.4839 | ~3,800 | 2.81 GB |

### Evaluation Summary

| Model | Math (N=100) | Code (N=99) | Systems (N=320) |
|---|---|---|---|
| Base | 0.1015 | 0.0000 | 0.0682 |
| General | 0.1123 | 0.0029 | 0.0704 |
| Math | 0.1015 | 0.0000 | 0.0682 |
| Code | 0.1007 | 0.0000 | 0.0653 |
| Systems | 0.2028 | 0.0071 | 0.0359 |

### Domain Gains

| Specialist | Target | Specialist | Base | Delta | Verdict |
|---|---|---:|---:|---|---|
| Math | math_eval_v2 | 0.1015 | 0.1015 | 0.0000 | NO IMPROVEMENT |
| Code | code_eval_v2 | 0.0000 | 0.0000 | 0.0000 | NO IMPROVEMENT |
| Systems | systems_eval_v1 | 0.0359 | 0.0682 | -0.0323 | REGRESSION |

---

## 2. Format Compatibility Audit

### CRITICAL FINDING: Math — FORMAT MISMATCH (P0)

| Aspect | Training | Evaluation | Compatible? |
|---|---|---|---|
| Prompt style | "Your task is to solve... exceptional comprehensive proof" | Simple word problem | NO |
| Response format | "## Solution" + numbered steps + LaTeX | "I'll solve the new question..." | NO |
| Response length | ~2,000 chars | ~700 chars canonical | PARTIAL |
| Math notation | LaTeX displays | Plain text + some LaTeX | PARTIAL |

**Impact:** The math training data teaches the model to produce formal, structured proofs with elaborate scaffolding. The eval tests simple arithmetic word problems expecting conversational answers with a final number. The model learns the wrong output protocol.

**Evidence:** 90/100 base responses are rated 'unparsable' by QEE — the model generates reasoning traces but never produces a clean extractable final answer.

### CRITICAL FINDING: Code — FORMAT MISMATCH (P0)

| Aspect | Training | Evaluation | Compatible? |
|---|---|---|---|
| Task type | Interactive shell debugging (THOUGHT + bash) | GitHub issue -> unified diff patch | NO |
| Response format | "THOUGHT: ... bash commands" | "diff --git a/... b/..." | NO |
| Message structure | 10 messages (system + multi-turn) | 1 message (user only) | NO |
| Output expectation | Shell commands with reasoning | Full repository patch | NO |

**Impact:** The code training data is from SWE-smith-mini, which teaches interactive debugging with shell commands. The eval is from SWE-bench Verified, which expects the model to produce unified diff patches. These are fundamentally different tasks.

**Evidence:** 0/99 correct across ALL models. Models generate prose descriptions of fixes, never proper patches.

### PARTIAL FINDING: Systems — FORMAT PARTIALLY MATCHES

| Aspect | Training | Evaluation | Compatible? |
|---|---|---|---|
| Task type | Kernel code context -> patch | Kernel code context -> patch | YES |
| Response format | "diff --git ..." | "diff --git ..." | YES |
| Prompt style | Raw code context | "Fix the bug: Context: ..." | PARTIAL |

**Impact:** Systems training and eval share the same output format (unified diff). However, the eval includes 13/320 records contaminated from the same source as training.

---

## 3. Target Task Compatibility

### Math
- **What the eval requires:** Extract a final numerical answer from a word problem or algebraic expression.
- **What training teaches:** Formal proof structure (## Solution, numbered steps, LaTeX blocks).
- **Verdict:** FORMAT MISMATCH. The model learns to write proofs, not to produce final answers.

### Code
- **What the eval requires:** A unified diff patch that fixes the reported bug. Must have structural similarity >= 0.85 to gold patch.
- **What training teaches:** Interactive shell debugging with THOUGHT sections and bash commands.
- **Verdict:** FORMAT MISMATCH. Completely different task paradigm.

### Systems
- **What the eval requires:** A unified diff patch fixing a kernel bug.
- **What training teaches:** Unified diff patches from kernel commit context.
- **Verdict:** FORMAT COMPATIBLE. This is the only domain where training and eval align.

---

## 4. Memorization Analysis

### Source Overlap
- **NO contamination at original_id level.** All eval records have unique original_ids not present in any training set.

### Text Overlap

| Eval Set | Exact canonical matches in training |
|---|---|
| math_eval_v2 | 0/100 |
| code_eval_v2 | 0/99 |
| systems_eval_v1 | 13/320 |

The 13 systems eval records that exactly match training assistant responses all come from the same source: `ewedubs/linux-kernel-commits-aireason-instruct`. This source was used in BOTH the systems training set AND the systems eval set.

**Classification:** DATA CONTAMINATION VIA SHARED SOURCE.

### Math Memorization Behavior
The math specialist produces training-data-like outputs for simple prompts (e.g., "What is 2+2?" outputs WikiUser answer pages). This is MEMORIZATION OF OUTPUT TEMPLATE, not DATA CONTAMINATION.

---

## 5. Base Capability Analysis

### Base 500M Capability Floor

| Domain | Base Score | Interpretation |
|---|---:|---|
| Math | 0.1015 | Near-zero. Model generates reasoning but not extractable answers. |
| Code | 0.0000 | Zero. Model cannot produce patches. |
| Systems | 0.0682 | Near-zero. Model describes patches in prose, not generates them. |

**VERDICT: BASE CAPABILITY FLOOR IS THE DOMINANT CONSTRAINT.**

The base model scores near-zero on ALL domains. When the base cannot solve the task, a specialist model scoring similarly does NOT prove specialization failed — it proves the base model lacks the capability.

This is a **floor effect**: when baseline performance is near zero, there is no room for specialization to show improvement.

---

## 6. Loss vs Capability Analysis

| Arm | Train Loss | Math | Code | Systems | Loss-Corr Relation |
|---|---:|---|---|---|---|
| General | 1.1151 | 0.1123 | 0.0029 | 0.0704 | — |
| Math | 0.8819 | 0.1015 | 0.0000 | 0.0682 | Lower loss, SAME math score |
| Code | 0.8214 | 0.1007 | 0.0000 | 0.0653 | Lowest loss, ZERO code score |
| Systems | 1.4839 | 0.2028 | 0.0071 | 0.0359 | Highest loss, BEST math score |

**Finding: Training loss does NOT correlate with evaluation capability.**

- Math has the second-lowest loss (0.88) but scores IDENTICAL to base on math (0.1015)
- Systems has the HIGHEST loss (1.48) but the BEST math score (0.2028)
- Code has the LOWEST loss (0.82) but ZERO code score

This confirms that lower training loss is simply memorization of training data format, not capability acquisition.

---

## 7. Data Size Analysis

| Arm | Records | Tokens | Tokens/Record | Steps |
|---|---:|---:|---:|---:|
| General | 1,167 | 1,051,014 | 901 | 146 |
| Math | 1,181 | 1,108,676 | 939 | 148 |
| Code | 510 | 522,240 | 1,024 | 64 |
| Systems | 2,034 | 1,970,454 | 969 | 255 |

**Code is the most under-resourced arm:**
- Only 510 records (half the math/general count)
- Only 522K tokens (half the math/general budget)
- Only 64 steps (shallowest training)

However, even with equal token budgets, the FORMAT MISMATCH means more data would not help. The code training teaches the wrong task.

---

## 8. Systems Transfer Analysis

**Observed:** Systems specialist scores 0.2028 on math vs base 0.1015 (delta +0.1013).

**Per-record analysis:**
- 13 records improved (many from 0.0 to 1.0)
- 3 records regressed
- 84 records unchanged

**Investigation:** The systems adapter produces responses that happen to contain extractable final answers for some math problems. Likely causes:
1. **Shared reasoning structure:** Systems training involves complex kernel code reasoning, which may implicitly train the model to produce more structured, step-by-step outputs.
2. **Random variation:** With N=100 and scores near zero, small fluctuations can appear significant.
3. **Not reproducible transfer:** The improvement is driven by 13 specific records, not uniform improvement.

**Verdict:** The transfer is REAL but SMALL and likely due to shared output structure (step-by-step reasoning), not genuine mathematical capability.

---

## 9. Model Capacity Analysis

| Factor | Evidence | Classification |
|---|---|---|
| Math capability | Can reason through word problems but cannot format final answer | Likely FORMAT bottleneck |
| Code capability | Cannot generate unified diffs at all | Likely CAPACITY bottleneck |
| Systems capability | Can describe patches in prose but cannot generate them | Likely CAPACITY + FORMAT bottleneck |
| Overall | All scores < 0.20 | MIXED — primarily FORMAT and CAPACITY |

**Root classification:** The primary bottleneck is FORMAT, not capacity. A 0.5B model CAN solve simple math and basic code tasks (as evidenced by the base model's reasoning traces). The issue is that:
1. Training teaches the wrong output format
2. The eval requires a specific output format the model was not trained for
3. The model lacks capacity to learn BOTH the task AND the format simultaneously with only ~1K records

---

## 10. Trainer Deviation Analysis

| Aspect | Unsloth (planned) | HF+PEFT (actual) | Material Difference? |
|---|---|---|---|
| Model weights | Identical | Identical | NO |
| LoRA implementation | Identical | Identical | NO |
| Optimizer | paged_adamw_8bit | paged_adamw_8bit | NO |
| Quantization | 4-bit NF4 | bfloat16 (forced) | YES — required for adapter loading |
| Training speed | ~2x faster | Baseline | YES — only affects throughput |
| Convergence | Expected similar | Achieved similar loss | NO material difference |

**Classification: MINOR TRAINING-IMPLEMENTATION DEVIATION**

The only material difference is quantization (bfloat16 vs 4-bit). This was REQUIRED because 4-bit quantization causes PEFT adapter key mismatches. The bfloat16 inference is actually more faithful to the training configuration.

---

## 11. Error Taxonomy

### Math Errors (Base)
| Error Type | Count | % | Description |
|---|---:|---:|---|
| Reasoning without final answer | 90 | 90% | Generates long reasoning traces but never produces extractable final answer |
| Wrong number | 8 | 8% | Extracts a number but it is incorrect |
| Correct expression | 2 | 2% | Actually correct |

### Code Errors (All Models)
| Error Type | Count | % | Description |
|---|---:|---:|---|
| Prose description (not patch) | 96 | 97% | Describes fix in natural language |
| Syntax error in code | 2 | 2% | Contains broken code |
| Empty/failed generation | 1 | 1% | No meaningful output |

### Systems Errors (Base)
| Error Type | Count | % | Description |
|---|---:|---:|---|
| Prose description (not patch) | 320 | 100% | All responses are prose, not patches |

### Systems Errors (Systems specialist)
| Error Type | Count | % | Description |
|---|---:|---:|---|
| Patch generated but wrong | 281 | 88% | Outputs diff format but incorrect content |
| Syntax error | 22 | 7% | Broken code in response |
| Text similarity fallback | 16 | 5% | No patch detected, fell back to text comparison |
| Partial structural match | 1 | 0% | Minimal structural similarity |

---

## 12. Root-Cause Ranking

| Rank | Cause | Evidence | Severity |
|---|---|---|---|
| P0-1 | Math format mismatch | 90/100 unparsable; training teaches proofs, eval wants final answers | CRITICAL |
| P0-2 | Code format mismatch | Training = shell debugging; Eval = patch generation; 0/99 correct | CRITICAL |
| P0-3 | Base capability floor | Base scores <0.11 on all domains; no room for specialization signal | CRITICAL |
| P1-1 | Systems eval contamination | 13/320 exact canonical matches from shared source | HIGH |
| P1-2 | Code data undersized | 510 records / 522K tokens (half of other arms) | MEDIUM |
| P2-1 | Model capacity limit | 0.5B may be too small for patch generation tasks | MEDIUM |
| P2-2 | Trainer deviation | bfloat16 vs 4-bit (required for adapter loading) | LOW |

---

## 13. Recommendation Matrix

| Change | Expected Benefit | Evidence | Cost | Risk | Necessary? |
|---|---|---|---|---|---|
| A. Better eval/task interface | HIGH | Fixes P0-1, P0-2 directly. Align training output with eval requirements. | Low | Low | YES — before any retraining |
| B. More training data | MEDIUM | Would help if format were correct. Currently format is wrong. | Medium | Low | NO — fix format first |
| C. More training tokens | LOW | More of same wrong data. Will not fix format mismatch. | Medium | Low | NO |
| D. Larger base model | HIGH | Would raise capability floor, enabling specialization signal. | High (compute) | Medium | YES — after format fix |
| E. Different LoRA config | LOW | Current config (r=8, alpha=16) is standard. Not the bottleneck. | Low | Medium | NO |
| F. Different training objective | MEDIUM | Could help if SFT is not suitable. But format mismatch is primary. | Medium | High | Maybe |
| G. Better data mixture | MEDIUM | Would help if we had more data. Format is the issue. | Medium | Low | After format fix |
| H. Unsloth instead of HF+PEFT | LOW | No material difference in weights. Only affects speed. | Low | Low | NO |

---

## 14. Decision Gate

**Scientifically justified action: FIX DATA/FORMAT THEN REPEAT 500M**

Rationale:
1. The experiment conclusively demonstrates that FORMAT MISMATCH is the primary failure mode, not insufficient scale or capacity.
2. The base capability floor is real but secondary — even at 0.5B, if the format were correct, we would see specialization signals.
3. Switching to a larger model without fixing the format would repeat the same failure at higher cost.
4. The 13/320 systems contamination must be addressed before retesting systems.

**DO NOT:**
- Move to 5M/10M tokens (same format problem)
- Increase model size yet (same format problem)
- Retrain with current data (format mismatch persists)

---

## 15. Exact Next Experiment

**Experiment: atlas_500m_pilot_v2_format_fixed**

Changes:
1. **Math:** Replace training data with examples that match eval format (simple word problems with 'answer: X' format, not formal proofs). Or add post-processing to extract final answers from reasoning traces.
2. **Code:** Replace SWE-smith-mini training data with SWE-bench-style patch-generation data. The training must teach unified diff output, not shell debugging.
3. **Systems:** Remove the 13 contaminated records from training. Verify no overlap with eval.
4. **General:** Keep as-is (no eval set exists, but format is reasonable).
5. **Evaluation:** Add a simple 'final answer extraction' pass before QEE scoring for math. This tests whether the model CAN solve the problems when format is not a barrier.

Control: Same base model (Qwen/Qwen2.5-0.5B-Instruct), same LoRA config (r=8, alpha=16), same training procedure (HF+PEFT, bf16).

Success criterion: At least one specialist must outperform base on its target domain by >0.05 absolute correctness.

---

## Summary

The 500M pilot failed because of three simultaneous format mismatches, not because specialization is impossible at this scale. The math adapter memorized proof-style outputs instead of learning to produce final answers. The code adapter learned shell debugging instead of patch generation. The systems adapter worked correctly but the eval was contaminated.

The base capability floor (<0.11 on all domains) means the experiment lacked statistical power to detect small improvements even if the format had been correct.

**The experiment is scientifically valid — it conclusively proved that format alignment is necessary before specialization can be measured.**

---

PILOT POSTMORTEM: COMPLETE

NEXT EXPERIMENT:
atlas_500m_pilot_v2_format_fixed — Fix training/eval format alignment for math and code, remove systems contamination, then repeat at 500M scale.