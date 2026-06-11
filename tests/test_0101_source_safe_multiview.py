from __future__ import annotations

from dupe_engine.config import EngineConfig
from dupe_engine.matchers import multipass_text_matches, rare_token_block_matches, sequence_neighbor_matches
from dupe_engine.models import MatchSignal, PageMatch, PageRecord, TruthPageRef, TruthPair
from dupe_engine.ocr import apply_openai_ocr_evidence_text, update_best_text
from dupe_engine.ocr_metrics import build_ocr_validation_report


def make_page(group: str, document: str, page_number: int, text: str = "") -> PageRecord:
    return PageRecord(
        group=group,
        document_id=document.replace(".", "_"),
        document_name=document,
        page_number=page_number,
        image_path=f"/tmp/{group}_{document}_{page_number}.png",
        native_text=text,
        raw_text=text,
        best_text=text,
        comparison_text=text,
        best_text_source="native" if text else "none",
        native_text_status="usable" if text else "missing",
        best_word_count=len(text.split()),
        native_word_count=len(text.split()),
    )


def test_source_safe_openai_ocr_sidecar_preserves_primary_text() -> None:
    config = EngineConfig(source_safe_ocr_merge_enabled=True, native_min_usable_words=3)
    page = make_page("A", "native.pdf", 1, "native clinical assessment plan medication followup")
    update_best_text(page, page.native_text, "native", config)
    original_text = page.raw_text
    original_source = page.best_text_source

    sidecar_text = "Case Number: AB-123456 DOB: 01/02/1970 provider treatment determination"
    page.openai_ocr_text = sidecar_text
    page.openai_ocr_word_count = 8
    page.openai_ocr_usable = True
    apply_openai_ocr_evidence_text(page, sidecar_text, 0.9, config)

    assert page.raw_text == original_text
    assert page.best_text_source == original_source
    assert page.openai_ocr_text == sidecar_text
    assert page.meta["source_safe_ocr_merge"]["openai_sidecar_available"] is True


def test_multiview_openai_sidecar_generates_candidate_without_best_text_replacement() -> None:
    config = EngineConfig(
        source_safe_ocr_merge_enabled=True,
        multiview_text_candidates_enabled=True,
        suppress_low_information_candidates=False,
        loose_tfidf_threshold=0.55,
        tfidf_max_df=1.0,
    )
    left = make_page("A", "left.pdf", 1)
    right = make_page("B", "right.pdf", 1)
    left.openai_ocr_text = "case number ab-123456 hearing notice provider treatment determination benefit review"
    right.openai_ocr_text = "case number ab-123456 hearing notice provider treatment determination benefit review"
    left.openai_ocr_word_count = 9
    right.openai_ocr_word_count = 9
    left.openai_ocr_usable = True
    right.openai_ocr_usable = True

    matches = multipass_text_matches([left], [right], config)

    assert any(signal.name == "tfidf_openai_ocr_text_similarity" for match in matches for signal in match.signals)
    assert left.best_text_source == "none"
    assert right.best_text_source == "none"



def test_cross_view_native_to_openai_sidecar_generates_candidate() -> None:
    config = EngineConfig(
        multiview_text_candidates_enabled=True,
        multiview_cross_text_candidates_enabled=True,
        suppress_low_information_candidates=False,
        loose_tfidf_threshold=0.55,
        tfidf_max_df=1.0,
    )
    left = make_page("A", "native.pdf", 1, "case ab-900 appeal hearing provider treatment determination benefit review")
    right = make_page("B", "scan.pdf", 1)
    right.openai_ocr_text = "case ab-900 appeal hearing provider treatment determination benefit review"
    right.openai_ocr_word_count = 8
    right.openai_ocr_usable = True

    matches = multipass_text_matches([left], [right], config)

    assert any(
        signal.name == "tfidf_native_text_x_openai_ocr_text_similarity"
        for match in matches
        for signal in match.signals
    )


def test_rare_token_blocking_generates_source_safe_candidate() -> None:
    config = EngineConfig(
        suppress_low_information_candidates=False,
        rare_token_min_overlap=2,
        rare_token_min_jaccard=0.10,
        rare_token_max_df=10,
    )
    left = make_page("A", "left.pdf", 1, "appeal zx9912 cardiology alfaxolone benefit hearing determination")
    right = make_page("B", "right.pdf", 1)
    right.openai_ocr_text = "appeal zx9912 cardiology alfaxolone benefit hearing determination"
    right.openai_ocr_usable = True
    right.openai_ocr_word_count = 7

    matches = rare_token_block_matches([left], [right], config)

    assert len(matches) == 1
    assert matches[0].match_type == "rare_token_candidate"
    assert matches[0].signals[0].name == "rare_source_token_overlap"

def test_sequence_neighbor_promotion_uses_strong_anchor_and_adjacent_support() -> None:
    config = EngineConfig(sequence_neighbor_window=1, sequence_min_text_similarity=0.30, suppress_low_information_candidates=False)
    a1 = make_page("A", "bundle_a.pdf", 1, "exact anchor medication plan assessment followup provider treatment")
    b1 = make_page("B", "bundle_b.pdf", 1, "exact anchor medication plan assessment followup provider treatment")
    a2 = make_page("A", "bundle_a.pdf", 2, "discharge summary medication plan physical therapy restrictions")
    b2 = make_page("B", "bundle_b.pdf", 2, "therapy medication plan discharge instructions restrictions")
    anchor = PageMatch(
        match_type="exact_text_duplicate",
        confidence=0.99,
        page_a=a1,
        page_b=b1,
        signals=[MatchSignal("exact_normalized_text_hash", 1.0)],
        candidate_stage="deterministic_exact",
    )

    matches = sequence_neighbor_matches([anchor], [a1, a2], [b1, b2], config)

    assert len(matches) == 1
    assert matches[0].match_type == "sequence_neighbor_candidate"
    assert matches[0].page_a is a2
    assert matches[0].page_b is b2


def test_ocr_ready_but_not_candidate_generated_diagnostic() -> None:
    left = make_page("A", "left.pdf", 1)
    right = make_page("B", "right.pdf", 1)
    left.openai_ocr_text = "case number ab-123456 treatment provider determination review hearing notice"
    right.openai_ocr_text = "case number ab-123456 treatment provider determination review hearing notice"
    left.openai_ocr_word_count = 8
    right.openai_ocr_word_count = 8
    left.openai_ocr_usable = True
    right.openai_ocr_usable = True
    truth = [
        TruthPair(
            a=TruthPageRef("left.pdf", 1),
            b=TruthPageRef("right.pdf", 1),
            label="duplicate",
            kind="ocr_sidecar",
        )
    ]

    report = build_ocr_validation_report([left, right], [], truth_pairs=truth)

    assert report["summary"]["ocr_ready_but_not_candidate_generated_count"] == 1
    assert len(report["ocr_ready_missed_candidate_rows"]) == 1
