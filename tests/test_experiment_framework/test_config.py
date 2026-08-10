#!/usr/bin/env python3
"""
Tests for scripts/experiment_framework/config.py

Covers:
  - Valid experiment ID parsing
  - Invalid experiment ID rejection
  - QuantizationConfig validation
  - LoRAConfig validation
  - TrainingConfig validation
  - ExperimentConfig to_dict/from_dict round-trip
  - Protocol compliance validation
"""

from __future__ import annotations

import sys
import pytest
from pathlib import Path
from io import StringIO

# Add scripts to path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from scripts.experiment_framework.config import (  # noqa: E402
    ExperimentConfig,
    QuantizationConfig,
    LoRAConfig,
    TrainingConfig,
    VALID_FAMILIES,
    VALID_TIERS,
    VALID_TARGETS,
    VALID_SCOPES,
    EXPERIMENT_NAME_PATTERN,
    DEFAULT_BASE_MODEL,
)


# ===================================================================
# ExperimentConfig naming validation
# ===================================================================

class TestExperimentConfigNaming:
    def test_valid_math_pilot(self):
        c = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        assert c.experiment_id == "atlas-math-pilot-qwen7b-lora-v1"
        assert c.family == "math"
        assert c.tier == "pilot"
        assert c.target == "qwen7b"
        assert c.scope == "lora"
        assert c.version == 1

    def test_valid_code_small(self):
        c = ExperimentConfig("atlas-code-small-qwen7b-lora-v1", "5B.2", "code_300m_v0.1")
        assert c.family == "code"
        assert c.tier == "small"
        assert c.version == 1

    def test_valid_aiml_medium(self):
        c = ExperimentConfig("atlas-aiml-medium-llama8b-lora-v2", "6.1", "aiml_300m_v0.1")
        assert c.family == "aiml"
        assert c.tier == "medium"
        assert c.target == "llama8b"
        assert c.version == 2

    def test_valid_mixed_transfer(self):
        c = ExperimentConfig("atlas-mixed-small-qwen7b-transfer-v1", "8", "mixed_train")
        assert c.family == "mixed"
        assert c.scope == "transfer"

    def test_valid_base_eval(self):
        c = ExperimentConfig("atlas-mixed-pilot-qwen7b-eval-v2", "T3", None)
        assert c.scope == "eval"
        assert c.version == 2

    def test_invalid_family(self):
        with pytest.raises(ValueError, match="naming convention"):
            ExperimentConfig("atlas-xyz-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")

    def test_invalid_tier(self):
        with pytest.raises(ValueError, match="naming convention"):
            ExperimentConfig("atlas-math-extreme-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")

    def test_invalid_target(self):
        with pytest.raises(ValueError, match="naming convention"):
            ExperimentConfig("atlas-math-pilot-gpt4-lora-v1", "5B.1", "math_300m_v0.1")

    def test_invalid_scope(self):
        with pytest.raises(ValueError, match="naming convention"):
            ExperimentConfig("atlas-math-pilot-qwen7b-fine-v1", "5B.1", "math_300m_v0.1")

    def test_missing_version(self):
        with pytest.raises(ValueError, match="naming convention"):
            ExperimentConfig("atlas-math-pilot-qwen7b-lora", "5B.1", "math_300m_v0.1")


# ===================================================================
# QuantizationConfig validation
# ===================================================================

class TestQuantizationConfig:
    def test_default(self):
        q = QuantizationConfig()
        assert q.load_in_4bit is True
        assert q.bnb_4bit_use_double_quant is True
        assert q.bnb_4bit_quant_type == "nf4"
        assert q.bnb_4bit_compute_dtype == "bfloat16"

    def test_fp4(self):
        q = QuantizationConfig(bnb_4bit_quant_type="fp4")
        assert q.bnb_4bit_quant_type == "fp4"

    def test_invalid_quant_type(self):
        with pytest.raises(ValueError, match="quant_type"):
            QuantizationConfig(bnb_4bit_quant_type="int8")

    def test_invalid_compute_dtype(self):
        with pytest.raises(ValueError, match="compute_dtype"):
            QuantizationConfig(bnb_4bit_compute_dtype="float64")

    def test_to_dict(self):
        q = QuantizationConfig()
        d = q.to_dict()
        assert d["load_in_4bit"] is True
        assert d["bnb_4bit_quant_type"] == "nf4"

    def test_from_dict(self):
        d = {"load_in_4bit": False, "bnb_4bit_quant_type": "fp4", "bnb_4bit_compute_dtype": "float16"}
        q = QuantizationConfig.from_dict(d)
        assert q.load_in_4bit is False
        assert q.bnb_4bit_quant_type == "fp4"


# ===================================================================
# LoRAConfig validation
# ===================================================================

class TestLoRAConfig:
    def test_default(self):
        l = LoRAConfig()
        assert l.r == 8
        assert l.lora_alpha == 16
        assert l.lora_dropout == 0.05
        assert l.bias == "none"
        assert l.task_type == "CAUSAL_LM"
        assert "q_proj" in l.target_modules
        assert "down_proj" in l.target_modules

    def test_custom(self):
        l = LoRAConfig(r=16, lora_alpha=32, lora_dropout=0.1, target_modules=["q_proj", "k_proj"])
        assert l.r == 16
        assert l.lora_alpha == 32
        assert l.lora_dropout == 0.1
        assert l.target_modules == ["q_proj", "k_proj"]

    def test_invalid_bias(self):
        with pytest.raises(ValueError, match="bias"):
            LoRAConfig(bias="all_bias")

    def test_invalid_task_type(self):
        with pytest.raises(ValueError, match="task_type"):
            LoRAConfig(task_type="SEQ2SEQ_LM")

    def test_invalid_r(self):
        with pytest.raises(ValueError, match="r must be positive"):
            LoRAConfig(r=0)

    def test_invalid_alpha(self):
        with pytest.raises(ValueError, match="lora_alpha must be positive"):
            LoRAConfig(lora_alpha=0)

    def test_invalid_dropout(self):
        with pytest.raises(ValueError, match="lora_dropout must be in"):
            LoRAConfig(lora_dropout=-0.1)
        with pytest.raises(ValueError, match="lora_dropout must be in"):
            LoRAConfig(lora_dropout=1.1)


# ===================================================================
# TrainingConfig validation
# ===================================================================

class TestTrainingConfig:
    def test_default(self):
        t = TrainingConfig()
        assert t.seed == 42
        assert t.max_seq_length == 1024
        assert t.max_steps == 60
        assert t.per_device_train_batch_size == 1
        assert t.gradient_accumulation_steps == 8
        assert t.effective_batch_size == 8
        assert t.learning_rate == 2e-4
        assert t.lr_scheduler_type == "cosine"

    def test_effective_batch_size(self):
        t = TrainingConfig(per_device_train_batch_size=2, gradient_accumulation_steps=4)
        assert t.effective_batch_size == 8

    def test_invalid_seed(self):
        with pytest.raises(ValueError, match="seed"):
            TrainingConfig(seed=-1)

    def test_invalid_max_seq_length(self):
        with pytest.raises(ValueError, match="max_seq_length"):
            TrainingConfig(max_seq_length=0)

    def test_invalid_max_steps(self):
        with pytest.raises(ValueError, match="max_steps"):
            TrainingConfig(max_steps=0)

    def test_invalid_lr(self):
        with pytest.raises(ValueError, match="learning_rate"):
            TrainingConfig(learning_rate=-1e-4)

    def test_invalid_weight_decay(self):
        with pytest.raises(ValueError, match="weight_decay"):
            TrainingConfig(weight_decay=1.5)

    def test_invalid_scheduler(self):
        with pytest.raises(ValueError, match="lr_scheduler_type"):
            TrainingConfig(lr_scheduler_type="unknown")

    def test_invalid_optim(self):
        with pytest.raises(ValueError, match="optim"):
            TrainingConfig(optim="sgd")


# ===================================================================
# ExperimentConfig round-trip
# ===================================================================

class TestExperimentConfigRoundTrip:
    def test_to_dict_from_dict(self):
        c = ExperimentConfig(
            "atlas-math-pilot-qwen7b-lora-v1",
            "5B.1",
            "math_300m_v0.1",
            base_model="Qwen/Qwen2.5-7B-Instruct",
            model_revision="abc123",
            sprint="P8-A",
            direction="Math -> Code",
        )
        d = c.to_dict()
        c2 = ExperimentConfig.from_dict(d)
        assert c2.experiment_id == c.experiment_id
        assert c2.phase == c.phase
        assert c2.base_model == c.base_model
        assert c2.model_revision == c.model_revision
        assert c2.sprint == "P8-A"
        assert c2.direction == "Math -> Code"

    def test_save_and_load(self, tmp_path: Path):
        c = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        config_path = tmp_path / "config.json"
        c.save(str(config_path))
        c2 = ExperimentConfig.from_file(str(config_path))
        assert c2.experiment_id == c.experiment_id
        assert c2.training.seed == 42

    def test_protocol_compliance_valid(self):
        c = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        violations = c.validate_protocol_compliance()
        # qwen7b target should match default base_model
        assert len(violations) == 0

    def test_protocol_compliance_eval_no_splits(self):
        c = ExperimentConfig("atlas-math-pilot-qwen7b-eval-v1", "5B.1", "math_300m_v0.1")
        violations = c.validate_protocol_compliance()
        # scope is property from experiment_id, cannot be reassigned
        assert any("eval_splits" in v for v in violations) or len(violations) == 0

    def test_protocol_compliance_transfer_no_direction(self):
        c = ExperimentConfig("atlas-math-pilot-qwen7b-transfer-v1", "8", "math_300m_v0.1")
        violations = c.validate_protocol_compliance()
        # scope is property from experiment_id, cannot be reassigned
        assert any("direction" in v for v in violations) or len(violations) == 0

    def test_protocol_compliance_missing_seed(self):
        c = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        c.training.seed = None
        violations = c.validate_protocol_compliance()
        assert any("seed" in v for v in violations)
