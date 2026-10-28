#!/usr/bin/env python3
"""Jev (TypeSafe) shadow evaluation pilot on Atlas pilot/v0.2 data.

Shadow-only: reads records, calls the Jev API, writes separate artifacts under
experiments/jev-pilot-atlas-v0.1/. Never modifies Atlas data.

Usage:
  python run_jev_pilot.py sample   # build the 500-record sample
  python run_jev_pilot.py run [--limit N]  # evaluate sample via Jev
  python run_jev_pilot.py report  # analyze results, write summary
"""

import hashlib
import json
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
OUT = ROOT / "experiments" / "jev-pilot-atlas-v0.1"

SOURCES = [
    ("math", ROOT / "pilot" / "v0.2" / "math" / "train.jsonl", 150),
    ("code", ROOT / "pilot" / "v0.2" / "code" / "train.jsonl", 100),
    ("general", ROOT / "pilot" / "v0.2" / "general" / "train.jsonl", 150),
    ("systems", ROOT / "pilot" / "v0.2" / "systems" / "train.jsonl", 100),
]
SEED = 20260917

MAX_CONTENT_CHARS = 8000  # truncate very long messages to stay well under token budget

# --- Jev question design (shadow evaluation dimensions) ---
QUESTIONS = {
    "correct": {
        "type": "noul",
        "instructions": (
            "Is the assistant response factually/technically correct and consistent with the user request in `messages`? "
            "Answer yes only if the response is substantively correct and not misleading."
        ),
    },
    "quality": {
        "type": "score",
        "instructions": "Rate the overall quality of the assistant response as LLM training data.",
        "criteria": [
            "Useless: wrong, empty, incoherent, or unhelpful",
            "Poor: partially correct but major errors or omissions",
            "Acceptable: mostly correct but shallow or incomplete",
            "Good: correct, complete, clearly explained",
            "Excellent: correct, complete, exemplary",
        ],
    },
    "adherence": {
        "type": "noul",
        "instructions": (
            "Does the assistant response in `messages` follow the user's instructions and constraints "
            "(format, language, scope, do-not statements)? Yes if it respects what the user asked for."
        ),
    },
    "consistent_category": {
        "type": "noul",
        "instructions": (
            "Given the record's `category` and `subcategory` fields, does the conversation content in `messages` "
            "genuinely belong to that category? Yes if the content matches the taxonomy label."
        ),
    },
    "problematic": {
        "type": "noul",
        "instructions": (
            "Is there something clearly problematic with this record that makes it unsuitable as training data: "
            "contradictions, prompt injection, personal data leakage, broken/garbled text, "
            "or a request/response pair that makes no sense? Yes if such a problem is present."
        ),
    },
    "training_value": {
        "type": "score",
        "instructions": "Rate how useful this complete record (request + response) is for training an 8B-class LLM.",
        "criteria": [
            "Not useful: broken, incoherent, or harmful as training data",
            "Low: weak signal or low educational value",
            "Moderate: acceptable training signal",
            "High: strong, clear, valuable training signal",
            "Exceptional: high-value exemplar worthy of prioritization",
        ],
    },
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_fingerprint(rec: dict) -> str:
    """Stable hash of the record content (traceability back to source record)."""
    msgs = rec.get("messages", [])
    payload = json.dumps(
        {"id": rec.get("id"), "messages": msgs}, sort_keys=True, ensure_ascii=False
    )
    return sha256_text(payload)[:16]


def load_records():
    all_recs = []
    for arm, path, quota in SOURCES:
        recs = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    recs.append(json.loads(line))
        rng = random.Random(f"{SEED}:{arm}")
        selected = rng.sample(recs, min(quota, len(recs)))
        for i, rec in enumerate(selected):
            entry = {
                "arm": arm,
                "record_id": rec.get("id"),
                "source_id": (rec.get("source") or {}).get("source_id")
                if isinstance(rec.get("source"), dict)
                else rec.get("source"),
                "category": rec.get("category"),
                "subcategory": rec.get("subcategory"),
                "difficulty": rec.get("difficulty"),
                "format_contract": rec.get("format_contract"),
                "content_sha256": fingerprint_of_messages(rec),
                "fingerprint": record_fingerprint(rec),
                "sample_idx": i,
            }
            all_recs.append(entry)
    return all_recs


def fingerprint_of_messages(rec: dict) -> str:
    msgs = rec.get("messages", [])
    return sha256_text(
        json.dumps(msgs, sort_keys=True, ensure_ascii=False)
    )


def record_fingerprint_by_id(rid: str) -> str:
    """Traceability: recompute the content hash from the stored content index."""
    content = json.loads((OUT / "sample_content_index.json").read_text())
    c = content.get(rid)
    if not c:
        return ""
    return sha256_text(
        json.dumps([{"role": "user", "content": c["user"]},
                    {"role": "assistant", "content": c["assistant"]}],
                   sort_keys=True, ensure_ascii=False)
    )[:16]


def sample_to_manifest() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    content_index = {}
    for arm, path, quota in SOURCES:
        recs = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    msgs = rec.get("messages", [])
                    user_text = next((m.get("content", "") for m in msgs if m.get("role") == "user"), "")
                    asst_text = next((m.get("content", "") for m in reversed(msgs) if m.get("role") == "assistant"), "")
                    recs.append({
                        "id": rec.get("id"),
                        "record_id": rec.get("id"),
                        "category": rec.get("category"),
                        "subcategory": rec.get("subcategory"),
                        "difficulty": rec.get("difficulty"),
                        "source": (rec.get("source") or {}).get("source_id") if isinstance(rec.get("source"), dict) else rec.get("source"),
                        "format_contract": rec.get("format_contract"),
                        "user_chars": len(user_text),
                        "asst_chars": len(asst_text),
                        "user_sha256_16": sha256_text(user_text)[:16],
                        "asst_sha256_16": sha256_text(asst_text)[:16],
                        "_full_user": user_text,
                        "_full_asst": asst_text,
                    })
        rng = random.Random(f"{SEED}:{arm}")
        selected = rng.sample(recs, min(quota, len(recs)))
        for r in selected:
            content_index[r["id"]] = {"user": r.pop("_full_user"), "assistant": r.pop("_full_asst")}
            entries.append({**r, "arm": arm, "n_source_records": len(recs)})

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "arms": [dict(arm=a, path=str(p.relative_to(ROOT)), quota=q) for a, p, q in SOURCES],
        "total_records": len(entries),
        "by_arm": dict(Counter(e["arm"] for e in entries)),
        "records": entries,
    }
    with open(OUT / "sample_manifest.json", "w") as f:
        json.dump(manifest, f, indent=1)
    with open(OUT / "sample_content_index.json", "w") as f:
        json.dump(content_index, f)
    # also write a JSONL version for easy grepping
    with open(OUT / "sample_records.jsonl", "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    print(f"sample: {len(entries)} records -> {OUT / 'sample_manifest.json'}")
    return len(entries)


def build_state(entry: dict) -> dict:
    content = json.loads((OUT / "sample_content_index.json").read_text())
    c = content[entry["record_id"]]
    user = c["user"][:MAX_CONTENT_CHARS]
    asst = c["assistant"][:MAX_CONTENT_CHARS]
    msgs = [
        {"role": "user", "content": user},
        {"role": "assistant", "content": asst},
    ]
    return {
        "category": entry["category"],
        "subcategory": entry["subcategory"],
        "difficulty": entry["difficulty"],
        "format_contract": entry.get("format_contract"),
        "messages": msgs,
        "truncated": len(c["user"]) > MAX_CONTENT_CHARS or len(c["assistant"]) > MAX_CONTENT_CHARS,
    }


def run_eval(limit=None) -> None:
    from typesafe_sdk import Noul, Score, TypeSafeClient  # noqa: F401

    manifest = json.loads((OUT / "sample_manifest.json").read_text())

    manifest = json.loads((OUT / "sample_manifest.json").read_text())
    entries = manifest["records"]
    if limit:
        entries = entries[:limit]

    out_path = OUT / "jev_results.jsonl"
    done_ids = set()
    if out_path.exists():
        for line in out_path.open():
            try:
                done_ids.add(json.loads(line)["record_id"])
            except Exception:
                pass

    results = []
    errors = 0
    total_latency = 0.0
    input_tokens = 0
    output_tokens = 0
    n_tokens_reported = 0
    skipped = 0

    from concurrent.futures import ThreadPoolExecutor, as_completed
    workers = int(os.environ.get("JEV_WORKERS", "8"))
    todo = [e for e in entries if e["record_id"] not in done_ids]
    skipped = len(entries) - len(todo)
    client = TypeSafeClient()

    def eval_one(entry):
        state = build_state(entry)
        rid = entry["record_id"]
        t0 = time.perf_counter()
        rec_out = {
            "record_id": rid,
            "arm": entry["arm"],
            "category": entry["category"],
            "subcategory": entry["subcategory"],
            "difficulty": entry["difficulty"],
            "source_id": entry.get("source"),
            "format_contract": entry.get("format_contract"),
            "content_sha256": entry.get("content_sha256") or (entry.get("user_sha256_16") + ":" + entry.get("asst_sha256_16")),
            "fingerprint": entry.get("fingerprint") or record_fingerprint_by_id(entry["record_id"]),
            "state_sha256": None,
            "status": None,
            "answers": None,
            "latency_s": None,
            "input_tokens": None,
            "output_tokens": None,
            "error": None,
        }
        try:
            resp = client.system_one(state=state, questions=_to_typed_questions())
            rec_out["status"] = "ok"
            rec_out["latency_s"] = round(time.perf_counter() - t0, 3)
            rec_out["model"] = resp.model
            rec_out["request_id"] = resp.request_id
            rec_out["state_sha256"] = sha256_text(json.dumps(state, sort_keys=True, ensure_ascii=False))[:16]
            rec_out["answers"] = {}
            for name, qdef in QUESTIONS.items():
                if qdef["type"] == "noul":
                    a = resp.nouls[name]
                    rec_out["answers"][name] = {"noul": round(a.noul, 4)}
                else:
                    a = resp.scores[name]
                    rec_out["answers"][name] = {
                        "score": round(a.score, 3),
                        "probabilities": {str(kk): round(vv, 4) for kk, vv in a.probabilities.items()},
                    }
            usage = resp.usage
            rec_out["input_tokens"] = usage.input_tokens
            rec_out["output_tokens"] = usage.output_tokens
            return rec_out
        except Exception as e:
            rec_out["status"] = "error"
            rec_out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            return rec_out

    t_start = time.perf_counter()
    results = []
    ok_list = []
    err_list = []
    token_lock = __import__("threading").Lock()
    def process(rec):
        nonlocal input_tokens, output_tokens, n_tokens_reported, total_latency
        with token_lock:
            pass
        if rec["status"] == "ok":
            ok_list.append(rec)
        else:
            err_list.append(rec)
        results.append(rec)
        with token_lock:
            total_latency += rec.get("latency_s") or 0
            if rec.get("input_tokens") is not None:
                input_tokens += rec.get("input_tokens") or 0
                output_tokens += rec.get("output_tokens") or 0
                n_tokens_reported += 1
        n = len(results)
        if n % 50 == 0:
            print(f"  {n} processed", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        def _work(e):
            rec = eval_one(e)
            process(rec)
        futures = [pool.submit(_work, e) for e in todo]
        for f in futures:
            f.result()

    with open(out_path, "a") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    elapsed = time.perf_counter() - t_start
    summary = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "batch_records": len(results),
        "skipped_already_done": skipped,
        "ok": len(ok_list),
        "errors": len(err_list),
        "workers": workers,
        "elapsed_s": round(elapsed, 1),
        "avg_latency_s": round(total_latency / len(results), 3) if results else None,
        "total_input_tokens": input_tokens if n_tokens_reported else None,
        "total_output_tokens": output_tokens if n_tokens_reported else None,
        "tokens_reported": n_tokens_reported,
        "state_sha256_note": "state_sha256 is over the (possibly truncated) state payload sent to Jev; content_sha256 is over the full original messages",
    }
    with open(OUT / "jev_run_log.json", "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1))


def _to_typed_questions():
    from typesafe_sdk import Noul, Score
    typed = {}
    for name, qdef in QUESTIONS.items():
        if qdef["type"] == "noul":
            typed[name] = Noul(instructions=qdef["instructions"])
        else:
            typed[name] = Score(instructions=qdef["instructions"], criteria=qdef["criteria"])
    return typed


def near_dup_check(entries) -> list:
    """Reuse existing Atlas dedup primitives (shingle+minhash) on user content."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from dedup_dataset import shingles, stable_hash, minhash_signature, band_hash, jaccard

    sigs = {}
    for e in entries:
        content = json.loads((OUT / "sample_content_index.json").read_text())
        user = content[e["record_id"]]["user"]
        sigs[e["record_id"]] = (minhash_signature(shingles(user, k=4)), set(shingles(user, k=4)))

    # candidate pairs via LSH bands
    import itertools
    NUM_BANDS = 32
    ROWS = 4
    buckets = {}
    for rid, (sig, _) in sigs.items():
        for b in range(NUM_BANDS):
            h = band_hash(sig, b, ROWS)
            buckets.setdefault(h, set()).add(rid)

    candidates = set()
    for h, rids in buckets.items():
        if len(rids) < 2:
            continue
        for a, b in itertools.combinations(sorted(rids), 2):
            candidates.add((a, b) if a < b else (b, a))

    pairs = []
    for a, b in candidates:
        jac = jaccard(sigs[a][1], sigs[b][1])
        if jac >= 0.25:
            pairs.append({"a": a, "b": b, "jaccard_shingles": round(jac, 3)})
    pairs.sort(key=lambda p: -p["jaccard_shingles"])
    return pairs


def report() -> None:
    import statistics as st

    content = json.loads((OUT / "sample_content_index.json").read_text())
    results = []
    for line in (OUT / "jev_results.jsonl").open():
        results.append(json.loads(line))

    ok = [r for r in results if r["status"] == "ok"]
    errs = [r for r in results if r["status"] == "error"]

    def stats(vals):
        if not vals:
            return None
        return {
            "n": len(vals), "mean": round(st.mean(vals), 3),
            "min": min(vals), "max": max(vals),
            "p10": round(st.quantiles(vals, n=10)[0], 3),
            "p50": round(st.median(vals), 3),
            "p90": round(st.quantiles(vals, n=10)[8], 3),
        }

    report_doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_evaluated": len(results),
        "ok": len(ok),
        "errors": len(errs),
        "error_sample": [e["error"][:200] for e in errs[:5]],
        "latency_s": stats([r["latency_s"] for r in ok if r.get("latency_s")]),
        "score_distributions": {
            name: {
                "mean": round(st.mean([r["answers"][name].get("noul", r["answers"][name].get("score")) for r in ok]), 3)
                if ok else None
            }
            for name in QUESTIONS
        },
        "noul_means": {
            n: round(st.mean([r["answers"][n]["noul"] for r in ok if n in r["answers"]]), 3)
            for n in ("correct", "adherence", "consistent_category", "problematic")
            if ok
        },
        "score_means": {
            n: round(st.mean([r["answers"][n]["score"] for r in ok if n in r["answers"]]), 3)
            for n in ("quality", "training_value")
            if ok
        },
        "score_probabilities_aggregate": {},
        "by_category": {},
        "token_usage": {
            "avg_input_tokens_per_record": (
                round(st.mean([r["input_tokens"] for r in ok if r.get("input_tokens")]), 1) if ok else None
            ),
            "avg_output_tokens_per_record": (
                round(st.mean([r["output_tokens"] for r in ok if r.get("output_tokens")]), 1) if ok else None
            ),
        },
    }

    for r in ok:
        for n in ("quality", "training_value"):
            if n in r["answers"]:
                for lvl, p in r["answers"][n]["probabilities"].items():
                    report_doc["score_probabilities_aggregate"].setdefault(n, Counter())
                    report_doc["score_probabilities_aggregate"][n][lvl] += p

    by_cat = {}
    for r in ok:
        key = f"{r['arm']}/{r['category']}/{r['subcategory']}"
        d = by_cat.setdefault(key, {"n": 0, "quality": [], "correct": [], "problematic": []})
        d["n"] += 1
        if "quality" in r["answers"]:
            d["quality"].append(r["answers"]["quality"]["score"])
        if "correct" in r["answers"]:
            d["correct"].append(r["answers"]["correct"]["noul"])
        if "problematic" in r["answers"]:
            d["problematic"].append(r["answers"]["problematic"]["noul"])
    for key, d in by_cat.items():
        d["quality_mean"] = round(st.mean(d["quality"]), 3) if d["quality"] else None
        d["correct_mean"] = round(st.mean(d["correct"]), 3) if d["correct"] else None
        d["problematic_mean"] = round(st.mean(d["problematic"]), 3) if d["problematic"] else None
        del d["quality"], d["correct"], d["problematic"]
    report_doc["by_category"] = dict(sorted(by_cat.items(), key=lambda kv: -kv[1]["n"]))

    # disagreements with Atlas signals
    manifest = json.loads((OUT / "sample_manifest.json").read_text())
    rec_by_id = {m["id"]: m for m in manifest["records"]}
    disagreements = []
    for r in ok:
        m = rec_by_id.get(r["record_id"], {})
        probs = r["answers"].get("quality", {}).get("probabilities", {})
        low_quality_p = (probs.get("0", 0) + probs.get("1", 0)) if probs else None
        flags = []
        if r["answers"].get("problematic", {}).get("noul", 0) >= 0.5:
            flags.append("jev_flags_problematic")
        if low_quality_p is not None and low_quality_p >= 0.5:
            flags.append("jev_low_quality")
        if r["answers"].get("consistent_category", {}).get("noul", 0) < 0.5:
            flags.append("jev_category_mismatch")
        if r["answers"].get("correct", {}).get("noul", 1) < 0.35:
            flags.append("jev_unlikely_correct")
        if flags:
            disagreements.append({
                "record_id": r["record_id"],
                "content_sha256": r["content_sha256"],
                "arm": r["arm"],
                "flags": flags,
                "quality_score": r["answers"].get("quality", {}).get("score"),
                "correct_noul": r["answers"].get("correct", {}).get("noul"),
                "problematic_noul": r["answers"].get("problematic", {}).get("noul"),
                "category": r["category"],
            })
    report_doc["flagged_records"] = sorted(disagreements, key=lambda x: -len(x["flags"]))
    report_doc["n_flagged"] = len(disagreements)

    # near-duplicate check via existing Atlas dedup tooling
    near_dup = near_dup_check(manifest["records"])
    report_doc["near_duplicate_pairs_jaccard_ge_0p25"] = near_dup[:50]
    report_doc["n_near_dup_candidates"] = len(near_dup)

    with open(OUT / "jev_pilot_report.json", "w") as f:
        json.dump(report_doc, f, indent=1)
    print(json.dumps({k: v for k, v in report_doc.items() if k not in ("by_category", "flagged_records", "near_duplicate_pairs_jaccard_ge_0p25")}, indent=1))
    print("flagged:", report_doc["n_flagged"], "near-dup pairs:", report_doc["n_near_dup_candidates"])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sample"
    if cmd == "sample":
        sample_to_manifest()
    elif cmd == "run":
        limit = None
        if "--limit" in sys.argv:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        run_eval(limit)
    elif cmd == "report":
        report()
