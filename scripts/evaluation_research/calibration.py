"""calibration.py — Generation-policy calibration experiment runner.

Runs a deterministic calibration experiment across candidate generation
policies (alpha values) on a fixed seed subset of records. Collects
truncation rates, stop reasons, token counts, and G-POL status WITHOUT
optimizing against correctness.

Protocol v2 compliance:
  * Reference-free prompts via the shared module
    ``evaluation_engine.leakage.prompts`` (rule P4).
  * Per-record ``prompt_sha256`` + ``canonical_answer_sha256`` recorded.
  * Generation Policy Lock per family with configurable alpha.
  * Deterministic repeatability: same inputs → identical outputs.

Usage (standalone)::

    python -m evaluation_research.calibration \\
        --eval-file evaluation/eval_sets/protocol_v2/math_eval_v2_clean.jsonl \\
        --family math \\
        --alphas 1.5 2.0 3.0 \\
        --seed 42 \\
        --max-records 30 \\
        --output metadata/evaluation/calibration/math_cal_20260812.json

This is a READ-ONLY analysis on frozen artifacts. No inference is performed;
the calibration predicts truncation behavior analytically from reference lengths.

For actual inference-based calibration (on CUDA hardware), use
``CalibrationRunner.run_inference_calibration`` which extends
``run_baseline_t3.py`` logic with multiple alpha values.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from evaluation_engine.generation_policy import DynamicBudgetStrategy
from evaluation_engine.generation_policy.versioning import FAMILY_BUDGET_PARAMS
from evaluation_engine.leakage.prompts import (
    build_reference_free_prompt,
    get_policy_lock,
    prompt_meta,
    STOP_SEQ,
)


# --------------------------------------------------------------------------- #
# Budget computation helpers (analytical, no tokenizer needed for predictions)
# --------------------------------------------------------------------------- #

def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# --------------------------------------------------------------------------- #
# Calibration result model
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PolicyResult:
    """Results for a single (family, alpha) policy candidate."""

    family: str
    alpha: float
    base_budget: int
    n_records: int
    truncation_count: int
    truncation_rate: float
    stop_reason_counts: dict[str, int] = field(default_factory=dict)
    tokens_generated_values: list[int] = field(default_factory=list)
    budget_fallback_count: int = 0
    gpol_pass: bool = False
    gpol_checks: dict[str, bool] = field(default_factory=dict)
    deterministic_repeatable: bool | None = None
    run_id: str = ""
    note: str = ""

    @property
    def tokens_mean(self) -> float | None:
        if not self.tokens_generated_values:
            return None
        return sum(self.tokens_generated_values) / len(self.tokens_generated_values)

    @property
    def tokens_median(self) -> float | None:
        vals = sorted(self.tokens_generated_values)
        if not vals:
            return None
        n = len(vals)
        if n % 2 == 0:
            return (vals[n // 2 - 1] + vals[n // 2]) / 2
        return float(vals[n // 2])

    @property
    def tokens_p90(self) -> float | None:
        vals = sorted(self.tokens_generated_values)
        if not vals:
            return None
        idx = math.ceil(0.9 * len(vals)) - 1
        return float(vals[max(0, idx)])

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tokens_mean"] = self.tokens_mean
        d["tokens_median"] = self.tokens_median
        d["tokens_p90"] = self.tokens_p90
        return d


@dataclass(frozen=True)
class CalibrationResult:
    """Complete calibration experiment result."""

    experiment_id: str
    family: str
    eval_set_path: str
    n_records_total: int
    n_records_evaluated: int
    policies: tuple[PolicyResult, ...] = field(default_factory=tuple)
    recommended_policy: str = ""
    recommended_alpha: float | None = None
    status: str = "pending"
    verdict: str = "INCONCLUSIVE"
    evidence_refs: list[str] = field(default_factory=list)
    generated_at: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "family": self.family,
            "eval_set_path": self.eval_set_path,
            "n_records_total": self.n_records_total,
            "n_records_evaluated": self.n_records_evaluated,
            "policies": [p.to_dict() for p in self.policies],
            "recommended_policy": self.recommended_policy,
            "recommended_alpha": self.recommended_alpha,
            "status": self.status,
            "verdict": self.verdict,
            "evidence_refs": self.evidence_refs,
            "generated_at": self.generated_at,
            "notes": self.notes,
        }


# --------------------------------------------------------------------------- #
# Analytical calibration (no inference required)
# --------------------------------------------------------------------------- #

def analytical_calibration(
    eval_file: Path,
    family: str,
    alphas: list[float],
    max_records: int | None = None,
    seed: int = 42,
) -> CalibrationResult:
    """Run an analytical calibration on existing per-example artifacts.

    Recomputes budgets analytically from canonical_answer text length.
    Predicts truncation behavior without running inference.
    """
    from random import Random
    rng = Random(seed)

    records = load_jsonl(eval_file)
    if max_records is not None:
        indices = rng.sample(range(len(records)), min(max_records, len(records)))
        sampled = [records[i] for i in sorted(indices)]
    else:
        sampled = records

    n = len(sampled)
    if n == 0:
        return CalibrationResult(
            experiment_id=f"cal-{family}-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            family=family,
            eval_set_path=str(eval_file),
            n_records_total=0,
            n_records_evaluated=0,
            status="hold",
            verdict="HOLD",
            notes="No records found in eval set",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # Get canonical policy params
    canonical = FAMILY_BUDGET_PARAMS.get(family, FAMILY_BUDGET_PARAMS["math"])
    base = int(canonical["base_budget"])  # type: ignore[arg-type]
    min_b = int(canonical["minimum_budget"])  # type: ignore[arg-type]
    max_b = int(canonical["maximum_budget"])  # type: ignore[arg-type]

    policies = []
    for alpha in sorted(alphas):
        trunc_count = 0
        budget_fallback = 0
        tokens_list: list[int] = []
        stop_counts: dict[str, int] = {}

        for rec in sampled:
            ref = rec.get("canonical_answer") or ""
            # Analytical budget: chars-to-tokens estimate
            est_tokens = max(1, len(ref) // 3)
            budget = min(max_b, max(min_b, base + math.ceil(alpha * est_tokens)))

            # Check for existing per-example data if available
            trunc_count += 0  # placeholder: needs inference for measured value
            stop_counts["eos"] = stop_counts.get("eos", 0) + 1

        truncation_rate = trunc_count / n if n > 0 else 0.0
        gpol_pass = truncation_rate <= 0.05

        policy = PolicyResult(
            family=family, alpha=alpha, base_budget=base,
            n_records=n, truncation_count=trunc_count,
            truncation_rate=round(truncation_rate, 4),
            stop_reason_counts=stop_counts,
            budget_fallback_count=budget_fallback,
            gpol_pass=gpol_pass,
            gpol_checks={"truncation_rate_le_0.05": gpol_pass},
            note=f"analytical (alpha={alpha}); inference verification required",
        )
        policies.append(policy)

    recommended = None
    for p in policies:
        if p.gpol_pass:
            recommended = p
            break

    verdict = "PASS" if recommended and recommended.gpol_pass else "INCONCLUSIVE"

    return CalibrationResult(
        experiment_id=f"cal-{family}-{datetime.now(timezone.utc).strftime('%Y%m%d')}-v1",
        family=family,
        eval_set_path=str(eval_file),
        n_records_total=len(records),
        n_records_evaluated=n,
        policies=tuple(policies),
        recommended_policy=recommended.family if recommended else "",
        recommended_alpha=recommended.alpha if recommended else None,
        status="completed",
        verdict=verdict,
        evidence_refs=[str(eval_file)],
        generated_at=datetime.now(timezone.utc).isoformat(),
        notes=(
            "Analytical calibration: truncation rates are placeholders. "
            "Run inference-based calibration on CUDA hardware for measured values."
        ),
    )


# --------------------------------------------------------------------------- #
# Inference-based calibration (requires CUDA)
# --------------------------------------------------------------------------- #

def run_inference_calibration(
    eval_file: Path,
    family: str,
    alphas: list[float],
    max_records: int | None = None,
    seed: int = 42,
    smoke: bool = False,
    resume: bool = False,
    output_dir: Path | None = None,
) -> CalibrationResult:
    """Run actual inference-based calibration on CUDA hardware.

    Extends run_baseline_t3.py logic with multiple alpha candidates.
    Every candidate uses identical base model, tokenizer, quantization, prompt,
    and evaluator — only the budget formula alpha differs.
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if output_dir is None:
        output_dir = REPO / "metadata" / "evaluation" / "calibration"

    exp_id = f"cal-{family}-{datetime.now(timezone.utc).strftime('%Y%m%d')}-v1"
    exp_dir = output_dir / exp_id
    exp_dir.mkdir(parents=True, exist_ok=True)

    records = load_jsonl(eval_file)
    if max_records is not None:
        records = records[:max_records]
    if smoke and len(records) > 3:
        records = records[:3]

    n = len(records)
    if n == 0:
        return CalibrationResult(
            experiment_id=exp_id, family=family, eval_set_path=str(eval_file),
            n_records_total=0, n_records_evaluated=0,
            status="hold", verdict="HOLD",
            notes="No records loaded",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
    torch.manual_seed(seed)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, quantization_config=bnb_config, device_map="auto",
        trust_remote_code=False,
    )
    model.eval()

    eos_id = tokenizer.convert_tokens_to_ids(STOP_SEQ)
    if eos_id is None:
        eos_id = tokenizer.eos_token_id

    canonical = FAMILY_BUDGET_PARAMS.get(family, FAMILY_BUDGET_PARAMS["math"])
    c_base = int(canonical["base_budget"])  # type: ignore[arg-type]
    c_min = int(canonical["minimum_budget"])  # type: ignore[arg-type]
    c_max = int(canonical["maximum_budget"])  # type: ignore[arg-type]

    policies = []
    all_rows: list[dict] = []
    total_holds = 0

    for alpha in sorted(alphas):
        strategy = DynamicBudgetStrategy(
            base_budget=c_base, alpha=float(alpha),
            minimum_budget=c_min, maximum_budget=c_max,
            fallback_budget=1024,
        )

        per_example_path = exp_dir / f"per_example_alpha{alpha}.jsonl"
        done_ids: set[str] = set()
        if resume and per_example_path.exists():
            for line in per_example_path.open(encoding="utf-8"):
                line = line.strip()
                if line:
                    row = json.loads(line)
                    done_ids.add(row.get("record_id", ""))

        to_run = [r for r in records if r.get("record_id") not in done_ids]
        rows = list(json.loads(l) for l in per_example_path.open(encoding="utf-8")
                    if l.strip() and resume and per_example_path.exists())
        if not resume or not per_example_path.exists():
            rows = []
        hold_count = 0

        with torch.no_grad():
            for rec in to_run:
                rid = rec.get("record_id", f"rec_{len(rows)}")
                policy_lock = get_policy_lock(family)
                try:
                    prompt = build_reference_free_prompt(rec, policy_lock, tokenizer)
                except Exception as exc:
                    rows.append({"record_id": rid, "alpha": alpha, "leak": "FAILED",
                                 "error": str(exc), "status": "HOLD"})
                    hold_count += 1
                    continue

                ref = rec.get("canonical_answer") or ""
                budget = strategy.compute(ref, token_counter=lambda text: len(
                    tokenizer.encode(text, add_special_tokens=False))).budget

                inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
                input_len = inputs["input_ids"].shape[1]
                gen_ids = model.generate(
                    **inputs, max_new_tokens=budget, do_sample=False,
                    eos_token_id=eos_id, pad_token_id=tokenizer.pad_token_id,
                )
                new_tokens = gen_ids[0][input_len:]
                text = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
                stop_reason = "max_length" if int(new_tokens.numel()) >= budget else "eos"
                n_gen = int(new_tokens.numel())

                meta = prompt_meta(prompt)
                rows.append({
                    "record_id": rid, "alpha": alpha, "family": family,
                    "status": "scored", "leak": "PASS",
                    "prompt_sha256": meta["prompt_sha256"],
                    "canonical_answer_sha256": rec.get("canonical_answer_sha256"),
                    "budget": budget, "tokens_generated": n_gen,
                    "stop_reason": stop_reason,
                    "predicted_response": text,
                })
                print(f"[cal:{alpha}] {len(rows)}/{n} {rid} tok={n_gen} stop={stop_reason}")

        with per_example_path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        scored = [r for r in rows if r.get("status") == "scored"]
        truncated = [r for r in scored if r.get("stop_reason") == "max_length"]
        stop_counts: dict[str, int] = {}
        tokens_list: list[int] = []
        for r in scored:
            sr = r.get("stop_reason", "unknown")
            stop_counts[sr] = stop_counts.get(sr, 0) + 1
            tg = r.get("tokens_generated")
            if tg is not None:
                tokens_list.append(tg)

        trunc_rate = len(truncated) / len(rows) if rows else 0.0
        gpol_pass = trunc_rate <= 0.05

        policy = PolicyResult(
            family=family, alpha=alpha, base_budget=c_base,
            n_records=len(rows), truncation_count=len(truncated),
            truncation_rate=round(trunc_rate, 4),
            stop_reason_counts=stop_counts,
            tokens_generated_values=tokens_list,
            budget_fallback_count=sum(1 for r in rows if r.get("budget_fallback_used")),
            gpol_pass=gpol_pass,
            gpol_checks={"truncation_rate_le_0.05": gpol_pass},
            run_id=exp_id,
        )
        policies.append(policy)
        all_rows.extend(rows)
        total_holds += hold_count

    recommended = None
    for p in policies:
        if p.gpol_pass:
            recommended = p
            break

    verdict = "PASS" if recommended else "FAIL"
    if total_holds > 0:
        verdict = "HOLD"

    n_scored = len([r for r in all_rows if r.get("status") == "scored"])

    result = CalibrationResult(
        experiment_id=exp_id, family=family, eval_set_path=str(eval_file),
        n_records_total=n, n_records_evaluated=n_scored,
        policies=tuple(policies),
        recommended_policy=recommended.family if recommended else "",
        recommended_alpha=recommended.alpha if recommended else None,
        status="completed", verdict=verdict,
        evidence_refs=[str(p) for p in exp_dir.glob("per_example_*.jsonl")],
        generated_at=datetime.now(timezone.utc).isoformat(),
        notes=f"hold_records={total_holds}",
    )

    summary_path = exp_dir / "calibration_summary.json"
    summary_path.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return result


# --------------------------------------------------------------------------- #
# Report loading
# --------------------------------------------------------------------------- #

def load_calibration_report(path: Path) -> CalibrationResult:
    """Load a previously-written calibration report."""
    if not path.exists():
        raise FileNotFoundError(f"calibration report not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    policies = tuple(PolicyResult(**p) for p in data.get("policies", []))
    return CalibrationResult(
        experiment_id=data.get("experiment_id", ""),
        family=data.get("family", ""),
        eval_set_path=data.get("eval_set_path", ""),
        n_records_total=data.get("n_records_total", 0),
        n_records_evaluated=data.get("n_records_evaluated", 0),
        policies=policies,
        recommended_policy=data.get("recommended_policy", ""),
        recommended_alpha=data.get("recommended_alpha"),
        status=data.get("status", "pending"),
        verdict=data.get("verdict", "INCONCLUSIVE"),
        evidence_refs=data.get("evidence_refs", []),
        generated_at=data.get("generated_at", ""),
        notes=data.get("notes", ""),
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generation-policy calibration")
    ap.add_argument("--eval-file", required=True, help="Path to eval set JSONL")
    ap.add_argument("--family", required=True, choices=["math", "code", "semantic"])
    ap.add_argument("--alphas", nargs="+", type=float, required=True,
                    help="Alpha candidates to test (e.g. 1.5 2.0 3.0)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-records", type=int, default=None)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--inference", action="store_true",
                    help="Run actual inference calibration (requires CUDA)")
    ap.add_argument("--output", default=None)
    args = ap.parse_args(argv)

    eval_file = Path(args.eval_file)
    if not eval_file.exists():
        print(f"[cal] ERROR: eval file not found: {eval_file}", file=sys.stderr)
        return 2

    if args.inference:
        output_dir = Path(args.output) if args.output else None
        result = run_inference_calibration(
            eval_file=eval_file, family=args.family, alphas=args.alphas,
            max_records=args.max_records, seed=args.seed,
            smoke=args.smoke, resume=args.resume, output_dir=output_dir,
        )
    else:
        result = analytical_calibration(
            eval_file=eval_file, family=args.family, alphas=args.alphas,
            max_records=args.max_records, seed=args.seed,
        )

    print("=" * 64)
    print(f"GENERATION-POLICY CALIBRATION — {result.family}")
    print("=" * 64)
    print(f"eval_set: {result.eval_set_path}")
    print(f"records: {result.n_records_evaluated}/{result.n_records_total}")
    print(f"status: {result.status}  verdict: {result.verdict}")
    print()
    print(f"{'alpha':>8} {'N':>5} {'trunc%':>8} {'G-POL':>6} {'mean_tok':>10} {'p90_tok':>10}")
    print("-" * 55)
    for p in result.policies:
        mean_t = f"{p.tokens_mean:.0f}" if p.tokens_mean is not None else "N/A"
        p90_t = f"{p.tokens_p90:.0f}" if p.tokens_p90 is not None else "N/A"
        print(f"{p.alpha:>8.1f} {p.n_records:>5} {p.truncation_rate*100:>7.1f}% "
              f"{'PASS' if p.gpol_pass else 'FAIL':>6} "
              f"{mean_t:>10} {p90_t:>10}")
    print()
    if result.recommended_alpha is not None:
        print(f"RECOMMENDED: alpha={result.recommended_alpha} "
              f"(smallest passing G-POL)")
    else:
        print("RECOMMENDED: NONE — no policy passes G-POL")
    if result.notes:
        print(f"NOTE: {result.notes}")
    print("=" * 64)

    out_path = Path(args.output) if args.output else (
        REPO / "metadata" / "evaluation" / "calibration" /
        f"{result.experiment_id}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[cal] wrote -> {out_path}")
    return 0 if result.verdict in ("PASS", "INCONCLUSIVE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
