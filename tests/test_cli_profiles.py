from __future__ import annotations

import argparse

from dupe_engine.cli import build_config


def test_openai_ocr_live_flag_overrides_env_dry_run(monkeypatch) -> None:
    monkeypatch.setenv("DUPE_OPENAI_OCR_DRY_RUN", "true")
    args = argparse.Namespace(openai_ocr_live=True)

    config = build_config(args)

    assert config.openai_ocr_dry_run is False


def test_openai_ocr_is_enabled_and_required_by_default(monkeypatch) -> None:
    monkeypatch.delenv("DUPE_OPENAI_API_KEY", raising=False)
    args = argparse.Namespace()

    config = build_config(args)

    assert config.enable_openai_ocr is True
    assert config.require_openai_ocr is True
    assert config.openai_ocr_dry_run is False


def test_openai_ocr_selection_mode_cli_override(monkeypatch) -> None:
    import argparse
    monkeypatch.delenv("DUPE_OPENAI_OCR_SELECTION_MODE", raising=False)
    args = argparse.Namespace(openai_ocr_selection_mode="weak_pages", openai_ocr_exclude_low_info=True)
    config = build_config(args)
    assert config.openai_ocr_selection_mode == "weak_pages"
    assert config.openai_ocr_allow_low_information_pages is False
