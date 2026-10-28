# Dataset Manifest / Statistics — translation-ai-v0.1

Source: **Helsinki-NLP/opus-100**, revision `805090dc28bf78897da9641cdf08b61287580df9`
(direction flipped to xx→en; per-row provenance incl. `row_offset` kept on every record).
License note: mixed upstream OPUS licenses — local research/baseline use only, not redistributed.
Record format: `{"id","source_lang","source","target_lang":"en","target", provenance:{...}}`.

## Counts

| pair | raw | kept (clean) | kept% | train | val | test |
|---|---|---|---|---|---|---|
| zh→en | 60,000 | 57,266 | 95.4 | 51,377 | 2,904 | 2,985 |
| ja→en | 60,000 | 57,555 | 95.9 | 51,758 | 2,807 | 2,990 |
| ko→en | 40,000 | 37,265 | 93.2 | 33,551 | 1,830 | 1,884 |
| ms→en | 40,000 | 36,642 | 91.6 | 32,958 | 1,869 | 1,815 |
| **total** | **200,000** | **188,728** | **94.4** | **169,644** | **9,410** | **9,674** |

## Rejections by reason (deterministic filters, first-hit wins)

| reason | zh | ja | ko | ms |
|---|---|---|---|---|
| bad_script (script-based lang-ID) | 1,061 | 940 | 1,945 | 144 |
| duplicate (exact pair) | 930 | 1,068 | 476 | 1,362 |
| misaligned (char ratio outside 1/8–8) | 687 | 434 | 314 | 59 |
| too_long (>1000 chars / >200 tokens) | 56 | 3 | 0 | 1 |
| copy_pair (source == target) | 0 | 0 | 0 | 1,792 |
| empty/malformed | 0 | 0 | 0 | 0 |

Notes:
- ms `copy_pair` (1,792): Malay shares the Latin script with English; identical
  strings are usually untranslated fragments — correctly excluded.
- ko `bad_script` (1,945): opus-100 ko rows contain occasional non-Hangul rows
  (hanja-only / Latin-only) — correctly excluded.
- Splits: per-language `sha256(norm(source))` group partition ≈90/5/5;
  **cross-split near-duplicate key leakage asserted = 0** (`split_manifest.json`).
- Tokenizer (`tokenizers` BPE byte-level, 16k + 4k smoke) trained on **train only**.
