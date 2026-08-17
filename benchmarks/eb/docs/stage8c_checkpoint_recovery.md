# Stage 8C — LONG Checkpoint & Recovery

**Date:** 2026-08-16  
**Status:** Implemented  
**Prerequisite:** Stage 8B.2 (LOCKED)

---

## 1. Overview

Stage 8C adds checkpoint and manual resume support to `LongHorizonRunner`. A LONG task can now be interrupted mid-execution, have its state saved to disk, and later resumed from the last completed stage boundary.

**Key design decision:** Hybrid archive-based checkpoint with sandbox recreation. Sandboxes are never reused across process restarts — they are always recreated from the archived workspace.

---

## 2. Checkpoint Format

### 2.1 Schema (Version 1.0)

```python
class CheckpointV1(BaseModel):
    schema_version: str           # "1.0"
    eb_version: str               # "0.1.0"
    task_id: str
    run_id: str
    repeat_id: str
    fixture_id: str | None
    fixture_hash: str | None
    docker_image: str
    completed_stages: list[dict]  # Serialized StageResult objects
    next_stage_index: int         # Resume point
    prev_response: str            # Last stage output for prompt context
    sandbox_id: str               # Traceability only (may be stale)
    sandbox_image: str
    workspace_archive_path: str   # "workspace.tar.gz"
    workspace_snapshot: dict[str, str]  # path → sha256
    archive_sha256: str           # SHA-256 of workspace.tar.gz
    security_policy: dict[str, Any]
    configuration: dict[str, Any]
    backend: str                  # "docker" or "opensandbox"
    created_at: str
    resumed_from: str | None
    checksum: str | None          # SHA-256 of serialized payload
```

### 2.2 Integrity

- **Checksum:** Computed over the full model dump (excluding `checksum` field). Verified on load.
- **Archive SHA-256:** Computed over the `workspace.tar.gz` file bytes. Verified on resume.
- **Fixture hash:** Recomputed on resume and compared against stored hash. Rejects mismatched fixtures.

---

## 3. Storage Layout

```
outputs/checkpoints/
  └── <run_id>/
        └── <task_id>/
              └── <timestamp>-<pid>.ckpt/
                    ├── checkpoint.json        # CheckpointV1 serialized
                    ├── workspace.tar.gz       # Compressed workspace snapshot
                    └── workspace_snapshot.json # path → SHA-256 map
```

**File permissions:** All checkpoint files are written with mode `0600` (owner read/write only).

**Atomic writes:** Checkpoint files are written to a temp file first, then renamed. A crash during write produces either the old valid checkpoint or no checkpoint — never a partially written file.

---

## 4. Archive Policy

### 4.1 What Is Archived

The entire workspace directory is archived as `workspace.tar.gz`, containing:
- All files modified by the model during stage execution
- Any artifacts produced by the model
- The git working tree state (if the fixture is a git repo)

### 4.2 What Is Excluded

- `.git/` directories (not relevant for benchmark execution)
- Absolute paths and `../` traversal paths (rejected during both archive and restore)
- Secrets, API keys, environment variable values (never persisted)

### 4.3 Path Safety

During archive:
- Paths are validated with `_is_safe_path()` — rejects absolute paths and `..` components
- `.git/` is excluded

During restore:
- Tar members with absolute paths or `..` components are rejected with `CheckpointValidationError`

---

## 5. Secret Exclusions

Checkpoints explicitly do NOT contain:

| Category | Reason |
|----------|--------|
| API keys / tokens | Never passed to checkpoint; adapter reconstructed from factory on resume |
| Environment variable values | Only `SecurityPolicy.allowed_env` names are stored, not values |
| Adapter connection strings | Never persisted |
| Host filesystem paths outside workspace | Path traversal protection prevents escape |

---

## 6. Integrity Model

Three layers of integrity verification:

1. **Checkpoint file integrity:** JSON parse + schema validation + checksum verification
2. **Archive integrity:** SHA-256 of `workspace.tar.gz` verified against stored `archive_sha256`
3. **Workspace integrity:** File-level SHA-256 hashes verified against `workspace_snapshot` (warning on mismatch, not fatal)

If any layer fails, the checkpoint is rejected and the task returns an ERROR result.

---

## 7. Resume Algorithm

```
1. Load checkpoint from disk
2. Validate schema version
3. Validate checkpoint checksum
4. Validate backend matches runner backend
5. Validate docker image matches
6. Validate fixture hash (if present)
7. Verify archive SHA-256
8. Extract workspace.tar.gz to new temp directory
9. Verify workspace snapshot hashes (warning on mismatch)
10. Create NEW sandbox (never reuse old sandbox_id)
11. Copy restored workspace into sandbox
12. Build LongRunContext with completed_stages preserved
13. Set next_stage_index from checkpoint
14. Execute only remaining stages
15. Append new StageResults to completed list
16. Run final evaluation
17. Cleanup sandbox
18. Delete checkpoint files
```

---

## 8. Sandbox Recreation

**Both Docker and OpenSandbox use the same recreate-on-resume strategy.**

| Aspect | Behavior |
|--------|----------|
| Old sandbox ID | Ignored — never reused |
| New sandbox | Created from `sandbox_image` + `security_policy` stored in checkpoint |
| Workspace | Restored from `workspace.tar.gz` archive |
| Backend | Must match checkpoint backend; mismatch is TERMINAL |

Docker: New container from same image, new workspace bind mount.  
OpenSandbox: New sandbox from same image, workspace restored via `copy_in`.

---

## 9. Failure Semantics

### 9.1 Recoverable (Manual Resume)

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Process crash | Checkpoint exists on disk | Resume from last checkpoint |
| Host restart | Sandbox gone, checkpoint on disk | Recreate sandbox, restore workspace, resume |
| Sandbox disappearance | `sandbox_id` invalid on resume | Create new sandbox, restore workspace |
| Transient adapter error | Stage status = ERROR | Retry stage on resume |
| Timeout | Stage status = TIMEOUT | Continue from next stage |

### 9.2 Terminal

| Failure | Action |
|---------|--------|
| Fixture hash mismatch | CHECKPOINT_INCOMPATIBLE — do not resume |
| Missing workspace archive | CHECKPOINT_CORRUPTED — do not resume |
| Unsupported schema version | CHECKPOINT_VERSION_MISMATCH — do not resume |
| Backend mismatch | CHECKPOINT_INCOMPATIBLE — do not resume |
| Docker image unavailable | SANDBOX_CREATION_FAILED — do not resume |
| Corrupted checkpoint (bad JSON/checksum) | CHECKPOINT_CORRUPTED — do not resume |
| Invalid archive paths | CHECKPOINT_CORRUPTED — do not resume |

**Recoverable does NOT mean automatic retry.** Manual `--resume` is required.

---

## 10. Idempotency

| Operation | Guarantee |
|-----------|-----------|
| `checkpoint()` | Idempotent — overwrites atomically |
| `resume()` when complete | Idempotent — no-op, returns existing result |
| `resume()` when incomplete | Exactly-once logical completion — completed stages never re-executed |
| Mid-stage crash | At-least-once physical execution of current stage only |

**Tradeoff documented:** We accept at-least-once physical execution of the current (incomplete) stage on resume, but exactly-once logical completion of all prior stages. Full at-least-once for all stages would require per-sub-operation checkpoints, which is unnecessary complexity.

---

## 11. Limitations

| Limitation | Reason |
|------------|--------|
| No automatic retry | Manual `--resume` required |
| Single-host only | No distributed checkpoint storage |
| No batch resume | Batch concurrency deferred to 8D |
| No schema migration | Only v1.0 supported |
| No encryption | Benchmark outputs are not secrets |
| No cross-machine migration | Same-host execution assumed |
| No OpenSandbox pause/resume | Backend coupling avoided; recreate is simpler |

---

## 12. Files Changed

| File | Change |
|------|--------|
| `eb/core/checkpoint.py` | New — `CheckpointV1` model, exceptions, schema versioning |
| `eb/runners/checkpoint.py` | New — `CheckpointManager` for I/O, archiving, validation |
| `eb/runners/long_horizon.py` | Modified — `resume()` method, checkpoint save, `output_root` param |
| `eb/runners/orchestration.py` | Modified — `--resume` parameter, per-task resume dispatch |
| `tests/test_long_horizon_checkpoint.py` | New — 28 tests for checkpoint/resume |
| `docs/stage8c_checkpoint_recovery.md` | New — this document |

---

## 13. Test Results

```
731 passed, 9 skipped, 1 warning
```

Baseline: 703 passed, 9 skipped, 1 warning.  
New: +28 tests, 0 regressions.
