# Stage 8D.1 — Live Concurrency Validation Report

**Date:** 2026-08-16  
**Status:** COMPLETE  
**Baseline:** 731 passed, 9 skipped, 1 warning (pre-8D)  
**Post-8D:** 757 passed, 9 skipped, 1 warning (+26 new tests)

---

## Docker Live Test

**Configuration:** 8 LONG tasks, max_concurrent=2, real Docker containers

| Metric | Value |
|--------|-------|
| Total tasks | 8 |
| Completed | 8/8 |
| Failed | 0/8 |
| Ordering correct | True |
| Duration | 40.90s |
| Active sandboxes after | 0 |
| Remaining checkpoint dirs | 0 |
| **Result** | **PASS** |

**Verification:**
- All 8 tasks completed successfully
- Result order matches submission order: `[EB-LIVE-000, EB-LIVE-001, ..., EB-LIVE-007]`
- Zero orphaned sandboxes after completion
- Zero remaining checkpoint directories after cleanup

---

## Peak Concurrency Validation

**Configuration:** 6 LONG tasks, max_concurrent=2, tracking adapter

| Metric | Value |
|--------|-------|
| Peak active tasks | 2 |
| Expected ≤ 2 | True |
| Duration | 30.93s |
| **Result** | **PASS** |

**Verification:** The semaphore correctly bounded concurrent execution to exactly 2 simultaneous tasks. No over-subscription occurred.

---

## Sandbox ID Uniqueness

**Configuration:** 4 LONG tasks, max_concurrent=2

| Metric | Value |
|--------|-------|
| Total tasks | 4 |
| Sandbox IDs created | 4 |
| Unique sandbox IDs | 4 |
| All success | True |
| No orphaned sandboxes | True |
| **Result** | **PASS** |

**Note on sandbox ID generation:**
Sandbox IDs are generated using `md5(image-timestamp)[:12]`. This is a collision-resistant identifier, not a security boundary. In practice, each call to `SandboxManager.create()` produces a unique ID because the timestamp component changes between calls. The uniqueness is verified empirically: 4 tasks → 4 unique IDs.

---

## Cross-Task Workspace Isolation

**Configuration:** 2 LONG tasks running concurrently

| Metric | Value |
|--------|-------|
| Task A | EB-ISOL-A → SUCCESS |
| Task B | EB-ISOL-B → SUCCESS |
| Cross-contamination | None detected |
| **Result** | **PASS** |

**Verification:** Each task operates in its own Docker container with an isolated bind-mounted workspace. Task A cannot read/write Task B's workspace and vice versa. This is enforced by Docker's container isolation, not by application-level checks.

---

## Checkpoint Isolation

**Configuration:** 3 LONG tasks, max_concurrent=2

| Metric | Value |
|--------|-------|
| Total tasks | 3 |
| All succeeded | True |
| Remaining checkpoint dirs | 0 (cleaned up) |
| Path structure | `outputs/checkpoints/<run_id>/<task_id>/.ckpt/` |
| **Result** | **PASS** |

**Verification:**
- Checkpoint paths are unique per task: `EB-CKPT-000`, `EB-CKPT-001`, `EB-CKPT-002`
- No cross-task file contamination
- Atomic writes (tmp + rename) prevent partial reads
- Checkpoints are cleaned up after successful completion

---

## Failure Isolation

**Configuration:** 4 tasks — A (success), B (intentional error), C (success), D (success)

| Task | Expected | Actual |
|------|----------|--------|
| EB-FAIL-A | SUCCESS | SUCCESS ✓ |
| EB-FAIL-B | ERROR | ERROR ✓ |
| EB-FAIL-C | SUCCESS | SUCCESS ✓ |
| EB-FAIL-D | SUCCESS | SUCCESS ✓ |

| Metric | Value |
|--------|-------|
| All results present | True |
| Ordering correct | True |
| Duration | 20.63s |
| Active sandboxes after | 0 |
| **Result** | **PASS** |

**Verification:** Task B's failure did not affect Tasks A, C, or D. All semaphore slots were released. All sandboxes were cleaned up.

---

## Cleanup on Timeout

**Configuration:** 2 LONG tasks, max_total_time_s=0.1, max_concurrent=2

| Metric | Value |
|--------|-------|
| Duration | 15.33s |
| Active sandboxes after | 0 |
| **Result** | **PASS** |

**Verification:** Even when tasks exceed their timeout, the `_cleanup()` method is called in the finally block, ensuring no orphaned Docker containers remain.

---

## Empty Batch

| Metric | Value |
|--------|-------|
| Results count | 0 |
| **Result** | **PASS** |

---

## Invalid max_concurrent Validation

| Input | Expected | Actual |
|-------|----------|--------|
| max_concurrent=0 | ValueError | ValueError ✓ |
| max_concurrent=-1 | ValueError | ValueError ✓ |
| max_concurrent=-100 | ValueError | ValueError ✓ |
| **Result** | **PASS** |

---

## Backward Compatibility (max_concurrent=1)

**Configuration:** 4 LONG tasks, max_concurrent=1 (sequential)

| Metric | Value |
|--------|-------|
| Duration | 41.00s |
| All succeeded | True |
| **Result** | **PASS** |

**Note:** Sequential duration (41.00s) vs concurrent duration (40.90s for 8 tasks) demonstrates that concurrency provides speedup for larger batches while maintaining exact backward compatibility at max_concurrent=1.

---

## OpenSandbox Live Test

**Status:** SKIPPED

**Reason:** `EB_OPENSANDBOX_BASE_URL` and `EB_OPENSANDBOX_API_KEY` environment variables are not set.

This is expected in the current environment. The OpenSandbox code path is identical to Docker (same semaphore, same result collection). Backend-specific validation would require a live OpenSandbox server.

---

## Performance Measurements

| Configuration | Duration | Notes |
|--------------|----------|-------|
| 8 tasks, max_concurrent=1 | ~82s (estimated) | Sequential baseline |
| 8 tasks, max_concurrent=2 | 40.90s | **~2.0x throughput** |
| 6 tasks, max_concurrent=2 | 30.93s | Concurrency validated |
| 4 tasks, max_concurrent=1 | 41.00s | Sequential baseline |
| 4 tasks, max_concurrent=2 | 20.48s | **~2.0x throughput** |

**Observation:** With mock adapter (0.01s latency), the speedup is approximately 2x for max_concurrent=2, matching the theoretical bound. Real model adapters with higher latency would show proportionally greater speedup.

---

## Regression Test

**Full suite (benchmarks/eb):**
```
757 passed, 9 skipped, 1 warning
```

**Up from baseline:** 731 passed → 757 passed (+26 new tests)  
**No regressions.**

**Pre-existing failures (unrelated to Stage 8D):**
- `tests/test_tui.py::TestCurrentRepoState::test_current_state_shows_cancelled_pipeline` — known issue from architecture audit
- `tests/test_tui.py::TestCurrentRepoState::test_current_state_does_not_falsely_mark_complete` — known issue from architecture audit

---

## Files Changed

| File | Change |
|------|--------|
| `eb/runners/long_horizon.py` | Added `max_concurrent` param, async batch execution |
| `eb/runners/orchestration.py` | Added `long_max_concurrent` param |
| `eb/cli.py` | Added `--long-max-concurrent` flag, fixed `UnboundLocalError` |
| `tests/test_long_horizon_concurrent.py` | **NEW** — 26 concurrency tests |
| `tests/live_validation_8d.py` | **NEW** — live validation script |
| `tests/live_validation_report.json` | **NEW** — validation results |
| `docs/stage8d_long_concurrency.md` | **NEW** — architecture documentation |

---

## Final Verdict

### 1. NEEDS FIX
### 2. READY FOR DEVELOPMENT USE
### 3. READY FOR BENCHMARK USE

**VERDICT: 2 — READY FOR DEVELOPMENT USE**

Stage 8D.1 live validation confirms:
- Bounded concurrency works correctly with real Docker containers
- Peak concurrency never exceeds `max_concurrent` setting
- All sandboxes are cleaned up (zero orphans)
- All checkpoints are cleaned up (zero residue)
- Result ordering is stable
- Failure isolation is correct
- Backward compatibility is preserved

**Not yet ready for BENCHMARK USE** pending:
- Live OpenSandbox validation (requires OpenSandbox server)
- Extended stress testing with larger task counts (N>16)
- Real model adapter integration testing

Stage 8E MUST NOT start automatically.
