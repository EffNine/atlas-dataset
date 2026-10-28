"""Smoke ingestion pipeline for Source Discovery v1.0.

Flow per source:
  VERIFY METADATA -> DOWNLOAD (small sample) -> HASH -> PARSE -> NORMALIZE
  -> LANGUAGE CHECK + ALIGNMENT CHECK (quality_filter) -> DEDUP
  -> QUALITY FILTER -> stage CORPUS (source-specific staging dir)

Write-safety (hard):
  - All writes go through _guard_write(), which requires the target to sit
    under metadata/source_discovery/ or tmp/source_discovery/ AND pass
    atlas_paths.is_write_safe(). Anything else raises.
  - PROTECTED_PREFIXES (curated/, raw/ except raw/pilot, review_queue/,
    training_views/, releases/, translation-ai-v0.1/, pilot/, artifacts/,
    knowledge_packs/ bulk, existing experiments/) are refused even if the
    generic guard would pass — belt and suspenders for the non-mutation rule.

v1.0 smoke default: opus-100 only, tiny per-language caps, streaming, fully
reversible (delete metadata/source_discovery/staging/<id>/ + tmp files).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atlas_paths import get_root, is_write_safe  # noqa: E402

from .ai2_adapter import review_or_quarantine  # noqa: E402
from .dedup import dedup_by_content  # noqa: E402
from .jev_adapter import build_jev_input, smoke_dataflow  # noqa: E402
from .normalize import normalize_pair  # noqa: E402
from .quality_filter import filter_corpus  # noqa: E402
from .registry import SD_DOMAINS  # noqa: E402

ROOT = get_root()
SD_METADATA = ROOT / "metadata" / "source_discovery"
SD_STAGING = SD_METADATA / "staging"
SD_TMP = ROOT / "tmp" / "source_discovery"

PROTECTED_PREFIXES = (
    "curated", "raw", "review_queue", "training_views", "releases",
    "translation-ai-v0.1", "pilot", "artifacts", "experiments",
    "knowledge_packs",
)
# raw/pilot is the one approved exception — we still refuse it here because
# source-discovery has no business writing pilot seeds.
ALWAYS_REFUSED = PROTECTED_PREFIXES


def _guard_write(target: str | Path) -> Path:
    p = Path(target).resolve()
    rel = None
    try:
        rel = p.relative_to(ROOT.resolve())
    except ValueError:
        raise PermissionError(f"refused write outside repo root: {p}")
    first = rel.parts[0] if rel.parts else ""
    if first in ALWAYS_REFUSED:
        raise PermissionError(
            f"refused write to protected tree {first}/: {p} "
            f"(source-discovery is isolated to metadata/source_discovery/ "
            f"and tmp/source_discovery/)")
    allowed = (SD_METADATA.resolve(), SD_TMP.resolve())
    if not any(str(p).startswith(str(a)) for a in allowed):
        raise PermissionError(f"refused write outside source-discovery roots: {p}")
    if not is_write_safe(p, ROOT):
        raise PermissionError(f"atlas_paths.is_write_safe refused: {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


OPUS_CONFIGS = {"zh": "en-zh", "ja": "en-ja", "ko": "en-ko", "ms": "en-ms"}


def ingest_opus100_sample(per_lang: int = 30) -> dict[str, Any]:
    """Stream a tiny opus-100 sample per language and run the full cheap chain.

    Returns a stats report. Writes staged normalized output per language under
    metadata/source_discovery/staging/opus-100/ (small, reversible).
    """
    from .parsers import hf_stream_sample  # lazy: datasets optional

    entry_meta = {"source_id": "opus-100", "method": "hf_streaming_sample",
                  "per_lang_cap": per_lang}
    try:
        from huggingface_hub import HfApi
        revision = str(HfApi().dataset_info("Helsinki-NLP/opus-100").sha or "")
    except Exception as exc:  # noqa: BLE001 — record, keep going with norev
        revision = ""
        entry_meta["revision_warning"] = (
            f"{type(exc).__name__}: {str(exc)[:200]}")

    all_normalized: list[dict] = []
    per_lang_counts: dict[str, Any] = {}
    for lang, cfg in OPUS_CONFIGS.items():
        try:
            rows, _info = hf_stream_sample("Helsinki-NLP/opus-100", cfg,
                                           "train", per_lang)
        except Exception as exc:  # noqa: BLE001 — per-lang failure is data
            per_lang_counts[lang] = {"error": (
                f"{type(exc).__name__}: {str(exc)[:200]}")}
            continue
        normed = []
        for i, ex in enumerate(rows):
            tr = ex.get("translation", {}) if isinstance(ex, dict) else {}
            src = tr.get(lang, "")
            tgt = tr.get("en", "")
            try:
                normed.append(normalize_pair(
                    src if isinstance(src, str) else "",
                    tgt if isinstance(tgt, str) else "",
                    lang, "en", "opus-100", revision,
                    f"opus100-{cfg}-train-{i:07d}",
                    method="hf_streaming_sample", parser_format="hf_dict"))
            except ValueError as exc:
                normed.append({"id": f"opus-100:malformed:{lang}:{i}",
                               "source_lang": lang, "target_lang": "en",
                               "source": "", "target": "",
                               "source_id": "opus-100",
                               "source_revision": revision,
                               "source_record_id": f"row-{i}",
                               "content_sha256": "",
                               "quality_status": "malformed",
                               "acquisition": {"error": str(exc)[:200]}})
        per_lang_counts[lang] = {"n_streamed": len(normed)}
        all_normalized.extend(normed)

    kept, rejected, fstats = filter_corpus(all_normalized)
    kept2, dups, dstats = dedup_by_content(kept)
    for r in kept2:
        r["quality_status"] = "auto_kept"

    # Stage (small, reversible).
    staged_files = []
    by_lang: dict[str, list[dict]] = {}
    for r in kept2:
        by_lang.setdefault(r.get("source_lang", "?"), []).append(r)
    for lang, recs in by_lang.items():
        outp = _guard_write(SD_STAGING / "opus-100" / f"normalized_{lang}-en.jsonl")
        with open(outp, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        staged_files.append(str(outp.relative_to(ROOT)))
    rejp = _guard_write(SD_STAGING / "opus-100" / "rejected.jsonl")
    with open(rejp, "w", encoding="utf-8") as f:
        for r in rejected:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    staged_files.append(str(rejp.relative_to(ROOT)))

    # JEV boundary check (synthetic smoke only — never on the corpus).
    jev_smoke = smoke_dataflow(n_per_band=2)
    # AI-2 boundary check on up to 3 kept records (no live call).
    ai2_probe = []
    for r in kept2[:3]:
        probe = review_or_quarantine(r["source"], r["target"],
                                     r["source_id"],
                                     f"{r['source_lang']}→en",
                                     "subtitle", allow_live_call=False)
        ai2_probe.append({"id": r["id"], "verdict": probe["verdict"],
                          "quarantine": probe["quarantine"],
                          "blind": probe.get("blind")})
        # Prove JEV-input mapping works on real staged content (no JEV call).
        _ = build_jev_input(r)

    direction_counts = dict(Counter(
        f"{r.get('source_lang')}→{r.get('target_lang')}" for r in kept2))
    return {
        "smoke": "opus-100",
        "acquired_utc": _utcnow(),
        "source_revision": revision,
        "per_lang": per_lang_counts,
        "n_normalized": len(all_normalized),
        "quality_filter": fstats,
        "dedup": dstats,
        "n_usable": len(kept2),
        "by_direction": direction_counts,
        "by_domain": {"subtitle": len(kept2)},
        "staged_files": staged_files,
        "jev_boundary_smoke": {"ok": jev_smoke.get("ok"),
                               "synthetic": jev_smoke.get("synthetic_smoke")},
        "ai2_boundary_probe": ai2_probe,
        "meta": entry_meta,
    }


def corpus_stats(records: list[dict]) -> dict[str, Any]:
    return {
        "n": len(records),
        "by_direction": dict(Counter(
            f"{r.get('source_lang')}→{r.get('target_lang')}" for r in records)),
        "by_source": dict(Counter(r.get("source_id") for r in records)),
    }


def domain_of(source_id: str, registry: list[dict]) -> str:
    for e in registry:
        if e.get("source_id") == source_id:
            d = e.get("domain", "other")
            return d if d in SD_DOMAINS else "other"
    return "other"
