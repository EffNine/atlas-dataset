"""Tests for core/types.py — enum definitions and parsing."""
import pytest

from eb.core.types import (
    BenchmarkPartition,
    Capability,
    Difficulty,
    ExecutionMode,
    JudgeMode,
    parse_capability,
    parse_difficulty,
    parse_execution_mode,
    parse_judge_mode,
    parse_partition,
)


class TestExecutionMode:
    def test_enum_values(self):
        assert ExecutionMode.SINGLE.value == "SINGLE"
        assert ExecutionMode.MULTI.value == "MULTI"
        assert ExecutionMode.EXEC.value == "EXEC"
        assert ExecutionMode.LONG.value == "LONG"

    def test_iteration(self):
        modes = [m.value for m in ExecutionMode]
        assert sorted(modes) == ["EXEC", "LONG", "MULTI", "SINGLE"]

    def test_parse_valid(self):
        assert parse_execution_mode("SINGLE") == ExecutionMode.SINGLE
        assert parse_execution_mode("multi") == ExecutionMode.MULTI
        assert parse_execution_mode("exec") == ExecutionMode.EXEC
        assert parse_execution_mode("LONG") == ExecutionMode.LONG

    def test_parse_invalid(self):
        with pytest.raises(ValueError, match="Invalid execution mode"):
            parse_execution_mode("INVALID")
        with pytest.raises(ValueError, match="Invalid execution mode"):
            parse_execution_mode("")


class TestDifficulty:
    def test_enum_values(self):
        assert Difficulty.L1.value == "L1"
        assert Difficulty.L5.value == "L5"

    def test_parse_valid(self):
        assert parse_difficulty("L1") == Difficulty.L1
        assert parse_difficulty("l3") == Difficulty.L3
        assert parse_difficulty("L5") == Difficulty.L5

    def test_parse_invalid(self):
        with pytest.raises(ValueError, match="Invalid difficulty"):
            parse_difficulty("L9")
        with pytest.raises(ValueError, match="Invalid difficulty"):
            parse_difficulty("extreme")


class TestCapability:
    def test_all_capabilities_present(self):
        expected = {"ARCH", "DEBUG", "CODE", "UNDERSTAND", "PLAN", "TEST",
                     "ADVISORY", "JUDGMENT", "EVIDENCE", "MYENG", "AGENT", "LONG"}
        actual = {c.value for c in Capability}
        assert actual == expected

    def test_parse_valid(self):
        assert parse_capability("ARCH") == Capability.ARCH
        assert parse_capability("debug") == Capability.DEBUG
        assert parse_capability("AGENT") == Capability.AGENT

    def test_parse_invalid(self):
        with pytest.raises(ValueError, match="Invalid capability"):
            parse_capability("UNKNOWN")


class TestJudgeMode:
    def test_enum_values(self):
        assert JudgeMode.DETERMINISTIC.value == "DETERMINISTIC"
        assert JudgeMode.CLOUD_JUDGE.value == "CLOUD_JUDGE"
        assert JudgeMode.AI_OPINION.value == "AI_OPINION"

    def test_parse_valid(self):
        assert parse_judge_mode("DETERMINISTIC") == JudgeMode.DETERMINISTIC
        assert parse_judge_mode("rubric") == JudgeMode.RUBRIC
        assert parse_judge_mode("CLOUD_JUDGE") == JudgeMode.CLOUD_JUDGE


class TestBenchmarkPartition:
    def test_enum_values(self):
        assert BenchmarkPartition.DEVELOPMENT.value == "development"
        assert BenchmarkPartition.HIDDEN.value == "hidden"

    def test_parse_valid(self):
        assert parse_partition("development") == BenchmarkPartition.DEVELOPMENT
        assert parse_partition("VALIDATION") == BenchmarkPartition.VALIDATION
        assert parse_partition("private") == BenchmarkPartition.PRIVATE
        assert parse_partition("HIDDEN") == BenchmarkPartition.HIDDEN

    def test_parse_invalid(self):
        with pytest.raises(ValueError, match="Invalid partition"):
            parse_partition("leaked")
