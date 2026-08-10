#!/usr/bin/env python3
"""
run_m2_evaluation.py — Sprint 5B.4 M2 Expanded Evaluation

Evaluates the M2 LoRA adapter (lora_pilot_math_m2_v0.1) on the
Protocol v2 math eval set (N=100) using QEE v2. Produces:

  * Baseline run on math_eval_v2 (same base model, no adapter)
  * M1 adapter run on same split (for direct comparison)
  * M2 adapter run on same split
  * Per-example deltas, statistical comparison, and M1 vs M2 analysis

Does NOT retrain. Does NOT modify frozen assets.
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

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from credential_helper import get_hf_token
sys.path.insert(0, str(REPO / "scripts"))

# Directories
M1_EXP = REPO / "experiments" / "lora_pilot_math_v0.1"
M2_EXP = REPO / "experiments" / "lora_pilot_math_m2_v0.1"
EVAL_V2_DIR = REPO / "evaluation" / "eval_sets" / "protocol_v2"
CERT_DIR = REPO / "metadata" / "evaluation" / "protocol_v2_baseline"
OUT_DIR = M2_EXP / "evaluation" / "expanded_5b4"

BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
MODEL_REVISION = "a09a35458c702b33eeacc393d103063234e8bc28"
SEED = 42

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
    n_ref_tokens = len(tokenizer.encode(ref, add_special_tokens=False)) if ref else 0
    budget = min(4096, max(256, 128 + math.ceil(1.5 * n_ref_tokens)))
    t0 = time.perf_counter()
    gen = model.generate(
        **inputs, max_new_tokens=budget, do_sample=False,
        pad_token_id=tokenizer.pad_token_id)
    latency = time.perf_counter() - t0
    new_tokens = gen[0][input_len:]
    text = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    stop_reason = "max_length" if len(new_tokens) > 0 and new_tokens[-1].item() == tokenizer.eos_token_id else ("eos" if len(new_tokens) > 0 else "empty")
    return text, int(new_tokens.numel()), latency, stop_reason


def score_qee_v2(question, reference, response):
    from evaluation_engine.v2.engine import QeeV2Engine as _QEE
    engine = _QEE()
    _, result = engine._type_result("math", question, reference, response)
    breakdown = engine._dimensions("math", result, question, reference, response)
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
        "answer_type": "math",
        "correctness": round(float(result.score), 4),
        "correct": result.correct,
        "quality_score": score,
        "quality_continuous": round(float(continuous), 4),
        "method": getattr(result, "method", "rubric"),
        "flags": flags,
        "dimensions": {k: round(v, 3) for k, v in dims.items()},
    }


def metrics_for_response(score, stop_reason):
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
    return {"device": "cuda", "gpu_name": p.name,
            "vram_total_mib": round(p.total_memory / 1024 ** 2, 2),
            "torch_version": torch.__version__, "cuda_version": torch.version.cuda}


def run_eval(records, model, tokenizer, device, label):
    results = []
    for rec in records:
        rid = rec.get("record_id")
        try:
            response, n_tokens, latency, stop_reason = generate(model, tokenizer, rec, device)
            score = score_qee_v2(rec.get("problem", ""), get_reference(rec), response)
            met = metrics_for_response(score, stop_reason)
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
            if device == "cuda":
                torch.cuda.empty_cache()
                import gc; gc.collect()
        except Exception as e:
            results.append({
                "record_id": rid,
                "predicted_response": f"ERROR: {e}",
                "reference_answer": get_reference(rec),
                "latency_s": None, "tokens_generated": None, "tokens_per_sec": None,
                "stop_reason": "error",
                "correctness": None, "reasoning_quality": None,
                "hallucination_rate": None, "answer_format_consistency": None,
                "truncated": False, "v2": {}, "run_label": label,
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
        "truncation_rate": round(sum(1 for r in results if r.get("truncated")) / max(1, len(results)), 4),
        "stop_reason_counts": dict(Counter(r.get("stop_reason") for r in results)),
        "method_counts": dict(Counter(r.get("v2", {}).get("method", "unknown") for r in valid)),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"=== Sprint 5B.4 M2 Evaluation | device={device} ===")

    # Load Protocol v2 cert
    cert = json.loads((CERT_DIR / "protocol_certificate.json").read_text())
    print(f"Protocol v2 cert: readiness={cert['readiness_verdict']}")

    # Load eval set
    eval_file = EVAL_V2_DIR / "math_eval_v2.jsonl"
    records = load_jsonl(eval_file)
    manifest = json.loads((EVAL_V2_DIR / "math_eval_v2_manifest.json").read_text())
    print(f"Eval set: N={len(records)}, checksum valid: {manifest['checksum']['records'] == cert['eval_sets']['math']['checksum']}")

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
        BASE_MODEL, quantization_config=bnb_config, device_map="auto",
        trust_remote_code=False,
        token=hf_token)
    model.eval()

    # --- Run 1: Baseline (no adapter) ---
    print("\n--- Run 1: Baseline ---")
    baseline_results = run_eval(records, model, tokenizer, device, "baseline")
    baseline_agg = aggregate_results(baseline_results, "baseline")
    print(f"Baseline: correctness={baseline_agg['correctness']['mean']:.4f}, N={baseline_agg['evaluated_examples']}")

    # Free memory
    del model
    torch.cuda.empty_cache()
    import gc; gc.collect()

    # --- Run 2: M1 Adapter ---
    print("\n--- Run 2: M1 Adapter (r=8, alpha=16, 117 train records) ---")
    m1_adapter = PeftModel.from_pretrained(
        AutoModelForCausalLM.from_pretrained(
            BASE_MODEL, quantization_config=bnb_config, device_map="auto",
            trust_remote_code=False,
            token=hf_token),
        M1_EXP / "checkpoints")
    m1_adapter.eval()
    m1_results = run_eval(records, m1_adapter, tokenizer, device, "m1")
    m1_agg = aggregate_results(m1_results, "m1")
    print(f"M1: correctness={m1_agg['correctness']['mean']:.4f}, N={m1_agg['evaluated_examples']}")

    del m1_adapter
    torch.cuda.empty_cache()
    gc.collect()

    # --- Run 3: M2 Adapter ---
    print("\n--- Run 3: M2 Adapter (r=8, alpha=16, 131 train records) ---")
    m2_adapter = PeftModel.from_pretrained(
        AutoModelForCausalLM.from_pretrained(
            BASE_MODEL, quantization_config=bnb_config, device_map="auto",
            trust_remote_code=False,
            token=hf_token),
        M2_EXP / "checkpoints")
    m2_adapter.eval()
    m2_results = run_eval(records, m2_adapter, tokenizer, device, "m2")
    m2_agg = aggregate_results(m2_results, "m2")
    print(f"M2: correctness={m2_agg['correctness']['mean']:.4f}, N={m2_agg['evaluated_examples']}")

    del m2_adapter
    torch.cuda.empty_cache()
    gc.collect()

    # --- Compute comparisons ---
    baseline_by_id = {r["record_id"]: r for r in baseline_results}
    m1_by_id = {r["record_id"]: r for r in m1_results}
    m2_by_id = {r["record_id"]: r for r in m2_results}

    # M1 vs M2 per-example
    m1_m2_comparison = []
    for rec in records:
        rid = rec.get("record_id")
        br = baseline_by_id.get(rid, {})
        m1r = m1_by_id.get(rid, {})
        m2r = m2_by_id.get(rid, {})
        bc = br.get("correctness")
        m1c = m1r.get("correctness")
        m2c = m2r.get("correctness")
        if bc is None or m1c is None or m2c is None:
            continue
        m1_m2_comparison.append({
            "record_id": rid,
            "difficulty": rec.get("difficulty"),
            "baseline": round(bc, 4),
            "m1": round(m1c, 4),
            "m2": round(m2c, 4),
            "m1_delta": round(m1c - bc, 4),
            "m2_delta": round(m2c - bc, 4),
            "m2_vs_m1": round(m2c - m1c, 4),
            "m1_status": "improved" if m1c > bc else ("regressed" if m1c < bc else "unchanged"),
            "m2_status": "improved" if m2c > bc else ("regressed" if m2c < bc else "unchanged"),
            "m1_better": m1c > m2c,
            "m2_better": m2c > m1c,
        })

    # Aggregate stats
    m1_correctness = [r["correctness"] for r in m1_results if r.get("correctness") is not None]
    m2_correctness = [r["correctness"] for r in m2_results if r.get("correctness") is not None]
    baseline_correctness = [r["correctness"] for r in baseline_results if r.get("correctness") is not None]

    # M1 vs M2 delta stats
    m1_deltas = [c - b for b, c in zip(baseline_correctness, m1_correctness)]
    m2_deltas = [c - b for b, c in zip(baseline_correctness, m2_correctness)]
    m1_m2_deltas = [m2 - m1 for m1, m2 in zip(m1_correctness, m2_correctness)]

    def paired_ttest(a, b):
        if len(a) < 2:
            return None, None
        diffs = [ai - bi for ai, bi in zip(a, b)]
        n = len(diffs)
        mean = sum(diffs) / n
        var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
        se = math.sqrt(var / n) if var > 0 else 1e-10
        t = mean / se
        # Approximate p-value
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

    m1_vs_base_t, m1_vs_base_p = paired_ttest(baseline_correctness, m1_correctness)
    m2_vs_base_t, m2_vs_base_p = paired_ttest(baseline_correctness, m2_correctness)
    m2_vs_m1_t, m2_vs_m1_p = paired_ttest(m1_correctness, m2_correctness)

    # M2 vs M1 improvement counts
    m2_improved_over_m1 = sum(1 for r in m1_m2_comparison if r["m2_better"])
    m1_improved_over_m2 = sum(1 for r in m1_m2_comparison if r["m1_better"])
    unchanged = sum(1 for r in m1_m2_comparison if not r["m2_better"] and not r["m1_better"])

    # Failure analysis
    m2_failures = [r for r in m1_m2_comparison if r["m2"] < 0.4]
    m2_regressions = [r for r in m1_m2_comparison if r["m2_status"] == "regressed"]
    m2_gains = sorted([r for r in m1_m2_comparison if r["m2_delta"] > 0], key=lambda x: -x["m2_delta"])[:5]
    m2_losses = sorted([r for r in m1_m2_comparison if r["m2_delta"] < 0], key=lambda x: x["m2_delta"])[:5]

    # Scaling analysis
    scaling = {
        "m1_training_records": 117,
        "m2_training_records": 131,
        "record_increase": 131 - 117,
        "increase_pct": round(100 * (131 - 117) / 117, 1),
        "m1_correctness_delta": round(baseline_agg["correctness"]["mean"] - baseline_agg["correctness"]["mean"] + (m1_agg["correctness"]["mean"] - baseline_agg["correctness"]["mean"]), 4),
        "m2_correctness_delta": round(m2_agg["correctness"]["mean"] - baseline_agg["correctness"]["mean"], 4),
        "scaling_delta": round(m2_agg["correctness"]["mean"] - m1_agg["correctness"]["mean"], 4),
    }

    # Build report
    report = {
        "experiment_id": "lora_pilot_math_m2_v0.1",
        "sprint": "5B.4",
        "evaluation_id": "m2_expanded_eval_v2",
        "status": "COMPLETE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hardware": gpu_info_fn(),
        "protocol_v2": {
            "readiness_verdict": cert["readiness_verdict"],
            "eval_set": "math_eval_v2",
            "n_records": len(records),
            "checksum": manifest["checksum"]["records"],
        },
        "training_comparison": {
            "m1": {"training_records": 117, "steps": 60, "final_loss": 0.25298, "view_id": "math_300m_v0.1"},
            "m2": {"training_records": 131, "steps": 60, "final_loss": float(m2_agg.get("_final_loss", 0.2296)), "view_id": "math_m2_v0.1"},
            "hyperparameters_identical": True,
        },
        "baseline": baseline_agg,
        "m1": m1_agg,
        "m2": m2_agg,
        "deltas": {
            "m1_vs_baseline": {
                "correctness": round(m1_agg["correctness"]["mean"] - baseline_agg["correctness"]["mean"], 4),
                "reasoning_quality": round(m1_agg["reasoning_quality"]["mean"] - baseline_agg["reasoning_quality"]["mean"], 4),
                "hallucination_rate": round(m1_agg["hallucination_rate"]["mean"] - baseline_agg["hallucination_rate"]["mean"], 4),
            },
            "m2_vs_baseline": {
                "correctness": round(m2_agg["correctness"]["mean"] - baseline_agg["correctness"]["mean"], 4),
                "reasoning_quality": round(m2_agg["reasoning_quality"]["mean"] - baseline_agg["reasoning_quality"]["mean"], 4),
                "hallucination_rate": round(m2_agg["hallucination_rate"]["mean"] - baseline_agg["hallucination_rate"]["mean"], 4),
            },
            "m2_vs_m1": {
                "correctness": round(m2_agg["correctness"]["mean"] - m1_agg["correctness"]["mean"], 4),
                "reasoning_quality": round(m2_agg["reasoning_quality"]["mean"] - m1_agg["reasoning_quality"]["mean"], 4),
                "hallucination_rate": round(m2_agg["hallucination_rate"]["mean"] - m1_agg["hallucination_rate"]["mean"], 4),
            },
        },
        "statistical_comparison": {
            "m1_vs_baseline": {"t_stat": m1_vs_base_t, "p_value": m1_vs_base_p,
                               "interpretation": "significant" if m1_vs_base_p and m1_vs_base_p < 0.05 else "not significant"},
            "m2_vs_baseline": {"t_stat": m2_vs_base_t, "p_value": m2_vs_base_p,
                               "interpretation": "significant" if m2_vs_base_p and m2_vs_base_p < 0.05 else "not significant"},
            "m2_vs_m1": {"t_stat": m2_vs_m1_t, "p_value": m2_vs_m1_p,
                         "interpretation": "significant" if m2_vs_m1_p and m2_vs_m1_p < 0.05 else "not significant"},
        },
        "scaling_analysis": {
            "training_records_m1": 117,
            "training_records_m2": 131,
            "record_increase": 14,
            "increase_pct": "12.0%",
            "m1_correctness": round(m1_agg["correctness"]["mean"], 4),
            "m2_correctness": round(m2_agg["correctness"]["mean"], 4),
            "correctness_delta_m2_vs_m1": round(m2_agg["correctness"]["mean"] - m1_agg["correctness"]["mean"], 4),
        },
        "per_example_comparison": m1_m2_comparison,
        "m2_vs_m1_counts": {
            "m2_better": m2_improved_over_m1,
            "m1_better": m1_improved_over_m2,
            "unchanged": unchanged,
            "total": len(m1_m2_comparison),
        },
        "failure_analysis": {
            "m2_records_below_0.4": len(m2_failures),
            "m2_regressions_from_baseline": len(m2_regressions),
            "biggest_m2_gains": [{"record_id": r["record_id"], "baseline": r["baseline"], "m2": r["m2"], "delta": r["m2_delta"]} for r in m2_gains],
            "biggest_m2_losses": [{"record_id": r["record_id"], "baseline": r["baseline"], "m2": r["m2"], "delta": r["m2_delta"]} for r in m2_losses],
        },
    }

    # Write artifacts
    (OUT_DIR / "m2_evaluation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (OUT_DIR / "m2_per_example.jsonl").open("w", encoding="utf-8") as f:
        for r in m1_m2_comparison:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (OUT_DIR / "m2_baseline_results.jsonl").open("w", encoding="utf-8") as f:
        for r in baseline_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (OUT_DIR / "m2_m1_results.jsonl").open("w", encoding="utf-8") as f:
        for r in m1_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (OUT_DIR / "m2_m2_results.jsonl").open("w", encoding="utf-8") as f:
        for r in m2_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n=== Results ===")
    print(f"Baseline correctness: {baseline_agg['correctness']['mean']:.4f} (N={baseline_agg['evaluated_examples']})")
    print(f"M1 correctness:       {m1_agg['correctness']['mean']:.4f} (N={m1_agg['evaluated_examples']})")
    print(f"M2 correctness:       {m2_agg['correctness']['mean']:.4f} (N={m2_agg['evaluated_examples']})")
    print(f"M1 vs Baseline delta: {m1_agg['correctness']['mean'] - baseline_agg['correctness']['mean']:+.4f}")
    print(f"M2 vs Baseline delta: {m2_agg['correctness']['mean'] - baseline_agg['correctness']['mean']:+.4f}")
    print(f"M2 vs M1 delta:       {m2_agg['correctness']['mean'] - m1_agg['correctness']['mean']:+.4f}")
    print(f"M2 better than M1: {m2_improved_over_m1}, M1 better than M2: {m1_improved_over_m2}, Unchanged: {unchanged}")
    print(f"\nWrote to {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
