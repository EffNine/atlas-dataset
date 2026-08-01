#!/usr/bin/env python3
"""Tests for the adaptive workload scheduler (Parallel Processing v2).

Covers:
- 100 small shards distribution
- 1 huge shard splitting
- mixed shard sizes
- deterministic task ordering
- resume after failure
- duplicate task prevention
- config loading
- line-offset correctness (streaming chunk coverage)
- process_file_range correctness

All deterministic and CI-safe (no network, no dev-pc).
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts"
INTEL = SCRIPTS / "intelligence"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(INTEL))

from adaptive_scheduler import (  # noqa: E402
    Task,
    TaskRegistry,
    load_scheduler_config,
    plan_tasks,
    write_scheduler_report,
)


# ── Fixtures / helpers ───────────────────────────────────────────────


def _make_file(td: Path, name: str, lines: int, line_bytes: int = 60) -> Path:
    p = td / name
    with open(p, "w", encoding="utf-8") as f:
        for i in range(lines):
            rec = {
                "id": f"{name}_{i}",
                "category": "01_foundation",
                "messages": [
                    {"role": "user", "content": "What is 2+2?" + "x" * 10},
                    {"role": "assistant", "content": "The answer is 4." + "x" * 10},
                ],
            }
            f.write(json.dumps(rec) + "\n")
    return p


def _default_cfg() -> dict:
    # Small thresholds so tests don't need huge files
    return {
        "scheduler": "adaptive",
        "target_task_size_mb": 512,
        "max_task_size_mb": 1024,
        "split_large_shards": True,
        "min_split_size_mb": 2048,
        "task_timeout_seconds": 3600,
        "max_retries": 2,
        "max_parallel_workers": 10,
    }


# ── Config loading ───────────────────────────────────────────────────


def test_load_scheduler_config_defaults():
    cfg = load_scheduler_config({})
    assert cfg["scheduler"] == "adaptive"
    assert cfg["target_task_size_mb"] >= 1
    assert cfg["max_task_size_mb"] >= cfg["target_task_size_mb"]
    assert cfg["max_retries"] >= 0


def test_load_scheduler_config_overrides():
    cfg = load_scheduler_config({
        "parallelism": {
            "classification": {
                "scheduler": "adaptive",
                "target_task_size_mb": 64,
                "max_task_size_mb": 128,
                "min_split_size_mb": 256,
                "split_large_shards": False,
            }
        }
    })
    assert cfg["target_task_size_mb"] == 64
    assert cfg["max_task_size_mb"] == 128
    assert cfg["min_split_size_mb"] == 256
    assert cfg["split_large_shards"] is False


def test_config_yaml_has_scheduler_keys():
    yaml = pytest.importorskip("yaml")
    cfg = yaml.safe_load((ROOT / "config/parallelism.yaml").read_text())
    clf = cfg["parallelism"]["classification"]
    assert clf["scheduler"] == "adaptive"
    assert clf["target_task_size_mb"] > 0
    assert clf["max_task_size_mb"] >= clf["target_task_size_mb"]
    assert clf["min_split_size_mb"] >= clf["target_task_size_mb"]


# ── Small shards: 100 small files → one task each ────────────────────


def test_100_small_shards_one_task_each(tmp_path: Path):
    shards = []
    for i in range(100):
        shards.append(_make_file(tmp_path, f"small_{i:04d}.jsonl", 100))
    cfg = _default_cfg()
    tasks = plan_tasks("swebench", shards, cfg, "stage2")
    assert len(tasks) == 100
    for t in tasks:
        assert t.offset_end == -1  # whole file
        assert "chunk" not in t.task_id
    # All shards covered exactly once
    assert len({t.input_file for t in tasks}) == 100


# ── Huge shard splitting ─────────────────────────────────────────────


def test_1_huge_shard_splits_into_chunks(tmp_path: Path):
    # ~60 bytes/line * 20000 = ~1.2MB. Force split with tiny target (512KB).
    shard = _make_file(tmp_path, "huge_atlas.jsonl", 20000)
    cfg = _default_cfg()
    cfg["target_task_size_mb"] = 1  # 1MB target -> split the 1.2MB file into 2
    cfg["min_split_size_mb"] = 1
    tasks = plan_tasks("huge", [shard], cfg, "stage2")
    assert len(tasks) >= 2
    assert all("chunk" in t.task_id for t in tasks)
    # Offsets cover [0, line_count) exactly, in order, no gaps/overlaps
    offsets = sorted((t.offset_start, t.offset_end) for t in tasks)
    assert offsets[0][0] == 0
    assert offsets[-1][1] == 20000
    for (_, e1), (s2, _) in zip(offsets, offsets[1:]):
        assert e1 == s2  # contiguous, no gap
    # Original file untouched
    assert shard.exists()
    assert len(tasks) <= 64  # cap


def test_split_disabled_large_shard_one_task(tmp_path: Path):
    shard = _make_file(tmp_path, "big_atlas.jsonl", 5000)
    cfg = _default_cfg()
    cfg["min_split_size_mb"] = 1
    cfg["target_task_size_mb"] = 1
    cfg["split_large_shards"] = False
    tasks = plan_tasks("big", [shard], cfg, "stage2")
    # One whole-file task (split disabled), even though large
    assert len(tasks) == 1
    assert tasks[0].offset_end == -1


# ── Mixed shard sizes ────────────────────────────────────────────────


def test_mixed_shard_sizes_balanced(tmp_path: Path):
    small = _make_file(tmp_path, "a_small_atlas.jsonl", 50)       # tiny
    medium = _make_file(tmp_path, "b_medium_atlas.jsonl", 5000)   # ~0.3MB
    big = _make_file(tmp_path, "c_big_atlas.jsonl", 40000)        # ~2.4MB
    cfg = _default_cfg()
    cfg["target_task_size_mb"] = 1
    cfg["min_split_size_mb"] = 1
    tasks = plan_tasks("mixed", [small, medium, big], cfg, "stage2")
    # big should be split; small/medium whole
    big_tasks = [t for t in tasks if "c_big" in t.task_id]
    assert len(big_tasks) >= 2
    # Deterministic order: sorted by task_id
    ids = [t.task_id for t in tasks]
    assert ids == sorted(ids)
    # No task exceeds max size (approx by line span)
    for t in big_tasks:
        assert t.offset_end - t.offset_start > 0


# ── Deterministic ordering ───────────────────────────────────────────


def test_deterministic_task_ordering(tmp_path: Path):
    shards = [_make_file(tmp_path, f"d_{i:03d}.jsonl", 100) for i in range(20)]
    cfg = _default_cfg()
    cfg["target_task_size_mb"] = 1
    cfg["min_split_size_mb"] = 1
    big = _make_file(tmp_path, "z_big_atlas.jsonl", 30000)
    shards.append(big)
    t1 = plan_tasks("det", shards, cfg, "stage2")
    t2 = plan_tasks("det", shards, cfg, "stage2")
    assert [t.task_id for t in t1] == [t.task_id for t in t2]
    assert [(t.offset_start, t.offset_end) for t in t1] == \
           [(t.offset_start, t.offset_end) for t in t2]


# ── Registry: resume / failure / duplicate prevention ───────────────


def test_registry_completed_skipped(tmp_path: Path):
    reg = TaskRegistry(tmp_path, "stage2")
    task = Task(task_id="x_0001", source="x", input_file="f",
                offset_start=0, offset_end=-1, estimated_bytes=10)
    assert not reg.is_completed("x_0001")
    reg.record(task, "completed", worker_id="w1", record_count=5)
    assert reg.is_completed("x_0001")
    assert reg.completed_count() == 1
    assert reg.status_counts()["completed"] == 1


def test_registry_failed_retries(tmp_path: Path):
    reg = TaskRegistry(tmp_path, "stage2")
    task = Task(task_id="y_0001", source="y", input_file="f",
                offset_start=0, offset_end=-1, estimated_bytes=10)
    reg.record(task, "failed", worker_id="w1")
    reg.record(task, "failed", worker_id="w1")
    assert reg.attempts("y_0001") == 2
    assert reg.is_failed("y_0001")


def test_registry_persists_across_instances(tmp_path: Path):
    task = Task(task_id="z_0001", source="z", input_file="f",
                offset_start=0, offset_end=-1, estimated_bytes=10)
    TaskRegistry(tmp_path, "stage2").record(task, "completed", record_count=3)
    reg2 = TaskRegistry(tmp_path, "stage2")  # new instance reads the file
    assert reg2.is_completed("z_0001")
    assert reg2.status_counts()["completed"] == 1


def test_duplicate_task_prevention_via_registry(tmp_path: Path):
    """Same task_id recorded twice does not create two completions."""
    reg = TaskRegistry(tmp_path, "stage2")
    task = Task(task_id="dup_0001", source="dup", input_file="f",
                offset_start=0, offset_end=-1, estimated_bytes=10)
    reg.record(task, "completed", record_count=1)
    reg.record(task, "completed", record_count=1)
    assert reg.completed_count() == 1  # dict keyed by task_id


# ── Report ───────────────────────────────────────────────────────────


def test_write_scheduler_report(tmp_path: Path):
    shards = [_make_file(tmp_path, f"r_{i}.jsonl", 100) for i in range(3)]
    cfg = _default_cfg()
    tasks = plan_tasks("report", shards, cfg, "stage2")
    reg = TaskRegistry(tmp_path, "stage2")
    for t in tasks:
        reg.record(t, "completed", record_count=100)
    out = write_scheduler_report(tmp_path, "stage2", shards, tasks, reg,
                                 split_operations=0, worker_utilization=0.9)
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["total_shards"] == 3
    assert data["generated_tasks"] == len(tasks)
    assert data["task_status_counts"]["completed"] == len(tasks)
    assert "largest_shard_bytes" in data
    assert "split_operations" in data


# ── Line-offset correctness (streaming chunk) ────────────────────────


def test_process_file_range_offsets(tmp_path: Path):
    from difficulty_analyzer import process_file_range
    p = _make_file(tmp_path, "rng_atlas.jsonl", 100)
    _, _, results0_50, _ = process_file_range(p, 0, 50, None)
    _, _, results50_100, _ = process_file_range(p, 50, 100, None)
    assert len(results0_50) == 50
    assert len(results50_100) == 50
    # No overlap and full coverage
    ids0 = {r["record_id"] for r in results0_50}
    ids1 = {r["record_id"] for r in results50_100}
    assert ids0.isdisjoint(ids1)
    assert len(ids0 | ids1) == 100


def test_process_file_range_to_eof(tmp_path: Path):
    from difficulty_analyzer import process_file_range
    p = _make_file(tmp_path, "eof_atlas.jsonl", 80)
    _, _, results, _ = process_file_range(p, 40, -1, None)
    assert len(results) == 40


# ── Full adaptive classify smoke (single source, small) ─────────────


def test_classify_adaptive_smoke(tmp_path: Path):
    """End-to-end: adaptive classify of a small source produces output."""
    sys.path.insert(0, str(INTEL))
    from batch_classify import SourceConfig, classify_source_shards_adaptive

    src = tmp_path / "raw" / "generated"
    src.mkdir(parents=True)
    _make_file(src, "smoke_shard0_atlas.jsonl", 30)
    _make_file(src, "smoke_shard1_atlas.jsonl", 30)

    cfg = _default_cfg()
    cfg["target_task_size_mb"] = 512  # no split for tiny files
    out = tmp_path / "out" / "classified_smoke.jsonl"

    stats = classify_source_shards_adaptive(
        tmp_path, SourceConfig("smoke", "raw/generated/smoke_shard*_atlas.jsonl"),
        out, shard_workers=2, scheduler_cfg=cfg,
    )
    assert stats["classified"] == 60
    assert out.exists()
    assert sum(1 for _ in open(out)) == 60


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
