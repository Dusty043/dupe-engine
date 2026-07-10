"""AWS pilot orchestration tests.

Uses moto to stub SQS, S3, and DynamoDB — no live AWS required.
Tests verify the adapter modules, the worker loop, and the UI dispatch path.
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helper: set env vars for AWS mode and restore afterwards
# ---------------------------------------------------------------------------

class _AWSEnv:
    """Context manager that temporarily sets AWS pilot environment variables."""

    QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789/dupe-test"
    BUCKET = "dupe-test-bucket"
    TABLE = "dupe-test-jobs"
    REGION = "us-east-1"

    def __init__(self, *, sqs: bool = True, s3: bool = True, dynamo: bool = True):
        self._to_set: dict[str, str] = {}
        self._to_set["DUPE_AWS_REGION"] = self.REGION
        if sqs:
            self._to_set["DUPE_SQS_QUEUE_URL"] = self.QUEUE_URL
        if s3:
            self._to_set["DUPE_S3_BUCKET"] = self.BUCKET
        if dynamo:
            self._to_set["DUPE_DYNAMO_TABLE"] = self.TABLE
        self._saved: dict[str, str | None] = {}

    def __enter__(self):
        for key, value in self._to_set.items():
            self._saved[key] = os.environ.get(key)
            os.environ[key] = value
        return self

    def __exit__(self, *args):
        for key, saved in self._saved.items():
            if saved is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = saved


# ---------------------------------------------------------------------------
# 1. job_queue — local mode (no AWS)
# ---------------------------------------------------------------------------

class TestJobQueueLocalMode:
    def test_send_and_receive(self):
        from dupe_engine import job_queue
        assert not job_queue._aws_mode()

        message = {"job_id": "job_test_001", "input_prefix": "s3://b/input/job_test_001/"}
        receipt = job_queue.send_job(message)
        assert isinstance(receipt, str) and len(receipt) > 0

        result = job_queue.receive_job(wait_seconds=1)
        assert result is not None
        received_msg, received_receipt = result
        assert received_msg["job_id"] == "job_test_001"

    def test_delete_removes_from_store(self):
        from dupe_engine import job_queue
        job_queue.send_job({"job_id": "job_delete_test"})
        result = job_queue.receive_job(wait_seconds=1)
        assert result is not None
        _, receipt_handle = result
        job_queue.delete_job(receipt_handle)
        # After deletion the receipt handle should be gone
        assert receipt_handle not in job_queue._local_receipts

    def test_receive_returns_none_when_empty(self):
        from dupe_engine import job_queue
        # Drain any leftovers first
        while job_queue.receive_job(wait_seconds=0) is not None:
            pass
        result = job_queue.receive_job(wait_seconds=0)
        assert result is None

    def test_extend_visibility_noop_in_local_mode(self):
        from dupe_engine import job_queue
        # Should not raise
        job_queue.extend_visibility("fake-receipt", 300)


# ---------------------------------------------------------------------------
# 2. job_queue — SQS message shape
# ---------------------------------------------------------------------------

class TestJobQueueMessageShape:
    def test_required_fields_present(self):
        from dupe_engine import job_queue
        message = {
            "job_id": "job_shape_001",
            "input_prefix": "s3://bucket/input/job_shape_001/",
            "output_prefix": "s3://bucket/runs/job_shape_001/",
            "engine_version": "v0.10.9",
            "config": {
                "embedding_reranker_enabled": True,
                "embedding_reranker_min_confidence": 0.80,
                "embedding_reranker_ocr_penalty": 0.01,
                "embedding_reranker_same_doc_bonus": 0.03,
                "embedding_reranker_tesseract_bonus": 0.02,
                "embedding_reranker_action": "demote",
            },
        }
        receipt = job_queue.send_job(message)
        result = job_queue.receive_job(wait_seconds=1)
        assert result is not None
        received, _ = result
        assert received["job_id"] == "job_shape_001"
        assert received["engine_version"] == "v0.10.9"
        assert "config" in received
        assert received["config"]["embedding_reranker_min_confidence"] == 0.80


# ---------------------------------------------------------------------------
# 3. artifact_store — local mode
# ---------------------------------------------------------------------------

class TestArtifactStoreLocalMode:
    def test_upload_and_download_file(self, tmp_path):
        from dupe_engine import artifact_store
        assert not artifact_store._aws_mode()

        src = tmp_path / "test.txt"
        src.write_text("hello artifact", encoding="utf-8")

        dest_uri = "s3://test-bucket/runs/job_x/test.txt"
        artifact_store.upload_file(src, dest_uri)

        dl_dest = tmp_path / "downloaded.txt"
        artifact_store.download_file(dest_uri, dl_dest)
        assert dl_dest.read_text(encoding="utf-8") == "hello artifact"

    def test_upload_dir_and_download_prefix(self, tmp_path):
        from dupe_engine import artifact_store

        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "run_manifest.json").write_text('{"v": 1}', encoding="utf-8")
        (run_dir / "sub").mkdir()
        (run_dir / "sub" / "page.png").write_bytes(b"\x89PNG")

        s3_prefix = "s3://test-bucket/runs/job_upload_dir/"
        uploaded = artifact_store.upload_dir(run_dir, s3_prefix)
        assert len(uploaded) == 2

        dl_dir = tmp_path / "downloaded"
        paths = artifact_store.download_prefix(s3_prefix, dl_dir)
        assert len(paths) == 2
        assert (dl_dir / "run_manifest.json").exists()
        assert (dl_dir / "sub" / "page.png").exists()

    def test_two_jobs_use_separate_s3_prefixes(self):
        from dupe_engine import artifact_store
        with _AWSEnv(sqs=False, s3=True, dynamo=False):
            prefix_a = artifact_store.make_input_prefix("job_aaa")
            prefix_b = artifact_store.make_input_prefix("job_bbb")
            assert prefix_a != prefix_b
            assert "job_aaa" in prefix_a
            assert "job_bbb" in prefix_b

    def test_output_prefix_contains_job_id(self):
        from dupe_engine import artifact_store
        with _AWSEnv(sqs=False, s3=True, dynamo=False):
            prefix = artifact_store.make_output_prefix("job_out_001")
            assert "job_out_001" in prefix
            assert prefix.startswith("s3://")


# ---------------------------------------------------------------------------
# 4. job_status — local file-based mode
# ---------------------------------------------------------------------------

class TestJobStatusLocalMode:
    def test_put_and_get(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DUPE_LOCAL_STATUS_DIR", str(tmp_path / "status"))
        from dupe_engine import job_status
        assert not job_status._aws_mode()

        record = {
            "job_id": "job_status_001",
            "status": "queued",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        job_status.put_job(record)
        retrieved = job_status.get_job("job_status_001")
        assert retrieved is not None
        assert retrieved["status"] == "queued"

    def test_update_job(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DUPE_LOCAL_STATUS_DIR", str(tmp_path / "status"))
        from dupe_engine import job_status

        job_status.put_job({"job_id": "job_update_001", "status": "queued", "created_at": "2026-01-01T00:00:00+00:00"})
        job_status.update_job("job_update_001", status="running")
        retrieved = job_status.get_job("job_update_001")
        assert retrieved["status"] == "running"

    def test_get_nonexistent_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DUPE_LOCAL_STATUS_DIR", str(tmp_path / "status"))
        from dupe_engine import job_status
        assert job_status.get_job("nonexistent_job") is None

    def test_list_jobs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DUPE_LOCAL_STATUS_DIR", str(tmp_path / "status"))
        from dupe_engine import job_status

        for i in range(3):
            job_status.put_job({
                "job_id": f"job_list_{i:03d}",
                "status": "queued",
                "created_at": f"2026-01-0{i + 1}T00:00:00+00:00",
            })
        jobs = job_status.list_jobs()
        assert len(jobs) == 3

    def test_get_job_converts_dynamo_decimal_to_json_safe_numbers(self, monkeypatch):
        """Regression: DynamoDB returns Decimal for numbers; get_job() must
        hand back plain int/float or downstream json.dumps() raises TypeError."""
        from decimal import Decimal
        from dupe_engine import job_status

        with _AWSEnv(sqs=False, s3=False, dynamo=True):
            fake_table = MagicMock()
            fake_table.get_item.return_value = {
                "Item": {
                    "job_id": "job_decimal_001",
                    "status": "completed",
                    "pages_processed": Decimal("42"),
                    "match_count": Decimal("3"),
                    "confidence": Decimal("0.875"),
                }
            }
            fake_resource = MagicMock()
            fake_resource.Table.return_value = fake_table

            with patch("boto3.resource", return_value=fake_resource):
                record = job_status.get_job("job_decimal_001")

            assert record["pages_processed"] == 42
            assert isinstance(record["pages_processed"], int)
            assert record["confidence"] == 0.875
            assert isinstance(record["confidence"], float)
            json.dumps(record)  # must not raise TypeError

    def test_status_persists_across_instantiation(self, tmp_path, monkeypatch):
        """Status written in one module import is readable after module reload."""
        monkeypatch.setenv("DUPE_LOCAL_STATUS_DIR", str(tmp_path / "status"))
        from dupe_engine import job_status

        job_status.put_job({"job_id": "job_persist_001", "status": "completed", "created_at": "2026-01-01T00:00:00+00:00"})

        # Simulate reading from a fresh context by directly reading the file
        status_file = tmp_path / "status" / "job_persist_001.json"
        assert status_file.exists()
        data = json.loads(status_file.read_text(encoding="utf-8"))
        assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# 5. log — structured output
# ---------------------------------------------------------------------------

class TestLog:
    def test_emits_valid_json(self, capsys):
        from dupe_engine.log import log
        log("info", "test_event", job_id="job_log_001", count=42)
        out = capsys.readouterr().out.strip()
        record = json.loads(out)
        assert record["level"] == "info"
        assert record["event"] == "test_event"
        assert record["job_id"] == "job_log_001"
        assert record["count"] == 42
        assert "ts" in record

    def test_redacts_api_key(self, capsys):
        from dupe_engine.log import log
        log("info", "should_redact", api_key="sk-secret123")
        out = capsys.readouterr().out.strip()
        record = json.loads(out)
        assert record["api_key"] == "[REDACTED]"
        assert "sk-secret123" not in out

    def test_does_not_log_raw_text(self, capsys):
        from dupe_engine.log import log
        # Callers must not pass document content — verify the log helper just
        # passes through whatever field names are given (guard is at call site)
        log("info", "page_processed", job_id="job_log_002", page_count=5)
        out = capsys.readouterr().out.strip()
        record = json.loads(out)
        assert "page_count" in record


# ---------------------------------------------------------------------------
# 6. ReviewJobStore — local mode unchanged
# ---------------------------------------------------------------------------

class TestReviewJobStoreLocalMode:
    def test_create_get_update_list(self, tmp_path):
        from dupe_engine.review_ui_server import ReviewJobStore

        store = ReviewJobStore(workspace_dir=tmp_path / "ws")
        job_dir = tmp_path / "ws" / "job_local_001"
        job_dir.mkdir(parents=True)

        record = store.create_job_record(
            job_dir=job_dir,
            received_files=["a.pdf"],
            ere_files=["b.pdf"],
            settings={"dpi": 150},
        )
        assert record["status"] == "queued"
        assert record["job_id"] == "job_local_001"

        store.update_job("job_local_001", status="running")
        retrieved = store.get_job("job_local_001")
        assert retrieved["status"] == "running"

        jobs = store.list_jobs()
        assert any(j["job_id"] == "job_local_001" for j in jobs)

    def test_two_jobs_isolated(self, tmp_path):
        from dupe_engine.review_ui_server import ReviewJobStore

        store = ReviewJobStore(workspace_dir=tmp_path / "ws")
        for suffix in ["aaa", "bbb"]:
            job_dir = tmp_path / "ws" / f"job_{suffix}"
            job_dir.mkdir(parents=True)
            store.create_job_record(
                job_dir=job_dir,
                received_files=["x.pdf"],
                ere_files=["y.pdf"],
                settings={},
            )

        assert store.get_job("job_aaa")["job_id"] == "job_aaa"
        assert store.get_job("job_bbb")["job_id"] == "job_bbb"
        assert store.get_job("job_aaa")["job_dir"] != store.get_job("job_bbb")["job_dir"]


# ---------------------------------------------------------------------------
# 7. Worker — mark running/completed/failed
# ---------------------------------------------------------------------------

class TestWorkerJobLifecycle:
    def test_marks_running_then_completed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DUPE_LOCAL_STATUS_DIR", str(tmp_path / "status"))
        monkeypatch.setenv("DUPE_WORKER_WORKDIR", str(tmp_path / "work"))
        from dupe_engine import job_status, job_queue

        # Pre-create the job record
        job_status.put_job({
            "job_id": "job_worker_ok",
            "status": "queued",
            "created_at": "2026-01-01T00:00:00+00:00",
        })

        # Build a message and mock the engine
        message = {
            "job_id": "job_worker_ok",
            "input_prefix": "",
            "output_prefix": "",
            "engine_version": "v0.10.9",
            "config": {},
        }

        received_dir = tmp_path / "work" / "job_worker_ok" / "input" / "received_records"
        ere_dir = tmp_path / "work" / "job_worker_ok" / "input" / "ere_records"
        received_dir.mkdir(parents=True)
        ere_dir.mkdir(parents=True)
        (received_dir / "a.pdf").write_bytes(b"%PDF-1.4")
        (ere_dir / "b.pdf").write_bytes(b"%PDF-1.4")

        from dupe_engine import worker

        with patch.object(worker, "run_ab_compare") as mock_engine, \
             patch.object(worker, "write_ui_run_artifacts"), \
             patch.object(worker, "build_fallback_audit", return_value={"rows": []}), \
             patch.object(worker, "write_fallback_audit_json"), \
             patch.object(worker, "write_json"), \
             patch.object(worker, "build_report", return_value={"summary": {}}), \
             patch.object(worker, "build_capability_report", return_value=MagicMock(to_json=lambda: {})):

            mock_engine.return_value = ([], [], [])

            success = worker._process_job(message, "fake-receipt")

        assert success is True
        record = job_status.get_job("job_worker_ok")
        assert record["status"] == "succeeded"  # must match app.js's status vocabulary
        assert record["stage"] == "completed"

    def test_marks_failed_on_engine_exception(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DUPE_LOCAL_STATUS_DIR", str(tmp_path / "status"))
        monkeypatch.setenv("DUPE_WORKER_WORKDIR", str(tmp_path / "work"))
        from dupe_engine import job_status, worker

        job_status.put_job({
            "job_id": "job_worker_fail",
            "status": "queued",
            "created_at": "2026-01-01T00:00:00+00:00",
        })

        received_dir = tmp_path / "work" / "job_worker_fail" / "input" / "received_records"
        ere_dir = tmp_path / "work" / "job_worker_fail" / "input" / "ere_records"
        received_dir.mkdir(parents=True)
        ere_dir.mkdir(parents=True)
        (received_dir / "a.pdf").write_bytes(b"%PDF-1.4")
        (ere_dir / "b.pdf").write_bytes(b"%PDF-1.4")

        message = {
            "job_id": "job_worker_fail",
            "input_prefix": "",
            "output_prefix": "",
            "engine_version": "v0.10.9",
            "config": {},
        }

        with patch.object(worker, "run_ab_compare", side_effect=RuntimeError("engine boom")):
            success = worker._process_job(message, "fake-receipt")

        assert success is False
        record = job_status.get_job("job_worker_fail")
        assert record["status"] == "failed"
        assert "engine boom" in (record.get("error_message") or "")

    def test_does_not_delete_sqs_message_on_failure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DUPE_LOCAL_STATUS_DIR", str(tmp_path / "status"))
        monkeypatch.setenv("DUPE_WORKER_WORKDIR", str(tmp_path / "work"))
        from dupe_engine import job_status, job_queue, worker

        job_status.put_job({
            "job_id": "job_no_delete",
            "status": "queued",
            "created_at": "2026-01-01T00:00:00+00:00",
        })

        received_dir = tmp_path / "work" / "job_no_delete" / "input" / "received_records"
        ere_dir = tmp_path / "work" / "job_no_delete" / "input" / "ere_records"
        received_dir.mkdir(parents=True)
        ere_dir.mkdir(parents=True)
        (received_dir / "a.pdf").write_bytes(b"%PDF-1.4")
        (ere_dir / "b.pdf").write_bytes(b"%PDF-1.4")

        # Send a real message to the local queue and get its receipt
        message = {
            "job_id": "job_no_delete",
            "input_prefix": "",
            "output_prefix": "",
            "engine_version": "v0.10.9",
            "config": {},
        }
        job_queue.send_job(message)
        received = job_queue.receive_job(wait_seconds=1)
        assert received is not None
        _, receipt_handle = received

        delete_calls = []
        original_delete = job_queue.delete_job

        def track_delete(rh):
            delete_calls.append(rh)
            original_delete(rh)

        with patch.object(job_queue, "delete_job", side_effect=track_delete), \
             patch.object(worker, "run_ab_compare", side_effect=RuntimeError("fail")):
            worker._poll_once()

        # delete_job must NOT have been called
        assert receipt_handle not in delete_calls


# ---------------------------------------------------------------------------
# 8. /api/run/load — must fetch worker's S3 output before serving it
# ---------------------------------------------------------------------------

class TestRunLoadDownloadsS3Output(unittest.TestCase):
    """Regression: worker uploads run artifacts to S3 (output_prefix) but the
    review UI's /api/run/load only ever looked at a local path — which never
    existed for AWS-processed jobs, since the worker runs in a separate task.
    Reviewers saw 'No candidates in this queue' for every completed job."""

    def _post_run_load(self, store, job_id: str):
        from dupe_engine.review_ui_server import build_handler
        HandlerClass = build_handler(store=store, static_dir=Path("/nonexistent"), server_host="0.0.0.0")
        handler = HandlerClass.__new__(HandlerClass)
        body = json.dumps({"job_id": job_id}).encode("utf-8")
        handler.path = "/api/run/load"
        handler.command = "POST"
        handler.client_address = ("10.0.0.1", 12345)
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler._is_authenticated = lambda: True

        captured = {}

        def fake_send_json(payload, status=None):
            captured["payload"] = payload
            captured["status"] = status

        handler.send_json = fake_send_json
        handler.send_error_json = lambda status, message: captured.update(
            payload={"ok": False, "error": message}, status=status
        )
        handler.do_POST()
        return captured

    def test_downloads_output_prefix_when_run_dir_missing(self, tmp_path=None):
        import tempfile
        from dupe_engine.review_ui_server import REQUIRED_RUN_FILES, ReviewJobStore

        with tempfile.TemporaryDirectory() as workspace, _AWSEnv(sqs=False, s3=True, dynamo=False):
            store = ReviewJobStore(workspace_dir=Path(workspace))
            job_dir = Path(workspace) / "job_s3_run"
            job_dir.mkdir(parents=True)
            store.create_job_record(job_dir=job_dir, received_files=["a.pdf"], ere_files=["b.pdf"], settings={})
            store.update_job("job_s3_run", status="succeeded", stage="completed",
                              output_prefix="s3://dupe-test-bucket/runs/job_s3_run/")

            def fake_download_prefix(s3_prefix, local_dir):
                local_dir = Path(local_dir)
                local_dir.mkdir(parents=True, exist_ok=True)
                for name in REQUIRED_RUN_FILES:
                    (local_dir / name).write_text("{}" if name != "candidates.json" else "[]", encoding="utf-8")
                return [local_dir / name for name in REQUIRED_RUN_FILES]

            from dupe_engine import review_ui_server
            with patch.object(review_ui_server._artifact_store_module, "download_prefix",
                               side_effect=fake_download_prefix) as mock_download:
                result = self._post_run_load(store, "job_s3_run")

            mock_download.assert_called_once_with(
                "s3://dupe-test-bucket/runs/job_s3_run/", store.workspace_dir / "job_s3_run" / "run"
            )
            assert result["payload"].get("has_run") is True, result["payload"]

    def test_skips_download_when_run_dir_already_local(self):
        import tempfile
        from dupe_engine.review_ui_server import REQUIRED_RUN_FILES, ReviewJobStore

        with tempfile.TemporaryDirectory() as workspace, _AWSEnv(sqs=False, s3=True, dynamo=False):
            store = ReviewJobStore(workspace_dir=Path(workspace))
            job_dir = Path(workspace) / "job_local_cached"
            job_dir.mkdir(parents=True)
            store.create_job_record(job_dir=job_dir, received_files=["a.pdf"], ere_files=["b.pdf"], settings={})
            store.update_job("job_local_cached", status="succeeded", stage="completed",
                              output_prefix="s3://dupe-test-bucket/runs/job_local_cached/")

            run_dir = job_dir / "run"
            run_dir.mkdir()
            for name in REQUIRED_RUN_FILES:
                (run_dir / name).write_text("{}" if name != "candidates.json" else "[]", encoding="utf-8")

            from dupe_engine import review_ui_server
            with patch.object(review_ui_server._artifact_store_module, "download_prefix") as mock_download:
                result = self._post_run_load(store, "job_local_cached")

            mock_download.assert_not_called()
            assert result["payload"].get("has_run") is True, result["payload"]
