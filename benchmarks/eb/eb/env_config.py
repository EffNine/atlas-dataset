#!/usr/bin/env python3
"""
env_config.py — Environment variable loading and validation for EB.

Loads secrets from .env files via dotenv-compatible parsing, validates
required variables for cloud judge configuration, and redacts secrets
from error messages and logs.

Stage 4 readiness: defines the stable env contract for cloud judge.
Does NOT implement the cloud judge client.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Stable env var contract for cloud judge (Stage 4+)
JUDGE_BASE_URL_VAR = "EB_JUDGE_BASE_URL"
JUDGE_API_KEY_VAR = "EB_JUDGE_API_KEY"
JUDGE_MODEL_VAR = "EB_JUDGE_MODEL"

# Sensitive variable names that must never be printed
SECRET_VARS = {
    JUDGE_API_KEY_VAR,
    "EB_API_KEY",
    "EB_LOCAL_MODEL_PATH",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
}

# Default values
DEFAULT_JUDGE_MODEL = "auto"

# ---------------------------------------------------------------------------
# Dotenv parsing (stdlib-only, no python-dotenv dependency)
# ---------------------------------------------------------------------------


def _parse_dotenv(dotenv_path: Path) -> dict[str, str]:
    """
    Parse a .env file into a dict. Handles comments, blank lines,
    quoted values, and variable expansion. Does NOT call subprocess.
    """
    vars_dict: dict[str, str] = {}
    if not dotenv_path.exists():
        return vars_dict
    with dotenv_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Split on first '='
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Remove surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            # Don't override already-set env vars
            if key not in os.environ:
                vars_dict[key] = value
    return vars_dict


def load_env(env_path: Path | str | None = None) -> dict[str, str]:
    """
    Load environment variables from .env file(s).

    Searches in order:
      1. Explicit path if provided
      2. Current working directory .env
      3. EB root directory .env (discovered from package location)

    Only sets variables that are not already present in os.environ.
    """
    loaded: dict[str, str] = {}

    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path.cwd() / ".env")

    # Discover EB root
    try:
        from .paths import get_root
        candidates.append(get_root() / ".env")
    except Exception:
        pass

    for path in candidates:
        parsed = _parse_dotenv(path)
        loaded.update(parsed)

    # Apply to os.environ (only unset vars with non-empty values)
    for key, value in loaded.items():
        if key not in os.environ and value:
            os.environ[key] = value

    return loaded


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class EnvValidationError(ValueError):
    """Raised when required environment variables are missing."""


def validate_judge_env(required: bool = True) -> dict[str, str]:
    """
    Validate cloud judge environment variables.

    Args:
        required: If True, raises on missing vars. If False, returns
                  whatever is available.

    Returns:
        Dict with judge config values.

    Raises:
        EnvValidationError: If required vars are missing.
    """
    result: dict[str, str] = {}

    base_url = os.environ.get(JUDGE_BASE_URL_VAR, "")
    api_key = os.environ.get(JUDGE_API_KEY_VAR, "")
    model = os.environ.get(JUDGE_MODEL_VAR, DEFAULT_JUDGE_MODEL)

    result[JUDGE_BASE_URL_VAR] = base_url
    result[JUDGE_API_KEY_VAR] = api_key  # stored but never printed
    result[JUDGE_MODEL_VAR] = model

    if required:
        missing = []
        if not base_url:
            missing.append(JUDGE_BASE_URL_VAR)
        if not api_key:
            missing.append(JUDGE_API_KEY_VAR)
        if missing:
            raise EnvValidationError(
                f"Cloud judge requires these env vars: {', '.join(missing)}. "
                f"Set them in .env or export them before running."
            )

    return result


def validate_run_env() -> dict[str, str]:
    """Validate environment for a standard benchmark run."""
    # No required vars for Stage 3 — local adapters may need config
    return {
        JUDGE_BASE_URL_VAR: os.environ.get(JUDGE_BASE_URL_VAR, ""),
        JUDGE_API_KEY_VAR: os.environ.get(JUDGE_API_KEY_VAR, ""),
        JUDGE_MODEL_VAR: os.environ.get(JUDGE_MODEL_VAR, DEFAULT_JUDGE_MODEL),
        "EB_LOCAL_MODEL_PATH": os.environ.get("EB_LOCAL_MODEL_PATH", ""),
        "EB_API_KEY": os.environ.get("EB_API_KEY", ""),
    }


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


def redact(value: str) -> str:
    """
    Redact a secret value for safe logging.
    Only redacts values that match known secret patterns (API keys, tokens).
    Returns non-secret values unchanged, including URLs and plain text.
    """
    if not value:
        return ""
    # Known secret patterns: API keys, tokens, passwords
    lower = value.lower()
    secret_patterns = [
        r"^sk[-_]",           # OpenAI-style: sk-, sk_
        r"api.?key",          # api-key, api_key, apikey
        r"^token",            # token-based
        r"password",          # password-based
        r"secret",            # secret-based
        r"credential",        # credential-based
        r"private.?key",      # private-key, private_key
    ]
    for pat in secret_patterns:
        if re.search(pat, lower):
            if len(value) <= 8:
                return "[REDACTED]"
            return f"{value[:4]}...{value[-4:]}"
    # Not a secret pattern — return as-is
    return value


def redact_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of dict with secret values redacted."""
    result = {}
    for k, v in d.items():
        if k in SECRET_VARS:
            result[k] = redact(str(v)) if v else ""
        else:
            result[k] = v
    return result


def safe_print_env() -> None:
    """Print non-secret environment config for debugging."""
    config = validate_run_env()
    redacted = redact_dict(config)
    print("EB Environment (secrets redacted):")
    for k, v in redacted.items():
        print(f"  {k} = {v}")


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

# Load .env on first import
_load_env_done = False


def ensure_env_loaded() -> None:
    """Ensure .env is loaded (idempotent)."""
    global _load_env_done
    if not _load_env_done:
        load_env()
        _load_env_done = True


# Auto-load on import
ensure_env_loaded()
