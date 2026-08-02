# Universal Scheduler Final Audit — Phase 5E

**Date:** 2026-08-02
**Mode:** Read-only audit (no code, no dataset, no release, no HF changes)
**Baseline:** HEAD == `f147a2e` == origin/main (clean tree)
**Audit target:** `scripts/parallel/` as the canonical execution layer; readiness for Phase 6 (Compression → Release → Evaluation)

---

## 1. Executive Summary

Phase 5E confirms the Universal Scheduler (`scripts/parallel/`) is the
**canonical, consolidated execution layer** for Atlas. Six of nine pipelines
are fully migrated (Validation, Extraction, Training Views, ETL, Downloader,
Acquisition Engine) with behavior-preserving fallbacks, and the Phase 5D
cleanup removed the last duplicate YAML loader and shim stubs.

**Ready to migrate next:** Compression (Phase 6) — its task unit (per-shard
compression with per-category routing) maps cleanly onto the scheduler's
file-task model. **No blocking issues.** Two design decisions must be
confirmed before implementation (registry stage key; skip-existing
semantics), but neither blocks design work.

**Deferred with justification:** Release pipeline tools (dedup, HF upload)
have domain-specific retry/resume (network backoff, remote-size resume) that
map poorly onto the task registry; they need a lighter-touch migration or a
documented exemption. Evaluation is fully sequential by design (model-free
heuristics, deterministic, read-only) — no executor exists to migrate.

**Gaps found (non-blocking):**
1. `_backpressure()` in `scheduler.py` is **dead code** — defined but never
   invoked; the RAM-headroom pause is aspirational, not active. Bounded
   submission still prevents overload via worker caps.
2. `disk_free()` is reported by the monitor but **never gates submission**
   — disk-pressure backpressure is not implemented (acceptable: workloads
   are RAM/CPU bound, not disk bound).
3. `resolve_worker_count("classification")` returns `"auto"` because the
   classification stage uses `stage1/stage2_shard_workers` keys the unified
   resolver ignores (documented 5D gap, pre-existing behavior preserved).
4. `generate_knowledge_pack` retains an inline `ProcessPoolExecutor`
   (intentionally — a registry "completed" marker would wrongly skip
   re-reading changed curated files on fresh pack builds; rationale
   documented in `engine.py:814-821`).

---

## 2. Migration Status

| Phase | Pipeline | Status | Commit | Registry file |
|-------|----------|--------|--------|---------------|
| P1 | Validation | ✅ Migrated | `2b86c11` | `task_registry_validation.jsonl` |
| P2 | Extraction | ✅ Migrated | `66ca4b1` | `task_registry_extraction.jsonl` |
| P3 | Training Views | ✅ Migrated | `048a2e4` | `task_registry_training_views.jsonl` |
| P4 | ETL | ✅ Migrated | `51750e6` | `task_registry_etl.jsonl` |
| P5B | Downloader | ✅ Migrated | `4301b74` | `task_registry_acquisition.jsonl` |
| P5C | Acquisition Engine | ✅ Migrated | `3a68c93` | `task_registry_acquisition.jsonl` |
| P5D | Cleanup (shims, config consolidation) | ✅ Done | `5746d06`–`f147a2e` | — |
| P5E | **Final audit** | ✅ This report | `f147a2e` | — |
| P6 | **Compression** | ⏳ Not started | — | — |
| P7 | **Release (dedup/upload)** | ⏳ Not started | — | — |
| P8 | **Evaluation** | ⏳ Not started | — | — |

All six migrated pipelines ship **both** paths: scheduler primary, original
sequential/ProcessPool fallback on any scheduler import/execution error —
output byte-identical (per-phase determinism tests passed).

---

## 3. Pipeline Matrix

Legend — executor: `sched=proc` (Scheduler process pool), `sched=thread`
(Scheduler thread pool), `PPE` (manual ProcessPoolExecutor), `TPE` (manual
ThreadPoolExecutor), `seq` (sequential), `n/a` (no parallelism).

| # | Pipeline | Current executor | Scheduler integrated? | Task model | Registry | Retry | Resume | Resource-aware | Deterministic output | Remaining gaps |
|---|----------|------------------|----------------------|------------|----------|-------|--------|----------------|----------------------|----------------|
| 1 | Validation | `sched=proc` + PPE fallback | ✅ | file | ✅ | ✅ 2x | ✅ | ✅ safe_worker_limit | ✅ sorted by task_id | none material |
| 2 | Extraction | `sched=proc` + PPE fallback | ✅ | shard (`extract:{src}:{shard}`) | ✅ | ✅ 2x | ✅ | ✅ | ✅ | none material |
| 3 | Training Views | `sched=proc` + PPE fallback | ✅ | file + record-range (`tv:validate:{start}:{end}`) | ✅ | ✅ 2x | ✅ inline re-validate | ✅ | ✅ range-ordered | none material |
| 4 | ETL | `sched=proc` + seq fallback | ✅ | source (`etl:{sid}`) | ✅ | ✅ 2x | ✅ reload report.json | ✅ | ✅ sorted by source_id | none material |
| 5 | Downloader | `sched=thread` + seq fallback | ✅ | source (`download:{sid}:{url_hash}`) | ✅ | ✅ 2x | ✅ | ✅ I/O-aware `safe_io_worker_limit` | ✅ | none material |
| 6 | Acquisition Engine | `sched=proc` + seq fallback | ✅ | source (`acq:engine:{bid}:{sid}`) | ✅ | ✅ 2x | ✅ + lease re-claim | ✅ | ✅ manifest-order finalize (byte-identical) | `generate_knowledge_pack` loader intentionally unscheduled |
| 7 | Compression | `PPE` (manual) | ❌ | file (whole shard) | ❌ | ❌ | ⚠️ `--skip-existing` (output-exists check) | ❌ fixed `--workers` CLI | ✅ sorted by input name | **Phase 6 target**; no registry/retry/adaptive workers |
| 8 | Release (dedup/upload/download) | `PPE`/`TPE` manual + HF-library managed | ❌ | category (dedup), section (upload) | ❌ | ⚠️ upload: network backoff only | ⚠️ upload: remote-size skip | ⚠️ download uses unified config; dedup/upload fixed CLI | ⚠️ partial | domain-specific retry/resume; needs exemption or light migration |
| 9 | Evaluation | `seq` | ❌ | n/a (no parallelism) | BenchmarkRegistry (different domain) | ❌ | ❌ | ❌ | ✅ deterministic + reproducibility hash | sequential by design; no executor exists to migrate |
| 10 | Classification | `PPE` manual (static+adaptive) + `TPE` source orchestration | ⚠️ partial | byte-range tasks via `parallel.planner`; registry + monitor adopted | ✅ (adopted) | ✅ (registry attempts) | ✅ | ⚠️ config keys ignored → `"auto"` | ✅ sorted merge | drives `ProcessPoolExecutor` manually, not `Scheduler.run()`; stage1/stage2 key gap |

**Classification detail (partial adoption):** `batch_classify_v2.py` already
uses `parallel.planner.byte_range_tasks`, `parallel.registry.TaskRegistry`,
and `parallel.monitor.write_legacy_scheduler_report`, but the adaptive path
manages its own `ProcessPoolExecutor` + retry loop instead of
`Scheduler.run()`. It is functionally equivalent but bypasses the scheduler's
bounded-submission and RAM-backpressure machinery. Recommend a follow-up to
route it through `Scheduler.run()` (Phase 6 or cleanup).

---

## 4. Duplicate Infrastructure Findings

### Config loaders
| Location | Verdict | Notes |
|----------|---------|-------|
| `scripts/parallel/config.py` | **KEEP (canonical)** | only `yaml.safe_load` in the codebase; merges defaults + env + hardware profiles |
| `run_classify_all_v2.py` | ✅ MIGRATED (5D) | now calls `load_parallelism_config` |
| `batch_classify_v2.py`, `download_release.py`, `run_extract_all.py`, `engine.py`, TV generator | ✅ MIGRATED | all use `parallel.config` |
| any other `import yaml` | ✅ NONE | grep-verified: only `parallel/config.py:80` |

### Worker-limit logic
| Location | Verdict | Notes |
|----------|---------|-------|
| `scripts/parallel/resource.py` | **KEEP (canonical)** | `safe_worker_limit` (CPU/RAM), `safe_io_worker_limit` (I/O cap 8), `detect_cpu/ram/disk/gpu` |
| `parallel/config.resolve_worker_count` | **KEEP (canonical)** | precedence CLI > env > config > auto |
| `compress_release.py --workers`, `dedup_release.py --jobs`, `upload_huggingface.py --workers` | **MIGRATE (Phase 6/7)** | raw CLI ints, no RAM/cpu caps, not from unified config (CLI default exempt under ADR-013, but no safety caps) |
| `engine.py generate_knowledge_pack` | ✅ MIGRATED (5D) | uses `resolve_worker_count("acquisition")` |

### Retry systems
| Location | Verdict | Notes |
|----------|---------|-------|
| `parallel/scheduler.py` + `parallel/registry.py` | **KEEP (canonical)** | max_retries, `retry` transition, attempts from append-only file |
| `downloader/http_util.py` + `cache.py` | **KEEP (domain)** | HTTP exponential-backoff + Range resume — network layer, not task layer |
| `upload_huggingface.py _upload_section_with_retry` | **KEEP (domain)** | network backoff for HF API; scheduler registry would be wrong abstraction |
| `automation/failure_recovery.py` RetryManager | **KEEP (domain)** | pipeline-level agent retry/resume, distinct from task-level registry |
| `batch_classify_v2.py` manual retry loop | **MIGRATE (follow-up)** | should fold into `Scheduler.run()` retry semantics |

### Resume / checkpoint systems
| Location | Verdict | Notes |
|----------|---------|-------|
| `parallel/registry.py` TaskRegistry | **KEEP (canonical)** | append-only JSONL, lease re-claim, completed-skip |
| `acquisition_engine/checkpoint.py` CheckpointManager | **KEEP (facade)** | writes legacy `engine_checkpoint.json` shape; completed-status derived from registry (5C constraint) |
| `upload_huggingface.py _resume_skip` | **KEEP (domain)** | remote-size comparison against HF — no task registry analog |
| `compress_release.py --skip-existing` | **MIGRATE (Phase 6)** | replace with registry-based resume + keep `--skip-existing` as semantic equivalent |
| `download_release.py` | **KEEP** | HF `snapshot_download` owns its resume |

### Task planning
| Location | Verdict | Notes |
|----------|---------|-------|
| `parallel/planner.py` | **KEEP (canonical)** | file / shard / byte-range planners; deterministic task_ids |
| `batch_classify_v2.py split_single_shard` | **KEEP (special)** | classification-specific single-shard splitting (filename-named chunks); complements planner |

### Registry implementations
| Location | Verdict | Notes |
|----------|---------|-------|
| `parallel/registry.py` TaskRegistry | **KEEP (canonical)** | 6 pipelines use it; schema `{task_id,status,attempt,timestamp}+free-form` consistent |
| `evaluation_engine/registry.py` BenchmarkRegistry | **KEEP (different domain)** | benchmark *definitions*, not task state — do not conflate |
| `automation/failure_recovery.py` RetryManager | **KEEP (different domain)** | pipeline retry history |

---

## 5. Remaining Risks

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| R1 | `_backpressure()` dead code — RAM-headroom pause never runs | Low (bounded submission still caps in-flight workers) | Wire `_backpressure()` into `Scheduler.run()` submit loop (cheap, Phase 6 cleanup) |
| R2 | `disk_free()` not used for admission control | Low (workloads RAM/CPU-bound) | Document as intentional; add disk gate only if a disk-bound stage emerges (compression writes large outputs — re-evaluate during Phase 6) |
| R3 | Classification worker resolution returns `"auto"` (stage1/stage2 keys ignored) | Medium (classification relies on `auto` → scheduler picks CPU-based limit; historically stage2=10 was intended) | Add `stage1_shard_workers`/`stage2_shard_workers` to `resolve_worker_count` key candidates; verify no behavior change |
| R4 | Compression/release pipelines have zero registry/retry/adaptive-worker coverage | Medium (Phase 6/7 scope) | Migrate compression first; document release domain retry as exempt |
| R5 | `generate_knowledge_pack` inline executor bypasses scheduler | Low (intentional, documented) | None — keep; re-verify rationale at v2.0 |
| R6 | `test_parallel_stabilization.py` has 2 pre-existing failures at clean HEAD | Low (unrelated to scheduler; verified pre-existing in 5D) | Track separately; do not block migration |
| R7 | Evaluation in-memory load (`eval_dataset.py load()`) reads entire JSONL into RAM | Low-Medium (9.3M-record v1.2 ≈ multi-GB; only when run on full dataset) | Consider streaming/chunked eval if full-dataset runs become routine |

---

## 6. Recommended Phase 6-8 Order

1. **Phase 6 — Compression** (`compress_release.py`)
   - Task unit: file (one shard per task), worker `compress_task` (module-level wrapper around `_route_shard`).
   - Registry stage key: `compression` → `task_registry_compression.jsonl`.
   - Keep `--skip-existing` semantics as registry-resume equivalent (or keep flag, map to `is_completed`).
   - Adaptive workers via `resolve_worker_count("release")`/`safe_worker_limit` (shard streaming is O(1) RAM per worker — CPU-bound, process pool).
   - Determinism: outputs already sorted by input name; verify hash-identical to current run.
   - **Decision needed before implementation:** registry stage key naming (`compression` vs `release`) and whether `--skip-existing` remains a separate flag or maps to registry state.

2. **Phase 7 — Release tools** (`dedup_release.py`, `upload_huggingface.py`)
   - Recommend **exemption-by-design doc** for network-domain retry/resume (upload) instead of forcing TaskRegistry.
   - Dedup is embarrassingly parallel per category: candidate for scheduler (file/category task) with registry resume.
   - Download already uses unified config — no work beyond documenting.

3. **Phase 8 — Evaluation**
   - No executor exists; nothing to migrate for correctness.
   - Optional: add scheduler only if parallel metric evaluation is needed; otherwise document as intentionally sequential.
   - Add classification `Scheduler.run()` follow-up (R3/R4) here or in a Phase 6 cleanup slice.

4. **Phase 6 cleanup slice (non-blocking, can run with 6/7/8):**
   - Wire `_backpressure()` into `Scheduler.run()`.
   - Extend `resolve_worker_count` key candidates with classification keys.
   - Route `batch_classify_v2` adaptive path through `Scheduler.run()`.

---

## 7. Blocking Issues Before Compression Migration

**None.**

Compression is the cleanest possible next migration:
- worker already module-level (`_route_shard`) — picklable ✓
- task unit is a whole shard file — `file_tasks()` fits directly ✓
- output merge is already sorted by input name — deterministic ✓
- streaming O(1) memory per worker ✓
- existing `--workers` CLI → `Scheduler(workers=None)` adaptive ✓

The two design decisions in §6.1 (registry stage key; `--skip-existing`
mapping) are **design-time choices, not blockers** — they should be decided
in the Phase 6 design doc before implementation, per the standard
audit → design → implement phase gate.

---

## 8. Verification

- `python3 scripts/validate_architecture.py` → **RESULT: PASS** (155 files, 0 violations; governance report restored after check)
- JSON schema validation: see probe result (temp, cleaned)
- Markdown completeness check: see probe result (temp, cleaned)
- Tree cleanliness after audit: clean (`git status --porcelain` empty after restoring validator-touched governance report)

---

*Generated by Hermes (read-only audit, Phase 5E). No files outside `reports/parallelism/` modified.*
