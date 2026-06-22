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
    check_bedrock_embeddings_status,
    check_bedrock_ocr_status,
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


class BedrockOcrProvider:
    """Amazon Bedrock Claude vision OCR fallback.

    Uses the Bedrock InvokeModel API with the Anthropic messages format.
    boto3 is imported lazily so the rest of the engine works without it.
    Configure via DUPE_BEDROCK_OCR_MODEL and DUPE_BEDROCK_REGION.
    """

    def __init__(self, config: EngineConfig):
        self.config = config
        self._status = check_bedrock_ocr_status(config)

    def healthcheck(self) -> ProviderStatus:
        return self._status

    def extract_page_text(self, image_path: Path) -> OcrResult:
        if not self._status.available:
            return OcrResult(provider="bedrock", metadata={"skipped_reason": self._status.reason})
        try:
            import boto3  # noqa: PLC0415
        except ImportError:
            return OcrResult(provider="bedrock", metadata={"skipped_reason": "boto3 not installed"})
        try:
            image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
            client = boto3.client(
                "bedrock-runtime",
                region_name=self.config.bedrock_region,
            )
            payload = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2500,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Extract the readable text from this medical-record page. Return plain text only.",
                        },
                    ],
                }],
            }
            response = client.invoke_model(
                modelId=self.config.bedrock_ocr_model,
                body=json.dumps(payload),
                contentType="application/json",
                accept="application/json",
            )
            body = json.loads(response["body"].read())
            text = body.get("content", [{}])[0].get("text", "")
            usage = body.get("usage", {})
            return OcrResult(
                text=str(text).strip(),
                provider="bedrock",
                confidence=None,
                metadata={
                    "model": self.config.bedrock_ocr_model,
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                },
            )
        except Exception as exc:
            return OcrResult(provider="bedrock", metadata={"error": str(exc)})


def make_vision_ocr_provider(config: EngineConfig) -> OcrProvider:
    """Return the vision OCR provider chain for the current config.

    When DUPE_VISION_OCR_PROVIDER=bedrock:
      Primary:  BedrockOcrProvider
      Failsafe: OpenAIOcrProvider (only used if Bedrock returns an error;
                skipped silently if no OpenAI key is configured)

    When DUPE_VISION_OCR_PROVIDER=openai (default):
      Primary:  OpenAIOcrProvider (no failsafe needed)
    """
    if config.vision_ocr_provider.lower() == "bedrock":
        bedrock_status = check_bedrock_ocr_status(config)
        primary: OcrProvider = BedrockOcrProvider(config) if bedrock_status.available else NoopOcrProvider(bedrock_status)
        openai_status = check_openai_ocr_status(config)
        failsafe: OcrProvider | None = OpenAIOcrProvider(config) if openai_status.available else None
        return _CascadeOcrProvider(primary, failsafe)
    return make_openai_ocr_provider(config)


class _CascadeOcrProvider:
    """Try primary; on error silently fall back to failsafe if available.

    Used for Bedrock → OpenAI cascade. Both providers are independently
    observable: result.provider carries the name of whichever actually ran,
    and metadata["cascade_from"] is set when the failsafe took over.
    """

    def __init__(self, primary: OcrProvider, failsafe: OcrProvider | None):
        self._primary = primary
        self._failsafe = failsafe

    def healthcheck(self) -> ProviderStatus:
        return self._primary.healthcheck()

    def extract_page_text(self, image_path: Path) -> OcrResult:
        result = self._primary.extract_page_text(image_path)
        if result.metadata.get("error") and self._failsafe is not None:
            fallback = self._failsafe.extract_page_text(image_path)
            if not fallback.metadata.get("error") and not fallback.metadata.get("skipped_reason"):
                return OcrResult(
                    text=fallback.text,
                    provider=fallback.provider,
                    confidence=fallback.confidence,
                    metadata={
                        **fallback.metadata,
                        "cascade_from": result.provider,
                        "cascade_reason": "primary_error",
                        "cascade_primary_error": result.metadata.get("error", ""),
                    },
                )
        return result


class BedrockEmbeddingProvider:
    """Amazon Titan Embeddings V2 via Bedrock IAM auth.

    Titan takes one text per InvokeModel call (no batch array like OpenAI).
    embed_texts loops over inputs; boto3 is imported lazily so the rest of
    the engine works without it installed.

    Supported dimensions: 256, 512, 1024 (default). Set DUPE_EMBEDDINGS_DIMENSIONS
    to override. Vectors are normalized by default.
    """

    def __init__(self, config: EngineConfig):
        self.config = config
        self._status = check_bedrock_embeddings_status(config)

    def healthcheck(self) -> ProviderStatus:
        return self._status

    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        if not self._status.available:
            return EmbeddingResult(
                vectors=[],
                provider="bedrock",
                model=self.config.bedrock_embeddings_model,
                metadata={"skipped_reason": self._status.reason},
            )
        try:
            import boto3  # noqa: PLC0415
        except ImportError:
            return EmbeddingResult(
                vectors=[],
                provider="bedrock",
                model=self.config.bedrock_embeddings_model,
                metadata={"skipped_reason": "boto3 not installed"},
            )
        client = boto3.client("bedrock-runtime", region_name=self.config.bedrock_region)
        vectors: list[list[float]] = []
        total_tokens = 0
        for text in texts:
            payload: dict[str, object] = {"inputText": text, "normalize": True}
            if self.config.embeddings_dimensions:
                payload["dimensions"] = self.config.embeddings_dimensions
            response = client.invoke_model(
                modelId=self.config.bedrock_embeddings_model,
                body=json.dumps(payload),
                contentType="application/json",
                accept="application/json",
            )
            body = json.loads(response["body"].read())
            vectors.append(body["embedding"])
            total_tokens += body.get("inputTextTokenCount", 0)
        return EmbeddingResult(
            vectors=vectors,
            provider="bedrock",
            model=self.config.bedrock_embeddings_model,
            metadata={"total_input_tokens": total_tokens, "text_count": len(texts)},
        )


def make_embedding_provider(config: EngineConfig) -> EmbeddingProvider:
    provider = config.embeddings_provider.lower()
    if provider == "bedrock":
        status = check_bedrock_embeddings_status(config)
        if status.available:
            return BedrockEmbeddingProvider(config)
        return NoopEmbeddingProvider(status)
    status = check_embeddings_status(config)
    if status.available and provider == "openai":
        return OpenAIEmbeddingProvider(config)
    return NoopEmbeddingProvider(status)
