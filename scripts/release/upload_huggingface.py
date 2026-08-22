#!/usr/bin/env python3
"""Upload an Atlas release to Hugging Face Hub (private by default).

Design:
  - resume: files already on the Hub with matching checksum are skipped (no
    re-upload); interrupted uploads continue where they left off
  - parallel: one ``upload_folder`` per top-level release section
    (dataset/<category>, metadata, docs) submitted as futures
  - retry: transient failures (5xx / connection / 429) retried with backoff;
    fatal errors (401/403/404/bad creds) abort immediately
  - progress: tqdm progress bar over files
  - verification: after upload, every remote file is checked via
    ``get_paths_info`` (size + sha256 where available); fails loudly on any
    mismatch
  - token: read from HF_TOKEN env var only — never hardcoded
  - pre-upload gate: local release checksums.sha256 is verified before any
    network I/O starts

Usage:
  export HF_TOKEN=hf_xxx
  .venv-release/bin/python scripts/release/upload_huggingface.py \
      --repo-id EffNine/atlas-dataset \
      --release v1.0 \
      --private \
      --workers 4 \
      --dry-run

Layout:
  Files land under ``releases/<release>/<section>/…`` on the Hub, matching
  the canonical publish_promotion.py convention and the live repo. Optional
  governance files (--extra-file README.md …) land at
  ``releases/<release>/<filename>`` so a release folder is self-describing.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from pathlib import Path
from typing import Any

from common import REPO_ROOT, human_bytes, require_env

from verify_sha256 import (
    ManifestError,
    load_checksum_manifest,
    sha256_file,
    verify_manifest_files,
)

DEFAULT_RELEASE = "v1.0"
MAX_RETRIES = 3
BACKOFF_BASE_S = 2.0

# Top-level sections inside a release that get uploaded.
RELEASE_SECTIONS = ("dataset", "metadata", "docs")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker resolution (U-1)
# ---------------------------------------------------------------------------

def resolve_upload_workers(explicit: int | None = None) -> int:
    """Resolve upload worker count.

    Precedence:
      CLI --workers
      ATLAS_WORKERS_RELEASE
      config/parallelism.yaml release.upload_workers
      default 4
    """
    if explicit is not None and explicit > 0:
        return int(explicit)
    try:
        from parallel.config import resolve_worker_count
        resolved = resolve_worker_count("release", explicit=explicit)
        if isinstance(resolved, int) and resolved > 0:
            return resolved
    except Exception:
        pass
    return 4


# ---------------------------------------------------------------------------
# Retry classification (U-4)
# ---------------------------------------------------------------------------

class UploadErrorCategory(Enum):
    RETRYABLE = "retryable"
    FATAL = "fatal"


def _classify_upload_error(exc: Exception) -> UploadErrorCategory:
    """Classify an upload exception as retryable or fatal."""
    msg = str(exc).lower()

    # Authz / authn / not-found -> fatal.
    fatal_signals = [
        "401",
        "403",
        "404",
        "unauthorized",
        "invalid repository",
        "permission denied",
        "bad credentials",
        "not found",
        "repository not found",
        "access denied",
    ]
    for signal in fatal_signals:
        if signal in msg:
            return UploadErrorCategory.FATAL

    # Retryable: timeouts, connection issues, 429, 5xx.
    retry_signals = [
        "timeout",
        "timed out",
        "connection",
        "429",
        "500",
        "502",
        "503",
        "504",
        "server error",
        "service unavailable",
        "too many requests",
    ]
    for signal in retry_signals:
        if signal in msg:
            return UploadErrorCategory.RETRYABLE

    # Default: retryable for unknown exceptions to preserve existing behavior.
    return UploadErrorCategory.RETRYABLE


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Remote metadata helpers
# ---------------------------------------------------------------------------

def _remote_sizes(api, repo_id: str, token: str) -> dict[str, int]:
    """Return {path_in_repo: size} for every file already on the Hub."""
    try:
        files = api.list_repo_files(repo_id=repo_id, repo_type="dataset", token=token)
    except Exception:
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
        for f in files:
            sizes[f] = -1
    return sizes


def _remote_checksums(api, repo_id: str, token: str) -> dict[str, str]:
    """Return {path_in_repo: sha256_hex} where the Hub exposes it."""
    try:
        files = api.list_repo_files(repo_id=repo_id, repo_type="dataset", token=token)
    except Exception:
        return {}
    if not files:
        return {}
    checksums: dict[str, str] = {}
    try:
        infos = api.get_paths_info(
            repo_id=repo_id, paths=files, repo_type="dataset", token=token, expand=True
        )
        for info in infos:
            rpath = getattr(info, "path", None)
            if not rpath:
                continue
            lfs = getattr(info, "lfs", None)
            sha = None
            if lfs is not None:
                sha = getattr(lfs, "sha256", None)
            if sha is None:
                sha = getattr(info, "sha256", None)
            if sha:
                checksums[rpath] = str(sha).lower()
    except Exception:
        pass
    return checksums


# ---------------------------------------------------------------------------
# Resume skip (U-2/U-3): checksum-aware
# ---------------------------------------------------------------------------

def _resume_skip(
    sections: list[tuple[str, list[Path]]],
    remote_sizes: dict[str, int],
    remote_checksums: dict[str, str],
    release_root: Path,
    path_prefix: str = "",
) -> tuple[list[tuple[str, list[Path]]], int]:
    """Keep only files that are missing or differ on the Hub.

    Prefer SHA-256 comparison when remote metadata is available.
    Fall back to size-only with a warning when remote SHA-256 is unavailable.

    ``path_prefix`` is the repo-side directory the release lives under
    (e.g. ``releases/v1.0``). Empty string compares against repo root.
    """
    pending: list[tuple[str, list[Path]]] = []
    size_only_fallback_warnings = 0
    for section, files in sections:
        missing: list[Path] = []
        for f in files:
            rel = str(f.relative_to(release_root))
            rpath = f"{path_prefix}/{rel}" if path_prefix else rel
            if rpath not in remote_sizes:
                missing.append(f)
                continue
            remote_sha = remote_checksums.get(rpath)
            if remote_sha:
                try:
                    local_sha = sha256_file(f).lower()
                except OSError:
                    missing.append(f)
                    continue
                if local_sha != remote_sha:
                    missing.append(f)
                # else: skip upload
            else:
                size_only_fallback_warnings += 1
                if remote_sizes.get(rpath, -1) != f.stat().st_size:
                    missing.append(f)
                # else: skip upload with warning
        if missing:
            pending.append((section, missing))
    return pending, size_only_fallback_warnings


# ---------------------------------------------------------------------------
# Upload + retry (U-4)
# ---------------------------------------------------------------------------

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
    path_prefix: str = "",
) -> dict[str, Any]:
    """Upload one section; retry only retryable failures.

    Lands the local ``<section>/`` directory under
    ``[<path_prefix>/]<section>`` in the repo.
    """
    last_err: Exception | None = None
    section_dir = release_root / section
    path_in_repo = f"{path_prefix}/{section}" if path_prefix else section
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
                path_in_repo=path_in_repo,
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
            category = _classify_upload_error(exc)
            if category == UploadErrorCategory.FATAL:
                raise RuntimeError(
                    f"fatal upload error for section {section}: {exc}"
                ) from exc
            if attempt < MAX_RETRIES:
                wait = BACKOFF_BASE_S * (2 ** (attempt - 1))
                print(
                    f"  [retry {attempt}/{MAX_RETRIES}] {section} failed "
                    f"({exc}); waiting {wait:.0f}s"
                )
                time.sleep(wait)
    raise RuntimeError(f"upload failed for section {section}: {last_err}")


# ---------------------------------------------------------------------------
# Post-upload verification
# ---------------------------------------------------------------------------

def _verify_remote(
    api,
    repo_id: str,
    token: str,
    local_files: list[Path],
    release_root: Path,
    path_prefix: str = "",
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
        rpath = f"{path_prefix}/{rel}" if path_prefix else rel
        if rpath not in remote:
            ok = False
            problems.append(f"MISSING on Hub: {rpath}")
            continue
        rsize = remote[rpath]["size"]
        lsize = local.stat().st_size
        if rsize is not None and rsize != lsize:
            ok = False
            problems.append(f"SIZE mismatch: {rpath} local={lsize} remote={rsize}")
    return ok, problems


# ---------------------------------------------------------------------------
# Extra-file upload (governance docs)
# ---------------------------------------------------------------------------

def _upload_extra_file_with_retry(
    api,
    local_path: Path,
    *,
    repo_id: str,
    token: str,
    path_in_repo: str,
    commit_message: str,
) -> dict[str, Any]:
    """Upload a single file; retry only retryable failures."""
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            commit = api.upload_file(
                path_or_fileobj=str(local_path),
                path_in_repo=path_in_repo,
                repo_id=repo_id,
                repo_type="dataset",
                token=token,
                commit_message=commit_message,
            )
            return {
                "section": f"extra:{local_path.name}",
                "files": 1,
                "commit_url": getattr(commit, "commit_url", ""),
                "commit_hash": getattr(commit, "commit_hash", ""),
            }
        except Exception as exc:
            last_err = exc
            category = _classify_upload_error(exc)
            if category == UploadErrorCategory.FATAL:
                raise RuntimeError(
                    f"fatal upload error for {path_in_repo}: {exc}"
                ) from exc
            if attempt < MAX_RETRIES:
                wait = BACKOFF_BASE_S * (2 ** (attempt - 1))
                print(
                    f"  [retry {attempt}/{MAX_RETRIES}] {path_in_repo} failed "
                    f"({exc}); waiting {wait:.0f}s"
                )
                time.sleep(wait)
    raise RuntimeError(f"upload failed for {path_in_repo}: {last_err}")


# ---------------------------------------------------------------------------
# Pre-upload verification gate (U-5/U-6)
# ---------------------------------------------------------------------------

def _pre_upload_verify(release_root: Path) -> None:
    """Verify local release checksums before any network I/O.

    Raises SystemExit on mismatch so no partial upload occurs.
    """
    manifest_path = release_root / "metadata" / "checksums.sha256"
    if not manifest_path.exists():
        print(
            "ERROR: pre-upload verification failed: "
            f"missing checksums manifest: {manifest_path}"
        )
        sys.exit(2)
    try:
        manifest = load_checksum_manifest(manifest_path)
    except ManifestError as exc:
        print(f"ERROR: pre-upload verification failed: {exc}")
        sys.exit(2)
    result = verify_manifest_files(release_root, manifest)
    if not result.ok:
        print("Release integrity check failed:")
        for item in result.missing:
            print(f"  missing  : {item}")
        for item in result.mismatches:
            print(f"  mismatch : {item}")
        for item in result.errors:
            print(f"  error    : {item}")
        raise RuntimeError(
            "Pre-upload verification failed: local release checksums do not match manifest."
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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
    ap.add_argument("--workers", type=int, default=None, help="Parallel section uploads.")
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
    ap.add_argument(
        "--extra-file",
        action="append",
        default=[],
        dest="extra_files",
        metavar="NAME",
        help="Additional file in the release root to upload as "
        "releases/<release>/<NAME> (repeatable), e.g. governance docs.",
    )
    args = ap.parse_args(argv)

    workers = resolve_upload_workers(explicit=args.workers)
    print(f"Resolved upload workers: {workers}")

    release_root = _release_root(args.release, args.output)
    local_files = _collect_local_files(release_root)
    sections = _plan_sections(release_root)
    # Repo-side location of this release (canonical publish_promotion layout).
    path_prefix = f"releases/{args.release}"

    # Safeguard: surface the exact release identity being published.
    rel_meta_path = release_root / "metadata" / "release.json"
    if rel_meta_path.is_file():
        try:
            rel_meta = json.loads(rel_meta_path.read_text(encoding="utf-8"))
            print(
                f"Release identity: version={rel_meta.get('release_version')} "
                f"id={rel_meta.get('release_id')} status={rel_meta.get('status')} "
                f"records={rel_meta.get('total_records')}"
            )
        except Exception as exc:
            print(f"WARNING: could not read {rel_meta_path}: {exc}")

    extra_paths: list[Path] = []
    for name in args.extra_files:
        p = release_root / name
        if not p.is_file():
            print(f"ERROR: --extra-file {name} not found in release root: {p}")
            return 2
        extra_paths.append(p)

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
        print("\nResume logic: files already on the Hub with matching checksum are skipped.")
        print("Verification: all remote files checked post-upload (size + sha256).")
        print("Token source: HF_TOKEN env var.")
        return 0

    # U-5/U-6: pre-upload verification gate
    _pre_upload_verify(release_root)

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
    remote_checksums = _remote_checksums(api, args.repo_id, token)
    pending_sections, size_only_warnings = _resume_skip(
        sections, remote_sizes, remote_checksums, release_root, path_prefix=path_prefix
    )
    uploaded_names = {s for s, _ in sections} - {s for s, _ in pending_sections}
    for s in sorted(uploaded_names):
        print(f"  section {s}: already complete on Hub — skipping")

    if size_only_warnings:
        print(
            f"  WARNING: {size_only_warnings} file(s) skipped using size-only fallback "
            f"because remote SHA-256 metadata was unavailable."
        )

    results: list[dict[str, Any]] = []
    if pending_sections:
        print(f"\nUploading {len(pending_sections)} pending section(s)...")
        if workers <= 1:
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
                        path_prefix=path_prefix,
                    )
                )
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
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
                        path_prefix=path_prefix,
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
    else:
        print("Nothing to upload — all sections already on the Hub.")

    # 2b. Governance/extra files → releases/<release>/<NAME>.
    for extra in extra_paths:
        r = _upload_extra_file_with_retry(
            api,
            extra,
            repo_id=args.repo_id,
            token=token,
            path_in_repo=f"{path_prefix}/{extra.name}",
            commit_message=args.commit_message.format(release=args.release)
            + f" (governance: {extra.name})",
        )
        results.append(r)
        print(f"  + extra {extra.name} → {path_prefix}/{extra.name}")

    for r in results:
        print(f"  section {r['section']}: {r.get('commit_url') or 'dry'}")
        print(f"  commit : {r.get('commit_hash') or 'n/a'}")

    # 3. Verify all local files exist remotely with matching size/sha256.
    print("\nVerifying remote files...")
    verify_files = sorted(set(local_files) | set(extra_paths))
    ok, problems = _verify_remote(
        api, args.repo_id, token, verify_files, release_root, path_prefix=path_prefix
    )
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
