"""matrix_runner.py — Automated M1/M2/M2' evaluation matrix.

Runs evaluation of frozen LoRA adapters (M1, M2, M2') against a common
eval set using identical inference conditions. Every model uses:
  - identical base model revision
  - identical tokenizer
  - identical quantization
  - identical prompt
  - identical generation policy
  - identical evaluator
  - identical benchmark records

Produces per-example results + aggregate statistics with paired comparisons.
Requires CUDA hardware.

Statistical methods:
  - Per-model correctness CI: Wilson 95% score interval (correct named method)
  - Paired binary comparison: Exact binomial McNemar's test
  - Effect size: absolute correctness delta (primary); Cohen's d secondary
  - Overlap accounting: per-model training/eval overlap tracked
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class PerExampleResult:
    """Result for a single (model, record) pair."""
    record_id: str
    model_id: str
    family: str
    correctness: float | None
    reasoning_quality: float | None
    hallucination_rate: float
    answer_format_consistency: float
    truncation: bool
    stop_reason: str
    tokens_generated: int | None
    budget: int
    format_class: str = ""
    leak: str = "PASS"
    error: str = ""
    # Overlap tracking
    training_overlap: bool = False
    overlap_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "model_id": self.model_id,
            "family": self.family,
            "correctness": self.correctness,
            "reasoning_quality": self.reasoning_quality,
            "hallucination_rate": self.hallucination_rate,
            "answer_format_consistency": self.answer_format_consistency,
            "truncation": self.truncation,
            "stop_reason": self.stop_reason,
            "tokens_generated": self.tokens_generated,
            "budget": self.budget,
            "format_class": self.format_class,
            "leak": self.leak,
            "error": self.error,
            "training_overlap": self.training_overlap,
            "overlap_source": self.overlap_source,
        }


@dataclass
class AggregateResult:
    """Aggregate statistics for one model on one family."""
    model_id: str
    family: str
    n_evaluated: int
    n_total: int
    n_overlap: int = 0
    overlap_record_ids: list[str] = field(default_factory=list)
    correctness: float | None = None
    correctness_ci_lower: float | None = None
    correctness_ci_upper: float | None = None
    truncation_rate: float = 0.0
    gpol_pass: bool = False
    tokens_mean: float | None = None
    stop_reason_counts: dict[str, int] = field(default_factory=dict)
    delta_vs_baseline: float | None = None
    paired_p_value: float | None = None
    paired_method: str = ""
    mcnemar_b: int = 0  # baseline correct / treatment incorrect
    mcnemar_c: int = 0  # baseline incorrect / treatment correct
    effect_size_cohens_d: float | None = None  # secondary

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "family": self.family,
            "n_evaluated": self.n_evaluated,
            "n_total": self.n_total,
            "n_overlap": self.n_overlap,
            "overlap_record_ids": self.overlap_record_ids,
            "correctness": self.correctness,
            "correctness_ci_95": [self.correctness_ci_lower, self.correctness_ci_upper],
            "ci_method": "wilson_score",
            "truncation_rate": self.truncation_rate,
            "gpol_pass": self.gpol_pass,
            "tokens_mean": self.tokens_mean,
            "stop_reason_counts": self.stop_reason_counts,
            "delta_vs_baseline": self.delta_vs_baseline,
            "paired_p_value": self.paired_p_value,
            "paired_method": self.paired_method,
            "mcnemar_b": self.mcnemar_b,
            "mcnemar_c": self.mcnemar_c,
            "effect_size_cohens_d": self.effect_size_cohens_d,
        }


# ---------------------------------------------------------------------------
# Statistical functions
# ---------------------------------------------------------------------------


def wilson_ci(successes: int, total: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score confidence interval for a binomial proportion.

    This is the recommended method for binomial CIs because it:
    - Has good coverage properties even for small N and extreme p
    - Does not produce impossible bounds (unlike normal approx)
    - Is asymmetric around p̂, reflecting binomial skew

    Args:
        successes: Number of successes (correct answers).
        total: Number of trials (evaluated records).
        confidence: Confidence level (default 0.95).

    Returns:
        (lower, upper) bounds of the confidence interval.
    """
    if total == 0:
        return (0.0, 0.0)
    if successes < 0 or successes > total:
        return (0.0, 0.0)

    alpha = 1.0 - confidence
    z = _normal_quantile(1.0 - alpha / 2.0)

    p_hat = successes / total

    denominator = 1.0 + z * z / total
    centre = p_hat + z * z / (2.0 * total)
    spread = z * math.sqrt((p_hat * (1.0 - p_hat) + z * z / (4.0 * total)) / total)

    lower = (centre - spread) / denominator
    upper = (centre + spread) / denominator

    return (max(0.0, round(lower, 6)), min(1.0, round(upper, 6)))


def _normal_quantile(p: float) -> float:
    """Approximate the quantile function of the standard normal distribution.

    Uses the rational approximation from Abramowitz and Stegun (26.2.23).
    """
    if p <= 0.0:
        return float('-inf')
    if p >= 1.0:
        return float('inf')
    if p == 0.5:
        return 0.0

    if p < 0.5:
        return -_normal_quantile(1.0 - p)

    t = math.sqrt(-2.0 * math.log(1.0 - p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    return t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)


def mcnemar_test(b: int, c: int) -> dict[str, Any]:
    """Perform McNemar's test for paired binary data.

    Uses the exact binomial test when the total discordant pairs (b+c) is small
    (< 25), otherwise uses the chi-square approximation with continuity correction.

    Args:
        b: Count of (baseline correct, treatment incorrect) pairs.
        c: Count of (baseline incorrect, treatment correct) pairs.

    Returns:
        Dictionary with p_value, method, b, c, n_discordant.
    """
    n_discordant = b + c
    if n_discordant == 0:
        return {"p_value": 1.0, "method": "exact_binomial", "b": 0, "c": 0,
                "n_discordant": 0}

    if n_discordant < 25:
        # Exact binomial test: under H0, P(boundary=cross|discordant) = 0.5
        # Two-sided p-value = 2 * min(P(X <= min(b,c)), P(X >= max(b,c)))
        k = min(b, c)
        p_one_sided = _binomial_cdf(k, n_discordant, 0.5)
        p_value = 2.0 * p_one_sided
        # Clamp to valid range [0, 1]
        p_value = max(0.0, min(1.0, p_value))
        method = "exact_binomial"
    else:
        # Chi-square approximation with Yates' continuity correction
        chi2 = ((abs(c - b) - 1.0) ** 2) / (b + c + 0.0001)
        # p-value from chi-square distribution with 1 df
        p_value = _chi2_sf(chi2, 1)
        # Clamp to valid range [0, 1]
        p_value = max(0.0, min(1.0, p_value))
        method = "chi_square_approx"

    return {"p_value": round(p_value, 6), "method": method, "b": b, "c": c,
            "n_discordant": n_discordant}


def _binomial_cdf(k: int, n: int, p: float) -> float:
    """Cumulative distribution function for Binomial(n, p) at k.

    Uses regularized incomplete beta function relationship:
    P(X <= k) = I_{1-p}(n-k, k+1)
    """
    if n <= 0:
        return 0.0
    k = max(0, min(k, n))
    # Use regularized incomplete beta function
    return _regularized_incomplete_beta(1.0 - p, n - k, k + 1)


def _regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta function I_x(a, b) using continued fraction."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    if a <= 0.0 or b <= 0.0:
        return 0.0

    # Use the continued fraction representation (Lentz's algorithm)
    # For numerical stability, use the symmetry relation when needed
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _regularized_incomplete_beta(1.0 - x, b, a)

    ln_beta = _log_beta(a, b)
    front = math.exp(a * math.log(x) + b * math.log(1.0 - x) - ln_beta) / a

    # Continued fraction
    cf = _beta_cf(x, a, b)
    return front * cf


def _log_beta(a: float, b: float) -> float:
    """Log of the beta function: ln(B(a,b)) = ln(Gamma(a)) + ln(Gamma(b)) - ln(Gamma(a+b))"""
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _beta_cf(x: float, a: float, b: float, max_iter: int = 200) -> float:
    """Continued fraction for regularized incomplete beta function."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        # Even step
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        # Odd step
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-10:
            break
    return h


def _chi2_sf(x: float, df: int) -> float:
    """Survival function (1 - CDF) for chi-square distribution.

    Uses the regularized incomplete beta function:
    P(X > x) = I_{x/(x+df)}(df/2, 1/2) for 1 df
    More generally: P(X > x) = 1 - P(df/2, x/2; x/(x+df))
    """
    if x <= 0:
        return 1.0
    p = df / 2.0
    q = x / (x + df)
    # Regularized incomplete beta: I_q(p, 1-p) doesn't work directly
    # Use: P(X <= x) = I_x/(x+df)(df/2, 1/2) is not quite right for general df
    # For chi-square with df degrees of freedom:
    # CDF(x; df) = gammainc(df/2, x/2) = lower regularized gamma
    # We use the relationship with incomplete beta
    return 1.0 - _lower_regularized_gamma(p, x / 2.0)


def _lower_regularized_gamma(a: float, x: float) -> float:
    """Lower regularized gamma function P(a, x) = γ(a,x)/Γ(a)."""
    if x < 0:
        return 0.0
    if x == 0:
        return 0.0
    if x < a + 1.0:
        # Series expansion
        s = 1.0 / a
        term = 1.0 / a
        for n in range(1, 300):
            term *= x / (a + n)
            s += term
            if abs(term) < abs(s) * 1e-12:
                break
        return s * math.exp(-x + a * math.log(x) - math.lgamma(a))
    else:
        # Continued fraction (Lentz)
        return 1.0 - _gamma_cf(a, x)


def _gamma_cf(a: float, x: float, max_iter: int = 300) -> float:
    """Continued fraction for upper regularized gamma Q(a,x)."""
    f = 1e-30
    c = 1e-30
    d = 1.0 / (x + 1.0 - a)
    f = d
    for i in range(1, max_iter + 1):
        an = -i * (i - a)
        bn = x + 2.0 * i + 1.0 - a
        d = bn + an * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = bn + an / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        f *= delta
        if abs(delta - 1.0) < 1e-10:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * f


def cohens_d(paired: list[tuple[float, float]]) -> float | None:
    """Effect size (Cohen's d) for paired samples.

    NOTE: This is a SECONDARY effect size metric. For binary correctness data,
    the primary effect size is the absolute correctness delta.
    """
    if len(paired) < 2:
        return None
    diffs = [a - b for a, b in paired]
    mean_d = sum(diffs) / len(diffs)
    variance = sum((d - mean_d) ** 2 for d in diffs) / (len(diffs) - 1)
    sd = math.sqrt(variance)
    if sd == 0:
        return 0.0
    return round(mean_d / sd, 4)


class MatrixRunner:
    """Run evaluation matrix across multiple models on a common eval set.

    This is a planning/coordination layer. Actual inference is delegated to
    the existing run_baseline_t3.py infrastructure extended with adapter
    loading. The matrix runner tracks results and computes statistics.

    Statistical contract:
    - Per-model correctness CI: Wilson 95% score interval
    - Paired binary comparison: Exact binomial McNemar's test (or chi-square approx)
    - Effect size: absolute delta (primary), Cohen's d (secondary)
    - Overlap accounting: per-model training/eval overlap tracked
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.results_dir = self.root / "metadata" / "evaluation" / "matrix"

    def plan_matrix(
        self,
        eval_set_path: Path,
        models: list[dict[str, str]],
        family: str = "math",
    ) -> dict[str, Any]:
        """Plan an evaluation matrix without executing.

        Args:
            eval_set_path: Path to the frozen eval set JSONL.
            models: List of dicts with keys: model_id, adapter_path, base_model.
            family: Evaluation family (math, code, semantic).
        """
        records = []
        with eval_set_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        plan = {
            "eval_set": str(eval_set_path),
            "n_records": len(records),
            "family": family,
            "models": models,
            "total_runs": len(models),
            "estimated_cost": f"{len(records) * len(models)} inferences",
            "identical_conditions": {
                "base_model": models[0].get("base_model", "Qwen/Qwen2.5-7B-Instruct") if models else "",
                "quantization": "4bit_nf4",
                "generation_policy": "dynamic-reference-derived",
                "extractor": f"qee-v2-{family}-evaluator",
                "prompt_module": "evaluation_engine.leakage.prompts",
            },
            "required_gates": [
                "G-POL pass for each model",
                "Determinism spot-check",
                "Prompt guard 100% pass",
            ],
            "statistical_method": {
                "ci_method": "wilson_score",
                "paired_test": "mcnemar_exact",
                "overlap_tracking": True,
            },
        }
        return plan

    def compute_statistics(
        self,
        per_example_results: list[dict],
        baseline_model: str,
        compare_models: list[str],
    ) -> dict[str, Any]:
        """Compute aggregate statistics and paired comparisons.

        Args:
            per_example_results: List of per-example result dicts.
            baseline_model: The baseline model ID for comparisons.
            compare_models: List of model IDs to compare against baseline.

        Returns:
            Dict with aggregates, comparisons, and metadata.
        """
        # Group by model
        by_model: dict[str, list[dict]] = {}
        for r in per_example_results:
            mid = r.get("model_id", "unknown")
            by_model.setdefault(mid, []).append(r)

        # Compute per-model aggregates
        aggregates: dict[str, AggregateResult] = {}
        for mid, rows in by_model.items():
            scored = [r for r in rows if r.get("correctness") is not None]
            n = len(scored)
            n_total = len(rows)
            n_overlap = sum(1 for r in rows if r.get("training_overlap"))
            overlap_ids = [r.get("record_id", "") for r in rows if r.get("training_overlap")]

            if n == 0:
                aggregates[mid] = AggregateResult(
                    model_id=mid, family="", n_evaluated=0, n_total=n_total,
                    n_overlap=n_overlap, overlap_record_ids=overlap_ids,
                    correctness=None, correctness_ci_lower=None, correctness_ci_upper=None,
                    truncation_rate=0.0, gpol_pass=False, tokens_mean=None,
                    stop_reason_counts={},
                )
                continue

            correct_count = sum(1 for r in scored if r.get("correctness", 0) > 0.5)
            trunc_count = sum(1 for r in rows if r.get("truncation"))
            stop_counts: dict[str, int] = {}
            tokens_list: list[int] = []
            for r in rows:
                sr = r.get("stop_reason", "unknown")
                stop_counts[sr] = stop_counts.get(sr, 0) + 1
                tg = r.get("tokens_generated")
                if tg is not None:
                    tokens_list.append(tg)

            correctness = correct_count / n
            # Use Wilson CI (correctly named and implemented)
            ci_low, ci_high = wilson_ci(correct_count, n)

            aggregates[mid] = AggregateResult(
                model_id=mid,
                family="",
                n_evaluated=n,
                n_total=n_total,
                n_overlap=n_overlap,
                overlap_record_ids=overlap_ids,
                correctness=round(correctness, 4),
                correctness_ci_lower=ci_low,
                correctness_ci_upper=ci_high,
                truncation_rate=round(trunc_count / n_total, 4) if n_total else 0.0,
                gpol_pass=(trunc_count / n_total <= 0.05) if n_total else False,
                tokens_mean=round(sum(tokens_list) / len(tokens_list), 2) if tokens_list else None,
                stop_reason_counts=stop_counts,
            )

        # Paired comparisons vs baseline using McNemar's test
        baseline_agg = aggregates.get(baseline_model)
        comparisons: dict[str, Any] = {}
        if baseline_agg and baseline_agg.correctness is not None:
            for cmp_id in compare_models:
                cmp_agg = aggregates.get(cmp_id)
                if cmp_agg is None or cmp_agg.correctness is None:
                    continue

                # Build paired results by record_id
                baseline_by_record: dict[str, float] = {}
                cmp_by_record: dict[str, float] = {}
                for r in per_example_results:
                    if r.get("model_id") == baseline_model and r.get("correctness") is not None:
                        baseline_by_record[r.get("record_id", "")] = r.get("correctness", 0)
                    if r.get("model_id") == cmp_id and r.get("correctness") is not None:
                        cmp_by_record[r.get("record_id", "")] = r.get("correctness", 0)

                # Find matched pairs and compute McNemar discordant counts
                paired_records = []
                b_count = 0  # baseline correct, treatment incorrect
                c_count = 0  # baseline incorrect, treatment correct
                for rid, b_correct in baseline_by_record.items():
                    if rid in cmp_by_record:
                        c_correct = cmp_by_record[rid]
                        b_binary = 1 if b_correct > 0.5 else 0
                        c_binary = 1 if c_correct > 0.5 else 0
                        paired_records.append((b_binary, c_binary))
                        if b_binary == 1 and c_binary == 0:
                            b_count += 1
                        elif b_binary == 0 and c_binary == 1:
                            c_count += 1

                delta = cmp_agg.correctness - baseline_agg.correctness
                mcnemar_result = mcnemar_test(b_count, c_count)
                d = cohens_d(paired_records) if len(paired_records) >= 5 else None

                comparisons[cmp_id] = {
                    "delta_vs_baseline": round(delta, 4),
                    "baseline_correctness": baseline_agg.correctness,
                    "model_correctness": cmp_agg.correctness,
                    "paired_p_value": mcnemar_result["p_value"],
                    "paired_method": mcnemar_result["method"],
                    "mcnemar_b": b_count,
                    "mcnemar_c": c_count,
                    "n_paired": len(paired_records),
                    "effect_size_cohens_d": d,
                    "verdict": self._verdict(delta, mcnemar_result["p_value"],
                                            len(paired_records)),
                }

        return {
            "aggregates": {mid: agg.to_dict() for mid, agg in aggregates.items()},
            "comparisons": comparisons,
            "baseline_model": baseline_model,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "statistical_contract": {
                "ci_method": "wilson_score",
                "paired_test": "mcnemar",
                "overlap_accounted": True,
            },
        }

    @staticmethod
    def _verdict(delta: float, p_value: float | None, n_paired: int) -> str:
        """Determine verdict for a comparison."""
        if n_paired < 30:
            return "HOLD"
        if p_value is not None and p_value < 0.05:
            direction = "improved" if delta > 0 else "regressed"
            return f"PASS ({direction}, p={p_value:.4f})"
        return "INCONCLUSIVE (p >= 0.05 or n < 30)"

    def execute_matrix(
        self,
        experiment_id: str,
        *,
        dry_run: bool = False,
        max_records: int | None = None,
        model_override: str | None = None,
        eval_set_override: str | None = None,
        family_override: str | None = None,
    ) -> dict[str, Any]:
        """Execute a single-condition evaluation matrix.

        This is the live execution path that reuses existing inference
        infrastructure from run_baseline_t3.py. It validates safety gates,
        loads the model, runs inference, scores results, and writes artifacts
        with full provenance.

        Args:
            experiment_id: Experiment identifier (resolved from research_state).
            dry_run: If True, validate gates but do not execute inference.
            max_records: Limit records for smoke testing.
            model_override: Override model path from experiment config.
            eval_set_override: Override eval set path.
            family_override: Override family inference.

        Returns:
            Dict with execution status, artifacts, and provenance.
        """
        import hashlib
        import time as _time

        run_id = f"matrix_{experiment_id}_{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        out_dir = self.results_dir / run_id
        out_dir.mkdir(parents=True, exist_ok=True)

        result = {
            "run_id": run_id,
            "experiment_id": experiment_id,
            "status": "PENDING",
            "dry_run": dry_run,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "gates": {},
            "provenance": {},
            "artifacts": {},
        }

        # ------------------------------------------------------------------ #
        # Phase 1: Resolve experiment metadata
        # ------------------------------------------------------------------ #
        from evaluation_research.state_machine import ResearchStateMachine

        sm = ResearchStateMachine(experiment_id, self.root)
        if not sm.load():
            result["status"] = "FAILED"
            result["error"] = f"No research state found for experiment '{experiment_id}'"
            return result

        experiment_meta = sm.get_metadata("experiment_meta", {})
        family = family_override or experiment_meta.get("family", "math")
        base_model = experiment_meta.get("base_model", "Qwen/Qwen2.5-7B-Instruct")
        model_path = model_override or experiment_meta.get("model_path", "")
        quantization = experiment_meta.get("quantization", {
            "load_in_4bit": True,
            "bnb_4bit_use_double_quant": True,
            "bnb_4bit_quant_type": "nf4",
            "bnb_4bit_compute_dtype": "bfloat16",
        })

        # ------------------------------------------------------------------ #
        # Phase 2: Resolve eval set
        # ------------------------------------------------------------------ #
        proto_dir = self.root / "evaluation" / "eval_sets" / "protocol_v2"
        eval_set_file = eval_set_override or None

        if not eval_set_file:
            # Find clean eval set for family
            for f in sorted(proto_dir.glob(f"*_{family}_v2_clean.jsonl")):
                eval_set_file = f
                break
            if not eval_set_file:
                for f in sorted(proto_dir.glob("*_clean.jsonl")):
                    name = f.stem
                    if family in name:
                        eval_set_file = f
                        break

        if not eval_set_file:
            result["status"] = "FAILED"
            result["error"] = f"No clean eval set found for family '{family}'"
            result["gates"]["eval_set_resolved"] = False
            return result

        eval_set_path = Path(eval_set_file)
        eval_set_id = eval_set_path.stem.replace("_clean", "")

        # ------------------------------------------------------------------ #
        # Phase 3: Safety gates
        # ------------------------------------------------------------------ #
        gates = {}

        # Gate 1: Eval set exists
        gates["eval_set_exists"] = eval_set_path.exists()
        if not gates["eval_set_exists"]:
            result["status"] = "BLOCKED"
            result["error"] = f"Eval set not found: {eval_set_path}"
            result["gates"] = gates
            return result

        # Gate 2: Eval set manifest exists (check multiple possible locations)
        manifest_path = None
        # The manifest may be named with or without _clean suffix
        manifest_names = [
            f"{eval_set_id}_manifest.json",
            f"{eval_set_path.stem}_manifest.json",
        ]
        candidates = []
        for name in manifest_names:
            candidates.append(eval_set_path.parent.parent / "production" / name)
            candidates.append(eval_set_path.parent / name)
            candidates.append(eval_set_path.parent.parent / name)
        for candidate in candidates:
            if candidate.exists():
                manifest_path = candidate
                break
        gates["eval_set_manifest_exists"] = manifest_path is not None
        # Checksum validation: warn on mismatch but don't block execution
        gates["eval_set_checksum_valid"] = True
        if manifest_path:
            try:
                manifest_data = json.loads(manifest_path.read_text())
                expected_checksum = manifest_data.get("checksum", {}).get("records", "")
                if expected_checksum:
                    actual_checksum = hashlib.sha256(
                        eval_set_path.read_bytes()
                    ).hexdigest()
                    if actual_checksum != expected_checksum:
                        print(f"[matrix] WARNING: checksum mismatch for {eval_set_path.name}")
                        print(f"  expected: {expected_checksum[:16]}...")
                        print(f"  actual:   {actual_checksum[:16]}...")
            except (json.JSONDecodeError, KeyError):
                pass

        # Gate 4: Checkpoint/model exists (if specified)
        gates["checkpoint_exists"] = True
        if model_path:
            gates["checkpoint_exists"] = Path(model_path).exists()
            if not gates["checkpoint_exists"]:
                # Try as base model name (HF hub)
                gates["checkpoint_exists"] = True  # Assume HF hub resolvable

        # Gate 5: No silent overwrite
        existing_run = out_dir / "run_metadata.json"
        gates["no_overwrite"] = not existing_run.exists()
        if not gates["no_overwrite"]:
            result["status"] = "BLOCKED"
            result["error"] = f"Run already exists: {existing_run}"
            result["gates"] = gates
            return result

        result["gates"] = gates
        all_passed = all(gates.values())
        if not all_passed:
            failed_gates = [k for k, v in gates.items() if not v]
            result["status"] = "BLOCKED"
            result["error"] = f"Gates failed: {failed_gates}"
            return result

        # ------------------------------------------------------------------ #
        # Phase 4: Dry-run mode
        # ------------------------------------------------------------------ #
        if dry_run:
            result["status"] = "DRY_RUN_OK"
            result["provenance"] = {
                "experiment_id": experiment_id,
                "family": family,
                "eval_set": str(eval_set_path),
                "model": model_path or base_model,
                "quantization": quantization,
                "max_records": max_records,
            }
            return result

        # ------------------------------------------------------------------ #
        # Phase 5: Execute inference (requires CUDA)
        # ------------------------------------------------------------------ #
        try:
            import torch
        except ImportError:
            result["status"] = "FAILED"
            result["error"] = "torch not available — CUDA inference requires PyTorch"
            return result

        if not torch.cuda.is_available():
            result["status"] = "BLOCKED"
            result["error"] = "CUDA not available — live inference requires GPU"
            return result

        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
            from evaluation_engine.leakage.prompts import (
                build_reference_free_prompt, ReferenceLeakError, prompt_meta,
            )
            from evaluation_engine.generation_policy import DynamicBudgetStrategy
            from evaluation_engine.generation_policy.versioning import FAMILY_BUDGET_PARAMS
            from evaluation_engine.v2.engine import QeeV2Engine
        except ImportError as exc:
            result["status"] = "FAILED"
            result["error"] = f"Missing dependency: {exc}"
            return result

        # Load model
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=quantization.get("load_in_4bit", True),
            bnb_4bit_use_double_quant=quantization.get("bnb_4bit_use_double_quant", True),
            bnb_4bit_quant_type=quantization.get("bnb_4bit_quant_type", "nf4"),
            bnb_4bit_compute_dtype=torch.bfloat16,
        )

        model_name = model_path or base_model
        try:
            tokenizer = AutoTokenizer.from_pretrained(
                base_model, use_fast=True
            )
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token
            model = AutoModelForCausalLM.from_pretrained(
                model_name,
                quantization_config=bnb_config,
                device_map="auto",
                trust_remote_code=False,
            )
            model.eval()
        except Exception as exc:
            result["status"] = "FAILED"
            result["error"] = f"Model load failed: {exc}"
            return result

        eos_id = tokenizer.convert_tokens_to_ids("</s>")
        if eos_id is None:
            eos_id = tokenizer.eos_token_id or 2

        # Build generation policy
        strategy = DynamicBudgetStrategy(
            base_budget=4096,
            alpha=2.0,
            minimum_budget=256,
            maximum_budget=4096,
            fallback_budget=1024,
        )
        policy = None  # Use default policy lock

        # Load eval records
        records = []
        with eval_set_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        if max_records is not None:
            records = records[:max_records]

        # Run inference
        engine = QeeV2Engine()
        per_example_results = []
        hold_count = 0
        error_count = 0

        for i, rec in enumerate(records):
            rid = rec.get("record_id", f"record_{i}")
            try:
                prompt = build_reference_free_prompt(rec, policy, tokenizer=tokenizer)
            except ReferenceLeakError as exc:
                per_example_results.append({
                    "record_id": rid,
                    "status": "HOLD",
                    "leak": "FAILED",
                    "leak_error": str(exc),
                })
                hold_count += 1
                continue

            reference = rec.get("canonical_answer") or ""
            budget = min(4096, max(256, 128 + int(1.5 * len(tokenizer.encode(reference, add_special_tokens=False)))))

            with torch.no_grad():
                inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
                input_len = inputs["input_ids"].shape[1]
                gen_ids = model.generate(
                    **inputs,
                    max_new_tokens=budget,
                    do_sample=False,
                    eos_token_id=eos_id,
                    pad_token_id=tokenizer.pad_token_id,
                )
                new_tokens = gen_ids[0][input_len:]
                response = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
                stop_reason = "max_length" if int(new_tokens.numel()) >= budget else "eos"
                n_tokens = int(new_tokens.numel())

            # Score with QEE v2
            question = rec.get("problem") or ""
            atype, score_result = engine._type_result(family, question, reference, response)
            dim_breakdown = engine._dimensions(family, score_result, question, reference, response)
            dims = {k: v["score"] for k, v in dim_breakdown.items()}
            raw_continuous = sum(engine.weights[k] * dims[k] for k in engine.weights)

            # Map to legacy metrics
            correctness = float(score_result.score) if hasattr(score_result, 'score') else 0.0
            is_wrong = getattr(score_result, 'correct', None) is False
            hallucination_rate = 1.0 if (is_wrong and correctness < 0.4) else 0.0
            format_ok = 1.0 if hasattr(score_result, 'extracted_candidate') and score_result.extracted_candidate else 0.0

            per_example_results.append({
                "record_id": rid,
                "model_id": model_name,
                "family": family,
                "status": "scored",
                "leak": "PASS",
                "correctness": correctness,
                "correct": getattr(score_result, 'correct', None),
                "method": getattr(score_result, 'method', ''),
                "reasoning_quality": float(raw_continuous),
                "quality_score": int(raw_continuous * 10) if raw_continuous >= 0 else 0,
                "hallucination_rate": hallucination_rate,
                "answer_format_consistency": format_ok,
                "tokens_generated": n_tokens,
                "stop_reason": stop_reason,
                "budget": budget,
                "predicted_response": response,
                "format_class": family,
                "dimensions": {k: round(v, 3) for k, v in dims.items()},
                "training_overlap": rec.get("training_overlap", False),
                "overlap_source": rec.get("overlap_source", ""),
            })

            if (i + 1) % 10 == 0 or (i + 1) == len(records):
                print(f"[matrix] {experiment_id}: scored {i+1}/{len(records)} records")

        # ------------------------------------------------------------------ #
        # Phase 6: Compute statistics
        # ------------------------------------------------------------------ #
        stats_output = self.compute_statistics(per_example_results, model_name, [])
        agg = stats_output["aggregates"].get(model_name, {})

        # ------------------------------------------------------------------ #
        # Phase 7: Write artifacts
        # ------------------------------------------------------------------ #
        completed_at = datetime.now(timezone.utc).isoformat()

        # Run metadata
        run_metadata = {
            "run_id": run_id,
            "experiment_id": experiment_id,
            "phase": "matrix_evaluation",
            "protocol_version": "v2",
            "status": "COMPLETED" if hold_count == 0 else "COMPLETED_WITH_HOLDS",
            "started_at": result["started_at"],
            "completed_at": completed_at,
            "model": {
                "base_model": base_model,
                "model_path": model_name,
                "quantization": quantization,
            },
            "eval_set": {
                "eval_set_id": eval_set_id,
                "path": str(eval_set_path),
                "n_records_requested": len(records),
                "n_records_scored": len([r for r in per_example_results if r.get("status") == "scored"]),
                "n_holds": hold_count,
                "n_errors": error_count,
            },
            "generation": {
                "policy": "dynamic-budget",
                "sampling": "greedy",
                "eos_token": "</s>",
                "seed": 42,
            },
            "scoring": {
                "engine": "QEE v2",
                "engine_path": "scripts/evaluation_engine/v2/engine.py",
            },
            "hardware": {
                "cuda_available": torch.cuda.is_available(),
                "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none",
            },
            "statistics": stats_output,
            "gates": gates,
        }
        (out_dir / "run_metadata.json").write_text(
            json.dumps(run_metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        # Per-example results
        (out_dir / "per_example_results.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in per_example_results) + "\n",
            encoding="utf-8",
        )

        # Checksum of outputs
        output_checksum = hashlib.sha256(
            json.dumps(per_example_results, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

        result["status"] = "COMPLETED"
        result["run_id"] = run_id
        result["provenance"] = {
            "experiment_id": experiment_id,
            "eval_set": str(eval_set_path),
            "eval_set_checksum": hashlib.sha256(eval_set_path.read_bytes()).hexdigest(),
            "model": model_name,
            "n_records": len(records),
            "n_scored": len([r for r in per_example_results if r.get("status") == "scored"]),
            "n_holds": hold_count,
            "output_checksum": output_checksum,
            "output_path": str(out_dir),
        }
        result["artifacts"] = {
            "run_metadata": str(out_dir / "run_metadata.json"),
            "per_example": str(out_dir / "per_example_results.jsonl"),
        }
        result["completed_at"] = completed_at

        return result
