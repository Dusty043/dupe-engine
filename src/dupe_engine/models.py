from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PageRecord:
    group: str
    document_id: str
    document_name: str
    page_number: int
    image_path: str

    # Backwards-compatible field. This is the best available text used by the
    # current deterministic matching layers.
    raw_text: str = ""
    normalized_text: str = ""
    comparison_text: str = ""
    text_hash: str | None = None

    exact_image_hash: str | None = None
    perceptual_hash: str | None = None
    ocr_used: bool = False

    # Text provenance fields. These make OCR/AI provenance visible without
    # putting PHI text in reports by default.
    native_text: str = ""
    ocr_text: str = ""
    best_text: str = ""
    text_source: str = "none"  # native | ocr | native_plus_ocr | none
    ocr_confidence: float | None = None
    native_word_count: int = 0
    ocr_word_count: int = 0
    best_word_count: int = 0

    # v0.8 tiered OCR route fields. These remain metadata-only unless text
    # previews are explicitly enabled; reports can still show which OCR tier
    # was attempted/used without exposing extracted PHI text.
    native_text_status: str = "unknown"  # usable | weak | missing
    tesseract_attempted: bool = False
    tesseract_text: str = ""
    tesseract_confidence: float | None = None
    tesseract_word_count: int = 0
    tesseract_usable: bool = False
    tesseract_profile: str | None = None
    openai_ocr_selected: bool = False
    openai_ocr_attempted: bool = False
    openai_ocr_text: str = ""
    openai_ocr_word_count: int = 0
    openai_ocr_usable: bool = False
    openai_ocr_provider: str | None = None
    openai_ocr_model: str | None = None
    openai_ocr_selection_reason: str | None = None
    openai_ocr_skip_reason: str | None = None
    openai_ocr_error: str | None = None
    ocr_route: str = "native_only"
    ocr_escalation_reason: str | None = None
    best_text_source: str = "none"

    is_low_information: bool = False
    low_information_reason: str | None = None

    meta: dict[str, Any] = field(default_factory=dict)
    ai_route_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def page_id(self) -> str:
        return f"{self.group}:{self.document_id}:{self.page_number}"

    @property
    def page_key(self) -> tuple[str, int]:
        return (self.document_name, self.page_number)

    def to_json(self, include_text: bool = False, text_preview_chars: int = 300) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "page_id": self.page_id,
            "group": self.group,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "page_number": self.page_number,
            "image_path": self.image_path,
            "ocr_used": self.ocr_used,
            "text_source": self.text_source,
            "ocr_confidence": self.ocr_confidence,
            "native_word_count": self.native_word_count,
            "ocr_word_count": self.ocr_word_count,
            "best_word_count": self.best_word_count,
            "native_text_status": self.native_text_status,
            "tesseract_attempted": self.tesseract_attempted,
            "tesseract_confidence": self.tesseract_confidence,
            "tesseract_word_count": self.tesseract_word_count,
            "tesseract_usable": self.tesseract_usable,
            "tesseract_profile": self.tesseract_profile,
            "openai_ocr_selected": self.openai_ocr_selected,
            "openai_ocr_attempted": self.openai_ocr_attempted,
            "openai_ocr_word_count": self.openai_ocr_word_count,
            "openai_ocr_usable": self.openai_ocr_usable,
            "openai_ocr_provider": self.openai_ocr_provider,
            "openai_ocr_model": self.openai_ocr_model,
            "openai_ocr_selection_reason": self.openai_ocr_selection_reason,
            "openai_ocr_skip_reason": self.openai_ocr_skip_reason,
            "openai_ocr_error": self.openai_ocr_error,
            "ocr_route": self.ocr_route,
            "ocr_escalation_reason": self.ocr_escalation_reason,
            "best_text_source": self.best_text_source,
            "is_low_information": self.is_low_information,
            "low_information_reason": self.low_information_reason,
            "text_hash": self.text_hash,
            "exact_image_hash": self.exact_image_hash,
            "perceptual_hash": self.perceptual_hash,
            "meta": self.meta,
            "ai_route_events": self.ai_route_events,
        }
        if include_text:
            payload["text_preview"] = self.raw_text.replace("\n", " ").strip()[:text_preview_chars]
        return payload


@dataclass
class MatchSignal:
    name: str
    score: float
    details: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeterministicPassRecord:
    pass_name: str
    layer: str
    matched: bool
    score: float | None = None
    threshold: float | None = None
    metric: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EscalationDecision:
    embedding_required: bool = False
    llm_detector_required: bool = False
    adjudicator_required: bool = False
    reason: str = ""
    policy: str = "deterministic_multipass_v1"

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageMatch:
    """Legacy-compatible match object returned by current detectors.

    v0.4 treats this as an aggregated detector candidate. It remains the primary object for
    current JSON/CSV/HTML reports until calibration decides the final candidate
    and adjudication schemas.
    """

    match_type: str
    confidence: float
    page_a: PageRecord
    page_b: PageRecord
    signals: list[MatchSignal]
    recommendation: str = "review"
    candidate_stage: str = "single_threshold"
    review_bucket: str = "needs_review"
    review_priority: str = "medium"
    review_rationale: str = ""
    engine_candidate_label: str = "needs_review"
    adjudicator_suggested_label: str | None = None
    human_final_label: str | None = None
    visibility: str = "main_review_list"
    visibility_reason: str = ""
    candidate_category: str = "standard"
    deterministic_passes: list[DeterministicPassRecord] = field(default_factory=list)
    escalation: EscalationDecision = field(default_factory=EscalationDecision)
    ai_route_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def pair_key_ordered(self) -> tuple[str, str]:
        return (self.page_a.page_id, self.page_b.page_id)

    @property
    def pair_key_unordered(self) -> tuple[str, str]:
        return tuple(sorted((self.page_a.page_id, self.page_b.page_id)))  # type: ignore[return-value]

    @property
    def candidate_sources(self) -> list[str]:
        return [signal.name for signal in self.signals]

    def to_json(self, include_text: bool = False, text_preview_chars: int = 300) -> dict[str, Any]:
        return {
            "schema_role": "detector_candidate",
            "match_type": self.match_type,
            "confidence": round(self.confidence, 4),
            "candidate_sources": self.candidate_sources,
            "recommendation": self.recommendation,
            "candidate_stage": self.candidate_stage,
            "review_bucket": self.review_bucket,
            "review_priority": self.review_priority,
            "review_rationale": self.review_rationale,
            "engine_candidate_label": self.engine_candidate_label,
            "adjudicator_suggested_label": self.adjudicator_suggested_label,
            "human_final_label": self.human_final_label,
            "visibility": self.visibility,
            "visibility_reason": self.visibility_reason,
            "candidate_category": self.candidate_category,
            "deterministic_passes": [record.to_json() for record in self.deterministic_passes],
            "escalation": self.escalation.to_json(),
            "ai_route_events": self.ai_route_events,
            "page_a": self.page_a.to_json(include_text=include_text, text_preview_chars=text_preview_chars),
            "page_b": self.page_b.to_json(include_text=include_text, text_preview_chars=text_preview_chars),
            "signals": [signal.to_json() for signal in self.signals],
        }


@dataclass
class CandidateMatch:
    """Candidate pair emitted by one or more detectors.

    This is the forward-looking detector output schema. Calibration will decide
    the final scoring details later; for now it documents the separation between
    detection and adjudication.
    """

    page_a: PageRecord
    page_b: PageRecord
    detector_signals: list[MatchSignal]
    candidate_score: float
    candidate_label: str
    candidate_sources: list[str]
    candidate_stage: str = "single_threshold"
    review_bucket: str = "needs_review"
    review_priority: str = "medium"
    review_rationale: str = ""
    engine_candidate_label: str = "needs_review"
    adjudicator_suggested_label: str | None = None
    human_final_label: str | None = None
    visibility: str = "main_review_list"
    visibility_reason: str = ""
    candidate_category: str = "standard"
    deterministic_passes: list[DeterministicPassRecord] = field(default_factory=list)
    escalation: EscalationDecision = field(default_factory=EscalationDecision)
    needs_adjudication: bool = False
    ai_route_events: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_page_match(cls, match: PageMatch, needs_adjudication: bool = False) -> "CandidateMatch":
        return cls(
            page_a=match.page_a,
            page_b=match.page_b,
            detector_signals=list(match.signals),
            candidate_score=match.confidence,
            candidate_label=match.match_type,
            candidate_sources=match.candidate_sources,
            candidate_stage=match.candidate_stage,
            review_bucket=match.review_bucket,
            review_priority=match.review_priority,
            review_rationale=match.review_rationale,
            engine_candidate_label=match.engine_candidate_label,
            adjudicator_suggested_label=match.adjudicator_suggested_label,
            human_final_label=match.human_final_label,
            visibility=match.visibility,
            visibility_reason=match.visibility_reason,
            candidate_category=match.candidate_category,
            deterministic_passes=list(match.deterministic_passes),
            escalation=match.escalation,
            needs_adjudication=needs_adjudication or match.escalation.adjudicator_required,
            ai_route_events=list(match.ai_route_events),
        )

    def to_json(self, include_text: bool = False, text_preview_chars: int = 300) -> dict[str, Any]:
        return {
            "schema_role": "candidate_match",
            "candidate_label": self.candidate_label,
            "candidate_score": round(self.candidate_score, 4),
            "candidate_sources": self.candidate_sources,
            "candidate_stage": self.candidate_stage,
            "review_bucket": self.review_bucket,
            "review_priority": self.review_priority,
            "review_rationale": self.review_rationale,
            "engine_candidate_label": self.engine_candidate_label,
            "adjudicator_suggested_label": self.adjudicator_suggested_label,
            "human_final_label": self.human_final_label,
            "visibility": self.visibility,
            "visibility_reason": self.visibility_reason,
            "candidate_category": self.candidate_category,
            "needs_adjudication": self.needs_adjudication,
            "deterministic_passes": [record.to_json() for record in self.deterministic_passes],
            "escalation": self.escalation.to_json(),
            "ai_route_events": self.ai_route_events,
            "page_a": self.page_a.to_json(include_text=include_text, text_preview_chars=text_preview_chars),
            "page_b": self.page_b.to_json(include_text=include_text, text_preview_chars=text_preview_chars),
            "detector_signals": [signal.to_json() for signal in self.detector_signals],
        }


@dataclass
class AdjudicationResult:
    decision: str
    confidence: float
    reason: str
    supporting_factors: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    provider: str = "none"
    model: str | None = None
    raw_response_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdjudicatedMatch:
    candidate: CandidateMatch
    adjudication: AdjudicationResult
    final_label: str
    final_confidence: float
    human_recommendation: str = "review"

    def to_json(self, include_text: bool = False, text_preview_chars: int = 300) -> dict[str, Any]:
        return {
            "schema_role": "adjudicated_match",
            "final_label": self.final_label,
            "final_confidence": round(self.final_confidence, 4),
            "human_recommendation": self.human_recommendation,
            "candidate": self.candidate.to_json(include_text=include_text, text_preview_chars=text_preview_chars),
            "adjudication": self.adjudication.to_json(),
        }


@dataclass(frozen=True)
class TruthPageRef:
    document: str
    page: int

    @property
    def key(self) -> tuple[str, int]:
        return (self.document, self.page)


@dataclass(frozen=True)
class TruthPair:
    a: TruthPageRef
    b: TruthPageRef
    label: str
    kind: str = "unspecified"
    notes: str = ""

    # v0.8.6+ optional rich truth metadata. These fields let synthetic v3
    # corpuses attribute misses/hits to the expected engine layer without
    # breaking older bucket-style truth files.
    pair_id: str | None = None
    v3_truth_label: str | None = None
    expected_min_layer: str | None = None
    required_layers: list[str] = field(default_factory=list)
    difficulty: str | None = None
    is_must_match: bool | None = None
    is_hard_negative: bool | None = None
    vision_fallback_expected: bool | None = None
    reason_tags: list[str] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def unordered_key(self) -> tuple[tuple[str, int], tuple[str, int]]:
        return tuple(sorted((self.a.key, self.b.key)))  # type: ignore[return-value]
