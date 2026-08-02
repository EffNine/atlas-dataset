# Compression Pipeline Audit — Universal Scheduler Phase 6A

**Date:** 2026-08-02
**Mode:** AUDIT ONLY — no code changes, no dataset changes, no release/HF operations
**Baseline:** `f147a2e` (main)
**Upstream:** Phase 5E final audit (`reports/parallelism/universal_scheduler_final_audit.md`)
→ recommended compression as the next migration (cleanest fit: file-task model,
`_route_shard` already module-level, output sorted by input name).

---

## 1. Executive Summary

`scripts/release/compress_release.py` is the only compression pipeline. It is a
standalone CLI tool: globs JSONL shards, routes each record by its `category`
field into per-category writers, compresses with zstd (level 19 default), and
verifies every output in the worker before returning. It already uses a
`ProcessPoolExecutor` keyed off a raw CLI `--workers` int, with NO registry, NO
retry, and NO resource awareness. Resume is a disk-based `--skip-existing` scan.

It is the cleanest possible Universal Scheduler migration target:

- **Task unit is already a file (shard)**; `_route_shard` is already module-level
  and picklable — no refactor of the worker body required.
- **No cross-shard merge exists**: each shard writes its own
  `{category}/{shard_stem}.jsonl.zst` files, so workers never touch shared
  output files — parallelism is safe by construction.
- **Deterministic output is already guaranteed by construction**: results are
  aggregated sorted by input filename; per-shard category output order follows
  input record order.
- **Gaps to close**: registry (none), retry (none — verification failure = hard
  exit 1), worker limits (raw CLI int, no RAM/CPU caps), resume (disk scan only,
  not task-state based), `task_id` must embed the release tag to prevent
  cross-release registry collisions.

---

## 2. Pipeline Inventory

### 2.1 Entry points

| Entry point | Type | Invoked by |
|-------------|------|------------|
| `scripts/release/compress_release.py` (CLI `main()`) | script | manual per docs (`docs/huggingface_release_pipeline.md` §3 step 1) |
| `_route_shard(args)` | module-level worker | internal (ProcessPoolExecutor + sequential path) |
| `scripts/release/common.py` | shared helper module | `iter_jsonl`, `open_zstd_writer`, `count_jsonl_zst`, `sha256_file`, `CATEGORIES`, `DEFAULT_ZSTD_LEVEL` |

Call graph (grep-verified): NO production code invokes `compress_release.py` as a
subprocess or library. Only `tests/test_release_pipeline.py` invokes it (4
compression tests: routing/mixed shards, report+statistics, dry-run, skip-existing).
`e2e_pipeline.py`, `progressive_expansion*.py`, `promote_release.py`,
`join_release.py`, `build_release_metadata.py`, `run_pipeline.sh` do NOT call it
(build_release_metadata only *reads* `dataset/<category>/*.jsonl.zst`).

### 2.2 CLI surface

| Flag | Default | Meaning |
|------|---------|---------|
| `--release` | `v1.0-RC1` | release tag → output root `releases/<release>/dataset/` |
| `--input` | `<repo>/raw/generated` | directory containing JSONL shards |
| `--pattern` | `*_atlas.jsonl` | glob for shard files |
| `--output` | None | explicit release root override |
| `--workers` | **2** | raw parallel worker count (old audit said 1 — stale; on-disk default is 2) |
| `--level` | 19 | zstd level (1-22) |
| `--dry-run` | False | list shards + preview category, write nothing |
| `--skip-existing` | False | skip shards whose output files exist and decompress OK |

### 2.3 Output artifacts

- `releases/<release>/dataset/<category>/<shard_stem>.jsonl.zst` — one file per
  (category, shard) actually containing that category.
- `releases/<release>/metadata/compression_report.json` — per-file records/bytes/
  sha256, by-category totals, failures list.
- `releases/<release>/metadata/statistics.json` — record counts per category.
- Exit codes: 0 = all verified OK; 1 = any failure; 2 = no shards matched.

---

## 3. Execution Model

### 3.1 Shard routing (worker behavior)

`_route_shard(args)` — module-level, takes a JSON-safe dict
`{input_path, out_root, level}`:

1. Streams the shard line-by-line (`iter_jsonl`, O(1) memory).
2. Routes each record by `rec["category"]` (NOT filename — mixed shards exist,
   e.g. `ultrafeedback_atlas.jsonl` spans 01_foundation + 08_creative_knowledge).
3. Opens a zstd writer per encountered category:
   `{out_root}/{cat}/{input_path.stem}.jsonl.zst` (mkdir via `open_zstd_writer`).
4. Records with unknown category → appended to `errors`, skipped.
5. Closes all writers, then **verifies in the same worker**: decompresses each
   output (`count_jsonl_zst`) and computes per-file `bytes` + `sha256`.
6. Returns a JSON-safe result dict: `{input, input_bytes, input_records,
   by_category, verified, errors, elapsed_s}`.

### 3.2 Executor usage

```
workers <= 1  → sequential loop (same worker function, no pool)
workers  > 1  → ProcessPoolExecutor(max_workers=args.workers)
                futures = {pool.submit(_route_shard, t) for t in tasks}
                results collected via as_completed (completion order, then re-sorted)
```

- Pool: **process** only. No thread pool, no `multiprocessing` module, no
  `parallel.*` imports anywhere in `scripts/release/compress_release.py`.
- `_route_shard` is the ONLY function sent to the pool; it is module-level and
  picklable. The dict args pattern means no unpicklable state crosses the
  boundary. macOS spawn works today (tests run with `--workers 2`).

### 3.3 Merge / order guarantees

- **No merge step exists.** Per-category folders are populated independently;
  file names = shard stems, so folder ordering is filename order.
- Report aggregation is deterministic: `for r in sorted(results, key=lambda x:
  x["input"])` — i.e. sorted by shard filename. Within a shard, `verified` dict
  iterates categories in first-encounter order (deterministic for fixed input).
- zstd single-threaded frames (`zstd.ZstdCompressor(level=level)`), so output
  bytes are deterministic for identical input + level. `utc_now()`/`elapsed_s`
  in the report are the only non-deterministic fields (report only, not data).

### 3.4 Retry / resume behavior

- **Retry: NONE.** Any hard failure (worker exception, verification mismatch,
  read error) propagates to `failures[]` and the run exits 1. No retry, no
  backoff, no task-state tracking.
- **Resume: `--skip-existing` only.** Planner-time disk scan: for each shard,
  if ANY `{category}/{stem}.jsonl.zst` exists AND all found files decompress
  OK (`count_jsonl_zst >= 0`), the shard is skipped. This is a disk heuristic,
  not task state. Two failure modes:
  - Partial-output shards (some categories written before crash) are NOT
    detected as corrupt — only files that *exist* are checked, so a crash that
    wrote category A but not B leaves A's file intact and the shard is skipped
    on resume → silent partial output. (Today's risk; registry + per-shard
    atomicity closes it.)
  - A corrupt-but-countable file (count ≥ 0 but wrong records) is treated as OK.

### 3.5 Checksum / integrity handling

- In-worker verification: every output decompressed + counted immediately after
  writing (`count_jsonl_zst`), plus `sha256_file` recorded in the report.
- Report aggregates `verified[cat].ok` and appends to `failures[]` on mismatch;
  exit 1 if any failure.
- The report's sha256 is informational for downstream `generate_checksums.py` /
  `verify_release.py` (separate tool, out of scope).

### 3.6 Resource usage

| Dimension | Current state |
|-----------|---------------|
| CPU | raw CLI int (default 2), no caps, no adaptive sizing. zstd level 19 is CPU-heavy; uneven shard sizes idle fast workers |
| RAM | O(1) streaming per worker + zstd frame buffers; no RAM-aware limit (docs warn "keep low on 8GB RAM machines") |
| Disk | writes ~1/3 of raw input; docs warn "ensure free space ≥ source size"; NO disk check in code (`disk_free()` in `parallel/resource.py` is reporting-only) |
| Backpressure | none |
| Config | reads NO `config/parallelism.yaml`; worker count is CLI-only |

---

## 4. Migration Boundary

### 4.1 What becomes a Scheduler task

- **One task per shard** (file task). Worker = `compress_task(task)` — a thin
  module-level wrapper that builds the existing `_route_shard` args dict from
  `task.input` + `task.extra` and calls `_route_shard` verbatim. The worker body
  stays untouched (byte-identical behavior preserved).
- Worker resolution/limit → `resolve_worker_count("release")` /
  `safe_worker_limit()` (adaptive), with `--workers` kept as the explicit CLI
  override (precedence: CLI > env > config > auto).
- Retry: worker **raises** when `errors` non-empty OR any `verified.ok == False`
  (today it only records; scheduler retry needs an exception) → scheduler retries
  up to `max_retries`, then terminal fail → exit 1 (same final exit semantics).

### 4.2 What must remain serialized

- **Planner**: glob + sort shards, `--skip-existing` disk scan, dry-run listing.
- **Finalize (single writer)**: aggregation loop (must iterate results sorted by
  task_id == shard name order), `compression_report.json` + `statistics.json`
  writes, exit-code decision. Mirrors the "pure workers + serialized finalize"
  pattern from 5C.

### 4.3 What state belongs in TaskRegistry

- `task_id`, `status` (pending/running/completed/failed/retry/skipped), `attempt`,
  `timestamp`, `error`, and telemetry (`record_count` via `_record_count`).
- **`task_id` MUST embed the release tag**: `compress:{release}:{shard_stem}`.
  The registry lives at repo-global `metadata/pipeline_state/`; a bare
  `compress:{shard}` would collide across releases (v1.0-RC1 vs v1.0-RC2) and
  wrongly skip the second release's compression.

### 4.4 What cannot be parallelized (deterministic output)

- Nothing at the shard level — shard outputs are disjoint by construction. The
  only deterministic-order requirement is the **report aggregation order**
  (sorted by shard name), which stays in serialized finalize. Scheduler returns
  results sorted by task_id; for a single-release run, `compress:{release}:{stem}`
  sort == shard-name sort, so finalize order is preserved byte-identically.

---

## 5. Evaluation Against Universal Scheduler (`scripts/parallel/`)

| Module | Evaluation for compression | Verdict |
|--------|---------------------------|---------|
| `config.py` | `resolve_worker_count("release")` reads `release.compress_workers` (DEFAULTS: `"auto"`; YAML has no `release:` section — verified on disk). "auto" → scheduler picks `safe_worker_limit()` | READY (config canonical; explicit CLI override preserved) |
| `resource.py` | `safe_worker_limit()` (CPU×RAM) fits a CPU-bound zstd workload; per-task RAM default 512 MB is generous for O(1) streaming workers; `disk_free()` reporting-only (R2 from 5E: re-evaluate for disk-heavy compression) | READY; note disk headroom risk |
| `models.py` | `Task` + `TaskResult` fit file tasks directly; `extra={"out_root":…, "level":…}` | READY |
| `registry.py` | `TaskRegistry(root, "compression")` → `metadata/pipeline_state/task_registry_compression.jsonl`; lease re-claim (900s default) covers crashed workers; `attempts()` from append-only file | READY (stage naming decision below) |
| `planner.py` | `file_tasks()` gives one Task per shard with `estimated_size_mb`; task_id = `source:operation:name` matches `compress:{release}:{stem}` if source="compression", operation="compress" | READY |
| `scheduler.py` | `Scheduler.run()` provides bounded submission, retry ≤ max_retries, resume-skip of completed, deterministic result sort by task_id, in-run task_id dedupe; `worker_limit_fn` not needed (CPU-bound → process pool) | READY; `_backpressure()` dead-code noted (scheduler-wide cleanup, out of scope) |
| `monitor.py` | Optional `Monitor` writes `reports/performance/compression_scheduler_report.json`; not required for correctness | OPTIONAL |

### Boundary review (5E step 4 re-check)

- `scripts/parallel/` is canonical and stable (6 pipelines migrated, 5D shims in place).
- Worker picklable: `compress_task` + `_route_shard` module-level, dict-only payloads.
- Task_ids deterministic: `compress:{release}:{stem}` (release-embedded to avoid
  cross-release collisions — refinement over 5E's bare `compress:{shard}`).
- Merges sorted: finalize re-orders by task_id; single-release == filename order.
- Retries don't duplicate outputs: worker re-opens writers with `"wb"` (overwrite),
  each task owns its files → retry rewrites atomically per-file, no dupes.

---

## 6. Findings

| # | Finding | Severity | Impact |
|---|---------|----------|--------|
| F1 | No registry / no task-state resume; `--skip-existing` is a disk heuristic that can silently accept partial output after a crash | Medium | Migration closes this via per-shard task completion + lease re-claim |
| F2 | Verification failure is non-retryable (hard exit 1); worker records `ok=False` instead of raising | Low | Migration: worker raises → scheduler retry; exit 1 preserved on terminal failure |
| F3 | Worker count is raw CLI int (default 2), no RAM/CPU caps; uneven shards idle workers | Medium | `resolve_worker_count("release")` + `safe_worker_limit()`; `--workers` stays as override |
| F4 | Zero disk-awareness while compression is disk-heavy (docs: keep free space ≥ source size) | Medium | Keep `--workers 1` guidance; optional pre-flight `disk_free()` check in finalize (design decision) |
| F5 | `task_id` must embed release tag or the global registry collides across releases | High (design) | `compress:{release}:{stem}` — resolved in design |
| F6 | Registry `record_count` telemetry: `_record_count()` looks for `record_count/total/classified/processed`; worker returns `input_records` → 0 unless worker result adds a `total` alias | Low | Add `"total": total` in worker result payload |
| F7 | `--skip-existing` semantics vs registry resume divergence (file deleted but task completed) | Low | Keep flag as planner-time disk check; registry resume is additional; verify_release catches missing files downstream |
| F8 | Old `atlas_parallelism_audit.md` says worker default 1 — stale; on-disk default is 2 | Info | Document corrected default |

---

## 7. Decisions Needed Before Implementation

1. **Registry stage key**: `compression` (→ `task_registry_compression.jsonl`,
   per 5E recommendation) vs `release` (shared with future dedup/upload tasks).
   Recommendation: **`compression`** — isolates from Phase 7 release tools;
   task_ids already carry operation prefix for future sharing.
2. **`--skip-existing` mapping**: keep as planner-time disk check layered on
   registry resume (recommended — belt-and-suspenders, preserves today's flag
   contract) vs pure registry state.
3. **Worker cap**: leave `release.compress_workers` at `"auto"` (safe limit —
   behavior change from default 2) vs pin a concrete value (e.g. 4) in
   `config/parallelism.yaml` to bound disk pressure. Recommendation: pin a
   modest default in YAML at implementation time, document `ATLAS_WORKERS_RELEASE`
   / `--workers` for constrained machines.
4. **Failure semantics**: worker raises on verification mismatch (retryable,
   recommended) vs record-only (today's behavior, exit 1 without retry).

---

## 8. Verification (this audit)

- Mode: read-only. No source/dataset/release/HF files modified.
- `git status` baseline: `f147a2e` clean except the two untracked Phase 5E final
  audit reports (`universal_scheduler_final_audit.{md,json}` — pre-existing,
  untouched by this phase).
- On-disk probes run (fresh, temporary, cleaned up):
  - `resolve_worker_count("release")` → `"auto"`; `release` stage cfg =
    `{'compress_workers': 'auto', 'upload_workers': 4}`; YAML has no `release:`
    section (defaults only).
  - Call graph grep: no production invoker of `compress_release.py`; only
    `tests/test_release_pipeline.py`.
  - `releases/` contains `v1.0-RC1`, `v1.0-RC2`, `restored` — untouched.
- See `reports/parallelism/compression_audit.json` for the machine-readable
  schema + probe evidence.

**STOP — awaiting design review approval before Phase 6B (implementation).**
