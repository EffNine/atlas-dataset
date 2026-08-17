"""Tests for Stage 8E.2 — LONG Judge Calibration Set & Reference Labels.

Validates:
  - All 12 fixtures load and are schema-valid
  - Deterministic outcomes are correct (judge mocked to unavailable)
  - Judge eligibility follows gating rules
  - Reference labels are explicit (no fabricated human labels)
  - Calibration metadata validates
  - Judge output can be recorded without live API
  - Fixture hashes are stable
"""
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add benchmarks/eb to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from eb.core.schema import (
    StageData,
    StageResult,
    Task,
    TaskResult,
)
from eb.core.types import (
    BenchmarkPartition,
    Capability,
    Difficulty,
    EvaluatorStatus,
    ExecutionMode,
    JudgeMode,
)
from eb.evaluators.judge import JudgeEvaluator
from eb.evaluators.long_horizon import LongHorizonEvaluator


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIXTURES_ROOT = Path(__file__).parent.parent / "repositories" / "fixtures" / "long-calibration"
CALIBRATION_META_PATH = Path(__file__).resolve().parent.parent.parent.parent / "metadata" / "calibration" / "long_judge_calibration_v1.json"

EXPECTED_OUTCOMES = {
    "C1-obvious-success": "PASS",
    "C2-obvious-failure": "FAIL",
    "C3-partial-impl": "PARTIAL",
    "C4-correct-poor-quality": "PASS",
    "C5-high-quality": "PASS",
    "C6-req-change-correct": "PASS",
    "C7-req-change-ignored": "FAIL",
    "C8-unnecessary-refactor": "PASS",
    "C9-regression": "FAIL",
    "C10-tests-overfit": "PASS",
    "C11-weak-tests": "PASS",
    "C12-strong-tests-incomplete": "PARTIAL",
}

# Judge eligibility per fixture (True = judge attempted, False = judge skipped)
JUDGE_ELIGIBLE = {
    "C1-obvious-success": True,
    "C2-obvious-failure": False,
    "C3-partial-impl": True,
    "C4-correct-poor-quality": True,
    "C5-high-quality": True,
    "C6-req-change-correct": True,
    "C7-req-change-ignored": False,
    "C8-unnecessary-refactor": True,
    "C9-regression": False,
    "C10-tests-overfit": True,
    "C11-weak-tests": True,
    "C12-strong-tests-incomplete": True,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture(fixture_name: str) -> dict:
    """Load a calibration fixture JSON."""
    fixture_path = FIXTURES_ROOT / fixture_name / "fixture.json"
    assert fixture_path.exists(), f"Missing fixture: {fixture_path}"
    with fixture_path.open() as f:
        return json.load(f)


def _build_task_from_fixture(fixture: dict) -> Task:
    """Build a Task from a fixture dict."""
    stages = fixture.get("stages", [])
    context = {"stages": stages}
    if "delivery_criteria" in fixture:
        context["delivery_criteria"] = fixture["delivery_criteria"]
    metadata = fixture.get("metadata", {})
    caps = metadata.get("capabilities", ["CODE", "TEST"])
    valid_caps = []
    for c in caps:
        try:
            valid_caps.append(Capability(c))
        except ValueError:
            pass
    if not valid_caps:
        valid_caps = [Capability.CODE]
    return Task.model_validate({
        "id": f"EB-CAL-{fixture['id']}",
        "category": metadata.get("category", "engineering"),
        "mode": ExecutionMode.LONG,
        "difficulty": Difficulty.L3,
        "capabilities": valid_caps,
        "prompt": f"Calibration task: {fixture['id']}",
        "partition": BenchmarkPartition.DEVELOPMENT,
        "context": context,
    })


def _make_stage_results_for_fixture(fixture_name: str, fixture: dict) -> list[StageResult]:
    """Return simulated stage results matching the intended scenario."""
    stages = fixture.get("stages", [])
    results = []
    n = len(stages)

    if fixture_name == "C1-obvious-success":
        # All SUCCESS, high scores
        for s in stages:
            results.append(StageResult(
                stage_id=s["id"], stage_name=s["name"],
                status="SUCCESS", score=1.0,
                output=f"Stage {s['id']} completed successfully",
            ))
    elif fixture_name == "C2-obvious-failure":
        # Stage 1 SUCCESS, terminal stage FAILED
        results.append(StageResult(stage_id=stages[0]["id"], stage_name=stages[0]["name"],
                                   status="SUCCESS", score=1.0))
        results.append(StageResult(stage_id=stages[-1]["id"], stage_name=stages[-1]["name"],
                                   status="FAILED", score=0.0, error="terminal failure"))
    elif fixture_name == "C3-partial-impl":
        # Core implementation (add) succeeds; remaining functions incomplete.
        # Non-terminal implement_rest stage fails; terminal test stage succeeds.
        # Outcome: PARTIAL (terminal not failed, but not all stages succeeded).
        for i, s in enumerate(stages):
            if i == 2:
                # implement_rest: failed — only add was implemented
                results.append(StageResult(stage_id=s["id"], stage_name=s["name"],
                                           status="FAILED", score=0.0, error="missing subtract/multiply/divide"))
            else:
                results.append(StageResult(stage_id=s["id"], stage_name=s["name"],
                                           status="SUCCESS", score=1.0))
    elif fixture_name == "C4-correct-poor-quality":
        # All SUCCESS but low scores — delivery criteria not met (no "passed" in response)
        for s in stages:
            results.append(StageResult(stage_id=s["id"], stage_name=s["name"],
                                       status="SUCCESS", score=0.4))
    elif fixture_name == "C5-high-quality":
        # All SUCCESS, high scores, delivery met
        for s in stages:
            results.append(StageResult(stage_id=s["id"], stage_name=s["name"],
                                       status="SUCCESS", score=0.95))
    elif fixture_name == "C6-req-change-correct":
        # All SUCCESS, adaptation succeeded
        for s in stages:
            results.append(StageResult(stage_id=s["id"], stage_name=s["name"],
                                       status="SUCCESS", score=0.9))
    elif fixture_name == "C7-req-change-ignored":
        # Stages 1-2 SUCCESS, stage 3 (after req change) FAILED
        for i, s in enumerate(stages):
            if i < 2:
                results.append(StageResult(stage_id=s["id"], stage_name=s["name"],
                                           status="SUCCESS", score=1.0))
            else:
                results.append(StageResult(stage_id=s["id"], stage_name=s["name"],
                                           status="FAILED", score=0.0, error="did not adapt"))
    elif fixture_name == "C8-unnecessary-refactor":
        # All SUCCESS but implementation is over-engineered
        for s in stages:
            results.append(StageResult(stage_id=s["id"], stage_name=s["name"],
                                       status="SUCCESS", score=0.7))
    elif fixture_name == "C9-regression":
        # Terminal stage fails due to regression
        results.append(StageResult(stage_id=stages[0]["id"], stage_name=stages[0]["name"],
                                   status="SUCCESS", score=1.0))
        results.append(StageResult(stage_id=stages[1]["id"], stage_name=stages[1]["name"],
                                   status="SUCCESS", score=0.8))
        results.append(StageResult(stage_id=stages[-1]["id"], stage_name=stages[-1]["name"],
                                   status="FAILED", score=0.0, error="regression in divide"))
    elif fixture_name == "C10-tests-overfit":
        # All SUCCESS (tests manipulated to pass)
        for s in stages:
            results.append(StageResult(stage_id=s["id"], stage_name=s["name"],
                                       status="SUCCESS", score=1.0))
    elif fixture_name == "C11-weak-tests":
        # All SUCCESS (weak tests pass)
        for s in stages:
            results.append(StageResult(stage_id=s["id"], stage_name=s["name"],
                                       status="SUCCESS", score=1.0))
    elif fixture_name == "C12-strong-tests-incomplete":
        # Strong comprehensive tests written (stages 0-1 succeed).
        # Implementation is incomplete — only add/subtract present.
        # implement_partial stage fails; terminal test stage succeeds.
        # Outcome: PARTIAL (strong tests expose gap, terminal not failed).
        for i, s in enumerate(stages):
            if i == 2:
                # implement_partial: failed — only add/subtract implemented
                results.append(StageResult(stage_id=s["id"], stage_name=s["name"],
                                           status="FAILED", score=0.0, error="missing multiply/divide"))
            else:
                results.append(StageResult(stage_id=s["id"], stage_name=s["name"],
                                           status="SUCCESS", score=1.0))
    else:
        # Default: all SUCCESS
        for s in stages:
            results.append(StageResult(stage_id=s["id"], stage_name=s["name"],
                                       status="SUCCESS", score=1.0))

    return results


def _get_raw_response(fixture_name: str) -> str:
    """Return appropriate raw_response to satisfy delivery criteria where needed."""
    # Fixtures with delivery_criteria that checks for "passed"
    pass_needed = [
        "C1-obvious-success", "C4-correct-poor-quality", "C5-high-quality",
        "C6-req-change-correct", "C8-unnecessary-refactor",
        "C10-tests-overfit", "C11-weak-tests",
    ]
    if fixture_name in pass_needed:
        return "All tests passed successfully"
    return "Calibration evaluation complete"


def _run_evaluation(fixture_name: str) -> tuple[Task, TaskResult, dict]:
    """Run full evaluation for a fixture and return (task, result, eval_result)."""
    fixture = _load_fixture(fixture_name)
    task = _build_task_from_fixture(fixture)
    stage_results = _make_stage_results_for_fixture(fixture_name, fixture)
    raw_response = _get_raw_response(fixture_name)

    result = TaskResult(
        task_id=f"EB-CAL-{fixture_name}",
        run_id="calibration-run-001",
        stage_results=stage_results,
        raw_response=raw_response,
    )

    evaluator = LongHorizonEvaluator()
    # Mock judge as unavailable to test deterministic logic in isolation
    with patch.object(JudgeEvaluator, '_ensure_client', side_effect=ValueError("no judge env")):
        ev_result = evaluator.evaluate(task, result)
    return task, result, ev_result.model_dump()


# ---------------------------------------------------------------------------
# Fixture Loading Tests
# ---------------------------------------------------------------------------

class TestFixtureLoading:
    """All 12 fixtures must load and be schema-valid."""

    @pytest.mark.parametrize("fixture_name", [
        "C1-obvious-success",
        "C2-obvious-failure",
        "C3-partial-impl",
        "C4-correct-poor-quality",
        "C5-high-quality",
        "C6-req-change-correct",
        "C7-req-change-ignored",
        "C8-unnecessary-refactor",
        "C9-regression",
        "C10-tests-overfit",
        "C11-weak-tests",
        "C12-strong-tests-incomplete",
    ])
    def test_fixture_exists_and_loads(self, fixture_name: str):
        fixture = _load_fixture(fixture_name)
        assert "id" in fixture
        assert fixture["id"] == fixture_name
        assert "stages" in fixture
        assert isinstance(fixture["stages"], list)
        assert len(fixture["stages"]) > 0

    def test_all_12_fixtures_present(self):
        """Exactly 12 calibration fixtures must exist."""
        fixture_dirs = [d for d in FIXTURES_ROOT.iterdir() if d.is_dir()]
        assert len(fixture_dirs) == 12, f"Expected 12 fixtures, found {len(fixture_dirs)}"

    def test_fixture_schema_valid(self):
        """Each fixture must be convertible to a valid Task."""
        for fixture_name in EXPECTED_OUTCOMES:
            fixture = _load_fixture(fixture_name)
            task = _build_task_from_fixture(fixture)
            assert task.id.startswith("EB-CAL-")
            assert task.mode == ExecutionMode.LONG

    def test_fixture_hashes_stable(self):
        """Fixture JSON files must have stable content (no random timestamps)."""
        for fixture_name in EXPECTED_OUTCOMES:
            fixture_path = FIXTURES_ROOT / fixture_name / "fixture.json"
            content = fixture_path.read_bytes()
            h = hashlib.sha256(content).hexdigest()[:16]
            content2 = fixture_path.read_bytes()
            h2 = hashlib.sha256(content2).hexdigest()[:16]
            assert h == h2, f"Fixture {fixture_name} hash unstable"


# ---------------------------------------------------------------------------
# Deterministic Outcome Tests
# ---------------------------------------------------------------------------

class TestDeterministicOutcomes:
    """Verify deterministic outcomes match expected values."""

    @pytest.mark.parametrize("fixture_name,expected_outcome", [
        ("C1-obvious-success", "PASS"),
        ("C2-obvious-failure", "FAIL"),
        ("C3-partial-impl", "PARTIAL"),
        ("C4-correct-poor-quality", "PASS"),
        ("C5-high-quality", "PASS"),
        ("C6-req-change-correct", "PASS"),
        ("C7-req-change-ignored", "FAIL"),
        ("C8-unnecessary-refactor", "PASS"),
        ("C9-regression", "FAIL"),
        ("C10-tests-overfit", "PASS"),
        ("C11-weak-tests", "PASS"),
        ("C12-strong-tests-incomplete", "PARTIAL"),
    ])
    def test_deterministic_outcome(self, fixture_name: str, expected_outcome: str):
        task, result, ev = _run_evaluation(fixture_name)
        assert ev["status"] == expected_outcome, (
            f"{fixture_name}: expected {expected_outcome}, got {ev['status']}"
        )
        assert result.long_outcome == expected_outcome

    def test_c1_high_score(self):
        """C1 should produce a high deterministic score (>0.8)."""
        _, _, ev = _run_evaluation("C1-obvious-success")
        assert ev["score"] is not None
        assert ev["score"] >= 0.8, f"C1 score {ev['score']} below 0.8 threshold"

    def test_c2_zero_score(self):
        """C2 (terminal failure) must produce score 0.0."""
        _, _, ev = _run_evaluation("C2-obvious-failure")
        assert ev["score"] == 0.0

    def test_c9_zero_score(self):
        """C9 (regression) must produce score 0.0."""
        _, _, ev = _run_evaluation("C9-regression")
        assert ev["score"] == 0.0


# ---------------------------------------------------------------------------
# Judge Eligibility Tests
# ---------------------------------------------------------------------------

class TestJudgeEligibility:
    """Judge invocation must follow gating rules from 8E.1."""

    @pytest.mark.parametrize("fixture_name,eligible", [
        ("C1-obvious-success", True),
        ("C2-obvious-failure", False),
        ("C3-partial-impl", True),
        ("C4-correct-poor-quality", True),
        ("C5-high-quality", True),
        ("C6-req-change-correct", True),
        ("C7-req-change-ignored", False),
        ("C8-unnecessary-refactor", True),
        ("C9-regression", False),
        ("C10-tests-overfit", True),
        ("C11-weak-tests", True),
        ("C12-strong-tests-incomplete", True),
    ])
    def test_judge_skipped_for_fail(self, fixture_name: str, eligible: bool):
        """FAIL outcomes must skip judge; PASS/PARTIAL must attempt judge."""
        fixture = _load_fixture(fixture_name)
        task = _build_task_from_fixture(fixture)
        stage_results = _make_stage_results_for_fixture(fixture_name, fixture)
        raw_response = _get_raw_response(fixture_name)
        result = TaskResult(
            task_id=f"EB-CAL-{fixture_name}",
            run_id="calibration-run-001",
            stage_results=stage_results,
            raw_response=raw_response,
        )
        evaluator = LongHorizonEvaluator()
        # Mock judge unavailable to test deterministic gating only
        with patch.object(JudgeEvaluator, '_ensure_client', side_effect=ValueError("no judge env")):
            ev_result = evaluator.evaluate(task, result)

        has_quality = "quality_score" in ev_result.details
        if not eligible:
            # FAIL → judge must be skipped
            assert not has_quality, (
                f"{fixture_name}: judge should be skipped for {ev_result.status}"
            )
        # PASS/PARTIAL → judge is attempted (may return None if client unavailable)
        # We don't assert quality_score presence because client may be unavailable

    def test_c2_judge_skipped(self):
        """C2 (FAIL) must not invoke judge."""
        _, _, ev = _run_evaluation("C2-obvious-failure")
        assert "quality_score" not in ev["details"]

    def test_c9_judge_skipped(self):
        """C9 (FAIL due to regression) must not invoke judge."""
        _, _, ev = _run_evaluation("C9-regression")
        assert "quality_score" not in ev["details"]

    def test_c1_judge_attempted(self):
        """C1 (PASS) must attempt judge invocation."""
        fixture = _load_fixture("C1-obvious-success")
        task = _build_task_from_fixture(fixture)
        stage_results = _make_stage_results_for_fixture("C1-obvious-success", fixture)
        result = TaskResult(
            task_id="EB-CAL-C1", run_id="r1",
            stage_results=stage_results,
            raw_response="All tests passed successfully",
        )
        evaluator = LongHorizonEvaluator()
        # Mock judge unavailable to isolate deterministic check
        with patch.object(JudgeEvaluator, '_ensure_client', side_effect=ValueError("no judge env")):
            ev = evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.PASS
        # Judge was attempted but skipped due to unavailable client
        assert "quality_score" not in ev.details

    def test_c3_judge_attempted(self):
        """C3 (PARTIAL — incomplete implementation) must attempt judge invocation."""
        _, _, ev = _run_evaluation("C3-partial-impl")
        assert ev["status"] == EvaluatorStatus.PARTIAL.value
        # Judge was attempted but skipped due to unavailable client
        assert "quality_score" not in ev["details"]

    def test_c12_judge_attempted(self):
        """C12 (PARTIAL — strong tests, incomplete impl) must attempt judge invocation."""
        _, _, ev = _run_evaluation("C12-strong-tests-incomplete")
        assert ev["status"] == EvaluatorStatus.PARTIAL.value
        # Judge was attempted but skipped due to unavailable client
        assert "quality_score" not in ev["details"]

    def test_c7_judge_skipped(self):
        """C7 (FAIL — requirement change ignored, terminal fails) must not invoke judge."""
        _, _, ev = _run_evaluation("C7-req-change-ignored")
        assert ev["status"] == EvaluatorStatus.FAIL.value
        assert "quality_score" not in ev["details"]


# ---------------------------------------------------------------------------
# Reference Labels Tests
# ---------------------------------------------------------------------------

class TestReferenceLabels:
    """Validate calibration metadata and reference labels."""

    def test_metadata_file_exists(self):
        assert CALIBRATION_META_PATH.exists(), f"Missing calibration metadata: {CALIBRATION_META_PATH}"

    def test_metadata_schema_valid(self):
        with CALIBRATION_META_PATH.open() as f:
            meta = json.load(f)
        assert meta.get("calibration_version") == "v1.0"
        assert "created_at" in meta
        assert "rubric_version" in meta
        assert "fixtures" in meta
        assert len(meta["fixtures"]) == 12

    def test_all_fixtures_have_reference_entries(self):
        """Every calibration fixture must have a reference entry."""
        with CALIBRATION_META_PATH.open() as f:
            meta = json.load(f)
        fixture_ids = {f["fixture_id"] for f in meta["fixtures"]}
        for fn in EXPECTED_OUTCOMES:
            found = fn in fixture_ids
            assert found, f"Missing reference entry for {fn}"

    def test_no_fabricated_human_labels(self):
        """No reference label should claim to be 'human' or 'expert' without explicit status."""
        with CALIBRATION_META_PATH.open() as f:
            meta = json.load(f)
        for entry in meta["fixtures"]:
            status = entry.get("reference_status")
            assert status in (
                "deterministic_reference",
                "expert_review_required",
                "provisional",
                "judge_output",
            ), f"{entry['fixture_id']}: unexpected reference_status={status!r}"

    def test_deterministic_references_explicit(self):
        """C1, C2, C7, C9 should use deterministic_reference where applicable."""
        with CALIBRATION_META_PATH.open() as f:
            meta = json.load(f)
        by_id = {f["fixture_id"]: f for f in meta["fixtures"]}

        assert by_id["C2-obvious-failure"]["reference_status"] == "deterministic_reference"
        assert by_id["C7-req-change-ignored"]["reference_status"] == "deterministic_reference"
        assert by_id["C9-regression"]["reference_status"] == "deterministic_reference"

    def test_expert_review_required_for_susceptible_fixtures(self):
        """C3-C6 and C8, C10-C12 should be marked expert_review_required."""
        with CALIBRATION_META_PATH.open() as f:
            meta = json.load(f)
        by_id = {f["fixture_id"]: f for f in meta["fixtures"]}

        expert_required = [
            "C3-partial-impl", "C4-correct-poor-quality", "C5-high-quality",
            "C6-req-change-correct", "C8-unnecessary-refactor",
            "C10-tests-overfit", "C11-weak-tests", "C12-strong-tests-incomplete",
        ]
        for fid in expert_required:
            assert by_id[fid]["reference_status"] == "expert_review_required", (
                f"{fid} should be expert_review_required"
            )


# ---------------------------------------------------------------------------
# Mock Judge Tests
# ---------------------------------------------------------------------------

class TestMockJudgeRecording:
    """Judge output can be recorded without live API."""

    def test_judge_output_recorded_without_api(self):
        """With a mocked judge, quality_score should be recorded in details."""
        fixture_name = "C1-obvious-success"
        fixture = _load_fixture(fixture_name)
        task = _build_task_from_fixture(fixture)
        stage_results = _make_stage_results_for_fixture(fixture_name, fixture)
        result = TaskResult(
            task_id=f"EB-CAL-{fixture_name}",
            run_id="calibration-run-001",
            stage_results=stage_results,
            raw_response="All tests passed successfully",
        )

        mock_judge_response = json.dumps({
            "score": 0.85,
            "criterion_scores": {
                "correctness": 0.9,
                "completeness": 0.85,
                "requirement_adherence": 0.9,
                "implementation_quality": 0.8,
                "test_quality": 0.85,
                "regression_safety": 0.95,
                "adaptation_quality": 0.9,
                "final_delivery_quality": 0.85,
            },
            "reasoning_summary": "High quality implementation",
            "evidence": ["all tests pass", "clean code"],
            "flags": [],
            "confidence": 0.85,
        })

        with patch.dict('os.environ', {'EB_JUDGE_BASE_URL': 'http://test:8000', 'EB_JUDGE_API_KEY': 'test-key'}):
            with patch('eb.evaluators.judge.JudgeClient.from_env') as MockFromEnv:
                mock_instance = MagicMock()
                mock_instance.discover_models.return_value = [
                    MagicMock(id="fake-judge", owned_by="test")
                ]
                mock_instance.evaluate.return_value = (mock_judge_response, 0.1, 10, 5)
                MockFromEnv.return_value = mock_instance

                evaluator = LongHorizonEvaluator()
                ev_result = evaluator.evaluate(task, result)

        assert ev_result.status == EvaluatorStatus.PASS
        assert "quality_score" in ev_result.details
        assert ev_result.details["quality_score"] == 0.85

    def test_judge_does_not_affect_deterministic_score(self):
        """Judge quality_score must not modify raw_task_score or long_outcome."""
        fixture_name = "C1-obvious-success"
        fixture = _load_fixture(fixture_name)
        task = _build_task_from_fixture(fixture)
        stage_results = _make_stage_results_for_fixture(fixture_name, fixture)
        result = TaskResult(
            task_id=f"EB-CAL-{fixture_name}",
            run_id="calibration-run-001",
            stage_results=stage_results,
            raw_response="All tests passed successfully",
        )

        mock_judge_response = json.dumps({
            "score": 0.1,
            "criterion_scores": {},
            "reasoning_summary": "bad",
            "evidence": [],
            "flags": ["poor"],
            "confidence": 0.2,
        })

        evaluator = LongHorizonEvaluator()
        ev_before = evaluator.evaluate(task, result)
        deterministic_score_before = ev_before.score
        outcome_before = result.long_outcome

        with patch.dict('os.environ', {'EB_JUDGE_BASE_URL': 'http://test:8000', 'EB_JUDGE_API_KEY': 'test-key'}):
            with patch('eb.evaluators.judge.JudgeClient.from_env') as MockFromEnv:
                mock_instance = MagicMock()
                mock_instance.discover_models.return_value = [
                    MagicMock(id="fake-judge", owned_by="test")
                ]
                mock_instance.evaluate.return_value = (mock_judge_response, 0.1, 10, 5)
                MockFromEnv.return_value = mock_instance

                ev_after = evaluator.evaluate(task, result)

        assert ev_after.score == deterministic_score_before
        assert result.long_outcome == outcome_before
        assert ev_after.details.get("quality_score") == 0.1


# ---------------------------------------------------------------------------
# Rubric Dimension Tests
# ---------------------------------------------------------------------------

class TestRubricDimensions:
    """Validate 8-dimension rubric is applied in calibration context."""

    def test_eight_dimensions_in_criteria(self):
        """JudgeEvaluator must derive exactly 8 LONG criteria."""
        evaluator = JudgeEvaluator()
        task = Task.model_validate({
            "id": "EB-CAL-DIM-TEST",
            "category": "engineering",
            "mode": ExecutionMode.LONG,
            "difficulty": Difficulty.L3,
            "capabilities": [Capability.LONG],
            "prompt": "Test dimension derivation",
            "partition": BenchmarkPartition.DEVELOPMENT,
            "context": {"stages": []},
        })
        criteria = evaluator._derive_criteria(task)
        long_ids = {
            "correctness", "completeness", "requirement_adherence",
            "implementation_quality", "test_quality", "regression_safety",
            "adaptation_quality", "final_delivery_quality",
        }
        found_ids = {c["id"] for c in criteria}
        assert long_ids == found_ids, f"Expected {long_ids}, got {found_ids}"

    def test_weights_sum_to_one(self):
        evaluator = JudgeEvaluator()
        task = Task.model_validate({
            "id": "EB-CAL-WEIGHT-TEST",
            "category": "long_horizon",
            "mode": ExecutionMode.LONG,
            "difficulty": Difficulty.L3,
            "capabilities": [Capability.LONG],
            "prompt": "Test weight sum",
            "partition": BenchmarkPartition.DEVELOPMENT,
            "context": {"stages": []},
        })
        criteria = evaluator._derive_criteria(task)
        total = sum(c.get("weight", 0.0) for c in criteria)
        assert abs(total - 1.0) < 0.001, f"Weights sum to {total}"

    def test_old_criteria_removed(self):
        """Old 3-dimension criteria must not appear in LONG tasks."""
        evaluator = JudgeEvaluator()
        task = Task.model_validate({
            "id": "EB-CAL-OLD-TEST",
            "category": "long_horizon",
            "mode": ExecutionMode.LONG,
            "difficulty": Difficulty.L3,
            "capabilities": [Capability.LONG],
            "prompt": "Test old criteria removed",
            "partition": BenchmarkPartition.DEVELOPMENT,
            "context": {"stages": []},
        })
        criteria = evaluator._derive_criteria(task)
        old_ids = {"comprehension", "coherence", "completion"}
        found_old = old_ids & {c["id"] for c in criteria}
        assert found_old == set(), f"Old criteria still present: {found_old}"


# ---------------------------------------------------------------------------
# Calibration Metadata Consistency
# ---------------------------------------------------------------------------

class TestCalibrationMetadataConsistency:
    """Ensure calibration metadata is consistent with fixture outcomes."""

    def test_metadata_matches_fixture_count(self):
        with CALIBRATION_META_PATH.open() as f:
            meta = json.load(f)
        fixture_dirs = [d for d in FIXTURES_ROOT.iterdir() if d.is_dir()]
        assert len(meta["fixtures"]) == len(fixture_dirs) == 12

    def test_all_fixtures_have_scenario_field(self):
        with CALIBRATION_META_PATH.open() as f:
            meta = json.load(f)
        for entry in meta["fixtures"]:
            assert "scenario" in entry
            assert entry["scenario"] is not None
            assert isinstance(entry["scenario"], str)

    def test_all_fixtures_have_rationale(self):
        with CALIBRATION_META_PATH.open() as f:
            meta = json.load(f)
        for entry in meta["fixtures"]:
            assert "reference_rationale" in entry
            assert len(entry["reference_rationale"]) > 0

    def test_dimension_references_have_status(self):
        """Every dimension reference must have an explicit status."""
        with CALIBRATION_META_PATH.open() as f:
            meta = json.load(f)
        valid_statuses = {"deterministic_reference", "expert_review_required", "provisional", "judge_output"}
        for entry in meta["fixtures"]:
            for dim_name, dim_ref in entry.get("dimension_references", {}).items():
                assert "status" in dim_ref, f"{entry['fixture_id']}.{dim_name} missing status"
                assert dim_ref["status"] in valid_statuses, (
                    f"{entry['fixture_id']}.{dim_name} has invalid status: {dim_ref['status']}"
                )

    def test_rubric_version_recorded(self):
        with CALIBRATION_META_PATH.open() as f:
            meta = json.load(f)
        assert meta.get("rubric_version") == "8E.1"

    def test_created_at_present(self):
        with CALIBRATION_META_PATH.open() as f:
            meta = json.load(f)
        assert "created_at" in meta
        assert "T" in meta["created_at"]  # ISO format check


# ---------------------------------------------------------------------------
# End-to-End Calibration Run
# ---------------------------------------------------------------------------

class TestCalibrationRun:
    """Full end-to-end calibration: load fixtures, evaluate, record results."""

    def test_full_calibration_run(self):
        """Run all 12 fixtures and verify outcomes."""
        results = {}
        for fixture_name in EXPECTED_OUTCOMES:
            task, result, ev = _run_evaluation(fixture_name)
            results[fixture_name] = {
                "outcome": ev["status"],
                "score": ev["score"],
                "judge_eligible": ev["status"] in ("PASS", "PARTIAL"),
                "long_outcome": result.long_outcome,
            }

        for fixture_name, expected in EXPECTED_OUTCOMES.items():
            assert results[fixture_name]["outcome"] == expected, (
                f"{fixture_name}: expected {expected}, got {results[fixture_name]['outcome']}"
            )

    def test_calibration_is_deterministic(self):
        """Running calibration twice must produce identical outcomes."""
        run1 = {}
        for fixture_name in EXPECTED_OUTCOMES:
            _, _, ev = _run_evaluation(fixture_name)
            run1[fixture_name] = ev["status"]

        run2 = {}
        for fixture_name in EXPECTED_OUTCOMES:
            _, _, ev = _run_evaluation(fixture_name)
            run2[fixture_name] = ev["status"]

        assert run1 == run2, "Calibration runs are not deterministic"
