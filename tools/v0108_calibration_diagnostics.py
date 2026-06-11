#!/usr/bin/env python3
"""Wrapper for v0.10.8 calibration diagnostics.

Run from project root after applying the patch:

    python tools/v0108_calibration_diagnostics.py /data/runs/my_run
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dupe_engine.calibration_diagnostics_v0108 import main

if __name__ == "__main__":
    raise SystemExit(main())
