"""Tests for Stage 8E.1 — LONG Judge Criteria & Gated Invocation."""
import json
import pytest
from unittest.mock import MagicMock, patch

from eb.core.schema import (
    StageData, StageResult, Task, TaskResult, EvaluatorResult,
    JudgeModelInfo, JudgeCapabilityProfile,
)
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition, JudgeMode, EvaluatorStatus
from eb.evaluators.long_horizon import LongHorizonEvaluator
from eb.evaluators.judge import JudgeEvaluator
from eb.judges.prompt_builder import JudgePromptBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_long_task(stages: list[dict] | None = None, **overrides) -> Task:
    if stages is None:
        stages = [
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ]
    defaults = {
        "id": "EB-LONG-8E1",
        "category": "engineering",
        "mode": ExecutionMode.LONG,
        "difficulty": Difficulty.L3,
        "capabilities": [Capability.LONG],
        "prompt": "Complete the engineering workflow.",
        "partition": BenchmarkPartition.DEVELOPMENT,
        "context": {"stages": stages},
    }
    defaults.update(overrides)
    return Task.model_validate(defaults)


def _make_result(stage_statuses: list[tuple]) -> TaskResult:
    sr_list = []
    for i, (sid, status) in enumerate(stage_statuses):
        sr = StageResult(stage_id=sid, stage_name=f"S{i}", status=status, score=1.0 if status == "SUCCESS" else 0.0)
        sr_list.append(sr)
    return TaskResult(task_id="EB-LONG-8E1", run_id="r1", stage_results=sr_list, raw_response="done")


class _FakeJudgeClient:
    """Mock judge client that returns structured JSON."""

    def __init__(self, response: str | None = None, models: list[dict] | None = None):
        self._response = response or '{"score": 0.8, "criterion_scores": {}, "reasoning_summary": "good", "evidence": [], "flags": [], "confidence": 0.8}'
        self._models = models or [{"id": "fake-judge", "owned_by": "test"}]
        self.call_count = 0

    def discover_models(self, force_refresh=False):
        return [JudgeModelInfo(id=m["id"], owned_by=m.get("owned_by")) for m in self._models]

    def evaluate(self, model_id, messages, *, max_tokens=2048, temperature=0.0, timeout_s=None, retry_count=0):
        self.call_count += 1
        return self._response, 0.1, 10, 5


# ---------------------------------------------------------------------------
# LONG Rubric Dimensions
# ---------------------------------------------------------------------------


class TestLongRubricDimensions:
    """Test that the LONG-specific judge rubric has exactly 8 dimensions with correct weights."""

    def test_eight_dimensions_present(self):
        """All 8 dimension IDs should appear in the judge prompt."""
        builder = JudgePromptBuilder()
        task = _make_long_task()
        result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
        stages = [StageData(id="s1", name="S1", prompt="P1"), StageData(id="s2", name="S2", prompt="P2", terminal=True)]
        from eb.evaluators.judge import JudgeEvaluator
        criteria = JudgeEvaluator()._derive_criteria(task)
        messages = builder.build_long_evidence_prompt(task, result, result.stage_results, stages, criteria)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        content = messages[1]["content"]
        # All 8 dimension IDs should appear in the prompt
        for dim in ("correctness", "completeness", "requirement_adherence",
                     "implementation_quality", "test_quality", "regression_safety",
                     "adaptation_quality", "final_delivery_quality"):
            assert dim in content, f"Dimension {dim} missing from prompt"

    def test_weights_sum_to_one(self):
        evaluator = JudgeEvaluator()
        task = _make_long_task()
        criteria = evaluator._derive_criteria(task)
        long_criteria = [c for c in criteria if c.get("id") in (
            "correctness", "completeness", "requirement_adherence",
            "implementation_quality", "test_quality", "regression_safety",
            "adaptation_quality", "final_delivery_quality",
        )]
        assert len(long_criteria) == 8
        total_weight = sum(c.get("weight", 0.0) for c in long_criteria)
        assert abs(total_weight - 1.0) < 0.001, f"Weights sum to {total_weight}, expected 1.0"

    def test_weight_values_correct(self):
        evaluator = JudgeEvaluator()
        task = _make_long_task()
        criteria = evaluator._derive_criteria(task)
        expected = {
            "correctness": 0.25,
            "completeness": 0.15,
            "requirement_adherence": 0.15,
            "implementation_quality": 0.15,
            "test_quality": 0.10,
            "regression_safety": 0.10,
            "adaptation_quality": 0.05,
            "final_delivery_quality": 0.05,
        }
        by_id = {c["id"]: c.get("weight", 0.0) for c in criteria}
        for dim, expected_weight in expected.items():
            assert by_id.get(dim) == expected_weight, f"{dim}: expected {expected_weight}, got {by_id.get(dim)}"

    def test_old_criteria_removed(self):
        """Old 3-dimension criteria (comprehension, coherence, completion) must not appear."""
        evaluator = JudgeEvaluator()
        task = _make_long_task()
        criteria = evaluator._derive_criteria(task)
        old_ids = {"comprehension", "coherence", "completion"}
        found_old = old_ids & {c.get("id") for c in criteria}
        assert found_old == set(), f"Old criteria still present: {found_old}"


# ---------------------------------------------------------------------------
# Gated Judge Invocation
# ---------------------------------------------------------------------------


class TestGatedJudgeInvocation:
    """Test that judge is only invoked for PASS and PARTIAL outcomes."""

    def _skip_judge(self):
        """Helper to patch _ensure_client to raise ValueError (simulates missing env)."""
        return patch.object(JudgeEvaluator, '_ensure_client', side_effect=ValueError("no judge env"))

    def test_pass_outcome_invokes_judge(self):
        """PASS → judge should be attempted; quality_score may be None if client unavailable."""
        task = _make_long_task()
        result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
        evaluator = LongHorizonEvaluator()
        with self._skip_judge():
            ev = evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.PASS
        assert result.long_outcome == "PASS"
        # No quality_score when judge is unavailable
        assert "quality_score" not in ev.details

    def test_partial_outcome_invokes_judge(self):
        """PARTIAL → judge should be attempted; quality_score may be None if client unavailable."""
        task = _make_long_task()
        result = _make_result([("s1", "FAILED"), ("s2", "SUCCESS")])
        evaluator = LongHorizonEvaluator()
        with self._skip_judge():
            ev = evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.PARTIAL
        assert result.long_outcome == "PARTIAL"
        # No quality_score when judge is unavailable
        assert "quality_score" not in ev.details

    def test_fail_outcome_skips_judge(self):
        """FAIL → judge must be skipped."""
        task = _make_long_task()
        result = _make_result([("s1", "SUCCESS"), ("s2", "FAILED")])
        evaluator = LongHorizonEvaluator()
        ev = evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.FAIL
        assert ev.score == 0.0
        assert result.long_outcome == "FAIL"
        # quality_score must NOT be present in details
        assert "quality_score" not in ev.details

    def test_not_applicable_skips_judge(self):
        """NOT_APPLICABLE → judge must be skipped."""
        task = _make_long_task([])
        result = TaskResult(task_id="EB-LONG-8E1", run_id="r1", stage_results=[])
        evaluator = LongHorizonEvaluator()
        ev = evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.NOT_APPLICABLE
        assert "quality_score" not in ev.details

    def test_adapter_error_skips_judge(self):
        """ERROR stages → FAIL → judge skipped."""
        task = _make_long_task()
        result = TaskResult(
            task_id="EB-LONG-8E1", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="ERROR", error="boom"),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
            ],
        )
        evaluator = LongHorizonEvaluator()
        ev = evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.FAIL
        assert "quality_score" not in ev.details


# ---------------------------------------------------------------------------
# Quality Score
# ---------------------------------------------------------------------------


class TestQualityScore:
    """Test that quality_score is separate from deterministic score."""

    def test_quality_score_in_details_for_pass(self):
        """PASS outcome → quality_score present in details (when judge available)."""
        task = _make_long_task()
        result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
        evaluator = LongHorizonEvaluator()
        with patch.dict('os.environ', {'EB_JUDGE_BASE_URL': 'http://test:8000', 'EB_JUDGE_API_KEY': 'test-key'}):
            with patch('eb.evaluators.judge.JudgeClient.from_env') as MockFromEnv:
                mock_instance = MagicMock()
                mock_instance.discover_models.return_value = [JudgeModelInfo(id="fake-judge", owned_by="test")]
                mock_instance.evaluate.return_value = ('{"score": 0.75, "criterion_scores": {}, "reasoning_summary": "ok", "evidence": [], "flags": [], "confidence": 0.7}', 0.1, 10, 5)
                MockFromEnv.return_value = mock_instance
                ev = evaluator.evaluate(task, result)
        # Deterministic score unchanged
        assert ev.score is not None
        assert ev.score > 0.0
        # Quality score should be in details
        assert "quality_score" in ev.details
        assert ev.details["quality_score"] == 0.75

    def test_quality_score_range(self):
        """quality_score must be in [0.0, 1.0]."""
        task = _make_long_task()
        result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
        evaluator = LongHorizonEvaluator()
        with patch.dict('os.environ', {'EB_JUDGE_BASE_URL': 'http://test:8000', 'EB_JUDGE_API_KEY': 'test-key'}):
            with patch('eb.evaluators.judge.JudgeClient.from_env') as MockFromEnv:
                mock_instance = MagicMock()
                mock_instance.discover_models.return_value = [JudgeModelInfo(id="fake-judge", owned_by="test")]
                mock_instance.evaluate.return_value = ('{"score": 0.3, "criterion_scores": {}, "reasoning_summary": "ok", "evidence": [], "flags": [], "confidence": 0.5}', 0.1, 10, 5)
                MockFromEnv.return_value = mock_instance
                ev = evaluator.evaluate(task, result)
        qs = ev.details.get("quality_score")
        assert qs is not None
        assert 0.0 <= qs <= 1.0

    def test_quality_does_not_change_raw_task_score(self):
        """quality_score must not modify raw_task_score."""
        task = _make_long_task()
        result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
        evaluator = LongHorizonEvaluator()
        ev_before = evaluator.evaluate(task, result)
        deterministic_score = ev_before.score
        raw_score = result.raw_task_score

        with patch.dict('os.environ', {'EB_JUDGE_BASE_URL': 'http://test:8000', 'EB_JUDGE_API_KEY': 'test-key'}):
            with patch('eb.evaluators.judge.JudgeClient.from_env') as MockFromEnv:
                mock_instance = MagicMock()
                mock_instance.discover_models.return_value = [JudgeModelInfo(id="fake-judge", owned_by="test")]
                mock_instance.evaluate.return_value = ('{"score": 0.1, "criterion_scores": {}, "reasoning_summary": "bad", "evidence": [], "flags": ["poor"], "confidence": 0.3}', 0.1, 10, 5)
                MockFromEnv.return_value = mock_instance
                ev_after = evaluator.evaluate(task, result)

        # Deterministic score must be identical
        assert ev_after.score == deterministic_score
        assert result.raw_task_score == raw_score
        # But quality_score should reflect the judge's assessment
        assert ev_after.details.get("quality_score") == 0.1

    def test_quality_does_not_change_long_outcome(self):
        """quality_score must not modify long_outcome."""
        task = _make_long_task()
        result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
        evaluator = LongHorizonEvaluator()
        ev_before = evaluator.evaluate(task, result)
        outcome_before = result.long_outcome

        with patch.dict('os.environ', {'EB_JUDGE_BASE_URL': 'http://test:8000', 'EB_JUDGE_API_KEY': 'test-key'}):
            with patch('eb.evaluators.judge.JudgeClient.from_env') as MockFromEnv:
                mock_instance = MagicMock()
                mock_instance.discover_models.return_value = [JudgeModelInfo(id="fake-judge", owned_by="test")]
                mock_instance.evaluate.return_value = ('{"score": 0.0, "criterion_scores": {}, "reasoning_summary": "terrible", "evidence": [], "flags": ["fail"], "confidence": 0.1}', 0.1, 10, 5)
                MockFromEnv.return_value = mock_instance
                ev_after = evaluator.evaluate(task, result)

        assert result.long_outcome == outcome_before
        assert ev_after.status == EvaluatorStatus.PASS

    def test_judge_cannot_override_deterministic_fail(self):
        """Even if judge would rate high, FAIL outcome must remain FAIL."""
        task = _make_long_task()
        result = _make_result([("s1", "SUCCESS"), ("s2", "FAILED")])
        evaluator = LongHorizonEvaluator()
        ev = evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.FAIL
        assert ev.score == 0.0
        assert result.long_outcome == "FAIL"
        # No quality_score because judge was skipped
        assert "quality_score" not in ev.details


# ---------------------------------------------------------------------------
# Evidence Bounding
# ---------------------------------------------------------------------------


class TestEvidenceBounding:
    """Test that judge evidence is bounded and secrets are excluded."""

    def test_evidence_bounded(self):
        """Long stage outputs should be truncated in judge prompt."""
        builder = JudgePromptBuilder()
        task = _make_long_task()
        long_output = "x" * 5000
        result = TaskResult(
            task_id="EB-LONG-8E1", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0, output=long_output),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0, output="done"),
            ],
            raw_response="final output",
        )
        stages = [
            StageData(id="s1", name="S1", prompt="P1"),
            StageData(id="s2", name="S2", prompt="P2", terminal=True),
        ]
        messages = builder.build_long_evidence_prompt(task, result, result.stage_results, stages, [])
        content = messages[1]["content"]
        # Should not exceed max_evidence_chars (default 12000)
        assert len(content) <= 12500  # small buffer for formatting overhead

    def test_secrets_excluded(self):
        """API keys and secrets must not appear in judge prompt."""
        builder = JudgePromptBuilder()
        task = _make_long_task(context={
            "stages": [
                {"id": "s1", "name": "S1", "prompt": "P1"},
                {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
            ],
            "api_key": "sk-secret-key-12345",
            "password": "hunter2",
            "expected": "ground_truth_answer",
        })
        result = TaskResult(
            task_id="EB-LONG-8E1", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
            ],
            raw_response="done",
        )
        stages = [
            StageData(id="s1", name="S1", prompt="P1"),
            StageData(id="s2", name="S2", prompt="P2", terminal=True),
        ]
        messages = builder.build_long_evidence_prompt(task, result, result.stage_results, stages, [])
        content = messages[1]["content"]
        assert "sk-secret-key-12345" not in content
        assert "hunter2" not in content
        assert "ground_truth_answer" not in content

    def test_ground_truth_excluded(self):
        """expected/answer/acceptable_answers must not leak."""
        builder = JudgePromptBuilder()
        task = _make_long_task(context={
            "stages": [{"id": "s1", "name": "S1", "prompt": "P1"}],
            "expected": "the_correct_answer",
            "answer": "also_correct",
            "acceptable_answers": ["alt1", "alt2"],
        })
        result = TaskResult(task_id="t", run_id="r", stage_results=[], raw_response="x")
        stages = [StageData(id="s1", name="S1", prompt="P1")]
        messages = builder.build_long_evidence_prompt(task, result, result.stage_results, stages, [])
        content = messages[1]["content"]
        assert "the_correct_answer" not in content
        assert "also_correct" not in content
        assert "alt1" not in content


# ---------------------------------------------------------------------------
# Non-LONG Modes Unaffected
# ---------------------------------------------------------------------------


class TestNonLongModesUnaffected:
    """SINGLE, EXEC, MULTI modes must not be affected by 8E.1 changes."""

    def test_single_mode_unaffected(self):
        task = Task(
            id="S-001", category="arch", mode=ExecutionMode.SINGLE,
            difficulty=Difficulty.L3, prompt="Hello",
            partition=BenchmarkPartition.DEVELOPMENT,
        )
        result = TaskResult(task_id="S-001", run_id="r1")
        evaluator = LongHorizonEvaluator()
        ev = evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.NOT_APPLICABLE
        assert "quality_score" not in ev.details

    def test_exec_mode_unaffected(self):
        task = Task(
            id="E-001", category="code", mode=ExecutionMode.EXEC,
            difficulty=Difficulty.L2, prompt="Fix bug",
            partition=BenchmarkPartition.DEVELOPMENT,
        )
        result = TaskResult(task_id="E-001", run_id="r1")
        evaluator = LongHorizonEvaluator()
        ev = evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.NOT_APPLICABLE

    def test_multi_mode_unaffected(self):
        task = Task(
            id="M-001", category="arch", mode=ExecutionMode.MULTI,
            difficulty=Difficulty.L3, prompt="Discuss",
            partition=BenchmarkPartition.DEVELOPMENT,
        )
        result = TaskResult(task_id="M-001", run_id="r1")
        evaluator = LongHorizonEvaluator()
        ev = evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Existing Non-LONG Judge Behavior
# ---------------------------------------------------------------------------


class TestExistingJudgeBehaviorUnaffected:
    """Non-LONG judge evaluation must continue to work as before."""

    def test_architecture_judge_criteria(self):
        evaluator = JudgeEvaluator()
        task = Task(
            id="ARCH-001", category="architecture", mode=ExecutionMode.SINGLE,
            difficulty=Difficulty.L4, capabilities=[Capability.ARCH],
            prompt="Design a system.", partition=BenchmarkPartition.DEVELOPMENT,
        )
        criteria = evaluator._derive_criteria(task)
        crit_ids = {c["id"] for c in criteria}
        assert "architecture_quality" in crit_ids
        assert "tradeoff_reasoning" in crit_ids
        total = sum(c.get("weight", 0) for c in criteria)
        assert abs(total - 1.0) < 0.001

    def test_coding_judge_criteria(self):
        evaluator = JudgeEvaluator()
        task = Task(
            id="CODE-001", category="coding", mode=ExecutionMode.SINGLE,
            difficulty=Difficulty.L3, capabilities=[Capability.CODE],
            prompt="Write code.", partition=BenchmarkPartition.DEVELOPMENT,
        )
        criteria = evaluator._derive_criteria(task)
        crit_ids = {c["id"] for c in criteria}
        assert "correctness" in crit_ids
        assert "code_quality" in crit_ids
        assert "efficiency" in crit_ids

    def test_judge_authority_level_unchanged(self):
        evaluator = JudgeEvaluator()
        assert evaluator.authority_level == 3
        assert evaluator.name == "judge"

    def test_judge_does_not_crash_on_missing_env(self):
        """When judge env vars are missing, LongHorizonEvaluator should skip gracefully."""
        import os
        # Ensure env vars are unset
        orig_url = os.environ.pop("EB_JUDGE_BASE_URL", None)
        orig_key = os.environ.pop("EB_JUDGE_API_KEY", None)
        try:
            task = _make_long_task()
            result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
            evaluator = LongHorizonEvaluator()
            ev = evaluator.evaluate(task, result)
            assert ev.status == EvaluatorStatus.PASS
            # No quality_score when judge is unavailable
            assert "quality_score" not in ev.details
        finally:
            if orig_url:
                os.environ["EB_JUDGE_BASE_URL"] = orig_url
            if orig_key:
                os.environ["EB_JUDGE_API_KEY"] = orig_key
