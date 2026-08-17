#!/usr/bin/env python3
"""
types.py — Canonical enums for the EffNine Benchmark (EB).

Defines stable, JSON-serializable enums for execution modes, difficulty levels,
capabilities, judge strategies, and benchmark partitions.
"""

from __future__ import annotations

from enum import Enum, auto


class ExecutionMode(str, Enum):
    """Benchmark execution mode."""

    SINGLE = "SINGLE"
    MULTI = "MULTI"
    EXEC = "EXEC"
    LONG = "LONG"


class Difficulty(str, Enum):
    """Task difficulty level."""

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"


class Capability(str, Enum):
    """Engineering capability being measured."""

    ARCH = "ARCH"
    DEBUG = "DEBUG"
    CODE = "CODE"
    UNDERSTAND = "UNDERSTAND"
    PLAN = "PLAN"
    TEST = "TEST"
    ADVISORY = "ADVISORY"
    JUDGMENT = "JUDGMENT"
    EVIDENCE = "EVIDENCE"
    MYENG = "MYENG"
    AGENT = "AGENT"
    LONG = "LONG"


class JudgeMode(str, Enum):
    """Evaluation authority tier."""

    DETERMINISTIC = "DETERMINISTIC"
    RUBRIC = "RUBRIC"
    CLOUD_JUDGE = "CLOUD_JUDGE"
    AI_OPINION = "AI_OPINION"


class JudgeDiversityPolicy(str, Enum):
    """How strongly to prefer diverse judges."""

    OFF = "off"
    PREFERRED = "preferred"
    REQUIRED = "required"


class CapabilityDimension(str, Enum):
    """Normalized capability dimensions for judge profiling."""

    REASONING = "reasoning"
    CODING = "coding"
    PLANNING = "planning"
    INSTRUCTION_FOLLOWING = "instruction_following"
    LONG_CONTEXT = "long_context"
    FACTUAL_ANALYSIS = "factual_analysis"
    VISION = "vision"
    LATENCY = "latency"
    AVAILABILITY = "availability"


class JudgeSelectionReason(str, Enum):
    """Why a particular judge was selected."""

    HIGHEST_SCORE = "highest_capability_score"
    DIVERSITY_FAVOR = "diversity_preferred"
    OVERRIDE = "explicit_model_override"
    FALLBACK = "only_available"
    SINGLE_JUDGE = "only_one_valid"


class JudgeDisagreementLevel(str, Enum):
    """How much judges disagree on a result."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class EvaluatorStatus(str, Enum):
    """Outcome status of an evaluator execution."""

    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"
    PENDING = "PENDING"
    PENDING_JUDGE = "PENDING_JUDGE"


class AggregationStrategy(str, Enum):
    """How multiple evaluator results combine into a task raw score."""

    SINGLE_AUTHORITY = "single_authoritative"
    WEIGHTED = "weighted"
    ALL_REQUIRED = "all_required"
    ANY_REQUIRED = "any_required"


class BenchmarkPartition(str, Enum):
    """Benchmark data partition."""

    DEVELOPMENT = "development"
    VALIDATION = "validation"
    PRIVATE = "private"
    HIDDEN = "hidden"


def parse_execution_mode(value: str) -> ExecutionMode:
    """Parse a string into ExecutionMode, raising ValueError on invalid input."""
    try:
        return ExecutionMode(value.upper())
    except ValueError:
        valid = [m.value for m in ExecutionMode]
        raise ValueError(
            f"Invalid execution mode {value!r}. Must be one of: {', '.join(valid)}"
        )


def parse_difficulty(value: str) -> Difficulty:
    """Parse a string into Difficulty, raising ValueError on invalid input."""
    try:
        return Difficulty(value.upper())
    except ValueError:
        valid = [d.value for d in Difficulty]
        raise ValueError(f"Invalid difficulty {value!r}. Must be one of: {', '.join(valid)}")


def parse_capability(value: str) -> Capability:
    """Parse a string into Capability, raising ValueError on invalid input."""
    try:
        return Capability(value.upper())
    except ValueError:
        valid = [c.value for c in Capability]
        raise ValueError(f"Invalid capability {value!r}. Must be one of: {', '.join(valid)}")


def parse_partition(value: str) -> BenchmarkPartition:
    """Parse a string into BenchmarkPartition, raising ValueError on invalid input."""
    try:
        return BenchmarkPartition(value.lower())
    except ValueError:
        valid = [p.value for p in BenchmarkPartition]
        raise ValueError(f"Invalid partition {value!r}. Must be one of: {', '.join(valid)}")


def parse_judge_mode(value: str) -> JudgeMode:
    """Parse a string into JudgeMode, raising ValueError on invalid input."""
    try:
        return JudgeMode(value.upper())
    except ValueError:
        valid = [j.value for j in JudgeMode]
        raise ValueError(f"Invalid judge mode {value!r}. Must be one of: {', '.join(valid)}")


def parse_evaluator_status(value: str) -> EvaluatorStatus:
    """Parse a string into EvaluatorStatus, raising ValueError on invalid input."""
    try:
        return EvaluatorStatus(value.upper())
    except ValueError:
        valid = [s.value for s in EvaluatorStatus]
        raise ValueError(f"Invalid evaluator status {value!r}. Must be one of: {', '.join(valid)}")


def parse_aggregation_strategy(value: str) -> AggregationStrategy:
    """Parse a string into AggregationStrategy, raising ValueError on invalid input."""
    try:
        return AggregationStrategy(value)
    except ValueError:
        valid = [s.value for s in AggregationStrategy]
        raise ValueError(f"Invalid aggregation strategy {value!r}. Must be one of: {', '.join(valid)}")
