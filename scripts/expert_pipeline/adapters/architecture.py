"""Kubernetes Enhancement Proposals adapter (expert-arch-001, Apache-2.0).

Streams KEP README documents from kubernetes/enhancements and converts each
into an Atlas Expert Record: the KEP motivation becomes the problem, and the
proposal / design / alternatives sections become the solution. Upstream text
is used verbatim (expert-authored, SIG-reviewed); no text generation.

License verified via the GitHub API (Apache-2.0, spdx_id confirmed) on
2026-08-22; recorded in metadata/source_registry.json with status "review".

Network notes:
- Listing uses one recursive git-trees API call; fetching uses the contents
  API with an application/vnd.github.raw accept header.
- Unauthenticated GitHub API allows ~60 requests/hour. Set GITHUB_TOKEN or
  GH_TOKEN in the environment for authenticated (5000/hour) pulls.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Iterator

from .base import SourceAdapter
from ..util import utc_now_iso

REPO = "kubernetes/enhancements"
BRANCH = "main"
TREES_URL = f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1"
CONTENTS_URL = f"https://api.github.com/repos/{REPO}/contents/"
DEFAULT_LIMIT = 100

# keps/sig-<sig>/NNNN-<slug>/README.md  (kep-template dir excluded)
KEP_README_RE = re.compile(
    r"^keps/(sig-[a-z0-9-]+/(?!0000-kep-template/)\d{4}-[a-z0-9-]+)/README\.md$")
TEMPLATE_KEP_DIR = "0000-kep-template"
TITLE_RE = re.compile(r"^#\s*KEP-(\d+):\s*(.+?)\s*$")

# Canonical H2 sections of the KEP template we map onto the record.
SECTION_PROBLEM = "Motivation"
SECTION_SUMMARY = "Summary"
SECTION_SOLUTION = ("Proposal", "Design Details", "Alternatives", "Drawbacks")
CONTEXT_SUMMARY_CAP = 1200


def _http_get(url: str, timeout: int = 30, headers: dict[str, str] | None = None) -> str:
    req_headers = {"User-Agent": "atlas-expert-pipeline/0.1"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        req_headers["Authorization"] = f"Bearer {token}"
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _list_kep_paths_via_trees() -> list[str]:
    """One recursive git-trees call (cheapest, but blocked/truncated on some
    networks and proxies)."""
    try:
        data = json.loads(_http_get(TREES_URL))
    except ValueError as e:
        raise RuntimeError(
            "could not decode GitHub trees response (rate limited?). "
            "Set GITHUB_TOKEN/GH_TOKEN and retry."
        ) from e
    if data.get("truncated"):
        raise RuntimeError("git trees response truncated")
    paths = []
    for blob in data.get("tree", []):
        if blob.get("type") != "blob":
            continue
        m = KEP_README_RE.match(blob.get("path", ""))
        if m:
            paths.append(m.group(0))
    return sorted(paths)


def _list_kep_paths_via_walk() -> list[str]:
    """Directory walk over the contents API (~#sig-dirs + 1 requests).
    Used when the git-trees endpoint is unavailable or truncated.

    Note: no ?ref= query string is sent — the contents API defaults to the
    repository's default branch (BRANCH), and query strings are mangled by
    some egress proxies."""
    try:
        sig_entries = json.loads(_http_get(f"{CONTENTS_URL}keps"))
    except ValueError as e:
        raise RuntimeError(
            "could not decode GitHub contents response (rate limited?). "
            "Set GITHUB_TOKEN/GH_TOKEN and retry."
        ) from e
    paths: list[str] = []
    for sig in sig_entries:
        name = sig.get("name", "")
        if sig.get("type") != "dir" or not name.startswith("sig-"):
            continue
        children = json.loads(_http_get(f"{CONTENTS_URL}keps/{name}"))
        for child in children:
            cname = child.get("name", "")
            if (child.get("type") == "dir" and cname != TEMPLATE_KEP_DIR
                    and re.match(r"^\d{4}-", cname)):
                paths.append(f"keps/{name}/{cname}/README.md")
    return sorted(paths)


def _list_kep_paths() -> list[str]:
    """Deterministic, sorted list of KEP README paths."""
    try:
        return _list_kep_paths_via_trees()
    except (urllib.error.URLError, RuntimeError, ValueError, KeyError):
        return _list_kep_paths_via_walk()


def _fetch_kep(path: str) -> str:
    # No ?ref= — defaults to the default branch; query strings break behind
    # some egress proxies.
    return _http_get(f"{CONTENTS_URL}{path}",
                     headers={"Accept": "application/vnd.github.raw"})


def parse_kep_slug(path: str) -> tuple[str, str]:
    """'keps/sig-arch/1659-standard-topology-labels/README.md'
    -> ('sig-arch', '1659-standard-topology-labels')."""
    m = KEP_README_RE.match(path)
    if not m:
        raise ValueError(f"not a KEP readme path: {path}")
    sig, kep_dir = m.group(1).split("/", 1)
    return sig, kep_dir


def parse_title(markdown: str, kep_dir: str) -> str:
    for line in markdown.splitlines():
        m = TITLE_RE.match(line)
        if m:
            return m.group(2)
    return kep_dir


def parse_sections(markdown: str) -> dict[str, str]:
    """Map of H2 heading -> body text (sub-headings kept inside the body)."""
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in markdown.splitlines():
        if re.match(r"^##\s+\S", line):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = re.sub(r"^##\s+", "", line).strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def find_section(sections: dict[str, str], name: str) -> str:
    for key, body in sections.items():
        if key.lower() == name.lower():
            return body
    return ""


def difficulty_from_sections(design_len: int, has_alternatives: bool) -> int:
    # Documented heuristic: design-complexity proxy (same style as the
    # OpenMath length-based calibration).
    d = 2
    if has_alternatives or design_len >= 2500:
        d = 3
    if design_len >= 8000:
        d = 4
    return d


def build_problem_solution(sections: dict[str, str]) -> tuple[str, str]:
    """Faithful problem/solution mapping from upstream sections."""
    problem = find_section(sections, SECTION_PROBLEM) or find_section(sections, SECTION_SUMMARY)
    parts: list[str] = []
    for name in SECTION_SOLUTION:
        body = find_section(sections, name)
        if body:
            parts.append(f"## {name}\n\n{body}")
    return problem.strip(), "\n\n".join(parts)


class KepAdapter(SourceAdapter):
    source_id = "expert-arch-001"
    source_name = "Kubernetes Enhancement Proposals"
    source_url = f"https://github.com/{REPO}"
    source_license = "Apache-2.0"
    # expert_record_schema_v0.1 has no dedicated architecture domain;
    # software_engineering + architecture subdomains is the faithful mapping.
    domain = "software_engineering"
    expert_tier = "E2"
    id_prefix = "expert_arch"
    stream_source = f"{REPO} (keps/**/README.md via GitHub contents API)"

    def iter_raw(self, limit: int | None = None) -> Iterator[dict]:
        effective = limit if limit else DEFAULT_LIMIT
        n = 0
        for path in _list_kep_paths():
            if n >= effective:
                return
            sig, kep_dir = parse_kep_slug(path)
            try:
                markdown = _fetch_kep(path)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    continue  # KEP dir without a README; skip, not fatal
                raise
            sections = parse_sections(markdown)
            problem, solution = build_problem_solution(sections)
            if not problem.strip() or not solution.strip():
                continue  # skip empty/template docs rather than emit hollow records
            yield {
                "path": path,
                "sig": sig,
                "kep_dir": kep_dir,
                "title": parse_title(markdown, kep_dir),
                "markdown": markdown,
                "sections": sections,
                "problem": problem,
                "solution": solution,
            }
            n += 1

    def to_record(self, raw: dict, idx: int) -> dict:
        sig, kep_dir = raw["sig"], raw["kep_dir"]
        kep_number = kep_dir.split("-", 1)[0]
        title = raw["title"]
        sections = raw["sections"]
        problem, solution = raw["problem"], raw["solution"]

        summary = find_section(sections, SECTION_SUMMARY)
        has_alternatives = bool(find_section(sections, "Alternatives"))
        has_drawbacks = bool(find_section(sections, "Drawbacks"))
        design_len = len(find_section(sections, "Design Details")) + len(
            find_section(sections, "Proposal")
        )

        summary_ctx = summary[:CONTEXT_SUMMARY_CAP]
        context_parts = [
            f"SIG: {sig}",
            f"KEP number: {kep_number}",
            f"Title: {title}",
        ]
        if summary_ctx:
            context_parts.append(f"Summary: {summary_ctx}")
        context = "\n".join(context_parts)

        found = [k for k in sections if k]
        return {
            "id": f"{self.id_prefix}_{idx:06d}",
            "domain": self.domain,
            "expert_tier": self.expert_tier,
            "difficulty": difficulty_from_sections(design_len, has_alternatives),
            "type": "qa",
            "source": {
                "source_id": self.source_id,
                "name": self.source_name,
                "url": self.source_url,
                "license": self.source_license,
                "accessed_at": self.accessed_at,
                "version": f"{REPO}@{BRANCH}, stream snapshot",
            },
            "license": self.source_license,
            "attribution": (
                "Kubernetes SIGs and contributors. kubernetes/enhancements "
                "is Apache-2.0 licensed."
            ),
            "problem": problem,
            "context": context,
            "solution": solution,
            "verification": {
                "method": "peer_review",
                "status": "needs_review",
                "evidence": (
                    f"upstream SIG-reviewed design doc; sections_found={found}; "
                    f"alternatives={has_alternatives}"
                ),
                "reviewer": None,
                "reviewed_at": None,
            },
            "provenance": {
                "original_id": f"{sig}/{kep_dir}",
                "ingestion_pipeline": "atlas-expert-architecture-v0.1",
                "transformations": [
                    "raw_stream",
                    "markdown_section_split",
                    "verbatim_problem_solution_map",
                    "schema_v0.1_map",
                    "quality_calibration_score",
                ],
                "difficulty_classifier_version": None,
                "expert_layer_version": "0.1.0",
            },
            "metadata": {
                "language": "en",
                "subdomains": ["architecture", "design-decisions", sig],
                "quality_score": None,
                "synthetic": False,
                "model_generated": False,
                "notes": "Pre-review (curated=False). Source document used verbatim.",
            },
            "extraction": {
                "source_path": raw["path"],
                "kep_number": kep_number,
                "title": title,
                "sections_found": found,
                "has_summary": bool(summary),
                "has_alternatives": has_alternatives,
                "has_drawbacks": has_drawbacks,
                "motivation_len": len(problem),
                "design_len": design_len,
            },
            "messages": [
                {"role": "user", "content": problem + ("\n\n" + context if context else "")},
                {"role": "assistant", "content": solution},
            ],
            "created_at": utc_now_iso(),
            "curated": False,
        }
