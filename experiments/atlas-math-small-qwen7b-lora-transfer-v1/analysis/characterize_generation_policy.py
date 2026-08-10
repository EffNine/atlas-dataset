#!/usr/bin/env python3
"""
characterize_generation_policy.py — P8-A.2 output-policy characterization.

READ-ONLY on inputs; writes analysis/patterns/generation_policy.json.
No training, no dataset/QEE modification.

Characterizes the generation policy of the Phase 6.3 baseline (base model)
versus the P8-A math-trained adapter on the same 100 code_eval_v1 records,
using the frozen per-example predictions (no new inference).

Signals per response:
  kind            patch | fenced_code | code_tokens | pure_prose
  is_patch        response contains a unified diff marker
  has_fence       response contains a ``` code fence
  has_code_tokens response contains code-like tokens
  tokens          tokens_generated
  truncated       tokens_generated >= max_new_tokens (the eval cap = 512)
  stop_reason     'max_length' if truncated else 'eos'
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EXP = REPO / "experiments" / "atlas-math-small-qwen7b-lora-transfer-v1"
POST_EXAMPLE = EXP / "evaluation" / "post_training_per_example.jsonl"
BASE_EXAMPLE = REPO / "experiments" / "phase6_baseline_eval" / "per_example_results.jsonl"
OUT_DIR = EXP / "analysis" / "patterns"

MAX_NEW_TOKENS = 512

DIFF_RE = re.compile(r"(?m)^(diff --git |--- a/|\+\+\+ b/|@@ )")
CODE_RE = re.compile(r"\b(def |class |import |return |function |print\()")


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def classify(text: str) -> dict:
    is_diff = bool(DIFF_RE.search(text or ""))
    has_fence = "```" in (text or "")
    has_code = bool(CODE_RE.search(text or ""))
    if is_diff:
        kind = "patch"
    elif has_fence and has_code:
        kind = "fenced_code"
    elif has_fence:
        kind = "fence_only"
    elif has_code:
        kind = "code_tokens"
    else:
        kind = "pure_prose"
    return {"is_patch": is_diff, "has_fence": has_fence,
            "has_code_tokens": has_code, "kind": kind}


def characterize(rows: list[dict], label: str) -> dict:
    kinds = Counter()
    patches = 0
    truncated = 0
    toks = []
    for r in rows:
        text = r.get("predicted_response") or ""
        sig = classify(text)
        kinds[sig["kind"]] += 1
        patches += int(sig["is_patch"])
        t = r.get("tokens_generated") or 0
        toks.append(t)
        truncated += int(t >= MAX_NEW_TOKENS)
    n = len(rows) or 1
    return {
        "label": label,
        "n": len(rows),
        "max_new_tokens": MAX_NEW_TOKENS,
        "kinds": dict(sorted(kinds.items())),
        "patch_emission_rate": round(patches / n, 4),
        "prose_rate": round(kinds["pure_prose"] / n, 4),
        "fenced_code_rate": round((kinds["fenced_code"] + kinds["fence_only"]) / n, 4),
        "token_length": {
            "mean": round(statistics.mean(toks), 1),
            "median": round(statistics.median(toks), 1),
            "min": min(toks), "max": max(toks),
        },
        "truncation_rate": round(truncated / n, 4),
        "truncated_count": truncated,
        "stop_reason": {
            "eos": n - truncated,
            "max_length": truncated,
        },
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    post = load_jsonl(POST_EXAMPLE)
    base = [r for r in load_jsonl(BASE_EXAMPLE) if r.get("view_id") == "code-300m"]

    result = {
        "experiment_id": "atlas-math-small-qwen7b-lora-transfer-v1",
        "phase": "8", "sprint": "P8-A.2",
        "eval_split": "evaluation/eval_sets/phase6_expansion_v1/code_eval_v1.jsonl",
        "n": len(post),
        "note": ("Characterization of EXISTING frozen per-example predictions. "
                 "The eval prompt template rendered the record messages, which "
                 "include the gold assistant solution, then added an empty "
                 "assistant turn (reference-in-prompt)."),
        "baseline": characterize(base, "baseline"),
        "post_training": characterize(post, "post_training"),
    }
    out = OUT_DIR / "generation_policy.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
