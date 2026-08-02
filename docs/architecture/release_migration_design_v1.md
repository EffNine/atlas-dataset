# Release Tools Migration — Design v1

**Phase:** 7A (audit + design) → 7B (implementation, pending approval)
**Date:** 2026-08-02
**Status:** DRAFT — awaiting design approval. No implementation before approval.
**Baseline:** `a1eb632` (main)
**Upstream:** `reports/parallelism/release_audit.{md,json}` (Phase 7A audit)
**Patterns:** Phase 5C (pure workers + serialized finalize), Phase 6B (compression
migration — `compress_release.py` + `scheduler_tasks.py` reference implementation)

---

## 1. Scope

Migrate the **dedup release step** (`scripts/release/dedup_release.py`) onto the
Universal Scheduler (`scripts/parallel/`). Document exemptions for every other
release tool. This design mirrors the Phase 6B compression migration so the two
release steps share one execution model, registry family, and retry/resume
semantics.

**In scope (7B):**
- `dedup_release.py` scheduler adoption (category tasks, registry, retry, resume).
- Config: add `release.dedup_workers` to `config/parallelism.yaml`.
- Tests: `tests/test_scheduler_dedup.py` (+ keep existing CLI tests green).
- Docs + report updates (this design doc → implementation report at 7B end).

**Explicitly NOT in scope (documented exemptions):**
- `join_release.py` — sequential by design (cross-pass stub index, global dedup,
  manifest gate). No scheduler tasks.
- `generate_checksums.py`, `verify_release.py`, `build_release_metadata.py` —
  pure sequential, deterministic order, cheap; no migration value.
- `promote_release.py` — governance single-writer with `--dry-run` gate; **never**
  a scheduler task; requires explicit human sign-off (skill rule).
- `publish_promotion.py` — network governance; exemption + hardening candidates
  F6/F7 (batch-commit silent-drop, no destination pre-check). Implement only with
  explicit approval; dry-run/list-only testing first.
- `upload_huggingface.py` — network domain with backoff retry + remote-size
  resume; exemption-by-design (5E verdict). Hardening F4/F5 (sha256 verification,
  config-wired workers) can ride along in 7B.
- `update_release_index.py` — single-writer, chain-preserving; sequential.
- `download_release.py` — HF-library-managed retry/resume; sequential.
- `audit_duplicates.py` — read-only analysis; sequential.

**Phase boundary:** 7B = dedup scheduler + config + tests + verification + STOP.
7C (if approved) = publish/upload hardening. No dataset/release/HF changes until
explicit approval of each phase.

---

## 2. Task Model

### 2.1 Task unit

**One task per category** (9 tasks for a full release: `01_foundation` …
`09_personal_assistant`).

Rationale (audit D2): the source is already one `.zst` per category; the dedup
`seen` dict spans the whole category (byte-identical duplicate detection), so
splitting inside a category would break correctness. Category outputs are disjoint
files → safe for process-pool parallelism with zero cross-task coupling.

### 2.2 Worker

`dedup_task(task)` — module-level, in the new scheduler module (pattern:
`scheduler_tasks.py` from 6B):

```
def dedup_task(task: Task) -> dict:
    src = task["extra"]["source_dataset"] / "dataset" / task["extra"]["category"] / f'{task["extra"]["category"]}.jsonl.zst'
    dst = task["extra"]["target_dataset"] / "dataset" / task["extra"]["category"] / f'{task["extra"]["category"]}.jsonl.zst'
    stats: dict = {}
    dedup_category(src, dst, stats)      # reuses scripts/release/dedup_release.py worker VERBATIM
    return {"category": task["extra"]["category"], **stats}
```

- **Byte-identical output by construction**: calls the same `dedup_category`
  function the old `ProcessPoolExecutor` dispatched. No behavioral change.
- **Raises on error** (missing source, zstd corruption, write failure) → the
  scheduler records `failed` + `attempts` and retries per policy (audit D4).
- Returns the per-category stats dict for the finalize step.

### 2.3 Planning

Inline planner `plan_dedup_tasks(release_cfg, category_names)` (pattern:
`plan_compress_tasks`), NOT `planner.file_tasks()`, to control the exact task_id
format:

```
Task(
  task_id=f"dedup:{release}:{category}",
  kind="dedup",
  command="dedup_task",            # worker key for dispatch
  pool="process",
  extra={
    "source_dataset": ".../releases/<source>",
    "target_dataset": ".../releases/<target>",
    "category": "<category>",
    "expect_total": <int>,
    "expect_software": <int>,
  },
)
```

Planning is **stateless + deterministic**: same inputs → same task list → same
task_ids → registry resume works across restarts.

---

## 3. Registry Stage Naming & Task ID Format

### 3.1 Stage key

`dedup` — `metadata/pipeline_state/task_registry_dedup.jsonl` (audit D1).

- Isolates from `task_registry_compression.jsonl` (6B) and from any future
  `upload`/`release` stage.
- Task_ids carry an operation prefix (`dedup:`, `compress:`) so a future shared
  `release` registry is still reachable without breaking ids.
- Registry read/write via `TaskRegistry(root, "dedup")` — lease re-claim 900s,
  append-only attempts history, same semantics as compression.

### 3.2 Task ID format

```
dedup:{release}:{category}
```

Examples:
```
dedup:v1.0-RC2:01_foundation
dedup:v1.0-RC2:09_personal_assistant
```

**Deterministic guarantee:** the release is embedded in the id because the
registry is repo-global; a bare `dedup:{category}` would collide across releases
(same lesson as compression F5). Category names sort alphabetically ==
`CATEGORIES` order → result aggregation by task_id reproduces today's sequential
report ordering exactly.

### 3.3 Registry lifecycle (resume mapping)

| Prior state | Scheduler behavior |
|-------------|--------------------|
| absent | task planned, runs |
| `completed` | **skipped** (resume) |
| `running` | lease check: if lease expired → re-claim, run (crash recovery); if lease live → mark `skipped` with note (concurrent run guard) |
| `failed`/`retry` | re-run if `attempts < max_retries`; else terminal failure → exit 1 |
| `skipped` | left as-is |

Resume = **per-category incremental**: a run interrupted after 5 of 9 categories
resumes at category 6, not from scratch (fixes audit F1).

---

## 4. Worker Model

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Pool | `process` | CPU-bound zstd decompress + per-line SHA-256; pure worker (no SQLite fork hazard on macOS — worker only touches release files) |
| Worker count | `resolve_worker_count("release")` → `release.dedup_workers` (new key, default 4); CLI `--jobs` overrides (CLI > env > config) | Fixes audit F2; explicit override preserved |
| Task RAM | default (512MB) | O(1) streaming + per-category seen dict (~1M ids) fits |
| Submission | bounded (scheduler default) | 9 tasks ≪ bound; no resource spike |
| Result merge | sorted by task_id | deterministic report ordering |

`config/parallelism.yaml` addition (mirrors 6B's `compress_workers`):

```yaml
parallelism:
  stages:
    release:
      compress_workers: 4
      upload_workers: 4
      dedup_workers: 4      # NEW
```

Env override continues to work: `ATLAS_WORKERS_RELEASE=6 scripts/release/dedup_release.py ...`

---

## 5. Retry Policy

| Aspect | Policy | Rationale |
|--------|--------|-----------|
| `max_retries` | `2` (scheduler default) | mirrors compression; transient zstd/IO errors are the realistic failure class |
| Failure semantics | worker **raises** → `failed`/`retry`; after max attempts → terminal failure, exit 1 | audit D4; same final semantics as today's hard failure |
| Duplicate safety | retry rewrites only that category's output (`open_zstd_writer` = `"wb"` overwrite); outputs are disjoint per task | **no duplicate records possible on retry** |
| Idempotence | planning is stateless; completed tasks skipped | re-run is safe |
| Network | N/A (local CPU/IO only) | network tools remain exempt (upload/download) |
| No blind auto-retry | finalize step (stats+manifest) never retries | governance artifact (audit F3) |

**Important:** the scheduler does NOT auto-retry the finalize step. If
`compute_statistics`/`build_manifest` fails after all categories completed, the
run exits non-zero and the operator re-invokes — the finalize is idempotent
(recomputes stats from complete outputs, refuses to write a mismatched signature),
so a manual re-run is safe.

---

## 6. Serialized Finalize (the "pure workers + serialized finalize" pattern)

After all category tasks reach `completed`, the **driver process** (main thread,
no pool) runs, in order:

1. Consume results sorted by task_id → build the deterministic per-category stats
   dict (identical aggregation to today's submission-order loop).
2. `compute_statistics(target_dataset)` — re-reads all 9 output files: counts,
   licenses, difficulty, quality, sources. (Unchanged function.)
3. **Validation gate:** if `--expect-total`/`--expect-software` provided, compare
   computed totals; mismatch → **exit 1, do not sign** (same as today).
4. `build_manifest(...)` — signs the new manifest chained to the source release's
   `chain_hash` (`sha256-chain-v1`, `json.dumps(sort_keys=True)` → deterministic
   `content_hash`).
5. Write `metadata/releases/<target>_release.json` + `reports/releases/<target>_dedup_report.json`.

**Deterministic guarantee:** stats + manifest are byte-identical to the current
sequential CLI when inputs are identical — finalize consumes the same worker
functions in the same order. The signed manifest's `content_hash` is computed over
sorted keys, so ordering invariance holds by construction.

---

## 7. CLI & Backward Compatibility

`dedup_release.py` keeps its public CLI exactly:

```
dedup_release.py --source v1.0-RC1 --target v1.0-RC2 [--jobs N] [--expect-total N] [--expect-software N] [--skip-sign]
```

Internal behavior change: with `--jobs` unset (default), the scheduler path runs
(registry + process pool via config). With `--jobs 1`, an **explicit** sequential
fallback executes the old loop (kept for emergencies/byte-comparison testing).

| Flag | Behavior after 7B |
|------|--------------------|
| `--jobs N` (N>1) | scheduler path with worker count N (explicit override) |
| `--jobs 1` (explicit) | legacy sequential loop (old executor fallback per migration pattern) |
| unset | scheduler path with `release.dedup_workers` (default 4) |

**Fallback strategy (migration pattern):** old executor code stays in
`dedup_release.py` as `_dedup_sequential(...)`; scheduler path is the default.
A `--legacy` hidden flag forces the old path. Removed only after validation
(7B report shows scheduler output byte-identical on a fixture).

---

## 8. Deterministic Guarantees (immutable artifacts, checksums, ordering)

| Guarantee | Mechanism |
|-----------|-----------|
| Immutable release artifacts | dedup only CREATES the new target release (RC2 from RC1); never mutates the frozen source. Scheduler tasks write only `<target>/dataset/<cat>/<cat>.jsonl.zst` (new files) |
| Checksum correctness | dedup migration does NOT touch `generate_checksums.py`; the per-category SHA-256 in the dedup report is informational, not the release checksum source of truth |
| Manifest ordering | finalize iterates `CATEGORIES` + sorted task results — identical to today |
| content_hash stability | `json.dumps(sort_keys=True)` + `sha256-chain-v1` — unchanged signing function |
| Deterministic task_ids | `dedup:{release}:{category}` — planning stateless; resume-safe |
| Deterministic output bytes | same `dedup_category` worker, same zstd level, `"wb"` overwrite per task |

**Duplicate publish prevention** (applies to publish/upload exemption, not dedup):
- upload already skips size-matched remote files (resume) — hardening F4 adds
  sha256 comparison.
- publish hardening F6/F7 (per-file commit + destination pre-check) is designed
  here but **not implemented** without approval.

---

## 9. Network Failure Handling

Dedup is a **local** step (zstd + SHA-256); no network in the worker. Network
handling stays where it belongs:

| Tool | Handling |
|------|----------|
| `upload_huggingface.py` | domain backoff retry (3x, 2s·2^(n-1)); remote-size resume; **keep** |
| `download_release.py` | HF-library retry/resume (`snapshot_download`); **keep** |
| `publish_promotion.py` | no retry today; if hardened (F6/F7), per-file commits make retry idempotent — destination-exists check before copy |

No scheduler-level network retry is introduced. The scheduler's retry applies only
to local worker failures.

---

## 10. Rollback Strategy

| Layer | Rollback |
|-------|----------|
| Registry | `task_registry_dedup.jsonl` is append-only + lease-timestamped; a bad run can be reset by re-running with a cleared/repaired registry (compression precedent) or by deleting the stage file (documented operational action) |
| Output files | target release dir is new; delete `<target>/dataset/<cat>/<cat>.jsonl.zst` and re-run — `"wb"` overwrite + stateless planning make re-generation exact |
| Manifest | finalize refuses to overwrite an existing manifest path with different content; delete the failed target manifest and re-run finalize (idempotent) |
| Source release | **never touched** by dedup; frozen RC1 remains the rollback anchor |
| Code | `--legacy` flag + old executor retained until 7B validation proves byte-identical output |

---

## 11. Approval Gates

| Gate | Tool | Enforcement |
|------|------|-------------|
| Promote RC→final | `promote_release.py` | `--dry-run` required first; explicit user sign-off (skill rule); **never** a scheduler task |
| Upload/publish to HF | `upload_huggingface.py`, `publish_promotion.py` | docs rule: "never upload before an explicit human instruction"; manual CLI only; no scheduler auto-resume |
| Dedup (new RC) | scheduler | no human gate — it creates new artifacts and never mutates frozen ones; the signed manifest is the governance record |
| Phase 7B implementation | — | **this design must be approved before any code** (audit D1–D6 confirmed) |

---

## 12. Implementation Plan (7B, after approval)

1. **Config:** add `release.dedup_workers: 4` to `config/parallelism.yaml`.
2. **Scheduler module:** `scripts/release/scheduler_dedup.py` (or extend
   `scheduler_tasks.py` with a `dedup_task` + `plan_dedup_tasks` + `run_dedup`).
3. **CLI wiring:** `dedup_release.py` gains scheduler path + `--legacy` fallback;
   finalize stays serialized in driver.
4. **Tests:** `tests/test_scheduler_dedup.py` —
   - planning determinism (same inputs → same task_ids)
   - registry resume (completed skipped; failed retried; lease re-claim)
   - retry no-duplicate (worker raises once → retry → output matches expected)
   - byte-identical vs legacy path on a synthetic fixture
   - finalize ordering (stats sorted by task_id == CATEGORIES order)
   - config wiring (`resolve_worker_count("release")` == dedup_workers)
5. **Verification:** fresh probe against on-disk fixtures; run full
   `test_scheduler_dedup.py` + `test_release_pipeline.py` + `test_join_release.py`;
   git diff audit; confirm zero dataset/release/HF changes; write
   `reports/parallelism/dedup_migration_report.md`; STOP for approval.

**Phase 7C (optional, only with separate approval):** publish hardening (F6/F7 —
per-file commits + destination pre-check), upload hardening (F4/F5 — sha256
verification + config-wired workers).

---

## 13. Risks

| Risk | Mitigation |
|------|-----------|
| Scheduler path output differs from legacy | byte-identical fixture test (same worker, same order); `--legacy` retained |
| Registry collisions across releases | release embedded in task_id |
| Partial registry after crash | lease re-claim (900s) + per-category resume |
| Finalize failure after categories complete | idempotent finalize; manual re-invoke; exit 1 |
| Process pool on macOS SQLite | pure worker (no DB access in `dedup_task`); `pool=process` safe (same as compression) |
| Config change drift | `resolve_worker_count("release")` single source; `dedup_workers` default 4 matches today's effective 4 |
| Silent publish/upload corruption (exempt tools) | documented exemption + F4/F6/F7 hardening candidates with approval gates |

---

## 14. Open Questions (for approval)

1. **Registry stage key `dedup` vs `release`** — design recommends `dedup` (D1).
2. **`release.dedup_workers` default 4** — confirm (D3).
3. **Failure semantics** — worker raises → retry → exit 1 after max_retries (D4).
4. **Upload hardening (F4/F5) in 7B scope or deferred** — design recommends
   include (small, high-value, no scheduler dependency).
5. **Publish hardening (F6/F7)** — design as approved but **implement only with
   explicit approval**; dry-run/list-only test first.
6. **`--jobs 1` explicit = legacy fallback** vs always-scheduler with
   `--jobs` as pure worker count — design recommends legacy fallback for
   byte-comparison safety.

---

*End of design v1 — awaiting approval. No Phase 7B code changes made.*
