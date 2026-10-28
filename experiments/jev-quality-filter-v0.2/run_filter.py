#!/usr/bin/env python3
"""JEV quality-filter v0.2: adaptive confidence router -> blind AI-2 -> report.

Isolation: reads ONLY from ../jev-pilot-atlas-v0.1/ (stored JEV results,
content index, sample manifest) and ../jev-quality-filter-v0.1/
(stored blind AI-2 verdicts for reuse + v0.1 bands for comparison).
Writes ONLY inside this directory. Never touches Atlas source data, never
reads Phase-2 human labels, never reruns JEV.

Usage:
  python run_filter.py route           # offline adaptive routing, no network
  python run_filter.py run [--limit N] # top-up AI-2 calls for newly-escalated
                                       # records only (resume-safe)
  python run_filter.py report          # rebuild results + summaries
  python run_filter.py verify          # re-hash read-only inputs vs recorded
                                       # provenance (Atlas-untouched check)
"""

import hashlib
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PILOT = ROOT / "experiments" / "jev-pilot-atlas-v0.1"
V01 = ROOT / "experiments" / "jev-quality-filter-v0.1"

sys.path.insert(0, str(HERE))
import router  # noqa: E402

AI2_NEW_RESULTS = HERE / "ai2_results.jsonl"  # v0.2-made calls ONLY
FILTER_RESULTS = HERE / "filter_results.jsonl"
CONFIG_SUMMARY = HERE / "config_summary.json"
DISAGREEMENT_SUMMARY = HERE / "disagreement_summary.json"

V01_AI2_RESULTS = V01 / "ai2_results.jsonl"
V01_FILTER_RESULTS = V01 / "filter_results.jsonl"

POLICY_ORDER = ("conservative", "balanced", "aggressive")

# Fixed reporting buckets for disagreement-direction analysis (NOT routing
# thresholds; they only slice already-escalated records for reporting).
C_BUCKETS = [("C<0.40", lambda c: c < 0.40),
             ("C 0.40-0.60", lambda c: 0.40 <= c < 0.60),
             ("C>=0.60", lambda c: c >= 0.60)]
P_BUCKETS = [("p<0.15", lambda p: p < 0.15),
             ("p 0.15-0.30", lambda p: 0.15 <= p < 0.30),
             ("p>=0.30", lambda p: p >= 0.30)]
CORR_BUCKETS = [("c<0.60", lambda c: c < 0.60),
                ("c 0.60-0.85", lambda c: 0.60 <= c < 0.85),
                ("c>=0.85", lambda c: c >= 0.85)]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def input_provenance() -> dict:
    return {
        "jev_results.jsonl": sha256_file(PILOT / "jev_results.jsonl"),
        "sample_content_index.json": sha256_file(
            PILOT / "sample_content_index.json"),
        "sample_manifest.json": sha256_file(PILOT / "sample_manifest.json"),
        "v0.1_ai2_results.jsonl": sha256_file(V01_AI2_RESULTS),
        "router_formula": router.FORMULA_VERSION,
        "policies": {k: dict(v) for k, v in router.POLICIES.items()},
    }


def load_inputs():
    jev = {}
    for line in (PILOT / "jev_results.jsonl").open():
        line = line.strip()
        if line:
            r = json.loads(line)
            jev[r["record_id"]] = r
    content = json.loads((PILOT / "sample_content_index.json").read_text())
    manifest = json.loads((PILOT / "sample_manifest.json").read_text())
    meta = {m["id"]: m for m in manifest["records"]}
    return jev, content, meta


def load_ai2_stored() -> dict:
    """Blind AI-2 verdicts made by v0.1 (read-only reuse, never rewritten)."""
    out = {}
    for line in V01_AI2_RESULTS.open():
        line = line.strip()
        if line:
            r = json.loads(line)
            r["_source"] = "jev-quality-filter-v0.1"
            out[r["record_id"]] = r
    return out


def load_ai2_new() -> dict:
    """AI-2 verdicts made by v0.2 top-up calls (local file, resume-safe)."""
    out = {}
    if AI2_NEW_RESULTS.exists():
        for line in AI2_NEW_RESULTS.open():
            line = line.strip()
            if line:
                r = json.loads(line)
                r["_source"] = "jev-quality-filter-v0.2"
                out[r["record_id"]] = r
    return out


def load_ai2_effective() -> tuple[dict, dict]:
    """New v0.2 calls overlay stored v0.1 verdicts. Returns (merged, new)."""
    stored = load_ai2_stored()
    new = load_ai2_new()
    merged = dict(stored)
    merged.update(new)
    return merged, new


def deterministic_validate(user: str, asst: str) -> tuple[str, list]:
    """Local schema/format checks. Returns (VALID|INVALID, reasons)."""
    reasons = []
    if not isinstance(user, str) or not user.strip():
        reasons.append("empty_user")
    if not isinstance(asst, str) or not asst.strip():
        reasons.append("empty_assistant")
    if user and len(user.strip()) < 5:
        reasons.append("user_too_short")
    if asst and len(asst.strip()) < 10:
        reasons.append("assistant_too_short")
    if "\x00" in (user + asst):
        reasons.append("null_bytes")
    if reasons:
        return "INVALID", reasons
    return "VALID", []


def escalated_union(jev, content) -> list[str]:
    """Record ids AMBIGUOUS under ANY v0.2 policy (AI-2 candidates)."""
    todo = []
    for rid, r in jev.items():
        if r.get("status") != "ok":
            continue
        c = content.get(rid)
        if not c:
            continue
        if deterministic_validate(c["user"], c["assistant"])[0] != "VALID":
            continue
        routed = [router.route_record(r["answers"], p) for p in POLICY_ORDER]
        if any(x["band"] == "AMBIGUOUS" for x in routed):
            todo.append(rid)
    return sorted(todo)


def cmd_route():
    jev, content, _meta = load_inputs()
    print(f"records with stored JEV results: {len(jev)} (JEV NOT rerun)")
    for name in POLICY_ORDER:
        dist: Counter = Counter()
        for _rid, r in jev.items():
            if r.get("status") != "ok":
                dist["JEV_ERROR"] += 1
            else:
                dist[router.route_record(r["answers"], name)["band"]] += 1
        print(f"  {name} {router.POLICIES[name]}: {dict(dist)}")
    union = escalated_union(jev, content)
    stored = load_ai2_stored()
    missing = [rid for rid in union if rid not in stored]
    print(f"escalation union (AI-2 candidates): {len(union)}; "
          f"covered by stored v0.1 verdicts: {len(union) - len(missing)}; "
          f"new AI-2 calls needed: {len(missing)}")


def cmd_run(limit=None):
    import ai2_reviewer
    jev, content, meta = load_inputs()
    effective, _new = load_ai2_effective()
    union = escalated_union(jev, content)
    todo = [rid for rid in union if rid not in effective]
    if limit:
        todo = todo[:limit]
    print(f"v0.2 top-up AI-2 candidates: {len(todo)} "
          f"(union {len(union)}, already have verdict: "
          f"{len(union) - len(todo)}); blind review, no JEV data passed")
    if not todo:
        return
    config = ai2_reviewer.resolve_config()
    print(f"AI-2 model: {config['model']} (temperature 0.0)")
    workers = int(os.environ.get("AI2_WORKERS", "8"))
    n_done = [0]

    def work(rid):
        r = jev[rid]
        c = content[rid]
        m = meta.get(rid, {})
        try:
            res = ai2_reviewer.review_record(
                c["user"], c["assistant"],
                str(m.get("category", "")), str(m.get("subcategory", "")),
                config)
            entry = {
                "record_id": rid,
                "content_sha256": sha256_text(json.dumps(
                    [c["user"], c["assistant"]], ensure_ascii=False)),
                "arm": r.get("arm"),
                "status": "ok",
                "verdict": res["verdict"],
                "confidence": res["confidence"],
                "correctness": res["correctness"],
                "completeness": res["completeness"],
                "suitability": res["suitability"],
                "rationale": res["rationale"],
                "latency_s": res["latency_s"],
                "input_tokens": res.get("input_tokens"),
                "output_tokens": res.get("output_tokens"),
                "model": res.get("model"),
                "made_by": "jev-quality-filter-v0.2",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:  # noqa: BLE001 -- fail-safe capture
            reason = getattr(exc, "reason", type(exc).__name__)
            entry = {
                "record_id": rid,
                "content_sha256": sha256_text(json.dumps(
                    [c["user"], c["assistant"]], ensure_ascii=False)),
                "arm": r.get("arm"),
                "status": "error",
                "verdict": "ERROR",
                "error_reason": f"{reason}: {str(exc)[:200]}",
                "made_by": "jev-quality-filter-v0.2",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
        with open(AI2_NEW_RESULTS, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        n_done[0] += 1
        if n_done[0] % 25 == 0 or n_done[0] == len(todo):
            print(f"  {n_done[0]}/{len(todo)} v0.2 AI-2 calls done", flush=True)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, todo))
    print(f"v0.2 AI-2 batch: {n_done[0]} calls in "
          f"{time.perf_counter() - t0:.1f}s")


def build_results():
    jev, content, meta = load_inputs()
    ai2, _new = load_ai2_effective()
    rows = []
    for rid, r in jev.items():
        c = content.get(rid, {})
        user, asst = c.get("user", ""), c.get("assistant", "")
        det_status, det_reasons = deterministic_validate(user, asst)
        a = ai2.get(rid)
        ai2_verdict = a.get("verdict") if a else None
        jev_ok = r.get("status") == "ok"
        if jev_ok:
            conf_all = {p: router.route_record(r["answers"], p)
                        for p in POLICY_ORDER}
            jev_block = {
                "status": r.get("status"),
                "model": r.get("model"),
                "correct": r["answers"]["correct"]["noul"],
                "quality": r["answers"]["quality"]["score"],
                "problematic": r["answers"]["problematic"]["noul"],
                "adherence": r["answers"]["adherence"]["noul"],
                "consistent_category":
                    r["answers"]["consistent_category"]["noul"],
                "training_value": r["answers"]["training_value"]["score"],
                "latency_s": r.get("latency_s"),
                "input_tokens": r.get("input_tokens"),
                "output_tokens": r.get("output_tokens"),
            }
        else:
            conf_all = {}
            jev_block = {"status": r.get("status"), "error": r.get("error")}
        entry = {
            "record_id": rid,
            "arm": r.get("arm"),
            "content_sha256": r.get("content_sha256"),
            "deterministic": {"status": det_status, "reasons": det_reasons},
            "jev": jev_block,
            "ai2": (None if a is None else {
                k: a.get(k) for k in (
                    "status", "verdict", "confidence", "correctness",
                    "completeness", "suitability", "rationale", "latency_s",
                    "input_tokens", "output_tokens", "model",
                    "error_reason", "reviewed_at")}),
            "ai2_source": (None if a is None else a.get("_source")),
            "per_policy": {},
        }
        for name in POLICY_ORDER:
            if det_status != "VALID":
                entry["per_policy"][name] = {
                    "band": "N/A", "final": "REJECT",
                    "path": "deterministic_gate", "quarantine": False,
                    "confidence": None}
            elif not jev_ok:
                entry["per_policy"][name] = {
                    "band": "N/A", "final": "AMBIGUOUS",
                    "path": "jev_error_unresolved", "quarantine": True,
                    "confidence": None}
            else:
                routed = conf_all[name]
                band = routed["band"]
                invoked = band == "AMBIGUOUS"
                if invoked and ai2_verdict is None:
                    final, path, quar = "AMBIGUOUS", "ai2_pending", True
                elif invoked:
                    final, path, quar = router.final_for(band, ai2_verdict)
                else:
                    final, path, quar = router.final_for(band, None)
                entry["per_policy"][name] = {
                    "band": band, "ai2_invoked": invoked,
                    "final": final, "path": path, "quarantine": quar,
                    "confidence": routed.get("confidence"),
                    "degraded_reason": routed.get("degraded_reason")}
        rows.append(entry)
    rows.sort(key=lambda e: e["record_id"])
    with open(FILTER_RESULTS, "w") as f:
        for e in rows:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return rows


def _bucketize(rows, policy, key_fn, buckets):
    """Disagreement direction per reporting bucket for escalated records."""
    table = {}
    for label, pred in buckets:
        cell = {"n": 0, "agree": 0,
                "ai2_accept_where_lean_reject": 0,
                "ai2_reject_where_lean_accept": 0,
                "ai2_ambiguous_or_error": 0}
        for e in rows:
            pc = e["per_policy"][policy]
            if not pc.get("ai2_invoked") or e["ai2"] is None:
                continue
            conf = pc.get("confidence") or {}
            key_val = key_fn(e, conf)
            if key_val is None or not pred(key_val):
                continue
            v = e["ai2"].get("verdict")
            cell["n"] += 1
            if v not in ("ACCEPT", "REJECT"):
                cell["ai2_ambiguous_or_error"] += 1
                continue
            lean = router.jev_lean_stance(
                e["jev"]["correct"], e["jev"]["quality"],
                e["jev"]["problematic"])
            if (v == "ACCEPT") == (lean == "ACCEPT-lean"):
                cell["agree"] += 1
            elif v == "ACCEPT":
                cell["ai2_accept_where_lean_reject"] += 1
            else:
                cell["ai2_reject_where_lean_accept"] += 1
        table[label] = cell
    return table


def summarize(rows):
    ai2, new = load_ai2_effective()
    ai2_ok = [a for a in ai2.values() if a.get("status") == "ok"]
    summary: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "jev-quality-filter-v0.2",
        "router_formula": router.FORMULA_VERSION,
        "formula": ("C=clip(S-0.50*p-0.25*U-0.25*D,0,1); "
                    "S=0.40*c+0.25*q/4+0.15*a+0.10*k+0.10*t/4; "
                    "U=(qs+ts)/2; D=mean(|c-qn|,|c-(1-p)|,|c-a|,|c-k|); "
                    "p>=0.80 forces LOW; degraded signals escalate"),
        "n_records": len(rows),
        "routing": "adaptive confidence bands; experimental operating "
                   "policies, NOT calibrated (see README)",
        "ground_truth": None,
        "accuracy_claims": "NONE -- workflow evaluation only; human labels "
                           "never used; JEV outputs are not ground truth",
        "input_provenance": input_provenance(),
        "configs": {},
        "ai2": {
            "n_invoked_union": len(
                {e["record_id"] for e in rows
                 for p in POLICY_ORDER
                 if e["per_policy"][p].get("ai2_invoked")}),
            "n_reused_v01": sum(1 for a in ai2.values()
                                if a.get("_source")
                                == "jev-quality-filter-v0.1"),
            "n_new_v02": len(new),
            "n_ok": len(ai2_ok),
            "n_error": len(ai2) - len(ai2_ok),
            "verdict_dist": dict(Counter(
                a.get("verdict") for a in ai2.values())),
            "mean_confidence": (round(sum(
                a["confidence"] for a in ai2_ok
                if a.get("confidence") is not None) / max(1, sum(
                    1 for a in ai2_ok
                    if a.get("confidence") is not None)), 3)
                if ai2_ok else None),
            "total_input_tokens": sum(
                a.get("input_tokens") or 0 for a in ai2_ok),
            "total_output_tokens": sum(
                a.get("output_tokens") or 0 for a in ai2_ok),
            "mean_latency_s": (round(sum(
                a["latency_s"] for a in ai2_ok
                if a.get("latency_s") is not None) / max(1, sum(
                    1 for a in ai2_ok
                    if a.get("latency_s") is not None)), 3)
                if ai2_ok else None),
            "cost_usd": "NOT ESTIMATED -- apply operator price card",
        },
    }
    jev_lat = [e["jev"].get("latency_s") for e in rows
               if e["jev"].get("latency_s") is not None]
    summary["jev_reused"] = {
        "n": len(rows),
        "total_input_tokens": sum((e["jev"].get("input_tokens") or 0)
                                  for e in rows),
        "total_output_tokens": sum((e["jev"].get("output_tokens") or 0)
                                   for e in rows),
        "mean_latency_s": (round(sum(jev_lat) / len(jev_lat), 3)
                           if jev_lat else None),
        "latency_reported": len(jev_lat),
    }
    for name in POLICY_ORDER:
        finals = Counter(e["per_policy"][name]["final"] for e in rows)
        bands = Counter(e["per_policy"][name]["band"] for e in rows)
        paths = Counter(e["per_policy"][name]["path"] for e in rows)
        agree = dis = ai2_amb = 0
        dis_accept_lean_reject = dis_reject_lean_accept = 0
        for e in rows:
            pc = e["per_policy"][name]
            if not pc.get("ai2_invoked") or e["ai2"] is None:
                continue
            v = e["ai2"].get("verdict")
            if v not in ("ACCEPT", "REJECT"):
                ai2_amb += 1
                continue
            lean = router.jev_lean_stance(
                e["jev"]["correct"], e["jev"]["quality"],
                e["jev"]["problematic"])
            if (v == "ACCEPT") == (lean == "ACCEPT-lean"):
                agree += 1
            else:
                dis += 1
                if v == "ACCEPT":
                    dis_accept_lean_reject += 1
                else:
                    dis_reject_lean_accept += 1
        n_esc = bands.get("AMBIGUOUS", 0)
        ai2_in = sum((e["ai2"].get("input_tokens") or 0)
                     for e in rows
                     if e["per_policy"][name].get("ai2_invoked")
                     and e["ai2"] and e["ai2"].get("status") == "ok")
        ai2_out = sum((e["ai2"].get("output_tokens") or 0)
                      for e in rows
                      if e["per_policy"][name].get("ai2_invoked")
                      and e["ai2"] and e["ai2"].get("status") == "ok")
        ai2_err = sum(1 for e in rows
                      if e["per_policy"][name].get("ai2_invoked")
                      and e["ai2"] is not None
                      and e["ai2"].get("verdict") not in ("ACCEPT", "REJECT"))
        ai2_lat = [e["ai2"]["latency_s"] for e in rows
                   if e["per_policy"][name].get("ai2_invoked")
                   and e["ai2"] and e["ai2"].get("latency_s") is not None]
        summary["configs"][name] = {
            "thresholds": router.POLICIES[name],
            "band_dist": dict(bands),
            "n_auto_accept": bands.get("HIGH", 0),
            "n_auto_reject": bands.get("LOW", 0),
            "n_escalated": n_esc,
            "pct_auto_accept": round(100 * bands.get("HIGH", 0)
                                     / len(rows), 1),
            "pct_auto_reject": round(100 * bands.get("LOW", 0)
                                     / len(rows), 1),
            "pct_escalated": round(100 * n_esc / len(rows), 1),
            "pct_jev_only": round(100 * (len(rows) - n_esc) / len(rows), 1),
            "final_dist": dict(finals),
            "path_dist": dict(paths),
            "n_unresolved_ambiguous": finals.get("AMBIGUOUS", 0),
            "n_ai2_errors": ai2_err,
            "ai2_input_tokens": ai2_in,
            "ai2_output_tokens": ai2_out,
            "ai2_total_tokens": ai2_in + ai2_out,
            "combined_total_tokens": (
                summary["jev_reused"]["total_input_tokens"]
                + summary["jev_reused"]["total_output_tokens"]
                + ai2_in + ai2_out),
            "ai2_mean_latency_s": (round(sum(ai2_lat) / len(ai2_lat), 3)
                                   if ai2_lat else None),
            "disagreement": {
                "agree": agree, "disagree": dis,
                "disagree_rate": (round(dis / max(1, agree + dis), 3)
                                  if (agree + dis) else None),
                "ai2_accept_where_lean_reject": dis_accept_lean_reject,
                "ai2_reject_where_lean_accept": dis_reject_lean_accept,
                "ai2_ambiguous_or_error": ai2_amb,
            },
            "disagreement_by_confidence": _bucketize(
                rows, name, lambda e, cf: cf.get("C"), C_BUCKETS),
            "disagreement_by_problematic": _bucketize(
                rows, name,
                lambda e, cf: e["jev"].get("problematic"), P_BUCKETS),
            "disagreement_by_correctness": _bucketize(
                rows, name,
                lambda e, cf: e["jev"].get("correct"), CORR_BUCKETS),
        }
    with open(CONFIG_SUMMARY, "w") as f:
        json.dump(summary, f, indent=1)
    return summary


def build_disagreement_experiment(rows):
    """Second experiment: conservative disagreement-handling matrix.

    For escalated records with an AI-2 verdict, compares the JEV-lean stance
    (heuristic, NOT ground truth) with the blind AI-2 verdict and applies
    the no-winner matrix: agreement passes through, any disagreement
    quarantines as AMBIGUOUS, AI-2 AMBIGUOUS/ERROR/missing fails safe.
    Also reports how many primary finals the matrix would overturn into
    quarantine.
    """
    result: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rule": ("agree passes through; any lean-vs-verdict disagreement "
                 "-> AMBIGUOUS quarantine (no winner selected); AI-2 "
                 "AMBIGUOUS/ERROR/missing -> AMBIGUOUS fail-safe"),
        "jev_stance": ("jev_lean_stance reused verbatim from v0.1; heuristic "
                       "analysis convenience only, NOT ground truth"),
        "policies": {},
    }
    for name in POLICY_ORDER:
        cells: Counter = Counter()
        dir_cells: Counter = Counter()
        overturned = []
        for e in rows:
            pc = e["per_policy"][name]
            if not pc.get("ai2_invoked"):
                continue
            v = e["ai2"].get("verdict") if e["ai2"] else None
            lean = router.jev_lean_stance(
                e["jev"]["correct"], e["jev"]["quality"],
                e["jev"]["problematic"])
            final, path, _q = router.resolve_disagreement(lean, v)
            cells[path] += 1
            if path == "disagree_quarantine":
                lean_short = ("leanA" if lean == "ACCEPT-lean" else "leanR")
                dir_cells[f"{lean_short}_vs_ai2_{v}"] += 1
                if pc["final"] in ("ACCEPT", "REJECT"):
                    overturned.append(e["record_id"])
            if path == "disagree_fail_safe" and v in ("AMBIGUOUS", "ERROR",
                                                      None):
                dir_cells[f"ai2_{v}_fail_safe"] += 1
        n = sum(cells.values())
        result["policies"][name] = {
            "n_escalated": n,
            "matrix_dist": dict(cells),
            "direction_dist": dict(dir_cells),
            "n_quarantined_by_disagreement": cells.get(
                "disagree_quarantine", 0),
            "n_fail_safe": cells.get("disagree_fail_safe", 0),
            "n_primary_finals_overturned_to_quarantine": len(overturned),
            "overturned_record_ids": sorted(overturned),
        }
    with open(DISAGREEMENT_SUMMARY, "w") as f:
        json.dump(result, f, indent=1)
    return result


def load_v01_bands() -> dict:
    """v0.1 per-record bands for the fixed-vs-adaptive comparison (Q8)."""
    out = {}
    if not V01_FILTER_RESULTS.exists():
        return out
    for line in V01_FILTER_RESULTS.open():
        line = line.strip()
        if line:
            r = json.loads(line)
            out[r["record_id"]] = {k: v["band"]
                                   for k, v in r["per_config"].items()}
    return out


def cmd_report():
    rows = build_results()
    summary = summarize(rows)
    dis = build_disagreement_experiment(rows)
    v01 = load_v01_bands()
    print(f"records: {len(rows)}; "
          f"ai2 reused v0.1: {summary['ai2']['n_reused_v01']}, "
          f"new v0.2: {summary['ai2']['n_new_v02']}")
    for name in POLICY_ORDER:
        c = summary["configs"][name]
        print(f"  {name}: HIGH {c['n_auto_accept']} LOW {c['n_auto_reject']} "
              f"AMB {c['n_escalated']} ({c['pct_escalated']}%) "
              f"final {c['final_dist']} disagree {c['disagreement']}")
        d = dis["policies"][name]
        print(f"    disagreement-matrix: {d['matrix_dist']} "
              f"overturned->quarantine: "
              f"{d['n_primary_finals_overturned_to_quarantine']}")
    if v01:
        for name in POLICY_ORDER:
            for cfg in ("A-balanced", "B-strict-accept", "C-lenient-accept"):
                both = [(e["record_id"],
                         e["per_policy"][name]["band"],
                         v01.get(e["record_id"], {}).get(cfg))
                        for e in rows]
                saved = sum(1 for _r, new_b, old_b in both
                            if old_b == "AMBIGUOUS" and new_b != "AMBIGUOUS")
                caught = sum(1 for _r, new_b, old_b in both
                             if new_b == "AMBIGUOUS" and old_b != "AMBIGUOUS")
                print(f"    v0.2-{name} vs v0.1-{cfg}: auto-routed "
                      f"(saved AI-2): {saved}; newly escalated: {caught}")
    print(f"... wrote {FILTER_RESULTS.name} ({len(rows)}), "
          f"{CONFIG_SUMMARY.name}, {DISAGREEMENT_SUMMARY.name}")


def cmd_verify():
    recorded = None
    if CONFIG_SUMMARY.exists():
        recorded = json.loads(CONFIG_SUMMARY.read_text()).get(
            "input_provenance", {})
    current = input_provenance()
    ok = True
    for key, digest in current.items():
        if key in ("router_formula", "policies"):
            continue
        status = "OK " if recorded and recorded.get(key) == digest else (
            "RECORDED" if not recorded else "MISMATCH")
        if status == "MISMATCH":
            ok = False
        print(f"  [{status}] {key}: {digest[:16]}...")
    print("inputs match recorded provenance" if ok and recorded
          else "provenance recorded (first run)" if not recorded
          else "MISMATCH -- investigate before trusting results")
    return ok


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "route"
    if cmd == "route":
        cmd_route()
    elif cmd == "run":
        limit = None
        if "--limit" in sys.argv:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        cmd_run(limit)
        cmd_report()
    elif cmd == "report":
        cmd_report()
    elif cmd == "verify":
        sys.exit(0 if cmd_verify() else 1)
    else:
        print("unknown command", cmd)
        sys.exit(1)
