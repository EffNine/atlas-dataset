# Atlas Source Discovery v1.1 — First Training Corpus Build: DATASET REPORT

**Scope:** First real training corpus for translation-ai-v0.2 (NOT yet trained).
**Built:** 2026-09-18. **Pipeline:** `scripts/source_discovery/` (v1.0 + v1.1 modules).
**Isolation:** All artifacts under `metadata/source_discovery/v1.1/` (manifests +
reports tracked; bulk `*.jsonl` gitignored, regenerable from pinned revisions)
and `tmp/source_discovery/v1.1/` (ephemeral). No existing Atlas dataset, and
neither `translation-ai-v0.1` nor any release bundle, was modified.

---

## 1. Corpora produced (license-separated, never silently mixed)

| Corpus | Rows | License states | Content |
|---|---|---|---|
| `corpus/training_ready.jsonl` | 2,286,916 (deterministic-kept) | ALLOW only | hsc + tomato + tatoeba-ko/ms |
| `corpus/research_baseline.jsonl` | 106,833 | UNKNOWN + RESTRICTED | opus-100 + jesc + jparacrawl-verah |
| `corpus/quarantine.jsonl` | 19 | mixed (sampled) | JEV non-KEEP sampled records |
| `corpus/splits/*` | 90/5/5 hash partitions | per parent corpus | train/val/test, zero hash leakage (asserted) |
| `terminology/terminology.jsonl` | 642,943 terms | RESTRICTED (share-alike) | JMdict ja-en + CC-CEDICT zh-en sidecar |
| `jev/post_jev_removals.json` | 19 tombstones | — | MUST-exclude overlay on training_ready + splits |

**Final training-ready after JEV overlay: 2,286,916 − 19 = 2,286,897.**

## 2. Per-source acquisition (exact measured numbers)

| Source | Raw acquired | Kept | Rejected | Keep % | Revision (pinned) |
|---|---|---|---|---|---|
| hsc-wuxia-100k (zh→en, web_novel, MIT) | 204,302 | 180,021 | 24,281 | 88.1 | 7510b5b496ee492c04f23902023f1c75e1379f6e |
| tomato-zh2en (zh→en, web_novel, Apache-2.0, **EN side is MT output**) | 2,097,046 | 2,091,399 | 5,647 | 99.7 | ef8f3982420e540be981976493d0bfabac5a50f7 / zh-en.zip sha256 `bd83bcb9…` (5,883,041,582 B) |
| tatoeba-koen (ko→en, general, CC-BY-2.0-FR) | 11,553 | 11,552 | 1 | 100.0 | eng-kor_links join (11,598 links) |
| tatoeba-msen (ms→en, general, CC-BY-2.0-FR) | 4,113 | 3,944 | 169 | 95.9 | eng-zsm_links join (4,125 links) |
| opus-100 bounded (4 langs, subtitle, **UNKNOWN**) | 50,000 | 47,470 | 2,530 | 94.9 | 805090dc28bf78897da9641cdf08b61287580df9 |
| jesc sample (ja→en, subtitle, **UNKNOWN**) | 30,000 | 29,758 | 242 | 99.2 | split.tar.gz sha (102,198,329 B) |
| jparacrawl-verah sample (ja→en, general, **ntt-research**) | 50,000 | 29,605 | 20,395 | 59.2 | b9e28c23dc1484974523a9ec7b523208ee2d803f / tsv.gz 103,852,669 B |
| **Total** | **2,447,014** | **2,393,749** | **53,265** | **97.8** | — |

Advertised-vs-usable: hsc "100k" name → actual 204,302 rows (pretty name says
200K Stratified); tomato has no advertised count → measured 2,097,046 pairs;
JParaCrawl-mirror "1M" file → sampled 50k, kept 59.2%. Never assume.

## 3. Top rejection reasons (all sources)

duplicate_content 38,805 (hsc stock-phrase repeats 20,334; jpara web-crawl
repeats 17,898) · html_boilerplate 7,278 (tomato MT translator notes 5,130;
jpara boilerplate 2,136) · misaligned_ratio 4,494 · copy_pair 982 (opus 880) ·
wrong-language rows 1,259 total (opus ko 347 worst) · too_long 93 (tomato
chapters >5000 chars) · corrupted_encoding 43 · repeated_text 10.

## 4. By language pair (kept rows, training + baseline)

zh→en 2,285,817 (99.3% training-side is zh) · ja→en 73,898 (all baseline:
jesc 29,758 + jpara 29,605 + opus-ja ~14,535) · ko→en 20,884 (tatoeba 11,552 +
opus-ko ~9,332) · ms→en 13,150 (tatoeba 3,944 + opus-ms ~9,206).
**Counts NOT equalized — this is the measured real corpus.**

## 5. By domain / by license state

Domain: web_novel 2,271,420 (hsc+tomato) · subtitle 77,228 (opus+jesc) ·
general 45,101 (tatoeba+jpara). literary/novel/light_novel/manga sentence
 corpora: **0 verified** (see §7). Terminology sidecar separate (642,943).
License: ALLOW 2,286,916 (training-ready) · UNKNOWN 77,228 + RESTRICTED
29,605 (research-baseline only) · BLOCKED 0 ingested.

## 6. Splits (deterministic, hash-bucket 90/5/5 on content_sha256)

training_ready: train 2,058,552 / val 114,317 / test 114,047.
research_baseline: train 96,248 / val 5,236 / test 5,349.
Guards: global exact content-hash dedup BEFORE splitting; zero cross-split
hash overlap asserted at build; test set isolated (no training use);
per-record `chapter_id` (tomato) and `orig_split` (hsc) preserved for
chapter-level leakage analysis. Limitation: no novel-grouping metadata exists
for chapter-aware partitioning — documented, not solved.

## 7. Language gaps (explicit, not scraped around)

- **JA literary: NONE verified.** Official JParaCrawl site unreachable
  (kecl.ntt.co.jp 503 twice; jparacrawl.org DNS fail). Community mirror
  verified instead (RESTRICTED, noisy — 40.8% rejected). JESC ingested as
  subtitle baseline only. Aozora is monolingual.
- **KO literary: NONE verified.** AI-Hub stays BLOCKED_ACCESS (403, never
  bypassed). KO volume = tatoeba join (11,552, general) + opus-ko baseline.
- **MS literary: NONE verified.** MS volume = tatoeba join (3,944, general)
  + opus-ms baseline. No open ms-en dictionary release found.
- Dictionaries: ja (JMdict 443,275 terms) + zh (CC-CEDICT 199,668 terms)
  ingested as RESTRICTED sidecar; ko/ms dicts are gaps.

## 8. JEV bounded pass (n=100: 50 hsc + 50 tomato; balanced policy v0.2-router-v1)

- JEV evaluated 100/100 ok, 0 errors. 149,988 in / 10,000 out tokens,
  mean latency 0.369 s. No human labels. Routing signals only.
- Bands: HIGH 36 → KEEP (auto) · LOW 11 → REJECT (10 auto + 1 problematic
  rail, p≥0.80) · AMBIGUOUS 53 → 53 live blind AI-2 calls.
- AI-2: 45 ACCEPT→KEEP · 6 REJECT · 2 AMBIGUOUS→QUARANTINE (fail-closed live).
- Finals: **KEEP 81 · REJECT 17 · QUARANTINE 2** → 19 tombstoned from
  training-ready (quarantine.jsonl + post_jev_removals.json).
- Stability note: two pre-cache reruns varied ±3 AI-2 verdicts out of 53
  (single-sample temperament); verdicts are now cached (`jev/ai2_cache.jsonl`)
  so reruns are bit-stable. No accuracy/calibration claims.

## 9. Terminology sidecar (separate from sentence pairs)

JMdict (ja→en, 443,275 rows, license per EDRDG site terms — no in-file header,
verify before redistribution) + CC-CEDICT (zh→en, 199,668 rows, in-file
CC-BY-SA-4.0 header verified). Schema: source_term/target_term + domain +
license + provenance(entry_ref). RESTRICTED share-alike throughout. KO/MS:
gaps, not scraped.

## 10. Provenance & reproducibility

Every training row carries: id, source_lang/target_lang, source/target,
source_id, source_revision, source_record_id (+chapter_id / orig_split /
target_origin where applicable), original_sha256, content_sha256,
quality_status, license_status, acquisition{method, acquired_utc,
parser_format, direction}. Archive hashes recorded (tomato zip, JESC tar,
jpara tsv.gz, dict downloads). Same pinned revisions → same bytes
(deterministic single-pass pipeline; JEV sample is stride-deterministic).

## 11. Known limitations

1. Training-ready is 99.3% zh→en — a zh→en novel/MT-mix model, NOT a
   balanced 4-direction model. JA/KO/MS need volume + literary sources.
2. Tomato EN is MT output (distillation-grade, not human gold).
3. hsc EN provenance (human vs MT) unverified — loose literary alignments
   observed; ratio filter trimmed the worst 3,944.
4. JEV covered 100/2.29M rows (0.004%) — the corpus is
   deterministic-filtered, not JEV-certified.
5. No chapter-aware split partitioning (metadata lacks novel grouping).
6. `dedup` stats block in old staging stats.json files uses legacy key names
   (`n_duplicates` = duplicates dropped inside the quality pass) — superseded
   by `n_duplicates_dropped` in the streamer; counts unaffected.

## 12. Verdict for translation-ai-v0.2

Sufficient to START zh→en training (2.29M ALLOW rows, 114k held-out test,
provenance complete, JEV boundary proven). NOT sufficient for the stated
4-direction novel/manga goal: ja/ko/ms lack volume and lack ANY verified
literary parallel data. Train zh→en first; keep ja/ko/ms on the opus/tatoeba
baseline until literary sources are found. **No training was run in v1.1.**
