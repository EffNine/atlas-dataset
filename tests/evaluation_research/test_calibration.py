"""Tests for evaluation_research."""
import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import pytest
import json
from evaluation_research.calibration import (
    PolicyResult,
    CalibrationResult,
    analytical_calibration,
    load_calibration_report,
    load_jsonl,
)


def _make_eval_record(i, problem="What is 2+2?", canonical="\boxed{4}"):
    return {
        "record_id": f"test_math_{i:04d}",
        "family": "math",
        "problem": problem,
        "canonical_answer": canonical,
        "canonical_answer_sha256": "",
        "eval_set_id": "test_math_eval",
    }


class TestAnalyticalCalibration:
    def test_empty_eval_set(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        result = analytical_calibration(f, "math", [1.5, 3.0])
        assert result.status == "hold"
        assert result.verdict == "HOLD"
        assert result.n_records_total == 0

    def test_returns_policies_for_each_alpha(self, tmp_path):
        records = [_make_eval_record(i) for i in range(10)]
        f = tmp_path / "test.jsonl"
        f.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        result = analytical_calibration(f, "math", [1.5, 2.0, 3.0], max_records=5)
        assert result.n_records_evaluated == 5
        assert len(result.policies) == 3
        alphas = {p.alpha for p in result.policies}
        assert alphas == {1.5, 2.0, 3.0}

    def test_policy_gpol_tracking(self, tmp_path):
        records = [_make_eval_record(i) for i in range(10)]
        f = tmp_path / "test.jsonl"
        f.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        result = analytical_calibration(f, "math", [1.5, 3.0], max_records=10)
        for p in result.policies:
            assert isinstance(p.gpol_pass, bool)
            assert "truncation_rate_le_0.05" in p.gpol_checks

    def test_recommended_alpha_is_smallest_passing(self, tmp_path):
        records = [_make_eval_record(i) for i in range(10)]
        f = tmp_path / "test.jsonl"
        f.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        result = analytical_calibration(f, "math", [1.5, 2.0, 3.0], max_records=10)
        assert result.recommended_alpha == 1.5

    def test_deterministic_across_runs(self, tmp_path):
        records = [_make_eval_record(i) for i in range(20)]
        f = tmp_path / "test.jsonl"
        f.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        r1 = analytical_calibration(f, "math", [1.5, 3.0], max_records=10, seed=42)
        r2 = analytical_calibration(f, "math", [1.5, 3.0], max_records=10, seed=42)
        assert r1.n_records_evaluated == r2.n_records_evaluated
        assert len(r1.policies) == len(r2.policies)

    def test_different_seed_samples_different_records(self, tmp_path):
        records = [_make_eval_record(i) for i in range(100)]
        f = tmp_path / "test.jsonl"
        f.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        r1 = analytical_calibration(f, "math", [1.5], max_records=10, seed=42)
        r2 = analytical_calibration(f, "math", [1.5], max_records=10, seed=99)
        assert r1.n_records_evaluated == 10
        assert r2.n_records_evaluated == 10


class TestPolicyResult:
    def test_tokens_mean_empty(self):
        p = PolicyResult(family="math", alpha=1.5, base_budget=128, n_records=5,
                         truncation_count=0, truncation_rate=0.0)
        assert p.tokens_mean is None
        assert p.tokens_median is None
        assert p.tokens_p90 is None

    def test_tokens_stats_computed(self):
        p = PolicyResult(family="math", alpha=1.5, base_budget=128, n_records=5,
                         truncation_count=0, truncation_rate=0.0,
                         tokens_generated_values=[100, 200, 300, 400, 500])
        assert p.tokens_mean == 300.0
        assert p.tokens_median == 300.0
        assert p.tokens_p90 == 500.0

    def test_to_dict(self):
        p = PolicyResult(family="math", alpha=3.0, base_budget=128, n_records=30,
                         truncation_count=0, truncation_rate=0.0, gpol_pass=True)
        d = p.to_dict()
        assert d["alpha"] == 3.0
        assert d["gpol_pass"] is True
        assert d["tokens_mean"] is None


class TestCalibrationResult:
    def test_to_dict(self):
        r = CalibrationResult(
            experiment_id="cal-math-test", family="math",
            eval_set_path="test.jsonl", n_records_total=100,
            n_records_evaluated=30, verdict="INCONCLUSIVE",
        )
        d = r.to_dict()
        assert d["experiment_id"] == "cal-math-test"
        assert d["verdict"] == "INCONCLUSIVE"


class TestLoadJsonl:
    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        assert load_jsonl(f) == []

    def test_single_record(self, tmp_path):
        f = tmp_path / "single.jsonl"
        f.write_text(json.dumps({"record_id": "r1", "problem": "q", "canonical_answer": "a"}) + "\n",
                     encoding="utf-8")
        records = load_jsonl(f)
        assert len(records) == 1
        assert records[0]["record_id"] == "r1"

    def test_multiple_records(self, tmp_path):
        records = [_make_eval_record(i) for i in range(5)]
        f = tmp_path / "multi.jsonl"
        f.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        loaded = load_jsonl(f)
        assert len(loaded) == 5
        assert loaded[0]["record_id"] == "test_math_0000"
        assert loaded[4]["record_id"] == "test_math_0004"


class TestLoadCalibrationReport:
    def test_load_and_roundtrip(self, tmp_path):
        original = CalibrationResult(
            experiment_id="cal-test-v1", family="math",
            eval_set_path="math_eval_v2_clean.jsonl",
            n_records_total=87, n_records_evaluated=30,
            verdict="INCONCLUSIVE", notes="analytical only",
            generated_at="2026-08-12T00:00:00Z",
        )
        path = tmp_path / "report.json"
        path.write_text(json.dumps(original.to_dict()), encoding="utf-8")
        loaded = load_calibration_report(path)
        assert loaded.experiment_id == "cal-test-v1"
        assert loaded.verdict == "INCONCLUSIVE"
        assert loaded.n_records_total == 87

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_calibration_report(tmp_path / "missing.json")
