# Stage 7 — MULTI Runner Integration

## Overview

Stage 7 implements the MULTI execution mode runner for the EffNine Benchmark (EB).
MULTI tasks are multi-turn conversations where the model maintains state across
multiple turns with potentially changing context or requirements.

## Architecture

```
MULTI Runner
     │
     ▼
ModelAdapter (backend-agnostic)
     │
     ├─→ OpenAI-compatible adapter
     ├─→ Local adapter
     └─→ Any ModelAdapter implementation
```

The MULTI runner does **not** depend on Docker or OpenSandbox internals.
It uses the model adapter directly for each turn.

### Component Diagram

```
RunOrchestrator
     │
     ├─→ SingleRunner   (SINGLE mode)
     ├─→ MultiRunner    (MULTI mode) ← Stage 7
     └─→ RepositoryRunner (EXEC mode)
```

## Turn Protocol

The MULTI runner uses a simple text-based protocol for turn management:

| Signal | Meaning |
|--------|---------|
| `FINAL_ANSWER:<text>` | Terminate conversation, submit answer |
| `CONTINUE:<text>` | Request another turn with follow-up prompt |
| Any other text | Treated as final answer |

Example conversation:
```
User: Design a distributed caching system.
Assistant: CONTINUE:Tell me more about eviction policies.
Assistant: FINAL_ANSWER:LRU with TTL expiration.
```

## Configuration

### MultiRunner Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_turns` | 10 | Maximum conversation turns per task |
| `turn_timeout_s` | 120.0 | Per-turn timeout in seconds |
| `max_total_time_s` | 600.0 | Total task timeout in seconds |
| `max_concurrent` | 4 | Max concurrent tasks in batch mode |

### RunOrchestrator Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `multi_max_turns` | 10 | Passed to MultiRunner |
| `multi_turn_timeout` | 120.0 | Passed to MultiRunner |
| `multi_max_total_time` | 600.0 | Passed to MultiRunner |
| `multi_max_concurrent` | 4 | Passed to MultiRunner |

## Concurrency Model

### Batch Execution

`MultiRunner.run_batch()` executes tasks concurrently with bounded workers:

1. Creates an `asyncio.Semaphore(max_workers)`
2. Each task runs in its own `asyncio.Task`
3. Results are collected in a dict indexed by submission position
4. Final results are returned in stable submission order

### Worker Model

```
Batch (N tasks)
  │
  ├── Worker 1 ──→ Task A ──→ Result[0]
  ├── Worker 2 ──→ Task B ──→ Result[1]
  │                (Semaphore bounds concurrency)
  ├── Worker 1 ──→ Task C ──→ Result[2]
  └── Worker 2 ──→ Task D ──→ Result[3]
```

**Key invariant**: No more than `max_concurrent` tasks execute simultaneously.

## Result Schema

Each `TaskResult` from MULTI execution includes:

```python
{
    "task_id": str,
    "run_id": str,
    "raw_response": str | None,
    "execution_metadata": {
        "status": "SUCCESS" | "FAILED" | "ERROR" | "SKIPPED",
        "repeat_id": str,
        "turn_count": int,
        "max_turns": int,
        "total_time_s": float,
        "total_latency_s": float,
        "token_usage": {
            "prompt_tokens": int,
            "completion_tokens": int,
            "total_tokens": int,
        },
        "turns": [
            {
                "turn_index": int,
                "response_text": str | None,
                "latency_s": float,
                "token_usage": dict,
                "status": str,
                "error": str | None,
                "timestamp": str,
            }
        ],
        "inference_settings": dict,
        "adapter_metadata": dict,
        "timestamp": str,
    },
    "evaluator_results": list[EvaluatorResult],
    "raw_task_score": float | None,
    "flags": list[str],
}
```

## Failure Semantics

| Scenario | Status | Flags |
|----------|--------|-------|
| Normal completion with FINAL_ANSWER | SUCCESS | — |
| Max turns reached without FINAL_ANSWER | FAILED | `max_turns_reached` |
| Total time exceeded | FAILED | `total_time_exceeded` |
| Adapter exception | ERROR | `generation_error: ...` |
| Adapter returns error response | ERROR | `adapter_error: ...` |
| Mode mismatch (not MULTI) | SKIPPED | `mode_mismatch: ...` |
| Batch task exception | ERROR | `batch_error: ...` |

**Isolation guarantee**: A failure in one task never corrupts another task's result.

## Security

- MULTI runner does not create sandboxes
- No filesystem access beyond what the adapter provides
- No network access beyond what the adapter uses
- Token usage is tracked and capped per turn
- Total time is bounded by `max_total_time_s`

### Known Limitations

- No sandbox isolation (unlike EXEC mode)
- No CPU/memory/PID limits at the task level
- Conversation history grows with each turn (potential context overflow)

## Testing

### Unit Tests

```bash
cd benchmarks/eb
python -m pytest tests/test_multi_runner.py -q
```

### Integration Tests

```bash
python -m pytest tests/test_orchestration.py -q
```

### Full Suite

```bash
python -m pytest tests/ -q
```

## Live Validation

### 8 tasks, 2 workers

```python
from eb.runners.multi import MultiRunner
from eb.core.schema import Task
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition
from eb.runners.base import RunContext

tasks = [Task(id=f"EB-MULTI-{i:03d}", category="arch", mode=ExecutionMode.MULTI,
              difficulty=Difficulty.L3, capabilities=[Capability.ARCH],
              prompt=f"Task {i}", partition=BenchmarkPartition.DEVELOPMENT)
         for i in range(8)]

runner = MultiRunner(adapter, max_concurrent=2)
ctx = RunContext(run_id="test", model_name="m", suite="test")
results = runner.run_batch(tasks, ctx)
# len(results) == 8, ordered by submission
```

## Backward Compatibility

- Existing SINGLE and EXEC runners unchanged
- `RunOrchestrator` defaults preserve previous behavior
- MULTI tasks are now discovered and executed (previously skipped)
- The `ExecutionMode.MULTI` enum value already existed

## Files Changed

| File | Change |
|------|--------|
| `eb/runners/multi.py` | New — MultiRunner implementation |
| `eb/runners/__init__.py` | Export MultiRunner, TurnRecord, MultiTurnContext |
| `eb/runners/orchestration.py` | Integrate MULTI tasks into run pipeline |
| `tests/test_multi_runner.py` | New — 31 tests covering all scenarios |
| `tests/test_orchestration.py` | Update test to expect MULTI execution |
| `docs/architecture.md` | Document MULTI runner |
| `docs/stage7_multi_runner.md` | New — this file |

## Verdict

**READY FOR DEVELOPMENT USE**

The MULTI runner is implemented, tested, and integrated into the orchestration
layer. It supports:

- Multi-turn conversation with bounded turns
- Configurable concurrent batch execution
- Stable result ordering
- Failure isolation
- Comprehensive test coverage (31 unit tests)

Next recommended stage: **Stage 8 — LONG runner integration** (multi-stage
engineering scenarios with multiple phases).
