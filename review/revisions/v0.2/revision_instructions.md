# Atlas v0.2 Revision Instructions

**Version:** 0.2.0
**Phase:** Phase 4B.5.7 — Revision Resolution Workflow
**Cohort:** Batch 001 + Batch 002 needs_revision records
**Governance:** CONTROLLED — no changes to original decisions, rejected records, or curated dataset

---

## 1. Purpose

This document defines the controlled workflow for resolving the 6 `needs_revision` records identified during human review of Batch 001 and Batch 002. The workflow ensures repairs are traceable, re-evaluable, and do not bypass original review governance.

---

## 2. Workflow Overview

```
Identify needs_revision records
        │
        ▼
Classify issue (content / metadata / mixed)
        │
        ▼
Create revision record (revision_template.json)
        │
        ▼
Resolve provenance blockers first (if any)
        │
        ▼
Apply content fix (human rewrite)
        │
        ▼
Re-evaluate (second human review)
        │
        ▼
Update decision (approved or escalated)
```

---

## 3. Revision States

| State | Description |
|---|---|
| `identified` | Record added to revision queue; not yet assigned |
| `in_progress` | Revision work underway |
| `provenance_pending` | Lineage/metadata repair required before content revision |
| `content_revised` | Content rewrite completed; awaiting re-evaluation |
| `re_evaluation_pending` | Ready for second human reviewer |
| `re_evaluation_complete` | Second review rendered a final decision |
| `escalated` | Cannot be repaired; to be converted to rejected |

---

## 4. Revision Ordering

### Phase 1 — Resolve provenance blockers first
Two records have provenance concerns that must be cleared before content revision:

1. **s5_02_software_engineering_programming_0029** — CC-BY-SA-4.0 attribution/share-alike tracking
2. **h3_05_hardware_engineering_firmware_0003** — WikiChip attribution metadata

**Action:** Add explicit attribution and share-alike documentation to `metadata/source_registry.json` or record-level lineage metadata. Do not proceed to content revision until provenance is cleared.

### Phase 2 — Content revision (4 records + 2 after provenance)
All six records require human-authored content expansion to meet training-usefulness standards:

| Record | Focus Area |
|---|---|
| `h2_05_hardware_engineering_embedded_systems_0012` | Bare-metal vs RTOS: use-case implications, scheduler semantics, real-time constraints |
| `b1_07_business_knowledge_finance_0001` | Time value of money: investment return rationale, rate/inflation sensitivity, horizon dependency |
| `h4_05_hardware_engineering_embedded_systems_0004` | Bare-metal vs RTOS: scheduling guarantees, real-time constraints, use-case implications |
| `h3_05_hardware_engineering_firmware_0003` | Firmware: ROM/EEPROM context, update-role detail, system-context examples |
| `s5_02_software_engineering_programming_0029` | Programming concept with expanded explanation and rationale |
| `b2_07_business_knowledge_finance_0002` | Compound interest: nominal vs real rate, compounding frequency, horizon effects |

### Phase 3 — Second human review
Every revised record must be re-evaluated by a human reviewer who was NOT the original reviewer. The second reviewer uses the existing `review/v0.2/checklist.md` and `review/v0.2/template.json`.

---

## 5. Revision Records

Each revision is recorded using `revision_template.json` and stored in `review/revisions/v0.2/` as:

```
review/revisions/v0.2/<record_id>.json
```

The revision record captures:
- Original issue (from the reviewer's feedback)
- Proposed fix (what was changed and why)
- Updated content (the rewritten knowledge object)
- Revision notes (rationale, reviewer comments)
- Resolver identity and timestamp
- Current status in the revision lifecycle

---

## 6. Validation Gates

Before a revised record can move to `approved`:

| Gate | Requirement |
|---|---|
| Content correctness | Revised content contains no factual errors |
| Depth adequacy | Content meets the category-specific depth rubric |
| Provenance cleared | All source/license blockers are documented |
| Attribution retained | CC-BY-SA/RAIL-M attribution metadata is preserved |
| Second review | A different human reviewer evaluated and approved |
| Original decision unchanged | The original `needs_revision` field in the decision file is never overwritten |

---

## 7. Escalation Path

If a record cannot be repaired within two revision cycles:
1. Document the reason in `revision_notes`
2. Set status to `escalated`
3. Route to reviewer-operations for conversion to `rejected`
4. Update `review_queue/rejected.jsonl`

Currently no records are classified as "not repairable" (Class C).

---

## 8. Prohibited Actions

- ❌ Do NOT modify original review decision files (`review/decisions/v0.2/batch_*.jsonl`)
- ❌ Do NOT modify rejected records
- ❌ Do NOT modify the curated dataset (`curated/v0.2/`)
- ❌ Do NOT change release gate state
- ❌ Do NOT approve revisions without second human review
- ❌ Do NOT bypass provenance resolution for mixed-type records

---

## 9. References

| Artifact | Location |
|---|---|
| Revision queue | `review/revisions/v0.2/revision_queue.json` |
| Revision template | `review/revisions/v0.2/revision_template.json` |
| Revision records | `review/revisions/v0.2/<record_id>.json` |
| Batch 001 decisions | `review/decisions/v0.2/batch_001.jsonl` |
| Batch 002 decisions | `review/decisions/v0.2/batch_002.jsonl` |
| Review checklist | `review/v0.2/checklist.md` |
| Review template | `review/v0.2/template.json` |
| Revision analysis | `docs/v0.2_revision_feedback_analysis.md` |
| Resolution plan | `docs/v0.2_revision_resolution_plan.md` |

---

## 10. Completion Criteria

The revision workflow is complete when:
- All 6 revision records have status `re_evaluation_complete` or `escalated`
- Each revised record has a second human review decision
- The revision log is complete and auditable
- v0.2 release remains blocked (other 100 pending records must still be reviewed)
