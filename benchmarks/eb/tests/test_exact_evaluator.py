"""Tests for eb/evaluators/exact.py — Exact-match evaluator."""
import pytest

from eb.core.schema import Task, EvaluatorResult, TaskResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition, JudgeMode, EvaluatorStatus
from eb.evaluators.exact import ExactEvaluator


def _make_task(**overrides) -> Task:
    defaults = {
        "id": "EB-TEST-001",
        "category": "architecture",
        "mode": ExecutionMode.SINGLE,
        "difficulty": Difficulty.L3,
        "capabilities": [Capability.ARCH],
        "prompt": "What is 2+2?",
        "partition": BenchmarkPartition.DEVELOPMENT,
        "context": {},
    }
    defaults.update(overrides)
    return Task.model_validate(defaults)


def _make_result(text: str = "4") -> TaskResult:
    return TaskResult(task_id="EB-TEST-001", run_id="run-1", raw_response=text)


class TestExactEvaluator:
    def setup_method(self):
        self.evaluator = ExactEvaluator()

    def test_exact_match_pass(self):
        task = _make_task(context={"expected": "4"})
        result = _make_result("4")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PASS
        assert outcome.score == 1.0
        assert outcome.max_score == 1.0
        assert outcome.normalized_score == 1.0

    def test_exact_match_fail(self):
        task = _make_task(context={"expected": "4"})
        result = _make_result("5")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.FAIL
        assert outcome.score == 0.0
        assert outcome.authoritative_level == 1

    def test_exact_match_no_expected(self):
        task = _make_task(context={})
        result = _make_result("anything")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.NOT_APPLICABLE
        assert outcome.score is None

    def test_acceptable_answers_pass(self):
        task = _make_task(context={"acceptable_answers": ["4", "four", "IV"]})
        result = _make_result("four")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PASS
        assert outcome.score == 1.0

    def test_acceptable_answers_fail(self):
        task = _make_task(context={"acceptable_answers": ["4", "four"]}, evaluation={"evaluators": [
            {"type": "exact", "parameters": {}}
        ]})
        result = _make_result("five")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.FAIL
        assert outcome.score == 0.0

    def test_normalization_trim(self):
        task = _make_task(context={"expected": "hello", "evaluation": {"evaluators": [
            {"type": "exact", "parameters": {"normalization": "trim"}}
        ]}})
        result = _make_result("  hello  ")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PASS

    def test_normalization_lowercase(self):
        task = _make_task(context={"expected": "HELLO"}, evaluation={"evaluators": [
            {"type": "exact", "parameters": {"normalization": "lowercase"}}
        ]})
        result = _make_result("hello")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PASS

    def test_normalization_whitespace(self):
        task = _make_task(context={"expected": "hello world"}, evaluation={"evaluators": [
            {"type": "exact", "parameters": {"normalization": "whitespace"}}
        ]})
        result = _make_result("hello   world")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PASS

    def test_exact_normalization_no_change(self):
        task = _make_task(context={"expected": "Hello", "evaluation": {"evaluators": [
            {"type": "exact", "parameters": {"normalization": "exact"}}
        ]}})
        result = _make_result("hello")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.FAIL

    def test_is_applicable_with_expected(self):
        task = _make_task(context={"expected": "answer"})
        assert self.evaluator.is_applicable(task) is True

    def test_is_applicable_with_acceptable(self):
        task = _make_task(context={"acceptable_answers": ["a", "b"]})
        assert self.evaluator.is_applicable(task) is True

    def test_is_applicable_without_expected(self):
        task = _make_task(context={})
        assert self.evaluator.is_applicable(task) is False

    def test_evaluator_name(self):
        assert self.evaluator.name == "exact"

    def test_evaluator_mode(self):
        assert JudgeMode.DETERMINISTIC in self.evaluator.supported_modes

    def test_malformed_config_no_expected(self):
        task = _make_task(evaluation={"evaluators": [{"type": "exact", "parameters": {}}]})
        result = _make_result("whatever")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.NOT_APPLICABLE

    def test_preserves_evaluator_results(self):
        task = _make_task(context={"expected": "4"})
        result = _make_result("4")
        outcome = self.evaluator.evaluate(task, result)
        assert len(outcome.evidence) > 0
        assert len(outcome.flags) == 0

    def test_evidence_contains_details(self):
        task = _make_task(context={"expected": "correct"})
        result = _make_result("wrong")
        outcome = self.evaluator.evaluate(task, result)
        assert any("expected" in e for e in outcome.evidence)
        assert any("got" in e for e in outcome.evidence)
