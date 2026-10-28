"""Step T1 — Verify the v1.1 training-ready corpus WITHOUT modifying it.

Read-only checks against Atlas Source Discovery v1.1 artifacts:
  1. sha256 of the three training_ready split files == corpus_manifest.json
     (proves we train on exactly the finalized manifests).
  2. zh-only ALLOW composition per split, by source (provenance preserved).
  3. JEV tombstone overlay located per split; test split must contain ZERO
     tombstoned ids (test immutability); train/val hits are excluded downstream.
  4. Zero content_sha256 overlap train-vs-test and train-vs-val on zh rows
     (leakage check on the exact rows we will train/evaluate on).
  5. Terminology sidecar shape check (term rows, NOT sentence pairs).

Writes ONLY to the v0.2 data dir: data/dataset_manifest.json.
Never writes to Atlas. Never deletes anything.

Usage:
    PYTHONPATH=src .venv/bin/python -m tai.verify_corpus \
        --sdmani <atlas v1.1 dir> --out data/dataset_manifest.json
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

SPLITS = ("training_ready.train", "training_ready.val", "training_ready.test")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdmani", required=True,
                    help="Atlas v1.1 dir (metadata/source_discovery/v1.1)")
    ap.add_argument("--out", default="data/dataset_manifest.json")
    args = ap.parse_args()

    sd = Path(args.sdmani)
    corpus_manifest = json.loads((sd / "corpus_manifest.json").read_text())
    jev_doc = json.loads((sd / "jev/post_jev_removals.json").read_text())
    jev_ids = {r["record_id"] for r in jev_doc.get("removed", [])}
    print(f"JEV tombstones: {len(jev_ids)}")

    manifest = {
        "scope": "zh->en ONLY (source_lang==zh, license ALLOW, JEV tombstones excluded)",
        "atlas_manifest_version": corpus_manifest.get("manifest_version"),
        "atlas_files_verified": {},
        "per_split": {},
        "jev": {"n_tombstones": len(jev_ids), "hits_per_split": {}},
        "leakage": {},
        "terminology_sidecar": {},
    }

    # 1. manifest integrity (read-only)
    for split in SPLITS:
        rel = f"corpus/splits/{split}.jsonl"
        actual = sha256_file(sd / rel)
        expected = corpus_manifest["files"][rel]["sha256"]
        ok = actual == expected
        manifest["atlas_files_verified"][rel] = {"sha256": actual, "match": ok}
        print(f"{rel}: sha256 match={ok}")
        assert ok, f"MANIFEST MISMATCH on {rel}: refusing to train on drifted data"

    # 2-3. composition + JEV location per split
    zh_hashes: dict[str, set[str]] = {}
    for split in SPLITS:
        n_total = 0
        n_zh = 0
        by_src: dict = collections.Counter()
        by_lic: dict = collections.Counter()
        non_zh_lic: dict = collections.Counter()
        jev_hits: list[str] = []
        hashes: set[str] = set()
        with open(sd / f"corpus/splits/{split}.jsonl", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                n_total += 1
                by_lic[rec.get("license_status")] += 1
                if rec.get("source_lang") != "zh":
                    non_zh_lic[rec.get("source_id")] += 1
                    continue
                n_zh += 1
                by_src[rec.get("source_id")] += 1
                hashes.add(rec["content_sha256"])
                if rec.get("id") in jev_ids:
                    jev_hits.append(rec["id"])
                # zh rows must all be ALLOW (training-ready corpus property)
                assert rec.get("license_status") == "ALLOW", \
                    f"non-ALLOW zh row in {split}: {rec.get('id')}"
        zh_hashes[split] = hashes
        manifest["per_split"][split] = {
            "n_total": n_total,
            "n_zh_allow": n_zh,
            "by_source_zh": dict(by_src),
            "license_all_rows": dict(by_lic),
            "non_zh_by_source": dict(non_zh_lic),
            "n_zh_hashes": len(hashes),
        }
        manifest["jev"]["hits_per_split"][split] = len(jev_hits)
        print(f"{split}: total={n_total} zh_ALLOW={n_zh} src={dict(by_src)} jev_hits={len(jev_hits)}")

    # test set must be untouched by the JEV overlay (immutability)
    assert manifest["jev"]["hits_per_split"]["training_ready.test"] == 0, \
        "JEV tombstone inside TEST split: test set would change — aborting"
    found = sum(manifest["jev"]["hits_per_split"].values())
    assert found == len(jev_ids), \
        f"only {found}/{len(jev_ids)} tombstones located — aborting"

    # 4. leakage on the exact zh rows used (post-overlay membership is a
    # subset, so hash-disjointness on the full zh sets implies it post-overlay)
    for a, b in (("training_ready.train", "training_ready.test"),
                 ("training_ready.train", "training_ready.val"),
                 ("training_ready.val", "training_ready.test")):
        overlap = len(zh_hashes[a] & zh_hashes[b])
        manifest["leakage"][f"{a}__vs__{b}"] = overlap
        print(f"leakage {a} vs {b}: {overlap}")
        assert overlap == 0, f"TRAIN/TEST LEAKAGE {overlap} — aborting"

    # 5. terminology sidecar is term rows, never sentence pairs
    term_path = sd / "terminology/terminology.jsonl"
    n_term = 0
    zh_terms = 0
    with open(term_path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            assert "source_term" in rec and "target_term" in rec, "unexpected term schema"
            assert "source" not in rec and "target" not in rec, "sentence-shaped term row!"
            n_term += 1
            if rec.get("source_lang") == "zh":
                zh_terms += 1
    manifest["terminology_sidecar"] = {
        "rows": n_term, "zh_rows": zh_terms,
        "use_in_v02": "EVAL-ONLY term-coverage diagnostic (never sentence-pair training data)",
    }
    print(f"terminology: {n_term} term rows ({zh_terms} zh), sentence-pair use: FORBIDDEN")

    # final usable counts (zh ALLOW minus JEV tombstones; test unaffected)
    for split in SPLITS:
        usable = (manifest["per_split"][split]["n_zh_allow"]
                  - manifest["jev"]["hits_per_split"][split])
        manifest["per_split"][split]["n_usable_zh"] = usable
    tr = manifest["per_split"]["training_ready.train"]["n_usable_zh"]
    va = manifest["per_split"]["training_ready.val"]["n_usable_zh"]
    te = manifest["per_split"]["training_ready.test"]["n_usable_zh"]
    print(f"USABLE zh rows (post-JEV): train={tr} val={va} test={te}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print("wrote", out)


if __name__ == "__main__":
    main()
