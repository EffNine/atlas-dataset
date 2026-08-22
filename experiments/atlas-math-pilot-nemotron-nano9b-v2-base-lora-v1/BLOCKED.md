# Nemotron Nano 9B v2 Base — Experiment Report

**Experiment ID:** `atlas-math-pilot-nemotron-nano9b-v2-base-lora-v1`
**Phase:** 6.3 (proposed)
**Date:** 2026-08-14
**Status:** **BLOCKED** — model cannot be loaded in current environment

---

## A. Exact Model ID

`nvidia/NVIDIA-Nemotron-Nano-9B-v2-Base`

Verified via HuggingFace Hub API. This is the **only** public model matching "Nemotron Nano 9B v2 Base" from NVIDIA.

---

## B. Exact Revision

Not resolved — model files downloaded for inspection but model cannot be loaded due to dependency failure.

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

**This is a hybrid Mamba-Transformer architecture** (similar to NVIDIA's Jamba model), NOT a standard transformer. It requires the `mamba-ssm` library for its SSM/Mamba2 layers.

---

## D. Parameter Count

| Field | Value |
|-------|-------|
| Total parameters | 8,888,227,328 (~8.89B) |
| Model size (bf16) | ~16.5 GB (4 safetensors shards) |
| Hidden size | 4,480 |
| Intermediate size | 15,680 |
| Vocab size | 131,072 |
| Max position embeddings | 131,072 |

---

## E. Tokenizer

| Field | Value |
|-------|-------|
| Class | TokenizersBackend (HuggingFace Tokenizers) |
| vocab_size | 131,072 |
| pad_token | None (needs setting to eos_token) |
| eos_token | `</s>` |
| bos_token | `<s>` |
| model_max_length | 131,072 |

---

## F. Dependencies Required

| Package | Required For |
|---------|-------------|
| `mamba-ssm` | Mamba2 mixer layers (`mixer.in_proj`, `mixer.out_proj`, SSM kernel) |
| `causal-conv1d` | Conv1d layer in Mamba2 mixer |

Both packages require CUDA C++ compilation against the exact PyTorch version.

---

## G. LoRA Target Modules (planned)

Based on architecture inspection:

| Module type | Layer names | Count |
|-------------|-------------|-------|
| Attention | `layers.*.mixer.q_proj`, `k_proj`, `v_proj`, `o_proj` | ~16 |
| Mamba | `layers.*.mixer.in_proj`, `mixer.out_proj` | ~54 |
| MLP | `layers.*.mixer.up_proj`, `mixer.down_proj` | ~50 |

**Note:** Unlike the previous Nemotron-Orchestrator-8B (Qwen3ForCausalLM with standard `q_proj/k_proj/v_proj/o_proj/gate_proj/up_proj/down_proj`), this model uses a `mixer.*` naming convention because each layer contains a hybrid mixer component.

---

## H. BLOCKER: mamba-ssm Incompatibility

### Root Cause

The `mamba-ssm` package (required by the NemotronH architecture) has **no pre-built wheel compatible with PyTorch 2.13.0**.

### Evidence

1. **All pre-built wheels** on the [mamba-ssm GitHub releases](https://github.com/state-spaces/mamba/releases) are compiled against PyTorch 2.9 or 2.10:
   - `cu13torch2.9` — CUDA 13, PyTorch 2.9
   - `cu13torch2.10` — CUDA 13, PyTorch 2.10
   - `cu13torch25.xx` / `cu13torch26.xx` — NVIDIA internal torch versioning (not compatible)

2. **No wheel for PyTorch 2.13** exists on any index (PyPI, NVIDIA, PyTorch whl).

3. **Source build fails** — `mamba-ssm` requires CUDA Triton kernel compilation which fails in the current environment (missing build tools / CUDA toolkit mismatch).

4. **Attempted workaround — downgrading PyTorch to 2.10:**
   - Installing `torch==2.10.0+cu130` resolves the mamba_ssm import
   - BUT it breaks `transformers>=5.14`, `peft>=0.20`, and `bitsandbytes>=0.50` which require PyTorch 2.13+
   - The environment cannot run both the old experiments (which require torch 2.13) and mamba-ssm simultaneously

### Specific Error

```
ImportError: selective_scan_cuda.cpython-312-x86_64-linux-gnu.so:
undefined symbol: _ZN3c104impl3cow23materialize_cow_storageERNS_11StorageImplE
```

This symbol (`c10::impl::cow::materialize_cow_storage`) was **removed from PyTorch's C++ ABI between 2.10 and 2.13**. The mamba_ssm CUDA extension was compiled against the 2.10 ABI and cannot link against 2.13.

---

## I. VRAM Projection

| Stage | Projected VRAM |
|-------|---------------|
| Model load (NF4 quantized) | ~5,000 MiB |
| + LoRA attachment | ~5,100 MiB |
| + Gradient checkpointing | ~5,800 MiB |
| Training (seq=1024, batch=1) | ~8,500 MiB (projected) |
| Headroom on 12GB | ~3,200 MiB |

The model is **smaller** than Nemotron-Orchestrator-8B (8.89B vs ~8.2B but with more efficient architecture). VRAM should be compatible with the RTX 5070 12GB using the same proven configuration.

---

## J. Suggested Fixes

### Option 1: Downgrade PyTorch (breaks existing experiments)
Downgrade to PyTorch 2.10.0, then downgrade transformers/peft/bitsandbytes to compatible versions. This would break the existing `atlas-math-pilot-nemotron8b-lora-v1` experiment infrastructure.

### Option 2: Upgrade mamba-ssm (not available)
Wait for `mamba-ssm` to release wheels for PyTorch 2.13. As of 2026-08, no such wheel exists.

### Option 3: Use a different machine
Run on a machine with PyTorch 2.10 installed, or use a container with the correct dependency stack.

### Option 4: Skip this model
Proceed with other Nemotron models that don't require mamba-ssm (e.g., the already-completed Nemotron-Orchestrator-8B).

---

## K. Previous Experiment Status

**UNTOUCHED.** The `atlas-math-pilot-nemotron8b-lora-v1` experiment remains complete and valid:
- Checkpoint: `experiments/atlas-math-pilot-nemotron8b-lora-v1/checkpoints/adapter_model.safetensors`
- SHA-256: `759ee618c582bf06ca09cc6c30a264618148c57c4960aa826836738e7d52c777`
- Status: TRAINING_COMPLETED, EVALUATION_COMPLETED

---

## L. Conclusion

**Nemotron Nano 9B v2 Base is NOT READY for training in the current environment.**

The blocking issue is the `mamba-ssm` dependency, which has no PyTorch 2.13-compatible pre-built wheel and cannot be built from source in this environment. This is a hard dependency — the model's `modeling_nemotron_h.py` raises `ImportError("mamba-ssm is required by the Mamba model but cannot be imported")` if the package is unavailable.

**No model substitution was made.** The requested model was verified but cannot run.

---

## M. Files Changed

| File | Status |
|------|--------|
| `scripts/experiment_framework/config.py` | **No change** (nemotron8b target already exists from previous experiment) |
| `scripts/tui_backend.py` | **No change** |
| `metadata/experiment_registry.json` | **No change** |
| `experiments/atlas-math-pilot-nemotron-nano9b-v2-base-lora-v1/` | **Not created** (experiment blocked before creation) |

**No files were modified.** The environment was reverted to its original state after the compatibility investigation.

---

## N. Reproduction Command

```bash
# Verify the blocker
/home/afnan/projects/active/atlas-dataset/.venv/bin/python -c "
from transformers import AutoModelForCausalLM, BitsAndBytesConfig
import torch
model_id = 'nvidia/NVIDIA-Nemotron-Nano-9B-v2-Base'
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_use_double_quant=True,
                          bnb_4bit_quant_type='nf4', bnb_4bit_compute_dtype=torch.bfloat16)
model = AutoModelForCausalLM.from_pretrained(model_id, quantization_config=bnb,
                                               device_map='cpu', trust_remote_code=True)
" 2>&1
# Expected: ImportError: mamba-ssm is required by the Mamba model but cannot be imported
```
