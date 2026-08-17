# Stage 8E.1 — LONG Judge Criteria & Gated Invocation

**Status:** Complete  
**Date:** 2026-08-16  
**Related:** Stage 8A (LONG runner), Stage 8B (fixtures), Stage 8D (concurrency)

---

## 1. LONG Judge Rubric

The existing 3-dimension LONG judge criteria (`comprehension`, `coherence`, `completion`) have been replaced with an 8-dimension engineering rubric:

| Dimension | Weight | Description |
|-----------|--------|-------------|
| `correctness` | 0.25 | Correctness of implementation against requirements and test outcomes |
| `completeness` | 0.15 | Completeness of stage execution and artifact delivery |
| `requirement_adherence` | 0.15 | Adherence to original and changed requirements throughout the workflow |
| `implementation_quality` | 0.15 | Code structure, readability, and engineering best practices |
| `test_quality` | 0.10 | Quality, coverage, and robustness of tests produced |
| `regression_safety` | 0.10 | Absence of unintended changes or regressions to existing code |
| `adaptation_quality` | 0.05 | Quality of adaptation when requirements change mid-workflow |
| `final_delivery_quality` | 0.05 | Overall quality and professionalism of the final deliverable |

**Total weight: 1.0**

These criteria are derived in `JudgeEvaluator._derive_criteria()` when the task has `Capability.LONG` or category `long_horizon`.

---

## 2. Deterministic / Model-Judge Boundary

### Deterministic (Authority = 1, immutable)

The following properties remain exclusively deterministic and cannot be overridden by model judges:

- Stage pass/fail (SUCCESS/FAILED/TIMEOUT/ERROR)
- Terminal stage failure
- File existence / expected artifacts
- Repository state (diff, changed files)
- Exit codes from test commands
- Requirement version / change tracking
- Stage completion order
- Delivery criteria (contains/regex/file_exists checks)
- Progress score (completed/total stages)
- Error penalties (adapter/sandbox failures)
- `long_outcome` (PASS/PARTIAL/FAIL/NOT_APPLICABLE)

### Model-Judged (Authority = 3, supplemental)

The following properties require semantic understanding and are appropriate for model judgment:

- Implementation quality (code structure, patterns)
- Engineering reasoning quality
- Requirement interpretation correctness
- Maintainability / code structure
- Unnecessary changes / refactoring
- Regression risk (diff semantics)
- Final delivery quality (holistic assessment)

**Critical invariant:** A model judge MUST NOT downgrade a result from PASS to FAIL on deterministic grounds. It can only add quality dimensions on top.

---

## 3. Gated Judge Invocation

Judge evaluation is gated by the deterministic `long_outcome`:

| `long_outcome` | Judge Invoked? | Rationale |
|----------------|----------------|-----------|
| `PASS` | Yes | High-quality execution; quality dimensions add nuance |
| `PARTIAL` | Yes | Meaningful progress; quality assessment still valuable |
| `FAIL` | **No** | Deterministic gate failed; judge cannot override |
| `NOT_APPLICABLE` | **No** | No stages executed; nothing to judge |

The gating logic is implemented in `LongHorizonEvaluator._try_judge_evaluation()`:

```python
long_outcome = getattr(result, "long_outcome", None)
if long_outcome in (EvaluatorStatus.FAIL.value, EvaluatorStatus.NOT_APPLICABLE.value):
    return None, None  # Skip judge
```

This ensures the judge only evaluates tasks that have already passed deterministic gates.

---

## 4. QUALITY vs SCORE

### SCORE (Deterministic, Authority = 1)

- Computed by `LongHorizonEvaluator`
- Formula: `progress * 0.7 + terminal * 0.3` with modifiers
- Range: 0.0–1.0
- **Authoritative benchmark score**
- Stored in `EvaluatorResult.score` and `TaskResult.raw_task_score`

### QUALITY (Model-Judged, Authority = 3)

- Computed by `JudgeEvaluator.evaluate_long_judge()`
- Range: 0.0–1.0
- **Supplemental only** — never overrides SCORE
- Stored in `EvaluatorResult.details["quality_score"]`
- If judge is unavailable or skipped: `quality_score` is absent from details

### Key Separation Rules

1. `quality_score` NEVER modifies `raw_task_score`
2. `quality_score` NEVER modifies `long_outcome`
3. `quality_score` is absent when `long_outcome == FAIL` or `NOT_APPLICABLE`
4. The authoritative benchmark `EB_SCORE` continues to use deterministic `SCORE` only

---

## 5. Authority Hierarchy

| Level | Evaluator | Role |
|-------|-----------|------|
| 1 | `LongHorizonEvaluator` | Deterministic evidence (authoritative) |
| 2 | `RubricEvaluator` | Structured rubric scaffold |
| 3 | `JudgeEvaluator` | Cloud AI judge (supplemental for LONG) |
| 4 | AI Opinion | Reserved |

Cloud judges cannot override deterministic failure. The `aggregate_task_evaluator_results()` function in `scoring/raw.py` uses `single_authoritative` strategy, which selects the highest-authority applicable result.

---

## 6. Evidence Limits

### What the Judge Receives

The `JudgePromptBuilder.build_long_evidence_prompt()` constructs a bounded prompt containing:

- Task ID, category, mode, capabilities
- Original task prompt
- Stage execution results (status, score, output per stage — truncated at 1500 chars each)
- Requirement changes (if any)
- Delivery criteria (if any)
- Final delivery response (truncated at 2000 chars)

### Total Evidence Cap

- **12,000 characters** total for LONG evidence (vs. 8,000 for single-stage)
- Individual stage outputs capped at 1,500 chars
- Final response capped at 2,000 chars
- Ground truth (`expected`, `answer`, `acceptable_answers`) explicitly excluded

### Security

- API keys, secrets, and credentials are NOT included in judge prompts
- The prompt builder filters out ground truth fields
- Existing `JudgePromptBuilder.SYSTEM_PROMPT` instructs judges to evaluate, not solve

---

## 7. Reproducibility

Model-based LONG evaluation records the following metadata (already supported by existing schema):

| Field | Source |
|-------|--------|
| Judge model | `JudgeResult.model_id` |
| Provider | `JudgeModelInfo.owned_by` |
| Model version | `JudgeModelInfo.id` |
| Prompt/rubric version | `TaskJudgeConfig` or task context |
| Temperature | Always 0.0 (enforced) |
| Evaluation timestamp | `datetime.now(timezone.utc)` |
| Evidence inputs | Task ID, stage results, diff, output |
| Judge output | `JudgeResult.raw_response` (truncated to 2000 chars) |
| Evaluator version | `eb` package version |

All metadata is stored in `EvaluatorResult.details` and serialized in benchmark run artifacts.

---

## 8. Provider Configuration

Judge configuration continues to come from existing EB configuration:

- **Environment variables:** `EB_JUDGE_BASE_URL`, `EB_JUDGE_API_KEY`, `EB_JUDGE_MODEL`
- **Config file:** `config/judges.yaml` (gateway, routing, retry settings)
- **No hardcoded models:** The router selects judges dynamically from gateway metadata
- **Fallback:** If judge client is unavailable, evaluation continues with deterministic score only

---

## 9. Files Changed

| File | Change |
|------|--------|
| `eb/evaluators/judge.py` | Added `evaluate_long_judge()` method; updated `_derive_criteria()` with 8 LONG dimensions; added optional `messages` param to `_evaluate_with_judge()` |
| `eb/evaluators/long_horizon.py` | Added `_try_judge_evaluation()` method; integrated gated judge invocation in `evaluate()` |
| `eb/judges/prompt_builder.py` | Added `build_long_evidence_prompt()` method with bounded evidence |
| `tests/test_long_horizon_judge_8e1.py` | New test file (24 tests) |
| `docs/stage8e1_long_judge.md` | This document |

---

## 10. Test Coverage

24 new tests in `tests/test_long_horizon_judge_8e1.py`:

| Test Class | Tests | Coverage |
|-----------|-------|----------|
| `TestLongRubricDimensions` | 4 | 8 dimensions present, weights sum to 1.0, old criteria removed |
| `TestGatedJudgeInvocation` | 5 | PASS/PARTIAL invoke judge; FAIL/N/A skip judge; error stages skip |
| `TestQualityScore` | 5 | quality_score in details, range [0,1], doesn't change raw_score/outcome, fail immunity |
| `TestEvidenceBounding` | 3 | Evidence bounded, secrets excluded, ground truth excluded |
| `TestNonLongModesUnaffected` | 3 | SINGLE/EXEC/MULTI unchanged |
| `TestExistingJudgeBehaviorUnaffected` | 4 | Architecture/coding criteria unchanged, authority level preserved, graceful degradation |

---

## 11. Known Limitations

1. **No live judge validation:** OpenSandbox live concurrency validation was deferred in 8D; similarly, live judge evaluation requires `EB_JUDGE_BASE_URL` and `EB_JUDGE_API_KEY` to be set. Tests mock the judge client.

2. **Single-judge fallback:** If only one judge model is available, evaluation proceeds with `single_judge` flag. Multi-judge consensus requires ≥2 models.

3. **No calibration yet:** Stage 8E.2 (calibration fixtures and human reference labels) is deferred. Judge accuracy against human labels is not yet measured.

4. **No agreement metrics:** Stage 8E.3 (judge vs. human, judge vs. judge agreement rates) is deferred. Simple threshold-based disagreement flags are used.

---

## 12. Final Verdict

**READY FOR DEVELOPMENT USE**

Stage 8E.1 implements:
- 8-dimension LONG-specific judge rubric with correct weights
- Gated judge invocation (PASS/PARTIAL only)
- Separate QUALITY score that never overrides deterministic SCORE
- Bounded evidence with secret/ground-truth exclusion
- Full test coverage (24 tests)
- Zero regressions in existing judge infrastructure

**NOT YET READY FOR BENCHMARK USE** pending:
- Stage 8E.2: Calibration fixtures and human reference labels
- Stage 8E.3: Agreement metrics and reporting

Stage 8E.2 MUST NOT start automatically.
