"""Deterministic-routing, boundary, malformed-signal, and matrix tests."""
import copy

import router


def good_answers(**over):
    base = {
        "correct": {"noul": 0.90},
        "quality": {"score": 3.20,
                    "probabilities": {"2": 0.05, "3": 0.60, "4": 0.35}},
        "adherence": {"noul": 0.85},
        "consistent_category": {"noul": 0.95},
        "problematic": {"noul": 0.10},
        "training_value": {"score": 2.80,
                           "probabilities": {"2": 0.10, "3": 0.80,
                                             "4": 0.10}},
    }
    for k, v in over.items():
        base[k] = v
    return base


def test_confidence_worked_example():
    """Hand-computed: S=0.8525 U=0.30 D=0.05 C=0.7150. Guards the formula."""
    sig, reason = router.extract_signals(good_answers())
    assert reason is None
    assert sig is not None
    conf = router.confidence_from_signals(sig)
    assert conf["support"] == 0.8525
    assert conf["uncertainty"] == 0.3
    assert conf["disagreement"] == 0.05
    assert conf["C"] == 0.715


def test_deterministic_same_input_same_output():
    ans = good_answers()
    for policy in ("conservative", "balanced", "aggressive"):
        first = router.route_record(ans, policy)
        second = router.route_record(copy.deepcopy(ans), policy)
        assert first == second


def test_policy_divergence_on_mid_record():
    """C=0.715 is HIGH for balanced/aggressive, AMBIGUOUS for conservative."""
    assert router.route_record(good_answers(), "conservative")["band"] \
        == "AMBIGUOUS"
    assert router.route_record(good_answers(), "balanced")["band"] == "HIGH"
    assert router.route_record(good_answers(), "aggressive")["band"] == "HIGH"


def test_boundaries_route_outward():
    for policy, t in router.POLICIES.items():
        hi = router.route_from_confidence(t["tau_hi"], 0.1, policy)
        lo = router.route_from_confidence(t["tau_lo"], 0.1, policy)
        assert hi["band"] == "HIGH", policy
        assert lo["band"] == "LOW", policy
        mid = router.route_from_confidence(
            (t["tau_lo"] + t["tau_hi"]) / 2.0, 0.1, policy)
        assert mid["band"] == "AMBIGUOUS", policy
        eps = 1e-9
        assert router.route_from_confidence(
            t["tau_hi"] - eps, 0.1, policy)["band"] == "AMBIGUOUS", policy
        assert router.route_from_confidence(
            t["tau_lo"] + eps, 0.1, policy)["band"] == "AMBIGUOUS", policy


def test_problematic_rail_overrides_high_confidence():
    for policy in router.POLICIES:
        r = router.route_from_confidence(0.99, 0.80, policy)
        assert r["band"] == "LOW"
        assert r["path"] == "problematic_rail_quarantine"
        assert r["quarantine"] is True
        r2 = router.route_from_confidence(0.99, 0.799, policy)
        assert r2["band"] == "HIGH"


def test_deterministic_invalid_never_reaches_ai():
    for policy in router.POLICIES:
        r = router.route_record(good_answers(), policy, det_status="INVALID")
        assert (r["band"], r["path"]) == ("N/A", "deterministic_gate")
        final, _path, _q = router.final_for(r["band"], None)
        assert final == "AMBIGUOUS"  # N/A band takes no auto path


def test_jev_error_never_auto_routes():
    for policy in router.POLICIES:
        r = router.route_record(good_answers(), policy, jev_ok=False)
        assert r["path"] == "jev_error_unresolved"
        assert r["confidence"] is None


def _assert_degraded(answers):
    for policy in router.POLICIES:
        r = router.route_record(answers, policy)
        assert r["band"] == "AMBIGUOUS", (policy, r)
        assert r["path"] == "jev_signal_degraded", (policy, r)
        assert r["confidence"] is None
        assert r["degraded_reason"]


def test_missing_signal_escalates():
    ans = good_answers()
    del ans["correct"]
    _assert_degraded(ans)


def test_malformed_types_escalate():
    _assert_degraded(good_answers(correct={"noul": "high"}))
    _assert_degraded(good_answers(correct={"noul": None}))
    _assert_degraded(good_answers(correct={"noul": True}))  # bool is not num
    _assert_degraded(good_answers(quality={"score": 3.0}))  # no probs
    _assert_degraded(good_answers(
        quality={"score": 3.0, "probabilities": {}}))
    _assert_degraded(good_answers(
        quality={"score": 3.0, "probabilities": {"3": "lots"}}))
    _assert_degraded("not-a-dict")
    _assert_degraded(None)


def test_out_of_range_escalates():
    _assert_degraded(good_answers(correct={"noul": 1.5}))
    _assert_degraded(good_answers(correct={"noul": -0.1}))
    _assert_degraded(good_answers(quality={
        "score": 4.5, "probabilities": {"4": 1.0}}))
    _assert_degraded(good_answers(problematic={"noul": 2.0}))


def test_degraded_never_auto_accepts_or_rejects():
    ans = {"correct": {"noul": 0.99}}  # high-looking but incomplete
    for policy in router.POLICIES:
        r = router.route_record(ans, policy)
        final, _p, _q = router.final_for(r["band"], "ACCEPT")
        # band is AMBIGUOUS so the final follows AI-2, never JEV auto-accept
        assert r["band"] == "AMBIGUOUS"
        assert final == "ACCEPT"  # only because AI-2 said so here


def test_final_for_fail_closed():
    assert router.final_for("HIGH", None) == ("ACCEPT", "jev_auto_accept",
                                              False)
    assert router.final_for("LOW", None) == ("REJECT",
                                             "jev_auto_reject_quarantine",
                                             True)
    for verdict in (None, "AMBIGUOUS", "ERROR", "GARBAGE"):
        assert router.final_for("AMBIGUOUS", verdict) == (
            "AMBIGUOUS", "ai2_unresolved", True)
    assert router.final_for("AMBIGUOUS", "ACCEPT")[0] == "ACCEPT"
    assert router.final_for("AMBIGUOUS", "REJECT")[0] == "REJECT"


def test_jev_lean_stance_matches_v01_heuristic():
    assert router.jev_lean_stance(0.5, 3.5, 0.1) == "REJECT-lean"
    assert router.jev_lean_stance(0.9, 2.0, 0.1) == "REJECT-lean"
    assert router.jev_lean_stance(0.9, 3.0, 0.30) == "REJECT-lean"
    assert router.jev_lean_stance(0.9, 3.0, 0.1) == "ACCEPT-lean"
    assert router.jev_lean_stance(0.6, 2.5, 0.29) == "ACCEPT-lean"


def test_disagreement_matrix_no_winner_selected():
    assert router.resolve_disagreement("ACCEPT-lean", "ACCEPT") == (
        "ACCEPT", "agree_accept", False)
    assert router.resolve_disagreement("REJECT-lean", "REJECT") == (
        "REJECT", "agree_reject", True)
    # disagreements quarantine -- neither side wins
    assert router.resolve_disagreement("ACCEPT-lean", "REJECT") == (
        "AMBIGUOUS", "disagree_quarantine", True)
    assert router.resolve_disagreement("REJECT-lean", "ACCEPT") == (
        "AMBIGUOUS", "disagree_quarantine", True)
    # fail-safe on anything unresolved
    for bad in ("AMBIGUOUS", "ERROR", None, "GARBAGE"):
        assert router.resolve_disagreement("ACCEPT-lean", bad) == (
            "AMBIGUOUS", "disagree_fail_safe", True)
        assert router.resolve_disagreement("REJECT-lean", bad) == (
            "AMBIGUOUS", "disagree_fail_safe", True)
    assert router.resolve_disagreement(None, "ACCEPT") == (
        "AMBIGUOUS", "disagree_fail_safe", True)


def test_confidence_clipped_to_unit_interval():
    extreme = good_answers(
        correct={"noul": 0.0},
        quality={"score": 0.0, "probabilities": {"0": 0.34, "1": 0.33,
                                                 "2": 0.33}},
        adherence={"noul": 0.0},
        consistent_category={"noul": 0.0},
        problematic={"noul": 1.0},
        training_value={"score": 0.0, "probabilities": {"0": 1.0}})
    sig, _ = router.extract_signals(extreme)
    assert sig is not None
    c = router.confidence_from_signals(sig)["C"]
    assert 0.0 <= c <= 1.0
    top = good_answers(
        correct={"noul": 1.0},
        quality={"score": 4.0, "probabilities": {"4": 1.0}},
        adherence={"noul": 1.0},
        consistent_category={"noul": 1.0},
        problematic={"noul": 0.0},
        training_value={"score": 4.0, "probabilities": {"4": 1.0}})
    sig2, _ = router.extract_signals(top)
    assert sig2 is not None
    c2 = router.confidence_from_signals(sig2)["C"]
    assert 0.0 <= c2 <= 1.0
