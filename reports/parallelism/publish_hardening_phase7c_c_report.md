# Publish Promotion Hardening — Phase 7C-C Report

## P-1 → P-7 Mapping

| ID | Issue | Implementation | Location |
|----|-------|---------------|----------|
| P-1 | Commit batch silent-drop risk | One `CommitOperationCopy` per file in sorted order; each file gets its own `create_commit` call | `scripts/release/publish_promotion.py` → `perform_dataset_copy()` |
| P-2 | Duplicate publish guard | Check `release_index.json` for existing release entry; abort if found | `scripts/release/publish_promotion.py` → `check_duplicate_publish()` |
| P-3 | Destination validation | Validate source exists, destination path valid, no duplicate destinations, no path collisions — all before any HF operation | `scripts/release/publish_promotion.py` → `validate_destinations()` |
| P-4 | SHA256 verification gate | Run `verify_manifest_files()` against `metadata/checksums.sha256` before any HF copy | `scripts/release/publish_promotion.py` → `run_sha256_gate()` |
| P-5 | Post-copy verification | After copy: verify destination exists, size matches, SHA256 matches; fail on any mismatch | `scripts/release/publish_promotion.py` → `post_copy_verify()` |
| P-6 | Rollback safety | If `release_index` update fails after successful HF copy: do not mark release published; emit recovery information; preserve audit log; no destructive cleanup | `scripts/release/publish_promotion.py` → `update_release_index_safe()` + `RollbackError` |
| P-7 | Release index integrity | `release_index.json` updated only after all verification passes; chain hashes preserved from source manifest | `scripts/release/publish_promotion.py` → `update_release_index_safe()` |

## Files Changed

| File | Change |
|------|--------|
| `scripts/release/publish_promotion.py` | Complete rewrite with P-1 through P-7 hardening |
| `tests/test_publish_hardening.py` | New test file — 32 tests covering all hardening points |

## Tests

### test_publish_hardening.py — 32 tests, all passing

| Test Class | Tests | Coverage |
|-----------|-------|----------|
| `TestDuplicatePublishGuard` | 5 | P-2: existing release blocks, RC blocks, new release continues, missing index, malformed index |
| `TestCommitOperations` | 3 | P-1: one op per file, sorted ordering, idempotent skip |
| `TestDestinationValidation` | 4 | P-3: missing source fails, missing destination fails, no dataset files fails, valid destinations pass |
| `TestSHA256Gate` | 5 | P-4: valid manifest passes, corrupted file blocks, missing manifest fails, missing file blocks, no real HF operation |
| `TestPostCopyVerify` | 4 | P-5: missing destination fails, checksum mismatch fails, size mismatch fails, all files match passes |
| `TestRollbackSafety` | 2 | P-6: rollback error emits recovery, no destructive cleanup |
| `TestNoRealHFOperations` | 5 | Safety: all HF calls mocked, duplicate guard no HF, SHA gate no HF, no index write on block, no dataset modification on block |
| `TestDryRun` | 1 | Dry-run mode produces no HF calls |
| `TestMainFlow` | 2 | Exit codes: duplicate guard → 3, missing source → 4 |

### Related release tests (all passing)

- `tests/test_release_pipeline.py` — 14 passed

### Architecture validator

```
RESULT: PASS — All architecture governance rules satisfied
```

## Verification Evidence

### Verification Probe

- Tempfile: `hermes-verify-` prefix, created via `tempfile.mkstemp`, cleaned up via `os.unlink`
- All probe assertions passed:
  - `tempfile_ok`: true
  - `duplicate_guard_implemented`: true
  - `duplicate_guard_blocks`: true
  - `commit_ordering_sorted`: true
  - `one_op_per_file`: true
  - `sha_gate_implemented`: true
  - `sha_gate_before_hf`: true
  - `no_hf_operation_dry_run`: true
  - `no_release_publish`: true
  - `no_dataset_modified`: true
  - `git_diff_expected_files`: true
  - `pytest_passed`: true (32/32)
  - `architecture_validator_passed`: true

## Explicit Statements

- **No HuggingFace publish performed.** All HF calls are mocked in tests; dry-run mode is the only execution path exercised.
- **No release promotion executed.** No release was promoted to final.
- **No dataset modified.** Only copy operations (LFS reuse) and metadata/docs uploads are performed; no dataset bytes are changed.

## Commit

```
feat: harden release promotion verification Phase 7C-C
```

## Stop Condition

Implementation + verification complete. STOP. Awaiting approval for 7C-D.