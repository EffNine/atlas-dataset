# Evaluation Report — LoRA Math Pilot v0.1 (Phase 5B.1) — Post-Training

**Experiment:** `lora_pilot_math_v0.1`
**Phase:** 5B.1 — QLoRA Math Pilot
**Status:** COMPLETE
**Evaluation engine:** QEE v2 (`scripts/evaluation_engine/v2`), math dispatch

## Summary

The trained LoRA adapter was reloaded on the `Qwen/Qwen2.5-7B-Instruct` base
(4-bit NF4 + double quant + bf16) and evaluated on the approved
`math_300m_v0.1` **eval** split (13 records) with greedy generation
(`max_new_tokens=256`). Predictions were scored with the QEE v2 math evaluator
using the same protocol as the Phase 5A.3 baseline.

## Adapter verification

- Adapter reload: **OK** (`checkpoints/adapter_config.json`,
  `adapter_model.safetensors`)
- Base: `Qwen/Qwen2.5-7B-Instruct` (revision `a09a35458c702b33eeacc393d103063234e8bc28`)
- LoRA: `r=8`, `lora_alpha=16`, `lora_dropout=0.05`, `bias=none`,
  `task_type=CAUSAL_LM`; target modules `{q,k,v,o,gate,up,down}_proj`
- Inference mode: trainable params on eval = 0 (frozen base, adapter applied)
- Backbone loaded exactly as training: NF4 4-bit, double quant, bf16 compute

## Model / dataset provenance

| Item | Value |
|------|-------|
| Base model | `Qwen/Qwen2.5-7B-Instruct` |
| Model revision | `a09a35458c702b33eeacc393d103063234e8bc28` |
| Training view | `math_300m_v0.1` |
| Eval split sha256 | `60b1e078b019c2b815ffd5b55078b914f36baf6a6463db8beeee2b4ce8a28123` |
| Eval records | 13 |
| Git commit | `d15f931` |

## Results (QEE v2, math dispatch), N=13

| Metric | Baseline (5A.3) | Post-training (LoRA) | Delta |
|--------|-----------------|----------------------|-------|
| Correctness | 0.6109 | 0.6538 | **+0.0429** |
| Reasoning quality | 0.6796 | 0.7085 | +0.0289 |
| Hallucination rate | 0.3846 | 0.3077 | **-0.0769** |
| Answer format consistency | 1.0000 | 1.0000 | 0.0000 |
| Mean latency (s) | 6.5775 | 3.4123 | -3.1652 |
| Mean tokens/sec | 17.72 | 7.85 | -9.87 |

> Correctness improved measurably (+0.0429 to 0.6538) and the hallucination
> rate declined by -0.0769. Reasoning quality improved slightly (+0.0284).
> Format consistency unchanged at 1.0.

## Per-example deltas (correctness)

| record_id | Baseline | LoRA | Delta |
|-----------|----------|------|-------|
| expert_math_000125 | 1.0 | 1.0 | 0.0 |
| expert_math_000281 | 1.0 | 1.0 | 0.0 |
| expert_math_000831 | 0.1667 | 0.0 | -0.1673 |
| expert_math_000900 | 0.5 | 0.5 | 0.0 |
| expert_math_000961 | 1.0 | 1.0 | 0.0 |
| expert_math_001421 | 0.0 | 0.0 | 0.0 |
| expert_math_001505 | 1.0 | 1.0 | 0.0 |
| expert_math_001802 | 0.025 | 0.0 | -0.025 |
| expert_math_002168 | 1.0 | 1.0 | 0.0 |
| expert_math_002660 | 0.0 | 0.0 | 0.0 |
| expert_math_002701 | 0.25 | 1.0 | **+0.75** |
| expert_math_002953 | 1.0 | 1.0 | 0.0 |
| expert_math_002995 | 1.0 | 1.0 | 0.0 |

The net improvement is driven primarily by `expert_math_002701`
(correctness 0.25→1.0, hallucination 1.0→0.0). 9/13 examples were already at
the evaluation ceiling (correctness 1.0) in baseline and stayed there. Two
low-score examples regressed modestly (`000831`, `001802`).

## Interpretation / limitations

- **Measurable delta exists** per QEE v2: correctness +0.0429, hallucination
  -0.0769. Improvement is not claimed beyond what the engine measures.
- **Small eval set (N=13)** and a strong single-example gain mean the aggregate
  delta is sensitive to individual records; treat as directional, not a
  statistically robust signal.
- Baseline already saturates (9/13 perfect), limiting headroom.
- QEE v2 is used in raw-score form; calibrated unsupervised gating is NOT
  authorized (human review gates remain mandatory per Phase 5C).
- Inference throughput (7.85 tok/s vs 17.72 tok/s) is lower with the adapter;
  load was identical, so this is a per-run observation, not a trained property.

## Artifacts

- `evaluation/post_training.json`
- `evaluation/post_training_per_example.jsonl`
- `evaluation/adapter_metadata.json`
- `evaluation/comparison_metrics.json`
- Training: `training_log.json`, `training_log/step_metrics.csv`, `checkpoints/`