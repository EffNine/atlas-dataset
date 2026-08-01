#!/usr/bin/env python3
"""Download and restore an Atlas release from Hugging Face Hub.

Recovery path: pulls the release tree (dataset/, metadata/, docs/) from the
Hub, then verifies every file against the release's own checksums.sha256
(which is included in the download).

Usage:
  export HF_TOKEN=hf_xxx   # required for private repos
  .venv-release/bin/python scripts/release/download_release.py \
      --repo-id EffNine/atlas-dataset \
      --release v1.0-RC1 \
      --output releases/restored \
      --verify
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import REPO_ROOT, human_bytes, require_env, sha256_file

DEFAULT_RELEASE = "v1.0-RC1"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Download and verify an Atlas release from Hugging Face Hub.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--repo-id", required=True, help="HF repo id, e.g. EffNine/atlas-dataset")
    ap.add_argument("--release", default=DEFAULT_RELEASE, help="Release version tag.")
    ap.add_argument(
        "--output",
        default=None,
        help="Destination directory (default: <repo>/releases/restored/<release>).",
    )
    ap.add_argument(
        "--revision",
        default=None,
        help="Optional revision (branch/tag/commit); default = main.",
    )
    ap.add_argument("--verify", action="store_true", help="Verify SHA-256 after download.")
    ap.add_argument("--no-cache", action="store_true", help="Use local_dir (no HF cache).")
    args = ap.parse_args(argv)

    dest = (
        Path(args.output)
        if args.output
        else REPO_ROOT / "releases" / "restored" / args.release
    )
    dest.mkdir(parents=True, exist_ok=True)

    token = require_env("HF_TOKEN")

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print(
            "ERROR: huggingface_hub is required. Install it in the release venv: "
            "python -m pip install huggingface_hub"
        )
        return 2

    prefix = f"releases/{args.release}/"
    print(
        f"Downloading {args.repo_id} release {args.release} → {dest}\n"
        f"  revision : {args.revision or 'main'}"
    )
    snapshot_download(
        repo_id=args.repo_id,
        repo_type="dataset",
        revision=args.revision,
        token=token,
        local_dir=dest,
        allow_patterns=[f"{prefix}*"],
        max_workers=4,
    )

    # snapshot_download with local_dir mirrors the repo tree; the release files
    # land under dest/releases/<release>/ when the repo stores releases/.
    # If the repo is release-rooted (files at top level), they land in dest/.
    release_dir = dest / prefix
    if not release_dir.exists() and (dest / "dataset").exists():
        # release-rooted repo layout
        release_dir = dest
    if not release_dir.exists():
        print(f"ERROR: release files not found under {dest}")
        return 1

    files = sorted(p for p in release_dir.rglob("*") if p.is_file())
    print(f"Downloaded {len(files)} files ({human_bytes(sum(f.stat().st_size for f in files))})")

    if not args.verify:
        print("Skipping verification (--verify not set).")
        return 0

    # Verify against the release's own checksums.sha256.
    checksum_file = release_dir / "metadata" / "checksums.sha256"
    if not checksum_file.exists():
        print(f"ERROR: {checksum_file} not found in download — cannot verify.")
        return 1

    expected: dict[str, str] = {}
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            hexd, rel = line.split("  ", 1)
        except ValueError:
            continue
        expected[rel] = hexd

    problems: list[str] = []
    checked = 0
    for rel, hexd in expected.items():
        fp = release_dir / rel
        if not fp.exists():
            problems.append(f"MISSING: {rel}")
            continue
        actual = sha256_file(fp)
        checked += 1
        if actual != hexd:
            problems.append(f"MISMATCH: {rel}")
    for fp in files:
        rel = str(fp.relative_to(release_dir))
        # The checksum manifest itself is never listed in checksums.sha256
        # (self-referential hash avoidance in generate_checksums.py).
        if rel == "metadata/checksums.sha256":
            continue
        if rel not in expected:
            problems.append(f"EXTRA (not in checksums): {rel}")

    print(f"\nVerified {checked}/{len(expected)} checksum entries")
    if problems:
        print(f"VERIFICATION FAILED — {len(problems)} problem(s):")
        for p in problems[:20]:
            print(f"  {p}")
        return 1
    print("VERIFICATION OK — download matches release checksums.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
