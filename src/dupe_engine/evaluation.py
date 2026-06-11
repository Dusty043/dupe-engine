from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .models import PageMatch, TruthPageRef, TruthPair


TRUTH_BUCKETS = [
    ("must_match", "duplicate"),
    ("should_not_match", "not_duplicate"),
    ("related_but_not_duplicate", "not_duplicate"),
    ("partial_overlap", "partial_overlap"),
    ("low_information_ignore", "low_information_ignore"),
]

TRUTH_CANDIDATE_FILENAMES = [
    "synthetic_v3_truth_pairs.json",
    "synthetic_v2_truth_pairs.json",
    "synthetic_all_pairs_truth.json",
    "truth_pairs.json",
    "ground_truth_pairs.json",
    "ground_truth.json",
    "truth.json",
]

DUPLICATE_LIKE_V3_LABELS = {"duplicate", "likely_duplicate", "possible_duplicate"}


class TruthFileError(ValueError):
    """Raised when an explicit eval truth file cannot produce pair-level truth records."""


@dataclass(frozen=True)
class TruthContext:
    """Outcome of optional truth-file resolution.

    Production-like runs usually do not have truth. Synthetic runs can provide a
    truth file explicitly or allow the engine to discover one near the PDF corpus.
    """

    status: str
    source: str
    path: Path | None = None
    pairs: list[TruthPair] | None = None
    message: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.pairs)

    def to_json(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "status": self.status,
            "source": self.source,
            "path": str(self.path) if self.path else None,
            "pair_count": len(self.pairs or []),
            "message": self.message,
            "warnings": self.warnings,
        }


def load_truth_pairs(path: Path) -> list[TruthPair]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TruthFileError(f"Truth file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise TruthFileError(f"Truth file is not valid JSON: {path}: {exc}") from exc

    if isinstance(data, list):
        pairs = load_v3_truth_pair_list(data)
        if not pairs:
            raise TruthFileError("No v3 pair-level truth pairs were found in the list-format truth file.")
        return pairs

    if not isinstance(data, dict):
        raise TruthFileError("Truth file must be either a JSON object with pair-level truth buckets or a v3 pair list.")

    pairs: list[TruthPair] = []

    for label_key, label in TRUTH_BUCKETS:
        bucket_items = data.get(label_key, [])
        if bucket_items is None:
            bucket_items = []
        if not isinstance(bucket_items, list):
            raise TruthFileError(f"Truth bucket '{label_key}' must be a list.")
        for idx, item in enumerate(bucket_items, start=1):
            if not isinstance(item, dict):
                raise TruthFileError(f"Truth bucket '{label_key}' item {idx} must be an object.")
            try:
                page_a, page_b = extract_truth_pages(item)
                pairs.append(
                    build_truth_pair(
                        page_a=page_a,
                        page_b=page_b,
                        label=label,
                        kind=str(item.get("type", item.get("kind", item.get("category", "unspecified")))),
                        notes=str(item.get("notes", item.get("reason", ""))),
                        metadata=item,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise TruthFileError(
                    f"Truth bucket '{label_key}' item {idx} must contain valid page refs with document/page fields."
                ) from exc

    if not pairs:
        bucket_names = ", ".join(label_key for label_key, _ in TRUTH_BUCKETS)
        if "groups" in data:
            raise TruthFileError(
                "No pair-level truth buckets were found. This looks like group-style corpus metadata; "
                f"use a pair-level truth JSON containing one of: {bucket_names}. "
                "For the bundled example corpus, use examples/truth/synthetic_all_pairs_truth.json."
            )
        raise TruthFileError(
            "No pair-level truth pairs were found. Expected a JSON file containing one of: "
            f"{bucket_names}."
        )
    return pairs


def load_v3_truth_pair_list(items: list[Any]) -> list[TruthPair]:
    pairs: list[TruthPair] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise TruthFileError(f"v3 truth pair item {idx} must be an object.")
        try:
            left_file = str(item["left_file"])
            right_file = str(item["right_file"])
            left_page = int(item["left_page"])
            right_page = int(item["right_page"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TruthFileError(
                f"v3 truth pair item {idx} must contain left_file/left_page/right_file/right_page."
            ) from exc

        v3_label = str(item.get("truth_label", "")).strip() or "unspecified"
        label = normalize_v3_truth_label(v3_label, item)
        kind = str(item.get("optional_internal_label") or f"{v3_label}|{item.get('expected_min_layer', 'unspecified')}|{item.get('difficulty', 'unspecified')}")
        pairs.append(
            build_truth_pair(
                page_a={"document": left_file, "page": left_page},
                page_b={"document": right_file, "page": right_page},
                label=label,
                kind=kind,
                notes=str(item.get("notes", "")),
                metadata=item,
            )
        )
    return pairs


def normalize_v3_truth_label(v3_label: str, item: dict[str, Any]) -> str:
    normalized = v3_label.strip().lower()
    if normalized == "partial_overlap":
        return "partial_overlap"
    if normalized == "low_information_ignore":
        return "low_information_ignore"
    if normalized == "not_duplicate":
        return "not_duplicate"
    if normalized in DUPLICATE_LIKE_V3_LABELS:
        return "duplicate"
    if bool(item.get("is_hard_negative")):
        return "not_duplicate"
    if item.get("is_must_match") is True:
        return "duplicate"
    return "not_duplicate"


def build_truth_pair(
    page_a: dict[str, Any],
    page_b: dict[str, Any],
    label: str,
    kind: str,
    notes: str,
    metadata: dict[str, Any] | None = None,
) -> TruthPair:
    metadata = metadata or {}
    return TruthPair(
        a=TruthPageRef(document=str(page_a["document"]), page=int(page_a["page"])),
        b=TruthPageRef(document=str(page_b["document"]), page=int(page_b["page"])),
        label=label,
        kind=kind,
        notes=notes,
        pair_id=metadata_str(metadata, "pair_id") or metadata_str(metadata, "v3_pair_id"),
        v3_truth_label=metadata_str(metadata, "truth_label") or metadata_str(metadata, "v3_truth_label"),
        expected_min_layer=metadata_str(metadata, "expected_min_layer"),
        required_layers=metadata_list(metadata, "required_layers"),
        difficulty=metadata_str(metadata, "difficulty"),
        is_must_match=metadata_bool(metadata, "is_must_match"),
        is_hard_negative=metadata_bool(metadata, "is_hard_negative"),
        vision_fallback_expected=metadata_bool(metadata, "vision_fallback_expected"),
        reason_tags=metadata_list(metadata, "reason_tags"),
        raw_metadata=dict(metadata),
    )


def metadata_str(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def metadata_bool(metadata: dict[str, Any], key: str) -> bool | None:
    if key not in metadata:
        return None
    value = metadata.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def metadata_list(metadata: dict[str, Any], key: str) -> list[str]:
    value = metadata.get(key)
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value)]


def resolve_truth_context(
    explicit_path: str | Path | None = None,
    search_roots: Iterable[Path] | None = None,
    auto_detect: bool = True,
) -> TruthContext:
    """Resolve optional truth.

    Explicit truth is strict: a missing or invalid file raises TruthFileError.
    Auto-detected truth is opportunistic: invalid candidates become warnings and
    the run continues without evaluation.
    """
    if explicit_path:
        path = Path(explicit_path)
        pairs = load_truth_pairs(path)
        return TruthContext(
            status="available",
            source="explicit",
            path=path,
            pairs=pairs,
            message=f"Using explicit truth file: {path}",
        )

    if not auto_detect:
        return TruthContext(
            status="disabled",
            source="disabled",
            pairs=None,
            message="Truth auto-detection disabled; evaluation metrics were skipped.",
        )

    warnings: list[str] = []
    for path in candidate_truth_paths(search_roots or []):
        if not path.exists() or not path.is_file():
            continue
        try:
            pairs = load_truth_pairs(path)
        except TruthFileError as exc:
            warnings.append(f"Skipped invalid auto-detected truth candidate {path}: {exc}")
            continue
        return TruthContext(
            status="available",
            source="auto_detected",
            path=path,
            pairs=pairs,
            message=f"Auto-detected pair-level truth file: {path}",
            warnings=warnings,
        )

    message = "No pair-level truth file found; evaluation metrics were skipped."
    return TruthContext(status="not_found", source="auto_detect", pairs=None, message=message, warnings=warnings)


def candidate_truth_paths(search_roots: Iterable[Path]) -> list[Path]:
    roots: list[Path] = []
    for raw_root in search_roots:
        root = Path(raw_root)
        if root in roots:
            continue
        roots.append(root)
        if root.name == "pdfs":
            for extra in [root.parent, root.parent / "truth", root.parent.parent / "truth", root.parent.parent]:
                if extra not in roots:
                    roots.append(extra)
        else:
            for extra in [root / "truth", root.parent / "truth"]:
                if extra not in roots:
                    roots.append(extra)

    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        for name in TRUTH_CANDIDATE_FILENAMES:
            path = root / name
            if path in seen:
                continue
            seen.add(path)
            candidates.append(path)
    return candidates


def extract_truth_pages(item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if "a" in item and "b" in item:
        return item["a"], item["b"]
    if "page_1" in item and "page_2" in item:
        return item["page_1"], item["page_2"]
    raise KeyError("truth pair must contain either a/b or page_1/page_2")


def evaluate_matches(matches: list[PageMatch], truth_pairs: list[TruthPair], threshold: float = 0.0) -> dict[str, Any]:
    predicted = {
        match_key_from_pages(match.page_a.document_name, match.page_a.page_number, match.page_b.document_name, match.page_b.page_number): match
        for match in matches
        if match.confidence >= threshold
    }

    must_match = {pair.unordered_key: pair for pair in truth_pairs if pair.label == "duplicate"}
    should_not_match = {pair.unordered_key: pair for pair in truth_pairs if pair.label == "not_duplicate"}
    partial_overlap = {pair.unordered_key: pair for pair in truth_pairs if pair.label == "partial_overlap"}
    low_information_ignore = {pair.unordered_key: pair for pair in truth_pairs if pair.label == "low_information_ignore"}

    true_positives = []
    false_negatives = []
    expected_negative_hits = []
    partial_hits = []
    low_information_hits = []

    for key, pair in must_match.items():
        if key in predicted:
            true_positives.append(match_to_eval_json(predicted[key], pair))
        else:
            false_negatives.append(truth_to_json(pair))

    for key, pair in should_not_match.items():
        if key in predicted:
            expected_negative_hits.append(match_to_eval_json(predicted[key], pair))

    for key, pair in partial_overlap.items():
        if key in predicted:
            partial_hits.append(match_to_eval_json(predicted[key], pair))

    for key, pair in low_information_ignore.items():
        if key in predicted:
            low_information_hits.append(match_to_eval_json(predicted[key], pair))

    known_truth = set(must_match) | set(should_not_match) | set(partial_overlap) | set(low_information_ignore)
    unknown_predictions = [
        match_to_prediction_json(match)
        for key, match in predicted.items()
        if key not in known_truth
    ]

    layer_breakdown = build_recall_by_expected_layer(must_match.values(), predicted)

    return {
        "threshold": threshold,
        "summary": {
            "predicted_match_count": len(predicted),
            "truth_duplicate_count": len(must_match),
            "truth_should_not_match_count": len(should_not_match),
            "truth_partial_overlap_count": len(partial_overlap),
            "truth_low_information_ignore_count": len(low_information_ignore),
            "true_positive_count": len(true_positives),
            "false_negative_count": len(false_negatives),
            "expected_negative_hit_count": len(expected_negative_hits),
            "partial_overlap_hit_count": len(partial_hits),
            "low_information_ignore_hit_count": len(low_information_hits),
            "unknown_prediction_count": len(unknown_predictions),
            "recall_on_must_match": safe_div(len(true_positives), len(must_match)),
            "known_negative_hit_rate": safe_div(len(expected_negative_hits), len(should_not_match)),
            "low_information_hit_rate": safe_div(len(low_information_hits), len(low_information_ignore)),
            "recall_by_expected_min_layer": layer_breakdown,
        },
        "true_positives": true_positives,
        "false_negatives": false_negatives,
        "expected_negative_hits": expected_negative_hits,
        "partial_overlap_hits": partial_hits,
        "low_information_ignore_hits": low_information_hits,
        "unknown_predictions": unknown_predictions,
    }


def build_recall_by_expected_layer(
    truth_pairs: Iterable[TruthPair],
    predicted: dict[tuple[tuple[str, int], tuple[str, int]], PageMatch],
) -> dict[str, dict[str, Any]]:
    breakdown: dict[str, dict[str, Any]] = {}
    for pair in truth_pairs:
        layer = pair.expected_min_layer or "unspecified"
        bucket = breakdown.setdefault(layer, {"truth_count": 0, "true_positive_count": 0, "false_negative_count": 0, "recall": None})
        bucket["truth_count"] += 1
        if pair.unordered_key in predicted:
            bucket["true_positive_count"] += 1
        else:
            bucket["false_negative_count"] += 1
    for bucket in breakdown.values():
        bucket["recall"] = safe_div(int(bucket["true_positive_count"]), int(bucket["truth_count"]))
    return dict(sorted(breakdown.items()))


def build_no_truth_eval_report(matches: list[PageMatch], threshold: float, truth_context: TruthContext) -> dict[str, Any]:
    predicted = [match for match in matches if match.confidence >= threshold]
    return {
        "threshold": threshold,
        "evaluation_available": False,
        "truth_status": truth_context.to_json(),
        "summary": {
            "predicted_match_count": len(predicted),
            "truth_duplicate_count": None,
            "truth_should_not_match_count": None,
            "truth_partial_overlap_count": None,
            "truth_low_information_ignore_count": None,
            "true_positive_count": None,
            "false_negative_count": None,
            "expected_negative_hit_count": None,
            "partial_overlap_hit_count": None,
            "low_information_ignore_hit_count": None,
            "unknown_prediction_count": None,
            "recall_on_must_match": None,
            "known_negative_hit_rate": None,
            "low_information_hit_rate": None,
            "recall_by_expected_min_layer": {},
        },
        "note": truth_context.message,
    }


def match_key_from_pages(doc_a: str, page_a: int, doc_b: str, page_b: int) -> tuple[tuple[str, int], tuple[str, int]]:
    return tuple(sorted(((doc_a, int(page_a)), (doc_b, int(page_b)))))  # type: ignore[return-value]


def match_to_eval_json(match: PageMatch, truth: TruthPair) -> dict[str, Any]:
    payload = match_to_prediction_json(match)
    payload["truth"] = truth_to_json(truth)
    return payload


def match_to_prediction_json(match: PageMatch) -> dict[str, Any]:
    return {
        "match_type": match.match_type,
        "confidence": round(match.confidence, 4),
        "candidate_stage": match.candidate_stage,
        "recommendation": match.recommendation,
        "engine_candidate_label": match.engine_candidate_label,
        "adjudicator_suggested_label": match.adjudicator_suggested_label,
        "human_final_label": match.human_final_label,
        "visibility": match.visibility,
        "visibility_reason": match.visibility_reason,
        "candidate_category": match.candidate_category,
        "a": {"document": match.page_a.document_name, "page": match.page_a.page_number},
        "b": {"document": match.page_b.document_name, "page": match.page_b.page_number},
        "page_a_low_information": match.page_a.is_low_information,
        "page_b_low_information": match.page_b.is_low_information,
        "signals": [signal.to_json() for signal in match.signals],
    }


def truth_to_json(pair: TruthPair) -> dict[str, Any]:
    return {
        "a": {"document": pair.a.document, "page": pair.a.page},
        "b": {"document": pair.b.document, "page": pair.b.page},
        "label": pair.label,
        "type": pair.kind,
        "notes": pair.notes,
        "pair_id": pair.pair_id,
        "v3_truth_label": pair.v3_truth_label,
        "expected_min_layer": pair.expected_min_layer,
        "required_layers": pair.required_layers,
        "difficulty": pair.difficulty,
        "is_must_match": pair.is_must_match,
        "is_hard_negative": pair.is_hard_negative,
        "vision_fallback_expected": pair.vision_fallback_expected,
        "reason_tags": pair.reason_tags,
    }


def safe_div(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)
