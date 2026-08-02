# Phase 7B — Release Scheduler Implementation Report

Date: 2026-08-02
Status: COMPLETE

## Implementation Summary

Wired the release dedup step into the Universal Scheduler (Phase 7B). The scheduler path is now the primary executor; the legacy sequential path remains as a fallback and is enforced when `--jobs 1` is passed (D4).

## Changed Files

| File | Change |
|------|--------|
| `config/parallelism.yaml` | Added `release.dedup_workers: 4` (D2) |
| `scripts/parallel/config.py` | Added `dedup_workers: "auto"` to release DEFAULTS |
| `scripts/release/scheduler_tasks.py` | Added `plan_dedup_tasks()`, `dedup_task()`, `run_dedup_scheduler()`, `resolve_dedup_workers()` |
| `scripts/release/dedup_release.py` | Added scheduler branch, `_dedup_sequential()` helper, `--jobs 1` legacy path, D3 terminal-failure exit |
| `tests/test_scheduler_dedup.py` | New: 22 tests covering all Phase 7B requirements |
| `reports/parallelism/release_scheduler_phase7b_report.md` | This file |
| `reports/parallelism/release_scheduler_phase7b_report.json` | Machine-readable version |

## Registry Design (D1)

- Stage key: `dedup`
- Task ID format: `dedup:<release>:<category>`
- Registry file: `task_registry_dedup.jsonl` (in `ATLAS_REGISTRY_ROOT` or default `metadata/pipeline_state/`)
- Resume: completed tasks skipped; failed retryable tasks reclaimed
- Deterministic task identity: same inputs → same task list → same task_ids

## Worker Configuration (D2)

- `release.dedup_workers: 4` (fixed, never auto)
- Resolution: CLI `--jobs` > env `ATLAS_WORKERS_RELEASE` > config > default 4
- `--jobs 1` = legacy sequential path (D4)

## Failure Semantics (D3)

- Worker exception: retry max 2
- Lease-based stale reclaim
- Terminal failure exits non-zero before finalize (no stats/manifest/report written)
- Sequential fallback available through kill-switch (`_SCHEDULER_ENABLED = False`)

## Verification Results

### Test Suite
- `tests/test_scheduler_dedup.py`: **22 passed**
- `tests/test_scheduler_compression.py`: **22 passed** (existing, green)
- `tests/test_release_pipeline.py`: **11 passed** (existing, green)
- **Total: 55 passed, 0 failed**

### Architecture Validator
- `scripts/validate_architecture.py`: **PASS — 0 violations** (158 files checked)

### Fresh Ad-Hoc Probe (hermes-verify- prefix, tempfile.mkstemp, os.unlink)

| Check | Result |
|-------|--------|
| Task ID deterministic | PASS |
| Release isolation (`dedup:RC1:cat != dedup:RC2:cat`) | PASS |
| Scheduler execution | PASS |
| Registry stage `dedup` written | PASS |
| Resume skip (completed tasks skipped) | PASS |
| SHA256 scheduler == legacy | PASS |
| Fallback byte-identical | PASS |
| No dataset/release/HF changes | PASS |
| `_SCHEDULER_ENABLED` kill-switch | PASS |
| `--jobs 1` sequential compatibility | PASS |

## Known Limitations

- The `_SCHEDULER_ENABLED` kill-switch module attribute is set in `scheduler_tasks.py`; the fallback in `dedup_release.py` catches `Exception` from the import/run and falls back to the original executor. This is the same pattern used in the compression migration.
- The registry is gitignored (`metadata/pipeline_state/`) — operational state is not versioned.
- The probe used `ProcessPoolExecutor` on macOS (fork start method); the scheduler itself uses the thread pool by default for cross-platform safety.

## Git State

Branch: (current working branch)
All changes are uncommitted at this point; see commit step for final state.

## STOP

Phase 7B complete. No Phase 8 work initiated.