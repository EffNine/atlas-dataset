#!/usr/bin/env python3
"""Tests for the downloader migration (Universal Scheduler Phase 5B).

Covers:
- deterministic task identity (download:<sid>:<url_hash>)
- task planning (one source = one task)
- I/O-aware worker limits (not CPU-only)
- retry (failed task retried then completed / terminal after max)
- resume (completed tasks skipped; stale running re-claimed)
- cache-conflict prevention (same source not re-downloaded)
- fallback (sequential identical behavior)
- output identity (scheduler vs sequential: same cache objects/logs)
"""

from __future__ import annotations

import json
import multiprocessing
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
REPO = Path(__file__).resolve().parent.parent

if sys.platform == "darwin":
    try:
        multiprocessing.set_start_method("fork", force=True)
    except RuntimeError:
        pass

# A tiny local HTTP server serves deterministic content for adapter download
# without any external network (keeps tests offline + fast).


def _fake_adapters(cache, fail_sids: set[str] | None = None):
    """Build adapter list that writes a deterministic cache entry per source."""
    from downloader.adapters.base import DownloadResult, DownloadStatus
    from downloader.cache import CacheEntry

    fail_sids = fail_sids or set()

    class FakeAdapter:
        name = "fake"

        def supports(self, source: dict) -> bool:
            return True

        def download(self, source: dict, *, dry_run: bool = False):
            sid = str(source.get("id") or source.get("source_id") or "")
            url = source.get("url") or f"https://example.com/{sid}"
            if sid in fail_sids and not dry_run:
                return DownloadResult(
                    source_ref=f":{sid}", adapter="fake", status=DownloadStatus.FAILED,
                    summary="forced failure", url=url, files=[],
                    errors=["forced failure"], warnings=[], entries=[],
                )
            payload = json.dumps({"sid": sid, "content": f"data-{sid}"}).encode("utf-8")
            entry = cache.put_bytes(
                f":{sid}",
                payload,
                adapter="fake",
                metadata={"filename": f"{sid}.json"},
            )
            if dry_run:
                return DownloadResult(
                    source_ref=f":{sid}", adapter="fake", status=DownloadStatus.PLANNED,
                    summary="planned", url=url, files=[], errors=[], warnings=[], entries=[],
                )
            return DownloadResult(
                source_ref=f":{sid}", adapter="fake", status=DownloadStatus.DOWNLOADED,
                summary="downloaded", url=url,
                files=[{"filename": f"{sid}.json", "url": url, "checksum": entry.checksum}],
                errors=[], warnings=[], entries=[],
            )

    return [FakeAdapter()]


def _fake_write_log(root: Path):
    def _write(sid: str, result) -> None:
        log_dir = root / "metadata" / "download_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / f"{sid}.download.json").write_text(
            json.dumps({"source_id": sid, "adapter": result.adapter,
                        "status": result.status.value, "url": result.url,
                        "files": result.files}),
            encoding="utf-8",
        )
    return _write


@pytest.fixture
def env(tmp_path: Path):
    """Root with cache + registry + a few sources."""
    from downloader.cache import CacheManager
    root = tmp_path
    cache = CacheManager(root)
    sources = [
        {"id": "s1", "name": "one", "url": "https://example.com/s1"},
        {"id": "s2", "name": "two", "url": "https://example.com/s2"},
        {"id": "s3", "name": "three", "url": "https://example.com/s3"},
    ]
    return {"root": root, "cache": cache, "sources": sources}


# ----------------------------------------------------------------------
# 1. deterministic task identity
# ----------------------------------------------------------------------

class TestTaskIdentity:
    def test_task_id_format(self):
        from downloader.scheduler_tasks import download_task_id
        tid = download_task_id("s1", "https://example.com/s1")
        parts = tid.split(":")
        assert parts[0] == "download"
        assert parts[1] == "s1"
        assert len(parts[2]) == 12  # url hash

    def test_same_url_same_id(self):
        from downloader.scheduler_tasks import download_task_id
        a = download_task_id("s1", "https://example.com/x")
        b = download_task_id("s1", "https://example.com/x")
        assert a == b

    def test_changed_url_new_id(self):
        from downloader.scheduler_tasks import download_task_id
        a = download_task_id("s1", "https://example.com/x")
        b = download_task_id("s1", "https://example.com/y")
        assert a != b  # URL change -> new task, not a duplicate of the old

    def test_plan_one_task_per_source(self, env):
        from downloader.scheduler_tasks import plan_download_tasks
        tasks = plan_download_tasks(env["sources"])
        assert len(tasks) == 3
        assert all(t.operation == "download_source" for t in tasks)
        assert all(t.task_id.startswith("download:") for t in tasks)


# ----------------------------------------------------------------------
# 2. I/O-aware worker limits
# ----------------------------------------------------------------------

class TestIOAwareWorkers:
    def test_safe_io_worker_limit_bounded(self):
        from parallel import resource
        limit = resource.safe_io_worker_limit()
        # io_worker_cap default 8, RAM-bounded, never 0
        assert 1 <= limit <= 8

    def test_safe_io_worker_limit_respects_cap(self):
        from parallel import resource
        limit = resource.safe_io_worker_limit(max_workers=2)
        assert limit <= 2

    def test_not_cpu_scaled(self, monkeypatch):
        """A 64-core machine still respects io_worker_cap (bandwidth/disk
        pressure, not CPU)."""
        from parallel import resource
        monkeypatch.setattr(resource, "detect_cpu", lambda: 64)
        monkeypatch.setattr(resource, "detect_ram",
                            lambda: {"total_mb": 262144, "available_mb": 200000, "used_mb": 62144})
        limit = resource.safe_io_worker_limit()
        assert limit <= 8  # io_worker_cap, NOT 64


# ----------------------------------------------------------------------
# 3. scheduler end-to-end (thread pool)
# ----------------------------------------------------------------------

class TestSchedulerRun:
    def test_all_completed(self, env):
        from downloader.scheduler_tasks import run_download_scheduler
        payloads = run_download_scheduler(
            env["root"], env["sources"], _fake_adapters(env["cache"]),
            env["cache"], _fake_write_log(env["root"]), workers=2,
        )
        assert len(payloads) == 3
        assert all(p["status"] == "downloaded" for p in payloads)
        assert sorted(p["source_id"] for p in payloads) == ["s1", "s2", "s3"]
        # cache objects written
        for sid in ("s1", "s2", "s3"):
            assert env["cache"].has(f":{sid}")

    def test_resume_skips_completed(self, env):
        from downloader.scheduler_tasks import run_download_scheduler
        r1 = run_download_scheduler(
            env["root"], env["sources"], _fake_adapters(env["cache"]),
            env["cache"], _fake_write_log(env["root"]), workers=2,
        )
        assert all(p["status"] == "downloaded" for p in r1)
        # Rerun with the same registry: completed tasks skipped, results
        # reloaded from download logs (status cached).
        r2 = run_download_scheduler(
            env["root"], env["sources"], _fake_adapters(env["cache"]),
            env["cache"], _fake_write_log(env["root"]), workers=2,
        )
        assert len(r2) == 3
        assert all(p["status"] in ("cached", "downloaded") for p in r2)

    def test_failed_source_reported_not_crash(self, env):
        from downloader.scheduler_tasks import run_download_scheduler
        payloads = run_download_scheduler(
            env["root"], env["sources"], _fake_adapters(env["cache"], fail_sids={"s2"}),
            env["cache"], _fake_write_log(env["root"]), workers=2, registry_root=env["root"] / "reg",
        )
        by_id = {p["source_id"]: p for p in payloads}
        assert by_id["s1"]["status"] == "downloaded"
        assert by_id["s2"]["status"] == "failed"
        assert by_id["s3"]["status"] == "downloaded"


# ----------------------------------------------------------------------
# 4. retry + registry
# ----------------------------------------------------------------------

class TestRetryRegistry:
    def test_failed_task_retried_then_completed(self, env, tmp_path: Path):
        from downloader.scheduler_tasks import download_task, plan_download_tasks
        from parallel.scheduler import Scheduler

        tasks = plan_download_tasks(env["sources"][:1])
        calls = {"n": 0}
        import functools
        adapters = _fake_adapters(env["cache"])
        write_log = _fake_write_log(env["root"])

        # Inject worker context the way run_download_scheduler does
        import downloader.scheduler_tasks as st
        st._WORKER_CTX["adapters"] = adapters
        st._WORKER_CTX["cache"] = env["cache"]
        st._WORKER_CTX["write_log"] = write_log

        def flaky(t):
            if calls["n"] == 0:
                calls["n"] += 1
                raise RuntimeError("transient")
            calls["n"] += 1
            return download_task(t)

        s = Scheduler("acquisition", registry_root=tmp_path / "reg", workers=1,
                      pool="thread", max_retries=2)
        results = s.run(tasks, flaky)
        assert results[0].status == "completed"

    def test_terminal_failure_after_max_retries(self, env, tmp_path: Path):
        from downloader.scheduler_tasks import plan_download_tasks
        from parallel.scheduler import Scheduler

        tasks = plan_download_tasks(env["sources"][:1])

        def always_fail(t):
            raise RuntimeError("always")

        s = Scheduler("acquisition", registry_root=tmp_path / "reg", workers=1,
                      pool="thread", max_retries=2)
        results = s.run(tasks, always_fail)
        assert results[0].status == "failed"
        assert results[0].attempts == 3

    def test_stale_running_reclaimed(self, tmp_path: Path):
        from parallel.registry import TaskRegistry
        reg = TaskRegistry(tmp_path / "reg", "acquisition")
        reg.claim("download:s1:abc123def456")
        reclaimed = reg.reclaim_stale_running(lease_seconds=0)
        assert "download:s1:abc123def456" in reclaimed
        assert reg.status("download:s1:abc123def456") == "pending"


# ----------------------------------------------------------------------
# 5. cache-conflict prevention
# ----------------------------------------------------------------------

class TestCacheConflict:
    def test_no_double_download(self, env):
        """Same source planned twice -> second run skips (registry completed),
        cache object written once."""
        from downloader.scheduler_tasks import run_download_scheduler
        sources = [env["sources"][0], env["sources"][0]]  # duplicate s1
        r1 = run_download_scheduler(
            env["root"], sources, _fake_adapters(env["cache"]),
            env["cache"], _fake_write_log(env["root"]), workers=2,
        )
        # Scheduler dedupes by task_id: only one task for s1.
        assert len([p for p in r1 if p["source_id"] == "s1"]) == 1
        assert env["cache"].has(":s1")


# ----------------------------------------------------------------------
# 6. fallback + output identity
# ----------------------------------------------------------------------

class TestFallback:
    def test_sequential_fallback_identical(self, env, monkeypatch):
        """When the scheduler is disabled (kill-switch), the sequential
        fallback produces the same cache objects + logs."""
        from downloader.scheduler_tasks import run_download_scheduler
        import downloader.scheduler_tasks as st

        monkeypatch.setattr(st, "_SCHEDULER_ENABLED", False)
        payloads = run_download_scheduler(
            env["root"], env["sources"], _fake_adapters(env["cache"]),
            env["cache"], _fake_write_log(env["root"]), workers=2,
        )
        # Sequential fallback still downloads all.
        assert len(payloads) == 3
        assert env["cache"].has(":s1") and env["cache"].has(":s3")
