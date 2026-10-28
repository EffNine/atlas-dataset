#!/usr/bin/env python3
"""Adaptive JEV confidence router for `jev-quality-filter-v0.2`.

Experiment-only deterministic routing function. No I/O, no network, no Atlas
access. Given one record's STORED JEV signals it computes a single confidence
value C in [0, 1] and maps it to a routing band (HIGH / LOW / AMBIGUOUS).

EXACT FORMULA (v0.2-router-v1; also documented in README.md and REPORT.md):

Inputs (from the stored JEV first pass; none are recomputed here):
  c  = correct.noul                  in [0, 1]   (higher = more correct)
  q  = quality.score                 in [0, 4];  qn = q / 4
  p  = problematic.noul              in [0, 1]   (higher = more problematic)
  a  = adherence.noul                in [0, 1]
  k  = consistent_category.noul      in [0, 1]   (category consistency)
  t  = training_value.score          in [0, 4];  tn = t / 4
  qs = 1 - max(quality.probabilities)            (distributional uncertainty)
  ts = 1 - max(training_value.probabilities)     (distributional uncertainty)

Derived components:
  S = 0.40*c + 0.25*qn + 0.15*a + 0.10*k + 0.10*tn   (positive support)
  U = (qs + ts) / 2                                   (uncertainty)
  D = (|c - qn| + |c - (1-p)| + |c - a| + |c - k|) / 4 (cross-dimension
      disagreement: how much JEV's own dimensions contradict each other)
  C_raw = S - 0.50*p - 0.25*U - 0.25*D
  C = clip(C_raw, 0, 1), rounded to 4 decimals.

Routing for a policy with thresholds (tau_lo, tau_hi), tau_lo < tau_hi:
  deterministic INVALID            -> REJECT   (path deterministic_gate)
  JEV status != "ok"               -> AMBIGUOUS (path jev_error_unresolved)
  any required signal missing /
    malformed / out of range       -> AMBIGUOUS (path jev_signal_degraded;
                                     C is None; incomplete evidence is never
                                     auto-routed in either direction)
  p >= 0.80                        -> LOW      (path problematic_rail_quarantine;
                                     extreme-risk rail, overrides C)
  C >= tau_hi                      -> HIGH     (auto ACCEPT)
  C <= tau_lo                      -> LOW      (auto REJECT + quarantine)
  otherwise                        -> AMBIGUOUS (blind AI-2 review)

Boundary semantics: equality routes outward (>= HIGH, <= LOW). A value cannot
satisfy both because tau_lo < tau_hi is enforced at policy definition.

POLICIES (operating intents only -- NOT accuracy/optimality claims; the
thresholds are uncalibrated round-number operating points fixed BEFORE the
v0.2 run, never tuned against human labels or JEV outcomes):
  conservative = (tau_lo 0.45, tau_hi 0.75): widest escalation band; hardest
      to auto-accept, easiest to quarantine. Escalates most to AI-2.
  balanced     = (tau_lo 0.35, tau_hi 0.65): middle operating point.
  aggressive   = (tau_lo 0.25, tau_hi 0.55): narrowest escalation band; most
      auto-routing, least AI-2 spend.

WEIGHT RATIONALE (documented judgment, not a fitted result): correctness
dominates (0.40) because it is JEV's primary verdict-like signal; quality
(0.25) is second; adherence/category-consistency/training-value are small
stabilisers (0.15/0.10/0.10). The problematic penalty (0.50) is the largest
single term so high-risk records cannot score high. Uncertainty and
disagreement penalties (0.25 each) are deliberately smaller than the
problematic penalty: they express doubt, not danger.

NON-CLAIMS: C is a routing convenience, not a probability of correctness.
No precision/recall/accuracy may be computed from it: there is no
independent ground truth in this experiment and human labels are never used.
"""

from __future__ import annotations

FORMULA_VERSION = "v0.2-router-v1"

POLICIES: dict[str, dict[str, float]] = {
    "conservative": {"tau_lo": 0.45, "tau_hi": 0.75},
    "balanced": {"tau_lo": 0.35, "tau_hi": 0.65},
    "aggressive": {"tau_lo": 0.25, "tau_hi": 0.55},
}

for _name, _t in POLICIES.items():
    assert _t["tau_lo"] < _t["tau_hi"], f"policy {_name}: need tau_lo < tau_hi"

PROBLEMATIC_RAIL = 0.80  # p >= rail forces LOW regardless of C

REQUIRED_NOUL = ("correct", "adherence", "consistent_category", "problematic")
REQUIRED_SCORE = ("quality", "training_value")


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _as_float(x) -> float | None:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    return None


def extract_signals(answers: dict) -> tuple[dict | None, str | None]:
    """Validate stored JEV answers and extract numeric signals.

    Returns (signals, None) on success or (None, reason) when any required
    signal is missing, malformed, or out of range. `reason` names the first
    offending field so failures are inspectable.
    """
    if not isinstance(answers, dict):
        return None, "answers_not_a_dict"
    try:
        out: dict[str, float] = {}
        for key in REQUIRED_NOUL:
            node = answers.get(key)
            raw_v = node.get("noul") if isinstance(node, dict) else None
            v = _as_float(raw_v)
            if v is None or not 0.0 <= v <= 1.0:
                return None, f"bad_noul:{key}={raw_v!r}"
            out[key] = v
        for key in REQUIRED_SCORE:
            node = answers.get(key)
            raw_v = node.get("score") if isinstance(node, dict) else None
            v = _as_float(raw_v)
            if v is None or not 0.0 <= v <= 4.0:
                return None, f"bad_score:{key}={raw_v!r}"
            out[key] = v
            probs = node.get("probabilities") if isinstance(node, dict) else None
            if not isinstance(probs, dict) or not probs:
                return None, f"bad_probabilities:{key}"
            tops: list[float] = []
            for x in probs.values():
                if not _is_num(x):
                    return None, f"bad_probabilities:{key}"
                tops.append(float(x))
            top = max(tops)
            if not isinstance(top, float) or not 0.0 <= top <= 1.0:
                return None, f"bad_probabilities:{key}"
            out[key + "_top"] = top
    except AttributeError:
        return None, "answers_malformed"
    return out, None


def confidence_from_signals(sig: dict) -> dict:
    """Pure confidence computation. `sig` must come from extract_signals."""
    c = sig["correct"]
    qn = sig["quality"] / 4.0
    p = sig["problematic"]
    a = sig["adherence"]
    k = sig["consistent_category"]
    tn = sig["training_value"] / 4.0
    qs = 1.0 - sig["quality_top"]
    ts = 1.0 - sig["training_value_top"]
    support = 0.40 * c + 0.25 * qn + 0.15 * a + 0.10 * k + 0.10 * tn
    uncertainty = (qs + ts) / 2.0
    disagreement = (abs(c - qn) + abs(c - (1.0 - p)) + abs(c - a)
                    + abs(c - k)) / 4.0
    raw = support - 0.50 * p - 0.25 * uncertainty - 0.25 * disagreement
    clipped = min(1.0, max(0.0, raw))
    return {
        "C": round(clipped, 4),
        "support": round(support, 4),
        "uncertainty": round(uncertainty, 4),
        "disagreement": round(disagreement, 4),
        "problematic": p,
        "correct": c,
        "quality": sig["quality"],
    }


def route_from_confidence(c_value: float | None, problematic: float | None,
                           policy: str, det_status: str = "VALID",
                           jev_ok: bool = True,
                           degraded_reason: str | None = None) -> dict:
    """Map a confidence value to a band. Pure function; boundary-testable.

    Returns {"band", "path", "quarantine"}. Never raises on numeric input.
    """
    if det_status != "VALID":
        return {"band": "N/A", "path": "deterministic_gate",
                "quarantine": False}
    if not jev_ok:
        return {"band": "N/A", "path": "jev_error_unresolved",
                "quarantine": False}
    if degraded_reason is not None or c_value is None:
        return {"band": "AMBIGUOUS", "path": "jev_signal_degraded",
                "quarantine": False}
    if problematic is not None and problematic >= PROBLEMATIC_RAIL:
        return {"band": "LOW", "path": "problematic_rail_quarantine",
                "quarantine": True}
    t = POLICIES[policy]
    if c_value >= t["tau_hi"]:
        return {"band": "HIGH", "path": "jev_auto_accept",
                "quarantine": False}
    if c_value <= t["tau_lo"]:
        return {"band": "LOW", "path": "jev_auto_reject_quarantine",
                "quarantine": True}
    return {"band": "AMBIGUOUS", "path": "ai2_escalation",
            "quarantine": False}


def route_record(answers: dict, policy: str, det_status: str = "VALID",
                 jev_ok: bool = True) -> dict:
    """End-to-end deterministic routing for one record's stored JEV answers.

    Returns {"band", "path", "quarantine", "confidence" | None,
    "degraded_reason" | None}. Same input always yields same output.
    """
    if det_status != "VALID":
        return {"band": "N/A", "path": "deterministic_gate",
                "quarantine": False, "confidence": None,
                "degraded_reason": None}
    if not jev_ok:
        return {"band": "N/A", "path": "jev_error_unresolved",
                "quarantine": False, "confidence": None,
                "degraded_reason": None}
    sig, reason = extract_signals(answers)
    if sig is None:
        routed = route_from_confidence(None, None, policy,
                                       degraded_reason=reason)
        routed.update({"confidence": None, "degraded_reason": reason})
        return routed
    conf = confidence_from_signals(sig)
    routed = route_from_confidence(conf["C"], conf["problematic"], policy)
    routed.update({"confidence": conf, "degraded_reason": None})
    return routed


def jev_lean_stance(correct: float, quality: float,
                    problematic: float) -> str:
    """Heuristic stance of JEV's continuous signal on an escalated record.

    Reused VERBATIM from v0.1 for comparability. Analysis convenience ONLY:
    not a routing decision, not a gate, and NOT ground truth. Used solely to
    give the disagreement-handling experiment a JEV side to compare against
    the blind AI-2 verdict.
    """
    if correct < 0.6 or quality < 2.5 or problematic >= 0.30:
        return "REJECT-lean"
    return "ACCEPT-lean"


def final_for(band: str, ai2_verdict: str | None) -> tuple[str, str, bool]:
    """Primary final-decision rule. Returns (final, path, quarantine).

    Fail-closed: any AI-2 verdict other than ACCEPT/REJECT -- including
    AMBIGUOUS, ERROR, and missing (None) -- yields AMBIGUOUS, never ACCEPT.
    """
    if band == "HIGH":
        return "ACCEPT", "jev_auto_accept", False
    if band == "LOW":
        return "REJECT", "jev_auto_reject_quarantine", True
    if ai2_verdict == "ACCEPT":
        return "ACCEPT", "ai2_accept", False
    if ai2_verdict == "REJECT":
        return "REJECT", "ai2_reject", False
    return "AMBIGUOUS", "ai2_unresolved", True


DISAGREEMENT_MATRIX = {
    ("ACCEPT-lean", "ACCEPT"): ("ACCEPT", "agree_accept"),
    ("REJECT-lean", "REJECT"): ("REJECT", "agree_reject"),
    ("ACCEPT-lean", "REJECT"): ("AMBIGUOUS", "disagree_quarantine"),
    ("REJECT-lean", "ACCEPT"): ("AMBIGUOUS", "disagree_quarantine"),
}


def resolve_disagreement(jev_stance: str | None,
                         ai2_verdict: str | None) -> tuple[str, str, bool]:
    """Conservative disagreement resolution (second experiment).

    Agreement passes through; ANY disagreement quarantines as AMBIGUOUS
    (no winner is selected); AI-2 AMBIGUOUS/ERROR/missing fails safe to
    AMBIGUOUS. Returns (final, path, quarantine).
    """
    if ai2_verdict not in ("ACCEPT", "REJECT"):
        return "AMBIGUOUS", "disagree_fail_safe", True
    if not isinstance(jev_stance, str):
        return "AMBIGUOUS", "disagree_fail_safe", True
    key = (jev_stance, ai2_verdict)
    if key in DISAGREEMENT_MATRIX:
        final, path = DISAGREEMENT_MATRIX[key]
        return final, path, final != "ACCEPT"
    return "AMBIGUOUS", "disagree_fail_safe", True
