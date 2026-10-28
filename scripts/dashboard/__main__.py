#!/usr/bin/env python3
"""Allow `python -m scripts.dashboard.server` invocation."""
from .server import main

raise SystemExit(main())
