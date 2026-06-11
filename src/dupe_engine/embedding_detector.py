from __future__ import annotations

import math
from collections import Counter
from typing import Iterable

from .ai_ledger import ROUTE_TEXT_EMBEDDING, add_match_ai_event, make_ai_route_event, pair_subject_id
from .capabilities import check_embeddings_status
from .config import EngineConfig
from .hashing import hamming_distance
from .matchers import apply_candidate_controls, merge_pair_matches
from .models import MatchSignal, PageMatch, PageRecord
from .providers import EmbeddingResult, make_embedding_provider
from .progress import emit_progress
from .text import tokenize_for_similarity


EXACT_MATCH_TYPES = {"exact_image_duplicate", "exact_text_duplicate"}
EXACT_SIGNAL_NAMES = {"exact_image_hash", "exact_normalized_text_hash"}


def apply_embedding_detector(
    matches: list[PageMatch],
    config: EngineConfig,
    *,
    pages_a: list[PageRecord] | None = None,
    pages_b: list[PageRecord] | None = None,
    all_pairs: bool = False,
) -> list[PageMatch]:
    """Apply governed embedding support and bounded embedding recall.

    v0.9.5 only embedded deterministic candidates after cheaper layers nominated
    the pair. v0.9.8 keeps that reranking behavior, then optionally adds a
    bounded vector-neighborhood recall pass over pages with usable post-OCR text.
    The recall pass analyzes nearest-neighbor rank, margin, reciprocity, and
    source relation before creating reviewer-safe candidates.
    """

    if not config.enable_embeddings:
        return matches

    status = check_embeddings_status(config)
    selected_existing = select_embedding_candidates(matches, config)

    if not status.available:
        record_unavailable_embedding_events(selected_existing, config, status)
        return matches

    provider = make_embedding_provider(config)
    matches = apply_embedding_support_to_existing_candidates(matches, selected_existing, config, provider_status=status, provider=provider)

    if not config.embeddings_create_candidates or not pages_a or not pages_b:
        matches.sort(key=lambda item: item.confidence, reverse=True)
        return matches

    recall_candidates = create_embedding_recall_candidates(matches, pages_a, pages_b, config, provider_status=status, provider=provider, all_pairs=all_pairs)
    if not recall_candidates:
        matches.sort(key=lambda item: item.confidence, reverse=True)
        return matches

    merged = merge_pair_matches(matches + recall_candidates, unordered=all_pairs, config=config)
    return apply_candidate_controls(merged, config)


def record_unavailable_embedding_events(selected: list[PageMatch], config: EngineConfig, status) -> None:
    skipped_status = "dry_run_skipped" if status.status == "dry_run" else "skipped_unavailable"
    for match in selected:
        record_embedding_event(
            match,
            status=skipped_status,
            config=config,
            provider=status.provider,
            model=status.model or config.embeddings_model,
            reason=embedding_reason(match),
            selected=True,
            dry_run=status.status == "dry_run",
            error="" if status.status == "dry_run" else (status.reason or status.status),
            metadata={"provider_status": status.status, "provider_reason": status.reason or ""},
        )


def apply_embedding_support_to_existing_candidates(
    matches: list[PageMatch],
    selected: list[PageMatch],
    config: EngineConfig,
    *,
    provider_status,
    provider,
) -> list[PageMatch]:
    """Rerank/support deterministic candidates with pairwise embedding scores."""

    if not selected:
        return matches

    page_texts: dict[str, tuple[PageRecord, str]] = {}
    for match in selected:
        for page in (match.page_a, match.page_b):
            text = embedding_text_for_page(page)
            if has_enough_embedding_text(text, config):
                page_texts[page.page_id] = (page, text)

    if not page_texts:
        for match in selected:
            record_embedding_event(
                match,
                status="skipped_no_usable_text",
                config=config,
                provider=provider_status.provider,
                model=provider_status.model or config.embeddings_model,
                reason=embedding_reason(match),
                selected=True,
                error="no selected pages had enough best_text tokens for embedding",
            )
        return matches

    ordered_page_ids = list(page_texts)
    texts = [page_texts[page_id][1] for page_id in ordered_page_ids]
    emit_progress(stage="embedding_support_running", message=f"Embedding support for {len(texts)} page text(s)", current=0, total=len(texts), details={"mode": "candidate_support"})
    try:
        result = provider.embed_texts(texts)
    except Exception as exc:
        for match in selected:
            record_embedding_provider_error(match, config, provider_status, exc)
        return matches

    if len(result.vectors) != len(ordered_page_ids):
        error = f"expected {len(ordered_page_ids)} vectors, got {len(result.vectors)}"
        for match in selected:
            record_embedding_event(
                match,
                status="error",
                config=config,
                provider=result.provider,
                model=result.model,
                reason=embedding_reason(match),
                selected=True,
                attempted=True,
                error=error,
                metadata=result.metadata,
            )
        return matches

    emit_progress(stage="embedding_support_complete", message="Embedding support vectors received", current=len(texts), total=len(texts), details={"mode": "candidate_support", "page_count": len(texts)})
    vectors = dict(zip(ordered_page_ids, result.vectors))
    for match in selected:
        vec_a = vectors.get(match.page_a.page_id)
        vec_b = vectors.get(match.page_b.page_id)
        if vec_a is None or vec_b is None:
            record_embedding_event(
                match,
                status="skipped_no_usable_text",
                config=config,
                provider=result.provider,
                model=result.model,
                reason=embedding_reason(match),
                selected=True,
                error="one or both pages did not have enough embedding text",
                metadata=result.metadata,
            )
            continue
        score = cosine_similarity(vec_a, vec_b)
        match.signals.append(
            MatchSignal(
                "embedding_similarity",
                score,
                {
                    "provider": result.provider,
                    "model": result.model,
                    "threshold": config.embeddings_similarity_threshold,
                    "deterministic_stage": match.candidate_stage,
                    "embedding_mode": "candidate_support",
                },
            )
        )
        changed_matching = False
        if score >= config.embeddings_similarity_threshold:
            if match.match_type not in EXACT_MATCH_TYPES:
                match.match_type = "embedding_supported_candidate"
                changed_matching = True
            new_confidence = round(max(match.confidence, min(0.96, score)), 4)
            changed_matching = changed_matching or new_confidence > match.confidence
            match.confidence = new_confidence
            match.recommendation = "review_embedding_supported"
        else:
            match.recommendation = "review_embedding_not_supportive"
        record_embedding_event(
            match,
            status="completed",
            config=config,
            provider=result.provider,
            model=result.model,
            reason=embedding_reason(match),
            selected=True,
            attempted=True,
            succeeded=True,
            changed_matching=changed_matching,
            metadata={
                **result.metadata,
                "similarity": score,
                "threshold": config.embeddings_similarity_threshold,
                "text_source_a": match.page_a.best_text_source,
                "text_source_b": match.page_b.best_text_source,
                "embedding_mode": "candidate_support",
            },
        )
    matches.sort(key=lambda item: item.confidence, reverse=True)
    return matches


def create_embedding_recall_candidates(
    existing_matches: list[PageMatch],
    pages_a: list[PageRecord],
    pages_b: list[PageRecord],
    config: EngineConfig,
    *,
    provider_status,
    provider,
    all_pairs: bool = False,
) -> list[PageMatch]:
    """Create new semantic candidates using bounded vector neighborhood analysis.

    This is intentionally not an all-pairs threshold dump. The provider returns
    page embeddings, then the engine builds nearest-neighbor neighborhoods,
    calculates per-neighbor rank/margin/reciprocity/source relation, and only
    emits candidates that pass the configured gates.
    """

    existing_keys = {match.pair_key_unordered for match in existing_matches}
    exact_keys = {match.pair_key_unordered for match in existing_matches if match_is_exact(match)}

    eligible_pages = select_embedding_pages(list({page.page_id: page for page in (pages_a + pages_b)}.values()), config)
    eligible_ids = {page.page_id for page in eligible_pages}
    left_pages = [page for page in pages_a if page.page_id in eligible_ids]
    right_pages = [page for page in pages_b if page.page_id in eligible_ids]
    if not left_pages or not right_pages:
        return []

    page_texts = {page.page_id: embedding_text_for_page(page) for page in eligible_pages}
    ordered_ids = list(page_texts)
    emit_progress(stage="embedding_recall_running", message=f"Embedding recall for {len(ordered_ids)} eligible page(s)", current=0, total=len(ordered_ids), details={"mode": "vector_recall"})
    try:
        result = provider.embed_texts([page_texts[page_id] for page_id in ordered_ids])
    except Exception as exc:
        synthetic_match = first_non_exact_match(existing_matches)
        if synthetic_match is not None:
            record_embedding_provider_error(synthetic_match, config, provider_status, exc)
        return []

    if len(result.vectors) != len(ordered_ids):
        return []

    emit_progress(stage="embedding_recall_complete", message="Embedding recall vectors received", current=len(ordered_ids), total=len(ordered_ids), details={"mode": "vector_recall", "page_count": len(ordered_ids)})
    vectors = dict(zip(ordered_ids, result.vectors))
    neighborhoods = build_vector_neighborhoods(left_pages, right_pages, vectors, config, all_pairs=all_pairs)
    reciprocal_ranks = build_reciprocal_ranks(left_pages, right_pages, vectors, all_pairs=all_pairs)

    candidates: list[PageMatch] = []
    per_page_count: Counter[str] = Counter()
    max_pairs = max(0, config.max_embedding_pairs_per_job)
    max_per_page = max(1, config.embeddings_max_candidates_per_page)
    top_k = max(1, config.embeddings_candidate_top_k)

    for page_a in left_pages:
        neighbors = neighborhoods.get(page_a.page_id, [])[:top_k]
        for idx, (score, page_b) in enumerate(neighbors, start=1):
            key = tuple(sorted((page_a.page_id, page_b.page_id)))
            if key in existing_keys:
                continue
            if config.embeddings_skip_exact_matches and key in exact_keys:
                continue
            if all_pairs and page_a.page_id > page_b.page_id:
                continue
            if per_page_count[page_a.page_id] >= max_per_page or per_page_count[page_b.page_id] >= max_per_page:
                continue

            next_score = neighbors[idx][0] if idx < len(neighbors) else 0.0
            margin = round(score - next_score, 6)
            reciprocal_rank = reciprocal_ranks.get((page_a.page_id, page_b.page_id))
            reciprocal_ok = bool(reciprocal_rank is not None and reciprocal_rank <= top_k)
            source_relation = vector_source_relation(page_a, page_b)
            cross_source = source_relation == "cross_source"
            gate = vector_gate_decision(
                score=score,
                margin=margin,
                reciprocal_ok=reciprocal_ok,
                cross_source=cross_source,
                config=config,
                page_a=page_a,
                page_b=page_b,
                query_rank=idx,
                reciprocal_rank=reciprocal_rank,
            )
            if not gate["accepted"]:
                continue

            match = make_embedding_recall_match(
                page_a,
                page_b,
                score,
                config,
                result,
                query_rank=idx,
                reciprocal_rank=reciprocal_rank,
                margin_to_next=margin,
                source_relation=source_relation,
                gate=gate,
            )
            candidates.append(match)
            per_page_count[page_a.page_id] += 1
            per_page_count[page_b.page_id] += 1
            if max_pairs and len(candidates) >= max_pairs:
                return candidates
    return candidates


def build_vector_neighborhoods(
    left_pages: list[PageRecord],
    right_pages: list[PageRecord],
    vectors: dict[str, list[float]],
    config: EngineConfig,
    *,
    all_pairs: bool = False,
) -> dict[str, list[tuple[float, PageRecord]]]:
    neighborhoods: dict[str, list[tuple[float, PageRecord]]] = {}
    for page_a in left_pages:
        vec_a = vectors.get(page_a.page_id)
        if vec_a is None:
            continue
        scored: list[tuple[float, PageRecord]] = []
        for page_b in right_pages:
            if page_a.page_id == page_b.page_id:
                continue
            if all_pairs and page_a.page_id > page_b.page_id:
                # Keep the same unordered-pair convention used by all-pairs matching.
                continue
            vec_b = vectors.get(page_b.page_id)
            if vec_b is None:
                continue
            scored.append((cosine_similarity(vec_a, vec_b), page_b))
        scored.sort(key=lambda item: item[0], reverse=True)
        neighborhoods[page_a.page_id] = scored
    return neighborhoods


def build_reciprocal_ranks(
    left_pages: list[PageRecord],
    right_pages: list[PageRecord],
    vectors: dict[str, list[float]],
    *,
    all_pairs: bool = False,
) -> dict[tuple[str, str], int]:
    reciprocal: dict[tuple[str, str], int] = {}
    for page_b in right_pages:
        vec_b = vectors.get(page_b.page_id)
        if vec_b is None:
            continue
        scored: list[tuple[float, PageRecord]] = []
        for page_a in left_pages:
            if page_a.page_id == page_b.page_id:
                continue
            if all_pairs and page_a.page_id > page_b.page_id:
                continue
            vec_a = vectors.get(page_a.page_id)
            if vec_a is None:
                continue
            scored.append((cosine_similarity(vec_b, vec_a), page_a))
        scored.sort(key=lambda item: item[0], reverse=True)
        for rank, (_score, page_a) in enumerate(scored, start=1):
            reciprocal[(page_a.page_id, page_b.page_id)] = rank
    return reciprocal


def vector_gate_decision(
    *,
    score: float,
    margin: float,
    reciprocal_ok: bool,
    cross_source: bool,
    config: EngineConfig,
    page_a: PageRecord | None = None,
    page_b: PageRecord | None = None,
    query_rank: int = 1,
    reciprocal_rank: int | None = None,
) -> dict[str, object]:
    reasons: list[str] = []
    margin_ok = margin >= config.embeddings_min_margin
    hybrid = hybrid_vector_score(
        score=score,
        margin=margin,
        reciprocal_ok=reciprocal_ok,
        cross_source=cross_source,
        page_a=page_a,
        page_b=page_b,
        query_rank=query_rank,
        reciprocal_rank=reciprocal_rank,
        config=config,
    ) if page_a is not None and page_b is not None else {"score": score}
    if config.embeddings_hybrid_scoring_enabled:
        if hybrid["score"] < config.embeddings_hybrid_min_score:
            reasons.append("below_hybrid_vector_score")
    elif score < config.embeddings_similarity_threshold:
        reasons.append("below_similarity_threshold")
    if config.embeddings_require_cross_source and not cross_source:
        reasons.append("same_source_disallowed")
    if config.embeddings_require_reciprocal and not reciprocal_ok:
        reasons.append("not_reciprocal")
    if config.embeddings_min_margin > 0 and not margin_ok and not reciprocal_ok and not config.embeddings_hybrid_scoring_enabled:
        reasons.append("low_margin_not_reciprocal")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "similarity_ok": score >= config.embeddings_similarity_threshold,
        "margin_ok": margin_ok,
        "reciprocal_ok": reciprocal_ok,
        "cross_source_ok": cross_source or not config.embeddings_require_cross_source,
        "min_similarity": config.embeddings_similarity_threshold,
        "min_margin": config.embeddings_min_margin,
        "require_cross_source": config.embeddings_require_cross_source,
        "require_reciprocal": config.embeddings_require_reciprocal,
        "hybrid_scoring_enabled": config.embeddings_hybrid_scoring_enabled,
        "hybrid_min_score": config.embeddings_hybrid_min_score,
        "hybrid": hybrid,
    }


def hybrid_vector_score(
    *,
    score: float,
    margin: float,
    reciprocal_ok: bool,
    cross_source: bool,
    page_a: PageRecord,
    page_b: PageRecord,
    query_rank: int,
    reciprocal_rank: int | None,
    config: EngineConfig,
) -> dict[str, object]:
    rank_quality = 1.0 / max(1, query_rank)
    reciprocal_quality = 1.0 / max(1, reciprocal_rank) if reciprocal_rank else 0.0
    margin_quality = min(1.0, max(0.0, margin) / max(0.01, config.embeddings_min_margin or 0.01))
    min_words = min(page_a.best_word_count or 0, page_b.best_word_count or 0)
    text_quality = min(1.0, float(min_words) / 120.0)
    visual_support = pages_have_visual_support(page_a, page_b, config)
    ocr_source_bonus = 1.0 if {page_a.best_text_source, page_b.best_text_source} & {"openai_ocr", "tesseract_ocr"} else 0.0
    low_info_penalty = 0.15 if (page_a.is_low_information or page_b.is_low_information) else 0.0
    same_source_penalty = 0.05 if not cross_source else 0.0
    hybrid_score = (
        0.62 * score
        + 0.10 * rank_quality
        + 0.08 * margin_quality
        + 0.07 * reciprocal_quality
        + 0.06 * text_quality
        + 0.04 * (1.0 if visual_support else 0.0)
        + 0.03 * ocr_source_bonus
        - low_info_penalty
        - same_source_penalty
    )
    return {
        "score": round(max(0.0, min(1.0, hybrid_score)), 6),
        "rank_quality": round(rank_quality, 6),
        "margin_quality": round(margin_quality, 6),
        "reciprocal_quality": round(reciprocal_quality, 6),
        "text_quality": round(text_quality, 6),
        "visual_support": visual_support,
        "ocr_source_bonus": ocr_source_bonus,
        "low_information_penalty": low_info_penalty,
        "same_source_penalty": same_source_penalty,
    }


def pages_have_visual_support(page_a: PageRecord, page_b: PageRecord, config: EngineConfig) -> bool:
    if not page_a.perceptual_hash or not page_b.perceptual_hash:
        return False
    try:
        return hamming_distance(page_a.perceptual_hash, page_b.perceptual_hash) <= config.standard_phash_threshold
    except Exception:
        return False


def vector_source_relation(page_a: PageRecord, page_b: PageRecord) -> str:
    return "same_source" if source_group_key(page_a) == source_group_key(page_b) else "cross_source"


def source_group_key(page: PageRecord) -> str:
    raw = page.meta.get("source_group") or page.group or ""
    if raw and raw not in {"CORPUS", "T"}:
        return str(raw)
    name = page.document_name.replace("\\", "/")
    if "/" in name:
        return name.split("/", 1)[0]
    return str(raw or page.document_id)


def make_embedding_recall_match(
    page_a: PageRecord,
    page_b: PageRecord,
    score: float,
    config: EngineConfig,
    result: EmbeddingResult,
    *,
    query_rank: int,
    reciprocal_rank: int | None,
    margin_to_next: float,
    source_relation: str,
    gate: dict[str, object],
) -> PageMatch:
    hybrid_payload = gate.get("hybrid") if isinstance(gate.get("hybrid"), dict) else {}
    hybrid_score_value = float(hybrid_payload.get("score", score)) if hybrid_payload else score
    candidate_confidence = hybrid_score_value if config.embeddings_hybrid_scoring_enabled else score
    signals = [
        MatchSignal(
            "embedding_similarity",
            score,
            {
                "provider": result.provider,
                "model": result.model,
                "threshold": config.embeddings_similarity_threshold,
                "top_k": config.embeddings_candidate_top_k,
                "embedding_mode": "hybrid_vector_recall" if config.embeddings_hybrid_scoring_enabled else "vector_recall",
                "vector_analysis": True,
                "query_rank": query_rank,
                "reciprocal_rank": reciprocal_rank,
                "margin_to_next": margin_to_next,
                "source_relation": source_relation,
                "gate": gate,
                "text_source_a": page_a.best_text_source,
                "text_source_b": page_b.best_text_source,
            },
        )
    ]
    if config.embeddings_hybrid_scoring_enabled:
        signals.append(
            MatchSignal(
                "hybrid_vector_score",
                hybrid_score_value,
                {"hybrid": hybrid_payload, "threshold": config.embeddings_hybrid_min_score},
            )
        )
    match = PageMatch(
        match_type="hybrid_vector_candidate" if config.embeddings_hybrid_scoring_enabled else "embedding_similarity_candidate",
        confidence=round(min(0.94, candidate_confidence), 4),
        page_a=page_a,
        page_b=page_b,
        signals=signals,
        recommendation="review_hybrid_vector_candidate" if config.embeddings_hybrid_scoring_enabled else "review_embedding_vector_candidate",
        candidate_stage="hybrid_vector_recall" if config.embeddings_hybrid_scoring_enabled else "vector_recall",
    )
    record_embedding_event(
        match,
        status="completed",
        config=config,
        provider=result.provider,
        model=result.model,
        reason="hybrid vector-neighborhood recall candidate after OCR rescue" if config.embeddings_hybrid_scoring_enabled else "bounded vector-neighborhood recall candidate after OCR rescue",
        selected=True,
        attempted=True,
        succeeded=True,
        changed_matching=True,
        metadata={
            **result.metadata,
            "similarity": score,
            "threshold": config.embeddings_similarity_threshold,
            "embedding_mode": "hybrid_vector_recall" if config.embeddings_hybrid_scoring_enabled else "vector_recall",
            "query_rank": query_rank,
            "reciprocal_rank": reciprocal_rank,
            "margin_to_next": margin_to_next,
            "source_relation": source_relation,
            "gate": gate,
            "hybrid_score": hybrid_score_value if config.embeddings_hybrid_scoring_enabled else None,
            "text_source_a": page_a.best_text_source,
            "text_source_b": page_b.best_text_source,
        },
    )
    return match

def select_embedding_pages(pages: list[PageRecord], config: EngineConfig) -> list[PageRecord]:
    candidates = [page for page in pages if page_is_embedding_eligible(page, config)]
    candidates.sort(key=embedding_page_sort_key, reverse=True)
    max_pages = max(0, config.embeddings_max_pages_per_job)
    return candidates[:max_pages] if max_pages else candidates


def page_is_embedding_eligible(page: PageRecord, config: EngineConfig) -> bool:
    if page.is_low_information:
        return False
    text = embedding_text_for_page(page)
    if len(text.strip()) < config.embeddings_min_text_chars:
        return False
    return has_enough_embedding_text(text, config)


def embedding_page_sort_key(page: PageRecord) -> tuple[int, int, int]:
    source_rank = {"openai_ocr": 4, "tesseract_ocr": 3, "native": 2, "none": 0}.get(page.best_text_source, 1)
    return (source_rank, page.best_word_count, len(embedding_text_for_page(page)))


def record_embedding_provider_error(match: PageMatch, config: EngineConfig, status, exc: Exception) -> None:
    match.signals.append(
        MatchSignal(
            "embedding_provider_error",
            0.0,
            {"provider": status.provider, "model": status.model, "error": str(exc)[:500]},
        )
    )
    record_embedding_event(
        match,
        status="error",
        config=config,
        provider=status.provider,
        model=status.model or config.embeddings_model,
        reason=embedding_reason(match),
        selected=True,
        attempted=True,
        error=str(exc)[:500],
    )


def first_non_exact_match(matches: Iterable[PageMatch]) -> PageMatch | None:
    for match in matches:
        if not match_is_exact(match):
            return match
    return None


def match_is_exact(match: PageMatch) -> bool:
    if match.match_type in EXACT_MATCH_TYPES:
        return True
    signal_names = {signal.name for signal in match.signals}
    return bool(signal_names & EXACT_SIGNAL_NAMES)


def record_embedding_event(
    match: PageMatch,
    *,
    status: str,
    config: EngineConfig,
    provider: str,
    model: str,
    reason: str,
    selected: bool = True,
    attempted: bool = False,
    succeeded: bool = False,
    changed_matching: bool = False,
    dry_run: bool = False,
    error: str = "",
    metadata: dict | None = None,
) -> None:
    add_match_ai_event(
        match,
        make_ai_route_event(
            route=ROUTE_TEXT_EMBEDDING,
            status=status,
            provider=provider,
            model=model,
            subject_type="candidate_pair",
            subject_id=pair_subject_id(match),
            input_kind="page_text_pair",
            reason=reason,
            selected=selected,
            attempted=attempted,
            succeeded=succeeded,
            changed_matching=changed_matching,
            dry_run=dry_run,
            error=error,
            candidate_stage=match.candidate_stage,
            candidate_confidence=match.confidence,
            pair_key=pair_subject_id(match),
            metadata=metadata or {},
        ),
    )


def embedding_reason(match: PageMatch) -> str:
    return (
        f"{match.candidate_stage} candidate confidence {match.confidence:.3f}; "
        "deterministic candidate selected for semantic text comparison"
    )


def select_embedding_candidates(matches: list[PageMatch], config: EngineConfig) -> list[PageMatch]:
    candidates = [
        match
        for match in matches
        if match.escalation.embedding_required
        and match.match_type not in EXACT_MATCH_TYPES
        and not (match.page_a.is_low_information or match.page_b.is_low_information)
    ]
    candidates.sort(key=lambda match: (match.confidence, len(match.signals)), reverse=True)
    return candidates[: max(0, config.max_embedding_pairs_per_job)]


def embedding_text_for_page(page: PageRecord) -> str:
    return page.best_text or page.raw_text or page.comparison_text or page.normalized_text or ""


def has_enough_embedding_text(text: str, config: EngineConfig) -> bool:
    return len(tokenize_for_similarity(text, config.domain_stopwords)) >= config.embeddings_min_words


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return round(dot / (norm_left * norm_right), 6)
