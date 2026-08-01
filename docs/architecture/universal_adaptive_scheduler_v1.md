# Universal Adaptive Scheduler v1 — Architecture

**Status:** Proposed (DESIGN ONLY — awaiting approval before implementation)
**Date:** 2026-08-01
**Phase:** 4C.5 — Parallel Processing v2 / Universal Scheduler
**Audit reference:** `reports/parallelism/atlas_parallelism_audit.md`
**Related ADRs:** ADR-013 (parallel processing), ADR-012 (intelligence layer)

---

## 1. Current State

### 1.1 Parallel implementations today

| Area | Execution model | Config source | Resume |
|------|----------------|---------------|--------|
| Classification (v1.2) | Adaptive scheduler v2 + ProcessPool | `config/parallelism.yaml` | Yes — TaskRegistry |
| v1.2 runner | Custom (ThreadPool sources + subprocess) | CONFIG + CLI | Partial — `--skip` |
| Acquisition engine | Sequential gen + ProcessPool load | CONFIG (`acquisition.file_workers`) | Yes — checkpoint.py |
| Downloader | Sequential | HARD | Partial — cache |
| ETL source processing | Sequential | HARD | Partial — registry log |
| Transform (ParallelRunner) | ThreadPool wrapper | CLI `--max-workers` | Partial — IncrementalState |
| Extraction (run_extract_all) | ProcessPool (per-shard) | CONFIG (`extraction.shard_workers`) | Partial — per-shard files |
| Validation (validate_dataset) | ProcessPool (per-file) | CONFIG (`validation.file_workers`) | No |
| Training views gen | ProcessPool load + seq gen | CONFIG (`training_views.workers`) | Partial — manifest |
| Training views val | ProcessPool (record-chunk) | CONFIG (`training_views.workers`) | No |
| Evaluation | Sequential | HARD | No |
| Release join | Sequential | HARD | Partial — manifest |
| Release compress | ProcessPool | CLI `--workers` (default 1) | Partial — `--skip-existing` |
| Release checksum | Sequential | HARD | Partial — skip-if-exists |
| Release upload | ThreadPool (per-section) | CLI `--workers` (default 4) | Yes — size-match |
| Release publish/promote | Sequential | HARD | No |
| Release download | ThreadPool (HF snapshot) | CONFIG (acq.file_workers reused) | Yes — HF cache |

### 1.2 Duplicated components (from audit)

1. **Parallel curated-file loaders** — `acquisition_engine.engine.generate_knowledge_pack`
   (`_load_one`) vs `training_view_engine.generator` (`_load_view_workers`) — same
   pattern, different worker loaders and config keys.
2. **Per-source execution wrappers** — `ParallelRunner` (ThreadPool),
   `batch_classify_v2._classify_one` (ProcessPool+subprocess),
   `e2e_pipeline`/`automation_runner`.
3. **Split logic** — `batch_classify.split_single_shard` (static chunking) vs
   `adaptive_scheduler.plan_tasks` (adaptive chunking).
4. **Worker-count plumbing** — five independent parsers of
   `config/parallelism.yaml` (`validate_dataset.load_parallelism_config`,
   `adaptive_scheduler.load_scheduler_config`, `run_extract_all.load_config`,
   `acquisition_engine._load_file_workers`, `training_view_engine._load_view_workers`).
5. **Resume helpers** — `downloader/cache.py`, upload size-match,
   compress `--skip-existing`, `TaskRegistry` — four bespoke mechanisms.

### 1.3 Migration candidates

- **High value / low risk:** shared config loader, TaskRegistry as universal
  resume layer, planner as universal task generator.
- **Already adaptive-compatible:** validation, extraction, training views,
  compress, classification.
- **Needs redesign:** downloader, ETL, evaluation, join, publish/promote.

---

## 2. Target Architecture

### 2.1 Shared subsystem: `scripts/parallel/`

```
scripts/parallel/
  __init__.py       # public API: get_scheduler(), plan(), run(), monitor()
  config.py         # single YAML loader + hardware profile + env overrides
  resource.py       # CPU/RAM/disk detection + safe worker limits
  planner.py        # workload -> tasks (file/shard/byte/record-range)
  registry.py       # checkpoint/resume + task state machine
  scheduler.py      # adaptive worker management + backpressure + recovery
  monitor.py        # runtime metrics (CPU/RAM/disk/throughput)
```

### 2.2 Module responsibilities

#### `config.py`
- `load_parallelism_config()` — the **single** YAML loader for
  `config/parallelism.yaml`; removes the five duplicate parsers (Finding 1.2.4).
- `load_hardware_profile()` — merges static profile (from YAML) with runtime
  detection (from `resource.py`).
- Environment overrides: `ATLAS_WORKERS_*`, `ATLAS_PROFILE` env vars
  (last-wins precedence: CLI > env > YAML > hardware default).
- `get_stage_config(stage)` — returns resolved stage settings with defaults.

#### `resource.py`
- `detect_cpu()` — logical cores (`os.cpu_count()`, `len(os.sched_getaffinity(0))`
  where available).
- `detect_ram()` — total + available (`os.sysconf('SC_PAGE_SIZE') ×
  SC_PHYS_PAGES`; psutil optional enhancement).
- `disk_free(path)` — `shutil.disk_usage`.
- `detect_gpu()` — **placeholder**: probe `nvidia-smi` / `torch.cuda` if
  installed; returns `{"present": false, "count": 0}` otherwise (never crashes).
- `safe_worker_limit()` — returns
  `min(cores, max(1, ram_available_mb // per_task_ram_mb))` with a safety
  margin (default 0.8 of available RAM) — **the single place worker counts
  are derived**.

#### `planner.py`
- `plan_workload(spec, config)` → `list[Task]`; converts any pipeline workload
  into tasks.
- Task kinds (from audit E-column):
  - `file` — whole file per task (validation, checksum, upload).
  - `shard` — shard file per task (extraction, compress).
  - `byte` — byte-range chunk of a file (classification adaptive v2).
  - `record_range` — line/record-range chunk (validation record checks,
    training view record validation).
- Deterministic ordering: tasks sorted by `(source, operation, start_offset)`
  so resume/merge is reproducible.
- Splitting policy delegated to Section 4 rules (large task splitting).

#### `registry.py`
- Generic `TaskRegistry` (superset of `adaptive_scheduler.TaskRegistry`).
- Append-only JSONL at `metadata/pipeline_state/task_registry_{stage}.jsonl`.
- States: `pending` → `running` → `completed` | `failed` → (retry) →
  `running` …; `retry` cap from config (`max_retries`).
- API: `plan_tasks()`, `claim_next()`, `mark_running()`, `mark_completed()`,
  `mark_failed()`, `pending()`, `attempts(task_id)`, `summary()`.
- **Resume**: on start, completed tasks are skipped; running tasks from a dead
  worker are re-claimed after a lease timeout (crash recovery).

#### `scheduler.py`
- `AdaptiveScheduler` — owns worker pool per stage.
- `run(tasks, worker_fn)`:
  1. `registry.sync()` (resume completed)
  2. dynamic worker count from `resource.safe_worker_limit()`
  3. bounded submission (never more than N in flight)
  4. backpressure: pause submitting when RAM/disk crosses thresholds
  5. failure recovery: retry failed ≤ `max_retries`, then report
  6. deterministic merge of per-task outputs by `task.id` order
- Worker kinds: `process` (CPU-bound), `thread` (I/O-bound), `subprocess`
  (isolated third-party CLI) — selected per operation.

#### `monitor.py`
- `Monitor` — collects per-second samples: CPU%, RAM used/avail, disk free,
  throughput (records/s), active tasks.
- Writes `reports/performance/{stage}_scheduler_report.json` (extends the
  v2 report format) + optional `metrics.csv` for plotting.
- `metrics()` returns a snapshot for backpressure decisions in scheduler.py.

### 2.3 Pipeline integration pattern

Existing pipelines become thin adapters:

```python
from parallel import get_scheduler

def main():
    sched = get_scheduler("validation")          # config + resources resolved
    tasks = sched.plan("validate_one_file", files)  # planner
    results = sched.run(tasks, validate_one_file)   # registry + pool + monitor
```

No pipeline chooses its own worker count anymore; the scheduler does.

---

## 3. Universal Task Model

### 3.1 Task

```json
{
  "task_id": "validate:curated/v0.2:00041",
  "source": "curated/v0.2",
  "operation": "validate_one_file",
  "input": "metadata/curated/v0.2/file_00041.jsonl",
  "estimated_size_mb": 187.2,
  "priority": 1,
  "status": "pending",
  "worker_group": "validation",
  "offset_start": 0,
  "offset_end": null,
  "created_at": "2026-08-01T00:00:00Z"
}
```

- `task_id` is deterministic (`source:operation:key`) — enables duplicate
  prevention and idempotent resume.
- `offset_start/end` populated for `byte` / `record_range` tasks; null for
  whole-file / shard tasks.
- `priority` reserved for future backpressure ordering (default 1).

### 3.2 Worker

```json
{
  "worker_id": "dev-pc-w1",
  "host": "dev-pc",
  "capacity": 2,
  "memory_limit_mb": 12288,
  "cpu_limit": 8
}
```

- `worker_id` recorded in registry entries (multi-machine readiness).
- Capacity = concurrent tasks this worker may run (I/O workers higher).

---

## 4. Resource-Aware Scheduling Rules

### 4.1 Task size classes

| Class | Size | Policy |
|-------|------|--------|
| Small | < 64 MB | Batch multiple tasks per worker (e.g. 4 small files per process) to reduce spawn overhead |
| Medium | 64–512 MB | One worker per task |
| Large | > 512 MB | Split: line range / record range / shard partition into ≤ target_task_size_mb chunks |

### 4.2 Hard rules (never violated)

1. **RAM safety**: `active_workers ≤ max(1, available_ram_mb / per_task_ram_mb)`
   with a 0.8 utilization cap. If the estimate says 14 workers but RAM allows
   8, the scheduler runs 8.
2. **No permanent CPU saturation**: if sustained CPU > 95% for 60 s and other
   stages are pending, shed low-priority tasks (or serialize them).
3. **Disk headroom**: stages writing outputs require
   `free_disk ≥ max(output_estimate × 1.2, 10 GB)`; otherwise they pause and
   report (disk-full prevention, Section 7.3).
4. **GPU is never assumed**: GPU-aware work (future evaluation) requires
   `resource.detect_gpu()["present"] == true`; otherwise falls back to CPU.

### 4.3 Config representation

```yaml
# config/parallelism.yaml (extended)
parallelism:
  global:
    safety_margin_ram: 0.8
    cpu_saturation_threshold: 0.95
    disk_headroom_gb: 10
    default_per_task_ram_mb: 512
  classification: ...   # unchanged keys
  validation:
    file_workers: auto   # NEW: 'auto' => scheduler decides
    chunk_size: 1000
  extraction:
    shard_workers: auto
    shards_per_source: 41
  training_views:
    workers: auto
  release:
    compress_workers: auto
    upload_workers: 4    # I/O-bound; threads cheap
```

`auto` is the default going forward — the scheduler computes the number.

---

## 5. Hardware Profiles

### 5.1 Developer PC (dev-pc, WSL2 Ubuntu-24.04)

```yaml
hardware_profiles:
  dev-pc:
    cpu_cores: 16
    ram_mb: 30720
    gpu: "RTX 5070 (no driver, unusable)"
    disk_gb: 420
    per_task_ram_mb: 512
    safe_workers: 16        # = min(16 cores, 30720×0.8/512)
    classification_workers: 10   # measured sweet spot
    profile: worker
```

- Classification measured: stage2 10 workers ≈ 600–700 rec/s; single-shard
  sources split to ~6–10 chunks.

### 5.2 Mac (control plane)

```yaml
hardware_profiles:
  mac-controller:
    cpu_cores: 8
    ram_mb: 16384            # adjust to actual
    gpu: null
    disk_gb: 512
    profile: controller
```

- Runs orchestration, git, review tooling — NOT heavy pipeline stages.
- All heavy work dispatched to dev-pc over SSH/Tailscale.

### 5.3 Future: multi-node worker

```yaml
hardware_profiles:
  worker-node-01:
    cpu_cores: 64
    ram_mb: 262144
    gpu: "A100-80G × 8 (placeholder)"
    disk_gb: 2000
    profile: worker
```

- Identical config schema; only `profile: worker` + network attachment differ.

### 5.4 Profile resolution

1. `ATLAS_PROFILE` env var (if set).
2. `--profile` CLI flag (if set).
3. Hostname match in `hardware_profiles` (e.g. `dev-pc`).
4. Fallback: auto-detect via `resource.py` (no YAML needed).

---

## 6. Migration Strategy

### P0 — First wave (highest value, lowest risk)

| Pipeline | Current state | Migration effort | Expected benefit |
|----------|--------------|------------------|------------------|
| Validation | ProcessPool file-level, config `file_workers=8`, no resume | LOW — files already map to tasks; swap executor for scheduler.run | Resume + adaptive sizing; uneven files no longer block |
| Extraction | ProcessPool shard-level, config `shard_workers=8` | LOW — shards map to tasks | Byte-aware split for uneven shards; registry resume |
| Training views | ProcessPool load + record validate | MEDIUM — generator/validator share pools; migrate both | Memory safety (record-chunk backpressure); per-model views parallel |

### P1 — Second wave

| Pipeline | Current state | Migration effort | Expected benefit |
|----------|--------------|------------------|------------------|
| Compression | ProcessPool, CLI `--workers` default 1 | LOW — shard tasks fit planner | Adaptive workers (real default >1); skip-existing via registry |
| Classification cleanup | Adaptive v2 exists but bespoke | MEDIUM — port to shared modules, keep behavior | Single codebase; remove split_single_shard duplication |
| ETL | Sequential per source | MEDIUM — adopt ParallelRunner-style fan-out | Source-level parallelism |

### P2 — Third wave

| Pipeline | Current state | Migration effort | Expected benefit |
|----------|--------------|------------------|------------------|
| Acquisition | Sequential gen + ProcessPool load | MEDIUM — reuse registry with existing checkpoint | One resume mechanism |
| Release publishing | Sequential (promote/publish) | LOW | Uniformity; idempotency |

### P3 — Last wave

| Pipeline | Current state | Migration effort | Expected benefit |
|----------|--------------|------------------|------------------|
| Evaluation | Sequential dry-run | HIGH — needs real execution model first | Parallel benchmarks when full eval lands |

---

## 7. Failure Scenarios

| Scenario | Handling |
|----------|----------|
| **Worker crash** | Registry marks task `failed`; scheduler retries ≤ `max_retries`; per-task output files are partial-safe (rename-to-final only on success). |
| **Machine reboot** | Registry is append-only JSONL on disk; restart `scheduler.run` → completed tasks skipped, `running` tasks re-claimed after lease timeout (default 15 min), remaining tasks continue. |
| **Disk full** | Monitor checks `disk_headroom_gb` before each batch; on low disk: pause submissions, flush completed outputs, raise `DiskFullSignal` with a clear message. |
| **Partial output** | Workers write to `_tmp/{task_id}.part`; final rename only after validation (line count / checksum); registry `completed` only after rename. |
| **Duplicate task execution** | Deterministic `task_id` + registry `claim_next()` is atomic-ish (append-only claim line); completed tasks are skipped on resume; merge dedupes by task_id. |
| **Network interruption** | I/O operations retry with backoff (existing upload/download pattern); registry status stays `running` until lease expiry, then re-claim. |

---

## 8. Multi-Machine Future

### 8.1 Topology

```
Mac controller (orchestration, review, git)
      |
      |  SSH / Tailscale (dev-pc has Tailscale-ready network)
      v
dev-pc workers (WSL2, 16C/30GB)     future: GPU nodes (A100 etc.)
      |                                    |
      +------------ shared TaskRegistry ---+
              (NFS / object store / SQLite)
```

### 8.2 Design extensions (not implemented now)

1. **Registry on shared store** — `metadata/pipeline_state/` moves to NFS /
   SQLite so any node sees the same task state.
2. **Content-addressed tasks** — task_id = hash(input, offset, operation);
   any node may claim any task; result merge by task_id order.
3. **Worker advertisement** — each node runs a worker agent that registers
   with the controller (host, capacity, resources) — Worker model already
   supports it.
4. **Stage-to-host pinning** — `worker_group → host` mapping in config
   (e.g. classification → dev-pc, evaluation → GPU node).
5. **Tailscale** — control-plane (Mac) reaches dev-pc over the mesh;
   no port-forwarding changes needed for SSH-driven dispatch.

---

## 9. Performance Goals

| Goal | Definition |
|------|-----------|
| No manual worker counts | Every pipeline uses `auto` or scheduler-computed limits; `config/parallelism.yaml` remains the single source for *policies* (per-task RAM, thresholds), not hard numbers |
| Scheduler decides based on hardware | `safe_worker_limit()` from `resource.py` at runtime |
| All long jobs resumable | Every stage ≥ MEDIUM bottleneck gets a TaskRegistry entry; `resume` is the default CLI behavior |
| No duplicate processing | Deterministic task_ids + registry skip |
| No RAM explosion | 0.8 RAM cap + per-task RAM estimate; backpressure on memory pressure |
| Predictable throughput | Monitor reports records/s per stage; classification target ≥ 600 rec/s sustained on dev-pc; validation target: full v1.2 (9.3M records) < 30 min with 8 workers |

---

## 10. Deliverables

**This phase (design only):**
- [x] `docs/architecture/universal_adaptive_scheduler_v1.md` (this document)
- [x] ADR (ADR-015-universal-scheduler.md — created alongside)

**Explicitly NOT in scope (awaiting approval):**
- No changes to `scripts/parallel/` (does not exist yet beyond stub `__init__.py`)
- No pipeline refactors
- No dataset / release / HF operations
- No config changes

**After approval, implementation order:**
1. `config.py` + `resource.py` (shared loaders; remove 5 duplicate parsers)
2. `registry.py` (universal TaskRegistry)
3. `planner.py` (universal task generation)
4. `scheduler.py` + `monitor.py`
5. P0 migrations: validation → extraction → training views
6. P1–P3 per Section 6

---

## Appendix: Mapping audit findings → architecture

| Audit finding | Addressed by |
|---------------|--------------|
| 5 duplicate config parsers | `config.py` single loader |
| Duplicate loaders (acq vs views) | `scheduler.run()` + `planner` task kinds |
| Duplicate split logic | `planner.py` byte/record-range splitting |
| 4 bespoke resume helpers | `registry.py` |
| No resource awareness anywhere | `resource.py` + `monitor.py` + Section 4 hard rules |
| Sequential pipelines | Migration plan Section 6 |
