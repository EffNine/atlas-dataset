# HF Release Audit — Atlas Dataset

**Date:** 2026-08-22 · **Mode:** read-only discovery · Phase 1 of HF mirror completion

## 1. Existing pipeline discovered

| Component | Path | Role |
|---|---|---|
| Uploader (generic) | `scripts/release/upload_huggingface.py` | section uploads + pre-gate + resume + retry + post-verify |
| Publisher (canonical) | `scripts/release/publish_promotion.py` | promotion flow; uploads under `releases/{version}/…` |
| Downloader/verifier | `scripts/release/download_release.py` | `snapshot_download` mirror-side |
| Index updater | `scripts/release/update_release_index.py` | records hub publication into `metadata/release_index.json` (chain hashes untouched) |
| Packaging | `compress_release.py`, `generate_checksums.py`, `build_release_metadata.py` | zstd bundles, sha256 manifest, docs |

**Repo ID:** `EffNine/atlas-dataset` (dataset type) — configured in
`update_release_index.py` default and proven by live index entries.
**Auth:** `HF_TOKEN` env var only (`require_env`); a user token also exists in
the standard HF cache (`~/.cache/huggingface/token`). No secrets committed.
**LFS:** handled by huggingface_hub automatically; `.gitattributes` present on
Hub; all 9 `.zst` payloads stored as LFS with server-side sha256 exposed.

## 2. Live Hub state (probed read-only, authenticated)

- Repo exists, **private: true**, last_modified 2026-08-02, 17 files:
  - `releases/v1.0/**` — exactly the 15 v1.0 FINAL files (9 dataset zst, 4 metadata, 2 docs)
  - `README.md` (repo card), `.gitattributes`
- Publication recorded in `metadata/release_index.json`: v1.0 → commit
  `1370ac420b55fd9d2f7f7b0d26971beafed8ba80`, files=15, total_records=9,515,938,
  verified=true (2026-08-01).
- **Byte-identity (payload):** all 9 LFS dataset files on Hub match governed
  backup `data/atlas/releases/v1.0` sha256-for-sha256. 0 mismatches.

## 3. Findings

| # | Finding | Severity | Detail |
|---|---|---|---|
| F1 | `upload_huggingface.py` path scheme is stale | **HIGH** | Uploads to repo-root sections (`dataset/`, …) while the Hub convention is `releases/<version>/…`. Running it as-is would create a duplicate ~4.8 GB tree and a second source of truth |
| F2 | Stale defaults | MED | `DEFAULT_RELEASE="v1.0-RC1"` in uploader; RC1/RC2 defaults also in `compress_release.py`, `audit_duplicates.py`, `build_release_metadata.py` (historical tools — docstrings accurate for their era, low risk) |
| F3 | Governance files absent from release folder | MED | Mission set (manifest.json, BACKUP_MANIFEST.json, checksums.sha256 top-level, RELEASE_NOTES.md, RESTORE.md, README.md) not present under `releases/v1.0/` |
| F4 | Hardcoded machine paths | NONE in release scripts | Only tilde-path doc example in `verify_backup.py`; acceptable |
| F5 | Secrets | NONE | No tokens/keys in any release script |
| F6 | Structure matches v1.0 FINAL | YES | Governed backup layout = Hub layout (sections relative to release root) |

## 4. Decisions

1. **Reuse** `EffNine/atlas-dataset` — no new repository.
2. **Keep** the live version-prefixed layout `releases/v1.0/**` — no redesign;
   mission's proposed `atlas-v1.0/` tree maps onto the existing prefix
   (avoids duplicating 4.8 GB and preserves download tooling).
3. **Fix** `upload_huggingface.py` (Phase 6): align paths to
   `releases/{release}/…`, fix resume/verify comparisons, bump default
   release, add explicit `--extra-file` support for governance files.
4. Governance files are added **inside the release folder** so the release is
   self-describing; the governed local backup gains the same files (it remains
   checksum-clean; verifier scope unchanged).
