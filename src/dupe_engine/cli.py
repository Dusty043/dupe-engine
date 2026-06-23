from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from .ai_ledger import build_ai_call_ledger, write_ai_ledger_csv
from .calibration import build_calibration_report, parse_thresholds, write_rows_csv
from .capabilities import CapabilityReport, ProviderStatus, build_capability_report
from .config import EngineConfig
from .engine import run_ab_compare, run_all_pairs_compare
from .fallback_audit import build_fallback_audit, write_fallback_audit_csv, write_fallback_audit_json
from .evaluation import TruthContext, TruthFileError, build_no_truth_eval_report, evaluate_matches, resolve_truth_context
from .models import PageRecord, TruthPair
from .phase_eval import build_phase_eval_report
from .ocr_metrics import build_ocr_validation_report
from .progress import PROGRESS_ENV, emit_progress, finish_progress, initialize_progress
from .reporting import (
    build_all_pairs_report,
    build_page_records_report,
    build_report,
    write_html_report,
    write_json,
    write_matches_csv,
)
from .ui_artifacts import write_ui_run_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(prog="dupe-engine", description="PDF duplicate page detection engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_doctor_parser(subparsers)
    add_compare_ab_parser(subparsers)
    add_compare_all_parser(subparsers)
    add_eval_ab_parser(subparsers)
    add_eval_all_parser(subparsers)
    add_tui_parser(subparsers)
    add_review_ui_parser(subparsers)
    add_worker_parser(subparsers)
    add_calibrate_parser(subparsers)
    add_calibrate_loop_parser(subparsers)
    add_calibrate_loop_stress_parser(subparsers)
    add_continuous_calibration_parser(subparsers)
    add_prune_calibration_run_parser(subparsers)
    add_analyze_calibration_parser(subparsers)
    add_heal_parser(subparsers)

    args = parser.parse_args()

    # heal is dispatch before build_config — it needs no API keys or engine config
    if args.command == "heal":
        command_heal(args)
        return

    config = build_config(args)

    try:
        if args.command == "doctor":
            command_doctor(args, config)
        elif args.command == "compare-ab":
            command_compare_ab(args, config)
        elif args.command == "compare-all":
            command_compare_all(args, config)
        elif args.command == "eval-ab":
            command_eval_ab(args, config)
        elif args.command == "eval-all":
            command_eval_all(args, config)
        elif args.command == "tui":
            command_tui(args, config)
        elif args.command == "review-ui":
            command_review_ui(args, config)
        elif args.command == "worker":
            command_worker(args, config)
        elif args.command == "calibrate":
            command_calibrate(args, config)
        elif args.command == "calibrate-loop":
            command_calibrate_loop(args, config)
        elif args.command == "calibrate-loop-stress":
            command_calibrate_loop_stress(args, config)
        elif args.command == "continuous-calibration":
            command_continuous_calibration(args, config)
        elif args.command == "prune-calibration-run":
            command_prune_calibration_run(args, config)
        elif args.command == "analyze-calibration":
            command_analyze_calibration(args, config)
        else:
            parser.error(f"Unknown command: {args.command}")
    except TruthFileError as exc:
        raise SystemExit(f"Truth file error: {exc}") from None


def add_optional_ai_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ocr", action="store_true", help="OCR is enabled by default in v0.9.8; kept for backward-compatible scripts")
    parser.add_argument("--openai-ocr", action="store_true", help="OpenAI OCR fallback is enabled by default in v0.9.8; kept for backward-compatible scripts")
    parser.add_argument("--openai-ocr-dry-run", action="store_true", help="Report OpenAI OCR fallback as configured but do not call provider")
    parser.add_argument("--openai-ocr-live", action="store_true", help="Force OpenAI OCR fallback out of dry-run mode for this run; v0.9.8 uses live mode by default unless DUPE_OPENAI_OCR_DRY_RUN=true.")
    parser.add_argument("--embeddings", action="store_true", help="Enable embedding detector provider/status reporting")
    parser.add_argument("--llm-detector", action="store_true", help="Enable LLM candidate detector provider/status reporting")
    parser.add_argument("--adjudicator", action="store_true", help="Enable adjudicator agent provider/status reporting")
    parser.add_argument("--llm", action="store_true", help="Shortcut: enable both --llm-detector and --adjudicator status reporting")
    parser.add_argument("--require-ocr", action="store_true", help="OCR is required by default in v0.9.8; kept for explicit scripts")
    parser.add_argument("--require-openai-ocr", action="store_true", help="OpenAI OCR fallback is required by default in v0.9.8; kept for explicit scripts")
    parser.add_argument("--require-embeddings", action="store_true", help="Fail the run if embeddings are enabled but unavailable")
    parser.add_argument("--require-llm-detector", action="store_true", help="Fail the run if LLM candidate detector is enabled but unavailable")
    parser.add_argument("--require-adjudicator", action="store_true", help="Fail the run if adjudicator is enabled but unavailable")


def add_common_engine_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--work-dir", default="output/work", help="Directory for rendered pages and intermediate files")
    parser.add_argument("--out", default="output/results.json", help="JSON output path")
    parser.add_argument("--csv", default=None, help="Optional CSV output path")
    parser.add_argument("--html", default=None, help="Optional HTML review report path")
    parser.add_argument("--pages-out", default=None, help="Optional page_records.json output path")
    parser.add_argument("--run-dir", default=None, help="Optional v0.8.6 UI-ready run artifact folder")
    parser.add_argument("--ocr-validation-out", default=None, help="Optional v0.8 OCR validation JSON output path")
    parser.add_argument("--ocr-route-csv", default=None, help="Optional v0.8 OCR per-page route CSV output path")
    parser.add_argument("--ocr-candidate-csv", default=None, help="Optional v0.8 OCR-relevant candidate CSV output path")
    parser.add_argument("--ai-ledger-out", default=None, help="Optional v0.8.1 AI/OpenAI route ledger JSON output path")
    parser.add_argument("--ai-ledger-csv", default=None, help="Optional v0.8.1 AI/OpenAI route ledger CSV output path")
    parser.add_argument("--fallback-audit-out", default=None, help="Optional v0.9.8 OpenAI OCR fallback audit JSON output path")
    parser.add_argument("--fallback-audit-csv", default=None, help="Optional v0.9.8 OpenAI OCR fallback per-page audit CSV output path")
    parser.add_argument("--progress-dir", default=None, help="Optional v0.9.8 progress output directory; defaults to --run-dir when provided")
    parser.add_argument("--dpi", type=int, default=None)
    parser.add_argument("--tfidf-threshold", type=float, default=None)
    parser.add_argument("--tfidf-top-k", type=int, default=None)
    parser.add_argument("--phash-threshold", type=int, default=None)
    parser.add_argument("--include-text-preview", action="store_true", help="Include extracted text previews in JSON. Do not use with real PHI unless approved.")
    parser.add_argument("--single-threshold", action="store_true", help="Disable v0.4 deterministic multi-pass mode and use legacy single thresholds")
    parser.add_argument("--strict-phash-threshold", type=int, default=None)
    parser.add_argument("--standard-phash-threshold", type=int, default=None)
    parser.add_argument("--loose-phash-threshold", type=int, default=None)
    parser.add_argument("--strict-tfidf-threshold", type=float, default=None)
    parser.add_argument("--standard-tfidf-threshold", type=float, default=None)
    parser.add_argument("--loose-tfidf-threshold", type=float, default=None)
    parser.add_argument("--multipass-text-top-k", type=int, default=None)
    parser.add_argument("--multipass-visual-all-pages", action="store_true", help="Allow visual strict/standard/loose candidates across all pages; can increase runtime/candidate volume")
    parser.add_argument("--disable-source-safe-ocr-merge", action="store_true", help="Promote accepted OpenAI OCR into canonical best_text instead of keeping it as source-safe sidecar evidence")
    parser.add_argument("--disable-multiview-text-candidates", action="store_true", help="Disable source-view TF-IDF candidate generation and use only canonical comparison text")
    parser.add_argument("--disable-cross-view-text-candidates", action="store_true", help="Disable OCR/native cross-view TF-IDF candidate generation")
    parser.add_argument("--disable-multiview-key-token-candidates", action="store_true", help="Disable source-safe key-token overlap candidate generation")
    parser.add_argument("--disable-rare-token-candidates", action="store_true", help="Disable bounded source-safe rare-token candidate generation")
    parser.add_argument("--rare-token-min-overlap", type=int, default=None, help="Minimum shared rare/source tokens for rare-token candidates")
    parser.add_argument("--rare-token-min-jaccard", type=float, default=None, help="Minimum rare/source token Jaccard similarity for rare-token candidates")
    parser.add_argument("--rare-token-max-df", type=int, default=None, help="Maximum page document-frequency for a token to count as rare")
    parser.add_argument("--disable-bounded-visual-ocr-weak", action="store_true", help="Disable bounded visual candidate expansion for OCR-weak pages")
    parser.add_argument("--disable-sequence-candidates", action="store_true", help="Disable bounded sequence-neighbor candidate promotion")
    parser.add_argument("--sequence-anchor-min-confidence", type=float, default=None, help="Minimum confidence for an anchor match to promote adjacent sequence candidates")
    parser.add_argument("--sequence-neighbor-window", type=int, default=None, help="Adjacent page window for sequence-neighbor promotion")
    parser.add_argument("--sequence-min-text-similarity", type=float, default=None, help="Minimum source-view text similarity for sequence-neighbor candidates without visual support")
    parser.add_argument("--sequence-min-text-similarity-with-visual", type=float, default=None, help="Minimum source-view text similarity for sequence-neighbor candidates with visual support")
    parser.add_argument("--sequence-visual-support-phash-threshold", type=int, default=None, help="Maximum pHash distance considered visual support for sequence-neighbor candidates")
    parser.add_argument("--disable-low-info-filter", action="store_true", help="Disable low-information page classification")
    parser.add_argument("--disable-low-info-suppression", action="store_true", help="Keep low-information candidate pairs in outputs")
    parser.add_argument("--include-low-info-exacts", action="store_true", help="Keep exact duplicate matches even when a page is low-information")
    parser.add_argument("--max-candidates-per-job", type=int, default=None)
    parser.add_argument("--max-candidates-per-page", type=int, default=None)
    parser.add_argument("--main-review-min-confidence", type=float, default=None, help="Minimum confidence for default main-review-list visibility")
    parser.add_argument("--main-review-max-candidates-per-100-pages", type=int, default=None, help="Default main review list budget; overflow remains in calibration_only visibility")
    parser.add_argument("--tesseract-min-confidence", type=float, default=None)
    parser.add_argument("--tesseract-min-words", type=int, default=None)
    parser.add_argument("--tesseract-profiles", default=None, help="Comma-separated Tesseract preprocessing profiles, e.g. standard or standard,grayscale,high_contrast")
    parser.add_argument("--native-min-usable-words", type=int, default=None)
    parser.add_argument("--openai-ocr-max-pages", type=int, default=None)
    parser.add_argument("--openai-ocr-max-pages-per-document", type=int, default=None, help="Maximum OpenAI OCR fallback pages per document; protects the run budget from one bad bundle")
    parser.add_argument("--openai-ocr-min-candidate-confidence", type=float, default=None)
    parser.add_argument(
        "--openai-ocr-selection-mode",
        choices=["candidate_based", "weak_pages", "vision_expected", "weak_pages_or_vision_expected", "reason_balanced"],
        default=None,
        help="OpenAI OCR fallback page selection policy. v0.9.8 defaults to reason_balanced.",
    )
    parser.add_argument("--openai-ocr-exclude-low-info", action="store_true", help="Do not select low-information/no-text pages for OpenAI OCR fallback")
    parser.add_argument("--openai-ocr-reason-quotas", default=None, help="Reason-balanced OpenAI OCR quota weights/counts, e.g. vision_expected:30,weak_tesseract:30,no_text:20,candidate_based:20")
    parser.add_argument("--openai-ocr-post-candidate-rescue", action="store_true", help="Run a second targeted OpenAI OCR rescue pass after deterministic/vector candidates exist")
    parser.add_argument("--openai-ocr-post-candidate-rescue-pages", type=int, default=None, help="Maximum pages for the post-candidate OpenAI OCR rescue reserve")
    parser.add_argument("--openai-ocr-post-candidate-min-confidence", type=float, default=None, help="Minimum candidate confidence used to nominate post-candidate OCR rescue pages")
    parser.add_argument("--openai-ocr-evidence-upgrade", action="store_true", help="Enable experimental OCR evidence upgrade: key-token acceptance and combined OCR evidence")
    parser.add_argument("--openai-ocr-combine-evidence", action="store_true", help="Combine native/Tesseract/OpenAI text when OpenAI OCR is accepted")
    parser.add_argument("--openai-ocr-key-token-acceptance", action="store_true", help="Accept short OpenAI OCR when it contains enough useful key tokens")
    parser.add_argument("--queue-profile", choices=["strict_main", "balanced", "recall_first"], default=None, help="Queue routing profile for main/secondary/calibration review visibility")
    parser.add_argument("--embedding-top-k", type=int, default=None, help="Embedding recall top-k neighbors per page")
    parser.add_argument("--embedding-similarity-threshold", type=float, default=None, help="Minimum cosine similarity for embedding-created candidates")
    parser.add_argument("--embedding-min-margin", type=float, default=None, help="Minimum margin between the top vector neighbor and the next neighbor")
    parser.add_argument("--embedding-require-cross-source", action="store_true", help="Only create embedding recall candidates across distinct source groups")
    parser.add_argument("--embedding-require-reciprocal", action="store_true", help="Only create embedding recall candidates when the nearest-neighbor relation is reciprocal within top-k")
    parser.add_argument("--embedding-max-candidates-per-page", type=int, default=None, help="Maximum embedding-created candidates per page")
    parser.add_argument("--embedding-max-candidates-per-job", type=int, default=None, help="Maximum embedding-created/vector-supported candidate pairs per job")
    parser.add_argument("--embedding-max-pages", type=int, default=None, help="Maximum pages eligible for embedding recall in a run")
    parser.add_argument("--embedding-min-text-chars", type=int, default=None, help="Minimum best-text characters for embedding recall eligibility")
    parser.add_argument("--embedding-dry-run", action="store_true", help="Enable embeddings status but prevent provider calls")
    parser.add_argument("--embedding-hybrid-scoring", action="store_true", help="Use the experimental v0.9.9 hybrid vector scoring gate for embedding-created candidates")
    parser.add_argument("--embedding-hybrid-min-score", type=float, default=None, help="Minimum hybrid vector score for the experimental hybrid gate")
    parser.add_argument("--embedding-reranker", action="store_true", help="Enable v0.10.9 pure-embedding precision reranker (off by default)")
    parser.add_argument("--embedding-reranker-min-confidence", type=float, default=None, help="Minimum precision score to keep an embedding candidate (default 0.80)")
    parser.add_argument("--embedding-reranker-ocr-penalty", type=float, default=None, help="Confidence penalty per OpenAI-OCR-selected page (default 0.01)")
    parser.add_argument("--embedding-reranker-same-doc-bonus", type=float, default=None, help="Confidence bonus when both pages share the same document (default 0.03)")
    parser.add_argument("--embedding-reranker-tesseract-bonus", type=float, default=None, help="Confidence bonus per Tesseract-usable page (default 0.02)")
    parser.add_argument("--embedding-reranker-action", choices=["demote", "drop"], default=None, help="Action for low-precision embedding candidates: demote (default) or drop")
    add_optional_ai_args(parser)


def add_doctor_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("doctor", help="Show deterministic and optional AI capability status")
    parser.add_argument("--json", action="store_true", help="Print machine-readable capability status")
    add_optional_ai_args(parser)


def add_compare_ab_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("compare-ab", help="Compare Group A PDFs against Group B PDFs")
    parser.add_argument("group_a", help="Folder containing Group A PDFs")
    parser.add_argument("group_b", help="Folder containing Group B PDFs")
    add_common_engine_args(parser)


def add_compare_all_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("compare-all", help="Compare all PDF pages in a single corpus folder")
    parser.add_argument("pdf_dir", help="Folder containing PDFs")
    add_common_engine_args(parser)


def add_eval_ab_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("eval-ab", help="Run A/B comparison and evaluate when pair-level truth is available")
    parser.add_argument("group_a", help="Folder containing Group A PDFs")
    parser.add_argument("group_b", help="Folder containing Group B PDFs")
    parser.add_argument("--truth", default=None, help="Optional strict path to pair-level truth JSON. If omitted, the engine auto-detects valid nearby truth and otherwise skips eval.")
    parser.add_argument("--no-truth-autodetect", action="store_true", help="Do not auto-detect truth when --truth is omitted; useful for production-like benchmark rounds.")
    parser.add_argument("--eval-out", default="output/eval.json", help="Evaluation JSON output path")
    parser.add_argument("--phase-eval-out", default=None, help="Optional phase-aware OCR/vector/review evaluation JSON output path")
    parser.add_argument("--eval-threshold", type=float, default=0.0)
    add_calibration_args(parser)
    add_common_engine_args(parser)


def add_eval_all_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("eval-all", help="Run all-pairs comparison and evaluate when pair-level truth is available")
    parser.add_argument("pdf_dir", help="Folder containing PDFs")
    parser.add_argument("--truth", default=None, help="Optional strict path to pair-level truth JSON. If omitted, the engine auto-detects valid nearby truth and otherwise skips eval.")
    parser.add_argument("--no-truth-autodetect", action="store_true", help="Do not auto-detect truth when --truth is omitted; useful for production-like benchmark rounds.")
    parser.add_argument("--eval-out", default="output/eval.json", help="Evaluation JSON output path")
    parser.add_argument("--phase-eval-out", default=None, help="Optional phase-aware OCR/vector/review evaluation JSON output path")
    parser.add_argument("--eval-threshold", type=float, default=0.0)
    add_calibration_args(parser)
    add_common_engine_args(parser)


def add_tui_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("tui", help="Open the dependency-free benchmark dashboard/menu")
    parser.add_argument("--summarize", default=None, help="Print a dashboard for an existing benchmark output folder")
    parser.add_argument("--pdf-dir", default=None, help="PDF corpus folder for benchmark runs")
    parser.add_argument("--truth", default=None, help="Ground truth JSON path for benchmark runs")
    parser.add_argument("--no-truth-autodetect", action="store_true", help="Do not auto-detect truth when --truth is omitted; useful for production-like benchmark rounds")
    parser.add_argument("--output-dir", default=None, help="Benchmark output folder")
    parser.add_argument("--dpi", type=int, default=150, help="Render DPI for the benchmark command")
    parser.add_argument("--tesseract-profiles", default=None, help="Comma-separated Tesseract preprocessing profiles for OCR benchmark runs")
    parser.add_argument(
        "--profile",
        choices=["baseline", "ocr", "ocr-openai-dry-run", "ocr-live", "embeddings-dry-run", "governance"],
        default="ocr",
        help="Benchmark profile/preset",
    )
    parser.add_argument("--eval-threshold", type=float, default=0.0)
    parser.add_argument("--rounds", choices=["single", "truth-and-no-truth"], default="single", help="Run one benchmark or paired with-truth/no-truth benchmark rounds")
    parser.add_argument("--include-text-preview", action="store_true", help="Include text previews in outputs. Avoid for real PHI unless approved.")
    parser.add_argument("--print-command", action="store_true", help="Print the benchmark command instead of opening the interactive menu")
    parser.add_argument("--run", action="store_true", help="Run the benchmark command immediately and then summarize outputs")


def add_review_ui_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("review-ui", help="Open the local Medical Records Sorter Assist review UI")
    parser.add_argument("--run-dir", default=None, help="Debug/dev only: open an existing run artifact folder immediately on startup. Omit in production — the UI starts clean and loads a run automatically after a job completes.")
    parser.add_argument("--workspace", default="output/review_ui_jobs", help="Local workspace where browser-uploaded jobs are stored")
    parser.add_argument("--host", default="127.0.0.1", help="Host/interface for the local review UI server")
    parser.add_argument("--port", type=int, default=8765, help="Port for the local review UI server")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open a browser window")


def add_worker_parser(subparsers: argparse._SubParsersAction) -> None:
    subparsers.add_parser(
        "worker",
        help="Run the long-polling SQS worker (AWS pilot mode). Polls DUPE_SQS_QUEUE_URL, processes one job at a time.",
    )


def add_calibrate_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("calibrate", help="Run staged OCR/vector/queue calibration sweeps against a truth set")
    parser.add_argument("pdf_dir", help="Folder containing calibration PDFs")
    parser.add_argument("--truth", required=True, help="Pair-level truth JSON for calibration")
    parser.add_argument("--out-dir", default="output/calibration/medium_v098", help="Calibration output folder")
    parser.add_argument("--profile", choices=["low_cost", "balanced", "recall_first", "accuracy_first", "focused_rescue", "v4_calibration", "generalization"], default="balanced", help="Calibration matrix profile")
    parser.add_argument("--stages", default="control,ocr,vector,queue", help="Comma-separated stages to run: control,ocr,vector,queue")
    parser.add_argument("--corpus-id", default=None, help="Label for the primary calibration corpus in cross-corpus scorecards")
    parser.add_argument("--secondary-pdf-dir", default=None, help="Optional second corpus PDF directory for generalization calibration")
    parser.add_argument("--secondary-truth", default=None, help="Truth JSON for --secondary-pdf-dir")
    parser.add_argument("--secondary-corpus-id", default=None, help="Label for the second corpus in cross-corpus scorecards")
    parser.add_argument("--max-runs", type=int, default=None, help="Optional cap on sub-runs for smoke testing")
    parser.add_argument("--resume", action="store_true", help="Reuse completed run folders and continue the calibration matrix")
    parser.add_argument("--skip-existing", action="store_true", help="Skip completed run folders when scorecard artifacts are present")
    parser.add_argument("--dry-run", action="store_true", help="Write the calibration manifest/plan but do not execute engine sub-runs")
    parser.add_argument("--confirm-live-ai", action="store_true", help="Required before calibration can execute live OpenAI OCR or embedding calls")
    parser.add_argument("--dpi", type=int, default=150, help="Render DPI for each sub-run")
    parser.add_argument("--tesseract-profiles", default="standard,grayscale,high_contrast", help="Tesseract preprocessing profiles for each sub-run")
    parser.add_argument("--progress", choices=["tui", "plain", "none"], default="tui", help="Calibration progress display mode; calibrate-loop uses a single aggregate TUI when --max-parallel-runs is greater than 1")
    parser.add_argument("--retry-failed", action="store_true", help="When resuming, rerun failed/aborted sub-runs instead of carrying their failed scorecard rows forward")
    parser.add_argument("--only-run", default=None, help="Run exactly one planned calibration run_id")
    parser.add_argument("--fail-fast", action="store_true", help="Stop the calibration matrix at the first failed sub-run")
    parser.add_argument("--llm-analysis", action="store_true", help="After calibration finishes, write a metrics-only LLM calibration analysis report")
    parser.add_argument("--llm-analysis-dry-run", action="store_true", help="Write the analysis payload/heuristic report without calling an LLM provider")
    parser.add_argument("--llm-analysis-model", default=None, help="Model for --llm-analysis; defaults to DUPE_LLM_ANALYSIS_MODEL/DUPE_LLM_MODEL/gpt-4o-mini")
    parser.add_argument("--llm-analysis-out", default=None, help="Optional Markdown output path for --llm-analysis")
    parser.add_argument("--llm-analysis-json-out", default=None, help="Optional JSON output path for --llm-analysis")
    parser.add_argument("--llm-analysis-include-text-snippets", action="store_true", help="Include limited false-negative metadata snippets in LLM analysis input. Default is metrics-only and safer for PHI.")



def add_calibrate_loop_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("calibrate-loop", help="Run iterative calibration batches until a target recall threshold is met")
    add_calibrate_loop_args(parser, default_out_dir="output/calibration/loop_v0105")


def add_calibrate_loop_stress_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("calibrate-loop-stress", help="Try looped calibration at high parallelism, then fall back to safer worker counts if a trial fails")
    add_calibrate_loop_args(parser, default_out_dir="output/calibration/loop_v0105_stress")
    parser.add_argument("--parallel-candidates", default="10,6", help="Comma-separated worker counts to try in order; default tries 10 then 6")
    parser.add_argument("--stress-continue-after-success", action="store_true", help="Continue testing lower worker counts even after the first no-failed-runs trial succeeds")



def add_continuous_calibration_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("continuous-calibration", help="Server-oriented continuous calibration runner with p6 defaults, guardrails, decision logs, and pruning")
    add_calibrate_loop_args(parser, default_out_dir="/data/runs/loop_v0107_server")
    parser.set_defaults(
        max_parallel_runs=6,
        batch_size=3,
        max_iterations=999,
        prune_artifacts="analysis-only",
        max_plateau_iterations=3,
        min_recall_gain=0.01,
        progress="tui",
    )


def add_prune_calibration_run_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("prune-calibration-run", help="Prune bulky calibration artifacts while keeping analysis JSON/CSV/Markdown evidence")
    parser.add_argument("run_dir", help="Calibration run directory to prune")
    parser.add_argument("--mode", choices=["analysis-only", "compact-debug"], default="analysis-only", help="Artifact retention policy")
    parser.add_argument("--apply", action="store_true", help="Actually delete files. Without this flag, the command is a dry run.")
    parser.add_argument("--no-summary-required", action="store_true", help="Allow pruning even if no summary/scorecard marker exists")

def add_calibrate_loop_args(parser: argparse.ArgumentParser, *, default_out_dir: str) -> None:
    parser.add_argument("pdf_dir", help="Folder containing calibration PDFs")
    parser.add_argument("--truth", required=True, help="Pair-level truth JSON for calibration")
    parser.add_argument("--out-dir", default=default_out_dir, help="Looped calibration output folder")
    parser.add_argument("--corpus-id", default=None, help="Label for the primary calibration corpus")
    parser.add_argument("--secondary-pdf-dir", default=None, help="Optional second corpus PDF directory for cross-corpus acceptance")
    parser.add_argument("--secondary-truth", default=None, help="Truth JSON for --secondary-pdf-dir")
    parser.add_argument("--secondary-corpus-id", default=None, help="Label for the second corpus")
    parser.add_argument("--bootstrap-calibration-dir", default=None, help="Optional existing calibration folder whose scorecard seeds the first generated batch")
    parser.add_argument("--target-recall", type=float, default=0.80, help="Stop when the target metric reaches this recall, using worst-case variant recall across corpora")
    parser.add_argument("--target-metric", choices=["strict_recall", "any_queue_recall", "main_or_secondary_recall", "ocr_dependent_recall"], default="strict_recall", help="Metric used for loop acceptance")
    parser.add_argument("--accept-max-known-negative-hits", type=int, default=None, help="Optional acceptance guardrail for total known negative hits across a variant")
    parser.add_argument("--accept-max-unknown-predictions", type=int, default=None, help="Optional acceptance guardrail for total unknown predictions across a variant")
    parser.add_argument("--accept-max-candidates-per-100-pages", type=float, default=None, help="Optional acceptance guardrail for candidate explosion")
    parser.add_argument("--max-iterations", type=int, default=4, help="Maximum loop iterations")
    parser.add_argument("--batch-size", type=int, default=4, help="Maximum config variants per iteration before corpus expansion")
    parser.add_argument("--aggressive-search", action="store_true", help="Bias the loop toward wider recall/candidate/OCR/vector variants. This is noisier but useful when chasing recall quickly.")
    parser.add_argument("--max-parallel-runs", type=int, default=1, help="Maximum concurrent engine sub-runs for calibrate-loop; hard-capped at --parallel-hard-cap, default 10")
    parser.add_argument("--parallel-hard-cap", type=int, default=10, help="Safety ceiling for --max-parallel-runs. Raise only when the host can tolerate more workers.")
    parser.add_argument("--resume", action="store_true", help="Reuse completed run folders and continue the loop")
    parser.add_argument("--skip-existing", action="store_true", help="Skip completed run folders when scorecard artifacts are present")
    parser.add_argument("--retry-failed", action="store_true", help="When resuming, rerun failed/aborted sub-runs instead of carrying failed rows forward")
    parser.add_argument("--dry-run", action="store_true", help="Write the loop state and first batch manifest but do not execute engine sub-runs")
    parser.add_argument("--confirm-live-ai", action="store_true", help="Required before the loop can execute live OpenAI OCR or embedding calls")
    parser.add_argument("--dpi", type=int, default=150, help="Render DPI for each sub-run unless a variant overrides it")
    parser.add_argument("--tesseract-profiles", default="standard,grayscale,high_contrast", help="Tesseract preprocessing profiles for each sub-run")
    parser.add_argument("--progress", choices=["tui", "plain", "none"], default="tui", help="Calibration progress display mode; calibrate-loop uses a single aggregate TUI when --max-parallel-runs is greater than 1")
    parser.add_argument("--fail-fast", action="store_true", help="Stop the loop at the first failed sub-run")
    parser.add_argument("--no-llm-analysis", action="store_true", help="Disable per-iteration LLM/heuristic analysis reports")
    parser.add_argument("--llm-analysis-dry-run", action="store_true", help="Write the analysis payload/heuristic report without calling an LLM provider")
    parser.add_argument("--llm-analysis-model", default=None, help="Model for per-iteration analysis; defaults to DUPE_LLM_ANALYSIS_MODEL/DUPE_LLM_MODEL/gpt-4o-mini")
    parser.add_argument("--llm-analysis-out", default=None, help="Optional Markdown output path for per-iteration analysis")
    parser.add_argument("--llm-analysis-json-out", default=None, help="Optional JSON output path for per-iteration analysis")
    parser.add_argument("--llm-analysis-include-text-snippets", action="store_true", help="Include limited false-negative metadata snippets in analysis input. Default is metrics-only and safer for PHI.")
    parser.add_argument("--fatal-llm-analysis", action="store_true", help="Fail the calibration loop if the optional per-iteration LLM analysis step fails. Default is nonfatal so long recall runs are not lost.")
    parser.add_argument("--prune-artifacts", choices=["off", "analysis-only", "compact-debug"], default="off", help="Prune completed iteration artifacts after summaries are written. analysis-only keeps JSON/JSONL/CSV/MD/TXT files.")
    parser.add_argument("--prune-dry-run", action="store_true", help="Plan pruning without deleting files")
    parser.add_argument("--max-total-runtime-hours", type=float, default=None, help="Stop after this many wall-clock hours")
    parser.add_argument("--max-iteration-runtime-hours", type=float, default=None, help="Stop after an iteration exceeds this many hours")
    parser.add_argument("--max-run-dir-gb", type=float, default=None, help="Pause/stop if the calibration output directory exceeds this size in GiB")
    parser.add_argument("--min-free-disk-gb", type=float, default=None, help="Pause/stop if free disk under the output directory falls below this GiB threshold")
    parser.add_argument("--max-openai-ocr-pages", type=int, default=None, help="Stop when total OpenAI OCR attempted pages exceed this count")
    parser.add_argument("--max-embedding-calls", type=int, default=None, help="Stop when total embedding calls exceed this count")
    parser.add_argument("--max-llm-analysis-calls", type=int, default=None, help="Stop when total LLM analysis calls exceed this count")
    parser.add_argument("--max-unknown-predictions-total", type=int, default=None, help="Stop if total unknown predictions across successful rows exceeds this count")
    parser.add_argument("--max-known-negative-hits-total", type=int, default=None, help="Stop if total known-negative hits across successful rows exceeds this count")
    parser.add_argument("--max-best-unknown-predictions", type=int, default=None, help="Stop if the current best generalized candidate has more unknown predictions than this")
    parser.add_argument("--max-best-known-negative-hits", type=int, default=None, help="Stop if the current best generalized candidate has more known-negative hits than this")
    parser.add_argument("--max-plateau-iterations", type=int, default=None, help="Stop after this many iterations without at least --min-recall-gain improvement")
    parser.add_argument("--min-recall-gain", type=float, default=0.01, help="Minimum best worst-recall gain required to reset plateau detection")


def add_analyze_calibration_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("analyze-calibration", help="Write a metrics-only LLM analysis report for an existing calibration output folder")
    parser.add_argument("calibration_dir", help="Calibration output directory containing scorecard/recommendation artifacts")
    parser.add_argument("--out", default=None, help="Markdown report output path; defaults to <calibration_dir>/llm_analysis.md")
    parser.add_argument("--json-out", default=None, help="JSON analysis output path; defaults to <calibration_dir>/llm_analysis.json")
    parser.add_argument("--model", default=None, help="Analysis LLM model; defaults to DUPE_LLM_ANALYSIS_MODEL/DUPE_LLM_MODEL/gpt-4o-mini")
    parser.add_argument("--dry-run", action="store_true", help="Write heuristic analysis only; do not call an LLM provider")
    parser.add_argument("--include-text-snippets", action="store_true", help="Include limited false-negative metadata snippets in analysis input. Default is metrics-only.")

def add_heal_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "heal",
        help="Diagnose a completed run, prescribe targeted config fixes, and optionally re-run to verify improvement",
    )
    parser.add_argument("--run-dir", required=True, help="Completed run directory to diagnose (must contain results.json)")
    parser.add_argument("--truth", default=None, help="Optional pair-level truth JSON for recall/FN analysis")
    parser.add_argument(
        "--feedback",
        default=None,
        help=(
            "Optional reviewer feedback JSON with missed/false-alarm verdicts. "
            'Format: {"version":"1","feedback_pairs":[{"doc_a":"...","page_a":1,'
            '"doc_b":"...","page_b":2,"verdict":"missed_duplicate","notes":"..."}]}'
        ),
    )
    parser.add_argument("--pdf-dir", default=None, help="PDF corpus directory — required when using --apply")
    parser.add_argument("--apply", action="store_true", help="Re-run the job with the prescribed config changes")
    parser.add_argument("--iterations", type=int, default=1, help="Maximum heal cycles when using --apply (default: 1)")
    parser.add_argument("--target-recall", type=float, default=None, help="Recall target for HEALED certification (e.g. 0.85)")
    parser.add_argument("--target-queue-size", type=float, default=None, help="Max queue candidates per 100 pages for HEALED certification (e.g. 50)")
    parser.add_argument("--out-dir", default=None, help="Output directory for prescription.json and heal artifacts (default: <run-dir>/heal_output)")
    parser.add_argument("--verbose", action="store_true", help="Print the full re-run command when using --apply")


def command_heal(args: argparse.Namespace) -> None:
    from .healing_harness import run_heal
    run_heal(args)


def command_calibrate(args: argparse.Namespace, config: EngineConfig) -> None:
    from .calibration_harness import CalibrationError, run_calibration

    try:
        result = run_calibration(args)
    except CalibrationError as exc:
        raise SystemExit(f"Calibration error: {exc}") from None
    print("Calibration complete" if result.get("executed") else "Calibration plan written")
    print(f"- out_dir: {result.get('out_dir')}")
    print(f"- planned runs: {result.get('planned_run_count')}")
    print(f"- executed runs: {result.get('executed_run_count')}")
    if result.get("scorecard_csv"):
        print(f"- scorecard: {result.get('scorecard_csv')}")
    if result.get("recommended_configs"):
        print(f"- recommendations: {result.get('recommended_configs')}")
    analysis = result.get("llm_analysis") or {}
    if analysis:
        print(f"- llm analysis: {analysis.get('analysis_md')} ({analysis.get('status')})")


def command_calibrate_loop(args: argparse.Namespace, config: EngineConfig) -> None:
    from .calibration_loop import CalibrationLoopError, run_calibration_loop

    try:
        result = run_calibration_loop(args)
    except CalibrationLoopError as exc:
        raise SystemExit(f"Calibration loop error: {exc}") from None
    print("Calibration loop complete" if result.get("executed") else "Calibration loop plan written")
    print(f"- out_dir: {result.get('out_dir')}")
    print(f"- planned runs: {result.get('planned_run_count')}")
    print(f"- executed runs: {result.get('executed_run_count')}")
    print(f"- iterations: {result.get('iteration_count')}")
    print(f"- stop reason: {result.get('stop_reason')}")
    print(f"- loop state: {result.get('loop_state')}")
    print(f"- run summary: {result.get('run_summary_md')}")
    print(f"- decision log: {result.get('decision_log')}")
    accepted = result.get("accepted") or {}
    print(f"- accepted: {accepted.get('accepted')} target={accepted.get('target_metric')} >= {accepted.get('target_recall')}")



def command_calibrate_loop_stress(args: argparse.Namespace, config: EngineConfig) -> None:
    from .calibration_loop import CalibrationLoopError, run_calibration_loop_stress

    try:
        result = run_calibration_loop_stress(args)
    except CalibrationLoopError as exc:
        raise SystemExit(f"Calibration loop stress error: {exc}") from None
    print("Calibration loop stress complete")
    print(f"- out_dir: {result.get('out_dir')}")
    print(f"- selected parallel: {result.get('selected_parallel_runs')}")
    print(f"- summary: {result.get('summary_json')}")
    for trial in result.get("trials", []):
        print(
            f"- p{trial.get('max_parallel_runs')}: "
            f"status={trial.get('status')} failed_runs={trial.get('failed_run_count')} "
            f"rows={trial.get('scorecard_row_count')} "
            f"out_dir={trial.get('out_dir')}"
        )
        if trial.get("error_message"):
            print(f"  error: {trial.get('error_message')}")


def command_continuous_calibration(args: argparse.Namespace, config: EngineConfig) -> None:
    from .calibration_loop import CalibrationLoopError, run_calibration_loop

    try:
        result = run_calibration_loop(args)
    except CalibrationLoopError as exc:
        raise SystemExit(f"Continuous calibration error: {exc}") from None
    print("Continuous calibration complete" if result.get("executed") else "Continuous calibration plan written")
    print(f"- out_dir: {result.get('out_dir')}")
    print(f"- planned runs: {result.get('planned_run_count')}")
    print(f"- executed runs: {result.get('executed_run_count')}")
    print(f"- iterations: {result.get('iteration_count')}")
    print(f"- stop reason: {result.get('stop_reason')}")
    print(f"- run summary: {result.get('run_summary_md')}")
    print(f"- decision log: {result.get('decision_log')}")
    accepted = result.get("accepted") or {}
    print(f"- accepted: {accepted.get('accepted')} target={accepted.get('target_metric')} >= {accepted.get('target_recall')}")


def command_prune_calibration_run(args: argparse.Namespace, config: EngineConfig) -> None:
    from .calibration_observability import prune_calibration_artifacts

    result = prune_calibration_artifacts(
        Path(args.run_dir),
        mode=args.mode,
        dry_run=not bool(args.apply),
        require_summary=not bool(args.no_summary_required),
    )
    print("Calibration prune complete" if args.apply else "Calibration prune dry run complete")
    print(f"- run_dir: {result.get('run_dir')}")
    print(f"- mode: {result.get('mode')}")
    print(f"- status: {result.get('status')}")
    print(f"- delete files: {result.get('deleted_file_count')}")
    print(f"- bytes deleted: {result.get('bytes_deleted')}")


def command_analyze_calibration(args: argparse.Namespace, config: EngineConfig) -> None:
    from .calibration_analysis import LlmAnalysisOptions, run_calibration_llm_analysis

    result = run_calibration_llm_analysis(
        Path(args.calibration_dir),
        LlmAnalysisOptions(
            enabled=True,
            dry_run=bool(getattr(args, "dry_run", False)),
            include_text_snippets=bool(getattr(args, "include_text_snippets", False)),
            model=getattr(args, "model", None),
            output_md=getattr(args, "out", None),
            output_json=getattr(args, "json_out", None),
        ),
    )
    print("Calibration analysis written")
    print(f"- markdown: {result.get('analysis_md')}")
    print(f"- json: {result.get('analysis_json')}")
    print(f"- status: {result.get('status')}")

def command_review_ui(args: argparse.Namespace, config: EngineConfig) -> None:
    from .review_ui_server import ReviewUiError, serve_review_ui
    from .security import assert_baa_endpoint

    assert_baa_endpoint(config)
    try:
        serve_review_ui(args)
    except ReviewUiError as exc:
        raise SystemExit(f"Review UI error: {exc}") from None


def command_worker(args: argparse.Namespace, config: EngineConfig) -> None:
    from .security import assert_baa_endpoint
    from .worker import run_worker_loop

    assert_baa_endpoint(config)
    run_worker_loop()


def command_tui(args: argparse.Namespace, config: EngineConfig) -> None:
    from .tui import run_tui

    run_tui(args)


def add_calibration_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--calibration-out", default=None, help="Optional v0.8 calibration diagnostics JSON output path")
    parser.add_argument("--candidate-summary-csv", default=None, help="Optional v0.8 candidate summary CSV output path")
    parser.add_argument("--false-positive-csv", default=None, help="Optional v0.8 false-positive/unlabeled prediction review CSV output path")
    parser.add_argument("--false-negative-csv", default=None, help="Optional v0.8 false-negative review CSV output path")
    parser.add_argument("--threshold-sweep-csv", default=None, help="Optional v0.8 threshold sweep CSV output path")
    parser.add_argument("--calibration-thresholds", default=None, help="Comma-separated confidence thresholds for calibration sweep")


def build_config(args: argparse.Namespace) -> EngineConfig:
    base = EngineConfig.from_env()
    enable_llm_detector = base.enable_llm_candidate_detector or bool(getattr(args, "llm_detector", False)) or bool(getattr(args, "llm", False))
    enable_adjudicator = base.enable_adjudicator or bool(getattr(args, "adjudicator", False)) or bool(getattr(args, "llm", False))
    return replace(
        base,
        dpi=getattr(args, "dpi", None) or base.dpi,
        enable_ocr=base.enable_ocr or bool(getattr(args, "ocr", False)) or bool(getattr(args, "openai_ocr", False)),
        enable_openai_ocr=base.enable_openai_ocr or bool(getattr(args, "openai_ocr", False)),
        openai_ocr_dry_run=False if bool(getattr(args, "openai_ocr_live", False)) else (base.openai_ocr_dry_run or bool(getattr(args, "openai_ocr_dry_run", False))),
        tesseract_min_confidence=getattr(args, "tesseract_min_confidence", None) if getattr(args, "tesseract_min_confidence", None) is not None else base.tesseract_min_confidence,
        tesseract_min_words=getattr(args, "tesseract_min_words", None) if getattr(args, "tesseract_min_words", None) is not None else base.tesseract_min_words,
        tesseract_preprocessing_profiles=getattr(args, "tesseract_profiles", None) or base.tesseract_preprocessing_profiles,
        native_min_usable_words=getattr(args, "native_min_usable_words", None) if getattr(args, "native_min_usable_words", None) is not None else base.native_min_usable_words,
        openai_ocr_max_pages_per_job=getattr(args, "openai_ocr_max_pages", None) if getattr(args, "openai_ocr_max_pages", None) is not None else base.openai_ocr_max_pages_per_job,
        openai_ocr_max_pages_per_document=getattr(args, "openai_ocr_max_pages_per_document", None) if getattr(args, "openai_ocr_max_pages_per_document", None) is not None else base.openai_ocr_max_pages_per_document,
        openai_ocr_min_candidate_confidence=getattr(args, "openai_ocr_min_candidate_confidence", None) if getattr(args, "openai_ocr_min_candidate_confidence", None) is not None else base.openai_ocr_min_candidate_confidence,
        openai_ocr_selection_mode=getattr(args, "openai_ocr_selection_mode", None) or base.openai_ocr_selection_mode,
        openai_ocr_reason_quotas=getattr(args, "openai_ocr_reason_quotas", None) or base.openai_ocr_reason_quotas,
        openai_ocr_post_candidate_rescue_enabled=base.openai_ocr_post_candidate_rescue_enabled or bool(getattr(args, "openai_ocr_post_candidate_rescue", False)),
        openai_ocr_post_candidate_max_pages=getattr(args, "openai_ocr_post_candidate_rescue_pages", None) if getattr(args, "openai_ocr_post_candidate_rescue_pages", None) is not None else base.openai_ocr_post_candidate_max_pages,
        openai_ocr_post_candidate_min_confidence=getattr(args, "openai_ocr_post_candidate_min_confidence", None) if getattr(args, "openai_ocr_post_candidate_min_confidence", None) is not None else base.openai_ocr_post_candidate_min_confidence,
        openai_ocr_allow_low_information_pages=base.openai_ocr_allow_low_information_pages and not bool(getattr(args, "openai_ocr_exclude_low_info", False)),
        openai_ocr_evidence_upgrade_enabled=base.openai_ocr_evidence_upgrade_enabled or bool(getattr(args, "openai_ocr_evidence_upgrade", False)),
        openai_ocr_key_token_acceptance=base.openai_ocr_key_token_acceptance or bool(getattr(args, "openai_ocr_key_token_acceptance", False)) or bool(getattr(args, "openai_ocr_evidence_upgrade", False)),
        openai_ocr_combine_text_evidence=base.openai_ocr_combine_text_evidence or bool(getattr(args, "openai_ocr_combine_evidence", False)) or bool(getattr(args, "openai_ocr_evidence_upgrade", False)),
        enable_embeddings=base.enable_embeddings or bool(getattr(args, "embeddings", False)),
        enable_llm_candidate_detector=enable_llm_detector,
        enable_adjudicator=enable_adjudicator,
        require_ocr=base.require_ocr or bool(getattr(args, "require_ocr", False)),
        require_openai_ocr=base.require_openai_ocr or bool(getattr(args, "require_openai_ocr", False)),
        require_embeddings=base.require_embeddings or bool(getattr(args, "require_embeddings", False)),
        require_llm_candidate_detector=base.require_llm_candidate_detector or bool(getattr(args, "require_llm_detector", False)),
        require_adjudicator=base.require_adjudicator or bool(getattr(args, "require_adjudicator", False)),
        tfidf_threshold=getattr(args, "tfidf_threshold", None) if getattr(args, "tfidf_threshold", None) is not None else base.tfidf_threshold,
        tfidf_top_k=getattr(args, "tfidf_top_k", None) if getattr(args, "tfidf_top_k", None) is not None else base.tfidf_top_k,
        perceptual_hash_threshold=getattr(args, "phash_threshold", None) if getattr(args, "phash_threshold", None) is not None else base.perceptual_hash_threshold,
        enable_multipass=base.enable_multipass and not bool(getattr(args, "single_threshold", False)),
        strict_phash_threshold=getattr(args, "strict_phash_threshold", None) if getattr(args, "strict_phash_threshold", None) is not None else base.strict_phash_threshold,
        standard_phash_threshold=getattr(args, "standard_phash_threshold", None) if getattr(args, "standard_phash_threshold", None) is not None else base.standard_phash_threshold,
        loose_phash_threshold=getattr(args, "loose_phash_threshold", None) if getattr(args, "loose_phash_threshold", None) is not None else base.loose_phash_threshold,
        strict_tfidf_threshold=getattr(args, "strict_tfidf_threshold", None) if getattr(args, "strict_tfidf_threshold", None) is not None else base.strict_tfidf_threshold,
        standard_tfidf_threshold=getattr(args, "standard_tfidf_threshold", None) if getattr(args, "standard_tfidf_threshold", None) is not None else base.standard_tfidf_threshold,
        loose_tfidf_threshold=getattr(args, "loose_tfidf_threshold", None) if getattr(args, "loose_tfidf_threshold", None) is not None else base.loose_tfidf_threshold,
        multipass_text_top_k=getattr(args, "multipass_text_top_k", None) if getattr(args, "multipass_text_top_k", None) is not None else base.multipass_text_top_k,
        multipass_visual_all_pages=base.multipass_visual_all_pages or bool(getattr(args, "multipass_visual_all_pages", False)),
        source_safe_ocr_merge_enabled=base.source_safe_ocr_merge_enabled and not bool(getattr(args, "disable_source_safe_ocr_merge", False)),
        multiview_text_candidates_enabled=base.multiview_text_candidates_enabled and not bool(getattr(args, "disable_multiview_text_candidates", False)),
        multiview_cross_text_candidates_enabled=base.multiview_cross_text_candidates_enabled and not bool(getattr(args, "disable_cross_view_text_candidates", False)),
        multiview_key_token_candidates_enabled=base.multiview_key_token_candidates_enabled and not bool(getattr(args, "disable_multiview_key_token_candidates", False)),
        rare_token_candidates_enabled=base.rare_token_candidates_enabled and not bool(getattr(args, "disable_rare_token_candidates", False)),
        rare_token_min_overlap=getattr(args, "rare_token_min_overlap", None) if getattr(args, "rare_token_min_overlap", None) is not None else base.rare_token_min_overlap,
        rare_token_min_jaccard=getattr(args, "rare_token_min_jaccard", None) if getattr(args, "rare_token_min_jaccard", None) is not None else base.rare_token_min_jaccard,
        rare_token_max_df=getattr(args, "rare_token_max_df", None) if getattr(args, "rare_token_max_df", None) is not None else base.rare_token_max_df,
        bounded_visual_ocr_weak_enabled=base.bounded_visual_ocr_weak_enabled and not bool(getattr(args, "disable_bounded_visual_ocr_weak", False)),
        sequence_candidate_promotion_enabled=base.sequence_candidate_promotion_enabled and not bool(getattr(args, "disable_sequence_candidates", False)),
        sequence_anchor_min_confidence=getattr(args, "sequence_anchor_min_confidence", None) if getattr(args, "sequence_anchor_min_confidence", None) is not None else base.sequence_anchor_min_confidence,
        sequence_neighbor_window=getattr(args, "sequence_neighbor_window", None) if getattr(args, "sequence_neighbor_window", None) is not None else base.sequence_neighbor_window,
        sequence_min_text_similarity=getattr(args, "sequence_min_text_similarity", None) if getattr(args, "sequence_min_text_similarity", None) is not None else base.sequence_min_text_similarity,
        sequence_min_text_similarity_with_visual=getattr(args, "sequence_min_text_similarity_with_visual", None) if getattr(args, "sequence_min_text_similarity_with_visual", None) is not None else base.sequence_min_text_similarity_with_visual,
        sequence_visual_support_phash_threshold=getattr(args, "sequence_visual_support_phash_threshold", None) if getattr(args, "sequence_visual_support_phash_threshold", None) is not None else base.sequence_visual_support_phash_threshold,
        enable_low_information_filter=base.enable_low_information_filter and not bool(getattr(args, "disable_low_info_filter", False)),
        suppress_low_information_candidates=base.suppress_low_information_candidates and not bool(getattr(args, "disable_low_info_suppression", False)),
        include_low_information_exact_matches=base.include_low_information_exact_matches or bool(getattr(args, "include_low_info_exacts", False)),
        max_candidates_per_job=getattr(args, "max_candidates_per_job", None) if getattr(args, "max_candidates_per_job", None) is not None else base.max_candidates_per_job,
        max_candidates_per_page=getattr(args, "max_candidates_per_page", None) if getattr(args, "max_candidates_per_page", None) is not None else base.max_candidates_per_page,
        main_review_min_confidence=getattr(args, "main_review_min_confidence", None) if getattr(args, "main_review_min_confidence", None) is not None else base.main_review_min_confidence,
        main_review_max_candidates_per_100_pages=getattr(args, "main_review_max_candidates_per_100_pages", None) if getattr(args, "main_review_max_candidates_per_100_pages", None) is not None else base.main_review_max_candidates_per_100_pages,
        embeddings_candidate_top_k=getattr(args, "embedding_top_k", None) if getattr(args, "embedding_top_k", None) is not None else base.embeddings_candidate_top_k,
        embeddings_similarity_threshold=getattr(args, "embedding_similarity_threshold", None) if getattr(args, "embedding_similarity_threshold", None) is not None else base.embeddings_similarity_threshold,
        embeddings_min_margin=getattr(args, "embedding_min_margin", None) if getattr(args, "embedding_min_margin", None) is not None else base.embeddings_min_margin,
        embeddings_require_cross_source=base.embeddings_require_cross_source or bool(getattr(args, "embedding_require_cross_source", False)),
        embeddings_require_reciprocal=base.embeddings_require_reciprocal or bool(getattr(args, "embedding_require_reciprocal", False)),
        embeddings_max_candidates_per_page=getattr(args, "embedding_max_candidates_per_page", None) if getattr(args, "embedding_max_candidates_per_page", None) is not None else base.embeddings_max_candidates_per_page,
        max_embedding_pairs_per_job=getattr(args, "embedding_max_candidates_per_job", None) if getattr(args, "embedding_max_candidates_per_job", None) is not None else base.max_embedding_pairs_per_job,
        embeddings_max_pages_per_job=getattr(args, "embedding_max_pages", None) if getattr(args, "embedding_max_pages", None) is not None else base.embeddings_max_pages_per_job,
        embeddings_min_text_chars=getattr(args, "embedding_min_text_chars", None) if getattr(args, "embedding_min_text_chars", None) is not None else base.embeddings_min_text_chars,
        embeddings_dry_run=base.embeddings_dry_run or bool(getattr(args, "embedding_dry_run", False)),
        embeddings_hybrid_scoring_enabled=base.embeddings_hybrid_scoring_enabled or bool(getattr(args, "embedding_hybrid_scoring", False)),
        embeddings_hybrid_min_score=getattr(args, "embedding_hybrid_min_score", None) if getattr(args, "embedding_hybrid_min_score", None) is not None else base.embeddings_hybrid_min_score,
        embedding_reranker_enabled=base.embedding_reranker_enabled or bool(getattr(args, "embedding_reranker", False)),
        embedding_reranker_min_confidence=getattr(args, "embedding_reranker_min_confidence", None) if getattr(args, "embedding_reranker_min_confidence", None) is not None else base.embedding_reranker_min_confidence,
        embedding_reranker_ocr_penalty=getattr(args, "embedding_reranker_ocr_penalty", None) if getattr(args, "embedding_reranker_ocr_penalty", None) is not None else base.embedding_reranker_ocr_penalty,
        embedding_reranker_same_doc_bonus=getattr(args, "embedding_reranker_same_doc_bonus", None) if getattr(args, "embedding_reranker_same_doc_bonus", None) is not None else base.embedding_reranker_same_doc_bonus,
        embedding_reranker_tesseract_bonus=getattr(args, "embedding_reranker_tesseract_bonus", None) if getattr(args, "embedding_reranker_tesseract_bonus", None) is not None else base.embedding_reranker_tesseract_bonus,
        embedding_reranker_action=getattr(args, "embedding_reranker_action", None) or base.embedding_reranker_action,
        review_queue_profile=getattr(args, "queue_profile", None) or base.review_queue_profile,
        include_text_preview=base.include_text_preview or bool(getattr(args, "include_text_preview", False)),
    )


def command_doctor(args: argparse.Namespace, config: EngineConfig) -> None:
    capabilities = build_capability_report(config, used_core_layers=False)
    if args.json:
        print(json.dumps(capabilities.to_json(), indent=2))
    else:
        print_capability_report(capabilities)


def start_command_progress(args: argparse.Namespace, command_name: str) -> None:
    raw_progress_dir = getattr(args, "progress_dir", None) or getattr(args, "run_dir", None)
    if not raw_progress_dir:
        out_path = Path(getattr(args, "out", "output/results.json"))
        raw_progress_dir = str(out_path.parent / "progress")
    os.environ[PROGRESS_ENV] = str(Path(raw_progress_dir))
    initialize_progress(command=command_name, source_args={key: value for key, value in vars(args).items() if key not in {"func"}})


def finish_command_progress_success(summary: dict | None = None) -> None:
    finish_progress(status="succeeded", message="Engine run complete", details={"summary": summary or {}})


def finish_command_progress_failed(exc: BaseException) -> None:
    finish_progress(status="failed", message=str(exc), details={"error_type": type(exc).__name__})


def command_compare_ab(args: argparse.Namespace, config: EngineConfig) -> None:
    start_command_progress(args, "compare-ab")
    try:
        enforce_required_capabilities(config)
    except Exception as exc:
        finish_command_progress_failed(exc)
        raise
    pages_a, pages_b, matches = run_ab_compare(Path(args.group_a), Path(args.group_b), Path(args.work_dir), config)
    emit_progress(stage="building_reports", message="Building run reports and capability summary")
    capabilities = build_run_capabilities(config, pages_a + pages_b, matches)
    report = build_report(pages_a, pages_b, matches, config, mode="ab", capabilities=capabilities)
    write_outputs(args, report, matches, pages_a + pages_b, config, capabilities, html_title="A/B Duplicate Comparison Report")
    ocr_report = write_ocr_validation_outputs(args, pages_a + pages_b, matches, None, capabilities, threshold=0.0)
    fallback_audit = write_fallback_audit_outputs(args, pages_a + pages_b, config)
    print_summary(report)
    print_fallback_audit_summary(fallback_audit)
    if ocr_report:
        print_ocr_validation_summary(ocr_report)
    print_capability_short(capabilities)
    write_ui_artifacts_output(
        args,
        command_name="compare-ab",
        report=report,
        pages=pages_a + pages_b,
        matches=matches,
        config=config,
        capabilities=capabilities,
        ocr_report=ocr_report,
    )
    finish_command_progress_success(report.get("summary", {}))


def command_compare_all(args: argparse.Namespace, config: EngineConfig) -> None:
    start_command_progress(args, "compare-all")
    try:
        enforce_required_capabilities(config)
    except Exception as exc:
        finish_command_progress_failed(exc)
        raise
    pages, matches = run_all_pairs_compare(Path(args.pdf_dir), Path(args.work_dir), config)
    emit_progress(stage="building_reports", message="Building run reports and capability summary")
    capabilities = build_run_capabilities(config, pages, matches)
    report = build_all_pairs_report(pages, matches, config, capabilities=capabilities)
    write_outputs(args, report, matches, pages, config, capabilities, html_title="All-Pairs Duplicate Comparison Report")
    ocr_report = write_ocr_validation_outputs(args, pages, matches, None, capabilities, threshold=0.0)
    fallback_audit = write_fallback_audit_outputs(args, pages, config)
    print_summary(report)
    print_fallback_audit_summary(fallback_audit)
    if ocr_report:
        print_ocr_validation_summary(ocr_report)
    print_capability_short(capabilities)
    write_ui_artifacts_output(
        args,
        command_name="compare-all",
        report=report,
        pages=pages,
        matches=matches,
        config=config,
        capabilities=capabilities,
        ocr_report=ocr_report,
    )
    finish_command_progress_success(report.get("summary", {}))


def command_eval_ab(args: argparse.Namespace, config: EngineConfig) -> None:
    start_command_progress(args, "eval-ab")
    try:
        enforce_required_capabilities(config)
    except Exception as exc:
        finish_command_progress_failed(exc)
        raise
    truth_context = resolve_truth_context(
        getattr(args, "truth", None),
        search_roots=truth_search_roots_for_ab(Path(args.group_a), Path(args.group_b)),
        auto_detect=not bool(getattr(args, "no_truth_autodetect", False)),
    )
    pages_a, pages_b, matches = run_ab_compare(Path(args.group_a), Path(args.group_b), Path(args.work_dir), config)
    pages = pages_a + pages_b
    capabilities = build_run_capabilities(config, pages, matches)
    report = build_report(pages_a, pages_b, matches, config, mode="ab", capabilities=capabilities)
    attach_truth_status(report, truth_context)
    write_outputs(args, report, matches, pages, config, capabilities, html_title="A/B Duplicate Comparison Report")
    eval_report = write_evaluation_output(args, matches, pages, truth_context, report, capabilities)
    calibration_report = write_calibration_outputs(args, matches, truth_context.pairs or [], pages, truth_context)
    ocr_report = write_ocr_validation_outputs(args, pages, matches, truth_context.pairs, capabilities, threshold=args.eval_threshold, truth_context=truth_context)
    fallback_audit = write_fallback_audit_outputs(args, pages, config)
    print_summary(report)
    print_fallback_audit_summary(fallback_audit)
    print_truth_status(truth_context)
    print_eval_summary(eval_report)
    if calibration_report:
        print_calibration_summary(calibration_report)
    if ocr_report:
        print_ocr_validation_summary(ocr_report)
    print_capability_short(capabilities)
    write_ui_artifacts_output(
        args,
        command_name="eval-ab",
        report=report,
        pages=pages,
        matches=matches,
        config=config,
        capabilities=capabilities,
        truth_context=truth_context,
        eval_report=eval_report,
        calibration_report=calibration_report,
        ocr_report=ocr_report,
    )
    finish_command_progress_success(report.get("summary", {}))


def command_eval_all(args: argparse.Namespace, config: EngineConfig) -> None:
    start_command_progress(args, "eval-all")
    try:
        enforce_required_capabilities(config)
    except Exception as exc:
        finish_command_progress_failed(exc)
        raise
    pdf_dir = Path(args.pdf_dir)
    truth_context = resolve_truth_context(
        getattr(args, "truth", None),
        search_roots=truth_search_roots_for_all(pdf_dir),
        auto_detect=not bool(getattr(args, "no_truth_autodetect", False)),
    )
    pages, matches = run_all_pairs_compare(pdf_dir, Path(args.work_dir), config)
    capabilities = build_run_capabilities(config, pages, matches)
    report = build_all_pairs_report(pages, matches, config, capabilities=capabilities)
    attach_truth_status(report, truth_context)
    write_outputs(args, report, matches, pages, config, capabilities, html_title="All-Pairs Duplicate Comparison Report")
    eval_report = write_evaluation_output(args, matches, pages, truth_context, report, capabilities)
    calibration_report = write_calibration_outputs(args, matches, truth_context.pairs or [], pages, truth_context)
    ocr_report = write_ocr_validation_outputs(args, pages, matches, truth_context.pairs, capabilities, threshold=args.eval_threshold, truth_context=truth_context)
    fallback_audit = write_fallback_audit_outputs(args, pages, config)
    print_summary(report)
    print_fallback_audit_summary(fallback_audit)
    print_truth_status(truth_context)
    print_eval_summary(eval_report)
    if calibration_report:
        print_calibration_summary(calibration_report)
    if ocr_report:
        print_ocr_validation_summary(ocr_report)
    print_capability_short(capabilities)
    write_ui_artifacts_output(
        args,
        command_name="eval-all",
        report=report,
        pages=pages,
        matches=matches,
        config=config,
        capabilities=capabilities,
        truth_context=truth_context,
        eval_report=eval_report,
        calibration_report=calibration_report,
        ocr_report=ocr_report,
    )
    finish_command_progress_success(report.get("summary", {}))


def write_ui_artifacts_output(
    args: argparse.Namespace,
    *,
    command_name: str,
    report: dict,
    pages: list[PageRecord],
    matches,
    config: EngineConfig,
    capabilities: CapabilityReport,
    truth_context: TruthContext | None = None,
    eval_report: dict | None = None,
    calibration_report: dict | None = None,
    ocr_report: dict | None = None,
) -> None:
    run_dir = getattr(args, "run_dir", None)
    if not run_dir:
        return
    emit_progress(stage="writing_ui_artifacts", message="Writing UI run artifacts and page previews")
    write_ui_run_artifacts(
        Path(run_dir),
        command_name=command_name,
        report=report,
        pages=pages,
        matches=matches,
        config=config,
        capabilities=capabilities,
        truth_context=truth_context,
        eval_report=eval_report,
        calibration_report=calibration_report,
        ocr_report=ocr_report,
        source_args={key: value for key, value in vars(args).items() if key not in {"func"}},
    )
    emit_progress(stage="ui_artifacts_written", message="UI run artifacts written", details={"run_dir": run_dir})
    print(f"UI run artifacts: {run_dir}")


def truth_search_roots_for_all(pdf_dir: Path) -> list[Path]:
    return [pdf_dir, pdf_dir.parent, pdf_dir.parent / "truth", pdf_dir.parent.parent / "truth"]


def truth_search_roots_for_ab(group_a: Path, group_b: Path) -> list[Path]:
    roots = [group_a, group_b, group_a.parent, group_b.parent]
    try:
        common = Path(__import__("os").path.commonpath([str(group_a.resolve()), str(group_b.resolve())]))
        roots.extend([common, common / "truth", common.parent / "truth"])
    except ValueError:
        pass
    return roots


def attach_truth_status(report: dict, truth_context: TruthContext) -> None:
    status = truth_context.to_json()
    report["truth_status"] = status
    report.setdefault("summary", {})["truth_available"] = status["available"]
    report.setdefault("summary", {})["truth_source"] = status["source"]
    report.setdefault("summary", {})["truth_path"] = status["path"]


def write_evaluation_output(
    args: argparse.Namespace,
    matches,
    pages: list[PageRecord],
    truth_context: TruthContext,
    report: dict,
    capabilities: CapabilityReport,
) -> dict:
    truth_pairs = truth_context.pairs or []
    if truth_context.available:
        eval_report = evaluate_matches(matches, truth_pairs, threshold=args.eval_threshold)
        eval_report["evaluation_available"] = True
        eval_report["truth_status"] = truth_context.to_json()
    else:
        eval_report = build_no_truth_eval_report(matches, threshold=args.eval_threshold, truth_context=truth_context)
    phase_eval = build_phase_eval_report(pages, matches, truth_pairs, threshold=args.eval_threshold)
    eval_report["phase_eval"] = phase_eval
    eval_report["capabilities"] = capabilities.to_json()
    eval_report["ai_call_summary"] = build_ai_call_ledger(pages, matches, capabilities=capabilities.to_json())["summary"]
    eval_report["schema_notes"] = report["schema_notes"]
    if getattr(args, "eval_out", None):
        write_json(Path(args.eval_out), eval_report)
    if getattr(args, "phase_eval_out", None):
        write_json(Path(args.phase_eval_out), phase_eval)
    return eval_report


def enforce_required_capabilities(config: EngineConfig) -> None:
    capabilities = build_capability_report(config, used_core_layers=False)
    errors = capabilities.blocking_errors
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(2)


def build_run_capabilities(config: EngineConfig, pages: list[PageRecord], matches=None) -> CapabilityReport:
    capabilities = build_capability_report(config, used_core_layers=True)
    layers = dict(capabilities.layers)
    ocr = layers.get("ocr")
    if ocr:
        layers["ocr"] = replace(ocr, used=any(page.ocr_used for page in pages))
    tesseract = layers.get("tesseract_ocr")
    if tesseract:
        layers["tesseract_ocr"] = replace(tesseract, used=any(page.tesseract_attempted for page in pages))
    openai_ocr = layers.get("openai_ocr_fallback")
    if openai_ocr:
        layers["openai_ocr_fallback"] = replace(openai_ocr, used=any(page.openai_ocr_selected or page.openai_ocr_attempted for page in pages))
    signal_names = {signal.name for match in (matches or []) for signal in match.signals}
    embeddings = layers.get("embeddings")
    if embeddings:
        layers["embeddings"] = replace(embeddings, used="embedding_similarity" in signal_names)
    llm_detector = layers.get("llm_candidate_detector")
    if llm_detector:
        layers["llm_candidate_detector"] = replace(llm_detector, used="llm_candidate_signal" in signal_names)
    adjudicator = layers.get("adjudicator_agent")
    if adjudicator:
        layers["adjudicator_agent"] = replace(adjudicator, used="adjudicator_decision" in signal_names)
    return CapabilityReport(layers=layers)


def write_outputs(
    args: argparse.Namespace,
    report: dict,
    matches,
    pages,
    config: EngineConfig,
    capabilities: CapabilityReport,
    html_title: str,
) -> None:
    write_json(Path(args.out), report)
    if args.csv:
        write_matches_csv(Path(args.csv), matches)
    if args.html:
        write_html_report(Path(args.html), matches, title=html_title, capabilities=capabilities.to_json())
    if args.pages_out:
        write_json(Path(args.pages_out), build_page_records_report(pages, config, capabilities=capabilities))
    write_ai_ledger_outputs(args, pages, matches, capabilities)



def write_ai_ledger_outputs(
    args: argparse.Namespace,
    pages: list[PageRecord],
    matches,
    capabilities: CapabilityReport,
) -> dict | None:
    requested = bool(getattr(args, "ai_ledger_out", None) or getattr(args, "ai_ledger_csv", None))
    if not requested:
        return None
    ledger = build_ai_call_ledger(pages, matches, capabilities=capabilities.to_json())
    if args.ai_ledger_out:
        write_json(Path(args.ai_ledger_out), ledger)
    if args.ai_ledger_csv:
        write_ai_ledger_csv(Path(args.ai_ledger_csv), ledger["records"])
    return ledger

def write_calibration_outputs(args: argparse.Namespace, matches, truth_pairs, pages, truth_context: TruthContext | None = None) -> dict | None:
    requested = any(
        getattr(args, name, None)
        for name in [
            "calibration_out",
            "candidate_summary_csv",
            "false_positive_csv",
            "false_negative_csv",
            "threshold_sweep_csv",
        ]
    )
    if not requested:
        return None

    try:
        thresholds = parse_thresholds(getattr(args, "calibration_thresholds", None))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    calibration_report = build_calibration_report(
        matches,
        truth_pairs,
        pages=pages,
        threshold=getattr(args, "eval_threshold", 0.0),
        thresholds=thresholds,
    )
    if truth_context is not None:
        calibration_report["truth_status"] = truth_context.to_json()
        calibration_report["summary"]["truth_available"] = truth_context.available
    if args.calibration_out:
        write_json(Path(args.calibration_out), calibration_report)
    if args.candidate_summary_csv:
        write_rows_csv(Path(args.candidate_summary_csv), calibration_report["candidate_summary"])
    if args.false_positive_csv:
        write_rows_csv(Path(args.false_positive_csv), calibration_report["false_positive_review"])
    if args.false_negative_csv:
        write_rows_csv(Path(args.false_negative_csv), calibration_report["false_negative_review"])
    if args.threshold_sweep_csv:
        write_rows_csv(Path(args.threshold_sweep_csv), calibration_report["threshold_sweep"])
    return calibration_report


def write_fallback_audit_outputs(args: argparse.Namespace, pages: list[PageRecord], config: EngineConfig) -> dict | None:
    run_dir = getattr(args, "run_dir", None)
    requested = bool(getattr(args, "fallback_audit_out", None) or getattr(args, "fallback_audit_csv", None) or run_dir)
    if not requested:
        return None
    audit = build_fallback_audit(pages, config)
    default_dir = Path(run_dir) if run_dir else Path(getattr(args, "out", "output/results.json")).parent
    json_path = Path(getattr(args, "fallback_audit_out", None) or default_dir / "fallback_audit.json")
    csv_path = Path(getattr(args, "fallback_audit_csv", None) or default_dir / "fallback_pages.csv")
    write_fallback_audit_json(json_path, audit)
    write_fallback_audit_csv(csv_path, audit["rows"])
    emit_progress(stage="fallback_audit_written", message="Wrote OpenAI OCR fallback audit", details={"fallback_audit": json_path, "fallback_csv": csv_path, "summary": audit.get("summary", {})})
    return audit


def write_ocr_validation_outputs(
    args: argparse.Namespace,
    pages: list[PageRecord],
    matches,
    truth_pairs: list[TruthPair] | None,
    capabilities: CapabilityReport,
    threshold: float = 0.0,
    truth_context: TruthContext | None = None,
) -> dict | None:
    requested = any(
        getattr(args, name, None)
        for name in [
            "ocr_validation_out",
            "ocr_route_csv",
            "ocr_candidate_csv",
        ]
    )
    if not requested:
        return None

    report = build_ocr_validation_report(
        pages,
        matches,
        truth_pairs=truth_pairs,
        threshold=threshold,
        capabilities=capabilities.to_json(),
    )
    if truth_context is not None:
        report["truth_status"] = truth_context.to_json()
        report["summary"]["truth_available"] = truth_context.available
    if args.ocr_validation_out:
        write_json(Path(args.ocr_validation_out), report)
    if args.ocr_route_csv:
        write_rows_csv(Path(args.ocr_route_csv), report["ocr_route_rows"])
    if args.ocr_candidate_csv:
        write_rows_csv(Path(args.ocr_candidate_csv), report["ocr_candidate_rows"])
    return report


def print_summary(report: dict) -> None:
    summary = report["summary"]
    print(f"Mode: {report['mode']}")
    print(f"Total pages: {summary.get('total_pages')}")
    print(f"OCR pages: {summary.get('ocr_pages')}")
    print(f"Tesseract attempted/usable: {summary.get('tesseract_attempted_pages')}/{summary.get('tesseract_usable_pages')}")
    print(f"OpenAI OCR selected/attempted/usable: {summary.get('openai_ocr_selected_pages')}/{summary.get('openai_ocr_attempted_pages')}/{summary.get('openai_ocr_usable_pages')}")
    if summary.get('openai_ocr_selection_mode'):
        print(f"OpenAI OCR selection mode/budget: {summary.get('openai_ocr_selection_mode')} / {summary.get('openai_ocr_max_pages_per_job')}")
    if summary.get('openai_ocr_selection_reason_counts'):
        print(f"OpenAI OCR selection reasons: {summary.get('openai_ocr_selection_reason_counts')}")
    if summary.get('openai_ocr_skip_reason_counts'):
        print(f"OpenAI OCR skip reasons: {summary.get('openai_ocr_skip_reason_counts')}")
    print(f"Text sources: {summary.get('text_source_counts')}")
    print(f"OCR routes: {summary.get('ocr_route_counts')}")
    print(f"Matches: {summary.get('match_count')}")
    print(f"Candidates needing adjudication: {summary.get('adjudication_needed_count')}")
    if summary.get("ai_call_record_count"):
        print(f"AI route ledger records: {summary.get('ai_call_record_count')} (attempted={summary.get('ai_call_attempted_count')})")
        print(f"AI route counts: {summary.get('ai_call_route_counts')}")
    for match_type, count in summary.get("match_counts_by_type", {}).items():
        print(f"- {match_type}: {count}")


def print_truth_status(truth_context: TruthContext) -> None:
    status = truth_context.to_json()
    if status["available"]:
        print(f"Truth: {status['source']} ({status['pair_count']} pairs) {status['path']}")
    else:
        print(f"Truth: unavailable - {status['message']}")
    for warning in status.get("warnings", []):
        print(f"Truth warning: {warning}")


def print_eval_summary(eval_report: dict) -> None:
    summary = eval_report["summary"]
    print("Evaluation:")
    if not eval_report.get("evaluation_available", True):
        print(f"- skipped: {eval_report.get('note', 'no truth file available')}")
        print(f"- predicted candidates: {summary.get('predicted_match_count')}")
        return
    print(f"- true positives: {summary['true_positive_count']}")
    print(f"- false negatives: {summary['false_negative_count']}")
    print(f"- expected negative hits: {summary['expected_negative_hit_count']}")
    print(f"- partial overlap hits: {summary['partial_overlap_hit_count']}")
    if "low_information_ignore_hit_count" in summary:
        print(f"- low-information ignore hits: {summary['low_information_ignore_hit_count']}")
    print(f"- unknown predictions: {summary['unknown_prediction_count']}")
    print(f"- recall on must_match: {summary['recall_on_must_match']}")
    phase = eval_report.get("phase_eval", {})
    vector_summary = phase.get("vector_retrieval_eval", {}).get("summary", {}) if isinstance(phase, dict) else {}
    if vector_summary:
        print(f"- vector candidates: {vector_summary.get('vector_candidate_count')} (embedding-only={vector_summary.get('embedding_only_candidate_count')})")
        if vector_summary.get("recall_at_5"):
            print(f"- vector recall@5: {vector_summary.get('recall_at_5', {}).get('recall')}")
    ocr_summary = phase.get("ocr_rescue_eval", {}).get("summary", {}) if isinstance(phase, dict) else {}
    if ocr_summary and ocr_summary.get("ocr_ready_pair_rate") is not None:
        print(f"- OCR-ready duplicate pair rate: {ocr_summary.get('ocr_ready_pair_rate')}")

def print_calibration_summary(calibration_report: dict) -> None:
    summary = calibration_report["summary"]
    print("Calibration artifacts:")
    print(f"- review buckets: {summary['review_bucket_counts']}")
    print(f"- main review list: {summary.get('main_review_list_candidate_count')} candidates ({summary.get('main_review_list_pairs_per_100_pages')} per 100 pages)")
    print(f"- secondary review: {summary.get('secondary_review_candidate_count')} candidates")
    print(f"- calibration only: {summary.get('calibration_only_candidate_count')} candidates")
    print(f"- false-positive review rows: {summary['false_positive_review_count']}")
    print(f"- false-negative review rows: {summary['false_negative_review_count']}")
    print(f"- known review risk count: {summary['known_review_risk_count']}")


def print_fallback_audit_summary(fallback_audit: dict | None) -> None:
    if not fallback_audit:
        return
    summary = fallback_audit.get("summary", {})
    print("OpenAI fallback audit:")
    print(f"- eligible/selected/attempted/usable/improved: {summary.get('eligible_pages')}/{summary.get('selected_pages')}/{summary.get('attempted_pages')}/{summary.get('usable_pages')}/{summary.get('improved_pages')}")
    print(f"- eligible not selected: {summary.get('eligible_not_selected_pages')} (budget skip estimate: {summary.get('skipped_due_budget_estimate')})")


def print_ocr_validation_summary(ocr_report: dict) -> None:
    summary = ocr_report["summary"]
    print("OCR validation:")
    print(f"- weak/missing native pages: {summary.get('native_weak_or_missing_pages')}")
    print(f"- Tesseract attempted/usable/improved: {summary.get('tesseract_attempted_pages')}/{summary.get('tesseract_usable_pages')}/{summary.get('tesseract_improved_pages')}")
    print(f"- OpenAI OCR selected/attempted/usable/improved: {summary.get('openai_ocr_selected_pages')}/{summary.get('openai_ocr_attempted_pages')}/{summary.get('openai_ocr_usable_pages')}/{summary.get('openai_ocr_improved_pages')}")
    if summary.get("openai_ocr_selection_reason_counts"):
        print(f"- OpenAI OCR selection reasons: {summary.get('openai_ocr_selection_reason_counts')}")
    if summary.get("openai_ocr_skip_reason_counts"):
        print(f"- OpenAI OCR skip reasons: {summary.get('openai_ocr_skip_reason_counts')}")
    if summary.get("truth_ocr_dependent_duplicate_count") is not None:
        print(f"- OCR-dependent duplicate recall: {summary.get('truth_ocr_dependent_true_positive_count')}/{summary.get('truth_ocr_dependent_duplicate_count')} = {summary.get('truth_ocr_dependent_recall')}")


def print_capability_report(capabilities: CapabilityReport) -> None:
    print("Duplicate Engine Capability Check")
    print("")
    for status in capabilities.layers.values():
        display_status(status)
    if capabilities.blocking_errors:
        print("Blocking configuration errors:")
        for error in capabilities.blocking_errors:
            print(f"- {error}")
        print("")


def print_capability_short(capabilities: CapabilityReport) -> None:
    print("Capabilities:")
    for name in ["ocr", "tesseract_ocr", "openai_ocr_fallback", "embeddings", "llm_candidate_detector", "adjudicator_agent"]:
        status = capabilities.layers.get(name)
        if not status:
            continue
        state = "available" if status.available else "disabled" if not status.enabled else status.status
        reason = f" ({status.reason})" if status.reason else ""
        print(f"- {name}: {state}, used={status.used}{reason}")


def display_status(status: ProviderStatus) -> None:
    state = "available" if status.available else "disabled" if not status.enabled else status.status
    print(f"{status.layer}: {state}")
    print(f"  role: {status.role}")
    print(f"  enabled: {status.enabled}")
    print(f"  available: {status.available}")
    print(f"  used: {status.used}")
    print(f"  provider: {status.provider}")
    if status.model:
        print(f"  model: {status.model}")
    if status.endpoint_configured:
        print("  endpoint configured: true")
    if status.reason:
        print(f"  reason: {status.reason}")
    if status.required:
        print("  required: true")
    if status.details:
        print(f"  details: {status.details}")
    print("")


if __name__ == "__main__":
    main()
