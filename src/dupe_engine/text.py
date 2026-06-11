from __future__ import annotations

import re

from .config import DEFAULT_DOMAIN_STOPWORDS


def repair_ocr_spacing(text: str) -> str:
    # Keep conservative. Aggressive repair can invent tokens and harm evidence.
    return (
        text.replace("\u00a0", " ")
        .replace("ﬁ", "fi")
        .replace("ﬂ", "fl")
    )


def normalize_text_for_hash(text: str) -> str:
    """Normalize text for exact-ish text hashing.

    This path is intentionally less aggressive than the similarity path. It
    preserves more content so distinct pages do not collapse just because page
    numbers, IDs, or dates were stripped.
    """

    text = repair_ocr_spacing(text).lower()
    text = re.sub(r"[^a-z0-9\s./:-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_text_for_similarity(text: str) -> str:
    """Normalize text for fuzzy comparison.

    This removes obvious page labels and punctuation noise but avoids removing
    substantive clinical terms such as negation, side, severity, medication,
    diagnosis, or procedure words.
    """

    text = repair_ocr_spacing(text).lower()
    text = re.sub(r"page\s+\d+\s+of\s+\d+", " ", text)
    text = re.sub(r"\bpage\s+\d+\b", " ", text)
    text = re.sub(r"[^a-z0-9\s.-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize_for_similarity(text: str, stopwords: set[str] | None = None) -> list[str]:
    stopwords = stopwords if stopwords is not None else DEFAULT_DOMAIN_STOPWORDS
    normalized = normalize_text_for_similarity(text)
    tokens = re.findall(r"\b[a-z][a-z0-9.-]{2,}\b", normalized)
    return [token for token in tokens if token not in stopwords]


def substantial_text(text: str, stopwords: set[str] | None = None, min_tokens: int = 8) -> bool:
    return len(tokenize_for_similarity(text, stopwords=stopwords)) >= min_tokens
