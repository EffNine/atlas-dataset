# Compression Migration Design — Universal Scheduler Phase 6

**Date:** 2026-08-02
**Status:** APPROVED — implemented (Phase 6B). See
`reports/parallelism/scheduler_phase6_compression_report.json`.
**Audit reference:** `reports/parallelism/compression_audit.md` + `.json`
**Upstream:** Phase 5E final audit — compression identified as the cleanest
Phase 6 target (file-task model, `_route_shard` already module-level, output
sorted by input name, no cross-shard merge).

---

## 1. Objective

Migrate `scripts/release/compress_release.py`'s **execution layer** to the
Universal Scheduler (`scripts/parallel/`) while preserving behavior:

- identical output bytes (per-category `*.jsonl.zst` files, same record order,
  same zstd level),
- identical report semantics (`compression_report.json`, `statistics.json`,
  exit codes 0/1/2),
- identical CLI surface (`--release/--input/--pattern/--output/--workers/
  --level/--dry-run/--skip-existing`),
- sequential fallback on any scheduler failure (byte-identical output),
- registry resume + retry + lease-based crash recovery (new capabilities,
  additive only).

**Explicitly out of scope:** `generate_checksums.py`, `verify_release.py`,
`dedup_release.py`, `upload_huggingface.py`, `download_release.py` (Phase 7),
dataset content, raw data, HF operations.

---

## 2. Current Architecture (summary)

- CLI-only tool; no production callers (tests invoke it as subprocess).
- One module-level worker `_route_shard(args)` — streams a shard, routes each
  record by `category`, writes per-category zstd files, verifies in-worker
  (decompress + count + sha256).
- `ProcessPoolExecutor` with raw `--workers` int (default 2); `workers <= 1`
  → sequential loop.
- No registry, no retry; resume = `--skip-existing` disk scan.
- Report aggregation deterministic: sorted by shard filename.
- Output files are disjoint per task (each shard owns its
  `{category}/{stem}.jsonl.zst` files) → no merge step exists.

---

## 3. Task Model

| Field | Value |
|-------|-------|
| `task_id` | `compress:{release}:{shard_stem}` (e.g. `compress:v1.0-RC1:ultrafeedback_atlas.jsonl`) |
| `source` | `compression` |
| `operation` | `compress` |
| `input` | absolute path to the shard JSONL file |
| `estimated_size_mb` | `shard_size_bytes / (1024*1024)` (from `file_tasks()`) |
| `status` | `pending` (registry lifecycle) |
| `extra` | `{"out_root": str, "level": int, "release": str}` |

**Why the release tag in task_id:** the registry lives at repo-global
`metadata/pipeline_state/`. A bare `compress:{shard_stem}` would be shared
across releases — compressing `v1.0-RC2` would see `v1.0-RC1`'s tasks as
completed and wrongly skip. The release prefix makes each release's tasks
distinct while keeping the id deterministic and sortable (single-release runs
sort exactly by shard name, preserving report order).

**Planner:** `parallel.planner.file_tasks(shards, source="compression",
operation="compress")` — sorted by filename, one Task per shard. The
`--skip-existing` disk scan runs at plan time (unchanged semantics, layered on
registry resume).

---

## 4. Worker Model

New module `scripts/release/scheduler_tasks.py` (mirrors 5B/5C pattern):

| Function | Role |
|----------|------|
| `plan_compress_tasks(shards, release, out_root, level)` | file tasks with release-scoped task_id + `extra` |
| `compress_task(task)` | module-level worker: builds `_route_shard` args dict from `task.input`/`task.extra`, calls `_route_shard` verbatim; **raises** on `errors` or any `verified.ok == False`; returns result with `"total"` alias added for registry telemetry |
| `run_compression_scheduler(shards, release, out_root, level, workers, skip_existing, dry_run, ...)` | planner → `Scheduler(stage="compression", pool="process", ...)` → serialized finalize; sequential fallback on scheduler import error |

**Rules:**
- `_route_shard` stays in `compress_release.py`, module-level, untouched —
  the old sequential/ProcessPool path and the scheduler path share it.
- `compress_task` must be module-level (picklable for process pool); no
  lambdas/closures.
- **Retry contract:** a task that fails verification raises → scheduler
  records `retry` → resubmits; terminal failure after `max_retries` →
  `failures[]` + exit 1 (today's exit semantics preserved).
- Retry rewrites the shard's own output files (`open(..., "wb")` overwrite) —
  no duplicate records possible because each task owns disjoint files.

---

## 5. Registry Stage Naming

- **Stage key: `compression`** (per 5E recommendation) →
  `metadata/pipeline_state/task_registry_compression.jsonl`.
- Rationale: isolates compression from future Phase 7 release-tool registries
  (`upload`, `dedup`); task_ids already carry an operation prefix so a shared
  `release` registry would also work, but per-stage separation keeps each
  pipeline's state inspectable.
- **Worker resolution:** `resolve_worker_count("release")` (reads
  `release.compress_workers`, currently `"auto"` → scheduler picks
  `safe_worker_limit()`) with `--workers` as the explicit CLI override
  (precedence: CLI > env `ATLAS_WORKERS_RELEASE` > config > auto).
- **Config change (implementation-time):** pin a modest `compress_workers`
  value (e.g. 4) in `config/parallelism.yaml` to bound disk pressure, or
  document `"auto"` behavior change. **Decision D3.**

---

## 6. Retry Policy

| Aspect | Policy |
|--------|--------|
| `max_retries` | 2 (registry default) |
| Trigger | worker exception (read error, zstd write error, verification mismatch) |
| Transition | `failed` → `retry` → `running` (scheduler `_settle`) |
| Attempts counted | from append-only registry file (`registry.attempts()`) |
| Terminal | `failed` after max retries → `failures[]` → exit 1 |
| Backoff | scheduler's built-in `min(BACKPRESSURE_POLL_S, attempts+1)` |

Behavior change vs today: verification failures are retried instead of a hard
exit-1 on first mismatch. Documented as intentional (F2).

---

## 7. Resume Mapping

- **Registry resume:** completed task_ids skipped (`status="skipped"`, results
  not re-stored — reload from disk/report or re-verify inline as needed);
  stale `running` re-claimed after lease (default 900s).
- **`--skip-existing` (kept, decision D2):** planner-time disk scan — skip
  shard if outputs exist and decompress OK. Layers on top of registry resume:
  - legacy runs (no registry) still skip via disk;
  - registry-completed tasks skip even if the flag is off;
  - deleted outputs after completion → registry says completed, `--skip-existing`
    would re-run (disk check wins when flag present); without the flag the task
    stays skipped — downstream `verify_release.py` catches missing files.
- **Crash recovery:** completed-skip + stale-running re-claim + per-shard task
  granularity closes the today's partial-output hole (F1): a crash mid-shard
  leaves the task `running` → re-claimed → re-run → full rewrite of that
  shard's outputs.

---

## 8. Deterministic Merge Strategy

- **No merge step exists** and none is introduced: outputs are disjoint
  per-task files. The scheduler never merges category folders.
- **Ordering:** `Scheduler.run()` returns results sorted by `task_id`;
  `compress:{release}:{stem}` sorts by shard name within one release →
  identical to today's `sorted(results, key=lambda x: x["input"])`.
- **Finalize (serialized, single writer):** iterate results in task_id order,
  aggregate `by_category`/`per_file`/`failures`, write
  `compression_report.json` + `statistics.json`. Same code as today's
  aggregation, just consuming scheduler results in deterministic order.
- **Byte determinism:** zstd single-threaded frames at fixed `level` →
  identical output files for identical input. Only `utc_now`/`elapsed_s` in
  the report differ between runs (report-only, not data) — same as today.

---

## 9. Fallback Strategy

```python
try:
    from parallel.scheduler import Scheduler
    from parallel.config import resolve_worker_count
    ...scheduler path...
except Exception as exc:
    print(f"...scheduler unavailable ({exc}); falling back to sequential", file=sys.stderr)
    ...original ProcessPoolExecutor/sequential loop (byte-identical)...
```

- Module-level `_SCHEDULER_ENABLED = True` kill-switch inside the try block;
  setting it `False` forces the fallback (test hook + operational override).
- `scripts/release/common.py` + `_route_shard` remain importable without
  `scripts/parallel` on the path (fallback never depends on the scheduler).
- Output from either path is byte-identical; registry is only written by the
  scheduler path.

---

## 10. Rollback Strategy

1. **Git revert** of the implementation commit — the tool, tests, and docs
   revert to the audited baseline (Phase 5E state).
2. **Runtime kill-switch:** `_SCHEDULER_ENABLED = False` → sequential fallback
   immediately, byte-identical output, no code change.
3. **Registry reset:** delete/rename `task_registry_compression.jsonl` to force
   a full re-run (equivalent to pre-migration behavior).
4. **No dataset/release/HF impact:** compression output is identical either
   way; releases untouched by this phase.
5. Rollback decision documented in the Phase 6B report if required.

---

## 11. Risks

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| R1 | Worker-count behavior change: `auto` → `safe_worker_limit()` (up to CPU cores) vs today's default 2 → higher disk write pressure on 22 GB raw input | Medium | Pin `compress_workers` in YAML (decision D3); keep `--workers` override; docs note `--workers 1` for constrained machines |
| R2 | Cross-release registry collision if task_id omits release | High | Release embedded in task_id (design §3) |
| R3 | Registry-completed task whose outputs were manually deleted stays skipped | Low | `--skip-existing` disk check re-runs when flag present; `verify_release.py` catches downstream; document |
| R4 | Verification mismatch now retries (behavior change) | Low | Intentional (F2); terminal failure still exits 1 |
| R5 | macOS spawn pickling: `compress_task` must be module-level | Low | Module-level only, dict payloads, existing tests already exercise spawn with `--workers 2` |
| R6 | Report aggregation order must match today byte-for-byte (minus timestamps) | Medium | Finalize consumes results sorted by task_id; determinism test compares old vs new reports |
| R7 | Registry `record_count` telemetry shows 0 unless worker result includes `total` | Low | `compress_task` adds `"total"` alias (F6) |
| R8 | `_backpressure()` dead code in scheduler (5E R1) — not wired during this phase | Low | Out of scope; bounded submission still caps in-flight workers; revisit scheduler-wide |

---

## 12. Implementation Sketch (Phase 6B, after approval)

1. `scripts/release/scheduler_tasks.py` — `plan_compress_tasks`, `compress_task`,
   `run_compression_scheduler` (+ fallback + kill-switch).
2. `scripts/release/compress_release.py` — `main()` calls
   `run_compression_scheduler` in the try block; original loop kept as fallback.
3. `config/parallelism.yaml` — pin `release.compress_workers` (decision D3).
4. `tests/test_scheduler_compression.py` — planning, worker limits, retry,
   resume, failed-task recovery, deterministic output (old vs new hashes).
5. Determinism verification: old CLI vs scheduler on fixture shards → same
   output hashes + same record counts; reports differ only in timestamps.
6. Docs: `docs/parallel/universal_scheduler_usage.md` migration example +
   `reports/parallelism/scheduler_phase6_compression_report.json`.
7. Phase-gated commits; arch validator + fresh ad-hoc probe before commit.

**STOP — implementation does not begin until design review approval.**
