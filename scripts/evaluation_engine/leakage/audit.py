#!/usr/bin/env python3
"""audit.py — Protocol v2 L3 post-hoc audit.

Re-derives the reference-free prompt from a frozen eval record and verifies it
against the recorded per-example artifacts:

  * the recomputed ``prompt_sha256`` equals the recorded value (detects builder
    or data drift after the fact),
  * the recomputed ``canonical_answer_sha256`` equals the recorded value,
  * the reference-absence check passes on the re-derived prompt (L2 guard
    re-run).

Fail-closed: the audit exits non-zero if ANY record fails. It also verifies the
policy-lock block used to derive the prompt matches the recorded block, so a
policy change is surfaced rather than silently changing hashes.

Usage::

    python audit.py --per-example <per_example.jsonl> --eval-file <eval.jsonl> \
        --family math [--report <out.json>]

``per-example`` entries must carry ``record_id``, ``prompt_sha256``,
``canonical_answer_sha256`` and (optionally) ``policy_block_sha256``.

Deterministic, offline, stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow standalone execution: ``python scripts/evaluation_engine/leakage/audit.py``
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from evaluation_engine.leakage.prompts import (  # noqa: E402
        build_reference_free_prompt,
        canonical_answer_sha256,
        get_policy_lock,
        prompt_sha256,
    )
else:
    from .prompts import (
        build_reference_free_prompt,
        canonical_answer_sha256,
        get_policy_lock,
        prompt_sha256,
    )


def audit_record(record: dict, pex: dict, family: str) -> dict:
    """Audit one record against its recorded per-example artifact."""
    record_id = record.get("record_id", "unknown")
    errors: list[str] = []
    checks: dict[str, bool] = {}

    # Identity.
    same_id = pex.get("record_id") == record_id
    checks["record_id_match"] = same_id
    if not same_id:
        errors.append("per-example record_id does not match eval record")

    # Policy block identity (recompute with the family lock used by the audit).
    policy = get_policy_lock(family)
    policy_block_sha = policy.to_block()["policy_block_sha256"]
    recorded_policy = pex.get("policy_block_sha256")
    if isinstance(recorded_policy, str) and recorded_policy:
        checks["policy_block_match"] = recorded_policy == policy_block_sha
        if not checks["policy_block_match"]:
            errors.append(
                "recorded policy_block_sha256 differs from current family lock"
            )
    else:
        checks["policy_block_match"] = True  # not recorded; treated as unconstrained

    # canonical_answer_sha256 reproducible.
    recomputed_ref = canonical_answer_sha256(record)
    recorded_ref = pex.get("canonical_answer_sha256")
    checks["canonical_answer_sha256_reproducible"] = (
        isinstance(recorded_ref, str) and recorded_ref == recomputed_ref
    )
    if not checks["canonical_answer_sha256_reproducible"]:
        errors.append("canonical_answer_sha256 mismatch")

    # Re-derive prompt + verify recorded hash + reference absence.
    try:
        prompt = build_reference_free_prompt(record, policy)
        recomputed_prompt = prompt_sha256(prompt)
        recorded_prompt = pex.get("prompt_sha256")
        checks["prompt_sha256_reproducible"] = (
            isinstance(recorded_prompt, str) and recorded_prompt == recomputed_prompt
        )
        if not checks["prompt_sha256_reproducible"]:
            errors.append(
                f"prompt_sha256 mismatch (recorded={recorded_prompt!r} "
                f"recomputed={recomputed_prompt})"
            )
        # L2 guard re-run: build_reference_free_prompt already guards; an
        # absence re-check is recorded for the report.
        checks["reference_absence"] = True
    except Exception as exc:  # noqa: BLE001 - fail closed on any guard hit
        checks["prompt_sha256_reproducible"] = False
        checks["reference_absence"] = False
        errors.append(f"prompt re-derivation / guard failed: {exc}")

    verdict = "pass" if not errors else "fail"
    return {
        "record_id": record_id,
        "checks": checks,
        "errors": errors,
        "audit_verdict": verdict,
    }


def run_audit(per_example_file: str | Path, eval_file: str | Path,
              family: str, report_path: str | Path | None = None) -> dict:
    per_example = []
    with Path(per_example_file).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                per_example.append(json.loads(line))

    records = {}
    with Path(eval_file).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                records[r.get("record_id")] = r

    results = []
    for pex in per_example:
        rec = records.get(pex.get("record_id"))
        if rec is None:
            results.append({
                "record_id": pex.get("record_id"),
                "checks": {"eval_record_found": False},
                "errors": ["eval record not found in eval file"],
                "audit_verdict": "fail",
            })
        else:
            results.append(audit_record(rec, pex, family))

    passed = [r for r in results if r["audit_verdict"] == "pass"]
    failed = [r for r in results if r["audit_verdict"] == "fail"]
    report = {
        "layer": "L3",
        "audit_tool": "scripts/evaluation_engine/leakage/audit.py",
        "per_example_file": str(per_example_file),
        "eval_file": str(eval_file),
        "family": family,
        "n_records": len(results),
        "n_pass": len(passed),
        "n_fail": len(failed),
        "leak_pass_rate": len(passed) / len(results) if results else 0.0,
        "fail_closed": bool(results) and len(passed) == len(results),
        "policy_lock": get_policy_lock(family).to_block(),
        "records": results,
    }
    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Protocol v2 L3 post-hoc audit")
    ap.add_argument("--per-example", required=True,
                    help="per-example JSONL produced by a v2 validation/run")
    ap.add_argument("--eval-file", required=True, help="eval JSONL")
    ap.add_argument("--family", required=True,
                    choices=["math", "code", "semantic"])
    ap.add_argument("--report", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    report = run_audit(args.per_example, args.eval_file, args.family,
                       report_path=args.report)
    print(
        f"[L3] {report['n_pass']}/{report['n_records']} pass, "
        f"leak_pass_rate={report['leak_pass_rate']:.4f}"
    )
    for r in report["records"]:
        if r["audit_verdict"] == "fail":
            print(f"  FAIL {r['record_id']}: {r['errors']}")
    if report["fail_closed"]:
        print("[L3] audit PASSED (fail-closed: no leakage / drift)")
        return 0
    print("[L3] audit FAILED (fail-closed)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
