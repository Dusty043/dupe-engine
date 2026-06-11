# Handoff: Dupe Engine v0.6

## Intent

v0.6 continues the AI-light approach:

```text
deterministic multi-pass
→ candidate hygiene
→ selected embedding support
→ later LLM detector/adjudicator
```

## Major changes from v0.4

- Default visual-all-pages mode is off for scale.
- Low-information pages are annotated and suppressed by default.
- Candidate budgets limit review volume.
- Nested PDF folders are supported.
- Synthetic v2 truth format is supported.
- OpenAI-compatible embeddings can run as a selected-candidate detector.

## Validation commands

```bash
PYTHONPATH=src python -m pytest -q
```

```bash
PYTHONPATH=src python -m dupe_engine.cli doctor --json
```

```bash
PYTHONPATH=src python -m dupe_engine.cli eval-all ./examples/synthetic_medical_pdf_corpus/pdfs \
  --truth ./examples/truth/synthetic_all_pairs_truth.json \
  --out output/all_pairs_results.json \
  --eval-out output/all_pairs_eval.json \
  --html output/all_pairs_report.html \
  --csv output/all_pairs_matches.csv \
  --pages-out output/all_pairs_pages.json
```

For Synthetic v2 medium:

```bash
PYTHONPATH=src python -m dupe_engine.cli eval-all /mnt/data/synthetic_corpus_v2_medium/pdfs \
  --truth /mnt/data/synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --dpi 36 \
  --out output/synthetic_v2_results.json \
  --eval-out output/synthetic_v2_eval.json \
  --html output/synthetic_v2_report.html \
  --csv output/synthetic_v2_matches.csv \
  --pages-out output/synthetic_v2_pages.json
```

## Embeddings

Embeddings are disabled by default.

```bash
DUPE_EMBEDDINGS_ENABLED=true
DUPE_EMBEDDINGS_PROVIDER=openai
DUPE_EMBEDDINGS_MODEL=text-embedding-3-small
DUPE_OPENAI_API_KEY=...
```

When enabled and available, embeddings only run on deterministic candidates selected by escalation policy.

## Next suggested version

v0.7 should focus on OCR, because Synthetic v2 still contains image-only/OCR-dependent duplicates that embeddings cannot help unless text exists first.
