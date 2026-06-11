from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .config import EngineConfig
from .models import PageRecord
from .ocr import page_has_weak_text_or_ocr, page_openai_ocr_selection_score, page_vision_fallback_expected

SCHEMA_VERSION = "dupe_engine_openai_ocr_fallback_audit_v0_10_1"


def build_fallback_audit(pages: list[PageRecord], config: EngineConfig) -> dict[str, Any]:
    rows = build_fallback_rows(pages, config)
    selected = [row for row in rows if row["openai_ocr_selected"]]
    attempted = [row for row in rows if row["openai_ocr_attempted"]]
    usable = [row for row in rows if row["openai_ocr_usable"]]
    improved = [row for row in rows if row["openai_ocr_improved"]]
    sidecar = [row for row in rows if row.get("openai_ocr_sidecar_available")]
    eligible_not_selected = [row for row in rows if row["eligible_for_fallback"] and not row["openai_ocr_selected"]]
    skipped_due_budget_estimate = max(0, len(eligible_not_selected)) if len(selected) >= config.openai_ocr_max_pages_per_job else 0
    return {
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "page_count": len(pages),
            "selection_mode": config.openai_ocr_selection_mode,
            "max_pages_per_job": config.openai_ocr_max_pages_per_job,
            "max_pages_per_document": config.openai_ocr_max_pages_per_document,
            "post_candidate_rescue_enabled": config.openai_ocr_post_candidate_rescue_enabled,
            "post_candidate_rescue_max_pages": config.openai_ocr_post_candidate_max_pages,
            "post_candidate_rescue_min_confidence": config.openai_ocr_post_candidate_min_confidence,
            "allow_low_information_pages": config.openai_ocr_allow_low_information_pages,
            "low_information_penalty": config.openai_ocr_low_information_penalty,
            "accept_cleaner_shorter_text": config.openai_ocr_accept_cleaner_shorter_text,
            "require_tesseract_first": config.openai_ocr_require_tesseract_first,
            "eligible_pages": sum(1 for row in rows if row["eligible_for_fallback"]),
            "selected_pages": len(selected),
            "attempted_pages": len(attempted),
            "usable_pages": len(usable),
            "improved_pages": len(improved),
            "sidecar_evidence_pages": len(sidecar),
            "source_safe_ocr_merge_enabled": config.source_safe_ocr_merge_enabled,
            "eligible_not_selected_pages": len(eligible_not_selected),
            "skipped_due_budget_estimate": skipped_due_budget_estimate,
            "selection_reason_counts": dict(sorted(Counter(row["selection_reason_group"] for row in selected).items())),
            "skip_reason_counts": dict(sorted(Counter(row["openai_ocr_skip_reason"] or "selected_not_attempted" for row in selected if not row["openai_ocr_attempted"]).items())),
            "error_count": sum(1 for row in rows if bool(row["openai_ocr_error"])),
        },
        "rows": rows,
    }


def build_fallback_rows(pages: list[PageRecord], config: EngineConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in pages:
        vision_expected = page_vision_fallback_expected(page, config)
        weak_text = page_has_weak_text_or_ocr(page, config)
        eligible = fallback_eligible_for_policy(page, config, vision_expected=vision_expected, weak_text=weak_text)
        sidecar_available = bool(page.openai_ocr_usable and (page.openai_ocr_text or "").strip())
        improved = page.best_text_source == "openai_ocr" or (config.source_safe_ocr_merge_enabled and sidecar_available)
        reason = page.openai_ocr_selection_reason or page.ocr_escalation_reason or ""
        rows.append(
            {
                "document": page.document_name,
                "page": page.page_number,
                "page_id": page.page_id,
                "eligible_for_fallback": eligible,
                "selection_score": round(page_openai_ocr_selection_score(page, config), 6),
                "weak_text_or_ocr": weak_text,
                "vision_fallback_expected": vision_expected,
                "native_text_status": page.native_text_status,
                "native_word_count": page.native_word_count,
                "best_text_source": page.best_text_source,
                "best_word_count": page.best_word_count,
                "ocr_route": page.ocr_route,
                "tesseract_attempted": page.tesseract_attempted,
                "tesseract_usable": page.tesseract_usable,
                "tesseract_confidence": page.tesseract_confidence if page.tesseract_confidence is not None else "",
                "tesseract_word_count": page.tesseract_word_count,
                "is_low_information": page.is_low_information,
                "low_information_reason": page.low_information_reason or "",
                "openai_ocr_selected": bool(page.openai_ocr_selected),
                "openai_ocr_attempted": page.openai_ocr_attempted,
                "openai_ocr_usable": page.openai_ocr_usable,
                "openai_ocr_improved": improved,
                "openai_ocr_sidecar_available": sidecar_available,
                "source_safe_ocr_merge": bool(page.meta.get("source_safe_ocr_merge", {}).get("enabled", False)),
                "openai_ocr_word_count": page.openai_ocr_word_count,
                "openai_ocr_provider": page.openai_ocr_provider or "",
                "openai_ocr_model": page.openai_ocr_model or "",
                "openai_ocr_selection_reason": reason,
                "selection_reason_group": reason.split(";")[0].strip() if reason else "not_selected",
                "openai_ocr_skip_reason": page.openai_ocr_skip_reason or "",
                "openai_ocr_error": page.openai_ocr_error or "",
                "openai_ocr_quality_json": json.dumps(page.meta.get("openai_ocr_quality", {}), sort_keys=True),
            }
        )
    rows.sort(key=lambda row: (not bool(row["openai_ocr_selected"]), -float(row["selection_score"]), str(row["document"]), int(row["page"])))
    return rows


def fallback_eligible_for_policy(page: PageRecord, config: EngineConfig, *, vision_expected: bool, weak_text: bool) -> bool:
    if page.openai_ocr_attempted or page.openai_ocr_usable:
        return bool(page.openai_ocr_selected)
    if page.native_text_status == "usable":
        return False
    if page.is_low_information and not config.openai_ocr_allow_low_information_pages:
        return False
    if config.openai_ocr_require_tesseract_first and not page.tesseract_attempted and page.ocr_route != "tesseract_unavailable":
        return False
    if page.tesseract_usable:
        return False
    mode = (config.openai_ocr_selection_mode or "weak_pages_or_vision_expected").strip().lower()
    if mode == "vision_expected":
        return vision_expected
    if mode == "weak_pages":
        return weak_text
    if mode == "weak_pages_or_vision_expected":
        return weak_text or vision_expected
    if mode == "reason_balanced":
        # Reason-balanced is a budget allocation policy over the same eligible
        # OCR-rescue universe, with no-text pages included explicitly.
        return weak_text or vision_expected or int(page.best_word_count or 0) == 0
    return False


def write_fallback_audit_json(path: Path, audit: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(audit, indent=2), encoding="utf-8")


def write_fallback_audit_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["document", "page", "page_id"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
