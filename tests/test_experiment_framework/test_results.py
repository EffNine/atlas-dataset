#!/usr/bin/env python3
"""
Tests for scripts/experiment_framework/results.py

Covers:
  - AggregateMetrics computation
  - ResultEntry creation
  - ResultRegistry CRUD operations
  - Comparison functionality
  - Persistence round-trip
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add scripts to path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from scripts.experiment_framework.results import (  # noqa: E402
    ResultRegistry,
    ResultEntry,
    AggregateMetrics,
)


# ===================================================================
# AggregateMetrics
# ===================================================================

class TestAggregateMetrics:
    def test_compute_from_results(self):
        results = [
            {"correctness": 1.0, "reasoning_quality": 0.8, "hallucination_rate": 0.0,
             "answer_format_consistency": 1.0, "latency_s": 1.0, "tokens_per_sec": 10.0},
            {"correctness": 0.5, "reasoning_quality": 0.6, "hallucination_rate": 0.5,
             "answer_format_consistency": 1.0, "latency_s": 2.0, "tokens_per_sec": 5.0},
            {"correctness": None, "reasoning_quality": None, "hallucination_rate": None,
             "answer_format_consistency": None, "latency_s": None, "tokens_per_sec": None},
        ]
        agg = AggregateMetrics.compute_from_results(results)
        assert agg.correctness == 0.75  # (1.0 + 0.5) / 2
        assert agg.evaluated_examples == 2
        assert agg.total_examples == 3

    def test_compute_empty_results(self):
        agg = AggregateMetrics.compute_from_results([])
        assert agg.evaluated_examples == 0
        assert agg.total_examples == 0

    def test_to_dict_from_dict(self):
        agg = AggregateMetrics(
            correctness=0.75,
            reasoning_quality=0.7,
            hallucination_rate=0.25,
            answer_format_consistency=1.0,
            evaluated_examples=4,
            total_examples=5,
        )
        d = agg.to_dict()
        agg2 = AggregateMetrics.from_dict(d)
        assert agg2.correctness == 0.75
        assert agg2.evaluated_examples == 4


# ===================================================================
# ResultEntry
# ===================================================================

class TestResultEntry:
    def test_create(self):
        entry = ResultEntry(
            experiment_id="test-exp",
            evaluation_id="post_training",
            status="COMPLETE",
            model="LORA_ADAPTER",
            model_id="Qwen/Qwen2.5-7B-Instruct",
            aggregate=AggregateMetrics(correctness=0.65, evaluated_examples=13, total_examples=13),
        )
        assert entry.experiment_id == "test-exp"
        assert entry.status == "COMPLETE"
        assert entry.aggregate.correctness == 0.65

    def test_to_dict_from_dict(self):
        entry = ResultEntry(
            experiment_id="test-exp",
            evaluation_id="post_training",
            status="COMPLETE",
            model="LORA_ADAPTER",
            model_id="Qwen/Qwen2.5-7B-Instruct",
            aggregate=AggregateMetrics(correctness=0.65, evaluated_examples=13, total_examples=13),
        )
        d = entry.to_dict()
        entry2 = ResultEntry.from_dict(d)
        assert entry2.experiment_id == entry.experiment_id
        assert entry2.aggregate.correctness == 0.65


# ===================================================================
# ResultRegistry
# ===================================================================

class TestResultRegistry:
    @pytest.fixture
    def registry(self, tmp_path: Path):
        return ResultRegistry(registry_path=tmp_path / "results.json")

    def test_add_and_get(self, registry: ResultRegistry):
        entry = ResultEntry(
            experiment_id="test-exp",
            evaluation_id="post_training",
            status="COMPLETE",
            model="LORA_ADAPTER",
            model_id="Qwen/Qwen2.5-7B-Instruct",
            aggregate=AggregateMetrics(correctness=0.65, evaluated_examples=13, total_examples=13),
        )
        registry.add(entry)
        results = registry.get("test-exp")
        assert len(results) == 1
        assert results[0].experiment_id == "test-exp"
        assert results[0].aggregate.correctness == 0.65

    def test_get_latest(self, registry: ResultRegistry):
        entry1 = ResultEntry(
            experiment_id="test-exp",
            evaluation_id="eval1",
            status="COMPLETE",
            model="BASE_MODEL",
            model_id="Qwen/Qwen2.5-7B-Instruct",
            aggregate=AggregateMetrics(correctness=0.60, evaluated_examples=10, total_examples=10),
        )
        entry2 = ResultEntry(
            experiment_id="test-exp",
            evaluation_id="eval2",
            status="COMPLETE",
            model="LORA_ADAPTER",
            model_id="Qwen/Qwen2.5-7B-Instruct",
            aggregate=AggregateMetrics(correctness=0.65, evaluated_examples=10, total_examples=10),
        )
        registry.add(entry1)
        registry.add(entry2)
        latest = registry.get_latest("test-exp")
        assert latest.evaluation_id == "eval2"
        assert latest.aggregate.correctness == 0.65

    def test_get_missing(self, registry: ResultRegistry):
        assert registry.get("nonexistent") == []

    def test_list_by_status(self, registry: ResultRegistry):
        registry.add(ResultEntry(
            experiment_id="exp1", evaluation_id="eval1", status="COMPLETE",
            model="BASE_MODEL", model_id="model1",
            aggregate=AggregateMetrics(correctness=0.6, evaluated_examples=10, total_examples=10),
        ))
        registry.add(ResultEntry(
            experiment_id="exp2", evaluation_id="eval1", status="HOLD",
            model="LORA_ADAPTER", model_id="model2",
            aggregate=AggregateMetrics(evaluated_examples=0, total_examples=0),
        ))
        complete = registry.list_by_status("COMPLETE")
        holds = registry.list_by_status("HOLD")
        assert len(complete) == 1
        assert len(holds) == 1
        assert complete[0][0] == "exp1"
        assert holds[0][0] == "exp2"

    def test_compare(self, registry: ResultRegistry):
        registry.add(ResultEntry(
            experiment_id="baseline", evaluation_id="base", status="COMPLETE",
            model="BASE_MODEL", model_id="model1",
            aggregate=AggregateMetrics(correctness=0.60, evaluated_examples=10, total_examples=10),
        ))
        registry.add(ResultEntry(
            experiment_id="experimental", evaluation_id="lora", status="COMPLETE",
            model="LORA_ADAPTER", model_id="model1",
            aggregate=AggregateMetrics(correctness=0.65, evaluated_examples=10, total_examples=10),
        ))
        comparison = registry.compare("baseline", "experimental", metric="correctness")
        assert comparison is not None
        assert comparison["baseline_value"] == 0.60
        assert comparison["experimental_value"] == 0.65
        assert comparison["delta"] == 0.05

    def test_compare_missing(self, registry: ResultRegistry):
        comparison = registry.compare("baseline", "experimental")
        assert comparison is None

    def test_persistence(self, registry: ResultRegistry):
        registry.add(ResultEntry(
            experiment_id="test-exp", evaluation_id="eval1", status="COMPLETE",
            model="LORA_ADAPTER", model_id="model1",
            aggregate=AggregateMetrics(correctness=0.65, evaluated_examples=10, total_examples=10),
        ))
        registry.save()

        registry2 = ResultRegistry(registry_path=registry.path)
        registry2.load()
        assert len(registry2.get("test-exp")) == 1

    def test_len(self, registry: ResultRegistry):
        assert len(registry) == 0
        registry.add(ResultEntry(
            experiment_id="exp1", evaluation_id="eval1", status="COMPLETE",
            model="BASE_MODEL", model_id="m1",
            aggregate=AggregateMetrics(evaluated_examples=1, total_examples=1),
        ))
        assert len(registry) == 1

    def test_summary(self, registry: ResultRegistry):
        registry.add(ResultEntry(
            experiment_id="exp1", evaluation_id="eval1", status="COMPLETE",
            model="BASE_MODEL", model_id="m1",
            aggregate=AggregateMetrics(evaluated_examples=1, total_examples=1),
        ))
        registry.add(ResultEntry(
            experiment_id="exp2", evaluation_id="eval1", status="HOLD",
            model="LORA_ADAPTER", model_id="m2",
            aggregate=AggregateMetrics(evaluated_examples=0, total_examples=0),
        ))
        summary = registry.summary()
        assert summary["total_entries"] == 2
        assert summary["experiments"] == 2
        assert summary["by_status"]["COMPLETE"] == 1
        assert summary["by_status"]["HOLD"] == 1
