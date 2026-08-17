"""Tests for eb/env_config.py — Environment variable loading and validation."""
import os
import pytest
from pathlib import Path

from eb.env_config import (
    JUDGE_BASE_URL_VAR,
    JUDGE_API_KEY_VAR,
    JUDGE_MODEL_VAR,
    DEFAULT_JUDGE_MODEL,
    load_env,
    validate_judge_env,
    validate_run_env,
    redact,
    redact_dict,
    safe_print_env,
    _parse_dotenv,
    EnvValidationError,
)


class TestParseDotenv:
    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / ".env"
        f.write_text("")
        assert _parse_dotenv(f) == {}

    def test_comments_and_blanks(self, tmp_path: Path):
        f = tmp_path / ".env"
        f.write_text("# comment\n\n  \n  # another\n")
        assert _parse_dotenv(f) == {}

    def test_basic_key_value(self, tmp_path: Path):
        f = tmp_path / ".env"
        f.write_text("FOO=bar\n")
        result = _parse_dotenv(f)
        assert result["FOO"] == "bar"

    def test_quoted_values(self, tmp_path: Path):
        f = tmp_path / ".env"
        f.write_text('NAME="hello world"\nSINGLE=\'single\'\n')
        result = _parse_dotenv(f)
        assert result["NAME"] == "hello world"
        assert result["SINGLE"] == "single"

    def test_does_not_override_env(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("EXISTING", "from_env")
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING=from_file\nNEW=value\n")
        monkeypatch.chdir(tmp_path)
        load_env()
        assert os.environ.get("EXISTING") == "from_env"  # env wins
        assert os.environ.get("NEW") == "value"
        del os.environ["EXISTING"]
        del os.environ["NEW"]

    def test_missing_file(self, tmp_path: Path):
        assert _parse_dotenv(tmp_path / "nonexistent") == {}


class TestLoadEnv:
    def test_loads_from_cwd(self, tmp_path: Path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_LOAD_VAR=loaded\n")
        monkeypatch.chdir(tmp_path)
        loaded = load_env()
        assert os.environ.get("TEST_LOAD_VAR") == "loaded"
        # Cleanup
        del os.environ["TEST_LOAD_VAR"]

    def test_does_not_override_existing(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("ALREADY_SET", "env_value")
        env_file = tmp_path / ".env"
        env_file.write_text("ALREADY_SET=file_value\n")
        monkeypatch.chdir(tmp_path)
        load_env()
        assert os.environ.get("ALREADY_SET") == "env_value"
        del os.environ["ALREADY_SET"]

    def test_idempotent(self, tmp_path: Path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("IDEMP=1\n")
        monkeypatch.chdir(tmp_path)
        load_env()
        load_env()
        assert os.environ.get("IDEMP") == "1"
        del os.environ["IDEMP"]


class TestValidateJudgeEnv:
    def test_all_present(self, monkeypatch):
        monkeypatch.setenv(JUDGE_BASE_URL_VAR, "https://example.com/v1")
        monkeypatch.setenv(JUDGE_API_KEY_VAR, "sk-test-key-1234")
        monkeypatch.setenv(JUDGE_MODEL_VAR, "gpt-4")
        result = validate_judge_env(required=True)
        assert result[JUDGE_BASE_URL_VAR] == "https://example.com/v1"
        assert result[JUDGE_API_KEY_VAR] == "sk-test-key-1234"
        assert result[JUDGE_MODEL_VAR] == "gpt-4"
        del os.environ[JUDGE_BASE_URL_VAR]
        del os.environ[JUDGE_API_KEY_VAR]
        del os.environ[JUDGE_MODEL_VAR]

    def test_missing_url_raises(self, monkeypatch):
        monkeypatch.delenv(JUDGE_BASE_URL_VAR, raising=False)
        monkeypatch.delenv(JUDGE_API_KEY_VAR, raising=False)
        with pytest.raises(EnvValidationError, match="EB_JUDGE_BASE_URL"):
            validate_judge_env(required=True)

    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.setenv(JUDGE_BASE_URL_VAR, "https://example.com/v1")
        monkeypatch.delenv(JUDGE_API_KEY_VAR, raising=False)
        with pytest.raises(EnvValidationError, match="EB_JUDGE_API_KEY"):
            validate_judge_env(required=True)
        del os.environ[JUDGE_BASE_URL_VAR]

    def test_missing_with_required_false(self, monkeypatch):
        monkeypatch.delenv(JUDGE_BASE_URL_VAR, raising=False)
        monkeypatch.delenv(JUDGE_API_KEY_VAR, raising=False)
        result = validate_judge_env(required=False)
        assert result[JUDGE_BASE_URL_VAR] == ""
        assert result[JUDGE_API_KEY_VAR] == ""

    def test_model_defaults_to_auto(self, monkeypatch):
        monkeypatch.delenv(JUDGE_MODEL_VAR, raising=False)
        result = validate_judge_env(required=False)
        assert result[JUDGE_MODEL_VAR] == DEFAULT_JUDGE_MODEL


class TestValidateRunEnv:
    def test_returns_all_vars(self, monkeypatch):
        monkeypatch.setenv(JUDGE_BASE_URL_VAR, "https://ex.com/v1")
        monkeypatch.setenv(JUDGE_API_KEY_VAR, "sk-key")
        monkeypatch.setenv(JUDGE_MODEL_VAR, "auto")
        monkeypatch.setenv("EB_LOCAL_MODEL_PATH", "/models")
        monkeypatch.setenv("EB_API_KEY", "sk-run-key")
        result = validate_run_env()
        assert result[JUDGE_BASE_URL_VAR] == "https://ex.com/v1"
        assert result["EB_LOCAL_MODEL_PATH"] == "/models"
        del os.environ[JUDGE_BASE_URL_VAR]
        del os.environ[JUDGE_API_KEY_VAR]
        del os.environ[JUDGE_MODEL_VAR]
        del os.environ["EB_LOCAL_MODEL_PATH"]
        del os.environ["EB_API_KEY"]


class TestRedact:
    def test_api_key_redacted(self):
        assert "sk-l..." in redact("sk-live-abc123xyz789")

    def test_url_not_redacted(self):
        assert redact("https://example.com/v1") == "https://example.com/v1"

    def test_plain_text_not_redacted(self):
        assert redact("short") == "short"
        assert redact("12345678") == "12345678"
        assert redact("123456789") == "123456789"

    def test_empty_string(self):
        assert redact("") == ""

    def test_token_pattern_redacted(self):
        assert "toke..." in redact("token-abc123xyz789")

    def test_secret_pattern_redacted(self):
        assert "secr..." in redact("secret-key-1234567890")

    def test_api_key_pattern_redacted(self):
        assert "sk-l..." in redact("sk-live-abc123xyz789")
        assert "toke..." in redact("token-xyz123abc456")


class TestRedactDict:
    def test_redacts_secrets(self):
        d = {
            "EB_JUDGE_API_KEY": "sk-secret-key-1234",
            "EB_JUDGE_BASE_URL": "https://example.com/v1",
            "EB_API_KEY": "sk-another-secret",
            "model": "test-model",
        }
        result = redact_dict(d)
        assert "sk-s..." in result["EB_JUDGE_API_KEY"]
        assert result["EB_JUDGE_BASE_URL"] == "https://example.com/v1"
        assert "sk-a..." in result["EB_API_KEY"]
        assert result["model"] == "test-model"

    def test_none_values(self):
        d = {"EB_JUDGE_API_KEY": None, "name": "test"}
        result = redact_dict(d)
        assert result["EB_JUDGE_API_KEY"] == ""
        assert result["name"] == "test"


class TestSafePrintEnv:
    def test_no_crash(self, capsys):
        # Should not raise even with empty env
        safe_print_env()
        captured = capsys.readouterr()
        assert "EB Environment" in captured.out
        assert "sk-" not in captured.out  # no raw secrets


class TestImportStability:
    def test_module_imports_cleanly(self):
        import eb.env_config  # noqa: F401
        # Should not raise on import

    def test_constants_are_correct(self):
        assert JUDGE_BASE_URL_VAR == "EB_JUDGE_BASE_URL"
        assert JUDGE_API_KEY_VAR == "EB_JUDGE_API_KEY"
        assert JUDGE_MODEL_VAR == "EB_JUDGE_MODEL"
        assert DEFAULT_JUDGE_MODEL == "auto"
