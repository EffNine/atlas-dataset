"""Interactive terminal reviewer for Atlas expert review samples.

Speeds up human calibration review: one record at a time, single-key verdicts,
dimension-score defaults, full-text pager, incremental crash-safe decisions
file, and resume (already-decided records are skipped on restart).

Usage:
  python3 scripts/expert_pipeline/review_ui.py \
      --input     review/atlas_expert_architecture-v0.1_review_input.jsonl \
      --sample    review/atlas_expert_architecture-v0.1_review_sample.jsonl \
      --decisions review/atlas_expert_architecture-v0.1_review_decisions.jsonl

Keys per record:
  k = KEEP    x = REJECT    v = REVISE
  f = full text in pager    s = skip (decide later)    q = quit (progress kept)

Blind by construction: payloads come from sonnet_input.py output, which strips
auto_gate / quality_score. auto_gate_snapshot is joined from the sample file
only at save time, after the verdict is fixed.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pydoc
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "review" / "atlas_expert_architecture-v0.1_review_input.jsonl"
DEFAULT_SAMPLE = REPO_ROOT / "review" / "atlas_expert_architecture-v0.1_review_sample.jsonl"
DEFAULT_DECISIONS = REPO_ROOT / "review" / "atlas_expert_architecture-v0.1_review_decisions.jsonl"

VERDICT_BY_KEY = {"k": "KEEP", "x": "REJECT", "v": "REVISE"}
DIM_KEYS = ["correctness", "reasoning_depth", "explanation_quality", "provenance_confidence"]
DEFAULT_DIMS = {
    "KEEP": [4, 3, 4, 4],
    "REVISE": [3, 2, 3, 3],
    "REJECT": [2, 1, 2, 2],
}


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def load_jsonl(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def load_sample_index(sample_path: Path) -> dict[str, dict]:
    """review_id -> sample envelope (for auto_gate_snapshot join at save time)."""
    return {e["review_id"]: e for e in load_jsonl(sample_path)}


def decided_ids(decisions_path: Path) -> set[str]:
    if not decisions_path.exists():
        return set()
    return {d["review_id"] for d in load_jsonl(decisions_path)}


def build_decision(block: dict, sample_entry: dict | None, verdict: str,
                   dims: list[int], notes: str, reviewer: str,
                   now: str | None = None) -> dict:
    return {
        "review_id": block["review_id"],
        "record_id": block["record_id"],
        "reviewer": reviewer,
        "verdict": verdict,
        "dimensions": dict(zip(DIM_KEYS, dims)),
        "notes": notes.strip(),
        "reviewed_at": now or _utc_now_iso(),
        "auto_gate_snapshot": (
            (sample_entry or {}).get("calibration", {}).get("auto_gate")
        ),
    }


def append_decision(decisions_path: Path, decision: dict) -> None:
    """Crash-safe: one JSONL line, flushed immediately."""
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    with open(decisions_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(decision, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def parse_dims(raw: str, default: list[int]) -> list[int] | None:
    """'4,3,4,5' / '4 3 4 5' / '' (default). Returns None if invalid."""
    raw = raw.strip()
    if not raw:
        return list(default)
    parts = [p for p in raw.replace(",", " ").split(" ") if p]
    if len(parts) != len(DIM_KEYS):
        return None
    try:
        vals = [int(p) for p in parts]
    except ValueError:
        return None
    if any(v < 1 or v > 5 for v in vals):
        return None
    return vals


def _clip(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    return text[:limit] + f"\n... [+{len(text) - limit} chars, press f for full text]"


def render(block: dict, max_problem: int = 1200, max_solution: int = 1800,
           full: bool = False) -> str:
    p = block.get("payload", {})
    extraction = p.get("extraction", {})
    title = extraction.get("title") or p.get("id", "?")
    problem = p.get("problem") or ""
    solution = p.get("solution") or ""
    summary_ctx = p.get("context") or ""
    head = (
        f"{block['review_id']} | {title}\n"
        f"sig={extraction.get('sig', '?')} kep={extraction.get('kep_number', '?')} "
        f"difficulty={p.get('difficulty', '?')} "
        f"path={extraction.get('source_path', '?')}"
    )
    body = (
        f"\n--- PROBLEM (motivation) ---\n{_clip(problem, None if full else max_problem)}\n"
        f"\n--- CONTEXT ---\n{_clip(summary_ctx, None if full else 600)}\n"
        f"\n--- SOLUTION (proposal/design) ---\n{_clip(solution, None if full else max_solution)}"
    )
    return head + body


def run_session(blocks: list[dict], sample_by_id: dict[str, dict],
                decisions_path: Path, reviewer: str,
                *, input_fn: Callable[[str], str] = input,
                print_fn: Callable[..., None] = print,
                pager_fn: Callable[[str], None] | None = None,
                now_fn: Callable[[], str] = _utc_now_iso) -> dict:
    done = decided_ids(decisions_path)
    pending = [b for b in blocks if b["review_id"] not in done]
    counts = {"KEEP": 0, "REVISE": 0, "REJECT": 0, "skipped": 0}
    print_fn(f"{len(blocks)} records | {len(done)} already reviewed | {len(pending)} to go")

    for idx, block in enumerate(pending, start=len(done) + 1):
        print_fn("=" * 72)
        print_fn(f"[{idx}/{len(blocks)}]")
        print_fn(render(block))

        verdict_key = ""
        while verdict_key not in VERDICT_BY_KEY:
            verdict_key = input_fn("Verdict [k]=KEEP [x]=REJECT re[v]ISE [f]ull [s]kip [q]uit: ").strip().lower()
            if verdict_key == "q":
                remaining = len(pending) - (idx - len(done))
                counts["skipped"] += remaining
                print_fn(f"quit early: {len(pending) - remaining} decided this session, "
                         f"{remaining} still pending")
                return counts
            if verdict_key == "s":
                counts["skipped"] += 1
                print_fn("(skipped)")
                break
            if verdict_key == "f":
                (pager_fn or pydoc.pager)(render(block, full=True))
                verdict_key = ""
                continue
            if verdict_key not in VERDICT_BY_KEY:
                print_fn("  ? enter k, x, v, f, s or q")

        if verdict_key == "s":
            continue
        verdict = VERDICT_BY_KEY[verdict_key]

        dims: list[int] | None = None
        while dims is None:
            raw = input_fn(f"dimensions c,r,e,p 1-5 [{'/'.join(map(str, DEFAULT_DIMS[verdict]))}] Enter=default: ")
            dims = parse_dims(raw, DEFAULT_DIMS[verdict])
            if dims is None:
                print_fn("  ? need 4 numbers in 1..5, e.g. '4,3,4,5'")
        notes = input_fn("notes (Enter=none): ")

        decision = build_decision(block, sample_by_id.get(block["review_id"]),
                                  verdict, dims, notes, reviewer, now_fn())
        append_decision(decisions_path, decision)
        counts[verdict] += 1
        total_done = len(done) + counts["KEEP"] + counts["REVISE"] + counts["REJECT"]
        print_fn(f"saved {decision['review_id']} ({total_done}/{len(blocks)})")

    print_fn(f"session complete: KEEP={counts['KEEP']} REVISE={counts['REVISE']} "
             f"REJECT={counts['REJECT']} skipped={counts['skipped']}")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive human review UI")
    parser.add_argument("--input", default=str(DEFAULT_INPUT),
                        help="blind review input JSONL (sonnet_input.py output)")
    parser.add_argument("--sample", default=str(DEFAULT_SAMPLE),
                        help="sample file (for auto_gate_snapshot join at save time)")
    parser.add_argument("--decisions", default=str(DEFAULT_DECISIONS),
                        help="decisions JSONL (appended incrementally; resume-safe)")
    parser.add_argument("--reviewer", default=f"human:{os.environ.get('USER', 'unknown')}")
    args = parser.parse_args(argv)

    blocks = load_jsonl(Path(args.input))
    sample_by_id = load_sample_index(Path(args.sample))
    if not blocks:
        print("nothing to review: empty input file")
        return 1
    run_session(blocks, sample_by_id, Path(args.decisions), args.reviewer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
