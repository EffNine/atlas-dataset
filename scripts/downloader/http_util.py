#!/usr/bin/env python3
"""HTTP helpers for Atlas Downloader v1.6 — retry + resumable transfers.

Stdlib-only (urllib). Used by CacheManager and source adapters.
"""

from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping


DEFAULT_USER_AGENT = "AtlasDatasetDownloader/1.6 (+https://github.com/EffNine/atlas-dataset)"
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 0.5  # seconds; doubles each attempt


@dataclass
class HttpFetchResult:
    """Result of a (possibly resumed) HTTP download to a local path."""

    path: Path
    bytes_written: int
    sha256: str
    status_code: int
    content_type: str | None
    resumed: bool
    url: str


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute SHA-256 of a file without loading it entirely into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_opener(headers: Mapping[str, str] | None = None) -> urllib.request.OpenerDirector:
    """Build a urllib opener that always sends a polite User-Agent."""
    merged = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        merged.update({str(k): str(v) for k, v in headers.items()})
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(),
        urllib.request.HTTPHandler(),
        _HeaderInjector(merged),
    )


class _HeaderInjector(urllib.request.BaseHandler):
    def __init__(self, headers: Mapping[str, str]) -> None:
        self._headers = dict(headers)

    def http_request(self, req: urllib.request.Request) -> urllib.request.Request:
        for key, value in self._headers.items():
            if req.get_header(key) is None and req.has_header(key) is False:
                req.add_header(key, value)
        return req

    https_request = http_request


def fetch_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bytes, int, str | None]:
    """GET *url* and return ``(body, status_code, content_type)`` with retries."""
    opener = build_opener(headers)
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(url, method="GET")
            with opener.open(req, timeout=timeout) as resp:
                body = resp.read()
                status = getattr(resp, "status", None) or resp.getcode() or 200
                content_type = resp.headers.get("Content-Type")
                return body, int(status), content_type
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            # Do not retry permanent client errors except 408/429
            if isinstance(exc, urllib.error.HTTPError) and exc.code in {400, 401, 403, 404, 410}:
                raise
            if attempt >= max_retries:
                break
            sleep(backoff_base * (2 ** attempt))

    assert last_error is not None
    raise last_error


def download_with_resume(
    url: str,
    dest: Path,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    chunk_size: int = 1024 * 256,
    sleep: Callable[[float], None] = time.sleep,
) -> HttpFetchResult:
    """Download *url* to *dest*, resuming via HTTP Range when a partial exists.

    Writes to ``dest`` (creating parents). On success returns checksum of the
    final file. Partial progress is kept in ``dest`` itself so a crash mid-
    transfer can resume on the next call.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    opener = build_opener(headers)
    last_error: Exception | None = None
    resumed = False
    status_code = 200
    content_type: str | None = None
    bytes_written = 0

    for attempt in range(max_retries + 1):
        existing = dest.stat().st_size if dest.exists() else 0
        req_headers = dict(headers or {})
        if existing > 0:
            req_headers["Range"] = f"bytes={existing}-"
            resumed = True

        try:
            req = urllib.request.Request(url, method="GET", headers=req_headers)
            with opener.open(req, timeout=timeout) as resp:
                status_code = int(getattr(resp, "status", None) or resp.getcode() or 200)
                content_type = resp.headers.get("Content-Type")

                # Server ignored Range → restart from scratch
                if existing > 0 and status_code == 200:
                    existing = 0
                    resumed = False
                    mode = "wb"
                elif existing > 0 and status_code == 206:
                    mode = "ab"
                else:
                    mode = "wb" if existing == 0 else "ab"

                with dest.open(mode) as out:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        out.write(chunk)
                        bytes_written += len(chunk)

            checksum = sha256_file(dest)
            return HttpFetchResult(
                path=dest,
                bytes_written=bytes_written if bytes_written else dest.stat().st_size,
                sha256=checksum,
                status_code=status_code,
                content_type=content_type,
                resumed=resumed and existing > 0,
                url=url,
            )
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in {400, 401, 403, 404, 410}:
                raise
            if attempt >= max_retries:
                break
            sleep(backoff_base * (2 ** attempt))

    assert last_error is not None
    raise last_error
