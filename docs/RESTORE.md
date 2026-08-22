# Release Backup & Restore Procedure (Atlas)

## Canonical backup locations

| Release | Governed backup | Integrity |
|---|---|---|
| v1.0 (final) | `~/projects/data/atlas/releases/v1.0` | `metadata/checksums.sha256` (14 entries) + `BACKUP_MANIFEST.json` |

> **History:** until 2026-08-22 the only full copy of the v1.0 bytes lived in
> `tmp/atlas-recovery/v1.0-RC2/` — a gitignored scratch directory the project
> treats as disposable. The governed copy above was made from it and verified
> at destination. The original was left untouched.

## Verify integrity

```bash
python3 scripts/release/verify_backup.py ~/projects/data/atlas/releases/v1.0
# expect: "VERIFIED: backup is intact and consistent."  exit 0
```

The script checks: required files present, every sha256 in
`checksums.sha256` matches file bytes, no unlisted payload files, and
identity agreement between `release.json` and `BACKUP_MANIFEST.json`.

## Restore into the repo

```bash
DEST=~/projects/active/atlas-dataset/releases/v1.0
SRC=~/projects/data/atlas/releases/v1.0

# 0. verify first — never restore unverified bytes
python3 scripts/release/verify_backup.py "$SRC" || exit 1

mkdir -p "$DEST"
cp -a "$SRC/dataset" "$DEST/"
cp -a "$SRC/metadata/checksums.sha256" "$SRC/metadata/provenance.json" \
      "$SRC/metadata/release.json" "$SRC/metadata/statistics.json" "$SRC/metadata/" 2>/dev/null || true
cp -a "$SRC/metadata" "$DEST/"
cp -a "$SRC/docs" "$DEST/"

# re-verify at destination
cd "$DEST" && grep -v '^#' metadata/checksums.sha256 | sha256sum -c -
```

After restoring, refresh derived views if needed via
`python -m scripts.automation_runner e2e` (see AGENTS.md).

## Rules

1. **Never delete `tmp/atlas-recovery/` or any release bytes** before the
   governed backup verifies clean in *two* independent locations.
2. Any new release must ship `checksums.sha256` (existing
   `scripts/release/generate_checksums.py`) and be copied to
   `~/projects/data/atlas/releases/<version>/` with a `BACKUP_MANIFEST.json`.
3. Run `verify_backup.py` after any move, copy, or disk migration.
