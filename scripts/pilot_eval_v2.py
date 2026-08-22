#!/usr/bin/env python3
"""
Atlas 500M Pilot v2 — Evaluation Script

Evaluates v2 models across all domains using corrected eval sets.
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
ADAPTER_BASE = ROOT / "artifacts" / "pilot" / "v0.2"
EVAL_BASE = ROOT / "evaluation" / "eval_sets" / "protocol_v2"
OUTPUT_DIR = ROOT / "reports" / "pilot_eval_v2"

EVAL_SETS = {
    "math_eval_v2": EVAL_BASE / "math_eval_v2.jsonl",
    "code_eval_v2": EVAL_BASE / "code_eval_v2.jsonl",
    "systems_eval_v2": EVAL_BASE / "systems_eval_v2.jsonl",
}
EVAL_DISPATCH = {
    "math_eval_v2": "math",
    "code_eval_v2": "code",
    "systems_eval_v2": "code",  # systems eval contains patch answers
}
ADAPTERS = {
    "base": None,
    "general": ADAPTER_BASE / "general" / "adapter",
    "math": ADAPTER_BASE / "math" / "adapter",
    "code": ADAPTER_BASE / "code" / "adapter",
    "systems": ADAPTER_BASE / "systems" / "adapter",
}

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


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"=== Atlas 500M Pilot v2 — QEE v2 Capability Evaluation ===")
    print(f"Device: {device} | GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"Base model: {BASE_MODEL}")
    print(f"Greedy decoding, max_new_tokens={MAX_NEW_TOKENS}, batch_size={BATCH_SIZE}")
    print()

    tokenizer = load_tokenizer()
    model, dev = load_base_model()
    print(f"Base model loaded on {dev}")
    print()

    # Load eval sets
    eval_data = {}
    for ename, epath in EVAL_SETS.items():
        if epath.exists():
            with epath.open() as f:
                eval_data[ename] = [json.loads(l) for l in f]
            print(f"Eval set {ename}: {len(eval_data[ename])} records (dispatch: {EVAL_DISPATCH[ename]})")
        else:
            print(f"Eval set {ename}: NOT FOUND")

    all_results = {}

    for mname, apath in ADAPTERS.items():
        print(f"\n--- Model: {mname} ---", flush=True)
        t_model_start = time.perf_counter()

        if apath and (apath / "adapter_config.json").exists():
            model = PeftModel.from_pretrained(model, apath)
            model.eval()
            print(f"  Adapter loaded: {apath.name}")

        all_results[mname] = {}

        for ename in sorted(eval_data):
            records = eval_data[ename]
            eval_type = EVAL_DISPATCH[ename]
            print(f"    {ename} ({len(records)} records, eval_type={eval_type})...", flush=True)
            t_start = time.perf_counter()
            results = []
            for i in range(0, len(records), BATCH_SIZE):
                batch = records[i:i+BATCH_SIZE]
                generations, _ = generate_batch(model, tokenizer, batch, dev)
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
            all_results[mname][ename] = results

            out_path = OUTPUT_DIR / f"{mname}_{ename}_per_example.jsonl"
            with out_path.open("w") as f:
                for r in results:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"      Saved: {out_path.name}", flush=True)

        t_model_total = time.perf_counter() - t_model_start
        print(f"  Total time for {mname}: {t_model_total:.1f}s")

    # Aggregate
    aggregates = {}
    for mname, evals in all_results.items():
        aggregates[mname] = {}
        for ename, results in evals.items():
            valid = [r for r in results if r.get("correctness") is not None]
            if not valid:
                aggregates[mname][ename] = {"n": 0}
                continue
            corr_vals = [r["correctness"] for r in valid]
            n = len(corr_vals)
            m_corr, se_corr = mean_std(corr_vals)
            ci_lo, ci_hi = ci_95(corr_vals)
            qual_vals = [r["reasoning_quality"] for r in valid if r.get("reasoning_quality") is not None]
            fmt_vals = [r["answer_format_consistency"] for r in valid]
            hall_vals = [r["hallucination_rate"] for r in valid]
            aggregates[mname][ename] = {
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

    # Domain gains
    gains = {}
    eval_map = {"math": "math_eval_v2", "code": "code_eval_v2", "systems": "systems_eval_v2"}
    for specialist in ["math", "code", "systems"]:
        target = eval_map[specialist]
        base_corr = aggregates.get("base", {}).get(target, {}).get("correctness_mean")
        spec_corr = aggregates.get(specialist, {}).get(target, {}).get("correctness_mean")
        gen_corr = aggregates.get("general", {}).get(target, {}).get("correctness_mean")
        if base_corr is not None and spec_corr is not None:
            gains[specialist] = {
                "target_domain": target,
                "delta_vs_base": round(spec_corr - base_corr, 4),
                "delta_vs_general": round(spec_corr - gen_corr, 4) if gen_corr is not None else None,
                "specialist_score": spec_corr,
                "base_score": base_corr,
                "general_score": gen_corr,
            }

    # Cross-domain
    cross_gains = {}
    for specialist in ["math", "code", "systems"]:
        cross_gains[specialist] = {}
        for other in ["math", "code", "systems"]:
            if other == specialist:
                continue
            target = eval_map[other]
            base_corr = aggregates.get("base", {}).get(target, {}).get("correctness_mean")
            spec_corr = aggregates.get(specialist, {}).get(target, {}).get("correctness_mean")
            gen_corr = aggregates.get("general", {}).get(target, {}).get("correctness_mean")
            if base_corr is not None and spec_corr is not None:
                cross_gains[specialist][other] = {
                    "delta_vs_base": round(spec_corr - base_corr, 4),
                    "delta_vs_general": round(spec_corr - gen_corr, 4) if gen_corr is not None else None,
                    "specialist_score": spec_corr,
                    "base_score": base_corr,
                }

    general_vs_base = {}
    for ename in eval_data:
        base_corr = aggregates.get("base", {}).get(ename, {}).get("correctness_mean")
        gen_corr = aggregates.get("general", {}).get(ename, {}).get("correctness_mean")
        if base_corr is not None and gen_corr is not None:
            general_vs_base[ename] = round(gen_corr - base_corr, 4)

    # Training losses
    training_losses = {}
    for arm in ["general", "math", "code", "systems"]:
        meta_path = ADAPTER_BASE / arm / "training_metadata.json"
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
                training_losses[arm] = meta.get("avg_loss")

    # Save
    full_results = {
        "experiment": "atlas_500m_pilot_v2_format_fixed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "base_model": BASE_MODEL,
        "device": device,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
        "torch_version": torch.__version__,
        "training_losses": training_losses,
        "eval_sets": {name: {"n": len(recs), "dispatch": EVAL_DISPATCH[name]} for name, recs in eval_data.items()},
        "aggregates": {
            mname: {
                ename: {k: v for k, v in agg.items() if k not in ("correctness_values",)}
                for ename, agg in aggs.items()
            }
            for mname, aggs in aggregates.items()
        },
        "domain_gains": gains,
        "cross_domain_gains": cross_gains,
        "general_vs_base": general_vs_base,
    }

    with (OUTPUT_DIR / "evaluation_results.json").open("w") as f:
        json.dump(full_results, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\n=== COMPLETE ===")
    print(f"Results saved to {OUTPUT_DIR}")
    return full_results, aggregates, gains, cross_gains, general_vs_base


if __name__ == "__main__":
    main()
