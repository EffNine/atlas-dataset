"""
training_view_engine — Training View generation, filtering, manifest, and validation.

Provides the TrainingViewGenerator orchestrator and supporting modules
for generating reproducible, disposable model-specific training views
from approved Atlas knowledge objects.

Exports:
    TrainingViewGenerator — Top-level orchestrator for view generation.
    TrainingViewFilter   — Filtering logic for record eligibility.
    TrainingViewManifest — Manifest construction and checksumming.
    TrainingViewValidator — Validation logic for inputs, content, and outputs.
"""

from __future__ import annotations

from .generator import TrainingViewGenerator
from .filter import TrainingViewFilter
from .manifest import TrainingViewManifest
from .validator import TrainingViewValidator

__all__ = [
    "TrainingViewGenerator",
    "TrainingViewFilter",
    "TrainingViewManifest",
    "TrainingViewValidator",
]
