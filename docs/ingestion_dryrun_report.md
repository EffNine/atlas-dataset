# Atlas v0.1 — Pre-Ingestion Report (DRY RUN)

**Generated:** 2026-07-27  
**Mode:** DRY RUN — no data downloaded, transformed, or modified.  
**Manifest:** `metadata/acquisition_manifest_v0.1.json`  
**Plan stub:** `metadata/ingestion_plan_v0.1.json`

## 1. Executive summary

- Sources planned: **38** across **9** batches.
- Target examples: **1000** (matches category balance: yes).
- Estimated download: **3.1 TB** (local reference table; no network used).
- Model-generated synthetic: **37** (3.7%); cap 5% → within cap ✅.
- License gate: **PASS ✅** (enforced by `scripts/validate_dataset.py:is_denied_license`).
- Registry status: **ok ✅**.

## 2. License validation

Every planned license was checked against the commercial-safety gate. Denied licenses (NC / proprietary / ambiguous / unknown) are hard-blocked and **must never be ingested**.

| Source | License | Class | Denied? |
|---|---|---|---|
| f1 (OpenAssistant/oasst1) | Apache-2.0 | permissive | ✅ no |
| f6 (nvidia/HelpSteer2) | CC-BY-4.0 | permissive | ✅ no |
| f5 (HuggingFaceH4/ultrafeedback_) | MIT | permissive | ✅ no |
| f2 (databricks/dolly-15k) | CC-BY-4.0 | permissive | ✅ no |
| s1 (princeton-nlp/SWE-bench) | MIT | permissive | ✅ no |
| s4 (sahil2801/CodeAlpaca-20k) | Apache-2.0 | permissive | ✅ no |
| s6 (allenai/tulu-3-sft-mixture) | ODC-BY | permissive | ✅ no |
| s5 (StackExchange Code (Stack Ov) | CC-BY-SA-4.0 | share-alike | ✅ no |
| s2 (bigcode/the-stack-v2) | BigCode Open RAIL-M | use-restricted | ✅ no |
| y1 (Linux man-pages + kernel doc) | Public domain / MIT-style (man-pages); GFDL for some kernel docs | permissive | ✅ no |
| y2 (Kubernetes official document) | CC-BY-4.0 | permissive | ✅ no |
| y3 (Docker official documentatio) | Apache-2.0 | permissive | ✅ no |
| y4 (Arch Wiki) | CC-BY-SA-4.0 | share-alike | ✅ no |
| y5 (StackExchange Systems (Serve) | CC-BY-SA-4.0 | share-alike | ✅ no |
| m1 (arXiv (cs.LG / cs.CL / cs.AI) | arXiv non-exclusive license | permissive | ✅ no |
| m2 (Open-Platypus) | Apache-2.0 | permissive | ✅ no |
| m3 (allenai/tulu-3-sft-mixture () | ODC-BY | permissive | ✅ no |
| m4 (EleutherAI/the_pile (permiss) | Mixed (per-subset) | review | ✅ no |
| c1 (openai/gsm8k) | MIT | permissive | ✅ no |
| c2 (cais/mmlu) | MIT | permissive | ✅ no |
| c3 (Hendrycks MATH (competition_) | MIT | permissive | ✅ no |
| c5 (open-web-math/open-web-math) | ODC-BY | permissive | ✅ no |
| c6 (allenai/sciq) | CC-BY-4.0 | permissive | ✅ no |
| h2 (arXiv hardware/arch (eess.AR) | arXiv non-exclusive license | permissive | ✅ no |
| h1 (Wikipedia hardware articles) | CC-BY-SA-3.0 | share-alike | ✅ no |
| h4 (StackExchange Electronics + ) | CC-BY-SA-4.0 | share-alike | ✅ no |
| h6 (Atlas synthetic-from-docs (h) | CC-BY-4.0 (generated; human-review) | permissive | ✅ no |
| h3 (WikiChip / SemiWiki-style se) | CC-BY-SA-4.0 (verify) | share-alike | ✅ no |
| b1 (gbharti/finance-alpaca) | MIT | permissive | ✅ no |
| b3 (StackExchange Finance/Econom) | CC-BY-SA-4.0 | share-alike | ✅ no |
| b2 (Wikipedia business / economi) | CC-BY-SA-3.0 | share-alike | ✅ no |
| b4 (Atlas synthetic-from-cases () | CC-BY-4.0 (generated; human-review) | permissive | ✅ no |
| r1 (Project Gutenberg) | Public Domain (US) | permissive | ✅ no |
| r2 (Wikipedia creative-writing /) | CC-BY-SA-3.0 | share-alike | ✅ no |
| r3 (Atlas synthetic-from-style () | CC-BY-4.0 (generated; human-review) | permissive | ✅ no |
| f1 (OpenAssistant/oasst1 (planni) | Apache-2.0 | permissive | ✅ no |
| s6 (allenai/tulu-3-sft-mixture () | ODC-BY | permissive | ✅ no |
| g1 (Atlas synthetic-from-license) | CC-BY-4.0 (generated; human-review) | permissive | ✅ no |

> All planned licenses pass the commercial-safety gate.

## 3. Download-size estimates

Estimates from a local reference table (Phase 2 HF probe + known archive sizes). Entries of `0 B` are locally-generated (no download).

| Source | Est. size | Basis |
|---|---|---|
| f1 | 100.7 MB | HF oasst1 dataset_size (train+val) |
| f6 | 28.6 MB | estimate: 10k conv, CC-BY-4.0 |
| f5 | 762.9 MB | estimate: 64k pairs, MIT |
| f2 | 15.3 MB | HF dolly-15k dataset_size (~16MB; gated) |
| s1 | 397.2 MB | HF SWE-bench dataset_size |
| s4 | 38.1 MB | estimate: 20k code instruct |
| s6 | 1.9 GB | estimate: tulu-3 subset sample |
| s5 | 55.9 GB | estimate: SE code dumps (SO+Unix.SE) XML |
| s2 | 2.7 TB | HF The Stack v2 ~3TB (subset only) |
| y1 | 476.8 MB | estimate: kernel+man-pages scrape |
| y2 | 286.1 MB | estimate: kubernetes.io/docs scrape |
| y3 | 190.7 MB | estimate: docs.docker.com scrape |
| y4 | 381.5 MB | estimate: Arch Wiki dump |
| y5 | 74.5 GB | estimate: SE systems dumps |
| m1 | 46.6 GB | estimate: arXiv cs.LG/CL/AI subset |
| m2 | 114.4 MB | estimate: Open-Platypus 25k |
| m3 | 953.7 MB | estimate: tulu-3 ML subset |
| m4 | 93.1 GB | estimate: Pile permissive subsets |
| c1 | 4.5 MB | HF gsm8k dataset_size |
| c2 | 161.0 MB | HF mmlu dataset_size (all) |
| c3 | 114.4 MB | estimate: Hendrycks MATH |
| c5 | 52.8 GB | HF open-web-math dataset_size |
| c6 | 19.1 MB | estimate: sciq 11k |
| h2 | 4.7 GB | estimate: arXiv hw/arch subset |
| h1 | 286.1 MB | estimate: Wikipedia hw articles |
| h4 | 18.6 GB | estimate: SE Electronics dumps |
| h6 | 0 B (local/generated) | generated locally from licensed docs (no download) |
| h3 | 190.7 MB | estimate: WikiChip scrape (license verify) |
| b1 | 76.3 MB | estimate: finance-alpaca 70k |
| b3 | 9.3 GB | estimate: SE Finance/Econ dumps |
| b2 | 286.1 MB | estimate: Wikipedia business articles |
| b4 | 0 B (local/generated) | generated locally from licensed docs (no download) |
| r1 | 9.3 GB | estimate: Project Gutenberg PD subset |
| r2 | 286.1 MB | estimate: Wikipedia creative articles |
| r3 | 0 B (local/generated) | generated locally from licensed docs (no download) |
| f1 | 100.7 MB | HF oasst1 dataset_size (train+val) |
| s6 | 1.9 GB | estimate: tulu-3 subset sample |
| g1 | 0 B (local/generated) | generated locally from licensed docs (no download) |

**Total estimated download: 3.1 TB**

## 4. Canonical schema mapping

Each source maps to all 12 canonical fields (`schemas/dataset_schema.json`). Below: fields mapped per source (template only — no real content).

| Source | Cat | Schema fields | Missing |
|---|---|---|---|
| f1 | 01_foundation | 12/12 | — |
| f6 | 01_foundation | 12/12 | — |
| f5 | 01_foundation | 12/12 | — |
| f2 | 01_foundation | 12/12 | — |
| s1 | 02_software_engineering | 12/12 | — |
| s4 | 02_software_engineering | 12/12 | — |
| s6 | 02_software_engineering | 12/12 | — |
| s5 | 02_software_engineering | 12/12 | — |
| s2 | 02_software_engineering | 12/12 | — |
| y1 | 03_system_engineering | 12/12 | — |
| y2 | 03_system_engineering | 12/12 | — |
| y3 | 03_system_engineering | 12/12 | — |
| y4 | 03_system_engineering | 12/12 | — |
| y5 | 03_system_engineering | 12/12 | — |
| m1 | 04_ai_machine_learning | 12/12 | — |
| m2 | 04_ai_machine_learning | 12/12 | — |
| m3 | 04_ai_machine_learning | 12/12 | — |
| m4 | 04_ai_machine_learning | 12/12 | — |
| c1 | 06_science_engineering | 12/12 | — |
| c2 | 06_science_engineering | 12/12 | — |
| c3 | 06_science_engineering | 12/12 | — |
| c5 | 06_science_engineering | 12/12 | — |
| c6 | 06_science_engineering | 12/12 | — |
| h2 | 05_hardware_engineering | 12/12 | — |
| h1 | 05_hardware_engineering | 12/12 | — |
| h4 | 05_hardware_engineering | 12/12 | — |
| h6 | 05_hardware_engineering | 12/12 | — |
| h3 | 05_hardware_engineering | 12/12 | — |
| b1 | 07_business_knowledge | 12/12 | — |
| b3 | 07_business_knowledge | 12/12 | — |
| b2 | 07_business_knowledge | 12/12 | — |
| b4 | 07_business_knowledge | 12/12 | — |
| r1 | 08_creative_knowledge | 12/12 | — |
| r2 | 08_creative_knowledge | 12/12 | — |
| r3 | 08_creative_knowledge | 12/12 | — |
| f1 | 09_personal_assistant | 12/12 | — |
| s6 | 09_personal_assistant | 12/12 | — |
| g1 | 09_personal_assistant | 12/12 | — |

Mapping rule per source: `category` ← manifest category; `subcategory` ← first subcategory; `type` ← extraction-method map; `source` ← {name,url,license,date}; `messages` ← user/assistant pair produced by `clean+convert`; `tags` ← subcategories (+ `synthetic` if applicable); `quality_score`/`verified` set downstream.

## 5. Execution plans (per batch)

### B01 (order 1) — Foundation SFT seed (verified, permissive)

- Target examples: 100
- Steps:
  - **f1** (OpenAssistant/oasst1) [permissive] → tree_to_ranked_turn → 40 ex
  - **f6** (nvidia/HelpSteer2) [permissive] → conversation_to_turn → 25 ex
  - **f5** (HuggingFaceH4/ultrafeedback_binarized) [permissive] → chosen_response_pair → 20 ex
  - **f2** (databricks/dolly-15k) [permissive] → prompt_response_pair → 15 ex
    - constraint: gated: accept HF terms; re-verify license on download; record date_added in sources.json

### B02 (order 2) — Software engineering (verified + community)

- Target examples: 200
- Steps:
  - **s1** (princeton-nlp/SWE-bench) [permissive] → issue_to_patch → 50 ex
  - **s4** (sahil2801/CodeAlpaca-20k) [permissive] → instruction_pair → 40 ex
  - **s6** (allenai/tulu-3-sft-mixture) [permissive] → subset_sample → 50 ex
    - constraint: audit per-subset licenses; exclude any NC/restricted sub-component
  - **s5** (StackExchange Code (Stack Overflow / Unix & Linux)) [share-alike] → xml_dump_parse → 40 ex
    - constraint: attribution per record (post id + author + URL)
    - constraint: share-alike tracking in source.license
    - constraint: filter score>=5
    - constraint: strip PII
  - **s2** (bigcode/the-stack-v2) [use-restricted] → subset_permissive_license → 20 ex
    - constraint: subset to per-file permissive licenses only
    - constraint: document RAIL-M behavioral use clauses
    - constraint: record RAIL-M obligations in ingestion runbook

### B03 (order 3) — System engineering (Tier-1 docs + community)

- Target examples: 150
- Steps:
  - **y1** (Linux man-pages + kernel documentation) [permissive] → doc_to_instruction → 30 ex
    - constraint: pin doc version; flag any GFDL subsections for separate tracking
  - **y2** (Kubernetes official documentation) [permissive] → doc_to_instruction → 30 ex
    - constraint: pin doc version
  - **y3** (Docker official documentation) [permissive] → doc_to_instruction → 25 ex
    - constraint: pin doc version
  - **y4** (Arch Wiki) [share-alike] → doc_to_instruction → 25 ex
    - constraint: attribution per article
    - constraint: share-alike tracking
    - constraint: restructure wiki tone to task format
  - **y5** (StackExchange Systems (ServerFault / Unix.SE / Super User / Network Engineering)) [share-alike] → xml_dump_parse → 40 ex
    - constraint: attribution per record
    - constraint: share-alike tracking
    - constraint: filter score>=5
    - constraint: strip PII

### B04 (order 4) — AI & ML (Tier-1 + verified open)

- Target examples: 200
- Steps:
  - **m1** (arXiv (cs.LG / cs.CL / cs.AI / stat.ML)) [permissive] → doc_to_instruction → 50 ex
    - constraint: convert only well-sourced sections
    - constraint: cite arXiv id
    - constraint: flag preprint status
  - **m2** (Open-Platypus) [permissive] → instruction_pair → 50 ex
  - **m3** (allenai/tulu-3-sft-mixture (ML/LLM/agent subsets)) [permissive] → subset_sample → 70 ex
    - constraint: audit per-subset licenses; exclude NC/restricted
  - **m4** (EleutherAI/the_pile (permissive subsets)) [review] → subset_permissive → 30 ex
    - constraint: subset ONLY to permissive components (arXiv, PubMed, FreeLaw, etc.)
    - constraint: exclude restricted subsets
    - constraint: per-record license tagging

### B05 (order 5) — Science & engineering (verified benchmarks + open)

- Target examples: 100
- Steps:
  - **c1** (openai/gsm8k) [permissive] → cot_pair → 25 ex
    - constraint: reserve official test split as EVAL (do not SFT the test split)
  - **c2** (cais/mmlu) [permissive] → mc_to_openqa → 25 ex
    - constraint: reserve official test split as EVAL
    - constraint: convert MC to open-form for SFT
  - **c3** (Hendrycks MATH (competition_math)) [permissive] → cot_pair → 20 ex
  - **c5** (open-web-math/open-web-math) [permissive] → doc_to_instruction → 15 ex
  - **c6** (allenai/sciq) [permissive] → qa_pair → 15 ex

### B06 (order 6) — Hardware (licensed + capped synthetic)

- Target examples: 80
- Steps:
  - **h2** (arXiv hardware/arch (eess.AR, cs.AR, cs.CR)) [permissive] → doc_to_instruction → 30 ex
    - constraint: convert only well-sourced sections
    - constraint: cite arXiv id
  - **h1** (Wikipedia hardware articles) [share-alike] → doc_to_instruction → 20 ex
    - constraint: attribution per article
    - constraint: share-alike tracking
  - **h4** (StackExchange Electronics + Electrical Engineering) [share-alike] → xml_dump_parse → 15 ex
    - constraint: attribution per record
    - constraint: filter score>=5
    - constraint: strip PII
  - **h6** (Atlas synthetic-from-docs (hardware)) [permissive] → doc2qa_synthetic → 12 ex
    - constraint: capped <=15% of hardware category (<=12)
    - constraint: only from licensed docs h1/h2/h4
    - constraint: every record human-reviewed before curated/
  - **h3** (WikiChip / SemiWiki-style semiconductor wikis) [share-alike] → doc_to_instruction → 3 ex
    - constraint: RE-VERIFY license on access
    - constraint: attribution per article
    - constraint: share-alike tracking

### B07 (order 7) — Business (licensed + capped synthetic)

- Target examples: 70
- Steps:
  - **b1** (gbharti/finance-alpaca) [permissive] → instruction_pair → 30 ex
  - **b3** (StackExchange Finance/Economics/Personal Finance) [share-alike] → xml_dump_parse → 20 ex
    - constraint: attribution per record
    - constraint: filter score>=5
    - constraint: strip PII
  - **b2** (Wikipedia business / economics / strategy) [share-alike] → doc_to_instruction → 15 ex
    - constraint: attribution per article
    - constraint: share-alike tracking
  - **b4** (Atlas synthetic-from-cases (business)) [permissive] → doc2qa_synthetic → 5 ex
    - constraint: capped <=15% of business category (<=10)
    - constraint: only from licensed docs b1/b2
    - constraint: every record human-reviewed

### B08 (order 8) — Creative (licensed PD + capped synthetic)

- Target examples: 50
- Steps:
  - **r1** (Project Gutenberg) [permissive] → task_frame → 30 ex
  - **r2** (Wikipedia creative-writing / rhetoric / design) [share-alike] → doc_to_instruction → 10 ex
    - constraint: attribution per article
    - constraint: share-alike tracking
  - **r3** (Atlas synthetic-from-style (creative)) [permissive] → doc2qa_synthetic → 10 ex
    - constraint: capped <=20% of creative category (<=10)
    - constraint: only from PD/Gutenberg style text
    - constraint: every record human-reviewed

### B09 (order 9) — Personal assistant (derived + capped synthetic)

- Target examples: 50
- Steps:
  - **f1** (OpenAssistant/oasst1 (planning/productivity turns)) [permissive] → tree_to_ranked_turn_filtered → 20 ex
    - constraint: sub-filter: planning / productivity / workflow turns only
  - **s6** (allenai/tulu-3-sft-mixture (planning/agentic subset)) [permissive] → subset_sample_filtered → 20 ex
    - constraint: sub-filter: planning / agentic / decision-making
  - **g1** (Atlas synthetic-from-licensed (personal assistant)) [permissive] → doc2qa_synthetic → 10 ex
    - constraint: capped <=20% of 09 category (<=10)
    - constraint: only from licensed planning docs
    - constraint: every record human-reviewed

## 6. Risk flags

- No blocking risks detected in dry run.

## 7. Next step

On human approval, execute batches in `order` using the steps in `metadata/ingestion_plan_v0.1.json`. The real engine will: download → clean → dedup → convert → quality_score → human review → `curated/`, with the denied-license gate enforced by `scripts/validate_dataset.py --strict`.

> **DRY RUN — nothing was downloaded, transformed, or written outside this report and the plan stub.**