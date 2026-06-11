from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .models import PageMatch, PageRecord

ROUTE_VISION_OCR_EXTRACTION = "vision_ocr_extraction"
ROUTE_TEXT_EMBEDDING = "text_embedding"
ROUTE_TEXT_ADJUDICATION = "text_adjudication"
ROUTE_VISION_PAIR_ADJUDICATION = "vision_pair_adjudication"

AI_ROUTE_POLICIES: dict[str, dict[str, str]] = {
    ROUTE_VISION_OCR_EXTRACTION: {
        "purpose": "Recover visible page text when native/Tesseract text is weak and deterministic evidence says the page matters.",
        "input_kind": "page_image",
        "default_gate": "weak native text; Tesseract attempted or unavailable; deterministic candidate exists; not low-information",
    },
    ROUTE_TEXT_EMBEDDING: {
        "purpose": "Compare best available page text semantically after deterministic candidate nomination.",
        "input_kind": "page_text",
        "default_gate": "deterministic candidate; non-exact pair; not low-information; enough best_text tokens",
    },
    ROUTE_TEXT_ADJUDICATION: {
        "purpose": "Review structured candidate evidence and suggest reviewer-facing explanation/label.",
        "input_kind": "structured_candidate_evidence",
        "default_gate": "candidate already surfaced and adjudicator policy selects it",
    },
    ROUTE_VISION_PAIR_ADJUDICATION: {
        "purpose": "Hard-case visual comparison of two rendered pages when OCR/text/embedding evidence remains inconclusive.",
        "input_kind": "page_image_pair_plus_evidence",
        "default_gate": "special escalation only; not part of default v0.8.1 flow",
    },
}

CSV_FIELDNAMES = [
    "route",
    "status",
    "provider",
    "model",
    "subject_type",
    "subject_id",
    "input_kind",
    "purpose",
    "reason",
    "selected",
    "attempted",
    "succeeded",
    "changed_evidence",
    "changed_matching",
    "dry_run",
    "cache_hit",
    "usage_total_tokens",
    "usage_prompt_tokens",
    "usage_completion_tokens",
    "error",
    "document_name",
    "page_number",
    "candidate_stage",
    "candidate_confidence",
    "pair_key",
    "metadata_json",
]


def make_ai_route_event(
    *,
    route: str,
    status: str,
    provider: str = "",
    model: str = "",
    subject_type: str = "",
    subject_id: str = "",
    input_kind: str = "",
    purpose: str = "",
    reason: str = "",
    selected: bool = False,
    attempted: bool = False,
    succeeded: bool = False,
    changed_evidence: bool = False,
    changed_matching: bool = False,
    dry_run: bool = False,
    cache_hit: bool = False,
    usage: dict[str, Any] | None = None,
    error: str = "",
    document_name: str = "",
    page_number: int | None = None,
    candidate_stage: str = "",
    candidate_confidence: float | None = None,
    pair_key: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = AI_ROUTE_POLICIES.get(route, {})
    return {
        "route": route,
        "status": status,
        "provider": provider,
        "model": model,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "input_kind": input_kind or policy.get("input_kind", ""),
        "purpose": purpose or policy.get("purpose", ""),
        "reason": reason,
        "selected": bool(selected),
        "attempted": bool(attempted),
        "succeeded": bool(succeeded),
        "changed_evidence": bool(changed_evidence),
        "changed_matching": bool(changed_matching),
        "dry_run": bool(dry_run),
        "cache_hit": bool(cache_hit),
        "usage": usage or {},
        "error": error,
        "document_name": document_name,
        "page_number": page_number,
        "candidate_stage": candidate_stage,
        "candidate_confidence": candidate_confidence,
        "pair_key": pair_key,
        "metadata": metadata or {},
    }


def add_page_ai_event(page: PageRecord, event: dict[str, Any]) -> None:
    page.ai_route_events.append(event)
    page.meta.setdefault("ai_route_events", []).append(event)


def add_match_ai_event(match: PageMatch, event: dict[str, Any]) -> None:
    match.ai_route_events.append(event)


def page_subject_id(page: PageRecord) -> str:
    return page.page_id


def pair_subject_id(match: PageMatch) -> str:
    return f"{match.page_a.page_id}|{match.page_b.page_id}"


def build_ai_call_ledger(
    pages: list[PageRecord],
    matches: list[PageMatch],
    capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records = collect_ai_call_records(pages, matches)
    return {
        "schema_version": "dupe_engine_ai_call_ledger_v0_8_1",
        "summary": summarize_ai_call_records(records),
        "route_policies": AI_ROUTE_POLICIES,
        "capabilities": capabilities or {},
        "records": records,
    }


def collect_ai_call_records(pages: list[PageRecord], matches: list[PageMatch]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for page in pages:
        for event in page.ai_route_events or page.meta.get("ai_route_events", []):
            normalized = normalize_event(event)
            key = event_key(normalized)
            if key not in seen:
                seen.add(key)
                records.append(normalized)

    for match in matches:
        for event in match.ai_route_events:
            normalized = normalize_event(event)
            key = event_key(normalized)
            if key not in seen:
                seen.add(key)
                records.append(normalized)

    return records


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    route = str(event.get("route", ""))
    policy = AI_ROUTE_POLICIES.get(route, {})
    normalized = dict(event)
    normalized.setdefault("input_kind", policy.get("input_kind", ""))
    normalized.setdefault("purpose", policy.get("purpose", ""))
    normalized.setdefault("usage", {})
    normalized.setdefault("metadata", {})
    for key in ["selected", "attempted", "succeeded", "changed_evidence", "changed_matching", "dry_run", "cache_hit"]:
        normalized[key] = bool(normalized.get(key, False))
    if normalized.get("page_number") is None:
        normalized["page_number"] = ""
    if normalized.get("candidate_confidence") is None:
        normalized["candidate_confidence"] = ""
    return normalized


def event_key(event: dict[str, Any]) -> str:
    return "|".join(
        str(event.get(part, ""))
        for part in [
            "route",
            "status",
            "subject_type",
            "subject_id",
            "reason",
            "candidate_stage",
            "candidate_confidence",
            "attempted",
            "dry_run",
        ]
    )


def summarize_ai_call_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_route = Counter(str(record.get("route", "unknown")) for record in records)
    by_status = Counter(str(record.get("status", "unknown")) for record in records)
    by_provider = Counter(str(record.get("provider", "unknown")) for record in records)
    route_status: dict[str, dict[str, int]] = {}
    for record in records:
        route = str(record.get("route", "unknown"))
        status = str(record.get("status", "unknown"))
        route_status.setdefault(route, {})[status] = route_status.setdefault(route, {}).get(status, 0) + 1
    return {
        "record_count": len(records),
        "selected_count": sum(1 for record in records if record.get("selected")),
        "attempted_count": sum(1 for record in records if record.get("attempted")),
        "succeeded_count": sum(1 for record in records if record.get("succeeded")),
        "changed_evidence_count": sum(1 for record in records if record.get("changed_evidence")),
        "changed_matching_count": sum(1 for record in records if record.get("changed_matching")),
        "dry_run_count": sum(1 for record in records if record.get("dry_run")),
        "error_count": sum(
            1
            for record in records
            if str(record.get("status", "")) == "error"
            or (bool(record.get("error")) and not str(record.get("status", "")).startswith(("dry_run", "skipped")))
        ),
        "by_route": dict(by_route),
        "by_status": dict(by_status),
        "by_provider": dict(by_provider),
        "route_status_counts": route_status,
    }


def flatten_ai_record(record: dict[str, Any]) -> dict[str, Any]:
    usage = record.get("usage") or {}
    metadata = record.get("metadata") or {}
    return {
        "route": record.get("route", ""),
        "status": record.get("status", ""),
        "provider": record.get("provider", ""),
        "model": record.get("model", ""),
        "subject_type": record.get("subject_type", ""),
        "subject_id": record.get("subject_id", ""),
        "input_kind": record.get("input_kind", ""),
        "purpose": record.get("purpose", ""),
        "reason": record.get("reason", ""),
        "selected": record.get("selected", False),
        "attempted": record.get("attempted", False),
        "succeeded": record.get("succeeded", False),
        "changed_evidence": record.get("changed_evidence", False),
        "changed_matching": record.get("changed_matching", False),
        "dry_run": record.get("dry_run", False),
        "cache_hit": record.get("cache_hit", False),
        "usage_total_tokens": usage.get("total_tokens", ""),
        "usage_prompt_tokens": usage.get("prompt_tokens", ""),
        "usage_completion_tokens": usage.get("completion_tokens", ""),
        "error": record.get("error", ""),
        "document_name": record.get("document_name", ""),
        "page_number": record.get("page_number", ""),
        "candidate_stage": record.get("candidate_stage", ""),
        "candidate_confidence": record.get("candidate_confidence", ""),
        "pair_key": record.get("pair_key", ""),
        "metadata_json": json.dumps(metadata, sort_keys=True),
    }


def write_ai_ledger_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for record in records:
            writer.writerow(flatten_ai_record(record))
