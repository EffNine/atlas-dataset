# Code LoRA Pilot Report — Phase 5B.2

**Experiment:** `lora_pilot_code_v0.1`
**Objective:** Validate whether Atlas training (QLoRA) improves software-engineering (code) capabilities on the approved `code_300m_v0.1` training view.
**Scope:** Code capability change only. No claim of general-intelligence improvement is made.
**Date:** 2026-08-04

---

## 1. Pre-training record (baseline)

| Fact | Value |
|------|-------|
| Repository git commit | `d1fb9310c37d5e119327f3baa45f89cab2d4c5b0` (`d1fb931`) |
| Train view file | `output/training_views/code_300m_v0.1/train.jsonl` (22 records) |
| Train file SHA-256 | `71d17e4bc51a925955ac48c9724861e803b6310608009823fe1cff91e21dbc69` |
| Approved manifest records SHA-256 | `41a336e51e890a92fd06f2ab76a7c66e5ec28c7a196cfa4bc22622d18e80fd56` (all 24 train+eval records; verified exact match against the on-disk view) |
| Checksum match | `true` |
| Base model | `Qwen/Qwen2.5-7B-Instruct` |
| Model revision | `a09a35458c702b33eeacc393d103063234e8bc28` |
| Eval split | `code_300m_v0.1/eval.jsonl` — 2 records (`expert_swe_000299`, `expert_swe_000366`) |

Training configuration is byte-for-byte the validated Phase 5B.1 math QLoRA setup (no config change).

## 2. Training configuration (identical to validated math pilot)

```json
{
  "quantization": { "load_in_4bit": true, "bnb_4bit_use_double_quant": true,
                    "bnb_4bit_quant_type": "nf4", "bnb_4bit_compute_dtype": "bfloat16" },
  "lora": { "r": 8, "lora_alpha": 16, "lora_dropout": 0.05, "bias": "none",
            "task_type": "CAUSAL_LM",
            "target_modules": ["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"] },
  "training": { "seed": 42, "max_seq_length": 1024, "max_steps": 60,
                "per_device_train_batch_size": 1, "gradient_accumulation_steps": 8,
                "effective_batch_size": 8, "learning_rate": 0.0002, "weight_decay": 0.01,
                "lr_scheduler_type": "cosine", "warmup_ratio": 0.03,
                "optim": "paged_adamw_8bit", "max_grad_norm": 1.0,
                "bf16": true, "gradient_checkpointing": true }
}
```

**Schedule note:** the code view has 22 train examples vs 117 for math. With
`max_steps=60` / accum 8 → 480 micro-steps → **~21.8 epochs** over 22 examples
(vs ~4.1 epochs for math). Kept identical to the validated setup per plan; the
epoch inflation on this tiny set is a known overfitting risk and is reported
here transparently.

## 3. Training metrics

| Metric | Value |
|--------|-------|
| Steps completed | 60 / 60 |
| Examples consumed | 480 |
| Final loss | 0.03913 |
| Min loss | 0.00819 |
| Trainable params | 0.2643 % of model |
| Peak VRAM allocated | 17,536.9 MiB (~11.4 GiB physical, RTX 5070 12 GB) |
| Throughput (mean) | 47.12 tokens/s |
| Wall time | 8,092 s (~2.25 h) |
| Optimizer | paged_adamw_8bit, cosine LR, warmup 0.03 |

Loss trajectory shows rapid overfit (min 0.008, final 0.039) consistent with the
22-example / ~21.8-epoch schedule. Adapter: `checkpoints/adapter_model.safetensors`
(80 MB), r=8 alpha=16 on 7 modules — same footprint as the math pilot.

## 4. Evaluation — QEE v2 code metrics

Baseline from `experiments/baseline_eval_v0.2` (code-300m rows); post-training
from `experiments/lora_pilot_code_v0.1/evaluation/`. N=2 records.

| Metric | Baseline | LoRA post-training | Δ |
|--------|----------|--------------------|---|
| Correctness | 0.5000 | 0.5526 | **+0.0526** |
| Reasoning quality | 0.6075 | 0.6435 | +0.0360 |
| Hallucination rate | 0.5000 | 0.5000 | 0.0000 |
| Answer format consistency | 1.0000 | 1.0000 | 0.0000 |

Both models produce patch-formatted answers (format consistency 1.0). The
+0.05 correctness delta is driven entirely by a single record (`000299`) and is
statistically meaningless at N=2.

## 5. Per-example comparison

| record_id | Baseline corr | LoRA corr | Δ | Class | Detail |
|-----------|---------------|-----------|---|-------|--------|
| `expert_swe_000299` | 0.0000 | 0.1053 | +0.1053 | **improved (format)** | Baseline answered in prose (no unified diff, 0 added lines). LoRA emitted a real unified diff (6 added lines, patch-similarity 0.105) but the fix is wrong (invented `__copy__` instead of the dtype-preserving copy). Still `correct=False`. |
| `expert_swe_000366` | 1.0000 | 1.0000 | 0.0000 | unchanged | Both correct (`joblib` added to `show_versions`; 1 added line, similarity 1.0). |

## 6. Regression analysis

- **Improved:** 1 of 2 (`000299`) — but only in *answer format* (prose → real
  diff), not in correctness. The LoRA produced a structurally valid patch shell
  yet failed to apply the correct change.
- **Regressed:** 0 of 2.
- **Unchanged:** 1 of 2 (`000366`, already correct in baseline).

Patch added-line similarity vs reference:

| record_id | Reference added lines | Baseline sim | LoRA sim |
|-----------|----------------------|--------------|----------|
| `expert_swe_000299` | 32 | 0.000 | 0.105 |
| `expert_swe_000366` | 1 | 1.000 | 1.000 |

## 7. Conclusions (code capability only)

1. **No reliable code-ability improvement is demonstrated.** The only delta
   (+0.105 on `000299`) is a format change (prose → diff) on a record that is
   still *incorrect*. The already-correct record stayed correct.
2. **No regression observed** in code output; the adapter did not degrade the
   one correct baseline answer.
3. **Dataset is far too small to conclude anything.** 22 train / 2 eval examples
   with a ~21.8-epoch schedule produced near-zero training loss (overfit). Any
   correctness number on N=2 is anecdotal.
4. **No general-intelligence claim is made.** This pilot speaks only to whether
   the training changed the model's code-diff production; it does not.

**Recommendation:** treat the code LoRA result as **inconclusive (GO to expand,
not to adopt)**. Do not gate training decisions on N=2. A meaningful code pilot
needs a larger approved code view (the source SWE set is 6,500 records) and a
train/eval split sized for statistical signal, plus a correctness gate that
requires *functional* patch equivalence rather than format shape.

## 8. Artifacts

- `experiments/lora_pilot_code_v0.1/config.json`
- `experiments/lora_pilot_code_v0.1/training_log.json`
- `experiments/lora_pilot_code_v0.1/training_log/step_metrics.csv`
- `experiments/lora_pilot_code_v0.1/checkpoints/` (adapter)
- `experiments/lora_pilot_code_v0.1/evaluation/post_training.json`
- `experiments/lora_pilot_code_v0.1/evaluation/post_training_per_example.jsonl`
- `experiments/lora_pilot_code_v0.1/evaluation/comparison_metrics.json`
- `experiments/lora_pilot_code_v0.1/evaluation/adapter_metadata.json`
- `experiments/lora_pilot_code_v0.1/run_lora_training.py`, `run_lora_eval.py`
