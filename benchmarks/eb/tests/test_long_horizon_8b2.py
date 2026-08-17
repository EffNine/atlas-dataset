"""Tests for Stage 8B.2 — LONG scoring outcome semantics (score vs outcome separation)."""
import pytest
from unittest.mock import MagicMock

from eb.core.schema import StageData, StageResult, Task, TaskResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition, EvaluatorStatus
from eb.evaluators.long_horizon import LongHorizonEvaluator


def _make_task(stages: list[dict], **overrides) -> Task:
    defaults = {
        "id": "EB-CAL-001",
        "category": "engineering",
        "mode": ExecutionMode.LONG,
        "difficulty": Difficulty.L3,
        "capabilities": [Capability.ADVISORY],
        "prompt": "Calibration task",
        "partition": BenchmarkPartition.DEVELOPMENT,
        "context": {"stages": stages},
    }
    defaults.update(overrides)
    return Task.model_validate(defaults)


def _make_result(stage_statuses: list[tuple], scores: list[float | None] = None) -> TaskResult:
    if scores is None:
        scores = [1.0] * len(stage_statuses)
    sr_list = []
    for i, (sid, status) in enumerate(stage_statuses):
        sr = StageResult(stage_id=sid, stage_name=f"S{i}", status=status, score=scores[i])
        sr_list.append(sr)
    return TaskResult(task_id="EB-CAL-001", run_id="r1", stage_results=sr_list)


class TestOutcomeSemantics:
    """Test that outcome (PASS/PARTIAL/FAIL) is determined by gates, not score threshold."""

    def setup_method(self):
        self.evaluator = LongHorizonEvaluator()

    def test_all_success_passes(self):
        """All stages SUCCESS → PASS."""
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.PASS
        assert ev.score == pytest.approx(1.0, abs=0.01)

    def test_terminal_failure_fails(self):
        """Terminal stage FAILED → FAIL, score=0."""
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = _make_result([("s1", "SUCCESS"), ("s2", "FAILED")])
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.FAIL
        assert ev.score == 0.0

    def test_implicit_terminal_failure_fails(self):
        """Last stage TIMEOUT with no explicit terminal flag → FAIL."""
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2"},
        ])
        result = _make_result([("s1", "SUCCESS"), ("s2", "TIMEOUT")])
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.FAIL
        assert ev.score == 0.0

    def test_early_stage_fail_is_partial(self):
        """First stage FAILED, terminal SUCCESS → PARTIAL (not PASS, not FAIL)."""
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = _make_result([("s1", "FAILED"), ("s2", "SUCCESS")])
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.PARTIAL
        assert ev.score == pytest.approx(0.65, abs=0.01)

    def test_middle_stage_fail_is_partial(self):
        """Middle stage FAILED, terminal SUCCESS → PARTIAL."""
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2"},
            {"id": "s3", "name": "S3", "prompt": "P3", "terminal": True},
        ])
        result = _make_result([("s1", "SUCCESS"), ("s2", "FAILED"), ("s3", "SUCCESS")])
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.PARTIAL
        assert ev.score == pytest.approx(0.7667, abs=0.01)

    def test_adapter_error_is_fail(self):
        """Any ERROR status → FAIL (hard gate)."""
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = TaskResult(
            task_id="EB-CAL-001", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="ERROR", error="boom"),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
            ],
        )
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.FAIL
        assert ev.score == pytest.approx(0.325, abs=0.01)

    def test_empty_stages_not_applicable(self):
        """No stages → NOT_APPLICABLE."""
        task = _make_task([])
        result = TaskResult(task_id="EB-CAL-001", run_id="r1", stage_results=[])
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.NOT_APPLICABLE
        assert ev.score is None

    def test_no_stage_results_not_applicable(self):
        """No stage results but task has stages → NOT_APPLICABLE."""
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
        ])
        result = TaskResult(task_id="EB-CAL-001", run_id="r1", stage_results=[])
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.NOT_APPLICABLE


class TestDeliveryCriteriaGates:
    """Delivery criteria act as gates on outcome."""

    def setup_method(self):
        self.evaluator = LongHorizonEvaluator()

    def test_delivery_met_all_pass(self):
        """All stages pass + delivery criteria met → PASS."""
        task = _make_task(
            stages=[
                {"id": "s1", "name": "S1", "prompt": "P1"},
                {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
            ],
            context={"delivery_criteria": {"checks": [{"type": "contains", "value": "passed"}]}},
        )
        result = TaskResult(
            task_id="EB-CAL-001", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
            ],
            raw_response="All tests passed successfully",
        )
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.PASS

    def test_delivery_unmet_all_stages_pass(self):
        """All stages pass but delivery criteria unmet → PARTIAL."""
        task = _make_task(
            stages=[
                {"id": "s1", "name": "S1", "prompt": "P1"},
                {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
            ],
            context={"delivery_criteria": {"checks": [{"type": "contains", "value": "delivered"}]}},
        )
        result = TaskResult(
            task_id="EB-CAL-001", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
            ],
            raw_response="Implementation complete but no delivery confirmation",
        )
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.PARTIAL
        assert "delivery_criteria_not_met" in str(ev.flags)

    def test_partial_delivery_still_partial(self):
        """Partial delivery criteria match → PARTIAL."""
        task = _make_task(
            stages=[
                {"id": "s1", "name": "S1", "prompt": "P1"},
                {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
            ],
            context={"delivery_criteria": {"checks": [
                {"type": "contains", "value": "passed"},
                {"type": "contains", "value": "delivered"},
            ]}},
        )
        result = TaskResult(
            task_id="EB-CAL-001", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
            ],
            raw_response="Tests passed",
        )
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.PARTIAL


class TestRequirementChangeGates:
    """Requirement change adaptation acts as a gate on outcome."""

    def setup_method(self):
        self.evaluator = LongHorizonEvaluator()

    def test_req_change_adapted_all_pass(self):
        """All stages pass + requirement change adapted → PASS."""
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "requirement_change": {"from": "a", "to": "b"}},
            {"id": "s3", "name": "S3", "prompt": "P3", "terminal": True},
        ])
        result = TaskResult(
            task_id="EB-CAL-001", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
                StageResult(stage_id="s3", stage_name="S3", status="SUCCESS", score=1.0),
            ],
        )
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.PASS

    def test_req_change_not_adapted_is_partial(self):
        """All stages SUCCESS but requirement change not adapted → PARTIAL."""
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "requirement_change": {"from": "a", "to": "b"}},
            {"id": "s3", "name": "S3", "prompt": "P3", "terminal": True},
        ])
        result = TaskResult(
            task_id="EB-CAL-001", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="FAILED", score=0.0),
                StageResult(stage_id="s3", stage_name="S3", status="SUCCESS", score=1.0),
            ],
        )
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.PARTIAL
        assert "requirement_change_not_fully_adapted" in str(ev.flags)


class TestScoreBounds:
    """Verify score stays within canonical [0.0, 1.0] range."""

    def setup_method(self):
        self.evaluator = LongHorizonEvaluator()

    def setup_method(self):
        self.evaluator = LongHorizonEvaluator()

    def test_score_non_negative(self):
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = _make_result([("s1", "FAILED"), ("s2", "FAILED")])
        ev = self.evaluator.evaluate(task, result)
        assert ev.score >= 0.0

    def test_score_not_above_one(self):
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
        ev = self.evaluator.evaluate(task, result)
        assert ev.score <= 1.0

    def test_low_quality_all_success_still_pass(self):
        """All stages SUCCESS with low scores → PASS (gates pass, score reflects quality)."""
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = TaskResult(
            task_id="EB-CAL-001", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=0.1),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=0.2),
            ],
        )
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.PASS
        assert ev.score == pytest.approx(0.76, abs=0.01)

    def test_high_quality_all_success(self):
        """All stages SUCCESS with high scores → PASS."""
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = TaskResult(
            task_id="EB-CAL-001", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=0.9),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=0.95),
            ],
        )
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.PASS
        assert ev.score == pytest.approx(0.985, abs=0.01)


class TestLongOutcomeField:
    """Test that long_outcome is set on TaskResult."""

    def setup_method(self):
        self.evaluator = LongHorizonEvaluator()

    def test_long_outcome_set_on_pass(self):
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
        self.evaluator.evaluate(task, result)
        assert result.long_outcome == "PASS"

    def test_long_outcome_set_on_partial(self):
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = _make_result([("s1", "FAILED"), ("s2", "SUCCESS")])
        self.evaluator.evaluate(task, result)
        assert result.long_outcome == "PARTIAL"

    def test_long_outcome_set_on_fail(self):
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = _make_result([("s1", "SUCCESS"), ("s2", "FAILED")])
        self.evaluator.evaluate(task, result)
        assert result.long_outcome == "FAIL"

    def test_long_outcome_none_for_not_applicable(self):
        task = _make_task([])
        result = TaskResult(task_id="t", run_id="r", stage_results=[])
        self.evaluator.evaluate(task, result)
        assert result.long_outcome is None

    def test_passed_property_respects_long_outcome(self):
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
        self.evaluator.evaluate(task, result)
        assert result.passed is True

    def test_passed_property_false_for_partial(self):
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = _make_result([("s1", "FAILED"), ("s2", "SUCCESS")])
        self.evaluator.evaluate(task, result)
        assert result.passed is False


class TestBackwardCompatibility:
    """Ensure changes don't break SINGLE, EXEC, MULTI modes."""

    def setup_method(self):
        self.evaluator = LongHorizonEvaluator()

    def test_single_mode_not_applicable(self):
        task = Task(
            id="S-001", category="arch", mode=ExecutionMode.SINGLE,
            difficulty=Difficulty.L3, prompt="Hello",
            partition=BenchmarkPartition.DEVELOPMENT,
        )
        result = TaskResult(task_id="S-001", run_id="r1")
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.NOT_APPLICABLE

    def test_exec_mode_not_applicable(self):
        task = Task(
            id="E-001", category="code", mode=ExecutionMode.EXEC,
            difficulty=Difficulty.L2, prompt="Fix bug",
            partition=BenchmarkPartition.DEVELOPMENT,
        )
        result = TaskResult(task_id="E-001", run_id="r1")
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.NOT_APPLICABLE

    def test_multi_mode_not_applicable(self):
        task = Task(
            id="M-001", category="arch", mode=ExecutionMode.MULTI,
            difficulty=Difficulty.L3, prompt="Discuss",
            partition=BenchmarkPartition.DEVELOPMENT,
        )
        result = TaskResult(task_id="M-001", run_id="r1")
        ev = self.evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.NOT_APPLICABLE


class TestEvidenceAndFlags:
    """Test that evidence and flags are informative."""

    def setup_method(self):
        self.evaluator = LongHorizonEvaluator()

    def test_terminal_failure_evidence(self):
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = _make_result([("s1", "SUCCESS"), ("s2", "FAILED")])
        ev = self.evaluator.evaluate(task, result)
        assert "terminal_stage_failed" in ev.evidence
        assert any("terminal_failure" in f for f in ev.flags)

    def test_error_stage_flag(self):
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = TaskResult(
            task_id="EB-CAL-001", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="ERROR", error="boom"),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
            ],
        )
        ev = self.evaluator.evaluate(task, result)
        assert any("stage_error" in f for f in ev.flags)

    def test_stage_failed_flag(self):
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = _make_result([("s1", "FAILED"), ("s2", "SUCCESS")])
        ev = self.evaluator.evaluate(task, result)
        assert any("stage_failed" in f for f in ev.flags)

    def test_rationale_includes_outcome(self):
        task = _make_task([
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = _make_result([("s1", "FAILED"), ("s2", "SUCCESS")])
        ev = self.evaluator.evaluate(task, result)
        assert "outcome=PARTIAL" in ev.rationale
