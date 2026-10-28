#!/usr/bin/env python3
"""Phase 2 — Atlas pilot/v0.2 deduplication, taxonomy audit, and calibration prep.

Shadow-only: reads pilot/v0.2 and Phase 1 Jev results; writes artifacts under
experiments/jev-pilot-atlas-v0.1/phase2/. Never modifies Atlas source data.

Usage:
  python phase2_prep.py all
  python phase2_prep.py dedup
  python phase2_prep.py taxonomy
  python phase2_prep.py calibration-set
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
OUT = P1 / "phase2"

PILOT_FILES = {
    "math": ROOT / "pilot" / "v0.2" / "math" / "train.jsonl",
    "code": ROOT / "pilot" / "v0.2" / "code" / "train.jsonl",
    "general": ROOT / "pilot" / "v0.2" / "general" / "train.jsonl",
    "systems": ROOT / "v0.2" if False else ROOT / "pilot" / "v0.2" / "systems" / "train.jsonl",
}

# ---------------------------------------------------------------- helpers


def sha16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def load_pilot():
    """arm -> list of record dicts, preserving original IDs."""
    data = {}
    for arm, path in PILOT_FILES.items():
        recs = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    recs.append(json.loads(line))
        data[arm] = recs
    return data


def user_text(rec: dict) -> str:
    return next((m.get("content", "") for m in rec.get("messages", []) if m.get("role") == "user"), "")


def asst_text(rec: dict) -> str:
    return next((m.get("content", "") for m in reversed(rec.get("messages", [])) if m.get("role") == "assistant"), "")


def source_id(rec: dict):
    s = rec.get("source")
    if isinstance(s, dict):
        return s.get("source_id") or s.get("name") or ""
    return s if s is not None else ""


def record_provenance(rec: dict, arm: str) -> dict:
    """Traceable identity for a record: original id, content hash, arm, source."""
    return {
        "record_id": rec.get("id"),
        "arm": arm,
        "source": source_id(rec),
        "category_label": rec.get("category"),
        "subcategory_label": rec.get("subcategory"),
        "user_sha256_16": sha16(user_text(rec)),
        "asst_sha256_16": sha16(asst_text(rec)),
        "full_content_sha256": sha16(
            json.dumps(rec.get("messages", []), sort_keys=True, ensure_ascii=False)
        ),
    }


# ---------------------------------------------------------------- 1. dedup


def _stable_manifest(manifest: dict) -> dict:
    """Strip non-deterministic fields for equality checks / hashing."""
    m = {k: v for k, v in manifest.items() if k not in ("generated_at",)}
    for row in m.get("records", []):
        row.pop("generated_at", None)
    return m


def dedup_analysis(data: dict) -> dict:
    m = _dedup_core(data)
    m["generated_at"] = datetime.now(timezone.utc).isoformat()
    return m


def _dedup_core(data: dict) -> dict:
    """Deterministic core — no timestamps. `dedup_analysis` wraps with generated_at."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from dedup_dataset import shingles, minhash_signature, jaccard

    # exact content groups
    full_groups = defaultdict(list)
    user_groups = defaultdict(list)
    user_shingles = {}
    for arm, recs in data.items():
        for rec in recs:
            key = (sha16(json.dumps(rec.get("messages", []), sort_keys=True, ensure_ascii=False)),)
            full_groups[sha16(json.dumps(rec.get("messages", []), sort_keys=True, ensure_ascii=False))].append(
                record_provenance(rec, arm)
            )
            user_groups[sha16(user_text(rec))].append(record_provenance(rec, arm))
            user_shingles[rec.get("id")] = set(shingles(user_text(rec), k=4))

    exact_content_dups = {k: v for k, v in full_groups.items() if len(v) > 1}
    exact_user_dups = {k: v for k, v in user_groups.items() if len(v) > 1}

    # near-dup candidates via banding on user content (same LSH as dedup_dataset.py)
    NUM_BANDS, ROWS = 32, 4
    sigs = {}
    for arm, recs in data.items():
        for rec in recs:
            rid = rec.get("id")
            sigs[rid] = minhash_signature(user_shingles[rid])
    buckets: dict[int, set] = defaultdict(set)
    import itertools

    for rid, sig in sigs.items():
        for b in range(NUM_BANDS):
            start = b * ROWS
            band_sig = sig[start:start + ROWS]
            h = int.from_bytes(
                (tuple(band_sig)).__repr__().encode(), "big", signed=False
            ) % (2**64)
            buckets[h].add(rid)
    candidates: set[tuple] = set()
    for group in buckets.values():
        if len(group) < 2:
            continue
        for a, b in itertools.combinations(sorted(group), 2):
            j = jaccard(user_shingles[a], user_shingles[b])
            if 0.8 <= j < 1.0:
                candidates.add((a, b, round(j, 4)))

    exact_content_rids = {p["record_id"] for v in exact_content_dups.values() for p in v}
    exact_user_rids = {p["record_id"] for v in exact_user_dups.values() for p in v}

    # canonical selection: earliest arm order, then input order
    ARM_ORDER = ["math", "code", "general", "systems"]
    def canon_key(p):
        return (ARM_ORDER.index(p["arm"]),)

    manifest_rows = []
    full_dup_rows = 0
    user_only_dup_rows = 0
    for h, group in sorted(exact_content_dups.items()):
        group_sorted = sorted(group, key=lambda p: (ARM_ORDER.index(p["arm"]), p["record_id"]))
        canon = group_sorted[0]
        for p in group_sorted[1:]:
            full_dup_rows += 1
            manifest_rows.append({
                "dup_class": "exact_duplicate",
                "dedup_action": "drop_duplicate",
                "canonical_record_id": canon["record_id"],
                "canonical_arm": canon["arm"],
                "duplicate_record_id": p["record_id"],
                "duplicate_arm": p["arm"],
                "duplicate_source": p["source"],
                "content_sha256": h,
                "note": "identical user+assistant content across arms",
                "requires_human_review": False,
                "human_review_reason": None,
            })
    # user-only dups that are NOT full-content dups
    for h, group in sorted(exact_user_dups.items()):
        if h in exact_content_dups:
            continue
        group_sorted = sorted(group, key=lambda p: (ARM_ORDER.index(p["arm"]), p["record_id"]))
        canon = group_sorted[0]
        for p in group_sorted[1:]:
            user_only_dup_rows += 1
            same_src = canon["source"] == p["source"]
            manifest_rows.append({
                "dup_class": "exact_duplicate_user_only",
                "dedup_action": "drop_duplicate" if same_src else "keep_both_review",
                "canonical_record_id": canon["record_id"],
                "canonical_arm": canon["arm"],
                "duplicate_record_id": p["record_id"],
                "duplicate_arm": p["arm"],
                "duplicate_source": p["source"],
                "content_sha256": h,
                "note": "identical user content, differing assistant responses",
                "requires_human_review": not same_src,
                "human_review_reason": None if same_src else "same prompt from two different sources; decide whether distinct answers are legitimate",
            })
    dup_count = full_dup_rows  # only identical full-content duplicates reduce the record count

    # near-dup rows
    near_seen = set()
    for a, b, j in sorted(candidates):
        pair = tuple(sorted((a, b)))
        if pair in near_seen:
            continue
        near_seen.add(pair)
        rec_a = next((r for arm in data for r in data[arm] if r.get("id") == a), {})
        rec_b = next((r for arm in data for r in data[arm] if r.get("id") == b), {})
        pa, pb = record_provenance(rec_a, rec_a.get("arm", "?")), record_provenance(rec_b, rec_b.get("arm", "?"))
        manifest_rows.append({
            "dup_class": "near_duplicate",
            "dedup_action": "keep_both_review",
            "canonical_record_id": None,
            "duplicate_record_id": None,
            "pair": [
                {k: pa[k] for k in ("record_id", "arm", "source", "user_sha256_16")},
                {k: pb[k] for k in ("record_id", "arm", "source", "user_sha256_16")},
            ],
            "jaccard": j,
            "content_sha256": None,
            "note": "user-content Jaccard in [0.8, 1.0); not exact duplicates",
            "requires_human_review": True,
            "human_review_reason": "near-duplicate: confirm whether distinct examples or redundant",
        })

    n_total = sum(len(v) for v in data.values())
    manifest = {
        "version": "phase2-dedup-v1",
        "scope": "pilot/v0.2 (4 arms)",
        "method": "deterministic SHA-256 content hashing (exact) + MinHash LSH Jaccard>=0.8 on user text (near); canonical = earliest arm in [math,code,general,systems] then input order",
        "n_total_records": n_total,
        "n_exact_content_dup_groups": len(exact_content_dups),
        "n_exact_user_only_dup_groups": len(exact_user_dups) - len(exact_content_dups),
        "n_near_dup_pairs": len(near_seen),
        "n_duplicate_rows": full_dup_rows + user_only_dup_rows,
        "n_exact_content_duplicate_rows": full_dup_rows,
        "n_user_only_duplicate_rows": user_only_dup_rows,
        "unique_records_after_exact_dedup": n_total - full_dup_rows,
        "records_after_excluding_user_only_redundant": n_total - full_dup_rows - sum(
            1 for r in manifest_rows
            if r["dup_class"] == "exact_duplicate_user_only" and r["dedup_action"] == "drop_duplicate"
        ),
        "n_requires_human_review": sum(1 for r in manifest_rows if r["requires_human_review"]),
        "breakdown": {
            "exact_content_dup_groups": len(exact_content_dups),
            "exact_user_only_dup_groups": len(exact_user_dups) - len(exact_content_dups),
            "exact_user_only_same_source_rows": sum(
                1 for r in manifest_rows
                if r["dup_class"] == "exact_duplicate_user_only" and r["dedup_action"] == "drop_duplicate"
            ),
            "exact_user_only_diff_source_rows": sum(
                1 for r in manifest_rows
                if r["dup_class"] == "exact_duplicate_user_only" and r["dedup_action"] == "keep_both_review"
            ),
            "near_dup_pairs": len(near_seen),
            "exact_dup_by_arm_pair": {
                f"{k[0]}->{k[1]}": v
                for k, v in Counter(
                    (r["canonical_arm"], r["duplicate_arm"])
                    for r in manifest_rows if r["dup_class"] == "exact_duplicate"
                ).most_common()
            },
            "note": (
                "exact_duplicate rows = the 822 identical user+assistant content groups "
                "(the Phase-1 finding). exact_duplicate_user_only = same prompt, different "
                "answers: same-source pairs are redundant (drop), cross-source pairs are "
                "potentially legitimate parallel answers (human review). "
                "unique_records_after_exact_dedup counts ONLY the identical-content groups; "
                "user-only and near-dup rows need review before they are ever dropped."
            ),
        },
        "records": manifest_rows,
    }
    return manifest


# ---------------------------------------------------------------- 2. taxonomy

# Independent category reference (see phase2/taxonomy_reference_v1.json).
# The audit compares record content against this reference — NOT against the
# record's own category label.
CATEGORY_KEYWORDS = {
    "01_foundation": ["reason", "explain", "define", "general", "communication", "writing"],
    "02_software_engineering": ["def ", "function", "class ", "python", "code", "bug", "algorithm", "repository", "swe", "fix", "test", "django", "parse"],
    "03_system_engineering": ["linux", "kernel", "network", "docker", "kubernetes", "tcp", "process", "systemd", "device", "driver", "mutex"],
    "04_ai_machine_learning": ["model", "neural", "training", "gradient", "llm", "transformer", "dataset", "inference", "embed"],
    "05_hardware_engineering": ["cpu", "gpio", "voltage", "pcb", "microcontroller", "fpga", "hardware", "sensor"],
    "06_science_engineering": ["equation", "derive", "physics", "chemical", "thermo", "circuit", "force", "momentum"],
    "07_business_knowledge": ["market", "revenue", "strategy", "financial", "business plan", "cost"],
    "08_creative_knowledge": ["story", "poem", "fiction", "creative", "narrative", "character"],
    "09_personal_assistant": ["calendar", "schedule", "reminder", "personal", "email me", "book"],
}
# Math-specific signals (pilot/v0.2 math arm is math)
MATH_DOMAIN = [
    r"\b(prove|proof|triangle|ellipse|hyperbola|polygon|integral|derivative|polynomial|modular)\b",
    r"\b(digit|base [a-z]|integer pair|combinator|algebra|geometry|number theory)\b",
    r"\\frac", r"\\sum", r"\\int", r"\\boxed", r"\\d",
    r"\b(equation|inequality|prime number|congruence)\b",
]
MATH_RE = re.compile("|".join(MATH_DOMAIN), re.IGNORECASE)


def infer_category(content: str, source: str) -> dict:
    """Independent, content-based category inference (domain-scoped signals).

    Deliberately conservative: returns a distribution over candidate categories
    plus a confidence flag. Used to SUSPECT misclassification, not to relabel.
    Domain signals are weighted so that code/kernel-specific terms dominate over
    generic numerals; a record is only a 'suspect' when inference is confident
    AND disagrees with the label.
    """
    low = content.lower()
    scores: dict[str, float] = {}

    def bump(cat, w):
        scores[cat] = scores.get(cat, 0.0) + w

    # source priors first (strongest provenance signal)
    s = str(source).lower()
    if "linux-kernel" in s:
        bump("03_system_engineering", 6)
    if "swe" in s:
        bump("02_software_engineering", 6)
    if "openmath" in s:
        bump("01_foundation", 6)

    # domain-specific, weighted signals
    if re.search(r"\b(def |class |import |from .+ import |try:|except|assert|middleware|migration|fixture|patch)\b", low):
        bump("02_software_engineering", 3)
    if re.search(r"\b(fix|bug|error|function|variable|repository|commit|pull request|stack ?trace|unit test|django|refactor|sympy|numpy|module|package)\b", low):
        bump("02_software_engineering", 2)
    if re.search(r"\b(linux|kernel|driver|systemd|network|docker|kubernetes|tcp|udp|process|mutex|device|firmware|container|iptables|mailbox|semaphore)\b", low):
        bump("03_system_engineering", 3)
    if re.search(r"\b(neural|gradient|training|inference|embed|transformer|llm|model weight|loss function|fine-?tun)\b", low):
        bump("04_ai_machine_learning", 3)
    if re.search(r"\b(cpu|gpio|voltage|pcb|microcontroller|fpga|hardware|sensor|clock signal)\b", low):
        bump("05_hardware_engineering", 3)
    if re.search(r"\b(physics|thermodynamic|chemical|circuit|force|momentum|ohm|newton|energy conservation)\b", low):
        bump("06_science_engineering", 3)
    if re.search(r"\b(revenue|market|strategy|financial|business plan|cost-benefit|profit|shareholder)\b", low):
        bump("07_business_knowledge", 3)
    if re.search(r"\b(story|poem|fiction|narrative|character arc|creative writing)\b", low):
        bump("08_creative_knowledge", 3)
    if re.search(r"\b(calendar|schedule|reminder|book (a|the)|email (me|my)|personal)\b", low):
        bump("09_personal_assistant", 3)
    # strong math-domain signals -> foundation reasoning in this taxonomy
    math_hits = len(MATH_RE.findall(content))
    if math_hits:
        bump("01_foundation", min(math_hits, 6))
    if re.search(r"\b(prove|proof|integer|arithmetic|solve for)\b", low):
        bump("01_foundation", 1)
    # generic reasoning fallback
    if re.search(r"\b(explain|describe|define|summarize|what is|how does|why)\b", low):
        bump("01_foundation", 0.5)

    if not scores:
        return {"predicted": None, "confidence": 0.0, "scores": {}, "method": "domain-signal", "note": "no signal; inconclusive"}
    best = max(scores.values())
    total = sum(scores.values())
    top = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    confidence = best / total
    second = top[1][1] / total if len(top) > 1 else 0.0
    # math-heavy content is legitimately foundation; low confidence when a domain
    # signal competes (record may belong to the domain arm, not foundation)
    if math_hits and len([c for c in scores if c != "01_foundation" and scores[c] >= 2]) >= 1:
        confidence = min(confidence, 0.45)
    return {
        "predicted": top[0][0],
        "confidence": round(confidence, 3),
        "margin": round(confidence - second, 3),
        "scores": {k: round(v, 2) for k, v in scores.items()},
        "method": "domain-signal (weighted, source-prior)",
        "note": "independent inference; suspect when confidence>=0.5 AND margin>=0.3 AND predicted != label",
    }


def taxonomy_audit(data: dict) -> dict:
    rows = []
    per_category = defaultdict(lambda: {"n": 0, "suspect": 0, "predicted_counts": Counter()})
    examples = []
    for arm, recs in data.items():
        for rec in recs:
            label = rec.get("category")
            src = source_id(rec)
            content = user_text(rec) + "\n" + asst_text(rec)
            inf = infer_category(content, src)
            # pilot/v0.2 uses non-canonical labels (mathematics, software_engineering,
            # system_engineering). Map them to canonical for comparison.
            label_canon = {
                "mathematics": "01_foundation",
                "software_engineering": "02_software_engineering",
                "system_engineering": "03_system_engineering",
            }.get(label, label)
            predicted = inf.get("predicted")
            # 01_foundation is the 'general reasoning' bucket: math-domain content
            # legitimately lands there. A non-math-domain prediction against a
            # math label is a real mismatch; a math prediction against a
            # non-math label is a real mismatch; same-domain is a match.
            MATCHED = {
                ("01_foundation", "01_foundation"),  # math/general
                ("02_software_engineering", "02_software_engineering"),
                ("03_system_engineering", "03_system_engineering"),
            }
            # treat 01_foundation as compatible with itself only; all others strict
            match = (
                (predicted, label_canon) in MATCHED
                or predicted is None  # inconclusive -> no evidence of mismatch
            )
            suspect = (
                not match
                and predicted is not None
                and label_canon is not None
                and inf.get("confidence", 0) >= 0.5
                and inf.get("margin", 0) >= 0.3
            )
            pc = per_category[label]
            pc["n"] += 1
            pc["predicted_counts"][inf.get("predicted")] += 1
            if suspect:
                pc["suspect"] += 1
            row = {
                "record_id": rec.get("id"),
                "arm": arm,
                "source": src,
                "label": label,
                "label_canonical": label_canon,
                "inferred_category": inf["predicted"],
                "inferred_confidence": inf["confidence"],
                "inferred_scores": inf["scores"],
                "label_match": match,
                "suspect_misclassification": suspect,
            }
            rows.append(row)
            # collect examples: all confident suspects first, then domain-mismatches
            if (suspect or (not match and inf.get("confidence", 0) >= 0.4)) and len(examples) < 60:
                examples.append({
                    **{k: row[k] for k in ("record_id", "arm", "source", "label", "inferred_category", "inferred_confidence")},
                    "domain_mismatch": (not match) and not suspect,
                    "user_snippet": user_text(rec)[:220].replace("\n", " "),
                })
    # tally non-suspect domain disagreements (predicted != label, any confidence)
    domain_mismatch = 0
    for r in rows:
        pred, lab = r.get("inferred_category"), r.get("label_canonical")
        if pred is None or lab is None:
            continue
        if pred == lab:
            continue
        MATCHED_PAIRS = {
            ("01_foundation", "01_foundation"),
            ("02_software_engineering", "02_software_engineering"),
            ("03_system_engineering", "03_system_engineering"),
        }
        if (pred, lab) not in MATCHED_PAIRS:
            domain_mismatch += 1

    audit = {
        "version": "phase2-taxonomy-audit-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "independent domain-signal inference; NOT the record's own label",
        "reference_version": "taxonomy_reference_v1",
        "n_records": len(rows),
        "n_suspect_misclassification": sum(1 for r in rows if r["suspect_misclassification"]),
        "n_domain_mismatch_any_confidence": domain_mismatch,
        "n_label_match": sum(1 for r in rows if r["label_match"]),
        "n_inconclusive_inference": sum(1 for r in rows if r.get("inferred_category") is None),
        "per_label": {k: {"n": v["n"], "suspect": v["suspect"], "predicted_counts": dict(v["predicted_counts"].most_common())} for k, v in sorted(per_category.items())},
        "representative_suspects": examples,
        "interpretation": (
            "n_suspect_misclassification = confident (>=0.5) AND clear-margin (>=0.3) AND domain-mismatched "
            "inferences: the strongest screen-detected misclassifications. "
            "n_domain_mismatch_any_confidence = all records whose predicted domain differs from the label "
            "(including low-confidence inferences): the full disagreement surface for human review. "
            "n_inconclusive_inference = records with no detectable domain signal: cannot be judged by this method."
        ),
        "limitation": "keyword/domain-signal method is a coarse screen; it is NOT ground truth. Math-domain content is "
            "legitimately 01_foundation (general reasoning) in this pilot's taxonomy. Source priors are weighted heavily "
            "because source is authoritative provenance. Human review is required before any relabel decision.",
        "rows": rows,
    }
    return audit


# ---------------------------------------------------------------- 3. reference


def taxonomy_reference() -> dict:
    """Independent, versioned category reference.

    Jev category-consistency questions must compare record content against THIS
    reference (out-of-state), not against the label supplied in the record.
    """
    cat_meta = json.loads((ROOT / "metadata" / "categories.json").read_text())
    reference = {
        "version": "taxonomy_reference_v1",
        "created": datetime.now(timezone.utc).isoformat(),
        "purpose": "independent category reference for Jev shadow evaluation (out-of-state)",
        "note": "Derived from metadata/categories.json (canonical Atlas taxonomy) plus pilot/v0.2 observed label mappings. Auditable: each entry lists its source.",
        "label_mappings": {
            "mathematics": "01_foundation",
            "software_engineering": "02_software_engineering",
            "system_engineering": "03_system_engineering",
        },
        "categories": {},
    }
    for key, meta in cat_meta["categories"].items():
        reference["categories"][key] = {
            "title": meta["title"],
            "description": meta["description"],
            "subcategories": meta.get("subcategories", []),
            "source": "metadata/categories.json",
        }
    reference["sha256"] = None  # filled below
    body = json.dumps({k: v for k, v in reference.items() if k != "sha256"}, sort_keys=True).encode()
    reference["sha256"] = hashlib.sha256(body).hexdigest()
    return reference


# ---------------------------------------------------------------- 4. calibration set


def calibration_set(jev_results: list[dict], data: dict) -> dict:
    """Stratified ~100-record human calibration set.

    Criteria are defined HERE, before any human labels are collected:
      correctness       — is the assistant response substantively correct? (yes/no)
      problematic       — is the record unsuitable as training data? (yes/no)
      category_correct  — does content belong to the record's label? (yes/no)
    Stratification (deterministic, seeded):
      normal       40 — quality>=2.5 AND correct>=0.6 AND not flagged
      low_jev      20 — lowest Jev quality scores
      flagged      20 — >=1 Jev flag (problematic>=0.5 OR correct<0.35 OR quality<=1)
      outliers     10 — quality<1.5 OR correct<0.25
      spread       10 — one per arm-source cell to cover remaining arms
    """
    import random

    ok = [r for r in jev_results if r["status"] == "ok"]

    def flags(r):
        f = []
        if r["answers"]["problematic"]["noul"] >= 0.5:
            f.append("problematic")
        if r["answers"]["correct"]["noul"] < 0.35:
            f.append("unlikely_correct")
        if r["answers"]["quality"]["score"] <= 1.0:
            f.append("low_quality")
        return f

    normal = [r for r in ok if r["answers"]["quality"]["score"] >= 2.5 and r["answers"]["correct"]["noul"] >= 0.6 and not flags(r)]
    low = sorted(ok, key=lambda r: r["answers"]["quality"]["score"])
    flagged = [r for r in ok if flags(r)]
    outliers = [r for r in ok if r["answers"]["quality"]["score"] < 1.5 or r["answers"]["correct"]["noul"] < 0.25]

    # deterministic picks
    rng = random.Random("calib-v1")
    picks: dict[str, list[dict]] = {
        "normal": rng.sample(normal, min(40, len(normal))),
        "low_jev": low[:20],
        "flagged": rng.sample(flagged, min(20, len(flagged))),
        "outliers": rng.sample(outliers, min(10, len(outliers))),
    }
    chosen_ids = {r["record_id"] for v in picks.values() for r in v}
    # spread: one per (arm, source) cell not yet covered
    cells = defaultdict(list)
    for r in ok:
        if r["record_id"] not in chosen_ids:
            cells[(r["arm"], r.get("source_id"))].append(r)
    spread = []
    for cell in sorted(cells, key=lambda c: (str(c[0]), str(c[1]))):
        rng2 = random.Random(f"calib-v1:spread:{cell[0]}:{cell[1]}")
        pick = rng2.choice(cells[cell])
        if pick["record_id"] not in chosen_ids:
            spread.append(pick)
            chosen_ids.add(pick["record_id"])
        if len(spread) >= 10:
            break

    rec_by_id = {}
    for arm, recs in data.items():
        for rec in recs:
            rec_by_id.setdefault(rec.get("id"), (arm, rec))

    manifest_rows = []
    for stratum, items in {**picks, "spread": spread}.items():
        for r in items:
            arm, _ = rec_by_id.get(r["record_id"], (r["arm"], None))
            manifest_rows.append({
                "record_id": r["record_id"],
                "arm": r["arm"],
                "stratum": stratum,
                "jev_signals": {
                    "quality": r["answers"]["quality"]["score"],
                    "correct": r["answers"]["correct"]["noul"],
                    "problematic": r["answers"]["problematic"]["noul"],
                    "adherence": r["answers"]["adherence"]["noul"],
                    "consistent_category": r["answers"]["consistent_category"]["noul"],
                    "training_value": r["answers"]["training_value"]["score"],
                    "flags": flags(r),
                },
                "content_sha256": r.get("content_sha256"),
                "labeling_status": "pending",
                "human_labels": None,
            })
    manifest = {
        "version": "phase2-calibration-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_records": len(manifest_rows),
        "strata": {k: len(v) for k, v in {**picks, "spread": spread}.items()},
        "labeling_criteria": {
            "correctness": "Is the assistant response substantively correct given the user request? Answer yes/no. 'Substantively' means the final answer/conclusion is right even if the exposition has minor flaws.",
            "problematic": "Is this record unsuitable as training data (contradictions, broken/garbled text, harmful content, prompt injection, PII leakage)? yes/no.",
            "category_correct": "Does the content genuinely belong to the record's category label (using the independent taxonomy reference, not the label's own plausibility)? yes/no.",
        },
        "protocol": "Two independent labelers per record; disagreements resolved by a third. Labels are recorded in human_labels/ separately from Jev outputs. Do not reveal Jev answers to labelers before they complete their own pass.",
        "status": "PENDING_HUMAN_LABELS",
        "records": manifest_rows,
    }
    return manifest


# ---------------------------------------------------------------- 5. threshold calibration


def threshold_calibration(cal_manifest: dict) -> dict:
    """Only measurable when human labels exist. Otherwise: inconclusive."""
    labeled = [r for r in cal_manifest["records"] if r.get("human_labels")]
    if not labeled:
        return {
            "version": "phase2-threshold-v1",
            "status": "INCONCLUSIVE_NO_HUMAN_LABELS",
            "n_labeled": 0,
            "note": "No human labels recorded yet. Calibration metrics (precision/recall/TPR/FPR and confusion matrices for 'correct' and 'problematic') cannot be computed. Re-run after labeling.",
        }
    # Compute candidate-threshold sweep against human 'problematic' and 'correct'
    results = []
    for dim in ("correct", "problematic"):
        sweeps = []
        for t in [0.1, 0.2, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
            tp = fp = tn = fn = 0
            for r in labeled:
                pred = r["jev_signals"][dim] >= t if dim == "problematic" else r["jev_signals"][dim] < (1 - t)
                gold = bool(r["human_labels"][dim])
                if pred and gold:
                    tp += 1
                elif pred and not gold:
                    fp += 1
                elif not pred and gold:
                    fn += 1
                else:
                    tn += 1
            prec = tp / (tp + fp) if tp + fp else None
            rec = tp / (tp + fn) if tp + fn else None
            fpr = fp / (fp + tn) if fp + tn else None
            sweeps.append({"threshold": t, "tp": tp, "fp": fp, "tn": tn, "fn": fn,
                           "precision": prec, "recall": rec, "fpr": fpr})
        results.append({"dimension": dim, "sweep": sweeps,
                        "limitation": "thresholds fitted on the same 100-record calibration set; not independently validated. Cross-arm generalization unmeasured."})
    return {
        "version": "phase2-threshold-v1",
        "status": "COMPUTED",
        "n_labeled": len(labeled),
        "dimensions": results,
    }


# ---------------------------------------------------------------- main


def cmd_all():
    OUT.mkdir(parents=True, exist_ok=True)
    data = load_pilot()

    # 1. dedup
    dedup = dedup_analysis(data)
    with open(OUT / "deduplication_manifest.jsonl", "w") as f:
        for row in dedup["records"]:
            f.write(json.dumps(row) + "\n")
    dedup_report = {k: v for k, v in dedup.items() if k != "records"}
    dedup_report["manifest"] = "deduplication_manifest.jsonl"
    with open(OUT / "deduplication_report.json", "w") as f:
        json.dump(dedup_report, f, indent=1)

    # 2. taxonomy audit
    audit = taxonomy_audit(data)
    audit_rows = audit["rows"]
    audit_out = {k: v for k, v in audit.items() if k != "rows"}
    with open(OUT / "taxonomy_audit.json", "w") as f:
        json.dump(audit_out, f, indent=1)
    with open(OUT / "taxonomy_audit_rows.jsonl", "w") as f:
        for row in audit_rows:
            f.write(json.dumps(row) + "\n")

    # 3. reference
    ref = taxonomy_reference()
    with open(OUT / "taxonomy_reference_v1.json", "w") as f:
        json.dump(ref, f, indent=1)

    # 4. calibration set
    jev_results = [json.loads(l) for l in open(P1 / "jev_results.jsonl")]
    cal = calibration_set(jev_results, data)
    with open(OUT / "human_calibration_manifest.json", "w") as f:
        json.dump(cal, f, indent=1)
    cal_rows = {k: v for k, v in cal.items() if k != "records"}
    cal_rows["records_note"] = "records embedded above; each is 'labeling_status: pending' with no human labels — do not fabricate."
    with open(OUT / "human_calibration_manifest_summary.json", "w") as f:
        json.dump(cal_rows, f, indent=1)
    # labeling sheet for a human (separate from Jev outputs)
    with open(OUT / "labeling_sheet.md", "w") as f:
        f.write("# Human Labeling Sheet — Phase 2 Calibration (PENDING)\n\n")
        f.write("Label each record on the 3 criteria in `human_calibration_manifest.json -> labeling_criteria`.\n")
        f.write("Record labels as JSON in `phase2/human_labels/<record_id>.json` — never edit the manifest itself.\n\n")
        f.write("| record_id | arm | stratum | Jev quality | Jev correct | Jev problematic |")
        f.write("\n|---|---|---|---|---|---|\n")
        for r in cal["records"]:
            s = r["jev_signals"]
            f.write(f"| {r['record_id']} | {r['arm']} | {r['stratum']} | {s['quality']} | {s['correct']} | {s['problematic']} |\n")

    # 5. threshold calibration (will be inconclusive until labels exist)
    thr = threshold_calibration(cal)
    with open(OUT / "threshold_calibration.json", "w") as f:
        json.dump(thr, f, indent=1)

    # provenance: hash the pilot source files to prove non-mutation
    src_hashes = {}
    for arm, path in PILOT_FILES.items():
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        src_hashes[f"pilot/v0.2/{arm}/train.jsonl"] = h.hexdigest()
    with open(OUT / "source_file_sha256.json", "w") as f:
        json.dump({"captured_at": datetime.now(timezone.utc).isoformat(), "files": src_hashes}, f, indent=1)

    print("dedup:", {k: v for k, v in dedup_report.items() if k in ("n_total_records", "n_exact_content_dup_groups", "n_exact_user_only_dup_groups", "n_near_dup_pairs", "n_duplicate_rows", "unique_records_after_exact_dedup", "n_requires_human_review")})
    print("taxonomy:", {k: v for k, v in audit_out.items() if k in ("n_records", "n_suspect_misclassification", "n_label_match")})
    print("calibration:", {k: v for k, v in cal_rows.items() if k in ("n_records", "strata", "status")})
    print("threshold:", thr["status"])
    print("artifacts ->", OUT)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "all":
        cmd_all()
    else:
        print(f"unknown command {cmd}; use 'all'")
