#!/usr/bin/env python3
"""Verify the integrity of an Atlas release backup directory.

Checks, in order:
  1. required files exist (metadata/checksums.sha256, metadata/release.json,
     BACKUP_MANIFEST.json)
  2. every entry in checksums.sha256 matches the actual file bytes
  3. no extra payload files hide inside dataset/
  4. release.json identity agrees with BACKUP_MANIFEST.json

Exit codes: 0 = verified, 1 = verification failure.

Usage:
    python3 scripts/release/verify_backup.py <backup-dir>

Example (canonical v1.0 backup):
    python3 scripts/release/verify_backup.py ~/projects/data/atlas/releases/v1.0
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

CHUNK = 1024 * 1024


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 1
    root = Path(argv[1]).expanduser().resolve()

    failures: list[str] = []

    sums_path = root / "metadata" / "checksums.sha256"
    release_path = root / "metadata" / "release.json"
    manifest_path = root / "BACKUP_MANIFEST.json"
    for p in (sums_path, release_path, manifest_path):
        if not p.is_file():
            failures.append(f"missing required file: {p}")
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1

    # 2. verify every listed checksum
    entries: list[tuple[str, str]] = []
    for line in sums_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # sha256sum format is "<hex>  <path>" (two spaces) or "<hex> *<path>";
        # split on any run of whitespace so both parse cleanly.
        parts = line.split(None, 1)
        if len(parts) != 2:
            failures.append(f"malformed checksums entry: {line!r}")
            continue
        entries.append((parts[0], parts[1].lstrip("*")))
    verified = 0
    for digest, rel in entries:
        target = root / rel
        if not target.is_file():
            failures.append(f"listed but missing: {rel}")
            continue
        actual = sha256_of(target)
        if actual != digest:
            failures.append(f"CHECKSUM MISMATCH: {rel} expected={digest} actual={actual}")
        else:
            verified += 1

    # 3. no unlisted payload files under dataset/
    listed = {name for _, name in entries}
    dataset_dir = root / "dataset"
    if dataset_dir.is_dir():
        for f in sorted(dataset_dir.rglob("*")):
            if f.is_file():
                rel = f.relative_to(root).as_posix()
                if rel not in listed:
                    failures.append(f"unlisted payload file: {rel}")

    # 4. identity agreement between release.json and backup manifest
    try:
        release = json.loads(release_path.read_text())
        manifest = json.loads(manifest_path.read_text())
        m_rel = manifest.get("release", {})
        for key in ("release_id", "release_version", "status", "total_records"):
            if key in m_rel and release.get(key) != m_rel[key]:
                failures.append(
                    f"identity mismatch on {key}: release.json="
                    f"{release.get(key)!r} BACKUP_MANIFEST={m_rel[key]!r}"
                )
    except json.JSONDecodeError as e:
        failures.append(f"unparseable JSON: {e}")

    print(f"backup: {root}")
    print(f"entries verified OK: {verified}/{len(entries)}")
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("VERIFIED: backup is intact and consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
