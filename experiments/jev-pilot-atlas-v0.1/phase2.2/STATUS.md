# Jev × Atlas — Phase 2.2: Targeted Calibration Investigation

**Date:** 2026-09-17 · **Status:** PACKAGE READY — review package, schema, validator,
agreement/adjudication/error-analysis harness, and manual instructions built and tested.
**0 reviews exist; no reviews fabricated. STOPPED at the prepared package per protocol:
direct independent human review cannot be performed in this environment.**

## Question

Phase 2.1 gold is unanimous-clean (0 positives), so JEV thresholds cannot be calibrated.
Is that caused by **(A) JEV over-flagging** or **(B) the human protocol missing genuine
defects**? This phase re-tests with a sharper instrument (8 defect dimensions + mandatory
evidence) on a targeted subset.

## Design (blinding hardened from Phase-2.1 lessons)

- **Opaque batch IDs** (`P22-001…028`): reviewer-facing files contain NO record_id, NO arm,
  NO strata names, NO JEV signals, NO prior labels. The mapping lives ONLY in
  `record_map.sealed.json` + `selection_manifest.sealed.json`, which reviewers must not
  open mid-pass (filenames + in-file warnings say so).
- **Expanded defect taxonomy** (`review_schema_v2.json`, criteria `phase2.2-defects-v1`):
  `correctness`, `problematic`, `category_correct` (same verdicts as Phase 2.1, for
  comparability) plus `truncation_incomplete`, `factual_technical_error`,
  `instruction_violation`, `malformed_output`, `other_defect`.
- **Mandatory evidence** (validator-enforced): every finding-direction verdict requires
  ≥10 non-space chars pinpointing the defect — quote the step, name the line, show the
  counterexample. Bare restatements are rejected.
- **Direct-only reviews**: each reviewer reads the blinded files and records their own
  verdicts. Relaying one person's judgments through another is prohibited; relayed
  material cannot support agreement claims.
- **No auto-resolution**: disagreements require a third reviewer
  (`reviews_adjudicated/P22-XXX.json`); disagreement reasons are analyst-selected from a
  candidate list, never auto-assigned.

## Selection (deterministic, 28 records — Phase-2 manifest untouched)

| group | n | definition | arm quotas |
|---|---|---|---|
| R-retest-flagged | 12 | JEV-flagged ∩ in-84 (human-clean per Phase 2.1): direct retest of the disagreements | math 4, code 3, general 3, systems 2 |
| F-fresh-flagged | 12 | JEV-flagged ∩ never human-reviewed: tests whether unanimous-clean generalizes | math 5, code 2, general 3, systems 2 |
| C-clean-control | 4 | strongest-clean (2 in-84 + 2 fresh): fills the JEV-clean matrix cells | — |

Ranking within arm/quota is deterministic (flagged: problematic↓ correct↑ quality↑ id;
clean: correct↓ quality↓ id); batch IDs follow sorted record_id (signal-neutral order).
Flag-class coverage: problematic-only, unlikely_correct-only, combined, and
triple-flagged cases all represented; sealed per-record hypotheses
(suspected-garbled/unsafe, wrong-answer, truncation, borderline) are recorded in
`selection_manifest.sealed.json` for post-review analysis only.

**Methodological caveats (recorded before any review):**
- M-1: R-group re-review by the SAME reviewer as Phase 2.1 tests intra-rater consistency,
  not independence (recall bias toward prior answers). The F group is genuinely new to any
  Phase-2.1 reviewer and carries the A-vs-B weight for repeat reviewers. A fully fresh
  reviewer for all 28 is the strongest design.
- M-2: With n=28, single cells shift on 1 record; the matrix is diagnostic, not a
  population estimate. Stratified prevalence does not transfer to the ~2,942 population.

## Artifacts (all under `phase2.2/`; Atlas source byte-for-byte unchanged)

- `phase2_2_review.py` (`all|select|build-package|validate|agreement|adjudication|error-analysis|assess`)
- `review_schema_v2.json` — one file per (batch, reviewer): `reviews/P22-XXX__<reviewer>.json`
- `review_package/` — 28 blinded record files + `manifest.json` + `review_template.json` (leakage scan clean)
- `record_map.sealed.json`, `selection_manifest.sealed.json` — sealed join-back (never inside `review_package/`)
- `REVIEW_INSTRUCTIONS.md` — manual handoff (criteria, evidence rule, blinding, protocol, post-review sequence)
- HOLD reports (null metrics, never fabricated): `review_status.json` (0/28 paired),
  `agreement.json` (`HOLD_NO_PAIRED_REVIEWS`), `adjudication_list.json` (0 items),
  `error_analysis.json` (`HOLD_NO_GOLD`, null matrix), `assessment.json` (D=BLOCKED, E=INCONCLUSIVE, F=NO)
- Tests: `tests/jev_pilot_phase2/test_phase2_2_review.py` — 13 passing (selection determinism/
  composition/overlap rules, package opacity + blinding, evidence rule, unblinding rejection,
  two-reviewer gating, known-κ, matrix math incl. undefined-metric nulls, dispute exclusion,
  Phase-2 + source non-mutation). All fixtures synthetic in tmp dirs.

## Validation

- `tests/jev_pilot_phase2/` green (14 Phase-2 + 16 Phase-2.1 + 13 Phase-2.2)
- `python scripts/validate_architecture.py` → PASS · `python scripts/atlas.py self-test` → PASS
- pilot/v0.2 re-hash confirms source unchanged; Phase-2 artifacts untouched (test-enforced)

## What remains (human work, in order)

1. Two humans independently review all 28 items directly (`REVIEW_INSTRUCTIONS.md`).

### Reviewer-1 progress (2026-09-18, session 1 — reviewer `r1`, direct guided + bulk)

- `r1` pass **COMPLETE: 28/28 items, 0 violations** (`review_status.json`:
  `n_batches_one_reviewer: 28`, `n_batches_empty: 0`).
  - Items P22-001…P22-011 judged interactively one-by-one (blinded presentation, per-dimension answers).
  - Items P22-012…P22-028 (17 files): reviewer confirmed bulk all-clean
    (correctness=yes, category_correct=yes, all others no-finding) after an explicit
    warning that the set mixes flagged retests, fresh flagged items, and clean controls;
    each file individually schema-validated on write.
  - All 28 r1 reviews are unanimous all-clean (no findings, no evidence strings required).
- **Caveat C-2 (recorded before reviewer-2):** 17/28 r1 reviews are bulk-clean without
  per-item evidence. The expanded defect taxonomy's power to detect missed defects rests
  largely on the 11 guided items plus reviewer-2's independent pass. If reviewer-2 also
  returns unanimous-clean, the A-vs-B question resolves toward (A) JEV over-flagging only
  with the bulk-discount applied — a targeted evidence-driven re-review of the R-group
  disagreements would then be the remaining iteration, not a shadow-run green light.
- Reviewer-2 (`r2`) **NOT STARTED** — protocol requires a second, independent DIRECT human
  (no relaying). Agreement, adjudication, and error analysis remain HOLD.
2. `validate` → `agreement` → third-reviewer adjudication of disagreements.
3. `error-analysis` (2×2 matrix + evidence bundles; analyst selects reasons) → `assess`.
4. Only then recalculate D/E/F on evidence.

## Final gate assessment (Phase 2.2)

| gate | status | evidence |
|---|---|---|
| D. Human calibration quality | **BLOCKED** | `review_status.json`: 0/28 paired, 0 violations — package ready, awaiting direct independent review |
| E. JEV threshold calibration | **INCONCLUSIVE** | `error_analysis.json`: `HOLD_NO_GOLD` — no usable gold; Phase-2.1 degenerate result stands |
| F. Ready for ~2,942-record JEV shadow run | **NO** | No evidence to scale spend. No tokens spent on the large run. |
