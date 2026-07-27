#!/usr/bin/env python3
"""
atlas_paths.py — Canonical project path registry for Atlas.

Centralizes all project-root-relative path construction so that every
consumer uses the same path references. Prevents hardcoded path drift.

This module is stdlib-only and importable from anywhere in the project.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Repository root discovery
# ---------------------------------------------------------------------------


def discover_root(marker_file: Path | None = None) -> Path:
    """Discover the atlas-dataset repository root.

    Walks up from the caller's working directory or __file__ location,
    looking for the marker file (scripts/atlas.py by default).

    Returns:
        Absolute Path to the repository root.

    Raises:
        RuntimeError: If root cannot be determined.
    """
    if marker_file is None:
        marker_file = Path("scripts") / "atlas.py"

    # Candidate starting points
    import __main__
    candidates: list[Path] = []
    try:
        candidates.append(Path.cwd())
    except Exception:
        pass
    try:
        candidates.append(Path(__main__.__file__).resolve().parent.parent)
    except Exception:
        pass
    # If invoked from within the package, use the module file location
    candidates.append(Path(__file__).resolve().parent.parent)

    for c in candidates:
        resolved = c.resolve()
        for ancestor in [resolved] + list(resolved.parents):
            check = ancestor / marker_file
            if check.exists():
                return ancestor

    raise RuntimeError(
        "Cannot determine atlas-dataset root. "
        "Run from within the repository or set ATLAS_ROOT."
    )


def get_root() -> Path:
    """Get the project root, cached after first call."""
    if _ROOT_CACHE.get("root") is None:
        _ROOT_CACHE["root"] = discover_root()
    return _ROOT_CACHE["root"]


# Cached root — populated on first call to get_root()
_ROOT_CACHE: dict[str, Path] = {}


# ---------------------------------------------------------------------------
# Named path factories
# ---------------------------------------------------------------------------


def scripts_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "scripts"


def schemas_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "schemas"


def metadata_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "metadata"


def curated_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "curated"


def review_queue_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "review_queue"


def review_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "review"


def training_views_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "training_views"


def docs_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "docs"


def tmp_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "tmp"


def raw_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "raw"


def raw_pilot_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "raw" / "pilot"


def migrations_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "migrations"


def knowledge_packs_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "knowledge_packs"


def acquisitions_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return scripts_dir(root) / "acquisition_engine"


def releases_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return metadata_dir(root) / "releases"


# ---------------------------------------------------------------------------
# Individual file references
# ---------------------------------------------------------------------------


def dataset_schema_path(root: Path | None = None) -> Path:
    return schemas_dir(root) / "dataset_schema.json"


def knowledge_object_schema_path(root: Path | None = None) -> Path:
    return schemas_dir(root) / "knowledge_object_schema.json"


def chat_schema_path(root: Path | None = None) -> Path:
    return schemas_dir(root) / "chat_schema.json"


def categories_metadata_path(root: Path | None = None) -> Path:
    return metadata_dir(root) / "categories.json"


def acquisition_manifest_path(root: Path | None = None) -> Path:
    return metadata_dir(root) / "acquisition_manifest_v0.1.json"


def ingestion_plan_path(root: Path | None = None) -> Path:
    return metadata_dir(root) / "ingestion_plan_v0.1.json"


def release_index_path(root: Path | None = None) -> Path:
    return metadata_dir(root) / "release_index.json"


def engine_checksums_path(root: Path | None = None) -> Path:
    return metadata_dir(root) / "engine_checksums.json"


def lifecycle_state_path(root: Path | None = None) -> Path:
    return metadata_dir(root) / "lifecycle_state.json"


def config_policy_path(root: Path | None = None) -> Path:
    return metadata_dir(root) / "config_policy_v1.json"


def pilot_seed_path(root: Path | None = None) -> Path:
    return raw_pilot_dir(root) / "seed.jsonl"


def pilot_candidates_path(version: str = "v0.1", root: Path | None = None) -> Path:
    return curated_dir(root) / version / "pilot_candidates.jsonl"


def release_manifest_path(version: str, root: Path | None = None) -> Path:
    return releases_dir(root) / f"{version}_release.json"


# ---------------------------------------------------------------------------
# Approved write roots (for the write guard)
# ---------------------------------------------------------------------------

APPROVED_WRITE_ROOTS: tuple[str, ...] = (
    "curated",
    "review_queue",
    "training_views",
    "metadata",
    "docs",
    "tmp",
    "raw/pilot",
    "migrations",
    "knowledge_packs",
)


def approved_write_paths(root: Path | None = None) -> list[Path]:
    """Return the list of approved write-root paths."""
    if root is None:
        root = get_root()
    result = []
    for rel in APPROVED_WRITE_ROOTS:
        parts = rel.split("/")
        p = root
        for part in parts:
            p = p / part
        result.append(p)
    return result


def is_write_safe(target: Path, root: Path | None = None) -> bool:
    """Check if a write target is within an approved root."""
    if root is None:
        root = get_root()
    resolved = target.resolve()
    for approved in approved_write_paths(root):
        try:
            if str(resolved).startswith(str(approved.resolve())):
                return True
        except (OSError, ValueError):
            continue
    return False


# ---------------------------------------------------------------------------
# Path resolution helper for scripts that don't have a ROOT reference
# ---------------------------------------------------------------------------


def resolve_from_script(script_file: str, levels_up: int = 1) -> Path:
    """Resolve a path relative to a script's location.

    Args:
        script_file: __file__ from the calling script.
        levels_up: How many parent levels to go up to reach project root.
                  Default 1 (script in scripts/ subdir).

    Returns:
        Absolute project root path.
    """
    return Path(script_file).resolve().parents[levels_up - 1]
