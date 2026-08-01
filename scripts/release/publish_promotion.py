#!/usr/bin/env python3
"""Publish an Atlas release promotion to Hugging Face Hub without re-uploading data.

For a promotion (RC -> final) the dataset files are byte-identical to the
source release. This script:

  1. Server-side copies releases/<from>/dataset/** -> releases/<to>/dataset/**
     via CommitOperationCopy (reuses existing LFS objects; no 4.8GB upload).
  2. Uploads releases/<to>/metadata/** and releases/<to>/docs/** (small files).
  3. Verifies every file exists remotely with matching size.

Usage:
  HF_TOKEN=... .venv-release/bin/python scripts/release/publish_promotion.py \
      --repo-id EffNine/atlas-dataset --from v1.0-RC2 --to v1.0

Requires huggingface_hub >= 0.24 (CommitOperationCopy support).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from common import REPO_ROOT

from huggingface_hub import HfApi, CommitOperationAdd, CommitOperationCopy


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-id", required=True)
    ap.add_argument("--from", dest="from_version", required=True)
    ap.add_argument("--to", dest="to_version", required=True)
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)

    token = os.environ.get("HF_TOKEN")
    if not token:
        print("ERROR: HF_TOKEN not set", file=sys.stderr)
        return 2

    root = Path(args.root) if args.root else REPO_ROOT
    to_root = root / "releases" / args.to_version
    if not to_root.exists():
        print(f"ERROR: release root does not exist: {to_root}", file=sys.stderr)
        return 2

    api = HfApi()
    prefix_from = f"releases/{args.from_version}/dataset"
    prefix_to = f"releases/{args.to_version}/dataset"

    # 1. Enumerate source dataset files on the remote.
    remote_files = api.list_repo_files(repo_id=args.repo_id, repo_type="dataset", token=token)
    src_dataset = [f for f in remote_files if f.startswith(prefix_from + "/")]
    if not src_dataset:
        print(f"ERROR: no remote files found under {prefix_from}/", file=sys.stderr)
        return 2
    print(f"Remote dataset files to copy: {len(src_dataset)}")

    ops: list = []
    for rf in sorted(src_dataset):
        rel = rf[len("releases/") :]  # releases/<from>/dataset/<cat>/<file>
        dst_rel = "releases/" + args.to_version + rel[len(args.from_version) + 1 :]
        ops.append(CommitOperationCopy(src_path_in_repo=rf, path_in_repo=dst_rel))

    # 2. Add metadata + docs (small local files).
    for section in ("metadata", "docs"):
        sec_dir = to_root / section
        if sec_dir.is_dir():
            for f in sorted(sec_dir.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(to_root)
                    ops.append(CommitOperationAdd(path_in_repo=f"releases/{args.to_version}/{rel}", path_or_fileobj=str(f)))
    print(f"Total operations: {len(ops)} (copy={len(src_dataset)}, add={len(ops) - len(src_dataset)})")

    # 3. Commit.
    print("Committing...")
    commit = api.create_commit(
        repo_id=args.repo_id,
        repo_type="dataset",
        operations=ops,
        commit_message=f"Atlas {args.to_version} final release (promoted from {args.from_version})",
        token=token,
    )
    print(f"Commit: {commit.commit_url}")

    # 4. Verify remote.
    remote_paths = api.list_repo_files(repo_id=args.repo_id, repo_type="dataset", token=token)
    expected = set(f"releases/{args.to_version}/{f.relative_to(to_root)}" for f in to_root.rglob("*") if f.is_file())
    missing = [p for p in expected if p not in remote_paths]
    if missing:
        print(f"ERROR: missing after publish: {missing}", file=sys.stderr)
        return 1
    print(f"Verify: all {len(expected)} v1.0 files present remotely.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
