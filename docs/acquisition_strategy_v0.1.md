# Atlas Dataset — v0.1 Acquisition Strategy

**Generated:** 2026-07-27  
**Status:** Planned — *no data ingested.*  
**Drives:** `metadata/acquisition_manifest_v0.1.json` (machine-readable, batch-ordered).  
**Policy:** `docs/source_policy.md` (commercial-safe only).  
**Registry:** `metadata/source_registry.json` (Phase 2 evaluation).

## 1. Objective

Produce **1,000 high-quality, verified, commercial-safe instruction examples** for Atlas v0.1, 
balanced across the 9 Atlas categories, using only Accept/Review sources from the Phase 2 
registry. Quality gate: `quality_score >= 7` AND `verified == true`. No rejected (NC / 
proprietary / ambiguous) source is ever ingested.

## 2. Category targets & coverage

| Category | Target | Share |
|---|---|---|
| 01_foundation | 100 | 10% |
| 02_software_engineering | 200 | 20% |
| 03_system_engineering | 150 | 15% |
| 04_ai_machine_learning | 200 | 20% |
| 05_hardware_engineering | 80 | 8% |
| 06_science_engineering | 100 | 10% |
| 07_business_knowledge | 70 | 7% |
| 08_creative_knowledge | 50 | 5% |
| 09_personal_assistant | 50 | 5% |
| **Total** | **1000** | **100%** |

## 3. What gets ingested, in order

Batches are ordered by trust + ease: Tier-1/2 verified sources first, community (share-alike) 
next with attribution, capped synthetic last and only where a category is sparse.

### Batch B01 (order 1) — Foundation SFT seed (verified, permissive)

| Source | License | Cat | # | Synthetic | Constraints |
|---|---|---|---|---|---|
| OpenAssistant/oasst1 | Apache-2.0 | 01_foundation | 40 | no | — |
| nvidia/HelpSteer2 | CC-BY-4.0 | 01_foundation | 25 | no | — |
| HuggingFaceH4/ultrafeedback_binarized | MIT | 01_foundation | 20 | no | — |
| databricks/dolly-15k | CC-BY-4.0 | 01_foundation | 15 | no | gated: accept HF terms; re-verify license on download; record date_added in sources.json |

*Batch total: 100 examples.*

### Batch B02 (order 2) — Software engineering (verified + community)

| Source | License | Cat | # | Synthetic | Constraints |
|---|---|---|---|---|---|
| princeton-nlp/SWE-bench | MIT | 02_software_engineering | 50 | no | — |
| sahil2801/CodeAlpaca-20k | Apache-2.0 | 02_software_engineering | 40 | no | — |
| allenai/tulu-3-sft-mixture | ODC-BY | 02_software_engineering | 50 | no | audit per-subset licenses; exclude any NC/restricted sub-component |
| StackExchange Code (Stack Overflow / Unix & Linux) | CC-BY-SA-4.0 | 02_software_engineering | 40 | no | attribution per record (post id + author + URL); share-alike tracking in source.license; filter score>=5; strip PII |
| bigcode/the-stack-v2 | BigCode Open RAIL-M | 02_software_engineering | 20 | no | subset to per-file permissive licenses only; document RAIL-M behavioral use clauses; record RAIL-M obligations in ingestion runbook |

*Batch total: 200 examples.*

### Batch B03 (order 3) — System engineering (Tier-1 docs + community)

| Source | License | Cat | # | Synthetic | Constraints |
|---|---|---|---|---|---|
| Linux man-pages + kernel documentation | Public domain / MIT-style (man-pages); GFDL for some kernel docs | 03_system_engineering | 30 | no | pin doc version; flag any GFDL subsections for separate tracking |
| Kubernetes official documentation | CC-BY-4.0 | 03_system_engineering | 30 | no | pin doc version |
| Docker official documentation | Apache-2.0 | 03_system_engineering | 25 | no | pin doc version |
| Arch Wiki | CC-BY-SA-4.0 | 03_system_engineering | 25 | no | attribution per article; share-alike tracking; restructure wiki tone to task format |
| StackExchange Systems (ServerFault / Unix.SE / Super User / Network Engineering) | CC-BY-SA-4.0 | 03_system_engineering | 40 | no | attribution per record; share-alike tracking; filter score>=5; strip PII |

*Batch total: 150 examples.*

### Batch B04 (order 4) — AI & ML (Tier-1 + verified open)

| Source | License | Cat | # | Synthetic | Constraints |
|---|---|---|---|---|---|
| arXiv (cs.LG / cs.CL / cs.AI / stat.ML) | arXiv non-exclusive license | 04_ai_machine_learning | 50 | no | convert only well-sourced sections; cite arXiv id; flag preprint status |
| Open-Platypus | Apache-2.0 | 04_ai_machine_learning | 50 | no | — |
| allenai/tulu-3-sft-mixture (ML/LLM/agent subsets) | ODC-BY | 04_ai_machine_learning | 70 | no | audit per-subset licenses; exclude NC/restricted |
| EleutherAI/the_pile (permissive subsets) | Mixed (per-subset) | 04_ai_machine_learning | 30 | no | subset ONLY to permissive components (arXiv, PubMed, FreeLaw, etc.); exclude restricted subsets; per-record license tagging |

*Batch total: 200 examples.*

### Batch B05 (order 5) — Science & engineering (verified benchmarks + open)

| Source | License | Cat | # | Synthetic | Constraints |
|---|---|---|---|---|---|
| openai/gsm8k | MIT | 06_science_engineering | 25 | no | reserve official test split as EVAL (do not SFT the test split) |
| cais/mmlu | MIT | 06_science_engineering | 25 | no | reserve official test split as EVAL; convert MC to open-form for SFT |
| Hendrycks MATH (competition_math) | MIT | 06_science_engineering | 20 | no | — |
| open-web-math/open-web-math | ODC-BY | 06_science_engineering | 15 | no | — |
| allenai/sciq | CC-BY-4.0 | 06_science_engineering | 15 | no | — |

*Batch total: 100 examples.*

### Batch B06 (order 6) — Hardware (licensed + capped synthetic)

| Source | License | Cat | # | Synthetic | Constraints |
|---|---|---|---|---|---|
| arXiv hardware/arch (eess.AR, cs.AR, cs.CR) | arXiv non-exclusive license | 05_hardware_engineering | 30 | no | convert only well-sourced sections; cite arXiv id |
| Wikipedia hardware articles | CC-BY-SA-3.0 | 05_hardware_engineering | 20 | no | attribution per article; share-alike tracking |
| StackExchange Electronics + Electrical Engineering | CC-BY-SA-4.0 | 05_hardware_engineering | 15 | no | attribution per record; filter score>=5; strip PII |
| Atlas synthetic-from-docs (hardware) | CC-BY-4.0 (generated; human-review) | 05_hardware_engineering | 12 | yes | capped <=15% of hardware category (<=12); only from licensed docs h1/h2/h4; every record human-reviewed before curated/ |
| WikiChip / SemiWiki-style semiconductor wikis | CC-BY-SA-4.0 (verify) | 05_hardware_engineering | 3 | no | RE-VERIFY license on access; attribution per article; share-alike tracking |

*Batch total: 80 examples.*

### Batch B07 (order 7) — Business (licensed + capped synthetic)

| Source | License | Cat | # | Synthetic | Constraints |
|---|---|---|---|---|---|
| gbharti/finance-alpaca | MIT | 07_business_knowledge | 30 | no | — |
| StackExchange Finance/Economics/Personal Finance | CC-BY-SA-4.0 | 07_business_knowledge | 20 | no | attribution per record; filter score>=5; strip PII |
| Wikipedia business / economics / strategy | CC-BY-SA-3.0 | 07_business_knowledge | 15 | no | attribution per article; share-alike tracking |
| Atlas synthetic-from-cases (business) | CC-BY-4.0 (generated; human-review) | 07_business_knowledge | 5 | yes | capped <=15% of business category (<=10); only from licensed docs b1/b2; every record human-reviewed |

*Batch total: 70 examples.*

### Batch B08 (order 8) — Creative (licensed PD + capped synthetic)

| Source | License | Cat | # | Synthetic | Constraints |
|---|---|---|---|---|---|
| Project Gutenberg | Public Domain (US) | 08_creative_knowledge | 30 | no | — |
| Wikipedia creative-writing / rhetoric / design | CC-BY-SA-3.0 | 08_creative_knowledge | 10 | no | attribution per article; share-alike tracking |
| Atlas synthetic-from-style (creative) | CC-BY-4.0 (generated; human-review) | 08_creative_knowledge | 10 | yes | capped <=20% of creative category (<=10); only from PD/Gutenberg style text; every record human-reviewed |

*Batch total: 50 examples.*

### Batch B09 (order 9) — Personal assistant (derived + capped synthetic)

| Source | License | Cat | # | Synthetic | Constraints |
|---|---|---|---|---|---|
| OpenAssistant/oasst1 (planning/productivity turns) | Apache-2.0 | 09_personal_assistant | 20 | no | sub-filter: planning / productivity / workflow turns only |
| allenai/tulu-3-sft-mixture (planning/agentic subset) | ODC-BY | 09_personal_assistant | 20 | no | sub-filter: planning / agentic / decision-making |
| Atlas synthetic-from-licensed (personal assistant) | CC-BY-4.0 (generated; human-review) | 09_personal_assistant | 10 | yes | capped <=20% of 09 category (<=10); only from licensed planning docs; every record human-reviewed |

*Batch total: 50 examples.*

## 4. Licensing constraints (summary)

- **Permissive (MIT / Apache-2.0 / CC-BY-4.0 / ODC-BY / Public Domain / arXiv):** ingest freely after normal clean → dedup → score → human-review.
- **Share-alike (CC-BY-SA-3.0 / 4.0):** StackExchange, Wikipedia, Arch Wiki. Require **per-record attribution** (post id/author/URL or article) + **share-alike tracking** in `source.license`. Filter score≥5; strip PII.
- **Use-restricted (BigCode Open RAIL-M):** The Stack v2 — **subset only to per-file permissive licenses**; document RAIL-M behavioral obligations in the ingestion runbook. Defer if subsetting tooling is unavailable (counts as Review, not bulk).
- **Gated (databricks/dolly-15k):** re-verify license on download; record accepted terms + `date_added` in `sources.json`.
- **Mixed (The Pile):** ingest **only permissive subsets**, each tagged per-record.
- **Denied (NC / proprietary / ambiguous / ToS-violating):** NEVER ingested. Preserved in registry as `rejected` for reference only.

## 5. Synthetic-data discipline

Model-generated synthetic is capped at **5%** of v0.1 (=50 examples max). Planned synthetic = 
**37** (3.7%): hardware 12, business 5, creative 10, personal-assistant 10. 
All synthetic is **generated strictly from licensed source text** (doc2qa), never bulk model-dreamed, 
and **every synthetic record is human-reviewed before `curated/`**.

> Doc-derived instruction (Linux/K8s/Docker/Arch/arXiv/Wikipedia → Q&A) is **not** counted as synthetic; 
> it is a transform of licensed text, not model generation.

## 6. Success criteria

1. Curated total == 1000 examples, per-category within +/-5% of target.
2. 100% pass schema validation + denied-license gate (scripts/validate_dataset.py).
3. 100% have quality_score >= 7 AND verified == true.
4. Zero records sourced from rejected sources (status=='rejected' in registry).
5. Model-generated synthetic share <= 5% of total (cap).
6. No 'unknown' licenses; every record carries resolved license + attribution metadata where required.
7. Held-out 10% (100 ex) stratified test split frozen; external benchmarks (MMLU/GSM8K test) reserved.
8. Reproducibility: every curated record traceable to a manifest entry (source_id + batch_id).

## 7. Reproducible driver contract

`metadata/acquisition_manifest_v0.1.json` is the single source of truth for automated ingestion. 
A future ingestion driver should:

1. Load the manifest; for each `batch` in `order`, for each `dataset`:
   - Resolve `source_id` → `metadata/source_registry.json` (confirm `status` ∈ {accepted, review}).
   - Enforce `license_constraints` (attribution, RAIL-M subset, gated re-verify, share-alike tagging).
   - Run `extraction_method` → write immutable raw to `raw/<category>/<source_id>/`.
   - Run pipeline: `clean → dedup → convert → quality_score`.
   - Apply `quality_gate` (score≥7) + human review (`verified=true`) before `curated/`.
   - Tag each record with `source_id` + `batch_id` for traceability.
2. After all batches: validate whole set with `scripts/validate_dataset.py --strict` (denied-license gate).
3. Freeze held-out 10% stratified test split; reserve external benchmarks.
4. Emit v0.1 manifest + stats; cut release only after all success criteria pass.

## 8. Notes / risks

- **09_personal_assistant** is the lowest-confidence batch (no dedicated Phase 2 candidate). It reuses 
  planning/agentic slices of oasst1 (f1) and tulu-3 (s6) plus a capped synthetic bridge (g1). 
  Prioritize finding a richer licensed PA source for v0.2.
- **RAIL-M (s2)** is the riskiest batch; if subsetting tooling is not ready, drop its 20 examples and 
  backfill from CodeAlpaca/tulu-3 to keep the 200 SW target.
- **Gated sources (f2)** block on human acceptance of HF terms before their 15 examples can be pulled.

> **STOP — no datasets ingested. Awaiting approval + human gates before Phase 3 execution.**