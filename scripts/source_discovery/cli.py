#!/usr/bin/env python3
"""Atlas Source Discovery v1.0 CLI.

Subcommands (all isolated to metadata/source_discovery/ + tmp/):
  build-registry  — write the versioned registry from candidates.py
  verify          — live metadata verification (HF API + HTTP HEAD)
  ingest-smoke    — tiny opus-100 streaming smoke ingest + stage + stats
  jev-smoke       — JEV router wiring check (synthetic signals only)
  ai2-probe       — AI-2 blindness + fail-closed check (no live call)
  stats           — print registry + smoke stats summaries
  report          — write a machine-readable v1 summary JSON

Examples:
  .venv/bin/python -m source_discovery.cli build-registry
  .venv/bin/python -m source_discovery.cli verify --no-http
  .venv/bin/python -m source_discovery.cli ingest-smoke --per-lang 30
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas_paths import get_root  # noqa: E402
from source_discovery.ai2_adapter import (  # noqa: E402
    EXPECTED_PAYLOAD_KEYS, build_ai2_request, review_or_quarantine)
from source_discovery.candidates import build_initial_candidates  # noqa: E402
from source_discovery.jev_adapter import load_router, smoke_dataflow  # noqa: E402
from source_discovery.pipeline import (  # noqa: E402
    SD_METADATA, ingest_opus100_sample)
from source_discovery.registry import (  # noqa: E402
    REGISTRY_VERSION, load_registry, registry_stats, save_registry,
    validate_source_entry)
from source_discovery.verify import verify_registry  # noqa: E402

REGISTRY_PATH = SD_METADATA / "v1" / "source_registry_v1.json"
VERIFY_PATH = SD_METADATA / "v1" / "verification_report_v1.json"
SMOKE_PATH = SD_METADATA / "v1" / "smoke_stats_v1.json"


def cmd_build_registry(_args: argparse.Namespace) -> int:
    sources = build_initial_candidates()
    errors = []
    for e in sources:
        errs = validate_source_entry(e)
        if errs:
            errors.append({"source_id": e.get("source_id"), "errors": errs})
    if errors:
        print(json.dumps({"ok": False, "validation_errors": errors}, indent=2))
        return 1
    payload = save_registry(REGISTRY_PATH, sources)
    print(f"registry v{REGISTRY_VERSION}: {payload['n_sources']} sources "
          f"-> {REGISTRY_PATH.relative_to(get_root())}")
    print(json.dumps(registry_stats(sources), indent=2, ensure_ascii=False))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    data = load_registry(REGISTRY_PATH)
    sources = data["sources"]
    report = verify_registry(sources, check_http=not args.no_http)
    save_registry(REGISTRY_PATH, sources, verification={
        "verified_at": report["verified_at"], "n_hf_ok": report["n_hf_ok"],
        "n_http_ok": report["n_http_ok"]})
    VERIFY_PATH.parent.mkdir(parents=True, exist_ok=True)
    VERIFY_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                           + "\n", encoding="utf-8")
    print(f"verified {report['n_sources']}: hf_ok={report['n_hf_ok']} "
          f"http_ok={report['n_http_ok']}")
    print(f"registry updated; report -> "
          f"{VERIFY_PATH.relative_to(get_root())}")
    return 0


def cmd_ingest_smoke(args: argparse.Namespace) -> int:
    report = ingest_opus100_sample(per_lang=args.per_lang)
    SMOKE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SMOKE_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                          + "\n", encoding="utf-8")
    print(f"smoke usable={report['n_usable']}/{report['n_normalized']} "
          f"by_direction={report['by_direction']}")
    print(f"rejected={report['quality_filter']} dup={report['dedup']}")
    print(f"staged: {report['staged_files']}")
    print(f"stats -> {SMOKE_PATH.relative_to(get_root())}")
    return 0


def cmd_jev_smoke(args: argparse.Namespace) -> int:
    loaded = load_router()
    print(f"router available={loaded.get('available')} "
          f"formula={loaded.get('formula_version')}")
    out = smoke_dataflow(n_per_band=args.n_per_band)
    print(json.dumps(out, indent=2, ensure_ascii=False)[:3000])
    return 0 if out.get("ok") else 1


def cmd_ai2_probe(_args: argparse.Namespace) -> int:
    msgs = build_ai2_request("夜色的街道很安静。", "The night street is quiet.",
                             "opus-100", "zh→en", "subtitle")
    import json as _json
    payload = _json.loads(msgs[1]["content"])
    keys_ok = set(payload.keys()) == set(EXPECTED_PAYLOAD_KEYS)
    leaks = any(k in payload for k in ("jev", "confidence", "band", "score"))
    res = review_or_quarantine("夜色的街道很安静。",
                               "The night street is quiet.",
                               "opus-100", "zh→en", "subtitle",
                               allow_live_call=False)
    print(f"payload_keys_ok={keys_ok} no_jev_leak={not leaks} "
          f"fail_closed={res['quarantine'] and res['verdict'] == 'NOT-CALLED'}")
    return 0 if (keys_ok and not leaks and res["quarantine"]) else 1


def cmd_stats(_args: argparse.Namespace) -> int:
    data = load_registry(REGISTRY_PATH)
    print(json.dumps(registry_stats(data["sources"]), indent=2,
                     ensure_ascii=False))
    if SMOKE_PATH.exists():
        smoke = json.loads(SMOKE_PATH.read_text(encoding="utf-8"))
        print(f"smoke: usable={smoke.get('n_usable')} "
              f"by_direction={smoke.get('by_direction')}")
    return 0


def cmd_report(_args: argparse.Namespace) -> int:
    data = load_registry(REGISTRY_PATH)
    verify = json.loads(VERIFY_PATH.read_text(encoding="utf-8")) \
        if VERIFY_PATH.exists() else {}
    smoke = json.loads(SMOKE_PATH.read_text(encoding="utf-8")) \
        if SMOKE_PATH.exists() else {}
    summary = {
        "registry_version": REGISTRY_VERSION,
        "registry": registry_stats(data["sources"]),
        "verification": {k: verify.get(k) for k in
                         ("verified_at", "n_sources", "n_hf_ok", "n_http_ok")},
        "smoke": {k: smoke.get(k) for k in
                  ("smoke", "n_normalized", "n_usable", "by_direction",
                   "by_domain", "quality_filter", "dedup",
                   "jev_boundary_smoke", "source_revision")},
    }
    outp = SD_METADATA / "v1" / "source_discovery_v1_summary.json"
    outp.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


# --- v1.1 corpus build -------------------------------------------------------

def cmd_v11_hsc(_args: argparse.Namespace) -> int:
    from source_discovery.corpus_v1_1 import acquire_hsc
    stats = acquire_hsc()
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


def cmd_v11_tomato(args: argparse.Namespace) -> int:
    from source_discovery.corpus_v1_1 import acquire_tomato
    stats = acquire_tomato(args.revision, limit_pairs=args.limit_pairs)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


def cmd_v11_opus(args: argparse.Namespace) -> int:
    from source_discovery.corpus_v1_1 import acquire_opus
    caps = {"zh": args.zh, "ja": args.ja, "ko": args.ko, "ms": args.ms}
    stats = acquire_opus(caps)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


def cmd_v11_jesc(args: argparse.Namespace) -> int:
    from source_discovery.corpus_v1_1 import acquire_jesc
    stats = acquire_jesc(cap=args.cap)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


def cmd_v11_jparacrawl(args: argparse.Namespace) -> int:
    from source_discovery.corpus_v1_1 import acquire_jparacrawl_verah
    stats = acquire_jparacrawl_verah(cap=args.cap)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


def cmd_v11_assemble(_args: argparse.Namespace) -> int:
    from source_discovery.corpus_v1_1 import assemble_corpora
    summary = assemble_corpora()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def cmd_v11_sidecar(_args: argparse.Namespace) -> int:
    from source_discovery.terminology import build_sidecar
    manifest = build_sidecar()
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def cmd_v11_jev(args: argparse.Namespace) -> int:
    from source_discovery.jev_run import run_bounded_jev
    stats = run_bounded_jev(n_total=args.n)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


def cmd_v11_audits(_args: argparse.Namespace) -> int:
    from source_discovery.audits import run_audits
    report = run_audits()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def cmd_v11_tatoeba(args: argparse.Namespace) -> int:
    from source_discovery.audits import ingest_tatoeba_joined
    stats = ingest_tatoeba_joined(args.lang, cap=args.cap)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


def cmd_v11_manifests(_args: argparse.Namespace) -> int:
    import hashlib as _hl
    from source_discovery.corpus_v1_1 import V11
    from source_discovery.hashing import sha256_file as _sha

    def _load(p):
        return json.loads(Path(p).read_text(encoding="utf-8"))

    # Source manifest from staging manifests + registry statuses.
    reg = _load(V11.parent / "v1" / "source_registry_v1.json")
    reg_status = {e["source_id"]: e["status"] for e in reg["sources"]}
    # registry ids differ slightly from staging ids; map explicitly.
    sources = {}
    for sid in ("hsc-wuxia-100k", "tomato-zh2en", "opus-100", "jesc",
                "jparacrawl-verah", "tatoeba-koen", "tatoeba-msen"):
        mp = V11 / "staging" / sid / "manifest.json"
        if mp.exists():
            sources[sid] = _load(mp)
    source_manifest = {
        "manifest_version": "sd-v1.1", "sources": sources,
        "registry_statuses": {k: reg_status.get(k, "n/a") for k in
                              list(sources) + ["jparacrawl-verah-mirror",
                                               "tatoeba-koen"]},
    }
    with open(V11 / "source_manifest.json", "w",
              encoding="utf-8") as f:
        json.dump(source_manifest, f, indent=2, ensure_ascii=False)

    # Corpus + split + quarantine manifests.
    summon = _load(V11 / "corpus_summary.json")
    files = {}
    for rel in ("corpus/training_ready.jsonl",
                "corpus/research_baseline.jsonl",
                "corpus/quarantine.jsonl",
                "corpus/splits/training_ready.train.jsonl",
                "corpus/splits/training_ready.val.jsonl",
                "corpus/splits/training_ready.test.jsonl",
                "corpus/splits/research_baseline.train.jsonl",
                "corpus/splits/research_baseline.val.jsonl",
                "corpus/splits/research_baseline.test.jsonl",
                "terminology/terminology.jsonl"):
        p = V11 / rel
        if p.exists():
            files[rel] = {"bytes": p.stat().st_size,
                          "sha256": _sha(p)}
    # row counts without loading bulk: splits from summary; quarantine +
    # terminology from their manifests.
    quar_n = None
    if (V11 / "jev" / "post_jev_removals.json").exists():
        quar_n = _load(V11 / "jev" / "post_jev_removals.json")["n_removed"]
    term_n = _load(V11 / "terminology" / "terminology_manifest.json")["n_terms"]
    corpus_manifest = {
        "manifest_version": "sd-v1.1", "summary": summon, "files": files,
        "quarantine_rows": quar_n, "terminology_rows": term_n,
    }
    with open(V11 / "corpus_manifest.json", "w", encoding="utf-8") as f:
        json.dump(corpus_manifest, f, indent=2, ensure_ascii=False)

    # Aggregate stats (source-mapped domains/licenses; no bulk scan).
    domain_of = {"hsc-wuxia-100k": "web_novel", "tomato-zh2en": "web_novel",
                 "tatoeba-koen": "general", "tatoeba-msen": "general",
                 "opus-100": "subtitle", "jesc": "subtitle",
                 "jparacrawl-verah": "general"}
    lic_of = {"hsc-wuxia-100k": "ALLOW", "tomato-zh2en": "ALLOW",
              "tatoeba-koen": "ALLOW", "tatoeba-msen": "ALLOW",
              "opus-100": "UNKNOWN", "jesc": "UNKNOWN",
              "jparacrawl-verah": "RESTRICTED"}
    by_source = dict(summon["by_source_training"])
    by_source.update(summon["by_source_baseline"])
    by_language = dict(summon["by_source_lang_training"])
    for k, v in summon["by_source_lang_baseline"].items():
        by_language[k] = by_language.get(k, 0) + v
    by_domain: dict = {}
    by_license: dict = {}
    for sid, n in by_source.items():
        by_domain[domain_of.get(sid, "other")] = \
            by_domain.get(domain_of.get(sid, "other"), 0) + n
        by_license[lic_of.get(sid, "UNKNOWN")] = \
            by_license.get(lic_of.get(sid, "UNKNOWN"), 0) + n
    rejections: dict = {}
    for sid, m in sources.items():
        qf = m.get("quality_filter", {})
        for k, v in qf.items():
            if k not in ("n_input", "kept", "n_kept", "n_rejected") and \
                    isinstance(v, int):
                rejections[k] = rejections.get(k, 0) + v
        rejections["_raw_total"] = rejections.get("_raw_total", 0) + \
            m.get("n_raw_shaped", 0)
        rejections["_kept_total"] = rejections.get("_kept_total", 0) + \
            m.get("n_kept", 0)
    stats_out = {"by_source": by_source, "by_language": by_language,
                 "by_domain": by_domain, "by_license_state": by_license,
                 "rejections": rejections}
    with open(V11 / "stats.json", "w", encoding="utf-8") as f:
        json.dump(stats_out, f, indent=2, ensure_ascii=False)
    print(json.dumps(stats_out, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="source-discovery-v1")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build-registry")
    v = sub.add_parser("verify")
    v.add_argument("--no-http", action="store_true")
    s = sub.add_parser("ingest-smoke")
    s.add_argument("--per-lang", type=int, default=30)
    j = sub.add_parser("jev-smoke")
    j.add_argument("--n-per-band", type=int, default=2)
    sub.add_parser("ai2-probe")
    sub.add_parser("stats")
    sub.add_parser("report")
    h = sub.add_parser("v11-hsc")
    h.set_defaults(func=cmd_v11_hsc)
    t = sub.add_parser("v11-tomato")
    t.add_argument("--revision", required=True)
    t.add_argument("--limit-pairs", type=int, default=None)
    t.set_defaults(func=cmd_v11_tomato)
    o = sub.add_parser("v11-opus")
    o.add_argument("--zh", type=int, default=15000)
    o.add_argument("--ja", type=int, default=15000)
    o.add_argument("--ko", type=int, default=10000)
    o.add_argument("--ms", type=int, default=10000)
    o.set_defaults(func=cmd_v11_opus)
    jc = sub.add_parser("v11-jesc")
    jc.add_argument("--cap", type=int, default=30000)
    jc.set_defaults(func=cmd_v11_jesc)
    jpc = sub.add_parser("v11-jparacrawl")
    jpc.add_argument("--cap", type=int, default=50000)
    jpc.set_defaults(func=cmd_v11_jparacrawl)
    sub.add_parser("v11-assemble").set_defaults(func=cmd_v11_assemble)
    sub.add_parser("v11-sidecar").set_defaults(func=cmd_v11_sidecar)
    j11 = sub.add_parser("v11-jev")
    j11.add_argument("--n", type=int, default=100)
    j11.set_defaults(func=cmd_v11_jev)
    sub.add_parser("v11-audits").set_defaults(func=cmd_v11_audits)
    tb = sub.add_parser("v11-tatoeba")
    tb.add_argument("--lang", required=True, choices=["ko", "ms"])
    tb.add_argument("--cap", type=int, default=20000)
    tb.set_defaults(func=cmd_v11_tatoeba)
    sub.add_parser("v11-manifests").set_defaults(func=cmd_v11_manifests)
    args = ap.parse_args(argv)
    if hasattr(args, "func"):
        return args.func(args)
    if args.cmd == "build-registry":
        return cmd_build_registry(args)
    if args.cmd == "verify":
        return cmd_verify(args)
    if args.cmd == "ingest-smoke":
        return cmd_ingest_smoke(args)
    if args.cmd == "jev-smoke":
        return cmd_jev_smoke(args)
    if args.cmd == "ai2-probe":
        return cmd_ai2_probe(args)
    if args.cmd == "stats":
        return cmd_stats(args)
    if args.cmd == "report":
        return cmd_report(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
