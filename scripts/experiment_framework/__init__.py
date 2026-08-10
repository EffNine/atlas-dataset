#!/usr/bin/env python3
"""
experiment_framework — Atlas QLoRA experiment infrastructure.

This package provides the canonical framework for managing QLoRA training
experiments under the Atlas Research Protocol v1.0 (Phase 6.1). It supports:

  - Experiment configuration with protocol-compliant naming
  - Experiment registry for tracking all experiments
  - Run metadata collection (pre/post training)
  - Checkpoint metadata and adapter tracking
  - Training manifests (dataset + config provenance)
  - Evaluation manifests (split provenance + scoring)
  - Result registry (aggregate + per-example results)
  - Experiment directory scaffold generation
  - Training runner base class (with resume support)
  - Evaluation runner base class (with baseline comparison)
  - Transfer analysis (cross-domain gain, Transfer Ratio)
  - Reproducibility checklist verification
  - Seed management and version tracking

The framework does NOT perform training or evaluation itself — it provides
the infrastructure and metadata management around those operations.

All artifacts are written under experiments/{experiment_id}/ and never
modify frozen dataset, training view, or evaluation engine artifacts.

Usage:
    from scripts.experiment_framework import (
        ExperimentConfig,
        ExperimentRegistry,
        ExperimentScaffold,
        TrainingRunner,
        EvaluationRunner,
    )
"""

from __future__ import annotations

__version__ = "0.1.0"
__package__ = "experiment_framework"

from .config import (  # noqa: E402
    ExperimentConfig,
    QuantizationConfig,
    LoRAConfig,
    TrainingConfig,
    VALID_FAMILIES,
    VALID_TIERS,
    VALID_TARGETS,
    VALID_SCOPES,
    EXPERIMENT_NAME_PATTERN,
)

from .registry import (  # noqa: E402
    ExperimentRegistry,
    ExperimentRecord,
)

from .scaffold import (  # noqa: E402
    ExperimentScaffold,
    DEFAULT_LAYOUT,
)

from .metadata import (  # noqa: E402
    RunMetadata,
    CheckpointMetadata,
    compute_sha256,
    git_info,
)

from .manifests import (  # noqa: E402
    DatasetManifest,
    TrainingManifest,
    EvaluationManifest,
)

from .results import (  # noqa: E402
    ResultRegistry,
    ResultEntry,
    AggregateMetrics,
)

from .training_runner import (  # noqa: E402
    TrainingRunner,
    TrainingStepLog,
)

from .eval_runner import (  # noqa: E402
    EvaluationRunner,
    BaselineComparison,
    TransferAnalysis,
)

from .reproducibility import (  # noqa: E402
    ReproducibilityChecklist,
    ChecklistStatus,
)

__all__ = [
    # Config
    "ExperimentConfig",
    "QuantizationConfig",
    "LoRAConfig",
    "TrainingConfig",
    "VALID_FAMILIES",
    "VALID_TIERS",
    "VALID_TARGETS",
    "VALID_SCOPES",
    "EXPERIMENT_NAME_PATTERN",
    # Registry
    "ExperimentRegistry",
    "ExperimentRecord",
    # Scaffold
    "ExperimentScaffold",
    "DEFAULT_LAYOUT",
    # Metadata
    "RunMetadata",
    "CheckpointMetadata",
    "compute_sha256",
    "git_info",
    # Manifests
    "DatasetManifest",
    "TrainingManifest",
    "EvaluationManifest",
    # Results
    "ResultRegistry",
    "ResultEntry",
    "AggregateMetrics",
    # Training runner
    "TrainingRunner",
    "TrainingStepLog",
    # Eval runner
    "EvaluationRunner",
    "BaselineComparison",
    "TransferAnalysis",
    # Reproducibility
    "ReproducibilityChecklist",
    "ChecklistStatus",
    # Version
    "__version__",
]
