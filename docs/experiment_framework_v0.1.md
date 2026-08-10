# Atlas QLoRA Experiment Framework

> **Phase:** 5B  
> **Version:** 0.1.0  
> **Date:** 2026-08-07  
> **Status:** Implementation complete — awaiting Technical Lead review

---

## 1. Overview

This framework provides the infrastructure for managing QLoRA training experiments under the **Atlas Research Protocol v1.0**. It is the canonical foundation for all future experiment runs, ensuring:

- **Reproducibility**: Every experiment is pinned to git commit, dataset checksum, model revision, config, and seed.
- **Governance**: All outputs are written under `experiments/{id}/` — never touching frozen `curated/`, `raw/`, `review_queue/`, or `training_views/`.
- **Transfer analysis**: Built-in support for cross-domain gain computation and Transfer Ratio per protocol §8.
- **Fail-closed**: Checksum mismatches abort training immediately; unverifiable metrics produce HOLD artifacts.

---

## 2. Architecture

```
scripts/experiment_framework/
├── __init__.py          # Public API exports
├── config.py            # ExperimentConfig, QuantizationConfig, LoRAConfig, TrainingConfig
├── registry.py          # ExperimentRegistry, ExperimentRecord, ExperimentStatus
├── scaffold.py          # ExperimentScaffold — directory layout generator
├── metadata.py          # RunMetadata, CheckpointMetadata, SHA-256 utilities
├── manifests.py         # DatasetManifest, TrainingManifest, EvaluationManifest
├── results.py           # ResultRegistry, ResultEntry, AggregateMetrics
├── training_runner.py   # TrainingRunner base class (abstract train_step)
├── eval_runner.py       # EvaluationRunner base class (abstract generate/score)
└── reproducibility.py   # ReproducibilityChecklist (15 protocol §4 checks)
```

---

## 3. Public API

### 3.1 Experiment Configuration

```python
from scripts.experiment_framework import ExperimentConfig

# Create a math pilot config
config = ExperimentConfig(
    experiment_id="atlas-math-pilot-qwen7b-lora-v1",
    phase="5B.1",
    training_view_id="math_300m_v0.1",
)

# Access parsed fields
print(config.family)    # "math"
print(config.tier)      # "pilot"
print(config.target)    # "qwen7b"
print(config.scope)     # "lora"
print(config.version)   # 1

# Save to JSON
config.save("experiments/atlas-math-pilot-qwen7b-lora-v1/config.json")

# Load from JSON
config = ExperimentConfig.from_file("path/to/config.json")
```

### 3.2 Experiment Registry

```python
from scripts.experiment_framework import ExperimentRegistry, ExperimentStatus

registry = ExperimentRegistry()  # defaults to metadata/experiment_registry.json

# Create
record = registry.create(config)

# Query
by_family = registry.list_by_family("math")
by_tier = registry.list_by_tier("pilot")
holds = registry.list_holds()
completed = registry.list_completed()

# Update
registry.update("atlas-math-pilot-qwen7b-lora-v1",
                status=ExperimentStatus.TRAINING_COMPLETED,
                git_commit="abc123")

# Summary
print(registry.summary())
```

### 3.3 Experiment Scaffold

```python
from scripts.experiment_framework import ExperimentScaffold

scaffold = ExperimentScaffold(
    "atlas-math-pilot-qwen7b-lora-v1",
    experiments_root=Path("experiments"),
)
paths = scaffold.create()

# Access standard paths
print(scaffold.checkpoints_dir)       # experiments/.../checkpoints/
print(scaffold.training_log_dir)      # experiments/.../training_log/
print(scaffold.evaluation_dir)        # experiments/.../evaluation/

# All artifact paths
artifacts = scaffold.get_artifact_paths()
# {
#   "config": ..., "training_log": ..., "step_metrics": ...,
#   "adapter_config": ..., "post_training_eval": ..., ...
# }
```

### 3.4 Run Metadata

```python
from scripts.experiment_framework import RunMetadata, compute_sha256, git_info

# Collect pre-run metadata
meta = RunMetadata.collect(
    experiment_id="atlas-math-pilot-qwen7b-lora-v1",
    phase="5B.1",
    train_jsonl_path=Path("output/training_views/math_300m_v0.1/train.jsonl"),
    approved_train_sha256="6aecc2a7...",
)

# Validate
errors = meta.validate()
if errors:
    for e in errors:
        print(f"VALIDATION ERROR: {e}")

# Git info
git = git_info()
# {"git_commit": "d1fb931...", "git_short": "d1fb931", "git_status_clean": "true"}
```

### 3.5 Manifests

```python
from scripts.experiment_framework import DatasetManifest, TrainingManifest, EvaluationManifest

# Dataset manifest
train_manifest = DatasetManifest.create(
    dataset_id="math_train_v1",
    file_path=Path("output/training_views/math_300m_v0.1/train.jsonl"),
    split_type="train",
    approved_sha256="6aecc2a7...",
)

# Training manifest
training_manifest = TrainingManifest.create(config, train_manifest)

# Evaluation manifest
eval_manifest = EvaluationManifest.create(
    experiment_id="atlas-math-pilot-qwen7b-lora-v1",
    eval_jsonl_path=Path("output/training_views/math_300m_v0.1/eval.jsonl"),
    eval_split_id="math_eval_v1",
    engine="QEE v2",
    baseline_experiment_id="baseline_eval_v0.2",
)
```

### 3.6 Result Registry

```python
from scripts.experiment_framework import ResultRegistry, ResultEntry, AggregateMetrics

registry = ResultRegistry()

# Add result
registry.add(ResultEntry(
    experiment_id="atlas-math-pilot-qwen7b-lora-v1",
    evaluation_id="post_training",
    status="COMPLETE",
    model="LORA_ADAPTER",
    model_id="Qwen/Qwen2.5-7B-Instruct",
    aggregate=AggregateMetrics(
        correctness=0.6538,
        evaluated_examples=13,
        total_examples=13,
    ),
))

# Compare with baseline
comparison = registry.compare("baseline_eval_v0.2", "atlas-math-pilot-qwen7b-lora-v1")
# {"baseline_value": 0.6109, "experimental_value": 0.6538, "delta": 0.0429}
```

### 3.7 Reproducibility Checklist

```python
from scripts.experiment_framework import ReproducibilityChecklist, ChecklistStatus

rc = ReproducibilityChecklist("atlas-math-pilot-qwen7b-lora-v1")

# Mark checks
rc.check_item(1, ChecklistStatus.PASS, "git commit: d1fb931")
rc.check_item(2, ChecklistStatus.PASS, "train sha256: 6aecc2a7...")
# ... etc for all 15 checks

# Validate an experiment directory
errors = rc.validate_experiment(Path("experiments/atlas-math-pilot-qwen7b-lora-v1"))
if errors:
    for e in errors:
        print(f"CHECKLIST ERROR: {e}")

# Save/load
rc.save("experiments/atlas-math-pilot-qwen7b-lora-v1/reproducibility_checklist.json")
rc2 = ReproducibilityChecklist.load("path/to/checklist.json")
```

### 3.8 Training Runner (Base Class)

```python
from scripts.experiment_framework import TrainingRunner, ExperimentConfig

class MyTrainingRunner(TrainingRunner):
    def train_step(self, example):
        # Subclass implements the actual training step
        # Returns (loss, tokens, mem_alloc_mib, mem_reserved_mib)
        ...

# Usage
config = ExperimentConfig.from_file("path/to/config.json")
runner = MyTrainingRunner(
    config=config,
    train_jsonl_path=Path("output/training_views/math_300m_v0.1/train.jsonl"),
    approved_train_sha256="6aecc2a7...",
)

# Setup: create scaffold, verify checksums
metadata = runner.setup()

# Run training loop
step_logs = runner.run_training_loop(
    examples=examples,
    max_steps=60,
    grad_accum_steps=8,
)

# Save checkpoint
checkpoint = runner.save_checkpoint(model, trainable_params, total_params)

# Finalize
results = runner.finalize()
```

### 3.9 Evaluation Runner (Base Class)

```python
from scripts.experiment_framework import EvaluationRunner

class MyEvalRunner(EvaluationRunner):
    def generate_response(self, record):
        # Subclass implements inference
        ...
    def score_response(self, record, response):
        # Subclass implements scoring
        ...

# Usage
runner = MyEvalRunner(
    experiment_id="atlas-math-pilot-qwen7b-lora-v1",
    eval_jsonl_path=Path("output/training_views/math_300m_v0.1/eval.jsonl"),
    eval_split_id="math_eval_v1",
    engine="QEE v2",
    baseline_experiment_id="baseline_eval_v0.2",
)

# Run evaluation
result = runner.run_evaluation(output_dir=Path("experiments/.../evaluation"))

# Compute transfer analysis
analysis = runner.compute_transfer_analysis(
    baseline_results=baseline_per_example,
    metric="correctness",
    tau=0.05,
)
```

---

## 4. Experiment Directory Layout

Every experiment created by the framework follows this canonical layout:

```
experiments/{experiment_id}/
├── config.json                    # Full experiment configuration
├── experiment_manifest.json       # Pre-run manifest (dataset + model + evaluator)
├── pre_run_metadata.json          # Git, checksums, hardware collected before training
├── training_log.json              # Post-training log
├── training_log/
│   ├── step_metrics.csv           # Per-optimizer-step metrics
│   └── console.log                # Captured stdout
├── checkpoints/
│   ├── adapter_config.json        # PEFT adapter config (auto-saved)
│   ├── adapter_model.safetensors  # Adapter weights (auto-saved)
│   └── checkpoint_metadata.json   # Checkpoint provenance
├── evaluation/
│   ├── post_training.json         # Aggregate eval results
│   ├── post_training_per_example.jsonl  # Per-example results
│   ├── adapter_metadata.json      # Adapter verification
│   └── comparison_metrics.json    # Baseline vs post-training
├── analysis/                      # (created on demand)
│   ├── p8a_transfer_analysis.json
│   └── p8a_per_example_deltas.jsonl
├── reproducibility_checklist.json # Protocol §4 checklist
└── README.md                      # Auto-generated scaffold README
```

---

## 5. Protocol Compliance

The framework enforces the Atlas Research Protocol v1.0 requirements:

| Protocol Requirement | Framework Implementation |
|---------------------|--------------------------|
| Naming convention (§2) | `EXPERIMENT_NAME_PATTERN` regex validation in `ExperimentConfig` |
| Pre-run metadata (§3.1) | `RunMetadata.collect()` captures git, checksums, hardware |
| Checksum verification (§4.2-3) | `DatasetManifest.create()` computes raw + records SHA-256 |
| Seed management (§4.7) | `TrainingConfig.seed` with `set_seed()` in runners |
| Engine version recording (§4.8) | `EvaluationManifest.engine_commit` field |
| Baseline recording (§4.11) | `EvaluationRunner.baseline_experiment_id` |
| Fail-closed rule (§4.15) | `RunMetadata.validate()` raises on checksum mismatch |
| Transfer Ratio (§8.2) | `TransferAnalysis.compute_transfer_ratio()` |
| Transfer type taxonomy (§8.3) | `TransferAnalysis.classify_transfer_type()` |

---

## 6. Configuration Examples

See `configs/experiment_examples/qlora_experiment_examples.json` for complete examples:

1. **math_pilot** — Phase 5B.1 validated baseline (N=117 train, N=13 eval)
2. **math_small_transfer** — Phase 8 P8-A cross-domain (N=400 train, N=100 eval)
3. **baseline_eval** — Protocol v2 baseline (inference-only)

---

## 7. Unit Tests

```bash
# Run all experiment framework tests
python3 -m pytest tests/test_experiment_framework/ -v

# Run a specific test file
python3 -m pytest tests/test_experiment_framework/test_config.py -v
python3 -m pytest tests/test_experiment_framework/test_registry.py -v
python3 -m pytest tests/test_experiment_framework/test_metadata.py -v
python3 -m pytest tests/test_experiment_framework/test_manifests.py -v
python3 -m pytest tests/test_experiment_framework/test_results.py -v
python3 -m pytest tests/test_experiment_framework/test_scaffold.py -v
python3 -m pytest tests/test_experiment_framework/test_reproducibility.py -v
```

**Results:** 132 passed, 0 failed.

---

## 8. Do Not

- **Do not modify** `curated/`, `raw/`, `review_queue/`, or `training_views/` directly.
- **Do not** change frozen dataset versions or evaluation engine code.
- **Do not** fabricate metrics — use `HOLD` artifacts with null metrics when unverifiable.
- **Do not** train without passing the reproducibility checklist.
- **Do not** claim results from underpowered eval splits (N < 30 per protocol §7).

---

## 9. Future Work

- [ ] Integrate with `scripts/atlas.py` CLI entry point
- [ ] Add checkpoint/resume support to `TrainingRunner`
- [ ] Add seed sweep support for symmetry analysis (RQ5)
- [ ] Add CI integration for automatic checklist verification
- [ ] Add human approval gate integration with automation layer

---

*Framework version: 0.1.0 | Protocol version: v1.1 | Last updated: 2026-08-07*
