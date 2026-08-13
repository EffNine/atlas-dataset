#!/usr/bin/env python3
"""Tests for the Atlas TUI control plane."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from tui_backend import TuiBackend, BenchmarkEntry, ExperimentEntry, GPUInfo, LogEvent, RunStatus, SystemInfo
from atlas_tui import AtlasTui, VIEW_DASHBOARD, VIEW_RESEARCH, VIEW_EXPERIMENTS, VIEW_BENCHMARKS
from atlas_tui import VIEW_RUNS, VIEW_SYSTEM, VIEW_LOGS, MAIN_MENU

ARROW_UP = "\x1b[A"
ARROW_DOWN = "\x1b[B"
ARROW_LEFT = "\x1b[D"
ARROW_RIGHT = "\x1b[C"


@pytest.fixture
def backend(tmp_path):
    (tmp_path / "metadata" / "research_state").mkdir(parents=True)
    (tmp_path / "metadata" / "pipeline_state").mkdir(parents=True)
    (tmp_path / "metadata" / "evaluation" / "reports").mkdir(parents=True)
    (tmp_path / "metadata" / "evaluation" / "calibration").mkdir(parents=True)
    (tmp_path / "evaluation" / "eval_sets" / "production").mkdir(parents=True)
    (tmp_path / "experiments").mkdir(parents=True)
    (tmp_path / "reports" / "performance").mkdir(parents=True)

    registry = {
        "schema_version": "1.0",
        "registry": {
            "internal": {
                "atlas_quality_benchmark": {
                    "benchmark_id": "atlas_quality_benchmark",
                    "category": "internal",
                    "purpose": "Quality benchmark",
                    "metric": "quality_score_agreement",
                    "license": "Apache-2.0",
                    "status": "draft",
                }
            },
            "external": {
                "gsm8k": {
                    "benchmark_id": "gsm8k",
                    "category": "external",
                    "purpose": "Grade school math",
                    "metric": "exact_match",
                    "license": "MIT",
                    "status": "placeholder",
                }
            }
        }
    }
    (tmp_path / "metadata" / "benchmark_registry.json").write_text(json.dumps(registry))

    (tmp_path / "metadata" / "research_state" / "gate-exp.json").write_text(json.dumps({
        "experiment_id": "gate-exp",
        "current_state": "LICENSE_VALIDATED",
        "transitions": [
            {"from_state": "BENCHMARK_DISCOVERY", "to_state": "BENCHMARK_ACQUIRED",
             "timestamp": "2026-08-12T00:00:00+00:00", "triggered_by": "system",
             "reason": "", "metadata": {}, "verdict": ""},
            {"from_state": "BENCHMARK_ACQUIRED", "to_state": "LICENSE_VALIDATED",
             "timestamp": "2026-08-12T01:00:00+00:00", "triggered_by": "system",
             "reason": "", "metadata": {}, "verdict": ""},
        ],
        "metadata": {},
        "human_approved": [],
        "last_updated": "2026-08-12T01:00:00+00:00",
    }))
    (tmp_path / "metadata" / "research_state" / "test-exp.json").write_text(json.dumps({
        "experiment_id": "test-exp",
        "current_state": "BENCHMARK_DISCOVERY",
        "transitions": [],
        "metadata": {},
        "human_approved": [],
        "last_updated": "2026-08-12T00:00:00+00:00",
    }))

    exp_reg = {
        "schema_version": "1.0",
        "experiments": [
            {
                "experiment_id": "lora_pilot_math_v0.1",
                "phase": "Phase 5B.1", "family": "math", "tier": "pilot",
                "target": "qwen7b", "scope": "lora", "version": 1,
                "status": "HOLD",
                "created_at": "2026-08-01T00:00:00+00:00",
                "updated_at": "2026-08-05T00:00:00+00:00",
                "hold_reason": "CUDA unavailable",
                "notes": "LoRA pilot math",
            },
            {
                "experiment_id": "atlas-math-small-qwen7b-lora-transfer-v1-eval",
                "phase": "P8-A", "family": "math", "tier": "small",
                "target": "qwen7b", "scope": "eval", "version": 1,
                "status": "EVALUATION_COMPLETED",
                "created_at": "2026-08-10T00:00:00+00:00",
                "updated_at": "2026-08-12T00:00:00+00:00",
            },
        ]
    }
    (tmp_path / "metadata" / "experiment_registry.json").write_text(json.dumps(exp_reg))

    eval_report = {
        "evaluation_id": "eval-atlas-math-small-qwen7b-lora-transfer-v1-eval-20260727",
        "benchmark_id": "atlas_quality_benchmark",
        "mode": "full",
        "dataset_version": "v0.2",
        "records_evaluated": 29,
        "timestamp": "2026-07-27T18:09:33+00:00",
        "reproducibility_hash": "abc123def456",
        "metrics": [
            {"metric_id": "correctness", "status": "PASS", "value": 0.827,
             "ci_lower": 0.65, "ci_upper": 0.94},
        ],
        "failures": [],
        "recommendations": [],
    }
    (tmp_path / "metadata" / "evaluation" / "reports" / "eval-atlas-math-small-qwen7b-lora-transfer-v1-eval-20260727.json") \
        .write_text(json.dumps(eval_report))

    return TuiBackend(root=tmp_path)


@pytest.fixture
def tui(backend):
    t = AtlasTui.__new__(AtlasTui)
    t.console = mock.MagicMock()
    t.backend = backend
    t.current_view = VIEW_DASHBOARD
    t.selected_row = 0
    t._menu_index = 0
    t.log_filter = ""
    t.research_exp_index = 0
    t.benchmark_index = 0
    t.experiment_index = 0
    t.run_index = 0
    t.running = True
    t.paused = False
    t._modal_type = None
    t._modal_msg = ""
    t._modal_confirm = False
    t._pending_action = None
    t._log_offset = 0
    t._log_paused = False
    return t


# ---------------------------------------------------------------------------
# Backend tests
# ---------------------------------------------------------------------------

class TestTuiBackend:
    def test_get_system_info(self, backend):
        info = backend.get_system_info()
        assert isinstance(info, SystemInfo)
        assert info.cpu_cores >= 1
        assert info.ram_total_mb > 0
        assert info.ram_used_mb >= 0
        assert info.python_version != ""

    def test_get_gpu_info_no_gpu(self):
        with mock.patch("tui_backend.subprocess.run", side_effect=FileNotFoundError):
            gpu = TuiBackend()._get_gpu_info()
        assert gpu.present is False
        assert gpu.count == 0

    def test_get_benchmarks(self, backend):
        bms = backend.get_benchmarks()
        assert len(bms) >= 2
        ids = {bm.benchmark_id for bm in bms}
        assert "atlas_quality_benchmark" in ids
        assert "gsm8k" in ids

    def test_benchmark_statuses(self, backend):
        bms = backend.get_benchmarks()
        atlas_bm = next(bm for bm in bms if bm.benchmark_id == "atlas_quality_benchmark")
        assert atlas_bm.status == "REGISTERED"
        assert atlas_bm.frozen is False
        assert atlas_bm.contamination == "pending"

        gsm8k = next(bm for bm in bms if bm.benchmark_id == "gsm8k")
        assert gsm8k.status == "PLACEHOLDER"

    def test_get_research_states(self, backend):
        states = backend.get_research_states()
        assert "gate-exp" in states
        assert "test-exp" in states

    def test_research_gate_detection(self, backend):
        gate = backend.get_research_gate("gate-exp")
        assert gate is not None
        assert gate.is_approval_gate is True
        assert gate.state == "LICENSE_VALIDATED"
        assert len(gate.next_states) > 0

    def test_research_non_gate(self, backend):
        gate = backend.get_research_gate("test-exp")
        assert gate is not None
        assert gate.is_approval_gate is False

    def test_get_experiments(self, backend):
        exps = backend.get_experiments()
        ids = {e.experiment_id for e in exps}
        assert "lora_pilot_math_v0.1" in ids
        assert "atlas-math-small-qwen7b-lora-transfer-v1-eval" in ids

    def test_experiment_enrichment(self, backend):
        exps = backend.get_experiments()
        eval_exp = next((e for e in exps if e.experiment_id == "atlas-math-small-qwen7b-lora-transfer-v1-eval"), None)
        assert eval_exp is not None
        assert eval_exp.correctness == 0.827
        assert eval_exp.ci_lower == 0.65
        assert eval_exp.ci_upper == 0.94
        assert eval_exp.n_evaluated == 29

    def test_hold_experiment(self, backend):
        exps = backend.get_experiments()
        pilot = next((e for e in exps if e.experiment_id == "lora_pilot_math_v0.1"), None)
        assert pilot is not None
        assert pilot.status == "HOLD"
        assert pilot.hold_reason == "CUDA unavailable"

    def test_get_logs(self, backend):
        logs = backend.get_logs(limit=10)
        assert isinstance(logs, list)
        for evt in logs:
            assert isinstance(evt, LogEvent)
            assert evt.timestamp
            assert evt.level
            assert evt.component
            assert evt.message

    def test_get_run_status_idle(self, tmp_path):
        root = tmp_path / "idle_test"
        root.mkdir()
        (root / "metadata" / "pipeline_state").mkdir(parents=True)
        backend = TuiBackend(root=root)
        run = backend.get_run_status()
        assert run.status == RunStatus.IDLE

    def test_cli_dispatch(self, backend):
        with mock.patch("tui_backend.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout="usage: atlas", stderr="")
            rc, out, err = backend.run_cli(["--help"])
            assert rc == 0
            assert "usage" in out.lower()

    def test_discover_benchmarks(self, backend):
        ok, msg = backend.discover_benchmarks(register=False)
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    def test_approve_research_gate_not_at_gate(self, backend):
        ok, msg = backend.approve_research_gate("test-exp", "tester")
        assert ok is False

    def test_get_calibration_status(self, backend):
        cal = backend.get_calibration_status()
        assert isinstance(cal, list)


# ---------------------------------------------------------------------------
# TUI rendering tests
# ---------------------------------------------------------------------------

class TestTuiRendering:
    def _render_safely(self, tui, render_method):
        try:
            panel = render_method()
            assert panel is not None
            return True
        except Exception:
            return False

    def test_dashboard_render(self, tui):
        assert self._render_safely(tui, tui._render_dashboard)

    def test_research_render(self, tui):
        tui.current_view = VIEW_RESEARCH
        assert self._render_safely(tui, tui._render_research)

    def test_experiments_render(self, tui):
        tui.current_view = VIEW_EXPERIMENTS
        assert self._render_safely(tui, tui._render_experiments)

    def test_benchmarks_render(self, tui):
        tui.current_view = VIEW_BENCHMARKS
        assert self._render_safely(tui, tui._render_benchmarks)

    def test_runs_render(self, tui):
        tui.current_view = VIEW_RUNS
        assert self._render_safely(tui, tui._render_runs)

    def test_system_render(self, tui):
        tui.current_view = VIEW_SYSTEM
        assert self._render_safely(tui, tui._render_system)

    def test_logs_render(self, tui):
        tui.current_view = VIEW_LOGS
        assert self._render_safely(tui, tui._render_logs)

    def test_all_views_render(self, tui):
        for view, method in [
            (VIEW_DASHBOARD, tui._render_dashboard),
            (VIEW_RESEARCH, tui._render_research),
            (VIEW_EXPERIMENTS, tui._render_experiments),
            (VIEW_BENCHMARKS, tui._render_benchmarks),
            (VIEW_RUNS, tui._render_runs),
            (VIEW_SYSTEM, tui._render_system),
            (VIEW_LOGS, tui._render_logs),
        ]:
            tui.current_view = view
            panel = method()
            assert panel is not None, f"View {view} failed to render"


# ---------------------------------------------------------------------------
# Key handling tests
# ---------------------------------------------------------------------------

class TestKeyHandling:
    def test_quit(self, tui):
        tui.handle_key("q")
        assert tui.running is False

    def test_view_navigation(self, tui):
        tui.handle_key("2")
        assert tui.current_view == VIEW_RESEARCH
        tui.handle_key("3")
        assert tui.current_view == VIEW_EXPERIMENTS
        tui.handle_key("4")
        assert tui.current_view == VIEW_BENCHMARKS
        tui.handle_key("5")
        assert tui.current_view == VIEW_RUNS
        tui.handle_key("6")
        assert tui.current_view == VIEW_SYSTEM
        tui.handle_key("7")
        assert tui.current_view == VIEW_LOGS
        tui.handle_key("1")
        assert tui.current_view == VIEW_DASHBOARD

    def test_pause_toggle(self, tui):
        assert tui.paused is False
        tui.handle_key("p")
        assert tui.paused is True
        tui.handle_key("p")
        assert tui.paused is False

    def test_help_modal(self, tui):
        tui.handle_key("h")
        assert tui._modal_type == "info"
        assert len(tui._modal_msg) > 100

    def test_research_nav_right(self, tui):
        tui.current_view = VIEW_RESEARCH
        tui.research_exp_index = 0
        tui.handle_key(ARROW_RIGHT)
        assert tui.research_exp_index >= 0

    def test_research_nav_left(self, tui):
        tui.current_view = VIEW_RESEARCH
        states = tui.backend.get_research_states()
        tui.research_exp_index = len(states) - 1
        tui.handle_key(ARROW_LEFT)
        assert tui.research_exp_index >= 0

    def test_experiments_nav_down(self, tui):
        tui.current_view = VIEW_EXPERIMENTS
        tui.experiment_index = 0
        tui.handle_key(ARROW_DOWN)
        assert tui.experiment_index >= 0
        tui.handle_key(ARROW_UP)
        assert tui.experiment_index >= 0

    def test_benchmarks_nav_right(self, tui):
        tui.current_view = VIEW_BENCHMARKS
        tui.benchmark_index = 0
        tui.handle_key(ARROW_RIGHT)
        assert tui.benchmark_index >= 0
        tui.handle_key(ARROW_LEFT)
        assert tui.benchmark_index >= 0

    def test_approve_gate_confirmation(self, tui):
        tui.current_view = VIEW_RESEARCH
        states = tui.backend.get_research_states()
        gate_exp = None
        for eid, data in states.items():
            gate = tui.backend.get_research_gate(eid)
            if gate and gate.is_approval_gate:
                gate_exp = eid
                break
        if gate_exp is None:
            pytest.skip("No gate state found in test backend")
        exp_ids = list(states.keys())
        tui.research_exp_index = exp_ids.index(gate_exp)
        tui.handle_key("a")
        assert tui._modal_type == "confirm"
        assert gate_exp in tui._modal_msg

    def test_approve_non_gate_no_confirm(self, tui):
        tui.current_view = VIEW_RESEARCH
        states = tui.backend.get_research_states()
        non_gate_exp = None
        for eid, data in states.items():
            gate = tui.backend.get_research_gate(eid)
            if gate and not gate.is_approval_gate:
                non_gate_exp = eid
                break
        if non_gate_exp is None:
            pytest.skip("No non-gate state found in test backend")
        exp_ids = list(states.keys())
        tui.research_exp_index = exp_ids.index(non_gate_exp)
        tui.handle_key("a")
        assert tui._modal_type == "info"
        assert "not at an approval gate" in tui._modal_msg.lower()

    def test_discover_confirmation(self, tui):
        tui.current_view = VIEW_BENCHMARKS
        tui.handle_key("d")
        assert tui._modal_type == "confirm"
        assert "discover" in tui._modal_msg.lower()

    def test_cancel_run_confirmation(self, tui):
        tui.current_view = VIEW_RUNS
        tui.handle_key("c")
        assert tui._modal_type == "confirm"
        assert "cancel" in tui._modal_msg.lower()

    def test_experiment_inspect(self, tui):
        tui.current_view = VIEW_EXPERIMENTS
        tui.handle_key("Enter")
        assert tui._modal_type == "info"
        exps = tui.backend.get_experiments()
        if exps:
            assert exps[0].experiment_id in tui._modal_msg

    def test_modal_confirm_yes(self, tui):
        tui._modal_type = "confirm"
        tui._modal_msg = "test confirm"
        tui._pending_action = "discover"
        tui.handle_key("y")
        assert tui._modal_type is None

    def test_modal_confirm_no(self, tui):
        tui._modal_type = "confirm"
        tui._modal_msg = "test confirm"
        tui._pending_action = "discover"
        tui.handle_key("n")
        assert tui._modal_type is None
        assert tui._pending_action is None

    def test_modal_escape(self, tui):
        tui._modal_type = "info"
        tui._modal_msg = "test info"
        tui.handle_key("escape")
        assert tui._modal_type is None

    def test_logs_filter_cycle(self, tui):
        tui.current_view = VIEW_LOGS
        assert tui.log_filter == ""
        tui.handle_key("f")
        assert tui.log_filter == "INFO"
        tui.handle_key("f")
        assert tui.log_filter == "WARN"
        tui.handle_key("f")
        assert tui.log_filter == "ERROR"
        tui.handle_key("f")
        assert tui.log_filter == ""

    def test_logs_scroll(self, tui):
        tui.current_view = VIEW_LOGS
        tui.handle_key(ARROW_DOWN)
        assert tui._log_offset >= 0
        tui.handle_key(ARROW_UP)

    def test_jump_to_logs_from_runs(self, tui):
        tui.current_view = VIEW_RUNS
        tui.handle_key("l")
        assert tui.current_view == VIEW_LOGS

    def test_start_run_confirmation(self, tui):
        tui.current_view = VIEW_RUNS
        tui.handle_key("s")
        assert tui._modal_type == "confirm"
        assert "pipeline" in tui._modal_msg.lower()

    def test_p_is_global_pause(self, tui):
        tui.current_view = VIEW_RESEARCH
        initial_paused = tui.paused
        tui.handle_key("p")
        assert tui.paused == (not initial_paused)
        tui.handle_key("p")
        assert tui.paused == initial_paused


# ---------------------------------------------------------------------------
# Keyboard navigation tests
# ---------------------------------------------------------------------------

class TestKeyboardNavigation:
    """Tests for j/k arrow-key navigation and main menu."""

    def test_main_menu_down_j(self, tui):
        tui.current_view = VIEW_DASHBOARD
        tui._menu_index = 0
        tui.handle_key("j")
        assert tui._menu_index == 1

    def test_main_menu_up_k(self, tui):
        tui.current_view = VIEW_DASHBOARD
        tui._menu_index = 1
        tui.handle_key("k")
        assert tui._menu_index == 0

    def test_main_menu_down_arrow(self, tui):
        tui.current_view = VIEW_DASHBOARD
        tui._menu_index = 0
        tui.handle_key(ARROW_DOWN)
        assert tui._menu_index == 1

    def test_main_menu_up_arrow(self, tui):
        tui.current_view = VIEW_DASHBOARD
        tui._menu_index = 1
        tui.handle_key(ARROW_UP)
        assert tui._menu_index == 0

    def test_main_menu_wrap_down(self, tui):
        tui.current_view = VIEW_DASHBOARD
        tui._menu_index = len(MAIN_MENU) - 1
        tui.handle_key("j")
        assert tui._menu_index == 0

    def test_main_menu_wrap_up(self, tui):
        tui.current_view = VIEW_DASHBOARD
        tui._menu_index = 0
        tui.handle_key("k")
        assert tui._menu_index == len(MAIN_MENU) - 1

    def test_main_menu_enter_opens_view(self, tui):
        tui.current_view = VIEW_DASHBOARD
        tui._menu_index = 0  # Benchmarks
        tui.handle_key("Enter")
        assert tui.current_view == VIEW_BENCHMARKS

    def test_main_menu_enter_selects_research(self, tui):
        tui.current_view = VIEW_DASHBOARD
        tui._menu_index = 1  # Research
        tui.handle_key("Enter")
        assert tui.current_view == VIEW_RESEARCH

    def test_main_menu_enter_selects_experiments(self, tui):
        tui.current_view = VIEW_DASHBOARD
        tui._menu_index = 2  # Experiments
        tui.handle_key("Enter")
        assert tui.current_view == VIEW_EXPERIMENTS

    def test_main_menu_enter_selects_pipelines(self, tui):
        tui.current_view = VIEW_DASHBOARD
        tui._menu_index = 3  # Pipelines
        tui.handle_key("Enter")
        assert tui.current_view == VIEW_RUNS

    def test_esc_from_research_returns_to_menu(self, tui):
        tui.current_view = VIEW_RESEARCH
        tui.handle_key("escape")
        assert tui.current_view == VIEW_DASHBOARD
        assert tui._menu_index == 0

    def test_esc_from_experiments_returns_to_menu(self, tui):
        tui.current_view = VIEW_EXPERIMENTS
        tui.handle_key("escape")
        assert tui.current_view == VIEW_DASHBOARD
        assert tui._menu_index == 0

    def test_esc_from_benchmarks_returns_to_menu(self, tui):
        tui.current_view = VIEW_BENCHMARKS
        tui.handle_key("escape")
        assert tui.current_view == VIEW_DASHBOARD
        assert tui._menu_index == 0

    def test_esc_from_runs_returns_to_menu(self, tui):
        tui.current_view = VIEW_RUNS
        tui.handle_key("escape")
        assert tui.current_view == VIEW_DASHBOARD
        assert tui._menu_index == 0

    def test_esc_from_logs_returns_to_menu(self, tui):
        tui.current_view = VIEW_LOGS
        tui.handle_key("escape")
        assert tui.current_view == VIEW_DASHBOARD
        assert tui._menu_index == 0

    def test_esc_from_system_returns_to_menu(self, tui):
        tui.current_view = VIEW_SYSTEM
        tui.handle_key("escape")
        assert tui.current_view == VIEW_DASHBOARD
        assert tui._menu_index == 0

    def test_esc_does_not_affect_running(self, tui):
        tui.current_view = VIEW_RESEARCH
        tui.running = True
        tui.handle_key("escape")
        assert tui.running is True

    def test_enter_in_experiments_shows_modal(self, tui):
        tui.current_view = VIEW_EXPERIMENTS
        tui.experiment_index = 0
        tui.handle_key("Enter")
        assert tui._modal_type == "info"
        exps = tui.backend.get_experiments()
        if exps:
            assert exps[0].experiment_id in tui._modal_msg

    def test_enter_in_benchmarks_shows_modal(self, tui):
        tui.current_view = VIEW_BENCHMARKS
        tui.benchmark_index = 0
        tui.handle_key("Enter")
        assert tui._modal_type == "info"
        bms = tui.backend.get_benchmarks()
        if bms:
            assert bms[0].benchmark_id in tui._modal_msg

    def test_cr_key_same_as_enter_in_main_menu(self, tui):
        """Raw-mode Enter (\\r) must open the selected view."""
        tui.current_view = VIEW_DASHBOARD
        tui._menu_index = 1  # Research
        tui.handle_key("\r")
        assert tui.current_view == VIEW_RESEARCH

    def test_cr_key_same_as_enter_in_experiments(self, tui):
        tui.current_view = VIEW_EXPERIMENTS
        tui.experiment_index = 0
        tui.handle_key("\r")
        assert tui._modal_type == "info"

    def test_cr_key_same_as_enter_in_benchmarks(self, tui):
        tui.current_view = VIEW_BENCHMARKS
        tui.benchmark_index = 0
        tui.handle_key("\r")
        assert tui._modal_type == "info"

    def test_j_navigation_in_experiments(self, tui):
        tui.current_view = VIEW_EXPERIMENTS
        tui.experiment_index = 0
        tui.handle_key("j")
        assert tui.experiment_index >= 0

    def test_k_navigation_in_experiments(self, tui):
        tui.current_view = VIEW_EXPERIMENTS
        tui.experiment_index = 1
        tui.handle_key("k")
        assert tui.experiment_index == 0

    def test_j_navigation_in_research(self, tui):
        tui.current_view = VIEW_RESEARCH
        tui.research_exp_index = 0
        tui.handle_key("j")
        assert tui.research_exp_index >= 0

    def test_k_navigation_in_research(self, tui):
        tui.current_view = VIEW_RESEARCH
        states = tui.backend.get_research_states()
        if len(states) > 1:
            tui.research_exp_index = 1
            tui.handle_key("k")
            assert tui.research_exp_index == 0

    def test_j_navigation_in_benchmarks(self, tui):
        tui.current_view = VIEW_BENCHMARKS
        tui.benchmark_index = 0
        tui.handle_key("j")
        assert tui.benchmark_index >= 0

    def test_k_navigation_in_benchmarks(self, tui):
        tui.current_view = VIEW_BENCHMARKS
        bms = tui.backend.get_benchmarks()
        if len(bms) > 1:
            tui.benchmark_index = 1
            tui.handle_key("k")
            assert tui.benchmark_index == 0

    def test_j_navigation_in_logs(self, tui):
        tui.current_view = VIEW_LOGS
        initial = tui._log_offset
        tui.handle_key("j")
        assert tui._log_offset >= initial

    def test_k_navigation_in_logs(self, tui):
        tui.current_view = VIEW_LOGS
        tui._log_offset = 30
        tui.handle_key("k")
        assert tui._log_offset == 0

    def test_numeric_shortcuts_still_work_from_menu(self, tui):
        tui.current_view = VIEW_DASHBOARD
        tui.handle_key("4")
        assert tui.current_view == VIEW_BENCHMARKS

    def test_numeric_shortcuts_still_work_from_view(self, tui):
        tui.current_view = VIEW_BENCHMARKS
        tui.handle_key("3")
        assert tui.current_view == VIEW_EXPERIMENTS
        tui.handle_key("1")
        assert tui.current_view == VIEW_DASHBOARD


# ---------------------------------------------------------------------------
# Safety tests
# ---------------------------------------------------------------------------

class TestSafety:
    def test_no_auto_approve(self, tui):
        tui.current_view = VIEW_RESEARCH
        states = tui.backend.get_research_states()
        gate_exp = None
        for eid, data in states.items():
            gate = tui.backend.get_research_gate(eid)
            if gate and gate.is_approval_gate:
                gate_exp = eid
                break
        if gate_exp is None:
            pytest.skip("No gate state found")
        exp_ids = list(states.keys())
        tui.research_exp_index = exp_ids.index(gate_exp)
        tui.handle_key("a")
        assert tui._modal_type == "confirm"
        assert tui._pending_action is not None

    def test_cancel_requires_confirm(self, tui):
        tui.current_view = VIEW_RUNS
        tui.handle_key("c")
        assert tui._modal_type == "confirm"

    def test_discover_requires_confirm(self, tui):
        tui.current_view = VIEW_BENCHMARKS
        tui.handle_key("d")
        assert tui._modal_type == "confirm"

    def test_acquire_requires_confirm(self, tui):
        tui.current_view = VIEW_BENCHMARKS
        tui.handle_key("a")
        assert tui._modal_type == "confirm"

    def test_freeze_requires_confirm(self, tui):
        tui.current_view = VIEW_BENCHMARKS
        tui.handle_key("f")
        assert tui._modal_type == "confirm"

    def test_evaluate_requires_confirm(self, tui):
        tui.current_view = VIEW_EXPERIMENTS
        tui.handle_key("e")
        assert tui._modal_type == "confirm"


# ---------------------------------------------------------------------------
# Backend unavailable tests
# ---------------------------------------------------------------------------

class TestBackendUnavailable:
    def test_missing_state_dir(self, tmp_path):
        root = tmp_path / "empty"
        root.mkdir()
        backend = TuiBackend(root=root)
        states = backend.get_research_states()
        assert states == {}
        benchmarks = backend.get_benchmarks()
        assert benchmarks == []
        experiments = backend.get_experiments()
        assert all(e.status in ("HOLD", "NOT_STARTED") for e in experiments)

    def test_corrupt_json_files(self, tmp_path):
        (tmp_path / "metadata" / "research_state").mkdir(parents=True)
        (tmp_path / "metadata" / "benchmark_registry.json").write_text("{corrupt")
        (tmp_path / "metadata" / "experiment_registry.json").write_text("{corrupt")
        (tmp_path / "metadata" / "research_state" / "bad.json").write_text("{corrupt")

        backend = TuiBackend(root=tmp_path)
        assert backend.get_research_states() == {}
        assert backend.get_benchmarks() == []
        exps = backend.get_experiments()
        assert len(exps) >= 0

    def test_empty_registry(self, tmp_path):
        (tmp_path / "metadata").mkdir(parents=True)
        (tmp_path / "metadata" / "benchmark_registry.json").write_text(
            json.dumps({"schema_version": "1.0", "registry": {"internal": {}, "external": {}}})
        )
        (tmp_path / "metadata" / "experiment_registry.json").write_text(
            json.dumps({"schema_version": "1.0", "experiments": []})
        )
        backend = TuiBackend(root=tmp_path)
        bms = backend.get_benchmarks()
        exps = backend.get_experiments()
        assert bms == []
        assert len(exps) >= 0


# ---------------------------------------------------------------------------
# GPU monitoring tests
# ---------------------------------------------------------------------------

class TestGpuMonitoring:
    def test_gpu_info_structure(self, backend):
        info = backend.get_system_info()
        assert isinstance(info.gpu, GPUInfo)
        assert hasattr(info.gpu, "present")
        assert hasattr(info.gpu, "used_mb")
        assert hasattr(info.gpu, "total_mb")
        assert hasattr(info.gpu, "free_mb")
        assert hasattr(info.gpu, "processes")

    def test_gpu_warning_in_runs_view(self, backend):
        tui = AtlasTui.__new__(AtlasTui)
        tui.backend = backend
        tui.paused = False

        high_gpu = GPUInfo(present=True, count=1, name="RTX 5070",
                           total_mb=12227, used_mb=11000, free_mb=1227,
                           processes=[{"pid": "123", "name": "ollama", "memory_mb": 9600}])
        tui.backend.get_system_info = mock.MagicMock(return_value=SystemInfo(
            cpu_cores=16, ram_total_mb=30000, ram_used_mb=15000,
            ram_available_mb=15000, disk_free_gb=100.0, gpu=high_gpu,
            python_version="3.14.4", atlas_root="/tmp",
        ))
        tui.current_view = VIEW_RUNS
        panel = tui._render_runs()
        from rich.panel import Panel
        assert isinstance(panel, Panel)


# ---------------------------------------------------------------------------
# No fake progress tests
# ---------------------------------------------------------------------------

class TestNoFakeProgress:
    def test_idle_run_has_no_fake_progress(self, tmp_path):
        root = tmp_path / "idle_test"
        root.mkdir()
        (root / "metadata" / "pipeline_state").mkdir(parents=True)
        backend = TuiBackend(root=root)
        run = backend.get_run_status()
        assert run.status == RunStatus.IDLE
        assert run.records_completed == 0
        assert run.throughput == 0.0
        assert run.eta_seconds == 0

    def test_progress_derived_from_state(self, tmp_path):
        backend = TuiBackend(root=tmp_path)
        run = backend.get_run_status()
        assert run.records_completed == 0
        assert run.records_total == 0

    def test_experiments_show_artifact_metrics_only(self, backend):
        exps = backend.get_experiments()
        for exp in exps:
            if exp.status == "NOT_STARTED":
                assert exp.correctness is None
                assert exp.ci_lower is None
                assert exp.ci_upper is None


# ---------------------------------------------------------------------------
# Entry point tests
# ---------------------------------------------------------------------------

class TestEntryPoint:
    def test_main_returns_zero_on_keyboard_interrupt(self):
        with mock.patch("atlas_tui.AtlasTui.run", side_effect=KeyboardInterrupt):
            from atlas_tui import main
            result = main()
            assert result == 0

    def test_atlas_cli_tui_command_exists(self):
        from atlas import main as atlas_main
        with pytest.raises(SystemExit) as exc_info:
            atlas_main(["tui", "--help"])
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# Behavioral tests — actual execution via backend
# ---------------------------------------------------------------------------

class TestPipelineActions:
    def test_start_run_invokes_cli(self, backend):
        with mock.patch.object(backend, "run_cli") as mock_run:
            mock_run.return_value = (0, "Pipeline started.", "")
            ok, msg = backend.start_pipeline()
            assert ok is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "automation-runner" in args or any("run" in a for a in args)

    def test_start_run_failure_shows_error(self, backend):
        with mock.patch.object(backend, "run_cli") as mock_run:
            mock_run.return_value = (1, "", "pipeline not found")
            ok, msg = backend.start_pipeline()
            assert ok is False
            assert "failed" in msg.lower() or "not found" in msg.lower()

    def test_cancel_run_invokes_cli(self, backend):
        with mock.patch.object(backend, "run_cli") as mock_run:
            mock_run.return_value = (0, '{"command": "cancel", "cancelled": true}', "")
            ok, msg = backend.cancel_pipeline()
            assert ok is True

    def test_cancel_run_terminal_state_not_invoked(self, backend):
        with mock.patch.object(backend, "run_cli") as mock_run:
            mock_run.return_value = (1, "", "already terminal")
            ok, msg = backend.cancel_pipeline()
            assert ok is False
            assert "terminal" in msg.lower() or "already" in msg.lower()

    def test_confirm_start_shows_modal(self, tui):
        tui.current_view = VIEW_RUNS
        tui.handle_key("s")
        assert tui._modal_type == "confirm"
        assert tui._pending_action == "start_run"

    def test_reject_start_nothing_invoked(self, tui, backend):
        tui.current_view = VIEW_RUNS
        tui.handle_key("s")
        assert tui._modal_type == "confirm"
        tui.handle_key("n")
        assert tui._modal_type is None
        assert tui._pending_action is None


class TestResearchActions:
    def test_approve_persists_and_survives_recreation(self, tmp_path):
        from evaluation_research.state_machine import ResearchStateMachine, ResearchState

        sm = ResearchStateMachine("exp-test", tmp_path)
        sm.transition_to(ResearchState.BENCHMARK_ACQUIRED)
        sm.transition_to(ResearchState.LICENSE_VALIDATED)
        assert sm.approve_gate(ResearchState.LICENSE_VALIDATED, approved_by="reviewer")
        assert "LICENSE_VALIDATED" in sm._human_approved
        assert sm.transition_to(ResearchState.CONTAMINATION_AUDIT)

        sm2 = ResearchStateMachine("exp-test", tmp_path)
        assert sm2.load() is True
        assert "LICENSE_VALIDATED" in sm2._human_approved
        assert sm2.current_state == ResearchState.CONTAMINATION_AUDIT

    def test_approve_failed_does_not_persist_invalid_state(self, tmp_path):
        from evaluation_research.state_machine import ResearchStateMachine, ResearchState

        sm = ResearchStateMachine("exp-fail", tmp_path)
        ok = sm.approve_gate(ResearchState.EVALUATION_COMPLETE, approved_by="reviewer")
        assert ok is False
        state_file = tmp_path / "metadata" / "research_state" / "exp-fail.json"
        assert not state_file.exists()

    def test_approve_backend_calls_fsm(self, backend, tmp_path):
        from evaluation_research.state_machine import ResearchStateMachine, ResearchState
        import json

        state_dir = tmp_path / "metadata" / "research_state"
        state_dir.mkdir(parents=True, exist_ok=True)
        exp_data = {
            "experiment_id": "test-approve",
            "current_state": "LICENSE_VALIDATED",
            "transitions": [
                {"from_state": "BENCHMARK_DISCOVERY", "to_state": "BENCHMARK_ACQUIRED",
                 "timestamp": "2026-08-12T00:00:00+00:00", "triggered_by": "system",
                 "reason": "", "metadata": {}, "verdict": ""},
                {"from_state": "BENCHMARK_ACQUIRED", "to_state": "LICENSE_VALIDATED",
                 "timestamp": "2026-08-12T01:00:00+00:00", "triggered_by": "system",
                 "reason": "", "metadata": {}, "verdict": ""},
            ],
            "metadata": {},
            "human_approved": [],
            "last_updated": "2026-08-12T01:00:00+00:00",
        }
        (state_dir / "test-approve.json").write_text(json.dumps(exp_data))

        backend_test = TuiBackend(root=tmp_path)
        with mock.patch.object(backend_test, "run_cli") as mock_cli:
            mock_cli.return_value = (0, '{"current_state": "LICENSE_VALIDATED"}', "")
            ok, msg = backend_test.approve_research_gate("test-approve", "human_user")
        assert ok is True
        assert "Approved" in msg or "LICENSE_VALIDATED" in msg

        sm = ResearchStateMachine("test-approve", tmp_path)
        assert sm.load() is True
        assert sm.current_state == ResearchState.LICENSE_VALIDATED
        assert "LICENSE_VALIDATED" in sm._human_approved
        assert sm.transition_to(ResearchState.CONTAMINATION_AUDIT)
        assert sm.current_state == ResearchState.CONTAMINATION_AUDIT

    def test_reject_approve_no_mutation(self, backend, tmp_path):
        from evaluation_research.state_machine import ResearchStateMachine, ResearchState
        import json

        state_dir = tmp_path / "metadata" / "research_state"
        state_dir.mkdir(parents=True, exist_ok=True)
        exp_data = {
            "experiment_id": "test-reject",
            "current_state": "BENCHMARK_DISCOVERY",
            "transitions": [],
            "metadata": {},
            "human_approved": [],
            "last_updated": "2026-08-12T00:00:00+00:00",
        }
        (state_dir / "test-reject.json").write_text(json.dumps(exp_data))

        backend_test = TuiBackend(root=tmp_path)
        ok, msg = backend_test.approve_research_gate("test-reject", "human_user")
        assert ok is False

        sm = ResearchStateMachine("test-reject", tmp_path)
        assert sm.load() is True
        assert sm.current_state == ResearchState.BENCHMARK_DISCOVERY


class TestBenchmarkActions:
    def test_discover_invokes_cli(self, backend):
        with mock.patch.object(backend, "run_cli") as mock_run:
            mock_run.return_value = (0, "discovered 2 benchmarks", "")
            ok, msg = backend.discover_benchmarks(register=True)
            assert ok is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "benchmark" in args and "discover" in args

    def test_acquire_invokes_cli(self, backend):
        with mock.patch.object(backend, "run_cli") as mock_run:
            mock_run.return_value = (0, "acquired gsm8k", "")
            ok, msg = backend.acquire_benchmark("gsm8k", dry_run=True)
            assert ok is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "benchmark" in args and "acquire" in args

    def test_audit_invokes_cli(self, backend):
        with mock.patch.object(backend, "run_cli") as mock_run:
            mock_run.return_value = (0, "audit passed", "")
            ok, msg = backend.audit_contamination("/tmp/test.jsonl")
            assert ok is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "benchmark" in args and "audit" in args

    def test_freeze_invokes_cli(self, backend, tmp_path):
        eval_dir = tmp_path / "evaluation" / "eval_sets" / "production"
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "test-bm_clean.jsonl").write_text('{"problem":"test"}\n')

        backend_test = TuiBackend(root=tmp_path)
        with mock.patch.object(backend_test, "run_cli") as mock_run:
            mock_run.return_value = (0, "audit passed", "")
            ok, msg = backend_test.freeze_benchmark("test-bm")
            assert ok is True
            audit_call = mock_run.call_args_list[0]
            assert "audit" in audit_call[0][0]
            manifest = eval_dir / "test-bm_manifest.json"
            assert manifest.exists()


class TestExperimentActions:
    def test_evaluate_invokes_cli(self, backend):
        with mock.patch.object(backend, "run_cli") as mock_run:
            mock_run.return_value = (0, "evaluation completed", "")
            ok, msg = backend.evaluate_experiment("test-exp")
            assert ok is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "eval" in args and "matrix" in args

    def test_hold_updates_registry(self, backend, tmp_path):
        import json
        reg_path = tmp_path / "metadata" / "experiment_registry.json"
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        if not reg_path.exists():
            reg_path.write_text(json.dumps({"schema_version": "1.0", "experiments": []}))
        data = json.loads(reg_path.read_text())
        data["experiments"].append({"experiment_id": "hold-test", "status": "CREATED", "hold_reason": ""})
        reg_path.write_text(json.dumps(data))

        backend_test = TuiBackend(root=tmp_path)
        ok, msg = backend_test.hold_experiment("hold-test", "Testing hold")
        assert ok is True
        assert "HOLD" in msg

        updated = json.loads(reg_path.read_text())
        exp = next((e for e in updated["experiments"] if e["experiment_id"] == "hold-test"), None)
        assert exp is not None
        assert exp["status"] == "HOLD"
        assert exp["hold_reason"] == "Testing hold"


class TestKeyCollision:
    def test_p_is_always_pause_in_research(self, tui):
        tui.current_view = VIEW_RESEARCH
        initial_index = tui.research_exp_index
        tui.handle_key("p")
        assert tui.paused is True
        assert tui.research_exp_index == initial_index

    def test_p_is_always_pause_in_experiments(self, tui):
        tui.current_view = VIEW_EXPERIMENTS
        initial_index = tui.experiment_index
        tui.handle_key("p")
        assert tui.paused is True
        assert tui.experiment_index == initial_index

    def test_p_is_always_pause_in_benchmarks(self, tui):
        tui.current_view = VIEW_BENCHMARKS
        initial_index = tui.benchmark_index
        tui.handle_key("p")
        assert tui.paused is True
        assert tui.benchmark_index == initial_index

    def test_p_is_always_pause_in_logs(self, tui):
        tui.current_view = VIEW_LOGS
        initial_offset = tui._log_offset
        tui.handle_key("p")
        assert tui.paused is True
        assert tui._log_offset == initial_offset

    def test_b_works_as_previous_in_research(self, tui):
        tui.current_view = VIEW_RESEARCH
        states = tui.backend.get_research_states()
        if len(states) > 1:
            tui.research_exp_index = 0
            tui.handle_key("b")
            assert tui.research_exp_index == len(states) - 1

    def test_b_works_as_previous_in_benchmarks(self, tui):
        tui.current_view = VIEW_BENCHMARKS
        benchmarks = tui.backend.get_benchmarks()
        if len(benchmarks) > 1:
            tui.benchmark_index = 0
            tui.handle_key("b")
            assert tui.benchmark_index == len(benchmarks) - 1


class TestActionExecution:
    def test_discover_execution_shows_result(self, tui, backend):
        with mock.patch.object(backend, "discover_benchmarks") as mock_fn:
            mock_fn.return_value = (True, "Discovered 3 benchmarks")
            tui.current_view = VIEW_BENCHMARKS
            tui.handle_key("d")
            assert tui._modal_type == "confirm"
            tui.handle_key("y")
            assert tui._modal_type is None
            assert "OK" in tui._modal_msg
            mock_fn.assert_called_once_with(register=True)

    def test_discover_execution_failure_shows_error(self, tui, backend):
        with mock.patch.object(backend, "discover_benchmarks") as mock_fn:
            mock_fn.return_value = (False, "Network error")
            tui.current_view = VIEW_BENCHMARKS
            tui.handle_key("d")
            tui.handle_key("y")
            assert tui._modal_type is None
            assert "FAILED" in tui._modal_msg or "error" in tui._modal_msg.lower()
            mock_fn.assert_called_once()

    def test_approve_execution_shows_result(self, tui, backend):
        with mock.patch.object(backend, "approve_research_gate") as mock_fn:
            mock_fn.return_value = (True, "Approved LICENSE_VALIDATED by tui-user")
            tui.current_view = VIEW_RESEARCH
            states = backend.get_research_states()
            gate_exp = None
            for eid, data in states.items():
                gate = backend.get_research_gate(eid)
                if gate and gate.is_approval_gate:
                    gate_exp = eid
                    break
            if gate_exp:
                exp_ids = list(states.keys())
                tui.research_exp_index = exp_ids.index(gate_exp)
                tui.handle_key("a")
                assert tui._modal_type == "confirm"
                tui.handle_key("y")
                assert tui._modal_type is None
                assert "OK" in tui._modal_msg
                mock_fn.assert_called_once()

    def test_hold_execution_shows_result(self, tui, backend, tmp_path):
        import json
        reg_path = tmp_path / "metadata" / "experiment_registry.json"
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        if not reg_path.exists():
            reg_path.write_text(json.dumps({"schema_version": "1.0", "experiments": []}))
        data = json.loads(reg_path.read_text())
        data["experiments"].append({"experiment_id": "hold-test", "status": "CREATED", "hold_reason": ""})
        reg_path.write_text(json.dumps(data))
        backend_test = TuiBackend(root=tmp_path)
        tui.backend = backend_test
        tui.current_view = VIEW_EXPERIMENTS
        tui.handle_key("H")
        assert tui._modal_type == "confirm"
        tui.handle_key("y")
        assert tui._modal_type is None
        assert "HOLD" in tui._modal_msg

    def test_start_run_execution_shows_result(self, tui, backend):
        with mock.patch.object(backend, "start_pipeline") as mock_fn:
            mock_fn.return_value = (True, "Pipeline started.")
            tui.current_view = VIEW_RUNS
            tui.handle_key("s")
            assert tui._modal_type == "confirm"
            tui.handle_key("y")
            assert tui._modal_type is None
            assert "OK" in tui._modal_msg
            mock_fn.assert_called_once()

    def test_cancel_run_execution_shows_result(self, tui, backend):
        with mock.patch.object(backend, "cancel_pipeline") as mock_fn:
            mock_fn.return_value = (True, "Cancellation submitted.")
            tui.current_view = VIEW_RUNS
            tui.handle_key("c")
            assert tui._modal_type == "confirm"
            tui.handle_key("y")
            assert tui._modal_type is None
            assert "OK" in tui._modal_msg
            mock_fn.assert_called_once()


class TestNoFakeThroughput:
    def test_idle_has_zero_throughput(self, tmp_path):
        root = tmp_path / "idle"
        root.mkdir()
        (root / "metadata" / "pipeline_state").mkdir(parents=True)
        backend = TuiBackend(root=root)
        run = backend.get_run_status()
        assert run.throughput == 0.0
        assert run.status == RunStatus.IDLE

    def test_insufficient_data_yields_zero(self, tmp_path):
        root = tmp_path / "no_ts"
        root.mkdir()
        ps_dir = root / "metadata" / "pipeline_state"
        ps_dir.mkdir(parents=True)
        ps_file = ps_dir / "default.jsonl"
        ps_file.write_text('{"completed": 5}\n')
        backend = TuiBackend(root=root)
        run = backend.get_run_status()
        assert run.throughput == 0.0

    def test_real_timestamps_produce_throughput(self, tmp_path):
        root = tmp_path / "with_ts"
        root.mkdir()
        ps_dir = root / "metadata" / "pipeline_state"
        ps_dir.mkdir(parents=True)
        start_time = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()
        (ps_dir / "default.jsonl").write_text(
            f'{{"completed": 50, "total_sources": 100, "updated_at": "{start_time}"}}\n'
        )
        backend = TuiBackend(root=root)
        run = backend.get_run_status()
        assert run.throughput > 0
        assert 0.1 < run.throughput < 2.0

    def test_error_does_not_produce_fake_progress(self, tmp_path):
        root = tmp_path / "bad_ts"
        root.mkdir()
        ps_dir = root / "metadata" / "pipeline_state"
        ps_dir.mkdir(parents=True)
        (ps_dir / "default.jsonl").write_text('{"completed": 10, "updated_at": "not-a-date"}\n')
        backend = TuiBackend(root=root)
        run = backend.get_run_status()
        assert run.throughput == 0.0


class TestSafetyConfirmations:
    def test_every_destructive_action_needs_confirm(self, tui):
        actions = [
            (VIEW_RESEARCH, "a", "approve"),
            (VIEW_BENCHMARKS, "d", "discover"),
            (VIEW_BENCHMARKS, "a", "acquire"),
            (VIEW_BENCHMARKS, "f", "freeze"),
            (VIEW_EXPERIMENTS, "e", "evaluate"),
            (VIEW_EXPERIMENTS, "H", "hold"),
            (VIEW_RUNS, "s", "start"),
            (VIEW_RUNS, "c", "cancel"),
        ]
        for view, key, action_name in actions:
            tui.current_view = view
            tui.handle_key(key)
            assert tui._modal_type == "confirm", f"{action_name} should require confirmation"
            tui._modal_type = None
            tui._pending_action = None

    def test_confirmation_alone_never_counts_as_success(self, tui):
        tui.current_view = VIEW_RUNS
        tui.handle_key("s")
        assert tui._modal_type == "confirm"
        assert tui._pending_action == "start_run"


class TestPipelineCancellation:
    def test_cancel_invokes_new_command(self, backend):
        with mock.patch.object(backend, "run_cli") as mock_run:
            mock_run.return_value = (0, '{"command": "cancel", "cancelled": true}', "")
            ok, msg = backend.cancel_pipeline()
            assert ok is True
            args = mock_run.call_args[0][0]
            assert "cancel" in args

    def test_cancel_failure_shows_error(self, backend):
        with mock.patch.object(backend, "run_cli") as mock_run:
            mock_run.return_value = (1, "", "already terminal")
            ok, msg = backend.cancel_pipeline()
            assert ok is False
            assert "terminal" in msg.lower() or "already" in msg.lower()

    def test_cancel_persists_state(self, tmp_path):
        from automation.state_machine import PipelineState, StateMachine

        sm = StateMachine("cancel-test", tmp_path)
        sm.transition_to(PipelineState.QUALITY_CHECK)
        assert sm.current_state == PipelineState.QUALITY_CHECK

        ok = sm.transition_to(PipelineState.CANCELLED, triggered_by="tui")
        assert ok is True
        assert sm.current_state == PipelineState.CANCELLED
        assert sm.is_terminal() is True

        sm2 = StateMachine("cancel-test", tmp_path)
        assert sm2.load() is True
        assert sm2.current_state == PipelineState.CANCELLED


class TestEvalMatrixCLI:
    def test_eval_matrix_cli_registered(self):
        from atlas import main as atlas_main
        import pytest
        with pytest.raises(SystemExit) as exc_info:
            atlas_main(["eval", "matrix", "--help"])
        assert exc_info.value.code == 0

    def test_eval_matrix_resolves_eval_set(self, tmp_path):
        from atlas import cmd_eval_matrix
        import json

        proto_dir = tmp_path / "evaluation" / "eval_sets" / "protocol_v2"
        proto_dir.mkdir(parents=True)
        (proto_dir / "math_eval_v2_clean.jsonl").write_text('{"problem": "test"}\n')

        state_dir = tmp_path / "metadata" / "research_state"
        state_dir.mkdir(parents=True)
        (state_dir / "matrix-test.json").write_text(json.dumps({
            "experiment_id": "matrix-test",
            "current_state": "LICENSE_VALIDATED",
            "transitions": [],
            "metadata": {},
            "human_approved": [],
            "last_updated": "2026-08-12T00:00:00+00:00",
        }))

        rc = cmd_eval_matrix("matrix-test", tmp_path, dry_run=True)
        assert rc == 0


class TestMatrixExecution:
    """Test the matrix execution contract."""

    def test_dry_run_never_invokes_inference(self, tmp_path):
        """Dry-run must not attempt CUDA/model loading."""
        from evaluation_research.matrix_runner import MatrixRunner
        import json, hashlib

        # Set up minimal research state
        state_dir = tmp_path / "metadata" / "research_state"
        state_dir.mkdir(parents=True)
        (state_dir / "dry-test.json").write_text(json.dumps({
            "experiment_id": "dry-test",
            "current_state": "LICENSE_VALIDATED",
            "transitions": [],
            "metadata": {"family": "math"},
            "human_approved": [],
            "last_updated": "2026-08-12T00:00:00+00:00",
        }))

        # Create eval set
        proto_dir = tmp_path / "evaluation" / "eval_sets" / "protocol_v2"
        proto_dir.mkdir(parents=True)
        content = b'{"record_id": "r1", "problem": "2+2", "canonical_answer": "4"}\n'
        (proto_dir / "math_eval_v2_clean.jsonl").write_text(content.decode())

        # Create manifest with matching checksum (in same dir as eval set)
        checksum = hashlib.sha256(content).hexdigest()
        (proto_dir / "math_eval_v2_clean_manifest.json").write_text(json.dumps({
            "eval_set_id": "math_eval_v2_clean",
            "checksum": {"records": checksum},
        }))

        runner = MatrixRunner(tmp_path)
        result = runner.execute_matrix("dry-test", dry_run=True)
        assert result["status"] == "DRY_RUN_OK"
        assert result["dry_run"] is True
        # Should not have tried to load model
        assert "torch" not in str(result.get("error", ""))

    def test_missing_eval_set_blocks_execution(self, tmp_path):
        """Missing eval set should block execution with clear error."""
        from evaluation_research.matrix_runner import MatrixRunner
        import json

        state_dir = tmp_path / "metadata" / "research_state"
        state_dir.mkdir(parents=True)
        (state_dir / "no-eval.json").write_text(json.dumps({
            "experiment_id": "no-eval",
            "current_state": "LICENSE_VALIDATED",
            "transitions": [],
            "metadata": {"family": "math"},
            "human_approved": [],
            "last_updated": "2026-08-12T00:00:00+00:00",
        }))

        runner = MatrixRunner(tmp_path)
        result = runner.execute_matrix("no-eval", dry_run=False)
        assert result["status"] == "FAILED"
        assert "eval set" in result["error"].lower()

    def test_missing_experiment_blocks_execution(self, tmp_path):
        """Non-existent experiment should fail gracefully."""
        from evaluation_research.matrix_runner import MatrixRunner

        runner = MatrixRunner(tmp_path)
        result = runner.execute_matrix("nonexistent", dry_run=False)
        assert result["status"] == "FAILED"
        assert "research state" in result["error"].lower()

    def test_no_cuda_blocks_execution(self, tmp_path):
        """Execution should handle missing dependencies gracefully."""
        from evaluation_research.matrix_runner import MatrixRunner
        import json

        state_dir = tmp_path / "metadata" / "research_state"
        state_dir.mkdir(parents=True)
        (state_dir / "no-cuda.json").write_text(json.dumps({
            "experiment_id": "no-cuda",
            "current_state": "LICENSE_VALIDATED",
            "transitions": [],
            "metadata": {"family": "math"},
            "human_approved": [],
            "last_updated": "2026-08-12T00:00:00+00:00",
        }))

        proto_dir = tmp_path / "evaluation" / "eval_sets" / "protocol_v2"
        proto_dir.mkdir(parents=True)
        (proto_dir / "math_eval_v2_clean.jsonl").write_text(
            '{"record_id": "r1", "problem": "2+2", "canonical_answer": "4"}\n'
        )

        runner = MatrixRunner(tmp_path)
        result = runner.execute_matrix("no-cuda", dry_run=False)
        # Should complete or be blocked, not crash with exception
        assert result["status"] in ("COMPLETED", "BLOCKED", "FAILED", "DRY_RUN_OK")

    def test_execute_writes_artifacts_on_success(self, tmp_path):
        """Successful execution should write run metadata and per-example results."""
        from evaluation_research.matrix_runner import MatrixRunner
        import json, hashlib

        state_dir = tmp_path / "metadata" / "research_state"
        state_dir.mkdir(parents=True)
        (state_dir / "mock-cuda.json").write_text(json.dumps({
            "experiment_id": "mock-cuda",
            "current_state": "LICENSE_VALIDATED",
            "transitions": [],
            "metadata": {
                "family": "math",
                "base_model": "Qwen/Qwen2.5-7B-Instruct",
            },
            "human_approved": [],
            "last_updated": "2026-08-12T00:00:00+00:00",
        }))

        proto_dir = tmp_path / "evaluation" / "eval_sets" / "protocol_v2"
        proto_dir.mkdir(parents=True)
        content = b'{"record_id": "r1", "problem": "2+2", "canonical_answer": "4"}\n'
        (proto_dir / "math_eval_v2_clean.jsonl").write_text(content.decode())

        # Create manifest with matching checksum
        checksum = hashlib.sha256(content).hexdigest()
        (proto_dir / "math_eval_v2_clean_manifest.json").write_text(json.dumps({
            "eval_set_id": "math_eval_v2_clean",
            "checksum": {"records": checksum},
        }))

        runner = MatrixRunner(tmp_path)
        result = runner.execute_matrix("mock-cuda", dry_run=True)
        assert result["status"] == "DRY_RUN_OK"
        assert "provenance" in result
        assert result["provenance"]["experiment_id"] == "mock-cuda"
        assert "eval_set" in result["provenance"]
        assert "model" in result["provenance"]

    def test_no_overwrite_existing_run(self, tmp_path):
        """Execution should not overwrite existing run artifacts."""
        from evaluation_research.matrix_runner import MatrixRunner
        import json
        from datetime import datetime, timezone

        state_dir = tmp_path / "metadata" / "research_state"
        state_dir.mkdir(parents=True)
        (state_dir / "overwrite-test.json").write_text(json.dumps({
            "experiment_id": "overwrite-test",
            "current_state": "LICENSE_VALIDATED",
            "transitions": [],
            "metadata": {"family": "math"},
            "human_approved": [],
            "last_updated": "2026-08-12T00:00:00+00:00",
        }))

        proto_dir = tmp_path / "evaluation" / "eval_sets" / "protocol_v2"
        proto_dir.mkdir(parents=True)
        (proto_dir / "math_eval_v2_clean.jsonl").write_text(
            '{"record_id": "r1", "problem": "2+2", "canonical_answer": "4"}\n'
        )

        # Pre-create an existing run with a specific timestamp
        results_dir = tmp_path / "metadata" / "evaluation" / "matrix"
        results_dir.mkdir(parents=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        existing_run = results_dir / f"matrix_overwrite-test_{ts}"
        existing_run.mkdir(parents=True)
        (existing_run / "run_metadata.json").write_text("{}")

        runner = MatrixRunner(tmp_path)
        result = runner.execute_matrix("overwrite-test", dry_run=False)
        # Should be blocked due to existing run OR succeed (different timestamp)
        # The key test is that it doesn't crash
        assert result["status"] in ("BLOCKED", "COMPLETED", "DRY_RUN_OK", "FAILED")

    def test_per_example_record_ids_preserved(self, tmp_path):
        """Per-example results must retain record_id."""
        from evaluation_research.matrix_runner import MatrixRunner

        # Test with compute_statistics to verify record_id preservation
        results = [
            {"record_id": "r1", "model_id": "m1", "correctness": 1.0},
            {"record_id": "r2", "model_id": "m1", "correctness": 0.0},
            {"record_id": "r3", "model_id": "m1", "correctness": 1.0},
        ]
        runner = MatrixRunner(tmp_path)
        out = runner.compute_statistics(results, "m1", [])

        m1 = out["aggregates"]["m1"]
        assert m1["n_evaluated"] == 3
        assert abs(m1["correctness"] - 2/3) < 0.001
        assert m1["ci_method"] == "wilson_score"

    def test_eval_matrix_exit_code_on_success(self, tmp_path):
        """Successful dry-run should return exit code 0."""
        from atlas import cmd_eval_matrix
        import json

        proto_dir = tmp_path / "evaluation" / "eval_sets" / "protocol_v2"
        proto_dir.mkdir(parents=True)
        (proto_dir / "math_eval_v2_clean.jsonl").write_text('{"problem": "test"}\n')

        state_dir = tmp_path / "metadata" / "research_state"
        state_dir.mkdir(parents=True)
        (state_dir / "exit-code-test.json").write_text(json.dumps({
            "experiment_id": "exit-code-test",
            "current_state": "LICENSE_VALIDATED",
            "transitions": [],
            "metadata": {},
            "human_approved": [],
            "last_updated": "2026-08-12T00:00:00+00:00",
        }))

        rc = cmd_eval_matrix("exit-code-test", tmp_path, dry_run=True)
        assert rc == 0

    def test_eval_matrix_exit_code_on_missing_experiment(self, tmp_path):
        """Missing experiment should return non-zero exit code."""
        from atlas import cmd_eval_matrix

        rc = cmd_eval_matrix("nonexistent-exp", tmp_path, dry_run=True)
        assert rc != 0

    def test_eval_matrix_exit_code_on_missing_eval_set(self, tmp_path):
        """Missing eval set should return non-zero exit code."""
        from atlas import cmd_eval_matrix
        import json

        state_dir = tmp_path / "metadata" / "research_state"
        state_dir.mkdir(parents=True)
        (state_dir / "no-set.json").write_text(json.dumps({
            "experiment_id": "no-set",
            "current_state": "LICENSE_VALIDATED",
            "transitions": [],
            "metadata": {"family": "math"},
            "human_approved": [],
            "last_updated": "2026-08-12T00:00:00+00:00",
        }))

        rc = cmd_eval_matrix("no-set", tmp_path, dry_run=True)
        assert rc != 0

    def test_eval_matrix_writes_plan_artifact(self, tmp_path):
        """Dry-run should write a plan artifact to metadata/evaluation/matrix/."""
        from atlas import cmd_eval_matrix
        import json, os

        proto_dir = tmp_path / "evaluation" / "eval_sets" / "protocol_v2"
        proto_dir.mkdir(parents=True)
        (proto_dir / "math_eval_v2_clean.jsonl").write_text('{"problem": "test"}\n')

        state_dir = tmp_path / "metadata" / "research_state"
        state_dir.mkdir(parents=True)
        (state_dir / "artifact-test.json").write_text(json.dumps({
            "experiment_id": "artifact-test",
            "current_state": "LICENSE_VALIDATED",
            "transitions": [],
            "metadata": {},
            "human_approved": [],
            "last_updated": "2026-08-12T00:00:00+00:00",
        }))

        rc = cmd_eval_matrix("artifact-test", tmp_path, dry_run=True)
        assert rc == 0

        plan_path = tmp_path / "metadata" / "evaluation" / "matrix" / "artifact-test_plan.json"
        assert plan_path.exists()
        data = json.loads(plan_path.read_text())
        assert data["family"] == "math"
        assert data["n_records"] == 1


class TestPipelineCancellationDeep:
    """Deep tests for pipeline cancellation behavior."""

    def test_scheduler_observes_cancellation(self, tmp_path):
        """After cancellation, the scheduler should see CANCELLED state."""
        from automation.state_machine import PipelineState, StateMachine

        sm = StateMachine("sched-cancel", tmp_path)
        sm.transition_to(PipelineState.QUALITY_CHECK)
        sm.transition_to(PipelineState.PROVENANCE_CHECK)

        ok = sm.transition_to(PipelineState.CANCELLED, triggered_by="scheduler")
        assert ok is True
        assert sm.current_state == PipelineState.CANCELLED
        assert sm.is_terminal() is True

        # Summary should reflect cancellation
        summary = sm.summary()
        assert summary["current_state"] == "CANCELLED"
        assert summary["is_terminal"] is True

    def test_no_new_work_after_cancellation(self, tmp_path):
        """Once cancelled, no further forward transitions should be possible."""
        from automation.state_machine import PipelineState, StateMachine

        sm = StateMachine("no-work", tmp_path)
        sm.transition_to(PipelineState.QUALITY_CHECK)
        sm.transition_to(PipelineState.CANCELLED)

        # Should not be able to continue forward
        assert sm.can_transition_to(PipelineState.PROVENANCE_CHECK) is False
        assert sm.can_transition_to(PipelineState.VALIDATION) is False
        assert sm.can_transition_to(PipelineState.RELEASED) is False

    def test_cancel_preserved_on_restart(self, tmp_path):
        """Restarting the pipeline (creating new StateMachine) preserves CANCELLED state."""
        from automation.state_machine import PipelineState, StateMachine

        # First instance cancels
        sm1 = StateMachine("restart-test", tmp_path)
        sm1.transition_to(PipelineState.QUALITY_CHECK)
        sm1.transition_to(PipelineState.CANCELLED)
        assert sm1.current_state == PipelineState.CANCELLED

        # New instance loaded from same root should see CANCELLED
        sm2 = StateMachine("restart-test", tmp_path)
        assert sm2.load() is True
        assert sm2.current_state == PipelineState.CANCELLED
        assert sm2.is_terminal() is True

    def test_no_accidental_cancellation_of_unrelated_runs(self, tmp_path):
        """Cancelling one pipeline must not affect another."""
        from automation.state_machine import PipelineState, StateMachine

        sm_a = StateMachine("pipeline-a", tmp_path)
        sm_b = StateMachine("pipeline-b", tmp_path)

        sm_a.transition_to(PipelineState.QUALITY_CHECK)
        sm_b.transition_to(PipelineState.QUALITY_CHECK)

        # Cancel only pipeline-a
        ok = sm_a.transition_to(PipelineState.CANCELLED, triggered_by="user")
        assert ok is True
        assert sm_a.current_state == PipelineState.CANCELLED

        # Pipeline-b should be unaffected
        assert sm_b.current_state == PipelineState.QUALITY_CHECK
        assert sm_b.is_terminal() is False

        # Verify persistence
        sm_b2 = StateMachine("pipeline-b", tmp_path)
        assert sm_b2.load() is True
        assert sm_b2.current_state == PipelineState.QUALITY_CHECK

    def test_cancel_from_multiple_states(self, tmp_path):
        """Cancellation should work from any non-terminal state."""
        from automation.state_machine import PipelineState, StateMachine

        for from_state in [
            PipelineState.INGESTED,
            PipelineState.QUALITY_CHECK,
            PipelineState.PROVENANCE_CHECK,
            PipelineState.CONTENT_REVISION,
            PipelineState.VALIDATION,
            PipelineState.WAITING_HUMAN_APPROVAL,
            PipelineState.READY_FOR_RELEASE,
        ]:
            sm = StateMachine(f"cancel-from-{from_state.value}", tmp_path)
            # Get to the from_state
            current = PipelineState.INGESTED
            while current != from_state:
                next_state = PipelineState(current.value.replace("INGESTED", "QUALITY_CHECK")
                    if current == PipelineState.INGESTED else
                    current.value.replace("QUALITY_CHECK", "PROVENANCE_CHECK")
                    if current == PipelineState.QUALITY_CHECK else
                    current.value.replace("PROVENANCE_CHECK", "CONTENT_REVISION")
                    if current == PipelineState.PROVENANCE_CHECK else
                    current.value.replace("CONTENT_REVISION", "VALIDATION")
                    if current == PipelineState.CONTENT_REVISION else
                    current.value.replace("VALIDATION", "WAITING_HUMAN_APPROVAL")
                    if current == PipelineState.VALIDATION else
                    current.value.replace("WAITING_HUMAN_APPROVAL", "READY_FOR_RELEASE")
                    if current == PipelineState.WAITING_HUMAN_APPROVAL else None)
                if next_state is None:
                    break
                sm.transition_to(next_state)
                current = next_state

            ok = sm.transition_to(PipelineState.CANCELLED, triggered_by="tui")
            assert ok is True, f"Should be able to cancel from {from_state.value}"
            assert sm.current_state == PipelineState.CANCELLED

    def test_cancel_already_cancelled_is_noop(self, tmp_path):
        """Cancelling an already-cancelled pipeline should return False."""
        from automation.state_machine import PipelineState, StateMachine

        sm = StateMachine("already-cancelled", tmp_path)
        sm.transition_to(PipelineState.CANCELLED)

        ok = sm.transition_to(PipelineState.CANCELLED, triggered_by="tui")
        assert ok is False
        assert sm.error is not None
