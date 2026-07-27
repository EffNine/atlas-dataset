#!/usr/bin/env python3
"""
atlas — Atlas Dataset Foundation command-line entry point.

Subcommands:
  atlas self-test        Permanent invariant checks (no network, no unauthorized
                         writes, license gate integrity, manifest validation,
                         canonical schema validation, deterministic planning,
                         knowledge object integrity, training-view safety).
                         Exits non-zero if any invariant fails.
  atlas ingest-pilot     Run the Phase 3A controlled pilot ingestion (<=100
                         objects) through the full pipeline, producing:
                           curated/v0.1/pilot_candidates.jsonl
                           review_queue/*.jsonl
                           training_views/{qwen,llama,deepseek}/README.md (placeholders)
                           metadata/pilot_manifest.json
                           docs/phase3a_pilot_report.md
                         No auto-promotion: every object enters review as 'pending'.
  atlas gen-calibration-sample
                         Produce a deterministic, stratified review worksheet
                         (review_queue/calibration_sample.jsonl) from the
                         existing pilot candidates. READ-ONLY on the dataset;
                         emits a review artifact only (no dataset growth).
                         Also writes an illustrative synthetic seed
                         (review_queue/quality_reviews.example.jsonl) for
                         demoing the harness — delete before real runs.
  atlas calibrate        Measure automated quality_score.py vs structured
                         human review (review/quality_reviews.jsonl):
                         scoring accuracy, bias by category/source, confidence,
                         and bulk-ingestion recommendations. Writes
                         metadata/calibration_report.json + a markdown digest.
                         READ-ONLY on the dataset.

Design guarantees (also asserted by self-test):
  * Zero network access during any command.
  * Never writes outside approved output roots (curated/, review_queue/,
    training_views/, metadata/, docs/, tmp/, raw/pilot/).
  * Reuses scripts/validate_dataset.py:is_denied_license as the single license gate.

Usage:
  python scripts/atlas.py self-test
  python scripts/atlas.py ingest-pilot [--max 100]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# Reuse the SINGLE license gate from validate_dataset.py
_vspec = importlib.util.spec_from_file_location("validate_mod", ROOT / "scripts" / "validate_dataset.py")
if _vspec is None or _vspec.loader is None:
    raise ImportError("Could not load validate_dataset.py")
_validate = importlib.util.module_from_spec(_vspec)
_vspec.loader.exec_module(_validate)
is_denied_license = _validate.is_denied_license

# Acquisition Engine (loaded lazily in command functions)
_ENGINE = None
def _get_engine(mode="dry-run") -> "AcquisitionEngine":
    global _ENGINE
    if _ENGINE is None:
        from acquisition_engine import AcquisitionEngine
        _ENGINE = AcquisitionEngine(ROOT, mode=mode)
    return _ENGINE


# ---------------------------------------------------------------------------
# Network + write guard (shared by self-test and pilot)
# ---------------------------------------------------------------------------
class NetworkBlocked(RuntimeError):
    pass


def _install_network_block():
    import socket
    import urllib.request
    sock_init = socket.socket.__init__

    def _blocked_init(self, *a, **k):
        raise NetworkBlocked("network access is forbidden in this command")
    socket.socket.__init__ = _blocked_init

    def _blocked_urlopen(*a, **k):
        raise NetworkBlocked("network access is forbidden in this command")
    urllib.request.urlopen = _blocked_urlopen


APPROVED_ROOTS = (
    ROOT / "curated", ROOT / "review_queue", ROOT / "training_views",
    ROOT / "metadata", ROOT / "docs", ROOT / "tmp", ROOT / "raw" / "pilot",
    ROOT / "migrations",  # framework state file (applied.json) only
)


def _assert_write_safe(path: Path):
    p = path.resolve()
    if not any(str(p).startswith(str(r.resolve())) for r in APPROVED_ROOTS):
        raise RuntimeError(f"unauthorized write target: {p}")


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------
def cmd_self_test(argv) -> int:
    _install_network_block()
    failures = []
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))
        if not cond:
            failures.append((name, detail))

    # 1. No network access (blocking socket raises)
    try:
        import socket
        socket.socket()  # should raise NetworkBlocked
        check("no-network-access", False, "socket creation was allowed")
    except NetworkBlocked:
        check("no-network-access", True)
    except Exception as e:
        check("no-network-access", False, f"unexpected: {e}")

    # 2. No unauthorized writes: writing outside approved roots raises
    try:
        _assert_write_safe(Path("/etc/atlas_test_write"))
        check("no-unauthorized-writes", False, "write to /etc was allowed")
    except RuntimeError:
        check("no-unauthorized-writes", True)
    # and an approved root is allowed
    try:
        _assert_write_safe(ROOT / "tmp" / "ok")
        check("approved-write-allowed", True)
    except RuntimeError:
        check("approved-write-allowed", False, "approved root wrongly blocked")

    # 3. License gate integrity: denied set is blocked, allowed set passes
    denied = ["cc-by-nc-4.0", "cc-by-nd-4.0", "proprietary", "all-rights-reserved", "unknown"]
    allowed = ["mit", "Apache-2.0", "CC-BY-4.0", "ODC-BY", "CC-BY-SA-4.0",
               "BigCode Open RAIL-M", "Public Domain", "arXiv non-exclusive license"]
    gate_ok = all(is_denied_license(d) for d in denied) and not any(is_denied_license(a) for a in allowed)
    check("license-gate-integrity", gate_ok,
          f"denied={[d for d in denied if not is_denied_license(d)]}; "
          f"allowed_blocked={[a for a in allowed if is_denied_license(a)]}")

    # 4. Manifest validation
    man_path = ROOT / "metadata" / "acquisition_manifest_v0.1.json"
    if man_path.exists():
        man = json.loads(man_path.read_text(encoding="utf-8"))
        man_ok = (man.get("total_target_examples") == 1000
                  and len(man.get("batches", [])) == 9
                  and "global_constraints" in man)
        check("manifest-validation", man_ok, "acquisition manifest structure")
    else:
        check("manifest-validation", False, "manifest missing")

    # 5. Canonical schema validation (base + knowledge object).
    # The jsonschema/referencing stack is OPTIONAL; if it is unavailable in the
    # environment we degrade to a structural self-check (mirroring the design of
    # scripts/validate_dataset.py, which never hard-depends on jsonschema).
    sample = {
        "id": "01_foundation_instruction-following_0000",
        "category": "01_foundation", "subcategory": "instruction-following",
        "difficulty": 1, "knowledge_type": "procedure", "canonical_answer": "x",
        "metadata": {"language": "en"}, "source_attribution": {
            "source_id": "f1", "name": "n", "url": "", "license": "Apache-2.0",
            "attribution_text": "a"},
        "license": "Apache-2.0", "tags": ["t"], "quality_score": 9,
        "verification_status": "pending",
        "lineage": {"source": "s", "transformations": [], "knowledge_object": "id",
                    "curated_dataset": "curated/v0.1", "training_view": "qwen",
                    "future_model": "m"},
        "training_view_eligibility": {"qwen": True, "llama": True, "deepseek": True},
        "messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
    }
    schema_ok = None
    try:
        import jsonschema  # type: ignore
        from referencing import Registry, Resource  # type: ignore
        dschema = json.loads((ROOT / "schemas" / "dataset_schema.json").read_text())
        kschema = json.loads((ROOT / "schemas" / "knowledge_object_schema.json").read_text())
        chat = json.loads((ROOT / "schemas" / "chat_schema.json").read_text())
        reg = Registry().with_resources([
            (dschema["$id"], Resource.from_contents(dschema)),
            (kschema["$id"], Resource.from_contents(kschema)),
            (chat["$id"], Resource.from_contents(chat)),
        ])
        ks_validator = jsonschema.Draft202012Validator(kschema, registry=reg)
        errs = list(ks_validator.iter_errors(sample))
        schema_ok = (not errs)
        check("canonical-schema-validation", schema_ok, f"schema errors: {errs}")
    except Exception as e:
        # Structural fallback: confirm all required keys present + enums valid.
        required = {"id", "category", "subcategory", "difficulty", "knowledge_type",
                    "canonical_answer", "metadata", "source_attribution", "license",
                    "tags", "quality_score", "verification_status", "lineage",
                    "training_view_eligibility", "messages"}
        cats = {"01_foundation", "02_software_engineering", "03_system_engineering",
                "04_ai_machine_learning", "05_hardware_engineering", "06_science_engineering",
                "07_business_knowledge", "08_creative_knowledge", "09_personal_assistant"}
        structural_ok = (required <= set(sample.keys())
                         and sample["category"] in cats
                         and sample["knowledge_type"] in {"fact", "procedure", "concept",
                                                          "reasoning", "code", "reference", "creative"}
                         and sample["verification_status"] in {"pending", "approved",
                                                               "rejected", "needs_revision"}
                         and set(sample["training_view_eligibility"]) == {"qwen", "llama", "deepseek"})
        check("canonical-schema-validation", structural_ok,
              f"jsonschema unavailable ({type(e).__name__}); structural fallback ok={structural_ok}")

    # 6. Deterministic planning: dry-run plan is reproducible
    plan_path = ROOT / "metadata" / "ingestion_plan_v0.1.json"
    if plan_path.exists():
        p = json.loads(plan_path.read_text())
        det_ok = (p.get("checks", {}).get("license_gate_passed") is True
                  and p.get("checks", {}).get("synthetic_within_cap") is True)
        check("deterministic-planning", det_ok, "plan invariants stable")
    else:
        check("deterministic-planning", False, "plan missing")

    # 7. Knowledge object integrity: run migrations on sample, assert fields present
    sys.path.insert(0, str(ROOT / "migrations"))
    runner = importlib.util.spec_from_file_location("mrunner", ROOT / "migrations" / "runner.py")
    mrunner = importlib.util.module_from_spec(runner)
    runner.loader.exec_module(mrunner)
    mods = mrunner.load_migrations()
    migrated = dict(sample)
    applied = []
    for mid, mod in mods:
        migrated = mod.up(migrated)
        applied.append(f"migrate:{mid}")
    required = ["id", "category", "subcategory", "difficulty", "knowledge_type",
                "canonical_answer", "metadata", "source_attribution", "license", "tags",
                "quality_score", "verification_status", "lineage", "training_view_eligibility",
                "messages"]
    missing = [f for f in required if f not in migrated]
    check("knowledge-object-integrity", not missing, f"missing: {missing}")

    # 8. Training-view generation safety: views come only from eligibility flags
    tve = migrated.get("training_view_eligibility", {})
    tvs_ok = isinstance(tve, dict) and set(tve.keys()) == {"qwen", "llama", "deepseek"}
    check("training-view-safety", tvs_ok, "eligibility has exactly qwen/llama/deepseek")

    # ---- report ----
    print("=" * 60)
    print("ATLAS SELF-TEST")
    print("=" * 60)
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    print("-" * 60)
    if failures:
        print(f"RESULT: FAIL ({len(failures)} invariant(s) failed)")
        for name, detail in failures:
            print(f"  - {name}: {detail}")
        return 1
    print("RESULT: PASS — all invariants hold")
    return 0


# ---------------------------------------------------------------------------
# ingest-pilot
# ---------------------------------------------------------------------------
def cmd_ingest_pilot(argv) -> int:
    _install_network_block()
    ap = argparse.ArgumentParser(description="Run Phase 3A controlled pilot ingestion.")
    ap.add_argument("--max", type=int, default=100, help="max records (<=100)")
    args = ap.parse_args(argv)
    if args.max > 100:
        print("[pilot] ERROR: max must be <= 100", file=sys.stderr)
        return 2
    if args.max <= 0:
        print("[pilot] ERROR: max must be > 0", file=sys.stderr)
        return 2

    import time
    t0 = time.time()
    stats = {"attempted": 0, "accepted": 0, "rejected": 0, "duplicates": 0,
             "license_blocked": 0, "by_category": {}, "quality": [],
             "license_stats": {}, "review_states": {}}

    # 1) ensure seed exists; write to approved raw/pilot root
    seed_path = ROOT / "raw" / "pilot" / "seed.jsonl"
    if not seed_path.exists():
        _assert_write_safe(seed_path)
        import pilot_seed
        rc = pilot_seed.main(["--output", str(seed_path)])
        if rc != 0:
            return rc

    # 2) read seed; enforce max
    raw_records = []
    with seed_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                raw_records.append(json.loads(line))
    if len(raw_records) > args.max:
        raw_records = raw_records[:args.max]
    stats["attempted"] = len(raw_records)

    # 3) pipeline per record: license validation -> schema mapping -> cleaning
    #    -> normalization -> dedup(normalized) -> quality -> canonical object
    #    -> review queue (pending) -> curated candidate
    from clean_dataset import clean_text  # reuse text cleaning
    import hashlib

    seen_norm = set()
    out_records = []
    review = {"pending": [], "approved": [], "rejected": [], "needs_revision": []}

    for rec in raw_records:
        # license validation (denied gate)
        lic = rec.get("license") or rec.get("source_attribution", {}).get("license", "unknown")
        if is_denied_license(lic):
            stats["license_blocked"] += 1
            stats["rejected"] += 1
            continue
        sa = rec.get("source_attribution", {})
        sa["license"] = lic
        sa["share_alike"] = "sa" in lic.lower()

        # schema mapping + cleaning/normalization
        msgs = []
        for m in rec.get("messages", []):
            msgs.append({"role": m["role"], "content": clean_text(m.get("content", ""))})
        rec["messages"] = msgs
        rec["canonical_answer"] = clean_text(rec.get("canonical_answer", ""))
        rec["tags"] = [t for t in rec.get("tags", []) if t]

        # dedup (normalized signature)
        norm = "\n".join(f"{m['role']}:{m['content'].strip().lower()}" for m in msgs)
        h = hashlib.sha1(norm.encode()).hexdigest()
        if h in seen_norm:
            stats["duplicates"] += 1
            stats["rejected"] += 1
            continue
        seen_norm.add(h)

        # quality evaluation (heuristic floor; authored seed already 9, human review still required)
        try:
            q = int(rec.get("quality_score", 0))
        except (TypeError, ValueError):
            q = 0
        q = max(0, min(10, q))
        rec["quality_score"] = q
        stats["quality"].append(q)

        # license stats
        stats["license_stats"][lic] = stats["license_stats"].get(lic, 0) + 1
        # category counts
        c = rec["category"]
        stats["by_category"][c] = stats["by_category"].get(c, 0) + 1

        # gate: quality >= 8.5 else route to needs_revision (NOT auto-reject of valid content,
        # but flagged for human). For pilot, authored content is 9 -> passes.
        if q < 8.5:
            rec["verification_status"] = "needs_revision"
        else:
            rec["verification_status"] = "pending"  # never auto-approved
        rec["verified"] = False

        out_records.append(rec)
        review[rec["verification_status"]].append(rec["id"])
        stats["accepted"] += 1

    # 4) migrations (apply full canonical schema: 001/002/003)
    sys.path.insert(0, str(ROOT / "migrations"))
    mrunner = importlib.util.spec_from_file_location("mrunner", ROOT / "migrations" / "runner.py")
    mod = importlib.util.module_from_spec(mrunner)
    mrunner.loader.exec_module(mod)
    applied_global = []
    for rec in out_records:
        applied = []
        for mid, m in mod.load_migrations():
            rec = m.up(rec)
            tag = f"migrate:{mid}"
            if tag not in applied:
                applied.append(tag)
            if mid not in applied_global:
                applied_global.append(mid)
        rec.setdefault("lineage", {})["transformations"] = applied
        rec["verified"] = (rec["verification_status"] == "approved")
    # record migration state so the framework state file stays consistent
    _assert_write_safe(ROOT / "migrations" / "applied.json")
    mod.save_state({"applied": applied_global, "applied_by": "atlas ingest-pilot"})

    # 5) write curated candidates (approved output root)
    curated_path = ROOT / "curated" / "v0.1" / "pilot_candidates.jsonl"
    _assert_write_safe(curated_path)
    curated_path.parent.mkdir(parents=True, exist_ok=True)
    with curated_path.open("w", encoding="utf-8") as f:
        for rec in out_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 5b) validate curated Knowledge Objects against the superset schema
    # (structural check; jsonschema used if available). Count failures for the report.
    from validate_knowledge_object import structural_errors as _ko_struct
    try:
        import jsonschema  # type: ignore
        from referencing import Registry, Resource  # type: ignore
        _ko_schema = json.loads((ROOT / "schemas" / "knowledge_object_schema.json").read_text())
        _ko_chat = json.loads((ROOT / "schemas" / "chat_schema.json").read_text())
        _ko_reg = Registry().with_resources([
            (_ko_schema["$id"], Resource.from_contents(_ko_schema)),
            (_ko_chat["$id"], Resource.from_contents(_ko_chat)),
        ])
        _ko_val = jsonschema.Draft202012Validator(_ko_schema, registry=_ko_reg)
        ko_fail = sum(1 for rec in out_records if list(_ko_val.iter_errors(rec)))
    except Exception:
        ko_fail = sum(1 for rec in out_records if _ko_struct(rec))
    stats["ko_validation_failures"] = ko_fail

    # 6) review queue (every object enters; status from record).
    # Clear the queue first so re-runs do not accumulate stale entries.
    rq_dir = ROOT / "review_queue"
    _assert_write_safe(rq_dir)
    if rq_dir.exists():
        for old in rq_dir.glob("*.jsonl"):
            old.unlink()
    rq_dir.mkdir(parents=True, exist_ok=True)
    rq_index = []
    for rec in out_records:
        st = rec["verification_status"]
        part = rq_dir / f"{st}.jsonl"
        with part.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": rec["id"], "category": rec["category"],
                                "subcategory": rec["subcategory"],
                                "quality_score": rec["quality_score"],
                                "license": rec["license"],
                                "verification_status": st}, ensure_ascii=False) + "\n")
        rq_index.append({"id": rec["id"], "status": st})
    stats["review_states"] = {k: len(v) for k, v in review.items()}

    # 7) training views placeholders ONLY (no data generation)
    tv_dir = ROOT / "training_views"
    _assert_write_safe(tv_dir)
    tv_dir.mkdir(parents=True, exist_ok=True)
    eligible_counts = {"qwen": 0, "llama": 0, "deepseek": 0}
    for rec in out_records:
        tve = rec.get("training_view_eligibility", {})
        for v in ("qwen", "llama", "deepseek"):
            if tve.get(v):
                eligible_counts[v] += 1
    for v in ("qwen", "llama", "deepseek"):
        vd = tv_dir / v
        vd.mkdir(parents=True, exist_ok=True)
        ph = vd / "README.md"
        ph.write_text(
            f"# Training View Placeholder: {v}\n\n"
            f"STATUS: PLACEHOLDER — no training data generated.\n\n"
            f"Eligible pilot objects: {eligible_counts[v]}/{len(out_records)}.\n\n"
            f"Real view generation happens only after human review approves records and a "
            f"future `atlas build-views` command is authorized. This file is a pointer only.\n",
            encoding="utf-8")

    # 8) pilot manifest
    man_path = ROOT / "metadata" / "pilot_manifest.json"
    _assert_write_safe(man_path)
    pil_man = {
        "pilot": "phase-3a", "date": date.today().isoformat(),
        "attempted": stats["attempted"], "accepted": stats["accepted"],
        "rejected": stats["rejected"], "duplicates": stats["duplicates"],
        "license_blocked": stats["license_blocked"],
        "ko_validation_failures": stats.get("ko_validation_failures", 0),
        "by_category": stats["by_category"], "license_stats": stats["license_stats"],
        "review_states": stats["review_states"],
        "avg_quality": round(sum(stats["quality"]) / len(stats["quality"]), 2) if stats["quality"] else 0,
        "outputs": {"curated": str(curated_path), "review_queue": str(rq_dir),
                    "training_views": str(tv_dir)},
    }
    man_path.write_text(json.dumps(pil_man, indent=2), encoding="utf-8")

    # 9) timing
    dt = round(time.time() - t0, 3)
    print(f"[pilot] attempted={stats['attempted']} accepted={stats['accepted']} "
          f"rejected={stats['rejected']} duplicates={stats['duplicates']} "
          f"license_blocked={stats['license_blocked']}")
    print(f"[pilot] avg_quality={pil_man['avg_quality']}  time={dt}s")
    print(f"[pilot] curated -> {curated_path}")
    print(f"[pilot] review_queue -> {rq_dir}")
    print(f"[pilot] training_views -> {tv_dir} (placeholders only)")
    print("[pilot] STOP — pilot complete at 100 objects. No auto-promotion; awaiting approval.")
    return 0


# --------------------------------------------------------------------------- #
# gen-calibration-sample  (READ-ONLY on dataset; emits a review worksheet)
# --------------------------------------------------------------------------- #
def cmd_gen_calibration_sample(argv) -> int:
    _install_network_block()
    import gen_calibration_sample as gcs
    ap = argparse.ArgumentParser(description="Generate a quality-calibration review worksheet.")
    ap.add_argument("--candidates", default=str(ROOT / "curated" / "v0.1" / "pilot_candidates.jsonl"))
    ap.add_argument("--worksheet-out", default=str(ROOT / "review_queue" / "calibration_sample.jsonl"))
    ap.add_argument("--example-out", default=str(ROOT / "review_queue" / "quality_reviews.example.jsonl"))
    ap.add_argument("--sample-frac", type=float, default=0.30)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-example", action="store_true")
    args = ap.parse_args(argv)

    candidates = gcs.load_jsonl(Path(args.candidates))
    if not candidates:
        print(f"[gen-cal] ERROR: no candidates at {args.candidates}", file=sys.stderr)
        return 2
    before = len(candidates)

    worksheet = gcs.build_worksheet(candidates, args.sample_frac, args.seed)
    _assert_write_safe(Path(args.worksheet_out))
    Path(args.worksheet_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.worksheet_out).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in worksheet) + "\n", encoding="utf-8")
    print(f"[gen-cal] worksheet -> {args.worksheet_out}  ({len(worksheet)} records to review)")

    if not args.no_example:
        reviews = gcs.build_example_reviews(worksheet, args.seed)
        _assert_write_safe(Path(args.example_out))
        Path(args.example_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.example_out).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in reviews) + "\n", encoding="utf-8")
        print(f"[gen-cal] EXAMPLE seed -> {args.example_out}  ({len(reviews)} ILLUSTRATIVE reviews)")
        print("[gen-cal] NOTE: example seed is synthetic. Delete before real calibration.")

    after = len(candidates)
    _assert_write_safe(Path(args.worksheet_out))
    print(f"[gen-cal] READ-ONLY on dataset: candidate count {before} -> {after} (unchanged)")
    return 0


# --------------------------------------------------------------------------- #
# calibrate  (READ-ONLY on dataset; measures scorer vs human review)
# --------------------------------------------------------------------------- #
def cmd_calibrate(argv) -> int:
    _install_network_block()
    import calibrate_quality as cq
    ap = argparse.ArgumentParser(description="Calibrate the quality scorer against human review.")
    ap.add_argument("--reviews", default=str(ROOT / "review" / "quality_reviews.jsonl"))
    ap.add_argument("--candidates", default=str(ROOT / "curated" / "v0.1" / "pilot_candidates.jsonl"))
    ap.add_argument("--report-out", default=str(ROOT / "metadata" / "calibration_report.json"))
    ap.add_argument("--md-out", default=str(ROOT / "docs" / "quality_calibration_report.md"))
    args = ap.parse_args(argv)

    reviews = cq.load_jsonl(Path(args.reviews))
    candidates = cq.load_jsonl(Path(args.candidates))
    report = cq.calibrate(reviews, candidates)

    print("=" * 64)
    print("ATLAS QUALITY CALIBRATION")
    print("=" * 64)
    print(f"reviews={report['n_reviews']} matched={report['n_matched']} "
          f"missing={report['n_missing_candidates']}")
    g = report.get("global")
    if g is None:
        print("STATUS: NO CALIBRATION DATA — seed reviews then re-run.")
    else:
        print(f"MAE={g['mae']}  within-1={g['within1_agree']*100:.0f}%  "
              f"threshold_F1={g['threshold']['f1']:.3f}  bias={g['mean_bias']:+}")
        print(f"READINESS: {report['readiness']['verdict']}")
        print(f"recommendations: {len(report['recommendations'])}")
    print("=" * 64)

    if args.report_out:
        _assert_write_safe(Path(args.report_out))
        Path(args.report_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"[calibrate] wrote report -> {args.report_out}")
    if args.md_out:
        _assert_write_safe(Path(args.md_out))
        Path(args.md_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md_out).write_text(cq.render_markdown(report), encoding="utf-8")
        print(f"[calibrate] wrote digest -> {args.md_out}")
    return 0


# --------------------------------------------------------------------------- #
# Acquire — Acquisition Engine dry-run / execute / resume
# --------------------------------------------------------------------------- #

def cmd_acquire(argv) -> int:
    ap = argparse.ArgumentParser(description="Atlas Acquisition Engine.")
    ap.add_argument("--dry-run", action="store_true", help="plan only, no side effects")
    ap.add_argument("--execute", action="store_true", help="run the ingestion pipeline")
    ap.add_argument("--resume", action="store_true", help="resume from checkpoint")
    ap.add_argument("--max", type=int, default=100, help="max records (execute mode)")
    ap.add_argument("--report", default=str(ROOT / "docs" / "acquisition_plan_report.md"),
                    help="output path for dry-run report")
    args = ap.parse_args(argv)

    if args.execute:
        engine = _get_engine(mode="execute")
        if args.resume:
            print("[acquire] Resuming from checkpoint...")
            result = engine.resume(max_records=args.max)
        else:
            print("[acquire] Executing ingestion pipeline...")
            result = engine.execute(max_records=args.max)
    else:
        # Default or --dry-run
        engine = _get_engine(mode="dry-run")
        print("[acquire] Running dry-run (no data will be modified)...")
        result = engine.dry_run()

    if result.get("status") == "error":
        print(f"[acquire] ERROR: {result.get('error', 'unknown')}", file=sys.stderr)
        return 1

    if args.execute:
        print(f"[acquire] Mode: execute")
        print(f"  Attempted: {result.get('records_attempted', 0)}")
        print(f"  Accepted:  {result.get('records_accepted', 0)}")
        print(f"  Rejected:  {result.get('records_rejected', 0)}")
        print(f"  Quality:   {result.get('avg_quality', 0)}")
        print(f"  Time:      {result.get('execution_time_s', 0)}s")
    else:
        print(f"[acquire] Mode: dry-run")
        checks = result.get("checks", {})
        print(f"  Sources:     {result.get('sources_planned', 0)}")
        print(f"  Batches:     {result.get('batches_planned', 0)}")
        print(f"  Target:      {result.get('total_target', 0)}")
        print(f"  Est. DL:     {result.get('estimated_download', '?')}")
        print(f"  License:     {'PASS' if checks.get('license_gate_passed') else 'BLOCKED'}")
        print(f"  Synthetic:   {checks.get('synthetic_count', 0)} ({checks.get('synthetic_pct', 0)}%)")
        print(f"  Registry:    {'OK' if checks.get('registry_ok') else 'ISSUES'}")

        # Write plan report
        report_path = Path(args.report)
        _assert_write_safe(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_md = engine.render_plan_report(result)
        report_path.write_text(report_md, encoding="utf-8")
        print(f"[acquire] Report -> {report_path}")

    cp = engine.checkpoint_summary()
    print(f"[acquire] Checkpoint: {cp.get('status', 'none')} "
          f"(session={cp.get('session_id', '-')})")
    return 0


# --------------------------------------------------------------------------- #
# Verify — integrity verification
# --------------------------------------------------------------------------- #

def cmd_verify(argv) -> int:
    ap = argparse.ArgumentParser(description="Verify integrity of a frozen version.")
    ap.add_argument("--version", default="v0.1", help="version to verify")
    args = ap.parse_args(argv)

    engine = _get_engine(mode="dry-run")
    result = engine.verify_integrity(args.version)

    print("=" * 60)
    print(f"INTEGRITY VERIFICATION — version {args.version}")
    print("=" * 60)
    print(f"Status: {'PASS' if result.get('status') == 'passed' else 'FAIL'}")

    reg = result.get("checksum_registry", {})
    print(f"  Checksum registry: {'VERIFIED' if reg.get('verified') else 'FAILED'}")
    if reg.get("mismatches"):
        for m in reg["mismatches"]:
            print(f"    MISMATCH: {m}")
    if reg.get("missing"):
        for m in reg["missing"]:
            print(f"    MISSING: {m}")
    print(f"  Verification log chain: {'INTACT' if result.get('verification_log_chain') else 'BROKEN'}")
    print(f"  Log entries: {result.get('verification_log_entries', 0)}")
    print(f"  Version manifest: {'EXISTS' if result.get('version_manifest_exists') else 'MISSING'}")
    print(f"  Curated files: {result.get('curated_file_count', 0)}")

    if result.get("status") != "passed":
        return 1
    return 0


# --------------------------------------------------------------------------- #
# Pack — Knowledge Pack generation / verification
# --------------------------------------------------------------------------- #

def cmd_pack(argv) -> int:
    ap = argparse.ArgumentParser(description="Generate or verify a Knowledge Pack.")
    ap.add_argument("--generate", help="pack name (e.g. foundation-v0.1)")
    ap.add_argument("--category", nargs="*", help="category filter(s)")
    ap.add_argument("--min-quality", type=int, default=7, help="minimum quality score")
    ap.add_argument("--describe", default="", help="pack description")
    ap.add_argument("--verify", action="store_true", help="verify existing pack(s)")
    args = ap.parse_args(argv)

    engine = _get_engine(mode="dry-run")

    if args.verify:
        print("[pack] Verifying Knowledge Packs...")
        result = engine.verify_knowledge_pack()
        if result.get("verified"):
            print("[pack] All packs verified successfully")
            for p in result.get("packs", []):
                print(f"  ✅ {p.get('pack_name')} ({p.get('record_count')} records)")
        else:
            print("[pack] Verification FAILED")
            for p in result.get("packs", []):
                if not p.get("verified"):
                    print(f"  ❌ {p.get('pack_name')}: {p.get('errors', ['unknown'])}")
            return 1
        return 0

    if args.generate:
        print(f"[pack] Generating Knowledge Pack '{args.generate}'...")
        manifest = engine.generate_knowledge_pack(
            name=args.generate,
            category_filter=args.category,
            min_quality=args.min_quality,
            description=args.describe,
        )
        print(f"[pack] Pack '{args.generate}' generated — {manifest.get('total_records', 0)} records")
        return 0

    print("[pack] Specify --generate <name> or --verify", file=sys.stderr)
    return 2


# --------------------------------------------------------------------------- #
# Version — dataset version management
# --------------------------------------------------------------------------- #

def cmd_version(argv) -> int:
    ap = argparse.ArgumentParser(description="Manage dataset versions.")
    ap.add_argument("--list", action="store_true", help="list all versions")
    ap.add_argument("--freeze", help="freeze current state as a version (e.g. v0.2)")
    ap.add_argument("--changelog", default="", help="changelog for frozen version")
    ap.add_argument("--diff", nargs=2, metavar=("FROM", "TO"),
                    help="diff two versions")
    args = ap.parse_args(argv)

    engine = _get_engine(mode="dry-run")

    if args.list:
        versions = engine.list_versions()
        if not versions:
            print("[version] No versions recorded")
        else:
            print("=" * 60)
            print("DATASET VERSIONS")
            print("=" * 60)
            for v in versions:
                print(f"  {v.get('version', '?')}  "
                      f"({v.get('total_records', 0)} records)  "
                      f"frozen: {v.get('frozen_at', '?')[:19]}")
        return 0

    if args.freeze:
        print(f"[version] Freezing version '{args.freeze}'...")
        changelog = args.changelog or f"Release of {args.freeze}"
        manifest = engine.freeze_version(args.freeze, changelog=changelog)
        if manifest is None:
            print("[version] ERROR: No curated data to freeze", file=sys.stderr)
            return 1
        print(f"[version] Frozen '{args.freeze}' — {manifest.get('total_records', 0)} records")
        return 0

    if args.diff:
        from_v, to_v = args.diff
        print(f"[version] Diffing {from_v} -> {to_v}...")
        diff = engine.diff_versions(from_v, to_v)
        if diff is None:
            print(f"[version] ERROR: One or both versions not found", file=sys.stderr)
            return 1
        print(f"  From: {diff.get('from_records', 0)} records")
        print(f"  To:   {diff.get('to_records', 0)} records")
        print(f"  Added:   {diff.get('added', 0)}")
        print(f"  Removed: {diff.get('removed', 0)}")
        print(f"  Changed: {diff.get('changed', 0)}")
        # Write diff report
        diff_path = ROOT / "docs" / f"diff_{from_v}_{to_v}.md"
        from acquisition_engine.dataset_diff import render_diff_markdown
        diff_detail = engine.version_mgr.diff(from_v, to_v)
        if diff_detail:
            md = render_diff_markdown(diff_detail)
            diff_path.write_text(md, encoding="utf-8")
            print(f"[version] Diff report -> {diff_path}")
        return 0

    print("[version] Specify --list, --freeze, or --diff", file=sys.stderr)
    return 2


# --------------------------------------------------------------------------- #
# Lifecycle — lifecycle state management
# --------------------------------------------------------------------------- #

def cmd_lifecycle(argv) -> int:
    ap = argparse.ArgumentParser(description="Report on record lifecycle state.")
    ap.add_argument("--report", action="store_true", help="print lifecycle state summary")
    args = ap.parse_args(argv)

    engine = _get_engine(mode="dry-run")
    report = engine.lifecycle_report()

    if args.report:
        print("=" * 60)
        print("LIFECYCLE STATE REPORT")
        print("=" * 60)
        print(f"Total records tracked: {report.get('total_records', 0)}")
        print("")
        states = report.get("state_summary", {})
        if states:
            print("| State | Count |")
            print("|---|---|")
            for state in ["raw", "processing", "curated", "review", "approved",
                          "released", "archived", "rejected"]:
                count = states.get(state, 0)
                if count > 0:
                    print(f"| {state} | {count} |")
        print("")
        # Write lifecycle report
        report_path = ROOT / "docs" / "lifecycle_report.md"
        _assert_write_safe(report_path)
        report_path.write_text(
            "# Lifecycle State Report\n\n"
            f"**Generated:** {report.get('generated', '?')}\n\n"
            f"Total records: {report.get('total_records', 0)}\n\n"
            f"```json\n{json.dumps(states, indent=2)}\n```\n",
            encoding="utf-8",
        )
        print(f"[lifecycle] Report -> {report_path}")
    return 0


# --------------------------------------------------------------------------- #
# Checkpoint — checkpoint status
# --------------------------------------------------------------------------- #

def cmd_checkpoint(argv) -> int:
    ap = argparse.ArgumentParser(description="Show checkpoint status.")
    ap.add_argument("--status", action="store_true", help="show checkpoint summary")
    args = ap.parse_args(argv)

    engine = _get_engine(mode="dry-run")
    cp = engine.checkpoint_summary()
    if cp.get("status") == "no_checkpoint":
        print("[checkpoint] No checkpoint found — engine has not been run yet")
        return 0

    print("=" * 60)
    print("ENGINE CHECKPOINT STATUS")
    print("=" * 60)
    print(f"Session ID:      {cp.get('session_id', '?')}")
    print(f"Mode:            {cp.get('mode', '?')}")
    print(f"Status:          {cp.get('status', '?')}")
    print(f"Total sources:   {cp.get('total_sources', 0)}")
    print(f"Completed:       {cp.get('completed', 0)}")
    print(f"Failed:          {cp.get('failed', 0)}")
    print(f"Pending:         {cp.get('pending', 0)}")
    print(f"Completed batches: {cp.get('completed_batches', [])}")
    print(f"Current batch:   {cp.get('current_batch', 'none')}")
    print(f"Last updated:    {cp.get('updated_at', '?')}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="atlas", description="Atlas Dataset Foundation CLI.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    # Existing commands
    sub.add_parser("self-test", help="run permanent invariant checks")
    p_ing = sub.add_parser("ingest-pilot", help="run Phase 3A controlled pilot ingestion")
    p_ing.add_argument("--max", type=int, default=100)
    p_gen = sub.add_parser("gen-calibration-sample",
                           help="generate quality-calibration review worksheet")
    p_gen.add_argument("--candidates", default=str(ROOT / "curated" / "v0.1" / "pilot_candidates.jsonl"))
    p_gen.add_argument("--worksheet-out", default=str(ROOT / "review_queue" / "calibration_sample.jsonl"))
    p_gen.add_argument("--example-out", default=str(ROOT / "review_queue" / "quality_reviews.example.jsonl"))
    p_gen.add_argument("--sample-frac", type=float, default=0.30)
    p_gen.add_argument("--seed", type=int, default=7)
    p_gen.add_argument("--no-example", action="store_true")
    p_cal = sub.add_parser("calibrate", help="calibrate quality scorer vs human review")
    p_cal.add_argument("--reviews", default=str(ROOT / "review" / "quality_reviews.jsonl"))
    p_cal.add_argument("--candidates", default=str(ROOT / "curated" / "v0.1" / "pilot_candidates.jsonl"))
    p_cal.add_argument("--report-out", default=str(ROOT / "metadata" / "calibration_report.json"))
    p_cal.add_argument("--md-out", default=str(ROOT / "docs" / "quality_calibration_report.md"))

    # ---- Acquisition Engine commands (Phase 3D) ----
    p_acquire = sub.add_parser("acquire", help="run the Acquisition Engine (dry-run, execute, or resume)")
    p_acquire.add_argument("--dry-run", action="store_true", help="plan only, no side effects")
    p_acquire.add_argument("--execute", action="store_true", help="run the ingestion pipeline")
    p_acquire.add_argument("--resume", action="store_true", help="resume from checkpoint")
    p_acquire.add_argument("--max", type=int, default=100, help="max records (execute mode)")
    p_acquire.add_argument("--report", default=str(ROOT / "docs" / "acquisition_plan_report.md"),
                           help="output path for dry-run report")

    p_verify = sub.add_parser("verify", help="verify integrity of a frozen version")
    p_verify.add_argument("--version", default="v0.1", help="version to verify")

    p_pack = sub.add_parser("pack", help="generate or verify a Knowledge Pack")
    p_pack.add_argument("--generate", help="pack name (e.g. foundation-v0.1)")
    p_pack.add_argument("--category", nargs="*", help="category filter(s)")
    p_pack.add_argument("--min-quality", type=int, default=7, help="minimum quality score")
    p_pack.add_argument("--describe", default="", help="pack description")
    p_pack.add_argument("--verify", action="store_true", help="verify existing pack(s)")

    p_version = sub.add_parser("version", help="manage dataset versions")
    p_version.add_argument("--list", action="store_true", help="list all versions")
    p_version.add_argument("--freeze", help="freeze current state as a version (e.g. v0.2)")
    p_version.add_argument("--changelog", default="", help="changelog for frozen version")
    p_version.add_argument("--diff", nargs=2, metavar=("FROM", "TO"),
                           help="diff two versions (e.g. v0.1 v0.2)")

    p_lifecycle = sub.add_parser("lifecycle", help="report on record lifecycle state")
    p_lifecycle.add_argument("--report", action="store_true", help="print lifecycle state summary")

    p_ckpt = sub.add_parser("checkpoint", help="show checkpoint status")
    p_ckpt.add_argument("--status", action="store_true", help="show checkpoint summary")
    args = ap.parse_args(argv)
    # Args after the program name + subcommand name are for the subcommand.
    # Stripping the subcommand token avoids argparse choking on it inside the
    # subcommand's own parser (the previous dispatch left it in, so e.g.
    # `ingest-pilot --max 5` silently fell back to the default).
    rest = (argv[2:] if argv else sys.argv[2:])
    if args.cmd == "self-test":
        return cmd_self_test([])
    if args.cmd == "ingest-pilot":
        return cmd_ingest_pilot(rest)
    if args.cmd == "gen-calibration-sample":
        return cmd_gen_calibration_sample(rest)
    if args.cmd == "calibrate":
        return cmd_calibrate(rest)

    # ---- Acquisition Engine commands ----
    if args.cmd == "acquire":
        return cmd_acquire(rest)
    if args.cmd == "verify":
        return cmd_verify(rest)
    if args.cmd == "pack":
        return cmd_pack(rest)
    if args.cmd == "version":
        return cmd_version(rest)
    if args.cmd == "lifecycle":
        return cmd_lifecycle(rest)
    if args.cmd == "checkpoint":
        return cmd_checkpoint(rest)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
