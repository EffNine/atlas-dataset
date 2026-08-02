"""OpenMathInstruct-2 adapter (expert-math-002, CC-BY-4.0).

Streams nvidia/OpenMathInstruct-2 train split and converts each row to an
Atlas Expert Record. Solutions are model-generated (Llama3.1-405B-Instruct,
per NVIDIA README) so metadata.model_generated=true and synthetic=true.

Mirrors the validated transformation in
reports/expert_pilot_sample_calibration_openmath_v0.1.json (GO).
"""

from __future__ import annotations

from typing import Any, Iterator

from .base import SourceAdapter
from ..util import utc_now_iso


def difficulty_from_problem(problem: str) -> int:
    # Calibration heuristic (documented): problem length as complexity proxy.
    n = len(problem or "")
    if n >= 600:
        return 4
    if n >= 300:
        return 3
    return 2


class OpenMathAdapter(SourceAdapter):
    source_id = "expert-math-002"
    source_name = "OpenMathInstruct-2"
    source_url = "https://huggingface.co/datasets/nvidia/OpenMathInstruct-2"
    source_license = "CC-BY-4.0"
    domain = "mathematics"
    expert_tier = "E2"
    id_prefix = "expert_math"
    stream_source = "nvidia/OpenMathInstruct-2 (train split, 13,972,791 instances)"

    def iter_raw(self, limit: int | None = None) -> Iterator[dict]:
        from datasets import load_dataset

        ds = load_dataset("nvidia/OpenMathInstruct-2", split="train", streaming=True)
        it = iter(ds)
        for _ in range(limit if limit is not None else 3000):
            try:
                yield next(it)
            except StopIteration:
                return

    def to_record(self, raw: dict, idx: int) -> dict:
        problem = raw.get("problem") or ""
        solution = raw.get("generated_solution") or ""
        expected_answer = raw.get("expected_answer") or ""
        problem_source = raw.get("problem_source") or ""
        if not problem_source:
            problem_source = "unknown"

        return {
            "id": f"{self.id_prefix}_{idx:06d}",
            "domain": self.domain,
            "expert_tier": self.expert_tier,
            "difficulty": difficulty_from_problem(problem),
            "type": "qa",
            "source": {
                "source_id": self.source_id,
                "name": self.source_name,
                "url": self.source_url,
                "license": self.source_license,
                "accessed_at": self.accessed_at,
                "version": "nvidia/OpenMathInstruct-2 train split, stream snapshot",
            },
            "license": self.source_license,
            "attribution": "NVIDIA. OpenMathInstruct-2 is CC-BY-4.0 licensed.",
            "problem": problem,
            "context": f"Problem source: {problem_source}\nExpected answer: {expected_answer}",
            "solution": solution,
            "verification": {
                "method": "verified_solution_set",
                "status": "needs_review",
                "evidence": f"problem_source={problem_source}; expected_answer_present={bool(expected_answer.strip())}",
                "reviewer": None,
                "reviewed_at": None,
            },
            "provenance": {
                "original_id": self.original_id(raw, problem, solution),
                "ingestion_pipeline": "atlas-expert-pilot-6500-v0.1",
                "transformations": ["raw_stream", "row_to_example", "schema_v0.1_map", "quality_calibration_score"],
                "difficulty_classifier_version": None,
                "expert_layer_version": "0.1.0",
            },
            "metadata": {
                "language": "en",
                "subdomains": ["math", "chain-of-thought", problem_source.lower().replace("_", "-")],
                "quality_score": None,
                "synthetic": True,
                "model_generated": True,
                "notes": "Pilot record; pre-review (curated=False). model_generated=True per NVIDIA README.",
            },
            "extraction": {
                "problem_source": problem_source,
                "has_expected_answer": bool(expected_answer.strip()),
                "expected_answer_head": expected_answer[:80] if expected_answer else None,
                "problem_len": len(problem),
                "solution_len": len(solution),
            },
            "messages": [
                {"role": "user", "content": problem},
                {"role": "assistant", "content": solution},
            ],
            "created_at": utc_now_iso(),
            "curated": False,
        }
