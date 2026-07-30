# Atlas Intelligence Layer v1

**Version:** 1.0.0  
**Status:** Draft  
**Release Context:** Atlas v1.0-RC1 (immutable)  
**Purpose:** Metadata-only intelligence system for dataset record analysis

---

## 1. Motivation

The Atlas Dataset v1.0-RC1 contains **9,893,844 records** across 9 categories, of which approximately **1,543,548 records (15.6%)** have no assigned difficulty level. These records come from four primary sources (Tulu-3, OpenWebMath, ArXiv, C4) and were ingested with license status `"unknown"`, which excluded them from the original v0.1-v0.3 difficulty classification pipeline.

The Intelligence Layer v1 addresses this gap by providing:

- A **standardised difficulty taxonomy** (5 levels) replacing the original 3-level scheme
- An **extensible metadata schema** for attaching intelligence attributes to records
- A **deterministic, rule-based classification engine** that can scale to millions of records
- **Foundation for future intelligence attributes** (reasoning type classification, skill domain tagging)

Key design principles:

| Principle | Rationale |
|-----------|-----------|
| **Metadata-only** | Never modifies canonical dataset records |
| **Deterministic** | Same record → same result, every time |
| **Stdlib-only** | No ML dependencies, no GPU, no network calls |
| **Explainable** | Every classification includes a human-readable reason |
| **Schema-validated** | All output conforms to `intelligence_schema_v1.json` |

---

## 2. Difficulty Taxonomy

The taxonomy defines **5 levels of cognitive demand**, inspired by Bloom's Taxonomy but adapted for AI training dataset records.

### Level 1 — Basic

| Aspect | Description |
|--------|-------------|
| **Memory/Recall** | Simple facts, direct answers, single-step reasoning |
| **Examples** | "What is the capital of France?", "Define a variable" |
| **Token range** | < 30 words per turn |
| **Technical vocab** | None required |
| **Reasoning steps** | 0–1 |

### Level 2 — Intermediate

| Aspect | Description |
|--------|-------------|
| **Comprehension/Application** | Multi-concept explanations, standard programming, practical problems |
| **Examples** | "Explain how a hash table works", "Write a palindrome checker" |
| **Token range** | 30–150 words per turn |
| **Technical vocab** | Basic domain terms |
| **Reasoning steps** | 2–4 |

### Level 3 — Advanced

| Aspect | Description |
|--------|-------------|
| **Analysis** | Multi-step reasoning, debugging, design trade-offs, cross-domain |
| **Examples** | "Debug a race condition", "Design a K8s deployment strategy" |
| **Token range** | 100–400 words per turn |
| **Technical vocab** | Professional-level |
| **Reasoning steps** | 5+ with conditions |

### Level 4 — Expert

| Aspect | Description |
|--------|-------------|
| **Evaluation** | Architecture decisions, deep analysis, system optimisation, research interpretation |
| **Examples** | "Design a multi-region control plane", "Critique ML paper methodology" |
| **Token range** | 200+ words per turn |
| **Technical vocab** | Dense, precise |
| **Reasoning steps** | 8+ with multiple constraints |

### Level 5 — Research

| Aspect | Description |
|--------|-------------|
| **Synthesis** | Frontier knowledge, novel synthesis, original hypotheses, unanswered problems |
| **Examples** | "Propose a research agenda for mechanistic interpretability" |
| **Token range** | 300+ words per turn |
| **Technical vocab** | Frontier-level |
| **Reasoning steps** | 10+ with novel connections |

**Continuity with v0 scheme:**

```
v0: 0 (unassessed) → v1: unknown
v0: 1 (easy)       → v1: Level 1–2
v0: 2 (medium)     → v1: Level 2–3
v0: 3 (hard)       → v1: Level 3–4
```

Full taxonomy with indicators, examples, and scoring criteria:  
`metadata/intelligence/difficulty_taxonomy_v1.json`

---

## 3. Classification Methodology

The difficulty classifier (`scripts/intelligence/difficulty_analyzer.py`) uses **7 signal extractors** whose outputs are fused into a single difficulty level.

### Signal Extractor Pipeline

```
Dataset Record
    │
    ├─► Prompt Complexity       (15% weight)
    │     Length, sophistication markers, constraints, code presence
    │
    ├─► Answer Complexity       (30% weight)
    │     Length, structural richness, abstraction level, reasoning steps, code fraction, citations
    │
    ├─► Technical Vocabulary    (18% weight)
    │     Density of domain-specific technical terms (6 domain dictionaries)
    │
    ├─► Reasoning Depth         (30% weight)
    │     Step markers, conditional language, reasoning patterns, mathematical notation
    │
    ├─► Domain Difficulty       (7% weight)
    │     Base offset per category (e.g., AI/ML: +0.3, personal assistant: -0.2)
    │
    └─► Source Reliability      (confidence only)
          Trust level of upstream source (arxiv_cs: 0.90, tulu3_sft: 0.70)
```

### Fusion

The weighted raw score maps to difficulty levels via calibrated thresholds:

| Raw Score Range | Level |
|-----------------|-------|
| 0.00 – 0.17    | 1 (Basic) |
| 0.18 – 0.39    | 2 (Intermediate) |
| 0.40 – 0.61    | 3 (Advanced) |
| 0.62 – 0.79    | 4 (Expert) |
| 0.80 – 1.00    | 5 (Research) |

### Confidence

Confidence (0–1) reflects signal agreement and evidence sufficiency:

- **High agreement** across all 4 main signals → higher confidence
- **Low vocabulary density** + **short text** → lower confidence (< 0.5)
- Records with confidence < 0.5 are flagged for manual review

---

## 4. Metadata Schema

Output records conform to `metadata/intelligence/intelligence_schema_v1.json`.

### Top-level fields

```json
{
  "record_id": "string (FK to canonical record)",
  "difficulty": {
    "level": 1..5,
    "confidence": 0.0..1.0,
    "source": "classifier|manual|rule_based",
    "reason": "human-readable explanation"
  },
  "reasoning_types": ["factual", "explanation", "coding", "debugging", "analysis", "design", "research"],
  "skill_domains": ["software_engineering", "system_engineering", "ai_ml", "science", "business", "creative"],
  "classified_at": "ISO 8601 timestamp",
  "classifier_version": "1.0.0",
  "features": {
    "prompt_tokens": int,
    "answer_tokens": int,
    "total_tokens": int,
    "vocabulary_density": float,
    "reasoning_steps_estimate": int,
    "code_fraction": float,
    "cross_domain_flag": bool
  },
  "review_status": "unreviewed|accepted|disputed|overridden"
}
```

### Reasoning Types

| Type | Description |
|------|-------------|
| `factual` | Simple assertion, definition, recall |
| `explanation` | Causal or mechanistic explanation ("because...") |
| `coding` | Code generation, implementation |
| `debugging` | Error diagnosis, root cause analysis |
| `analysis` | Comparison, evaluation, trade-offs |
| `design` | Architecture, system design, planning |
| `research` | Frontier knowledge, hypotheses, novel synthesis |

### Skill Domains

| Domain | Typical Categories | Example Topics |
|--------|-------------------|----------------|
| `software_engineering` | 02, 09 | Algorithms, APIs, programming |
| `system_engineering` | 03, 05 | Infrastructure, networking, hardware |
| `ai_ml` | 04, 01, 09 | ML, deep learning, LLMs |
| `science` | 06, 05 | Physics, math, biology, chemistry |
| `business` | 07 | Finance, strategy, management |
| `creative` | 08 | Writing, art, music, design |

---

## 5. Limitations

### Current

| Limitation | Impact | Workaround |
|------------|--------|------------|
| **Rule-based only** | Cannot match human judgment accuracy | Stratified human validation recommended |
| **English-centric vocab** | Under-counts non-English technical terms | Extend `TECHNICAL_VOCAB` dictionaries |
| **No ML classifier** | Limited to surface-level text signals | Future phase: train on human-reviewed samples |
| **Token estimates** | Word-count proxy, not true tokenization | Acceptable for relative comparison |
| **No cross-modal analysis** | Ignores images, audio, structured data | Metadata-only phase; content analysis is future |
| **Small sample validation** | 16 synthetic records in dry-run | Full production run needed for reliable stats |

### Extrapolation Risk

The baseline report's per-source projections are based on very small samples. The actual distribution when running against all 1.5M unknown records may differ significantly, especially for:

- **ArXiv CS**: Contains research papers that should produce L3-L5 results
- **OpenWebMath**: Contains derivations that may span L3-L4
- **C4**: Large web corpus with diverse difficulty levels
- **Tulu-3**: Instruction-tuning data with mixed difficulty

---

## 6. Future Improvements

### Immediate (v1.1)

- [ ] Run full production classification across all 1,543,548 unknown records
- [ ] Validate against human review on stratified sample (n=400, 100 per source)
- [ ] Calibrate classifier thresholds based on human agreement analysis
- [ ] Integrate difficulty metadata into training view generation

### Short-term (v1.2)

- [ ] Add ML-based classifier trained on human-reviewed samples
- [ ] Extend to multi-lingual technical vocabulary detection
- [ ] Add per-category difficulty distribution monitoring
- [ ] Support difficulty overrides via `review_status` field

### Medium-term (v2.0)

- [ ] Add additional intelligence attributes beyond difficulty
- [ ] Knowledge type classification (fact / procedure / concept / reasoning / code)
- [ ] Cross-modal metadata for multimodal records
- [ ] Active learning loop for classifier improvement

---

## File Reference

| File | Purpose |
|------|---------|
| `metadata/intelligence/difficulty_taxonomy_v1.json` | 5-level difficulty framework |
| `metadata/intelligence/intelligence_schema_v1.json` | JSON Schema for intelligence metadata |
| `scripts/intelligence/difficulty_analyzer.py` | Difficulty classification engine |
| `tests/test_intelligence_layer.py` | Validation suite (15 tests) |
| `reports/intelligence/difficulty_baseline_report.json` | Baseline analysis of unknown records |

---

*Atlas Intelligence Layer v1. Metadata-only. Immutable dataset preserved.*
