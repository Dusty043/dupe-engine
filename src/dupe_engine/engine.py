from __future__ import annotations

from pathlib import Path

from .config import EngineConfig
from .ingest import ingest_pdf_dir_as_corpus, ingest_pdf_group
from .embedding_detector import apply_embedding_detector
from .matchers import compare_all_pages, compare_groups
from .ocr import apply_openai_ocr_fallback, apply_openai_ocr_post_candidate_rescue
from .page_quality import annotate_page_quality
from .models import PageMatch, PageRecord
from .review import apply_main_review_visibility_budget
from .progress import emit_progress


def run_ab_compare(
    group_a_dir: Path,
    group_b_dir: Path,
    work_dir: Path,
    config: EngineConfig,
) -> tuple[list[PageRecord], list[PageRecord], list[PageMatch]]:
    image_dir = work_dir / "pages"
    image_dir.mkdir(parents=True, exist_ok=True)
    emit_progress(stage="ingesting_group_a", message="Reading Received/Group A PDFs")
    pages_a = ingest_pdf_group("A", group_a_dir, image_dir, config)
    emit_progress(stage="ingesting_group_b", message="Reading ERE/Group B PDFs")
    pages_b = ingest_pdf_group("B", group_b_dir, image_dir, config)
    emit_progress(stage="generating_candidates", message="Generating initial deterministic candidates", details={"page_count": len(pages_a) + len(pages_b)})
    matches = compare_groups(pages_a, pages_b, config)
    emit_progress(stage="candidates_generated", message=f"Generated {len(matches)} initial candidates", details={"candidate_count": len(matches)})
    changed = apply_openai_ocr_fallback(matches, config, pages=pages_a + pages_b)
    if changed:
        emit_progress(stage="rerunning_after_fallback", message=f"OpenAI OCR improved {changed} page(s); rerunning candidates", details={"changed_pages": changed})
        for page in pages_a + pages_b:
            annotate_page_quality(page, config)
        matches = compare_groups(pages_a, pages_b, config)
        emit_progress(stage="candidates_regenerated", message=f"Generated {len(matches)} candidates after fallback", details={"candidate_count": len(matches)})
    emit_progress(stage="v2_layers", message="Embedding recall is optional/budgeted; LLM layers remain non-blocking v2 extensions", details={"embeddings_enabled": config.enable_embeddings, "llm_detector_enabled": config.enable_llm_candidate_detector, "adjudicator_enabled": config.enable_adjudicator})
    matches = apply_embedding_detector(matches, config, pages_a=pages_a, pages_b=pages_b, all_pairs=False)
    rescue_changed = apply_openai_ocr_post_candidate_rescue(matches, config, pages=pages_a + pages_b)
    if rescue_changed:
        emit_progress(stage="rerunning_after_post_candidate_rescue", message=f"Post-candidate OCR rescue improved {rescue_changed} page(s); rerunning candidates", details={"changed_pages": rescue_changed})
        for page in pages_a + pages_b:
            annotate_page_quality(page, config)
        matches = compare_groups(pages_a, pages_b, config)
        matches = apply_embedding_detector(matches, config, pages_a=pages_a, pages_b=pages_b, all_pairs=False)
        emit_progress(stage="candidates_regenerated_after_post_candidate_rescue", message=f"Generated {len(matches)} candidates after post-candidate rescue", details={"candidate_count": len(matches)})
    apply_main_review_visibility_budget(
        matches,
        total_pages=len(pages_a) + len(pages_b),
        max_candidates_per_100_pages=config.main_review_max_candidates_per_100_pages,
    )
    return pages_a, pages_b, matches


def run_all_pairs_compare(
    pdf_dir: Path,
    work_dir: Path,
    config: EngineConfig,
) -> tuple[list[PageRecord], list[PageMatch]]:
    image_dir = work_dir / "pages"
    image_dir.mkdir(parents=True, exist_ok=True)
    emit_progress(stage="ingesting_corpus", message="Reading corpus PDFs")
    pages = ingest_pdf_dir_as_corpus(pdf_dir, image_dir, config)
    emit_progress(stage="generating_candidates", message="Generating initial deterministic candidates", details={"page_count": len(pages)})
    matches = compare_all_pages(pages, config)
    emit_progress(stage="candidates_generated", message=f"Generated {len(matches)} initial candidates", details={"candidate_count": len(matches)})
    changed = apply_openai_ocr_fallback(matches, config, pages=pages)
    if changed:
        emit_progress(stage="rerunning_after_fallback", message=f"OpenAI OCR improved {changed} page(s); rerunning candidates", details={"changed_pages": changed})
        for page in pages:
            annotate_page_quality(page, config)
        matches = compare_all_pages(pages, config)
        emit_progress(stage="candidates_regenerated", message=f"Generated {len(matches)} candidates after fallback", details={"candidate_count": len(matches)})
    emit_progress(stage="v2_layers", message="Embedding recall is optional/budgeted; LLM layers remain non-blocking v2 extensions", details={"embeddings_enabled": config.enable_embeddings, "llm_detector_enabled": config.enable_llm_candidate_detector, "adjudicator_enabled": config.enable_adjudicator})
    matches = apply_embedding_detector(matches, config, pages_a=pages, pages_b=pages, all_pairs=True)
    rescue_changed = apply_openai_ocr_post_candidate_rescue(matches, config, pages=pages)
    if rescue_changed:
        emit_progress(stage="rerunning_after_post_candidate_rescue", message=f"Post-candidate OCR rescue improved {rescue_changed} page(s); rerunning candidates", details={"changed_pages": rescue_changed})
        for page in pages:
            annotate_page_quality(page, config)
        matches = compare_all_pages(pages, config)
        matches = apply_embedding_detector(matches, config, pages_a=pages, pages_b=pages, all_pairs=True)
        emit_progress(stage="candidates_regenerated_after_post_candidate_rescue", message=f"Generated {len(matches)} candidates after post-candidate rescue", details={"candidate_count": len(matches)})
    apply_main_review_visibility_budget(
        matches,
        total_pages=len(pages),
        max_candidates_per_100_pages=config.main_review_max_candidates_per_100_pages,
    )
    return pages, matches
