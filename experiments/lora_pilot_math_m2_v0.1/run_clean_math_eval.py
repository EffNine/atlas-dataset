#!/usr/bin/env python3
"""
run_clean_math_eval.py — Evaluate M1, M2, M2' LoRA adapters on the clean
math evaluation set (math_eval_v2_clean, N=87).

The clean set = math_eval_v2 minus 13 M2 training-overlap records.
Zero training/eval overlap for ALL three models.

Outputs per experiment:
  - experiments/lora_pilot_math_v0.1/evaluation/clean_math/m1_clean_evaluation.json
  - experiments/lora_pilot_math_m2_v0.1/evaluation/clean_math/m2_clean_evaluation.json
  - experiments/lora_pilot_math_m2prime_v0.1/evaluation/clean_math/m2prime_clean_evaluation.json
  - Shared per-model results: experiments/lora_pilot_math_m2_v0.1/evaluation/clean_math/all_models_results.jsonl
  - Combined comparison: experiments/lora_pilot_math_m2_v0.1/evaluation/clean_math/comparison.json

Does NOT retrain. Does NOT modify frozen assets.
Uses the same protocol as existing M2/M2' evaluations.
"""
from __future__ import annotations

import json
import math
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
REPO = Path(__file__).resolve().parent.parent.parent
EVAL_V2_DIR = REPO / "evaluation" / "eval_sets" / "protocol_v2"
CERT_DIR = REPO / "metadata" / "evaluation" / "protocol_v2_baseline"
OUT_DIR = REPO / "experiments" / "lora_pilot_math_m2_v0.1" / "evaluation" / "clean_math"

M1_EXP = REPO / "experiments" / "lora_pilot_math_v0.1"
M2_EXP = REPO / "experiments" / "lora_pilot_math_m2_v0.1"
M2PRIME_EXP = REPO / "experiments" / "lora_pilot_math_m2prime_v0.1"

MAX_NEW_TOKENS = 256
ANSTYPE = "math"

sys.path.insert(0, str(REPO / "scripts"))
from evaluation_engine.v2.engine import QeeV2Engine


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_prompt(record, tokenizer) -> str:
    messages = record.get("messages") or []
    if messages:
        try:
            return tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            return "\n".join(
                f"{m['role']}: {m['content']}" for m in messages) + "\nassistant: "
    return tokenizer.apply_chat_template(
        [{"role": "user", "content": record.get("problem", "")}],
        tokenize=False, add_generation_prompt=True)


def get_reference(record) -> str:
    for m in record.get("messages") or []:
        if m.get("role") == "assistant":
            return (m.get("content") or "").strip()
    return record.get("canonical_answer", "") or ""


def user_text(record) -> str:
    for m in record.get("messages") or []:
        if m.get("role") == "user":
            return (m.get("content") or "").strip()
    return record.get("problem", "")


@torch.no_grad()
def generate(model, tokenizer, record, device):
    prompt = build_prompt(record, tokenizer)
    inputs = tokenizer(prompt, return_tensors="pt").to(device)
    input_len = inputs["input_ids"].shape[1]
    t0 = time.perf_counter()
    gen = model.generate(
        **inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False,
        pad_token_id=tokenizer.pad_token_id)
    latency = time.perf_counter() - t0
    new_tokens = gen[0][input_len:]
    text = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    return text, int(new_tokens.numel()), latency


def score_qee_v2(question, reference, response):
    engine = QeeV2Engine()
    _, result = engine._type_result(ANSTYPE, question, reference, response)
    breakdown = engine._dimensions(ANSTYPE, result, question, reference, response)
    dims = {k: v["score"] for k, v in breakdown.items()}
    raw = sum(engine.weights[k] * dims[k] for k in engine.weights)
    continuous, score = engine._map_to_scale(raw)
    flags = []
    if result.correct is False:
        flags.append("incorrect")
    elif result.correct is None:
        flags.append("unverifiable")
    if result.score < 0.4:
        flags.append("low_correctness")
    return {
        "answer_type": ANSTYPE,
        "correctness": round(float(result.score), 4),
        "correct": result.correct,
        "quality_score": score,
        "quality_continuous": round(float(continuous), 4),
        "method": getattr(result, "method", "rubric"),
        "flags": flags,
        "dimensions": {k: round(v, 3) for k, v in dims.items()},
    }


def metrics(score):
    correctness = float(score["correctness"])
    reasoning_quality = float(score["quality_continuous"])
    hallucination = 1.0 if score["correct"] is False and correctness < 0.4 else 0.0
    format_ok = 1.0 if score["method"] != "no_final_answer" else 0.0
    return {
        "correctness": correctness,
        "reasoning_quality": reasoning_quality,
        "hallucination_rate": hallucination,
        "answer_format_consistency": format_ok,
    }


def compute_stats(values):
    if not values:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "n": 0}
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / max(1, n - 1) if n > 1 else 0.0
    std = math.sqrt(variance)
    return {"mean": round(mean, 6), "std": round(std, 6),
            "min": round(min(values), 6), "max": round(max(values), 6), "n": n}


def json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(json_safe(v) for v in obj)
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def gpu_info_fn():
    if not torch.cuda.is_available():
        return None
    p = torch.cuda.get_device_properties(0)
    return {
        "device": "cuda", "gpu_name": p.name,
        "vram_total_mib": round(p.total_memory / 1024**2, 2),
        "torch_version": torch.__version__, "cuda_version": torch.version.cuda,
    }


def paired_ttest(a, b):
    if len(a) < 2:
        return None, None
    diffs = [ai - bi for ai, bi in zip(a, b)]
    n = len(diffs)
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    se = math.sqrt(var / n) if var > 0 else 1e-10
    t = mean / se
    p = 2 * _normal_cdf(-abs(t))
    return round(t, 4), round(p, 6)


def _normal_cdf(x):
    if x < -8: return 0.0
    if x > 8: return 1.0
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x) / math.sqrt(2)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
    return 0.5 * (1.0 + sign * y)


def mcnemar_test(a, b):
    """McNemar's test for paired binary data.
    a, b: lists of 0/1 correctness scores.
    Returns: chi2 statistic, p-value (approx), b (a=1,b=0), c (a=0,b=1)
    """
    from collections import Counter
    cont = Counter(zip(a, b))
    b_count = cont.get((1, 0), 0)  # a correct, b incorrect
    c_count = cont.get((0, 1), 0)  # a incorrect, b correct
    if b_count + c_count == 0:
        return 0.0, 1.0, b_count, c_count
    chi2 = (abs(b_count - c_count) - 1) ** 2 / (b_count + c_count)
    # Approximate p-value from chi-square(1)
    p = math.exp(-chi2 / 2)
    return round(chi2, 4), round(p, 4), b_count, c_count


def wilson_ci(successes, n, z=1.96):
    """Wilson score confidence interval for a proportion."""
    if n == 0:
        return (0.0, 0.0)
    p_hat = successes / n
    denominator = 1 + z**2 / n
    center = (p_hat + z**2 / (2 * n)) / denominator
    margin = z * math.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2)) / denominator
    return (round(max(0, center - margin), 4), round(min(1, center + margin), 4))


def run_eval(records, model, tokenizer, device, label):
    results = []
    for rec in records:
        rid = rec.get("record_id")
        try:
            response, n_tokens, latency = generate(model, tokenizer, rec, device)
            score = score_qee_v2(user_text(rec), get_reference(rec), response)
            met = metrics(score)
            tps = n_tokens / latency if latency > 0 else 0.0
            results.append({
                "record_id": rid,
                "category": rec.get("category"),
                "predicted_response": response,
                "reference_answer": get_reference(rec),
                "latency_s": round(latency, 4),
                "tokens_generated": n_tokens,
                "tokens_per_sec": round(tps, 2),
                **met,
                "v2": dict(score),
                "run_label": label,
            })
            if device == "cuda":
                torch.cuda.empty_cache()
        except Exception as e:
            results.append({
                "record_id": rid,
                "category": rec.get("category"),
                "predicted_response": f"ERROR: {e}",
                "reference_answer": get_reference(rec),
                "latency_s": None, "tokens_generated": None, "tokens_per_sec": None,
                "correctness": None, "reasoning_quality": None,
                "hallucination_rate": None, "answer_format_consistency": None,
                "v2": {}, "run_label": label,
            })
    return results


def aggregate_results(results, label):
    valid = [r for r in results if r.get("correctness") is not None]
    n = len(valid) if valid else 1
    return {
        "label": label,
        "correctness": {"mean": round(sum(r["correctness"] for r in valid) / n, 4),
                        **compute_stats([r["correctness"] for r in valid])},
        "reasoning_quality": {"mean": round(sum(r["reasoning_quality"] for r in valid) / n, 4),
                              **compute_stats([r["reasoning_quality"] for r in valid])},
        "hallucination_rate": {"mean": round(sum(r["hallucination_rate"] for r in valid) / n, 4),
                               **compute_stats([r["hallucination_rate"] for r in valid])},
        "answer_format_consistency": {"mean": round(sum(r["answer_format_consistency"] for r in valid) / n, 4),
                                       **compute_stats([r["answer_format_consistency"] for r in valid])},
        "evaluated_examples": len(valid),
        "total_examples": len(results),
        "truncation_rate": round(sum(1 for r in results if r.get("stop_reason") == "max_length") / max(1, len(results)), 4),
        "stop_reason_counts": dict(Counter(r.get("stop_reason") for r in results)),
        "method_counts": dict(Counter(r.get("v2", {}).get("method", "unknown") for r in valid)),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"=== Clean Math Eval | device={device} | N=87 ===")

    # Load clean eval set
    eval_file = EVAL_V2_DIR / "math_eval_v2_clean.jsonl"
    manifest_file = EVAL_V2_DIR / "math_eval_v2_clean_manifest.json"
    records = load_jsonl(eval_file)
    manifest = json.loads(manifest_file.read_text())
    print(f"Eval set: math_eval_v2_clean, N={len(records)}")
    print(f"Checksum: {manifest['checksum']['records']}")

    # Load protocol cert
    cert = json.loads((CERT_DIR / "protocol_certificate.json").read_text())
    print(f"Protocol v2 cert: readiness={cert['readiness_verdict']}")

    # Load model and tokenizer
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
    )
    print("Loading base model ...")
    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL, use_fast=True, token=None)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, quantization_config=bnb_config, device_map="cpu",
        trust_remote_code=False, token=None)
    model.eval()

    if device == "cuda":
        model = model.to(device)
        print(f"GPU: {torch.cuda.get_device_properties(0).name}")

    # Define experiments to run
    experiments = [
        ("m1", M1_EXP / "checkpoints", "lora_pilot_math_v0.1"),
        ("m2", M2_EXP / "checkpoints", "lora_pilot_math_m2_v0.1"),
        ("m2prime", M2PRIME_EXP / "checkpoints", "lora_pilot_math_m2prime_v0.1"),
    ]

    all_results = {}
    all_aggs = {}

    for label, adapter_dir, exp_id in experiments:
        if not (adapter_dir / "adapter_config.json").exists():
            print(f"\n  SKIP {label}: adapter not found at {adapter_dir}")
            continue
        print(f"\n--- Evaluating {label} ---")
        adapter_config = json.loads((adapter_dir / "adapter_config.json").read_text())
        print(f"  Loading adapter (r={adapter_config.get('r')}, alpha={adapter_config.get('lora_alpha')}) ...")

        # Reload model for each adapter
        if label != "m1":
            del model
            torch.cuda.empty_cache() if device == "cuda" else None
            import gc; gc.collect()

        model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL, quantization_config=bnb_config, device_map="cpu",
            trust_remote_code=False, token=None)
        model = PeftModel.from_pretrained(model, adapter_dir)
        model.eval()
        if device == "cuda":
            model = model.to(device)

        results = run_eval(records, model, tokenizer, device, label)
        agg = aggregate_results(results, label)
        all_results[label] = results
        all_aggs[label] = agg
        print(f"  {label}: correctness={agg['correctness']['mean']:.4f}, N={agg['evaluated_examples']}")

    # Save per-experiment results
    for label, results in all_results.items():
        exp_dir = None
        if label == "m1":
            exp_dir = M1_EXP / "evaluation" / "clean_math"
        elif label == "m2":
            exp_dir = M2_EXP / "evaluation" / "clean_math"
        elif label == "m2prime":
            exp_dir = M2PRIME_EXP / "evaluation" / "clean_math"
        if exp_dir:
            exp_dir.mkdir(parents=True, exist_ok=True)
            agg = all_aggs[label]
            report = {
                "experiment_id": next(e[2] for e in experiments if e[0] == label),
                "evaluation_id": f"clean_math_{label}",
                "status": "COMPLETE",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "hardware": gpu_info_fn(),
                "dataset": {
                    "eval_set": "math_eval_v2_clean",
                    "eval_jsonl": str(eval_file),
                    "n_records": len(records),
                    "checksum": manifest["checksum"]["records"],
                },
                "aggregate": {
                    "correctness": agg["correctness"]["mean"],
                    "reasoning_quality": agg["reasoning_quality"]["mean"],
                    "hallucination_rate": agg["hallucination_rate"]["mean"],
                    "answer_format_consistency": agg["answer_format_consistency"]["mean"],
                    "evaluated_examples": agg["evaluated_examples"],
                    "total_examples": agg["total_examples"],
                    "truncation_rate": agg["truncation_rate"],
                },
            }
            (exp_dir / f"{label}_clean_evaluation.json").write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            with (exp_dir / f"{label}_clean_per_example.jsonl").open("w", encoding="utf-8") as f:
                for r in results:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Build combined comparison
    print("\n=== Combined Comparison ===")
    by_id = {}
    for label, results in all_results.items():
        for r in results:
            rid = r["record_id"]
            if rid not in by_id:
                by_id[rid] = {"record_id": rid, "difficulty": records[[rec["record_id"] for rec in records].index(rid)].get("difficulty") if rid in [rec["record_id"] for rec in records] else None}
            if r.get("correctness") is not None:
                by_id[rid][label] = r["correctness"]

    comparison = []
    for rid, data in by_id.items():
        m1c = data.get("m1")
        m2c = data.get("m2")
        m2pc = data.get("m2prime")
        if m1c is None or m2c is None or m2pc is None:
            continue
        comparison.append({
            "record_id": rid,
            "difficulty": data.get("difficulty"),
            "m1": round(m1c, 4),
            "m2": round(m2c, 4),
            "m2prime": round(m2pc, 4),
            "m2_vs_m1": round(m2c - m1c, 4),
            "m2prime_vs_m1": round(m2pc - m1c, 4),
            "m2prime_vs_m2": round(m2pc - m2c, 4),
        })

    # Statistical analysis
    m1_scores = [r["m1"] for r in comparison]
    m2_scores = [r["m2"] for r in comparison]
    m2p_scores = [r["m2prime"] for r in comparison]

    # Paired t-tests
    m2_vs_m1_t, m2_vs_m1_p = paired_ttest(m1_scores, m2_scores)
    m2p_vs_m1_t, m2p_vs_m1_p = paired_ttest(m1_scores, m2p_scores)
    m2p_vs_m2_t, m2p_vs_m2_p = paired_ttest(m2_scores, m2p_scores)

    # McNemar's tests
    m2_mcnemar_chi2, m2_mcnemar_p, m2_b, m2_c = mcnemar_test(m1_scores, m2_scores)
    m2p_mcnemar_chi2, m2p_mcnemar_p, m2p_b, m2p_c = mcnemar_test(m1_scores, m2p_scores)

    # Wilson CIs
    m1_wilson = wilson_ci(sum(m1_scores), len(m1_scores))
    m2_wilson = wilson_ci(sum(m2_scores), len(m2_scores))
    m2p_wilson = wilson_ci(sum(m2p_scores), len(m2p_scores))

    # Discordant pairs
    from collections import Counter
    def discordant_counts(scores_a, scores_b):
        cont = Counter(zip(scores_a, scores_b))
        return {
            "both_correct": cont.get((1.0, 1.0), 0),
            "both_incorrect": cont.get((0.0, 0.0), 0),
            "a_correct_b_incorrect": cont.get((1.0, 0.0), 0),
            "a_incorrect_b_correct": cont.get((0.0, 1.0), 0),
        }

    m2_discord = discordant_counts(m1_scores, m2_scores)
    m2p_discord = discordant_counts(m1_scores, m2p_scores)

    # Power analysis
    def power_approx(p1, p2, n):
        diff = abs(p1 - p2)
        pooled = (p1 + p2) / 2
        se = math.sqrt(2 * pooled * (1 - pooled) / n)
        z = diff / se - 1.96
        return max(0, min(1, 0.5 * (1 + math.erf(z / math.sqrt(2)))))

    m1_mean = sum(m1_scores) / len(m1_scores)
    m2_mean = sum(m2_scores) / len(m2_scores)
    m2p_mean = sum(m2p_scores) / len(m2p_scores)

    power_m2 = power_approx(m1_mean, m2_mean, len(m1_scores))
    power_m2p = power_approx(m1_mean, m2p_mean, len(m1_scores))

    comparison_report = {
        "experiment_id": "clean_math_eval_v2",
        "evaluation_id": "m1_m2_m2prime_clean_comparison",
        "status": "COMPLETE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hardware": gpu_info_fn(),
        "dataset": {
            "eval_set": "math_eval_v2_clean",
            "eval_jsonl": str(eval_file),
            "n_records": len(records),
            "checksum": manifest["checksum"]["records"],
            "description": "math_eval_v2 minus 13 M2 training-overlap records",
        },
        "models": {
            "m1": {"correctness_mean": round(m1_mean, 4), "n": len(m1_scores),
                   "wilson_ci_95": m1_wilson},
            "m2": {"correctness_mean": round(m2_mean, 4), "n": len(m2_scores),
                   "wilson_ci_95": m2_wilson},
            "m2prime": {"correctness_mean": round(m2p_mean, 4), "n": len(m2p_scores),
                        "wilson_ci_95": m2p_wilson},
        },
        "deltas": {
            "m2_vs_m1": round(m2_mean - m1_mean, 4),
            "m2prime_vs_m1": round(m2p_mean - m1_mean, 4),
            "m2prime_vs_m2": round(m2p_mean - m2_mean, 4),
        },
        "statistical_comparison": {
            "m2_vs_m1": {
                "paired_ttest": {"t_stat": m2_vs_m1_t, "p_value": m2_vs_m1_p,
                                 "interpretation": "significant" if m2_vs_m1_p and m2_vs_m1_p < 0.05 else "not significant"},
                "mcnemar": {"chi2": m2_mcnemar_chi2, "p_value": m2_mcnemar_p,
                            "discordant_b": m2_b, "discordant_c": m2_c},
            },
            "m2prime_vs_m1": {
                "paired_ttest": {"t_stat": m2p_vs_m1_t, "p_value": m2p_vs_m1_p,
                                 "interpretation": "significant" if m2p_vs_m1_p and m2p_vs_m1_p < 0.05 else "not significant"},
                "mcnemar": {"chi2": m2p_mcnemar_chi2, "p_value": m2p_mcnemar_p,
                            "discordant_b": m2p_b, "discordant_c": m2p_c},
            },
            "m2prime_vs_m2": {
                "paired_ttest": {"t_stat": m2p_vs_m2_t, "p_value": m2p_vs_m2_p,
                                 "interpretation": "significant" if m2p_vs_m2_p and m2p_vs_m2_p < 0.05 else "not significant"},
            },
        },
        "power_analysis": {
            "m2_vs_m1": {"observed_diff": round(abs(m2_mean - m1_mean), 4),
                         "power_at_n87": round(power_m2, 4)},
            "m2prime_vs_m1": {"observed_diff": round(abs(m2p_mean - m1_mean), 4),
                              "power_at_n87": round(power_m2p, 4)},
            "note": "Power is low for detecting small effects (2-3pp) at N=87. N>=500 needed for >10% power.",
        },
        "discordant_pairs": {
            "m2_vs_m1": m2_discord,
            "m2prime_vs_m1": m2p_discord,
        },
        "per_example": comparison,
    }

    (OUT_DIR / "comparison.json").write_text(
        json.dumps(comparison_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with (OUT_DIR / "all_models_results.jsonl").open("w", encoding="utf-8") as f:
        for r in comparison:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n=== Results ===")
    print(f"M1 correctness:  {m1_mean:.4f} (95% CI: {m1_wilson})")
    print(f"M2 correctness:  {m2_mean:.4f} (95% CI: {m2_wilson})")
    print(f"M2' correctness: {m2p_mean:.4f} (95% CI: {m2p_wilson})")
    print(f"M2 vs M1 delta:  {m2_mean - m1_mean:+.4f} (t={m2_vs_m1_t}, p={m2_vs_m1_p:.4f}, McNemar p={m2_mcnemar_p:.4f})")
    print(f"M2' vs M1 delta: {m2p_mean - m1_mean:+.4f} (t={m2p_vs_m1_t}, p={m2p_vs_m1_p:.4f}, McNemar p={m2p_mcnemar_p:.4f})")
    print(f"Power (M2 vs M1): {power_m2:.1%}")
    print(f"Power (M2' vs M1): {power_m2p:.1%}")
    print(f"\nWrote to {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
