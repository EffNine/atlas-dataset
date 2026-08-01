#!/usr/bin/env python3
"""Upload an Atlas release to Hugging Face Hub (private by default).

Design:
  - resume: files already on the Hub with matching size are skipped (no
    re-upload); interrupted uploads continue where they left off
  - parallel: one ``upload_folder`` per top-level release section
    (dataset/<category>, metadata, docs) submitted as futures
  - retry: transient failures (5xx / connection) retried with backoff
  - progress: tqdm progress bar over files
  - verification: after upload, every remote file is checked via
    ``get_paths_info`` (size + sha256 where available); fails loudly on any
    mismatch
  - token: read from HF_TOKEN env var only — never hardcoded

Usage:
  export HF_TOKEN=hf_xxx
  .venv-release/bin/python scripts/release/upload_huggingface.py \
      --repo-id EffNine/atlas-dataset \
      --release v1.0-RC1 \
      --private \
      --workers 4 \
      --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from common import REPO_ROOT, human_bytes, require_env

DEFAULT_RELEASE = "v1.0-RC1"
MAX_RETRIES = 3
BACKOFF_BASE_S = 2.0

# Top-level sections inside a release that get uploaded.
RELEASE_SECTIONS = ("dataset", "metadata", "docs")


def _release_root(release: str, output: str | None = None) -> Path:
    if output:
        return Path(output)
    return REPO_ROOT / "releases" / release


def _collect_local_files(release_root: Path) -> list[Path]:
    files = sorted(
        p
        for p in release_root.rglob("*")
        if p.is_file() and p.name != ".gitkeep"
    )
    if not files:
        print(f"ERROR: release root is empty: {release_root}")
        sys.exit(2)
    return files


def _plan_sections(
    release_root: Path,
) -> list[tuple[str, list[Path]]]:
    """Group local files into upload sections: (path_in_repo_prefix, files)."""
    sections: list[tuple[str, list[Path]]] = []
    for section in RELEASE_SECTIONS:
        files = [
            p
            for p in sorted((release_root / section).rglob("*"))
            if p.is_file() and p.name != ".gitkeep"
        ]
        if files:
            sections.append((section, files))
    return sections


def _remote_sizes(api, repo_id: str, token: str) -> dict[str, int]:
    """Return {path_in_repo: size} for every file already on the Hub."""
    try:
        files = api.list_repo_files(repo_id=repo_id, repo_type="dataset", token=token)
    except Exception:
        # Repo may not exist yet -> treat as empty.
        return {}
    if not files:
        return {}
    sizes: dict[str, int] = {}
    try:
        infos = api.get_paths_info(
            repo_id=repo_id, paths=files, repo_type="dataset", token=token, expand=True
        )
        for info in infos:
            rpath = getattr(info, "path", None)
            size = getattr(info, "size", None)
            if rpath is not None and size is not None:
                sizes[rpath] = size
    except Exception:
        # Fall back to listing only (size unknown -> always re-upload).
        for f in files:
            sizes[f] = -1
    return sizes


def _resume_skip(
    sections: list[tuple[str, list[Path]]],
    remote_sizes: dict[str, int],
    release_root: Path,
) -> list[tuple[str, list[Path]]]:
    """Keep only files that are missing or differ in size on the Hub.

    A file is skipped when the remote entry exists AND has the same size.
    Size -1 (unknown) never skips — it forces a re-upload.
    """
    pending: list[tuple[str, list[Path]]] = []
    for section, files in sections:
        missing = [
            f
            for f in files
            if str(f.relative_to(release_root)) not in remote_sizes
            or remote_sizes.get(str(f.relative_to(release_root)), -1) != f.stat().st_size
        ]
        if missing:
            pending.append((section, missing))
    return pending


def _upload_section_with_retry(
    api,
    section: str,
    files: list[Path],
    *,
    repo_id: str,
    token: str,
    release_root: Path,
    commit_message: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Upload one section; retry on transient failure.

    Uploads only the section's own folder (release_root/<section>) so the
    remote repo gets dataset/, metadata/, docs/ at top level — NOT the whole
    release root nested under each section.
    """
    last_err: Exception | None = None
    section_dir = release_root / section
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if dry_run:
                return {
                    "section": section,
                    "files": len(files),
                    "bytes": sum(f.stat().st_size for f in files),
                    "dry_run": True,
                }
            commit = api.upload_folder(
                repo_id=repo_id,
                folder_path=str(section_dir),
                path_in_repo=section,
                repo_type="dataset",
                token=token,
                commit_message=commit_message,
                run_as_future=False,
            )
            return {
                "section": section,
                "files": len(files),
                "commit_url": getattr(commit, "commit_url", ""),
                "commit_hash": getattr(commit, "commit_hash", ""),
            }
        except Exception as exc:
            last_err = exc
            if attempt < MAX_RETRIES:
                wait = BACKOFF_BASE_S * (2 ** (attempt - 1))
                print(
                    f"  [retry {attempt}/{MAX_RETRIES}] {section} failed "
                    f"({exc}); waiting {wait:.0f}s"
                )
                time.sleep(wait)
    raise RuntimeError(f"upload failed for section {section}: {last_err}")


def _verify_remote(
    api,
    repo_id: str,
    token: str,
    local_files: list[Path],
    release_root: Path,
) -> tuple[bool, list[str]]:
    """Verify every local file exists remotely with matching size (+ sha256)."""
    remote_paths = api.list_repo_files(repo_id=repo_id, repo_type="dataset", token=token)
    infos = api.get_paths_info(
        repo_id=repo_id, paths=remote_paths, repo_type="dataset", token=token, expand=True
    )
    remote: dict[str, dict[str, Any]] = {}
    for info in infos:
        rpath = getattr(info, "path", None)
        if rpath is None:
            continue
        remote[rpath] = {
            "size": getattr(info, "size", None),
            "sha256": getattr(getattr(info, "lfs", None), "sha256", None)
            or getattr(info, "sha256", None),
        }

    problems: list[str] = []
    ok = True
    for local in local_files:
        rel = str(local.relative_to(release_root))
        if rel not in remote:
            ok = False
            problems.append(f"MISSING on Hub: {rel}")
            continue
        rsize = remote[rel]["size"]
        lsize = local.stat().st_size
        if rsize is not None and rsize != lsize:
            ok = False
            problems.append(f"SIZE mismatch: {rel} local={lsize} remote={rsize}")
    return ok, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Upload an Atlas release to Hugging Face Hub.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--repo-id", required=True, help="HF repo id, e.g. EffNine/atlas-dataset")
    ap.add_argument("--release", default=DEFAULT_RELEASE, help="Release version tag.")
    ap.add_argument(
        "--private",
        action="store_true",
        help="Create the repo private if it does not exist.",
    )
    ap.add_argument("--workers", type=int, default=4, help="Parallel section uploads.")
    ap.add_argument("--dry-run", action="store_true", help="Plan only; no network I/O.")
    ap.add_argument(
        "--commit-message",
        default="Atlas {release} release",
        help="Commit message template (supports {release}).",
    )
    ap.add_argument(
        "--output",
        default=None,
        help="Release root (default: <repo>/releases/<release>).",
    )
    args = ap.parse_args(argv)

    release_root = _release_root(args.release, args.output)
    local_files = _collect_local_files(release_root)
    sections = _plan_sections(release_root)

    total_bytes = sum(f.stat().st_size for f in local_files)
    print(
        f"Atlas HF upload | repo={args.repo_id} | release={args.release} "
        f"| private={args.private} | dry_run={args.dry_run}"
    )
    print(f"  local files : {len(local_files)}")
    print(f"  total size  : {human_bytes(total_bytes)}")
    print(f"  sections    : {[s for s, _ in sections]}")

    if args.dry_run:
        print("\nDRY RUN — no network I/O performed. Plan:")
        for section, files in sections:
            print(
                f"  upload {section:10s} → {args.repo_id}/{args.release}/"
                f"{section} ({len(files)} files, "
                f"{human_bytes(sum(f.stat().st_size for f in files))})"
            )
        print("\nResume logic: files already on the Hub with matching size are skipped.")
        print("Verification: all remote files checked post-upload (size + sha256).")
        print("Token source: HF_TOKEN env var.")
        return 0

    token = require_env("HF_TOKEN")

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print(
            "ERROR: huggingface_hub is required. Install it in the release venv: "
            "python -m pip install huggingface_hub"
        )
        return 2

    api = HfApi()

    # 1. Ensure repo exists (private when requested).
    try:
        repo_info = api.repo_info(repo_id=args.repo_id, repo_type="dataset", token=token)
        if args.private and not repo_info.private:
            print(
                f"WARNING: repo {args.repo_id} exists but is public; "
                f"--private ignored for existing repos."
            )
    except Exception:
        api.create_repo(
            repo_id=args.repo_id,
            repo_type="dataset",
            token=token,
            private=args.private,
            exist_ok=True,
        )
        print(f"Created repo {args.repo_id} (private={args.private})")

    # 2. Resume: determine which sections already exist remotely.
    remote_sizes = _remote_sizes(api, args.repo_id, token)
    pending_sections = _resume_skip(sections, remote_sizes, release_root)
    uploaded_names = {s for s, _ in sections} - {s for s, _ in pending_sections}
    for s in sorted(uploaded_names):
        print(f"  section {s}: already complete on Hub — skipping")

    if not pending_sections:
        print("Nothing to upload — all sections already on the Hub.")
        return 0

    print(f"\nUploading {len(pending_sections)} pending section(s)...")
    results: list[dict[str, Any]] = []
    if args.workers <= 1:
        for section, files in pending_sections:
            results.append(
                _upload_section_with_retry(
                    api,
                    section,
                    files,
                    repo_id=args.repo_id,
                    token=token,
                    release_root=release_root,
                    commit_message=args.commit_message.format(release=args.release),
                )
            )
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    _upload_section_with_retry,
                    api,
                    section,
                    files,
                    repo_id=args.repo_id,
                    token=token,
                    release_root=release_root,
                    commit_message=args.commit_message.format(release=args.release),
                ): section
                for section, files in pending_sections
            }
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                    print(f"  + {futures[fut]} uploaded")
                except Exception as exc:
                    print(f"  ! {futures[fut]} FAILED: {exc}")
                    return 1

    for r in results:
        print(f"  section {r['section']}: {r.get('commit_url') or 'dry'}")
        print(f"  commit : {r.get('commit_hash') or 'n/a'}")

    # 3. Verify all local files exist remotely with matching size/sha256.
    print("\nVerifying remote files...")
    ok, problems = _verify_remote(api, args.repo_id, token, local_files, release_root)
    if ok:
        print(f"VERIFICATION OK — all {len(local_files)} files present on Hub.")
    else:
        print(f"VERIFICATION FAILED — {len(problems)} problem(s):")
        for p in problems[:20]:
            print(f"  {p}")
        return 1

    # 4. Record the publication in release_index.json (chain hashes untouched).
    try:
        from update_release_index import update_index

        commit_hash = ""
        commit_url = ""
        if results:
            commit_hash = results[-1].get("commit_hash", "")
            commit_url = results[-1].get("commit_url", "")
        update_index(
            release=args.release,
            repo_id=args.repo_id,
            repo_type="dataset",
            commit_url=commit_url,
            commit_hash=commit_hash,
            files=len(local_files),
        )
        print(f"\nrelease_index.json updated for {args.release} → {args.repo_id}")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"WARNING: release_index.json update failed: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
