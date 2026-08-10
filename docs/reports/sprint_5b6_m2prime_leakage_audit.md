# M2' Leakage Audit

**Sprint:** 5B.6  
**Date:** 2026-08-09

---

## 1. Eval Set Definition

| Field | Value |
|-------|-------|
| Eval set ID | `math_eval_v2` |
| Eval set path | `evaluation/eval_sets/protocol_v2/math_eval_v2.jsonl` |
| Eval set manifest | `evaluation/eval_sets/protocol_v2/math_eval_v2_manifest.json` |
| N records | 100 |
| Checksum | `16288500568c4dc161beaf55d557709519ab5d41eea0aeddd01c5fc735989056` |

---

## 2. M1 Leakage Audit

| Check | Result |
|-------|--------|
| M1 records | 117 |
| M1 ∩ eval | **0 records** |
| Leakage status | ✅ CLEAN |

M1 was constructed with zero eval overlap by design (verified in Phase 4A freeze).

---

## 3. M2' Leakage Audit

| Check | Result |
|-------|--------|
| M2' records | 118 |
| M2' ∩ eval | **0 records** |
| Leakage status | ✅ CLEAN |

M2' was constructed by explicitly excluding all 13 eval-overlap records from M2.

---

## 4. Original M2 Leakage (for reference)

| Check | Result |
|-------|--------|
| M2 records | 131 |
| M2 ∩ eval | **13 records** |
| Leakage ratio | 9.9% |
| Leakage status | ❌ CONTAMINATED |

### Excluded records (now in M2'):

```
expert_math_000125  (difficulty 2)
expert_math_000281  (difficulty 2)
expert_math_000831  (difficulty 2)
expert_math_000900  (difficulty 2)
expert_math_000961  (difficulty 2)
expert_math_001421  (difficulty 2)
expert_math_001505  (difficulty 2)
expert_math_001802  (difficulty 2)
expert_math_002168  (difficulty 3)
expert_math_002660  (difficulty 2)
expert_math_002701  (difficulty 3)
expert_math_002953  (difficulty 2)
expert_math_002995  (difficulty 3)
```

---

## 5. Leakage Impact Analysis

### M2 (original) — contaminated

The 13 leaked records were present in BOTH the training set and the eval set. This creates two possible failure modes:

1. **Overfitting to eval records:** The model memorizes specific eval examples, inflating performance on those records but potentially degrading generalization.
2. **Artificially low generalization gap:** With 13% of training data overlapping eval, the model's eval performance may not reflect true generalization.

### M2' — clean

Zero overlap eliminates both failure modes. Any performance difference between M1 and M2' can be attributed to dataset composition, not leakage.

---

## 6. Cross-Set Leakage Check

We also verify that M1 and M2' do not share records with each other's eval sets (they don't — both have 0 overlap).

| Pair | Overlap | Status |
|------|---------|--------|
| M1 ∩ math_eval_v2 | 0 | ✅ |
| M2' ∩ math_eval_v2 | 0 | ✅ |
| M1 ∩ M2' | 117 (M1 ⊂ M2') | ✅ Expected |

---

## 7. Conclusion

M2' is **leakage-clean**. The controlled comparison between M1 and M2' isolates dataset size as the sole variable.

---

*Audit generated: 2026-08-09*
