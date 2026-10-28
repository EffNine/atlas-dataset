#!/usr/bin/env python3
"""dashboard.jobs — persisted asynchronous job runner for dashboard actions.

Layer 4 (CLI & Tooling). Executes whitelisted argv lists (built by
dashboard.actions) as subprocesses on a bounded worker pool so that aiohttp
request handlers never block. Job records are persisted to
metadata/dashboard/jobs.json as *evidence* of operator-triggered work; they
are never a second source of Atlas truth.

Guarantees:
- subprocess only (no shell), argv fully server-controlled
- per-job timeout with graceful SIGTERM → SIGKILL escalation
- cancel support for queued and running jobs
- crash recovery: jobs left 'running' by a dead server become 'interrupted'
- atomic JSON persistence guarded by a threading.Lock
"""

from __future__ import annotations

import json
import logging
import os
import queue
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("atlas.dashboard.jobs")

MAX_PERSISTED_JOBS = 300
LOG_TAIL_LINES = 400
KILL_GRACE_S = 5.0

ACTIVE_STATUSES = frozenset({"queued", "running"})
TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "timeout", "cancelled", "interrupted"})

# Actions whose non-zero exit codes carry domain meaning beyond pass/fail.
# atlas sft-review run exits 3 when some records still need adjudication —
# that is an explicit ATTENTION state, never acceptance.
ATTENTION_EXIT_CODES: dict[str, set[int]] = {
    "review.ai_run": {3},
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    def __init__(self, data_dir: Path, root: Path, max_workers: int = 2,
                 env: dict[str, str] | None = None) -> None:
        self._dir = data_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._logs_dir = self._dir / "logs"
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        self._jobs_path = self._dir / "jobs.json"
        self._root = root
        self._env = env if env is not None else dict(os.environ)
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._cancel_requested: set[str] = set()
        self._load()
        self._recover_interrupted()
        # Daemon worker pool: interpreter shutdown must never be held
        # hostage by a worker blocked in proc.wait() on a long child.
        self._queue: "queue.Queue[Callable[[], None] | None]" = queue.Queue()
        self._workers: list[threading.Thread] = []
        for i in range(max(1, max_workers)):
            t = threading.Thread(target=self._worker_loop,
                                 name=f"atlas-dash-job-{i}", daemon=True)
            t.start()
            self._workers.append(t)
        log.info("JobManager ready (%d worker slots)", max_workers)

    # ── persistence ────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._jobs_path.exists():
            return
        try:
            raw = json.loads(self._jobs_path.read_text(encoding="utf-8"))
            for rec in raw.get("jobs", []):
                self._jobs[rec["id"]] = rec
        except (OSError, ValueError, KeyError):
            log.exception("jobs.json unreadable; starting with empty registry")

    def _persist_locked(self) -> None:
        ordered = sorted(self._jobs.values(),
                         key=lambda j: j["created_at"], reverse=True)
        keep = ordered[:MAX_PERSISTED_JOBS]
        self._jobs = {j["id"]: j for j in keep}
        tmp = self._jobs_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"updated_at": _utcnow(),
                                   "jobs": keep}, indent=1),
                       encoding="utf-8")
        os.replace(tmp, self._jobs_path)

    def _recover_interrupted(self) -> None:
        with self._lock:
            changed = False
            for job in self._jobs.values():
                if job["status"] in ACTIVE_STATUSES:
                    job["status"] = "interrupted"
                    job["finished_at"] = _utcnow()
                    job["error"] = ("server restarted while job was "
                                    f"{job['status']}")
                    changed = True
            if changed:
                self._persist_locked()

    # ── public API (called from asyncio handlers; all non-blocking) ────

    def submit(self, *, action_id: str, title: str, argv: list[str],
               danger: str, timeout_s: int,
               params: dict[str, Any] | None = None) -> dict[str, Any]:
        job_id = f"job_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
        log_path = self._logs_dir / f"{job_id}.log"
        try:
            log_ref = str(log_path.relative_to(self._root))
        except ValueError:
            # data dir outside the repo (e.g. tests) — store absolute path
            log_ref = str(log_path)
        record: dict[str, Any] = {
            "id": job_id,
            "action": action_id,
            "title": title,
            "danger": danger,
            "argv": argv,
            "params": params or {},
            "status": "queued",
            "exit_code": None,
            "needs_attention": False,
            "error": None,
            "log_file": log_ref,
            "pid": None,
            "created_at": _utcnow(),
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
            "timeout_s": int(timeout_s),
            "triggered_by": "dashboard",
        }
        with self._lock:
            self._jobs[job_id] = record
            self._persist_locked()
        job_id_ref = job_id

        def _task() -> None:
            self._execute(job_id_ref)

        self._queue.put(_task)
        return dict(record)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            rec = self._jobs.get(job_id)
            return dict(rec) if rec else None

    def list_jobs(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = sorted(self._jobs.values(),
                           key=lambda j: j["created_at"], reverse=True)
            if status:
                items = [j for j in items if j["status"] == status]
            return [dict(j) for j in items[:limit]]

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values()
                       if j["status"] in ACTIVE_STATUSES)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {}
            for j in self._jobs.values():
                counts[j["status"]] = counts.get(j["status"], 0) + 1
            return {"total_tracked": len(self._jobs),
                    "active": sum(counts.get(s, 0) for s in ACTIVE_STATUSES),
                    "by_status": counts}

    def cancel(self, job_id: str) -> tuple[bool, str]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False, "unknown job id"
            if job["status"] == "queued":
                # queued work cannot be cheaply dequeued; mark it so the
                # runner no-ops when it starts.
                self._cancel_requested.add(job_id)
                job["status"] = "cancelled"
                job["finished_at"] = _utcnow()
                job["error"] = "cancelled before start"
                self._persist_locked()
                return True, "queued job cancelled"
            if job["status"] != "running":
                return False, f"job is {job['status']} and cannot be cancelled"
            self._cancel_requested.add(job_id)
        # Wait briefly for process registration (running flag flips just
        # before Popen; the handle lands under lock immediately afterwards).
        proc = None
        for _ in range(100):
            with self._lock:
                proc = self._procs.get(job_id)
            if proc is not None:
                break
            time.sleep(0.02)
        if proc is None or proc.poll() is not None:
            return True, "process already exited; finalizing"
        try:
            proc.terminate()
        except OSError:
            pass
        return True, "SIGTERM sent"

    def log_tail(self, job_id: str, max_bytes: int = 64_000) -> str:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return ""
            ref = Path(job["log_file"])
            path = ref if ref.is_absolute() else self._root / ref
        if not path.exists():
            return ""
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            data = fh.read().decode("utf-8", errors="replace")
        lines = data.splitlines()
        return "\n".join(lines[-LOG_TAIL_LINES:])

    def shutdown(self) -> None:
        """Stop accepting work and terminate any active job processes."""
        with self._lock:
            procs = list(self._procs.items())
        for _job_id, proc in procs:
            if proc.poll() is None:
                try:
                    self._terminate(proc)
                except OSError:
                    pass
        for _ in self._workers:
            self._queue.put(None)

    def _worker_loop(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                break
            try:
                task()
            except Exception:  # pragma: no cover — worker must never die
                log.exception("dashboard job task raised")

    # ── execution (worker thread context) ──────────────────────────────

    def _execute(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if job_id in self._cancel_requested:
                return  # already cancelled while queued
            job["status"] = "running"
            job["started_at"] = _utcnow()
            argv = list(job["argv"])
            timeout_s = float(job["timeout_s"])
            self._persist_locked()
        log_ref = Path(job["log_file"])
        log_path = log_ref if log_ref.is_absolute() else self._root / log_ref
        started = time.monotonic()
        tail: deque[str] = deque(maxlen=LOG_TAIL_LINES * 4)
        try:
            proc = subprocess.Popen(  # noqa: S603 — argv is server-built
                argv, cwd=str(self._root), env=self._env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            with self._lock:
                job["status"] = "failed"
                job["finished_at"] = _utcnow()
                job["error"] = f"failed to spawn process: {exc}"
                job["duration_ms"] = int((time.monotonic() - started) * 1000)
                self._append_log(log_path, tail, f"[spawn-error] {exc}\n")
                self._persist_locked()
            return
        reader = threading.Thread(target=self._drain, args=(proc, log_path, tail),
                                  daemon=True, name=f"{job_id}-drain")
        reader.start()
        # Register the process under lock immediately so cancel() can never
        # observe status==running without a process handle to terminate.
        with self._lock:
            self._procs[job_id] = proc
            job["pid"] = proc.pid
            self._persist_locked()
        timed_out = False
        try:
            rc = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._terminate(proc)
            try:
                rc = proc.wait(timeout=KILL_GRACE_S + 5)
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = proc.wait()
        reader.join(timeout=10)

        cancelled = job_id in self._cancel_requested and not timed_out
        with self._lock:
            self._procs.pop(job_id, None)
            job["exit_code"] = rc
            job["finished_at"] = _utcnow()
            job["duration_ms"] = int((time.monotonic() - started) * 1000)
            if timed_out:
                job["status"] = "timeout"
                job["error"] = f"exceeded timeout of {timeout_s:.0f}s and was killed"
            elif cancelled:
                job["status"] = "cancelled"
                job["error"] = "cancelled by operator"
            elif rc == 0:
                job["status"] = "succeeded"
            else:
                job["status"] = "failed"
                job["needs_attention"] = (
                    rc in ATTENTION_EXIT_CODES.get(job["action"], set()))
                if job["needs_attention"]:
                    job["status"] = "needs_attention"
                    job["error"] = (
                        "completed with attention code %d — review output; "
                        "this is NOT an acceptance" % rc)
                else:
                    job["error"] = f"exit code {rc}"
            self._persist_locked()
        log.info("job %s -> %s (rc=%s, %.1fs)",
                 job_id, job["status"], rc,
                 (time.monotonic() - started))

    @staticmethod
    def _terminate(proc: subprocess.Popen[bytes]) -> None:
        try:
            if os.name == "posix":
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    return
                except (ProcessLookupError, PermissionError):
                    pass
            proc.terminate()
        except OSError:
            pass

    def _drain(self, proc: subprocess.Popen[bytes], log_path: Path,
               tail: deque[str]) -> None:
        assert proc.stdout is not None
        with log_path.open("a", encoding="utf-8") as sink:
            argv = proc.args
            if isinstance(argv, (list, tuple)):
                sink.write(f"[cmd] {' '.join(str(a) for a in argv)}\n")
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace")
                tail.append(line)
                try:
                    sink.write(line)
                    sink.flush()
                except (OSError, ValueError):
                    break

    @staticmethod
    def _append_log(log_path: Path, tail: deque[str], text: str) -> None:
        try:
            with log_path.open("a", encoding="utf-8") as sink:
                sink.write(text)
        except OSError:
            pass
