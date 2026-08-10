#!/usr/bin/env python3
"""run_baseline_t3.py — Protocol v2 canonical baseline (T3, R1/R2).

Establishes the first clean baseline under Protocol v2 for
``experiments/atlas-mixed-pilot-qwen7b-eval-v2``: reference-free inference of
``Qwen/Qwen2.5-7B-Instruct`` (no LoRA) on ``math_eval_v2`` (N=100) and
``code_eval_v2`` (N=99), scored with the unchanged QEE v2 engine.

Protocol v2 compliance (docs/research/protocol_v2_transition.md §3):
  * Reference-free prompts via the shared module
    ``evaluation_engine.leakage.prompts`` (rule P4) with the real tokenizer;
    per-record ``prompt_sha256`` + ``canonical_answer_sha256`` recorded.
  * Runtime guard (L2) runs on every record and FAILS CLOSED on any hit
    (record -> HOLD, run aborted, non-zero exit).
  * Generation Policy Lock per family: per-record reference-derived token
    budget ``min(4096, max(256, 128 + ceil(1.5*N_tokens(reference_i))))``,
    ``<|im_end|>`` eos / pad = eos, greedy, seed 42, NF4+bf16.
  * Code responses pass through the diff-extraction wrapper (P8 generation
    policy §4.5); format covariates (patch / fenced / code / prose) and
    truncation are first-class metrics.
  * Scoring: unchanged QEE v2; reference argument from ``canonical_answer``.
  * G-POL gate: patch-emission >= 0.90, truncation <= 0.05 (recorded either
    way), majority stop reason = eos, determinism spot-check.
  * Experiment fingerprint re-verified against the pre-registered input block.

The experiment fingerprint, certificate, leak scan ids, and policy locks are
read from ``metadata/evaluation/protocol_v2_baseline/``.

Usage (on the CUDA dev box)::

    python scripts/evaluation_engine/run_baseline_t3.py [--families math code] \\
        [--max-records N] [--smoke]

``--smoke`` runs 3 records per family and exits (validation of the full path).
Writes ONLY under ``experiments/atlas-mixed-pilot-qwen7b-eval-v2/``.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

EXPERIMENT_ID = "atlas-mixed-pilot-qwen7b-eval-v2"
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
MODEL_REVISION = "a09a35458c702b33eeacc393d103063234e8bc28"
SEED = 42
MAX_BUDGET = 4096
BUDGET_FALLBACK = 1024

EVAL_DIR = REPO / "evaluation" / "eval_sets" / "protocol_v2"
CERT_DIR = REPO / "metadata" / "evaluation" / "protocol_v2_baseline"
OUT_DIR = REPO / "experiments" / EXPERIMENT_ID

FAMILIES = {
    "math": {"eval_file": "math_eval_v2.jsonl", "family": "math"},
    "code": {"eval_file": "code_eval_v2.jsonl", "family": "code"},
}

_DIFF_MARKER_RE = re.compile(r"(?m)^(diff --git |--- a/|\+\+\+ b/)")
_FENCE_RE = re.compile(r"```")
_CODE_LIKE_RE = re.compile(r"(?m)(^\s*(def|class|import|from|function|return)\b|=>|;|\{[^}]*\})")


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# --------------------------------------------------------------------------- #
# Generation Policy Lock helpers (Sprint 5A.6: DynamicBudgetStrategy)
# --------------------------------------------------------------------------- #
from evaluation_engine.generation_policy import (
    DynamicBudgetStrategy,
)
from evaluation_engine.generation_policy.versioning import FAMILY_BUDGET_PARAMS

# Per-family dynamic budget strategies (calibrated, Sprint 5A.5).
_FAM_STRATEGIES: dict[str, DynamicBudgetStrategy] = {
    fam: DynamicBudgetStrategy(
        base_budget=p["base_budget"],
        alpha=p["alpha"],
        minimum_budget=p["minimum_budget"],
        maximum_budget=p["maximum_budget"],
        fallback_budget=BUDGET_FALLBACK,
    )
    for fam, p in FAMILY_BUDGET_PARAMS.items()
}


def per_record_budget(reference: str, tokenizer, fallback: int = BUDGET_FALLBACK,
                      strategy: DynamicBudgetStrategy | None = None) -> int:
    """Dynamic reference-derived budget (Sprint 5A.6).

    Uses DynamicBudgetStrategy from the family policy; falls back to the
    canonical StaticBudget formula for backward compatibility when no strategy
    is supplied.
    """
    if strategy is not None:
        result = strategy.compute(reference, token_counter=lambda text: len(
            tokenizer.encode(text, add_special_tokens=False)))
        return result.budget
    # Fallback to static formula (legacy).
    try:
        n_tokens = len(tokenizer.encode(reference, add_special_tokens=False))
    except Exception:  # noqa: BLE001 - budget is a covariate; fail soft here
        return fallback
    return min(MAX_BUDGET, max(256, 128 + math.ceil(1.5 * n_tokens)))


def classify_code_response(response: str) -> str:
    """Classify a code-family response into patch / fenced_code / code_tokens /
    pure_prose (policy covariate)."""
    if _DIFF_MARKER_RE.search(response):
        return "patch"
    if _FENCE_RE.search(response):
        return "fenced_code"
    if _CODE_LIKE_RE.search(response):
        return "code_tokens"
    return "pure_prose"


def extract_diff(response: str) -> tuple[str, bool]:
    """Diff-extraction wrapper (P8 generation policy §4.5). Returns
    (extracted_text, emitted_diff). Leading prose is dropped; the diff runs to
    end-of-response."""
    text = response or ""
    # Strip a leading fenced ```diff ... ``` block when the whole response is
    # one fenced block.
    if text.strip().startswith("```"):
        m = re.match(r"```\w*\s*\n(.*?)```", text, re.DOTALL)
        if m:
            inner = m.group(1)
            if _DIFF_MARKER_RE.search(inner):
                return inner, True
    marker = _DIFF_MARKER_RE.search(text)
    if marker:
        return text[marker.start():], True
    return "", False


# --------------------------------------------------------------------------- #
# Scoring (unchanged QEE v2; reference from canonical_answer)
# --------------------------------------------------------------------------- #
def score_response(family: str, record: dict, response: str, extracted: str):
    """Score a response with the QEE v2 engine. Returns a dict in the pilot
    metric shape (correctness / reasoning_quality / hallucination_rate /
    answer_format_consistency) plus the full QEE v2 record."""
    from evaluation_engine.v2.engine import QeeV2Engine

    engine = QeeV2Engine()
    question = record.get("problem") or ""
    reference = record.get("canonical_answer") or ""

    candidate = extracted if family == "code" else response

    _, result = engine._type_result(family, question, reference, candidate)
    dim_breakdown = engine._dimensions(family, result, question, reference, candidate)
    dims = {k: v["score"] for k, v in dim_breakdown.items()}
    raw_continuous = sum(engine.weights[k] * dims[k] for k in engine.weights)
    continuous, quality_score = engine._map_to_scale(raw_continuous)

    correctness = float(result.score)
    is_wrong = result.correct is False
    hallucination_rate = 1.0 if (is_wrong and correctness < 0.4) else 0.0

    if family == "math":
        method = result.method
        format_ok = 1.0 if method != "no_final_answer" else 0.0
    else:  # code: the policy contract is unified-diff emission
        method = result.method
        format_ok = 1.0 if extracted.strip() else 0.0

    return {
        "correctness": correctness,
        "correct": result.correct,
        "method": method,
        "reasoning_quality": float(continuous),
        "quality_score": quality_score,
        "raw_continuous": round(raw_continuous, 4),
        "hallucination_rate": hallucination_rate,
        "answer_format_consistency": format_ok,
        "extracted_reference": getattr(result, "extracted_reference", ""),
        "extracted_candidate": getattr(result, "extracted_candidate", ""),
        "dimensions": {k: round(v, 3) for k, v in dims.items()},
        "flags": [f for f in (["incorrect"] if is_wrong else [])]
        if result.correct is not None else ["unverifiable"],
    }


# --------------------------------------------------------------------------- #
# Determinism / G-POL aggregation
# --------------------------------------------------------------------------- #
def aggregate_family(rows: list[dict], family: str, total_records: int) -> dict:
    valid = [r for r in rows if r.get("correctness") is not None]
    n = len(valid) or 1

    token_counts = [r["tokens_generated"] for r in valid if r.get("tokens_generated") is not None]
    stop_reasons = Counter(r.get("stop_reason") for r in rows)
    trunc_count = sum(1 for r in rows if r.get("stop_reason") == "max_length")

    agg = {
        "family": family,
        "evaluated_examples": len(valid),
        "total_examples": total_records,
        "correctness": round(sum(r["correctness"] for r in valid) / n, 4),
        "reasoning_quality": round(sum(r["reasoning_quality"] for r in valid) / n, 4),
        "hallucination_rate": round(sum(r["hallucination_rate"] for r in valid) / n, 4),
        "answer_format_consistency": round(
            sum(r["answer_format_consistency"] for r in valid) / n, 4
        ),
        "patch_emission_rate": (
            round(sum(1 for r in valid if r["format_class"] == "patch") / len(valid), 4)
            if family == "code" and valid else None
        ),
        "format_distribution": dict(
            Counter(r.get("format_class") for r in rows)
        ),
        "truncation_rate": round(trunc_count / len(rows), 4) if rows else None,
        "stop_reason_counts": dict(stop_reasons),
        "tokens_mean": round(sum(token_counts) / len(token_counts), 2) if token_counts else None,
        "tokens_median": (
            float(sorted(token_counts)[len(token_counts) // 2]) if token_counts else None
        ),
        "budget_fallback_used": sum(1 for r in rows if r.get("budget_fallback_used")),
    }
    return agg


def gpol_verdict(agg: dict, family: str, spot_check: dict | None) -> dict:
    """Gate G-POL (Protocol v2 §3.6)."""
    if family == "code":
        checks = {
            "patch_emission_rate_ge_0.90": (
                agg.get("patch_emission_rate") is not None
                and agg["patch_emission_rate"] >= 0.90
            ),
            "truncation_rate_le_0.05": (
                agg.get("truncation_rate") is not None
                and agg["truncation_rate"] <= 0.05
            ),
            "majority_stop_is_eos": (
                agg.get("stop_reason_counts", {}).get("eos", 0)
                >= agg.get("stop_reason_counts", {}).get("max_length", 0)
            ),
            "determinism_spot_check": (
                spot_check is not None and spot_check.get("all_identical") is True
            ),
        }
    else:
        checks = {
            "truncation_rate_le_0.05": (
                agg.get("truncation_rate") is not None
                and agg["truncation_rate"] <= 0.05
            ),
            "majority_stop_is_eos": (
                agg.get("stop_reason_counts", {}).get("eos", 0)
                >= agg.get("stop_reason_counts", {}).get("max_length", 0)
            ),
            "determinism_spot_check": (
                spot_check is not None and spot_check.get("all_identical") is True
            ),
        }
    return {
        "family": family,
        "gate": "G-POL",
        "checks": checks,
        "pass": all(checks.values()),
        "note": (
            "gate failure -> capability conclusions HOLD; policy covariates "
            "reported, never interpreted as capability"
        ),
    }


# --------------------------------------------------------------------------- #
# Hardware / runtime info
# --------------------------------------------------------------------------- #
def hardware_info() -> dict:
    import platform

    import torch

    info = {
        "host": platform.node(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
    }
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        info["gpu"] = props.name
        info["vram_total_mib"] = round(props.total_memory / 1024**2, 2)
        info["cuda_version"] = torch.version.cuda
    for mod in ("transformers", "bitsandbytes", "accelerate"):
        try:
            info[mod] = __import__(mod).__version__
        except Exception:  # noqa: BLE001
            info[mod] = None
    return info


# --------------------------------------------------------------------------- #
# Main run
# --------------------------------------------------------------------------- #
def load_model():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    torch.manual_seed(SEED)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL, revision=MODEL_REVISION, use_fast=True
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        revision=MODEL_REVISION,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=False,
    )
    model.eval()
    return model, tokenizer


def torch_generation_decorator(fn):
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        import torch

        with torch.no_grad():
            return fn(*args, **kwargs)

    return wrapper


@torch_generation_decorator
def generate(model, tokenizer, prompt: str, max_new_tokens: int, eos_id: int):
    import torch

    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    input_len = inputs["input_ids"].shape[1]
    gen_ids = model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        eos_token_id=eos_id,
        pad_token_id=tokenizer.pad_token_id,
    )
    new_tokens = gen_ids[0][input_len:]
    text = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    stop_reason = "max_length" if int(new_tokens.numel()) >= max_new_tokens else "eos"
    return text, int(new_tokens.numel()), stop_reason


def process_record(family: str, record: dict, model, tokenizer, policy, eos_id: int) -> dict:
    from evaluation_engine.leakage.prompts import (
        ReferenceLeakError,
        build_reference_free_prompt,
        prompt_meta,
    )

    rid = record.get("record_id", "unknown")

    # Prompt build + L2 runtime guard (fail-closed).
    try:
        prompt = build_reference_free_prompt(record, policy, tokenizer=tokenizer)
    except ReferenceLeakError as exc:
        return {
            "record_id": rid, "family": family, "leak": "FAILED",
            "leak_error": str(exc), "status": "HOLD",
        }

    reference = record.get("canonical_answer") or ""
    strategy = _FAM_STRATEGIES.get(family)
    budget = per_record_budget(reference, tokenizer, strategy=strategy)
    budget_fallback_used = budget == BUDGET_FALLBACK

    response, n_tokens, stop_reason = generate(
        model, tokenizer, prompt, max_new_tokens=budget, eos_id=eos_id
    )

    if family == "code":
        extracted, emitted_diff = extract_diff(response)
        format_class = classify_code_response(response)
    else:
        extracted, emitted_diff, format_class = response, True, "math"

    score = score_response(family, record, response, extracted)

    meta = prompt_meta(prompt)
    out = {
        "record_id": rid,
        "family": family,
        "eval_set_id": record.get("eval_set_id"),
        "status": "scored",
        "leak": "PASS",
        "prompt_sha256": meta["prompt_sha256"],
        "prompt_fingerprint": meta["prompt_fingerprint"],
        "prompt_sha256_deterministic_renderer": record.get("prompt_sha256"),
        "canonical_answer_sha256": record.get("canonical_answer_sha256"),
        "budget": budget,
        "budget_fallback_used": budget_fallback_used,
        "tokens_generated": n_tokens,
        "stop_reason": stop_reason,
        "predicted_response": response,
        "format_class": format_class,
        "emitted_diff": emitted_diff,
        "extracted_diff": extracted,
        **score,
    }
    return out


def run_family(family: str, model, tokenizer, policy, eos_id: int,
               max_records: int | None, out: dict, resume: bool = False) -> list[dict]:
    cfg = FAMILIES[family]
    eval_file = EVAL_DIR / cfg["eval_file"]
    records = load_jsonl(eval_file)
    if max_records is not None:
        records = records[:max_records]

    per_example_path = OUT_DIR / f"per_example_{family}.jsonl"

    # Resume: reload previously-scored rows, skip their records.
    done_ids: set[str] = set()
    if resume and per_example_path.exists():
        for line in per_example_path.open(encoding="utf-8"):
            line = line.strip()
            if line:
                row = json.loads(line)
                done_ids.add(row.get("record_id"))
        print(f"[{family}] resume: {len(done_ids)} records already scored")
        per_example = [
            json.loads(l) for l in per_example_path.open(encoding="utf-8") if l.strip()
        ]
        to_score = [r for r in records if r.get("record_id") not in done_ids]
    else:
        per_example_path.parent.mkdir(parents=True, exist_ok=True)
        if per_example_path.exists():
            per_example_path.unlink()
        per_example = []
        to_score = records

    for i, rec in enumerate(to_score):
        row = process_record(family, rec, model, tokenizer, policy, eos_id)
        per_example.append(row)
        # Checkpoint: append immediately so a crash never loses progress.
        with per_example_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"[{family}] {len(per_example)}/{len(records)} {row.get('record_id')} "
            f"tokens={row.get('tokens_generated')} stop={row.get('stop_reason')} "
            f"correctness={row.get('correctness')}"
        )
        if row.get("status") == "HOLD":
            out["hold_records"].append(row)

    # Fail closed on any hold.
    if out["hold_records"]:
        print(f"[{family}] FAIL_CLOSED: {len(out['hold_records'])} guard holds")
        return per_example

    # Determinism spot-check: regenerate a fixed sample and compare.
    spot = None
    if len(records) >= 3:
        sample = records[:3]
        spot = determinism_spot_check(sample, family, model, tokenizer, policy, eos_id)
        print(f"[{family}] determinism spot-check identical={spot['all_identical']}")

    agg = aggregate_family(per_example, family, len(records))
    gpol = gpol_verdict(agg, family, spot)
    out["families"][family] = {
        "aggregate": agg,
        "gpol": gpol,
        "spot_check": spot,
    }
    return per_example


def determinism_spot_check(sample: list[dict], family: str, model, tokenizer,
                           policy, eos_id: int) -> dict:
    from evaluation_engine.leakage.prompts import build_reference_free_prompt

    first, second = [], []
    for rec in sample:
        prompt = build_reference_free_prompt(rec, policy, tokenizer=tokenizer)
        reference = rec.get("canonical_answer") or ""
        strategy = _FAM_STRATEGIES.get(family)
        budget = per_record_budget(reference, tokenizer, strategy=strategy)
        r1, n1, s1 = generate(model, tokenizer, prompt, max_new_tokens=budget, eos_id=eos_id)
        r2, n2, s2 = generate(model, tokenizer, prompt, max_new_tokens=budget, eos_id=eos_id)
        first.append(r1)
        second.append(r2)
    identical = first == second
    return {
        "family": family,
        "sample_size": len(sample),
        "all_identical": identical,
        "matches": [a == b for a, b in zip(first, second)],
        "sample_record_ids": [r.get("record_id") for r in sample],
        "note": "two greedy generations within one process on a fixed sample",
    }


def verify_fingerprint() -> dict:
    """Recompute the experiment fingerprint from the certificate's input block
    and compare to the pre-registered value. Fail closed on mismatch."""
    fp_file = CERT_DIR / "experiment_fingerprint.json"
    if not fp_file.exists():
        return {
            "verified": False,
            "error": f"missing {fp_file.relative_to(REPO)}",
        }
    fp = json.loads(fp_file.read_text(encoding="utf-8"))
    recomputed = sha256_hex(canonical_json(fp["input_block"]))
    return {
        "verified": recomputed == fp["fingerprint_sha256"],
        "fingerprint_sha256": fp["fingerprint_sha256"],
        "recomputed": recomputed,
        "experiment_id": fp["experiment_id"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Protocol v2 canonical baseline (T3)")
    ap.add_argument("--families", nargs="*", default=["math", "code"],
                    choices=["math", "code"])
    ap.add_argument("--max-records", type=int, default=None,
                    help="limit records per family (smoke/validation)")
    ap.add_argument("--smoke", action="store_true",
                    help="run 3 records per family and stop (validation only)")
    ap.add_argument("--resume", action="store_true",
                    help="resume from existing per_example checkpoints "
                         "(skip already-scored records)")
    args = ap.parse_args()

    import torch
    from evaluation_engine.leakage.prompts import (
        TEMPLATE_VERSION, get_policy_lock,
    )

    if args.smoke:
        args.max_records = 3

    # --- Fingerprint + certificate gates ----------------------------------- #
    fp_check = verify_fingerprint()
    print(f"[T3] experiment fingerprint verified={fp_check.get('verified')} "
          f"({fp_check.get('fingerprint_sha256', '')[:16]})")
    if not fp_check.get("verified"):
        print("[T3] FAIL_CLOSED: experiment fingerprint mismatch; aborting.")
        return 3

    cert_file = CERT_DIR / "protocol_certificate.json"
    cert = json.loads(cert_file.read_text(encoding="utf-8"))
    if cert.get("readiness_verdict") != "READY":
        print(f"[T3] FAIL_CLOSED: readiness verdict={cert.get('readiness_verdict')}; aborting.")
        return 3

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run = {
        "experiment_id": EXPERIMENT_ID,
        "phase": "T3 canonical baseline (R1/R2)",
        "protocol_version": "v2",
        "status": "RUNNING",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": {"base_model": BASE_MODEL, "revision": MODEL_REVISION},
        "fingerprint_verified": fp_check,
        "leak_scan_ids": {
            fam: cert["eval_sets"][fam]["leak_scan_id"] for fam in ("math", "code")
        },
        "template_version": TEMPLATE_VERSION,
        "engine_commit": cert["engine"]["git_commit"],
        "engine_patch": {
            "id": "RP-001",
            "reference": "docs/research/robustness_patch_rp001.md",
            "math_eval_sha256": sha256_hex(
                (REPO / "scripts" / "evaluation_engine" / "v2" / "math_eval.py")
                .read_text(encoding="utf-8")
            ),
            "note": "documented robustness patch (guard bare '=' in "
                    "extract_final_answer); no scoring/normalization change",
        },
        "policy_locks": cert["policy_locks"],
        "families": {},
        "hold_records": [],
    }

    print(f"[T3] loading {BASE_MODEL} (rev {MODEL_REVISION[:12]}) ...")
    try:
        model, tokenizer = load_model()
    except Exception as exc:  # noqa: BLE001
        run["status"] = "BLOCKED"
        run["error"] = str(exc)
        run["completed_at"] = datetime.now(timezone.utc).isoformat()
        print(f"[T3] MODEL_LOAD_FAILURE: {exc}")
        (OUT_DIR / "run_metadata.json").write_text(
            json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return 2

    eos_id = tokenizer.convert_tokens_to_ids("<|im_end|>")
    if eos_id is None or tokenizer.eos_token_id is None:
        run["status"] = "FAILED"
        run["error"] = "eos token resolution failed"
        return 4

    all_per_example: dict[str, list[dict]] = {}
    for fam in args.families:
        policy = get_policy_lock(fam)
        rows = run_family(fam, model, tokenizer, policy, eos_id,
                          args.max_records, run, resume=args.resume)
        all_per_example[fam] = rows

    # --- Write artifacts ----------------------------------------------------- #
    if run["hold_records"]:
        run["status"] = "FAILED"
    else:
        leak_pass = all(
            all(r.get("leak") == "PASS" for r in rows)
            for rows in all_per_example.values()
        )
        run["status"] = "COMPLETED" if leak_pass else "FAILED"
        run["leak_pass_rate"] = 1.0 if leak_pass else None

    run["hardware"] = hardware_info()
    run["completed_at"] = datetime.now(timezone.utc).isoformat()

    (OUT_DIR / "run_metadata.json").write_text(
        json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    for fam, rows in all_per_example.items():
        (OUT_DIR / f"per_example_{fam}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )
        fam_block = run["families"].get(fam, {})
        if fam_block:
            (OUT_DIR / f"aggregate_{fam}.json").write_text(
                json.dumps(fam_block, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    # Generation policy summary (merged across families).
    gpol_summary = {
        "experiment_id": EXPERIMENT_ID,
        "families": {
            fam: {
                "gpol": run["families"].get(fam, {}).get("gpol"),
                "aggregate_policy_covariates": {
                    k: v for k, v in run["families"]
                    .get(fam, {}).get("aggregate", {}).items()
                    if k in (
                        "patch_emission_rate", "format_distribution",
                        "truncation_rate", "stop_reason_counts",
                        "tokens_mean", "tokens_median", "budget_fallback_used",
                    )
                },
            }
            for fam in run["families"]
        },
    }
    (OUT_DIR / "generation_policy_summary.json").write_text(
        json.dumps(gpol_summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    config = {
        "experiment_id": EXPERIMENT_ID,
        "phase": "T3 canonical baseline (R1/R2)",
        "objective": "First fully valid baseline under Protocol v2 (reference-free, "
                     "policy-locked).",
        "scope": "baseline inference/evaluation only. No LoRA. No training. "
                 "No dataset/view/release modification.",
        "base_model": BASE_MODEL,
        "model_revision": MODEL_REVISION,
        "inference": {
            "quantization": "4bit_nf4_double_quant",
            "compute_dtype": "bfloat16",
            "sampling": "greedy", "do_sample": False, "seed": SEED,
            "budget_rule": "budget_i = min(4096, max(256, 128 + ceil(1.5*N_tokens(ref))))",
            "budget_fallback": BUDGET_FALLBACK,
            "stop_sequence": "<|im_end|>",
            "extraction_rule": "P8-generation-policy-lock v1.0 diff extraction wrapper",
            "device_map": "auto",
        },
        "prompt": {
            "module": "scripts/evaluation_engine/leakage/prompts.py",
            "source": "record['problem'] only; canonical_answer never rendered",
        },
        "scoring": {
            "engine": "scripts/evaluation_engine/v2 (QEE v2)",
            "engine_commit": cert["engine"]["git_commit"],
            "reference": "record['canonical_answer']",
        },
        "families": {fam: str((EVAL_DIR / FAMILIES[fam]["eval_file"]).relative_to(REPO))
                     for fam in args.families},
        "artifacts": {
            "run_metadata": "experiments/atlas-mixed-pilot-qwen7b-eval-v2/run_metadata.json",
            "per_example": {fam: f"experiments/atlas-mixed-pilot-qwen7b-eval-v2/per_example_{fam}.jsonl"
                            for fam in args.families},
            "aggregate": {fam: f"experiments/atlas-mixed-pilot-qwen7b-eval-v2/aggregate_{fam}.json"
                          for fam in args.families},
            "generation_policy_summary": (
                "experiments/atlas-mixed-pilot-qwen7b-eval-v2/generation_policy_summary.json"),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (OUT_DIR / "config.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"\n[T3] status={run['status']}")
    for fam in run["families"]:
        a = run["families"][fam]["aggregate"]
        g = run["families"][fam]["gpol"]
        print(f"[T3] {fam}: correctness={a['correctness']} "
              f"reasoning={a['reasoning_quality']} "
              f"format={a['answer_format_consistency']} "
              f"trunc={a['truncation_rate']} gpol_pass={g['pass']}")
    return 0 if run["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
