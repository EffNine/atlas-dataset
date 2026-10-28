"""Provenance, isolation, and pipeline-structure tests (offline)."""
import json
import re
from pathlib import Path

import run_filter
import router

HERE = Path(run_filter.__file__).resolve().parent


def test_pipeline_reads_no_human_labels():
    for mod in (run_filter, router):
        assert mod.__file__ is not None
        src = open(mod.__file__).read()
        assert "phase2" not in src, mod.__name__
        assert "human_label" not in src, mod.__name__
    assert (HERE.parent / "jev-pilot-atlas-v0.1" / "sample_manifest.json"
            ).exists()


def test_router_and_runner_share_one_formula_version():
    assert run_filter.router is router
    assert run_filter.router.FORMULA_VERSION == "v0.2-router-v1"


def test_input_provenance_hashes_are_wellformed():
    prov = run_filter.input_provenance()
    assert prov["router_formula"] == "v0.2-router-v1"
    assert set(prov["policies"]) == {"conservative", "balanced", "aggressive"}
    for key, digest in prov.items():
        if key in ("router_formula", "policies"):
            continue
        assert re.fullmatch(r"[0-9a-f]{64}", digest), key


def test_build_results_preserves_provenance():
    jev, _content, _meta = run_filter.load_inputs()
    assert len(jev) == 500
    rows = run_filter.build_results()
    try:
        assert len(rows) == 500
        by_id = jev
        for e in rows:
            src = by_id[e["record_id"]]
            assert e["content_sha256"] == src.get("content_sha256")
            assert e["arm"] == src.get("arm")
            assert set(e["per_policy"]) == {"conservative", "balanced",
                                            "aggressive"}
            for name, pc in e["per_policy"].items():
                assert {"band", "final", "path", "quarantine",
                        "confidence"} <= set(pc)
                assert pc["final"] in ("ACCEPT", "REJECT", "AMBIGUOUS")
                if pc["band"] in ("HIGH", "LOW"):
                    assert pc.get("ai2_invoked") is not True or \
                        pc["band"] == "AMBIGUOUS"
            # AI-2 block is either absent or a real verdict, never invented
            if e["ai2"] is not None:
                assert e["ai2"].get("verdict") in ("ACCEPT", "REJECT",
                                                   "AMBIGUOUS", "ERROR")
                assert e["ai2_source"] in ("jev-quality-filter-v0.1",
                                           "jev-quality-filter-v0.2")
            else:
                assert e["ai2_source"] is None
    finally:
        # build_results writes filter_results.jsonl; the report step owns the
        # final artifact, so remove the test-time byproduct if report outputs
        # do not exist yet.
        if not run_filter.CONFIG_SUMMARY.exists() and \
                run_filter.FILTER_RESULTS.exists():
            run_filter.FILTER_RESULTS.unlink()


def test_no_record_auto_accepts_on_degraded_signals_in_real_data():
    jev, _c, _m = run_filter.load_inputs()
    bad = [rid for rid, r in jev.items()
           if r.get("status") == "ok"
           and router.extract_signals(r["answers"])[0] is None]
    assert bad == []  # all 500 stored records carry complete signals


def test_v01_comparison_loader_reads_bands_only():
    v01 = run_filter.load_v01_bands()
    assert len(v01) == 500
    sample = next(iter(v01.values()))
    assert set(sample) == {"A-balanced", "B-strict-accept", "C-lenient-accept"}


def test_disagreement_experiment_covers_all_escalated():
    rows = run_filter.build_results()
    try:
        dis = run_filter.build_disagreement_experiment(rows)
        try:
            for name in ("conservative", "balanced", "aggressive"):
                cell = dis["policies"][name]
                n_esc = sum(1 for e in rows
                            if e["per_policy"][name].get("ai2_invoked"))
                assert cell["n_escalated"] == n_esc
                assert (cell["n_quarantined_by_disagreement"]
                        + cell["n_fail_safe"]
                        + cell["matrix_dist"].get("agree_accept", 0)
                        + cell["matrix_dist"].get("agree_reject", 0)) == n_esc
        finally:
            if run_filter.DISAGREEMENT_SUMMARY.exists() and \
                    not run_filter.CONFIG_SUMMARY.exists():
                run_filter.DISAGREEMENT_SUMMARY.unlink()
    finally:
        if not run_filter.CONFIG_SUMMARY.exists() and \
                run_filter.FILTER_RESULTS.exists():
            run_filter.FILTER_RESULTS.unlink()
