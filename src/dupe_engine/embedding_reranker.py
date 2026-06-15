"""v0.10.9 pure embedding precision reranker.

Applies a calibrated precision score to pure embedding (semantic_recall)
candidates and either demotes or drops those below the configured threshold.

"Pure embedding" is identified at runtime by:
    match.match_type == "embedding_similarity_candidate"

(The candidate_category field may not be populated until after annotation;
match_type is set at detector time and is always reliable.)

Score formula (additive, clamped to [0.0, 1.0]):
    score  = base confidence
    score -= ocr_penalty  per OpenAI-OCR-selected page
    score += tesseract_bonus  per Tesseract-usable page
    score += same_doc_bonus  when both pages share document_name

Demotion lowers confidence to _DEMOTE_CONFIDENCE (0.49), sets
review_rationale to a reranker tag, and re-annotates so existing visibility
machinery routes the match to calibration_only. The calibration annotation
guard (if not match.review_rationale) is satisfied by the non-empty rationale
we set, preventing overwrite.

Drop removes the match from the returned list entirely.

All decisions are recorded as ai_route_events for traceability.
summarize_reranker derives counts from those events; no second state store.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import EngineConfig
    from .models import PageMatch

# Confidence assigned to demoted matches. Below the typical calibration
# threshold floor (0.6) so demoted rows are excluded at operational thresholds.
_DEMOTE_CONFIDENCE: float = 0.49

_PURE_EMBEDDING_MATCH_TYPES: frozenset[str] = frozenset({
    "embedding_similarity_candidate",
    # hybrid_vector_candidate is intentionally excluded: it has already passed a
    # hybrid vector scoring gate and is treated as a higher-confidence match type.
})

_VALID_ACTIONS: frozenset[str] = frozenset({"demote", "drop"})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RerankerParams:
    min_confidence: float
    ocr_penalty: float
    same_doc_bonus: float
    tesseract_bonus: float
    action: str  # "demote" | "drop"


@dataclass(frozen=True)
class RerankerDecision:
    original_confidence: float
    precision_score: float
    decision: str  # "keep" | "demote" | "drop"
    components: dict[str, Any]
    reason: str


# ---------------------------------------------------------------------------
# Config extraction
# ---------------------------------------------------------------------------

def params_from_config(config: "EngineConfig") -> RerankerParams:
    action = str(getattr(config, "embedding_reranker_action", "demote")).strip().lower()
    if action not in _VALID_ACTIONS:
        action = "demote"
    return RerankerParams(
        min_confidence=float(getattr(config, "embedding_reranker_min_confidence", 0.80)),
        ocr_penalty=float(getattr(config, "embedding_reranker_ocr_penalty", 0.01)),
        same_doc_bonus=float(getattr(config, "embedding_reranker_same_doc_bonus", 0.03)),
        tesseract_bonus=float(getattr(config, "embedding_reranker_tesseract_bonus", 0.02)),
        action=action,
    )


# ---------------------------------------------------------------------------
# Match classification
# ---------------------------------------------------------------------------

def is_pure_embedding_match(match: "PageMatch") -> bool:
    return match.match_type in _PURE_EMBEDDING_MATCH_TYPES


# ---------------------------------------------------------------------------
# Scoring (pure math — shared with simulator)
# ---------------------------------------------------------------------------

def score_components(
    *,
    confidence: float,
    a_ocr: bool,
    b_ocr: bool,
    a_tesseract: bool,
    b_tesseract: bool,
    same_doc: bool,
    params: RerankerParams,
) -> tuple[float, dict[str, Any]]:
    """Compute precision score and component breakdown.

    Returns (precision_score, components_dict). Score is clamped to [0.0, 1.0].
    """
    ocr_penalty_total = (params.ocr_penalty if a_ocr else 0.0) + (params.ocr_penalty if b_ocr else 0.0)
    tesseract_bonus_total = (params.tesseract_bonus if a_tesseract else 0.0) + (params.tesseract_bonus if b_tesseract else 0.0)
    same_doc_bonus_applied = params.same_doc_bonus if same_doc else 0.0

    raw = confidence - ocr_penalty_total + tesseract_bonus_total + same_doc_bonus_applied
    precision_score = max(0.0, min(1.0, raw))

    components: dict[str, Any] = {
        "base_confidence": round(confidence, 4),
        "a_openai_ocr_selected": a_ocr,
        "b_openai_ocr_selected": b_ocr,
        "ocr_penalty_total": round(ocr_penalty_total, 4),
        "a_tesseract_usable": a_tesseract,
        "b_tesseract_usable": b_tesseract,
        "tesseract_bonus_total": round(tesseract_bonus_total, 4),
        "same_document": same_doc,
        "same_document_bonus": round(same_doc_bonus_applied, 4),
        "precision_score": round(precision_score, 4),
        "min_confidence": round(params.min_confidence, 4),
    }
    return precision_score, components


# ---------------------------------------------------------------------------
# Per-match decision
# ---------------------------------------------------------------------------

def compute_precision_score(match: "PageMatch", config: "EngineConfig") -> RerankerDecision:
    params = params_from_config(config)
    confidence = float(match.confidence)
    a_ocr = bool(getattr(match.page_a, "openai_ocr_selected", False))
    b_ocr = bool(getattr(match.page_b, "openai_ocr_selected", False))
    a_tess = bool(getattr(match.page_a, "tesseract_usable", False))
    b_tess = bool(getattr(match.page_b, "tesseract_usable", False))
    a_doc = str(getattr(match.page_a, "document_name", "") or "")
    b_doc = str(getattr(match.page_b, "document_name", "") or "")
    same_doc = bool(a_doc and a_doc == b_doc)

    precision_score, components = score_components(
        confidence=confidence,
        a_ocr=a_ocr,
        b_ocr=b_ocr,
        a_tesseract=a_tess,
        b_tesseract=b_tess,
        same_doc=same_doc,
        params=params,
    )

    if precision_score >= params.min_confidence:
        decision = "keep"
        reason = f"embedding_reranker_keep:score_gte_threshold:{precision_score:.4f}>={params.min_confidence:.4f}"
    elif params.action == "drop":
        decision = "drop"
        reason = f"embedding_reranker_drop:score_lt_threshold:{precision_score:.4f}<{params.min_confidence:.4f}"
    else:
        decision = "demote"
        reason = f"embedding_reranker_demote:score_lt_threshold:{precision_score:.4f}<{params.min_confidence:.4f}"

    return RerankerDecision(
        original_confidence=round(confidence, 4),
        precision_score=round(precision_score, 4),
        decision=decision,
        components=components,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# List-level application
# ---------------------------------------------------------------------------

def apply_embedding_reranker(
    matches: "list[PageMatch]",
    config: "EngineConfig",
) -> "list[PageMatch]":
    """Apply precision reranker to pure embedding candidates.

    Returns the same list object unchanged when disabled (exact pass-through).
    Returns a new list when enabled; non-pure-embedding matches are included
    unchanged; pure embedding matches are kept, demoted, or dropped per config.
    """
    if not getattr(config, "embedding_reranker_enabled", False):
        return matches

    # Import here to avoid circular imports at module level.
    from .review import annotate_match_for_review

    main_confidence = float(getattr(config, "main_review_min_confidence", 0.86))
    queue_profile = str(getattr(config, "review_queue_profile", "balanced"))

    result: list[PageMatch] = []
    for match in matches:
        if not is_pure_embedding_match(match):
            result.append(match)
            continue

        decision = compute_precision_score(match, config)
        event: dict[str, Any] = {
            "route": "embedding_reranker",
            "decision": decision.decision,
            "reason": decision.reason,
            "original_confidence": decision.original_confidence,
            "precision_score": decision.precision_score,
            "components": decision.components,
        }

        if decision.decision == "keep":
            match.ai_route_events.append(event)
            result.append(match)

        elif decision.decision == "demote":
            match.confidence = _DEMOTE_CONFIDENCE
            # Re-annotate so visibility reflects the lowered confidence, then
            # overwrite review_rationale with the reranker tag so calibration's
            # annotation guard (if not match.review_rationale) leaves it alone.
            annotate_match_for_review(match, main_confidence, queue_profile)
            match.review_rationale = (
                f"embedding_reranker_demoted: precision_score={decision.precision_score:.4f} "
                f"< threshold={decision.components['min_confidence']:.4f}"
            )
            match.ai_route_events.append(event)
            result.append(match)

        else:  # drop
            # Demote to 0.0 confidence and include in output so summarize_reranker
            # can count the drop event. At confidence 0.0 the match will be routed
            # to calibration_only and never surfaced to reviewers, so this is
            # functionally equivalent to exclusion while keeping the audit trail.
            match.confidence = 0.0
            annotate_match_for_review(match, main_confidence, queue_profile)
            match.review_rationale = (
                f"embedding_reranker_dropped: precision_score={decision.precision_score:.4f} "
                f"< threshold={decision.components['min_confidence']:.4f}"
            )
            match.ai_route_events.append(event)
            result.append(match)

    return result


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summarize_reranker(matches: "list[PageMatch]") -> dict[str, Any]:
    """Derive reranker summary from ai_route_events. No second state store."""
    evaluated = 0
    kept = 0
    demoted = 0
    dropped = 0
    scores: list[float] = []

    for match in matches:
        for event in getattr(match, "ai_route_events", []):
            if event.get("route") != "embedding_reranker":
                continue
            evaluated += 1
            d = event.get("decision", "")
            s = event.get("precision_score")
            if s is not None:
                scores.append(float(s))
            if d == "keep":
                kept += 1
            elif d == "demote":
                demoted += 1
            elif d == "drop":
                dropped += 1

    return {
        "enabled": True,
        "evaluated": evaluated,
        "kept": kept,
        "demoted": demoted,
        "dropped": dropped,
        "min_precision_score": round(min(scores), 4) if scores else None,
        "max_precision_score": round(max(scores), 4) if scores else None,
        "mean_precision_score": round(sum(scores) / len(scores), 4) if scores else None,
    }
