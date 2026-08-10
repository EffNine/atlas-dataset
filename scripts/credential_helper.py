"""
Credential helper — load Hugging Face tokens from environment only.

Usage:
    export HF_TOKEN=hf_xxx
    python script.py

On startup, import get_hf_token() to validate that the credential is configured.
The function reports whether the credential is present, never its value.
"""
from __future__ import annotations

import os
import sys


_REQUIRED_ENV = "HF_TOKEN"


def get_hf_token() -> str:
    """Return the Hugging Face token from HF_TOKEN env var.

    Raises SystemExit if the variable is not set (fail-closed).
    Never prints or logs the token value.
    """
    token = os.environ.get(_REQUIRED_ENV, "")
    if not token:
        print(
            f"ERROR: environment variable {_REQUIRED_ENV} is not set.\n"
            f"Set it before running this script, e.g.:\n"
            f"  export {_REQUIRED_ENV}=hf_xxx",
            file=sys.stderr,
        )
        sys.exit(1)
    return token


def check_credential() -> dict:
    """Return a status dict indicating whether the credential is configured.

    The token value is never included in the output.
    """
    token = os.environ.get(_REQUIRED_ENV, "")
    return {
        "configured": bool(token),
        "env_var": _REQUIRED_ENV,
        "token_prefix": (token[:8] + "..." if len(token) > 8 else "[short]"),
    }


if __name__ == "__main__":
    status = check_credential()
    print(f"Credential check: configured={status['configured']}")
    if not status["configured"]:
        sys.exit(1)
    print(f"Token present (prefix: {status['token_prefix']})")
