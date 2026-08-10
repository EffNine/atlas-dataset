# M1 vs M2' Difficulty Distribution Comparison

**Sprint:** 5B.6  
**Date:** 2026-08-09

---

## 1. Difficulty Distribution

### M1 (117 records)

| Difficulty | Count | Percentage |
|------------|-------|------------|
| 2 | 100 | 85.5% |
| 3 | 17 | 14.5% |
| 4 | 0 | 0.0% |
| **Total** | **117** | **100%** |

### M2' (118 records)

| Difficulty | Count | Percentage |
|------------|-------|------------|
| 2 | 101 | 85.6% |
| 3 | 17 | 14.4% |
| 4 | 0 | 0.0% |
| **Total** | **118** | **100%** |

### Difference

| Difficulty | M1 | M2' | Delta |
|------------|----|-----|-------|
| 2 | 100 | 101 | +1 |
| 3 | 17 | 17 | 0 |
| 4 | 0 | 0 | 0 |

The extra record in M2' (`expert_math_000761`) is difficulty level 2.

---

## 2. Text Length Distribution

| Statistic | M1 | M2' |
|-----------|----|-----|
| Average | 967 chars | 964 chars |
| Minimum | 277 chars | 277 chars |
| Maximum | 3,620 chars | 3,620 chars |

The distributions are nearly identical. The extra record (`expert_math_000761`, 596 chars) is within the normal range.

---

## 3. Source Distribution

| Source | M1 | M2' |
|--------|----|-----|
| OpenMathInstruct-2 | 117 | 118 |
| License | CC-BY-4.0 | CC-BY-4.0 |

Both sets come from the same source with the same license.

---

## 4. Comparison with Original M2

For reference, the original M2 (131 records) had:

| Difficulty | M1 (117) | M2 (131) | M2' (118) |
|------------|----------|----------|-----------|
| 2 | 100 | 111 | 101 |
| 3 | 17 | 20 | 17 |
| 4 | 0 | 0 | 0 |

The original M2 had slightly more difficulty-3 records (20 vs 17), but this was confounded by eval leakage. M2' restores the difficulty balance to match M1.

---

## 5. Assessment

**M1 and M2' have virtually identical difficulty and length distributions.** The only difference is the addition of one difficulty-2 record (`expert_math_000761`) to M2'.

This means any performance difference between M1 and M2' cannot be attributed to difficulty or length bias — it reflects the effect of adding one additional training record.

---

*Generated: 2026-08-09*
