#!/usr/bin/env python3
"""Compatibility entry point for the supplied compiler's --spec/--all workflow.

The implementation lives in the installed library. Source files no longer need
be in the current working directory. Coverage now distinguishes requested and
applied calibration; output directories must be empty.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from worldloom.process_planning.__main__ import main

if __name__ == "__main__":
    main()
