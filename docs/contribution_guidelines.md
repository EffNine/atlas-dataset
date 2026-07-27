# Contribution Guidelines

These rules apply to anyone (human or agent) adding data to Atlas.

## 1. Source First

- Every item must trace to a registered source in `metadata/sources.json`.
- Never add data whose license is unknown or incompatible. Resolve the license
  **before** the item reaches `curated/`.
- Original sources go to `raw/` and are **never edited in place**.

## 2. No Raw Editing

If a source has an error, note it in the record's `notes` field and fix it in
the cleaned copy — do not rewrite the raw file.

## 3. Canonical Format Only

- All contributions are authored/cleaned into the canonical JSONL schema
  (`schemas/dataset_schema.json`).
- Do not submit model-specific formats (ChatML, Alpaca, etc.) as contributions.

## 4. Required Fields

| Field | Rule |
|---|---|
| `id` | unique, matches `^[a-z0-9_]+$`, follows naming convention |
| `category` | one of the 9 Atlas categories |
| `subcategory` | from controlled list where possible |
| `type` | instruction \| conversation \| qa \| reasoning |
| `source` | `name` + `license` required; `url`/`date` strongly recommended |
| `messages` | ≥1 user + ≥1 assistant turn; non-empty content |
| `tags` | lowercase, hyphenated, ≤20 |
| `quality_score` | 1–10 after scoring; 0 only pre-review |
| `verified` | `false` until a human reviewer approves |

## 5. Quality Gate

- Run `scripts/quality_score.py` and `scripts/validate_dataset.py`.
- Items scoring < 7 are sent back for revision or rejected.
- A second human must confirm `verified=true` before `curated/` promotion.

## 6. Review Workflow

```
author draft  ->  raw/generated or personal_knowledge
      │  clean_dataset.py
      ▼
cleaned (verified=false, quality_score=0)
      │  quality_score.py + human review
      ▼
verified=true  ->  curated/vX.Y  (on next release)
```

## 7. Prohibited Content

- Hallucinated or technically incorrect answers.
- Duplicates of existing records.
- Low-effort / placeholder responses ("I don't know" without value).
- Outdated information presented as current.
- PII or unlicensed third-party text.

## 8. Commit Hygiene

- One logical batch per PR.
- Include the affected category in the PR title.
- Generative additions must cite `generated-synthetic` as source.
