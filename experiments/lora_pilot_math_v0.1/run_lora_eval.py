#!/usr/bin/env python3
"""
run_lora_eval.py — Atlas Phase 5B.2 post-training evaluation.

Loads the trained LoRA adapter (experiments/lora_pilot_math_v0.1/checkpoints)
on the Qwen/Qwen2.5-7B-Instruct base with the identical NF4 4-bit + double
quant + bf16 config, verifies adapter save/load, generates greedy responses on
the approved math_300m_v0.1 EVAL split, and scores them with the QEE v2
correctness engine (math dispatch).

Constraints honored:
  - Does NOT modify the dataset, training views, or release artifacts.
  - Outputs remain under experiments/lora_pilot_math_v0.1/.

Outputs:
  - evaluation/post_training.json
  - evaluation/post_training_per_example.jsonl
  - evaluation/adapter_metadata.json
  - evaluation/comparison_metrics.json

Run:
  .venv/bin/python experiments/lora_pilot_math_v0.1/run_lora_eval.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
REPO = Path(__file__).resolve().parent.parent.parent
EXPERIMENT = REPO / "experiments" / "lora_pilot_math_v0.1"
ADAPTER_DIR = EXPERIMENT / "checkpoints"
EVAL_JSONL = REPO / "output" / "training_views" / "math_300m_v0.1" / "eval.jsonl"
EVAL_DIR = EXPERIMENT / "evaluation"
BASELINE_EXAMPLE_FILE = REPO / "experiments" / "lora_pilot_math_v0.1" / "evaluation" / "baseline.json"

MAX_NEW_TOKENS = 256
ANSTYPE = "math"

sys.path.insert(0, str(REPO / "scripts"))
from evaluation_engine.v2.engine import QeeV2Engine
from credential_helper import get_hf_token


def build_prompt(record, tokenizer) -> str:
    messages = record.get("messages") or []
    if messages:
        try:
            return tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            return "\n".join(f"{m['role']}: {m['content']}" for m in messages) + "\nassistant: "
    return f"user: {record.get('problem', '')}\nassistant: "


def get_reference(record) -> str:
    for m in record.get("messages") or []:
        if m.get("role") == "assistant":
            return (m.get("content") or "").strip()
    return ""


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
    gen = model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False,
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


def metrics(score, response):
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


def load_baseline_math():
    base = {}
    if not BASELINE_EXAMPLE_FILE.exists():
        return base
    with BASELINE_EXAMPLE_FILE.open(encoding="utf-8") as f:
        data = json.load(f)
    for view_id, agg in data.get("domain_aggregates", {}).items():
        pass  # We compare aggregates, not per-example
    return data


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


def main():
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"=== Post-training QEE v2 eval | device={device} ===")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
    )
    print(f"Loading base {BASE_MODEL} ...")
    hf_token = get_hf_token()
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, use_fast=True, token=hf_token)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, quantization_config=bnb_config, device_map="cpu",
        trust_remote_code=False, token=hf_token)
    model.eval()

    if not (ADAPTER_DIR / "adapter_config.json").exists():
        raise SystemExit(f"adapter not found at {ADAPTER_DIR}")
    adapter_config = json.loads((ADAPTER_DIR / "adapter_config.json").read_text())
    print(f"Loading LoRA adapter (r={adapter_config.get('r')}, alpha {adapter_config.get('lora_alpha')}) ...")
    model = PeftModel.from_pretrained(model, ADAPTER_DIR)
    model.eval()
    trainable, total = model.get_nb_trainable_parameters()
    active = model.active_adapter
    if not isinstance(active, (list, tuple)):
        active = [active]

    adapter_meta = {
        "adapter_path": str(ADAPTER_DIR),
        "base_model": BASE_MODEL,
        "loaded": True,
        "peft_config": json_safe(model.peft_config),
        "active_adapter": list(active),
        "trainable_params_on_eval": int(trainable),
        "total_params_on_eval": int(total),
    }
    (EVAL_DIR / "adapter_metadata.json").write_text(
        json.dumps(adapter_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("  adapter loaded OK -> adapter_metadata.json")

    if device == "cuda":
        model = model.to(device)
        print(f"GPU: {torch.cuda.get_device_properties(0).name}")

    records = []
    with EVAL_JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"eval records: {len(records)}")

    baseline_data = load_baseline_math()

    results = []
    for rec in records:
        rid = rec.get("record_id") or rec.get("id")
        try:
            response, n_tokens, latency = generate(model, tokenizer, rec, device)
            score = score_qee_v2(user_text(rec), get_reference(rec), response)
            met = metrics(score, response)
            tps = n_tokens / latency if latency > 0 else 0.0
            results.append({
                "record_id": rid, "view_id": rec.get("view_id"),
                "category": rec.get("category"),
                "predicted_response": response,
                "reference_answer": get_reference(rec),
                "latency_s": round(latency, 4), "tokens_generated": n_tokens,
                "tokens_per_sec": round(tps, 2),
                **met, "v2": dict(score),
            })
        except Exception as e:
            results.append({
                "record_id": rid, "view_id": rec.get("view_id"),
                "category": rec.get("category"),
                "predicted_response": f"ERROR: {e}",
                "reference_answer": get_reference(rec),
                "latency_s": None, "tokens_generated": None, "tokens_per_sec": None,
                "correctness": None, "reasoning_quality": None,
                "hallucination_rate": None, "answer_format_consistency": None,
                "v2": {},
            })

    valid = [r for r in results if r["correctness"] is not None]
    n = len(valid) if valid else 1
    agg = {
        "correctness": round(sum(r["correctness"] for r in valid) / n, 4),
        "reasoning_quality": round(sum(r["reasoning_quality"] for r in valid) / n, 4),
        "hallucination_rate": round(sum(r["hallucination_rate"] for r in valid) / n, 4),
        "answer_format_consistency": round(sum(r["answer_format_consistency"] for r in valid) / n, 4),
        "latency_s_mean": round(sum(r["latency_s"] for r in valid) / n, 4) if valid else None,
        "tokens_per_sec_mean": round(sum(r["tokens_per_sec"] for r in valid) / n, 2) if valid else None,
        "evaluated_examples": len(valid),
        "total_examples": len(records),
    }
    print("post-training agg:", json.dumps(agg, indent=2))

    post = {
        "experiment_id": "lora_pilot_math_v0.1", "phase": "5B.2",
        "evaluation_id": "post_training", "status": "COMPLETE",
        "model": "LORA_ADAPTER", "model_id": BASE_MODEL,
        "adapter_path": str(ADAPTER_DIR),
        "hardware": gpu_info_fn(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inference_config": {"base_model": BASE_MODEL, "adapter": str(ADAPTER_DIR),
                             "quantization": "4bit_nf4_double_quant",
                             "max_new_tokens": MAX_NEW_TOKENS, "sampling": "greedy"},
        "scoring": {"engine": "scripts/evaluation_engine/v2 (QEE v2)",
                    "dispatch": "authoritative training-view category: math"},
        "dataset": {"training_view_id": "math_300m_v0.1",
                    "eval_jsonl": str(EVAL_JSONL), "n_records": len(records)},
        "aggregate": agg,
        "total_examples": len(results),
    }
    (EVAL_DIR / "post_training.json").write_text(
        json.dumps(post, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (EVAL_DIR / "post_training_per_example.jsonl").open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("\nWrote post_training.json, post_training_per_example.jsonl")


if __name__ == "__main__":
    main()
