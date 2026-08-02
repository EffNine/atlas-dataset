"""Entry point: python -m expert_pipeline (from the scripts/ directory)."""

from __future__ import annotations

import sys

from .runner import main

if __name__ == "__main__":
    sys.exit(main())
