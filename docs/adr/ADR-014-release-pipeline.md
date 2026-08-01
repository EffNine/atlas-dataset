# ADR-014: Release Pipeline

**Status:** Accepted
**Date:** 2026-08-01
**Phase:** 4C.4 — Engineering Stabilization

---

## Context

Atlas publishes versioned dataset releases. The release pipeline takes
curated/verified content and produces a **release candidate** (RC), then a
**final release** with:

- A manifest (file list + SHA-256 checksums)
- A bundle (tracked skeleton files; content artifacts such as `.zst`
  excluded from git via `.gitignore`)
- Publishing metadata for Hugging Face
- Governance state (release → gate → release-candidate counts)

Before stabilization, the pipeline had gaps:

1. Missing batch IDs in manifests caused governance mismatches (count
   invariants violated).
2. Release promotion was manual and inconsistent — RC state could be
   promoted without explicit sign-off.
3. Manifests and bundles could drift (files added after manifest creation).
4. No single record of which release state a given bundle was in.

## Decision

Adopt a **versioned, gated release pipeline** with manifest-driven
governance:

1. **Release candidate first**: content is assembled into an RC, validated,
   and reviewed. Promotion to final requires explicit human sign-off.
2. **Manifest is authoritative**: every release has a manifest recording
   files + SHA-256 checksums; verification compares each curated file
   against its own baseline hash (never a shared/reused baseline).
3. **Governance invariants enforced**: missing batch IDs or count
   mismatches (release / gate / release-candidate) block further manifest
   changes until reconciled.
4. **Immutable final releases**: once promoted, a release is frozen
   (see ADR-011). No in-place edits.
5. **Bundle policy**: track skeletons in git, ignore bulk `.zst` artifacts
   via `.gitignore`; the manifest + HF publish record the real artifacts.
6. **Automated promotion tooling**: `release promotion` workflows verify
   state before writing manifests; release metadata is versioned in-repo.

## Rationale

- Manifests with per-file baseline hashes give a verifiable, immutable
  record of exactly what was published.
- Gate + explicit sign-off prevents accidental promotion of unvalidated
  content.
- Skeleton tracking with `.zst` ignored keeps the repo within GitHub's
  100MB file limits while preserving provenance through manifests.
- Governance invariants make mismatches fail loudly at build time, not
  silently at publish time.

## Alternatives Considered

1. **Push directly to final without RC** — rejected: no review gate,
  no quality check before publication.
2. **Store all artifacts in git** — rejected: exceeds GitHub limits;
  binary blobs bloat the repo.
3. **Hashless manifests** — rejected: no integrity verification (see
  ADR-011 rationale).
4. **Human-only release process** — rejected: unverifiable, inconsistent;
  automation is required for reproducibility.

## Consequences

- **Positive**: verifiable releases, gated promotion, clear provenance,
  governance mismatches detected early.
- **Negative**: promotion requires explicit sign-off each time — a process
  cost, intentionally.
- **Negative**: `.zst` artifacts are not in git; a manifest without the
  backing store loses content — mitigated by HF publishing records.

## Future Revisions

- Add signed manifests or registry-based attestation when consumers demand
  stronger integrity.
- Integrate classification summary artifacts and training views into the
  release bundle.
- Automate HF publish verification (re-download + hash-check) post-push.
