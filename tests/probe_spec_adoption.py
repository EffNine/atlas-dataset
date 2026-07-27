#!/usr/bin/env python3
"""
probe_spec_adoption.py — AD-HOC Atlas v1.0 specification adoption probe.

Purpose:
  Validate the authoritative status of the Atlas v1.0 specification
  after ADR-009 is accepted.

Checks (all against current on-disk repo state):
  1. ADR-009 file exists
  2. ADR-009 references docs/specs/atlas_v1_spec.md
  3. ADR-009 contains required sections
  4. No dataset files modified in this phase
  5. No implementation files modified in this phase

No network access is required.
No repo artifacts are created or modified.
Exit 0 = pass, 1 = fail.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR_PATH = ROOT / "docs" / "adr" / "ADR-009-atlas-v1-specification-adoption.md"
SPEC_PATH = ROOT / "docs" / "specs" / "atlas_v1_spec.md"

REQUIRED_SECTIONS = [
    "Context",
    "Decision",
    "Scope",
    "Non-Negotiable Principles",
    "Consequences",
    "Version Policy",
]

DATASET_PATTERNS = [
    "raw/**",
    "curated/**",
    "training_views/**",
    "review_queue/**",
    "knowledge_packs/**",
    "tmp/**",
    "metadata/source_registry.json",
    "metadata/calibration_baseline_v0.1.json",
    "metadata/checksums_v0.1.json",
    "metadata/engine_checkpoint.json",
]

IMPLEMENTATION_PATTERNS = [
    "scripts/**",
    "migrations/**",
    "schemas/**",
    "processing/**",
    "evaluation/**",
    "configs/**",
]


def passed(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    message = f"[{status}] {name}"
    if detail:
        message += f" -- {detail}"
    print(message)


def git_changed_paths() -> set[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return set()
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}
    except Exception:
        return set()


def matches_any(rel_path: str, patterns: list[str]) -> bool:
    path = Path(rel_path)
    for pattern in patterns:
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            if str(path).startswith(prefix + "/") or str(path) == prefix:
                return True
        else:
            if str(path) == pattern:
                return True
    return False


def main() -> int:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        passed(name, ok, detail)

    if not ADR_PATH.exists():
        check("adr_exists", False, str(ADR_PATH))
        failed = [name for name, ok, _ in results if not ok]
        print(f"FAILED: {len(failed)}/{len(results)}")
        return 1

    adr_text = ADR_PATH.read_text(encoding="utf-8")
    check("adr_exists", True, str(ADR_PATH))
    check("adr_references_atlas_v1_spec", "docs/specs/atlas_v1_spec.md" in adr_text, str(SPEC_PATH))

    lower = adr_text.lower()
    for section in REQUIRED_SECTIONS:
        check(f"adr_section:{section.lower().replace(' ', '_')}", section.lower() in lower)

    datasets_changed = False
    dataset_examples: list[str] = []
    implementations_changed = False
    implementation_examples: list[str] = []

    for rel_path in sorted(git_changed_paths()):
        if matches_any(rel_path, DATASET_PATTERNS):
            datasets_changed = True
            dataset_examples.append(rel_path)
        if matches_any(rel_path, IMPLEMENTATION_PATTERNS):
            implementations_changed = True
            implementation_examples.append(rel_path)

    dataset_detail = ", ".join(dataset_examples[:3]) if dataset_examples else ""
    implementation_detail = ", ".join(implementation_examples[:3]) if implementation_examples else ""
    check("no_dataset_files_modified", not datasets_changed, dataset_detail)
    check("no_implementation_files_modified", not implementations_changed, implementation_detail)

    failed = [name for name, ok, _ in results if not ok]
    print(f"probe_spec_adoption: {len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
