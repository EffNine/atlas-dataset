# Phase 3A — Controlled LoRA Validation Pilot: Math v0.1

## Purpose
Validate whether the approved `math-300m` training view improves mathematical reasoning
in a small QLoRA experiment before any broader training investment.

## Scope
- NOT production training
- NOT model release
- NOT dataset modification

## Approved Training View
- `output/training_views/math_300m_v0.1`
- Source: `expert-math-002` / OpenMathInstruct-2
- License: CC-BY-4.0
- Train: 117 records
- Eval: 13 records
- Determinism: train/eval checksums verified stable; see `config.json`

## Experiment Layout
```text
experiments/lora_pilot_math_v0.1/
├── config.json
├── README.md
├── training_log/
├── checkpoints/
└── evaluation/
```

## Target Configuration
- Base model: `Qwen/Qwen2.5-7B-Instruct`
- Adapter: QLoRA 4-bit NF4
- Intended GPU: NVIDIA RTX 5070 12GB
- Seed: 42

## Current Status
`HOLD` — training is blocked because this execution environment does not have a CUDA-capable NVIDIA GPU.
Baseline evaluation artifacts were created; post-training evaluation and final GO/HOLD report
depend on running this experiment on the CUDA box.

## Reproducibility
To rerun:
1. Use a CUDA Linux/WSL2 environment with RTX 5070.
2. Install exact package versions into a clean venv.
3. Verify dataset checksums in `config.json`.
4. Run baseline evaluation.
5. Run training with recorded seed/config.
6. Run post-training evaluation.
7. Write `reports/lora_pilot_math_v0.1.json`.

## Success Criteria
- No dataset checksum mismatch
- Reproducible baseline metrics
- Measurable before/after deltas with documented limitations

## Safety
Do not promote the adapter, push weights, or claim improvement without evaluation artifacts.
