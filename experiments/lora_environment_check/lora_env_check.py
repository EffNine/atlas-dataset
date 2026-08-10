#!/usr/bin/env python3
"""
lora_env_check.py - Phase 5B.0 QLoRA Training Environment Validation.

Validates the RTX 5070 CUDA environment for a future QLoRA LoRA pilot WITHOUT
starting real training. Checks:

  1. Environment facts (CUDA, torch, bitsandbytes, peft, trl, accelerate,
     transformers, driver).
  2. Loads Qwen/Qwen2.5-7B-Instruct with NF4 4-bit + double quant + bf16
     compute.
  3. Attaches a minimal LoRA adapter (r=8, alpha=16) to the same target modules
     planned for the pilot.
  4. Validates a forward pass, a backward pass, a single gradient step on LoRA
     params, and adapter save/load round-trip.
  5. Records peak VRAM.

Writes config.json, environment_report.json, and test logs under
experiments/lora_environment_check/. No dataset / training-view / release
changes. No full QLoRA training.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch

EXPERIMENT = Path("/mnt/d/atlas-dataset/experiments/lora_environment_check")
LOGS = EXPERIMENT / "test_logs"
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj",
                  "gate_proj", "up_proj", "down_proj"]


def version_of(name: str) -> str:
    try:
        import importlib.metadata as im
        return im.version(name)
    except Exception:
        return "NOT INSTALLED"


def main() -> None:
    EXPERIMENT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    log_file = LOGS / "lora_env_check.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("lora_env_check")
    log.info("=== Phase 5B.0 QLoRA environment validation ===")

    report: dict = {
        "experiment_id": "lora_environment_check",
        "phase": "5B.0",
        "status": "RUNNING",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "env_facts": {},
        "safe_imports": [],
        "model": {"base_model": BASE_MODEL},
        "quantization": {"load_in_4bit": True, "double_quant": True,
                         "quant_type": "nf4", "compute_dtype": "bfloat16"},
        "lora": {},
        "validation_results": {},
        "peak_vram_mib": None,
        "issues": [],
    }

    # ---- 1. environment facts ----
    log.info("--- 1. environment facts ---")
    facts = report["env_facts"]
    facts["torch"] = {
        "version": torch.__version__,
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_runtime": torch.version.cuda,
        "cudnn_version": torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else None,
    }
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        facts["cuda_device"] = {
            "name": props.name,
            "capability": list(torch.cuda.get_device_capability(0)),
            "vram_total_mib": round(props.total_memory / 1024 ** 2, 2),
            "multiprocessor_count": props.multi_processor_count,
        }
    facts["packages"] = {
        "python": sys.version.split()[0],
        "transformers": version_of("transformers"),
        "peft": version_of("peft"),
        "trl": version_of("trl"),
        "bitsandbytes": version_of("bitsandbytes"),
        "accelerate": version_of("accelerate"),
        "datasets": version_of("datasets"),
        "numpy": version_of("numpy"),
    }
    try:
        drv = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip().splitlines()
        facts["nvidia_driver"] = drv[0] if drv else None
        nvsmi = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=15).stdout
        m = re.search(r"CUDA UMD Version:\s*([0-9.]+)", nvsmi)
        facts["cuda_umd_version"] = m.group(1) if m else None
    except Exception as e:
        facts["nvidia_probe_error"] = str(e)
    log.info(json.dumps(facts, indent=2))

    # ---- 2. safe import checks ----
    log.info("--- 2. safe import checks ---")
    checks = []

    def chk(component: str, src: str) -> dict:
        try:
            exec(src, {})
            return {"component": component, "status": "OK", "detail": ""}
        except Exception as e:
            return {"component": component, "status": "FAIL",
                    "detail": f"{type(e).__name__}: {e}"}

    checks.append(chk("transformers", "from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig"))
    checks.append(chk("peft", "from peft import LoraConfig, get_peft_model, PeftModel"))
    checks.append(chk("trl", "from trl import SFTConfig, SFTTrainer"))
    checks.append(chk("bitsandbytes", "import bitsandbytes; from bitsandbytes.nn import Linear4bit"))
    checks.append(chk("accelerate", "from accelerate import Accelerator, init_empty_weights"))
    checks.append({
        "component": "torch.cuda",
        "status": "OK" if torch.cuda.is_available() else "FAIL",
        "detail": str(torch.cuda.get_device_name(0)) if torch.cuda.is_available() else "cuda not available",
    })
    report["safe_imports"] = checks
    for c in checks:
        log.info("  %s: %s %s", c["component"], c["status"], c["detail"])

    # ---- 3. load base model with NF4 double-quant + bf16 ----
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, PeftModel

    log.info("--- 3. loading %s (NF4 double-quant, bf16) ---", BASE_MODEL)
    try:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, use_fast=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=False,
        )
        model.eval()
        report["quantization"]["loaded_ok"] = True
        report["model"]["dtype"] = str(model.dtype)
        report["model"]["device_map"] = getattr(model, "hf_device_map",
                                                getattr(model, "device_map", None))
        log.info("  model loaded: dtype=%s device_map=%s",
                 model.dtype, report["model"]["device_map"])
    except Exception as e:
        report["quantization"]["loaded_ok"] = False
        report["issues"].append({"step": "model_load", "error": f"{type(e).__name__}: {e}"})
        log.error("  model load failed: %s", e)
        raise

    # ---- 4. attach minimal LoRA ----
    log.info("--- 4. attaching minimal LoRA adapter ---")
    try:
        lora_config = LoraConfig(
            r=8, lora_alpha=16, lora_dropout=0.05, bias="none",
            task_type="CAUSAL_LM", target_modules=TARGET_MODULES,
        )
        report["lora"]["config"] = {
            "r": 8, "lora_alpha": 16, "lora_dropout": 0.05,
            "bias": "none", "task_type": "CAUSAL_LM", "target_modules": TARGET_MODULES,
        }
        model = get_peft_model(model, lora_config)
        trainable, total = model.get_nb_trainable_parameters()
        report["lora"]["trainable_params"] = int(trainable)
        report["lora"]["total_params"] = int(total)
        report["lora"]["trainable_pct"] = round(100.0 * trainable / total, 4)
        report["lora"]["attached_ok"] = True
        log.info("  LoRA attached: %s trainable / %s total (%.2f%%)",
                 f"{trainable:,}", f"{total:,}", report["lora"]["trainable_pct"])
    except Exception as e:
        report["lora"]["attached_ok"] = False
        report["issues"].append({"step": "lora_attach", "error": f"{type(e).__name__}: {e}"})
        log.error("  lora attach failed: %s", e)
        raise

    # ---- 5. validation: forward / backward / grad step / save-load ----
    vr = report["validation_results"]

    log.info("--- 5a. forward pass (no_grad) ---")
    try:
        prompt = "Solve for x: 2x + 5 = 11."
        inputs = tokenizer(prompt, return_tensors="pt").to("cuda")
        with torch.no_grad():
            out = model(**inputs)
        vr["forward_pass"] = {"status": "OK",
                              "logits_shape": list(out.logits.shape),
                              "loss_proxy": round(float(out.logits.float().mean()), 6)}
        log.info("  forward OK: %s", list(out.logits.shape))
    except Exception as e:
        vr["forward_pass"] = {"status": "FAIL", "error": f"{type(e).__name__}: {e}"}
        report["issues"].append({"step": "forward", "error": str(e)})
        log.error("  forward failed: %s", e)
        raise

    log.info("--- 5b. backward pass (train mode, LoRA-only grads) ---")
    try:
        model.train()
        full_text = "Solve for x: 2x + 5 = 11.\nAnswer: x = 3."
        enc = tokenizer(full_text, return_tensors="pt").to("cuda")
        input_ids, attention_mask = enc["input_ids"], enc["attention_mask"]
        labels = input_ids.clone()
        loss = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels).loss
        loss.backward()
        vr["backward_pass"] = {"status": "OK", "loss": round(float(loss), 6)}
        log.info("  backward OK: loss=%.6f", float(loss))
    except Exception as e:
        vr["backward_pass"] = {"status": "FAIL", "error": f"{type(e).__name__}: {e}"}
        report["issues"].append({"step": "backward", "error": f"{type(e).__name__}: {e}"})
        log.error("  backward failed: %s", e)
        raise

    log.info("--- 5c. gradient step on LoRA params ---")
    try:
        pre = {n: p.detach().clone() for n, p in model.named_parameters()
               if p.requires_grad and "lora" in n}
        opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=2e-4)
        opt.step()
        opt.zero_grad()
        changed = sum(1 for n, p in model.named_parameters()
                      if p.requires_grad and "lora" in n and not torch.equal(pre[n], p))
        vr["gradient_step"] = {"status": "OK" if changed > 0 else "FAIL",
                               "changed_lora_params": changed}
        if changed == 0:
            report["issues"].append({"step": "gradient_step", "error": "no LoRA params changed"})
        log.info("  gradient step OK: %d LoRA params changed", changed)
    except Exception as e:
        vr["gradient_step"] = {"status": "FAIL", "error": f"{type(e).__name__}: {e}"}
        report["issues"].append({"step": "gradient_step", "error": f"{type(e).__name__}: {e}"})
        log.error("  gradient step failed: %s", e)
        raise

    log.info("--- 5d. adapter save / reload round-trip ---")
    adapter_dir = LOGS / "adapter_mini"
    try:
        model.save_pretrained(str(adapter_dir))
        files = sorted(p.name for p in adapter_dir.iterdir())
        log.info("  adapter saved: %s", files)
        # Free the trained model so the fresh base + adapter fits in 12GB.
        del model, tokenizer
        torch.cuda.empty_cache()
        log.info("  freed trained model, reloading base + adapter")
        tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, use_fast=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        model_fresh = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL, quantization_config=bnb_config, device_map="auto",
            trust_remote_code=False)
        model_fresh.eval()
        model_loaded = PeftModel.from_pretrained(model_fresh, adapter_dir)
        model_loaded.eval()
        vr["adapter_save_load"] = {"status": "OK",
                                   "path": str(adapter_dir),
                                   "files": files}
        log.info("  adapter reload OK: %s", files)
        del model_fresh, model_loaded
        torch.cuda.empty_cache()
    except Exception as e:
        vr["adapter_save_load"] = {"status": "FAIL", "error": f"{type(e).__name__}: {e}"}
        report["issues"].append({"step": "adapter_save_load", "error": f"{type(e).__name__}: {e}"})
        log.error("  adapter save/load failed: %s", e)
        raise

    # ---- 6. VRAM + verdict ----
    peak = torch.cuda.max_memory_allocated() / 1024 ** 2
    reserved = torch.cuda.memory_reserved() / 1024 ** 2
    report["peak_vram_mib"] = {"peak_allocated": round(peak, 1),
                               "peak_reserved": round(reserved, 1)}
    ok = (not report["issues"]) and all(
        v.get("status") == "OK" for v in report["validation_results"].values())
    report["verdict"] = "GO" if ok else "HOLD"
    report["status"] = "COMPLETE"

    (EXPERIMENT / "environment_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    config = {
        "experiment_id": "lora_environment_check",
        "phase": "5B.0",
        "objective": "Validate the RTX 5070 CUDA environment for a future QLoRA LoRA pilot.",
        "scope": "environment validation only. No full QLoRA training, no dataset/view/release changes.",
        "constraints": ["No full training", "No dataset modification",
                        "No training-view modification", "No release artifact changes",
                        "All outputs under experiments/lora_environment_check/"],
        "base_model": BASE_MODEL,
        "quantization": {
            "load_in_4bit": True, "bnb_4bit_use_double_quant": True,
            "bnb_4bit_quant_type": "nf4", "bnb_4bit_compute_dtype": "bfloat16",
        },
        "lora_check": {
            "r": 8, "lora_alpha": 16, "lora_dropout": 0.05, "bias": "none",
            "task_type": "CAUSAL_LM", "target_modules": TARGET_MODULES,
            "lr_probe": 2e-4, "optimizer_probe": "AdamW (LoRA params only)",
        },
        "validation": ["forward_pass", "backward_pass", "gradient_step", "adapter_save_load"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (EXPERIMENT / "config.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    log.info("=== DONE verdict=%s ===", report["verdict"])
    print(json.dumps({k: report[k] for k in [
        "status", "verdict", "env_facts", "lora", "validation_results",
        "peak_vram_mib", "issues", "safe_imports"]}, indent=2))


if __name__ == "__main__":
    main()
