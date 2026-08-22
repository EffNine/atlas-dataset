# HF Restore Verification — Atlas v1.0

**Date:** 2026-08-22 · **Method:** clean-room download from Hugging Face into a
fresh temp directory, independent checksum + byte-comparison against the
governed local release.

## Procedure

1. `snapshot_download(repo_id="EffNine/atlas-dataset", repo_type="dataset",
   allow_patterns=["releases/v1.0/**"])` → `/tmp/opencode/hf-verify-v1.0`
   (21 files fetched, no local cache reuse for payload).
2. Ran the downloaded copy's own manifest:
   `grep -v '^#' checksums.sha256 | sha256sum -c -`
3. Compared every file byte-for-byte (SHA-256) between the HF download and
   `~/projects/data/atlas/releases/v1.0`.
4. Cross-checked identity fields against the authoritative repo manifest.

## Results

| Check | Result |
|---|---|
| Downloaded-copy checksums (`checksums.sha256`, 14 entries) | **14/14 OK** |
| Files compared hf ↔ governed local | **21 / 21 byte-identical** |
| Hash mismatches | **NONE** |
| Extra files on either side | **NONE** |
| `release_id` | `4dcfd43e9da2d756` — identical to authoritative |
| `total_records` | 9,515,938 — identical |
| Repo visibility | private ✅ |

## Conclusion

The Hugging Face mirror is **byte-identical** to the governed local v1.0
FINAL release and passes its own shipped integrity manifest after a cold
download. HF is hereby a valid **off-device backup and distribution
mirror**: a full restore is possible from this repository alone using
`RESTORE.md` in the release folder.
