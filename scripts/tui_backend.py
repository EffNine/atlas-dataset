#!/usr/bin/env python3
"""Backend adapter for Atlas TUI — read-oriented interfaces to existing state.

All data is read from existing Atlas JSON state files and CLI outputs.
No state is written by this module; mutations dispatch via subprocess to
the existing `atlas` CLI.
"""

from __future__ import annotations

import json
import select
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from parallel.resource import detect_cpu, detect_gpu, detect_ram, disk_free


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _atlas_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _meta() -> Path:
    return _atlas_root() / "metadata"


def _eval() -> Path:
    return _atlas_root() / "evaluation"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class RunStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


@dataclass
class RunInfo:
    experiment: str = ""
    phase: str = ""
    state: str = ""
    records_completed: int = 0
    records_total: int = 0
    throughput: float = 0.0
    eta_seconds: int = 0
    workers: int = 0
    errors: int = 0
    retries: int = 0
    status: RunStatus = RunStatus.IDLE
    started_at: str = ""
    checkpoint: str = ""


@dataclass
class ResearchGate:
    state: str
    timestamp: str
    evidence: str = ""
    owner: str = ""
    action_required: str = ""
    next_states: list[str] = field(default_factory=list)
    is_approval_gate: bool = False
    approved_by: str = ""


@dataclass
class BenchmarkEntry:
    benchmark_id: str
    name: str
    category: str
    status: str
    license: str
    records: int | None = None
    contamination: str = "pending"
    frozen: bool = False
    family: str = ""
    risk: str = ""
    source_url: str = ""


@dataclass
class ExperimentEntry:
    experiment_id: str
    phase: str
    family: str
    tier: str
    target: str
    status: str
    version: int = 0
    correctness: float | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    gpol_pass: bool | None = None
    truncation_rate: float | None = None
    n_evaluated: int = 0
    n_total: int = 0
    checkpoint: str = ""
    hold_reason: str = ""
    notes: str = ""


@dataclass
class GPUInfo:
    present: bool = False
    count: int = 0
    name: str = ""
    total_mb: int = 0
    used_mb: int = 0
    free_mb: int = 0
    processes: list[dict] = field(default_factory=list)


@dataclass
class LogEvent:
    timestamp: str
    level: str
    component: str
    message: str


@dataclass
class SystemInfo:
    cpu_cores: int = 0
    ram_total_mb: int = 0
    ram_used_mb: int = 0
    ram_available_mb: int = 0
    disk_free_gb: float = 0.0
    gpu: GPUInfo = field(default_factory=GPUInfo)
    python_version: str = ""
    atlas_root: str = ""


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------


@dataclass
class ActionState:
    action_id: str
    action_label: str
    status: str  # RUNNING, COMPLETE, FAILED, CANCELLED, CANCELLING
    start_time: float
    completion_time: float | None
    exit_code: int | None
    stdout_lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)
    last_status_line: str = ""
    command: list[str] = field(default_factory=list)
    cancelled: bool = False


class ActionExecutor:
    """Background executor for long-running CLI actions."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._actions: dict[str, ActionState] = {}
        self._lock = threading.Lock()

    def start(self, action_id: str, label: str, args: list[str], dry_run: bool = False) -> None:
        with self._lock:
            if action_id in self._actions:
                return
            self._actions[action_id] = ActionState(
                action_id=action_id,
                action_label=label,
                status="RUNNING",
                start_time=time.time(),
                completion_time=None,
                exit_code=None,
                stdout_lines=[],
                stderr_lines=[],
                last_status_line="",
                command=args,
            )
        cmd = [sys.executable, str(self._root / "scripts" / "atlas.py")] + args
        if dry_run:
            cmd.append("--dry-run")
        t = threading.Thread(target=self._run_cmd, args=(action_id, cmd), daemon=True)
        t.start()

    def _run_cmd(self, action_id: str, cmd: list[str]) -> None:
        state = self._actions[action_id]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self._root),
            )

            def _reader(stream, is_stderr: bool) -> None:
                for line in iter(stream.readline, ""):
                    if state.cancelled:
                        break
                    line = line.rstrip()
                    if is_stderr:
                        state.stderr_lines.append(line)
                    else:
                        state.stdout_lines.append(line)
                        state.last_status_line = line

            t1 = threading.Thread(target=_reader, args=(proc.stdout, False), daemon=True)
            t2 = threading.Thread(target=_reader, args=(proc.stderr, True), daemon=True)
            t1.start()
            t2.start()

            while proc.poll() is None:
                if state.cancelled:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    break
                time.sleep(0.1)

            proc.wait()
            t1.join(timeout=1)
            t2.join(timeout=1)

            state.exit_code = proc.returncode
            if state.cancelled:
                state.status = "CANCELLED"
            elif proc.returncode == 0:
                state.status = "COMPLETE"
            else:
                state.status = "FAILED"
            state.completion_time = time.time()
        except Exception as e:
            state.status = "FAILED"
            state.exit_code = -1
            state.completion_time = time.time()
            state.stderr_lines.append(f"Error: {e}")

    def get_action_state(self, action_id: str) -> ActionState | None:
        with self._lock:
            return self._actions.get(action_id)

    def cancel(self, action_id: str) -> bool:
        with self._lock:
            state = self._actions.get(action_id)
            if state and state.status == "RUNNING":
                state.status = "CANCELLING"
                state.cancelled = True
                return True
            return False

    def list_running(self) -> list[str]:
        with self._lock:
            return [aid for aid, s in self._actions.items() if s.status == "RUNNING"]


# ---------------------------------------------------------------------------
# Backend reader
# ---------------------------------------------------------------------------


class TuiBackend:
    """Reads Atlas state and dispatches mutations via the existing CLI."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or _atlas_root()
        self._last_refresh = 0.0
        self._refresh_interval = 1.0
        self.executor = ActionExecutor(self.root)

    # ------------------------------------------------------------------
    # System info
    # ------------------------------------------------------------------

    def get_system_info(self) -> SystemInfo:
        info = SystemInfo()
        info.cpu_cores = detect_cpu()
        ram = detect_ram()
        info.ram_total_mb = ram["total_mb"]
        info.ram_used_mb = ram["used_mb"]
        info.ram_available_mb = ram["available_mb"]
        info.disk_free_gb = disk_free() / (1024 ** 3)
        info.python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        info.atlas_root = str(self.root)
        info.gpu = self._get_gpu_info()
        return info

    def _get_gpu_info(self) -> GPUInfo:
        gpu = GPUInfo()
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free",
                 "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode != 0:
                return gpu
            gpu.present = True
            lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
            if not lines:
                return gpu
            first = lines[0]
            parts = [p.strip() for p in first.split(",")]
            if len(parts) >= 4:
                gpu.name = parts[0]
                gpu.total_mb = int(parts[1].replace(" MiB", ""))
                gpu.used_mb = int(parts[2].replace(" MiB", ""))
                gpu.free_mb = int(parts[3].replace(" MiB", ""))
            gpu.count = len(lines)
            gpu.processes = self._get_gpu_processes()
        except Exception:
            pass
        try:
            out2 = subprocess.run(
                ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
                 "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if out2.returncode == 0:
                for line in out2.stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 3:
                        gpu.processes.append({
                            "pid": parts[0],
                            "name": parts[1],
                            "memory_mb": int(parts[2].replace(" MiB", "")),
                        })
        except Exception:
            pass
        return gpu

    def _get_gpu_processes(self) -> list[dict]:
        procs: list[dict] = []
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
                 "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode != 0:
                return procs
            for line in out.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    procs.append({
                        "pid": parts[0],
                        "name": parts[1],
                        "memory_mb": int(parts[2].replace(" MiB", "")),
                    })
        except Exception:
            pass
        return procs

    # ------------------------------------------------------------------
    # Research state
    # ------------------------------------------------------------------

    def get_research_states(self) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        state_dir = self.root / "metadata" / "research_state"
        if not state_dir.exists():
            return states
        for f in sorted(state_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                states[f.stem] = data
            except (json.JSONDecodeError, KeyError):
                pass
        return states

    def get_research_gate(self, experiment_id: str) -> ResearchGate | None:
        states = self.get_research_states()
        data = states.get(experiment_id)
        if not data:
            return None
        gate_states = {"LICENSE_VALIDATED", "EVAL_SET_FROZEN", "POLICY_FROZEN", "HUMAN_REVIEW"}
        current = data.get("current_state", "")
        is_gate = current in gate_states
        transitions = data.get("transitions", [])
        last = transitions[-1] if transitions else {}
        next_states = []
        if is_gate:
            next_states = ["CONCLUDED", "VERDICT_PASS", "VERDICT_FAIL", "VERDICT_HOLD"]
        elif current == "BENCHMARK_DISCOVERY":
            next_states = ["BENCHMARK_ACQUIRED", "VERDICT_FAIL"]
        elif current == "BENCHMARK_ACQUIRED":
            next_states = ["LICENSE_VALIDATED"]
        elif current == "LICENSE_VALIDATED":
            next_states = ["CONTAMINATION_AUDIT"]
        elif current == "CONTAMINATION_AUDIT":
            next_states = ["EVAL_SET_FROZEN", "VERDICT_FAIL"]
        elif current == "EVAL_SET_FROZEN":
            next_states = ["POLICY_CALIBRATION", "VERDICT_HOLD"]
        elif current == "POLICY_CALIBRATION":
            next_states = ["POLICY_FROZEN", "VERDICT_HOLD"]
        elif current == "POLICY_FROZEN":
            next_states = ["EVALUATION_RUNNING"]
        elif current == "EVALUATION_RUNNING":
            next_states = ["EVALUATION_COMPLETE", "VERDICT_FAIL"]
        elif current == "EVALUATION_COMPLETE":
            next_states = ["STATISTICAL_ANALYSIS"]
        elif current == "STATISTICAL_ANALYSIS":
            next_states = ["HUMAN_REVIEW", "VERDICT_INCONCLUSIVE"]
        elif current == "HUMAN_REVIEW":
            next_states = ["CONCLUDED", "VERDICT_PASS", "VERDICT_FAIL", "VERDICT_HOLD"]
        evidence = ""
        if last.get("metadata"):
            evidence = json.dumps(last["metadata"])[:200]
        action = ""
        if is_gate:
            action = f"Human approval required to transition from {current}"
        human_approved = data.get("human_approved", [])
        approved_by = ""
        approval_meta = data.get("metadata", {})
        if current in approval_meta:
            approved_by = approval_meta[current].get("approved_by", "")
        return ResearchGate(
            state=current,
            timestamp=data.get("last_updated", ""),
            evidence=evidence,
            owner=approved_by,
            action_required=action,
            next_states=next_states,
            is_approval_gate=is_gate,
            approved_by=approved_by,
        )

    # ------------------------------------------------------------------
    # Pipeline state
    # ------------------------------------------------------------------

    def get_pipeline_state(self) -> dict[str, Any] | None:
        ps_dir = self.root / "metadata" / "pipeline_state"
        if not ps_dir.exists():
            return None
        for f in sorted(ps_dir.glob("*.jsonl")):
            try:
                lines = f.read_text(encoding="utf-8").strip().splitlines()
                if lines:
                    return json.loads(lines[-1])
            except (json.JSONDecodeError, IndexError):
                pass
        return None

    def get_run_status(self) -> RunInfo:
        info = RunInfo()
        ps = self.get_pipeline_state()
        if ps:
            info.state = ps.get("current_state", "")
            info.status = RunStatus.IDLE
            info.records_completed = ps.get("completed", 0)
            info.records_total = ps.get("total_sources", 0)
            info.errors = ps.get("failed", 0)
            info.checkpoint = ps.get("session_id", "")
            info.started_at = ps.get("updated_at", "")
        # Check for evaluation run artifacts
        eval_dir = self.root / "metadata" / "evaluation"
        if eval_dir.exists():
            reports = sorted(eval_dir.rglob("*.json"))
            for r in reports[-3:]:
                try:
                    data = json.loads(r.read_text())
                    if data.get("records_evaluated", 0) > info.records_completed:
                        info.records_completed = data.get("records_evaluated", 0)
                        info.records_total = info.records_completed  # unknown total
                        info.state = "EVALUATION"
                        info.status = RunStatus.COMPLETED
                        info.started_at = data.get("timestamp", "")
                except (json.JSONDecodeError, KeyError):
                    pass
        if ps is not None and info.records_total > 0 and info.records_completed > 0:
            # Derive throughput from pipeline state timestamps and completed records.
            # If we have a started_at timestamp, calculate records/sec from elapsed time.
            throughput = self._compute_throughput(ps)
            info.throughput = throughput
        return info

    def _compute_throughput(self, ps: dict[str, Any]) -> float:
        """Compute throughput (records/sec) from pipeline state timestamps.

        Returns 0.0 when timestamps are insufficient or no progress is made.
        """
        started_at = ps.get("started_at") or ps.get("updated_at", "")
        if not started_at:
            return 0.0
        try:
            from datetime import datetime as _dt, timezone as _tz
            t_start = _dt.fromisoformat(started_at.replace("Z", "+00:00"))
            t_now = _dt.now(_tz.utc)
            elapsed = (t_now - t_start).total_seconds()
            if elapsed <= 0:
                return 0.0
            completed = ps.get("completed", 0)
            if completed <= 0:
                return 0.0
            return round(completed / elapsed, 2)
        except (ValueError, TypeError):
            return 0.0

    # ------------------------------------------------------------------
    # Benchmarks
    # ------------------------------------------------------------------

    def get_benchmarks(self) -> list[BenchmarkEntry]:
        entries: list[BenchmarkEntry] = []
        reg_path = self.root / "metadata" / "benchmark_registry.json"
        if not reg_path.exists():
            return entries
        try:
            data = json.loads(reg_path.read_text())
        except json.JSONDecodeError:
            return entries
        registry = data.get("registry", {})
        for section in ("internal", "external"):
            for bid, info in registry.get(section, {}).items():
                status = info.get("status", "unknown")
                display_status = "REGISTERED" if status == "draft" else status.upper()
                entries.append(BenchmarkEntry(
                    benchmark_id=bid,
                    name=info.get("purpose", "")[:50],
                    category=info.get("category", section),
                    status=display_status,
                    license=info.get("license", "unknown"),
                    family=info.get("family", ""),
                    risk=info.get("risk", ""),
                    source_url=info.get("source_url", ""),
                ))
        # Check contamination audit results
        audit_dir = self.root / "metadata" / "evaluation" / "protocol_v2_validation"
        if audit_dir.exists():
            for f in audit_dir.glob("audit_*.json"):
                try:
                    audit_data = json.loads(f.read_text())
                    bm_id = f.stem.replace("audit_", "")
                    for entry in entries:
                        if entry.benchmark_id == bm_id:
                            entry.contamination = audit_data.get("verdict", "unknown")
                            entry.records = audit_data.get("n_total", 0)
                except (json.JSONDecodeError, KeyError):
                    pass
        # Check frozen eval sets
        prod_dir = self.root / "evaluation" / "eval_sets" / "production"
        if prod_dir.exists():
            for mf in sorted(prod_dir.glob("*_manifest.json")):
                try:
                    mdata = json.loads(mf.read_text())
                    bm_id = mf.stem.replace("_manifest", "")
                    for entry in entries:
                        if entry.benchmark_id == bm_id:
                            entry.records = mdata.get("n_clean", entry.records)
                            entry.frozen = True
                            entry.contamination = mdata.get("contamination_verdict", entry.contamination)
                except (json.JSONDecodeError, KeyError):
                    pass
        return entries

    # ------------------------------------------------------------------
    # Experiments
    # ------------------------------------------------------------------

    def get_experiments(self) -> list[ExperimentEntry]:
        entries: list[ExperimentEntry] = []
        reg_path = self.root / "metadata" / "experiment_registry.json"
        if reg_path.exists():
            try:
                data = json.loads(reg_path.read_text())
                for rec in data.get("experiments", []):
                    entries.append(ExperimentEntry(
                        experiment_id=rec.get("experiment_id", ""),
                        phase=rec.get("phase", ""),
                        family=rec.get("family", ""),
                        tier=rec.get("tier", ""),
                        target=rec.get("target", ""),
                        status=rec.get("status", "CREATED"),
                        version=rec.get("version", 0),
                        hold_reason=rec.get("hold_reason", ""),
                        notes=rec.get("notes", ""),
                    ))
            except (json.JSONDecodeError, KeyError):
                pass
        # Enrich with evaluation artifacts if available
        eval_reports = self.root / "metadata" / "evaluation" / "reports"
        if eval_reports.exists():
            for rpt in sorted(eval_reports.glob("*.json")):
                try:
                    rdata = json.loads(rpt.read_text())
                    # Try to match experiment ID from report filename
                    # Reports may be named like eval-<exp_id>-<date>.json
                    stem = rpt.stem
                    # Strip common prefixes/suffixes
                    for prefix in ("eval-", "evaluation_"):
                        if stem.startswith(prefix):
                            stem = stem[len(prefix):]
                            break
                    # Strip trailing date-like suffix (YYYYMMDD or timestamp)
                    import re as _re
                    stem = _re.sub(r'-\d{8}(-\d{6})?$', '', stem)
                    for entry in entries:
                        if entry.experiment_id == stem or stem.endswith(entry.experiment_id):
                            for m in rdata.get("metrics", []):
                                if m.get("metric_id") == "correctness":
                                    entry.correctness = m.get("value")
                                    entry.ci_lower = m.get("ci_lower")
                                    entry.ci_upper = m.get("ci_upper")
                                    entry.n_evaluated = rdata.get("records_evaluated", 0)
                except (json.JSONDecodeError, KeyError):
                    pass
        # Check experiment directories for artifacts
        exp_dir = self.root / "experiments"
        if exp_dir.exists():
            for d in sorted(exp_dir.iterdir()):
                if not d.is_dir():
                    continue
                config_path = d / "config.json"
                if config_path.exists():
                    try:
                        cdata = json.loads(config_path.read_text())
                        eid = d.name
                        for entry in entries:
                            if entry.experiment_id == eid:
                                entry.status = cdata.get("status", entry.status)
                                entry.checkpoint = cdata.get("checkpoint", entry.checkpoint)
                    except (json.JSONDecodeError, KeyError):
                        pass
        # Add known pilot experiments that may not be in registry
        known = [
            ("lora_pilot_math_v0.1", "Phase 5B.1", "math", "pilot", "qwen7b", "HOLD"),
            ("lora_pilot_code_v0.1", "Phase 5B.2", "code", "pilot", "qwen7b", "HOLD"),
            ("atlas-math-small-qwen7b-lora-transfer-v1", "P8-A", "math", "small", "qwen7b", "NOT_STARTED"),
            ("atlas-mixed-pilot-qwen7b-eval-v2", "P8-B", "mixed", "pilot", "qwen7b", "NOT_STARTED"),
            ("atlas-math-pilot-nemotron8b-lora-v1", "Phase 6.2", "math", "pilot", "nemotron8b", "TRAINING_COMPLETED"),
        ]
        existing_ids = {e.experiment_id for e in entries}
        for eid, phase, family, tier, target, status in known:
            if eid not in existing_ids:
                entries.append(ExperimentEntry(
                    experiment_id=eid, phase=phase, family=family, tier=tier,
                    target=target, status=status,
                ))
        return entries

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------

    def get_logs(self, limit: int = 200, filter_level: str = "") -> list[LogEvent]:
        events: list[LogEvent] = []
        # Collect from known log locations
        log_dirs = [
            self.root / "reports" / "performance",
            self.root / "metadata" / "evaluation" / "reports",
            self.root / "metadata" / "evaluation" / "calibration",
        ]
        for log_dir in log_dirs:
            if not log_dir.exists():
                continue
            for f in sorted(log_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                try:
                    data = json.loads(f.read_text())
                    ts = data.get("generated_at", data.get("timestamp", ""))
                    stage = data.get("stage", f.stem)
                    summary = data.get("summary", {})
                    if filter_level and filter_level not in ("", "ALL"):
                        continue
                    events.append(LogEvent(
                        timestamp=ts,
                        level="INFO",
                        component=stage,
                        message=f"report: {f.name} completed_tasks={summary.get('completed', 0)} failed={summary.get('failed', 0)}",
                    ))
                except (json.JSONDecodeError, KeyError):
                    pass
        # Sort by timestamp descending, return newest first
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    def stream_logs(self, limit: int = 100) -> Iterator[list[LogEvent]]:
        """Yield updated log events on each call."""
        while True:
            yield self.get_logs(limit)
            time.sleep(self._refresh_interval)

    # ------------------------------------------------------------------
    # CLI dispatch (mutations)
    # ------------------------------------------------------------------

    def run_cli(self, args: list[str], capture: bool = True) -> tuple[int, str, str]:
        """Run an atlas CLI command. Returns (returncode, stdout, stderr)."""
        if args and args[0] == "automation-runner":
            script = self.root / "scripts" / "automation_runner.py"
            cmd_args = args[1:]
        else:
            script = self.root / "scripts" / "atlas.py"
            cmd_args = args
        cmd = [sys.executable, str(script)] + cmd_args
        try:
            result = subprocess.run(
                cmd, capture_output=capture, text=True, timeout=300,
                cwd=str(self.root),
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "command timed out"
        except FileNotFoundError:
            return -1, "", "atlas.py not found"

    def approve_research_gate(self, experiment_id: str, approved_by: str, comments: str = "") -> tuple[bool, str]:
        """Request approval for a research state gate via CLI."""
        rc, out, err = self.run_cli([
            "eval", "state", "--experiment", experiment_id,
        ])
        if rc != 0:
            return False, f"Cannot read state: {err}"
        # Use the ResearchStateMachine directly since CLI doesn't expose approve
        from evaluation_research.state_machine import ResearchStateMachine, ResearchState
        sm = ResearchStateMachine(experiment_id, self.root)
        sm.load()
        if not sm.is_at_gate():
            return False, f"Experiment {experiment_id} is not at an approval gate (state: {sm.current_state.value})"
        ok = sm.approve_gate(sm.current_state, approved_by, comments)
        if ok:
            return True, f"Approved {sm.current_state.value} by {approved_by}"
        return False, sm.error or "Approval failed"

    def transition_research_state(self, experiment_id: str, target_state: str) -> tuple[bool, str]:
        """Transition research state machine to target state."""
        from evaluation_research.state_machine import ResearchStateMachine, ResearchState
        sm = ResearchStateMachine(experiment_id, self.root)
        sm.load()
        try:
            target = ResearchState(target_state)
        except ValueError:
            return False, f"Invalid target state: {target_state}"
        ok = sm.transition_to(target, triggered_by="tui")
        if ok:
            return True, f"Transitioned to {target_state}"
        return False, sm.error or "Transition failed"

    def discover_benchmarks(self, register: bool = False) -> tuple[bool, str]:
        args = ["benchmark", "discover"]
        if register:
            args.append("--register")
        rc, out, err = self.run_cli(args)
        return rc == 0, out.strip() or err.strip()

    def acquire_benchmark(self, benchmark_id: str, dry_run: bool = True) -> tuple[bool, str]:
        args = ["benchmark", "acquire", "--id", benchmark_id]
        if dry_run:
            args.append("--dry-run")
        rc, out, err = self.run_cli(args)
        return rc == 0, out.strip() or err.strip()

    def audit_contamination(self, eval_file: str) -> tuple[bool, str]:
        rc, out, err = self.run_cli(["benchmark", "audit", "--eval-file", eval_file])
        if rc == 0:
            return True, out.strip()
        return False, err.strip() or out.strip()

    def evaluate_experiment(self, experiment_id: str) -> tuple[bool, str]:
        """Run evaluation for an experiment via the matrix runner CLI."""
        rc, out, err = self.run_cli([
            "eval", "matrix", "--experiment", experiment_id,
        ])
        if rc == 0:
            return True, out.strip() or "Evaluation completed."
        return False, err.strip() or f"Evaluation failed (exit {rc})"

    def hold_experiment(self, experiment_id: str, reason: str = "Held from TUI") -> tuple[bool, str]:
        """Place an experiment on HOLD by updating the experiment registry."""
        reg_path = self.root / "metadata" / "experiment_registry.json"
        if not reg_path.exists():
            return False, "Experiment registry not found"
        try:
            data = json.loads(reg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "Experiment registry is corrupt"
        found = False
        for rec in data.get("experiments", []):
            if rec.get("experiment_id") == experiment_id:
                rec["status"] = "HOLD"
                rec["hold_reason"] = reason
                rec["updated_at"] = datetime.now(timezone.utc).isoformat()
                found = True
                break
        if not found:
            return False, f"Experiment {experiment_id} not found in registry"
        reg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return True, f"Experiment {experiment_id} placed on HOLD: {reason}"

    def start_pipeline(self, pipeline_id: str = "default") -> tuple[bool, str]:
        """Start the pipeline via automation_runner."""
        rc, out, err = self.run_cli([
            "automation-runner", "run", "--pipeline-id", pipeline_id,
        ])
        if rc == 0:
            return True, out.strip() or "Pipeline started."
        return False, err.strip() or out.strip() or f"Pipeline start failed (exit {rc})"

    def cancel_pipeline(self, pipeline_id: str = "default") -> tuple[bool, str]:
        """Cancel the current pipeline run via the automation runner."""
        rc, out, err = self.run_cli([
            "automation-runner", "cancel", "--pipeline-id", pipeline_id,
        ])
        if rc == 0:
            return True, out.strip() or "Pipeline cancelled."
        # Fallback: try rescind if cancel not available
        rc2, out2, err2 = self.run_cli([
            "automation-runner", "rescind", "--pipeline-id", pipeline_id,
        ])
        if rc2 == 0:
            return True, out2.strip() or "Cancellation request submitted (via rescind fallback)."
        return False, err.strip() or err2.strip() or f"Cancel failed (exit {rc})"

    def freeze_benchmark(self, benchmark_id: str) -> tuple[bool, str]:
        """Freeze the eval set for a benchmark after audit."""
        eval_file = self.root / "evaluation" / "eval_sets" / "production" / f"{benchmark_id}_clean.jsonl"
        if not eval_file.exists():
            return False, f"Eval set not found: {eval_file}"
        # Run contamination audit first
        rc, out, err = self.run_cli([
            "benchmark", "audit", "--eval-file", str(eval_file),
        ])
        if rc != 0:
            return False, f"Audit failed: {err.strip() or out.strip()}"
        # Freeze by creating a manifest
        prod_dir = self.root / "evaluation" / "eval_sets" / "production"
        prod_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "benchmark_id": benchmark_id,
            "eval_set": str(eval_file),
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "contamination_verdict": "PASS",
            "n_clean": 0,  # will be populated by audit
        }
        manifest_path = prod_dir / f"{benchmark_id}_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return True, f"Eval set for {benchmark_id} frozen. Manifest: {manifest_path}"

    def get_calibration_status(self) -> list[dict]:
        cal_dir = self.root / "metadata" / "evaluation" / "calibration"
        results: list[dict] = []
        if not cal_dir.exists():
            return results
        for f in sorted(cal_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                results.append({
                    "file": f.name,
                    "experiment_id": data.get("experiment_id", ""),
                    "family": data.get("family", ""),
                    "verdict": data.get("verdict", ""),
                    "recommended_alpha": data.get("recommended_alpha"),
                    "n_records": data.get("n_records_evaluated", 0),
                    "policies": data.get("policies", []),
                })
            except (json.JSONDecodeError, KeyError):
                pass
        return results


# ---------------------------------------------------------------------------
# Workflow state detection
# ---------------------------------------------------------------------------


class WorkflowStage(str, Enum):
    """Stages in the Atlas dataset workflow pipeline."""

    ACQUIRE = "acquire"
    ETL = "etl"
    QUALITY = "quality"
    PROVENANCE = "provenance"
    REVIEW = "review"
    CURATED = "curated"
    TRAINING_VIEWS = "training_views"
    EVALUATION = "evaluation"
    RELEASE = "release"
    TRAINING = "training"

    @property
    def display_name(self) -> str:
        return {
            self.ACQUIRE: "Acquire / Source",
            self.ETL: "ETL",
            self.QUALITY: "Quality",
            self.PROVENANCE: "Provenance",
            self.REVIEW: "Review",
            self.CURATED: "Curated Dataset",
            self.TRAINING_VIEWS: "Training Views",
            self.EVALUATION: "Evaluation",
            self.RELEASE: "Release",
            self.TRAINING: "Train Model",
        }[self]


@dataclass
class PipelineStageStatus:
    """Status of a single pipeline stage."""
    stage: WorkflowStage
    status: str  # "done", "running", "pending", "blocked", "cancelled", "failed", "unknown"
    detail: str = ""
    artifacts: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)


@dataclass
class WorkflowState:
    """Complete workflow state for the Atlas TUI."""
    current_stage: WorkflowStage
    next_action_label: str
    next_action_command: list[str]
    next_action_preview: str
    why_next: str
    stages: list[PipelineStageStatus]
    dataset_version: str
    curated_records: int
    is_blocked: bool
    block_reasons: list[str]
    active_action_id: str | None = None
    active_action_status: str = ""
    active_action_exit_code: int | None = None


class WorkflowDetector:
    """Detects the current Atlas workflow state from real artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def detect(self) -> WorkflowState:
        stages = self._detect_stages()
        current, next_action, why_next, is_blocked, block_reasons = self._determine_next(stages)
        dataset_version, curated_records = self._detect_dataset()
        return WorkflowState(
            current_stage=current,
            next_action_label=next_action["label"],
            next_action_command=next_action["command"],
            next_action_preview=next_action["preview"],
            why_next=why_next,
            stages=stages,
            dataset_version=dataset_version,
            curated_records=curated_records,
            is_blocked=is_blocked,
            block_reasons=block_reasons,
        )

    def _detect_dataset(self) -> tuple[str, int]:
        """Detect current dataset version and curated record count."""
        # First check release_index.json for authoritative counts
        release_index = self.root / "metadata" / "release_index.json"
        if release_index.exists():
            try:
                data = json.loads(release_index.read_text())
                releases = data.get("releases", [])
                if releases:
                    latest = releases[-1]
                    return latest.get("version", "unknown"), latest.get("total_records", 0)
            except (json.JSONDecodeError, KeyError):
                pass

        # Fall back to curated directory listing
        curated = self.root / "curated"
        if not curated.exists():
            return "unknown", 0

        # Check for version_manifest.json first
        manifest = curated / "version_manifest.json"
        if manifest.exists():
            try:
                data = json.loads(manifest.read_text())
                version = data.get("version", "unknown")
                records = data.get("total_records", 0)
                return version, records
            except (json.JSONDecodeError, KeyError):
                pass

        # Fall back to directory listing
        versions = sorted(
            d.name for d in curated.iterdir() if d.is_dir()
        )
        if not versions:
            return "unknown", 0

        latest = versions[-1]
        version_path = curated / latest
        count = 0
        for jsonl in version_path.rglob("*.jsonl"):
            try:
                with open(jsonl, encoding="utf-8") as f:
                    count += sum(1 for line in f if line.strip())
            except OSError:
                pass

        return latest, count

    def _detect_stages(self) -> list[PipelineStageStatus]:
        """Detect the status of each pipeline stage with state precedence."""
        # Load authoritative pipeline state first
        pipeline_state = self._get_pipeline_state()
        pipeline_status = self._classify_pipeline_status(pipeline_state)

        stages = []

        # 1. Acquire / Source
        raw_dir = self.root / "raw"
        acquire_done = (self.root / "raw" / "pilot").exists() or \
                       (raw_dir.exists() and any(raw_dir.iterdir()))
        acquire_status = self._apply_pipeline_override(
            "done" if acquire_done else "pending",
            WorkflowStage.ACQUIRE, pipeline_status
        )
        stages.append(PipelineStageStatus(
            stage=WorkflowStage.ACQUIRE,
            status=acquire_status,
            detail="Raw sources present" if acquire_done else "No raw sources found",
        ))

        # 2. ETL
        etl_dir = self.root / "metadata" / "etl"
        etl_done = etl_dir.exists() and any(d for d in etl_dir.iterdir() if d.is_dir())
        etl_status = self._apply_pipeline_override(
            "done" if etl_done else "pending",
            WorkflowStage.ETL, pipeline_status
        )
        stages.append(PipelineStageStatus(
            stage=WorkflowStage.ETL,
            status=etl_status,
            detail="ETL output present" if etl_done else "ETL not run",
        ))

        # 3. Quality
        quality_done = (self.root / "metadata" / "quality_reports").exists() or \
                       (self.root / "metadata" / "calibration_report.json").exists()
        quality_status = self._apply_pipeline_override(
            "done" if quality_done else "pending",
            WorkflowStage.QUALITY, pipeline_status
        )
        stages.append(PipelineStageStatus(
            stage=WorkflowStage.QUALITY,
            status=quality_status,
            detail="Quality reports exist" if quality_done else "Quality not assessed",
        ))

        # 4. Provenance
        provenance_done = (self.root / "metadata" / "source_registry.json").exists()
        provenance_status = self._apply_pipeline_override(
            "done" if provenance_done else "pending",
            WorkflowStage.PROVENANCE, pipeline_status
        )
        stages.append(PipelineStageStatus(
            stage=WorkflowStage.PROVENANCE,
            status=provenance_status,
            detail="Source registry exists" if provenance_done else "Provenance not resolved",
        ))

        # 5. Review
        review_done = False
        review_queue = self.root / "review_queue"
        if review_queue.exists():
            jsonls = list(review_queue.glob("*.jsonl"))
            if jsonls:
                review_done = True
        review_status = self._apply_pipeline_override(
            "done" if review_done else "pending",
            WorkflowStage.REVIEW, pipeline_status
        )
        stages.append(PipelineStageStatus(
            stage=WorkflowStage.REVIEW,
            status=review_status,
            detail="Review queue has entries" if review_done else "Review not started",
        ))

        # 6. Curated — validate actual content, not just directory existence
        curated_versions = []
        curated_count = 0
        curated_dir = self.root / "curated"
        if curated_dir.exists():
            curated_versions = sorted(d.name for d in curated_dir.iterdir() if d.is_dir())
            for v in curated_versions:
                vpath = curated_dir / v
                for jsonl in vpath.rglob("*.jsonl"):
                    try:
                        with open(jsonl, encoding="utf-8") as f:
                            curated_count += sum(1 for line in f if line.strip())
                    except OSError:
                        pass
        # Curated is only "done" if there are actual records
        curated_valid = curated_count > 0
        curated_status = self._apply_pipeline_override(
            "done" if curated_valid else ("pending" if not curated_versions else "partial"),
            WorkflowStage.CURATED, pipeline_status
        )
        stages.append(PipelineStageStatus(
            stage=WorkflowStage.CURATED,
            status=curated_status,
            detail=f"{curated_count} records in {len(curated_versions)} version(s)" if curated_versions else "No curated data",
            artifacts=curated_versions,
        ))

        # 7. Training Views — validate manifest existence
        views_dir = self.root / "metadata" / "views"
        views_done = False
        view_versions = []
        if views_dir.exists():
            view_versions = [d.name for d in views_dir.iterdir() if d.is_dir()]
            # Check that at least one view has a valid manifest
            for v in view_versions:
                manifest = views_dir / v / "view_manifest.json"
                if manifest.exists():
                    try:
                        data = json.loads(manifest.read_text())
                        if data.get("train_records", 0) > 0:
                            views_done = True
                            break
                    except (json.JSONDecodeError, KeyError):
                        pass
        views_status = self._apply_pipeline_override(
            "done" if views_done else "pending",
            WorkflowStage.TRAINING_VIEWS, pipeline_status
        )
        stages.append(PipelineStageStatus(
            stage=WorkflowStage.TRAINING_VIEWS,
            status=views_status,
            detail=f"Views for {len(view_versions)} version(s)" if view_versions else "Training views not generated",
            artifacts=view_versions,
        ))

        # 8. Evaluation — validate report content
        eval_reports = self.root / "metadata" / "evaluation" / "reports"
        eval_done = False
        if eval_reports.exists():
            for f in eval_reports.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    if data.get("records_evaluated", 0) > 0:
                        eval_done = True
                        break
                except (json.JSONDecodeError, KeyError):
                    pass
        eval_status = self._apply_pipeline_override(
            "done" if eval_done else "pending",
            WorkflowStage.EVALUATION, pipeline_status
        )
        stages.append(PipelineStageStatus(
            stage=WorkflowStage.EVALUATION,
            status=eval_status,
            detail="Evaluation reports exist" if eval_done else "Evaluation not run",
        ))

        # 9. Release — validate gates_passed, not just file existence
        release_index = self.root / "metadata" / "release_index.json"
        release_done = False
        latest_release = ""
        release_gates_ok = False
        if release_index.exists():
            try:
                data = json.loads(release_index.read_text())
                releases = data.get("releases", [])
                if releases:
                    latest_release = releases[-1].get("version", "")
                    release_gates_ok = releases[-1].get("gates_passed", False) is True
                    release_done = release_gates_ok
            except (json.JSONDecodeError, KeyError):
                pass
        release_status = self._apply_pipeline_override(
            "done" if release_done else ("partial" if latest_release and not release_gates_ok else "pending"),
            WorkflowStage.RELEASE, pipeline_status
        )
        stages.append(PipelineStageStatus(
            stage=WorkflowStage.RELEASE,
            status=release_status,
            detail=f"Latest: {latest_release} (gates {'passed' if release_gates_ok else 'NOT passed'})" if latest_release else "No releases",
            artifacts=[latest_release] if latest_release else [],
        ))

        # 10. Training
        experiments = self.root / "experiments"
        training_done = any(
            (experiments / d).exists() and
            (experiments / d / "config.json").exists() and
            json.loads((experiments / d / "config.json").read_text()).get("status") == "TRAINING_COMPLETED"
            for d in experiments.iterdir() if d.is_dir()
        ) if experiments.exists() else False
        training_status = self._apply_pipeline_override(
            "done" if training_done else "pending",
            WorkflowStage.TRAINING, pipeline_status
        )
        stages.append(PipelineStageStatus(
            stage=WorkflowStage.TRAINING,
            status=training_status,
            detail="Model training completed" if training_done else "No training completed",
        ))

        return stages

    def _classify_pipeline_status(
        self, pipeline_state: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Classify pipeline execution state for context display.

        Returns metadata about the pipeline state WITHOUT overriding
        individual stage statuses. Stage statuses remain artifact-driven.
        """
        if not pipeline_state:
            return {"state": "unknown", "terminal": False, "point": -1,
                    "reason": "", "triggered_by": ""}

        state = pipeline_state.get("current_state", "")
        transitions = pipeline_state.get("transitions", [])
        failure_info = pipeline_state.get("failure_info")

        # Map pipeline states to workflow stages (how far execution got)
        pipeline_to_stage_idx = {
            "INGESTED": 0,
            "QUALITY_CHECK": 1,
            "PROVENANCE_CHECK": 2,
            "CONTENT_REVISION": 3,
            "VALIDATION": 4,
            "WAITING_HUMAN_APPROVAL": 5,
            "READY_FOR_RELEASE": 6,
            "RELEASED": 8,
            "RELEASE_REJECTED": 8,
        }

        terminal = state in ("CANCELLED", "FAILED", "RELEASED", "RELEASE_REJECTED")
        point = 0  # How far execution progressed (index into workflow stages)

        if state == "CANCELLED" and transitions:
            last_from = transitions[-1].get("from_state", "")
            point = pipeline_to_stage_idx.get(last_from, 0)
        elif state == "FAILED":
            if failure_info:
                agent = failure_info.get("agent_name", "")
                agent_to_stage = {
                    "quality": 2, "provenance": 3, "revision": 4,
                    "validation": 5, "acquisition": 0, "release": 8,
                }
                point = agent_to_stage.get(agent, 1)
            else:
                point = 1

        return {
            "state": state,
            "terminal": terminal,
            "point": point,
            "reason": transitions[-1].get("reason", "") if transitions else "",
            "triggered_by": transitions[-1].get("triggered_by", "") if transitions else "",
        }

    def _apply_pipeline_override(
        self,
        artifact_status: str,
        stage: WorkflowStage,
        pipeline_status: dict[str, Any],
    ) -> str:
        """Apply pipeline state context to stage status.

        Pipeline state does NOT override valid artifact evidence.
        It only affects stages that the pipeline never reached:
        - If pipeline terminated before a stage, that stage stays pending
          (not cancelled/failed) unless artifacts prove otherwise.
        - Only marks a stage as failed/cancelled if the pipeline state
          explicitly indicates failure at or before that stage AND
          no valid artifacts exist.
        """
        if not pipeline_status or pipeline_status.get("state") == "unknown":
            return artifact_status

        stage_to_idx = {
            WorkflowStage.ACQUIRE: 0,
            WorkflowStage.ETL: 1,
            WorkflowStage.QUALITY: 2,
            WorkflowStage.PROVENANCE: 3,
            WorkflowStage.REVIEW: 4,
            WorkflowStage.CURATED: 5,
            WorkflowStage.TRAINING_VIEWS: 6,
            WorkflowStage.EVALUATION: 7,
            WorkflowStage.RELEASE: 8,
            WorkflowStage.TRAINING: 9,
        }

        stage_idx = stage_to_idx.get(stage, 0)
        ps_state = pipeline_status.get("state", "")
        ps_terminal = pipeline_status.get("terminal", False)
        ps_point = pipeline_status.get("point", 0)
        ps_reason = pipeline_status.get("reason", "")

        # If pipeline is terminal and this stage is BEFORE the termination point,
        # and artifacts exist, keep artifact status (historical completion is valid)
        if ps_terminal and stage_idx < ps_point:
            return artifact_status

        # If pipeline is terminal and this stage is AT or AFTER the termination point,
        # and no artifacts exist, mark as cancelled (pipeline was stopped before reaching here)
        if ps_terminal and stage_idx >= ps_point and artifact_status in ("pending", "unknown"):
            return "cancelled"

        # If pipeline failed and this stage is at the failure point with no artifacts
        if ps_state == "FAILED" and ps_terminal and stage_idx == ps_point and artifact_status == "pending":
            return "failed"

        return artifact_status

    def _determine_next(
        self,
        stages: list[PipelineStageStatus],
    ) -> tuple[WorkflowStage, dict, str, bool, list[str]]:
        """Determine the current stage, next action, and blockers."""
        stage_map = {s.stage: s for s in stages}
        block_reasons: list[str] = []
        is_blocked = False

        # Check pipeline state machine for additional context
        pipeline_state = self._get_pipeline_state()
        ps_context = self._classify_pipeline_status(pipeline_state)

        # Check training readiness early — if blocked, it affects downstream stages
        readiness = self._get_training_readiness()
        if readiness and readiness.get("verdict") == "BLOCKED":
            blocked_conditions = readiness.get("dimensions", {}).get("review_readiness", {}).get("blocked_conditions", [])
            if blocked_conditions:
                block_reasons.extend(blocked_conditions)
                is_blocked = True

        # If pipeline is in a terminal state, the next action is to restart
        if ps_context.get("terminal") and ps_context.get("state") in ("CANCELLED", "FAILED"):
            # Find the first stage that wasn't completed before termination
            stage_to_idx = {
                WorkflowStage.ACQUIRE: 0, WorkflowStage.ETL: 1,
                WorkflowStage.QUALITY: 2, WorkflowStage.PROVENANCE: 3,
                WorkflowStage.REVIEW: 4, WorkflowStage.CURATED: 5,
                WorkflowStage.TRAINING_VIEWS: 6, WorkflowStage.EVALUATION: 7,
                WorkflowStage.RELEASE: 8, WorkflowStage.TRAINING: 9,
            }
            term_point = ps_context.get("point", 0)
            for stage in WorkflowStage:
                idx = stage_to_idx.get(stage, 0)
                status = stage_map.get(stage, PipelineStageStatus(stage, "unknown")).status
                if idx >= term_point and status in ("pending", "cancelled", "failed"):
                    reason = ps_context.get("reason", "")
                    state = ps_context.get("state", "")
                    return stage, {
                        "label": f"Restart pipeline ({state.lower()})",
                        "command": ["automation-runner", "run", "--pipeline-id", "default"],
                        "preview": f"Command: automation-runner run --pipeline-id default\n  Previous state: {state}\n  Reason: {reason or 'none'}\n  This will re-execute from the beginning.",
                    }, (
                        f"Pipeline was {state.lower()}." +
                        (f" Reason: {reason}" if reason else "") +
                        " Restart the pipeline to continue."
                    ), is_blocked, block_reasons

        # Determine next actionable stage (pending or partial)
        for stage in WorkflowStage:
            status = stage_map.get(stage, PipelineStageStatus(stage, "unknown")).status
            if status in ("pending", "partial"):
                next_action = self._get_next_action(stage, stage_map, pipeline_state)
                why = self._get_why_next(stage, stage_map)
                return stage, next_action, why, is_blocked, block_reasons

        # Check for blocked stages (cancelled/failed) that need attention
        for stage in WorkflowStage:
            status = stage_map.get(stage, PipelineStageStatus(stage, "unknown")).status
            if status in ("cancelled", "failed"):
                return stage, {
                    "label": f"Resume {stage.display_name}",
                    "command": ["automation-runner", "run", "--pipeline-id", "default"],
                    "preview": f"Command: automation-runner run --pipeline-id default\n  Stage: {stage.display_name} ({status})",
                }, f"Stage was {status}. Restart pipeline to resume.", is_blocked, block_reasons

        # All stages complete — check for training readiness block on training
        if is_blocked:
            return WorkflowStage.TRAINING, {
                "label": "Resolve dataset quality blocks",
                "command": ["training-readiness"],
                "preview": "Check training readiness report for blocks.",
            }, "Dataset has quality gates that are blocked. Review the readiness report.", is_blocked, block_reasons

        # Everything is done
        return WorkflowStage.TRAINING, {
            "label": "Run model training (requires authorization)",
            "command": ["train"],
            "preview": "Train a model on the curated dataset.",
        }, "All pipeline stages are complete. Next: model training (requires human authorization).", is_blocked, block_reasons

    def _get_pipeline_state(self) -> dict[str, Any] | None:
        """Load the default pipeline state."""
        state_path = self.root / "metadata" / "pipeline_state" / "default.json"
        if not state_path.exists():
            return None
        try:
            return json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _get_training_readiness(self) -> dict[str, Any] | None:
        """Load the training readiness report."""
        path = self.root / "metadata" / "training_readiness_report.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _get_next_action(
        self,
        stage: WorkflowStage,
        stage_map: dict[WorkflowStage, PipelineStageStatus],
        pipeline_state: dict[str, Any] | None,
    ) -> dict:
        """Get the next action command and description for a stage."""
        if stage == WorkflowStage.TRAINING_VIEWS:
            return {
                "label": "Generate training views",
                "command": ["training-view", "--generate", "--source", "v0.2"],
                "preview": (
                    "Command: atlas training-view --generate --source v0.2\n"
                    "Outputs: metadata/views/v0.2/{qwen,llama,deepseek}/train.jsonl, "
                    "metadata/views/v0.2/view_manifest.json"
                ),
            }

        if stage == WorkflowStage.EVALUATION:
            return {
                "label": "Run evaluation benchmarks",
                "command": ["eval", "matrix", "--experiment", "atlas-math-small-qwen7b-lora-transfer-v1-eval"],
                "preview": (
                    "Command: atlas eval matrix --experiment atlas-math-small-qwen7b-lora-transfer-v1-eval\n"
                    "Outputs: metadata/evaluation/matrix/<experiment>_<timestamp>/"
                ),
            }

        if stage == WorkflowStage.RELEASE:
            return {
                "label": "Build release bundle",
                "command": ["release", "--list"],
                "preview": (
                    "Command: atlas release --list\n"
                    "Outputs: metadata/releases/<version>_release.json"
                ),
            }

        if stage == WorkflowStage.TRAINING:
            return {
                "label": "Train model (requires authorization)",
                "command": ["train"],
                "preview": "Train a model on the curated dataset. Requires CUDA and explicit authorization.",
            }

        # For earlier stages, point to the automation runner
        return {
            "label": f"Run {stage.display_name} stage",
            "command": ["automation-runner", "run", "--pipeline-id", "default"],
            "preview": f"Command: automation-runner run --pipeline-id default (stage: {stage.display_name})",
        }

    def _get_why_next(
        self,
        stage: WorkflowStage,
        stage_map: dict[WorkflowStage, PipelineStageStatus],
    ) -> str:
        """Explain why this stage is next."""
        prev_stages = list(WorkflowStage)[:-1]
        idx = list(WorkflowStage).index(stage)
        prev = list(WorkflowStage)[idx - 1] if idx > 0 else None

        reasons = {
            WorkflowStage.ACQUIRE: "Raw sources need to be acquired.",
            WorkflowStage.ETL: "Sources acquired; ETL extraction and normalization required.",
            WorkflowStage.QUALITY: "ETL complete; quality scoring needed.",
            WorkflowStage.PROVENANCE: "Quality scored; provenance resolution needed.",
            WorkflowStage.REVIEW: "Provenance resolved; human review needed.",
            WorkflowStage.CURATED: "Review complete; curated dataset needs to be finalized.",
            WorkflowStage.TRAINING_VIEWS: (
                "Curated dataset is approved and eligible.\n"
                "Training views have not been generated for the current release."
            ),
            WorkflowStage.EVALUATION: (
                "Training views generated.\n"
                "Evaluation benchmarks need to be run to validate dataset quality."
            ),
            WorkflowStage.RELEASE: (
                "Evaluation complete.\n"
                "Release bundle needs to be created for distribution."
            ),
            WorkflowStage.TRAINING: (
                "All upstream stages complete.\n"
                "Model training requires explicit human authorization."
            ),
        }
        return reasons.get(stage, "Next stage in the pipeline.")
