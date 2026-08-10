#!/usr/bin/env python3
"""
run_m2prime_evaluation.py — Sprint 5B.7 M2' Evaluation (simplified)

Evaluates M2' on math_eval_v2 (N=100) using same approach as M2 evaluation.
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

M1_EXP = REPO / "experiments" / "lora_pilot_math_v0.1"
M2PRIME_EXP = REPO / "experiments" / "lora_pilot_math_m2prime_v0.1"
EVAL_V2_DIR = REPO / "evaluation" / "eval_sets" / "protocol_v2"
CERT_DIR = REPO / "metadata" / "evaluation" / "protocol_v2_baseline"
OUT_DIR = M2PRIME_EXP / "evaluation"

BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"

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
    return f"user: {record.get('problem', '')}\nassistant: "


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
        pad_token_id=tokenizer.pad_token_id)
    latency = time.perf_counter() - t0
    new_tokens = gen[0][input_len:]
    text = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    stop_reason = "max_length" if len(new_tokens) > 0 and new_tokens[-1].item() == tokenizer.eos_token_id else ("eos" if len(new_tokens) > 0 else "empty")
    return text, int(new_tokens.numel()), latency, stop_reason, budget, n_ref_tokens


def score_qee_v2(question, reference, response):
    engine = QeeV2Engine()
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
        question = ""
        for m in rec.get("messages") or []:
            if m.get("role") == "user":
                question = m.get("content", "")
                break
        try:
            response, n_tokens, latency, stop_reason, budget, n_ref_tokens = generate(model, tokenizer, rec, device)
            score = score_qee_v2(question, get_reference(rec), response)
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
                "reference_tokens": n_ref_tokens,
                "budget": budget,
                **met,
                "v2": dict(score),
                "run_label": label,
            })
            if device == "cuda":
                torch.cuda.empty_cache()
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
    print(f"=== Sprint 5B.7 M2' Evaluation | device={device} ===")

    m2prime_adapter = M2PRIME_EXP / "checkpoints"
    if not (m2prime_adapter / "adapter_config.json").exists():
        raise SystemExit(f"M2' adapter not found at {m2prime_adapter}. Run training first.")

    m1_adapter = M1_EXP / "checkpoints"
    if not (m1_adapter / "adapter_config.json").exists():
        raise SystemExit(f"M1 adapter not found at {m1_adapter}. Run M1 training first.")

    cert = json.loads((CERT_DIR / "protocol_certificate.json").read_text())
    print(f"Protocol v2 cert: readiness={cert['readiness_verdict']}")

    eval_file = EVAL_V2_DIR / "math_eval_v2.jsonl"
    records = load_jsonl(eval_file)
    manifest = json.loads((EVAL_V2_DIR / "math_eval_v2_manifest.json").read_text())
    print(f"Eval set: N={len(records)}, checksum valid: {manifest['checksum']['records'] == cert['eval_sets']['math']['checksum']}")

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
    if device == "cuda":
        model = model.to("cuda")
    model.eval()

    # --- Run 1: Baseline ---
    print("\n--- Run 1: Baseline ---")
    baseline_results = run_eval(records, model, tokenizer, device, "baseline")
    baseline_agg = aggregate_results(baseline_results, "baseline")
    print(f"Baseline: correctness={baseline_agg['correctness']['mean']:.4f}, N={baseline_agg['evaluated_examples']}")

    del model
    torch.cuda.empty_cache()
    import gc; gc.collect()

    # --- Run 2: M1 Adapter ---
    print("\n--- Run 2: M1 Adapter (r=8, alpha=16, 117 train records) ---")
    m1_model = PeftModel.from_pretrained(
        AutoModelForCausalLM.from_pretrained(
            BASE_MODEL, quantization_config=bnb_config, device_map="cpu",
            trust_remote_code=False,
            token=hf_token),
        m1_adapter)
    if device == "cuda":
        m1_model = m1_model.to("cuda")
    m1_model.eval()
    m1_results = run_eval(records, m1_model, tokenizer, device, "m1")
    m1_agg = aggregate_results(m1_results, "m1")
    print(f"M1: correctness={m1_agg['correctness']['mean']:.4f}, N={m1_agg['evaluated_examples']}")

    del m1_model
    torch.cuda.empty_cache()
    gc.collect()

    # --- Run 3: M2' Adapter ---
    print("\n--- Run 3: M2' Adapter (r=8, alpha=16, 118 train records) ---")
    m2prime_model = PeftModel.from_pretrained(
        AutoModelForCausalLM.from_pretrained(
            BASE_MODEL, quantization_config=bnb_config, device_map="cpu",
            trust_remote_code=False,
            token=hf_token),
        m2prime_adapter)
    if device == "cuda":
        m2prime_model = m2prime_model.to("cuda")
    m2prime_model.eval()
    m2prime_results = run_eval(records, m2prime_model, tokenizer, device, "m2prime")
    m2prime_agg = aggregate_results(m2prime_results, "m2prime")
    print(f"M2': correctness={m2prime_agg['correctness']['mean']:.4f}, N={m2prime_agg['evaluated_examples']}")

    del m2prime_model
    torch.cuda.empty_cache()
    gc.collect()

    # --- Compute comparisons ---
    baseline_by_id = {r["record_id"]: r for r in baseline_results}
    m1_by_id = {r["record_id"]: r for r in m1_results}
    m2prime_by_id = {r["record_id"]: r for r in m2prime_results}

    m1_m2prime_comparison = []
    for rec in records:
        rid = rec.get("record_id")
        br = baseline_by_id.get(rid, {})
        m1r = m1_by_id.get(rid, {})
        m2pr = m2prime_by_id.get(rid, {})
        bc = br.get("correctness")
        m1c = m1r.get("correctness")
        m2pc = m2pr.get("correctness")
        if bc is None or m1c is None or m2pc is None:
            continue
        m1_m2prime_comparison.append({
            "record_id": rid,
            "difficulty": rec.get("difficulty"),
            "baseline": round(bc, 4),
            "m1": round(m1c, 4),
            "m2prime": round(m2pc, 4),
            "m1_delta": round(m1c - bc, 4),
            "m2prime_delta": round(m2pc - bc, 4),
            "m2prime_vs_m1": round(m2pc - m1c, 4),
            "m1_status": "improved" if m1c > bc else ("regressed" if m1c < bc else "unchanged"),
            "m2prime_status": "improved" if m2pc > bc else ("regressed" if m2pc < bc else "unchanged"),
            "m1_better": m1c > m2pc,
            "m2prime_better": m2pc > m1c,
        })

    m1_correctness = [r["correctness"] for r in m1_results if r.get("correctness") is not None]
    m2prime_correctness = [r["correctness"] for r in m2prime_results if r.get("correctness") is not None]
    baseline_correctness = [r["correctness"] for r in baseline_results if r.get("correctness") is not None]

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

    m1_vs_base_t, m1_vs_base_p = paired_ttest(baseline_correctness, m1_correctness)
    m2prime_vs_base_t, m2prime_vs_base_p = paired_ttest(baseline_correctness, m2prime_correctness)
    m2prime_vs_m1_t, m2prime_vs_m1_p = paired_ttest(m1_correctness, m2prime_correctness)

    m2prime_improved_over_m1 = sum(1 for r in m1_m2prime_comparison if r["m2prime_better"])
    m1_improved_over_m2prime = sum(1 for r in m1_m2prime_comparison if r["m1_better"])
    unchanged = sum(1 for r in m1_m2prime_comparison if not r["m2prime_better"] and not r["m1_better"])

    m2prime_failures = [r for r in m1_m2prime_comparison if r["m2prime"] < 0.4]
    m2prime_regressions = [r for r in m1_m2prime_comparison if r["m2prime_status"] == "regressed"]
    m2prime_gains = sorted([r for r in m1_m2prime_comparison if r["m2prime_delta"] > 0], key=lambda x: -x["m2prime_delta"])[:5]
    m2prime_losses = sorted([r for r in m1_m2prime_comparison if r["m2prime_delta"] < 0], key=lambda x: x["m2prime_delta"])[:5]

    m1_training_log = {}
    m1_log_path = M1_EXP / "training_log.json"
    if m1_log_path.exists():
        with m1_log_path.open(encoding="utf-8") as f:
            m1_training_log = json.load(f)

    report = {
        "experiment_id": "lora_pilot_math_m2prime_v0.1",
        "sprint": "5B.7",
        "evaluation_id": "m2prime_evaluation",
        "status": "COMPLETE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hardware": gpu_info_fn(),
        "training_comparison": {
            "m1": {
                "training_records": 117,
                "steps": 60,
                "final_loss": m1_training_log.get("training_metrics", {}).get("final_loss"),
                "min_loss": m1_training_log.get("training_metrics", {}).get("min_loss"),
                "view_id": "math_300m_v0.1",
            },
            "m2prime": {
                "training_records": 118,
                "steps": 60,
                "final_loss": 0.17043,
                "min_loss": 0.15857,
                "m2prime_only_record": "expert_math_000761",
                "view_id": "math_m2prime_v0.1",
            },
            "hyperparameters_identical": True,
            "eval_overlap_m1": 0,
            "eval_overlap_m2prime": 0,
        },
        "baseline": baseline_agg,
        "m1": m1_agg,
        "m2prime": m2prime_agg,
        "deltas": {
            "m1_vs_baseline": {
                "correctness": round(m1_agg["correctness"]["mean"] - baseline_agg["correctness"]["mean"], 4),
                "reasoning_quality": round(m1_agg["reasoning_quality"]["mean"] - baseline_agg["reasoning_quality"]["mean"], 4),
                "hallucination_rate": round(m1_agg["hallucination_rate"]["mean"] - baseline_agg["hallucination_rate"]["mean"], 4),
            },
            "m2prime_vs_baseline": {
                "correctness": round(m2prime_agg["correctness"]["mean"] - baseline_agg["correctness"]["mean"], 4),
                "reasoning_quality": round(m2prime_agg["reasoning_quality"]["mean"] - baseline_agg["reasoning_quality"]["mean"], 4),
                "hallucination_rate": round(m2prime_agg["hallucination_rate"]["mean"] - baseline_agg["hallucination_rate"]["mean"], 4),
            },
            "m2prime_vs_m1": {
                "correctness": round(m2prime_agg["correctness"]["mean"] - m1_agg["correctness"]["mean"], 4),
                "reasoning_quality": round(m2prime_agg["reasoning_quality"]["mean"] - m1_agg["reasoning_quality"]["mean"], 4),
                "hallucination_rate": round(m2prime_agg["hallucination_rate"]["mean"] - m1_agg["hallucination_rate"]["mean"], 4),
            },
        },
        "statistical_comparison": {
            "m1_vs_baseline": {"t_stat": m1_vs_base_t, "p_value": m1_vs_base_p,
                               "interpretation": "significant" if m1_vs_base_p and m1_vs_base_p < 0.05 else "not significant"},
            "m2prime_vs_baseline": {"t_stat": m2prime_vs_base_t, "p_value": m2prime_vs_base_p,
                                     "interpretation": "significant" if m2prime_vs_base_p and m2prime_vs_base_p < 0.05 else "not significant"},
            "m2prime_vs_m1": {"t_stat": m2prime_vs_m1_t, "p_value": m2prime_vs_m1_p,
                              "interpretation": "significant" if m2prime_vs_m1_p and m2prime_vs_m1_p < 0.05 else "not significant"},
        },
        "scaling_analysis": {
            "training_records_m1": 117,
            "training_records_m2prime": 118,
            "record_increase": 1,
            "increase_pct": "0.9%",
            "m1_correctness": round(m1_agg["correctness"]["mean"], 4),
            "m2prime_correctness": round(m2prime_agg["correctness"]["mean"], 4),
            "correctness_delta_m2prime_vs_m1": round(m2prime_agg["correctness"]["mean"] - m1_agg["correctness"]["mean"], 4),
        },
        "per_example_comparison": m1_m2prime_comparison,
        "m2prime_vs_m1_counts": {
            "m2prime_better": m2prime_improved_over_m1,
            "m1_better": m1_improved_over_m2prime,
            "unchanged": unchanged,
            "total": len(m1_m2prime_comparison),
        },
        "failure_analysis": {
            "m2prime_records_below_0.4": len(m2prime_failures),
            "m2prime_regressions_from_baseline": len(m2prime_regressions),
            "biggest_m2prime_gains": [{"record_id": r["record_id"], "baseline": r["baseline"], "m2prime": r["m2prime"], "delta": r["m2prime_delta"]} for r in m2prime_gains],
            "biggest_m2prime_losses": [{"record_id": r["record_id"], "baseline": r["baseline"], "m2prime": r["m2prime"], "delta": r["m2prime_delta"]} for r in m2prime_losses],
        },
    }

    (OUT_DIR / "m2prime_evaluation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (OUT_DIR / "m2prime_per_example.jsonl").open("w", encoding="utf-8") as f:
        for r in m1_m2prime_comparison:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (OUT_DIR / "m2prime_baseline_results.jsonl").open("w", encoding="utf-8") as f:
        for r in baseline_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (OUT_DIR / "m2prime_m1_results.jsonl").open("w", encoding="utf-8") as f:
        for r in m1_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (OUT_DIR / "m2prime_m2prime_results.jsonl").open("w", encoding="utf-8") as f:
        for r in m2prime_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n=== Results ===")
    print(f"Baseline correctness: {baseline_agg['correctness']['mean']:.4f} (N={baseline_agg['evaluated_examples']})")
    print(f"M1 correctness:       {m1_agg['correctness']['mean']:.4f} (N={m1_agg['evaluated_examples']})")
    print(f"M2' correctness:      {m2prime_agg['correctness']['mean']:.4f} (N={m2prime_agg['evaluated_examples']})")
    print(f"M1 vs Baseline delta: {m1_agg['correctness']['mean'] - baseline_agg['correctness']['mean']:+.4f}")
    print(f"M2' vs Baseline delta: {m2prime_agg['correctness']['mean'] - baseline_agg['correctness']['mean']:+.4f}")
    print(f"M2' vs M1 delta:       {m2prime_agg['correctness']['mean'] - m1_agg['correctness']['mean']:+.4f}")
    print(f"M2' better than M1: {m2prime_improved_over_m1}, M1 better than M2': {m1_improved_over_m2prime}, Unchanged: {unchanged}")
    print(f"\nWrote to {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
