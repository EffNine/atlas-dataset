#!/usr/bin/env python3
"""Tests for Atlas Downloader v1.6 — Cache Manager, adapters, DownloadAgent."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

from downloader.cache import CacheManager  # noqa: E402
from downloader.http_util import download_with_resume, sha256_file  # noqa: E402
from downloader.adapters.documentation import DocumentationAdapter  # noqa: E402
from downloader.adapters.github import GitHubAdapter  # noqa: E402
from downloader.adapters.arxiv import ArxivAdapter  # noqa: E402
from downloader.adapters.huggingface import HuggingFaceAdapter  # noqa: E402
from downloader.adapters.stackexchange import StackExchangeAdapter  # noqa: E402
from downloader.adapters.base import DownloadStatus  # noqa: E402
from downloader.download_agent import DownloadAgent  # noqa: E402
from automation.base_agent import AgentStatus  # noqa: E402


# ── local HTTP fixture ────────────────────────────────────────────────


class _Handler(BaseHTTPRequestHandler):
    payload = b"atlas-downloader-v1.6-fixture-content\n"
    fail_once = False
    _failed = False

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/fail-once"):
            if not _Handler._failed:
                _Handler._failed = True
                self.send_response(503)
                self.end_headers()
                return
        if self.path.startswith("/missing"):
            self.send_response(404)
            self.end_headers()
            return

        data = _Handler.payload
        range_hdr = self.headers.get("Range")
        if range_hdr and range_hdr.startswith("bytes="):
            start = int(range_hdr.split("=", 1)[1].split("-", 1)[0] or 0)
            chunk = data[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(chunk)
            return

        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):  # noqa: A003
        return


@pytest.fixture()
def http_server():
    _Handler._failed = False
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield f"http://{host}:{port}"
    server.shutdown()
    thread.join(timeout=2)


@pytest.fixture()
def atlas_root(tmp_path: Path) -> Path:
    root = tmp_path / "atlas"
    (root / "raw" / ".cache").mkdir(parents=True)
    (root / "metadata" / "acquisition_logs").mkdir(parents=True)
    (root / "curated").mkdir()
    (root / "review_queue").mkdir()
    (root / "training_views").mkdir()
    (root / "raw" / "external").mkdir(parents=True)
    return root


# ── Cache Manager ─────────────────────────────────────────────────────


def test_cache_put_bytes_and_get(atlas_root: Path):
    cache = CacheManager(atlas_root)
    entry = cache.put_bytes("demo:ref", b"hello-atlas", url="https://example.test", adapter="test")
    assert entry.checksum == hashlib.sha256(b"hello-atlas").hexdigest()
    assert cache.object_path(entry.checksum).exists()
    assert cache.verify("demo:ref") is True
    loaded = cache.get("demo:ref")
    assert loaded is not None
    assert loaded.size_bytes == 11


def test_cache_download_url_with_resume(atlas_root: Path, http_server: str):
    cache = CacheManager(atlas_root, max_retries=2, backoff_base=0.01)
    url = f"{http_server}/file.txt"

    # Seed a partial file (first 5 bytes) to force resume
    partial = cache.partial_path("resume:demo")
    partial.write_bytes(_Handler.payload[:5])

    entry = cache.download_url(url, "resume:demo", adapter="test")
    assert entry.size_bytes == len(_Handler.payload)
    assert entry.checksum == hashlib.sha256(_Handler.payload).hexdigest()
    assert cache.verify("resume:demo")

    # Second call is a cache hit
    again = cache.download_url(url, "resume:demo", adapter="test")
    assert again.checksum == entry.checksum


def test_cache_checksum_mismatch_raises(atlas_root: Path, http_server: str):
    cache = CacheManager(atlas_root, max_retries=1, backoff_base=0.01)
    with pytest.raises(ValueError, match="checksum mismatch"):
        cache.download_url(
            f"{http_server}/file.txt",
            "bad:checksum",
            expected_checksum="0" * 64,
        )


def test_download_with_resume_helper(tmp_path: Path, http_server: str):
    dest = tmp_path / "out.bin"
    dest.write_bytes(_Handler.payload[:8])
    result = download_with_resume(
        f"{http_server}/file.txt",
        dest,
        max_retries=1,
        backoff_base=0.01,
    )
    assert result.path.read_bytes() == _Handler.payload
    assert result.sha256 == sha256_file(dest)


# ── Adapters ──────────────────────────────────────────────────────────


def test_documentation_adapter_download(atlas_root: Path, http_server: str):
    cache = CacheManager(atlas_root, max_retries=1, backoff_base=0.01)
    adapter = DocumentationAdapter(cache)
    source = {"id": "doc1", "url": f"{http_server}/docs/page", "name": "fixture-docs"}
    assert adapter.supports(source)

    planned = adapter.download(source, dry_run=True)
    assert planned.status == DownloadStatus.PLANNED

    result = adapter.download(source, dry_run=False)
    assert result.status == DownloadStatus.DOWNLOADED
    assert result.entries[0].size_bytes == len(_Handler.payload)

    cached = adapter.download(source, dry_run=False)
    assert cached.status == DownloadStatus.CACHED


def test_adapter_supports_routing():
    cache = CacheManager.__new__(CacheManager)  # no init needed for supports()
    # Minimal stand-ins — supports() does not touch cache
    hf = HuggingFaceAdapter(cache)  # type: ignore[arg-type]
    gh = GitHubAdapter(cache)  # type: ignore[arg-type]
    ax = ArxivAdapter(cache)  # type: ignore[arg-type]
    se = StackExchangeAdapter(cache)  # type: ignore[arg-type]
    doc = DocumentationAdapter(cache)  # type: ignore[arg-type]

    assert hf.supports({"url": "https://huggingface.co/datasets/OpenAssistant/oasst1"})
    assert gh.supports({"url": "https://github.com/yizhongw/self-instruct"})
    assert ax.supports({"url": "https://arxiv.org/abs/1706.03762"})
    assert se.supports({"url": "https://archive.org/details/stackexchange", "name": "StackExchange"})
    assert doc.supports({"url": "https://docs.python.org/3/library/json.html"})
    assert not doc.supports({"url": "https://huggingface.co/datasets/x/y"})


# ── DownloadAgent ─────────────────────────────────────────────────────


def _seed_registry(root: Path, sources: list[dict]) -> None:
    (root / "metadata" / "source_registry.json").write_text(
        json.dumps({"sources": sources}, indent=2),
        encoding="utf-8",
    )


def test_download_agent_dry_run_from_acquisition_logs(atlas_root: Path, http_server: str):
    _seed_registry(
        atlas_root,
        [
            {
                "id": "d1",
                "name": "fixture/docs",
                "url": f"{http_server}/docs/page",
                "status": "accepted",
                "license": "MIT",
            }
        ],
    )
    (atlas_root / "metadata" / "acquisition_logs" / "d1.acquisition.json").write_text(
        json.dumps(
            {
                "packet_id": "d1",
                "source_id": "d1",
                "checksum": "abc",
                "status": "acquired",
            }
        ),
        encoding="utf-8",
    )

    agent = DownloadAgent(atlas_root, config={"mode": "dry-run"})
    result = agent.execute()
    assert result.status == AgentStatus.PASSED
    assert result.data["stats"]["planned"] == 1
    assert result.data["downloaded"][0]["adapter"] == "documentation"


def test_download_agent_download_mode(atlas_root: Path, http_server: str):
    _seed_registry(
        atlas_root,
        [
            {
                "id": "d1",
                "name": "fixture/docs",
                "url": f"{http_server}/docs/page",
                "status": "accepted",
                "license": "MIT",
            }
        ],
    )
    (atlas_root / "metadata" / "acquisition_logs" / "d1.acquisition.json").write_text(
        json.dumps({"packet_id": "d1", "source_id": "d1", "status": "acquired"}),
        encoding="utf-8",
    )

    agent = DownloadAgent(
        atlas_root,
        config={"mode": "download", "max_retries": 1, "backoff_base": 0.01},
    )
    result = agent.execute()
    assert result.status == AgentStatus.PASSED
    assert result.data["stats"]["downloaded"] == 1
    log = atlas_root / "metadata" / "download_logs" / "d1.download.json"
    assert log.exists()
    # Immutable trees untouched
    assert list((atlas_root / "curated").iterdir()) == []
    assert list((atlas_root / "raw" / "external").iterdir()) == []


def test_download_agent_context_sources(atlas_root: Path, http_server: str):
    agent = DownloadAgent(
        atlas_root,
        config={"mode": "download", "max_retries": 1, "backoff_base": 0.01},
    )
    result = agent.execute(
        context={
            "sources": [
                {
                    "id": "ctx1",
                    "url": f"{http_server}/docs/page",
                    "name": "context-doc",
                }
            ]
        }
    )
    assert result.status == AgentStatus.PASSED
    assert result.data["stats"]["downloaded"] == 1


def test_download_agent_requires_sources(atlas_root: Path):
    agent = DownloadAgent(atlas_root, config={"mode": "dry-run"})
    result = agent.execute()
    assert result.status == AgentStatus.FAILED
    assert any("no acquisition logs" in e for e in result.errors)
