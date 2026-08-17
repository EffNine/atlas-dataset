# Stage 8A — LONG Runner Implementation

**Date:** 2026-08-16  
**Status:** Implemented  
**Scope:** LongHorizonRunner, StageResult model, orchestrator integration, tests

---

## 1. LONG Semantic Definition

### 1.1 What LONG Is

LONG is a **multi-stage engineering workflow** with:

- Repository work across stages
- Sandbox execution
- Persistent state across stages
- Per-stage evaluation
- Failures at any stage
- Requirement/context changes between stages
- Final delivery assessment

### 1.2 What LONG Is NOT

- LONG is **not** MULTI with more turns
- LONG is **not** conversation-only iteration
- LONG does **not** use transient turn context
- LONG requires a sandbox for repository continuity

### 1.3 Key Distinction: MULTI vs LONG

| Dimension | MULTI | LONG |
|-----------|-------|------|
| Nature | Conversation-level iteration | Engineering workflow |
| State | Turn history (prompt/response) | Stage state (artifacts, filesystem, test results) |
| Termination | `FINAL_ANSWER:` or max turns | Stage completion or final delivery |
| Sandbox | Not required | Required (repository work per stage) |
| Stages | N/A (single conversation) | Multiple distinct phases |
| Failure handling | Per-turn error | Per-stage failure (no recovery in 8A) |
| Checkpointing | Not needed | Not implemented in 8A (deferred) |
| Evaluation | After final answer | Per-stage + final delivery |

---

## 2. Implementation Summary

### 2.1 Files Changed

| File | Change |
|------|--------|
| `eb/core/schema.py` | Added `StageData`, `StageResult` models; extended `TaskResult` with LONG fields |
| `eb/runners/long_horizon.py` | Implemented `LongHorizonRunner` |
| `eb/runners/__init__.py` | Exported `LongHorizonRunner` |
| `eb/runners/orchestration.py` | Integrated LONG into `RunOrchestrator` |
| `tests/test_long_horizon_runner.py` | Added 32 unit/integration tests |

### 2.2 New Models

**`StageData`** — Represents a single stage definition:
- `id`: unique stage identifier
- `name`: human-readable stage name
- `prompt`: the prompt for this stage
- `evaluation`: per-stage evaluation config (dict)
- `timeout_s`: optional per-stage timeout
- `metadata`: arbitrary stage metadata

**`StageResult`** — Result from a single stage execution:
- `stage_id`: matches StageData.id
- `stage_name`: matches StageData.name
- `status`: SUCCESS, FAILED, ERROR, TIMEOUT, CANCELLED
- `output`: the model's response text
- `score`: aggregated evaluator score
- `duration_s`: time to execute the stage
- `token_usage`: prompt/completion/total tokens
- `evaluator_results`: per-stage evaluator outputs
- `raw_score`: pre-aggregation score
- `flags`: additional diagnostic flags
- `error`: error description if status is ERROR/TIMEOUT
- `metadata`: stage-specific metadata

### 2.3 TaskResult Extensions

Added LONG-specific fields to `TaskResult`:
- `stage_results: list[StageResult]` — all stage results in order
- `stages: list[StageData]` — the stages that were executed
- `sandbox_id_long: str | None` — the sandbox ID used across all stages

### 2.4 LongHorizonRunner

**Constructor parameters:**
- `adapter`: ModelAdapter — the inference backend
- `dispatcher`: EvaluatorDispatcher — evaluator dispatch
- `sandbox_manager`: SandboxManager — sandbox lifecycle management
- `max_stages`: int — maximum stages to execute (default: 10)
- `max_total_time_s`: float — total workflow timeout (default: 900s)
- `stage_timeout_s`: float — per-stage timeout (default: 120s)
- `docker_image`: str — default Docker image (default: python:3.11-slim)

**Execution flow:**
```
LONG Task
  -> validate mode == LONG
  -> extract stages from task.context["stages"]
  -> load repository fixture (if repository_id provided)
  -> create workspace copy
  -> create sandbox
  -> copy fixture into sandbox
  -> for each stage (sequentially):
       -> build stage prompt (includes prev stage output)
       -> generate response via adapter
       -> evaluate response
       -> record StageResult
       -> if ERROR or TIMEOUT: stop
  -> aggregate final score from all stage scores
  -> cleanup sandbox
  -> return TaskResult with stage_results
```

---

## 3. Stage Lifecycle

### 3.1 Sandbox Lifecycle

The same sandbox is created once and reused across all stages:

1. **Create** — `SandboxManager.create(image, policy)` called once before Stage 1
2. **Copy In** — Fixture workspace copied into sandbox once before Stage 1
3. **Execute** — Each stage runs in the same sandbox; repository changes persist
4. **Collect** — Evidence collected after all stages complete
5. **Cleanup** — Sandbox stopped and destroyed after final evaluation

This ensures **engineering continuity** — a file written in Stage 1 is visible in Stage 2.

### 3.2 Stage State Continuity

Each stage receives:
- The original task prompt
- The current stage's prompt
- The previous stage's output (via "PREVIOUS STAGE OUTPUT" section)

This allows later stages to build upon earlier results.

### 3.3 Stage Transitions

- **Success** -> proceed to next stage with previous output
- **Error** -> terminate workflow, record StageResult(ERROR)
- **Timeout** -> terminate workflow, record StageResult(TIMEOUT)
- **Max stages reached** -> complete with executed stages

---

## 4. Failure Semantics

### 4.1 Handled Failures

| Failure Type | Behavior |
|-------------|----------|
| Stage adapter error | Record StageResult(ERROR), terminate workflow |
| Stage timeout | Record StageResult(TIMEOUT), terminate workflow |
| Sandbox creation failure | Return TaskResult(ERROR) immediately |
| Fixture not found | Return TaskResult(ERROR) immediately |
| No stages defined | Return TaskResult(ERROR) immediately |
| Max stages reached | Complete successfully with executed stages |
| Total time exceeded | Record remaining stages as TIMEOUT, terminate |
| Adapter exception | Record StageResult(ERROR), terminate workflow |

### 4.2 No Recovery

Stage 8A does **not** implement recovery logic. A failed stage terminates the entire workflow. This is by design — recovery is deferred to a future stage.

### 4.3 Cleanup Guarantees

Cleanup runs on all exit paths:
- Successful completion
- Stage failure
- Timeout
- Adapter error
- Sandbox creation failure

---

## 5. Current Limitations

### 5.1 Explicitly NOT Implemented in 8A

The following are deferred to future stages:

| Feature | Deferred To | Reason |
|---------|-------------|--------|
| Checkpoint/resume | Future stage | Requires persistent state storage |
| Recovery logic | Future stage | Complex semantic decisions needed |
| stages.json fixture schema | Stage 8B | Formal schema design needed |
| Stage fixture definitions | Stage 8B | Requires new file format |
| Advanced batch concurrency | Stage 8D | Requires scheduler integration |
| LONG-specific evaluator | Stage 8B+ | Evaluator design deferred |
| CLI flags for LONG | Stage 8C | CLI integration deferred |
| Requirement-change handling | Stage 8B | New fixture semantics needed |
| Stage-level cancellation | Future stage | Lifecycle management needed |

### 5.2 Stage Definition Format

For Stage 8A, stages are defined inline in `task.context["stages"]`:

```json
{
  "context": {
    "stages": [
      {"id": "arch", "name": "Architecture", "prompt": "Design the system"},
      {"id": "impl", "name": "Implementation", "prompt": "Implement it"},
      {"id": "test", "name": "Testing", "prompt": "Write tests"}
    ]
  }
}
```

Stage 8B will introduce a formal `stages.json` fixture schema.

---

## 6. Architecture Guardrails

### 6.1 What Was Preserved

- Existing SINGLE, EXEC, MULTI runners untouched
- Sandbox interface unchanged (Docker/OpenSandbox agnostic)
- Evaluator/dispatcher infrastructure unchanged
- Scoring semantics unchanged
- TaskResult backward compatibility preserved
- RunOrchestrator behavior for non-LONG modes unchanged

### 6.2 What Was Added

- `LongHorizonRunner` as a standalone class (does NOT extend MultiRunner)
- `StageData` and `StageResult` Pydantic models
- LONG task routing in `RunOrchestrator`
- 32 new tests covering all required scenarios

---

## 7. Tests

### 7.1 Test Coverage

**32 new tests** in `tests/test_long_horizon_runner.py`:

| Category | Tests |
|----------|-------|
| Single task execution | 12 |
| Stage failure handling | 4 |
| Batch execution | 5 |
| Scoring | 2 |
| Sandbox interaction | 2 |
| Context/result models | 4 |
| Integration | 2 |

### 7.2 Full Suite Result

```
631 passed, 9 skipped, 1 warning
```

No regressions in existing SINGLE, EXEC, MULTI, Docker sandbox, or OpenSandbox tests.

---

## 8. Smoke Test

### 8.1 Test: Three-Stage Engineering Workflow

```python
task = _make_long_task(stages=[
    {"id": "arch", "name": "Architecture", "prompt": "Design the system"},
    {"id": "impl", "name": "Implementation", "prompt": "Implement it"},
    {"id": "test", "name": "Testing", "prompt": "Write tests"},
])
```

**Verified:**
- Same sandbox/workspace continuity across all 3 stages
- Stage 2 sees "PREVIOUS STAGE OUTPUT" containing Stage 1's response
- Stage 3 sees "PREVIOUS STAGE OUTPUT" containing Stage 2's response
- All 3 StageResults recorded with SUCCESS status
- Final TaskResult.raw_response == Stage 3 output
- Final TaskResult.raw_task_score == average of stage scores
- Sandbox created once, cleaned up once
- No regression in SINGLE/EXEC/MULTI tests

---

## 9. Files Changed

### New Files
- `eb/runners/long_horizon.py` — LongHorizonRunner implementation
- `tests/test_long_horizon_runner.py` — 32 unit/integration tests
- `docs/stage8a_long_runner.md` — This document

### Modified Files
- `eb/core/schema.py` — Added StageData, StageResult; extended TaskResult
- `eb/runners/__init__.py` — Exported LongHorizonRunner
- `eb/runners/orchestration.py` — Integrated LONG into RunOrchestrator

---

## 10. Verdict

**READY FOR DEVELOPMENT USE**

Stage 8A provides a minimal, correct, composable LONG runner that:
- Executes multi-stage workflows with sandbox continuity
- Handles failures, timeouts, and errors gracefully
- Produces deterministic TaskResult with stage-level detail
- Integrates cleanly with existing orchestration
- Passes all tests with no regressions

Not ready for benchmark use yet because:
- stages.json fixture schema is not finalized (Stage 8B)
- No real benchmark tasks exist in LONG format yet
- LONG-specific evaluator is not implemented
