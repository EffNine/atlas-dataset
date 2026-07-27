"""
evaluation_engine — Atlas Evaluation Engine.

Provides deterministic, read-only evaluation orchestration for the Atlas
dataset. The engine measures knowledge quality, safety, and engineering
properties without modifying any dataset artifacts.

Usage:
    from evaluation_engine import EvaluationOrchestrator, EvaluationRunner
    engine = EvaluationOrchestrator("/path/to/atlas-dataset")
    runner = EvaluationRunner("/path/to/atlas-dataset")
    result = runner.run("atlas_quality_benchmark", mode="dry-run")

Evaluation modes:
    - dry-run:  verify infrastructure without actual scoring
    - full:     execute all registered metrics against curated data
"""

from .engine import EvaluationOrchestrator
from .registry import BenchmarkRegistry
from .report import EvaluationReport
from .runner import EvaluationRunner, EvaluationResult
from .metrics import (
    MetricRegistry,
    BaseMetric,
    # Phase 5A base metrics
    QualityScoreAgreement,
    ProvenanceAccuracy,
    SchemaPassRate,
    ContentSafetyRate,
    DeterminismScore,
    ReproducibilityHash,
    # Phase 5B quality metrics
    QualityMeanScore,
    QualityScoreDistribution,
    QualityCategoryAverage,
    # Phase 5B review alignment metrics
    ReviewAgreementRate,
    ReviewDisagreementCount,
    ReviewApprovalPredictionAccuracy,
    # Phase 5B provenance metrics
    ProvenanceValidSourceRate,
    ProvenanceLicensePassRate,
    # Safety extensions
    HallucinationRiskScore,
)

__all__ = [
    "EvaluationOrchestrator",
    "BenchmarkRegistry",
    "EvaluationReport",
    "EvaluationRunner",
    "EvaluationResult",
    "MetricRegistry",
    "BaseMetric",
    "QualityScoreAgreement",
    "ProvenanceAccuracy",
    "SchemaPassRate",
    "ContentSafetyRate",
    "DeterminismScore",
    "ReproducibilityHash",
    "QualityMeanScore",
    "QualityScoreDistribution",
    "QualityCategoryAverage",
    "ReviewAgreementRate",
    "ReviewDisagreementCount",
    "ReviewApprovalPredictionAccuracy",
    "ProvenanceValidSourceRate",
    "ProvenanceLicensePassRate",
    "HallucinationRiskScore",
]
