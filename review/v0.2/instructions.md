# Atlas v0.2 Human Review Instructions

**Cohort:** Phase 4B Expansion  
**Version:** v0.2 candidate  
**Generated:** 2026-07-27  
**Authoritative state:** `metadata/v0.2_review_manifest.json`

## Objective
Complete human review for 150 v0.2 expansion records without modifying dataset data.

## Ground Rules
- Do not modify records in `curated/v0.2/data/phase4b_expansion.jsonl`.
- Do not move records to `approved`.
- Do not auto-populate reviewer decisions.
- Human decision remains authoritative.
- Every record must end in exactly one final human decision: `approved`, `needs_revision`, or `rejected`.

## Approval Criteria
- factual correctness
- useful for model training
- supported by category evidence if challenged
- category and difficulty consistent with content
- no unsupported claims or hallucinations
- license attribution coherent with source provenance in record

## Rejection Criteria
- factual errors
- unsupported/hallucinated claims
- unsafe or non-trainable content
- unresolved license or provenance problem

## Needs Revision Criteria
- useful, but incomplete, ambiguous, or contains fixable flaws
- reviewer should note a concrete revision target

## Reviewer Output
Use `review/v0.2/template.json` for one JSON object per reviewed record.
Emit completed entries to `review/v0.2/filled_reviews.jsonl`.
Then update `metadata/v0.2_review_manifest.json` review fields for reviewed records only after explicit human confirmation.

## Release Gate
Release remains blocked while any record is `pending`, `needs_revision`, or `rejected`.
Release may proceed only after every expansion record is `approved`.
