# ADR-015: Universal Adaptive Scheduler

**Status:** Proposed (awaiting approval)
**Date:** 2026-08-01
**Phase:** 4C.5 — Parallel Processing v2 / Universal Scheduler
**Design reference:** `docs/architecture/universal_adaptive_scheduler_v1.md`
**Audit reference:** `reports/parallelism/atlas_parallelism_audit.md`
**Supersedes (in part):** ADR-013 (extends its unified-config decision to a
shared scheduling subsystem)

---

## Context

Atlas has 20 pipelines spanning intelligence, acquisition, ETL, extraction,
validation, training views, evaluation, and release. The parallelism audit
(`reports/parallelism/atlas_parallelism_audit.md`) found:

- Five independent parsers of `config/parallelism.yaml`.
- Four bespoke resume mechanisms (TaskRegistry, downloader cache, upload
  size-match, compress `--skip-existing`).
- Two parallel curated-file loaders with different config keys.
- Two split-logic implementations (`split_single_shard`, `plan_tasks`).
- Zero resource awareness (no pipeline monitors RAM/CPU/disk/GPU).
- Worker counts chosen by each script (hardcoded, CLI, or config) — never by
  the hardware actually available.

Adaptive Scheduler v2 (proven in v1.2 classification) already provides:
task planning, TaskRegistry, byte-aware splitting, deterministic merge. The
decision: generalize that proven pattern into a shared subsystem instead of
continuing per-pipeline implementations.

## Decision

1. **Create `scripts/parallel/` as the shared scheduling subsystem** with six
   modules: `config.py` (single YAML loader + hardware profiles + env
   overrides), `resource.py` (CPU/RAM/disk detection + GPU placeholder +
   `safe_worker_limit()`), `planner.py` (workload → tasks: file/shard/byte/
   record-range), `registry.py` (universal TaskRegistry with
   pending/running/completed/failed/retry states), `scheduler.py` (adaptive
   worker management, backpressure, failure recovery, deterministic merge),
   `monitor.py` (runtime metrics + scheduler reports).

2. **One task model** across all pipelines:
   `{task_id, source, operation, input, estimated_size_mb, priority, status,
   offset_start, offset_end}` with deterministic task_ids for idempotent
   resume.

3. **Scheduler decides worker counts** from hardware (`safe_worker_limit()`)
   with hard safety rules: RAM cap (0.8 utilization), no permanent CPU
   saturation, disk headroom ≥ 10 GB, GPU never assumed. Pipelines stop
   choosing worker counts; `auto` becomes the default config value.

4. **Universal resume** via TaskRegistry: completed-skip, lease-based
   re-claim after crash, retry ≤ `max_retries`, rename-to-final on partial
   output safety.

5. **Migration order:** P0 = validation, extraction, training views;
   P1 = compression, classification cleanup, ETL; P2 = acquisition, release
   publishing; P3 = evaluation.

6. **Design-only now:** no code changes, no dataset/release/HF operations
   until approval.

## Consequences

**Positive:**
- Removes all five duplicate config parsers and four resume mechanisms.
- Every pipeline gets resume + resource safety with the same code.
- Multi-machine readiness built in (worker_id in registry, content-addressed
  tasks, shared-store registry path documented).
- Predictable performance: scheduler reports per stage.

**Negative / Trade-offs:**
- Migration cost spread across 20 pipelines (phased, P0–P3).
- `auto` worker counts mean behavior depends on runtime detection; hardware
  profile overrides required for deterministic tuning.
- GPU placeholder only — real GPU scheduling deferred until evaluation
  engine gains a full execution mode.

**Risk mitigation:**
- Phase-gated migration; each pipeline keeps its existing behavior until
  migrated (backward compatible).
- Existing Adaptive Scheduler v2 remains operational until classification
  cleanup (P1) ports it to shared modules.
- Architecture validation (Check 7) extended to forbid new hardcoded worker
  counts in migrated pipelines.

## Status

Proposed — awaiting approval. No implementation started.
