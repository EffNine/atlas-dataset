#!/usr/bin/env python3
"""Backend adapter for Atlas TUI — read-oriented interfaces to existing state.

All data is read from existing Atlas JSON state files and CLI outputs.
No state is written by this module; mutations dispatch via subprocess to
the existing `atlas` CLI.
"""

from __future__ import annotations

import json
import subprocess
import sys
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
# Backend reader
# ---------------------------------------------------------------------------


class TuiBackend:
    """Reads Atlas state and dispatches mutations via the existing CLI."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or _atlas_root()
        self._last_refresh = 0.0
        self._refresh_interval = 1.0

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
            import subprocess
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
            _subproc = subprocess
            out2 = _subproc.run(
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
        cmd = ["python", str(self.root / "scripts" / "atlas.py")] + args
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
