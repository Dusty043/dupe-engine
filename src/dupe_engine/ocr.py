from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import re

from .ai_ledger import ROUTE_VISION_OCR_EXTRACTION, add_page_ai_event, make_ai_route_event, page_subject_id
from .config import EngineConfig
from .hashing import sha256_bytes
from .models import PageMatch, PageRecord
from .providers import OcrResult, make_ocr_provider, make_openai_ocr_provider, make_vision_ocr_provider
from .text import normalize_text_for_hash, normalize_text_for_similarity, substantial_text, tokenize_for_similarity
from .progress import emit_progress


def run_local_ocr(image_path: Path) -> str:
    """Backwards-compatible OCR helper."""

    result = run_ocr(image_path, EngineConfig(enable_ocr=True))
    return result.text


def run_ocr(image_path: Path, config: EngineConfig) -> OcrResult:
    provider = make_ocr_provider(config)
    return provider.extract_page_text(image_path)


def word_count(text: str, config: EngineConfig) -> int:
    return len(tokenize_for_similarity(text or "", config.domain_stopwords))


def classify_native_text(text: str, config: EngineConfig) -> str:
    if not text or not text.strip():
        return "missing"
    if word_count(text, config) >= config.native_min_usable_words:
        return "usable"
    return "weak"


def apply_initial_ocr_route(page: PageRecord, image_path: Path, config: EngineConfig) -> None:
    """Apply native → Tesseract route during ingestion.

    OpenAI OCR fallback is intentionally not called here by default because v0.8
    only escalates provider OCR after deterministic candidate value exists.
    """

    page.native_word_count = word_count(page.native_text, config)
    page.native_text_status = classify_native_text(page.native_text, config)
    page.best_text_source = "native" if page.native_text_status == "usable" else "none"
    page.ocr_route = "native_only" if page.native_text_status == "usable" else "native_weak"

    if not config.enable_ocr or page.native_text_status == "usable":
        update_best_text(page, page.native_text, "native", config)
        return

    result = run_ocr(image_path, config)
    page.tesseract_attempted = result.provider == "tesseract"
    page.tesseract_text = result.text if result.provider == "tesseract" else ""
    page.tesseract_confidence = result.confidence if result.provider == "tesseract" else None
    page.tesseract_word_count = int(result.metadata.get("word_count", word_count(result.text, config)) or 0) if result.provider == "tesseract" else 0
    page.tesseract_usable = bool(result.metadata.get("usable", False)) if result.provider == "tesseract" else False
    page.tesseract_profile = str(result.metadata.get("profile")) if result.provider == "tesseract" and result.metadata.get("profile") else None

    page.meta["tesseract_metadata"] = result.metadata

    if page.tesseract_usable and len(result.text.strip()) > len(page.native_text.strip()):
        page.ocr_used = True
        page.ocr_text = result.text
        page.ocr_confidence = result.confidence
        page.ocr_route = "tesseract_usable"
        update_best_text(page, result.text, "tesseract_ocr", config)
    else:
        page.ocr_route = "tesseract_weak" if page.tesseract_attempted else "tesseract_unavailable"
        update_best_text(page, page.native_text, "native" if page.native_text.strip() else "none", config)


def update_best_text(page: PageRecord, text: str, source: str, config: EngineConfig) -> None:
    page.raw_text = text or ""
    page.best_text = page.raw_text
    page.text_source = "ocr" if source in {"tesseract_ocr", "openai_ocr"} else source
    page.best_text_source = source
    page.normalized_text = normalize_text_for_hash(page.raw_text)
    page.comparison_text = normalize_text_for_similarity(page.raw_text)
    page.best_word_count = word_count(page.raw_text, config)
    page.ocr_word_count = max(page.tesseract_word_count, page.openai_ocr_word_count, word_count(page.ocr_text, config))
    page.text_hash = None
    if substantial_text(page.normalized_text, stopwords=config.domain_stopwords):
        page.text_hash = sha256_bytes(page.normalized_text.encode("utf-8"))



def record_vision_ocr_event(
    page: PageRecord,
    *,
    status: str,
    config: EngineConfig,
    reason: str,
    provider: str | None = None,
    model: str | None = None,
    selected: bool = True,
    attempted: bool = False,
    succeeded: bool = False,
    changed_evidence: bool = False,
    dry_run: bool = False,
    error: str = "",
    usage: dict | None = None,
    metadata: dict | None = None,
) -> None:
    add_page_ai_event(
        page,
        make_ai_route_event(
            route=ROUTE_VISION_OCR_EXTRACTION,
            status=status,
            provider=provider or config.openai_ocr_provider,
            model=model or config.openai_ocr_model,
            subject_type="page",
            subject_id=page_subject_id(page),
            input_kind="page_image",
            reason=reason,
            selected=selected,
            attempted=attempted,
            succeeded=succeeded,
            changed_evidence=changed_evidence,
            dry_run=dry_run,
            usage=usage or {},
            error=error,
            document_name=page.document_name,
            page_number=page.page_number,
            metadata=metadata or {},
        ),
    )

def apply_openai_ocr_fallback(matches: list[PageMatch], config: EngineConfig, pages: list[PageRecord] | None = None) -> int:
    """Escalate selected weak-OCR pages to OpenAI OCR fallback.

    This function mutates PageRecord objects already attached to matches. The
    caller should rerun deterministic comparison afterward if any page changed.

    v0.8 also records selected-but-not-called pages for dry-run and unavailable
    provider validation. That lets OCR testing answer "what would escalate and
    why" without requiring credentials.
    """

    if not config.enable_openai_ocr:
        return 0

    selected = select_openai_ocr_pages(matches, config, pages=pages)
    for page, reason in selected:
        page.openai_ocr_selected = True
        page.openai_ocr_selection_reason = reason
        page.ocr_escalation_reason = reason

    emit_progress(
        stage="openai_ocr_selection",
        message=f"Selected {len(selected)} page(s) for OpenAI OCR fallback",
        current=0,
        total=len(selected),
        details={
            "selection_mode": config.openai_ocr_selection_mode,
            "max_pages_per_job": config.openai_ocr_max_pages_per_job,
            "selected_pages": len(selected),
        },
    )

    if not selected:
        return 0

    provider = make_vision_ocr_provider(config)
    status = provider.healthcheck()

    if config.openai_ocr_dry_run:
        for page, reason in selected:
            page.openai_ocr_skip_reason = "dry_run"
            metadata = {"skipped_reason": "DUPE_OPENAI_OCR_DRY_RUN=true; provider calls disabled"}
            page.meta["openai_ocr_metadata"] = metadata
            record_vision_ocr_event(
                page,
                status="dry_run_skipped",
                config=config,
                reason=reason,
                dry_run=True,
                metadata=metadata,
            )
        emit_progress(stage="openai_ocr_complete", message="OpenAI OCR fallback dry-run complete", status="running", current=0, total=len(selected), details={"dry_run": True, "selected_pages": len(selected)})
        return 0

    if not status.available:
        unavailable_reason = status.reason or status.status
        for page, selection_reason in selected:
            page.openai_ocr_skip_reason = unavailable_reason
            metadata = {"skipped_reason": unavailable_reason}
            page.meta["openai_ocr_metadata"] = metadata
            record_vision_ocr_event(
                page,
                status="skipped_unavailable",
                config=config,
                reason=selection_reason,
                error=unavailable_reason,
                metadata=metadata,
            )
        emit_progress(stage="openai_ocr_complete", message="OpenAI OCR fallback unavailable", status="running", current=0, total=len(selected), details={"available": False, "reason": unavailable_reason, "selected_pages": len(selected)})
        return 0

    changed = 0
    for idx, (page, reason) in enumerate(selected, start=1):
        emit_progress(
            stage="openai_ocr_running",
            message=f"OpenAI OCR fallback {idx}/{len(selected)}",
            current=idx - 1,
            total=len(selected),
            details={"document": page.document_name, "page": page.page_number, "reason": reason},
        )
        result = provider.extract_page_text(Path(page.image_path))
        page.openai_ocr_attempted = True
        page.openai_ocr_provider = result.provider
        page.openai_ocr_model = str(result.metadata.get("model") or config.openai_ocr_model)
        page.openai_ocr_text = result.text
        page.openai_ocr_word_count = word_count(result.text, config)
        page.openai_ocr_usable = openai_ocr_is_usable(result.text, config)
        page.ocr_escalation_reason = reason
        page.meta["openai_ocr_metadata"] = result.metadata
        if result.metadata.get("error"):
            page.openai_ocr_error = str(result.metadata.get("error"))
        if result.metadata.get("skipped_reason"):
            page.openai_ocr_skip_reason = str(result.metadata.get("skipped_reason"))
        improved = False
        accepted, acceptance_reason, quality_metadata = should_accept_openai_ocr_result(page, result.text, config)
        page.meta["openai_ocr_quality"] = quality_metadata
        if page.openai_ocr_usable and accepted:
            page.ocr_used = True
            page.ocr_text = result.text
            page.ocr_confidence = result.confidence
            page.ocr_route = "openai_ocr_fallback"
            apply_openai_ocr_evidence_text(page, result.text, result.confidence, config)
            changed += 1
            improved = True
        else:
            page.openai_ocr_skip_reason = page.openai_ocr_skip_reason or acceptance_reason
        record_vision_ocr_event(
            page,
            status="completed" if not page.openai_ocr_error else "error",
            config=config,
            reason=reason,
            provider=result.provider,
            model=page.openai_ocr_model,
            attempted=True,
            succeeded=page.openai_ocr_usable and not bool(page.openai_ocr_error),
            changed_evidence=improved,
            error=page.openai_ocr_error or "",
            usage=result.metadata.get("usage", {}) if isinstance(result.metadata.get("usage", {}), dict) else {},
            metadata={
                "word_count": page.openai_ocr_word_count,
                "usable": page.openai_ocr_usable,
                "acceptance_reason": acceptance_reason,
                "quality": quality_metadata,
                "response_id": result.metadata.get("response_id"),
                "skipped_reason": page.openai_ocr_skip_reason or "",
                "cascade_from": result.metadata.get("cascade_from"),
            },
        )
        emit_progress(
            stage="openai_ocr_running",
            message=f"OpenAI OCR fallback {idx}/{len(selected)}",
            current=idx,
            total=len(selected),
            details={
                "document": page.document_name,
                "page": page.page_number,
                "usable": page.openai_ocr_usable,
                "word_count": page.openai_ocr_word_count,
                "improved": improved,
                "error": page.openai_ocr_error or "",
            },
        )
    emit_progress(stage="openai_ocr_complete", message=f"OpenAI OCR fallback complete; {changed} page(s) improved", current=len(selected), total=len(selected), details={"selected_pages": len(selected), "changed_pages": changed})
    return changed



def apply_openai_ocr_post_candidate_rescue(matches: list[PageMatch], config: EngineConfig, pages: list[PageRecord] | None = None) -> int:
    """Second-pass OpenAI OCR rescue for suspicious weak candidate neighborhoods.

    v0.9.9 keeps the first fallback pass quota/page-quality based. This pass is
    intentionally pair-aware: after deterministic/vector candidates exist, it
    spends a separate reserve budget on remaining weak pages attached to
    suspicious candidates. It targets the common calibration failure mode where
    a truth pair was nearly surfaced but one side never received provider OCR.
    """

    if not config.enable_openai_ocr:
        return 0
    if not config.openai_ocr_post_candidate_rescue_enabled:
        return 0
    if config.openai_ocr_post_candidate_max_pages <= 0:
        return 0

    selected = select_post_candidate_openai_ocr_pages(matches, config, pages=pages)
    for page, reason in selected:
        page.openai_ocr_selected = True
        page.openai_ocr_selection_reason = reason
        page.ocr_escalation_reason = reason

    emit_progress(
        stage="post_candidate_openai_ocr_selection",
        message=f"Selected {len(selected)} page(s) for post-candidate OpenAI OCR rescue",
        current=0,
        total=len(selected),
        details={
            "selection_mode": "post_candidate_rescue",
            "max_pages": config.openai_ocr_post_candidate_max_pages,
            "selected_pages": len(selected),
        },
    )

    if not selected:
        return 0

    provider = make_vision_ocr_provider(config)
    status = provider.healthcheck()

    if config.openai_ocr_dry_run:
        for page, reason in selected:
            page.openai_ocr_skip_reason = "dry_run"
            metadata = {"skipped_reason": "DUPE_OPENAI_OCR_DRY_RUN=true; provider calls disabled", "post_candidate_rescue": True}
            page.meta["openai_ocr_metadata"] = metadata
            record_vision_ocr_event(
                page,
                status="dry_run_skipped",
                config=config,
                reason=reason,
                dry_run=True,
                metadata=metadata,
            )
        emit_progress(stage="post_candidate_openai_ocr_complete", message="Post-candidate OpenAI OCR rescue dry-run complete", current=0, total=len(selected), details={"dry_run": True, "selected_pages": len(selected)})
        return 0

    if not status.available:
        unavailable_reason = status.reason or status.status
        for page, selection_reason in selected:
            page.openai_ocr_skip_reason = unavailable_reason
            metadata = {"skipped_reason": unavailable_reason, "post_candidate_rescue": True}
            page.meta["openai_ocr_metadata"] = metadata
            record_vision_ocr_event(
                page,
                status="skipped_unavailable",
                config=config,
                reason=selection_reason,
                error=unavailable_reason,
                metadata=metadata,
            )
        emit_progress(stage="post_candidate_openai_ocr_complete", message="Post-candidate OpenAI OCR rescue unavailable", current=0, total=len(selected), details={"available": False, "reason": unavailable_reason, "selected_pages": len(selected)})
        return 0

    changed = 0
    for idx, (page, reason) in enumerate(selected, start=1):
        emit_progress(
            stage="post_candidate_openai_ocr_running",
            message=f"Post-candidate OpenAI OCR rescue {idx}/{len(selected)}",
            current=idx - 1,
            total=len(selected),
            details={"document": page.document_name, "page": page.page_number, "reason": reason},
        )
        result = provider.extract_page_text(Path(page.image_path))
        page.openai_ocr_attempted = True
        page.openai_ocr_provider = result.provider
        page.openai_ocr_model = str(result.metadata.get("model") or config.openai_ocr_model)
        page.openai_ocr_text = result.text
        page.openai_ocr_word_count = word_count(result.text, config)
        page.openai_ocr_usable = openai_ocr_is_usable(result.text, config)
        page.ocr_escalation_reason = reason
        metadata = dict(result.metadata)
        metadata["post_candidate_rescue"] = True
        page.meta["openai_ocr_metadata"] = metadata
        if result.metadata.get("error"):
            page.openai_ocr_error = str(result.metadata.get("error"))
        if result.metadata.get("skipped_reason"):
            page.openai_ocr_skip_reason = str(result.metadata.get("skipped_reason"))
        improved = False
        accepted, acceptance_reason, quality_metadata = should_accept_openai_ocr_result(page, result.text, config)
        page.meta["openai_ocr_quality"] = quality_metadata
        if page.openai_ocr_usable and accepted:
            page.ocr_used = True
            page.ocr_text = result.text
            page.ocr_confidence = result.confidence
            page.ocr_route = "openai_ocr_post_candidate_rescue"
            apply_openai_ocr_evidence_text(page, result.text, result.confidence, config)
            changed += 1
            improved = True
        else:
            page.openai_ocr_skip_reason = page.openai_ocr_skip_reason or acceptance_reason
        record_vision_ocr_event(
            page,
            status="completed" if not page.openai_ocr_error else "error",
            config=config,
            reason=reason,
            attempted=True,
            succeeded=page.openai_ocr_usable and not bool(page.openai_ocr_error),
            changed_evidence=improved,
            error=page.openai_ocr_error or "",
            usage=result.metadata.get("usage", {}) if isinstance(result.metadata.get("usage", {}), dict) else {},
            metadata={
                "word_count": page.openai_ocr_word_count,
                "usable": page.openai_ocr_usable,
                "acceptance_reason": acceptance_reason,
                "quality": quality_metadata,
                "response_id": result.metadata.get("response_id"),
                "skipped_reason": page.openai_ocr_skip_reason or "",
                "post_candidate_rescue": True,
            },
        )
        emit_progress(
            stage="post_candidate_openai_ocr_running",
            message=f"Post-candidate OpenAI OCR rescue {idx}/{len(selected)}",
            current=idx,
            total=len(selected),
            details={
                "document": page.document_name,
                "page": page.page_number,
                "usable": page.openai_ocr_usable,
                "word_count": page.openai_ocr_word_count,
                "improved": improved,
                "error": page.openai_ocr_error or "",
            },
        )
    emit_progress(stage="post_candidate_openai_ocr_complete", message=f"Post-candidate OpenAI OCR rescue complete; {changed} page(s) improved", current=len(selected), total=len(selected), details={"selected_pages": len(selected), "changed_pages": changed})
    return changed


def select_post_candidate_openai_ocr_pages(
    matches: list[PageMatch],
    config: EngineConfig,
    pages: list[PageRecord] | None = None,
) -> list[tuple[PageRecord, str]]:
    selected: dict[str, tuple[PageRecord, str, float]] = {}
    min_conf = config.openai_ocr_post_candidate_min_confidence

    # Pool A: original candidate-bound rescue behavior.
    for match in sorted(matches, key=lambda item: post_candidate_rescue_match_score(item, config), reverse=True):
        if match.match_type in {"exact_image_duplicate", "exact_text_duplicate"}:
            continue
        if match.confidence < min_conf and not post_candidate_match_has_rescue_signal(match):
            continue
        priority = post_candidate_rescue_match_score(match, config)
        for side, page in (("A", match.page_a), ("B", match.page_b)):
            if not page_needs_openai_ocr(page, config, allow_low_information=config.openai_ocr_allow_low_information_pages):
                continue
            reason = (
                "post_candidate_rescue candidate-bound selection; "
                f"match_type={match.match_type}; stage={match.candidate_stage}; "
                f"confidence={match.confidence:.3f}; page_side={side}; "
                f"ocr_route={page.ocr_route}; best_words={page.best_word_count}"
            )
            score = priority + page_openai_ocr_selection_score(page, config)
            add_selected_openai_ocr_page(selected, page, reason, score)

    candidate_bound_count = len(selected)

    # Pool B: v0.10.8 orphan weak-page rescue.
    #
    # The first implementation of post-candidate rescue could only OCR pages
    # attached to existing candidate matches. That misses the hard v4 case where
    # weak/vision-expected pages never enter the candidate pool at all. Fill the
    # remaining reserve from all weak/orphan pages so the existing engine rerun
    # path can regenerate candidates after OCR evidence improves.
    if pages:
        add_orphan_post_candidate_openai_ocr_pages(selected, pages, config)

    ordered = sorted(selected.values(), key=lambda item: item[2], reverse=True)
    rescue_config = replace(config, openai_ocr_max_pages_per_job=config.openai_ocr_post_candidate_max_pages)
    capped = apply_openai_ocr_budget_caps(ordered, rescue_config)

    orphan_count = sum(1 for _page, reason in capped if "orphan weak-page" in reason)
    for page, reason in capped:
        page.meta["post_candidate_rescue_source"] = "orphan_weak_page" if "orphan weak-page" in reason else "candidate_bound"
        page.meta["post_candidate_rescue_candidate_bound_pool_size"] = candidate_bound_count
        page.meta["post_candidate_rescue_orphan_selected"] = orphan_count

    return capped


def add_orphan_post_candidate_openai_ocr_pages(
    selected: dict[str, tuple[PageRecord, str, float]],
    pages: list[PageRecord],
    config: EngineConfig,
) -> int:
    """Add weak pages that are not represented in current candidate matches.

    Candidate-bound post-candidate rescue is useful only when a weak page already
    appears in at least one candidate. This helper intentionally covers the
    orphan case: pages that still need provider OCR but did not survive candidate
    generation.
    """

    added = 0
    for page in pages:
        if not page_needs_openai_ocr(page, config, allow_low_information=config.openai_ocr_allow_low_information_pages):
            continue

        # Do not spend the post-candidate reserve retrying pages already sent to
        # provider OCR in the initial fallback pass.
        if getattr(page, "openai_ocr_attempted", False):
            continue

        reason = (
            "post_candidate_rescue orphan weak-page selection; "
            f"ocr_route={getattr(page, 'ocr_route', '')}; "
            f"best_words={getattr(page, 'best_word_count', 0)}; "
            f"native_status={getattr(page, 'native_text_status', '')}; "
            f"tesseract_attempted={getattr(page, 'tesseract_attempted', False)}; "
            f"tesseract_usable={getattr(page, 'tesseract_usable', False)}"
        )

        # Keep candidate-bound pages ahead when both pools compete for the same
        # reserve. Orphan pages fill unused/remaining budget.
        score = page_openai_ocr_selection_score(page, config) - 100.0
        before = len(selected)
        add_selected_openai_ocr_page(selected, page, reason, score)
        if len(selected) > before:
            added += 1

    return added


def post_candidate_match_has_rescue_signal(match: PageMatch) -> bool:
    signal_names = {signal.name for signal in match.signals}
    if signal_names & {"embedding_similarity", "hybrid_vector_score", "near_visual_candidate", "perceptual_hash_distance"}:
        return True
    if match.match_type in {"embedding_similarity_candidate", "hybrid_vector_candidate", "embedding_supported_candidate", "near_visual_candidate", "weighted_text_candidate"}:
        return True
    return False


def post_candidate_rescue_match_score(match: PageMatch, config: EngineConfig) -> float:
    priority = float(match.confidence or 0.0) * 10.0
    if match.match_type in {"embedding_similarity_candidate", "hybrid_vector_candidate"}:
        priority += 3.0
    elif match.match_type == "embedding_supported_candidate":
        priority += 2.5
    elif match.match_type == "near_visual_candidate":
        priority += 2.0
    elif match.match_type == "weighted_text_candidate":
        priority += 1.0
    if any(page_has_weak_text_or_ocr(page, config) for page in (match.page_a, match.page_b)):
        priority += 0.5
    return priority

def select_openai_ocr_pages(
    matches: list[PageMatch],
    config: EngineConfig,
    pages: list[PageRecord] | None = None,
) -> list[tuple[PageRecord, str]]:
    """Select pages for OpenAI OCR fallback.

    v0.9.8 keeps the earlier weak/vision page selectors, and adds
    ``reason_balanced``. The balanced mode splits the provider budget across
    explicit vision-fallback pages, weak Tesseract pages, no-text pages, and
    candidate-based pages so one reason bucket cannot consume every OpenAI OCR
    call in an OCR-heavy batch.
    """

    mode = normalize_openai_ocr_selection_mode(config.openai_ocr_selection_mode)
    all_pages = collect_selection_pages(matches, pages)
    if mode == "reason_balanced":
        return select_reason_balanced_openai_ocr_pages(matches, config, all_pages)

    selected: dict[str, tuple[PageRecord, str, float]] = {}

    if mode in {"candidate_based", "weak_pages_or_vision_expected"}:
        add_candidate_based_openai_ocr_pages(selected, matches, config)

    if mode in {"vision_expected", "weak_pages_or_vision_expected"}:
        add_page_based_openai_ocr_pages(
            selected,
            all_pages,
            config,
            mode="vision_expected",
        )

    if mode in {"weak_pages", "weak_pages_or_vision_expected"}:
        add_page_based_openai_ocr_pages(
            selected,
            all_pages,
            config,
            mode="weak_pages",
        )

    ordered = sorted(selected.values(), key=lambda item: item[2], reverse=True)
    return apply_openai_ocr_budget_caps(ordered, config)


def normalize_openai_ocr_selection_mode(value: str) -> str:
    normalized = (value or "reason_balanced").strip().lower().replace("-", "_")
    aliases = {
        "candidate": "candidate_based",
        "candidates": "candidate_based",
        "candidate_based": "candidate_based",
        "weak": "weak_pages",
        "weak_pages": "weak_pages",
        "vision": "vision_expected",
        "vision_expected": "vision_expected",
        "weak_or_vision": "weak_pages_or_vision_expected",
        "weak_pages_or_vision_expected": "weak_pages_or_vision_expected",
        "balanced": "reason_balanced",
        "reason_balanced": "reason_balanced",
        "reason_balanced_budget": "reason_balanced",
    }
    return aliases.get(normalized, "reason_balanced")


def select_reason_balanced_openai_ocr_pages(
    matches: list[PageMatch],
    config: EngineConfig,
    pages: list[PageRecord],
) -> list[tuple[PageRecord, str]]:
    """Select OpenAI OCR pages with reason quotas and global/per-doc caps."""

    max_pages = max(0, config.openai_ocr_max_pages_per_job)
    if max_pages == 0:
        return []

    pools = build_openai_ocr_reason_pools(matches, pages, config)
    quotas = parse_openai_ocr_reason_quotas(config.openai_ocr_reason_quotas, max_pages)
    # Preserve candidate-based rescue for tiny budgets and backwards-compatible
    # one-off calls. If candidate evidence exists but percentage rounding gave
    # it zero slots, borrow one from the largest page-level bucket.
    if pools.get("candidate_based") and quotas.get("candidate_based", 0) == 0 and max_pages > 0:
        donor = max((key for key in quotas if key != "candidate_based"), key=lambda key: quotas.get(key, 0), default=None)
        if donor and quotas.get(donor, 0) > 0:
            quotas[donor] -= 1
        quotas["candidate_based"] = 1
    chosen: dict[str, tuple[PageRecord, str, float]] = {}
    per_document: dict[str, int] = {}

    def try_add(page: PageRecord, reason: str, score: float) -> bool:
        # True quota balancing: once a page is selected for a bucket, preserve
        # that bucket's reason instead of later replacing it with a higher-scored
        # overlapping reason. The audit counts should reflect the reserved quota
        # that selected the page, not merely the highest available reason.
        if page.page_id in chosen:
            return False
        if len(chosen) >= max_pages:
            return False
        doc_key = f"{page.group}:{page.document_name}"
        per_doc_cap = max(0, config.openai_ocr_max_pages_per_document)
        if per_doc_cap and per_document.get(doc_key, 0) >= per_doc_cap:
            page.openai_ocr_skip_reason = "skipped_due_per_document_budget"
            return False
        chosen[page.page_id] = (page, reason, score)
        per_document[doc_key] = per_document.get(doc_key, 0) + 1
        return True

    for bucket in ["candidate_based", "vision_expected", "weak_tesseract", "no_text"]:
        quota = quotas.get(bucket, 0)
        added = 0
        for page, reason, score in sorted(pools.get(bucket, []), key=lambda item: item[2], reverse=True):
            if added >= quota:
                break
            if try_add(page, reason, score):
                added += 1

    # Fill unused quota with the best remaining eligible pages, regardless of bucket.
    remainder: list[tuple[PageRecord, str, float]] = []
    for bucket_items in pools.values():
        remainder.extend(bucket_items)
    for page, reason, score in sorted(remainder, key=lambda item: item[2], reverse=True):
        if len(chosen) >= max_pages:
            break
        try_add(page, reason, score)

    return [(page, reason) for page, reason, _score in sorted(chosen.values(), key=lambda item: item[2], reverse=True)]


def build_openai_ocr_reason_pools(
    matches: list[PageMatch],
    pages: list[PageRecord],
    config: EngineConfig,
) -> dict[str, list[tuple[PageRecord, str, float]]]:
    pools: dict[str, list[tuple[PageRecord, str, float]]] = {
        "vision_expected": [],
        "weak_tesseract": [],
        "no_text": [],
        "candidate_based": [],
    }

    candidate_selected: dict[str, tuple[PageRecord, str, float]] = {}
    add_candidate_based_openai_ocr_pages(candidate_selected, matches, config)
    pools["candidate_based"] = [
        (page, f"candidate_based selection; {reason}", score + 0.2)
        for page, reason, score in candidate_selected.values()
    ]

    for page in pages:
        if not page_needs_openai_ocr(
            page,
            config,
            allow_low_information=config.openai_ocr_allow_low_information_pages,
        ):
            continue
        base_score = page_openai_ocr_selection_score(page, config)
        # Keep the pools broad but quota-reserved. Pages may appear in multiple
        # pools, but the quota allocator keeps the first successful bucket reason
        # so the run budget genuinely samples each failure mode.
        if page_vision_fallback_expected(page, config):
            pools["vision_expected"].append((page, page_based_openai_ocr_reason(page, mode="vision_expected"), base_score + 3.0))
        if page_is_weak_tesseract_for_openai_selection(page, config):
            pools["weak_tesseract"].append((page, page_based_openai_ocr_reason(page, mode="weak_tesseract"), base_score + 2.0))
        if page_is_no_text_for_openai_selection(page, config):
            pools["no_text"].append((page, page_based_openai_ocr_reason(page, mode="no_text"), base_score + 1.5))
    return pools


def parse_openai_ocr_reason_quotas(value: str, max_pages: int) -> dict[str, int]:
    """Parse quota weights/counts for reason-balanced fallback.

    Values are treated as percentages/weights when their sum differs from the
    page budget. If the sum exactly equals ``max_pages``, they are treated as
    absolute counts. Missing buckets receive zero unless leftover rounding fills
    them later from the global remainder.
    """

    allowed = ["vision_expected", "weak_tesseract", "no_text", "candidate_based"]
    raw: dict[str, float] = {}
    for part in (value or "").split(","):
        if not part.strip() or ":" not in part:
            continue
        key, raw_value = part.split(":", 1)
        key = key.strip().lower().replace("-", "_")
        if key not in allowed:
            continue
        try:
            raw[key] = max(0.0, float(raw_value.strip()))
        except ValueError:
            continue
    if not raw:
        raw = {"vision_expected": 30, "weak_tesseract": 30, "no_text": 20, "candidate_based": 20}

    total = sum(raw.values())
    if max_pages <= 0 or total <= 0:
        return {key: 0 for key in allowed}
    if int(total) == max_pages and all(float(value).is_integer() for value in raw.values()):
        quotas = {key: int(raw.get(key, 0)) for key in allowed}
    else:
        fractional = {key: (raw.get(key, 0.0) / total) * max_pages for key in allowed}
        quotas = {key: int(fractional[key]) for key in allowed}
        remainder = max_pages - sum(quotas.values())
        for key, _frac in sorted(fractional.items(), key=lambda item: item[1] - int(item[1]), reverse=True)[:remainder]:
            quotas[key] += 1
    return quotas


def page_explicit_vision_fallback_expected(page: PageRecord) -> bool:
    meta_value = page.meta.get("vision_fallback_expected")
    if isinstance(meta_value, bool):
        return meta_value
    if isinstance(meta_value, str):
        return meta_value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def page_is_no_text_for_openai_selection(page: PageRecord, config: EngineConfig) -> bool:
    return page.best_word_count == 0 or (page.best_text_source == "none" and page.native_text_status == "missing")


def page_is_weak_tesseract_for_openai_selection(page: PageRecord, config: EngineConfig) -> bool:
    if page.tesseract_attempted and not page.tesseract_usable:
        return True
    if page.ocr_route in {"tesseract_weak", "tesseract_unavailable"}:
        return True
    if page.tesseract_confidence is not None and page.tesseract_confidence < config.tesseract_min_confidence:
        return True
    return False


def collect_selection_pages(matches: list[PageMatch], pages: list[PageRecord] | None) -> list[PageRecord]:
    collected: dict[str, PageRecord] = {}
    for page in pages or []:
        collected[page.page_id] = page
    for match in matches:
        collected.setdefault(match.page_a.page_id, match.page_a)
        collected.setdefault(match.page_b.page_id, match.page_b)
    return list(collected.values())


def add_candidate_based_openai_ocr_pages(
    selected: dict[str, tuple[PageRecord, str, float]],
    matches: list[PageMatch],
    config: EngineConfig,
) -> None:
    for match in sorted(matches, key=lambda m: m.confidence, reverse=True):
        if match.confidence < config.openai_ocr_min_candidate_confidence:
            continue
        if match.match_type in {"exact_image_duplicate", "exact_text_duplicate"}:
            continue
        for side, page in (("A", match.page_a), ("B", match.page_b)):
            if not page_needs_openai_ocr(page, config, allow_low_information=False):
                continue
            reason = f"{match.candidate_stage} candidate confidence {match.confidence:.3f}; weak OCR/text on page {side}"
            add_selected_openai_ocr_page(selected, page, reason, 10.0 + match.confidence)


def add_page_based_openai_ocr_pages(
    selected: dict[str, tuple[PageRecord, str, float]],
    pages: list[PageRecord],
    config: EngineConfig,
    *,
    mode: str,
) -> None:
    for page in pages:
        if not page_needs_openai_ocr(
            page,
            config,
            allow_low_information=config.openai_ocr_allow_low_information_pages,
        ):
            continue
        score = page_openai_ocr_selection_score(page, config)
        if mode == "vision_expected" and not page_vision_fallback_expected(page, config):
            continue
        if mode == "weak_pages" and not page_has_weak_text_or_ocr(page, config):
            continue
        reason = page_based_openai_ocr_reason(page, mode=mode)
        add_selected_openai_ocr_page(selected, page, reason, score)


def add_selected_openai_ocr_page(
    selected: dict[str, tuple[PageRecord, str, float]],
    page: PageRecord,
    reason: str,
    score: float,
) -> None:
    previous = selected.get(page.page_id)
    if previous is None or score > previous[2]:
        selected[page.page_id] = (page, reason, score)



def openai_ocr_min_usable_words(config: EngineConfig) -> int:
    base = max(8, min(config.native_min_usable_words, config.tesseract_min_words))
    if config.openai_ocr_evidence_upgrade_enabled:
        return max(5, min(base, 12))
    return base


def openai_ocr_is_usable(text: str, config: EngineConfig) -> bool:
    if word_count(text, config) >= openai_ocr_min_usable_words(config):
        return True
    if config.openai_ocr_key_token_acceptance or config.openai_ocr_evidence_upgrade_enabled:
        return ocr_key_token_count(text) >= config.openai_ocr_min_key_tokens
    return False


def ocr_key_tokens(text: str) -> set[str]:
    raw = text or ""
    tokens: set[str] = set()
    # Dates / month-year references / useful identifiers. We keep only counts
    # and hashed evidence in reports, never raw OCR snippets by default.
    patterns = [
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}\b",
        r"\b(?:case|claim|member|patient|record|reference|invoice|receipt|document|dob|mrn)\s*(?:no\.?|number|id|#|:)\s*[a-z0-9-]{3,}\b",
        r"\b[a-z]{2,5}-\d{3,}\b",
        r"\b\d{3}-\d{2}-\d{4}\b",
        r"\b\d{5,}\b",
    ]
    lower = raw.lower()
    for pattern in patterns:
        for match in re.findall(pattern, lower, flags=re.IGNORECASE):
            value = match if isinstance(match, str) else " ".join(match)
            cleaned = re.sub(r"\s+", " ", value.strip().lower())
            if cleaned:
                tokens.add(cleaned[:80])
    # Domain-bearing field labels are useful even when the page is short.
    for label in ["claimant", "case number", "member id", "hearing", "provider", "diagnosis", "treatment", "receipt", "benefit", "determination"]:
        if label in lower:
            tokens.add(label)
    return tokens


def ocr_key_token_count(text: str) -> int:
    return len(ocr_key_tokens(text))


def ocr_key_token_density(text: str, config: EngineConfig) -> float:
    chars = max(1, len(text or ""))
    return round(ocr_key_token_count(text) / chars, 5)


def build_openai_ocr_evidence_text(page: PageRecord, openai_text: str, config: EngineConfig) -> str:
    if not (config.openai_ocr_combine_text_evidence or config.openai_ocr_evidence_upgrade_enabled):
        return openai_text or ""
    parts: list[str] = []
    for label, text in [
        ("openai", openai_text),
        ("tesseract", page.tesseract_text),
        ("native", page.native_text),
        ("previous_best", page.raw_text),
    ]:
        cleaned = (text or "").strip()
        if not cleaned:
            continue
        normalized = re.sub(r"\s+", " ", cleaned)
        if normalized not in parts:
            parts.append(normalized)
    return "\n".join(parts) if parts else (openai_text or "")


def apply_openai_ocr_evidence_text(page: PageRecord, openai_text: str, confidence: float | None, config: EngineConfig) -> None:
    evidence_text = build_openai_ocr_evidence_text(page, openai_text, config)
    metadata = {
        "enabled": bool(config.openai_ocr_evidence_upgrade_enabled),
        "combined_text_available": bool(config.openai_ocr_combine_text_evidence or config.openai_ocr_evidence_upgrade_enabled),
        "openai_word_count": word_count(openai_text, config),
        "evidence_word_count": word_count(evidence_text, config),
        "key_token_count": ocr_key_token_count(openai_text),
        "key_token_density": ocr_key_token_density(openai_text, config),
    }
    if config.openai_ocr_evidence_upgrade_enabled:
        page.meta["openai_ocr_evidence_upgrade"] = metadata

    page.ocr_confidence = confidence

    if config.source_safe_ocr_merge_enabled:
        # v0.10.1: OpenAI OCR is normally sidecar evidence for candidate
        # formation. Do not overwrite useful canonical native/Tesseract text.
        #
        # v0.10.8 repair: if the canonical matching view is empty, promote
        # accepted OpenAI OCR into the canonical view. Otherwise OCR-dependent
        # pages can show ocr_route=openai_ocr_fallback and usable provider text,
        # while still participating in matching as text_source=none/best_words=0.
        page.ocr_text = page.tesseract_text or page.ocr_text or ""
        page.ocr_word_count = max(page.ocr_word_count, page.openai_ocr_word_count, word_count(page.ocr_text, config))

        canonical_words = int(page.best_word_count or 0)
        canonical_source = (page.best_text_source or page.text_source or "none").strip().lower()
        should_promote_empty_canonical = (
            bool((openai_text or "").strip())
            and metadata["openai_word_count"] > 0
            and (
                canonical_words <= 0
                or canonical_source in {"", "none", "missing"}
                or not (page.raw_text or "").strip()
            )
        )

        if should_promote_empty_canonical:
            page.ocr_text = evidence_text
            update_best_text(page, evidence_text, "openai_ocr", config)
            page.meta["openai_ocr_empty_canonical_promoted"] = {
                "enabled": True,
                "previous_best_text_source": canonical_source,
                "previous_best_word_count": canonical_words,
                "openai_word_count": metadata["openai_word_count"],
                "evidence_word_count": metadata["evidence_word_count"],
                "reason": "source_safe_openai_ocr_promoted_because_canonical_text_was_empty",
            }
            canonical_preserved = False
        else:
            canonical_preserved = True

        page.meta["source_safe_ocr_merge"] = {
            "enabled": True,
            "openai_sidecar_available": bool((openai_text or "").strip()),
            "canonical_text_preserved": canonical_preserved,
            "canonical_best_text_source": page.best_text_source,
            "canonical_best_word_count": page.best_word_count,
            "openai_word_count": metadata["openai_word_count"],
            "evidence_word_count": metadata["evidence_word_count"],
            "key_token_count": metadata["key_token_count"],
            "empty_canonical_promoted": should_promote_empty_canonical,
        }
        return

    page.ocr_text = evidence_text
    update_best_text(page, evidence_text, "openai_ocr", config)

def ocr_text_quality_score(text: str, config: EngineConfig) -> float:
    """Conservative OCR evidence quality score used for rescue acceptance."""

    raw = text or ""
    tokens = tokenize_for_similarity(raw, config.domain_stopwords)
    if not tokens:
        return 0.0
    unique_tokens = len(set(tokens))
    alpha_words = len(re.findall(r"\b[a-zA-Z]{3,}\b", raw))
    digit_heavy = sum(1 for token in re.findall(r"\S+", raw) if sum(ch.isdigit() for ch in token) > max(2, len(token) // 2))
    artifact_words = sum(1 for token in re.findall(r"\S+", raw) if len(token) >= 8 and not re.search(r"[aeiouAEIOU]", token))
    return round(len(tokens) + unique_tokens * 0.6 + alpha_words * 0.25 - digit_heavy * 0.4 - artifact_words * 0.5, 4)


def should_accept_openai_ocr_result(page: PageRecord, text: str, config: EngineConfig) -> tuple[bool, str, dict[str, float | int | str]]:
    """Accept OpenAI OCR when it gives cleaner usable evidence, even if shorter."""

    candidate_words = word_count(text, config)
    min_words = openai_ocr_min_usable_words(config)
    current_quality = ocr_text_quality_score(page.raw_text, config)
    candidate_quality = ocr_text_quality_score(text, config)
    current_words = word_count(page.raw_text, config)
    quality_delta = candidate_quality - current_quality
    word_delta = candidate_words - current_words
    key_token_count = ocr_key_token_count(text)
    key_token_density = ocr_key_token_density(text, config)
    metadata = {
        "candidate_words": candidate_words,
        "current_words": current_words,
        "candidate_quality": candidate_quality,
        "current_quality": current_quality,
        "quality_delta": round(quality_delta, 4),
        "word_delta": word_delta,
        "key_token_count": key_token_count,
        "key_token_density": key_token_density,
        "evidence_upgrade_enabled": bool(config.openai_ocr_evidence_upgrade_enabled),
    }
    if candidate_words < min_words:
        if (config.openai_ocr_key_token_acceptance or config.openai_ocr_evidence_upgrade_enabled) and key_token_count >= config.openai_ocr_min_key_tokens and key_token_density >= config.openai_ocr_min_key_token_density:
            return True, "openai_ocr_key_token_evidence_text", metadata
        return False, "openai_ocr_not_usable_text", metadata
    if candidate_words > current_words:
        return True, "openai_ocr_longer_usable_text", metadata
    if config.openai_ocr_accept_cleaner_shorter_text and quality_delta >= 2.0:
        return True, "openai_ocr_cleaner_usable_text", metadata
    if config.openai_ocr_accept_cleaner_shorter_text and quality_delta >= 0.75 and candidate_words >= max(min_words, int(current_words * 0.75)):
        return True, "openai_ocr_shorter_but_cleaner_text", metadata
    if config.openai_ocr_evidence_upgrade_enabled and key_token_count >= config.openai_ocr_min_key_tokens and quality_delta >= -0.25:
        return True, "openai_ocr_key_token_supported_text", metadata
    return False, "openai_ocr_not_better_than_current_evidence", metadata


def page_based_openai_ocr_reason(page: PageRecord, *, mode: str) -> str:
    route = page.ocr_route or "unknown_route"
    best_words = page.best_word_count
    tesseract_words = page.tesseract_word_count
    confidence = page.tesseract_confidence
    vision = page.meta.get("vision_fallback_expected")
    parts = [f"{mode} selection", f"ocr_route={route}", f"best_words={best_words}", f"tesseract_words={tesseract_words}"]
    if confidence is not None:
        parts.append(f"tesseract_confidence={confidence:.1f}")
    if vision is not None:
        parts.append(f"vision_fallback_expected={bool(vision)}")
    if page.is_low_information:
        parts.append(f"low_information={page.low_information_reason or 'true'}")
    return "; ".join(parts)


def apply_openai_ocr_budget_caps(
    ordered: list[tuple[PageRecord, str, float]],
    config: EngineConfig,
) -> list[tuple[PageRecord, str]]:
    """Apply global and per-document caps after scoring all eligible pages."""

    max_pages = max(0, config.openai_ocr_max_pages_per_job)
    per_doc_cap = max(0, config.openai_ocr_max_pages_per_document)
    if max_pages == 0:
        return []

    chosen: list[tuple[PageRecord, str]] = []
    per_document: dict[str, int] = {}
    for page, reason, _score in ordered:
        doc_key = f"{page.group}:{page.document_name}"
        if per_doc_cap and per_document.get(doc_key, 0) >= per_doc_cap:
            page.openai_ocr_skip_reason = "skipped_due_per_document_budget"
            continue
        chosen.append((page, reason))
        per_document[doc_key] = per_document.get(doc_key, 0) + 1
        if len(chosen) >= max_pages:
            break
    return chosen


def page_openai_ocr_selection_score(page: PageRecord, config: EngineConfig) -> float:
    score = 0.0
    explicit_vision = page.meta.get("vision_fallback_expected") is True
    if explicit_vision:
        score += 2.0
    elif page_vision_fallback_expected(page, config):
        score += 1.0
    if page.ocr_route in {"tesseract_weak", "tesseract_unavailable"}:
        score += 0.9
    if page.native_text_status == "missing":
        score += 0.55
    elif page.native_text_status == "weak":
        score += 0.35
    if page.tesseract_attempted and not page.tesseract_usable:
        score += 0.35
    if page.tesseract_confidence is not None:
        score += max(0.0, min(config.tesseract_min_confidence, config.tesseract_min_confidence - page.tesseract_confidence)) / 100.0
    if page.best_text_source in {"none", "native"}:
        score += 0.25
    if page.best_word_count == 0:
        score += 0.20
    elif page.best_word_count <= config.low_information_word_count:
        score += 0.05
    # Strongly de-prioritize blank/header-only pages so tied budgets do not get
    # consumed by low-information pages before real OCR rescue candidates.
    if page.is_low_information and config.openai_ocr_low_information_penalty:
        score -= 0.65
    # Stable deterministic tie-break without favoring just page number.
    tie_seed = abs(hash(page.page_id)) % 10000
    score += tie_seed / 100_000_000
    return score


def page_vision_fallback_expected(page: PageRecord, config: EngineConfig) -> bool:
    meta_value = page.meta.get("vision_fallback_expected")
    if isinstance(meta_value, bool):
        return meta_value
    if isinstance(meta_value, str) and meta_value.strip().lower() in {"1", "true", "yes", "y", "on"}:
        return True
    if page.ocr_route in {"tesseract_weak", "tesseract_unavailable"}:
        return True
    if page.tesseract_attempted and not page.tesseract_usable:
        return True
    if page.tesseract_confidence is not None and page.tesseract_confidence < config.tesseract_min_confidence:
        return True
    return False


def page_has_weak_text_or_ocr(page: PageRecord, config: EngineConfig) -> bool:
    if page.native_text_status in {"missing", "weak"}:
        return True
    if page.ocr_route in {"native_weak", "tesseract_weak", "tesseract_unavailable"}:
        return True
    if page.best_word_count < min(config.native_min_usable_words, config.tesseract_min_words):
        return True
    if page.best_text_source in {"none", "native"} and page.tesseract_attempted and not page.tesseract_usable:
        return True
    return False


def page_needs_openai_ocr(page: PageRecord, config: EngineConfig, *, allow_low_information: bool = False) -> bool:
    if page.is_low_information and not allow_low_information:
        return False
    if page.openai_ocr_attempted or page.openai_ocr_usable:
        return False
    if page.native_text_status == "usable":
        return False
    if config.openai_ocr_require_tesseract_first and not page.tesseract_attempted:
        if page.ocr_route != "tesseract_unavailable":
            return False
    if page.tesseract_usable:
        return False
    return True
