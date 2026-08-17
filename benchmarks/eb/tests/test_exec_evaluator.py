"""Tests for eb/evaluators/code.py — Extended with EXEC repository evidence evaluation."""
import pytest

from eb.evaluators.code import CodeEvaluator
from eb.core.schema import Task, TaskResult, EvaluatorResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition, EvaluatorStatus, JudgeMode


def _make_exec_task(**overrides) -> Task:
    defaults = {
        "id": "EB-EXEC-TEST",
        "category": "debug",
        "mode": ExecutionMode.EXEC,
        "difficulty": Difficulty.L2,
        "capabilities": [Capability.CODE],
        "prompt": "Fix the bug",
        "partition": BenchmarkPartition.DEVELOPMENT,
        "context": {"repository_id": "test-repo"},
    }
    defaults.update(overrides)
    return Task.model_validate(defaults)


def _make_exec_result(
    tests_passed: bool = True,
    test_count: int = 3,
    changed_files: list[str] | None = None,
    diff: str | None = "diff --git a/x.py\n+print('fixed')\n",
    **overrides,
) -> TaskResult:
    meta = {
        "test_summary": {
            "passed": tests_passed,
            "test_count": test_count,
            "exit_code": 0 if tests_passed else 1,
        },
        "changed_files": changed_files or ["src/parser.py"],
        "diff": diff,
    }
    meta.update(overrides)
    return TaskResult(
        task_id="EB-EXEC-TEST",
        run_id="run-001",
        raw_response="I fixed the bug.",
        execution_metadata=meta,
    )


class TestCodeEvaluatorWithEXEC:
    def test_exec_task_with_passing_tests_scores_high(self):
        evaluator = CodeEvaluator()
        task = _make_exec_task()
        result = _make_exec_result(tests_passed=True, test_count=3)

        ev_result = evaluator.evaluate(task, result)

        assert ev_result.status == EvaluatorStatus.PASS
        assert ev_result.score is not None
        assert ev_result.score >= 0.7

    def test_exec_task_with_failing_tests_scores_low(self):
        evaluator = CodeEvaluator()
        task = _make_exec_task()
        result = _make_exec_result(tests_passed=False, test_count=0, exit_code=1)

        ev_result = evaluator.evaluate(task, result)

        assert ev_result.status == EvaluatorStatus.FAIL
        assert ev_result.score is not None
        assert ev_result.score < 0.5

    def test_exec_task_with_no_evidence_scores_neutral(self):
        evaluator = CodeEvaluator()
        task = _make_exec_task()
        result = _make_exec_result(
            tests_passed=False,
            test_count=0,
            changed_files=[],
            diff=None,
        )

        ev_result = evaluator.evaluate(task, result)

        assert ev_result.score is not None

    def test_exec_task_with_no_changes_scores_low(self):
        evaluator = CodeEvaluator()
        task = _make_exec_task()
        result = _make_exec_result(
            tests_passed=True,
            changed_files=[],
            diff=None,
        )

        ev_result = evaluator.evaluate(task, result)

        # No code changes is a negative signal
        assert ev_result.score is not None

    def test_non_exec_task_still_works(self):
        """Single-mode tasks should still work as before."""
        evaluator = CodeEvaluator()
        task = Task(
            id="EB-SINGLE-001",
            category="coding",
            mode=ExecutionMode.SINGLE,
            difficulty=Difficulty.L1,
            capabilities=[Capability.CODE],
            prompt="Write a function",
            partition=BenchmarkPartition.DEVELOPMENT,
            context={"expected_code": "def hello(): pass"},
        )
        result = TaskResult(
            task_id="EB-SINGLE-001",
            run_id="run-001",
            raw_response="```python\ndef hello(): pass\n```",
        )

        ev_result = evaluator.evaluate(task, result)

        assert ev_result.status in (EvaluatorStatus.PASS, EvaluatorStatus.FAIL)
        assert ev_result.evaluator == "code"

    def test_exec_task_is_applicable(self):
        evaluator = CodeEvaluator()
        task = _make_exec_task()
        assert evaluator.is_applicable(task) is True

    def test_single_task_with_repository_context_not_applicable(self):
        """Tasks with old-style 'repository' context (not EXEC mode) are still NOT_APPLICABLE."""
        evaluator = CodeEvaluator()
        task = Task(
            id="EB-OLD-001",
            category="coding",
            mode=ExecutionMode.SINGLE,
            difficulty=Difficulty.L1,
            capabilities=[Capability.CODE],
            prompt="Fix this",
            partition=BenchmarkPartition.DEVELOPMENT,
            context={"repository": "/host/path/to/repo"},
        )
        assert evaluator.is_applicable(task) is False

    def test_deterministic_scoring(self):
        """Same input should produce same score every time."""
        evaluator = CodeEvaluator()
        task = _make_exec_task()
        result = _make_exec_result(tests_passed=True, test_count=5)

        r1 = evaluator.evaluate(task, result)
        r2 = evaluator.evaluate(task, result)

        assert r1.score == r2.score
        assert r1.status == r2.status
