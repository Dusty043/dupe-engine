# Synthetic Medical PDF Duplicate Test Corpus

This ZIP contains synthetic, fictional medical-looking PDF files for testing duplicate and near-duplicate detection. It contains no real patient data and is not for clinical use.

## Included categories

1. Exact duplicate pages
2. Near-duplicate visual pages
3. Same text, different formatting
4. Same page with different scan quality
5. Similar medical-looking content but not duplicate
6. OCR/scanned image-only pages
7. Header/footer/page-number noise
8. Partial overlaps
9. Multi-document / multi-page batches
10. Negative controls

## Files

- `pdfs/` - generated PDF corpus
- `manifest.csv` - page-level labels, duplicate groups, text-layer expectations, and notes
- `ground_truth.json` - grouped labels for programmatic evaluation

Total PDFs: 11
Total pages: 34

Every page includes synthetic wording or metadata indicating that it is not a real patient record.
