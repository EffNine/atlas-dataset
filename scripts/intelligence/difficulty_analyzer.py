#!/usr/bin/env python3
"""
difficulty_analyzer.py — Atlas Difficulty Classification Engine (v1).

Analyzes dataset records and assigns difficulty levels, reasoning types,
and skill domains per the Atlas Intelligence Metadata Schema v1.

This is a metadata-only operation.  The engine NEVER modifies or rewrites
canonical dataset records.

Usage:
  python difficulty_analyzer.py --input-file <path> [--output-file <path>]
  python difficulty_analyzer.py --input-file <path> --dry-run --sample-size 200
  python difficulty_analyzer.py --input-file <path> --output-file results.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLASSIFIER_VERSION = "1.1.0"

# Technical vocabulary per skill domain (used for density scoring)
TECHNICAL_VOCAB: dict[str, set[str]] = {
    "software_engineering": {
        "algorithm", "api", "array", "async", "authentication", "binary",
        "buffer", "cache", "class", "compiler", "concurrency", "database",
        "deployment", "encryption", "framework", "function", "git", "hash",
        "inheritance", "interface", "json", "library", "middleware", "module",
        "multithreading", "namespace", "null", "object", "pipeline",
        "polymorphism", "protocol", "queue", "recursion", "refactoring",
        "regex", "repository", "serialization", "socket", "stream",
        "synchronization", "thread", "token", "type", "variable", "vector",
        "virtualization", "websocket", "xml", "yaml",
    },
    "system_engineering": {
        "bandwidth", "boot", "bottleneck", "cluster", "container", "daemon",
        "docker", "downtime", "fault", "firewall", "grafana", "horizontal",
        "kubernetes", "latency", "load", "logging", "metric", "monitoring",
        "orchestration", "partition", "pod", "provisioning", "replica",
        "scalability", "scheduler", "service", "shard", "throughput", "tls",
        "uptime", "vertical",
    },
    "ai_ml": {
        "activation", "attention", "backpropagation", "batch", "bias",
        "classification", "convolution", "dataset", "dropout", "embedding",
        "epoch", "fine-tune", "gradient", "inference", "latent", "logits",
        "loss", "model", "neural", "normalization", "overfitting", "pooling",
        "precision", "recall", "regression", "reinforcement", "softmax",
        "supervised", "tokenizer", "training", "transformer", "unsupervised",
        "validation", "weights",
    },
    "science": {
        "atom", "calculus", "catalyst", "chromatography", "derivative",
        "differential", "electron", "equation", "genome", "hypothesis",
        "isotope", "kinetics", "molecule", "neutron", "orbit", "particle",
        "phenotype", "photon", "probability", "quantum", "spectroscopy",
        "statistics", "synthesis", "taxonomy", "thermodynamics", "vector",
    },
    "business": {
        "acquisition", "agile", "asset", "audit", "benchmark", "capex",
        "cashflow", "compliance", "dividend", "equity", "forecast",
        "franchise", "friction", "governance", "inventory", "leverage",
        "liability", "margin", "merger", "opex", "portfolio", "quarterly",
        "revenue", "risk", "stakeholder", "startup", "supply", "valuation",
    },
    "creative": {
        "aesthetic", "analogous", "archetype", "asymmetry", "chroma",
        "composition", "contrast", "diegetic", "dissonance", "exposition",
        "foreshadowing", "gestalt", "harmony", "juxtaposition", "leitmotif",
        "metaphor", "motif", "narrative", "palette", "perspective",
        "protagonist", "rhythm", "saturation", "stanza", "subtext",
        "symmetry", "syntax", "tension", "texture", "typography",
    },
}

ALL_TECH_VOCAB = set.union(*TECHNICAL_VOCAB.values()) if TECHNICAL_VOCAB else set()

# Reasoning indicators (used for both reasoning_type detection and depth scoring)
REASONING_PATTERNS: dict[str, list[str]] = {
    "factual": [
        r"\bis\b", r"\bmeans?\b", r"\bdefined?\s+as\b", r"\brefers?\s+to\b",
        r"\bis\s+a\b", r"\bconsists?\s+of\b",
    ],
    "explanation": [
        r"\bbecause\b", r"\btherefore\b", r"\bhence\b", r"\bworks\s+by\b",
        r"\bexplain", r"\bas\s+a\s+result\b", r"\bdue\s+to\b",
        r"\bthis\s+(means?|implies?|suggests?)\b",
    ],
    "coding": [
        r"```\w*", r"def\s+\w+\s*\(", r"class\s+\w+", r"import\s+\w+",
        r"function\s+\w+", r"public\s+\w+", r"int\s+\w+\s*=\b",
        r"\bconsole\.log\b", r"\breturn\b", r"\bprint[f]?\(",
    ],
    "debugging": [
        r"\bbug\b", r"\berror\b", r"\bfail(ure|s)?\b", r"\bcrash\b",
        r"\bexception\b", r"\bdebug", r"\bissue\b", r"\bproblem\b",
        r"\bincorrect\b", r"\bmalfunction\b", r"\bwrong\b",
    ],
    "analysis": [
        r"\bcompare\b", r"\bcontrast\b", r"\bevaluate\b", r"\banaly(s|z)e\b",
        r"\btrade[- ]?off\b", r"\bimplications?\b", r"\bpro[s]?\s+and\s+con[s]?\b",
        r"\badvantage", r"\bdisadvantage", r"\bversus\b", r"\bvs\.?\b",
    ],
    "design": [
        r"\bdesign\b", r"\barchitecture\b", r"\bpattern\b", r"\bcomponent\b",
        r"\binterface\b", r"\bmodular", r"\bscalab", r"\breliab",
        r"\bmaintainab", r"\bcoupling\b", r"\bcohesion\b",
    ],
    "research": [
        r"\bhypothesis\b", r"\bnovel\b", r"\bfrontier\b", r"\bunanswered\b",
        r"\bwe\s+propose\b", r"\bthis\s+work\b", r"\bcontribution\b",
        r"\bstate[- ]?of[- ]?the[- ]?art\b", r"\bopen\s+problem\b",
        r"\bresearch\s+(question|direction|gap|agenda)\b",
    ],
}

# Step-counting / reasoning-depth markers
STEP_PATTERNS = re.compile(
    r"(?:"
    r"first(?:ly)?|second(?:ly)?|third(?:ly)?|fourth(?:ly)?|fifth(?:ly)?|"
    r"finally|next|then|last(?:ly)?|step\s+\d+|phase\s+\d+|stage\s+\d+|"
    r"in\s+order\s+to|to\s+(?:do|achieve|implement|solve|compute)|"
    r"if\s+\w+|when\s+\w+|after\s+\w+|before\s+\w+|"
    r"there(?:fore|by|fore)|consequently|subsequently|"
    r"meanwhile|simultaneously|alternatively|"
    r"(?:^|\s)\(\d+\)\s|(?:^|\s)\d+\.[\s)]|(?:^|\s)\d+\)\s|"   # (1), 1., 1)
    r"(?:^|\s)[A-Z]\.\s(?=[A-Z])"                                # A. B. C. sections
    r")",
    re.IGNORECASE | re.MULTILINE,
)

CONDITIONAL_PATTERNS = re.compile(
    r"\b(?:if|unless|provided\s+that|assuming|given\s+that|"
    r"depending\s+on|in\s+case|otherwise|else\b|"
    r"whenever|whether|should\s+\w+)\b",
    re.IGNORECASE,
)

# Source trust mapping for confidence calibration
SOURCE_TRUST: dict[str, float] = {
    "wikimedia/wikipedia": 0.85,
    "synthetic/personal-assistant": 0.50,
    "allenai/c4": 0.60,
    "tulu3_sft": 0.70,
    "ultrafeedback": 0.65,
    "openwebmath": 0.80,
    "arxiv_cs": 0.90,
    "other": 0.40,
}

# Difficulty thresholds (overridable at module level or via parameter)
# Format: (raw_score_threshold, difficulty_level)
# v1.0 defaults:  L3@0.40, L4@0.62, L5@0.80
# v1.1 calibrated: L3@0.35, L4@0.55, L5@0.75
LEVEL_THRESHOLDS_V1_0: list[tuple[float, int]] = [
    (0.0, 1),   # Basic
    (0.18, 2),  # Intermediate
    (0.40, 3),  # Advanced
    (0.62, 4),  # Expert
    (0.80, 5),  # Research
]

LEVEL_THRESHOLDS_V1_1: list[tuple[float, int]] = [
    (0.0, 1),   # Basic
    (0.18, 2),  # Intermediate
    (0.35, 3),  # Advanced  (was 0.40)
    (0.55, 4),  # Expert    (was 0.62)
    (0.75, 5),  # Research  (was 0.80)
]

# Category base difficulty (default offset per category)
CATEGORY_DIFFICULTY_OFFSET: dict[str, float] = {
    "01_foundation": 0.0,
    "02_software_engineering": 0.2,
    "03_system_engineering": 0.3,
    "04_ai_machine_learning": 0.3,
    "05_hardware_engineering": 0.3,
    "06_science_engineering": 0.2,
    "07_business_knowledge": 0.1,
    "08_creative_knowledge": 0.1,
    "09_personal_assistant": -0.2,
}

# Level thresholds (active — currently v1.1 calibrated)
LEVEL_THRESHOLDS = LEVEL_THRESHOLDS_V1_1


# ---------------------------------------------------------------------------
# Signal extractors
# ---------------------------------------------------------------------------

def _text_from_messages(messages: list[dict]) -> tuple[str, str]:
    """Extract user prompt and assistant answer from messages list."""
    prompt_parts = []
    answer_parts = []
    for msg in messages:
        content = msg.get("content", "") or ""
        if isinstance(content, list):
            content = " ".join(
                item.get("text", "") for item in content
                if isinstance(item, dict)
            )
        content = str(content).strip()
        role = msg.get("role", "")
        if role == "user":
            prompt_parts.append(content)
        elif role == "assistant":
            answer_parts.append(content)
    return " ".join(prompt_parts), " ".join(answer_parts)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: word count / 0.75."""
    words = len(text.split())
    return max(0, int(words / 0.75))


def _prompt_complexity(prompt: str, answer: str) -> float:
    """Score prompt complexity 0..1 based on length, structure, and markers."""
    if not prompt:
        return 0.0

    score = 0.0
    words = prompt.split()
    word_count = len(words)

    # Length contribution (longer == potentially more complex, capping at 600 words)
    length_norm = min(word_count / 600.0, 1.0)
    score += 0.15 * length_norm

    # Structural markers: how many reasoning steps are implied
    steps = len(STEP_PATTERNS.findall(prompt))
    conds = len(CONDITIONAL_PATTERNS.findall(prompt))
    structure_score = min((steps + conds) / 8.0, 1.0)
    score += 0.15 * structure_score

    # Question sophistication markers — strong signals
    sophistication = 0.0
    if re.search(r"\b(?:compare|contrast|evaluate|analyse?ze|justify|critique)\b", prompt, re.I):
        sophistication += 0.5
    if re.search(r"\b(?:design|propose|create|develop|build|implement)\b", prompt, re.I):
        sophistication += 0.4
    if re.search(r"\b(?:explain|describe|elaborate|discuss|detail)\b", prompt, re.I):
        sophistication += 0.2
    if re.search(r"\b(?:why|how)\b", prompt, re.I):
        sophistication += 0.1
    # Multiple imperative verbs suggest compound request
    imperatives = len(re.findall(r"\b(?:design|explain|compare|list|describe|write|create|prove|derive|show|implement|optimise?|analyze|analyse|evaluate|justify)\b", prompt, re.I))
    if imperatives >= 2:
        sophistication += 0.2
    score += 0.30 * min(sophistication, 1.0)

    # Constraint density: "given X" / "under Y conditions" / "with Z constraints"
    constraints = len(re.findall(
        r"\b(?:given|assuming|provided\s+that|under\s+\w+\s+(?:condition|constraint|assumption)|"
        r"without\s+(?:using|modifying|changing)|in\s+the\s+context\s+of|"
        r"subject\s+to|constrained\s+by|limited\s+to)\b",
        prompt, re.I,
    ))
    constraint_score = min(constraints / 4.0, 1.0)
    score += 0.15 * constraint_score

    # Code presence in prompt
    if re.search(r"```|def\s+\w+\s*\(|class\s+\w+|<[a-zA-Z]+[^>]*>", prompt):
        score += 0.15

    # Multi-sentence prompt (indicates compound question)
    sentences = len(re.findall(r'[.!?]+', prompt))
    if sentences >= 3:
        score += 0.10

    return min(score, 1.0)


def _answer_complexity(answer: str) -> float:
    """Score answer complexity 0..1 based on structure, depth, and abstraction."""
    if not answer:
        return 0.0

    score = 0.0
    words = answer.split()
    word_count = len(words)

    # Length contribution (more gradual ramp)
    length_norm = min(word_count / 1500.0, 1.0)
    score += 0.15 * length_norm

    # Structural richness: sections, headings, lists, code blocks
    structures = 0
    if re.search(r"(?:^|\n)#{1,6}\s", answer):
        structures += 2
    # Bullet lists (*, -, +)
    if re.search(r"(?:^|\n)[*\-\+]\s", answer):
        structures += 1.5
    # Numbered lists (1., 1), (1))
    if re.search(r"(?:^|\n)\d+[.\)]\s", answer):
        structures += 1
    # Inline numbered items like (1), (2), (n)
    if re.search(r"\(\d+\)\s", answer):
        structures += 1
    # Code blocks
    if "```" in answer:
        structures += 2
    if ">>> " in answer or " $ " in answer:
        structures += 1
    # Tables
    if "|" in answer and "---" in answer:
        structures += 2
    # LaTeX math
    if re.search(r'\$\$|\$[^$]+\$', answer):
        structures += 2
    # Bold/italic markers
    if re.search(r'\*\*|__', answer):
        structures += 0.5
    score += 0.20 * min(structures / 8.0, 1.0)

    # Abstraction level: references to theory, principles, trade-offs
    abstractions = 0
    if re.search(r"\b(?:abstract|theory|principle|concept|paradigm|framework|methodology)\b", answer, re.I):
        abstractions += 1
    if re.search(r"\b(?:trade[- ]?off|limitation|constraint|complexity|overhead|bottleneck)\b", answer, re.I):
        abstractions += 1
    if re.search(r"\b(?:in\s+general|in\s+practice|in\s+theory|in\s+the\s+limit|in\s+the\s+worst\s+case)\b", answer, re.I):
        abstractions += 1
    if re.search(r"\b(?:implications?|consequences?|ramifications?|downsides?|drawbacks?)\b", answer, re.I):
        abstractions += 1
    if re.search(r"\b(?:however|although|nevertheless|nonetheless|on\s+the\s+other\s+hand|conversely)\b", answer, re.I):
        abstractions += 1  # contrastive/hedging language
    score += 0.20 * min(abstractions / 5.0, 1.0)

    # Reasoning steps (including numbered list items and explicit step markers)
    steps = len(STEP_PATTERNS.findall(answer))
    conds = len(CONDITIONAL_PATTERNS.findall(answer))
    reasoning_score = min((steps * 0.8 + conds * 1.2) / 12.0, 1.0)
    score += 0.25 * reasoning_score

    # Code fraction (code to total word ratio)
    code_blocks = re.findall(r"```\w*\n(.*?)```", answer, re.DOTALL)
    code_total = sum(len(b.split()) for b in code_blocks)
    if word_count > 0:
        code_frac = code_total / word_count
        score += 0.20 * min(code_frac * 2.5, 1.0)

    # Domain-specific depth signals: citations, references, formulae
    if re.search(r"\[\d+\]|et\s+al\.|\(doi:|arxiv:", answer, re.I):
        score += 0.15
    # Mathematical notation (operators, symbols)
    if re.search(r"[×÷±≈≠≡≤≥∞∫∑√∂∇]", answer):
        score += 0.10
    # Technical notation with subscripts/superscript notation
    if re.search(r"\w_\{\w+\}|\w\^\{\w+\}|\\[alpha|beta|gamma|theta]", answer):
        score += 0.10

    return min(score, 1.0)


def _technical_vocabulary_density(text: str, category: str) -> float:
    """Compute the density of technical vocabulary in text (0..1)."""
    if not text:
        return 0.0

    words_lower = set(re.findall(r"[a-z_][a-z0-9_]{2,}", text.lower()))
    if not words_lower:
        return 0.0

    # Domain-specific vocabulary
    domain_vocab = set()
    for skill_domain, vocab_set in TECHNICAL_VOCAB.items():
        # Check if category aligns with this domain
        if category and any(d in category for d in ["software", "system", "ai", "science", "business", "creative"]):
            if "software" in category and skill_domain == "software_engineering":
                domain_vocab.update(vocab_set)
            elif "system" in category and skill_domain == "system_engineering":
                domain_vocab.update(vocab_set)
            elif "ai" in category and skill_domain == "ai_ml":
                domain_vocab.update(vocab_set)
            elif "science" in category and skill_domain == "science":
                domain_vocab.update(vocab_set)
            elif "business" in category and skill_domain == "business":
                domain_vocab.update(vocab_set)
            elif "creative" in category and skill_domain == "creative":
                domain_vocab.update(vocab_set)
            elif "foundation" in category or "personal" in category:
                domain_vocab.update(vocab_set)  # broad vocabulary
        else:
            domain_vocab.update(vocab_set)

    # General tech vocabulary (always included)
    domain_vocab.update(ALL_TECH_VOCAB)

    matches = len(words_lower & domain_vocab)
    density = matches / len(words_lower)
    return min(density * 3.0, 1.0)  # amplify; 33% tech words -> 1.0


def _reasoning_depth(prompt: str, answer: str) -> float:
    """Estimate reasoning depth 0..1 based on step markers, conditions, and structure."""
    combined = prompt + " " + answer

    steps = len(STEP_PATTERNS.findall(combined))
    conds = len(CONDITIONAL_PATTERNS.findall(combined))

    # Depth signal from reasoning pattern matches
    reasoning_hits = 0
    for rtype, patterns in REASONING_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, combined, re.I):
                reasoning_hits += 1
                break  # one per type

    # Each hit beyond factual/explanation indicates deeper reasoning
    depth_from_type = max(0, reasoning_hits - 1) / 6.0  # 0..~0.83

    # Mathematical content (formulas, equations, derivations)
    math_signals = 0
    if re.search(r"[×÷±≈≠≡≤≥∞∫∑√∂∇∏∆∈∀∃→⇒⇔]", combined):
        math_signals += 2
    if re.search(r"\w\s*=\s*\\frac|\w\s*=\s*[÷×]\s*\w|∂²|∂/∂|∫|∑|∏", combined):
        math_signals += 2
    if re.search(r"\b[A-Z]hat\b|Ĥ|ψ|φ|θ|λ|μ|σ|ω|ℏ", combined):
        math_signals += 1
    # Scientific notation (e = mc² style)
    if re.search(r"\w\^|\w_\{|\w_\w\b", combined):
        math_signals += 1

    raw = (steps * 0.07 + conds * 0.12 + depth_from_type * 0.30 + math_signals * 0.08)
    return min(raw, 1.0)


def _normalize_source_name(raw_name: str) -> str:
    """Normalize a source name for fuzzy matching against SOURCE_TRUST keys.

    Strips hyphens, underscores, and whitespace; lowercases; extracts the
    meaningful identifier portion so that e.g. 'open-web-math/open-web-math'
    matches the key 'openwebmath'.
    """
    return raw_name.lower().replace("-", "").replace("_", "").replace("/", "").replace(" ", "")


def _source_reliability(record: dict) -> float:
    """Extract source reliability score (0..1) from record metadata.

    Supports progressive matching:
      1. Exact lookup against SOURCE_TRUST keys.
      2. Normalized (hyphen/underscore/case-insensitive) lookup.
      3. Partial containment (any direction) after normalization.
      4. Fallback to 'other'.
    """
    source = record.get("source", {})
    if isinstance(source, str):
        source_name = source
    elif isinstance(source, dict):
        source_name = source.get("name", "other")
    else:
        source_name = "other"

    # 1. Direct lookup
    if source_name in SOURCE_TRUST:
        return SOURCE_TRUST[source_name]

    # 2. Normalized lookup
    normalized_name = _normalize_source_name(source_name)
    normalized_trust = {_normalize_source_name(k): v for k, v in SOURCE_TRUST.items()}

    if normalized_name in normalized_trust:
        return normalized_trust[normalized_name]

    # 3. Partial containment (safe: only match when one is fully contained in the other)
    for norm_key, trust in normalized_trust.items():
        if norm_key in normalized_name or normalized_name in norm_key:
            return trust

    # 4. Fallback
    return SOURCE_TRUST["other"]


def _domain_difficulty_offset(category: str) -> float:
    """Get base difficulty offset for a category."""
    return CATEGORY_DIFFICULTY_OFFSET.get(category, 0.0)


# ---------------------------------------------------------------------------
# Reasoning type detection
# ---------------------------------------------------------------------------

def _detect_reasoning_types(prompt: str, answer: str) -> list[str]:
    """Detect reasoning types present in the record, ordered by strength."""
    combined = prompt + " " + answer
    scores: dict[str, float] = {}

    for rtype, patterns in REASONING_PATTERNS.items():
        hits = 0
        for pat in patterns:
            hits += len(re.findall(pat, combined, re.I))
        scores[rtype] = hits

    # Normalise and threshold
    max_score = max(scores.values()) if scores else 0
    if max_score == 0:
        return ["factual"]

    result = [
        rtype for rtype, score in
        sorted(scores.items(), key=lambda x: -x[1])
        if score >= max(1, max_score * 0.3)
    ]
    return result[:4] if result else ["factual"]


# ---------------------------------------------------------------------------
# Skill domain detection
# ---------------------------------------------------------------------------

def _detect_skill_domains(prompt: str, answer: str, category: str) -> list[str]:
    """Detect skill domains from text content and category."""
    combined = (prompt + " " + answer).lower()

    # Direct category mapping
    category_to_domain = {
        "01_foundation": ["software_engineering", "ai_ml", "science"],
        "02_software_engineering": ["software_engineering"],
        "03_system_engineering": ["system_engineering"],
        "04_ai_machine_learning": ["ai_ml"],
        "05_hardware_engineering": ["system_engineering", "science"],
        "06_science_engineering": ["science"],
        "07_business_knowledge": ["business"],
        "08_creative_knowledge": ["creative"],
        "09_personal_assistant": ["software_engineering", "ai_ml"],
    }

    base_domains = category_to_domain.get(category, ["software_engineering"])

    # Check text for cross-domain signals
    domain_hits: dict[str, float] = {d: 0.5 for d in base_domains}
    for domain, vocab in TECHNICAL_VOCAB.items():
        hits = sum(1 for word in vocab if word in combined)
        if hits > 2:
            domain_hits[domain] = domain_hits.get(domain, 0.0) + min(hits / 5.0, 1.0)

    sorted_domains = sorted(domain_hits, key=lambda d: -domain_hits[d])
    return sorted_domains[:3]


# ---------------------------------------------------------------------------
# Difficulty level fusion
# ---------------------------------------------------------------------------

def _compute_difficulty(
    prompt_complexity: float,
    answer_complexity: float,
    tech_vocab_density: float,
    reasoning_depth: float,
    source_reliability: float,
    domain_offset: float,
    override_thresholds: list[tuple[float, int]] | None = None,
) -> tuple[int, float]:
    """
    Fuse all signals into a difficulty level (1..5) and confidence (0..1).

    Parameters
    ----------
    override_thresholds : optional list of (raw_score_threshold, level) pairs.
        When provided, this overrides the module-level LEVEL_THRESHOLDS for
        this call.  Used for A/B threshold calibration without global mutation.
    """
    thresholds = LEVEL_THRESHOLDS if override_thresholds is None else override_thresholds

    # Weighted raw score
    raw = (
        prompt_complexity * 0.15 +
        answer_complexity * 0.30 +
        tech_vocab_density * 0.18 +
        reasoning_depth * 0.30 +
        domain_offset * 0.07
    )

    raw = max(0.0, min(raw, 1.0))

    # Map to level using provided thresholds
    level = 1
    for threshold, lvl in thresholds:
        if raw >= threshold:
            level = lvl

    # Confidence: based on signal agreement, source reliability, and evidence volume
    signals = [prompt_complexity, answer_complexity, tech_vocab_density, reasoning_depth]
    mean_signal = sum(signals) / len(signals)
    variance = sum((s - mean_signal) ** 2 for s in signals) / len(signals)
    agreement = 1.0 - min(variance * 4.0, 1.0)  # low variance = high agreement

    # Boost confidence if source is reliable, penalise if low
    source_factor = source_reliability * 0.3 + 0.7

    # Evidence-volume factor: continuous ramp from 0.45 (minimal text) to 1.0 (rich text).
    # Replaces the old binary cutoff (has_content = 1.0 if mean_signal > 0.05 else 0.3)
    # which collapsed confidence on short-but-clear records.
    # The ramp uses prompt+answer complexity as a proxy for text volume:
    text_volume = prompt_complexity + answer_complexity
    evidence_factor = min(0.45 + text_volume * 2.0, 1.0)

    confidence = agreement * source_factor * evidence_factor
    confidence = max(0.0, min(confidence, 1.0))

    return level, round(confidence, 4)


def _generate_reason(level: int, prompt: str, answer: str, signals: dict[str, float]) -> str:
    """Generate a human-readable reason for the assigned level."""
    reasons = []
    level_names = {1: "basic", 2: "intermediate", 3: "advanced", 4: "expert", 5: "research"}

    if signals["prompt_complexity"] > 0.6:
        reasons.append("complex prompt")
    elif signals["prompt_complexity"] < 0.2:
        reasons.append("simple query")

    if signals["answer_complexity"] > 0.6:
        reasons.append("detailed answer")
    elif signals["answer_complexity"] < 0.2:
        reasons.append("short answer")

    if signals["tech_vocab_density"] > 0.4:
        reasons.append("technical vocabulary")

    if signals["reasoning_depth"] > 0.5:
        reasons.append("multi-step reasoning")
    elif signals["reasoning_depth"] < 0.2:
        reasons.append("single-step reasoning")

    if not reasons:
        reasons.append("insufficient evidence")

    return f"Level {level} ({level_names[level]}): {', '.join(reasons)}"


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_record(record: dict) -> dict | None:
    """
    Analyze a single dataset record and return intelligence metadata.

    Returns None if the record cannot be parsed (missing critical fields).
    """
    record_id = record.get("id")
    if not record_id:
        return None

    category = record.get("category", "01_foundation")
    messages = record.get("messages", [])
    if isinstance(record.get("content"), dict):
        # Some records use content dict instead of messages
        prompt = record["content"].get("question", "")
        answer = record["content"].get("answer", "")
    else:
        prompt, answer = _text_from_messages(messages)

    if not prompt and not answer:
        return None

    # --- Extract signals ---
    prompt_complexity = _prompt_complexity(prompt, answer)
    answer_complexity = _answer_complexity(answer)
    tech_vocab = _technical_vocabulary_density(prompt + " " + answer, category)
    reasoning_depth = _reasoning_depth(prompt, answer)
    source_rel = _source_reliability(record)
    domain_offset = _domain_difficulty_offset(category)

    # --- Detect types ---
    reasoning_types = _detect_reasoning_types(prompt, answer)
    skill_domains = _detect_skill_domains(prompt, answer, category)

    # --- Compute difficulty ---
    level, confidence = _compute_difficulty(
        prompt_complexity,
        answer_complexity,
        tech_vocab,
        reasoning_depth,
        source_rel,
        domain_offset,
    )

    signals = {
        "prompt_complexity": round(prompt_complexity, 4),
        "answer_complexity": round(answer_complexity, 4),
        "tech_vocab_density": round(tech_vocab, 4),
        "reasoning_depth": round(reasoning_depth, 4),
    }

    reason = _generate_reason(level, prompt, answer, signals)

    # --- Build output ---
    prompt_tokens = _estimate_tokens(prompt)
    answer_tokens = _estimate_tokens(answer)

    result = {
        "record_id": record_id,
        "difficulty": {
            "level": level,
            "confidence": confidence,
            "source": "classifier",
            "reason": reason,
        },
        "reasoning_types": reasoning_types,
        "skill_domains": skill_domains,
        "classified_at": datetime.now(timezone.utc).isoformat(),
        "classifier_version": CLASSIFIER_VERSION,
        "features": {
            "prompt_tokens": prompt_tokens,
            "answer_tokens": answer_tokens,
            "total_tokens": prompt_tokens + answer_tokens,
            "vocabulary_density": round(tech_vocab, 4),
            "reasoning_steps_estimate": max(
                1, int(reasoning_depth * 15)
            ),
            "code_fraction": round(
                len(re.findall(r"```", answer)) / max(len(answer.split()), 1) * 10,
                4,
            ),
            "cross_domain_flag": len(skill_domains) > 1,
        },
        "review_status": "unreviewed",
    }

    return result


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def process_file(
    input_path: Path,
    output_path: Path | None,
    sample_size: int | None = None,
    dry_run: bool = False,
) -> tuple[int, int, list[dict], list[dict]]:
    """
    Process a JSONL file of records.

    Returns (total, classified, results, errors).
    When dry_run=True, results are truncated to sample_size.
    """
    records: list[dict] = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"  [WARN] JSON parse error: {e}", file=sys.stderr)

    # Sample if requested (deterministic: first N)
    if sample_size and sample_size < len(records):
        records = records[:sample_size]

    results: list[dict] = []
    errors: list[dict] = []
    classified = 0

    for i, rec in enumerate(records):
        try:
            result = analyze_record(rec)
            if result:
                results.append(result)
                classified += 1
            else:
                errors.append({
                    "index": i,
                    "record_id": rec.get("id", "unknown"),
                    "error": "Could not parse record (missing content)",
                })
        except Exception as e:
            errors.append({
                "index": i,
                "record_id": rec.get("id", "unknown"),
                "error": str(e),
            })

    # Write output unless dry-run
    if output_path and not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for result in results:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(f"  Written {len(results)} classifications to {output_path}")

    return len(records), classified, results, errors


def process_file_range(
    input_path: Path,
    offset_start: int,
    offset_end: int,
    output_path: Path | None,
    dry_run: bool = False,
) -> tuple[int, int, list[dict], list[dict]]:
    """Process a line range [offset_start, offset_end) of a JSONL file.

    Streaming: opens the file once, skips offset_start lines, reads until
    offset_end (or EOF if offset_end < 0), classifies each record. The
    original file is never modified.

    Returns (total, classified, results, errors) like process_file().
    """
    records: list[dict] = []
    with open(input_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < offset_start:
                continue
            if offset_end >= 0 and i >= offset_end:
                break
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"  [WARN] JSON parse error: {e}", file=sys.stderr)

    results: list[dict] = []
    errors: list[dict] = []
    classified = 0

    for i, rec in enumerate(records):
        try:
            result = analyze_record(rec)
            if result:
                results.append(result)
                classified += 1
            else:
                errors.append({
                    "index": offset_start + i,
                    "record_id": rec.get("id", "unknown"),
                    "error": "Could not parse record (missing content)",
                })
        except Exception as e:
            errors.append({
                "index": offset_start + i,
                "record_id": rec.get("id", "unknown"),
                "error": str(e),
            })

    if output_path and not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for result in results:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")

    return len(records), classified, results, errors


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def _compute_distribution(results: list[dict]) -> dict[str, int]:
    dist: dict[str, int] = {str(i): 0 for i in range(1, 6)}
    for r in results:
        lvl = r["difficulty"]["level"]
        dist[str(lvl)] = dist.get(str(lvl), 0) + 1
    return dist


def _compute_confidence_stats(results: list[dict]) -> dict:
    confs = [r["difficulty"]["confidence"] for r in results]
    if not confs:
        return {"mean": 0, "min": 0, "max": 0, "low_confidence_count": 0}

    low_conf = [c for c in confs if c < 0.5]
    return {
        "mean": round(sum(confs) / len(confs), 4),
        "min": round(min(confs), 4),
        "max": round(max(confs), 4),
        "low_confidence_count": len(low_conf),
        "low_confidence_fraction": round(len(low_conf) / len(confs), 4),
    }


def _compute_type_distribution(results: list[dict]) -> dict[str, int]:
    type_counts: dict[str, int] = {}
    for r in results:
        for rt in r.get("reasoning_types", []):
            type_counts[rt] = type_counts.get(rt, 0) + 1
    return dict(sorted(type_counts.items(), key=lambda x: -x[1]))


def _compute_domain_distribution(results: list[dict]) -> dict[str, int]:
    domain_counts: dict[str, int] = {}
    for r in results:
        for sd in r.get("skill_domains", []):
            domain_counts[sd] = domain_counts.get(sd, 0) + 1
    return dict(sorted(domain_counts.items(), key=lambda x: -x[1]))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Atlas Difficulty Classification Engine v1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --input-file records.jsonl --output-file classified.jsonl\n"
            "  %(prog)s --input-file records.jsonl --dry-run --sample-size 500\n"
        ),
    )
    parser.add_argument(
        "--input-file", "-i",
        type=str,
        required=True,
        help="Path to JSONL file of dataset records.",
    )
    parser.add_argument(
        "--output-file", "-o",
        type=str,
        default=None,
        help="Path to write classified intelligence metadata (JSONL).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run analysis but do NOT write output. Prints summary only.",
    )
    parser.add_argument(
        "--sample-size", "-n",
        type=int,
        default=None,
        help="Process only the first N records (deterministic).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        return 1

    output_path = Path(args.output_file) if args.output_file else None

    print(f"Atlas Difficulty Classifier v{CLASSIFIER_VERSION}")
    print(f"  Input:   {input_path}")
    print(f"  Output:  {output_path or '(stdout summary only)'}")
    print(f"  Dry-run: {args.dry_run}")
    if args.sample_size:
        print(f"  Sample:  {args.sample_size} records")
    print()

    total, classified, results, errors = process_file(
        input_path=input_path,
        output_path=output_path,
        sample_size=args.sample_size,
        dry_run=args.dry_run,
    )

    # --- Summary ---
    print("--- Results ---")
    print(f"  Total records processed: {total}")
    print(f"  Successfully classified:  {classified}")
    print(f"  Errors / skipped:         {len(errors)}")

    if results:
        dist = _compute_distribution(results)
        print(f"\n  Difficulty distribution:")
        for lvl in sorted(dist.keys()):
            count = dist[lvl]
            pct = count / len(results) * 100
            print(f"    Level {lvl}: {count:>6} ({pct:5.1f}%)")

        conf_stats = _compute_confidence_stats(results)
        print(f"\n  Confidence: mean={conf_stats['mean']:.3f}, "
              f"min={conf_stats['min']:.3f}, max={conf_stats['max']:.3f}")
        print(f"  Low-confidence samples: {conf_stats['low_confidence_count']} "
              f"({conf_stats['low_confidence_fraction']*100:.1f}%)")

        type_dist = _compute_type_distribution(results)
        print(f"\n  Reasoning types (top):")
        for rt, cnt in list(type_dist.items())[:5]:
            print(f"    {rt}: {cnt}")

        domain_dist = _compute_domain_distribution(results)
        print(f"\n  Skill domains (top):")
        for sd, cnt in list(domain_dist.items())[:5]:
            print(f"    {sd}: {cnt}")

    if errors:
        print(f"\n  Errors:")
        for err in errors[:10]:
            print(f"    [{err['index']}] {err['record_id']}: {err['error']}")
        if len(errors) > 10:
            print(f"    ... and {len(errors) - 10} more")

    print(f"\n--- {'DRY RUN' if args.dry_run else 'Done'} ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
