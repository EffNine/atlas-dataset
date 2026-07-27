# Phase 2 — Source Discovery & Evaluation Report

**Project:** Atlas Dataset Foundation
**Phase:** 2 (Source Discovery & Evaluation) — *research only, no ingestion*
**Date:** 2026-07-27
**Author:** AI Dataset Research Analyst (Hermes)
**Status:** ✅ Complete — awaiting human approval before any download/ingestion.

---

## 1. Summary

This phase produced a **reliable, license-verified acquisition roadmap** for Atlas. We evaluated **53 candidate sources** across the 8 mission categories, scored each on five quality dimensions (accuracy, technical quality, diversity, cleanliness, license clarity), and assigned a recommendation: **Accept / Review / Reject**.

All license facts were verified programmatically against the HuggingFace datasets API (`cardData.license`) and/or the GitHub license API on the generation date. Access-gated sources (HF 401) and vanished repos are explicitly flagged **(gated)** / **(verify)** so they are not silently trusted.

### Recommendation tally

| Recommendation | Count | Meaning |
|---|---|---|
| ✅ Accept | 25 | Clean license + high quality → safe to plan ingestion |
| 🟡 Review | 22 | Usable with conditions (filtering, attribution, un-gating, sub-license audit) |
| ⛔ Reject | 6 | Legal risk, non-commercial, or proprietary → exclude |

### Tier distribution observed

- **Tier 1 (official/academic):** Linux kernel docs, Kubernetes/Docker docs, Arch Wiki, arXiv, Project Gutenberg, Red Hat docs → highest trust, must be converted doc→instruction.
- **Tier 2 (open datasets / expert-generated):** oasst1, Dolly, HelpSteer2, Capybara, tulu-3, FineWeb, Open-Platypus → primary SFT volume.
- **Tier 3 (community):** StackExchange dumps (SO, Unix.SE, ServerFault, Electronics, Finance), LMSYS-chat-1m → high value, share-alike + PII handling required.
- **Tier 4 (synthetic):** alpaca-cleaned variants, CodeAlpaca, finance-alpaca, doc-derived synthetic → **capped** to keep Atlas knowledge-driven, not model-echo.

> **Policy guardrail maintained:** Synthetic-only sources are treated as a minority. Where a category is sparse (hardware, business, creative), we lean on **licensed Tier-1/2 text + capped synthetic-from-docs** rather than bulk synthetic generation.

---

## 2. Best Candidates (flagship picks)

| ID | Dataset | Why it's best-in-class |
|---|---|---|
| S1 | princeton-nlp/SWE-bench | Real GitHub issues + gold patches verified by tests; **MIT**; the gold software-engineering eval & SFT set. |
| C1 | openai/gsm8k | Step-by-step math reasoning; **MIT**; canonical CoT seed + eval. |
| C2 | cais/mmlu | 57-subject reasoning; **MIT**; doubles as held-out eval. |
| F1 | OpenAssistant/oasst1 | Human-curated, ranked, multilingual; **Apache-2.0**. |
| F6 | nvidia/HelpSteer2 | Human-annotated on 5 axes; **CC-BY-4.0**; premium helpful-assistant signal. |
| Y1–Y3 | Linux/K8s/Docker official docs | Tier-1 authoritative; clean permissive licenses. |
| R1 | Project Gutenberg | Truly public-domain creative text; **zero license risk**. |
| M2 | Open-Platypus | Expert-curated science/math/code; **Apache-2.0**. |

---

## 3. Recommended First Data Sources (v0.1 build order)

Atlas v0.1 targets **1,000 verified examples** (roadmap Milestone 1). Proposed ingestion order, prioritizing clean licenses + high quality + category balance:

1. **Foundation (10%):** `oasst1` (ranked turns) + `HelpSteer2` + `Dolly-15k` (after gating accepted).
2. **Software Engineering (20%):** `SWE-bench` (problem→patch) + `CodeAlpaca-20k` + sampled `tulu-3` code subsets.
3. **System Engineering (15%):** Convert **K8s/Docker/Linux/Arch Wiki** docs → instruction (Tier-1); sample **StackExchange Systems** dumps (attribute, filter).
4. **AI/ML (20%):** `Open-Platypus` + `tulu-3` ML subsets + `FineWeb` for continued-pretraining complement.
5. **Science (10%):** `gsm8k` + `mmlu` + `sciq` + `OpenWebMath`.
6. **Hardware (8%):** `arXiv cs.AR/eess.AR` papers + Wikipedia hardware (convert) + **capped** doc-derived synthetic (≤15%).
7. **Business (7%):** `finance-alpaca` (sampled) + Wikipedia business (convert) + **capped** synthetic (≤15%).
8. **Creative (5%):** `Project Gutenberg` (task-framed) + **capped** style-derived synthetic (≤20%).

Every record still passes the existing pipeline: `clean → validate → convert → quality_score (≥7) → human verify → curated/`.

---

## 4. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Share-alike contamination** (CC-BY-SA from StackExchange/Wikipedia/Arch) | High | Track per-record license; keep Atlas's own CC-BY-4.0 but **attribute** upstream; isolate share-alike-derived records if a stricter downstream license is ever required. |
| **RAIL-M use restrictions** (The Stack v2 / StarCoderData) | Med | Do **not** bulk-ingest; subset to per-file permissive licenses; document RAIL-M behavioral clauses; treat as **Review**, not Accept. |
| **Access-gated sources** (Dolly, tinycoder, OpenMathInstruct-2) | Med | Re-verify license on download; record `date_added` + accepted terms in `sources.json`. |
| **Synthetic drift / model echo** | Med | Enforce synthetic cap per category; require human review on every synthetic-derived record; prefer solution-verified math. |
| **PII in community dumps** (StackExchange, LMSYS, HH-RLHF) | High | Parse + strip user identities; sample; exclude raw PII; hold out sensitive subsets. |
| **Non-commercial traps** (alpaca original CC-BY-NC, LIMA NC) | High | Already **Rejected**; never ingest NC sources into a potentially-commercial foundation. |
| **Proprietary references** (vendor datasheets, Cisco docs, Reddit) | High | **Rejected** for ingestion; permitted only as human out-of-band reference, never as source text. |
| **Preprint unreviewed claims** (arXiv) | Low/Med | Convert only well-sourced sections; flag as reference-grade; human-verify factual claims. |

---

## 5. Next-Step Recommendation

1. **Approve the ingestion tier.** Human signs off on the Accept/Review lists. (Decision gate: *Begin bulk ingestion* — currently blocking per roadmap.)
2. **Resolve gated sources.** Accept Dolly-15k / tinycoder / OpenMathInstruct-2 terms; record in `sources.json`.
3. **Run a licensed doc→instruction pilot** on one Tier-1 source (e.g. Kubernetes docs) to validate the conversion + human-review loop before scaling.
4. **Build v0.1 batches** per the category balance above; keep synthetic share under cap.
5. **Re-confirm licenses at download time** — licenses change; the registry is a snapshot, not a permanent grant.

> **STOP — no datasets have been downloaded or ingested. Awaiting human approval before Phase 3 (ingestion).**

---

### Appendix — deliverables produced this phase
- `docs/dataset_candidates.md` — 53 candidates, full scoring + per-category sections.
- `metadata/source_registry.json` — machine-readable registry (status / quality_score / scores / license).
- `docs/phase2_source_discovery_report.md` — this report.
