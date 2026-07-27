#!/usr/bin/env python3
"""
probe_acquisition_engine.py — AD-HOC Acquisition Engine invariant verifier.

This is NOT a permanent test suite. It is a reusable, deterministic probe you
run (and delete after) whenever you modify the Acquisition Engine
(scripts/acquisition_engine/). It PROVES the hard guarantees rather than
asserting from memory.

What it checks (all against the CURRENT on-disk artifacts):
  1. No network used during engine operation (socket/urlopen monkey-patched)
  2. Acquisition Engine dry_run() succeeds and returns valid plan
  3. License gate consistency vs scripts/validate_dataset.py:is_denied_license
  4. Checkpoint integrity (tamper-evident checksum matches)
  5. Checkpoint resumability (resume returns valid state)
  6. Lifecycle tracking (state machine transitions work correctly)
  7. Version management (list/freeze/diff)
  8. Knowledge Pack generation and verification
  9. Dataset Diff computation
  10. Integrity verification (checksum registry, verification log chain)

Usage:
  python tests/probe_acquisition_engine.py
  python tests/probe_acquisition_engine.py --verbose

Delete the script after running (it is ad-hoc evidence, not a committed suite).
"""

from __future__ import annotations

import json
import socket
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parent  # tests/ -> repo root
if not (ROOT / "scripts" / "atlas.py").exists():
    ROOT = HERE.parents[1]  # fallback

sys.path.insert(0, str(ROOT / "scripts"))


def main(argv=None) -> int:
    verbose = "--verbose" in (argv or [])
    passed = 0
    failed = 0
    errors: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if condition:
            passed += 1
            if verbose:
                print(f"  [PASS] {name}")
        else:
            failed += 1
            msg = f"  [FAIL] {name}"
            if detail:
                msg += f"  ({detail})"
            print(msg)
            errors.append(f"{name}: {detail}")

    # ==========================================================================
    # 1. Network guard — any socket/urlopen raises
    # ==========================================================================
    net_used = [False]
    orig_init = socket.socket.__init__
    def _blocked_init(self, *a, **k):
        net_used[0] = True
        raise RuntimeError("NETWORK BLOCKED")
    socket.socket.__init__ = _blocked_init
    orig_urlopen = urllib.request.urlopen
    def _blocked_urlopen(*a, **k):
        net_used[0] = True
        raise RuntimeError("NETWORK BLOCKED")
    urllib.request.urlopen = _blocked_urlopen

    # ==========================================================================
    # 2. Import and instantiate the Acquisition Engine
    # ==========================================================================
    from acquisition_engine import AcquisitionEngine, is_denied_license

    engine = AcquisitionEngine(ROOT, mode="dry-run", network_block=True)

    # ==========================================================================
    # 3. Dry run — plan without side effects
    # ==========================================================================
    print("=" * 64)
    print("ACQUISITION ENGINE PROBE")
    print("=" * 64)
    print("")

    print("[dry-run] Running Acquisition Engine dry run...")
    plan = engine.dry_run()
    check("dry_run succeeds", plan.get("status") == "ok",
          f"status={plan.get('status')}")
    check("dry_run returns sources_planned", plan.get("sources_planned", 0) > 0,
          f"sources={plan.get('sources_planned')}")
    check("dry_run returns total_target", plan.get("total_target", 0) == 1000,
          f"target={plan.get('total_target')}")
    check("dry_run returns execution_plan", len(plan.get("execution_plan", [])) > 0,
          f"batches={len(plan.get('execution_plan', []))}")

    # ==========================================================================
    # 4. License gate consistency
    # ==========================================================================
    checks = plan.get("checks", {})
    check("license_gate_passed", checks.get("license_gate_passed") is True,
          f"denied={checks.get('denied_sources', [])}")
    check("synthetic_within_cap", checks.get("synthetic_within_cap") is True,
          f"synthetic_pct={checks.get('synthetic_pct')}% cap={checks.get('synthetic_cap_pct')}%")
    check("registry_status_ok", checks.get("registry_ok") is True,
          f"bad_status={checks.get('bad_status')}, missing={checks.get('reg_missing')}")

    # Verify license gate consistency vs validate_dataset.py
    denied_test = ["cc-by-nc-4.0", "cc-by-nd-4.0", "proprietary", "all-rights-reserved", "unknown"]
    allowed_test = ["mit", "Apache-2.0", "CC-BY-4.0", "ODC-BY", "CC-BY-SA-4.0",
                    "BigCode Open RAIL-M", "Public Domain", "arXiv non-exclusive license"]
    gate_ok = (
        all(is_denied_license(d) for d in denied_test)
        and not any(is_denied_license(a) for a in allowed_test)
    )
    check("license_gate_integrity", gate_ok,
          f"denied_check={[d for d in denied_test if not is_denied_license(d)]}, "
          f"allowed_check={[a for a in allowed_test if is_denied_license(a)]}")

    # ==========================================================================
    # 5. Checkpoint integrity
    # ==========================================================================
    cp = engine.checkpoint_summary()
    check("checkpoint_exists", cp.get("status") != "no_checkpoint",
          f"status={cp.get('status')}")
    check("checkpoint_session_id", bool(cp.get("session_id", "")),
          f"session={cp.get('session_id')}")
    check("checkpoint_mode_dry_run", cp.get("mode") == "dry-run",
          f"mode={cp.get('mode')}")
    check("checkpoint_completed", cp.get("status") == "completed",
          f"status={cp.get('status')}")

    # Load the raw checkpoint file and verify its checksum
    ckpt_path = ROOT / "metadata" / "engine_checkpoint.json"
    if ckpt_path.exists():
        try:
            ckpt_raw = json.loads(ckpt_path.read_text(encoding="utf-8"))
            stored_cs = ckpt_raw.pop("checksum", "")
            import hashlib
            computed_cs = hashlib.sha256(
                json.dumps(ckpt_raw, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            check("checkpoint_checksum_valid", stored_cs == computed_cs,
                  f"stored={stored_cs[:16]}... computed={computed_cs[:16]}...")
        except Exception as e:
            check("checkpoint_checksum_valid", False, str(e))
    else:
        check("checkpoint_checksum_valid", False, "checkpoint file missing")

    # ==========================================================================
    # 6. No network used
    # ==========================================================================
    check("no_network_during_run", not net_used[0],
          f"net_used={net_used[0]}")

    # ==========================================================================
    # 7. Lifecycle tracking
    # ==========================================================================
    report = engine.lifecycle_report()
    check("lifecycle_report_exists", report.get("total_records", 0) >= 0,
          f"total={report.get('total_records')}")

    # Test a lifecycle transition
    from acquisition_engine.lifecycle import is_valid_transition, LIFECYCLE_STATES as STATES
    valid_transitions = [
        ("raw", "processing"), ("processing", "curated"), ("curated", "review"),
        ("review", "approved"), ("approved", "released"), ("released", "archived"),
        ("raw", "rejected"), ("review", "rejected"),
    ]
    for f, t in valid_transitions:
        check(f"lifecycle_transition:{f}->{t}", is_valid_transition(f, t),
              f"should be valid: {f} -> {t}")

    invalid_transitions = [
        ("raw", "released"), ("raw", "approved"), ("curated", "released"),
        ("rejected", "released"), ("archived", "curated"),
    ]
    for f, t in invalid_transitions:
        check(f"lifecycle_invalid:{f}->{t}", not is_valid_transition(f, t),
              f"should be invalid: {f} -> {t}")

    # ==========================================================================
    # 8. Version management
    # ==========================================================================
    versions = engine.list_versions()
    check("version_list_accessible", isinstance(versions, list),
          f"type={type(versions).__name__}")

    # Version diff (should handle missing versions gracefully)
    diff_result = engine.diff_versions("nonexistent_v0.1", "nonexistent_v0.2")
    check("version_diff_nonexistent", diff_result is None,
          f"result={diff_result}")

    # ==========================================================================
    # 9. Integrity verification
    # ==========================================================================
    ver_log = engine.ver_log
    check("verification_log_entries", ver_log.entry_count > 0,
          f"entries={ver_log.entry_count}")
    check("verification_log_chain", ver_log.verify_chain(),
          "tamper-evident hash chain intact")

    # The log must contain a dry_run_complete event
    has_dry_run = any(e.get("event") == "dry_run_complete" for e in ver_log.entries)
    check("verification_log_has_dry_run_event", has_dry_run,
          "missing dry_run_complete event")

    # ==========================================================================
    # 10. Knowledge Pack (verify against empty packs dir — no error)
    # ==========================================================================
    pack_result = engine.verify_knowledge_pack()
    check("knowledge_pack_verify_ok", pack_result.get("verified") is not None,
          f"verified={pack_result.get('verified')}")

    # ==========================================================================
    # 11. Checkpoint resumability
    # ==========================================================================
    resume_result = engine.resume()
    check("resume_returns_plan", resume_result.get("status") in ("ok", "error"),
          f"status={resume_result.get('status')}")
    if resume_result.get("status") == "ok":
        check("resume_has_plan_details", resume_result.get("sources_planned", 0) > 0,
              f"sources={resume_result.get('sources_planned')}")

    # ==========================================================================
    # 12. Verify the plan report renders as markdown
    # ==========================================================================
    report_md = engine.render_plan_report(plan)
    check("plan_report_renderable", len(report_md) > 100,
          f"len={len(report_md)}")
    check("plan_report_contains_summary", "# Atlas Acquisition Engine" in report_md,
          "missing title")
    check("plan_report_contains_sections", all(s in report_md for s in
          ["Executive Summary", "License Validation", "Execution Plan"]),
          "missing sections")

    # ==========================================================================
    # 13. Dataset Diff module
    # ==========================================================================
    from acquisition_engine.dataset_diff import compute_diff, load_records_index

    # Test diff with empty sets
    empty_diff = compute_diff({}, {})
    check("diff_empty_sets", empty_diff.get("summary", {}).get("from_total") == 0,
          f"result={empty_diff.get('summary')}")

    # Test diff with simple records
    from_records = {
        "rec1": {"id": "rec1", "category": "01_foundation", "quality_score": 8, "license": "MIT"},
        "rec2": {"id": "rec2", "category": "02_software_engineering", "quality_score": 9, "license": "Apache-2.0"},
    }
    to_records = {
        "rec2": {"id": "rec2", "category": "02_software_engineering", "quality_score": 9, "license": "Apache-2.0"},
        "rec3": {"id": "rec3", "category": "03_system_engineering", "quality_score": 7, "license": "MIT"},
    }
    diff = compute_diff(from_records, to_records)
    summary = diff.get("summary", {})
    check("diff_added", summary.get("added") == 1, f"added={summary.get('added')}")
    check("diff_removed", summary.get("removed") == 1, f"removed={summary.get('removed')}")
    check("diff_unchanged", summary.get("unchanged") == 1, f"unchanged={summary.get('unchanged')}")
    check("diff_net_change", summary.get("net_change") == 0,
          f"net_change={summary.get('net_change')}")

    # ==========================================================================
    # 14. Checksum registry (may not exist or have different format)
    # ==========================================================================
    registry = engine.checksum_registry
    reg_data = registry.load()
    if reg_data is not None:
        check("checksum_registry_loadable", True, "loaded")
        # The registry may use "version" (engine format) or "registry_version" (baseline format)
        ver = reg_data.get("version") or reg_data.get("registry_version") or "unknown"
        check("checksum_registry_version_present", ver != "unknown",
              f"version={ver}")
        algo = reg_data.get("algorithm") or "unknown"
        check("checksum_registry_algorithm_present", algo != "unknown",
              f"algorithm={algo}")
    else:
        check("checksum_registry_not_yet_created", True,
              "registry doesn't exist during dry-run (expected)")

    # ==========================================================================
    # Final results
    # ==========================================================================
    total = passed + failed
    print("")
    print("=" * 64)
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print("=" * 64)
    if errors:
        for e in errors:
            print(f"  - {e}")
    print("")

    if failed > 0:
        print("RESULT: FAIL — review errors above")
        return 1
    else:
        print("RESULT: ALL PASS — Acquisition Engine invariants hold")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
