#!/usr/bin/env python3
"""Automated-quality-filter prototype: deterministic -> JEV(reused) -> bands -> AI-2.

Isolation: reads ONLY from ../jev-pilot-atlas-v0.1/ (JEV results, content index,
manifest). Writes ONLY inside this directory. Never touches Atlas source data,
never reads Phase-2 human labels.

Usage:
  python run_filter.py bands            # offline band analysis, no network
  python run_filter.py run [--limit N]  # AI-2 on union-ambiguous (resumable)
  python run_filter.py report           # rebuild filter_results.jsonl + config_summary.json
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

AI2_RESULTS = HERE / "ai2_results.jsonl"
FILTER_RESULTS = HERE / "filter_results.jsonl"
CONFIG_SUMMARY = HERE / "config_summary.json"

# --- Experimental operating thresholds (NOT calibrated; see README.md) ---
CONFIGS = {
    "A-balanced":      {"C_HI": 0.85, "Q_HI": 3.0, "P_LO": 0.15,
                        "C_LO": 0.35, "Q_LO": 1.8, "P_HI": 0.50},
    "B-strict-accept": {"C_HI": 0.90, "Q_HI": 3.2, "P_LO": 0.10,
                        "C_LO": 0.50, "Q_LO": 2.0, "P_HI": 0.40},
    "C-lenient-accept": {"C_HI": 0.75, "Q_HI": 2.5, "P_LO": 0.25,
                         "C_LO": 0.25, "Q_LO": 1.2, "P_HI": 0.65},
}

# JEV-lean heuristic for agreement analysis ONLY (not ground truth, not a gate):
# which way was JEV's continuous signal pointing on an escalated record?
def jev_lean(correct: float, quality: float, problematic: float) -> str:
    if correct < 0.6 or quality < 2.5 or problematic >= 0.30:
        return "REJECT-lean"
    return "ACCEPT-lean"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def classify_band(answers: dict, cfg: dict) -> str:
    c = answers["correct"]["noul"]
    q = answers["quality"]["score"]
    p = answers["problematic"]["noul"]
    if c >= cfg["C_HI"] and q >= cfg["Q_HI"] and p <= cfg["P_LO"]:
        return "HIGH"
    if c <= cfg["C_LO"] or q <= cfg["Q_LO"] or p >= cfg["P_HI"]:
        return "LOW"
    return "AMBIGUOUS"


def final_for(band: str, ai2_verdict: str | None) -> tuple[str, str]:
    """Returns (final_decision, decision_path)."""
    if band == "HIGH":
        return "ACCEPT", "jev_auto_accept"
    if band == "LOW":
        return "REJECT", "jev_auto_reject_quarantine"
    if ai2_verdict == "ACCEPT":
        return "ACCEPT", "ai2_accept"
    if ai2_verdict == "REJECT":
        return "REJECT", "ai2_reject"
    return "AMBIGUOUS", "ai2_unresolved"


def cmd_bands():
    jev, content, meta = load_inputs()
    print(f"records with JEV results: {len(jev)}")
    for name, cfg in CONFIGS.items():
        dist = Counter()
        for rid, r in jev.items():
            if r.get("status") != "ok":
                dist["JEV_ERROR"] += 1
            else:
                dist[classify_band(r["answers"], cfg)] += 1
        print(f"  {name}: {dict(dist)}")
    # union ambiguous
    union = [rid for rid, r in jev.items()
             if r.get("status") == "ok" and any(
                 classify_band(r["answers"], c) == "AMBIGUOUS"
                 for c in CONFIGS.values())]
    print(f"union-ambiguous (AI-2 candidates): {len(union)}")


def load_ai2() -> dict:
    out = {}
    if AI2_RESULTS.exists():
        for line in AI2_RESULTS.open():
            line = line.strip()
            if line:
                r = json.loads(line)
                out[r["record_id"]] = r
    return out


def cmd_run(limit=None):
    sys.path.insert(0, str(HERE))
    import ai2_reviewer
    jev, content, meta = load_inputs()
    done = load_ai2()
    todo = []
    for rid, r in jev.items():
        if r.get("status") != "ok":
            continue
        c = content.get(rid)
        if not c:
            continue
        if deterministic_validate(c["user"], c["assistant"])[0] != "VALID":
            continue
        if rid in done:
            continue
        if any(classify_band(r["answers"], cfg) == "AMBIGUOUS"
               for cfg in CONFIGS.values()):
            todo.append(rid)
    if limit:
        todo = todo[:limit]
    print(f"AI-2 candidates: {len(todo)} (already done: {len(done)}), "
          f"model blind review, no JEV data passed")
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
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:  # noqa: BLE001 — fail-safe capture
            reason = getattr(exc, "reason", type(exc).__name__)
            entry = {
                "record_id": rid,
                "content_sha256": sha256_text(json.dumps(
                    [c["user"], c["assistant"]], ensure_ascii=False)),
                "arm": r.get("arm"),
                "status": "error",
                "verdict": "ERROR",
                "error_reason": f"{reason}: {str(exc)[:200]}",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
        with open(AI2_RESULTS, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        n_done[0] += 1
        if n_done[0] % 25 == 0:
            print(f"  {n_done[0]}/{len(todo)} AI-2 calls done", flush=True)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, todo))
    print(f"AI-2 batch: {n_done[0]} calls in {time.perf_counter()-t0:.1f}s")


def build_results():
    jev, content, meta = load_inputs()
    ai2 = load_ai2()
    rows = []
    for rid, r in jev.items():
        c = content.get(rid, {})
        user, asst = c.get("user", ""), c.get("assistant", "")
        det_status, det_reasons = deterministic_validate(user, asst)
        a = ai2.get(rid)
        ai2_verdict = (a.get("verdict") if a else None)
        jev_ok = r.get("status") == "ok"
        entry = {
            "record_id": rid,
            "arm": r.get("arm"),
            "content_sha256": r.get("content_sha256"),
            "deterministic": {"status": det_status, "reasons": det_reasons},
            "jev": ({
                "status": r.get("status"),
                "model": r.get("model"),
                "correct": r["answers"]["correct"]["noul"],
                "quality": r["answers"]["quality"]["score"],
                "problematic": r["answers"]["problematic"]["noul"],
                "adherence": r["answers"]["adherence"]["noul"],
                "training_value": r["answers"]["training_value"]["score"],
                "latency_s": r.get("latency_s"),
                "input_tokens": r.get("input_tokens"),
                "output_tokens": r.get("output_tokens"),
            } if jev_ok else {"status": r.get("status"),
                              "error": r.get("error")}),
            "ai2": (None if a is None else {
                k: a.get(k) for k in (
                    "status", "verdict", "confidence", "correctness",
                    "completeness", "suitability", "rationale", "latency_s",
                    "input_tokens", "output_tokens", "model",
                    "error_reason", "reviewed_at")}),
            "per_config": {},
        }
        for name, cfg in CONFIGS.items():
            if det_status != "VALID":
                entry["per_config"][name] = {
                    "band": "N/A", "final": "REJECT",
                    "path": "deterministic_gate"}
            elif not jev_ok:
                entry["per_config"][name] = {
                    "band": "N/A", "final": "AMBIGUOUS",
                    "path": "jev_error_unresolved"}
            else:
                band = classify_band(r["answers"], cfg)
                invoked = band == "AMBIGUOUS"
                if invoked and ai2_verdict is None:
                    final, path = "AMBIGUOUS", "ai2_pending"
                elif invoked:
                    final, path = final_for(band, ai2_verdict)
                else:
                    final, path = final_for(band, None)
                entry["per_config"][name] = {
                    "band": band, "ai2_invoked": invoked,
                    "final": final, "path": path}
        rows.append(entry)
    rows.sort(key=lambda e: e["record_id"])
    with open(FILTER_RESULTS, "w") as f:
        for e in rows:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return rows


def summarize(rows):
    ai2 = load_ai2()
    ai2_ok = [a for a in ai2.values() if a.get("status") == "ok"]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_records": len(rows),
        "bands": "experimental operating thresholds; NOT calibrated (see README)",
        "ground_truth": None,
        "accuracy_claims": "NONE — workflow evaluation only; "
                           "Phase-2 human labels never used",
        "configs": {},
        "ai2": {
            "n_invoked_union": len(ai2),
            "n_ok": len(ai2_ok),
            "n_error": len(ai2) - len(ai2_ok),
            "verdict_dist": dict(Counter(a.get("verdict") for a in ai2.values())),
            "mean_confidence": (round(sum(a["confidence"] for a in ai2_ok
                                          if a.get("confidence") is not None)
                                      / max(1, sum(
                                          1 for a in ai2_ok
                                          if a.get("confidence") is not None)), 3)
                                if ai2_ok else None),
            "total_input_tokens": sum(a.get("input_tokens") or 0 for a in ai2_ok),
            "total_output_tokens": sum(a.get("output_tokens") or 0 for a in ai2_ok),
            "ai2_token_reporting": sum(1 for a in ai2_ok
                                       if a.get("input_tokens") is not None),
            "mean_latency_s": (round(sum(a["latency_s"] for a in ai2_ok
                                         if a.get("latency_s") is not None)
                                     / max(1, sum(
                                         1 for a in ai2_ok
                                         if a.get("latency_s") is not None)), 3)
                               if ai2_ok else None),
            "cost_usd": "NOT ESTIMATED — apply operator price card to tokens",
        },
    }
    # JEV baseline cost (reused, not respent)
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
    for name in CONFIGS:
        finals = Counter(e["per_config"][name]["final"] for e in rows)
        bands = Counter(e["per_config"][name]["band"] for e in rows)
        paths = Counter(e["per_config"][name]["path"] for e in rows)
        # lean-agreement on escalated-with-AI2-verdict records
        agree = dis = ai2_amb = 0
        for e in rows:
            pc = e["per_config"][name]
            if not pc.get("ai2_invoked") or e["ai2"] is None:
                continue
            v = e["ai2"].get("verdict")
            if v not in ("ACCEPT", "REJECT"):
                ai2_amb += 1
                continue
            lean = jev_lean(e["jev"]["correct"], e["jev"]["quality"],
                            e["jev"]["problematic"])
            lean_accept = lean == "ACCEPT-lean"
            if (v == "ACCEPT") == lean_accept:
                agree += 1
            else:
                dis += 1
        summary["configs"][name] = {
            "thresholds": CONFIGS[name],
            "jev_band_dist": dict(bands),
            "pct_auto_accept": round(100 * bands.get("HIGH", 0) / len(rows), 1),
            "pct_auto_reject": round(100 * bands.get("LOW", 0) / len(rows), 1),
            "pct_escalated": round(
                100 * bands.get("AMBIGUOUS", 0) / len(rows), 1),
            "final_dist": dict(finals),
            "path_dist": dict(paths),
            "ai2_lean_agreement": {"agree": agree, "disagree": dis,
                                   "ai2_ambiguous_or_error": ai2_amb},
            "n_unresolved_ambiguous": finals.get("AMBIGUOUS", 0),
        }
    with open(CONFIG_SUMMARY, "w") as f:
        json.dump(summary, f, indent=1)
    return summary


def cmd_report():
    rows = build_results()
    summary = summarize(rows)
    print(json.dumps(summary, indent=1)[:3000])
    print(f"... wrote {FILTER_RESULTS.name} ({len(rows)} records), "
          f"{CONFIG_SUMMARY.name}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "bands"
    if cmd == "bands":
        cmd_bands()
    elif cmd == "run":
        limit = None
        if "--limit" in sys.argv:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        cmd_run(limit)
        cmd_report()
    elif cmd == "report":
        cmd_report()
    else:
        print("unknown command", cmd)
        sys.exit(1)
