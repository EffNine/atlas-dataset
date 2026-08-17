"""Tests for eb/evaluators/evidence.py — Evidence evaluator."""
import pytest

from eb.core.schema import Task, TaskResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition, EvaluatorStatus
from eb.evaluators.evidence import EvidenceEvaluator


def _make_task(**overrides) -> Task:
    defaults = {
        "id": "EB-EVID-001",
        "category": "evidence",
        "mode": ExecutionMode.SINGLE,
        "difficulty": Difficulty.L4,
        "capabilities": [Capability.EVIDENCE],
        "prompt": "Support your claim.",
        "partition": BenchmarkPartition.DEVELOPMENT,
        "context": {},
    }
    defaults.update(overrides)
    return Task.model_validate(defaults)


def _make_result(text: str) -> TaskResult:
    return TaskResult(task_id="EB-EVID-001", run_id="run-1", raw_response=text)


class TestEvidenceEvaluator:
    def setup_method(self):
        self.evaluator = EvidenceEvaluator()

    def test_required_claims_all_present(self):
        task = _make_task(context={"required_claims": ["claim A", "claim B"]})
        result = _make_result("I agree with claim A and claim B because...")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PASS
        assert outcome.score == 1.0

    def test_required_claims_partial(self):
        task = _make_task(context={"required_claims": ["claim A", "claim B", "claim C"]})
        result = _make_result("I agree with claim A only.")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.FAIL
        assert outcome.score == pytest.approx(0.333, abs=0.01)

    def test_required_claims_none_present(self):
        task = _make_task(context={"required_claims": ["claim A", "claim B"]})
        result = _make_result("I disagree with everything.")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.FAIL
        assert outcome.score == 0.0

    def test_forbidden_claims_absent(self):
        task = _make_task(context={"forbidden_claims": ["secret info", "classified data"]})
        result = _make_result("This is public information.")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PASS
        assert outcome.score == 1.0

    def test_forbidden_claims_present(self):
        task = _make_task(context={"forbidden_claims": ["secret info"]})
        result = _make_result("I will reveal secret info now.")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.FAIL
        assert outcome.score == 0.0

    def test_expected_facts_present(self):
        task = _make_task(context={"expected_facts": ["fact one", "fact two"]})
        result = _make_result("fact one is true and fact two is also true.")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PASS

    def test_expected_facts_partial(self):
        task = _make_task(context={"expected_facts": ["fact one", "fact two", "fact three"]})
        result = _make_result("fact one is mentioned.")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.FAIL
        assert outcome.score == pytest.approx(0.333, abs=0.01)

    def test_no_evidence_requirements(self):
        task = _make_task(context={})
        result = _make_result("whatever")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.NOT_APPLICABLE

    def test_is_applicable_with_claims(self):
        task = _make_task(context={"required_claims": ["x"]})
        assert self.evaluator.is_applicable(task) is True

    def test_is_applicable_without_claims(self):
        task = _make_task(context={})
        assert self.evaluator.is_applicable(task) is False

    def test_case_insensitive(self):
        task = _make_task(context={"required_claims": ["Claim A"]})
        result = _make_result("i mention claim a in my response.")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.PASS

    def test_evaluator_name(self):
        assert self.evaluator.name == "evidence"

    def test_authority_level(self):
        assert self.evaluator.authority_level == 1
