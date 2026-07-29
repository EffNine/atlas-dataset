# Atlas v1.8 — Transform + Training Views + Release Builder

> **Status:** Implemented  
> **Depends on:** ETL v1.7  
> **Writes:** `metadata/etl/*/transformed*.jsonl`, `metadata/views/`, `metadata/release_bundles/`  
> **Never writes:** `curated/` (promotion remains human-gated)

---

## Flow

```
cleaned.jsonl / atlas_staging.jsonl
        │
        ▼  Transform (5 types)
 transformed.jsonl + transformed_atlas.jsonl
        │
        ▼  View Builder (Qwen / Llama / DeepSeek + eval holdout)
 metadata/views/<version>/
        │
        ▼  Release Builder
 metadata/release_bundles/<version>/
   data/canonical.jsonl
   views/<model>/train.jsonl
   eval/holdout.jsonl
   README.md (dataset card)
   RELEASE_NOTES.md
   manifest.json (SHA-256)
```

---

## Training types

| Type | Source shapes |
|---|---|
| `instruction` | instruction/output, documentation text |
| `qa_pair` | question/answer |
| `reasoning` | QA with chain-of-thought markers (`<< >>`, `####`) |
| `conversation` | multi-turn messages |
| `knowledge` | factual knowledge objects from QA/docs |

---

## CLI

```bash
# Full orchestrated publish (staging mode)
python -m scripts.automation_runner publish \
  --version v0.3-gsm8k-demo --source-id c1 --limit 100

# Or step by step
python -m scripts.automation_runner transform --source-id c1 --limit 100
python -m scripts.automation_runner views --version v0.3-gsm8k-demo --source-id c1 --limit 100
python -m scripts.automation_runner release-build --version v0.3-gsm8k-demo --source-id c1
```

Production mode (requires approved curated records):

```bash
python -m scripts.automation_runner views --version v0.2 --curated-version v0.2 --production
python -m scripts.automation_runner release-build --version v0.2 --production
```

`--hub-publish` is accepted but currently a no-op stub (credentials not configured).

---

## Safety

- Staging bundles are explicitly **unverified**
- Production flags block when no approved records exist
- `curated/`, `review_queue/`, `training_views/` trees are not mutated by this stage  
  (materialized views live under `metadata/views/` until a future curated promotion)

---

## Roadmap

```
v1.7 ETL ✅
v1.8 Transform + Views + Release Builder ✅  (this document)
v1.9 Performance + Scale ← next
v2.0 Full e2e orchestration
```
