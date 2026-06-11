from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .capabilities import CapabilityReport
from .config import EngineConfig
from .evaluation import match_key_from_pages, truth_to_json
from .models import PageMatch, PageRecord, TruthPair
from .reporting import ENGINE_VERSION

ARTIFACT_SCHEMA_VERSION = "dupe_engine_ui_run_v0_9_7"


def write_ui_run_artifacts(
    run_dir: Path,
    *,
    command_name: str,
    report: dict[str, Any],
    pages: list[PageRecord],
    matches: list[PageMatch],
    config: EngineConfig,
    capabilities: CapabilityReport,
    truth_context: Any | None = None,
    eval_report: dict[str, Any] | None = None,
    calibration_report: dict[str, Any] | None = None,
    ocr_report: dict[str, Any] | None = None,
    source_args: dict[str, Any] | None = None,
) -> None:
    """Emit a stable run folder that a thin review UI can consume.

    This intentionally duplicates some information from the existing report JSONs.
    The goal is to give the UI a stable contract while the core detector internals
    keep evolving.
    """

    run_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = run_dir / "assets" / "page_images"
    assets_dir.mkdir(parents=True, exist_ok=True)

    page_assets = copy_page_images(pages, assets_dir)
    truth_pairs = list(getattr(truth_context, "pairs", None) or [])
    truth_index = {pair.unordered_key: pair for pair in truth_pairs}

    pages_payload = build_pages_payload(pages, page_assets)
    candidates_payload = build_candidates_payload(matches, page_assets, truth_index)
    candidate_pairs_payload = {
        "schema_version": "dupe_engine_candidate_pairs_v0_8_6",
        "candidate_count": candidates_payload["candidate_count"],
        "pairs": candidates_payload["candidates"],
    }
    metrics_payload = build_metrics_payload(report, eval_report, calibration_report, ocr_report)
    manifest_payload = build_run_manifest(
        command_name=command_name,
        report=report,
        pages=pages,
        matches=matches,
        config=config,
        capabilities=capabilities,
        truth_context=truth_context,
        source_args=source_args or {},
    )

    write_json(run_dir / "run_manifest.json", manifest_payload)
    write_json(run_dir / "pages.json", pages_payload)
    write_json(run_dir / "candidates.json", candidates_payload)
    write_json(run_dir / "candidate_pairs.json", candidate_pairs_payload)
    write_json(run_dir / "capabilities.json", capabilities.to_json())
    write_json(run_dir / "metrics.json", metrics_payload)
    if eval_report is not None:
        write_json(run_dir / "truth_eval.json", eval_report)
        if isinstance(eval_report.get("phase_eval"), dict):
            write_json(run_dir / "phase_eval.json", eval_report["phase_eval"])
    ensure_review_decisions_file(run_dir / "review_decisions.json")


def copy_page_images(pages: list[PageRecord], assets_dir: Path) -> dict[str, str]:
    paths: dict[str, str] = {}
    used_names: set[str] = set()
    for page in pages:
        src = Path(page.image_path)
        suffix = src.suffix or ".png"
        base = safe_asset_stem(page.document_name)
        candidate_name = f"{base}__p{page.page_number:04d}{suffix}"
        if candidate_name in used_names:
            digest = hashlib.sha1(page.page_id.encode("utf-8")).hexdigest()[:8]
            candidate_name = f"{base}__p{page.page_number:04d}__{digest}{suffix}"
        used_names.add(candidate_name)
        dst = assets_dir / candidate_name
        if src.exists():
            shutil.copy2(src, dst)
            paths[page.page_id] = str(Path("assets") / "page_images" / candidate_name)
        else:
            paths[page.page_id] = page.image_path
    return paths


def build_pages_payload(pages: list[PageRecord], page_assets: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_version": "dupe_engine_pages_v0_8_6",
        "page_count": len(pages),
        "pages": [build_ui_page(page, page_assets) for page in pages],
    }


def build_candidates_payload(
    matches: list[PageMatch],
    page_assets: dict[str, str],
    truth_index: dict[tuple[tuple[str, int], tuple[str, int]], TruthPair],
) -> dict[str, Any]:
    candidates = []
    for rank, match in enumerate(sorted(matches, key=lambda item: item.confidence, reverse=True), start=1):
        key = match_key_from_pages(match.page_a.document_name, match.page_a.page_number, match.page_b.document_name, match.page_b.page_number)
        truth = truth_index.get(key)
        candidates.append(build_ui_candidate(match, rank, page_assets, truth))
    return {
        "schema_version": "dupe_engine_candidates_v0_8_6",
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def build_ui_page(page: PageRecord, page_assets: dict[str, str]) -> dict[str, Any]:
    payload = page.to_json(include_text=False)
    payload["asset_image_path"] = page_assets.get(page.page_id, page.image_path)
    payload["source_pdf_name"] = page.meta.get("source_pdf_name")
    payload["relative_pdf_path"] = page.meta.get("relative_pdf_path", page.document_name)
    return payload


def build_ui_candidate(
    match: PageMatch,
    rank: int,
    page_assets: dict[str, str],
    truth: TruthPair | None,
) -> dict[str, Any]:
    signals = [signal.to_json() for signal in match.signals]
    signal_scores = {signal["name"]: signal["score"] for signal in signals if "name" in signal and "score" in signal}
    return {
        "candidate_id": stable_candidate_id(match),
        "rank": rank,
        "queue": match.visibility,
        "match_type": match.match_type,
        "confidence": round(match.confidence, 4),
        "engine_label": match.engine_candidate_label,
        "adjudicator_suggested_label": match.adjudicator_suggested_label,
        "human_final_label": match.human_final_label,
        "review_bucket": match.review_bucket,
        "review_priority": match.review_priority,
        "review_rationale": match.review_rationale,
        "candidate_stage": match.candidate_stage,
        "candidate_category": match.candidate_category,
        "visibility": match.visibility,
        "visibility_reason": match.visibility_reason,
        "left": build_candidate_side(match.page_a, page_assets),
        "right": build_candidate_side(match.page_b, page_assets),
        "signals": signals,
        "signal_scores": signal_scores,
        "deterministic_passes": [record.to_json() for record in match.deterministic_passes],
        "escalation": match.escalation.to_json(),
        "ai_route_events": match.ai_route_events,
        "truth": truth_to_json(truth) if truth else None,
        "expected_min_layer": truth.expected_min_layer if truth else None,
        "required_layers": truth.required_layers if truth else [],
        "difficulty": truth.difficulty if truth else None,
        "reason_tags": truth.reason_tags if truth else [],
        "review_decision": None,
    }


def build_candidate_side(page: PageRecord, page_assets: dict[str, str]) -> dict[str, Any]:
    return {
        "page_id": page.page_id,
        "document": page.document_name,
        "page": page.page_number,
        "asset_image_path": page_assets.get(page.page_id, page.image_path),
        "native_text_status": page.native_text_status,
        "ocr_route": page.ocr_route,
        "best_text_source": page.best_text_source,
        "native_word_count": page.native_word_count,
        "best_word_count": page.best_word_count,
        "tesseract_attempted": page.tesseract_attempted,
        "tesseract_usable": page.tesseract_usable,
        "openai_ocr_selected": page.openai_ocr_selected,
        "openai_ocr_attempted": page.openai_ocr_attempted,
        "openai_ocr_usable": page.openai_ocr_usable,
        "is_low_information": page.is_low_information,
        "low_information_reason": page.low_information_reason,
    }


def stable_candidate_id(match: PageMatch) -> str:
    left = f"{match.page_a.document_name}#{match.page_a.page_number}"
    right = f"{match.page_b.document_name}#{match.page_b.page_number}"
    digest = hashlib.sha1("||".join(sorted([left, right])).encode("utf-8")).hexdigest()[:16]
    return f"cand_{digest}"


def build_metrics_payload(
    report: dict[str, Any],
    eval_report: dict[str, Any] | None,
    calibration_report: dict[str, Any] | None,
    ocr_report: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": "dupe_engine_metrics_v0_9_7",
        "summary": report.get("summary", {}),
        "eval_summary": (eval_report or {}).get("summary"),
        "calibration_summary": (calibration_report or {}).get("summary"),
        "ocr_summary": (ocr_report or {}).get("summary"),
        "phase_eval_summary": ((eval_report or {}).get("phase_eval") or {}).get("strict_pair_eval"),
        "vector_eval_summary": (((eval_report or {}).get("phase_eval") or {}).get("vector_retrieval_eval") or {}).get("summary"),
        "review_queue_eval_summary": (((eval_report or {}).get("phase_eval") or {}).get("review_queue_eval") or {}).get("summary"),
        "ai_call_summary": report.get("ai_call_summary", {}),
    }


def build_run_manifest(
    *,
    command_name: str,
    report: dict[str, Any],
    pages: list[PageRecord],
    matches: list[PageMatch],
    config: EngineConfig,
    capabilities: CapabilityReport,
    truth_context: Any | None,
    source_args: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_contract_version": "0.9.8",
        "engine_version": report.get("engine_version", ENGINE_VERSION),
        "mode": report.get("mode"),
        "command": command_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "page_count": len(pages),
        "candidate_count": len(matches),
        "summary": report.get("summary", {}),
        "truth_status": truth_context.to_json() if truth_context else {"available": False, "status": "not_provided"},
        "capabilities_summary": summarize_capabilities(capabilities),
        "inputs": json_safe(source_args),
        "config": json_safe(asdict(config)),
        "artifacts": {
            "run_manifest": "run_manifest.json",
            "pages": "pages.json",
            "candidates": "candidates.json",
            "candidate_pairs": "candidate_pairs.json",
            "capabilities": "capabilities.json",
            "metrics": "metrics.json",
            "truth_eval": "truth_eval.json",
            "phase_eval": "phase_eval.json",
            "review_decisions": "review_decisions.json",
            "fallback_audit": "fallback_audit.json",
            "fallback_pages": "fallback_pages.csv",
            "progress": "progress.json",
            "progress_events": "progress_events.jsonl",
            "page_images": "assets/page_images/",
        },
    }


def summarize_capabilities(capabilities: CapabilityReport) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name, status in capabilities.layers.items():
        summary[name] = {
            "enabled": status.enabled,
            "available": status.available,
            "used": status.used,
            "provider": status.provider,
            "status": status.status,
            "reason": status.reason,
            "model": status.model,
        }
    return summary


def ensure_review_decisions_file(path: Path) -> None:
    if path.exists():
        return
    write_json(
        path,
        {
            "schema_version": "dupe_engine_review_decisions_v0_8_6",
            "decisions": [],
        },
    )


def safe_asset_stem(value: str) -> str:
    keep = []
    for char in value.replace("/", "__").replace("\\", "__"):
        if char.isalnum() or char in {"-", "_", "."}:
            keep.append(char)
        else:
            keep.append("_")
    stem = "".join(keep).strip("._") or "page"
    return stem[:120]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(payload), indent=2), encoding="utf-8")


def json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
