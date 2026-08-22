# Nemotron-Orchestrator-8B QLoRA Math Pilot — Final Report

**Experiment ID:** `atlas-math-pilot-nemotron8b-lora-v1`
**Phase:** 6.2
**Date:** 2026-08-14
**Status:** TRAINING_COMPLETED → EVALUATION_COMPLETED

---

## A. Model ID / Revision

| Field | Value |
|-------|-------|
| Model ID | `nvidia/Nemotron-Orchestrator-8B` |
| Architecture | Qwen3ForCausalLM |
| Hidden size | 4096 |
| Layers | 36 |
| Attention heads | 32 |
| Vocab size | 151,936 |
| Revision (cache) | `26df4b9aad5abdc5b7871ee4c71063ce888feb26` |
| Total params | 8,212,558,848 |

---

## B. Hardware Compatibility

| Field | Value |
|-------|-------|
| GPU | NVIDIA GeForce RTX 5070 |
| VRAM total | 11,773 MiB |
| CUDA | Available |
| bf16 support | Yes |
| torch | 2.13.0+cu130 |
| transformers | 5.14.1 |
| peft | 0.20.0 |
| bitsandbytes | 0.50.0 |
| accelerate | 1.14.0 |

**Result:** PASS — model fits in 12GB with NF4 quantization + gradient checkpointing.

---

## C. VRAM Usage

| Stage | Allocated MiB | Reserved MiB |
|-------|--------------|--------------|
| Model load (CPU→CUDA) | ~5,877 | ~5,878 |
| Peak during training (seq=1024) | ~8,447 | ~8,712 |
| Peak during evaluation | ~6,335 | — |
| Headroom at peak | — | 3,326 MiB free |

**Note:** Gradient checkpointing was required. Without it, OOM occurred at seq_len=1024.

---

## D. Quantization

| Field | Value |
|-------|-------|
| Type | NF4 4-bit + double quantization |
| Compute dtype | bfloat16 |
| `load_in_4bit` | true |
| `bnb_4bit_use_double_quant` | true |

---

## E. LoRA Configuration

| Field | Value |
|-------|-------|
| r | 8 |
| lora_alpha | 16 |
| lora_dropout | 0.05 |
| bias | none |
| task_type | CAUSAL_LM |
| Target modules | q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj |
| Trainable params | 21,823,488 (0.266% of total) |

---

## F. Training Configuration

| Field | Value |
|-------|-------|
| Seed | 42 |
| Max seq length | 1024 |
| Max steps | 60 |
| Batch size | 1 |
| Gradient accumulation | 8 |
| Effective batch size | 8 |
| Learning rate | 2e-4 |
| Weight decay | 0.01 |
| LR scheduler | cosine |
| Warmup ratio | 0.03 |
| Optimizer | paged_adamw_8bit |
| Max grad norm | 1.0 |
| bf16 | true |
| Gradient checkpointing | true |
| Training view | math_300m_v0.1 (117 records) |
| Train JSONL SHA-256 | `6aecc2a7...a4572` (matched) |

---

## G. Smoke Test Result

**PASS**

- 60 optimizer steps completed
- Loss decreased: 1.2829 → 0.3552
- No NaN/Inf gradients
- No CUDA OOM
- Checkpoint saved and reloaded successfully
- Throughput: 631.56 tok/s mean
- Wall time: 263.5s

---

## H. Pilot Training Result

| Metric | Value |
|--------|-------|
| Steps completed | 60 |
| Final loss | 0.35517 |
| Min loss | 0.19887 |
| Peak VRAM | 8,446.8 MiB |
| Throughput | 631.56 tok/s |
| Wall time | 263.543s |
| Examples consumed | 480 (60 × 8 accum) |

---

## I. Checkpoint

| Field | Value |
|-------|-------|
| Path | `experiments/atlas-math-pilot-nemotron8b-lora-v1/checkpoints/` |
| Adapter file | `adapter_model.safetensors` (84 MB) |
| SHA-256 | `759ee618c582bf06ca09cc6c30a264618148c57c4960aa826836738e7d52c777` |
| Config | `adapter_config.json` (r=8, alpha=16) |

---

## J. Resume / Reload Verification

**PASS**

- Checkpoint saved via `model.save_pretrained()`
- Reloaded via `PeftModel.from_pretrained(base_model, checkpoint_dir)`
- Inference test: "What is 2+2?" → "What is 2+2? Also, can you explain the concept of addition in mathematics?\\n\\n2+2 equals 4. Addition"
- Trainable params on reload: 0 (correct — base model params are frozen)

---

## K. Evaluation Result

| Metric | Value |
|--------|-------|
| Correctness | 0.8462 |
| Reasoning quality | 0.8292 |
| Hallucination rate | 0.1538 |
| Answer format consistency | 0.9231 |
| Evaluated examples | 13/13 |
| Latency mean | 2.83s |
| Tokens/sec mean | 11.45 |
| Engine | QEE v2 (math dispatch) |
| Eval split | `output/training_views/math_300m_v0.1/eval.jsonl` |

---

## L. G-POL / Truncation

| Field | Value |
|-------|-------|
| Max new tokens | 256 |
| Sampling | greedy (do_sample=False) |
| Truncation | None observed in 13/13 examples |
| G-POL | Not explicitly measured in this pilot (small N) |

**Note:** N=13 is below the benchmark plan gate of N≥30. G-POL/truncation metrics should be captured in the expanded eval split.

---

## M. TUI Integration

**PASS**

- Experiment registered in `metadata/experiment_registry.json`
- Experiment visible in TUI Experiments view
- Status: `TRAINING_COMPLETED`
- All 22 TUI experiment tests pass

---

## N. Tests

| Test Suite | Result |
|------------|--------|
| `tests/test_tui.py` (experiment-related, 22 tests) | **22 PASS** |
| Full suite (1229 tests) | 1220 PASS, 9 FAIL (pre-existing, unrelated) |

The 9 pre-existing failures are in `test_release_pipeline.py` and `test_scheduler_compression.py` — not caused by this change.

---

## O. Files Changed

### New files
```
experiments/atlas-math-pilot-nemotron8b-lora-v1/
├── config.json
├── run_lora_training.py
├── run_lora_eval.py
├── checkpoints/
│   ├── adapter_config.json
│   ├── adapter_model.safetensors
│   └── README.md
├── training_log/
│   └── step_metrics.csv
├── training_log.json
└── evaluation/
    ├── post_training.json
    ├── post_training_per_example.jsonl
    └── adapter_metadata.json
```

### Modified files
```
scripts/experiment_framework/config.py   (+nemotron8b target)
scripts/tui_backend.py                   (+Nemotron experiment entry)
metadata/experiment_registry.json        (+Nemotron registry record)
```

---

## P. Exact Command to Reproduce

```bash
cd /home/afnan/projects/active/atlas-dataset

# Training smoke test (60 steps)
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  .venv/bin/python experiments/atlas-math-pilot-nemotron8b-lora-v1/run_lora_training.py

# Evaluation
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  .venv/bin/python experiments/atlas-math-pilot-nemotron8b-lora-v1/run_lora_eval.py

# TUI
.venv/bin/python scripts/atlas_tui.py
```

---

## Q. Is Nemotron READY for Longer Production Training?

**YES — with caveats.**

### Confirmed
- Model loads and runs on RTX 5070 12GB with NF4 + gradient checkpointing
- Loss is finite and decreasing (1.28 → 0.36 over 60 steps)
- Checkpoint save/reload is intact
- No NaN/Inf gradients
- Evaluation runs successfully with QEE v2
- TUI integration works

### Caveats
1. **N=13 eval** — below the benchmark plan gate of N≥30. Expand eval split before claiming capability results.
2. **Gradient checkpointing required** — without it, OOM at seq_len=1024. This ~30% speed penalty is acceptable for pilot but should be profiled for production.
3. **No baseline comparison** — this pilot trains from scratch on math data; no pre/post comparison against Qwen2.5-7B baseline on the same split.
4. **G-POL not measured** — generation policy compliance should be verified on the expanded eval set.

### Recommendation
Proceed to expanded pilot (`atlas-math-small-nemotron8b-lora-v1`) with:
- N≥30 eval split (per benchmark_plan.md first gate)
- Baseline evaluation of untrained Nemotron-Orchestrator-8B on same split
- G-POL / truncation tracking
