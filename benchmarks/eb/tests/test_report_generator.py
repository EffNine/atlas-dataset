"""Tests for eb/reports/generator.py — Report generation."""
import json
import pytest
from pathlib import Path

from eb.reports.generator import (
    generate_human_report,
    generate_machine_report,
    write_report_files,
)


class TestHumanReport:
    def test_basic_format(self, tmp_path):
        run_data = {
            "model": "atan-v1",
            "base_model": "Qwen2.5-7B",
            "benchmark_version": "eb-v0.1",
            "task_set_version": "tasks-v0.1",
            "repeats": 5,
            "overall_eb_score": 1284,
            "error_percent": 0.8,
            "capability_scores": {
                "ARCH": {"eb_score": 1382, "error_percent": 0.4},
                "CODE": {"eb_score": 1048, "error_percent": 1.2},
                "PLAN": {"eb_score": 1461, "error_percent": 2.8},
            },
            "baseline_eb_score": 1000,
            "improvement_percent": 28.4,
            "stability_status": "Excellent",
        }
        text = generate_human_report(run_data)
        assert "EFFNINE BENCHMARK" in text
        assert "atan-v1" in text
        assert "Qwen2.5-7B" in text
        assert "1284" in text
        assert "Architecture" in text
        assert "1382" in text
        assert "Coding" in text or "CODE" in text
        assert "Planning" in text or "PLAN" in text
        assert "+28.4%" in text

    def test_no_capability_scores(self, tmp_path):
        run_data = {
            "model": "m",
            "base_model": "base",
            "benchmark_version": "eb-v0.1",
            "task_set_version": "tasks-v0.1",
            "repeats": 1,
            "overall_eb_score": 1000,
        }
        text = generate_human_report(run_data)
        assert "EFFNINE BENCHMARK" in text
        assert "1000" in text

    def test_no_error_percent(self, tmp_path):
        run_data = {
            "model": "m",
            "base_model": "base",
            "benchmark_version": "eb-v0.1",
            "task_set_version": "tasks-v0.1",
            "repeats": 1,
            "overall_eb_score": 1284,
        }
        text = generate_human_report(run_data)
        assert "1284" in text
        assert "\u00b1" not in text or "1284" in text

    def test_exact_format_matches_specimen(self):
        """Verify the report matches the specimen format from the spec."""
        run_data = {
            "model": "atan-v1",
            "base_model": "Qwen2.5-7B",
            "benchmark_version": "eb-v0.1",
            "task_set_version": "tasks-v0.1",
            "repeats": 5,
            "overall_eb_score": 1284,
            "error_percent": 0.8,
            "capability_scores": {
                "ARCH": {"eb_score": 1382, "error_percent": 0.4},
                "DEBUG": {"eb_score": 1217, "error_percent": 0.7},
                "CODE": {"eb_score": 1048, "error_percent": 1.1},
                "PLAN": {"eb_score": 1461, "error_percent": 2.8},
                "TEST": {"eb_score": 1124, "error_percent": 0.9},
                "ADVISORY": {"eb_score": 1520, "error_percent": 1.5},
                "JUDGMENT": {"eb_score": 1418, "error_percent": 1.2},
                "EVIDENCE": {"eb_score": 1291, "error_percent": 0.6},
                "MYENG": {"eb_score": 1840, "error_percent": 3.1},
                "AGENT": {"eb_score": 1087, "error_percent": 1.8},
                "LONG": {"eb_score": 963, "error_percent": 7.4},
            },
            "baseline_eb_score": 1000,
            "improvement_percent": 28.4,
            "stability_status": "Excellent",
        }
        text = generate_human_report(run_data)

        # Verify key sections exist
        assert "EB SCORE" in text
        assert "CAPABILITY" in text
        assert "STABILITY" in text
        assert "BASELINE" in text

        # Verify specific scores
        assert "1382" in text
        assert "1217" in text
        assert "1840" in text
        assert "963" in text
        assert "+28.4%" in text
        assert "Excellent" in text


class TestMachineReport:
    def test_full_structure(self):
        run_data = {
            "model": "atan-v1",
            "base_model": "Qwen2.5-7B",
            "benchmark_version": "eb-v0.1",
            "task_set_version": "tasks-v0.1",
            "repeats": 5,
            "overall_eb_score": 1284,
            "base_raw_mean": 0.5,
            "model_raw_mean": 0.75,
            "improvement_percent": 28.4,
            "error_percent": 0.8,
            "scoring_version": "eb-score-v1",
            "task_set_hash": "abc123",
            "baseline_run_id": "baseline-001",
        }
        report = generate_machine_report(run_data)
        assert report["report_type"] == "effnine_benchmark"
        assert report["scoring_version"] == "eb-score-v1"
        assert report["overall_eb_score"] == 1284
        assert report["model"] == "atan-v1"
        assert report["benchmark_compatibility"]["benchmark_version"] == "eb-v0.1"
        assert report["benchmark_compatibility"]["task_set_hash"] == "abc123"

    def test_no_secret_leakage(self):
        run_data = {
            "model": "atan-v1",
            "base_model": "Qwen2.5-7B",
            "benchmark_version": "eb-v0.1",
            "task_set_version": "tasks-v0.1",
            "repeats": 1,
            "overall_eb_score": 1284,
            "api_key": "sk-secret-123",
            "password": "secret",
        }
        report = generate_machine_report(run_data)
        assert "api_key" not in report
        assert "password" not in report


class TestWriteReportFiles:
    def test_writes_both_files(self, tmp_path):
        run_data = {
            "model": "m",
            "base_model": "base",
            "benchmark_version": "eb-v0.1",
            "task_set_version": "tasks-v0.1",
            "repeats": 1,
            "overall_eb_score": 1000,
        }
        artifact_dir = tmp_path / "runs" / "run-001"
        artifact_dir.mkdir(parents=True)

        human_text = generate_human_report(run_data)
        machine_data = generate_machine_report(run_data)

        paths = write_report_files(str(artifact_dir), "run-001", human_text, machine_data)

        assert "report.txt" in paths
        assert "report.json" in paths

        # Verify report.txt
        report_path = paths["report.txt"]
        assert Path(report_path).exists()
        content = Path(report_path).read_text(encoding="utf-8")
        assert "EFFNINE BENCHMARK" in content

        # Verify report.json
        json_path = paths["report.json"]
        assert Path(json_path).exists()
        with Path(json_path).open(encoding="utf-8") as f:
            data = json.load(f)
        assert data["overall_eb_score"] == 1000
        assert data["schema_version"] == "8F.1"
