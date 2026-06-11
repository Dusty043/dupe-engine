from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from .config import EngineConfig
from .hashing import perceptual_dhash, sha256_file
from .models import PageRecord
from .ocr import apply_initial_ocr_route, word_count
from .page_quality import annotate_page_quality
from .progress import emit_progress


def ingest_pdf_group(group_name: str, input_dir: Path, image_dir: Path, config: EngineConfig) -> list[PageRecord]:
    image_dir.mkdir(parents=True, exist_ok=True)
    pdf_paths = sorted(input_dir.rglob("*.pdf") if config.recursive_pdf_input else input_dir.glob("*.pdf"))
    total_pages = count_pdf_pages(pdf_paths)
    emit_progress(
        stage="reading_pdfs",
        message=f"Found {len(pdf_paths)} PDF(s) in group {group_name}",
        current=0,
        total=total_pages,
        details={"group": group_name, "pdf_count": len(pdf_paths), "input_dir": input_dir},
    )
    pages: list[PageRecord] = []
    for pdf_idx, pdf_path in enumerate(pdf_paths, start=1):
        emit_progress(
            stage="rendering_pages",
            message=f"Reading {pdf_path.name}",
            current=len(pages),
            total=total_pages,
            details={"group": group_name, "pdf_index": pdf_idx, "pdf_count": len(pdf_paths), "document": pdf_path.name},
        )
        pages.extend(
            ingest_pdf(
                group_name,
                pdf_path,
                image_dir,
                config,
                source_root=input_dir,
                progress_start_index=len(pages),
                progress_total_pages=total_pages,
            )
        )
    emit_progress(
        stage="ingest_complete",
        message=f"Finished group {group_name}",
        current=len(pages),
        total=total_pages,
        details={"group": group_name, "page_count": len(pages)},
    )
    return pages


def ingest_pdf_dir_as_corpus(input_dir: Path, image_dir: Path, config: EngineConfig) -> list[PageRecord]:
    return ingest_pdf_group("ALL", input_dir, image_dir, config)


def ingest_pdf(
    group_name: str,
    pdf_path: Path,
    image_dir: Path,
    config: EngineConfig,
    source_root: Path | None = None,
    *,
    progress_start_index: int = 0,
    progress_total_pages: int | None = None,
) -> list[PageRecord]:
    file_hash = sha256_file(pdf_path)
    document_id = file_hash[:12]
    records: list[PageRecord] = []

    try:
        relative_pdf_path = str(pdf_path.relative_to(source_root)) if source_root else pdf_path.name
    except ValueError:
        relative_pdf_path = pdf_path.name

    doc = fitz.open(pdf_path)
    try:
        for idx in range(len(doc)):
            page_number = idx + 1
            page = doc[idx]

            native_text = page.get_text("text") or ""

            image_name = f"{group_name}_{document_id}_{safe_stem(pdf_path.stem)}_page_{page_number:04d}.png"
            image_path = image_dir / image_name
            pix = page.get_pixmap(dpi=config.dpi)
            pix.save(image_path)

            record = PageRecord(
                group=group_name,
                document_id=document_id,
                document_name=relative_pdf_path,
                page_number=page_number,
                image_path=str(image_path),
                raw_text=native_text,
                native_text=native_text,
                best_text=native_text,
                text_source="native" if native_text.strip() else "none",
                native_word_count=word_count(native_text, config),
                exact_image_hash=sha256_file(image_path),
                perceptual_hash=perceptual_dhash(image_path),
                meta={"source_pdf_sha256": file_hash, "relative_pdf_path": relative_pdf_path, "source_pdf_name": pdf_path.name},
            )
            apply_initial_ocr_route(record, image_path, config)
            records.append(record)
            annotate_page_quality(records[-1], config)
            emit_progress(
                stage="ocr_routing",
                message=f"Processed {relative_pdf_path} page {page_number}",
                current=progress_start_index + len(records),
                total=progress_total_pages,
                details={
                    "group": group_name,
                    "document": relative_pdf_path,
                    "page": page_number,
                    "ocr_route": record.ocr_route,
                    "best_text_source": record.best_text_source,
                    "best_word_count": record.best_word_count,
                },
            )
    finally:
        doc.close()

    return records


def safe_stem(stem: str) -> str:
    keep = []
    for char in stem:
        if char.isalnum() or char in {"-", "_"}:
            keep.append(char)
        else:
            keep.append("_")
    return "".join(keep)[:80]


def count_pdf_pages(pdf_paths: list[Path]) -> int:
    total = 0
    for pdf_path in pdf_paths:
        try:
            doc = fitz.open(pdf_path)
            try:
                total += len(doc)
            finally:
                doc.close()
        except Exception:
            continue
    return total
