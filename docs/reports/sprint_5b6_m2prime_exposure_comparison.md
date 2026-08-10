# M1 vs M2' Exposure Comparison

**Sprint:** 5B.6  
**Date:** 2026-08-09

---

## 1. Training Configuration

Both M1 and M2' use identical training hyperparameters:

| Parameter | Value |
|-----------|-------|
| max_steps | 60 |
| per_device_train_batch_size | 1 |
| gradient_accumulation_steps | 8 |
| **examples_consumed** | **480** |

---

## 2. Presentation Count Distribution

### M1 (117 records)

```
480 examples / 117 records = 4 full presentations + 12 remainder
```

| Presentations/record | Record count |
|---------------------|--------------|
| 4 | 105 |
| 5 | 12 |
| **Total** | **117** |

Average: 4.1026 presentations per record

### M2' (118 records)

```
480 examples / 118 records = 4 full presentations + 8 remainder
```

| Presentations/record | Record count |
|---------------------|--------------|
| 4 | 110 |
| 5 | 8 |
| **Total** | **118** |

Average: 4.0678 presentations per record

---

## 3. Exposure Difference Analysis

| Metric | M1 | M2' | Difference |
|--------|----|-----|------------|
| Avg presentations/record | 4.1026 | 4.0678 | 0.0348 |
| Records at 4 presentations | 105 | 110 | +5 |
| Records at 5 presentations | 12 | 8 | -4 |
| Max presentations | 5 | 5 | 0 |
| Min presentations | 4 | 4 | 0 |

### Assessment

The exposure difference is **negligible**:
- Average difference: 0.035 presentations per record (0.85%)
- Only 4 records differ in presentation count (12 vs 8 at the maximum)
- Both distributions are centered at 4 presentations per record

This is dramatically better than the original M2 comparison:
- M1 vs M2: 4.10 vs 3.66 presentations/record (12% difference)
- M1 vs M2': 4.10 vs 4.07 presentations/record (0.85% difference)

---

## 4. Why This Matters

In the original M2 vs M1 comparison, the lower per-record exposure for M2 (3–4 vs 4–5) was a **confounding variable**. A model that sees each record fewer times may underperform simply due to less training, not due to dataset composition.

M2' eliminates this confound by using the same step count and batch configuration, ensuring that both models receive nearly identical per-record exposure.

---

## 5. Controlled Variable Summary

| Variable | M1 | M2' | Matched? |
|----------|----|-----|----------|
| Base model | Qwen2.5-7B-Instruct | Qwen2.5-7B-Instruct | ✅ |
| Model revision | a09a3545... | a09a3545... | ✅ |
| LoRA config | r=8, α=16, dropout=0.05 | r=8, α=16, dropout=0.05 | ✅ |
| Max steps | 60 | 60 | ✅ |
| Batch size | 1 | 1 | ✅ |
| Grad accumulation | 8 | 8 | ✅ |
| Examples consumed | 480 | 480 | ✅ |
| Learning rate | 2e-4 cosine | 2e-4 cosine | ✅ |
| Seed | 42 | 42 | ✅ |
| Seq length | 256 | 256 | ✅ |
| Eval set | math_eval_v2 | math_eval_v2 | ✅ |
| Dataset size | 117 | 118 | ❌ (intentional) |
| Eval leakage | 0 | 0 | ✅ |
| Per-record exposure | 4.10 avg | 4.07 avg | ✅ (near-identical) |

**The only intentional difference is dataset size (117 vs 118 records).**

---

*Generated: 2026-08-09*
