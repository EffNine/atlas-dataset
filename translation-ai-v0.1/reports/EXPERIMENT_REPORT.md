# Experiment Report — translation-ai-v0.1 run-v1 (first real baseline)

## 1. Dataset size by language (clean, kept)

| pair | raw | kept | train | val | test |
|---|---|---|---|---|---|
| zh→en | 60,000 | 57,266 | 51,377 | 2,904 | 2,985 |
| ja→en | 60,000 | 57,555 | 51,758 | 2,807 | 2,990 |
| ko→en | 40,000 | 37,265 | 33,551 | 1,830 | 1,884 |
| ms→en | 40,000 | 36,642 | 32,958 | 1,869 | 1,815 |
| total | 200,000 | 188,728 | 169,644 | 9,410 | 9,674 |

Source: opus-100 rev `805090dc`, xx→en. Splits: hash-partitioned, leak keys = 0.
Details: `reports/DATASET.md`. No test data used for training/tokenizer/tuning/selection.

## 2. Train/val/test sizes

169,644 / 9,410 / 9,674 (see table above; per-language breakdown in §1).

## 3. Model architecture

From-scratch pre-norm encoder-decoder Transformer (`src/tai/model.py`):
4 encoder + 4 decoder layers, d_model 384, 6 heads, d_ff 1536, learned positions,
max_len 128, shared 16k BPE (byte-level, lang-tagged source: `<zh>/<ja>/<ko>/<ms>`).
**35,094,528 params.** No pretrained weights. seed=7 (deterministic algorithms on,
warn-only: cuDNN mem-efficient attention stays non-deterministic — see §9).

Training: AdamW lr 5e-4 (warmup 2000 + cosine), batch 64×2 accum (=128),
label smoothing 0.1, clip 1.0, AMP on, early stop (patience 3, val loss).
Full config: `checkpoints/run-v1/run_manifest.json`.

## 4. Training time

~24 min on RTX 5070 12GB (12 epochs, 15,900 optimizer steps; early stop epoch 11,
best = epoch 8). ~13 opt-steps/s, peak ~4.6 GB VRAM. Eval decode ~131 s.

## 5. Final losses (teacher-forced, label smoothing off)

| pair | val loss | test loss |
|---|---|---|
| zh→en | 3.046 | 3.075 |
| ja→en | 3.401 | 3.343 |
| ko→en | 3.491 | 3.542 |
| ms→en | 2.848 | 2.905 |
| overall best val | **3.167** (epoch 8) | — |

Loss curve: 4.51 → 3.87 → 3.55 → 3.38 → 3.28 → 3.22 → 3.19 → 3.170 → 3.167 → plateau/rise.

## 6. BLEU / chrF per language (sacrebleu, greedy, held-out test)

| pair | BLEU | chrF | echo-baseline BLEU | echo chrF |
|---|---|---|---|---|
| zh→en | **12.89** | **38.13** | 0.06 | 2.23 |
| ja→en | **5.28** | **20.72** | 0.17 | 0.69 |
| ko→en | **4.87** | **19.90** | 1.59 | 1.66 |
| ms→en | **13.43** | **29.69** | 3.24 | 14.47 |

Model beats the echo baseline on every pair/metric. Absolute scores are modest —
expected for 35M params on noisy subtitle data; this is a baseline, not a product.
Raw JSON: `reports/eval_run-v1.json`. No COMET/BERTScore (deferred, non-blocking).

## 7. Sample translations

Good (short/formulaic):
- zh `在这方面，联合国开发计划署可在每个国家发挥作用。` → `In that regard, UNDP can play a role in each country.` (ref: `The United Nations Development Programme has a role to play in each country in this regard.`)
- ms `Saya telah menyakiti awak.` → `I have hurt you.` (exact match)
- ja `ドク？` → `Doc?` (exact; but note: ja test is heavy with trivial `ドク` repetitions — subtitle artifact)

Bad (rare words, repetition trap):
- zh `…制霸铃兰…` (conquer Suzuran) → `If he is a ghost, he could be a ghost.`
- ms `…Raja Versailles.` → `And he's not the King Rill.`
- ko `불량 교도관 없나?` → `No, no, no, no, no, no, no, no, no.`
- ko `정보 메시지가 표시됨Name` → `Message date` (UI-string noise in source data)

## 8. What worked

- End-to-end pipeline real and measurable: acquire→clean→split→tokenize→train→eval→infer.
- Deterministic cleaning (11,272 rows rejected with reasons) + asserted zero-leak splits.
- Smoke run caught nothing, but real run caught two genuine bugs (see §9) — pipeline earns its keep.
- Stable training: monotone val improvement for 8 epochs, early stop fired correctly.
- Every pair beats baseline; zh/ms BLEU ~13 shows the architecture can learn.

## 9. What failed

1. **OOM (batch 128):** RTX 5070 had only ~1 GB free — a resident `llama-server`
   (Qwen3 27B GGUF, port 8090) held 10.5 GB. Fixed with batch 64 + grad-accum 2
   (effective 128). NOTE: the llama-server process was killed during diagnosis;
   it must be restarted (see §11).
2. **Resume RNG bug:** `torch.load(map_location='cuda')` moves RNG ByteTensors to GPU
   while `set_rng_state*` demands CPU tensors → resume crashed. Fixed (`.cpu()`),
   resume verified end-to-end.
3. **Missing tokenizer decoder:** `tokenizers` ByteLevel pre-tokenizer without matching
   decoder → `decode()` emitted literal `Ġ`, underestimating BLEU ~10×
   (zh 1.38 → 12.89 after fix). Fixed in code + re-saved artifacts; eval re-run.
4. **Process-group kill:** a timed-out shell wrapper killed the first training run mid-epoch.
   Recovered via checkpoint resume (proving resumability); reruns use `setsid`-detached launch.
5. **Determinism caveat:** `torch.use_deterministic_algorithms(True, warn_only=True)` —
   CUDA mem-efficient attention backward is non-deterministic, so exact bit-reproducibility
   is NOT claimed; seed-determinism holds for data order, init, splits, tokenizer.
6. Data weaknesses: subtitle noise (UI strings, `Name` suffixes), ja test repetition,
   ko/ja absolute quality still low.

## 10. Recommended next experiment (run-v2, still small)

1. **Data:** add length/ratio tightening (drop 1–2 token pairs), dedupe UI-string noise
   (`Name`-suffixed rows), upsample ko/ja to 60k for balance. Keep caps modest.
2. **Model:** same 35M architecture (do NOT scale yet) + beam search (k=4) at eval;
   add repetition penalty / coverage analysis for the `no,no,no` failure mode.
3. **Training:** resume-from-best is wired; try dropout 0.15 + label smoothing 0.15 for the
   ja/ko overfitting wiggle at epochs 8–9.
4. **Metrics:** add BERTScore (local, no API) as the semantic signal; keep COMET optional.
5. Success criterion for v2: ja/ko BLEU ≥ 8 with no zh/ms regression, same data budget.
