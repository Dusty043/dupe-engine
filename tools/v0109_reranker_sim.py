"""v0.10.9 reranker offline simulation CLI.

Usage:
    python tools/v0109_reranker_sim.py /path/to/candidate_summary.csv [options]

Options:
    --out-dir PATH              Output directory (default: ./reranker_sim_out)
    --min-confidence FLOAT      Scoring threshold (default: 0.80)
    --ocr-penalty FLOAT         Per-OCR-page penalty (default: 0.01)
    --same-doc-bonus FLOAT      Same-document bonus (default: 0.03)
    --tesseract-bonus FLOAT     Per-Tesseract-usable-page bonus (default: 0.02)
    --action demote|drop        Action for low-scoring rows (default: demote)
    --threshold-start FLOAT     Sweep start (default: 0.80)
    --threshold-end FLOAT       Sweep end inclusive (default: 0.94)
    --threshold-step FLOAT      Sweep step (default: 0.02)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root without installing the package
_repo_src = Path(__file__).resolve().parent.parent / "src"
if str(_repo_src) not in sys.path:
    sys.path.insert(0, str(_repo_src))

from dupe_engine.embedding_reranker import RerankerParams
from dupe_engine.reranker_sim import simulate, write_outputs


def _build_thresholds(start: float, end: float, step: float) -> list[float]:
    thresholds: list[float] = []
    t = round(start, 4)
    while t <= round(end + 1e-9, 4):
        thresholds.append(round(t, 4))
        t = round(t + step, 4)
    return thresholds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="v0.10.9 offline reranker simulation: estimate TP/KN action rates at each threshold"
    )
    parser.add_argument("csv_path", type=Path, help="Path to candidate_summary.csv")
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory (default: ./reranker_sim_out)")
    parser.add_argument("--min-confidence", type=float, default=0.80, metavar="FLOAT")
    parser.add_argument("--ocr-penalty", type=float, default=0.01, metavar="FLOAT")
    parser.add_argument("--same-doc-bonus", type=float, default=0.03, metavar="FLOAT")
    parser.add_argument("--tesseract-bonus", type=float, default=0.02, metavar="FLOAT")
    parser.add_argument("--action", choices=["demote", "drop"], default="demote")
    parser.add_argument("--threshold-start", type=float, default=0.80, metavar="FLOAT")
    parser.add_argument("--threshold-end", type=float, default=0.94, metavar="FLOAT")
    parser.add_argument("--threshold-step", type=float, default=0.02, metavar="FLOAT")
    args = parser.parse_args(argv)

    csv_path = args.csv_path
    out_dir = args.out_dir or Path("reranker_sim_out")

    params = RerankerParams(
        min_confidence=args.min_confidence,
        ocr_penalty=args.ocr_penalty,
        same_doc_bonus=args.same_doc_bonus,
        tesseract_bonus=args.tesseract_bonus,
        action=args.action,
    )
    thresholds = _build_thresholds(args.threshold_start, args.threshold_end, args.threshold_step)

    print(f"Running reranker simulation on: {csv_path}")
    print(f"  action={params.action}  min_confidence={params.min_confidence}  "
          f"ocr_penalty={params.ocr_penalty}  same_doc_bonus={params.same_doc_bonus}  "
          f"tesseract_bonus={params.tesseract_bonus}")
    print(f"  threshold sweep: {thresholds[0]:.2f} → {thresholds[-1]:.2f} step {args.threshold_step:.2f}")

    result = simulate(csv_path, params, thresholds)
    write_outputs(result, out_dir)

    cohort = result.get("cohort") or {}
    recommended = result.get("recommended") or {}
    warnings = result.get("missing_field_warnings") or []

    if warnings:
        print(f"  WARNING: missing fields defaulted to False: {', '.join(warnings)}")

    print(f"\nCohort (pure embedding rows: {result.get('pure_embedding_count')}):")
    print(f"  TP={cohort.get('tp', 0)}  KN={cohort.get('kn', 0)}  "
          f"Partial={cohort.get('partial', 0)}  Unlabeled={cohort.get('unlabeled', 0)}")

    if recommended:
        tp_rate = recommended.get("tp_action_rate", 0.0)
        kn_rate = recommended.get("kn_action_rate", 0.0)
        print(f"\nRecommended threshold: {recommended.get('threshold')}")
        print(f"  TP actioned: {recommended.get('tp_demoted_or_dropped')}/{recommended.get('tp_total')} "
              f"({tp_rate * 100:.1f}%)")
        print(f"  KN actioned: {recommended.get('kn_demoted_or_dropped')}/{recommended.get('kn_total')} "
              f"({kn_rate * 100:.1f}%)")
        print(f"  Estimated review rows removed: {recommended.get('estimated_review_rows_removed')}")

    print(f"\nOutputs written to: {out_dir}")
    print(f"  - {out_dir / 'reranker_sim.md'}")
    print(f"  - {out_dir / 'reranker_sim.json'}")
    print(f"  - {out_dir / 'reranker_sim_sweep.csv'}")
    print(f"  - {out_dir / 'reranker_sim_rows.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
