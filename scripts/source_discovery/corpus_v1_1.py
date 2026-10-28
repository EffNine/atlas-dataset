"""First training corpus build (v1.1) on top of Source Discovery v1.0.

Sources (priority order): hsc-wuxia-100k (ALLOW/MIT) -> tomato-zh2en
(ALLOW/Apache-2.0, ZIP path, MT-derived EN) -> opus-100 bounded (UNKNOWN ->
research-baseline ONLY, never training-ready).

Isolation: writes ONLY under metadata/source_discovery/v1.1/ (manifests,
reports, small stats — tracked) and tmp/source_discovery/v1.1/ (bulk JSONL
staging — gitignored via v1.1/.gitignore). NEVER touches curated/, raw/,
review_queue/, training_views/, releases/, translation-ai-v0.1/, or any
existing Atlas dataset. No training. No human labels.

Determinism: same source revisions -> same corpus bytes. Streaming single
pass per source; global exact dedup on content_sha256 before splitting;
hash-bucket train/val/test partition (90/5/5).
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atlas_paths import get_root, is_write_safe  # noqa: E402

from source_discovery.hashing import sha256_file  # noqa: E402
from source_discovery.normalize import normalize_pair  # noqa: E402
from source_discovery.pipeline import _guard_write  # noqa: E402

ROOT = get_root()
V11 = ROOT / "metadata" / "source_discovery" / "v1.1"
V11_CORPUS = V11 / "corpus"
V11_STAGING = V11 / "staging"
V11_TMP = ROOT / "tmp" / "source_discovery" / "v1.1"

GITIGNORE_TEXT = """# v1.1 bulk JSONL is regenerable from pinned sources; manifests + reports are tracked.
corpus/*.jsonl
corpus/splits/*.jsonl
staging/**/*.jsonl
"""

SPLIT_BOUNDS = {"train": 90, "val": 5, "test": 5}  # hash buckets of 100


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_layout() -> None:
    for d in (V11_CORPUS, V11_CORPUS / "splits", V11_STAGING, V11_TMP):
        _guard_write(d / ".keep")
    gi = V11 / ".gitignore"
    if not gi.exists():
        _guard_write(gi)
        gi.write_text(GITIGNORE_TEXT, encoding="utf-8")


def _write_manifest(staging_dir: Path, stats: dict[str, Any]) -> None:
    """Persist the FULL stats (revision, license, domain) as manifest.json.

    clean_and_stage's stats.json is pipeline-shape only; the manifest is the
    provenance record for the source build.
    """
    payload = {"manifest_version": "sd-v1.1", "written_utc": _utcnow(),
               **stats}
    with open(staging_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _write_jsonl(path: Path, rows: Iterable[dict]) -> tuple[int, str]:
    _guard_write(path)
    n = 0
    h = hashlib.sha256()
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            line = json.dumps(r, ensure_ascii=False) + "\n"
            f.write(line)
            h.update(line.encode("utf-8"))
            n += 1
    return n, h.hexdigest()


def _read_jsonl(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def clean_and_stage(raw_iter: Iterable[dict], source_id: str,
                    staging_dir: Path,
                    manifest_extra: dict[str, Any] | None = None
                    ) -> dict[str, Any]:
    """Normalize already-shaped {source,target,langs,record_id} rows.

    Writes normalized.jsonl / kept.jsonl / rejected.jsonl into staging_dir.
    Returns stats. STREAMING single pass (constant memory besides the kept
    content-hash set); deterministic.
    """
    from source_discovery.quality_filter import filter_record

    staging_dir.mkdir(parents=True, exist_ok=True)
    norm_p = staging_dir / "normalized.jsonl"
    kept_p = staging_dir / "kept.jsonl"
    rej_p = staging_dir / "rejected.jsonl"
    for p in (norm_p, kept_p, rej_p):
        _guard_write(p)
    n_raw = n_malformed = 0
    stats: dict[str, Any] = {}
    seen: set[str] = set()
    n_kept = n_rej = 0
    with open(norm_p, "w", encoding="utf-8") as fn, \
            open(kept_p, "w", encoding="utf-8") as fk, \
            open(rej_p, "w", encoding="utf-8") as fr:
        for row in raw_iter:
            n_raw += 1
            try:
                rec = normalize_pair(
                    row["source"], row["target"], row["source_lang"],
                    row.get("target_lang", "en"), source_id,
                    row.get("source_revision", ""),
                    row.get("source_record_id", ""),
                    method=row.get("method", ""),
                    parser_format=row.get("parser_format", ""),
                    extra=row)
            except (ValueError, KeyError, TypeError):
                n_malformed += 1
                continue
            fn.write(json.dumps(rec, ensure_ascii=False) + "\n")
            reason = filter_record(rec, seen)
            if reason is None:
                rec["quality_status"] = "auto_kept"
                fk.write(json.dumps(rec, ensure_ascii=False) + "\n")
                ch = rec.get("content_sha256")
                if isinstance(ch, str):
                    seen.add(ch)
                n_kept += 1
            else:
                fr.write(json.dumps(
                    {"id": rec.get("id"), "reason": reason},
                    ensure_ascii=False) + "\n")
                stats[reason] = stats.get(reason, 0) + 1
                n_rej += 1
    out = {
        "n_raw_shaped": n_raw,
        "n_malformed_shape": n_malformed,
        "n_normalized": n_raw - n_malformed,
        "normalized_sha256": sha256_file(norm_p),
        "quality_filter": {"n_input": n_raw - n_malformed, "kept": n_kept,
                           **stats, "n_kept": n_kept,
                           "n_rejected": n_rej},
        "dedup": {"n_duplicates_dropped": stats.get("duplicate_content", 0),
                  "note": "exact content-hash dedup runs inside the quality "
                          "pass (first wins); counts included above"},
        "n_kept": n_kept, "kept_sha256": sha256_file(kept_p),
        "n_rejected": n_rej, "rejected_sha256": sha256_file(rej_p),
    }
    (staging_dir / "stats.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    if manifest_extra:
        out.update(manifest_extra)
        _write_manifest(staging_dir, out)
    return out


# ---------------------------------------------------------------------------
# Source 1: hsc-wuxia-100k (stream all Hub splits)
# ---------------------------------------------------------------------------

def acquire_hsc() -> dict[str, Any]:
    from datasets import load_dataset
    from huggingface_hub import HfApi

    ensure_layout()
    repo = "HSilvosa/hsc-wuxia-100k"
    revision = str(HfApi().dataset_info(repo).sha or "")

    def rows() -> Iterator[dict]:
        for split in ("train", "validation", "test"):
            ds = load_dataset(repo, split=split, streaming=True)
            for i, ex in enumerate(ds):
                yield {"source": ex.get("zh", "") or "",
                       "target": ex.get("en", "") or "",
                       "source_lang": "zh", "target_lang": "en",
                       "source_revision": revision,
                       "source_record_id": f"hsc-{split}-{i:07d}",
                       "method": "hf_streaming_full",
                       "parser_format": f"hf_arrow:{split}",
                       "orig_split": split}

    # Count raw first via shape pass inside clean_and_stage; raw count =
    # shaped + malformed. For exact raw acquired, stream once here.
    staging = V11_STAGING / "hsc-wuxia-100k"
    manifest_extra = {"repo": repo, "revision": revision,
                      "license": "mit", "license_state": "ALLOW",
                      "domain": "web_novel"}
    stats = clean_and_stage(rows(), "hsc-wuxia-100k", staging,
                            manifest_extra=manifest_extra)
    stats.update(manifest_extra)
    return stats


# ---------------------------------------------------------------------------
# Source 2: tomato-zh2en (ZIP path; EN side is MT-derived — provenance!)
# ---------------------------------------------------------------------------

def tomato_zip_path(revision: str) -> Path:
    from huggingface_hub import snapshot_download
    snap = snapshot_download("TomatoMTL/tomato-zh2en", repo_type="dataset",
                             revision=revision)
    return Path(snap) / "zh-en.zip"


def acquire_tomato(revision: str, limit_pairs: int | None = None) -> dict[str, Any]:
    ensure_layout()
    zpath = tomato_zip_path(revision)
    archive_sha = sha256_file(zpath)
    archive_bytes = zpath.stat().st_size

    def rows() -> Iterator[dict]:
        z = zipfile.ZipFile(zpath)
        try:
            names = z.namelist()
            raw_ids: set[int] = set()
            mtl_ids: set[int] = set()
            for n in names:
                parts = n.split("/")
                if len(parts) != 3 or not parts[2].endswith(".txt"):
                    continue
                try:
                    num = int(parts[2][:-4])
                except ValueError:
                    continue
                if parts[1] == "raw":
                    raw_ids.add(num)
                elif parts[1] == "mtl":
                    mtl_ids.add(num)
            pair_ids = sorted(raw_ids & mtl_ids)
            stats_note = {"n_raw_files": len(raw_ids),
                          "n_mtl_files": len(mtl_ids),
                          "n_paired": len(pair_ids),
                          "n_unpaired": len(raw_ids ^ mtl_ids)}
            (V11_STAGING / "tomato-zh2en").mkdir(parents=True, exist_ok=True)
            with open(V11_STAGING / "tomato-zh2en" / "pairing.json",
                      "w", encoding="utf-8") as f:
                json.dump(stats_note, f, indent=2)
            if limit_pairs is not None:
                pair_ids = pair_ids[:limit_pairs]
            for num in pair_ids:
                try:
                    zh = z.read(f"en/raw/{num}.txt").decode("utf-8")
                    en = z.read(f"en/mtl/{num}.txt").decode("utf-8")
                except (KeyError, UnicodeDecodeError):
                    yield {"source": "", "target": "",
                           "source_lang": "zh", "target_lang": "en",
                           "source_revision": revision,
                           "source_record_id": f"tomato-{num}",
                           "method": "zip_pair", "parser_format": "zip_txt_pair",
                           "chapter_id": str(num), "target_origin":
                           "machine_translated"}
                    continue
                yield {"source": zh, "target": en,
                       "source_lang": "zh", "target_lang": "en",
                       "source_revision": revision,
                       "source_record_id": f"tomato-{num}",
                       "method": "zip_pair", "parser_format": "zip_txt_pair",
                       "chapter_id": str(num),
                       "target_origin": "machine_translated"}
        finally:
            z.close()

    staging = V11_STAGING / "tomato-zh2en"
    manifest_extra = {"repo": "TomatoMTL/tomato-zh2en", "revision": revision,
                      "archive": "zh-en.zip", "archive_sha256": archive_sha,
                      "archive_bytes": archive_bytes,
                      "license": "apache-2.0", "license_state": "ALLOW",
                      "domain": "web_novel",
                      "target_origin": "machine_translated (EN side is MT "
                                       "output, not human gold — "
                                       "distillation-grade)"}
    stats = clean_and_stage(rows(), "tomato-zh2en", staging,
                            manifest_extra=manifest_extra)
    stats.update(manifest_extra)
    return stats


# ---------------------------------------------------------------------------
# Source 3: opus-100 bounded (UNKNOWN license -> research-baseline only)
# ---------------------------------------------------------------------------

OPUS_CONFIGS = {"zh": "en-zh", "ja": "en-ja", "ko": "en-ko", "ms": "en-ms"}


def acquire_opus(caps: dict[str, int]) -> dict[str, Any]:
    from datasets import load_dataset
    from huggingface_hub import HfApi

    ensure_layout()
    revision = str(HfApi().dataset_info("Helsinki-NLP/opus-100").sha or "")

    def rows() -> Iterator[dict]:
        for lang, cfg in OPUS_CONFIGS.items():
            ds = load_dataset("Helsinki-NLP/opus-100", cfg, split="train",
                              streaming=True)
            for i, ex in enumerate(ds):
                if i >= caps.get(lang, 0):
                    break
                tr = ex.get("translation", {}) or {}
                yield {"source": tr.get(lang, "") or "",
                       "target": tr.get("en", "") or "",
                       "source_lang": lang, "target_lang": "en",
                       "source_revision": revision,
                       "source_record_id": f"opus100-{cfg}-train-{i:07d}",
                       "method": "hf_streaming_bounded",
                       "parser_format": "hf_dict"}

    staging = V11_STAGING / "opus-100"
    manifest_extra = {"repo": "Helsinki-NLP/opus-100", "revision": revision,
                      "caps": caps, "license": "unknown",
                      "license_state": "UNKNOWN",
                      "license_note": "research-baseline only; NEVER "
                                      "training-ready",
                      "domain": "subtitle"}
    stats = clean_and_stage(rows(), "opus-100", staging,
                            manifest_extra=manifest_extra)
    stats.update(manifest_extra)
    return stats


# ---------------------------------------------------------------------------
# Source 4: JESC capped sample (UNKNOWN license -> research-baseline only)
# ---------------------------------------------------------------------------

def acquire_jesc(cap: int = 30000) -> dict[str, Any]:
    import tarfile

    ensure_layout()
    tpath = V11_TMP / "jesc_split.tar.gz"
    if not tpath.exists():
        raise FileNotFoundError(f"missing {tpath} (download split.tar.gz)")
    archive_sha = sha256_file(tpath)

    def rows() -> Iterator[dict]:
        t = tarfile.open(tpath)
        try:
            f = t.extractfile("split/train")
            if f is None:
                raise ValueError("split/train missing in JESC archive")
            n = 0
            for raw in f:
                if n >= cap:
                    break
                try:
                    line = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue
                # JESC TSV order is en \t ja; our direction is ja->en.
                yield {"source": parts[1], "target": parts[0],
                       "source_lang": "ja", "target_lang": "en",
                       "source_revision": archive_sha[:16],
                       "source_record_id": f"jesc-train-{n:07d}",
                       "method": "tar_tsv_sample",
                       "parser_format": "tsv:en_ja"}
                n += 1
        finally:
            t.close()

    staging = V11_STAGING / "jesc"
    manifest_extra = {"archive": "split.tar.gz",
                      "archive_sha256": archive_sha,
                      "archive_bytes": tpath.stat().st_size, "cap": cap,
                      "license": "unknown",
                      "license_state": "UNKNOWN",
                      "license_note": "research-baseline only; NEVER "
                                      "training-ready",
                      "domain": "subtitle"}
    stats = clean_and_stage(rows(), "jesc", staging,
                            manifest_extra=manifest_extra)
    stats.update(manifest_extra)
    return stats


# ---------------------------------------------------------------------------
# Source 5: JParaCrawl community mirror (RESTRICTED -> research-baseline only)
# ---------------------------------------------------------------------------

def acquire_jparacrawl_verah(cap: int = 50000) -> dict[str, Any]:
    import gzip as _gzip
    import urllib.request as _url

    ensure_layout()
    repo = "Verah/JParaCrawl-Filtered-English-Japanese-Parallel-Corpus"
    from huggingface_hub import HfApi, snapshot_download
    revision = str(HfApi().dataset_info(repo).sha or "")
    # NOTE: single-file resolve 404s on this host for this repo (CDN quirk
    # also seen on tomato-zh2en); snapshot_download routes correctly.
    snap = Path(snapshot_download(repo, repo_type="dataset",
                                  revision=revision))
    local = snap / "1m_filtered.tsv.gz"
    archive_sha = sha256_file(local)
    flag_dist: dict[str, int] = {}

    def rows() -> Iterator[dict]:
        n = 0
        with _gzip.open(local, "rt", encoding="utf-8",
                        errors="replace") as f:
            for line in f:
                if n >= cap:
                    break
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 5:
                    continue
                try:
                    rid = int(parts[0])
                    m1, m2 = int(parts[3]), int(parts[4])
                except ValueError:
                    continue
                flag_dist[f"m1_{m1}_m2_{m2}"] = \
                    flag_dist.get(f"m1_{m1}_m2_{m2}", 0) + 1
                # TSV order is id, english, japanese, m1, m2.
                yield {"source": parts[2], "target": parts[1],
                       "source_lang": "ja", "target_lang": "en",
                       "source_revision": revision,
                       "source_record_id": f"jpara-verah-{rid}",
                       "method": "tsv.gz_sample",
                       "parser_format": "tsv:id_en_ja_m1_m2"}
                n += 1

    staging = V11_STAGING / "jparacrawl-verah"
    stats = clean_and_stage(rows(), "jparacrawl-verah", staging)
    manifest_extra = {
        "repo": repo, "revision": revision, "file": "1m_filtered.tsv.gz",
        "archive_sha256": archive_sha,
        "archive_bytes": local.stat().st_size, "cap": cap,
        "license": "ntt-research (research purposes; verify NTT terms)",
        "license_state": "RESTRICTED",
        "license_note": "third-party mirror of NTT JParaCrawl v3; "
                        "research-only upstream terms; NEVER training-ready",
        "domain": "general",
        "third_party_filter_flags": flag_dist,
        "quality_note": "web-crawl noise observed (repeated EN across "
                        "unrelated JA, boilerplate); our filters apply, "
                        "third-party model flags recorded only",
    }
    # manifest written by re-running clean tail (rows exhausted); write here:
    _write_manifest(staging, {**stats, **manifest_extra})
    stats.update(manifest_extra)
    return stats


# ---------------------------------------------------------------------------
# Assembly: license-separated corpora + deterministic splits
# ---------------------------------------------------------------------------

def split_bucket(content_sha: str) -> str:
    b = int((content_sha or "0" * 8)[:8], 16) % 100
    if b < 90:
        return "train"
    if b < 95:
        return "val"
    return "test"


def assemble_corpora() -> dict[str, Any]:
    """Read staged kept files; write license-separated corpora + splits.

    STREAMING: global cross-source exact dedup (first wins in the priority
    order below) and hash-bucket train/val/test partition (90/5/5) happen in
    file passes. Zero cross-split content-hash leakage is asserted.
    """
    from collections import Counter as _Counter

    ensure_layout()
    plan = (("hsc-wuxia-100k", "training"), ("tomato-zh2en", "training"),
            ("tatoeba-koen", "training"), ("tatoeba-msen", "training"),
            ("opus-100", "baseline"), ("jesc", "baseline"),
            ("jparacrawl-verah", "baseline"))
    tr_p = V11_CORPUS / "training_ready.jsonl"
    bl_p = V11_CORPUS / "research_baseline.jsonl"
    _guard_write(tr_p)
    _guard_write(bl_p)

    seen_tr: set[str] = set()
    seen_bl: set[str] = set()
    n_tr = n_bl = 0
    dup_tr = dup_bl = 0
    dist_tr_dir: _Counter = _Counter()
    dist_tr_src: _Counter = _Counter()
    dist_bl_dir: _Counter = _Counter()
    dist_bl_src: _Counter = _Counter()
    with open(tr_p, "w", encoding="utf-8") as ftr, \
            open(bl_p, "w", encoding="utf-8") as fbl:
        for sid, bucket in plan:
            kp = V11_STAGING / sid / "kept.jsonl"
            if not kp.exists():
                continue
            seen = seen_tr if bucket == "training" else seen_bl
            for r in _read_jsonl(kp):
                ch = r.get("content_sha256")
                if not isinstance(ch, str) or ch in seen:
                    if bucket == "training":
                        dup_tr += 1
                    else:
                        dup_bl += 1
                    continue
                seen.add(ch)
                r["license_status"] = ("ALLOW" if bucket == "training"
                                       else "UNKNOWN")
                line = json.dumps(r, ensure_ascii=False) + "\n"
                if bucket == "training":
                    ftr.write(line)
                    n_tr += 1
                    dist_tr_dir[str(r.get("source_lang"))] += 1
                    dist_tr_src[sid] += 1
                else:
                    fbl.write(line)
                    n_bl += 1
                    dist_bl_dir[str(r.get("source_lang"))] += 1
                    dist_bl_src[sid] += 1

    # Deterministic splits per corpus (streaming bucket pass).
    split_info: dict[str, Any] = {}
    for corpus_name, cpath in (("training_ready", tr_p),
                               ("research_baseline", bl_p)):
        handles = {}
        for split in ("train", "val", "test"):
            sp = V11_CORPUS / "splits" / f"{corpus_name}.{split}.jsonl"
            _guard_write(sp)
            handles[split] = open(sp, "w", encoding="utf-8")
        counts = {"train": 0, "val": 0, "test": 0}
        split_hashes: dict[str, set] = {"train": set(), "val": set(),
                                        "test": set()}
        try:
            for r in _read_jsonl(cpath):
                s = split_bucket(r.get("content_sha256", ""))
                handles[s].write(json.dumps(r, ensure_ascii=False) + "\n")
                counts[s] += 1
                split_hashes[s].add(r.get("content_sha256"))
        finally:
            for h in handles.values():
                h.close()
        assert not (split_hashes["train"] & split_hashes["val"])
        assert not (split_hashes["train"] & split_hashes["test"])
        assert not (split_hashes["val"] & split_hashes["test"])
        for split in ("train", "val", "test"):
            sp = V11_CORPUS / "splits" / f"{corpus_name}.{split}.jsonl"
            split_info[f"{corpus_name}.{split}"] = {
                "n": counts[split], "sha256": sha256_file(sp)}

    summary = {
        "built_utc": _utcnow(),
        "n_training_ready": n_tr, "training_ready_sha256": sha256_file(tr_p),
        "n_research_baseline": n_bl,
        "research_baseline_sha256": sha256_file(bl_p),
        "cross_source_dedup": {"training_dups_dropped": dup_tr,
                               "baseline_dups_dropped": dup_bl},
        "by_source_lang_training": dict(dist_tr_dir),
        "by_source_training": dict(dist_tr_src),
        "by_source_lang_baseline": dict(dist_bl_dir),
        "by_source_baseline": dict(dist_bl_src),
        "splits": split_info,
    }
    with open(V11 / "corpus_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    return summary
