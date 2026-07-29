# Atlas Downloader v1.6 — Source Adapters + Cache Manager

> **Status:** Implemented on top of AcquisitionAgent v1  
> **Goal:** Enable Atlas to download data from external sources into a resumable, checksummed cache — not just record acquisition intent.

---

## What This Adds

| Component | Path | Role |
|---|---|---|
| Cache Manager | `scripts/downloader/cache.py` | Content-addressable store under `raw/.cache/` with SQLite index, resume, retry, SHA-256 verify |
| HTTP helpers | `scripts/downloader/http_util.py` | Stdlib urllib fetch with exponential backoff + Range resume |
| Source adapters | `scripts/downloader/adapters/` | HuggingFace, GitHub, Documentation, StackExchange, arXiv |
| DownloadAgent | `scripts/downloader/download_agent.py` | Routes acquired sources → adapters → cache |
| CLI | `automation_runner download` / `cache-stats` | Operator entry points |

---

## Cache Layout

```
raw/.cache/
  index.sqlite                 # O(1) source_ref → checksum lookups
  objects/{aa}/{sha256}        # content-addressable blobs
  partial/{ref_hash}.partial   # in-progress downloads (resumable)
  manifests/{ref_hash}.json    # multi-file download manifests
```

**Immutable protection:** never writes to `curated/`, `review_queue/`, `training_views/`, or immutable raw trees (`external/`, `generated/`, …). Download logs go to `metadata/download_logs/`.

---

## Adapters

| Adapter | Matches | Downloads |
|---|---|---|
| `huggingface` | `huggingface.co/datasets/…` | Hub API file list → selected files via `/resolve/main/` (default max 3 small/metadata files) |
| `github` | `github.com/owner/repo` | Public tarball via `codeload.github.com` |
| `documentation` | Generic HTTP(S) docs/pages | Full page body |
| `stackexchange` | StackExchange / archive.org dumps | Explicit `download_url` dump, else listing page |
| `arxiv` | arXiv abs/pdf IDs | PDF + Atom abstract metadata |

Adapters share one `CacheManager`. All network I/O goes through `download_url` / `put_bytes` so resume, checksum, and retry stay centralized.

---

## CLI Usage

```bash
# Plan downloads for sources with acquisition logs
python -m scripts.automation_runner download --mode dry-run

# Download acquired sources into the cache
python -m scripts.automation_runner download --mode download

# Limit to specific sources / HF file budget
python -m scripts.automation_runner download --mode download \
  --source-id s1 --source-id f4 --max-files 2

# Use accepted/review registry when no acquisition logs exist
python -m scripts.automation_runner download --mode dry-run --use-registry

# Cache inspection
python -m scripts.automation_runner cache-stats --list-entries
```

### Programmatic

```python
from downloader import DownloadAgent, CacheManager

agent = DownloadAgent(root, config={"mode": "download", "max_files": 2})
result = agent.execute()  # uses metadata/acquisition_logs/ + source_registry.json

# Or pass sources directly
result = agent.execute(context={"sources": [{"id": "x", "url": "https://example.com/a"}]})
```

---

## Safety & Design Rules

1. **Fail-closed** — missing acquisition logs without `--use-registry` fails rather than guessing.
2. **Deterministic** — same content → same SHA-256 object path.
3. **Idempotent** — re-running download hits the cache unless `--force`.
4. **Stdlib-first** — urllib + sqlite3 only (no `datasets` / requests dependency).
5. **Human gating preserved** — DownloadAgent consumes AcquisitionAgent outputs; it does not bypass APPROVE decisions.

---

## Tests

```bash
python -m pytest tests/test_downloader_v1_6.py -q
```

Coverage includes cache put/get/verify, Range resume, checksum mismatch, adapter routing, DownloadAgent dry-run/download modes, and immutable-tree protection. Integration downloads use a local `HTTPServer` fixture (no external network required).

---

## Roadmap Position

```
AcquisitionAgent v1  ✅
        ↓
Downloader + Cache v1.6  ✅  (this document)
        ↓
Extract + Normalize + Clean v1.7
        ↓
Transform + Training Views + Release Builder v1.8
        ↓
Performance + Scale v1.9
        ↓
Full E2E Automation v2.0
```

See `docs/roadmap/atlas_e2e_roadmap.md` for the full plan.
