from __future__ import annotations

import re
from collections.abc import Iterable

from .config import EngineConfig
from .models import PageMatch, PageRecord
from .text import tokenize_for_similarity


LOW_INFORMATION_RECORD_TYPES = {
    "blank_page",
    "separator_page",
    "signature_page",
    "cover_sheet",
    "fax_cover_sheet",
}

LOW_INFORMATION_PATTERNS = [
    re.compile(r"\bintentionally\s+left\s+blank\b", re.I),
    re.compile(r"\bblank\s+page\b", re.I),
    re.compile(r"\bseparator\s+page\b", re.I),
    re.compile(r"\bfax\s+cover\s+sheet\b", re.I),
    re.compile(r"\bcover\s+sheet\b", re.I),
    re.compile(r"\belectronically\s+signed\b", re.I),
]


def annotate_page_quality(page: PageRecord, config: EngineConfig) -> PageRecord:
    """Annotate a page with low-information flags used for candidate hygiene.

    This is intentionally conservative and explainable. It does not delete pages;
    it only marks them so candidate generation can suppress/downrank pages that
    are usually not useful reviewer matches.
    """

    if not config.enable_low_information_filter:
        return page

    reason = low_information_reason(page, config)
    page.is_low_information = reason is not None
    page.low_information_reason = reason
    page.meta["is_low_information"] = page.is_low_information
    if reason:
        page.meta["low_information_reason"] = reason
    return page


def low_information_reason(page: PageRecord, config: EngineConfig) -> str | None:
    meta_value = page.meta.get("is_low_information_page")
    if meta_value is True:
        return "metadata_low_information_page"

    record_type = str(page.meta.get("record_type", "")).strip().lower()
    if record_type in LOW_INFORMATION_RECORD_TYPES:
        return f"metadata_record_type:{record_type}"

    text = combined_quality_text(page)
    normalized = " ".join(text.split())
    token_count = len(tokenize_for_similarity(normalized, config.domain_stopwords))

    if token_count == 0:
        return "empty_or_no_substantial_text"
    if token_count <= config.low_information_word_count:
        return f"low_word_count:{token_count}"

    for pattern in LOW_INFORMATION_PATTERNS:
        if pattern.search(normalized):
            # Cover/signature pages with a lot of routing text can still be noisy.
            # Avoid classifying clinical notes with incidental signature text by
            # checking for a low-ish token count or known non-clinical terms.
            if token_count <= max(config.low_information_word_count * 3, 30):
                return f"pattern:{pattern.pattern}"

    return None



def combined_quality_text(page: PageRecord) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for text in [page.raw_text, page.best_text, page.comparison_text, page.native_text, page.tesseract_text, page.openai_ocr_text]:
        cleaned = " ".join((text or "").split())
        if not cleaned or cleaned in seen:
            continue
        parts.append(cleaned)
        seen.add(cleaned)
    return "\n".join(parts)


def source_safe_signal_has_substantial_evidence(match: PageMatch, config: EngineConfig) -> bool:
    source_safe_signals = {
        "tfidf_openai_ocr_text_similarity",
        "tfidf_combined_text_similarity",
        "tfidf_tesseract_text_similarity",
        "key_token_overlap",
        "sequence_neighbor_promotion",
        "exact_source_text_hash",
    }
    signal_names = {signal.name for signal in match.signals}
    if not (signal_names & source_safe_signals):
        return False
    for page in (match.page_a, match.page_b):
        source_text = "\n".join([page.tesseract_text or "", page.openai_ocr_text or ""])
        if len(tokenize_for_similarity(source_text, config.domain_stopwords)) >= max(3, config.low_information_word_count):
            return True
        if page.openai_ocr_word_count >= max(3, config.low_information_word_count):
            return True
    return False

def is_low_information_pair(match: PageMatch) -> bool:
    return bool(match.page_a.is_low_information or match.page_b.is_low_information)


def should_suppress_low_information_match(match: PageMatch, config: EngineConfig) -> bool:
    if not config.suppress_low_information_candidates:
        return False
    if not is_low_information_pair(match):
        return False
    if config.include_low_information_exact_matches and match.match_type in {"exact_image_duplicate", "exact_text_duplicate"}:
        return False
    if source_safe_signal_has_substantial_evidence(match, config):
        return False
    return True


def count_low_information_pages(pages: Iterable[PageRecord]) -> int:
    return sum(1 for page in pages if page.is_low_information)
