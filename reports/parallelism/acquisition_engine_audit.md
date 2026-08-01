# AcquisitionEngine — Read-Only Audit (Phase 5C)

**Date:** 2026-08-02
**Status:** READ-ONLY — no code changed, no dataset/release/HF operations
**Scope:** `scripts/acquisition_engine/engine.py` (+ checkpoint/lifecycle/integrity)
**Upstream:** Phase 5A audit (`reports/parallelism/atlas_acquisition_audit.md`),
Phase 5B downloader migration (`4301b74`) — downloader/cache/adapters NOT touched here.

---

## 1. Current Execution Flow

### 1.1 Entry points

| Method | Purpose | Side effects |
|--------|---------|--------------|
| `AcquisitionEngine.dry_run()` | Plan-only pass | writes `engine_checkpoint.json` (dry-run), nothing else |
| `AcquisitionEngine.execute(max_records=100, resume=False)` | Real ingestion | checkpoint, lifecycle, curated output, checksums, ver_log, version snapshot |
| `AcquisitionEngine.resume(max_records=100)` | Resume from checkpoint | delegates to `execute(resume=True)` or `dry_run` |

### 1.2 `execute()` step-by-step (lines 424–667)

```
0. install_network_block() if configured
1. load manifest (metadata/acquisition_manifest_v0.1.json)
2. mode check ("execute" only)
3. init/resume CheckpointManager (metadata/engine_checkpoint.json)
4. checkpoint.status = "running"
5. out_records = []; seen_norm = {}          # GLOBAL dedup set (cross-source)
6. for batch in manifest.batches:            # SEQUENTIAL
     if batch completed in checkpoint: skip
     checkpoint.set_current_batch(bid)
     for dataset in batch.datasets:          # SEQUENTIAL
       if source completed in checkpoint: skip
       checkpoint.update_source_status(sid, "resolving")
       resolve registry → missing? failed
       registry status not (accepted,review)? skipped
       license gate → denied? failed + ver_log append + continue
       checkpoint.update_source_status(sid, "downloading")   # SIMULATED
       checkpoint.update_source_status(sid, "pipelining")
       records = _generate_source_records(sid, d, reg, target,
                                          max_records - len(out_records))
       for rec in records:                   # SEQUENTIAL per record
         global cap check (len(out_records) >= max_records) → break
         license check per record
         dedup via seen_norm (SHA-1 of normalized messages)
         quality score clamp [0,10]
         lifecycle.transition(processing)    # SHARED FILE WRITE
         verification status (pending / needs_revision)
         out_records.append(rec)
         lifecycle.transition(curated)       # SHARED FILE WRITE
       checkpoint.update_source_status(sid, "completed", records_processed,
                                       records_accepted=sum(ids startswith sid[:3]))
       stats.accepted = len(out_records)
       if cap hit: break (source and batch loops)
     checkpoint.set_batch_completed(bid)
7. validate output (schema check, required keys)
8. write curated/v0.1/pilot_candidates.jsonl  # SINGLE FULL WRITE
9. compute checksums → checksum_registry.create("v0.1")
10. ver_log.append("curated_output")         # TAMPER-EVIDENT CHAIN
11. ver_log.append("version_snapshot")
12. checkpoint.status = "completed"
```

### 1.3 Source iteration granularity

- Iteration is **batch → source**, manifest order preserved.
- Each source yields **records** via `_generate_source_records()` (currently a
  synthetic stub capped at 10 records/source; "download" is simulated).
- `seen_norm` is a **global, cross-source dedup set** (SHA-1 over normalized
  messages) — order of first-seen determines which duplicate survives.
- `out_records` append order == manifest order → **deterministic output**.

### 1.4 Checkpoint handling (`checkpoint.py`)

- Single JSON file `metadata/engine_checkpoint.json` with an **integrity
  checksum** (SHA-256 of sorted JSON; `_save()` recomputes each write).
- `EngineCheckpoint`: session_id, mode, status, started_at, updated_at,
  current_batch, completed_batches, per-source `SourceCheckpoint{source_id,
  batch_id, status, records_processed, records_accepted, error}`.
- `update_source_status()` **rewrites the whole file every call**.
- Resume skips completed batches and completed sources.

### 1.5 Provenance tracking

- **Per-record provenance** is embedded at generation time in
  `_generate_source_records`: `source_attribution{source_id,name,url,license,
  attribution_text}` + `lineage{source,transformations,knowledge_object,
  curated_dataset,training_view}`.
- **Lifecycle** (`lifecycle.py` → `metadata/lifecycle.json`): per-record
  transitions raw→processing→curated with timestamps; single shared file.
- **VerificationLog** (`integrity.py` → `metadata/verification_log.json`):
  append-only tamper-evident chain (each entry hashed against previous).

### 1.6 Failure recovery

- A crashed run leaves checkpoint status "running"; `resume()` re-enters and
  skips completed sources/batches.
- **No lease-based re-claim**: a source stuck "downloading"/"pipelining" is
  never automatically re-claimed — it stays pending until a manual reset.
- Failed sources are marked `failed` and skipped on resume (must re-run).

---

## 2. Parallelization Boundaries

### 2.1 What can become scheduler tasks

| Step | Parallelizable? | Why |
|------|----------------|-----|
| Registry resolve + license gate | **YES** | read-only against registry + manifest; pure per source |
| `_generate_source_records` | **YES** | per-source deterministic, no shared state |
| Per-record dedup (seen_norm) | **NO (must stay central)** | global cross-source set; parallel first-wins would be non-deterministic |
| Per-record quality scoring | YES per record, but cheap | deterministic per record |
| `lifecycle.transition` | **NO (must stay central)** | single shared JSON file; concurrent writes corrupt |
| `ver_log.append` | **NO (must stay central)** | tamper-evident chain is append-ordered |
| `checkpoint.update_source_status` | **NO (must stay central)** | whole-file rewrite; concurrent calls clobber |
| `checksum_registry.create` | NO | single write at finalize |
| curated file write | NO | single full write at finalize |

**Verdict:** the **per-source pipeline** (resolve → license → generate) is
the parallelizable unit. Everything that touches shared state (dedup, score
gate decision, lifecycle, ver_log, checkpoint, curated write) must stay in a
single serialized finalize step.

### 2.2 Task granularity

- **Source-level tasks** (one Task per (batch, source)) — recommended.
  Matches the manifest's natural unit; record-level or byte-range tasks would
  fragment the global dedup and max_records semantics.
- Batch-level tasks are too coarse (no intra-batch parallelism).
- Worker returns **generated records + per-source stats only** — no shared
  writes inside the worker.

### 2.3 What the worker CANNOT do

The worker must be **pure** (no side effects beyond its own memory):
- NO lifecycle.transition
- NO ver_log.append
- NO checkpoint update
- NO curated file write
- NO global dedup decision

All of these move to a single-threaded finalize that consumes worker results
in deterministic (manifest) order.

---

## 3. Risk Assessment

| Risk | Severity | Detail | Mitigation |
|------|----------|--------|------------|
| **Duplicate acquisition** | MEDIUM | Same source in two batches / resume re-run could double-process | Deterministic task_id (`acq:<bid>:<sid>`), completed-skip; cache is content-addressed (5B) |
| **Checkpoint corruption** | HIGH | `_save()` rewrites whole JSON; concurrent `update_source_status` from workers → last-write-wins clobber | Workers never touch checkpoint; registry is source of truth; finalize writes checkpoint once |
| **Concurrent shared-file writes** | HIGH | lifecycle.json, verification_log.json, engine_checkpoint.json all single-file | All shared writes stay in serialized finalize; workers return data only |
| **Provenance/license metadata race** | MEDIUM | `source_attribution`/`lineage` written per record during generation — if workers mutated shared copies, race | Workers build records from immutable manifest/registry snapshots; attribution set inside worker on its OWN records (safe); finalize only appends |
| **Deterministic ordering** | HIGH | `out_records` order == manifest order; dedup first-wins depends on it | Results collected and **sorted by (batch order, source order)** before dedup/finalize — byte-identical output |
| **Global max_records cap** | MEDIUM | `max_records - len(out_records)` passed per source; parallel sources would overshoot | Workers generate up to their source target; finalize applies global cap in order (same as today) |
| **Dedup semantics change** | HIGH | seen_norm is cross-source; parallel per-source dedup would let cross-source duplicates through | Keep dedup in finalize, applied in deterministic order |
| **Network-block leak** | LOW | `install_network_block()` must not leak into workers in real download mode | Only dry-run uses it; real mode workers never install |

---

## 4. Migration Design Proposal

### 4.1 Task model

```python
Task(
    task_id="acq:engine:{batch_id}:{source_id}",   # deterministic
    source=source_id,
    operation="engine_source_pipeline",
    input=source_id,
    estimated_size_mb=0.0,
    extra={
        "root": str(root),
        "batch_id": bid,
        "dataset": manifest_dataset,       # immutable snapshot (serialized)
        "registry_entry": reg,             # immutable snapshot
        "max_records": max_records,        # informational; cap applied in finalize
    },
)
```

Worker returns `{"source_id", "batch_id", "records": [...], "attempted": N,
"license_blocked": 0/1, "status": "ok"}`. No shared writes.

### 4.2 Task IDs

`acq:engine:<batch_id>:<source_id>` — deterministic, sorted by batch order
then source order → preserves manifest ordering for the finalize pass.

### 4.3 Registry usage

- Stage `"acquisition"` → `metadata/pipeline_state/task_registry_acquisition.jsonl`
  (same registry the 5B downloader uses; distinct task prefixes).
- State mapping:
  - `pending` ↔ engine pending
  - `running` ↔ resolving/pipelining
  - `completed` ↔ engine completed
  - `failed` (after retries) / `skipped` ↔ engine failed/skipped
- **`CheckpointManager` stays** (constraint from 5B): it becomes a facade that
  reads registry states and writes the same `engine_checkpoint.json` shape.
  On `resume()`, completed sources are derived from the registry.

### 4.4 Resume/retry

- Completed tasks skipped (registry).
- **New capability**: stale `running` re-claimed after lease (fixes the
  current no-re-claim gap).
- Retry: `max_retries=2`; worker raising → retried → terminal failed.
- Finalize step (dedup/score/lifecycle/curated write) is idempotent: it
  consumes results collected in deterministic order; a re-run regenerates the
  same records from the same inputs.

### 4.5 Resource limits

- Pool: `process` (CPU record generation), fallback sequential on error /
  macOS SQLite-adjacent safety (though engine workers don't touch SQLite —
  they're pure, so process pool is safe on Mac too).
- Workers: `safe_worker_limit()` (CPU/RAM aware).
- No full-corpus load: per-source workers.

### 4.6 Sequential fallback

- Original sequential loop preserved exactly (same as Phases 1–4, 5B).
- Kill-switch `_SCHEDULER_ENABLED` pattern (from 5B) for operational safety.

---

## 5. Summary

| Aspect | Current | Target |
|--------|---------|--------|
| Execution | sequential batch→source loop | scheduler source tasks + serialized finalize |
| Task unit | (batch, source) implicit | explicit `acq:engine:<bid>:<sid>` |
| Dedup | global seen_norm in loop | same, but in finalize (deterministic order) |
| Checkpoint | CheckpointManager JSON | registry + facade writing same JSON |
| Crash recovery | no re-claim | lease-based stale re-claim |
| Shared writes | inline per source | finalize only |
| Output | deterministic manifest order | byte-identical (sorted results + finalize) |
| Fallback | n/a | sequential loop preserved |

**Verdict:** migratable with low risk provided workers are pure
(return-data-only), finalize stays serialized, and results are re-ordered to
manifest sequence before dedup/score. Detailed design follows in
`docs/architecture/acquisition_engine_migration_design_v1.md`.
