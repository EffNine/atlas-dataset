"""Tests for eb/runners/base.py — Runner interface and TaskStatus."""
import pytest

from eb.runners.base import RunContext, Runner, TaskStatus
from eb.core.schema import Task
from eb.core.types import ExecutionMode


class TestTaskStatus:
    def test_values(self):
        assert TaskStatus.SUCCESS.value == "SUCCESS"
        assert TaskStatus.FAILED.value == "FAILED"
        assert TaskStatus.ERROR.value == "ERROR"
        assert TaskStatus.SKIPPED.value == "SKIPPED"

    def test_iteration(self):
        values = [s.value for s in TaskStatus]
        assert sorted(values) == ["ERROR", "FAILED", "SKIPPED", "SUCCESS"]


class TestRunContext:
    def test_defaults(self):
        ctx = RunContext(run_id="r1", model_name="m", suite="s")
        assert ctx.repeat_index == 0
        assert ctx.inference_settings == {}
        assert ctx.extra == {}
        assert "T" in ctx.start_time  # ISO timestamp format

    def test_custom_fields(self):
        ctx = RunContext(
            run_id="r2",
            model_name="m2",
            suite="full",
            repeat_index=3,
            inference_settings={"seed": 99},
            extra={"custom": "data"},
        )
        assert ctx.repeat_index == 3
        assert ctx.inference_settings["seed"] == 99
        assert ctx.extra["custom"] == "data"


class TestRunnerAbstract:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            Runner()  # type: ignore[abstract]

    def test_mode_property_required(self):
        from eb.core.schema import TaskResult
        class ConcreteRunner(Runner):
            @property
            def mode(self):
                return ExecutionMode.SINGLE

            def run(self, task, ctx) -> TaskResult:  # type: ignore[override]
                return TaskResult(task_id="x", run_id="y")

        r = ConcreteRunner()
        assert r.mode == ExecutionMode.SINGLE
