#!/usr/bin/env python3
"""
long_horizon.py — LONG-specific evaluator for the EffNine Benchmark (EB).

Evaluates multi-stage engineering workflows by checking:
  1. Stage-level correctness (did each stage produce valid output?)
  2. Repository state artifacts (do expected files/changes exist?)
  3. Final delivery criteria (did the overall task succeed?)
  4. Requirement change adaptation (if applicable)

Scoring model (Stage 8B.2):
  - SCORE: continuous quality measure (0.0–1.0) based on progress + terminal quality
  - OUTCOME: categorical gate-based decision (PASS / PARTIAL / FAIL / NOT_APPLICABLE)
  - Gates are explicit and independent of score thresholds

Gate rules:
  - FAIL: terminal stage failed (FAILED/TIMEOUT), or no stages executed
  - PASS: all stages SUCCESS, all requirement changes adapted, delivery criteria met
  - PARTIAL: meaningful progress but one or more non-terminal gates failed
  - NOT_APPLICABLE: no stage results available

Score formula:
  base = progress_score * 0.7 + terminal_score * 0.3
  if error_stages: base *= 0.5
  if delivery_criteria: base = base * 0.7 + delivery_score * 0.3
  if requirement_changes: base = base * 0.8 + req_change_score * 0.2
  score = clamp(base, 0.0, 1.0)
"""

from __future__ import annotations

from typing import Any

from ..core.schema import EvaluatorResult, StageData, StageResult, Task, TaskResult
from ..core.types import EvaluatorStatus, JudgeMode
from .base import Evaluator


# ---------------------------------------------------------------------------
# LONG evaluator
# ---------------------------------------------------------------------------


class LongHorizonEvaluator(Evaluator):
    """
    Evaluates a completed LONG task execution.

    Separates SCORE (continuous quality) from OUTCOME (gate-based decision).

    SCORE is a weighted combination of stage progress and terminal quality,
    with modifiers for errors, delivery criteria, and requirement changes.

    OUTCOME is determined by explicit gates:
      - FAIL: terminal stage failed
      - PASS: all stages pass, all gates satisfied
      - PARTIAL: progress made but some gates failed
      - NOT_APPLICABLE: no stage results
    """

    @property
    def name(self) -> str:
        return "long_horizon"

    @property
    def authority_level(self) -> int:
        return 1  # Deterministic evidence

    @property
    def supported_modes(self) -> list[JudgeMode]:
        return [JudgeMode.DETERMINISTIC]

    def is_applicable(self, task: Task) -> bool:
        """Applicable only for LONG mode tasks."""
        return task.mode.value == "LONG" if hasattr(task.mode, 'value') else False

    def evaluate(self, task: Task, result: TaskResult) -> EvaluatorResult:
        """
        Evaluate a LONG task result with separated score and outcome.

        Returns:
          - NOT_APPLICABLE if no stage results
          - FAIL with score 0.0 if terminal stage failed
          - PARTIAL with score if gates partially satisfied
          - PASS with score if all gates satisfied
        """
        stage_results = result.stage_results
        stages = result.stages or self._extract_stages_from_task(task)

        if not stage_results:
            return EvaluatorResult(
                evaluator="long_horizon",
                mode=JudgeMode.DETERMINISTIC,
                status=EvaluatorStatus.NOT_APPLICABLE,
                rationale="No stage results available for LONG evaluation",
                flags=["no_stage_results"],
            )

        # Compute score (continuous quality measure)
        score = self._compute_score(stage_results, stages, task, result)

        # Determine outcome via explicit gates
        outcome = self._determine_outcome(stage_results, stages, task, result)

        # Build diagnostic info
        terminal_failed = self._check_terminal_failure(stage_results, stages)
        error_stages = [sr for sr in stage_results if sr.status == "ERROR"]
        failed_stages = [sr for sr in stage_results if sr.status == "FAILED"]

        # Update TaskResult with outcome
        if outcome in (EvaluatorStatus.PASS.value, EvaluatorStatus.PARTIAL.value, EvaluatorStatus.FAIL.value):
            result.long_outcome = outcome
            result.raw_task_score = score

        # Gate flags
        gates_triggered = self._detect_gates(stage_results, stages, task, result)

        # Build details dict
        details = {
            "stage_count": len(stage_results),
            "completed_stages": sum(
                1 for sr in stage_results if sr.status == "SUCCESS"
            ),
            "failed_stages": sum(
                1 for sr in stage_results if sr.status == "FAILED"
            ),
            "error_stages": len(error_stages),
            "outcome": outcome,
            "gates_triggered": gates_triggered,
        }

        # Stage 8E.1: Gated judge invocation for QUALITY scoring
        quality_score, quality_result = self._try_judge_evaluation(task, result, stage_results, stages)
        if quality_score is not None:
            details["quality_score"] = quality_score
            details["quality_evaluator"] = quality_result.model_dump() if quality_result else None

        return EvaluatorResult(
            evaluator="long_horizon",
            mode=JudgeMode.DETERMINISTIC,
            status=outcome,
            score=round(score, 4),
            max_score=1.0,
            normalized_score=round(score, 4),
            rationale=self._build_rationale(
                stage_results, score, terminal_failed, outcome, gates_triggered
            ),
            evidence=self._build_evidence(stage_results, score, terminal_failed),
            flags=gates_triggered,
            details=details,
        )

    # -----------------------------------------------------------------------
    # Score computation
    # -----------------------------------------------------------------------

    def _compute_score(
        self,
        stage_results: list[StageResult],
        stages: list[StageData],
        task: Task,
        result: TaskResult,
    ) -> float:
        """
        Compute continuous quality score (0.0–1.0).

        Formula:
          base = progress_score * 0.7 + terminal_score * 0.3
          if error_stages: base *= 0.5
          if delivery_criteria: base = base * 0.7 + delivery_score * 0.3
          if requirement_changes: base = base * 0.8 + req_change_score * 0.2
          score = clamp(base, 0.0, 1.0)
        """
        # Terminal failure → score is 0
        terminal_failed = self._check_terminal_failure(stage_results, stages)
        if terminal_failed:
            return 0.0

        progress_score = self._compute_progress_score(stage_results)
        terminal_score = self._compute_terminal_score(stage_results, stages)

        # Base formula: weighted combination of progress and terminal quality
        terminal_weight = 0.3
        base = progress_score * (1 - terminal_weight) + terminal_score * terminal_weight

        # Error penalty: 50% reduction for adapter/sandbox errors
        error_stages = [sr for sr in stage_results if sr.status == "ERROR"]
        if error_stages:
            base *= 0.5

        # Delivery criteria modifier
        delivery_score = self._check_delivery_criteria(task, result)
        if delivery_score is not None:
            base = base * 0.7 + delivery_score * 0.3

        # Requirement change adaptation modifier
        req_change_score = self._check_requirement_changes(task, stage_results)
        if req_change_score is not None:
            base = base * 0.8 + req_change_score * 0.2

        # Clamp to canonical range
        return max(0.0, min(1.0, round(base, 4)))

    def _compute_progress_score(self, stage_results: list[StageResult]) -> float:
        """Fraction of stages that completed successfully."""
        if not stage_results:
            return 0.0
        completed = sum(1 for sr in stage_results if sr.status == "SUCCESS")
        return completed / len(stage_results)

    def _compute_terminal_score(
        self, stage_results: list[StageResult], stages: list[StageData]
    ) -> float:
        """Score from the final/completed stage."""
        if not stage_results:
            return 0.0
        last = stage_results[-1]
        if last.score is not None:
            return last.score
        if last.status == "SUCCESS":
            return 1.0
        return 0.0

    # -----------------------------------------------------------------------
    # Outcome determination (gate-based)
    # -----------------------------------------------------------------------

    def _determine_outcome(
        self,
        stage_results: list[StageResult],
        stages: list[StageData],
        task: Task,
        result: TaskResult,
    ) -> str:
        """
        Determine outcome via explicit gates, not score threshold.

        FAIL gates (in priority order):
          1. Terminal stage failed (FAILED/TIMEOUT)
          2. Any stage has ERROR status (adapter/sandbox failure)

        PASS gates (all must pass):
          1. All stages have SUCCESS status
          2. All requirement changes were adapted (next stage succeeded)
          3. All delivery criteria are met (if delivery_criteria exists)

        PARTIAL: meaningful progress but one or more non-terminal gates failed
        NOT_APPLICABLE: no stage results (handled before this method)
        """
        # Check terminal failure (hard FAIL gate)
        terminal_failed = self._check_terminal_failure(stage_results, stages)
        if terminal_failed:
            return EvaluatorStatus.FAIL.value

        # Check for adapter/sandbox errors (hard FAIL gate)
        error_stages = [sr for sr in stage_results if sr.status == "ERROR"]
        if error_stages:
            return EvaluatorStatus.FAIL.value

        # Check if all stages succeeded
        all_success = all(sr.status == "SUCCESS" for sr in stage_results)

        # Check requirement change adaptation
        req_change_score = self._check_requirement_changes(task, stage_results)
        req_changes_present = req_change_score is not None
        req_changes_satisfied = req_change_score == 1.0 if req_changes_present else True

        # Check delivery criteria
        delivery_score = self._check_delivery_criteria(task, result)
        delivery_present = delivery_score is not None
        delivery_satisfied = delivery_score == 1.0 if delivery_present else True

        # All gates pass → PASS
        if all_success and req_changes_satisfied and delivery_satisfied:
            return EvaluatorStatus.PASS.value

        # Some progress but gates not fully satisfied → PARTIAL
        return EvaluatorStatus.PARTIAL.value

    def _detect_gates(
        self,
        stage_results: list[StageResult],
        stages: list[StageData],
        task: Task,
        result: TaskResult,
    ) -> list[str]:
        """Detect which gates were triggered for diagnostic reporting."""
        flags = []

        terminal_failed = self._check_terminal_failure(stage_results, stages)
        if terminal_failed:
            flags.append(f"terminal_failure:{terminal_failed}")

        error_stages = [sr for sr in stage_results if sr.status == "ERROR"]
        for es in error_stages:
            flags.append(f"stage_error:{es.stage_id}")

        failed_stages = [sr for sr in stage_results if sr.status == "FAILED"]
        for fs in failed_stages:
            flags.append(f"stage_failed:{fs.stage_id}")

        # Check requirement change gates
        req_change_score = self._check_requirement_changes(task, stage_results)
        if req_change_score is not None and req_change_score < 1.0:
            flags.append(f"requirement_change_not_fully_adapted:{req_change_score:.2f}")

        # Check delivery gates
        delivery_score = self._check_delivery_criteria(task, result)
        if delivery_score is not None and delivery_score < 1.0:
            flags.append(f"delivery_criteria_not_met:{delivery_score:.2f}")

        return flags

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _try_judge_evaluation(
        self,
        task: Task,
        result: TaskResult,
        stage_results: list[StageResult],
        stages: list[StageData],
    ) -> tuple[float | None, Any | None]:
        """
        Attempt judge evaluation for LONG tasks gated by deterministic outcome.

        Returns (quality_score, quality_result) or (None, None) if skipped.
        Judge is only invoked when long_outcome is PASS or PARTIAL.
        Falls back gracefully when judge client is unavailable.
        """
        long_outcome = getattr(result, "long_outcome", None)

        # Skip judge for FAIL and NOT_APPLICABLE (deterministic gate)
        if long_outcome in (EvaluatorStatus.FAIL.value, EvaluatorStatus.NOT_APPLICABLE.value):
            return None, None

        # Try to invoke judge; fall back gracefully if unavailable
        try:
            from .judge import JudgeEvaluator
            judge_eval = JudgeEvaluator()
            return judge_eval.evaluate_long_judge(task, result, stage_results, stages)
        except ValueError:
            # Judge client unavailable (no env vars) — skip gracefully
            return None, None
        except Exception:
            # Any other error — skip gracefully, deterministic result stands
            return None, None

    def _extract_stages_from_task(self, task: Task) -> list[StageData]:
        """Extract stage definitions from task context."""
        stages_data = task.context.get("stages", [])
        stages = []
        for sd in stages_data:
            if isinstance(sd, StageData):
                stages.append(sd)
            elif isinstance(sd, dict):
                try:
                    stages.append(StageData.model_validate(sd))
                except Exception:
                    continue
        return stages

    def _check_terminal_failure(
        self, stage_results: list[StageResult], stages: list[StageData]
    ) -> str | None:
        """Check if any terminal stage failed. Returns stage_id or None."""
        terminal_ids = {s.id for s in stages if s.terminal}
        if not terminal_ids:
            # No explicit terminal — check last stage
            if stage_results:
                last = stage_results[-1]
                if last.status in ("FAILED", "TIMEOUT"):
                    return last.stage_id
            return None

        for sr in stage_results:
            if sr.stage_id in terminal_ids and sr.status in ("FAILED", "TIMEOUT"):
                return sr.stage_id
        return None

    def _check_delivery_criteria(
        self, task: Task, result: TaskResult
    ) -> float | None:
        """Check final delivery criteria from task context. Returns score or None."""
        ctx = task.context
        delivery = ctx.get("delivery_criteria")
        if not delivery:
            return None

        checks = delivery.get("checks", [])
        if not checks:
            return None

        passed = 0
        total = len(checks)
        response = result.raw_response or ""

        for check in checks:
            check_type = check.get("type", "")
            value = check.get("value", "")
            if check_type == "contains":
                if value.lower() in (response or "").lower():
                    passed += 1
            elif check_type == "regex":
                import re
                if re.search(value, response or "", re.IGNORECASE):
                    passed += 1
            elif check_type == "file_exists":
                changed = result.changed_files or []
                if value in changed:
                    passed += 1

        if total == 0:
            return None
        return passed / total

    def _check_requirement_changes(
        self, task: Task, stage_results: list[StageResult]
    ) -> float | None:
        """Check if requirement changes were properly handled. Returns score or None."""
        stages = task.context.get("stages", [])
        changes = []
        for sd in stages:
            if isinstance(sd, dict):
                rc = sd.get("requirement_change")
            elif hasattr(sd, "requirement_change"):
                rc = sd.requirement_change
            else:
                rc = None
            if rc:
                changes.append(rc)

        if not changes:
            return None

        # For each requirement change, check if the NEXT stage adapted
        adapted = 0
        for i, change in enumerate(changes):
            next_stage_idx = i + 1
            if next_stage_idx < len(stage_results):
                next_sr = stage_results[next_stage_idx]
                if next_sr.status == "SUCCESS":
                    adapted += 1

        return adapted / len(changes) if changes else None

    def _build_rationale(
        self,
        stage_results: list[StageResult],
        score: float,
        terminal_failed: str | None,
        outcome: str,
        gates_triggered: list[str],
    ) -> str:
        """Build human-readable rationale."""
        completed = sum(1 for sr in stage_results if sr.status == "SUCCESS")
        failed = sum(1 for sr in stage_results if sr.status in ("FAILED", "TIMEOUT"))
        errors = sum(1 for sr in stage_results if sr.status == "ERROR")

        parts = [
            f"outcome={outcome}",
            f"score={score:.3f}",
            f"{completed}/{len(stage_results)} stages completed",
        ]
        if terminal_failed:
            parts.append(f"terminal_stage={terminal_failed}_failed")
        if failed:
            parts.append(f"{failed}_stages_failed")
        if errors:
            parts.append(f"{errors}_stages_error")
        if gates_triggered:
            parts.append(f"gates: {', '.join(gates_triggered)}")

        return "; ".join(parts)

    def _build_evidence(
        self,
        stage_results: list[StageResult],
        score: float,
        terminal_failed: str | None = None,
    ) -> list[str]:
        """Build evidence list."""
        evidence = []
        for sr in stage_results:
            evidence.append(f"stage_{sr.stage_id}={sr.status}")
            if sr.score is not None:
                evidence.append(f"stage_{sr.stage_id}_score={sr.score:.3f}")
        evidence.append(f"final_score={score:.3f}")
        if terminal_failed:
            evidence.append("terminal_stage_failed")
        return evidence
