# Atlas Dataset Card — v1.0

> **The dataset is the long-term asset. Models are replaceable.**

## Overview

Atlas v1.0 is a **model-agnostic, long-term knowledge foundation** for
training and evaluating 8B-class LLMs (Qwen, Llama, DeepSeek, Mistral, Gemma,
and future models). Canonical format is JSONL; model-specific formats are
generated downstream and never stored as source of truth.

| Metric | Value |
|---|---|
| Version | v1.0 |
| Release ID | `4dcfd43e9da2d756` |
| Status | final (frozen) |
| Records | 9,515,938 |
| Categories | 9 (each ≥ 1,000,000) |
| Avg quality_score | 7.94 |
| Gates | quality, license, human-review, dedup — all passed |

## Category distribution

| Category | Records |
|---|---|
| 01_foundation | 1,000,613 |
| 02_software_engineering | 997,144 |
| 03_system_engineering | 1,039,979 |
| 04_ai_machine_learning | 1,066,501 |
| 05_hardware_engineering | 1,090,289 |
| 06_science_engineering | 1,249,899 |
| 07_business_knowledge | 1,066,944 |
| 08_creative_knowledge | 1,004,557 |
| 09_personal_assistant | 1,000,012 |

## License distribution

| License | Records |
|---|---|
| unknown | 7,972,390 |
| ODC-BY | 1,166,924 |
| MIT | 205,243 |
| CC-BY-SA-3.0 | 112,901 |
| Apache-2.0 | 43,844 |
| CC-BY-4.0 | 10,403 |
| arXiv non-exclusive license | 3,737 |
| CC-BY-SA-4.0 | 310 |
| Public Domain (US) | 67 |
| MIT (inferred from repo) | 49 |
| CC-BY-4.0 (generated; human-review) | 7 |
| arXiv.org perpetual non-exclusive license (preprint; no copyright transfer) | 5 |
| Mixed (per-subset; many ODC-BY/CC; some restricted) | 5 |
| Custom / research-only (verify) | 5 |
| BigCode Open RAIL-M (use-restricted) | 4 |
| BigCode Open RAIL-M | 4 |
| CC-BY-SA-4.0 (attribution + share-alike) | 4 |
| Public domain / MIT-style (man-pages); GFDL for some kernel docs | 4 |
| CC-BY-4.0 (must human-review) | 4 |
| Apache-2.0 (verify; repo 404 at check) | 3 |
| Apache-2.0 (gated; verify) | 3 |
| CC-BY-4.0 (docs repo) | 3 |
| Apache-2.0 (docs repo) | 3 |
| CC-BY-SA-4.0 (some GFDL) | 3 |
| CC-BY-SA-4.0 (Red Hat Customer Portal docs) | 3 |
| CC-BY-4.0 (gated; verify on access) | 2 |
| MIT (verify; PII caution) | 2 |
| CC-BY-SA-4.0 (verify) | 2 |
| CC-BY-4.0 (generated; must human-review) | 2 |
| MIT (gated; verify) | 2 |

> Note: records carrying `license = "unknown"` at the record level should be
> reviewed by consumers for their own redistribution obligations (esp.
> CC-BY-SA-3.0 share-alike records).

## Quality distribution

| Score | Records |
|---|---|
| 4 | 8,000 |
| 5 | 52,708 |
| 6 | 31,699 |
| 7 | 1,804,156 |
| 8 | 6,155,148 |
| 9 | 1,464,227 |

## Difficulty distribution

| Level | Records |
|---|---|
| 0 | 18 |
| 1 | 1,000,088 |
| 2 | 8,049,938 |
| 3 | 465,894 |

## Source lineage

See `metadata/provenance.json` for the full per-source breakdown. The top
sources: Wikipedia (6,206,334),
synthetic personal-assistant (1,000,000),
C4 AI/ML (786,534).

## Schema

Each record is a canonical Atlas knowledge object:

```json
{
  "id": "wiki_sys_0_0000000",
  "category": "03_system_engineering",
  "subcategory": "systems",
  "type": "instruction|conversation|qa|reasoning",
  "source": { "name": ..., "url": ..., "license": ..., "date": ... },
  "messages": [ { "role": "user", "content": ... }, { "role": "assistant", "content": ... } ],
  "language": "en",
  "difficulty": 1,
  "tags": [...],
  "quality_score": 8,
  "verified": true,
  "notes": ""
}
```

## Intended use

- SFT of instruction-following 8B-class models (Qwen, Llama, DeepSeek, Mistral, Gemma)
- Knowledge-grounded reasoning and system/software engineering assistance
- Balanced coverage across foundation, engineering, science, business,
  creative, and personal-assistant domains

## Provenance & integrity

- Release hash chain: `4dcfd43e9da2d756…` (sha256-chain-v1, previous v1.0-RC2)
- Per-file integrity: `metadata/checksums.sha256` (SHA-256 of every release file)
- Frozen at `2026-08-01`; contents are immutable
