#!/usr/bin/env python3
"""
multi.py — MULTI execution mode runner for the EffNine Benchmark (EB).

Handles multi-turn tasks where the model maintains conversation state
across multiple turns. Each turn can have changing context or requirements.

Protocol:
  - Model responses starting with "CONTINUE:" trigger another turn.
  - Model responses starting with "FINAL_ANSWER:" terminate the turn sequence.
  - Any other response is treated as a final answer.
  - The runner also respects max_turns and total time limits.

Concurrency:
  - run_batch() executes tasks concurrently with bounded workers.
  - One failure does not corrupt unrelated task results.
  - Cancellation triggers cleanup of active sandboxes/turns.
  - Results are returned in stable submission order.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..adapters.base import ModelAdapter, ModelRequest
from ..core.schema import Task, TaskResult
from ..core.types import ExecutionMode
from ..evaluators.dispatcher import EvaluatorDispatcher
from ..scoring.raw import aggregate_task_evaluator_results
from .base import RunContext, Runner, TaskStatus


# ---------------------------------------------------------------------------
# Turn tracking
# ---------------------------------------------------------------------------


@dataclass
class TurnRecord:
    """A single turn in a MULTI task execution."""

    turn_index: int
    request: ModelRequest
    response_text: str | None
    latency_s: float
    token_usage: dict[str, int]
    status: str = "success"
    error: str | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "response_text": self.response_text,
            "latency_s": self.latency_s,
            "token_usage": self.token_usage,
            "status": self.status,
            "error": self.error,
            "timestamp": self.timestamp,
        }


@dataclass
class MultiTurnContext:
    """Mutable context for a single MULTI task execution."""

    task_id: str
    run_id: str
    repeat_id: str
    turns: list[TurnRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    final_response: str | None = None
    total_time_s: float = 0.0
    start_time: float = 0.0
    status: str = "running"


# ---------------------------------------------------------------------------
# MULTI runner
# ---------------------------------------------------------------------------


class MultiRunner(Runner):
    """
    Runner for ExecutionMode.MULTI tasks.

    Executes multi-turn conversations where the model maintains state
    across turns. Supports bounded concurrency in batch mode.

    The turn protocol uses:
      - "CONTINUE:<next_turn_prompt>" to request another turn
      - "FINAL_ANSWER:<answer>" to terminate
      - Any other text is treated as a final answer
    """

    def __init__(
        self,
        adapter: ModelAdapter,
        dispatcher: EvaluatorDispatcher | None = None,
        max_turns: int = 10,
        turn_timeout_s: float = 120.0,
        max_total_time_s: float = 600.0,
        max_concurrent: int = 4,
    ) -> None:
        self._adapter = adapter
        self._dispatcher = dispatcher or EvaluatorDispatcher()
        self._max_turns = max_turns
        self._turn_timeout_s = turn_timeout_s
        self._max_total_time_s = max_total_time_s
        self._max_concurrent = max_concurrent
        self._semaphore: asyncio.Semaphore | None = None

    @property
    def mode(self) -> ExecutionMode:
        return ExecutionMode.MULTI

    @property
    def adapter(self) -> ModelAdapter:
        return self._adapter

    @property
    def dispatcher(self) -> EvaluatorDispatcher:
        return self._dispatcher

    @property
    def max_turns(self) -> int:
        return self._max_turns

    @property
    def turn_timeout_s(self) -> float:
        return self._turn_timeout_s

    @property
    def max_total_time_s(self) -> float:
        return self._max_total_time_s

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    def run(self, task: Task, ctx: RunContext) -> TaskResult:
        """
        Execute a single MULTI task with bounded multi-turn conversation.
        """
        if task.mode != ExecutionMode.MULTI:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=[f"mode_mismatch: expected MULTI, got {task.mode.value}"],
                execution_metadata={
                    "status": TaskStatus.SKIPPED.value,
                    "reason": f"Task mode {task.mode.value} not supported by MultiRunner",
                },
            )

        repeat_id = f"r{ctx.repeat_index + 1:02d}"
        turn_ctx = MultiTurnContext(
            task_id=task.id,
            run_id=ctx.run_id,
            repeat_id=repeat_id,
            start_time=time.time(),
        )

        system_prompt = self._build_system_prompt(task, self._max_turns)
        current_prompt = task.prompt
        turn_index = 0
        total_latency = 0.0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        turn_history: list[dict[str, str]] = []

        while turn_index < self._max_turns:
            elapsed = time.time() - turn_ctx.start_time
            if elapsed >= self._max_total_time_s:
                turn_ctx.errors.append("total_time_exceeded")
                turn_ctx.status = "timeout"
                break

            turn_start = time.time()
            messages = turn_history + [{"role": "user", "content": current_prompt}]

            request = ModelRequest(
                model=ctx.model_name,
                messages=messages,
                system_prompt=system_prompt,
                context={
                    "task": task.model_dump(),
                    "turn_index": turn_index,
                    "max_turns": self._max_turns,
                },
            )

            try:
                response = self._adapter.generate(request)
            except Exception as e:
                turn_ctx.errors.append(f"generation_error: {type(e).__name__}: {e}")
                turn_ctx.status = "error"
                turn_record = TurnRecord(
                    turn_index=turn_index,
                    request=request,
                    response_text=None,
                    latency_s=0.0,
                    token_usage={},
                    status="error",
                    error=str(e),
                )
                turn_ctx.turns.append(turn_record)
                break

            turn_latency = time.time() - turn_start
            total_latency += turn_latency

            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            total_prompt_tokens += prompt_tokens
            total_completion_tokens += completion_tokens

            turn_record = TurnRecord(
                turn_index=turn_index,
                request=request,
                response_text=response.text if response.success else None,
                latency_s=round(turn_latency, 4),
                token_usage={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
                status="success" if response.success else "failed",
                error=response.error,
            )
            turn_ctx.turns.append(turn_record)

            if not response.success:
                turn_ctx.errors.append(f"adapter_error: {response.error or 'empty response'}")
                turn_ctx.status = "error"
                break

            response_text = response.text.strip()

            if response_text.startswith("FINAL_ANSWER:"):
                turn_ctx.final_response = response_text[len("FINAL_ANSWER:"):].strip()
                turn_ctx.status = "completed"
                break

            if response_text.startswith("CONTINUE:"):
                next_turn = response_text[len("CONTINUE:"):].strip()
                turn_history.append({"role": "assistant", "content": response_text})
                turn_history.append({"role": "user", "content": next_turn})
                current_prompt = next_turn
                turn_index += 1
                continue

            turn_ctx.final_response = response_text
            turn_ctx.status = "completed"
            break

        if turn_ctx.status == "running":
            turn_ctx.status = "timeout"
            turn_ctx.errors.append("max_turns_reached")

        turn_ctx.total_time_s = round(time.time() - turn_ctx.start_time, 2)

        result = TaskResult(
            task_id=task.id,
            run_id=ctx.run_id,
            raw_response=turn_ctx.final_response,
            execution_metadata={
                "status": self._resolve_status(turn_ctx),
                "repeat_id": repeat_id,
                "turn_count": len(turn_ctx.turns),
                "max_turns": self._max_turns,
                "total_time_s": turn_ctx.total_time_s,
                "total_latency_s": round(total_latency, 4),
                "token_usage": {
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                    "total_tokens": total_prompt_tokens + total_completion_tokens,
                },
                "turns": [t.to_dict() for t in turn_ctx.turns],
                "inference_settings": {
                    "seed": ctx.inference_settings.get("seed", 42),
                    "temperature": ctx.inference_settings.get("temperature", 0.0),
                    "top_p": ctx.inference_settings.get("top_p", 1.0),
                    "top_k": ctx.inference_settings.get("top_k", 0),
                    "max_tokens": ctx.inference_settings.get("max_tokens", 4096),
                },
                "adapter_metadata": self._adapter.metadata().to_dict(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        if turn_ctx.errors:
            result.flags.extend(turn_ctx.errors)

        self._evaluate(task, result)

        return result

    def run_batch(self, tasks: list[Task], ctx: RunContext) -> list[TaskResult]:
        """
        Execute multiple MULTI tasks concurrently with bounded workers.

        Uses asyncio.Semaphore to limit concurrent execution to
        self._max_concurrent tasks. Results are returned in stable
        submission order.
        """
        if not tasks:
            return []

        max_workers = min(self._max_concurrent, len(tasks))

        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(
                self._run_batch_async(tasks, ctx, max_workers)
            )
        finally:
            loop.close()

        return results

    async def _run_batch_async(
        self,
        tasks: list[Task],
        ctx: RunContext,
        max_workers: int,
    ) -> list[TaskResult]:
        """Async implementation of batch execution with bounded concurrency."""
        semaphore = asyncio.Semaphore(max_workers)
        tasks_with_index = [(i, task) for i, task in enumerate(tasks)]
        results_by_index: dict[int, TaskResult] = {}
        lock = asyncio.Lock()

        async def _execute_one(index: int, task: Task) -> None:
            async with semaphore:
                try:
                    result = await asyncio.to_thread(self.run, task, ctx)
                except Exception as e:
                    result = TaskResult(
                        task_id=task.id,
                        run_id=ctx.run_id,
                        raw_response=None,
                        flags=[f"batch_error: {type(e).__name__}: {e}"],
                        execution_metadata={
                            "status": TaskStatus.ERROR.value,
                            "repeat_id": f"r{ctx.repeat_index + 1:02d}",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                async with lock:
                    results_by_index[index] = result

        await asyncio.gather(*[
            _execute_one(i, t) for i, t in tasks_with_index
        ])

        return [results_by_index[i] for i in range(len(tasks))]

    def _evaluate(self, task: Task, result: TaskResult) -> None:
        """Run evaluators and aggregate into raw_task_score."""
        evaluator_specs = task.evaluation.evaluators if task.evaluation.evaluators else None
        eval_results = self._dispatcher.dispatch(task, result, evaluator_specs)
        result.evaluator_results = eval_results

        strategy = task.evaluation.aggregation.get("strategy", "single_authoritative")
        raw_score = aggregate_task_evaluator_results(eval_results, strategy)
        result.raw_task_score = raw_score

        all_evidence = []
        for ev in eval_results:
            all_evidence.extend(ev.evidence)
        result.primary_evidence = all_evidence[:10]

        for ev in eval_results:
            result.flags.extend(ev.flags)

    def _resolve_status(self, turn_ctx: MultiTurnContext) -> str:
        """Resolve the final status from turn context."""
        if turn_ctx.status == "error":
            return TaskStatus.ERROR.value
        if turn_ctx.status == "timeout":
            return TaskStatus.FAILED.value
        if turn_ctx.status == "completed":
            return TaskStatus.SUCCESS.value
        return TaskStatus.ERROR.value

    def _build_system_prompt(self, task: Task, max_turns: int) -> str:
        """Build the system prompt for MULTI turn conversations."""
        return (
            f"You are participating in a multi-turn benchmark task.\n"
            f"Your goal is to complete the task through conversation.\n\n"
            f"CONVERSATION PROTOCOL:\n"
            f"- To request another turn, respond with: CONTINUE:<your_message>\n"
            f"- To submit your final answer, respond with: FINAL_ANSWER:<your_answer>\n"
            f"- Maximum turns allowed: {max_turns}\n\n"
            f"Respond according to the protocol above."
        )
