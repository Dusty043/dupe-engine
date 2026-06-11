from __future__ import annotations

import json
from pathlib import Path

from dupe_engine.capabilities import build_capability_report
from dupe_engine.config import EngineConfig
from dupe_engine.models import MatchSignal, PageMatch, PageRecord
from dupe_engine.ui_artifacts import write_ui_run_artifacts


def make_page(tmp_path: Path, document: str, page: int) -> PageRecord:
    image = tmp_path / f"{document.replace('/', '_')}_{page}.png"
    image.write_bytes(b"fake image payload")
    return PageRecord(
        group="ALL",
        document_id=f"doc{page}",
        document_name=document,
        page_number=page,
        image_path=str(image),
        native_text="hello world",
        raw_text="hello world",
        best_text="hello world",
        text_source="native",
        native_word_count=2,
        best_word_count=2,
    )


def test_write_ui_run_artifacts_creates_contract_files(tmp_path: Path) -> None:
    config = EngineConfig()
    page_a = make_page(tmp_path, "source_A/intake.pdf", 1)
    page_b = make_page(tmp_path, "source_B/intake.pdf", 1)
    match = PageMatch(
        match_type="weighted_text_candidate",
        confidence=0.91,
        page_a=page_a,
        page_b=page_b,
        signals=[MatchSignal(name="tfidf", score=0.91)],
        engine_candidate_label="likely_duplicate",
        visibility="main_review_list",
    )
    report = {"engine_version": "0.8.1", "mode": "all_pairs", "summary": {"total_pages": 2, "match_count": 1}}
    run_dir = tmp_path / "run"

    write_ui_run_artifacts(
        run_dir,
        command_name="eval-all",
        report=report,
        pages=[page_a, page_b],
        matches=[match],
        config=config,
        capabilities=build_capability_report(config, used_core_layers=True),
    )

    for name in [
        "run_manifest.json",
        "pages.json",
        "candidates.json",
        "candidate_pairs.json",
        "capabilities.json",
        "metrics.json",
        "review_decisions.json",
    ]:
        assert (run_dir / name).exists()

    candidates = json.loads((run_dir / "candidates.json").read_text())
    assert candidates["candidate_count"] == 1
    first = candidates["candidates"][0]
    assert first["candidate_id"].startswith("cand_")
    assert first["left"]["document"] == "source_A/intake.pdf"
    assert first["left"]["asset_image_path"].startswith("assets/page_images/")

    decisions = json.loads((run_dir / "review_decisions.json").read_text())
    assert decisions == {"schema_version": "dupe_engine_review_decisions_v0_8_6", "decisions": []}
