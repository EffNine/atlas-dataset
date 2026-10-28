# translation-ai-v0.2 — STATUS

## State: RETRAINING AFTER TOKENIZER BUG (spaceless corpus) — full run pending

### Postmortem 2026-09-18: whitespace-stripping tokenizer bug (FOUND, FIXED, RERUNNING)
- `chunk_line` v1 split training text on whitespace, deleting every space.
  The BPE trainer never observed the space byte → space mapped to `<unk>`.
- Effect: the ENTIRE first pipeline (tokenizer → 2.04M encoded rows →
  15-epoch/7.7h training → eval) ran on spaceless text. Val loss 0.65 looked
  good but lived in corrupted space; greedy hypotheses had no spaces
  (`ShangguanTianyousnortedcoldly...`) → sacrebleu BLEU 0.0 (word-tokenized
  metric), while chrF (char-level) still showed learning (hsc 47.46).
- The v0.1 comparison from that run is INVALID and is NOT reported.
  Corrupted artifacts quarantined (`*-corrupt*`), never deleted.
- Fixes: char-slice chunking (spaces preserved, same 300-char memory bound);
  fail-fast roundtrip guard in `train_tokenizer` (aborts on `<unk>`/mismatch);
  `<unk>`-rate canary assert in `encode` (<1%); unit regression test.
- Lesson: the smoke "repetition" read (`Hewashehehe`) was the same space bug
  misdiagnosed. Trust the roundtrip guard, not eyeballing.

### Verified (2026-09-18, read-only on Atlas)
- All 3 `training_ready` split sha256 match `corpus_manifest.json` (sd-v1.1).
- zh ALLOW rows: train 2,044,605 / val 113,497 / test 113,318.
- JEV tombstones located: 18 train + 1 val + 0 test (test immutable, untouched).
- Leakage (content_sha256, exact zh rows): train/test 0, train/val 0, val/test 0.
- Terminology sidecar: 642,943 term rows (199,668 zh) — eval diagnostic only.
- Usable post-JEV: **train 2,044,587 / val 113,496 / test 113,318**.
- Manifest: `data/dataset_manifest.json`.

### Data-inspection decisions (measured, not assumed)
- hsc-wuxia: sentence-level (src p50 ~19 toks, 99.7% fit in 128).
- tomato (92% of zh train): chapter-chunks (src p50 ~890 toks, only ~6% fit in 128).
- `max_len` stays **128**: controlled parity with v0.1 + RTX 5070 12GB budget.
  Tomato truncation is a known, measured limitation → `length/truncation`
  failure analysis in evaluation. No causality claims beyond this limitation.
- Split files are source-grouped → stride sampling for tokenizer + decode sets.

### Safety invariants (asserted in code, not just policy)
- Atlas untouched · manifests unchanged · test set immutable · no deletions.
- zh→en ONLY · terminology never sentence-pair training data.
- JEV never labels, never modifies examples (19 ids excluded at load).
- No test tuning (early stopping on val loss only).

### Next
1. ~~`train_tokenizer` (zh train only, 16k BPE) → `data/tokenizer/`~~ DONE
   (25k-pair stride sample, step=81, chunk-capped 300 chars; vocab 16000)
2. ~~`encode` → `data/encoded/`~~ DONE (train 2,044,587 / val 113,496 /
   test 113,318; npz sha in `data/encoded/encode_manifest.json`)
3. ~~smoke (`configs/smoke.yaml`)~~ DONE — fwd/loss/bwd/ckpt/resume/infer all
   verified (2.48M-param smoke model; infer tuple-unpack bug found + fixed)
4. full run (`configs/base.yaml`, detached, pid logged) → `checkpoints/run-zh-v1/`
   - 35M-param arch identical to v0.1; batch 64×2 accum, AMP, early stop (val, patience 3)
   - ~15,973 opt-steps/epoch ≈ 30 min/epoch + val pass
5. evaluate → `reports/eval_run-zh-v1.json` + comparison + training report

### Training monitor
- `tail -f checkpoints/run-zh-v1/train_stdout.log`
- `checkpoints/run-zh-v1/train_log.jsonl` (machine-readable), `run_manifest.json` (final)
- resume: same command + `--resume checkpoints/run-zh-v1/ckpt_last.pt`
