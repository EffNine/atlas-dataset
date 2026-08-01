# AcquisitionEngine Migration Design — Universal Scheduler Phase 5C

**Date:** 2026-08-02
**Status:** PROPOSED — awaiting review before implementation
**Audit reference:** `reports/parallelism/acquisition_engine_audit.md`
**Upstream:** Phase 5B (`scripts/downloader/scheduler_tasks.py`) completed;
`metadata/engine_checkpoint.json` retained per 5B constraint.

---

## 1. Objective

Migrate `AcquisitionEngine.execute()`'s sequential batch→source loop to the
Universal Scheduler while:

- preserving **deterministic, byte-identical output** (`curated/v0.1/
  pilot_candidates.jsonl` modulo any `utc_now`-style fields),
- preserving license gates, dedup semantics, lifecycle, provenance fields,
  checkpoint shape, and the sequential fallback,
- adding source-level parallelism, registry resume/retry, and lease-based
  crash recovery.

**Explicitly out of scope:** downloader/adapters/cache (5B, frozen), ETL,
dataset content, releases, HF operations, raw data processing.

---

## 2. Core Design Principle: Pure Workers + Serialized Finalize

The single most important rule from the audit:

> **Workers are pure.** They resolve, gate, and generate records — returning
> data only. Everything that touches shared state (global dedup, lifecycle,
> ver_log, checkpoint, curated write) happens in a serialized finalize step,
> consuming worker results in deterministic manifest order.

This preserves:
- global `seen_norm` first-wins dedup,
- `max_records` global cap,
- lifecycle transition ordering,
- tamper-evident ver_log ordering,
- checkpoint integrity (single writer),
- deterministic output.

---

## 3. Architecture

### 3.1 New module

`scripts/acquisition_engine/scheduler_tasks.py`:

| Function | Role |
|----------|------|
| `engine_task_id(batch_id, source_id)` | `acq:engine:<bid>:<sid>` |
| `plan_engine_tasks(manifest, registry_by_id, max_records, root)` | one Task per (batch, source); manifest order |
| `engine_source_task(task)` | **pure worker**: resolve → license gate → generate records → return `{source_id, batch_id, records, stats}` |
| `run_engine_scheduler(root, manifest, reg_by_id, max_records, ...)` | scheduler run + ordered collection + **finalize**; sequential fallback |

### 3.2 Worker contract (pure)

```python
def engine_source_task(task) -> dict:
    """PURE worker — no shared-file writes, no lifecycle, no checkpoint."""
    extra = task.extra
    sid = task.input
    d = extra["dataset"]          # immutable manifest snapshot
    reg = extra["registry_entry"] # immutable registry snapshot
    # 1. resolve: reg is not None (planned only for resolvable sources)
    # 2. license gate: is_denied_license(d["license"]) -> raise/flag
    # 3. generate: records = _generate_source_records(sid, d, reg, target, max_allowed)
    #    (target = d.target_examples; max_allowed = extra["max_records"] informational)
    # 4. build per-record provenance (source_attribution/lineage) — ON ITS OWN records
    # returns {"source_id", "batch_id", "records": [...], "attempted": len,
    #          "license_blocked": bool}
    # raises RuntimeError on hard failure -> scheduler retry
```

Record generation is relocated **verbatim** from `_generate_source_records`;
provenance/attribution writing is unchanged, applied to the worker's own
records (no race — records are local to the worker until returned).

### 3.3 Finalize (serialized, in `run_engine_scheduler` or `execute`)

Replicates today's inner-loop semantics exactly, in manifest order:

```
for batch in manifest.batches:
    for dataset in batch.datasets:
        result = results_by_id[acq:engine:<bid>:<sid>]   # deterministic lookup
        for rec in result["records"]:                     # same per-record logic
            global cap check → break
            per-record license gate
            seen_norm dedup (SHA-1 normalized messages)
            quality score clamp
            lifecycle.transition(processing)
            verification status
            out_records.append(rec)
            lifecycle.transition(curated)
        checkpoint.update_source_status(sid, "completed", ...)
    checkpoint.set_batch_completed(bid)
# then existing finalize: validate -> curated write -> checksums -> ver_log
```

---

## 4. Task Model

```python
Task(
    task_id="acq:engine:b01:s1",
    source="s1",
    operation="engine_source_pipeline",
    input="s1",
    estimated_size_mb=0.0,
    extra={
        "root": str(root),
        "batch_id": "b01",
        "dataset": {...},        # manifest dataset snapshot
        "registry_entry": {...}, # registry entry snapshot
        "max_records": 100,
    },
)
```

### 4.1 Deterministic ordering guarantee

Results are collected by task_id and **re-ordered to manifest sequence**
(batch order index, then source order index) before finalize. This makes
parallel execution produce the same output as the sequential loop even when
workers finish out of order.

---

## 5. Registry Usage

- Stage `"acquisition"` (shared with 5B downloader registry file
  `task_registry_acquisition.jsonl`; distinct `acq:engine:` vs `download:`
  prefixes).
- States:
  - `pending` → engine pending
  - `running` → resolving/pipelining
  - `completed` → engine completed (per source)
  - `failed` / `skipped` → engine failed / skipped
- **`CheckpointManager` facade (constraint 3 from 5B):**
  - `metadata/engine_checkpoint.json` is **kept** and still written in the
    same shape (session_id, status, completed_batches, per-source statuses).
  - The facade derives completed-batch/source status from the TaskRegistry
    (single source of truth) and syncs the JSON on finalize.
  - `execute()`/`resume()` public signatures unchanged; `resume()` works
    after a scheduler run.

---

## 6. Resume / Retry / Crash Recovery

| Scenario | Behavior |
|----------|----------|
| Resume after completion | completed tasks skipped via registry |
| Resume after crash | stale `running` re-claimed after lease (900 s) — **fixes current gap** |
| Transient worker failure | retry up to `max_retries=2`, backoff |
| Hard failure (license denied, missing registry) | terminal `failed`/`skipped` in registry + checkpoint |
| Re-run finalize | idempotent: same inputs → same records → same dedup/score → same output |

---

## 7. Resource Limits

- Pool: `process` (CPU record generation). Workers are pure → no SQLite fork
  hazard (unlike ETL), so the process pool is safe on macOS too.
- Workers: `safe_worker_limit()` (CPU/RAM aware, 0.8 margin).
- No full-corpus load: one source per worker.
- Disk/bandwidth: N/A (no downloads in engine path; simulated).

---

## 8. Sequential Fallback

- Original loop preserved exactly; any scheduler error → sequential path
  (identical behavior).
- Kill-switch `_SCHEDULER_ENABLED` (same pattern as 5B) for operational
  safety and tests.

---

## 9. Implementation Plan

### Step 1 — Scheduler task module

Add `scripts/acquisition_engine/scheduler_tasks.py` (as above) with
`engine_source_task` extracting the per-source logic verbatim.

### Step 2 — execute() swap

`AcquisitionEngine.execute()`:
- plan tasks from manifest (skip sources already completed in registry),
- run scheduler (workers pure),
- re-order results to manifest sequence,
- **finalize** in the existing order (dedup/score/lifecycle/checkpoint/
  curated/checksums/ver_log) — unchanged code,
- fallback to original loop on error.

`CheckpointManager` gains a facade method to read registry-derived statuses
into the same JSON shape.

### Step 3 — Tests (`tests/test_scheduler_acquisition.py` additions)

- `test_engine_planning`: one task per (batch, source), deterministic ids,
  manifest order.
- `test_engine_output_identity`: scheduler vs sequential → identical record
  count, same record ids, same curated file hash (modulo `utc_now` if any).
- `test_engine_dedup_preserved`: cross-source duplicate rejected identically.
- `test_engine_license_gate`: denied license → failed, not crash.
- `test_engine_max_records_cap`: global cap applied in order.
- `test_engine_resume_equivalence`: CheckpointManager statuses == registry
  statuses after a run; `resume()` skips completed.
- `test_engine_stale_running_reclaimed`: stuck source re-claimed.
- `test_engine_fallback`: kill-switch → sequential identical output.
- `test_engine_provenance_race_free`: two workers' records keep correct
  attribution (no cross-worker mutation).

### Step 4 — Docs + reports

- `docs/parallel/universal_scheduler_usage.md` — "Migration example:
  Acquisition — Engine (Phase 5C)".
- `reports/parallelism/scheduler_phase5c_engine_report.json` +
  `scheduler_phase5c_verification_report.json` (generated from real runs).

### Step 5 — Verification

- Full pytest suite (all phases green).
- `validate_architecture.py` PASS.
- Fresh ad-hoc verification probe (temp-file pattern).
- No production acquisition run.

---

## 10. Rollback

- Additive scheduler path + preserved sequential loop → rollback = revert
  the swap commit; behavior identical.
- No dataset/release/HF mutation at any point.

---

## 11. Acceptance Checklist

- [ ] `curated/v0.1/pilot_candidates.jsonl` identical between scheduler and
      sequential paths (same records, same order, same hashes).
- [ ] `metadata/engine_checkpoint.json` still written, same shape.
- [ ] `execute()`/`resume()` signatures unchanged.
- [ ] License gates, dedup, provenance, lifecycle ordering preserved.
- [ ] Registry resume + stale re-claim + retry working.
- [ ] Sequential fallback identical.
- [ ] Full suite + arch validator + ad-hoc verification green.
