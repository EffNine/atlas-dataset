#!/usr/bin/env python3
"""
run_orchestration.py — Run orchestration for the EffNine Benchmark (EB).

Coordinates task loading, model adapter selection, runner invocation,
result collection, artifact writing, and registry updates. This is the
glue between the CLI and the runner/adapter layers.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..adapters.base import ModelAdapter
from ..adapters.factory import AdapterFactory
from ..core.manifest import BenchmarkRunManifest
from ..core.registry import BenchmarkRegistry
from ..core.schema import BaselineRecord, BenchmarkRun, EnvironmentInfo, InferenceSettings, ModelMetadata, RepeatedRunStats, TaskResult
from ..core.types import BenchmarkPartition, ExecutionMode
from ..evaluators.dispatcher import EvaluatorDispatcher
from ..paths import runs_dir
from ..scoring.eb_score import EbScoreResult, compute_eb_score
from ..scoring.raw import RunRawScores
from .base import RunContext, TaskStatus
from .long_horizon import LongHorizonRunner
from .multi import MultiRunner
from .repository import RepositoryRunner
from .single import SingleRunner


@dataclass
class RunSummary:
    """Human-readable summary of a benchmark run."""

    run_id: str
    model: str
    suite: str
    tasks_selected: int
    tasks_executed: int
    successes: int
    failures: int
    errors: int
    skipped: int
    elapsed_s: float
    artifact_dir: Path
    status: str = "completed"

    def print(self) -> None:
        print(f"\n{'='*60}")
        print(f"EB Run Complete: {self.run_id}")
        print(f"{'='*60}")
        print(f"  model          = {self.model}")
        print(f"  suite          = {self.suite}")
        print(f"  tasks selected = {self.tasks_selected}")
        print(f"  tasks executed = {self.tasks_executed}")
        print(f"  successes      = {self.successes}")
        print(f"  failures       = {self.failures}")
        print(f"  errors         = {self.errors}")
        print(f"  skipped        = {self.skipped}")
        print(f"  elapsed        = {self.elapsed_s:.1f}s")
        print(f"  artifacts      = {self.artifact_dir}")
        print(f"  status         = {self.status}")
        print(f"{'='*60}\n")


class RunOrchestrator:
    """
    Orchestrates a full benchmark run from CLI args to artifact output.

    Flow:
      1. Discover EB root and load config
      2. Load and filter tasks by suite/mode/partition
      3. Resolve model adapter via factory
      4. Execute tasks through the appropriate runner
      5. Write run artifacts (manifest, results, summary)
      6. Register the run in BenchmarkRegistry
    """

    def __init__(
        self,
        model_name: str,
        suite: str = "full",
        partitions: list[str] | None = None,
        repeats: int = 1,
        seed: int = 42,
        temperature: float = 0.0,
        top_p: float = 1.0,
        top_k: int = 0,
        max_tokens: int = 4096,
        context_length: int = 8192,
        benchmark_version: str | None = None,
        task_set_version: str | None = None,
        adapter_factory: AdapterFactory | None = None,
        output_dir: Path | None = None,
        baseline_run_id: str | None = None,
        as_baseline: bool = False,
        max_tool_calls: int = 50,
        sandbox_timeout: float = 300.0,
        docker_image: str = "python:3.11-slim",
        multi_max_turns: int = 10,
        multi_turn_timeout: float = 120.0,
        multi_max_total_time: float = 600.0,
        multi_max_concurrent: int = 4,
        long_max_stages: int = 10,
        long_max_total_time_s: float = 900.0,
        long_stage_timeout_s: float = 120.0,
        long_max_concurrent: int = 1,
        resume_from: str | None = None,
        sandbox_backend: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._suite = suite
        self._partitions = [BenchmarkPartition(p.strip()) for p in (partitions or ["development"])]
        self._repeats = max(1, repeats)
        self._seed = seed
        self._inference_settings = InferenceSettings(
            seed=seed,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            max_tokens=max_tokens,
            context_length=context_length,
        )
        self._benchmark_version = benchmark_version or "eb-v0.1"
        self._task_set_version = task_set_version or "tasks-v0.1"
        self._factory = adapter_factory or AdapterFactory()
        self._output_dir = output_dir
        self._baseline_run_id = baseline_run_id
        self._as_baseline = as_baseline
        self._max_tool_calls = max_tool_calls
        self._sandbox_timeout = sandbox_timeout
        self._docker_image = docker_image
        self._multi_max_turns = multi_max_turns
        self._multi_turn_timeout = multi_turn_timeout
        self._multi_max_total_time = multi_max_total_time
        self._multi_max_concurrent = multi_max_concurrent
        self._long_max_stages = long_max_stages
        self._long_max_total_time_s = long_max_total_time_s
        self._long_stage_timeout_s = long_stage_timeout_s
        self._long_max_concurrent = long_max_concurrent
        self._resume_from = resume_from
        self._sandbox_backend = sandbox_backend

    def _create_sandbox_manager(self) -> Any:
        """Create a SandboxManager using the resolved sandbox backend."""
        from ..sandbox.manager import SandboxManager, resolve_sandbox_backend
        backend = self._sandbox_backend or resolve_sandbox_backend()
        return SandboxManager(backend=backend)

    def run(self) -> RunSummary:
        """Execute the full benchmark run and return a summary."""
        import time
        start_time = time.time()

        # 1. Discover paths
        from ..paths import tasks_dir
        task_root = tasks_dir()

        # 2. Load tasks
        from ..tasks.loader import load_tasks_from_dir
        all_tasks = load_tasks_from_dir(task_root)

        # 3. Filter tasks by mode
        single_tasks = [t for t in all_tasks if t.mode == ExecutionMode.SINGLE]
        exec_tasks = [t for t in all_tasks if t.mode == ExecutionMode.EXEC]
        multi_tasks = [t for t in all_tasks if t.mode == ExecutionMode.MULTI]
        long_tasks = [t for t in all_tasks if t.mode == ExecutionMode.LONG]
        non_supported = [
            t for t in all_tasks
            if t.mode not in (ExecutionMode.SINGLE, ExecutionMode.EXEC, ExecutionMode.MULTI, ExecutionMode.LONG)
        ]

        if non_supported:
            modes_found = {t.mode.value for t in non_supported}
            print(f"[eb] WARNING: {len(non_supported)} non-supported task(s) found in suite, skipping: {sorted(modes_found)}")
            print(f"[eb]       Only SINGLE, EXEC, MULTI, and LONG tasks are executed in this stage.")

        # 4. Filter by partition
        filtered_single = [t for t in single_tasks if t.partition in self._partitions]
        filtered_exec = [t for t in exec_tasks if t.partition in self._partitions]
        filtered_multi = [t for t in multi_tasks if t.partition in self._partitions]
        filtered_long = [t for t in long_tasks if t.partition in self._partitions]

        if not filtered_single and not filtered_exec and not filtered_multi and not filtered_long:
            print(f"[eb] WARNING: no tasks found for partitions {self._partitions}")

        tasks_selected = len(filtered_single) + len(filtered_exec) + len(filtered_multi) + len(filtered_long)
        print(f"[eb] Tasks selected: {tasks_selected} (SINGLE={len(filtered_single)}, EXEC={len(filtered_exec)}, MULTI={len(filtered_multi)}, LONG={len(filtered_long)})")

        # 5. Resolve model adapter
        adapter = self._factory.create_adapter(
            self._model_name,
            inference_settings=self._inference_settings,
        )
        meta = adapter.metadata()
        print(f"[eb] Adapter: {meta.adapter_type}/{meta.backend} for model {meta.model_name}")

        # 6. Prepare output directory
        run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        if self._output_dir is None:
            artifact_dir = runs_dir() / run_id
        else:
            artifact_dir = Path(self._output_dir) / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # 7. Create manifest
        from ..sandbox.manager import resolve_sandbox_backend
        resolved_backend = self._sandbox_backend or resolve_sandbox_backend()
        manifest = BenchmarkRunManifest.create(
            run_id=run_id,
            benchmark_version=self._benchmark_version,
            task_set_version=self._task_set_version,
            task_dir=task_root,
            model=ModelMetadata(name=self._model_name, revision="local"),
            base_model=ModelMetadata(name=meta.model_name, revision="local"),
            suite=self._suite,
            partitions=[p.value for p in self._partitions],
            inference=self._inference_settings,
            evaluator_config_version="eb-eval-v1",
            sandbox_backend=resolved_backend,
            sandbox_image=self._docker_image,
            rubric_version="8F.1",
            long_max_concurrent=self._long_max_concurrent,
        )

        # 8. Execute tasks
        single_runner = SingleRunner(adapter)
        exec_runner = RepositoryRunner(
            adapter=adapter,
            dispatcher=single_runner.dispatcher,
            max_tool_calls=self._max_tool_calls,
            max_total_time_s=self._sandbox_timeout,
            docker_image=self._docker_image,
        )
        multi_runner = MultiRunner(
            adapter=adapter,
            dispatcher=single_runner.dispatcher,
            max_turns=self._multi_max_turns,
            turn_timeout_s=self._multi_turn_timeout,
            max_total_time_s=self._multi_max_total_time,
            max_concurrent=self._multi_max_concurrent,
        )
        long_runner = LongHorizonRunner(
            adapter=adapter,
            dispatcher=single_runner.dispatcher,
            max_stages=self._long_max_stages,
            max_total_time_s=self._long_max_total_time_s,
            stage_timeout_s=self._long_stage_timeout_s,
            docker_image=self._docker_image,
            max_concurrent=self._long_max_concurrent,
            sandbox_manager=self._create_sandbox_manager(),
        )
        all_results: list[Any] = []
        raw_scoring = RunRawScores(run_id=run_id)
        successes = 0
        failures = 0
        errors = 0
        skipped = 0

        for repeat_idx in range(self._repeats):
            repeat_label = f"[repeat {repeat_idx + 1}/{self._repeats}]"
            print(f"[eb] {repeat_label} Running {tasks_selected} task(s)...")

            for task in filtered_single:
                ctx = RunContext(
                    run_id=run_id,
                    model_name=self._model_name,
                    suite=self._suite,
                    inference_settings={
                        "seed": self._inference_settings.seed,
                        "temperature": self._inference_settings.temperature,
                        "top_p": self._inference_settings.top_p,
                        "top_k": self._inference_settings.top_k,
                        "max_tokens": self._inference_settings.max_tokens,
                    },
                    repeat_index=repeat_idx,
                )
                result = single_runner.run(task, ctx)
                all_results.append(result)
                raw_scoring.add_task_result(result, task.capabilities)
                status = result.execution_metadata.get("status", "UNKNOWN")
                if status == TaskStatus.SUCCESS.value:
                    successes += 1
                elif status == TaskStatus.ERROR.value:
                    errors += 1
                elif status == TaskStatus.FAILED.value:
                    failures += 1
                elif status == TaskStatus.SKIPPED.value:
                    skipped += 1
                eval_status = "no_eval"
                if result.evaluator_results:
                    statuses = [e.status.value for e in result.evaluator_results]
                    eval_status = ",".join(set(statuses))
                print(f"  {task.id}: {status}" + (f" eval=[{eval_status}]" if eval_status != "no_eval" else "") + (f" ({result.flags[0][:60]})" if result.flags else ""))

            for task in filtered_exec:
                ctx = RunContext(
                    run_id=run_id,
                    model_name=self._model_name,
                    suite=self._suite,
                    inference_settings={
                        "seed": self._inference_settings.seed,
                        "temperature": self._inference_settings.temperature,
                        "top_p": self._inference_settings.top_p,
                        "top_k": self._inference_settings.top_k,
                        "max_tokens": self._inference_settings.max_tokens,
                    },
                    repeat_index=repeat_idx,
                )
                result = exec_runner.run(task, ctx)
                all_results.append(result)
                raw_scoring.add_task_result(result, task.capabilities)
                status = result.execution_metadata.get("status", "UNKNOWN")
                if status == TaskStatus.SUCCESS.value:
                    successes += 1
                elif status == TaskStatus.ERROR.value:
                    errors += 1
                elif status == TaskStatus.FAILED.value:
                    failures += 1
                elif status == TaskStatus.SKIPPED.value:
                    skipped += 1
                test_info = result.execution_metadata.get("test_summary", {})
                extra = f" tests={test_info.get('test_count', '?')}" if test_info else ""
                exec_eval_status = "no_eval"
                if result.evaluator_results:
                    exec_statuses = [e.status.value for e in result.evaluator_results]
                    exec_eval_status = ",".join(set(exec_statuses))
                print(f"  {task.id}: {status}{extra}" + (f" eval=[{exec_eval_status}]" if exec_eval_status != "no_eval" else "") + (f" ({result.flags[0][:60]})" if result.flags else ""))

            if filtered_multi:
                multi_ctx = RunContext(
                    run_id=run_id,
                    model_name=self._model_name,
                    suite=self._suite,
                    inference_settings={
                        "seed": self._inference_settings.seed,
                        "temperature": self._inference_settings.temperature,
                        "top_p": self._inference_settings.top_p,
                        "top_k": self._inference_settings.top_k,
                        "max_tokens": self._inference_settings.max_tokens,
                    },
                    repeat_index=repeat_idx,
                )
                multi_results = multi_runner.run_batch(filtered_multi, multi_ctx)
                for result in multi_results:
                    all_results.append(result)
                    task = next(t for t in filtered_multi if t.id == result.task_id)
                    raw_scoring.add_task_result(result, task.capabilities)
                    status = result.execution_metadata.get("status", "UNKNOWN")
                    if status == TaskStatus.SUCCESS.value:
                        successes += 1
                    elif status == TaskStatus.ERROR.value:
                        errors += 1
                    elif status == TaskStatus.FAILED.value:
                        failures += 1
                    elif status == TaskStatus.SKIPPED.value:
                        skipped += 1
                    turn_count = result.execution_metadata.get("turn_count", "?")
                    multi_eval_status = "no_eval"
                    if result.evaluator_results:
                        m_statuses = [e.status.value for e in result.evaluator_results]
                        multi_eval_status = ",".join(set(m_statuses))
                    print(f"  {result.task_id}: {status} turns={turn_count}" + (f" eval=[{multi_eval_status}]" if multi_eval_status != "no_eval" else "") + (f" ({result.flags[0][:60]})" if result.flags else ""))

            if filtered_long:
                long_ctx = RunContext(
                    run_id=run_id,
                    model_name=self._model_name,
                    suite=self._suite,
                    inference_settings={
                        "seed": self._inference_settings.seed,
                        "temperature": self._inference_settings.temperature,
                        "top_p": self._inference_settings.top_p,
                        "top_k": self._inference_settings.top_k,
                        "max_tokens": self._inference_settings.max_tokens,
                    },
                    repeat_index=repeat_idx,
                )
                for task in filtered_long:
                    try:
                        result = long_runner.run(task, long_ctx, resume_from=self._resume_from)
                    except Exception as e:
                        result = TaskResult(
                            task_id=task.id,
                            run_id=run_id,
                            raw_response=None,
                            flags=[f"runner_error: {type(e).__name__}: {e}"],
                            execution_metadata={
                                "status": TaskStatus.ERROR.value,
                                "repeat_id": f"r{repeat_idx + 1:02d}",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                    all_results.append(result)
                    raw_scoring.add_task_result(result, task.capabilities)
                    status = result.execution_metadata.get("status", "UNKNOWN")
                    if status == TaskStatus.SUCCESS.value:
                        successes += 1
                    elif status == TaskStatus.ERROR.value:
                        errors += 1
                    elif status == TaskStatus.FAILED.value:
                        failures += 1
                    elif status == TaskStatus.SKIPPED.value:
                        skipped += 1
                    stage_count = result.execution_metadata.get("stage_count", "?")
                    long_eval_status = "no_eval"
                    if result.evaluator_results:
                        l_statuses = [e.status.value for e in result.evaluator_results]
                        long_eval_status = ",".join(set(l_statuses))
                    print(f"  {result.task_id}: {status} stages={stage_count}" + (f" eval=[{long_eval_status}]" if long_eval_status != "no_eval" else "") + (f" ({result.flags[0][:60]})" if result.flags else ""))

        elapsed = time.time() - start_time

        # Compute raw score aggregation
        raw_scoring.compute()

        # 9. Write artifacts
        self._write_artifacts(
            artifact_dir=artifact_dir,
            manifest=manifest,
            results=all_results,
            raw_scoring=raw_scoring,
            run_id=run_id,
        )

        # 10. Update registry
        env_info = EnvironmentInfo(
            hardware=manifest.environment.get("gpu_name"),
            torch_version=manifest.environment.get("torch_version"),
            python_version=manifest.environment.get("python_version"),
        )
        benchmark_run = BenchmarkRun(
            run_id=run_id,
            benchmark_version=self._benchmark_version,
            task_set_version=self._task_set_version,
            model=ModelMetadata(name=self._model_name, revision="local"),
            base_model=ModelMetadata(name=meta.model_name, revision="local"),
            baseline_run_id=self._baseline_run_id,
            suite=self._suite,
            partitions=self._partitions,
            inference=self._inference_settings,
            environment=env_info,
            task_results=all_results,
            task_set_hash=manifest.task_set_manifest.records_sha256,
        )
        registry = BenchmarkRegistry()
        registry.create_run(benchmark_run)

        # 11. Baseline registration or EB scoring
        if self._as_baseline:
            from ..scoring.eb_score import SCORING_VERSION
            bl = BaselineRecord(
                base_model_name=meta.model_name,
                base_model_revision="local",
                benchmark_version=self._benchmark_version,
                task_set_version=self._task_set_version,
                baseline_run_id=run_id,
                suite=self._suite,
                scoring_version=SCORING_VERSION,
            )
            # Compute raw EB scores from run for baseline
            raw_means = []
            for tr in all_results:
                if tr.raw_task_score is not None:
                    raw_means.append(tr.raw_task_score)
            if raw_means:
                eb_ref = round(1000 * (sum(raw_means) / len(raw_means)))
                bl.run_scores = [eb_ref] * self._repeats
            bl.compute_stats()
            registry.set_baseline(bl, as_registered=True)
            benchmark_run.run_status = "BASELINE_REGISTERED"
            print(f"\n[eb] Baseline registered: {run_id} for {meta.model_name}")
            print(f"  EB reference score: {bl.eb_score}")
        else:
            # Try to resolve and compute EB Score
            resolved = registry.resolve_baseline_for_run(benchmark_run)
            if resolved is not None:
                raw_means = []
                for tr in all_results:
                    if tr.raw_task_score is not None:
                        raw_means.append(tr.raw_task_score)
                if raw_means:
                    model_raw_mean = sum(raw_means) / len(raw_means)
                    base_raw_ref = float(resolved.mean) / 1000.0 if resolved.eb_score == 1000 and resolved.mean else float(resolved.mean or 1.0)
                    score_result = compute_eb_score(
                        model_raw_mean=model_raw_mean,
                        base_raw_mean=base_raw_ref,
                        baseline_run_id=resolved.baseline_run_id,
                        benchmark_version=self._benchmark_version,
                        task_set_version=self._task_set_version,
                        model_name=self._model_name,
                        base_model_name=resolved.base_model_name,
                    )
                    if isinstance(score_result, EbScoreResult):
                        benchmark_run.overall_eb_score = score_result.eb_score
                        benchmark_run.run_status = "BENCHMARK_COMPLETE"
                        benchmark_run.run_stats = RepeatedRunStats(
                            scores=[score_result.eb_score],
                        )
                        benchmark_run.run_stats.compute()
                        print(f"\n[eb] EB Score: {score_result.eb_score} (improvement: {score_result.improvement_percent:+.1f}%)")
                    else:
                        benchmark_run.run_status = "NOT_NORMALIZED"
                        print(f"\n[eb] WARNING: EB Score computation failed: {score_result.reason}")
                else:
                    benchmark_run.run_status = "RAW_COMPLETE"
            else:
                benchmark_run.run_status = "RAW_COMPLETE"
                print("\n[eb] No compatible baseline found. Run status: RAW_COMPLETE")

        registry.create_run(benchmark_run)  # Save updated run

        # 11. Close adapter
        adapter.close()

        summary = RunSummary(
            run_id=run_id,
            model=self._model_name,
            suite=self._suite,
            tasks_selected=tasks_selected,
            tasks_executed=sum(1 for r in all_results if r.execution_metadata.get("status") in (TaskStatus.SUCCESS.value, TaskStatus.FAILED.value)),
            successes=successes,
            failures=failures,
            errors=errors,
            skipped=skipped,
            elapsed_s=elapsed,
            artifact_dir=artifact_dir,
        )
        summary.print()
        return summary

    def _write_artifacts(
        self,
        artifact_dir: Path,
        manifest: BenchmarkRunManifest,
        results: list[Any],
        raw_scoring: RunRawScores,
        run_id: str,
    ) -> None:
        """Write run artifacts to disk."""
        # manifest.json
        manifest_path = artifact_dir / "manifest.json"
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest.to_dict(), f, indent=2, ensure_ascii=False)

        # results.jsonl — one JSON object per line
        results_path = artifact_dir / "results.jsonl"
        with results_path.open("w", encoding="utf-8") as f:
            for result in results:
                f.write(json.dumps(result.model_dump(), ensure_ascii=False) + "\n")

        # run.json — summary metadata
        run_info = {
            "run_id": run_id,
            "model": self._model_name,
            "suite": self._suite,
            "benchmark_version": self._benchmark_version,
            "task_set_version": self._task_set_version,
            "partitions": [p.value for p in self._partitions],
            "repeats": self._repeats,
            "inference_settings": self._inference_settings.model_dump(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "artifact_dir": str(artifact_dir),
            "manifest_sha256": manifest.manifest_sha256,
            "schema_version": "8F.1",
            "reproducibility": {
                "evaluator_config_version": manifest.evaluator_config_version,
                "sandbox_backend": manifest.sandbox_backend,
                "sandbox_image": manifest.sandbox_image,
                "rubric_version": manifest.rubric_version,
                "long_max_concurrent": manifest.long_max_concurrent,
            },
        }
        run_path = artifact_dir / "run.json"
        with run_path.open("w", encoding="utf-8") as f:
            json.dump(run_info, f, indent=2, ensure_ascii=False)

        # raw_scores.json — raw score aggregation (Stage 3)
        raw_path = artifact_dir / "raw_scores.json"
        raw_data = self._serialize_raw_scoring(raw_scoring)
        with raw_path.open("w", encoding="utf-8") as f:
            json.dump(raw_data, f, indent=2, ensure_ascii=False)

    def _serialize_raw_scoring(self, raw_scoring: RunRawScores) -> dict:
        """Serialize RunRawScores to a JSON-serializable dict."""
        task_scores = {}
        for tid, ts in raw_scoring.task_scores.items():
            task_scores[tid] = {
                "task_id": ts.task_id,
                "repeat_scores": ts.repeat_scores,
                "repeat_statuses": ts.repeat_statuses,
                "raw_mean": ts.raw_mean,
                "raw_median": ts.raw_median,
                "raw_stddev": ts.raw_stddev,
                "raw_min": ts.raw_min,
                "raw_max": ts.raw_max,
                "raw_error_percent": ts.raw_error_percent,
                "task_count": ts.task_count,
                "error_count": ts.error_count,
            }

        capability_scores = {}
        for cap_key, cs in raw_scoring.capability_scores.items():
            capability_scores[cap_key] = {
                "capability": cs.capability.value,
                "raw_mean": cs.raw_mean,
                "raw_median": cs.raw_median,
                "raw_stddev": cs.raw_stddev,
                "raw_min": cs.raw_min,
                "raw_max": cs.raw_max,
                "raw_error_percent": cs.raw_error_percent,
                "task_count": cs.task_count,
                "error_count": cs.error_count,
            }

        return {
            "run_id": raw_scoring.run_id,
            "overall_raw_mean": raw_scoring.overall_raw_mean,
            "overall_task_count": raw_scoring.overall_task_count,
            "overall_error_count": raw_scoring.overall_error_count,
            "overall_applicable_count": raw_scoring.overall_applicable_count,
            "task_scores": task_scores,
            "capability_scores": capability_scores,
        }
