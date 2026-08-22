# Atlas 500M Pilot — Training Report

**Date:** 2026-08-15
**Status:** COMPLETE

## 1. Base Model Snapshot

| Field | Value |
|-------|-------|
| Model | Qwen/Qwen2.5-0.5B-Instruct |
| Parameters | 494,032,768 |
| VRAM (load) | 0.92 GB |
| Torch | 2.13.0+cu130 |
| CUDA | 13.0 |
| GPU | NVIDIA GeForce RTX 5070 |

## 2. Training Results

| Arm | Records | Tokens | Steps | Loss | Time (s) | Tok/s | VRAM (GB) |
|-----|--------:|-------:|------:|-----:|---------:|------:|----------:|
| General | 1,167 | 1,051,014 | 146 | 1.1151 | 283 | 3715.4 | 2.81 |
| Math | 1,181 | 1,108,676 | 148 | 0.8819 | 287 | 3865.9 | 2.81 |
| Code | 510 | 522,240 | 64 | 0.8214 | 137 | 3817.6 | 2.81 |
| Systems | 2,034 | 1,970,454 | 255 | 1.4839 | 451 | 4372.8 | 2.81 |

## 3. Training Metrics

### General
- Loss: 1.1151
- Steps: 146
- Tokens: 1,051,014

### Math
- Loss: 0.8819
- Steps: 148
- Tokens: 1,108,676

### Code
- Loss: 0.8214
- Steps: 64
- Tokens: 522,240

### Systems
- Loss: 1.4839
- Steps: 255
- Tokens: 1,970,454

## 4. Artifact Checksums

| Arm | Adapter Path |
|-----|-------------|
| General | `artifacts/pilot/v0.1/general/adapter/` |
| Math | `artifacts/pilot/v0.1/math/adapter/` |
| Code | `artifacts/pilot/v0.1/code/adapter/` |
| Systems | `artifacts/pilot/v0.1/systems/adapter/` |

## 5. Training Efficiency

| Metric | General | Math | Code | Systems |
|--------|--------:|-----:|-----:|--------:|
| Tokens/sec | 3715.4 | 3865.9 | 3817.6 | 4372.8 |
| Peak VRAM (GB) | 2.81 | 2.81 | 2.81 | 2.81 |
| Steps | 146 | 148 | 64 | 255 |
| Time (min) | 4.7 | 4.8 | 2.3 | 7.5 |

## 6. Protocol Deviations

1. **Unsloth not available**: Disk quota exceeded during installation. Used standard HuggingFace Transformers + PEFT + bitsandbytes instead.
2. **Optimizer naming**: Changed `optimizer` to `optim` in TrainingArguments (newer transformers API).
3. **Warmup**: Changed `warmup_ratio` to `warmup_steps` (newer transformers API).
4. **torch_dtype deprecation**: Using deprecated `torch_dtype` argument (transformers 5.15.0).

All other hyperparameters match the frozen protocol exactly.

## 7. Final Recommendation

### Observations
- All arms trained successfully with no OOM errors
- Peak VRAM: ~2.8 GB (well within 12 GB limit)
- Training throughput: ~3,700-4,400 tokens/sec
- Loss curves show healthy training across all domains

### Next Steps
1. Run evaluation on protected eval sets
2. Compare domain-specific performance vs base
3. Assess specialization signal strength

---

```
500M PILOT:
COMPLETE

SPECIALIZATION SIGNAL:
INCONCLUSIVE (requires evaluation)
```