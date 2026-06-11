from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Iterable

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .config import EngineConfig
from .hashing import hamming_distance, sha256_bytes
from .models import DeterministicPassRecord, EscalationDecision, MatchSignal, PageMatch, PageRecord
from .page_quality import should_suppress_low_information_match
from .review import annotate_match_for_review, visibility_rank
from .text import normalize_text_for_hash, normalize_text_for_similarity, substantial_text, tokenize_for_similarity


STAGE_PRIORITY = {
    "single_threshold": 0,
    "deterministic_loose": 1,
    "embedding_recall": 1,
    "vector_recall": 1,
    "deterministic_standard": 2,
    "deterministic_strict": 3,
    "deterministic_exact": 4,
}


def compare_groups(pages_a: list[PageRecord], pages_b: list[PageRecord], config: EngineConfig) -> list[PageMatch]:
    """Compare Group A pages against Group B pages."""

    if config.enable_multipass:
        return compare_groups_multipass(pages_a, pages_b, config)

    raw_matches: list[PageMatch] = []
    raw_matches.extend(exact_image_matches(pages_a, pages_b))
    raw_matches.extend(exact_text_matches(pages_a, pages_b, config))
    raw_matches.extend(perceptual_image_matches(pages_a, pages_b, config))
    raw_matches.extend(weighted_text_matches(pages_a, pages_b, config))
    merged = merge_pair_matches(raw_matches, unordered=False, config=config)
    return apply_candidate_controls(merged, config)


def compare_all_pages(pages: list[PageRecord], config: EngineConfig) -> list[PageMatch]:
    """Compare all pages in one corpus, excluding self-pairs and duplicate reverse pairs."""

    raw_matches = compare_groups(pages, pages, config)
    filtered: list[PageMatch] = []
    seen: set[tuple[str, str]] = set()
    for match in raw_matches:
        if match.page_a.page_id == match.page_b.page_id:
            continue
        key = match.pair_key_unordered
        if key in seen:
            continue
        seen.add(key)
        filtered.append(match)
    filtered.sort(key=lambda m: m.confidence, reverse=True)
    return filtered


# ---------------------------------------------------------------------------
# v0.4 deterministic multi-pass candidate generation
# ---------------------------------------------------------------------------


def compare_groups_multipass(pages_a: list[PageRecord], pages_b: list[PageRecord], config: EngineConfig) -> list[PageMatch]:
    """Generate candidates using exact/strict/standard/loose deterministic bands.

    The bands are not independent votes. They preserve evidence strength so the
    engine can lower thresholds for recall while keeping escalation decisions
    transparent. v0.10.1 adds source-safe OCR views and a bounded sequence
    neighbor promotion pass before review-volume controls are applied.
    """

    raw_matches: list[PageMatch] = []
    raw_matches.extend(exact_image_matches(pages_a, pages_b))
    raw_matches.extend(exact_text_matches(pages_a, pages_b, config))
    raw_matches.extend(multipass_visual_matches(pages_a, pages_b, config))
    raw_matches.extend(multipass_text_matches(pages_a, pages_b, config))
    merged = merge_pair_matches(raw_matches, unordered=False, config=config)
    if config.sequence_candidate_promotion_enabled:
        sequence_matches = sequence_neighbor_matches(merged, pages_a, pages_b, config)
        if sequence_matches:
            merged = merge_pair_matches([*merged, *sequence_matches], unordered=False, config=config)
    return apply_candidate_controls(merged, config)


def multipass_visual_matches(pages_a: list[PageRecord], pages_b: list[PageRecord], config: EngineConfig) -> list[PageMatch]:
    # Strict visual candidates can run across all pages. Standard/loose visual
    # candidates remain bounded to text-poor or OCR-weak pages so a visual pass
    # can rescue scan/layout cases without becoming visual all-pairs.
    candidate_a = visual_candidate_pages(pages_a, config)
    candidate_b = visual_candidate_pages(pages_b, config)

    matches: list[PageMatch] = []
    for page_a in candidate_a:
        if not page_a.perceptual_hash:
            continue
        for page_b in candidate_b:
            if page_a.page_id == page_b.page_id or not page_b.perceptual_hash:
                continue
            if config.suppress_low_information_candidates and pages_low_information_for_generation(page_a, page_b, config):
                continue
            try:
                dist = hamming_distance(page_a.perceptual_hash, page_b.perceptual_hash)
            except ValueError:
                continue
            page_a_text_poor = page_is_text_poor(page_a, config)
            page_b_text_poor = page_is_text_poor(page_b, config)
            page_a_ocr_weak = page_has_ocr_weak_evidence(page_a, config)
            page_b_ocr_weak = page_has_ocr_weak_evidence(page_b, config)
            if dist > config.loose_phash_threshold:
                continue
            if dist > config.strict_phash_threshold and not (
                (page_a_text_poor and page_b_text_poor) or (page_a_ocr_weak and page_b_ocr_weak)
            ):
                continue
            pass_records = visual_pass_records(dist, config)
            stage = stage_from_pass_records(pass_records)
            score = round(max(0.0, 1.0 - (dist / 64.0)), 4)
            matches.append(
                PageMatch(
                    match_type="near_visual_candidate",
                    confidence=round(min(0.96, score), 4),
                    page_a=page_a,
                    page_b=page_b,
                    signals=[
                        MatchSignal(
                            "perceptual_hash",
                            score,
                            {
                                "hamming_distance": dist,
                                "candidate_stage": stage,
                                "bounded_reason": visual_candidate_reason(page_a, page_b, config),
                            },
                        )
                    ],
                    recommendation="review",
                    candidate_stage=stage,
                    deterministic_passes=pass_records,
                )
            )
    return matches


def multipass_text_matches(pages_a: list[PageRecord], pages_b: list[PageRecord], config: EngineConfig) -> list[PageMatch]:
    if not config.multiview_text_candidates_enabled:
        return multipass_text_matches_for_view(pages_a, pages_b, config, "primary_text")

    matches: list[PageMatch] = []
    for view_name in TEXT_VIEW_ORDER:
        matches.extend(multipass_text_matches_for_view(pages_a, pages_b, config, view_name))
    if config.multiview_cross_text_candidates_enabled:
        matches.extend(cross_view_text_matches(pages_a, pages_b, config))
    if config.multiview_key_token_candidates_enabled:
        matches.extend(key_token_overlap_matches(pages_a, pages_b, config))
    if config.rare_token_candidates_enabled:
        matches.extend(rare_token_block_matches(pages_a, pages_b, config))
    return matches


TEXT_VIEW_ORDER = ("primary_text", "native_text", "tesseract_text", "openai_ocr_text", "combined_text")
CROSS_TEXT_VIEW_PAIRS = (
    ("native_text", "tesseract_text"),
    ("tesseract_text", "native_text"),
    ("native_text", "openai_ocr_text"),
    ("openai_ocr_text", "native_text"),
    ("tesseract_text", "openai_ocr_text"),
    ("openai_ocr_text", "tesseract_text"),
    ("primary_text", "openai_ocr_text"),
    ("openai_ocr_text", "primary_text"),
)


def visual_candidate_pages(pages: list[PageRecord], config: EngineConfig) -> list[PageRecord]:
    if config.multipass_visual_all_pages:
        return pages
    return [
        page
        for page in pages
        if page_is_text_poor(page, config)
        or (config.bounded_visual_ocr_weak_enabled and page_has_ocr_weak_evidence(page, config))
    ]


def page_is_text_poor(page: PageRecord, config: EngineConfig) -> bool:
    return len(tokenize_for_similarity(page.comparison_text or page.raw_text or page.best_text, config.domain_stopwords)) < config.text_poor_word_count


def page_has_ocr_weak_evidence(page: PageRecord, config: EngineConfig) -> bool:
    if page.native_text_status in {"missing", "weak"}:
        return True
    if page.ocr_route in {"native_weak", "tesseract_weak", "tesseract_unavailable"}:
        return True
    if page.tesseract_attempted and not page.tesseract_usable:
        return True
    if page.best_word_count and page.best_word_count < min(config.native_min_usable_words, config.tesseract_min_words):
        return True
    return False



def pages_low_information_for_generation(page_a: PageRecord, page_b: PageRecord, config: EngineConfig) -> bool:
    return page_low_information_for_generation(page_a, config) or page_low_information_for_generation(page_b, config)


def page_low_information_for_generation(page: PageRecord, config: EngineConfig) -> bool:
    if not page.is_low_information:
        return False
    source_text = "\n".join([page.tesseract_text or "", page.openai_ocr_text or "", page.native_text or ""])
    if len(tokenize_for_similarity(source_text, config.domain_stopwords)) >= max(3, config.low_information_word_count):
        return False
    if len(source_key_tokens(page)) >= config.multiview_key_token_min_overlap:
        return False
    return True

def visual_candidate_reason(page_a: PageRecord, page_b: PageRecord, config: EngineConfig) -> str:
    reasons: list[str] = []
    if page_is_text_poor(page_a, config) and page_is_text_poor(page_b, config):
        reasons.append("text_poor_pair")
    if page_has_ocr_weak_evidence(page_a, config) and page_has_ocr_weak_evidence(page_b, config):
        reasons.append("ocr_weak_pair")
    return "+".join(reasons) if reasons else "strict_visual"


def page_text_views(page: PageRecord, config: EngineConfig) -> dict[str, str]:
    """Return source-safe text views for candidate formation.

    The returned values are generated on demand from per-source PageRecord fields
    and are not serialized into page metadata, avoiding a second PHI persistence
    path. `primary_text` remains the canonical engine text; OpenAI OCR stays a
    sidecar unless explicitly promoted elsewhere.
    """

    views: dict[str, str] = {}
    normalized_seen: set[str] = set()

    def add_view(name: str, text: str, *, allow_duplicate: bool = False) -> None:
        cleaned = normalize_text_for_similarity(text or "")
        if not cleaned:
            return
        if not allow_duplicate and cleaned in normalized_seen:
            return
        views[name] = cleaned
        normalized_seen.add(cleaned)

    add_view("primary_text", page.comparison_text or page.raw_text or page.best_text)
    add_view("native_text", page.native_text)
    add_view("tesseract_text", page.tesseract_text)
    add_view("openai_ocr_text", page.openai_ocr_text)

    combined = build_combined_source_text(page, config)
    if combined:
        primary_tokens = set(tokenize_for_similarity(views.get("primary_text", ""), config.domain_stopwords))
        combined_tokens = set(tokenize_for_similarity(combined, config.domain_stopwords))
        extra_tokens = combined_tokens - primary_tokens
        if len(extra_tokens) >= config.multiview_combined_min_extra_tokens:
            add_view("combined_text", combined, allow_duplicate=False)
    return views


def build_combined_source_text(page: PageRecord, config: EngineConfig) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for text in [page.raw_text, page.native_text, page.tesseract_text, page.openai_ocr_text, page.best_text]:
        cleaned = normalize_text_for_similarity(text or "")
        if not cleaned or cleaned in seen:
            continue
        parts.append(cleaned)
        seen.add(cleaned)
    return "\n".join(parts)


def page_text_view(page: PageRecord, view_name: str, config: EngineConfig) -> str:
    if view_name == "primary_text":
        return normalize_text_for_similarity(page.comparison_text or page.raw_text or page.best_text)
    if view_name == "native_text":
        return normalize_text_for_similarity(page.native_text)
    if view_name == "tesseract_text":
        return normalize_text_for_similarity(page.tesseract_text)
    if view_name == "openai_ocr_text":
        return normalize_text_for_similarity(page.openai_ocr_text)
    if view_name == "combined_text":
        return page_text_views(page, config).get("combined_text", "")
    return ""


def cross_view_text_matches(pages_a: list[PageRecord], pages_b: list[PageRecord], config: EngineConfig) -> list[PageMatch]:
    """Generate bounded TF-IDF candidates across different source text views.

    v0.10.1 compared each source view only against the same view on the other
    side. That misses pairs where one page has good native text and the other
    only has useful Tesseract/OpenAI sidecar text. This pass keeps the same
    loose TF-IDF threshold and top-k caps, but tests only OCR-relevant view
    pairs instead of every possible view combination.
    """

    matches: list[PageMatch] = []
    for view_a, view_b in CROSS_TEXT_VIEW_PAIRS:
        matches.extend(multipass_text_matches_for_views(pages_a, pages_b, config, view_a, view_b))
    return matches


def multipass_text_matches_for_view(
    pages_a: list[PageRecord],
    pages_b: list[PageRecord],
    config: EngineConfig,
    view_name: str,
) -> list[PageMatch]:
    return multipass_text_matches_for_views(pages_a, pages_b, config, view_name, view_name)


def multipass_text_matches_for_views(
    pages_a: list[PageRecord],
    pages_b: list[PageRecord],
    config: EngineConfig,
    view_a_name: str,
    view_b_name: str,
) -> list[PageMatch]:
    page_text_a = [(page, page_text_view(page, view_a_name, config)) for page in pages_a]
    page_text_b = [(page, page_text_view(page, view_b_name, config)) for page in pages_b]
    text_pages_a = [(page, text) for page, text in page_text_a if substantial_text(text, stopwords=config.domain_stopwords)]
    text_pages_b = [(page, text) for page, text in page_text_b if substantial_text(text, stopwords=config.domain_stopwords)]

    if not text_pages_a or not text_pages_b:
        return []

    all_texts = [text for _page, text in text_pages_a] + [text for _page, text in text_pages_b]

    vectorizer = TfidfVectorizer(
        tokenizer=lambda value: tokenize_for_similarity(value, config.domain_stopwords),
        token_pattern=None,
        lowercase=False,
        ngram_range=(1, 2),
        min_df=1,
        max_df=config.tfidf_max_df,
        sublinear_tf=True,
        norm="l2",
    )

    try:
        matrix = vectorizer.fit_transform(all_texts)
    except ValueError:
        return []
    matrix_a = matrix[: len(text_pages_a)]
    matrix_b = matrix[len(text_pages_a) :]
    sim = cosine_similarity(matrix_a, matrix_b)

    matches: list[PageMatch] = []
    same_view = view_a_name == view_b_name
    signal_name = text_candidate_signal_name(view_a_name if same_view else f"{view_a_name}_x_{view_b_name}")
    text_view_detail = view_a_name if same_view else f"{view_a_name}->{view_b_name}"
    for i, (page_a, _text_a) in enumerate(text_pages_a):
        candidates: list[tuple[int, float]] = []
        for j, score in enumerate(sim[i]):
            score_float = float(score)
            if score_float >= config.loose_tfidf_threshold:
                candidates.append((j, score_float))

        candidates.sort(key=lambda item: item[1], reverse=True)
        for j, score in candidates[: config.multipass_text_top_k]:
            page_b = text_pages_b[j][0]
            if page_a.page_id == page_b.page_id:
                continue
            if config.suppress_low_information_candidates and pages_low_information_for_generation(page_a, page_b, config):
                continue
            pass_records = text_pass_records(score, config, text_view=text_view_detail)
            if page_a.perceptual_hash and page_b.perceptual_hash:
                try:
                    visual_dist = hamming_distance(page_a.perceptual_hash, page_b.perceptual_hash)
                    if visual_dist <= config.loose_phash_threshold:
                        pass_records.extend(visual_pass_records(visual_dist, config))
                except ValueError:
                    pass
            stage = stage_from_pass_records(pass_records)
            matches.append(
                PageMatch(
                    match_type="weighted_text_candidate",
                    confidence=round(min(0.97, score), 4),
                    page_a=page_a,
                    page_b=page_b,
                    signals=[
                        MatchSignal(
                            signal_name,
                            score,
                            {
                                "candidate_stage": stage,
                                "text_view": text_view_detail,
                                "text_view_a": view_a_name,
                                "text_view_b": view_b_name,
                                "cross_view": not same_view,
                            },
                        )
                    ],
                    recommendation="review",
                    candidate_stage=stage,
                    deterministic_passes=pass_records,
                )
            )
    return matches


def text_candidate_signal_name(view_name: str) -> str:
    if view_name == "primary_text":
        return "tfidf_cosine_similarity"
    return f"tfidf_{view_name}_similarity"


def key_token_overlap_matches(pages_a: list[PageRecord], pages_b: list[PageRecord], config: EngineConfig) -> list[PageMatch]:
    tokens_a = [(page, source_key_tokens(page)) for page in pages_a]
    tokens_b = [(page, source_key_tokens(page)) for page in pages_b]
    matches: list[PageMatch] = []
    for page_a, set_a in tokens_a:
        if len(set_a) < config.multiview_key_token_min_overlap:
            continue
        for page_b, set_b in tokens_b:
            if page_a.page_id == page_b.page_id:
                continue
            if len(set_b) < config.multiview_key_token_min_overlap:
                continue
            if config.suppress_low_information_candidates and pages_low_information_for_generation(page_a, page_b, config):
                continue
            overlap = set_a & set_b
            union = set_a | set_b
            if not union:
                continue
            jaccard = len(overlap) / len(union)
            if len(overlap) < config.multiview_key_token_min_overlap or jaccard < config.multiview_key_token_min_jaccard:
                continue
            score = round(min(0.92, 0.56 + len(overlap) * 0.08 + jaccard * 0.22), 4)
            pass_records = key_token_pass_records(score, len(overlap), jaccard, config)
            stage = stage_from_pass_records(pass_records)
            matches.append(
                PageMatch(
                    match_type="key_token_text_candidate",
                    confidence=score,
                    page_a=page_a,
                    page_b=page_b,
                    signals=[
                        MatchSignal(
                            "key_token_overlap",
                            score,
                            {
                                "candidate_stage": stage,
                                "overlap_count": len(overlap),
                                "jaccard": round(jaccard, 4),
                                "source": "source_safe_key_tokens",
                            },
                        )
                    ],
                    recommendation="review",
                    candidate_stage=stage,
                    deterministic_passes=pass_records,
                )
            )
    return matches



def rare_token_block_matches(pages_a: list[PageRecord], pages_b: list[PageRecord], config: EngineConfig) -> list[PageMatch]:
    """Emit bounded candidates from rare OCR/native tokens.

    This is a blocking pass, not a fuzzy all-pairs pass. It indexes uncommon
    identifier-like and long content tokens across the two page sets, then only
    scores pairs that share enough rare evidence. It is designed for OCR-ready
    misses where useful sidecar text exists but same-view TF-IDF did not route
    the pair.
    """

    token_sets_a = [(page, source_rare_tokens(page, config)) for page in pages_a]
    token_sets_b = [(page, source_rare_tokens(page, config)) for page in pages_b]
    df: Counter[str] = Counter()
    for _page, tokens in [*token_sets_a, *token_sets_b]:
        df.update(tokens)

    filtered_b: dict[str, set[str]] = {}
    index_b: dict[str, list[PageRecord]] = defaultdict(list)
    for page, tokens in token_sets_b:
        filtered = {token for token in tokens if 0 < df[token] <= config.rare_token_max_df}
        filtered_b[page.page_id] = filtered
        if len(filtered) < config.rare_token_min_overlap:
            continue
        for token in filtered:
            index_b[token].append(page)

    matches: list[PageMatch] = []
    per_page_limit = max(config.multipass_text_top_k * 2, 8)
    for page_a, tokens in token_sets_a:
        filtered_a = {token for token in tokens if 0 < df[token] <= config.rare_token_max_df}
        if len(filtered_a) < config.rare_token_min_overlap:
            continue
        overlap_counts: Counter[str] = Counter()
        page_lookup: dict[str, PageRecord] = {}
        for token in filtered_a:
            for page_b in index_b.get(token, []):
                if page_a.page_id == page_b.page_id:
                    continue
                overlap_counts[page_b.page_id] += 1
                page_lookup[page_b.page_id] = page_b
        ranked = sorted(overlap_counts.items(), key=lambda item: item[1], reverse=True)[:per_page_limit]
        for page_b_id, overlap_count in ranked:
            if overlap_count < config.rare_token_min_overlap:
                continue
            page_b = page_lookup[page_b_id]
            if config.suppress_low_information_candidates and pages_low_information_for_generation(page_a, page_b, config):
                continue
            set_b = filtered_b.get(page_b.page_id, set())
            if not set_b:
                continue
            overlap = filtered_a & set_b
            union = filtered_a | set_b
            jaccard = len(overlap) / len(union) if union else 0.0
            dice = token_dice(filtered_a, set_b)
            key_overlap = len(source_key_tokens(page_a) & source_key_tokens(page_b))
            visual_support = False
            visual_score = 0.0
            visual_distance: int | None = None
            if page_a.perceptual_hash and page_b.perceptual_hash:
                try:
                    visual_distance = hamming_distance(page_a.perceptual_hash, page_b.perceptual_hash)
                    visual_score = max(0.0, 1.0 - (visual_distance / 64.0))
                    visual_support = visual_distance <= config.sequence_visual_support_phash_threshold
                except ValueError:
                    visual_distance = None
            if jaccard < config.rare_token_min_jaccard and key_overlap < config.multiview_key_token_min_overlap and not visual_support:
                continue
            score = rare_token_score(len(overlap), jaccard, dice, key_overlap, visual_score if visual_support else 0.0)
            pass_records = rare_token_pass_records(score, len(overlap), jaccard, dice, key_overlap, config)
            if visual_support and visual_distance is not None:
                pass_records.extend(visual_pass_records(visual_distance, config))
            stage = stage_from_pass_records(pass_records)
            matches.append(
                PageMatch(
                    match_type="rare_token_candidate",
                    confidence=score,
                    page_a=page_a,
                    page_b=page_b,
                    signals=[
                        MatchSignal(
                            "rare_source_token_overlap",
                            score,
                            {
                                "candidate_stage": stage,
                                "overlap_count": len(overlap),
                                "jaccard": round(jaccard, 4),
                                "dice": round(dice, 4),
                                "key_token_overlap": key_overlap,
                                "visual_support": visual_support,
                                "visual_distance": visual_distance if visual_distance is not None else "",
                            },
                        )
                    ],
                    recommendation="review",
                    candidate_stage=stage,
                    deterministic_passes=pass_records,
                )
            )
    return matches


def source_rare_tokens(page: PageRecord, config: EngineConfig) -> set[str]:
    # Keep this pass source-safe and OCR-focused. Avoid falling back to generic
    # raw/best text here, otherwise rare-token blocking can bypass TF-IDF
    # pruning tests and recreate broad text matching under another name.
    parts = [page.native_text, page.tesseract_text, page.openai_ocr_text]
    text = "\n".join(part for part in parts if part)
    if not text.strip():
        return set()
    normalized = normalize_text_for_similarity(text)
    tokens = set()
    for token in re.findall(r"\b[a-z0-9][a-z0-9.-]{2,}\b", normalized):
        cleaned = token.strip(".-")
        if not cleaned or cleaned in config.domain_stopwords:
            continue
        if len(cleaned) >= config.rare_token_min_length or any(ch.isdigit() for ch in cleaned):
            tokens.add(cleaned[:80])
    tokens.update(source_key_tokens(page))
    return tokens


def rare_token_score(overlap_count: int, jaccard: float, dice: float, key_overlap: int, visual_score: float) -> float:
    score = 0.50 + min(overlap_count, 8) * 0.045 + jaccard * 0.18 + dice * 0.14 + min(key_overlap, 4) * 0.025 + visual_score * 0.04
    return round(min(0.91, max(0.58, score)), 4)


def rare_token_pass_records(
    score: float,
    overlap_count: int,
    jaccard: float,
    dice: float,
    key_overlap: int,
    config: EngineConfig,
) -> list[DeterministicPassRecord]:
    details = {
        "overlap_count": overlap_count,
        "jaccard": round(jaccard, 4),
        "dice": round(dice, 4),
        "key_token_overlap": key_overlap,
    }
    return [
        DeterministicPassRecord(
            pass_name="standard_rare_tokens",
            layer="source_safe_rare_tokens",
            matched=overlap_count >= max(config.rare_token_min_overlap + 2, 5) and jaccard >= max(config.rare_token_min_jaccard, 0.30),
            score=score,
            threshold=max(config.rare_token_min_jaccard, 0.30),
            metric="rare_token_jaccard_gte",
            details=details,
        ),
        DeterministicPassRecord(
            pass_name="loose_rare_tokens",
            layer="source_safe_rare_tokens",
            matched=overlap_count >= config.rare_token_min_overlap and jaccard >= config.rare_token_min_jaccard,
            score=score,
            threshold=config.rare_token_min_jaccard,
            metric="rare_token_jaccard_gte",
            details=details,
        ),
    ]

def source_key_tokens(page: PageRecord) -> set[str]:
    tokens: set[str] = set()
    for text in [page.native_text, page.tesseract_text, page.openai_ocr_text, page.raw_text, page.best_text]:
        tokens.update(extract_key_tokens_for_matching(text or ""))
    return tokens


def extract_key_tokens_for_matching(text: str) -> set[str]:
    raw = text or ""
    lower = raw.lower()
    tokens: set[str] = set()
    patterns = [
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}\b",
        r"\b(?:case|claim|member|patient|record|reference|invoice|receipt|document|dob|mrn)\s*(?:no\.?|number|id|#|:)\s*[a-z0-9-]{3,}\b",
        r"\b[a-z]{2,5}-\d{3,}\b",
        r"\b\d{3}-\d{2}-\d{4}\b",
        r"\b\d{5,}\b",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, lower, flags=re.IGNORECASE):
            value = match if isinstance(match, str) else " ".join(match)
            cleaned = re.sub(r"\s+", " ", value.strip().lower())
            if cleaned:
                tokens.add(cleaned[:80])
    for label in ["claimant", "case number", "member id", "hearing", "provider", "diagnosis", "treatment", "receipt", "benefit", "determination"]:
        if label in lower:
            tokens.add(label)
    return tokens


def key_token_pass_records(score: float, overlap_count: int, jaccard: float, config: EngineConfig) -> list[DeterministicPassRecord]:
    rounded = round(score, 4)
    details = {"overlap_count": overlap_count, "jaccard": round(jaccard, 4)}
    return [
        DeterministicPassRecord(
            pass_name="standard_key_tokens",
            layer="source_safe_key_tokens",
            matched=overlap_count >= max(config.multiview_key_token_min_overlap + 1, 3) and jaccard >= max(config.multiview_key_token_min_jaccard, 0.50),
            score=rounded,
            threshold=max(config.multiview_key_token_min_jaccard, 0.50),
            metric="key_token_jaccard_gte",
            details=details,
        ),
        DeterministicPassRecord(
            pass_name="loose_key_tokens",
            layer="source_safe_key_tokens",
            matched=overlap_count >= config.multiview_key_token_min_overlap and jaccard >= config.multiview_key_token_min_jaccard,
            score=rounded,
            threshold=config.multiview_key_token_min_jaccard,
            metric="key_token_jaccard_gte",
            details=details,
        ),
    ]



def visual_pass_records(distance: int, config: EngineConfig) -> list[DeterministicPassRecord]:
    score = round(max(0.0, 1.0 - (distance / 64.0)), 4)
    return [
        DeterministicPassRecord(
            pass_name="strict_visual",
            layer="perceptual_hash",
            matched=distance <= config.strict_phash_threshold,
            score=score,
            threshold=float(config.strict_phash_threshold),
            metric="hamming_distance_lte",
            details={"hamming_distance": distance},
        ),
        DeterministicPassRecord(
            pass_name="standard_visual",
            layer="perceptual_hash",
            matched=distance <= config.standard_phash_threshold,
            score=score,
            threshold=float(config.standard_phash_threshold),
            metric="hamming_distance_lte",
            details={"hamming_distance": distance},
        ),
        DeterministicPassRecord(
            pass_name="loose_visual",
            layer="perceptual_hash",
            matched=distance <= config.loose_phash_threshold,
            score=score,
            threshold=float(config.loose_phash_threshold),
            metric="hamming_distance_lte",
            details={"hamming_distance": distance},
        ),
    ]


def text_pass_records(score: float, config: EngineConfig, text_view: str | None = None) -> list[DeterministicPassRecord]:
    rounded_score = round(float(score), 4)
    details = {"text_view": text_view} if text_view else {}
    return [
        DeterministicPassRecord(
            pass_name="strict_text",
            layer="weighted_text_similarity",
            matched=score >= config.strict_tfidf_threshold,
            score=rounded_score,
            threshold=config.strict_tfidf_threshold,
            metric="tfidf_cosine_gte",
            details=details,
        ),
        DeterministicPassRecord(
            pass_name="standard_text",
            layer="weighted_text_similarity",
            matched=score >= config.standard_tfidf_threshold,
            score=rounded_score,
            threshold=config.standard_tfidf_threshold,
            metric="tfidf_cosine_gte",
            details=details,
        ),
        DeterministicPassRecord(
            pass_name="loose_text",
            layer="weighted_text_similarity",
            matched=score >= config.loose_tfidf_threshold,
            score=rounded_score,
            threshold=config.loose_tfidf_threshold,
            metric="tfidf_cosine_gte",
            details=details,
        ),
    ]


def exact_pass_record(layer: str, pass_name: str = "exact") -> DeterministicPassRecord:
    return DeterministicPassRecord(
        pass_name=pass_name,
        layer=layer,
        matched=True,
        score=1.0,
        threshold=1.0,
        metric="hash_equal",
    )


def stage_from_pass_records(records: list[DeterministicPassRecord]) -> str:
    if any(record.pass_name.startswith("exact") and record.matched for record in records):
        return "deterministic_exact"
    if any(record.pass_name.startswith("strict") and record.matched for record in records):
        return "deterministic_strict"
    if any(record.pass_name.startswith("standard") and record.matched for record in records):
        return "deterministic_standard"
    if any(record.pass_name.startswith("loose") and record.matched for record in records):
        return "deterministic_loose"
    return "single_threshold"


def better_stage(left: str, right: str) -> str:
    return left if STAGE_PRIORITY.get(left, 0) >= STAGE_PRIORITY.get(right, 0) else right


def make_escalation_decision(match: PageMatch, config: EngineConfig) -> EscalationDecision:
    stage = match.candidate_stage
    signal_names = {signal.name for signal in match.signals}

    if "exact_image_hash" in signal_names or "exact_normalized_text_hash" in signal_names or "exact_source_text_hash" in signal_names:
        return EscalationDecision(reason="exact deterministic match; AI escalation not needed")

    embedding_required = (
        stage in {"deterministic_standard", "deterministic_loose"}
        or config.embedding_escalation_min_score <= match.confidence <= config.embedding_escalation_max_score
    )

    # The LLM candidate detector remains downstream of embeddings. v0.4 only
    # recommends it for weak/loose pairs when configured later; it does not call
    # a model yet.
    llm_detector_required = False
    if stage == "deterministic_loose" and config.llm_escalation_min_score <= match.confidence <= config.llm_escalation_max_score:
        llm_detector_required = True

    adjudicator_required = False
    if config.enable_adjudicator and config.adjudicator_min_confidence <= match.confidence <= config.adjudicator_max_confidence:
        adjudicator_required = True

    if embedding_required and llm_detector_required:
        reason = "loose deterministic candidate; run embeddings first, then consider LLM detector/adjudicator if evidence remains mixed"
    elif embedding_required:
        reason = "deterministic candidate is not exact; embedding support is justified before stronger AI use"
    elif adjudicator_required:
        reason = "candidate falls inside adjudicator confidence band"
    else:
        reason = "deterministic evidence sufficient for current review band or too weak for AI escalation"

    return EscalationDecision(
        embedding_required=embedding_required,
        llm_detector_required=llm_detector_required,
        adjudicator_required=adjudicator_required,
        reason=reason,
    )



def sequence_neighbor_matches(
    anchor_matches: list[PageMatch],
    pages_a: list[PageRecord],
    pages_b: list[PageRecord],
    config: EngineConfig,
) -> list[PageMatch]:
    """Promote adjacent page pairs from strong anchor matches.

    This recovers document-structure duplicates such as A page 4 matching B page
    9, where A5/B10 or A3/B8 are likely related but have weaker text. The pass
    is bounded by anchor strength, page adjacency, and independent text/visual
    support.
    """

    if config.sequence_neighbor_window <= 0:
        return []
    index: dict[tuple[str, str, int], PageRecord] = {}
    for page in [*pages_a, *pages_b]:
        index[(page.group, page.document_name, page.page_number)] = page

    matches: list[PageMatch] = []
    emitted: set[tuple[str, str]] = set()
    for anchor in sorted(anchor_matches, key=lambda match: match.confidence, reverse=True):
        if not is_sequence_anchor(anchor, config):
            continue
        for offset in range(-config.sequence_neighbor_window, config.sequence_neighbor_window + 1):
            if offset == 0:
                continue
            page_a = index.get((anchor.page_a.group, anchor.page_a.document_name, anchor.page_a.page_number + offset))
            page_b = index.get((anchor.page_b.group, anchor.page_b.document_name, anchor.page_b.page_number + offset))
            if page_a is None or page_b is None:
                continue
            if page_a.page_id == page_b.page_id:
                continue
            key = (page_a.page_id, page_b.page_id)
            if key in emitted or key == anchor.pair_key_ordered:
                continue
            if config.suppress_low_information_candidates and pages_low_information_for_generation(page_a, page_b, config):
                continue
            evidence = sequence_neighbor_evidence(page_a, page_b, config)
            if not evidence["matched"]:
                continue
            emitted.add(key)
            score = float(evidence["score"])
            stage_name = "standard_sequence" if score >= config.sequence_min_text_similarity else "loose_sequence"
            pass_record = DeterministicPassRecord(
                pass_name=stage_name,
                layer="document_sequence",
                matched=True,
                score=round(score, 4),
                threshold=float(evidence["threshold"]),
                metric="sequence_neighbor_supported",
                details={
                    "anchor_pair": anchor.pair_key_ordered,
                    "anchor_confidence": round(anchor.confidence, 4),
                    "offset": offset,
                    **evidence["details"],
                },
            )
            stage = stage_from_pass_records([pass_record])
            matches.append(
                PageMatch(
                    match_type="sequence_neighbor_candidate",
                    confidence=round(min(0.90, max(0.62, score)), 4),
                    page_a=page_a,
                    page_b=page_b,
                    signals=[
                        MatchSignal(
                            "sequence_neighbor_promotion",
                            score,
                            {
                                "candidate_stage": stage,
                                "anchor_confidence": round(anchor.confidence, 4),
                                "offset": offset,
                                **evidence["details"],
                            },
                        )
                    ],
                    recommendation="review",
                    candidate_stage=stage,
                    deterministic_passes=[pass_record],
                )
            )
    return matches


def is_sequence_anchor(match: PageMatch, config: EngineConfig) -> bool:
    if match.confidence < config.sequence_anchor_min_confidence:
        return False
    if match.match_type == "sequence_neighbor_candidate":
        return False
    signal_names = {signal.name for signal in match.signals}
    if signal_names & {"exact_image_hash", "exact_normalized_text_hash", "exact_source_text_hash"}:
        return True
    return STAGE_PRIORITY.get(match.candidate_stage, 0) >= STAGE_PRIORITY.get("deterministic_standard", 2)


def sequence_neighbor_evidence(page_a: PageRecord, page_b: PageRecord, config: EngineConfig) -> dict[str, object]:
    text_score, text_view_a, text_view_b = best_pair_text_overlap(page_a, page_b, config)
    visual_distance: int | None = None
    visual_score = 0.0
    visual_support = False
    if page_a.perceptual_hash and page_b.perceptual_hash:
        try:
            visual_distance = hamming_distance(page_a.perceptual_hash, page_b.perceptual_hash)
            visual_score = max(0.0, 1.0 - (visual_distance / 64.0))
            visual_support = visual_distance <= config.sequence_visual_support_phash_threshold
        except ValueError:
            visual_distance = None
    threshold = config.sequence_min_text_similarity_with_visual if visual_support else config.sequence_min_text_similarity
    matched = text_score >= threshold
    if not matched and visual_support and visual_distance is not None and visual_distance <= config.strict_phash_threshold:
        matched = text_score > 0.0 or page_is_text_poor(page_a, config) or page_is_text_poor(page_b, config)
    score = max(text_score, visual_score if visual_support else 0.0)
    return {
        "matched": matched,
        "score": round(score, 4),
        "threshold": threshold,
        "details": {
            "text_overlap": round(text_score, 4),
            "text_view_a": text_view_a,
            "text_view_b": text_view_b,
            "visual_support": visual_support,
            "visual_distance": visual_distance if visual_distance is not None else "",
            "visual_score": round(visual_score, 4),
        },
    }


def best_pair_text_overlap(page_a: PageRecord, page_b: PageRecord, config: EngineConfig) -> tuple[float, str, str]:
    views_a = page_text_views(page_a, config)
    views_b = page_text_views(page_b, config)
    best = (0.0, "none", "none")
    for view_a, text_a in views_a.items():
        tokens_a = set(tokenize_for_similarity(text_a, config.domain_stopwords))
        if not tokens_a:
            continue
        for view_b, text_b in views_b.items():
            tokens_b = set(tokenize_for_similarity(text_b, config.domain_stopwords))
            if not tokens_b:
                continue
            score = token_dice(tokens_a, tokens_b)
            if score > best[0]:
                best = (score, view_a, view_b)
    key_a = source_key_tokens(page_a)
    key_b = source_key_tokens(page_b)
    if key_a and key_b:
        score = token_dice(key_a, key_b)
        if score > best[0]:
            best = (score, "key_token_text", "key_token_text")
    return best


def token_dice(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return (2.0 * len(left & right)) / (len(left) + len(right))

# ---------------------------------------------------------------------------
# Legacy single-threshold layers kept for compatibility and optional fallback.
# ---------------------------------------------------------------------------


def exact_image_matches(pages_a: list[PageRecord], pages_b: list[PageRecord]) -> list[PageMatch]:
    by_hash_b: dict[str, list[PageRecord]] = defaultdict(list)
    for page in pages_b:
        if page.exact_image_hash:
            by_hash_b[page.exact_image_hash].append(page)

    matches: list[PageMatch] = []
    for page_a in pages_a:
        if not page_a.exact_image_hash:
            continue
        for page_b in by_hash_b.get(page_a.exact_image_hash, []):
            matches.append(
                PageMatch(
                    match_type="exact_image_duplicate",
                    confidence=1.0,
                    page_a=page_a,
                    page_b=page_b,
                    signals=[MatchSignal("exact_image_hash", 1.0)],
                    recommendation="safe_to_review_as_duplicate",
                    candidate_stage="deterministic_exact",
                    deterministic_passes=[exact_pass_record("exact_image_hash", "exact_image")],
                )
            )
    return matches


def exact_text_matches(pages_a: list[PageRecord], pages_b: list[PageRecord], config: EngineConfig) -> list[PageMatch]:
    if not config.multiview_text_candidates_enabled:
        by_hash_b: dict[str, list[PageRecord]] = defaultdict(list)
        for page in pages_b:
            if page.text_hash:
                by_hash_b[page.text_hash].append(page)

        matches: list[PageMatch] = []
        for page_a in pages_a:
            if not page_a.text_hash:
                continue
            for page_b in by_hash_b.get(page_a.text_hash, []):
                if page_a.page_id == page_b.page_id:
                    continue
                matches.append(
                    PageMatch(
                        match_type="exact_text_duplicate",
                        confidence=0.99,
                        page_a=page_a,
                        page_b=page_b,
                        signals=[MatchSignal("exact_normalized_text_hash", 1.0)],
                        recommendation="safe_to_review_as_duplicate",
                        candidate_stage="deterministic_exact",
                        deterministic_passes=[exact_pass_record("exact_normalized_text_hash", "exact_text")],
                    )
                )
        return matches

    by_hash_b: dict[str, list[tuple[PageRecord, str]]] = defaultdict(list)
    for page in pages_b:
        for view_name, text_hash in page_text_view_hashes(page, config).items():
            by_hash_b[text_hash].append((page, view_name))

    matches: list[PageMatch] = []
    seen: set[tuple[str, str, str, str]] = set()
    for page_a in pages_a:
        for view_a, text_hash in page_text_view_hashes(page_a, config).items():
            for page_b, view_b in by_hash_b.get(text_hash, []):
                if page_a.page_id == page_b.page_id:
                    continue
                key = (page_a.page_id, page_b.page_id, view_a, view_b)
                if key in seen:
                    continue
                seen.add(key)
                signal_name = "exact_normalized_text_hash" if view_a == view_b == "primary_text" else "exact_source_text_hash"
                matches.append(
                    PageMatch(
                        match_type="exact_text_duplicate",
                        confidence=0.99 if signal_name == "exact_normalized_text_hash" else 0.985,
                        page_a=page_a,
                        page_b=page_b,
                        signals=[MatchSignal(signal_name, 1.0, {"text_view_a": view_a, "text_view_b": view_b})],
                        recommendation="safe_to_review_as_duplicate",
                        candidate_stage="deterministic_exact",
                        deterministic_passes=[exact_pass_record(signal_name, "exact_text")],
                    )
                )
    return matches


def page_text_view_hashes(page: PageRecord, config: EngineConfig) -> dict[str, str]:
    hashes: dict[str, str] = {}
    views = page_text_views(page, config)
    for view_name in ["primary_text", "native_text", "tesseract_text", "openai_ocr_text"]:
        text = views.get(view_name, "")
        normalized = normalize_text_for_hash(text)
        if not substantial_text(normalized, stopwords=config.domain_stopwords):
            continue
        hashes[view_name] = sha256_bytes(normalized.encode("utf-8"))
    return hashes


def perceptual_image_matches(pages_a: list[PageRecord], pages_b: list[PageRecord], config: EngineConfig) -> list[PageMatch]:
    candidate_a = [
        page
        for page in pages_a
        if len(tokenize_for_similarity(page.comparison_text, config.domain_stopwords)) < config.text_poor_word_count
    ]
    candidate_b = [
        page
        for page in pages_b
        if len(tokenize_for_similarity(page.comparison_text, config.domain_stopwords)) < config.text_poor_word_count
    ]

    matches: list[PageMatch] = []
    for page_a in candidate_a:
        if not page_a.perceptual_hash:
            continue
        for page_b in candidate_b:
            if page_a.page_id == page_b.page_id or not page_b.perceptual_hash:
                continue
            try:
                dist = hamming_distance(page_a.perceptual_hash, page_b.perceptual_hash)
            except ValueError:
                continue
            if dist <= config.perceptual_hash_threshold:
                score = max(0.0, 1.0 - (dist / 64.0))
                matches.append(
                    PageMatch(
                        match_type="near_visual_duplicate",
                        confidence=round(min(0.96, score), 4),
                        page_a=page_a,
                        page_b=page_b,
                        signals=[MatchSignal("perceptual_hash", score, {"hamming_distance": dist})],
                        recommendation="review",
                    )
                )
    return matches


def weighted_text_matches(pages_a: list[PageRecord], pages_b: list[PageRecord], config: EngineConfig) -> list[PageMatch]:
    text_pages_a = [page for page in pages_a if substantial_text(page.comparison_text, stopwords=config.domain_stopwords)]
    text_pages_b = [page for page in pages_b if substantial_text(page.comparison_text, stopwords=config.domain_stopwords)]

    if not text_pages_a or not text_pages_b:
        return []

    all_pages = text_pages_a + text_pages_b
    texts = [page.comparison_text for page in all_pages]

    vectorizer = TfidfVectorizer(
        tokenizer=lambda value: tokenize_for_similarity(value, config.domain_stopwords),
        token_pattern=None,
        lowercase=False,
        ngram_range=(1, 2),
        min_df=1,
        max_df=config.tfidf_max_df,
        sublinear_tf=True,
        norm="l2",
    )

    try:
        matrix = vectorizer.fit_transform(texts)
    except ValueError:
        return []
    matrix_a = matrix[: len(text_pages_a)]
    matrix_b = matrix[len(text_pages_a) :]
    sim = cosine_similarity(matrix_a, matrix_b)

    matches: list[PageMatch] = []
    for i, page_a in enumerate(text_pages_a):
        candidates: list[tuple[int, float]] = []
        for j, score in enumerate(sim[i]):
            score_float = float(score)
            if score_float >= config.tfidf_threshold:
                candidates.append((j, score_float))

        candidates.sort(key=lambda item: item[1], reverse=True)
        for j, score in candidates[: config.tfidf_top_k]:
            page_b = text_pages_b[j]
            if page_a.page_id == page_b.page_id:
                continue
            matches.append(
                PageMatch(
                    match_type="weighted_text_duplicate",
                    confidence=round(min(0.97, score), 4),
                    page_a=page_a,
                    page_b=page_b,
                    signals=[MatchSignal("tfidf_cosine_similarity", score)],
                    recommendation="review",
                )
            )
    return matches


def merge_pair_matches(matches: Iterable[PageMatch], unordered: bool = False, config: EngineConfig | None = None) -> list[PageMatch]:
    by_pair: dict[tuple[str, str], PageMatch] = {}

    for match in matches:
        key = match.pair_key_unordered if unordered else match.pair_key_ordered
        existing = by_pair.get(key)
        if existing is None:
            by_pair[key] = match
            continue

        existing.signals.extend(match.signals)
        existing.deterministic_passes.extend(match.deterministic_passes)
        existing.confidence = max(existing.confidence, match.confidence)
        existing.candidate_stage = better_stage(existing.candidate_stage, match.candidate_stage)
        existing.match_type = choose_match_type(existing.match_type, match.match_type, existing.signals)
        existing.recommendation = choose_recommendation(existing)

    merged = list(by_pair.values())
    for match in merged:
        match.candidate_stage = better_stage(match.candidate_stage, stage_from_pass_records(match.deterministic_passes))
        if config is not None:
            match.escalation = make_escalation_decision(match, config)
            annotate_match_for_review(match, config.main_review_min_confidence, config.review_queue_profile)
        else:
            annotate_match_for_review(match)
        match.recommendation = choose_recommendation(match)
    merged.sort(key=lambda m: m.confidence, reverse=True)
    return merged


def apply_candidate_controls(matches: list[PageMatch], config: EngineConfig) -> list[PageMatch]:
    """Apply v0.5 candidate hygiene after detector aggregation.

    This keeps high-recall generation separate from review-volume controls:
    detectors can nominate broadly, then low-information suppression and budget
    limits decide what is worth returning/escalating.
    """

    for match in matches:
        annotate_match_for_review(match, config.main_review_min_confidence, config.review_queue_profile)

    sorted_matches = sorted(matches, key=candidate_sort_key, reverse=True)
    kept: list[PageMatch] = []
    per_page: Counter[str] = Counter()

    for match in sorted_matches:
        if should_suppress_low_information_match(match, config):
            continue
        if config.max_candidates_per_page > 0:
            if per_page[match.page_a.page_id] >= config.max_candidates_per_page:
                continue
            if per_page[match.page_b.page_id] >= config.max_candidates_per_page:
                continue
        kept.append(match)
        per_page[match.page_a.page_id] += 1
        per_page[match.page_b.page_id] += 1
        if config.max_candidates_per_job > 0 and len(kept) >= config.max_candidates_per_job:
            break

    kept.sort(key=lambda m: m.confidence, reverse=True)
    return kept


def candidate_sort_key(match: PageMatch) -> tuple[int, float, int]:
    signal_names = {signal.name for signal in match.signals}
    exact_bonus = 10 if {"exact_image_hash", "exact_normalized_text_hash", "exact_source_text_hash"} & signal_names else 0
    multi_signal_bonus = min(len(signal_names), 4)
    return (
        exact_bonus + STAGE_PRIORITY.get(match.candidate_stage, 0) + visibility_rank(match.visibility),
        match.confidence,
        multi_signal_bonus,
    )


def choose_match_type(current: str, new: str, signals: list[MatchSignal]) -> str:
    signal_names = {signal.name for signal in signals}
    if "exact_image_hash" in signal_names:
        return "exact_image_duplicate"
    if "exact_normalized_text_hash" in signal_names or "exact_source_text_hash" in signal_names:
        return "exact_text_duplicate"
    if len(signal_names) > 1:
        return "multi_signal_candidate"
    priority = [
        "exact_image_duplicate",
        "exact_text_duplicate",
        "near_visual_candidate",
        "near_visual_duplicate",
        "weighted_text_candidate",
        "weighted_text_duplicate",
        "key_token_text_candidate",
        "rare_token_candidate",
        "sequence_neighbor_candidate",
        "embedding_similarity_candidate",
        "embedding_supported_candidate",
    ]
    return min((current, new), key=lambda name: priority.index(name) if name in priority else 999)


def choose_recommendation(match: PageMatch) -> str:
    if match.visibility == "low_information":
        return "show_in_low_information_section"
    if match.visibility == "calibration_only":
        return "hide_from_main_list_keep_for_calibration"
    if match.review_bucket == "duplicate" or match.confidence >= 0.99:
        return "safe_to_review_as_duplicate"
    if match.review_bucket == "likely_duplicate" or match.confidence >= 0.90:
        return "high_confidence_review"
    if match.escalation.embedding_required or match.escalation.llm_detector_required:
        return "review_with_ai_escalation_available"
    return "review"
