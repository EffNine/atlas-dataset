#!/usr/bin/env python3
"""
long_horizon.py — LONG execution mode runner for the EffNine Benchmark (EB).

Handles multi-stage engineering workflows where:
  1. A task is decomposed into ordered stages
  2. Each stage executes within the SAME sandbox/workspace
  3. Repository changes persist across stages
  4. Each stage is evaluated independently
  5. Failures, timeouts, and adapter errors are handled per-stage

Stage lifecycle:
  LONG Task
    -> create sandbox
    -> Stage 1: execute -> evaluate -> StageResult -> checkpoint
    -> Stage 2: execute -> evaluate -> StageResult -> checkpoint
    -> ...
    -> final evaluation
    -> cleanup sandbox

Checkpoint/Resume (Stage 8C):
  - Checkpoint saved after each stage completion
  - On resume: load checkpoint, recreate sandbox, restore workspace,
    execute remaining stages, preserve completed StageResults

Concurrency (Stage 8D):
  - run_batch() executes LONG tasks concurrently with bounded workers
  - Uses asyncio.Semaphore to limit concurrent execution
  - Results are returned in stable submission order
  - One task failure does not cancel unrelated tasks
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..adapters.base import ModelAdapter, ModelRequest
from ..core.checkpoint import CheckpointLoadError, CheckpointV1
from ..core.schema import StageData, StageResult, Task, TaskResult
from ..core.types import ExecutionMode
from ..evaluators.dispatcher import EvaluatorDispatcher
from ..paths import repositories_dir
from ..sandbox.manager import SandboxManager
from .base import RunContext, TaskStatus
from .checkpoint import CheckpointManager
from .repository import RepositoryFixture, _async_run


# ---------------------------------------------------------------------------
# LONG task context
# ---------------------------------------------------------------------------


@dataclass
class LongRunContext:
    """Mutable execution context for a LONG task."""

    run_id: str
    task_id: str
    repeat_id: str
    workspace: Path
    stages: list[StageData]
    stage_results: list[StageResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_time_s: float = 0.0
    start_time: float = 0.0
    status: str = "running"
    sandbox_id: str = ""
    sandbox_image: str = ""
    current_stage_index: int = 0
    prev_response: str = ""

    def record_stage_result(self, result: StageResult) -> None:
        self.stage_results.append(result)
        self.current_stage_index += 1

    def add_error(self, error: str) -> None:
        self.errors.append(error)


# ---------------------------------------------------------------------------
# LONG runner
# ---------------------------------------------------------------------------


class LongHorizonRunner:
    """
    Runner for ExecutionMode.LONG tasks.

    Executes multi-stage engineering workflows inside a persistent sandbox.
    Each stage receives the model's output from the previous stage and can
    inspect/modify the same repository workspace.

    Stages are defined inline in task.context["stages"] for Stage 8A.
    Stage 8B will introduce a formal stages.json fixture schema.
    """

    def __init__(
        self,
        adapter: ModelAdapter,
        dispatcher: EvaluatorDispatcher | None = None,
        sandbox_manager: SandboxManager | None = None,
        max_stages: int = 10,
        max_total_time_s: float = 900.0,
        stage_timeout_s: float = 120.0,
        docker_image: str = "python:3.11-slim",
        output_root: Path | None = None,
        max_concurrent: int = 1,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError(f"max_concurrent must be >= 1, got {max_concurrent}")
        self._adapter = adapter
        self._dispatcher = dispatcher or EvaluatorDispatcher()
        self._sandbox_manager = sandbox_manager or SandboxManager()
        self._max_stages = max_stages
        self._max_total_time_s = max_total_time_s
        self._stage_timeout_s = stage_timeout_s
        self._docker_image = docker_image
        self._output_root = output_root
        self._max_concurrent = max_concurrent

    @property
    def mode(self) -> ExecutionMode:
        return ExecutionMode.LONG

    @property
    def adapter(self) -> ModelAdapter:
        return self._adapter

    @property
    def dispatcher(self) -> EvaluatorDispatcher:
        return self._dispatcher

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    def run(
        self,
        task: Task,
        ctx: RunContext,
        *,
        resume_from: str | None = None,
    ) -> TaskResult:
        """
        Execute a LONG task across multiple stages in a persistent sandbox.

        If resume_from is provided, loads the checkpoint and resumes from
        the saved stage boundary. Otherwise starts fresh.

        Flow (fresh):
          1. Validate task mode is LONG
          2. Extract stages from task.context["stages"]
          3. Load repository fixture (if repository_id provided)
          4. Create sandbox and copy workspace
          5. Execute stages sequentially (saving checkpoints)
          6. Evaluate final state
          7. Cleanup sandbox
          8. Return TaskResult with stage_results

        Flow (resume):
          1-4. Same as above but restore workspace from checkpoint archive
          5. Execute only remaining stages
          6-8. Same as above
        """
        if task.mode != ExecutionMode.LONG:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=[f"mode_mismatch: expected LONG, got {task.mode.value}"],
                execution_metadata={
                    "status": TaskStatus.SKIPPED.value,
                    "reason": f"Task mode {task.mode.value} not supported by LongHorizonRunner",
                },
            )

        task_start = datetime.now(timezone.utc)
        repeat_id = f"r{ctx.repeat_index + 1:02d}"

        # Resume path: load checkpoint and skip to remaining stages
        if resume_from:
            return self._resume(task, ctx, resume_from, task_start, repeat_id)

        # 1. Extract stages
        stages = self._extract_stages(task)
        if not stages:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=["no_stages_defined"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "timestamp": task_start.isoformat(),
                    "reason": "No stages defined in task.context['stages']",
                },
            )

        # 2. Load repository fixture if provided
        repository_id = task.context.get("repository_id", "")
        fixture = None
        if repository_id:
            fixture = self._load_fixture(repository_id)
            if fixture is None:
                return TaskResult(
                    task_id=task.id,
                    run_id=ctx.run_id,
                    raw_response=None,
                    flags=[f"fixture_not_found: {repository_id}"],
                    execution_metadata={
                        "status": TaskStatus.ERROR.value,
                        "repeat_id": repeat_id,
                        "timestamp": task_start.isoformat(),
                    },
                )

        # 3. Create workspace copy
        workspace = self._create_workspace_copy(fixture)
        if workspace is None and fixture is not None:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=["workspace_creation_failed"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "timestamp": task_start.isoformat(),
                },
            )

        # 4. Create sandbox
        sandbox_image = (fixture.image if fixture else None) or self._docker_image
        sandbox_id = ""
        try:
            from ..sandbox.security import SecurityPolicy
            policy = SecurityPolicy(
                network_enabled=task.context.get("network_enabled", False),
                timeout_seconds=self._max_total_time_s,
            )
            sandbox_id = _async_run(self._sandbox_manager.create(sandbox_image, policy))
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=[f"sandbox_creation_failed: {type(e).__name__}: {e}"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "timestamp": task_start.isoformat(),
                    "sandbox_image": sandbox_image,
                },
            )

        # 5. Copy fixture into sandbox
        if fixture and workspace is not None:
            try:
                _async_run(
                    self._sandbox_manager.copy_in(
                        sandbox_id, workspace, fixture.workspace_path
                    )
                )
            except Exception as e:
                self._cleanup(sandbox_id)
                return TaskResult(
                    task_id=task.id,
                    run_id=ctx.run_id,
                    raw_response=None,
                    flags=[f"fixture_copy_failed: {type(e).__name__}: {e}"],
                    execution_metadata={
                        "status": TaskStatus.ERROR.value,
                        "repeat_id": repeat_id,
                        "timestamp": task_start.isoformat(),
                        "sandbox_id": sandbox_id,
                    },
                )

        # 6. Execute stages sequentially
        ws = workspace or Path(tempfile.mkdtemp())
        long_ctx = LongRunContext(
            run_id=ctx.run_id,
            task_id=task.id,
            repeat_id=repeat_id,
            workspace=ws,
            stages=stages,
            sandbox_id=sandbox_id,
            sandbox_image=sandbox_image,
            start_time=time.time(),
        )

        try:
            self._execute_stages(task, long_ctx)
        except Exception as e:
            long_ctx.add_error(f"stage_execution_error: {type(e).__name__}: {e}")
            long_ctx.status = "error"

        # 7. Final evaluation
        elapsed = time.time() - long_ctx.start_time
        long_ctx.total_time_s = round(elapsed, 2)

        # 8. Build TaskResult
        result = self._build_task_result(
            task, long_ctx, task_start, repeat_id, long_ctx.stage_results
        )

        if long_ctx.errors:
            result.flags.extend(long_ctx.errors)

        # 9. Evaluate final result
        self._evaluate_final(task, result, long_ctx)

        # 10. Cleanup
        self._cleanup(sandbox_id)
        self._cleanup_checkpoints(long_ctx)

        return result

    def _cleanup_checkpoints(self, long_ctx: LongRunContext) -> None:
        """Clean up checkpoint files after successful completion."""
        try:
            manager = CheckpointManager(
                run_id=long_ctx.run_id,
                task_id=long_ctx.task_id,
                output_root=self._output_root,
            )
            manager.cleanup()
        except Exception:
            pass

    def run_batch(self, tasks: list[Task], ctx: RunContext) -> list[TaskResult]:
        """
        Execute multiple LONG tasks concurrently with bounded workers.

        Uses asyncio.Semaphore to limit concurrent execution to
        self._max_concurrent tasks. Results are returned in stable
        submission order.

        A single task failure does not cancel unrelated tasks.
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

    # -----------------------------------------------------------------------
    # Stage extraction
    # -----------------------------------------------------------------------

    def _extract_stages(self, task: Task) -> list[StageData]:
        """
        Extract stages from task.context["stages"].

        For Stage 8A, stages are defined inline in the task context.
        Stage 8B will introduce a formal stages.json fixture schema.
        """
        stages_data = task.context.get("stages", [])
        if not stages_data:
            return []

        stages = []
        for stage_data in stages_data:
            if isinstance(stage_data, StageData):
                stages.append(stage_data)
            elif isinstance(stage_data, dict):
                try:
                    stage = StageData.model_validate(stage_data)
                    stages.append(stage)
                except Exception:
                    continue
            else:
                continue

        return stages[:self._max_stages]

    # -----------------------------------------------------------------------
    # Stage execution
    # -----------------------------------------------------------------------

    def _execute_stages(self, task: Task, long_ctx: LongRunContext) -> None:
        """Execute stages sequentially within the persistent sandbox."""
        stage_index = long_ctx.current_stage_index
        prev_response = long_ctx.prev_response if stage_index > 0 else task.prompt

        while stage_index < len(long_ctx.stages):
            # Check total timeout
            elapsed = time.time() - long_ctx.start_time
            if elapsed >= self._max_total_time_s:
                long_ctx.add_error("total_time_exceeded")
                long_ctx.status = "timeout"
                # Record remaining stages as TIMEOUT
                for remaining_stage in long_ctx.stages[stage_index:]:
                    long_ctx.record_stage_result(StageResult(
                        stage_id=remaining_stage.id,
                        stage_name=remaining_stage.name,
                        status="TIMEOUT",
                        error="total_time_exceeded",
                        metadata={"stage_index": stage_index},
                    ))
                return

            stage = long_ctx.stages[stage_index]
            stage_start = time.time()

            # Execute the stage
            stage_result = self._execute_stage(
                task, stage, prev_response, long_ctx, stage_index
            )
            stage_duration = time.time() - stage_start

            stage_result.duration_s = round(stage_duration, 4)
            long_ctx.record_stage_result(stage_result)

            if stage_result.status == "ERROR":
                long_ctx.add_error(f"stage_{stage.id}_failed: {stage_result.error}")
                long_ctx.status = "error"
                return

            # Update prev_response for next stage
            prev_response = stage_result.output or ""
            stage_index += 1

            # Save checkpoint after each successful stage
            self._save_checkpoint(long_ctx, stage_index, prev_response)

        # All stages completed
        if stage_index >= len(long_ctx.stages):
            long_ctx.status = "completed"
        elif stage_index >= self._max_stages:
            long_ctx.add_error("max_stages_reached")
            long_ctx.status = "max_stages"

    def _execute_stage(
        self,
        task: Task,
        stage: StageData,
        prev_response: str,
        long_ctx: LongRunContext,
        stage_index: int,
    ) -> StageResult:
        """Execute a single stage: generate response, evaluate, return StageResult."""
        # Build prompt with stage context
        stage_prompt = self._build_stage_prompt(stage, prev_response, long_ctx)

        # Generate response
        try:
            request = ModelRequest(
                model=long_ctx.run_id,
                prompt=stage_prompt,
                context={
                    "task": task.model_dump(),
                    "stage": stage.model_dump(),
                    "stage_index": stage_index,
                    "sandbox_id": long_ctx.sandbox_id,
                },
            )
            response = self._adapter.generate(request)
        except Exception as e:
            return StageResult(
                stage_id=stage.id,
                stage_name=stage.name,
                status="ERROR",
                error=f"generation_error: {type(e).__name__}: {e}",
                metadata={"stage_index": stage_index},
            )

        if not response.success:
            return StageResult(
                stage_id=stage.id,
                stage_name=stage.name,
                status="ERROR",
                error=response.error or "empty response",
                metadata={"stage_index": stage_index},
            )

        output = response.text.strip() if response.text else ""

        # Evaluate the stage
        stage_task_result = TaskResult(
            task_id=task.id,
            run_id=long_ctx.run_id,
            raw_response=output,
            execution_metadata={
                "stage_index": stage_index,
                "stage_id": stage.id,
                "latency_s": response.latency_s,
                "token_usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
            },
        )

        eval_results = self._dispatcher.dispatch(task, stage_task_result, None)
        raw_score = self._aggregate_scores(eval_results) or 0.0

        return StageResult(
            stage_id=stage.id,
            stage_name=stage.name,
            status="SUCCESS",
            output=output,
            score=raw_score,
            token_usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            evaluator_results=eval_results,
            raw_score=raw_score,
            metadata={"stage_index": stage_index},
        )

    def _build_stage_prompt(
        self, stage: StageData, prev_response: str, long_ctx: LongRunContext
    ) -> str:
        """Build the prompt for a stage, including context from previous stages."""
        lines = [
            f"STAGE: {stage.name}",
            f"STAGE_ID: {stage.id}",
            "",
            stage.prompt,
        ]
        if prev_response:
            lines.append("")
            lines.append("PREVIOUS STAGE OUTPUT:")
            lines.append(prev_response[:2000])
        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Evaluation
    # -----------------------------------------------------------------------

    def _evaluate_final(
        self, task: Task, result: TaskResult, long_ctx: LongRunContext
    ) -> None:
        """Run final evaluation on the complete LONG execution."""
        all_eval_results: list[Any] = []
        all_scores: list[float] = []

        for sr in long_ctx.stage_results:
            all_eval_results.extend(sr.evaluator_results)
            if sr.score is not None:
                all_scores.append(sr.score)

        result.evaluator_results = all_eval_results

        if all_scores:
            result.raw_task_score = sum(all_scores) / len(all_scores)
        elif result.raw_task_score is None:
            result.raw_task_score = 0.0

    def _aggregate_scores(self, eval_results: list[Any]) -> float | None:
        """Aggregate evaluator results into a single score."""
        from ..scoring.raw import aggregate_task_evaluator_results
        strategy = "single_authoritative"
        return aggregate_task_evaluator_results(eval_results, strategy)

    def _collect_final_response(self, long_ctx: LongRunContext) -> str:
        """Collect the final output from the last stage."""
        if long_ctx.stage_results:
            last = long_ctx.stage_results[-1]
            return last.output or ""
        return ""

    def _resolve_status(self, long_ctx: LongRunContext) -> str:
        """Resolve the final TaskResult status from long context."""
        if long_ctx.status == "completed":
            return TaskStatus.SUCCESS.value
        if long_ctx.status in ("timeout", "max_stages"):
            return TaskStatus.FAILED.value
        return TaskStatus.ERROR.value

    # -----------------------------------------------------------------------
    # Repository fixture management (reused from RepositoryRunner)
    # -----------------------------------------------------------------------

    def _load_fixture(self, repository_id: str) -> RepositoryFixture | None:
        """Load a repository fixture by ID."""
        fixtures_root = repositories_dir()
        fixture_dir = fixtures_root / repository_id
        manifest_path = fixture_dir / "fixture.json"
        if not manifest_path.exists():
            return None
        try:
            fixture = RepositoryFixture.from_manifest(manifest_path)
            return fixture
        except Exception:
            return None

    def _create_workspace_copy(self, fixture: RepositoryFixture | None) -> Path | None:
        """Create a clean temporary copy of the fixture for this run."""
        if fixture is None:
            return Path(tempfile.mkdtemp(prefix="eb-long-workspace-"))

        fixtures_root = repositories_dir()
        source_dir = fixtures_root / fixture.fixture_id
        if not source_dir.exists():
            return None

        tmp_dir = Path(tempfile.mkdtemp(prefix=f"eb-long-{fixture.fixture_id}-"))
        try:
            for item in source_dir.iterdir():
                if item.is_dir():
                    shutil.copytree(item, tmp_dir / item.name, symlinks=True)
                else:
                    shutil.copy2(item, tmp_dir / item.name)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

        return tmp_dir

    # -----------------------------------------------------------------------
    # Checkpoint
    # -----------------------------------------------------------------------

    def _save_checkpoint(
        self,
        long_ctx: LongRunContext,
        next_stage_index: int,
        prev_response: str,
    ) -> None:
        """Save a checkpoint after a stage completes successfully."""
        try:
            from ..sandbox.security import SecurityPolicy
            policy = SecurityPolicy(
                network_enabled=long_ctx.sandbox_id != "",
                timeout_seconds=self._max_total_time_s,
            )
            manager = CheckpointManager(
                run_id=long_ctx.run_id,
                task_id=long_ctx.task_id,
                output_root=self._output_root,
            )
            manager.save(
                workspace=long_ctx.workspace,
                completed_stages=long_ctx.stage_results,
                next_stage_index=next_stage_index,
                prev_response=prev_response,
                sandbox_id=long_ctx.sandbox_id,
                sandbox_image=long_ctx.sandbox_image,
                docker_image=self._docker_image,
                fixture_id=None,
                fixture_hash=None,
                security_policy=policy.to_dict(),
                configuration={
                    "max_stages": self._max_stages,
                    "max_total_time_s": self._max_total_time_s,
                    "stage_timeout_s": self._stage_timeout_s,
                    "docker_image": self._docker_image,
                },
                backend=self._sandbox_manager.backend,
                repeat_id=long_ctx.repeat_id,
            )
        except Exception:
            pass  # Checkpoint failure is non-fatal

    def _resume(
        self,
        task: Task,
        ctx: RunContext,
        resume_from: str,
        task_start: datetime,
        repeat_id: str,
    ) -> TaskResult:
        """
        Resume a LONG task from a checkpoint.

        Validates the checkpoint, restores workspace, creates a new sandbox,
        and executes only the remaining stages.
        """
        try:
            ckpt_path = Path(resume_from)
            if not ckpt_path.exists():
                ckpt_base = Path(resume_from)
                if ckpt_base.is_dir():
                    ckpt_path = ckpt_base / "checkpoint.json"
                else:
                    ckpt_path = Path(resume_from)

            manager = CheckpointManager(
                run_id=ctx.run_id,
                task_id=task.id,
                output_root=self._output_root,
            )
            checkpoint = manager.load_from_path(ckpt_path)
        except CheckpointLoadError as e:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=[f"checkpoint_load_error: {e}"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "timestamp": task_start.isoformat(),
                    "reason": str(e),
                },
            )

        # Validate backend matches
        if checkpoint.backend != self._sandbox_manager.backend:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=[f"backend_mismatch: checkpoint={checkpoint.backend}, runner={self._sandbox_manager.backend}"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "timestamp": task_start.isoformat(),
                    "reason": f"Checkpoint backend {checkpoint.backend!r} does not match runner backend {self._sandbox_manager.backend!r}",
                },
            )

        # Validate docker image matches
        if checkpoint.docker_image and checkpoint.docker_image != self._docker_image:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=["docker_image_mismatch"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "timestamp": task_start.isoformat(),
                    "reason": f"Checkpoint docker image {checkpoint.docker_image!r} does not match runner image {self._docker_image!r}",
                },
            )

        # Load stages from task
        stages = self._extract_stages(task)
        if not stages:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=["no_stages_defined"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "timestamp": task_start.isoformat(),
                    "reason": "No stages defined in task.context['stages']",
                },
            )

        # Reconstruct completed stages
        completed_stages: list[StageResult] = []
        for sr_dict in checkpoint.completed_stages:
            try:
                completed_stages.append(StageResult.model_validate(sr_dict))
            except Exception:
                continue

        # Validate next_stage_index is within bounds
        next_idx = checkpoint.next_stage_index
        if next_idx > len(stages):
            next_idx = len(stages)

        # If all stages already completed, this is a no-op resume
        if next_idx >= len(stages):
            # Build result from completed stages
            long_ctx = LongRunContext(
                run_id=ctx.run_id,
                task_id=task.id,
                repeat_id=repeat_id,
                workspace=Path(tempfile.mkdtemp()),
                stages=stages,
                stage_results=completed_stages,
                start_time=time.time(),
                current_stage_index=len(stages),
                status="completed",
            )
            result = self._build_task_result(
                task, long_ctx, task_start, repeat_id, completed_stages
            )
            manager.cleanup()
            return result

        # Create workspace for restoration
        workspace = Path(tempfile.mkdtemp(prefix=f"eb-long-resume-{task.id}-"))
        try:
            # Validate and restore workspace from archive
            manager.validate_checkpoint(checkpoint, workspace=workspace, checkpoint_path=ckpt_path)
        except Exception as e:
            import shutil
            shutil.rmtree(workspace, ignore_errors=True)
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=[f"checkpoint_validation_error: {e}"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "timestamp": task_start.isoformat(),
                    "reason": str(e),
                },
            )

        # Create NEW sandbox (never reuse old sandbox_id)
        sandbox_image = checkpoint.sandbox_image or self._docker_image
        sandbox_id = ""
        try:
            from ..sandbox.security import SecurityPolicy
            policy = SecurityPolicy.from_dict(checkpoint.security_policy)
            sandbox_id = _async_run(self._sandbox_manager.create(sandbox_image, policy))
        except Exception as e:
            import shutil
            shutil.rmtree(workspace, ignore_errors=True)
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=[f"sandbox_creation_failed: {type(e).__name__}: {e}"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "timestamp": task_start.isoformat(),
                    "sandbox_image": sandbox_image,
                },
            )

        # Copy restored workspace into sandbox
        try:
            _async_run(
                self._sandbox_manager.copy_in(
                    sandbox_id, workspace, "/workspace"
                )
            )
        except Exception as e:
            self._cleanup(sandbox_id)
            import shutil
            shutil.rmtree(workspace, ignore_errors=True)
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=[f"fixture_copy_failed: {type(e).__name__}: {e}"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "timestamp": task_start.isoformat(),
                    "sandbox_id": sandbox_id,
                },
            )

        # Build LongRunContext with completed stages preserved
        long_ctx = LongRunContext(
            run_id=ctx.run_id,
            task_id=task.id,
            repeat_id=repeat_id,
            workspace=workspace,
            stages=stages,
            stage_results=completed_stages,
            sandbox_id=sandbox_id,
            sandbox_image=sandbox_image,
            start_time=time.time(),
            current_stage_index=next_idx,
        )

        # Execute remaining stages
        try:
            self._execute_stages(task, long_ctx)
        except Exception as e:
            long_ctx.add_error(f"stage_execution_error: {type(e).__name__}: {e}")
            long_ctx.status = "error"

        # Final evaluation
        final_response = self._collect_final_response(long_ctx)
        elapsed = time.time() - long_ctx.start_time
        long_ctx.total_time_s = round(elapsed, 2)

        result = self._build_task_result(
            task, long_ctx, task_start, repeat_id, long_ctx.stage_results
        )

        if long_ctx.errors:
            result.flags.extend(long_ctx.errors)

        # Evaluate final result
        self._evaluate_final(task, result, long_ctx)

        # Cleanup sandbox and checkpoint
        self._cleanup(sandbox_id)
        manager.cleanup()

        return result

    def _build_task_result(
        self,
        task: Task,
        long_ctx: LongRunContext,
        task_start: datetime,
        repeat_id: str,
        stage_results: list[StageResult],
    ) -> TaskResult:
        """Build a TaskResult from a LongRunContext."""
        final_response = self._collect_final_response(long_ctx)
        return TaskResult(
            task_id=task.id,
            run_id=long_ctx.run_id,
            raw_response=final_response,
            stage_results=stage_results,
            sandbox_id_long=long_ctx.sandbox_id,
            execution_metadata={
                "status": self._resolve_status(long_ctx),
                "repeat_id": repeat_id,
                "stage_count": len(stage_results),
                "max_stages": self._max_stages,
                "total_time_s": long_ctx.total_time_s,
                "stages": [
                    {
                        "stage_id": sr.stage_id,
                        "stage_name": sr.stage_name,
                        "status": sr.status,
                        "score": sr.score,
                        "duration_s": sr.duration_s,
                        "error": sr.error,
                    }
                    for sr in stage_results
                ],
                "timestamp": task_start.isoformat(),
            },
        )

    def _cleanup(self, sandbox_id: str) -> None:
        """Clean up sandbox resources."""
        if sandbox_id:
            try:
                _async_run(self._sandbox_manager.stop(sandbox_id))
            except Exception:
                pass
            try:
                _async_run(self._sandbox_manager.destroy(sandbox_id))
            except Exception:
                pass
