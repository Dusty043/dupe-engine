from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any

from .adjudication import noop_adjudicate_many
from .ai_ledger import build_ai_call_ledger
from .candidates import summarize_candidates, to_candidate_matches
from .capabilities import CapabilityReport
from .config import EngineConfig
from .embedding_reranker import summarize_reranker
from .models import PageMatch, PageRecord
from .page_quality import count_low_information_pages

ENGINE_VERSION = "0.8.1"


def build_report(
    pages_a: list[PageRecord] | None,
    pages_b: list[PageRecord] | None,
    matches: list[PageMatch],
    config: EngineConfig,
    mode: str,
    capabilities: CapabilityReport | None = None,
) -> dict[str, Any]:
    all_pages = (pages_a or []) + (pages_b or [])
    candidates = to_candidate_matches(matches, config)
    adjudicated = noop_adjudicate_many(candidates, config)
    ai_ledger_summary = build_ai_call_ledger(all_pages, matches, capabilities.to_json() if capabilities else {}).get("summary", {})
    return {
        "engine_version": ENGINE_VERSION,
        "mode": mode,
        "schema_notes": build_schema_notes(),
        "capabilities": capabilities.to_json() if capabilities else {},
        "ai_call_summary": ai_ledger_summary,
        "summary": {
            "group_a_pages": len(pages_a or []),
            "group_b_pages": len(pages_b or []),
            "total_pages": len(all_pages),
            "match_count": len(matches),
            "match_counts_by_type": count_by_type(matches),
            "ocr_pages": sum(1 for page in all_pages if page.ocr_used),
            "tesseract_attempted_pages": sum(1 for page in all_pages if page.tesseract_attempted),
            "tesseract_usable_pages": sum(1 for page in all_pages if page.tesseract_usable),
            "openai_ocr_selected_pages": sum(1 for page in all_pages if page.openai_ocr_selected),
            "openai_ocr_attempted_pages": sum(1 for page in all_pages if page.openai_ocr_attempted),
            "openai_ocr_usable_pages": sum(1 for page in all_pages if page.openai_ocr_usable),
            "openai_ocr_improved_pages": sum(1 for page in all_pages if page.ocr_route == "openai_ocr_fallback"),
            "openai_ocr_selection_mode": config.openai_ocr_selection_mode,
            "openai_ocr_max_pages_per_job": config.openai_ocr_max_pages_per_job,
            "openai_ocr_max_pages_per_document": config.openai_ocr_max_pages_per_document,
            "openai_ocr_accept_cleaner_shorter_text": config.openai_ocr_accept_cleaner_shorter_text,
            "openai_ocr_skip_reason_counts": count_openai_ocr_skip_reasons(all_pages),
            "openai_ocr_selection_reason_counts": count_openai_ocr_selection_reasons(all_pages),
            "text_source_counts": count_text_sources(all_pages),
            "ocr_route_counts": count_ocr_routes(all_pages),
            "low_information_pages": count_low_information_pages(all_pages),
            "embedding_signal_count": count_signal(matches, "embedding_similarity"),
            "embedding_candidate_count": count_by_type(matches).get("embedding_similarity_candidate", 0),
            "hybrid_vector_candidate_count": count_by_type(matches).get("hybrid_vector_candidate", 0),
            "embedding_supported_candidate_count": count_by_type(matches).get("embedding_supported_candidate", 0),
            "embedding_reranker": summarize_reranker(matches),
            "ai_call_record_count": ai_ledger_summary.get("record_count", 0),
            "ai_call_attempted_count": ai_ledger_summary.get("attempted_count", 0),
            "ai_call_route_counts": ai_ledger_summary.get("by_route", {}),
            **summarize_candidates(candidates),
        },
        "matches": [
            match.to_json(
                include_text=config.include_text_preview,
                text_preview_chars=config.text_preview_chars,
            )
            for match in matches
        ],
        "candidate_matches": [
            candidate.to_json(
                include_text=config.include_text_preview,
                text_preview_chars=config.text_preview_chars,
            )
            for candidate in candidates
        ],
        "adjudicated_matches_preview": [
            item.to_json(
                include_text=False,
                text_preview_chars=config.text_preview_chars,
            )
            for item in adjudicated
        ],
    }


def build_all_pairs_report(
    pages: list[PageRecord],
    matches: list[PageMatch],
    config: EngineConfig,
    capabilities: CapabilityReport | None = None,
) -> dict[str, Any]:
    candidates = to_candidate_matches(matches, config)
    adjudicated = noop_adjudicate_many(candidates, config)
    ai_ledger_summary = build_ai_call_ledger(pages, matches, capabilities.to_json() if capabilities else {}).get("summary", {})
    return {
        "engine_version": ENGINE_VERSION,
        "mode": "all_pairs",
        "schema_notes": build_schema_notes(),
        "capabilities": capabilities.to_json() if capabilities else {},
        "ai_call_summary": ai_ledger_summary,
        "summary": {
            "total_pages": len(pages),
            "match_count": len(matches),
            "match_counts_by_type": count_by_type(matches),
            "ocr_pages": sum(1 for page in pages if page.ocr_used),
            "tesseract_attempted_pages": sum(1 for page in pages if page.tesseract_attempted),
            "tesseract_usable_pages": sum(1 for page in pages if page.tesseract_usable),
            "openai_ocr_selected_pages": sum(1 for page in pages if page.openai_ocr_selected),
            "openai_ocr_attempted_pages": sum(1 for page in pages if page.openai_ocr_attempted),
            "openai_ocr_usable_pages": sum(1 for page in pages if page.openai_ocr_usable),
            "openai_ocr_improved_pages": sum(1 for page in pages if page.ocr_route == "openai_ocr_fallback"),
            "openai_ocr_selection_mode": config.openai_ocr_selection_mode,
            "openai_ocr_max_pages_per_job": config.openai_ocr_max_pages_per_job,
            "openai_ocr_max_pages_per_document": config.openai_ocr_max_pages_per_document,
            "openai_ocr_accept_cleaner_shorter_text": config.openai_ocr_accept_cleaner_shorter_text,
            "openai_ocr_skip_reason_counts": count_openai_ocr_skip_reasons(pages),
            "openai_ocr_selection_reason_counts": count_openai_ocr_selection_reasons(pages),
            "text_source_counts": count_text_sources(pages),
            "ocr_route_counts": count_ocr_routes(pages),
            "low_information_pages": count_low_information_pages(pages),
            "embedding_signal_count": count_signal(matches, "embedding_similarity"),
            "embedding_candidate_count": count_by_type(matches).get("embedding_similarity_candidate", 0),
            "hybrid_vector_candidate_count": count_by_type(matches).get("hybrid_vector_candidate", 0),
            "embedding_supported_candidate_count": count_by_type(matches).get("embedding_supported_candidate", 0),
            "embedding_reranker": summarize_reranker(matches),
            "ai_call_record_count": ai_ledger_summary.get("record_count", 0),
            "ai_call_attempted_count": ai_ledger_summary.get("attempted_count", 0),
            "ai_call_route_counts": ai_ledger_summary.get("by_route", {}),
            **summarize_candidates(candidates),
        },
        "matches": [
            match.to_json(
                include_text=config.include_text_preview,
                text_preview_chars=config.text_preview_chars,
            )
            for match in matches
        ],
        "candidate_matches": [
            candidate.to_json(
                include_text=config.include_text_preview,
                text_preview_chars=config.text_preview_chars,
            )
            for candidate in candidates
        ],
        "adjudicated_matches_preview": [
            item.to_json(
                include_text=False,
                text_preview_chars=config.text_preview_chars,
            )
            for item in adjudicated
        ],
    }


def build_schema_notes() -> dict[str, str]:
    return {
        "matches": "legacy-compatible detector candidate records",
        "candidate_matches": "v0.6 forward schema: aggregated detector outputs with deterministic pass history and escalation recommendations",
        "adjudicated_matches_preview": "placeholder final schema; real adjudication remains disabled until calibrated",
        "deterministic_passes": "strict/standard/loose bands are confidence levels, not independent votes",
        "low_information_filter": "Candidate hygiene suppresses/downranks low-information blank/cover/signature/separator pages before AI escalation; v0.8 treats low-information as visibility/category, not a duplicate label.",
        "embedding_similarity": "v0.9.8 embedding route can support deterministic candidates and add bounded vector-neighborhood recall candidates after OCR rescue",
        "tiered_ocr": "v0.9.8 OCR validation route: native text -> Tesseract TSV/confidence -> budgeted OpenAI OCR rescue with cleaner-shorter acceptance and selection/skip reasons",
        "ai_route_governance": "v0.8.1 separates OpenAI use into logical routes: vision_ocr_extraction, text_embedding, text_adjudication, and optional vision_pair_adjudication. Reports can emit an AI call ledger without PHI text.",
        "ocr_validation": "v0.8 adds OCR-specific route rows, OCR-dependent truth recall, selected OpenAI fallback rows, and OCR candidate diagnostics.",
        "phase_eval": "v0.9.8 adds phase-aware evaluation for strict pair scoring, OCR evidence readiness, vector retrieval recall, review queue burden, and unknown prediction buckets.",
        "review_buckets": "v0.8 keeps reviewer-facing labels aligned to duplicate, likely_duplicate, possible_duplicate, partial_overlap, and needs_review. not_duplicate is reserved for adjudicator/human decisions.",
        "candidate_visibility": "v0.8 separates label from visibility: main_review_list, low_information, and calibration_only.",
        "low_information_truth": "low_information_ignore remains a truth/evaluation category only.",
        "v1_output_contract": "Detector output now includes engine_candidate_label, adjudicator_suggested_label, human_final_label, visibility, visibility_reason, and candidate_category.",
        "calibration_artifacts": "v0.8 eval commands emit threshold sweeps, candidate summaries, false-positive review CSVs, false-negative review CSVs, and visibility counts.",
    }


def build_page_records_report(
    pages: list[PageRecord],
    config: EngineConfig,
    capabilities: CapabilityReport | None = None,
) -> dict[str, Any]:
    return {
        "engine_version": ENGINE_VERSION,
        "capabilities": capabilities.to_json() if capabilities else {},
        "page_count": len(pages),
        "pages": [
            page.to_json(
                include_text=config.include_text_preview,
                text_preview_chars=config.text_preview_chars,
            )
            for page in pages
        ],
    }


def count_by_type(matches: list[PageMatch]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in matches:
        counts[match.match_type] = counts.get(match.match_type, 0) + 1
    return counts


def count_openai_ocr_skip_reasons(pages: list[PageRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for page in pages:
        if page.openai_ocr_selected and not page.openai_ocr_attempted:
            key = page.openai_ocr_skip_reason or "selected_not_attempted"
            counts[key] = counts.get(key, 0) + 1
    return counts


def count_openai_ocr_selection_reasons(pages: list[PageRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for page in pages:
        if not page.openai_ocr_selected:
            continue
        reason = page.openai_ocr_selection_reason or "unknown"
        key = reason.split(";")[0].strip() or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


def count_text_sources(pages: list[PageRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for page in pages:
        key = page.text_source or "none"
        counts[key] = counts.get(key, 0) + 1
    return counts


def count_ocr_routes(pages: list[PageRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for page in pages:
        key = page.ocr_route or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts




def count_signal(matches: list[PageMatch], signal_name: str) -> int:
    return sum(1 for match in matches for signal in match.signals if signal.name == signal_name)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_matches_csv(path: Path, matches: list[PageMatch]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "match_type",
                "confidence",
                "a_document",
                "a_page",
                "b_document",
                "b_page",
                "signals",
                "candidate_stage",
                "review_bucket",
                "engine_candidate_label",
                "adjudicator_suggested_label",
                "human_final_label",
                "visibility",
                "visibility_reason",
                "candidate_category",
                "review_priority",
                "review_rationale",
                "embedding_escalation",
                "llm_detector_escalation",
                "recommendation",
            ],
        )
        writer.writeheader()
        for match in matches:
            writer.writerow(
                {
                    "match_type": match.match_type,
                    "confidence": round(match.confidence, 4),
                    "a_document": match.page_a.document_name,
                    "a_page": match.page_a.page_number,
                    "b_document": match.page_b.document_name,
                    "b_page": match.page_b.page_number,
                    "signals": "; ".join(f"{s.name}={s.score:.4f}" for s in match.signals),
                    "candidate_stage": match.candidate_stage,
                    "review_bucket": match.review_bucket,
                    "engine_candidate_label": match.engine_candidate_label,
                    "adjudicator_suggested_label": match.adjudicator_suggested_label or "",
                    "human_final_label": match.human_final_label or "",
                    "visibility": match.visibility,
                    "visibility_reason": match.visibility_reason,
                    "candidate_category": match.candidate_category,
                    "review_priority": match.review_priority,
                    "review_rationale": match.review_rationale,
                    "embedding_escalation": match.escalation.embedding_required,
                    "llm_detector_escalation": match.escalation.llm_detector_required,
                    "recommendation": match.recommendation,
                }
            )


def write_html_report(
    path: Path,
    matches: list[PageMatch],
    title: str = "Duplicate Engine Report",
    capabilities: dict[str, Any] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx, match in enumerate(matches, start=1):
        signal_text = ", ".join(
            html.escape(f"{s.name}: {s.score:.4f} {s.details if s.details else ''}") for s in match.signals
        )
        rows.append(
            f"""
            <section class="match">
              <h2>#{idx} {html.escape(match.match_type)} · {match.confidence:.3f}</h2>
              <p><strong>Recommendation:</strong> {html.escape(match.recommendation)}</p>
              <p><strong>Engine label:</strong> {html.escape(match.engine_candidate_label)} · priority {html.escape(match.review_priority)}</p>
              <p><strong>Visibility:</strong> {html.escape(match.visibility)} · {html.escape(match.visibility_reason)}</p>
              <p><strong>Adjudicator suggested label:</strong> {html.escape(match.adjudicator_suggested_label or 'not run')}</p>
              <p><strong>Human final label:</strong> {html.escape(match.human_final_label or 'not reviewed')}</p>
              <p><strong>Review rationale:</strong> {html.escape(match.review_rationale)}</p>
              <p><strong>Candidate stage:</strong> {html.escape(match.candidate_stage)}</p>
              <p><strong>Escalation:</strong> embedding={str(match.escalation.embedding_required).lower()}, llm_detector={str(match.escalation.llm_detector_required).lower()}, adjudicator={str(match.escalation.adjudicator_required).lower()}</p>
              <p><strong>Escalation reason:</strong> {html.escape(match.escalation.reason)}</p>
              <p><strong>Candidate sources:</strong> {html.escape(', '.join(match.candidate_sources))}</p>
              <p><strong>Signals:</strong> {signal_text}</p>
              <div class="pages">
                <figure>
                  <img src="{html.escape(match.page_a.image_path)}" alt="Page A" />
                  <figcaption>{html.escape(match.page_a.document_name)} · page {match.page_a.page_number}</figcaption>
                </figure>
                <figure>
                  <img src="{html.escape(match.page_b.image_path)}" alt="Page B" />
                  <figcaption>{html.escape(match.page_b.document_name)} · page {match.page_b.page_number}</figcaption>
                </figure>
              </div>
            </section>
            """
        )

    capability_banner = render_capability_banner(capabilities or {})
    pipeline_banner = render_pipeline_banner()

    document = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 32px; background: #fafafa; color: #111; }}
    h1 {{ margin-bottom: 8px; }}
    .banner {{ background: white; border: 1px solid #ddd; border-radius: 12px; padding: 16px; margin: 16px 0; }}
    .banner h2 {{ margin-top: 0; }}
    .cap-list {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 8px; padding: 0; list-style: none; }}
    .cap-list li {{ border: 1px solid #e5e5e5; border-radius: 8px; padding: 8px; background: #fcfcfc; }}
    .cap-status {{ font-weight: 700; }}
    .match {{ background: white; border: 1px solid #ddd; border-radius: 12px; padding: 16px; margin: 16px 0; }}
    .pages {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    figure {{ margin: 0; }}
    img {{ max-width: 100%; border: 1px solid #ccc; border-radius: 8px; background: white; }}
    figcaption {{ font-size: 13px; margin-top: 6px; color: #444; }}
    code {{ background: #f2f2f2; padding: 1px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p>Total matches: {len(matches)}</p>
  {pipeline_banner}
  {capability_banner}
  {''.join(rows)}
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def render_pipeline_banner() -> str:
    return """
    <section class="banner">
      <h2>Pipeline model</h2>
      <p><strong>v0.8 uses deterministic multi-pass candidate generation, candidate hygiene, v1-aligned candidate labels, visibility routing, calibration artifacts, and optional embedding escalation before any LLM adjudication.</strong> Strict, standard, and loose threshold bands preserve evidence strength so the engine can lower thresholds for recall without treating correlated passes as separate votes. Low-information candidates are routed away from the main review list by visibility, not by fake duplicate labels.</p>
    </section>
    """


def render_capability_banner(capabilities: dict[str, Any]) -> str:
    if not capabilities:
        return ""
    items = []
    for name, status in capabilities.items():
        enabled = status.get("enabled")
        available = status.get("available")
        used = status.get("used")
        reason = status.get("reason")
        provider = status.get("provider")
        role = status.get("role", "")
        state = "available" if available else "disabled" if not enabled else status.get("status", "unavailable")
        marker = "OK" if available else "--" if not enabled else "WARN"
        reason_html = f"<br><small>{html.escape(str(reason))}</small>" if reason else ""
        provider_html = f"<br><small>provider: <code>{html.escape(str(provider))}</code></small>" if provider else ""
        role_html = f"<br><small>role: <code>{html.escape(str(role))}</code></small>" if role else ""
        used_html = "yes" if used else "no"
        items.append(
            f"<li><span class=\"cap-status\">{html.escape(marker)}</span> "
            f"{html.escape(name)} — {html.escape(str(state))}; used: {html.escape(used_html)}"
            f"{provider_html}{role_html}{reason_html}</li>"
        )
    return f"""
    <section class="banner">
      <h2>Capability visibility</h2>
      <p>This report shows which matching, enrichment, detection, and adjudication layers were available, disabled, unavailable, or skipped for this run.</p>
      <ul class="cap-list">{''.join(items)}</ul>
    </section>
    """
