"""Tests for eb/scoring/raw.py — Raw score aggregation."""
import pytest

from eb.core.schema import TaskResult, EvaluatorResult
from eb.core.types import Capability, EvaluatorStatus, JudgeMode
from eb.scoring.raw import (
    TaskRawScore,
    CapabilityRawScore,
    RunRawScores,
    aggregate_task_evaluator_results,
)


def _make_eval_result(evaluator: str, score: float | None, status: EvaluatorStatus, authority: int = 1) -> EvaluatorResult:
    return EvaluatorResult(
        evaluator=evaluator,
        mode=JudgeMode.DETERMINISTIC,
        status=status,
        score=score,
        max_score=1.0,
        normalized_score=score,
        authoritative_level=authority,
    )


def _make_task_result(task_id: str, eval_results: list[EvaluatorResult]) -> TaskResult:
    return TaskResult(task_id=task_id, run_id="run-1", evaluator_results=eval_results)


class TestTaskRawScore:
    def test_add_and_compute(self):
        ts = TaskRawScore(task_id="t1")
        ts.add_repeat(0.8, "PASS", [])
        ts.add_repeat(1.0, "PASS", [])
        ts.add_repeat(0.9, "PASS", [])
        ts.compute()
        assert ts.raw_mean == pytest.approx(0.9)
        assert ts.raw_median == pytest.approx(0.9)
        assert ts.raw_min == 0.8
        assert ts.raw_max == 1.0
        assert ts.task_count == 3

    def test_single_repeat(self):
        ts = TaskRawScore(task_id="t1")
        ts.add_repeat(0.75, "PASS", [])
        ts.compute()
        assert ts.raw_mean == 0.75
        assert ts.raw_stddev == 0.0
        assert ts.raw_error_percent == 0.0

    def test_empty_no_compute(self):
        ts = TaskRawScore(task_id="t1")
        ts.compute()
        assert ts.raw_mean is None
        assert ts.raw_stddev is None

    def test_error_counting(self):
        ts = TaskRawScore(task_id="t1")
        ts.add_repeat(0.5, "ERROR", [])
        ts.add_repeat(0.8, "PASS", [])
        ts.compute()
        assert ts.error_count == 1
        assert ts.task_count == 2

    def test_has_data(self):
        ts = TaskRawScore(task_id="t1")
        assert ts.has_data is False
        ts.add_repeat(0.5, "PASS", [])
        assert ts.has_data is True


class TestCapabilityRawScore:
    def test_compute_from_tasks(self):
        ts1 = TaskRawScore(task_id="t1")
        ts1.add_repeat(0.8, "PASS", [])
        ts1.compute()
        ts2 = TaskRawScore(task_id="t2")
        ts2.add_repeat(1.0, "PASS", [])
        ts2.compute()

        cs = CapabilityRawScore(capability=Capability.CODE)
        cs.task_scores = [ts1, ts2]
        cs.compute()
        assert cs.raw_mean == pytest.approx(0.9)
        assert cs.task_count == 2

    def test_empty_capability(self):
        cs = CapabilityRawScore(capability=Capability.ARCH)
        cs.compute()
        assert cs.raw_mean is None

    def test_no_double_counting(self):
        """Same task can appear in multiple capabilities; each contributes once per capability."""
        ts = TaskRawScore(task_id="t1")
        ts.add_repeat(0.9, "PASS", [])
        ts.compute()

        cs_arch = CapabilityRawScore(capability=Capability.ARCH)
        cs_arch.task_scores.append(ts)
        cs_arch.compute()

        cs_code = CapabilityRawScore(capability=Capability.CODE)
        cs_code.task_scores.append(ts)
        cs_code.compute()

        assert cs_arch.raw_mean == 0.9
        assert cs_code.raw_mean == 0.9
        # Each capability independently counts the task
        assert cs_arch.task_count == 1
        assert cs_code.task_count == 1


class TestRunRawScores:
    def test_add_task_result(self):
        run = RunRawScores(run_id="r1")
        eval_r = _make_eval_result("exact", 1.0, EvaluatorStatus.PASS)
        task_r = _make_task_result("t1", [eval_r])
        run.add_task_result(task_r, [Capability.CODE])
        run.compute()
        assert run.overall_raw_mean == pytest.approx(1.0)
        assert run.overall_task_count == 1

    def test_multiple_tasks_different_capabilities(self):
        run = RunRawScores(run_id="r1")
        # Task 1: ARCH
        eval1 = _make_eval_result("exact", 0.8, EvaluatorStatus.PASS)
        run.add_task_result(_make_task_result("t1", [eval1]), [Capability.ARCH])
        # Task 2: CODE
        eval2 = _make_eval_result("exact", 1.0, EvaluatorStatus.PASS)
        run.add_task_result(_make_task_result("t2", [eval2]), [Capability.CODE])
        run.compute()
        assert run.overall_raw_mean == pytest.approx(0.9)
        assert "ARCH" in run.capability_scores
        assert "CODE" in run.capability_scores

    def test_primary_capability_policy(self):
        """First capability is used as primary."""
        run = RunRawScores(run_id="r1")
        eval_r = _make_eval_result("exact", 0.7, EvaluatorStatus.PASS)
        run.add_task_result(_make_task_result("t1", [eval_r]), [Capability.ARCH,Capability.CODE])
        run.compute()
        assert run.capability_scores["ARCH"].raw_mean == 0.7
        # CODE should not have this task (primary is ARCH)
        assert "CODE" not in run.capability_scores or run.capability_scores["CODE"].task_count == 0

    def test_zero_mean_safety(self):
        run = RunRawScores(run_id="r1")
        eval_r = _make_eval_result("exact", 0.0, EvaluatorStatus.FAIL)
        run.add_task_result(_make_task_result("t1", [eval_r]), [Capability.CODE])
        run.compute()
        assert run.overall_raw_mean == 0.0
        # Should not crash on zero mean
        ts = run.task_scores["t1"]
        assert ts.raw_error_percent is None  # safe: division by zero avoided

    def test_evaluator_results_preserved(self):
        run = RunRawScores(run_id="r1")
        eval_r = _make_eval_result("exact", 1.0, EvaluatorStatus.PASS)
        run.add_task_result(_make_task_result("t1", [eval_r]), [Capability.CODE])
        assert len(run.all_evaluator_results) == 1
        assert run.all_evaluator_results[0].evaluator == "exact"

    def test_get_task_raw_score(self):
        run = RunRawScores(run_id="r1")
        eval_r = _make_eval_result("exact", 0.5, EvaluatorStatus.PASS)
        run.add_task_result(_make_task_result("t1", [eval_r]), [Capability.CODE])
        run.compute()
        assert run.get_task_raw_score("t1") == 0.5
        assert run.get_task_raw_score("missing") is None


class TestAggregateTaskEvaluatorResults:
    def test_single_authoritative(self):
        results = [
            _make_eval_result("exact", 1.0, EvaluatorStatus.PASS, authority=1),
            _make_eval_result("rubric", 0.5, EvaluatorStatus.PASS, authority=2),
        ]
        score = aggregate_task_evaluator_results(results, "single_authoritative")
        # Higher authority (rubric=2) wins
        assert score == 0.5

    def test_weighted(self):
        results = [
            _make_eval_result("exact", 1.0, EvaluatorStatus.PASS, authority=1),
            _make_eval_result("rubric", 0.5, EvaluatorStatus.PASS, authority=2),
        ]
        score = aggregate_task_evaluator_results(results, "weighted")
        # (1*1.0 + 2*0.5) / (1+2) = 2.0/3 = 0.667
        assert score == pytest.approx(0.667, abs=0.01)

    def test_all_required_min(self):
        results = [
            _make_eval_result("exact", 1.0, EvaluatorStatus.PASS),
            _make_eval_result("code", 0.3, EvaluatorStatus.FAIL),
        ]
        score = aggregate_task_evaluator_results(results, "all_required")
        assert score == 0.3

    def test_any_required_max(self):
        results = [
            _make_eval_result("exact", 1.0, EvaluatorStatus.PASS),
            _make_eval_result("code", 0.3, EvaluatorStatus.FAIL),
        ]
        score = aggregate_task_evaluator_results(results, "any_required")
        assert score == 1.0

    def test_empty_results(self):
        score = aggregate_task_evaluator_results([], "single_authoritative")
        assert score is None

    def test_all_not_applicable(self):
        results = [
            _make_eval_result("exact", None, EvaluatorStatus.NOT_APPLICABLE),
        ]
        score = aggregate_task_evaluator_results(results, "single_authoritative")
        assert score is None

    def test_unknown_strategy_fallback(self):
        results = [
            _make_eval_result("exact", 0.8, EvaluatorStatus.PASS),
        ]
        score = aggregate_task_evaluator_results(results, "unknown_strategy")
        assert score == 0.8

    def test_no_double_counting_in_capability(self):
        """A task with multiple capabilities only counts once per capability."""
        run = RunRawScores(run_id="r1")
        eval_r = _make_eval_result("exact", 0.9, EvaluatorStatus.PASS)
        run.add_task_result(_make_task_result("t1", [eval_r]), [Capability.ARCH, Capability.CODE, Capability.TEST])
        run.compute()
        # Only ARCH gets the task (primary)
        assert run.capability_scores["ARCH"].task_count == 1
        assert "CODE" not in run.capability_scores or run.capability_scores["CODE"].task_count == 0
        assert "TEST" not in run.capability_scores or run.capability_scores["TEST"].task_count == 0
