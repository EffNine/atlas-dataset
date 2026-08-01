#!/usr/bin/env python3
"""Generate and verify checksums.sha256 for a release.

Walks the release directory and produces a sha256sum-format file:

    <hex>  <relative-path>

Usage:
  .venv-release/bin/python scripts/release/generate_checksums.py \
      --release v1.0-RC1 [--output releases/v1.0-RC1/metadata/checksums.sha256]

Verify mode:
  .venv-release/bin/python scripts/release/generate_checksums.py \
      --release v1.0-RC1 --verify
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import REPO_ROOT, sha256_file, utc_now

DEFAULT_RELEASE = "v1.0-RC1"


def find_release_root(release: str, output: str | None = None) -> Path:
    if output:
        # output may be the metadata file path; derive release root as parent.parent
        p = Path(output)
        if p.name == "checksums.sha256":
            return p.parent.parent
        return p
    return REPO_ROOT / "releases" / release


def collect_files(release_root: Path) -> list[Path]:
    """All files under release_root, relative paths, sorted for determinism."""
    if not release_root.exists():
        print(f"ERROR: release root does not exist: {release_root}")
        sys.exit(2)
    files = sorted(p for p in release_root.rglob("*") if p.is_file())
    if not files:
        print(f"ERROR: no files found under {release_root}")
        sys.exit(2)
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate or verify checksums.sha256 for an Atlas release.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--release", default=DEFAULT_RELEASE, help="Release version tag.")
    ap.add_argument(
        "--output",
        default=None,
        help="checksums.sha256 path (default: releases/<release>/metadata/checksums.sha256).",
    )
    ap.add_argument(
        "--verify",
        action="store_true",
        help="Verify existing checksums.sha256 instead of generating.",
    )
    args = ap.parse_args(argv)

    release_root = find_release_root(args.release, args.output)
    checksum_path = (
        Path(args.output)
        if args.output
        else release_root / "metadata" / "checksums.sha256"
    )

    if args.verify:
        if not checksum_path.exists():
            print(f"ERROR: {checksum_path} not found — generate it first.")
            return 2
        expected: dict[str, str] = {}
        with checksum_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    hexd, rel = line.split("  ", 1)
                except ValueError:
                    print(f"ERROR: malformed checksum line: {line!r}")
                    return 2
                expected[rel] = hexd

        mismatches: list[str] = []
        missing: list[str] = []
        files = collect_files(release_root)
        for rel in sorted(expected):
            fp = release_root / rel
            if not fp.exists():
                missing.append(rel)
        for fp in files:
            rel = str(fp.relative_to(release_root))
            if rel not in expected:
                continue  # extra file, not covered by manifest — reported below
            actual = sha256_file(fp)
            if actual != expected[rel]:
                mismatches.append(f"{rel}: expected {expected[rel]} got {actual}")

        extra = [str(fp.relative_to(release_root)) for fp in files if str(fp.relative_to(release_root)) not in expected]
        ok = not mismatches and not missing
        print(f"Checksum verify ({checksum_path}):")
        print(f"  entries       : {len(expected)}")
        print(f"  files on disk : {len(files)}")
        print(f"  mismatched    : {len(mismatches)}")
        print(f"  missing       : {len(missing)}")
        print(f"  extra (untracked): {len(extra)}")
        for m in mismatches[:10]:
            print(f"    MISMATCH {m}")
        for m in missing[:10]:
            print(f"    MISSING  {m}")
        for m in extra[:10]:
            print(f"    EXTRA    {m}")
        print("RESULT: " + ("OK" if ok else "FAILED"))
        return 0 if ok else 1

    # Generate mode.
    files = collect_files(release_root)
    lines: list[str] = []
    for fp in files:
        rel = str(fp.relative_to(release_root))
        # Never checksum the checksum file itself (self-referential hash).
        if checksum_path.resolve() == fp.resolve():
            continue
        lines.append(f"{sha256_file(fp)}  {rel}")

    checksum_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Atlas release {args.release} — SHA-256 checksums\n"
        f"# generated: {utc_now()}\n"
        f"# tool: scripts/release/generate_checksums.py\n"
        f"# format: sha256sum  (<hex>  <relative-path>)\n"
    )
    checksum_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines)} checksums → {checksum_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
