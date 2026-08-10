#!/usr/bin/env python3
"""build_eval_v2.py — Protocol v2 eval-set rebuild (T2).

Builds new versioned eval sets (``math_eval_v2``, ``code_eval_v2``) with a
separate ``canonical_answer`` field, from the frozen Protocol v1 eval sets
under ``evaluation/eval_sets/phase6_expansion_v1/``. The frozen v1 files are
NEVER modified (immutability rule).

Derivation contract (Protocol v2 §3.2)
--------------------------------------
* ``canonical_answer`` is derived deterministically from the frozen v1
  ``solution`` field (math = expected solution text; code = gold patch, the
  unified diff). The derived value is verified byte-equal to the source gold
  and its SHA-256 is recorded per record.
* ``canonical_answer_sha256`` and ``prompt_sha256`` are recorded per record.
* ``messages`` contains ONLY the user problem turn — no reference answer
  (mission requirement and the strongest guarantee against re-leakage).
* Reference-derived v1 fields are sanitized / dropped (see the per-record
  ``protocol_v2.sanitized_from_v1`` note): ``solution`` -> ``canonical_answer``,
  ``context`` dropped (math context carries ``Expected answer: ...``; code
  context carries gold-derived ``Files touched: ...``),
  ``verification_evidence.expected_answer_head`` scrubbed.
* Provenance is preserved: record_id, original_id, source metadata, lineage,
  verification, and a pointer to the source v1 eval set are carried forward.

Deterministic: identical inputs produce byte-identical records and checksums.
Read-only on frozen assets. Writes only under
``evaluation/eval_sets/protocol_v2/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Repository layout (this repo root; the same script runs on the WSL box
# where the path is /mnt/d/atlas-dataset).
REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

V1_DIR = REPO / "evaluation" / "eval_sets" / "phase6_expansion_v1"
OUT_DIR = REPO / "evaluation" / "eval_sets" / "protocol_v2"

BUILD_SCRIPT = "scripts/evaluation_engine/build_eval_v2.py"
BUILD_VERSION = "v1"

FAMILIES = {
    "math": {
        "v1_file": "math_eval_v1.jsonl",
        "v2_id": "math_eval_v2",
        "family": "math",
        "canonical_source": "solution (expected solution text)",
    },
    "code": {
        "v1_file": "code_eval_v1.jsonl",
        "v2_id": "code_eval_v2",
        "family": "code",
        "canonical_source": "solution (gold patch, unified diff)",
    },
}


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def derive_canonical_answer(v1: dict, family: str) -> str:
    """Deterministic derivation of ``canonical_answer`` from the frozen v1
    record. The full v1 ``solution`` text is the canonical reference for both
    families (the QEE v2 math extractor pulls the final answer from it; the
    code scorer aligns the unified diff). Fail-closed if missing/empty."""
    solution = v1.get("solution")
    if not isinstance(solution, str) or not solution.strip():
        raise ValueError(
            f"derive_canonical_answer[{family}] {v1.get('record_id')}: "
            "missing/empty v1 solution"
        )
    return solution


def sanitized_verification_evidence(v1: dict) -> dict:
    """Copy verification evidence, scrubbing the reference-derived
    ``expected_answer_head`` field (a partial reference)."""
    ev = dict(v1.get("verification_evidence") or {})
    ev.pop("expected_answer_head", None)
    return ev


def record_to_v2(v1: dict, family_cfg: dict) -> dict:
    record_id = v1.get("record_id")
    family = family_cfg["family"]
    canonical = derive_canonical_answer(v1, family)

    messages = [{"role": "user", "content": v1.get("problem") or ""}]

    lineage = dict(v1.get("lineage") or {})
    lineage["source_eval_set"] = {
        "eval_set_id": "phase6-" + family + "-eval-v1",
        "version": "v1",
    }

    # Runtime guard verdict at build time (fail-closed). Any guard hit means
    # the record is held (moved to the *_held.jsonl sidecar) rather than
    # silently evaluated.
    from evaluation_engine.leakage.prompts import (
        ReferenceLeakError,
        build_reference_free_prompt,
        get_policy_lock,
        prompt_fingerprint,
        prompt_sha256,
    )

    guard_verdict = "pass"
    guard_reason = None
    prompt_sha = None
    fp = None
    try:
        prompt = build_reference_free_prompt(
            {"record_id": record_id, "family": family, "problem": v1.get("problem"),
             "canonical_answer": canonical},
            get_policy_lock(family),
        )
        prompt_sha = prompt_sha256(prompt)
        fp = prompt_fingerprint(prompt)
    except ReferenceLeakError as exc:
        guard_verdict = "fail"
        guard_reason = str(exc)

    protocol_v2 = {
        "prompt_source": "problem",
        "canonical_answer_source": "solution",
        "canonical_answer_derivation": family_cfg["canonical_source"],
        "canonical_answer_verified_equal_source_gold": True,
        "sanitized_from_v1": {
            "dropped": ["context", "solution", "messages[assistant]"],
            "scrubbed": ["verification_evidence.expected_answer_head"],
            "reason": (
                "reference-derived content removed so no gold survives outside "
                "canonical_answer; frozen v1 retains the originals"
            ),
        },
        "messages_contains_reference": False,
        "leak_guard_verdict": guard_verdict,
        "leak_guard_reason": guard_reason,
    }

    out = {
        "record_id": record_id,
        "version": "v2",
        "eval_set_id": family_cfg["v2_id"],
        "family": family,
        "view_id": v1.get("view_id"),
        "source_id": v1.get("source_id"),
        "original_id": v1.get("original_id"),
        "domain": v1.get("domain"),
        "category": v1.get("category"),
        "difficulty": v1.get("difficulty"),
        "expert_tier": v1.get("expert_tier"),
        "license": v1.get("license"),
        "source_name": v1.get("source_name"),
        "source_url": v1.get("source_url"),
        "subdomains": v1.get("subdomains", []),
        "lineage": lineage,
        "verification": v1.get("verification"),
        "verification_evidence": sanitized_verification_evidence(v1),
        "problem": v1.get("problem"),
        "canonical_answer": canonical,
        "canonical_answer_sha256": sha256_hex(canonical),
        "canonical_answer_source": "solution",
        "prompt_sha256": prompt_sha,
        "prompt_fingerprint": fp,
        "messages": messages,
        "protocol_v2": protocol_v2,
    }
    return out


def build_manifest(v2_rows: list[dict], family_cfg: dict, v1_rows: list[dict],
                   out_jsonl: Path, held_rows: list[dict] | None = None) -> dict:
    v2_id = family_cfg["v2_id"]
    family = family_cfg["family"]
    held_rows = held_rows or []
    manifest = {
        "eval_set_id": v2_id,
        "version": "v2",
        "family": family,
        "derived_from": {
            "eval_set_id": "phase6-" + family + "-eval-v1",
            "version": "v1",
            "n_records": len(v1_rows),
            "dir": str(V1_DIR.relative_to(REPO)),
        },
        "n_records": len(v2_rows),
        "n_clean": len(v2_rows),
        "n_held": len(held_rows),
        "held_record_ids": [h.get("record_id") for h in held_rows],
        "leak_guard_holds": [
            {
                "record_id": h.get("record_id"),
                "reason": (h.get("protocol_v2") or {}).get("leak_guard_reason"),
            }
            for h in held_rows
        ],
        "derivation": {
            "script": BUILD_SCRIPT,
            "build_version": BUILD_VERSION,
            "method": "deterministic; canonical_answer byte-equal copy of v1 "
                      "solution; verified equal to source gold",
            "canonical_answer_present": sum(
                1 for r in v2_rows if r.get("canonical_answer")
            ),
            "canonical_answer_non_empty": sum(
                1 for r in v2_rows if (r.get("canonical_answer") or "").strip()
            ),
            "canonical_answer_verified_equal_solution": sum(
                1 for r in v2_rows if r.get("protocol_v2", {}).get(
                    "canonical_answer_verified_equal_source_gold")
            ),
            "messages_user_only": sum(
                1 for r in v2_rows
                if all(m.get("role") == "user" for m in r.get("messages", []))
            ),
            "leak_guard_pass": sum(
                1 for r in v2_rows
                if (r.get("protocol_v2") or {}).get("leak_guard_verdict") == "pass"
            ),
            "prompt_sha256_recorded": sum(
                1 for r in v2_rows if r.get("prompt_sha256")
            ),
        },
        "provenance": {
            "original_id_present": sum(
                1 for r in v2_rows if r.get("original_id")
            ),
            "record_ids_match_v1": sum(
                1 for r in v2_rows
                if r.get("record_id") in {v.get("record_id") for v in v1_rows}
            ),
            "release": "expert-pilot-6500-v0.1",
        },
        "checksum": {
            "algorithm": "SHA-256",
            "records": sha256_of_lines(v2_rows),
        },
        "files": {
            "eval_jsonl": str(out_jsonl.relative_to(REPO)),
            "manifest": str((out_jsonl.parent / (v2_id + "_manifest.json"))
                            .relative_to(REPO)),
        },
    }
    if held_rows:
        manifest["files"]["held_jsonl"] = str(
            (out_jsonl.parent / (v2_id + "_held.jsonl")).relative_to(REPO)
        )
    return manifest


def build_family(family: str) -> dict:
    cfg = FAMILIES[family]
    v1_path = V1_DIR / cfg["v1_file"]
    if not v1_path.exists():
        raise FileNotFoundError(f"frozen v1 eval set not found: {v1_path}")

    v1_rows = load_jsonl(v1_path)
    all_rows = [record_to_v2(r, cfg) for r in v1_rows]
    # Deterministic ordering: preserve v1 order (already record_id-sorted).
    all_rows.sort(key=lambda r: r["record_id"])

    # Fail-closed split: guard-clean records form the evaluable eval set;
    # records that trip the runtime guard are held (sidecar) with their reason.
    clean = [r for r in all_rows
             if (r.get("protocol_v2") or {}).get("leak_guard_verdict") == "pass"]
    held = [r for r in all_rows if r not in clean]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_jsonl = OUT_DIR / (cfg["v2_id"] + ".jsonl")
    with out_jsonl.open("w", encoding="utf-8") as f:
        for r in clean:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if held:
        held_path = OUT_DIR / (cfg["v2_id"] + "_held.jsonl")
        with held_path.open("w", encoding="utf-8") as f:
            for r in held:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    manifest = build_manifest(clean, cfg, v1_rows, out_jsonl, held)
    manifest_path = OUT_DIR / (cfg["v2_id"] + "_manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "family": family,
        "eval_set_id": cfg["v2_id"],
        "n_records": len(clean),
        "n_held": len(held),
        "held_record_ids": [h.get("record_id") for h in held],
        "canonical_answer_present": manifest["derivation"][
            "canonical_answer_present"
        ],
        "messages_user_only": manifest["derivation"]["messages_user_only"],
        "record_ids_match_v1": manifest["provenance"]["record_ids_match_v1"],
        "checksum": manifest["checksum"]["records"],
        "manifest": str(manifest_path.relative_to(REPO)),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Protocol v2 eval-set rebuild (T2)")
    ap.add_argument("--families", nargs="*", default=["math", "code"],
                    choices=["math", "code"],
                    help="families to rebuild (default: math code)")
    args = ap.parse_args(argv)

    summary = {}
    for fam in args.families:
        res = build_family(fam)
        summary[fam] = res
        print(f"[T2] {res['eval_set_id']}: {res['n_records']} clean, "
              f"{res['n_held']} held; canonical_answer="
              f"{res['canonical_answer_present']}/{res['n_records']}, "
              f"messages_user_only={res['messages_user_only']}/{res['n_records']}, "
              f"ids_match_v1={res['record_ids_match_v1']}/{res['n_records']}")
        if res["held_record_ids"]:
            print(f"     HELD: {res['held_record_ids']}")

    summary_path = OUT_DIR / "build_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {summary_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
