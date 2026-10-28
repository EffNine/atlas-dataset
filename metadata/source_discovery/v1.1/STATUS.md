# Atlas Source Discovery v1.1 — STATUS

**State:** CORPUS COMPLETE. No training run. Awaiting decision on zh→en-first
training vs continued JA/KO/MS sourcing.

## Pipeline state

- v1.0 registry: 22 sources (7 INGESTED, 5 VERIFIED, 8 DISCOVERED, 1 FAILED,
  1 BLOCKED_ACCESS). `metadata/source_discovery/v1/source_registry_v1.json`.
- v1.1 corpora: training_ready 2,286,916 rows (final 2,286,897 after 19 JEV
  tombstones) · research_baseline 106,833 · quarantine 19 · terminology
  642,943 terms. Splits 90/5/5, zero cross-split hash leakage (asserted).
- JEV bounded pass: 100 sampled, 100 ok, finals KEEP 81 / REJECT 17 /
  QUARANTINE 2 (53 live AI-2 calls, verdicts cached). Routing signals only.

## Non-goals respected

No model training · no full-corpus JEV · no human-label gate · no gated
(AI-Hub) bypass · no proprietary scraping (Qidian untouched) · no license
upgrades (opus stays UNKNOWN, JParaCrawl-mirror RESTRICTED) · no literary
claims for subtitle data · no invented sources (3 DISCOVERED entries remain
explicitly ambiguous/URL-broken).

## Known gaps (explicit)

JA literary: none · KO literary: none · MS literary: none · KO/MS
dictionaries: none · JParaCrawl official: unreachable (503/DNS) · CC-CEDICT
GitHub URL from v1.0: 404 (MDBG direct download used instead).

## Reversibility

Delete `metadata/source_discovery/v1.1/`, `tmp/source_discovery/v1.1/`, and
the HF cache entries to revert all v1.1 effects. Tracked files added:
`scripts/source_discovery/{corpus_v1_1,terminology,jev_run,audits}.py`,
`cli.py` (v11-* commands), `tests/test_source_discovery_v1_1.py`,
`metadata/source_discovery/v1.1/` manifests + reports. Zero tracked files
modified.

## Next options (not started)

1. translation-ai-v0.2 zh→en training on training_ready.train (114k test
   held out; apply post_jev_removals.json first).
2. Continued JA/KO/MS literary sourcing (official JParaCrawl recovery,
   KO/MS dictionary identification).
3. Wider JEV sampling once training starts producing error profiles.
