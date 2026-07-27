# ADR-002: Commercial-Safe Licensing

**Status:** Accepted
**Date:** 2026-07-27

## Context
Atlas is intended to be a long-term, potentially-commercial knowledge foundation.
A single Non-Commercial (NC), proprietary, or legally-ambiguous record poisons
the entire dataset's commercial usability and can create downstream liability.
Licenses must be evaluated and enforced, not assumed.

## Decision
Atlas is **commercial-safe from day one**. We hard-reject:
- Non-Commercial licenses (`CC-BY-NC*`, `CC-BY-ND*`) — blocks commercial use.
- Proprietary / all-rights-reserved — no redistribution/derivative rights.
- Unknown / ambiguous — cannot confirm commercial safety.
- ToS-violating scrapes (e.g. ShareGPT, Reddit exports).

Allowed (with conditions):
- Permissive (MIT/Apache/BSD/CC-BY*/CC0/ODC-BY/Public Domain/arXiv).
- **Share-alike (CC-BY-SA*)**: permitted commercially but requires per-record
  **attribution** and **share-alike tracking** in `source_attribution`.
- **Use-restricted (BigCode Open RAIL-M)**: only the per-file *permissive* subset
  is ingested; RAIL-M behavioral obligations are documented in the runbook.

The gate is enforced in **one place** — `scripts/validate_dataset.py:
is_denied_license` — and reused by the dry-run engine and the pilot ingestion
via `atlas`. Rejected sources are kept in `metadata/source_registry.json` with
`status: rejected` as a *reference record only* and are never ingested.

## Alternatives
- Allow NC sources but mark them. Rejected: a mixed-license dataset cannot be
  shipped commercially without stripping NC records, which defeats the purpose.
- Decide license case-by-case at ingest. Rejected: error-prone; a single mistake
  is catastrophic. The gate is automatic and deterministic.

## Consequences
- 100% commercial-safe licensing is a hard, testable invariant (`atlas self-test`
  → license-gate-integrity).
- Some high-value sources (The Stack v2, StackExchange) require extra handling
  (subsetting, attribution). This is accepted cost for safety.
- If a rejected source later relicenses (e.g. Apache-2.0), it is re-evaluated and
  moved out of `rejected` only after verification.
