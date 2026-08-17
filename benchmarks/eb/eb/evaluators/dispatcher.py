#!/usr/bin/env python3
"""
dispatcher.py — Evaluator registry and dispatcher for the EffNine Benchmark (EB).

Maps evaluator type names to concrete Evaluator implementations.
Unknown types fail clearly. Unsupported evaluators produce explicit
UNSUPPORTED status rather than silent omission.
"""

from __future__ import annotations

from typing import Any

from ..core.schema import EvaluatorResult, Task, TaskResult
from ..core.types import EvaluatorStatus, JudgeMode
from .base import Evaluator


class EvaluatorDispatcher:
    """
    Registry-based dispatcher that selects evaluators for a task.

    Usage:
        dispatcher = EvaluatorDispatcher()
        dispatcher.register(ExactEvaluator())
        dispatcher.register(CodeEvaluator())
        dispatcher.register(EvidenceEvaluator())
        dispatcher.register(RubricEvaluator())

        results = dispatcher.dispatch(task, task_result)
    """

    def __init__(self) -> None:
        self._registry: dict[str, Evaluator] = {}

    def register(self, evaluator: Evaluator) -> None:
        """Register an evaluator by its name."""
        self._registry[evaluator.name] = evaluator

    def get(self, name: str) -> Evaluator | None:
        """Look up an evaluator by name. Returns None if not registered."""
        return self._registry.get(name)

    def dispatch(
        self,
        task: Task,
        result: TaskResult,
        evaluator_specs: list[dict[str, Any]] | None = None,
    ) -> list[EvaluatorResult]:
        """
        Select and run evaluators for a task based on its evaluation config.

        Args:
            task: The benchmark task.
            result: The TaskResult with raw_response populated.
            evaluator_specs: Explicit evaluator specs from task.evaluation.evaluators.
                             If None, falls back to primary_mode heuristic.

        Returns:
            List of EvaluatorResult, one per configured evaluator.
        """
        from .exact import ExactEvaluator
        from .code import CodeEvaluator
        from .evidence import EvidenceEvaluator
        from .rubric import RubricEvaluator
        from .judge import JudgeEvaluator

        # Ensure core evaluators are registered
        for ev_cls in (ExactEvaluator, CodeEvaluator, EvidenceEvaluator, RubricEvaluator):
            ev = ev_cls()
            if ev.name not in self._registry:
                self.register(ev)

        # Register judge evaluator if not already present
        if "judge" not in self._registry:
            self.register(JudgeEvaluator())

        if evaluator_specs is None:
            # Use explicit evaluator specs from task config if available
            evaluator_specs = task.evaluation.evaluators
            if not evaluator_specs:
                evaluator_specs = self._default_specs(task)

        outcomes: list[EvaluatorResult] = []

        for spec in evaluator_specs:
            ev_type = spec.get("type")
            if ev_type is None:
                continue

            evaluator = self._resolve_evaluator(ev_type)
            if evaluator is None:
                outcomes.append(
                    EvaluatorResult(
                        evaluator=ev_type,
                        mode=self._infer_mode(task, ev_type),
                        status=EvaluatorStatus.UNSUPPORTED,
                        rationale=f"No evaluator registered for type {ev_type!r}",
                        flags=[f"unknown_evaluator_type:{ev_type}"],
                    )
                )
                continue

            # Check if this evaluator is applicable to the task
            if not evaluator.is_applicable(task):
                outcomes.append(
                    EvaluatorResult(
                        evaluator=ev_type,
                        mode=self._infer_mode(task, ev_type),
                        status=EvaluatorStatus.NOT_APPLICABLE,
                        rationale=f"Evaluator {ev_type!r} is not applicable to this task",
                        flags=[f"not_applicable:{ev_type}"],
                    )
                )
                continue

            try:
                outcome = evaluator.evaluate(task, result)
                outcomes.append(outcome)
            except Exception as e:
                outcomes.append(
                    EvaluatorResult(
                        evaluator=ev_type,
                        mode=self._infer_mode(task, ev_type),
                        status=EvaluatorStatus.ERROR,
                        rationale=f"Evaluator {ev_type!r} raised {type(e).__name__}: {e}",
                        flags=[f"evaluator_error:{ev_type}"],
                        details={"error_type": type(e).__name__, "error_msg": str(e)},
                    )
                )

        return outcomes

    def _resolve_evaluator(self, name: str) -> Evaluator | None:
        """Look up an evaluator by name, with fallback to known classes."""
        if name in self._registry:
            return self._registry[name]
        # Lazy import known evaluators to avoid circular imports
        from .exact import ExactEvaluator
        from .code import CodeEvaluator
        from .evidence import EvidenceEvaluator
        from .rubric import RubricEvaluator
        from .judge import JudgeEvaluator

        known: dict[str, type[Evaluator]] = {
            "exact": ExactEvaluator,
            "code": CodeEvaluator,
            "evidence": EvidenceEvaluator,
            "rubric": RubricEvaluator,
            "judge": JudgeEvaluator,
        }
        cls = known.get(name)
        if cls is not None:
            instance = cls()
            self.register(instance)
            return instance
        return None

    def _default_specs(self, task: Task) -> list[dict[str, Any]]:
        """Build default evaluator specs from task.evaluation when none are explicit."""
        eval_config = task.evaluation
        mode = eval_config.primary_mode

        if mode == JudgeMode.DETERMINISTIC:
            # Heuristic: pick evaluators based on task category and context
            specs: list[dict[str, Any]] = []
            cat = task.category.lower()
            ctx = task.context

            # Check for expected answer in context
            if "expected" in ctx or "acceptable_answers" in ctx or "answer" in ctx:
                specs.append({
                    "type": "exact",
                    "required": True,
                    "parameters": {
                        "expected": ctx.get("expected") or ctx.get("answer"),
                        "acceptable_answers": ctx.get("acceptable_answers"),
                        "normalization": ctx.get("normalization", "trim"),
                    },
                })

            # Code tasks get code evaluator
            if cat in ("coding", "code", "debug") or "code" in ctx:
                specs.append({
                    "type": "code",
                    "required": False,
                    "parameters": ctx.get("code_check", {}),
                })

            # Evidence tasks
            if cat in ("evidence",) or ctx.get("required_claims") or ctx.get("required_evidence"):
                specs.append({
                    "type": "evidence",
                    "required": False,
                    "parameters": {
                        "required_claims": ctx.get("required_claims", []),
                        "forbidden_claims": ctx.get("forbidden_claims", []),
                        "expected_facts": ctx.get("expected_facts", []),
                    },
                })

            if not specs:
                # Default: exact with no expected (will be NOT_APPLICABLE)
                specs.append({"type": "exact", "required": False, "parameters": {}})

            return specs

        if mode == JudgeMode.RUBRIC:
            criteria = eval_config.extra.get("criteria", [])
            return [{
                "type": "rubric",
                "required": True,
                "parameters": {
                    "criteria": criteria,
                    "weights": eval_config.extra.get("weights", {}),
                },
            }]

        # CLOUD_JUDGE and AI_OPINION are Stage 4+
        return [{
            "type": "rubric",
            "required": False,
            "parameters": {"criteria": [], "_pending_judge": True},
        }]

    def _infer_mode(self, task: Task, evaluator_type: str) -> JudgeMode:
        """Infer the JudgeMode for an evaluator result."""
        mode = task.evaluation.primary_mode
        if evaluator_type in ("exact", "code", "evidence"):
            return JudgeMode.DETERMINISTIC
        if evaluator_type == "rubric":
            return JudgeMode.RUBRIC
        return mode
