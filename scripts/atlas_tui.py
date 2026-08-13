#!/usr/bin/env python3
"""Atlas TUI Control Plane — terminal UI for the Atlas dataset foundation.

The TUI is a control plane and observability layer. It reads state from
existing Atlas JSON files and dispatches mutations to the existing CLI.
It does NOT duplicate scheduler, FSM, or evaluation logic.

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
from rich.spinner import Spinner
from rich.live import Live

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from tui_backend import TuiBackend, RunStatus


# ---------------------------------------------------------------------------
# View IDs
# ---------------------------------------------------------------------------

VIEW_DASHBOARD = "dashboard"
VIEW_RESEARCH = "research"
VIEW_EXPERIMENTS = "experiments"
VIEW_BENCHMARKS = "benchmarks"
VIEW_RUNS = "runs"
VIEW_SYSTEM = "system"
VIEW_LOGS = "logs"

ALL_VIEWS = [VIEW_DASHBOARD, VIEW_RESEARCH, VIEW_EXPERIMENTS, VIEW_BENCHMARKS,
             VIEW_RUNS, VIEW_SYSTEM, VIEW_LOGS]

# Main menu items: (label, target_view)
MAIN_MENU = [
    ("Benchmarks", VIEW_BENCHMARKS),
    ("Research", VIEW_RESEARCH),
    ("Experiments", VIEW_EXPERIMENTS),
    ("Pipelines", VIEW_RUNS),
    ("System", VIEW_SYSTEM),
    ("Logs", VIEW_LOGS),
]

# Reverse map: view_id -> menu index
_VIEW_TO_MENU: dict[str, int] = {v: i for i, (_, v) in enumerate(MAIN_MENU)}


# ---------------------------------------------------------------------------
# Main TUI class
# ---------------------------------------------------------------------------


class AtlasTui:
    """Terminal control plane for Atlas."""

    def __init__(self) -> None:
        self.console = Console()
        self.backend = TuiBackend()
        self.current_view = VIEW_DASHBOARD
        self.selected_row = 0
        self._menu_index = 0
        self.log_filter = ""
        self.research_exp_index = 0
        self.benchmark_index = 0
        self.experiment_index = 0
        self.run_index = 0
        self.running = True
        self.paused = False
        self._modal_type: str | None = None
        self._modal_msg: str = ""
        self._modal_confirm: bool = False
        self._pending_action: str | None = None
        self._log_offset = 0
        self._log_paused = False

    # ------------------------------------------------------------------
    # Keyboard input (non-blocking, single-key)
    # ------------------------------------------------------------------

    def _read_key(self, timeout: float | None = 0.05) -> str | None:
        """Read a single keypress without requiring Enter.

        Returns the key string (including escape sequences for arrow keys),
        or None if no key was pressed within the timeout.
        A timeout of None blocks until a key is available.
        """
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
                    # Peek for escape sequence (arrow keys are ESC [ A/B/C/D)
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
            # Fallback for non-TTY or platforms without termios
            try:
                ready, _, _ = select.select([sys.stdin], [], [], timeout)
                if ready:
                    return sys.stdin.read(1)
            except (OSError, ValueError):
                pass
            return None

    # ------------------------------------------------------------------
    # State tracking for change detection
    # ------------------------------------------------------------------

    def _state_snapshot(self) -> tuple:
        """Return a hashable snapshot of state relevant to rendering."""
        return (
            self.current_view,
            self._menu_index,
            self.research_exp_index,
            self.benchmark_index,
            self.experiment_index,
            self.run_index,
            self._log_offset,
            self.log_filter,
            self.paused,
            self._modal_type,
        )

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _status_style(self, status: str) -> str:
        styles = {
            "CREATED": "dim", "CONFIGURED": "blue",
            "TRAINING_STARTED": "yellow", "TRAINING_COMPLETED": "green",
            "TRAINING_FAILED": "red", "EVALUATION_STARTED": "cyan",
            "EVALUATION_COMPLETED": "green", "EVALUATION_FAILED": "red",
            "ANALYSIS_COMPLETED": "green",
            "HOLD": "yellow", "CANCELLED": "red",
            "RUNNING": "yellow", "NOT_STARTED": "dim",
            "PASS": "green", "FAIL": "red",
            "INCONCLUSIVE": "yellow",
        }
        return styles.get(status.upper(), "white")

    def _panel(self, content, title: str, border_style: str = "cyan") -> Panel:
        return Panel(content, title=f"[bold {border_style}]{title}[/bold {border_style}]", border_style=border_style)

    # ------------------------------------------------------------------
    # Header / footer
    # ------------------------------------------------------------------

    def _render_header(self) -> Panel:
        view_label = self.current_view.upper()
        title = Text(f" ATLAS CONTROL PLANE ", style="bold cyan")
        title.append(f" [{view_label}] ", style="bold yellow")
        if self.paused:
            title.append(" [PAUSED]", style="bold red")
        info_text = Text(
            " q:quit  m:menu  r:refresh  h:help  p:pause"
            "  j/k or ↓/↑ navigate  Enter: select  Esc: back",
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
    # Dashboard (main menu)
    # ------------------------------------------------------------------

    def _render_dashboard(self) -> Panel:
        if self._menu_index >= len(MAIN_MENU):
            self._menu_index = 0
        if self._menu_index < 0:
            self._menu_index = len(MAIN_MENU) - 1

        lines: list[str] = []
        for i, (label, _view) in enumerate(MAIN_MENU):
            marker = Text(" >", style="bold yellow") if i == self._menu_index else Text("  ")
            style = "bold yellow" if i == self._menu_index else "white"
            lines.append(f"{marker} {label}")

        nav = Text("↑↓/jk Navigate  Enter: Open  Esc: Help  q:Quit  r:Refresh", style="dim")
        return Panel(
            Group(
                Text("\n".join(lines)),
                Rule(),
                nav,
            ),
            title="[bold on cyan] ATLAS CONTROL PLANE [/bold on cyan]",
            border_style="cyan",
        )

    # ------------------------------------------------------------------
    # Research view
    # ------------------------------------------------------------------

    def _render_research(self) -> Panel:
        states = self.backend.get_research_states()
        if not states:
            return self._panel(
                "[dim]No research experiments found.\n\n"
                "  atlas benchmark discover --register\n"
                "  atlas eval calibrate-policy --eval-file <path> --family math --alphas 1.5 2.0\n",
                "Research FSM", "yellow",
            )

        exp_ids = list(states.keys())
        if self.research_exp_index >= len(exp_ids):
            self.research_exp_index = 0
        if self.research_exp_index < 0:
            self.research_exp_index = 0
        exp_id = exp_ids[self.research_exp_index]
        data = states[exp_id]
        gate = self.backend.get_research_gate(exp_id)

        table = Table(title=f"Research: {exp_id}", box=box.ROUNDED, show_header=True)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_row("Current State", gate.state if gate else data.get("current_state", "?"))
        table.add_row("Last Updated", data.get("last_updated", "")[:19] if data.get("last_updated") else "—")
        table.add_row("Transitions", str(len(data.get("transitions", []))))
        table.add_row("At Approval Gate", "YES" if (gate and gate.is_approval_gate) else "No")
        table.add_row("Approved By", gate.approved_by if gate and gate.approved_by else "—")
        table.add_row("Next States", ", ".join(gate.next_states) if gate and gate.next_states else "—")
        transitions = data.get("transitions", [])
        if transitions:
            last = transitions[-1]
            table.add_row("Last Transition", f"{last.get('from_state', '')} → {last.get('to_state', '')}")
            table.add_row("Triggered By", last.get("triggered_by", ""))
        if gate and gate.action_required:
            table.add_row("Action Required", gate.action_required)

        nav = Text("←/→ navigate | a:approve gate | r:refresh", style="dim")
        return Panel(Group(table, nav), title="[bold yellow]Research FSM[/bold yellow]", border_style="yellow")

    # ------------------------------------------------------------------
    # Experiments view
    # ------------------------------------------------------------------

    def _render_experiments(self) -> Panel:
        experiments = self.backend.get_experiments()
        if not experiments:
            return self._panel("[dim]No experiments registered.[/dim]", "Experiments", "magenta")

        if self.experiment_index >= len(experiments):
            self.experiment_index = 0
        if self.experiment_index < 0:
            self.experiment_index = 0

        table = Table(box=box.ROUNDED, show_header=True)
        table.add_column("ID", style="cyan", max_width=28)
        table.add_column("Phase", width=10)
        table.add_column("Family", width=8)
        table.add_column("Target", width=10)
        table.add_column("Status", width=12)
        table.add_column("Correct", width=10)
        table.add_column("CI 95%", width=14)
        table.add_column("G-POL", width=8)
        table.add_column("Trunc%", width=8)
        table.add_column("N", width=8)

        for i, exp in enumerate(experiments):
            rs = "bold" if i == self.experiment_index else None
            ss = self._status_style(exp.status)
            ci = f"{exp.ci_lower:.3f}–{exp.ci_upper:.3f}" if exp.ci_lower is not None and exp.ci_upper is not None else "—"
            gp = "✓" if exp.gpol_pass else ("✗" if exp.gpol_pass is not None else "—")
            tr = f"{exp.truncation_rate:.1%}" if exp.truncation_rate is not None else "—"
            n = f"{exp.n_evaluated}/{exp.n_total}" if exp.n_total > 0 else (str(exp.n_evaluated) if exp.n_evaluated else "—")
            table.add_row(
                exp.experiment_id[:26], exp.phase, exp.family, exp.target,
                Text(exp.status, style=ss),
                f"{exp.correctness:.3f}" if exp.correctness is not None else "—",
                ci, gp, tr, n,
                style=rs,
            )

        sel = experiments[self.experiment_index]
        detail_parts = []
        if sel.hold_reason:
            detail_parts.append(Text(f"  Hold: {sel.hold_reason}", style="red"))
        if sel.notes:
            detail_parts.append(Text(f"  Notes: {sel.notes}", style="dim"))
        detail = Group(*detail_parts) if detail_parts else Text("")
        nav = Text("↑/↓ navigate | Enter: inspect | e:evaluate | h:hold", style="dim")
        return Panel(Group(table, detail, nav), title="[bold magenta]Experiments[/bold magenta]", border_style="magenta")

    # ------------------------------------------------------------------
    # Benchmarks view
    # ------------------------------------------------------------------

    def _render_benchmarks(self) -> Panel:
        benchmarks = self.backend.get_benchmarks()
        if not benchmarks:
            return self._panel(
                "[dim]No benchmarks registered.\n\n"
                "  Press 'd' to discover & register benchmarks.[/dim]",
                "Benchmarks", "blue",
            )

        if self.benchmark_index >= len(benchmarks):
            self.benchmark_index = 0
        if self.benchmark_index < 0:
            self.benchmark_index = 0

        table = Table(box=box.ROUNDED, show_header=True)
        table.add_column("ID", style="cyan", max_width=18)
        table.add_column("Status", width=14)
        table.add_column("License", width=12)
        table.add_column("Records", width=10)
        table.add_column("Contamination", width=14)
        table.add_column("Frozen", width=8)
        table.add_column("Category", width=10)

        for i, bm in enumerate(benchmarks):
            rs = "bold" if i == self.benchmark_index else None
            bs = "green" if bm.frozen else ("blue" if bm.status == "REGISTERED" else "yellow")
            table.add_row(
                bm.benchmark_id[:16],
                Text(bm.status, style=bs),
                bm.license,
                str(bm.records) if bm.records is not None else "—",
                bm.contamination,
                "YES" if bm.frozen else "NO",
                bm.category,
                style=rs,
            )

        sel = benchmarks[self.benchmark_index]
        detail_lines = [
            f"  ID:       {sel.benchmark_id}",
            f"  Name:     {sel.name}",
            f"  Status:   {sel.status}",
            f"  License:  {sel.license}",
            f"  Family:   {sel.family or '—'}",
            f"  Risk:     {sel.risk or '—'}",
            f"  URL:      {sel.source_url[:60] if sel.source_url else '—'}",
        ]
        nav = Text("←/→ navigate | d:discover | a:acquire | A:audit | f:freeze | Enter: details", style="dim")
        return Panel(Group(table, Text("\n".join(detail_lines), style="dim"), nav),
                     title="[bold blue]Benchmarks[/bold blue]", border_style="blue")

    # ------------------------------------------------------------------
    # Runs view
    # ------------------------------------------------------------------

    def _render_runs(self) -> Panel:
        run_info = self.backend.get_run_status()
        sys_info = self.backend.get_system_info()

        table = Table(box=box.ROUNDED, show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value")

        sc = {RunStatus.IDLE: "dim", RunStatus.RUNNING: "green", RunStatus.PAUSED: "yellow",
              RunStatus.FAILED: "red", RunStatus.COMPLETED: "blue", RunStatus.CANCELLED: "dim"} \
            .get(run_info.status, "white")
        table.add_row("Status", Text(run_info.status.value.upper(), style=sc))
        table.add_row("Experiment", run_info.experiment or "—")
        table.add_row("Phase", run_info.phase or "—")
        table.add_row("State", run_info.state or "IDLE")
        table.add_row("Records", f"{run_info.records_completed} / {run_info.records_total or '?'}")
        if run_info.throughput > 0:
            table.add_row("Throughput", f"{run_info.throughput:.1f} rec/s")
        if run_info.eta_seconds > 0:
            m, s = divmod(run_info.eta_seconds, 60)
            table.add_row("ETA", f"{m:02d}:{s:02d}")
        table.add_row("Workers", str(run_info.workers) if run_info.workers else "—")
        table.add_row("Errors", str(run_info.errors))
        table.add_row("Retries", str(run_info.retries))
        table.add_row("Checkpoint", run_info.checkpoint[:30] if run_info.checkpoint else "—")
        table.add_row("Started", run_info.started_at[:19] if run_info.started_at else "—")

        warnings = []
        if sys_info.gpu.present and sys_info.gpu.used_mb > sys_info.gpu.total_mb * 0.8:
            warnings.append(f"⚠ GPU VRAM high: {sys_info.gpu.used_mb}MB/{sys_info.gpu.total_mb}MB")
        for proc in sys_info.gpu.processes:
            if proc.get("memory_mb", 0) > 1000:
                warnings.append(f"  Process '{proc['name']}' (PID {proc['pid']}) using {proc['memory_mb']}MB VRAM")

        nav = Text("s:start  p:pause  c:cancel  l:logs  r:refresh", style="dim")
        content = Group(table)
        if warnings:
            content = Group(table, Text("\n".join(warnings), style="red"), nav)
        else:
            content = Group(table, nav)
        return Panel(content, title="[bold green]Current Run[/bold green]", border_style="green")

    # ------------------------------------------------------------------
    # System view
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
            if sys_info.gpu.processes:
                proc_lines = []
                for p in sys_info.gpu.processes:
                    proc_lines.append(f"  PID {p['pid']}: {p['name']} ({p['memory_mb']} MB)")
                table.add_row("GPU Processes", "\n".join(proc_lines))
        else:
            table.add_row("GPU", "Not detected")

        nav = Text("r:refresh", style="dim")
        return Panel(Group(table, nav), title="[bold white]System[/bold white]", border_style="white")

    # ------------------------------------------------------------------
    # Logs view
    # ------------------------------------------------------------------

    def _render_logs(self) -> Panel:
        logs = self.backend.get_logs(limit=40, filter_level=self.log_filter)
        if not logs:
            return self._panel("[dim]No logs found.[/dim]", "Logs", "magenta")

        # Paginate
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
        nav_parts.append(Text("  ↑/↓ scroll  p:pause  l:logs", style="dim"))
        nav = Group(*nav_parts)
        return Panel(Group(table, nav), title="[bold magenta]Logs[/bold magenta]", border_style="magenta")

    # ------------------------------------------------------------------
    # Modal
    # ------------------------------------------------------------------

    def _show_modal(self, mtype: str, msg: str, confirm: bool = False) -> None:
        self._modal_type = mtype
        self._modal_msg = msg
        self._modal_confirm = confirm
        # Do NOT reset _pending_action here — it is set by the caller before
        # invoking this method and must survive until the modal is dismissed.

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
    # Key handling
    # ------------------------------------------------------------------

    def handle_key(self, key: str) -> None:
        # Modal overrides (always first)
        if self._modal_type == "confirm":
            if key.lower() == "y":
                self._execute_pending()
                self._modal_type = None
            elif key.lower() == "n" or key == "escape" or key == "\x1b":
                self._modal_type = None
                self._pending_action = None
            return

        if key in ("escape", "\x1b") and self._modal_type:
            self._modal_type = None
            self._pending_action = None
            return

        # Global keys (always processed, even in modals — except modal overrides above)
        if key == "q":
            self.running = False
            return

        if key == "r":
            self.backend = TuiBackend()
            return

        if key == "h":
            self._show_modal("info", self._help_text())
            return

        if key == "p":
            self.paused = not self.paused
            return

        # Esc goes back to main menu from any sub-view
        if key in ("escape", "\x1b") and self.current_view != VIEW_DASHBOARD:
            self.current_view = VIEW_DASHBOARD
            self._menu_index = 0
            self._log_offset = 0
            return

        # Main menu navigation (dashboard view)
        if self.current_view == VIEW_DASHBOARD:
            if key in ("\x1b[B", "j", "n", "\x1b[C"):  # down
                self._menu_index = (self._menu_index + 1) % len(MAIN_MENU)
            elif key in ("\x1b[A", "k", "b", "\x1b[D"):  # up
                self._menu_index = (self._menu_index - 1) % len(MAIN_MENU)
            elif key in ("Enter", "\r"):
                _, target = MAIN_MENU[self._menu_index]
                self.current_view = target
                self._log_offset = 0
            # Fall through to numeric shortcuts for view switching

        # View-specific actions
        if self.current_view == VIEW_RESEARCH:
            states = self.backend.get_research_states()
            exp_ids = list(states.keys())
            if key in ("\x1b[C", "j", "n", "\x1b[B"):          # right / down / next
                self.research_exp_index = (self.research_exp_index + 1) % max(1, len(exp_ids))
            elif key in ("\x1b[D", "k", "b", "\x1b[A"):        # left / up / prev
                self.research_exp_index = (self.research_exp_index - 1) % max(1, len(exp_ids))
            elif key in ("Enter", "\r"):
                if exp_ids:
                    exp_id = exp_ids[self.research_exp_index]
                    gate = self.backend.get_research_gate(exp_id)
                    state_str = gate.state if gate else states.get(exp_id, {}).get("current_state", "?")
                    self._show_modal("info",
                        f"Research: {exp_id}\n"
                        f"  State: {state_str}\n"
                        f"  Transitions: {len(states.get(exp_id, {}).get('transitions', []))}")
            elif key == "a":
                if exp_ids:
                    exp_id = exp_ids[self.research_exp_index]
                    gate = self.backend.get_research_gate(exp_id)
                    if gate and gate.is_approval_gate:
                        self._pending_action = f"approve_{exp_id}"
                        self._show_modal("confirm",
                            f"Approve gate for '{exp_id}'?\n"
                            f"  State: {gate.state}\n"
                            f"  This is a MANDATORY human approval step.")
                    else:
                        self._show_modal("info", f"'{exp_id}' is not at an approval gate (state: {gate.state if gate else '?'})")

        elif self.current_view == VIEW_EXPERIMENTS:
            experiments = self.backend.get_experiments()
            if key in ("\x1b[B", "j", "n"):          # down / next
                self.experiment_index = min(len(experiments) - 1, self.experiment_index + 1) if experiments else 0
            elif key in ("\x1b[A", "k", "b"):        # up / prev
                self.experiment_index = max(0, self.experiment_index - 1) if experiments else 0
            elif key in ("Enter", "\r"):
                if experiments:
                    exp = experiments[self.experiment_index]
                    ci = f"{exp.ci_lower:.3f}–{exp.ci_upper:.3f}" if exp.ci_lower is not None and exp.ci_upper is not None else "—"
                    trunc = f"{exp.truncation_rate:.1%}" if exp.truncation_rate is not None else "—"
                    self._show_modal("info",
                        f"Experiment: {exp.experiment_id}\n"
                        f"  Phase: {exp.phase}  Family: {exp.family}  Target: {exp.target}\n"
                        f"  Status: {exp.status}\n"
                        f"  Correctness: {exp.correctness if exp.correctness is not None else '—'}\n"
                        f"  CI 95%: {ci}\n"
                        f"  G-POL: {'PASS' if exp.gpol_pass else 'FAIL' if exp.gpol_pass is not None else '—'}\n"
                        f"  Truncation: {trunc}\n"
                        f"  N: {exp.n_evaluated}/{exp.n_total}\n"
                        f"  Hold: {exp.hold_reason or 'none'}")
            elif key == "e":
                if experiments:
                    exp = experiments[self.experiment_index]
                    self._pending_action = f"eval_{exp.experiment_id}"
                    self._show_modal("confirm",
                        f"Run evaluation for '{exp.experiment_id}'?\n"
                        f"  Status: {exp.status}\n"
                        f"  This invokes the existing evaluation engine.")
            elif key == "H":
                if experiments:
                    exp = experiments[self.experiment_index]
                    self._pending_action = f"hold_{exp.experiment_id}"
                    self._show_modal("confirm",
                        f"Place '{exp.experiment_id}' on HOLD?\n"
                        f"  Current status: {exp.status}")

        elif self.current_view == VIEW_BENCHMARKS:
            benchmarks = self.backend.get_benchmarks()
            if key in ("\x1b[C", "j", "n", "\x1b[B"):          # right / down / next
                self.benchmark_index = min(len(benchmarks) - 1, self.benchmark_index + 1) if benchmarks else 0
            elif key in ("\x1b[D", "k", "b", "\x1b[A"):        # left / up / prev
                self.benchmark_index = (self.benchmark_index - 1) % max(1, len(benchmarks)) if benchmarks else 0
            elif key in ("Enter", "\r"):
                if benchmarks:
                    bm = benchmarks[self.benchmark_index]
                    self._show_modal("info",
                        f"Benchmark: {bm.benchmark_id}\n"
                        f"  Name: {bm.name}\n"
                        f"  Status: {bm.status}\n"
                        f"  License: {bm.license}\n"
                        f"  Records: {bm.records if bm.records else '?'}\n"
                        f"  Contamination: {bm.contamination}\n"
                        f"  Frozen: {'Yes' if bm.frozen else 'No'}")
            elif key == "d":
                self._pending_action = "discover"
                self._show_modal("confirm", "Run 'atlas benchmark discover --register'?\n  This scans for new benchmarks and registers them.")
            elif key == "a":
                if benchmarks:
                    bm = benchmarks[self.benchmark_index]
                    self._pending_action = f"acquire_{bm.benchmark_id}"
                    self._show_modal("confirm", f"Acquire benchmark '{bm.benchmark_id}'? (dry-run mode)")
            elif key == "A":
                if benchmarks:
                    bm = benchmarks[self.benchmark_index]
                    self._pending_action = f"audit_{bm.benchmark_id}"
                    self._show_modal("confirm",
                        f"Run contamination audit for '{bm.benchmark_id}'?\n"
                        f"  This will audit the eval set and update the registry.")
            elif key == "f":
                if benchmarks:
                    bm = benchmarks[self.benchmark_index]
                    if bm.frozen:
                        self._show_modal("info", f"'{bm.benchmark_id}' is already frozen.")
                    else:
                        self._pending_action = f"freeze_{bm.benchmark_id}"
                        self._show_modal("confirm",
                            f"Freeze eval set for '{bm.benchmark_id}'?\n"
                            f"  Requires a passed contamination audit.")

        elif self.current_view == VIEW_RUNS:
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
            elif key == "l":
                self.current_view = VIEW_LOGS

        elif self.current_view == VIEW_LOGS:
            page_size = 30
            logs = self.backend.get_logs(limit=100, filter_level=self.log_filter)
            if key in ("\x1b[B", "j", "n"):          # down / scroll down
                self._log_offset = min(max(0, len(logs) - page_size), self._log_offset + page_size)
            elif key in ("\x1b[A", "k", "b"):        # up / scroll up
                self._log_offset = max(0, self._log_offset - page_size)
            elif key == "g":
                self._log_offset = 0
            elif key == "f":
                filters = ["", "INFO", "WARN", "ERROR"]
                idx = filters.index(self.log_filter) if self.log_filter in filters else 0
                self.log_filter = filters[(idx + 1) % len(filters)]

        # Numeric view shortcuts still work from any view
        view_map = {"1": VIEW_DASHBOARD, "2": VIEW_RESEARCH, "3": VIEW_EXPERIMENTS,
                    "4": VIEW_BENCHMARKS, "5": VIEW_RUNS, "6": VIEW_SYSTEM, "7": VIEW_LOGS}
        if key in view_map:
            self.current_view = view_map[key]
            self._log_offset = 0

    def _execute_pending(self) -> None:
        action = self._pending_action
        if not action:
            self._modal_type = None
            return
        msg = ""
        ok = False
        if action == "discover":
            ok, msg = self.backend.discover_benchmarks(register=True)
        elif action.startswith("acquire_"):
            bm_id = action.replace("acquire_", "")
            ok, msg = self.backend.acquire_benchmark(bm_id, dry_run=True)
        elif action.startswith("approve_"):
            exp_id = action.replace("approve_", "")
            ok, msg = self.backend.approve_research_gate(exp_id, "tui-user")
        elif action.startswith("audit_"):
            bm_id = action.replace("audit_", "")
            eval_file = self.backend.root / "evaluation" / "eval_sets" / "production" / f"{bm_id}_clean.jsonl"
            if eval_file.exists():
                ok, msg = self.backend.audit_contamination(str(eval_file))
            else:
                ok, msg = False, f"No eval set found for {bm_id}. Run discover/acquire first."
        elif action.startswith("eval_"):
            exp_id = action.replace("eval_", "")
            ok, msg = self.backend.evaluate_experiment(exp_id)
        elif action.startswith("hold_"):
            exp_id = action.replace("hold_", "")
            ok, msg = self.backend.hold_experiment(exp_id, "Held from TUI")
        elif action.startswith("freeze_"):
            bm_id = action.replace("freeze_", "")
            ok, msg = self.backend.freeze_benchmark(bm_id)
        elif action == "start_run":
            ok, msg = self.backend.start_pipeline()
        elif action == "cancel_run":
            ok, msg = self.backend.cancel_pipeline()
        else:
            msg = f"Unknown action: {action}"

        self._modal_type = "info"
        self._modal_msg = msg + ("\n  Result: OK" if ok else ("\n  Result: FAILED" if not ok and msg else ""))
        self._pending_action = None

    def _help_text(self) -> str:
        return (
            "ATLAS TUI CONTROL PLANE — Help\n"
            "══════════════════════════════\n\n"
            "Main Menu (Dashboard):\n"
            "  ↑↓ / jk   Navigate menu items\n"
            "  Enter     Open selected view\n"
            "  Esc       Show this help\n\n"
            "Global:\n"
            "  q    Quit\n"
            "  r    Refresh (reload state)\n"
            "  h    Help\n"
            "  p    Pause tick (freeze display)\n"
            "  Esc  Back to main menu\n\n"
            "Research (view):\n"
            "  ↑↓ / jk  Navigate experiments\n"
            "  Enter    Inspect experiment\n"
            "  a    Approve gate (MANDATORY human approval)\n\n"
            "Experiments (view):\n"
            "  ↑↓ / jk  Navigate\n"
            "  Enter  Inspect details\n"
            "  e    Run evaluation (requires confirmation)\n"
            "  H    Place on HOLD\n\n"
            "Benchmarks (view):\n"
            "  ↑↓ / jk  Navigate\n"
            "  Enter  Inspect benchmark\n"
            "  d    Discover & register all benchmarks\n"
            "  a    Acquire selected benchmark (dry-run)\n"
            "  A    View contamination audit status\n"
            "  f    Freeze eval set (requires audit pass)\n\n"
            "Runs (view):\n"
            "  s    Start pipeline via orchestrator\n"
            "  c    Cancel run (requires confirmation)\n"
            "  l    Jump to logs\n\n"
            "Logs (view):\n"
            "  ↑↓ / jk  Scroll\n"
            "  g    Go to top\n"
            "  f    Cycle filter: ALL → INFO → WARN → ERROR\n\n"
            "Number shortcuts (any view): 1=Menu 2=Research 3=Exp 4=Bench 5=Runs 6=Sys 7=Logs\n\n"
            "Safety:\n"
            "  All destructive actions require Y/n confirmation\n"
            "  Human approval is mandatory at FSM gates\n"
            "  No automatic process killing\n"
            "  Progress bars reflect real state only\n"
        )

    # ------------------------------------------------------------------
    # Main render loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.console.clear()
        self.console.print("[bold cyan]Starting Atlas Control Plane...[/bold cyan]")
        self.console.print("")

        # Detect TTY for key handling
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

    def _render_once(self) -> None:
        """Render a single frame to the console."""
        self.console.clear()

        # Header
        view_label = self.current_view.upper()
        title = Text(f" ATLAS CONTROL PLANE ", style="bold cyan")
        title.append(f" [{view_label}] ", style="bold yellow")
        if self.paused:
            title.append(" [PAUSED]", style="bold red")
        info_text = Text(
            " q:quit  m:menu  r:refresh  h:help  p:pause"
            "  j/k or ↓/↑ navigate  Enter: select  Esc: back",
            style="dim",
        )
        self.console.print(Panel(Group(title, Rule(), info_text), border_style="cyan", box=box.ROUNDED))
        self.console.print("")

        # Main view
        if self.current_view == VIEW_DASHBOARD:
            self.console.print(self._render_dashboard())
        elif self.current_view == VIEW_RESEARCH:
            self.console.print(self._render_research())
        elif self.current_view == VIEW_EXPERIMENTS:
            self.console.print(self._render_experiments())
        elif self.current_view == VIEW_BENCHMARKS:
            self.console.print(self._render_benchmarks())
        elif self.current_view == VIEW_RUNS:
            self.console.print(self._render_runs())
        elif self.current_view == VIEW_SYSTEM:
            self.console.print(self._render_system())
        elif self.current_view == VIEW_LOGS:
            self.console.print(self._render_logs())

        self.console.print("")

        # Footer
        sys_info = self.backend.get_system_info()
        parts = []
        parts.append(f" CPU: {sys_info.cpu_cores}c")
        parts.append(f" RAM: {sys_info.ram_used_mb // 1024}/{sys_info.ram_total_mb // 1024}GB")
        if sys_info.gpu.present:
            vram_pct = sys_info.gpu.used_mb / max(1, sys_info.gpu.total_mb) * 100
            color = "red" if vram_pct > 80 else "yellow" if vram_pct > 60 else "green"
            parts.append(Text(f" GPU: {sys_info.gpu.name[:18]}", style=color))
            parts.append(f" VRAM: {sys_info.gpu.used_mb}MB/{sys_info.gpu.total_mb}MB")
        self.console.print(Panel(Text("  ".join(str(p) for p in parts), style="dim"),
                                  border_style="dim", box=box.SIMPLE))

        # Modal overlay
        if self._modal_type:
            self.console.print("")
            if self._modal_type == "confirm":
                self.console.print(Panel(
                    Group(Text(self._modal_msg, style="bold yellow"),
                          Text("  [Y]es  [N]o  (Escape to cancel)", style="dim")),
                    title="[bold red] CONFIRM [/bold red]", border_style="red"))
            else:
                self.console.print(Panel(Text(self._modal_msg, style="cyan"),
                                          title="[bold blue] INFO [/bold blue]", border_style="blue"))

    def _render_loop_interactive(self) -> None:
        """Interactive loop — render only on state change or key press."""
        self._render_once()  # initial render
        last_state = self._state_snapshot()

        while self.running:
            # Block until a key is pressed (no polling, no repeated redraws)
            key = self._read_key(timeout=None)  # blocks until key available
            if key is None:
                continue

            self.handle_key(key)

            # Only re-render if state actually changed
            if self._state_snapshot() != last_state:
                self._render_once()
                last_state = self._state_snapshot()

    def _render_loop_mock(self) -> None:
        """Demo loop for non-interactive contexts — shows each view briefly."""
        for view in ALL_VIEWS:
            old = self.current_view
            self.current_view = view
            self._render_once()
            time.sleep(1.5)
            self.current_view = old
        self._render_once()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    tui = AtlasTui()
    try:
        tui.run()
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"[red]TUI error: {e}[/red]")
        import traceback
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
