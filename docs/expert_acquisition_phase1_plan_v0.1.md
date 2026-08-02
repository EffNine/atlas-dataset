# Atlas Expert Acquisition Phase 1 Plan v0.1

## Scope

This plan covers acquisition analysis only for Priority 1 expert domains:
- Software Engineering
- AI/ML
- Mathematics

It does not cover System Engineering, Science, Creative, Business, or Hardware in this phase.

## Expert Tier Mix Target

| Tier | Target Share | Role in 300M Specialist Training |
|------|--------------|----------------------------------|
| E1 | 60% | Stable professional knowledge and authoritative references |
| E2 | 30% | Advanced reasoning and problem solving |
| E3 | 10% | Frontier signal; sparse but high-value |

## Phase 1 Targets

| Domain | Phase 1 Target | Notes |
|--------|----------------|-------|
| Software Engineering | 200,000 | Includes debugging, code review, system design, and issue-to-patch expertise |
| AI/ML | 150,000 | Includes paper expertise, textbook derivations, and experiment analysis |
| Mathematics | 150,000 | Includes competition math, university reasoning, and proof-style data |
| **Total** | **500,000** | Seed corpus for Atlas Expert v1 |

## General Pipeline Contract

All expert data must pass the same canonical pipeline:

Raw Expert Data -> License Check -> Quality Filter -> Difficulty Scoring -> Atlas Expert Layer -> Training Dataset

No random dataset is recommended without:
1. confirmed license status,
2. defined transformation,
3. explicit quality validation method.

---

## Software Engineering

### Why this domain first

Software Engineering is the closest fit to the intended specialist behavior of Novexa/Gumi. It provides executable, verifiable, and reviewable expert signals: issue statements, patches, reviews, and design reasoning.

### Phase 1 Sources

#### 1. SWE-bench verified
- **Source:** princeton-nlp/SWE-bench
- **Expert tier:** E2
- **License:** MIT
- **Expected value:** Gold issue-to-patch pairs with verified FAIL_TO_PASS and PASS_TO_PASS outcomes. Strong supervised signal for debugging and repair.
- **Acquisition risk:** Low. License is permissive. Dataset is already public and widely used.
- **Transformation required:** Convert each instance into expert record format with problem, repo context, and patch/solution. Keep verified instances only.
- **Quality validation method:** Use official SWE-bench verification predicates. Require passing patch and test evidence. Reject unresolved or broken instances.

#### 2. StackExchange Code XML dumps
- **Source:** Stack Exchange / archive.org
- **Expert tier:** E1
- **License:** CC-BY-SA-4.0
- **Expected value:** Large-scale community-voted Q&A across programming, debugging, and tool usage. Useful for broad E1 coverage.
- **Acquisition risk:** Medium. Requires attribution, PII stripping, and share-alike tracking. Quality varies by tag and score threshold.
- **Transformation required:** Parse XML dumps, filter by score/acceptance, extract highest-quality answers, convert to expert qa/instruction format.
- **Quality validation method:** Keep accepted answers with score >= threshold. Strip PII. Attribute per record. Spot-check for stale or insecure advice.

#### 3. GitHub issue-to-solution pairs
- **Source:** [HUMAN MUST SUPPLY]
- **Expert tier:** E2
- **License:** [HUMAN MUST SUPPLY]
- **Expected value:** Real developer workflow data: issue -> discussion -> PR -> merge. High realism for assistant-style training.
- **Acquisition risk:** High. License and redistribution rights are repo-specific. GitHub Terms of Service and contributor consent must be checked.
- **Transformation required:** Extract issue title/body, linked PR, final patch summary, and resolution outcome. Convert to problem/solution format. Anonymize contributor metadata if required.
- **Quality validation method:** Require merged PR or maintainer-verified resolution. Filter by repo health and signal-to-noise ratio. Exclude security-sensitive private repos.

#### 4. Code review expert examples
- **Source:** [HUMAN MUST SUPPLY]
- **Expert tier:** E2
- **License:** [HUMAN MUST SUPPLY]
- **Expected value:** Review comments and revised code teach critique, style, correctness, and security reasoning.
- **Acquisition risk:** High. Public review datasets are limited. Many repos do not allow redistribution of review conversations.
- **Transformation required:** Pair review feedback with before/after code changes. Normalize to instruction/response format. Preserve reviewer rationale.
- **Quality validation method:** Require review threads with actionable feedback and accepted revisions. Prefer expert-maintained projects or public review exports with explicit redistribution permission.

#### 5. System design Q&A
- **Source:** [HUMAN MUST SUPPLY]
- **Expert tier:** E1
- **License:** [HUMAN MUST SUPPLY]
- **Expected value:** Architecture tradeoffs, scalability reasoning, and infrastructure decisions. Strengthens design-oriented responses.
- **Acquisition risk:** Medium. Curated design Q&A sources are smaller and may be mixed quality.
- **Transformation required:** Convert design questions and answers into structured expert records. Preserve constraints, assumptions, and alternative options.
- **Quality validation method:** Require answers with explicit rationale and tradeoff discussion. Prefer sources with expert review or community validation.

---

## AI / ML

### Why this domain

AI/ML is already represented in Atlas, but current classified expert signal is only ~36k L4/L5 records. For a 300M specialist, this domain needs deeper coverage of paper understanding, implementation reasoning, and experiment analysis.

### Phase 1 Sources

#### 1. ArXiv cs.LG / cs.CL / cs.AI / stat.ML
- **Source:** arXiv.org
- **Expert tier:** E1
- **License:** arXiv non-exclusive license
- **Expected value:** Tier-1 academic corpus. With extraction, can yield large-scale paper-to-explanation expert pairs.
- **Acquisition risk:** Low for preprocessing and storage. Redistribution must respect arXiv license and citation expectations.
- **Transformation required:** Extract abstract, methodology, results, and key claims. Convert into expert qa/reasoning records. Preserve paper metadata and arXiv id.
- **Quality validation method:** Require well-sourced sections. Filter by venue reputation or citation proxies where possible. Exclude low-quality preprints with retractions or corrections when detectable.

#### 2. Open-Platypus
- **Source:** garage-bAInd/Open-Platypus
- **Expert tier:** E2
- **License:** Apache-2.0
- **Expected value:** Expert-curated instruction-style data spanning science, math, and code. Good E2 reasoning seed.
- **Acquisition risk:** Low. Permissive license. Some content may be model-generated or GPT-4 augmented.
- **Transformation required:** Audit factual claims, preserve original question/answer pairs, map to expert schema. Flag uncertain factual content.
- **Quality validation method:** Cross-check technical claims against authoritative sources. Prefer human-authored or verified subsets. Track model-generated content separately.

#### 3. ML textbook derivations and explanations
- **Source:** [HUMAN MUST SUPPLY]
- **Expert tier:** E1
- **License:** [HUMAN MUST SUPPLY]
- **Expected value:** Step-by-step derivations, algorithm walkthroughs, and conceptual explanations. Strong E1 foundation for ML specialists.
- **Acquisition risk:** Medium. Many ML textbooks are copyrighted. Must identify openly licensed or public-domain content.
- **Transformation required:** Convert textbook sections into explanation records. Preserve notation, equations, and step logic. Avoid paraphrasic drift from source.
- **Quality validation method:** Require explicit source location and redistribution rights. Prefer open-access textbooks, CC-BY course notes, or author-approved excerpts. Validate mathematical notation preservation.

#### 4. Experiment analysis and paper explanation pairs
- **Source:** [HUMAN MUST SUPPLY]
- **Expert tier:** E2
- **License:** [HUMAN MUST SUPPLY]
- **Expected value:** Teaches result interpretation, ablation reasoning, and experimental design. Bridges paper reading and practical analysis.
- **Acquisition risk:** High. Curated experiment-analysis datasets are rare and may have mixed licensing.
- **Transformation required:** Pair paper or result set with structured analysis questions and expert answers. Preserve charts/tables as text where possible.
- **Quality validation method:** Require answers grounded in provided data. Prefer human-authored analysis. Exclude speculative or unsupported claims.

---

## Mathematics

### Why this domain

Mathematics supplies the reasoning muscle for expert training. It is currently missing from classified Atlas data. Without a dedicated math expert layer, the 300M specialist will lack structured quantitative reasoning at scale.

### Phase 1 Sources

#### 1. AIME / AMC / competition math problems
- **Source:** [HUMAN MUST SUPPLY]
- **Expert tier:** E3
- **License:** [HUMAN MUST SUPPLY]
- **Expected value:** Frontier-level competition problems with verified solutions. Strong E3 signal.
- **Acquisition risk:** High. Competition problems are often copyrighted or redistribution-restricted. Must verify license before ingestion.
- **Transformation required:** Convert problem statements and official solutions into expert qa/reasoning records. Preserve problem source and year.
- **Quality validation method:** Require official or verified solutions. Use exact answer checks where available. Exclude problems without redistribution rights.

#### 2. OpenMathInstruct-2
- **Source:** Ai-MO/OpenMathInstruct-2
- **Expert tier:** E2
- **License:** MIT, gated; verify on download
- **Expected value:** Large-scale math instruction data. Can contribute a major portion of Phase 1 math target.
- **Acquisition risk:** Medium. Size is attractive, but gated access and license verification are required. Content may include synthetic or model-generated explanations.
- **Transformation required:** Validate license and access terms. Filter to verified solution paths. Convert to expert schema with problem, context, solution, and verification fields.
- **Quality validation method:** Require ground-truth answer or validator pass. Sample for correctness. Track synthetic ratio.

#### 3. Proof-Pile / mathematical documents corpus
- **Source:** [HUMAN MUST SUPPLY]
- **Expert tier:** E2
- **License:** [HUMAN MUST SUPPLY]
- **Expected value:** Mathematical documents, proofs, and formal text. Good for proof-chain and notation-rich reasoning.
- **Acquisition risk:** Medium. Proven mathematical corpora may be large but license-mixed.
- **Transformation required:** Extract proof-oriented Q&A or theorem-to-proof pairs. Normalize notation. Convert to expert schema.
- **Quality validation method:** Require formal or community-verified proofs. Prefer sources with explicit redistribution permission. Validate mathematical correctness by sampling.

#### 4. University-level math reasoning problems
- **Source:** [HUMAN MUST SUPPLY]
- **Expert tier:** E2
- **License:** [HUMAN MUST SUPPLY]
- **Expected value:** Course-level problems with verified solutions. Bridges competition math and applied domain math.
- **Acquisition risk:** Medium. Course materials vary widely in license and quality.
- **Transformation required:** Convert exams, problem sets, and solution manuals into expert records. Include problem constraints and expected solution method.
- **Quality validation method:** Require verified solutions. Prefer open-courseware with clear licensing. Exclude paywalled or proprietary materials.

---

## Cross-Cutting Quality Gates for Phase 1

| Gate | Requirement |
|------|-------------|
| License | Must be resolved before promotion. No `unknown` license in curated expert data. |
| Difficulty | Must be assigned from 1-5 with provenance. |
| Expert tier | Must be assigned E1/E2/E3 with documented rationale. |
| Verification | Must have method and evidence. Verified is preferred; unverified requires explicit flag. |
| PII | Must be stripped where applicable. |
| Attribution | Required for CC-BY-SA and attribution-required sources. |
| Synthetic cap | Expert layer mostly prefers non-synthetic sources. Synthetic content must be labeled and capped. |

## Out of Scope for Phase 1

- System Engineering bulk acquisition
- Science domain expansion beyond existing accepted sources
- Creative and Business expert data
- Model training
- Release or Hugging Face publication

## Next Actions

1. Resolve `[HUMAN MUST SUPPLY]` sources in Phase 1 shortlist.
2. Confirm license and redistribution rights for each candidate.
3. Run source discovery and gating checks for review/accepted sources.
4. Produce per-source extraction runbooks before any ingestion.
