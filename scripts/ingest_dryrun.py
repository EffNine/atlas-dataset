#!/usr/bin/env python3
"""
ingest_dryrun.py — Atlas v0.1 ingestion engine, DRY-RUN mode only.

Reads metadata/acquisition_manifest_v0.1.json, then for every planned source:
  1. Validates the license against the commercial-safety gate (delegates to
     scripts/validate_dataset.py:is_denied_license — single source of truth).
  2. Estimates download size from a LOCAL reference table (no network).
  3. Maps the source to the canonical Atlas schema (schemas/dataset_schema.json)
     and emits a per-source canonical-record TEMPLATE (no data, no download).
  4. Generates an execution plan (ordered steps) per batch.
  5. Produces a pre-ingestion report (docs/ingestion_dryrun_report.md).

HARD GUARANTEE: this script NEVER downloads, transforms, writes, or modifies any
dataset content. It only reads the manifest + registry + schemas and writes the
report + a JSON plan stub. No `requests`/network calls; no file writes outside the
report/plan outputs; `raw/` and `curated/` are never touched.

Usage:
  python scripts/ingest_dryrun.py
  python scripts/ingest_dryrun.py --manifest metadata/acquisition_manifest_v0.1.json --out docs/ingestion_dryrun_report.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "metadata" / "acquisition_manifest_v0.1.json"
REGISTRY = ROOT / "metadata" / "source_registry.json"
REPORT = ROOT / "docs" / "ingestion_dryrun_report.md"
PLAN = ROOT / "metadata" / "ingestion_plan_v0.1.json"

# ---------------------------------------------------------------------------
# Import the SINGLE source of truth for the license gate from validate_dataset.py
# so the dry-run engine cannot drift from the enforced pipeline gate.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(ROOT / "scripts"))
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("validate_mod", ROOT / "scripts" / "validate_dataset.py")
_validate = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_validate)
is_denied_license = _validate.is_denied_license

# ---------------------------------------------------------------------------
# Local download-size reference table (bytes). NO network — hand-curated from
# the Phase 2 HuggingFace API probe + known archive sizes. "gated"/"unknown"
# entries are flagged for human resolution; estimates are upper-bound intent.
# ---------------------------------------------------------------------------
SIZE_REF = {
    # source_id: (estimated_bytes, basis)
    "f1": (105_611_404, "HF oasst1 dataset_size (train+val)"),
    "f6": (30_000_000, "estimate: 10k conv, CC-BY-4.0"),
    "f5": (800_000_000, "estimate: 64k pairs, MIT"),
    "f2": (16_000_000, "HF dolly-15k dataset_size (~16MB; gated)"),
    "s1": (416_515_483, "HF SWE-bench dataset_size"),
    "s4": (40_000_000, "estimate: 20k code instruct"),
    "s6": (2_000_000_000, "estimate: tulu-3 subset sample"),
    "s5": (60_000_000_000, "estimate: SE code dumps (SO+Unix.SE) XML"),
    "s2": (3_000_000_000_000, "HF The Stack v2 ~3TB (subset only)"),
    "y1": (500_000_000, "estimate: kernel+man-pages scrape"),
    "y2": (300_000_000, "estimate: kubernetes.io/docs scrape"),
    "y3": (200_000_000, "estimate: docs.docker.com scrape"),
    "y4": (400_000_000, "estimate: Arch Wiki dump"),
    "y5": (80_000_000_000, "estimate: SE systems dumps"),
    "m1": (50_000_000_000, "estimate: arXiv cs.LG/CL/AI subset"),
    "m2": (120_000_000, "estimate: Open-Platypus 25k"),
    "m3": (1_000_000_000, "estimate: tulu-3 ML subset"),
    "m4": (100_000_000_000, "estimate: Pile permissive subsets"),
    "c1": (4_676_934, "HF gsm8k dataset_size"),
    "c2": (168_856_915, "HF mmlu dataset_size (all)"),
    "c3": (120_000_000, "estimate: Hendrycks MATH"),
    "c5": (56_651_995_057, "HF open-web-math dataset_size"),
    "c6": (20_000_000, "estimate: sciq 11k"),
    "h2": (5_000_000_000, "estimate: arXiv hw/arch subset"),
    "h1": (300_000_000, "estimate: Wikipedia hw articles"),
    "h4": (20_000_000_000, "estimate: SE Electronics dumps"),
    "h6": (0, "generated locally from licensed docs (no download)"),
    "h3": (200_000_000, "estimate: WikiChip scrape (license verify)"),
    "b1": (80_000_000, "estimate: finance-alpaca 70k"),
    "b3": (10_000_000_000, "estimate: SE Finance/Econ dumps"),
    "b2": (300_000_000, "estimate: Wikipedia business articles"),
    "b4": (0, "generated locally from licensed docs (no download)"),
    "r1": (10_000_000_000, "estimate: Project Gutenberg PD subset"),
    "r2": (300_000_000, "estimate: Wikipedia creative articles"),
    "r3": (0, "generated locally from licensed docs (no download)"),
    "g1": (0, "generated locally from licensed docs (no download)"),
}

# Canonical schema fields (from schemas/dataset_schema.json) — used to prove the
# mapping is complete for each source (no data, just field contract).
SCHEMA_FIELDS = ["id", "category", "subcategory", "type", "source", "messages",
                 "language", "difficulty", "tags", "quality_score", "verified", "notes"]


def fmt_bytes(n: int) -> str:
    if n <= 0:
        return "0 B (local/generated)"
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.1f} {u}" if u != "B" else f"{int(f)} {u}"
        f /= 1024.0


def license_class_of(lic: str) -> str:
    low = lic.lower()
    if is_denied_license(lic):
        return "DENIED"
    if "rail" in low:
        return "use-restricted"
    if "sa" in low or "share-alike" in low or "share alike" in low:
        return "share-alike"
    if any(p in low for p in ("mit", "apache", "bsd", "cc-by-4.0", "cc-by-3.0",
                              "cc0", "odc-by", "public domain", "arxiv")):
        return "permissive"
    return "review"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Atlas v0.1 ingestion engine — DRY RUN (no data).")
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--registry", default=str(REGISTRY))
    ap.add_argument("--out", default=str(REPORT))
    ap.add_argument("--plan", default=str(PLAN))
    args = ap.parse_args(argv)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    reg_by_id = {s["id"]: s for s in registry.get("sources", [])}

    constraints = manifest["global_constraints"]
    cap_pct = constraints["synthetic_model_generated_cap_pct"]
    total_target = manifest["total_target_examples"]

    # ---- validation + planning pass ----------------------------------------
    batch_reports = []
    per_source_rows = []
    license_blocked = []
    total_dl_bytes = 0
    cat_counts = Counter()
    syn_count = 0
    reg_missing = []

    for b in manifest["batches"]:
        rows = []
        for d in b["datasets"]:
            sid = d["source_id"]
            reg = reg_by_id.get(sid)
            if reg is None:
                reg_missing.append(sid)
                reg_status = "MISSING-IN-REGISTRY"
                reg_rec = None
            else:
                reg_status = reg.get("status", "candidate")
                reg_rec = reg.get("recommendation", "")

            lic = d["license"]
            lclass = license_class_of(lic)
            denied = is_denied_license(lic)
            if denied:
                license_blocked.append((sid, lic))

            est, basis = SIZE_REF.get(sid, (0, "unknown — add to SIZE_REF"))
            total_dl_bytes += est
            if d["synthetic"]:
                syn_count += d["target_examples"]
            cat_counts[d["category"]] += d["target_examples"]

            # schema mapping: build a canonical-record TEMPLATE (no real content)
            template = {
                "id": f"{d['category']}_{d['subcategories'][0]}_<seq>",
                "category": d["category"],
                "subcategory": d["subcategories"][0],
                "type": _type_for_extraction(d["extraction_method"]),
                "source": {
                    "name": d["name"],
                    "url": d["url"],
                    "license": lic,
                    "date": "",  # resolved at ingest time
                },
                "messages": [
                    {"role": "user", "content": "<extracted-from: %s>" % d["extraction_method"]},
                    {"role": "assistant", "content": "<generated-by: clean+convert pipeline>"},
                ],
                "language": "en",
                "difficulty": 0,
                "tags": d["subcategories"] + ([ "synthetic"] if d["synthetic"] else []),
                "quality_score": 0,  # set by quality_score.py after convert
                "verified": False,   # set by human reviewer
                "notes": d["notes"],
            }
            # confirm every schema field is represented
            missing_fields = [f for f in SCHEMA_FIELDS if f not in template]

            row = {
                "batch_id": b["batch_id"],
                "order": b["order"],
                "source_id": sid,
                "name": d["name"],
                "category": d["category"],
                "subcategories": d["subcategories"],
                "target": d["target_examples"],
                "license": lic,
                "license_class": lclass,
                "denied": denied,
                "registry_status": reg_status,
                "registry_recommendation": reg_rec,
                "synthetic": d["synthetic"],
                "extraction_method": d["extraction_method"],
                "constraints": d["license_constraints"],
                "est_bytes": est,
                "est_basis": basis,
                "schema_fields_mapped": len(SCHEMA_FIELDS) - len(missing_fields),
                "schema_missing_fields": missing_fields,
                "canonical_template": template,
            }
            rows.append(row)
            per_source_rows.append(row)
        batch_reports.append((b, rows))

    # ---- aggregate checks ---------------------------------------------------
    syn_pct = round(100 * syn_count / total_target, 1)
    syn_over = syn_pct > cap_pct
    license_block_ok = len(license_blocked) == 0
    # every source must be accepted/review in registry
    bad_status = [r["source_id"] for r in per_source_rows
                  if r["registry_status"] not in ("accepted", "review")]
    cat_ok = all(abs(cat_counts[c] - manifest["category_targets"][c]) <=
                 manifest["category_targets"][c] * 0.05 + 0.001
                 for c in manifest["category_targets"])

    # ---- write plan stub (JSON) ---------------------------------------------
    plan_doc = {
        "manifest_version": manifest["manifest_version"],
        "atlas_target_version": manifest["atlas_target_version"],
        "mode": "dry-run",
        "generated": date.today().isoformat(),
        "checks": {
            "license_gate_passed": license_block_ok,
            "denied_sources": [{"source_id": s, "license": l} for s, l in license_blocked],
            "synthetic_within_cap": not syn_over,
            "synthetic_count": syn_count,
            "synthetic_pct": syn_pct,
            "synthetic_cap_pct": cap_pct,
            "registry_status_ok": len(bad_status) == 0,
            "registry_missing": reg_missing,
            "bad_registry_status": bad_status,
            "category_balance_ok": cat_ok,
            "total_target": total_target,
            "estimated_download_bytes": total_dl_bytes,
        },
        "execution_plan": [
            {
                "batch_id": b["batch_id"],
                "order": b["order"],
                "theme": b["theme"],
                "steps": _plan_steps(b, rows),
            }
            for b, rows in batch_reports
        ],
        "sources": [
            {
                "source_id": r["source_id"], "name": r["name"], "license": r["license"],
                "license_class": r["license_class"], "denied": r["denied"],
                "registry_status": r["registry_status"], "target": r["target"],
                "est_bytes": r["est_bytes"], "synthetic": r["synthetic"],
                "schema_fields_mapped": r["schema_fields_mapped"],
                "schema_missing_fields": r["schema_missing_fields"],
            }
            for r in per_source_rows
        ],
    }
    Path(args.plan).write_text(json.dumps(plan_doc, indent=2), encoding="utf-8")

    # ---- write markdown report ---------------------------------------------
    _write_report(args.out, manifest, batch_reports, per_source_rows,
                  total_dl_bytes, syn_count, syn_pct, syn_over, license_block_ok,
                  license_blocked, bad_status, reg_missing, cat_counts, cat_ok)

    # ---- console summary ----------------------------------------------------
    print(f"[dryrun] sources planned : {len(per_source_rows)}")
    print(f"[dryrun] total target     : {total_target} examples")
    print(f"[dryrun] est download     : {fmt_bytes(total_dl_bytes)}")
    print(f"[dryrun] synthetic         : {syn_count} ({syn_pct}%) cap={cap_pct}% "
          f"{'OVER' if syn_over else 'ok'}")
    print(f"[dryrun] license gate      : {'PASS' if license_block_ok else 'BLOCKED ' + str(license_blocked)}")
    print(f"[dryrun] registry status   : {'ok' if not bad_status and not reg_missing else 'ISSUES ' + str(bad_status+reg_missing)}")
    print(f"[dryrun] category balance  : {'ok' if cat_ok else 'MISMATCH'}")
    print(f"[dryrun] report -> {args.out}")
    print(f"[dryrun] plan   -> {args.plan}")
    print("[dryrun] DRY RUN COMPLETE — no data downloaded, transformed, or modified.")
    return 0


def _type_for_extraction(method: str) -> str:
    if method in ("doc_to_instruction", "doc2qa", "doc2qa_synthetic", "task_frame",
                  "mc_to_openqa", "generate_from_docs"):
        return "instruction"
    if method in ("cot_pair", "qa_pair", "prompt_response_pair", "instruction_pair",
                  "chosen_response_pair", "subset_sample", "subset_sample_filtered",
                  "subset_permissive", "tree_to_ranked_turn",
                  "tree_to_ranked_turn_filtered", "xml_dump_parse", "filter_planning"):
        return "instruction"
    if method in ("issue_to_patch", "conversation_to_turn"):
        return "conversation"
    return "instruction"


def _plan_steps(b: dict, rows: list) -> list:
    """Generate ordered execution steps for a batch (plan text only)."""
    steps = []
    for r in rows:
        sid = r["source_id"]
        steps.append({
            "step": f"resolve:{sid}",
            "action": "resolve source_id -> registry; confirm status in (accepted,review)",
            "source_id": sid,
        })
        if r["license_class"] == "DENIED":
            steps.append({"step": f"BLOCK:{sid}", "action": "LICENSE DENIED — must not ingest",
                          "source_id": sid})
            continue
        if r["est_bytes"] == 0:
            steps.append({"step": f"generate:{sid}",
                          "action": "generate locally from licensed docs via doc2qa (no download); human review mandatory",
                          "source_id": sid})
        else:
            steps.append({"step": f"download:{sid}",
                          "action": f"download to raw/{r['category']}/{sid}/ (est {fmt_bytes(r['est_bytes'])})",
                          "source_id": sid})
        # license-specific handling
        for c in r["constraints"]:
            steps.append({"step": f"constraint:{sid}", "action": c, "source_id": sid})
        steps.append({"step": f"pipeline:{sid}",
                      "action": "clean -> dedup -> convert -> quality_score", "source_id": sid})
        steps.append({"step": f"gate:{sid}",
                      "action": "apply quality_gate (score>=7); human review -> verified",
                      "source_id": sid})
    return steps


def _write_report(path, manifest, batch_reports, rows, total_dl, syn_n, syn_pct,
                  syn_over, lic_ok, lic_blocked, bad_status, reg_missing, cat_counts, cat_ok):
    L = []
    L.append("# Atlas v0.1 — Pre-Ingestion Report (DRY RUN)")
    L.append("")
    L.append(f"**Generated:** {date.today().isoformat()}  ")
    L.append("**Mode:** DRY RUN — no data downloaded, transformed, or modified.  ")
    L.append(f"**Manifest:** `metadata/acquisition_manifest_v0.1.json`  ")
    L.append(f"**Plan stub:** `metadata/ingestion_plan_v0.1.json`")
    L.append("")
    L.append("## 1. Executive summary")
    L.append("")
    L.append(f"- Sources planned: **{len(rows)}** across **{len(batch_reports)}** batches.")
    L.append(f"- Target examples: **{manifest['total_target_examples']}** "
             f"(matches category balance: {'yes' if cat_ok else 'NO'}).")
    L.append(f"- Estimated download: **{fmt_bytes(total_dl)}** "
             f"(local reference table; no network used).")
    L.append(f"- Model-generated synthetic: **{syn_n}** ({syn_pct}%); cap "
             f"{manifest['global_constraints']['synthetic_model_generated_cap_pct']}% → "
             f"{'OVER CAP ⚠' if syn_over else 'within cap ✅'}.")
    L.append(f"- License gate: **{'PASS ✅' if lic_ok else 'BLOCKED ⛔ ' + str(lic_blocked)}** "
             f"(enforced by `scripts/validate_dataset.py:is_denied_license`).")
    L.append(f"- Registry status: **{'ok ✅' if not bad_status and not reg_missing else 'ISSUES ⚠ ' + str(bad_status + reg_missing)}**.")
    L.append("")
    L.append("## 2. License validation")
    L.append("")
    L.append("Every planned license was checked against the commercial-safety gate. "
             "Denied licenses (NC / proprietary / ambiguous / unknown) are hard-blocked and "
             "**must never be ingested**.")
    L.append("")
    L.append("| Source | License | Class | Denied? |")
    L.append("|---|---|---|---|")
    for r in rows:
        L.append(f"| {r['source_id']} ({r['name'][:28]}) | {r['license']} | "
                 f"{r['license_class']} | {'⛔ YES' if r['denied'] else '✅ no'} |")
    L.append("")
    if lic_blocked:
        L.append("> ⛔ BLOCKED sources above violate the commercial-safety policy. "
                 "Ingestion of these must be aborted.")
    else:
        L.append("> All planned licenses pass the commercial-safety gate.")
    L.append("")
    L.append("## 3. Download-size estimates")
    L.append("")
    L.append("Estimates from a local reference table (Phase 2 HF probe + known archive sizes). "
             "Entries of `0 B` are locally-generated (no download).")
    L.append("")
    L.append("| Source | Est. size | Basis |")
    L.append("|---|---|---|")
    for r in rows:
        L.append(f"| {r['source_id']} | {fmt_bytes(r['est_bytes'])} | {r['est_basis']} |")
    L.append("")
    L.append(f"**Total estimated download: {fmt_bytes(total_dl)}**")
    L.append("")
    L.append("## 4. Canonical schema mapping")
    L.append("")
    L.append(f"Each source maps to all {len(SCHEMA_FIELDS)} canonical fields "
             f"(`schemas/dataset_schema.json`). Below: fields mapped per source "
             f"(template only — no real content).")
    L.append("")
    L.append("| Source | Cat | Schema fields | Missing |")
    L.append("|---|---|---|---|")
    for r in rows:
        L.append(f"| {r['source_id']} | {r['category']} | "
                 f"{r['schema_fields_mapped']}/{len(SCHEMA_FIELDS)} | "
                 f"{', '.join(r['schema_missing_fields']) or '—'} |")
    L.append("")
    L.append("Mapping rule per source: `category` ← manifest category; `subcategory` ← first "
             "subcategory; `type` ← extraction-method map; `source` ← {name,url,license,date}; "
             "`messages` ← user/assistant pair produced by `clean+convert`; `tags` ← subcategories "
             "(+ `synthetic` if applicable); `quality_score`/`verified` set downstream.")
    L.append("")
    L.append("## 5. Execution plans (per batch)")
    L.append("")
    for b, brows in batch_reports:
        L.append(f"### {b['batch_id']} (order {b['order']}) — {b['theme']}")
        L.append("")
        L.append(f"- Target examples: {sum(r['target'] for r in brows)}")
        L.append("- Steps:")
        for r in brows:
            L.append(f"  - **{r['source_id']}** ({r['name']}) "
                     f"[{r['license_class']}{' / DENIED' if r['denied'] else ''}] "
                     f"→ {r['extraction_method']} → {r['target']} ex")
            if r["constraints"]:
                for c in r["constraints"]:
                    L.append(f"    - constraint: {c}")
        L.append("")
    L.append("## 6. Risk flags")
    L.append("")
    if syn_over:
        L.append(f"- ⚠ Synthetic share {syn_pct}% exceeds cap {manifest['global_constraints']['synthetic_model_generated_cap_pct']}%. Reduce capped-synthetic sources.")
    if lic_blocked:
        L.append(f"- ⛔ Denied licenses present: {lic_blocked}. Must not ingest.")
    if bad_status:
        L.append(f"- ⚠ Sources with non-accepted/review registry status: {bad_status}.")
    if reg_missing:
        L.append(f"- ⚠ Sources missing from registry: {reg_missing} (add before ingest).")
    if not (syn_over or lic_blocked or bad_status or reg_missing):
        L.append("- No blocking risks detected in dry run.")
    L.append("")
    L.append("## 7. Next step")
    L.append("")
    L.append("On human approval, execute batches in `order` using the steps in "
             "`metadata/ingestion_plan_v0.1.json`. The real engine will: download → clean → "
             "dedup → convert → quality_score → human review → `curated/`, with the denied-license "
             "gate enforced by `scripts/validate_dataset.py --strict`.")
    L.append("")
    L.append("> **DRY RUN — nothing was downloaded, transformed, or written outside this report and the plan stub.**")
    Path(path).write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
