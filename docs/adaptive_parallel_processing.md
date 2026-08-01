# Adaptive Parallel Processing — Workload Scheduler Design

**Status:** Proposed
**Date:** 2026-08-01
**Phase:** 4C.4 — Engineering Stabilization / Parallel Processing v2

---

## 1. Problem Statement

The Atlas classification pipeline uses a fixed assignment model:

```
source → shards → workers (one worker per shard)
```

This works when shards are roughly equal in size, but fails in the real
dataset:

| Scenario | Current behaviour | Problem |
|----------|-------------------|---------|
| Many small shards | 1 worker per shard | Workers finish early and idle; under-utilization |
| One huge shard (e.g. 8GB swebench) | 1 worker takes the whole file | Single worker is the bottleneck (~120-150 rec/s) |
| Mixed sizes | `worker1 → 50MB`, `worker2 → 5GB` | Wall-clock time = slowest worker |
| Future expert datasets | unknown sizes | No way to plan ahead |

The unit of work must change from **"one shard"** to **"one balanced
workload task"**.

---

## 2. Design Goals

1. **Shard-size aware scheduling** — balance work by estimated bytes, not
   shard count.
2. **Large shard splitting** — split huge files into virtual chunks
   (streaming, never modify the original).
3. **Work queue architecture** — a planner produces a task queue; workers
   pull tasks (no static assignment).
4. **Resume / crash safety** — a persistent task registry tracks
   pending/running/completed/failed so a restart continues without
   repeating completed work.
5. **Performance monitoring** — scheduler reports worker utilization and
   split operations.
6. **Backward compatibility** — existing commands keep working; the new
   scheduler is the default but falls back gracefully.

---

## 3. Architecture

```
source
  │
  ▼
shard discovery ── size estimation (stat + line sampling)
  │
  ▼
workload planner (split large shards, balance by bytes)
  │
  ▼
task queue (list of Task dicts)
  │
  ▼
workers (ProcessPoolExecutor pulls tasks)
  │
  ▼
per-task output files → merge (deterministic order) → per-source output
```

### 3.1 Task shape

```json
{
  "task_id": "swebench_0001",
  "source": "swebench",
  "input_file": "raw/generated/swebench_atlas.jsonl",
  "offset_start": 0,
  "offset_end": 100000,
  "estimated_bytes": 512000000,
  "worker_group": "stage2"
}
```

- `offset_start/offset_end` are **line offsets** (0-based) into the input
  file. For a whole-shard task, `offset_end` = line count (or -1 = unknown,
  stream to EOF).
- `estimated_bytes` comes from file size × line fraction (or stat when the
  task covers the whole file).
- `worker_group` maps to the parallelism config section (stage1/stage2).

### 3.2 Workload planner algorithm

1. Discover shards matching the source glob; stat each for byte size.
2. For each shard:
   - If size ≤ `target_task_size_mb` → **one task** for the whole shard.
   - If size > `min_split_size_mb` and `split_large_shards: true` → split
     into chunks of `target_task_size_mb` (line-aware, see §3.3).
   - Else → one task (large but split disabled).
3. Build the task list in **deterministic order**: sort shards by name,
   chunk offsets ascending.
4. Optionally cap concurrent tasks at `max_parallel_workers`.

The planner does **not** hard-assign workers. Workers pull from the queue
via a shared iterator, so any worker can take any task.

### 3.3 Large shard splitting (streaming)

- **Never modify the original shard.** Virtual chunks are defined by line
  offset ranges only.
- Splitting is **streaming**: the worker opens the file once, skips to
  `offset_start` lines, processes exactly `offset_end - offset_start`
  lines, then stops.
- Line counting is done once during planning (single pass, O(n)), then the
  per-chunk offsets are fixed.
- **Output ordering deterministic**: chunks are written to
  `_tmp_shards/{label}_chunkNNNN_{shard}.jsonl` in ascending offset order
  and merged in sorted-name order (the existing merge glob already does
  this).
- Split metadata is recorded in the task (offsets) and in the scheduler
  report.

### 3.4 Task registry (resume / crash safety)

Persistent state at `metadata/pipeline_state/task_registry.jsonl`
(append-only JSONL):

```json
{
  "task_id": "swebench_0001",
  "status": "completed",
  "source": "swebench",
  "input_file": "raw/generated/swebench_atlas.jsonl",
  "offset_start": 0,
  "offset_end": 100000,
  "output_file": "metadata/intelligence/_tmp/classified_swebench.jsonl",
  "record_count": 95000,
  "worker_id": "w3",
  "timestamp": "2026-08-01T23:00:00Z"
}
```

**Statuses:** `pending` → `running` → `completed` | `failed`.

**Resume rules:**
- On start, load the registry for the current source + worker_group.
- A task with status `completed` and a non-empty output contribution is
  **skipped** (never re-run).
- A task with status `running` from a dead worker is **re-queued**
  (stale after `task_timeout_seconds`).
- `failed` tasks are retried up to `max_retries`.

**Duplicate prevention:** task_id is deterministic
(`{source}_{chunk_index:04d}` or `{source}_{shard}_full`), so re-planning
after a crash produces the same ids, and the registry dedupes.

---

## 4. Configuration

Extend `config/parallelism.yaml`:

```yaml
parallelism:
  classification:
    stage1_shard_workers: 8
    stage2_shard_workers: 10
    parallel_sources: 2
    skip_v11_sources: true
    print_interval: 1
    scheduler: adaptive          # default
    target_task_size_mb: 512     # ideal task size
    max_task_size_mb: 1024       # hard cap per task
    split_large_shards: true
    min_split_size_mb: 2048      # only split shards >= this
    task_timeout_seconds: 3600   # stale-running threshold
    max_retries: 2
```

**Defaults** preserve current behaviour for small corpora: shards under
512MB → one task each, which is exactly what the current pipeline does.
The scheduler only changes behaviour when a shard is genuinely large or
the workload is very unbalanced.

---

## 5. Performance Report

`reports/performance/{worker_group}_scheduler_report.json`:

```json
{
  "schema_version": "1.0",
  "worker_group": "stage2",
  "generated_at": "...",
  "total_shards": 205,
  "total_bytes": 22000000000,
  "generated_tasks": 48,
  "average_task_size_bytes": 458333333,
  "worker_utilization": 0.87,
  "idle_time_estimate_seconds": 120,
  "largest_shard_bytes": 8000000000,
  "split_operations": 3,
  "task_status_counts": {"pending": 0, "running": 0, "completed": 48, "failed": 0}
}
```

---

## 6. Backward Compatibility

- `run_classify_all_v2.py` (note: the user-facing name; the repo file is
  `run_classify_all_v2.py` at repo root) keeps working with no flags.
- `--scheduler adaptive` is the **default**; `--scheduler static` restores
  the old per-shard assignment.
- Per-source output contract unchanged:
  `metadata/intelligence/_tmp/classified_{label}.jsonl` → merged → deleted
  after append to v1.2 (the append-per-source + `--no-merge` flow is
  untouched).
- The planner degrades to one-task-per-shard when all shards are small, so
  existing runs behave identically.

---

## 7. Testing Strategy

`tests/test_adaptive_scheduler.py` (deterministic, CI-safe):

1. **100 small shards** → 100 tasks (or fewer when capped), balanced,
   no split.
2. **1 huge shard** → N chunk tasks, offsets cover the whole file,
   original untouched.
3. **Mixed shard sizes** → tasks sorted by deterministic order, no worker
   gets a > max_task_size task.
4. **Deterministic task ordering** → same input, same task list (twice).
5. **Resume after failure** → completed tasks skipped, failed re-queued.
6. **Duplicate task prevention** → same task_id not scheduled twice.
7. **Config loading** → defaults + overrides from parallelism.yaml.
8. **Line-offset correctness** → chunk offsets sum to full coverage; a
   simulated streaming read at the offsets returns the right records.

---

## 8. Constraints (non-negotiable)

- Do NOT modify: `releases/`, `metadata/releases/`, HF datasets,
  v1.0 final, v1.0-RC2, running v1.2 output.
- Do NOT change dataset contents (`raw/`, `curated/`).
- Code changes only; the original shard files are read-only.
- Tests must pass before the production path is switched to adaptive.
- Architecture validation must pass (`scripts/validate_architecture.py`).

---

## 9. Implementation Plan

| Commit | Content |
|--------|---------|
| 1 | This design doc (`docs/adaptive_parallel_processing.md` + design section) |
| 2 | `scripts/intelligence/adaptive_scheduler.py` (planner, registry, report), config keys, classifier wiring (`--scheduler adaptive\|static`) |
| 3 | `tests/test_adaptive_scheduler.py` + finalize documentation (tuning guide, examples) |

---

## 10. Future Work

- Multi-node execution: task registry already has `worker_id`; a shared
  registry (NFS/object store) enables cross-machine workers.
- Dynamic rebalancing: move pending tasks from a slow worker to idle ones.
- GPU-aware task sizing for model-based scoring.
