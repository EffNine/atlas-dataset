#!/usr/bin/env python3
"""
training_runner.py — Base class for QLoRA training runners.

Provides a reusable training runner that handles:
  - Checksum verification before training
  - Deterministic data loading (sorted by record_id)
  - Training loop with step metrics logging
  - Checkpoint saving
  - Resume support
  - Reproducibility checklist compliance
"""

from __future__ import annotations

import csv
import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

from .config import ExperimentConfig
from .scaffold import ExperimentScaffold
from .metadata import RunMetadata, CheckpointMetadata, git_info, hardware_info, compute_sha256


@dataclass
class TrainingStepLog:
    """A single training step log entry."""
    step: int
    loss: float
    lr: float
    mem_alloc_mib: float
    mem_reserved_mib: float
    tokens_this_step: int
    tokens_per_sec: float
    elapsed_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "loss": round(self.loss, 5),
            "lr": round(self.lr, 7),
            "mem_alloc_mib": round(self.mem_alloc_mib, 1),
            "mem_reserved_mib": round(self.mem_reserved_mib, 1),
            "tokens_this_step": self.tokens_this_step,
            "tokens_per_sec": round(self.tokens_per_sec, 2),
            "elapsed_s": round(self.elapsed_s, 3),
        }


class TrainingRunner:
    """
    Base class for QLoRA training runners.

    This class provides the infrastructure for running QLoRA training
    experiments in a reproducible manner. It does NOT perform training
    itself — it manages the metadata, checksums, and logging around
    the training process.

    Subclasses should implement the `train_step` method to perform
    the actual training iteration.
    """

    def __init__(
        self,
        config: ExperimentConfig,
        experiment_root: Path | None = None,
        train_jsonl_path: Path | None = None,
        approved_train_sha256: str | None = None,
    ):
        self.config = config
        self.experiment_root = experiment_root or Path.cwd()
        self.scaffold = ExperimentScaffold(
            config.experiment_id,
            experiments_root=self.experiment_root.parent,
        )
        self.train_jsonl_path = train_jsonl_path
        self.approved_train_sha256 = approved_train_sha256

        # Training state
        self._step_logs: list[TrainingStepLog] = []
        self._pre_run_metadata: RunMetadata | None = None
        self._checkpoint_metadata: CheckpointMetadata | None = None

    @property
    def experiment_id(self) -> str:
        return self.config.experiment_id

    @property
    def checkpoints_dir(self) -> Path:
        return self.scaffold.checkpoints_dir

    @property
    def training_log_dir(self) -> Path:
        return self.scaffold.training_log_dir

    def setup(self) -> RunMetadata:
        """
        Set up the experiment: create scaffold, verify checksums, collect metadata.

        Returns:
            RunMetadata collected before training starts.

        Raises:
            SystemExit: If checksum verification fails (fail-closed).
        """
        # Create experiment scaffold
        self.scaffold.create()

        # Collect pre-run metadata
        self._pre_run_metadata = RunMetadata.collect(
            experiment_id=self.experiment_id,
            phase=self.config.phase,
            train_jsonl_path=self.train_jsonl_path,
            approved_train_sha256=self.approved_train_sha256,
        )

        # Verify checksums
        if self.approved_train_sha256 is not None and self.train_jsonl_path is not None:
            import hashlib
            h = hashlib.sha256()
            with self.train_jsonl_path.open("rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            actual_sha = h.hexdigest()
            if actual_sha != self.approved_train_sha256:
                raise SystemExit(
                    f"ABORT: training subset checksum mismatch (fail-closed)\n"
                    f"  expected: {self.approved_train_sha256}\n"
                    f"  actual:   {actual_sha}"
                )

        # Save pre-run metadata
        self._save_pre_run_metadata()

        return self._pre_run_metadata

    def _save_pre_run_metadata(self) -> None:
        """Save pre-run metadata to the experiment directory."""
        if self._pre_run_metadata is None:
            return
        meta_path = self.scaffold.root / "pre_run_metadata.json"
        with meta_path.open("w", encoding="utf-8") as f:
            json.dump(self._pre_run_metadata.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")

    def _save_training_log(self) -> None:
        """Save the training log to the experiment directory."""
        log_data = {
            "experiment_id": self.experiment_id,
            "phase": self.config.phase,
            "status": "COMPLETED",
            "pre_training": self._pre_run_metadata.to_dict() if self._pre_run_metadata else {},
            "config": self.config.to_dict(),
            "trainable_parameters": None,
            "trainable_percent": None,
            "training_metrics": self._compute_training_metrics(),
            "files": {
                "step_metrics": str(self.training_log_dir / "step_metrics.csv"),
                "adapter": str(self.checkpoints_dir),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        log_path = self.scaffold.root / "training_log.json"
        with log_path.open("w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    def _compute_training_metrics(self) -> dict[str, Any]:
        """Compute training metrics from step logs."""
        if not self._step_logs:
            return {
                "steps": 0,
                "examples_consumed": 0,
                "final_loss": None,
                "min_loss": None,
                "peak_mem_allocated_mib": None,
                "last_mem_allocated_mib": None,
                "last_mem_reserved_mib": None,
                "throughput_tps_mean": None,
                "wall_time_s": None,
            }

        steps = len(self._step_logs)
        grad_accum = self.config.training.gradient_accumulation_steps
        final_loss = self._step_logs[-1].loss
        min_loss = min(log.loss for log in self._step_logs)
        peak_mem = max(log.mem_alloc_mib for log in self._step_logs)
        last_mem_alloc = self._step_logs[-1].mem_alloc_mib
        last_mem_reserved = self._step_logs[-1].mem_reserved_mib
        mean_tps = sum(log.tokens_per_sec for log in self._step_logs) / steps
        wall_time = self._step_logs[-1].elapsed_s

        return {
            "steps": steps,
            "examples_consumed": steps * grad_accum,
            "final_loss": round(final_loss, 5),
            "min_loss": round(min_loss, 5),
            "peak_mem_allocated_mib": round(peak_mem, 1),
            "last_mem_allocated_mib": round(last_mem_alloc, 1),
            "last_mem_reserved_mib": round(last_mem_reserved, 1),
            "throughput_tps_mean": round(mean_tps, 2),
            "wall_time_s": round(wall_time, 3),
        }

    def _write_step_metrics_csv(self) -> None:
        """Write step metrics to CSV."""
        csv_path = self.training_log_dir / "step_metrics.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "step", "loss", "lr", "mem_alloc_mib", "mem_reserved_mib",
                "tokens_this_step", "tokens_per_sec", "elapsed_s",
            ])
            for log in self._step_logs:
                d = log.to_dict()
                writer.writerow([
                    d["step"], d["loss"], d["lr"], d["mem_alloc_mib"],
                    d["mem_reserved_mib"], d["tokens_this_step"],
                    d["tokens_per_sec"], d["elapsed_s"],
                ])

    def _write_config(self) -> None:
        """Write the experiment config to the experiment directory."""
        config_path = self.scaffold.root / "config.json"
        with config_path.open("w", encoding="utf-8") as f:
            json.dump(self.config.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")

    def run_training_loop(
        self,
        examples: list[dict],
        max_steps: int,
        grad_accum_steps: int,
        logging_steps: int = 10,
    ) -> list[TrainingStepLog]:
        """
        Run the training loop, collecting step metrics.

        Subclasses should override `train_step` to perform the actual
        training computation. This method handles timing, logging,
        and checkpoint saving.

        Args:
            examples: List of training examples (pre-tokenized).
            max_steps: Maximum number of optimizer steps.
            grad_accum_steps: Gradient accumulation steps.
            logging_steps: How often to log metrics.

        Returns:
            List of TrainingStepLog entries.
        """
        step = 0
        micro = 0
        loss_window = 0.0
        token_window = 0
        window_t0 = time.perf_counter()
        t_start = time.perf_counter()
        peak_mem = 0.0
        idx = 0
        n_examples = len(examples)

        self._step_logs = []

        print(f"Training {self.experiment_id} for {max_steps} steps "
              f"(batch={self.config.training.per_device_train_batch_size}, "
              f"accum={grad_accum_steps}) ...")

        while step < max_steps:
            ex = examples[idx % n_examples]
            idx += 1

            # Call subclass implementation
            loss, tokens, mem_alloc, mem_reserved = self.train_step(ex)

            loss_window += loss
            token_window += tokens
            peak_mem = max(peak_mem, mem_alloc)
            micro += 1

            if micro % grad_accum_steps == 0:
                step += 1
                avg_loss = loss_window / grad_accum_steps
                toks = token_window
                dt = time.perf_counter() - window_t0
                tps = toks / dt if dt > 0 else 0.0
                loss_window = 0.0
                token_window = 0
                window_t0 = time.perf_counter()

                # Compute current LR
                lr = self._compute_lr(step, max_steps)

                log = TrainingStepLog(
                    step=step,
                    loss=avg_loss,
                    lr=lr,
                    mem_alloc_mib=mem_alloc,
                    mem_reserved_mib=mem_reserved,
                    tokens_this_step=toks,
                    tokens_per_sec=tps,
                    elapsed_s=time.perf_counter() - t_start,
                )
                self._step_logs.append(log)

                if step % logging_steps == 0 or step == 1:
                    print(f"  step {step:3d} loss={avg_loss:.4f} lr={lr:.2e} "
                          f"tps={tps:.1f} mem=(alloc {mem_alloc:.0f}, "
                          f"reserved {mem_reserved:.0f})MiB")

        self._write_step_metrics_csv()
        return self._step_logs

    def train_step(self, example: dict) -> tuple[float, int, float, float]:
        """
        Perform a single training step.

        Subclasses MUST override this method to perform the actual
        forward pass, loss computation, and backward pass.

        Args:
            example: Pre-tokenized training example dict.

        Returns:
            (loss, tokens, mem_alloc_mib, mem_reserved_mib)
        """
        raise NotImplementedError("Subclasses must implement train_step")

    def _compute_lr(self, step: int, max_steps: int) -> float:
        """Compute learning rate for the current step using the configured scheduler."""
        cfg = self.config.training
        warmup = max(1, int(max_steps * cfg.warmup_ratio))
        if step < warmup:
            return cfg.learning_rate * (step + 1) / warmup
        if cfg.lr_scheduler_type == "cosine":
            if np is not None:
                prog = (step - warmup) / max(max_steps - warmup, 1)
                return cfg.learning_rate * float(0.5 * (1 + np.cos(np.pi * prog)))
            # Fallback: simple cosine approximation
            prog = (step - warmup) / max(max_steps - warmup, 1)
            import math
            return cfg.learning_rate * float(0.5 * (1 + math.cos(math.pi * prog)))
        return cfg.learning_rate

    def save_checkpoint(
        self,
        model: Any,
        trainable_params: int,
        total_params: int,
    ) -> CheckpointMetadata:
        """
        Save the LoRA adapter checkpoint.

        Args:
            model: The PEFT model to save.
            trainable_params: Number of trainable parameters.
            total_params: Total number of parameters.

        Returns:
            CheckpointMetadata for the saved adapter.
        """
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(self.checkpoints_dir))

        # Compute adapter SHA-256
        adapter_model_path = self.checkpoints_dir / "adapter_model.safetensors"
        adapter_sha = None
        if adapter_model_path.exists():
            adapter_sha = compute_sha256(adapter_model_path)

        metrics = self._compute_training_metrics()
        self._checkpoint_metadata = CheckpointMetadata(
            adapter_path=str(self.checkpoints_dir),
            base_model=self.config.base_model,
            adapter_model_sha256=adapter_sha,
            trainable_parameters=trainable_params,
            total_parameters=total_params,
            trainable_percent=round(100.0 * trainable_params / total_params, 4)
            if total_params > 0 else None,
            training_steps=metrics["steps"],
            final_loss=metrics["final_loss"],
            min_loss=metrics["min_loss"],
            peak_mem_allocated_mib=metrics["peak_mem_allocated_mib"],
        )
        self._checkpoint_metadata.save(self.checkpoints_dir / "checkpoint_metadata.json")
        return self._checkpoint_metadata

    def finalize(self) -> dict[str, Any]:
        """
        Finalize the experiment: save training log, config, and metadata.

        Returns:
            Dictionary with final training results.
        """
        self._write_config()
        self._save_training_log()

        return {
            "experiment_id": self.experiment_id,
            "status": "COMPLETED",
            "training_metrics": self._compute_training_metrics(),
            "checkpoint_metadata": self._checkpoint_metadata.to_dict()
            if self._checkpoint_metadata else None,
        }
