#!/usr/bin/env python3
"""Cache Manager for Atlas Downloader v1.6.

Content-addressable download cache under ``raw/.cache/`` with:
  - SHA-256 verification of every stored object
  - HTTP Range resume for interrupted transfers
  - Exponential-backoff retry
  - SQLite index for O(1) source_ref lookups

Design constraints:
  - Never writes to curated/, review_queue/, training_views/
  - Never mutates immutable raw source trees (external/generated/…)
  - Cache lives only under raw/.cache/
  - Deterministic: same URL + same content → same checksum path
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .http_util import (
    DEFAULT_BACKOFF_BASE,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    download_with_resume,
    sha256_file,
)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CacheEntry:
    """One indexed cache object."""

    source_ref: str
    checksum: str
    rel_path: str
    size_bytes: int
    url: str = ""
    adapter: str = ""
    content_type: str | None = None
    created_at: str = ""
    verified_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CacheManager:
    """Content-addressable cache with SQLite index.

    Layout::

        raw/.cache/
          index.sqlite
          objects/{aa}/{sha256}
          partial/{source_ref_hash}.partial
          manifests/{source_ref_hash}.json   # optional multi-file manifests

    Args:
        root: Atlas repository root.
        cache_dir: Override cache location (defaults to ``raw/.cache``).
        max_retries: Retry budget for network transfers.
        timeout: Per-request timeout seconds.
        backoff_base: Exponential backoff base (seconds).
    """

    def __init__(
        self,
        root: str | Path,
        cache_dir: str | Path | None = None,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
    ) -> None:
        self.root = Path(root).resolve()
        self.cache_dir = Path(cache_dir).resolve() if cache_dir else (self.root / "raw" / ".cache")
        self.objects_dir = self.cache_dir / "objects"
        self.partial_dir = self.cache_dir / "partial"
        self.manifests_dir = self.cache_dir / "manifests"
        self.index_path = self.cache_dir / "index.sqlite"
        self.max_retries = max_retries
        self.timeout = timeout
        self.backoff_base = backoff_base

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.partial_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── public API ────────────────────────────────────────────────────

    def get(self, source_ref: str) -> CacheEntry | None:
        """Return a cache entry if present and the object file still exists."""
        row = self._fetch_row(source_ref)
        if row is None:
            return None
        entry = self._row_to_entry(row)
        obj = self.object_path(entry.checksum)
        if not obj.exists():
            self._delete_row(source_ref)
            return None
        return entry

    def has(self, source_ref: str) -> bool:
        return self.get(source_ref) is not None

    def object_path(self, checksum: str) -> Path:
        """Absolute path for a content-addressed object."""
        return self.objects_dir / checksum[:2] / checksum

    def verify(self, source_ref: str) -> bool:
        """Re-hash the stored object and confirm it matches the index."""
        entry = self.get(source_ref)
        if entry is None:
            return False
        path = self.object_path(entry.checksum)
        actual = sha256_file(path)
        if actual != entry.checksum:
            return False
        self._touch_verified(source_ref)
        return True

    def put_bytes(
        self,
        source_ref: str,
        data: bytes,
        *,
        url: str = "",
        adapter: str = "",
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CacheEntry:
        """Store raw bytes under content-addressable path and index them."""
        checksum = hashlib.sha256(data).hexdigest()
        dest = self.object_path(checksum)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            tmp = dest.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(dest)
        return self._upsert_entry(
            source_ref=source_ref,
            checksum=checksum,
            size_bytes=len(data),
            url=url,
            adapter=adapter,
            content_type=content_type,
            metadata=metadata or {},
        )

    def put_file(
        self,
        source_ref: str,
        path: Path,
        *,
        checksum: str | None = None,
        url: str = "",
        adapter: str = "",
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        move: bool = False,
    ) -> CacheEntry:
        """Ingest an existing local file into the content-addressable store."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        checksum = checksum or sha256_file(path)
        dest = self.object_path(checksum)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            if move:
                path.replace(dest)
            else:
                shutil.copy2(path, dest)
        elif move and path.resolve() != dest.resolve():
            path.unlink(missing_ok=True)
        return self._upsert_entry(
            source_ref=source_ref,
            checksum=checksum,
            size_bytes=dest.stat().st_size,
            url=url,
            adapter=adapter,
            content_type=content_type,
            metadata=metadata or {},
        )

    def download_url(
        self,
        url: str,
        source_ref: str,
        *,
        expected_checksum: str | None = None,
        headers: Mapping[str, str] | None = None,
        adapter: str = "",
        metadata: dict[str, Any] | None = None,
        force: bool = False,
    ) -> CacheEntry:
        """Download *url* into the cache (resume + retry + verify).

        If *source_ref* is already cached and ``force`` is False, returns the
        existing entry after a quick existence check (no re-download).
        """
        if not force:
            existing = self.get(source_ref)
            if existing is not None:
                if expected_checksum and existing.checksum != expected_checksum:
                    raise ValueError(
                        f"cached checksum mismatch for {source_ref}: "
                        f"expected {expected_checksum}, got {existing.checksum}"
                    )
                return existing

        partial = self.partial_path(source_ref)
        result = download_with_resume(
            url,
            partial,
            headers=headers,
            timeout=self.timeout,
            max_retries=self.max_retries,
            backoff_base=self.backoff_base,
        )

        if expected_checksum and result.sha256 != expected_checksum:
            partial.unlink(missing_ok=True)
            raise ValueError(
                f"checksum mismatch for {source_ref}: "
                f"expected {expected_checksum}, got {result.sha256}"
            )

        entry = self.put_file(
            source_ref,
            partial,
            checksum=result.sha256,
            url=url,
            adapter=adapter,
            content_type=result.content_type,
            metadata={
                **(metadata or {}),
                "resumed": result.resumed,
                "status_code": result.status_code,
                "bytes_written": result.bytes_written,
            },
            move=True,
        )
        return entry

    def write_manifest(self, source_ref: str, files: list[dict[str, Any]]) -> Path:
        """Persist a multi-file download manifest keyed by source_ref."""
        path = self.manifest_path(source_ref)
        doc = {
            "source_ref": source_ref,
            "generated_at": _ts(),
            "files": files,
            "file_count": len(files),
        }
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def read_manifest(self, source_ref: str) -> dict[str, Any] | None:
        path = self.manifest_path(source_ref)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def purge(self, source_ref: str, *, delete_object: bool = False) -> bool:
        """Remove index entry (and optionally the object file if unreferenced)."""
        entry = self.get(source_ref)
        if entry is None:
            return False
        self._delete_row(source_ref)
        self.manifest_path(source_ref).unlink(missing_ok=True)
        self.partial_path(source_ref).unlink(missing_ok=True)
        if delete_object and not self._checksum_referenced(entry.checksum):
            self.object_path(entry.checksum).unlink(missing_ok=True)
        return True

    def stats(self) -> dict[str, Any]:
        """Aggregate cache statistics."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM cache_entries"
            ).fetchone()
        object_count = sum(1 for _ in self.objects_dir.rglob("*") if _.is_file())
        return {
            "cache_dir": str(self.cache_dir),
            "entries": int(row[0]),
            "total_bytes": int(row[1]),
            "object_files": object_count,
            "index_path": str(self.index_path),
        }

    def list_entries(self) -> list[CacheEntry]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM cache_entries ORDER BY source_ref").fetchall()
        return [self._row_to_entry(r) for r in rows]

    def partial_path(self, source_ref: str) -> Path:
        digest = hashlib.sha256(source_ref.encode("utf-8")).hexdigest()
        return self.partial_dir / f"{digest}.partial"

    def manifest_path(self, source_ref: str) -> Path:
        digest = hashlib.sha256(source_ref.encode("utf-8")).hexdigest()
        return self.manifests_dir / f"{digest}.json"

    # ── SQLite ────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.index_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    source_ref   TEXT PRIMARY KEY,
                    checksum     TEXT NOT NULL,
                    rel_path     TEXT NOT NULL,
                    size_bytes   INTEGER NOT NULL,
                    url          TEXT,
                    adapter      TEXT,
                    content_type TEXT,
                    created_at   TEXT NOT NULL,
                    verified_at  TEXT,
                    metadata_json TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cache_checksum ON cache_entries(checksum)"
            )
            conn.commit()

    def _fetch_row(self, source_ref: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM cache_entries WHERE source_ref = ?",
                (source_ref,),
            ).fetchone()

    def _delete_row(self, source_ref: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM cache_entries WHERE source_ref = ?", (source_ref,))
            conn.commit()

    def _checksum_referenced(self, checksum: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM cache_entries WHERE checksum = ? LIMIT 1",
                (checksum,),
            ).fetchone()
        return row is not None

    def _touch_verified(self, source_ref: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE cache_entries SET verified_at = ? WHERE source_ref = ?",
                (_ts(), source_ref),
            )
            conn.commit()

    def _upsert_entry(
        self,
        *,
        source_ref: str,
        checksum: str,
        size_bytes: int,
        url: str,
        adapter: str,
        content_type: str | None,
        metadata: dict[str, Any],
    ) -> CacheEntry:
        rel_path = f"objects/{checksum[:2]}/{checksum}"
        now = _ts()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cache_entries (
                    source_ref, checksum, rel_path, size_bytes, url, adapter,
                    content_type, created_at, verified_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_ref) DO UPDATE SET
                    checksum=excluded.checksum,
                    rel_path=excluded.rel_path,
                    size_bytes=excluded.size_bytes,
                    url=excluded.url,
                    adapter=excluded.adapter,
                    content_type=excluded.content_type,
                    verified_at=excluded.verified_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    source_ref,
                    checksum,
                    rel_path,
                    size_bytes,
                    url,
                    adapter,
                    content_type,
                    now,
                    now,
                    json.dumps(metadata, sort_keys=True),
                ),
            )
            conn.commit()
        return CacheEntry(
            source_ref=source_ref,
            checksum=checksum,
            rel_path=rel_path,
            size_bytes=size_bytes,
            url=url,
            adapter=adapter,
            content_type=content_type,
            created_at=now,
            verified_at=now,
            metadata=metadata,
        )

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> CacheEntry:
        meta_raw = row["metadata_json"] or "{}"
        try:
            metadata = json.loads(meta_raw)
        except json.JSONDecodeError:
            metadata = {}
        return CacheEntry(
            source_ref=row["source_ref"],
            checksum=row["checksum"],
            rel_path=row["rel_path"],
            size_bytes=int(row["size_bytes"]),
            url=row["url"] or "",
            adapter=row["adapter"] or "",
            content_type=row["content_type"],
            created_at=row["created_at"] or "",
            verified_at=row["verified_at"] or "",
            metadata=metadata if isinstance(metadata, dict) else {},
        )
