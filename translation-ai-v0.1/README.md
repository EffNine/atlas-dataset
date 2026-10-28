# translation-ai-v0.1 — Specialized xx→en Neural Machine Translation

A focused, from-scratch encoder-decoder Transformer for
**Chinese→English, Japanese→English, Korean→English, Malay→English**.
Not a chatbot. No pretrained weights. No JEV in the loop. Real data, real training, real metrics.

## Pipeline

```
acquire (opus-100, pinned revision) → preprocess (deterministic filters)
  → splits (hash-partitioned, leak-free) → tokenizer (train-only BPE)
  → train (PyTorch Transformer, AMP, checkpointing, resume)
  → evaluate (loss + BLEU + chrF per language + echo baseline)
```

## Quick start

```bash
V=/home/afnan/projects/active/atlas-dataset/.venv/bin/python
export PYTHONPATH=src

# 1. data (200k raw rows; records revision in manifest)
$V -m tai.acquire --out data/raw --seed 7
# 2. clean
$V -m tai.preprocess --inp data/raw --out data/clean
# 3. splits (asserts zero cross-split key leakage)
$V -m tai.splits --inp data/clean --out data/splits --seed 7
# 4. tokenizer (TRAIN ONLY — never val/test)
$V -m tai.train_tokenizer --splits data/splits --out data/tokenizer --vocab-size 16000
# 5. smoke test first
$V -m tai.train --config configs/smoke.yaml
# 6. real run (background, then poll the log)
nohup $V -m tai.train --config configs/base.yaml > checkpoints/run-v1/train_stdout.log 2>&1 &
# 7. evaluate
$V -m tai.evaluate --checkpoint checkpoints/run-v1/ckpt_best.pt \
    --tokenizer data/tokenizer/tokenizer.json --splits data/splits \
    --out reports/eval_run-v1.json
# 8. translate
echo "夜色的街道" | $V -m tai.infer --checkpoint checkpoints/run-v1/ckpt_best.pt \
    --tokenizer data/tokenizer/tokenizer.json --lang zh
```

## Rules (hard)

- Test data is NEVER used for training, tokenizer fitting, threshold tuning, or model selection.
- No fabricated translations or labels. Metrics come from sacrebleu on held-out test splits.
- Training loss alone is never claimed as translation quality.
- Existing projects (`novel-translator`, Atlas datasets) are read-only inputs at most —
  this project vendors nothing from them and modifies nothing outside `translation-ai-v0.1/`.

## Layout

| Path | What |
|---|---|
| `src/tai/` | `acquire`, `preprocess`, `splits`, `train_tokenizer`, `model`, `train`, `evaluate`, `infer`, `utils` |
| `configs/` | `base.yaml` (real run), `smoke.yaml` (pipeline check) |
| `tests/` | unit tests for preprocessing, splits, model |
| `data/` | generated: `raw/`, `clean/`, `splits/`, `tokenizer/`, `tokenizer_smoke/` |
| `checkpoints/` | generated run dirs (`ckpt_best.pt`, `ckpt_last.pt`, `run_manifest.json`, `train_log.jsonl`) |
| `reports/` | `AUDIT.md`, `DATASET.md`, `EXPERIMENT_REPORT.md`, eval JSON |

## Current baseline (run-v1)

See `reports/EXPERIMENT_REPORT.md`. Model: 4+4 layers, d=384, 6 heads, 16k BPE, ~20M params.
