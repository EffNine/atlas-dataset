"""Tests for eb/evaluators/rubric.py — Rubric evaluator."""
import pytest

from eb.core.schema import Task, TaskResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition, EvaluatorStatus, JudgeMode
from eb.evaluators.rubric import RubricEvaluator


def _make_task(**overrides) -> Task:
    defaults = {
        "id": "EB-RUB-001",
        "category": "architecture",
        "mode": ExecutionMode.SINGLE,
        "difficulty": Difficulty.L4,
        "capabilities": [Capability.ARCH],
        "prompt": "Design a system.",
        "partition": BenchmarkPartition.DEVELOPMENT,
        "context": {},
        "evaluation": {"primary_mode": "RUBRIC"},
    }
    defaults.update(overrides)
    return Task.model_validate(defaults)


def _make_result(text: str) -> TaskResult:
    return TaskResult(task_id="EB-RUB-001", run_id="run-1", raw_response=text)


class TestRubricEvaluator:
    def setup_method(self):
        self.evaluator = RubricEvaluator()

    def test_no_criteria_not_applicable(self):
        task = _make_task()
        result = _make_result("some response")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.NOT_APPLICABLE

    def test_pending_judge_when_no_criteria(self):
        task = _make_task(evaluation={
            "primary_mode": "RUBRIC",
            "evaluators": [{"type": "rubric", "parameters": {"_pending_judge": True}}]
        })
        result = _make_result("some response")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PENDING_JUDGE

    def test_deterministic_criteria_pass(self):
        task = _make_task(evaluation={
            "evaluators": [{
                "type": "rubric",
                "parameters": {
                    "criteria": [
                        {"id": "clarity", "weight": 1.0, "check": {"type": "contains", "value": "clear"}},
                        {"id": "detail", "weight": 1.0, "check": {"type": "min_length", "value": 10}},
                    ]
                }
            }]
        })
        result = _make_result("This is a clear and detailed explanation.")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PASS
        assert outcome.score == 1.0

    def test_deterministic_criteria_fail(self):
        task = _make_task(evaluation={
            "evaluators": [{
                "type": "rubric",
                "parameters": {
                    "criteria": [
                        {"id": "clarity", "weight": 1.0, "check": {"type": "contains", "value": "clear"}},
                    ]
                }
            }]
        })
        result = _make_result("vague response")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.FAIL
        assert outcome.score == 0.0

    def test_reference_scores_used(self):
        task = _make_task(evaluation={
            "evaluators": [{
                "type": "rubric",
                "parameters": {
                    "criteria": [
                        {"id": "architecture", "weight": 0.5, "score": 0.8},
                        {"id": "clarity", "weight": 0.5, "score": 0.6},
                    ]
                }
            }]
        })
        result = _make_result("response")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PASS
        assert outcome.score == pytest.approx(0.7)

    def test_weighted_aggregation(self):
        task = _make_task(evaluation={
            "evaluators": [{
                "type": "rubric",
                "parameters": {
                    "criteria": [
                        {"id": "arch", "weight": 2.0, "score": 1.0},
                        {"id": "style", "weight": 1.0, "score": 0.0},
                    ]
                }
            }]
        })
        result = _make_result("response")
        outcome = self.evaluator.evaluate(task, result)
        # (2.0 * 1.0 + 1.0 * 0.0) / 3.0 = 0.667
        assert outcome.score == pytest.approx(0.667, abs=0.01)

    def test_pending_judge_with_some_criteria(self):
        task = _make_task(evaluation={
            "evaluators": [{
                "type": "rubric",
                "parameters": {
                    "criteria": [
                        {"id": "objective", "weight": 1.0, "score": 0.8},
                        {"id": "subjective", "weight": 1.0, "requires_judge": True},
                    ]
                }
            }]
        })
        result = _make_result("response")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PENDING_JUDGE
        assert "pending_judge" in outcome.flags

    def test_regex_check_pass(self):
        task = _make_task(evaluation={
            "evaluators": [{
                "type": "rubric",
                "parameters": {
                    "criteria": [
                        {"id": "has_code", "weight": 1.0, "check": {"type": "regex", "pattern": "def\\s+"}},
                    ]
                }
            }]
        })
        result = _make_result("def my_function(): pass")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PASS

    def test_not_contains_check(self):
        task = _make_task(evaluation={
            "evaluators": [{
                "type": "rubric",
                "parameters": {
                    "criteria": [
                        {"id": "no_secret", "weight": 1.0, "check": {"type": "not_contains", "value": "password123"}},
                    ]
                }
            }]
        })
        result = _make_result("safe response without secrets")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PASS

    def test_zero_weight_rejected(self):
        task = _make_task(evaluation={
            "evaluators": [{
                "type": "rubric",
                "parameters": {
                    "criteria": [
                        {"id": "x", "weight": 0, "score": 1.0},
                    ]
                }
            }]
        })
        result = _make_result("response")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.NOT_APPLICABLE

    def test_evaluator_name(self):
        assert self.evaluator.name == "rubric"

    def test_authority_level(self):
        assert self.evaluator.authority_level == 2

    def test_supported_modes(self):
        assert JudgeMode.RUBRIC in self.evaluator.supported_modes
        assert JudgeMode.DETERMINISTIC in self.evaluator.supported_modes
