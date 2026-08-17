# EffNine Benchmark (EB)

Capability benchmark for EffNine models, starting with **atan-v1** (software engineering + agentic specialist).

## Locked design

- EB is separate from Atlas training and the existing evaluation engine.
- Each model lineage uses its own base-model benchmark baseline of 1000.
- Main user-facing metric is an **EB Score** index, not a 0-100 exam score.
- Repeated runs are used to report score stability and Error %.
- Local inference/execution is preferred; repository and agentic tasks run in Docker/OpenSandbox sandboxes.
- AI judging is cloud-only.
- Deterministic evidence outranks rubric evaluation, which outranks AI-judge opinion.
- Execution modes: SINGLE, MULTI, EXEC, LONG.
- atan-v1 is the first engineering target.
- Mira-v1 is a future visual/UI benchmark extension.

## Architecture: Capability vs Execution Mode

EB makes a strict distinction between **capability** (what is being measured) and **execution mode** (how the task is run):

| Concept | Examples | Stored As |
|---------|----------|-----------|
| **Capability** (category) | ARCH, DEBUG, CODE, UNDERSTAND, PLAN, TEST, ADVISORY, JUDGMENT, EVIDENCE, MYENG, AGENT, LONG | Task metadata — `capabilities` list |
| **Execution mode** | SINGLE, MULTI, EXEC, LONG | Task metadata — `mode` field |
| **Partition** | development, validation, private, hidden | Task metadata — `partition` field |
| **Difficulty** | L1, L2, L3, L4, L5 | Task metadata — `difficulty` field |

Tasks are organized by **capability category** in `tasks/<category>/`. The runner filters tasks by their `mode` field at runtime.

## Execution Modes

| Mode | Description |
|------|-------------|
| **SINGLE** | Standalone reasoning / architecture / advisory / judgment tasks. One prompt, one response. |
| **MULTI** | Multi-turn tasks with changing context or requirements. Model maintains conversation state. |
| **EXEC** | Model works inside a repository/environment. Runs in Docker/OpenSandbox sandbox. Code compilation and test execution. |
| **LONG** | Long-horizon engineering scenarios involving multiple stages, failures, requirement changes, recovery, and final delivery. |

## Sandbox Backends

EB supports two sandbox backends for EXEC mode:

### Docker (default)
Direct Docker SDK integration with strict security defaults:
- Read-only root filesystem
- No Docker socket mount
- No host network access
- Non-root user execution
- CPU/memory/PID limits
- Workspace-only filesystem access

### OpenSandbox (Validated Opt-In Alternative)
Control-plane API backend using [OpenSandbox](https://github.com/opensandbox-group/OpenSandbox):
- Network policy via egress sidecar (deny by default)
- CPU/memory limits (PID limits not supported)
- File upload/download via execd API
- Snapshot support
- Isolated execution via bubblewrap namespaces
- **Validated** — 402 tests passing, zero regressions, behavioral parity with Docker confirmed

Select backend via environment variable:
```bash
EB_SANDBOX_BACKEND=docker        # default
EB_SANDBOX_BACKEND=opensandbox   # validated alternative
```

## Scoring

- **Base model = 1000 EB Score**. Each trained model is normalized relative to its own lineage baseline.
- Example: `Qwen2.5-7B-Instruct = 1000`, `atan-v1 = 1284` (1.284x baseline).
- Repeated runs report mean, median, stddev, min, max, and **Error %** (`stddev / mean * 100`).
- Final report format: `EB Score  1284 ± 0.8%`

## Evaluation Authority Hierarchy

For each task, evaluations are applied in this order:

1. **Deterministic evidence (SCORE)** — exact match, compilation, test execution. Authoritative benchmark score.
2. **Reference/rubric evaluation** — rubric-based scoring against reference.
3. **Cloud AI judge (QUALITY)** — provider-agnostic, multi-judge consensus. Supplemental only for LONG tasks.
4. **AI opinion** — not used in production benchmarks.

A code solution that does not compile must not receive a high score merely because an AI judge likes its explanation.

### LONG-Specific: SCORE / OUTCOME / QUALITY

For LONG tasks, the evaluation produces three distinct concepts:

| Concept | Type | Authority | Determines |
|---------|------|-----------|------------|
| **SCORE** | Continuous [0.0, 1.0] | Deterministic (Authority 1) | Authoritative benchmark score |
| **OUTCOME** | Categorical (PASS/PARTIAL/FAIL/NOT_APPLICABLE) | Gate-based (Authority 1) | Terminal gate decision |
| **QUALITY** | Continuous [0.0, 1.0] | Model-judge (Authority 3) | Supplemental quality assessment |

**Key invariants:**
- `SCORE` is deterministic and authoritative — never overridden by judge
- `OUTCOME` is gate-based — FAIL cannot be upgraded by judge
- `QUALITY` is supplemental — never modifies `SCORE` or `OUTCOME`
- `LOW_AGREEMENT` is diagnostic-only — never overrides deterministic results
- Judge cannot override deterministic FAIL
- Quality cannot modify benchmark SCORE

## Cloud AI Judge

- Cloud-only. No local judge models.
- Provider-agnostic: supports OpenAI, Anthropic, Gemini, DeepSeek, and other OpenAI-compatible endpoints.
- Multi-judge consensus supported (Judge A + Judge B + Judge C → aggregated).
- The model being tested must not act as its own judge.

## Benchmark Partitions

| Partition | Description |
|-----------|-------------|
| `development` | Visible to developers, may be used for calibration |
| `validation` | Internal quality check, not for public release |
| `private` | Calibrated but not yet approved for public use |
| `hidden` | Secret eval set, never mixed with training data |

**Critical rule:** Hidden and private partition tasks must never appear in any Atlas training dataset.

## Environment Variables

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

The `.env` file is gitignored — never commit secrets.

### Required for Cloud Judge (Stage 4+)

| Variable | Description | Example |
|----------|-------------|---------|
| `EB_JUDGE_BASE_URL` | OpenAI-compatible judge endpoint | `https://your-conductor-endpoint/v1` |
| `EB_JUDGE_API_KEY` | API key for the judge | (leave empty, set via export) |
| `EB_JUDGE_MODEL` | Judge model name or `auto` | `auto` |

### Required for Local Inference

| Variable | Description | Example |
|----------|-------------|---------|
| `EB_LOCAL_MODEL_PATH` | Path to local model directory | `/models/qwen2.5-7b-instruct` |
| `EB_API_KEY` | API key for openai-compatible adapters | (provider-specific) |

### Sandbox Backend Configuration

| Variable | Description | Example |
|----------|-------------|---------|
| `EB_SANDBOX_BACKEND` | `"docker"` (default) or `"opensandbox"` | `docker` |
| `EB_OPENSANDBOX_BASE_URL` | OpenSandbox server endpoint | `http://localhost:8080` |
| `EB_OPENSANDBOX_API_KEY` | API key for OpenSandbox server | (set via export) |

### Optional Provider Keys

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI provider key |
| `ANTHROPIC_API_KEY` | Anthropic provider key |
| `DEEPSEEK_API_KEY` | DeepSeek provider key |

**Never put API keys in YAML config files.** Config files reference env var names; values come from the environment.

### Security

- Secrets are never printed. Error messages and logs redact values showing only first/last 4 characters.
- The `.env` file is excluded from git.
- Run metadata manifests redact secret fields before writing to disk.

```bash
eb run --model atan-v1 --suite full --repeats 5
eb compare atan-v1 atan-v1.1
eb report --run-id <run-id>
```

## Directory Structure

```
benchmarks/eb/
├── eb/                    # Python package
│   ├── __init__.py
│   ├── cli.py             # CLI entry point
│   ├── paths.py           # Path resolution
│   ├── core/              # Types, schemas, registry, manifest
│   ├── adapters/          # Model inference adapters
│   ├── runners/           # Execution mode runners
│   ├── evaluators/        # Scoring evaluators
│   ├── judges/            # Cloud AI judge
│   ├── sandbox/           # Multi-backend sandbox (Docker + OpenSandbox)
│   ├── scoring/           # EB score computation
│   ├── reports/           # Report generation
│   ├── tasks/             # Task loader and registry
│   └── factory/           # Task generation (future)
├── config/                # Benchmark configuration (YAML)
├── tasks/                 # Task data (organized by capability)
├── repositories/          # Docker/OpenSandbox repo fixtures for EXEC mode
├── outputs/               # Run artifacts (gitignored)
├── metadata/              # EB registry state
├── tests/                 # Test suite
├── docs/                  # Documentation
├── pyproject.toml
└── README.md
```

## Mira-v1 Extension

Mira-v1 (visual/UI/TUI benchmark) is reserved for a future extension. The architecture is designed to support a parallel `visual/` track without coupling visual scoring into the engineering track.

## Current Status

**All Stages 6A–8F complete. OpenSandbox validated. Benchmark infrastructure ready.**

982 tests collected. 402+ passing (OpenSandbox validation: 402 passed, 1 skipped, 0 failed). Zero production code changes during final OpenSandbox validation.

### Stage 6 — EXEC Runner & Docker Sandbox
- **Sandbox interface** (`eb/sandbox/base.py`): Abstract `Sandbox` with lifecycle (`create/start/exec/copy_in/copy_out/collect/stop/destroy`) and `ExecResult`/`SandboxMetadata` types
- **Security policy** (`eb/sandbox/security.py`): Immutable `SecurityPolicy` with safe defaults (no network, no privileged, read-only root, non-root user, finite CPU/memory/PIDs/timeout). Command validation with dangerous-command and dangerous-path detection
- **Docker adapter** (`eb/sandbox/docker.py`): `DockerSandbox` implementation with workspace volume mounting, no Docker socket exposure, resource limits, output truncation
- **Sandbox manager** (`eb/sandbox/manager.py`): `SandboxManager` with backend selection (`EB_SANDBOX_BACKEND`), lifecycle tracking, orphan cleanup, `SandboxExecution` recording
- **EXEC runner** (`eb/runners/repository.py`): `RepositoryRunner` for `ExecutionMode.EXEC` tasks with bounded agent loop, tool protocol (`list_files/read_file/write_file/patch_file/run_command/run_tests`), fixture management, diff/test collection
- **Repository fixtures**: `repositories/` directory with typed `fixture.json` manifest schema, deterministic hash verification, clean workspace copies
- **Schema extensions**: `TaskResult` gains `repository_id`, `repository_hash`, `docker_image`, `sandbox_id`, `tool_calls`, `command_count`, `changed_files`, `test_summary`, `diff`, `timeout_status`
- **Code evaluator extension**: EXEC-aware evaluation scoring from test results and git diff evidence (deterministic, no LLM judge for basic correctness)
- **CLI flags**: `--max-tool-calls`, `--sandbox-timeout`, `--docker-image`
- **Report extension**: EXEC section in human-readable reports (repository, tests, changed files, execution time)
- **Test fixture**: `repositories/fixtures/eb-python-bug-001/` — minimal Python CSV parser with off-by-one bug and pytest suite

### Stage 6A — OpenSandbox Validated
- Multi-backend sandbox architecture with Docker (default) and OpenSandbox
- Backend selection via `EB_SANDBOX_BACKEND` env var
- SDK v0.1.15, Server v0.2.2, localhost:8080, healthy
- Basic lifecycle, file transfer, timeout, security all PASS
- LONG workflow, checkpoint/resume, concurrency all PASS
- Docker/OpenSandbox behavioral parity confirmed
- **402 passed, 1 skipped, 0 failed** — zero production code changes during validation
- Default remains Docker; OpenSandbox is validated opt-in alternative

### Stage 7 — MULTI Runner
- Multi-turn conversation runner with bounded turns
- Turn protocol: `FINAL_ANSWER:` / `CONTINUE:` signals
- Bounded concurrency via `asyncio.Semaphore`
- Stable result ordering, failure isolation
- 31 tests, zero regressions

### Stage 8A — LONG Runner
- Multi-stage engineering workflow runner
- Persistent sandbox/workspace across stages
- Deterministic stage evaluation
- Terminal gate semantics
- 32 tests, zero regressions

### Stage 8B — LONG Fixtures & Evaluation Semantics
- `stages.json` schema with rich stage definitions
- 4 synthetic fixtures (simple-impl, requirement-change, failure-propagation, final-delivery)
- `LongHorizonEvaluator` with terminal-stage dominant scoring
- SCORE/OUTCOME separation: continuous score + gate-based outcome
- `EvaluatorStatus.PARTIAL` added
- `TaskResult.long_outcome` field added
- 42 + 30 = 72 tests, zero regressions
- A-T calibration: 20/20 correct outcomes

### Stage 8C — Checkpoint & Recovery
- `CheckpointV1` schema with SHA-256 integrity
- Workspace archive (`workspace.tar.gz`) with path traversal protection
- Fixture hash validation on resume
- Sandbox recreation (never reuse old sandbox ID)
- Completed stages not re-executed
- Manual `--resume` required (no auto-retry)
- 28 tests, zero regressions
- Limitations: single-host, no batch resume, no schema migration, no encryption

### Stage 8D — LONG Concurrency
- Bounded concurrent batch execution via `asyncio.Semaphore`
- `--long-max-concurrent` CLI flag (default: 1)
- Per-task sandbox/workspace/checkpoint isolation
- Stable result ordering, failure isolation
- Live Docker validation: 8 tasks, max_concurrent=2, zero orphans
- 26 tests, zero regressions

### Stage 8E.1 — LONG Judge
- 8-dimension engineering rubric (correctness, completeness, requirement_adherence, implementation_quality, test_quality, regression_safety, adaptation_quality, final_delivery_quality)
- Gated judge invocation: PASS/PARTIAL invoke judge; FAIL/N/A skip
- QUALITY score supplemental only — never overrides SCORE
- Bounded evidence (12,000 char cap, secrets excluded, ground truth excluded)
- 24 tests, zero regressions

### Stage 8E.2 — LONG Calibration
- Calibration fixture framework
- Human reference label support
- 62 tests passing

### Stage 8E.3 — Judge Agreement & Calibration
- Multi-judge consensus aggregation
- Judge-vs-human agreement metrics
- LOW_AGREEMENT diagnostic flag (diagnostic-only)
- 43 tests passing

### Stage 8F — CLI & Reporting
- `eb run`, `eb compare`, `eb report`, `eb baseline`, `eb status`, `eb calibrate`
- `--resume`, `--sandbox-backend`, `--output-dir`, `--long-max-concurrent` flags
- Run metadata persistence (benchmark version, task set version/hash, model identity, git commit, evaluator config version, sandbox backend/image, rubric version, concurrency, timestamps)
- 70 tests passing
- SCORE/OUTCOME/QUALITY invariants verified

### Not Yet Implemented
- Benchmark factory / adversarial generation — Stage 9+
- Mira-v1 (visual/UI benchmark) — future extension
- Automatic checkpoint retry — deferred
- Batch checkpoint resume — deferred
- Distributed/multi-host execution — deferred
