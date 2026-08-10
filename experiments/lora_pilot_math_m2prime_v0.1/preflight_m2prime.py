#!/usr/bin/env python3
"""
preflight_m2prime.py — Sprint 5B.7 Pre-Flight Verification

Verifies all pre-flight conditions before M2' training execution.
Run this BEFORE training to ensure all gates pass.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
EXPERIMENT = REPO / "experiments" / "lora_pilot_math_m2prime_v0.1"
MANIFEST = EXPERIMENT / "m2prime_manifest.json"
STAGED = EXPERIMENT / "staged_train.jsonl"
M1_EXP = REPO / "experiments" / "lora_pilot_math_v0.1"
EVAL_V2_DIR = REPO / "evaluation" / "eval_sets" / "protocol_v2"
CERT_DIR = REPO / "metadata" / "evaluation" / "protocol_v2_baseline"
OUT_DIR = EXPERIMENT / "evaluation"

APPROVED_SHA = "7dfa81114f4096286415a672830f6ff334cc95066080fd9f5267e86d0e413dda"
EXPECTED_RECORDS = 118

FAILURES = []


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return None


def check(name: str, condition: bool, detail: str = ""):
    status = "PASS" if condition else "FAIL"
    marker = "✓" if condition else "✗"
    print(f"  [{marker}] {name}: {status}" + (f" — {detail}" if detail else ""))
    if not condition:
        FAILURES.append(name)
    return condition


def main():
    print("=== Sprint 5B.7 M2' Pre-Flight Verification ===\n")

    # 1. File existence
    print("[1] File existence")
    check("manifest exists", MANIFEST.exists(), str(MANIFEST))
    check("staged_train exists", STAGED.exists(), str(STAGED))
    check("M1 adapter exists", (M1_EXP / "checkpoints" / "adapter_config.json").exists(),
          "required for comparison eval")
    check("math_eval_v2 exists", (EVAL_V2_DIR / "math_eval_v2.jsonl").exists(),
          str(EVAL_V2_DIR / "math_eval_v2.jsonl"))

    # 2. Checksum verification
    print("\n[2] Checksum verification")
    actual_sha = sha256_file(STAGED) if STAGED.exists() else ""
    check("staged_train SHA-256", actual_sha == APPROVED_SHA,
          f"expected={APPROVED_SHA[:16]}..., got={actual_sha[:16]}..." if actual_sha else "file missing")

    # 3. Record count
    print("\n[3] Record count")
    n_records = sum(1 for _ in STAGED.open(encoding="utf-8") if _.strip()) if STAGED.exists() else 0
    check("record count = 118", n_records == EXPECTED_RECORDS, f"got {n_records}")

    # 4. Manifest integrity
    print("\n[4] Manifest integrity")
    if MANIFEST.exists():
        with MANIFEST.open(encoding="utf-8") as f:
            manifest = json.load(f)
        check("manifest n_records = 118", manifest.get("n_records") == 118,
              f"got {manifest.get('n_records')}")
        check("M1 ⊆ M2'", manifest.get("subset_verification", {}).get("m1_subset_of_m2prime"),
              "all 117 M1 records present in M2'")
        check("M2' only record = expert_math_000761",
              manifest.get("subset_verification", {}).get("m2prime_only_records") == ["expert_math_000761"])
        check("zero eval overlap", manifest.get("leakage_audit", {}).get("m2prime_eval_overlap_count") == 0)
        check("zero M1 eval overlap", manifest.get("leakage_audit", {}).get("m1_eval_overlap_count") == 0)
    else:
        check("manifest exists", False, "manifest file missing")

    # 5. Eval set integrity
    print("\n[5] Eval set integrity")
    eval_file = EVAL_V2_DIR / "math_eval_v2.jsonl"
    manifest_file = EVAL_V2_DIR / "math_eval_v2_manifest.json"
    cert_file = CERT_DIR / "protocol_certificate.json"

    check("math_eval_v2 exists", eval_file.exists(), str(eval_file))
    check("math_eval_v2_manifest exists", manifest_file.exists(), str(manifest_file))
    check("protocol_certificate exists", cert_file.exists(), str(cert_file))

    if eval_file.exists() and manifest_file.exists():
        eval_records = list(eval_file.open(encoding="utf-8"))
        eval_count = sum(1 for l in eval_records if l.strip())
        check("math_eval_v2 N=100", eval_count == 100, f"got {eval_count}")

        # Verify checksum matches certificate
        cert = json.loads(cert_file.read_text()) if cert_file.exists() else {}
        manifest = json.loads(manifest_file.read_text())
        expected_checksum = cert.get("eval_sets", {}).get("math", {}).get("checksum", "")
        actual_checksum = manifest.get("checksum", {}).get("records", "")
        check("checksum matches cert", actual_checksum == expected_checksum,
              f"expected={expected_checksum[:16]}..., got={actual_checksum[:16]}..." if actual_checksum else "")

        # Verify no M2' records in eval
        m2prime_ids = set()
        with STAGED.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    m2prime_ids.add(rec.get("record_id") or rec.get("id"))

        eval_ids = set()
        with eval_file.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    eval_ids.add(rec.get("record_id") or rec.get("id"))

        overlap = m2prime_ids & eval_ids
        check("M2' ∩ math_eval_v2 = ∅", len(overlap) == 0, f"overlap: {overlap}" if overlap else "")

    # 6. CUDA availability
    print("\n[6] Runtime environment")
    try:
        import torch
        cuda_ok = torch.cuda.is_available()
        check("CUDA available", cuda_ok,
              torch.cuda.get_device_name(0) if cuda_ok else "no GPU detected")
        if cuda_ok:
            p = torch.cuda.get_device_properties(0)
            check("RTX 5070 detected", "RTX 5070" in p.name, f"GPU: {p.name}")
    except ImportError:
        check("torch installed", False, "import torch failed")

    # Summary
    print("\n" + "=" * 50)
    if FAILURES:
        print(f"PRE-FLIGHT FAILED: {len(FAILURES)} check(s) failed")
        for f in FAILURES:
            print(f"  - {f}")
        print("\nABORT: Do not proceed with training until all checks pass.")
        return 1
    else:
        print("PRE-FLIGHT PASSED: All checks passed. Proceed with training.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
