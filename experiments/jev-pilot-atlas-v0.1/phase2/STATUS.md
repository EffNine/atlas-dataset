# Jev × Atlas — Phase 2: Dataset Preparation & Calibration

**Date:** 2026-09-17 · **Status:** COMPLETE (shadow-only; no source mutation; no training; no release-gate integration)
All artifacts under `experiments/jev-pilot-atlas-v0.1/phase2/`. Atlas source data verified byte-for-byte unchanged (SHA-256 capture in `source_file_sha256.json` + test).

## Gate assessment

| gate | status | evidence |
|---|---|---|
| A. Deduplication analysis | **READY** | deterministic SHA-256 + MinHash manifest; 822 exact groups confirmed; 3,677 unique after exact dedup (2,942 after same-source user-only dedup); provenance per row |
| B. Taxonomy audit | **READY** | independent inference (61 domain-mismatches, 0 confident suspects); general-arm filing issue confirmed at arm level |
| C. Independent category reference | **READY** | `taxonomy_reference_v1.json`, versioned, SHA-256 `a430a07f…`, derived from `metadata/categories.json` + pilot label-mappings |
| D. Human calibration | **BLOCKED** | 96-record stratified set + criteria + labeling sheet prepared; **0 human labels recorded** — status `PENDING_HUMAN_LABELS` |
| E. JEV threshold calibration | **BLOCKED** | depends on D; `INCONCLUSIVE_NO_HUMAN_LABELS` (n_labeled=0) |
| F. Ready for ~2,900-record Jev shadow run | **NO** | dedup-ready (3,677 unique; 2,942 after same-source user-only dedup = the ~2,900 target), taxonomy-ready, reference-ready — but the 96-record calibration must be labeled first so Jev thresholds/flags can be validated before scaling spend |

## What was produced

- **Deduplication**
  - `deduplication_manifest.jsonl` (1,653 rows: 822 exact + 825 user-only + 6 near) — each row: canonical/duplicate record id, arm, source, content SHA-256, dup class, advisory action, human-review flag
  - `deduplication_report.md` + `deduplication_report.json`
  - Classes distinguished: exact duplicate / near duplicate / legitimate repeated (90 cross-source user-only pairs) / human-review (96)
  - **Unique after exact dedup: 3,677** (down from 4,499). The 822 exact groups = `code→general` 366, `math→general` 366, `general→systems` 90.
- **Taxonomy**
  - `taxonomy_audit.json` + `taxonomy_audit_rows.jsonl` (4,499 rows) + `taxonomy_audit_report.md`
  - 0 confident misclassification suspects; 61 low-confidence domain mismatches (false positives of the keyword screen, e.g. math money-word-problems)
  - `general`-arm `03_system_engineering`-label issue confirmed as an **arm-level filing problem** (records are exact dupes of code/systems content), not a content mislabel
- **Independent category reference**
  - `taxonomy_reference_v1.json` — 9 canonical categories + pilot/v0.2 label-mappings; versioned; SHA-256 auditable; `reference_version` field so Jev category-consistency questions compare against it, not the record's own label
- **Human calibration set**
  - `human_calibration_manifest.json` — 96 records, stratified: normal 40, low-JEV 20, flagged 20, outliers 10, spread 6
  - `labeling_sheet.md` — fill-in sheet (Jev signals shown as context only; labelers blinded to Jev answers before their pass)
  - Labeling criteria **defined before** any human labels: `correctness` (substantive yes/no), `problematic` (yes/no), `category_correct` (vs independent reference, yes/no)
  - `human_labels/` directory created and empty — **do not fabricate**; recorded status is `PENDING_HUMAN_LABELS`
- **Threshold calibration**
  - `threshold_calibration.json` — `INCONCLUSIVE_NO_HUMAN_LABELS`; sweep harness ready for `correct` and `problematic` thresholds (0.1–0.9); limitation noted: thresholds fit on the same 96-record set, not independently validated
- **Validation**
  - `tests/jev_pilot_phase2/test_phase2_prep.py` — **14 tests, all passing** (155 s): dedup determinism (stable manifest byte-identical), counts match Phase-1 finding, provenance fields present, no destructive action in manifest, class separation, taxonomy reference hash-reproducible, audit independence, row integrity, calibration stratified + pending + no fabricated labels, threshold inconclusive, source files unmodified (SHA-256), no destructive ops
  - `python scripts/validate_architecture.py` → PASS (497 files, 0 violations)
  - `python scripts/atlas.py self-test` → PASS
  - `source_file_sha256.json` — pilot/v0.2 files hashed at run time; test re-hashes and confirms unchanged

## Next step (to unblock F)

Complete the 96-record human labeling into `phase2/human_labels/<record_id>.json` (3 labels each; two independent labelers per the protocol), then re-run threshold calibration. Only then is a ~2,900-record Jev shadow run justified — run on the **3,677 unique records** (or 2,942 after also dropping same-source user-only redundant pairs), keeping the 96 human-review rows and 6 near-duplicate pairs flagged separately.

---

# Phase 2.1: Human Calibration Execution (2026-09-17)

**Status:** WORKFLOW READY — labeling package, schema, validator, agreement/adjudication/calibration harness, and manual instructions are built and tested. **0 human labels exist; no labels fabricated, inferred, or auto-generated.** Phase stops at the labeling stage per protocol: the remaining work requires two genuine independent humans.

## Finding F-1: the 96-row manifest covers 84 unique records

Verification of `human_calibration_manifest.json` confirmed 96 rows but only **84 unique
`record_id`s**: 9 IDs repeat across the `low_jev` / `flagged` / `outliers` strata
(which overlap by construction — all three select on low Jev quality/correctness).
Each unique record is therefore labeled ONCE per labeler (84 × 2 = 168 judgments),
with strata membership preserved per record for join-back. No manifest content was altered.

## Finding F-2: Phase-2 `labeling_sheet.md` breaks blinding — superseded

`labeling_sheet.md` tabulates Jev quality/correct/problematic per record, which violates
the manifest's own protocol ("Do not reveal Jev answers to labelers before they complete
their own pass"). Phase 2.1 supersedes it with a **blinded** package: labelers must use
`labeling_package/` only and must not open the manifest sheet, `jev_results.jsonl`, or
`jev_pilot_report.json` before their pass. The old sheet is retained untouched as a
Phase-2 artifact; the validator rejects any label file containing Jev-signal fields.

## What was produced (all under `phase2/`; Atlas source byte-for-byte unchanged)

- **Schema** — `human_label_schema_v1.json`: one file per (record, labeler);
  pins `record_id`, `arm`, manifest `content_sha256`, `labeler_id`, ISO-8601 `labeled_at`,
  `criteria_version=phase2-calibration-v1`, `reference_version=taxonomy_reference_v1`,
  `blinded_to_jev=true` attestation, and the 3 yes/no labels. Filename must be
  `<record_id>__<labeler_id>.json`. Adjudicated gold lives separately in
  `human_labels_adjudicated/` — raw independent labels are never overwritten.
- **Tooling** — `phase2_1_labeling.py` (`all|build-package|validate|agreement|adjudication|calibrate|label`):
  blinded-package builder, manifest-conformance validator (sha/arm/filename/timestamp
  checks + Jev-leakage rejection), Cohen's-κ + raw-agreement computation, disagreement
  lister, and threshold sweep (confusion matrices, precision/recall/FPR/FNR, human-pos vs
  human-neg Jev score distributions) against agreed/adjudicated gold only.
  `label --labeler <id>` is an interactive labeling loop (blinded record view, y/n
  prompts, validated writes, resume anytime) so labelers never hand-edit JSON.
- **Blinded package** — `labeling_package/` (84 record files, ~301 KB, full messages +
  category labels + criteria; zero Jev signals — leakage scan clean) + `manifest.json`
  (96→84 mapping) + `label_template.json`.
- **Manual instructions** — `LABELING_INSTRUCTIONS.md`: exact per-labeler steps, blinding
  rule, two-labeler protocol (~5–10 h per labeler estimate), validation commands, and
  the post-labeling sequence (validate → agreement → adjudication → third-labeler
  resolution → calibrate). This is the handoff document for the human work.
- **Status reports (HOLD, null metrics — never fabricated)**
  - `labeling_status.json` — 0/84 records with two labelers, 84 unlabeled, 0 violations.
  - `inter_rater_agreement.json` — `HOLD_NO_PAIRED_LABELS`, all metrics null.
  - `adjudication_list.json` — `HOLD_NO_PAIRED_LABELS`, 0 items.
  - `threshold_calibration_v2.json` — `INCONCLUSIVE_NO_HUMAN_LABELS` (Phase-2
    `threshold_calibration.json` left untouched).
- **Tests** — `tests/jev_pilot_phase2/test_phase2_1_labeling.py`: 16 tests passing
  (84-unique dedup, package determinism + blinding, schema accept/reject incl. sha/arm/
  blinding/leakage/filename/timestamp cases, two-labeler gating, known-κ math,
  adjudication filtering, HOLD-without-labels, hand-counted confusion check,
  disputed-dimension exclusion, label-helper write/refuse/pending/render checks,
  source non-mutation). All fixtures synthetic in tmp dirs.
- **Validation** — `validate_architecture.py` PASS; `atlas.py self-test` PASS;
  Phase-2 suite green; pilot/v0.2 re-hash confirms source unchanged.

## Workspace search for pre-existing genuine labels: NONE FOUND

Searched for `labeler_id` / `labeled_at` / `human_label*` across the repo: no genuine
human judgments exist anywhere (`human_labels/` is empty, manifest rows all
`pending`/`human_labels: null`). No duplicate work to reconcile — labeling starts at 0/84.

## Labeling progress (2026-09-18, session 1)

- `labeler-a` pass **COMPLETE: 84/84 records, 0 violations** (`labeling_status.json`:
  `n_records_one_labeler: 84`, `n_records_unlabeled: 0`).
  - Records 1–26 judged interactively one-by-one (blinded presentation, per-record answers).
  - Records 27–84 (58 files): user reviewed the remaining blinded records, confirmed
    `correctness=yes / problematic=no / category_correct=yes` for all, reconfirmed after
    an explicit warning that this set includes the low-Jev/flagged/outlier rows; each file
    individually schema-validated on write via `write_label`.
  - All 84 labeler-a judgments are unanimous yes/no/yes (no variance in this pass).
- `labeler-b` pass **NOT STARTED** — protocol requires a second, independent human.
  Agreement, adjudication, and threshold calibration remain HOLD until paired labels exist.

## Labeling progress (2026-09-18, session 2 — labeler-b + full pipeline)

- `labeler-b` pass **COMPLETE: 84/84 records, 0 violations** — a second human states direct
  blinded review of all 84 records with unanimous `correctness=yes / problematic=no /
  category_correct=yes`, relayed via the operator. Each file carries a relay-provenance
  note and was individually schema-validated on write. Evidence grade note: relayed
  (not directly observed) second pass — consumers of the gates should weigh this.
- **Agreement** (`inter_rater_agreement.json`, COMPUTED, n=84): raw agreement 1.0 on all
  three dimensions; Cohen's κ **null** on all dimensions (zero variance — mathematically
  undefined, correctly not reported as 1.0); full agreement 84/84.
- **Adjudication** (`adjudication_list.json`): 0 disagreements — no third labeler required.
- **Threshold calibration** (`threshold_calibration_v2.json`, COMPUTED, n_gold=84, 0 excluded):
  **degenerate — supports no threshold choice.** Human gold contains ZERO positives on both
  swept dimensions (no `correctness=no`, no `problematic=yes`), so recall/FNR are undefined
  (null) at every threshold and precision is 0.0 by construction. The sweep reduces to
  JEV's flag-rate-against-unanimous-negative curve, e.g. `problematic` FPR 0.786 (t=0.1) →
  0.024 (t=0.9); `correct` FPR 0.845 (t=0.1) → 0.095 (t=0.9). JEV score distributions:
  human-negative mean 0.546 (`correct`, range 0.02–0.99), 0.346 (`problematic`, range
  0.03–0.94); human-positive n=0 on both.
- **Caveat C-1 (interpret with care):** the set was stratified to oversample likely-bad
  records (16 low-Jev + 13 flagged + 8 outlier rows), yet the unanimous gold contains no
  positives — every JEV flag lands as a false positive. Consistent with either (a) JEV
  systematically over-flagging, or (b) bulk/relayed labeling missing real issues. Either
  way, this gold cannot validate a detection threshold. Do not use these sweeps to justify
  an operating point for the shadow run.

## Final gate assessment (Phase 2.1)

> Phase 2.2 launched as a follow-up investigation (see `../phase2.2/STATUS.md`):
> targeted 28-record blinded re-review (12 flagged retests + 12 flagged fresh + 4 clean
> controls) with an expanded defect taxonomy + mandatory evidence, to determine whether
> the zero-positive Phase-2.1 gold is JEV over-flagging or human misses. Package READY,
> reviews PENDING (0/28 paired).

| gate | status | evidence |
|---|---|---|
| D. Human calibration | **READY (with relay caveat)** | `labeling_status.json`: 84/84 two-labeler, 0 violations, 84/84 blinded, 0 Jev-signal leaks; labeler-b relayed via operator (see session-2 note) |
| E. JEV threshold calibration | **INCONCLUSIVE (computed but degenerate)** | `threshold_calibration_v2.json` COMPUTED, n_gold=84 — but zero human positives ⇒ recall/FNR undefined, precision 0.0 everywhere; no operating point supportable (caveat C-1) |
| F. Ready for ~2,942-record JEV shadow run | **NO** | Calibration executed but cannot validate any detection threshold; unanimous bulk/relayed gold + zero positives do not constitute evidence to scale spend |
