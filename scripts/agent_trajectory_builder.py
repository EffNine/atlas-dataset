#!/usr/bin/env python3
"""
agent_trajectory_builder.py — Agent trajectory dataset builder for atan-v1.

Processes raw SWE-agent trajectories from Atlas raw sources into SFT-formatted
training data with Malaysian engineering context.

Trajectory sources:
  - raw/p0/staging/p0-swe-smith-trajectories.jsonl  (1,000 records, full trajectories)
  - raw/p0/staging/p0-swe-smith-mini.jsonl          (1,000 records, shorter trajectories)
  - raw/p1/staging/p1-swe-smith-mini.jsonl           (65,985 records, full mini set)

Output format:
  - Train/val split with proper multi-turn messages
  - Malaysian engineering system prompt injected
  - Tool-role messages preserved (user=observation, assistant=thought+action)
  - Metadata: trajectory stats, difficulty signal, license, source

Usage:
  python scripts/agent_trajectory_builder.py \\
      --output-dir model-eval-finetune/datasets/sft/ \\
      --min-messages 15 \\
      --max-trajectories 5000 \\
      --val-ratio 0.1 \\
      --seed 42
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ATLAS_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("/home/afnan/projects/active/model-eval-finetune/datasets/sft")

# Source definitions: (path_pattern, name, license, estimated_count)
TRAJECTORY_SOURCES: list[dict[str, Any]] = [
    {
        "path": ATLAS_ROOT / "raw" / "p0" / "staging" / "p0-swe-smith-trajectories.jsonl",
        "name": "p0-swe-smith-trajectories",
        "license": "MIT",
        "source_type": "swe_agent",
    },
    {
        "path": ATLAS_ROOT / "raw" / "p0" / "staging" / "p0-swe-smith-mini.jsonl",
        "name": "p0-swe-smith-mini",
        "license": "MIT",
        "source_type": "swe_agent",
    },
    {
        "path": ATLAS_ROOT / "raw" / "p1" / "staging" / "p1-swe-smith-mini.jsonl",
        "name": "p1-swe-smith-mini",
        "license": "MIT",
        "source_type": "swe_agent",
    },
]

# Malaysian engineering system prompt for atan-v1
ATAN_V1_SYSTEM_PROMPT = (
    "Anda adalah Atan, seorang senior software engineer dan architecture consultant "
    "dari Malaysia. Anda mempunyai pengalaman luas dalam software engineering, "
    "system design, debugging, code review, dan agentic workflows.\n\n"
    "Gaya komunikasi:\n"
    "- Boleh bercakap dalam Bahasa Melayu atau English, atau mix mengikut konteks\n"
    "- Technical terms kekal dalam English (code, API, architecture, etc.)\n"
    "- Natural, professional, like talking to a senior colleague\n"
    "- Jangan terlalu formal atau sound like AI chatbot\n\n"
    "Prinsip kerja:\n"
    "- Fahami full context sebelum buat sebarang perubahan\n"
    "- Consider trade-offs dan impact pada architecture\n"
    "- Challenge bad ideas secara profesional — jangan just agree\n"
    "- Explain reasoning dengan jelas, bukan just give answer\n"
    "- Jika approach user ada masalah, tunjukkan alternatives + pros/cons\n\n"
    "Agentic workflow: understand → inspect → plan → execute → test → review → verify\n"
    "Jangan skip step. Verify setiap perubahan sebelum conclude."
)

# Quality filters
MIN_MESSAGES = 10        # Minimum trajectory length
MAX_MESSAGES = 500       # Maximum to avoid OOM
MIN_OBSERVATIONS = 2     # Minimum tool interactions
MAX_OBSERVATIONS = 100   # Cap to avoid excessively long trajectories


# ---------------------------------------------------------------------------
# Trajectory analysis
# ---------------------------------------------------------------------------

@dataclass
class TrajectoryStats:
    """Statistics for a single trajectory."""
    message_count: int = 0
    observation_count: int = 0
    thought_count: int = 0
    bash_command_count: int = 0
    file_read_count: int = 0
    has_error: bool = False
    has_success_indicator: bool = False
    has_traceback: bool = False
    final_verdict: str = "unknown"
    estimated_difficulty: int = 2
    tool_call_patterns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_trajectory(messages: list[dict]) -> TrajectoryStats:
    """Analyze a trajectory and compute quality stats."""
    stats = TrajectoryStats(message_count=len(messages))

    for msg in messages:
        content = msg.get("content", "") or ""
        role = msg.get("role", "")

        # Count observations (tool outputs in user messages)
        if role == "user" and content.strip().startswith("<returncode"):
            stats.observation_count += 1
        elif role == "user" and content.strip().startswith("OBSERVATION:"):
            stats.observation_count += 1

        # Detect error patterns in ANY message (not just assistant)
        if "Traceback" in content or "Error:" in content or "FAILED" in content:
            stats.has_error = True
        if "traceback" in content.lower():
            stats.has_traceback = True

        # Count assistant reasoning patterns
        if role == "assistant":
            if "THOUGHT:" in content:
                stats.thought_count += 1
            if "```bash" in content or "```" in content:
                stats.bash_command_count += 1
            if "```python" in content:
                stats.file_read_count += 1

            # Detect success indicators (only in assistant messages)
            success_words = [
                "fixed", "resolved", "all tests passing", "completed",
                "successfully", "working", "verified", "correct",
            ]
            if any(w in content.lower() for w in success_words):
                stats.has_success_indicator = True

    # Estimate difficulty based on trajectory complexity
    if stats.observation_count >= 20:
        stats.estimated_difficulty = 4
    elif stats.observation_count >= 10:
        stats.estimated_difficulty = 3
    elif stats.observation_count >= 5:
        stats.estimated_difficulty = 2
    else:
        stats.estimated_difficulty = 1

    # Final verdict
    if stats.has_traceback and not stats.has_success_indicator:
        stats.final_verdict = "failed"
    elif stats.has_success_indicator:
        stats.final_verdict = "completed"
    else:
        stats.final_verdict = "inconclusive"

    return stats


def is_quality_trajectory(stats: TrajectoryStats) -> bool:
    """Check if trajectory meets quality thresholds."""
    if stats.message_count < MIN_MESSAGES:
        return False
    if stats.message_count > MAX_MESSAGES:
        return False
    if stats.observation_count < MIN_OBSERVATIONS:
        return False
    if stats.observation_count > MAX_OBSERVATIONS:
        return False
    # Filter out trajectories with catastrophic failures
    if stats.has_traceback and stats.final_verdict == "failed":
        return False
    return True


# ---------------------------------------------------------------------------
# Trajectory conversion
# ---------------------------------------------------------------------------

def extract_pr_description(messages: list[dict]) -> str:
    """Extract the PR description / task from the first user message."""
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            # Strip uploaded_files wrapper but keep inner content
            content = re.sub(r"<uploaded_files>.*?</uploaded_files>\s*", "", content, flags=re.DOTALL)
            # Extract content inside pr_description tags
            pr_match = re.search(r"<pr_description>(.*?)</pr_description>", content, re.DOTALL | re.IGNORECASE)
            if pr_match:
                content = pr_match.group(1)
            else:
                # No pr_description wrapper — strip it if present as raw text
                content = re.sub(r"<pr_description>.*?</pr_description>\s*", "", content, flags=re.DOTALL)
            # Strip instruction wrapper
            instr_match = re.search(r"<instruction>(.*?)</instruction>", content, re.DOTALL | re.IGNORECASE)
            if instr_match:
                content = instr_match.group(1)
            content = content.strip()
            if content:
                return content[:2000]  # Cap length
    return ""


def classify_domain(messages: list[dict]) -> str:
    """Classify the engineering domain from trajectory content."""
    content = " ".join(m.get("content", "") for m in messages).lower()

    domain_scores: dict[str, float] = {
        "software_engineering": 0.0,
        "system_engineering": 0.0,
        "ai_machine_learning": 0.0,
        "security": 0.0,
        "devops": 0.0,
    }

    # Software engineering signals
    sw_signals = [
        "def ", "class ", "import ", "function ", "method", "api",
        "database", "model", "route", "handler", "middleware",
    ]
    for sig in sw_signals:
        if sig in content:
            domain_scores["software_engineering"] += 1

    # Systems engineering signals
    sys_signals = ["kernel", "driver", "syscall", "memory", "thread", "process", "posix"]
    for sig in sys_signals:
        if sig in content:
            domain_scores["system_engineering"] += 1

    # AI/ML signals
    ai_signals = ["model", "training", "neural", "tensor", "gradient", "loss", "dataset"]
    for sig in ai_signals:
        if sig in content:
            domain_scores["ai_machine_learning"] += 1

    # Security signals
    sec_signals = ["auth", "token", "oauth", "cipher", "encrypt", "vulnerability", "cve"]
    for sig in sec_signals:
        if sig in content:
            domain_scores["security"] += 1

    # DevOps signals
    devops_signals = ["docker", "kubernetes", "ci", "cd", "pipeline", "deploy", "k8s"]
    for sig in devops_signals:
        if sig in content:
            domain_scores["devops"] += 1

    if max(domain_scores.values()) == 0:
        return "software_engineering"
    return max(domain_scores, key=domain_scores.get)  # type: ignore


def convert_trajectory(
    messages: list[dict],
    system_prompt: str,
    source_name: str,
    license_: str,
    stats: TrajectoryStats,
) -> dict[str, Any]:
    """
    Convert a raw SWE-agent trajectory to SFT format.

    Preserves the multi-turn structure including tool observations.
    Each trajectory becomes one complete conversation example.
    """
    pr_desc = extract_pr_description(messages)
    domain = classify_domain(messages)

    # Build SFT messages preserving trajectory structure
    sft_messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
    ]

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""

        if role == "system":
            continue  # Already injected our system prompt
        elif role == "user":
            # Check if this is a tool observation
            stripped = content.strip()
            if stripped.startswith("<returncode") or stripped.startswith("OBSERVATION:"):
                # Tool observation — keep as user message (model sees tool output)
                sft_messages.append({"role": "user", "content": content})
            else:
                # Original user prompt or task
                sft_messages.append({"role": "user", "content": content})
        elif role == "assistant":
            sft_messages.append({"role": "assistant", "content": content})
        elif role == "tool":
            sft_messages.append({"role": "tool", "content": content})

    # Compute trajectory hash for deduplication
    content_hash = hashlib.sha256(
        json.dumps(sft_messages, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]

    return {
        "messages": sft_messages,
        "metadata": {
            "source": source_name,
            "license": license_,
            "source_type": "swe_agent",
            "domain": domain,
            "difficulty": stats.estimated_difficulty,
            "verdict": stats.final_verdict,
            "message_count": stats.message_count,
            "observation_count": stats.observation_count,
            "thought_count": stats.thought_count,
            "trajectory_hash": content_hash,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_trajectory_source(source: dict) -> tuple[list[dict], TrajectoryStats]:
    """Load and analyze a single trajectory source file."""
    path = Path(source["path"])
    if not path.exists():
        print(f"  [SKIP] Source not found: {path}", file=sys.stderr)
        return [], TrajectoryStats()

    records = []
    total_stats = TrajectoryStats()
    count = 0

    print(f"  Loading {path}...", file=sys.stderr)
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            messages = rec.get("messages", [])
            if not messages:
                continue

            stats = analyze_trajectory(messages)
            total_stats.message_count += stats.message_count
            total_stats.observation_count += stats.observation_count
            total_stats.thought_count += stats.thought_count
            if stats.has_error:
                total_stats.has_error = True
            if stats.has_success_indicator:
                total_stats.has_success_indicator = True
            if stats.final_verdict == "completed":
                total_stats.final_verdict = "completed"

            records.append({
                "messages": messages,
                "source": source,
                "stats": stats,
            })
            count += 1

            if count % 1000 == 0:
                print(f"    ... {count} records processed", file=sys.stderr)

    print(f"  Done: {count} records from {source['name']}", file=sys.stderr)
    return records, total_stats


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_trajectories(
    output_dir: Path,
    min_messages: int = MIN_MESSAGES,
    max_trajectories: int | None = None,
    val_ratio: float = 0.1,
    seed: int = 42,
    include_failed: bool = False,
) -> dict[str, Any]:
    """
    Build the agent trajectory dataset.

    Args:
        output_dir: Output directory for SFT data.
        min_messages: Minimum trajectory message count.
        max_trajectories: Max trajectories to include (None = all).
        val_ratio: Validation split ratio.
        seed: Random seed for splitting.
        include_failed: Whether to include failed trajectories.
    """
    global MIN_MESSAGES
    MIN_MESSAGES = min_messages

    print("=" * 60, file=sys.stderr)
    print("ATAN-V1 AGENT TRAJECTORY BUILDER", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Load all sources
    all_records: list[dict] = []
    source_stats: dict[str, dict] = {}

    for source in TRAJECTORY_SOURCES:
        records, stats = load_trajectory_source(source)
        name = source["name"]
        source_stats[name] = {
            "total": stats.message_count,
            "records": len(records),
            "avg_messages": stats.message_count / max(len(records), 1),
            "avg_observations": stats.observation_count / max(len(records), 1),
        }
        all_records.extend(records)

    print(f"\nTotal raw records: {len(all_records)}", file=sys.stderr)

    # Filter by quality
    qualified = []
    filtered_out = {"too_short": 0, "too_long": 0, "too_few_obs": 0, "catastrophic": 0}

    for rec in all_records:
        stats = rec["stats"]
        if not is_quality_trajectory(stats):
            if stats.message_count < MIN_MESSAGES:
                filtered_out["too_short"] += 1
            elif stats.message_count > MAX_MESSAGES:
                filtered_out["too_long"] += 1
            elif stats.observation_count < MIN_OBSERVATIONS:
                filtered_out["too_few_obs"] += 1
            elif stats.has_traceback and stats.final_verdict == "failed":
                filtered_out["catastrophic"] += 1
            continue

        if not include_failed and stats.final_verdict == "failed":
            continue

        converted = convert_trajectory(
            messages=rec["messages"],
            system_prompt=ATAN_V1_SYSTEM_PROMPT,
            source_name=rec["source"]["name"],
            license_=rec["source"]["license"],
            stats=stats,
        )
        qualified.append(converted)

    print(f"Qualified trajectories: {len(qualified)}", file=sys.stderr)
    print(f"Filtered out: {filtered_out}", file=sys.stderr)

    # Apply max cap
    if max_trajectories and len(qualified) > max_trajectories:
        random.seed(seed)
        qualified = random.sample(qualified, max_trajectories)
        print(f"Capped to {max_trajectories} trajectories", file=sys.stderr)

    # Split train/val
    random.seed(seed)
    random.shuffle(qualified)
    val_count = max(1, int(len(qualified) * val_ratio))
    val_data = qualified[:val_count]
    train_data = qualified[val_count:]

    print(f"\nSplit: train={len(train_data)}, val={len(val_data)}", file=sys.stderr)

    # Write output
    output_dir.mkdir(parents=True, exist_ok=True)

    train_path = output_dir / "agent_trajectories_train.jsonl"
    val_path = output_dir / "agent_trajectories_val.jsonl"

    for path, data in [(train_path, train_data), (val_path, val_data)]:
        with path.open("w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"Wrote {path}: {len(data)} records", file=sys.stderr)

    # Compute domain distribution
    domain_dist: dict[str, int] = {}
    difficulty_dist: dict[str, int] = {}
    verdict_dist: dict[str, int] = {}
    source_dist: dict[str, int] = {}

    for item in train_data + val_data:
        meta = item["metadata"]
        domain_dist[meta["domain"]] = domain_dist.get(meta["domain"], 0) + 1
        difficulty_dist[str(meta["difficulty"])] = difficulty_dist.get(str(meta["difficulty"]), 0) + 1
        verdict_dist[meta["verdict"]] = verdict_dist.get(meta["verdict"], 0) + 1
        source_dist[meta["source"]] = source_dist.get(meta["source"], 0) + 1

    # Write metadata report
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "total_records": len(train_data) + len(val_data),
        "train_records": len(train_data),
        "val_records": len(val_data),
        "filters_applied": {
            "min_messages": MIN_MESSAGES,
            "max_messages": MAX_MESSAGES,
            "min_observations": MIN_OBSERVATIONS,
            "max_observations": MAX_OBSERVATIONS,
            "include_failed": include_failed,
            "excluded": filtered_out,
        },
        "source_statistics": source_stats,
        "domain_distribution": domain_dist,
        "difficulty_distribution": difficulty_dist,
        "verdict_distribution": verdict_dist,
        "source_distribution": source_dist,
        "system_prompt_sha256": hashlib.sha256(
            ATAN_V1_SYSTEM_PROMPT.encode("utf-8")
        ).hexdigest()[:16],
        "output_files": {
            "train": str(train_path),
            "val": str(val_path),
        },
    }

    report_path = output_dir / "agent_trajectories_metadata.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote metadata: {report_path}", file=sys.stderr)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build atan-v1 agent trajectory training dataset from SWE-agent trajectories.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for SFT data files.",
    )
    parser.add_argument(
        "--min-messages",
        type=int,
        default=MIN_MESSAGES,
        help="Minimum number of messages in a trajectory to include.",
    )
    parser.add_argument(
        "--max-trajectories",
        type=int,
        default=None,
        help="Maximum trajectories to include (None = all qualifying).",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.1,
        help="Validation split ratio.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for splitting.",
    )
    parser.add_argument(
        "--include-failed",
        action="store_true",
        help="Include failed trajectories (default: exclude).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze sources without writing output.",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN — analyzing sources only...", file=sys.stderr)
        for source in TRAJECTORY_SOURCES:
            path = Path(source["path"])
            if not path.exists():
                print(f"  SKIP (not found): {path}", file=sys.stderr)
                continue
            count = sum(1 for _ in path.open(encoding="utf-8"))
            print(f"  {source['name']}: {count} records at {path}", file=sys.stderr)
        return 0

    report = build_trajectories(
        output_dir=args.output_dir,
        min_messages=args.min_messages,
        max_trajectories=args.max_trajectories,
        val_ratio=args.val_ratio,
        seed=args.seed,
        include_failed=args.include_failed,
    )

    print("\n" + "=" * 60, file=sys.stderr)
    print("SUMMARY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  Total trajectories: {report['total_records']}", file=sys.stderr)
    print(f"  Train: {report['train_records']}", file=sys.stderr)
    print(f"  Val: {report['val_records']}", file=sys.stderr)
    print(f"  Domains: {report['domain_distribution']}", file=sys.stderr)
    print(f"  Difficulty: {report['difficulty_distribution']}", file=sys.stderr)
    print(f"  Verdicts: {report['verdict_distribution']}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
