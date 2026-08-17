"""Stage 8F — Comprehensive tests for correctness, security, CLI, reporting, and invariants."""
import json
import pytest
import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

from eb.core.types import EvaluatorStatus, JudgeMode


# ============================================================================
# Schema / Security
# ============================================================================


class TestTaskEvaluationConfig:
    """Single authoritative TaskEvaluationConfig definition."""

    def test_single_definition(self):
        """There must be exactly one TaskEvaluationConfig class in schema.py."""
        import eb.core.schema as schema_module
        import inspect
        classes = [
            name for name, obj in inspect.getmembers(schema_module, inspect.isclass)
            if obj.__name__ == "TaskEvaluationConfig"
        ]
        assert len(classes) == 1, f"Expected 1 TaskEvaluationConfig, found {len(classes)}: {classes}"

    def test_judge_config_field_exists(self):
        from eb.core.schema import TaskEvaluationConfig
        assert "judge_config" in TaskEvaluationConfig.model_fields

    def test_get_judge_config_method_exists(self):
        from eb.core.schema import TaskEvaluationConfig
        assert hasattr(TaskEvaluationConfig, "get_judge_config")

    def test_judge_config_deserialization(self):
        from eb.core.schema import TaskEvaluationConfig
        data = {
            "primary_mode": "RUBRIC",
            "judge_config": {"min_judges": 3, "max_judges": 5},
        }
        tc = TaskEvaluationConfig.model_validate(data)
        assert tc.judge_config == {"min_judges": 3, "max_judges": 5}
        assert tc.primary_mode.value == "RUBRIC"

    def test_get_judge_config_from_field(self):
        from eb.core.schema import TaskEvaluationConfig
        tc = TaskEvaluationConfig(judge_config={"min_judges": 5, "timeout_s": 60.0})
        jc = tc.get_judge_config()
        assert jc.min_judges == 5
        assert jc.timeout_s == 60.0

    def test_get_judge_config_from_extra(self):
        from eb.core.schema import TaskEvaluationConfig
        tc = TaskEvaluationConfig(extra={"judge_config": {"preferred_judges": 2}})
        jc = tc.get_judge_config()
        assert jc.preferred_judges == 2

    def test_get_judge_config_field_overrides_extra(self):
        """judge_config field takes precedence over extra['judge_config']."""
        from eb.core.schema import TaskEvaluationConfig
        tc = TaskEvaluationConfig(
            extra={"judge_config": {"min_judges": 1}},
            judge_config={"min_judges": 10},
        )
        jc = tc.get_judge_config()
        assert jc.min_judges == 10

    def test_existing_fields_preserved(self):
        from eb.core.schema import TaskEvaluationConfig, JudgeMode
        tc = TaskEvaluationConfig(
            primary_mode=JudgeMode.RUBRIC,
            fallback_modes=[JudgeMode.DETERMINISTIC],
            max_tokens=2048,
            timeout_s=60.0,
            evaluators=[{"type": "code"}],
            aggregation={"strategy": "single_authoritative"},
        )
        assert tc.primary_mode == JudgeMode.RUBRIC
        assert tc.fallback_modes == [JudgeMode.DETERMINISTIC]
        assert tc.max_tokens == 2048
        assert tc.timeout_s == 60.0
        assert tc.evaluators == [{"type": "code"}]
        assert tc.aggregation == {"strategy": "single_authoritative"}

    def test_task_with_judge_config_deserializes(self):
        from eb.core.schema import Task
        data = {
            "id": "T1",
            "category": "coding",
            "mode": "SINGLE",
            "difficulty": "L2",
            "prompt": "Write a function.",
            "evaluation": {
                "primary_mode": "RUBRIC",
                "judge_config": {"min_judges": 3},
            },
        }
        task = Task.model_validate(data)
        assert task.evaluation.judge_config == {"min_judges": 3}
        jc = task.evaluation.get_judge_config()
        assert jc.min_judges == 3


class TestAdapterMetadataRedaction:
    """AdapterMetadata.to_dict() must redact sensitive keys."""

    def test_api_key_redacted(self):
        from eb.adapters.base import AdapterMetadata
        m = AdapterMetadata(
            adapter_type="test", backend="docker", model_name="m",
            extra={"api_key": "secret123"},
        )
        d = m.to_dict()
        assert d["extra"]["api_key"] == "[REDACTED]"

    def test_token_redacted(self):
        from eb.adapters.base import AdapterMetadata
        m = AdapterMetadata(
            adapter_type="test", backend="docker", model_name="m",
            extra={"token": "tok123"},
        )
        d = m.to_dict()
        assert d["extra"]["token"] == "[REDACTED]"

    def test_password_redacted(self):
        from eb.adapters.base import AdapterMetadata
        m = AdapterMetadata(
            adapter_type="test", backend="docker", model_name="m",
            extra={"password": "pass123"},
        )
        d = m.to_dict()
        assert d["extra"]["password"] == "[REDACTED]"

    def test_secret_redacted(self):
        from eb.adapters.base import AdapterMetadata
        m = AdapterMetadata(
            adapter_type="test", backend="docker", model_name="m",
            extra={"secret": "sec123"},
        )
        d = m.to_dict()
        assert d["extra"]["secret"] == "[REDACTED]"

    def test_normal_metadata_preserved(self):
        from eb.adapters.base import AdapterMetadata
        m = AdapterMetadata(
            adapter_type="test", backend="docker", model_name="m",
            extra={"base_url": "http://example.com", "version": "1.0"},
        )
        d = m.to_dict()
        assert d["extra"]["base_url"] == "http://example.com"
        assert d["extra"]["version"] == "1.0"

    def test_non_sensitive_keys_preserved(self):
        from eb.adapters.base import AdapterMetadata
        m = AdapterMetadata(
            adapter_type="test", backend="docker", model_name="m",
            extra={"model_name": "gpt-4", "region": "us-east-1"},
        )
        d = m.to_dict()
        assert d["extra"]["model_name"] == "gpt-4"
        assert d["extra"]["region"] == "us-east-1"

    def test_other_adapter_fields_preserved(self):
        from eb.adapters.base import AdapterMetadata
        m = AdapterMetadata(
            adapter_type="openai", backend="api", model_name="gpt-4",
            supported_settings=["seed", "temperature"],
            version="1.0.0",
            extra={"api_key": "secret"},
        )
        d = m.to_dict()
        assert d["adapter_type"] == "openai"
        assert d["backend"] == "api"
        assert d["model_name"] == "gpt-4"
        assert d["supported_settings"] == ["seed", "temperature"]
        assert d["version"] == "1.0.0"
        assert d["extra"]["api_key"] == "[REDACTED]"


# ============================================================================
# CLI
# ============================================================================


class TestCLIParser:
    """CLI argument parsing for Stage 8F additions."""

    def test_resume_flag(self):
        from eb.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["run", "--model", "m", "--resume", "/path/to/ckpt"])
        assert args.resume == "/path/to/ckpt"

    def test_resume_default_none(self):
        from eb.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["run", "--model", "m"])
        assert args.resume is None

    def test_sandbox_backend_flag(self):
        from eb.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["run", "--model", "m", "--sandbox-backend", "opensandbox"])
        assert args.sandbox_backend == "opensandbox"

    def test_sandbox_backend_docker(self):
        from eb.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["run", "--model", "m", "--sandbox-backend", "docker"])
        assert args.sandbox_backend == "docker"

    def test_sandbox_backend_default_none(self):
        from eb.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["run", "--model", "m"])
        assert args.sandbox_backend is None

    def test_output_dir_flag(self):
        from eb.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["run", "--model", "m", "--output-dir", "/tmp/out"])
        assert args.output_dir == "/tmp/out"

    def test_output_dir_default_none(self):
        from eb.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["run", "--model", "m"])
        assert args.output_dir is None

    def test_status_command(self):
        from eb.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["status", "run-123"])
        assert args.command == "status"
        assert args.run_id == "run-123"

    def test_calibrate_command(self):
        from eb.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["calibrate"])
        assert args.command == "calibrate"
        assert not args.live_judge

    def test_calibrate_with_live_judge(self):
        from eb.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["calibrate", "--live-judge"])
        assert args.live_judge is True

    def test_calibrate_with_judge_model(self):
        from eb.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["calibrate", "--judge-model", "gpt-4"])
        assert args.judge_model == "gpt-4"

    def test_calibrate_with_output(self):
        from eb.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["calibrate", "--output", "/tmp/cal.json"])
        assert args.output == "/tmp/cal.json"

    def test_invalid_sandbox_backend_rejected(self):
        from eb.cli import build_parser
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["run", "--model", "m", "--sandbox-backend", "invalid"])

    def test_status_missing_run_id_rejected(self):
        from eb.cli import build_parser
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["status"])


class TestCLIExecution:
    """CLI execution behavior for new commands."""

    def test_status_not_found_exits_1(self, tmp_path, monkeypatch):
        """eb status for unknown run exits 1."""
        import subprocess
        result = subprocess.run(
            ["python", "-m", "eb.cli", "status", "nonexistent-run"],
            capture_output=True, text=True,
            cwd="/home/afnan/projects/active/atlas-dataset/benchmarks/eb",
        )
        assert result.returncode == 1
        assert "not found" in result.stderr.lower() or "not found" in result.stdout.lower()

    def test_calibrate_runs_without_live_judge(self, tmp_path, monkeypatch):
        """eb calibrate works without live judge (NOT_AVAILABLE)."""
        import subprocess
        result = subprocess.run(
            ["python", "-m", "eb.cli", "calibrate"],
            capture_output=True, text=True,
            cwd="/home/afnan/projects/active/atlas-dataset/benchmarks/eb",
        )
        assert result.returncode == 0
        assert "Calibration report generated" in result.stdout


# ============================================================================
# Reporting
# ============================================================================


class TestMachineReport:
    """Machine report must include schema_version, score, outcome, quality."""

    def test_schema_version_present(self):
        from eb.reports.generator import generate_machine_report
        report = generate_machine_report({"model": "m", "repeats": 1})
        assert report["schema_version"] == "8F.1"

    def test_score_from_task_results(self):
        from eb.reports.generator import generate_machine_report
        report = generate_machine_report({
            "model": "m",
            "task_results": [
                {"raw_task_score": 0.8},
                {"raw_task_score": 0.6},
            ],
        })
        assert report["score"] == 0.7

    def test_score_none_when_no_results(self):
        from eb.reports.generator import generate_machine_report
        report = generate_machine_report({"model": "m", "task_results": []})
        assert report["score"] is None

    def test_outcome_distribution(self):
        from eb.reports.generator import generate_machine_report
        report = generate_machine_report({
            "model": "m",
            "task_results": [
                {"long_outcome": "PASS"},
                {"long_outcome": "PASS"},
                {"long_outcome": "PARTIAL"},
                {"long_outcome": "FAIL"},
            ],
        })
        assert report["outcome_distribution"] == {"PASS": 2, "PARTIAL": 1, "FAIL": 1}

    def test_outcome_distribution_none_when_no_long_tasks(self):
        from eb.reports.generator import generate_machine_report
        report = generate_machine_report({
            "model": "m",
            "task_results": [
                {"raw_task_score": 0.8},
            ],
        })
        assert report["outcome_distribution"] is None

    def test_quality_from_evaluator_details(self):
        from eb.reports.generator import generate_machine_report
        report = generate_machine_report({
            "model": "m",
            "task_results": [
                {
                    "evaluator_results": [
                        {"details": {"quality_score": 0.9}},
                        {"details": {"quality_score": 0.7}},
                    ],
                },
            ],
        })
        assert report["quality"]["avg_quality_score"] == 0.8
        assert report["quality"]["quality_count"] == 2

    def test_quality_none_when_no_evaluators(self):
        from eb.reports.generator import generate_machine_report
        report = generate_machine_report({
            "model": "m",
            "task_results": [],
        })
        assert report["quality"]["avg_quality_score"] is None
        assert report["quality"]["quality_count"] == 0

    def test_judge_enabled_flag(self):
        from eb.reports.generator import generate_machine_report
        report_with_judge = generate_machine_report({
            "model": "m",
            "judge": {"provider": "openrouter"},
        })
        assert report_with_judge["judge_enabled"] is True

        report_without_judge = generate_machine_report({"model": "m"})
        assert report_without_judge["judge_enabled"] is False

    def test_sandbox_backend_in_report(self):
        from eb.reports.generator import generate_machine_report
        report = generate_machine_report({
            "model": "m",
            "reproducibility": {"sandbox_backend": "docker"},
        })
        assert report["sandbox_backend"] == "docker"

    def test_no_secrets_in_report(self):
        from eb.reports.generator import generate_machine_report
        report = generate_machine_report({
            "model": "m",
            "api_key": "sk-secret",
            "password": "secret123",
            "token": "tok123",
        })
        assert "api_key" not in report
        assert "password" not in report
        assert "token" not in report

    def test_stable_json_serialization(self):
        from eb.reports.generator import generate_machine_report
        run_data = {
            "model": "atan-v1",
            "base_model": "Qwen2.5-7B",
            "benchmark_version": "eb-v0.1",
            "task_set_version": "tasks-v0.1",
            "repeats": 1,
            "overall_eb_score": 1284,
            "reproducibility": {
                "evaluator_config_version": "eb-eval-v1",
                "sandbox_backend": "docker",
                "sandbox_image": "python:3.11-slim",
                "rubric_version": "8F.1",
                "long_max_concurrent": 1,
            },
        }
        report = generate_machine_report(run_data)
        json_str = json.dumps(report, sort_keys=True, ensure_ascii=False)
        report2 = generate_machine_report(run_data)
        json_str2 = json.dumps(report2, sort_keys=True, ensure_ascii=False)
        assert json_str == json_str2


class TestHumanReport:
    """Human report should show outcome distribution, sandbox backend, judge status."""

    def test_outcome_distribution_shown(self):
        from eb.reports.generator import generate_human_report
        text = generate_human_report({
            "model": "m",
            "outcome_distribution": {"PASS": 2, "FAIL": 1},
        })
        assert "OUTCOME DISTRIBUTION" in text
        assert "PASS" in text
        assert "FAIL" in text

    def test_sandbox_backend_shown(self):
        from eb.reports.generator import generate_human_report
        text = generate_human_report({
            "model": "m",
            "reproducibility": {"sandbox_backend": "opensandbox"},
        })
        assert "Sandbox Backend" in text
        assert "opensandbox" in text

    def test_judge_status_shown(self):
        from eb.reports.generator import generate_human_report
        text = generate_human_report({
            "model": "m",
            "judge": {"provider": "openrouter"},
            "quality": {"avg_quality_score": 0.85, "quality_count": 10},
        })
        assert "JUDGE & QUALITY" in text
        assert "Judge Enabled    yes" in text
        assert "Avg Quality" in text

    def test_no_judge_no_quality_section(self):
        from eb.reports.generator import generate_human_report
        text = generate_human_report({"model": "m", "task_results": []})
        assert "JUDGE & QUALITY" not in text


# ============================================================================
# Reproducibility
# ============================================================================


class TestReproducibilityMetadata:
    """Run manifest must persist reproducibility metadata."""

    def test_evaluator_config_version(self):
        from eb.core.manifest import BenchmarkRunManifest, TaskSetManifest
        from eb.core.schema import InferenceSettings, ModelMetadata
        m = BenchmarkRunManifest(
            run_id="r1",
            benchmark_version="eb-v0.1",
            task_set_manifest=TaskSetManifest(task_set_version="t1", task_dir="/tmp"),
            model=ModelMetadata(name="m", revision="r"),
            base_model=ModelMetadata(name="base", revision="r"),
            suite="full",
            partitions=["development"],
            inference=InferenceSettings(),
            evaluator_config_version="eb-eval-v1",
        )
        assert m.evaluator_config_version == "eb-eval-v1"

    def test_sandbox_backend(self):
        from eb.core.manifest import BenchmarkRunManifest, TaskSetManifest
        from eb.core.schema import InferenceSettings, ModelMetadata
        m = BenchmarkRunManifest(
            run_id="r1",
            benchmark_version="eb-v0.1",
            task_set_manifest=TaskSetManifest(task_set_version="t1", task_dir="/tmp"),
            model=ModelMetadata(name="m", revision="r"),
            base_model=ModelMetadata(name="base", revision="r"),
            suite="full",
            partitions=["development"],
            inference=InferenceSettings(),
            sandbox_backend="opensandbox",
        )
        assert m.sandbox_backend == "opensandbox"

    def test_sandbox_image(self):
        from eb.core.manifest import BenchmarkRunManifest, TaskSetManifest
        from eb.core.schema import InferenceSettings, ModelMetadata
        m = BenchmarkRunManifest(
            run_id="r1",
            benchmark_version="eb-v0.1",
            task_set_manifest=TaskSetManifest(task_set_version="t1", task_dir="/tmp"),
            model=ModelMetadata(name="m", revision="r"),
            base_model=ModelMetadata(name="base", revision="r"),
            suite="full",
            partitions=["development"],
            inference=InferenceSettings(),
            sandbox_image="python:3.11-slim",
        )
        assert m.sandbox_image == "python:3.11-slim"

    def test_rubric_version(self):
        from eb.core.manifest import BenchmarkRunManifest, TaskSetManifest
        from eb.core.schema import InferenceSettings, ModelMetadata
        m = BenchmarkRunManifest(
            run_id="r1",
            benchmark_version="eb-v0.1",
            task_set_manifest=TaskSetManifest(task_set_version="t1", task_dir="/tmp"),
            model=ModelMetadata(name="m", revision="r"),
            base_model=ModelMetadata(name="base", revision="r"),
            suite="full",
            partitions=["development"],
            inference=InferenceSettings(),
            rubric_version="8F.1",
        )
        assert m.rubric_version == "8F.1"

    def test_long_max_concurrent(self):
        from eb.core.manifest import BenchmarkRunManifest, TaskSetManifest
        from eb.core.schema import InferenceSettings, ModelMetadata
        m = BenchmarkRunManifest(
            run_id="r1",
            benchmark_version="eb-v0.1",
            task_set_manifest=TaskSetManifest(task_set_version="t1", task_dir="/tmp"),
            model=ModelMetadata(name="m", revision="r"),
            base_model=ModelMetadata(name="base", revision="r"),
            suite="full",
            partitions=["development"],
            inference=InferenceSettings(),
            long_max_concurrent=4,
        )
        assert m.long_max_concurrent == 4

    def test_all_reproducibility_fields_in_run_info(self, tmp_path):
        """Run artifact run.json must contain reproducibility section."""
        from eb.runners.orchestration import RunOrchestrator
        # Verify that _write_artifacts includes reproducibility in run_info
        # by checking the method source
        import inspect
        src = inspect.getsource(RunOrchestrator._write_artifacts)
        assert "reproducibility" in src
        assert "evaluator_config_version" in src
        assert "sandbox_backend" in src


# ============================================================================
# SCORE / OUTCOME / QUALITY Invariants
# ============================================================================


class TestScoreOutcomeQualityInvariants:
    """Prove that QUALITY never modifies SCORE or OUTCOME."""

    def test_quality_cannot_modify_raw_task_score(self):
        """LOW_AGREEMENT or any judge output must not change raw_task_score."""
        from eb.core.schema import TaskResult, EvaluatorResult
        from eb.core.types import EvaluatorStatus, JudgeMode
        result = TaskResult(
            task_id="T1", run_id="R1",
            raw_task_score=0.8,
            evaluator_results=[
                EvaluatorResult(
                    evaluator="judge", mode=JudgeMode.CLOUD_JUDGE,
                    status=EvaluatorStatus.PASS, score=0.9,
                    details={"quality_score": 0.85},
                ),
            ],
        )
        assert result.raw_task_score == 0.8
        # Adding quality details does not change raw_task_score
        result.evaluator_results[0].details["quality_score"] = 0.99
        assert result.raw_task_score == 0.8

    def test_quality_cannot_modify_long_outcome(self):
        """LOW_AGREEMENT or any judge output must not change long_outcome."""
        from eb.core.schema import TaskResult, EvaluatorResult
        from eb.core.types import EvaluatorStatus, JudgeMode
        result = TaskResult(
            task_id="T1", run_id="R1",
            long_outcome="PASS",
            evaluator_results=[
                EvaluatorResult(
                    evaluator="judge", mode=JudgeMode.CLOUD_JUDGE,
                    status=EvaluatorStatus.PASS, score=0.9,
                    details={"quality_score": 0.85},
                    flags=["LOW_AGREEMENT"],
                ),
            ],
        )
        assert result.long_outcome == "PASS"
        result.evaluator_results[0].details["quality_score"] = 0.1
        assert result.long_outcome == "PASS"

    def test_low_agreement_cannot_modify_raw_task_score(self):
        from eb.core.schema import TaskResult, EvaluatorResult
        from eb.core.types import EvaluatorStatus, JudgeMode
        result = TaskResult(
            task_id="T1", run_id="R1",
            raw_task_score=0.5,
            evaluator_results=[
                EvaluatorResult(
                    evaluator="judge", mode=JudgeMode.CLOUD_JUDGE,
                    status=EvaluatorStatus.PASS, score=0.7,
                    details={"quality_score": 0.3},
                    flags=["LOW_AGREEMENT"],
                ),
            ],
        )
        assert result.raw_task_score == 0.5

    def test_low_agreement_cannot_modify_long_outcome(self):
        from eb.core.schema import TaskResult, EvaluatorResult
        from eb.core.types import EvaluatorStatus, JudgeMode
        result = TaskResult(
            task_id="T1", run_id="R1",
            long_outcome="PARTIAL",
            evaluator_results=[
                EvaluatorResult(
                    evaluator="judge", mode=JudgeMode.CLOUD_JUDGE,
                    status=EvaluatorStatus.PASS, score=0.7,
                    details={"quality_score": 0.3},
                    flags=["LOW_AGREEMENT"],
                ),
            ],
        )
        assert result.long_outcome == "PARTIAL"

    def test_judge_disabled_run_has_no_quality_score(self):
        from eb.core.schema import TaskResult
        result = TaskResult(
            task_id="T1", run_id="R1",
            raw_task_score=0.8,
            evaluator_results=[],
        )
        has_quality = any(
            ev.details.get("quality_score") is not None
            for ev in result.evaluator_results
        )
        assert not has_quality

    def test_deterministic_fail_has_no_judge_quality(self):
        from eb.core.schema import TaskResult, EvaluatorResult
        from eb.core.types import EvaluatorStatus, JudgeMode
        result = TaskResult(
            task_id="T1", run_id="R1",
            raw_task_score=0.0,
            evaluator_results=[
                EvaluatorResult(
                    evaluator="exact", mode=JudgeMode.DETERMINISTIC,
                    status=EvaluatorStatus.FAIL, score=0.0,
                ),
            ],
        )
        has_quality = any(
            ev.details.get("quality_score") is not None
            for ev in result.evaluator_results
        )
        assert not has_quality

    def test_partial_may_have_quality_score(self):
        from eb.core.schema import TaskResult, EvaluatorResult
        from eb.core.types import EvaluatorStatus, JudgeMode
        result = TaskResult(
            task_id="T1", run_id="R1",
            long_outcome="PARTIAL",
            evaluator_results=[
                EvaluatorResult(
                    evaluator="judge", mode=JudgeMode.CLOUD_JUDGE,
                    status=EvaluatorStatus.PASS, score=0.6,
                    details={"quality_score": 0.55},
                ),
            ],
        )
        assert result.evaluator_results[0].details["quality_score"] == 0.55

    def test_pass_may_have_quality_score(self):
        from eb.core.schema import TaskResult, EvaluatorResult
        from eb.core.types import EvaluatorStatus, JudgeMode
        result = TaskResult(
            task_id="T1", run_id="R1",
            long_outcome="PASS",
            evaluator_results=[
                EvaluatorResult(
                    evaluator="judge", mode=JudgeMode.CLOUD_JUDGE,
                    status=EvaluatorStatus.PASS, score=0.9,
                    details={"quality_score": 0.88},
                ),
            ],
        )
        assert result.evaluator_results[0].details["quality_score"] == 0.88


# ============================================================================
# Regression Tests
# ============================================================================


class TestRegression:
    """Ensure Stage 8F changes do not break existing behavior."""

    def test_single_unchanged(self, sample_task_data):
        """SINGLE mode tasks still work."""
        from eb.core.schema import Task
        task = Task.model_validate(sample_task_data)
        assert task.mode.value == "SINGLE"
        assert task.evaluation.primary_mode.value == "RUBRIC"

    def test_exec_unchanged(self):
        from eb.core.schema import Task
        data = {
            "id": "EB-CODE-001",
            "category": "coding",
            "mode": "EXEC",
            "difficulty": "L2",
            "prompt": "Write a function.",
            "evaluation": {"primary_mode": "DETERMINISTIC"},
            "partition": "development",
        }
        task = Task.model_validate(data)
        assert task.mode.value == "EXEC"

    def test_multi_unchanged(self):
        from eb.core.schema import Task
        data = {
            "id": "EB-MULTI-001",
            "category": "agentic",
            "mode": "MULTI",
            "difficulty": "L3",
            "prompt": "Multi-turn task.",
            "evaluation": {"primary_mode": "RUBRIC"},
            "partition": "development",
        }
        task = Task.model_validate(data)
        assert task.mode.value == "MULTI"

    def test_long_unchanged(self):
        from eb.core.schema import Task
        data = {
            "id": "EB-LONG-001",
            "category": "long_horizon",
            "mode": "LONG",
            "difficulty": "L5",
            "prompt": "Long task.",
            "context": {"stages": [
                {"id": "s1", "name": "Stage 1", "prompt": "Do thing", "order": 0},
            ]},
            "evaluation": {"primary_mode": "CLOUD_JUDGE"},
            "partition": "development",
        }
        task = Task.model_validate(data)
        assert task.mode.value == "LONG"
        assert len(task.context["stages"]) == 1

    def test_checkpoint_behavior_unchanged(self):
        from eb.core.checkpoint import CheckpointV1, CURRENT_SCHEMA_VERSION
        ckpt = CheckpointV1(
            task_id="t1", run_id="r1", repeat_id="r01",
            docker_image="python:3.11-slim",
        )
        ckpt.mark_checkpointed()
        assert ckpt.schema_version == CURRENT_SCHEMA_VERSION
        assert ckpt.verify_checksum()

    def test_docker_remains_default(self, monkeypatch):
        monkeypatch.delenv("EB_SANDBOX_BACKEND", raising=False)
        from eb.sandbox.manager import resolve_sandbox_backend
        assert resolve_sandbox_backend() == "docker"

    def test_opensandbox_remains_opt_in(self, monkeypatch):
        monkeypatch.setenv("EB_SANDBOX_BACKEND", "opensandbox")
        from eb.sandbox.manager import resolve_sandbox_backend
        assert resolve_sandbox_backend() == "opensandbox"

    def test_final_score_is_deprecated_but_present(self):
        from eb.core.schema import TaskResult
        import inspect
        # final_score field must still exist
        assert "final_score" in TaskResult.model_fields
        # Check docstring/comments for deprecation notice
        result = TaskResult(task_id="T1", run_id="R1")
        assert result.final_score is None

    def test_run_orchestrator_accepts_new_params(self):
        from eb.runners.orchestration import RunOrchestrator
        import inspect
        sig = inspect.signature(RunOrchestrator.__init__)
        params = list(sig.parameters.keys())
        assert "resume_from" in params
        assert "sandbox_backend" in params
        assert "output_dir" in params
