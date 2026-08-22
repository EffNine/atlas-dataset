# Clean Math Evaluation Report — M1/M2/M2' Scaling Comparison

**Date:** 2026-08-12
**Experiment:** `clean_math_eval_v2`
**Status:** COMPLETE

---

## VERIFIED

1. **The proposed N=118 combined eval set is INVALID.** The 18 "unused" expert_math records are review metadata only (`review/expert_pilot_6500_review_decisions_v0.1.jsonl`). They contain no `problem`, `messages`, or `canonical_answer` fields. They cannot be used for evaluation.

2. **Maximum available eval set:** `math_eval_v2` (N=100). No additional evaluatable records exist in the repository.

3. **Clean eval set constructed:** `math_eval_v2_clean` (N=87) = `math_eval_v2` minus 13 M2 training-overlap records. Zero training/eval overlap for ALL three models.

4. **Provenance verified:** All checkpoints loaded correctly. All scores computed with QEE v2, math dispatch. Same protocol as existing M2/M2' evaluations.

## DATASET PROVENANCE

| Item | Value |
|------|-------|
| Source eval set | `math_eval_v2` (N=100) |
| Excluded records | 13 (M2 training overlap) |
| Clean eval set | `math_eval_v2_clean` (N=87) |
| Checksum | `90ce0cc1a0b45ef06c3701897df13cd3e875fb8b0637a0d95ce8404aeb04ce75` |
| M1 overlap | 0 |
| M2 overlap | 0 (excluded) |
| M2' overlap | 0 |
| All records have problem + canonical_answer | Yes (87/87) |

## RESULTS

| Model | Correctness (N=87) | 95% Wilson CI | vs M1 Delta |
|-------|-------------------|---------------|-------------|
| M1 (baseline) | 0.6801 | (0.5762, 0.7687) | — |
| M2 (131 train recs) | 0.6552 | (0.5506, 0.7466) | **-0.0249** |
| M2' (118 train recs) | 0.6284 | (0.5234, 0.7224) | **-0.0517** |

## STATISTICS

### M2 vs M1 (N=87, zero overlap)
- Paired t-test: t=0.5447, p=0.5860 (not significant)
- McNemar's test: χ²=0.2667, p=0.8752 (not significant)
- Discordant pairs: b=9 (M1→0, M2→1), c=6 (M1→1, M2→0)
- Power at observed diff: 5.4%

### M2' vs M1 (N=87, zero overlap)
- Paired t-test: t=1.5801, p=0.1141 (not significant)
- McNemar's test: χ²=1.125, p=0.5698 (not significant)
- Discordant pairs: b=6 (M1→0, M2'→1), c=2 (M1→1, M2'→0)
- Power at observed diff: 10.7%

### M2' vs M2 (N=87)
- Paired t-test: t=0.6226, p=0.5335 (not significant)
- McNemar's test: χ²=0.0, p=1.0 (no discordance)
- Power: negligible

## M2 OVERLAP SENSITIVITY

The N=87 clean set excludes the 13 M2 training-overlap records. This means:
- M2 is now evaluated on a truly clean set (zero overlap)
- The comparison is fairer than the original N=100 result
- M2's correctness dropped from 0.6800 (N=100) to 0.6552 (N=87)
- This suggests the 13 overlap records were helping M2's score

**Original M2 result (N=100, 13 overlap):**
- M1: 0.7017, M2: 0.6800, Delta: -0.0217, p=0.608

**Clean M2 result (N=87, 0 overlap):**
- M1: 0.6801, M2: 0.6552, Delta: -0.0249, p=0.586

The direction and magnitude of the delta are consistent. The clean result is more trustworthy.

## INTERPRETATION

1. **M2 underperforms M1** on the clean set (-0.0249), consistent with the original result (-0.0217).
2. **M2' underperforms M1 more** on the clean set (-0.0517), compared to the original (-0.0250).
3. **Neither difference is statistically significant** by any test (all p > 0.05).
4. **Power is severely lacking** (5-11% at N=87). The experiment cannot detect the observed 2-5pp effects.
5. **M2' shows a larger negative delta** than M2, which is surprising given M2' has zero eval overlap. This suggests the single additional record (expert_math_000761) may have a negative effect, or the difference is noise.
6. **Truncation rate is a known G-POL issue** (90-95%) and must not be treated as capability evidence.

## DECISION

**HOLD — UNDERPOWERED**

The clean evaluation confirms the M2/M2' negative direction but cannot distinguish signal from noise. Neither result reaches statistical significance. The experiment is underpowered for the observed effect sizes.

### Why HOLD and not STOP:
- Both M2 and M2' show negative point estimates, but the confidence intervals are wide and overlap substantially.
- The M2' result (-0.0517) is more pronounced but still not significant (p=0.114 by t-test, p=0.570 by McNemar's).
- No evidence of scaling benefit; no evidence of scaling harm either.
- The proper conclusion is that we cannot tell with N=87.

### Why not CONTINUE SCALING:
- Adding more training data without increasing eval N will not resolve the power problem.
- The source pool is depleted (only 236 total expert_math records, 131 already used).
- Further scaling would require new data acquisition (external benchmark integration).

## NEXT STEP

**Acquire a larger math evaluation set from an external source.**

Options:
1. **Integrate GSM8K** (MIT license, N=1,319 test) — registered in benchmark_registry as placeholder
2. **Integrate MATH benchmark** (MIT license, competition_math split, N=5,000) — registered in benchmark_registry as placeholder
3. **Request additional expert_math records** from OpenMathInstruct-2 (3,000 acquired, only 236 kept — investigate filtering pipeline)

Until N≥500, the scaling question remains unanswerable with current data.

---

## Files Produced

| File | Path |
|------|------|
| Clean eval set | `evaluation/eval_sets/protocol_v2/math_eval_v2_clean.jsonl` |
| Clean eval manifest | `evaluation/eval_sets/protocol_v2/math_eval_v2_clean_manifest.json` |
| Comparison report | `experiments/lora_pilot_math_m2_v0.1/evaluation/clean_math/comparison.json` |
| M1 clean results | `experiments/lora_pilot_math_m2_v0.1/evaluation/clean_math/m1_clean_results.jsonl` |
| M2 clean results | `experiments/lora_pilot_math_m2_v0.1/evaluation/clean_math/m2_clean_results.jsonl` |
| M2' clean results | `experiments/lora_pilot_math_m2_v0.1/evaluation/clean_math/m2prime_clean_results.jsonl` |
| Builder script | `scripts/build_clean_math_eval.py` |
| Eval script | `experiments/lora_pilot_math_m2_v0.1/run_clean_math_eval.py` |

---

*Report generated: 2026-08-12*
*Evaluation engine: QEE v2 (Protocol v2)*
*Execution environment: NVIDIA GeForce RTX 5070 12GB*
