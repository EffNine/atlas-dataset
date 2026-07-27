# Atlas Dataset — Source Licensing & Commercial-Safety Policy

**Status:** Enforced from Phase 1 / affirmed Phase 2.
**Owner:** Atlas Lead (AI Data Engineer).
**Scope:** Every upstream source evaluated for, planned for, or ingested into Atlas.

---

## 1. Mandate

> **Atlas must be commercial-safe from day one.**
> Reject any source that is Non-Commercial (NC), proprietary, or legally ambiguous.
> Rejected sources are preserved as a *reference record only* and are **never** ingested
> into `raw/`, `curated/`, or any canonical Atlas data.

This policy is non-negotiable: a single NC or proprietary record poisons the
entire dataset's commercial usability. Quality and volume never override it.

---

## 2. License Classification

### ✅ Allowed (commercial-safe, ingest after normal cleaning/review)
| License | Notes |
|---|---|
| MIT | Permissive. |
| Apache-2.0 | Permissive; note patent grant. |
| BSD-2 / BSD-3 | Permissive. |
| CC-BY-4.0 / CC-BY-3.0 | Permissive with attribution. |
| CC0-1.0 | Public-domain dedication. |
| ODC-BY | Open Data Commons attribution (FineWeb, OpenWebMath, tulu-3). |
| Public Domain (e.g. Project Gutenberg, US) | No restrictions. |
| arXiv non-exclusive license | Preprint; no copyright transfer. Use with citation. |

### 🟡 Allowed WITH conditions (track explicitly; do not silently bulk-ingest)
| License / Case | Condition |
|---|---|
| **CC-BY-SA-3.0 / 4.0** | Commercial use allowed, but **share-alike + attribution** required. Record upstream license per record; if Atlas ever ships under a stricter downstream license, isolate these records. |
| **BigCode Open RAIL-M** (The Stack v2, StarCoderData) | Use-restricted (behavioral clauses). Subset to per-file permissive licenses; document RAIL-M obligations in the ingestion runbook; treat as `review`, not `accept`. |
| **Gated / access-restricted** (Dolly-15k, tinycoder, OpenMathInstruct-2) | Re-verify the license on download; record accepted terms + `date_added` in `sources.json`. |

### ⛔ Denied (NEVER ingest)
| License / Case | Why |
|---|---|
| **CC-BY-NC-*** | Non-commercial → blocks commercial use of Atlas. |
| **CC-BY-ND-*** | No derivatives → cannot reshape into instruction format. |
| **Proprietary / all-rights-reserved** | No redistribution/derivative rights (vendor datasheets, Cisco docs, paywalled text). |
| **Unknown / ambiguous** | Cannot confirm commercial safety. Resolve before any use, else reject. |
| **ToS-violating scrapes** (ShareGPT, Reddit exports) | Violates upstream Terms of Service; content not licensed to us. |

---

## 3. Enforcement

1. **Registry gate.** `metadata/source_registry.json` carries `status` per source:
   `accepted | review | rejected | candidate`. A source with `status: rejected`
   is a **reference record only** and is excluded from every ingestion batch.
2. **Pipeline gate.** `scripts/validate_dataset.py` already hard-fails on
   `license == "unknown"`. The ingestion runbook MUST additionally reject any
   record whose resolved license is in the **Denied** set above before promotion
   to `curated/`.
3. **Human gate.** The *Begin bulk ingestion* decision gate (roadmap) requires
   explicit Atlas Lead sign-off; this policy is the first checklist item.

---

## 4. Rejected-Source Reference Record

The authoritative, machine-readable list of rejected sources lives in
`metadata/source_registry.json` (filter `status == "rejected"`). As of Phase 2
these are (kept for reference, never ingested):

| ID | Source | Reason |
|---|---|---|
| F8 | stanfordnlp/lima (LIMA) | CC-BY-NC-4.0 (non-commercial) |
| Y8 | Cisco / vendor proprietary networking docs | Proprietary (all rights reserved) |
| H5 | Manufacturer datasheets / app notes (Intel, AMD, ARM, TI) | Proprietary |
| R4 | Reddit WritingPrompts / r/writing scrapes | Reddit ToS (no license to content) |
| X1 | ShareGPT | No license; violates OpenAI ToS |
| X2 | tatsu-lab/alpaca (original) | CC-BY-NC-4.0 (non-commercial) |

If a previously-rejected source later changes license (e.g. re-released under
Apache-2.0), re-evaluate and move it out of `rejected` only after verification.
