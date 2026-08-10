#!/usr/bin/env python3
"""validate_protocol_v2.py — Protocol v2 validation suite (task 4).

Runs the full protocol validation for every eval_v2 record in each family:

  * reference-absence — the canonical answer never appears in the rendered
    reference-free prompt,
  * prompt-hash reproducibility — building the prompt twice (and re-deriving
    it during the L3 audit) yields the same ``prompt_sha256``,
  * leakage guard (L2) — ``guard_reference_free`` passes for 100% of records
    (fail-closed),
  * artifact reproducibility — ``canonical_answer_sha256`` reproducible from
    the stored value; eval-set content checksum matches the manifest; a full
    rebuild of the eval_v2 sets reproduces byte-identical files,
  * guard controls — a reconstructed v1-style leaked prompt MUST trip the
    guard (positive control) while the clean reference-free prompt passes
    (negative control).

Coordinated layers:
  L1  static scan   -> ``leakage/scan.py``   (per eval set),
  L2  runtime guard -> ``prompts.build_reference_free_prompt`` (every record),
  L3  post-hoc audit-> ``leakage/audit.py``  (re-derive + hash verification).

Writes validation artifacts under ``metadata/evaluation/protocol_v2_validation/``
and prints a pass/fail summary. Exits non-zero if anything fails (fail closed).
No model is loaded, no inference is executed, no QEE scoring is touched, and
no frozen asset is modified.

Usage::

    python validate_protocol_v2.py [--families math code]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

EVAL_DIR = REPO / "evaluation" / "eval_sets" / "protocol_v2"
V1_DIR = REPO / "evaluation" / "eval_sets" / "phase6_expansion_v1"
OUT_DIR = REPO / "metadata" / "evaluation" / "protocol_v2_validation"

VALIDATION_VERSION = "v1"

FAMILIES = {
    "math": {
        "eval_file": "math_eval_v2.jsonl",
        "manifest_file": "math_eval_v2_manifest.json",
        "v1_file": "math_eval_v1.jsonl",
    },
    "code": {
        "eval_file": "code_eval_v2.jsonl",
        "manifest_file": "code_eval_v2_manifest.json",
        "v1_file": "code_eval_v1.jsonl",
    },
}


def sha256_of_lines(lines: list[dict]) -> str:
    blob = "\n".join(
        json.dumps(r, sort_keys=True, ensure_ascii=False) for r in lines
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def build_leaked_prompt_v1(v1_record: dict, family: str) -> str:
    """Reconstruct the historical v1 leak: render the full ``messages`` array
    (which contains the assistant gold) with the ChatML template, then open the
    generation turn. The guard MUST trip on this (positive control)."""
    from evaluation_engine.leakage.prompts import get_policy_lock

    policy = get_policy_lock(family)
    msgs = v1_record.get("messages") or []
    parts = [f"<|im_start|>{m.get('role')}\n{m.get('content')}<|im_end|>\n"
             for m in msgs]
    if not parts:
        parts.append(f"<|im_start|>user\n{v1_record.get('problem')}<|im_end|>\n")
    return "".join(parts) + "<|im_start|>assistant\n"


def run_family_validation(family: str) -> dict:
    from evaluation_engine.leakage import (
        build_reference_free_prompt,
        get_policy_lock,
        prompt_sha256,
        guard_reference_free,
        ReferenceLeakError,
    )

    cfg = FAMILIES[family]
    eval_file = EVAL_DIR / cfg["eval_file"]
    manifest_file = EVAL_DIR / cfg["manifest_file"]
    v1_file = V1_DIR / cfg["v1_file"]

    records = load_jsonl(eval_file)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    eval_set_id = manifest.get("eval_set_id")
    policy = get_policy_lock(family)
    policy_block = policy.to_block()

    # --- Per-record validation ------------------------------------------- #
    per_example = []
    n_fail = 0
    leak_details: list[str] = []
    for rec in records:
        rid = rec.get("record_id", "unknown")
        checks = {}
        prompt_sha = None

        # L2 guard + reference-absence + prompt-hash reproducibility.
        try:
            prompt1 = build_reference_free_prompt(rec, policy)
            prompt2 = build_reference_free_prompt(rec, policy)
            h1, h2 = prompt_sha256(prompt1), prompt_sha256(prompt2)
            prompt_sha = h1
            checks["no_canonical_answer_in_prompt"] = True
            checks["prompt_hash_reproducible"] = h1 == h2
            checks["leakage_guard_pass"] = True
            if h1 != h2:
                raise RuntimeError("prompt_sha256 not reproducible")
        except Exception as exc:  # noqa: BLE001 - fail closed
            checks["no_canonical_answer_in_prompt"] = False
            checks["prompt_hash_reproducible"] = False
            checks["leakage_guard_pass"] = False
            leak_details.append(f"{rid}: {exc}")
            n_fail += 1

        # canonical_answer_sha256 reproducibility from the stored value.
        recomputed = hashlib.sha256(
            (rec.get("canonical_answer") or "").encode("utf-8")
        ).hexdigest()
        checks["canonical_answer_sha256_reproducible"] = (
            rec.get("canonical_answer_sha256") == recomputed
        )
        if not checks["canonical_answer_sha256_reproducible"]:
            n_fail += 1

        # messages reference-free.
        checks["messages_reference_free"] = all(
            m.get("role") == "user" for m in rec.get("messages", [])
        )
        if not checks["messages_reference_free"]:
            n_fail += 1

        verdict = "pass" if all(checks.values()) else "fail"
        per_example.append({
            "record_id": rid,
            "family": family,
            "eval_set_id": eval_set_id,
            "prompt_sha256": prompt_sha,
            "canonical_answer_sha256": recomputed,
            "policy_block_sha256": policy_block["policy_block_sha256"],
            "checks": checks,
            "verdict": verdict,
        })

    # --- L1 static scan --------------------------------------------------- #
    scan_report_path = OUT_DIR / f"leak_scan_{cfg['eval_file'].replace('.jsonl', '')}.json"
    from evaluation_engine.leakage.scan import run_scan as l1_scan

    scan_report = l1_scan(
        eval_file, family, set_id=eval_set_id,
        report_path=scan_report_path,
    )

    # --- L3 post-hoc audit ------------------------------------------------ #
    pex_file = OUT_DIR / f"per_example_{cfg['eval_file'].replace('.jsonl', '')}.jsonl"
    write_jsonl(pex_file, per_example)
    from evaluation_engine.leakage.audit import run_audit as l3_audit

    audit_report_path = OUT_DIR / f"audit_{cfg['eval_file'].replace('.jsonl', '')}.json"
    audit_report = l3_audit(pex_file, eval_file, family, report_path=audit_report_path)

    # --- Guard controls ---------------------------------------------------- #
    v1_records = load_jsonl(v1_file)
    sample = v1_records[:3]
    controls = {"leaked_positive_control": {}, "clean_negative_control": {}}
    for rec in sample:
        rid = rec.get("record_id") or "unknown"
        leaked = build_leaked_prompt_v1(rec, family)
        try:
            guard_reference_free(
                leaked, rec.get("solution") or rec.get("canonical_answer") or "",
                rid)
            controls["leaked_positive_control"][rid] = False  # guard must trip
        except ReferenceLeakError:
            controls["leaked_positive_control"][rid] = True
        # Negative control: clean reference-free prompt passes.
        try:
            v2rec = next(r for r in records if r["record_id"] == rid)
            build_reference_free_prompt(v2rec, policy)
            controls["clean_negative_control"][rid] = True
        except ReferenceLeakError:
            controls["clean_negative_control"][rid] = False

    # --- Held records (fail-closed holds from build-time guard) ------------- #
    held_file = EVAL_DIR / cfg["eval_file"].replace(".jsonl", "_held.jsonl")
    held_info = {
        "n_held": 0,
        "record_ids": [],
        "reasons": [],
        "guard_confirmed_hold": True,
    }
    if held_file.exists():
        held_records = load_jsonl(held_file)
        held_info["n_held"] = len(held_records)
        held_info["record_ids"] = [r.get("record_id") for r in held_records]
        held_info["reasons"] = [
            (r.get("protocol_v2") or {}).get("leak_guard_reason")
            for r in held_records
        ]
        # Confirm each held record actually trips the runtime guard.
        for r in held_records:
            try:
                build_reference_free_prompt(r, policy)
                held_info["guard_confirmed_hold"] = False
            except ReferenceLeakError:
                pass

    # --- Artifact reproducibility ------------------------------------------ #
    content_checksum = sha256_of_lines(records)
    checksum_matches_manifest = (
        content_checksum == manifest.get("checksum", {}).get("records")
    )

    n_pass = len(per_example) - n_fail
    return {
        "family": family,
        "eval_set_id": eval_set_id,
        "n_records": len(records),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "pass_rate": (n_pass / len(records)) if records else 0.0,
        "leak_scan": {
            "leak_scan_id": scan_report["leak_scan_id"],
            "leak_pass_rate": scan_report["leak_pass_rate"],
            "fail_closed": scan_report["fail_closed"],
        },
        "runtime_guard": {
            "leakage_guard_pass": all(p["checks"]["leakage_guard_pass"]
                                      for p in per_example),
            "no_canonical_answer_in_prompt": all(
                p["checks"]["no_canonical_answer_in_prompt"] for p in per_example),
        },
        "post_hoc_audit": {
            "leak_pass_rate": audit_report["leak_pass_rate"],
            "fail_closed": audit_report["fail_closed"],
        },
        "prompt_hash_reproducible": all(
            p["checks"]["prompt_hash_reproducible"] for p in per_example),
        "guard_controls": controls,
        "held": held_info,
        "artifact_reproducibility": {
            "content_checksum_matches_manifest": checksum_matches_manifest,
            "content_checksum": content_checksum,
            "manifest_checksum": manifest.get("checksum", {}).get("records"),
        },
        "files": {
            "per_example": str(pex_file.relative_to(REPO)),
            "leak_scan": str(scan_report_path.relative_to(REPO)),
            "audit": str(audit_report_path.relative_to(REPO)),
        },
        "leak_details": leak_details,
    }


def check_rebuild_determinism() -> dict:
    """Re-run the eval_v2 builder and verify raw-file hashes are unchanged."""
    before = {}
    for p in sorted(EVAL_DIR.glob("*.jsonl")):
        before[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "evaluation_engine" / "build_eval_v2.py")],
        capture_output=True, text=True,
    )
    after = {}
    for p in sorted(EVAL_DIR.glob("*.jsonl")):
        after[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    same = before == after and proc.returncode == 0
    return {
        "rebuild_exit_code": proc.returncode,
        "byte_identical": same,
        "files": sorted(before),
        "stderr_tail": (proc.stderr or "").strip().splitlines()[-3:],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Protocol v2 validation suite")
    ap.add_argument("--families", nargs="*", default=["math", "code"],
                    choices=["math", "code"])
    args = ap.parse_args(argv)

    from evaluation_engine.leakage.prompts import TEMPLATE_VERSION

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    for fam in args.families:
        results[fam] = run_family_validation(fam)
        r = results[fam]
        print(
            f"[VALIDATE {fam}] records={r['n_records']} pass={r['n_pass']} "
            f"fail={r['n_fail']} pass_rate={r['pass_rate']:.4f} "
            f"L1_scan_id={r['leak_scan']['leak_scan_id'][:16]}"
        )
        if r["n_fail"]:
            for d in r["leak_details"]:
                print(f"   FAIL {d}")
        ctrl = r["guard_controls"]
        print(f"   guard controls: leaked-trips={list(ctrl['leaked_positive_control'].values())} "
              f"clean-passes={list(ctrl['clean_negative_control'].values())}")
        if r["held"]["n_held"]:
            print(f"   held (fail-closed): {r['held']['record_ids']} "
                  f"guard_confirmed={r['held']['guard_confirmed_hold']}")

    rebuild = check_rebuild_determinism()
    print(f"[VALIDATE] rebuild determinism: byte_identical={rebuild['byte_identical']} "
          f"exit={rebuild['rebuild_exit_code']}")

    all_pass = (
        all(r["pass_rate"] == 1.0 for r in results.values())
        and all(r["leak_scan"]["fail_closed"] for r in results.values())
        and all(r["post_hoc_audit"]["fail_closed"] for r in results.values())
        and all(r["prompt_hash_reproducible"] for r in results.values())
        and all(
            all(v for v in r["guard_controls"]["leaked_positive_control"].values())
            and all(v for v in r["guard_controls"]["clean_negative_control"].values())
            for r in results.values()
        )
        and all(r["held"]["guard_confirmed_hold"] for r in results.values())
        and all(r["artifact_reproducibility"]["content_checksum_matches_manifest"]
                for r in results.values())
        and rebuild["byte_identical"]
    )

    summary = {
        "validation_version": VALIDATION_VERSION,
        "template_version": TEMPLATE_VERSION,
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "families": results,
        "rebuild_determinism": rebuild,
        "overall_pass": all_pass,
        "status": "COMPLETED" if all_pass else "FAILED",
    }
    summary_path = OUT_DIR / "validation_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {summary_path.relative_to(REPO)}")
    print(f"[VALIDATE] overall: {'PASS' if all_pass else 'FAIL'} "
          f"({summary['status']})")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
