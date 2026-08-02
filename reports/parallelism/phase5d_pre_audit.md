# Phase 5D Pre-Audit — Universal Scheduler Hardening Preparation

**Date:** 2026-08-02
**Mode:** Read-only workspace audit (no code, no commits, no dataset/HF/release operations)
**Repository:** `/Users/afnanrudy/Github-Projects/atlas-dataset` (macOS checkout)
**Baseline:** HEAD == origin/main == `5224e17` (0 ahead / 0 behind)

---

## 1. Git State Audit

### 1.1 Summary

| Metric | Value |
|--------|-------|
| Current HEAD | `5224e17` chore: refresh architecture validation report |
| Remote HEAD (origin/main) | `5224e17` |
| Divergence | **0 ahead / 0 behind** (clean sync with origin) |
| Modified (unstaged) | 12 files |
| Staged | 0 files |
| Untracked | 4 files |
| Total uncommitted work | 16 files — **all Phase 5D cleanup/preparation, none committed** |

### 1.2 Modified files — classification

| File | Δ | Classification |
|------|---|----------------|
| `config/parallelism.yaml` | +16 | **Required change** — adds precedence documentation header only; no key/value changes |
| `scripts/parallel/config.py` | +13 | **Required change** — docstring documents worker resolution precedence (5-level); no logic change (module already had `explicit` support) |
| `scripts/parallel/__init__.py` | +34 | **Required change** — docstring replaced with "Scheduler API Freeze v1" public-API contract |
| `scripts/validate_dataset.py` | +12/-9 | **Required change** — removes local `load_parallelism_config()`; imports `parallel.config` |
| `scripts/run_extract_all.py` | +20/-13 | **Required change** — removes inline YAML loader; uses `resolve_worker_count("extraction", ...)`; `--shard-workers` CLI still honored |
| `scripts/training_view_engine/generator.py` | +22/-11 | **Required change** — `_load_view_workers()` now resolves via `parallel.config` with classification fallback |
| `scripts/acquisition_engine/engine.py` | +14/-8 | **Required change** — `_load_file_workers()` now resolves via `parallel.config` |
| `scripts/release/download_release.py` | +18/-10 | **Required change** — inline YAML loader replaced; `resolve_worker_count("acquisition", ...)` |
| `scripts/intelligence/batch_classify_v2.py` | +10/-0 | **Required change** — `ProcessPoolExecutor(max_workers=args.workers)` → `resolve_worker_count("classification", ...)` |
| `scripts/intelligence/batch_classify.py` | +71/-924 | **Required change (large)** — converted from full implementation (35KB) to deprecation shim forwarding to `batch_classify_v2` |
| `scripts/intelligence/adaptive_scheduler.py` | +222/-299 | **Required change (large)** — converted from full implementation to deprecation shim forwarding to `scripts/parallel/` |
| `metadata/architecture_validation_report.json` | 1 line | **Generated artifact** — timestamp bump only (validator re-run at 07:40) |

### 1.3 Untracked files — classification

| File | Classification |
|------|----------------|
| `docs/architecture/scheduler_api_freeze_v1.md` (238 lines) | **Documentation — Phase 5D preparation** (API freeze contract, removal target v2.0) |
| `docs/architecture/scheduler_cleanup_design_v1.md` (248 lines) | **Documentation — Phase 5D design doc** (authored "Agnes (Sapiens AI)", Status: Draft) |
| `docs/architecture/scheduler_deprecation_policy.md` (118 lines) | **Documentation — Phase 5D preparation** (deprecation policy, removal timeline) |
| `reports/parallelism/scheduler_cleanup_audit.md` (185 lines) | **Report — Phase 5D cleanup audit** (parallel-implementation inventory) |

### 1.4 Change-type tally

| Type | Files |
|------|-------|
| Required change (cleanup implementation) | 10 code files |
| Documentation/report (untracked) | 4 files |
| Generated artifact | 1 (arch validation report) |
| Temporary file | 0 |
| Accidental change | 0 |
| Phase 5C leftovers | 0 (5C was fully committed at `3a68c93` + `5224e17`) |
| Unrelated changes | 0 |

**Conclusion:** Every uncommitted change belongs to **Phase 5D cleanup**. There is a coherent, already-implemented cleanup effort sitting uncommitted in the working tree, plus a design doc (`scheduler_cleanup_design_v1.md`) describing the plan it implements — but the design doc says "Next Step: Await design review before implementing cleanup," while the implementation already exists. **The phase gate was not respected: implementation happened before design approval.**

---

## 2. Compare Against Latest Pushed State

- HEAD == origin/main == `5224e17` — fetch confirms zero divergence.
- No commits exist locally that aren't on origin, and vice versa.
- Therefore the entire 16-file uncommitted set is **Phase 5D work in progress** layered on top of the fully-pushed Phase 5C state.
- No Phase 5C leftovers detected: 5C implementation (`3a68c93`) and governance refresh (`5224e17`) are both committed and clean.

---

## 3. Universal Scheduler Architecture Audit (read-only)

### 3.1 Duplicate implementations after the working-tree changes

| Category | Finding | Status |
|----------|---------|--------|
| Duplicate YAML config loaders | 6 standalone loaders removed (validate_dataset, run_extract_all, training_view_engine/generator, acquisition_engine/engine, release/download_release, batch_classify_v2 inline). `scripts/parallel/config.py` is the single remaining loader (`load_parallelism_config()`). | ✅ Resolved in working tree |
| Duplicate worker limit logic | `resolve_worker_count()` now used by all migrated pipelines. | ✅ Resolved |
| Duplicate retry logic | All scheduler paths use `Scheduler` + `TaskRegistry` `max_retries` (2). Downloader `http_util.py`/`cache.py` retry is **protocol-level HTTP resume** (domain-specific, correctly kept). | ✅ No duplication |
| Duplicate planner implementations | `plan_workload`/`file_tasks`/`shard_tasks`/`byte_range_tasks` in `scripts/parallel/planner.py` is the only shared planner. Per-pipeline `plan_*_tasks` wrappers (extraction, ETL, downloader, engine) are thin task-generators over it. | ✅ Single planner |
| Duplicate registry implementations | `scripts/parallel/registry.py` `TaskRegistry` is the only task registry. `adaptive_scheduler.TaskRegistry` is now a forwarding shim. `acquisition_engine/checkpoint.py` `CheckpointManager` is a **different abstraction** (batch/source lifecycle facade — correctly kept). | ✅ Single registry |

### 3.2 Remaining duplicate config loader (NOT touched by cleanup)

| File | Loader | Gap |
|------|--------|-----|
| `run_classify_all_v2.py` (repo root) | Own `load_parallelism_config()` with a hand-rolled YAML fallback parser (lines ~40-75) | **Not migrated** — this is a 5th config loader that duplicates `parallel.config` and was NOT included in the cleanup. It reads `config/parallelism.yaml` directly. |

### 3.3 Hardcoded resources outside config

Remaining `max_workers=` occurrences (non-test, non-`parallel/`):

| File | Line | Purpose | Verdict |
|------|------|---------|---------|
| `scripts/validate_dataset.py` | 370 | Manual `ProcessPoolExecutor` **fallback** | ✅ Intentional crash-safety net (kept per design) |
| `scripts/run_extract_all.py` | 146 | Manual `ProcessPoolExecutor` **fallback** | ✅ Intentional (kept) |
| `scripts/training_view_engine/validator.py` | 315 | Manual **fallback** | ✅ Intentional (kept) |
| `scripts/training_view_engine/generator.py` | 356 | Manual **fallback** | ✅ Intentional (kept) |
| `scripts/acquisition_engine/engine.py` | 815 | `generate_knowledge_pack` curated-file loader | ⚠️ **5D leftover** — design doc targets this for migration to `parallel` file tasks (not yet done) |
| `scripts/intelligence/batch_classify_v2.py` | 199 | Source-level `ProcessPoolExecutor` | ⚠️ Now worker-count from config but still a raw executor, not scheduler |
| `scripts/release/compress_release.py` | 245 | Release compression | ✅ Out of scope (release pipeline, deferred) |
| `scripts/release/upload_huggingface.py` | 332 | ThreadPool uploads w/ backoff | ✅ Out of scope (external API, deferred) |
| `scripts/release/dedup_release.py` | 305 | Release dedup | ✅ Out of scope (deferred) |
| `scripts/release/download_release.py` | 87 | `snapshot_download(max_workers=)` | ✅ CLI/config-driven, HF SDK call |
| `scripts/e2e_pipeline.py` | 97 | `ParallelRunner` | ✅ Test utility |

### 3.4 Registry consistency

Shared schema (from `scripts/parallel/registry.py` + on-disk JSONL):

| Field | Present | Notes |
|-------|---------|-------|
| `task_id` | ✅ | Deterministic per pipeline (`validation:validate_one_file:<file>`, `tv:validate:<start>:<end>`, `extract:<src>:<shard>`, `etl:<sid>`, `download:<sid>:<url_hash>`, `acq:engine:<batch>:<sid>`) |
| `status` | ✅ | States: `pending/running/completed/failed/retry/skipped`; terminal = `completed/skipped` |
| `attempt` | ✅ | Retry counter from append-only file |
| `timestamp` | ✅ | ISO-8601 UTC per record |
| `lease` | ⚠️ | Not a stored field — lease is **derived** from `timestamp` by `reclaim_stale_running(lease_seconds=900)`; no per-record `lease` column. Consistent across registries. |
| `metadata` | ⚠️ | Free-form via `**fields` (e.g. `record_count`, `error`, `worker_id`) — no strict schema enforcement. Consistent across registries. |
| `worker_id` | ⚠️ | Only written on `claim()` (`running` records); absent from completed records. Consistent. |

On-disk check:
- `task_registry_validation.jsonl` — 7 records, keys `[attempt, record_count, status, task_id, timestamp]`
- `task_registry_training_views.jsonl` — 69 records, same key set
- Both registries are internally consistent; schemas match across stages.

**Verdict:** Registry schema is consistent across all six migrated pipelines (validation, extraction, training views, ETL, downloader, acquisition). `lease`/`metadata` are conventions (timestamp-derived lease, free-form fields), not enforced columns — a hardening candidate but not an inconsistency.

---

## 4. Pipeline Migration Status Matrix

| Pipeline | Scheduler | Registry | Resume | Retry | Resource aware | Remaining issues |
|----------|-----------|----------|--------|-------|----------------|------------------|
| Validation | ✅ `parallel` file tasks (fallback kept) | ✅ `task_registry_validation.jsonl` | ✅ skipped-rewind | ✅ max_retries=2 | ✅ `resolve_worker_count("validation")` | None |
| Extraction | ✅ `parallel` shard tasks (fallback kept) | ✅ | ✅ | ✅ | ✅ `resolve_worker_count("extraction")` | None |
| Training Views | ✅ `parallel` load+validate layers (fallback kept) | ✅ `task_registry_training_views.jsonl` | ✅ range re-validate | ✅ | ✅ `resolve_worker_count("training_views")` | `generator._load_view_workers` has a subtle double-fallback (training_views → classification → 1) — see §5.4 |
| ETL | ✅ `parallel` source-level (fallback kept) | ✅ | ✅ report.json reload | ✅ | ✅ | None |
| Downloader | ✅ `parallel` thread pool (I/O-aware) | ✅ | ✅ URL-hash task id | ✅ | ✅ `safe_io_worker_limit()` | None |
| Acquisition | ✅ `parallel` process pool (pure workers) | ✅ + `CheckpointManager` facade | ✅ lease re-claim | ✅ | ✅ | `generate_knowledge_pack` inline loader still raw executor (§3.3) |
| Compression | ❌ Not migrated | — | — | — | — | **Deferred** — release pipeline, own `ProcessPoolExecutor`, CLI workers |
| Release (compress/upload/dedup) | ❌ Not migrated | — | — | — | — | **Deferred** — release-specific, domain retry/backoff |
| Evaluation | ❌ Not migrated | `evaluation_engine/registry.py` (different abstraction) | — | — | — | **Deferred** — not a task-registry consumer |

**6/9 migrated; compression, release, evaluation explicitly deferred** (matches the phase plan).

---

## 5. Verification Results

### 5.1 Architecture validator

```
python3 scripts/validate_architecture.py
→ Checked 155 files, 0 violation(s) found. RESULT: PASS
```

- 4 KNOWN violations (progressive_expansion license-function duplication) — pre-existing, unchanged.
- Running the validator rewrote `metadata/architecture_validation_report.json` (timestamp bump) — expected generated-artifact behavior; that file was already modified before this audit.

### 5.2 Test results (read-only, no dataset/HF/release ops)

| Suite | Dirty tree (current) | Clean HEAD (temp worktree) | Verdict |
|-------|---------------------|---------------------------|---------|
| `test_adaptive_scheduler.py` (16 tests) | **4 passed / 12 failed** | **16 passed** | 🔴 **12 regressions caused by the uncommitted shims** |
| `test_universal_scheduler.py` + extraction + training_views + ETL + acquisition + acquisition_engine (104 tests) | **104 passed** | — | ✅ No regression |
| `test_parallel_stabilization.py` (22 tests) | 20 passed / 2 failed | **same 2 failed** | ⚠️ Pre-existing (also fails at clean HEAD) |
| `test_downloader_v1_6.py` + `test_acquisition_agent.py` | passed | — | ✅ |

**Net new failures: 12 (all in `test_adaptive_scheduler.py`), all caused by the uncommitted Phase 5D shim implementation.**

### 5.3 Confirmed bugs in the uncommitted working tree

1. **Infinite recursion** (`batch_classify_v2._classify_one` ↔ shim `classify_source_shards_adaptive`):
   - `batch_classify_v2._classify_one()` imports `classify_source_shards_adaptive` from the new `batch_classify` shim (line 124-128).
   - The shim's `classify_source_shards_adaptive` forwards back to `batch_classify_v2._classify_one` (line 96-98).
   - Result: `_classify_one → shim → _classify_one → shim → …` — **RecursionError, reproduced** with a nonexistent-source smoke test. Any adaptive classification run (the default!) crashes.

2. **Shim `SourceConfig` is a broken empty stub**:
   - The shim's `try: from batch_classify_v2 import ALL_SOURCES as SourceConfig` fails (circular import during partial v2 load), falling into `SourceConfig = type("SourceConfig", (), {})`.
   - `batch_classify.SourceConfig` is therefore **not** the real v2 dataclass — verified: `shim.SourceConfig is v2.SourceConfig → False`, `__annotations__ → NONE`, instantiation → `TypeError: SourceConfig() takes no arguments`.
   - Any consumer doing `from batch_classify import SourceConfig` (including `tests/test_adaptive_scheduler.py:301`) gets a broken class.

3. **`ALL_SOURCES` missing from the shim** — the shim exports `ALL_SOURCES as SourceConfig` which lands in the stub fallback; no real `ALL_SOURCES` list is re-exported.

4. **12 test regressions** in `test_adaptive_scheduler.py` (16/16 → 4/16) — direct consequence of #1–#3 plus signature drift in the shimmed `Task`/`plan_tasks`/`merge_and_report` wrappers.

### 5.4 Behavior notes (not bugs, but worth approving consciously)

- `run_extract_all.py`: CLI `--shard-workers` still takes precedence; `"auto"` falls back to 4 (previous default was 4). Same behavior.
- `training_view_engine/generator.py` `_load_view_workers()`: `"auto"` → classification resolution → `"auto"` → 1. Previously: `training_views.workers` → classification `stage2_shard_workers` → 1. If `training_views.workers` is set (it is, =8), behavior identical.
- `batch_classify_v2.py`: `resolve_worker_count("classification", ...)` returns `"auto"` (classification has no `workers`/`file_workers`/`shard_workers` key — it uses `stage1_shard_workers`/`stage2_shard_workers`), so it falls back to hardcoded 8 — same as the old `--workers` default. Config values `stage1_shard_workers: 8` / `stage2_shard_workers: 10` are still bypassed by the unified resolver for this stage.
- `engine.py` / `download_release.py`: resolve `acquisition` → 4 (config `file_workers: 4`) — matches previous behavior.

---

## 6. Findings Summary

| # | Severity | Finding |
|---|----------|---------|
| F1 | 🔴 Critical | Phase gate violated: cleanup implementation exists in working tree while `scheduler_cleanup_design_v1.md` is still "Draft — Awaiting Review" |
| F2 | 🔴 Critical | Infinite recursion `_classify_one ↔ classify_source_shards_adaptive` — breaks all adaptive classification (the default path) |
| F3 | 🔴 Critical | Shim `batch_classify.SourceConfig` is an empty stub (`TypeError` on instantiation) — breaks legacy imports |
| F4 | 🔴 Critical | 12 test regressions in `test_adaptive_scheduler.py` (16/16 → 4/16) |
| F5 | 🟠 High | `ALL_SOURCES` not re-exported by the shim |
| F6 | 🟠 High | `run_classify_all_v2.py` still has its own YAML loader — 5th duplicate not covered by cleanup |
| F7 | 🟠 Medium | `generate_knowledge_pack` inline `ProcessPoolExecutor` (engine.py:815) still unmigrated — design doc targets it for 5D but no code |
| F8 | 🟡 Low | `resolve_worker_count("classification")` ignores `stage1/stage2_shard_workers` keys (returns `"auto"`) — classification config bypassed by unified resolver |
| F9 | 🟡 Info | Registry `lease`/`metadata` are conventions (timestamp-derived, free-form), not enforced columns — hardening candidate, not inconsistency |
| F10 | 🟢 Info | 6/9 pipelines migrated; compression/release/evaluation deferred as planned |

---

## 7. Cleanup Scope Recommendation (for approval, not executed)

1. **Decide the design gate**: approve `scheduler_cleanup_design_v1.md` as-is, amend it to match the shim approach actually implemented (deprecation shims instead of file deletion — the design says "Remove" both legacy files, but the implementation keeps them as shims with v2.0 removal), or reject and rework.
2. **Fix the shims before committing**: break the `_classify_one` ↔ shim recursion (shim should delegate to a non-recursive internal, or v2 should stop importing the shim), and re-export the real `SourceConfig`/`ALL_SOURCES` (import order-safe pattern).
3. **Re-run `test_adaptive_scheduler.py`** — must return to 16/16 before commit.
4. **Migrate or explicitly defer** `run_classify_all_v2.py` loader consolidation and `generate_knowledge_pack` file-tasks.
5. **Decide whether to commit** the 4 untracked docs (design, API freeze, deprecation policy, cleanup audit) as a `docs:`/`report:` commit separate from the code fix.
6. Do **not** touch compression/release/evaluation pipelines in this phase.

---

*Prepared as a read-only audit. No files were modified by this audit beyond the architecture validator's expected regeneration of `metadata/architecture_validation_report.json` (already modified before the audit began). No commits were made.*
