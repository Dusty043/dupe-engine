from __future__ import annotations

import os
from dataclasses import dataclass, field


DEFAULT_DOMAIN_STOPWORDS = {
    "patient",
    "patients",
    "medical",
    "record",
    "records",
    "provider",
    "page",
    "pages",
    "printed",
    "signed",
    "date",
    "dob",
    "mrn",
    "visit",
    "claimant",
    "fax",
}

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class EngineConfig:
    """Runtime configuration for the duplicate engine.

    v0.8 keeps the cheap deterministic multi-pass engine first and validates
    tiered OCR routing: native text, Tesseract TSV/confidence, and an
    required OpenAI vision OCR fallback for selected high-value pages.
    """

    dpi: int = 150
    recursive_pdf_input: bool = True

    # Unified OpenAI provider settings. v0.9.8 assumes OpenAI is the only
    # external AI provider; route-specific base URLs / key env vars may still
    # override these shared settings when needed.
    openai_base_url: str = ""
    openai_api_key_env: str = "DUPE_OPENAI_API_KEY"

    min_text_chars_before_ocr: int = 200

    # Tiered OCR enrichment. Native PDF text is always attempted first.
    # Tesseract is the cheap worker-side OCR tier. OpenAI OCR fallback is
    # reserved for selected pages where Tesseract is weak and the candidate
    # evidence justifies a provider call.
    enable_ocr: bool = True
    ocr_provider: str = "tiered"
    native_min_usable_words: int = 40
    tesseract_enabled: bool = True
    tesseract_cmd: str = "tesseract"
    tesseract_min_confidence: float = 65.0
    tesseract_min_words: int = 40
    tesseract_preprocessing_profiles: str = "standard,grayscale,high_contrast"
    ocr_service_url: str = ""
    enable_openai_ocr: bool = True
    openai_ocr_provider: str = "openai"
    openai_ocr_base_url: str = ""
    openai_ocr_api_key_env: str = ""
    openai_ocr_model: str = "gpt-4o-mini"
    openai_ocr_timeout_seconds: int = 60
    openai_ocr_max_pages_per_job: int = 50
    openai_ocr_max_pages_per_document: int = 5
    openai_ocr_min_candidate_confidence: float = 0.60
    # v0.9.8 adds reason_balanced so one fallback reason cannot consume the entire budget.
    # Supported: candidate_based, weak_pages, vision_expected, weak_pages_or_vision_expected, reason_balanced.
    openai_ocr_selection_mode: str = "reason_balanced"
    openai_ocr_reason_quotas: str = "vision_expected:30,weak_tesseract:30,no_text:20,candidate_based:20"
    openai_ocr_allow_low_information_pages: bool = True
    openai_ocr_low_information_penalty: bool = True
    openai_ocr_accept_cleaner_shorter_text: bool = True
    # v0.9.9b experimental OCR evidence upgrade. This keeps the same
    # fallback provider route, but accepts short OCR when it contains useful
    # key tokens and can optionally combine native/Tesseract/OpenAI evidence
    # into the text used by deterministic/vector matching.
    openai_ocr_evidence_upgrade_enabled: bool = False
    openai_ocr_key_token_acceptance: bool = False
    openai_ocr_combine_text_evidence: bool = False
    openai_ocr_min_key_tokens: int = 3
    openai_ocr_min_key_token_density: float = 0.015
    openai_ocr_require_tesseract_first: bool = True
    openai_ocr_dry_run: bool = False

    # v0.9.9 targeted second-pass OCR rescue. The first OpenAI OCR pass is
    # page-quality/quota based. This optional reserve pass runs after
    # deterministic/vector candidates exist and selects remaining weak pages
    # that participate in suspicious candidate neighborhoods.
    openai_ocr_post_candidate_rescue_enabled: bool = False
    openai_ocr_post_candidate_max_pages: int = 0
    openai_ocr_post_candidate_min_confidence: float = 0.50

    # Deterministic matching. The legacy single-threshold values remain for
    # compatibility; multi-pass profiles are default.
    perceptual_hash_threshold: int = 8
    text_poor_word_count: int = 25
    tfidf_threshold: float = 0.86
    tfidf_top_k: int = 3
    tfidf_max_df: float = 0.85

    # Deterministic multi-pass candidate generation.
    enable_multipass: bool = True
    # v0.4 defaulted this to true; v0.5/v0.6 default to false because the
    # medium synthetic corpus showed visual-all-pages can explode candidate
    # counts and runtime. Enable explicitly for smaller experiments.
    multipass_visual_all_pages: bool = False
    multipass_text_top_k: int = 5
    strict_phash_threshold: int = 8
    standard_phash_threshold: int = 16
    loose_phash_threshold: int = 28
    strict_tfidf_threshold: float = 0.94
    standard_tfidf_threshold: float = 0.86
    loose_tfidf_threshold: float = 0.74

    # v0.10.1 source-safe evidence and candidate formation. OpenAI OCR is kept
    # as sidecar evidence by default; deterministic matching can still form
    # candidates from native, Tesseract, OpenAI, combined, and key-token views.
    source_safe_ocr_merge_enabled: bool = True
    multiview_text_candidates_enabled: bool = True
    multiview_cross_text_candidates_enabled: bool = True
    multiview_key_token_candidates_enabled: bool = True
    multiview_key_token_min_overlap: int = 2
    multiview_key_token_min_jaccard: float = 0.34
    multiview_combined_min_extra_tokens: int = 3
    rare_token_candidates_enabled: bool = True
    rare_token_min_overlap: int = 3
    rare_token_min_jaccard: float = 0.20
    rare_token_max_df: int = 8
    rare_token_min_length: int = 5
    bounded_visual_ocr_weak_enabled: bool = True
    sequence_candidate_promotion_enabled: bool = True
    sequence_anchor_min_confidence: float = 0.86
    sequence_neighbor_window: int = 1
    sequence_min_text_similarity: float = 0.42
    sequence_min_text_similarity_with_visual: float = 0.25
    sequence_visual_support_phash_threshold: int = 24

    embedding_escalation_min_score: float = 0.60
    embedding_escalation_max_score: float = 0.92
    llm_escalation_min_score: float = 0.65
    llm_escalation_max_score: float = 0.90
    max_embedding_pairs_per_job: int = 500
    max_llm_pairs_per_job: int = 50

    # v0.5 candidate hygiene / scaling controls.
    enable_low_information_filter: bool = True
    low_information_word_count: int = 12
    suppress_low_information_candidates: bool = True
    include_low_information_exact_matches: bool = False
    max_candidates_per_job: int = 2000
    max_candidates_per_page: int = 40
    main_review_min_confidence: float = 0.86
    main_review_max_candidates_per_100_pages: int = 50

    # Embedding detector. v0.9.8 can rerank deterministic candidates and, when
    # enabled, add a bounded vector-neighborhood semantic recall pass after OCR rescue.
    enable_embeddings: bool = False
    embeddings_provider: str = "openai"
    embeddings_base_url: str = ""
    embeddings_api_key_env: str = ""
    embeddings_model: str = "text-embedding-3-small"
    embeddings_dimensions: int | None = None
    embeddings_batch_size: int = 64
    embeddings_timeout_seconds: int = 45
    embeddings_candidate_top_k: int = 5
    embeddings_similarity_threshold: float = 0.88
    embeddings_min_margin: float = 0.03
    embeddings_require_cross_source: bool = False
    embeddings_require_reciprocal: bool = False
    embeddings_max_candidates_per_page: int = 2
    embeddings_min_words: int = 8
    embeddings_min_text_chars: int = 120
    embeddings_max_pages_per_job: int = 1000
    embeddings_create_candidates: bool = True
    embeddings_skip_exact_matches: bool = True
    embeddings_dry_run: bool = False
    # v0.9.9 experimental profile only. Hybrid scoring combines embedding
    # similarity with neighborhood rank, margin, reciprocity, OCR text quality,
    # and visual/source penalties before emitting vector recall candidates.
    embeddings_hybrid_scoring_enabled: bool = False
    embeddings_hybrid_min_score: float = 0.78

    # v0.10.9 pure embedding precision reranker. Off by default until offline
    # simulation confirms a safe threshold/action via v0109_reranker_sim.py.
    embedding_reranker_enabled: bool = False
    embedding_reranker_min_confidence: float = 0.80
    embedding_reranker_ocr_penalty: float = 0.01
    embedding_reranker_same_doc_bonus: float = 0.03
    embedding_reranker_tesseract_bonus: float = 0.02
    embedding_reranker_action: str = "demote"  # "demote" | "drop"

    # Queue routing. v0.9.8 separates recall discovery from what appears in the default reviewer queue.
    # Supported: strict_main, balanced, recall_first.
    review_queue_profile: str = "balanced"

    # LLM candidate detector provision. This is distinct from adjudication. It
    # should only run on small candidate pools created by cheaper detectors.
    enable_llm_candidate_detector: bool = False
    llm_candidate_provider: str = "openai"
    llm_candidate_base_url: str = ""
    llm_candidate_api_key_env: str = ""
    llm_candidate_model: str = ""
    llm_candidate_threshold: float = 0.70

    # Adjudicator agent provision. This reviews candidate evidence and produces
    # the final review label/reason. It is not a first-pass detector.
    enable_adjudicator: bool = False
    adjudicator_provider: str = "openai"
    adjudicator_base_url: str = ""
    adjudicator_api_key_env: str = ""
    adjudicator_model: str = ""
    adjudicator_borderline_only: bool = True
    adjudicator_min_confidence: float = 0.70
    adjudicator_max_confidence: float = 0.92

    # Strict mode toggles. v0.9.8 requires OCR and OpenAI fallback by default.
    require_ocr: bool = True
    require_openai_ocr: bool = True
    require_embeddings: bool = False
    require_llm_candidate_detector: bool = False
    require_adjudicator: bool = False

    include_text_preview: bool = False
    text_preview_chars: int = 300
    log_phi: bool = False
    persist_extracted_text: bool = False

    # Matching behavior.
    allow_same_document_matches: bool = True
    compare_within_group: bool = False

    domain_stopwords: set[str] = field(default_factory=lambda: set(DEFAULT_DOMAIN_STOPWORDS))

    @classmethod
    def from_env(cls) -> "EngineConfig":
        dimensions_raw = env_str("DUPE_EMBEDDINGS_DIMENSIONS", "")
        try:
            dimensions = int(dimensions_raw) if dimensions_raw else None
        except ValueError:
            dimensions = None

        generic_llm_enabled = env_bool("DUPE_LLM_ENABLED", False)
        generic_llm_provider = env_str("DUPE_LLM_PROVIDER", "openai") or "openai"
        openai_base_url = env_str("DUPE_OPENAI_BASE_URL", "")
        openai_api_key_env = env_str("DUPE_OPENAI_API_KEY_ENV", "DUPE_OPENAI_API_KEY") or "DUPE_OPENAI_API_KEY"
        generic_llm_base_url = env_str("DUPE_LLM_BASE_URL", openai_base_url)
        generic_llm_model = env_str("DUPE_LLM_MODEL", "")

        return cls(
            dpi=env_int("DUPE_DPI", 150),
            openai_base_url=openai_base_url,
            openai_api_key_env=openai_api_key_env,
            recursive_pdf_input=env_bool("DUPE_RECURSIVE_PDF_INPUT", True),
            min_text_chars_before_ocr=env_int("DUPE_MIN_TEXT_CHARS_BEFORE_OCR", 200),
            enable_ocr=env_bool("DUPE_OCR_ENABLED", True),
            ocr_provider=env_str("DUPE_OCR_PROVIDER", "tiered") or "tiered",
            native_min_usable_words=env_int("DUPE_NATIVE_MIN_USABLE_WORDS", 40),
            tesseract_enabled=env_bool("DUPE_TESSERACT_ENABLED", True),
            tesseract_cmd=env_str("DUPE_TESSERACT_CMD", "tesseract") or "tesseract",
            tesseract_min_confidence=env_float("DUPE_TESSERACT_MIN_CONFIDENCE", 65.0),
            tesseract_min_words=env_int("DUPE_TESSERACT_MIN_WORDS", 40),
            tesseract_preprocessing_profiles=env_str("DUPE_TESSERACT_PREPROCESSING_PROFILES", "standard,grayscale,high_contrast") or "standard",
            ocr_service_url=env_str("DUPE_OCR_SERVICE_URL", ""),
            enable_openai_ocr=env_bool("DUPE_OPENAI_OCR_ENABLED", True),
            openai_ocr_provider=env_str("DUPE_OPENAI_OCR_PROVIDER", "openai") or "openai",
            openai_ocr_base_url=env_str("DUPE_OPENAI_OCR_BASE_URL", openai_base_url),
            openai_ocr_api_key_env=env_str("DUPE_OPENAI_OCR_API_KEY_ENV", ""),
            openai_ocr_model=env_str("DUPE_OPENAI_OCR_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
            openai_ocr_timeout_seconds=env_int("DUPE_OPENAI_OCR_TIMEOUT_SECONDS", 60),
            openai_ocr_max_pages_per_job=env_int("DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB", 50),
            openai_ocr_max_pages_per_document=env_int("DUPE_OPENAI_OCR_MAX_PAGES_PER_DOCUMENT", 5),
            openai_ocr_min_candidate_confidence=env_float("DUPE_OPENAI_OCR_MIN_CANDIDATE_CONFIDENCE", 0.60),
            openai_ocr_selection_mode=env_str("DUPE_OPENAI_OCR_SELECTION_MODE", "reason_balanced") or "reason_balanced",
            openai_ocr_reason_quotas=env_str("DUPE_OPENAI_OCR_REASON_QUOTAS", "vision_expected:30,weak_tesseract:30,no_text:20,candidate_based:20") or "vision_expected:30,weak_tesseract:30,no_text:20,candidate_based:20",
            openai_ocr_allow_low_information_pages=env_bool("DUPE_OPENAI_OCR_ALLOW_LOW_INFORMATION_PAGES", True),
            openai_ocr_low_information_penalty=env_bool("DUPE_OPENAI_OCR_LOW_INFORMATION_PENALTY", True),
            openai_ocr_accept_cleaner_shorter_text=env_bool("DUPE_OPENAI_OCR_ACCEPT_CLEANER_SHORTER_TEXT", True),
            openai_ocr_evidence_upgrade_enabled=env_bool("DUPE_OPENAI_OCR_EVIDENCE_UPGRADE_ENABLED", False),
            openai_ocr_key_token_acceptance=env_bool("DUPE_OPENAI_OCR_KEY_TOKEN_ACCEPTANCE", False),
            openai_ocr_combine_text_evidence=env_bool("DUPE_OPENAI_OCR_COMBINE_TEXT_EVIDENCE", False),
            openai_ocr_min_key_tokens=env_int("DUPE_OPENAI_OCR_MIN_KEY_TOKENS", 3),
            openai_ocr_min_key_token_density=env_float("DUPE_OPENAI_OCR_MIN_KEY_TOKEN_DENSITY", 0.015),
            openai_ocr_require_tesseract_first=env_bool("DUPE_OPENAI_OCR_REQUIRE_TESSERACT_FIRST", True),
            openai_ocr_dry_run=env_bool("DUPE_OPENAI_OCR_DRY_RUN", False),
            openai_ocr_post_candidate_rescue_enabled=env_bool("DUPE_OPENAI_OCR_POST_CANDIDATE_RESCUE_ENABLED", False),
            openai_ocr_post_candidate_max_pages=env_int("DUPE_OPENAI_OCR_POST_CANDIDATE_MAX_PAGES", 0),
            openai_ocr_post_candidate_min_confidence=env_float("DUPE_OPENAI_OCR_POST_CANDIDATE_MIN_CONFIDENCE", 0.50),
            perceptual_hash_threshold=env_int("DUPE_PHASH_THRESHOLD", 8),
            text_poor_word_count=env_int("DUPE_TEXT_POOR_WORD_COUNT", 25),
            tfidf_threshold=env_float("DUPE_TFIDF_THRESHOLD", 0.86),
            tfidf_top_k=env_int("DUPE_TFIDF_TOP_K", 3),
            tfidf_max_df=env_float("DUPE_TFIDF_MAX_DF", 0.85),
            enable_multipass=env_bool("DUPE_MULTIPASS_ENABLED", True),
            multipass_visual_all_pages=env_bool("DUPE_MULTIPASS_VISUAL_ALL_PAGES", False),
            multipass_text_top_k=env_int("DUPE_MULTIPASS_TEXT_TOP_K", 5),
            strict_phash_threshold=env_int("DUPE_STRICT_PHASH_THRESHOLD", 8),
            standard_phash_threshold=env_int("DUPE_STANDARD_PHASH_THRESHOLD", 16),
            loose_phash_threshold=env_int("DUPE_LOOSE_PHASH_THRESHOLD", 28),
            strict_tfidf_threshold=env_float("DUPE_STRICT_TFIDF_THRESHOLD", 0.94),
            standard_tfidf_threshold=env_float("DUPE_STANDARD_TFIDF_THRESHOLD", 0.86),
            loose_tfidf_threshold=env_float("DUPE_LOOSE_TFIDF_THRESHOLD", 0.74),
            source_safe_ocr_merge_enabled=env_bool("DUPE_SOURCE_SAFE_OCR_MERGE_ENABLED", True),
            multiview_text_candidates_enabled=env_bool("DUPE_MULTIVIEW_TEXT_CANDIDATES_ENABLED", True),
            multiview_key_token_candidates_enabled=env_bool("DUPE_MULTIVIEW_KEY_TOKEN_CANDIDATES_ENABLED", True),
            multiview_key_token_min_overlap=env_int("DUPE_MULTIVIEW_KEY_TOKEN_MIN_OVERLAP", 2),
            multiview_key_token_min_jaccard=env_float("DUPE_MULTIVIEW_KEY_TOKEN_MIN_JACCARD", 0.34),
            multiview_combined_min_extra_tokens=env_int("DUPE_MULTIVIEW_COMBINED_MIN_EXTRA_TOKENS", 3),
            bounded_visual_ocr_weak_enabled=env_bool("DUPE_BOUNDED_VISUAL_OCR_WEAK_ENABLED", True),
            sequence_candidate_promotion_enabled=env_bool("DUPE_SEQUENCE_CANDIDATE_PROMOTION_ENABLED", True),
            sequence_anchor_min_confidence=env_float("DUPE_SEQUENCE_ANCHOR_MIN_CONFIDENCE", 0.86),
            sequence_neighbor_window=env_int("DUPE_SEQUENCE_NEIGHBOR_WINDOW", 1),
            sequence_min_text_similarity=env_float("DUPE_SEQUENCE_MIN_TEXT_SIMILARITY", 0.42),
            sequence_min_text_similarity_with_visual=env_float("DUPE_SEQUENCE_MIN_TEXT_SIMILARITY_WITH_VISUAL", 0.25),
            sequence_visual_support_phash_threshold=env_int("DUPE_SEQUENCE_VISUAL_SUPPORT_PHASH_THRESHOLD", 24),
            embedding_escalation_min_score=env_float("DUPE_EMBEDDING_ESCALATION_MIN_SCORE", 0.60),
            embedding_escalation_max_score=env_float("DUPE_EMBEDDING_ESCALATION_MAX_SCORE", 0.92),
            llm_escalation_min_score=env_float("DUPE_LLM_ESCALATION_MIN_SCORE", 0.65),
            llm_escalation_max_score=env_float("DUPE_LLM_ESCALATION_MAX_SCORE", 0.90),
            max_embedding_pairs_per_job=env_int("DUPE_MAX_EMBEDDING_PAIRS_PER_JOB", 500),
            max_llm_pairs_per_job=env_int("DUPE_MAX_LLM_PAIRS_PER_JOB", 50),
            enable_low_information_filter=env_bool("DUPE_LOW_INFORMATION_FILTER_ENABLED", True),
            low_information_word_count=env_int("DUPE_LOW_INFORMATION_WORD_COUNT", 12),
            suppress_low_information_candidates=env_bool("DUPE_SUPPRESS_LOW_INFORMATION_CANDIDATES", True),
            include_low_information_exact_matches=env_bool("DUPE_INCLUDE_LOW_INFORMATION_EXACT_MATCHES", False),
            max_candidates_per_job=env_int("DUPE_MAX_CANDIDATES_PER_JOB", 2000),
            max_candidates_per_page=env_int("DUPE_MAX_CANDIDATES_PER_PAGE", 40),
            main_review_min_confidence=env_float("DUPE_MAIN_REVIEW_MIN_CONFIDENCE", 0.86),
            main_review_max_candidates_per_100_pages=env_int("DUPE_MAIN_REVIEW_MAX_CANDIDATES_PER_100_PAGES", 50),
            enable_embeddings=env_bool("DUPE_EMBEDDINGS_ENABLED", False),
            embeddings_provider=env_str("DUPE_EMBEDDINGS_PROVIDER", "openai") or "openai",
            embeddings_base_url=env_str("DUPE_EMBEDDINGS_BASE_URL", openai_base_url),
            embeddings_api_key_env=env_str("DUPE_EMBEDDINGS_API_KEY_ENV", ""),
            embeddings_model=env_str("DUPE_EMBEDDINGS_MODEL", "text-embedding-3-small") or "text-embedding-3-small",
            embeddings_dimensions=dimensions,
            embeddings_batch_size=env_int("DUPE_EMBEDDINGS_BATCH_SIZE", 64),
            embeddings_timeout_seconds=env_int("DUPE_EMBEDDINGS_TIMEOUT_SECONDS", 45),
            embeddings_candidate_top_k=env_int("DUPE_EMBEDDINGS_CANDIDATE_TOP_K", 5),
            embeddings_similarity_threshold=env_float("DUPE_EMBEDDINGS_SIMILARITY_THRESHOLD", 0.88),
            embeddings_min_margin=env_float("DUPE_EMBEDDINGS_MIN_MARGIN", 0.03),
            embeddings_require_cross_source=env_bool("DUPE_EMBEDDINGS_REQUIRE_CROSS_SOURCE", False),
            embeddings_require_reciprocal=env_bool("DUPE_EMBEDDINGS_REQUIRE_RECIPROCAL", False),
            embeddings_max_candidates_per_page=env_int("DUPE_EMBEDDINGS_MAX_CANDIDATES_PER_PAGE", 2),
            embeddings_min_words=env_int("DUPE_EMBEDDINGS_MIN_WORDS", 8),
            embeddings_min_text_chars=env_int("DUPE_EMBEDDINGS_MIN_TEXT_CHARS", 120),
            embeddings_max_pages_per_job=env_int("DUPE_EMBEDDINGS_MAX_PAGES_PER_JOB", 1000),
            embeddings_create_candidates=env_bool("DUPE_EMBEDDINGS_CREATE_CANDIDATES", True),
            embeddings_skip_exact_matches=env_bool("DUPE_EMBEDDINGS_SKIP_EXACT_MATCHES", True),
            embeddings_dry_run=env_bool("DUPE_EMBEDDINGS_DRY_RUN", False),
            embeddings_hybrid_scoring_enabled=env_bool("DUPE_EMBEDDINGS_HYBRID_SCORING_ENABLED", False),
            embeddings_hybrid_min_score=env_float("DUPE_EMBEDDINGS_HYBRID_MIN_SCORE", 0.78),
            embedding_reranker_enabled=env_bool("DUPE_EMBEDDING_RERANKER_ENABLED", False),
            embedding_reranker_min_confidence=env_float("DUPE_EMBEDDING_RERANKER_MIN_CONFIDENCE", 0.80),
            embedding_reranker_ocr_penalty=env_float("DUPE_EMBEDDING_RERANKER_OCR_PENALTY", 0.01),
            embedding_reranker_same_doc_bonus=env_float("DUPE_EMBEDDING_RERANKER_SAME_DOC_BONUS", 0.03),
            embedding_reranker_tesseract_bonus=env_float("DUPE_EMBEDDING_RERANKER_TESSERACT_BONUS", 0.02),
            embedding_reranker_action=env_str("DUPE_EMBEDDING_RERANKER_ACTION", "demote") or "demote",
            review_queue_profile=env_str("DUPE_REVIEW_QUEUE_PROFILE", "balanced") or "balanced",
            enable_llm_candidate_detector=env_bool("DUPE_LLM_CANDIDATE_ENABLED", False),
            llm_candidate_provider=env_str("DUPE_LLM_CANDIDATE_PROVIDER", generic_llm_provider) or generic_llm_provider,
            llm_candidate_base_url=env_str("DUPE_LLM_CANDIDATE_BASE_URL", generic_llm_base_url),
            llm_candidate_api_key_env=env_str("DUPE_LLM_CANDIDATE_API_KEY_ENV", ""),
            llm_candidate_model=env_str("DUPE_LLM_CANDIDATE_MODEL", generic_llm_model),
            llm_candidate_threshold=env_float("DUPE_LLM_CANDIDATE_THRESHOLD", 0.70),
            enable_adjudicator=env_bool("DUPE_ADJUDICATOR_ENABLED", generic_llm_enabled),
            adjudicator_provider=env_str("DUPE_ADJUDICATOR_PROVIDER", generic_llm_provider) or generic_llm_provider,
            adjudicator_base_url=env_str("DUPE_ADJUDICATOR_BASE_URL", generic_llm_base_url),
            adjudicator_api_key_env=env_str("DUPE_ADJUDICATOR_API_KEY_ENV", ""),
            adjudicator_model=env_str("DUPE_ADJUDICATOR_MODEL", generic_llm_model),
            adjudicator_borderline_only=env_bool("DUPE_ADJUDICATOR_BORDERLINE_ONLY", True),
            adjudicator_min_confidence=env_float("DUPE_ADJUDICATOR_MIN_CONFIDENCE", 0.70),
            adjudicator_max_confidence=env_float("DUPE_ADJUDICATOR_MAX_CONFIDENCE", 0.92),
            require_ocr=env_bool("DUPE_REQUIRE_OCR", True),
            require_openai_ocr=env_bool("DUPE_REQUIRE_OPENAI_OCR", True),
            require_embeddings=env_bool("DUPE_REQUIRE_EMBEDDINGS", False),
            require_llm_candidate_detector=env_bool("DUPE_REQUIRE_LLM_CANDIDATE", False),
            require_adjudicator=env_bool("DUPE_REQUIRE_ADJUDICATOR", False),
            include_text_preview=env_bool("DUPE_INCLUDE_TEXT_PREVIEW", False),
            text_preview_chars=env_int("DUPE_TEXT_PREVIEW_CHARS", 300),
            log_phi=env_bool("DUPE_LOG_PHI", False),
            persist_extracted_text=env_bool("DUPE_PERSIST_EXTRACTED_TEXT", False),
        )
