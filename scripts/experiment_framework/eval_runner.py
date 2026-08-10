#!/usr/bin/env python3
"""
eval_runner.py — Base class for evaluation runners.

Provides evaluation infrastructure for:
  - Baseline evaluation (base model inference)
  - Post-training evaluation (adapter inference)
  - Transfer analysis (cross-domain gain computation)
  - Per-example result recording
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .manifests import EvaluationManifest
from .results import ResultEntry, AggregateMetrics


@dataclass
class BaselineComparison:
    """Comparison between baseline and post-training results."""
    baseline_exp_id: str
    baseline_path: str
    post_training_exp_id: str
    post_training_path: str
    metric: str = "correctness"
    baseline_value: float | None = None
    post_training_value: float | None = None
    delta: float | None = None
    per_example_deltas: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TransferAnalysis:
    """
    Cross-domain transfer analysis results.

    Computes:
      - In-domain gain: Δ_in^X = score(LoRA_X, E_X) - score(B, E_X)
      - Cross-domain gain: Δ_cross^{X→Y} = score(LoRA_X, E_Y) - score(B, E_Y)
      - Transfer Ratio: TR_{X→Y} = Δ_cross^{X→Y} / Δ_in^X
      - Transfer type: positive / negative / neutral / UNDETERMINED
    """
    experiment_id: str
    direction: str  # e.g., "Math -> Code"
    source_domain: str
    target_domain: str
    tau: float = 0.05
    tau_sym: float = 0.25

    # In-domain gain
    delta_in: float | None = None
    delta_in_source_eval: str | None = None

    # Cross-domain gain
    delta_cross: float | None = None
    delta_cross_target_eval: str | None = None

    # Transfer Ratio
    transfer_ratio: float | None = None
    transfer_ratio_status: str | None = None  # "N/A (HOLD)" or a number

    # Transfer type
    transfer_type: str | None = None  # "positive", "negative", "neutral", "UNDETERMINED"

    # Per-example classification
    improved_count: int = 0
    regressed_count: int = 0
    unchanged_count: int = 0

    # Symmetry analysis (for RQ5)
    symmetry_verdict: str | None = None  # "symmetric", "asymmetric", "UNDETERMINED"

    # Metadata
    generated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def classify_transfer_type(self) -> str:
        """
        Classify the transfer type per protocol §8.3.

        Returns:
            "positive", "negative", "neutral", or "UNDETERMINED"
        """
        if self.delta_cross is None:
            return "UNDETERMINED"

        if self.delta_cross >= self.tau and self.improved_count > self.regressed_count:
            self.transfer_type = "positive"
        elif self.delta_cross <= -self.tau and self.regressed_count > self.improved_count:
            self.transfer_type = "negative"
        elif abs(self.delta_cross) < self.tau:
            self.transfer_type = "neutral"
        else:
            self.transfer_type = "UNDETERMINED"

        return self.transfer_type

    def compute_transfer_ratio(self) -> None:
        """
        Compute the Transfer Ratio per protocol §8.2.

        TR is N/A (HOLD) when Δ_in^X ≤ 0.
        """
        if self.delta_in is None or self.delta_cross is None:
            self.transfer_ratio = None
            self.transfer_ratio_status = "N/A (HOLD)"
            return

        if self.delta_in <= 0:
            self.transfer_ratio = None
            self.transfer_ratio_status = "N/A (HOLD)"
        else:
            self.transfer_ratio = round(self.delta_cross / self.delta_in, 4)
            self.transfer_ratio_status = str(self.transfer_ratio)


class EvaluationRunner:
    """
    Base class for evaluation runners.

    This class provides infrastructure for running evaluations
    (baseline and post-training) and computing transfer analysis.
    It does NOT perform inference itself — subclasses implement
    the inference and scoring logic.
    """

    def __init__(
        self,
        experiment_id: str,
        eval_jsonl_path: Path | str,
        eval_split_id: str,
        engine: str = "QEE v2",
        engine_commit: str | None = None,
        engine_patches: list[str] | None = None,
        baseline_experiment_id: str | None = None,
        baseline_path: str | None = None,
    ):
        self.experiment_id = experiment_id
        self.eval_jsonl_path = Path(eval_jsonl_path)
        self.eval_split_id = eval_split_id
        self.engine = engine
        self.engine_commit = engine_commit
        self.engine_patches = engine_patches
        self.baseline_experiment_id = baseline_experiment_id
        self.baseline_path = baseline_path

        self._manifest: EvaluationManifest | None = None
        self._results: list[dict[str, Any]] = []
        self._aggregate: AggregateMetrics | None = None

    @property
    def manifest(self) -> EvaluationManifest:
        """Get or create the evaluation manifest."""
        if self._manifest is None:
            self._manifest = EvaluationManifest.create(
                experiment_id=self.experiment_id,
                eval_jsonl_path=self.eval_jsonl_path,
                eval_split_id=self.eval_split_id,
                engine=self.engine,
                engine_commit=self.engine_commit,
                engine_patches=self.engine_patches,
                baseline_experiment_id=self.baseline_experiment_id,
                baseline_path=self.baseline_path,
            )
        return self._manifest

    def load_eval_records(self) -> list[dict[str, Any]]:
        """Load evaluation records from the JSONL file."""
        records = []
        with self.eval_jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def generate_response(self, record: dict) -> tuple[str, int, float]:
        """
        Generate a response for a single evaluation record.

        Subclasses MUST override this method.

        Args:
            record: Evaluation record dict.

        Returns:
            (predicted_response, n_tokens, latency_s)
        """
        raise NotImplementedError("Subclasses must implement generate_response")

    def score_response(self, record: dict, response: str) -> dict[str, Any]:
        """
        Score a generated response using the evaluation engine.

        Subclasses MUST override this method.

        Args:
            record: Original evaluation record.
            response: Generated response text.

        Returns:
            Scoring result dict with correctness, quality, etc.
        """
        raise NotImplementedError("Subclasses must implement score_response")

    def run_evaluation(
        self,
        output_dir: Path | str | None = None,
    ) -> ResultEntry:
        """
        Run the full evaluation pipeline.

        Args:
            output_dir: Directory to write results. Defaults to current working directory.

        Returns:
            ResultEntry with evaluation results.
        """
        output_dir = Path(output_dir) if output_dir else Path.cwd()
        output_dir.mkdir(parents=True, exist_ok=True)

        records = self.load_eval_records()
        self._results = []

        for rec in records:
            rid = rec.get("record_id") or rec.get("id", "unknown")
            try:
                response, n_tokens, latency_s = self.generate_response(rec)
                score = self.score_response(rec, response)
                tps = n_tokens / latency_s if latency_s > 0 else 0.0

                self._results.append({
                    "record_id": rid,
                    "view_id": rec.get("view_id"),
                    "category": rec.get("category"),
                    "predicted_response": response,
                    "reference_answer": self._get_reference(rec),
                    "latency_s": round(latency_s, 4),
                    "tokens_generated": n_tokens,
                    "tokens_per_sec": round(tps, 2),
                    "correctness": score.get("correctness"),
                    "reasoning_quality": score.get("quality_continuous"),
                    "hallucination_rate": score.get("hallucination_rate", 0.0),
                    "answer_format_consistency": score.get("answer_format_consistency", 1.0),
                    "v2": score,
                })
            except Exception as e:
                self._results.append({
                    "record_id": rid,
                    "view_id": rec.get("view_id"),
                    "category": rec.get("category"),
                    "predicted_response": f"ERROR: {e}",
                    "reference_answer": self._get_reference(rec),
                    "latency_s": None,
                    "tokens_generated": None,
                    "tokens_per_sec": None,
                    "correctness": None,
                    "reasoning_quality": None,
                    "hallucination_rate": None,
                    "answer_format_consistency": None,
                    "v2": {},
                })

        # Compute aggregates
        self._aggregate = AggregateMetrics.compute_from_results(self._results)

        # Write per-example results
        per_example_path = output_dir / "post_training_per_example.jsonl"
        with per_example_path.open("w", encoding="utf-8") as f:
            for r in self._results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        # Write aggregate results
        result_entry = ResultEntry(
            experiment_id=self.experiment_id,
            evaluation_id="post_training",
            status="COMPLETE",
            model="BASE_MODEL" if not hasattr(self, '_adapter_path') else "LORA_ADAPTER",
            model_id=getattr(self, '_base_model', "unknown"),
            adapter_path=getattr(self, '_adapter_path', None),
            hardware=getattr(self, '_hardware', None),
            aggregate=self._aggregate,
            per_example_path=str(per_example_path),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        # Write result entry
        result_path = output_dir / "post_training.json"
        with result_path.open("w", encoding="utf-8") as f:
            json.dump(result_entry.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")

        return result_entry

    def _get_reference(self, record: dict) -> str:
        """Extract the reference answer from a record."""
        for m in record.get("messages") or []:
            if m.get("role") == "assistant":
                return (m.get("content") or "").strip()
        return record.get("solution") or record.get("canonical_answer", "")

    def compute_transfer_analysis(
        self,
        baseline_results: list[dict[str, Any]],
        metric: str = "correctness",
        tau: float = 0.05,
    ) -> TransferAnalysis:
        """
        Compute cross-domain transfer analysis.

        Args:
            baseline_results: List of baseline per-example results.
            metric: Metric to use for analysis (default: "correctness").
            tau: Threshold for transfer classification.

        Returns:
            TransferAnalysis with computed deltas and classification.
        """
        # Build lookup by record_id
        baseline_by_id = {r["record_id"]: r for r in baseline_results}
        post_by_id = {r["record_id"]: r for r in self._results}
        common_ids = sorted(set(baseline_by_id.keys()) & set(post_by_id.keys()))

        # Compute per-example deltas
        deltas = []
        improved = []
        regressed = []
        unchanged = []

        for rid in common_ids:
            b = baseline_by_id[rid]
            p = post_by_id[rid]
            b_val = b.get(metric)
            p_val = p.get(metric)
            if b_val is None or p_val is None:
                continue
            delta = p_val - b_val
            deltas.append({"record_id": rid, "delta": delta, "baseline": b_val, "post": p_val})
            if delta > tau:
                improved.append(rid)
            elif delta < -tau:
                regressed.append(rid)
            else:
                unchanged.append(rid)

        # Compute aggregate deltas
        valid_baseline = [r for r in baseline_results if r.get(metric) is not None]
        valid_post = [r for r in self._results if r.get(metric) is not None]
        common_valid = [
            (b, p) for b, p in zip(valid_baseline, valid_post)
            if b["record_id"] == p["record_id"]
        ]

        if common_valid:
            baseline_agg = sum(r[0][metric] for r in common_valid) / len(common_valid)
            post_agg = sum(r[1][metric] for r in common_valid) / len(common_valid)
            delta_cross = post_agg - baseline_agg
        else:
            baseline_agg = post_agg = delta_cross = None

        analysis = TransferAnalysis(
            experiment_id=self.experiment_id,
            direction=getattr(self, '_direction', "unknown"),
            source_domain=getattr(self, '_source_domain', "unknown"),
            target_domain=getattr(self, '_target_domain', "unknown"),
            tau=tau,
            delta_cross=round(delta_cross, 4) if delta_cross is not None else None,
            delta_cross_target_eval=str(self.eval_jsonl_path),
            improved_count=len(improved),
            regressed_count=len(regressed),
            unchanged_count=len(unchanged),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        analysis.classify_transfer_type()
        analysis.compute_transfer_ratio()

        # Save analysis
        output_dir = Path(self.eval_jsonl_path).parent / "analysis"
        output_dir.mkdir(parents=True, exist_ok=True)
        analysis_path = output_dir / f"{self.experiment_id}_transfer_analysis.json"
        with analysis_path.open("w", encoding="utf-8") as f:
            json.dump(analysis.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")

        # Save per-example deltas
        deltas_path = output_dir / f"{self.experiment_id}_per_example_deltas.jsonl"
        with deltas_path.open("w", encoding="utf-8") as f:
            for d in deltas:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

        return analysis
