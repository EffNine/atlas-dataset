#!/usr/bin/env python3
"""Phase 2.2 — Targeted JEV Calibration Investigation for Atlas x Jev.

Question: is the zero-positive Phase-2.1 gold caused by (A) JEV over-flagging
or (B) the human protocol missing genuine defects?

Shadow-only: reads pilot/v0.2 + Phase-1 Jev results + Phase-2 manifest; writes
ONLY under experiments/jev-pilot-atlas-v0.1/phase2.2/. Never modifies Atlas
source data, never fabricates reviews, never treats Jev outputs as ground truth,
never auto-resolves disagreements.

Design (blinding hardened from Phase-2.1 lessons):
  - Reviewer-facing batch IDs (P22-XXX) are opaque. The record_id mapping lives
    ONLY in sealed files reviewers must not open mid-pass.
  - Blinded record files contain NO JEV signals, NO strata names, NO arm, NO
    prior human labels, NO thresholds.
  - Expanded defect taxonomy (8 dims) + MANDATORY evidence for every finding.

Usage:
  python phase2_2_review.py all | select | build-package | validate | agreement | adjudication | error-analysis | assess
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # repo root
P1 = ROOT / "experiments" / "jev-pilot-atlas-v0.1"
P2 = P1 / "phase2"
P22 = P1 / "phase2.2"

SCHEMA_VERSION = "human-review-v2"
CRITERIA_VERSION = "phase2.2-defects-v1"
REFERENCE_VERSION = "taxonomy_reference_v1"
REVIEWER_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
BATCH_RE = re.compile(r"^P22-[0-9]{3}$")

DIMS = ("correctness", "problematic", "category_correct", "truncation_incomplete",
        "factual_technical_error", "instruction_violation", "malformed_output",
        "other_defect")
# verdict value that constitutes a "finding" per dimension
FINDING_VALUE = {"correctness": "no", "problematic": "yes", "category_correct": "no",
                 "truncation_incomplete": "yes", "factual_technical_error": "yes",
                 "instruction_violation": "yes", "malformed_output": "yes",
                 "other_defect": "yes"}
# dimensions that count toward "human defect" for the error matrix
# (category_correct is taxonomy placement, reported separately — not a content defect)
DEFECT_DIMS = ("correctness", "problematic", "truncation_incomplete",
               "factual_technical_error", "instruction_violation",
               "malformed_output", "other_defect")
TOP_LEVEL_KEYS = {"schema_version", "batch_id", "reviewer_id", "reviewed_at",
                  "criteria_version", "reference_version", "blinded_to_jev",
                  "blinded_to_prior_labels", "labels", "evidence", "notes"}
EVIDENCE_MIN_CHARS = 10

JEV_RESULTS = P1 / "jev_results.jsonl"
P2_MANIFEST = P2 / "human_calibration_manifest.json"
REVIEWS_DIR = P22 / "reviews"
ADJUDICATED_DIR = P22 / "reviews_adjudicated"
PACKAGE_DIR = P22 / "review_package"

CANDIDATE_REASONS = [
    "jev_signal_miscalibrated_for_this_defect_type",
    "human_missed_genuine_defect",
    "record_ambiguous_needs_third_review",
    "defect_present_but_below_training_harm_threshold",
    "category_or_arm_filing_issue_not_content_defect",
    "truncation_artifact_of_view_not_source",
]


# ---------------------------------------------------------------- helpers


def jev_flags(r: dict) -> list:
    """Same flag rule as Phase 2 (phase2_prep.flags). Definitional, not learned."""
    f = []
    if r["answers"]["problematic"]["noul"] >= 0.5:
        f.append("problematic")
    if r["answers"]["correct"]["noul"] < 0.35:
        f.append("unlikely_correct")
    if r["answers"]["quality"]["score"] <= 1.0:
        f.append("low_quality")
    return f


def load_jev() -> list:
    return [json.loads(l) for l in open(JEV_RESULTS) if l.strip()]


def load_in84() -> set:
    return {r["record_id"] for r in json.loads(P2_MANIFEST.read_text())["records"]}


def load_pilot_by_id() -> dict:
    out = {}
    for arm in ("math", "code", "general", "systems"):
        with open(ROOT / "pilot" / "v0.2" / arm / "train.jsonl") as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    out.setdefault(rec.get("id"), (arm, rec))
    return out


def hypothesize(r: dict) -> str:
    """Sealed-only defect hypothesis from JEV signal pattern. Never shown to reviewers."""
    p, c, q = (r["answers"]["problematic"]["noul"], r["answers"]["correct"]["noul"],
               r["answers"]["quality"]["score"])
    if p >= 0.7:
        return "suspected-garbled/unsafe"
    if c < 0.25:
        return "suspected-wrong-answer"
    if q <= 1.0:
        return "suspected-truncation/incomplete"
    if c < 0.35:
        return "suspected-borderline-correctness"
    return "clean-control"


def rank_key_flagged(r: dict):
    a = r["answers"]
    return (-a["problematic"]["noul"], a["correct"]["noul"], a["quality"]["score"], r["record_id"])


def rank_key_clean(r: dict):
    a = r["answers"]
    return (-a["correct"]["noul"], -a["quality"]["score"], r["record_id"])


# ---------------------------------------------------------------- 1. selection


def select_subset(jev: list | None = None, in84: set | None = None) -> list[dict]:
    """Deterministic 28-record targeted subset (no timestamps in output rows).

    R: 12 flagged retest (in-84, human-clean per Phase 2.1) — quotas math4/code3/general3/systems2
    F: 12 flagged fresh (never human-reviewed) — quotas math5/code2/general3/systems2
    C: 4 clean controls (2 in-84 + 2 fresh), strongest-clean first
    """
    jev = jev if jev is not None else load_jev()
    in84 = in84 if in84 is not None else load_in84()
    ok = [r for r in jev if r["status"] == "ok"]

    def pick(pool, quotas, key):
        chosen = []
        for arm, n in quotas.items():
            cands = sorted((r for r in pool if r["arm"] == arm), key=key)[:n]
            if len(cands) < n:
                raise RuntimeError(f"selection shortfall: arm={arm} need={n} have={len(cands)}")
            chosen.extend(cands)
        return chosen

    flagged_in = [r for r in ok if jev_flags(r) and r["record_id"] in in84]
    # dedupe by record_id (jev_results has one row per record; guard anyway)
    flagged_in = list({r["record_id"]: r for r in flagged_in}.values())
    flagged_fresh = [r for r in ok if jev_flags(r) and r["record_id"] not in in84]
    clean_in = sorted((r for r in ok if not jev_flags(r) and r["record_id"] in in84
                       and r["answers"]["quality"]["score"] >= 2.5
                       and r["answers"]["correct"]["noul"] >= 0.6), key=rank_key_clean)
    clean_fresh = sorted((r for r in ok if not jev_flags(r) and r["record_id"] not in in84
                          and r["answers"]["quality"]["score"] >= 2.5
                          and r["answers"]["correct"]["noul"] >= 0.6), key=rank_key_clean)

    rows = []
    for r in pick(flagged_in, {"math": 4, "code": 3, "general": 3, "systems": 2}, rank_key_flagged):
        rows.append({"record_id": r["record_id"], "arm": r["arm"], "group": "R-retest-flagged",
                     "hypothesis": hypothesize(r), "jev": _sig(r)})
    for r in pick(flagged_fresh, {"math": 5, "code": 2, "general": 3, "systems": 2}, rank_key_flagged):
        rows.append({"record_id": r["record_id"], "arm": r["arm"], "group": "F-fresh-flagged",
                     "hypothesis": hypothesize(r), "jev": _sig(r)})
    if len(clean_in) < 2 or len(clean_fresh) < 2:
        raise RuntimeError("selection shortfall: clean controls")
    for r in clean_in[:2] + clean_fresh[:2]:
        rows.append({"record_id": r["record_id"], "arm": r["arm"], "group": "C-clean-control",
                     "hypothesis": "clean-control", "jev": _sig(r)})
    assert len(rows) == 28, len(rows)
    assert len({r["record_id"] for r in rows}) == 28, "selection must be 28 unique records"
    return rows


def _sig(r: dict) -> dict:
    a = r["answers"]
    return {"quality": a["quality"]["score"], "correct": a["correct"]["noul"],
            "problematic": a["problematic"]["noul"], "adherence": a["adherence"]["noul"],
            "consistent_category": a["consistent_category"]["noul"],
            "training_value": a["training_value"]["score"], "flags": jev_flags(r)}


# ---------------------------------------------------------------- 2. build package


def build_package(rows: list[dict] | None = None, package_dir: Path = PACKAGE_DIR,
                  sealed_dir: Path = P22) -> dict:
    rows = rows if rows is not None else select_subset()
    pilot = load_pilot_by_id()
    missing = [r["record_id"] for r in rows if r["record_id"] not in pilot]
    if missing:
        raise RuntimeError(f"selection records missing from pilot/v0.2: {missing}")

    rec_dir = package_dir / "records"
    rec_dir.mkdir(parents=True, exist_ok=True)
    by_id = {r["record_id"]: r for r in rows}
    # signal-neutral ordering: batch IDs follow sorted record_id, never signal rank
    ordered = sorted(by_id)
    batch_of = {rid: f"P22-{i + 1:03d}" for i, rid in enumerate(ordered)}

    for rid in ordered:
        arm, rec = pilot[rid]
        payload = {
            "batch_id": batch_of[rid],
            # NO record_id, NO arm, NO strata, NO jev, NO prior labels — opaque by design
            "content_sha256": _content_sha(rec),
            "criteria_version": CRITERIA_VERSION,
            "reference_version": REFERENCE_VERSION,
            "source": rec.get("source"),
            "category_label": rec.get("category"),
            "subcategory_label": rec.get("subcategory"),
            "license": rec.get("license"),
            "messages": rec.get("messages"),
            "defect_criteria": _criteria_text(),
            "note": "BLINDED: opaque batch ID; no Jev signals, strata, arm, or prior labels by design.",
        }
        (rec_dir / f"{batch_of[rid]}.json").write_text(
            json.dumps(payload, indent=1, ensure_ascii=False) + "\n")

    (package_dir / "review_template.json").write_text(json.dumps({        "schema_version": SCHEMA_VERSION,
        "batch_id": "<P22-XXX>",
        "reviewer_id": "<your-reviewer-id>",
        "reviewed_at": "<ISO-8601, e.g. 2026-09-18T10:00:00+00:00>",
        "criteria_version": CRITERIA_VERSION,
        "reference_version": REFERENCE_VERSION,
        "blinded_to_jev": True,
        "blinded_to_prior_labels": True,
        "labels": {d: "<yes|no>" for d in DIMS},
        "evidence": {d: "<required (>=10 chars) for every finding-direction verdict>" for d in DIMS},
        "notes": "<optional>",
    }, indent=1) + "\n")

    sealed_map = {
        "sealed": True,
        "warning": "SEALED — reviewers must NOT open this file (or selection_manifest.sealed.json) until their blind pass is recorded. Unblinds batch IDs to record IDs and JEV signals.",
        "map": {batch_of[r["record_id"]]: {"record_id": r["record_id"], "arm": r["arm"],
                                           "group": r["group"]} for r in rows},
    }
    sealed_dir.mkdir(parents=True, exist_ok=True)
    (sealed_dir / "record_map.sealed.json").write_text(json.dumps(sealed_map, indent=1) + "\n")
    selection = {
        "sealed": True,
        "warning": "SEALED — contains JEV signals, groups, and hypotheses. Reviewers must NOT open mid-pass.",
        "version": "phase2.2-selection-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_records": len(rows),
        "groups": {g: sum(1 for r in rows if r["group"] == g) for g in ("R-retest-flagged", "F-fresh-flagged", "C-clean-control")},
        "arms": dict(Counter(r["arm"] for r in rows)),
        "method": ("R: flagged∩in-84 human-clean, strongest-signal per-arm quotas math4/code3/general3/systems2; "
                   "F: flagged∩fresh, quotas math5/code2/general3/systems2; "
                   "C: strongest-clean 2 in-84 + 2 fresh. Rank keys deterministic; batch IDs assigned in sorted-record_id order."),
        "rows": [{**r, "batch_id": batch_of[r["record_id"]]} for r in rows],
    }
    (sealed_dir / "selection_manifest.sealed.json").write_text(json.dumps(selection, indent=1) + "\n")
    pkg_manifest = {
        "version": "phase2.2-package-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_records": len(rows),
        "blinded": True,
        "criteria_version": CRITERIA_VERSION,
        "reference_version": REFERENCE_VERSION,
        "batches": sorted(batch_of.values()),
    }
    (package_dir / "manifest.json").write_text(json.dumps(pkg_manifest, indent=1) + "\n")
    return selection


def _content_sha(rec: dict) -> str:
    import hashlib as _h
    u = next((m.get("content", "") for m in rec.get("messages", []) if m.get("role") == "user"), "")
    a = next((m.get("content", "") for m in reversed(rec.get("messages", [])) if m.get("role") == "assistant"), "")
    f = lambda s: _h.sha256(s.encode()).hexdigest()[:16]
    return f(u) + ":" + f(a)


def _criteria_text() -> dict:
    return {
        "correctness": "Is the assistant response substantively correct? Finding = no.",
        "problematic": "Unsuitable as training data (contradictions, garbled, harmful, injection, PII)? Finding = yes.",
        "category_correct": "Content genuinely belongs to its category label per taxonomy_reference_v1? Finding = no.",
        "truncation_incomplete": "Cut off mid-reasoning, missing conclusion/boxed answer, visibly incomplete? Finding = yes.",
        "factual_technical_error": "Concrete wrong fact, wrong derivation step, or code that cannot work as claimed? Finding = yes.",
        "instruction_violation": "Ignores/contradicts the user request? Finding = yes.",
        "malformed_output": "Garbled text, broken encoding, stray fragments, unusable structure? Finding = yes.",
        "other_defect": "Concrete defect not covered above (describe in evidence)? Finding = yes.",
        "evidence_rule": "Every finding-direction verdict REQUIRES evidence (>=10 non-space chars) pinpointing the defect.",
    }


# ---------------------------------------------------------------- 3. validate


def _parse_time(s: str) -> bool:
    try:
        datetime.fromisoformat(s)
        return True
    except (ValueError, TypeError):
        return False


def validate_review(obj: dict, batches: set, filename: str) -> list[str]:
    errs: list[str] = []
    if not isinstance(obj, dict):
        return [f"{filename}: top-level JSON must be an object"]
    for f in TOP_LEVEL_KEYS - {"notes"}:
        if f not in obj:
            errs.append(f"{filename}: missing required field '{f}'")
    extra = set(obj) - TOP_LEVEL_KEYS
    if extra:
        errs.append(f"{filename}: forbidden extra fields {sorted(extra)} (possible unblinding leak)")
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
    if obj.get("blinded_to_prior_labels") is not True:
        errs.append(f"{filename}: blinded_to_prior_labels must be true")
    bid = obj.get("batch_id")
    if not isinstance(bid, str) or not BATCH_RE.match(bid):
        errs.append(f"{filename}: batch_id must match ^P22-[0-9]{{3}}$")
    elif bid not in batches:
        errs.append(f"{filename}: unknown batch_id '{bid}'")
    rid = obj.get("reviewer_id", "")
    if not isinstance(rid, str) or not REVIEWER_RE.match(rid):
        errs.append(f"{filename}: reviewer_id must match ^[A-Za-z0-9_-]{{1,64}}$")
    elif not filename.endswith(f"__{rid}.json"):
        errs.append(f"{filename}: filename must end with '__{rid}.json'")
    if not isinstance(obj.get("reviewed_at"), str) or not _parse_time(obj["reviewed_at"]):
        errs.append(f"{filename}: reviewed_at must be ISO-8601")
    labels, evidence = obj.get("labels"), obj.get("evidence")
    if not isinstance(labels, dict) or not isinstance(evidence, dict):
        return errs + [f"{filename}: labels and evidence must be objects"]
    for dim in DIMS:
        if dim not in labels:
            errs.append(f"{filename}: labels missing '{dim}'")
        elif labels[dim] not in ("yes", "no"):
            errs.append(f"{filename}: labels.{dim} must be 'yes'/'no', got {labels[dim]!r}")
        if dim not in evidence:
            errs.append(f"{filename}: evidence missing '{dim}'")
        elif not isinstance(evidence[dim], str):
            errs.append(f"{filename}: evidence.{dim} must be a string")
        elif labels.get(dim) == FINDING_VALUE[dim]:
            if len(evidence[dim].replace(" ", "").replace("\n", "")) < EVIDENCE_MIN_CHARS:
                errs.append(f"{filename}: evidence.{dim} required (>=10 non-space chars) for finding verdict '{labels[dim]}'")
    for dim in list(labels) + list(evidence):
        if dim not in DIMS:
            errs.append(f"{filename}: unknown dimension '{dim}'")
    return errs


def batch_set() -> set:
    man = json.loads((PACKAGE_DIR / "manifest.json").read_text())
    return set(man["batches"])


def validate_reviews(reviews_dir: Path = REVIEWS_DIR) -> dict:
    batches = batch_set() if (PACKAGE_DIR / "manifest.json").exists() else set()
    files = sorted(reviews_dir.glob("*.json")) if reviews_dir.is_dir() else []
    per_batch: dict[str, dict[str, dict]] = {}
    for b in batches:
        per_batch[b] = {}
    violations: list[str] = []
    n_valid = 0
    for path in files:
        try:
            obj = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            violations.append(f"{path.name}: invalid JSON ({e})")
            continue
        errs = validate_review(obj, batches, path.name)
        if errs:
            violations.extend(errs)
            continue
        bid, rid = obj["batch_id"], obj["reviewer_id"]
        if rid in per_batch.get(bid, {}):
            violations.append(f"{path.name}: duplicate review from '{rid}' for '{bid}'")
            continue
        per_batch.setdefault(bid, {})[rid] = obj
        n_valid += 1
    paired = sum(1 for v in per_batch.values() if len(v) >= 2)
    single = sum(1 for v in per_batch.values() if len(v) == 1)
    empty = sum(1 for v in per_batch.values() if not v)
    reviewers = sorted({r for v in per_batch.values() for r in v})
    return {
        "version": "phase2.2-review-status-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_batches": len(batches),
        "n_review_files_valid": n_valid,
        "n_review_files_total": len(files),
        "n_batches_two_reviewers": paired,
        "n_batches_one_reviewer": single,
        "n_batches_empty": empty,
        "reviewer_ids_seen": reviewers,
        "meets_two_reviewer_requirement": bool(batches) and paired == len(batches) and not violations,
        "violations": violations,
        "per_batch": {b: sorted(per_batch.get(b, {})) for b in sorted(batches)},
    }


# ---------------------------------------------------------------- 4. agreement + adjudication


def cohens_kappa(a_yes: int, a_no: int, b_yes: int, b_no: int, agree: int, n: int):
    if n == 0:
        return None
    po = agree / n
    pe = ((a_yes / n) * (b_yes / n)) + ((a_no / n) * (b_no / n))
    if pe == 1.0:
        return None
    return round((po - pe) / (1 - pe), 4)


def _paired_objs(status: dict, reviews_dir: Path = REVIEWS_DIR):
    for bid, rids in sorted(status["per_batch"].items()):
        if len(rids) >= 2:
            r2 = sorted(rids)[:2]
            yield bid, [json.loads((reviews_dir / f"{bid}__{r}.json").read_text()) for r in r2]


def compute_agreement(status: dict, reviews_dir: Path = REVIEWS_DIR) -> dict:
    pairs = list(_paired_objs(status, reviews_dir))
    out: dict = {
        "version": "phase2.2-agreement-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_batches_two_reviewers": len(pairs),
        "status": "COMPUTED" if pairs else "HOLD_NO_PAIRED_REVIEWS",
    }
    if not pairs:
        out["note"] = "No batch has two independent reviews yet. Metrics null — never fabricate."
        out["dimensions"] = {d: {"n_paired": 0, "n_agree": 0, "raw_agreement": None, "cohens_kappa": None} for d in DIMS}
        out["full_agreement"] = {"n_paired": 0, "n_full_agree": 0, "rate": None}
        return out
    dims = {}
    for dim in DIMS:
        a_yes = a_no = b_yes = b_no = agree = 0
        for _, (oa, ob) in pairs:
            va, vb = oa["labels"][dim], ob["labels"][dim]
            # kappa computed on finding-direction polarity is identical; use raw yes/no
            a_yes += va == "yes"
            a_no += va == "no"
            b_yes += vb == "yes"
            b_no += vb == "no"
            agree += va == vb
        n = len(pairs)
        dims[dim] = {"n_paired": n, "n_agree": agree, "raw_agreement": round(agree / n, 4),
                     "cohens_kappa": cohens_kappa(a_yes, a_no, b_yes, b_no, agree, n)}
    full = sum(1 for _, (oa, ob) in pairs if all(oa["labels"][d] == ob["labels"][d] for d in DIMS))
    out["dimensions"] = dims
    out["full_agreement"] = {"n_paired": len(pairs), "n_full_agree": full, "rate": round(full / len(pairs), 4)}
    return out


def build_adjudication_list(status: dict, reviews_dir: Path = REVIEWS_DIR) -> dict:
    items = []
    for bid, (oa, ob) in _paired_objs(status, reviews_dir):
        rids = sorted(status["per_batch"][bid])[:2]
        disagreed = [d for d in DIMS if oa["labels"][d] != ob["labels"][d]]
        if disagreed:
            items.append({
                "batch_id": bid,
                "reviewers": rids,
                "disagreed_dimensions": disagreed,
                "votes": {d: {rids[0]: {"verdict": oa["labels"][d], "evidence": oa["evidence"].get(d, "")},
                                     rids[1]: {"verdict": ob["labels"][d], "evidence": ob["evidence"].get(d, "")}}
                          for d in disagreed},
                "resolution": "pending_third_reviewer",
            })
    return {
        "version": "phase2.2-adjudication-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_disagreements": len(items),
        "n_paired_batches": sum(1 for v in status["per_batch"].values() if len(v) >= 2),
        "status": "COMPUTED" if status["n_batches_two_reviewers"] else "HOLD_NO_PAIRED_REVIEWS",
        "items": items,
        "adjudication_protocol": ("A third reviewer (different id from both originals) resolves each item; "
                                  "gold goes to reviews_adjudicated/<batch>.json. Raw reviews NEVER modified; "
                                  "disagreements NEVER auto-resolved."),
    }


# ---------------------------------------------------------------- 5. error analysis + assessment


def load_gold(status: dict, reviews_dir: Path = REVIEWS_DIR,
              adjudicated_dir: Path = ADJUDICATED_DIR) -> tuple[dict, dict]:
    gold, prov = {}, {}
    for bid, (oa, ob) in _paired_objs(status, reviews_dir):
        rids = sorted(status["per_batch"][bid])[:2]
        adj_path = adjudicated_dir / f"{bid}.json"
        adj = {}
        if adj_path.exists():
            aobj = json.loads(adj_path.read_text())
            adj = aobj.get("labels", {})
            if aobj.get("adjudicator_id") in rids:
                adj = {}  # adjudicator must differ from both originals; else ignore + flag below
        g, p = {}, {}
        for dim in DIMS:
            if oa["labels"][dim] == ob["labels"][dim]:
                g[dim] = oa["labels"][dim]
                p[dim] = f"agreement:{rids[0]}+{rids[1]}"
            elif dim in adj and adj[dim] in ("yes", "no"):
                g[dim] = adj[dim]
                p[dim] = "adjudicated"
            else:
                p[dim] = "disputed_unadjudicated_excluded"
        gold[bid] = g
        prov[bid] = p
    return gold, prov


def human_defect(g: dict) -> bool | None:
    """True=defect, False=clean, None=unusable (no agreed/adjudicated defect dim)."""
    vals = [g[d] for d in DEFECT_DIMS if d in g]
    if not vals:
        return None
    return any(v == FINDING_VALUE[d] for d, v in zip([d for d in DEFECT_DIMS if d in g], vals))


def error_analysis(status: dict, reviews_dir: Path = REVIEWS_DIR,
                   adjudicated_dir: Path = ADJUDICATED_DIR) -> dict:
    sel = json.loads((P22 / "selection_manifest.sealed.json").read_text())
    by_batch = {r["batch_id"]: r for r in sel["rows"]}
    gold, prov = load_gold(status, reviews_dir, adjudicated_dir)
    if not gold:
        return {"version": "phase2.2-error-analysis-v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "status": "HOLD_NO_GOLD",
                "note": "No agreed/adjudicated gold exists. Matrix cells are null — never fabricate.",
                "matrix": {"TP_flagged_defect": None, "FP_flagged_clean": None,
                           "FN_clean_defect": None, "TN_clean_clean": None},
                "metrics": {"precision": None, "recall": None, "fpr": None, "fnr": None},
                "items": []}
    tp = fp = fn = tn = 0
    unusable = 0
    items = []
    for bid, g in sorted(gold.items()):
        hd = human_defect(g)
        jf = bool(by_batch[bid]["jev"]["flags"])
        if hd is None:
            unusable += 1
            continue
        if jf and hd:
            tp += 1
        elif jf and not hd:
            fp += 1
        elif not jf and hd:
            fn += 1
        else:
            tn += 1
        cell = {(True, True): "TP_flagged_defect", (True, False): "FP_flagged_clean",
                (False, True): "FN_clean_defect", (False, False): "TN_clean_clean"}[(jf, hd)]
        items.append({
            "batch_id": bid,
            "record_id": by_batch[bid]["record_id"],
            "group": by_batch[bid]["group"],
            "cell": cell,
            "jev_flagged": jf,
            "jev_signals": by_batch[bid]["jev"],
            "human_defect": hd,
            "human_labels": {d: g.get(d) for d in DIMS},
            "gold_provenance": prov[bid],
            "candidate_reasons": list(CANDIDATE_REASONS),
            "analyst_reason_selected": None,
            "resolution": "pending_analyst" if cell in ("FP_flagged_clean", "FN_clean_defect") else "agreement",
        })
    return {
        "version": "phase2.2-error-analysis-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "COMPUTED",
        "n_gold_batches": len(gold),
        "n_unusable_no_defect_status": unusable,
        "matrix": {"TP_flagged_defect": tp, "FP_flagged_clean": fp,
                   "FN_clean_defect": fn, "TN_clean_clean": tn},
        "metrics": {
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "fpr": round(fp / (fp + tn), 4) if fp + tn else None,
            "fnr": round(fn / (fn + tp), 4) if fn + tp else None,
        },
        "category_correct_note": "category_correct excluded from the defect matrix (taxonomy placement, not content defect); see agreement per-dimension.",
        "items": items,
    }


def assess(status: dict, err: dict, adj: dict) -> dict:
    """Gate recalculation from evidence only. No thresholds invented here."""
    paired_ok = status["meets_two_reviewer_requirement"]
    disagreements_open = adj.get("n_disagreements", 0)
    m = err.get("matrix", {})
    known = [v for v in m.values() if v is not None]
    n_known = sum(known) if known else 0
    tp, fp, fn = m.get("TP_flagged_defect") or 0, m.get("FP_flagged_clean") or 0, m.get("FN_clean_defect") or 0
    d = ("READY" if paired_ok and not disagreements_open
         else "CAVEATED" if paired_ok else "BLOCKED")
    if err.get("status") != "COMPUTED" or n_known == 0:
        e, f, why_e, why_f = "INCONCLUSIVE", "NO", "no usable error-analysis gold", "no evidence to scale spend"
    elif disagreements_open:
        e, f, why_e, why_f = "INCONCLUSIVE", "NO", f"{disagreements_open} disagreements await third review", "adjudication incomplete"
    elif tp + fn == 0:
        e, f, why_e, why_f = ("INCONCLUSIVE", "NO",
                              "gold has zero human-defect positives: recall unmeasurable, no operating point supportable",
                              "zero-positive gold cannot validate detection; another iteration or revised sampling required")
    elif tp + fp == 0:
        e, f, why_e, why_f = ("INCONCLUSIVE", "NO",
                              "gold has zero JEV-flagged cases usable: precision unmeasurable",
                              "no evidence to scale spend")
    else:
        e, f = "READY", "CONDITIONAL"
        why_e = (f"matrix TP={tp} FP={fp} FN={fn}: measurable precision/recall; thresholds provisional, same-set fit")
        why_f = ("shadow run justifiable ONLY at an evidence-backed operating point with stated FPR/FNR limits; "
                 "stratified prevalence does not transfer — flag-rate expectations must be re-estimated on the target population")
        f = "NO"  # default-deny: flip to YES only by explicit human decision, never automatically
        why_f = ("default-deny: even with measurable calibration, the ~2,942-record spend requires explicit human "
                 "go-ahead at a stated operating point. " + why_f)
    return {"version": "phase2.2-assessment-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "D_human_calibration_quality": {"status": d,
                "detail": f"{status['n_batches_two_reviewers']}/{status['n_batches']} paired, {len(status['violations'])} violations, {disagreements_open} open disagreements"},
            "E_jev_threshold_calibration": {"status": e, "detail": why_e},
            "F_shadow_run_2942": {"status": f, "detail": why_f}}


# ---------------------------------------------------------------- main


def cmd_all():
    rows = select_subset()
    sel = build_package(rows)
    print(f"select+package: {sel['n_records']} records {sel['groups']} -> {PACKAGE_DIR}")
    status = validate_reviews()
    (P22 / "review_status.json").write_text(json.dumps(status, indent=1) + "\n")
    print(f"validate: {status['n_batches_two_reviewers']}/{status['n_batches']} paired; {len(status['violations'])} violations")
    agr = compute_agreement(status)
    (P22 / "agreement.json").write_text(json.dumps(agr, indent=1) + "\n")
    print(f"agreement: {agr['status']}")
    adj = build_adjudication_list(status)
    (P22 / "adjudication_list.json").write_text(json.dumps(adj, indent=1) + "\n")
    print(f"adjudication: {adj['n_disagreements']} disagreements")
    err = error_analysis(status)
    (P22 / "error_analysis.json").write_text(json.dumps(err, indent=1) + "\n")
    print(f"error-analysis: {err['status']}")
    asm = assess(status, err, adj)
    (P22 / "assessment.json").write_text(json.dumps(asm, indent=1) + "\n")
    print(f"assess: D={asm['D_human_calibration_quality']['status']} "
          f"E={asm['E_jev_threshold_calibration']['status']} F={asm['F_shadow_run_2942']['status']}")
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
    if cmd == "all":
        cmd_all()
    elif cmd == "select":
        rows = select_subset()
        print(f"selected {len(rows)}: {Counter(r['group'] for r in rows)} arms={dict(Counter(r['arm'] for r in rows))}")
    elif cmd == "build-package":
        sel = build_package()
        print(f"package: {sel['n_records']} records -> {PACKAGE_DIR}")
    elif cmd == "validate":
        status = validate_reviews()
        (P22 / "review_status.json").write_text(json.dumps(status, indent=1) + "\n")
        print(json.dumps({k: status[k] for k in ("n_batches", "n_batches_two_reviewers",
              "n_batches_one_reviewer", "n_batches_empty", "reviewer_ids_seen",
              "meets_two_reviewer_requirement")}, indent=1))
        for v in status["violations"]:
            print("VIOLATION:", v)
    elif cmd == "agreement":
        status = validate_reviews()
        agr = compute_agreement(status)
        (P22 / "agreement.json").write_text(json.dumps(agr, indent=1) + "\n")
        print(agr["status"])
    elif cmd == "adjudication":
        status = validate_reviews()
        adj = build_adjudication_list(status)
        (P22 / "adjudication_list.json").write_text(json.dumps(adj, indent=1) + "\n")
        print(f"disagreements: {adj['n_disagreements']}")
    elif cmd == "error-analysis":
        status = validate_reviews()
        err = error_analysis(status)
        (P22 / "error_analysis.json").write_text(json.dumps(err, indent=1) + "\n")
        print(err["status"])
    elif cmd == "assess":
        status = validate_reviews()
        err = error_analysis(status)
        adj = build_adjudication_list(status)
        asm = assess(status, err, adj)
        (P22 / "assessment.json").write_text(json.dumps(asm, indent=1) + "\n")
        print(json.dumps(asm, indent=1))
    else:
        print(f"unknown command {cmd}; use all|select|build-package|validate|agreement|adjudication|error-analysis|assess")
