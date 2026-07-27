---
name: Atlas AI Dataset Foundation
version: 0.1.0
status: foundation-scaffold
created: 2026-07-27
license: CC-BY-4.0
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

## Stats (v0.1.0 — scaffold)

| Metric | Value |
|---|---|
| Total examples | 0 (seed examples in `examples/`) |
| Categories | 9 |
| Target v0.1 | 1000 high-quality examples |
| Verified | 0 |
| Avg quality_score | n/a |

Statistics are generated programmatically by `scripts/validate_dataset.py
--stats` and appended to each versioned release manifest.

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
