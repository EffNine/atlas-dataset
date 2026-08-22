"""evaluation_research — Atlas research automation package.

Provides automated generation-policy calibration, benchmark onboarding,
contamination auditing, clean eval-set construction, M1/M2/M2' evaluation
matrices, and a research experiment state machine.

All components are deterministic, reproducible, and read-only on frozen
dataset assets. No model training is performed by this package.
"""

from __future__ import annotations

from .artifacts import ArtifactIntegrity, ArtifactVerifier, sha256_file, sha256_text
from .calibration import (
    CalibrationResult,
    PolicyResult,
    analytical_calibration,
    load_calibration_report,
    run_inference_calibration,
)
from .contamination import ContaminationAuditor, run_contamination_audit
from .eval_set_builder import EvalSetBuilder, FrozenEvalSet
from .state_machine import ResearchState, ResearchStateMachine

__all__ = [
    "ArtifactIntegrity",
    "ArtifactVerifier",
    "CalibrationResult",
    "PolicyResult",
    "ContaminationAuditor",
    "EvalSetBuilder",
    "FrozenEvalSet",
    "ResearchState",
    "ResearchStateMachine",
    "analytical_calibration",
    "load_calibration_report",
    "run_contamination_audit",
    "run_inference_calibration",
    "sha256_file",
    "sha256_text",
]
