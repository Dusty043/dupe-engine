from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageEnhance, ImageOps

from .capabilities import (
    ProviderStatus,
    check_adjudicator_status,
    check_embeddings_status,
    check_llm_candidate_detector_status,
    check_openai_ocr_status,
    check_tesseract_ocr_status,
    get_openai_api_key,
    get_openai_ocr_api_key,
)
from .config import EngineConfig
from .models import AdjudicationResult, CandidateMatch

try:
    import pytesseract
except ImportError:  # Doctor/config will report OCR unavailable when required.
    pytesseract = None


@dataclass(frozen=True)
class OcrResult:
    text: str = ""
    provider: str = "none"
    confidence: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    provider: str
    model: str
    metadata: dict[str, object] = field(default_factory=dict)


class OcrProvider(Protocol):
    def healthcheck(self) -> ProviderStatus: ...
    def extract_page_text(self, image_path: Path) -> OcrResult: ...


class EmbeddingProvider(Protocol):
    def healthcheck(self) -> ProviderStatus: ...
    def embed_texts(self, texts: list[str]) -> EmbeddingResult: ...


class CandidateDetector(Protocol):
    def healthcheck(self) -> ProviderStatus: ...
    def detect_candidates(self, candidates: list[CandidateMatch]) -> list[CandidateMatch]: ...


class AdjudicatorAgent(Protocol):
    def healthcheck(self) -> ProviderStatus: ...
    def adjudicate(self, candidate: CandidateMatch) -> AdjudicationResult: ...


class NoopOcrProvider:
    def __init__(self, status: ProviderStatus):
        self._status = status

    def healthcheck(self) -> ProviderStatus:
        return self._status

    def extract_page_text(self, image_path: Path) -> OcrResult:
        return OcrResult(provider=self._status.provider, metadata={"skipped_reason": self._status.reason})


class TesseractOcrProvider:
    """Cheap worker-side OCR tier using Tesseract TSV output.

    v0.8 uses TSV so the engine can preserve an average word confidence and a
    profile name. The caller decides whether this result is usable.
    """

    def __init__(self, config: EngineConfig):
        self.config = config
        self._status = check_tesseract_ocr_status(config)

    def healthcheck(self) -> ProviderStatus:
        return self._status

    def extract_page_text(self, image_path: Path) -> OcrResult:
        if not self._status.available or pytesseract is None:
            return OcrResult(provider="tesseract", metadata={"skipped_reason": self._status.reason})

        best: OcrResult | None = None
        profiles = [p.strip() for p in self.config.tesseract_preprocessing_profiles.split(",") if p.strip()] or ["standard"]
        for profile in profiles:
            result = self._extract_with_profile(image_path, profile)
            if best is None or _ocr_result_rank(result) > _ocr_result_rank(best):
                best = result
        return best or OcrResult(provider="tesseract", metadata={"error": "no OCR profiles produced a result"})

    def _extract_with_profile(self, image_path: Path, profile: str) -> OcrResult:
        try:
            with Image.open(image_path) as image:
                processed = preprocess_image(image, profile)
                data = pytesseract.image_to_data(processed, output_type=pytesseract.Output.DICT)
        except Exception as exc:
            return OcrResult(provider="tesseract", metadata={"profile": profile, "error": str(exc)})

        words: list[str] = []
        confs: list[float] = []
        for text, conf in zip(data.get("text", []), data.get("conf", [])):
            word = str(text).strip()
            if not word:
                continue
            words.append(word)
            try:
                conf_value = float(conf)
            except (TypeError, ValueError):
                continue
            if conf_value >= 0:
                confs.append(conf_value)

        avg_conf = round(sum(confs) / len(confs), 2) if confs else None
        extracted = " ".join(words)
        usable = bool(avg_conf is not None and avg_conf >= self.config.tesseract_min_confidence and len(words) >= self.config.tesseract_min_words)
        return OcrResult(
            text=extracted,
            provider="tesseract",
            confidence=avg_conf,
            metadata={
                "profile": profile,
                "word_count": len(words),
                "confidence_count": len(confs),
                "usable": usable,
                "min_confidence": self.config.tesseract_min_confidence,
                "min_words": self.config.tesseract_min_words,
            },
        )


class OpenAIOcrProvider:
    """OpenAI OCR fallback for selected high-value pages.

    This uses an OpenAI chat-completions style vision request. v0.9.8 keeps
    OpenAI as the single AI provider family, with route-specific base URL/key
    overrides available for approved gateways. It is never called unless
    enabled, available, and selected by the OCR escalation policy.
    """

    def __init__(self, config: EngineConfig):
        self.config = config
        self._status = check_openai_ocr_status(config)
        self.api_key = get_openai_ocr_api_key(config) or ""
        self.base_url = ((config.openai_ocr_base_url or config.openai_base_url).rstrip("/") if (config.openai_ocr_base_url or config.openai_base_url) else "https://api.openai.com/v1")

    def healthcheck(self) -> ProviderStatus:
        return self._status

    def extract_page_text(self, image_path: Path) -> OcrResult:
        if not self._status.available:
            return OcrResult(provider=self._status.provider, metadata={"skipped_reason": self._status.reason})
        try:
            image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
            payload: dict[str, object] = {
                "model": self.config.openai_ocr_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are an OCR extraction component. Return only the text visible on the page. Preserve line order when reasonable. Do not summarize.",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Extract the readable text from this medical-record page. Return plain text only."},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                        ],
                    },
                ],
                "temperature": 0,
                "max_tokens": 2500,
            }
            data = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                url=f"{self.base_url}/chat/completions",
                data=data,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=self.config.openai_ocr_timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
            text = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            return OcrResult(
                text=str(text).strip(),
                provider=self.config.openai_ocr_provider,
                confidence=None,
                metadata={
                    "model": self.config.openai_ocr_model,
                    "response_id": body.get("id"),
                    "usage": body.get("usage", {}),
                },
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return OcrResult(provider=self.config.openai_ocr_provider, metadata={"error": f"HTTP {exc.code}: {detail[:500]}"})
        except Exception as exc:
            return OcrResult(provider=self.config.openai_ocr_provider, metadata={"error": str(exc)})


class NoopEmbeddingProvider:
    def __init__(self, status: ProviderStatus):
        self._status = status

    def healthcheck(self) -> ProviderStatus:
        return self._status

    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[],
            provider=self._status.provider,
            model=self._status.model or "",
            metadata={"skipped_reason": self._status.reason},
        )


class OpenAIEmbeddingProvider:
    """Minimal OpenAI embedding client using stdlib HTTP."""

    def __init__(self, config: EngineConfig):
        self.config = config
        self._status = check_embeddings_status(config)
        self.api_key = get_openai_api_key(config) or ""
        self.base_url = ((config.embeddings_base_url or config.openai_base_url).rstrip("/") if (config.embeddings_base_url or config.openai_base_url) else "https://api.openai.com/v1")

    def healthcheck(self) -> ProviderStatus:
        return self._status

    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        if not self._status.available:
            return EmbeddingResult(vectors=[], provider=self._status.provider, model=self.config.embeddings_model, metadata={"skipped_reason": self._status.reason})
        vectors: list[list[float]] = []
        for start in range(0, len(texts), max(1, self.config.embeddings_batch_size)):
            batch = texts[start : start + max(1, self.config.embeddings_batch_size)]
            vectors.extend(self._embed_batch(batch))
        return EmbeddingResult(
            vectors=vectors,
            provider=self._status.provider,
            model=self.config.embeddings_model,
            metadata={"batch_count": (len(texts) + max(1, self.config.embeddings_batch_size) - 1) // max(1, self.config.embeddings_batch_size)},
        )

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload: dict[str, object] = {"model": self.config.embeddings_model, "input": texts}
        if self.config.embeddings_dimensions:
            payload["dimensions"] = self.config.embeddings_dimensions
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url=f"{self.base_url}/embeddings",
            data=data,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.embeddings_timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"embedding provider HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"embedding provider request failed: {exc}") from exc
        items = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in items]


class NoopCandidateDetector:
    def __init__(self, status: ProviderStatus):
        self._status = status

    def healthcheck(self) -> ProviderStatus:
        return self._status

    def detect_candidates(self, candidates: list[CandidateMatch]) -> list[CandidateMatch]:
        return candidates


class NoopAdjudicatorAgent:
    def __init__(self, status: ProviderStatus):
        self._status = status

    def healthcheck(self) -> ProviderStatus:
        return self._status

    def adjudicate(self, candidate: CandidateMatch) -> AdjudicationResult:
        return AdjudicationResult(
            decision="not_run",
            confidence=0.0,
            reason=self._status.reason or "adjudicator agent not available",
            provider=self._status.provider,
            model=self._status.model,
        )


def preprocess_image(image: Image.Image, profile: str) -> Image.Image:
    if profile == "standard":
        return image.convert("RGB")
    gray = ImageOps.grayscale(image)
    if profile == "grayscale":
        return gray
    if profile == "high_contrast":
        return ImageEnhance.Contrast(gray).enhance(2.0)
    if profile == "threshold":
        enhanced = ImageEnhance.Contrast(gray).enhance(2.0)
        return enhanced.point(lambda pixel: 255 if pixel > 180 else 0)
    return image.convert("RGB")


def _ocr_result_rank(result: OcrResult) -> float:
    word_count = float(result.metadata.get("word_count", len(result.text.split())) or 0)
    confidence = float(result.confidence or 0)
    return confidence + min(word_count, 300.0) * 0.15


def make_ocr_provider(config: EngineConfig) -> OcrProvider:
    status = check_tesseract_ocr_status(config)
    if status.available:
        return TesseractOcrProvider(config)
    return NoopOcrProvider(status)


def make_openai_ocr_provider(config: EngineConfig) -> OcrProvider:
    status = check_openai_ocr_status(config)
    if status.available:
        return OpenAIOcrProvider(config)
    return NoopOcrProvider(status)


def make_embedding_provider(config: EngineConfig) -> EmbeddingProvider:
    status = check_embeddings_status(config)
    if status.available and config.embeddings_provider.lower() == "openai":
        return OpenAIEmbeddingProvider(config)
    return NoopEmbeddingProvider(status)
