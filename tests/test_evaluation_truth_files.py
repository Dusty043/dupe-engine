from __future__ import annotations

import json
from pathlib import Path

import pytest

from dupe_engine.evaluation import TruthFileError, load_truth_pairs


def test_load_truth_pairs_rejects_group_style_metadata(tmp_path: Path) -> None:
    truth_path = tmp_path / "ground_truth.json"
    truth_path.write_text(
        json.dumps(
            {
                "corpus_name": "example",
                "groups": {
                    "exact_duplicate": [
                        {"pdf_file": "a.pdf", "page_number": "1", "relation": "duplicate"},
                        {"pdf_file": "a.pdf", "page_number": "2", "relation": "duplicate"},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(TruthFileError, match="pair-level truth"):
        load_truth_pairs(truth_path)


def test_load_truth_pairs_requires_known_truth_buckets(tmp_path: Path) -> None:
    truth_path = tmp_path / "empty_truth.json"
    truth_path.write_text(json.dumps({"pairs": []}), encoding="utf-8")

    with pytest.raises(TruthFileError, match="Expected a JSON file"):
        load_truth_pairs(truth_path)


def test_load_truth_pairs_accepts_pair_truth_buckets(tmp_path: Path) -> None:
    truth_path = tmp_path / "pairs.json"
    truth_path.write_text(
        json.dumps(
            {
                "must_match": [
                    {
                        "a": {"document": "a.pdf", "page": 1},
                        "b": {"document": "b.pdf", "page": 2},
                        "type": "exact",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    pairs = load_truth_pairs(truth_path)

    assert len(pairs) == 1
    assert pairs[0].label == "duplicate"
    assert pairs[0].kind == "exact"

from dupe_engine.evaluation import resolve_truth_context


def test_resolve_truth_context_skips_missing_auto_truth(tmp_path: Path) -> None:
    context = resolve_truth_context(search_roots=[tmp_path / "pdfs"])

    assert context.available is False
    assert context.status == "not_found"
    assert context.source == "auto_detect"


def test_resolve_truth_context_auto_detects_valid_pair_truth(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "corpus" / "pdfs"
    pdf_dir.mkdir(parents=True)
    truth_path = tmp_path / "corpus" / "truth_pairs.json"
    truth_path.write_text(
        json.dumps(
            {
                "must_match": [
                    {
                        "a": {"document": "a.pdf", "page": 1},
                        "b": {"document": "b.pdf", "page": 1},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    context = resolve_truth_context(search_roots=[pdf_dir])

    assert context.available is True
    assert context.source == "auto_detected"
    assert context.path == truth_path
    assert len(context.pairs or []) == 1


def test_resolve_truth_context_can_disable_auto_detection(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "corpus" / "pdfs"
    pdf_dir.mkdir(parents=True)
    truth_path = tmp_path / "corpus" / "truth_pairs.json"
    truth_path.write_text(
        json.dumps(
            {
                "must_match": [
                    {
                        "a": {"document": "a.pdf", "page": 1},
                        "b": {"document": "b.pdf", "page": 1},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    context = resolve_truth_context(search_roots=[pdf_dir], auto_detect=False)

    assert context.available is False
    assert context.status == "disabled"
    assert context.source == "disabled"
    assert context.path is None


def test_load_truth_pairs_accepts_v3_pair_list(tmp_path: Path) -> None:
    truth_path = tmp_path / "synthetic_v3_truth_pairs.json"
    truth_path.write_text(
        json.dumps(
            [
                {
                    "pair_id": "v3_pair_1",
                    "left_file": "source_A/intake.pdf",
                    "left_page": 1,
                    "right_file": "source_B/intake.pdf",
                    "right_page": 1,
                    "truth_label": "likely_duplicate",
                    "expected_min_layer": "ocr",
                    "difficulty": "ocr_required",
                    "is_must_match": True,
                    "is_hard_negative": False,
                    "reason_tags": ["native_vs_scan"],
                    "notes": "Same content, one side scanned.",
                },
                {
                    "pair_id": "v3_pair_2",
                    "left_file": "source_A/intake.pdf",
                    "left_page": 2,
                    "right_file": "source_B/intake.pdf",
                    "right_page": 2,
                    "truth_label": "not_duplicate",
                    "expected_min_layer": "llm_adjudication",
                    "difficulty": "hard_negative",
                    "is_must_match": False,
                    "is_hard_negative": True,
                },
            ]
        ),
        encoding="utf-8",
    )

    pairs = load_truth_pairs(truth_path)

    assert len(pairs) == 2
    assert pairs[0].a.document == "source_A/intake.pdf"
    assert pairs[0].label == "duplicate"
    assert pairs[0].v3_truth_label == "likely_duplicate"
    assert pairs[0].expected_min_layer == "ocr"
    assert pairs[0].reason_tags == ["native_vs_scan"]
    assert pairs[1].label == "not_duplicate"
    assert pairs[1].is_hard_negative is True
