"""Tests for the automatic post-job healing bridge (worker_healing.py).

Covers the three contracts that matter for a feature that runs automatically
on every completed AWS job: it must skip cleanly when there's nothing to
fix, it must actually verify a fix when one's prescribed, and a failure
inside healing must never be visible to the caller (the job's own success
can't depend on this).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from dupe_engine.config import EngineConfig


def _write_results(workdir: Path, *, total_pages: int, main_review_count: int, ocr_selected: int) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "results.json").write_text(json.dumps({
        "summary": {
            "total_pages": total_pages,
            "candidate_count": main_review_count,
            "main_review_list_candidate_count": main_review_count,
            "openai_ocr_selected_pages": ocr_selected,
            "openai_ocr_max_pages_per_job": 50,
            "embedding_reranker": {"enabled": False, "evaluated": 0},
        },
        "capabilities": {"embeddings": {"used": False}},
    }), encoding="utf-8")


class TestApplyPrescription:
    def test_translates_reranker_flags_into_engine_config(self):
        from dupe_engine.worker_healing import _apply_prescription

        original = EngineConfig.from_env()
        assert original.embedding_reranker_enabled is False  # sanity: default is off

        healed = _apply_prescription(
            original, ["--embedding-reranker", "--embedding-reranker-action", "demote"]
        )

        assert healed.embedding_reranker_enabled is True
        assert healed.embedding_reranker_action == "demote"

    def test_preserves_unrelated_original_fields(self):
        from dataclasses import replace
        from dupe_engine.worker_healing import _apply_prescription

        original = replace(EngineConfig.from_env(), dpi=222)
        healed = _apply_prescription(original, ["--embedding-reranker"])

        assert healed.dpi == 222  # untouched by the prescription, must survive
        assert healed.embedding_reranker_enabled is True

    def test_no_op_when_prescription_matches_defaults(self):
        from dupe_engine.worker_healing import _apply_prescription

        original = EngineConfig.from_env()
        healed = _apply_prescription(original, [])

        assert healed == original


class TestHealthyJobSkipsHealing:
    def test_no_issues_writes_empty_prescription_and_stops(self, tmp_path):
        from dupe_engine import worker_healing

        workdir = tmp_path / "job"
        run_dir = workdir / "run"
        _write_results(workdir, total_pages=100, main_review_count=10, ocr_selected=90)

        with patch.object(worker_healing, "run_ab_compare") as mock_engine:
            worker_healing.run_post_job_heal(
                job_id="job_healthy",
                workdir=workdir,
                run_dir=run_dir,
                received_dir=tmp_path / "received",
                ere_dir=tmp_path / "ere",
                config=EngineConfig.from_env(),
            )

        mock_engine.assert_not_called()
        prescription = json.loads((run_dir / "heal_output" / "prescription.json").read_text())
        assert prescription["cli_args"] == []
        assert not (run_dir / "heal_output" / "heal_report.json").exists()


class TestOverloadedQueueTriggersHealedRerun:
    def test_prescribes_reranker_and_verifies_via_rerun(self, tmp_path):
        from dupe_engine import worker_healing

        workdir = tmp_path / "job"
        run_dir = workdir / "run"
        # queue_per_100 = 80/100*100 = 80, well above the 50 threshold
        _write_results(workdir, total_pages=100, main_review_count=80, ocr_selected=90)

        with patch.object(worker_healing, "run_ab_compare", return_value=([], [], [])) as mock_engine:
            worker_healing.run_post_job_heal(
                job_id="job_overloaded",
                workdir=workdir,
                run_dir=run_dir,
                received_dir=tmp_path / "received",
                ere_dir=tmp_path / "ere",
                config=EngineConfig.from_env(),
            )

        mock_engine.assert_called_once()
        heal_out = run_dir / "heal_output"
        prescription = json.loads((heal_out / "prescription.json").read_text())
        assert "--embedding-reranker" in prescription["cli_args"]
        assert "queue_overload" in prescription["issues_addressed"]

        report = json.loads((heal_out / "heal_report.json").read_text())
        assert report["status"] in {"HEALED", "IMPROVED", "RESISTANT"}
        assert (heal_out / "healed" / "results.json").exists()


class TestHealingFailureNeverPropagates:
    def test_missing_results_json_does_not_raise(self, tmp_path):
        from dupe_engine import worker_healing

        workdir = tmp_path / "job_no_results"  # deliberately never written
        run_dir = workdir / "run"

        worker_healing.run_post_job_heal(
            job_id="job_broken",
            workdir=workdir,
            run_dir=run_dir,
            received_dir=tmp_path / "received",
            ere_dir=tmp_path / "ere",
            config=EngineConfig.from_env(),
        )  # must not raise

    def test_engine_exception_during_apply_does_not_raise(self, tmp_path):
        from dupe_engine import worker_healing

        workdir = tmp_path / "job"
        run_dir = workdir / "run"
        _write_results(workdir, total_pages=100, main_review_count=80, ocr_selected=90)

        with patch.object(worker_healing, "run_ab_compare", side_effect=RuntimeError("engine blew up")):
            worker_healing.run_post_job_heal(
                job_id="job_apply_fails",
                workdir=workdir,
                run_dir=run_dir,
                received_dir=tmp_path / "received",
                ere_dir=tmp_path / "ere",
                config=EngineConfig.from_env(),
            )  # must not raise despite the engine failing mid-heal
