from __future__ import annotations

from pathlib import Path

import fitz

from dupe_engine.config import EngineConfig
from dupe_engine.ingest import ingest_pdf_dir_as_corpus


def make_pdf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def test_ingest_preserves_relative_pdf_path_identity(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    make_pdf(pdf_dir / "source_A" / "intake_batch_001.pdf", "A document")
    make_pdf(pdf_dir / "source_B" / "intake_batch_001.pdf", "B document")

    pages = ingest_pdf_dir_as_corpus(pdf_dir, tmp_path / "work", EngineConfig(dpi=72))

    names = sorted(page.document_name for page in pages)
    assert names == [
        "source_A/intake_batch_001.pdf",
        "source_B/intake_batch_001.pdf",
    ]
    assert sorted(page.meta["source_pdf_name"] for page in pages) == [
        "intake_batch_001.pdf",
        "intake_batch_001.pdf",
    ]
