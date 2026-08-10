#!/usr/bin/env python3
"""
run_phase6_baseline_eval.py — Atlas Phase 6.3 baseline evaluation runner.

Runs Qwen2.5-7B-Instruct (NF4 4-bit + double quant + bf16 compute) on the
Phase 6.2 expanded evaluation sets:

  - evaluation/eval_sets/phase6_expansion_v1/math_eval_v1.jsonl  (N=100)
  - evaluation/eval_sets/phase6_expansion_v1/code_eval_v1.jsonl  (N=100)

and scores every generated response with the QEE v2 engine
(scripts/evaluation_engine/v2/). Answer-type dispatch uses the record's
authoritative view_id (math-300m -> math, code-300m -> code).

Constraints honored:
  - No model training.
  - No dataset / training-view / release modification.
  - No QEE scoring-logic change.
  - Outputs under experiments/phase6_baseline_eval/ only.

Outputs:
  config.json
  baseline.json
  per_example_results.jsonl
  hardware_info.json

Run:
  .venv-eval/bin/python experiments/phase6_baseline_eval/run_phase6_baseline_eval.py
  .venv-eval/bin/python experiments/phase6_baseline_eval/run_phase6_baseline_eval.py --rescore-only
"""
from __future__ import annotations

import gc
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"

REPO = Path("/mnt/d/atlas-dataset")
EVAL_SETS = REPO / "evaluation" / "eval_sets" / "phase6_expansion_v1"
EXPERIMENT = REPO / "experiments" / "phase6_baseline_eval"
OUTPUT_FILE = EXPERIMENT / "baseline.json"
PER_EXAMPLE_FILE = EXPERIMENT / "per_example_results.jsonl"
CONFIG_FILE = EXPERIMENT / "config.json"
HARDWARE_FILE = EXPERIMENT / "hardware_info.json"

MAX_NEW_TOKENS = 512
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

EVAL_FILES = {
    "math": EVAL_SETS / "math_eval_v1.jsonl",
    "code": EVAL_SETS / "code_eval_v1.jsonl",
}
VIEW_TO_TYPE = {"math-300m": "math", "code-300m": "code"}

sys.path.insert(0, str(REPO / "scripts"))
from evaluation_engine.v2.engine import QeeV2Engine  # noqa: E402


def load_model_and_tokenizer(model_id: str):
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=False,
    )
    model.eval()
    return model, tokenizer


def build_prompt(record: dict, tokenizer) -> str:
    messages = record.get("messages") or []
    if messages:
        try:
            return tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        except Exception:
            parts = [f"{m.get('role', 'user')}: {m.get('content', '')}\n" for m in messages]
            parts.append("assistant: ")
            return "\n".join(parts)
    return f"user: {record.get('problem', '')}\nassistant: "


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
    if atype == "math":
        format_ok = 1.0 if method != "no_final_answer" else 0.0
    elif atype == "code":
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


def load_records():
    recs_by_key = {}
    for fam, path in EVAL_FILES.items():
        rows = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        recs_by_key[fam] = rows
    return recs_by_key


def run_full_inference():
    print(f"Phase: phase6_baseline_eval (6.3)")
    print(f"Base model: {BASE_MODEL}")
    print(f"Device: {DEVICE}")
    if DEVICE == "cuda":
        props = torch.cuda.get_device_properties(0)
        print(f"GPU: {props.name}")

    print(f"\nLoading {BASE_MODEL} ...")
    try:
        model, tokenizer = load_model_and_tokenizer(BASE_MODEL)
    except Exception as e:
        print(f"MODEL_LOAD_FAILURE: {e}")
        baseline = {
            "experiment_id": "phase6_baseline_eval", "phase": "6.3",
            "evaluation_id": "phase6_baseline", "status": "BLOCKED",
            "model": "BASE_MODEL", "model_id": BASE_MODEL, "adapter_path": None,
            "error": str(e),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "domain_aggregates": {}, "overall_aggregate": {}, "total_examples": 0,
        }
        OUTPUT_FILE.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        sys.exit(2)

    recs_by_key = load_records()
    domain_aggregates = {}
    per_example_all = []

    for fam, rows in recs_by_key.items():
        results = []
        for rec in rows:
            rid = rec.get("record_id")
            try:
                response, n_tokens, latency_s = generate_response(model, tokenizer, rec)
                score = score_with_qee_v2(rec, response)
                metrics = v2_metrics(score, response)
                tokens_per_sec = n_tokens / latency_s if latency_s > 0 else 0.0
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
                    "tokens_per_sec": round(tokens_per_sec, 2),
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
        domain_aggregates[fam] = aggregate(results, len(rows))
        per_example_all.extend(results)
        print(f"  {fam}: {json.dumps(domain_aggregates[fam])}")

    peak_malloc_mib = None
    vram_reserved_mib = None
    if DEVICE == "cuda":
        peak_malloc_mib = torch.cuda.max_memory_allocated() / 1024**2
        vram_reserved_mib = torch.cuda.memory_reserved() / 1024**2

    del model
    del tokenizer
    gc.collect()
    if DEVICE == "cuda":
        torch.cuda.empty_cache()

    return per_example_all, domain_aggregates, {
        "gpu_info": gpu_info_fn(), "peak_malloc_mib": peak_malloc_mib,
        "vram_reserved_mib": vram_reserved_mib,
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


def rescore_only():
    print("Rescore-only mode: re-scoring cached predictions (no model load).")
    cached = []
    with PER_EXAMPLE_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cached.append(json.loads(line))

    recs_by_id = {}
    for fam, rows in load_records().items():
        for rec in rows:
            recs_by_id[(fam, rec.get("record_id"))] = rec

    domain_aggregates = {}
    per_example_all = []
    for fam in EVAL_FILES:
        results = []
        for row in cached:
            rid = row.get("record_id")
            key = (fam, rid)
            if key in recs_by_id:
                rec = recs_by_id[key]
                response = row.get("predicted_response") or ""
                if response.startswith("ERROR:"):
                    results.append(row)
                    continue
                score = score_with_qee_v2(rec, response)
                metrics = v2_metrics(score, response)
                new_row = {
                    "record_id": rid,
                    "view_id": rec.get("view_id"),
                    "category": rec.get("category"),
                    "difficulty": rec.get("difficulty"),
                    "original_id": rec.get("original_id"),
                    "predicted_response": response,
                    "reference_answer": get_reference_answer(rec),
                    "latency_s": row.get("latency_s"),
                    "tokens_generated": row.get("tokens_generated"),
                    "tokens_per_sec": row.get("tokens_per_sec"),
                    **metrics,
                    "v2": dict(score),
                }
                results.append(new_row)
        domain_aggregates[fam] = aggregate(results, len(results))
        per_example_all.extend(results)
        print(f"  {fam}: {json.dumps(domain_aggregates[fam])}")

    overall = {
        k: round(sum(d.get(k, 0.0) for d in domain_aggregates.values()) / len(domain_aggregates), 4)
        for k in ("correctness", "reasoning_quality", "hallucination_rate",
                  "answer_format_consistency")
    }
    baseline = {
        "experiment_id": "phase6_baseline_eval", "phase": "6.3",
        "evaluation_id": "phase6_baseline", "status": "COMPLETE",
        "model": "BASE_MODEL", "model_id": BASE_MODEL, "adapter_path": None,
        "hardware": gpu_info_fn(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inference_config": {
            "base_model": BASE_MODEL, "quantization": "4bit_nf4_double_quant",
            "max_new_tokens": MAX_NEW_TOKENS, "sampling": "greedy",
        },
        "scoring": {
            "engine": "scripts/evaluation_engine/v2 (QEE v2)",
            "dispatch": "authoritative view_id category (math/code)",
            "dimensions": "7-dim weighted rubric",
        },
        "domain_aggregates": domain_aggregates,
        "overall_aggregate": overall,
        "total_examples": len(per_example_all),
        "per_example_path": str(PER_EXAMPLE_FILE),
    }
    OUTPUT_FILE.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with PER_EXAMPLE_FILE.open("w", encoding="utf-8") as f:
        for r in per_example_all:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nRescore complete -> {OUTPUT_FILE}")


def main():
    if "--rescore-only" in sys.argv:
        rescore_only()
        return
    EXPERIMENT.mkdir(parents=True, exist_ok=True)

    per_example_all, domain_aggregates, extra = run_full_inference()
    gpu_info = extra["gpu_info"]
    if gpu_info:
        gpu_info["peak_vram_allocated_mib"] = round(extra["peak_malloc_mib"], 2) if extra["peak_malloc_mib"] else None
        gpu_info["peak_vram_reserved_mib"] = round(extra["vram_reserved_mib"], 2) if extra["vram_reserved_mib"] else None

    overall = {
        k: round(sum(d.get(k, 0.0) for d in domain_aggregates.values()) / len(domain_aggregates), 4)
        for k in ("correctness", "reasoning_quality", "hallucination_rate",
                  "answer_format_consistency")
    }
    baseline = {
        "experiment_id": "phase6_baseline_eval", "phase": "6.3",
        "evaluation_id": "phase6_baseline", "status": "COMPLETE",
        "model": "BASE_MODEL", "model_id": BASE_MODEL, "adapter_path": None,
        "hardware": gpu_info,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inference_config": {
            "base_model": BASE_MODEL, "quantization": "4bit_nf4_double_quant",
            "max_new_tokens": MAX_NEW_TOKENS, "sampling": "greedy",
        },
        "scoring": {
            "engine": "scripts/evaluation_engine/v2 (QEE v2)",
            "dispatch": "authoritative view_id category (math/code)",
            "dimensions": "7-dim weighted rubric",
        },
        "domain_aggregates": domain_aggregates,
        "overall_aggregate": overall,
        "total_examples": len(per_example_all),
        "per_example_path": str(PER_EXAMPLE_FILE),
    }
    OUTPUT_FILE.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with PER_EXAMPLE_FILE.open("w", encoding="utf-8") as f:
        for r in per_example_all:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    config = {
        "experiment_id": "phase6_baseline_eval", "phase": "6.3",
        "objective": "Baseline QEE v2 evaluation on the Phase 6.2 expanded eval sets.",
        "scope": "baseline inference/evaluation only. No training, dataset, training-view, or QEE logic change.",
        "constraints": [
            "No model training", "No dataset modification", "No training-view modification",
            "No QEE scoring-logic change", "All outputs under experiments/phase6_baseline_eval/",
        ],
        "base_model": BASE_MODEL,
        "generation": {
            "max_new_tokens": MAX_NEW_TOKENS, "sampling": "greedy", "seed": None,
            "quantization": "4bit_nf4_double_quant", "compute_dtype": "bfloat16",
        },
        "eval_sets": {k: str(v) for k, v in EVAL_FILES.items()},
        "scoring": {
            "engine": "scripts/evaluation_engine/v2 (QEE v2)",
            "dispatch": "authoritative view_id category",
            "dimensions": ["accuracy", "completeness", "technical_correctness",
                           "clarity", "usefulness", "originality", "relevance"],
        },
        "artifacts": {
            "config": str(CONFIG_FILE), "baseline": str(OUTPUT_FILE),
            "per_example": str(PER_EXAMPLE_FILE), "hardware_info": str(HARDWARE_FILE),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    hardware = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": "dev-pc (WSL2 Ubuntu-24.04)",
        "gpu": gpu_info,
        "python": sys.version,
        "venv": ".venv-eval",
        "packages": {},
    }
    try:
        import transformers
        import accelerate
        import bitsandbytes
        hardware["packages"] = {
            "torch": torch.__version__, "transformers": transformers.__version__,
            "accelerate": accelerate.__version__, "bitsandbytes": bitsandbytes.__version__,
        }
    except Exception as e:
        hardware["packages_error"] = str(e)
    HARDWARE_FILE.write_text(json.dumps(hardware, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nPhase 6.3 baseline written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
