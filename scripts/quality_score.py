#!/usr/bin/env python3
"""
quality_score.py — Atlas heuristic quality scorer (1-10).

Computes a weighted score across seven dimensions defined in docs/quality_standard.md:
  accuracy(0.20), completeness(0.15), technical_correctness(0.20), clarity(0.15),
  usefulness(0.15), originality(0.05), relevance(0.10).

This is a *heuristic* estimator to triage large batches. It is NOT a substitute
for human review. Final acceptance still requires a human setting verified=true.

Heuristics are intentionally simple and dependency-free:
  * completeness: assistant length + presence of structure (lists/steps/code).
  * clarity: sentence/paragraph structure, no ALLCAPS spam, balanced length.
  * usefulness: addresses an imperative question; contains actionable content.
  * originality: low boilerplate ratio (not a generic template opener).
  * relevance: category keyword appears in content or tags.
  * accuracy / technical_correctness: lexical-sanity + code-block balance
    (heuristic; real verification is human).

Usage:
  python scripts/quality_score.py --input examples/sample_dataset.jsonl
  python scripts/quality_score.py --input tmp/cleaned.jsonl --write  # update quality_score in place
  python scripts/quality_score.py --input tmp/cleaned.jsonl --threshold 7  # list rejects
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

WEIGHTS = {
    "accuracy": 0.20,
    "completeness": 0.15,
    "technical_correctness": 0.20,
    "clarity": 0.15,
    "usefulness": 0.15,
    "originality": 0.05,
    "relevance": 0.10,
}

CATEGORY_KEYWORDS = {
    "01_foundation": ["reason", "explain", "step", "because", "therefore", "decision"],
    "02_software_engineering": ["function", "code", "bug", "class", "algorithm", "refactor", "test"],
    "03_system_engineering": ["linux", "docker", "kubernetes", "network", "kernel", "server", "port"],
    "04_ai_machine_learning": ["model", "loss", "transformer", "prompt", "rag", "token", "embedding"],
    "05_hardware_engineering": ["cpu", "gpu", "firmware", "voltage", "clock", "benchmark", "pcb"],
    "06_science_engineering": ["equation", "theorem", "integral", "force", "circuit", "matrix"],
    "07_business_knowledge": ["revenue", "strategy", "market", "profit", "roi", "stakeholder"],
    "08_creative_knowledge": ["story", "character", "metaphor", "narrative", "design", "tone"],
    "09_personal_assistant": ["schedule", "plan", "task", "prioritize", "workflow", "reminder"],
}

BOILERPLATE_OPENERS = [
    "sure,", "here is", "here's", "as an ai", "i'm happy to", "certainly,", "of course,",
]

CODE_FENCE_RE = re.compile(r"```")
URL_RE = re.compile(r"https?://")
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
ALLCAPS_RE = re.compile(r"\b[A-Z]{4,}\b")


def assistant_text(rec: dict) -> str:
    return "\n".join(m["content"] for m in rec.get("messages", []) if m["role"] == "assistant")


def user_text(rec: dict) -> str:
    return "\n".join(m["content"] for m in rec.get("messages", []) if m["role"] == "user")


def score_completeness(text: str) -> float:
    n = len(text)
    if n < 50:
        return 0.2
    if n < 200:
        return 0.5
    if n < 600:
        return 0.75
    base = 0.85
    # structure bonus
    if re.search(r"(?m)^\s*[-*\d.]\s+", text):
        base += 0.08
    if CODE_FENCE_RE.search(text):
        base += 0.07
    return min(1.0, base)


def score_clarity(text: str) -> float:
    sents = [s for s in SENT_SPLIT_RE.split(text) if s.strip()]
    if not sents:
        return 0.2
    avg = sum(len(s.split()) for s in sents) / len(sents)
    # ideal avg sentence length 8-25 words
    if 8 <= avg <= 25:
        base = 0.9
    elif 4 <= avg < 8 or 25 < avg <= 40:
        base = 0.65
    else:
        base = 0.4
    # penalize ALLCAPS spam
    caps = len(ALLCAPS_RE.findall(text))
    if caps > 3:
        base -= 0.15
    return max(0.1, min(1.0, base))


def score_usefulness(user: str, asst: str) -> float:
    # imperative user question + actionable answer
    action_verbs = ["how", "what", "why", "write", "create", "fix", "explain", "design", "implement", "solve"]
    u = user.lower()
    asks = any(u.startswith(v) or f" {v} " in f" {u}" for v in action_verbs)
    actionable = bool(re.search(r"(?m)^\s*[-*\d.]\s+", asst)) or CODE_FENCE_RE.search(asst) or len(asst) > 200
    if asks and actionable:
        return 0.9
    if asks or actionable:
        return 0.65
    return 0.4


def score_originality(text: str) -> float:
    low = text.lower().strip()
    for b in BOILERPLATE_OPENERS:
        if low.startswith(b):
            return 0.4
    # generic-length penalty
    if len(text) < 80:
        return 0.5
    return 0.85


def score_relevance(rec: dict) -> float:
    cat = rec.get("category", "")
    kws = CATEGORY_KEYWORDS.get(cat, [])
    blob = (assistant_text(rec) + " " + user_text(rec) + " " + " ".join(rec.get("tags", []))).lower()
    hits = sum(1 for k in kws if k in blob)
    if hits == 0:
        return 0.4
    if hits == 1:
        return 0.7
    return 0.95


def score_technical(asst: str) -> float:
    # heuristic: code blocks should be balanced and not dangling
    fences = CODE_FENCE_RE.findall(asst)
    if fences and len(fences) % 2 != 0:
        return 0.4  # unclosed code block
    # presence of numbers/identifiers suggests specific content
    has_spec = bool(re.search(r"\b\d+(\.\d+)?\b", asst))
    return 0.85 if (has_spec or fences) else 0.6


def score_accuracy(asst: str) -> float:
    # lexical sanity; extreme length without structure is suspect
    if URL_RE.search(asst):
        return 0.8  # cites sources
    if len(asst) < 30:
        return 0.4
    return 0.75


def score_record(rec: dict) -> tuple[int, dict]:
    asst = assistant_text(rec)
    user = user_text(rec)
    dims = {
        "accuracy": score_accuracy(asst),
        "completeness": score_completeness(asst),
        "technical_correctness": score_technical(asst),
        "clarity": score_clarity(asst),
        "usefulness": score_usefulness(user, asst),
        "originality": score_originality(asst),
        "relevance": score_relevance(rec),
    }
    raw = sum(dims[k] * WEIGHTS[k] for k in WEIGHTS)
    # map 0..1 -> 1..10
    scaled = 1 + round(raw * 9)
    scaled = max(1, min(10, scaled))
    return scaled, dims


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Heuristic quality scorer for Atlas records.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--write", action="store_true", help="write computed quality_score back into the file")
    ap.add_argument("--threshold", type=int, default=0, help="if >0, list records scoring below it")
    ap.add_argument("--explain", type=int, default=0, help="print dimension breakdown for first N records")
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
        s, dims = score_record(rec)
        results.append((rec, s, dims))

    total = len(results)
    scores = [s for _, s, _ in results]
    avg = sum(scores) / total if total else 0
    dist = {}
    for s in scores:
        dist[s] = dist.get(s, 0) + 1

    print(f"[quality] total={total} avg={avg:.2f}")
    print(f"[quality] distribution: " + ", ".join(f"{k}:{dist[k]}" for k in sorted(dist)))

    rejects = [(rec, s) for rec, s, _ in results if s < args.threshold] if args.threshold else []
    if rejects:
        print(f"\n[quality] records below threshold {args.threshold}:")
        for rec, s in rejects:
            print(f"  {rec.get('id')}: {s}")

    if args.explain:
        for rec, s, dims in results[:args.explain]:
            print(f"\n{rec.get('id')} -> {s}")
            for k, v in dims.items():
                print(f"    {k:22s} {v:.2f}")

    if args.write:
        out_path = path
        with out_path.open("w", encoding="utf-8") as f:
            for rec, s, _ in results:
                rec["quality_score"] = s
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[quality] wrote scores back to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
