#!/usr/bin/env python3
"""
Atlas 500M Pilot v3 — Evaluation Script

Evaluates all v3 models across math, code, and systems eval sets.
Compares against v2 baselines.
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

ROOT = Path("/home/afnan/projects/active/atlas-dataset")
sys.path.insert(0, str(ROOT / "scripts"))

BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
V3_ARTIFACTS = ROOT / "experiments" / "atlas-500m-pilot-v3-scale" / "artifacts"
V2_ARTIFACTS = ROOT / "artifacts" / "pilot" / "v0.2"
EVAL_BASE = ROOT / "evaluation" / "eval_sets" / "protocol_v2"
OUTPUT_DIR = ROOT / "experiments" / "atlas-500m-pilot-v3-scale" / "evaluation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EVAL_SETS = {
    "math_eval_v2": EVAL_BASE / "math_eval_v2.jsonl",
    "code_eval_v2": EVAL_BASE / "code_eval_v2.jsonl",
    "systems_eval_v2": EVAL_BASE / "systems_eval_v2.jsonl",
}
EVAL_DISPATCH = {
    "math_eval_v2": "math",
    "code_eval_v2": "code",
    "systems_eval_v2": "code",
}

# Load v2 results for comparison
V2_RESULTS = {}
v2_report = ROOT / "reports" / "pilot_eval_v2"
if v2_report.exists():
    for f in v2_report.glob("*_math_eval_v2_per_example.jsonl"):
        arm = f.stem.replace("_math_eval_v2_per_example", "")
        with open(f) as fh:
            V2_RESULTS.setdefault(arm, {})["math_eval_v2"] = [json.loads(l) for l in fh]
    for f in v2_report.glob("*_code_eval_v2_per_example.jsonl"):
        arm = f.stem.replace("_code_eval_v2_per_example", "")
        with open(f) as fh:
            V2_RESULTS.setdefault(arm, {})["code_eval_v2"] = [json.loads(l) for l in fh]
    for f in v2_report.glob("*_systems_eval_v2_per_example.jsonl"):
        arm = f.stem.replace("_systems_eval_v2_per_example", "")
        with open(f) as fh:
            V2_RESULTS.setdefault(arm, {})["systems_eval_v2"] = [json.loads(l) for l in fh]

print(f"V2 baseline results loaded for: {list(V2_RESULTS.keys())}")

# v3 adapters
ADAPTERS = {}
for arm in ["general", "math", "code", "systems"]:
    apath = V3_ARTIFACTS / arm / "adapter"
    if (apath / "adapter_config.json").exists():
        ADAPTERS[arm] = apath
    else:
        print(f"WARNING: No adapter found for {arm} at {apath}")

# Also load v2 adapters for comparison
V2_ADAPTERS = {}
for arm in ["general", "math", "code", "systems"]:
    apath = V2_ARTIFACTS / arm / "adapter"
    if (apath / "adapter_config.json").exists():
        V2_ADAPTERS[arm] = apath


MAX_NEW_TOKENS = 256
BATCH_SIZE = 16

from evaluation_engine.v2.engine import QeeV2Engine
from evaluation_engine.v2.math_eval import MathAnswerEvaluator
from evaluation_engine.v2.code_eval import CodeAnswerEvaluator

QEE = QeeV2Engine()
MATH_EVAL = MathAnswerEvaluator()
CODE_EVAL = CodeAnswerEvaluator()


def load_tokenizer():
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, use_fast=True, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = 'left'
    return tokenizer


def load_base_model():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, dtype=torch.bfloat16, device_map=device,
        trust_remote_code=True,
    )
    model.eval()
    return model, device


def build_prompt(record, tokenizer):
    messages = record.get("messages") or []
    if messages:
        try:
            return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            return "\n".join(f"{m['role']}: {m['content']}" for m in messages) + "\nassistant: "
    return f"user: {record.get('problem', '')}\nassistant: "


@torch.no_grad()
def generate_batch(model, tokenizer, records, device):
    prompts = [build_prompt(r, tokenizer) for r in records]
    inputs = tokenizer(prompts, return_tensors="pt", padding=True, truncation=True, max_length=1024).to(device)
    input_lens = inputs["input_ids"].shape[1]
    t0 = time.perf_counter()
    gen = model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False,
                         pad_token_id=tokenizer.pad_token_id)
    latency = time.perf_counter() - t0
    results = []
    for i in range(len(records)):
        new_tokens = gen[i][input_lens:]
        text = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        results.append((text, int(new_tokens.numel())))
    return results, latency


def score_record(record, response, eval_type):
    ref = record.get("canonical_answer", "")
    question = record.get("problem", "") or (
        "\n".join(m.get("content", "") for m in record.get("messages", []) if m.get("role") == "user")
    )

    if eval_type == "math":
        result = MATH_EVAL.evaluate(question=question, reference=ref, candidate=response)
        correctness = result.score
        correct = result.correct
        method = result.method
        reason = result.reason
        flags = []
        if correct is False:
            flags.append("incorrect")
        elif correct is None:
            flags.append("unverifiable")
        if correctness < 0.4:
            flags.append("low_correctness")
        return {
            "answer_type": "math",
            "correctness": round(correctness, 4),
            "correct": correct,
            "quality_score": int(max(1, min(10, round(1 + correctness * 9)))),
            "quality_continuous": round(correctness, 4),
            "method": method,
            "flags": flags,
            "extracted_reference": result.extracted_reference,
            "extracted_candidate": result.extracted_candidate,
            "dimensions": {
                "accuracy": round(correctness, 3),
                "technical_correctness": round(correctness, 3),
                "completeness": round(min(1.0, correctness + 0.1 if correctness < 1.0 else 1.0), 3),
                "clarity": 0.8 if result.extracted_candidate else 0.4,
                "usefulness": round(correctness, 3),
                "originality": 0.7 if result.method != "no_final_answer" else 0.4,
                "relevance": 0.9 if result.extracted_candidate else 0.3,
            },
        }

    elif eval_type == "code":
        result = CODE_EVAL.evaluate(question=question, reference=ref, candidate=response)
        correctness = result.score
        correct = result.correct
        method = result.method
        flags = []
        if correct is False:
            flags.append("incorrect")
        elif correct is None:
            flags.append("unverifiable")
        if correctness < 0.4:
            flags.append("low_correctness")
        struct = result.details.get("structural_similarity",
                                    result.details.get("patch_similarity"))
        return {
            "answer_type": "code",
            "correctness": round(correctness, 4),
            "correct": correct,
            "quality_score": int(max(1, min(10, round(1 + correctness * 9)))),
            "quality_continuous": round(correctness, 4),
            "method": method,
            "flags": flags,
            "dimensions": {
                "accuracy": round(correctness, 3),
                "technical_correctness": round(correctness, 3),
                "completeness": round(min(1.0, correctness * 0.9 + 0.1), 3),
                "clarity": 0.9 if result.method != "syntax" else 0.5,
                "usefulness": round(correctness, 3),
                "originality": 0.6,
                "relevance": 0.85 if struct is not None else 0.5,
            },
        }
    else:
        result = QEE.evaluate_record(record, reference=ref)
        return result


def mean_std(values):
    if not values:
        return 0.0, 0.0
    n = len(values)
    m = sum(values) / n
    var = sum((v - m) ** 2 for v in values) / max(n - 1, 1)
    return m, math.sqrt(var)


def ci_95(values):
    if len(values) < 2:
        return 0.0, 0.0
    m, se = mean_std(values)
    n = len(values)
    t_approx = 1.96 if n >= 30 else 2.045 if n >= 20 else 2.228 if n >= 10 else 4.303
    half_width = t_approx * se / math.sqrt(n)
    return m - half_width, m + half_width


def evaluate_model(model, tokenizer, device, model_name, eval_type_tag):
    """Evaluate a model on all eval sets. Returns (all_results, aggregates)."""
    all_results = {}

    for ename in sorted(EVAL_SETS):
        epath = EVAL_SETS[ename]
        if not epath.exists():
            print(f"  {ename}: NOT FOUND")
            continue
        with open(epath) as f:
            records = [json.loads(l) for l in f]
        eval_type = EVAL_DISPATCH[ename]
        print(f"    {ename} ({len(records)} records, eval_type={eval_type})...", flush=True)

        t_start = time.perf_counter()
        results = []
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i:i+BATCH_SIZE]
            generations, _ = generate_batch(model, tokenizer, batch, device)
            for j, rec in enumerate(batch):
                resp, n_tok = generations[j]
                score = score_record(rec, resp, eval_type)
                results.append({
                    "record_id": rec.get("record_id", f"unknown_{i+j}"),
                    "view_id": rec.get("view_id"),
                    "category": rec.get("category"),
                    "difficulty": rec.get("difficulty"),
                    "predicted_response": resp,
                    "reference_answer": (rec.get("canonical_answer") or "")[:500],
                    "tokens_generated": n_tok,
                    "correctness": score["correctness"],
                    "reasoning_quality": score["quality_continuous"],
                    "hallucination_rate": 1.0 if score["correct"] is False and score["correctness"] < 0.4 else 0.0,
                    "answer_format_consistency": 1.0 if score["method"] not in ("empty", "no_final_answer") else 0.0,
                    "qee_v2": score,
                })
        elapsed = time.perf_counter() - t_start
        valid = [r for r in results if r.get("correctness") is not None]
        mean_corr = sum(r["correctness"] for r in valid) / len(valid) if valid else 0
        print(f"      {len(valid)}/{len(results)} scored, mean_correctness={mean_corr:.4f} in {elapsed:.1f}s", flush=True)
        all_results[ename] = results

        # Save per-example
        out_path = OUTPUT_DIR / f"{model_name}_{ename}_per_example.jsonl"
        with open(out_path, "w") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Aggregate
    aggregates = {}
    for ename, results in all_results.items():
        valid = [r for r in results if r.get("correctness") is not None]
        if not valid:
            aggregates[ename] = {"n": 0}
            continue
        corr_vals = [r["correctness"] for r in valid]
        n = len(corr_vals)
        m_corr, se_corr = mean_std(corr_vals)
        ci_lo, ci_hi = ci_95(corr_vals)
        qual_vals = [r["reasoning_quality"] for r in valid if r.get("reasoning_quality") is not None]
        fmt_vals = [r["answer_format_consistency"] for r in valid]
        hall_vals = [r["hallucination_rate"] for r in valid]
        aggregates[ename] = {
            "n": n,
            "correctness_mean": round(m_corr, 4),
            "correctness_se": round(se_corr / math.sqrt(n), 4) if n > 1 else 0.0,
            "correctness_ci95_lo": round(ci_lo, 4),
            "correctness_ci95_hi": round(ci_hi, 4),
            "quality_mean": round(sum(qual_vals) / len(qual_vals), 4) if qual_vals else None,
            "format_consistency": round(sum(fmt_vals) / len(fmt_vals), 4) if fmt_vals else None,
            "hallucination_rate": round(sum(hall_vals) / len(hall_vals), 4) if hall_vals else None,
            "correctness_values": corr_vals,
        }

    return all_results, aggregates


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", type=str, default="all",
                        choices=["general", "math", "code", "systems", "all"])
    args = parser.parse_args()

    print(f"=== Atlas 500M Pilot v3 — QEE v2 Capability Evaluation ===")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device} | GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"Base model: {BASE_MODEL}")
    print(f"Greedy decoding, max_new_tokens={MAX_NEW_TOKENS}, batch_size={BATCH_SIZE}")
    print()

    tokenizer = load_tokenizer()
    base_model, dev = load_base_model()
    print(f"Base model loaded on {dev}")

    arms_to_eval = ["general", "math", "code", "systems"] if args.arm == "all" else [args.arm]

    all_aggregates = {}
    all_per_example = {}

    for arm in arms_to_eval:
        print(f"\n--- Model: {arm} (v3) ---", flush=True)
        apath = ADAPTERS.get(arm)
        if not apath:
            print(f"  SKIP: No adapter found")
            continue

        model = PeftModel.from_pretrained(base_model, apath)
        model.eval()
        print(f"  Adapter loaded: {apath}")

        results, aggs = evaluate_model(model, tokenizer, dev, f"{arm}_v3", "v3")
        all_aggregates[f"{arm}_v3"] = aggs
        all_per_example[f"{arm}_v3"] = results
        print(f"  Saved per-example results to {OUTPUT_DIR}/")

    # Domain gains (v3)
    gains_v3 = {}
    eval_map = {"math": "math_eval_v2", "code": "code_eval_v2", "systems": "systems_eval_v2"}
    for specialist in ["math", "code", "systems"]:
        target = eval_map[specialist]
        base_corr = all_aggregates.get("base_v3", {}).get(target, {}).get("correctness_mean")
        spec_corr = all_aggregates.get(f"{specialist}_v3", {}).get(target, {}).get("correctness_mean")
        gen_corr = all_aggregates.get("general_v3", {}).get(target, {}).get("correctness_mean")
        if spec_corr is not None:
            gains_v3[specialist] = {
                "target_domain": target,
                "delta_vs_base": round(spec_corr - (base_corr or 0), 4),
                "delta_vs_general": round(spec_corr - gen_corr, 4) if gen_corr is not None else None,
                "specialist_score": spec_corr,
                "base_score": base_corr,
                "general_score": gen_corr,
            }

    # V2 vs V3 comparison
    v2_vs_v3 = {}
    for arm in ["general", "math", "code", "systems"]:
        v2_vs_v3[arm] = {}
        for ename in EVAL_SETS:
            v3_corr = all_aggregates.get(f"{arm}_v3", {}).get(ename, {}).get("correctness_mean")
            v2_data = V2_RESULTS.get(arm, {}).get(ename, [])
            if v2_data:
                valid_v2 = [r for r in v2_data if r.get("correctness") is not None]
                v2_corr = sum(r["correctness"] for r in valid_v2) / len(valid_v2) if valid_v2 else None
            else:
                v2_corr = None
            v2_vs_v3[arm][ename] = {
                "v2_correctness": v2_corr,
                "v3_correctness": v3_corr,
                "delta": round(v3_corr - v2_corr, 4) if v2_corr is not None and v3_corr is not None else None,
            }

    # Save full results
    full_results = {
        "experiment": "atlas-500m-pilot-v3-scale",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "base_model": BASE_MODEL,
        "device": device,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
        "torch_version": torch.__version__,
        "eval_sets": {name: {"n": len(json.loads(l) for l in open(epath))} for name, epath in EVAL_SETS.items()},
        "aggregates": all_aggregates,
        "domain_gains": gains_v3,
        "v2_vs_v3": v2_vs_v3,
    }

    with open(OUTPUT_DIR / "evaluation_results.json", "w") as f:
        json.dump(full_results, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Print summary
    print(f"\n=== V3 EVALUATION COMPLETE ===")
    print(f"Results saved to {OUTPUT_DIR}")
    print()
    for arm in ["general", "math", "code", "systems"]:
        key = f"{arm}_v3"
        if key not in all_aggregates:
            continue
        aggs = all_aggregates[key]
        print(f"{arm}:")
        for ename, agg in aggs.items():
            print(f"  {ename}: n={agg['n']}, corr={agg['correctness_mean']:.4f}")
        print()

    print("=== V2 vs V3 Comparison ===")
    for arm, evals in v2_vs_v3.items():
        print(f"{arm}:")
        for ename, cmp in evals.items():
            delta_str = f"delta={cmp['delta']:+.4f}" if cmp['delta'] is not None else "N/A"
            print(f"  {ename}: v2={cmp['v2_correctness']:.4f} -> v3={cmp['v3_correctness']:.4f} {delta_str}")
        print()

    return full_results


if __name__ == "__main__":
    main()
