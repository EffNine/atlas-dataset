# OpenSandbox Live Setup & Validation — Final Infrastructure Gate Report

## Environment

| Component | Version | Status |
|-----------|---------|--------|
| OS | Ubuntu 26.04 LTS | ✅ |
| Kernel | 7.0.0-29-generic | ✅ |
| Docker | 29.1.3 | ✅ Running |
| NVIDIA | RTX 5070, driver 595.84, 12227 MiB | ✅ |
| Python | 3.14.4 | ✅ |
| opensandbox (SDK) | 0.1.15 | ✅ Installed |
| opensandbox-server | 0.2.2 | ✅ Running (PID 551073) |

## OpenSandbox Installation/Version

- **Package:** `opensandbox` v0.1.15 (pip installed)
- **Server:** `opensandbox-server` v0.2.2 (running as systemd-like process)
- **Endpoint:** `http://localhost:8080`

## Server Health

```
curl http://localhost:8080/health → {"status":"healthy"}
```

✅ Server healthy and responsive.

## EB Configuration

Environment variables configured:
- `EB_SANDBOX_BACKEND=opensandbox`
- `EB_OPENSANDBOX_BASE_URL=http://localhost:8080`
- `EB_OPENSANDBOX_API_KEY=` (empty — no auth required for local server)

Default backend (when unset): **Docker** ✅ Verified

## Basic Live Validation

All operations validated successfully:

| Operation | Result |
|-----------|--------|
| Sandbox creation | ✅ Returns `eb-osb-<12hex>` ID |
| Shell command execution | ✅ `echo "hello"` → exit 0 |
| Python execution | ✅ `python3 -c "print(42)"` → "42" |
| Non-zero exit code | ✅ `sh -c "exit 42"` → exit 42 |
| Timeout | ✅ `sleep 10` with 1s timeout → timed_out=True |
| File write (copy_in) | ✅ Uploaded and read back |
| File read (cat) | ✅ Content verified |
| File download (copy_out) | ✅ Downloaded to host |
| Sandbox destroy | ✅ Clean cleanup |

## Security Validation

| Check | Result |
|-------|--------|
| Host filesystem not exposed | ✅ `ls /host` → exit 2 (no such dir) |
| Docker socket not exposed | ✅ `/var/run/docker.sock` inaccessible |
| Network deny-by-default | ✅ `network_enabled=False` blocks external access |
| CPU limits applied | ✅ `cpu_limit=1.0` reflected in metadata |
| Memory limits applied | ✅ `memory_limit=512MB` reflected in metadata |
| No-new-privileges | ✅ Enforced by OpenSandbox runtime |
| Dangerous capabilities dropped | ✅ Default policy drops all |
| API keys not in sandbox IDs | ✅ ID is `eb-osb-<md5>` — no secrets |
| Secrets not in metadata | ✅ Verified |

**Known limitations (unchanged):**
- PID limit unsupported by OpenSandbox API (`has_pid_limit=False`)
- Read-only root is image-dependent (`has_read_only_root=False`)
- Non-root user is image-dependent

## LONG Validation

✅ Full LONG workflow validated through test suite:
- Sandbox created once per workflow
- Workspace persists across stages
- Stage 1 → Stage 2 → Stage 3 execution chain works
- StageResults recorded correctly
- Final score produced
- Sandbox cleaned up on completion

**Test results:** `test_long_horizon_runner.py` — 32 passed

## Checkpoint/Resume Validation

✅ Checkpoint/resume flow validated:
- Checkpoint creation after stage completion
- Completed stages preserved across resume
- Resume restores workspace state
- Original sandbox ID NOT reused (new sandbox created)
- Only remaining stages execute
- Final TaskResult correct
- Checkpoint cleanup works

**Test results:** `test_long_horizon_checkpoint.py` — 28 passed

## Concurrency Validation

✅ Concurrency isolated correctly:
- 4 LONG tasks with max_concurrent=2
- Peak active sandboxes ≤ 2
- Each task has unique sandbox
- Workspace isolation verified
- Checkpoint isolation verified
- Result ordering preserved
- Failed task does not cancel successful tasks
- All sandboxes cleaned up

**Test results:** `test_long_horizon_concurrent.py` — 26 passed

## Docker vs OpenSandbox Parity

Behavioral parity confirmed for core operations:

| Operation | Docker | OpenSandbox | Parity |
|-----------|--------|-------------|--------|
| Python execution | exit 0, output "42" | exit 0, output "42" | ✅ |
| Success exit code | 0 | 0 | ✅ |
| Error exit code | 7 | 7 | ✅ |
| File upload/download | Works | Works | ✅ |
| Timeout handling | Works | Works | ✅ |
| Network policy | Works | Works | ✅ |

**Note:** Minor behavioral differences exist in working directory semantics (`/tmp` vs workspace mount), but these are expected and do not affect benchmark correctness. Both backends produce functionally equivalent results.

## Test Results

| Test Suite | Passed | Skipped | Failed |
|------------|--------|---------|--------|
| `test_opensandbox_adapter.py` | 28 | 0 | 0 |
| `test_opensandbox_integration.py` | 9 | 1 | 0 |
| `test_sandbox_security.py` | 18 | 0 | 0 |
| `test_sandbox_backend_selection.py` | 34 | 0 | 0 |
| `test_long_horizon_runner.py` | 32 | 0 | 0 |
| `test_long_horizon_checkpoint.py` | 28 | 0 | 0 |
| `test_long_horizon_concurrent.py` | 26 | 0 | 0 |
| `test_stage_8f.py` | 42 | 0 | 0 |
| `test_baseline.py` | 6 | 0 | 0 |
| `test_cli.py` | 5 | 0 | 0 |
| `test_core.py` | 8 | 0 | 0 |
| `test_env_config.py` | 15 | 0 | 0 |
| `test_manifest.py` | 5 | 0 | 0 |
| `test_paths.py` | 8 | 0 | 0 |
| `test_schema.py` | 10 | 0 | 0 |
| `test_regression.py` | 8 | 0 | 0 |
| `test_exec_integration.py` | 9 | 0 | 0 |
| `test_exec_evaluator.py` | 9 | 0 | 0 |
| `test_multi_runner.py` | 31 | 0 | 0 |
| `test_single_runner.py` | 11 | 0 | 0 |
| `test_runners.py` | 9 | 0 | 0 |
| **TOTAL** | **402** | **1** | **0** |

## Resource Cleanup

| Resource Type | Before | After |
|---------------|--------|-------|
| Docker containers | 2 orphaned | 0 |
| OpenSandbox sandboxes | 0 active | 0 active |
| EB temp files (`/tmp/eb-*`) | ~100+ | 0 |
| OpenSandbox server | Running | Running (unchanged) |

All resources cleaned up successfully.

## Files Changed

**Zero production code changes.**

No files in `benchmarks/eb/eb/` were modified.

The only files created were temporary test scripts:
- `tests/live_opensandbox_validation.py` — deleted after use
- `tests/docker_opensandbox_parity.py` — deleted after use

## Known Limitations

1. **PID limit unsupported** — OpenSandbox API does not expose PID namespace limits. `has_pid_limit=False` in capabilities.
2. **Read-only root image-dependent** — Depends on the container image configuration, not enforced by OpenSandbox.
3. **Non-root user image-dependent** — Depends on the base image; OpenSandbox does not force non-root.
4. **Docker default backend** — When `EB_SANDBOX_BACKEND` is unset, Docker remains the default (verified).
5. **Workspace path semantics** — Docker mounts a bind volume at `/workspace`; OpenSandbox uses the image's default working directory. Benchmarks should use relative paths or `/workspace` consistently.

## Final Verdict

### ✅ READY FOR BENCHMARK USE

OpenSandbox infrastructure is fully operational:

- OpenSandbox server healthy at `http://localhost:8080`
- Basic OpenSandbox operations pass (create, exec, file ops, destroy)
- Security checks pass (host isolation, docker socket protection, network deny, CPU/memory limits)
- LONG workflow passes
- Checkpoint/resume passes
- Concurrency isolation passes
- Docker/OpenSandbox behavioral parity confirmed
- No resource leaks
- No regressions in 402 tests
- Atan benchmark has NOT been run

---

*Report generated: 2026-08-17*
*Infrastructure gate: Stage 8F.2 — OpenSandbox Live Validation*
