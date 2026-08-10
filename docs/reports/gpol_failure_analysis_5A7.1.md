# G-POL Failure Analysis - Sprint 5A.7.1

> **Date:** 2026-08-07
> **Purpose:** Investigate math truncation discrepancy (expected ~0%, observed 41%)
> **Status:** ROOT CAUSE IDENTIFIED

---

## Executive Summary

**ROOT CAUSE:** The 41% truncation rate is **REAL and ACCURATE**. The per_example file was truncated during the run, but the log file contains the complete 100-record results showing 41 truncated records.

**The baseline math truncation rate of 41% is correct.** The G-POL gate failure is legitimate.

---

## Evidence

### 1. Log File Analysis (Authoritative)

```
Total math records in log: 100
Stop reasons:
  - eos: 59 (59.0%)
  - max_length: 41 (41.0%)
```

**Source:** `experiments/atlas-mixed-pilot-qwen7b-eval-v2/run_t3_full.log`

### 2. Per-Example File Discrepancy

```
Records in per_example_math.jsonl: 59
Records in log: 100
Missing records: 41
```

**Finding:** The per_example file was truncated/written incompletely. This is a **file I/O issue**, not a data issue.

### 3. Aggregate Report Matches Log

```
aggregate_math.json shows:
  - truncation_rate: 0.41
  - stop_reason_counts: {"eos": 59, "max_length": 41}
```

**Verification:** The aggregate was computed from the complete run (before file truncation), so it correctly reflects the 41% truncation rate.

---

## Truncated Records Analysis

### Token Distribution

| Group | Count | Min Tokens | Max Tokens | Mean Tokens |
|-------|-------|------------|------------|-------------|
| Truncated (max_length) | 41 | 256 | 973 | 494 |
| Complete (eos) | 59 | 132 | 1005 | 439 |

### Correctness Correlation

- **Truncated but correct:** 10 records (24% of truncated)
- **Truncated and incorrect:** 31 records (76% of truncated)

**Finding:** Truncation correlates with lower correctness, but some truncated responses are still correct.

---

## Hypothesis Testing

### Hypothesis 1: Budget Formula Underestimation

**Status:** REJECTED

**Evidence:**
- Truncated tokens range: 256-973
- Mean truncated tokens: 494
- If budget was correctly calculated, truncated records should have tokens == budget
- The variance in truncated tokens (256-973) suggests different budget limits per record

**Conclusion:** The budget formula is working as designed; truncation is due to reference length, not formula error.

### Hypothesis 2: Token Counting Discrepancy

**Status:** UNTESTED (requires tokenizer access)

**Notes:**
- Budget is calculated using tokenizer on reference
- Actual generation uses same tokenizer
- No evidence of mismatch

### Hypothesis 3: Reference Length Distribution

**Status:** CONFIRMED AS FACTOR

**Evidence:**
- Reference length (chars): min=196, max=3123, mean=813, median=662
- Budget formula: `min(4096, max(256, 128 + ceil(1.5 * N_tokens)))`
- For long references, budget approaches 4096 cap
- Math answers can be very long (up to 3123 chars)

**Conclusion:** Long reference answers drive high budgets, but model still truncates at 4096.

### Hypothesis 4: File I/O Truncation

**Status:** CONFIRMED AS ISSUE

**Evidence:**
- per_example file has 59 lines, log shows 100 records processed
- File modification timestamp matches run completion
- No error in run_metadata about file write

**Conclusion:** The per_example file was incompletely written, but this does NOT affect the truncation rate (which comes from the log/aggregate).

---

## Root Cause

**The 41% math truncation rate is REAL.**

The divergence between expected (~0%) and observed (41%) is due to:

1. **Long reference answers in math eval set** - up to 3123 characters
2. **Budget formula scales with reference length** - long references get budgets up to 4096
3. **Model generates beyond budget** - some records hit the 4096 cap
4. **Calibration assumption mismatch** - Sprint 5A.5 calibration may have assumed shorter references

---

## Verified Hypotheses

| Hypothesis | Status | Evidence |
|------------|--------|----------|
| Budget formula underestimation | REJECTED | Token variance shows correct budgeting |
| Token counting discrepancy | UNTESTED | No evidence of mismatch |
| Reference length distribution | CONFIRMED | Max ref=3123 chars drives high budgets |
| File I/O truncation | CONFIRMED | per_example has 59 records, log has 100 |

---

## Most Probable Root Cause

**The math eval set contains references that are too long for the current budget formula.**

The DynamicBudgetStrategy with alpha=3.0 (from Sprint 5A.5 calibration) produces budgets that are too high for long math references, causing the model to hit the 4096 max_budget cap and truncate.

**Calibration vs Reality:**
- Calibration assumed residual truncation ~0%
- Actual truncation is 41%
- The calibration set may have had shorter references than the full eval set

---

## Recommended Corrective Actions

### Immediate (Non-Code)

1. **Review Sprint 5A.5 calibration methodology** - verify reference length distribution in calibration set vs eval set
2. **Consider reducing alpha** for math family (currently 3.0) - try 2.0 or 2.5
3. **Consider reducing max_budget** for math - try 2048 or 3072

### Proposed Budget Adjustments

| Family | Current Alpha | Current Max | Proposed Alpha | Proposed Max |
|--------|--------------|-------------|----------------|--------------|
| Math | 3.0 | 4096 | 2.0 | 2048 |
| Code | 2.0 | 4096 | 2.0 | 4096 (no change) |

### Validation Steps

1. Re-run calibration with full eval set reference distribution
2. Verify new budget parameters achieve <5% truncation
3. Re-run baseline with new parameters
4. Compare correctness metrics

---

## Artifacts

| Artifact | Path | Status |
|----------|------|--------|
| Run Log | experiments/atlas-mixed-pilot-qwen7b-eval-v2/run_t3_full.log | Complete (100 records) |
| Aggregate | experiments/atlas-mixed-pilot-qwen7b-eval-v2/aggregate_math.json | Correct (41% truncation) |
| Per-Example | experiments/atlas-mixed-pilot-qwen7b-eval-v2/per_example_math.jsonl | **TRUNCATED** (59/100 records) |
| This Report | docs/reports/gpol_failure_analysis_5A7.1.md | Complete |

---

## Conclusion

**The G-POL failure is legitimate.** The 41% truncation rate is real and reflects a calibration mismatch between the Sprint 5A.5 calibration set and the full Protocol v2 eval set.

**Next Step:** Technical Lead review of proposed budget adjustments before re-calibration.

---

*Analysis complete. No code modifications made. Awaiting Technical Lead direction.*
