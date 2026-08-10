#!/usr/bin/env python3
"""
run_5b3_expanded_eval.py — Sprint 5B.3 Expanded Evaluation

Evaluates the frozen M1 LoRA adapter (lora_pilot_math_v0.1) on the
Protocol v2 math eval set (N=100) using QEE v2. Produces:

  * A new baseline run on math_eval_v2 (same base model, no adapter)
  * Post-training eval on the same split with the LoRA adapter
  * Per-example deltas, statistical comparison, and the expanded report

Does NOT retrain. Does NOT modify frozen assets.
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

# Resolve repo root robustly: try __file__ first (absolute when run directly),
# fall back to cwd-based detection.
_REPO_CANDIDATE = Path(__file__).resolve().parent.parent
if (_REPO_CANDIDATE / "scripts" / "evaluation_engine").exists():
    REPO = _REPO_CANDIDATE
else:
    # __file__ is relative; walk up from cwd until we find the repo root.
    _cwd = Path.cwd().resolve()
    _test = _cwd
    for _ in range(5):
        if (_test / "scripts" / "evaluation_engine").exists():
            REPO = _test
            break
        _test = _test.parent
    else:
        raise RuntimeError(f"Cannot find Atlas repo root from {Path(__file__)}")

sys.path.insert(0, str(REPO / "scripts"))
from credential_helper import get_hf_token

EXPERIMENT_DIR = REPO / "experiments" / "lora_pilot_math_v0.1"
ADAPTER_DIR = EXPERIMENT_DIR / "checkpoints"
EVAL_V2_DIR = REPO / "evaluation" / "eval_sets" / "protocol_v2"
CERT_DIR = REPO / "metadata" / "evaluation" / "protocol_v2_baseline"
OUT_DIR = REPO / "experiments" / "lora_pilot_math_v0.1" / "evaluation" / "expanded_5b3"

BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
MODEL_REVISION = "a09a35458c702b33eeacc393d103063234e8bc28"
SEED = 42

MAX_NEW_TOKENS = 256
ANSTYPE = "math"


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_prompt(record, tokenizer) -> str:
    problem = record.get("problem", "")
    if not problem:
        messages = record.get("messages") or []
        if messages:
            try:
                return tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True)
            except Exception:
                return "\n".join(
                    f"{m['role']}: {m['content']}" for m in messages) + "\nassistant: "
    return tokenizer.apply_chat_template(
        [{"role": "user", "content": problem}],
        tokenize=False, add_generation_prompt=True)


def get_reference(record) -> str:
    return record.get("canonical_answer", "") or ""


@torch.no_grad()
def generate(model, tokenizer, record, device):
    prompt = build_prompt(record, tokenizer)
    inputs = tokenizer(prompt, return_tensors="pt").to(device)
    input_len = inputs["input_ids"].shape[1]
    ref = get_reference(record)
    # Dynamic budget from P8 generation policy
    n_ref_tokens = len(tokenizer.encode(ref, add_special_tokens=False)) if ref else 0
    budget = min(4096, max(256, 128 + math.ceil(1.5 * n_ref_tokens)))
    t0 = time.perf_counter()
    gen = model.generate(
        **inputs, max_new_tokens=budget, do_sample=False,
        pad_token_id=tokenizer.pad_token_id, seed=SEED)
    latency = time.perf_counter() - t0
    new_tokens = gen[0][input_len:]
    text = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    stop_reason = "max_length" if new_tokens[-1].item() == tokenizer.eos_token_id else "eos"
    return text, int(new_tokens.numel()), latency, stop_reason


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


def metrics_for_response(score, response, stop_reason):
    correctness = float(score["correctness"])
    reasoning_quality = float(score["quality_continuous"])
    hallucination = 1.0 if score["correct"] is False and correctness < 0.4 else 0.0
    format_ok = 1.0 if score["method"] != "no_final_answer" else 0.0
    truncated = stop_reason == "max_length"
    return {
        "correctness": correctness,
        "reasoning_quality": reasoning_quality,
        "hallucination_rate": hallucination,
        "answer_format_consistency": format_ok,
        "truncated": truncated,
    }


def compute_stats(values):
    if not values:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "n": 0}
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / max(1, n - 1) if n > 1 else 0.0
    std = math.sqrt(variance)
    return {
        "mean": round(mean, 6),
        "std": round(std, 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        "n": n,
    }


def t_test_independent(baseline_vals, adapter_vals):
    """Welch's t-test for independent samples."""
    n1, n2 = len(baseline_vals), len(adapter_vals)
    if n1 < 2 or n2 < 2:
        return None, None
    m1, m2 = sum(baseline_vals) / n1, sum(adapter_vals) / n2
    v1 = sum((x - m1) ** 2 for x in baseline_vals) / (n1 - 1)
    v2 = sum((x - m2) ** 2 for x in adapter_vals) / (n2 - 1)
    se = math.sqrt(v1 / n1 + v2 / n2) if (v1 / n1 + v2 / n2) > 0 else 1e-10
    t_stat = (m2 - m1) / se
    # Welch-Satterthwaite df
    num = (v1 / n1 + v2 / n2) ** 2
    denom = (v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1)
    df = num / denom if denom > 0 else 1
    # Approximate p-value using regularized incomplete beta (two-tailed)
    p_value = _t_cdf_approx(abs(t_stat), df) * 2
    return round(t_stat, 4), round(p_value, 6)


def _t_cdf_approx(t, df):
    """Approximate two-tailed p from t-distribution using normal approx for large df."""
    if df >= 30:
        # Normal approximation for large df
        return _normal_cdf(-abs(t))
    # For small df, use a simple approximation
    x = df / (df + t * t)
    # Regularized incomplete beta approximation
    if x <= 0:
        return 1.0
    if x >= 1:
        return 0.0
    # Simple approximation: use the fact that for t-dist with df,
    # P(T > t) ≈ 0.5 * I_x(df/2, 0.5) where I is regularized beta
    # Use a basic numerical integration fallback
    n_steps = 1000
    step = 2.0 / n_steps
    total = 0.0
    for i in range(n_steps):
        ti = -t + i * step
        if ti < 0:
            continue
        val = (1 + ti * ti / df) ** (-(df + 1) / 2)
        total += val
    # Normalize (this is a rough approximation)
    approx_pdf_mean = total * step / n_steps
    # Convert to CDF using normal approx from tail
    z = t * (1 - 1 / (4 * df))  # Cornish-Fisher adjustment
    return _normal_cdf(-abs(z))


def _normal_cdf(x):
    """Standard normal CDF approximation (Abramowitz and Stegun)."""
    if x < -8:
        return 0.0
    if x > 8:
        return 1.0
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x) / math.sqrt(2)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
    return 0.5 * (1.0 + sign * y)


def effect_size(baseline_vals, adapter_vals):
    """Cohen's d for independent samples."""
    n1, n2 = len(baseline_vals), len(adapter_vals)
    if n1 < 2 or n2 < 2:
        return None
    m1, m2 = sum(baseline_vals) / n1, sum(adapter_vals) / n2
    v1 = sum((x - m1) ** 2 for x in baseline_vals) / (n1 - 1)
    v2 = sum((x - m2) ** 2 for x in adapter_vals) / (n2 - 1)
    pooled_std = math.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    if pooled_std < 1e-10:
        return 0.0
    return round((m2 - m1) / pooled_std, 4)


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
        "device": "cuda",
        "gpu_name": p.name,
        "vram_total_mib": round(p.total_memory / 1024 ** 2, 2),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
    }


def run_eval(records, model, tokenizer, device, label):
    results = []
    for rec in records:
        rid = rec.get("record_id")
        try:
            response, n_tokens, latency, stop_reason = generate(
                model, tokenizer, rec, device)
            score = score_qee_v2(rec.get("problem", ""), get_reference(rec), response)
            met = metrics_for_response(score, response, stop_reason)
            tps = n_tokens / latency if latency > 0 else 0.0
            results.append({
                "record_id": rid,
                "predicted_response": response,
                "reference_answer": get_reference(rec),
                "latency_s": round(latency, 4),
                "tokens_generated": n_tokens,
                "tokens_per_sec": round(tps, 2),
                "stop_reason": stop_reason,
                **met,
                "v2": dict(score),
                "run_label": label,
            })
            # Free memory after each record to prevent OOM on 12GB GPU
            if device == "cuda":
                torch.cuda.empty_cache()
                import gc; gc.collect()
        except Exception as e:
            results.append({
                "record_id": rid,
                "predicted_response": f"ERROR: {e}",
                "reference_answer": get_reference(rec),
                "latency_s": None,
                "tokens_generated": None,
                "tokens_per_sec": None,
                "stop_reason": "error",
                "correctness": None,
                "reasoning_quality": None,
                "hallucination_rate": None,
                "answer_format_consistency": None,
                "truncated": False,
                "v2": {},
                "run_label": label,
            })
    return results


def aggregate_results(results, label):
    valid = [r for r in results if r.get("correctness") is not None]
    n = len(valid) if valid else 1
    agg = {
        "label": label,
        "correctness": {
            **compute_stats([r["correctness"] for r in valid]),
            "mean": round(sum(r["correctness"] for r in valid) / n, 4),
        },
        "reasoning_quality": {
            **compute_stats([r["reasoning_quality"] for r in valid]),
            "mean": round(sum(r["reasoning_quality"] for r in valid) / n, 4),
        },
        "hallucination_rate": {
            **compute_stats([r["hallucination_rate"] for r in valid]),
            "mean": round(sum(r["hallucination_rate"] for r in valid) / n, 4),
        },
        "answer_format_consistency": {
            **compute_stats([r["answer_format_consistency"] for r in valid]),
            "mean": round(sum(r["answer_format_consistency"] for r in valid) / n, 4),
        },
        "evaluated_examples": len(valid),
        "total_examples": len(results),
        "truncated_count": sum(1 for r in results if r.get("truncated")),
        "truncation_rate": round(sum(1 for r in results if r.get("truncated")) / max(1, len(results)), 4),
        "stop_reason_counts": dict(Counter(r.get("stop_reason") for r in results)),
        "method_counts": dict(Counter(r.get("v2", {}).get("method", "unknown") for r in valid)),
    }
    return agg


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"=== Sprint 5B.3 Expanded Evaluation | device={device} ===")

    # Load Protocol v2 cert
    cert = json.loads((CERT_DIR / "protocol_certificate.json").read_text())
    print(f"Protocol v2 cert: readiness={cert['readiness_verdict']}")
    if cert["readiness_verdict"] != "READY":
        print("HOLD: Protocol v2 cert not READY")
        sys.exit(1)

    # Load eval set
    eval_file = EVAL_V2_DIR / "math_eval_v2.jsonl"
    records = load_jsonl(eval_file)
    manifest = json.loads((EVAL_V2_DIR / "math_eval_v2_manifest.json").read_text())
    print(f"Eval set: N={len(records)}, checksum matches manifest: "
          f"{manifest['checksum']['records'] == cert['eval_sets']['math']['checksum']}")

    # Load tokenizer and model
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
    )
    print(f"Loading base {BASE_MODEL} ...")
    hf_token = get_hf_token()
    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL, use_fast=True,
        token=hf_token)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, quantization_config=bnb_config, device_map="cpu",
        trust_remote_code=False,
        token=hf_token)
    model.eval()

    # --- Run 1: Baseline (no adapter) ---
    print("\n--- Run 1: Baseline (Qwen/Qwen2.5-7B-Instruct, no adapter) ---")
    if device == "cuda":
        model = model.to(device)
    baseline_results = run_eval(records, model, tokenizer, device, "baseline")
    baseline_agg = aggregate_results(baseline_results, "baseline")
    print(f"Baseline: correctness={baseline_agg['correctness']['mean']:.4f}, "
          f"N={baseline_agg['evaluated_examples']}")

    # Free memory before loading adapter
    if device == "cuda":
        del model
        torch.cuda.empty_cache()
        import gc; gc.collect()

    # --- Run 2: LoRA adapter ---
    print(f"\n--- Run 2: LoRA adapter (r=8, alpha=16) ---")
    adapter_config = json.loads((ADAPTER_DIR / "adapter_config.json").read_text())
    print(f"Loading LoRA adapter (r={adapter_config.get('r')}, alpha {adapter_config.get('lora_alpha')}) ...")
    model = PeftModel.from_pretrained(model, ADAPTER_DIR)
    model.eval()
    trainable, total = model.get_nb_trainable_parameters()
    print(f"Trainable params on eval: {trainable}, Total params: {total}")

    adapter_results = run_eval(records, model, tokenizer, device, "adapter")
    adapter_agg = aggregate_results(adapter_results, "adapter")
    print(f"Adapter: correctness={adapter_agg['correctness']['mean']:.4f}, "
          f"N={adapter_agg['evaluated_examples']}")

    # --- Compute deltas and statistics ---
    baseline_by_id = {r["record_id"]: r for r in baseline_results}
    adapter_by_id = {r["record_id"]: r for r in adapter_results}

    deltas = []
    per_example = []
    for rec in records:
        rid = rec.get("record_id")
        br = baseline_by_id.get(rid, {})
        ar = adapter_by_id.get(rid, {})
        bc = br.get("correctness")
        ac = ar.get("correctness")
        if bc is None or ac is None:
            continue
        delta = ac - bc
        deltas.append(delta)
        improved = "improved" if delta > 0 else ("regressed" if delta < 0 else "unchanged")
        per_example.append({
            "record_id": rid,
            "difficulty": rec.get("difficulty"),
            "subdomain": rec.get("subdomains", ["?"])[0] if rec.get("subdomains") else "?",
            "baseline_correctness": round(bc, 4),
            "adapter_correctness": round(ac, 4),
            "delta": round(delta, 4),
            "baseline_reasoning_quality": round(br.get("reasoning_quality", 0), 4),
            "adapter_reasoning_quality": round(ar.get("reasoning_quality", 0), 4),
            "baseline_hallucination_rate": round(br.get("hallucination_rate", 0), 4),
            "adapter_hallucination_rate": round(ar.get("hallucination_rate", 0), 4),
            "baseline_format_consistency": round(br.get("answer_format_consistency", 0), 4),
            "adapter_format_consistency": round(ar.get("answer_format_consistency", 0), 4),
            "status": improved,
            "baseline_method": br.get("v2", {}).get("method", "?"),
            "adapter_method": ar.get("v2", {}).get("method", "?"),
        })

    improved_count = sum(1 for d in deltas if d > 0)
    regressed_count = sum(1 for d in deltas if d < 0)
    unchanged_count = sum(1 for d in deltas if d == 0)

    # Statistical tests
    baseline_correctness_vals = [r["correctness"] for r in baseline_results if r.get("correctness") is not None]
    adapter_correctness_vals = [r["correctness"] for r in adapter_results if r.get("correctness") is not None]

    t_stat, p_value = t_test_independent(baseline_correctness_vals, adapter_correctness_vals)
    cohens_d = effect_size(baseline_correctness_vals, adapter_correctness_vals)

    # Per-difficulty breakdown
    by_difficulty = {}
    for pe in per_example:
        d = str(pe["difficulty"])
        by_difficulty.setdefault(d, {"baseline": [], "adapter": [], "deltas": []})
        by_difficulty[d]["baseline"].append(pe["baseline_correctness"])
        by_difficulty[d]["adapter"].append(pe["adapter_correctness"])
        by_difficulty[d]["deltas"].append(pe["delta"])
    difficulty_summary = {}
    for d, data in by_difficulty.items():
        n = len(data["baseline"])
        difficulty_summary[d] = {
            "n": n,
            "baseline_mean": round(sum(data["baseline"]) / n, 4),
            "adapter_mean": round(sum(data["adapter"]) / n, 4),
            "mean_delta": round(sum(data["deltas"]) / n, 4),
        }

    # Per-subdomain breakdown
    by_subdomain = {}
    for pe in per_example:
        sd = pe["subdomain"]
        by_subdomain.setdefault(sd, {"baseline": [], "adapter": [], "deltas": []})
        by_subdomain[sd]["baseline"].append(pe["baseline_correctness"])
        by_subdomain[sd]["adapter"].append(pe["adapter_correctness"])
        by_subdomain[sd]["deltas"].append(pe["delta"])
    subdomain_summary = {}
    for sd, data in by_subdomain.items():
        n = len(data["baseline"])
        subdomain_summary[sd] = {
            "n": n,
            "baseline_mean": round(sum(data["baseline"]) / n, 4),
            "adapter_mean": round(sum(data["adapter"]) / n, 4),
            "mean_delta": round(sum(data["deltas"]) / n, 4),
        }

    # Failure analysis
    failure_records = [pe for pe in per_example if pe["adapter_correctness"] < 0.4 and pe["delta"] < 0]
    largest_regressions = sorted(
        [pe for pe in per_example if pe["delta"] < 0],
        key=lambda x: x["delta"]
    )[:5]
    biggest_gains = sorted(
        [pe for pe in per_example if pe["delta"] > 0],
        key=lambda x: -x["delta"]
    )[:5]

    # --- Build report ---
    report = {
        "experiment_id": "lora_pilot_math_v0.1",
        "sprint": "5B.3",
        "evaluation_id": "expanded_math_eval_v2",
        "status": "COMPLETE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hardware": gpu_info_fn(),
        "protocol_v2": {
            "readiness_verdict": cert["readiness_verdict"],
            "eval_set": "math_eval_v2",
            "n_records": len(records),
            "checksum": manifest["checksum"]["records"],
            "certificate_sha256": cert.get("certificate_sha256", "")[:16],
        },
        "adapter": {
            "path": str(ADAPTER_DIR),
            "base_model": BASE_MODEL,
            "model_revision": MODEL_REVISION,
            "lora_config": json_safe({
                "r": adapter_config.get("r"),
                "lora_alpha": adapter_config.get("lora_alpha"),
                "lora_dropout": adapter_config.get("lora_dropout"),
                "target_modules": adapter_config.get("target_modules"),
            }),
            "trainable_params": int(trainable),
            "total_params": int(total),
        },
        "baseline": baseline_agg,
        "adapter": adapter_agg,
        "delta": {
            "correctness": round(adapter_agg["correctness"]["mean"] - baseline_agg["correctness"]["mean"], 4),
            "reasoning_quality": round(adapter_agg["reasoning_quality"]["mean"] - baseline_agg["reasoning_quality"]["mean"], 4),
            "hallucination_rate": round(adapter_agg["hallucination_rate"]["mean"] - baseline_agg["hallucination_rate"]["mean"], 4),
            "format_consistency": round(adapter_agg["answer_format_consistency"]["mean"] - baseline_agg["answer_format_consistency"]["mean"], 4),
        },
        "statistical_comparison": {
            "n_baseline": len(baseline_correctness_vals),
            "n_adapter": len(adapter_correctness_vals),
            "t_test_statistic": t_stat,
            "t_test_p_value_two_tailed": p_value,
            "cohens_d": cohens_d,
            "interpretation": (
                "statistically significant (p < 0.05)"
                if p_value is not None and p_value < 0.05
                else "not statistically significant (p >= 0.05)"
                if p_value is not None
                else "insufficient samples for t-test"
            ),
            "effect_size_interpretation": (
                "small" if abs(cohens_d) is not None and abs(cohens_d) < 0.2 else
                "medium" if abs(cohens_d) is not None and abs(cohens_d) < 0.5 else
                "large" if abs(cohens_d) is not None else None,
            ) if cohens_d is not None else None,
        },
        "per_example_counts": {
            "improved": improved_count,
            "regressed": regressed_count,
            "unchanged": unchanged_count,
            "total": len(deltas),
        },
        "by_difficulty": difficulty_summary,
        "by_subdomain": subdomain_summary,
        "failure_analysis": {
            "records_below_0.4_correctness": len(failure_records),
            "largest_regressions": [
                {"record_id": pe["record_id"], "delta": pe["delta"],
                 "baseline": pe["baseline_correctness"], "adapter": pe["adapter_correctness"]}
                for pe in largest_regressions
            ],
            "biggest_gains": [
                {"record_id": pe["record_id"], "delta": pe["delta"],
                 "baseline": pe["baseline_correctness"], "adapter": pe["adapter_correctness"]}
                for pe in biggest_gains
            ],
        },
        "truncation_rate": adapter_agg["truncation_rate"],
        "stop_reason_counts": adapter_agg["stop_reason_counts"],
        "method_counts": adapter_agg["method_counts"],
    }

    # Write artifacts
    (OUT_DIR / "expanded_evaluation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (OUT_DIR / "expanded_per_example.jsonl").open("w", encoding="utf-8") as f:
        for pe in per_example:
            f.write(json.dumps(pe, ensure_ascii=False) + "\n")
    with (OUT_DIR / "expanded_baseline_results.jsonl").open("w", encoding="utf-8") as f:
        for r in baseline_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (OUT_DIR / "expanded_adapter_results.jsonl").open("w", encoding="utf-8") as f:
        for r in adapter_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n=== Results ===")
    print(f"Baseline correctness: {baseline_agg['correctness']['mean']:.4f} ± {baseline_agg['correctness']['std']:.4f} (N={baseline_agg['evaluated_examples']})")
    print(f"Adapter correctness:  {adapter_agg['correctness']['mean']:.4f} ± {adapter_agg['correctness']['std']:.4f} (N={adapter_agg['evaluated_examples']})")
    print(f"Delta correctness:    {report['delta']['correctness']:.4f}")
    print(f"Delta reasoning:      {report['delta']['reasoning_quality']:.4f}")
    print(f"Delta hallucination:  {report['delta']['hallucination_rate']:.4f}")
    print(f"t-stat: {t_stat}, p-value: {p_value}, Cohen's d: {cohens_d}")
    print(f"Improved: {improved_count}, Regressed: {regressed_count}, Unchanged: {unchanged_count}")
    print(f"Truncation rate: {adapter_agg['truncation_rate']:.4f}")
    print(f"\nWrote to {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
