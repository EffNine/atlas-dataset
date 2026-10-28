# translation-ai-v0.2 — zh→en data-scaling experiment

First serious Chinese→English model on the Atlas Source Discovery v1.1
training-ready corpus. Controlled experiment: **same 35M-parameter
architecture as translation-ai-v0.1** (4+4 layers, d=384, 6 heads, 16k BPE,
max_len 128, from scratch) — only the data scales (~51k → ~2.04M zh pairs).

Scope: **zh→en ONLY**. No ja/ko/ms training. No JEV in the loop (JEV served
as a corpus filtering layer; its 19 tombstones are excluded, never trained on).

## Pipeline

```
verify_corpus (manifest sha + zh counts + JEV overlay + zero-leakage proof, read-only on Atlas)
  → train_tokenizer (zh TRAIN only, stride-sampled 16k BPE)
  → encode (deterministic pre-tokenization, JEV-excluded)
  → train --config configs/smoke.yaml   (pipeline check: fwd/loss/bwd/ckpt/resume/infer)
  → train --config configs/base.yaml    (full run, early stop on VAL loss)
  → evaluate (fixed held-out zh TEST; loss + BLEU + chrF + failure taxonomy)
```

## Quick start

```bash
V=/home/afnan/projects/active/atlas-dataset/.venv/bin/python
SD=/home/afnan/projects/active/atlas-dataset/metadata/source_discovery/v1.1
export PYTHONPATH=src
cd translation-ai-v0.2

# 1. verify (read-only; aborts on manifest drift / leakage / test tombstones)
$V -m tai.verify_corpus --sdmani $SD --out data/dataset_manifest.json
# 2. tokenizer (TRAIN ONLY — never val/test)
$V -m tai.train_tokenizer --splits $SD/corpus/splits --out data/tokenizer \
    --jev-removals $SD/jev/post_jev_removals.json
# 3. encode
$V -m tai.encode --splits $SD/corpus/splits --tokenizer data/tokenizer/tokenizer.json \
    --jev-removals $SD/jev/post_jev_removals.json --out data/encoded
# 4. smoke test first
$V -m tai.train --config configs/smoke.yaml   # (needs data/encoded_smoke + tokenizer_smoke; see STATUS.md)
# 5. real run (detached, then poll the log)
setsid nohup $V -m tai.train --config configs/base.yaml > checkpoints/run-zh-v1/train_stdout.log 2>&1 < /dev/null &
# 6. evaluate (fixed test set; val never used for selection beyond early stopping)
$V -m tai.evaluate --checkpoint checkpoints/run-zh-v1/ckpt_best.pt \
    --tokenizer data/tokenizer/tokenizer.json --encoded data/encoded \
    --splits $SD/corpus/splits --terminology $SD/terminology/terminology.jsonl \
    --out reports/eval_run-zh-v1.json
# 7. translate
echo "微微一思索，他旋即恍然" | $V -m tai.infer \
    --checkpoint checkpoints/run-zh-v1/ckpt_best.pt \
    --tokenizer data/tokenizer/tokenizer.json --lang zh
```

## Rules (hard, from the milestone)

- zh→en ONLY. No ja/ko/ms training in this milestone.
- Atlas unchanged; v1.1 manifests unchanged; test set immutable; no data deletion.
- Terminology sidecar is NEVER sentence-pair training data (eval diagnostic only).
- JEV is NEVER training labels and NEVER modifies examples (filter layer only).
- No tuning against the test set (early stopping on validation loss only).
- `translation-ai-v0.1/` untouched. No release integration. No production deployment.
- Tomato EN is MT output (distillation-grade); hsc EN provenance unverified.
  Provenance (hsc-wuxia vs tomato) is preserved end-to-end — sources are never
  silently treated as equivalent human-quality references.

## Layout

| Path | What |
|---|---|
| `src/tai/` | `verify_corpus`, `train_tokenizer`, `encode`, `model` (=v0.1), `train`, `evaluate`, `infer`, `utils` (=v0.1) |
| `configs/` | `base.yaml` (real run), `smoke.yaml` (pipeline check) |
| `tests/` | `test_model.py` (=v0.1), `test_corpus_guards.py` |
| `data/` | generated: `dataset_manifest.json`, `tokenizer/`, `encoded/` (+ smoke variants) |
| `checkpoints/` | generated run dirs (`ckpt_best.pt`, `ckpt_last.pt`, `run_manifest.json`, `train_log.jsonl`) |
| `reports/` | eval JSON, comparison, training report, failure analysis |

`model.py`, `utils.py`, `infer.py`, `tests/test_model.py` are byte-identical to
v0.1 (proven infrastructure). `train.py` keeps the v0.1 recipe; only data
plumbing changed (encoded npz input, zh-only, per-source val loss).
