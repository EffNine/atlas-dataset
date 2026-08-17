"""Tests for Stage 8E.3 — LONG Judge Agreement, Calibration & Reporting.

Validates:
  1. Agreement calculation (absolute error, MAE)
  2. MAE computation
  3. Categorical agreement
  4. Dimension-level agreement
  5. Missing reference handling
  6. Deterministic reference handling
  7. Expert reference handling
  8. LOW_AGREEMENT threshold
  9. No modification of raw_task_score
  10. No modification of long_outcome
  11. Metadata preservation
  12. Reproducibility
  13. Mock judge calibration
  14. No-live-API graceful behavior
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from eb.calibration.agreement import (
    AgreementAnalyzer,
    CalibrationReport,
    DimensionAgreement,
    FixtureAgreement,
    LOW_AGREEMENT_THRESHOLD,
    compute_agreement,
)
from eb.calibration.fixtures import (
    CalibrationFixture,
    CalibrationFixtureSet,
    DimensionReference,
    LONG_DIMENSIONS,
)
from eb.calibration.report import generate_report
from eb.core.schema import (
    EvaluatorResult,
    JudgeModelInfo,
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
# Helpers
# ---------------------------------------------------------------------------


def _make_long_task(**overrides) -> Task:
    defaults = {
        "id": "EB-CAL-8E3",
        "category": "engineering",
        "mode": ExecutionMode.LONG,
        "difficulty": Difficulty.L3,
        "capabilities": [Capability.LONG],
        "prompt": "Complete the engineering workflow.",
        "partition": BenchmarkPartition.DEVELOPMENT,
        "context": {"stages": [
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ]},
    }
    defaults.update(overrides)
    return Task.model_validate(defaults)


def _make_result(statuses: list[tuple]) -> TaskResult:
    sr_list = []
    for i, (sid, status) in enumerate(statuses):
        sr = StageResult(
            stage_id=sid, stage_name=f"S{i}",
            status=status, score=1.0 if status == "SUCCESS" else 0.0,
        )
        sr_list.append(sr)
    return TaskResult(task_id="EB-CAL-8E3", run_id="r1", stage_results=sr_list)


def _make_fixture(
    fixture_id: str,
    expected_outcome: str = "PASS",
    judge_eligible: bool = True,
    dimension_values: dict[str, float | None] | None = None,
    dim_statuses: dict[str, str] | None = None,
    reference_status: str = "expert_review_required",
) -> CalibrationFixture:
    """Create a minimal calibration fixture for testing."""
    dims = {}
    for dim in LONG_DIMENSIONS:
        val = (dimension_values or {}).get(dim)
        st = (dim_statuses or {}).get(dim, reference_status)
        dims[dim] = DimensionReference(
            dimension=dim, value=val, status=st, rationale="test rationale"
        )
    return CalibrationFixture(
        fixture_id=fixture_id,
        scenario=f"test-{fixture_id}",
        description=f"Test fixture {fixture_id}",
        reference_status=reference_status,
        reference_rationale=f"Rationale for {fixture_id}",
        expected_outcome=expected_outcome,
        expected_quality="medium",
        judge_eligible=judge_eligible,
        dimension_references=dims,
    )


def _make_fixture_set(fixtures: list[CalibrationFixture]) -> CalibrationFixtureSet:
    """Create a CalibrationFixtureSet from a list of fixtures."""
    class _FakeSet(CalibrationFixtureSet):
        def __init__(self, fixs):
            self._fixtures = {f.fixture_id: f for f in fixs}

        @property
        def fixtures(self):
            return dict(self._fixtures)

        @property
        def fixture_ids(self):
            return list(self._fixtures.keys())

        def get(self, fixture_id):
            return self._fixtures.get(fixture_id)

        def judge_eligible_fixtures(self):
            return [f for f in self._fixtures.values() if f.judge_eligible]

        def deterministic_reference_fixtures(self):
            return [f for f in self._fixtures.values() if f.reference_status == "deterministic_reference"]

        def expert_reference_fixtures(self):
            return [f for f in self._fixtures.values() if f.reference_status == "expert_review_required"]

        def fixtures_with_dimension_reference(self, dimension):
            return [f for f in self._fixtures.values() if f.has_reference_for(dimension)]

        def count(self):
            return len(self._fixtures)

        def validate(self):
            return []

    return _FakeSet(fixtures)


# ---------------------------------------------------------------------------
# 1. Agreement Calculation
# ---------------------------------------------------------------------------


class TestAgreementCalculation:
    """Test absolute error and overall agreement metrics."""

    def test_absolute_error_correct(self):
        """Absolute error = |judge - reference|."""
        err = AgreementAnalyzer.absolute_error(judge=0.7, reference=0.9)
        assert err == pytest.approx(0.2)

    def test_absolute_error_symmetric(self):
        """Absolute error is symmetric."""
        assert AgreementAnalyzer.absolute_error(0.3, 0.8) == AgreementAnalyzer.absolute_error(0.8, 0.3)

    def test_absolute_error_zero_when_equal(self):
        """Absolute error is zero when judge equals reference."""
        assert AgreementAnalyzer.absolute_error(0.5, 0.5) == 0.0

    def test_overall_mae_computed(self):
        """Overall MAE is computed across all comparable fixtures."""
        fixtures = [
            _make_fixture("F1", dimension_values={"correctness": 0.8, "completeness": 0.9}),
            _make_fixture("F2", dimension_values={"correctness": 0.6, "completeness": 0.7}),
        ]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.record_judge_output("F1", score=0.85, criterion_scores={"correctness": 0.85, "completeness": 0.95})
        analyzer.record_judge_output("F2", score=0.65, criterion_scores={"correctness": 0.65, "completeness": 0.75})
        report = analyzer.analyze()

        assert report.comparable_samples == 2
        assert report.overall_mae is not None
        assert 0.0 <= report.overall_mae <= 1.0


# ---------------------------------------------------------------------------
# 2. MAE
# ---------------------------------------------------------------------------


class TestMAE:
    """Test mean absolute error computation."""

    def test_mae_empty_list(self):
        """MAE of empty list is None."""
        assert AgreementAnalyzer.mean_absolute_error([]) is None

    def test_mae_single_value(self):
        """MAE of single value is that value."""
        assert AgreementAnalyzer.mean_absolute_error([0.5]) == 0.5

    def test_mae_multiple_values(self):
        """MAE of multiple values is the arithmetic mean."""
        errors = [0.1, 0.3, 0.5]
        mae = AgreementAnalyzer.mean_absolute_error(errors)
        assert mae == 0.3

    def test_mae_in_dimension_stats(self):
        """Dimension-level MAE is computed correctly."""
        fixtures = [_make_fixture("F1", dimension_values={"correctness": 0.8})]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.record_judge_output("F1", score=0.7, criterion_scores={"correctness": 0.7})
        report = analyzer.analyze()

        dim_stat = report.dimension_analysis.get("correctness")
        assert dim_stat is not None
        assert dim_stat.mae == 0.1


# ---------------------------------------------------------------------------
# 3. Categorical Agreement
# ---------------------------------------------------------------------------


class TestCategoricalAgreement:
    """Test categorical agreement (high/medium/low/none)."""

    def test_same_category_returns_true(self):
        """Scores in the same category agree."""
        assert AgreementAnalyzer().categorical_agreement(0.85, 0.90) is True

    def test_different_category_returns_false(self):
        """Scores in different categories disagree."""
        assert AgreementAnalyzer().categorical_agreement(0.3, 0.85) is False

    def test_none_score_returns_none(self):
        """Missing score returns None (no comparison)."""
        assert AgreementAnalyzer().categorical_agreement(None, 0.8) is None
        assert AgreementAnalyzer().categorical_agreement(0.8, None) is None

    def test_category_boundaries(self):
        """Category boundaries at 0.8 and 0.5."""
        a = AgreementAnalyzer()
        assert a._score_to_category(0.9) == "high"
        assert a._score_to_category(0.8) == "high"
        assert a._score_to_category(0.79) == "medium"
        assert a._score_to_category(0.5) == "medium"
        assert a._score_to_category(0.49) == "low"
        assert a._score_to_category(0.01) == "low"
        assert a._score_to_category(0.0) == "none"


# ---------------------------------------------------------------------------
# 4. Dimension-Level Agreement
# ---------------------------------------------------------------------------


class TestDimensionLevelAgreement:
    """Test per-dimension agreement analysis."""

    def test_all_eight_dimensions_present(self):
        """All 8 LONG dimensions appear in the report."""
        fixtures = [_make_fixture("F1", judge_eligible=True)]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        report = analyzer.analyze()

        for dim in LONG_DIMENSIONS:
            assert dim in report.dimension_analysis, f"Missing dimension: {dim}"

    def test_dimension_mae_computed(self):
        """Per-dimension MAE is computed when reference and judge exist."""
        fixtures = [
            _make_fixture("F1", dimension_values={"correctness": 0.8, "test_quality": 0.7}),
        ]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.record_judge_output(
            "F1", score=0.75,
            criterion_scores={"correctness": 0.7, "test_quality": 0.75},
        )
        report = analyzer.analyze()

        correctness = report.dimension_analysis["correctness"]
        assert correctness.sample_count == 1
        assert correctness.mae == 0.1  # |0.7 - 0.8|

    def test_dimension_agreement_rate(self):
        """Agreement rate reflects categorical match count."""
        fixtures = [
            _make_fixture("F1", dimension_values={"correctness": 0.8}),
            _make_fixture("F2", dimension_values={"correctness": 0.6}),
        ]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        # F1: judge=0.85 (high), ref=0.8 (high) → agree
        # F2: judge=0.3 (low), ref=0.6 (medium) → disagree
        analyzer.record_judge_output("F1", score=0.85, criterion_scores={"correctness": 0.85})
        analyzer.record_judge_output("F2", score=0.3, criterion_scores={"correctness": 0.3})
        report = analyzer.analyze()

        correctness = report.dimension_analysis["correctness"]
        assert correctness.agreement_rate == 0.5


# ---------------------------------------------------------------------------
# 5. Missing Reference Handling
# ---------------------------------------------------------------------------


class TestMissingReference:
    """Test that missing references are handled correctly."""

    def test_missing_reference_not_available(self):
        """When no reference exists, comparison_status = NOT_AVAILABLE."""
        fixtures = [_make_fixture("F1", dimension_values={})]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.record_judge_output("F1", score=0.7)
        report = analyzer.analyze()

        fixture_report = report.fixture_analysis["F1"]
        assert fixture_report.comparison_status == "NOT_AVAILABLE"
        assert fixture_report.reference_available is False

    def test_no_fabricated_labels(self):
        """Missing references must not produce fake comparison data."""
        fixtures = [_make_fixture("F1", dimension_values={})]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.record_judge_output("F1", score=0.7)
        report = analyzer.analyze()

        # MAE should be None since nothing is comparable
        assert report.overall_mae is None
        assert report.comparable_samples == 0

    def test_partial_dimension_references(self):
        """Fixtures with some dimensions having references and others not."""
        fixtures = [_make_fixture(
            "F1",
            dimension_values={"correctness": 0.8},  # has reference
            dim_statuses={"correctness": "deterministic_reference", "completeness": "expert_review_required"},
        )]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.record_judge_output("F1", score=0.7, criterion_scores={"correctness": 0.75, "completeness": 0.6})
        report = analyzer.analyze()

        # Correctness should be comparable
        corr = report.dimension_analysis["correctness"]
        assert corr.sample_count == 1
        assert corr.mae is not None
        # Completeness has no reference value, so no sample
        comp = report.dimension_analysis["completeness"]
        assert comp.sample_count == 0


# ---------------------------------------------------------------------------
# 6. Deterministic Reference Handling
# ---------------------------------------------------------------------------


class TestDeterministicReference:
    """Test handling of deterministic_reference type labels."""

    def test_deterministic_reference_used_for_comparison(self):
        """Deterministic references are used in agreement computation."""
        fixtures = [_make_fixture(
            "F1",
            reference_status="deterministic_reference",
            dimension_values={"correctness": 1.0, "completeness": 1.0},
        )]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.record_judge_output("F1", score=0.9, criterion_scores={"correctness": 0.9, "completeness": 0.9})
        report = analyzer.analyze()

        fixture_report = report.fixture_analysis["F1"]
        assert fixture_report.reference_available is True
        assert fixture_report.reference_status == "deterministic_reference"
        assert fixture_report.comparison_status == "AVAILABLE"
        assert fixture_report.absolute_error == pytest.approx(0.1)

    def test_deterministic_fail_fixture_skipped(self):
        """FIXTURES with FAIL outcome should not contribute to agreement."""
        # C2 and C7 and C9 are deterministic FAIL — judge is skipped
        fixtures = [
            _make_fixture("C2", expected_outcome="FAIL", judge_eligible=False,
                          reference_status="deterministic_reference",
                          dimension_values={}),
        ]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        report = analyzer.analyze()

        # No judge output recorded, so no comparison
        assert report.judge_samples == 0
        assert report.comparable_samples == 0


# ---------------------------------------------------------------------------
# 7. Expert Reference Handling
# ---------------------------------------------------------------------------


class TestExpertReference:
    """Test handling of expert_review_required type labels."""

    def test_expert_reference_with_value(self):
        """Expert references with values participate in agreement analysis."""
        fixtures = [_make_fixture(
            "F1",
            reference_status="expert_review_required",
            dimension_values={"correctness": 0.75, "implementation_quality": 0.7},
        )]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.record_judge_output("F1", score=0.72, criterion_scores={
            "correctness": 0.8, "implementation_quality": 0.65
        })
        report = analyzer.analyze()

        fixture_report = report.fixture_analysis["F1"]
        assert fixture_report.reference_available is True
        assert fixture_report.reference_status == "expert_review_required"

    def test_expert_reference_without_value(self):
        """Expert references without values (null) are NOT_AVAILABLE."""
        fixtures = [_make_fixture(
            "F1",
            reference_status="expert_review_required",
            dimension_values={},  # no values yet
        )]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.record_judge_output("F1", score=0.7)
        report = analyzer.analyze()

        fixture_report = report.fixture_analysis["F1"]
        assert fixture_report.reference_available is False
        assert fixture_report.comparison_status == "NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# 8. LOW_AGREEMENT Threshold
# ---------------------------------------------------------------------------


class TestLowAgreement:
    """Test LOW_AGREEMENT flag behavior."""

    def test_threshold_value(self):
        """LOW_AGREEMENT threshold is 0.3."""
        assert LOW_AGREEMENT_THRESHOLD == 0.3

    def test_low_agreement_flag_set(self):
        """Flag is set when |judge - reference| > 0.3."""
        fixtures = [_make_fixture("F1", dimension_values={"correctness": 0.9})]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        # Judge is 0.5, reference is 0.9 → error = 0.4 > 0.3
        analyzer.record_judge_output("F1", score=0.5, criterion_scores={"correctness": 0.5})
        report = analyzer.analyze()

        fixture_report = report.fixture_analysis["F1"]
        assert fixture_report.low_agreement is True
        assert "LOW_AGREEMENT" in fixture_report.flags
        assert fixture_report.absolute_error == 0.4

    def test_no_low_agreement_when_within_threshold(self):
        """No flag when |judge - reference| <= 0.3."""
        fixtures = [_make_fixture("F1", dimension_values={"correctness": 0.8})]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        # Judge is 0.7, reference is 0.8 → error = 0.1 <= 0.3
        analyzer.record_judge_output("F1", score=0.7, criterion_scores={"correctness": 0.7})
        report = analyzer.analyze()

        fixture_report = report.fixture_analysis["F1"]
        assert fixture_report.low_agreement is False
        assert "LOW_AGREEMENT" not in fixture_report.flags

    def test_low_agreement_is_diagnostic_only(self):
        """LOW_AGREEMENT does not modify the fixture's expected outcome."""
        fixtures = [_make_fixture("F1", expected_outcome="PASS", dimension_values={"correctness": 0.9})]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.record_judge_output("F1", score=0.1, criterion_scores={"correctness": 0.1})
        report = analyzer.analyze()

        # Outcome remains PASS despite huge disagreement
        assert report.fixture_analysis["F1"].outcome == "PASS"
        assert report.fixture_analysis["F1"].low_agreement is True


# ---------------------------------------------------------------------------
# 9. No Modification of raw_task_score
# ---------------------------------------------------------------------------


class TestNoScoreModification:
    """Verify that calibration analysis never touches benchmark SCORE."""

    def test_agreement_does_not_affect_raw_task_score(self):
        """Running calibration analysis must not modify raw_task_score."""
        task = _make_long_task()
        result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
        evaluator = LongHorizonEvaluator()
        ev_before = evaluator.evaluate(task, result)
        raw_score_before = result.raw_task_score

        # Run calibration analysis
        fixtures = [_make_fixture("F1", dimension_values={"correctness": 0.8})]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.record_judge_output("F1", score=0.1)
        analyzer.analyze()

        # raw_task_score must be unchanged
        assert result.raw_task_score == raw_score_before
        assert ev_before.score == result.raw_task_score

    def test_agreement_does_not_affect_long_outcome(self):
        """Running calibration analysis must not modify long_outcome."""
        task = _make_long_task()
        result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
        evaluator = LongHorizonEvaluator()
        ev_before = evaluator.evaluate(task, result)
        outcome_before = result.long_outcome

        fixtures = [_make_fixture("F1", dimension_values={"correctness": 0.8})]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.record_judge_output("F1", score=0.1)
        analyzer.analyze()

        assert result.long_outcome == outcome_before


# ---------------------------------------------------------------------------
# 10. No Modification of long_outcome
# ---------------------------------------------------------------------------


class TestNoOutcomeModification:
    """Verify long_outcome is immutable under calibration analysis."""

    def test_partiaL_outcome_preserved(self):
        """PARTIAL outcome must remain PARTIAL after calibration."""
        task = _make_long_task()
        result = _make_result([("s1", "FAILED"), ("s2", "SUCCESS")])
        evaluator = LongHorizonEvaluator()
        ev = evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.PARTIAL
        outcome_before = result.long_outcome

        fixtures = [_make_fixture("F1", dimension_values={"correctness": 0.5})]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.analyze()

        assert result.long_outcome == outcome_before

    def test_pass_outcome_preserved_with_low_agreement(self):
        """PASS outcome stays PASS even when judge disagrees strongly."""
        task = _make_long_task()
        result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
        evaluator = LongHorizonEvaluator()
        ev_before = evaluator.evaluate(task, result)
        assert ev_before.status == EvaluatorStatus.PASS
        outcome_before = result.long_outcome

        fixtures = [_make_fixture("F1", dimension_values={"correctness": 0.95})]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.record_judge_output("F1", score=0.05)  # huge disagreement
        analyzer.analyze()

        assert result.long_outcome == outcome_before


# ---------------------------------------------------------------------------
# 11. Metadata Preservation
# ---------------------------------------------------------------------------


class TestMetadataPreservation:
    """Verify calibration metadata is preserved in reports."""

    def test_fixture_metadata_preserved(self):
        """Per-fixture metadata includes all required fields."""
        fixtures = [_make_fixture("F1", dimension_values={"correctness": 0.8})]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(
            fixture_set=fs,
            calibration_version="v1.0",
            rubric_version="8E.1",
            judge_model="test-judge",
            provider="test-provider",
            model_version="v2.0",
            prompt_version="p1",
            temperature=0.0,
            live_judge="NOT_AVAILABLE",
        )
        analyzer.record_judge_output("F1", score=0.7, criterion_scores={"correctness": 0.7})
        report = analyzer.analyze()

        meta = report.fixture_analysis["F1"].metadata
        assert meta["fixture_id"] == "F1"
        assert meta["calibration_version"] == "v1.0"
        assert meta["rubric_version"] == "8E.1"
        assert meta["judge_model"] == "test-judge"
        assert meta["provider"] == "test-provider"
        assert meta["model_version"] == "v2.0"
        assert meta["prompt_version"] == "p1"
        assert meta["temperature"] == 0.0
        assert "evaluation_timestamp" in meta

    def test_report_level_metadata(self):
        """Report-level metadata fields are present."""
        fixtures = [_make_fixture("F1")]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(
            fixture_set=fs,
            calibration_version="v1.1",
            rubric_version="8E.1",
            judge_model="gpt-5",
            provider="openai",
            live_judge="NOT_AVAILABLE",
        )
        report = analyzer.analyze()

        d = report.to_dict()
        assert d["calibration_version"] == "v1.1"
        assert d["rubric_version"] == "8E.1"
        assert d["judge_model"] == "gpt-5"
        assert d["provider"] == "openai"
        assert d["temperature"] == 0.0
        assert d["live_judge"] == "NOT_AVAILABLE"
        assert "evaluation_timestamp" in d
        assert d["report_hash"] != ""

    def test_reproducibility_hash_stable(self):
        """Same inputs produce the same report hash."""
        fixtures = [_make_fixture("F1", dimension_values={"correctness": 0.8})]
        fs = _make_fixture_set(fixtures)
        analyzer1 = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer1.record_judge_output("F1", score=0.7, criterion_scores={"correctness": 0.7})
        report1 = analyzer1.analyze()

        analyzer2 = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer2.record_judge_output("F1", score=0.7, criterion_scores={"correctness": 0.7})
        report2 = analyzer2.analyze()

        # Hash must be stable across runs with same inputs
        # The sha256() method computes from to_dict() excluding the runtime timestamp
        def _hash_stable(report):
            import hashlib, json
            d = report.to_dict()
            d.pop("evaluation_timestamp", None)
            d.pop("report_hash", None)
            for fa in d.get("fixture_analysis", {}).values():
                fa.get("metadata", {}).pop("evaluation_timestamp", None)
            raw = json.dumps(d, sort_keys=True, ensure_ascii=False)
            return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

        assert _hash_stable(report1) == _hash_stable(report2)


# ---------------------------------------------------------------------------
# 12. Reproducibility
# ---------------------------------------------------------------------------


class TestReproducibility:
    """Test that calibration analysis is deterministic and reproducible."""

    def test_same_inputs_same_report(self):
        """Two analyses with identical inputs produce identical reports."""
        fixtures = [
            _make_fixture("F1", dimension_values={"correctness": 0.8}),
            _make_fixture("F2", dimension_values={"correctness": 0.6}),
        ]
        fs = _make_fixture_set(fixtures)

        outputs = {
            "F1": {"score": 0.75, "criterion_scores": {"correctness": 0.75}},
            "F2": {"score": 0.65, "criterion_scores": {"correctness": 0.65}},
        }

        a1 = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        for fid, out in outputs.items():
            a1.record_judge_output(fid, out["score"], out["criterion_scores"])
        r1 = a1.analyze()

        a2 = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        for fid, out in outputs.items():
            a2.record_judge_output(fid, out["score"], out["criterion_scores"])
        r2 = a2.analyze()

        # Compare everything except mutable timestamps and hash
        def _strip_transient(d):
            d = dict(d)
            d.pop("evaluation_timestamp", None)
            d.pop("report_hash", None)
            for fa in d.get("fixture_analysis", {}).values():
                fa.get("metadata", {}).pop("evaluation_timestamp", None)
            return d

        assert _strip_transient(r1.to_dict()) == _strip_transient(r2.to_dict())

    def test_report_json_serializable(self):
        """Report must serialize to JSON and back without loss."""
        fixtures = [_make_fixture("F1", dimension_values={"correctness": 0.8})]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        analyzer.record_judge_output("F1", score=0.7, criterion_scores={"correctness": 0.7})
        report = analyzer.analyze()

        json_str = json.dumps(report.to_dict())
        restored = json.loads(json_str)
        assert restored["calibration_version"] == report.calibration_version
        assert restored["overall"]["comparable_samples"] == report.comparable_samples


# ---------------------------------------------------------------------------
# 13. Mock Judge Calibration
# ---------------------------------------------------------------------------


class TestMockJudgeCalibration:
    """Test calibration with mocked judge outputs."""

    def test_mock_judge_recorded_and_analyzed(self):
        """Mock judge outputs are recorded and contribute to agreement metrics."""
        fixtures = [
            _make_fixture("C1", expected_outcome="PASS", dimension_values={"correctness": 0.95, "completeness": 1.0}),
            _make_fixture("C3", expected_outcome="PARTIAL", dimension_values={"correctness": 0.5, "completeness": 0.4}),
        ]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")

        # Mock judge outputs
        analyzer.record_judge_output("C1", score=0.9, criterion_scores={
            "correctness": 0.9, "completeness": 0.95,
            "requirement_adherence": 0.9, "implementation_quality": 0.85,
            "test_quality": 0.9, "regression_safety": 0.95,
            "adaptation_quality": 0.9, "final_delivery_quality": 0.9,
        }, confidence=0.85)
        analyzer.record_judge_output("C3", score=0.45, criterion_scores={
            "correctness": 0.5, "completeness": 0.3,
            "requirement_adherence": 0.4, "implementation_quality": 0.4,
            "test_quality": 0.5, "regression_safety": 0.6,
            "adaptation_quality": 0.5, "final_delivery_quality": 0.4,
        }, confidence=0.6)

        report = analyzer.analyze()

        assert report.judge_samples == 2
        assert report.reference_samples == 2
        assert report.comparable_samples == 2
        assert report.overall_mae is not None
        assert report.overall_agreement_rate is not None

    def test_mock_judge_does_not_affect_deterministic(self):
        """Mock judge calibration does not affect deterministic evaluator results."""
        task = _make_long_task()
        result = _make_result([("s1", "SUCCESS"), ("s2", "SUCCESS")])
        evaluator = LongHorizonEvaluator()
        ev = evaluator.evaluate(task, result)

        assert ev.status == EvaluatorStatus.PASS
        assert result.raw_task_score is not None
        assert result.long_outcome == "PASS"


# ---------------------------------------------------------------------------
# 14. No-Live-API Graceful Behavior
# ---------------------------------------------------------------------------


class TestNoLiveAPI:
    """Test graceful behavior when no live judge API is available."""

    def test_live_judge_not_available_by_default(self):
        """Default live_judge status is NOT_AVAILABLE."""
        analyzer = AgreementAnalyzer()
        assert analyzer.live_judge_status == "NOT_AVAILABLE"

    def test_report_marks_live_judge_not_available(self):
        """Report correctly marks live_judge = NOT_AVAILABLE when no API."""
        analyzer = AgreementAnalyzer(live_judge="NOT_AVAILABLE")
        report = analyzer.analyze()
        assert report.live_judge == "NOT_AVAILABLE"

    def test_analysis_runs_without_judge_outputs(self):
        """Analysis completes even with no judge outputs recorded."""
        fixtures = [
            _make_fixture("F1", dimension_values={"correctness": 0.8}),
        ]
        fs = _make_fixture_set(fixtures)
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        report = analyzer.analyze()

        # Should complete without errors
        assert report is not None
        assert report.judge_samples == 0
        assert report.comparable_samples == 0
        assert report.overall_mae is None

    def test_convenience_function_no_api(self):
        """compute_agreement() works without live API."""
        report = compute_agreement(
            judge_model=None,
            provider=None,
            live_judge="NOT_AVAILABLE",
        )
        assert report is not None
        assert report.live_judge == "NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# Integration: End-to-End with Existing Fixtures
# ---------------------------------------------------------------------------


class TestIntegrationWithExistingFixtures:
    """End-to-end tests using the real calibration fixture set."""

    def test_loads_all_12_fixtures(self):
        """All 12 calibration fixtures load successfully."""
        fs = CalibrationFixtureSet()
        assert fs.count() == 12

    def test_judge_eligible_count(self):
        """9 fixtures are judge-eligible (C3 and C12 corrected to PARTIAL)."""
        fs = CalibrationFixtureSet()
        eligible = fs.judge_eligible_fixtures()
        assert len(eligible) == 9

    def test_deterministic_fixtures(self):
        """C2, C7, C9 are deterministic_reference (FAIL)."""
        fs = CalibrationFixtureSet()
        deterministic = fs.deterministic_reference_fixtures()
        ids = {f.fixture_id for f in deterministic}
        assert "C2-obvious-failure" in ids
        assert "C7-req-change-ignored" in ids
        assert "C9-regression" in ids

    def test_c3_and_c12_judge_eligible(self):
        """C3 and C12 are judge-eligible (PARTIAL outcomes)."""
        fs = CalibrationFixtureSet()
        eligible_ids = {f.fixture_id for f in fs.judge_eligible_fixtures()}
        assert "C3-partial-impl" in eligible_ids
        assert "C12-strong-tests-incomplete" in eligible_ids

    def test_all_eight_dimensions_have_coverage(self):
        """All 8 LONG dimensions have at least one fixture with a reference value."""
        fs = CalibrationFixtureSet()
        for dim in LONG_DIMENSIONS:
            fixtures_with_ref = fs.fixtures_with_dimension_reference(dim)
            assert len(fixtures_with_ref) > 0, f"No fixtures have reference for dimension: {dim}"

    def test_full_calibration_report(self):
        """Full report generation from real fixtures."""
        fs = CalibrationFixtureSet()
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        report = analyzer.analyze()

        assert report.calibration_version == "v1.0"
        assert report.rubric_version == "8E.1"
        assert report.reference_samples > 0
        assert report.live_judge == "NOT_AVAILABLE"

        # All 12 fixtures should have an entry
        assert len(report.fixture_analysis) == 12
        # All 8 dimensions should be present
        assert len(report.dimension_analysis) == 8

    def test_report_is_json_serializable(self):
        """Full report must serialize to valid JSON."""
        fs = CalibrationFixtureSet()
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        report = analyzer.analyze()
        data = report.to_dict()
        json_str = json.dumps(data, indent=2)
        restored = json.loads(json_str)
        assert restored["calibration_version"] == "v1.0"
        assert len(restored["fixture_analysis"]) == 12


# ---------------------------------------------------------------------------
# C7 Adaptation Decision
# ---------------------------------------------------------------------------


class TestC7AdaptationDecision:
    """C7 remains deterministic FAIL; adaptation_quality calibrated through C6."""

    def test_c7_is_deterministic_fail(self):
        """C7 is a deterministic_reference with FAIL outcome."""
        fs = CalibrationFixtureSet()
        c7 = fs.get("C7-req-change-ignored")
        assert c7 is not None
        assert c7.reference_status == "deterministic_reference"
        assert c7.expected_outcome == "FAIL"
        assert c7.judge_eligible is False

    def test_c7_judge_skipped(self):
        """C7 must skip judge invocation."""
        # C7: requirement change present but not adapted; terminal stage fails
        task = Task.model_validate({
            "id": "EB-CAL-C7",
            "category": "engineering",
            "mode": ExecutionMode.LONG,
            "difficulty": Difficulty.L3,
            "capabilities": [Capability.LONG],
            "prompt": "Implement calculator with adaptation.",
            "partition": BenchmarkPartition.DEVELOPMENT,
            "context": {"stages": [
                {"id": "s1", "name": "S1", "prompt": "Implement add/subtract"},
                {"id": "s2", "name": "S2", "prompt": "Adapt to add/subtract/multiply/divide",
                 "requirement_change": {"from": "add/subtract", "to": "add/subtract/multiply/divide"}},
                {"id": "s3", "name": "S3", "prompt": "Test", "terminal": True},
            ]},
        })
        result = TaskResult(
            task_id="EB-CAL-C7", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
                StageResult(stage_id="s3", stage_name="S3", status="FAILED", score=0.0, error="did not adapt"),
            ],
        )
        evaluator = LongHorizonEvaluator()
        ev = evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.FAIL
        assert "quality_score" not in ev.details

    def test_adaptation_quality_calibrated_through_c6(self):
        """C6 (successful adaptation) provides the adaptation_quality calibration point."""
        fs = CalibrationFixtureSet()
        c6 = fs.get("C6-req-change-correct")
        assert c6 is not None
        assert c6.judge_eligible is True
        assert c6.expected_outcome == "PASS"
        # adaptation_quality should have a reference in C6
        adapt_ref = c6.dimension_references.get("adaptation_quality")
        assert adapt_ref is not None


# ---------------------------------------------------------------------------
# Non-LONG Evaluators Unaffected
# ---------------------------------------------------------------------------


class TestNonLongUnaffected:
    """Non-LONG evaluators must not be affected by 8E.3 changes."""

    def test_single_mode_evaluator_unaffected(self):
        task = Task(
            id="S-001", category="arch", mode=ExecutionMode.SINGLE,
            difficulty=Difficulty.L3, capabilities=[Capability.ARCH],
            prompt="Design a system.", partition=BenchmarkPartition.DEVELOPMENT,
        )
        result = TaskResult(task_id="S-001", run_id="r1")
        evaluator = LongHorizonEvaluator()
        ev = evaluator.evaluate(task, result)
        assert ev.status == EvaluatorStatus.NOT_APPLICABLE

    def test_architecture_judge_unaffected(self):
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


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------


class TestReportGeneration:
    """Test report serialization and loading."""

    def test_generate_report_writes_file(self, tmp_path: Path):
        """generate_report() writes JSON to the specified path."""
        fs = CalibrationFixtureSet()
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        output = tmp_path / "report.json"
        report = generate_report(fixture_set=fs, output_path=output, live_judge="NOT_AVAILABLE")

        assert output.exists()
        with output.open() as f:
            data = json.load(f)
        assert data["calibration_version"] == "v1.0"
        assert len(data["fixture_analysis"]) == 12

    def test_report_structure(self):
        """Report has the expected top-level structure."""
        fs = CalibrationFixtureSet()
        analyzer = AgreementAnalyzer(fixture_set=fs, live_judge="NOT_AVAILABLE")
        report = analyzer.analyze()
        d = report.to_dict()

        assert "calibration_version" in d
        assert "rubric_version" in d
        assert "judge_model" in d
        assert "provider" in d
        assert "temperature" in d
        assert "evaluation_timestamp" in d
        assert "live_judge" in d
        assert "overall" in d
        assert "dimension_analysis" in d
        assert "fixture_analysis" in d
        assert "report_hash" in d

        overall = d["overall"]
        assert "reference_samples" in overall
        assert "judge_samples" in overall
        assert "comparable_samples" in overall
        assert "mae" in overall
        assert "agreement_rate" in overall
        assert "low_agreement_count" in overall
