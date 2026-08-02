# Atlas Expert Extraction Runbook v0.1

## Purpose

Define how each VERIFIED or PARTIAL Priority 1 expert source is transformed into
an Atlas Expert Record Schema document.

This runbook is analysis and procedure only:
- no ingestion
- no downloads
- no dataset modifications

## Scope

Only the following sources from `metadata/expert_source_registry_v0.1.json`:
- SWE-bench verified
- StackExchange Code XML dumps
- ArXiv cs.LG / cs.CL / cs.AI / stat.ML
- Open-Platypus
- OpenMathInstruct-2

## Preconditions

1. The source has been evaluated in `metadata/expert_source_registry_v0.1.json`.
2. The record format is frozen in `docs/expert_record_schema_v0.1.md`.
3. Any license facts used below are taken directly from the registry or known
   public source pages. Unknown licensing facts are marked `[UNKNOWN]` and must
   be resolved before ingestion.

## General Rules

- Every output record must include `source`, `license`, `domain`, `expert_tier`,
  `difficulty`, `problem`, `context`, `solution`, `verification`, `provenance`.
- Do not invent license details. If a fact is unknown, keep it unresolved.
- Deduplication and quality filtering are mandatory before expert-layer promotion.
- Verification strategy is source-specific and must be recorded in
  `verification.method` and `verification.evidence`.

---

## 1. SWE-bench verified

Source id: `expert-swe-001`
Registry status: `VERIFIED`

### Input format

- Hugging Face dataset files for `princeton-nlp/SWE-bench`
- JSON-like instances with task identifiers, problem statements, repo metadata,
  and patch or evaluation references
- Verified instances carry official SWE-bench verification outcomes such as
  `FAIL_TO_PASS` and `PASS_TO_PASS` counts

### Required preprocessing

1. Confirm dataset version/snapshot and record access date.
2. Load only verified instances; exclude unresolved or broken instances.
3. Normalize repo, branch, and commit references.
4. Strip or anonymize contributor metadata if present in patches or logs.
5. Validate that patch evidence and test references are present.

### Transformation into Atlas Expert Record Schema

- `id`: `expert_swe_<seq>` or source-derived instance id with prefix
- `domain`: `software_engineering`
- `expert_tier`: `E2`
- `difficulty`: assign from instance signal; default to `3` if absent
- `type`: `qa`
- `source`: `expert-swe-001`, SWE-bench verified, MIT, snapshot date
- `license`: `MIT`
- `attribution`: Princeton NLP attribution text if required by downstream policy
- `problem`: issue statement or bug description
- `context`: repo name, file paths, failing tests, environment constraints
- `solution`: patch summary or repaired code; full patch may be included if
  storage allows
- `verification.method`: `gold_patch`
- `verification.status`: `verified` only for instances with passing evidence
- `verification.evidence`: `FAIL_TO_PASS` and `PASS_TO_PASS` counts
- `provenance.original_id`: upstream instance identifier
- `metadata.subdomains`: debugging, patch-generation, language/tool tags
- `messages`: user turn = problem + optional context; assistant turn = solution

### Quality filters

- Keep only instances with complete patch/test evidence.
- Reject unresolved or broken instances.
- Prefer instances with higher `PASS_TO_PASS` counts.
- Exclude security-sensitive private repo details if discovered.

### Deduplication strategy

- Deduplicate by upstream instance id.
- Secondary dedup by normalized problem text hash.

### Verification strategy

- Use official SWE-bench verification predicates as primary evidence.
- Record pass/fail counts explicitly.
- If a patch is later re-evaluated, update `verification.evidence` only; do
  not change upstream raw data.

### Expected output fields

All Atlas Expert Record Schema fields are expected, with emphasis on:
`verification.evidence`, `metadata.subdomains`, `source.version`, and
`provenance.original_id`.

---

## 2. StackExchange Code XML dumps

Source id: `expert-swe-002`
Registry status: `PARTIAL`

### Input format

- Stack Exchange XML dumps via archive.org or official archive exports
- Posts, comments, users, post history, votes, and tags
- Accepted answers and high-score answers are the primary expert targets

### Required preprocessing

1. Confirm dump date and archive source.
2. Parse XML for Posts and Comments only if needed for context.
3. Filter to accepted answers or high-score answers by tag.
4. Strip PII from user names, emails, and profile text.
5. Remove comments that do not add expert signal.
6. Record score threshold used.

### Transformation into Atlas Expert Record Schema

- `id`: `expert_swe_stackexchange_<post_id>` or canonical post id
- `domain`: `software_engineering`
- `expert_tier`: `E1`
- `difficulty`: assign from score/acceptance heuristics; default `2`
- `type`: `qa`
- `source`: `expert-swe-002`, StackExchange Code XML dumps, `CC-BY-SA-4.0`,
  dump date
- `license`: `CC-BY-SA-4.0`
- `attribution`: required; include post id, author, and post URL
- `problem`: question title and body
- `context`: tags, score, accepted status, related posts if useful
- `solution`: accepted or highest-score answer body
- `verification.method`: `peer_review`
- `verification.status`: `verified` only for accepted or high-score answers
- `verification.evidence`: score, acceptance flag, reviewer notes if any
- `provenance.original_id`: post id or answer id
- `metadata.subdomains`: tags normalized to Atlas subdomain tags
- `messages`: user turn = question; assistant turn = answer

### Quality filters

- Require minimum score threshold; exact threshold must be documented.
- Keep accepted answers first, then highest-score answers.
- Exclude duplicate questions and near-duplicate answers.
- Exclude low-quality or obsolete answers even if scored.

### Deduplication strategy

- Deduplicate by post id.
- Secondary dedup by normalized question/answer pair hash.
- Remove exact duplicates across tags.

### Verification strategy

- Use StackExchange community score and acceptance as proxy verification.
- Record score and acceptance state in `verification.evidence`.
- Human spot-check recommended for high-value subdomains.

### Expected output fields

All Atlas Expert Record Schema fields are expected, with emphasis on:
`attribution`, `verification.evidence`, `metadata.subdomains`, and
`source.version`.

---

## 3. ArXiv cs.LG / cs.CL / cs.AI / stat.ML

Source id: `expert-aiml-001`
Registry status: `VERIFIED`

### Input format

- ArXiv abstract and source text for cs.LG, cs.CL, cs.AI, and stat.ML
- Metadata includes arXiv id, authors, title, abstract, and PDF/source links
- License is arXiv non-exclusive license

### Required preprocessing

1. Confirm arXiv category filter and access date.
2. Fetch abstracts and well-sourced sections only.
3. Preserve arXiv id, authors, and year for provenance.
4. Convert only sections suitable for expert Q/A or explanation pairs.
5. Do not ingest full PDFs without a text-extraction and cleaning pipeline.

### Transformation into Atlas Expert Record Schema

- `id`: `expert_aiml_arxiv_<arxiv_id>` or normalized seq
- `domain`: `ai_machine_learning`
- `expert_tier`: `E1`
- `difficulty`: assign from section complexity; default `2`
- `type`: `reasoning` or `qa`
- `source`: `expert-aiml-001`, ArXiv cs.LG/CL/AI/stat.ML,
  `arXiv non-exclusive license`, access date
- `license`: `arXiv non-exclusive license`
- `attribution`: required; include arXiv id, authors, and title
- `problem`: research question or concept explanation prompt derived from paper
- `context`: abstract, section excerpt, methodology summary, constraints
- `solution`: expert explanation, derivation, or summary grounded in source
- `verification.method`: `peer_review`
- `verification.status`: `verified` only for well-sourced sections
- `verification.evidence`: arXiv id, section source, author/year
- `provenance.original_id`: arXiv id
- `metadata.subdomains`: transformers, llm, rag, mlops, or paper-specific tags
- `messages`: user turn = problem + context; assistant turn = solution

### Quality filters

- Require complete abstract or well-sourced section.
- Exclude retracted or corrected papers when detectable.
- Prefer papers from reputable venues or with citation proxies.
- Exclude low-quality or incoherent sections.

### Deduplication strategy

- Deduplicate by arXiv id.
- Secondary dedup by normalized problem/solution pair hash.

### Verification strategy

- Use arXiv id and section provenance as verification evidence.
- Record source location explicitly.
- Human review recommended for frontier claims.

### Expected output fields

All Atlas Expert Record Schema fields are expected, with emphasis on:
`attribution`, `provenance.original_id`, `verification.evidence`, and
`source.version`.

---

## 4. Open-Platypus

Source id: `expert-aiml-002`
Registry status: `VERIFIED`

### Input format

- Hugging Face dataset files for `garage-bAInd/Open-Platypus`
- Instruction-style pairs across science, math, and code
- License: `Apache-2.0`

### Required preprocessing

1. Confirm dataset version and access date.
2. Load full dataset; size is publicly claimed but exact row count should be
   verified from the downloaded file.
3. Separate human-authored content from model-augmented content if detectable.
4. Normalize question/answer formatting.
5. Flag factual claims for audit.

### Transformation into Atlas Expert Record Schema

- `id`: `expert_aiml_openplatypus_<seq>` or source-derived id
- `domain`: `ai_machine_learning`
- `expert_tier`: `E2`
- `difficulty`: assign from question complexity; default `2`
- `type`: `qa` or `instruction`
- `source`: `expert-aiml-002`, Open-Platypus, `Apache-2.0`, access date
- `license`: `Apache-2.0`
- `attribution`: optional for permissive license; include source attribution
  if required by project policy
- `problem`: question or instruction text
- `context`: optional background or data provided in the pair
- `solution`: answer text
- `verification.method`: `verified_solution_set`
- `verification.status`: `verified` only after factual audit
- `verification.evidence`: source pair id, audit notes
- `provenance.original_id`: upstream row id or hash
- `metadata.subdomains`: science, math, code, or domain-specific tags
- `metadata.model_generated`: `true` if upstream content is model-generated
- `messages`: user turn = problem; assistant turn = solution

### Quality filters

- Require complete question/answer pairs.
- Exclude empty or malformed answers.
- Flag model-generated content for separate tracking.
- Prefer human-authored or verified subsets.

### Deduplication strategy

- Deduplicate by upstream row id.
- Secondary dedup by normalized question/answer pair hash.

### Verification strategy

- Use curated dataset provenance as baseline verification.
- Perform factual audit on technical claims.
- Cross-check against authoritative sources where possible.

### Expected output fields

All Atlas Expert Record Schema fields are expected, with emphasis on:
`metadata.model_generated`, `verification.status`, `metadata.quality_score`,
and `metadata.notes`.

---

## 5. OpenMathInstruct-2

Source id: `expert-math-002`
Registry status: `PARTIAL`

### Input format

- Hugging Face dataset files for `Ai-MO/OpenMathInstruct-2`
- Math instruction pairs with problem statements and solutions
- Claimed size is large; exact row count should be verified from file
- License claim: `MIT`, gated; verify on download

### Required preprocessing

1. Confirm gated-access status and exact license on download.
2. Record dataset version and access date.
3. Validate that access terms allow intended expert-training use.
4. Normalize mathematical notation and LaTeX formatting if present.
5. Filter to verified solution paths if distinguishable.

### Transformation into Atlas Expert Record Schema

- `id`: `expert_math_openmathinstruct2_<seq>` or source-derived id
- `domain`: `mathematics`
- `expert_tier`: `E2`
- `difficulty`: assign from problem complexity; default `3`
- `type`: `reasoning`
- `source`: `expert-math-002`, OpenMathInstruct-2, `MIT`, access date,
  version snapshot
- `license`: `MIT` only if confirmed on download; otherwise leave as
  `[UNKNOWN]` until resolved
- `attribution`: optional for MIT; include source attribution if required
- `problem`: math problem statement
- `context`: optional constraints, definitions, or background
- `solution`: step-by-step solution or final answer with reasoning
- `verification.method`: `auto_grader` or `verified_solution_set`
- `verification.status`: `verified` only for ground-truth validated paths
- `verification.evidence`: grader output, validator result, or solution set id
- `provenance.original_id`: upstream row id or problem id
- `metadata.subdomains`: olympiad, calculus, algebra, number theory, or
  problem-specific tags
- `messages`: user turn = problem; assistant turn = solution

### Quality filters

- Require complete problem and solution pairs.
- Exclude problems without ground-truth answers if validator is available.
- Sample for correctness before full promotion.
- Track synthetic or model-generated ratio separately.

### Deduplication strategy

- Deduplicate by upstream problem id.
- Secondary dedup by normalized problem text hash.

### Verification strategy

- Use ground-truth answer or validator pass as primary evidence.
- Record grader or validator output in `verification.evidence`.
- Human review recommended for edge cases.

### Expected output fields

All Atlas Expert Record Schema fields are expected, with emphasis on:
`verification.evidence`, `metadata.subdomains`, `source.version`,
`license`, and `metadata.synthetic`.

---

## Cross-Cutting Notes

- All sources in this runbook are Priority 1 only.
- No random dataset recommendations are included.
- If a source moves from `PARTIAL` to `VERIFIED` after additional checks,
  update `metadata/expert_source_registry_v0.1.json` before ingestion.
- If a source becomes `UNKNOWN`, stop and resolve the unknown fact before
  proceeding.

## Out of Scope

- System Engineering, Science, Creative, Business, and Hardware sources
- Model training, release, or Hugging Face publication
- Any operation that modifies `raw/`, `curated/`, or training outputs
