# Stage 8B — LONG Benchmark Fixtures & Evaluation Semantics

**Date:** 2026-08-16  
**Status:** Implemented  
**Prerequisite:** Stage 8A LONG Runner Core (locked)

---

## 1. LONG Task Semantics

### 1.1 Definition

LONG is a **multi-stage engineering workflow** where:

- A task is decomposed into ordered stages
- Each stage executes within the **same persistent sandbox/workspace**
- Repository changes made in Stage N are visible in Stage N+1
- Each stage has its own prompt, evaluation criteria, and expected artifacts
- Stages may have dependencies on previous stages
- Requirements may change between stages
- A terminal stage defines the final delivery gate
- Failures at any stage may terminate the workflow

### 1.2 What LONG Is NOT

| Concept | LONG vs MULTI |
|---------|---------------|
| State | Stage artifacts + filesystem vs turn history |
| Sandbox | Required for repository continuity vs not required |
| Evaluation | Per-stage + final delivery vs single final answer |
| Failure | Per-stage with gate semantics vs per-turn error |
| Recovery | Not implemented in 8B (deferred) vs not applicable |

### 1.3 State Authoritativeness

The authoritative state hierarchy for LONG tasks:

1. **StageResult** — per-stage outcome (status, score, output, error)
2. **TaskResult.stage_results** — ordered list of all StageResults
3. **TaskResult.raw_task_score** — aggregated final score
4. **Sandbox workspace** — persistent filesystem state across stages

---

## 2. stages.json Schema

### 2.1 Overview

The `stages.json` schema defines the structure of a LONG task fixture. Each fixture lives in:

```
repositories/fixtures/<fixture-id>/fixture.json
```

The fixture contains:
- Metadata (id, version, language, image, test_command)
- An ordered list of `stages`
- Optional `delivery_criteria` for final evaluation
- Optional `requirement_change` definitions per stage

### 2.2 Stage Schema

```python
class StageData(BaseModel):
    id: str                              # Unique stage identifier
    name: str                            # Human-readable name
    prompt: str                          # The prompt for this stage
    order: int = 0                       # Execution order (auto-sorted if omitted)
    objective: str | None = None         # What this stage aims to achieve
    instructions: str | None = None      # Additional instructions
    expected_artifacts: list[str] = []   # Files that should exist after this stage
    expected_state: dict[str, Any] = {}  # Expected repository state
    evaluation_criteria: list[dict] = [] # Per-stage evaluation checks
    dependencies: list[str] = []         # Stage IDs this stage depends on
    terminal: bool = False               # If True, failure caps final score
    failure_mode: str = "abort"          # "abort" | "continue" | "skip_remaining"
    requirement_change: dict | None = None  # {"from": "...", "to": "..."}
    timeout_s: float | None = None       # Per-stage timeout
    metadata: dict[str, Any] = {}        # Arbitrary metadata
    fixture_id: str | None = None        # Reference to parent fixture
    source_path: str = "source"          # Source directory in fixture
    workspace_path: str = "/workspace"   # Sandbox workspace path
```

### 2.3 Delivery Criteria Schema

```python
delivery_criteria: {
    "checks": [
        {"type": "contains", "value": "required string"},
        {"type": "regex", "value": "pattern"},
        {"type": "file_exists", "value": "path/to/file"},
    ]
}
```

### 2.4 Requirement Change Schema

```python
requirement_change: {
    "from": "previous requirement description",
    "to": "new requirement description",
    "context": {...}  # Optional additional context
}
```

---

## 3. Fixture Types

Four representative synthetic fixtures are provided:

### 3.1 Fixture A — `long-simple-impl`

**Workflow:** Inspect → Implement → Test

```
Stage 1 (inspect):    Read test file, understand requirements
Stage 2 (implement):  Write calculator.py with add/subtract/multiply/divide
Stage 3 (test, terminal): Run pytest, verify all pass
```

**Purpose:** Tests basic multi-stage engineering workflow with a clear terminal gate.

### 3.2 Fixture B — `long-requirement-change`

**Workflow:** Implement v1 → Requirement changes → Adapt → Verify

```
Stage 1 (implement_v1):    Create Counter with increment/get_value
Stage 2 (requirement_change): New req: add decrement/reset/non-negative guard
Stage 3 (verify, terminal): Run tests, verify adapted implementation
```

**Purpose:** Tests the model's ability to adapt to changing requirements mid-workflow.

### 3.3 Fixture C — `long-failure-propagation`

**Workflow:** Implement → Intentional Failure → (Should Not Execute)

```
Stage 1 (implement):       Create validate_email utility
Stage 2 (intentional_failure, terminal): Deliberately fail
Stage 3 (should_not_execute): Should never run
```

**Purpose:** Tests that terminal stage failures correctly terminate the workflow.

### 3.4 Fixture D — `long-final-delivery`

**Workflow:** Implement Service → Test → Verify Delivery

```
Stage 1 (implement):       Create DataService with get_data/is_healthy
Stage 2 (test, terminal):  Run tests, verify delivery criteria
```

**Purpose:** Tests final delivery gate with explicit delivery criteria.

---

## 4. Evaluation Model

### 4.1 LongHorizonEvaluator

The `LongHorizonEvaluator` evaluates a completed LONG task by checking:

1. **Stage completeness** — Were all expected stages executed?
2. **Terminal stage status** — Did the terminal stage pass?
3. **Stage progress** — What fraction of stages succeeded?
4. **Final delivery** — Do delivery criteria match the output?
5. **Requirement adaptation** — Were requirement changes handled?

### 4.2 Evaluator Logic

```python
def evaluate(self, task: Task, result: TaskResult) -> EvaluatorResult:
    # 1. Check for no stage results
    if not result.stage_results:
        return NOT_APPLICABLE

    # 2. Check terminal stage failure
    if terminal_stage_failed:
        return FAIL(score=0.0)

    # 3. Compute progress score
    progress = completed_stages / total_stages

    # 4. Compute terminal score
    terminal = last_stage.score or (1.0 if success else 0.0)

    # 5. Apply weighted formula
    score = progress * 0.7 + terminal * 0.3

    # 6. Apply error penalty
    if error_stages:
        score *= 0.5

    # 7. Apply delivery criteria adjustment
    if delivery_criteria:
        score = score * 0.7 + delivery_score * 0.3

    # 8. Apply requirement change adaptation
    if requirement_changes:
        score = score * 0.8 + adaptation_score * 0.2

    return PASS/FAIL(score)
```

### 4.3 Scoring Model: Terminal-Stage Dominant with Progressive Gating

**Formula:**
```
final_score = progress_score * 0.7 + terminal_score * 0.3
```

Where:
- `progress_score` = fraction of stages completed successfully
- `terminal_score` = score from the final/terminal stage

**Modifiers:**
- Adapter errors: ×0.5 penalty
- Delivery criteria match: +30% weight to delivery score
- Requirement change adaptation: +20% weight to adaptation score

**Rationale:**
- A task where implementation passes but final verification fails should NOT receive a high score
- The terminal stage carries 30% weight as a "gate" — it must pass for a meaningful score
- Progress (70%) rewards partial completion, ensuring early-stage effort is recognized
- Error penalties ensure adapter/sandbox failures are reflected in the score

---

## 5. Requirement Changes

### 5.1 Representation

Requirement changes are encoded in the stage definition:

```json
{
  "id": "adapt",
  "name": "Adapt to New Requirements",
  "prompt": "Update your implementation to support...",
  "requirement_change": {
    "from": "original requirement",
    "to": "updated requirement"
  }
}
```

### 5.2 Evaluation

The evaluator checks:
1. Whether the next stage after a requirement change succeeded
2. Whether the output reflects adaptation (via delivery criteria)

### 5.3 Limitations

For Stage 8B, requirement changes are **declarative only**:
- The fixture specifies what changed
- The evaluator checks if the model adapted
- **No autonomous recovery** is implemented

---

## 6. Files Changed

### New Files
- `eb/evaluators/long_horizon.py` — LongHorizonEvaluator (22KB)
- `tests/test_long_horizon_8b.py` — 42 tests for schema, fixtures, evaluator, scoring
- `repositories/fixtures/long-simple-impl/fixture.json` — Fixture A
- `repositories/fixtures/long-simple-impl/source/calculator.py` — Skeleton
- `repositories/fixtures/long-simple-impl/source/tests/test_calculator.py` — Tests
- `repositories/fixtures/long-requirement-change/fixture.json` — Fixture B
- `repositories/fixtures/long-requirement-change/source/app.py` — Skeleton
- `repositories/fixtures/long-requirement-change/source/tests/test_app.py` — Tests
- `repositories/fixtures/long-failure-propagation/fixture.json` — Fixture C
- `repositories/fixtures/long-failure-propagation/source/utils.py` — Skeleton
- `repositories/fixtures/long-failure-propagation/source/tests/test_utils.py` — Tests
- `repositories/fixtures/long-final-delivery/fixture.json` — Fixture D
- `repositories/fixtures/long-final-delivery/source/service.py` — Implementation
- `repositories/fixtures/long-final-delivery/source/tests/test_service.py` — Tests
- `docs/stage8b_long_fixtures.md` — This document

### Modified Files
- `eb/core/schema.py` — Enhanced StageData with rich fields (objective, instructions, artifacts, dependencies, terminal, failure_mode, requirement_change)

---

## 7. Test Results

```
673 passed, 9 skipped, 1 warning
```

**No regressions** in:
- SINGLE runner (14 tests)
- EXEC runner (15 tests)
- MULTI runner (24 tests)
- Orchestration (5 tests)
- Schema validation
- Evaluator dispatch

---

## 8. Deferred Work

The following are explicitly **NOT implemented** in Stage 8B:

| Feature | Stage | Reason |
|---------|-------|--------|
| Checkpoint/resume | Future | Requires persistent state storage |
| Autonomous recovery | Future | Complex semantic decisions needed |
| Advanced batch concurrency | 8D | Requires scheduler integration |
| Production-scale LONG benchmark | Future | Needs more fixtures and validation |
| Advanced CLI flags | 8C | CLI integration deferred |
| stages.json formal schema file | 8B+ | Current inline format is sufficient for 8B |
| Multi-model judge for LONG | Future | Judge integration deferred |

---

## 9. Verdict

**READY FOR DEVELOPMENT USE**

Stage 8B provides:
- A formal stages.json schema with rich stage definitions
- Four representative synthetic fixtures covering common LONG patterns
- A LONG-specific evaluator with terminal-stage dominant scoring
- Requirement change representation and adaptation tracking
- 42 new tests with zero regressions

Not yet ready for benchmark use because:
- Only 4 synthetic fixtures exist (need more for statistical significance)
- No real-world LONG tasks validated yet
- LONG-specific evaluator needs more calibration against human judges
