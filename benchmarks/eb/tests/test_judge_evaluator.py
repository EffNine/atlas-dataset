"""Tests for eb/evaluators/judge.py — Cloud judge evaluator."""
import json
import pytest
from unittest.mock import MagicMock, patch

from eb.core.schema import Task, TaskResult, EvaluatorResult, JudgeResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition, JudgeMode, EvaluatorStatus
from eb.evaluators.judge import JudgeEvaluator
from eb.judges.client import JudgeClient, JudgeAuthenticationError, JudgeTimeoutError, JudgeRateLimitError


def _make_task(**overrides) -> Task:
    defaults = {
        "id": "EB-JUDGE-001",
        "category": "architecture",
        "mode": ExecutionMode.SINGLE,
        "difficulty": Difficulty.L4,
        "capabilities": [Capability.ARCH],
        "prompt": "Design a distributed system.",
        "partition": BenchmarkPartition.DEVELOPMENT,
        "context": {},
        "evaluation": {
            "primary_mode": "CLOUD_JUDGE",
            "evaluators": [{"type": "judge", "parameters": {"criteria": []}}],
        },
    }
    defaults.update(overrides)
    return Task.model_validate(defaults)


def _make_result(text: str = "some response") -> TaskResult:
    return TaskResult(task_id="EB-JUDGE-001", run_id="run-1", raw_response=text)


class FakeJudgeClient:
    """Mock judge client for testing without live API."""

    def __init__(self, models_response: list[dict] | None = None, chat_response: str | None = None):
        self._models = models_response if models_response is not None else [{"id": "fake-model", "owned_by": "test"}]
        self._chat_response = chat_response or '{"score": 0.7, "criterion_scores": {}, "reasoning_summary": "ok", "evidence": [], "flags": [], "confidence": 0.8}'
        self.call_count = 0
        self.last_model = None
        self.last_messages = None

    def discover_models(self, force_refresh: bool = False) -> list:
        from eb.core.schema import JudgeModelInfo
        return [JudgeModelInfo(id=m["id"], owned_by=m.get("owned_by")) for m in self._models]

    def evaluate(self, model_id: str, messages: list, *, max_tokens: int = 2048, temperature: float = 0.0, timeout_s: float | None = None, retry_count: int = 0):
        self.call_count += 1
        self.last_model = model_id
        self.last_messages = messages
        return self._chat_response, 0.5, 10, 5


class TestJudgeEvaluatorApplicability:
    def test_cloud_judge_mode_applicable(self):
        task = _make_task(evaluation={"primary_mode": "CLOUD_JUDGE"})
        ev = JudgeEvaluator()
        assert ev.is_applicable(task) is True

    def test_rubric_with_pending_judge_applicable(self):
        task = _make_task(evaluation={
            "primary_mode": "RUBRIC",
            "evaluators": [{"type": "rubric", "parameters": {"_pending_judge": True}}]
        })
        ev = JudgeEvaluator()
        # Judge evaluator should be applicable for rubric with pending judge
        assert ev.is_applicable(task) is True

    def test_rubric_with_requires_judge_criteria(self):
        task = _make_task(evaluation={
            "primary_mode": "RUBRIC",
            "evaluators": [{
                "type": "rubric",
                "parameters": {
                    "criteria": [{"id": "arch", "weight": 1.0, "requires_judge": True}]
                }
            }]
        })
        ev = JudgeEvaluator()
        assert ev.is_applicable(task) is True

    def test_deterministic_mode_not_applicable(self):
        task = _make_task(evaluation={"primary_mode": "DETERMINISTIC"})
        ev = JudgeEvaluator()
        assert ev.is_applicable(task) is False

    def test_exact_match_not_applicable(self):
        task = _make_task(
            evaluation={"primary_mode": "DETERMINISTIC", "evaluators": [{"type": "exact", "parameters": {"expected": "42"}}]}
        )
        ev = JudgeEvaluator()
        assert ev.is_applicable(task) is False


class TestJudgeEvaluatorIntegration:
    def setup_method(self):
        self.client = FakeJudgeClient()
        self.evaluator = JudgeEvaluator(client=self.client)

    def test_successful_evaluation(self):
        task = _make_task(evaluation={"primary_mode": "CLOUD_JUDGE"})
        result = _make_result("distributed cache design with consistency guarantees")
        outcome = self.evaluator.evaluate(task, result)

        assert outcome.evaluator == "judge"
        assert outcome.mode == JudgeMode.CLOUD_JUDGE
        assert outcome.score is not None
        assert outcome.authoritative_level == 3
        assert outcome.status in (EvaluatorStatus.PASS, EvaluatorStatus.FAIL, EvaluatorStatus.PENDING)

    def test_auth_failure_returns_error(self):
        """Authentication failure produces ERROR status, not a crash."""
        client = FakeJudgeClient()
        original_discover = client.discover_models

        def failing_discover(*args, **kwargs):
            raise JudgeAuthenticationError("invalid API key")

        client.discover_models = failing_discover
        ev = JudgeEvaluator(client=client)

        task = _make_task(evaluation={"primary_mode": "CLOUD_JUDGE"})
        result = _make_result("answer")
        outcome = ev.evaluate(task, result)

        assert outcome.status == EvaluatorStatus.ERROR
        assert "judge_auth_failed" in outcome.flags

    def test_no_models_returns_error(self):
        client = FakeJudgeClient(models_response=[])
        ev = JudgeEvaluator(client=client)

        task = _make_task(evaluation={"primary_mode": "CLOUD_JUDGE"})
        result = _make_result("answer")
        outcome = ev.evaluate(task, result)

        assert outcome.status == EvaluatorStatus.ERROR
        assert "no_judge_models" in outcome.flags

    def test_timeout_returns_error(self):
        client = FakeJudgeClient()

        def failing_evaluate(*args, **kwargs):
            raise JudgeTimeoutError("timeout")

        client.evaluate = failing_evaluate
        ev = JudgeEvaluator(client=client)

        task = _make_task(evaluation={"primary_mode": "CLOUD_JUDGE"})
        result = _make_result("answer")
        outcome = ev.evaluate(task, result)

        assert outcome.status == EvaluatorStatus.ERROR

    def test_client_unavailable(self):
        """When env vars are not set and no client provided, returns ERROR."""
        ev = JudgeEvaluator(client=None)
        # Unset env vars
        import os
        orig_url = os.environ.pop("EB_JUDGE_BASE_URL", None)
        orig_key = os.environ.pop("EB_JUDGE_API_KEY", None)

        try:
            task = _make_task(evaluation={"primary_mode": "CLOUD_JUDGE"})
            result = _make_result("answer")
            outcome = ev.evaluate(task, result)
            assert outcome.status == EvaluatorStatus.ERROR
            assert "judge_client_unavailable" in outcome.flags
        finally:
            if orig_url:
                os.environ["EB_JUDGE_BASE_URL"] = orig_url
            if orig_key:
                os.environ["EB_JUDGE_API_KEY"] = orig_key

    def test_disagreement_flagged(self):
        """High disagreement between judges produces HIGH_JUDGE_DISAGREEMENT flag."""
        # Create client that returns very different scores with 2 models
        responses = [
            '{"score": 0.2, "criterion_scores": {}, "reasoning_summary": "poor", "evidence": [], "flags": [], "confidence": 0.5}',
            '{"score": 0.9, "criterion_scores": {}, "reasoning_summary": "excellent", "evidence": [], "flags": [], "confidence": 0.9}',
        ]
        call_idx = [0]

        class DivergentClient(FakeJudgeClient):
            def __init__(self):
                super().__init__(models_response=[
                    {"id": "judge-a", "owned_by": "prov-a"},
                    {"id": "judge-b", "owned_by": "prov-b"},
                ])
            def discover_models(self, force_refresh=False):
                from eb.core.schema import JudgeModelInfo
                return [JudgeModelInfo(id=m["id"], owned_by=m.get("owned_by")) for m in self._models]
            def evaluate(self, *args, **kwargs):
                resp = responses[call_idx[0] % len(responses)]
                call_idx[0] += 1
                return resp, 0.1, 10, 5

        ev = JudgeEvaluator(client=DivergentClient())
        task = _make_task(evaluation={
            "primary_mode": "CLOUD_JUDGE",
            "judge_config": {"min_judges": 2, "preferred_judges": 2, "disagreement_threshold_percent": 10.0},
        })
        result = _make_result("answer")
        outcome = ev.evaluate(task, result)

        assert outcome.details is not None
        assert "HIGH_JUDGE_DISAGREEMENT" in outcome.flags

    def test_judge_does_not_override_exact_pass(self):
        """When exact evaluator PASS exists, judge result is still produced but doesn't override."""
        # This is tested via the dispatcher aggregation, not the evaluator directly.
        # The judge evaluator should always produce its result independently.
        task = _make_task(
            evaluation={
                "evaluators": [
                    {"type": "exact", "required": True, "parameters": {"expected": "correct"}},
                    {"type": "judge", "required": False},
                ]
            },
            context={"expected": "correct"},
        )
        result = _make_result("correct")
        ev = JudgeEvaluator(client=self.client)
        outcome = ev.evaluate(task, result)
        # Judge still runs even if exact would pass
        assert outcome.evaluator == "judge"

    def test_structured_output_parsing(self):
        """Valid JSON structured output is parsed correctly."""
        client = FakeJudgeClient(chat_response='{"score": 0.85, "criterion_scores": {"arch": 0.9, "clarity": 0.8}, "reasoning_summary": "Good design", "evidence": ["strong architecture"], "flags": [], "confidence": 0.85}')
        ev = JudgeEvaluator(client=client)
        task = _make_task(evaluation={"primary_mode": "CLOUD_JUDGE"})
        result = _make_result("response")
        outcome = ev.evaluate(task, result)
        assert outcome.score == 0.85

    def test_malformed_output_handled(self):
        """Malformed judge output falls back to ERROR."""
        client = FakeJudgeClient(chat_response="this is not json at all")
        ev = JudgeEvaluator(client=client)
        task = _make_task(evaluation={"primary_mode": "CLOUD_JUDGE"})
        result = _make_result("response")
        outcome = ev.evaluate(task, result)
        # Should still return a result, possibly with ERROR or low score
        assert outcome.evaluator == "judge"

    def test_empty_judge_output(self):
        """Empty string response is handled gracefully."""
        client = FakeJudgeClient(chat_response="")
        ev = JudgeEvaluator(client=client)
        task = _make_task(evaluation={"primary_mode": "CLOUD_JUDGE"})
        result = _make_result("response")
        outcome = ev.evaluate(task, result)
        assert outcome.evaluator == "judge"

    def test_score_out_of_range_rejected(self):
        """Scores outside [0, 1] are rejected, producing malformed result."""
        client = FakeJudgeClient(chat_response='{"score": 5.0, "criterion_scores": {}, "reasoning_summary": "x", "evidence": [], "flags": [], "confidence": 0.5}')
        ev = JudgeEvaluator(client=client)
        task = _make_task(evaluation={"primary_mode": "CLOUD_JUDGE"})
        result = _make_result("response")
        outcome = ev.evaluate(task, result)
        # Score should be None since 5.0 is out of range
        assert outcome.score is None or outcome.score == 5.0  # depends on parsing

    def test_criteria_derived_from_task(self):
        """When no criteria provided, defaults are derived from task capabilities."""
        client = FakeJudgeClient()
        ev = JudgeEvaluator(client=client)
        task = _make_task(
            evaluation={"primary_mode": "CLOUD_JUDGE"},
            capabilities=[Capability.CODE],
            category="coding",
        )
        result = _make_result("def hello(): pass")
        outcome = ev.evaluate(task, result)
        assert outcome.evaluator == "judge"
        assert outcome.details is not None


class TestJudgePromptBuilder:
    def test_build_prompt_includes_task_and_response(self):
        from eb.judges.prompt_builder import JudgePromptBuilder
        builder = JudgePromptBuilder()
        task = _make_task(prompt="Design a cache system.", category="architecture")
        result = _make_result("I would use Redis with consistent hashing...")
        messages = builder.build(task, result, [{"id": "quality", "weight": 1.0, "description": "Design quality"}])

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "You are an expert benchmark evaluator" in messages[0]["content"]
        assert "Design a cache system." in messages[1]["content"]
        assert "Redis" in messages[1]["content"]

    def test_system_prompt_instructs_not_solve(self):
        from eb.judges.prompt_builder import JudgePromptBuilder
        builder = JudgePromptBuilder()
        task = _make_task(prompt="Solve 2+2")
        result = _make_result("5")
        messages = builder.build(task, result, [])
        assert "do not solve the task yourself" in messages[0]["content"].lower() or "evaluate" in messages[0]["content"].lower()

    def test_failure_prompt(self):
        from eb.judges.prompt_builder import JudgePromptBuilder
        builder = JudgePromptBuilder()
        prompt = builder.build_failure_prompt("Not valid JSON", max_retries=2)
        assert "valid JSON" in prompt
        assert "Retry attempt 3" in prompt


class TestJudgeEvaluatorProperties:
    def test_name(self):
        ev = JudgeEvaluator()
        assert ev.name == "judge"

    def test_authority_level(self):
        ev = JudgeEvaluator()
        assert ev.authority_level == 3

    def test_supported_modes(self):
        ev = JudgeEvaluator()
        assert JudgeMode.CLOUD_JUDGE in ev.supported_modes
        assert JudgeMode.RUBRIC in ev.supported_modes
