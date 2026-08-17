#!/usr/bin/env python3
"""
base.py — Abstract Evaluator interface for the EffNine Benchmark (EB).

Defines the contract that all evaluators must implement. Evaluators receive
a validated Task and a ModelResponse (via TaskResult), and produce an
EvaluatorResult with a deterministic score, evidence, and status.

Stage 3: tiers 1 (deterministic) and non-AI parts of tier 2 (rubric).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..core.schema import EvaluatorResult, Task, TaskResult
from ..core.types import JudgeMode


class Evaluator(ABC):
    """
    Abstract base class for all evaluators.

    Every evaluator must declare:
      - name: the registry key used to look up this evaluator
      - authority_level: higher numbers = more authoritative (1=deterministic, 2=rubric, 3=cloud judge, 4=ai opinion)
      - supported_modes: which JudgeModes this evaluator handles

    The evaluate() method receives a Task and a partially-built TaskResult
    (with raw_response populated) and returns an EvaluatorResult.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique registry key for this evaluator (e.g. 'exact', 'code', 'evidence', 'rubric')."""
        ...

    @property
    def authority_level(self) -> int:
        """
        Authority tier: higher = more authoritative.
        1 = deterministic evidence (highest for Stage 3)
        2 = rubric/reference
        3 = cloud judge
        4 = AI opinion
        """
        return 1

    @property
    def supported_modes(self) -> list[JudgeMode]:
        """JudgeModes this evaluator can handle."""
        return [JudgeMode.DETERMINISTIC]

    @abstractmethod
    def evaluate(self, task: Task, result: TaskResult) -> EvaluatorResult:
        """
        Evaluate a model response against a task.

        Args:
            task: The validated benchmark task.
            result: The TaskResult containing raw_response and execution metadata.

        Returns:
            EvaluatorResult with score, status, evidence, and flags.
        """
        ...

    def is_applicable(self, task: Task) -> bool:
        """
        Check whether this evaluator can meaningfully evaluate the given task.

        Override to implement early-exit logic (e.g. no expected answer for exact).
        Default: always applicable.
        """
        return True
