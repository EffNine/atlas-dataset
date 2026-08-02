#!/usr/bin/env python3
"""Shared helpers for the Atlas Hugging Face release pipeline.

Stdlib + zstandard only. No hardcoded tokens or paths.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

try:
    import zstandard as zstd
except ImportError:  # pragma: no cover
    zstd = None

# Canonical Atlas category order (matches metadata/categories.json).
CATEGORIES: list[str] = [
    "01_foundation",
    "02_software_engineering",
    "03_system_engineering",
    "04_ai_machine_learning",
    "05_hardware_engineering",
    "06_science_engineering",
    "07_business_knowledge",
    "08_creative_knowledge",
    "09_personal_assistant",
]

# zstd compression level used by default (good ratio; 22 = max).
DEFAULT_ZSTD_LEVEL = 19

# Repo root (scripts/release/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


from verify_sha256 import sha256_file as _sha256_file  # noqa: E402


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """SHA-256 of a file, streamed (O(1) memory)."""
    return _sha256_file(path, chunk_size=chunk_size)


def iter_jsonl(path: Path) -> Iterator[dict]:
    """Yield parsed JSON objects from a JSONL file, line by line."""
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def open_zstd_writer(path: Path, level: int = DEFAULT_ZSTD_LEVEL):
    """Return a binary writer that compresses with zstd.

    Must be closed by the caller. Raises RuntimeError if zstandard is missing.
    """
    if zstd is None:
        raise RuntimeError(
            "zstandard is required. Install it in the release venv: "
            "python -m pip install zstandard"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    compressor = zstd.ZstdCompressor(level=level)
    return compressor.stream_writer(open(path, "wb"))


@contextlib.contextmanager
def open_zstd_reader(path: Path):
    """Context manager yielding an iterator of raw bytes lines from a .zst file.

    Usage:
        with open_zstd_reader(path) as reader:
            for raw_line in reader:   # raw_line is bytes, newline stripped
                ...

    O(1) memory; the file handle is closed on context exit. Raises
    RuntimeError if zstandard is missing.
    """
    if zstd is None:
        raise RuntimeError("zstandard is required for .zst reading")
    fh = open(path, "rb")
    try:
        dctx = zstd.ZstdDecompressor()
        reader = dctx.stream_reader(fh)

        def _lines():
            buf = bytearray()
            while True:
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                buf.extend(chunk)
                while b"\n" in buf:
                    line, _, rest = buf.partition(b"\n")
                    yield bytes(line)
                    buf = bytearray(rest)
            if buf.strip():
                yield bytes(buf)

        yield _lines()
    finally:
        fh.close()


def count_jsonl_zst(path: Path) -> int:
    """Decompress a .jsonl.zst file and count non-empty lines.

    Streams; O(1) memory. Raises on corrupt frames.
    """
    if zstd is None:
        raise RuntimeError("zstandard is required for .zst verification")
    with open(path, "rb") as fh:
        dctx = zstd.ZstdDecompressor()
        reader = dctx.stream_reader(fh)
        count = 0
        # Reuse a bytearray to avoid per-line allocation churn.
        buf = bytearray()
        while True:
            chunk = reader.read(1024 * 1024)
            if not chunk:
                break
            buf.extend(chunk)
            while b"\n" in buf:
                line, _, rest = buf.partition(b"\n")
                if line.strip():
                    count += 1
                buf = bytearray(rest)
        if buf.strip():
            count += 1
    return count


def require_env(name: str) -> str:
    """Return env var value or raise with a clear message."""
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(
            f"ERROR: environment variable {name} is not set.\n"
            f"Set it first, e.g.  export {name}=hf_xxx  (or read it from a "
            f"secret manager). Never hardcode tokens in scripts."
        )
    return value


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"
