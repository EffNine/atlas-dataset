#!/usr/bin/env python3
"""
quality_score.py — Atlas Quality Evaluation Engine (QEE).

Replaces the original single-pass heuristic "constant-7" scorer with an
*explainable, multi-dimensional* evaluation engine that:

  1. Produces MEANINGFUL SCORE VARIANCE. Each of the seven Atlas quality
     dimensions (accuracy, completeness, technical_correctness, clarity,
     usefulness, originality, relevance) is scored independently on a 0..1
     scale from transparent, dependency-free linguistic / metadata signals,
     then combined by the published WEIGHTS into a 1..10 integer quality_score.
     Unlike the prior scorer (which collapsed every record to 7.0), the QEE
     differentiates records so that correlation with human review is measurable.

  2. SEPARATES CONFIDENCE from the score. `confidence` (0..1) and
     `confidence_level` (1..5) reflect how much *evidence* the engine had to
     judge the record (text richness, metadata source_confidence, relevance
     signal, structural richness). It deliberately does NOT enter the score, so
     a low-confidence record is not silently scored lower or higher.

  3. EMITS A TRANSPARENT RATIONALE. `evaluate_record()` returns a per-dimension
     breakdown with a human-readable reason for each score, plus an overall
     one-line explanation and a list of boolean `flags`. This is what makes the
     engine auditable for calibration and human review.

Public contract (unchanged, so calibrate_quality.py / gen_calibration_sample.py
/ freeze_calibration_baseline.py keep working):
  * WEIGHTS : dict[dimension] -> float  (sums to 1.0)
  * score_record(rec) -> (int quality_score, dict[dimension]->0..1 float)

New primary API:
  * evaluate_record(rec) -> dict with keys:
        quality_score (int 1..10), quality_continuous (float 0..1),
        dimensions (dict dim->0..1), confidence (float 0..1),
        confidence_level (int 1..5), rationale (list of {dimension,score,reason}),
        flags (list[str]), explanation (str)

Design invariants:
  * Stdlib-only (no pip installs).
  * Deterministic & pure: same record -> same result, no randomness, no network.
  * READ-ONLY on records: never mutates its input.
  * Tolerant of missing/partial records (used by clean/validate stages).

Usage:
  python scripts/quality_score.py --input examples/sample_dataset.jsonl
  python scripts/quality_score.py --input tmp/cleaned.jsonl --write  # update quality_score in place
  python scripts/quality_score.py --input curated/v0.1/pilot_candidates.jsonl --explain 3
  python scripts/quality_score.py --input curated/v0.1/pilot_candidates.jsonl --rationale 2
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Published weights (schemas/quality_review_schema.json dimension_scores mirror
# these keys exactly). Kept identical to the prior scorer for schema stability.
# --------------------------------------------------------------------------- #
WEIGHTS = {
    "accuracy": 0.20,
    "completeness": 0.15,
    "technical_correctness": 0.20,
    "clarity": 0.15,
    "usefulness": 0.15,
    "originality": 0.05,
    "relevance": 0.10,
}

# Category keyword signals used by the relevance + technical dimensions.
CATEGORY_KEYWORDS = {
    "01_foundation": ["reason", "explain", "step", "because", "therefore", "decision", "why", "principle"],
    "02_software_engineering": ["function", "code", "bug", "class", "algorithm", "refactor", "test", "variable", "api"],
    "03_system_engineering": ["linux", "docker", "kubernetes", "network", "kernel", "server", "port", "process", "config"],
    "04_ai_machine_learning": ["model", "loss", "transformer", "prompt", "rag", "token", "embedding", "training", "inference"],
    "05_hardware_engineering": ["cpu", "gpu", "firmware", "voltage", "clock", "benchmark", "pcb", "circuit", "memory"],
    "06_science_engineering": ["equation", "theorem", "integral", "force", "circuit", "matrix", "energy", "formula"],
    "07_business_knowledge": ["revenue", "strategy", "market", "profit", "roi", "stakeholder", "cost", "risk"],
    "08_creative_knowledge": ["story", "character", "metaphor", "narrative", "design", "tone", "voice", "theme"],
    "09_personal_assistant": ["schedule", "plan", "task", "prioritize", "workflow", "reminder", "goal", "habit"],
}

BOILERPLATE_OPENERS = [
    "sure,", "here is", "here's", "as an ai", "i'm happy to", "certainly,", "of course,",
]

CODE_FENCE_RE = re.compile(r"```")
URL_RE = re.compile(r"https?://")
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
ALLCAPS_RE = re.compile(r"\b[A-Z]{4,}\b")
DIGIT_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
ENUM_RE = re.compile(r"(?m)(^\s*[-*]\s+|^\s*\d+\.\s+)")
WHITESPACE_RE = re.compile(r"\s+")


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# --------------------------------------------------------------------------- #
# Text extraction helpers (tolerant of missing fields)
# --------------------------------------------------------------------------- #
def assistant_text(rec: dict) -> str:
    return "\n".join(m["content"] for m in rec.get("messages", []) if m.get("role") == "assistant")


def user_text(rec: dict) -> str:
    return "\n".join(m["content"] for m in rec.get("messages", []) if m.get("role") == "user")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT_RE.split(text) if s.strip()]


def _avg_sentence_words(text: str) -> float:
    sents = _sentences(text)
    if not sents:
        return 0.0
    return sum(len(s.split()) for s in sents) / len(sents)


# --------------------------------------------------------------------------- #
# Dimension scorers — each returns a 0..1 float plus a reason string.
# They are deliberately simple, dependency-free, and explainable.
# --------------------------------------------------------------------------- #
def dim_completeness(asst: str) -> tuple[float, str]:
    """Coverage of the question. Driven mainly by substantive answer length
    (word count), with a diminishing-returns curve and a small multi-sentence
    bonus (an answer that develops more than one sentence shows elaboration)."""
    words = len(asst.split())
    if words == 0:
        return 0.1, "empty answer"
    # Ideal band ~16+ words for an instruction answer; saturates near 28.
    base = _clamp(words / 26.0)
    sents = _sentences(asst)
    if len(sents) >= 2:
        base = min(1.0, base + 0.06)  # elaboration bonus
    reason = f"answer {words} words across {len(sents)} sentence(s); graded for substance"
    return round(base, 3), reason


def dim_clarity(asst: str) -> tuple[float, str]:
    """Unambiguous, well-structured writing. Penalizes ALLCAPS spam and extreme
    sentence lengths; rewards a balanced average sentence length."""
    sents = _sentences(asst)
    if not sents:
        return 0.2, "no sentences"
    avg = _avg_sentence_words(asst)
    if 8 <= avg <= 25:
        base = 0.92
    elif 4 <= avg < 8 or 25 < avg <= 40:
        base = 0.7
    else:
        base = 0.45
    caps = len(ALLCAPS_RE.findall(asst))
    if caps > 3:
        base -= 0.15
    base = max(0.1, min(1.0, base))
    return round(base, 3), f"avg sentence {avg:.0f} words, ALLCAPS spikes={caps}"


def dim_usefulness(user: str, asst: str) -> tuple[float, str]:
    """Genuinely helps a real user/task. Combines an imperative/question user
    turn with substantive, actionable answer content."""
    action_verbs = ["how", "what", "why", "write", "create", "fix", "explain",
                    "design", "implement", "solve", "when", "should", "best"]
    u = f" {user.lower()} "
    asks = any(u.startswith(v) or f" {v} " in u for v in action_verbs)
    actionable = bool(ENUM_RE.search(asst)) or CODE_FENCE_RE.search(asst) or len(asst.split()) >= 12
    words = len(asst.split())
    if asks and actionable:
        base = 0.9
    elif asks or actionable:
        base = 0.7
    else:
        base = 0.45
    # substance nudge: very short answers are less useful regardless
    if words < 8:
        base = max(0.3, base - 0.2)
    return round(base, 3), f"user_imperative={asks}, actionable={actionable}, {words} words"


def dim_technical(asst: str, rec: dict) -> tuple[float, str]:
    """Domain / code / math correctness signal. For code-bearing answers,
    checks balanced fences; for conceptual answers, rewards lexical specificity
    (numbers, technical terms, category keywords)."""
    fences = CODE_FENCE_RE.findall(asst)
    if fences and len(fences) % 2 != 0:
        return 0.4, "unclosed code fence"
    cat = rec.get("category", "")
    kws = CATEGORY_KEYWORDS.get(cat, [])
    blob = (asst + " " + " ".join(rec.get("tags", []))).lower()
    hits = sum(1 for k in kws if k in blob)
    has_spec = bool(DIGIT_RE.search(asst))
    # code present -> high; otherwise specificity from digits + keyword hits
    if fences:
        return 0.9, "code block present and balanced"
    base = 0.55 + 0.05 * min(hits, 4) + (0.1 if has_spec else 0.0)
    return round(min(1.0, base), 3), f"category_keyword_hits={hits}, has_specific_values={has_spec}"


def dim_accuracy(asst: str, rec: dict) -> tuple[float, str]:
    """Factual-correctness proxy. Lexical sanity: not too short (a one-liner is
    often incomplete rather than wrong), cites sources when URLs present, and
    answers with concrete specifics are trusted more than vague ones."""
    if len(asst) < 30:
        return 0.45, "answer very short; insufficient to judge correctness"
    if URL_RE.search(asst):
        return 0.82, "cites external source"
    # specificity proxy: presence of digits / category terms suggests grounded content
    cat = rec.get("category", "")
    kws = CATEGORY_KEYWORDS.get(cat, [])
    blob = asst.lower()
    hits = sum(1 for k in kws if k in blob)
    spec = bool(DIGIT_RE.search(asst))
    base = 0.72 + 0.04 * min(hits, 3) + (0.06 if spec else 0.0)
    return round(min(0.95, base), 3), f"len={len(asst)}, keyword_hits={hits}, specific={spec}"


def dim_originality(asst: str) -> tuple[float, str]:
    """Not a generic / boilerplate response. Penalizes stock openers and
    ultra-short generic replies; otherwise treats authored content as original."""
    low = asst.lower().strip()
    for b in BOILERPLATE_OPENERS:
        if low.startswith(b):
            return 0.4, f"boilerplate opener '{b.strip()}'"
    if len(asst) < 25:
        return 0.55, "very short / generic-length reply"
    return 0.85, "no boilerplate; authored content"


def dim_relevance(rec: dict) -> tuple[float, str]:
    """On-topic for its category / subcategory. Keyword hits in the answer,
    user question, and tags; subcategory term presence is an extra signal."""
    cat = rec.get("category", "")
    kws = CATEGORY_KEYWORDS.get(cat, [])
    blob = (assistant_text(rec) + " " + user_text(rec) + " " +
            " ".join(rec.get("tags", []))).lower()
    hits = sum(1 for k in kws if k in blob)
    sub = (rec.get("subcategory") or "").lower().replace("_", " ")
    sub_hit = sub and sub in blob
    if hits == 0 and not sub_hit:
        return 0.4, f"no '{cat}' keyword signals found"
    if hits >= 2 or (hits >= 1 and sub_hit):
        return 0.95, f"{hits} keyword hit(s), subcategory_match={sub_hit}"
    return 0.7, f"{hits} keyword hit(s), subcategory_match={sub_hit}"


# --------------------------------------------------------------------------- #
# Confidence model (SEPARATE from the score)
# --------------------------------------------------------------------------- #
def score_confidence(rec: dict, dims: dict[str, float]) -> tuple[float, int]:
    """Estimate how much EVIDENCE the engine had to judge this record.

    Confidence is a function of signal richness, NOT the quality itself:
      * text richness   — enough words to evaluate substance
      * source metadata — source_confidence (high/medium/low)
      * relevance signal— category keywords present (engine can ground judgment)
      * structural richness — multi-sentence / enumerated content
      * specificity      — presence of concrete values / terms
    Returns (confidence 0..1, confidence_level 1..5).
    """
    asst = assistant_text(rec)
    words = len(asst.split())
    # text richness saturates ~24 words
    richness = _clamp(words / 24.0)

    meta = rec.get("metadata", {}) or {}
    src_conf = meta.get("source_confidence", "high")
    src_map = {"high": 1.0, "medium": 0.7, "low": 0.4}
    src = src_map.get(str(src_conf).lower(), 0.7)

    rel = dims.get("relevance", 0.0)
    struct = min(1.0, 0.5 * len(_sentences(asst)) + (0.5 if ENUM_RE.search(asst) else 0.0))
    spec = 0.6 if (DIGIT_RE.search(asst) or CODE_FENCE_RE.search(asst)) else 0.3

    # weighted evidence combination (not the quality score)
    conf = 0.30 * richness + 0.25 * src + 0.20 * rel + 0.15 * struct + 0.10 * spec
    conf = round(_clamp(conf), 3)
    level = int(round(1 + conf * 4))
    level = max(1, min(5, level))
    return conf, level


# --------------------------------------------------------------------------- #
# Rationale assembly
# --------------------------------------------------------------------------- #
def _rationale_for(dimension: str, value: float, reason: str) -> dict:
    band = ("strong" if value >= 0.8 else "adequate" if value >= 0.6
            else "weak" if value >= 0.4 else "poor")
    return {"dimension": dimension, "score": round(value, 3), "band": band,
            "reason": reason}


# --------------------------------------------------------------------------- #
# Primary evaluation API
# --------------------------------------------------------------------------- #
def evaluate_record(rec: dict) -> dict:
    """Explainable evaluation. Returns the full result dict (see module docstring)."""
    asst = assistant_text(rec)
    user = user_text(rec)

    dims = {
        "accuracy": dim_accuracy(asst, rec)[0],
        "completeness": dim_completeness(asst)[0],
        "technical_correctness": dim_technical(asst, rec)[0],
        "clarity": dim_clarity(asst)[0],
        "usefulness": dim_usefulness(user, asst)[0],
        "originality": dim_originality(asst)[0],
        "relevance": dim_relevance(rec)[0],
    }

    # store reasons too (kept out of `dimensions` which must be pure 0..1)
    reasons = {
        "accuracy": dim_accuracy(asst, rec)[1],
        "completeness": dim_completeness(asst)[1],
        "technical_correctness": dim_technical(asst, rec)[1],
        "clarity": dim_clarity(asst)[1],
        "usefulness": dim_usefulness(user, asst)[1],
        "originality": dim_originality(asst)[1],
        "relevance": dim_relevance(rec)[1],
    }

    quality_continuous = sum(dims[k] * WEIGHTS[k] for k in WEIGHTS)
    quality_score = int(max(1, min(10, round(1 + quality_continuous * 9))))

    confidence, confidence_level = score_confidence(rec, dims)

    # flags
    flags: list[str] = []
    if len(asst.split()) < 8:
        flags.append("very_short_answer")
    if dims["relevance"] < 0.5:
        flags.append("low_relevance")
    if confidence < 0.5:
        flags.append("low_confidence")
    if any(asst.lower().strip().startswith(b) for b in BOILERPLATE_OPENERS):
        flags.append("boilerplate_opener")
    if CODE_FENCE_RE.findall(asst) and len(CODE_FENCE_RE.findall(asst)) % 2 != 0:
        flags.append("unclosed_code_fence")

    rationale = [_rationale_for(k, dims[k], reasons[k]) for k in WEIGHTS]

    top_dim = max(dims, key=lambda k: dims[k])
    low_dim = min(dims, key=lambda k: dims[k])
    explanation = (
        f"quality_score={quality_score} (continuous={quality_continuous:.2f}); "
        f"strongest='{top_dim}' ({dims[top_dim]:.2f}), "
        f"weakest='{low_dim}' ({dims[low_dim]:.2f}); "
        f"confidence={confidence:.2f} (level {confidence_level}/5)"
        + ("" if not flags else f"; flags={flags}")
    )

    return {
        "quality_score": quality_score,
        "quality_continuous": round(quality_continuous, 4),
        "dimensions": {k: round(v, 3) for k, v in dims.items()},
        "confidence": confidence,
        "confidence_level": confidence_level,
        "rationale": rationale,
        "flags": flags,
        "explanation": explanation,
    }


def score_record(rec: dict) -> tuple[int, dict]:
    """Backward-compatible API: (int quality_score, {dim: 0..1 float}).

    Used by calibrate_quality.py, gen_calibration_sample.py,
    freeze_calibration_baseline.py, and tests.
    """
    ev = evaluate_record(rec)
    return ev["quality_score"], ev["dimensions"]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Atlas Quality Evaluation Engine.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--write", action="store_true", help="write computed quality_score back into the file")
    ap.add_argument("--threshold", type=int, default=0, help="if >0, list records scoring below it")
    ap.add_argument("--explain", type=int, default=0, help="print dimension breakdown for first N records")
    ap.add_argument("--rationale", type=int, default=0, help="print full rationale for first N records")
    args = ap.parse_args(argv)

    path = Path(args.input)
    if not path.exists():
        print(f"[quality] ERROR: input not found: {path}", file=sys.stderr)
        return 2

    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    results = []
    for rec in records:
        ev = evaluate_record(rec)
        results.append((rec, ev))

    total = len(results)
    scores = [ev["quality_score"] for _, ev in results]
    avg = sum(scores) / total if total else 0
    dist = {}
    for s in scores:
        dist[s] = dist.get(s, 0) + 1
    confs = [ev["confidence"] for _, ev in results]
    avg_conf = sum(confs) / total if total else 0

    print(f"[quality] total={total} avg={avg:.2f} avg_confidence={avg_conf:.2f}")
    print(f"[quality] distribution: " + ", ".join(f"{k}:{dist[k]}" for k in sorted(dist)))

    rejects = [(rec, ev) for rec, ev in results if ev["quality_score"] < args.threshold] if args.threshold else []
    if rejects:
        print(f"\n[quality] records below threshold {args.threshold}:")
        for rec, ev in rejects:
            print(f"  {rec.get('id')}: {ev['quality_score']} (conf={ev['confidence']:.2f})")

    if args.explain:
        for rec, ev in results[:args.explain]:
            print(f"\n{rec.get('id')} -> {ev['quality_score']} (conf={ev['confidence']:.2f})")
            for k, v in ev["dimensions"].items():
                print(f"    {k:22s} {v:.2f}")

    if args.rationale:
        for rec, ev in results[:args.rationale]:
            print(f"\n=== {rec.get('id')} -> quality_score={ev['quality_score']} "
                  f"confidence={ev['confidence']:.2f} (level {ev['confidence_level']}/5) ===")
            for r in ev["rationale"]:
                print(f"    {r['dimension']:22s} {r['score']:.2f} [{r['band']}]  {r['reason']}")
            print(f"    flags: {ev['flags']}")
            print(f"    -> {ev['explanation']}")

    if args.write:
        out_path = path
        with out_path.open("w", encoding="utf-8") as f:
            for rec, ev in results:
                rec["quality_score"] = ev["quality_score"]
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[quality] wrote scores back to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
