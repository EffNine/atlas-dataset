"""Tests for Atlas Source Discovery v1.0.

Covers: registry validation, deterministic hashing, provenance preservation,
parser correctness, language validation, duplicate detection, license-state
handling, malformed input, source revision tracking, deterministic output,
Atlas source non-mutation, JEV boundary, AI-2 blindness/fail-closed.

No network. No model training. No writes outside tmp_path + guarded roots.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from source_discovery.ai2_adapter import (  # noqa: E402
    EXPECTED_PAYLOAD_KEYS,
    build_ai2_request,
    review_or_quarantine,
)
from source_discovery.candidates import build_initial_candidates  # noqa: E402
from source_discovery.dedup import dedup_by_content  # noqa: E402
from source_discovery.hashing import (  # noqa: E402
    content_hash,
    sha256_canonical,
    sha256_text,
)
from source_discovery.jev_adapter import (  # noqa: E402
    build_jev_input,
    load_router,
    route_with_stored_signals,
    smoke_dataflow,
)
from source_discovery.language_check import check_pair_languages, lang_ok  # noqa: E402
from source_discovery.license_policy import (  # noqa: E402
    classify_license,
    is_training_ready_license,
)
from source_discovery.normalize import normalize_pair, normalize_text  # noqa: E402
from source_discovery.parsers import (  # noqa: E402
    detect_format,
    parse_csv,
    parse_file,
    parse_jsonl,
    parse_tsv,
    parse_txt,
)
from source_discovery.pipeline import _guard_write  # noqa: E402
from source_discovery.quality_filter import filter_corpus, filter_record  # noqa: E402
from source_discovery.registry import (  # noqa: E402
    SD_ALLOWED_TRANSITIONS,
    SD_DOMAINS,
    SD_SOURCE_STATUSES,
    blank_entry,
    registry_stats,
    transition,
    validate_source_entry,
)

ZH = "夜色的街道很安静，人们都回家了。"
JA = "夜の街は静かで、人々は家に帰りました。"
KO = "밤거리는 조용하고 사람들은 집에 돌아갔다."
MS = "Jalan pada waktu malam sunyi dan orang ramai pulang ke rumah."
EN = "The night street was quiet and everyone went home."


def _good_entry(**kw):
    e = blank_entry("t1")
    e.update({"name": "T", "source_type": "parallel_corpus",
              "languages": ["zh", "en"], "directions": ["zh→en"],
              "url": "https://example.com", "repo_id": "",
              "license": "CC0-1.0", "license_evidence": "card",
              "publisher": "P", "citation": "", "estimated_size": "10",
              "format": "JSONL", "access_method": "http",
              "source_revision": "", "checksum": "", "status": "DISCOVERED",
              "license_state": "ALLOW", "domain": "general", "notes": ""})
    e.update(kw)
    return e


# --- registry validation ----------------------------------------------------

def test_registry_accepts_valid_entry():
    assert validate_source_entry(_good_entry()) == []


def test_registry_rejects_missing_field():
    e = _good_entry()
    del e["url"]
    assert any("missing_field:url" in x for x in validate_source_entry(e))


def test_registry_rejects_bad_status_license_domain():
    assert any("bad_status" in x for x in
               validate_source_entry(_good_entry(status="NOPE")))
    assert any("bad_license_state" in x for x in
               validate_source_entry(_good_entry(license_state="NOPE")))
    assert any("bad_domain" in x for x in
               validate_source_entry(_good_entry(domain="NOPE")))
    assert any("bad_source_type" in x for x in
               validate_source_entry(_good_entry(source_type="NOPE")))


def test_registry_transition_guards_illegal():
    e = _good_entry(status="DISCOVERED")
    with pytest.raises(ValueError):
        transition(e, "INGESTED")  # must pass through VERIFIED/DOWNLOADABLE
    transition(e, "VERIFIED", note="ok")
    assert e["status"] == "VERIFIED"


def test_all_spec_statuses_known():
    assert SD_SOURCE_STATUSES == frozenset({
        "DISCOVERED", "VERIFIED", "DOWNLOADABLE", "INGESTED", "REJECTED",
        "BLOCKED_LICENSE", "BLOCKED_ACCESS", "FAILED"})
    # every status can at least return to DISCOVERED or terminate somewhere
    for s in SD_SOURCE_STATUSES:
        assert s in SD_ALLOWED_TRANSITIONS


def test_initial_candidates_all_validate():
    for e in build_initial_candidates():
        assert validate_source_entry(e) == [], e["source_id"]


def test_initial_candidates_cover_four_directions():
    cands = build_initial_candidates()
    dirs = {d for e in cands for d in e["directions"]}
    for d in ("zh→en", "ja→en", "ko→en", "ms→en"):
        assert d in dirs, f"missing direction {d}"


# --- deterministic hashing ---------------------------------------------------

def test_hashing_deterministic_and_sensitive():
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abd")
    assert len(sha256_text("x")) == 64
    assert sha256_canonical({"b": 1, "a": 2}) == \
        sha256_canonical({"a": 2, "b": 1})
    assert content_hash("a", "b", "zh", "en") != \
        content_hash("a", "b", "ja", "en")


# --- provenance preservation -------------------------------------------------

def test_normalize_preserves_provenance():
    r = normalize_pair(ZH, EN, "zh", "en", "opus-100", "rev123456789",
                       "row-7", method="hf", parser_format="hf_dict")
    assert r["source_id"] == "opus-100"
    assert r["source_revision"] == "rev123456789"
    assert r["source_record_id"] == "row-7"
    assert r["source_lang"] == "zh" and r["target_lang"] == "en"
    assert len(r["content_sha256"]) == 64
    assert len(r["original_sha256"]) == 64
    assert r["id"].startswith("opus-100:rev12345:row-7")
    assert r["acquisition"]["direction"] == "zh→en"


def test_normalize_deterministic_id_and_hash():
    a = normalize_pair(ZH, EN, "zh", "en", "s", "rev", "r1")
    b = normalize_pair(ZH, EN, "zh", "en", "s", "rev", "r1")
    assert a["id"] == b["id"]
    assert a["content_sha256"] == b["content_sha256"]
    c = normalize_pair(ZH, EN, "zh", "en", "s", "rev", "r2")
    assert a["content_sha256"] == c["content_sha256"]  # same content
    assert a["id"] != c["id"]  # different record id


def test_source_revision_tracked_in_id():
    a = normalize_pair(ZH, EN, "zh", "en", "s", "aaa", "r1")
    b = normalize_pair(ZH, EN, "zh", "en", "s", "bbb", "r1")
    assert "aaa" in a["id"] and "bbb" in b["id"]


def test_normalize_text_deterministic():
    assert normalize_text("  a   b \r\n\r\n\r\n c  ") == "a b\n\nc"
    assert normalize_text(ZH) == ZH


# --- parsers -----------------------------------------------------------------

def test_parsers_jsonl_csv_tsv_txt(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"a": 1}\n\nnot-json\n', encoding="utf-8")
    recs, errs = parse_jsonl(p)
    assert recs == [{"a": 1}] and len(errs) == 1

    c = tmp_path / "b.csv"
    c.write_text("src,tgt\n你好,hello\n", encoding="utf-8")
    recs, _ = parse_csv(c)
    assert recs[0]["src"] == "你好"

    t = tmp_path / "c.tsv"
    t.write_text("src\ttgt\n안녕\thello\n", encoding="utf-8")
    recs, _ = parse_tsv(t)
    assert recs[0]["tgt"] == "hello"

    x = tmp_path / "d.txt"
    x.write_text("line1\n\nline2\n", encoding="utf-8")
    recs, _ = parse_txt(x)
    assert recs == ["line1", "line2"]

    assert detect_format("f.JSONL") == "jsonl"
    assert detect_format("f.tar.gz") == "tar"
    recs, errs, fmt = parse_file(tmp_path / "nope.xyz")
    assert fmt == "unknown" and errs


# --- language validation -----------------------------------------------------

def test_language_positive_cases():
    assert lang_ok(ZH, "zh") and lang_ok(JA, "ja") and lang_ok(KO, "ko")
    assert lang_ok(MS, "ms") and lang_ok(EN, "en")


def test_language_negative_cases():
    assert not lang_ok(EN, "zh")
    assert not lang_ok(ZH, "ko")
    assert not lang_ok("", "en")
    assert check_pair_languages(EN, EN, "zh") is not None
    assert check_pair_languages(ZH, EN, "zh") is None
    assert check_pair_languages(ZH, EN, "xx") == "unsupported_language"


# --- duplicates ----------------------------------------------------------------

def test_duplicate_detection_first_wins():
    a = normalize_pair(ZH, EN, "zh", "en", "s", "r", "1")
    b = normalize_pair(ZH, EN, "zh", "en", "s", "r", "2")
    kept, dups, stats = dedup_by_content([a, b])
    assert len(kept) == 1 and kept[0]["source_record_id"] == "1"
    assert stats["n_duplicates"] == 1
    assert dups[0]["kept_id"] == a["id"]


# --- license states ------------------------------------------------------------

def test_license_state_handling():
    assert classify_license("UNKNOWN")[0] == "UNKNOWN"
    assert classify_license("")[0] == "UNKNOWN"
    assert classify_license("CC-BY-NC-4.0")[0] == "BLOCKED"
    assert classify_license("proprietary")[0] == "BLOCKED"
    assert classify_license("CC-BY-SA-4.0")[0] == "RESTRICTED"
    assert classify_license("CC0-1.0")[0] == "ALLOW"
    assert classify_license("MIT")[0] == "ALLOW"
    assert is_training_ready_license("ALLOW")
    assert not is_training_ready_license("RESTRICTED")
    assert not is_training_ready_license("UNKNOWN")
    assert not is_training_ready_license("BLOCKED")


# --- malformed input + quality filter ------------------------------------------

def test_quality_filter_reasons():
    base = normalize_pair(ZH, EN, "zh", "en", "s", "r", "1")
    assert filter_record(dict(base)) is None
    assert filter_record({"nope": 1}) == "malformed_record"
    e = dict(base, source="   ", target=EN)
    assert filter_record(e) == "empty_pair"
    e = dict(base, source=EN, target=EN)
    assert filter_record(e) == "copy_pair"
    e = dict(base, source="x" * 6000)
    assert filter_record(e) == "too_long"
    e = dict(base, source="<html>hi", target=EN)
    assert filter_record(e) in ("wrong_language_source_zh", "html_boilerplate")
    e = dict(base, source="Click here to subscribe now " + ZH,
             target=EN)
    assert filter_record(e) == "html_boilerplate"
    e = dict(base, source="ab" * 200, target=EN)
    assert filter_record(e) in ("wrong_language_source_zh", "repeated_text")


def test_filter_corpus_deterministic():
    recs = [normalize_pair(ZH, EN, "zh", "en", "s", "r", str(i))
            for i in range(3)]
    recs.append(dict(recs[0], id="dup"))  # same content hash
    k1, r1, s1 = filter_corpus(recs)
    k2, r2, s2 = filter_corpus(recs)
    assert [r["id"] for r in k1] == [r["id"] for r in k2]
    assert s1 == s2
    assert s1.get("duplicate_content", 0) >= 1


# --- Atlas non-mutation ----------------------------------------------------------

def test_guard_refuses_protected_trees(tmp_path):
    import atlas_paths
    root = atlas_paths.get_root()
    for rel in ("curated/x.jsonl", "raw/y.jsonl",
                "translation-ai-v0.1/data/z.jsonl", "releases/v1.0/a.json",
                "review_queue/q.jsonl", "training_views/t.json",
                "pilot/v0.2/f.jsonl", "experiments/e.json"):
        with pytest.raises(PermissionError):
            _guard_write(root / rel)
    ok = _guard_write(root / "metadata" / "source_discovery" / "staging" /
                      "t" / "probe.jsonl")
    assert "source_discovery" in str(ok)
    ok2 = _guard_write(root / "tmp" / "source_discovery" / "probe.jsonl")
    assert "source_discovery" in str(ok2)


# --- JEV boundary ------------------------------------------------------------------

def test_jev_boundary_loads_real_router():
    loaded = load_router()
    assert loaded["available"], loaded.get("reason")
    assert loaded["formula_version"] == "v0.2-router-v1"
    assert set(loaded["policies"]) == {"conservative", "balanced",
                                       "aggressive"}


def test_jev_smoke_only_synthetic():
    out = smoke_dataflow(n_per_band=1)
    assert out["ok"] and out["synthetic_smoke"]
    assert "not quality" in out["note"]


def test_jev_route_high_low_sane():
    from source_discovery.jev_adapter import _synthetic_answers
    hi = route_with_stored_signals(_synthetic_answers("high"), "balanced")
    lo = route_with_stored_signals(_synthetic_answers("low"), "balanced")
    assert hi["band"] == "HIGH"
    assert lo["band"] == "LOW"


def test_jev_input_carries_no_scores():
    r = normalize_pair(ZH, EN, "zh", "en", "s", "r", "1")
    ji = build_jev_input(r)
    for forbidden in ("correct", "quality", "problematic", "confidence",
                      "band", "score"):
        assert forbidden not in ji


# --- AI-2 blindness + fail-closed ----------------------------------------------------

def test_ai2_payload_keys_exact_and_no_jev_leak():
    import json as _json
    msgs = build_ai2_request(ZH, EN, "opus-100", "zh→en", "subtitle")
    payload = _json.loads(msgs[1]["content"])
    assert set(payload.keys()) == set(EXPECTED_PAYLOAD_KEYS)
    blob = _json.dumps(payload)
    for tok in ("noul", "tau_hi", "tau_lo", "band", "C="):
        assert tok not in blob


def test_ai2_reviewer_accepts_no_jev_args():
    from source_discovery.ai2_adapter import load_ai2_module
    loaded = load_ai2_module()
    assert loaded["available"]
    sig = inspect.signature(loaded["module"].review_record)
    for forbidden in ("jev", "confidence", "band", "scores", "signals"):
        assert forbidden not in sig.parameters, forbidden


def test_ai2_fail_closed_by_default():
    res = review_or_quarantine(ZH, EN, "s", "zh→en", "subtitle",
                               allow_live_call=False)
    assert res["quarantine"] and res["final"] == "AMBIGUOUS"
    assert res["blind"]


# --- determinism + domains -----------------------------------------------------------------

def test_registry_stats_counts():
    stats = registry_stats([_good_entry(source_id="a", domain="novel"),
                            _good_entry(source_id="b", domain="novel")])
    assert stats["by_domain"] == {"novel": 2}


def test_all_domains_in_spec_vocabulary():
    for e in build_initial_candidates():
        assert e["domain"] in SD_DOMAINS, e["source_id"]
