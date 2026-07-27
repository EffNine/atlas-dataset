# Provenance Blocked Queue — Atlas v0.2

**Generated:** 2026-07-28T02:45:00+00:00
**Phase:** Phase 5E.1 — Governance Remediation
**Target Resolution Phase:** Phase 5E.2 — Provenance Resolution

---

## Overview

Two records from the `needs_revision` cohort are blocked on provenance/metadata resolution. These are **Class B** records under the revision taxonomy — their content cannot be revised until the provenance blocker is cleared.

| Count | Classification |
|-------|---------------|
| 2 | B — Metadata/provenance repair |

---

## Blocked Records

### 1. `s5_02_software_engineering_programming_0029`

| Field | Value |
|-------|-------|
| **Batch** | Batch 002 |
| **Category** | 02_software_engineering |
| **Current State** | `needs_revision` |
| **Issue Type** | Provenance restricted |
| **License** | CC-BY-SA-4.0 |
| **Source** | StackExchange Code |
| **Severity** | Medium-high |
| **Provenance Blocker** | ✅ Yes |

**Required Action:**
Add CC-BY-SA-4.0 attribution metadata to the record's lineage or `source_registry.json`. Include share-alike tracking documentation and upstream source URL.

**Downstream Blocker:**
Content revision cannot proceed until provenance is cleared. After resolution, a content depth expansion is also needed.

**Reviewer Decision:**
> *"StackExchange Code content is correct and concise, but the CC-BY-SA-4.0 provenance path needs explicit attribution/share-alike tracking confirmation before approval. Sending to needs_revision so upstream documentation can clear the record."*

---

### 2. `h3_05_hardware_engineering_firmware_0003`

| Field | Value |
|-------|-------|
| **Batch** | Batch 002 |
| **Category** | 05_hardware_engineering |
| **Current State** | `needs_revision` |
| **Issue Type** | Mixed: missing depth + provenance |
| **License** | WikiChip-derived (requires_tracking) |
| **Source** | WikiChip |
| **Severity** | Medium-high |
| **Provenance Blocker** | ✅ Yes |

**Required Action:**
Complete WikiChip attribution documentation in the record's lineage metadata. Confirm attribution wording has been reviewed and accepted.

**Downstream Blocker:**
Content revision cannot proceed until provenance is cleared. After resolution, a content depth expansion is also needed (ROM/EEPROM context, update-role detail, system-context examples).

**Reviewer Decision:**
> *"The firmware definition is accurate but too thin for training use: no ROM/EEPROM context, no update-role detail, no system-context examples. Also carries WikiChip-derived license wording that still needs human-review attribution metadata."*

---

## Resolution Ordering

```
Phase 5E.2 — Provenance Resolution
  ├── s5_...0029: CC-BY-SA-4.0 attribution tracking
  └── h3_...0003: WikiChip attribution metadata
         │
         ▼
Phase 5E.3 — Content Revision (deferred until provenance cleared)
  ├── s5_...0029: programming depth expansion
  └── h3_...0003: firmware definition expansion
```

---

## Escalation Path

If provenance cannot be resolved within 2 revision cycles per record:
1. Document escalation reason in `revision_notes`
2. Set status to `escalated`
3. Route to reviewer-operations for conversion to `rejected`
4. Update `review_queue/rejected.jsonl`

---

## References

- `review/operations/provenance_blocked_queue.json` — machine-readable queue
- `review/revisions/v0.2/revision_queue.json` — parent revision queue
- `docs/v0.2_revision_resolution_plan.md` — full resolution strategy
- `metadata/source_registry.json` — source-level license documentation
