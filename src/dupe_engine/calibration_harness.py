from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class CalibrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class VectorProfile:
    name: str
    enabled: bool
    top_k: int = 5
    min_similarity: float = 0.88
    min_margin: float = 0.03
    max_candidates_per_page: int = 2
    max_candidates_per_job: int = 300
    min_text_chars: int = 120
    hybrid_scoring: bool = False
    hybrid_min_score: float = 0.78


@dataclass(frozen=True)
class CalibrationRunSpec:
    run_id: str
    stage: str
    profile_name: str
    ocr_cap: int
    ocr_selection_mode: str
    ocr_reason_quotas: str
    vector_profile: str
    embeddings_enabled: bool
    embedding_top_k: int
    embedding_min_similarity: float
    embedding_min_margin: float
    embedding_max_candidates_per_page: int
    embedding_max_candidates_per_job: int
    embedding_min_text_chars: int
    queue_profile: str
    tesseract_profiles: str = ""
    openai_ocr_max_pages_per_document: int = 5
    post_candidate_rescue_pages: int = 0
    post_candidate_rescue_min_confidence: float = 0.50
    embedding_hybrid_scoring: bool = False
    embedding_hybrid_min_score: float = 0.78
    corpus_id: str = "primary"
    pdf_dir: str = ""
    truth: str = ""
    variant_id: str = "default"
    dpi: int | None = None
    ocr_evidence_upgrade_enabled: bool = False
    strict_tfidf_threshold: float | None = None
    standard_tfidf_threshold: float | None = None
    loose_tfidf_threshold: float | None = None
    multipass_text_top_k: int | None = None
    max_candidates_per_job: int | None = None
    max_candidates_per_page: int | None = None
    main_review_min_confidence: float | None = None
    main_review_max_candidates_per_100_pages: int | None = None
    openai_ocr_min_candidate_confidence: float | None = None
    sequence_anchor_min_confidence: float | None = None
    sequence_neighbor_window: int | None = None
    sequence_min_text_similarity: float | None = None
    sequence_min_text_similarity_with_visual: float | None = None
    sequence_visual_support_phash_threshold: int | None = None
    cross_view_text_candidates_enabled: bool = True
    rare_token_candidates_enabled: bool = True
    rare_token_min_overlap: int | None = None
    rare_token_min_jaccard: float | None = None
    rare_token_max_df: int | None = None
    embedding_reranker_enabled: bool = False
    embedding_reranker_min_confidence: float = 0.80
    embedding_reranker_ocr_penalty: float = 0.01
    embedding_reranker_same_doc_bonus: float = 0.03
    embedding_reranker_tesseract_bonus: float = 0.02
    embedding_reranker_action: str = "demote"


VECTOR_PROFILES: dict[str, VectorProfile] = {
    "off": VectorProfile("off", enabled=False),
    "v097_control": VectorProfile(
        "v097_control",
        enabled=True,
        top_k=5,
        min_similarity=0.88,
        min_margin=0.03,
        max_candidates_per_page=2,
        max_candidates_per_job=500,
        min_text_chars=120,
    ),
    "conservative": VectorProfile(
        "conservative",
        enabled=True,
        top_k=3,
        min_similarity=0.88,
        min_margin=0.05,
        max_candidates_per_page=1,
        max_candidates_per_job=150,
        min_text_chars=180,
    ),
    "balanced": VectorProfile(
        "balanced",
        enabled=True,
        top_k=5,
        min_similarity=0.85,
        min_margin=0.03,
        max_candidates_per_page=2,
        max_candidates_per_job=300,
        min_text_chars=150,
    ),
    "recall_first": VectorProfile(
        "recall_first",
        enabled=True,
        top_k=10,
        min_similarity=0.82,
        min_margin=0.02,
        max_candidates_per_page=2,
        max_candidates_per_job=500,
        min_text_chars=120,
    ),
    "hybrid_test": VectorProfile(
        "hybrid_test",
        enabled=True,
        top_k=5,
        min_similarity=0.82,
        min_margin=0.02,
        max_candidates_per_page=2,
        max_candidates_per_job=300,
        min_text_chars=150,
        hybrid_scoring=True,
        hybrid_min_score=0.78,
    ),
}

PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "low_cost": {"ocr_cap": 50, "vector": "conservative", "queue": "strict_main", "per_doc_cap": 5},
    "balanced": {"ocr_cap": 75, "vector": "balanced", "queue": "balanced", "per_doc_cap": 5},
    "recall_first": {"ocr_cap": 100, "vector": "recall_first", "queue": "recall_first", "per_doc_cap": 5},
    "accuracy_first": {"ocr_cap": 150, "vector": "balanced", "queue": "recall_first", "per_doc_cap": 8},
    "focused_rescue": {"ocr_cap": 150, "vector": "conservative", "queue": "balanced", "per_doc_cap": 8},
    "v4_calibration": {"ocr_cap": 225, "vector": "conservative", "queue": "balanced", "per_doc_cap": 8},
    "generalization": {"ocr_cap": 150, "vector": "balanced", "queue": "balanced", "per_doc_cap": 8},
}

DEFAULT_REASON_QUOTAS = "vision_expected:30,weak_tesseract:30,no_text:20,candidate_based:20"


def build_calibration_corpora(args: Any, pdf_dir: Path, truth: Path) -> list[dict[str, str]]:
    primary_id = getattr(args, "corpus_id", None) or pdf_dir.name or "primary"
    corpora = [{"corpus_id": str(primary_id), "pdf_dir": str(pdf_dir), "truth": str(truth)}]
    secondary_pdf = getattr(args, "secondary_pdf_dir", None)
    secondary_truth = getattr(args, "secondary_truth", None)
    if secondary_pdf or secondary_truth:
        if not secondary_pdf or not secondary_truth:
            raise CalibrationError("Both --secondary-pdf-dir and --secondary-truth are required for cross-corpus calibration")
        sec_pdf = Path(secondary_pdf).resolve()
        sec_truth = Path(secondary_truth).resolve()
        if not sec_pdf.exists():
            raise CalibrationError(f"Secondary PDF directory does not exist: {sec_pdf}")
        if not sec_truth.exists():
            raise CalibrationError(f"Secondary truth file does not exist: {sec_truth}")
        secondary_id = getattr(args, "secondary_corpus_id", None) or sec_pdf.name or "secondary"
        corpora.append({"corpus_id": str(secondary_id), "pdf_dir": str(sec_pdf), "truth": str(sec_truth)})
    return corpora


def run_calibration(args: Any) -> dict[str, Any]:
    pdf_dir = Path(args.pdf_dir).resolve()
    truth = Path(args.truth).resolve()
    out_dir = Path(args.out_dir).resolve()
    if not pdf_dir.exists():
        raise CalibrationError(f"PDF directory does not exist: {pdf_dir}")
    if not truth.exists():
        raise CalibrationError(f"Truth file does not exist: {truth}")

    corpora = build_calibration_corpora(args, pdf_dir, truth)
    stages = parse_stages(args.stages)
    if not args.dry_run and not args.confirm_live_ai:
        raise CalibrationError("Refusing to execute calibration with live AI routes unless --confirm-live-ai is provided. Use --dry-run to write only the plan.")

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "calibration_manifest.json"
    scorecard_json = out_dir / "scorecard.json"
    scorecard_csv = out_dir / "scorecard.csv"
    recommendations_path = out_dir / "recommended_configs.json"

    planned = build_initial_plan(args.profile, stages, max_runs=args.max_runs, corpora=corpora)
    if getattr(args, "only_run", None):
        planned = [spec for spec in planned if spec.run_id == args.only_run]
        if not planned:
            raise CalibrationError(f"--only-run did not match any planned run: {args.only_run}")
    write_json(
        manifest_path,
        {
            "schema_version": "dupe_engine_calibration_harness_v0_10_0",
            "pdf_dir": str(pdf_dir),
            "truth": str(truth),
            "out_dir": str(out_dir),
            "profile": args.profile,
            "stages": stages,
            "corpora": corpora,
            "planned_run_count": len(planned),
            "runs": [asdict(spec) for spec in planned],
            "safety": {"confirm_live_ai": bool(args.confirm_live_ai), "dry_run": bool(args.dry_run)},
        },
    )

    if args.dry_run:
        write_scorecard(scorecard_csv, [])
        write_json(scorecard_json, {"schema_version": "dupe_engine_calibration_scorecard_v0_10_0", "rows": []})
        return {
            "executed": False,
            "out_dir": str(out_dir),
            "planned_run_count": len(planned),
            "executed_run_count": 0,
            "scorecard_csv": str(scorecard_csv),
            "recommended_configs": None,
        }

    rows: list[dict[str, Any]] = []
    executed = 0
    total_runs = len(planned)
    root = Path(__file__).resolve().parents[2]
    src = str(root / "src")
    for index, spec in enumerate(planned, start=1):
        run_dir = out_dir / "runs" / spec.run_id
        run_config_path = run_dir / "run_config.json"
        status = read_json(run_dir / "run_status.json")
        existing_complete = (run_dir / "truth_eval.json").exists() and (run_dir / "phase_eval.json").exists()
        if status.get("status") == "running" and (args.resume or args.skip_existing):
            status.update({"status": "aborted", "completed_at": now_iso(), "error_message": "Previous calibration process exited before marking this run complete."})
            write_json(run_dir / "run_status.json", status)
        if existing_complete and (args.skip_existing or args.resume):
            row = build_scorecard_row(spec, run_dir, reused=True)
            rows.append(row)
            write_scorecard(scorecard_csv, rows)
            write_json(scorecard_json, {"schema_version": "dupe_engine_calibration_scorecard_v0_10_0", "rows": rows})
            continue
        if status.get("status") in {"failed", "aborted"} and (args.resume or args.skip_existing) and not getattr(args, "retry_failed", False):
            rows.append(build_failed_scorecard_row(spec, run_dir, status=status, reused=True))
            write_scorecard(scorecard_csv, rows)
            write_json(scorecard_json, {"schema_version": "dupe_engine_calibration_scorecard_v0_10_0", "rows": rows})
            continue
        if run_dir.exists() and not args.resume and not args.skip_existing:
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        write_json(run_config_path, asdict(spec))
        started = time.time()
        spec_pdf_dir = Path(spec.pdf_dir).resolve() if spec.pdf_dir else pdf_dir
        spec_truth = Path(spec.truth).resolve() if spec.truth else truth
        cmd = build_eval_command(spec, spec_pdf_dir, spec_truth, run_dir, args)
        env = os.environ.copy()
        env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        (run_dir / "command.txt").write_text(" ".join(cmd) + "\n", encoding="utf-8")
        write_run_status(run_dir, spec, status="running", command=cmd, started_at=now_iso())
        returncode = run_subprocess_with_progress(cmd, cwd=root, env=env, run_dir=run_dir, spec=spec, run_index=index, total_runs=total_runs, progress_mode=getattr(args, "progress", "tui"))
        if returncode != 0:
            error = {"status": "failed", "returncode": returncode, "completed_at": now_iso(), "error_message": f"Sub-run failed with exit code {returncode}", "stdout_tail": read_text_tail(run_dir / "stdout.log")}
            write_json(run_dir / "run_error.json", error)
            write_run_status(run_dir, spec, status="failed", exit_code=returncode, completed_at=now_iso(), error_message=error["error_message"])
            row = build_failed_scorecard_row(spec, run_dir, status=error, runtime_seconds=round(time.time() - started, 2), reused=False)
            rows.append(row)
            write_scorecard(scorecard_csv, rows)
            write_json(scorecard_json, {"schema_version": "dupe_engine_calibration_scorecard_v0_10_0", "rows": rows})
            if getattr(args, "fail_fast", False):
                raise CalibrationError(f"Sub-run {spec.run_id} failed with exit code {returncode}. See {run_dir / 'stdout.log'}")
            continue
        write_run_status(run_dir, spec, status="succeeded", exit_code=0, completed_at=now_iso())
        row = build_scorecard_row(spec, run_dir, runtime_seconds=round(time.time() - started, 2), reused=False)
        rows.append(row)
        executed += 1
        write_scorecard(scorecard_csv, rows)
        write_json(scorecard_json, {"schema_version": "dupe_engine_calibration_scorecard_v0_10_0", "rows": rows})
        render_completed_run(row, mode=getattr(args, "progress", "tui"))

    recommendations = build_recommendations(rows)
    write_json(recommendations_path, recommendations)
    write_scorecard(scorecard_csv, rows)
    write_json(scorecard_json, {"schema_version": "dupe_engine_calibration_scorecard_v0_10_0", "rows": rows, "recommendations": recommendations})
    analysis_result = None
    if bool(getattr(args, "llm_analysis", False)):
        from .calibration_analysis import LlmAnalysisOptions, run_calibration_llm_analysis

        analysis_result = run_calibration_llm_analysis(
            out_dir,
            LlmAnalysisOptions(
                enabled=True,
                dry_run=bool(getattr(args, "llm_analysis_dry_run", False)),
                include_text_snippets=bool(getattr(args, "llm_analysis_include_text_snippets", False)),
                model=getattr(args, "llm_analysis_model", None),
                output_md=getattr(args, "llm_analysis_out", None),
                output_json=getattr(args, "llm_analysis_json_out", None),
            ),
        )
    return {
        "executed": True,
        "out_dir": str(out_dir),
        "planned_run_count": len(planned),
        "executed_run_count": executed,
        "scorecard_csv": str(scorecard_csv),
        "recommended_configs": str(recommendations_path),
        "llm_analysis": analysis_result,
    }


def parse_stages(value: str) -> list[str]:
    allowed = {"control", "ocr", "vector", "queue", "focused", "v4"}
    stages = [part.strip().lower() for part in (value or "control,ocr,vector,queue").split(",") if part.strip()]
    invalid = [stage for stage in stages if stage not in allowed]
    if invalid:
        raise CalibrationError(f"Unknown calibration stage(s): {', '.join(invalid)}")
    return stages or ["ocr", "vector", "queue"]


def build_initial_plan(profile: str, stages: list[str], max_runs: int | None = None, corpora: list[dict[str, str]] | None = None) -> list[CalibrationRunSpec]:
    defaults = PROFILE_DEFAULTS.get(profile, PROFILE_DEFAULTS["balanced"])
    corpora = corpora or [{"corpus_id": "primary", "pdf_dir": "", "truth": ""}]
    specs: list[CalibrationRunSpec] = []
    counter = 1

    def add(
        stage: str,
        ocr_cap: int,
        ocr_mode: str,
        vector_name: str,
        queue_profile: str,
        *,
        tesseract_profiles: str = "",
        per_doc_cap: int | None = None,
        post_rescue_pages: int = 0,
        post_rescue_min_confidence: float = 0.50,
        corpus: dict[str, str] | None = None,
        variant_id: str = "default",
        dpi: int | None = None,
        ocr_evidence_upgrade: bool = False,
    ) -> None:
        nonlocal counter
        vector = VECTOR_PROFILES[vector_name]
        corpus = corpus or corpora[0]
        specs.append(
            CalibrationRunSpec(
                run_id=f"run_{counter:03d}_{slug(str(corpus.get('corpus_id', 'primary')))}_{stage}_{slug(variant_id)}_{slug(ocr_mode)}_cap{ocr_cap}_{vector.name}_{queue_profile}_rescue{post_rescue_pages}",
                stage=stage,
                profile_name=profile,
                ocr_cap=ocr_cap,
                ocr_selection_mode=ocr_mode,
                ocr_reason_quotas=DEFAULT_REASON_QUOTAS,
                vector_profile=vector.name,
                embeddings_enabled=vector.enabled,
                embedding_top_k=vector.top_k,
                embedding_min_similarity=vector.min_similarity,
                embedding_min_margin=vector.min_margin,
                embedding_max_candidates_per_page=vector.max_candidates_per_page,
                embedding_max_candidates_per_job=vector.max_candidates_per_job,
                embedding_min_text_chars=vector.min_text_chars,
                queue_profile=queue_profile,
                tesseract_profiles=tesseract_profiles,
                openai_ocr_max_pages_per_document=int(per_doc_cap if per_doc_cap is not None else defaults.get("per_doc_cap", 5)),
                post_candidate_rescue_pages=int(post_rescue_pages),
                post_candidate_rescue_min_confidence=float(post_rescue_min_confidence),
                embedding_hybrid_scoring=bool(vector.hybrid_scoring),
                embedding_hybrid_min_score=float(vector.hybrid_min_score),
                corpus_id=str(corpus.get("corpus_id", "primary")),
                pdf_dir=str(corpus.get("pdf_dir", "")),
                truth=str(corpus.get("truth", "")),
                variant_id=variant_id,
                dpi=dpi,
                ocr_evidence_upgrade_enabled=bool(ocr_evidence_upgrade),
            )
        )
        counter += 1

    if "control" in stages and profile not in {"focused_rescue", "v4_calibration", "generalization"}:
        # v0.9.9 sanity control: reproduce the last known-good v0.9.7-style
        # medium run before trusting the staged calibration matrix. It uses
        # standard-only Tesseract profiles and the pre-reason-balanced fallback
        # selection mode so regressions in the harness/config path are obvious.
        add(
            "control",
            50,
            "weak_pages_or_vision_expected",
            "v097_control",
            "balanced",
            tesseract_profiles="standard",
            per_doc_cap=5,
        )

    if profile == "generalization":
        per_doc_cap = int(defaults.get("per_doc_cap", 8))
        variants = [
            {
                "variant_id": "stable_baseline",
                "ocr_cap": 150,
                "vector": "conservative",
                "queue": "balanced",
                "dpi": None,
                "ocr_evidence_upgrade": False,
            },
            {
                "variant_id": "evidence_conservative",
                "ocr_cap": 150,
                "vector": "conservative",
                "queue": "balanced",
                "dpi": None,
                "ocr_evidence_upgrade": True,
            },
            {
                "variant_id": "evidence_balanced_vector",
                "ocr_cap": 150,
                "vector": "balanced",
                "queue": "balanced",
                "dpi": None,
                "ocr_evidence_upgrade": True,
            },
            {
                "variant_id": "evidence_recall_queue",
                "ocr_cap": 150,
                "vector": "balanced",
                "queue": "recall_first",
                "dpi": None,
                "ocr_evidence_upgrade": True,
            },
            {
                "variant_id": "evidence_high_dpi",
                "ocr_cap": 150,
                "vector": "balanced",
                "queue": "balanced",
                "dpi": 200,
                "ocr_evidence_upgrade": True,
            },
        ]
        for variant in variants:
            for corpus in corpora:
                add(
                    "generalization",
                    int(variant["ocr_cap"]),
                    "reason_balanced",
                    str(variant["vector"]),
                    str(variant["queue"]),
                    per_doc_cap=per_doc_cap,
                    post_rescue_pages=0,
                    corpus=corpus,
                    variant_id=str(variant["variant_id"]),
                    dpi=variant["dpi"],
                    ocr_evidence_upgrade=bool(variant["ocr_evidence_upgrade"]),
                )
    elif profile == "focused_rescue":
        per_doc_cap = int(defaults.get("per_doc_cap", 8))
        # v0.9.9 focused matrix: compare current best vs targeted post-candidate
        # rescue budgets and the experimental hybrid vector gate. This avoids
        # rerunning broad sweeps now that v0.9.8b identified the baseline.
        add("focused", 150, "reason_balanced", "conservative", "balanced", per_doc_cap=per_doc_cap, post_rescue_pages=0)
        add("focused", 150, "reason_balanced", "conservative", "balanced", per_doc_cap=per_doc_cap, post_rescue_pages=25)
        add("focused", 150, "reason_balanced", "conservative", "balanced", per_doc_cap=per_doc_cap, post_rescue_pages=50)
        add("focused", 150, "reason_balanced", "hybrid_test", "balanced", per_doc_cap=per_doc_cap, post_rescue_pages=50)
        add("focused", 150, "reason_balanced", "hybrid_test", "balanced", per_doc_cap=per_doc_cap, post_rescue_pages=75)
    elif profile == "v4_calibration":
        per_doc_cap = int(defaults.get("per_doc_cap", 8))
        # v0.9.9a v4 calibration matrix: keep the run count small and test
        # exactly the remaining uncertainty on the fresh calibration corpus.
        # 1) current best stable profile, 2) higher OCR budget, 3) targeted
        # rescue, 4) higher budget + rescue, 5) higher budget + broader vector.
        add("v4", 150, "reason_balanced", "conservative", "balanced", per_doc_cap=per_doc_cap, post_rescue_pages=0)
        add("v4", 225, "reason_balanced", "conservative", "balanced", per_doc_cap=per_doc_cap, post_rescue_pages=0)
        add("v4", 150, "reason_balanced", "conservative", "balanced", per_doc_cap=per_doc_cap, post_rescue_pages=50)
        add("v4", 225, "reason_balanced", "conservative", "balanced", per_doc_cap=per_doc_cap, post_rescue_pages=25)
        add("v4", 225, "reason_balanced", "balanced", "balanced", per_doc_cap=per_doc_cap, post_rescue_pages=0)
    elif profile == "accuracy_first":
        per_doc_cap = int(defaults.get("per_doc_cap", 8))
        if "ocr" in stages:
            # Keep a no-fallback baseline, then focus on high-recall OCR budgets.
            add("ocr", 0, "weak_pages_or_vision_expected", "off", "balanced", per_doc_cap=per_doc_cap)
            add("ocr", 100, "weak_pages_or_vision_expected", "off", "balanced", per_doc_cap=per_doc_cap)
            add("ocr", 100, "reason_balanced", "off", "balanced", per_doc_cap=per_doc_cap)
            add("ocr", 150, "reason_balanced", "off", "balanced", per_doc_cap=per_doc_cap)
        if "vector" in stages:
            for cap in [100, 150]:
                for vector_name in ["conservative", "balanced"]:
                    add("vector", cap, "reason_balanced", vector_name, "balanced", per_doc_cap=per_doc_cap)
            add("vector", 150, "reason_balanced", "recall_first", "balanced", per_doc_cap=per_doc_cap)
        if "queue" in stages:
            for queue_profile in ["strict_main", "balanced", "recall_first"]:
                add("queue", 150, "reason_balanced", "balanced", queue_profile, per_doc_cap=per_doc_cap)
    else:
        if "ocr" in stages:
            for cap in [0, 50, 75, 100]:
                for mode in ["weak_pages_or_vision_expected", "reason_balanced"]:
                    add("ocr", cap, mode, "off", "balanced")

        if "vector" in stages:
            ocr_cap = int(defaults["ocr_cap"])
            for vector_name in ["off", "conservative", "balanced", "recall_first"]:
                add("vector", ocr_cap, "reason_balanced", vector_name, "balanced")

        if "queue" in stages:
            ocr_cap = int(defaults["ocr_cap"])
            vector_name = str(defaults["vector"])
            for queue_profile in ["strict_main", "balanced", "recall_first"]:
                add("queue", ocr_cap, "reason_balanced", vector_name, queue_profile)

    if max_runs is not None and max_runs > 0:
        return specs[:max_runs]
    return specs


def build_eval_command(spec: CalibrationRunSpec, pdf_dir: Path, truth: Path, run_dir: Path, args: Any) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "dupe_engine.cli",
        "eval-all",
        str(pdf_dir),
        "--truth",
        str(truth),
        "--work-dir",
        str(run_dir / "work"),
        "--out",
        str(run_dir / "results.json"),
        "--eval-out",
        str(run_dir / "truth_eval.json"),
        "--phase-eval-out",
        str(run_dir / "phase_eval.json"),
        "--calibration-out",
        str(run_dir / "calibration.json"),
        "--candidate-summary-csv",
        str(run_dir / "candidate_summary.csv"),
        "--false-negative-csv",
        str(run_dir / "false_negatives.csv"),
        "--false-positive-csv",
        str(run_dir / "false_positive_review.csv"),
        "--fallback-audit-out",
        str(run_dir / "fallback_audit.json"),
        "--fallback-audit-csv",
        str(run_dir / "fallback_pages.csv"),
        "--ocr-validation-out",
        str(run_dir / "ocr_validation.json"),
        "--run-dir",
        str(run_dir),
        "--dpi",
        str(spec.dpi if spec.dpi is not None else args.dpi),
        "--ocr",
        "--require-ocr",
        "--openai-ocr",
        "--openai-ocr-live",
        "--require-openai-ocr",
        "--openai-ocr-max-pages",
        str(spec.ocr_cap),
        "--openai-ocr-selection-mode",
        spec.ocr_selection_mode,
        "--openai-ocr-reason-quotas",
        spec.ocr_reason_quotas,
        "--openai-ocr-max-pages-per-document",
        str(spec.openai_ocr_max_pages_per_document),
        "--queue-profile",
        spec.queue_profile,
        "--tesseract-profiles",
        str(spec.tesseract_profiles or args.tesseract_profiles),
    ]
    if spec.post_candidate_rescue_pages > 0:
        cmd.extend([
            "--openai-ocr-post-candidate-rescue",
            "--openai-ocr-post-candidate-rescue-pages",
            str(spec.post_candidate_rescue_pages),
            "--openai-ocr-post-candidate-min-confidence",
            str(spec.post_candidate_rescue_min_confidence),
        ])
    if spec.ocr_evidence_upgrade_enabled:
        cmd.extend(["--openai-ocr-evidence-upgrade", "--openai-ocr-combine-evidence", "--openai-ocr-key-token-acceptance"])
    append_optional_engine_overrides(cmd, spec)
    if spec.embeddings_enabled:
        cmd.extend(
            [
                "--embeddings",
                "--embedding-top-k",
                str(spec.embedding_top_k),
                "--embedding-similarity-threshold",
                str(spec.embedding_min_similarity),
                "--embedding-min-margin",
                str(spec.embedding_min_margin),
                "--embedding-max-candidates-per-page",
                str(spec.embedding_max_candidates_per_page),
                "--embedding-max-pages",
                "1000",
                "--embedding-min-text-chars",
                str(spec.embedding_min_text_chars),
            ]
        )
        cmd.extend(["--embedding-max-candidates-per-job", str(spec.embedding_max_candidates_per_job)])
        if spec.embedding_hybrid_scoring:
            cmd.extend(["--embedding-hybrid-scoring", "--embedding-hybrid-min-score", str(spec.embedding_hybrid_min_score)])
    if spec.embedding_reranker_enabled:
        cmd.extend([
            "--embedding-reranker",
            "--embedding-reranker-min-confidence", str(spec.embedding_reranker_min_confidence),
            "--embedding-reranker-ocr-penalty", str(spec.embedding_reranker_ocr_penalty),
            "--embedding-reranker-same-doc-bonus", str(spec.embedding_reranker_same_doc_bonus),
            "--embedding-reranker-tesseract-bonus", str(spec.embedding_reranker_tesseract_bonus),
            "--embedding-reranker-action", spec.embedding_reranker_action,
        ])
    return cmd


def append_optional_engine_overrides(cmd: list[str], spec: CalibrationRunSpec) -> None:
    """Append existing engine config knobs carried by calibration-loop specs.

    These are CLI/config overrides only. They do not introduce new detector
    behavior; they let the harness test stricter or looser acceptance and
    candidate-formation thresholds that already exist in EngineConfig.
    """

    optional_flags: list[tuple[str, Any]] = [
        ("--strict-tfidf-threshold", spec.strict_tfidf_threshold),
        ("--standard-tfidf-threshold", spec.standard_tfidf_threshold),
        ("--loose-tfidf-threshold", spec.loose_tfidf_threshold),
        ("--multipass-text-top-k", spec.multipass_text_top_k),
        ("--max-candidates-per-job", spec.max_candidates_per_job),
        ("--max-candidates-per-page", spec.max_candidates_per_page),
        ("--main-review-min-confidence", spec.main_review_min_confidence),
        ("--main-review-max-candidates-per-100-pages", spec.main_review_max_candidates_per_100_pages),
        ("--openai-ocr-min-candidate-confidence", spec.openai_ocr_min_candidate_confidence),
        ("--sequence-anchor-min-confidence", spec.sequence_anchor_min_confidence),
        ("--sequence-neighbor-window", spec.sequence_neighbor_window),
        ("--sequence-min-text-similarity", spec.sequence_min_text_similarity),
        ("--sequence-min-text-similarity-with-visual", spec.sequence_min_text_similarity_with_visual),
        ("--sequence-visual-support-phash-threshold", spec.sequence_visual_support_phash_threshold),
        ("--rare-token-min-overlap", spec.rare_token_min_overlap),
        ("--rare-token-min-jaccard", spec.rare_token_min_jaccard),
        ("--rare-token-max-df", spec.rare_token_max_df),
    ]
    for flag, value in optional_flags:
        if value is not None:
            cmd.extend([flag, str(value)])
    if spec.cross_view_text_candidates_enabled is False:
        cmd.append("--disable-cross-view-text-candidates")
    if spec.rare_token_candidates_enabled is False:
        cmd.append("--disable-rare-token-candidates")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_run_status(run_dir: Path, spec: CalibrationRunSpec, **updates: Any) -> None:
    payload = read_json(run_dir / "run_status.json")
    payload.update({
        "run_id": spec.run_id,
        "stage": spec.stage,
        "profile_name": spec.profile_name,
        "corpus_id": spec.corpus_id,
        "variant_id": spec.variant_id,
        "dpi": spec.dpi,
        "ocr_evidence_upgrade_enabled": spec.ocr_evidence_upgrade_enabled,
        "strict_tfidf_threshold": spec.strict_tfidf_threshold,
        "standard_tfidf_threshold": spec.standard_tfidf_threshold,
        "loose_tfidf_threshold": spec.loose_tfidf_threshold,
        "multipass_text_top_k": spec.multipass_text_top_k,
        "max_candidates_per_job": spec.max_candidates_per_job,
        "max_candidates_per_page": spec.max_candidates_per_page,
        "main_review_min_confidence": spec.main_review_min_confidence,
        "main_review_max_candidates_per_100_pages": spec.main_review_max_candidates_per_100_pages,
        "openai_ocr_min_candidate_confidence": spec.openai_ocr_min_candidate_confidence,
        "openai_ocr_max_pages_per_document": spec.openai_ocr_max_pages_per_document,
        "sequence_anchor_min_confidence": spec.sequence_anchor_min_confidence,
        "sequence_neighbor_window": spec.sequence_neighbor_window,
        "sequence_min_text_similarity": spec.sequence_min_text_similarity,
        "sequence_min_text_similarity_with_visual": spec.sequence_min_text_similarity_with_visual,
        "sequence_visual_support_phash_threshold": spec.sequence_visual_support_phash_threshold,
        "cross_view_text_candidates_enabled": spec.cross_view_text_candidates_enabled,
        "rare_token_candidates_enabled": spec.rare_token_candidates_enabled,
        "rare_token_min_overlap": spec.rare_token_min_overlap,
        "rare_token_min_jaccard": spec.rare_token_min_jaccard,
        "rare_token_max_df": spec.rare_token_max_df,
        "ocr_cap": spec.ocr_cap,
        "ocr_selection_mode": spec.ocr_selection_mode,
        "vector_profile": spec.vector_profile,
        "queue_profile": spec.queue_profile,
        "post_candidate_rescue_pages": spec.post_candidate_rescue_pages,
        "embedding_hybrid_scoring": spec.embedding_hybrid_scoring,
    })
    payload.update(updates)
    if "started_at" not in payload:
        payload["started_at"] = now_iso()
    write_json(run_dir / "run_status.json", payload)


def run_subprocess_with_progress(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    run_dir: Path,
    spec: CalibrationRunSpec,
    run_index: int,
    total_runs: int,
    progress_mode: str = "tui",
) -> int:
    stdout_path = run_dir / "stdout.log"
    started = time.time()
    with stdout_path.open("w", encoding="utf-8") as stdout_file:
        proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, text=True, stdout=stdout_file, stderr=subprocess.STDOUT)
        last_render = 0.0
        while proc.poll() is None:
            now = time.time()
            if now - last_render >= 2.0:
                render_progress_tick(run_dir, spec, run_index, total_runs, started, progress_mode)
                last_render = now
            time.sleep(0.5)
        render_progress_tick(run_dir, spec, run_index, total_runs, started, progress_mode, final=True)
        return int(proc.returncode or 0)


def render_progress_tick(
    run_dir: Path,
    spec: CalibrationRunSpec,
    run_index: int,
    total_runs: int,
    started: float,
    mode: str,
    *,
    final: bool = False,
) -> None:
    if mode == "none":
        return
    elapsed = int(time.time() - started)
    progress = read_json(run_dir / "progress.json")
    stage = progress.get("stage") or "starting"
    message = progress.get("message") or "starting run"
    current = progress.get("current")
    total = progress.get("total")
    if mode == "plain" or not sys.stdout.isatty():
        progress_bits = f" {current}/{total}" if current is not None and total is not None else ""
        print(
            f"[calibrate {run_index}/{total_runs}] {spec.run_id} | "
            f"OCR cap={spec.ocr_cap} mode={spec.ocr_selection_mode} vector={spec.vector_profile} "
            f"rescue={spec.post_candidate_rescue_pages} queue={spec.queue_profile} | "
            f"{stage}{progress_bits} | {message} | elapsed={format_duration(elapsed)}",
            flush=True,
        )
        return
    render_progress_dashboard(run_dir, spec, run_index, total_runs, elapsed, stage, message, final=final)


def render_progress_dashboard(
    run_dir: Path,
    spec: CalibrationRunSpec,
    run_index: int,
    total_runs: int,
    elapsed: int,
    stage: str,
    message: str,
    *,
    final: bool = False,
) -> None:
    progress = read_json(run_dir / "progress.json")
    events = read_progress_events(run_dir / "progress_events.jsonl")
    categories = summarize_progress_categories(events)
    run_pct = estimate_run_progress(spec, progress, categories)
    overall_pct = ((run_index - 1) + run_pct) / max(1, total_runs)
    score_rows = read_scorecard_rows(run_dir)
    completed = len([row for row in score_rows if row.get("status") == "succeeded"])
    failed = len([row for row in score_rows if row.get("status") in {"failed", "aborted"}])
    width = max(92, min(128, shutil.get_terminal_size((110, 32)).columns))
    bar_width = 30

    print("\033[2J\033[H", end="")
    print("╭" + "─" * (width - 2) + "╮")
    print(f"│ {'Dupe Engine calibration':<{width - 4}} │")
    print("├" + "─" * (width - 2) + "┤")
    print(f"│ Profile: {spec.profile_name:<18} Corpus: {truncate_middle(spec.corpus_id, 14):<14} Runs: {run_index}/{total_runs:<3} done={completed:<2} failed={failed:<2} elapsed={format_duration(elapsed):<9} │".ljust(width - 1) + "│")
    print(f"│ Current: {truncate_middle(spec.run_id, width - 13):<{width - 13}} │")
    config = f"variant={spec.variant_id} | OCR cap={spec.ocr_cap} {spec.ocr_selection_mode} | vector={spec.vector_profile} | queue={spec.queue_profile} | rescue={spec.post_candidate_rescue_pages} | evidence_upgrade={spec.ocr_evidence_upgrade_enabled}"
    print(f"│ Config:  {truncate_middle(config, width - 13):<{width - 13}} │")
    print("├" + "─" * (width - 2) + "┤")
    print(f"│ Overall calibration  {render_bar(None, None, overall_pct, width=bar_width)}  {run_index - 1}/{total_runs} complete".ljust(width - 1) + "│")
    print(f"│ Current run          {render_bar(None, None, run_pct, width=bar_width)}  {format_progress_numbers(progress.get('current'), progress.get('total'))}".ljust(width - 1) + "│")
    print(f"│ Stage                {truncate_middle(stage + ' - ' + message, width - 24):<{width - 24}} │")
    print("├" + "─" * (width - 2) + "┤")
    for label, event_key in [
        ("PDF render + Tesseract", "ocr"),
        ("OpenAI OCR fallback", "openai"),
        ("Candidate generation", "candidates"),
        ("Vector embeddings", "embedding"),
        ("Post-candidate rescue", "post_rescue"),
        ("Reports / artifacts", "artifacts"),
    ]:
        event = categories.get(event_key)
        pct = stage_category_progress(event_key, event, spec)
        cur = event.get("current") if event else None
        tot = event.get("total") if event else None
        status_text = category_status_text(event_key, event, spec)
        print(f"│ {label:<22} {render_bar(cur, tot, pct, width=bar_width)}  {status_text:<22} │".ljust(width - 1) + "│")
    print("├" + "─" * (width - 2) + "┤")
    if score_rows:
        print(f"│ {'Last completed runs':<{width - 4}} │")
        for row in score_rows[-3:]:
            summary = (
                f"{row.get('run_id','')} | status={row.get('status','')} | "
                f"recall={row.get('strict_recall','')} ocr={row.get('ocr_dependent_recall','')} "
                f"TP={row.get('true_positives','')} FN={row.get('false_negatives','')} "
                f"neg={row.get('known_negative_hits','')} q={row.get('main_queue_size','')}/{row.get('secondary_queue_size','')}"
            )
            print(f"│   {truncate_middle(summary, width - 7):<{width - 7}} │")
    else:
        print(f"│ {'No completed sub-runs yet.':<{width - 4}} │")
    print("├" + "─" * (width - 2) + "┤")
    print(f"│ Logs: {truncate_middle(str(run_dir / 'stdout.log'), width - 11):<{width - 11}} │")
    print("╰" + "─" * (width - 2) + "╯")
    if final:
        print("")



def render_parallel_progress_dashboard(
    iter_dir: Path,
    specs: list[CalibrationRunSpec],
    *,
    iteration: int,
    target_recall: float,
    target_metric: str,
    started: float,
    max_parallel: int,
    final: bool = False,
) -> None:
    """Render a single parent-owned dashboard for concurrent calibration runs.

    Child processes write progress.json/progress_events.jsonl in their own run
    folders. The parent loop reads those files and owns terminal rendering so
    two simultaneous sub-runs never compete for cursor control.
    """

    elapsed = int(time.time() - started)
    term = shutil.get_terminal_size((122, 36))
    width = max(104, min(148, term.columns))
    compact = len(specs) > 4 or term.lines < 34
    bar_width = 14 if compact else 18
    run_summaries = collect_parallel_run_summaries(iter_dir, specs)
    total_runs = max(1, len(run_summaries))
    completed = len([item for item in run_summaries if item["status"] == "succeeded"])
    failed = len([item for item in run_summaries if item["status"] in {"failed", "aborted"}])
    running = len([item for item in run_summaries if item["status"] == "running"])
    pending = len([item for item in run_summaries if item["status"] in {"pending", "starting"}])
    overall_pct = sum(float(item["progress_pct"] or 0.0) for item in run_summaries) / total_runs
    score_rows = read_iteration_scorecard_rows(iter_dir)

    def line(text: str = "") -> None:
        print(f"│ {truncate_middle(text, width - 4):<{width - 4}} │")

    print("\033[2J\033[H", end="")
    print("╭" + "─" * (width - 2) + "╮")
    line("Dupe Engine calibration loop · aggregate parallel TUI" + (" · compact" if compact else ""))
    print("├" + "─" * (width - 2) + "┤")
    line(
        f"Iteration {iteration} | target {target_metric}>={target_recall:.2f} | "
        f"workers {running}/{max_parallel} active | done={completed} failed={failed} pending={pending} | elapsed={format_duration(elapsed)}"
    )
    line(f"Overall {render_bar(None, None, overall_pct, width=bar_width)}  {completed + failed}/{total_runs} finished")
    print("├" + "─" * (width - 2) + "┤")
    for item in run_summaries:
        status = parallel_status_label(item["status"])
        spec = item["spec"]
        stage_text = f"{item['stage']} - {item['message']}" if item["message"] else str(item["stage"])
        if compact:
            run_head = (
                f"{item['index']:02d} {status:<5} {truncate_middle(spec.run_id, 34):<34} "
                f"{truncate_middle(spec.corpus_id, 10):<10} {render_bar(None, None, item['progress_pct'], width=bar_width)} "
                f"OCR={spec.ocr_cap:<3} cand={spec.max_candidates_per_job or '-':<5} {truncate_middle(stage_text, 32)}"
            )
            line(run_head)
        else:
            run_head = (
                f"{item['index']:02d} {status:<5} {truncate_middle(spec.run_id, 30):<30} "
                f"{truncate_middle(spec.corpus_id, 14):<14} {render_bar(None, None, item['progress_pct'], width=bar_width)}"
            )
            line(run_head)
            config = (
                f"variant={spec.variant_id} | OCR={spec.ocr_cap} | vector={spec.vector_profile} | "
                f"queue={spec.queue_profile} | xview={spec.cross_view_text_candidates_enabled} | rare={spec.rare_token_candidates_enabled}"
            )
            line("     " + config)
            line("     " + stage_text)
    print("├" + "─" * (width - 2) + "┤")
    if score_rows:
        line("Last completed runs")
        for row in score_rows[-3:]:
            summary = (
                f"{row.get('run_id','')} | recall={row.get('strict_recall','')} "
                f"ocr={row.get('ocr_dependent_recall','')} neg={row.get('known_negative_hits','')} "
                f"unknown={row.get('unknown_predictions','')} status={row.get('status','')}"
            )
            line("  " + summary)
    else:
        line("No completed sub-runs yet. Child stdout is captured under iteration_*/runs/*/stdout.log.")
    print("├" + "─" * (width - 2) + "┤")
    line(f"Iteration dir: {iter_dir}")
    print("╰" + "─" * (width - 2) + "╯")
    if final:
        print("")


def collect_parallel_run_summaries(iter_dir: Path, specs: list[CalibrationRunSpec]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for index, spec in enumerate(specs, start=1):
        run_dir = iter_dir / "runs" / spec.run_id
        status_payload = read_json(run_dir / "run_status.json")
        raw_status = str(status_payload.get("status") or "")
        if not raw_status:
            raw_status = "starting" if run_dir.exists() else "pending"
        progress = read_json(run_dir / "progress.json")
        events = read_progress_events(run_dir / "progress_events.jsonl")
        categories = summarize_progress_categories(events)
        if raw_status == "succeeded":
            pct = 1.0
        elif raw_status in {"failed", "aborted"}:
            pct = max(estimate_run_progress(spec, progress, categories), 0.01)
        elif raw_status == "pending":
            pct = 0.0
        else:
            pct = estimate_run_progress(spec, progress, categories)
        stage = progress.get("stage") or raw_status
        message = progress.get("message") or status_payload.get("error_message") or ""
        summaries.append(
            {
                "index": index,
                "spec": spec,
                "run_dir": run_dir,
                "status": raw_status,
                "progress_pct": max(0.0, min(1.0, float(pct or 0.0))),
                "stage": stage,
                "message": message,
            }
        )
    return summaries


def parallel_status_label(status: str) -> str:
    if status == "succeeded":
        return "DONE"
    if status in {"failed", "aborted"}:
        return "FAIL"
    if status == "running":
        return "RUN"
    if status == "starting":
        return "BOOT"
    return "WAIT"


def read_iteration_scorecard_rows(iter_dir: Path) -> list[dict[str, Any]]:
    scorecard = iter_dir / "scorecard.csv"
    if not scorecard.exists():
        return []
    try:
        with scorecard.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []

def read_scorecard_rows(run_dir: Path) -> list[dict[str, Any]]:
    scorecard = run_dir.parent.parent / "scorecard.csv"
    if not scorecard.exists():
        return []
    try:
        with scorecard.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


def estimate_run_progress(spec: CalibrationRunSpec, progress: dict[str, Any], categories: dict[str, dict[str, Any]]) -> float:
    weights: list[tuple[str, float]] = [("ocr", 0.26), ("openai", 0.32), ("candidates", 0.10), ("artifacts", 0.08)]
    if spec.embeddings_enabled:
        weights.append(("embedding", 0.16))
    if spec.post_candidate_rescue_pages > 0:
        weights.append(("post_rescue", 0.08))
    total_weight = sum(weight for _, weight in weights) or 1.0
    weighted = 0.0
    for key, weight in weights:
        weighted += stage_category_progress(key, categories.get(key), spec) * weight
    pct = weighted / total_weight
    current_stage = str(progress.get("stage") or "")
    if current_stage == "complete":
        pct = 1.0
    return max(0.0, min(1.0, pct))


def stage_category_progress(key: str, event: dict[str, Any] | None, spec: CalibrationRunSpec) -> float:
    if key == "post_rescue" and spec.post_candidate_rescue_pages <= 0:
        return 1.0
    if key == "embedding" and not spec.embeddings_enabled:
        return 1.0
    if not event:
        return 0.0
    stage = str(event.get("stage") or "")
    if stage.endswith("complete") or stage in {"ingest_complete", "candidates_generated", "candidates_regenerated", "candidates_regenerated_after_post_candidate_rescue", "ui_artifacts_written", "fallback_audit_written", "complete"}:
        return 1.0
    pct = event.get("percent")
    try:
        if pct is not None:
            return max(0.0, min(1.0, float(pct)))
        current = event.get("current")
        total = event.get("total")
        if current is not None and total:
            return max(0.0, min(1.0, float(current) / float(total)))
    except Exception:
        pass
    return 0.15


def category_status_text(key: str, event: dict[str, Any] | None, spec: CalibrationRunSpec) -> str:
    if key == "post_rescue" and spec.post_candidate_rescue_pages <= 0:
        return "not configured"
    if key == "embedding" and not spec.embeddings_enabled:
        return "disabled"
    if not event:
        return "pending"
    current = event.get("current")
    total = event.get("total")
    if current is not None and total is not None:
        return f"{current}/{total}"
    stage = str(event.get("stage") or "")
    return stage.replace("_", " ")[:22]


def format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "0s"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def truncate_middle(value: Any, width: int) -> str:
    text = str(value)
    if len(text) <= width:
        return text
    if width <= 8:
        return text[:width]
    left = max(1, (width - 3) // 2)
    right = max(1, width - 3 - left)
    return text[:left] + "..." + text[-right:]


def read_progress_events(path: Path, limit: int = 250) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except Exception:
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def summarize_progress_categories(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    categories: dict[str, dict[str, Any]] = {}
    for event in events:
        stage = str(event.get("stage") or "")
        category = None
        if stage in {"reading_pdfs", "rendering_pages", "ocr_routing", "ingest_complete", "ingesting_corpus", "ingesting_group_a", "ingesting_group_b"}:
            category = "ocr"
        elif stage.startswith("post_candidate_openai_ocr") or stage in {"rerunning_after_post_candidate_rescue", "candidates_regenerated_after_post_candidate_rescue"}:
            category = "post_rescue"
        elif stage.startswith("openai_ocr") or stage in {"rerunning_after_fallback", "candidates_regenerated"}:
            category = "openai"
        elif stage in {"generating_candidates", "candidates_generated"}:
            category = "candidates"
        elif stage.startswith("embedding") or stage == "v2_layers":
            category = "embedding"
        elif stage in {"building_reports", "writing_ui_artifacts", "ui_artifacts_written", "fallback_audit_written", "complete"}:
            category = "artifacts"
        if category:
            categories[category] = event
    return categories


def progress_row_from_event(label: str, event: dict[str, Any] | None) -> tuple[str, Any, Any, Any]:
    if not event:
        return (label, None, None, None)
    return (label, event.get("current"), event.get("total"), event.get("percent"))


def bar_from_progress(progress: dict[str, Any]) -> str:
    return render_bar(progress.get("current"), progress.get("total"), progress.get("percent"))


def render_bar(current: Any, total: Any, pct: Any, width: int = 24) -> str:
    try:
        value = float(pct) if pct is not None else (float(current) / float(total) if current is not None and total else None)
    except Exception:
        value = None
    if value is None:
        return "[" + ("·" * width) + "]"
    value = max(0.0, min(1.0, value))
    filled = int(round(value * width))
    return "[" + ("█" * filled) + ("░" * (width - filled)) + f"] {value * 100:5.1f}%"


def format_progress_numbers(current: Any, total: Any) -> str:
    if current is None and total is None:
        return "pending"
    if current is None or total is None:
        return str(current or total or "")
    return f"{current}/{total}"


def last_completed_scorecard_row(run_dir: Path) -> dict[str, Any] | None:
    scorecard = run_dir.parent.parent / "scorecard.csv"
    if not scorecard.exists():
        return None
    try:
        with scorecard.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return None
    return rows[-1] if rows else None

def render_completed_run(row: dict[str, Any], mode: str) -> None:
    if mode == "none":
        return
    status = row.get("status", "succeeded")
    print(
        f"\n[completed] {row.get('run_id')} status={status} recall={row.get('strict_recall')} "
        f"ocr_recall={row.get('ocr_dependent_recall')} known_neg={row.get('known_negative_hits')} "
        f"main={row.get('main_queue_size')} secondary={row.get('secondary_queue_size')}",
        flush=True,
    )


def read_text_tail(path: Path, limit: int = 4000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]


def build_failed_scorecard_row(
    spec: CalibrationRunSpec,
    run_dir: Path,
    *,
    status: dict[str, Any] | None = None,
    runtime_seconds: float | None = None,
    reused: bool = False,
) -> dict[str, Any]:
    status = status or read_json(run_dir / "run_status.json")
    row = {
        "run_id": spec.run_id,
        "stage": spec.stage,
        "profile_name": spec.profile_name,
        "corpus_id": spec.corpus_id,
        "variant_id": spec.variant_id,
        "dpi": spec.dpi,
        "ocr_evidence_upgrade_enabled": spec.ocr_evidence_upgrade_enabled,
        "strict_tfidf_threshold": spec.strict_tfidf_threshold,
        "standard_tfidf_threshold": spec.standard_tfidf_threshold,
        "loose_tfidf_threshold": spec.loose_tfidf_threshold,
        "multipass_text_top_k": spec.multipass_text_top_k,
        "max_candidates_per_job": spec.max_candidates_per_job,
        "max_candidates_per_page": spec.max_candidates_per_page,
        "main_review_min_confidence": spec.main_review_min_confidence,
        "main_review_max_candidates_per_100_pages": spec.main_review_max_candidates_per_100_pages,
        "openai_ocr_min_candidate_confidence": spec.openai_ocr_min_candidate_confidence,
        "openai_ocr_max_pages_per_document": spec.openai_ocr_max_pages_per_document,
        "sequence_anchor_min_confidence": spec.sequence_anchor_min_confidence,
        "sequence_neighbor_window": spec.sequence_neighbor_window,
        "sequence_min_text_similarity": spec.sequence_min_text_similarity,
        "sequence_min_text_similarity_with_visual": spec.sequence_min_text_similarity_with_visual,
        "sequence_visual_support_phash_threshold": spec.sequence_visual_support_phash_threshold,
        "cross_view_text_candidates_enabled": spec.cross_view_text_candidates_enabled,
        "rare_token_candidates_enabled": spec.rare_token_candidates_enabled,
        "rare_token_min_overlap": spec.rare_token_min_overlap,
        "rare_token_min_jaccard": spec.rare_token_min_jaccard,
        "rare_token_max_df": spec.rare_token_max_df,
        "ocr_cap": spec.ocr_cap,
        "ocr_selection_mode": spec.ocr_selection_mode,
        "ocr_reason_quotas": spec.ocr_reason_quotas,
        "openai_ocr_selected": None,
        "openai_ocr_attempted": None,
        "openai_ocr_usable": None,
        "openai_ocr_improved": None,
        "openai_ocr_eligible_skipped": None,
        "embeddings_enabled": spec.embeddings_enabled,
        "embedding_profile": spec.vector_profile,
        "embedding_top_k": spec.embedding_top_k,
        "embedding_min_similarity": spec.embedding_min_similarity,
        "embedding_min_margin": spec.embedding_min_margin,
        "embedding_max_candidates_per_page": spec.embedding_max_candidates_per_page,
        "embedding_max_candidates_per_job": spec.embedding_max_candidates_per_job,
        "embedding_min_text_chars": spec.embedding_min_text_chars,
        "embedding_candidates": None,
        "embedding_calls": None,
        "queue_profile": spec.queue_profile,
        "tesseract_profiles": spec.tesseract_profiles or "default",
        "post_candidate_rescue_pages": spec.post_candidate_rescue_pages,
        "post_candidate_rescue_min_confidence": spec.post_candidate_rescue_min_confidence,
        "embedding_hybrid_scoring": spec.embedding_hybrid_scoring,
        "embedding_hybrid_min_score": spec.embedding_hybrid_min_score,
        "openai_ocr_selection_reason_counts": "{}",
        "false_negative_reason_counts": "{}",
        "strict_recall": None,
        "any_queue_recall": None,
        "main_review_recall": None,
        "main_or_secondary_recall": None,
        "secondary_review_recall": None,
        "ocr_dependent_recall": None,
        "ocr_ready_pair_rate": None,
        "vector_recall_at_5": None,
        "vector_group_recall_at_5": None,
        "true_positives": None,
        "false_negatives": None,
        "known_negative_hits": None,
        "unknown_predictions": None,
        "main_queue_size": None,
        "secondary_queue_size": None,
        "calibration_queue_size": None,
        "low_information_queue_size": None,
        "candidates_per_100_pages": None,
        "runtime_seconds": runtime_seconds,
        "reviewable_score": -9999.0,
        "reused": reused,
        "status": status.get("status", "failed"),
        "error_message": status.get("error_message", ""),
        "exit_code": status.get("exit_code", status.get("returncode")),
    }
    return row


def build_scorecard_row(spec: CalibrationRunSpec, run_dir: Path, runtime_seconds: float | None = None, reused: bool = False) -> dict[str, Any]:
    report = read_json(run_dir / "results.json")
    truth_eval = read_json(run_dir / "truth_eval.json")
    phase_eval = read_json(run_dir / "phase_eval.json")
    fallback = read_json(run_dir / "fallback_audit.json")
    summary = report.get("summary", {})
    eval_summary = truth_eval.get("summary", {})
    review_summary = (phase_eval.get("review_queue_eval") or {}).get("summary", {})
    vector_summary = (phase_eval.get("vector_retrieval_eval") or {}).get("summary", {})
    ocr_summary = (phase_eval.get("ocr_rescue_eval") or {}).get("summary", {})
    fallback_summary = fallback.get("summary", {})
    row = {
        "run_id": spec.run_id,
        "stage": spec.stage,
        "profile_name": spec.profile_name,
        "corpus_id": spec.corpus_id,
        "variant_id": spec.variant_id,
        "dpi": spec.dpi,
        "ocr_evidence_upgrade_enabled": spec.ocr_evidence_upgrade_enabled,
        "strict_tfidf_threshold": spec.strict_tfidf_threshold,
        "standard_tfidf_threshold": spec.standard_tfidf_threshold,
        "loose_tfidf_threshold": spec.loose_tfidf_threshold,
        "multipass_text_top_k": spec.multipass_text_top_k,
        "max_candidates_per_job": spec.max_candidates_per_job,
        "max_candidates_per_page": spec.max_candidates_per_page,
        "main_review_min_confidence": spec.main_review_min_confidence,
        "main_review_max_candidates_per_100_pages": spec.main_review_max_candidates_per_100_pages,
        "openai_ocr_min_candidate_confidence": spec.openai_ocr_min_candidate_confidence,
        "openai_ocr_max_pages_per_document": spec.openai_ocr_max_pages_per_document,
        "sequence_anchor_min_confidence": spec.sequence_anchor_min_confidence,
        "sequence_neighbor_window": spec.sequence_neighbor_window,
        "sequence_min_text_similarity": spec.sequence_min_text_similarity,
        "sequence_min_text_similarity_with_visual": spec.sequence_min_text_similarity_with_visual,
        "sequence_visual_support_phash_threshold": spec.sequence_visual_support_phash_threshold,
        "cross_view_text_candidates_enabled": spec.cross_view_text_candidates_enabled,
        "rare_token_candidates_enabled": spec.rare_token_candidates_enabled,
        "rare_token_min_overlap": spec.rare_token_min_overlap,
        "rare_token_min_jaccard": spec.rare_token_min_jaccard,
        "rare_token_max_df": spec.rare_token_max_df,
        "ocr_cap": spec.ocr_cap,
        "ocr_selection_mode": spec.ocr_selection_mode,
        "ocr_reason_quotas": spec.ocr_reason_quotas,
        "openai_ocr_selected": fallback_summary.get("selected_pages", summary.get("openai_ocr_selected_pages")),
        "openai_ocr_attempted": fallback_summary.get("attempted_pages", summary.get("openai_ocr_attempted_pages")),
        "openai_ocr_usable": fallback_summary.get("usable_pages", summary.get("openai_ocr_usable_pages")),
        "openai_ocr_improved": fallback_summary.get("improved_pages", summary.get("openai_ocr_improved_pages")),
        "openai_ocr_eligible_skipped": fallback_summary.get("eligible_not_selected_pages"),
        "embeddings_enabled": spec.embeddings_enabled,
        "embedding_profile": spec.vector_profile,
        "embedding_top_k": spec.embedding_top_k,
        "embedding_min_similarity": spec.embedding_min_similarity,
        "embedding_min_margin": spec.embedding_min_margin,
        "embedding_max_candidates_per_page": spec.embedding_max_candidates_per_page,
        "embedding_max_candidates_per_job": spec.embedding_max_candidates_per_job,
        "embedding_min_text_chars": spec.embedding_min_text_chars,
        "embedding_candidates": vector_summary.get("vector_candidate_count"),
        "embedding_calls": (summary.get("ai_call_route_counts") or {}).get("text_embedding"),
        "queue_profile": spec.queue_profile,
        "tesseract_profiles": spec.tesseract_profiles or "default",
        "post_candidate_rescue_pages": spec.post_candidate_rescue_pages,
        "post_candidate_rescue_min_confidence": spec.post_candidate_rescue_min_confidence,
        "embedding_hybrid_scoring": spec.embedding_hybrid_scoring,
        "embedding_hybrid_min_score": spec.embedding_hybrid_min_score,
        "embedding_reranker_enabled": spec.embedding_reranker_enabled,
        "embedding_reranker_min_confidence": spec.embedding_reranker_min_confidence,
        "embedding_reranker_ocr_penalty": spec.embedding_reranker_ocr_penalty,
        "embedding_reranker_same_doc_bonus": spec.embedding_reranker_same_doc_bonus,
        "embedding_reranker_tesseract_bonus": spec.embedding_reranker_tesseract_bonus,
        "embedding_reranker_action": spec.embedding_reranker_action,
        "embedding_reranker_evaluated": (summary.get("embedding_reranker") or {}).get("evaluated"),
        "embedding_reranker_demoted": (summary.get("embedding_reranker") or {}).get("demoted"),
        "embedding_reranker_dropped": (summary.get("embedding_reranker") or {}).get("dropped"),
        "openai_ocr_selection_reason_counts": json.dumps(fallback_summary.get("selection_reason_counts", {}), sort_keys=True),
        "false_negative_reason_counts": read_false_negative_reason_counts(run_dir / "false_negatives.csv"),
        "strict_recall": eval_summary.get("recall_on_must_match"),
        "any_queue_recall": review_summary.get("must_match_coverage_any_queue"),
        "main_review_recall": review_summary.get("must_match_coverage_main_review"),
        "main_or_secondary_recall": review_summary.get("must_match_coverage_main_or_secondary"),
        "secondary_review_recall": review_summary.get("must_match_coverage_secondary_review"),
        "ocr_dependent_recall": ((read_json(run_dir / "ocr_validation.json").get("summary") or {}).get("truth_ocr_dependent_recall") if (run_dir / "ocr_validation.json").exists() else None),
        "ocr_ready_pair_rate": ocr_summary.get("ocr_ready_pair_rate"),
        "vector_recall_at_5": (vector_summary.get("recall_at_5") or {}).get("recall"),
        "vector_group_recall_at_5": (vector_summary.get("group_recall_at_5") or {}).get("recall"),
        "true_positives": eval_summary.get("true_positive_count"),
        "false_negatives": eval_summary.get("false_negative_count"),
        "known_negative_hits": eval_summary.get("expected_negative_hit_count"),
        "unknown_predictions": eval_summary.get("unknown_prediction_count"),
        "main_queue_size": review_summary.get("main_review_candidate_count"),
        "secondary_queue_size": review_summary.get("secondary_review_candidate_count"),
        "calibration_queue_size": review_summary.get("calibration_only_candidate_count"),
        "low_information_queue_size": review_summary.get("low_information_candidate_count"),
        "candidates_per_100_pages": safe_div(summary.get("match_count"), summary.get("total_pages"), multiplier=100),
        "runtime_seconds": runtime_seconds,
        "status": "succeeded",
        "error_message": "",
        "exit_code": 0,
        "reused": reused,
    }
    row["reviewable_score"] = rank_score(row)
    return row


def rank_score(row: dict[str, Any]) -> float:
    def f(key: str) -> float:
        value = row.get(key)
        return float(value) if value is not None else 0.0
    # v0.9.9 is explicitly recall-first: false negatives are more costly
    # than extra review candidates. Costs/noise still matter, but they should
    # not cause the recommender to prefer a low-recall no-AI baseline.
    return round(
        260 * f("any_queue_recall")
        + 220 * f("strict_recall")
        + 160 * f("ocr_dependent_recall")
        + 80 * f("main_or_secondary_recall")
        + 40 * f("main_review_recall")
        + 40 * f("vector_group_recall_at_5")
        - 2.0 * f("known_negative_hits")
        - 0.01 * f("main_queue_size")
        - 0.005 * f("secondary_queue_size")
        - 0.002 * f("unknown_predictions")
        - 0.03 * f("openai_ocr_attempted"),
        4,
    )


def build_recommendations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"schema_version": "dupe_engine_calibration_recommendations_v0_10_0", "recommendations": {}}
    generalization = build_generalization_summary(rows)
    return {
        "schema_version": "dupe_engine_calibration_recommendations_v0_10_0",
        "recommendations": {
            "control_v097": first_control_row(rows),
            "best_by_recall_first_score": best_row(rows, "reviewable_score"),
            "best_by_strict_recall": best_row(rows, "strict_recall"),
            "best_by_any_queue_recall": best_row(rows, "any_queue_recall"),
            "best_reviewable_at_or_above_control": best_reviewable_at_or_above_control(rows),
            "best_low_cost": best_low_cost(rows),
            "best_generalized_config": generalization.get("best_generalized_config"),
        },
        "generalization_summary": generalization,
        "notes": "v0.10.0 ranks cross-corpus generalization first. Prefer configs with strong average recall and stable worst-case recall across corpora. Optional LLM analysis is metrics-only by default.",
    }



def build_generalization_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    succeeded = [row for row in rows if row.get("status") == "succeeded"]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in succeeded:
        variant = str(row.get("variant_id") or row.get("run_id") or "default")
        grouped.setdefault(variant, []).append(row)
    variants: list[dict[str, Any]] = []
    for variant, group in grouped.items():
        strict_values = [float(row.get("strict_recall") or 0.0) for row in group]
        ocr_values = [float(row.get("ocr_dependent_recall") or 0.0) for row in group]
        any_values = [float(row.get("any_queue_recall") or 0.0) for row in group]
        known_neg = sum(float(row.get("known_negative_hits") or 0.0) for row in group)
        unknown = sum(float(row.get("unknown_predictions") or 0.0) for row in group)
        main_q = sum(float(row.get("main_queue_size") or 0.0) for row in group)
        secondary_q = sum(float(row.get("secondary_queue_size") or 0.0) for row in group)
        attempted = sum(float(row.get("openai_ocr_attempted") or 0.0) for row in group)
        corpus_results = {
            str(row.get("corpus_id") or "unknown"): {
                "strict_recall": row.get("strict_recall"),
                "any_queue_recall": row.get("any_queue_recall"),
                "ocr_dependent_recall": row.get("ocr_dependent_recall"),
                "true_positives": row.get("true_positives"),
                "false_negatives": row.get("false_negatives"),
                "known_negative_hits": row.get("known_negative_hits"),
                "main_queue_size": row.get("main_queue_size"),
                "secondary_queue_size": row.get("secondary_queue_size"),
            }
            for row in group
        }
        avg_strict = sum(strict_values) / len(strict_values) if strict_values else 0.0
        worst_strict = min(strict_values) if strict_values else 0.0
        avg_any = sum(any_values) / len(any_values) if any_values else 0.0
        avg_ocr = sum(ocr_values) / len(ocr_values) if ocr_values else 0.0
        # Cross-corpus score: reward average recall, but punish worst-case drops.
        score = round(
            260 * avg_strict
            + 220 * worst_strict
            + 160 * avg_any
            + 120 * avg_ocr
            - 2.0 * known_neg
            - 0.004 * (main_q + secondary_q)
            - 0.001 * unknown
            - 0.015 * attempted,
            4,
        )
        example = group[0]
        variants.append(
            {
                "variant_id": variant,
                "run_count": len(group),
                "corpus_count": len(corpus_results),
                "avg_strict_recall": round(avg_strict, 4),
                "worst_strict_recall": round(worst_strict, 4),
                "avg_any_queue_recall": round(avg_any, 4),
                "avg_ocr_dependent_recall": round(avg_ocr, 4),
                "total_known_negative_hits": int(known_neg),
                "total_unknown_predictions": int(unknown),
                "total_main_queue_size": int(main_q),
                "total_secondary_queue_size": int(secondary_q),
                "total_openai_ocr_attempted": int(attempted),
                "generalization_score": score,
                "profile": {
                    "ocr_cap": example.get("ocr_cap"),
                    "ocr_selection_mode": example.get("ocr_selection_mode"),
                    "embedding_profile": example.get("embedding_profile"),
                    "queue_profile": example.get("queue_profile"),
                    "ocr_evidence_upgrade_enabled": example.get("ocr_evidence_upgrade_enabled"),
                    "dpi": example.get("dpi"),
                },
                "corpus_results": corpus_results,
            }
        )
    variants.sort(key=lambda item: float(item.get("generalization_score") or 0.0), reverse=True)
    return {
        "variant_count": len(variants),
        "variants": variants,
        "best_generalized_config": variants[0] if variants else None,
    }


def best_row(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return max(rows, key=lambda row: float(row.get(key) or 0.0), default=None)


def best_low_cost(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    affordable = [row for row in rows if int(row.get("openai_ocr_attempted") or 0) <= 50]
    return best_row(affordable or rows, "reviewable_score")


def first_control_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        if row.get("stage") == "control" or row.get("embedding_profile") == "v097_control":
            return row
    return None


def best_reviewable_at_or_above_control(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    control = first_control_row(rows)
    control_recall = float((control or {}).get("strict_recall") or 0.0)
    candidates = [row for row in rows if float(row.get("strict_recall") or 0.0) >= control_recall]
    return best_row(candidates or rows, "reviewable_score")


def read_false_negative_reason_counts(path: Path) -> str:
    if not path.exists():
        return "{}"
    counts: dict[str, int] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            reason = row.get("reason_missed") or row.get("recommended_next_step") or "unknown"
            counts[reason] = counts.get(reason, 0) + 1
    return json.dumps(counts, sort_keys=True)


def write_scorecard(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = collect_scorecard_fields(rows)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def collect_scorecard_fields(rows: list[dict[str, Any]]) -> list[str]:
    preferred = [
        "run_id",
        "stage",
        "profile_name",
        "corpus_id",
        "variant_id",
        "dpi",
        "ocr_evidence_upgrade_enabled",
        "strict_tfidf_threshold",
        "standard_tfidf_threshold",
        "loose_tfidf_threshold",
        "multipass_text_top_k",
        "max_candidates_per_job",
        "max_candidates_per_page",
        "main_review_min_confidence",
        "main_review_max_candidates_per_100_pages",
        "openai_ocr_min_candidate_confidence",
        "openai_ocr_max_pages_per_document",
        "sequence_anchor_min_confidence",
        "sequence_neighbor_window",
        "sequence_min_text_similarity",
        "sequence_min_text_similarity_with_visual",
        "sequence_visual_support_phash_threshold",
        "ocr_cap",
        "ocr_selection_mode",
        "ocr_reason_quotas",
        "openai_ocr_selected",
        "openai_ocr_attempted",
        "openai_ocr_usable",
        "openai_ocr_improved",
        "openai_ocr_eligible_skipped",
        "embeddings_enabled",
        "embedding_profile",
        "embedding_top_k",
        "embedding_min_similarity",
        "embedding_min_margin",
        "embedding_max_candidates_per_page",
        "embedding_max_candidates_per_job",
        "embedding_min_text_chars",
        "embedding_candidates",
        "embedding_calls",
        "queue_profile",
        "tesseract_profiles",
        "post_candidate_rescue_pages",
        "post_candidate_rescue_min_confidence",
        "embedding_hybrid_scoring",
        "embedding_hybrid_min_score",
        "openai_ocr_selection_reason_counts",
        "false_negative_reason_counts",
        "strict_recall",
        "any_queue_recall",
        "main_review_recall",
        "main_or_secondary_recall",
        "secondary_review_recall",
        "ocr_dependent_recall",
        "ocr_ready_pair_rate",
        "vector_recall_at_5",
        "vector_group_recall_at_5",
        "true_positives",
        "false_negatives",
        "known_negative_hits",
        "unknown_predictions",
        "main_queue_size",
        "secondary_queue_size",
        "calibration_queue_size",
        "low_information_queue_size",
        "candidates_per_100_pages",
        "runtime_seconds",
        "status",
        "error_message",
        "exit_code",
        "reviewable_score",
        "reused",
    ]
    extras = sorted({key for row in rows for key in row if key not in preferred})
    return preferred + extras


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def safe_div(value: Any, denominator: Any, multiplier: float = 1.0) -> float | None:
    try:
        if value is None or denominator in {None, 0}:
            return None
        return round(float(value) * multiplier / float(denominator), 4)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_")[:40]
