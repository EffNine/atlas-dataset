#!/usr/bin/env python3
"""Phase 2.1 — Human Calibration Execution for Atlas x Jev.

Shadow-only: reads pilot/v0.2 + Phase-1/Phase-2 artifacts; writes ONLY under
experiments/jev-pilot-atlas-v0.1/phase2/. Never modifies Atlas source data,
never fabricates/infers human labels, never treats Jev outputs as ground truth.

Workflow (two independent labelers per record):
  1. build-package  — blinded labeling package (NO Jev signals) for 84 unique
                       records underlying the 96 manifest rows.
  2. <humans label> — labelers fill phase2/human_labels/<record_id>__<labeler>.json
                       per human_label_schema_v1.json + LABELING_INSTRUCTIONS.md.
  3. validate        — schema + manifest conformance; writes labeling_status.json.
  4. agreement       — inter-rater agreement per dimension; writes
                       inter_rater_agreement.json (HOLD with nulls if no labels).
  5. adjudication    — disagreement list; writes adjudication_list.json.
  6. calibrate       — JEV threshold calibration vs human gold; writes
                       threshold_calibration_v2.json (HOLD if no genuine labels).

Usage:
  python phase2_1_labeling.py all | build-package | validate | agreement | adjudication | calibrate
  python phase2_1_labeling.py label --labeler <id> [--limit N] [--record <record_id>]
      # interactive labeling: shows each pending record blinded, records your y/n
      # answers. The human makes every judgment; the script only writes the file.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # repo root
P1 = ROOT / "experiments" / "jev-pilot-atlas-v0.1"
P2 = P1 / "phase2"

SCHEMA_VERSION = "human-label-v1"
CRITERIA_VERSION = "phase2-calibration-v1"
REFERENCE_VERSION = "taxonomy_reference_v1"
LABELER_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LABEL_DIMS = ("correctness", "problematic", "category_correct")
YES_NO = ("yes", "no")

MANIFEST_PATH = P2 / "human_calibration_manifest.json"
SCHEMA_PATH = P2 / "human_label_schema_v1.json"
LABELS_DIR = P2 / "human_labels"
ADJUDICATED_DIR = P2 / "human_labels_adjudicated"
PACKAGE_DIR = P2 / "labeling_package"


# ---------------------------------------------------------------- helpers


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def manifest_index(manifest: dict) -> dict:
    """record_id -> manifest row (first occurrence; duplicates share the id)."""
    idx = {}
    for r in manifest["records"]:
        idx.setdefault(r["record_id"], r)
    return idx


def unique_records(manifest: dict) -> list[dict]:
    """Deduplicated labeling units: 96 rows -> 84 unique records.

    9 record_ids repeat across strata (low_jev/flagged/outliers overlap by
    construction). Each unique record is labeled ONCE per labeler; the strata
    membership of every row is preserved in `strata` for join-back.
    """
    by_id: dict[str, dict] = {}
    for r in manifest["records"]:
        rid = r["record_id"]
        if rid not in by_id:
            by_id[rid] = {
                "record_id": rid,
                "arm": r["arm"],
                "content_sha256": r["content_sha256"],
                "strata": [],
            }
        by_id[rid]["strata"].append(r["stratum"])
        # consistency guard: same id must map to same arm + sha
        assert by_id[rid]["arm"] == r["arm"], f"arm mismatch for {rid}"
        assert by_id[rid]["content_sha256"] == r["content_sha256"], f"sha mismatch for {rid}"
    return [by_id[k] for k in sorted(by_id)]


def load_pilot_by_id() -> dict:
    """record_id -> (arm, record). Read-only."""
    out = {}
    for arm in ("math", "code", "general", "systems"):
        path = ROOT / "pilot" / "v0.2" / arm / "train.jsonl"
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    out.setdefault(rec.get("id"), (arm, rec))
    return out


# ---------------------------------------------------------------- 1. build-package


def build_package(package_dir: Path = PACKAGE_DIR) -> dict:
    """Write the blinded labeling package (no Jev signals anywhere in it)."""
    manifest = load_manifest()
    units = unique_records(manifest)
    pilot = load_pilot_by_id()
    reference = json.loads((P2 / "taxonomy_reference_v1.json").read_text())

    rec_dir = package_dir / "records"
    rec_dir.mkdir(parents=True, exist_ok=True)

    missing = [u["record_id"] for u in units if u["record_id"] not in pilot]
    if missing:
        raise RuntimeError(f"{len(missing)} calibration records not found in pilot/v0.2: {missing[:5]}")

    for u in units:
        arm, rec = pilot[u["record_id"]]
        assert arm == u["arm"], f"arm drift for {u['record_id']}: manifest={u['arm']} pilot={arm}"
        payload = {
            "record_id": u["record_id"],
            "arm": u["arm"],
            # NOTE: strata intentionally omitted here — names like low_jev/flagged
            # would leak Jev's view. Strata mapping lives only in manifest.json
            # (join-back key), which labelers are instructed not to open mid-pass.
            "content_sha256": u["content_sha256"],
            "criteria_version": CRITERIA_VERSION,
            "reference_version": REFERENCE_VERSION,
            "source": rec.get("source"),
            "category_label": rec.get("category"),
            "subcategory_label": rec.get("subcategory"),
            "license": rec.get("license"),
            "messages": rec.get("messages"),
            "labeling_criteria": manifest["labeling_criteria"],
            "note": "BLINDED: no Jev signals, scores, or flags are included by design. Judge from content only.",
        }
        (rec_dir / f"{u['record_id']}.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")

    template = {
        "schema_version": SCHEMA_VERSION,
        "record_id": "<record_id>",
        "arm": "<math|code|general|systems>",
        "content_sha256": "<copy from labeling_package manifest — do not recompute>",
        "labeler_id": "<your-labeler-id>",
        "labeled_at": "<ISO-8601 timestamp, e.g. 2026-09-18T10:00:00+00:00>",
        "criteria_version": CRITERIA_VERSION,
        "reference_version": REFERENCE_VERSION,
        "blinded_to_jev": True,
        "labels": {"correctness": "<yes|no>", "problematic": "<yes|no>", "category_correct": "<yes|no>"},
        "notes": "<optional rationale>",
    }
    (package_dir / "label_template.json").write_text(json.dumps(template, indent=1) + "\n")

    pkg_manifest = {
        "version": "phase2.1-labeling-package-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_manifest_rows": manifest["n_records"],
        "n_unique_records": len(units),
        "note": "96 manifest rows reference 84 unique records (9 ids repeat across low_jev/flagged/outliers strata). Label each unique record ONCE per labeler.",
        "criteria_version": CRITERIA_VERSION,
        "reference_version": REFERENCE_VERSION,
        "blinded": True,
        "records": [
            {
                "record_id": u["record_id"],
                "arm": u["arm"],
                "strata": sorted(set(u["strata"])),
                "content_sha256": u["content_sha256"],
                "package_file": f"records/{u['record_id']}.json",
            }
            for u in units
        ],
    }
    (package_dir / "manifest.json").write_text(json.dumps(pkg_manifest, indent=1) + "\n")
    return pkg_manifest


# ---------------------------------------------------------------- 2. validate


def _parse_time(s: str) -> bool:
    try:
        datetime.fromisoformat(s)
        return True
    except (ValueError, TypeError):
        return False


def validate_label(obj: dict, idx: dict, filename: str) -> list[str]:
    """Return a list of violations (empty = valid). Never raises on bad input."""
    errs: list[str] = []
    if not isinstance(obj, dict):
        return [f"{filename}: top-level JSON must be an object"]
    for f in ("schema_version", "record_id", "arm", "content_sha256", "labeler_id",
              "labeled_at", "criteria_version", "reference_version", "blinded_to_jev", "labels"):
        if f not in obj:
            errs.append(f"{filename}: missing required field '{f}'")
    if errs:
        return errs
    if obj.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"{filename}: schema_version must be '{SCHEMA_VERSION}'")
    if obj.get("criteria_version") != CRITERIA_VERSION:
        errs.append(f"{filename}: criteria_version must be '{CRITERIA_VERSION}'")
    if obj.get("reference_version") != REFERENCE_VERSION:
        errs.append(f"{filename}: reference_version must be '{REFERENCE_VERSION}'")
    if obj.get("blinded_to_jev") is not True:
        errs.append(f"{filename}: blinded_to_jev must be true")
    rid = obj.get("record_id")
    if rid not in idx:
        errs.append(f"{filename}: unknown record_id '{rid}' (not in calibration manifest)")
        return errs
    row = idx[rid]
    if obj.get("arm") != row["arm"]:
        errs.append(f"{filename}: arm '{obj.get('arm')}' != manifest arm '{row['arm']}'")
    if obj.get("content_sha256") != row["content_sha256"]:
        errs.append(f"{filename}: content_sha256 does not match manifest (wrong content judged?)")
    lid = obj.get("labeler_id", "")
    if not isinstance(lid, str) or not LABELER_RE.match(lid):
        errs.append(f"{filename}: labeler_id must match ^[A-Za-z0-9_-]{{1,64}}$")
    else:
        expected_suffix = f"__{lid}.json"
        if not filename.endswith(expected_suffix):
            errs.append(f"{filename}: filename must end with '{expected_suffix}'")
    if not isinstance(obj.get("labeled_at"), str) or not _parse_time(obj["labeled_at"]):
        errs.append(f"{filename}: labeled_at must be an ISO-8601 timestamp string")
    labels = obj.get("labels")
    if not isinstance(labels, dict):
        errs.append(f"{filename}: labels must be an object")
    else:
        for dim in LABEL_DIMS:
            if dim not in labels:
                errs.append(f"{filename}: labels missing dimension '{dim}'")
            elif labels[dim] not in YES_NO:
                errs.append(f"{filename}: labels.{dim} must be 'yes' or 'no', got {labels[dim]!r}")
        for dim in labels:
            if dim not in LABEL_DIMS:
                errs.append(f"{filename}: unknown label dimension '{dim}'")
    # Jev signals must never leak into a human label file
    for leak in ("jev_signals", "jev_scores", "quality", "correct", "problematic_score", "flags", "consistent_category"):
        if leak in obj:
            errs.append(f"{filename}: forbidden field '{leak}' — Jev outputs are not human ground truth")
    return errs


def validate_labels(labels_dir: Path = LABELS_DIR, manifest: dict | None = None) -> dict:
    manifest = manifest or load_manifest()
    idx = manifest_index(manifest)
    files = sorted(labels_dir.glob("*.json")) if labels_dir.is_dir() else []
    per_record: dict[str, dict[str, dict]] = defaultdict(dict)  # rid -> labeler -> obj
    violations: list[str] = []
    n_valid = 0
    for path in files:
        try:
            obj = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            violations.append(f"{path.name}: invalid JSON ({e})")
            continue
        errs = validate_label(obj, idx, path.name)
        if errs:
            violations.extend(errs)
            continue
        rid, lid = obj["record_id"], obj["labeler_id"]
        if lid in per_record[rid]:
            violations.append(f"{path.name}: duplicate label from labeler '{lid}' for record '{rid}'")
            continue
        per_record[rid][lid] = obj
        n_valid += 1

    units = unique_records(manifest)
    fully = sum(1 for u in units if len(per_record.get(u["record_id"], {})) >= 2)
    partial = sum(1 for u in units if len(per_record.get(u["record_id"], {})) == 1)
    unlabeled = sum(1 for u in units if not per_record.get(u["record_id"]))
    labelers = sorted({lid for m in per_record.values() for lid in m})
    status = {
        "version": "phase2.1-labeling-status-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_unique_records": len(units),
        "n_manifest_rows": manifest["n_records"],
        "n_label_files_valid": n_valid,
        "n_label_files_total": len(files),
        "n_records_two_labelers": fully,
        "n_records_one_labeler": partial,
        "n_records_unlabeled": unlabeled,
        "labeler_ids_seen": labelers,
        "meets_two_labeler_requirement": fully == len(units) and not violations,
        "violations": violations,
        "per_record": {
            u["record_id"]: sorted(per_record.get(u["record_id"], {}).keys()) for u in units
        },
    }
    return status


# ---------------------------------------------------------------- 3. agreement


def cohens_kappa(a_yes: int, a_no: int, b_yes: int, b_no: int, agree: int, n: int) -> float | None:
    """Binary Cohen's kappa from margins. None when undefined (n==0 or pe==1)."""
    if n == 0:
        return None
    po = agree / n
    pe = ((a_yes / n) * (b_yes / n)) + ((a_no / n) * (b_no / n))
    if pe == 1.0:
        return None
    return round((po - pe) / (1 - pe), 4)


def compute_agreement(status: dict, labels_dir: Path = LABELS_DIR) -> dict:
    done = [rid for rid, lids in status["per_record"].items() if len(lids) >= 2]
    out: dict = {
        "version": "phase2.1-agreement-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_records_two_labelers": len(done),
        "status": "COMPUTED" if done else "HOLD_NO_PAIRED_LABELS",
    }
    if not done:
        out["note"] = ("No record has two independent labels yet. Agreement metrics are null — "
                       "never fabricate. Complete human labeling first.")
        out["dimensions"] = {
            dim: {"n_paired": 0, "n_agree": 0, "raw_agreement": None, "cohens_kappa": None}
            for dim in LABEL_DIMS
        }
        out["full_agreement"] = {"n_paired": 0, "n_full_agree": 0, "rate": None}
        return out
    # deterministic labeler order per record: sorted ids -> (A, B)
    dim_stats: dict[str, dict] = {}
    full_agree = 0
    for dim in LABEL_DIMS:
        a_yes = a_no = b_yes = b_no = agree = 0
        for rid in done:
            lids = sorted(status["per_record"][rid])[:2]
            objs = [json.loads((labels_dir / f"{rid}__{lid}.json").read_text()) for lid in lids]
            va, vb = objs[0]["labels"][dim], objs[1]["labels"][dim]
            a_yes += va == "yes"
            a_no += va == "no"
            b_yes += vb == "yes"
            b_no += vb == "no"
            agree += va == vb
        n = len(done)
        dim_stats[dim] = {
            "n_paired": n,
            "n_agree": agree,
            "raw_agreement": round(agree / n, 4),
            "cohens_kappa": cohens_kappa(a_yes, a_no, b_yes, b_no, agree, n),
            "margins": {"A_yes": a_yes, "A_no": a_no, "B_yes": b_yes, "B_no": b_no},
        }
    for rid in done:
        lids = sorted(status["per_record"][rid])[:2]
        objs = [json.loads((labels_dir / f"{rid}__{lid}.json").read_text()) for lid in lids]
        if all(objs[0]["labels"][d] == objs[1]["labels"][d] for d in LABEL_DIMS):
            full_agree += 1
    out["dimensions"] = dim_stats
    out["full_agreement"] = {
        "n_paired": len(done),
        "n_full_agree": full_agree,
        "rate": round(full_agree / len(done), 4),
    }
    out["note"] = ("Kappa is undefined (null) when a dimension has zero variance. "
                   "Low agreement or small n means thresholds cannot be trusted — see calibrate step.")
    return out


# ---------------------------------------------------------------- 4. adjudication


def build_adjudication_list(status: dict, labels_dir: Path = LABELS_DIR) -> dict:
    items = []
    for rid, lids in sorted(status["per_record"].items()):
        if len(lids) < 2:
            continue
        lids2 = sorted(lids)[:2]
        objs = [json.loads((labels_dir / f"{rid}__{lid}.json").read_text()) for lid in lids2]
        disagreed = [d for d in LABEL_DIMS if objs[0]["labels"][d] != objs[1]["labels"][d]]
        if disagreed:
            items.append({
                "record_id": rid,
                "labelers": lids2,
                "disagreed_dimensions": disagreed,
                "votes": {d: {lids2[0]: objs[0]["labels"][d], lids2[1]: objs[1]["labels"][d]} for d in disagreed},
                "resolution": "pending_third_labeler",
            })
    return {
        "version": "phase2.1-adjudication-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_disagreements": len(items),
        "n_paired_records": sum(1 for lids in status["per_record"].values() if len(lids) >= 2),
        "status": "COMPUTED" if status["n_records_two_labelers"] else "HOLD_NO_PAIRED_LABELS",
        "items": items,
        "adjudication_protocol": ("A third labeler (different id from both originals) resolves each item; "
                                  "the resolved gold is written to human_labels_adjudicated/<record_id>.json. "
                                  "Raw independent labels are NEVER modified."),
    }


# ---------------------------------------------------------------- 5. calibrate


THRESHOLDS = [0.1, 0.2, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def load_gold(status: dict, labels_dir: Path = LABELS_DIR,
              adjudicated_dir: Path = ADJUDICATED_DIR) -> tuple[dict, dict]:
    """record_id -> {dim: 'yes'/'no'} gold + provenance per record.

    Gold rule: agreed dimensions use the agreed value; disagreed dimensions
    require an adjudicated file; records without two labelers are excluded.
    """
    gold, prov = {}, {}
    for rid, lids in status["per_record"].items():
        if len(lids) < 2:
            continue
        lids2 = sorted(lids)[:2]
        objs = [json.loads((labels_dir / f"{rid}__{lid}.json").read_text()) for lid in lids2]
        adj_path = adjudicated_dir / f"{rid}.json"
        adj = json.loads(adj_path.read_text())["labels"] if adj_path.exists() else {}
        g, p = {}, {}
        for dim in LABEL_DIMS:
            if objs[0]["labels"][dim] == objs[1]["labels"][dim]:
                g[dim] = objs[0]["labels"][dim]
                p[dim] = f"agreement:{lids2[0]}+{lids2[1]}"
            elif dim in adj and adj[dim] in YES_NO:
                g[dim] = adj[dim]
                p[dim] = "adjudicated"
            else:
                p[dim] = "disputed_unadjudicated_excluded"
        gold[rid] = g
        prov[rid] = p
    return gold, prov


def calibrate(status: dict, manifest: dict, labels_dir: Path = LABELS_DIR,
              adjudicated_dir: Path = ADJUDICATED_DIR) -> dict:
    gold, prov = load_gold(status, labels_dir, adjudicated_dir)
    idx = manifest_index(manifest)
    # human 'correctness=yes' means NOT incorrect; 'problematic=yes' is the positive class
    dims_cfg = {
        "correct": {"human_dim": "correctness", "human_positive": "no",
                    "jev": lambda s: s["correct"], "invert": True,
                    "note": "positive = human says INCORRECT; JEV predicts positive when jev_correct < (1-t)"},
        "problematic": {"human_dim": "problematic", "human_positive": "yes",
                        "jev": lambda s: s["problematic"], "invert": False,
                        "note": "positive = human says PROBLEMATIC; JEV predicts positive when jev_problematic >= t"},
    }
    if not gold:
        return {
            "version": "phase2.1-threshold-v2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "INCONCLUSIVE_NO_HUMAN_LABELS",
            "n_gold_records": 0,
            "note": ("No adjudicated/agreed human gold exists. Precision/recall/FPR/FNR and "
                     "confusion matrices are null — never fabricate. Complete labeling first."),
            "dimensions": {},
        }
    dimensions = []
    for name, cfg in dims_cfg.items():
        usable = [(rid, g[cfg["human_dim"]]) for rid, g in gold.items() if cfg["human_dim"] in g]
        sweep = []
        for t in THRESHOLDS:
            tp = fp = tn = fn = 0
            for rid, hv in usable:
                js = idx[rid]["jev_signals"]
                pred = (js[name] < (1 - t)) if cfg["invert"] else (js[name] >= t)
                actual = (hv == cfg["human_positive"])
                if pred and actual:
                    tp += 1
                elif pred and not actual:
                    fp += 1
                elif not pred and actual:
                    fn += 1
                else:
                    tn += 1
            sweep.append({
                "threshold": t,
                "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
                "precision": round(tp / (tp + fp), 4) if tp + fp else None,
                "recall": round(tp / (tp + fn), 4) if tp + fn else None,
                "fpr": round(fp / (fp + tn), 4) if fp + tn else None,
                "fnr": round(fn / (fn + tp), 4) if fn + tp else None,
            })
        # score distributions: human-positive vs human-negative
        pos = [idx[rid]["jev_signals"][name] for rid, hv in usable if hv == cfg["human_positive"]]
        neg = [idx[rid]["jev_signals"][name] for rid, hv in usable if hv != cfg["human_positive"]]
        def stats(v):
            if not v:
                return {"n": 0, "mean": None, "min": None, "max": None}
            return {"n": len(v), "mean": round(sum(v) / len(v), 4),
                    "min": round(min(v), 4), "max": round(max(v), 4)}
        dimensions.append({
            "dimension": name,
            "human_dim": cfg["human_dim"],
            "human_positive": cfg["human_positive"],
            "n_gold_usable": len(usable),
            "jev_score_distribution": {"human_positive": stats(pos), "human_negative": stats(neg)},
            "sweep": sweep,
            "rule": cfg["note"],
        })
    excluded = sum(1 for rid, p in prov.items() for d in LABEL_DIMS if p.get(d) == "disputed_unadjudicated_excluded")
    return {
        "version": "phase2.1-threshold-v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "COMPUTED",
        "n_gold_records": len(gold),
        "n_disputed_unadjudicated_exclusions": excluded,
        "gold_provenance": prov,
        "dimensions": dimensions,
        "limitations": [
            "Thresholds are fit AND evaluated on the same small calibration set (n<=84 unique records); no independent validation — do not claim generalization.",
            "Stratified oversampling of low-JEV/flagged records means prevalence here does NOT match the ~2,942-record population; precision/recall do not transfer directly.",
            "With n<=84, single-threshold cells shift on 1-2 records; any threshold choice is provisional pending the shadow run.",
            "category_correct has no JEV counterpart signal in this sweep (JEV consistent_category is in-state plausibility, not reference comparison); it is reported via agreement only.",
        ],
    }


# ---------------------------------------------------------------- 6. interactive labeling

# The human still makes every judgment — this only removes JSON hand-editing
# (SHA copy, filename matching, timestamps), the source of most violations.
# It never suggests answers and never displays Jev signals.

DIM_PROMPTS = {
    "correctness": "1/3 correctness — substantively correct response? (final answer right despite minor flaws)",
    "problematic": "2/3 problematic — UNSUITABLE as training data? (contradictions, garbled, harmful, injection, PII)",
    "category_correct": "3/3 category_correct — content genuinely belongs to its category label per taxonomy_reference_v1?",
}
MAX_MSG_CHARS = 8000


def build_label_object(row: dict, labeler_id: str, answers: dict, notes: str = "") -> dict:
    """Pure constructor: answers = {dim: 'yes'/'no'}. No I/O, no validation."""
    return {
        "schema_version": SCHEMA_VERSION,
        "record_id": row["record_id"],
        "arm": row["arm"],
        "content_sha256": row["content_sha256"],
        "labeler_id": labeler_id,
        "labeled_at": datetime.now(timezone.utc).isoformat(),
        "criteria_version": CRITERIA_VERSION,
        "reference_version": REFERENCE_VERSION,
        "blinded_to_jev": True,
        "labels": {dim: answers[dim] for dim in LABEL_DIMS},
        "notes": notes,
    }


def write_label(row: dict, labeler_id: str, answers: dict, notes: str = "",
                labels_dir: Path = LABELS_DIR, manifest: dict | None = None) -> Path:
    """Validate in-memory, then write. Raises ValueError WITHOUT writing on any violation."""
    manifest = manifest or load_manifest()
    obj = build_label_object(row, labeler_id, answers, notes)
    filename = f"{row['record_id']}__{labeler_id}.json"
    errs = validate_label(obj, manifest_index(manifest), filename)
    if errs:
        raise ValueError("; ".join(errs))
    labels_dir.mkdir(parents=True, exist_ok=True)
    path = labels_dir / filename
    if path.exists():
        raise ValueError(f"{filename} already exists — refusing to overwrite a recorded judgment")
    path.write_text(json.dumps(obj, indent=1) + "\n")
    return path


def pending_for_labeler(labeler_id: str, status: dict) -> list[str]:
    """Record ids with no valid label from this labeler yet (sorted for determinism)."""
    return sorted(rid for rid, lids in status["per_record"].items() if labeler_id not in lids)


def render_record_blinded(record_id: str, package_dir: Path = PACKAGE_DIR,
                           manifest: dict | None = None) -> str:
    """Terminal rendering from the BLINDED package file. Never touches Jev outputs."""
    manifest = manifest or load_manifest()
    pkg_file = package_dir / "records" / f"{record_id}.json"
    if not pkg_file.exists():
        # fall back to building a blinded view straight from pilot (read-only)
        arm, rec = load_pilot_by_id()[record_id]
        payload = {"record_id": record_id, "arm": arm,
                   "source": rec.get("source"), "category_label": rec.get("category"),
                   "subcategory_label": rec.get("subcategory"), "messages": rec.get("messages"),
                   "labeling_criteria": manifest["labeling_criteria"]}
    else:
        payload = json.loads(pkg_file.read_text())
    lines = [f"=== {payload['record_id']}  (arm={payload['arm']}) ==="]
    src = payload.get("source") or {}
    lines.append(f"source: {src.get('source_id') or src.get('name')} | "
                 f"category: {payload.get('category_label')}/{payload.get('subcategory_label')}")
    for m in payload.get("messages", []):
        body = m.get("content", "")
        if len(body) > MAX_MSG_CHARS:
            body = body[:MAX_MSG_CHARS] + f"\n[... truncated at {MAX_MSG_CHARS} chars — see labeling_package/records/{record_id}.json for full text]"
        lines.append(f"--- {m.get('role')} ---\n{body}")
    lines.append("--- criteria ---")
    for dim in LABEL_DIMS:
        lines.append(f"{dim}: {manifest['labeling_criteria'][dim]}")
    return "\n".join(lines)


def cmd_label(labeler_id: str, limit: int | None = None, only_record: str | None = None,
              labels_dir: Path = LABELS_DIR) -> dict:
    """Interactive labeling loop. Every judgment comes from the human at the keyboard."""
    if not LABELER_RE.match(labeler_id):
        raise ValueError(f"bad labeler_id {labeler_id!r} (must match ^[A-Za-z0-9_-]{{1,64}}$)")
    manifest = load_manifest()
    idx = manifest_index(manifest)
    status = validate_labels(labels_dir=labels_dir, manifest=manifest)
    queue = [only_record] if only_record else pending_for_labeler(labeler_id, status)
    if only_record and only_record not in idx:
        raise ValueError(f"unknown record_id {only_record!r}")
    if only_record and labeler_id in status["per_record"].get(only_record, []):
        raise ValueError(f"{only_record} already labeled by {labeler_id} — refusing to overwrite")
    done, skipped = 0, 0
    print(f"Labeler '{labeler_id}': {len(queue)} record(s) pending. Answer y/n per dimension; 's' skips, 'q' quits.")
    print("BLINDING: Jev signals are never shown. Do not open jev_results.jsonl / the manifest sheet mid-pass.")
    for rid in queue:
        if limit is not None and done >= limit:
            break
        print("\n" + render_record_blinded(rid, manifest=manifest))
        answers = {}
        aborted = False
        for dim in LABEL_DIMS:
            while True:
                raw = input(f"{DIM_PROMPTS[dim]} [y/n/s=skip record/q=quit]: ").strip().lower()
                if raw in ("y", "yes"):
                    answers[dim] = "yes"
                    break
                if raw in ("n", "no"):
                    answers[dim] = "no"
                    break
                if raw == "s":
                    aborted = True
                    break
                if raw == "q":
                    print(f"stopped: wrote {done}, skipped {skipped}. Resume anytime — same command.")
                    return {"written": done, "skipped": skipped}
                print("  please answer y / n / s / q")
            if aborted:
                break
        if aborted or len(answers) != 3:
            skipped += 1
            continue
        notes = input("notes (optional, Enter to skip): ").strip()[:2000]
        confirm = input(f"record {answers}? [Enter=save / s=skip]: ").strip().lower()
        if confirm not in ("", "y", "yes"):
            skipped += 1
            continue
        path = write_label(idx[rid], labeler_id, answers, notes, labels_dir, manifest)
        done += 1
        print(f"  saved {path.name} ({done} this session)")
    print(f"session done: wrote {done}, skipped {skipped}. Run `validate` to check progress.")
    return {"written": done, "skipped": skipped}


# ---------------------------------------------------------------- main


def cmd_all():
    pkg = build_package()
    print(f"package: {pkg['n_unique_records']} unique records ({pkg['n_manifest_rows']} rows) -> {PACKAGE_DIR}")
    manifest = load_manifest()
    status = validate_labels(manifest=manifest)
    (P2 / "labeling_status.json").write_text(json.dumps(status, indent=1) + "\n")
    print(f"validate: {status['n_records_two_labelers']}/{status['n_unique_records']} with two labelers; "
          f"{len(status['violations'])} violations")
    agr = compute_agreement(status)
    (P2 / "inter_rater_agreement.json").write_text(json.dumps(agr, indent=1) + "\n")
    print(f"agreement: {agr['status']}")
    adj = build_adjudication_list(status)
    (P2 / "adjudication_list.json").write_text(json.dumps(adj, indent=1) + "\n")
    print(f"adjudication: {adj['n_disagreements']} disagreements")
    cal = calibrate(status, manifest)
    (P2 / "threshold_calibration_v2.json").write_text(json.dumps(cal, indent=1) + "\n")
    print(f"calibrate: {cal['status']}")
    # provenance: confirm Atlas source untouched (read-only re-hash)
    src = json.loads((P2 / "source_file_sha256.json").read_text())
    for relpath, recorded in src["files"].items():
        h = hashlib.sha256()
        with open(ROOT / relpath, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        assert h.hexdigest() == recorded, f"SOURCE MODIFIED: {relpath}"
    print("source integrity: pilot/v0.2 byte-for-byte unchanged")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    manifest = load_manifest()
    if cmd == "all":
        cmd_all()
    elif cmd == "build-package":
        pkg = build_package()
        print(f"package: {pkg['n_unique_records']} unique records -> {PACKAGE_DIR}")
    elif cmd == "validate":
        status = validate_labels(manifest=manifest)
        (P2 / "labeling_status.json").write_text(json.dumps(status, indent=1) + "\n")
        print(json.dumps({k: status[k] for k in ("n_unique_records", "n_records_two_labelers",
              "n_records_one_labeler", "n_records_unlabeled", "labeler_ids_seen",
              "meets_two_labeler_requirement")}, indent=1))
        for v in status["violations"]:
            print("VIOLATION:", v)
    elif cmd == "agreement":
        status = validate_labels(manifest=manifest)
        agr = compute_agreement(status)
        (P2 / "inter_rater_agreement.json").write_text(json.dumps(agr, indent=1) + "\n")
        print(agr["status"])
    elif cmd == "adjudication":
        status = validate_labels(manifest=manifest)
        adj = build_adjudication_list(status)
        (P2 / "adjudication_list.json").write_text(json.dumps(adj, indent=1) + "\n")
        print(f"disagreements: {adj['n_disagreements']}")
    elif cmd == "calibrate":
        status = validate_labels(manifest=manifest)
        cal = calibrate(status, manifest)
        (P2 / "threshold_calibration_v2.json").write_text(json.dumps(cal, indent=1) + "\n")
        print(cal["status"])
    elif cmd == "label":
        args = sys.argv[2:]
        try:
            labeler_id = args[args.index("--labeler") + 1]
        except (ValueError, IndexError):
            print("usage: phase2_1_labeling.py label --labeler <id> [--limit N] [--record <record_id>]")
            sys.exit(2)
        limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
        only = args[args.index("--record") + 1] if "--record" in args else None
        cmd_label(labeler_id, limit=limit, only_record=only)
    else:
        print(f"unknown command {cmd}; use all|build-package|validate|agreement|adjudication|calibrate|label")
