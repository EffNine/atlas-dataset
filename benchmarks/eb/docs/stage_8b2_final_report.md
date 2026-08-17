# Stage 8B.2 — LONG Scoring Semantics Fix: Final Report

## Executive Summary

Redesigned the LONG evaluator to separate **SCORE** (continuous quality) from **OUTCOME** (gate-based decision). The 4 counter-intuitive PASS results from 8B.1 are all resolved. Full test suite: **703 passed, 9 skipped, 1 warning** (matches baseline + 30 new tests).

---

## Final Scoring Model

### Dual Concept: Score vs Outcome

| Concept | Type | Range | Determined By |
|---------|------|-------|---------------|
| **SCORE** | Continuous | [0.0, 1.0] | Weighted formula + modifiers |
| **OUTCOME** | Categorical | PASS / PARTIAL / FAIL / NOT_APPLICABLE | Explicit gates |

### Score Formula

```
base = progress_score * 0.7 + terminal_score * 0.3

if error_stages:        base *= 0.5
if delivery_criteria:   base = base * 0.7 + delivery_score * 0.3
if requirement_changes: base = base * 0.8 + req_change_score * 0.2

score = clamp(base, 0.0, 1.0)
```

**Why each weight exists:**
- `0.7` progress: LONG tasks measure workflow completion; intermediate work matters
- `0.3` terminal: Final delivery quality matters but shouldn't override process failure
- `0.5` error penalty: Adapter/sandbox errors indicate infrastructure failure, not partial work
- `0.7/0.3` delivery blend: Delivery criteria modulate but don't dominate the score
- `0.8/0.2` req-change blend: Adaptation is important but doesn't override core progress

### Outcome Gate Rules

**FAIL gates** (hard failures):
1. Terminal stage failed (FAILED/TIMEOUT)
2. Any stage has ERROR status (adapter/sandbox failure)

**PASS gates** (all must pass):
1. All stages have SUCCESS status
2. All requirement changes were adapted (next stage succeeded)
3. All delivery criteria are met (if delivery_criteria exists)

**PARTIAL**: Meaningful progress occurred but one or more non-terminal gates failed

**NOT_APPLICABLE**: No stage results available

---

## Outcome Model

### New EvaluatorStatus Value

Added `PARTIAL = "PARTIAL"` to `EvaluatorStatus` enum (`eb/core/types.py:104`).

### New TaskResult Field

Added `long_outcome: str | None = None` to `TaskResult` (`eb/core/schema.py:321`).

### Updated `TaskResult.passed` Property

```python
@property
def passed(self) -> bool | None:
    if self.long_outcome == "PASS":
        return True
    if self.long_outcome in ("FAIL", "PARTIAL"):
        return False
    score = self.raw_task_score if self.raw_task_score is not None else self.final_score
    if score is None:
        return None
    return score >= 0.5
```

---

## Gate Rules (Explicit)

| Gate | Condition | Outcome |
|------|-----------|---------|
| Terminal failure | `sr.status in (FAILED, TIMEOUT)` for terminal stage | FAIL |
| Adapter/sandbox error | `sr.status == ERROR` for any stage | FAIL |
| All gates pass | All SUCCESS + req changes adapted + delivery met | PASS |
| Partial | Anything else with meaningful execution | PARTIAL |
| No execution | No stage results | NOT_APPLICABLE |

---

## A–J Calibration Results

| # | Scenario | Score | Outcome | Gates Triggered | Expected | Correct? |
|---|----------|-------|---------|-----------------|----------|----------|
| A | all_stages_succeed | 1.0000 | PASS | — | PASS, score 1.0 | ✓ |
| B | early_stage_fails | 0.6500 | PARTIAL | stage_failed:s1 | NOT PASS | ✓ |
| C | middle_stage_fails | 0.7667 | PARTIAL | stage_failed:s2 | NOT PASS | ✓ |
| D | terminal_stage_fails | 0.0000 | FAIL | terminal_failure:s2 | FAIL | ✓ |
| E | strong_impl_weak_delivery | 0.5320 | PARTIAL | delivery_criteria_not_met:0.00 | NOT PASS | ✓ |
| F | weak_early_strong_final | 1.0000 | PASS | — | PASS | ✓ |
| G | requirement_change_succeeds | 1.0000 | PASS | — | PASS | ✓ |
| H | requirement_change_fails | 0.6133 | PARTIAL | stage_failed:s2, req_change_not_fully_adapted | NOT PASS | ✓ |
| I | adapter_error | 0.3250 | FAIL | stage_error:s1 | FAIL | ✓ |
| J | empty/no-op | N/A | NOT_APPLICABLE | no_stage_results | NOT_APPLICABLE | ✓ |

**10/10 correct.** All 4 previously-counter-intuitive scenarios (B, C, E, H) now produce PARTIAL instead of PASS.

---

## K–T Adversarial Calibration Results

| # | Scenario | Score | Outcome | Correct? |
|---|----------|-------|---------|----------|
| K | all_pass_delivery_fails | 0.7000 | PARTIAL | ✓ |
| L | first_pass_later_fail | 0.0000 | FAIL | ✓ |
| M | optional_stage_fails | 0.7667 | PARTIAL | ✓ |
| N | required_fails_useful_later | 0.7367 | PARTIAL | ✓ |
| O | req_change_twice_both_succeed | 1.0000 | PASS | ✓ |
| P | req_change_then_adapt_fails | 0.6133 | PARTIAL | ✓ |
| Q | terminal_passes_tests_fail | 0.7450 | PARTIAL | ✓ |
| R | all_low_quality | 0.7600 | PASS | ✓ |
| S | all_high_quality | 0.9850 | PASS | ✓ |
| T | sandbox_failure_no_stages | N/A | NOT_APPLICABLE | ✓ |

**10/10 correct.** All semantic boundary cases behave as expected.

---

## Score Bounds

All scores verified within canonical [0.0, 1.0] range across all 20 scenarios. No violations.

---

## Backward Compatibility

| Aspect | Status |
|--------|--------|
| SINGLE mode | Unchanged — returns NOT_APPLICABLE |
| EXEC mode | Unchanged — returns NOT_APPLICABLE |
| MULTI mode | Unchanged — returns NOT_APPLICABLE |
| `raw_task_score` aggregation | Unchanged — continuous score still flows through |
| `EvaluatorResult.status` | Extended with PARTIAL; existing consumers handle unknown statuses |
| `TaskResult.passed` | Now checks `long_outcome` first, falls back to score threshold |
| Score consumers (raw.py, orchestration.py, reports) | Unchanged — use `raw_task_score`, not outcome |
| Docker sandbox | Fixed SDK 7.2.0 compatibility (`create_host_config`, `api.create_container`) |

---

## Tests

### New Tests (30 in `tests/test_long_horizon_8b2.py`)

| Class | Tests | Coverage |
|-------|-------|----------|
| TestOutcomeSemantics | 8 | PASS/PARTIAL/FAIL/NOT_APPLICABLE determination |
| TestDeliveryCriteriaGates | 3 | Delivery met/unmet/partial |
| TestRequirementChangeGates | 2 | Adapted/not-adapted |
| TestScoreBounds | 4 | Range [0,1], low/high quality |
| TestLongOutcomeField | 6 | `long_outcome` field, `passed` property |
| TestBackwardCompatibility | 3 | SINGLE/EXEC/MULTI not affected |
| TestEvidenceAndFlags | 4 | Evidence, flags, rationale |

### Full Suite

```
703 passed, 9 skipped, 1 warning
```

Baseline was 673 passed, 9 skipped, 1 warning. Net change: +30 tests, 0 regressions.

---

## Files Changed

### Modified
- `eb/core/types.py` — Added `PARTIAL = "PARTIAL"` to `EvaluatorStatus`
- `eb/core/schema.py` — Added `long_outcome` field to `TaskResult`; updated `passed` property
- `eb/evaluators/long_horizon.py` — Complete rewrite: separated score computation from outcome gating
- `eb/sandbox/docker.py` — Fixed Docker SDK 7.2.0 compatibility (`create_host_config`, `api.create_container` + `api.start`, removed `user=` parameter)
- `tests/test_long_horizon_8b.py` — Updated `test_partial_progress_score` to expect PARTIAL

### New
- `tests/test_long_horizon_8b2.py` — 30 new tests for outcome semantics
- `tests/test_stage_8b1_validation.py` — E2E validation script
- `tests/test_stage_8b2_calibration.py` — A-T calibration script

---

## Final Verdict

### **2. READY FOR 8C**

All blocking issues from 8B.1 are resolved:
- 4/4 fixtures pass through real Docker sandbox
- 4/4 fixtures pass through OpenSandbox backend
- 12/12 pipeline checks pass
- 20/20 calibration scenarios (A–T) produce correct outcomes
- 703 tests pass, 9 skipped, 1 warning (baseline preserved)
- Score remains continuous and informative
- Outcome is explicitly represented via gates
- No arbitrary threshold abuse
- Backward compatibility maintained
