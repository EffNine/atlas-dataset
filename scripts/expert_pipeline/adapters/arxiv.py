"""ArXiv cs.LG / cs.CL / cs.AI / stat.ML adapter (expert-aiml-001).

Pulls newest submissions per primary category via the arXiv API, filters to
primary category, checks abs pages for retraction markers, and converts each
paper to an abstract-grounded Atlas Expert Record.

Mirrors the validated transformation in
reports/expert_pilot_sample_calibration_arxiv_v0.1.json (GO).
"""

from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
from typing import Any, Iterator

from .base import SourceAdapter
from ..util import utc_now_iso

API_BASE = "https://export.arxiv.org/api/query"
CATEGORIES = ["cs.LG", "cs.CL", "cs.AI", "stat.ML"]
PAGE_SIZE = 500          # arXiv API page size (max 2000 per query; 500 is conservative)
MAX_PAGES_PER_CAT = 20   # safety cap (~10k raw entries per category)
DIFFICULTY_DEFAULT = 2

RETRACTION_MARKERS = ("retracted", "withdrawn", "this paper has been retracted", "retraction notice")


def _unescape(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\n", " ").replace("\r", " ")).strip()


def _http_get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "atlas-expert-pilot/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _query_arxiv(category: str, start: int = 0, max_results: int = PAGE_SIZE) -> list[dict]:
    params = {
        "search_query": f"cat:{category}",
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = API_BASE + "?" + urllib.parse.urlencode(params)
    xml = _http_get(url)
    entries = []
    for em in re.finditer(r"<entry>(.*?)</entry>", xml, re.S):
        e = em.group(1)

        def grab(tag: str) -> str:
            m = re.search(rf"<{tag}>(.*?)</{tag}>", e, re.S)
            return _unescape(m.group(1)) if m else ""

        def grab_arxiv(tag: str) -> str:
            m = re.search(rf"<arxiv:{tag}[^>]*>(.*?)</arxiv:{tag}>", e, re.S)
            return _unescape(m.group(1)) if m else ""

        pid = grab("id").strip().rstrip("/").split("/abs/")[-1]
        primary_m = re.search(r'<arxiv:primary_category[^>]*term="([^"]+)"', e)
        entries.append({
            "arxiv_id": pid,
            "title": grab("title"),
            "abstract": grab("summary"),
            "published": grab("published"),
            "updated": grab("updated"),
            "primary_category": primary_m.group(1) if primary_m else "",
            "categories": re.findall(r'<category term="([^"]+)"', e),
            "authors": [_unescape(a) for a in re.findall(r"<name>(.*?)</name>", e, re.S)],
            "comment": grab_arxiv("comment"),
            "doi": grab_arxiv("doi"),
            "journal_ref": grab_arxiv("journal_ref"),
        })
    return entries


def _check_retraction(abs_url: str) -> dict:
    try:
        html = _http_get(abs_url, timeout=30).lower()
    except Exception as e:  # noqa: BLE001
        return {"checked": False, "reason": f"fetch error: {e!r}"}
    markers = sorted({kw for kw in RETRACTION_MARKERS if kw in html})
    return {"checked": True, "retraction_markers": markers}


def _derive_problem(paper: dict) -> str:
    year = (paper["published"] or "")[:4] or "unknown"
    first_author = paper["authors"][0] if paper["authors"] else "unknown"
    return (
        f"Explain the core contribution and methodology of the paper "
        f"'{paper['title']}' (arXiv:{paper['arxiv_id']}, {year}) by "
        f"{first_author} et al. Ground your explanation in the abstract."
    )


def _derive_subdomains(paper: dict) -> list[str]:
    subs = []
    for c in paper["categories"]:
        c = c.lower()
        if "cs.cl" in c or c.startswith("cl"):
            subs.append("nlp")
        elif "cs.lg" in c or c.startswith("lg"):
            subs.append("machine-learning")
        elif "cs.ai" in c or c.startswith("ai"):
            subs.append("ai")
        elif "stat.ml" in c:
            subs.append("ml-theory")
    if not subs:
        subs = ["ai-machine-learning"]
    title_l = paper["title"].lower()
    for kw, tag in (("transform", "transformers"), ("rag", "rag"), ("retrieval", "retrieval"),
                    ("diffusion", "diffusion"), ("llm", "llm"), ("large language", "llm"),
                    ("agent", "agents"), ("multimodal", "multimodal")):
        if kw in title_l and tag not in subs:
            subs.append(tag)
    return subs[:5]


class ArxivAdapter(SourceAdapter):
    source_id = "expert-aiml-001"
    source_name = "ArXiv cs.LG / cs.CL / cs.AI / stat.ML"
    source_url = "https://arxiv.org"
    source_license = "arXiv non-exclusive license"
    domain = "ai_machine_learning"
    expert_tier = "E1"
    id_prefix = "expert_aiml_arxiv"
    stream_source = "arXiv API (newest per primary category, abstract-grounded)"

    def iter_raw(self, limit: int | None = None) -> Iterator[dict]:
        """Yield primary-category papers, paginating per category until limit.

        Distributes the requested total evenly across CATEGORIES. With
        limit=None it targets 3000 records (the pilot allocation).
        """
        total_target = limit if limit is not None else 3000
        per_cat = -(-total_target // len(CATEGORIES))  # ceil division
        yielded = 0
        for cat in CATEGORIES:
            start = 0
            cat_yielded = 0
            for _ in range(MAX_PAGES_PER_CAT):
                entries = _query_arxiv(cat, start=start, max_results=PAGE_SIZE)
                for e in entries:
                    if e["primary_category"] != cat:
                        continue
                    yield e
                    yielded += 1
                    cat_yielded += 1
                    if yielded >= total_target:
                        return
                    if cat_yielded >= per_cat:
                        break
                if cat_yielded >= per_cat or not entries:
                    break
                start += PAGE_SIZE
                time.sleep(1.5)  # be polite to arXiv API

    def to_record(self, raw: dict, idx: int) -> dict:
        paper = raw
        arxiv_id = paper["arxiv_id"]
        year = (paper["published"] or "")[:4] or "unknown"
        author_str = ", ".join(paper["authors"][:6]) if paper["authors"] else "unknown"
        context = (
            f"Title: {paper['title']}\n"
            f"Authors: {author_str}\n"
            f"Primary category: {paper['primary_category']}\n"
            f"Categories: {', '.join(paper['categories'])}\n"
            f"Published: {paper['published']}\n"
            f"Abstract:\n{paper['abstract']}"
        )
        attribution = f"arXiv:{arxiv_id} '{paper['title']}' by {author_str} ({year}). arXiv non-exclusive license."

        return {
            "id": f"{self.id_prefix}_{idx:04d}",
            "domain": self.domain,
            "expert_tier": self.expert_tier,
            "difficulty": DIFFICULTY_DEFAULT,
            "type": "reasoning",
            "source": {
                "source_id": self.source_id,
                "name": self.source_name,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "license": self.source_license,
                "accessed_at": self.accessed_at,
                "version": f"arXiv {arxiv_id} (published {paper['published']})",
            },
            "license": self.source_license,
            "attribution": attribution,
            "problem": _derive_problem(paper),
            "context": context,
            "solution": paper["abstract"],
            "verification": {
                "method": "peer_review",
                "status": "needs_review",
                "evidence": f"arXiv:{arxiv_id}; authors={author_str[:120]}; year={year}",
                "reviewer": None,
                "reviewed_at": None,
            },
            "provenance": {
                "original_id": arxiv_id,
                "ingestion_pipeline": "atlas-expert-pilot-6500-v0.1",
                "transformations": ["arxiv_api_fetch", "metadata_normalize", "abstract_extract", "schema_v0.1_map", "quality_calibration_score"],
                "difficulty_classifier_version": None,
                "expert_layer_version": "0.1.0",
            },
            "metadata": {
                "language": "en",
                "subdomains": _derive_subdomains(paper),
                "quality_score": None,
                "synthetic": False,
                "model_generated": False,
                "notes": "Pilot record; pre-review (curated=False). Abstract-grounded solution; no full-text ingestion.",
            },
            "extraction": {
                "arxiv_id": arxiv_id,
                "title": paper["title"],
                "published": paper["published"],
                "primary_category": paper["primary_category"],
                "categories": paper["categories"],
                "author_count": len(paper["authors"]),
                "abstract_len": len(paper["abstract"]),
                "retraction_check": _check_retraction(f"https://arxiv.org/abs/{arxiv_id}"),
            },
            "messages": [
                {"role": "user", "content": _derive_problem(paper) + "\n\n" + context},
                {"role": "assistant", "content": paper["abstract"]},
            ],
            "created_at": utc_now_iso(),
            "curated": False,
        }
