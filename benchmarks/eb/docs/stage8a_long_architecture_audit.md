# Stage 8A — LONG Runner Architecture Audit

**Date:** 2026-08-16  
**Status:** Audit Complete — No code modified  
**Scope:** Existing LONG execution model across the entire EB repository

---

## 1. LONG Semantic Definition

### 1.1 What LONG Is (From Documentation)

From `README.md`:
> **LONG** — Long-horizon engineering scenarios involving **multiple stages**, **failures**, **requirement changes**, **recovery**, and **final delivery**.

From `eb/tasks/README.md`:
> **LONG** — Long-horizon engineering scenarios with multiple stages

From `docs/architecture.md`:
> `long_horizon.py` — LONG mode (multi-stage) — **Stage 9**

Note: There is a discrepancy — `docs/architecture.md` labels LONG as **Stage 9**, while `README.md` labels it as **Stage 8**. The stage7 documentation references "Stage 8" as the next step. This suggests the original plan was Stage 8, but the architecture doc was updated to Stage 9 at some point.

### 1.2 What LONG Is NOT

- LONG is **not** simply "MULTI with more turns"
- LONG is **not** conversation-only
- LONG is **not** a single continuous dialogue
- LONG is **not** currently implemented (placeholder only)

### 1.3 Key Distinction: MULTI vs LONG

| Dimension | MULTI | LONG |
|-----------|-------|------|
| Nature | Conversation-level iteration | Engineering workflow |
| State | Turn history (prompt/response) | Stage state (artifacts, file system, test results) |
| Termination | `FINAL_ANSWER:` or max turns | Stage completion or final delivery |
| Sandbox | Not required | Likely required (repository work per stage) |
| Stages | N/A (single conversation) | Multiple distinct phases |
| Failure handling | Per-turn error | Per-stage failure + recovery |
| Checkpointing | Not needed | Likely needed (stage boundaries) |
| Evaluation | After final answer | Per-stage + final delivery |

---

## 2. Existing Architecture

### 2.1 Enum & Type Infrastructure

**Fully implemented:**
- `ExecutionMode.LONG = "LONG"` in `eb/core/types.py:20`
- `Capability.LONG = "LONG"` in `eb/core/types.py:47`
- `parse_execution_mode("LONG")` works (tested in `tests/test_core.py:33`)
- Judge router routes LONG tasks to long-context models (`eb/judges/router.py:41`)
- Judge profiler profiles LONG capability dimensions (`eb/judges/profiler.py:51`)
- Judge evaluator applies LONG-specific criteria (`eb/evaluators/judge.py:480-488`)
- Report generator includes LONG in capability order (`eb/reports/generator.py:200`)

**SingleRunner rejects LONG:**
- `tests/test_single_runner.py:131-138` verifies `SingleRunner` returns `SKIPPED` for LONG tasks

### 2.2 Runner Infrastructure

**Placeholders exist but are empty:**
- `eb/runners/long_horizon.py` — 1 line: `"""long_horizon runner placeholder."""`
- `eb/evaluators/long_horizon.py` — 1 line: `"""long_horizon evaluator placeholder."""`

**Not exported from `eb/runners/__init__.py`** — LongHorizonRunner does not exist yet.

### 2.3 Orchestrator Current State

The `RunOrchestrator.run()` method (lines 149-161 of `orchestration.py`):
```python
single_tasks = [t for t in all_tasks if t.mode == ExecutionMode.SINGLE]
exec_tasks = [t for t in all_tasks if t.mode == ExecutionMode.EXEC]
multi_tasks = [t for t in all_tasks if t.mode == ExecutionMode.MULTI]
non_supported = [
    t for t in all_tasks
    if t.mode not in (ExecutionMode.SINGLE, ExecutionMode.EXEC, ExecutionMode.MULTI)
]

if non_supported:
    modes_found = {t.mode.value for t in non_supported}
    print(f"[eb] WARNING: {len(non_supported)} non-supported task(s) found in suite, skipping: {sorted(modes_found)}")
```

**LONG tasks are currently classified as `non_supported` and skipped with a warning.**

### 2.4 Task Schema

**No LONG-specific fields in `Task` or `TaskResult`:**
- `Task` schema (`eb/core/schema.py:80-148`) has no stage-related fields
- `TaskResult` schema (`eb/core/schema.py:203-234`) has no stage-related fields
- The `context` dict could hold stage metadata, but there's no structured support

**Planned task layout** (from `eb/tasks/README.md:54-62`):
```
tasks/long_horizon/EB-LONG-001/
├── task.json       # Task definition
├── stages.json     # Stage-by-stage requirements
├── fixtures/       # Repository/environment fixtures
└── expected/       # Expected outputs per stage
```

**No `stages.json`, `fixtures/`, or `expected/` directories exist** in the repository.

### 2.5 Judge/Evaluator Infrastructure

**Judge router already handles LONG:**
- `CAPABILITY_REQUIREMENTS[Capability.LONG] = {"reasoning": 0.9, "long_context": 1.0, "instruction_following": 0.7}`
- Long-context models (128k+ context) are preferred for LONG tasks

**Judge evaluator already handles LONG:**
- Criteria: comprehension (0.3), coherence (0.3), completion (0.4)
- Uses cloud AI judge for subjective evaluation

**No dedicated LONG evaluator exists** — `eb/evaluators/long_horizon.py` is a placeholder.

### 2.6 Sandbox Infrastructure

**Sandbox interface is backend-agnostic:**
- `Sandbox` ABC in `eb/sandbox/base.py` defines create/start/exec/copy_in/copy_out/collect/stop/destroy
- `SandboxManager` in `eb/sandbox/manager.py` manages lifecycle with orphan cleanup
- Both Docker and OpenSandbox backends implement the same interface

**LONG could reuse the sandbox infrastructure** since it likely needs per-stage execution environments.

### 2.7 OpenSandbox Resume Capability

From `docs/opensandbox_integration_report.md:27`:
```
/v1/sandboxes/{id}/resume  POST  Resume paused sandbox
```

OpenSandbox supports sandbox pause/resume, which could be relevant for LONG stage transitions. Docker does not have an equivalent pause/resume API.

---

## 3. Required State Model

### 3.1 What LONG State Must Track

Based on the semantic definition ("multiple stages, failures, requirement changes, recovery, final delivery"), a LONG task requires:

1. **Stage definitions** — Ordered list of phases, each with:
   - Prompt/instructions
   - Required inputs (files, code, context)
   - Expected outputs (artifacts, tests, deliverables)
   - Timeout limits
   - Failure recovery policy

2. **Stage execution state** — Per-stage:
   - Current status (pending, running, completed, failed, recovered)
   - Sandbox ID (if sandboxed)
   - Tool call history
   - File changes
   - Test results
   - Timestamps

3. **Cross-stage state** — Persistent across stages:
   - Cumulative file system state
   - Requirement changes applied
   - Failure history
   - Recovery actions taken

4. **Final delivery state** — Aggregated:
   - All stage results
   - Final artifact hash
   - Overall pass/fail
   - EB score components

### 3.2 State Model Recommendations

**Option A: Extend TaskResult with stage fields**
- Add `stages: list[dict]` to `TaskResult.execution_metadata`
- Add `stage_results: list[TaskResult]` to `TaskResult`
- Simpler but mixes concerns

**Option B: New LongHorizonResult type**
- Dedicated result model for LONG tasks
- Contains list of stage results
- Cleaner separation but more code

**Recommendation: Option B** — A dedicated result model prevents schema pollution and makes the stage lifecycle explicit.

### 3.3 Required New Schema Fields

```python
@dataclass
class StageResult:
    stage_index: int
    stage_id: str
    status: str  # "running", "completed", "failed", "recovered"
    sandbox_id: str | None
    tool_calls: list[dict]
    test_summary: dict | None
    diff: str | None
    duration_s: float
    error: str | None
    timestamp: str

class LongHorizonResult(BaseModel):
    task_id: str
    run_id: str
    stages: list[StageResult]
    final_response: str | None
    raw_task_score: float | None
    final_score: float | None
    flags: list[str]
    execution_metadata: dict[str, Any]
```

---

## 4. Required Lifecycle

### 4.1 LONG Task Lifecycle

```
START
  │
  ▼
Load stages.json
  │
  ▼
For each stage:
  ├─→ Create sandbox (if required)
  ├─→ Copy fixtures into sandbox
  ├─→ Run model agent loop (bounded tool calls)
  ├─→ Execute stage tests
  ├─→ Collect stage evidence (diff, artifacts)
  ├─→ Evaluate stage result
  ├─→ If failed:
  │   ├─→ Apply recovery (retry, fix, skip)
  │   └─→ Record recovery action
  └─→ Clean up sandbox
  │
  ▼
Aggregate stage results
  │
  ▼
Compute final score
  │
  ▼
END
```

### 4.2 Key Lifecycle Properties

1. **Sequential stages** — Each stage completes before the next begins
2. **Sandbox per stage** — Each stage may need a fresh sandbox or a persistent one
3. **Failure recovery** — Failed stages can be retried or recovered
4. **Artifact persistence** — Stage outputs persist across stages (file system)
5. **Progressive evaluation** — Each stage is evaluated, then final aggregation

---

## 5. Sandbox Interaction

### 5.1 Does LONG Require Sandbox?

**Yes, almost certainly.** Based on the definition:
- "engineering scenarios" implies code/repository work
- "multiple stages" implies persistent state across phases
- "final delivery" implies testable outputs

LONG tasks will likely need:
- Repository fixtures per stage (like EXEC)
- File system access within sandbox
- Command execution for testing
- Diff collection for evidence

### 5.2 Sandbox Reuse Patterns

**Pattern A: Fresh sandbox per stage**
- Each stage gets a new sandbox
- Simpler isolation
- No cross-stage state persistence

**Pattern B: Persistent sandbox across stages**
- One sandbox created at start, used throughout
- Stage outputs persist naturally
- More complex cleanup

**Pattern C: Checkpointed sandbox**
- Save snapshot after each stage
- Resume from snapshot on recovery
- Requires OpenSandbox pause/resume or Docker commit

**Recommendation: Pattern B (persistent sandbox)** for Stage 8A minimum viable implementation. Pattern C can be added later.

### 5.3 Sandbox Lifecycle for LONG

```
Create sandbox (once, at task start)
  │
  ├─→ Stage 1: copy fixtures → exec → test → collect evidence
  ├─→ Stage 2: (same files persist) → exec → test → collect evidence
  ├─→ Stage 3: (same files persist) → exec → test → collect evidence
  │
Stop sandbox
Destroy sandbox
```

---

## 6. Failure/Recovery Model

### 6.1 Failure Types in LONG

| Failure Type | Description | Recovery Strategy |
|-------------|-------------|-------------------|
| Stage timeout | Stage exceeds time limit | Retry with adjusted timeout, or mark failed |
| Test failure | Stage tests don't pass | Retry with different approach, or mark failed |
| Sandbox failure | Sandbox creation/exec fails | Retry with new sandbox, or skip stage |
| Adapter failure | Model generation fails | Retry adapter call, or mark stage failed |
| Recovery exhausted | Max retries exceeded | Mark stage failed, continue to next stage |

### 6.2 Recovery Semantics

1. **Per-stage retry** — Each stage has a `max_retries` config
2. **Progressive timeout** — Retry with increased timeout (exponential backoff)
3. **Fallback strategy** — If all retries fail, mark stage as `RECOVERED_FAILED`
4. **Final aggregation** — Failed stages contribute to score based on policy

### 6.3 Checkpoint/Resume

**Not required for Stage 8A minimum.** Reasons:
- LONG tasks are expected to complete in a single process lifetime
- Process failure during a LONG task = full retry (acceptable for benchmark)
- Checkpointing adds significant complexity
- Can be added in a future stage if needed

**If checkpoints are needed later:**
- Save `StageResult` to disk after each stage
- On resume, load checkpoint and continue from last completed stage
- Requires persistent storage in `outputs/checkpoints/`

---

## 7. Should LONG Reuse MultiRunner?

### 7.1 Comparison

| Aspect | MultiRunner | LONG Runner |
|--------|-------------|-------------|
| Concurrency | Batch workers | Sequential stages |
| State | Turn history | Stage artifacts + file system |
| Sandbox | Not used | Required |
| Failure | Per-task | Per-stage with recovery |
| Checkpoint | Not needed | Potentially needed |
| Evaluator | Standard | Per-stage + final |

### 7.2 Shared Abstractions to Reuse

1. **`Runner` base class** — LONG should extend `Runner` like MultiRunner does
2. **`RunContext`** — Same context structure
3. **`TaskResult`** — LONG can extend with stage-specific fields
4. **`EvaluatorDispatcher`** — Same dispatcher for per-stage evaluation
5. **`aggregate_task_evaluator_results`** — Same aggregation logic
6. **Batch concurrency pattern** — LONG batch can use same `asyncio.Semaphore` pattern

### 7.3 New Abstractions Needed

1. **`StageResult`** — Per-stage execution result
2. **`LongHorizonContext`** — Cross-stage mutable state
3. **`StageRunner`** — Internal helper for single-stage execution (could reuse RepositoryRunner logic)
4. **`StageLoader`** — Load `stages.json` and validate structure

### 7.4 Recommendation

**Do NOT extend MultiRunner.** LONG and MULTI are fundamentally different:
- MULTI = conversation iteration (no sandbox)
- LONG = engineering workflow (requires sandbox, stages, recovery)

**DO reuse patterns from MultiRunner:**
- Bounded concurrency in batch mode
- Result ordering preservation
- Failure isolation
- Turn/stage metadata structure

---

## 8. Components That Must NOT Change

| Component | Reason |
|-----------|--------|
| `ExecutionMode` enum | LONG already defined |
| `Capability` enum | LONG already defined |
| `Sandbox` interface | Backend-agnostic, unchanged |
| `DockerSandbox` | No changes needed |
| `OpenSandboxBackend` | No changes needed |
| `SandboxManager` | No changes needed |
| `RepositoryRunner` | EXEC runner, separate concern |
| `SingleRunner` | SINGLE mode, separate concern |
| `MultiRunner` | MULTI mode, separate concern |
| `JudgeRouter` | Already handles LONG |
| `JudgeProfiler` | Already handles LONG |
| `JudgeEvaluator` | Already handles LONG |
| `ReportGenerator` | Already handles LONG |
| `BenchmarkRegistry` | Run storage, unchanged |
| `BenchmarkRunManifest` | Run metadata, may need LONG extension |
| `Task` schema | May need stage context extension |
| `TaskResult` schema | May need stage fields extension |

---

## 9. Minimum Correct Stage 8 Implementation

### 9.1 What "Minimum Correct" Means

A Stage 8 implementation that:
1. Executes LONG tasks end-to-end
2. Produces valid `TaskResult` with stage metadata
3. Integrates with `RunOrchestrator`
4. Passes all existing tests
5. Has focused new tests
6. Does not break SINGLE, MULTI, or EXEC

### 9.2 Required Files

**New files:**
1. `eb/runners/long_horizon.py` — `LongHorizonRunner` implementation
2. `tests/test_long_horizon_runner.py` — Unit tests

**Modified files:**
1. `eb/runners/__init__.py` — Export `LongHorizonRunner`
2. `eb/runners/orchestration.py` — Add LONG task filtering + execution
3. `eb/core/schema.py` — Add `StageResult` dataclass and LONG fields to `TaskResult`
4. `eb/cli.py` — Add LONG-specific CLI flags (optional for min viable)

### 9.3 CORE Implementation Scope

```python
class LongHorizonRunner(Runner):
    """Runner for ExecutionMode.LONG tasks."""
    
    @property
    def mode(self) -> ExecutionMode:
        return ExecutionMode.LONG
    
    def __init__(
        self,
        adapter: ModelAdapter,
        dispatcher: EvaluatorDispatcher | None = None,
        max_stages: int = 5,
        stage_timeout_s: float = 300.0,
        max_tool_calls: int = 50,
        max_total_time_s: float = 1800.0,
        docker_image: str = "python:3.11-slim",
        max_concurrent: int = 4,
    ) -> None:
        ...
    
    def run(self, task: Task, ctx: RunContext) -> TaskResult:
        """Execute a LONG task with multiple stages."""
        ...
    
    def run_batch(self, tasks: list[Task], ctx: RunContext) -> list[TaskResult]:
        """Execute multiple LONG tasks with bounded concurrency."""
        ...
```

### 9.4 Stage Result Schema

```python
@dataclass
class StageResult:
    stage_index: int
    stage_id: str
    status: str  # "completed", "failed", "recovered", "skipped"
    sandbox_id: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    test_summary: dict[str, Any] | None = None
    diff: str | None = None
    duration_s: float = 0.0
    error: str | None = None
    timestamp: str = ""

class TaskResult(BaseModel):
    # ... existing fields ...
    
    # LONG-specific fields (Stage 8)
    stage_results: list[StageResult] = field(default_factory=list)
    total_stages: int = 0
    completed_stages: int = 0
    failed_stages: int = 0
    recovery_actions: list[str] = field(default_factory=list)
```

---

## 10. Risks

### 10.1 High Risks

| Risk | Mitigation |
|------|------------|
| Stage state management complexity | Start with simple sequential stages, add recovery later |
| Sandbox lifecycle across stages | Reuse `SandboxManager` with persistent sandbox pattern |
| Test fixture creation | No LONG fixtures exist yet; start with minimal synthetic fixtures |
| Schema compatibility | Add optional fields to `TaskResult`, don't break existing schema |

### 10.2 Medium Risks

| Risk | Mitigation |
|------|------------|
| LONG task format ambiguity | Define minimal `stages.json` schema before implementation |
| Evaluation per-stage vs final | Start with final-only evaluation, add per-stage later |
| Recovery semantics | Define clear recovery policy (retry count, fallback) |
| Performance with many stages | Add stage-level timeout, cap total stages |

### 10.3 Low Risks

| Risk | Mitigation |
|------|------------|
| Judge routing for LONG | Already implemented |
| Report generation for LONG | Already has LONG capability label |
| Registry compatibility | LONG runs stored same as other runs |

---

## 11. Tests Required

### 11.1 Unit Tests (`tests/test_long_horizon_runner.py`)

| Test Category | Tests |
|--------------|-------|
| Mode rejection | SINGLE/EXEC/MULTI tasks rejected by LongHorizonRunner |
| Single stage success | One stage, passes, correct result |
| Multi-stage success | Multiple stages, all pass, correct aggregation |
| Stage failure | One stage fails, others continue |
| Stage recovery | Failed stage recovers on retry |
| Max stages reached | Exceeds max_stages, status=FAILED |
| Total timeout | Exceeds max_total_time_s, status=FAILED |
| Adapter error | Model generation fails, error recorded |
| Empty stages | Task with no stages defined |
| Batch empty | Zero tasks returns empty list |
| Batch ordering | Results in submission order |
| Batch isolation | One task failure doesn't affect others |
| Concurrency bounded | max_concurrent respected |
| Metadata completeness | All required fields present in result |
| Score computation | raw_task_score computed correctly |

### 11.2 Integration Tests

| Test | Description |
|------|-------------|
| Orchestrator LONG execution | RunOrchestrator executes LONG tasks alongside SINGLE/EXEC |
| Artifact writing | LONG results written to artifacts correctly |
| Registry update | LONG runs registered correctly |

### 11.3 Existing Tests to Verify Unchanged

All 599 existing tests must continue to pass, especially:
- `tests/test_single_runner.py` — LONG rejection still works
- `tests/test_orchestration.py` — LONG now executed (not skipped)
- `tests/test_core.py` — ExecutionMode.LONG enum still valid
- `tests/test_judge_router.py` — LONG routing still works

---

## 12. Recommended Stage 8 Breakdown

### 8A — LONG Runner Core (This Stage)
- Implement `LongHorizonRunner` with sequential stage execution
- Add `StageResult` dataclass
- Add LONG fields to `TaskResult`
- Integrate into `RunOrchestrator`
- Write unit tests
- **No checkpointing, no recovery, no persistent sandbox**

### 8B — LONG Stage Fixtures
- Define `stages.json` schema
- Create sample LONG task fixtures
- Add fixture loading validation
- Write fixture tests

### 8C — LONG Recovery & Checkpoint
- Add per-stage retry with exponential backoff
- Add checkpoint save/load between stages
- Add recovery action logging
- Write recovery tests

### 8D — LONG Batch Concurrency
- Add `run_batch()` with bounded workers (like MultiRunner)
- Add concurrent LONG execution tests
- Verify result ordering

### 8E — LONG Evaluation
- Implement `long_horizon.py` evaluator
- Add per-stage rubric evaluation
- Add final delivery evaluation
- Write evaluator tests

### 8F — LONG CLI & Reporting
- Add `--max-stages`, `--stage-timeout` CLI flags
- Add LONG section to reports
- Add LONG to comparison output

---

## 13. Implementation Constraints

### Must Do
- LONG tasks must execute through the full pipeline (load → run → evaluate → score → artifact)
- LONG must not break SINGLE, MULTI, or EXEC
- LONG must preserve result ordering in batch mode
- LONG must use the existing sandbox infrastructure (not create new abstractions)
- LONG must follow the existing runner pattern (extends `Runner`, implements `run()` and `run_batch()`)

### Must Not Do
- Do NOT modify `ExecutionMode` enum
- Do NOT modify `Sandbox` interface
- Do NOT modify Docker or OpenSandbox backends
- Do NOT add GPU support
- Do NOT add Kubernetes support
- Do NOT add checkpointing (defer to 8C)
- Do NOT add recovery logic (defer to 8C)
- Do NOT modify CodeBro MCP
- Do NOT change OpenSandbox defaults
- Do NOT make LONG require OpenSandbox (Docker must work)

### Verdict for Stage 8A
**READY FOR IMPLEMENTATION** — The audit is complete. The minimum viable implementation is well-defined:
1. `LongHorizonRunner` with sequential stage execution
2. `StageResult` dataclass
3. LONG fields in `TaskResult`
4. Orchestrator integration
5. 15+ unit tests
