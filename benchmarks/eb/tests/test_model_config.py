"""Tests for config/models.yaml — Model configuration parsing and validation."""
import pytest
import yaml

from eb.adapters.factory import AdapterFactory
from eb.paths import config_dir


class TestModelsConfig:
    def test_config_file_exists(self):
        cfg = config_dir() / "models.yaml"
        assert cfg.exists()

    def test_loads_yaml(self):
        cfg = config_dir() / "models.yaml"
        with cfg.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "models" in data
        assert isinstance(data["models"], list)
        assert len(data["models"]) > 0

    def test_atan_v1_is_local(self):
        cfg = config_dir() / "models.yaml"
        with cfg.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        atan = next((m for m in data["models"] if m["name"] == "atan-v1"), None)
        assert atan is not None
        assert atan["type"] == "local"
        assert atan["backend"] == "transformers"

    def test_openai_models_have_base_url(self):
        cfg = config_dir() / "models.yaml"
        with cfg.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for m in data["models"]:
            if m["type"] in ("openai_compatible", "openai"):
                assert "base_url" in m, f"Model {m['name']} missing base_url"
                assert "api_key_env" in m, f"Model {m['name']} missing api_key_env"

    def test_future_models_not_in_active_list(self):
        cfg = config_dir() / "models.yaml"
        with cfg.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        names = [m["name"] for m in data["models"]]
        assert "Mira-v1" not in names  # Mira is in future_models, not active models
