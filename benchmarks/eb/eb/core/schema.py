#!/usr/bin/env python3
"""
schema.py — Pydantic data models for the EffNine Benchmark (EB).

Defines the canonical data structures for tasks, results, benchmark runs,
baseline records, and capability scores. All models validate their inputs
and reject malformed data before it enters the system.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .types import (
    AggregationStrategy,
    BenchmarkPartition,
    Capability,
    CapabilityDimension,
    Difficulty,
    EvaluatorStatus,
    ExecutionMode,
    JudgeDiversityPolicy,
    JudgeMode,
    JudgeSelectionReason,
    parse_aggregation_strategy,
    parse_capability,
    parse_difficulty,
    parse_evaluator_status,
    parse_execution_mode,
    parse_judge_mode,
    parse_partition,
)


# ---------------------------------------------------------------------------
# Task schemas
# ---------------------------------------------------------------------------


class TaskEvaluationConfig(BaseModel):
    """How a single task should be evaluated."""

    primary_mode: JudgeMode = JudgeMode.DETERMINISTIC
    fallback_modes: list[JudgeMode] = Field(default_factory=list)
    max_tokens: int | None = None
    timeout_s: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    # Evaluator definitions (Stage 3+)
    evaluators: list[dict[str, Any]] = Field(default_factory=list)
    aggregation: dict[str, Any] = Field(default_factory=lambda: {"strategy": "single_authoritative"})
    judge_config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evaluators")
    @classmethod
    def _validate_evaluators(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for ev in v:
            if "type" not in ev:
                raise ValueError("Each evaluator must have a 'type' field")
        return v

    @field_validator("aggregation")
    @classmethod
    def _validate_aggregation(cls, v: dict[str, Any]) -> dict[str, Any]:
        valid_strategies = [s.value for s in AggregationStrategy]
        strategy = v.get("strategy", "single_authoritative")
        if strategy not in valid_strategies:
            raise ValueError(
                f"Invalid aggregation strategy {strategy!r}. "
                f"Must be one of: {', '.join(valid_strategies)}"
            )
        return v

    def get_judge_config(self) -> TaskJudgeConfig:
        """Extract and validate judge configuration from extra or judge_config field."""
        raw: dict[str, Any] = {}
        raw.update(self.extra.get("judge_config", {}))
        raw.update(self.judge_config)
        return TaskJudgeConfig.model_validate(raw)


class Task(BaseModel):
    """A single benchmark task."""

    id: str
    version: str = "1.0"
    category: str
    mode: ExecutionMode
    difficulty: Difficulty
    capabilities: list[Capability] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    prompt: str
    context: dict[str, Any] = Field(default_factory=dict)
    evaluation: TaskEvaluationConfig = Field(default_factory=TaskEvaluationConfig)
    partition: BenchmarkPartition = BenchmarkPartition.DEVELOPMENT
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("id must be non-empty")
        if len(v) > 128:
            raise ValueError("id must be at most 128 characters")
        return v.strip()

    @field_validator("category")
    @classmethod
    def _validate_category(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("category must be non-empty")
        return v.strip()

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, v: ExecutionMode | str) -> ExecutionMode:
        if isinstance(v, str):
            return parse_execution_mode(v)
        return v

    @field_validator("difficulty")
    @classmethod
    def _validate_difficulty(cls, v: Difficulty | str) -> Difficulty:
        if isinstance(v, str):
            return parse_difficulty(v)
        return v

    @field_validator("capabilities")
    @classmethod
    def _validate_capabilities(cls, v: list[Capability | str]) -> list[Capability]:
        result: list[Capability] = []
        for c in v:
            if isinstance(c, str):
                result.append(parse_capability(c))
            else:
                result.append(c)
        return result

    @field_validator("partition")
    @classmethod
    def _validate_partition(cls, v: BenchmarkPartition | str) -> BenchmarkPartition:
        if isinstance(v, str):
            return parse_partition(v)
        return v

    def sha256(self) -> str:
        """Canonical SHA-256 of sorted, serialized task fields (excluding prompt for stability)."""
        payload = self.model_dump(exclude={"prompt"})
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Stage schemas (LONG execution mode)
# ---------------------------------------------------------------------------


class StageData(BaseModel):
    """A single stage within a LONG task.

    Supports both inline definition (task.context["stages"]) and the
    formal stages.json fixture schema introduced in Stage 8B.
    """

    id: str
    name: str
    prompt: str
    order: int = 0
    objective: str | None = None
    instructions: str | None = None
    expected_artifacts: list[str] = Field(default_factory=list)
    expected_state: dict[str, Any] = Field(default_factory=dict)
    evaluation_criteria: list[dict[str, Any]] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    terminal: bool = False
    failure_mode: str = "abort"  # "abort" | "continue" | "skip_remaining"
    requirement_change: dict[str, Any] | None = None
    timeout_s: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    # stages.json fixture fields
    fixture_id: str | None = None
    source_path: str = "source"
    workspace_path: str = "/workspace"

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("stage id must be non-empty")
        return v.strip()

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("stage name must be non-empty")
        return v.strip()

    @field_validator("failure_mode")
    @classmethod
    def _validate_failure_mode(cls, v: str) -> str:
        valid = ("abort", "continue", "skip_remaining")
        if v not in valid:
            raise ValueError(f"failure_mode must be one of {valid}, got {v!r}")
        return v

    def to_inline_context(self) -> dict[str, Any]:
        """Serialize to the inline context format used by Stage 8A."""
        return {
            "id": self.id,
            "name": self.name,
            "prompt": self.prompt,
        }


class StageResult(BaseModel):
    """Result from a single LONG stage execution."""

    stage_id: str
    stage_name: str
    status: str = "pending"  # SUCCESS, FAILED, ERROR, TIMEOUT, CANCELLED
    output: str | None = None
    score: float | None = None
    duration_s: float = 0.0
    token_usage: dict[str, int] = Field(default_factory=dict)
    evaluator_results: list[EvaluatorResult] = Field(default_factory=list)
    raw_score: float | None = None
    flags: list[str] = Field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def passed(self) -> bool | None:
        if self.score is None:
            return None
        return self.score >= 0.5


# ---------------------------------------------------------------------------
# Result schemas
# ---------------------------------------------------------------------------


class EvaluatorResult(BaseModel):
    """Result from a single evaluator."""

    evaluator: str
    mode: JudgeMode
    status: EvaluatorStatus = EvaluatorStatus.PENDING
    score: float | None = None
    max_score: float | None = None
    normalized_score: float | None = None
    rationale: str | None = None
    evidence: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    authoritative_level: int = 1

    @field_validator("status", mode="before")
    @classmethod
    def _parse_status(cls, v: EvaluatorStatus | str | None) -> EvaluatorStatus:
        if isinstance(v, EvaluatorStatus):
            return v
        if v is None:
            return EvaluatorStatus.PENDING
        return parse_evaluator_status(v)

    @property
    def is_terminal(self) -> bool:
        """True if the evaluator has reached a final state (not PENDING)."""
        return self.status not in (EvaluatorStatus.PENDING, EvaluatorStatus.PENDING_JUDGE)

    @property
    def is_applicable(self) -> bool:
        """True if the evaluator produced a meaningful result (not N/A or UNSUPPORTED)."""
        return self.status not in (
            EvaluatorStatus.NOT_APPLICABLE,
            EvaluatorStatus.UNSUPPORTED,
        )

    @property
    def passed(self) -> bool | None:
        """True if status is PASS, False if FAIL, None if N/A/UNSUPPORTED/PENDING."""
        if self.status == EvaluatorStatus.PASS:
            return True
        if self.status == EvaluatorStatus.FAIL:
            return False
        return None


class TaskResult(BaseModel):
    """Complete result for a single task execution."""

    task_id: str
    run_id: str
    raw_response: str | None = None
    evaluator_results: list[EvaluatorResult] = Field(default_factory=list)
    raw_task_score: float | None = None
    # Deprecated compatibility field. raw_task_score is the authoritative score.
    final_score: float | None = None
    primary_evidence: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    execution_metadata: dict[str, Any] = Field(default_factory=dict)

    # EXEC-specific fields (Stage 6)
    repository_id: str | None = None
    repository_hash: str | None = None
    docker_image: str | None = None
    sandbox_id: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    command_count: int = 0
    changed_files: list[str] = Field(default_factory=list)
    test_summary: dict[str, Any] = Field(default_factory=dict)
    diff: str | None = None
    timeout_status: str | None = None

    # LONG-specific fields (Stage 8A)
    stage_results: list[StageResult] = Field(default_factory=list)
    stages: list[StageData] = Field(default_factory=list)
    sandbox_id_long: str | None = None
    long_outcome: str | None = None  # PASS, PARTIAL, FAIL, NOT_APPLICABLE

    @property
    def passed(self) -> bool | None:
        """True if outcome is PASS, False if FAIL/PARTIAL, None if undefined."""
        if self.long_outcome == "PASS":
            return True
        if self.long_outcome in ("FAIL", "PARTIAL"):
            return False
        score = self.raw_task_score if self.raw_task_score is not None else self.final_score
        if score is None:
            return None
        return score >= 0.5


# ---------------------------------------------------------------------------
# Benchmark run schemas
# ---------------------------------------------------------------------------


class ModelMetadata(BaseModel):
    """Identity of a model being benchmarked."""

    name: str
    revision: str
    type: str = "model"  # "base_model", "lora_adapter", etc.
    extra: dict[str, Any] = Field(default_factory=dict)


class InferenceSettings(BaseModel):
    """Inference parameters for reproducibility."""

    seed: int = 42
    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 0
    max_tokens: int = 4096
    context_length: int = 8192
    tool_configuration: str = "none"


class EnvironmentInfo(BaseModel):
    """Hardware and runtime environment."""

    hardware: str | None = None
    torch_version: str | None = None
    cuda_version: str | None = None
    python_version: str | None = None
    container_image: str | None = None
    container_image_sha: str | None = None


class JudgeMetadata(BaseModel):
    """Cloud judge configuration."""

    provider: str | None = None
    model: str | None = None
    version: str | None = None


class JudgeModelInfo(BaseModel):
    """Normalized internal representation of a discovered judge model."""

    id: str
    owned_by: str | None = None
    context_length: int | None = None
    created: int | None = None
    capabilities: dict[str, float] = Field(default_factory=dict)
    modality: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class JudgeCapabilityProfile(BaseModel):
    """Normalized capability profile for a judge model."""

    model_id: str
    reasoning: float = 0.0
    coding: float = 0.0
    planning: float = 0.0
    instruction_following: float = 0.0
    long_context: float = 0.0
    factual_analysis: float = 0.0
    vision: float = 0.0
    latency: float = 0.5
    availability: float = 1.0
    source: str = "unknown"  # gateway_metadata, configured, probe
    probe_version: str | None = None


class JudgeSelectionResult(BaseModel):
    """Result of judge model selection for a task."""

    primary: str | None = None
    secondary: str | None = None
    tertiary: str | None = None
    selected_models: list[str] = Field(default_factory=list)
    selection_scores: dict[str, float] = Field(default_factory=dict)
    capability_requirements: dict[str, float] = Field(default_factory=dict)
    selection_reason: str = ""
    fallback_behavior: str = ""
    diversity_policy: str = "off"


class JudgeResult(BaseModel):
    """Result from a single cloud judge evaluation."""

    model_id: str
    score: float | None = None
    max_score: float = 1.0
    criterion_scores: dict[str, float] = Field(default_factory=dict)
    reasoning_summary: str | None = None
    evidence: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    confidence: float | None = None
    status: str = "success"  # success, error, timeout, rate_limit, malformed
    error: str | None = None
    latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw_response: str | None = None


class ConsensusResult(BaseModel):
    """Aggregated result from multiple judges."""

    final_score: float | None = None
    max_score: float = 1.0
    judge_scores: list[float] = Field(default_factory=list)
    mean: float | None = None
    median: float | None = None
    stddev: float | None = None
    disagreement_percent: float = 0.0
    selected_judge_count: int = 0
    failed_judge_count: int = 0
    disagreement_level: str = "low"
    flags: list[str] = Field(default_factory=list)
    per_judge: list[dict[str, Any]] = Field(default_factory=list)


class TaskJudgeConfig(BaseModel):
    """Judge-specific configuration for a task evaluation."""

    min_judges: int = 2
    preferred_judges: int = 3
    max_judges: int = 3
    disagreement_threshold_percent: float = 15.0
    diversity_policy: JudgeDiversityPolicy = JudgeDiversityPolicy.PREFERRED
    criteria: list[dict[str, Any]] = Field(default_factory=list)
    max_retries: int = 2
    timeout_s: float = 120.0


class RepeatedRunStats(BaseModel):
    """Statistics across repeated runs of the same model."""

    scores: list[int] = Field(default_factory=list)
    mean: float | None = None
    median: float | None = None
    stddev: float | None = None
    min_score: int | None = None
    max_score: int | None = None
    error_percent: float | None = None

    def compute(self) -> None:
        """Compute derived statistics from scores."""
        if not self.scores:
            return
        n = len(self.scores)
        self.mean = sum(self.scores) / n
        sorted_scores = sorted(self.scores)
        if n % 2 == 0:
            self.median = (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2
        else:
            self.median = sorted_scores[n // 2]
        if n > 1:
            variance = sum((s - (self.mean or 0)) ** 2 for s in self.scores) / (n - 1)
            self.stddev = variance ** 0.5
        else:
            self.stddev = 0.0
        self.min_score = min(self.scores)
        self.max_score = max(self.scores)
        if self.mean is not None and self.mean != 0:
            self.error_percent = (self.stddev / self.mean) * 100


class CapabilityScore(BaseModel):
    """Aggregated EB score for a single capability."""

    capability: Capability
    eb_score: int
    raw_mean: float
    task_count: int
    run_stats: RepeatedRunStats | None = None

    @field_validator("eb_score")
    @classmethod
    def _validate_eb_score(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"eb_score must be positive, got {v}")
        return v


class BenchmarkRun(BaseModel):
    """Complete record of a single benchmark execution."""

    run_id: str
    benchmark_version: str
    task_set_version: str
    model: ModelMetadata
    base_model: ModelMetadata
    baseline_run_id: str | None = None
    suite: str
    partitions: list[BenchmarkPartition] = Field(default_factory=list)
    inference: InferenceSettings
    environment: EnvironmentInfo
    judge: JudgeMetadata | None = None
    task_results: list[TaskResult] = Field(default_factory=list)
    capability_scores: dict[str, CapabilityScore] = Field(default_factory=dict)
    overall_eb_score: int | None = None
    run_stats: RepeatedRunStats | None = None
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    git_commit: str | None = None
    manifest_sha256: str | None = None
    task_set_hash: str | None = None
    scoring_version: str = "eb-score-v1"
    evaluator_config_version: str | None = None
    run_status: str = "RAW_COMPLETE"

    @property
    def is_normalized(self) -> bool:
        """True if this run has a valid EB Score."""
        return self.overall_eb_score is not None and self.overall_eb_score > 0

    @property
    def status_label(self) -> str:
        """Human-readable status label."""
        if self.run_status == "BENCHMARK_COMPLETE":
            return "Benchmark Complete"
        if self.run_status == "RAW_COMPLETE":
            return "Raw Results Only"
        if self.run_status == "NOT_NORMALIZED":
            return "Not Normalized (no baseline)"
        return self.run_status

    def compute_eb_score(self, baseline_score: int = 1000) -> int:
        """Compute EB score relative to baseline (default 1000)."""
        if not self.task_results:
            return 0
        valid = [r.raw_task_score for r in self.task_results if r.raw_task_score is not None]
        if not valid:
            return 0
        raw_mean = sum(valid) / len(valid)
        eb_score = round(1000 * raw_mean / (baseline_score / 1000))
        self.overall_eb_score = eb_score
        return eb_score

    def add_run_result(self, result: TaskResult) -> None:
        """Add a task result to this run."""
        self.task_results.append(result)

    def to_dict(self) -> dict[str, Any]:
        d = self.model_dump(by_alias=False, exclude_none=False)
        # Serialize enums to strings
        for cap in d.get("capability_scores", {}).values():
            if isinstance(cap, CapabilityScore):
                cap_dict = cap.model_dump()
                cap_dict["capability"] = cap.capability.value
                d["capability_scores"][cap.capability.value] = cap_dict
        return d


# ---------------------------------------------------------------------------
# Baseline schemas
# ---------------------------------------------------------------------------


class BaselineRecord(BaseModel):
    """Baseline performance record for a base model."""

    base_model_name: str
    base_model_revision: str
    benchmark_version: str
    task_set_version: str
    baseline_run_id: str
    suite: str = ""
    partitions: list[str] = Field(default_factory=list)
    task_set_hash: str | None = None
    scoring_version: str = "eb-score-v1"
    evaluator_config_version: str | None = None
    run_scores: list[int] = Field(default_factory=list)
    raw_scores: list[float] = Field(default_factory=list)
    mean: float | None = None
    median: float | None = None
    stddev: float | None = None
    min_score: int | None = None
    max_score: int | None = None
    error_percent: float | None = None
    eb_score: int = 1000
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_stats(self) -> None:
        """Compute statistics from run scores."""
        if not self.run_scores:
            return
        n = len(self.run_scores)
        self.mean = sum(self.run_scores) / n
        sorted_scores = sorted(self.run_scores)
        if n % 2 == 0:
            self.median = (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2
        else:
            self.median = sorted_scores[n // 2]
        if n > 1:
            variance = sum((s - (self.mean or 0)) ** 2 for s in self.run_scores) / (n - 1)
            self.stddev = variance ** 0.5
        else:
            self.stddev = 0.0
        self.min_score = min(self.run_scores)
        self.max_score = max(self.run_scores)
        if self.mean is not None and self.mean != 0:
            self.error_percent = (self.stddev / self.mean) * 100

    def add_score(self, score: int) -> None:
        """Add a single run score and recompute statistics."""
        self.run_scores.append(score)
        self.compute_stats()


# ---------------------------------------------------------------------------
# Rebuild dependent models to pick up schema changes
# ---------------------------------------------------------------------------

# Force Pydantic to rebuild models that reference TaskEvaluationConfig,
# ensuring they see the latest fields (e.g. judge_config added in Stage 4).
try:
    Task.model_rebuild()
except Exception:
    pass
