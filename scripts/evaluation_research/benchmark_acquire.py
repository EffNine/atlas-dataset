"""benchmark_acquire.py — Benchmark acquisition via HuggingFace download + cache.

Downloads benchmark data from HuggingFace Hub into the content-addressable
cache, validates schema (problem + canonical_answer fields), and registers
the benchmark in the registry as acquired.

The benchmark data is stored under raw/benchmarks/{benchmark_id}/ and is
never modified after download (immutable after checksum verification).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .benchmark_discover import BenchmarkDiscovery, register_benchmark
from .artifacts import sha256_file


@dataclass
class AcquisitionResult:
    """Result of a benchmark acquisition attempt."""
    benchmark_id: str
    status: str  # acquired | partial | failed
    n_records: int
    files_downloaded: list[str]
    checksums: dict[str, str]
    schema_valid: bool
    schema_errors: list[str]
    license_verified: bool
    acquired_at: str
    cache_dir: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "status": self.status,
            "n_records": self.n_records,
            "files_downloaded": self.files_downloaded,
            "checksums": self.checksums,
            "schema_valid": self.schema_valid,
            "schema_errors": self.schema_errors,
            "license_verified": self.license_verified,
            "acquired_at": self.acquired_at,
            "cache_dir": self.cache_dir,
            "error": self.error,
        }


# Regex to extract problem/answer fields from common benchmark formats
_GSM8K_QUESTION_RE = re.compile(r"^(.+?)\n### Answer$", re.MULTILINE)
_GSM8K_ANSWER_RE = re.compile(r"### Answer\n\s*(.+)$", re.MULTILINE)
_MATH_QUESTION_RE = re.compile(r'"question":\s*"(.+?)"', re.DOTALL)
_MATH_ANSWER_RE = re.compile(r'"level":.*?"solution":\s*"(.+?)"', re.DOTALL)


def _extract_gsm8k_text(text: str) -> tuple[list[str], list[str]]:
    """Extract questions and answers from GSM8K text format."""
    questions, answers = [], []
    blocks = re.split(r"\n### ", text)
    for block in blocks:
        if not block.strip():
            continue
        lines = block.strip().split("\n")
        if len(lines) >= 2 and lines[-1].startswith("Answer"):
            question = "\n".join(lines[:-1]).strip()
            answer_part = lines[-1].replace("Answer:", "").strip()
            # Extract final numeric answer
            nums = re.findall(r"[\d,]+\.\d+|[\d,]+", answer_part)
            final_ans = nums[-1].replace(",", "") if nums else answer_part
            questions.append(question)
            answers.append(final_ans)
    return questions, answers


def _extract_math_json(records: list[dict]) -> tuple[list[str], list[str]]:
    """Extract problem/canonical_answer from MATH dataset JSON format."""
    problems, answers = [], []
    for rec in records:
        q = rec.get("problem", "")
        s = rec.get("solution", "")
        # Extract boxed answer from solution
        boxed = re.search(r"\\boxed\{([^}]+)\}", s)
        ans = boxed.group(1) if boxed else s[:200]
        problems.append(q)
        answers.append(ans)
    return problems, answers


def validate_schema(records: list[dict], benchmark_id: str) -> tuple[bool, list[str]]:
    """Validate that records have required fields for Protocol v2."""
    errors = []
    for i, rec in enumerate(records):
        rid = rec.get("record_id", f"{benchmark_id}_row_{i}")
        if "problem" not in rec or not str(rec.get("problem", "")).strip():
            errors.append(f"{rid}: missing or empty 'problem'")
        if "canonical_answer" not in rec or not str(rec.get("canonical_answer", "")).strip():
            # Try to derive from existing fields
            solution = rec.get("solution", "")
            answer = rec.get("answer", "")
            if solution:
                rec["canonical_answer"] = solution
            elif answer:
                rec["canonical_answer"] = answer
            else:
                errors.append(f"{rid}: missing or empty 'canonical_answer' (and no solution/answer to derive)")
    return len(errors) == 0, errors


def acquire_benchmark(
    benchmark_id: str,
    root: Path | None = None,
    dry_run: bool = False,
) -> AcquisitionResult:
    """Acquire a benchmark from HuggingFace Hub.

    Downloads the benchmark data, validates schema, stores in cache,
    and updates the benchmark registry.

    Returns AcquisitionResult with full provenance.
    """
    if root is None:
        root = Path(__file__).resolve().parent.parent
    from evaluation_research.benchmark_discover import discover_benchmark

    discovery = discover_benchmark(benchmark_id, root)
    if not discovery.license_compatible:
        return AcquisitionResult(
            benchmark_id=benchmark_id,
            status="failed",
            n_records=0,
            files_downloaded=[],
            checksums={},
            schema_valid=False,
            schema_errors=["license not compatible"],
            license_verified=False,
            acquired_at=datetime.now(timezone.utc).isoformat(),
            error=f"License {discovery.license} is denied",
        )

    cache_dir = root / "raw" / "benchmarks" / benchmark_id
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Use HuggingFace adapter to download
    from downloader.adapters.huggingface import HuggingFaceAdapter
    from downloader.cache import CacheManager

    cache = CacheManager(root)
    adapter = HuggingFaceAdapter(cache, config={})

    source = {
        "id": benchmark_id,
        "name": discovery.name,
        "url": discovery.source_url,
        "source_type": "huggingface",
    }

    if dry_run:
        result = adapter.download(source, dry_run=True)
        return AcquisitionResult(
            benchmark_id=benchmark_id,
            status="planned",
            n_records=0,
            files_downloaded=[f["filename"] for f in result.files],
            checksums={},
            schema_valid=True,
            schema_errors=[],
            license_verified=discovery.license_compatible,
            acquired_at=datetime.now(timezone.utc).isoformat(),
        )

    download_result = adapter.download(source, dry_run=False)
    if download_result.status.value != "DOWNLOADED":
        return AcquisitionResult(
            benchmark_id=benchmark_id,
            status="failed",
            n_records=0,
            files_downloaded=[],
            checksums={},
            schema_valid=False,
            schema_errors=[download_result.summary],
            license_verified=discovery.license_compatible,
            acquired_at=datetime.now(timezone.utc).isoformat(),
            error=download_result.summary,
        )

    # Parse downloaded files and extract records
    records = []
    checksums = {}
    for f in download_result.files:
        fp = Path(f.get("local_path", ""))
        if not fp.exists():
            continue
        checksums[f["filename"]] = sha256_file(fp)

        if fp.suffix in (".json", ".jsonl"):
            with fp.open(encoding="utf-8") as fh:
                content = fh.read()
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # Try line-by-line
                for line in content.splitlines():
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            if isinstance(data, dict) and "problem" not in data:
                                data["benchmark_id"] = benchmark_id
                                records.append(data)
                        except json.JSONDecodeError:
                            continue
                continue

            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        item["benchmark_id"] = benchmark_id
                        records.append(item)
            elif isinstance(data, dict):
                data["benchmark_id"] = benchmark_id
                records.append(data)

    # Derive canonical_answer where missing
    for rec in records:
        if "canonical_answer" not in rec or not rec.get("canonical_answer"):
            for src in ("solution", "answer", "result", "final_answer"):
                if src in rec and rec[src]:
                    rec["canonical_answer"] = str(rec[src])
                    break

    # Validate schema
    schema_valid, schema_errors = validate_schema(records, benchmark_id)

    # Store canonical records
    out_path = cache_dir / f"{benchmark_id}_records.jsonl"
    if records and schema_valid:
        out_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8",
        )

    # Update registry
    register_benchmark(root, BenchmarkDiscovery(
        benchmark_id=benchmark_id,
        name=discovery.name,
        source_url=discovery.source_url,
        license=discovery.license,
        license_compatible=True,
        family=discovery.family,
        estimated_n_records=len(records),
        canonical_answer_available=True,
        split=discovery.split,
        status="acquired" if schema_valid else "validated_with_issues",
        provenance_notes=discovery.provenance_notes,
        contamination_risk=discovery.contamination_risk,
        discovered_at=datetime.now(timezone.utc).isoformat(),
    ))

    return AcquisitionResult(
        benchmark_id=benchmark_id,
        status="acquired" if schema_valid else "partial",
        n_records=len(records),
        files_downloaded=[f["filename"] for f in download_result.files],
        checksums=checksums,
        schema_valid=schema_valid,
        schema_errors=schema_errors,
        license_verified=discovery.license_compatible,
        acquired_at=datetime.now(timezone.utc).isoformat(),
        cache_dir=str(cache_dir),
    )
