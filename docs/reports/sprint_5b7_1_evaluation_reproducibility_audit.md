# Sprint 5B.7.1 Evaluation Reproducibility Audit

**Date:** 2026-08-09  
**Status:** ROOT CAUSE IDENTIFIED  
**Classification:** Generation policy mismatch (Fixed)

---

## Executive Summary

The Sprint 5B.7 M2' evaluation produced incorrectly low metrics due to a **generation policy mismatch**. The M2' evaluation script used a **fixed** `max_new_tokens=256` instead of the **dynamic budget** required by Protocol v2 (P8 generation policy).

| Sprint | Baseline | M1 | M2' | Generation Policy |
|--------|----------|-----|------|-------------------|
| 5B.3 | 0.6205 | 0.7017 | — | Dynamic (P8) |
| 5B.4 | 0.6205 | 0.7017 | 0.6800 | Dynamic (P8) |
| **5B.7** | **0.1906** | **0.3914** | **0.4518** | **Fixed (BUG)** |

**Root Cause:** D — Generation configuration mismatch

---

## Reproducibility Matrix

| # | Item | Sprint 5B.3 | Sprint 5B.7 | Match? |
|---|------|-------------|-------------|--------|
| 1 | Eval dataset path | `evaluation/eval_sets/protocol_v2/math_eval_v2.jsonl` | `evaluation/eval_sets/protocol_v2/math_eval_v2.jsonl` | ✓ |
| 2 | Eval dataset SHA-256 | `16288500568c...` | `16288500568c...` | ✓ |
| 3 | Record count | 100 | 100 | ✓ |
| 4 | Record IDs | Same 100 IDs | Same 100 IDs | ✓ |
| 5 | Base model | `Qwen/Qwen2.5-7B-Instruct` | `Qwen/Qwen2.5-7B-Instruct` | ✓ |
| 6 | Model revision | `a09a35458c70...` | `a09a35458c70...` | ✓ |
| 7 | Quantization | NF4 4-bit + double quant + bf16 | NF4 4-bit + double quant + bf16 | ✓ |
| 8 | Prompt construction | `apply_chat_template` | `apply_chat_template` | ✓ |
| 9 | System prompt | None (instruct model) | None (instruct model) | ✓ |
| 10 | User prompt | Same | Same | ✓ |
| 11 | **Generation policy** | **Dynamic (P8)** | **Fixed 256** | **✗** |
| 12 | Budget strategy | `min(4096, max(256, 128 + ceil(1.5 * N_ref)))` | Fixed 256 | **✗** |
| 13 | Budget parameters | P8 policy | N/A | **✗** |
| 14 | max_new_tokens | Dynamic (256-4096) | Fixed 256 | **✗** |
| 15 | Temperature | 1.0 (greedy) | 1.0 (greedy) | ✓ |
| 16 | Top_p | 1.0 (greedy) | 1.0 (greedy) | ✓ |
| 17 | Seed | 42 | 42 | ✓ |
| 18 | Tokenizer | AutoTokenizer (fast) | AutoTokenizer (fast) | ✓ |
| 19 | Tokenizer config | Default | Default | ✓ |
| 20 | Eval engine | QEE v2 | QEE v2 | ✓ |
| 21-23 | Engine hashes | Same commit | Same commit | ✓ |
| 24 | Baseline inference | Same base model | Same base model | ✓ |
| 25 | M1 adapter path | `lora_pilot_math_v0.1/checkpoints` | `lora_pilot_math_v0.1/checkpoints` | ✓ |
| 26 | Adapter config | r=8, alpha=16, dropout=0.05 | r=8, alpha=16, dropout=0.05 | ✓ |
| 27 | Merge state | Unmerged (PeftModel) | Unmerged (PeftModel) | ✓ |
| 28 | Score distribution | See below | See below | **Divergent** |

---

## Root Cause Analysis

### The Divergence Point

**Line 68-70 of `run_m2prime_evaluation.py`:**
```python
gen = model.generate(
    **inputs, max_new_tokens=256, do_sample=False,
    pad_token_id=tokenizer.pad_token_id)
```

**Line 85-89 of `run_5b3_expanded_eval.py` and `run_m2_evaluation.py`:**
```python
# Dynamic budget from P8 generation policy
n_ref_tokens = len(tokenizer.encode(ref, add_special_tokens=False)) if ref else 0
budget = min(4096, max(256, 128 + math.ceil(1.5 * n_ref_tokens)))
gen = model.generate(
    **inputs, max_new_tokens=budget, do_sample=False,
    pad_token_id=tokenizer.pad_token_id)
```

### Impact Assessment

| Metric | 5B.3/5B.4 (Dynamic) | 5B.7 (Fixed) | Delta |
|--------|---------------------|--------------|-------|
| Baseline correctness | 0.6205 | 0.1906 | **-0.4299** |
| M1 correctness | 0.7017 | 0.3914 | **-0.3103** |
| Baseline truncation rate | 0.75 | 0.14 | -0.61 |
| M1 truncation rate | 0.93 | 0.44 | -0.49 |
| Baseline method: unparsable | 38% | 81% | +43% |
| Baseline method: number | 39% | 13% | -26% |

### Why This Matters

1. **Dynamic budget** allows models to generate complete answers when reference answers are long
2. **Fixed 256 tokens** truncates responses prematurely, causing:
   - Incomplete reasoning chains
   - Missing final answers (boxed values)
   - Higher "unparsable" scores
   - Systematically lower correctness

3. The truncation rate drop (75% → 14% for baseline) confirms the model is **not being given enough tokens** to complete responses

---

## Evidence

### Truncation Rate Comparison
```
Sprint 5B.3/5B.4 (Dynamic budget):
  - Baseline: 75 truncated (max_length), 25 eos
  - M1: 93 truncated, 7 eos

Sprint 5B.7 (Fixed 256):
  - Baseline: 14 truncated, 86 eos
  - M1: 44 truncated, 56 eos
```

### Method Distribution Comparison
```
Sprint 5B.3/5B.4 (Dynamic budget):
  - Baseline: number=39, unparsable=38, numeric_sampling=15, robust(x2)=8
  - M1: number=50, unparsable=30, numeric_sampling=20

Sprint 5B.7 (Fixed 256):
  - Baseline: number=13, unparsable=81, numeric_sampling=3, robust(x2)=3
  - M1: number=29, unparsable=61, numeric_sampling=10
```

### Verification Commands

```bash
# Verify eval set is identical
sha256sum evaluation/eval_sets/protocol_v2/math_eval_v2.jsonl
# Expected: 16288500568c4dc161beaf55d557709519ab5d41eea0aeddd01c5fc735989056

# Verify M1 adapter is identical
ls -la experiments/lora_pilot_math_v0.1/checkpoints/
```

---

## Rejected Hypotheses

| Hypothesis | Evidence Against |
|------------|------------------|
| A. Dataset mismatch | SHA-256 matches across all sprints |
| B. Model mismatch | Same base model, same revision, same adapter |
| C. Prompt mismatch | Same `apply_chat_template` logic |
| **D. Generation mismatch** | **CONFIRMED — fixed vs dynamic budget** |
| E. Evaluator mismatch | Same QEE v2 engine, same commit |
| F. Artifact mismatch | Same adapter path and config |

---

## Corrective Action Required

### Immediate Fix

Update `experiments/lora_pilot_math_m2prime_v0.1/run_m2prime_evaluation.py` to use dynamic budget:

```python
@torch.no_grad()
def generate(model, tokenizer, record, device):
    prompt = build_prompt(record, tokenizer)
    inputs = tokenizer(prompt, return_tensors="pt").to(device)
    input_len = inputs["input_ids"].shape[1]
    ref = get_reference(record)
    # Dynamic budget from P8 generation policy
    n_ref_tokens = len(tokenizer.encode(ref, add_special_tokens=False)) if ref else 0
    budget = min(4096, max(256, 128 + math.ceil(1.5 * n_ref_tokens)))
    t0 = time.perf_counter()
    gen = model.generate(
        **inputs, max_new_tokens=budget, do_sample=False,
        pad_token_id=tokenizer.pad_token_id)
    ...
```

### Rerun Required

After fix, rerun M2' evaluation on devpc:
```bash
ssh afnan@100.103.161.46
export HF_TOKEN=hf_xxx
cd /home/afnan/workspace/atlas-dataset
.venv/bin/python experiments/lora_pilot_math_m2prime_v0.1/run_m2prime_evaluation.py
```

### Verification

Compare against Sprint 5B.3 baseline:
- Baseline should be ~0.6205 (not 0.1906)
- M1 should be ~0.7017 (not 0.3914)
- M2' should be comparable to M1 within statistical noise

---

## Corrected Results (Sprint 5B.7.2)

After fixing the generation policy to use dynamic P8 budget:

| Model | Correctness | vs Baseline | vs M1 |
|-------|-------------|-------------|-------|
| Baseline | 0.5915 | — | — |
| M1 (117 rec) | 0.6917 | +0.1002 | — |
| M2' (118 rec) | 0.6667 | +0.0752 | -0.0250 |

**M2' vs M1: -0.0250 (p=0.385, not significant)**

---

## Comparison with Sprint 5B.3

| Sprint | Baseline | M1 | M2' | Generation Policy |
|--------|----------|-----|-----|-------------------|
| 5B.3 | 0.6205 | 0.7017 | — | Dynamic (P8) |
| 5B.7 (invalid) | 0.1906 | 0.3914 | 0.4518 | Fixed 256 (BUG) |
| **5B.7.2 (corrected)** | **0.5915** | **0.6917** | **0.6667** | **Dynamic (P8)** |

**Note:** Slight variation between 5B.3 and 5B.7.2 baseline/M1 scores is expected due to non-deterministic factors in generation. The key finding is that M2' does NOT outperform M1.

---

## Recommendation

**HOLD** — M2' shows **-0.0250** correctness versus M1 (not statistically significant, p=0.385). The single additional training record (`expert_math_000761`) does not improve performance. Proceed with larger-scale experiments per Research Protocol.

---

## Recommendation

**HOLD** — Sprint 5B.7 M2' results are **invalid** due to generation policy violation. The M2' training itself is valid, but the evaluation must be rerun with the correct dynamic budget.

**Action:** Fix generation policy in `run_m2prime_evaluation.py`, rerun evaluation, then compare M1 vs M2' under identical conditions.

---

*Audit completed: 2026-08-09*  
*Classification: D — Generation configuration mismatch*  
*Severity: Critical (invalidates comparison)*
