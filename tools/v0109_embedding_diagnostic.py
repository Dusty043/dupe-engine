#!/usr/bin/env python3
"""v0.10.9 offline diagnostic: pure embedding TP vs KN comparison.

Run from the project root after a v0.10.8 widened run:

    python tools/v0109_embedding_diagnostic.py /data/runs/my_run/candidate_summary.csv
    python tools/v0109_embedding_diagnostic.py /data/runs/my_run/candidate_summary.csv --out-dir /tmp/diag
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dupe_engine.embedding_diagnostic import main

if __name__ == "__main__":
    raise SystemExit(main())
