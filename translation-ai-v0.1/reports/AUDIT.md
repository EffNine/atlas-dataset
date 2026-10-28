# Data / Infrastructure Audit — translation-ai-v0.1

Date: 2026-09-17. Method: direct inspection (files, fixtures, configs, code).

## 1. novel-translator (`/home/afnan/projects/active/novel-translator/`)

- **What it is:** Rust CLI (`cargo`, ~191 tests) that parses EPUB/TXT/HTML/folders
  into a canonical `Novel` model and translates via an **external OpenAI-compatible
  API** (or a deterministic mock provider for tests). Phase 3 status.
- **Languages:** zh/ja/ko source detection (script-based), English target. **No Malay.**
- **Training data? NO.** Fixtures are monolingual source texts only
  (`fixtures/{chinese,japanese,korean}/`, `fixtures/real/*/source.txt` from
  Gutenberg/Aozora/Wikisource, all public domain). The sole English file is a
  *generated* EPUB (`output/japanese/source.en.epub`), not a reference corpus.
- **Reusable for us:** language-detection heuristics, normalization rules,
  paragraph-alignment and checkpoint/resume ideas (consumer-side, later).
  Nothing copied — concepts only.
- **Verdict: not a data source. Untouched.**

## 2. Atlas dataset (this workspace)

- Searched `metadata/source_registry.json`, `metadata/sources.json`, `curated/`,
  `pilot/` for translation/parallel content: **no zh/ja/ko/ms↔en parallel corpus exists.**
  (`grep -ril translat` hits are wiki-extraction scripts and CSS, unrelated.)
- Atlas holds general assistant/SFT data (9.5M records, v1.0 released) — wrong shape
  (instruction/response, not parallel translation pairs) and governed/immutable.
- **Verdict: not a data source. Untouched (no reads beyond registry inspection).**

## 3. Decision: external open parallel corpus

- Requirement: real xx→en pairs, 4 languages incl. Malay, permissive license, scriptable.
- **Chosen: Helsinki-NLP/opus-100** (`en-zh`, `en-ja`, `en-ko`, `en-ms` configs),
  direction flipped to xx→en. Pinned revision `805090dc28bf78897da9641cdf08b61287580df9`,
  recorded in `data/raw/acquire_manifest.json` with per-row offsets.
- Caps: zh/ja 60k, ko/ms 40k (200k rows). License note in manifest: mixed upstream
  OPUS licenses, local research/baseline use only, not redistributed.
- Alternatives considered: Tatoeba (too small for ko/ms), Flores (eval-only, small),
  OpenSubtitles-full (heavier than needed for a v0.1 baseline).

## 4. Infrastructure

- GPU: NVIDIA GeForce RTX 5070 12GB, CUDA available, torch 2.13.0+cu130.
- Env: repo `.venv` (torch, transformers, datasets, tokenizers, + sacrebleu installed
  for this project). Tokenizer backend: HF `tokenizers` BPE byte-level (no new
  compiled deps; full CJK coverage, no UNK on text).
- Metrics: sacrebleu (BLEU + chrF). COMET/BERTScore deferred (model downloads,
  not a blocker for run-v1 — stated upfront).

## 5. Contamination controls (enforced in code, not just policy)

- Tokenizer trains on **train split only** (`train_tokenizer.py` reads `train_*`).
- Splits are whole-group partitioned by `sha256(norm(source))` with an
  **asserted zero-leak check** across train/val/test.
- `evaluate.py` never trains/tunes/selects; early stopping uses **val loss only**.
