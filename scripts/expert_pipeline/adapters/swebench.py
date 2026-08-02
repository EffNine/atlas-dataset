"""SWE-bench Verified adapter (expert-swe-001, MIT).

Streams the verified test split (500 instances) and converts each instance
to an Atlas Expert Record with gold-patch verification.

Mirrors the validated transformation in the Phase 0.5 calibration script
(reports/expert_pilot_sample_calibration_swe_v0.2.json, GO).
"""

from __future__ import annotations

from typing import Any, Iterator

from .base import SourceAdapter
from ..util import extract_files, parse_list_field, utc_now_iso

# SWE-bench Verified difficulty time-label -> Atlas 1-5 scale (documented mapping)
DIFFICULTY_MAP = {
    "<15 min fix": 2,
    "15 min - 1 hour": 3,
    "1-4 hours": 4,
    ">4 hours": 5,
}
DIFFICULTY_DEFAULT = 3


class SwebenchAdapter(SourceAdapter):
    source_id = "expert-swe-001"
    source_name = "SWE-bench verified"
    source_url = "https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified"
    source_license = "MIT"
    domain = "software_engineering"
    expert_tier = "E2"
    id_prefix = "expert_swe"
    stream_source = "SWE-bench/SWE-bench_Verified (test split, 500 instances)"

    def iter_raw(self, limit: int | None = None) -> Iterator[dict]:
        from datasets import load_dataset

        ds = load_dataset("SWE-bench/SWE-bench_Verified", split="test", streaming=True)
        it = iter(ds)
        for _ in range(limit if limit is not None else 500):
            try:
                yield next(it)
            except StopIteration:
                return

    def to_record(self, raw: dict, idx: int) -> dict:
        inst_id = raw.get("instance_id") or ""
        problem = raw.get("problem_statement") or ""
        patch = raw.get("patch") or ""
        repo = raw.get("repo") or ""
        base_commit = raw.get("base_commit") or ""
        ftp = parse_list_field(raw.get("FAIL_TO_PASS"))
        ptp = parse_list_field(raw.get("PASS_TO_PASS"))
        files = extract_files(patch)

        diff_label = raw.get("difficulty")
        difficulty = DIFFICULTY_MAP.get(diff_label, DIFFICULTY_DEFAULT)

        context_parts = [f"Repository: {repo}", f"Base commit: {base_commit}"]
        if files:
            context_parts.append("Files touched: " + ", ".join(files))
        if ftp:
            context_parts.append("Failing tests: " + "; ".join(str(t) for t in ftp[:20]))
        context = "\n".join(context_parts)

        evidence = f"FAIL_TO_PASS={len(ftp)}, PASS_TO_PASS={len(ptp)}"

        return {
            "id": f"{self.id_prefix}_{idx:06d}",
            "domain": self.domain,
            "expert_tier": self.expert_tier,
            "difficulty": difficulty,
            "type": "qa",
            "source": {
                "source_id": self.source_id,
                "name": self.source_name,
                "url": self.source_url,
                "license": self.source_license,
                "accessed_at": self.accessed_at,
                "version": "SWE-bench/SWE-bench_Verified test split, stream snapshot",
            },
            "license": self.source_license,
            "attribution": "Princeton NLP. SWE-bench is MIT-licensed.",
            "problem": problem,
            "context": context,
            "solution": patch,
            "verification": {
                "method": "gold_patch",
                "status": "verified",
                "evidence": evidence,
                "reviewer": None,
                "reviewed_at": None,
            },
            "provenance": {
                "original_id": inst_id,
                "ingestion_pipeline": "atlas-expert-pilot-6500-v0.1",
                "transformations": ["raw_stream", "instance_to_example", "schema_v0.1_map", "quality_calibration_score"],
                "difficulty_classifier_version": None,
                "expert_layer_version": "0.1.0",
            },
            "metadata": {
                "language": "en",
                "subdomains": ["debugging", "patch-generation", (repo.split("/")[-1] if repo else "unknown")],
                "quality_score": None,
                "synthetic": False,
                "model_generated": False,
                "notes": "Pilot record; pre-review (curated=False).",
            },
            "extraction": {
                "repo": repo,
                "base_commit": base_commit,
                "difficulty_label": diff_label,
                "has_hints": bool(raw.get("hints_text")),
                "has_test_patch": bool((raw.get("test_patch") or "").strip()),
                "has_patch": bool(patch.strip()),
                "has_problem": bool(problem.strip()),
                "fail_to_pass_count": len(ftp),
                "pass_to_pass_count": len(ptp),
                "files_changed": files,
                "fail_to_pass": [str(t) for t in ftp[:20]],
                "pass_to_pass": [str(t) for t in ptp[:20]],
            },
            "messages": [
                {"role": "user", "content": problem + ("\n\n" + context if context else "")},
                {"role": "assistant", "content": patch},
            ],
            "created_at": utc_now_iso(),
            "curated": False,
        }
