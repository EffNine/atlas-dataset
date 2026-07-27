# ADR-010: Architecture Governance — Enforced Dependency Boundaries

**Status:** Accepted
**Date:** 2026-07-28
**Phase:** 4C.3 — Architecture Governance & Operational Maturity

---

## Context

After Phase 4C.2 (Architecture Hardening), the Atlas codebase has been
refactored to eliminate the majority of duplicated enums, constants, and
validation logic. The canonical modules now exist:

- `atlas_constants.py` — enum registry + license utilities
- `atlas_schema.py` — schema field definitions + patterns
- `atlas_paths.py` — path registry + root discovery
- `validate_dataset.py` — canonical structural validation
- `validate_knowledge_object.py` — knowledge object validation

However, there is no **enforceable mechanism** to prevent future drift.
Without governance:

1. A developer could introduce new duplicated enums (re-creating the original
   debt).
2. A module could import from a higher layer, creating circular dependencies.
3. A new validator could bypass the canonical path registry and hardcode paths.
4. The release module could re-implement structural validation instead of
   delegating to `validate_dataset.py`.

The Phase 4C.0 health report (score: 7.4/10) and the Phase 4C.2 dependency
audit both identified "no governance enforcement" as the single largest
remaining risk to architecture maintainability.

## Decision

Adopt a **formally defined architecture governance contract** with an
**automated policy validator**.

### Components

1. **Governance Contract** (`docs/governance/atlas_architecture_governance.md`)
   - Defines 5-layer dependency model
   - Assigns ownership boundaries for each canonical module
   - Establishes cross-cutting rules (no business logic in CLI, no
     validation duplication in release, no duplicate definitions)
   - Documents exception process via ADR

2. **Architecture Policy Validator** (`scripts/validate_architecture.py`)
   - Automated static analysis that checks:
     - Forbidden imports (lower → higher layer violations)
     - Circular dependency chains
     - Duplicated constants outside canonical modules
     - Duplicated license functions outside `atlas_constants`
     - Duplicated schema definitions outside `atlas_schema`
     - Direct filesystem path construction outside `atlas_paths`
   - Exit 0 = pass, exit 1 = violation found
   - Outputs machine-readable report to `metadata/architecture_validation_report.json`

3. **Architecture Decision Record** (this document)
   - Records the decision for future reference
   - Links to the governance contract and validator

### Scope

The governance contract applies to all `.py` files in the repository
except temporary scripts in `tmp/` (which are ephemeral by nature).

The validator must be run as part of CI before any merge that changes
Python source files.

## Consequences

### Benefits

| Benefit | Description |
|---------|-------------|
| **Lower drift risk** | Automated enforcement prevents gradual erosion of the architecture. |
| **Easier extension** | New modules have clear placement rules — no guessing where code belongs. |
| **Safer refactoring** | Dependency rules ensure changes in one layer don't break higher layers. |
| **Better onboarding** | New contributors can read the governance contract and understand the architecture in minutes. |
| **Auditable compliance** | The validation report provides machine-readable evidence of architectural compliance. |

### Costs

| Cost | Mitigation |
|------|-----------|
| **Additional validation maintenance** | The validator is ~400 lines of pure Python with no dependencies. Maintenance is minimal. |
| **Initial compliance effort** | The validator runs cleanly against the current codebase (no violations). No refactoring needed. |
| **False positives risk** | The validator uses precise pattern matching (regex on import lines, AST for constant definitions). False positives are reviewed as part of the ADR exception process. |
| **Enforcement overhead** | CI integration is a single `python scripts/validate_architecture.py` step. |

### Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| Validator false negative (misses violation) | Medium | Low | Regex + AST based; test suite covers known-good and known-bad cases. |
| Validator false positive (flags compliant code) | Low | Low | Exception process via ADR; quick to override with documented rationale. |
| Developer bypasses validator | Low | Low | CI gates; PR cannot merge without validator pass. |
| Governance contract becomes stale | Medium | Medium | Contract is part of the codebase; versioned alongside the validator. |
| Validator maintenance burden | Low | Low | Pure stdlib, no dependencies, stable rule set. |

## Compliance

All existing code in the repository complies with this governance contract
as of Phase 4C.3. The architecture validator (`scripts/validate_architecture.py`)
returns exit 0 against the current codebase.

---

## References

- `docs/governance/atlas_architecture_governance.md` — Full governance contract
- `scripts/validate_architecture.py` — Automated policy validator
- `docs/architecture_dependency_audit_v0.2.md` — Dependency audit (Phase 4C.2)
- `docs/architecture_health_report.md` — Health report (Phase 4C.0)
- `docs/architecture_hardening_report.md` — Hardening report (Phase 4C.1)
