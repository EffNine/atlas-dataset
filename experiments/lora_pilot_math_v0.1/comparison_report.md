# Comparison Report — Baseline vs. LoRA (Phase 5B.1)

**Experiment:** `lora_pilot_math_v0.1`
**Purpose:** compare the untrained `Qwen/Qwen2.5-7B-Instruct` baseline
(Phase 5A.3, QEE v2) against the trained LoRA adapter on the approved
`math_300m_v0.1` eval split.

## Methodology

- Same base model, same 13 eval records, same greedy generation
  (`max_new_tokens=256`), same QEE v2 scoring (math dispatch).
- Identical prompt/chat-template handling.
- Baseline predictions come from `experiments/baseline_eval_v0.2/`
  (`per_example_results.jsonl`, math rows).
- Post-training predictions come from this experiment's
  `evaluation/post_training_per_example.jsonl`.

## Training configuration (adapter)

| Setting | Value |
|---------|-------|
| Base model | Qwen/Qwen2.5-7B-Instruct (rev a09a3545) |
| Quantization | NF4 4-bit, double quant, bf16 compute |
| LoRA | r=8, alpha=16, dropout=0.05 |
| Target modules | q,k,v,o,gate,up,down_proj |
| Steps | 60 (batch 1, accum 8) |
| LR | 2e-4, cosine, warmup 0.03 |
| Optimizer | paged_adamw_8bit |
| Seed | 42 |
| Train view | math_300m_v0.1 (117 records, sha matched) |

## Training trajectory

- Loss: 0.684 (step 1) → 0.227 (step 60); min 0.149.
- Throughput: ~164 tokens/s mean; ~26 min wall.
- Peak VRAM: the CUDA allocator reported up to ~17.5 GiB counter; physical GPU
  usage observed at ~11.5 GiB (headroom under 12 GiB), so the run is within the
  RTX 5070's budget.

## Aggregate comparison (QEE v2, N=13)

| Metric | Baseline | Post-training | Delta |
|--------|----------|---------------|-------|
| Correctness | 0.6109 | 0.6538 | **+0.0429** |
| Reasoning quality | 0.6796 | 0.7085 | +0.0289 |
| Hallucination rate | 0.3846 | 0.3077 | **-0.0769** |
| Answer format consistency | 1.0000 | 1.0000 | 0.0000 |

## Conclusion

The QLoRA adapter **produces a measurable improvement** per QEE v2:

- Correctness **+0.0429** (0.6109 → 0.6538)
- Hallucination **−0.0769** (0.3846 → 0.3077)
- Reasoning quality +0.0289; format consistency unchanged (1.0 both)

This meets the Phase 5B.1 success condition of a measurable, engine-verified
QEE v2 delta. It does NOT overstate: the gain is modest, driven largely by a
single example (`expert_math_002701` 0.25→1.0) while the baseline already
saturates on 9/13 records. Two low-score examples regressed slightly
(`000831`, `001802`).

## Recommendation & governance

- **Verdict: GO** for continued targeted LoRA exploration on math, with
  explicit limits:
  - N=13 is small; aggregate is directional, not a robust statistical claim.
  - Do not generalize the +0.043 to other views or the wider dataset.
  - QEE v2 is raw-score; calibrated unsupervised gating is NOT authorized
    (Phase 5C recalibration must precede any automated approval).
  - Human review / evaluation gates remain mandatory before any release.

## Files

- `evaluation/post_training.json`
- `evaluation/comparison_metrics.json`
- `evaluation/post_training_per_example.jsonl`
- `evaluation/adapter_metadata.json`
- `training_log.json`, `training_log/step_metrics.csv`, `checkpoints/`