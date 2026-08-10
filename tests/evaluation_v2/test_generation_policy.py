"""Tests for the Generation Policy infrastructure (Sprint 5A.4).

Covers, for the ``evaluation_engine.generation_policy`` package:

  * version support and family registration (``versioning``),
  * ``BudgetStrategy`` interface and the ``StaticBudget`` reference-derived
    implementation (determinism, cap/floor, fallback),
  * ``GenerationPolicy`` immutability, family defaults, strict dict loading,
    unknown-key / unknown-version rejection, stable hashes,
  * ``GenerationConfig`` strict loading, round-trip, stable hashes,
  * configuration loading from dict and JSON file (version-aware),
  * ``GenerationValidation`` gates (policy, config, pair, budget result),
  * ``GenerationMetadata`` block builders (deterministic, hashed, covariates).

Hermetic, offline, stdlib-only (conftest.py adds ``scripts/`` to sys.path).
"""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

from evaluation_engine.generation_policy import (
    DEFAULT_STATIC_BUDGET,
    BudgetResult,
    BudgetStrategy,
    GenerationConfig,
    GenerationMetadata,
    GenerationPolicy,
    GenerationValidation,
    StaticBudget,
    ValidationResult,
    default_generation_config,
    family_default_policy,
    load_config,
    load_config_file,
    load_policy,
    load_policy_file,
    version_info,
)
from evaluation_engine.generation_policy.policy import FAMILY_FORMAT_ACCOUNTING
from evaluation_engine.generation_policy.versioning import (
    BUDGET_FALLBACK,
    CONFIG_SCHEMA_VERSION,
    GENERATION_POLICY_VERSION,
    MAX_BUDGET,
    MIN_BUDGET,
    POLICY_SCHEMA_VERSION,
    RULE_DYNAMIC_REFERENCE_DERIVED,
    RULE_REFERENCE_DERIVED,
    SUPPORTED_BUDGET_RULES,
    SUPPORTED_FAMILIES,
    SUPPORTED_SCHEMA_VERSIONS,
    assert_family_supported,
    assert_policy_version_supported,
    assert_schema_version_supported,
)
from evaluation_engine.leakage.prompts import BUDGET_RULE


def _counter(n: int) -> object:
    return lambda text: n


# --------------------------------------------------------------------------- #
# Versioning
# --------------------------------------------------------------------------- #
class TestVersioning:
    def test_version_constants(self):
        assert GENERATION_POLICY_VERSION == "1.0"
        assert POLICY_SCHEMA_VERSION == CONFIG_SCHEMA_VERSION == "1"
        assert SUPPORTED_SCHEMA_VERSIONS == frozenset({"1"})

    def test_version_info_shape(self):
        info = version_info()
        assert info["generation_policy_version"] == GENERATION_POLICY_VERSION
        assert info["template_version"] == "qwen2.5-chatml-deterministic-v1"
        assert set(info["supported_families"]) == set(SUPPORTED_FAMILIES)

    def test_assert_supported_ok(self):
        assert_policy_version_supported(GENERATION_POLICY_VERSION)
        assert_schema_version_supported("1", "GenerationConfig")
        assert_family_supported("math")

    def test_assert_unsupported_raises(self):
        with pytest.raises(ValueError, match="unsupported GenerationPolicy version"):
            assert_policy_version_supported("9.9")
        with pytest.raises(ValueError, match="unsupported GenerationConfig schema"):
            assert_schema_version_supported("99", "GenerationConfig")
        with pytest.raises(ValueError, match="unsupported policy family"):
            assert_family_supported("biology")

    def test_supported_families(self):
        assert SUPPORTED_FAMILIES == ("math", "code", "semantic")


# --------------------------------------------------------------------------- #
# BudgetStrategy / StaticBudget
# --------------------------------------------------------------------------- #
class TestBudgetStrategy:
    def test_static_budget_implements_interface(self):
        assert isinstance(DEFAULT_STATIC_BUDGET, StaticBudget)
        assert callable(DEFAULT_STATIC_BUDGET.compute)
        # structural interface check
        assert hasattr(BudgetStrategy, "__call__")

    def test_canonical_rule_matches_protocol(self):
        assert DEFAULT_STATIC_BUDGET.rule == RULE_REFERENCE_DERIVED
        assert DEFAULT_STATIC_BUDGET.rule == BUDGET_RULE

    def test_formula_matches_protocol(self):
        # budget_i = min(4096, max(256, 128 + ceil(1.5 * N)))
        for n in (0, 1, 10, 64, 100, 1000, 5000):
            expected = min(MAX_BUDGET, max(MIN_BUDGET,
                                           128 + math.ceil(1.5 * n)))
            result = DEFAULT_STATIC_BUDGET.compute("x" * n,
                                                   token_counter=_counter(n))
            assert result.budget == expected
            assert result.reference_tokens == n
            assert not result.fallback_used

    def test_cap_at_max(self):
        r = DEFAULT_STATIC_BUDGET.compute("ref", token_counter=_counter(5000))
        assert r.budget == MAX_BUDGET
        assert r.capped is True
        assert r.floor_applied is False

    def test_floor_at_min(self):
        r = DEFAULT_STATIC_BUDGET.compute("ref", token_counter=_counter(1))
        assert r.budget == MIN_BUDGET
        assert r.floor_applied is True
        assert r.capped is False

    def test_no_counter_uses_fallback(self):
        r = DEFAULT_STATIC_BUDGET.compute("any reference")
        assert r.budget == BUDGET_FALLBACK
        assert r.fallback_used is True
        assert r.reference_tokens is None

    def test_counter_failure_uses_fallback(self):
        def bad(text):
            raise RuntimeError("no tokenizer")

        r = DEFAULT_STATIC_BUDGET.compute("ref", token_counter=bad)
        assert r.budget == BUDGET_FALLBACK
        assert r.fallback_used is True

    def test_deterministic(self):
        a = DEFAULT_STATIC_BUDGET.compute("ref", token_counter=_counter(50))
        b = DEFAULT_STATIC_BUDGET.compute("ref", token_counter=_counter(50))
        assert a == b
        assert a.to_dict() == b.to_dict()

    def test_custom_constants_change_rule(self):
        custom = StaticBudget(max_budget=2048, min_budget=128, base_tokens=64,
                              multiplier=2.0)
        assert "2048" in custom.rule and "128" in custom.rule
        r = custom.compute("ref", token_counter=_counter(100))
        expected = min(2048, max(128, 64 + math.ceil(2.0 * 100)))
        assert r.budget == expected

    def test_fixed_fallback_mode(self):
        r = DEFAULT_STATIC_BUDGET.fixed_fallback()
        assert r.budget == BUDGET_FALLBACK
        assert r.rule == "fixed-fallback"
        assert r.fallback_used is True

    def test_budget_result_immutable(self):
        r = BudgetResult(budget=1024, rule="x", reference_tokens=None,
                         fallback_used=True, capped=False, floor_applied=False)
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.budget = 5

    def test_budget_result_to_dict(self):
        r = DEFAULT_STATIC_BUDGET.compute("ref", token_counter=_counter(10))
        d = r.to_dict()
        assert d["budget"] == r.budget
        assert set(d) == {"budget", "rule", "reference_tokens",
                          "fallback_used", "capped", "floor_applied"}


# --------------------------------------------------------------------------- #
# GenerationPolicy
# --------------------------------------------------------------------------- #
class TestGenerationPolicy:
    def test_from_family_math(self):
        p = family_default_policy("math")
        assert p.family == "math"
        assert p.system_message_text
        assert p.system_message_sha256
        assert p.policy_lock_sha256
        assert p.extraction_rule == (
            "qee-v2-math-extractor (Phase 5A.4 + 6.4 patches)")
        assert p.format_accounting == FAMILY_FORMAT_ACCOUNTING["math"]
        assert p.budget_rule == RULE_DYNAMIC_REFERENCE_DERIVED
        assert p.budget_strategy == "dynamic"
        assert p.budget_params is not None
        assert p.budget_params["alpha"] == 3.0
        assert p.budget_params["base_budget"] == 128

    def test_from_family_code(self):
        p = family_default_policy("code")
        assert p.family == "code"
        assert "unified diff" in p.system_message_text
        assert p.format_accounting == FAMILY_FORMAT_ACCOUNTING["code"]

    def test_from_family_semantic(self):
        p = family_default_policy("semantic")
        assert p.family == "semantic"
        assert p.format_accounting == FAMILY_FORMAT_ACCOUNTING["semantic"]

    def test_from_family_unknown_raises(self):
        with pytest.raises(ValueError, match="unsupported policy family"):
            family_default_policy("cooking")

    def test_immutable(self):
        p = family_default_policy("math")
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.family = "code"

    def test_sha256_stable(self):
        a = family_default_policy("math")
        b = family_default_policy("math")
        assert a.sha256() == b.sha256()
        assert len(a.sha256()) == 64

    def test_hash_changes_on_change(self):
        a = family_default_policy("math")
        b = family_default_policy("code")
        assert a.sha256() != b.sha256()

    def test_to_dict_round_trip(self):
        p = family_default_policy("math")
        q = GenerationPolicy.from_dict(p.to_dict())
        assert p == q
        assert p.sha256() == q.sha256()

    def test_from_dict_unknown_key_raises(self):
        with pytest.raises(ValueError, match="unknown GenerationPolicy keys"):
            GenerationPolicy.from_dict({"family": "math", "bogus_key": 1})

    def test_from_dict_unsupported_version_raises(self):
        with pytest.raises(ValueError, match="unsupported GenerationPolicy version"):
            GenerationPolicy.from_dict({"family": "math", "version": "0.9"})

    def test_from_dict_unsupported_schema_raises(self):
        with pytest.raises(ValueError, match="unsupported GenerationPolicy schema"):
            GenerationPolicy.from_dict({"family": "math", "schema_version": "2"})

    def test_from_dict_unknown_family_raises(self):
        with pytest.raises(ValueError, match="unsupported policy family"):
            GenerationPolicy.from_dict({"family": "physics"})

    def test_from_dict_non_dict_raises(self):
        with pytest.raises(TypeError, match="expects a dict"):
            GenerationPolicy.from_dict(["math"])

    def test_to_block_self_hash(self):
        p = family_default_policy("math")
        block = p.to_block()
        assert block["policy_sha256"] == p.sha256()
        assert len(block["policy_block_sha256"]) == 64


# --------------------------------------------------------------------------- #
# GenerationConfig
# --------------------------------------------------------------------------- #
class TestGenerationConfig:
    def test_defaults_match_protocol(self):
        c = default_generation_config()
        assert c.quantization == "4bit_nf4_double_quant"
        assert c.compute_dtype == "bfloat16"
        assert c.sampling == "greedy"
        assert c.do_sample is False
        assert c.seed == 42
        assert c.max_budget == MAX_BUDGET
        assert c.budget_fallback == BUDGET_FALLBACK
        assert c.stop_sequence == "<|im_end|>"
        assert c.eos_token_id is None
        assert c.pad_token_id is None

    def test_immutable(self):
        c = default_generation_config()
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.seed = 7

    def test_sha256_stable(self):
        assert default_generation_config().sha256() == \
            default_generation_config().sha256()

    def test_from_dict_round_trip(self):
        c = default_generation_config()
        d = load_config(c.to_dict())
        assert c == d

    def test_from_dict_partial(self):
        c = load_config({"seed": 7, "eos_token_id": 151645})
        assert c.seed == 7
        assert c.eos_token_id == 151645
        assert c.quantization == "4bit_nf4_double_quant"
        assert c.pad_token_id is None

    def test_from_dict_unknown_key_raises(self):
        with pytest.raises(ValueError, match="unknown GenerationConfig keys"):
            load_config({"seed": 1, "bogus": True})

    def test_from_dict_unsupported_schema_raises(self):
        with pytest.raises(ValueError, match="unsupported GenerationConfig schema"):
            load_config({"schema_version": "9"})

    def test_from_dict_non_dict_raises(self):
        with pytest.raises(TypeError, match="expects a dict"):
            load_config([1, 2, 3])


# --------------------------------------------------------------------------- #
# Configuration loading (dict + file)
# --------------------------------------------------------------------------- #
class TestConfigurationLoading:
    def test_load_policy_dict(self):
        p = load_policy({"family": "math"})
        assert p.family == "math"
        assert p.version == GENERATION_POLICY_VERSION

    def test_load_policy_file(self, tmp_path):
        p = family_default_policy("code")
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(p.to_dict()), encoding="utf-8")
        q = load_policy_file(path)
        assert q == p

    def test_load_config_file(self, tmp_path):
        c = default_generation_config()
        path = tmp_path / "config.json"
        path.write_text(json.dumps(c.to_dict()), encoding="utf-8")
        d = load_config_file(path)
        assert d == c

    def test_load_config_file_rejects_non_object(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(TypeError, match="expected a JSON object"):
            load_config_file(path)

    def test_file_loading_rejects_unsupported_version(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps({"schema_version": "42"}), encoding="utf-8")
        with pytest.raises(ValueError, match="unsupported GenerationConfig schema"):
            load_config_file(path)


# --------------------------------------------------------------------------- #
# GenerationValidation
# --------------------------------------------------------------------------- #
class TestGenerationValidation:
    def test_valid_policy(self):
        for fam in SUPPORTED_FAMILIES:
            result = GenerationValidation.validate_policy(family_default_policy(fam))
            assert result.valid is True
            assert result.issues == ()
            assert result.policy_sha256 == family_default_policy(fam).sha256()

    def test_invalid_family_policy(self):
        bad = GenerationPolicy(family="nope", system_message_text="x",
                               stop_sequence="y", extraction_rule="z",
                               format_accounting=("a",), determinism="d")
        result = GenerationValidation.validate_policy(bad)
        assert result.valid is False
        assert any("unsupported policy family" in i for i in result.issues)

    def test_invalid_unsupported_version_policy(self):
        bad = GenerationPolicy(family="math", version="9.9",
                               system_message_text="x", stop_sequence="y",
                               extraction_rule="z", format_accounting=("a",),
                               determinism="d")
        result = GenerationValidation.validate_policy(bad)
        assert result.valid is False
        assert any("unsupported GenerationPolicy version" in i for i in result.issues)

    def test_invalid_unsupported_budget_rule(self):
        bad = GenerationPolicy(family="math", budget_rule="dynamic-tuning",
                               system_message_text="x", stop_sequence="y",
                               extraction_rule="z", format_accounting=("a",),
                               determinism="d")
        result = GenerationValidation.validate_policy(bad)
        assert result.valid is False
        assert any("budget_rule" in i for i in result.issues)

    def test_invalid_empty_extraction(self):
        bad = GenerationPolicy(family="math", extraction_rule="",
                               system_message_text="x", stop_sequence="y",
                               format_accounting=("a",), determinism="d")
        assert GenerationValidation.validate_policy(bad).valid is False

    def test_valid_config(self):
        result = GenerationValidation.validate_config(default_generation_config())
        assert result.valid is True

    def test_invalid_sampling(self):
        c = load_config({"sampling": "sampling-topk", "do_sample": True})
        result = GenerationValidation.validate_config(c)
        assert result.valid is False
        assert any("sampling" in i for i in result.issues)
        assert any("do_sample must be False" in i for i in result.issues)

    def test_greedy_requires_temperature_none_or_one(self):
        c = load_config({"temperature": 0.7, "do_sample": True})
        result = GenerationValidation.validate_config(c)
        assert any("temperature" in i for i in result.issues)

    def test_greedy_requires_top_p_none_or_one(self):
        c = load_config({"top_p": 0.9})
        result = GenerationValidation.validate_config(c)
        assert any("top_p" in i for i in result.issues)

    def test_budget_fallback_bounds(self):
        c = load_config({"max_budget": 512, "budget_fallback": 1024})
        result = GenerationValidation.validate_config(c)
        assert any("budget_fallback" in i for i in result.issues)

    def test_pad_must_equal_eos(self):
        c = load_config({"eos_token_id": 151645, "pad_token_id": 0})
        result = GenerationValidation.validate_config(c)
        assert any("pad_token_id must equal eos_token_id" in i for i in result.issues)

    def test_pad_equal_eos_ok(self):
        c = load_config({"eos_token_id": 151645, "pad_token_id": 151645})
        assert GenerationValidation.validate_config(c).valid is True

    def test_validate_pair_stop_mismatch(self):
        p = family_default_policy("math")
        c = load_config({"stop_sequence": "|other|"})
        result = GenerationValidation.validate_pair(p, c)
        assert result.valid is False
        assert any("stop_sequence" in i for i in result.issues)

    def test_validate_pair_ok(self):
        p = family_default_policy("math")
        c = default_generation_config()
        assert GenerationValidation.validate_pair(p, c).valid is True

    def test_validate_budget_result(self):
        r = DEFAULT_STATIC_BUDGET.compute("ref", token_counter=_counter(10))
        assert GenerationValidation.validate_budget_result(r).valid is True

    def test_validate_budget_result_fallback(self):
        r = DEFAULT_STATIC_BUDGET.compute("ref")
        assert GenerationValidation.validate_budget_result(r).valid is True

    def test_validate_budget_result_inconsistent(self):
        r = BudgetResult(budget=999, rule="x", reference_tokens=None,
                         fallback_used=True, capped=False, floor_applied=False)
        result = GenerationValidation.validate_budget_result(r)
        assert result.valid is False

    def test_validation_result_immutable_and_to_dict(self):
        result = ValidationResult(valid=True, issues=())
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.valid = False
        assert result.to_dict()["valid"] is True

    def test_module_level_convenience(self):
        from evaluation_engine.generation_policy import (
            run_config_validation, run_policy_validation,
        )
        assert run_policy_validation(family_default_policy("math")).valid is True
        assert run_config_validation(default_generation_config()).valid is True


# --------------------------------------------------------------------------- #
# GenerationMetadata
# --------------------------------------------------------------------------- #
class TestGenerationMetadata:
    def test_policy_block_hashes(self):
        p = family_default_policy("math")
        block = GenerationMetadata.policy_block(p)
        assert block["policy_sha256"] == p.sha256()
        assert len(block["policy_block_sha256"]) == 64

    def test_config_block_hashes(self):
        c = default_generation_config()
        block = GenerationMetadata.config_block(c)
        assert block["config_sha256"] == c.sha256()
        assert len(block["config_block_sha256"]) == 64

    def test_run_policy_lock_block_deterministic(self):
        p = family_default_policy("code")
        c = default_generation_config()
        r1 = DEFAULT_STATIC_BUDGET.compute("gold patch", token_counter=_counter(200))
        r2 = DEFAULT_STATIC_BUDGET.compute("gold patch 2", token_counter=_counter(400))
        a = GenerationMetadata.run_policy_lock_block(p, c, "tpl-sha", [r1, r2])
        b = GenerationMetadata.run_policy_lock_block(p, c, "tpl-sha", [r1, r2])
        assert a == b
        assert len(a["block_sha256"]) == 64

    def test_run_policy_lock_block_contents(self):
        p = family_default_policy("math")
        c = load_config({"eos_token_id": 151645, "pad_token_id": 151645})
        r = DEFAULT_STATIC_BUDGET.compute("ref", token_counter=_counter(10))
        block = GenerationMetadata.run_policy_lock_block(p, c, "tpl-sha", [r])
        assert block["policy_sha256"] == p.sha256()
        assert block["config_sha256"] == c.sha256()
        assert block["template_version"] == p.template_version
        assert block["prompt_template_sha256"] == "tpl-sha"
        assert block["eos_token_id"] == 151645
        assert block["budget_rule"] == RULE_DYNAMIC_REFERENCE_DERIVED
        assert block["extraction_rule"] == p.extraction_rule
        assert block["per_record_budgets"][0]["budget"] == r.budget

    def test_covariates(self):
        results = [
            DEFAULT_STATIC_BUDGET.compute("a", token_counter=_counter(100)),
            DEFAULT_STATIC_BUDGET.compute("b", token_counter=_counter(5000)),
            DEFAULT_STATIC_BUDGET.compute("c"),  # fallback
        ]
        cov = GenerationMetadata.covariates(results)
        assert cov["n"] == 3
        assert cov["fallback_rate"] == pytest.approx(1 / 3, abs=1e-4)
        assert cov["cap_rate"] == pytest.approx(1 / 3, abs=1e-4)
        assert cov["budget_mean"] is not None

    def test_covariates_empty_not_fabricated(self):
        cov = GenerationMetadata.covariates([])
        assert cov["n"] == 0
        assert cov["budget_mean"] is None
        assert cov["fallback_rate"] == 0.0

    def test_per_record_metadata(self):
        r = DEFAULT_STATIC_BUDGET.compute("ref", token_counter=_counter(50))
        md = GenerationMetadata.per_record_metadata("rid_1", r, "prompt-hash")
        assert md["record_id"] == "rid_1"
        assert md["prompt_sha256"] == "prompt-hash"
        assert md["budget"] == r.budget
        assert md["budget_fallback_used"] == r.fallback_used

    def test_generation_policy_summary(self):
        p = family_default_policy("math")
        c = default_generation_config()
        s = GenerationMetadata.generation_policy_summary(p, c, "tpl-sha")
        assert s["family"] == "math"
        assert s["policy_sha256"] == p.sha256()
        assert s["config_sha256"] == c.sha256()


# --------------------------------------------------------------------------- #
# Determinism end-to-end
# --------------------------------------------------------------------------- #
class TestEndToEndDeterminism:
    def test_policy_config_validation_chain(self):
        for fam in SUPPORTED_FAMILIES:
            p = family_default_policy(fam)
            c = default_generation_config()
            assert GenerationValidation.validate_policy(p).valid is True
            assert GenerationValidation.validate_config(c).valid is True
            assert GenerationValidation.validate_pair(p, c).valid is True

    def test_repeat_build_identical_hashes(self):
        def build():
            p = family_default_policy("code")
            c = load_config({"eos_token_id": 151645, "pad_token_id": 151645})
            return p.sha256(), c.sha256(), GenerationMetadata.run_policy_lock_block(
                p, c, "tpl-sha", [
                    DEFAULT_STATIC_BUDGET.compute(
                        "gold", token_counter=_counter(80))
                ])["block_sha256"]

        assert build() == build()

    def test_supported_budget_rules_contain_canonical(self):
        assert RULE_REFERENCE_DERIVED in SUPPORTED_BUDGET_RULES
        assert "fixed-fallback" in SUPPORTED_BUDGET_RULES
        assert RULE_DYNAMIC_REFERENCE_DERIVED in SUPPORTED_BUDGET_RULES
        assert "dynamic-tuning" not in SUPPORTED_BUDGET_RULES


# --------------------------------------------------------------------------- #
# DynamicBudgetStrategy (Sprint 5A.6)
# --------------------------------------------------------------------------- #
class TestDynamicBudgetStrategy:
    def test_implements_interface(self):
        from evaluation_engine.generation_policy import DynamicBudgetStrategy
        strat = DynamicBudgetStrategy(
            base_budget=128, alpha=3.0, minimum_budget=256, maximum_budget=4096,
        )
        assert hasattr(strat, "compute")
        assert hasattr(strat, "rule")

    def test_math_calibrated_params(self):
        from evaluation_engine.generation_policy import DynamicBudgetStrategy
        strat = DynamicBudgetStrategy(
            base_budget=128, alpha=3.0, minimum_budget=256, maximum_budget=4096,
        )
        # N=10 -> 128 + ceil(30) = 158 -> floored to 256
        r = strat.compute("x", token_counter=_counter(10))
        assert r.budget == 256
        assert r.floor_applied is True
        # N=100 -> 128 + 300 = 428
        r2 = strat.compute("x", token_counter=_counter(100))
        assert r2.budget == 428
        assert r2.floor_applied is False
        # N=1200 -> 128 + 3600 = 3728
        r3 = strat.compute("x", token_counter=_counter(1200))
        assert r3.budget == 3728
        # N=2000 -> 128 + 6000 = 6128 -> capped at 4096
        r4 = strat.compute("x", token_counter=_counter(2000))
        assert r4.budget == 4096
        assert r4.capped is True

    def test_code_calibrated_params(self):
        from evaluation_engine.generation_policy import DynamicBudgetStrategy
        strat = DynamicBudgetStrategy(
            base_budget=256, alpha=2.0, minimum_budget=256, maximum_budget=4096,
        )
        # N=50 -> 256 + 100 = 356
        r = strat.compute("x", token_counter=_counter(50))
        assert r.budget == 356
        # N=10 -> 256 + 20 = 276 (above floor)
        r2 = strat.compute("x", token_counter=_counter(10))
        assert r2.budget == 276

    def test_rule_string_matches_formula(self):
        from evaluation_engine.generation_policy import DynamicBudgetStrategy
        strat = DynamicBudgetStrategy(
            base_budget=128, alpha=3.5, minimum_budget=256, maximum_budget=4096,
        )
        assert "128" in strat.rule
        assert "3.5" in strat.rule
        assert "256" in strat.rule
        assert "4096" in strat.rule

    def test_fixed_fallback(self):
        from evaluation_engine.generation_policy import DynamicBudgetStrategy
        strat = DynamicBudgetStrategy(
            base_budget=128, alpha=3.0, minimum_budget=256, maximum_budget=4096,
        )
        r = strat.fixed_fallback()
        assert r.budget == strat.fallback_budget
        assert r.rule == "fixed-fallback"
        assert r.fallback_used is True

    def test_no_counter_uses_fallback(self):
        from evaluation_engine.generation_policy import DynamicBudgetStrategy
        strat = DynamicBudgetStrategy(
            base_budget=128, alpha=3.0, minimum_budget=256, maximum_budget=4096,
        )
        r = strat.compute("ref")
        assert r.budget == strat.fallback_budget
        assert r.fallback_used is True

    def test_counter_failure_uses_fallback(self):
        from evaluation_engine.generation_policy import DynamicBudgetStrategy
        strat = DynamicBudgetStrategy(
            base_budget=128, alpha=3.0, minimum_budget=256, maximum_budget=4096,
        )
        r = strat.compute("ref", token_counter=lambda t: 1/0)
        assert r.budget == strat.fallback_budget
        assert r.fallback_used is True

    def test_deterministic(self):
        from evaluation_engine.generation_policy import DynamicBudgetStrategy
        strat = DynamicBudgetStrategy(
            base_budget=128, alpha=3.0, minimum_budget=256, maximum_budget=4096,
        )
        a = strat.compute("ref", token_counter=_counter(100))
        b = strat.compute("ref", token_counter=_counter(100))
        assert a == b

    def test_immutable(self):
        from evaluation_engine.generation_policy import DynamicBudgetStrategy
        strat = DynamicBudgetStrategy(
            base_budget=128, alpha=3.0, minimum_budget=256, maximum_budget=4096,
        )
        with pytest.raises(Exception):  # noqa: B017 - frozen dataclass
            strat.base_budget = 999

    def test_to_dict_round_trip(self):
        from evaluation_engine.generation_policy import DynamicBudgetStrategy
        s1 = DynamicBudgetStrategy(
            base_budget=200, alpha=2.5, minimum_budget=300, maximum_budget=3500,
        )
        d = {
            "base_budget": s1.base_budget,
            "alpha": s1.alpha,
            "minimum_budget": s1.minimum_budget,
            "maximum_budget": s1.maximum_budget,
            "fallback_budget": s1.fallback_budget,
        }
        s2 = DynamicBudgetStrategy(**d)
        assert s1 == s2


# --------------------------------------------------------------------------- #
# Strategy selection from GenerationPolicy (Sprint 5A.6)
# --------------------------------------------------------------------------- #
class TestStrategySelection:
    def test_family_policy_selects_dynamic(self):
        for fam in ("math", "code", "semantic"):
            p = family_default_policy(fam)
            assert p.budget_strategy == "dynamic"
            assert p.budget_params is not None
            assert p.budget_rule == RULE_DYNAMIC_REFERENCE_DERIVED

    def test_dynamic_policy_from_dict(self):
        p = GenerationPolicy.from_dict({
            "family": "math",
            "budget_strategy": "dynamic",
            "budget_params": {"base_budget": 200, "alpha": 2.5,
                              "minimum_budget": 300, "maximum_budget": 3500},
        })
        assert p.budget_strategy == "dynamic"
        assert p.budget_params["alpha"] == 2.5

    def test_static_policy_from_dict(self):
        p = GenerationPolicy.from_dict({
            "family": "math",
            "budget_strategy": "static",
        })
        assert p.budget_strategy == "static"
        assert p.budget_params is None

    def test_policy_from_dict_backwards_compat(self):
        """A dict without budget_strategy defaults to static (backward compat)."""
        p = GenerationPolicy.from_dict({"family": "math"})
        # from_family sets dynamic; from_dict without explicit strategy
        # falls through to the _pick default of "static"
        assert p.budget_strategy == "static"
        assert p.budget_rule == RULE_REFERENCE_DERIVED

    def test_policy_from_dict_rejects_unknown_strategy(self):
        p = GenerationPolicy.from_dict({
            "family": "math", "budget_strategy": "quantum"})
        from evaluation_engine.generation_policy import GenerationValidation
        v = GenerationValidation.validate_policy(p)
        assert v.valid is False
        assert any("budget_strategy" in i for i in v.issues)

    def test_policy_from_dict_rejects_invalid_dynamic_params(self):
        p = GenerationPolicy.from_dict({
            "family": "math", "budget_strategy": "dynamic",
            "budget_params": {"base_budget": -1, "alpha": 1.0,
                              "minimum_budget": 256, "maximum_budget": 4096},
        })
        from evaluation_engine.generation_policy import GenerationValidation
        v = GenerationValidation.validate_policy(p)
        assert v.valid is False
        assert any("base_budget must be an int" in i for i in v.issues)

    def test_policy_from_dict_rejects_dynamic_missing_params(self):
        # Missing required keys -> validate_policy fails
        p = GenerationPolicy.from_dict({
            "family": "math", "budget_strategy": "dynamic",
            "budget_params": {"alpha": 3.0},  # missing keys
        })
        from evaluation_engine.generation_policy import GenerationValidation
        v = GenerationValidation.validate_policy(p)
        assert v.valid is False
        assert any("missing keys" in i for i in v.issues)

    def test_policy_from_dict_rejects_bad_alpha(self):
        p = GenerationPolicy.from_dict({
            "family": "math", "budget_strategy": "dynamic",
            "budget_params": {"base_budget": 128, "alpha": 0.0,
                              "minimum_budget": 256, "maximum_budget": 4096},
        })
        from evaluation_engine.generation_policy import GenerationValidation
        v = GenerationValidation.validate_policy(p)
        assert v.valid is False
        assert any("alpha must be a positive" in i for i in v.issues)

    def test_policy_round_trip_dynamic(self):
        p = family_default_policy("math")
        d = p.to_dict()
        assert d["budget_strategy"] == "dynamic"
        assert d["budget_params"] is not None
        q = GenerationPolicy.from_dict(d)
        assert q == p
        assert q.sha256() == p.sha256()


# --------------------------------------------------------------------------- #
# Backward compatibility (Sprint 5A.6)
# --------------------------------------------------------------------------- #
class TestBackwardCompatibility:
    def test_static_budget_unaffected(self):
        r = DEFAULT_STATIC_BUDGET.compute("ref", token_counter=_counter(100))
        assert r.budget == 128 + math.ceil(1.5 * 100)

    def test_default_policy_pre_sprint5a6_signature(self):
        """A policy created without budget_strategy/budget_params fields
        should still be valid and use static budget."""
        p = GenerationPolicy(
            family="math",
            system_message_text="x",
            system_message_sha256="y",
            policy_lock_sha256="z",
            extraction_rule="r",
            format_accounting=("a",),
            determinism="d",
        )
        from evaluation_engine.generation_policy import GenerationValidation
        v = GenerationValidation.validate_policy(p)
        assert v.valid is True
        assert p.budget_strategy == "static"

    def test_dynamic_policy_with_static_rule(self):
        """A dynamic strategy with budget_rule set to the canonical string
        is still valid (rule string is metadata, not functional)."""
        p = GenerationPolicy.from_dict({
            "family": "math",
            "budget_strategy": "dynamic",
            "budget_params": {"base_budget": 128, "alpha": 3.0,
                              "minimum_budget": 256, "maximum_budget": 4096},
            "budget_rule": RULE_REFERENCE_DERIVED,
        })
        from evaluation_engine.generation_policy import GenerationValidation
        v = GenerationValidation.validate_policy(p)
        assert v.valid is True

