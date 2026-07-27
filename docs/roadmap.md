# Roadmap

## Milestone 0 — Foundation Scaffold ✅ (this deliverable)

- Folder structure, schemas, metadata, configs, docs.
- Four processing scripts (clean / validate / convert / quality_score).
- Seed example dataset (`examples/sample_dataset.jsonl`).
- Pipeline verified end-to-end on seed data.
- **Model training paused by mandate.**

## Milestone 1 — Atlas v0.1 (Awaiting Approval)

Target: **1000 high-quality, verified examples.**

- [ ] Approve bulk ingestion sources & licensing.
- [ ] Build ingestion batches per category per `metadata/categories.json` balance.
- [ ] Clean → dedup → score → human review loop.
- [ ] Reach 1000 examples with `quality_score >= 7` and `verified == true`.
- [ ] Cut `curated/v0.1` with manifest + stats + changelog.
- [ ] Generate v0.1 in all 4 formats (Qwen/Llama/ShareGPT/Alpaca).
- [ ] Freeze evaluation/test_sets held-out split.

## Milestone 2 — Atlas v0.2

- [ ] Scale deduplication (near-duplicate / MinHash) in `processing/deduplication/`.
- [ ] Expand categories; refine subcategory vocabulary.
- [ ] Add multilingual coverage if mandated.
- [ ] Bias & coverage auditing per category.

## Milestone 3 — Atlas v1.0 (First Production Dataset)

- [ ] 5k–10k verified examples (or per agreed target).
- [ ] Formal evaluation against external benchmarks.
- [ ] Model-agnostic release artifacts for Qwen/Llama/DeepSeek/Mistral/Gemma.
- [ ] Published dataset card + versioned DOI-style tag.

## Expansion Principles (always)

- Dataset stays canonical JSONL; formats are generated.
- Raw is immutable; everything downstream is regenerable.
- Quality gate never relaxes below v0.1 threshold.
- New model? Add a template in `configs/formatting/templates.json` — no data migration.

## Decision Gates

| Gate | Blocking? | Owner |
|---|---|---|
| Begin bulk ingestion | YES — needs human approval | Atlas Lead |
| Promote to curated/ | YES — needs 2nd reviewer | Reviewer |
| Cut a release | YES — needs manifest + stats | Atlas Lead |
| Resume model training | YES — needs v0.1 complete | Atlas Lead |
