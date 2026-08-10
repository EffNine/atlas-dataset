#!/usr/bin/env python3
"""math_metric_audit.py — Math correctness failure audit (read-only).

Audits the 39 math records from the Protocol v2 baseline that scored 0.0 via
the frozen QEE v2 ``unparsable`` path (plus all other failed records) to
determine whether each failure is caused by a small set of
normalization/extraction issues or by a genuine model error.

Method (deterministic, offline, stdlib-only):
  * Loads the frozen v2 baseline per-example output + the eval records.
  * For every candidate extracted by the frozen extractor, applies an ordered
    cascade of PURELY SYNTACTIC normalizations (no math, no scoring-semantics
    change) and re-checks equivalence with the frozen ``expressions_equivalent``
    on the frozen extracted reference. The first transform (if any) that makes
    the pair equivalent labels the record "syntactic-recoverable".
  * Non-recovered records are examined against the response tail to distinguish
    extraction mis-targeting from genuine wrong answers.

This script does NOT modify the evaluator, the eval sets, or Protocol v2.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

PEX = REPO / "experiments" / "atlas-mixed-pilot-qwen7b-eval-v2" / "per_example_math.jsonl"
EVAL = REPO / "evaluation" / "eval_sets" / "protocol_v2" / "math_eval_v2.jsonl"
OUT = REPO / "experiments" / "atlas-mixed-pilot-qwen7b-eval-v2" / "math_metric_audit.json"

from evaluation_engine.v2.math_eval import expressions_equivalent, extract_final_answer


# --------------------------------------------------------------------------- #
# Syntactic-normalization cascade (robustness-only; no math-semantics change)
# --------------------------------------------------------------------------- #
def _strip_text_commands(text: str) -> str:
    """Drop \\text{...}/\\mathrm{...}/... human-text content (scaffolding)."""
    return re.sub(
        r"\\(?:text|mathrm|mathbf|mathit|textrm|textup|operatorname|mbox|textnormal)"
        r"\s*\{[^{}]*\}",
        "", text,
    )


def _strip_delim_residue(text: str) -> str:
    """Remove inline/display delimiters and the stray backslash they leave
    behind (e.g. ``\\$2880 \\]`` -> ``2880``), plus invisible ``\\left.``."""
    out = text
    out = out.replace("\\(", "").replace("\\)", "")
    out = out.replace("\\[", "").replace("\\]", "")
    out = re.sub(r"\$", "", out)
    out = re.sub(r"\\left\.", "", out)
    out = re.sub(r"\\right\.", "", out)
    out = re.sub(r"\\(?![A-Za-z{])", "", out)  # stray backslash before non-letter
    return out


def _strip_unit_residue(text: str) -> str:
    """Drop trailing alphabetic/unit residue so ``64 inches`` -> ``64`` (a
    robustness extension of the frozen ``_UNIT_WORDS`` list)."""
    out = text
    # Trailing words after the numeric expression (e.g. "inches", "people").
    out = re.sub(r"[\s\*]*[a-zA-Z][a-zA-Z\s]*$", "", out)
    return out


def _split_equals(text: str) -> str:
    """If the candidate is an equation ``A = B``, keep B (parser limitation:
    the frozen parser cannot parse an expression containing ``=``)."""
    parts = re.split(r"(?<![<>=!])=(?!=)", text)
    if len(parts) > 1:
        return parts[-1].strip()
    return text


def _operator_aliases(text: str) -> str:
    out = text
    out = out.replace("\\cdot", "*").replace("\\times", "*")
    out = out.replace("\\div", "/").replace("\\ast", "*")
    return out


def _frac_aliases(text: str) -> str:
    """\\dfrac/\\tfrac/\\cfrac -> \\frac (so the frozen expander can act)."""
    return re.sub(r"\\(dfrac|tfrac|cfrac)\b", "\\\\frac", text)


def _escapes(text: str) -> str:
    out = text
    out = out.replace("\\{", "(").replace("\\}", ")")
    out = out.replace("\\\\", "")  # LaTeX line break
    return out


TRANSFORMS = [
    ("text_commands", _strip_text_commands),
    ("delim_residue", _strip_delim_residue),
    ("unit_residue", _strip_unit_residue),
    ("operator_aliases", _operator_aliases),
    ("frac_aliases", _frac_aliases),
    ("escapes", _escapes),
    ("split_equals", _split_equals),
]


def syntactic_cascade(candidate: str):
    """Yield progressively-normalized candidates (cumulative transforms)."""
    out = candidate
    yield "none", out
    for name, fn in TRANSFORMS:
        out = fn(out)
        yield name, out


# --------------------------------------------------------------------------- #
# Final-answer hunter (better-targeted extraction, read-only analysis)
# --------------------------------------------------------------------------- #
def _boxed_blocks(text: str) -> list[str]:
    """Brace-balanced \\boxed{...} capture (mirrors the frozen extractor)."""
    blocks: list[str] = []
    i = 0
    n = len(text)
    token = "\\boxed"
    while True:
        start = text.find(token, i)
        if start == -1:
            break
        j = start + len(token)
        while j < n and text[j].isspace():
            j += 1
        if j >= n or text[j] != "{":
            i = start + len(token)
            continue
        depth, k = 0, j
        while k < n:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        if depth != 0:
            break
        blocks.append(text[j + 1 : k])
        i = k + 1
    return blocks


def hunt_final_answers(response: str) -> list[str]:
    """Deterministic candidates for the 'true' final answer in a response,
    in priority order. Used only for the read-only recovery estimate."""
    text = response or ""
    cands: list[str] = []

    boxed = _boxed_blocks(text)
    if boxed:
        cands.append(boxed[-1].strip())

    for pat in (r"(?i)\bfinal\s+answer\s*(?:is\s*)?[:*]?\s*(.+)",
                r"(?i)\banswer\s*(?:is\s*)?[:*]?\s*(.+)",
                r"(?i)\b(?:therefore|thus|so|hence)\b[^.\n]*?[:=]\s*([^\n]+)"):
        m = re.search(pat, text, re.DOTALL)
        if m:
            cands.append(m.group(1).strip())

    # RHS of the last '=' on a mathy line.
    mathy_eq = re.findall(r"[^=\n]*=(?![=<>])([^\n]*\d[^\n]*)", text)
    if mathy_eq:
        cands.append(mathy_eq[-1].strip())

    # Last number in the text (decimal/integer), and the last mathy line.
    nums = re.findall(r"-?\d+(?:\.\d+)?", text)
    if nums:
        cands.append(nums[-1])
    mathy_lines = [
        ln.strip().rstrip(".,;")
        for ln in text.splitlines()
        if re.search(r"[0-9]|[-+*/^()\\]", ln) and ln.strip()
    ]
    if mathy_lines:
        cands.append(mathy_lines[-1])
    return cands


def recoverable_via_hunter(reference: str, response: str) -> dict | None:
    """Does ANY hunted final-answer candidate equal the reference after the
    syntactic cascade? (read-only estimate of better-targeted extraction)."""
    for cand in hunt_final_answers(response):
        for name, c in syntactic_cascade(cand):
            eq, eq_method, n_ok = expressions_equivalent(reference, c)
            if eq:
                return {"transform": name, "source": cand[:50], "method": eq_method}
    return None


# --------------------------------------------------------------------------- #
# Per-record audit
# --------------------------------------------------------------------------- #
def audit_record(rec: dict) -> dict:
    rid = rec.get("record_id")
    reference = rec.get("extracted_reference") or ""
    candidate = rec.get("extracted_candidate") or ""
    method = rec.get("method")
    correctness = rec.get("correctness")

    if method != "unparsable":
        return {
            "record_id": rid, "method": method, "correctness": correctness,
            "cluster": "parsed_wrong_or_partial",
        }

    recovered = None
    for name, c in syntactic_cascade(candidate):
        eq, eq_method, n_ok = expressions_equivalent(reference, c)
        if eq:
            recovered = {"transform": name, "method": eq_method}
            break

    response = rec.get("predicted_response") or ""
    hunter = recoverable_via_hunter(reference, response) if not recovered else None
    truncated = rec.get("stop_reason") == "max_length"

    if recovered:
        cluster = "syntactic_recoverable"
    elif hunter:
        cluster = "extraction_target_gap"
    elif truncated:
        cluster = "truncated_incomplete"
    else:
        cluster = "genuine_wrong_answer"

    return {
        "record_id": rid,
        "method": method,
        "correctness": correctness,
        "reference": reference,
        "candidate": candidate,
        "recovered": recovered,
        "hunter": hunter,
        "truncated": truncated,
        "cluster": cluster,
    }


def main() -> int:
    pex = [json.loads(l) for l in PEX.open(encoding="utf-8") if l.strip()]
    ev = {}
    for l in EVAL.open(encoding="utf-8"):
        r = json.loads(l)
        ev[r["record_id"]] = r

    failed = [r for r in pex if (r.get("correctness") or 0) < 1.0]
    audit = [audit_record(r) for r in failed]

    syn = [a for a in audit if a["cluster"] == "syntactic_recoverable"]
    ext = [a for a in audit if a["cluster"] == "extraction_target_gap"]
    trunc = [a for a in audit if a["cluster"] == "truncated_incomplete"]
    wrong = [a for a in audit if a["cluster"] == "genuine_wrong_answer"]

    report = {
        "scope": "math failures on math_eval_v2 (frozen v2 baseline), read-only audit",
        "n_failed": len(failed),
        "n_unparsable": sum(1 for a in audit if a["method"] == "unparsable"),
        "clusters": {
            "syntactic_recoverable": {
                "n": len(syn),
                "by_transform": {
                    t: sum(1 for a in syn if a["recovered"]["transform"] == t)
                    for t in [x[0] for x in TRANSFORMS] + ["none"]
                },
            },
            "extraction_target_gap": {"n": len(ext)},
            "truncated_incomplete": {"n": len(trunc)},
            "genuine_wrong_answer": {"n": len(wrong)},
        },
        "records": sorted(audit, key=lambda a: a["record_id"]),
    }
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")

    print(f"failed={len(failed)} unparsable={report['n_unparsable']}")
    print(f"  syntactic_recoverable={len(syn)} extraction_target_gap={len(ext)} "
          f"truncated_incomplete={len(trunc)} genuine_wrong_answer={len(wrong)}")
    print("syntactic by transform:", report["clusters"]["syntactic_recoverable"]["by_transform"])
    for a in sorted(audit, key=lambda a: a["record_id"]):
        if a["method"] == "unparsable":
            print(f"  {a['record_id']} -> {a['cluster']}"
                  + (f" via {a['recovered']['transform']}"
                     if a["recovered"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
