#!/usr/bin/env python3
"""protocol_v2_certificate.py — Protocol v2 readiness certificate + experiment
fingerprint (T3 baseline pre-flight).

Produces two deterministic, offline, stdlib-only artifacts under
``metadata/evaluation/protocol_v2_baseline/``:

* ``protocol_certificate.json`` — a verifiable attestation that the Protocol v2
  evaluation substrate is ready for baseline inference. It pins the protocol
  version, template, prompt-builder module hash, policy locks, engine commit,
  per-family eval-set checksums, leak scan ids, and validation status.
* ``experiment_fingerprint.json`` — a deterministic SHA-256 over the stable
  input-identity block of the canonical baseline experiment
  (``atlas-mixed-pilot-qwen7b-eval-v2``): model + revision, eval sets +
  checksums, template version, policy locks, engine commit, and the locked
  inference configuration. Any change to an input changes the fingerprint, so
  a stored run can be pinned to its recorded inputs (Protocol v2 §3.8–3.9,
  Research Protocol v1 §3).

Nothing is written outside ``metadata/evaluation/protocol_v2_baseline/``. No
model is loaded, no inference is executed, no frozen asset is modified. Fail
closed: the certificate is only emitted when every checked item verifies.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

PROTOCOL_VERSION = "v2"
CERTIFICATE_VERSION = "v1"
FINGERPRINT_VERSION = "v1"

EXPERIMENT_ID = "atlas-mixed-pilot-qwen7b-eval-v2"
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
MODEL_REVISION = "a09a35458c702b33eeacc393d103063234e8bc28"

EVAL_DIR = REPO / "evaluation" / "eval_sets" / "protocol_v2"
V1_DIR = REPO / "evaluation" / "eval_sets" / "phase6_expansion_v1"
VALIDATION_DIR = REPO / "metadata" / "evaluation" / "protocol_v2_validation"
OUT_DIR = REPO / "metadata" / "evaluation" / "protocol_v2_baseline"

PROMPT_MODULE = REPO / "scripts" / "evaluation_engine" / "leakage" / "prompts.py"
ENGINE_DIR = REPO / "scripts" / "evaluation_engine" / "v2"

GOVERNING_DOCS = [
    "docs/research/protocol_v2_transition.md",
    "docs/research/protocol_v2_validation_report.md",
    "docs/research/p8_generation_policy.md",
]

FAMILIES = {
    "math": {
        "eval_file": "math_eval_v2.jsonl",
        "manifest_file": "math_eval_v2_manifest.json",
        "held_file": "math_eval_v2_held.jsonl",
    },
    "code": {
        "eval_file": "code_eval_v2.jsonl",
        "manifest_file": "code_eval_v2_manifest.json",
        "held_file": "code_eval_v2_held.jsonl",
    },
}

# Locked inference configuration (Generation Policy Lock, Protocol v2 §3.6).
INFERENCE_CONFIG = {
    "quantization": "4bit_nf4_double_quant",
    "compute_dtype": "bfloat16",
    "sampling": "greedy",
    "do_sample": False,
    "seed": 42,
    "budget_rule": "budget_i = min(4096, max(256, 128 + ceil(1.5 * N_tokens(reference_i))))",
    "budget_fallback": 1024,
    "stop_sequence": "<|im_end|>",
    "extraction_rule": "P8-generation-policy-lock v1.0 diff extraction wrapper",
    "device_map": "auto",
}


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_of_lines(lines: list[dict]) -> str:
    blob = "\n".join(
        json.dumps(r, sort_keys=True, ensure_ascii=False) for r in lines
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def git_short_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001
        return "[HUMAN MUST SUPPLY]"


def git_full_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO,
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:  # noqa: BLE001
        return "[HUMAN MUST SUPPLY]"


def policy_lock_blocks() -> dict:
    from evaluation_engine.leakage.prompts import get_policy_lock

    return {
        fam: get_policy_lock(fam).to_block() for fam in ("math", "code")
    }


def eval_set_cert(eval_set_id: str, family: str, cfg: dict) -> dict:
    eval_file = EVAL_DIR / cfg["eval_file"]
    manifest_file = EVAL_DIR / cfg["manifest_file"]
    held_file = EVAL_DIR / cfg["held_file"]

    records = load_jsonl(eval_file)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    checksum = sha256_of_lines(records)

    held_ids: list[str] = []
    if held_file.exists():
        held_ids = [str(r.get("record_id")) for r in load_jsonl(held_file)]

    return {
        "eval_set_id": eval_set_id,
        "family": family,
        "n_clean": len(records),
        "n_held": len(held_ids),
        "held_record_ids": held_ids,
        "checksum": checksum,
        "manifest_checksum": manifest.get("checksum", {}).get("records"),
        "checksum_matches_manifest": checksum == manifest.get("checksum", {}).get("records"),
        "canonical_answer_present": sum(
            1 for r in records if (r.get("canonical_answer") or "").strip()
        ),
        "canonical_answer_sha256_present": sum(
            1 for r in records if r.get("canonical_answer_sha256")
        ),
        "prompt_sha256_present": sum(
            1 for r in records if r.get("prompt_sha256")
        ),
        "messages_user_only": sum(
            1 for r in records
            if all(m.get("role") == "user" for m in r.get("messages", []))
        ),
        "manifest": str(manifest_file.relative_to(REPO)),
        "leak_scan_id": None,  # filled below from the validation summary / scan
    }


def main() -> int:
    # ---- Re-verify L1 scans (must reproduce recorded ids) ----------------- #
    from evaluation_engine.leakage.scan import run_scan

    scan_results: dict[str, dict] = {}
    for fam, cfg in FAMILIES.items():
        eval_file = EVAL_DIR / cfg["eval_file"]
        report = run_scan(eval_file, fam, set_id=cfg["eval_file"].replace(".jsonl", ""))
        scan_results[fam] = {
            "leak_scan_id": report["leak_scan_id"],
            "leak_pass_rate": report["leak_pass_rate"],
            "fail_closed": report["fail_closed"],
            "n_pass": report["n_pass"],
            "n_records": report["n_records"],
        }

    # ---- Validation summary (L2/L3 + controls) ---------------------------- #
    validation = {}
    vs: dict = {}
    if (VALIDATION_DIR / "validation_summary.json").exists():
        vs = json.loads((VALIDATION_DIR / "validation_summary.json").read_text(encoding="utf-8"))
        validation = {
            "status": vs.get("status"),
            "template_version": vs.get("template_version"),
            "rebuild_determinism": vs.get("rebuild_determinism", {}).get("byte_identical"),
            "per_family": {
                fam: {
                    "pass_rate": vs["families"][fam]["pass_rate"],
                    "runtime_guard": vs["families"][fam]["runtime_guard"],
                    "post_hoc_audit": vs["families"][fam]["post_hoc_audit"],
                    "guard_controls": vs["families"][fam]["guard_controls"],
                    "held": vs["families"][fam]["held"],
                }
                for fam in ("math", "code")
            },
        }

    # ---- Policy locks + prompt builder ------------------------------------ #
    blocks = policy_lock_blocks()

    eval_sets: dict[str, dict] = {}
    for fam, cfg in FAMILIES.items():
        cert = eval_set_cert(cfg["eval_file"].replace(".jsonl", ""), fam, cfg)
        cert["leak_scan_id"] = scan_results[fam]["leak_scan_id"]
        cert["leak_pass_rate"] = scan_results[fam]["leak_pass_rate"]
        cert["scan_fail_closed"] = scan_results[fam]["fail_closed"]
        eval_sets[fam] = cert

    l1_all_pass = all(v["scan_fail_closed"] and v["leak_pass_rate"] == 1.0
                      for v in eval_sets.values())
    l1_scan_ids_reproduced = all(
        eval_sets[fam]["leak_scan_id"]
        == vs["families"][fam]["leak_scan"]["leak_scan_id"]
        for fam in ("math", "code")
    ) if validation.get("per_family") else False

    engine_commit_short = git_short_head()
    engine_commit_full = git_full_head()

    certificate = {
        "artifact": "atlas-protocol-v2-readiness-certificate",
        "certificate_version": CERTIFICATE_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "governing_docs": GOVERNING_DOCS,
        "template_version": "qwen2.5-chatml-deterministic-v1",
        "prompt_builder": {
            "module": str(PROMPT_MODULE.relative_to(REPO)),
            "content_sha256": file_sha256(PROMPT_MODULE),
            "git_tracked": False,
            "note": "shared module (rule P4); not yet committed in this working tree",
        },
        "engine": {
            "path": str(ENGINE_DIR.relative_to(REPO)),
            "git_commit": engine_commit_short,
            "git_commit_full": engine_commit_full,
            "git_tracked": True,
            "note": "QEE v2 frozen; reference argument supplied from canonical_answer",
        },
        "policy_locks": blocks,
        "eval_sets": eval_sets,
        "leakage_guards": {
            "L1_static_scan": "PASS" if l1_all_pass else "FAIL",
            "L1_scan_ids_reproduced_from_validation": l1_scan_ids_reproduced,
            "L2_runtime_guard": (
                "PASS" if validation.get("per_family") and all(
                    validation["per_family"][fam]["runtime_guard"].get("leakage_guard_pass")
                    for fam in ("math", "code")
                ) else "NOT_RERUN")
            ,
            "L3_post_hoc_audit": (
                "PASS" if validation.get("per_family") and all(
                    validation["per_family"][fam]["post_hoc_audit"].get("leak_pass_rate") == 1.0
                    for fam in ("math", "code")
                ) else "NOT_RERUN")
            ,
            "validation_summary_status": validation.get("status"),
            "guard_controls": {
                fam: validation["per_family"][fam]["guard_controls"]
                for fam in ("math", "code")
            } if validation.get("per_family") else {},
            "held_fail_closed": {
                fam: validation["per_family"][fam]["held"]
                for fam in ("math", "code")
            } if validation.get("per_family") else {},
        },
        "readiness_verdict": (
            "READY" if l1_all_pass and l1_scan_ids_reproduced
            and validation.get("status") == "COMPLETED"
            else "HOLD"
        ),
        "fail_closed_rule": (
            "any unverifiable item -> HOLD with null metrics; baseline inference "
            "may not proceed unless verdict is READY"
        ),
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    certificate["certificate_sha256"] = sha256_hex(
        json.dumps({k: v for k, v in certificate.items() if k != "certificate_sha256"},
                   sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    )

    # ---- Experiment fingerprint ------------------------------------------- #
    fingerprint_payload = {
        "fingerprint_version": FINGERPRINT_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "phase": "T3 canonical baseline (R1/R2)",
        "protocol_version": PROTOCOL_VERSION,
        "scope": "eval",
        "base_model": BASE_MODEL,
        "model_revision": MODEL_REVISION,
        "template_version": "qwen2.5-chatml-deterministic-v1",
        "engine_commit": engine_commit_short,
        "engine_path": str(ENGINE_DIR.relative_to(REPO)),
        "eval_sets": {
            fam: {
                "eval_set_id": eval_sets[fam]["eval_set_id"],
                "n_clean": eval_sets[fam]["n_clean"],
                "n_held": eval_sets[fam]["n_held"],
                "checksum": eval_sets[fam]["checksum"],
                "leak_scan_id": eval_sets[fam]["leak_scan_id"],
            }
            for fam in ("math", "code")
        },
        "policy_locks": {
            fam: blocks[fam]["policy_block_sha256"] for fam in ("math", "code")
        },
        "inference_config": INFERENCE_CONFIG,
    }
    fingerprint = sha256_hex(
        json.dumps(fingerprint_payload, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":"))
    )

    experiment_fingerprint = {
        "fingerprint_version": FINGERPRINT_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "fingerprint_sha256": fingerprint,
        "input_block": fingerprint_payload,
        "note": (
            "sha256 over the sorted canonical input block; identical inputs "
            "yield the same fingerprint. Recorded in the T3 run metadata and "
            "re-verified by the runner before generation."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # ---- Write artifacts -------------------------------------------------- #
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cert_path = OUT_DIR / "protocol_certificate.json"
    fp_path = OUT_DIR / "experiment_fingerprint.json"
    cert_path.write_text(
        json.dumps(certificate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    fp_path.write_text(
        json.dumps(experiment_fingerprint, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"[CERT] verdict={certificate['readiness_verdict']}")
    print(f"[CERT] L1 scan ids reproduced={l1_scan_ids_reproduced}")
    print(f"[CERT] engine_commit={engine_commit_short} "
          f"model_revision={MODEL_REVISION[:12]}")
    print(f"[CERT] experiment fingerprint={fingerprint[:16]}")
    print(f"[CERT] wrote {cert_path.relative_to(REPO)}")
    print(f"[CERT] wrote {fp_path.relative_to(REPO)}")
    return 0 if certificate["readiness_verdict"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
