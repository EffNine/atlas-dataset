"""Local SWE-smith agent-trajectory adapter (expert-agentic-001, MIT).

Converts already-acquired raw agent trajectories (raw/p0|p1/staging/*swe-smith*)
into Atlas Expert Records. Structural gates applied at iteration time
(fail-closed, deterministic order):

  - >= MIN_MESSAGES non-system messages
  - >= MIN_OBSERVATIONS tool interactions (<returncode / OBSERVATION: markers)
  - conversation ends on an assistant turn
  - completion verdict == completed (success indicators present, no trailing
    unresolved traceback) — failed/inconclusive episodes are excluded from SFT
    seeds and counted

Honesty notes:
- upstream per-record `verified` flag is almost always False despite registry
  wording; verification.status reflects that flag, never assumes it.
- records are model-generated agent traces: metadata.model_generated=True,
  synthetic=True.
- canonical format keeps [user, ...] messages without any system prompt;
  upstream system content is preserved in record.context instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from .base import SourceAdapter
from ..util import sha256_hex, utc_now_iso

REPO_ROOT = Path(__file__).resolve().parents[3]  # adapters/ -> expert_pipeline/ -> scripts/ -> repo
RAW_PATHS = [
    REPO_ROOT / "raw" / "p0" / "staging" / "p0-swe-smith-trajectories.jsonl",
    REPO_ROOT / "raw" / "p0" / "staging" / "p0-swe-smith-mini.jsonl",
    REPO_ROOT / "raw" / "p1" / "staging" / "p1-swe-smith-mini.jsonl",
]

MIN_MESSAGES = 10
MIN_OBSERVATIONS = 2


def split_system(messages: list[dict]) -> tuple[list[dict], str]:
    """Return (non-system messages, folded system text)."""
    sys_text = "\n\n".join(
        (m.get("content") or "") for m in messages if m.get("role") == "system"
    ).strip()
    rest = [m for m in messages if m.get("role") != "system"]
    return rest, sys_text


def count_observations(messages: list[dict]) -> int:
    n = 0
    for m in messages:
        if m.get("role") != "user":
            continue
        c = (m.get("content") or "").strip()
        if c.startswith("<returncode") or c.startswith("OBSERVATION:"):
            n += 1
    return n


def completion_verdict(messages: list[dict]) -> str:
    """Mirrors agent_trajectory_builder conventions: success indicators vs tracebacks."""
    success_words = ("fixed", "resolved", "all tests passing", "completed",
                     "successfully", "working", "verified", "correct")
    has_success = False
    has_traceback = False
    for m in messages:
        if m.get("role") != "assistant":
            continue
        low = (m.get("content") or "").lower()
        if any(w in low for w in success_words):
            has_success = True
        if "traceback" in low:
            has_traceback = True
    if has_success:
        return "completed"
    if has_traceback:
        return "failed"
    return "inconclusive"


def difficulty_from_observations(n_obs: int) -> int:
    # Documented heuristic (mirrors agent_trajectory_builder).
    if n_obs >= 20:
        return 4
    if n_obs >= 10:
        return 3
    if n_obs >= 5:
        return 2
    return 1


def structural_gate(non_system: list[dict], n_obs: int, verdict: str) -> str | None:
    """Return a rejection reason, or None if the trajectory qualifies."""
    if len(non_system) < MIN_MESSAGES:
        return "too_few_messages"
    if n_obs < MIN_OBSERVATIONS:
        return "too_few_observations"
    if not non_system or non_system[-1].get("role") != "assistant":
        return "does_not_end_on_assistant"
    if verdict != "completed":
        return f"verdict_{verdict}"
    return None


class AgenticLocalAdapter(SourceAdapter):
    source_id = "expert-agentic-001"
    source_name = "SWE-smith agent trajectories"
    source_url = "https://huggingface.co/datasets/Kwai-Klear/SWE-smith-mini_swe_agent_plus-trajectories-66k"
    source_license = "MIT"
    domain = "software_engineering"
    expert_tier = "E2"
    id_prefix = "expert_agentic"
    stream_source = "local raw/p0+p1 staging swe-smith trajectory JSONL"

    def __init__(self, accessed_at: str | None = None,
                 paths: list[Path] | None = None) -> None:
        super().__init__(accessed_at=accessed_at)
        self.paths = [Path(p) for p in (paths or RAW_PATHS)]

    @staticmethod
    def _display_path(path: Path) -> str:
        try:
            return str(path.relative_to(REPO_ROOT))
        except ValueError:
            return str(path)

    def iter_raw(self, limit: int | None = None) -> Iterator[dict]:
        yielded = 0
        skip_reasons: dict[str, int] = {}
        for path in self.paths:
            if not path.exists():
                continue
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if limit is not None and yielded >= limit:
                        return
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except ValueError:
                        skip_reasons["bad_json"] = skip_reasons.get("bad_json", 0) + 1
                        continue
                    non_system, _ = split_system(raw.get("messages") or [])
                    n_obs = count_observations(non_system)
                    verdict = completion_verdict(non_system)
                    reason = structural_gate(non_system, n_obs, verdict)
                    if reason:
                        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                        continue
                    raw["_stats"] = {
                        "observations": n_obs,
                        "verdict": verdict,
                        "messages": len(non_system),
                        "source_file": self._display_path(path),
                        "skipped_before_yield": dict(skip_reasons),
                    }
                    yield raw
                    yielded += 1

    def to_record(self, raw: dict, idx: int) -> dict:
        messages = raw.get("messages") or []
        non_system, sys_text = split_system(messages)
        stats = raw.get("_stats") or {}
        n_obs = stats.get("observations", count_observations(non_system))
        verdict = stats.get("verdict", completion_verdict(non_system))
        first_user = next((m for m in non_system if m.get("role") == "user"), {})
        last_assistant = next(
            (m for m in reversed(non_system) if m.get("role") == "assistant"), {})
        problem = (first_user.get("content") or "").strip()
        solution = (last_assistant.get("content") or "").strip()

        context_parts = []
        if sys_text:
            context_parts.append(f"[upstream system]\n{sys_text[:1500]}")
        context_parts.append(
            f"episode: {stats.get('messages', len(non_system))} turns, "
            f"{n_obs} tool observations, verdict={verdict}")
        context = "\n\n".join(context_parts)

        upstream_verified = bool(raw.get("verified"))
        oid = raw.get("id") or self.original_id(raw, problem, solution)

        return {
            "id": f"{self.id_prefix}_{idx:06d}",
            "domain": self.domain,
            "expert_tier": self.expert_tier,
            "difficulty": difficulty_from_observations(n_obs),
            "type": "code",
            "source": {
                "source_id": self.source_id,
                "name": self.source_name,
                "url": self.source_url,
                "license": self.source_license,
                "accessed_at": self.accessed_at,
                "version": f"local staging snapshot ({stats.get('source_file', '?')})",
            },
            "license": self.source_license,
            "attribution": (
                "SWE-smith agent trajectories (Kwai-Klear/SWE-smith-mini_"
                "swe_agent_plus-trajectories-66k), MIT-licensed."
            ),
            "problem": problem,
            "context": context,
            "solution": solution,
            "verification": {
                "method": "auto_grader",
                "status": "verified" if upstream_verified else "unverified",
                "evidence": (
                    f"upstream_verified={upstream_verified}; final_verdict={verdict}; "
                    f"observations={n_obs}"
                ),
                "reviewer": None,
                "reviewed_at": None,
            },
            "provenance": {
                "original_id": oid if oid.startswith(self.source_id.replace('-', '_'))
                else f"{self.source_id}:{oid}",
                "ingestion_pipeline": "atlas-expert-agentic-v0.1",
                "transformations": [
                    "local_raw_stream",
                    "system_message_folded_to_context",
                    "structural_gates",
                    "schema_v0.1_map",
                    "quality_calibration_score",
                ],
                "difficulty_classifier_version": None,
                "expert_layer_version": "0.1.0",
            },
            "metadata": {
                "language": raw.get("language") or "en",
                "subdomains": ["agentic", "tool-use",
                               (raw.get("subcategory") or "swe-agent")],
                "quality_score": None,
                "synthetic": True,
                "model_generated": True,
                "notes": (
                    "Pre-review (curated=False). Model-generated agent episode on "
                    "real repo; completion-verdict gated at ingestion."
                ),
            },
            "extraction": {
                "source_file": stats.get("source_file"),
                "category": raw.get("category"),
                "subcategory": raw.get("subcategory"),
                "turn_count": len(non_system),
                "observation_count": n_obs,
                "final_verdict": verdict,
                "has_error_markers": any(
                    "traceback" in (m.get("content") or "").lower() for m in non_system),
                "messages_len_chars": sum(len(m.get("content") or "") for m in non_system),
            },
            "messages": non_system,
            "created_at": utc_now_iso(),
            "curated": False,
        }
