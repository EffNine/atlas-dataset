# Phase 7C — Release Upload & Publish Hardening Audit

**Scope:** `scripts/release/upload_huggingface.py`, `scripts/release/publish_promotion.py`  
**Date:** 2025-08-02  
**Status:** Audit/design only — no code changes, no HF upload, no release publish.

---

## 1. Executive Summary

Two issues require hardening before release operations become safe at scale:

1. **Upload verification is weaker than claimed.** `_verify_remote()` collects LFS sha256 but only compares file size. A corrupted LFS object of the same byte length would pass verification silently.
2. **Publish promotion has batch-operation drop risk and no duplicate prevention.** `publish_promotion.py` issues a single commit containing every `CommitOperationCopy`; the HF hub may drop copies in bulk commits. There is also no guard against publishing the same final release twice.

Everything else — resume/skip logic, retry backoff, repo creation — is acceptable for current scale but needs config integration and idempotency hardening.

---

## 2. upload_huggingface.py Audit

### 2.1 Worker Model

| Aspect | Current | Assessment |
|--------|---------|------------|
| Parallelism | `ThreadPoolExecutor` over **sections** (`dataset`, `metadata`, `docs`), max_workers from CLI `--workers` (default 4) | Coarse-grained: each section is one atomic `upload_folder` call. Reasonable for 3 sections, but concurrent section commits can race if HF rate-limits. |
| Config integration | None — script ignores `config/parallelism.yaml` despite `upload_workers: 4` being defined there | **Gap.** Violates unified config principle. CLI `--workers` is the only knob. |
| Backpressure | No memory or storage awareness | Acceptable for current scope; releases are small metadata + LFS dataset. |

**Finding:** Move worker default to `config.parallelism.release.upload_workers` with CLI override taking precedence.

### 2.2 Retry Behaviour

```python
MAX_RETRIES = 3
BACKOFF_BASE_S = 2.0
# exponential: 2s, 4s
```

- Retries apply to **whole sections**, not individual files.
- If `upload_folder` fails at 90% through a 15-file section, all 15 files are retried.
- `run_as_future=False` means the call is synchronous; retry loop is single-threaded within a section.

**Finding:** Acceptable given section-level atomicity. Add transient-error classification so non-retryable errors (auth, 404) fail immediately instead of exhausting retries.

### 2.3 Resume Behaviour

```python
def _resume_skip(sections, remote_sizes, release_root):
    # skip if remote exists AND size matches
```

- **Size-based skip only.** Files with matching remote size are not re-uploaded.
- **Gap:** A file whose bytes were corrupted post-upload but size is unchanged would be skipped forever.
- `_collect_local_files` exits if release root is empty — good defensive check.
- Section-level skip: if all files in a section match, the whole section is skipped. Good.

**Finding:** Resume logic is correct for the skip decision itself; the weakness is the verification predicate (see §2.5).

### 2.4 Remote Verification (Current)

```python
def _verify_remote(api, repo_id, token, local_files, release_root):
    remote[rpath] = {"size": ..., "sha256": ...}
    # compares only size
    if rsize is not None and rsize != lsize:
        problems.append(f"SIZE mismatch: ...")
```

The sha256 is collected but **never compared**. The docstring says "size + sha256" but the implementation only checks size.

**Known issue confirmed.**

### 2.5 Checksum Validation Strategy (Design)

Proposed SHA256 verification design:

```
Local checksums.sha256  (generated during release build)
        ↓
  Pre-upload: load local manifest of sha256 → local_expected
        ↓
  Post-upload remote fetch:
    - list_repo_files
    - get_paths_info(expand=True) → lfs.sha256 or file.sha256
        ↓
  Compare:
    for each local file:
      expected = local_checksums[rel]
      actual   = remote_lfs_sha256 OR remote_regular_sha256
      if actual != expected → FAIL
```

**Key design decisions:**

| Decision | Rationale |
|----------|-----------|
| Source of truth = local `checksums.sha256` file | Immutable, generated at build time, not rehashable against a partially-uploaded remote. |
| Prefer `lfs.sha256` over regular `sha256` | For LFS dataset files, `info.lfs.sha256` is the true content hash; `info.sha256` may be the pointer-file hash. |
| Fail if LFS file has no `lfs.sha256` | Indicates the file was not actually uploaded as LFS. |
| Verify **before** updating release_index | Do not record a successful publication if verification fails. |

**Resume correctness with SHA256:**

```python
def _resume_skip(sections, remote_sizes, local_checksums, release_root):
    for section, files in sections:
        missing = [
            f for f in files
            if str(f.relative_to(release_root)) not in remote_sizes
            or remote_sizes.get(str(f.relative_to(release_root)), -1) != f.stat().st_size
            or remote_sha256.get(str(f.relative_to(release_root))) != local_checksums[rel]
        ]
```

This is safe: only skip when size AND sha256 match. A size-match/sha256-mismatch forces re-upload.

### 2.6 Worker Configuration Integration

**Preferred path:**

```
CLI --workers → resolve_worker_count("release.upload", cfg, explicit=N)
                → config/parallelism.yaml[release][upload_workers]
                → default 4
```

The script should import `parallel.config.resolve_worker_count` and use it instead of the bare `--workers` default. This aligns with the unified parallelism config already established for classification, validation, extraction, etc.

### 2.7 Safe Retry Model

Current retry is section-level with exponential backoff. Proposed additions:

1. **Error classification:** Do not retry on `auth_error`, `repo_not_found`, `invalid_path`.
2. **Per-file checkpoint:** Before retrying a section, log which files were confirmed uploaded. On retry, attempt `upload_folder` with `allow_patterns` for missing files only.
3. **Circuit breaker:** After 2 consecutive section failures, halt and surface the error rather than cycling through all retries silently.

---

## 3. publish_promotion.py Audit

### 3.1 CommitOperationCopy Behaviour

```python
commit = api.create_commit(
    repo_id=...,
    operations=ops,  # ALL copy + add ops in one commit
    ...
)
```

**Known HF issue:** Batch `create_commit` with many `CommitOperationCopy` entries can silently drop some copy operations. The skill explicitly warns: "run one commit per dataset file."

**Current script:** Sends all copy ops in a single commit. **Non-compliant with documented pitfall.**

**Risk:** If 1–2 of 15 copies are dropped, verification would catch missing files (presence check only). But the missing files would not be retried — the script would exit with an error and leave the repo in a partially-copied state with no rollback.

### 3.2 Silent-Drop Risks

| Risk | Current State | Required |
|------|--------------|----------|
| Batch copy drop | Single commit with all ops | One commit per dataset file |
| Missing files not retried | Exit 1 on missing | Retry loop per dropped file |
| Orphaned partial state | No cleanup | Document manual cleanup path |

### 3.3 Destination Validation

```python
expected = set(f"releases/{to_version}/{f.relative_to(to_root)}" for f in to_root.rglob("*") if f.is_file())
missing = [p for p in expected if p not in remote_paths]
```

- Validates **presence only**, not size or sha256.
- Does not validate that copied files match source file checksums.
- Does not validate that destination metadata/docs files match local files.

**Required:** Match the same SHA256 verification strategy as `upload_huggingface.py`.

### 3.4 Duplicate Publish Prevention

```python
# No check for existing v1.0 files before publishing
```

If the script is run twice for the same `--to` version:
- `CommitOperationCopy` for already-existing destinations may be silently ignored or error.
- `CommitOperationAdd` for metadata/docs may overwrite or error.
- `release_index.json` would be updated again with a new commit URL, creating duplicate index entries.

**Required guard:**

```python
existing = {f for f in remote_files if f.startswith(f"releases/{to_version}/")}
if existing:
    print(f"ERROR: {to_version} already has {len(existing)} files on Hub")
    return 2
```

This must run **before** any commit operations.

### 3.5 Rollback Strategy

**Current state:** None. Once published, the only recovery is manual deletion on HF + re-run.

**Required design:** Since HF has no transactional rollback, the rollback strategy is operational, not programmatic:

1. **Pre-commit snapshot:** Record the HF repo state (file list + commit hash) before publishing.
2. **Post-commit verification gate:** If verification fails, do NOT update `release_index.json`.
3. **Manual rollback runbook:** Document the exact `hf delete` commands to remove the failed release files from HF.
4. **Idempotent retry:** After cleanup, the script can be re-run safely because duplicate-check prevents re-publishing.

---

## 4. SHA256 Verification Strategy (Unified)

This applies to both scripts.

### 4.1 Local Manifest

During release build (`build_release_metadata.py`), generate `releases/<version>/checksums.sha256`:

```
<sha256>  <relative-path>
<sha256>  dataset/...
<sha256>  metadata/...
<sha256>  docs/...
```

Format: standard sha256sum, one line per file.

### 4.2 Upload-time Verification Flow

```
┌─────────────────────┐
│ Local checksums.sha256  ← immutable, built once
└──────────┬──────────┘
           │ load into dict: local_checksums[rel] = sha256
           ▼
┌─────────────────────────────────────┐
│ Upload sections with retry           │
│ (per-section or per-file checkpoint) │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│ Remote fetch:                        │
│   list_repo_files                    │
│   get_paths_info(expand=True)        │
│   → remote[rel] = {size, sha256}     │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│ Compare loop:                        │
│   missing?   → FAIL                   │
│   size mismatch? → FAIL               │
│   sha256 mismatch? → FAIL             │
│   (sha256 source: lfs.sha256 first,   │
│    then regular sha256)               │
└──────────┬──────────────────────────┘
           │ all pass
           ▼
┌─────────────────────────────────────┐
│ Update release_index.json            │
└─────────────────────────────────────┘
```

### 4.3 Resume Correctness

Resume skip condition becomes:

```python
def _should_skip(rel, remote_sizes, remote_sha256s, local_path, local_checksums):
    remote_size = remote_sizes.get(rel)
    remote_sha = remote_sha256s.get(rel)
    local_size = local_path.stat().st_size
    local_sha = local_checksums.get(rel)
    return (
        remote_size is not None
        and remote_size == local_size
        and remote_sha is not None
        and remote_sha == local_sha
    )
```

**Correctness invariant:** A file is skipped **only if** both size and content hash match. Any mismatch forces re-upload.

---

## 5. Failure Mode Summary

| Failure | upload_huggingface.py | publish_promotion.py |
|---------|----------------------|---------------------|
| Network timeout | Retries section with backoff | No retry — fails immediately |
| HF batch copy drop | N/A (uses `upload_folder`) | Single commit drops copies silently |
| Partial upload | Size-based resume skips already-uploaded files | No resume — all-or-nothing commit |
| SHA256 mismatch | **Not detected** — only size checked | **Not detected** — only presence checked |
| Duplicate publish | Safe — `upload_folder` is idempotent for existing files | **Unsafe** — no duplicate guard |
| Auth failure | Retries 3x then raises | Raises immediately |
| Repo already exists | Warns if public + `--private` | No pre-check |

---

## 6. Design Requirements Summary

### 6.1 upload_huggingface.py Hardening

| Req | Description | Priority |
|-----|-------------|----------|
| U-1 | Replace `--workers` default with `resolve_worker_count("release.upload", cfg)` from `config/parallelism.yaml` | High |
| U-2 | Compare `lfs.sha256` (or `sha256`) against local `checksums.sha256` in `_verify_remote` | High |
| U-3 | Use local `checksums.sha256` as additional skip predicate in `_resume_skip` | High |
| U-4 | Classify errors: skip retry for auth/not-found/invalid errors | Medium |
| U-5 | Log per-file upload status before retry for section-level checkpointing | Medium |
| U-6 | Verify BEFORE updating `release_index.json`, not after | High |

### 6.2 publish_promotion.py Hardening

| Req | Description | Priority |
|-----|-------------|----------|
| P-1 | One `create_commit` per dataset file (not batch) — eliminates silent drop | High |
| P-2 | Pre-publish guard: abort if destination prefix already has files on HF | High |
| P-3 | Verify copied files: remote `lfs.sha256` matches local `checksums.sha256` | High |
| P-4 | Verify added metadata/docs: remote `sha256` matches local file hash | High |
| P-5 | Retry loop per dropped copy after single-file commits | Medium |
| P-6 | Document rollback runbook for partial publish scenarios | Medium |
| P-7 | Do not update `release_index.json` if verification fails | High |

### 6.3 Shared Infrastructure

| Req | Description |
|-----|-------------|
| S-1 | `checksums.sha256` generation during release build (`build_release_metadata.py`) |
| S-2 | Shared `verify_remote_sha256(api, repo_id, token, local_checksums, release_root)` function used by both scripts |
| S-3 | Shared `should_skip(rel, remote_meta, local_checksums, local_path)` for resume logic |

---

## 7. Implementation Ordering

```
Phase 7C-A: Shared verification module
  - S-1, S-2, S-3

Phase 7C-B: upload_huggingface.py hardening
  - U-1, U-2, U-3, U-6
  - U-4, U-5

Phase 7C-C: publish_promotion.py hardening
  - P-1, P-2, P-3, P-4, P-7
  - P-5, P-6

Phase 7C-D: Integration test
  - dry-run both scripts against test repo
  - inject sha256 mismatch, verify detection
  - simulate partial upload, verify resume correctness
```

---

## 8. Stop Point

**Audit and design complete. No code changes made.**  
Awaiting approval before entering Phase 7C implementation.
