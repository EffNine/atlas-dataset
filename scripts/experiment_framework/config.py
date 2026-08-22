#!/usr/bin/env python3
"""
config.py — Experiment configuration dataclasses.

Defines the canonical configuration structures for QLoRA experiments,
including experiment naming, quantization, LoRA hyperparameters, and
training hyperparameters. Follows the Atlas Research Protocol v1.0
naming convention: atlas-{family}-{tier}-{target}-{scope}-v{n}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any

# ---------------------------------------------------------------------------
# Naming convention constants
# ---------------------------------------------------------------------------

EXPERIMENT_NAME_PATTERN = re.compile(
    r"^atlas-("
    + "|".join([
        "math", "code", "aiml", "mixed",
    ])
    + r")-("
    + "|".join([
        "pilot", "small", "medium", "large", "prod",
    ])
    + r")-("
    + "|".join([
        "qwen7b", "llama8b", "deepseek8b", "mistral7b", "gemma7b", "nemotron8b",
    ])
    + r")-("
    + "|".join([
        "base", "lora", "full", "hp", "scale", "transfer", "eval",
    ])
    + r")-v(\d+)$"
)

VALID_FAMILIES: frozenset[str] = frozenset(["math", "code", "aiml", "mixed"])
VALID_TIERS: frozenset[str] = frozenset(["pilot", "small", "medium", "large", "prod"])
VALID_TARGETS: frozenset[str] = frozenset(["qwen7b", "llama8b", "deepseek8b", "mistral7b", "gemma7b", "nemotron8b"])
VALID_SCOPES: frozenset[str] = frozenset(["base", "lora", "full", "hp", "scale", "transfer", "eval"])

# ---------------------------------------------------------------------------
# Default locked values (Phase 5B.1 / Phase 7.2 validated configuration)
# ---------------------------------------------------------------------------

DEFAULT_BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
DEFAULT_SEED = 42
DEFAULT_MAX_SEQ_LENGTH = 1024
DEFAULT_MAX_STEPS = 60
DEFAULT_BATCH_SIZE = 1
DEFAULT_GRAD_ACCUMULATION = 8
DEFAULT_LEARNING_RATE = 2e-4
DEFAULT_WEIGHT_DECAY = 0.01
DEFAULT_WARMUP_RATIO = 0.03
DEFAULT_LR_SCHEDULE = "cosine"
DEFAULT_OPTIMIZER = "paged_adamw_8bit"
DEFAULT_MAX_GRAD_NORM = 1.0
DEFAULT_LORA_R = 8
DEFAULT_LORA_ALPHA = 16
DEFAULT_LORA_DROPOUT = 0.05
DEFAULT_TARGET_MODULES = [
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
]
DEFAULT_QUANT_TYPE = "nf4"
DEFAULT_COMPUTE_DTYPE = "bfloat16"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class QuantizationConfig:
    """QLoRA quantization configuration."""
    load_in_4bit: bool = True
    bnb_4bit_use_double_quant: bool = True
    bnb_4bit_quant_type: str = DEFAULT_QUANT_TYPE
    bnb_4bit_compute_dtype: str = DEFAULT_COMPUTE_DTYPE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QuantizationConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def __post_init__(self):
        if self.bnb_4bit_quant_type not in ("nf4", "fp4"):
            raise ValueError(
                f"bnb_4bit_quant_type must be 'nf4' or 'fp4', got {self.bnb_4bit_quant_type!r}"
            )
        if self.bnb_4bit_compute_dtype not in ("bfloat16", "float16", "float32"):
            raise ValueError(
                f"bnb_4bit_compute_dtype must be 'bfloat16', 'float16', or 'float32', "
                f"got {self.bnb_4bit_compute_dtype!r}"
            )


@dataclass
class LoRAConfig:
    """LoRA adapter configuration."""
    r: int = DEFAULT_LORA_R
    lora_alpha: int = DEFAULT_LORA_ALPHA
    lora_dropout: float = DEFAULT_LORA_DROPOUT
    bias: str = "none"
    task_type: str = "CAUSAL_LM"
    target_modules: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.target_modules:
            self.target_modules = list(DEFAULT_TARGET_MODULES)
        if self.bias not in ("none", "all", "lora_only"):
            raise ValueError(f"bias must be 'none', 'all', or 'lora_only', got {self.bias!r}")
        if self.task_type != "CAUSAL_LM":
            raise ValueError(f"task_type must be 'CAUSAL_LM', got {self.task_type!r}")
        if self.r <= 0:
            raise ValueError(f"r must be positive, got {self.r}")
        if self.lora_alpha <= 0:
            raise ValueError(f"lora_alpha must be positive, got {self.lora_alpha}")
        if not (0.0 <= self.lora_dropout <= 1.0):
            raise ValueError(f"lora_dropout must be in [0, 1], got {self.lora_dropout}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LoRAConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class TrainingConfig:
    """Training hyperparameter configuration."""
    seed: int = DEFAULT_SEED
    max_seq_length: int = DEFAULT_MAX_SEQ_LENGTH
    max_steps: int = DEFAULT_MAX_STEPS
    per_device_train_batch_size: int = DEFAULT_BATCH_SIZE
    gradient_accumulation_steps: int = DEFAULT_GRAD_ACCUMULATION
    learning_rate: float = DEFAULT_LEARNING_RATE
    weight_decay: float = DEFAULT_WEIGHT_DECAY
    lr_scheduler_type: str = DEFAULT_LR_SCHEDULE
    warmup_ratio: float = DEFAULT_WARMUP_RATIO
    optim: str = DEFAULT_OPTIMIZER
    max_grad_norm: float = DEFAULT_MAX_GRAD_NORM
    bf16: bool = True
    gradient_checkpointing: bool = True

    @property
    def effective_batch_size(self) -> int:
        return self.per_device_train_batch_size * self.gradient_accumulation_steps

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["effective_batch_size"] = self.effective_batch_size
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrainingConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def __post_init__(self):
        if self.seed < 0:
            raise ValueError(f"seed must be non-negative, got {self.seed}")
        if self.max_seq_length <= 0:
            raise ValueError(f"max_seq_length must be positive, got {self.max_seq_length}")
        if self.max_steps <= 0:
            raise ValueError(f"max_steps must be positive, got {self.max_steps}")
        if self.per_device_train_batch_size <= 0:
            raise ValueError(f"per_device_train_batch_size must be positive, got {self.per_device_train_batch_size}")
        if self.gradient_accumulation_steps <= 0:
            raise ValueError(f"gradient_accumulation_steps must be positive, got {self.gradient_accumulation_steps}")
        if self.learning_rate <= 0:
            raise ValueError(f"learning_rate must be positive, got {self.learning_rate}")
        if not (0.0 <= self.weight_decay <= 1.0):
            raise ValueError(f"weight_decay must be in [0, 1], got {self.weight_decay}")
        if not (0.0 <= self.warmup_ratio <= 1.0):
            raise ValueError(f"warmup_ratio must be in [0, 1], got {self.warmup_ratio}")
        if self.lr_scheduler_type not in ("cosine", "linear", "constant", "constant_with_warmup"):
            raise ValueError(
                f"lr_scheduler_type must be one of cosine/linear/constant/constant_with_warmup, "
                f"got {self.lr_scheduler_type!r}"
            )
        if self.optim not in ("paged_adamw_8bit", "adamw_torch", "adamw_apex"):
            raise ValueError(f"optim must be one of paged_adamw_8bit/adamw_torch/adamw_apex, got {self.optim!r}")
        if self.max_grad_norm <= 0:
            raise ValueError(f"max_grad_norm must be positive, got {self.max_grad_norm}")


@dataclass
class ExperimentConfig:
    """
    Canonical experiment configuration.

    This is the primary configuration object for any QLoRA experiment.
    It combines experiment-level metadata (id, phase, family, tier, etc.)
    with model, quantization, LoRA, and training hyperparameters.

    The configuration is validated against the Atlas Research Protocol v1.0
    naming convention and locked defaults where applicable.
    """
    experiment_id: str
    phase: str
    training_view_id: str
    base_model: str = DEFAULT_BASE_MODEL
    model_revision: str | None = None
    quantization: QuantizationConfig = field(default_factory=QuantizationConfig)
    lora: LoRAConfig = field(default_factory=LoRAConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)

    # Optional fields for cross-domain transfer experiments
    sprint: str | None = None
    direction: str | None = None
    research_question: str | None = None
    hypothesis: str | None = None
    expected_outcome: str | None = None

    # Optional fields for evaluation-only experiments
    eval_splits: dict[str, str] | None = None  # family -> path

    def __post_init__(self):
        self._validate_experiment_id()

    def _validate_experiment_id(self) -> None:
        """Validate experiment ID against protocol naming convention."""
        if not EXPERIMENT_NAME_PATTERN.match(self.experiment_id):
            raise ValueError(
                f"experiment_id {self.experiment_id!r} does not match the protocol "
                f"naming convention: atlas-{{family}}-{{tier}}-{{target}}-{{scope}}-v{{n}}\n"
                f"  family must be one of: {sorted(VALID_FAMILIES)}\n"
                f"  tier must be one of: {sorted(VALID_TIERS)}\n"
                f"  target must be one of: {sorted(VALID_TARGETS)}\n"
                f"  scope must be one of: {sorted(VALID_SCOPES)}"
            )

    @property
    def family(self) -> str:
        m = EXPERIMENT_NAME_PATTERN.match(self.experiment_id)
        return m.group(1) if m else "unknown"

    @property
    def tier(self) -> str:
        m = EXPERIMENT_NAME_PATTERN.match(self.experiment_id)
        return m.group(2) if m else "unknown"

    @property
    def target(self) -> str:
        m = EXPERIMENT_NAME_PATTERN.match(self.experiment_id)
        return m.group(3) if m else "unknown"

    @property
    def scope(self) -> str:
        m = EXPERIMENT_NAME_PATTERN.match(self.experiment_id)
        return m.group(4) if m else "unknown"

    @property
    def version(self) -> int:
        m = EXPERIMENT_NAME_PATTERN.match(self.experiment_id)
        return int(m.group(5)) if m else 0

    def to_dict(self) -> dict[str, Any]:
        d = {
            "experiment_id": self.experiment_id,
            "phase": self.phase,
            "training_view_id": self.training_view_id,
            "base_model": self.base_model,
            "model_revision": self.model_revision,
            "quantization": self.quantization.to_dict(),
            "lora": self.lora.to_dict(),
            "training": self.training.to_dict(),
        }
        # Add optional fields if set
        for attr in ("sprint", "direction", "research_question", "hypothesis",
                     "expected_outcome", "eval_splits"):
            val = getattr(self, attr)
            if val is not None:
                d[attr] = val
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentConfig":
        """Create ExperimentConfig from a dict (e.g. loaded from config.json)."""
        quant_data = data.get("quantization", {})
        lora_data = data.get("lora", {})
        train_data = data.get("training", {})
        return cls(
            experiment_id=data["experiment_id"],
            phase=data["phase"],
            training_view_id=data["training_view_id"],
            base_model=data.get("base_model", DEFAULT_BASE_MODEL),
            model_revision=data.get("model_revision"),
            quantization=QuantizationConfig.from_dict(quant_data),
            lora=LoRAConfig.from_dict(lora_data),
            training=TrainingConfig.from_dict(train_data),
            sprint=data.get("sprint"),
            direction=data.get("direction"),
            research_question=data.get("research_question"),
            hypothesis=data.get("hypothesis"),
            expected_outcome=data.get("expected_outcome"),
            eval_splits=data.get("eval_splits"),
        )

    @classmethod
    def from_file(cls, path: str) -> "ExperimentConfig":
        import json
        from pathlib import Path
        p = Path(path)
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def save(self, path: str) -> None:
        import json
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")

    def validate_protocol_compliance(self) -> list[str]:
        """
        Validate the configuration against the Atlas Research Protocol v1.0.

        Returns a list of violations (empty if compliant).
        """
        violations = []

        # Check naming convention (already validated in __post_init__)
        m = EXPERIMENT_NAME_PATTERN.match(self.experiment_id)
        if not m:
            violations.append(f"experiment_id {self.experiment_id!r} does not match naming convention")

        # Check that base model is in supported set
        supported_models = {
            "qwen7b": "Qwen/Qwen2.5-7B-Instruct",
            "llama8b": "meta-llama/Meta-Llama-3-8B",
            "deepseek8b": "deepseek-ai/DeepSeek-Coder-6.7B-Instruct",
            "mistral7b": "mistralai/Mistral-7B-Instruct-v0.3",
            "gemma7b": "google/gemma-2-9b-it",
            "nemotron8b": "nvidia/Nemotron-Orchestrator-8B",
        }
        expected_model = supported_models.get(self.target)
        if expected_model and self.base_model != expected_model:
            violations.append(
                f"base_model {self.base_model!r} does not match expected model for target {self.target!r} "
                f"({expected_model!r})"
            )

        # Check that eval-only experiments have eval_splits
        if self.scope == "eval" and not self.eval_splits:
            violations.append("eval-only experiments must specify eval_splits")

        # Check transfer experiments have direction
        if self.scope == "transfer" and not self.direction:
            violations.append("transfer experiments must specify direction")

        # Check seed is recorded
        if self.training.seed is None:
            violations.append("seed must be recorded for reproducibility")

        return violations
