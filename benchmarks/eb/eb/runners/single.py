#!/usr/bin/env python3
"""
single.py — SINGLE execution mode runner for the EffNine Benchmark (EB).

Handles standalone reasoning, architecture, advisory, and judgment tasks.
One prompt, one response. No multi-turn state, no repository execution,
no long-horizon orchestration.

The runner:
  - Validates that the task mode is SINGLE
  - Builds a ModelRequest from the task
  - Invokes the ModelAdapter
  - Dispatches evaluators via EvaluatorDispatcher
  - Aggregates evaluator results into raw_task_score
  - Preserves execution metadata (latency, tokens, settings, timestamps)
  - Does NOT compute EB Score
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ..adapters.base import ModelAdapter, ModelRequest
from ..core.schema import Task, TaskResult
from ..core.types import ExecutionMode
from ..evaluators.dispatcher import EvaluatorDispatcher
from ..scoring.raw import aggregate_task_evaluator_results
from .base import RunContext, Runner, TaskStatus


class SingleRunner(Runner):
    """
    Runner for ExecutionMode.SINGLE tasks.

    Executes one prompt → one response per task. Repeated runs are tracked
    as separate TaskResult entries within the same run.
    """

    @property
    def mode(self) -> ExecutionMode:
        return ExecutionMode.SINGLE

    def __init__(self, adapter: ModelAdapter, dispatcher: EvaluatorDispatcher | None = None) -> None:
        self._adapter = adapter
        self._dispatcher = dispatcher or EvaluatorDispatcher()

    @property
    def adapter(self) -> ModelAdapter:
        return self._adapter

    @property
    def dispatcher(self) -> EvaluatorDispatcher:
        return self._dispatcher

    def run(self, task: Task, ctx: RunContext) -> TaskResult:
        """
        Execute a SINGLE task via the model adapter, then evaluate.
        """
        if task.mode != ExecutionMode.SINGLE:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=[f"mode_mismatch: expected SINGLE, got {task.mode.value}"],
                execution_metadata={
                    "status": TaskStatus.SKIPPED.value,
                    "reason": f"Task mode {task.mode.value} not supported by SingleRunner",
                },
            )

        repeat_id = f"r{ctx.repeat_index + 1:02d}"
        task_start = datetime.now(timezone.utc)

        # Build the model request
        request = self._build_request(task, ctx)

        try:
            response = self._adapter.generate(request)
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=[f"generation_error: {type(e).__name__}: {e}"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "request": self._serialize_request(request),
                    "timestamp": task_start.isoformat(),
                },
            )

        # Build TaskResult from response
        result = TaskResult(
            task_id=task.id,
            run_id=ctx.run_id,
            raw_response=response.text if response.success else None,
            execution_metadata={
                "status": TaskStatus.SUCCESS.value if response.success else TaskStatus.FAILED.value,
                "repeat_id": repeat_id,
                "adapter": response.backend,
                "model": response.model,
                "finish_reason": response.finish_reason,
                "latency_s": response.latency_s,
                "token_usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
                "inference_settings": {
                    "seed": ctx.inference_settings.get("seed", 42),
                    "temperature": ctx.inference_settings.get("temperature", 0.0),
                    "top_p": ctx.inference_settings.get("top_p", 1.0),
                    "top_k": ctx.inference_settings.get("top_k", 0),
                    "max_tokens": ctx.inference_settings.get("max_tokens", 4096),
                },
                "timestamp": task_start.isoformat(),
                "adapter_metadata": self._adapter.metadata().to_dict(),
            },
        )

        if response.error:
            result.flags.append(f"adapter_error: {response.error}")
            result.execution_metadata["status"] = TaskStatus.ERROR.value
            result.execution_metadata["error"] = response.error

        # Stage 3: Evaluate the response
        self._evaluate(task, result)

        return result

    def _evaluate(self, task: Task, result: TaskResult) -> None:
        """Run evaluators and aggregate into raw_task_score."""
        evaluator_specs = task.evaluation.evaluators if task.evaluation.evaluators else None
        eval_results = self._dispatcher.dispatch(task, result, evaluator_specs)
        result.evaluator_results = eval_results

        # Aggregate evaluator results into raw_task_score
        strategy = task.evaluation.aggregation.get("strategy", "single_authoritative")
        raw_score = aggregate_task_evaluator_results(eval_results, strategy)
        result.raw_task_score = raw_score

        # Collect primary evidence from all evaluators
        all_evidence = []
        for ev in eval_results:
            all_evidence.extend(ev.evidence)
        result.primary_evidence = all_evidence[:10]  # Limit to avoid bloating artifacts

        # Set flags from evaluators
        for ev in eval_results:
            result.flags.extend(ev.flags)

    def _build_request(self, task: Task, ctx: RunContext) -> ModelRequest:
        """Construct a ModelRequest from a Task and RunContext."""
        settings = ctx.inference_settings
        return ModelRequest(
            model=ctx.model_name,
            prompt=task.prompt,
            system_prompt=task.context.get("system_prompt"),
            context=task.context,
            inference_settings=None,  # adapter uses ctx settings
        )

    def _serialize_request(self, request: ModelRequest) -> dict[str, Any]:
        """Serialize a ModelRequest for error metadata (no sensitive data)."""
        return {
            "model": request.model,
            "prompt_len": len(request.prompt),
            "has_system_prompt": request.system_prompt is not None,
            "context_keys": list(request.context.keys()),
        }
