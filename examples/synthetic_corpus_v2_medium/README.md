# Synthetic Corpus v2 - Medium Calibration

This corpus contains fabricated medical-looking PDFs for duplicate candidate testing. It contains no real PHI.

Generated profile: medium_calibration
Pages: 375
Documents: 12

Primary question: Does multipass deterministic detection catch likely duplicates without creating an unreviewable candidate explosion?

## Top-level files

- synthetic_v2_manifest.json
- synthetic_v2_page_metadata.json
- synthetic_v2_truth_pairs.json
- synthetic_v2_truth_clusters.json
- synthetic_v2_generation_log.json

PDFs are under pdfs/group_a_received_records through pdfs/group_e_email_records.

## Notes

Engine-run outputs are not populated because no detection engine was run here. Schema/templates are under templates/ for:

- synthetic_v2_all_pairs_results.json
- synthetic_v2_eval.json
- synthetic_v2_candidate_summary.csv
- synthetic_v2_false_positive_review.csv
- synthetic_v2_false_negative_review.csv

Use page_id as the canonical join key between engine output and truth files.
