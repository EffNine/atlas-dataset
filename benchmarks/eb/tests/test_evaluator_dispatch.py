"""Tests for eb/evaluators/dispatcher.py — Evaluator dispatcher."""
import pytest

from eb.core.schema import Task, TaskResult, EvaluatorResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition, JudgeMode, EvaluatorStatus
from eb.evaluators.dispatcher import EvaluatorDispatcher
from eb.evaluators.base import Evaluator


def _make_task(**overrides) -> Task:
    defaults = {
        "id": "EB-DISP-001",
        "category": "coding",
        "mode": ExecutionMode.SINGLE,
        "difficulty": Difficulty.L3,
        "capabilities": [Capability.CODE],
        "prompt": "Write code.",
        "partition": BenchmarkPartition.DEVELOPMENT,
        "context": {},
    }
    defaults.update(overrides)
    return Task.model_validate(defaults)


def _make_result(text: str = "response") -> TaskResult:
    return TaskResult(task_id="EB-DISP-001", run_id="run-1", raw_response=text)


class TestEvaluatorDispatcher:
    def setup_method(self):
        self.dispatcher = EvaluatorDispatcher()

    def test_lookup_registered_evaluator(self):
        from eb.evaluators.exact import ExactEvaluator
        ev = ExactEvaluator()
        self.dispatcher.register(ev)
        assert self.dispatcher.get("exact") is ev

    def test_lookup_unknown_returns_none(self):
        assert self.dispatcher.get("nonexistent") is None

    def test_dispatch_exact_match(self):
        task = _make_task(context={"expected": "correct"})
        result = _make_result("correct")
        outcomes = self.dispatcher.dispatch(task, result)
        assert len(outcomes) > 0
        exact_results = [o for o in outcomes if o.evaluator == "exact"]
        assert len(exact_results) == 1
        assert exact_results[0].status == EvaluatorStatus.PASS

    def test_dispatch_unknown_type(self):
        task = _make_task()
        result = _make_result("response")
        outcomes = self.dispatcher.dispatch(task, result, evaluator_specs=[
            {"type": "nonexistent_eval", "required": True}
        ])
        unknown = [o for o in outcomes if o.evaluator == "nonexistent_eval"]
        assert len(unknown) == 1
        assert unknown[0].status == EvaluatorStatus.UNSUPPORTED

    def test_dispatch_multiple_evaluators(self):
        task = _make_task(
            category="coding",
            context={"expected": "42", "required_claims": ["answer"]},
            evaluation={
                "evaluators": [
                    {"type": "exact", "required": True, "parameters": {"expected": "42"}},
                    {"type": "evidence", "required": False, "parameters": {"required_claims": ["answer"]}},
                ]
            }
        )
        result = _make_result("42 answer is correct")
        outcomes = self.dispatcher.dispatch(task, result)
        names = [o.evaluator for o in outcomes]
        assert "exact" in names
        assert "evidence" in names

    def test_dispatch_required_evaluator_missing(self):
        task = _make_task()
        outcomes = self.dispatcher.dispatch(task, _make_result("no code here"), evaluator_specs=[
            {"type": "exact", "required": True, "parameters": {"expected": "42"}},
            {"type": "code", "required": True},
        ])
        # Both should run; exact fails (expected mismatch), code may fail (no code)
        names = [o.evaluator for o in outcomes]
        assert "exact" in names
        assert "code" in names

    def test_default_specs_for_deterministic(self):
        task = _make_task(context={"expected": "answer"})
        result = _make_result("answer")
        outcomes = self.dispatcher.dispatch(task, result)
        assert len(outcomes) > 0

    def test_default_specs_for_rubric_mode(self):
        task = _make_task(
            evaluation={"primary_mode": "RUBRIC", "evaluators": []},
            context={"criteria": [{"id": "arch", "weight": 1.0}]}
        )
        result = _make_result("response")
        outcomes = self.dispatcher.dispatch(task, result)
        rubric_results = [o for o in outcomes if o.evaluator == "rubric"]
        assert len(rubric_results) == 1

    def test_unsupported_evaluator_does_not_crash(self):
        task = _make_task()
        outcomes = self.dispatcher.dispatch(task, _make_result("response"), evaluator_specs=[
            {"type": "cloud_judge_staging", "required": False}
        ])
        assert len(outcomes) == 1
        assert outcomes[0].status == EvaluatorStatus.UNSUPPORTED

    def test_evaluator_exception_handled(self):
        class BrokenEvaluator(Evaluator):
            @property
            def name(self): return "broken"
            @property
            def authority_level(self): return 1
            @property
            def supported_modes(self): return [JudgeMode.DETERMINISTIC]
            def is_applicable(self, task): return True
            def evaluate(self, task, result):
                raise RuntimeError("intentional failure")

        self.dispatcher.register(BrokenEvaluator())
        task = _make_task()
        outcomes = self.dispatcher.dispatch(task, _make_result("response"), evaluator_specs=[
            {"type": "broken", "required": False}
        ])
        assert len(outcomes) == 1
        assert outcomes[0].status == EvaluatorStatus.ERROR
        assert outcomes[0].rationale and "intentional failure" in outcomes[0].rationale

    def test_register_and_retrieve(self):
        from eb.evaluators.exact import ExactEvaluator
        ev = ExactEvaluator()
        self.dispatcher.register(ev)
        assert self.dispatcher.get("exact") is ev

    def test_dispatch_caches_known_evaluators(self):
        task = _make_task(context={"expected": "x"})
        result = _make_result("x")
        # First dispatch registers exact
        self.dispatcher.dispatch(task, result)
        # Second dispatch should find it cached
        outcomes2 = self.dispatcher.dispatch(task, result)
        assert len(outcomes2) > 0
