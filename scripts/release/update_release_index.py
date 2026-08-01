#!/usr/bin/env python3
"""Update release_index.json after a successful HF upload.

Adds an entry to the repo's ``metadata/release_index.json`` describing the
Hub publication of a release. Never touches the release chain hashes —
``chain_hash``/``content_hash``/``previous_hash`` are preserved exactly.

Usage (library):
    from update_release_index import update_index

    update_index(
        release="v1.0-RC1",
        repo_id="EffNine/atlas-dataset",
        repo_type="dataset",
        commit_url="https://huggingface.co/datasets/EffNine/atlas-dataset/commit/xxx",
        commit_hash="xxx",
        files=123,
        total_records=9_893_844,
    )

CLI:
  .venv-release/bin/python scripts/release/update_release_index.py \
      --release v1.0-RC1 --repo-id EffNine/atlas-dataset [--commit-url ...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import REPO_ROOT, read_json, utc_now, write_json

INDEX_PATH = REPO_ROOT / "metadata" / "release_index.json"


def update_index(
    *,
    release: str,
    repo_id: str,
    repo_type: str = "dataset",
    commit_url: str = "",
    commit_hash: str = "",
    files: int = 0,
    total_records: int = 0,
    index_path: Path = INDEX_PATH,
) -> dict:
    """Add/refresh the Hub publication record for a release. Returns new index.

    Preserves chain hashes; adds/updates the ``hub`` field on the matching
    release entry only.
    """
    if index_path.exists():
        index = read_json(index_path)
    else:
        index = {"releases": [], "genesis_hash": ""}

    releases = index.setdefault("releases", [])
    entry = next((r for r in releases if r.get("version") == release), None)
    if entry is None:
        entry = {
            "version": release,
            "release_type": "major",
            "created_at": utc_now(),
            "total_records": total_records,
            "chain_hash": "",
            "content_hash": "",
            "previous_hash": "",
            "gates_passed": True,
            "release_id": "",
            "hub": {},
        }
        releases.append(entry)

    entry["hub"] = {
        "repo_id": repo_id,
        "repo_type": repo_type,
        "published_at": utc_now(),
        "commit_url": commit_url,
        "commit_hash": commit_hash,
        "files": files,
        "total_records": total_records or entry.get("total_records", 0),
        "verified": True,
    }

    write_json(index_path, index)
    return index


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Record a successful HF Hub upload in release_index.json.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--release", required=True, help="Release version tag.")
    ap.add_argument("--repo-id", required=True, help="HF repo id.")
    ap.add_argument("--repo-type", default="dataset", help="HF repo type.")
    ap.add_argument("--commit-url", default="", help="Commit URL on the Hub.")
    ap.add_argument("--commit-hash", default="", help="Commit hash on the Hub.")
    ap.add_argument("--files", type=int, default=0, help="Number of files uploaded.")
    ap.add_argument("--total-records", type=int, default=0, help="Record count.")
    args = ap.parse_args(argv)

    index = update_index(
        release=args.release,
        repo_id=args.repo_id,
        repo_type=args.repo_type,
        commit_url=args.commit_url,
        commit_hash=args.commit_hash,
        files=args.files,
        total_records=args.total_records,
    )
    print(f"Updated {INDEX_PATH}: release={args.release} hub={args.repo_id}")
    entry = next(r for r in index["releases"] if r.get("version") == args.release)
    print(f"  chain_hash (unchanged): {entry.get('chain_hash', '')[:16]}...")
    print(f"  hub: {entry.get('hub')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
