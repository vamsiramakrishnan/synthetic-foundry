#!/usr/bin/env python3
"""Checkout compatibility entry point; implementation lives in the library."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from worldloom.process_bindings.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
