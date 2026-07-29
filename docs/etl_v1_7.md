# Atlas ETL v1.7 — Extract → Normalize → Clean

> **Status:** Implemented (gsm8k-first vertical slice)  
> **Depends on:** Downloader + Cache v1.6  
> **Outputs to:** `metadata/etl/<source_id>/` only — never `curated/`

---

## Pipeline

```
raw/.cache/ objects
        │
        ▼  Extractors (parquet / jsonl / json / html / markdown)
   extracted.jsonl
        │
        ▼  Normalizer → intermediate CanonicalRecord
   normalized.jsonl
        │
        ▼  Cleaners (malformed → length → PII → dedup → license)
   cleaned.jsonl
        │
        ▼  Promote (unverified) toward dataset_schema shape
   atlas_staging.jsonl
```

---

## Components

| Module | Path | Role |
|---|---|---|
| Extractors | `scripts/etl/extractors/` | Parse cached files → RawRecord |
| Normalizer | `scripts/etl/normalizer.py` | Canonical intermediate schema + Atlas promotion |
| Cleaners | `scripts/etl/cleaners/` | Dedup, PII redact/drop, malformed, license, length |
| Pipeline | `scripts/etl/pipeline.py` | Per-source ETL orchestration |
| ExtractAgent | `scripts/etl/extract_agent.py` | BaseAgent wrapper |
| CLI | `automation_runner etl` | Operator entry point |

### Parquet note
Parquet extraction requires optional `pyarrow` (`pip install pyarrow`). JSON/JSONL/HTML/Markdown are stdlib-only.

---

## CLI

```bash
# Process all sources that have download logs
python -m scripts.automation_runner etl

# gsm8k smoke (limit records)
python -m scripts.automation_runner etl --source-id c1 --limit 50

# Full gsm8k extract from cache
python -m scripts.automation_runner etl --source-id c1
```

Outputs land in:

```
metadata/etl/c1/
  extracted.jsonl
  normalized.jsonl
  cleaned.jsonl
  atlas_staging.jsonl
  dropped.json
  report.json
```

`atlas_staging.jsonl` records have `verified: false` — human review still required before curated release.

---

## Safety

- Never writes `curated/`, `review_queue/`, `training_views/`, or immutable raw trees
- Staging only under `metadata/etl/`
- Fail-closed when no cached files exist for a source

---

## Roadmap position

```
v1.6 Download/Cache  ✅
v1.7 Extract/Normalize/Clean  ✅  (this document)
v1.8 Transform + Training Views + Release Builder  ← next
```
