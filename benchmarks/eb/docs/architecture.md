# EB Architecture

## Overview

The EffNine Benchmark (EB) is a capability benchmark system for measuring
software engineering proficiency in models such as `atan-v1`. It is a
distinct subsystem from the Atlas `evaluation_engine/` — it measures
model capability rather than dataset quality.

## Key Architectural Distinctions

### Capability vs Execution Mode

EB separates **what** is being measured from **how** it is run:

- **Capability** (ARCH, DEBUG, CODE, UNDERSTAND, PLAN, TEST, ADVISORY,
  JUDGMENT, EVIDENCE, MYENG, AGENT, LONG) is stored as task metadata.
  Tasks are organized by capability in `tasks/<category>/`.

- **Execution mode** (SINGLE, MULTI, EXEC, LONG) is also task metadata.
  The runner selects the appropriate executor based on the `mode` field.

This means a single capability directory (e.g. `tasks/architecture/`)
may contain tasks with different execution modes.

### Deterministic > Rubric > Cloud Judge

The evaluation authority hierarchy ensures that hard evidence always
trumps opinion:

1. **Deterministic evidence (SCORE)** — exact output match, code compilation,
   test execution. These are binary and reproducible. Authoritative benchmark score.
2. **Rubric evaluation** — scored against a reference rubric. Useful
   for open-ended responses where exact match is impossible.
3. **Cloud AI judge (QUALITY)** — provider-agnostic, multi-judge consensus.
   Used only for subjective dimensions where no deterministic signal
   exists. Supplemental for LONG tasks; never overrides SCORE.
4. **AI opinion** — not used in production benchmarks.

### LONG Evaluation: SCORE / OUTCOME / QUALITY

For LONG tasks, three distinct evaluation concepts are produced:

| Concept | Type | Authority Level | Role |
|---------|------|----------------|------|
| **SCORE** | Continuous [0.0, 1.0] | 1 (Deterministic) | Authoritative benchmark score |
| **OUTCOME** | Categorical (PASS/PARTIAL/FAIL/NOT_APPLICABLE) | 1 (Gate-based) | Terminal gate decision |
| **QUALITY** | Continuous [0.0, 1.0] | 3 (Model-judge) | Supplemental quality assessment |

**Invariants:**
- `SCORE` is deterministic and authoritative — never overridden by judge
- `OUTCOME` is gate-based — FAIL cannot be upgraded by judge
- `QUALITY` is supplemental — never modifies `SCORE` or `OUTCOME`
- `LOW_AGREEMENT` is diagnostic-only — never overrides deterministic results
- Judge cannot override deterministic FAIL
- Quality cannot modify benchmark SCORE

## Subsystems

### core/
- `types.py` — Enum definitions (ExecutionMode, Difficulty, Capability,
  JudgeMode, BenchmarkPartition)
- `schema.py` — Pydantic data models (Task, TaskResult, BenchmarkRun,
  BaselineRecord, CapabilityScore)
- `registry.py` — BenchmarkRegistry for persistent run history
- `manifest.py` — BenchmarkRunManifest for reproducibility tracking

### adapters/
Model inference backends with framework-agnostic contract.
- `base.py` — Abstract ModelAdapter interface (ModelRequest, ModelResponse, TokenUsage, AdapterMetadata)
- `local.py` — Local inference with backend abstraction (transformers supported, vLLM ready)
- `openai_compatible.py` — OpenAI-compatible HTTP API adapter
- `factory.py` — Adapter factory resolving model configs to adapter instances

### runners/
Execution mode handlers.
- `base.py` — Abstract Runner interface, RunContext, TaskStatus
- `single.py` — SINGLE mode (standalone reasoning) — Stage 2
- `multi.py` — MULTI mode (multi-turn conversation with bounded workers) — Stage 7
- `orchestration.py` — Run orchestration: task loading, filtering, execution, artifacts, registry
- `repository.py` — EXEC mode (Docker/OpenSandbox sandbox) — Stage 6
- `long_horizon.py` — LONG mode (multi-stage) — Stages 8A–8F

### MULTI Runner (Stage 7)

The MULTI runner handles multi-turn tasks where the model maintains conversation
state across turns. Key properties:

- **Turn protocol**: `CONTINUE:<next_prompt>` requests another turn;
  `FINAL_ANSWER:<answer>` terminates. Any other text is treated as final.
- **Bounded concurrency**: `run_batch()` uses `asyncio.Semaphore` to limit
  concurrent tasks to `max_concurrent` (default 4).
- **Result ordering**: Results are returned in stable submission order,
  regardless of completion order.
- **Failure isolation**: One task failure does not affect others.
- **Turn metadata**: Each result preserves per-turn latency, token usage,
  and status in `execution_metadata["turns"]`.
- **Timeout handling**: Reaching `max_turns` without `FINAL_ANSWER` sets
  status to `FAILED` with `max_turns_reached` flag.
- **Backend-agnostic**: The MULTI runner does not depend on Docker or
  OpenSandbox internals. It uses the model adapter directly.

**Configuration** (via `RunOrchestrator`):
- `multi_max_turns` (default 10) — maximum turns per task
- `multi_turn_timeout` (default 120.0s) — per-turn timeout
- `multi_max_total_time` (default 600.0s) — total task timeout
- `multi_max_concurrent` (default 4) — max concurrent batch workers

See `docs/stage7_multi_runner.md` for full documentation.

### evaluators/
Scoring evaluators following the authority hierarchy.
- `base.py` — Abstract Evaluator interface with authority levels
- `exact.py` — Exact match with explicit normalization — Stage 3
- `code.py` — Code-specific (syntax, artifact match, safe test commands) — Stage 3
- `evidence.py` — Evidence-based verification (claims, facts) — Stage 3
- `rubric.py` — Structured rubric with deterministic checks and PENDING_JUDGE — Stage 3
- `dispatcher.py` — Registry-based evaluator dispatch — Stage 3
- `judge.py` — Cloud AI judge — Stage 4

### judges/
Cloud AI judge abstraction (Stage 4+).
- `client.py` — Provider-agnostic judge client
- `consensus.py` — Multi-judge aggregation

**Stage 4 readiness:** Environment configuration via `eb/env_config.py` defines the stable contract:
- `EB_JUDGE_BASE_URL` — OpenAI-compatible judge endpoint
- `EB_JUDGE_API_KEY` — API key (never printed, redacted in logs)
- `EB_JUDGE_MODEL` — Judge model name or `auto`

### config/
Benchmark configuration files (YAML).
- `models.yaml` — Model adapter configurations
- `judges.yaml` — Judge provider configuration
- `benchmark.yaml` — Benchmark-level settings
- `scoring.yaml` — Scoring parameters

Secrets are NEVER stored in YAML config files. Config references env var names; values come from environment.

### sandbox/
Multi-backend container management for EXEC mode.

#### Backend Architecture

```
EB Sandbox Interface (base.py)
      │
      ├── DockerSandbox (docker.py)
      │     └── Direct Docker SDK
      │
      └── OpenSandboxBackend (opensandbox.py)
            └── OpenSandbox control-plane API
                  └── Underlying Docker/Kubernetes runtime
```

Both backends implement the same `Sandbox` abstract interface.
`RepositoryRunner` and `SandboxManager` are backend-agnostic.

#### Backend Selection

```bash
# Default: Docker
EB_SANDBOX_BACKEND=docker

# Alternative: OpenSandbox
EB_SANDBOX_BACKEND=opensandbox
EB_OPENSANDBOX_BASE_URL=http://localhost:8080
EB_OPENSANDBOX_API_KEY=your-api-key
```

#### Docker Backend
- Direct Docker SDK integration
- Read-only root filesystem
- No Docker socket mount
- No host network access
- Non-root user execution
- CPU/memory/PID limits
- Workspace-only filesystem access
- Output size limits

#### OpenSandbox Backend (Validated Opt-In Alternative)
- Control-plane API to OpenSandbox server (SDK v0.1.15, Server v0.2.2)
- Network policy via egress sidecar (deny by default)
- CPU/memory limits (no PID limits)
- File upload/download via execd API
- Snapshot support
- Isolated execution via bubblewrap namespaces
- API key authentication
- **Validated**: 402 tests passing, zero regressions, behavioral parity with Docker confirmed
- Default remains Docker; OpenSandbox is opt-in alternative

See `docs/opensandbox_integration_report.md` for detailed comparison.
