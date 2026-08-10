#!/usr/bin/env python3
"""scan.py — Protocol v2 L1 static schema scan (pre-flight, per eval set).

Verifies, for every record in an eval set:
  * ``canonical_answer`` present and non-empty,
  * ``canonical_answer_sha256`` reproducible from the stored value,
  * ``problem`` present and non-empty,
  * the reference-free prompt (``problem`` only + policy system message) does
    NOT contain the canonical answer (reference-absence),
  * the ``messages`` array contains no reference answer (user-only continuity),
  * ``prompt_sha256`` / ``prompt_fingerprint`` recorded for L3 re-audit.

Fail-closed: the scan exits non-zero if ANY record fails. It produces a
``leak_scan_id`` recorded in run metadata, and a JSON report.

Usage::

    python scan.py --eval-file <eval.jsonl> --family math \
        --report <out.json> [--set-id <id>]

Deterministic, offline, stdlib-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Allow standalone execution: ``python scripts/evaluation_engine/leakage/scan.py``
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from evaluation_engine.leakage.prompts import (  # noqa: E402
        build_reference_free_prompt,
        canonical_answer_sha256,
        collapse_whitespace,
        get_policy_lock,
        prompt_fingerprint,
        prompt_sha256,
    )
else:
    from .prompts import (
        build_reference_free_prompt,
        canonical_answer_sha256,
        collapse_whitespace,
        get_policy_lock,
        prompt_fingerprint,
        prompt_sha256,
    )


def _messages_contain_reference(record: dict, reference: str) -> list[str]:
    """Return a list of leak descriptions if the messages array carries any
    reference-derived content; empty list means clean."""
    problems: list[str] = []
    for m in record.get("messages", []):
        role = m.get("role")
        content = m.get("content") or ""
        if role == "assistant" and content.strip():
            problems.append(f"messages contains assistant turn with content")
        norm_c = collapse_whitespace(content)
        norm_r = collapse_whitespace(reference or "")
        if norm_r and norm_r in norm_c:
            problems.append("messages contains full canonical_answer")
        elif norm_r and len(norm_r) > 60 and norm_r[:60] in norm_c:
            problems.append("messages contains canonical_answer fingerprint")
    return problems


def scan_record(record: dict, family: str) -> dict:
    """Run all L1 checks for one record and return a verdict dict."""
    record_id = record.get("record_id", "unknown")
    reference = record.get("canonical_answer")
    problem = record.get("problem")

    checks: dict[str, bool] = {}
    errors: list[str] = []

    # 1. canonical_answer present / non-empty.
    has_ref = isinstance(reference, str) and bool(reference.strip())
    checks["has_canonical_answer"] = has_ref
    if not has_ref:
        errors.append("missing or empty canonical_answer")

    # 2. canonical_answer_sha256 reproducible.
    if has_ref:
        recorded = record.get("canonical_answer_sha256")
        recomputed = canonical_answer_sha256(record)
        ok = isinstance(recorded, str) and recorded == recomputed
        checks["canonical_answer_sha256_reproducible"] = ok
        if not ok:
            errors.append(
                f"canonical_answer_sha256 mismatch (recorded={recorded!r} "
                f"recomputed={recomputed})"
            )
    else:
        checks["canonical_answer_sha256_reproducible"] = False

    # 3. problem present / non-empty.
    has_problem = isinstance(problem, str) and bool(problem.strip())
    checks["has_problem"] = has_problem
    if not has_problem:
        errors.append("missing or empty problem")

    # 4. Reference-free prompt: build and verify absence.
    prompt = None
    prompt_sha = None
    reference_absent = False
    if has_ref and has_problem:
        try:
            prompt = build_reference_free_prompt(record, get_policy_lock(family))
            prompt_sha = prompt_sha256(prompt)
            recorded_sha = record.get("prompt_sha256")
            norm_prompt = collapse_whitespace(prompt)
            norm_ref = collapse_whitespace(reference or "")
            reference_absent = (
                bool(norm_ref) and norm_ref not in norm_prompt
            )
            checks["prompt_source_is_problem"] = True
            checks["reference_absent_from_prompt"] = reference_absent
            if not reference_absent:
                errors.append("reference found in rendered prompt")
            if isinstance(recorded_sha, str) and recorded_sha:
                checks["prompt_sha256_matches_recorded"] = recorded_sha == prompt_sha
                if not checks["prompt_sha256_matches_recorded"]:
                    errors.append(
                        f"prompt_sha256 mismatch (recorded={recorded_sha!r} "
                        f"recomputed={prompt_sha})"
                    )
            else:
                checks["prompt_sha256_matches_recorded"] = True  # not yet recorded
        except Exception as exc:  # noqa: BLE001 - fail closed on any guard hit
            checks["prompt_source_is_problem"] = False
            checks["reference_absent_from_prompt"] = False
            errors.append(f"prompt build / guard failed: {exc}")

    # 5. messages reference-free.
    msg_leaks = _messages_contain_reference(record, reference or "") if has_ref else []
    checks["messages_reference_free"] = not msg_leaks
    if msg_leaks:
        errors.extend(msg_leaks)

    verdict = "pass" if not errors else "fail"
    return {
        "record_id": record_id,
        "canonical_answer_present": has_ref,
        "canonical_answer_sha256": (
            canonical_answer_sha256(record) if has_ref else None
        ),
        "prompt_sha256": prompt_sha,
        "prompt_fingerprint": (
            prompt_fingerprint(prompt) if prompt is not None else None
        ),
        "checks": checks,
        "errors": errors,
        "leak_verdict": verdict,
    }


def sha256_of_lines(lines: list[dict]) -> str:
    blob = "\n".join(
        json.dumps(r, sort_keys=True, ensure_ascii=False) for r in lines
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def run_scan(eval_file: str | Path, family: str, set_id: str | None = None,
             report_path: str | Path | None = None) -> dict:
    """Scan an eval set; returns the report dict (also writes it if requested).
    Exit non-zero is the caller's responsibility via ``main``."""
    eval_path = Path(eval_file)
    records = []
    with eval_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    policy = get_policy_lock(family)
    per_record = [scan_record(r, family) for r in records]
    passed = [p for p in per_record if p["leak_verdict"] == "pass"]
    failed = [p for p in per_record if p["leak_verdict"] == "fail"]
    pass_rate = len(passed) / len(per_record) if per_record else 0.0

    report = {
        "layer": "L1",
        "scan_tool": "scripts/evaluation_engine/leakage/scan.py",
        "eval_set_id": set_id or eval_path.stem,
        "eval_file": str(eval_path),
        "family": family,
        "policy_lock": policy.to_block(),
        "n_records": len(per_record),
        "n_pass": len(passed),
        "n_fail": len(failed),
        "leak_pass_rate": pass_rate,
        "fail_closed": pass_rate == 1.0,
        "records": per_record,
    }
    # Deterministic scan id: derived from the pass-rate + record verdicts +
    # the eval file records, so a clean re-scan reproduces the same id.
    report["leak_scan_id"] = sha256_of_lines(
        [
            {
                "record_id": p["record_id"],
                "leak_verdict": p["leak_verdict"],
                "canonical_answer_sha256": p["canonical_answer_sha256"],
            }
            for p in sorted(per_record, key=lambda x: x["record_id"])
        ]
    )

    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Protocol v2 L1 static leakage scan")
    ap.add_argument("--eval-file", required=True, help="eval JSONL to scan")
    ap.add_argument("--family", required=True,
                    choices=["math", "code", "semantic"])
    ap.add_argument("--set-id", default=None, help="eval set id for the report")
    ap.add_argument("--report", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    report = run_scan(args.eval_file, args.family, set_id=args.set_id,
                      report_path=args.report)
    print(
        f"[L1] {report['eval_set_id']}: {report['n_pass']}/{report['n_records']} "
        f"pass, leak_pass_rate={report['leak_pass_rate']:.4f}, "
        f"leak_scan_id={report['leak_scan_id'][:16]}"
    )
    for p in report["records"]:
        if p["leak_verdict"] == "fail":
            print(f"  FAIL {p['record_id']}: {p['errors']}")
    if report["fail_closed"]:
        print("[L1] scan PASSED (fail-closed: no leakage)")
        return 0
    print("[L1] scan FAILED (fail-closed)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
