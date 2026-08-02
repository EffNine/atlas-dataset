# Universal Scheduler Cleanup & Consolidation — Design Document

**Phase:** 5D — Universal Scheduler Cleanup & Consolidation  
**Date:** 2026-08-02  
**Status:** Reviewed — Implementation Approved (shim policy)  
**Author:** Agnes (Sapiens AI) — reconciled by Hermes (Phase 5D implementation)

---

## 1. Objective

Remove remaining duplicate parallel implementations and consolidate all dataset pipeline execution under the Universal Scheduler (`scripts/parallel/`). This phase is **NOT** about adding new features — it is about cleanup, consistency, documentation, and removing technical debt.

**Constraints:**
- Do NOT change dataset contents or releases
- Do NOT modify Hugging Face manifests
- Do NOT rerun classification or change existing outputs
- Must preserve SHA256 outputs, deterministic ordering, and existing tests
- Must preserve fallback execution paths

---

## 2. Migration Decisions

### 2.1 Legacy Modules: Compatibility Shims (NOT deletion)

**Decision (approved):** Legacy modules are converted to **backward-compatibility shims**, not removed.

**Reason:** Atlas has many existing pipeline references. Legacy modules must remain temporarily as thin compatibility layers so existing import paths keep working until the removal target (Atlas v2.0).

**Shim policy (hard rules):**
- Legacy modules **may** re-export canonical implementations (from `batch_classify_v2.py` / `scripts/parallel/`)
- Legacy modules **may** expose old import paths (function names, class names, signatures)
- Legacy modules **must** contain **NO duplicated business logic** — no independent scheduler, config loader, registry, retry, or worker-pool implementation
- Legacy modules **must** emit `DeprecationWarning` on use
- Canonical modules (`batch_classify_v2.py`, `scripts/parallel/`) are the **only** home of real logic

**Migration strategy:**
1. Move/keep real implementations in canonical homes (`batch_classify_v2.py`, `scripts/parallel/`)
2. Convert legacy modules to thin shims that forward to canonical code with deprecation warnings
3. Verify old import paths still work (identity of exported classes, callable signatures)
4. Do NOT remove shims until the removal criteria are met

**Future removal criteria (for Atlas v2.0):**
- [ ] No remaining imports of `batch_classify` / `adaptive_scheduler` anywhere in `scripts/` or `tests/`
- [ ] All pipelines reference `batch_classify_v2.py` / `scripts/parallel/` directly
- [ ] Tests pass without deprecation warnings from these modules
- [ ] Documentation updated to reference new paths only
- [ ] Changelog entry documenting the removal

| File | Action | Rationale |
|------|--------|-----------|
| `scripts/intelligence/batch_classify.py` | **Convert to shim** | Superseded by `batch_classify_v2.py` + universal scheduler. Kept as a thin re-export layer (SourceConfig, classify_source_shards, merge_and_report, …) so existing imports keep working. Contains NO business logic. |
| `scripts/intelligence/adaptive_scheduler.py` | **Convert to shim** | Superseded by `scripts/parallel/`. Kept as a thin forwarding layer (Task, TaskRegistry, plan_tasks, load_scheduler_config, write_scheduler_report) with NO independent scheduler/config/registry implementation. |

**Risk:** Low. Both files forward to canonical implementations; behavior is preserved for legacy callers and tests.

### 2.2 Files to Migrate (Worker Count Resolution)

| File | Current Pattern | New Pattern |
|------|----------------|-------------|
| `scripts/intelligence/batch_classify_v2.py` | Hardcoded `args.workers` (line 191) | Use `resolve_worker_count("classification", ...)` from `parallel.config` |
| `scripts/acquisition_engine/engine.py` | `_load_file_workers()` reads YAML directly (lines 775-784) | Use `resolve_worker_count("acquisition", ...)` from `parallel.config` |

**Risk:** Low. Same configuration source, different import path.

### 2.3 Files to Update (YAML Loader Consolidation)

Replace standalone YAML loaders with `parallel.config.load_parallelism_config()`:

| File | Current Lines | New Import |
|------|---------------|------------|
| `scripts/validate_dataset.py` | 211-219 (`load_parallelism_config()`) | `from parallel.config import load_parallelism_config` |
| `scripts/run_extract_all.py` | 38-40 (inline yaml load) | `from parallel.config import load_parallelism_config` |
| `scripts/training_view_engine/generator.py` | 298-300 (inline yaml load) | `from parallel.config import load_parallelism_config` |
| `scripts/release/download_release.py` | 73-78 (inline yaml load) | `from parallel.config import load_parallelism_config` |

**Risk:** Low. All read the same YAML file with the same structure. The `parallel.config` module has the same fallback behavior (returns empty dict on failure).

### 2.4 Files to Keep (Correct as-Is)

| File | Reason |
|------|--------|
| `scripts/parallel/runner.py` | Test-only utility for e2e_pipeline. Simple, no duplicate logic. |
| `scripts/release/compress_release.py` | Release pipeline with different constraints (compression, not transformation). |
| `scripts/release/upload_huggingface.py` | External API with domain-specific retry/backoff. |
| `scripts/release/dedup_release.py` | Release-specific deduplication. |
| `scripts/downloader/http_util.py` | Protocol-level HTTP Range resume, not a worker pool. |
| `scripts/downloader/cache.py` | Domain-specific caching layer with checksum verification. |
| `scripts/acquisition_engine/checkpoint.py` | Different abstraction (batch/source lifecycle, not task-level). |
| `scripts/automation/failure_recovery.py` | Different abstraction (pipeline-level failure recovery). |
| `scripts/intelligence/difficulty_analyzer.py` | CPU-bound analysis, not a parallel pipeline stage. |

### 2.5 Fallback Paths to Preserve

The following fallback `ProcessPoolExecutor` paths are **intentional crash-safety nets** and must be preserved:

| File | Fallback Lines | Purpose |
|------|---------------|---------|
| `scripts/validate_dataset.py` | 374-376 | Scheduler crash recovery gap |
| `scripts/run_extract_all.py` | 148-153 | Scheduler crash recovery gap |
| `scripts/training_view_engine/validator.py` | 309-315 | Scheduler crash recovery gap |
| `scripts/training_view_engine/generator.py` | 363-364 | Scheduler crash recovery gap |

---

## 3. What Gets Removed (Business Logic Only)

### 3.1 Legacy Business Logic Replaced by Shims

1. `scripts/intelligence/batch_classify.py` — business logic removed; module becomes a thin re-export shim over `batch_classify_v2.py` (kept as file for import compatibility)
2. `scripts/intelligence/adaptive_scheduler.py` — business logic removed; module becomes a thin forwarding shim over `scripts/parallel/` (kept as file for import compatibility)
3. Standalone YAML loaders in 5 pipeline files (validate_dataset, run_extract_all, training_view_engine/generator, acquisition_engine/engine, release/download_release) — replaced by `parallel.config`
4. `run_classify_all_v2.py` hand-rolled YAML loader + fallback parser — replaced by `parallel.config`

### 3.2 Duplicate Imports

- `from yaml import safe_load` or inline `import yaml` blocks that duplicate `parallel.config`

### 3.3 Local TaskRegistry Implementations

- `adaptive_scheduler.py`'s legacy `TaskRegistry` class — replaced by forwarding to `parallel.registry.TaskRegistry` (shim wrapper exposes the same methods, no state machine logic)

---

## 4. What Remains

### 4.1 Universal Scheduler (Unchanged)

```
scripts/parallel/
├── config.py       — load_parallelism_config(), resolve_worker_count()
├── resource.py     — detect_cpu(), detect_ram(), safe_worker_limit()
├── models.py       — Task, TaskResult, WorkerCapacity
├── planner.py      — file_tasks(), shard_tasks(), byte_range_tasks()
├── registry.py     — TaskRegistry (append-only JSONL checkpoint)
├── scheduler.py    — Scheduler (adaptive workers, backpressure, retry)
├── monitor.py      — Monitor (runtime metrics)
└── runner.py       — ParallelRunner (test utility)
```

### 4.2 Already-Migrated Pipelines (No Changes)

| Pipeline | Entry Point | Status |
|----------|-------------|--------|
| Validation | `scripts/validate_dataset.py` | ✅ Primary path: scheduler |
| Extraction | `scripts/run_extract_all.py` | ✅ Primary path: scheduler |
| Training Views | `scripts/training_view_engine/*.py` | ✅ Primary path: scheduler |
| ETL | `scripts/etl/pipeline.py` | ✅ Primary path: scheduler |
| Downloader | `scripts/downloader/scheduler_tasks.py` | ✅ Primary path: scheduler |
| Acquisition | `scripts/acquisition_engine/scheduler_tasks.py` | ✅ Primary path: scheduler (PURE WORKER) |

### 4.3 Release Pipeline (Unchanged)

Release pipelines (`compress_release.py`, `upload_huggingface.py`, `dedup_release.py`) use their own worker management and are outside the scope of this cleanup.

### 4.4 `generate_knowledge_pack` curated loader (engine.py) — intentionally retained

**Decision:** NOT migrated to the Universal Scheduler. Documented rationale (inline in `engine.py`):

- It is a **one-shot in-memory read** of curated JSONL with no resume/retry/checkpoint semantics. A `TaskRegistry` entry marking a file "completed" would skip re-reading that file on a later run even if curated changed — wrong for a fresh knowledge-pack build.
- The worker count is already resolved through the unified config (`parallel.config.resolve_worker_count("acquisition", ...)` via `_load_file_workers()`).
- The worker was converted from an inline closure to a module-level `_load_curated_file()` so it pickles under macOS spawn.

**Future migration (v2.0+):** only if knowledge-pack generation gains resumable/incremental semantics; otherwise keep the simple read.

---

## 5. Backward Compatibility Strategy

### 5.1 Import Compatibility

All changes maintain existing import paths. No external API contracts change:
- `from parallel.scheduler import Scheduler` — unchanged
- `from parallel.config import load_parallelism_config` — unchanged
- `from parallel.registry import TaskRegistry` — unchanged

### 5.2 Environment Variables

The `ATLAS_WORKERS_*` and `ATLAS_PROFILE` environment variable overrides continue to work. No new env vars are introduced.

### 5.3 CLI Arguments

- `--workers` / `--jobs` CLI args in release scripts are unchanged
- `batch_classify_v2.py --workers` continues to work (but now falls back to config if not specified)

### 5.4 Output Format

- SHA256 outputs are preserved
- Deterministic ordering is preserved (results sorted by task_id)
- JSONL registry format is unchanged
- Report formats are unchanged

---

## 6. Rollback Plan

If cleanup introduces issues:

1. **Immediate rollback:** Restore the pre-shim business logic from git:
   ```bash
   git checkout HEAD -- scripts/intelligence/batch_classify.py scripts/intelligence/adaptive_scheduler.py
   ```
2. **Partial rollback:** Revert specific file changes:
   ```bash
   git checkout HEAD -- scripts/validate_dataset.py scripts/run_extract_all.py
   ```
3. **Full rollback:** Revert the entire cleanup commit:
   ```bash
   git revert <cleanup-commit-sha>
   ```

No data changes are made, so no data rollback is needed. Because the shim policy keeps the legacy files in place (no deletion), rollback is a simple `git checkout` — no file restoration from history is required.

---

## 7. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Shim recursion (shim ↔ canonical mutual import) | High | Canonical `batch_classify_v2._classify_one` must NOT import from `batch_classify` shim — it calls its own module-level functions. Verify both import orders in fresh processes. |
| Shim exports wrong class identity (`SourceConfig` stub vs real) | High | Re-export canonical class directly (`from batch_classify_v2 import SourceConfig`); verify `shim.SourceConfig is v2.SourceConfig` and instantiation works in both import orders |
| YAML loader replacement changes behavior | Low | `parallel.config.load_parallelism_config()` has identical fallback behavior |
| `resolve_worker_count` returns different value than hardcoded | Medium | Test with current config values; document any differences |
| Fallback path deletion causes regression | Low | Fallback paths are explicitly marked for retention |

---

## 8. Implementation Steps

### Step 1: Verify No Active Callers (Pre-Cleanup)
```bash
grep -r "from.*batch_classify\b\|from.*adaptive_scheduler" scripts/ --include="*.py"
```

### Step 2: Fix Canonical Classification Implementation (`batch_classify_v2.py`)
- Port real `classify_source_shards` / `classify_source_shards_adaptive` / `merge_and_report` + helpers into v2 (canonical home)
- `_classify_one` calls v2-local functions only (NO import from the `batch_classify` shim)

### Step 3: Convert Legacy Files to Shims (NOT deletion)
```bash
# batch_classify.py → thin re-export shim over batch_classify_v2.py
# adaptive_scheduler.py → thin forwarding shim over scripts/parallel/
# NO rm — files stay as compatibility layers until Atlas v2.0
```

### Step 4: Update YAML Loaders
Replace standalone loaders with `from parallel.config import load_parallelism_config` in:
- `scripts/validate_dataset.py`
- `scripts/run_extract_all.py`
- `scripts/training_view_engine/generator.py`
- `scripts/release/download_release.py`
- `scripts/acquisition_engine/engine.py`
- `run_classify_all_v2.py` (also drops the hand-rolled fallback parser)

### Step 5: Update Worker Count Resolution
- `scripts/intelligence/batch_classify_v2.py` — use `resolve_worker_count("classification", ...)`
- `scripts/acquisition_engine/engine.py` — use `resolve_worker_count("acquisition", ...)`

### Step 6: Verify
- Run full test suite (expect `test_adaptive_scheduler.py` 16/16; 2 pre-existing `test_parallel_stabilization` failures; zstandard failures unrelated)
- Run architecture validator
- Verify deterministic outputs match

---

## 9. Acceptance Criteria

1. ✅ No standalone `ProcessPoolExecutor` / `ThreadPoolExecutor` in migrated pipelines (only fallbacks)
2. ✅ No duplicate YAML config loaders (including `run_classify_all_v2.py`)
3. ✅ No duplicate TaskRegistry implementations (shim forwards to `parallel.registry`)
4. ✅ All worker counts resolved through `parallel.config.resolve_worker_count()`
5. ✅ `test_adaptive_scheduler.py` 16/16 (regressions fixed)
6. ✅ Architecture validator passes
7. ✅ No new hardcoded worker counts
8. ✅ Deterministic outputs preserved
9. ✅ Fallback execution paths intact
10. ✅ Legacy modules are pure shims: re-export canonical symbols, emit `DeprecationWarning`, contain no business logic (verified by grep for executor/registry/config code in shims)

---

## 10. Sign-Off

| Role | Name | Status |
|------|------|--------|
| Design Author | Agnes (Sapiens AI) | Draft |
| Review | Hermes (Phase 5D pre-audit) | Reviewed |
| Approval | Afnan (EffNine) | Approved (shim policy) |

---

**Next Step:** Implementation complete per Steps 2–6; verification reports in `reports/parallelism/phase5d_cleanup_report.{md,json}`.