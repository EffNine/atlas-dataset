"""Small bounded JEV pass over v1.1 training candidates (never the full corpus).

Reuses the jev-pilot-atlas-v0.1 question set (imported, not copied) and the
jev-quality-filter-v0.2 router + blind AI-2 boundary (imported, not copied).

Routing (balanced policy): HIGH -> KEEP, LOW -> REJECT, AMBIGUOUS -> live
blind AI-2 (ACCEPT->KEEP, REJECT->REJECT, else QUARANTINE). JEV error ->
QUARANTINE. Fail closed everywhere. No human labels. No accuracy claims.
JEV outputs are routing signals, never ground truth.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atlas_paths import get_root  # noqa: E402

from source_discovery.ai2_adapter import review_or_quarantine  # noqa: E402
from source_discovery.corpus_v1_1 import (  # noqa: E402
    V11, _guard_write, _read_jsonl, _utcnow, _write_jsonl)
from source_discovery.jev_adapter import load_router  # noqa: E402

JEV_DIR = V11 / "jev"
PILOT_RUNNER = (get_root() / "experiments" / "jev-pilot-atlas-v0.1"
                / "run_jev_pilot.py")
MAX_CONTENT_CHARS = 8000
POLICY = "balanced"


def load_pilot_questions() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("sd_jev_pilot_runner",
                                                  PILOT_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load jev pilot runner")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return {"QUESTIONS": mod.QUESTIONS,
            "to_typed": mod._to_typed_questions}


def select_candidates(n_total: int = 100) -> list[dict]:
    """Deterministic stride sample across hsc + tomato kept rows.

    SINGLE streaming pass per source, stride over file order (source order
    is deterministic for a pinned revision: Hub stream order / chapter-id
    order). No full-file load, no sort — constant memory.
    """
    import json as _json

    staged: dict[str, Path] = {}
    for sid in ("hsc-wuxia-100k", "tomato-zh2en"):
        kp = V11 / "staging" / sid / "kept.jsonl"
        if kp.exists():
            staged[sid] = kp
    if not staged:
        return []
    # Count pass (cheap line count, no JSON parse).
    counts = {}
    for sid, kp in staged.items():
        with open(kp, "rb") as f:
            counts[sid] = sum(1 for _ in f)
    n_each = max(1, n_total // len(staged))
    out: list[dict] = []
    for sid, kp in staged.items():
        stride = max(1, counts[sid] // n_each)
        want_idx = set(range(0, counts[sid], stride)[:n_each])
        with open(kp, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i in want_idx:
                    try:
                        out.append(_json.loads(line))
                    except ValueError:
                        continue
                if len(want_idx) and i > max(want_idx):
                    break
    # Deterministic order: by record id within source.
    out.sort(key=lambda r: (r.get("source_id", ""), r.get("id", "")))
    return out[:n_total]


def jev_state(rec: dict) -> dict:
    return {
        "category": f"translation:{rec.get('source_id', '')}",
        "subcategory": (f"{rec.get('source_lang', '')}→"
                        f"{rec.get('target_lang', '')}"),
        "messages": [
            {"role": "user",
             "content": rec.get("source", "")[:MAX_CONTENT_CHARS]},
            {"role": "assistant",
             "content": rec.get("target", "")[:MAX_CONTENT_CHARS]},
        ],
    }


def run_bounded_jev(n_total: int = 100) -> dict[str, Any]:
    from typesafe_sdk import TypeSafeClient

    JEV_DIR.mkdir(parents=True, exist_ok=True)
    pilot = load_pilot_questions()
    typed_questions = pilot["to_typed"]()
    router = load_router()
    if not router.get("available"):
        raise RuntimeError(f"router unavailable: {router.get('reason')}")
    mod = router["module"]

    out_path = JEV_DIR / "jev_results.jsonl"
    done: dict[str, dict] = {}
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            line = line.strip()
            if line:
                r = json.loads(line)
                done[r["record_id"]] = r

    cands: list[dict] = []
    if len(done) < n_total:
        cands = [c for c in select_candidates(n_total)
                 if c["id"] not in done]
    else:
        # Sample already complete from a prior run: route stored results
        # only (no new selection, no new live calls).
        pass
    client = None
    if cands:
        client = TypeSafeClient()
    in_tok = out_tok = 0
    lat_sum = 0.0
    n_ok = n_err = 0

    def work(rec: dict) -> dict:
        assert client is not None  # work only runs over non-empty cands
        state = jev_state(rec)
        t0 = time.perf_counter()
        entry: dict[str, Any] = {
            "record_id": rec["id"],
            "content_sha256": rec.get("content_sha256"),
            "source_id": rec.get("source_id"),
            "direction": (f"{rec.get('source_lang')}→"
                          f"{rec.get('target_lang')}"),
            "policy": POLICY,
            "formula_version": mod.FORMULA_VERSION,
            "status": None, "answers": None, "latency_s": None,
            "input_tokens": None, "output_tokens": None,
            "error": None, "sampled_utc": _utcnow(),
        }
        try:
            resp = client.system_one(state=state, questions=typed_questions)
            entry.update(status="ok",
                         latency_s=round(time.perf_counter() - t0, 3),
                         model=getattr(resp, "model", None),
                         request_id=getattr(resp, "request_id", None),
                         answers={})
            for name, qdef in pilot["QUESTIONS"].items():
                if qdef["type"] == "noul":
                    a = resp.nouls[name]
                    entry["answers"][name] = {"noul": round(a.noul, 4)}
                else:
                    a = resp.scores[name]
                    entry["answers"][name] = {
                        "score": round(a.score, 3),
                        "probabilities": {
                            str(k): round(v, 4)
                            for k, v in a.probabilities.items()}}
            usage = getattr(resp, "usage", None)
            entry["input_tokens"] = getattr(usage, "input_tokens", None)
            entry["output_tokens"] = getattr(usage, "output_tokens", None)
        except Exception as exc:  # noqa: BLE001 — fail closed downstream
            entry.update(status="error",
                         error=f"{type(exc).__name__}: {str(exc)[:300]}")
        return entry

    results: list[dict] = []
    max_workers = int(os.environ.get("SD_JEV_WORKERS", "8"))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for entry in pool.map(work, cands):
            results.append(entry)
            if entry["status"] == "ok":
                n_ok += 1
            else:
                n_err += 1
            in_tok += entry.get("input_tokens") or 0
            out_tok += entry.get("output_tokens") or 0
            lat_sum += entry.get("latency_s") or 0

    with open(out_path, "a", encoding="utf-8") as f:
        for e in results:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # Route every stored result (new + previously done) via the real router.
    all_results = list(done.values()) + results
    by_id = {e["record_id"]: e for e in all_results}
    # AI-2 verdict cache: single-sample AI-2 verdicts vary run to run, so
    # cache the first live verdict per record for rerun stability.
    ai2_cache_path = JEV_DIR / "ai2_cache.jsonl"
    ai2_cache: dict[str, dict] = {}
    if ai2_cache_path.exists():
        for line in ai2_cache_path.open(encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    c = json.loads(line)
                    ai2_cache[c["record_id"]] = c
                except (ValueError, KeyError):
                    continue
    # Streaming lookup of the (few) routed records' full content: never load
    # the multi-GB corpus into memory.
    staged = V11 / "corpus" / "training_ready.jsonl"
    need = {e["record_id"] for e in all_results}
    content_by_id: dict[str, dict] = {}
    if staged.exists():
        import json as _json2
        with open(staged, encoding="utf-8") as f:
            for line in f:
                if len(content_by_id) >= len(need):
                    break
                try:
                    r = _json2.loads(line)
                except ValueError:
                    continue
                if r.get("id") in need:
                    content_by_id[r["id"]] = r
    finals: list[dict] = []
    ai2_calls = 0
    for rid, e in sorted(by_id.items()):
        if e.get("status") != "ok":
            finals.append({"record_id": rid, "band": "N/A",
                           "final": "QUARANTINE",
                           "path": "jev_error_unresolved",
                           "quarantine": True})
            continue
        routed = mod.route_record(e["answers"], POLICY)
        band = routed["band"]
        if band == "HIGH":
            finals.append({"record_id": rid, "band": band, "final": "KEEP",
                           "path": routed["path"], "quarantine": False,
                           "confidence": routed.get("confidence")})
        elif band == "LOW":
            finals.append({"record_id": rid, "band": band, "final": "REJECT",
                           "path": routed["path"], "quarantine": True,
                           "confidence": routed.get("confidence")})
        else:
            rec = content_by_id.get(rid, {})
            if rid in ai2_cache:
                ai2 = ai2_cache[rid]["verdict"]
                ai2_conf = ai2_cache[rid].get("confidence")
                ai2_calls += 0  # cached: no new live call
            else:
                live = review_or_quarantine(
                    rec.get("source", ""), rec.get("target", ""),
                    rec.get("source_id", ""),
                    f"{rec.get('source_lang', '')}→"
                    f"{rec.get('target_lang', '')}",
                    "web_novel", allow_live_call=True)
                ai2_calls += 1
                v_live = live.get("verdict")
                d_live = live.get("detail") or {}
                ai2_cache[rid] = {"record_id": rid, "verdict": v_live,
                                  "confidence": d_live.get("confidence"),
                                  "cached_utc": _utcnow()}
                ai2, ai2_conf = v_live, d_live.get("confidence")
            v = ai2
            if v == "ACCEPT":
                fin, quar = "KEEP", False
            elif v == "REJECT":
                fin, quar = "REJECT", False
            else:
                fin, quar = "QUARANTINE", True
            finals.append({"record_id": rid, "band": band, "final": fin,
                           "path": f"ai2_{str(v).lower()}",
                           "quarantine": quar,
                           "confidence": routed.get("confidence"),
                           "ai2_verdict": v,
                           "ai2_confidence": ai2_conf})

    with open(ai2_cache_path, "w", encoding="utf-8") as f:
        for rid in sorted(ai2_cache):
            f.write(json.dumps(ai2_cache[rid], ensure_ascii=False) + "\n")

    with open(JEV_DIR / "jev_finals.jsonl", "w", encoding="utf-8") as f:
        for x in finals:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")

    from collections import Counter
    dist = Counter(x["final"] for x in finals)
    stats = {
        "ran_utc": _utcnow(), "policy": POLICY,
        "formula_version": mod.FORMULA_VERSION,
        "n_evaluated_total": len(all_results),
        "n_new_this_run": len(results), "n_ok": n_ok, "n_errors": n_err,
        "total_input_tokens": in_tok, "total_output_tokens": out_tok,
        "mean_latency_s": round(lat_sum / max(1, len(results)), 3),
        "final_dist": dict(dist), "ai2_calls": ai2_calls,
        "ai2_cached_reuse": (sum(1 for x in finals
                                 if x["band"] == "AMBIGUOUS") - ai2_calls),
        "note": "routing signals only — not ground truth, no accuracy claims",
    }
    with open(JEV_DIR / "jev_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    # Quarantine corpus: full records for every sampled non-KEEP final
    # (REJECT and QUARANTINE alike — never silently left in training-ready).
    quar = [content_by_id[r] for r in
            [x["record_id"] for x in finals if x["final"] != "KEEP"]
            if r in content_by_id]
    _write_jsonl(V11 / "corpus" / "quarantine.jsonl", quar)
    removals = [{"record_id": x["record_id"], "final": x["final"],
                 "band": x["band"], "path": x["path"]}
                for x in finals if x["final"] != "KEEP"]
    with open(V11 / "jev" / "post_jev_removals.json", "w",
              encoding="utf-8") as f:
        json.dump({"generated_utc": _utcnow(),
                   "note": "tombstone overlay: consumers MUST exclude these "
                           "ids from training_ready.jsonl and its splits",
                   "n_removed": len(removals), "removed": removals},
                  f, indent=2, ensure_ascii=False)
    return stats
