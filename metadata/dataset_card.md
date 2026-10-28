---
name: Atlas AI Dataset Foundation
version: 1.0
status: released
created: 2026-07-27
released: 2026-08-01
license: Mixed - see by-license table (majority unknown; verify per use)
maintainer: Atlas Lead AI Data Engineer
model_agnostic: true
---

# Atlas Dataset Card

## Overview

Atlas is a **model-agnostic, long-term knowledge foundation** for training
and evaluating 8B-class LLMs (Qwen, Llama, DeepSeek, Mistral, Gemma, and
future models). It is deliberately decoupled from any single model's chat
template. The canonical format is plain JSONL; model-specific formats are
produced by downstream converters and never stored as source of truth.

> The dataset is the long-term asset. Models are replaceable.

## Stats (v1.0 — released 2026-08-01)

| Metric | Value |
|---|---|
| Total examples | 9,515,938 |
| Categories | 9 |
| Release gates | quality + license + human-review + dedup passed |
| Release id | 009285f2099075e6 |

Per-category counts (v1.0 manifest):

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

Top license buckets (v1.0 manifest — verify per use; most records are
license-unknown and unsuitable for commercial training as-is):

| License bucket | Records |
|---|---|
| unknown | 7,972,390 |
| ODC-BY | 1,166,924 |
| MIT | 205,243 |
| CC-BY-SA-3.0 | 112,901 |
| Apache-2.0 | 43,844 |
| CC-BY-4.0 | 10,403 |

Statistics are generated programmatically by `scripts/validate_dataset.py
--stats` and appended to each versioned release manifest. Figures above are
copied from `metadata/releases/v1.0_release.json`.

## Composition

See `metadata/categories.json` for the controlled taxonomy. Target category
balance for v0.1:

| Category | Target share |
|---|---|
| 01_foundation | 10% |
| 02_software_engineering | 20% |
| 03_system_engineering | 15% |
| 04_ai_machine_learning | 20% |
| 05_hardware_engineering | 8% |
| 06_science_engineering | 10% |
| 07_business_knowledge | 7% |
| 08_creative_knowledge | 5% |
| 09_personal_assistant | 5% |

## Schema

- Canonical record: `schemas/dataset_schema.json`
- Chat turn: `schemas/chat_schema.json`

## Intended Use

- Supervised fine-tuning (SFT) of instruction-following 8B-class models.
- Continued pre-training / domain alignment (subset).
- Evaluation against held-out `evaluation/test_sets`.

## Provenance & Licensing

All sources are tracked in `metadata/sources.json`. Original sources are
**never modified** — raw data is preserved under `raw/` permanently.

## Limitations

- v0.1 is small by design (quality over quantity).
- Bias, coverage gaps, and language skew must be tracked per release.

## Versioning

Semantic dataset versioning. Every release records a changelog, statistics,
added/removed data, and a frozen manifest. See `docs/roadmap.md`.
