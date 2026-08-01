# Atlas Dataset Card — v1.0-RC1

> **The dataset is the long-term asset. Models are replaceable.**

## Overview

Atlas v1.0-RC1 is a **model-agnostic, long-term knowledge foundation** for
training and evaluating 8B-class LLMs (Qwen, Llama, DeepSeek, Mistral, Gemma,
and future models). Canonical format is JSONL; model-specific formats are
generated downstream and never stored as source of truth.

| Metric | Value |
|---|---|
| Version | v1.0-RC1 |
| Release ID | `e66408aa594d9438` |
| Status | release_candidate (frozen) |
| Records | 9,893,844 |
| Categories | 9 (each ≥ 1,000,000) |
| Avg quality_score | 7.94 |
| Gates | quality, license, human-review, dedup — all passed |

## Category distribution

| Category | Records |
|---|---|
| 01_foundation | 1,000,613 |
| 02_software_engineering | 1,375,050 |
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
| CC-BY-SA-3.0 | 6,471,355 |
| MIT | 1,007,774 |
| ODC-BY | 869,441 |
| Apache-2.0 | 1,726 |
| unknown | 1,543,548 |

> Note: 1.54M records carry `license = "unknown"` at the record level. The
> release's license gate passed; consumers should review the `unknown`
> segment for their own redistribution obligations (esp. CC-BY-SA-3.0
> share-alike records).

## Quality distribution

| Score | Records |
|---|---|
| 4 | 8,000 |
| 5 | 52,708 |
| 6 | 31,699 |
| 7 | 1,826,363 |
| 8 | 6,489,765 |
| 9 | 1,485,309 |

## Difficulty distribution

| Level | Records |
|---|---|
| 1 (Basic) | 1,000,000 |
| 2 (Intermediate) | 7,345,301 |
| 3 (Advanced) | 4,995 |
| unassigned (?) | 1,543,548 |

## Source lineage

Wikipedia (6.47M), synthetic personal-assistant (1.00M), C4 AI/ML (0.79M),
OpenWebMath (0.34M), arXiv CS (0.12M), Tulu-3 (80k), UltraFeedback (60k),
other (24k). See `metadata/provenance.json` for the full breakdown.

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

- Release hash chain: `e66408aa594d9438…` (sha256-chain-v1, previous v0.3)
- Per-file integrity: `metadata/checksums.sha256` (SHA-256 of every release file)
- Frozen at `2026-07-30T14:40:31.399+00:00`; contents are immutable
