#!/usr/bin/env python3
"""
run_p8a_eval.py — Atlas P8-A post-training evaluation on code_eval_v1.

Loads the P8-A trained LoRA adapter on Qwen/Qwen2.5-7B-Instruct (NF4 4-bit +
double quant + bf16), verifies adapter load, generates greedy responses on the
frozen code_eval_v1 split (N=100), and scores every response with the frozen
QEE v2 engine (code dispatch by authoritative view_id, identical to the
Phase 6.3 baseline evaluation so deltas are comparable).

Scope: code_eval_v1 ONLY (mission constraint). No math evaluation.

Constraints honored:
  - Does NOT modify the dataset, eval sets, training views, or QEE engine.
  - Outputs remain under experiments/atlas-math-small-qwen7b-lora-transfer-v1/.

Outputs:
  - evaluation/post_training.json          aggregate metrics
  - evaluation/post_training_per_example.jsonl
  - evaluation/adapter_metadata.json

Run (on the training box):
  .venv-eval/bin/python experiments/atlas-math-small-qwen7b-lora-transfer-v1/run_p8a_eval.py
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
REPO = Path("/mnt/d/atlas-dataset")
EXPERIMENT = REPO / "experiments" / "atlas-math-small-qwen7b-lora-transfer-v1"
ADAPTER_DIR = EXPERIMENT / "checkpoints"
EVAL_JSONL = REPO / "evaluation" / "eval_sets" / "phase6_expansion_v1" / "code_eval_v1.jsonl"
EVAL_DIR = EXPERIMENT / "evaluation"

MAX_NEW_TOKENS = 512
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
VIEW_TO_TYPE = {"code-300m": "code"}

sys.path.insert(0, str(REPO / "scripts"))
from evaluation_engine.v2.engine import QeeV2Engine  # noqa: E402


def get_reference_answer(record: dict) -> str:
    for m in record.get("messages") or []:
        if m.get("role") == "assistant":
            return (m.get("content") or "").strip()
    return record.get("solution") or ""


def user_text(record: dict) -> str:
    for m in record.get("messages") or []:
        if m.get("role") == "user":
            return (m.get("content") or "").strip()
    return record.get("problem", "")


def build_prompt(record: dict, tokenizer) -> str:
    messages = record.get("messages") or []
    if messages:
        try:
            return tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            parts = [f"{m.get('role', 'user')}: {m.get('content', '')}\n" for m in messages]
            parts.append("assistant: ")
            return "\n".join(parts)
    return f"user: {record.get('problem', '')}\nassistant: "


@torch.no_grad()
def generate_response(model, tokenizer, record: dict) -> tuple[str, int, float]:
    prompt = build_prompt(record, tokenizer)
    inputs = tokenizer(prompt, return_tensors="pt").to(DEVICE)
    input_len = inputs["input_ids"].shape[1]
    t0 = time.perf_counter()
    gen_ids = model.generate(
        **inputs,
        max_new_tokens=MAX_NEW_TOKENS,
        do_sample=False,
        pad_token_id=tokenizer.pad_token_id,
    )
    latency_s = time.perf_counter() - t0
    new_tokens = gen_ids[0][input_len:]
    text = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    return text, int(new_tokens.numel()), latency_s


def score_with_qee_v2(record: dict, response: str) -> dict:
    atype = VIEW_TO_TYPE.get(record.get("view_id"), "semantic")
    question = user_text(record)
    reference = get_reference_answer(record)

    engine = QeeV2Engine()
    _, result = engine._type_result(atype, question, reference, response)
    dim_breakdown = engine._dimensions(atype, result, question, reference, response)
    dims = {k: v["score"] for k, v in dim_breakdown.items()}
    raw_continuous = sum(engine.weights[k] * dims[k] for k in engine.weights)
    continuous, score = engine._map_to_scale(raw_continuous)

    flags = []
    if result.correct is False:
        flags.append("incorrect")
    elif result.correct is None:
        flags.append("unverifiable")
    if result.score < 0.4:
        flags.append("low_correctness")

    return {
        "answer_type": atype,
        "correctness": round(float(result.score), 4),
        "correct": result.correct,
        "quality_score": score,
        "quality_continuous": round(float(continuous), 4),
        "method": getattr(result, "method", "rubric"),
        "flags": flags,
        "dimensions": {k: round(v, 3) for k, v in dims.items()},
    }


def v2_metrics(score: dict, response: str) -> dict:
    correctness = float(score["correctness"])
    reasoning_quality = float(score["quality_continuous"])
    hallucination_rate = 1.0 if score["correct"] is False and correctness < 0.4 else 0.0
    atype = score["answer_type"]
    method = score["method"]
    if atype == "code":
        format_ok = 1.0 if method not in ("empty", "syntax") else 0.0
    else:
        format_ok = 1.0 if response.strip() else 0.0
    return {
        "correctness": correctness,
        "reasoning_quality": reasoning_quality,
        "hallucination_rate": hallucination_rate,
        "answer_format_consistency": format_ok,
    }


def aggregate(results: list[dict], total: int) -> dict:
    valid = [r for r in results if r["correctness"] is not None]
    n = len(valid) if valid else 1
    return {
        "correctness": round(sum(r["correctness"] for r in valid) / n, 4),
        "reasoning_quality": round(sum(r["reasoning_quality"] for r in valid) / n, 4),
        "hallucination_rate": round(sum(r["hallucination_rate"] for r in valid) / n, 4),
        "answer_format_consistency": round(sum(r["answer_format_consistency"] for r in valid) / n, 4),
        "latency_s_mean": round(sum(r["latency_s"] for r in valid) / n, 4) if valid else None,
        "tokens_per_sec_mean": round(sum(r["tokens_per_sec"] for r in valid) / n, 2) if valid else None,
        "evaluated_examples": len(valid),
        "total_examples": total,
    }


def gpu_info_fn():
    if DEVICE != "cuda":
        return None
    props = torch.cuda.get_device_properties(0)
    return {
        "device": "cuda",
        "gpu_name": props.name,
        "vram_total_mib": round(props.total_memory / 1024**2, 2),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
    }


def main():
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"=== P8-A post-training QEE v2 eval | device={DEVICE} ===")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
    )
    print(f"Loading base {BASE_MODEL} ...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, quantization_config=bnb_config, device_map="auto",
        trust_remote_code=False)
    model.eval()

    if not (ADAPTER_DIR / "adapter_config.json").exists():
        raise SystemExit(f"adapter not found at {ADAPTER_DIR}")
    adapter_config = json.loads((ADAPTER_DIR / "adapter_config.json").read_text())
    print(f"Loading LoRA adapter (r={adapter_config.get('r')}, "
          f"alpha={adapter_config.get('lora_alpha')}) ...")
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
        "peft_config": model.peft_config,
        "active_adapter": list(active),
        "trainable_params_on_eval": int(trainable),
        "total_params_on_eval": int(total),
    }
    (EVAL_DIR / "adapter_metadata.json").write_text(
        json.dumps(adapter_meta, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print("  adapter loaded OK -> adapter_metadata.json")

    if DEVICE == "cuda":
        model = model.to(DEVICE)
        print(f"GPU: {torch.cuda.get_device_properties(0).name}")

    records = []
    with EVAL_JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    print(f"eval records: {len(records)} (code_eval_v1)")

    results = []
    for rec in records:
        rid = rec.get("record_id")
        try:
            response, n_tokens, latency_s = generate_response(model, tokenizer, rec)
            score = score_with_qee_v2(rec, response)
            metrics = v2_metrics(score, response)
            tps = n_tokens / latency_s if latency_s > 0 else 0.0
            results.append({
                "record_id": rid,
                "view_id": rec.get("view_id"),
                "category": rec.get("category"),
                "difficulty": rec.get("difficulty"),
                "original_id": rec.get("original_id"),
                "predicted_response": response,
                "reference_answer": get_reference_answer(rec),
                "latency_s": round(latency_s, 4),
                "tokens_generated": n_tokens,
                "tokens_per_sec": round(tps, 2),
                **metrics,
                "v2": dict(score),
            })
        except Exception as e:
            results.append({
                "record_id": rid,
                "view_id": rec.get("view_id"),
                "category": rec.get("category"),
                "difficulty": rec.get("difficulty"),
                "original_id": rec.get("original_id"),
                "predicted_response": f"ERROR: {e}",
                "reference_answer": get_reference_answer(rec),
                "latency_s": None, "tokens_generated": None, "tokens_per_sec": None,
                "correctness": None, "reasoning_quality": None,
                "hallucination_rate": None, "answer_format_consistency": None,
                "v2": {},
            })

    agg = aggregate(results, len(records))
    print("post-training agg:", json.dumps(agg, indent=2))

    post = {
        "experiment_id": "atlas-math-small-qwen7b-lora-transfer-v1",
        "phase": "8", "sprint": "P8-A",
        "evaluation_id": "post_training_code_eval_v1", "status": "COMPLETE",
        "model": "LORA_ADAPTER", "model_id": BASE_MODEL,
        "adapter_path": str(ADAPTER_DIR),
        "hardware": gpu_info_fn(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inference_config": {"base_model": BASE_MODEL, "adapter": str(ADAPTER_DIR),
                             "quantization": "4bit_nf4_double_quant",
                             "max_new_tokens": MAX_NEW_TOKENS, "sampling": "greedy"},
        "scoring": {"engine": "scripts/evaluation_engine/v2 (QEE v2)",
                    "dispatch": "authoritative view_id category: code"},
        "dataset": {"eval_split": "evaluation/eval_sets/phase6_expansion_v1/code_eval_v1.jsonl",
                    "eval_jsonl": str(EVAL_JSONL), "n_records": len(records)},
        "aggregate": agg,
        "total_examples": len(results),
    }
    (EVAL_DIR / "post_training.json").write_text(
        json.dumps(post, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (EVAL_DIR / "post_training_per_example.jsonl").open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("\nWrote post_training.json + post_training_per_example.jsonl")


if __name__ == "__main__":
    main()
