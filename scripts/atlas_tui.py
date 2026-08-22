#!/usr/bin/env python3
"""Atlas TUI — Guided workflow control plane for the Atlas dataset foundation.

The TUI is a lightweight guided workflow runner. It reads state from existing
Atlas JSON files and dispatches mutations to the existing CLI. It does NOT
duplicate scheduler, FSM, or evaluation logic.

Usage:
    python -m scripts.atlas_tui
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import termios
import tty
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.rule import Rule
from rich.columns import Columns

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from tui_backend import TuiBackend, RunStatus, WorkflowDetector, WorkflowStage, PipelineStageStatus

# ---------------------------------------------------------------------------
# View IDs
# ---------------------------------------------------------------------------

VIEW_WORKFLOW = "workflow"
VIEW_DATASET = "dataset"
VIEW_EXPERIMENTS = "experiments"
VIEW_EVALUATION = "evaluation"
VIEW_MODELS = "models"
VIEW_LOGS = "logs"
VIEW_SYSTEM = "system"

# Backward-compat aliases
VIEW_DASHBOARD = VIEW_WORKFLOW
VIEW_RESEARCH = VIEW_EXPERIMENTS  # experiments was closest match
VIEW_BENCHMARKS = VIEW_EVALUATION
VIEW_RUNS = VIEW_DATASET

ALL_VIEWS = [VIEW_WORKFLOW, VIEW_DATASET, VIEW_EXPERIMENTS, VIEW_EVALUATION,
             VIEW_MODELS, VIEW_LOGS, VIEW_SYSTEM]

# Backward-compat: MAIN_MENU for old tests
MAIN_MENU = [
    ("Workflow", VIEW_WORKFLOW),
    ("Dataset", VIEW_DATASET),
    ("Experiments", VIEW_EXPERIMENTS),
    ("Evaluation", VIEW_EVALUATION),
    ("Models", VIEW_MODELS),
    ("Logs", VIEW_LOGS),
    ("System", VIEW_SYSTEM),
]

# Navigation shortcuts: (key, view_id, label)
NAV_SHORTCUTS = [
    ("1", VIEW_WORKFLOW, "Workflow"),
    ("2", VIEW_DATASET, "Dataset"),
    ("3", VIEW_EXPERIMENTS, "Experiments"),
    ("4", VIEW_EVALUATION, "Evaluation"),
    ("5", VIEW_MODELS, "Models"),
    ("L", VIEW_LOGS, "Logs"),
    ("S", VIEW_SYSTEM, "System"),
]

# ---------------------------------------------------------------------------
# Main TUI class
# ---------------------------------------------------------------------------


class AtlasTui:
    """Terminal control plane for Atlas — guided workflow runner."""

    def __init__(self) -> None:
        self.console = Console()
        self.backend = TuiBackend()
        self.current_view = VIEW_WORKFLOW
        self.current_view_index = 0
        self.selected_index: dict[str, int] = {v: 0 for v in ALL_VIEWS}
        self._workflow_dirty = True  # force re-detect on first render

        # Workflow action state
        self._active_action: str | None = None
        self._last_action_result: dict[str, Any] | None = None
        self._preview_mode = False

        # Modal state
        self._modal_type: str | None = None
        self._modal_msg: str = ""
        self._modal_confirm = False
        self._pending_action: str | None = None

        # Log state
        self._log_offset = 0
        self._log_paused = False
        self.log_filter = ""

        # Cancel state
        self._cancel_confirm_open = False

        self.running = True
        self.paused = False

    @property
    def current_view(self) -> str:
        return ALL_VIEWS[self.current_view_index]

    @current_view.setter
    def current_view(self, value: str) -> None:
        if value in ALL_VIEWS:
            self.current_view_index = ALL_VIEWS.index(value)
        self._modal_type = None
        self._modal_msg = ""
        self._modal_confirm = False
        self._pending_action = None
        self._log_offset = 0
        self._log_paused = False
        self.log_filter = ""
        self._preview_mode = False
        self._cancel_confirm_open = False
        # Mark workflow as dirty when entering it
        if value == VIEW_WORKFLOW:
            self._workflow_dirty = True

    # Backward-compat properties
    @property
    def experiment_index(self) -> int:
        return self.selected_index.get(VIEW_EXPERIMENTS, 0)

    @experiment_index.setter
    def experiment_index(self, value: int) -> None:
        self.selected_index[VIEW_EXPERIMENTS] = value

    @property
    def benchmark_index(self) -> int:
        return self.selected_index.get(VIEW_EVALUATION, 0)

    @benchmark_index.setter
    def benchmark_index(self, value: int) -> None:
        self.selected_index[VIEW_EVALUATION] = value

    # ------------------------------------------------------------------
    # Keyboard input
    # ------------------------------------------------------------------

    def _read_key(self, timeout: float | None = 0.05) -> str | None:
        try:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            tty.setraw(fd)
            try:
                ready, _, _ = select.select([sys.stdin], [], [], timeout)
                if not ready:
                    return None
                ch = sys.stdin.read(1)
                if ch == '\x1b':
                    ready2, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if ready2:
                        ch2 = sys.stdin.read(1)
                        if ch2 == '[':
                            ready3, _, _ = select.select([sys.stdin], [], [], 0.05)
                            if ready3:
                                ch3 = sys.stdin.read(1)
                                return f'\x1b[{ch3}'
                        return '\x1b'
                return ch
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except (AttributeError, ImportError, OSError):
            try:
                ready, _, _ = select.select([sys.stdin], [], [], timeout)
                if ready:
                    return sys.stdin.read(1)
            except (OSError, ValueError):
                pass
            return None

    # ------------------------------------------------------------------
    # State snapshot for change detection
    # ------------------------------------------------------------------

    def _state_snapshot(self) -> tuple:
        return (
            self.current_view,
            self.current_view_index,
            tuple(sorted(self.selected_index.items())),
            self._log_offset,
            self.log_filter,
            self.paused,
            self._modal_type,
            self._active_action,
            self._cancel_confirm_open,
            self._workflow_dirty,
        )

    def _go_to_view(self, view_id: str) -> None:
        if view_id not in ALL_VIEWS:
            return
        self.current_view_index = ALL_VIEWS.index(view_id)
        self.current_view = view_id
        if view_id not in self.selected_index:
            self.selected_index[view_id] = 0

    def _go_next_view(self) -> None:
        self.current_view_index = (self.current_view_index + 1) % len(ALL_VIEWS)
        self._go_to_view(ALL_VIEWS[self.current_view_index])

    def _go_prev_view(self) -> None:
        self.current_view_index = (self.current_view_index - 1) % len(ALL_VIEWS)
        self._go_to_view(ALL_VIEWS[self.current_view_index])

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _panel(self, content, title: str, border_style: str = "cyan") -> Panel:
        return Panel(content, title=f"[bold {border_style}]{title}[/bold {border_style}]", border_style=border_style)

    def _status_mark(self, status: str) -> str:
        marks = {
            "done": "✓",
            "running": "●",
            "pending": "○",
            "blocked": "✗",
            "unknown": "?",
        }
        return marks.get(status, "○")

    def _status_color(self, status: str) -> str:
        colors = {
            "done": "green",
            "running": "yellow",
            "pending": "dim",
            "blocked": "red",
            "unknown": "white",
        }
        return colors.get(status, "white")

    # ------------------------------------------------------------------
    # Header / footer
    # ------------------------------------------------------------------

    def _render_header(self) -> Panel:
        view_label = ALL_VIEWS[self.current_view_index].upper()
        title = Text(f" ATLAS ", style="bold cyan")
        title.append(f"[{view_label}]", style="bold yellow")
        if self.paused:
            title.append(" [PAUSED]", style="bold red")
        if self._active_action:
            state = self.backend.executor.get_action_state(self._active_action)
            if state and state.status == "RUNNING":
                title.append(" [RUNNING]", style="bold yellow")
        info_text = Text(
            "← →:view  ↑ ↓:item  Enter:run  P:preview  L:logs  R:refresh  h:help  p:pause  q:quit",
            style="dim",
        )
        return Panel(Group(title, Rule(), info_text), border_style="cyan", box=box.ROUNDED)

    def _render_footer(self) -> Panel:
        sys_info = self.backend.get_system_info()
        parts = []
        parts.append(f" CPU: {sys_info.cpu_cores}c")
        parts.append(f" RAM: {sys_info.ram_used_mb // 1024}/{sys_info.ram_total_mb // 1024}GB")
        if sys_info.gpu.present:
            vram_pct = sys_info.gpu.used_mb / max(1, sys_info.gpu.total_mb) * 100
            color = "red" if vram_pct > 80 else "yellow" if vram_pct > 60 else "green"
            parts.append(Text(f" GPU: {sys_info.gpu.name[:18]}", style=color))
            parts.append(f" VRAM: {sys_info.gpu.used_mb}MB/{sys_info.gpu.total_mb}MB")
        footer = Text("  ".join(str(p) for p in parts), style="dim")
        return Panel(footer, border_style="dim", box=box.SIMPLE)

    # ------------------------------------------------------------------
    # Backward-compat render methods (delegate to new views)
    # ------------------------------------------------------------------

    def _render_dashboard(self) -> Panel:
        """Alias for workflow view (backward compat)."""
        return self._render_workflow()

    def _render_research(self) -> Panel:
        """Alias for experiments view (backward compat)."""
        return self._render_experiments()

    def _render_benchmarks(self) -> Panel:
        """Alias for evaluation view (backward compat)."""
        return self._render_evaluation()

    def _render_runs(self) -> Panel:
        """Alias for dataset view (backward compat)."""
        return self._render_dataset()

    def _render_system_compat(self) -> Panel:
        """Alias for system view (backward compat)."""
        return self._render_system()

    # ------------------------------------------------------------------
    # WORKFLOW view
    # ------------------------------------------------------------------

    def _get_workflow_state(self) -> Any:
        """Get or refresh workflow state."""
        if self._workflow_dirty:
            detector = WorkflowDetector(self.backend.root)
            ws = detector.detect()
            self._workflow_state = ws
            self._workflow_dirty = False
        return getattr(self, '_workflow_state', None)

    def _render_workflow(self) -> Panel:
        ws = self._get_workflow_state()
        if ws is None:
            return self._panel("[dim]Unable to detect workflow state.[/dim]", "Workflow", "yellow")

        # Build stage list
        lines: list[str] = []
        stage_list = list(WorkflowStage)
        current_idx = next((i for i, s in enumerate(stage_list) if s == ws.current_stage), -1)

        for i, stage in enumerate(stage_list):
            ps = next((s for s in ws.stages if s.stage == stage), None)
            if ps is None:
                continue
            mark = self._status_mark(ps.status)
            color = self._status_color(ps.status)
            is_current = (i == current_idx)
            is_next = (i == current_idx + 1)

            if is_current:
                line = Text(f"  {mark} {i+1}. {stage.display_name}  ← CURRENT", style=f"bold yellow")
            elif is_next:
                line = Text(f"  {mark} {i+1}. {stage.display_name}  ← NEXT", style=f"bold {color}")
            elif ps.status == "done":
                line = Text(f"  {mark} {i+1}. {stage.display_name}", style="green")
            elif ps.status == "blocked":
                line = Text(f"  ✗ {i+1}. {stage.display_name}", style="red")
            else:
                line = Text(f"  {mark} {i+1}. {stage.display_name}", style="dim")
            lines.append(line)

        # Next action section
        action_lines: list[str] = []
        action_lines.append("")
        action_lines.append(Text("  NEXT ACTION", style="bold cyan"))
        action_lines.append(Text(f"  {ws.next_action_label}", style="bold"))
        action_lines.append(Text(f"  Command: {' '.join(ws.next_action_command)}", style="dim"))
        action_lines.append(Text(f"  Why: {ws.why_next}", style="dim"))

        if ws.is_blocked:
            action_lines.append(Text("", style="red"))
            action_lines.append(Text("  BLOCKED", style="bold red"))
            for reason in ws.block_reasons[:3]:
                action_lines.append(Text(f"    • {reason}", style="red"))

        # Keyboard shortcuts
        nav = Text(
            "  [Enter] Run   [P] Preview   [L] Logs   [B] Back",
            style="bold yellow",
        )

        # Dataset info in header
        dataset_info = Text(
            f"  Dataset: {ws.dataset_version}  |  {ws.curated_records:,} curated records",
            style="dim",
        )

        content = Group(
            dataset_info,
            Rule(),
            Text("  WORKFLOW", style="bold cyan"),
            Group(*lines),
            Group(*action_lines),
            Rule(),
            nav,
        )
        return Panel(content, border_style="cyan", box=box.ROUNDED)

    def _render_workflow_preview(self) -> Panel:
        ws = self._get_workflow_state()
        if ws is None:
            return self._panel("[dim]No workflow state.[/dim]", "Preview", "yellow")

        lines = [
            Text(f"  PREVIEW: {ws.next_action_label.upper()}", style="bold cyan"),
            Text(""),
            Text(f"  Dataset:      {ws.dataset_version}", style="bold"),
            Text(f"  Command:      {' '.join(ws.next_action_command)}", style="yellow"),
            Text(""),
            Text("  Expected outputs:", style="bold"),
        ]

        # Show expected outputs based on action
        if "training-view" in ws.next_action_command:
            lines.append(Text("    metadata/views/<version>/{qwen,llama,deepseek}/train.jsonl", style="dim"))
            lines.append(Text("    metadata/views/<version>/view_manifest.json", style="dim"))
        elif "eval" in ws.next_action_command or "matrix" in ws.next_action_command:
            lines.append(Text("    metadata/evaluation/matrix/<experiment>_<timestamp>/", style="dim"))
            lines.append(Text("    Per-example results and aggregate metrics", style="dim"))
        elif "release" in ws.next_action_command:
            lines.append(Text("    metadata/releases/<version>_release.json", style="dim"))
            lines.append(Text("    Release bundle with checksums", style="dim"))
        elif "automation-runner" in ws.next_action_command:
            lines.append(Text("    metadata/pipeline_state/<pipeline_id>.json", style="dim"))
            lines.append(Text("    Stage artifacts based on pipeline state", style="dim"))
        else:
            lines.append(Text(f"    {ws.next_action_preview}", style="dim"))

        lines.append(Text(""))
        lines.append(Text("  Existing data will NOT be modified.", style="yellow"))
        lines.append(Text("  [Enter] Run   [Esc] Cancel", style="bold yellow"))

        return Panel(Group(*lines), title="[bold cyan] PREVIEW [/bold cyan]", border_style="cyan")

    def _render_workflow_complete(self) -> Panel:
        if not self._last_action_result:
            return self._render_workflow()

        result = self._last_action_result
        ws = self._get_workflow_state()

        lines: list[str] = []
        status_style = "green" if result.get("success") else "red"
        status_icon = "✓" if result.get("success") else "✗"
        lines.append(Text(f"  {status_icon} {'COMPLETE' if result.get('success') else 'FAILED'}", style=f"bold {status_style}"))
        lines.append(Text(""))
        lines.append(Text(f"  Action:     {result.get('label', 'Unknown')}", style="bold"))
        lines.append(Text(f"  Duration:   {result.get('duration', '?')}", style="dim"))
        lines.append(Text(f"  Exit code:  {result.get('exit_code', '?')}", style="dim"))

        if result.get("stdout"):
            lines.append(Text("", style="bold"))
            lines.append(Text("  Output:", style="bold"))
            for line in result["stdout"].splitlines()[-10:]:
                if line.strip():
                    lines.append(Text(f"    {line[:80]}", style="dim"))

        if result.get("stderr"):
            lines.append(Text("", style="bold"))
            lines.append(Text("  Errors:", style="red"))
            for line in result["stderr"].splitlines()[-5:]:
                if line.strip():
                    lines.append(Text(f"    {line[:80]}", style="red"))

        if ws:
            lines.append(Text("", style="bold"))
            lines.append(Text("  Next:", style="bold cyan"))
            lines.append(Text(f"    {ws.next_action_label}", style="yellow"))
            lines.append(Text(f"    {' '.join(ws.next_action_command)}", style="dim"))

        lines.append(Text("", style="bold"))
        lines.append(Text("  [Enter] Continue   [L] Logs   [B] Back   [R] Refresh", style="bold yellow"))

        return Panel(Group(*lines),
                     title=f"[bold {status_style}] ACTION {status_icon} [/bold {status_style}]",
                     border_style=status_style)

    def _render_workflow_blocked(self) -> Panel:
        ws = self._get_workflow_state()
        if ws is None:
            return self._render_workflow()

        lines = [
            Text("  BLOCKED", style="bold red"),
            Text(""),
            Text("  The next action cannot run yet.", style="red"),
            Text("  Missing prerequisites:", style="red"),
        ]
        for reason in ws.block_reasons[:5]:
            lines.append(Text(f"    • {reason}", style="red"))

        lines.append(Text(""))
        lines.append(Text("  [B] Back   [R] Refresh", style="bold yellow"))

        return Panel(Group(*lines), title="[bold red] BLOCKED [/bold red]", border_style="red")

    # ------------------------------------------------------------------
    # DATASET view
    # ------------------------------------------------------------------

    def _render_dataset(self) -> Panel:
        ws = self._get_workflow_state()
        if ws is None:
            return self._panel("[dim]No workflow state.[/dim]", "Dataset", "blue")

        table = Table(box=box.ROUNDED, show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")

        # Dataset version info
        table.add_row("Current Version", ws.dataset_version)
        table.add_row("Curated Records", f"{ws.curated_records:,}")

        # Release info
        release_index = self.backend.root / "metadata" / "release_index.json"
        if release_index.exists():
            try:
                data = json.loads(release_index.read_text())
                releases = data.get("releases", [])
                if releases:
                    latest = releases[-1]
                    table.add_row("Latest Release", latest.get("version", ""))
                    table.add_row("Release Records", f"{latest.get('total_records', 0):,}")
                    table.add_row("Gates Passed", "Yes" if latest.get("gates_passed") else "No")
            except (json.JSONDecodeError, KeyError):
                pass

        # Training readiness
        readiness = self.backend.root / "metadata" / "training_readiness_report.json"
        if readiness.exists():
            try:
                rd = json.loads(readiness.read_text())
                verdict = rd.get("verdict", "unknown")
                gate_summary = rd.get("gate_summary", {})
                table.add_row("Training Readiness", verdict)
                table.add_row("Gates Ready", str(gate_summary.get("ready", 0)))
                table.add_row("Gates Blocked", str(gate_summary.get("blocked", 0)))
            except (json.JSONDecodeError, KeyError):
                pass

        nav = Text("← →: change view  R:refresh  B:back to workflow", style="dim")
        return Panel(Group(table, nav), title="[bold blue]Dataset[/bold blue]", border_style="blue")

    # ------------------------------------------------------------------
    # EXPERIMENTS view (preserved from original)
    # ------------------------------------------------------------------

    def _render_experiments(self) -> Panel:
        experiments = self.backend.get_experiments()
        if not experiments:
            return self._panel("[dim]No experiments registered.[/dim]", "Experiments", "magenta")

        idx = self.selected_index.get(VIEW_EXPERIMENTS, 0)
        if idx >= len(experiments):
            idx = 0
        if idx < 0:
            idx = 0
        self.selected_index[VIEW_EXPERIMENTS] = idx

        table = Table(box=box.ROUNDED, show_header=True)
        table.add_column("ID", style="cyan", max_width=28)
        table.add_column("Phase", width=10)
        table.add_column("Family", width=8)
        table.add_column("Target", width=10)
        table.add_column("Status", width=12)
        table.add_column("N", width=8)

        statuses = {"HOLD": "yellow", "NOT_STARTED": "dim", "TRAINING_COMPLETED": "green",
                    "EVALUATION_COMPLETED": "green", "COMPLETED": "green", "FAILED": "red",
                    "RUNNING": "yellow", "CREATED": "dim"}

        for i, exp in enumerate(experiments):
            rs = "bold" if i == idx else None
            ss = statuses.get(exp.status.upper(), "white")
            n = f"{exp.n_evaluated}/{exp.n_total}" if exp.n_total > 0 else str(exp.n_evaluated) if exp.n_evaluated else "—"
            table.add_row(
                exp.experiment_id[:26], exp.phase, exp.family, exp.target,
                Text(exp.status, style=ss), n,
                style=rs,
            )

        sel = experiments[idx]
        detail_parts = []
        if sel.hold_reason:
            detail_parts.append(Text(f"  Hold: {sel.hold_reason}", style="red"))
        if sel.notes:
            detail_parts.append(Text(f"  Notes: {sel.notes}", style="dim"))
        detail = Group(*detail_parts) if detail_parts else Text("")
        nav = Text("↑↓ navigate  Enter: inspect  ←→: change view  B:back", style="dim")
        return Panel(Group(table, detail, nav), title="[bold magenta]Experiments[/bold magenta]", border_style="magenta")

    # ------------------------------------------------------------------
    # EVALUATION view
    # ------------------------------------------------------------------

    def _render_evaluation(self) -> Panel:
        benchmarks = self.backend.get_benchmarks()
        experiments = self.backend.get_experiments()

        lines: list[str] = []
        lines.append(Text("  BENCHMARKS", style="bold cyan"))

        if not benchmarks:
            lines.append(Text("  No benchmarks registered.", style="dim"))
        else:
            for i, bm in enumerate(benchmarks[:10]):
                marker = " ▶ " if i == self.selected_index.get(VIEW_EVALUATION, 0) else "   "
                frozen = " [FROZEN]" if bm.frozen else ""
                lines.append(Text(f"{marker}{bm.benchmark_id}{frozen}  ({bm.status})"))

        lines.append(Text(""))
        lines.append(Text("  EXPERIMENTS WITH EVALUATION", style="bold cyan"))
        eval_exps = [e for e in experiments if e.correctness is not None]
        if not eval_exps:
            lines.append(Text("  No evaluation results yet.", style="dim"))
        else:
            for exp in eval_exps[:5]:
                ci = f"{exp.ci_lower:.3f}–{exp.ci_upper:.3f}" if exp.ci_lower is not None else "—"
                lines.append(Text(f"  {exp.experiment_id[:30]}  correctness={exp.correctness:.3f}  CI={ci}"))

        nav = Text("↑↓ navigate  d:discover  ←→: change view  B:back", style="dim")
        return Panel(Group(*lines), title="[bold green]Evaluation[/bold green]", border_style="green")

    # ------------------------------------------------------------------
    # MODELS view
    # ------------------------------------------------------------------

    def _render_models(self) -> Panel:
        views_dir = self.backend.root / "metadata" / "views"
        lines: list[str] = []
        lines.append(Text("  TRAINING VIEWS", style="bold cyan"))

        if not views_dir.exists():
            lines.append(Text("  No training views generated yet.", style="dim"))
        else:
            for vdir in sorted(views_dir.iterdir()):
                if not vdir.is_dir():
                    continue
                manifest = vdir / "view_manifest.json"
                if manifest.exists():
                    try:
                        data = json.loads(manifest.read_text())
                        lines.append(Text(f"  {vdir.name}: {data.get('train_records', '?')} train, {data.get('eval_records', '?')} eval", style="green"))
                        for model, info in data.get("models", {}).items():
                            lines.append(Text(f"    {model}: {info.get('records', '?')} records", style="dim"))
                    except (json.JSONDecodeError, KeyError):
                        lines.append(Text(f"  {vdir.name}: (unreadable manifest)", style="yellow"))
                else:
                    lines.append(Text(f"  {vdir.name}: (no manifest)", style="dim"))

        # Check for release bundles
        bundles_dir = self.backend.root / "metadata" / "release_bundles"
        if bundles_dir.exists():
            lines.append(Text(""))
            lines.append(Text("  RELEASE BUNDLES", style="bold cyan"))
            for bdir in sorted(bundles_dir.iterdir()):
                if bdir.is_dir():
                    manifest = bdir / "manifest.json"
                    if manifest.exists():
                        try:
                            data = json.loads(manifest.read_text())
                            lines.append(Text(f"  {bdir.name}: {data.get('record_count', '?')} records", style="green"))
                        except (json.JSONDecodeError, KeyError):
                            lines.append(Text(f"  {bdir.name}: (unreadable)", style="dim"))

        nav = Text("← →: change view  B:back  R:refresh", style="dim")
        return Panel(Group(*lines), title="[bold yellow]Models & Views[/bold yellow]", border_style="yellow")

    # ------------------------------------------------------------------
    # LOGS view
    # ------------------------------------------------------------------

    def _render_logs(self) -> Panel:
        logs = self.backend.get_logs(limit=40, filter_level=self.log_filter)
        if not logs:
            return self._panel("[dim]No logs found.[/dim]", "Logs", "magenta")

        page_size = 30
        start = self._log_offset
        page = logs[start:start + page_size]

        table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        table.add_column("Time", width=12)
        table.add_column("Level", width=8)
        table.add_column("Component", width=14)
        table.add_column("Message", max_width=55)

        for evt in page:
            ls = {"DEBUG": "dim", "INFO": "green", "WARN": "yellow", "ERROR": "red"} \
                 .get(evt.level.upper(), "white")
            table.add_row(
                evt.timestamp[:19] if evt.timestamp else "",
                Text(evt.level, style=ls),
                evt.component,
                evt.message[:80],
            )

        nav_parts = [Text(f"  page {start // page_size + 1}/{(len(logs) + page_size - 1) // page_size}", style="dim")]
        if self.log_filter:
            nav_parts.append(Text(f"  filter: {self.log_filter}  [f] cycle", style="yellow"))
        else:
            nav_parts.append(Text("  [f] filter", style="dim"))
        nav_parts.append(Text("  ↑/↓ scroll  ←/→: change view  p:pause", style="dim"))
        nav = Group(*nav_parts)
        return Panel(Group(table, nav), title="[bold magenta]Logs[/bold magenta]", border_style="magenta")

    # ------------------------------------------------------------------
    # SYSTEM view (preserved)
    # ------------------------------------------------------------------

    def _render_system(self) -> Panel:
        sys_info = self.backend.get_system_info()
        table = Table(box=box.ROUNDED, show_header=True)
        table.add_column("Resource", style="cyan")
        table.add_column("Value")

        table.add_row("CPU Cores", str(sys_info.cpu_cores))
        table.add_row("RAM Total", f"{sys_info.ram_total_mb // 1024} GB")
        table.add_row("RAM Used", f"{sys_info.ram_used_mb} MB")
        table.add_row("RAM Available", f"{sys_info.ram_available_mb} MB")
        table.add_row("Disk Free", f"{sys_info.disk_free_gb:.1f} GB")
        table.add_row("Python", sys_info.python_version)

        if sys_info.gpu.present:
            table.add_row("GPU Model", sys_info.gpu.name)
            table.add_row("GPU Count", str(sys_info.gpu.count))
            table.add_row("VRAM Total", f"{sys_info.gpu.total_mb} MB")
            table.add_row("VRAM Used", f"{sys_info.gpu.used_mb} MB")
            table.add_row("VRAM Free", f"{sys_info.gpu.free_mb} MB")
        else:
            table.add_row("GPU", "Not detected")

        nav = Text("← →: change view  R:refresh  B:back", style="dim")
        return Panel(Group(table, nav), title="[bold white]System[/bold white]", border_style="white")

    # ------------------------------------------------------------------
    # Action panel (running action)
    # ------------------------------------------------------------------

    def _render_action_panel(self) -> Panel:
        if not self._active_action:
            return Panel("", border_style="default")

        state = self.backend.executor.get_action_state(self._active_action)
        if not state:
            return Panel("", border_style="default")

        elapsed = time.time() - state.start_time
        m, s = divmod(int(elapsed), 60)

        lines: list[str] = []
        lines.append(f"  {state.action_label}")
        lines.append("")
        lines.append(f"  Command: {' '.join(state.command)}")
        lines.append("")

        status_style = {
            "RUNNING": "yellow",
            "COMPLETE": "green",
            "FAILED": "red",
            "CANCELLED": "dim",
            "CANCELLING": "yellow",
        }.get(state.status, "white")
        lines.append(f"  Status: [bold {status_style}]{state.status}[/bold {status_style}]")
        lines.append(f"  Elapsed: {m:02d}:{s:02d}")

        if state.last_status_line:
            lines.append(f"  Activity: {state.last_status_line}")

        if state.status in ("COMPLETE", "FAILED", "CANCELLED"):
            lines.append("")
            if state.status == "COMPLETE":
                lines.append("  Result: Command completed successfully")
                self._last_action_result = {
                    "success": True,
                    "label": state.action_label,
                    "duration": f"{m:02d}:{s:02d}",
                    "exit_code": state.exit_code,
                    "stdout": "\n".join(state.stdout_lines[-20:]) if state.stdout_lines else "",
                    "stderr": "\n".join(state.stderr_lines[-10:]) if state.stderr_lines else "",
                }
            elif state.status == "FAILED":
                lines.append(f"  Exit code: {state.exit_code}")
                if state.stderr_lines:
                    lines.append(f"  Error: {state.stderr_lines[-1]}")
                self._last_action_result = {
                    "success": False,
                    "label": state.action_label,
                    "duration": f"{m:02d}:{s:02d}",
                    "exit_code": state.exit_code,
                    "stdout": "\n".join(state.stdout_lines[-20:]) if state.stdout_lines else "",
                    "stderr": "\n".join(state.stderr_lines[-10:]) if state.stderr_lines else "",
                }
            elif state.status == "CANCELLED":
                lines.append("  Result: Action was cancelled")

        recent: list[str] = []
        for line in state.stdout_lines[-5:]:
            if line.strip():
                recent.append(f"  > {line[:70]}")
        for line in state.stderr_lines[-3:]:
            if line.strip():
                recent.append(f"  ! {line[:70]}")

        if recent:
            lines.append("")
            lines.append("  Recent output:")
            lines.extend(recent)

        if state.status == "RUNNING":
            hint = "  [ESC] cancel  [q] quit"
        elif state.status in ("COMPLETE", "FAILED", "CANCELLED"):
            hint = "  [Enter] dismiss  [Esc] dismiss"
        else:
            hint = ""
        lines.append("")
        lines.append(hint)

        content = Text("\n".join(lines), style="dim")
        panel_title = "ACTIVE ACTION"
        if state.status == "RUNNING":
            panel_title += " — RUNNING"
        return Panel(content, title=f"[bold red]{panel_title}[/bold red]", border_style="red")

    def _render_cancel_confirm(self) -> Panel:
        return Panel(
            Group(
                Text("Cancel running action?", style="bold yellow"),
                Text("  [Y] Cancel  [N] Continue  [Esc] dismiss", style="dim"),
            ),
            title="[bold red] CANCEL ACTION [/bold red]",
            border_style="red",
        )

    # ------------------------------------------------------------------
    # Modal
    # ------------------------------------------------------------------

    def _show_modal(self, mtype: str, msg: str, confirm: bool = False) -> None:
        self._modal_type = mtype
        self._modal_msg = msg
        self._modal_confirm = confirm

    def _render_modal(self) -> Panel:
        if self._modal_type is None:
            return Panel("", border_style="default")
        if self._modal_type == "confirm":
            return Panel(
                Group(
                    Text(self._modal_msg, style="bold yellow"),
                    Text("  [Y]es  [N]o  ( Escape to cancel )", style="dim"),
                ),
                title="[bold red] CONFIRM [/bold red]",
                border_style="red",
            )
        return Panel(
            Text(self._modal_msg, style="cyan"),
            title="[bold blue] INFO [/bold blue]",
            border_style="blue",
        )

    # ------------------------------------------------------------------
    # Action polling
    # ------------------------------------------------------------------

    def _poll_actions(self) -> None:
        if not self._active_action:
            return
        state = self.backend.executor.get_action_state(self._active_action)
        if state and state.status in ("COMPLETE", "FAILED", "CANCELLED"):
            # Action finished — workflow state needs refresh
            self._workflow_dirty = True

    # ------------------------------------------------------------------
    # Key handling
    # ------------------------------------------------------------------

    def handle_key(self, key: str) -> None:
        # 1. Cancel action confirmation modal
        if self._cancel_confirm_open:
            if key.lower() == "y":
                if self._active_action:
                    self.backend.executor.cancel(self._active_action)
                self._cancel_confirm_open = False
            elif key.lower() == "n" or key in ("escape", "\x1b"):
                self._cancel_confirm_open = False
            return

        # 2. Info modal — dismiss on any key
        if self._modal_type == "info":
            if key in ("escape", "\x1b", "Enter", "\r"):
                self._modal_type = None
            return

        # 3. Confirm modal
        if self._modal_type == "confirm":
            if key.lower() == "y":
                self._execute_pending()
                self._modal_type = None
            elif key in ("Enter", "\r"):
                self._execute_pending()
                self._modal_type = None
            elif key.lower() == "n" or key in ("escape", "\x1b"):
                self._modal_type = None
                self._pending_action = None
            return

        # 4. Global keys
        if key == "q":
            self.running = False
            return

        if key == "r":
            self.backend = TuiBackend()
            self._workflow_dirty = True
            return

        if key == "h":
            self._show_modal("info", self._help_text())
            return

        if key == "p":
            self.paused = not self.paused
            return

        # Preview mode dismissal (before Esc global handler)
        if self._preview_mode:
            if key in ("escape", "\x1b", "Enter", "\r"):
                self._preview_mode = False
            return

        # Esc: close modal or return to workflow
        if key in ("escape", "\x1b"):
            if self._active_action and self.backend.executor.get_action_state(self._active_action):
                self._cancel_confirm_open = True
                return
            if self.current_view != VIEW_WORKFLOW:
                self._go_to_view(VIEW_WORKFLOW)
                return
            return

        # 5. Numeric/view shortcuts
        view_map = {"1": VIEW_WORKFLOW, "2": VIEW_DATASET, "3": VIEW_EXPERIMENTS,
                    "4": VIEW_EVALUATION, "5": VIEW_MODELS, "6": VIEW_LOGS, "7": VIEW_SYSTEM}
        if key in view_map:
            self._go_to_view(view_map[key])
            return

        # Letter shortcuts for logs/system
        if key.lower() == "l" and self.current_view != VIEW_LOGS:
            self._go_to_view(VIEW_LOGS)
            return
        if key == "L" and self.current_view != VIEW_LOGS:
            self._go_to_view(VIEW_LOGS)
            return
        if key == "S" and self.current_view != VIEW_SYSTEM:
            self._go_to_view(VIEW_SYSTEM)
            return

        # Back action (b) — go to workflow
        if key.lower() == "b" and self.current_view != VIEW_WORKFLOW:
            self._go_to_view(VIEW_WORKFLOW)
            return

        # 6. Arrow key navigation — LEFT/RIGHT always changes view
        if key == "\x1b[C":  # RIGHT
            self._go_next_view()
            return
        if key == "\x1b[D":  # LEFT
            self._go_prev_view()
            return

        # 7. View-specific handling
        if self.current_view == VIEW_WORKFLOW:
            self._handle_workflow_key(key)
            return

        if self.current_view == VIEW_EXPERIMENTS:
            self._handle_experiments_key(key)
            return

        if self.current_view == VIEW_RESEARCH:
            self._handle_research_key(key)
            return

        if self.current_view == VIEW_EVALUATION:
            self._handle_evaluation_key(key)
            return

        if self.current_view == VIEW_BENCHMARKS:
            self._handle_benchmarks_key(key)
            return

        if self.current_view == VIEW_LOGS:
            self._handle_logs_key(key)
            return

        if self.current_view == VIEW_DATASET or self.current_view == VIEW_RUNS:
            self._handle_runs_key(key)
            return

    def _handle_runs_key(self, key: str) -> None:
        """Handle keys in the runs/dataset view (backward compat)."""
        if key == "s":
            self._pending_action = "start_run"
            self._show_modal("confirm",
                "Start the Atlas pipeline?\n"
                "  This invokes the existing automation orchestrator.")
        elif key == "c":
            self._pending_action = "cancel_run"
            self._show_modal("confirm",
                "CANCEL the current run?\n"
                "  This requests the orchestrator to stop. Cannot be undone.")
        elif key.lower() == "l":
            self._go_to_view(VIEW_LOGS)
        return

    def _handle_workflow_key(self, key: str) -> None:
        """Handle keys in the workflow view."""
        # Preview mode
        if self._preview_mode:
            if key in ("escape", "\x1b", "Enter", "\r"):
                self._preview_mode = False
            return

        # Completion screen
        if self._last_action_result:
            if key in ("escape", "\x1b", "Enter", "\r"):
                self._last_action_result = None
                self._workflow_dirty = True
            elif key.lower() == "l":
                self._go_to_view(VIEW_LOGS)
            elif key.lower() == "b":
                self._last_action_result = None
                self._workflow_dirty = True
            elif key == "r":
                self._last_action_result = None
                self.backend = TuiBackend()
                self._workflow_dirty = True
            return

        # Normal workflow: Enter = run, P = preview
        if key in ("Enter", "\r"):
            ws = self._get_workflow_state()
            if ws and not ws.is_blocked:
                self._pending_action = "run_workflow"
                self._show_modal("confirm",
                    f"Run: {ws.next_action_label}?\n"
                    f"  Command: {' '.join(ws.next_action_command)}\n"
                    f"  This will execute the next pipeline stage.")
            elif ws and ws.is_blocked:
                self._show_modal("info",
                    f"Blocked: {ws.next_action_label}\n"
                    + ("\n".join(f"  • {r}" for r in ws.block_reasons[:3])))
            return

        if key.lower() == "p":
            ws = self._get_workflow_state()
            if ws:
                self._preview_mode = True
            return

        if key.lower() == "l":
            self._go_to_view(VIEW_LOGS)
            return

    def _handle_experiments_key(self, key: str) -> None:
        experiments = self.backend.get_experiments()
        if key in ("\x1b[B", "j", "n"):  # DOWN
            self.selected_index[VIEW_EXPERIMENTS] = min(len(experiments) - 1, self.selected_index.get(VIEW_EXPERIMENTS, 0) + 1) if experiments else 0
        elif key in ("\x1b[A", "k", "b"):  # UP
            self.selected_index[VIEW_EXPERIMENTS] = max(0, self.selected_index.get(VIEW_EXPERIMENTS, 0) - 1) if experiments else 0
        elif key in ("Enter", "\r"):
            if experiments:
                exp = experiments[self.selected_index.get(VIEW_EXPERIMENTS, 0)]
                self._show_modal("info",
                    f"Experiment: {exp.experiment_id}\n"
                    f"  Phase: {exp.phase}  Family: {exp.family}  Target: {exp.target}\n"
                    f"  Status: {exp.status}\n"
                    f"  Hold: {exp.hold_reason or 'none'}")
        elif key == "e":
            if experiments:
                exp = experiments[self.selected_index.get(VIEW_EXPERIMENTS, 0)]
                self._pending_action = f"eval_{exp.experiment_id}"
                self._show_modal("confirm",
                    f"Run evaluation for '{exp.experiment_id}'?\n"
                    f"  Status: {exp.status}\n"
                    f"  This invokes the existing evaluation engine.")
        elif key == "H":
            if experiments:
                exp = experiments[self.selected_index.get(VIEW_EXPERIMENTS, 0)]
                self._pending_action = f"hold_{exp.experiment_id}"
                self._show_modal("confirm",
                    f"Place '{exp.experiment_id}' on HOLD?\n"
                    f"  Current status: {exp.status}")
        return

    def _handle_research_key(self, key: str) -> None:
        """Handle keys in the research view (backward compat)."""
        states = self.backend.get_research_states()
        exp_ids = list(states.keys())
        if key in ("\x1b[B", "j", "n"):  # DOWN
            self.selected_index[VIEW_RESEARCH] = min(len(exp_ids) - 1, self.selected_index.get(VIEW_RESEARCH, 0) + 1) if exp_ids else 0
        elif key in ("\x1b[A", "k", "b"):  # UP
            self.selected_index[VIEW_RESEARCH] = max(0, self.selected_index.get(VIEW_RESEARCH, 0) - 1) if exp_ids else 0
        elif key == "a":
            if exp_ids:
                exp_id = exp_ids[self.selected_index.get(VIEW_RESEARCH, 0)]
                gate = self.backend.get_research_gate(exp_id)
                if gate and gate.is_approval_gate:
                    self._pending_action = f"approve_{exp_id}"
                    self._show_modal("confirm",
                        f"Approve gate for '{exp_id}'?\n"
                        f"  State: {gate.state}\n"
                        f"  This is a MANDATORY human approval step.")
                else:
                    self._show_modal("info", f"'{exp_id}' is not at an approval gate (state: {gate.state if gate else '?'})")
        return

    def _handle_benchmarks_key(self, key: str) -> None:
        """Handle keys in the benchmarks view (backward compat)."""
        benchmarks = self.backend.get_benchmarks()
        if key in ("\x1b[B", "j", "n"):  # DOWN
            self.selected_index[VIEW_BENCHMARKS] = min(len(benchmarks) - 1, self.selected_index.get(VIEW_BENCHMARKS, 0) + 1) if benchmarks else 0
        elif key in ("\x1b[A", "k", "b"):  # UP
            self.selected_index[VIEW_BENCHMARKS] = max(0, self.selected_index.get(VIEW_BENCHMARKS, 0) - 1) if benchmarks else 0
        elif key == "d":
            self._pending_action = "discover"
            self._show_modal("confirm", "Run 'atlas benchmark discover --register'?\n  This scans for new benchmarks and registers them.")
        elif key == "a":
            if benchmarks:
                bm = benchmarks[self.selected_index.get(VIEW_BENCHMARKS, 0)]
                self._pending_action = f"acquire_{bm.benchmark_id}"
                self._show_modal("confirm", f"Acquire benchmark '{bm.benchmark_id}'? (dry-run mode)")
        elif key == "A":
            if benchmarks:
                bm = benchmarks[self.selected_index.get(VIEW_BENCHMARKS, 0)]
                self._pending_action = f"audit_{bm.benchmark_id}"
                self._show_modal("confirm",
                    f"Run contamination audit for '{bm.benchmark_id}'?\n"
                    f"  This will audit the eval set and update the registry.")
        elif key == "f":
            if benchmarks:
                bm = benchmarks[self.selected_index.get(VIEW_BENCHMARKS, 0)]
                if bm.frozen:
                    self._show_modal("info", f"'{bm.benchmark_id}' is already frozen.")
                else:
                    self._pending_action = f"freeze_{bm.benchmark_id}"
                    self._show_modal("confirm",
                        f"Freeze eval set for '{bm.benchmark_id}'?\n"
                        f"  Requires a passed contamination audit.")
        return

    def _handle_evaluation_key(self, key: str) -> None:
        benchmarks = self.backend.get_benchmarks()
        if key in ("\x1b[B", "j", "n"):  # DOWN
            self.selected_index[VIEW_EVALUATION] = min(len(benchmarks) - 1, self.selected_index.get(VIEW_EVALUATION, 0) + 1) if benchmarks else 0
        elif key in ("\x1b[A", "k", "b"):  # UP
            self.selected_index[VIEW_EVALUATION] = max(0, self.selected_index.get(VIEW_EVALUATION, 0) - 1) if benchmarks else 0
        elif key == "d":
            self._pending_action = "discover"
            self._show_modal("confirm", "Run 'atlas benchmark discover --register'?\n  This scans for new benchmarks and registers them.")
        return

    def _handle_logs_key(self, key: str) -> None:
        page_size = 30
        logs = self.backend.get_logs(limit=100, filter_level=self.log_filter)
        if key in ("\x1b[B", "j", "n"):  # DOWN
            self._log_offset = min(max(0, len(logs) - page_size), self._log_offset + page_size)
        elif key in ("\x1b[A", "k", "b"):  # UP
            self._log_offset = max(0, self._log_offset - page_size)
        elif key == "g":
            self._log_offset = 0
        elif key == "f":
            filters = ["", "INFO", "WARN", "ERROR"]
            idx = filters.index(self.log_filter) if self.log_filter in filters else 0
            self.log_filter = filters[(idx + 1) % len(filters)]
        return

    def _execute_pending(self) -> None:
        action = self._pending_action
        if not action:
            self._modal_type = None
            return

        action_id = f"{action}_{int(time.time() * 1000)}"
        label = ""
        cmd_args: list[str] = []
        dry_run = False

        if action == "run_workflow":
            ws = self._get_workflow_state()
            if ws:
                label = ws.next_action_label
                cmd_args = list(ws.next_action_command)
                dry_run = False
            else:
                self._modal_type = "info"
                self._modal_msg = "No workflow state available."
                self._pending_action = None
                return
        elif action == "discover":
            label = "Benchmark Discover"
            cmd_args = ["benchmark", "discover", "--register"]
        elif action == "start_run":
            label = "Pipeline Start"
            cmd_args = ["automation-runner", "run", "--pipeline-id", "default"]
        elif action == "cancel_run":
            label = "Pipeline Cancel"
            cmd_args = ["automation-runner", "cancel", "--pipeline-id", "default"]
        elif action.startswith("approve_"):
            exp_id = action.replace("approve_", "")
            label = f"Research Approve — {exp_id}"
            ok, msg = self.backend.approve_research_gate(exp_id, "tui-user")
            self._modal_type = "info"
            self._modal_msg = msg + ("\n  Result: OK" if ok else "\n  Result: FAILED")
            self._pending_action = None
            return
        elif action.startswith("eval_"):
            exp_id = action.replace("eval_", "")
            label = f"Evaluation — {exp_id}"
            cmd_args = ["eval", "matrix", "--experiment", exp_id]
        elif action.startswith("hold_"):
            exp_id = action.replace("hold_", "")
            label = f"Hold Experiment — {exp_id}"
            ok, msg = self.backend.hold_experiment(exp_id, "Held from TUI")
            self._modal_type = "info"
            self._modal_msg = msg + ("\n  Result: OK" if ok else "\n  Result: FAILED")
            self._pending_action = None
            return
        elif action.startswith("acquire_"):
            bm_id = action.replace("acquire_", "")
            label = f"Benchmark Acquire — {bm_id}"
            cmd_args = ["benchmark", "acquire", "--id", bm_id]
            dry_run = True
        elif action.startswith("audit_"):
            bm_id = action.replace("audit_", "")
            label = f"Contamination Audit — {bm_id}"
            eval_file = self.backend.root / "evaluation" / "eval_sets" / "production" / f"{bm_id}_clean.jsonl"
            if eval_file.exists():
                cmd_args = ["benchmark", "audit", "--eval-file", str(eval_file)]
            else:
                self._modal_type = "info"
                self._modal_msg = f"No eval set found for {bm_id}."
                self._pending_action = None
                return
        elif action.startswith("freeze_"):
            bm_id = action.replace("freeze_", "")
            label = f"Freeze Benchmark — {bm_id}"
            eval_file = self.backend.root / "evaluation" / "eval_sets" / "production" / f"{bm_id}_clean.jsonl"
            if eval_file.exists():
                cmd_args = ["benchmark", "audit", "--eval-file", str(eval_file)]
            else:
                self._modal_type = "info"
                self._modal_msg = f"No eval set found for {bm_id}."
                self._pending_action = None
                return
        else:
            self._modal_type = "info"
            self._modal_msg = f"Unknown action: {action}"
            self._pending_action = None
            return

        if cmd_args:
            self.backend.executor.start(action_id, label, cmd_args, dry_run=dry_run)
            self._active_action = action_id
            self._pending_action = None
            self._last_action_result = None  # clear previous result
        else:
            self._modal_type = None

    def _help_text(self) -> str:
        return (
            "ATLAS TUI — Help\n"
            "══════════════════\n\n"
            "Navigation\n"
            "  ← →      Change view (cycle)\n"
            "  1-5      Quick jump to view\n"
            "  L        Jump to Logs\n"
            "  S        Jump to System\n"
            "  B        Back to Workflow\n"
            "  q        Quit\n"
            "  r        Refresh (reload state)\n"
            "  h        Show this help\n"
            "  p        Pause/resume UI refresh\n\n"
            "Workflow View\n"
            "  Enter    Run next action (requires confirmation)\n"
            "  P        Preview next action (command + outputs)\n"
            "  L        View logs\n"
            "  B        Go back to workflow\n\n"
            "After action completes:\n"
            "  Enter    Dismiss result, continue to next step\n"
            "  L        View logs\n"
            "  B        Go back to workflow\n"
            "  R        Refresh state\n\n"
            "Safety\n"
            "  All actions require Y/n confirmation\n"
            "  Esc during running action opens cancel confirmation\n"
            "  Human approval is mandatory at FSM gates\n"
            "  Progress bars reflect real state only\n"
        )

    # ------------------------------------------------------------------
    # Main render loop
    # ------------------------------------------------------------------

    def _render_once(self) -> None:
        """Render a single frame to the console."""
        self.console.clear()

        # Header
        self.console.print(self._render_header())
        self.console.print("")

        # Main view
        if self.current_view == VIEW_WORKFLOW:
            if self._preview_mode:
                self.console.print(self._render_workflow_preview())
            elif self._last_action_result:
                self.console.print(self._render_workflow_complete())
            elif self._get_workflow_state() and self._get_workflow_state().is_blocked:
                self.console.print(self._render_workflow_blocked())
            else:
                self.console.print(self._render_workflow())
        elif self.current_view == VIEW_DATASET:
            self.console.print(self._render_dataset())
        elif self.current_view == VIEW_EXPERIMENTS:
            self.console.print(self._render_experiments())
        elif self.current_view == VIEW_EVALUATION:
            self.console.print(self._render_evaluation())
        elif self.current_view == VIEW_MODELS:
            self.console.print(self._render_models())
        elif self.current_view == VIEW_LOGS:
            self.console.print(self._render_logs())
        elif self.current_view == VIEW_SYSTEM:
            self.console.print(self._render_system())

        self.console.print("")

        # Footer
        self.console.print(self._render_footer())
        self.console.print("")

        # Action panel
        if self._active_action:
            self.console.print(self._render_action_panel())
            self.console.print("")

        # Cancel confirmation modal
        if self._cancel_confirm_open:
            self.console.print(self._render_cancel_confirm())
            self.console.print("")
        # Info/confirm modal overlay
        elif self._modal_type:
            self.console.print(self._render_modal())
            self.console.print("")

    def _render_loop_interactive(self) -> None:
        """Interactive loop — render on state change or when action is running."""
        self._render_once()
        last_state = self._state_snapshot()

        while self.running:
            key = self._read_key(timeout=0.2)
            if key is not None:
                self.handle_key(key)

            self._poll_actions()

            snapshot = self._state_snapshot()
            if snapshot != last_state or self._active_action:
                self._render_once()
                last_state = snapshot

    def _render_loop_mock(self) -> None:
        """Demo loop for non-interactive contexts."""
        for view in ALL_VIEWS:
            old = self.current_view
            old_idx = self.current_view_index
            self.current_view = view
            self.current_view_index = ALL_VIEWS.index(view)
            self._render_once()
            time.sleep(1.5)
            self.current_view = old
            self.current_view_index = old_idx
        self._render_once()

    def run(self) -> None:
        self.console.clear()
        self.console.print("[bold cyan]Starting Atlas Control Plane...[/bold cyan]")
        self.console.print("")

        is_tty = sys.stdin.isatty()

        if not is_tty:
            self.console.print("[yellow]Not a TTY — running in demo/mock mode[/yellow]")
            self.console.print("  (In a real terminal, press keys to interact)\n")
            self._render_loop_mock()
            return

        try:
            self._render_loop_interactive()
        except KeyboardInterrupt:
            self.running = False
        finally:
            self.console.print("\n[green]Atlas Control Plane exited.[/green]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    tui = AtlasTui()
    try:
        tui.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
