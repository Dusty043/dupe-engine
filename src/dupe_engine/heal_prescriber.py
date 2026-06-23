"""
Prescription engine: maps ranked HealDiagnosis issues to concrete CLI flag changes.

Each _prescribe_* function returns (cli_flags, config_delta, note) or None.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .healing_harness import HealAssessment, HealDiagnosis, HealIssue, HealPrescription


def build_prescription(diagnosis: "HealDiagnosis") -> "HealPrescription":
    from .healing_harness import HealPrescription

    issues = diagnosis.issues
    assessment = diagnosis.assessment

    cli_args: list[str] = []
    config_delta: dict[str, Any] = {}
    issues_addressed: list[str] = []
    notes: list[str] = []

    handlers: dict[str, Any] = {
        "fallback_not_selected": _prescribe_ocr_cap,
        "fallback_selected_but_still_weak": _prescribe_ocr_quality,
        "low_information_suppressed_or_template": _prescribe_low_info,
        "semantic_or_adjudication_layer_miss": _prescribe_embeddings,
        "ocr_or_vision_layer_miss": _prescribe_ocr_quality,
        "deterministic_threshold_or_candidate_generation_miss": _prescribe_thresholds,
        "truth_identity_or_ingest_mismatch": _prescribe_identity,
        "queue_overload": _prescribe_queue,
        "low_ocr_coverage": _prescribe_ocr_cap,
        "embeddings_not_enabled": _prescribe_embeddings,
        "user_reported_missed": _prescribe_general_recall,
    }

    for issue in issues:
        handler = handlers.get(issue.root_cause)
        if handler is None:
            continue
        result = handler(issue, assessment)
        if result is None:
            continue
        new_flags, delta, note = result
        _merge_flags(cli_args, new_flags)
        config_delta.update(delta)
        if note:
            notes.append(note)
        issues_addressed.append(issue.root_cause)

    # Conservative recall-delta estimate: assume 60% of addressed FN causes convert
    recall_issues = {
        "fallback_not_selected", "semantic_or_adjudication_layer_miss",
        "ocr_or_vision_layer_miss", "deterministic_threshold_or_candidate_generation_miss",
        "user_reported_missed",
    }
    fn_addressed = sum(i.count for i in issues if i.root_cause in recall_issues and i.root_cause in issues_addressed)
    total_fn = assessment.fn_count or max(1, fn_addressed)
    expected_recall_delta = round(fn_addressed / total_fn * 0.6, 3) if fn_addressed else None

    return HealPrescription(
        diagnosis=diagnosis,
        issues_addressed=issues_addressed,
        config_delta=config_delta,
        cli_args=cli_args,
        expected_recall_delta=expected_recall_delta,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Flag merging
# ---------------------------------------------------------------------------

def _merge_flags(cli_args: list[str], new_flags: list[str]) -> None:
    """Merge new_flags into cli_args, skipping flag+value pairs whose flag name
    already appears. Operates on (--flag [value]) pairs so a shared numeric
    value like '7' in '--top-k 7' doesn't mistakenly block '--max-pages 7'."""
    existing = {f for f in cli_args if f.startswith("--")}
    i = 0
    while i < len(new_flags):
        token = new_flags[i]
        if token.startswith("--"):
            has_value = (i + 1 < len(new_flags) and not new_flags[i + 1].startswith("--"))
            if token not in existing:
                existing.add(token)
                cli_args.append(token)
                if has_value:
                    cli_args.append(new_flags[i + 1])
            i += 2 if has_value else 1
        else:
            # Bare positional (shouldn't appear in practice, keep anyway)
            if token not in cli_args:
                cli_args.append(token)
            i += 1


# ---------------------------------------------------------------------------
# Individual prescribers
# Returns (cli_flags, config_delta, note | None) or None
# ---------------------------------------------------------------------------

def _prescribe_ocr_cap(
    issue: "HealIssue",
    assessment: "HealAssessment",
) -> tuple[list[str], dict[str, Any], str | None] | None:
    summary = assessment.summary
    current_cap = int(summary.get("openai_ocr_max_pages_per_job") or 50)
    new_cap = min(max(current_cap + 25, int(current_cap * 1.5)), 300)
    if new_cap <= current_cap:
        return None

    flags = ["--openai-ocr-max-pages", str(new_cap)]
    delta: dict[str, Any] = {
        "openai_ocr_max_pages_per_job": {"before": current_cap, "after": new_cap, "reason": issue.root_cause},
    }

    current_per_doc = int(summary.get("openai_ocr_max_pages_per_document") or 5)
    new_per_doc = min(current_per_doc + 2, 10)
    if new_per_doc > current_per_doc:
        flags += ["--openai-ocr-max-pages-per-document", str(new_per_doc)]
        delta["openai_ocr_max_pages_per_document"] = {
            "before": current_per_doc, "after": new_per_doc,
            "reason": "increase per-document OCR coverage",
        }

    return flags, delta, None


def _prescribe_ocr_quality(
    issue: "HealIssue",
    assessment: "HealAssessment",
) -> tuple[list[str], dict[str, Any], str | None] | None:
    flags: list[str] = [
        "--openai-ocr-evidence-upgrade",
        "--openai-ocr-combine-evidence",
        "--openai-ocr-post-candidate-rescue",
        "--openai-ocr-post-candidate-rescue-pages", "3",
        "--openai-ocr-post-candidate-min-confidence", "0.45",
    ]
    delta: dict[str, Any] = {
        "ocr_evidence_upgrade": {"before": False, "after": True, "reason": "upgrade weak OCR evidence"},
        "post_candidate_rescue": {"before": False, "after": True, "reason": issue.root_cause},
    }
    return flags, delta, None


def _prescribe_low_info(
    issue: "HealIssue",
    assessment: "HealAssessment",
) -> tuple[list[str], dict[str, Any], str | None] | None:
    flags = ["--loose-tfidf-threshold", "0.68"]
    delta: dict[str, Any] = {
        "loose_tfidf_threshold": {"before": 0.74, "after": 0.68, "reason": "catch near-identical low-info pages"},
    }
    note = (
        "Low-information pages are suppressed by design to prevent FP explosion. "
        "Loosening TF-IDF marginally — monitor false positive rate after this change."
    )
    return flags, delta, note


def _prescribe_embeddings(
    issue: "HealIssue",
    assessment: "HealAssessment",
) -> tuple[list[str], dict[str, Any], str | None] | None:
    if assessment.embeddings_enabled:
        flags = [
            "--embedding-top-k", "10",
            "--embedding-similarity-threshold", "0.82",
            "--embedding-min-margin", "0.02",
        ]
        delta: dict[str, Any] = {
            "embedding_top_k": {"before": 5, "after": 10, "reason": "expand vector neighborhood"},
            "embedding_min_similarity": {"before": 0.85, "after": 0.82, "reason": "capture more semantic neighbors"},
        }
    else:
        flags = [
            "--embeddings",
            "--embedding-top-k", "10",
            "--embedding-similarity-threshold", "0.82",
            "--embedding-min-margin", "0.02",
            "--embedding-max-candidates-per-page", "2",
            "--embedding-max-candidates-per-job", "500",
            "--embedding-min-text-chars", "120",
        ]
        delta = {
            "embeddings_enabled": {"before": False, "after": True, "reason": issue.root_cause},
            "vector_profile": {"before": "off", "after": "recall_first", "reason": "enable semantic matching"},
        }
    return flags, delta, None


def _prescribe_thresholds(
    issue: "HealIssue",
    assessment: "HealAssessment",
) -> tuple[list[str], dict[str, Any], str | None] | None:
    flags: list[str] = ["--loose-tfidf-threshold", "0.68", "--tfidf-top-k", "7"]
    delta: dict[str, Any] = {
        "loose_tfidf_threshold": {"before": 0.74, "after": 0.68, "reason": issue.root_cause},
        "tfidf_top_k": {"before": 5, "after": 7, "reason": "expand text candidate set"},
    }
    if issue.count >= 3:
        flags += [
            "--openai-ocr-post-candidate-rescue",
            "--openai-ocr-post-candidate-rescue-pages", "2",
            "--openai-ocr-post-candidate-min-confidence", "0.50",
        ]
        delta["post_candidate_rescue"] = {
            "before": False, "after": True,
            "reason": "add rescue pass for borderline candidates",
        }
    return flags, delta, None


def _prescribe_identity(
    issue: "HealIssue",
    assessment: "HealAssessment",
) -> tuple[list[str], dict[str, Any], str | None] | None:
    note = (
        f"{issue.count} FN pair(s) couldn't be matched to page records — "
        "verify that document filenames in the truth file exactly match the PDF filenames used in this run."
    )
    return [], {}, note


def _prescribe_queue(
    issue: "HealIssue",
    assessment: "HealAssessment",
) -> tuple[list[str], dict[str, Any], str | None] | None:
    if not assessment.reranker_enabled:
        flags: list[str] = ["--embedding-reranker", "--embedding-reranker-action", "demote"]
        delta: dict[str, Any] = {
            "embedding_reranker_enabled": {"before": False, "after": True, "reason": "reduce queue via reranker demotion"},
        }
    else:
        flags = ["--embedding-reranker", "--embedding-reranker-action", "drop"]
        delta = {
            "embedding_reranker_action": {"before": "demote", "after": "drop", "reason": "queue still large — escalate to drop"},
        }
    return flags, delta, None


def _prescribe_general_recall(
    issue: "HealIssue",
    assessment: "HealAssessment",
) -> tuple[list[str], dict[str, Any], str | None] | None:
    flags: list[str] = ["--loose-tfidf-threshold", "0.68", "--tfidf-top-k", "7"]
    delta: dict[str, Any] = {
        "loose_tfidf_threshold": {"before": 0.74, "after": 0.68, "reason": "user-reported missed pairs"},
        "tfidf_top_k": {"before": 5, "after": 7, "reason": "expand candidate set"},
    }
    if not assessment.embeddings_enabled:
        emb_flags, emb_delta, _ = _prescribe_embeddings(issue, assessment)
        flags += emb_flags
        delta.update(emb_delta)
    return flags, delta, "Prescription based on user-reported feedback only — page-level data unavailable."
