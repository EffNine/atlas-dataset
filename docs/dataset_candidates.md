# Atlas Dataset — Candidate Source Registry (Phase 2)

Generated: 2026-07-27  
Scope: Source discovery & evaluation ONLY. No datasets downloaded or ingested.  
License facts verified via HuggingFace datasets API (cardData.license) / GitHub license API on the generation date; sources marked '(gated)' or '(verify)' were access-gated at check time and must be re-confirmed on download.

## Scoring model

Each candidate is scored 1–10 on five dimensions; **Overall = mean** of the five (rounded).

| Dimension | Meaning |
|---|---|
| Accuracy | factual correctness of content |
| Technical Quality | domain/code/math correctness |
| Diversity | breadth of topics/style |
| Cleanliness | formatting, dedup, PII-freeness |
| License Clarity | how usable/permissive the license is |

License-clarity rubric: permissive (MIT/Apache/CC-BY/ODC-BY/PD)=9–10 · CC-BY-SA (share-alike)=8 · RAIL (use-restricted)=5–6 · gated/restricted=4–5 · NC=3 · proprietary/unknown=1–2.

## Summary table

| ID | Dataset | Category | License | Overall | Rec |
|---|---|---|---|---|---|
| F1 | OpenAssistant/oasst1 | 01_foundation | Apache-2.0 | 9 | ✅ Accept |
| F2 | databricks/dolly-15k | 01_foundation | CC-BY-4.0 (gated; verify on access) | 8 | ✅ Accept |
| F3 | LDJnr/Capybara | 01_foundation | Apache-2.0 | 8 | 🟡 Review |
| F4 | yizhongw/self-instruct | 01_foundation | Apache-2.0 | 8 | 🟡 Review |
| F5 | HuggingFaceH4/ultrafeedback_binarized | 01_foundation | MIT | 9 | ✅ Accept |
| F6 | nvidia/HelpSteer2 | 01_foundation | CC-BY-4.0 | 9 | ✅ Accept |
| F7 | Anthropic/hh-rlhf | 01_foundation | MIT (verify; PII caution) | 8 | 🟡 Review |
| F8 | stanfordnlp/lima (LIMA) | 01_foundation | CC-BY-NC-4.0 (verify; non-commercial) | 8 | ⛔ Reject |
| S1 | princeton-nlp/SWE-bench | 02_software_engineering | MIT | 9 | ✅ Accept |
| S2 | bigcode/the-stack-v2 | 02_software_engineering | BigCode Open RAIL-M (use-restricted) | 8 | 🟡 Review |
| S3 | bigcode/starcoderdata | 02_software_engineering | BigCode Open RAIL-M | 8 | 🟡 Review |
| S4 | sahil2801/CodeAlpaca-20k | 02_software_engineering | Apache-2.0 | 8 | ✅ Accept |
| S5 | StackExchange Code (Stack Overflow / Unix & Linux) | 02_software_engineering | CC-BY-SA-4.0 (attribution + share-alike) | 8 | 🟡 Review |
| S6 | allenai/tulu-3-sft-mixture | 02_software_engineering | ODC-BY | 9 | ✅ Accept |
| S7 | WizardCoder / OpenCodeInstruct-style code data | 02_software_engineering | Apache-2.0 (verify; repo 404 at check) | 8 | 🟡 Review |
| S8 | nampdn-ai/tinycoder | 02_software_engineering | Apache-2.0 (gated; verify) | 7 | 🟡 Review |
| Y1 | Linux man-pages + kernel documentation | 03_system_engineering | Public domain / MIT-style (man-pages); GFDL for some kernel docs | 9 | ✅ Accept |
| Y2 | Kubernetes official documentation | 03_system_engineering | CC-BY-4.0 (docs repo) | 9 | ✅ Accept |
| Y3 | Docker official documentation | 03_system_engineering | Apache-2.0 (docs repo) | 9 | ✅ Accept |
| Y4 | Arch Wiki | 03_system_engineering | CC-BY-SA-4.0 (some GFDL) | 9 | ✅ Accept |
| Y5 | StackExchange Systems (ServerFault, Unix.SE, Super User, Network Engineering) | 03_system_engineering | CC-BY-SA-4.0 | 8 | 🟡 Review |
| Y6 | Red Hat Enterprise Linux / Fedora Documentation | 03_system_engineering | CC-BY-SA-4.0 (Red Hat Customer Portal docs) | 9 | ✅ Accept |
| Y7 | Wikimedia (sysadmin / networking articles) | 03_system_engineering | CC-BY-SA-3.0 | 8 | 🟡 Review |
| Y8 | Cisco / vendor proprietary networking docs (e.g. Cisco Press) | 03_system_engineering | Proprietary (all rights reserved) | 7 | ⛔ Reject |
| M1 | arXiv academic corpus (cs.LG, cs.CL, cs.AI, stat.ML) | 04_ai_machine_learning | arXiv.org perpetual non-exclusive license (preprint; no copyright transfer) | 9 | ✅ Accept |
| M2 | Open-Platypus | 04_ai_machine_learning | Apache-2.0 | 9 | ✅ Accept |
| M3 | allenai/tulu-3-sft-mixture | 04_ai_machine_learning | ODC-BY | 9 | ✅ Accept |
| M4 | EleutherAI/the_pile | 04_ai_machine_learning | Mixed (per-subset; many ODC-BY/CC; some restricted) | 7 | 🟡 Review |
| M5 | lmsys/lmsys-chat-1m | 04_ai_machine_learning | Custom / research-only (verify) | 7 | 🟡 Review |
| M6 | HuggingFaceFW/fineweb | 04_ai_machine_learning | ODC-BY | 8 | ✅ Accept |
| H1 | Wikipedia hardware articles (CPU/GPU/firmware/embedded) | 05_hardware_engineering | CC-BY-SA-3.0 | 8 | 🟡 Review |
| H2 | arXiv hardware/arch papers (eess.AR, cs.AR, cs.CR) | 05_hardware_engineering | arXiv non-exclusive license | 8 | ✅ Accept |
| H3 | WikiChip / SemiWiki-style semiconductor wikis | 05_hardware_engineering | CC-BY-SA-4.0 (verify) | 8 | 🟡 Review |
| H4 | StackExchange Electronics + Electrical Engineering | 05_hardware_engineering | CC-BY-SA-4.0 | 8 | 🟡 Review |
| H5 | Manufacturer datasheets / app notes (Intel, AMD, ARM, TI) | 05_hardware_engineering | Proprietary (all rights reserved) | 8 | ⛔ Reject |
| H6 | Synthetic-from-docs (hardware) | 05_hardware_engineering | CC-BY-4.0 (generated; must human-review) | 7 | 🟡 Review |
| C1 | openai/gsm8k | 06_science_engineering | MIT | 9 | ✅ Accept |
| C2 | cais/mmlu | 06_science_engineering | MIT | 9 | ✅ Accept |
| C3 | Hendrycks MATH (competition_math) | 06_science_engineering | MIT | 9 | ✅ Accept |
| C4 | Ai-MO/OpenMathInstruct-2 | 06_science_engineering | MIT (gated; verify) | 8 | 🟡 Review |
| C5 | open-web-math/open-web-math | 06_science_engineering | ODC-BY | 9 | ✅ Accept |
| C6 | allenai/sciq | 06_science_engineering | CC-BY-4.0 | 9 | ✅ Accept |
| C7 | arXiv physics / engineering preprints | 06_science_engineering | arXiv non-exclusive license | 8 | ✅ Accept |
| B1 | gbharti/finance-alpaca | 07_business_knowledge | MIT | 8 | ✅ Accept |
| B2 | Wikipedia business / economics / strategy articles | 07_business_knowledge | CC-BY-SA-3.0 | 8 | 🟡 Review |
| B3 | StackExchange Finance/Economics/Personal Finance | 07_business_knowledge | CC-BY-SA-4.0 | 8 | 🟡 Review |
| B4 | Synthetic-from-cases (business) | 07_business_knowledge | CC-BY-4.0 (must human-review) | 7 | 🟡 Review |
| R1 | Project Gutenberg | 08_creative_knowledge | Public Domain (US) | 9 | ✅ Accept |
| R2 | Wikipedia creative-writing / rhetoric / design articles | 08_creative_knowledge | CC-BY-SA-3.0 | 8 | 🟡 Review |
| R3 | Synthetic-from-style (creative) | 08_creative_knowledge | CC-BY-4.0 (must human-review) | 7 | 🟡 Review |
| R4 | Reddit WritingPrompts / r/writing scrapes | 08_creative_knowledge | Reddit User Agreement (no free license to content) | 6 | ⛔ Reject |
| X1 | ShareGPT | 01_foundation | No license; violates OpenAI ToS (user content) | 5 | ⛔ Reject |
| X2 | tatsu-lab/alpaca (original) | 01_foundation | CC-BY-NC-4.0 (non-commercial) | 6 | ⛔ Reject |


# 01 · Foundation Skills

## F1 · OpenAssistant/oasst1

- **Source:** OpenAssistant / LAION
- **URL:** https://huggingface.co/datasets/OpenAssistant/oasst1
- **Category:** 01_foundation  (subcategory hint: instruction-following)
- **Tier:** Tier 2
- **Description:** Human-curated assistant conversation trees (ranked, detoxified). Multilingual; strong instruction + reasoning coverage.
- **Format:** JSON (message trees)
- **License:** Apache-2.0
- **Size:** ~84k train / 4.4k val messages (100 MB)

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 8
- Diversity: 9
- Cleanliness: 8
- License Clarity: 10
- **Overall Score: 9**

- **Advantages:** Human-generated, ranked, multilingual (35+ langs), toxicity-filtered.
- **Potential Problems:** Verbose; needs tree->turn extraction; some low-quality branches.
- **Atlas Usage:** Core foundation SFT seed. Extract ranked assistant turns per subcategory (instruction-following, general-reasoning).
- **Recommendation:** ✅ Accept

## F2 · databricks/dolly-15k

- **Source:** Databricks
- **URL:** https://huggingface.co/datasets/databricks/dolly-15k
- **Category:** 01_foundation  (subcategory hint: instruction-following)
- **Tier:** Tier 2
- **Description:** 15k human-written prompt/response pairs by Databricks employees across 8 instruction categories (open Q&A, brainstorming, classification, etc.).
- **Format:** JSON
- **License:** CC-BY-4.0 (gated; verify on access)
- **Size:** ~15k examples (16 MB)

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 8
- Diversity: 7
- Cleanliness: 9
- License Clarity: 9
- **Overall Score: 8**

- **Advantages:** Genuinely human-written; clean; broad instruction types.
- **Potential Problems:** Access-gated (must accept on HF); some categories shallow; English only.
- **Atlas Usage:** Foundation SFT seed for instruction-following + communication. High trust after gating accepted.
- **Recommendation:** ✅ Accept
- **Notes:** HF returns 401 (gated). License reported CC-BY-4.0 by Databricks; confirm on download.

## F3 · LDJnr/Capybara

- **Source:** LDJnr
- **URL:** https://huggingface.co/datasets/LDJnr/Capybara
- **Category:** 01_foundation  (subcategory hint: communication)
- **Tier:** Tier 2
- **Description:** 430k+ ShareGPT-derived instruction pairs, deduplicated and cleaned, with diverse system personas (derived from LMSYS personas).
- **Format:** JSON / ShareGPT
- **License:** Apache-2.0
- **Size:** ~430k examples

**Quality Assessment (1–10):**

- Accuracy: 7
- Technical Quality: 7
- Diversity: 9
- Cleanliness: 8
- License Clarity: 10
- **Overall Score: 8**

- **Advantages:** Large, deduplicated, persona-diverse; permissive license.
- **Potential Problems:** Derived from ShareGPT (upstream ToS risk in original) — Capybara re-cleans but provenance is user-chat; spot-check for PII.
- **Atlas Usage:** Foundation diversity booster. Sample with quality/gender/depth filters; do not ingest raw ShareGPT.
- **Recommendation:** 🟡 Review
- **Notes:** ShareGPT upstream is ToS-risky; Capybara's reprocessing reduces but does not eliminate provenance risk. Sample, don't bulk-import.

## F4 · yizhongw/self-instruct

- **Source:** University of Washington
- **URL:** https://github.com/yizhongw/self-instruct
- **Category:** 01_foundation  (subcategory hint: instruction-following)
- **Tier:** Tier 2/4
- **Description:** Seed 175 human tasks + 52k model-generated instructions; the canonical bootstrapping dataset for instruction following.
- **Format:** JSON
- **License:** Apache-2.0
- **Size:** ~52k examples

**Quality Assessment (1–10):**

- Accuracy: 7
- Technical Quality: 7
- Diversity: 7
- Cleanliness: 7
- License Clarity: 10
- **Overall Score: 8**

- **Advantages:** Foundational method; permissive; good for synthetic-pipeline bootstrapping.
- **Potential Problems:** Heavily synthetic (Tier 4 upstream); repetition; weaker factual accuracy.
- **Atlas Usage:** Used as a TEMPLATE/METHOD reference and small seed, not a bulk source (synthetic cap applies).
- **Recommendation:** 🟡 Review

## F5 · HuggingFaceH4/ultrafeedback_binarized

- **Source:** HuggingFace
- **URL:** https://huggingface.co/datasets/HuggingFaceH4/ultrafeedback_binarized
- **Category:** 01_foundation  (subcategory hint: problem-solving)
- **Tier:** Tier 2
- **Description:** 64k+ instructions with 4-way preference annotations (helpfulness, correctness, coherence, complexity, verbosity); binarized for SFT/DPO.
- **Format:** JSON
- **License:** MIT
- **Size:** ~64k examples

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 8
- Diversity: 8
- Cleanliness: 9
- License Clarity: 10
- **Overall Score: 9**

- **Advantages:** MIT; rich multi-attribute signals; usable as instruction + preference data.
- **Potential Problems:** Chosen responses are model-generated (Tier 4); needs human/verifier pass for factual claims.
- **Atlas Usage:** Foundation quality signal + instruction pairs. Use chosen responses as SFT after accuracy filter.
- **Recommendation:** ✅ Accept

## F6 · nvidia/HelpSteer2

- **Source:** NVIDIA
- **URL:** https://huggingface.co/datasets/nvidia/HelpSteer2
- **Category:** 01_foundation  (subcategory hint: communication)
- **Tier:** Tier 2
- **Description:** 10k multi-turn conversations annotated on helpfulness, correctness, coherence, complexity, verbosity by humans.
- **Format:** JSON / CSV
- **License:** CC-BY-4.0
- **Size:** ~10k conversations

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 9
- Diversity: 7
- Cleanliness: 9
- License Clarity: 10
- **Overall Score: 9**

- **Advantages:** Human-annotated on 5 clear axes; CC-BY-4.0; excellent for helpful-assistant behavior.
- **Potential Problems:** Modest size; English; some topics narrow.
- **Atlas Usage:** Premium foundation seed for helpful-assistant + correctness alignment. High trust.
- **Recommendation:** ✅ Accept

## F7 · Anthropic/hh-rlhf

- **Source:** Anthropic
- **URL:** https://huggingface.co/datasets/Anthropic/hh-rlhf
- **Category:** 01_foundation  (subcategory hint: communication)
- **Tier:** Tier 2
- **Description:** 170k human-red-team + preference dialogues (harmless/helpful). Strong helpful-assistant and safety signal.
- **Format:** JSON
- **License:** MIT (verify; PII caution)
- **Size:** ~170k examples

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 8
- Diversity: 8
- Cleanliness: 7
- License Clarity: 8
- **Overall Score: 8**

- **Advantages:** High-quality human preference; MIT listed.
- **Potential Problems:** Potential PII in red-team chats; safety content needs careful curation; large.
- **Atlas Usage:** Foundation helpfulness/safety signal. Anonymize + sample; exclude raw PII.
- **Recommendation:** 🟡 Review

## F8 · stanfordnlp/lima (LIMA)

- **Source:** Stanford
- **URL:** https://huggingface.co/datasets/stanfordnlp/lima
- **Category:** 01_foundation  (subcategory hint: instruction-following)
- **Tier:** Tier 2
- **Description:** 1k carefully hand-curated prompt/response pairs demonstrating 'less is more' high-quality alignment.
- **Format:** JSON
- **License:** CC-BY-NC-4.0 (verify; non-commercial)
- **Size:** ~1k examples

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 9
- Diversity: 6
- Cleanliness: 10
- License Clarity: 4
- **Overall Score: 8**

- **Advantages:** Very high quality; canonical exemplar set.
- **Potential Problems:** Non-commercial license reported -> blocks commercial use of Atlas; tiny volume.
- **Atlas Usage:** Use only if Atlas is research-only; otherwise Reject. Good as few-shot exemplar reference.
- **Recommendation:** ⛔ Reject
- **Notes:** NC license incompatible with a potentially-commercial foundation. Flagged Reject unless mandate is research-only.

## X1 · ShareGPT

- **Source:** ShareGPT community scrape
- **URL:** https://sharegpt.com/
- **Category:** 01_foundation  (subcategory hint: communication)
- **Tier:** Tier 4 (non-compliant)
- **Description:** User-shared ChatGPT/LLM conversation exports.
- **Format:** JSON
- **License:** No license; violates OpenAI ToS (user content)
- **Size:** n/a

**Quality Assessment (1–10):**

- Accuracy: 6
- Technical Quality: 6
- Diversity: 8
- Cleanliness: 5
- License Clarity: 1
- **Overall Score: 5**

- **Advantages:** Diverse conversational style.
- **Potential Problems:** No usage rights; OpenAI ToS prohibits using ChatGPT outputs to train models; provenance/PII risk.
- **Atlas Usage:** REJECT. Do not ingest under any category (ToS + copyright risk).
- **Recommendation:** ⛔ Reject

## X2 · tatsu-lab/alpaca (original)

- **Source:** Stanford
- **URL:** https://huggingface.co/datasets/tatsu-lab/alpaca
- **Category:** 01_foundation  (subcategory hint: instruction-following)
- **Tier:** Tier 4
- **Description:** 52k instruction pairs generated via text-davinci-003 from self-instruct seeds.
- **Format:** JSON
- **License:** CC-BY-NC-4.0 (non-commercial)
- **Size:** ~52k

**Quality Assessment (1–10):**

- Accuracy: 7
- Technical Quality: 7
- Diversity: 7
- Cleanliness: 7
- License Clarity: 3
- **Overall Score: 6**

- **Advantages:** Widely used baseline.
- **Potential Problems:** Non-commercial license -> blocks a potentially-commercial Atlas; also synthetic.
- **Atlas Usage:** REJECT for Atlas. Prefer yahma/alpaca-cleaned (CC-BY-4.0) if needed.
- **Recommendation:** ⛔ Reject


# 02 · Software Engineering

## S1 · princeton-nlp/SWE-bench

- **Source:** Princeton NLP
- **URL:** https://huggingface.co/datasets/princeton-nlp/SWE-bench
- **Category:** 02_software_engineering  (subcategory hint: debugging)
- **Tier:** Tier 3 (verified)
- **Description:** 2k+ real GitHub issues + PRs with gold patches and FAIL_TO_PASS/PASS_TO_PASS tests across 12 popular Python repos.
- **Format:** JSON
- **License:** MIT
- **Size:** ~22k instances (train/dev/test; ~4 GB)

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 10
- Diversity: 7
- Cleanliness: 9
- License Clarity: 10
- **Overall Score: 9**

- **Advantages:** Real-world, verified-by-tests code; MIT; gold solutions.
- **Potential Problems:** Python-heavy; requires test harness to validate; large.
- **Atlas Usage:** Flagship software-engineering eval + SFT (problem_statement -> patch). Tier 1-ish quality.
- **Recommendation:** ✅ Accept

## S2 · bigcode/the-stack-v2

- **Source:** BigCode
- **URL:** https://huggingface.co/datasets/bigcode/the-stack-v2
- **Category:** 02_software_engineering  (subcategory hint: programming)
- **Tier:** Tier 2/3
- **Description:** 3 TB+ permissively-licensed source code across 600+ languages with per-file detected licenses.
- **Format:** Parquet (code blobs)
- **License:** BigCode Open RAIL-M (use-restricted)
- **Size:** 3 TB+

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 9
- Diversity: 10
- Cleanliness: 8
- License Clarity: 5
- **Overall Score: 8**

- **Advantages:** Massive, license-tagged at file level; great for code pretraining/SFT.
- **Potential Problems:** RAIL-M imposes behavioral use restrictions (not a plain permissive license); needs license filtering.
- **Atlas Usage:** Code knowledge base. Filter to permissive file licenses; respect RAIL-M use clauses. Review, not bulk dump.
- **Recommendation:** 🟡 Review

## S3 · bigcode/starcoderdata

- **Source:** BigCode
- **URL:** https://huggingface.co/datasets/bigcode/starcoderdata
- **Category:** 02_software_engineering  (subcategory hint: programming)
- **Tier:** Tier 2/3
- **Description:** ~6.4 TB permissively-licensed code (variant of The Stack v1) used to train StarCoder.
- **Format:** JSONL (code)
- **License:** BigCode Open RAIL-M
- **Size:** 6.4 TB

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 9
- Diversity: 10
- Cleanliness: 7
- License Clarity: 5
- **Overall Score: 8**

- **Advantages:** Huge, language-diverse code corpus.
- **Potential Problems:** RAIL-M restrictions; very large; needs license filtering.
- **Atlas Usage:** Same policy as S2. Use filtered subset for code SFT only.
- **Recommendation:** 🟡 Review

## S4 · sahil2801/CodeAlpaca-20k

- **Source:** Sahil Chaudhary
- **URL:** https://huggingface.co/datasets/sahil2801/CodeAlpaca-20k
- **Category:** 02_software_engineering  (subcategory hint: algorithms)
- **Tier:** Tier 4 (cleaned)
- **Description:** 20k code-generation instruction pairs (self-instruct style on code).
- **Format:** JSON
- **License:** Apache-2.0
- **Size:** ~20k examples

**Quality Assessment (1–10):**

- Accuracy: 7
- Technical Quality: 8
- Diversity: 7
- Cleanliness: 8
- License Clarity: 10
- **Overall Score: 8**

- **Advantages:** Clean, permissive, code-focused instruction data.
- **Potential Problems:** Synthetic (Tier 4 upstream); English; repetition.
- **Atlas Usage:** Software-engineering instruction seed. Sample under synthetic cap.
- **Recommendation:** ✅ Accept

## S5 · StackExchange Code (Stack Overflow / Unix & Linux)

- **Source:** Stack Exchange
- **URL:** https://archive.org/details/stackexchange
- **Category:** 02_software_engineering  (subcategory hint: code-review)
- **Tier:** Tier 3
- **Description:** Structured Q&A dumps (Stack Overflow, Unix.SE, Super User) with accepted answers, votes, tags.
- **Format:** XML dump
- **License:** CC-BY-SA-4.0 (attribution + share-alike)
- **Size:** ~SO: 50M+ posts

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 9
- Diversity: 9
- Cleanliness: 7
- License Clarity: 8
- **Overall Score: 8**

- **Advantages:** Real, voted, expert-validated; huge code/systems coverage.
- **Potential Problems:** CC-BY-SA-4.0 is share-alike (must attribute + license derivatives similarly); PII/PII-in-code risk; needs parsing.
- **Atlas Usage:** Strong Tier-3 community source for SW + systems. Attribute per post; filter low-score; strip PII.
- **Recommendation:** 🟡 Review

## S6 · allenai/tulu-3-sft-mixture

- **Source:** Allen AI
- **URL:** https://huggingface.co/datasets/allenai/tulu-3-sft-mixture
- **Category:** 02_software_engineering  (subcategory hint: open-source)
- **Tier:** Tier 2
- **Description:** Curated ~1M-example SFT mixture (incl. code, math, science, general) with cleaning + attribution metadata.
- **Format:** JSON
- **License:** ODC-BY
- **Size:** ~1M examples

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 8
- Diversity: 9
- Cleanliness: 9
- License Clarity: 9
- **Overall Score: 9**

- **Advantages:** Heavily curated, documented provenance, ODC-BY; includes code + science.
- **Potential Problems:** Mixture includes some NC/use-restricted upstreams -> must check per-subset licenses.
- **Atlas Usage:** Reference mixture + sampled subsets for SW/ML/science. Audit sub-licenses before ingest.
- **Recommendation:** ✅ Accept

## S7 · WizardCoder / OpenCodeInstruct-style code data

- **Source:** WizardLM / OpenCoder
- **URL:** https://huggingface.co/datasets/WizardLMTeam/WizardCoder
- **Category:** 02_software_engineering  (subcategory hint: software-architecture)
- **Tier:** Tier 4 (cleaned)
- **Description:** Evol-Instruct code datasets (Code-Evol-Instruct). High-difficulty code instruction pairs.
- **Format:** JSON
- **License:** Apache-2.0 (verify; repo 404 at check)
- **Size:** ~250k examples

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 9
- Diversity: 8
- Cleanliness: 7
- License Clarity: 6
- **Overall Score: 8**

- **Advantages:** Hard, diverse code tasks; strong empirical results.
- **Potential Problems:** Original WizardLM repo returned 404 at verification; license/availability must be re-confirmed.
- **Atlas Usage:** High-value code SFT if license confirmed permissive. Hold for re-verification.
- **Recommendation:** 🟡 Review

## S8 · nampdn-ai/tinycoder

- **Source:** Nampdn
- **URL:** https://huggingface.co/datasets/nampdn-ai/tinycoder
- **Category:** 02_software_engineering  (subcategory hint: programming)
- **Tier:** Tier 4
- **Description:** Compact code-instruction subset (smaller, curated) for efficient code SFT.
- **Format:** JSON
- **License:** Apache-2.0 (gated; verify)
- **Size:** gated

**Quality Assessment (1–10):**

- Accuracy: 7
- Technical Quality: 8
- Diversity: 6
- Cleanliness: 8
- License Clarity: 6
- **Overall Score: 7**

- **Advantages:** Compact; good for small-model code alignment.
- **Potential Problems:** Access-gated (HF 401); license unverified at check.
- **Atlas Usage:** Optional compact code seed after un-gating + license check.
- **Recommendation:** 🟡 Review


# 03 · System Engineering

## Y1 · Linux man-pages + kernel documentation

- **Source:** The Linux Man-pages Project / kernel.org
- **URL:** https://www.kernel.org/doc/html/latest/
- **Category:** 03_system_engineering  (subcategory hint: linux)
- **Tier:** Tier 1
- **Description:** Official Linux manual pages and kernel documentation (admin guides, APIs).
- **Format:** reST / HTML / roff
- **License:** Public domain / MIT-style (man-pages); GFDL for some kernel docs
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 10
- Diversity: 7
- Cleanliness: 9
- License Clarity: 9
- **Overall Score: 9**

- **Advantages:** Authoritative Tier-1 reference; no licensing ambiguity for man-pages.
- **Potential Problems:** Reference text, not instruction format; needs conversion to Q&A/instruction.
- **Atlas Usage:** Tier-1 gold source for linux subcategory. Convert docs->instruction via templates (synthetic-from-doc capped).
- **Recommendation:** ✅ Accept

## Y2 · Kubernetes official documentation

- **Source:** CNCF / Kubernetes
- **URL:** https://kubernetes.io/docs/
- **Category:** 03_system_engineering  (subcategory hint: kubernetes)
- **Tier:** Tier 1
- **Description:** Official Kubernetes concepts, tasks, tutorials, reference.
- **Format:** Markdown / HTML
- **License:** CC-BY-4.0 (docs repo)
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 10
- Diversity: 7
- Cleanliness: 9
- License Clarity: 10
- **Overall Score: 9**

- **Advantages:** Tier-1 authoritative; clean CC-BY-4.0.
- **Potential Problems:** Needs instruction conversion; version churn (pin versions).
- **Atlas Usage:** Tier-1 source for kubernetes/docker subcategories. Convert+verify, pin doc version.
- **Recommendation:** ✅ Accept

## Y3 · Docker official documentation

- **Source:** Docker Inc.
- **URL:** https://docs.docker.com/
- **Category:** 03_system_engineering  (subcategory hint: docker)
- **Tier:** Tier 1
- **Description:** Official Docker engine, compose, swarm, reference docs.
- **Format:** Markdown / HTML
- **License:** Apache-2.0 (docs repo)
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 10
- Diversity: 6
- Cleanliness: 9
- License Clarity: 10
- **Overall Score: 9**

- **Advantages:** Tier-1; Apache-2.0 docs repo.
- **Potential Problems:** Needs conversion; version pinning.
- **Atlas Usage:** Tier-1 for docker subcategory.
- **Recommendation:** ✅ Accept

## Y4 · Arch Wiki

- **Source:** Arch Linux
- **URL:** https://wiki.archlinux.org/
- **Category:** 03_system_engineering  (subcategory hint: linux)
- **Tier:** Tier 1/2
- **Description:** Community-maintained, rigorously-sourced Linux systems wiki (install, networking, boot, hardening).
- **Format:** MediaWiki
- **License:** CC-BY-SA-4.0 (some GFDL)
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 9
- Diversity: 8
- Cleanliness: 9
- License Clarity: 8
- **Overall Score: 9**

- **Advantages:** Exceptional practical systems depth; well-sourced.
- **Potential Problems:** CC-BY-SA-4.0 share-alike + attribution; wiki tone needs restructuring.
- **Atlas Usage:** Tier-1/2 systems knowledge (linux, networking, virtualization). Attribute; convert to instruction.
- **Recommendation:** ✅ Accept

## Y5 · StackExchange Systems (ServerFault, Unix.SE, Super User, Network Engineering)

- **Source:** Stack Exchange
- **URL:** https://archive.org/details/stackexchange
- **Category:** 03_system_engineering  (subcategory hint: networking)
- **Tier:** Tier 3
- **Description:** Voted Q&A for ops/troubleshooting/networking.
- **Format:** XML dump
- **License:** CC-BY-SA-4.0
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 9
- Diversity: 9
- Cleanliness: 7
- License Clarity: 8
- **Overall Score: 8**

- **Advantages:** Real troubleshooting; expert-voted; broad systems coverage.
- **Potential Problems:** Share-alike + attribution; PII; needs parsing + quality filter.
- **Atlas Usage:** Tier-3 community source for system troubleshooting. Attribute; filter score>=5; strip PII.
- **Recommendation:** 🟡 Review

## Y6 · Red Hat Enterprise Linux / Fedora Documentation

- **Source:** Red Hat
- **URL:** https://docs.redhat.com/
- **Category:** 03_system_engineering  (subcategory hint: performance-tuning)
- **Tier:** Tier 1/2
- **Description:** Enterprise-grade Linux administration, networking, security guides.
- **Format:** HTML / ASCIIDOC
- **License:** CC-BY-SA-4.0 (Red Hat Customer Portal docs)
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 10
- Diversity: 7
- Cleanliness: 9
- License Clarity: 9
- **Overall Score: 9**

- **Advantages:** High-quality enterprise systems content; clear CC-BY-SA-4.0.
- **Potential Problems:** Some portal content is subscriber-only -> must use only CC-BY-SA published docs; version pin.
- **Atlas Usage:** Tier-1/2 systems administration. Use only openly-licensed docs; convert+verify.
- **Recommendation:** ✅ Accept

## Y7 · Wikimedia (sysadmin / networking articles)

- **Source:** Wikimedia Foundation
- **URL:** https://www.wikipedia.org/
- **Category:** 03_system_engineering  (subcategory hint: networking)
- **Tier:** Tier 2
- **Description:** Encyclopedic articles on networking protocols, OS concepts, virtualization.
- **Format:** Wikitext / dumps
- **License:** CC-BY-SA-3.0
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 8
- Diversity: 8
- Cleanliness: 7
- License Clarity: 8
- **Overall Score: 8**

- **Advantages:** Broad conceptual coverage; well-known license.
- **Potential Problems:** Encyclopedic, not task-oriented; share-alike; varying depth.
- **Atlas Usage:** Background knowledge for networking/virtualization subcategories. Attribute; convert to Q&A.
- **Recommendation:** 🟡 Review

## Y8 · Cisco / vendor proprietary networking docs (e.g. Cisco Press)

- **Source:** Cisco / vendors
- **URL:** https://www.cisco.com/
- **Category:** 03_system_engineering  (subcategory hint: networking)
- **Tier:** Tier 1 (reference only)
- **Description:** Vendor certification/configuration guides.
- **Format:** PDF / HTML
- **License:** Proprietary (all rights reserved)
- **Size:** n/a

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 10
- Diversity: 7
- Cleanliness: 9
- License Clarity: 1
- **Overall Score: 7**

- **Advantages:** High technical quality.
- **Potential Problems:** Proprietary; no redistribution/derivative rights -> cannot ingest into Atlas.
- **Atlas Usage:** REJECT for dataset ingestion. Use only as out-of-band human reference, never as source text.
- **Recommendation:** ⛔ Reject


# 04 · AI & Machine Learning

## M1 · arXiv academic corpus (cs.LG, cs.CL, cs.AI, stat.ML)

- **Source:** Cornell / arXiv
- **URL:** https://arxiv.org/
- **Category:** 04_ai_machine_learning  (subcategory hint: transformers)
- **Tier:** Tier 1
- **Description:** Preprint papers + abstracts across ML/AI. Source of verified technical reference and reasoning.
- **Format:** TeX / PDF / API
- **License:** arXiv.org perpetual non-exclusive license (preprint; no copyright transfer)
- **Size:** huge

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 10
- Diversity: 9
- Cleanliness: 8
- License Clarity: 7
- **Overall Score: 9**

- **Advantages:** Tier-1 academic; cutting-edge; broad.
- **Potential Problems:** Preprints may be un-peer-reviewed; abstract/PDF not instruction format; some under embargo.
- **Atlas Usage:** Tier-1 knowledge base for transformers/llm/rag/mlops. Convert abstracts+key sections->instruction (synthetic-from-doc capped).
- **Recommendation:** ✅ Accept

## M2 · Open-Platypus

- **Source:** MosaicML / IBM
- **URL:** https://huggingface.co/datasets/garage-bAInd/Open-Platypus
- **Category:** 04_ai_machine_learning  (subcategory hint: machine-learning)
- **Tier:** Tier 2
- **Description:** 25k expert-curated (human+GPT-4) instruction pairs focused on science, math, and coding.
- **Format:** JSON
- **License:** Apache-2.0
- **Size:** ~25k examples

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 9
- Diversity: 8
- Cleanliness: 9
- License Clarity: 10
- **Overall Score: 9**

- **Advantages:** Curated, science-leaning; permissive; deduplicated.
- **Potential Problems:** Science/math heavy; some GPT-4 generated (Tier 4) content.
- **Atlas Usage:** ML/science instruction seed. Sample under synthetic cap; verify factual claims.
- **Recommendation:** ✅ Accept

## M3 · allenai/tulu-3-sft-mixture

- **Source:** Allen AI
- **URL:** https://huggingface.co/datasets/allenai/tulu-3-sft-mixture
- **Category:** 04_ai_machine_learning  (subcategory hint: llm)
- **Tier:** Tier 2
- **Description:** (see S6) includes ML/LLM/agent instruction subsets with provenance.
- **Format:** JSON
- **License:** ODC-BY
- **Size:** ~1M (subset ML)

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 8
- Diversity: 9
- Cleanliness: 9
- License Clarity: 9
- **Overall Score: 9**

- **Advantages:** Documented provenance; ODC-BY; ML-rich.
- **Potential Problems:** Check per-subset licenses (some upstream restricted).
- **Atlas Usage:** ML/LLM/agent instruction sampling. Audit sub-licenses.
- **Recommendation:** ✅ Accept

## M4 · EleutherAI/the_pile

- **Source:** EleutherAI
- **URL:** https://huggingface.co/datasets/EleutherAI/pile
- **Category:** 04_ai_machine_learning  (subcategory hint: deep-learning)
- **Tier:** Tier 2
- **Description:** 800GB diverse text (incl. arXiv, PubMed, FreeLaw, Stack, GitHub) for pretraining.
- **Format:** JSONL / mmap
- **License:** Mixed (per-subset; many ODC-BY/CC; some restricted)
- **Size:** 800 GB

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 8
- Diversity: 10
- Cleanliness: 7
- License Clarity: 4
- **Overall Score: 7**

- **Advantages:** Diverse, high-signal academic+code; great pretraining complement.
- **Potential Problems:** Mixed licenses per subset -> must subset by license; some subsets restricted (e.g. requiring exclusion).
- **Atlas Usage:** Pretraining/knowledge complement. Subset to permissive components only; exclude restricted subsets.
- **Recommendation:** 🟡 Review

## M5 · lmsys/lmsys-chat-1m

- **Source:** LMSYS
- **URL:** https://huggingface.co/datasets/lmsys/lmsys-chat-1m
- **Category:** 04_ai_machine_learning  (subcategory hint: ai-agents)
- **Tier:** Tier 3
- **Description:** 1M real user-LLM conversations (diverse models). Rich for agent/LLM behavior modeling.
- **Format:** JSON
- **License:** Custom / research-only (verify)
- **Size:** ~1M conversations

**Quality Assessment (1–10):**

- Accuracy: 7
- Technical Quality: 7
- Diversity: 9
- Cleanliness: 7
- License Clarity: 4
- **Overall Score: 7**

- **Advantages:** Massive real interaction corpus; great for LLM/agent behavior.
- **Potential Problems:** License None on HF -> likely research-only / custom terms; PII; ToS of underlying models.
- **Atlas Usage:** Research reference for ai-agents/llm behavior only if license cleared. Otherwise Reject.
- **Recommendation:** 🟡 Review

## M6 · HuggingFaceFW/fineweb

- **Source:** HuggingFace
- **URL:** https://huggingface.co/datasets/HuggingFaceFW/fineweb
- **Category:** 04_ai_machine_learning  (subcategory hint: mlops)
- **Tier:** Tier 2
- **Description:** 15T tokens of cleaned CommonCrawl (classifier-filtered) for pretraining.
- **Format:** Parquet
- **License:** ODC-BY
- **Size:** 15T tokens

**Quality Assessment (1–10):**

- Accuracy: 7
- Technical Quality: 7
- Diversity: 10
- Cleanliness: 9
- License Clarity: 9
- **Overall Score: 8**

- **Advantages:** Huge, cleaned, ODC-BY; ideal pretraining knowledge base.
- **Potential Problems:** Web-derived noise; not instruction format; needs downstream task filtering.
- **Atlas Usage:** Pretraining/knowledge complement for all categories. Not instruction data; use for continued-pretraining only.
- **Recommendation:** ✅ Accept


# 05 · Hardware Engineering

## H1 · Wikipedia hardware articles (CPU/GPU/firmware/embedded)

- **Source:** Wikimedia
- **URL:** https://www.wikipedia.org/
- **Category:** 05_hardware_engineering  (subcategory hint: cpu)
- **Tier:** Tier 2
- **Description:** Encyclopedic, sourced articles on processors, GPUs, firmware, embedded systems.
- **Format:** Wikitext / dumps
- **License:** CC-BY-SA-3.0
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 8
- Diversity: 8
- Cleanliness: 7
- License Clarity: 8
- **Overall Score: 8**

- **Advantages:** Broad conceptual hardware coverage; known license.
- **Potential Problems:** Not task-oriented; share-alike; depth varies; dated on cutting-edge silicon.
- **Atlas Usage:** Background knowledge for cpu/gpu/firmware/embedded-systems. Attribute; convert to Q&A.
- **Recommendation:** 🟡 Review

## H2 · arXiv hardware/arch papers (eess.AR, cs.AR, cs.CR)

- **Source:** Cornell / arXiv
- **URL:** https://arxiv.org/
- **Category:** 05_hardware_engineering  (subcategory hint: validation)
- **Tier:** Tier 1
- **Description:** Preprints on computer architecture, VLSI, firmware, embedded, benchmarking.
- **Format:** TeX / PDF
- **License:** arXiv non-exclusive license
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 10
- Diversity: 7
- Cleanliness: 8
- License Clarity: 7
- **Overall Score: 8**

- **Advantages:** Tier-1 academic depth on architecture/validation.
- **Potential Problems:** Preprints; not instruction format; niche.
- **Atlas Usage:** Tier-1 knowledge for validation/benchmarking/embedded-systems. Convert key sections->instruction (capped).
- **Recommendation:** ✅ Accept

## H3 · WikiChip / SemiWiki-style semiconductor wikis

- **Source:** WikiChip / SemiWiki
- **URL:** https://en.wikichip.org/
- **Category:** 05_hardware_engineering  (subcategory hint: gpu)
- **Tier:** Tier 2
- **Description:** Detailed microarchitecture, ISA, and process-node reference articles.
- **Format:** MediaWiki
- **License:** CC-BY-SA-4.0 (verify)
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 9
- Diversity: 7
- Cleanliness: 8
- License Clarity: 7
- **Overall Score: 8**

- **Advantages:** Deep microarchitecture detail; wiki format.
- **Potential Problems:** License must be re-verified (WikiChip terms vary); share-alike.
- **Atlas Usage:** Reference for cpu/gpu microarchitecture. Verify license; convert+attribute.
- **Recommendation:** 🟡 Review

## H4 · StackExchange Electronics + Electrical Engineering

- **Source:** Stack Exchange
- **URL:** https://archive.org/details/stackexchange
- **Category:** 05_hardware_engineering  (subcategory hint: embedded-systems)
- **Tier:** Tier 3
- **Description:** Voted Q&A on circuits, firmware, embedded, validation, benchmarking.
- **Format:** XML dump
- **License:** CC-BY-SA-4.0
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 9
- Diversity: 8
- Cleanliness: 7
- License Clarity: 8
- **Overall Score: 8**

- **Advantages:** Real hardware troubleshooting; expert-voted.
- **Potential Problems:** Share-alike + attribution; PII; needs parsing.
- **Atlas Usage:** Tier-3 community source for embedded-systems/firmware/validation. Attribute; filter; strip PII.
- **Recommendation:** 🟡 Review

## H5 · Manufacturer datasheets / app notes (Intel, AMD, ARM, TI)

- **Source:** Vendors
- **URL:** https://www.ti.com/ / arm.com
- **Category:** 05_hardware_engineering  (subcategory hint: bios)
- **Tier:** Tier 1 (reference only)
- **Description:** Authoritative silicon datasheets, reference manuals, errata.
- **Format:** PDF
- **License:** Proprietary (all rights reserved)
- **Size:** n/a

**Quality Assessment (1–10):**

- Accuracy: 10
- Technical Quality: 10
- Diversity: 7
- Cleanliness: 10
- License Clarity: 1
- **Overall Score: 8**

- **Advantages:** Gold-standard technical accuracy.
- **Potential Problems:** Proprietary; redistribution/derivative prohibited -> cannot ingest.
- **Atlas Usage:** REJECT for ingestion. Use only as human out-of-band reference; never as source text.
- **Recommendation:** ⛔ Reject

## H6 · Synthetic-from-docs (hardware)

- **Source:** Atlas internal (Tier 4)
- **URL:** raw/generated/
- **Category:** 05_hardware_engineering  (subcategory hint: benchmarking)
- **Tier:** Tier 4
- **Description:** Atlas-generated instruction pairs derived strictly from H1/H2/H3 licensed text (doc2qa).
- **Format:** JSONL
- **License:** CC-BY-4.0 (generated; must human-review)
- **Size:** TBD

**Quality Assessment (1–10):**

- Accuracy: 6
- Technical Quality: 8
- Diversity: 7
- Cleanliness: 8
- License Clarity: 7
- **Overall Score: 7**

- **Advantages:** Fills the sparse hardware category using only licensed source text.
- **Potential Problems:** Synthetic (Tier 4); capped by policy; must pass clean+human review before curated/.
- **Atlas Usage:** Bridge source until richer licensed hardware corpora found. Cap share; human-verify every record.
- **Recommendation:** 🟡 Review
- **Notes:** Allowed only as a CAP (e.g. <=15% of hardware category) and only from licensed docs. Never sole source.


# 06 · Science & Engineering

## C1 · openai/gsm8k

- **Source:** OpenAI
- **URL:** https://huggingface.co/datasets/openai/gsm8k
- **Category:** 06_science_engineering  (subcategory hint: mathematics)
- **Tier:** Tier 2
- **Description:** 8.5k grade-school math word problems with step-by-step reasoning solutions.
- **Format:** JSON
- **License:** MIT
- **Size:** ~8.5k examples

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 10
- Diversity: 6
- Cleanliness: 9
- License Clarity: 10
- **Overall Score: 9**

- **Advantages:** Gold-standard chain-of-thought math; MIT.
- **Potential Problems:** Narrow grade-school scope; English.
- **Atlas Usage:** Flagship mathematics reasoning SFT + eval. Also split into held-out test set.
- **Recommendation:** ✅ Accept

## C2 · cais/mmlu

- **Source:** UC Berkeley (Hendrycks)
- **URL:** https://huggingface.co/datasets/cais/mmlu
- **Category:** 06_science_engineering  (subcategory hint: physics)
- **Tier:** Tier 2
- **Description:** 57-subject multiple-choice knowledge/reasoning benchmark (14k Qs).
- **Format:** JSON
- **License:** MIT
- **Size:** ~14k examples

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 9
- Diversity: 9
- Cleanliness: 9
- License Clarity: 10
- **Overall Score: 9**

- **Advantages:** Broad, well-known; MIT; doubles as eval.
- **Potential Problems:** MC format; needs conversion to open Q&A for SFT.
- **Atlas Usage:** Eval benchmark + knowledge SFT (convert to open-form). Hold out as test set.
- **Recommendation:** ✅ Accept

## C3 · Hendrycks MATH (competition_math)

- **Source:** UC Berkeley
- **URL:** https://huggingface.co/datasets/hendrycks/competition_math
- **Category:** 06_science_engineering  (subcategory hint: mathematics)
- **Tier:** Tier 2
- **Description:** 12.5k competition mathematics problems with rigorous step-by-step proofs.
- **Format:** JSON
- **License:** MIT
- **Size:** ~12.5k examples

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 10
- Diversity: 7
- Cleanliness: 9
- License Clarity: 10
- **Overall Score: 9**

- **Advantages:** Hard math CoT; MIT; strong for reasoning.
- **Potential Problems:** Competition-level (hard); English.
- **Atlas Usage:** High-difficulty mathematics reasoning SFT. Use for hard-tier sampling.
- **Recommendation:** ✅ Accept

## C4 · Ai-MO/OpenMathInstruct-2

- **Source:** AI-MO
- **URL:** https://huggingface.co/datasets/Ai-MO/OpenMathInstruct-2
- **Category:** 06_science_engineering  (subcategory hint: mathematics)
- **Tier:** Tier 4 (verified)
- **Description:** 14M+(math) instruction pairs generated from GSM8K/MATH with verified solutions.
- **Format:** JSON
- **License:** MIT (gated; verify)
- **Size:** gated (~large)

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 9
- Diversity: 8
- Cleanliness: 8
- License Clarity: 6
- **Overall Score: 8**

- **Advantages:** Huge, solution-verified math instruction.
- **Potential Problems:** Access-gated (HF 401); synthetic (Tier 4) but solution-checked.
- **Atlas Usage:** Math reasoning scale-up after un-gating. Sample; keep under synthetic cap.
- **Recommendation:** 🟡 Review

## C5 · open-web-math/open-web-math

- **Source:** OpenWebMath
- **URL:** https://huggingface.co/datasets/open-web-math/open-web-math
- **Category:** 06_science_engineering  (subcategory hint: mathematics)
- **Tier:** Tier 2
- **Description:** 6.3M pages of high-quality web math (LaTeX-rich) filtered for educational value.
- **Format:** JSON
- **License:** ODC-BY
- **Size:** ~6.3M pages

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 8
- Diversity: 9
- Cleanliness: 9
- License Clarity: 9
- **Overall Score: 9**

- **Advantages:** Large, math-dense, ODC-BY; great pretraining complement.
- **Potential Problems:** Web-derived; needs instruction conversion; noise.
- **Atlas Usage:** Math/science pretraining complement + doc2qa source. Convert+verify.
- **Recommendation:** ✅ Accept

## C6 · allenai/sciq

- **Source:** Allen AI
- **URL:** https://huggingface.co/datasets/allenai/sciq
- **Category:** 06_science_engineering  (subcategory hint: engineering-concepts)
- **Tier:** Tier 2
- **Description:** 11k crowdsourced science exam Q&A with support passages (physics, chem, bio).
- **Format:** JSON
- **License:** CC-BY-4.0
- **Size:** ~11k examples

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 9
- Diversity: 7
- Cleanliness: 9
- License Clarity: 10
- **Overall Score: 9**

- **Advantages:** Human-written science Q&A; CC-BY-4.0.
- **Potential Problems:** Narrow exam style; English.
- **Atlas Usage:** Science knowledge SFT for physics/engineering-concepts.
- **Recommendation:** ✅ Accept

## C7 · arXiv physics / engineering preprints

- **Source:** Cornell / arXiv
- **URL:** https://arxiv.org/
- **Category:** 06_science_engineering  (subcategory hint: electronics)
- **Tier:** Tier 1
- **Description:** Preprints in physics, electronics, engineering fundamentals.
- **Format:** TeX / PDF
- **License:** arXiv non-exclusive license
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 9
- Technical Quality: 10
- Diversity: 8
- Cleanliness: 8
- License Clarity: 7
- **Overall Score: 8**

- **Advantages:** Tier-1 academic; broad science depth.
- **Potential Problems:** Preprints; not instruction; needs conversion.
- **Atlas Usage:** Tier-1 knowledge for physics/electronics. Convert+verify (capped synthetic-from-doc).
- **Recommendation:** ✅ Accept


# 07 · Business Knowledge

## B1 · gbharti/finance-alpaca

- **Source:** Gaurav Bhatt
- **URL:** https://huggingface.co/datasets/gbharti/finance-alpaca
- **Category:** 07_business_knowledge  (subcategory hint: finance)
- **Tier:** Tier 4 (cleaned)
- **Description:** 70k+ finance instruction pairs generated from SEC filings / fiqa via Alpaca template.
- **Format:** JSON
- **License:** MIT
- **Size:** ~70k examples

**Quality Assessment (1–10):**

- Accuracy: 7
- Technical Quality: 8
- Diversity: 7
- Cleanliness: 8
- License Clarity: 10
- **Overall Score: 8**

- **Advantages:** Domain-specific finance; MIT; fills business gap.
- **Potential Problems:** Synthetic from filings (Tier 4); some factual drift; US-centric.
- **Atlas Usage:** Finance subcategory seed. Sample under synthetic cap; verify numeric claims.
- **Recommendation:** ✅ Accept

## B2 · Wikipedia business / economics / strategy articles

- **Source:** Wikimedia
- **URL:** https://www.wikipedia.org/
- **Category:** 07_business_knowledge  (subcategory hint: strategy)
- **Tier:** Tier 2
- **Description:** Encyclopedic articles on finance, management, strategy, entrepreneurship.
- **Format:** Wikitext / dumps
- **License:** CC-BY-SA-3.0
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 8
- Diversity: 8
- Cleanliness: 7
- License Clarity: 8
- **Overall Score: 8**

- **Advantages:** Broad business concepts; known license.
- **Potential Problems:** Not task-oriented; share-alike; varies in depth.
- **Atlas Usage:** Background knowledge for management/strategy/entrepreneurship. Attribute; convert to Q&A.
- **Recommendation:** 🟡 Review

## B3 · StackExchange Finance/Economics/Personal Finance

- **Source:** Stack Exchange
- **URL:** https://archive.org/details/stackexchange
- **Category:** 07_business_knowledge  (subcategory hint: finance)
- **Tier:** Tier 3
- **Description:** Voted Q&A on quantitative finance, economics, personal finance.
- **Format:** XML dump
- **License:** CC-BY-SA-4.0
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 9
- Diversity: 8
- Cleanliness: 7
- License Clarity: 8
- **Overall Score: 8**

- **Advantages:** Real, expert-voted business/finance Q&A.
- **Potential Problems:** Share-alike + attribution; PII; needs parsing.
- **Atlas Usage:** Tier-3 business source for finance/management. Attribute; filter; strip PII.
- **Recommendation:** 🟡 Review

## B4 · Synthetic-from-cases (business)

- **Source:** Atlas internal (Tier 4)
- **URL:** raw/generated/
- **Category:** 07_business_knowledge  (subcategory hint: entrepreneurship)
- **Tier:** Tier 4
- **Description:** Atlas-generated business cases/QA from B1/B2 licensed text.
- **Format:** JSONL
- **License:** CC-BY-4.0 (must human-review)
- **Size:** TBD

**Quality Assessment (1–10):**

- Accuracy: 6
- Technical Quality: 8
- Diversity: 7
- Cleanliness: 8
- License Clarity: 7
- **Overall Score: 7**

- **Advantages:** Bridges sparse business category using licensed sources.
- **Potential Problems:** Synthetic (Tier 4); capped; needs human review.
- **Atlas Usage:** Cap share; human-verify. Never sole source for business.
- **Recommendation:** 🟡 Review
- **Notes:** Cap <=15% of business category; only from licensed docs.


# 08 · Creative Knowledge

## R1 · Project Gutenberg

- **Source:** Project Gutenberg
- **URL:** https://www.gutenberg.org/
- **Category:** 08_creative_knowledge  (subcategory hint: writing)
- **Tier:** Tier 1
- **Description:** 70k+ public-domain literary works (prose, poetry, essays) for style/creative writing.
- **Format:** Plain text
- **License:** Public Domain (US)
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 8
- Diversity: 9
- Cleanliness: 9
- License Clarity: 10
- **Overall Score: 9**

- **Advantages:** Genuinely public domain; rich creative style; zero license risk.
- **Potential Problems:** Older language/style; not instruction format; needs creative-task framing.
- **Atlas Usage:** Tier-1 creative writing style source. Frame as writing/rewrite/summarize tasks (not copy).
- **Recommendation:** ✅ Accept

## R2 · Wikipedia creative-writing / rhetoric / design articles

- **Source:** Wikimedia
- **URL:** https://www.wikipedia.org/
- **Category:** 08_creative_knowledge  (subcategory hint: design)
- **Tier:** Tier 2
- **Description:** Articles on writing craft, rhetoric, communication, design principles.
- **Format:** Wikitext / dumps
- **License:** CC-BY-SA-3.0
- **Size:** large

**Quality Assessment (1–10):**

- Accuracy: 8
- Technical Quality: 8
- Diversity: 7
- Cleanliness: 7
- License Clarity: 8
- **Overall Score: 8**

- **Advantages:** Conceptual writing/design knowledge; known license.
- **Potential Problems:** Share-alike; encyclopedic tone.
- **Atlas Usage:** Background for writing/design subcategories. Attribute; convert to Q&A.
- **Recommendation:** 🟡 Review

## R3 · Synthetic-from-style (creative)

- **Source:** Atlas internal (Tier 4)
- **URL:** raw/generated/
- **Category:** 08_creative_knowledge  (subcategory hint: creativity)
- **Tier:** Tier 4
- **Description:** Atlas-generated creative tasks (story, poetry, copy) from R1/R2 licensed text.
- **Format:** JSONL
- **License:** CC-BY-4.0 (must human-review)
- **Size:** TBD

**Quality Assessment (1–10):**

- Accuracy: 6
- Technical Quality: 8
- Diversity: 8
- Cleanliness: 8
- License Clarity: 7
- **Overall Score: 7**

- **Advantages:** Fills creative category with on-license style grounding.
- **Potential Problems:** Synthetic (Tier 4); capped; needs human review for quality.
- **Atlas Usage:** Cap share; human-verify. Creative category is candidate-poor -> lean on R1 + capped synthetic.
- **Recommendation:** 🟡 Review
- **Notes:** Cap <=20% of creative category; grounded only in PD/GPL-style licensed text.

## R4 · Reddit WritingPrompts / r/writing scrapes

- **Source:** Reddit
- **URL:** https://www.reddit.com/r/WritingPrompts/
- **Category:** 08_creative_knowledge  (subcategory hint: storytelling)
- **Tier:** Tier 3 (illegal to ingest)
- **Description:** User story prompts + responses.
- **Format:** JSON
- **License:** Reddit User Agreement (no free license to content)
- **Size:** n/a

**Quality Assessment (1–10):**

- Accuracy: 7
- Technical Quality: 7
- Diversity: 8
- Cleanliness: 6
- License Clarity: 1
- **Overall Score: 6**

- **Advantages:** Creative prompts are engaging.
- **Potential Problems:** Reddit ToS prohibits commercial redistribution/scraping for ML without license; user content not licensed to us.
- **Atlas Usage:** REJECT. Reddit content is not licensed for dataset use; legal risk high.
- **Recommendation:** ⛔ Reject
