# Atlas HF Release Report

**Date:** 2026-08-22 · **Mission:** make Hugging Face the official off-device
backup and distribution mirror for Atlas releases.

## 1. Existing HF repository discovered

`EffNine/atlas-dataset` (dataset type, **private**) — already existed with the
complete v1.0 FINAL payload (15 files under `releases/v1.0/`, published
2026-08-01, commit `1370ac42`). No new repository was created.

## 2. Current pipeline assessment

| Component | Status |
|---|---|
| `publish_promotion.py` | ✅ canonical publisher; owns the `releases/<version>/…` layout |
| `upload_huggingface.py` | ⚠️ had a **stale path scheme** (repo-root sections) that would have duplicated ~4.8 GB into a second tree, plus stale `DEFAULT_RELEASE="v1.0-RC1"` — **fixed** (see §5) |
| Pre-upload gate | ✅ checksums verified before any network I/O |
| Resume logic | ✅ checksum-aware skip; proven live (all sections skipped) |
| Retry classification | ✅ 429/5xx retryable, 401/403/404 fatal |
| Post-upload verify | ✅ size+sha256 via `get_paths_info` |
| Secrets / machine paths | ✅ none committed |
| Tests | ✅ `test_upload_hardening.py` extended: **22 passed** |

## 3. Upload status

- Payload (15 files): **already complete on Hub** — resume skipped everything,
  zero re-upload, zero duplication.
- Governance files uploaded to `releases/v1.0/`: `README.md`, `manifest.json`,
  `checksums.sha256`, `RELEASE_NOTES.md`, `RESTORE.md`, `BACKUP_MANIFEST.json`
  (commits `d981f2d5`, `d9badd0b`, `d14c0066`, `2cd5bb3b`, `3fda1003`, `29407654`).
- Release identity printed during upload:
  `version=v1.0 id=4dcfd43e9da2d756 status=final records=9515938`.
- `metadata/release_index.json` hub entry refreshed for v1.0.

## 4. Verification results

| Stage | Result |
|---|---|
| Pre-upload (`pre_upload_verification_v1.0_hf.json`) | all checks pass: manifest ✓, sha256 14/14 ✓, record count ✓, release ID ✓, status final ✓, hub payload byte-identical ✓ |
| Post-upload script verification | 21/21 files present on Hub |
| Clean-room download + `sha256sum -c` | **14/14 OK** |
| Byte comparison hf ↔ governed local | **21/21 identical, 0 mismatches** |

Full evidence: `docs/HF_RESTORE_VERIFICATION.md`.

**Conclusion:** HF is now a verified off-device mirror; restore is possible
from the Hub alone via the shipped `RESTORE.md`.

## 5. Fixes made

1. `upload_huggingface.py` aligned to the canonical version-prefixed layout
   (`releases/<release>/…`) — prevents accidental duplicate-tree uploads.
2. `DEFAULT_RELEASE` → `v1.0`; docstring documents the layout contract.
3. New `--extra-file NAME` (repeatable) for governance docs, with same retry
   classification; included in post-upload verification.
4. Upload now prints the release identity (version/id/status/records) as a
   fail-safe against publishing the wrong artifact.
5. Two regression tests for prefix-aware resume (`TestPathPrefixResume`).
6. Governance files added to the governed local backup (self-describing);
   backup still verifies 14/14 after the addition.

Evidence artifacts kept in-repo: `docs/HF_RELEASE_AUDIT.md`,
`reports/releases/pre_upload_verification_v1.0_hf.json`,
`docs/HF_RESTORE_VERIFICATION.md`.

## 6. Future release procedure

```bash
# 0. Build & promote per ADR-014 (human approval gate), then:
export HF_TOKEN=...   # or rely on cached token

# 1. Verify locally before anything leaves the machine
python3 scripts/release/verify_backup.py ~/projects/data/atlas/releases/<ver>

# 2. Dry-run plan (no network)
./.venv-nemotron-nano/bin/python scripts/release/upload_huggingface.py \
    --repo-id EffNine/atlas-dataset --release <ver> --private \
    --output <release-root> --dry-run \
    --extra-file README.md --extra-file manifest.json \
    --extra-file checksums.sha256 --extra-file RELEASE_NOTES.md \
    --extra-file RESTORE.md --extra-file BACKUP_MANIFEST.json

# 3. Upload (same command without --dry-run); confirm printed release ID

# 4. Clean-room verification
#    snapshot_download → sha256sum -c → byte-compare vs local
#    (procedure documented in docs/HF_RESTORE_VERIFICATION.md)

# 5. Record publication (automatic): metadata/release_index.json hub entry
```

Safeguards now built into the flow: pre-upload checksum gate (fail-closed),
release-ID banner, checksum-aware resume, post-upload size/sha verification,
clean-room restore check.
