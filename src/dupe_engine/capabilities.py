from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any

from .config import EngineConfig


@dataclass(frozen=True)
class ProviderStatus:
    layer: str
    enabled: bool
    available: bool
    used: bool = False
    provider: str = "builtin"
    status: str = "available"
    reason: str | None = None
    model: str | None = None
    endpoint_configured: bool = False
    required: bool = False
    role: str = "detector"
    details: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityReport:
    layers: dict[str, ProviderStatus]

    def to_json(self) -> dict[str, Any]:
        return {name: status.to_json() for name, status in self.layers.items()}

    @property
    def blocking_errors(self) -> list[str]:
        errors = []
        for status in self.layers.values():
            if status.required and (not status.enabled or not status.available):
                reason = status.reason or status.status
                errors.append(f"{status.layer} required but not available: {reason}")
        return errors


def build_capability_report(config: EngineConfig, used_core_layers: bool = False) -> CapabilityReport:
    layers = {
        "exact_image_hash": ProviderStatus(
            layer="exact_image_hash",
            enabled=True,
            available=True,
            used=used_core_layers,
            provider="builtin",
            status="available",
            role="detector",
        ),
        "exact_text_hash": ProviderStatus(
            layer="exact_text_hash",
            enabled=True,
            available=True,
            used=used_core_layers,
            provider="builtin",
            status="available",
            role="detector",
        ),
        "perceptual_hash": ProviderStatus(
            layer="perceptual_hash",
            enabled=True,
            available=True,
            used=used_core_layers,
            provider="builtin",
            status="available",
            role="detector",
            details={"threshold": config.perceptual_hash_threshold},
        ),
        "weighted_text_similarity": ProviderStatus(
            layer="weighted_text_similarity",
            enabled=True,
            available=True,
            used=used_core_layers,
            provider="builtin",
            status="available",
            role="detector",
            details={"tfidf_threshold": config.tfidf_threshold, "tfidf_top_k": config.tfidf_top_k},
        ),
        "deterministic_multipass": ProviderStatus(
            layer="deterministic_multipass",
            enabled=config.enable_multipass,
            available=True,
            used=used_core_layers and config.enable_multipass,
            provider="builtin",
            status="available" if config.enable_multipass else "disabled",
            role="detector",
            details={
                "strict_phash_threshold": config.strict_phash_threshold,
                "standard_phash_threshold": config.standard_phash_threshold,
                "loose_phash_threshold": config.loose_phash_threshold,
                "strict_tfidf_threshold": config.strict_tfidf_threshold,
                "standard_tfidf_threshold": config.standard_tfidf_threshold,
                "loose_tfidf_threshold": config.loose_tfidf_threshold,
                "visual_all_pages": config.multipass_visual_all_pages,
                "text_top_k": config.multipass_text_top_k,
            },
        ),
        "low_information_filter": ProviderStatus(
            layer="low_information_filter",
            enabled=config.enable_low_information_filter,
            available=True,
            used=used_core_layers and config.enable_low_information_filter,
            provider="builtin",
            status="available" if config.enable_low_information_filter else "disabled",
            role="candidate_hygiene",
            details={
                "word_count_threshold": config.low_information_word_count,
                "suppress_candidates": config.suppress_low_information_candidates,
                "include_exact_matches": config.include_low_information_exact_matches,
            },
        ),
        "candidate_budget_controls": ProviderStatus(
            layer="candidate_budget_controls",
            enabled=True,
            available=True,
            used=used_core_layers,
            provider="builtin",
            status="available",
            role="candidate_hygiene",
            details={
                "max_candidates_per_job": config.max_candidates_per_job,
                "max_candidates_per_page": config.max_candidates_per_page,
            },
        ),
        "ocr": check_ocr_status(config),
        "tesseract_ocr": check_tesseract_ocr_status(config),
        "openai_ocr_fallback": check_openai_ocr_status(config),
        "embeddings": check_embeddings_status(config),
        "llm_candidate_detector": check_llm_candidate_detector_status(config),
        "adjudicator_agent": check_adjudicator_status(config),
    }
    return CapabilityReport(layers=layers)


def check_ocr_status(config: EngineConfig) -> ProviderStatus:
    """Aggregate tiered OCR status.

    v0.8 reports Tesseract and OpenAI fallback separately, but keeps the
    historical ``ocr`` layer as an aggregate enrichment capability.
    """

    if not config.enable_ocr:
        return ProviderStatus(
            layer="ocr",
            enabled=False,
            available=False,
            used=False,
            provider=config.ocr_provider,
            status="disabled",
            reason="OCR is mandatory in v0.9.8; set DUPE_OCR_ENABLED=true",
            required=config.require_ocr,
            role="enrichment",
            details={"tiered": True},
        )

    tesseract = check_tesseract_ocr_status(config)
    openai = check_openai_ocr_status(config)
    available = tesseract.available or openai.available
    reason = None if available else "no OCR tier is available"
    return ProviderStatus(
        layer="ocr",
        enabled=True,
        available=available,
        provider=config.ocr_provider,
        status="available" if available else "unavailable",
        reason=reason,
        required=config.require_ocr,
        role="enrichment",
        details={
            "tiered": True,
            "native_min_usable_words": config.native_min_usable_words,
            "tesseract_status": tesseract.status,
            "openai_ocr_status": openai.status,
            "openai_ocr_required": config.require_openai_ocr,
        },
    )


def check_tesseract_ocr_status(config: EngineConfig) -> ProviderStatus:
    enabled = config.enable_ocr and config.tesseract_enabled
    if not enabled:
        return ProviderStatus(
            layer="tesseract_ocr",
            enabled=False,
            available=False,
            provider="tesseract",
            status="disabled",
            reason="OCR is mandatory; DUPE_TESSERACT_ENABLED=false",
            required=False,
            role="enrichment",
            details={"tesseract_cmd": config.tesseract_cmd},
        )

    pytesseract_available = importlib.util.find_spec("pytesseract") is not None
    tesseract_available = shutil.which(config.tesseract_cmd) is not None
    if not pytesseract_available:
        return ProviderStatus(
            layer="tesseract_ocr",
            enabled=True,
            available=False,
            provider="tesseract",
            status="unavailable",
            reason="pytesseract Python package is not installed",
            role="enrichment",
            details={"tesseract_cmd": config.tesseract_cmd},
        )
    if not tesseract_available:
        return ProviderStatus(
            layer="tesseract_ocr",
            enabled=True,
            available=False,
            provider="tesseract",
            status="unavailable",
            reason=f"tesseract executable not found: {config.tesseract_cmd}",
            role="enrichment",
            details={"tesseract_cmd": config.tesseract_cmd},
        )
    return ProviderStatus(
        layer="tesseract_ocr",
        enabled=True,
        available=True,
        provider="tesseract",
        status="available",
        role="enrichment",
        details={
            "tesseract_cmd": config.tesseract_cmd,
            "tesseract_version": get_tesseract_version(config.tesseract_cmd),
            "min_confidence": config.tesseract_min_confidence,
            "min_words": config.tesseract_min_words,
            "preprocessing_profiles": [p.strip() for p in config.tesseract_preprocessing_profiles.split(",") if p.strip()],
        },
    )


def get_tesseract_version(command: str) -> str | None:
    try:
        result = subprocess.run(
            [command, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    first_line = (result.stdout or result.stderr).splitlines()[0:1]
    return first_line[0].strip() if first_line else None


def _env_value(name: str | None) -> str | None:
    if not name:
        return None
    value = os.getenv(name)
    return value if value else None


def _openai_key_from_envs(*, config: EngineConfig | None = None, route_api_key_env: str = "", conventional_envs: tuple[str, ...] = ()) -> str | None:
    """Resolve a route-specific OpenAI key with a unified fallback.

    Priority:
    1. explicit route env-var name from config, e.g. DUPE_OPENAI_OCR_API_KEY_ENV=MY_OCR_KEY
    2. conventional route-specific key, e.g. DUPE_OPENAI_OCR_API_KEY
    3. unified configured key env, usually DUPE_OPENAI_API_KEY
    4. DUPE_OPENAI_API_KEY
    5. OPENAI_API_KEY
    """

    env_names: list[str] = []
    if route_api_key_env:
        env_names.append(route_api_key_env)
    env_names.extend(conventional_envs)
    if config and config.openai_api_key_env:
        env_names.append(config.openai_api_key_env)
    env_names.extend(["DUPE_OPENAI_API_KEY", "OPENAI_API_KEY"])

    seen: set[str] = set()
    for name in env_names:
        if not name or name in seen:
            continue
        seen.add(name)
        value = _env_value(name)
        if value:
            return value
    return None


def get_openai_ocr_api_key(config: EngineConfig | None = None) -> str | None:
    return _openai_key_from_envs(
        config=config,
        route_api_key_env=(config.openai_ocr_api_key_env if config else ""),
        conventional_envs=("DUPE_OPENAI_OCR_API_KEY",),
    )


def check_openai_ocr_status(config: EngineConfig) -> ProviderStatus:
    if not config.enable_openai_ocr:
        return ProviderStatus(
            layer="openai_ocr_fallback",
            enabled=False,
            available=False,
            provider=config.openai_ocr_provider,
            status="disabled",
            reason="OpenAI OCR fallback is mandatory in v0.9.8; set DUPE_OPENAI_OCR_ENABLED=true",
            model=config.openai_ocr_model or None,
            required=config.require_openai_ocr,
            role="enrichment",
        )

    provider = config.openai_ocr_provider.lower()
    endpoint_configured = True

    if config.openai_ocr_dry_run:
        return ProviderStatus(
            layer="openai_ocr_fallback",
            enabled=True,
            available=False,
            provider=provider,
            status="dry_run",
            reason="DUPE_OPENAI_OCR_DRY_RUN=true; provider calls disabled",
            model=config.openai_ocr_model or None,
            endpoint_configured=endpoint_configured,
            required=config.require_openai_ocr,
            role="enrichment",
            details=_openai_ocr_details(config),
        )

    if provider == "openai":
        if not get_openai_ocr_api_key(config):
            return ProviderStatus(
                layer="openai_ocr_fallback",
                enabled=True,
                available=False,
                provider=provider,
                status="unavailable",
                reason="OpenAI OCR key not set; use DUPE_OPENAI_API_KEY/OPENAI_API_KEY or override with DUPE_OPENAI_OCR_API_KEY(_ENV)",
                model=config.openai_ocr_model or None,
                endpoint_configured=endpoint_configured,
                required=config.require_openai_ocr,
                role="enrichment",
                details=_openai_ocr_details(config),
            )
        return ProviderStatus(
            layer="openai_ocr_fallback",
            enabled=True,
            available=True,
            provider=provider,
            status="available",
            reason="OpenAI OCR fallback provider configured and required",
            model=config.openai_ocr_model or None,
            endpoint_configured=endpoint_configured,
            required=config.require_openai_ocr,
            role="enrichment",
            details=_openai_ocr_details(config),
        )

    return ProviderStatus(
        layer="openai_ocr_fallback",
        enabled=True,
        available=False,
        provider=config.openai_ocr_provider,
        status="unknown_provider",
        reason=f"Unsupported OCR fallback provider: {config.openai_ocr_provider}; v0.9.8 supports openai only",
        model=config.openai_ocr_model or None,
        endpoint_configured=endpoint_configured,
        required=config.require_openai_ocr,
        role="enrichment",
        details=_openai_ocr_details(config),
    )


def check_bedrock_ocr_status(config: EngineConfig) -> ProviderStatus:
    """Return availability status for the Bedrock Claude vision OCR provider."""
    if config.vision_ocr_provider.lower() != "bedrock":
        return ProviderStatus(
            layer="bedrock_ocr_fallback",
            enabled=False,
            available=False,
            provider="bedrock",
            status="disabled",
            reason="DUPE_VISION_OCR_PROVIDER is not 'bedrock'",
            model=config.bedrock_ocr_model,
        )
    try:
        import boto3  # noqa: PLC0415
    except ImportError:
        return ProviderStatus(
            layer="bedrock_ocr_fallback",
            enabled=True,
            available=False,
            provider="bedrock",
            status="unavailable",
            reason="boto3 not installed; pip install 'dupe-engine[aws]'",
            model=config.bedrock_ocr_model,
        )
    try:
        session = boto3.Session(region_name=config.bedrock_region)
        creds = session.get_credentials()
        if creds is None:
            raise RuntimeError("No AWS credentials found")
        creds.get_frozen_credentials()
    except Exception as exc:
        return ProviderStatus(
            layer="bedrock_ocr_fallback",
            enabled=True,
            available=False,
            provider="bedrock",
            status="unavailable",
            reason=f"AWS credentials not available: {exc}",
            model=config.bedrock_ocr_model,
        )
    return ProviderStatus(
        layer="bedrock_ocr_fallback",
        enabled=True,
        available=True,
        provider="bedrock",
        status="available",
        reason="Bedrock OCR provider configured and available",
        model=config.bedrock_ocr_model,
        role="enrichment",
    )


def _openai_ocr_details(config: EngineConfig) -> dict[str, Any]:
    return {
        "max_pages_per_job": config.openai_ocr_max_pages_per_job,
        "min_candidate_confidence": config.openai_ocr_min_candidate_confidence,
        "selection_mode": config.openai_ocr_selection_mode,
        "allow_low_information_pages": config.openai_ocr_allow_low_information_pages,
        "require_tesseract_first": config.openai_ocr_require_tesseract_first,
        "timeout_seconds": config.openai_ocr_timeout_seconds,
        "provider_family": "openai",
        "base_url_configured": bool(config.openai_ocr_base_url or config.openai_base_url),
        "ai_route": "vision_ocr_extraction",
        "input_kind": "page_image",
        "required": config.require_openai_ocr,
    }


def get_openai_api_key(config: EngineConfig | None = None) -> str | None:
    return _openai_key_from_envs(
        config=config,
        route_api_key_env=(config.embeddings_api_key_env if config else ""),
        conventional_envs=("DUPE_EMBEDDINGS_API_KEY",),
    )


def get_openai_llm_api_key(config: EngineConfig | None = None, *, route: str = "llm_candidate") -> str | None:
    route_env = ""
    conventional: tuple[str, ...]
    if route == "adjudicator":
        route_env = config.adjudicator_api_key_env if config else ""
        conventional = ("DUPE_ADJUDICATOR_API_KEY", "DUPE_LLM_API_KEY")
    else:
        route_env = config.llm_candidate_api_key_env if config else ""
        conventional = ("DUPE_LLM_CANDIDATE_API_KEY", "DUPE_LLM_API_KEY")
    return _openai_key_from_envs(config=config, route_api_key_env=route_env, conventional_envs=conventional)


def _api_key_present(provider: str, config: EngineConfig | None = None) -> bool:
    provider = provider.lower()
    if provider == "openai":
        return bool(get_openai_api_key(config))
    return False


def check_embeddings_status(config: EngineConfig) -> ProviderStatus:
    if not config.enable_embeddings:
        return ProviderStatus(
            layer="embeddings",
            enabled=False,
            available=False,
            provider=config.embeddings_provider,
            status="disabled",
            reason="DUPE_EMBEDDINGS_ENABLED=false or --embeddings not provided",
            model=config.embeddings_model or None,
            required=config.require_embeddings,
            role="detector",
        )

    provider = config.embeddings_provider.lower()
    endpoint_configured = bool(config.embeddings_base_url) or provider == "openai"
    model_configured = bool(config.embeddings_model)

    if config.embeddings_dry_run:
        return ProviderStatus(
            layer="embeddings",
            enabled=True,
            available=False,
            provider=provider,
            status="dry_run",
            reason="DUPE_EMBEDDINGS_DRY_RUN=true; provider calls disabled",
            model=config.embeddings_model or None,
            endpoint_configured=endpoint_configured,
            required=config.require_embeddings,
            role="detector",
            details=_embedding_details(config),
        )

    if provider == "openai":
        if not _api_key_present(provider, config):
            return ProviderStatus(
                layer="embeddings",
                enabled=True,
                available=False,
                provider=provider,
                status="unavailable",
                reason="OpenAI embeddings key not set; use DUPE_OPENAI_API_KEY/OPENAI_API_KEY or override with DUPE_EMBEDDINGS_API_KEY(_ENV)",
                model=config.embeddings_model or None,
                endpoint_configured=endpoint_configured,
                required=config.require_embeddings,
                role="detector",
                details=_embedding_details(config),
            )
        if not model_configured:
            return ProviderStatus(
                layer="embeddings",
                enabled=True,
                available=False,
                provider=provider,
                status="unavailable",
                reason="DUPE_EMBEDDINGS_MODEL is not set",
                model=None,
                endpoint_configured=endpoint_configured,
                required=config.require_embeddings,
                role="detector",
                details=_embedding_details(config),
            )
        return ProviderStatus(
            layer="embeddings",
            enabled=True,
            available=True,
            provider=provider,
            status="available",
            reason="embedding detector provider configured",
            model=config.embeddings_model or None,
            endpoint_configured=endpoint_configured,
            required=config.require_embeddings,
            role="detector",
            details=_embedding_details(config),
        )

    return ProviderStatus(
        layer="embeddings",
        enabled=True,
        available=False,
        provider=config.embeddings_provider,
        status="unknown_provider",
        reason=f"Unsupported embeddings provider: {config.embeddings_provider}; v0.9.8 supports openai only",
        model=config.embeddings_model or None,
        endpoint_configured=endpoint_configured,
        required=config.require_embeddings,
        role="detector",
        details=_embedding_details(config),
    )


def _embedding_details(config: EngineConfig) -> dict[str, Any]:
    return {
        "candidate_top_k": config.embeddings_candidate_top_k,
        "similarity_threshold": config.embeddings_similarity_threshold,
        "dimensions": config.embeddings_dimensions,
        "max_pairs_per_job": config.max_embedding_pairs_per_job,
        "max_pages_per_job": config.embeddings_max_pages_per_job,
        "batch_size": config.embeddings_batch_size,
        "min_words": config.embeddings_min_words,
        "min_text_chars": config.embeddings_min_text_chars,
        "create_candidates": config.embeddings_create_candidates,
        "skip_exact_matches": config.embeddings_skip_exact_matches,
        "provider_family": "openai",
        "base_url_configured": bool(config.embeddings_base_url or config.openai_base_url),
        "ai_route": "text_embedding",
        "input_kind": "page_text_pair",
    }


def check_llm_candidate_detector_status(config: EngineConfig) -> ProviderStatus:
    if not config.enable_llm_candidate_detector:
        return ProviderStatus(
            layer="llm_candidate_detector",
            enabled=False,
            available=False,
            provider=config.llm_candidate_provider,
            status="disabled",
            reason="DUPE_LLM_CANDIDATE_ENABLED=false or --llm-detector not provided",
            model=config.llm_candidate_model or None,
            required=config.require_llm_candidate_detector,
            role="detector",
        )
    return _check_openai_like_llm_layer(
        layer="llm_candidate_detector",
        provider=config.llm_candidate_provider,
        base_url=config.llm_candidate_base_url,
        model=config.llm_candidate_model,
        api_key_available=bool(get_openai_llm_api_key(config, route="llm_candidate")),
        required=config.require_llm_candidate_detector,
        role="detector",
        success_reason="LLM candidate detector configured; detector integration remains deferred",
        details={"threshold": config.llm_candidate_threshold, "ai_route": "text_adjudication", "input_kind": "structured_candidate_evidence"},
    )


def check_adjudicator_status(config: EngineConfig) -> ProviderStatus:
    if not config.enable_adjudicator:
        return ProviderStatus(
            layer="adjudicator_agent",
            enabled=False,
            available=False,
            provider=config.adjudicator_provider,
            status="disabled",
            reason="DUPE_ADJUDICATOR_ENABLED=false or --adjudicator not provided",
            model=config.adjudicator_model or None,
            required=config.require_adjudicator,
            role="adjudicator",
        )
    return _check_openai_like_llm_layer(
        layer="adjudicator_agent",
        provider=config.adjudicator_provider,
        base_url=config.adjudicator_base_url,
        model=config.adjudicator_model,
        api_key_available=bool(get_openai_llm_api_key(config, route="adjudicator")),
        required=config.require_adjudicator,
        role="adjudicator",
        success_reason="adjudicator agent configured; agent integration remains deferred",
        details={
            "borderline_only": config.adjudicator_borderline_only,
            "min_confidence": config.adjudicator_min_confidence,
            "max_confidence": config.adjudicator_max_confidence,
            "ai_route": "text_adjudication",
            "input_kind": "structured_candidate_evidence",
        },
    )


def _check_openai_like_llm_layer(
    layer: str,
    provider: str,
    base_url: str,
    model: str,
    api_key_available: bool,
    required: bool,
    role: str,
    success_reason: str,
    details: dict[str, Any],
) -> ProviderStatus:
    provider_normalized = provider.lower()
    endpoint_configured = bool(base_url) or provider_normalized == "openai"
    model_configured = bool(model)

    if provider_normalized == "openai":
        if not api_key_available:
            return ProviderStatus(
                layer=layer,
                enabled=True,
                available=False,
                provider=provider_normalized,
                status="unavailable",
                reason="OpenAI key not set; use DUPE_OPENAI_API_KEY/OPENAI_API_KEY or a route-specific override",
                model=model or None,
                endpoint_configured=endpoint_configured,
                required=required,
                role=role,
                details=details,
            )
        if not model_configured:
            reason = f"model is not set for {layer}"
            status = "unavailable"
            available = False
        else:
            reason = success_reason
            status = "provisioned_not_active"
            available = False
        return ProviderStatus(
            layer=layer,
            enabled=True,
            available=available,
            provider=provider_normalized,
            status=status,
            reason=reason,
            model=model or None,
            endpoint_configured=endpoint_configured,
            required=required,
            role=role,
            details=details,
        )

    return ProviderStatus(
        layer=layer,
        enabled=True,
        available=False,
        provider=provider,
        status="unknown_provider",
        reason=f"Unsupported provider for {layer}: {provider}; v0.9.8 supports openai only",
        model=model or None,
        endpoint_configured=endpoint_configured,
        required=required,
        role=role,
        details=details,
    )
