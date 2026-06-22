"""
Healing harness: diagnose → prescribe → (optionally) heal → compare → certify.

Unlike the calibration loop (which searches the parameter space), this takes a
completed run that underperformed, identifies the specific failure modes in that
run, and prescribes the minimal config change to address them.

Feedback format (--feedback JSON):
  {
    "version": "1",
    "feedback_pairs": [
      {
        "doc_a": "Smith_John_001.pdf",
        "page_a": 3,
        "doc_b": "Smith_John_002.pdf",
        "page_b": 1,
        "verdict": "missed_duplicate",   // or "false_alarm"
        "notes": "same lab result, different header date"
      }
    ]
  }
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class HealAssessment:
    run_dir: Path
    health_score: float  # 0–100
    has_truth: bool
    has_feedback: bool
    recall: float | None = None
    precision: float | None = None
    fn_count: int = 0
    fp_count: int = 0
    total_pages: int = 0
    candidate_count: int = 0
    main_review_count: int = 0
    queue_per_100_pages: float | None = None
    ocr_selected_pages: int = 0
    ocr_coverage_pct: float | None = None
    embeddings_enabled: bool = False
    reranker_enabled: bool = False
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealIssue:
    root_cause: str
    count: int
    confidence: str  # high | medium | low
    detail: str


@dataclass
class HealDiagnosis:
    assessment: HealAssessment
    issues: list[HealIssue]
    fn_rows: list[dict[str, Any]]


@dataclass
class HealPrescription:
    diagnosis: HealDiagnosis
    issues_addressed: list[str]
    config_delta: dict[str, Any]
    cli_args: list[str]
    expected_recall_delta: float | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class HealComparison:
    before: HealAssessment
    after: HealAssessment
    recall_delta: float | None
    precision_delta: float | None
    queue_delta: float | None
    health_delta: float


@dataclass
class HealCertification:
    status: str  # HEALED | IMPROVED | RESISTANT
    comparison: HealComparison
    residual_issues: list[HealIssue]
    message: str


# ---------------------------------------------------------------------------
# Phase 1: Assess
# ---------------------------------------------------------------------------

def assess_run(
    run_dir: Path,
    truth_eval_path: Path | None = None,
    feedback_pairs: list[dict[str, Any]] | None = None,
) -> HealAssessment:
    results_path = run_dir / "results.json"
    if not results_path.exists():
        raise FileNotFoundError(f"No results.json in {run_dir} — is this a valid run directory?")

    results = _read_json(results_path)
    summary = results.get("summary", {})
    capabilities = results.get("capabilities", {})

    total_pages = int(summary.get("total_pages") or 0)
    candidate_count = int(summary.get("candidate_count") or 0)
    main_review_count = int(summary.get("main_review_list_candidate_count") or 0)
    ocr_selected = int(summary.get("openai_ocr_selected_pages") or 0)
    embeddings_enabled = bool(capabilities.get("embeddings", {}).get("used"))
    reranker_info = summary.get("embedding_reranker", {})
    reranker_enabled = bool(reranker_info.get("enabled")) and int(reranker_info.get("evaluated") or 0) > 0

    queue_per_100 = round(main_review_count / total_pages * 100, 1) if total_pages else None
    ocr_coverage = round(ocr_selected / total_pages * 100, 1) if total_pages else None

    recall: float | None = None
    precision: float | None = None
    fn_count = 0
    fp_count = 0
    has_truth = False

    if truth_eval_path and truth_eval_path.exists():
        has_truth = True
        truth_eval = _read_json(truth_eval_path)
        ev = truth_eval.get("summary", {})
        recall_raw = ev.get("recall")
        precision_raw = ev.get("precision")
        recall = float(recall_raw) if recall_raw is not None else None
        precision = float(precision_raw) if precision_raw is not None else None
        fn_count = int(ev.get("false_negative_count") or 0)
        fp_count = int(ev.get("false_positive_count") or 0)

    has_feedback = bool(feedback_pairs)
    if has_feedback and not has_truth:
        fn_count = sum(1 for p in feedback_pairs if p.get("verdict") == "missed_duplicate")
        fp_count = sum(1 for p in feedback_pairs if p.get("verdict") == "false_alarm")

    score = _compute_health_score(
        recall=recall,
        precision=precision,
        queue_per_100=queue_per_100,
        ocr_coverage=ocr_coverage,
        fn_count=fn_count,
        total_pages=total_pages,
    )

    return HealAssessment(
        run_dir=run_dir,
        health_score=score,
        has_truth=has_truth,
        has_feedback=has_feedback,
        recall=recall,
        precision=precision,
        fn_count=fn_count,
        fp_count=fp_count,
        total_pages=total_pages,
        candidate_count=candidate_count,
        main_review_count=main_review_count,
        queue_per_100_pages=queue_per_100,
        ocr_selected_pages=ocr_selected,
        ocr_coverage_pct=ocr_coverage,
        embeddings_enabled=embeddings_enabled,
        reranker_enabled=reranker_enabled,
        summary=summary,
    )


def _compute_health_score(
    recall: float | None,
    precision: float | None,
    queue_per_100: float | None,
    ocr_coverage: float | None,
    fn_count: int,
    total_pages: int,
) -> float:
    components: list[tuple[float, float]] = []

    if recall is not None:
        components.append((recall, 40.0))
    if precision is not None:
        components.append((precision, 20.0))
    if queue_per_100 is not None:
        qscore = max(0.0, 1.0 - max(0.0, queue_per_100 - 30) / 70.0)
        components.append((qscore, 15.0))
    if ocr_coverage is not None:
        components.append((min(1.0, ocr_coverage / 100.0), 15.0))
    if fn_count > 0 and recall is None and total_pages > 0:
        fn_rate = fn_count / max(1, total_pages)
        components.append((max(0.0, 1.0 - fn_rate * 5), 25.0))

    if not components:
        return 50.0

    total_weight = sum(w for _, w in components)
    weighted_sum = sum(s * w for s, w in components)
    return round(weighted_sum / total_weight * 100, 1)


# ---------------------------------------------------------------------------
# Phase 2: Diagnose
# ---------------------------------------------------------------------------

def diagnose_run(
    assessment: HealAssessment,
    feedback_pairs: list[dict[str, Any]] | None = None,
) -> HealDiagnosis:
    issue_counts: dict[str, int] = {}
    fn_rows: list[dict[str, Any]] = []

    # Read pre-classified FN rows from CSV (written at eval time with page-level data)
    fn_csv = assessment.run_dir / "false_negatives.csv"
    if fn_csv.exists():
        with open(fn_csv, newline="") as f:
            for row in csv.DictReader(f):
                reason = row.get("reason_missed") or "deterministic_threshold_or_candidate_generation_miss"
                row["_heal_root_cause"] = reason
                fn_rows.append(row)
                issue_counts[reason] = issue_counts.get(reason, 0) + 1
    elif assessment.has_truth and assessment.fn_count > 0:
        # Truth eval shows FNs but CSV wasn't written — can't classify without page records
        issue_counts["deterministic_threshold_or_candidate_generation_miss"] = assessment.fn_count

    # Feedback-reported missed pairs (user-supplied, no page-level data)
    feedback_missed = sum(1 for p in (feedback_pairs or []) if p.get("verdict") == "missed_duplicate")
    if feedback_missed:
        issue_counts["user_reported_missed"] = issue_counts.get("user_reported_missed", 0) + feedback_missed

    # Queue health (no truth required)
    if assessment.queue_per_100_pages is not None and assessment.queue_per_100_pages > 50:
        issue_counts["queue_overload"] = issue_counts.get("queue_overload", 0) + int(assessment.queue_per_100_pages - 50)

    if assessment.ocr_coverage_pct is not None and assessment.ocr_coverage_pct < 50 and assessment.total_pages > 0:
        issue_counts["low_ocr_coverage"] = 1

    if not assessment.embeddings_enabled and assessment.fn_count > 3:
        issue_counts["embeddings_not_enabled"] = assessment.fn_count

    issues = _rank_issues(issue_counts, assessment)
    return HealDiagnosis(assessment=assessment, issues=issues, fn_rows=fn_rows)


def _rank_issues(issue_counts: dict[str, int], assessment: HealAssessment) -> list[HealIssue]:
    issues: list[HealIssue] = []
    for cause, count in sorted(issue_counts.items(), key=lambda kv: -kv[1]):
        confidence = "high" if count >= 3 else "medium" if count >= 1 else "low"
        detail = _issue_detail(cause, count, assessment)
        issues.append(HealIssue(root_cause=cause, count=count, confidence=confidence, detail=detail))
    return issues


def _issue_detail(cause: str, count: int, a: HealAssessment) -> str:
    m = {
        "fallback_not_selected": f"{count} FN pair(s) had pages that qualified for vision OCR rescue but hit the cap or were skipped by selection mode",
        "fallback_selected_but_still_weak": f"{count} FN pair(s) were selected for OCR but extracted text remained too weak to match",
        "low_information_suppressed_or_template": f"{count} FN pair(s) are on low-information pages (covers, blanks, templates) — engine suppressed them",
        "semantic_or_adjudication_layer_miss": f"{count} FN pair(s) require semantic/embedding matching that isn't active",
        "ocr_or_vision_layer_miss": f"{count} FN pair(s) have poor OCR quality — Tesseract alone wasn't sufficient",
        "deterministic_threshold_or_candidate_generation_miss": f"{count} FN pair(s) were below deterministic thresholds or not generated as candidates",
        "truth_identity_or_ingest_mismatch": f"{count} FN pair(s) couldn't be matched to page records — check document naming in truth file",
        "queue_overload": f"Queue at {a.queue_per_100_pages or 0:.0f}/100 pages (target ≤50) — reviewer workload is too high",
        "low_ocr_coverage": f"Only {a.ocr_coverage_pct or 0:.0f}% of pages had vision OCR applied",
        "embeddings_not_enabled": f"{count} missed pairs may benefit from semantic embedding matching (currently disabled)",
        "user_reported_missed": f"{count} pair(s) reported as missed by reviewer — no page-level data available for root-cause classification",
    }
    return m.get(cause, f"{count} occurrence(s) of {cause}")


# ---------------------------------------------------------------------------
# Phase 4: Heal (re-run with prescription)
# ---------------------------------------------------------------------------

def apply_heal(
    prescription: HealPrescription,
    pdf_dir: Path,
    out_dir: Path,
    truth_path: Path | None = None,
    *,
    verbose: bool = False,
) -> Path:
    healed_run_dir = out_dir / "healed"
    healed_run_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "dupe_engine.cli", "eval-all",
        str(pdf_dir),
        "--out", str(healed_run_dir / "results.json"),
        "--run-dir", str(healed_run_dir),
        "--fallback-audit-out", str(healed_run_dir / "fallback_audit.json"),
        "--ocr-validation-out", str(healed_run_dir / "ocr_validation.json"),
        "--ocr", "--openai-ocr", "--openai-ocr-live", "--require-ocr", "--require-openai-ocr",
    ]

    if truth_path and truth_path.exists():
        cmd += [
            "--truth", str(truth_path),
            "--eval-out", str(healed_run_dir / "truth_eval.json"),
            "--false-negative-csv", str(healed_run_dir / "false_negatives.csv"),
            "--false-positive-csv", str(healed_run_dir / "false_positive_review.csv"),
        ]

    cmd += prescription.cli_args

    _write_json(healed_run_dir / "heal_prescription.json", _prescription_to_dict(prescription))

    if verbose:
        print(f"[heal] Command: {' '.join(cmd)}")

    t0 = time.monotonic()
    result = subprocess.run(cmd, capture_output=not verbose)
    elapsed = time.monotonic() - t0

    status = "succeeded" if result.returncode == 0 else "failed"
    _write_json(healed_run_dir / "heal_run_status.json", {
        "status": status,
        "exit_code": result.returncode,
        "runtime_seconds": round(elapsed, 1),
    })

    if result.returncode != 0:
        tail = result.stderr.decode("utf-8", errors="replace")[-2000:] if result.stderr else ""
        raise RuntimeError(f"Healed re-run failed (exit {result.returncode}):\n{tail}")

    return healed_run_dir


# ---------------------------------------------------------------------------
# Phase 5: Compare
# ---------------------------------------------------------------------------

def compare_runs(before: HealAssessment, after: HealAssessment) -> HealComparison:
    recall_delta = None
    if before.recall is not None and after.recall is not None:
        recall_delta = round(after.recall - before.recall, 4)
    precision_delta = None
    if before.precision is not None and after.precision is not None:
        precision_delta = round(after.precision - before.precision, 4)
    queue_delta = None
    if before.queue_per_100_pages is not None and after.queue_per_100_pages is not None:
        queue_delta = round(after.queue_per_100_pages - before.queue_per_100_pages, 1)

    return HealComparison(
        before=before,
        after=after,
        recall_delta=recall_delta,
        precision_delta=precision_delta,
        queue_delta=queue_delta,
        health_delta=round(after.health_score - before.health_score, 1),
    )


# ---------------------------------------------------------------------------
# Phase 6: Certify
# ---------------------------------------------------------------------------

def certify(
    comparison: HealComparison,
    target_recall: float | None = None,
    target_queue_size: float | None = None,
) -> HealCertification:
    after = comparison.after
    residual: list[HealIssue] = []

    if target_recall is not None and after.recall is not None and after.recall < target_recall:
        residual.append(HealIssue(
            root_cause="recall_below_target",
            count=1,
            confidence="high",
            detail=f"Recall {after.recall:.1%} still below target {target_recall:.1%}",
        ))

    if target_queue_size is not None and after.queue_per_100_pages is not None and after.queue_per_100_pages > target_queue_size:
        residual.append(HealIssue(
            root_cause="queue_above_target",
            count=1,
            confidence="high",
            detail=f"Queue {after.queue_per_100_pages:.0f}/100 pages above target {target_queue_size:.0f}",
        ))

    has_targets = target_recall is not None or target_queue_size is not None
    improved = comparison.health_delta > 0

    if has_targets and not residual:
        status = "HEALED"
        message = f"All targets met. Health +{comparison.health_delta:+.1f} pts."
    elif improved:
        status = "IMPROVED"
        parts = [f"Health {comparison.health_delta:+.1f} pts."]
        if comparison.recall_delta is not None:
            parts.append(f"Recall {comparison.recall_delta:+.1%}.")
        if residual:
            parts.append(f"{len(residual)} target(s) not yet met.")
        message = " ".join(parts)
    else:
        status = "RESISTANT"
        message = f"No improvement (health delta: {comparison.health_delta:+.1f} pts). Manual investigation recommended."

    return HealCertification(
        status=status,
        comparison=comparison,
        residual_issues=residual,
        message=message,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_heal(args: Any) -> None:
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        raise SystemExit(f"--run-dir not found: {run_dir}")

    truth_path = Path(args.truth) if getattr(args, "truth", None) else None
    if truth_path and not truth_path.exists():
        raise SystemExit(f"--truth not found: {truth_path}")

    feedback_pairs: list[dict[str, Any]] = []
    if getattr(args, "feedback", None):
        fb_path = Path(args.feedback)
        if not fb_path.exists():
            raise SystemExit(f"--feedback not found: {fb_path}")
        feedback_data = _read_json(fb_path)
        feedback_pairs = feedback_data.get("feedback_pairs", [])
        if not feedback_pairs:
            print("[heal] Warning: --feedback file has no feedback_pairs entries")

    apply = getattr(args, "apply", False)
    iterations = max(1, getattr(args, "iterations", 1))
    pdf_dir = Path(args.pdf_dir) if getattr(args, "pdf_dir", None) else None
    verbose = getattr(args, "verbose", False)
    target_recall = getattr(args, "target_recall", None)
    target_queue_size = getattr(args, "target_queue_size", None)
    out_dir = Path(args.out_dir) if getattr(args, "out_dir", None) else run_dir / "heal_output"

    truth_eval_path = run_dir / "truth_eval.json"

    print(f"\n[heal] Assessing: {run_dir}")
    assessment = assess_run(run_dir, truth_eval_path if truth_eval_path.exists() else None, feedback_pairs)
    _print_assessment(assessment)

    print(f"\n[heal] Diagnosing failure modes...")
    diagnosis = diagnose_run(assessment, feedback_pairs=feedback_pairs)
    _print_diagnosis(diagnosis)

    print(f"\n[heal] Building prescription...")
    from .heal_prescriber import build_prescription
    prescription = build_prescription(diagnosis)
    _print_prescription(prescription)

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "prescription.json", _prescription_to_dict(prescription))
    print(f"[heal] Prescription saved → {out_dir / 'prescription.json'}")

    if not apply:
        print(f"\n[heal] Done. Add --apply --pdf-dir <path> to re-run with this prescription.")
        return

    if not pdf_dir:
        raise SystemExit("--pdf-dir is required with --apply")
    if not pdf_dir.exists():
        raise SystemExit(f"--pdf-dir not found: {pdf_dir}")

    current_run_dir = run_dir
    current_assessment = assessment

    for i in range(iterations):
        cycle_label = f"cycle {i + 1}/{iterations}" if iterations > 1 else "heal"
        print(f"\n[heal] Running {cycle_label}...")

        cycle_out = out_dir / f"cycle_{i + 1}" if iterations > 1 else out_dir
        cycle_truth_eval = current_run_dir / "truth_eval.json"
        cycle_assessment = assess_run(
            current_run_dir,
            cycle_truth_eval if cycle_truth_eval.exists() else None,
            feedback_pairs,
        )
        cycle_diagnosis = diagnose_run(cycle_assessment, feedback_pairs=feedback_pairs)
        cycle_prescription = build_prescription(cycle_diagnosis)

        if not cycle_prescription.cli_args:
            print(f"[heal] No actionable prescription — stopping after {i} cycle(s).")
            break

        healed_run_dir = apply_heal(
            cycle_prescription,
            pdf_dir=pdf_dir,
            out_dir=cycle_out,
            truth_path=truth_path,
            verbose=verbose,
        )

        healed_truth_eval = healed_run_dir / "truth_eval.json"
        healed_assessment = assess_run(
            healed_run_dir,
            healed_truth_eval if healed_truth_eval.exists() else None,
            feedback_pairs,
        )

        comparison = compare_runs(current_assessment, healed_assessment)
        certification = certify(comparison, target_recall=target_recall, target_queue_size=target_queue_size)

        _print_comparison(comparison)
        print(f"\n[heal] {certification.status} — {certification.message}")

        _write_json(cycle_out / "heal_report.json", _certification_to_dict(certification))
        print(f"[heal] Report → {cycle_out / 'heal_report.json'}")

        if certification.status in {"HEALED", "RESISTANT"}:
            break

        current_run_dir = healed_run_dir
        current_assessment = healed_assessment


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def _print_assessment(a: HealAssessment) -> None:
    print(f"  Health score:  {a.health_score:.0f}/100")
    if a.recall is not None:
        print(f"  Recall:        {a.recall:.1%}   FN: {a.fn_count}")
    if a.precision is not None:
        print(f"  Precision:     {a.precision:.1%}   FP: {a.fp_count}")
    if a.queue_per_100_pages is not None:
        print(f"  Queue:         {a.main_review_count} candidates  ({a.queue_per_100_pages:.0f}/100 pages)")
    if a.ocr_coverage_pct is not None:
        print(f"  OCR coverage:  {a.ocr_coverage_pct:.0f}%  ({a.ocr_selected_pages}/{a.total_pages} pages)")
    print(f"  Embeddings:    {'on' if a.embeddings_enabled else 'off'}   Reranker: {'on' if a.reranker_enabled else 'off'}")


def _print_diagnosis(d: HealDiagnosis) -> None:
    if not d.issues:
        print("  No issues detected.")
        return
    for issue in d.issues[:6]:
        flag = "!" if issue.confidence == "high" else "~"
        print(f"  [{flag}] {issue.root_cause}  ×{issue.count}")
        print(f"       {issue.detail}")


def _print_prescription(p: HealPrescription) -> None:
    if not p.cli_args:
        print("  No actionable prescription found.")
        return
    for cause in p.issues_addressed:
        print(f"  → {cause}")
    print(f"  Flags: {' '.join(p.cli_args)}")
    if p.expected_recall_delta is not None and p.diagnosis.assessment.recall is not None:
        est = p.diagnosis.assessment.recall + p.expected_recall_delta
        print(f"  Est. recall after heal: {est:.1%} (±10pp; conservative estimate from {p.expected_recall_delta:+.1%})")
    for note in p.notes:
        print(f"  Note: {note}")


def _print_comparison(c: HealComparison) -> None:
    print(f"  Health:    {c.before.health_score:.0f} → {c.after.health_score:.0f}  ({c.health_delta:+.1f})")
    if c.recall_delta is not None:
        print(f"  Recall:    {c.before.recall:.1%} → {c.after.recall:.1%}  ({c.recall_delta:+.1%})")
    if c.precision_delta is not None:
        print(f"  Precision: {c.before.precision:.1%} → {c.after.precision:.1%}  ({c.precision_delta:+.1%})")
    if c.queue_delta is not None:
        print(f"  Queue:     {c.before.queue_per_100_pages:.0f} → {c.after.queue_per_100_pages:.0f}/100 pages  ({c.queue_delta:+.1f})")


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def _prescription_to_dict(p: HealPrescription) -> dict[str, Any]:
    return {
        "issues_addressed": p.issues_addressed,
        "config_delta": p.config_delta,
        "cli_args": p.cli_args,
        "expected_recall_delta": p.expected_recall_delta,
        "notes": p.notes,
        "diagnosis_issues": [
            {"root_cause": i.root_cause, "count": i.count, "confidence": i.confidence, "detail": i.detail}
            for i in p.diagnosis.issues
        ],
    }


def _certification_to_dict(c: HealCertification) -> dict[str, Any]:
    return {
        "status": c.status,
        "message": c.message,
        "residual_issues": [
            {"root_cause": i.root_cause, "count": i.count, "detail": i.detail}
            for i in c.residual_issues
        ],
        "comparison": {
            "health_before": c.comparison.before.health_score,
            "health_after": c.comparison.after.health_score,
            "health_delta": c.comparison.health_delta,
            "recall_before": c.comparison.before.recall,
            "recall_after": c.comparison.after.recall,
            "recall_delta": c.comparison.recall_delta,
            "precision_before": c.comparison.before.precision,
            "precision_after": c.comparison.after.precision,
            "precision_delta": c.comparison.precision_delta,
            "queue_per_100_before": c.comparison.before.queue_per_100_pages,
            "queue_per_100_after": c.comparison.after.queue_per_100_pages,
            "queue_delta": c.comparison.queue_delta,
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
