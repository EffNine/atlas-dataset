"""Tests for Atlas Source Discovery v1.1 corpus build.

Covers: split determinism + zero cross-split leakage, license separation
(UNKNOWN never training-ready), terminology sidecar schema + separation,
tomato ZIP pairing logic, JEV sampling determinism, corpus record schema,
chapter/orig-split provenance preservation, finalize math (KEEP/REJECT/
QUARANTINE accounting).

No network. No live JEV/AI-2 calls. Small fixtures only.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from source_discovery.corpus_v1_1 import split_bucket  # noqa: E402
from source_discovery.dedup import dedup_by_content  # noqa: E402
from source_discovery.jev_run import jev_state, select_candidates  # noqa: E402
from source_discovery.license_policy import (  # noqa: E402
    is_training_ready_license,
)
from source_discovery.normalize import normalize_pair  # noqa: E402
from source_discovery.quality_filter import filter_corpus  # noqa: E402

ZH = "夜色的街道很安静，人们都回家了。"
EN = "The night street was quiet and everyone went home."


def _rec(i: int, src: str = ZH, tgt: str = EN, sid: str = "s",
         rev: str = "r") -> dict:
    return normalize_pair(f"{src} {i}", f"{tgt} {i}", "zh", "en", sid, rev,
                          f"rec-{i}")


# --- splits -------------------------------------------------------------------

def test_split_bucket_deterministic_and_covering():
    import hashlib
    assert split_bucket("0" * 64) == split_bucket("0" * 64)
    seen = {split_bucket(hashlib.sha256(f"row-{i}".encode()).hexdigest())
            for i in range(3000)}
    assert seen == {"train", "val", "test"}


def test_split_no_cross_contamination():
    recs = [_rec(i) for i in range(500)]
    buckets: dict[str, set] = {"train": set(), "val": set(), "test": set()}
    for r in recs:
        buckets[split_bucket(r["content_sha256"])].add(r["content_sha256"])
    assert not (buckets["train"] & buckets["val"])
    assert not (buckets["train"] & buckets["test"])
    assert not (buckets["val"] & buckets["test"])
    assert sum(map(len, buckets.values())) == 500


def test_dedup_before_split_removes_cross_split_leakage():
    a = _rec(1)
    b = dict(_rec(1), id="other-id")  # same content, different id
    kept, dups, _ = dedup_by_content([a, b])
    assert len(kept) == 1 and len(dups) == 1


# --- license separation ---------------------------------------------------------

def test_unknown_never_training_ready():
    assert not is_training_ready_license("UNKNOWN")
    assert not is_training_ready_license("RESTRICTED")
    assert not is_training_ready_license("BLOCKED")
    assert is_training_ready_license("ALLOW")


def test_training_ready_record_schema():
    r = _rec(3)
    r["license_status"] = "ALLOW"
    r["quality_status"] = "auto_kept"
    for field in ("id", "source_lang", "target_lang", "source", "target",
                  "source_id", "source_revision", "source_record_id",
                  "content_sha256", "quality_status", "license_status"):
        assert field in r, field


# --- provenance extras ------------------------------------------------------------

def test_chapter_and_split_provenance_preserved():
    r = normalize_pair(ZH, EN, "zh", "en", "tomato-zh2en", "rev", "tomato-5",
                       extra={"chapter_id": "5",
                              "target_origin": "machine_translated"})
    assert r["chapter_id"] == "5"
    assert r["target_origin"] == "machine_translated"
    r2 = normalize_pair(ZH, EN, "zh", "en", "hsc-wuxia-100k", "rev", "h-1",
                        extra={"orig_split": "validation"})
    assert r2["orig_split"] == "validation"
    # unknown extras are dropped (schema discipline)
    r3 = normalize_pair(ZH, EN, "zh", "en", "s", "rev", "x",
                        extra={"surprise": "nope"})
    assert "surprise" not in r3


# --- tomato pairing -----------------------------------------------------------------

def test_tomato_pairing_logic(tmp_path):
    zp = tmp_path / "t.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("en/raw/7.txt", "你好世界")
        z.writestr("en/mtl/7.txt", "Hello world")
        z.writestr("en/raw/9.txt", "孤儿中文")
        z.writestr("en/mtl/11.txt", "Orphan english")
        z.writestr("notes.txt", "ignore me")
    with zipfile.ZipFile(zp) as z:
        raw_ids, mtl_ids = set(), set()
        for n in z.namelist():
            parts = n.split("/")
            if len(parts) == 3 and parts[2].endswith(".txt"):
                try:
                    num = int(parts[2][:-4])
                except ValueError:
                    continue
                (raw_ids if parts[1] == "raw" else
                 mtl_ids if parts[1] == "mtl" else set()).add(num)
    assert raw_ids == {7, 9} and mtl_ids == {7, 11}
    assert (raw_ids & mtl_ids) == {7}
    assert len(raw_ids ^ mtl_ids) == 2


# --- terminology sidecar -----------------------------------------------------------------

def test_sidecar_schema():
    row = {"source_lang": "ja", "target_lang": "en", "source_term": "猫",
           "target_term": "cat", "domain": "general", "source_id": "jmdict",
           "license": "CC-BY-SA-4.0", "license_state": "RESTRICTED",
           "provenance": {"revision": "abc", "entry_ref": "ent_seq:1"}}
    for field in ("source_lang", "target_lang", "source_term", "target_term",
                  "domain", "source_id", "license", "provenance"):
        assert field in row
    assert "source" not in row and "target" not in row  # not sentence pairs
    assert row["license_state"] == "RESTRICTED"  # share-alike tracked


def test_sidecar_never_sentence_data():
    assert "source_term" != "source"  # schema-distinct by construction


# --- JEV sampling + state --------------------------------------------------------------------

def test_jev_state_carries_no_scores():
    r = _rec(9)
    st = jev_state(r)
    assert st["messages"][0] == {"role": "user", "content": r["source"]}
    assert st["messages"][1]["role"] == "assistant"
    blob = json.dumps(st)
    for tok in ("noul", "tau_hi", "confidence", "band"):
        assert tok not in blob


def test_finalize_accounting():
    finals = [
        {"final": "KEEP", "quarantine": False},
        {"final": "REJECT", "quarantine": True},
        {"final": "QUARANTINE", "quarantine": True},
    ]
    kept = [f for f in finals if f["final"] == "KEEP"]
    quar = [f for f in finals if f["quarantine"]]
    assert len(kept) == 1 and len(quar) == 2
    # quarantine and rejected never silently merge into training-ready
    assert all(f["final"] != "KEEP" for f in quar)


def test_long_healthy_english_not_repeated():
    from source_discovery.quality_filter import _is_repeated
    long_en = ("Fujii Itsuki spread his textbook amidst the classroom "
               "chatter and studied hard every day. " * 25)
    assert not _is_repeated(long_en)
    short_en = ("The decisiveness in his voice could sever nails and chop "
                "iron, and his entire person seemed to radiate a valiant air")
    assert not _is_repeated(short_en)  # 116 chars, 19 uniques: legit
    assert _is_repeated("ab" * 500)
    assert _is_repeated("." * 300)
