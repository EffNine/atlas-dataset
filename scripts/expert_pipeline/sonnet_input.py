"""Blind input payload generation for Sonnet 5 review.

Per docs/expert_pilot_6500_sonnet5_review_execution_plan_v0.1.md:
- input: review/expert_pilot_6500_review_sample_v0.1.jsonl (324 lines)
- output: review/expert_pilot_6500_sonnet5_input_v0.1.jsonl
- one JSON object per line: {"review_id", "record_id", "payload"}
- payload strips ALL gate/hint values (calibration, quality_score)
- blind guard: grep check that no auto_gate/quality_score appears in output
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE = REPO_ROOT / "review" / "expert_pilot_6500_review_sample_v0.1.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "review" / "expert_pilot_6500_sonnet5_input_v0.1.jsonl"

FORBIDDEN = ("auto_gate", "quality_score")


def blind_payload(entry: dict) -> dict:
    """Return the review envelope + record with gate/hint values stripped."""
    rec = {k: v for k, v in entry["record"].items() if k != "calibration"}
    rec["metadata"] = {k: v for k, v in rec["metadata"].items() if k != "quality_score"}
    return {
        "review_id": entry["review_id"],
        "record_id": entry["record_id"],
        "payload": rec,
    }


def generate(sample_path: Path, out_path: Path) -> list[dict]:
    lines = [l for l in sample_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for line in lines:
        entry = json.loads(line)
        out.append(blind_payload(entry))
    if out_path.exists():
        raise FileExistsError(f"refusing to overwrite existing input file: {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for block in out:
            f.write(json.dumps(block, ensure_ascii=False) + "\n")
    return out


def blind_guard(out_path: Path) -> list[str]:
    """Return list of forbidden-value leaks found in the output file (empty = clean)."""
    text = out_path.read_text(encoding="utf-8").lower()
    return [tok for tok in FORBIDDEN if tok in text]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate blind Sonnet 5 review inputs")
    parser.add_argument("--sample", default=str(DEFAULT_SAMPLE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)

    out = Path(args.output)
    blocks = generate(Path(args.sample), out)
    leaks = blind_guard(out)
    if leaks:
        print(f"BLIND GUARD FAILURE: forbidden tokens found in output: {leaks}")
        return 1
    print(json.dumps({
        "written": str(out),
        "records": len(blocks),
        "blind_guard": "clean",
        "forbidden_checked": FORBIDDEN,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
