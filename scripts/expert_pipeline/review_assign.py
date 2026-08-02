"""AI reviewer assignment generation for the Phase 1B review.

Per docs/expert_pilot_6500_sonnet5_review_execution_plan_v0.1.md Step 1
(assign) and the review-operations skill: create assignments only — no
decisions, no verdicts, no label generation. Dataset stays read-only.

- one reviewer per record: ai-reviewer:claude-sonnet-5
- category-based assignment (uniform here: single AI reviewer)
- priority: high for boundary records (quality band 5-6, near/at threshold),
  normal otherwise
- review_status: assigned; completed_timestamp stays null
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE = REPO_ROOT / "review" / "expert_pilot_6500_review_sample_v0.1.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "review" / "expert_pilot_6500_sonnet5_assignments_v0.1.json"

AI_REVIEWER = "ai-reviewer:claude-sonnet-5"
BOUNDARY_BANDS = {(5, 6)}


def generate_assignments(sample_path: Path, reviewer: str = AI_REVIEWER,
                         assigned_at: str | None = None) -> list[dict]:
    lines = [l for l in sample_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    timestamp = assigned_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
    assignments = []
    for line in lines:
        entry = json.loads(line)
        band = tuple(entry["stratum"]["quality_band"])
        priority = "high" if band in BOUNDARY_BANDS else "normal"
        assignments.append({
            "record_id": entry["record_id"],
            "review_id": entry["review_id"],
            "category": entry["source_id"],
            "priority": priority,
            "review_status": "assigned",
            "assigned_reviewer": reviewer,
            "assigned_timestamp": timestamp,
            "completed_timestamp": None,
            "notes": f"quality_band={band[0]}-{band[1]}; blind AI review, no gate values shown",
        })
    return assignments


def write_assignments(assignments: list[dict], out_path: Path) -> None:
    if out_path.exists():
        raise FileExistsError(f"refusing to overwrite existing assignments: {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(assignments, f, indent=2, ensure_ascii=False)


def summarize(assignments: list[dict]) -> dict:
    by_cat: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for a in assignments:
        by_cat[a["category"]] = by_cat.get(a["category"], 0) + 1
        by_priority[a["priority"]] = by_priority.get(a["priority"], 0) + 1
        by_status[a["review_status"]] = by_status.get(a["review_status"], 0) + 1
    return {
        "total": len(assignments),
        "reviewer": assignments[0]["assigned_reviewer"] if assignments else None,
        "per_category": by_cat,
        "per_priority": by_priority,
        "per_status": by_status,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Sonnet 5 review assignments")
    parser.add_argument("--sample", default=str(DEFAULT_SAMPLE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--assigned-at", default=None, help="ISO timestamp (default: now UTC)")
    args = parser.parse_args(argv)

    assignments = generate_assignments(Path(args.sample), assigned_at=args.assigned_at)
    out = Path(args.output)
    write_assignments(assignments, out)
    print(json.dumps({"written": str(out), **summarize(assignments)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
