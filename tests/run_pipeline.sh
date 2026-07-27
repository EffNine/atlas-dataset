#!/usr/bin/env bash
#
# run_pipeline.sh — Reproducible Atlas pipeline validation run.
#
# 1. generate synthetic raw fixture  -> raw/generated/synthetic_test_v1.jsonl
# 2. clean   -> tmp/cleaned.jsonl        (struct + reject invalids)
# 3. dedup   -> tmp/deduped.jsonl        (exact SHA-1 + near LSH, drop)
# 4. quality -> tmp/deduped.jsonl        (write 1-10 scores back)
# 5. validate-> (report)                (schema + structure + dup checks)
# 6. convert -> tmp/converted_<fmt>.jsonl (6 model formats)
# 7. promote -> curated/v0.1/atlas_synthetic_test_v0.1.jsonl
# 8. verify  -> tests/verify_pipeline.py (assertions)
#
# All scripts are stdlib-only and deterministic (seed=42 in the generator).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> [1/8] generate synthetic fixture"
python3 tests/generate_synthetic_test.py

echo "==> [2/8] clean"
python3 scripts/clean_dataset.py --input raw/generated/synthetic_test_v1.jsonl --output tmp/cleaned.jsonl

echo "==> [3/8] dedup (drop)"
python3 scripts/dedup_dataset.py --input tmp/cleaned.jsonl --drop --output tmp/deduped.jsonl

echo "==> [4/8] quality_score (write back)"
python3 scripts/quality_score.py --input tmp/deduped.jsonl --write

echo "==> [5/8] validate"
python3 scripts/validate_dataset.py --input tmp/deduped.jsonl --stats

echo "==> [6/8] convert (6 formats)"
for fmt in qwen_chatml llama_instruction mistral_instruct gemma_instruct sharegpt alpaca; do
  python3 scripts/convert_format.py --format "$fmt" \
    --input tmp/deduped.jsonl --output "tmp/converted_${fmt}.jsonl"
done

echo "==> [7/8] promote to curated/v0.1"
mkdir -p curated/v0.1
cp tmp/deduped.jsonl curated/v0.1/atlas_synthetic_test_v0.1.jsonl

echo "==> [8/8] verify"
python3 tests/verify_pipeline.py
