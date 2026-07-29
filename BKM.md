# Atlas Dataset — BKM (Best Known Method)

> **Panduan praktikal如何使用 Atlas — dari daily operation sampai pipeline release.**

---

## 1. Apa Itu Atlas?

Atlas adalah dataset factory. Dia ambil **raw knowledge**, proses jadi **clean curated dataset**, dan boleh **convert ke format model** macam Qwen / Llama / Mistral.

```
Raw → Clean → Dedup → Score → Review → Curated → Convert
```

Semua data versioned, checksummed, dan ada provenance trail.

---

## 2. Struktur Ringkas

| Folder | Isi | Boleh modify? |
|---|---|---|
| `raw/` | Source asal (external, generated, conversations) | ❌ Immutable |
| `processing/` | Cleaners, validators, converters | ✅ Scripts |
| `curated/v0.1/` | Data dah review | ❌ Read-only |
| `curated/v0.2/` | Expansion data | ❌ Read-only |
| `review/` | Human review artifacts | ✅ Untuk review |
| `review_queue/` | Queue state | ✅ Untuk proses |
| `schemas/` | JSON Schema | ✅ Bila perlu |
| `configs/` | Templates forat | ✅ Bila perlu |
| `metadata/` | Semua metadata, release manifest, acquisition logs | ✅ Scripts update |
| `scripts/` | Semua kod pipeline | ✅ Bila develop |

---

## 3. Daily Workflow

### 3.1 Check Status Pipeline

```bash
# Self-test — verify semua invariant
python scripts/atlas.py self-test

# Check automation pipeline status
python -m scripts.automation_runner status --pipeline-id release-v0.3

# Check pipeline state file
cat metadata/pipeline_state/release-v0.3.json
```

### 3.2 Validate Data

```bash
# Validate file against schema
python scripts/validate_dataset.py --input curated/v0.2/data/v0.2_full.jsonl

# Stats report (category balance)
python scripts/validate_dataset.py --input curated/v0.2/data/v0.2_full.jsonl --stats

# Strict mode (verified + quality_score >= 8.5)
python scripts/validate_knowledge_object.py --input curated/v0.2/data/v0.2_full.jsonl --strict
```

### 3.3 Quality Score

```bash
# Score file
python scripts/quality_score.py --input curated/v0.2/data/v0.2_full.jsonl

# Score with full evaluation report
python scripts/quality_score.py --input curated/v0.2/data/v0.2_full.jsonl --full
```

### 3.4 Deduplicate

```bash
# Report sahaja
python scripts/dedup_dataset.py --input curated/v0.2/data/v0.2_full.jsonl --report

# Drop duplicates (simpan higher quality)
python scripts/dedup_dataset.py --input curated/v0.2/data/v0.2_full.jsonl --drop --output tmp/deduped.jsonl
```

### 3.5 Convert Format

```bash
# List available formats
python scripts/convert_format.py --list

# Convert to Qwen ChatML
python scripts/convert_format.py --format qwen_chatml \
    --input curated/v0.2/data/v0.2_full.jsonl --output tmp/qwen.jsonl

# Convert to Llama
python scripts/convert_format.py --format llama_instruction \
    --input curated/v0.2/data/v0.2_full.jsonl --output tmp/llama.jsonl
```

---

## 4. Adding New Data

### 4.1 Letak Raw Source

```
raw/external/<nama-source>/
raw/generated/<nama-file>.jsonl
raw/documentation/<topik>.jsonl
```

Setiap record kena ada:
```json
{
  "source": {
    "name": "nama-source",
    "license": "CC-BY-4.0",
    "url": "https://..."
  }
}
```

> **License gate:** `cc-by-nc*`, `cc-by-nd*`, `proprietary`, `all-rights-reserved`, `unknown` — **AUTO REJECT**.

### 4.2 Clean & Process

```bash
python scripts/clean_dataset.py --input raw/generated/draft.jsonl --output tmp/cleaned.jsonl
python scripts/dedup_dataset.py --input tmp/cleaned.jsonl --drop --output tmp/deduped.jsonl
python scripts/validate_dataset.py --input tmp/deduped.jsonl --stats
python scripts/quality_score.py --input tmp/deduped.jsonl
```

### 4.3 Stage untuk Review

Letak dalam `review_queue/pending.jsonl`.

Guna format:
```json
{
  "id": "01_foundation_reasoning_0001",
  "category": "01_foundation",
  "subcategory": "reasoning",
  "type": "qa",
  "messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}],
  "source": {"name": "...", "license": "CC-BY-4.0"},
  "language": "en",
  "difficulty": 3,
  "tags": ["reasoning"],
  "quality_score": 8,
  "verified": false
}
```

---

## 5. Acquisition Engine — Cara Guna

Acquisition Engine untuk ingest data dari external sources secara automatik.

```bash
# Dry-run — check apa akan di acquire
python scripts/acquisition_engine/engine.py --source arxiv --query "quantum computing" --dry-run

# Acquire (perlukan human approval)
python scripts/acquisition_engine/engine.py --source github --repo "user/repo" --acquire

# Check checkpoint status
cat metadata/engine_checkpoint.json

# Integrity check
python scripts/acquisition_engine/integrity.py --manifest metadata/acquisition_manifest_v0.1.json
```

### AQL — Atlas Query Language

```bash
# Query data
python scripts/atlas.py aql "SELECT * WHERE category='04_ai_machine_learning' LIMIT 5"

# Validate query
python scripts/atlas.py aql "SELECT * WHERE quality_score > 8"
```

---

## 6. Automation Pipeline — Step-by-Step

```bash
# 1. Run pipeline
python -m scripts.automation_runner run --pipeline-id release-v0.3

# 2. Check progress
python -m scripts.automation_runner status --pipeline-id release-v0.3

# 3. Jika ada agent fail
python -m scripts.automation_runner retry --pipeline-id release-v0.3

# 4. Jika siap — approve
python -m scripts.automation_runner approve --pipeline-id release-v0.3

# 5. Release
python -m scripts.automation_runner release --pipeline-id release-v0.3

# Pipeline states: INGESTED → QUALITY_CHECK → PROVENANCE_CHECK
# → CONTENT_REVISION → VALIDATION → WAITING_HUMAN_APPROVAL → RELEASED
```

---

## 7. Release Management

```bash
# Senarai releases
python scripts/atlas.py release list

# Create release candidate
python scripts/atlas.py release create-candidate --version v0.3

# Promote to release
python scripts/atlas.py release promote --version v0.3

# Check release quality gate
python scripts/atlas.py release check-quality --version v0.3

# Create knowledge pack
python scripts/atlas.py pack create --name foundation-pack --version v0.2
```

---

## 8. Evaluation

```bash
# Run evaluation
python scripts/evaluation_engine/runner.py \
    --dataset curated/v0.2/data/v0.2_full.jsonl \
    --output metadata/evaluation/reports/

# Check existing evaluation reports
cat metadata/evaluation/reports/index.json
```

---

## 9. Key Command Cheat Sheet

| Action | Command |
|---|---|
| **Self-test** | `python scripts/atlas.py self-test` |
| **Validate data** | `python scripts/validate_dataset.py --input <file>` |
| **Quality score** | `python scripts/quality_score.py --input <file>` |
| **Deduplicate** | `python scripts/dedup_dataset.py --input <file> --drop --output <out>` |
| **Convert format** | `python scripts/convert_format.py --format <name> --input <file> --output <out>` |
| **Run pipeline** | `python -m scripts.automation_runner run --pipeline-id <id>` |
| **Pipeline status** | `python -m scripts.automation_runner status --pipeline-id <id>` |
| **Approve release** | `python -m scripts.automation_runner approve --pipeline-id <id>` |
| **AQL query** | `python scripts/atlas.py aql "SELECT * WHERE ..."` |
| **Release list** | `python scripts/atlas.py release list` |
| **Create pack** | `python scripts/atlas.py pack create --name <name> --version <ver>` |
| **Calibrate** | `python scripts/atlas.py calibrate --reviews review/quality_reviews.jsonl` |
| **E2E pipeline** | `python scripts/e2e_pipeline.py --source <src> --output <out>` |

---

## 10. Troubleshooting

| Problem | Check |
|---|---|
| Pipeline fail | `python -m scripts.automation_runner status --pipeline-id <id>` — cek state machine |
| Schema validation error | `python scripts/validate_dataset.py --input <file>` — ikut `schemas/dataset_schema.json` |
| License reject | Pastikan license dalam senarai allowed — check `scripts/validate_dataset.py:is_denied_license` |
| Quality score rendah | Boleh adjust guna calibration — `python scripts/atlas.py calibrate` |
| Dedup salah | Guna `--report` dulu sebelum `--drop` |
| Release gate blocked | Lepas semua agent pass, kena human approve |
| AQL query error | `python scripts/atlas.py aql "DESCRIBE"` untuk tengok schema |

---

## 11. Critical Rules

1. **Jangan modify curated/ terus** — guna pipeline
2. **License mesti jelas** — kalau `unknown`, auto reject
3. **Human approval wajib** sebelum release
4. **Raw data immutable** — sekali masuk, jangan sentuh
5. **Deterministic** — output mesti sama untuk input yang sama
6. **Version everything** — release mesti ada manifest + checksum
7. **Fail closed** — kalau ragu, STOP. Jangan teka

---

> **Last updated:** 2026-07-29
> **Maintainer:** Atlas Engineering
