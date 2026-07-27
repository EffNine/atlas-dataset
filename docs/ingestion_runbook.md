# Ingestion Runbook (Atlas v0.1 → 1000 verified examples)

This runbook is the operational procedure for filling Atlas v0.1. It is gated
on human approval (see `docs/roadmap.md` decision gates). Do not bulk-ingest
until the Lead signs off.

## Pre-flight (one-time)

- [ ] `metadata/sources.json` has an entry for every upstream source.
- [ ] Licenses resolved — no `unknown` at curated stage.
- [ ] `metadata/categories.json` covers the subcategories you will use.
- [ ] Scripts pass a self-test on `examples/sample_dataset.jsonl`.

## Per-batch procedure

Repeat for each category until the target balance is met (see dataset_card.md):

```
1. COLLECT raw
   raw/<bucket>/<source>_<date>.jsonl
   - external, generated, documentation, conversations, personal_knowledge
   - NEVER edit raw files after write.

2. CLEAN
   python scripts/clean_dataset.py \
       --input raw/generated/draft.jsonl \
       --output tmp/cleaned.jsonl --category 04_ai_machine_learning

3. DEDUP (exact + near)
   python scripts/dedup_dataset.py --input tmp/cleaned.jsonl --drop \
       --output tmp/deduped.jsonl --threshold 0.85
   - inspect the report; near-dup clusters are flagged before dropping.

4. SCORE
   python scripts/quality_score.py --input tmp/deduped.jsonl --write
   - records < 7 are routed back or dropped.

5. VALIDATE (structure + gate)
   python scripts/validate_dataset.py --input tmp/deduped.jsonl --stats
   - fix any schema errors before review.

6. HUMAN REVIEW  (the quality gate)
   - reviewer sets verified=true and a final quality_score on accepted items.
   - second reviewer confirms before promotion to curated/.

7. PROMOTE
   - append verified records to curated/v0.1/atlas_v0.1.jsonl
   - keep raw + tmp artifacts for reproducibility (tmp is gitignored).
```

## Cut a release

```
python scripts/eval_dataset.py --input curated/v0.1/atlas_v0.1.jsonl \
    --split 0.05 --seed 42 --name atlas_v0.1
# writes evaluation/test_sets/atlas_v0.1_test.jsonl + _train.jsonl

# convert to every supported model format (now 6)
for fmt in qwen_chatml llama_instruction mistral_instruct gemma_instruct sharegpt alpaca; do
  python scripts/convert_format.py --format $fmt \
      --input curated/v0.1/atlas_v0.1.jsonl \
      --output curated/v0.1/formats/atlas_v0.1_$fmt.jsonl
done

# write release manifest: changelog, stats, added/removed, input->output hashes
```

## Acceptance gate for v0.1

- >= 1000 examples
- 100% `verified == true`
- 100% `quality_score >= 7`
- 0 `unknown` licenses
- all 9 categories within 0.05 of target share
- deduped (0 exact, near-dup clusters reviewed)
- held-out test split written

Only after all gates pass may model training resume.
