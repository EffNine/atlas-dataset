# Stage 8C — LONG Checkpoint & Recovery Architecture

**Date:** 2026-08-16  
**Status:** Design — Not Implemented  
**Prerequisite:** Stage 8B.2 (LOCKED)  
**Scope:** LONG checkpoint/resume for `LongHorizonRunner`

---

## 1. Audit Findings

### 1.1 Current LONG Execution Flow

```
LongHorizonRunner.run(task, ctx)
  │
  ├─ 1. Extract stages from task.context["stages"]
  ├─ 2. Load RepositoryFixture (if repository_id provided)
  ├─ 3. Create ephemeral workspace copy (tempdir)
  ├─ 4. Create sandbox (id generated, container not yet running)
  ├─ 5. Copy fixture into sandbox
  ├─ 6. Execute stages sequentially:
  │     For each stage:
  │       ├─ Build prompt (stage + previous output)
  │       ├─ Call adapter.generate()
  │       ├─ Evaluate with EvaluatorDispatcher
  │       └─ Record StageResult in LongRunContext
  ├─ 7. Collect final response from last StageResult
  ├─ 8. Build TaskResult with stage_results
  ├─ 9. Run final evaluation (LongHorizonEvaluator)
  └─ 10. Cleanup sandbox (stop + destroy)
```

### 1.2 What Exists Today

| Component | State | Persistence |
|-----------|-------|-------------|
| `LongRunContext` | In-memory dataclass | None — lost on process exit |
| `StageResult` | Pydantic model | Written to `TaskResult.stage_results` at end |
| `StageData` | Pydantic model | In task context, serializable |
| `TaskResult` | Pydantic model | Written to `results.jsonl` at end |
| Sandbox workspace | Temp directory on host | Lost on process exit |
| Sandbox container | Docker/OpenSandbox managed | Lost on destroy |
| Checkpoint file | Does not exist | — |

### 1.3 Critical Gaps Identified

1. **No intermediate persistence**: If the process dies mid-task, all stage results are lost.
2. **Ephemeral workspace**: The workspace temp directory is not archived anywhere.
3. **No resume path**: `run()` is a single atomic operation with no break points.
4. **Sandbox ID ephemeral**: `sandbox_id` is generated per-process via MD5 hash of image + timestamp. It cannot be reconstructed from external state.
5. **No checkpoint schema**: Nothing to version or validate against.
6. **Orphaned sandboxes**: If a process dies after `create()` but before `destroy()`, the sandbox becomes an orphan (already handled by `SandboxManager.cleanup_orphans()`).

### 1.4 What Is Already Serializable

All candidate types are Pydantic models or dataclasses with JSON-serializable fields:

- `StageData` — full Pydantic model, already used in task context
- `StageResult` — full Pydantic model, already serialized in `TaskResult`
- `SecurityPolicy` — frozen dataclass with `to_dict()` / `from_dict()`
- `RepositoryFixture` — dataclass with `from_manifest()`
- `LongRunContext` — dataclass, partially serializable (workspace is `Path`)

### 1.5 Security Audit of Checkpoint Contents

| Field | Sensitive? | Decision |
|-------|-----------|----------|
| `task_id`, `run_id` | No | Include |
| `stage_results[].output` | No (model text) | Include |
| `stage_results[].error` | No | Include |
| `stage_results[].token_usage` | No | Include |
| `sandbox_id` | No | Include (for traceability) |
| `workspace_archive_path` | No | Include (relative path) |
| `security_policy` | No | Include (no secrets in policy) |
| `adapter_config` | — | Exclude (never persist credentials) |
| `environment variables` | **Yes** | Exclude |
| `api_keys` | **Yes** | Exclude |
| `raw_response` body content | No | Include (it's the model output) |

The checkpoint must NOT contain:
- API keys or tokens
- Environment variable values
- Adapter connection strings with credentials

Existing `SecurityPolicy` already excludes secrets — `allowed_env` defaults to safe vars only.

---

## 2. Checkpoint Semantics

### 2.1 What a Checkpoint Represents

A checkpoint is a **point-in-time snapshot** of a LONG task execution state, capturing everything needed to resume from a specific stage boundary without re-executing completed stages.

**Authoritative state hierarchy:**

| Priority | Field | Source | Rationale |
|----------|-------|--------|-----------|
| 1 | `checkpoint_schema_version` | Checkpoint file | Determines parsing logic |
| 2 | `task_id` | Task | Immutable identity |
| 3 | `run_id` | RunContext | Immutable identity |
| 4 | `fixture_id` | RepositoryFixture | Anchors workspace restoration |
| 5 | `fixture_hash` | RepositoryFixture.compute_hash() | Verifies fixture integrity |
| 6 | `completed_stages` | `list[StageResult]` | Authoritative record of work done |
| 7 | `next_stage_index` | Integer | Resume point |
| 8 | `prev_response` | String | Context for next stage prompt |
| 9 | `sandbox_id` | String | Traceability only; may be stale |
| 10 | `sandbox_image` | String | For sandbox recreation |
| 11 | `security_policy` | SecurityPolicy | For sandbox recreation |
| 12 | `workspace_archive_path` | Path | For workspace restoration |
| 13 | `workspace_snapshot` | dict[str,str] | SHA-256 of files at checkpoint time |
| 14 | `configuration` | dict | Runner params (max_stages, timeouts, etc.) |
| 15 | `backend` | String | "docker" or "opensandbox" |
| 16 | `created_at` | ISO timestamp | Checkpoint creation time |
| 17 | `checkpoint_version` | String | eb package version at checkpoint time |

### 2.2 Checkpoint Schema (Version 1.0)

```python
class CheckpointV1(BaseModel):
    schema_version: str = "1.0"
    eb_version: str = "0.1.0"
    
    # Identity
    task_id: str
    run_id: str
    repeat_id: str
    
    # Fixture state
    fixture_id: str | None = None
    fixture_hash: str | None = None
    docker_image: str
    
    # Execution state
    completed_stages: list[StageResult] = Field(default_factory=list)
    next_stage_index: int = 0
    prev_response: str = ""
    
    # Sandbox state (traceability)
    sandbox_id: str = ""
    sandbox_image: str = ""
    
    # Workspace state
    workspace_archive_path: str = ""  # Relative to outputs/checkpoints/
    workspace_snapshot: dict[str, str] = Field(default_factory=dict)  # path → sha256
    
    # Security
    security_policy: dict[str, Any] = Field(default_factory=dict)
    
    # Configuration
    configuration: dict[str, Any] = Field(default_factory=dict)
    
    # Backend
    backend: str = "docker"
    
    # Timestamps
    created_at: str
    resumed_from: str | None = None  # Parent checkpoint ID, if any
    
    # Integrity
    checksum: str | None = None  # SHA-256 of serialized payload (excluding checksum field)
```

### 2.3 Schema Versioning Strategy

- `schema_version` is a string ("1.0", "1.1", etc.)
- On load, validate `schema_version` against supported versions
- If version is older but compatible, migrate fields
- If version is newer, reject with clear error
- `eb_version` records the package version for debuggability

**Compatibility rules:**

| Load version | File version | Action |
|-------------|-------------|--------|
| 1.0 | 1.0 | Direct load |
| 1.0 | 0.9 | Migrate: add new optional fields with defaults |
| 1.0 | 1.1 | Reject: "checkpoint_schema_version 1.1 requires eb >= X.Y.Z" |
| 1.0 | unknown | Reject: "unsupported schema_version" |

---

## 3. Sandbox Lifecycle Design

### 3.1 The Core Problem

The current flow creates one sandbox per task and keeps it alive across all stages. On resume, the sandbox may:

- Still exist (process was interrupted but host is up)
- Have been destroyed (cleanup ran on exit)
- Be orphaned (process crashed without cleanup)
- No longer be valid (host restarted, Docker daemon reset)

**Assumption:** Sandbox IDs MUST NOT be assumed valid across process restarts.

### 3.2 Strategy: Hybrid — Archive-Based with Sandbox Recreation

**Recommended approach: C (Sandbox Recreation + Workspace Restoration)**

Rationale:
- Docker has no pause/resume API (OpenSandbox does, but we cannot depend on it)
- Sandbox IDs are ephemeral and cannot be reliably reconstructed
- The workspace is the truly important persistent state (files the model produced)
- Recreating the sandbox is cheap and deterministic
- Archiving the workspace is cheap and deterministic

### 3.3 Sandbox Lifecycle with Checkpoint

```
Phase 1: Initial run
  create sandbox → copy fixture → execute stages → checkpoint → ...
  
Phase 2: Resume (after interruption)
  load checkpoint → discard old sandbox_id → create NEW sandbox
  → restore workspace from archive → continue from next_stage_index
```

### 3.4 Docker vs OpenSandbox Differences

| Aspect | Docker | OpenSandbox |
|--------|--------|-------------|
| Pause/resume API | None | `/v1/sandboxes/{id}/resume` |
| Snapshot API | `docker commit` (heavy) | Native snapshot support |
| Recreate cost | Fast (new container from image) | Fast (new sandbox from image) |
| Workspace restore | `copy_in` from archive | `copy_in` from archive |
| Recommendation | Always recreate on resume | Always recreate on resume |

**Decision:** Both backends use the same recreate-on-resume strategy. Do not use OpenSandbox pause/resume in MVP — it introduces coupling to a specific backend feature and complicates the abstraction.

### 3.5 Workspace Archive Format

On checkpoint, archive the workspace directory:

```
outputs/checkpoints/<run_id>/<task_id>/<checkpoint_id>/
  ├── checkpoint.json        # The checkpoint file
  ├── workspace.tar.gz       # Compressed workspace snapshot
  └── workspace_snapshot.json # File → SHA-256 map (redundant with checkpoint, for quick verify)
```

Archive contents:
- All files in the workspace directory (the temp copy of the fixture)
- Excludes `.git/` (not relevant for benchmark execution)
- Preserves relative paths

On resume:
1. Extract `workspace.tar.gz` to a new temp directory
2. Verify `workspace_snapshot.json` hashes match (integrity check)
3. Create new sandbox
4. Copy restored workspace into sandbox
5. Continue execution from `next_stage_index`

---

## 4. Repository State Strategy

### 4.1 What Must Be Preserved

The workspace is the **authoritative repository state**. It contains:
- Files modified by the model during stage execution
- Any artifacts produced by the model
- The git working tree state (if the fixture is a git repo)

### 4.2 Restoration Integrity

To prevent silent continuation from wrong state:

1. **Fixture hash verification**: On resume, recompute `RepositoryFixture.compute_hash()` and compare against `checkpoint.fixture_hash`. If mismatched, reject resume (TERMINAL).
2. **Workspace snapshot verification**: After extracting the archive, verify SHA-256 hashes of all files against `checkpoint.workspace_snapshot`. If mismatched, log warning but allow (filesystem may have minor timestamp differences; only content hashes matter).
3. **Checkpoint checksum**: The checkpoint file itself has a SHA-256 checksum. Verify on load.

### 4.3 Failure Mode: Fixture Changed

If the fixture source directory has been modified since the checkpoint was created:
- `fixture_hash` mismatch → TERMINAL (cannot trust workspace state)
- Action: Mark task as `CHECKPOINT_INCOMPATIBLE`, write result with error flag

### 4.4 Failure Mode: Workspace Archive Missing

If the checkpoint file exists but the archive is missing:
- Cannot restore workspace → TERMINAL
- Action: Mark task as `CHECKPOINT_CORRUPTED`, write result with error flag

---

## 5. Resume Point Semantics

### 5.1 Resume Algorithm

```
1. Load checkpoint from disk
2. Validate schema version, fixture hash, checkpoint checksum
3. Create new sandbox (ignore old sandbox_id)
4. Restore workspace from archive
5. Copy workspace into sandbox
6. Set next_stage_index = checkpoint.next_stage_index
7. Set prev_response = checkpoint.prev_response
8. Execute stages[next_stage_index:] sequentially
9. Append new StageResults to checkpoint.completed_stages
10. Write updated checkpoint (overwrite)
11. On final stage completion, run final evaluation
12. Cleanup sandbox
13. Delete checkpoint files (clean slate)
```

### 5.2 Exact Resume Point

Given:
- Task has 4 stages: [s1, s2, s3, s4]
- Checkpoint after s2 completes: `completed_stages = [sr1, sr2]`, `next_stage_index = 2`

Resume begins at **Stage 3** (index 2). It does NOT:
- Re-execute stages 1 or 2
- Duplicate StageResults
- Re-call the adapter for stages 1 or 2
- Re-run evaluators for stages 1 or 2

The `completed_stages` list is appended to, not replaced.

### 5.3 Idempotency Guarantee

- **checkpoint()** is idempotent: calling it multiple times at the same point produces the same result (overwrites atomically)
- **resume()** is idempotent: calling it when already at the same `next_stage_index` is a no-op (all stages already completed)
- **Stage completion** is exactly-once: once a StageResult is recorded in `completed_stages`, it is never re-executed on resume

**Tradeoff:** We choose exactly-once logical completion over at-least-once physical execution. If a crash occurs DURING a stage (not at a boundary), that stage will be re-executed on resume. This is acceptable because:
- Checkpoints are saved after each stage completes
- Stage-level crashes are rare (adapter calls are atomic)
- Re-executing a single stage is cheap compared to re-executing all prior stages

---

## 6. Failure Class Matrix

### 6.1 RECOVERABLE Failures

| Failure | Detection | Recovery Action |
|---------|-----------|-----------------|
| Process crash mid-stage | Checkpoint not written for current stage | Resume from last checkpoint, re-execute current stage |
| Host restart | Sandbox gone, checkpoint on disk | Recreate sandbox, restore workspace, resume |
| Sandbox disappearance | `sandbox_id` invalid on resume | Create new sandbox, restore workspace |
| Checkpoint corruption (partial write) | JSON parse error, checksum mismatch | Delete corrupted checkpoint, resume from earlier checkpoint if available, else restart from stage 0 |
| Adapter transient error during stage | Stage status = ERROR | Retry stage (up to max_retries), then mark FAILED |
| Stage timeout | `status == "TIMEOUT"` | Resume from next stage (current stage recorded as TIMEOUT) |

### 6.2 TERMINAL Failures

| Failure | Detection | Action |
|---------|-----------|--------|
| Fixture hash mismatch | `computed_hash != checkpoint.fixture_hash` | Mark task CHECKPOINT_INCOMPATIBLE, do not resume |
| Workspace archive missing | Checkpoint exists, archive file missing | Mark task CHECKPOINT_CORRUPTED, do not resume |
| Checkpoint schema too new | `schema_version > SUPPORTED` | Mark task CHECKPOINT_VERSION_MISMATCH, do not resume |
| Max stages reached | `next_stage_index >= max_stages` | Task already at limit; resume executes zero stages, final eval runs |
| All stages already completed | `next_stage_index >= len(stages)` | No-op resume: task is effectively complete, run final eval |
| Sandbox creation fails on resume | Exception in `sandbox.create()` | Mark task SANDBOX_CREATION_FAILED, cleanup archive |

### 6.3 Recovery Flow

```
Load checkpoint
  │
  ├─ Schema version invalid? ──→ TERMINAL: CHECKPOINT_VERSION_MISMATCH
  │
  ├─ Checksum mismatch? ──→ Try previous checkpoint? ──→ Yes: load previous
  │                            │
  │                           No: TERMINAL: CHECKPOINT_CORRUPTED
  │
  ├─ Fixture hash mismatch? ──→ TERMINAL: CHECKPOINT_INCOMPATIBLE
  │
  ├─ Workspace archive missing? ──→ TERMINAL: CHECKPOINT_CORRUPTED
  │
  ├─ Sandbox creation fails? ──→ TERMINAL: SANDBOX_CREATION_FAILED
  │
  └─ All checks pass ──→ Resume execution
         │
         ├─ next_stage_index >= len(stages)? ──→ No-op: run final eval only
         │
         └─ Execute remaining stages
                │
                ├─ Stage timeout → Record TIMEOUT, continue
                ├─ Stage error → Retry (if retries remaining) → Record ERROR
                └─ All stages done → Final eval → Cleanup checkpoint
```

---

## 7. Idempotency Model

### 7.1 Checkpoint writes

Checkpoints are written **after** each stage completes successfully. The write is atomic:

1. Write to temp file in same directory
2. Compute checksum
3. `os.replace()` to final path

This ensures a crash during write produces either the old checkpoint or the new one — never a partially written file.

### 7.2 Resume safety

Resume checks `next_stage_index` before executing any stage. If `next_stage_index >= len(stages)`, it returns immediately with a no-op result (final eval still runs).

### 7.3 Duplicate resume protection

If `resume()` is called when the task is already complete (`next_stage_index >= len(stages)`), the runner detects this and returns the existing result without re-execution. The checkpoint file is cleaned up.

### 7.4 Stage completion immutability

Once a `StageResult` is in `completed_stages`, it is never modified. New results are appended. This prevents corruption from partial writes.

---

## 8. Versioning

### 8.1 Checkpoint Schema Version

```python
SUPPORTED_SCHEMA_VERSIONS = {"1.0"}
CURRENT_SCHEMA_VERSION = "1.0"
```

### 8.2 EB Package Version

Recorded in `checkpoint.eb_version`. Used for debuggability, not enforcement.

### 8.3 Configuration Compatibility

The checkpoint stores `configuration` dict with all runner parameters. On resume:
- Compare stored config with current runner config
- If `max_stages` differs: allow (resume with new limit)
- If `stage_timeout_s` differs: allow (use new timeout for remaining stages)
- If `docker_image` differs: TERMINAL (workspace was built for different image)
- If `backend` differs: TERMINAL (sandbox recreation semantics differ)

### 8.4 Migration Path

For schema version 1.0 → 1.1 (future):
- Add new optional fields with defaults
- Existing 1.0 checkpoints load with defaults for new fields
- No data loss

---

## 9. Security

### 9.1 What Is Excluded from Checkpoints

- **API keys / tokens**: Never persisted. The adapter is reconstructed on resume from the original factory.
- **Environment variables**: Never persisted. Only `SecurityPolicy.allowed_env` names are stored, not values.
- **Adapter connection strings**: Never persisted.
- **Model responses containing PII**: Allowed (they are benchmark outputs, not secrets).

### 9.2 Checkpoint File Permissions

Checkpoints are written with mode `0600` (owner read/write only) to prevent other users from reading model outputs.

### 9.3 Checkpoint Storage Location

Only approved write roots may be used:
- `outputs/checkpoints/<run_id>/` — primary location
- Must pass `eb.paths.is_write_safe()` check

### 9.4 Checkpoint Cleanup

On successful task completion, all checkpoint files are deleted. Only failed/interrupted tasks retain checkpoints.

---

## 10. Test Plan

### 10.1 MVP Tests (Required)

| # | Test | Description | Category |
|---|------|-------------|----------|
| 1 | `test_checkpoint_after_stage_1` | Save checkpoint after stage 1 completes | Unit |
| 2 | `test_resume_at_stage_2` | Resume from checkpoint, execute remaining stages | Unit |
| 3 | `test_checkpoint_after_multiple_stages` | Save checkpoint after stages 1+2 | Unit |
| 4 | `test_process_interruption_simulation` | Mock crash between stages, verify resume skips completed | Unit |
| 5 | `test_sandbox_disappearance` | Sandbox ID invalid on resume, verify new sandbox created | Unit |
| 6 | `test_corrupted_checkpoint_json` | Malformed checkpoint.json → TERMINAL | Unit |
| 7 | `test_duplicate_resume` | Resume when already complete → no-op | Unit |
| 8 | `test_fixture_version_mismatch` | Fixture hash doesn't match → TERMINAL | Unit |
| 9 | `test_configuration_mismatch_backend` | Backend changed → TERMINAL | Unit |
| 10 | `test_cleanup_on_success` | Checkpoint deleted after full completion | Unit |
| 11 | `test_docker_backend_resume` | Full checkpoint/resume with Docker sandbox | Integration |
| 12 | `test_opensandbox_backend_resume` | Full checkpoint/resume with OpenSandbox | Integration (skip if no backend) |

### 10.2 Deferred Tests (Post-MVP)

| # | Test | Description | Category |
|---|------|-------------|----------|
| 13 | `test_checkpoint_schema_migration` | Load 0.9 checkpoint with 1.0 loader | Unit |
| 14 | `test_workspace_archive_integrity` | Verify SHA-256 hashes after extraction | Unit |
| 15 | `test_concurrent_checkpoint_writes` | Two checkpoints written simultaneously | Unit |
| 16 | `test_partial_checkpoint_deletion` | Archive missing but checkpoint exists | Unit |
| 17 | `test_stage_timeout_with_checkpoint` | Timeout mid-stage, resume retries | Unit |
| 18 | `test_max_stages_with_checkpoint` | Checkpoint at max_stages boundary | Unit |

### 10.3 MVP Scope

Tests 1–12 are MVP. Tests 13–18 are deferred.

---

## 11. MVP Boundary

### 11.1 In Scope (MVP)

- Checkpoint save after each stage completion
- Checkpoint load and resume
- Workspace archive/restore (tar.gz)
- Sandbox recreation on resume (both backends)
- Fixture hash verification
- Basic failure classification (recoverable vs terminal)
- Atomic checkpoint writes
- Checkpoint cleanup on success
- 12 MVP tests

### 11.2 Out of Scope (Deferred)

| Feature | Reason |
|---------|--------|
| Distributed checkpoint storage | No cloud artifact store needed for single-host benchmark |
| Automatic retry on resume | Manual resume via CLI; no auto-retry logic |
| Checkpoint compression tuning | tar.gz is sufficient |
| Incremental workspace diffs | Full archive is simpler and correct |
| Cross-machine migration | Single-host execution assumed |
| Checkpoint garbage collection | Not needed for benchmark scale |
| Checkpoint encryption | Not required for benchmark outputs |
| OpenSandbox pause/resume API | Adds backend coupling; recreate is simpler |
| Docker commit for workspace | Heavy; tar.gz archive is faster |
| Multi-task checkpoint (batch) | Batch resume deferred to 8D |

---

## 12. Final Design

### 12.1 Checkpoint Model

```
CheckpointV1 (Pydantic BaseModel)
  ├─ schema_version: str          # "1.0"
  ├─ eb_version: str              # "0.1.0"
  ├─ task_id: str
  ├─ run_id: str
  ├─ repeat_id: str
  ├─ fixture_id: str | None
  ├─ fixture_hash: str | None
  ├─ docker_image: str
  ├─ completed_stages: list[StageResult]
  ├─ next_stage_index: int
  ├─ prev_response: str
  ├─ sandbox_id: str
  ├─ sandbox_image: str
  ├─ workspace_archive_path: str
  ├─ workspace_snapshot: dict[str, str]
  ├─ security_policy: dict[str, Any]
  ├─ configuration: dict[str, Any]
  ├─ backend: str
  ├─ created_at: str
  ├─ resumed_from: str | None
  └─ checksum: str | None
```

### 12.2 State Authority

| State | Authoritative Source |
|-------|---------------------|
| Completed stages | `checkpoint.completed_stages` (disk) + `LongRunContext.stage_results` (memory) |
| Resume point | `checkpoint.next_stage_index` |
| Workspace state | `workspace.tar.gz` archive on disk |
| Sandbox state | Recreated on resume from `sandbox_image` + `security_policy` |
| Fixture integrity | `checkpoint.fixture_hash` vs recomputed hash |
| Checkpoint integrity | `checkpoint.checksum` vs computed checksum |

### 12.3 Persistence Strategy

**Directory layout:**
```
outputs/checkpoints/
  └── <run_id>/
        └── <task_id>/
              └── <checkpoint_id>.ckpt/
                    ├── checkpoint.json      # CheckpointV1 serialized
                    ├── workspace.tar.gz     # Compressed workspace
                    └── workspace_snapshot.json  # path → sha256 (for quick verify)
```

**Checkpoint ID:** `<stage_index:03d>-<timestamp>.ckpt` (e.g., `002-20260816T143000Z.ckpt`)

**Write protocol:**
1. Write `checkpoint.json` to temp file
2. Compute checksum
3. Write `workspace.tar.gz`
4. `os.replace()` temp → final path (atomic)
5. Write `workspace_snapshot.json`

**Read protocol:**
1. Load `checkpoint.json`
2. Verify checksum
3. Verify schema version
4. Verify fixture hash
5. Extract `workspace.tar.gz`
6. Verify workspace snapshot hashes (warning on mismatch, not fatal)

### 12.4 Repository State Strategy

**On checkpoint:**
1. Compute SHA-256 of every file in workspace (excluding `.git/`)
2. Create `workspace.tar.gz` of the entire workspace directory
3. Store file list + hashes in `workspace_snapshot`

**On resume:**
1. Extract `workspace.tar.gz` to new temp directory
2. Recompute hashes and compare with `workspace_snapshot`
3. If hashes match → workspace restored correctly
4. If hashes don't match → log warning, proceed (may be due to filesystem metadata differences)
5. Copy restored workspace into new sandbox

**Integrity guarantee:** The fixture hash check prevents using a checkpoint with a modified fixture. The workspace archive preserves the exact file state at checkpoint time.

### 12.5 Sandbox Strategy

**Always recreate on resume.** Do not attempt to reuse stale sandbox IDs.

Flow:
1. Load checkpoint → get `sandbox_image`, `security_policy`, `backend`
2. Create NEW sandbox with same image and policy
3. Copy restored workspace into new sandbox
4. Continue execution

**Docker:** New container from same image, new workspace bind mount.
**OpenSandbox:** New sandbox from same image, new workspace via `copy_in`.

### 12.6 Resume Algorithm

```python
def resume(self, task: Task, ctx: RunContext, checkpoint_path: Path) -> TaskResult:
    # 1. Load checkpoint
    checkpoint = CheckpointV1.load(checkpoint_path)
    
    # 2. Validate
    self._validate_checkpoint(checkpoint, task)
    
    # 3. Recreate sandbox
    sandbox_id = self._create_sandbox(checkpoint)
    
    # 4. Restore workspace
    workspace = self._restore_workspace(checkpoint)
    
    # 5. Copy into sandbox
    self._sandbox_manager.copy_in(sandbox_id, workspace, fixture.workspace_path)
    
    # 6. Build context from checkpoint
    long_ctx = LongRunContext(
        run_id=ctx.run_id,
        task_id=task.id,
        repeat_id=checkpoint.repeat_id,
        workspace=workspace,
        stages=self._extract_stages(task),
        stage_results=list(checkpoint.completed_stages),  # Preserve completed
        sandbox_id=sandbox_id,
        sandbox_image=checkpoint.sandbox_image,
        start_time=time.time(),
        current_stage_index=checkpoint.next_stage_index,
    )
    
    # 7. Execute remaining stages
    self._execute_stages(task, long_ctx)
    
    # 8. Final evaluation
    result = self._build_result(task, long_ctx, checkpoint)
    
    # 9. Cleanup
    self._cleanup(sandbox_id)
    self._cleanup_checkpoint(checkpoint_path)
    
    return result
```

### 12.7 Failure/Recovery Matrix

| Scenario | Class | Recovery |
|----------|-------|----------|
| Process crash after stage N | RECOVERABLE | Resume from checkpoint N, execute N+1..end |
| Process crash during stage N | RECOVERABLE | Resume from checkpoint N-1, re-execute stage N |
| Host restart | RECOVERABLE | Sandbox gone → recreate, restore workspace, resume |
| Sandbox container died | RECOVERABLE | Recreate sandbox, restore workspace, resume |
| Sandbox corruption detected | RECOVERABLE | Destroy corrupt sandbox, recreate fresh, resume |
| Checkpoint JSON parse error | TERMINAL | CHECKPOINT_CORRUPTED |
| Checkpoint checksum mismatch | TERMINAL | CHECKPOINT_CORRUPTED |
| Fixture hash mismatch | TERMINAL | CHECKPOINT_INCOMPATIBLE |
| Workspace archive missing | TERMINAL | CHECKPOINT_CORRUPTED |
| Schema version too new | TERMINAL | CHECKPOINT_VERSION_MISMATCH |
| Backend mismatch | TERMINAL | CHECKPOINT_INCOMPATIBLE |
| Docker image unavailable | TERMINAL | SANDBOX_CREATION_FAILED |
| All stages already completed | RECOVERABLE (no-op) | Run final eval only, delete checkpoint |
| Stage timeout | RECOVERABLE | Record TIMEOUT, continue to next stage |
| Adapter error (transient) | RECOVERABLE | Retry stage once, then record ERROR |
| Max stages reached | RECOVERABLE (no-op) | Execute zero remaining stages, final eval |

### 12.8 Idempotency Model

| Operation | Idempotent? | Guarantee |
|-----------|------------|-----------|
| `checkpoint()` | Yes | Overwrites atomically; crash during write produces valid old or new checkpoint |
| `resume()` when complete | Yes | No-op: detects `next_stage_index >= len(stages)`, runs final eval, cleans up |
| `resume()` when incomplete | Exactly-once logical | Completed stages never re-executed; current stage may re-execute if crash occurred mid-stage |
| Stage completion | Exactly-once | StageResult appended only after successful evaluation |
| Checkpoint cleanup | Yes | `missing_ok=True` on delete |

**Tradeoff documented:** We accept at-least-once physical execution of the current (incomplete) stage on resume, but exactly-once logical completion of all prior stages. This is the minimum correct behavior — full at-least-once for all stages would require per-sub-operation checkpoints, which is unnecessary complexity for the benchmark use case.

### 12.9 Versioning

```python
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})
CURRENT_SCHEMA_VERSION = "1.0"
```

**Load behavior:**
```python
def load(path: Path) -> "CheckpointV1":
    data = json.loads(path.read_text())
    version = data.get("schema_version", "0.0")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        if version < CURRENT_SCHEMA_VERSION:
            return _migrate_v0_to_v1(data)
        raise CheckpointVersionError(...)
    return CheckpointV1.model_validate(data)
```

**Future migration (1.0 → 1.1):** Add new optional fields, provide `_migrate_v1_to_v2()`.

### 12.10 Security Summary

- No secrets in checkpoints (verified by code review)
- Checkpoint files mode `0600`
- Checkpoint path within `outputs/` (approved write root)
- Adapter credentials reconstructed from factory on resume, never from checkpoint
- Workspace archive contains only benchmark-derived file content (no host filesystem leakage)

### 12.11 Test Plan (MVP)

**File:** `tests/test_long_horizon_checkpoint.py`

| Test | What It Verifies |
|------|-----------------|
| `test_checkpoint_after_stage_1` | Checkpoint file + archive created after first stage |
| `test_resume_at_stage_2` | Resume skips stage 1, executes stage 2 only |
| `test_checkpoint_after_multiple_stages` | Checkpoint captures all completed stages |
| `test_process_interruption_simulation` | Simulated crash → resume produces same final result |
| `test_sandbox_disappearance` | Old sandbox_id invalid → new sandbox created on resume |
| `test_corrupted_checkpoint_json` | Invalid JSON → TERMINAL result |
| `test_duplicate_resume` | Resume when complete → no-op, checkpoint cleaned |
| `test_fixture_version_mismatch` | Changed fixture → TERMINAL |
| `test_backend_mismatch` | Different backend in checkpoint → TERMINAL |
| `test_cleanup_on_success` | Checkpoint files deleted after full run |
| `test_docker_backend_resume` | End-to-end with Docker sandbox |
| `test_opensandbox_backend_resume` | End-to-end with OpenSandbox (skip if unavailable) |

### 12.12 MVP Scope

**Implemented in 8C:**
1. `CheckpointV1` schema in `eb/core/schema.py`
2. `CheckpointManager` in `eb/runners/checkpoint.py` (save/load/validate/cleanup)
3. `LongHorizonRunner.resume()` method
4. Checkpoint save after each stage in `_execute_stages()`
5. CLI flag `--resume <checkpoint_path>` in `RunOrchestrator`
6. 12 MVP tests

**NOT implemented in 8C:**
- Distributed storage
- Automatic retry logic
- Batch checkpoint/resume
- Checkpoint compression tuning
- Schema migration (beyond 1.0)
- Checkpoint encryption
- OpenSandbox pause/resume API usage
- Docker commit usage

### 12.13 Deferred Scope

| Feature | Stage | Reason |
|---------|-------|--------|
| Schema migration (1.0→1.1) | 8E | Low priority; additive changes only |
| Automatic retry on resume | 8D | Complex semantics; manual resume sufficient for MVP |
| Batch checkpoint/resume | 8D | Requires batch concurrency first |
| Checkpoint garbage collection | 8F | Operational concern; not needed for benchmark scale |
| Incremental workspace diffs | Future | Full archive is simpler and correct |
| Cross-machine migration | Future | Single-host execution assumption |
| Checkpoint encryption | Future | Not required for benchmark outputs |
| OpenSandbox native snapshot | Future | Adds backend coupling |

---

## 13. New Files

| File | Purpose |
|------|---------|
| `eb/core/checkpoint.py` | `CheckpointV1` schema, load/save/validate |
| `eb/runners/checkpoint.py` | `CheckpointManager` — file I/O, archive, cleanup |
| `tests/test_long_horizon_checkpoint.py` | 12 MVP tests |

## 14. Modified Files

| File | Change |
|------|--------|
| `eb/runners/long_horizon.py` | Add `resume()` method, checkpoint save in `_execute_stages()`, `--resume` support |
| `eb/runners/orchestration.py` | Add `--resume` CLI arg handling, pass to runner |
| `eb/core/schema.py` | Add `CheckpointV1` model |

## 15. Verification Strategy

After implementation:
1. `python -m pytest tests/test_long_horizon_checkpoint.py -q` — new tests pass
2. `python -m pytest tests/test_long_horizon_runner.py -q` — no regressions
3. `python -m pytest tests/test_long_horizon_8b.py -q` — no regressions
4. `python -m pytest tests/test_stage_8b2_calibration.py -q` — no regressions
5. `python -m pytest tests/ -q` — all 703 pass, 9 skip, 1 warn (unchanged)

---

*End of Stage 8C Architecture Audit & Design.*
