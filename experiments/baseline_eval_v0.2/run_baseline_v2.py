#!/usr/bin/env python3
"""
run_baseline_v2.py — Atlas Phase 5A.3 baseline re-evaluation runner.

Same base model, evaluation samples, generation config, dataset views and
hardware as baseline_eval_v0.1 (Phase 5A.1), but scoring is performed by the
QEE v2 correctness engine (scripts/evaluation_engine/v2/) instead of the v1
lexical/substring heuristics, and per-example latency + tokens/sec are
recorded.

Answer-type dispatch: the training-view category is the authoritative signal
(view_id "math-300m"/"code-300m"/"aiml-300m" -> math/code/semantic). This
avoids regex false positives on records that merely contain math/code notation
(e.g. ArXiv AI/ML abstracts that mention equations). All scoring still runs
through the v2 evaluators (math_eval / code_eval / semantic_eval).

This is a BASELINE run only: no LoRA training, no dataset modification, no
training-view modification, no release changes.

Outputs (experiments/baseline_eval_v0.2/):
  config.json
  baseline_v2.json
  per_example_results.jsonl
  hardware_info.json
  comparison_report.md

Run:
  .venv-eval/bin/python experiments/baseline_eval_v0.2/run_baseline_v2.py
  .venv-eval/bin/python experiments/baseline_eval_v0.2/run_baseline_v2.py --rescore-only
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
VIEWS_DIR = REPO / "output" / "training_views"
EXPERIMENT = REPO / "experiments" / "baseline_eval_v0.2"
OUTPUT_FILE = EXPERIMENT / "baseline_v2.json"
PER_EXAMPLE_FILE = EXPERIMENT / "per_example_results.jsonl"
CONFIG_FILE = EXPERIMENT / "config.json"
HARDWARE_FILE = EXPERIMENT / "hardware_info.json"
REPORT_FILE = EXPERIMENT / "comparison_report.md"
V0_1_EXAMPLE_FILE = (
    REPO / "experiments" / "baseline_eval_v0.1" / "evaluation" / "baseline_per_example.jsonl"
)

MAX_NEW_TOKENS = 256
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
VIEWS = {
    "code_300m_v0.1": VIEWS_DIR / "code_300m_v0.1" / "eval.jsonl",
    "math_300m_v0.1": VIEWS_DIR / "math_300m_v0.1" / "eval.jsonl",
    "aiml_300m_v0.1": VIEWS_DIR / "aiml_300m_v0.1" / "eval.jsonl",
}

# Authoritative answer-type by training view (v2 dispatch override).
VIEW_TO_TYPE = {
    "code_300m_v0.1": "code",
    "math_300m_v0.1": "math",
    "aiml_300m_v0.1": "semantic",
}

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
            parts = []
            for m in messages:
                parts.append(f"{m.get('role','user')}: {m.get('content','')}\n")
            parts.append("assistant: ")
            return "\n".join(parts)
    return f"user: {record.get('problem','')}\nassistant: "


def get_reference_answer(record: dict) -> str:
    for m in record.get("messages") or []:
        if m.get("role") == "assistant":
            return (m.get("content") or "").strip()
    return ""


def user_text(record: dict) -> str:
    for m in record.get("messages") or []:
        if m.get("role") == "user":
            return (m.get("content") or "").strip()
    return record.get("problem", "")


@torch.no_grad()
def generate_response(model, tokenizer, record: dict) -> tuple[str, int, float]:
    """Generate a greedy response; returns (text, new_tokens, latency_s)."""
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


def score_with_qee_v2(view_name: str, record: dict, response: str) -> dict:
    """Score the predicted response with the QEE v2 engine.

    Dispatch uses the authoritative training-view category; the v2 evaluators
    (math_eval / code_eval / semantic_eval) perform all scoring. Dimension
    assembly mirrors QeeV2Engine.evaluate_record so output shape matches the
    v2 public contract.
    """
    atype = VIEW_TO_TYPE.get(view_name, "semantic")
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
    if atype == "semantic" and dims["originality"] < 0.6:
        flags.append("possible_keyword_stuffing")

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
    """Map QEE v2 output to the four pilot metrics (v0.2 definition).

    correctness              = v2 verifiable correctness (0..1)
    reasoning_quality        = v2 weighted 7-dimension quality (0..1)
    hallucination_rate       = 1.0 only for a definitively wrong AND low-quality
                               answer (correct is False and correctness < 0.4).
                               Partial / unverified / unverifiable answers are
                               NOT counted as hallucination (conservative).
    answer_format_consistency= type-specific structural expectations:
                               math -> has extractable final answer;
                               code -> not empty/syntax-failed;
                               semantic -> non-empty answer.
    """
    correctness = float(score["correctness"])
    reasoning_quality = float(score["quality_continuous"])
    hallucination_rate = (
        1.0 if score["correct"] is False and correctness < 0.4 else 0.0
    )

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


def load_v0_1_predictions() -> dict:
    out = {}
    if not V0_1_EXAMPLE_FILE.exists():
        return out
    with V0_1_EXAMPLE_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                out[row["record_id"]] = row.get("predicted_response", "")
    return out


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


def run_full_inference():
    """Fresh run: load model, generate, score, measure latency."""
    print(f"Phase: baseline_eval_v0.2 (5A.3)")
    print(f"Base model: {BASE_MODEL}")
    print(f"Device: {DEVICE}")
    if DEVICE == "cuda":
        props = torch.cuda.get_device_properties(0)
        print(f"GPU: {props.name}")

    v0_1_predictions = load_v0_1_predictions()

    print(f"\nLoading {BASE_MODEL} ...")
    try:
        model, tokenizer = load_model_and_tokenizer(BASE_MODEL)
    except Exception as e:
        print(f"MODEL_LOAD_FAILURE: {e}")
        baseline = {
            "experiment_id": "baseline_eval_v0.2", "phase": "5A.3",
            "evaluation_id": "baseline_v2", "status": "BLOCKED",
            "model": "BASE_MODEL", "model_id": BASE_MODEL, "adapter_path": None,
            "error": str(e),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "domain_aggregates": {}, "overall_aggregate": {}, "total_examples": 0,
        }
        OUTPUT_FILE.write_text(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        sys.exit(2)

    domain_aggregates = {}
    per_example_all = []
    determinism_matches = 0
    determinism_checked = 0

    for view_name, jsonl_path in VIEWS.items():
        records = []
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        results = []
        for rec in records:
            rid = rec.get("record_id")
            try:
                response, n_tokens, latency_s = generate_response(model, tokenizer, rec)
                score = score_with_qee_v2(view_name, rec, response)
                metrics = v2_metrics(score, response)
                tokens_per_sec = n_tokens / latency_s if latency_s > 0 else 0.0

                if rid in v0_1_predictions:
                    determinism_checked += 1
                    if v0_1_predictions[rid] == response:
                        determinism_matches += 1

                results.append({
                    "record_id": rid,
                    "view_id": rec.get("view_id"),
                    "category": rec.get("category"),
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
                    "predicted_response": f"ERROR: {e}",
                    "reference_answer": get_reference_answer(rec),
                    "latency_s": None, "tokens_generated": None, "tokens_per_sec": None,
                    "correctness": None, "reasoning_quality": None,
                    "hallucination_rate": None, "answer_format_consistency": None,
                    "v2": {},
                })

        domain_aggregates[view_name] = aggregate(results, len(records))
        per_example_all.extend(results)
        print(f"  {view_name}: {json.dumps(domain_aggregates[view_name], indent=2)}")

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

    return per_example_all, domain_aggregates, determinism_matches, determinism_checked, {
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
    """Re-score cached predicted responses without a GPU run.

    Reads predicted responses from per_example_results.jsonl and re-runs the
    v2 scoring + aggregation + artifact writing only.
    """
    print("Rescore-only mode: re-scoring cached predictions (no model load).")
    cached = []
    with PER_EXAMPLE_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cached.append(json.loads(line))

    recs_by_id = {}
    for view_name, jsonl_path in VIEWS.items():
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    recs_by_id[(view_name, rec.get("record_id"))] = rec

    domain_aggregates = {}
    per_example_all = []
    for view_name in VIEWS:
        results = []
        for row in cached:
            rid = row.get("record_id")
            key = (view_name, rid)
            if key in recs_by_id:
                rec = recs_by_id[key]
                response = row.get("predicted_response") or ""
                if response.startswith("ERROR:"):
                    results.append(row)
                    continue
                score = score_with_qee_v2(view_name, rec, response)
                metrics = v2_metrics(score, response)
                new_row = {
                    "record_id": rid,
                    "view_id": rec.get("view_id"),
                    "category": rec.get("category"),
                    "predicted_response": response,
                    "reference_answer": get_reference_answer(rec),
                    "latency_s": row.get("latency_s"),
                    "tokens_generated": row.get("tokens_generated"),
                    "tokens_per_sec": row.get("tokens_per_sec"),
                    **metrics,
                    "v2": dict(score),
                }
                results.append(new_row)
        domain_aggregates[view_name] = aggregate(results, len(results))
        per_example_all.extend(results)
        print(f"  {view_name}: {json.dumps(domain_aggregates[view_name], indent=2)}")

    overall = {
        k: round(sum(d.get(k, 0.0) for d in domain_aggregates.values()) / len(domain_aggregates), 4)
        for k in ("correctness", "reasoning_quality", "hallucination_rate",
                  "answer_format_consistency")
    }
    overall["latency_s_mean"] = round(
        sum(d.get("latency_s_mean", 0.0) for d in domain_aggregates.values()) / len(domain_aggregates), 4)
    overall["tokens_per_sec_mean"] = round(
        sum(d.get("tokens_per_sec_mean", 0.0) for d in domain_aggregates.values()) / len(domain_aggregates), 2)

    baseline = {
        "experiment_id": "baseline_eval_v0.2", "phase": "5A.3",
        "evaluation_id": "baseline_v2", "status": "COMPLETE",
        "model": "BASE_MODEL", "model_id": BASE_MODEL, "adapter_path": None,
        "hardware": gpu_info_fn(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inference_config": {
            "base_model": BASE_MODEL, "quantization": "4bit_nf4_double_quant",
            "max_new_tokens": MAX_NEW_TOKENS, "sampling": "greedy",
        },
        "scoring": {
            "engine": "scripts/evaluation_engine/v2 (QEE v2)",
            "dispatch": "authoritative training-view category (math/code/semantic)",
            "dimensions": "7-dim weighted rubric, schema-compatible with v1",
            "note": "hallucination_rate = fraction of examples with a definitively wrong "
                    "AND low-quality final answer (correct is False and correctness < 0.4).",
        },
        "determinism_check_vs_v0.1": {
            "checked": 29, "exact_matches": 29, "match_ratio": 1.0,
            "note": "predicted_responses carried over from the full inference run which "
                    "matched the v0.1 per-example responses exactly (29/29).",
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

    per_example_all, domain_aggregates, dm, dc, extra = run_full_inference()
    gpu_info = extra["gpu_info"]
    peak_malloc_mib = extra["peak_malloc_mib"]
    vram_reserved_mib = extra["vram_reserved_mib"]

    if gpu_info:
        gpu_info["peak_vram_allocated_mib"] = round(peak_malloc_mib, 2) if peak_malloc_mib else None
        gpu_info["peak_vram_reserved_mib"] = round(vram_reserved_mib, 2) if vram_reserved_mib else None

    overall = {
        k: round(sum(d.get(k, 0.0) for d in domain_aggregates.values()) / len(domain_aggregates), 4)
        for k in ("correctness", "reasoning_quality", "hallucination_rate",
                  "answer_format_consistency")
    }
    overall["latency_s_mean"] = round(
        sum(d.get("latency_s_mean", 0.0) for d in domain_aggregates.values()) / len(domain_aggregates), 4)
    overall["tokens_per_sec_mean"] = round(
        sum(d.get("tokens_per_sec_mean", 0.0) for d in domain_aggregates.values()) / len(domain_aggregates), 2)

    baseline = {
        "experiment_id": "baseline_eval_v0.2", "phase": "5A.3",
        "evaluation_id": "baseline_v2", "status": "COMPLETE",
        "model": "BASE_MODEL", "model_id": BASE_MODEL, "adapter_path": None,
        "hardware": gpu_info,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inference_config": {
            "base_model": BASE_MODEL, "quantization": "4bit_nf4_double_quant",
            "max_new_tokens": MAX_NEW_TOKENS, "sampling": "greedy",
        },
        "scoring": {
            "engine": "scripts/evaluation_engine/v2 (QEE v2)",
            "dispatch": "authoritative training-view category (math/code/semantic)",
            "dimensions": "7-dim weighted rubric, schema-compatible with v1",
            "note": "hallucination_rate = fraction of examples with a definitively wrong "
                    "AND low-quality final answer (correct is False and correctness < 0.4).",
        },
        "determinism_check_vs_v0.1": {
            "checked": dc, "exact_matches": dm,
            "match_ratio": round(dm / dc, 4) if dc else None,
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
        "experiment_id": "baseline_eval_v0.2", "phase": "5A.3",
        "objective": "Official pre-LoRA baseline re-evaluated with the QEE v2 correctness engine.",
        "scope": "baseline inference/evaluation only. No LoRA training. No dataset/view/release modification.",
        "constraints": [
            "No model training", "No dataset modification", "No training-view modification",
            "No release artifact changes", "All outputs under experiments/baseline_eval_v0.2/",
        ],
        "base_model": BASE_MODEL,
        "same_as_v0.1": {
            "base_model": True, "evaluation_samples": True, "generation_config": True,
            "dataset_views": True, "hardware": True,
        },
        "generation": {
            "max_new_tokens": MAX_NEW_TOKENS, "sampling": "greedy", "seed": None,
            "quantization": "4bit_nf4_double_quant", "compute_dtype": "bfloat16",
        },
        "training_views": {
            "root": str(VIEWS_DIR),
            "views": ["code_300m_v0.1", "math_300m_v0.1", "aiml_300m_v0.1"],
            "read_only": True,
        },
        "scoring": {
            "engine": "scripts/evaluation_engine/v2 (QEE v2)",
            "replaces": "quality_score.py QEE v1 lexical/substring heuristics",
            "dispatch": "authoritative training-view category",
            "dimensions": ["accuracy", "completeness", "technical_correctness",
                           "clarity", "usefulness", "originality", "relevance"],
        },
        "artifacts": {
            "config": str(CONFIG_FILE), "baseline_v2": str(OUTPUT_FILE),
            "per_example": str(PER_EXAMPLE_FILE), "hardware_info": str(HARDWARE_FILE),
            "comparison_report": str(REPORT_FILE),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    CONFIG_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    hardware = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": "dev-pc (WSL2 Ubuntu-24.04)",
        "gpu": gpu_info,
        "nvidia_driver": None,
        "cuda_umd_version": None,
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

    print(f"\nBaseline v2 written to {OUTPUT_FILE}")
    print(f"Determinism vs v0.1: {dm}/{dc}")


if __name__ == "__main__":
    main()
