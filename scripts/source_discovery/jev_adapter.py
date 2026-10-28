"""JEV integration boundary for Source Discovery v1.0.

Reuses the existing JEV quality-filter architecture WITHOUT copying it:
the v0.2 router module is loaded read-only from
experiments/jev-quality-filter-v0.2/router.py via importlib. No JEV code is
duplicated here.

v1.0 scope (hard):
  - implement the boundary + verify the data flow (smoke only),
  - do NOT run JEV over the discovered corpus,
  - do NOT use human labels as a gate.

The v0.2 router consumes STORED JEV signals (correct/quality/problematic/...
noul scores), not raw translation pairs. So this adapter exposes:
  - build_jev_input(record): what a future JEV first-pass would receive,
  - route_with_stored_signals(answers, policy): delegation to the real router,
  - smoke_dataflow(n): end-to-end check with SYNTHETIC stored signals,
    clearly labeled — never a quality claim.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROUTER_PATH = (Path(__file__).resolve().parent.parent.parent
               / "experiments" / "jev-quality-filter-v0.2" / "router.py")


def load_router() -> dict[str, Any]:
    """Load the real v0.2 router read-only. Returns status dict."""
    if not ROUTER_PATH.exists():
        return {"available": False,
                "reason": f"router_not_found:{ROUTER_PATH}"}
    try:
        spec = importlib.util.spec_from_file_location("sd_jev_router_v02",
                                                      ROUTER_PATH)
        if spec is None or spec.loader is None:
            return {"available": False, "reason": "import_spec_failed"}
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return {"available": True, "module": mod,
                "formula_version": getattr(mod, "FORMULA_VERSION", ""),
                "policies": dict(getattr(mod, "POLICIES", {})),
                "router_path": str(ROUTER_PATH)}
    except Exception as exc:  # noqa: BLE001 — boundary must report, not crash
        return {"available": False,
                "reason": f"{type(exc).__name__}: {str(exc)[:300]}"}


def build_jev_input(record: dict[str, Any]) -> dict[str, Any]:
    """Map a normalized translation record to a future JEV first-pass input.

    No JEV call is made here. The mapping reuses the AI-2 content convention
    (user=source text, assistant=target text) so both reviewers see identical
    content bytes; taxonomy labels carry direction + domain, never scores.
    """
    return {
        "user": record.get("source", ""),
        "assistant": record.get("target", ""),
        "claimed_category": record.get("source_id", ""),
        "claimed_subcategory": (
            f"{record.get('source_lang', '')}→{record.get('target_lang', '')}"
            f":{record.get('quality_status', '')}"),
        "content_sha256": record.get("content_sha256", ""),
        "record_id": record.get("id", ""),
    }


def route_with_stored_signals(answers: dict[str, Any],
                              policy: str = "balanced") -> dict[str, Any]:
    """Route one record's STORED JEV answers via the real v0.2 router."""
    loaded = load_router()
    if not loaded.get("available"):
        return {"band": "N/A", "path": "jev_boundary_unavailable",
                "quarantine": True,
                "reason": loaded.get("reason", "unknown")}
    mod = loaded["module"]
    if policy not in mod.POLICIES:
        return {"band": "N/A", "path": "jev_unknown_policy",
                "quarantine": True, "reason": f"policy={policy!r}"}
    try:
        routed = mod.route_record(answers, policy)
        routed["formula_version"] = mod.FORMULA_VERSION
        routed["policy"] = policy
        return routed
    except Exception as exc:  # noqa: BLE001 — fail closed
        return {"band": "N/A", "path": "jev_router_error",
                "quarantine": True,
                "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _synthetic_answers(kind: str) -> dict[str, Any]:
    """Clearly-labeled SYNTHETIC JEV signals for smoke only (not quality)."""
    if kind == "high":
        c, q, p, a, k, t = 0.95, 3.6, 0.02, 0.92, 0.90, 3.5
    elif kind == "low":
        c, q, p, a, k, t = 0.20, 1.0, 0.60, 0.25, 0.30, 1.0
    else:
        c, q, p, a, k, t = 0.62, 2.4, 0.25, 0.60, 0.58, 2.2
    probs = {"0": 0.1, "1": 0.1, "2": 0.15, "3": 0.3, "4": 0.35}
    return {
        "correct": {"noul": c},
        "quality": {"score": q, "probabilities": dict(probs)},
        "problematic": {"noul": p},
        "adherence": {"noul": a},
        "consistent_category": {"noul": k},
        "training_value": {"score": t, "probabilities": dict(probs)},
    }


def smoke_dataflow(n_per_band: int = 2) -> dict[str, Any]:
    """Verify router data flow with synthetic signals. Smoke only.

    Returns per-policy band distribution over synthetic HIGH/AMBIGUOUS/LOW
    inputs. Labels every input synthetic_smoke=true. Makes no quality claim.
    """
    loaded = load_router()
    if not loaded.get("available"):
        return {"ok": False, "synthetic_smoke": True,
                "reason": loaded.get("reason")}
    mod = loaded["module"]
    kinds = (["high"] * n_per_band + ["ambiguous"] * n_per_band
             + ["low"] * n_per_band)
    per_policy: dict[str, Any] = {}
    for policy in mod.POLICIES:
        bands = [mod.route_record(_synthetic_answers(k), policy)["band"]
                 for k in kinds]
        per_policy[policy] = {
            "n_inputs": len(kinds),
            "bands": bands,
            "formula_version": mod.FORMULA_VERSION,
        }
    return {"ok": True, "synthetic_smoke": True,
            "note": "synthetic signals only — verifies wiring, not quality",
            "formula_version": loaded["formula_version"],
            "policies": loaded["policies"],
            "per_policy": per_policy}
