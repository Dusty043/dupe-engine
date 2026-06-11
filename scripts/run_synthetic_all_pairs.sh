#!/usr/bin/env bash
set -euo pipefail

python -m dupe_engine.cli eval-all ./examples/synthetic_medical_pdf_corpus/pdfs \
  --truth ./examples/truth/synthetic_all_pairs_truth.json \
  --out output/synthetic_all_pairs_results.json \
  --eval-out output/synthetic_all_pairs_eval.json \
  --csv output/synthetic_all_pairs_matches.csv \
  --html output/synthetic_all_pairs_report.html \
  --pages-out output/synthetic_all_pairs_pages.json
