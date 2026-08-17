"""Tests for eb/cli.py — CLI argument parsing."""
import pytest
import argparse

from eb.cli import build_parser, main, VERSION


class TestBuildParser:
    def test_parser_creates(self):
        parser = build_parser()
        assert parser.prog == "eb"

    def test_run_command_exists(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--model", "test-model"])
        assert args.command == "run"
        assert args.model == "test-model"
        assert args.suite == "full"
        assert args.repeats == 1

    def test_run_required_model(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["run"])

    def test_run_default_values(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--model", "m"])
        assert args.seed == 42
        assert args.temperature == 0.0
        assert args.top_p == 1.0
        assert args.top_k == 0
        assert args.max_tokens == 4096
        assert args.context_length == 8192

    def test_run_custom_values(self):
        parser = build_parser()
        args = parser.parse_args([
            "run", "--model", "m", "--repeats", "5",
            "--temperature", "0.7", "--seed", "99",
        ])
        assert args.repeats == 5
        assert args.temperature == 0.7
        assert args.seed == 99

    def test_compare_command(self):
        parser = build_parser()
        args = parser.parse_args(["compare", "model-a", "model-b"])
        assert args.command == "compare"
        assert args.runs == ["model-a", "model-b"]

    def test_report_command(self):
        parser = build_parser()
        args = parser.parse_args(["report", "--run-id", "run-123"])
        assert args.command == "report"
        assert args.run_id == "run-123"

    def test_version_flag(self):
        parser = build_parser()
        assert VERSION == "0.5.0"


class TestCLIExecution:
    def test_run_fails_with_unknown_model(self):
        """Running with an unknown model should fail with a clear error."""
        import subprocess
        result = subprocess.run(
            ["python", "-m", "eb.cli", "run", "--model", "nonexistent-model"],
            capture_output=True, text=True,
            cwd="/home/afnan/projects/active/atlas-dataset/benchmarks/eb",
        )
        assert result.returncode != 0
        assert "unknown model" in result.stderr.lower() or "valueerror" in result.stderr.lower()

    def test_compare_fails_with_implementation_not_ready(self):
        import subprocess
        result = subprocess.run(
            ["python", "-m", "eb.cli", "compare", "m1", "m2"],
            capture_output=True, text=True,
            cwd="/home/afnan/projects/active/atlas-dataset/benchmarks/eb",
        )
        assert result.returncode != 0

    def test_report_fails_with_implementation_not_ready(self):
        import subprocess
        result = subprocess.run(
            ["python", "-m", "eb.cli", "report", "--run-id", "x"],
            capture_output=True, text=True,
            cwd="/home/afnan/projects/active/atlas-dataset/benchmarks/eb",
        )
        assert result.returncode != 0

    def test_help_output(self):
        import subprocess
        result = subprocess.run(
            ["python", "-m", "eb.cli", "--help"],
            capture_output=True, text=True,
            cwd="/home/afnan/projects/active/atlas-dataset/benchmarks/eb",
        )
        assert result.returncode == 0
        assert "run" in result.stdout
        assert "compare" in result.stdout
        assert "report" in result.stdout

    def test_run_prints_config(self):
        """The run command should print parsed config before failing."""
        import subprocess
        result = subprocess.run(
            ["python", "-m", "eb.cli", "run", "--model", "atan-v1", "--repeats", "3"],
            capture_output=True, text=True,
            cwd="/home/afnan/projects/active/atlas-dataset/benchmarks/eb",
        )
        assert "atan-v1" in result.stdout
        assert "repeats" in result.stdout or "3" in result.stdout
