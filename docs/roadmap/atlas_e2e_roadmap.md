# Atlas E2E Roadmap — Long-Term Architecture Plan

> **Author:** Architecture Planning (Hermes)
> **Status:** Planning document — no production code changed
> **Scope:** All Atlas development phases after AcquisitionAgent v1

---

## Table of Contents

1. [Current Project Status](#1-current-project-status)
2. [Current Architecture](#2-current-architecture)
3. [Remaining Work Before True End-to-End Automation](#3-remaining-work-before-true-end-to-end-automation)
4. [Proposed Future Versions](#4-proposed-future-versions)
5. [Future Automation Flow](#5-future-automation-flow)
6. [Design Principles](#6-design-principles)
7. [Long-Term Vision](#7-long-term-vision)

---

## 1. Current Project Status

The Atlas Automation Layer currently has **10 production components** implemented and tested, plus the **AcquisitionAgent v1** as the most recent addition. All components live under `scripts/automation/` and follow the `BaseAgent` abstract interface.

### 1.1 State Machine

**File:** `state_machine.py` (409 lines)

A finite state machine (FSM) governing the dataset pipeline lifecycle. Defines 9 pipeline states:

| State | Meaning |
|---|---|
| `INGESTED` | Raw data has entered the pipeline |
| `QUALITY_CHECK` | Automated quality scoring complete |
| `PROVENANCE_CHECK` | Source provenance resolved |
| `CONTENT_REVISION` | Content review and revision complete |
| `VALIDATION` | Final structural validation passed |
| `WAITING_HUMAN_APPROVAL` | Waiting for human sign-off |
| `READY_FOR_RELEASE` | Release gate cleared |
| `RELEASE_REJECTED` | Release was denied |
| `RELEASED` | Dataset officially released (terminal) |
| `FAILED` | Pipeline halted on error |

Enforces forward-only progression, mandatory human approval before `RELEASED`, and persists state to `metadata/pipeline_state/` for durability across restarts. Invalid transitions are rejected with clear error messages.

**Responsibility:** Ensure pipeline advances in strict order and never skips governance steps.

### 1.2 Pipeline Orchestrator

**File:** `pipeline_orchestrator.py` (612 lines)

Owns the state machine, approval gate, and all agents. Sequences the pipeline stages: quality → provenance → revision → validation → human approval → release. Provides two execution modes:

- `run_full_pipeline()` — complete run from INGESTED to RELEASED
- `run_to_approval()` — run up to WAITING_HUMAN_APPROVAL

Handles failures gracefully — stops the pipeline on critical errors from quality or validation agents; allows advisory-only failures from provenance and revision agents.

**Responsibility:** Drive the pipeline workflow, collect agent results, manage gate transitions.

### 1.3 Approval Gate

**File:** `approval_gate.py` (401 lines)

Controls human approval before any pipeline reaches RELEASED. Enforces:

- Approval is **mandatory** before release — the orchestrator blocks without it
- Only authorized roles can approve (REVIEWER, MAINTAINER, ARCHITECT)
- Approval decisions are persisted to `metadata/pipeline_approvals.json`
- Denied requests can be re-filed
- Full audit trail of who approved, when, and with what comments

**Responsibility:** Gate human sign-off, provide audit trail, prevent unsupervised releases.

### 1.4 Provenance Agent

**File:** `provenance_agent.py` (165 lines)

Adapter wrapping the existing `ProvenanceResolver` (817 lines) without modifying it. Classifies records by resolution status (resolved/unresolved). Reports unresolved records that still need human attention. Can fail on unresolved records when `fail_on_unresolved=True`.

**Responsibility:** Ensure every record has complete provenance metadata (source, license, attribution).

### 1.5 Quality Agent

**File:** `quality_agent.py` (328 lines)

Production implementation that delegates to `quality_score.py` for deterministic, explainable quality assessment. Evaluates each record on **7 dimensions**:

- Accuracy
- Completeness
- Technical Correctness
- Clarity
- Usefulness
- Originality
- Relevance

Each record receives a 1–10 quality score, a confidence level (1–5), issue flags, and aggregate statistics. Configurable thresholds for PASS/FAIL and fail-on-flag behavior.

**Responsibility:** Score every record, identify quality issues, gate the pipeline on quality standards.

### 1.6 Revision Agent

**File:** `revision_agent.py` (626 lines)

Generates actionable revision proposals from quality evaluation findings. Maps low dimension scores to structured proposals by category:

- **Completeness** — missing explanation, insufficient detail
- **Technical Depth** — missing mechanism explanation, examples, trade-offs
- **Clarity** — unclear wording, poor structure
- **Usefulness** — insufficient practical guidance

Never modifies dataset records. Writes proposals to `metadata/pipeline_revisions/` for audit and human review.

**Responsibility:** Provide structured, actionable improvement suggestions for low-quality records.

### 1.7 Validation Agent

**File:** `validation_agent.py` (360 lines)

Comprehensive validation by delegating to existing production validators:

- `validate_dataset.py` — structural errors, JSON Schema validation
- `validate_knowledge_object.py` — KO-specific validation
- `atlas_constants.py` — license gate compliance
- Duplicate ID and content detection (normalized SHA-1)
- Strict curated gate (quality_score ≥ 7, verified=True)

No dataset files are written — only read-only analysis.

**Responsibility:** Ensure every record passes structural, schema, license, and integrity checks before release.

### 1.8 Release Manager

**File:** `release_manager.py` (441 lines)

Final gate before dataset release. Verifies ALL required gates pass:

- Quality gate
- Provenance gate
- Revision gate
- Validation gate
- Human approval gate

Generates release candidate metadata with checksums. Creates release artifacts in `metadata/releases/`. Supports approval and rejection workflows. Preserves full audit trail of every release attempt.

**Responsibility:** Verify all gates, produce versioned release artifacts, enforce cannot-release-without-approval.

### 1.9 Failure Recovery

**File:** `failure_recovery.py` (541 lines)

Supports targeted retry and resume for failed pipelines. Design constraints:

- Does NOT modify existing agents
- Retry history persisted to `metadata/pipeline_retries/`
- **Only the failed agent** is re-run on retry (scoped per type)
- On success, pipeline continues from the retried agent
- On failure, stays FAILED (no infinite loop)

Retry rules: quality → retry quality only; provenance → retry provenance only; etc.

**Responsibility:** Allow pipelines to recover from transient failures without restarting from INGESTED.

### 1.10 Automation Runner

**File:** `scripts/automation_runner.py` (CLI entry)

Exposes the automation pipeline as CLI commands: `python -m scripts.automation_runner run`, approve, status, etc. Exposes the full pipeline to operators.

**Responsibility:** Provide CLI interface for operating the pipeline.

### 1.11 AcquisitionAgent v1

**File:** `acquisition_agent.py` (361 lines)

Deterministic packet acquirer with two modes:

- **dry-run** — show planned acquisitions and skipped packets with reasons
- **acquire** — create `metadata/acquisition_logs/` and record acquisition checksums

Safety guarantees:
- Only APPROVE decisions are processed; DEFER/REJECT are skipped
- Unknown/absent human decision blocks acquisition (fail closed)
- Rejected-source registry entries are never acquired
- Dataset roots (`curated/`, `review_queue/`, `training_views/`, `raw/`) are never mutated

Validates against three inputs: human decisions file, acquisition manifest, and source registry.

**Responsibility:** Gate the transition from human review → actual data acquisition with deterministic safety guarantees.

---

## 2. Current Architecture

```
                         ┌─────────────────────┐
                         │    Source Registry    │
                         │  metadata/source_    │
                         │  registry.json       │
                         └──────────┬──────────┘
                                    │ source selection
                                    ▼
                         ┌─────────────────────┐
                         │  Acquisition Manifest │
                         │  acquisition_manifest │
                         │  _v0.1.json          │
                         └──────────┬──────────┘
                                    │ packet definitions
                                    ▼
                         ┌─────────────────────┐
                         │    Human Review      │
                         │  acquisition_human_  │
                         │  decisions.json      │
                         └──────────┬──────────┘
                                    │ APPROVE / DEFER / REJECT
                                    ▼
                         ┌─────────────────────┐
                         │   AcquisitionAgent    │
                         │  v1 (dry-run/acquire)│
                         │  acquisition_logs/   │
                         └──────────┬──────────┘
                                    │ acquired metadata
                                    ▼
                         ┌─────────────────────┐
                         │    Quality Agent     │
                         │  7-dim scoring      │
                         └──────────┬──────────┘
                                    │ quality scores
                                    ▼
                         ┌─────────────────────┐
                         │   Provenance Agent   │
                         │  resolver adapter   │
                         └──────────┬──────────┘
                                    │ provenance report
                                    ▼
                         ┌─────────────────────┐
                         │   Revision Agent     │
                         │  proposals generated │
                         └──────────┬──────────┘
                                    │ revision proposals
                                    ▼
                         ┌─────────────────────┐
                         │  Validation Agent    │
                         │  structural, license │
                         └──────────┬──────────┘
                                    │ validation report
                                    ▼
                         ┌─────────────────────┐
                         │   Approval Gate      │
                         │  HUMAN MUST APPROVE  │
                         └──────────┬──────────┘
                                    │ approved
                                    ▼
                         ┌─────────────────────┐
                         │   Release Manager    │
                         │  metadata/releases/  │
                         └─────────────────────┘
```

### Stage Descriptions

| Stage | Input | Output | Gate |
|---|---|---|---|
| **Registry** | Source candidates | Categorized, vetted sources | License policy |
| **Manifest** | Vetted sources | Acquisition packets with batch IDs | Schema validation |
| **Human Review** | Packets + metadata | APPROVE/DEFER/REJECT decisions per packet | Human judgment |
| **AcquisitionAgent** | Approved packets | Acquisition checksums + logs | Registry status, fail-closed |
| **Quality** | Curated JSONL records | 7-dimension scores, issue flags, aggregate stats | Configurable mean/min score threshold |
| **Provenance** | Records + source metadata | Resolution status per record | (Advisory — logs unresolved) |
| **Revision** | Quality scores + records | Structured revision proposals | (Advisory — creates proposals) |
| **Validation** | Records + schemas | Structural/schema/license error reports | Zero-error required |
| **Approval** | All prior results | APPROVED/DENIED decision | Human must approve |
| **Release** | Approved pipeline state | Release manifest + report + checksum | All gates must pass |

### What's Missing

The current pipeline handles **governance and quality after data is already curated**. It does **not** yet handle:

- **Downloading** data from external sources (HuggingFace, GitHub, arXiv, etc.)
- **Caching** downloaded data for resume and efficiency
- **Extracting** records from raw source formats (JSON, XML, Markdown, HTML, PDF)
- **Normalizing** multi-format records into the Atlas Canonical Schema
- **Cleaning** records (dedup, PII removal, malformed conversation removal)
- **Transforming** raw content into instruction/QA/conversation/reasoning/knowledge objects
- **Building training views** for different model families
- **Creating release bundles** automatically

These are the subjects of the roadmap ahead.

---

## 3. Remaining Work Before True End-to-End Automation

### 3.1 Dataset Downloader

The current AcquisitionAgent records what *should* be acquired but does **not** perform the actual download. A download subsystem is needed to pull data from external sources.

**Requirements:**

- **HuggingFace** — download datasets via `datasets` library or direct file downloads
- **GitHub** — clone or download repositories (documentation, code, issues, discussions)
- **Documentation** — scrape/fetch docs from websites (MDN, Python docs, etc.)
- **StackExchange** — download StackExchange data dumps (Q&A pairs)
- **arXiv** — download papers and metadata via arXiv API or bulk data

**Design constraints:**

- Each source type needs a dedicated **SourceAdapter** with type-specific logic
- Adapters share a common interface: `download(source_ref, target_dir) -> DownloadResult`
- Rate limiting, polite crawling, and API key management per adapter
- All downloads go through the Cache Manager (never re-download)

### 3.2 Cache Manager

A caching layer that prevents redundant downloads and supports resumable transfers.

**Requirements:**

- **Download cache** — store raw downloads by content hash in a content-addressable store
- **Resume support** — interrupted downloads resume from last byte (HTTP Range headers, file append)
- **Checksum verification** — verify every downloaded file against source-provided or computed checksums
- **Retry strategy** — exponential backoff with configurable max retries and timeout windows
- **Storage budgeting** — configurable max cache size with LRU eviction or manual purge
- **Cache index** — SQLite or JSON index mapping source references → cached file paths + metadata

**Design constraints:**

- Cache directory is under `raw/.cache/` — separate from immutable `raw/` storage
- Never serve stale content without re-verification
- Cache corruption detection via manifest checksums

### 3.3 Dataset Extractors

Once raw data is cached, extractors parse source formats into structured records.

**Required extractors:**

| Format | Source Examples | Extraction Approach |
|---|---|---|
| **HF datasets** | HuggingFace hub | `datasets.load_dataset()` → JSONL conversion |
| **JSON** | API responses, structured docs | Standard `json.load()` with schema mapping |
| **JSONL** | Pre-converted datasets | Line-by-line parse, validation |
| **XML** | Sphinx docs, WordPress exports | `xml.etree.ElementTree` parsing |
| **Markdown** | GitHub docs, blog posts | Markdown AST → section extraction |
| **HTML** | Documentation websites, forums | BeautifulSoup/lxml → content extraction |
| **PDF (future)** | arXiv papers, books | OCR / PyMuPDF → text + layout |

**Design constraints:**

- Extractor interface: `extract(raw_path, format_config) -> list[RawRecord]`
- Validation after extraction: every record must have at minimum `id`, `content`, `source`
- Language detection and encoding normalization applied during extraction
- Unparseable files are logged and skipped (never crash the pipeline)

### 3.4 Dataset Normalizer

Converts every extracted record into the **Atlas Canonical Schema** — the single internal representation that all downstream processing operates on.

**Responsibilities:**

- Map source-specific field names to canonical fields
- Convert date formats to ISO 8601
- Normalize license strings to canonical forms (MIT → `mit`, CC-BY-4.0 → `CC-BY-4.0`)
- Standardise role names in conversation records (`human` → `user`, `bot` → `assistant`)
- Ensure every record has `id`, `source`, `license`, `content`, `created_at`, `lineage` fields
- Fail on unmappable required fields (configurable strictness)

**Canonical Schema (v0.2):**

```python
{
    "id": str,                    # globally unique
    "source": str,                # source identifier
    "license": str,               # canonical license string
    "content": str | dict,        # raw content or structured object
    "created_at": str,            # ISO 8601
    "lineage": list[str],         # source + processing history
    "metadata": dict,             # source-specific extras, preserved
}
```

### 3.5 Cleaning Pipeline

Production-quality cleaning that operates on normalized records.

**Required cleaners:**

| Cleaner | What It Does | Criticality |
|---|---|---|
| **Duplicate Remover** | Content-hash dedup + near-duplicate detection (MinHash/LSH) | HIGH |
| **PII Filter** | Regex-based PII detection (emails, API keys, IPs, SSNs) | HIGH |
| **Malformed Conversation Remover** | Unclosed turns, mismatched roles, empty messages | HIGH |
| **License Metadata Injector** | Add canonical license + attribution + obligations to every record | MEDIUM |
| **Language Validator** | Detect language, filter to target set, flag low-confidence | MEDIUM |
| **Length Filter** | Min/max content length enforcement | LOW |

**Design constraints:**

- Each cleaner is an independent, composable step
- Cleaners operate on a streaming pipeline (memory-efficient)
- Every cleaning operation is logged for audit
- Reversible: original content is preserved in lineage metadata
- Cleaning is deterministic — same input always produces same output

### 3.6 Transformation Layer

Converts cleaned, normalized content into the **five Atlas training record types**.

**Target record types:**

```
Documentation  ──→  instruction  (how-to guides, tutorials)
QA             ──→  qa_pair      (question → answer)
Conversation   ──→  conversation (multi-turn dialogue)
Reasoning      ──→  reasoning    (step-by-step logic, chain-of-thought)
Knowledge      ──→  knowledge    (factual knowledge object)
```

**Transformation rules:**

- **Doc → Instruction:** Extract sections with clear "how to" intent. Generate instruction-response pairs from headings + body.
- **QA → QA Pair:** Preserve question-answer structure. Add category tags based on taxonomy.
- **Conversation → Conversation:** Preserve turn structure. Add role annotations where missing.
- **Reasoning → Reasoning:** Extract step-by-step explanations, proofs, analyses. Add structured rationale field.
- **Knowledge → Knowledge Object:** Format as structured knowledge entries with category, subcategory, canonical answer, source attribution.

**Design constraints:**

- Each transformation is a standalone module with a `transform(record) -> list[TrainRecord]` interface
- One input record may produce multiple training records (e.g., a doc page → multiple instruction pairs)
- Transformations are auditable — provenance chain preserved
- Records that cannot be confidently transformed are passed through as-is with a `transformation: raw` tag

### 3.7 Training View Builder

Generates model-family-specific training views from the canonical dataset.

**Responsibilities:**

- **Review Queue Views:** `review_queue/` per-batch view of unverified records needing human review
- **Curated Views:** `curated/vX.Y/` versioned, verified, quality-gated dataset snapshots
- **Training Views:** `training_views/{model}/` formatted per model chat template
  - Qwen (ChatML format)
  - Llama (ChatML / Llama format)
  - DeepSeek (DeepSeek format)
- **Evaluation Sets:** `evaluation/vX.Y/` held-out test sets, benchmark-compatible subsets

**Current state:** Training view infrastructure exists in `scripts/training_view_engine/` (generator, filter, manifest, validator). Needs **production integration** with the automation pipeline.

**Design constraints:**

- Training views are **generated, not stored** — they are deterministic outputs from curated data
- View regeneration is cheap and reproducible
- Each model family gets its own subdirectory under `training_views/`
- Evaluation sets are frozen at release time (never change after freeze)

### 3.8 Release Builder

Automates the final step: packaging a dataset for distribution.

**Responsibilities:**

- Create release bundle from curated snapshot + training views + evaluation sets
- Generate release manifest with checksums over every file
- Produce dataset card (README.md, stats, license, attribution)
- Create versioned tags (v0.1, v0.2, v1.0)
- Publish to HuggingFace Hub (optional, configurable)
- Generate human-readable release notes from changelog

**Current state:** Release Manager creates metadata artifacts. The Release Builder would **materialize the actual release files**.

**Design constraints:**

- Release builds are frozen — once published, never mutated
- Every release has a unique checksum
- Release manifests include file-level hashes for downstream verification

---

## 4. Proposed Future Versions

### Milestone Overview

| Version | Focus | Key Deliverables | Risks | Dependencies |
|---|---|---|---|---|
| v1.6 ✅ | **Downloader + Cache** | Source adapters (HF, GitHub, docs, SE, arXiv); Cache Manager with resume + checksums; retry logic | Source API rate limits; large downloads (arXiv bulk data); GitHub auth complexity | AcquisitionAgent v1 (complete) |
| v1.7 ✅ | **Extract + Normalize + Clean** | Extractors for all formats; Normalizer → Canonical Schema; Cleaning pipeline (dedup, PII, malformed removal, license injection, language validation) | PII false positives; format edge cases (malformed XML/HTML); near-duplicate algorithm tuning | v1.6 (cache populated) |
| v1.8 | **Transform + Training Views + Release** | Transformation layer (5 record types); Training View Builder production integration; Release Builder (bundles, manifests, Hub publish) | Transformation quality for poorly-structured sources; view generation performance at scale | v1.7 (clean records available) |
| v1.9 | **Performance + Scale** | Parallel processing (multi-worker extraction/normalization/cleaning); streaming pipeline; incremental updates (delta processing); memory optimization for large datasets | Thread safety in cleaners; incremental detection complexity; correctness verification | v1.8 (baseline pipeline) |
| v2.0 | **Full Automation** | End-to-end pipeline: source → download → cache → extract → normalize → clean → transform → quality → provenance → revision → validation → approval → release. Single command: `atlas pipeline e2e` | Integration complexity; error propagation across all stages; human approval UX | v1.9 (performance baseline) |

### v1.6 — Downloader + Cache Manager

**Goal:** Enable Atlas to actually download data from external sources, not just record the intent.

**Status:** ✅ Implemented — see `docs/downloader_v1_6.md`

**Deliverables:**

- [x] **Source Adapter interface** — abstract `SourceAdapter` with `download()` method
- [x] **HuggingFaceAdapter** — Hub HTTP API + `/resolve/main/` file fetch (stdlib; no `datasets` dep)
- [x] **GitHubAdapter** — public repo tarballs via `codeload.github.com`
- [x] **DocumentationAdapter** — fetch and cache web documentation pages
- [x] **StackExchangeAdapter** — dump URL / Archive.org listing cache
- [x] **arXivAdapter** — PDF + Atom abstract via export API
- [x] **Cache Manager** — content-addressable cache with resume support (`raw/.cache/`)
- [x] **Checksum verification** — SHA-256 verification of all downloaded files
- [x] **Retry strategy** — exponential backoff with configurable max retries
- [x] **Cache index** — SQLite-based index for O(1) cache lookups
- [x] **Integration test** — local HTTP fixture + DownloadAgent end-to-end (`tests/test_downloader_v1_6.py`)

**Risks:**

- Source API rate limits may require careful throttling
- Large bulk downloads (arXiv: ~180GB) need streaming and disk management
- GitHub API authentication setup required

**Dependencies:**

- AcquisitionAgent v1 (provides the manifest of what to acquire)

### v1.7 — Extractors + Normalizer + Cleaning Pipeline

**Goal:** Convert raw downloaded data into clean, normalized Atlas Canonical Schema records.

**Status:** ✅ Implemented (gsm8k-first) — see `docs/etl_v1_7.md`

**Deliverables:**

- [x] **Extractor interface** — `extract(raw_path) -> list[RawRecord]`
- [x] **HF Dataset Extractor** — Parquet via optional pyarrow (covers HF hub shards)
- [x] **JSON/JSONL Extractor** — standard JSON parse with schema mapping
- [ ] **XML Extractor** — deferred (StackExchange dumps); HTML/MD cover docs path
- [x] **Markdown Extractor** — heading-aware section records
- [x] **HTML Extractor** — stdlib HTMLParser text extraction
- [x] **Dataset Normalizer** — Canonical Schema converter with field mapping + Atlas promotion
- [x] **Duplicate Remover** — content-hash dedup (SHA-256)
- [ ] **Near-Duplicate Detector** — deferred to scale pass (exact dedup first)
- [x] **PII Filter** — regex-based PII detection and redaction/masking
- [x] **Malformed Conversation Remover** — structural validation
- [x] **License Metadata Injector** — per-record license normalization
- [ ] **Language Validator** — deferred (length + malformed gates cover smoke path)

**Risks:**

- PII filter may produce false positives (IP addresses in code examples)
- Near-duplicate detection at scale is computationally expensive
- HTML/Markdown extraction quality varies wildly by source

**Dependencies:**

- v1.6 (cache must be populated with raw downloads)

### v1.8 — Transformation Layer + Training Views + Release Builder

**Goal:** Transform cleaned records into training-ready formats and produce release bundles.

**Deliverables:**

- [ ] **Documentation → Instruction transformer**
- [ ] **QA → QA Pair transformer**
- [ ] **Conversation → Conversation transformer**
- [ ] **Reasoning → Reasoning transformer**
- [ ] **Knowledge → Knowledge Object transformer**
- [ ] **Training View Builder** (production integration with existing `training_view_engine/`)
  - Review queue views
  - Curated snapshot views
  - Model-family-specific training views (Qwen, Llama, DeepSeek)
  - Evaluation set generation
- [ ] **Release Builder**
  - Release bundle packaging
  - File-level checksum manifest
  - Dataset card generation
  - HuggingFace Hub publish (optional)
  - Release notes generator

**Risks:**

- Transformation quality is hard to automate for ambiguous source content
- Some sources may not map cleanly into the 5-type taxonomy
- Training view generation must handle model template differences (tokenizer, special tokens)

**Dependencies:**

- v1.7 (cleaned normalized records available)

### v1.9 — Parallel Processing + Incremental Updates

**Goal:** Make the pipeline fast enough for real-world dataset sizes (5k–10k+ records).

**Deliverables:**

- [ ] **Parallel processing framework** — multi-worker extract/normalize/clean
- [ ] **Streaming pipeline mode** — process data without loading everything into memory
- [ ] **Incremental update support** — only re-process changed sources
- [ ] **Cache invalidation** — source-aware cache expiry
- [ ] **Progress tracking** — per-stage progress bars and ETA estimates
- [ ] **Memory profiling** — reduce peak memory for large datasets
- [ ] **Performance benchmarks** — wall-clock targets per stage

**Risks:**

- Thread safety in cleaners and extractors (need to audit for shared state)
- Incremental update correctness (ensure no stale records slip through)
- Parallel I/O contention on cache and disk

**Dependencies:**

- v1.8 (baseline pipeline exists to optimize)

### v2.0 — Fully Automated End-to-End Pipeline

**Goal:** One command runs the entire pipeline from source selection to published dataset.

**Deliverables:**

- [ ] **End-to-end pipeline mode** — `atlas pipeline e2e` single command
- [ ] **Orchestrator v2** — extended to include download, cache, extract, normalize, clean, transform, training view, and release stages
- [ ] **Human approval at multiple gates** (optional) — approve at acquisition, approve at release
- [ ] **Failure propagation** — errors bubble up from any stage with clear recovery steps
- [ ] **Pipeline CLI** — full command suite (run, status, retry, approve, rollback)
- [ ] **Comprehensive integration tests** — end-to-end on synthetic data
- [ ] **Documentation** — operator runbook, architecture guide, troubleshooting guide

**Risks:**

- Integration complexity across 7+ new subsystems
- Error handling at every stage must be robust
- Human approval UX needs to be intuitive (web UI or team notification)

**Dependencies:**

- v1.9 (performance baseline and parallel processing)

---

## 5. Future Automation Flow

```
                         ┌─────────────────────┐
                         │    Source Registry    │
                         │  metadata/source_    │
                         │  registry.json       │
                         └──────────┬──────────┘
                                    │ source selection
                                    ▼
                         ┌─────────────────────┐
                         │    Human Review       │
                         │  acquisition_human_  │
                         │  decisions.json      │
                         └──────────┬──────────┘
                                    │ APPROVE / DEFER / REJECT
                                    ▼
                         ┌─────────────────────┐
                         │      Acquire         │◄── AcquisitionAgent v1
                         │  (metadata/logs)    │     (existing)
                         └──────────┬──────────┘
                                    │ approved source list
                                    ▼
                         ┌─────────────────────┐
                         │       Cache          │◄── Cache Manager (NEW v1.6)
                         │  raw/.cache/        │
                         │  resume + checksums │
                         └──────────┬──────────┘
                                    │ cached raw files
                                    ▼
                         ┌─────────────────────┐
                         │      Extract         │◄── Dataset Extractors (NEW v1.7)
                         │  HF / JSON / XML    │
                         │  MD / HTML / PDF    │
                         └──────────┬──────────┘
                                    │ raw records
                                    ▼
                         ┌─────────────────────┐
                         │     Normalize        │◄── Dataset Normalizer (NEW v1.7)
                         │  Canonical Schema  │
                         └──────────┬──────────┘
                                    │ normalized records
                                    ▼
                         ┌─────────────────────┐
                         │       Clean          │◄── Cleaning Pipeline (NEW v1.7)
                         │  dedup / PII / mal- │
                         │  formed / license    │
                         └──────────┬──────────┘
                                    │ clean records
                                    ▼
                         ┌─────────────────────┐
                         │    Transform         │◄── Transformation Layer (NEW v1.8)
                         │  doc→instr / QA→    │
                         │  pair / conv→conv   │
                         └──────────┬──────────┘
                                    │ training records
                                    ▼
                         ┌─────────────────────┐
                         │     Quality          │◄── Quality Agent (existing)
                         │  7-dim scoring      │
                         └──────────┬──────────┘
                                    │ scored records
                                    ▼
                         ┌─────────────────────┐
                         │   Revision (advisory)│◄── Revision Agent (existing)
                         │  proposals          │
                         └──────────┬──────────┘
                                    │ revision proposals
                                    ▼
                         ┌─────────────────────┐
                         │    Validation        │◄── Validation Agent (existing)
                         │  schema / license   │
                         └──────────┬──────────┘
                                    │ validated records
                                    ▼
                         ┌─────────────────────┐
                         │   Approval Gate      │◄── Approval Gate (existing)
                         │  HUMAN MUST APPROVE  │
                         └──────────┬──────────┘
                                    │ approved
                                    ▼
                         ┌─────────────────────┐
                         │   Training Views     │◄── Training View Builder (NEW v1.8)
                         │  Qwen/Llama/DeepSeek│
                         │  eval sets          │
                         └──────────┬──────────┘
                                    │ formatted views
                                    ▼
                         ┌─────────────────────┐
                         │      Release         │◄── Release Manager + Builder (NEW v1.8)
                         │  metadata/releases/ │
                         │  HF Hub publish     │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  Training Dataset    │
                         │  versioned, frozen,  │
                         │  ready for training  │
                         └─────────────────────┘
```

### Transition Explanations

| Transition | What Happens | Component |
|---|---|---|
| **Registry → Human Review** | Sources are selected from the registry. A human reviews and makes approval decisions per packet. | Source Registry + Manual Review |
| **Human Review → Acquire** | AcquisitionAgent reads human decisions. Only APPROVED packets proceed. Each packet gets a deterministic checksum. | AcquisitionAgent v1 |
| **Acquire → Cache** | Downloader iterates the acquired packet list. Each source is downloaded through its SourceAdapter. Files go to the content-addressable cache. | Source Adapters + Cache Manager |
| **Cache → Extract** | Extractors read cached raw files and parse them into structured RawRecords. One raw file may produce many records. | Dataset Extractors |
| **Extract → Normalize** | Normalizer maps source-specific field names to the Atlas Canonical Schema. Converts dates, licenses, and roles to standard forms. | Dataset Normalizer |
| **Normalize → Clean** | Cleaners run in sequence: duplicate removal, PII filtering, malformed conversation removal, license injection, language validation. Each cleaner is a pass-through filter. | Cleaning Pipeline |
| **Clean → Transform** | Transformers convert cleaned records into one of five training record types (instruction, QA, conversation, reasoning, knowledge). | Transformation Layer |
| **Transform → Quality** | Quality Agent scores every record on 7 dimensions. Records below threshold are flagged for revision. | Quality Agent |
| **Quality → Revision** | Revision Agent generates structured proposals for low-scoring records. This is advisory — pipeline continues. | Revision Agent |
| **Revision → Validation** | Validation Agent checks every record: structural validity, schema compliance, license gate, duplicate detection. | Validation Agent |
| **Validation → Approval** | Pipeline blocks here. Human must review the validation report and approve or deny the release. | Approval Gate |
| **Approval → Training Views** | Training View Builder generates model-family-specific formatted datasets from the approved curated snapshot. | Training View Builder |
| **Training Views → Release** | Release Builder packages everything: curated data, training views, evaluation sets, manifest, dataset card. Publishes versioned release. | Release Manager + Release Builder |
| **Release → Training Dataset** | The packaged release is now a frozen, versioned, immutable artifact ready for training. | (External) |

---

## 6. Design Principles

Every principle below has been followed by the existing pipeline and **must continue to be followed** in all future development phases.

### 6.1 Immutable Datasets

**Rule:** Once a dataset is released, it is never modified. Corrections create a new version.

**Why:** Ensures reproducibility of training experiments. A model trained on "Atlas v0.1" always uses the same data. Without immutability, training results are unreproducible.

**Enforcement:** Pipeline agents never write to `curated/`, `raw/`, `review_queue/`, or `training_views/`. Only the Release Builder creates new artifacts, and it always creates new directories (not overwrites).

### 6.2 Fail-Closed Safety

**Rule:** When state is uncertain or required inputs are missing, the pipeline refuses to proceed rather than making assumptions.

**Why:** A dataset with corrupted or missing governance metadata is worse than no dataset. The AcquisitionAgent refuses to acquire packets with missing human decisions; the pipeline refuses to release without human approval.

**Enforcement:** Every agent checks its preconditions before executing. Missing inputs → BLOCKED status, not a default assumption.

### 6.3 Human Approval Before Release

**Rule:** No dataset reaches the RELEASED state without explicit human sign-off.

**Why:** Automated quality checks can catch structural issues but cannot substitute for human judgment about dataset fitness, content appropriateness, or strategic alignment.

**Enforcement:** The state machine requires the WAITING_HUMAN_APPROVAL → RELEASED transition to be triggered by a human (via the Approval Gate). The orchestrator checks `is_releasable()` before permitting this transition.

### 6.4 Deterministic Processing

**Rule:** Given the same input and same configuration, every pipeline stage produces the same output.

**Why:** Debugging, auditing, and reproducibility all depend on deterministic behavior. A non-deterministic pipeline produces different results on each run, making it impossible to verify fixes or trust the output.

**Enforcement:** All agents sort their inputs before processing; checksums are computed on sorted, serialized JSON; random number generators are seeded with fixed values when randomness is needed (e.g., sample splitting).

### 6.5 Reproducible Builds

**Rule:** Every release can be rebuilt from source inputs using only the pipeline code and configuration.

**Why:** Future-proofing. If a model training run needs to be replicated two years later, the pipeline must still be able to produce the same dataset from the same raw data.

**Enforcement:** Every pipeline stage records its version and configuration in metadata. Releases include the pipeline version and all parameter values used. The Release Manager includes a `generated_by` field in every artifact.

### 6.6 Provenance-First

**Rule:** Every record in the dataset carries its complete provenance chain: where it came from, what license it has, every processing step applied.

**Why:** Governance, licensing compliance, and auditability all depend on knowing a record's origin. Without provenance, a dataset cannot be legally used for training.

**Enforcement:** The Canonical Schema requires a `lineage` field (list of processing steps). The Provenance Agent validates that every record has complete provenance metadata before it can advance through the pipeline.

### 6.7 Idempotent Operations

**Rule:** Running the same pipeline stage multiple times produces the same result as running it once.

**Why:** Enables safe retry after failure, incremental updates, and pipeline debugging. If a stage is not idempotent, recovering from a failure midway through requires starting over from scratch.

**Enforcement:** Agents check whether their output already exists before creating it. The Cache Manager uses content-addressing: writing the same content to the same cache key is a no-op. The AcquisitionAgent checks existing checksums before creating acquisition logs.

### 6.8 Modular Agents

**Rule:** Every pipeline stage is a standalone agent with a well-defined interface (`BaseAgent.execute()`) and no shared mutable state.

**Why:** Modularity enables independent development, testing, and replacement of any stage. A better quality scoring algorithm can be swapped in without touching the rest of the pipeline. A stage can fail without crashing the others.

**Enforcement:** All agents inherit from `BaseAgent`. Each agent has its own configuration namespace. Agents communicate only through `AgentResult` data dicts — never through shared variables or filesystem side effects.

### 6.9 Stdlib-First Where Practical

**Rule:** Prefer Python standard library over external dependencies unless there is a compelling performance or correctness reason to do otherwise.

**Why:** Minimizes dependency management burden, CI setup complexity, and supply-chain risk. Standard library code is well-tested, always available, and never requires version negotiation.

**Enforcement:** Existing agents use `json`, `hashlib`, `pathlib`, `collections`, `dataclasses`, `abc`, and `re` from stdlib. External dependencies (like `jsonschema`, `datasets`, `beautifulsoup4`) are only used in specialized stages where stdlib alternatives don't exist, and are always wrapped behind an importable interface that gracefully degrades when the dependency is absent.

### 6.10 Separation of Governance and Transformation

**Rule:** Governance stages (quality, provenance, validation, approval) are separate from transformation stages (extract, normalize, clean, transform, build views).

**Why:** Governance checks must be independent of data formats so they apply uniformly. Transformation stages can be swapped or replaced without affecting governance. This separation prevents a transformation bug from silently corrupting governance metadata.

**Enforcement:** Governance agents are in `scripts/automation/`. Transformation stages will be in their own modules (e.g., `scripts/downloader/`, `scripts/extractor/`, `scripts/cleaner/`). They communicate only through well-defined data contracts (JSONL with Canonical Schema).

---

## 7. Long-Term Vision

### What Atlas Should Become After v2.0

#### 7.1 Reproducible Dataset Factory

Atlas after v2.0 is a **fully automated dataset factory** that transforms raw source data into production-grade training datasets with a single command. The factory is:

- **Deterministic** — every build produces identical output for identical input
- **Versioned** — every release is a named, checksummed snapshot
- **Auditable** — every record carries its complete provenance chain
- **Idempotent** — re-running the pipeline is safe and cheap

#### 7.2 Production-Grade Governance

The governance layer (quality, provenance, revision, validation, approval) becomes a **self-documenting compliance system**:

- Automated policy enforcement via the state machine
- Human approval integrated at strategic gates (acquisition, release)
- Full audit trail from source selection to published dataset
- Compliance reports generated automatically per release

#### 7.3 Modular Acquisition

The acquisition subsystem becomes:

- **Plugin-based** — new source types are added by writing a SourceAdapter
- **Configurable** — each adapter has its own rate limiting, auth, and retry config
- **Resumable** — interrupted downloads resume from the last byte
- **Verifiable** — checksums are validated at every step (download → cache → extract)

#### 7.4 Multi-Source Ingestion

Atlas ingests from any number of source types:

- **Pre-built datasets** (HuggingFace, Kaggle)
- **Code repositories** (GitHub, GitLab)
- **Documentation** (web docs, wikis, blogs)
- **Q&A platforms** (StackExchange, Reddit)
- **Academic papers** (arXiv, papers with code)
- **Proprietary/internal data** (private repos, internal wikis, customer conversations)

Each source type uses its own adapter but produces the same Canonical Schema.

#### 7.5 Deterministic Releases

Every release is:

- **Rebuildable** — the same source + same pipeline version = same dataset
- **Verifiable** — file-level checksums in the manifest
- **Self-describing** — dataset card with stats, license, and provenance
- **Frozen** — once published, never mutated

This means a paper that trains on "Atlas v2.3" can be reproduced at any point in the future.

#### 7.6 Enterprise-Scale Dataset Pipeline

The pipeline scales to:

- **Thousands of sources** — registry supports source categorization, priority levels, and lifecycle states
- **Millions of records** — streaming processing, parallel workers, efficient caching
- **Multiple releases** — simultaneous pipeline runs for different versions or branches
- **Incremental updates** — only re-process sources that changed since the last release

#### 7.7 Future AI-Assisted Dataset Curation

Post-v2.0, Atlas will integrate AI assistance:

- **AI-assisted review** — suggest quality scores and revision proposals (partially done via Quality Agent + Revision Agent)
- **AI-assisted dedup** — use embeddings for near-duplicate detection at scale
- **AI-assisted transformation** — suggest instruction/QA/reasoning templates from raw content
- **AI-assisted coverage analysis** — identify gaps in the dataset taxonomy automatically
- **AI-assisted license analysis** — suggest license classification from README/CONTRIBUTING files

These are **assistance tools**, not autonomous pipelines — human oversight remains mandatory for all governance decisions.

---

## Document Summary

| Metric | Value |
|---|---|
| Sections | 7 |
| Sub-sections | ~35 |
| Estimated page length (printed) | 20–25 pages |
| Existing files modified | **0** |
| New files created | 1 (`docs/roadmap/atlas_e2e_roadmap.md`) |
| Production code changed | **None** |

---

*This document is a planning artifact. No production code was created, modified, or deleted during its preparation.*
