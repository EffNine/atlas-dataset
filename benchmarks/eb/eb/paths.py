#!/usr/bin/env python3
"""
paths.py — EB-specific path resolution.

Discovers the EB root directory and provides path helpers for all
EB subdirectories. Independent from Atlas's atlas_paths.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Root discovery
# ---------------------------------------------------------------------------

_EB_ROOT_CACHE: dict[str, Path] = {}


def discover_eb_root(marker_file: Path | None = None) -> Path:
    """Discover the EB root directory.

    Walks up from the caller's location looking for pyproject.toml
    inside an directory named "eb".  The marker file defaults to the
    package's own pyproject.toml location.

    Returns:
        Absolute Path to the EB root directory.

    Raises:
        RuntimeError: If root cannot be determined.
    """
    if marker_file is None:
        marker_file = Path("pyproject.toml")

    # Start from the module's own location — go up two levels:
    #   eb/eb/paths.py -> eb/eb/ -> benchmarks/eb/
    candidates: list[Path] = []
    try:
        import __main__
        candidates.append(Path.cwd())
    except Exception:
        pass

    # Use the module file location as the primary anchor
    module_dir = Path(__file__).resolve().parent
    candidates.append(module_dir)
    candidates.append(module_dir.parent)   # eb/ (the Python package dir)
    candidates.append(module_dir.parent.parent)  # benchmarks/eb/

    for c in candidates:
        resolved = c.resolve()
        for ancestor in [resolved] + list(resolved.parents):
            check = ancestor / marker_file
            if check.exists():
                # Verify this is actually the EB root by checking for the
                # characteristic subdirectory layout
                if (ancestor / "eb").exists() or ancestor == resolved:
                    return ancestor

    raise RuntimeError(
        "Cannot determine EB root. "
        "Run from within benchmarks/eb/ or set EB_ROOT environment variable."
    )


def get_root() -> Path:
    """Get the EB root, cached after first call."""
    key = "eb_root"
    if _EB_ROOT_CACHE.get(key) is None:
        _EB_ROOT_CACHE[key] = discover_eb_root()
    return _EB_ROOT_CACHE[key]


def reset_root_cache() -> None:
    """Clear the root cache (useful in tests)."""
    _EB_ROOT_CACHE.clear()


# ---------------------------------------------------------------------------
# Named path factories
# ---------------------------------------------------------------------------


def tasks_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "tasks"


def outputs_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "outputs"


def runs_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return outputs_dir(root) / "runs"


def metadata_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "metadata"


def config_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "config"


def reports_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "reports"


def repositories_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return root / "repositories"


def templates_dir(root: Path | None = None) -> Path:
    if root is None:
        root = get_root()
    return reports_dir(root) / "templates"


# ---------------------------------------------------------------------------
# Approved write roots
# ---------------------------------------------------------------------------

APPROVED_WRITE_ROOTS: tuple[str, ...] = (
    "outputs",
    "metadata",
    "reports",
    "tasks",
    "config",
    "tests",
    "docs",
    "tmp",
)


def approved_write_paths(root: Path | None = None) -> list[Path]:
    """Return the list of approved write-root paths."""
    if root is None:
        root = get_root()
    result = []
    for rel in APPROVED_WRITE_ROOTS:
        p = root / rel
        if p.exists():
            result.append(p)
    return result


def is_write_safe(target: Path, root: Path | None = None) -> bool:
    """Check if a write target is within an approved write root."""
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
