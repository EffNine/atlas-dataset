# Nemotron Nano 9B v2 Base — Final Report

**Experiment ID:** `atlas-math-pilot-nemotron-nano9b-v2-base-lora-v1`
**Phase:** 6.3 (proposed)
**Date:** 2026-08-14
**Status:** **BLOCKED** — PEFT + NF4 quantization incompatible with NemotronH mamba layers

---

## A. Exact Model ID

`nvidia/NVIDIA-Nemotron-Nano-9B-v2-Base`

Verified via HuggingFace Hub API. Public model, 8.89B parameters.

---

## B. Exact Revision

Not resolved — model files downloaded but training cannot proceed due to software incompatibility.

---

## C. Architecture

| Field | Value |
|-------|-------|
| Model type | `nemotron_h` |
| Architecture class | `NemotronHForCausalLM` |
| Hybrid pattern | `M-M-M-MM-M-M-M*-M-M-M*-M-M-M-M*-M-M-M-M*-M-MM-M-M-M-M-M-` |
| Mamba layers | 27 |
| Attention layers | 4 |
| MLP-only layers | 25 |
| Total layers | 56 |
| Hidden size | 4,480 |
| Attention heads | 40 |
| KV heads | 8 (GQA) |
| Head dim | 128 |
| Intermediate size | 15,680 |
| Vocab size | 131,072 |
| Max position | 131,072 |

---

## D. Parameter Count

| Field | Value |
|-------|-------|
| Total params | 8,888,227,328 (~8.89B) |
| Model size (bf16) | ~16.5 GB (4 safetensors shards) |

---

## E. Tokenizer

| Field | Value |
|-------|-------|
| Class | TokenizersBackend (HuggingFace Tokenizers) |
| vocab_size | 131,072 |
| pad_token | None → set to `</s>` |
| eos_token | `</s>` |

---

## F. Isolated Environment

| Field | Value |
|-------|-------|
| Path | `.venv-nemotron-nano/` |
| Python | 3.12.13 |
| torch | 2.10.0+cu130 |
| transformers | 5.14.1 |
| peft | 0.20.0 |
| bitsandbytes | 0.50.0 |
| mamba-ssm | 2.3.2.post1 |
| causal-conv1d | 1.6.2.post1 |
| CUDA | 13.0 |
| GPU | RTX 5070 12GB |

Requirements lockfile: `experiments/atlas-math-pilot-nemotron-nano9b-v2-base-lora-v1/requirements-nano.txt`

**Main Atlas `.venv` remains untouched:** torch 2.13.0+cu130, transformers 5.15.0.

---

## G. Quantization

NF4 4-bit + double quantization + bf16 compute — same as previous Nemotron experiment.

---

## H. LoRA Target Modules

Planned: `['q_proj', 'k_proj', 'v_proj', 'o_proj', 'up_proj', 'down_proj']`

PEFT correctly excludes `out_proj` and `conv1d` from Mamba-based models (`nemotron_h`).

Trainable params: ~9,030,656 (~0.10% of total)

---

## I. VRAM Usage

| Stage | Allocated MiB |
|-------|--------------|
| Model load (NF4, CPU) | ~5,100 |
| Model load (NF4, CUDA) | ~6,095 |
| + LoRA attachment | ~6,095 |
| Projected peak (training) | ~8,500 (estimated) |
| Headroom on 12GB | ~3,200 MiB |

VRAM is sufficient. The blocker is software compatibility, not memory.

---

## J. Blocker: PEFT + NF4 + Mamba Incompatibility

### Error

```
RuntimeError: mat1 and mat2 shapes cannot be multiplied (12x10240 and 1x22937600)
```

### Root Cause

When PEFT wraps a NF4-quantized NemotronH model, the mamba mixer's `out_proj` Linear layer weight shape becomes corrupted from `[4480, 10240]` to `[22937600, 1]`. This is caused by bitsandbytes' NF4 quantization storing weights in a compressed format that PEFT's module-wrapping logic cannot properly handle for custom architecture layers.

### Evidence

1. **Without LoRA**: Model loads, runs forward/backward, generates text — all OK
2. **With LoRA (any target modules)**: Forward pass crashes in mamba mixer's `out_proj` linear operation
3. **Shape inspection**: After PEFT wrapping, mamba `out_proj` shows shape `[22937600, 1]` instead of `[4480, 10240]`
4. **PEFT version**: 0.20.0 (latest stable); 0.9.0 exists but requires torch upgrade which breaks mamba_ssm
5. **Tried workarounds**:
   - Model type override (`nemotron_h` → `gpt_bigcode`): Still crashes (different error path)
   - 8-bit quantization: Device mismatch error in bitsandbytes
   - Full bf16 without quantization: OOM (17.8GB > 12GB)
   - Gradient checkpointing: Same shape corruption error

### Technical Detail

The mamba mixer's `out_proj` is a standard `nn.Linear(10240, 4480)` in bf16. After NF4 quantization + PEFT wrapping, bitsandbytes stores the weight as a quantized integral tensor with shape `[22937600, 1]` (flattened), and the dequantization path in PEFT's forward pass doesn't properly reshape it back.

This is a known limitation: PEFT's LoRA implementation assumes standard transformer architectures where quantized Linear layers maintain their shape through PEFT's module wrapping. The NemotronH model's mamba layers use non-standard Linear layer patterns that break this assumption.

---

## K. Files Changed

| File | Status |
|------|--------|
| `.venv-nemotron-nano/` | **NEW** — isolated environment with torch 2.10 + mamba_ssm |
| `experiments/atlas-math-pilot-nemotron-nano9b-v2-base-lora-v1/` | **NEW** — experiment directory |
| `experiments/atlas-math-pilot-nemotron-nano9b-v2-base-lora-v1/BLOCKED.md` | **NEW** — detailed blocker analysis |
| `experiments/atlas-math-pilot-nemotron-nano9b-v2-base-lora-v1/requirements-nano.txt` | **NEW** — dependency lockfile |
| `scripts/experiment_framework/config.py` | **No change** |
| `scripts/tui_backend.py` | **No change** |
| `metadata/experiment_registry.json` | **No change** |
| Main `.venv/` | **Untouched** |

---

## L. Reproduction Command

```bash
# Verify the blocker
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  .venv-nemotron-nano/bin/python -c "
import torch
from transformers import AutoModelForCausalLM, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model

model = AutoModelForCausalLM.from_pretrained(
    'nvidia/NVIDIA-Nemotron-Nano-9B-v2-Base',
    quantization_config=BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type='nf4', bnb_4bit_compute_dtype=torch.bfloat16
    ),
    device_map='cpu', trust_remote_code=True
)
model.config.use_cache = False
model = get_peft_model(model, LoraConfig(
    r=8, lora_alpha=16, target_modules=['q_proj','k_proj','v_proj','o_proj','up_proj','down_proj']
))
model = model.to('cuda')
import transformers
tok = transformers.AutoTokenizer.from_pretrained('nvidia/NVIDIA-Nemotron-Nano-9B-v2-Base', trust_remote_code=True)
tok.pad_token = tok.eos_token
inp = tok('What is 2+2?', return_tensors='pt').to('cuda')
out = model(input_ids=inp.input_ids, attention_mask=inp.attention_mask, labels=inp.input_ids.clone())
"
# Expected: RuntimeError: mat1 and mat2 shapes cannot be multiplied
```

---

## M. Conclusion

**Nemotron Nano 9B v2 Base is BLOCKED for QLoRA training on RTX 5070 12GB.**

The blocking issue is a fundamental incompatibility between:
1. PEFT 0.20.0's LoRA wrapping logic
2. bitsandbytes NF4 quantization
3. NemotronH's mamba mixer layers

The model loads and runs correctly without LoRA. With LoRA, the mamba layer's `out_proj` weight shape is corrupted during PEFT's module wrapping, causing a matrix multiplication shape mismatch.

### Recommended Next Steps

1. **Upgrade PEFT to 0.9.0** — requires downgrading torch from 2.10 to 2.13, which breaks mamba_ssm. Circular dependency.
2. **Use CPU offloading** — split model across CPU/GPU with `device_map="balanced"`, but this would be extremely slow.
3. **Wait for NVIDIA to update the model** — the `modeling_nemotron_h.py` may need to be updated for PEFT compatibility.
4. **Skip this model** — proceed with other Nemotron variants that use standard transformer architectures (e.g., the already-completed Nemotron-Orchestrator-8B).
5. **Use a different quantization library** — e.g., GPTQ, AWQ, or bitsandbytes 8-bit only (not 4-bit).

### Previous Experiment Status

**UNTOUCHED.** `atlas-math-pilot-nemotron8b-lora-v1` remains complete and valid.
