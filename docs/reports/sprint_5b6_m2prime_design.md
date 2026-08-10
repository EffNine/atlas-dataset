# M2' Controlled Experiment Design

**Sprint:** 5B.6  
**Date:** 2026-08-09  
**Status:** DESIGN ONLY — no training or evaluation permitted  
**Classification:** Controlled scaling comparison, M1 vs M2'

---

## 1. Design Rationale

Sprint 5B.4 compared M1 (117 records) against M2 (131 records) and found M2 underperformed M1 by -0.0217 correctness. The comparison was **confounded** by:

1. **Eval leakage:** 13 of 14 extra M2 records overlapped with `math_eval_v2`
2. **Unequal exposure:** M1 records received 4–5 presentations; M2 records received 3–4
3. **Unsupported difficulty claim:** Report claimed extra records were "harder" but data shows they are slightly easier

M2' eliminates all three confounds by:
- Removing all eval-overlap records from M2
- Matching training exposure via identical step/batch configuration
- Documenting actual difficulty distribution

---

## 2. M2' Construction

### 2.1 Source Pool

| Source | ID | License | Records in M2 |
|--------|----|---------|---------------|
| OpenMathInstruct-2 | expert-math-002 | CC-BY-4.0 | 131 |

### 2.2 Leakage Elimination

M2' is constructed by excluding all records that overlap with `math_eval_v2`:

| Set | Records | Eval Overlap |
|-----|---------|--------------|
| M2 (original) | 131 | 13 records |
| M2' (cleaned) | 118 | 0 records |
| M1 | 117 | 0 records |

**Excluded records (13):**
```
expert_math_000125, expert_math_000281, expert_math_000831, expert_math_000900,
expert_math_000961, expert_math_001421, expert_math_001505, expert_math_001802,
expert_math_002168, expert_math_002660, expert_math_002701, expert_math_002953,
expert_math_002995
```

**Added record (1):**
```
expert_math_000761  (the only M2 extra record not in eval set)
```

### 2.3 Subset Relationship

| Check | Result |
|-------|--------|
| M1 ⊆ M2' | **Yes** (all 117 M1 records present in M2') |
| M2' \ M1 | 1 record (`expert_math_000761`) |
| Duplicates in M2' | None |
| Duplicates in M1 | None |

---

## 3. Training Configuration (Identical to M1)

| Parameter | Value |
|-----------|-------|
| Base model | `Qwen/Qwen2.5-7B-Instruct` |
| Model revision | `a09a35458c702b33eeacc393d103063234e8bc28` |
| Quantization | NF4 4-bit + double quant |
| Compute dtype | bfloat16 |
| LoRA r | 8 |
| LoRA alpha | 16 |
| LoRA dropout | 0.05 |
| Target modules | q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj |
| Trainable parameters | 20,185,088 (0.264%) |
| Max seq length | 256 |
| Max steps | **60** (identical to M1) |
| Batch size | 1 |
| Gradient accumulation | 8 (effective batch = 8) |
| Examples consumed | **480** (identical to M1) |
| Learning rate | 2e-4 (cosine) |
| Warmup ratio | 0.03 |
| Optimizer | paged_adamw_8bit |
| Weight decay | 0.01 |
| Max grad norm | 1.0 |
| Seed | 42 |
| bf16 | true |
| Gradient checkpointing | true |

---

## 4. Evaluation Configuration

| Parameter | Value |
|-----------|-------|
| Eval set | `math_eval_v2` (N=100) |
| Eval set checksum | `16288500568c4dc161beaf55d557709519ab5d41eea0aeddd01c5fc735989056` |
| Engine | QEE v2 (frozen, Phase 8) |
| Greedy decoding | true |
| max_new_tokens | 256 |
| Baseline | Qwen/Qwen2.5-7B-Instruct (no adapter) |

---

## 5. Staged Artifact

| Artifact | Path | SHA-256 |
|----------|------|---------|
| M2' staged training JSONL | `experiments/lora_pilot_math_m2prime_v0.1/staged_train.jsonl` | `7dfa81114f4096286415a672830f6ff334cc95066080fd9f5267e86d0e413dda` |
| M2' manifest | `experiments/lora_pilot_math_m2prime_v0.1/m2prime_manifest.json` | (see §6) |

---

## 6. Acceptance Criteria

Before M2' training may proceed, the following must be verified:

| Criterion | Expected | Verification |
|-----------|----------|--------------|
| M1 ⊆ M2' | All 117 M1 records in M2' | Check record IDs |
| M2' ∩ eval = 0 | Zero overlap with math_eval_v2 | Cross-reference IDs |
| M2' ∩ M1 = M1 | M1 is proper subset | Set difference = 1 record |
| No duplicates in M2' | All record IDs unique | Count vs set count |
| Same source | expert-math-002 / OpenMathInstruct-2 | Provenance check |
| Same license | CC-BY-4.0 | License check |
| Checksum match | `7dfa8111...` | SHA-256 verification |
| Exposure matched | 480 examples consumed | Step × batch × accum |

---

## 7. What This Design Controls

| Confound | M2 (original) | M2' (this design) |
|----------|---------------|-------------------|
| Eval leakage | 13 records in eval | 0 records |
| Per-record exposure | 3–4 avg | 4–4.1 avg (matched) |
| Source | expert-math-002 | expert-math-002 |
| License | CC-BY-4.0 | CC-BY-4.0 |
| Hyperparameters | Identical to M1 | Identical to M1 |
| Eval set | math_eval_v2 | math_eval_v2 |
| Base model | Qwen2.5-7B-Instruct | Qwen2.5-7B-Instruct |
| Seed | 42 | 42 |

**The only variable changing between M1 and M2' is dataset size: 117 vs 118 records.**

---

## 8. Stop

**No training, evaluation, or code modifications are permitted under this design.**

This document and its manifest constitute the complete design. Execution requires separate Technical Lead approval.

---

*Design completed: 2026-08-09*  
*Design sprint: 5B.6*
